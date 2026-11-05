"""Seed a throwaway Facet library for the browser flows, then (with ``serve``) start the viewer on it.

No models and no scan: the photos are synthetic solid-colour images and their rows are written
straight into a database built by ``db.schema.init_database``, the same schema the scanner uses.
Each flow owns its own folder, and a flow that changes its folder resets it first (``reset``), so
flows never depend on one another's changes, nor on an earlier run of themselves.

    python client/e2e/seed_library.py serve --port 5099 --edition-password <pw>   # seed .work, run the viewer
    python client/e2e/seed_library.py reset <folder>                   # restore one folder as seeded
    python client/e2e/seed_library.py reimport <edit_path> <#rrggbb>   # see reimport() below
"""

import argparse
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORK = os.path.join(REPO, 'client', 'e2e', '.work')
LIBRARY = os.path.join(WORK, 'library')
DB_PATH = os.path.join(WORK, 'facet_e2e.db')
CONFIG_PATH = os.path.join(WORK, 'scoring_config.json')
# send2trash honours XDG_DATA_HOME: a deleted test photo lands here, not in the user's own Trash.
XDG_DATA_HOME = os.path.join(WORK, 'xdg-data')

sys.path.insert(0, REPO)

# folder -> [(file name, colour, aggregate, burst lead, AI edit of)]. One burst per folder.
PHOTOS = {
    # 01 strip + 02 hide bursts (read-only): the edit outscores both frames and leads.
    'burst': [('IMG_0001.jpg', '#3c6e47', 5.0, 0, None),
              ('IMG_0002.jpg', '#6e5a3c', 4.0, 0, None),
              ('IMG_0001_agy_1.jpg', '#2f9e44', 6.0, 1, 'IMG_0001.jpg')],
    # 03 reused name: the red edit is deleted and a blue one imported under the same name.
    # The red edit leads, so its card is in the gallery under Hide bursts.
    'reuse': [('IMG_0100.jpg', '#888888', 5.0, 0, None),
              ('IMG_0100_agy_1.jpg', '#e03131', 6.0, 1, 'IMG_0100.jpg')],
    # 04 lead delete: the edit leads; deleting it must hand the lead to IMG_0200.
    'lead': [('IMG_0200.jpg', '#1971c2', 5.0, 0, None),
             ('IMG_0201.jpg', '#5f3dc4', 3.0, 0, None),
             ('IMG_0200_agy_1.jpg', '#f08c00', 7.0, 1, 'IMG_0200.jpg')],
}
DATE = {'burst': '2026:01:10 10:00:', 'reuse': '2026:01:11 10:00:', 'lead': '2026:01:12 10:00:'}


def _jpeg(colour, size):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, 'JPEG', quality=90)
    return buf.getvalue()


def _histogram(thumbnail):
    """The scanner's own histogram for the photo page's RGB widget (every scanned row has one)."""
    import cv2
    import numpy as np
    from analyzers.technical import TechnicalAnalyzer
    image = cv2.imdecode(np.frombuffer(thumbnail, np.uint8), cv2.IMREAD_COLOR)
    return TechnicalAnalyzer.get_histogram_data(image)['histogram_bytes']


def _insert_photo(conn, folder, name, colour, aggregate, lead, group, second):
    path = os.path.join(LIBRARY, folder, name)
    with open(path, 'wb') as fh:
        fh.write(_jpeg(colour, (1200, 800)))
    thumbnail = _jpeg(colour, (640, 427))
    conn.execute(
        'INSERT OR REPLACE INTO photos (path, filename, thumbnail, histogram_data, image_width, image_height, '
        'aggregate, aesthetic, category, date_taken, burst_group_id, is_burst_lead, phash, scanned_at) '
        "VALUES (?, ?, ?, ?, 1200, 800, ?, ?, 'default', ?, ?, ?, ?, datetime('now'))",
        (path, name, thumbnail, _histogram(thumbnail), aggregate, aggregate, DATE[folder] + f'{second:02d}',
         group, lead, f'{group:016x}'))
    return path


def _seed_folder(conn, folder):
    group = list(PHOTOS).index(folder) + 1
    photos = PHOTOS[folder]
    os.makedirs(os.path.join(LIBRARY, folder))
    for second, (name, colour, aggregate, lead, _) in enumerate(photos):
        _insert_photo(conn, folder, name, colour, aggregate, lead, group, second)
    for revision, (name, _, _, _, source) in enumerate((p for p in photos if p[4]), start=1):
        conn.execute('INSERT INTO photo_ai_edits (edit_path, source_path, tool, note, revision, captioned) '
                     "VALUES (?, ?, 'antigravity-gemini', 'e2e edit', ?, 1)",
                     (os.path.join(LIBRARY, folder, name), os.path.join(LIBRARY, folder, source), revision))


def seed(edition_password):
    from db.schema import init_database
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(LIBRARY)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
        json.dump({'viewer': {'edition_password': edition_password, 'scan_directories': [LIBRARY],
                              'cull': {'allow_trash': True}}}, fh, indent=2)
    init_database(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    for folder in PHOTOS:
        _seed_folder(conn, folder)
    conn.commit()
    conn.close()


def reset(folder):
    """Put one folder back as seed() wrote it: its files, its rows and its AI edit links."""
    conn = sqlite3.connect(DB_PATH)
    prefix = os.path.join(LIBRARY, folder, '')
    conn.execute('DELETE FROM photos WHERE substr(path, 1, ?) = ?', (len(prefix), prefix))
    conn.execute('DELETE FROM photo_ai_edits WHERE substr(edit_path, 1, ?) = ?', (len(prefix), prefix))
    shutil.rmtree(prefix, ignore_errors=True)
    _seed_folder(conn, folder)
    conn.commit()
    conn.close()


def reimport(edit_path, colour):
    """Delete an edit and bring a new one in under the same name, as import + scan would.

    The new row is written the way the scanner writes it (no preview_revision), and then the
    post-scan step runs, so the flow exercises the real apply_ai_edit_captions."""
    from db.ai_edits import apply_ai_edit_captions
    conn = sqlite3.connect(DB_PATH)
    source, revision = conn.execute('SELECT source_path, revision FROM photo_ai_edits WHERE edit_path = ?',
                                    (edit_path,)).fetchone()
    group, aggregate, lead = conn.execute('SELECT burst_group_id, aggregate, is_burst_lead FROM photos WHERE path = ?',
                                          (edit_path,)).fetchone()
    conn.execute('DELETE FROM photos WHERE path = ?', (edit_path,))   # the trigger drops the link row
    folder = os.path.basename(os.path.dirname(edit_path))
    # Same score and lead as before: only the picture changes, as with a real second edit.
    _insert_photo(conn, folder, os.path.basename(edit_path), colour, aggregate, lead, group, 30)
    conn.execute('INSERT INTO photo_ai_edits (edit_path, source_path, tool, note, revision) '
                 "VALUES (?, ?, 'antigravity-gemini', 'e2e edit, again', ?)", (edit_path, source, revision))
    apply_ai_edit_captions(conn)
    conn.commit()
    conn.close()


def serve(port, edition_password):
    seed(edition_password)
    env = {**os.environ, 'FACET_CONFIG': CONFIG_PATH, 'DB_PATH': DB_PATH, 'PYTHONIOENCODING': 'utf-8',
           'FACET_BUILD': 'e2e', 'XDG_DATA_HOME': XDG_DATA_HOME}
    sys.exit(subprocess.call([sys.executable, 'viewer.py', '--production', '--port', str(port),
                              '--host', '127.0.0.1'], cwd=REPO, env=env))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    sd = sub.add_parser('seed')
    sd.add_argument('--edition-password', required=True)
    s = sub.add_parser('serve')
    s.add_argument('--port', type=int, default=5099)
    s.add_argument('--edition-password', required=True)
    rs = sub.add_parser('reset')
    rs.add_argument('folder', choices=list(PHOTOS))
    r = sub.add_parser('reimport')
    r.add_argument('edit_path')
    r.add_argument('colour')
    args = parser.parse_args()
    os.chdir(REPO)
    if args.cmd == 'seed':
        seed(args.edition_password)
    elif args.cmd == 'serve':
        serve(args.port, args.edition_password)
    elif args.cmd == 'reset':
        reset(args.folder)
    else:
        reimport(args.edit_path, args.colour)
