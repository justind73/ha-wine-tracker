"""Bounded image retrieval and processing; no AI, credentials, proxies or workers."""

import hashlib
import http.client
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 8000
MAX_OUTPUT_DIMENSION = 1800
DOWNLOAD_SECONDS = 12
MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
COMMENT_PREFIX = b"WineTrackerSource:"


class ImageError(Exception):
    def __init__(self, error, status=400):
        self.error, self.status = error, status


def https_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ImageError("invalid_image_url")
    if any(ord(c) < 33 or ord(c) > 126 for c in value) or "\\" in value:
        raise ImageError("invalid_image_url")
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (url.scheme != "https" or url.port not in (None, 443)
                or url.username is not None or url.password is not None or url.fragment
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
                or "." not in host or ".." in host):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return url
    except ValueError:
        pass
    raise ImageError("invalid_image_url")


def public_addresses(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ImageError("image_dns_failed", 502) from None
    if not addresses:
        raise ImageError("image_dns_failed", 502)
    for family, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (family not in (socket.AF_INET, socket.AF_INET6) or not ip.is_global
                or ip.is_multicast or ip.is_reserved
                or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo
                    or ip in ipaddress.ip_network("64:ff9b::/96")))):
            raise ImageError("image_private_address")
    # Pin a previously validated numeric address. Never resolve the name again
    # during connection (DNS rebinding); retain the hostname for TLS/SNI/Host.
    return sorted(addresses, key=lambda a: a[0] != socket.AF_INET)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        family, socktype, proto, _, address = self.address
        raw = socket.socket(family, socktype, proto)
        try:
            raw.settimeout(self.timeout)
            raw.connect(address)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def download_image(url):
    # Supplier-independent: public HTTPS only, including CDN redirects.
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    for hop in range(4):
        parsed = https_url(url)
        addresses = public_addresses(parsed.hostname)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImageError("image_download_timeout", 504)
        connection = PinnedHTTPSConnection(parsed.hostname, addresses[0], remaining)
        try:
            target = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
            connection.request("GET", target,
                               headers={"Accept": "image/jpeg,image/png,image/webp",
                                        "Accept-Encoding": "identity", "User-Agent": "WineTracker/1 image-fetch"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop == 3:
                    raise ImageError("image_redirect_limit")
                url = urljoin(url, location)
                continue  # Revalidate HTTPS, hostname syntax AND public DNS at every hop.
            if response.status != 200:
                raise ImageError("image_download_failed", 502)
            mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in MIME.values() or response.getheader("Content-Encoding", "identity") != "identity":
                raise ImageError("unsupported_image_type")
            length = response.getheader("Content-Length")
            if length is not None and (len(length) > 10 or not length.isascii()
                                       or not length.isdigit() or int(length) > MAX_BYTES):
                raise ImageError("image_too_large", 413)
            data = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ImageError("image_download_timeout", 504)
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ImageError("image_too_large", 413)
            if length is not None and len(data) != int(length):
                raise ImageError("invalid_image")
            return bytes(data), mime, url
        except (TimeoutError, socket.timeout):
            raise ImageError("image_download_timeout", 504) from None
        except (OSError, http.client.HTTPException):
            raise ImageError("image_download_failed", 502) from None
        finally:
            connection.close()
    raise ImageError("image_redirect_limit")


def upload_path(directory, filename):
    if not isinstance(filename, str) or not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|jpeg|png|webp)", filename):
        raise ImageError("invalid_uploaded_image")
    path = Path(directory) / filename
    if path.is_symlink() or path.resolve().parent != Path(directory).resolve() or not path.is_file():
        raise ImageError("uploaded_image_not_found", 404)
    return path


def encode_image(data, mime, provenance):
    if not data or len(data) > MAX_BYTES:
        raise ImageError("image_too_large", 413)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in MIME or (mime and MIME[image.format] != mime):
                raise ImageError("unsupported_image_type")
            width, height = image.size
            if (width < 32 or height < 32 or max(width, height) > MAX_DIMENSION
                    or width * height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1):
                raise ImageError("invalid_image_dimensions")
            image.verify()
        with Image.open(io.BytesIO(data)) as original:
            original.load()
            image = ImageOps.exif_transpose(original)
            image.thumbnail((MAX_OUTPUT_DIMENSION, MAX_OUTPUT_DIMENSION))
            rgba = image.convert("RGBA")
            clean = Image.new("RGB", rgba.size, "white")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            output = io.BytesIO()
            # Keep only our explicit attribution/provenance, not camera/GPS/EXIF.
            clean.save(output, format="JPEG", quality=85, optimize=True,
                       comment=COMMENT_PREFIX + json.dumps(provenance, ensure_ascii=False).encode("utf-8"))
            result = output.getvalue()
            if len(result) > MAX_BYTES:
                raise ImageError("image_too_large", 413)
            return result
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ImageError("invalid_image") from None


def normalize_rights(rights):
    """Accept legacy declarations; missing evidence never implies permission."""
    if rights is None:
        return {"status": "unverified"}
    if not isinstance(rights, dict) or not set(rights) <= {"status", "basis", "reference"}:
        raise ImageError("invalid_image_rights")
    basis = rights.get("basis")
    if basis is not None and basis not in ("permission", "license", "user_owned"):
        raise ImageError("invalid_image_rights")
    status = rights.get("status", "verified" if basis else "unverified")
    if status not in ("verified", "unverified") or (status == "verified" and not basis):
        raise ImageError("invalid_image_rights")
    if "reference" in rights and (not isinstance(rights["reference"], str)
                                  or not 1 <= len(rights["reference"].strip()) <= 1000):
        raise ImageError("invalid_image_rights")
    return {**rights, "status": status}


def prepare_image(source, directory):
    if not isinstance(source, dict) or not set(source) <= {
            "url", "upload_filename", "page_url", "source_name", "rights", "attribution"}:
        raise ImageError("invalid_image_source")
    if ("url" in source) == ("upload_filename" in source):
        raise ImageError("image_source_required")
    rights = normalize_rights(source.get("rights"))
    for field in ("attribution", "source_name"):
        if not isinstance(source.get(field, ""), str) or len(source.get(field, "")) > 500:
            raise ImageError("invalid_" + field)
    if "page_url" in source:
        https_url(source["page_url"])
    provenance = {**source, "rights": rights}
    if "url" in source:
        data, mime, final_url = download_image(source["url"])
        provenance["resolved_url"] = final_url
    else:
        path = upload_path(directory, source["upload_filename"])
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        mime = None
    provenance["original_sha256"] = hashlib.sha256(data).hexdigest()
    return encode_image(data, mime, provenance)


def image_info(directory, filename):
    try:
        path = upload_path(directory, filename)
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ImageError("image_too_large")
        with Image.open(io.BytesIO(data)) as image:
            comment = image.info.get("comment", b"")
            source = (json.loads(comment[len(COMMENT_PREFIX):])
                      if isinstance(comment, bytes) and comment.startswith(COMMENT_PREFIX) else None)
            if isinstance(source, dict):
                # Read old JPEG provenance without rewriting the file or ZIPs.
                try:
                    source["rights"] = normalize_rights(source.get("rights"))
                except ImageError:
                    source["rights"] = {"status": "unverified"}
            else:
                source = None
            return {"filename": filename, "available": True, "sha256": hashlib.sha256(data).hexdigest(),
                    "width": image.width, "height": image.height, "source": source}
    except (ImageError, OSError, ValueError, Image.DecompressionBombError):
        return {"filename": filename, "available": False}
