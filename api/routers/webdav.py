"""Minimal WebDAV upload endpoint for phone auto-upload (PhotoSync et al.).

Exposes a deliberately small WebDAV subset under ``/dav`` so mobile
auto-upload apps can push photos straight into a Facet inbox directory that
``facet.py --watch`` then scores — the PhotoPrism mobile-sync pattern. This is
upload-only plumbing: it never touches user sessions or JWTs. Access is HTTP
Basic against shared-device credentials (``upload.username`` / ``upload.password``);
an empty username, password, or inbox directory disables the whole tree (404).

Every filesystem operation is confined to ``upload.inbox_dir``: each target is
canonicalised with ``os.path.realpath`` and re-checked against the inbox root, so
traversal (``../``), absolute paths, encoded traversal, and symlink escape all
land outside the root and are refused. Uploads stream to disk in chunks (never
buffered whole in RAM), enforce ``upload.max_file_mb``, and land atomically via a
temp file plus ``os.replace``.

Implemented methods: OPTIONS, PROPFIND (depth 0 and 1), MKCOL, PUT, MOVE,
DELETE, GET, HEAD. LOCK/UNLOCK are intentionally not implemented (upload clients
treat their absence as a non-locking share); PROPFIND depth ``infinity`` is
served as depth 1 (immediate children only).
"""

import base64
import hmac
import logging
import mimetypes
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from email.utils import formatdate
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webdav"])

DAV_PREFIX = "/dav"
DAV_NS = "DAV:"
_REALM = "Facet upload"
_DEFAULT_MAX_FILE_MB = 500
_TMP_PREFIX = ".facet-upload-"
_TMP_SUFFIX = ".part"
_MB = 1024 * 1024

_ALLOW_METHODS = "OPTIONS, GET, HEAD, PROPFIND, PUT, DELETE, MKCOL, MOVE"
_OPTIONS_HEADERS = {"DAV": "1", "Allow": _ALLOW_METHODS, "MS-Author-Via": "DAV"}
_UNAUTH_HEADERS = {"WWW-Authenticate": f'Basic realm="{_REALM}"'}
_OK_STATUS = "HTTP/1.1 200 OK"


class _TooLarge(Exception):
    """Raised when a streamed upload exceeds the configured size cap."""


def _upload_config() -> dict:
    from api.config import _FULL_CONFIG

    return _FULL_CONFIG.get("upload", {}) or {}


def _feature_enabled(cfg: dict) -> bool:
    return bool(cfg.get("username")) and bool(cfg.get("password")) and bool(cfg.get("inbox_dir"))


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication required", headers=_UNAUTH_HEADERS)


def _check_auth(request: Request, cfg: dict) -> None:
    """Validate HTTP Basic credentials constant-time as UTF-8 bytes.

    A missing, malformed, or wrong header yields 401 with a ``WWW-Authenticate``
    challenge so a WebDAV client re-sends with credentials.
    """
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise _unauthorized()
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise _unauthorized()
    username, sep, password = decoded.partition(":")
    if not sep:
        raise _unauthorized()
    user_ok = hmac.compare_digest(username.encode("utf-8"), str(cfg["username"]).encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), str(cfg["password"]).encode("utf-8"))
    if not (user_ok and pass_ok):
        raise _unauthorized()


def _inbox_root(cfg: dict) -> str:
    """Canonical inbox root, created on demand; 404 if it cannot be a directory."""
    root = os.path.realpath(str(cfg["inbox_dir"]))
    try:
        os.makedirs(root, exist_ok=True)
    except OSError:
        raise HTTPException(status_code=404, detail="Upload inbox is unavailable")
    if not os.path.isdir(root):
        raise HTTPException(status_code=404, detail="Upload inbox is unavailable")
    return root


def _gate(request: Request):
    """Enforce feature enablement (404) then Basic auth (401); return (cfg, root)."""
    cfg = _upload_config()
    if not _feature_enabled(cfg):
        raise HTTPException(status_code=404, detail="Upload feature is disabled")
    _check_auth(request, cfg)
    return cfg, _inbox_root(cfg)


def _resolve(root: str, subpath: str) -> str:
    """Resolve ``subpath`` under ``root``, rejecting any escape with 403.

    ``subpath`` is already URL-decoded by the router. Containment is enforced by
    canonicalising with ``realpath`` (which normalises ``..`` and resolves
    symlinks) and re-asserting the result stays under the inbox root.
    """
    if subpath and "\x00" in subpath:
        raise HTTPException(status_code=400, detail="Invalid path")
    candidate = os.path.join(root, subpath) if subpath else root
    real = os.path.realpath(candidate)
    if real != root and not real.startswith(root + os.sep):
        raise HTTPException(status_code=403, detail="Path escapes the upload inbox")
    return real


def _max_bytes(cfg: dict) -> int:
    try:
        mb = float(cfg.get("max_file_mb", _DEFAULT_MAX_FILE_MB))
    except (TypeError, ValueError):
        mb = _DEFAULT_MAX_FILE_MB
    if mb <= 0:
        mb = _DEFAULT_MAX_FILE_MB
    return int(mb * _MB)


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _qn(tag: str) -> str:
    return f"{{{DAV_NS}}}{tag}"


def _href(subpath: str, is_dir: bool) -> str:
    href = DAV_PREFIX + "/"
    if subpath:
        href += quote(subpath)
    if is_dir and not href.endswith("/"):
        href += "/"
    return href


def _append_response(multistatus: ET.Element, root: str, path: str) -> None:
    is_dir = os.path.isdir(path)
    rel = os.path.relpath(path, root)
    subpath = "" if rel == "." else rel.replace(os.sep, "/")
    st = os.stat(path)
    response = ET.SubElement(multistatus, _qn("response"))
    ET.SubElement(response, _qn("href")).text = _href(subpath, is_dir)
    propstat = ET.SubElement(response, _qn("propstat"))
    prop = ET.SubElement(propstat, _qn("prop"))
    ET.SubElement(prop, _qn("displayname")).text = os.path.basename(path.rstrip(os.sep)) or root
    resourcetype = ET.SubElement(prop, _qn("resourcetype"))
    if is_dir:
        ET.SubElement(resourcetype, _qn("collection"))
    else:
        ET.SubElement(prop, _qn("getcontentlength")).text = str(st.st_size)
    ET.SubElement(prop, _qn("getlastmodified")).text = formatdate(st.st_mtime, usegmt=True)
    ET.SubElement(propstat, _qn("status")).text = _OK_STATUS


def _build_propfind(root: str, real: str, depth: str) -> bytes:
    multistatus = ET.Element(_qn("multistatus"))
    _append_response(multistatus, root, real)
    if depth != "0" and os.path.isdir(real):
        for name in sorted(os.listdir(real)):
            _append_response(multistatus, root, os.path.join(real, name))
    return ET.tostring(multistatus, encoding="utf-8", xml_declaration=True)


async def dav_options(request: Request, subpath: str = ""):
    _gate(request)
    return Response(status_code=200, headers=dict(_OPTIONS_HEADERS))


async def dav_propfind(request: Request, subpath: str = ""):
    _, root = _gate(request)
    real = _resolve(root, subpath)
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="Not found")
    depth = (request.headers.get("depth") or "1").strip().lower()
    xml = _build_propfind(root, real, depth)
    return Response(content=xml, status_code=207, media_type="application/xml; charset=utf-8")


async def dav_mkcol(request: Request, subpath: str = ""):
    _, root = _gate(request)
    real = _resolve(root, subpath)
    if os.path.exists(real):
        raise HTTPException(status_code=405, detail="Resource already exists")
    if not os.path.isdir(os.path.dirname(real)):
        raise HTTPException(status_code=409, detail="Parent collection does not exist")
    try:
        os.mkdir(real)
    except OSError:
        raise HTTPException(status_code=409, detail="Could not create collection")
    return Response(status_code=201)


async def dav_put(request: Request, subpath: str = ""):
    cfg, root = _gate(request)
    real = _resolve(root, subpath)
    parent = os.path.dirname(real)
    if not os.path.isdir(parent):
        raise HTTPException(status_code=409, detail="Parent collection does not exist")
    if os.path.isdir(real):
        raise HTTPException(status_code=405, detail="Cannot PUT onto a collection")
    existed = os.path.exists(real)
    max_bytes = _max_bytes(cfg)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=_TMP_PREFIX, suffix=_TMP_SUFFIX)
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > max_bytes:
                    raise _TooLarge()
                out.write(chunk)
        os.replace(tmp, real)
    except _TooLarge:
        _safe_unlink(tmp)
        raise HTTPException(status_code=413, detail="File exceeds upload.max_file_mb")
    except BaseException:
        _safe_unlink(tmp)
        raise
    return Response(status_code=204 if existed else 201)


def _parse_destination(header: str) -> str:
    if not header:
        raise HTTPException(status_code=400, detail="Missing Destination header")
    path = unquote(urlsplit(header).path)
    if path != DAV_PREFIX and not path.startswith(DAV_PREFIX + "/"):
        raise HTTPException(status_code=403, detail="Destination outside share")
    return path[len(DAV_PREFIX):].lstrip("/")


async def dav_move(request: Request, subpath: str = ""):
    _, root = _gate(request)
    src = _resolve(root, subpath)
    if src == root:
        raise HTTPException(status_code=403, detail="Refusing to move the inbox root")
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="Source not found")
    dest = _resolve(root, _parse_destination(request.headers.get("destination", "")))
    if dest == root:
        raise HTTPException(status_code=403, detail="Invalid destination")
    if not os.path.isdir(os.path.dirname(dest)):
        raise HTTPException(status_code=409, detail="Destination parent missing")
    dest_existed = os.path.exists(dest)
    overwrite = (request.headers.get("overwrite") or "T").strip().upper() != "F"
    if dest_existed and not overwrite:
        raise HTTPException(status_code=412, detail="Destination exists")
    if dest_existed:
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        else:
            os.remove(dest)
    shutil.move(src, dest)
    return Response(status_code=204 if dest_existed else 201)


async def dav_delete(request: Request, subpath: str = ""):
    _, root = _gate(request)
    real = _resolve(root, subpath)
    if real == root:
        raise HTTPException(status_code=403, detail="Refusing to delete the inbox root")
    if not os.path.exists(real):
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.isdir(real):
        shutil.rmtree(real)
    else:
        os.remove(real)
    return Response(status_code=204)


async def dav_get(request: Request, subpath: str = ""):
    _, root = _gate(request)
    real = _resolve(root, subpath)
    if os.path.isdir(real):
        raise HTTPException(status_code=405, detail="Cannot GET a collection")
    if not os.path.isfile(real):
        raise HTTPException(status_code=404, detail="Not found")
    media = mimetypes.guess_type(real)[0] or "application/octet-stream"
    if request.method == "HEAD":
        st = os.stat(real)
        headers = {
            "Content-Length": str(st.st_size),
            "Last-Modified": formatdate(st.st_mtime, usegmt=True),
        }
        return Response(status_code=200, media_type=media, headers=headers)
    return FileResponse(real, media_type=media)


_HANDLERS = (
    (["OPTIONS"], dav_options),
    (["PROPFIND"], dav_propfind),
    (["MKCOL"], dav_mkcol),
    (["PUT"], dav_put),
    (["MOVE"], dav_move),
    (["DELETE"], dav_delete),
    (["GET", "HEAD"], dav_get),
)

for _methods, _handler in _HANDLERS:
    for _path in (DAV_PREFIX, DAV_PREFIX + "/{subpath:path}"):
        router.add_api_route(_path, _handler, methods=_methods, include_in_schema=False)
