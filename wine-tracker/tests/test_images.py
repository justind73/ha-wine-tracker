"""Generic photograph security and atomic attachment, using disposable fixtures."""
import hashlib
import io
import json
from pathlib import Path
import socket
import ssl
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from PIL import Image, PngImagePlugin

import app as wine_app
import wine_api
import wine_images as images
from .test_write_api import BASE, headers, snapshot, enabled
from export_import import parse_import_file, apply_import, match_wines


def picture(fmt="PNG", size=(64, 96), **kwargs):
    stream = io.BytesIO()
    Image.new("RGB", size, "red").save(stream, format=fmt, **kwargs)
    return stream.getvalue()


@pytest.fixture
def remote(monkeypatch):
    calls = []
    def download(url):
        calls.append(url)
        return picture(), "image/png", "https://cdn.example.org/bottle.png"
    monkeypatch.setattr(images, "download_image", download)
    return calls


@pytest.fixture
def payload(sample_wine):
    wine = sample_wine["wine"]
    return {"match": {k: wine[k] for k in wine_api.IDENTITY_FIELDS}, "source": {
        "url": "https://merchant.example.org/photo.png",
        "page_url": "https://merchant.example.org/wine",
        "rights": {"basis": "permission", "reference": "Fixture photographer's written permission"},
        "attribution": "Fixture photographer"}}


def attach(client, payload, key="photo-operation-001", wine_id=1):
    return client.post(f"{BASE}/{wine_id}/image", json=payload, headers=headers(key))


@pytest.mark.parametrize("path,method", [(BASE,"GET"), (BASE+"/1/image","POST")])
@pytest.mark.parametrize("token,expected", [(None,401),("invalid",401)])
def test_image_routes_auth(client, enabled, path, method, token, expected, monkeypatch):
    monkeypatch.setattr(wine_app,"HA_INGRESS_ONLY",True)
    supplied = {"X-Ingress-Path":"/trusted", "X-Remote-User-Id":"admin"}
    if token:
        supplied["X-Wine-API-Key"] = token
    assert client.open(path, method=method, headers=supplied,
                       environ_overrides={"REMOTE_ADDR":"172.30.32.2"}).status_code == expected


def test_image_routes_disabled_and_readonly(client, enabled, monkeypatch):
    monkeypatch.setitem(wine_app.HA_OPTIONS,"wine_api_token","")
    assert client.get(BASE,headers=headers()).status_code == 503
    assert attach(client,{}).status_code == 503
    monkeypatch.setitem(wine_app.HA_OPTIONS,"wine_api_token",headers()["X-Wine-API-Key"])
    monkeypatch.setattr(wine_app,"AUTH_ENABLED",True)
    with client.session_transaction() as session:
        session.update(user="viewer",role="readonly")
    assert attach(client,{}).status_code == 403


@pytest.mark.parametrize("verified", [True, False])
def test_attach_replay_preservation_and_backup(client, db, enabled, payload, remote, upload_dir, tmp_path, verified):
    if not verified:
        payload["source"].pop("rights")
    payload["source"]["source_name"] = "Independent merchant"
    before = snapshot(db)
    response = attach(client,payload)
    assert response.status_code == 200, response.json
    wine, info = response.json["wine"], response.json["image"]
    stored = Path(upload_dir, wine["image"]).read_bytes()
    assert info["available"] and info["sha256"] == hashlib.sha256(stored).hexdigest()
    expected_rights = {**payload["source"]["rights"], "status": "verified"} if verified else {"status": "unverified"}
    assert info["source"]["rights"] == expected_rights
    for field in ("url", "page_url", "source_name", "attribution"):
        assert info["source"][field] == payload["source"][field]
    assert client.get("/api/wine/1").json["wine"]["image_info"] == info
    assert info["source"]["resolved_url"] == "https://cdn.example.org/bottle.png"
    original = client.get(BASE+"/1",headers=headers()).json
    assert original == response.json
    after = snapshot(db)
    oldwine = dict(zip([r[1] for r in db.execute("PRAGMA table_info(wines)")],before["wines"][0]))
    assert all(wine[k] == v for k,v in oldwine.items() if k != "image")
    assert after["timeline"] == before["timeline"]
    replay = attach(client,payload)
    assert replay.json == response.json and replay.headers["Idempotency-Replayed"] == "true"
    assert len(remote) == 1 and snapshot(db) == after
    assert len(list(Path(upload_dir).iterdir())) == 1
    assert attach(client,{**payload,"replace":True}).status_code == 409
    assert attach(client,payload,"photo-second-operation").json["error"] == "image_already_exists"
    assert len(remote) == 1
    archive = client.get("/export").data
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        assert zf.testzip() is None
        assert zf.read("images/"+wine["image"]) == stored
    parsed = parse_import_file(archive,"cellar.zip")
    restored = tmp_path / "restored"
    restored.mkdir()
    # The ordinary importer copies the image bytes; embedded provenance survives.
    apply_import(parsed, match_wines(parsed["wines"], db), db, str(restored), strategy="skip")
    assert images.image_info(restored,wine["image"]) == info


@pytest.mark.parametrize("field,value", [("name","Similar cuvee"),("producer","Other producer"),
    ("year",2021),("bottle_format",1.5),("bottle_format",0),("bottle_format",True)])
def test_incorrect_match_never_fetches(client, db, enabled, payload, remote, field,value):
    payload["match"][field] = value
    before = snapshot(db)
    response = attach(client,payload)
    assert response.status_code == 409 and response.json["error"] == "image_wine_mismatch"
    assert not remote and snapshot(db) == before


@pytest.mark.parametrize("source", [{}, {"url":"https://example.org/a.png","rights":{"status":"verified"}},
    {"url":"https://example.org/a.png","rights":{"basis":"private_use","reference":"personal"}},
    {"url":"https://example.org/a.png","rights":{"basis":"license","reference":" "}},
    {"upload_filename":"../../secrets.yaml","rights":{"basis":"user_owned","reference":"my photo"}}])
def test_source_failure_atomic(client,db,enabled,payload,remote,source):
    payload["source"] = source
    before = snapshot(db)
    assert attach(client,payload).status_code == 400
    assert snapshot(db) == before and not remote


def test_replace_requires_current_image(client,enabled,payload,remote,upload_dir):
    first = attach(client,payload).json
    updated = {**payload,"replace":True,"expected_image":"stale.jpg"}
    assert attach(client,updated,"photo-replace-001").json["error"] == "image_changed"
    updated["expected_image"] = first["wine"]["image"]
    second = attach(client,updated,"photo-replace-001")
    assert second.status_code == 200
    assert second.json["wine"]["image"] != first["wine"]["image"]
    # Old references may belong to another wine/chat; leave cleanup to upstream.
    assert Path(upload_dir,first["wine"]["image"]).exists()
    assert len(remote) == 2


def test_rollback_removes_new_file(client,db,enabled,payload,remote,upload_dir):
    db.execute("CREATE TRIGGER fail_photo BEFORE UPDATE OF image ON wines BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    db.commit()
    before=snapshot(db)
    with pytest.raises(Exception,match="fixture"):
        attach(client,payload)
    assert snapshot(db)==before and not list(Path(upload_dir).iterdir())


def test_storage_failure_keeps_existing_file(client,db,enabled,payload,remote,upload_dir,monkeypatch):
    class Fixed:
        hex = "a"*32
    monkeypatch.setattr(wine_api.uuid,"uuid4",lambda:Fixed())
    path=Path(upload_dir,Fixed.hex+".jpg")
    path.write_bytes(b"existing file")
    before=snapshot(db)
    assert attach(client,payload).json["error"]=="image_storage_unavailable"
    assert path.read_bytes()==b"existing file" and snapshot(db)==before


def test_concurrent_retries_only_one_image(app,client,db,enabled,payload,upload_dir,monkeypatch):
    barrier=Barrier(2)
    def download(url):
        barrier.wait(timeout=10)
        return picture(),"image/png",url
    monkeypatch.setattr(images,"download_image",download)
    def run(_):
        with app.test_client() as concurrent:
            return attach(concurrent,payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert results[0].json==results[1].json
    assert len(list(Path(upload_dir).iterdir()))==1
    assert db.execute("SELECT COUNT(*) FROM api_requests").fetchone()[0]==1


def test_changed_target_during_download(client,db,enabled,payload,upload_dir,monkeypatch):
    def prepare(*args):
        db.execute("UPDATE wines SET year=2021 WHERE id=1")
        db.commit()
        return picture()
    monkeypatch.setattr(wine_api,"prepare_image",prepare)
    assert attach(client,payload).json["error"]=="image_wine_mismatch"
    assert not list(Path(upload_dir).iterdir())


def test_owned_upload_and_legacy_comment(client,enabled,payload,upload_dir):
    filename="b"*32+".png"
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text("comment","Old ordinary PNG comment")
    Path(upload_dir,filename).write_bytes(picture(pnginfo=metadata))
    assert images.image_info(upload_dir,filename)["source"] is None
    payload["source"]={"upload_filename":filename,"rights":{"basis":"user_owned","reference":"My own photograph"}}
    response=attach(client,payload)
    assert response.status_code==200 and response.json["image"]["source"]["rights"]["basis"]=="user_owned"


@pytest.mark.parametrize("rights,expected", [
    (None, {"status": "unverified"}), ({}, {"status": "unverified"}),
    ({"status": "unverified"}, {"status": "unverified"}),
    ({"basis": "user_owned"}, {"basis": "user_owned", "status": "verified"}),
    ({"status": "verified", "basis": "license", "reference": "CC BY 4.0"},
     {"status": "verified", "basis": "license", "reference": "CC BY 4.0"}),
])
def test_optional_rights_and_product_page(client, enabled, payload, remote, rights, expected):
    payload["source"] = {"url": "https://independent.example.org/bottle.png"}
    if rights is not None:
        payload["source"]["rights"] = rights
    response = attach(client, payload)
    assert response.status_code == 200
    assert response.json["image"]["source"]["rights"] == expected
    assert response.json["image"]["source"]["url"] == payload["source"]["url"]


@pytest.mark.parametrize("rights", [[], "permission", {"status": "legal"},
    {"status": "verified"}, {"basis": "private_use"}, {"reference": 123},
    {"reference": "x" * 1001}, {"unknown": True}])
def test_malformed_rights_still_rejected(client, db, enabled, payload, remote, rights):
    payload["source"]["rights"] = rights
    before = snapshot(db)
    assert attach(client, payload).json["error"] == "invalid_image_rights"
    assert not remote and snapshot(db) == before


@pytest.mark.parametrize("field,value", [("source_name", "x" * 501), ("source_name", []),
    ("page_url", "javascript:alert(1)"), ("page_url", "https://localhost/private")])
def test_source_metadata_validation(client, db, enabled, payload, remote, field, value):
    payload["source"].pop("rights")
    payload["source"][field] = value
    before = snapshot(db)
    assert attach(client, payload).status_code == 400
    assert not remote and snapshot(db) == before


@pytest.mark.parametrize("basis", ["permission", "license", "user_owned"])
def test_legacy_rights_read_without_rewriting(client, db, sample_wine, upload_dir, basis):
    filename = "c" * 32 + ".jpg"
    old = {"url": "https://example.org/bottle.jpg",
           "rights": {"basis": basis, "reference": "Original evidence"}}
    data = images.encode_image(picture(), "image/png", old)
    path = Path(upload_dir, filename)
    path.write_bytes(data)
    db.execute("UPDATE wines SET image=? WHERE id=1", (filename,))
    db.commit()
    source = client.get("/api/wine/1").json["wine"]["image_info"]["source"]
    assert source == {**old, "rights": {**old["rights"], "status": "verified"}}
    assert path.read_bytes() == data


@pytest.mark.parametrize("source", [None, [], {"rights": "old unstructured note"}])
def test_unstructured_old_metadata_is_not_verified(upload_dir, source):
    filename = "d" * 32 + ".jpg"
    Path(upload_dir, filename).write_bytes(images.encode_image(picture(), "image/png", source))
    info = images.image_info(upload_dir, filename)
    assert info["available"]
    assert not info["source"] or info["source"]["rights"]["status"] == "unverified"


@pytest.mark.parametrize("value", ["http://example.org/a", "https://127.0.0.1/a", "https://[::1]/a",
    "https://example.org:444/a","https://a:b@example.org/a","file:///etc/passwd",
    "https://example.org/a#secret","https://localhost/a","https://example.org/ space",
    "https://example.org/\\evil","https://example.org/\n",None,"https://"+"x"*2050])
def test_unsafe_url(value):
    with pytest.raises(images.ImageError):
        images.https_url(value)


@pytest.mark.parametrize("address", ["127.0.0.1","10.0.0.1","172.30.32.1","192.168.1.10",
    "169.254.169.254","0.0.0.0","224.0.0.1","240.0.0.1","::1","fc00::1","fe80::1",
    "::ffff:8.8.8.8","2002:0808:0808::1","64:ff9b::808:808"])
def test_every_dns_answer_must_be_public(monkeypatch,address):
    good=(socket.AF_INET,socket.SOCK_STREAM,6,"",("8.8.8.8",443))
    bad=(socket.AF_INET6 if ":" in address else socket.AF_INET,socket.SOCK_STREAM,6,"",(address,443))
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:[good,bad])
    with pytest.raises(images.ImageError,match="image_private_address"):
        images.public_addresses("arbitrary.example.org")


def test_tls_pins_numeric_ip_and_verifies_hostname(monkeypatch):
    address=(socket.AF_INET,socket.SOCK_STREAM,6,"",("8.8.8.8",443))
    connected=[]
    class Raw:
        def settimeout(self,timeout): pass
        def connect(self,target): connected.append(target)
        def close(self): pass
    monkeypatch.setattr(socket,"socket",lambda *args:Raw())
    monkeypatch.setattr(socket,"getaddrinfo",lambda *args,**kw:pytest.fail("second DNS lookup"))
    conn=images.PinnedHTTPSConnection("cdn.example.org",address,12)
    assert conn._context.verify_mode==ssl.CERT_REQUIRED and conn._context.check_hostname
    class Context:
        def wrap_socket(self,raw,server_hostname):
            assert server_hostname=="cdn.example.org"
            return raw
    conn._context=Context()
    conn.connect()
    assert connected==[("8.8.8.8",443)]
    conn.close()


class Response:
    def __init__(self,status=200,headers=None,data=b"image"):
        self.status=status
        self.headers=headers if headers is not None else {"Content-Type":"image/png"}
        self.stream=io.BytesIO(data)
    def getheader(self,key,default=None): return self.headers.get(key,default)
    def read1(self,count): return self.stream.read(count)


def fake_network(monkeypatch,responses):
    hosts=[]
    requests=[]
    closed=[]
    def lookup(host,port,**kwargs):
        hosts.append(host)
        ip="127.0.0.1" if host=="internal.example.org" else "8.8.8.8"
        return [(socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,443))]
    monkeypatch.setattr(socket,"getaddrinfo",lookup)
    class Connection:
        sock=None
        def __init__(self,host,address,timeout): self.host=host
        def request(self,method,target,headers): requests.append((self.host,method,target,headers))
        def getresponse(self): return responses.pop(0)
        def close(self): closed.append(self.host)
    monkeypatch.setattr(images,"PinnedHTTPSConnection",Connection)
    return hosts,requests,closed


def test_generic_cdn_redirect_without_credentials(monkeypatch):
    hosts,requests,closed=fake_network(monkeypatch,[Response(302,{"Location":"https://cdn.example.org/image?size=large"}),Response()])
    data,mime,url=images.download_image("https://merchant.example.org/photo")
    assert hosts==["merchant.example.org","cdn.example.org"]==closed
    assert requests[1][2]=="/image?size=large"
    assert set(requests[1][3])=={"Accept","Accept-Encoding","User-Agent"}
    assert data==b"image" and mime=="image/png" and url.endswith("size=large")


@pytest.mark.parametrize("destination",["https://internal.example.org/a","http://cdn.example.org/a","https://127.0.0.1/a"])
def test_redirect_cannot_bypass_validation(monkeypatch,destination):
    _,requests,closed=fake_network(monkeypatch,[Response(302,{"Location":destination})])
    with pytest.raises(images.ImageError): images.download_image("https://example.org/a")
    assert len(requests)==len(closed)==1


@pytest.mark.parametrize("response,error",[
    (Response(404),"image_download_failed"),
    (Response(200,{"Content-Type":"image/svg+xml"}),"unsupported_image_type"),
    (Response(200,{"Content-Type":"image/png","Content-Encoding":"gzip"}),"unsupported_image_type"),
    (Response(200,{"Content-Type":"image/png","Content-Length":"9"}),"invalid_image"),
    (Response(200,{"Content-Type":"image/png","Content-Length":"9"*5000}),"image_too_large"),
    (Response(data=b"x"*(images.MAX_BYTES+1)),"image_too_large")])
def test_download_rejections(monkeypatch,response,error):
    _,_,closed=fake_network(monkeypatch,[response])
    with pytest.raises(images.ImageError,match=error): images.download_image("https://example.org/a")
    assert closed==["example.org"]


def test_redirect_limit_and_timeout(monkeypatch):
    _,requests,_=fake_network(monkeypatch,[Response(302,{"Location":"/again"}) for _ in range(4)])
    with pytest.raises(images.ImageError,match="image_redirect_limit"): images.download_image("https://example.org/a")
    assert len(requests)==4
    clock=iter([0,13])
    monkeypatch.setattr(images.time,"monotonic",lambda:next(clock))
    with pytest.raises(images.ImageError,match="image_download_timeout"): images.download_image("https://example.org/a")


@pytest.mark.parametrize("fmt",["JPEG","PNG","WEBP"])
def test_processing_supported_and_removes_exif(fmt):
    exif=Image.Exif()
    exif[0x010e]="private camera comment"
    encoded=images.encode_image(picture(fmt,(2000,1000),exif=exif),images.MIME[fmt],{"rights":"fixture"})
    with Image.open(io.BytesIO(encoded)) as result:
        assert result.format=="JPEG" and result.size==(1800,900)
        assert not result.getexif()
        assert result.info["comment"].startswith(images.COMMENT_PREFIX)
    assert b"private camera comment" not in encoded


@pytest.mark.parametrize("data,mime,error",[
    (b"<svg/>","image/png","invalid_image"),
    (picture("GIF"),"image/png","unsupported_image_type"),
    (picture(),"image/jpeg","unsupported_image_type"),
    (picture(size=(20,20)),"image/png","invalid_image_dimensions"),
    (picture(size=(8001,32)),"image/png","invalid_image_dimensions"),
    (picture(size=(4001,4000)),"image/png","invalid_image_dimensions"),
    (picture()[:40],"image/png","invalid_image"),
    (b"x"*(images.MAX_BYTES+1),None,"image_too_large")])
def test_rejects_bad_images(data,mime,error):
    with pytest.raises(images.ImageError,match=error): images.encode_image(data,mime,{})


def test_rejects_animation():
    stream=io.BytesIO()
    Image.new("RGB",(64,64),"red").save(stream,format="PNG",save_all=True,
        append_images=[Image.new("RGB",(64,64),"blue")],duration=100)
    with pytest.raises(images.ImageError,match="invalid_image_dimensions"):
        images.encode_image(stream.getvalue(),"image/png",{})


def test_list_pagination_and_missing_images(client,db,enabled,payload,remote):
    for i in range(2,5):
        db.execute("INSERT INTO wines (id,name) VALUES (?,?)",(i,"Wine "+str(i)))
    db.commit()
    attach(client,payload)
    first=client.get(BASE+"?limit=2",headers=headers()).json
    assert [w["id"] for w in first["wines"]]==[1,2] and first["next_after_id"]==2
    last=client.get(BASE+"?after_id=2&limit=2",headers=headers()).json
    assert [w["id"] for w in last["wines"]]==[3,4] and last["next_after_id"] is None
    missing=client.get(BASE+"?missing_image=true",headers=headers()).json
    assert [w["id"] for w in missing["wines"]]==[2,3,4]


@pytest.mark.parametrize("query",["limit=0","limit=101","limit=2.5","after_id=-1","after_id=x",
    "missing_image=yes","url=https://example.org","after_id="+"9"*30])
def test_invalid_list_query(client,enabled,query):
    assert client.get(BASE+"?"+query,headers=headers()).status_code==400



def test_upload_symlink_rejected(tmp_path):
    outside=tmp_path / "outside.png"
    outside.write_bytes(picture())
    folder=tmp_path / "uploads"
    folder.mkdir()
    link=folder / ("c"*32+".png")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not grant symlink creation")
    with pytest.raises(images.ImageError,match="uploaded_image_not_found"):
        images.upload_path(folder,link.name)


@pytest.mark.parametrize("fault,error",[(TimeoutError(),"image_download_timeout"),
    (ssl.SSLCertVerificationError(),"image_download_failed")])
def test_network_faults_are_sanitized(monkeypatch,fault,error):
    class Broken(Response):
        def read1(self,count): raise fault
    fake_network(monkeypatch,[Broken()])
    with pytest.raises(images.ImageError,match=error):
        images.download_image("https://example.org/a")


def test_unrelated_edit_during_fetch_survives(client,db,enabled,payload,upload_dir,monkeypatch):
    def prepare(*args):
        db.execute("UPDATE wines SET quantity=7,notes='Concurrent note' WHERE id=1")
        db.commit()
        return images.encode_image(picture(),"image/png",{})
    monkeypatch.setattr(wine_api,"prepare_image",prepare)
    result=attach(client,payload)
    assert result.status_code==200
    assert result.json["wine"]["quantity"]==7 and result.json["wine"]["notes"]=="Concurrent note"
