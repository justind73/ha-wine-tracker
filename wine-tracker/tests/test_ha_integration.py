"""Exercise the documented HA templates against an isolated HTTP wine API.

This is not a substitute for HA Core configuration validation on installation.
"""

import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

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
        assert loader.construct_scalar(node) == "wine_tracker_api_token"
        return TOKEN

    SecretLoader.add_constructor("!secret", secret)
    return yaml.load((ROOT / "examples/home-assistant/wine_tracker.yaml").read_text(encoding="utf-8"), Loader=SecretLoader)


def render(command, data):
    # HA's to_json serializes data, rather than interpolating it into JSON text.
    env = Environment(undefined=StrictUndefined)
    env.filters["to_json"] = lambda value: json.dumps(value, ensure_ascii=False)
    url = env.from_string(command["url"]).render(data)
    assert urlsplit(url).netloc == "64183197-wine-tracker:5050"
    headers = {name: env.from_string(value).render(data) for name, value in command["headers"].items()}
    body = env.from_string(command["payload"]).render(data) if "payload" in command else None
    if "content_type" in command:
        headers["Content-Type"] = command["content_type"]
    parsed = urlsplit(url)
    return parsed.path + (("?" + parsed.query) if parsed.query else ""), headers, body


@pytest.fixture
def endpoint(app, monkeypatch):
    monkeypatch.setitem(wine_app.HA_OPTIONS, "wine_api_token", TOKEN)
    monkeypatch.setattr(wine_app, "HA_INGRESS_ONLY", True)
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
        command = package["rest_command"]["wine_tracker_" + name]
        path, headers, body = render(command, data)
        response = endpoint(command["method"], path, headers=headers,
                            data=body.encode("utf-8") if body is not None else None)
        assert TOKEN not in response.text + str(dict(response.headers))
        return response

    created = call("add", {"request_id": "test-black-pig-create-001", "wine": {
        "producer": "The Black Pig", "name": "The Prize Shiraz", "year": 2023,
        "quantity": 6, "price": 12.5, "notes": "Classic Cellar commentary"}})
    assert created.status_code == 201
    wine_id = created.json()["wine"]["id"]
    operation = {"wine_id": wine_id, "request_id": "test-black-pig-consume-001",
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
    restocked = call("stock", {"wine_id": wine_id, "request_id": "test-restock-001", "change": {"delta": 2}})
    assert restocked.json()["wine"]["quantity"] == 7
    note = 'A "quoted" note.\nIt’s ready — {{ not_a_template }}.'
    patched = call("update", {"wine_id": wine_id, "request_id": "test-update-001", "changes": {"notes": note}})
    assert patched.json()["wine"]["notes"].endswith("\n\n" + note)
    replaced = call("update", {"wine_id": wine_id, "request_id": "test-replace-001",
                               "changes": {"notes": note, "notes_mode": "replace"}})
    assert replaced.json()["wine"]["notes"] == note
    assert replaced.json()["wine"]["price"] == 12.5


@pytest.mark.parametrize("wine_id", ["../edit/1", "https://evil.invalid/", "1?x=y", 1.5, True, None, -1])
def test_ha_template_cannot_redirect_credentials(package, wine_id):
    for action in ("get", "stock", "update", "image"):
        path, headers, body = render(package["rest_command"]["wine_tracker_" + action], {
            "wine_id": wine_id, "request_id": "test-operation-001", "change": {"delta": 1},
            "image": {}, "changes": {"notes": "Test"}, "url": "https://evil.invalid/", "headers": {"X-Wine-API-Key": "override"}})
        assert path in ("/api/v1/wines/0", "/api/v1/wines/0/stock", "/api/v1/wines/0/image")
        assert headers["X-Wine-API-Key"] == TOKEN


def test_ha_package_requires_key_and_disables_secret_logging(package):
    assert package["logger"]["logs"]["homeassistant.components.rest_command"] == "warning"
    command = package["rest_command"]["wine_tracker_add"]
    with pytest.raises(Exception, match="request_id"):
        render(command, {"wine": {"name": "Test"}})


def test_production_blocks_legacy_writes_even_with_spoofed_ingress(endpoint, db):
    headers = {"X-Ingress-Path": "/api/hassio_ingress/fake", "X-Remote-User-Id": "admin",
               "X-Wine-API-Key": TOKEN}
    for path in ("/add", "/edit/1", "/delete/1", "/import/commit"):
        assert endpoint("POST", path, json={"name": "Unauthorized"}, headers=headers).status_code == 403
    for path in ("/api/chat", "/api/wine/1/restore", "/api/ai-settings"):
        assert endpoint("POST", path, json={}, headers=headers).status_code == 403
    assert endpoint("GET", "/api/summary", headers=headers).status_code == 403
    assert db.execute("SELECT COUNT(*) FROM wines").fetchone()[0] == 0
    assert endpoint("POST", "/api/v1/wines", json={"name": "No token"}).status_code == 401


@pytest.mark.parametrize("peer", ["127.0.0.1", "172.30.33.4", "192.168.1.10"])
def test_ingress_identity_headers_cannot_replace_trusted_peer(client, monkeypatch, peer):
    monkeypatch.setattr(wine_app, "HA_INGRESS_ONLY", True)
    headers = {"X-Ingress-Path": "/api/hassio_ingress/fake",
               "X-Remote-User-Id": "admin", "X-Forwarded-For": "172.30.32.2",
               "Forwarded": "for=172.30.32.2", "X-Wine-API-Key": TOKEN}
    for path in ("/", "/export", "/api/summary"):
        assert client.get(path, headers=headers, environ_overrides={"REMOTE_ADDR": peer}).status_code == 403
    assert client.post("/add", data={"name": "Forbidden", "quantity": 1},
                       headers=headers, environ_overrides={"REMOTE_ADDR": peer}).status_code == 403


def test_authenticated_ingress_keeps_ui_but_never_bypasses_machine_key(client, monkeypatch, db):
    monkeypatch.setattr(wine_app, "HA_INGRESS_ONLY", True)
    monkeypatch.setitem(wine_app.HA_OPTIONS, "wine_api_token", TOKEN)
    peer = {"REMOTE_ADDR": "172.30.32.2"}
    headers = {"X-Ingress-Path": "/api/hassio_ingress/test"}
    assert client.get("/", headers=headers, environ_overrides=peer).status_code == 200
    assert client.get("/api/summary", headers=headers, environ_overrides=peer).status_code == 200
    added = client.post("/add", data={"name": "Ingress UI wine", "quantity": 3},
                        headers=headers, environ_overrides=peer)
    assert added.status_code in (200, 302)
    assert db.execute("SELECT quantity FROM wines WHERE name='Ingress UI wine'").fetchone()[0] == 3
    assert client.get("/api/v1/wines/1", headers=headers, environ_overrides=peer).status_code == 401
    assert client.get("/api/v1/wines/1", headers={**headers, "X-Wine-API-Key": TOKEN},
                      environ_overrides=peer).status_code == 200


def test_production_manifest_retains_ingress_and_private_api_network():
    config = yaml.safe_load((ROOT / "wine-tracker/config.yaml").read_text(encoding="utf-8"))
    assert config["ports"] == {}
    assert config["ingress"] is True and config["ingress_port"] == 5050
    assert config["environment"]["HA_INGRESS_ONLY"] == "true"
    assert config["environment"]["S6_KEEP_ENV"] == "1"
    assert config["environment"]["DATA_DIR"] == "/share/wine-tracker"
    assert config["map"] == ["share:rw"]


def test_ha_image_and_list_http_roundtrip(package, endpoint, db, monkeypatch):
    import wine_images
    from .test_images import picture
    monkeypatch.setattr(wine_images,"download_image",lambda url:(picture(),"image/png",url))
    def call(name,data):
        command=package["rest_command"]["wine_tracker_"+name]
        path,headers,body=render(command,data)
        assert TOKEN not in json.dumps(data)
        result=endpoint(command["method"],path,headers=headers,data=body.encode("utf-8") if body else None)
        assert TOKEN not in result.text
        return result
    # One generic order line. A placed order never adds physical stock.
    wine={"name":"Test cuvee","producer":"Independent producer","year":2022,"bottle_format":0.75,"quantity":0,"price":15}
    created=call("add",{"request_id":"order-123-line-1-record","wine":wine})
    assert created.status_code==201
    wine_id=created.json()["wine"]["id"]
    assert call("get",{"wine_id":wine_id}).json()["wine"]["quantity"]==0
    # Always use stock for receipt, including newly created wines. Same key
    # applies whether the order was first seen before or after delivery.
    receipt={"wine_id":wine_id,"request_id":"order-123-line-1-received","change":{"delta":6}}
    assert call("stock",receipt).json()["wine"]["quantity"]==6
    photo={"wine_id":wine_id,"request_id":"order-123-line-1-photo","image":{
        "match":{k: wine[k] for k in ("name","producer","year","bottle_format")},
        "source":{"url":"https://arbitrary.example.org/bottle.png","page_url":"https://arbitrary.example.org/wine",
                  "rights":{"basis":"license","reference":"Fixture licence allowing copying and resizing"},
                  "attribution":"Test photographer — example only"}}}
    result=call("image",photo)
    assert result.status_code==200 and result.json()["image"]["available"]
    assert call("image",photo).headers["Idempotency-Replayed"]=="true"
    assert call("stock",receipt).headers["Idempotency-Replayed"]=="true"
    current=call("get",{"wine_id":wine_id}).json()
    assert current["wine"]["quantity"]==6 and current["image"]==result.json()["image"]
    assert len(call("list",{}).json()["wines"])==1
    assert call("list",{"missing_image":True}).json()["wines"]==[]
    assert db.execute("SELECT COUNT(*) FROM timeline WHERE action='restocked'").fetchone()[0]==1


@pytest.mark.parametrize("data",[{}, {"after_id":"0&url=https://evil.invalid","limit":"1#x","missing_image":"true"},
    {"after_id":True,"limit":False,"missing_image":False}])
def test_list_template_keeps_fixed_destination(package,data):
    path,headers,body=render(package["rest_command"]["wine_tracker_list"],data)
    assert path=="/api/v1/wines?after_id=0&limit=50&missing_image=false"
    assert headers["X-Wine-API-Key"]==TOKEN and body is None
