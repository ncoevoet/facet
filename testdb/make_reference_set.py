"""Build, verify or extend the reference photo set from its manifest (GitHub issue #393).

Build / verify mode (the default) downloads every ``kind: download`` photo of
``reference_set.json`` into ``<out>/photos/<path>``, checks ``bytes`` and ``sha256`` byte for
byte, recomputes every ``kind: derived`` photo from its base and checks ``pixel_sha256``, then
writes ``<out>/manifest.lock.json``:

    python testdb/make_reference_set.py --out D:/ref-set [--only GROUP_OR_CASE] [--resume]
    python testdb/make_reference_set.py --out D:/ref-set --verify-only

Pin mode completes entries produced by ``licence_check.py`` (url, licence and provenance, no
hashes yet): it downloads each, computes ``sha256`` / ``bytes`` / ``megapixels`` (and
``pixel_sha256`` for derived entries), merges them into the manifest and rewrites it:

    python testdb/make_reference_set.py --pin APPROVED.json --out D:/ref-set

Rules that never bend: nothing is ever deleted (a file that fails its hash is renamed to
``<name>.bad``, or ``.bad2``, ...); a non-empty ``--out`` is refused without ``--resume``, and in
every mode (pin, resume, verify-only) a non-empty ``--out`` must already hold a
``manifest.lock.json`` or ``photos/`` tree written by this script. ``--out`` may never be a
network path (backslash-backslash host, //host, or the extended UNC prefix: the NAS is read-only),
and unless ``--allow-anywhere`` (tests only) may not sit on drive C: (any letter case), inside the
running checkout, inside any registered git worktree (``git worktree list``) or inside
``D:/photo-llm``.

``--only`` merges into an existing ``manifest.lock.json`` (when it was written for the same
manifest digest) and records ``only`` and ``covered`` (every photo id the lock vouches for), so a
lock never claims more than was verified.

Pin mode extras: the first photo added to a case whose ``known_gap`` is exactly the shipped
placeholder (``PLACEHOLDER_GAP``) clears that gap; a case with any other gap reason is an error
and the entry is skipped. An entry carrying ``licence_evidence.sha1`` (Commons) is checked against
the downloaded bytes and a difference is reported as ``revision_changed``; an entry carrying
``sha256`` (raw.pixls.us) must match the download, else it is skipped and the file kept as ``.bad``.
``megapixels`` come from Pillow (HEIC/HIF through ``pillow_heif``, JPEG XL through
``utils/jpegxl.py`` or ``imagecodecs``) and, for RAW, from ``rawpy`` ``raw.sizes`` (the full sensor
size, not the cropped preview). A truncated or undecodable derived file counts as ``mismatch``.
``Retry-After`` is honoured in both its seconds and HTTP-date forms (capped at 60 s).

Exit codes: 0 all verified; 1 mismatch / missing / failed files (listed at the end, each as
``mismatch`` / ``missing`` / ``failed``); 2 bad manifest, bad arguments or a refused ``--out``.
In pin mode the manifest is written even while it fails validation (a case may still be under
its photo minimum mid-way): exit 0 when the only errors left are per-case photo counts, else 1;
a skipped entry (download failure, id clash) is reported and also gives exit 1.

pixel_sha256 (derived files; originals are always byte-exact)
    sha256 over ``"<mode>:<width>x<height>:"`` followed by the raw bytes of the decoded image
    converted to RGB (RGBA when it has alpha), ignoring EXIF orientation. See ``pixel_sha256``.

Recipe grammar: ``op[:arg];op[:arg];...`` applied left to right to the decoded base, the closed set
    resize:N                    longest side to N pixels (Lanczos, aspect kept)
    crop:L,T,R,B                pixel box
    reencode_jpeg:Q             JPEG round trip at quality Q (1-100), also the quality of a JPEG save
    strip_exif                  drop the EXIF block (otherwise the base's is carried over)
    set_exif_orientation:N      write EXIF orientation N (1-8); pixels are not rotated
    convert_icc:srgb            convert from the base's embedded profile (else assume sRGB) to sRGB
    to_cmyk | to_grayscale | to_sepia
An unknown op or a malformed argument is an error. The output format follows the file extension
(.jpg/.jpeg, .png, .tif/.tiff).
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from reference_common import MANIFEST_PATH, file_level_digest, load_manifest, validate

REPO_DIR = Path(__file__).resolve().parent.parent
USER_AGENT = "FacetReferenceSet/1.0 (https://github.com/ncoevoet/facet)"
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 4
MAX_RETRY_AFTER = 60.0
CHUNK = 1 << 20
RAW_FORMATS = ("cr2", "cr3", "nef", "arw", "raf", "rw2", "orf", "pef", "dng")
IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF"}
DEFAULT_QUALITY = 95
# The validator's exact message (reference_common._check_cases) for a case below its photo minimum.
COUNT_ERROR = re.compile(r"case \S+: \d+ photos, need \d+-\d+ or a known_gap")
# The ``known_gap`` every shipped case carries until a photo is sourced for it.
PLACEHOLDER_GAP = "not yet sourced"
# The main checkout's tree (photos live there); never a build target.
PROTECTED_TREES = ("D:/photo-llm",)
LOCK_NAME = "manifest.lock.json"
# Canonical key order of a manifest photo entry; unknown keys follow in their given order.
ENTRY_ORDER = (
    "id", "path", "url", "sha256", "bytes", "kind", "derived_from", "recipe", "pixel_sha256",
    "licence", "author", "source_page", "attribution", "approved_by", "approved_on",
    "licence_evidence", "share_alike_ok", "change_notice", "cases", "expected_category",
    "acceptable_categories", "labeller", "reviewed", "sequence", "companion_of", "scored",
    "megapixels", "format", "notes",
)


class RecipeError(ValueError):
    """An unknown recipe op or a malformed argument."""


class FetchError(Exception):
    """A download that gave up; ``status`` is the HTTP code or None for a network failure."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# --- recipes -----------------------------------------------------------------------------

_OPS = {
    "resize": re.compile(r"\d+"),
    "crop": re.compile(r"\d+,\d+,\d+,\d+"),
    "reencode_jpeg": re.compile(r"\d{1,3}"),
    "strip_exif": None,
    "set_exif_orientation": re.compile(r"[1-8]"),
    "convert_icc": re.compile(r"srgb"),
    "to_cmyk": None,
    "to_grayscale": None,
    "to_sepia": None,
}


def parse_recipe(recipe):
    """``[(op, arg)]`` for a recipe string; raises ``RecipeError`` on anything outside the grammar."""
    steps = []
    for part in str(recipe or "").split(";"):
        op, _, arg = part.strip().partition(":")
        if op not in _OPS:
            raise RecipeError(f"unknown recipe op {op!r} in {recipe!r}")
        pattern = _OPS[op]
        if pattern is None and arg or pattern is not None and not pattern.fullmatch(arg):
            raise RecipeError(f"bad argument {arg!r} for recipe op {op!r}")
        if op == "reencode_jpeg" and not 1 <= int(arg) <= 100:
            raise RecipeError("reencode_jpeg quality must be 1-100")
        steps.append((op, arg))
    return steps


class _State:
    """What a recipe carries between steps: pixels, EXIF, ICC profile and JPEG quality."""

    def __init__(self, img):
        self.img = img
        self.exif = img.getexif() if img.getexif() else None
        self.icc = img.info.get("icc_profile")
        self.quality = DEFAULT_QUALITY


def _apply_step(state, op, arg):
    from PIL import Image, ImageCms, ImageOps

    img = state.img
    if op == "resize":
        scale = int(arg) / max(img.size)
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        state.img = img.resize(size, Image.LANCZOS)
    elif op == "crop":
        state.img = img.crop(tuple(int(v) for v in arg.split(",")))
    elif op == "reencode_jpeg":
        state.quality = int(arg)
        buffer = io.BytesIO()
        img.convert("RGB" if img.mode not in ("L", "CMYK") else img.mode).save(buffer, "JPEG", quality=state.quality)
        state.img = Image.open(io.BytesIO(buffer.getvalue()))
        state.img.load()
    elif op == "strip_exif":
        state.exif = None
    elif op == "set_exif_orientation":
        if state.exif is None:
            state.exif = Image.Exif()
        state.exif[0x0112] = int(arg)
    elif op == "convert_icc":
        target = ImageCms.createProfile("sRGB")
        source = ImageCms.ImageCmsProfile(io.BytesIO(state.icc)) if state.icc else target
        state.img = ImageCms.profileToProfile(img.convert("RGB"), source, target, outputMode="RGB")
        state.icc = ImageCms.ImageCmsProfile(target).tobytes()
    elif op == "to_cmyk":
        state.img = img.convert("CMYK")
    elif op == "to_grayscale":
        state.img = img.convert("L")
    elif op == "to_sepia":
        state.img = ImageOps.colorize(img.convert("L"), "#2e1a0a", "#ffe9c4")


def render_derived(base_path, recipe, dest_path):
    """Apply ``recipe`` to the decoded ``base_path`` and save the result as ``dest_path``."""
    from PIL import Image

    steps = parse_recipe(recipe)
    with Image.open(base_path) as opened:
        opened.load()
        state = _State(opened)
    for op, arg in steps:
        _apply_step(state, op, arg)
    fmt = IMAGE_FORMATS.get(Path(dest_path).suffix.lower())
    if fmt is None:
        raise RecipeError(f"cannot write a derived file with extension {Path(dest_path).suffix!r}")
    options = {}
    if state.exif is not None:
        options["exif"] = state.exif.tobytes()
    if state.icc:
        options["icc_profile"] = state.icc
    if fmt == "JPEG":
        options["quality"] = state.quality
    with open(dest_path, "wb") as handle:
        state.img.save(handle, fmt, **options)


def pixel_sha256(path):
    """sha256 of ``"<mode>:<w>x<h>:"`` + the decoded pixel bytes, RGB (RGBA with alpha), no EXIF rotation."""
    from PIL import Image

    with Image.open(path) as img:
        img.load()
        alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        rgb = img.convert("RGBA" if alpha else "RGB")
    digest = hashlib.sha256(f"{rgb.mode}:{rgb.width}x{rgb.height}:".encode())
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def _register_openers():
    """Teach Pillow HEIC/HIF (pillow_heif) and JPEG XL (utils/jpegxl.py) when importable."""
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        if str(REPO_DIR) not in sys.path:
            sys.path.append(str(REPO_DIR))
        from utils.jpegxl import register_bounded_jpegxl_opener

        register_bounded_jpegxl_opener()
    except Exception:  # noqa: BLE001 - imagecodecs fallback in _jxl_size
        pass


def _jxl_size(path):
    from PIL import Image

    try:
        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - no Pillow opener: decode with imagecodecs
        import imagecodecs

        array = imagecodecs.jpegxl_decode(Path(path).read_bytes())
        return array.shape[1], array.shape[0]


def megapixels_of(path, fmt):
    """``(megapixels or None, note)``: rawpy for RAW (full sensor size), JXL helpers, Pillow for the rest."""
    try:
        if fmt in RAW_FORMATS:
            import rawpy

            with rawpy.imread(str(path)) as raw:
                width, height = raw.sizes.width, raw.sizes.height
        else:
            from PIL import Image

            _register_openers()
            if fmt == "jxl":
                width, height = _jxl_size(path)
            else:
                with Image.open(path) as img:
                    width, height = img.size
        return round(width * height / 1e6, 3), ""
    except Exception as exc:  # noqa: BLE001 - any decoder failure just means "unknown"
        return None, f"megapixels unknown: {type(exc).__name__} reading {fmt}"


# --- files and network -------------------------------------------------------------------


def file_sha1(path):
    """sha1 of a file on disk (Commons publishes sha1 revisions)."""
    digest = hashlib.sha1()  # noqa: S324 - compared with the source's own identifier, not a security hash
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_retry_after(value, now):
    """Seconds to wait for a ``Retry-After`` header (delta-seconds or HTTP-date), capped; ``None`` if unusable."""
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER)
    try:
        when = parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    return min(max(0.0, when - now), MAX_RETRY_AFTER)


def file_sha256(path):
    """``(sha256, size)`` of a file on disk."""
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def photo_dest(out, photo):
    """``<out>/photos/<path>`` for a manifest photo (manifest paths are POSIX relative)."""
    return Path(out, "photos", *PurePosixPath(photo["path"]).parts)


def quarantine(path):
    """Rename ``path`` to the first free ``.bad`` / ``.bad2`` ...; nothing is ever deleted."""
    target = path.with_name(path.name + ".bad")
    number = 2
    while target.exists():
        target = path.with_name(f"{path.name}.bad{number}")
        number += 1
    path.replace(target)
    return target


class Fetcher:
    """Sequential, polite downloader: User-Agent, delay between requests, retry on 429/5xx."""

    def __init__(self, delay=1.0, backoff=1.0, timeout=60.0, sleep=time.sleep, clock=time.time):
        self.delay, self.backoff, self.timeout = delay, backoff, timeout
        self.sleep, self.clock = sleep, clock
        self.requests = 0

    def download(self, url, part_path):
        """Stream ``url`` into ``part_path``; return ``(sha256, size)``. Raises ``FetchError``."""
        last = None
        for attempt in range(MAX_ATTEMPTS):
            if self.requests and self.delay:
                self.sleep(self.delay)
            self.requests += 1
            wait = self.backoff * 2 ** attempt
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    digest, size = hashlib.sha256(), 0
                    with open(part_path, "wb") as handle:
                        for chunk in iter(lambda: response.read(CHUNK), b""):
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                return digest.hexdigest(), size
            except urllib.error.HTTPError as exc:
                last = FetchError(exc.code, f"HTTP {exc.code}")
                if exc.code not in RETRY_STATUS:
                    raise last from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                parsed = parse_retry_after(retry_after, self.clock())
                if parsed is not None:
                    wait = parsed
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last = FetchError(None, f"{type(exc).__name__}: {exc}")
            if attempt + 1 < MAX_ATTEMPTS and wait:
                self.sleep(wait)
        raise last


# --- checks ------------------------------------------------------------------------------


def verify_on_disk(photo, dest):
    """``(status, detail)``: ``ok``, ``missing`` or ``mismatch`` for the file at ``dest``."""
    if not dest.exists():
        return "missing", "not on disk"
    if photo["kind"] == "derived":
        try:
            got = pixel_sha256(dest)
        except Exception as exc:  # noqa: BLE001 - truncated / undecodable file is a mismatch, not a crash
            return "mismatch", f"undecodable derived file: {type(exc).__name__}: {exc}"
        want = photo["pixel_sha256"]
        return ("ok", "") if got == want else ("mismatch", f"pixel_sha256 expected {want} got {got}")
    got, size = file_sha256(dest)
    if got != photo["sha256"]:
        return "mismatch", f"sha256 expected {photo['sha256']} got {got}"
    if size != photo["bytes"]:
        return "mismatch", f"bytes expected {photo['bytes']} got {size}"
    return "ok", ""


def fetch_one(photo, dest, fetcher):
    """Download a ``download`` photo and verify it; a bad file is quarantined as ``.bad``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        got, size = fetcher.download(photo["url"], part)
    except FetchError as exc:
        return ("missing" if exc.status in (404, 410) else "failed"), f"{photo['url']}: {exc}"
    if got != photo["sha256"] or size != photo["bytes"]:
        part.replace(dest)
        bad = quarantine(dest)
        return "mismatch", f"sha256 expected {photo['sha256']} got {got}, bytes expected {photo['bytes']} got {size} (kept as {bad.name})"
    part.replace(dest)
    return "ok", ""


def derive_one(photo, base_dest, dest):
    """Recompute a derived photo from its base and verify its ``pixel_sha256``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part" + dest.suffix)
    try:
        render_derived(base_dest, photo["recipe"], part)
    except RecipeError:
        raise
    except Exception as exc:  # noqa: BLE001 - an undecodable base cannot be derived from
        return "mismatch", f"cannot derive from {base_dest.name}: {type(exc).__name__}: {exc}"
    part.replace(dest)
    status, detail = verify_on_disk(photo, dest)
    if status == "mismatch":
        detail += f" (kept as {quarantine(dest).name})"
    return status, detail


def select(manifest, only):
    """Photos matching ``only`` (a case id or group name; ``None`` = all) plus the bases they need."""
    photos = manifest["photos"]
    if only is not None:
        cases = manifest["cases"]
        wanted = {c for c, case in cases.items() if c == only or case.get("group") == only}
        if not wanted:
            raise ValueError(f"--only {only!r} is neither a case nor a group")
        photos = [p for p in photos if wanted & set(p.get("cases", ()))]
        by_id = {p["id"]: p for p in manifest["photos"]}
        for photo in list(photos):
            base = by_id.get(photo.get("derived_from"))
            if base is not None and base not in photos:
                photos.append(base)
    return sorted(photos, key=lambda p: p["kind"] == "derived")


def is_network_path(raw):
    """True for UNC paths in any slash mix: ``\\\\host\\x``, ``//host/x``, ``\\\\?\\UNC\\host\\x``."""
    text = str(raw).replace("/", "\\")
    return text.startswith("\\\\") or PureWindowsPath(text).drive.startswith("\\\\")


def _inside(path, base):
    left, right = (os.path.normcase(os.path.normpath(str(p))) for p in (path, base))
    return left == right or left.startswith(right.rstrip("\\/") + os.sep)


def on_drive_c(text):
    """True for a path on drive C: in any letter case (c:/x or C:/x)."""
    return PureWindowsPath(str(text)).drive.upper() == "C:"


def worktree_roots():
    """The running checkout plus every registered git worktree (read-only ``git worktree list``)."""
    roots = [REPO_DIR]
    try:
        listing = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=REPO_DIR, capture_output=True,
            text=True, timeout=30, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return roots
    for line in listing.splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line[len("worktree "):].strip()))
    return roots


def check_out(out, allow_anywhere):
    """Refuse a network ``--out`` always; unless ``allow_anywhere`` also drive C:, the repo and its worktrees."""
    if is_network_path(out):
        raise ValueError(f"--out {out} is a network path (never written to)")
    resolved = Path(out).resolve()
    if is_network_path(resolved):
        raise ValueError(f"--out {resolved} resolves to a network path (never written to)")
    if not allow_anywhere:
        for candidate in (str(out), str(resolved)):
            if on_drive_c(candidate):
                raise ValueError(f"--out {resolved} is on drive C: (use D:)")
        for root in worktree_roots():
            if _inside(resolved, root):
                raise ValueError(f"--out {resolved} is inside the checkout or worktree {root}")
        for tree in PROTECTED_TREES:
            if _inside(resolved, tree):
                raise ValueError(f"--out {resolved} is inside {tree}")
    return resolved


def check_out_contents(out):
    """A non-empty ``out`` must hold what this script wrote (``manifest.lock.json`` or ``photos/``)."""
    if not out.exists():
        return
    if not out.is_dir():
        raise ValueError(f"--out {out} is not a directory")
    if any(out.iterdir()) and not ((out / LOCK_NAME).is_file() or (out / "photos").is_dir()):
        raise ValueError(f"--out {out} is not empty and holds no {LOCK_NAME} or photos/ tree from this script")


def write_manifest(manifest, path):
    """The shipped formatting: 2-space indent, UTF-8, LF, trailing newline."""
    with open(path, "w", encoding="utf8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


# --- build / verify mode -----------------------------------------------------------------


def _previous_lock(out, digest):
    """Photos of an existing lock written for the same manifest digest (``--only`` merges into it)."""
    try:
        previous = json.loads((out / LOCK_NAME).read_text(encoding="utf8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(previous, dict) or previous.get("file_level_digest") != digest:
        return {}
    photos = previous.get("photos")
    return photos if isinstance(photos, dict) else {}


def run_build(args, manifest, out):
    results, lock = [], {}
    by_id = {p["id"]: p for p in manifest["photos"]}
    fetcher = Fetcher(args.delay, args.backoff)
    bad_ids = set()
    for photo in select(manifest, args.only):
        dest = photo_dest(out, photo)
        status, detail = verify_on_disk(photo, dest) if (args.verify_only or args.resume) else ("missing", "")
        if status == "mismatch" and not args.verify_only:
            detail += f" (kept as {quarantine(dest).name})"
        if status != "ok" and not args.verify_only:
            if photo["kind"] == "download":
                status, detail = fetch_one(photo, dest, fetcher)
            elif photo["derived_from"] in bad_ids or not photo_dest(out, by_id[photo["derived_from"]]).exists():
                status, detail = "missing", f"base {photo['derived_from']} unavailable"
            else:
                status, detail = derive_one(photo, photo_dest(out, by_id[photo["derived_from"]]), dest)
        if status != "ok":
            bad_ids.add(photo["id"])
            results.append((photo["id"], status, detail))
        else:
            lock[photo["id"]] = {"sha256": photo["sha256"], "pixel_sha256": photo.get("pixel_sha256")}
    if not args.verify_only:
        out.mkdir(parents=True, exist_ok=True)
        digest = file_level_digest(manifest)
        photos_lock = dict(lock)
        if args.only is not None:
            photos_lock = {**_previous_lock(out, digest), **lock}
        payload = {
            "file_level_digest": digest, "only": args.only, "covered": sorted(photos_lock),
            "photos": photos_lock,
        }
        (out / LOCK_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf8")
    print(f"{len(lock)} verified, {len(results)} bad")
    for pid, status, detail in results:
        print(f"{status} {pid}: {detail}")
    return 1 if results else 0


# --- pin mode ----------------------------------------------------------------------------


def _ordered(entry):
    known = {k: entry[k] for k in ENTRY_ORDER if k in entry}
    known.update({k: v for k, v in entry.items() if k not in known})
    return known


def _skip(skipped, entry, reason):
    print(f"skipped {entry.get('id')}: {reason}")
    skipped.append((entry.get("id"), reason))


def pin_download(entry, out, fetcher, existing):
    """Download ``entry`` (reusing a file that already matches the manifest) and hash it."""
    dest = photo_dest(out, entry)
    if dest.exists() and existing and existing.get("sha256") and file_sha256(dest)[0] == existing["sha256"]:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    fetcher.download(entry["url"], part)
    if dest.exists():
        quarantine(dest)
    part.replace(dest)
    return dest


def gap_conflict(entry, cases):
    """Reason string when a case of ``entry`` carries a gap other than the placeholder, else ``None``."""
    for case_id in entry.get("cases") or ():
        gap = (cases.get(case_id) or {}).get("known_gap")
        if gap and gap != PLACEHOLDER_GAP:
            return f"case {case_id} has known_gap {gap!r}; clear it by hand before adding photos"
    return None


def check_revision(entry, dest):
    """Reason string when the downloaded bytes differ from the source's own sha1 / sha256, else ``None``."""
    sha1 = (entry.get("licence_evidence") or {}).get("sha1")
    if sha1 and file_sha1(dest) != str(sha1).lower():
        return f"revision_changed: sha1 expected {sha1} got {file_sha1(dest)}"
    want = entry.get("sha256")
    if want and file_sha256(dest)[0] != str(want).lower():
        return f"sha256 expected {want} got {file_sha256(dest)[0]}"
    return None


def run_pin(args, manifest, out):
    approved = json.loads(Path(args.pin).read_text(encoding="utf8"))
    photos = manifest["photos"]
    by_id = {p["id"]: p for p in photos}
    fetcher = Fetcher(args.delay, args.backoff)
    skipped, pinned = [], 0
    for entry in sorted(approved, key=lambda e: e.get("kind") == "derived"):
        pid = entry.get("id")
        existing = by_id.get(pid)
        try:
            if entry.get("kind") == "derived":
                parse_recipe(entry.get("recipe"))
                same = existing is None or (existing.get("recipe"), existing.get("derived_from")) == (entry["recipe"], entry["derived_from"])
            else:
                same = existing is None or existing.get("url") == entry.get("url")
            if not same:
                _skip(skipped, entry, "id already pinned with a different url/recipe")
                continue
            conflict = gap_conflict(entry, manifest["cases"])
            if conflict:
                _skip(skipped, entry, conflict)
                continue
            done = dict(entry)
            dest = photo_dest(out, entry)
            if entry.get("kind") == "derived":
                base = by_id.get(entry["derived_from"])
                if base is None:
                    _skip(skipped, entry, f"base {entry['derived_from']} is not in the manifest")
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    quarantine(dest)
                render_derived(photo_dest(out, base), entry["recipe"], dest)
                done["pixel_sha256"] = pixel_sha256(dest)
            else:
                dest = pin_download(entry, out, fetcher, existing)
                wrong = check_revision(entry, dest)
                if wrong:
                    _skip(skipped, entry, f"{wrong} (kept as {quarantine(dest).name})")
                    continue
                done.setdefault("pixel_sha256", None)
            done["sha256"], done["bytes"] = file_sha256(dest)
            done.setdefault("derived_from", None)
            done.setdefault("recipe", None)
            for key in ("sequence", "companion_of"):
                done.setdefault(key, None)
            mp, note = megapixels_of(dest, entry["format"])
            done["megapixels"] = mp
            if note:
                done["notes"] = (str(done.get("notes") or "") + " " + note).strip()
            done.setdefault("notes", "")
        except FetchError as exc:
            _skip(skipped, entry, f"download failed: {exc}")
            continue
        except (RecipeError, OSError, KeyError, ValueError) as exc:
            _skip(skipped, entry, f"{type(exc).__name__}: {exc}")
            continue
        done = _ordered(done)
        if existing is None:
            photos.append(done)
        else:
            photos[photos.index(existing)] = done
        by_id[pid] = done
        for case_id in done.get("cases") or ():
            if (manifest["cases"].get(case_id) or {}).get("known_gap") == PLACEHOLDER_GAP:
                manifest["cases"][case_id]["known_gap"] = None
        pinned += 1
    write_manifest(manifest, args.manifest)
    errors = validate(manifest)
    for error in errors:
        print(f"validate: {error}")
    other = [e for e in errors if not COUNT_ERROR.match(e)]
    print(f"pinned {pinned}, skipped {len(skipped)}, {len(errors)} validation errors ({len(other)} not per-case counts)")
    return 1 if other or skipped else 0


# --- entry point -------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="directory to build the set into (on D:)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--only", help="a group name or case id")
    parser.add_argument("--resume", action="store_true", help="reuse an existing --out, skipping verified files")
    parser.add_argument("--verify-only", action="store_true", help="no network: re-hash what is on disk")
    parser.add_argument("--pin", type=Path, help="APPROVED.json from licence_check: fill hashes into the manifest")
    parser.add_argument("--allow-anywhere", action="store_true", help="skip the repo / drive C: refusal (tests)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--backoff", type=float, default=1.0, help="base seconds of the 429/5xx back-off")
    args = parser.parse_args(argv)

    try:
        out = check_out(args.out, args.allow_anywhere)
        check_out_contents(out)
        manifest = load_manifest(args.manifest)
        if args.pin:
            return run_pin(args, manifest, out)
        errors = validate(manifest)
        if errors:
            print("\n".join(f"manifest: {e}" for e in errors), file=sys.stderr)
            return 2
        for photo in manifest["photos"]:
            if photo["kind"] == "derived":
                parse_recipe(photo["recipe"])
        select(manifest, args.only)
        if args.verify_only:
            if not out.is_dir():
                raise ValueError(f"--out {out} does not exist")
        elif out.exists() and any(out.iterdir()) and not args.resume:
            raise ValueError(f"--out {out} is not empty (use --resume)")
    except (ValueError, OSError) as exc:  # RecipeError is a ValueError
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_build(args, manifest, out)


if __name__ == "__main__":
    sys.exit(main())
