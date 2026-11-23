"""Machine API tests: all data lives in conftest's temporary SQLite database."""

import io
import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import app as wine_app
from wine_api import MAX_BODY


TOKEN = "test-only-credential-with-at-least-32-characters"
BASE = "/api/v1/wines"
NOTE = "black pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setitem(wine_app.HA_OPTIONS, "wine_api_token", TOKEN)


def headers(key="operation-0001"):
    return {"X-Wine-API-Key": TOKEN, "Idempotency-Key": key}


def snapshot(db):
    return {table: [tuple(r) for r in db.execute(f"SELECT * FROM {table}")]
            for table in ("wines", "timeline", "api_requests")}


@pytest.mark.parametrize("method,path,body", [
    ("POST", BASE, {"name": "Unauthorized"}),
    ("PATCH", BASE + "/1", {"notes": "Unauthorized"}),
    ("POST", BASE + "/1/stock", {"delta": -1}),
    ("GET", BASE + "/1", None),
])
@pytest.mark.parametrize("credential", [None, "wrong-credential-with-more-than-32-characters"])
def test_all_routes_require_token(client, db, sample_wine, enabled, method, path, body, credential):
    before = snapshot(db)
    supplied = {"Idempotency-Key": "untrusted-0001", "X-Ingress-Path": "/trusted",
                "X-Remote-User-Id": "admin", "X-Forwarded-For": "172.30.32.2"}
    if credential:
        supplied["X-Wine-API-Key"] = credential
    response = client.open(path, method=method, json=body, headers=supplied)
    assert response.status_code == 401
    assert response.get_json() == {"ok": False, "error": "unauthorized"}
    assert snapshot(db) == before


@pytest.mark.parametrize("configured", ["", "short", " " * 40, "é" * 40, None])
def test_disabled_fails_closed(client, db, monkeypatch, configured):
    monkeypatch.setitem(wine_app.HA_OPTIONS, "wine_api_token", configured)
    before = snapshot(db)
    response = client.post(BASE, json={"name": "Test"}, headers=headers())
    assert response.status_code == 503
    assert response.json["error"] == "api_disabled"
    assert snapshot(db) == before


def test_session_cannot_replace_token(client, enabled, monkeypatch):
    monkeypatch.setattr(wine_app, "AUTH_ENABLED", True)
    with client.session_transaction() as session:
        session.update(user="admin", role="admin")
    assert client.post(BASE, json={"name": "Test"}).status_code == 401


def test_token_scope_and_standalone_auth(client, enabled, monkeypatch):
    monkeypatch.setattr(wine_app, "AUTH_ENABLED", True)
    response = client.post(BASE, json={"name": "Test"}, headers=headers())
    assert response.status_code == 201
    assert client.get(BASE + "/1", headers=headers()).status_code == 200
    # The credential grants no access to browser routes/settings/old APIs.
    assert client.get("/api/ai-settings", headers=headers()).status_code == 401
    assert client.get("/api/wine/1", headers=headers()).status_code == 401
    assert client.post("/add", data={"name": "Test"}, headers=headers()).status_code == 302
    with client.session_transaction() as session:
        session.update(user="viewer", role="readonly")
    for method, path, body in [("POST", BASE, {"name": "Other"}),
                               ("PATCH", BASE + "/1", {"notes": "Test"}),
                               ("POST", BASE + "/1/stock", {"delta": 1})]:
        assert client.open(path, method=method, json=body, headers=headers()).status_code == 403


def test_create_all_fields_and_replay(client, db, enabled):
    payload = {"name": "The Prize Shiraz", "producer": "The Black Pig", "year": 2023,
               "type": "Rotwein", "region": "South Australia", "grape": "Shiraz",
               "quantity": 6, "drink_from": 2024, "drink_until": 2030,
               "notes": "Classic Cellar commentary", "rating": 4, "price": 12.5,
               "purchased_at": "Cellar", "location": "Rack A", "bottle_format": 0.75,
               "alcohol_pct": 14.5, "vivino_id": 1234,
               "taste_profile": {"body": 4}, "food_pairings": ["Steak"],
               "maturity_data": {"peak": [2025, 2028]}}
    response = client.post(BASE, json=payload, headers=headers())
    assert response.status_code == 201
    wine = response.json["wine"]
    for key, value in payload.items():
        assert wine[key] == value
    assert wine["image"] is None
    replay = client.post(BASE, json=dict(reversed(list(payload.items()))), headers=headers())
    assert replay.status_code == 201
    assert replay.json == response.json
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(db.execute("SELECT * FROM wines").fetchall()) == 1
    event = db.execute("SELECT * FROM timeline").fetchone()
    assert (event["action"], event["quantity"]) == ("added", 6)


def test_duplicate_normalization_and_vintage(client, db, enabled):
    payload = {"name": "Château Test", "producer": "Domaine Test", "year": 2023}
    assert client.post(BASE, json=payload, headers=headers()).status_code == 201
    duplicate = {**payload, "name": "  CHA\u0302TEAU  TEST ", "producer": "domaine test"}
    before = snapshot(db)
    response = client.post(BASE, json=duplicate, headers=headers("operation-0002"))
    assert response.status_code == 409
    assert response.json["error"] == "duplicate_wine"
    assert snapshot(db) == before
    assert client.post(BASE, json={**payload, "year": 2024}, headers=headers("operation-0003")).status_code == 201
    assert client.patch(BASE + "/2", json={"year": 2023}, headers=headers("operation-0004")).status_code == 409


@pytest.mark.parametrize("payload", [
    {}, {"name": ""}, {"name": 3}, {"name": "a" * 513}, {"name": "Test", "extra": 1},
    {"name": "Test", "image": "../../secret"}, {"name": "Test", "quantity": -1},
    {"name": "Test", "quantity": True}, {"name": "Test", "quantity": 1.5},
    {"name": "Test", "year": "2023"}, {"name": "Test", "year": 0},
    {"name": "Test", "year": 2**100}, {"name": "Test", "rating": 6},
    {"name": "Test", "price": -1}, {"name": "Test", "price": float("inf")},
    {"name": "Test", "alcohol_pct": 101}, {"name": "Test", "bottle_format": 0},
    {"name": "Test", "notes": None}, {"name": "Test", "type": "unknown"},
    {"name": "Test", "drink_from": 2030, "drink_until": 2020},
    {"name": "Test", "food_pairings": [123]},
    {"name": "Test", "taste_profile": {"body": 6}},
    {"name": "Test", "maturity_data": {"peak": [2030, 2020]}},
])
def test_invalid_create_is_atomic(client, db, enabled, payload):
    before = snapshot(db)
    response = client.post(BASE, json=payload, headers=headers())
    assert response.status_code == 400
    assert snapshot(db) == before


@pytest.mark.parametrize("body", ["{", "null", "[]", '"text"',
                                   '{"name":"A","name":"B"}',
                                   '{"name":"\\ud800"}', '{"name":"A","price":NaN}',
                                   "[" * 2000 + "]" * 2000])
def test_malformed_json(client, db, enabled, body):
    before = snapshot(db)
    assert client.post(BASE, data=body, content_type="application/json", headers=headers()).status_code == 400
    assert snapshot(db) == before


def test_body_and_key_limits(client, db, enabled):
    before = snapshot(db)
    assert client.post(BASE, data={"name": "Test"}, headers=headers()).status_code == 415
    assert client.post(BASE, data=" " * (MAX_BODY + 1), content_type="application/json", headers=headers()).status_code == 413
    for key in ("", "short", "a" * 129, "contains spaces"):
        assert client.post(BASE, json={"name": "Test"}, headers=headers(key)).status_code == 400
    assert snapshot(db) == before


def test_black_pig_consumption_and_notes_are_atomic(client, db, enabled):
    # Illustrative wine ID 25 exists only in this temporary test database.
    db.execute("INSERT INTO wines (id, name, producer, year, quantity, notes, image) VALUES (25,?,?,?,?,?,?)",
               ("The Prize Shiraz", "The Black Pig", 2023, 6, "Classic Cellar commentary", "existing.jpg"))
    db.commit()
    before = dict(db.execute("SELECT * FROM wines WHERE id=25").fetchone())
    response = client.post(BASE + "/25/stock", json={"delta": -1, "notes": NOTE}, headers=headers())
    assert response.status_code == 200
    after = response.json["wine"]
    assert after["quantity"] == 5
    assert after["notes"] == "Classic Cellar commentary\n\n" + NOTE
    for field in before.keys() - {"quantity", "notes"}:
        assert after[field] == before[field]
    event = db.execute("SELECT * FROM timeline").fetchone()
    assert (event["wine_id"], event["action"], event["quantity"]) == (25, "consumed", 1)
    assert client.get(BASE + "/25", headers=headers()).json["wine"] == after
    # Exact retry, including the note, changes nothing a second time.
    replay = client.post(BASE + "/25/stock", json={"delta": -1, "notes": NOTE}, headers=headers())
    assert replay.json == response.json
    assert len(db.execute("SELECT * FROM timeline").fetchall()) == 1


def test_patch_preserves_fields_and_appends_exact_prose(client, sample_wine, enabled):
    original = sample_wine["wine"]
    path = BASE + f"/{original['id']}"
    note = "  Lovely — it’s ready!\nÀ votre santé.  "
    response = client.patch(path, json={"notes": note, "rating": 5, "drink_until": 2035}, headers=headers())
    assert response.status_code == 200
    after = response.json["wine"]
    assert after["notes"] == original["notes"] + "\n\n" + note
    for field in original.keys() - {"notes", "rating", "drink_until"}:
        assert after[field] == original[field]
    assert after["rating"] == 5 and after["drink_until"] == 2035
    replaced = client.patch(path, json={"notes": "Replacement", "notes_mode": "replace"}, headers=headers("operation-0002"))
    assert replaced.json["wine"]["notes"] == "Replacement"
    cleared = client.patch(path, json={"notes": "", "notes_mode": "replace", "grape": None}, headers=headers("operation-0003"))
    assert cleared.json["wine"]["notes"] == ""
    assert cleared.json["wine"]["grape"] is None


@pytest.mark.parametrize("payload", [{}, {"quantity": 20}, {"id": 4}, {"added": "2000-01-01"},
                                     {"notes_mode": "replace"}, {"notes": "x", "notes_mode": "unknown"},
                                     {"notes": ""}, {"drink_from": 2031}, {"name": None}])
def test_invalid_patch_preserves_everything(client, db, sample_wine, enabled, payload):
    before = snapshot(db)
    response = client.patch(BASE + f"/{sample_wine['wine']['id']}", json=payload, headers=headers())
    assert response.status_code == 400
    assert snapshot(db) == before


def test_zero_stock_and_restock(client, db, sample_wine, enabled):
    path = BASE + f"/{sample_wine['wine']['id']}/stock"
    response = client.post(path, json={"delta": -3}, headers=headers())
    assert response.json["wine"]["quantity"] == 0
    assert db.execute("SELECT COUNT(*) FROM wines").fetchone()[0] == 1
    before = snapshot(db)
    assert client.post(path, json={"delta": -1, "notes": NOTE}, headers=headers("operation-0002")).status_code == 409
    assert snapshot(db) == before
    response = client.post(path, json={"delta": 2}, headers=headers("operation-0003"))
    assert response.json["wine"]["quantity"] == 2
    events = db.execute("SELECT action, quantity FROM timeline ORDER BY id").fetchall()
    assert [tuple(e) for e in events] == [("added", 3), ("consumed", 3), ("restocked", 2)]


@pytest.mark.parametrize("payload", [{"delta": 0}, {"delta": True}, {"delta": "1"}, {"delta": 0.5},
                                     {"delta": 1000001}, {"delta": 1, "quantity": 4},
                                     {"delta": 1, "notes_mode": "replace"}, {"delta": 1, "notes": None}])
def test_invalid_stock_is_atomic(client, db, sample_wine, enabled, payload):
    before = snapshot(db)
    response = client.post(BASE + f"/{sample_wine['wine']['id']}/stock", json=payload, headers=headers())
    assert response.status_code == 400
    assert snapshot(db) == before


def test_idempotency_conflict_restart_and_snapshot(client, app, db, sample_wine, enabled):
    wine_id = sample_wine["wine"]["id"]
    path = BASE + f"/{wine_id}/stock"
    first = client.post(path, json={"delta": -1}, headers=headers())
    before = snapshot(db)
    assert client.post(path, json={"delta": 1}, headers=headers()).status_code == 409
    assert client.patch(BASE + f"/{wine_id}", json={"notes": "x"}, headers=headers()).status_code == 409
    assert client.post(BASE + "/999/stock", json={"delta": -1}, headers=headers()).status_code == 409
    assert snapshot(db) == before
    # A new connection/client and schema initialization preserve the receipt.
    wine_app.init_db()
    other = app.test_client()
    assert other.post(path, json={"delta": 1}, headers=headers("operation-0002")).status_code == 200
    replay = other.post(path, json={"delta": -1}, headers=headers())
    assert replay.json == first.json  # original snapshot, not current state
    assert other.get(BASE + f"/{wine_id}", headers=headers()).json["wine"]["quantity"] == 3


def test_failure_rolls_back_wine_note_timeline_and_receipt(client, db, sample_wine, enabled):
    db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON api_requests BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    db.commit()
    before = snapshot(db)
    with pytest.raises(sqlite3.IntegrityError):
        client.post(BASE + f"/{sample_wine['wine']['id']}/stock", json={"delta": -1, "notes": NOTE}, headers=headers())
    assert snapshot(db) == before


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_last_bottle_and_retries(app, client, db, enabled, same_key):
    wine = client.post(BASE, json={"name": "Last bottle", "quantity": 1}, headers=headers("create-0001")).json["wine"]
    barrier = Barrier(2)

    def consume(index):
        with app.test_client() as other:
            barrier.wait(timeout=10)
            key = "consume-0001" if same_key else f"consume-000{index}"
            response = other.post(BASE + f"/{wine['id']}/stock", json={"delta": -1, "notes": NOTE}, headers=headers(key))
            return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, (1, 2)))
    assert sorted(status for status, _ in results) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert results[0][1] == results[1][1]
    row = db.execute("SELECT quantity, notes FROM wines").fetchone()
    assert tuple(row) == (0, NOTE)
    assert db.execute("SELECT COUNT(*) FROM timeline WHERE action='consumed'").fetchone()[0] == 1


@pytest.mark.parametrize("method,path,payload", [("GET", BASE + "/999", None),
                                                 ("PATCH", BASE + "/999", {"notes": "x"}),
                                                 ("POST", BASE + "/999/stock", {"delta": 1})])
def test_missing_wine(client, db, enabled, method, path, payload):
    before = snapshot(db)
    response = client.open(path, method=method, json=payload, headers=headers())
    assert response.status_code == 404
    assert snapshot(db) == before


def test_credentials_never_returned_or_stored(client, db, enabled, caplog, capsys):
    response = client.post(BASE, json={"name": "Test"}, headers=headers())
    settings = client.get("/api/ai-settings")
    assert response.headers["Cache-Control"] == "no-store"
    assert TOKEN not in response.get_data(as_text=True) + settings.get_data(as_text=True)
    assert TOKEN not in str(snapshot(db)) + caplog.text + str(capsys.readouterr())
    assert "operation-0001" not in str(snapshot(db))


def test_api_token_options_and_environment(tmp_path, monkeypatch):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"wine_api_token": TOKEN}))
    monkeypatch.setattr(wine_app, "OPTIONS_PATH", str(options))
    monkeypatch.delenv("WINE_API_TOKEN", raising=False)
    assert wine_app.load_options()["wine_api_token"] == TOKEN
    monkeypatch.setenv("WINE_API_TOKEN", "another-test-token-with-32-characters")
    assert wine_app.load_options()["wine_api_token"] == "another-test-token-with-32-characters"
    monkeypatch.setenv("WINE_API_TOKEN", "")
    assert wine_app.load_options()["wine_api_token"] == ""


def test_additive_migration_preserves_existing_data(app, db, sample_wine):
    before = snapshot(db)
    columns = [tuple(r) for r in db.execute("PRAGMA table_info(wines)")]
    db.execute("DROP TABLE api_requests")
    db.commit()
    wine_app.init_db()
    wine_app.init_db()
    assert snapshot(db) == before
    assert [tuple(r) for r in db.execute("PRAGMA table_info(wines)")] == columns


def test_concurrent_duplicate_creation(app, db, enabled):
    barrier = Barrier(2)

    def create(index):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            return client.post(BASE, json={"name": "Same wine"},
                               headers=headers(f"create-000{index}")).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, (1, 2))) == [201, 409]
    assert db.execute("SELECT COUNT(*) FROM wines").fetchone()[0] == 1


def test_patch_retry_does_not_append_twice(client, db, sample_wine, enabled):
    path = BASE + f"/{sample_wine['wine']['id']}"
    first = client.patch(path, json={"notes": NOTE}, headers=headers())
    before = snapshot(db)
    assert client.patch(path, json={"notes": NOTE}, headers=headers()).json == first.json
    assert snapshot(db) == before


def test_api_created_wine_appears_in_existing_backup(client, enabled):
    response = client.post(BASE, json={"name": "Backup wine", "notes": NOTE, "quantity": 6}, headers=headers())
    assert response.status_code == 201
    archive = client.get("/export")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.data)) as backup:
        assert json.loads(backup.read("wines.json"))[0]["notes"] == NOTE
        assert json.loads(backup.read("timeline.json"))[0]["quantity"] == 6
        assert "api_requests.json" not in backup.namelist()


def test_unknown_length_body_is_bounded(client, db, enabled):
    before = snapshot(db)
    response = client.post(BASE, headers=headers(), content_type="application/json",
                           environ_overrides={"wsgi.input": io.BytesIO(b" " * (MAX_BODY + 1)),
                                              "wsgi.input_terminated": True,
                                              "CONTENT_LENGTH": ""})
    assert response.status_code == 413
    assert snapshot(db) == before


def test_query_string_credentials_rejected(client, enabled):
    assert client.post(BASE + "?wine_api_token=" + TOKEN,
                       json={"name": "Test"}, headers={"Idempotency-Key": "query-0001"}).status_code == 401


def test_database_lock_returns_safe_retryable_error(client, db, sample_wine, enabled):
    db.execute("BEGIN IMMEDIATE")
    try:
        response = client.post(BASE + f"/{sample_wine['wine']['id']}/stock",
                               json={"delta": -1}, headers=headers())
        assert response.status_code == 503
        assert response.json == {"ok": False, "error": "database_unavailable"}
    finally:
        db.rollback()
    assert client.post(BASE + f"/{sample_wine['wine']['id']}/stock",
                       json={"delta": -1}, headers=headers()).json["wine"]["quantity"] == 2
