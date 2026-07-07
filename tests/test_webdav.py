"""Tests for the minimal WebDAV upload endpoint (api/routers/webdav.py).

Covers the feature gate (unconfigured ⇒ 404), HTTP Basic auth (missing / wrong
⇒ 401 + WWW-Authenticate), the implemented method subset and status codes
(OPTIONS, PROPFIND depth 0/1, MKCOL, PUT, MOVE, DELETE), atomic streamed uploads
with the ``max_file_mb`` cap, and the filesystem-containment boundary
(traversal, absolute paths, encoded traversal, symlink escape all refused with
nothing written outside the inbox), plus XML escaping of hostile filenames.

Auth here is HTTP Basic validated against the ``upload`` config block, not a
FastAPI user dependency, so the plain ``client`` fixture drives the real code
path; the ``upload`` block is patched in place on ``api.config._FULL_CONFIG``
(the object ``_upload_config`` reads at call time), never via ``mock.patch``.
"""

import os
import xml.etree.ElementTree as ET

import pytest

from api.routers.webdav import _TMP_PREFIX, _TMP_SUFFIX

USER = "phone"
PASSWORD = "s3cret-upload-pass"
WRONG = ("phone", "nope")
NS = "DAV:"
AUTH = (USER, PASSWORD)


@pytest.fixture()
def inbox(tmp_path):
    """Enable the upload feature against a fresh inbox; yield its real path.

    ``max_file_mb`` is set tiny (0.001 MB ≈ 1 KiB) so the oversize test uses a
    cheap in-memory body. The prior ``upload`` block is restored on teardown.
    """
    from api import config

    prev = config._FULL_CONFIG.get("upload")
    root = tmp_path / "inbox"
    root.mkdir()
    config._FULL_CONFIG["upload"] = {
        "username": USER,
        "password": PASSWORD,
        "inbox_dir": str(root),
        "max_file_mb": 0.001,
    }
    yield type(root)(os.path.realpath(str(root)))
    if prev is None:
        config._FULL_CONFIG.pop("upload", None)
    else:
        config._FULL_CONFIG["upload"] = prev


def _parse_multistatus(content):
    root = ET.fromstring(content)
    out = {}
    for resp in root.findall(f"{{{NS}}}response"):
        prop = resp.find(f"{{{NS}}}propstat/{{{NS}}}prop")
        name = prop.findtext(f"{{{NS}}}displayname")
        resourcetype = prop.find(f"{{{NS}}}resourcetype")
        is_col = resourcetype is not None and resourcetype.find(f"{{{NS}}}collection") is not None
        out[name] = {
            "is_col": is_col,
            "length": prop.findtext(f"{{{NS}}}getcontentlength"),
            "href": resp.findtext(f"{{{NS}}}href"),
        }
    return out


def _no_temp_files(inbox):
    return not any(
        n.startswith(_TMP_PREFIX) or n.endswith(_TMP_SUFFIX)
        for n in os.listdir(inbox)
    )


# --- Feature gate / auth ---------------------------------------------------

class TestGate:
    def test_disabled_feature_returns_404(self, client):
        from api import config

        prev = config._FULL_CONFIG.get("upload")
        config._FULL_CONFIG["upload"] = {"username": "", "password": "", "inbox_dir": ""}
        try:
            resp = client.request("OPTIONS", "/dav/", auth=AUTH)
            assert resp.status_code == 404
            resp = client.request("PROPFIND", "/dav/", auth=AUTH)
            assert resp.status_code == 404
        finally:
            if prev is None:
                config._FULL_CONFIG.pop("upload", None)
            else:
                config._FULL_CONFIG["upload"] = prev

    def test_missing_auth_401_with_challenge(self, client, inbox):
        resp = client.request("PROPFIND", "/dav/")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == 'Basic realm="Facet upload"'

    def test_wrong_auth_401(self, client, inbox):
        resp = client.request("PROPFIND", "/dav/", auth=WRONG)
        assert resp.status_code == 401
        assert "www-authenticate" in resp.headers

    def test_options_advertises_dav_and_methods(self, client, inbox):
        resp = client.request("OPTIONS", "/dav/", auth=AUTH)
        assert resp.status_code == 200
        assert "1" in resp.headers["dav"]
        allow = resp.headers["allow"]
        for method in ("OPTIONS", "GET", "HEAD", "PROPFIND", "PUT", "DELETE", "MKCOL", "MOVE"):
            assert method in allow


# --- PROPFIND --------------------------------------------------------------

class TestPropfind:
    def test_depth_0_root_returns_207(self, client, inbox):
        resp = client.request("PROPFIND", "/dav/", auth=AUTH, headers={"Depth": "0"})
        assert resp.status_code == 207
        assert resp.headers["content-type"].startswith("application/xml")
        entries = _parse_multistatus(resp.content)
        assert len(entries) == 1
        root_entry = next(iter(entries.values()))
        assert root_entry["is_col"] is True
        assert root_entry["href"] == "/dav/"

    def test_depth_1_lists_uploaded_file_with_size(self, client, inbox):
        body = b"hello webdav"
        put = client.request("PUT", "/dav/shot.jpg", auth=AUTH, content=body)
        assert put.status_code == 201
        resp = client.request("PROPFIND", "/dav/", auth=AUTH, headers={"Depth": "1"})
        assert resp.status_code == 207
        entries = _parse_multistatus(resp.content)
        assert "shot.jpg" in entries
        assert entries["shot.jpg"]["is_col"] is False
        assert entries["shot.jpg"]["length"] == str(len(body))

    def test_propfind_missing_resource_404(self, client, inbox):
        resp = client.request("PROPFIND", "/dav/nope.jpg", auth=AUTH, headers={"Depth": "0"})
        assert resp.status_code == 404

    def test_xml_escaping_round_trips(self, client, inbox):
        name = "a & b <c>.jpg"
        (inbox / name).write_bytes(b"x")
        resp = client.request("PROPFIND", "/dav/", auth=AUTH, headers={"Depth": "1"})
        assert resp.status_code == 207
        assert b"&amp;" in resp.content
        entries = _parse_multistatus(resp.content)
        assert name in entries


# --- MKCOL -----------------------------------------------------------------

class TestMkcol:
    def test_mkcol_creates_dir(self, client, inbox):
        resp = client.request("MKCOL", "/dav/album", auth=AUTH)
        assert resp.status_code == 201
        assert (inbox / "album").is_dir()

    def test_mkcol_existing_405(self, client, inbox):
        (inbox / "album").mkdir()
        resp = client.request("MKCOL", "/dav/album", auth=AUTH)
        assert resp.status_code == 405

    def test_mkcol_missing_parent_409(self, client, inbox):
        resp = client.request("MKCOL", "/dav/missing/child", auth=AUTH)
        assert resp.status_code == 409


# --- PUT -------------------------------------------------------------------

class TestPut:
    def test_put_new_file_201_and_content(self, client, inbox):
        body = b"jpeg-bytes-here"
        resp = client.request("PUT", "/dav/a.jpg", auth=AUTH, content=body)
        assert resp.status_code == 201
        assert (inbox / "a.jpg").read_bytes() == body
        assert _no_temp_files(inbox)

    def test_put_overwrite_204(self, client, inbox):
        client.request("PUT", "/dav/a.jpg", auth=AUTH, content=b"one")
        resp = client.request("PUT", "/dav/a.jpg", auth=AUTH, content=b"two")
        assert resp.status_code == 204
        assert (inbox / "a.jpg").read_bytes() == b"two"
        assert _no_temp_files(inbox)

    def test_put_into_subdir(self, client, inbox):
        client.request("MKCOL", "/dav/sub", auth=AUTH)
        resp = client.request("PUT", "/dav/sub/b.jpg", auth=AUTH, content=b"in-sub")
        assert resp.status_code == 201
        assert (inbox / "sub" / "b.jpg").read_bytes() == b"in-sub"

    def test_put_missing_parent_409(self, client, inbox):
        resp = client.request("PUT", "/dav/nodir/c.jpg", auth=AUTH, content=b"x")
        assert resp.status_code == 409

    def test_put_exceeding_max_413_no_partial(self, client, inbox):
        body = b"x" * 5000
        resp = client.request("PUT", "/dav/big.jpg", auth=AUTH, content=body)
        assert resp.status_code == 413
        assert not (inbox / "big.jpg").exists()
        assert _no_temp_files(inbox)


# --- MOVE ------------------------------------------------------------------

class TestMove:
    def test_move_renames_within_inbox_201(self, client, inbox):
        client.request("PUT", "/dav/tmp-name.part", auth=AUTH, content=b"payload")
        resp = client.request(
            "MOVE", "/dav/tmp-name.part", auth=AUTH,
            headers={"Destination": "http://testserver/dav/final.jpg"},
        )
        assert resp.status_code == 201
        assert not (inbox / "tmp-name.part").exists()
        assert (inbox / "final.jpg").read_bytes() == b"payload"

    def test_move_overwrite_204(self, client, inbox):
        client.request("PUT", "/dav/src.jpg", auth=AUTH, content=b"new")
        client.request("PUT", "/dav/dst.jpg", auth=AUTH, content=b"old")
        resp = client.request(
            "MOVE", "/dav/src.jpg", auth=AUTH,
            headers={"Destination": "http://testserver/dav/dst.jpg"},
        )
        assert resp.status_code == 204
        assert (inbox / "dst.jpg").read_bytes() == b"new"

    def test_move_destination_outside_403(self, client, inbox):
        client.request("PUT", "/dav/src.jpg", auth=AUTH, content=b"payload")
        resp = client.request(
            "MOVE", "/dav/src.jpg", auth=AUTH,
            headers={"Destination": "http://testserver/etc/evil.jpg"},
        )
        assert resp.status_code == 403
        assert (inbox / "src.jpg").exists()

    def test_move_missing_source_404(self, client, inbox):
        resp = client.request(
            "MOVE", "/dav/ghost.jpg", auth=AUTH,
            headers={"Destination": "http://testserver/dav/x.jpg"},
        )
        assert resp.status_code == 404

    def test_move_root_refused_403(self, client, inbox):
        resp = client.request(
            "MOVE", "/dav/", auth=AUTH,
            headers={"Destination": "http://testserver/dav/sub"},
        )
        assert resp.status_code == 403
        assert inbox.is_dir()

    def test_move_overwrite_false_conflict_412(self, client, inbox):
        client.request("PUT", "/dav/src.jpg", auth=AUTH, content=b"new")
        client.request("PUT", "/dav/dst.jpg", auth=AUTH, content=b"old")
        resp = client.request(
            "MOVE", "/dav/src.jpg", auth=AUTH,
            headers={
                "Destination": "http://testserver/dav/dst.jpg",
                "Overwrite": "F",
            },
        )
        assert resp.status_code == 412
        assert (inbox / "dst.jpg").read_bytes() == b"old"
        assert (inbox / "src.jpg").exists()

    def test_move_missing_destination_400(self, client, inbox):
        client.request("PUT", "/dav/src.jpg", auth=AUTH, content=b"payload")
        resp = client.request("MOVE", "/dav/src.jpg", auth=AUTH)
        assert resp.status_code == 400
        assert (inbox / "src.jpg").exists()


# --- DELETE ----------------------------------------------------------------

class TestDelete:
    def test_delete_removes_file(self, client, inbox):
        (inbox / "gone.jpg").write_bytes(b"x")
        resp = client.request("DELETE", "/dav/gone.jpg", auth=AUTH)
        assert resp.status_code == 204
        assert not (inbox / "gone.jpg").exists()

    def test_delete_missing_404(self, client, inbox):
        resp = client.request("DELETE", "/dav/never.jpg", auth=AUTH)
        assert resp.status_code == 404

    def test_delete_removes_directory_recursively(self, client, inbox):
        client.request("MKCOL", "/dav/album", auth=AUTH)
        client.request("PUT", "/dav/album/child.jpg", auth=AUTH, content=b"x")
        resp = client.request("DELETE", "/dav/album", auth=AUTH)
        assert resp.status_code == 204
        assert not (inbox / "album").exists()
        assert not (inbox / "album" / "child.jpg").exists()


# --- Containment -----------------------------------------------------------

class TestContainment:
    def test_encoded_traversal_403(self, client, inbox, tmp_path):
        target = tmp_path / "escaped.jpg"
        resp = client.request(
            "PUT", "/dav/%2E%2E/%2E%2E/escaped.jpg", auth=AUTH, content=b"pwned",
        )
        assert resp.status_code == 403
        assert not target.exists()

    def test_absolute_path_refused(self, client, inbox):
        resp = client.request("PROPFIND", "/dav//etc/hosts.jpg", auth=AUTH, headers={"Depth": "0"})
        assert resp.status_code in (403, 404)

    def test_symlink_escape_put_403(self, client, inbox, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (inbox / "escape").symlink_to(outside, target_is_directory=True)
        resp = client.request("PUT", "/dav/escape/evil.jpg", auth=AUTH, content=b"pwned")
        assert resp.status_code == 403
        assert not (outside / "evil.jpg").exists()
        assert list(outside.iterdir()) == []

    def test_symlink_escape_propfind_403(self, client, inbox, tmp_path):
        outside = tmp_path / "outside2"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"top secret")
        (inbox / "escape2").symlink_to(outside, target_is_directory=True)
        resp = client.request("PROPFIND", "/dav/escape2", auth=AUTH, headers={"Depth": "1"})
        assert resp.status_code == 403

    def test_null_byte_path_400(self, client, inbox):
        resp = client.request("PUT", "/dav/%00evil.jpg", auth=AUTH, content=b"x")
        assert resp.status_code == 400


# --- GET / HEAD ------------------------------------------------------------

class TestGetHead:
    def test_get_serves_file_within_share(self, client, inbox):
        (inbox / "d.jpg").write_bytes(b"content")
        resp = client.get("/dav/d.jpg", auth=AUTH)
        assert resp.status_code == 200
        assert resp.content == b"content"

    def test_head_returns_length_no_body(self, client, inbox):
        (inbox / "d.jpg").write_bytes(b"content")
        resp = client.request("HEAD", "/dav/d.jpg", auth=AUTH)
        assert resp.status_code == 200
        assert resp.headers["content-length"] == str(len(b"content"))
        assert resp.content == b""

    def test_get_missing_404(self, client, inbox):
        resp = client.get("/dav/absent.jpg", auth=AUTH)
        assert resp.status_code == 404

    def test_get_on_collection_405(self, client, inbox):
        client.request("MKCOL", "/dav/album", auth=AUTH)
        resp = client.get("/dav/album", auth=AUTH)
        assert resp.status_code == 405
        resp = client.request("HEAD", "/dav/album", auth=AUTH)
        assert resp.status_code == 405
