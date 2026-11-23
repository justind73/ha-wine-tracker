"""Exercise the documented HA templates against an isolated HTTP wine API.

This is not a substitute for HA Core configuration validation on installation.
"""

import hashlib
import io
import json
from pathlib import Path
import runpy
import threading
from urllib.parse import urlsplit
import zipfile

from jinja2 import Environment, StrictUndefined
import pytest
import requests
from werkzeug.serving import make_server
import yaml

import app as wine_app


ROOT = Path(__file__).resolve().parents[2]
TOKEN = "isolated-ha-template-test-token-32-characters"
NOTE = "black pig is easy drinking good value go to evening wine. It’s how I discovered i liked Syrah. - Justin"


@pytest.fixture
def package():
    class SecretLoader(yaml.SafeLoader):
        pass

    def secret(loader, node):
        assert loader.construct_scalar(node) == "wine_tracker_staging_api_token"
        return TOKEN

    SecretLoader.add_constructor("!secret", secret)
    return yaml.load((ROOT / "examples/home-assistant/wine_tracker_staging.yaml").read_text(encoding="utf-8"), Loader=SecretLoader)


def render(command, data):
    # HA's to_json serializes data, rather than interpolating it into JSON text.
    env = Environment(undefined=StrictUndefined)
    env.filters["to_json"] = lambda value: json.dumps(value, ensure_ascii=False)
    url = env.from_string(command["url"]).render(data)
    assert urlsplit(url).netloc == "local-wine-tracker-api-staging:5050"
    headers = {name: env.from_string(value).render(data) for name, value in command["headers"].items()}
    body = env.from_string(command["payload"]).render(data) if "payload" in command else None
    if "content_type" in command:
        headers["Content-Type"] = command["content_type"]
    return urlsplit(url).path, headers, body


@pytest.fixture
def endpoint(app, monkeypatch):
    monkeypatch.setitem(wine_app.HA_OPTIONS, "wine_api_token", TOKEN)
    monkeypatch.setattr(wine_app, "AUTH_ENABLED", True)
    monkeypatch.setattr(wine_app, "_USERS", {})
    # Bind loopback on an OS-assigned port; never contact an HA instance.
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with requests.Session() as session:
        session.trust_env = False

        def call(method, path, **kwargs):
            return session.request(method, f"http://127.0.0.1:{server.server_port}" + path,
                                   timeout=10, allow_redirects=False, **kwargs)

        yield call
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def test_ha_package_black_pig_http_roundtrip(package, endpoint, db):
    def call(name, data):
        assert TOKEN not in json.dumps(data)
        command = package["rest_command"]["wine_tracker_staging_" + name]
        path, headers, body = render(command, data)
        response = endpoint(command["method"], path, headers=headers,
                            data=body.encode("utf-8") if body is not None else None)
        assert TOKEN not in response.text + str(dict(response.headers))
        return response

    created = call("add", {"request_id": "staging-black-pig-create-001", "wine": {
        "producer": "The Black Pig", "name": "The Prize Shiraz", "year": 2023,
        "quantity": 6, "price": 12.5, "notes": "Classic Cellar commentary"}})
    assert created.status_code == 201
    wine_id = created.json()["wine"]["id"]
    operation = {"wine_id": wine_id, "request_id": "staging-black-pig-consume-001",
                 "change": {"delta": -1, "notes": NOTE}}
    consumed = call("stock", operation)
    assert consumed.status_code == 200
    assert consumed.json()["wine"]["quantity"] == 5
    replay = call("stock", operation)
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == consumed.json()
    verified = call("get", {"wine_id": wine_id})
    assert verified.json()["wine"]["quantity"] == 5
    assert verified.json()["wine"]["notes"] == "Classic Cellar commentary\n\n" + NOTE
    assert db.execute("SELECT COUNT(*) FROM timeline WHERE action='consumed'").fetchone()[0] == 1
    assert call("stock", {**operation, "change": {"delta": -2}}).status_code == 409
    restocked = call("stock", {"wine_id": wine_id, "request_id": "staging-restock-001", "change": {"delta": 2}})
    assert restocked.json()["wine"]["quantity"] == 7
    note = 'A "quoted" note.\nIt’s ready — {{ not_a_template }}.'
    patched = call("update", {"wine_id": wine_id, "request_id": "staging-update-001", "changes": {"notes": note}})
    assert patched.json()["wine"]["notes"].endswith("\n\n" + note)
    replaced = call("update", {"wine_id": wine_id, "request_id": "staging-replace-001",
                               "changes": {"notes": note, "notes_mode": "replace"}})
    assert replaced.json()["wine"]["notes"] == note
    assert replaced.json()["wine"]["price"] == 12.5


@pytest.mark.parametrize("wine_id", ["../edit/1", "https://evil.invalid/", "1?x=y", 1.5, True, None, -1])
def test_ha_template_cannot_redirect_credentials(package, wine_id):
    for action in ("get", "stock", "update"):
        path, headers, body = render(package["rest_command"]["wine_tracker_staging_" + action], {
            "wine_id": wine_id, "request_id": "test-operation-001", "change": {"delta": 1},
            "changes": {"notes": "Test"}, "url": "https://evil.invalid/", "headers": {"X-Wine-API-Key": "override"}})
        assert path in ("/api/v1/wines/0", "/api/v1/wines/0/stock")
        assert headers["X-Wine-API-Key"] == TOKEN


def test_ha_package_requires_key_and_disables_secret_logging(package):
    assert package["logger"]["logs"]["homeassistant.components.rest_command"] == "warning"
    command = package["rest_command"]["wine_tracker_staging_add"]
    with pytest.raises(Exception, match="request_id"):
        render(command, {"wine": {"name": "Test"}})


def test_staging_blocks_legacy_writes_even_with_spoofed_ingress(endpoint, db):
    headers = {"X-Ingress-Path": "/api/hassio_ingress/fake", "X-Remote-User-Id": "admin",
               "X-Wine-API-Key": TOKEN}
    for path in ("/add", "/edit/1", "/delete/1", "/import/commit"):
        assert endpoint("POST", path, json={"name": "Unauthorized"}, headers=headers).status_code == 302
    for path in ("/api/chat", "/api/wine/1/restore", "/api/ai-settings"):
        assert endpoint("POST", path, json={}, headers=headers).status_code == 401
    assert endpoint("GET", "/api/summary", headers=headers).status_code == 401
    assert db.execute("SELECT COUNT(*) FROM wines").fetchone()[0] == 0
    assert endpoint("POST", "/api/v1/wines", json={"name": "No token"}).status_code == 401


def test_staging_archive_is_isolated_and_reproducible():
    builder = runpy.run_path(str(ROOT / "scripts/prepare-api-staging.py"))
    commit, data = builder["build_archive"](ROOT, "HEAD")
    assert builder["build_archive"](ROOT, commit)[1] == data
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        prefix = "wine_tracker_api_staging/"
        config = json.loads(archive.read(prefix + "config.json"))
        assert config["slug"] == "wine_tracker_api_staging"
        assert config["map"] == [] and config["ports"] == {}
        assert config["ingress"] is False and config["host_network"] is False
        assert config["boot"] == "manual"
        assert config["environment"] == {"S6_KEEP_ENV": "1", "AUTH_ENABLED": "true", "USERS": "", "DEV_AUTH": "",
                                         "DATA_DIR": "/data/wine-tracker-api-staging"}
        assert config["options"]["wine_api_token"] == ""
        manifest = json.loads(archive.read(prefix + "SOURCE.json"))
        assert manifest["source_commit"] == commit
        for path, checksum in manifest["files_sha256"].items():
            assert hashlib.sha256(archive.read(prefix + path)).hexdigest() == checksum
        assert all("wine.db" not in name and "/data/" not in name and "__pycache__" not in name
                   for name in archive.namelist())
        assert archive.read(prefix + "app/app.py") == builder["git"](ROOT, "show", commit + ":wine-tracker/app/app.py")
