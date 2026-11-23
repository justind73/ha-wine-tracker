"""Scoped machine API. Existing browser routes keep their own authentication."""

import hashlib
import json
import math
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


MAX_BODY = 65536
MAX_QUANTITY = 1000000
TEXT_FIELDS = {"name", "producer", "type", "region", "grape", "notes",
               "purchased_at", "location"}
INTEGER_FIELDS = {"year": (1, 9999), "drink_from": (1, 9999),
                  "drink_until": (1, 9999), "rating": (0, 5),
                  "quantity": (0, MAX_QUANTITY), "vivino_id": (1, 2**63 - 1)}
NUMBER_FIELDS = {"price": (0, 1000000000), "bottle_format": (0.01, 100),
                 "alcohol_pct": (0, 100)}
JSON_FIELDS = {"maturity_data", "taste_profile", "food_pairings"}
FIELDS = TEXT_FIELDS | INTEGER_FIELDS.keys() | NUMBER_FIELDS.keys() | JSON_FIELDS
IDENTITY_FIELDS = {"name", "producer", "year", "bottle_format"}
REQUIRED_VALUES = {"name", "quantity", "rating", "bottle_format"}


class ApiError(Exception):
    def __init__(self, error, status=400):
        self.error = error
        self.status = status


def init_api_db(db):
    # One durable receipt per successful write, in the same transaction as the
    # wine and timeline changes. No changes to existing wine/timeline columns.
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_requests (
            key_hash TEXT PRIMARY KEY,
            request_hash TEXT NOT NULL,
            response TEXT NOT NULL,
            status INTEGER NOT NULL,
            created TEXT NOT NULL
        )
    """)


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _structured_field(key, value):
    if key == "food_pairings":
        return (isinstance(value, list) and len(value) <= 100
                and all(isinstance(v, str) and len(v) <= 512 for v in value))
    if not isinstance(value, dict):
        return False
    if key == "taste_profile":
        return (set(value) <= {"body", "tannin", "acidity", "sweetness"}
                and all(_integer(v, 1, 5) for v in value.values()))
    return (set(value) <= {"youth", "maturity", "peak", "decline"}
            and all(isinstance(v, list) and len(v) == 2
                    and all(_integer(y, 1, 9999) for y in v) and v[0] <= v[1]
                    for v in value.values()))


def validate_fields(payload, wine_types, creating=False):
    allowed = FIELDS if creating else FIELDS - {"quantity"}
    if not set(payload) <= allowed:
        raise ApiError("unknown_or_readonly_field")
    if not payload or (creating and "name" not in payload):
        raise ApiError("wine_fields_required")
    values = dict(payload)
    for key, value in values.items():
        if value is None:
            if key in REQUIRED_VALUES or key == "notes":
                raise ApiError("invalid_" + key)
            continue
        valid = True
        if key in TEXT_FIELDS:
            valid = isinstance(value, str) and len(value) <= (50000 if key == "notes" else 512)
            if valid and key != "notes":
                values[key] = value.strip()
            if valid and key == "name":
                valid = bool(values[key])
            if valid and key == "type":
                valid = value in wine_types
        elif key in INTEGER_FIELDS:
            valid = _integer(value, *INTEGER_FIELDS[key])
        elif key in NUMBER_FIELDS:
            low, high = NUMBER_FIELDS[key]
            valid = (type(value) in (int, float) and low <= value <= high
                     and math.isfinite(value))
        elif key in JSON_FIELDS:
            valid = _structured_field(key, value)
            if valid:
                values[key] = json.dumps(value, ensure_ascii=False)
        if not valid:
            raise ApiError("invalid_" + key)
    return values


def _check_window(values):
    start, end = values.get("drink_from"), values.get("drink_until")
    if start is not None and end is not None and start > end:
        raise ApiError("invalid_drinking_window")


def _identity(values):
    def normalize(value):
        return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())
    return (normalize(values.get("name")), normalize(values.get("producer")),
            values.get("year"), values.get("bottle_format") or 0.75)


def _check_duplicate(db, values, exclude_id=None):
    identity = _identity(values)
    for row in db.execute("SELECT id, name, producer, year, bottle_format FROM wines"):
        if row["id"] != exclude_id and _identity(dict(row)) == identity:
            raise ApiError("duplicate_wine", 409)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def _read_body():
    if not request.is_json:
        raise ApiError("json_content_type_required", 415)
    if request.content_length is not None and request.content_length > MAX_BODY:
        raise ApiError("request_too_large", 413)
    raw = request.stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ApiError("request_too_large", 413)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
        # Reject unpaired surrogate escapes before SQLite/UTF-8 encoding.
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise ApiError("invalid_json") from None
    if not isinstance(data, dict):
        raise ApiError("json_object_required")
    return data


def create_wine_api(get_db, wine_json, get_token, wine_types):
    api = Blueprint("wine_api", __name__, url_prefix="/api/v1")

    @api.before_request
    def authenticate():
        token = get_token()
        # No default credential; malformed/short configuration fails closed.
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise ApiError("api_disabled", 503)
        supplied = request.headers.get("X-Wine-API-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", supplied) or not secrets.compare_digest(token, supplied):
            raise ApiError("unauthorized", 401)

    @api.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.errorhandler(ApiError)
    def api_error(error):
        return jsonify(ok=False, error=error.error), error.status

    @api.errorhandler(BadRequest)
    def bad_request(error):
        return jsonify(ok=False, error="invalid_request"), 400

    @api.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(ok=False, error="request_too_large"), 413

    def log_stock(db, wine_id, action, quantity):
        db.execute("INSERT INTO timeline (wine_id, action, quantity, timestamp) VALUES (?,?,?,?)",
                   (wine_id, action, quantity, datetime.now().isoformat()))

    def change_fields(db, wine_id, payload):
        row = db.execute("SELECT * FROM wines WHERE id=?", (wine_id,)).fetchone()
        if row is None:
            raise ApiError("not_found", 404)
        original = dict(row)
        fields = dict(payload)
        mode = fields.pop("notes_mode", "append")
        if mode not in ("append", "replace") or ("notes_mode" in payload and "notes" not in fields):
            raise ApiError("invalid_notes_mode")
        values = validate_fields(fields, wine_types)
        if "notes" in values and mode == "append":
            if not values["notes"]:
                raise ApiError("empty_note")
            old = original["notes"] or ""
            values["notes"] = old + ("\n\n" if old else "") + values["notes"]
            if len(values["notes"]) > 50000:
                raise ApiError("invalid_notes")
        merged = {**original, **values}
        if {"drink_from", "drink_until"} & values.keys():
            _check_window(merged)
        if IDENTITY_FIELDS & values.keys():
            _check_duplicate(db, merged, wine_id)
        # Column names come only from validate_fields' allowlist.
        assignments = ", ".join(f"{key}=?" for key in values)
        db.execute(f"UPDATE wines SET {assignments} WHERE id=?", (*values.values(), wine_id))

    def write(operation, wine_id=None):
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ApiError("idempotency_key_required")
        payload = _read_body()
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        canonical = json.dumps([operation, wine_id, payload], sort_keys=True, ensure_ascii=False)
        request_hash = hashlib.sha256(canonical.encode()).hexdigest()
        db = get_db()
        try:
            # Lock before reading: concurrent writers cannot consume the same
            # last bottle or race a duplicate check/idempotency receipt.
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute("SELECT * FROM api_requests WHERE key_hash=?", (key_hash,)).fetchone()
            if receipt:
                if receipt["request_hash"] != request_hash:
                    raise ApiError("idempotency_conflict", 409)
                db.rollback()
                response = jsonify(json.loads(receipt["response"]))
                response.headers["Idempotency-Replayed"] = "true"
                return response, receipt["status"]

            status = 200
            if operation == "create":
                values = {"quantity": 1, "rating": 0, "bottle_format": 0.75,
                          **validate_fields(payload, wine_types, creating=True)}
                _check_window(values)
                _check_duplicate(db, values)
                values["added"] = date.today().isoformat()
                columns = ", ".join(values)
                placeholders = ", ".join("?" for _ in values)
                cursor = db.execute(f"INSERT INTO wines ({columns}) VALUES ({placeholders})", tuple(values.values()))
                wine_id = cursor.lastrowid
                log_stock(db, wine_id, "added", values["quantity"])
                status = 201
            elif operation == "update":
                change_fields(db, wine_id, payload)
            else:
                if not set(payload) <= {"delta", "notes", "notes_mode"}:
                    raise ApiError("unknown_or_readonly_field")
                delta = payload.get("delta")
                if not _integer(delta, -MAX_QUANTITY, MAX_QUANTITY) or delta == 0:
                    raise ApiError("invalid_delta")
                row = db.execute("SELECT quantity FROM wines WHERE id=?", (wine_id,)).fetchone()
                if row is None:
                    raise ApiError("not_found", 404)
                quantity = (row["quantity"] or 0) + delta
                if not 0 <= quantity <= MAX_QUANTITY:
                    raise ApiError("stock_out_of_range", 409)
                notes = {k: v for k, v in payload.items() if k != "delta"}
                if notes:
                    change_fields(db, wine_id, notes)
                db.execute("UPDATE wines SET quantity=? WHERE id=?", (quantity, wine_id))
                log_stock(db, wine_id, "consumed" if delta < 0 else "restocked", abs(delta))

            result = {"ok": True, "wine": wine_json(wine_id)}
            db.execute("INSERT INTO api_requests VALUES (?,?,?,?,?)",
                       (key_hash, request_hash, json.dumps(result, ensure_ascii=False),
                        status, datetime.now().isoformat()))
            db.commit()
            return jsonify(result), status
        except sqlite3.OperationalError:
            db.rollback()
            # Never return SQL, body, headers or credentials in error output.
            raise ApiError("database_unavailable", 503) from None
        except Exception:
            db.rollback()
            raise

    @api.post("/wines")
    def create():
        return write("create")

    @api.get("/wines/<int:wine_id>")
    def retrieve(wine_id):
        wine = wine_json(wine_id)
        if wine is None:
            raise ApiError("not_found", 404)
        return jsonify(ok=True, wine=wine)

    @api.patch("/wines/<int:wine_id>")
    def update(wine_id):
        return write("update", wine_id)

    @api.post("/wines/<int:wine_id>/stock")
    def stock(wine_id):
        return write("stock", wine_id)

    return api
