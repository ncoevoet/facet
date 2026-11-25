"""Reference photo set regression check: scan, record, check, update, tolerances (issue #393).

Commands (all take ``--set-dir`` = the folder ``make_reference_set.py --out`` built, holding
``photos/``, and a SCRATCH ``--db``; never the library's default DB)::

    scan       --profile P --set-dir DIR --db DB [--config-dir D]
    record     --profile P --set-dir DIR --db DB --out testdb/reference_goldens/P.json
    check      --profile P --set-dir DIR --db DB [--golden G] [--tolerances T] [--report-only] [--json OUT]
    update     --profile P --set-dir DIR --db DB [--golden G] [--yes]
    tolerances --profile P --set-dir DIR --runs A.db B.db [C.db] [--holdout H.db] [--out T]

Exit codes of ``check``: 0 pass, 1 past tolerance, 2 setup error (missing set files, manifest
digest differs from the golden, DB not from the set, refused DB, failed scan pass). Without a
tolerances file the check is report-only and never exits 1 (spec "Tolerances plan").

Golden score columns are derived from ``db.schema.PHOTOS_COLUMNS``: every REAL column, plus
``image_width``/``image_height``/``face_count``, minus ``EXCLUDED_REAL``. BLOB columns are never
read at all. Excluded, and why:

- ``f_stop`` ``focal_length`` ``focal_length_35mm`` ``exposure_compensation`` ``gps_latitude``
  ``gps_longitude``: EXIF inputs copied from the file, not scorer output.
- ``image_aspect``: a fallback ratio, NULL for every row whose dimensions are real.
- ``raw_sharpness_variance`` ``raw_color_entropy`` ``raw_eye_sharpness``: unnormalised
  intermediates; their normalised forms (``tech_sharpness`` etc.) are recorded.
- ``sequence_ev_offset``: recorded in the ``sequence`` block, where it is read against its kind.
- ``learned_score``: the personal ranker's output, a function of the user's comparisons.
- user/review columns (``star_rating`` ``is_favorite`` ``is_rejected`` ``is_kept``, burst and
  similarity review flags) are not REAL scorer output and never read; neither are ``scanned_at``
  and ``date_added``, which differ every run.
Faces come from ``faces`` (bbox, confidence only: embeddings and crops are BLOBs). NULL stays null.
"""

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

TESTDB_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTDB_DIR.parent
for _path in (str(TESTDB_DIR), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import reference_common as rc  # noqa: E402
from db.schema import PHOTOS_COLUMNS  # noqa: E402

GOLDEN_VERSION = 1
GOLDEN_DIR = TESTDB_DIR / "reference_goldens"
CONFIG_DIR = TESTDB_DIR / "reference_configs"
TOLERANCES_PATH = TESTDB_DIR / "reference_tolerances.json"
PROFILES = ("legacy", "8gb", "16gb", "24gb")
PROTECTED_DB_NAME = "photo_scores_pro.db"
OVERALL = "(overall)"
MIN_PAIRS = 10
TOP_N = 10
UPDATE_MOVED_LIMIT = 0.20
FLOAT_DIGITS = 4
SCORE_FLOOR = 0.02
SRCC_MARGIN = 0.005
JACCARD_MARGIN = 0.05
IOU_MARGIN = 0.02

EXCLUDED_REAL = frozenset({
    "f_stop", "focal_length", "focal_length_35mm", "exposure_compensation", "gps_latitude",
    "gps_longitude", "image_aspect", "raw_sharpness_variance", "raw_color_entropy",
    "raw_eye_sharpness", "sequence_ev_offset", "learned_score",
})
SCORE_COLUMNS = tuple(
    name for name, declaration in PHOTOS_COLUMNS
    if (declaration.startswith("REAL") and name not in EXCLUDED_REAL)
    or name in ("image_width", "image_height")
)
FLAG_COLUMNS = ("is_blink", "is_monochrome", "is_silhouette", "is_group_portrait",
                "shadow_clipped", "highlight_clipped")
TEXT_COLUMNS = ("category", "tags", "caption", "composition_pattern", "subject_bbox",
                "junk_kind", "narrative_moment")
SET_COLUMNS = ("sequence_kind", "sequence_group_id", "sequence_ev_offset", "is_sequence_lead",
               "burst_group_id", "is_burst_lead", "duplicate_group_id", "is_duplicate_lead")
PHOTO_COLUMNS_READ = (("path", "face_count") + SCORE_COLUMNS + FLAG_COLUMNS + TEXT_COLUMNS + SET_COLUMNS)
# Post passes, in order: (name, flag). Duplicates do not run at scan end, so they are explicit;
# moments, junk and sequences are also run explicitly so each gets its own recorded exit code.
POST_PASSES = (
    ("recompute-average", "--recompute-average"),
    ("detect-sequences", "--detect-sequences"),
    ("detect-duplicates", "--detect-duplicates"),
    ("detect-junk", "--detect-junk"),
    ("detect-moments", "--detect-moments"),
)


class SetupError(Exception):
    """A problem with the inputs, not a regression: exit code 2."""


# --------------------------------------------------------------------------- paths and refusal

def default_db_path():
    """Where facet resolves its default DB (``db.connection.DEFAULT_DB_PATH``), at call time."""
    return Path(os.environ.get("DB_PATH", "photo_scores_pro.db")).resolve()


def refuse_protected_db(db):
    """Raise unless ``db`` is a scratch DB: not the default DB, not any ``photo_scores_pro.db``."""
    path = Path(db).resolve()
    if path == default_db_path() or path.name.lower() == PROTECTED_DB_NAME:
        raise SetupError(f"refusing {path}: that is the default/production database; use a scratch DB")


def _norm(path):
    return str(path).replace("\\", "/")


def photo_root(set_dir):
    return Path(set_dir) / "photos"


def relative_path(db_path, set_dir):
    """Manifest-relative path of a stored path, or None when it is outside ``<set_dir>/photos``.

    Handles ``\\`` separators and case-insensitive drive/dir spelling (R4). Both the resolved
    and the as-given root are tried, since a scan stores the path it was handed.
    """
    stored = _norm(db_path)
    root = photo_root(set_dir)
    for candidate in (root, root.resolve(), root.absolute()):
        prefix = _norm(candidate).rstrip("/") + "/"
        if stored.casefold().startswith(prefix.casefold()):
            return stored[len(prefix):]
    return None


def path_to_id(manifest):
    """``({path: id}, {path.casefold(): id})`` of the manifest's photos."""
    exact = {photo["path"]: photo["id"] for photo in manifest["photos"]}
    return exact, {path.casefold(): pid for path, pid in exact.items()}


def connect_readonly(db):
    if not Path(db).exists():
        raise SetupError(f"database {db} does not exist")
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)


def assert_db_in_set(db, set_dir):
    """SetupError when ``db`` holds a photo outside ``<set_dir>/photos`` (R6)."""
    if not Path(db).exists():
        return
    conn = connect_readonly(db)
    try:
        paths = [row[0] for row in conn.execute("SELECT path FROM photos")]
    except sqlite3.DatabaseError as error:
        raise SetupError(f"{db} is not a Facet database: {error}") from error
    finally:
        conn.close()
    foreign = [path for path in paths if relative_path(path, set_dir) is None]
    if foreign:
        raise SetupError(f"{db} holds {len(foreign)} photo(s) outside {photo_root(set_dir)}, e.g. {foreign[0]}")


# --------------------------------------------------------------------------- export

def _round(value):
    if isinstance(value, float):
        return round(value, FLOAT_DIGITS)
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(item) for item in value]
    return value


def dump_json(data):
    """Deterministic text: sorted keys, 4-decimal floats, 2-space indent, trailing newline."""
    return json.dumps(_round(data), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_json(data).encode("utf8"))


def _parse_bbox(text):
    if text is None:
        return None
    try:
        return [round(float(v), FLOAT_DIGITS) for v in json.loads(text)]
    except (TypeError, ValueError):
        return None


def _group_sets(rows, key_columns, label_by_row):
    """``{(kind, group_id): [ids]}`` for rows with a non-null group id."""
    sets = {}
    for pid, row in rows.items():
        key = label_by_row(row)
        if key is not None:
            sets.setdefault(key, []).append(pid)
    return {key: sorted(ids) for key, ids in sets.items()}


def export_photos(db, set_dir, manifest):
    """The ``photos`` and ``sets`` blocks of a golden from a scan DB. NULL stays null.

    Raises SetupError for a photo outside the set; manifest photos the scan lacks are returned
    in the third element.
    """
    exact, folded = path_to_id(manifest)
    scored = {p["id"] for p in manifest["photos"] if p.get("scored") is not False}
    conn = connect_readonly(db)
    conn.row_factory = sqlite3.Row
    try:
        have = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
        cols = [c for c in PHOTO_COLUMNS_READ if c in have]
        rows, foreign = {}, []
        for row in conn.execute(f"SELECT {', '.join(cols)} FROM photos"):
            rel = relative_path(row["path"], set_dir)
            pid = None if rel is None else exact.get(rel) or folded.get(rel.casefold())
            if pid is None:
                foreign.append(row["path"])
            elif pid in scored:
                rows[pid] = row
        faces = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'faces'").fetchone():
            for face in conn.execute(
                "SELECT photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence "
                "FROM faces ORDER BY photo_path, face_index"
            ):
                rel = relative_path(face["photo_path"], set_dir)
                pid = None if rel is None else exact.get(rel) or folded.get(rel.casefold())
                if pid is not None:
                    faces.setdefault(pid, []).append({
                        "bbox": [face[f"bbox_{c}"] for c in ("x1", "y1", "x2", "y2")],
                        "confidence": face["confidence"],
                    })
    finally:
        conn.close()
    if foreign:
        raise SetupError(f"{db} holds {len(foreign)} photo(s) not in the manifest, e.g. {foreign[0]}")
    missing = sorted(scored - set(rows))
    photos = {pid: _photo_record(row, faces.get(pid, [])) for pid, row in rows.items()}
    return photos, _build_sets(rows), missing


def _get(row, name):
    return row[name] if name in row.keys() else None


def _photo_record(row, faces):
    tags = _get(row, "tags")
    return {
        "scores": {name: _get(row, name) for name in SCORE_COLUMNS},
        "category": _get(row, "category"),
        "tags": None if tags is None else sorted({t.strip() for t in tags.split(",") if t.strip()}),
        "caption": _get(row, "caption"),
        "face_count": _get(row, "face_count"),
        "faces": faces,
        "composition_pattern": _get(row, "composition_pattern"),
        "subject_bbox": _parse_bbox(_get(row, "subject_bbox")),
        "flags": {name: _get(row, name) for name in FLAG_COLUMNS},
        "sequence": {"kind": _get(row, "sequence_kind"), "ev_offset": _get(row, "sequence_ev_offset"),
                     "is_lead": _get(row, "is_sequence_lead"), "group": None},
        "burst": {"group": None, "is_lead": _get(row, "is_burst_lead")},
        "duplicate": {"group": None, "is_lead": _get(row, "is_duplicate_lead")},
        "junk_kind": _get(row, "junk_kind"),
        "narrative_moment": _get(row, "narrative_moment"),
    }


def _build_sets(rows):
    """Membership as sorted id tuples keyed by (kind, smallest member id), never raw group ids.

    Sequence sets are keyed by ``(sequence_kind, sequence_group_id)``: the bracket and panorama
    passes number independently, so the kind always comes first.
    """
    def seq(row):
        kind, group = _get(row, "sequence_kind"), _get(row, "sequence_group_id")
        return None if kind is None or group is None else (kind, group)

    def burst(row):
        group = _get(row, "burst_group_id")
        return None if group is None else ("burst", group)

    def dup(row):
        group = _get(row, "duplicate_group_id")
        return None if group is None else ("duplicate", group)

    out = {}
    for name, key in (("sequence", seq), ("burst", burst), ("duplicate", dup)):
        groups = _group_sets(rows, None, key)
        entries = sorted(
            ({"kind": kind, "label": ids[0], "members": ids} for (kind, _), ids in groups.items()),
            key=lambda e: (e["kind"], e["label"]),
        )
        out[name] = entries
    return out


def attach_labels(photos, sets):
    """Write each photo's canonical group label into its sequence/burst/duplicate block."""
    for name in ("sequence", "burst", "duplicate"):
        for entry in sets[name]:
            for pid in entry["members"]:
                photos[pid][name]["group"] = entry["label"]


def build_golden(db, set_dir, manifest, profile, environment):
    photos, sets, missing = export_photos(db, set_dir, manifest)
    if missing:
        raise SetupError(f"{len(missing)} scored manifest photo(s) are absent from {db}, e.g. {missing[0]}")
    attach_labels(photos, sets)
    return _round({
        "golden_version": GOLDEN_VERSION,
        "profile": profile,
        "manifest_sha256": rc.file_level_digest(manifest),
        "environment": environment,
        "photos": photos,
        "sets": sets,
    })


# --------------------------------------------------------------------------- environment

LIB_NAMES = ("torch", "transformers", "onnxruntime", "onnxruntime-gpu", "open_clip_torch", "pyiqa",
             "pillow", "numpy", "imagecodecs", "insightface", "mediapipe", "scikit-learn", "hdbscan")
HF_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def hf_cache_dir():
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(var):
            return Path(os.environ[var])
    home = os.environ.get("HF_HOME")
    return Path(home) / "hub" if home else Path.home() / ".cache" / "huggingface" / "hub"


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def hf_commits(config, cache=None):
    """``{repo: [snapshot commit dirs]}`` for every config string naming a cached HF repo (read only)."""
    cache = Path(cache) if cache else hf_cache_dir()
    out = {}
    for text in sorted(set(_strings(config))):
        if HF_ID.fullmatch(text):
            snapshots = cache / ("models--" + text.replace("/", "--")) / "snapshots"
            if snapshots.is_dir():
                out[text] = sorted(entry.name for entry in snapshots.iterdir())
    return out


def _lib_versions():
    libs = {"python": sys.version.split()[0]}
    for name in LIB_NAMES:
        try:
            libs[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            libs[name] = None
    return libs


def _hardware():
    info = {"os": sys.platform}
    try:
        import torch
    except ImportError:
        return info | {"torch": None}
    info["torch_cuda"] = torch.version.cuda
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info |= {"gpu": props.name, "vram_mb": props.total_memory // (1024 * 1024),
                 "capability": list(torch.cuda.get_device_capability(0))}
    else:
        info["gpu"] = None
    return info


def _exiftool_version():
    for exe in (shutil.which("exiftool"), str(Path.cwd() / "exiftool.exe")):
        if exe and Path(exe).exists():
            try:
                done = subprocess.run([exe, "-ver"], capture_output=True, text=True, timeout=30)
                return done.stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                return None
    return None


def _git_commit():
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=30)
        return done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _facet_version():
    match = re.search(r'^version\s*=\s*"([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text("utf8"), re.M)
    return match.group(1) if match else None


def collect_environment(profile, db, config_path=None):
    """The golden's environment block. Informational: it is never compared, only shown."""
    import config_resolve
    config = config_resolve.load_resolved(str(config_path), named=True) if config_path \
        else config_resolve.load_resolved()
    models = copy.deepcopy(config["models"])
    models["profiles"] = {profile: models.get("profiles", {}).get(profile)}
    passes = []
    sidecar = passes_path(db)
    if sidecar.exists():
        passes = json.loads(sidecar.read_text("utf8")).get("passes", [])
    return {
        "recorded_at": date.today().isoformat(),
        "facet_version": _facet_version(),
        "git_commit": _git_commit(),
        "config_version_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf8")).hexdigest(),
        "models": models,
        "pinned": {"iqa_extended": config.get("iqa_extended"),
                   "blendshapes": (config.get("face_detection") or {}).get("blendshapes"),
                   "processing_mode": (config.get("processing") or {}).get("mode")},
        "hf_commits": hf_commits(config),
        "libs": _lib_versions(),
        "hardware": _hardware(),
        "exiftool": _exiftool_version(),
        "passes": [{"name": p["name"], "exit_code": p["exit_code"]} for p in passes],
    }


# --------------------------------------------------------------------------- scan

def passes_path(db):
    return Path(str(db) + ".passes.json")


def operator_config_path():
    import config_resolve
    return Path(config_resolve.default_config_path())


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def default_runner(argv, env):
    return subprocess.call(argv, env=env)


def run_scan(profile, set_dir, db, config_dir=None, runner=default_runner, facet_py=None,
             operator_config=None):
    """Scan the set into a scratch DB, then the post passes; record every pass's exit code.

    ``runner(argv, env) -> int`` is injectable so tests assert the argv sequence without facet.
    Returns the number of failed passes (the sidecar tells which); raises SetupError on refusal
    or when the operator's ``scoring_config.json`` changed during the scan.
    """
    if profile not in PROFILES:
        raise SetupError(f"unknown profile {profile!r}")
    refuse_protected_db(db)
    assert_db_in_set(db, set_dir)
    source = Path(config_dir or CONFIG_DIR) / f"{profile}.json"
    if not source.exists():
        raise SetupError(f"no override config {source}")
    if not photo_root(set_dir).is_dir():
        raise SetupError(f"{photo_root(set_dir)} is not a directory")
    scratch = Path(str(db) + ".config")
    scratch.mkdir(parents=True, exist_ok=True)
    config = scratch / f"{profile}.json"
    shutil.copyfile(source, config)
    facet = str(facet_py or REPO_ROOT / "facet.py")
    common = ["--config", str(config), "--db", str(db)]
    steps = [("scan", [str(photo_root(set_dir)), *common])]
    steps += [(name, [flag, *common]) for name, flag in POST_PASSES]
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONUTF8="1")
    operator = Path(operator_config) if operator_config else operator_config_path()
    before = _file_hash(operator)
    results = []
    for name, args in steps:
        argv = [sys.executable, facet, *args]
        results.append({"name": name, "argv": argv[1:], "exit_code": runner(argv, env)})
    after = _file_hash(operator)
    passes_path(db).write_text(
        json.dumps({"profile": profile, "passes": results}, indent=2, sort_keys=True) + "\n", "utf8")
    if before != after:
        raise SetupError(f"operator config {operator} changed during the scan")
    return sum(1 for r in results if r["exit_code"] != 0)


def failed_passes(db):
    sidecar = passes_path(db)
    if not sidecar.exists():
        return []
    return [p["name"] + f" (exit {p['exit_code']})"
            for p in json.loads(sidecar.read_text("utf8")).get("passes", []) if p["exit_code"] != 0]


# --------------------------------------------------------------------------- statistics

def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation, or None for under 3 pairs or a constant side."""
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def jaccard(a, b):
    a, b = set(a or ()), set(b or ())
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def face_ious(before, after):
    """IoU of each golden face with its best unmatched current face (0.0 when none is left)."""
    free = list(after)
    out = []
    for face in before:
        best = max(free, key=lambda other: iou(face["bbox"], other["bbox"]), default=None)
        if best is None:
            out.append(0.0)
            continue
        free.remove(best)
        out.append(iou(face["bbox"], best["bbox"]))
    return out


def _member_map(golden):
    out = {}
    for name in ("sequence", "burst", "duplicate"):
        table = {}
        for entry in golden["sets"][name]:
            for pid in entry["members"]:
                table[pid] = (entry["kind"], tuple(entry["members"]))
        out[name] = table
    return out


def assignments(golden, maps, pid):
    """``{kind: signature}`` of one photo's set memberships, junk and moment, for diffing."""
    photo = golden["photos"][pid]
    return {
        "sequence": (maps["sequence"].get(pid), photo["sequence"]["is_lead"], photo["sequence"]["ev_offset"]),
        "burst": (maps["burst"].get(pid), photo["burst"]["is_lead"]),
        "duplicate": (maps["duplicate"].get(pid), photo["duplicate"]["is_lead"]),
        "junk": photo["junk_kind"],
        "moment": photo["narrative_moment"],
    }


# --------------------------------------------------------------------------- label metrics

def label_metrics(golden_like, manifest):
    """Confusion matrix, out-of-accepted list and per-category pairwise agreement for one scan."""
    photos = golden_like["photos"]
    by_id = {p["id"]: p for p in manifest["photos"]}
    matrix, outside = {}, []
    for pid, record in photos.items():
        label = by_id[pid]
        expected = label.get("expected_category")
        if expected is None:
            continue
        got = record["category"]
        matrix.setdefault(expected, {})
        matrix[expected][got] = matrix[expected].get(got, 0) + 1
        if got not in (label.get("acceptable_categories") or [expected]):
            outside.append({"id": pid, "expected": expected, "got": got})
    agreement = {}
    for pair in manifest["pairs"]:
        better, worse = photos.get(pair["better"]), photos.get(pair["worse"])
        if better is None or worse is None:
            continue
        entry = agreement.setdefault(pair["category"], {"pairs": 0, "agree": 0, "flipped": []})
        entry["pairs"] += 1
        good, bad = better["scores"].get("aggregate"), worse["scores"].get("aggregate")
        if good is not None and bad is not None and good > bad:
            entry["agree"] += 1
        else:
            entry["flipped"].append([pair["better"], pair["worse"]])
    return {"confusion": matrix, "outside": sorted(outside, key=lambda o: o["id"]), "agreement": agreement}


# --------------------------------------------------------------------------- diff engine

class Tolerances:
    """Limits from ``reference_tolerances.json``; ``None`` limits mean report-only."""

    def __init__(self, data):
        self.data = data

    def get(self, *keys, default=None):
        node = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def score(self, column):
        table = self.data.get("score_abs", {})
        return table.get(column, table.get("_default", SCORE_FLOOR))

    def per_case(self, name, case, default=0):
        table = self.data.get(name, {})
        if isinstance(table, dict):
            return table.get(case, table.get("_default", default))
        return table


def _photo_diff(before, after, golden_maps, current_maps):
    """Raw per-photo differences, tolerance-free."""
    scores = {}
    for column in SCORE_COLUMNS:
        a, b = before["scores"].get(column), after["scores"].get(column)
        if a is None and b is None:
            continue
        scores[column] = None if a is None or b is None else b - a
    ious = face_ious(before["faces"], after["faces"]) if before["faces"] else []
    subject = None
    if before["subject_bbox"] and after["subject_bbox"]:
        subject = iou(before["subject_bbox"], after["subject_bbox"])
    elif before["subject_bbox"] != after["subject_bbox"]:
        subject = 0.0
    return {
        "scores": scores,
        "flip": before["category"] != after["category"],
        "face_delta": (after["face_count"] or 0) - (before["face_count"] or 0),
        "face_iou": min(ious) if ious else None,
        "faces_lost": max(0, len(before["faces"]) - len(after["faces"])),
        "subject_iou": subject,
        "jaccard": None if before["tags"] is None and after["tags"] is None
        else jaccard(before["tags"], after["tags"]),
        "assign": {kind: (golden_maps[kind] != current_maps[kind]) for kind in golden_maps},
    }


def _norm_scale(golden):
    scale = {}
    for column in SCORE_COLUMNS:
        values = [p["scores"].get(column) for p in golden["photos"].values() if p["scores"].get(column) is not None]
        if len(values) > 1:
            mean = sum(values) / len(values)
            std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        else:
            std = 0.0
        scale[column] = std or 1.0
    return scale


def compare(golden, current, manifest, tolerances=None):
    """Diff ``current`` against ``golden`` into a report dict with a ``violations`` list.

    Violations are produced per CASE as well as overall, so a regression confined to a small
    case fails even when the whole-set statistics stay inside tolerance. With
    ``tolerances=None`` nothing is a violation (report-only).
    """
    tol = Tolerances(tolerances) if tolerances is not None else None
    ids = sorted(set(golden["photos"]) & set(current["photos"]))
    by_id = {p["id"]: p for p in manifest["photos"]}
    maps_then, maps_now = _member_map(golden), _member_map(current)
    diffs = {
        pid: _photo_diff(golden["photos"][pid], current["photos"][pid],
                         assignments(golden, maps_then, pid), assignments(current, maps_now, pid))
        for pid in ids
    }
    case_members = {OVERALL: ids}
    for pid in ids:
        for case in by_id[pid].get("cases") or ():
            case_members.setdefault(case, []).append(pid)
    violations = []

    def violate(case, metric, photo, value, limit):
        violations.append({"case": case, "metric": metric, "photo": photo, "value": value, "limit": limit})

    cases = {}
    for case, members in sorted(case_members.items()):
        row = {"photos": len(members), "faces_lost_photos": 0, "category_flips": 0, "score_moved": 0,
               "worst_jaccard": None, "worst_face_iou": None, "worst_subject_iou": None,
               "assignment_changes": {}}
        for pid in members:
            d = diffs[pid]
            row["category_flips"] += d["flip"]
            row["faces_lost_photos"] += d["faces_lost"] > 0 or d["face_delta"] < 0
            if any(v is None or abs(v) > 1e-9 for v in d["scores"].values()):
                row["score_moved"] += 1
            for key, value in (("worst_jaccard", d["jaccard"]), ("worst_face_iou", d["face_iou"]),
                               ("worst_subject_iou", d["subject_iou"])):
                if value is not None:
                    row[key] = value if row[key] is None else min(row[key], value)
            for kind, changed in d["assign"].items():
                if changed:
                    row["assignment_changes"][kind] = row["assignment_changes"].get(kind, 0) + 1
            if tol is None:
                continue
            for column, delta in d["scores"].items():
                limit = tol.score(column)
                if delta is None:
                    violate(case, f"score_presence:{column}", pid, None, None)
                elif abs(delta) > limit:
                    violate(case, f"score_abs:{column}", pid, round(abs(delta), 4), limit)
            if abs(d["face_delta"]) > tol.get("face_count_change_max", default=0):
                violate(case, "face_count", pid, d["face_delta"], tol.get("face_count_change_max", default=0))
            for metric, value, key in (("face_bbox_iou", d["face_iou"], "bbox_iou_min"),
                                       ("subject_bbox_iou", d["subject_iou"], "bbox_iou_min"),
                                       ("tag_jaccard", d["jaccard"], "tag_jaccard_min")):
                limit = tol.get(key)
                if limit is not None and value is not None and value < limit:
                    violate(case, metric, pid, round(value, 4), limit)
        cases[case] = row
        if tol is None:
            continue
        flips_allowed = tol.per_case("category_flips_max", case)
        if row["category_flips"] > flips_allowed:
            violate(case, "category_flips", None, row["category_flips"], flips_allowed)
        for kind, count in row["assignment_changes"].items():
            allowed = tol.get("assignment_changes_max", kind, default=tol.get("assignment_changes_max", "_default", default=0))
            if count > allowed:
                violate(case, f"assignment:{kind}", None, count, allowed)
    srcc = {}
    for column in SCORE_COLUMNS:
        pairs = [(golden["photos"][p]["scores"].get(column), current["photos"][p]["scores"].get(column)) for p in ids]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        value = spearman([a for a, _ in pairs], [b for _, b in pairs])
        if value is not None:
            srcc[column] = value
            limit = tol.get("srcc_min", column) if tol else None
            if limit is not None and value < limit:
                violate(OVERALL, f"srcc:{column}", None, round(value, 4), limit)
    labels_now, labels_then = label_metrics(current, manifest), label_metrics(golden, manifest)
    label_report = _label_report(labels_now, labels_then, tol, violate)
    most_moved = _most_moved(ids, diffs, _norm_scale(golden))
    return {
        "photos": len(ids), "srcc": srcc, "cases": cases, "most_moved": most_moved,
        "labels": label_report, "violations": violations,
        "known_gaps": sorted(c for c, v in manifest["cases"].items() if v.get("known_gap")),
        "report_only": tol is None,
    }


def _label_report(now, then, tol, violate):
    min_pairs = (tol.get("label", "min_pairs", default=MIN_PAIRS) if tol else MIN_PAIRS)
    errors = {}
    for expected, row in now["confusion"].items():
        errors[expected] = sum(n for got, n in row.items() if got != expected)
    errors_then = {e: sum(n for g, n in row.items() if g != e) for e, row in then["confusion"].items()}
    outside_now = {o["id"] for o in now["outside"]}
    outside_then = {o["id"] for o in then["outside"]}
    agreement, not_checked = {}, []
    for category, entry in sorted(now["agreement"].items()):
        before = then["agreement"].get(category, {"agree": 0, "pairs": 0})
        rate = entry["agree"] / entry["pairs"]
        rate_then = before["agree"] / before["pairs"] if before["pairs"] else None
        agreement[category] = {"pairs": entry["pairs"], "agree": entry["agree"], "rate": rate,
                               "golden_rate": rate_then, "flipped": entry["flipped"],
                               "low_confidence": entry["pairs"] < min_pairs}
        if entry["pairs"] < min_pairs:
            not_checked.append(f"pairs-{category}: {entry['pairs']} pair(s) < {min_pairs} (LOW-CONFIDENCE)")
            continue
        margin = tol.get("label", "pair_agreement_margin", default=0) if tol else None
        if tol is not None and rate_then is not None and rate < rate_then - margin:
            violate(category, "pair_agreement", None, round(rate, 4), round(rate_then - margin, 4))
    for category in rc.LABELLED_CATEGORIES:
        if category not in now["agreement"]:
            not_checked.append(f"pairs-{category}: no pairs (LOW-CONFIDENCE)")
    if tol is not None:
        margin = tol.get("label", "confusion_errors_margin", default=0)
        for expected, count in errors.items():
            if count > errors_then.get(expected, 0) + margin:
                violate(expected, "confusion_errors", None, count, errors_then.get(expected, 0) + margin)
        for pid in sorted(outside_now - outside_then):
            violate("labels", "outside_accepted", pid, None, None)
    return {"confusion": now["confusion"], "confusion_errors": errors, "outside_accepted": now["outside"],
            "newly_outside": sorted(outside_now - outside_then), "agreement": agreement,
            "not_checked": not_checked}


def _most_moved(ids, diffs, scale):
    ranked = []
    for pid in ids:
        deltas = diffs[pid]["scores"]
        worst = max(((abs(v) / scale[c], c) for c, v in deltas.items() if v is not None), default=(0.0, None))
        ranked.append((worst[0], pid, worst[1]))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return [{"photo": pid, "normalised": round(value, 4), "column": column}
            for value, pid, column in ranked[:TOP_N] if value > 0]


# --------------------------------------------------------------------------- report

def render_report(report):
    lines = ["== (1) overall ==", f"photos compared: {report['photos']}"
             + ("   [REPORT-ONLY: no tolerances]" if report["report_only"] else "")]
    for column, value in sorted(report["srcc"].items()):
        lines.append(f"  SRCC {column}: {value:.4f}")
    lines += ["", "== (2) per case =="]
    for case, row in report["cases"].items():
        parts = []
        if row["faces_lost_photos"]:
            parts.append(f"{row['faces_lost_photos']} of {row['photos']} lost a face")
        if row["category_flips"]:
            parts.append(f"{row['category_flips']} category flips")
        if row["score_moved"]:
            parts.append(f"{row['score_moved']} score(s) moved")
        for kind, count in sorted(row["assignment_changes"].items()):
            parts.append(f"{count} {kind} change(s)")
        lines.append(f"  {case}: " + ("; ".join(parts) if parts else f"ok ({row['photos']} photos)"))
    lines += ["", f"== (3) top {TOP_N} most moved =="]
    lines += [f"  {m['photo']}: {m['normalised']} ({m['column']})" for m in report["most_moved"]] or ["  none"]
    labels = report["labels"]
    lines += ["", "== (4) category confusion (rows expected, columns scored) =="]
    for expected, row in sorted(labels["confusion"].items()):
        lines.append(f"  {expected}: " + ", ".join(f"{got}={n}" for got, n in sorted(row.items(), key=lambda i: str(i[0]))))
    lines.append("  outside acceptable_categories: " + (
        ", ".join(f"{o['id']} ({o['expected']}->{o['got']})" for o in labels["outside_accepted"]) or "none"))
    lines += ["", "== (5) pairwise agreement =="]
    for category, entry in labels["agreement"].items():
        tag = " LOW-CONFIDENCE" if entry["low_confidence"] else ""
        lines.append(f"  {category}: {entry['agree']}/{entry['pairs']}{tag}"
                     + (f"  flipped: {entry['flipped']}" if entry["flipped"] else ""))
    lines += ["", "== (6) sequence / burst / duplicate / junk / moment changes =="]
    changes = [(case, kind, n) for case, row in report["cases"].items() for kind, n in row["assignment_changes"].items()
               if case == OVERALL]
    lines += [f"  {kind}: {n} photo(s) changed" for _, kind, n in changes] or ["  none"]
    lines += ["", "== NOT CHECKED (a green run is not full coverage) =="]
    lines += [f"  {item}" for item in labels["not_checked"]]
    lines += [f"  known gap case: {case}" for case in report["known_gaps"]]
    lines += ["", f"violations: {len(report['violations'])}"]
    for v in report["violations"][:50]:
        lines.append(f"  [{v['case']}] {v['metric']}" + (f" {v['photo']}" if v["photo"] else "")
                     + f": {v['value']} vs limit {v['limit']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands

def _load_inputs(args):
    manifest = rc.load_manifest(args.manifest)
    refuse_protected_db(args.db)
    assert_db_in_set(args.db, args.set_dir)
    for photo in manifest["photos"]:
        if not (photo_root(args.set_dir) / photo["path"]).exists():
            raise SetupError(f"set file missing: {photo['path']}")
    return manifest


def _golden_path(args):
    return Path(args.golden) if getattr(args, "golden", None) else GOLDEN_DIR / f"{args.profile}.json"


def _load_golden(path, manifest, profile):
    if not Path(path).exists():
        raise SetupError(f"golden {path} does not exist")
    golden = json.loads(Path(path).read_text("utf8"))
    if golden.get("manifest_sha256") != rc.file_level_digest(manifest):
        raise SetupError("manifest digest differs from the golden's: re-record the golden")
    if golden.get("profile") != profile:
        raise SetupError(f"golden is for profile {golden.get('profile')!r}, not {profile!r}")
    return golden


def _current(args, manifest):
    failed = failed_passes(args.db)
    if failed:
        raise SetupError("scan incomplete, failed pass(es): " + ", ".join(failed))
    return build_golden(args.db, args.set_dir, manifest, args.profile, {})


def cmd_record(args):
    manifest = _load_inputs(args)
    current = build_golden(args.db, args.set_dir, manifest, args.profile,
                           collect_environment(args.profile, args.db, _scan_config(args)))
    write_json(args.out, current)
    print(f"recorded {len(current['photos'])} photos to {args.out}")
    return 0


def _scan_config(args):
    path = Path(str(args.db) + ".config") / f"{args.profile}.json"
    return path if path.exists() else None


def cmd_check(args):
    manifest = _load_inputs(args)
    golden = _load_golden(_golden_path(args), manifest, args.profile)
    current = _current(args, manifest)
    tolerances = None
    path = Path(args.tolerances) if args.tolerances else TOLERANCES_PATH
    if path.exists():
        tolerances = json.loads(path.read_text("utf8"))
    elif args.tolerances:
        raise SetupError(f"tolerances {path} does not exist")
    report = compare(golden, current, manifest, tolerances)
    print(render_report(report))
    if args.json:
        write_json(args.json, report)
    if report["violations"] and not args.report_only and tolerances is not None:
        return 1
    return 0


def moved_fraction(golden, current):
    ids = sorted(set(golden["photos"]) | set(current["photos"]))
    moved = sum(1 for pid in ids if _round(golden["photos"].get(pid)) != _round(current["photos"].get(pid)))
    return moved / len(ids) if ids else 0.0


def cmd_update(args):
    manifest = _load_inputs(args)
    path = _golden_path(args)
    golden = _load_golden(path, manifest, args.profile)
    current = build_golden(args.db, args.set_dir, manifest, args.profile,
                           collect_environment(args.profile, args.db, _scan_config(args)))
    print(render_report(compare(golden, current, manifest, None)))
    fraction = moved_fraction(golden, current)
    print(f"\nphotos moved: {fraction:.0%}")
    if fraction > UPDATE_MOVED_LIMIT and not args.yes:
        print(f"refusing: more than {UPDATE_MOVED_LIMIT:.0%} of photos moved; pass --yes to rewrite")
        return 1
    write_json(path, current)
    print(f"golden {path} rewritten")
    return 0


# --------------------------------------------------------------------------- tolerances

def derive_tolerances(exports, manifest):
    """Tolerances from >= 2 repeat exports of the same set (spec "Tolerances plan")."""
    if len(exports) < 2:
        raise SetupError("tolerances need at least 2 runs")
    ids = sorted(set.intersection(*(set(e["photos"]) for e in exports)))
    score_abs = {"_default": SCORE_FLOOR}
    for column in SCORE_COLUMNS:
        worst = 0.0
        for pid in ids:
            values = [e["photos"][pid]["scores"].get(column) for e in exports]
            if None in values:
                continue
            mean = sum(values) / len(values)
            std = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
            worst = max(worst, std)
        score_abs[column] = round(max(3 * worst, SCORE_FLOOR), 4)
    pairs = [(a, b) for i, a in enumerate(exports) for b in exports[i + 1:]]
    srcc_min, jaccards, ious, face_changes = {}, [], [], 0
    flips_by_case, assign_max = {}, {}
    agreement_drop, confusion_rise = 0.0, 0
    for a, b in pairs:
        report = compare(a, b, manifest, None)
        for column, value in report["srcc"].items():
            srcc_min[column] = min(srcc_min.get(column, 1.0), value)
        for case, row in report["cases"].items():
            flips_by_case[case] = max(flips_by_case.get(case, 0), row["category_flips"])
            for key in ("worst_jaccard",):
                if row[key] is not None:
                    jaccards.append(row[key])
            for key in ("worst_face_iou", "worst_subject_iou"):
                if row[key] is not None:
                    ious.append(row[key])
            for kind, count in row["assignment_changes"].items():
                assign_max[kind] = max(assign_max.get(kind, 0), count)
        for pid in ids:
            face_changes = max(face_changes, abs(b["photos"][pid]["face_count"] - a["photos"][pid]["face_count"]))
        labels = report["labels"]
        for entry in labels["agreement"].values():
            if entry["golden_rate"] is not None and not entry["low_confidence"]:
                agreement_drop = max(agreement_drop, entry["golden_rate"] - entry["rate"])
        for expected, count in labels["confusion_errors"].items():
            then = label_metrics(a, manifest)["confusion"].get(expected, {})
            confusion_rise = max(confusion_rise, count - sum(n for g, n in then.items() if g != expected))
    return {
        "derived_from_runs": len(exports),
        "score_abs": score_abs,
        "srcc_min": {c: round(v - SRCC_MARGIN, 4) for c, v in sorted(srcc_min.items())},
        "tag_jaccard_min": round(max(0.0, (min(jaccards) if jaccards else 1.0) - JACCARD_MARGIN), 4),
        "category_flips_max": {"_default": 0, **dict(sorted(flips_by_case.items()))},
        "face_count_change_max": face_changes,
        "assignment_changes_max": {"_default": 0, **dict(sorted(assign_max.items()))},
        "bbox_iou_min": round(max(0.0, (min(ious) if ious else 1.0) - IOU_MARGIN), 4),
        "label": {"min_pairs": MIN_PAIRS, "pair_agreement_margin": round(agreement_drop, 4),
                  "confusion_errors_margin": max(0, confusion_rise)},
    }


def cmd_tolerances(args):
    manifest = rc.load_manifest(args.manifest)
    exports = []
    for db in args.runs:
        refuse_protected_db(db)
        assert_db_in_set(db, args.set_dir)
        exports.append(build_golden(db, args.set_dir, manifest, args.profile, {}))
    tolerances = derive_tolerances(exports, manifest)
    write_json(args.out, tolerances)
    print(f"tolerances from {len(exports)} runs written to {args.out}")
    if not args.holdout:
        return 0
    refuse_protected_db(args.holdout)
    assert_db_in_set(args.holdout, args.set_dir)
    held = build_golden(args.holdout, args.set_dir, manifest, args.profile, {})
    report = compare(exports[0], held, manifest, tolerances)
    print(render_report(report))
    print("HOLD-OUT " + ("PASS" if not report["violations"] else "FAIL"))
    return 1 if report["violations"] else 0


def cmd_scan(args):
    failed = run_scan(args.profile, args.set_dir, args.db, args.config_dir)
    print(f"scan finished; {failed} failed pass(es); see {passes_path(args.db)}")
    return 1 if failed else 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, db=True):
        p.add_argument("--profile", required=True, choices=PROFILES)
        p.add_argument("--set-dir", required=True)
        p.add_argument("--manifest", default=str(rc.MANIFEST_PATH))
        if db:
            p.add_argument("--db", required=True)
        return p

    p = common(sub.add_parser("scan", help="scan the set into a scratch DB"))
    p.add_argument("--config-dir", default=None)
    p.set_defaults(func=cmd_scan)
    p = common(sub.add_parser("record", help="export a golden"))
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_record)
    p = common(sub.add_parser("check", help="diff a scan against its golden"))
    p.add_argument("--golden")
    p.add_argument("--tolerances")
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--json")
    p.set_defaults(func=cmd_check)
    p = common(sub.add_parser("update", help="rewrite the golden only"))
    p.add_argument("--golden")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_update)
    p = common(sub.add_parser("tolerances", help="derive tolerances from repeat runs"), db=False)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--holdout")
    p.add_argument("--out", default=str(TOLERANCES_PATH))
    p.set_defaults(func=cmd_tolerances)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SetupError as error:
        print(f"setup error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
