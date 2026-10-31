"""AI edits: import a file an AI tool made beside its original, linked and scanned."""

import os
import sqlite3

import pytest
from PIL import Image

from api.routers import ai_edits as ai_edits_router
from db.ai_edits import apply_ai_edit_captions, edit_file_name, next_revision
from tests.conftest import _TEST_DB_FILE


def _jpeg(path, colour=(200, 40, 40)):
    Image.new('RGB', (16, 12), colour).save(path, 'JPEG')
    return str(path)


@pytest.fixture()
def library(tmp_path, seed_photos_prefix, monkeypatch):
    """One scanned photo in a real folder, an edit waiting elsewhere, and a recorded scan call."""
    folder = tmp_path / 'library'
    folder.mkdir()
    original = _jpeg(folder / 'IMG_1.JPG')
    prefix = str(folder) + os.sep
    seed_photos_prefix(prefix, [{'path': original, 'filename': 'IMG_1.JPG', 'aggregate': 6.0,
                                 'category': 'default', 'date_taken': '2026:02:01 10:00:00'}])
    work = tmp_path / 'agy'
    work.mkdir()
    scans = []
    monkeypatch.setattr(ai_edits_router, 'start_file_scan', lambda user, paths: scans.append(paths))
    monkeypatch.setattr(ai_edits_router, 'tool_suffixes', lambda: {'antigravity-gemini': 'agy'})
    yield {'folder': folder, 'original': original, 'work': work, 'scans': scans, 'prefix': prefix}
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('DELETE FROM photo_ai_edits WHERE edit_path LIKE ?', (prefix + '%',))


def _import(client, lib, source, mode='copy', tool='antigravity-gemini'):
    return client.post('/api/photo/ai_edits/import', json={
        'original_path': lib['original'], 'source_file': source, 'mode': mode, 'tool': tool,
        'model': 'gemini-2.5-flash-image', 'note': 'brighten faces'})


def test_copy_places_the_edit_beside_the_original_and_scans_it(edition_client, library):
    source = _jpeg(library['work'] / 'out.jpg', (10, 200, 10))
    r = _import(edition_client, library, source)
    assert r.status_code == 200, r.text
    body = r.json()
    target = str(library['folder'] / 'IMG_1_agy_1.JPG')
    assert body == {'edit_path': target, 'revision': 1, 'mode': 'copy', 'source_removed': False,
                    'scan': {'started': True, 'detail': None}}
    assert os.path.exists(source) and open(target, 'rb').read() == open(source, 'rb').read()
    assert library['scans'] == [[target]]
    assert not [n for n in os.listdir(library['folder']) if n.endswith('.importing')]
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        row = conn.execute('SELECT source_path, tool, model, note, revision FROM photo_ai_edits WHERE edit_path = ?',
                           (target,)).fetchone()
    assert row == (library['original'], 'antigravity-gemini', 'gemini-2.5-flash-image', 'brighten faces', 1)


def test_move_deletes_the_source_and_the_next_import_takes_the_next_revision(edition_client, library):
    first = _jpeg(library['work'] / 'a.jpg')
    assert _import(edition_client, library, first, mode='move').json()['source_removed'] is True
    assert not os.path.exists(first)
    Image.new('RGB', (8, 8)).save(library['work'] / 'b.png', 'PNG')
    body = _import(edition_client, library, str(library['work'] / 'b.png')).json()
    assert body['revision'] == 2
    assert body['edit_path'] == str(library['folder'] / 'IMG_1_agy_2.png')


def test_a_file_placed_by_hand_holds_its_number_and_is_never_overwritten(edition_client, library):
    by_hand = _jpeg(library['folder'] / 'IMG_1_agy_1.JPG', (1, 2, 3))
    before = open(by_hand, 'rb').read()
    body = _import(edition_client, library, _jpeg(library['work'] / 'c.jpg')).json()
    assert body['revision'] == 2
    assert open(by_hand, 'rb').read() == before


@pytest.mark.parametrize('case,status', [
    ('unknown_tool', 422), ('missing', 422), ('relative', 422), ('not_an_image', 422), ('raw', 422),
    ('library_photo', 409),
])
def test_refuses(edition_client, library, case, status):
    source = _jpeg(library['work'] / 'ok.jpg')
    tool = 'antigravity-gemini'
    if case == 'unknown_tool':
        tool = 'midjourney'
    elif case == 'missing':
        source = str(library['work'] / 'nope.jpg')
    elif case == 'relative':
        source = 'ok.jpg'
    elif case == 'not_an_image':
        source = str(library['work'] / 'fake.jpg')
        open(source, 'w').write('not a jpeg')
    elif case == 'raw':
        source = str(library['work'] / 'edit.dng')
        open(source, 'wb').write(b'\0' * 64)
    elif case == 'library_photo':
        source = library['original']
    r = _import(edition_client, library, source, tool=tool)
    assert r.status_code == status, r.text
    assert library['scans'] == []
    assert sorted(os.listdir(library['folder'])) == ['IMG_1.JPG']


def test_unknown_original_is_404(edition_client, library):
    r = edition_client.post('/api/photo/ai_edits/import', json={
        'original_path': library['prefix'] + 'nope.jpg', 'source_file': _jpeg(library['work'] / 'x.jpg'),
        'mode': 'copy', 'tool': 'antigravity-gemini'})
    assert r.status_code == 404


def test_mode_is_required(edition_client, library):
    r = edition_client.post('/api/photo/ai_edits/import', json={
        'original_path': library['original'], 'source_file': _jpeg(library['work'] / 'x.jpg'),
        'tool': 'antigravity-gemini'})
    assert r.status_code == 422


def test_needs_edition(regular_client, library):
    assert _import(regular_client, library, _jpeg(library['work'] / 'x.jpg')).status_code in (401, 403)
    assert library['scans'] == []


def test_the_link_reads_from_both_sides_once_the_edit_is_scanned(edition_client, library, seed_photos_prefix):
    target = _import(edition_client, library, _jpeg(library['work'] / 'd.jpg')).json()['edit_path']
    # Before the scan lands the edit is not a photo yet: the original lists nothing.
    assert edition_client.get('/api/photo/ai_edits', params={'path': library['original']}).json()['edits'] == []
    seed_photos_prefix(str(library['folder']) + os.sep + 'IMG_1_agy', [{
        'path': target, 'filename': os.path.basename(target), 'aggregate': 5.0,
        'category': 'default', 'date_taken': '2026:02:01 10:00:00'}])
    of_original = edition_client.get('/api/photo/ai_edits', params={'path': library['original']}).json()
    assert of_original['edit_of'] is None
    assert [e['edit_path'] for e in of_original['edits']] == [target]
    of_edit = edition_client.get('/api/photo/ai_edits', params={'path': target}).json()
    assert of_edit['edit_of']['source_path'] == library['original'] and of_edit['edits'] == []
    assert edition_client.get('/api/photo', params={'path': target}).json()['ai_edit_of'] == library['original']
    assert 'ai_edit_of' not in edition_client.get('/api/photo', params={'path': library['original']}).json()


def test_file_names_and_revisions():
    assert edit_file_name(r'\\nas\p\IMG_1.JPG', 'agy', 1, '.jpg') == 'IMG_1_agy_1.JPG'
    assert edit_file_name('/p/IMG_1.JPG', 'agy', 3, '.png') == 'IMG_1_agy_3.png'
    names = ['IMG_1.JPG', 'IMG_1_agy_1.JPG', 'img_1_AGY_4.png', 'IMG_1_agy_x.jpg', 'IMG_10_agy_9.jpg']
    assert next_revision(r'\\nas\p\IMG_1.JPG', 'agy', names, []) == 5
    assert next_revision('/p/IMG_1.JPG', 'agy', [], [2, 7]) == 8
    assert next_revision('/p/IMG_1.JPG', 'agy', [], []) == 1


def test_the_edit_is_captioned_with_the_original_caption_and_the_note(edition_client, library, seed_photos_prefix):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET caption = ? WHERE path = ?', ('Two kids on a beach.', library['original']))
    target = _import(edition_client, library, _jpeg(library['work'] / 'cap.jpg')).json()['edit_path']
    seed_photos_prefix(str(library['folder']) + os.sep + 'IMG_1_agy', [{
        'path': target, 'filename': os.path.basename(target), 'aggregate': 5.0,
        'category': 'default', 'date_taken': '2026:02:01 10:00:00'}])
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        assert apply_ai_edit_captions(conn) == 1
        caption = conn.execute('SELECT caption FROM photos WHERE path = ?', (target,)).fetchone()[0]
        # Applied once: the next scan's pass leaves the user's later caption alone.
        conn.execute('UPDATE photos SET caption = ? WHERE path = ?', ('mine', target))
        assert apply_ai_edit_captions(conn) == 0
        kept = conn.execute('SELECT caption FROM photos WHERE path = ?', (target,)).fetchone()[0]
    assert caption == 'Two kids on a beach. AI: brighten faces'
    assert kept == 'mine'


def test_an_original_without_a_caption_gives_just_the_ai_line(edition_client, library, seed_photos_prefix):
    target = _import(edition_client, library, _jpeg(library['work'] / 'nocap.jpg')).json()['edit_path']
    seed_photos_prefix(str(library['folder']) + os.sep + 'IMG_1_agy', [{
        'path': target, 'filename': os.path.basename(target), 'aggregate': 5.0,
        'category': 'default', 'date_taken': '2026:02:01 10:00:00'}])
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        apply_ai_edit_captions(conn)
        caption = conn.execute('SELECT caption FROM photos WHERE path = ?', (target,)).fetchone()[0]
    assert caption == 'AI: brighten faces'


@pytest.mark.parametrize('states,expected', [
    ([(True, False), (True, True), (False, True)], True),   # the scan finishes with the photo
    ([(True, False), (False, False)], False),               # the scan ends without it (failed)
    ([(True, False)] * 50, False),                          # still running at the deadline
])
def test_the_import_waits_for_its_scan_before_saying_ready(monkeypatch, states, expected):
    import asyncio

    from api.agent import tools_ai_edits

    calls = iter(states)
    monkeypatch.setattr(tools_ai_edits, '_scan_state_for', lambda path: next(calls))
    monkeypatch.setattr(tools_ai_edits, 'READY_POLL_S', 0)
    monkeypatch.setattr(tools_ai_edits, 'READY_WAIT_S', 0 if len(states) == 50 else 60)
    assert asyncio.run(tools_ai_edits._wait_until_ready('/p/x_agy_1.jpg')) is expected
