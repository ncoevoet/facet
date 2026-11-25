"""Reference set fetch script (issue #393): build, verify, quarantine, resume and pin, no network.

Photos are tiny Pillow images served by a ``ThreadingHTTPServer`` on an ephemeral 127.0.0.1 port.
"""

import copy
import email.utils
import hashlib
import io
import json
import random
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

TESTDB = Path(__file__).resolve().parent.parent / "testdb"
if str(TESTDB) not in sys.path:
    sys.path.insert(0, str(TESTDB))

import licence_check as lc  # noqa: E402
import make_reference_set as mrs  # noqa: E402
import reference_common as rc  # noqa: E402

CASE = "landscape"
FAST = ["--allow-anywhere", "--delay", "0", "--backoff", "0"]
RECIPE = "resize:32;reencode_jpeg:60"
P1 = "categories/landscape/p1.jpg"


def jpeg_bytes(seed, size=(64, 48)):
    rng = random.Random(seed)
    img = Image.frombytes("RGB", size, bytes(rng.randrange(256) for _ in range(size[0] * size[1] * 3)))
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


class Server:
    def __init__(self):
        self.files, self.hits, self.flaky = {}, {}, {}
        self.retry_after = "0"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.hits[self.path] = owner.hits.get(self.path, 0) + 1
                if owner.flaky.get(self.path, 0) > 0:
                    owner.flaky[self.path] -= 1
                    self.send_response(503)
                    self.send_header("Retry-After", owner.retry_after)
                    self.end_headers()
                    return
                body = owner.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def add(self, name, body):
        self.files["/" + name] = body
        return f"{self.base}/{name}"


@pytest.fixture
def server():
    srv = Server()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def entry(index, url, body, **overrides):
    photo = {
        "id": f"p{index}", "path": f"categories/landscape/p{index}.jpg", "url": url,
        "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "kind": "download",
        "derived_from": None, "recipe": None, "pixel_sha256": None, "licence": "CC0-1.0",
        "author": "A. Author", "source_page": f"https://example.org/p{index}",
        "attribution": "A. Author, CC0", "approved_by": "licence-check", "approved_on": "2026-11-25",
        "licence_evidence": {"api_url": "https://example.org/api", "license_short_name": "CC0"},
        "cases": [CASE], "expected_category": "landscape", "acceptable_categories": ["landscape"],
        "labeller": "maintainer (reviewed)", "reviewed": True, "sequence": None,
        "companion_of": None, "scored": True, "megapixels": 0.003, "format": "jpeg", "notes": "",
    }
    photo.update(overrides)
    return photo


@pytest.fixture
def setup(server, tmp_path):
    """(manifest path, manifest, out dir, server): three downloads of the landscape case."""
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["cases"][CASE]["known_gap"] = None
    bodies = {i: jpeg_bytes(i) for i in (1, 2, 3)}
    manifest["photos"] = [entry(i, server.add(f"p{i}.jpg", bodies[i]), bodies[i]) for i in bodies]
    path = tmp_path / "manifest.json"
    mrs.write_manifest(manifest, path)
    return path, manifest, tmp_path / "out", server


def run(path, out, *extra):
    return mrs.main(["--manifest", str(path), "--out", str(out), *FAST, *extra])


def pin(path, out, approved):
    file = out.parent / "approved.json"
    file.write_text(json.dumps(approved))
    return mrs.main(["--pin", str(file), "--manifest", str(path), "--out", str(out), *FAST])


def add_derived(manifest, out, recipe=RECIPE):
    """Append a derived photo of p1; its hashes come from a render of the already built base."""
    target = out.parent / "scratch_derived.jpg"
    mrs.render_derived(out / "photos" / P1, recipe, target)
    photo = entry(
        9, None, b"x", kind="derived", path="derived/landscape/d9.jpg", derived_from="p1",
        recipe=recipe, pixel_sha256=mrs.pixel_sha256(target),
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size,
    )
    manifest["photos"].append(photo)
    return photo


def test_build_then_verify_only(setup):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    for p in manifest["photos"]:
        assert (out / "photos" / p["path"]).read_bytes()
    lock = json.loads((out / "manifest.lock.json").read_text())
    assert lock["file_level_digest"] == rc.file_level_digest(manifest)
    assert lock["photos"]["p1"]["sha256"] == manifest["photos"][0]["sha256"]
    assert run(path, out, "--verify-only") == 0


def test_flipped_byte_is_reported_and_kept(setup, capsys):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    victim = out / "photos" / manifest["photos"][1]["path"]
    data = bytearray(victim.read_bytes())
    data[10] ^= 0xFF
    victim.write_bytes(bytes(data))
    capsys.readouterr()
    assert run(path, out, "--verify-only") == 1
    assert "mismatch p2" in capsys.readouterr().out
    assert victim.read_bytes() == bytes(data)


def test_hash_mismatch_on_download_is_quarantined(setup, capsys):
    path, manifest, out, srv = setup
    srv.files["/p2.jpg"] = jpeg_bytes(99)
    assert run(path, out) == 1
    text = capsys.readouterr().out
    assert "mismatch p2" in text and "expected" in text
    assert (out / "photos" / "categories/landscape/p2.jpg.bad").read_bytes() == jpeg_bytes(99)
    assert not (out / "photos" / manifest["photos"][1]["path"]).exists()


def test_404_is_missing(setup, capsys):
    path, _, out, srv = setup
    del srv.files["/p3.jpg"]
    assert run(path, out) == 1
    assert "missing p3" in capsys.readouterr().out


def test_retry_on_503(setup):
    path, _, out, srv = setup
    srv.flaky["/p1.jpg"] = 2
    assert run(path, out) == 0
    assert srv.hits["/p1.jpg"] == 3


def test_resume_skips_verified_files(setup):
    path, _, out, srv = setup
    assert run(path, out) == 0
    srv.hits.clear()
    assert run(path, out, "--resume") == 0
    assert srv.hits == {}
    (out / "photos" / "categories/landscape/p3.jpg").write_bytes(b"junk")
    assert run(path, out, "--resume") == 0
    assert srv.hits == {"/p3.jpg": 1}
    assert (out / "photos" / "categories/landscape/p3.jpg.bad").read_bytes() == b"junk"


def test_non_empty_out_is_refused(setup, capsys):
    path, _, out, srv = setup
    out.mkdir()
    (out / "something").write_text("x")
    assert run(path, out) == 2
    assert "not empty" in capsys.readouterr().err
    assert srv.hits == {}


def test_out_inside_repo_or_on_c_is_refused(setup, capsys):
    path, _, _, srv = setup
    inside = mrs.REPO_DIR / "reference_fetch_test_out"
    assert mrs.main(["--manifest", str(path), "--out", str(inside), "--delay", "0"]) == 2
    assert "inside the checkout" in capsys.readouterr().err
    assert not inside.exists() and srv.hits == {}
    with pytest.raises(ValueError, match="drive C"):
        mrs.check_out(Path("C:/facet-ref-test"), False)


def test_derived_recipe_reproduces_pixel_hash(setup):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    derived = add_derived(manifest, out)
    mrs.write_manifest(manifest, path)
    dest = out / "photos" / derived["path"]
    assert run(path, out, "--resume") == 0
    with Image.open(dest) as img:  # independent recomputation of the documented definition
        rgb = img.convert("RGB")
    expect = hashlib.sha256(f"RGB:{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()).hexdigest()
    assert expect == derived["pixel_sha256"] == mrs.pixel_sha256(dest)
    assert max(rgb.size) == 32
    assert run(path, out, "--verify-only") == 0
    derived["pixel_sha256"] = "0" * 64
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--verify-only") == 1
    assert run(path, out, "--resume") == 1
    assert dest.with_name(dest.name + ".bad").exists()


@pytest.mark.parametrize("recipe", [
    "rotate:90", "resize", "resize:x", "reencode_jpeg:0", "strip_exif:1", "set_exif_orientation:9", "",
])
def test_unknown_or_malformed_recipe_rejected(recipe):
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe(recipe)


def test_unknown_recipe_in_manifest_exits_2(setup, capsys):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    add_derived(manifest, out)
    manifest["photos"][-1]["recipe"] = "sharpen:3"
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--resume") == 2
    assert "unknown recipe op" in capsys.readouterr().err


@pytest.mark.parametrize("recipe", [
    "crop:0,0,16,16", "strip_exif", "set_exif_orientation:6", "convert_icc:srgb",
    "to_cmyk", "to_grayscale", "to_sepia",
])
def test_every_recipe_op_runs_and_is_stable(tmp_path, recipe):
    base = tmp_path / "b.jpg"
    base.write_bytes(jpeg_bytes(5))
    first, second = tmp_path / "a.jpg", tmp_path / "c.jpg"
    mrs.render_derived(base, recipe, first)
    mrs.render_derived(base, recipe, second)
    assert mrs.pixel_sha256(first) == mrs.pixel_sha256(second)


def test_pin_mode_fills_hashes(setup, server):
    path, _, out, _ = setup
    body = jpeg_bytes(42)
    new = entry(4, server.add("p4.jpg", body), body)
    for key in ("sha256", "bytes", "megapixels", "derived_from", "recipe", "pixel_sha256", "sequence", "companion_of"):
        del new[key]
    assert pin(path, out, [new]) == 0
    raw = path.read_bytes()
    pinned = rc.load_manifest(path)["photos"][-1]
    assert pinned["id"] == "p4" and pinned["sha256"] == hashlib.sha256(body).hexdigest()
    assert pinned["bytes"] == len(body) and pinned["megapixels"] == 0.003
    assert (out / "photos" / pinned["path"]).read_bytes() == body
    assert list(pinned)[:5] == ["id", "path", "url", "sha256", "bytes"]
    assert not [e for e in rc.validate(rc.load_manifest(path)) if "p4" in e]
    assert raw.endswith(b"}\n") and b"\r" not in raw


def test_pin_same_id_different_url_is_an_error(setup, server, capsys):
    path, _, out, _ = setup
    body = jpeg_bytes(77)
    clash = entry(1, server.add("other.jpg", body), body)
    before = rc.load_manifest(path)["photos"]
    assert pin(path, out, [clash]) == 1
    assert "different url" in capsys.readouterr().out
    assert rc.load_manifest(path)["photos"] == before


def test_pin_download_failure_skips_entry_only(setup, server, capsys):
    path, _, out, _ = setup
    body = jpeg_bytes(55)
    good = entry(5, server.add("p5.jpg", body), body)
    bad = entry(6, server.base + "/nope.jpg", body)
    assert pin(path, out, [bad, good]) == 1
    ids = [p["id"] for p in rc.load_manifest(path)["photos"]]
    assert "p5" in ids and "p6" not in ids
    assert "skipped p6" in capsys.readouterr().out


def test_pin_derived_records_pixel_hash(setup):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    derived = add_derived(manifest, out)
    manifest["photos"].pop()
    mrs.write_manifest(manifest, path)
    partial = {k: v for k, v in derived.items() if k not in ("sha256", "bytes", "pixel_sha256", "megapixels")}
    assert pin(path, out, [partial]) == 0
    pinned = rc.load_manifest(path)["photos"][-1]
    assert pinned["pixel_sha256"] == derived["pixel_sha256"] and pinned["bytes"] > 0


def test_only_filters_by_case(setup):
    path, manifest, out, srv = setup
    manifest["photos"][1]["cases"] = ["landscape", "macro"]
    manifest["cases"]["macro"]["known_gap"] = None
    manifest["cases"]["macro"]["min_photos"] = 1
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--only", "macro") == 0
    assert srv.hits == {"/p2.jpg": 1}
    assert run(path, out, "--only", "nonsense", "--resume") == 2


# --- placeholder known gaps -----------------------------------------------------------------


def bare(index, server, seed=None):
    """A pin entry as licence_check leaves it: no hashes, no megapixels, no labels."""
    body = jpeg_bytes(seed or index + 100)
    new = entry(index, server.add(f"p{index}.jpg", body), body)
    for key in ("sha256", "bytes", "megapixels", "derived_from", "recipe", "pixel_sha256", "sequence", "companion_of"):
        del new[key]
    return new, body


def test_pin_clears_placeholder_gap_and_manifest_validates(server, tmp_path, capsys):
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["photos"] = []
    assert manifest["cases"][CASE]["known_gap"] == mrs.PLACEHOLDER_GAP
    path, out = tmp_path / "manifest.json", tmp_path / "out"
    mrs.write_manifest(manifest, path)
    assert pin(path, out, [bare(i, server)[0] for i in (1, 2)]) == 0  # only the count error is left
    pinned = rc.load_manifest(path)
    assert pinned["cases"][CASE]["known_gap"] is None
    errors = rc.validate(pinned)
    assert len(errors) == 1 and mrs.COUNT_ERROR.match(errors[0]), errors
    assert pin(path, out, [bare(3, server)[0]]) == 0
    assert rc.validate(rc.load_manifest(path)) == []


def test_pin_into_case_with_other_gap_is_an_error(server, tmp_path, capsys):
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["photos"] = []
    manifest["cases"][CASE]["known_gap"] = "no CC0 source exists"
    path, out = tmp_path / "manifest.json", tmp_path / "out"
    mrs.write_manifest(manifest, path)
    new, _ = bare(1, server)
    assert pin(path, out, [new]) == 1
    assert "no CC0 source exists" in capsys.readouterr().out
    after = rc.load_manifest(path)
    assert after["photos"] == [] and after["cases"][CASE]["known_gap"] == "no CC0 source exists"
    assert server.hits == {}  # refused before downloading


def test_count_error_matches_the_validators_message():
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["photos"] = []
    manifest["cases"][CASE]["known_gap"] = None
    errors = [e for e in rc.validate(manifest) if CASE in e]
    assert errors and all(mrs.COUNT_ERROR.match(e) for e in errors)
    assert not mrs.COUNT_ERROR.match(f"case {CASE}: known gap but has 2 photos")


# --- --out safety ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "\\\\host\\share\\x", "//host/share/x", "\\\\?\\UNC\\host\\share\\x", "\\\\localhost\\C$\\x",
    "//localhost/c$/x",
])
def test_network_out_is_refused_even_with_allow_anywhere(setup, raw, capsys):
    path, _, _, srv = setup
    assert mrs.main(["--manifest", str(path), "--out", raw, *FAST]) == 2
    assert "network path" in capsys.readouterr().err
    assert srv.hits == {}
    with pytest.raises(ValueError, match="network path"):
        mrs.check_out(Path(raw), True)


def test_out_inside_any_worktree_or_protected_tree_is_refused(tmp_path, monkeypatch):
    sibling, protected = tmp_path / "sibling-worktree", tmp_path / "photo-llm"
    monkeypatch.setattr(mrs, "worktree_roots", lambda: [mrs.REPO_DIR, sibling])
    monkeypatch.setattr(mrs, "PROTECTED_TREES", (str(protected),))
    for inside in (sibling / "out", sibling, protected / "photos", protected):
        with pytest.raises(ValueError, match="inside"):
            mrs.check_out(inside, False)
    elsewhere = tmp_path / "elsewhere" / "out"
    assert mrs.check_out(elsewhere, False) == elsewhere.resolve()
    assert mrs.check_out(sibling / "out", True)  # --allow-anywhere is the test escape hatch


def test_real_worktree_list_contains_this_checkout():
    roots = [str(r).lower().replace("\\", "/") for r in mrs.worktree_roots()]
    assert str(mrs.REPO_DIR).lower().replace("\\", "/") in roots


@pytest.mark.parametrize("raw", ["c:/facet-ref-test", "C:/facet-ref-test", "c:\\x\\y", "C:\\x"])
def test_drive_c_is_refused_in_any_letter_case(raw):
    with pytest.raises(ValueError, match="drive C"):
        mrs.check_out(Path(raw), False)


@pytest.mark.parametrize("raw,expected", [("c:/x", True), ("C:/x", True), ("d:/x", False), ("c", False)])
def test_on_drive_c_ignores_letter_case(raw, expected):
    # Path.resolve() upper-cases the drive on Windows, so only the helper itself can tell
    assert mrs.on_drive_c(raw) is expected


def test_pin_refuses_a_foreign_non_empty_out(setup, server, capsys):
    path, _, out, srv = setup
    out.mkdir()
    foreign = out / "holiday.jpg"
    foreign.write_bytes(b"precious")
    new, _ = bare(4, server)
    assert pin(path, out, [new]) == 2
    assert "holds no manifest.lock.json" in capsys.readouterr().err
    assert foreign.read_bytes() == b"precious" and sorted(p.name for p in out.iterdir()) == ["holiday.jpg"]
    assert srv.hits == {}
    assert run(path, out, "--resume") == 2 and run(path, out, "--verify-only") == 2


def test_pin_accepts_an_out_this_script_wrote(setup, server):
    path, _, out, _ = setup
    assert run(path, out) == 0
    new, _ = bare(4, server)
    assert pin(path, out, [new]) == 0


# --- megapixels -----------------------------------------------------------------------------


def test_megapixels_of_heic_needs_the_heif_opener(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    target = tmp_path / "tiny.heic"
    pillow_heif.from_pillow(Image.new("RGB", (64, 48), (10, 120, 200))).save(target)
    assert mrs.megapixels_of(target, "heic") == (0.003, "")


def test_megapixels_of_jxl_via_imagecodecs(tmp_path):
    imagecodecs = pytest.importorskip("imagecodecs")
    np = pytest.importorskip("numpy")
    if not imagecodecs.JPEGXL.available:
        pytest.skip("no JPEG XL codec")
    target = tmp_path / "tiny.jxl"
    target.write_bytes(imagecodecs.jpegxl_encode(np.zeros((48, 64, 3), dtype=np.uint8), lossless=True))
    assert mrs.megapixels_of(target, "jxl") == (0.003, "")


def test_megapixels_unknown_is_a_note_not_a_crash(tmp_path):
    target = tmp_path / "bad.heic"
    target.write_bytes(b"not an image")
    mp, note = mrs.megapixels_of(target, "heic")
    assert mp is None and "megapixels unknown" in note


# --- corrupt derived files ------------------------------------------------------------------


def test_truncated_derived_file_is_a_mismatch_not_a_crash(setup, capsys):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    derived = add_derived(manifest, out)
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--resume") == 0
    dest = out / "photos" / derived["path"]
    good = dest.read_bytes()
    dest.write_bytes(good[: len(good) // 2])
    capsys.readouterr()
    assert run(path, out, "--verify-only") == 1
    assert "mismatch p9" in capsys.readouterr().out
    assert run(path, out, "--resume") == 0  # re-derived, the broken file kept as .bad
    assert dest.with_name(dest.name + ".bad").read_bytes() == good[: len(good) // 2]
    assert run(path, out, "--verify-only") == 0
    dest.write_bytes(b"")
    assert mrs.verify_on_disk(derived, dest)[0] == "mismatch"


def test_pin_derived_from_a_corrupt_base_skips_the_entry(setup, capsys):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    derived = add_derived(manifest, out)
    manifest["photos"].pop()
    mrs.write_manifest(manifest, path)
    base = out / "photos" / P1
    base.write_bytes(base.read_bytes()[:50])
    partial = {k: v for k, v in derived.items() if k not in ("sha256", "bytes", "pixel_sha256", "megapixels")}
    assert pin(path, out, [partial]) == 1
    assert "skipped p9" in capsys.readouterr().out
    assert [p["id"] for p in rc.load_manifest(path)["photos"]] == ["p1", "p2", "p3"]


# --- lock with --only -----------------------------------------------------------------------


def two_case_setup(setup):
    path, manifest, out, srv = setup
    manifest["photos"][1]["cases"] = ["landscape", "macro"]
    manifest["cases"]["macro"]["known_gap"] = None
    manifest["cases"]["macro"]["min_photos"] = 1
    mrs.write_manifest(manifest, path)
    return path, manifest, out, srv


def test_only_merges_into_the_existing_lock(setup):
    path, manifest, out, _ = two_case_setup(setup)
    assert run(path, out) == 0
    full = json.loads((out / "manifest.lock.json").read_text())
    assert full["only"] is None and full["covered"] == ["p1", "p2", "p3"]
    assert run(path, out, "--only", "macro", "--resume") == 0
    lock = json.loads((out / "manifest.lock.json").read_text())
    assert lock["only"] == "macro" and lock["covered"] == ["p1", "p2", "p3"]
    assert lock["photos"] == full["photos"]


def test_only_on_a_fresh_out_claims_only_what_it_verified(setup):
    path, _, out, _ = two_case_setup(setup)
    assert run(path, out, "--only", "macro") == 0
    lock = json.loads((out / "manifest.lock.json").read_text())
    assert lock["only"] == "macro" and lock["covered"] == ["p2"] and list(lock["photos"]) == ["p2"]


def test_only_does_not_merge_a_lock_of_another_manifest(setup):
    path, manifest, out, _ = two_case_setup(setup)
    assert run(path, out) == 0
    manifest["photos"][0]["bytes"] += 1  # a FILE_FIELD: the digest changes, the old lock is stale
    manifest["photos"][0]["sha256"] = manifest["photos"][0]["sha256"][::-1]
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--only", "macro", "--resume") == 0
    lock = json.loads((out / "manifest.lock.json").read_text())
    assert lock["covered"] == ["p2"]


# --- revision pins --------------------------------------------------------------------------


def test_pin_checks_commons_sha1_revision(setup, server, capsys):
    path, _, out, _ = setup
    new, body = bare(4, server)
    new["licence_evidence"] = {**new["licence_evidence"], "sha1": "0" * 40}
    assert pin(path, out, [new]) == 1
    assert "revision_changed" in capsys.readouterr().out
    assert "p4" not in [p["id"] for p in rc.load_manifest(path)["photos"]]
    dest = out / "photos" / new["path"]
    assert not dest.exists() and dest.with_name(dest.name + ".bad").read_bytes() == body
    new["licence_evidence"]["sha1"] = hashlib.sha1(body).hexdigest()
    assert pin(path, out, [new]) == 0


def test_pin_verifies_an_approved_sha256(setup, server, capsys):
    path, _, out, _ = setup
    new, body = bare(4, server)
    new["sha256"] = "f" * 64
    assert pin(path, out, [new]) == 1
    assert "sha256 expected" in capsys.readouterr().out
    assert "p4" not in [p["id"] for p in rc.load_manifest(path)["photos"]]
    new["sha256"] = hashlib.sha256(body).hexdigest()
    assert pin(path, out, [new]) == 0
    assert rc.load_manifest(path)["photos"][-1]["sha256"] == new["sha256"]


def test_pin_download_quarantines_the_file_it_replaces(setup, server):
    path, _, out, _ = setup
    new, body = bare(4, server)
    dest = out / "photos" / new["path"]
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale")
    assert pin(path, out, [new]) == 0
    assert dest.read_bytes() == body
    assert dest.with_name(dest.name + ".bad").read_bytes() == b"stale"


# --- Retry-After ----------------------------------------------------------------------------


def fetch_with_retry_after(server, tmp_path, header, now=1_000_000_000.0):
    server.add("r.jpg", b"payload")
    server.flaky["/r.jpg"] = 1
    server.retry_after = header
    sleeps = []
    fetcher = mrs.Fetcher(delay=0, backoff=0, sleep=sleeps.append, clock=lambda: now)
    fetcher.download(server.base + "/r.jpg", tmp_path / "r.part")
    return sleeps


def test_retry_after_seconds_is_slept(server, tmp_path):
    assert fetch_with_retry_after(server, tmp_path, "7") == [7.0]


def test_retry_after_http_date_is_slept(server, tmp_path):
    header = email.utils.formatdate(1_000_000_030, usegmt=True)
    assert fetch_with_retry_after(server, tmp_path, header) == [30.0]
    assert fetch_with_retry_after(server, tmp_path, email.utils.formatdate(999_999_000, usegmt=True)) == []


def test_retry_after_is_capped_and_garbage_ignored(server, tmp_path):
    assert fetch_with_retry_after(server, tmp_path, "100000") == [mrs.MAX_RETRY_AFTER]
    assert fetch_with_retry_after(server, tmp_path, "soon") == []  # backoff 0 -> no sleep


# --- candidates -> licence_check -> pin -> validate ----------------------------------------


def test_candidates_to_licence_check_to_pin_validates(server, tmp_path):
    bodies = {n: jpeg_bytes(300 + ord(n)) for n in "ABC"}

    class FakeCommons:
        def __call__(self, url):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            pages = {}
            for index, title in enumerate(query["titles"][0].split("|"), 1):
                name = title[len("File:"):-len(".jpg")]
                body = bodies[name]
                values = {"LicenseShortName": "CC0", "Artist": "Jane Doe", "UsageTerms": "CC0"}
                pages[str(index)] = {
                    "title": title,
                    "imageinfo": [{
                        "url": server.add(f"{name}.jpg", body), "sha1": hashlib.sha1(body).hexdigest(),
                        "extmetadata": {k: {"value": v} for k, v in values.items()},
                    }],
                    "categories": [],
                }
            return json.dumps({"query": {"pages": pages}})

    lines = [
        json.dumps({
            "case": CASE, "source": "commons", "title": f"File:{n}.jpg", "page_url": "p",
            "covers_also": [], "identifiable_people": False, "child": False, "ai_generated": False,
            "derive": None, "notes": "",
        })
        for n in bodies
    ]
    candidates_file = tmp_path / "candidates.jsonl"
    candidates_file.write_text("\n".join(lines) + "\n", encoding="utf8")
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["photos"] = []
    path, out = tmp_path / "manifest.json", tmp_path / "out"
    mrs.write_manifest(manifest, path)
    approved, rejected, _ = lc.run(
        lc.read_jsonl([candidates_file]), manifest, lc.CachedFetch(FakeCommons()), date="2026-11-25",
    )
    assert len(approved) == 3 and not rejected
    assert pin(path, out, approved) == 0
    pinned = rc.load_manifest(path)
    assert [p["id"] for p in pinned["photos"]] == [e["id"] for e in approved]
    errors = rc.validate(pinned)
    assert [e for e in errors if e.startswith("photo ")] == [], errors
    assert errors == []
    for photo in pinned["photos"]:
        assert (out / "photos" / photo["path"]).read_bytes() in bodies.values()


# --- recipe ops added for the reference set candidates -----------------------------------------


@pytest.fixture
def rich_base(tmp_path):
    """A JPEG carrying an ICC profile and an EXIF block (orientation + capture time)."""
    from PIL import ImageCms

    rng = random.Random(7)
    img = Image.frombytes("RGB", (64, 48), bytes(rng.randrange(256) for _ in range(64 * 48 * 3)))
    exif = Image.Exif()
    exif[0x0112] = 1
    exif[0x0132] = "2020:01:01 10:00:00"
    path = tmp_path / "rich.jpg"
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    img.save(path, "JPEG", quality=90, exif=exif.tobytes(), icc_profile=icc)
    return path


def render_twice(base, recipe, tmp_path, ext):
    first, second = tmp_path / f"one{ext}", tmp_path / f"two{ext}"
    mrs.render_derived(base, recipe, first)
    mrs.render_derived(base, recipe, second)
    return first, second


@pytest.mark.parametrize(("recipe", "ext"), [
    ("strip_icc", ".jpg"), ("crop_aspect:1x1", ".jpg"), ("crop_aspect:21x9", ".jpg"),
    ("set_exif_datetime:2021:03:04 05:06:07", ".jpg"), ("to_16bit:png", ".png"), ("to_16bit:tiff", ".tif"),
    ("encode_heic:60", ".heic"), ("resize:32;crop_aspect:1x1;to_16bit:tiff", ".tiff"),
])
def test_new_ops_are_deterministic(tmp_path, rich_base, recipe, ext):
    first, second = render_twice(rich_base, recipe, tmp_path, ext)
    assert mrs.pixel_sha256(first) == mrs.pixel_sha256(second)
    if not recipe.startswith("encode_heic"):  # libheif bytes may differ between versions, pixels may not
        assert first.read_bytes() == second.read_bytes()


def test_strip_icc_drops_profile_keeps_pixels(tmp_path, rich_base):
    out = tmp_path / "o.jpg"
    mrs.render_derived(rich_base, "strip_icc", out)
    with Image.open(rich_base) as before, Image.open(out) as after:
        assert before.info.get("icc_profile") and "icc_profile" not in after.info
        assert after.getexif()[0x0112] == 1  # EXIF is a different concern and is kept
    ref = tmp_path / "ref.jpg"
    mrs.render_derived(rich_base, "strip_exif", ref)  # same single save, profile kept
    assert mrs.pixel_sha256(out) == mrs.pixel_sha256(ref)


@pytest.mark.parametrize(("spec", "expected"), [("1x1", (48, 48)), ("21x9", (64, 27)), ("4x3", (64, 48))])
def test_crop_aspect_centres(tmp_path, rich_base, spec, expected):
    out = tmp_path / "o.png"
    mrs.render_derived(rich_base, f"crop_aspect:{spec}", out)
    with Image.open(out) as img, Image.open(rich_base) as base:
        assert img.size == expected
        left = (64 - expected[0]) // 2
        top = (48 - expected[1]) // 2
        assert img.tobytes() == base.crop((left, top, left + expected[0], top + expected[1])).tobytes()


@pytest.mark.parametrize(("kind", "ext"), [("png", ".png"), ("tiff", ".tif")])
def test_to_16bit_writes_16_bits_and_hashes_raw_samples(tmp_path, rich_base, kind, ext):
    import numpy as np

    out = tmp_path / f"o{ext}"
    mrs.render_derived(rich_base, f"to_16bit:{kind}", out)
    array = mrs._read_16bit(out)
    assert array is not None and array.dtype == np.uint16 and array.shape == (48, 64, 3)
    with Image.open(rich_base) as base:
        assert (array == np.asarray(base.convert("RGB")).astype(np.uint16) * 257).all()
    want = hashlib.sha256(b"RGB16:64x48:" + array.astype("<u2").tobytes()).hexdigest()
    assert mrs.pixel_sha256(out) == want
    plain = tmp_path / "plain.png"  # an 8-bit file keeps the old definition
    mrs.render_derived(rich_base, "strip_exif", plain)
    assert mrs._read_16bit(plain) is None


def test_to_16bit_rules(tmp_path, rich_base):
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe("to_16bit:png;resize:10")
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe("to_16bit:gif")
    with pytest.raises(mrs.RecipeError):
        mrs.render_derived(rich_base, "to_16bit:png", tmp_path / "o.tif")


def test_encode_heic_pixel_hash_stable_across_encodes(tmp_path, rich_base):
    first, second = render_twice(rich_base, "encode_heic:50", tmp_path, ".heic")
    assert first.read_bytes()[4:8] == b"ftyp"
    assert mrs.pixel_sha256(first) == mrs.pixel_sha256(second)
    with pytest.raises(mrs.RecipeError):
        mrs.render_derived(rich_base, "encode_heic:50", tmp_path / "o.jpg")
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe("encode_heic:0")


def test_set_exif_datetime_distinguishes_variants(tmp_path, rich_base):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    mrs.render_derived(rich_base, "set_exif_orientation:6;set_exif_datetime:2021:03:04 05:06:07", a)
    mrs.render_derived(rich_base, "set_exif_orientation:8;set_exif_datetime:2021:03:04 05:07:07", b)
    with Image.open(a) as ia, Image.open(b) as ib:
        ea, eb = ia.getexif(), ib.getexif()
        assert ea.get_ifd(0x8769)[0x9003] == "2021:03:04 05:06:07" and ea[0x0132] == "2021:03:04 05:06:07"
        assert eb.get_ifd(0x8769)[0x9003] == "2021:03:04 05:07:07"
        assert ea[0x0112] == 6 and eb[0x0112] == 8
    assert mrs.pixel_sha256(a) == mrs.pixel_sha256(b)  # pixels are shared, the clock tells them apart
    c = tmp_path / "c.jpg"
    mrs.render_derived(rich_base, "strip_exif;set_exif_datetime:2022:01:02 03:04:05", c)
    with Image.open(c) as ic:
        assert ic.getexif().get_ifd(0x8769)[0x9003] == "2022:01:02 03:04:05"


@pytest.mark.parametrize("recipe", ["set_exif_datetime:2021-03-04", "set_exif_datetime:2021:13:40 25:61:61"])
def test_set_exif_datetime_rejects_bad_dates(recipe):
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe(recipe)


def test_write_xmp_sidecar_is_deterministic_and_complete(tmp_path):
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe("write_xmp_sidecar:rating=4,keywords=sea & sky")  # '&' is outside the alphabet
    recipe = "write_xmp_sidecar:rating=4,label=Red,keywords=sunset|sea sky"
    first, second = tmp_path / "p1.xmp", tmp_path / "p2.xmp"
    mrs.render_derived(tmp_path / "unused.jpg", recipe, first)
    mrs.render_derived(tmp_path / "unused.jpg", recipe, second)
    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf8")
    assert 'xmp:Rating="4"' in text and 'xmp:Label="Red"' in text
    assert "<rdf:li>sunset</rdf:li><rdf:li>sea sky</rdf:li>" in text
    assert "Date" not in text and "202" not in text  # no timestamps
    assert b"\r" not in first.read_bytes()


@pytest.mark.parametrize("recipe", [
    "write_xmp_sidecar:rating=9", "write_xmp_sidecar:colour=red", "write_xmp_sidecar:rating=1,rating=2",
    "write_xmp_sidecar:keywords=a||b", "write_xmp_sidecar:rating=1;resize:10", "write_xmp_sidecar",
    "raw_embedded_jpeg:1", "raw_embedded_jpeg;strip_exif",
])
def test_xmp_and_raw_recipe_rules(recipe):
    with pytest.raises(mrs.RecipeError):
        mrs.parse_recipe(recipe)


def test_xmp_entry_builds_verifies_and_pins(setup):
    path, manifest, out, _ = setup
    assert run(path, out) == 0
    recipe = "write_xmp_sidecar:rating=3,keywords=a|b"
    sidecar = out.parent / "scratch.xmp"
    mrs.render_derived(out / "photos" / P1, recipe, sidecar)
    xmp = entry(
        8, None, b"x", kind="derived", path="categories/landscape/p1.xmp", derived_from="p1", recipe=recipe,
        companion_of="p1", pixel_sha256=None, format="xmp", cases=[], expected_category=None,
        acceptable_categories=[], labeller=None, reviewed=False, scored=False, megapixels=None,
        sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest(), bytes=sidecar.stat().st_size,
    )
    manifest["photos"].append(xmp)
    mrs.write_manifest(manifest, path)
    assert run(path, out, "--resume") == 0  # builds the sidecar next to its photo
    dest = out / "photos" / xmp["path"]
    assert dest.read_bytes() == sidecar.read_bytes()
    assert mrs.verify_on_disk(xmp, dest) == ("ok", "")
    dest.write_text("tampered", encoding="utf8")
    assert mrs.verify_on_disk(xmp, dest)[0] == "mismatch"
    partial = {k: v for k, v in xmp.items() if k not in ("sha256", "bytes", "megapixels")}
    partial["id"] = "p8b"
    manifest["photos"].remove(xmp)
    mrs.write_manifest(manifest, path)
    assert pin(path, out, [partial]) == 0
    pinned = {p["id"]: p for p in rc.load_manifest(path)["photos"]}["p8b"]
    assert pinned["pixel_sha256"] is None and pinned["sha256"] == xmp["sha256"]


def _find_raw():
    root = Path("D:/facet-scratch/tmp/refute-393/img")
    return next(iter(sorted(root.glob("*.cr3"))), None) if root.is_dir() else None


def test_raw_embedded_jpeg_roundtrip(tmp_path):
    raw = _find_raw()
    if raw is None:
        pytest.skip("no RAW sample available")
    base = tmp_path / raw.name
    base.write_bytes(raw.read_bytes())
    first, second = render_twice(base, "raw_embedded_jpeg", tmp_path, ".jpg")
    assert first.read_bytes() == second.read_bytes() and first.read_bytes()[:3] == b"\xff\xd8\xff"
    assert mrs.pixel_sha256(first) == mrs.pixel_sha256(second)


def test_raw_embedded_jpeg_bitmap_thumb_is_an_error(tmp_path, monkeypatch):
    import rawpy

    class Thumb:
        format = rawpy.ThumbFormat.BITMAP
        data = b""

    class Raw:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_thumb(self):
            return Thumb()

    monkeypatch.setattr(rawpy, "imread", lambda path: Raw())
    with pytest.raises(mrs.DeriveError, match="BITMAP"):
        mrs.render_derived(tmp_path / "x.cr3", "raw_embedded_jpeg", tmp_path / "o.jpg")
    status, detail = mrs.derive_one(
        {"recipe": "raw_embedded_jpeg", "kind": "derived", "pixel_sha256": "0" * 64},
        tmp_path / "x.cr3", tmp_path / "o.jpg",
    )
    assert status == "mismatch" and "BITMAP" in detail


def gap_manifest(server, tmp_path, with_base=True):
    """landscape: 1 photo (min 3), the base of derived d1; macro: p2 and d1 (min 1)."""
    manifest = copy.deepcopy(rc.load_manifest())
    manifest["photos"] = []
    body = jpeg_bytes(1)
    base = entry(1, server.add("p1.jpg", body), body)
    base["cases"] = [CASE]
    manifest["cases"][CASE]["known_gap"] = None
    other = entry(2, server.add("p2.jpg", body), body)
    other["cases"] = ["macro"]
    other["expected_category"] = "macro"
    other["acceptable_categories"] = ["macro"]
    manifest["cases"]["macro"]["known_gap"] = None
    for case in ("landscape", "macro"):
        manifest["cases"][case]["min_photos"] = 3 if case == "landscape" else 1
    derived = {**base, "id": "d1", "path": "derived/d1.jpg", "url": None, "kind": "derived",
               "derived_from": "p1", "recipe": "strip_exif", "pixel_sha256": "e" * 64,
               "cases": ["macro"], "expected_category": "macro", "acceptable_categories": ["macro"]}
    manifest["photos"] = [base, other, derived]
    path = tmp_path / "manifest.json"
    mrs.write_manifest(manifest, path)
    return path


def test_finalize_gaps_keeps_derivation_bases_and_drops_orphans(server, tmp_path, capsys):
    path = gap_manifest(server, tmp_path)
    before = path.read_bytes()
    code = mrs.main(["--manifest", str(path), "--out", str(tmp_path / "out"), "--finalize-gaps",
                     "--date", "2026-11-25", *FAST])
    assert code == 0
    after = json.loads(path.read_text(encoding="utf8"))
    assert after["cases"][CASE]["known_gap"] == "only 1 candidate(s) passed the licence gate on 2026-11-25"
    assert after["cases"]["macro"]["known_gap"] is None
    ids = [p["id"] for p in after["photos"]]
    assert ids == ["p1", "p2", "d1"]  # p1 lost its only case but is d1's base
    assert after["photos"][0]["cases"] == []
    assert path.read_bytes() != before
    assert "| landscape | 1 |" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_finalize_gaps_drops_orphan_and_its_pairs(server, tmp_path):
    path = gap_manifest(server, tmp_path)
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["photos"] = [p for p in manifest["photos"] if p["id"] != "d1"]
    manifest["pairs"] = [{"better": "p1", "worse": "p2", "defect": "blur", "category": "landscape"}]
    mrs.write_manifest(manifest, path)
    assert mrs.main(["--manifest", str(path), "--out", str(tmp_path / "out"), "--finalize-gaps",
                     "--date", "2026-11-25", *FAST]) == 0
    after = json.loads(path.read_text(encoding="utf8"))
    assert [p["id"] for p in after["photos"]] == ["p2"]
    assert after["pairs"] == []


def test_finalize_gaps_needs_a_date(server, tmp_path, capsys):
    path = gap_manifest(server, tmp_path)
    assert mrs.main(["--manifest", str(path), "--out", str(tmp_path / "out"), "--finalize-gaps", *FAST]) == 2
