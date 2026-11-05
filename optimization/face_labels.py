"""Hand-labelled face ground truth for the small-face recall harness (issue #468).

    python -m optimization.face_labels sample --db photo_scores.db --out $TESTDB/facelabels
    # box the faces in labelme (label ``face``, rectangle tool), saving the JSON next to each image
    python -m optimization.face_labels import --labelme-dir $TESTDB/facelabels/images \\
        --manifest $TESTDB/facelabels/manifest.csv --out $TESTDB/facelabels/labels.json

then ``python facet.py --evaluate-models faces-detect --face-labels labels.json``.

This module owns the labels schema (load / write / clip), the candidate sampler and the
labelme importer. The library DB is opened read-only; the only files written are under
``--out``. Labels live outside git.
"""

import argparse
import csv
import json
import logging
import os
import sys

from optimization.eval_common import load_original, ro_connection, stratified_sample_rows

logger = logging.getLogger("facet.face_labels")

LABELS_VERSION = 1
LABEL_NAME = 'face'
DEFAULT_POSITIVES = 150
DEFAULT_NEGATIVES = 50
HIGH_RES_SHARE = 0.25            # share of positives from face_count 2-3 on large frames
HIGH_RES_PIXELS = 20_000_000
WIDE_FOCAL_MM = 35
MIN_POSITIVE_FACES = 4
EVENT_DAY_MIN_PHOTOS = 20        # no albums: a day with this many candidates stands in for an event
JPEG_QUALITY = 95
MANIFEST_FIELDS = ('index', 'path', 'kind', 'width', 'height')


# ---------------------------------------------------------------------------
# Labels schema
# ---------------------------------------------------------------------------

def clip_box(box, width, height):
    """``box`` clipped to the frame; ``ValueError`` when nothing is left of it."""
    x1, y1, x2, y2 = (float(v) for v in box)
    x1, x2 = max(0.0, min(x1, width)), max(0.0, min(x2, width))
    y1, y2 = max(0.0, min(y1, height)), max(0.0, min(y2, height))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"box {list(box)} has no area inside the {width}x{height} frame")
    return [x1, y1, x2, y2]


def load_labels(path):
    """Validated ``[(photo_path, width, height, [[x1, y1, x2, y2], ...])]``.

    An empty face list is a reviewed no-face photo.
    """
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get('version') != LABELS_VERSION:
        raise ValueError(f"{path}: expected a labels file with version {LABELS_VERSION}")
    out, seen = [], set()
    for entry in data.get('photos', []):
        p, w, h = entry['path'], int(entry['width']), int(entry['height'])
        if p in seen:
            raise ValueError(f"{path}: duplicate photo path {p}")
        seen.add(p)
        faces = []
        for box in entry['faces']:
            x1, y1, x2, y2 = (float(v) for v in box)
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"{p}: box {box} has no area")
            if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
                raise ValueError(f"{p}: box {box} is outside the {w}x{h} frame")
            faces.append([x1, y1, x2, y2])
        out.append((p, w, h, faces))
    return out


def write_labels(path, photos):
    """Write ``[(photo_path, width, height, faces)]`` as a labels file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {'version': LABELS_VERSION,
               'photos': [{'path': p, 'width': w, 'height': h, 'faces': [list(b) for b in faces]}
                          for p, w, h, faces in photos]}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------

def _positive_paths(conn, n_pos, seed):
    """Stratified positives: ~75% many-face wide-angle (event photos preferred), the rest
    two/three-face large frames so photos the 640 px detector under-counted can appear."""
    n_big = round(n_pos * HIGH_RES_SHARE)
    n_main = n_pos - n_big
    focal = "COALESCE(p.focal_length_35mm, p.focal_length)"
    main = list(conn.execute(
        "SELECT p.path, COALESCE(p.aggregate, 0), substr(p.date_taken, 1, 10), "
        "EXISTS (SELECT 1 FROM album_photos a WHERE a.photo_path = p.path) "
        f"FROM photos p WHERE p.face_count >= ? AND {focal} <= ?", (MIN_POSITIVE_FACES, WIDE_FOCAL_MM)))
    if conn.execute("SELECT 1 FROM album_photos LIMIT 1").fetchone():
        event = {r[0] for r in main if r[3]}
    else:  # a library without albums: photos from a busy day stand in for an event
        per_day = {}
        for r in main:
            per_day[r[2]] = per_day.get(r[2], 0) + 1
        event = {r[0] for r in main if r[2] and per_day[r[2]] >= EVENT_DAY_MIN_PHOTOS}
    chosen = stratified_sample_rows([(r[0], r[1]) for r in main if r[0] in event], n_main, seed)
    if len(chosen) < n_main:
        chosen += stratified_sample_rows([(r[0], r[1]) for r in main if r[0] not in event],
                                         n_main - len(chosen), seed + 1)
    big = [(r[0], r[1]) for r in conn.execute(
        "SELECT p.path, COALESCE(p.aggregate, 0) FROM photos p WHERE p.face_count BETWEEN 2 AND 3 "
        "AND COALESCE(p.image_width, 0) * COALESCE(p.image_height, 0) >= ?", (HIGH_RES_PIXELS,))]
    taken = {p for p, _ in chosen}
    chosen += stratified_sample_rows([r for r in big if r[0] not in taken], n_big, seed + 2)
    return [p for p, _ in chosen]


def _negative_paths(conn, n_neg, seed):
    rows = [(r[0], r[1]) for r in conn.execute(
        "SELECT p.path, COALESCE(p.aggregate, 0) FROM photos p WHERE COALESCE(p.face_count, 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.photo_path = p.path)")]
    return [p for p, _ in stratified_sample_rows(rows, n_neg, seed + 3)]


def sample_photos(db_path, out_dir, n_pos=DEFAULT_POSITIVES, n_neg=DEFAULT_NEGATIVES, loader=None):
    """Pick candidates, export full-resolution orientation-baked JPEGs and write ``manifest.csv``.

    Selection reads only stored ``face_count`` / focal length / albums, never detector output
    beyond that count, so it is biased toward photos the 640 px detector already works on
    (the 2-3 face large-frame stratum partly offsets that). Returns the manifest rows.
    """
    from optimization.model_eval import DEFAULT_SEED
    loader = loader or load_original
    out_dir = os.path.abspath(out_dir)
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        raise ValueError(f"{out_dir} is not empty; refusing to overwrite a labelling session")
    conn = ro_connection(db_path)
    try:
        picks = ([(p, 'positive') for p in _positive_paths(conn, n_pos, DEFAULT_SEED)]
                 + [(p, 'negative') for p in _negative_paths(conn, n_neg, DEFAULT_SEED)])
    finally:
        conn.close()
    images = os.path.join(out_dir, 'images')
    os.makedirs(images, exist_ok=True)
    manifest = []
    for path, kind in sorted(picks):
        img = loader(path)
        if img is None:
            logger.warning("unreadable, skipped: %s", path)
            continue
        index = f"{len(manifest) + 1:04d}"
        img.convert('RGB').save(os.path.join(images, f"{index}.jpg"), quality=JPEG_QUALITY)
        manifest.append({'index': index, 'path': path, 'kind': kind,
                         'width': img.width, 'height': img.height})
    with open(os.path.join(out_dir, 'manifest.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)
    return manifest


# ---------------------------------------------------------------------------
# labelme importer
# ---------------------------------------------------------------------------

def import_labelme(labelme_dir, manifest_path, out_path):
    """Convert a folder of labelme JSON files to a Facet labels file; returns the entries.

    A manifest image with no JSON is an error (never silently "no faces"); a JSON with zero
    shapes is a reviewed no-face photo. Only ``rectangle`` shapes labelled ``face`` are accepted.
    """
    with open(manifest_path, newline='', encoding='utf-8') as f:
        manifest = list(csv.DictReader(f))
    missing = [m['index'] for m in manifest
               if not os.path.isfile(os.path.join(labelme_dir, f"{m['index']}.json"))]
    if missing:
        raise ValueError(f"no labelme JSON for image(s) {', '.join(missing)}; label them (save with no "
                         "shapes when there is no face) before importing")
    photos = []
    for m in manifest:
        with open(os.path.join(labelme_dir, f"{m['index']}.json"), encoding='utf-8') as f:
            doc = json.load(f)
        w, h = int(m['width']), int(m['height'])
        if (int(doc.get('imageWidth', -1)), int(doc.get('imageHeight', -1))) != (w, h):
            raise ValueError(f"image {m['index']}: labelme says {doc.get('imageWidth')}x{doc.get('imageHeight')} "
                             f"but the manifest says {w}x{h}")
        faces = []
        for shape in doc.get('shapes', []):
            if shape.get('shape_type') != 'rectangle' or shape.get('label') != LABEL_NAME:
                raise ValueError(f"image {m['index']}: only rectangles labelled {LABEL_NAME!r} are accepted, "
                                 f"got {shape.get('shape_type')!r} {shape.get('label')!r}")
            points = shape.get('points') or []
            if len(points) < 2:
                raise ValueError(f"image {m['index']}: a rectangle needs 2 points, got {len(points)}")
            xs, ys = [pt[0] for pt in points], [pt[1] for pt in points]
            faces.append(clip_box([min(xs), min(ys), max(xs), max(ys)], w, h))
        photos.append((m['path'], w, h, faces))
    write_labels(out_path, photos)
    return photos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_labels_dir():
    testdb = os.environ.get('TESTDB')
    return os.path.join(testdb, 'facelabels') if testdb else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m optimization.face_labels',
                                     description='Sample photos for, and import, hand-labelled face boxes')
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('sample', help='export candidate photos for labelling')
    s.add_argument('--db', required=True)
    s.add_argument('--out', default=_default_labels_dir(), help='empty output directory (default $TESTDB/facelabels)')
    s.add_argument('--positives', type=int, default=DEFAULT_POSITIVES)
    s.add_argument('--negatives', type=int, default=DEFAULT_NEGATIVES)
    i = sub.add_parser('import', help='convert labelme JSON to a Facet labels file')
    base = _default_labels_dir()
    i.add_argument('--labelme-dir', default=base and os.path.join(base, 'images'))
    i.add_argument('--manifest', default=base and os.path.join(base, 'manifest.csv'))
    i.add_argument('--out', default=base and os.path.join(base, 'labels.json'))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        if args.command == 'sample':
            if not args.out:
                parser.error('--out is required when $TESTDB is not set')
            rows = sample_photos(args.db, args.out, args.positives, args.negatives)
            print(f"exported {len(rows)} photos to {args.out}")
        else:
            if not (args.labelme_dir and args.manifest and args.out):
                parser.error('--labelme-dir, --manifest and --out are required when $TESTDB is not set')
            photos = import_labelme(args.labelme_dir, args.manifest, args.out)
            print(f"wrote {len(photos)} photos, {sum(len(p[3]) for p in photos)} faces to {args.out}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
