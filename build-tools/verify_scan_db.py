"""Validate that a Facet scan DB is properly filled with valid data.

Usage: python build-tools/verify_scan_db.py <db_path> [profile]

Checks, per photo row: fill rate + value range for the scalar score columns, tag
validity, embedding presence, face metrics, and saliency/IQA coverage. Flags any
NaN/inf, out-of-range aesthetic scores, empty required columns, or zero rows.
Exit code 0 = all core checks passed, 1 = a problem was found.
"""
import json
import math
import sqlite3
import sys

DB = sys.argv[1]
PROFILE = sys.argv[2] if len(sys.argv) > 2 else "?"

# Score columns expected on every profile (all now run saliency + supplementary IQA).
CORE = [
    "aesthetic", "aggregate", "comp_score", "aesthetic_iaa", "liqe_score",
    "subject_sharpness", "subject_prominence", "bg_separation",
]
# Informational (profile-dependent: e.g. topiq_score only on TOPIQ profiles,
# face_quality_iqa only where a face exists).
INFO = [
    "topiq_score", "face_quality_iqa", "tech_sharpness", "color_score",
    "exposure_score", "subject_placement", "noise_sigma", "contrast_score",
]
SCORE_0_10 = {"aesthetic", "aggregate", "comp_score", "topiq_score"}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
rows = conn.execute("SELECT * FROM photos").fetchall()
n = len(rows)

problems = []
print(f"=== DB {DB}  (profile={PROFILE})  photos={n} ===")
if n == 0:
    print("FAIL: no photos in DB")
    sys.exit(1)


def stats(col):
    vals = [r[col] for r in rows if r[col] is not None]
    nan = sum(1 for v in vals if isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    mn = min(vals) if vals else None
    mx = max(vals) if vals else None
    return len(vals), mn, mx, nan


def show(col, required):
    if col not in cols:
        print(f"  {col:22} (column absent)")
        return
    filled, mn, mx, nan = stats(col)
    tag = "REQ" if required else "   "
    print(f"  {tag} {col:22} {filled}/{n}  range=[{mn},{mx}]  nan/inf={nan}")
    if nan:
        problems.append(f"{col}: {nan} NaN/inf values")
    if required and filled == 0:
        problems.append(f"{col}: required but 0/{n} filled")
    if col in SCORE_0_10 and filled:
        if mn is not None and (mn < 0 or mx > 10.001):
            problems.append(f"{col}: out of 0..10 range [{mn},{mx}]")


print("-- core score columns (must be filled + in range) --")
for c in CORE:
    show(c, required=True)
print("-- informational columns --")
for c in INFO:
    show(c, required=False)

# Tags
tag_counts = []
for r in rows:
    t = r["tags"]
    if not t:
        tag_counts.append(0)
    elif t.strip().startswith("["):
        try:
            tag_counts.append(len(json.loads(t)))
        except Exception:
            tag_counts.append(-1)
    else:
        tag_counts.append(len([x for x in t.split(",") if x.strip()]))
tagged = sum(1 for x in tag_counts if x > 0)
print(f"-- tags: {tagged}/{n} photos tagged; per-photo counts={tag_counts}")
if tagged == 0:
    problems.append("tags: 0 photos tagged")

# Embedding + faces + moment
emb = sum(1 for r in rows if ("clip_embedding" in cols and r["clip_embedding"] is not None))
print(f"-- clip_embedding: {emb}/{n}")
if emb < n:
    problems.append(f"clip_embedding: only {emb}/{n}")
if "face_count" in cols:
    fc = [r["face_count"] for r in rows]
    print(f"-- face_count: {fc}  (faces detected on {sum(1 for x in fc if x)}/{n})")
if "narrative_moment" in cols:
    moments = [r["narrative_moment"] for r in rows]
    filled = sum(1 for m in moments if m)
    print(f"-- narrative_moment: {filled}/{n}  values={sorted(set(m for m in moments if m))}")
if "caption" in cols:
    caps = sum(1 for r in rows if r["caption"])
    print(f"-- caption (VLM-only profiles): {caps}/{n}")
if "scoring_model" in cols:
    print(f"-- scoring_model: {sorted(set(r['scoring_model'] for r in rows))}")

print()
if problems:
    print("RESULT: FAIL")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("RESULT: PASS — all core columns filled with valid (in-range, non-NaN) data")
sys.exit(0)
