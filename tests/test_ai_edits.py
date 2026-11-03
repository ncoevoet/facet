"""AI edits: import an image an AI tool made beside its original, linked and scanned."""

import base64
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from api.routers import ai_edits as ai_edits_router
from api.routers import scan as scan_router
from db.ai_edits import apply_ai_edit_captions, edit_file_name, join_ai_edits_to_original_sets, next_revision
from tests.conftest import _TEST_DB_FILE


def _jpeg(path, colour=(200, 40, 40)):
    Image.new('RGB', (16, 12), colour).save(path, 'JPEG')
    return str(path)


def _b64(path):
    with open(path, 'rb') as fh:
        return base64.b64encode(fh.read()).decode('ascii')


@pytest.fixture()
def library(tmp_path, seed_photos_prefix, monkeypatch):
    """Two scanned photos in a real folder, a drop folder for edits, and a recorded scan call."""
    folder = tmp_path / 'library'
    folder.mkdir()
    original = _jpeg(folder / 'IMG_1.JPG')
    second = _jpeg(folder / 'IMG_2.JPG', (5, 5, 200))
    prefix = str(folder) + os.sep
    seed_photos_prefix(prefix, [
        {'path': original, 'filename': 'IMG_1.JPG', 'aggregate': 6.0, 'category': 'default',
         'date_taken': '2026:02:01 10:00:00'},
        {'path': second, 'filename': 'IMG_2.JPG', 'aggregate': 6.0, 'category': 'default',
         'date_taken': '2026:02:01 10:00:01'},
    ])
    work = tmp_path / 'agy'
    work.mkdir()
    scans = []
    settings = {'tool_suffixes': {'antigravity-gemini': 'agy'}, 'drop_dir': str(work)}
    monkeypatch.setattr(ai_edits_router, 'start_file_scan', lambda user, paths: scans.append(paths))
    monkeypatch.setattr(ai_edits_router, '_settings', lambda: settings)
    monkeypatch.setattr(ai_edits_router, 'get_all_scan_directories', lambda: [str(folder)])
    yield {'folder': folder, 'original': original, 'second': second, 'work': work, 'scans': scans,
           'prefix': prefix, 'settings': settings}
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('DELETE FROM photo_ai_edits WHERE edit_path LIKE ? OR source_path LIKE ?',
                     (prefix + '%', prefix + '%'))


def _import(client, lib, source=None, tool='antigravity-gemini', image_data=None):
    body = {'original_path': lib['original'], 'tool': tool, 'model': 'gemini-2.5-flash-image',
            'note': 'brighten faces'}
    if source is not None:
        body['source_file'] = source
    if image_data is not None:
        body['image_data'] = image_data
    return client.post('/api/photo/ai_edits/import', json=body)


def _library_files(lib):
    return sorted(os.listdir(lib['folder']))


def test_a_drop_file_is_copied_beside_the_original_and_scanned(edition_client, library):
    source = _jpeg(library['work'] / 'out.jpg', (10, 200, 10))
    r = _import(edition_client, library, 'out.jpg')
    assert r.status_code == 200, r.text
    body = r.json()
    target = str(library['folder'] / 'IMG_1_agy_1.JPG')
    assert body == {'edit_path': target, 'revision': 1, 'scan': {'started': True, 'detail': None}}
    # Facet wrote its own copy and left the assistant's file where it was.
    assert os.path.exists(source) and open(target, 'rb').read() == open(source, 'rb').read()
    assert library['scans'] == [[target]]
    assert not [n for n in os.listdir(library['folder']) if n.endswith('.importing')]
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        row = conn.execute('SELECT source_path, tool, model, note, revision FROM photo_ai_edits WHERE edit_path = ?',
                           (target,)).fetchone()
    assert row == (library['original'], 'antigravity-gemini', 'gemini-2.5-flash-image', 'brighten faces', 1)


def test_image_data_is_written_and_the_extension_follows_the_bytes(edition_client, library):
    png = library['work'] / 'named-like-a.jpg'
    Image.new('RGB', (8, 8), (1, 200, 3)).save(png, 'PNG')
    r = _import(edition_client, library, image_data=_b64(png))
    assert r.status_code == 200, r.text
    target = library['folder'] / 'IMG_1_agy_1.png'
    assert r.json()['edit_path'] == str(target)
    assert target.read_bytes() == png.read_bytes()


def test_the_next_import_takes_the_next_revision(edition_client, library):
    _jpeg(library['work'] / 'a.jpg')
    assert _import(edition_client, library, 'a.jpg').json()['revision'] == 1
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


def test_a_name_taken_after_the_listing_moves_on_instead_of_replacing(edition_client, library, monkeypatch):
    """The listing said revision 1 was free; a file appears there before the import publishes."""
    squatter = library['folder'] / 'IMG_1_agy_1.JPG'
    real_write = ai_edits_router._write_private

    def write_then_squat(folder, data):
        temp = real_write(folder, data)
        _jpeg(squatter, (9, 9, 9))
        return temp

    monkeypatch.setattr(ai_edits_router, '_write_private', write_then_squat)
    body = _import(edition_client, library, _jpeg(library['work'] / 's.jpg')).json()
    assert body['revision'] == 2
    # The squatter is still the squatter's file, not the edit.
    assert Image.open(squatter).getpixel((0, 0))[0] < 20
    assert (library['folder'] / 'IMG_1_agy_2.JPG').exists()


def test_two_imports_at_once_take_two_revisions(edition_client, library, monkeypatch):
    """Both calls list the folder before either publishes, so both start from revision 1."""
    for name, colour in (('p.jpg', (250, 0, 0)), ('q.jpg', (0, 0, 250))):
        _jpeg(library['work'] / name, colour)
    for _round in range(5):
        barrier = threading.Barrier(2, timeout=10)
        real_write = ai_edits_router._write_private

        def write_together(folder, data, real_write=real_write, barrier=barrier):
            temp = real_write(folder, data)
            barrier.wait()
            return temp

        monkeypatch.setattr(ai_edits_router, '_write_private', write_together)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda name: _import(edition_client, library, name), ['p.jpg', 'q.jpg']))
        monkeypatch.setattr(ai_edits_router, '_write_private', real_write)
        assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
        revisions = sorted(r.json()['revision'] for r in results)
        assert revisions[1] == revisions[0] + 1
        for r, name in zip(results, ['p.jpg', 'q.jpg']):
            assert open(r.json()['edit_path'], 'rb').read() == (library['work'] / name).read_bytes()
    assert not [n for n in _library_files(library) if n.endswith('.importing')]
    assert len([n for n in _library_files(library) if '_agy_' in n]) == 10


def test_the_library_photo_attack_is_refused_and_the_photo_is_untouched(edition_client, library):
    """A reviewer deleted a library photo with ``<lib>/./IMG_2.JPG`` and the old ``mode: move``."""
    before = open(library['second'], 'rb').read()
    spelled = str(library['folder']) + os.sep + '.' + os.sep + 'IMG_2.JPG'
    for source in (spelled, library['second'], os.path.join('..', 'library', 'IMG_2.JPG'),
                   str(library['folder']).upper() + os.sep + 'IMG_2.JPG'):
        body = {'original_path': library['original'], 'source_file': source, 'mode': 'move',
                'tool': 'antigravity-gemini'}
        r = edition_client.post('/api/photo/ai_edits/import', json=body)
        assert r.status_code == 422, (source, r.text)
    assert open(library['second'], 'rb').read() == before
    assert _library_files(library) == ['IMG_1.JPG', 'IMG_2.JPG']
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        assert conn.execute('SELECT 1 FROM photos WHERE path = ?', (library['second'],)).fetchone()
    assert library['scans'] == []


def test_a_hardlink_to_a_library_photo_is_refused(edition_client, library):
    link = library['work'] / 'linked.jpg'
    os.link(library['second'], link)
    r = _import(edition_client, library, 'linked.jpg')
    assert r.status_code == 422 and 'more than one link' in r.text
    assert os.path.exists(link) and os.path.exists(library['second'])
    assert _library_files(library) == ['IMG_1.JPG', 'IMG_2.JPG']


def test_a_symlink_out_of_the_drop_folder_is_refused(edition_client, library):
    link = library['work'] / 'sym.jpg'
    try:
        os.symlink(library['second'], link)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks need a privilege on this machine')
    r = _import(edition_client, library, 'sym.jpg')
    assert r.status_code == 422, r.text
    assert os.path.exists(library['second'])


def test_a_drop_folder_inside_a_scanned_folder_is_refused(edition_client, library):
    inner = library['folder'] / 'drop'
    inner.mkdir()
    _jpeg(inner / 'x.jpg')
    library['settings']['drop_dir'] = str(inner)
    r = _import(edition_client, library, 'x.jpg')
    assert r.status_code == 422 and 'scanned folder' in r.text


def test_source_file_needs_a_drop_folder(edition_client, library):
    library['settings']['drop_dir'] = ''
    r = _import(edition_client, library, _jpeg(library['work'] / 'x.jpg'))
    assert r.status_code == 422 and 'drop_dir' in r.text


def test_an_edit_over_the_size_limit_is_refused(edition_client, library, monkeypatch):
    monkeypatch.setattr(ai_edits_router, 'MAX_EDIT_BYTES', 64)
    source = _jpeg(library['work'] / 'big.jpg')
    assert _import(edition_client, library, 'big.jpg').status_code == 413
    assert _import(edition_client, library, image_data=_b64(source)).status_code == 413
    assert _library_files(library) == ['IMG_1.JPG', 'IMG_2.JPG']


@pytest.mark.parametrize('case,status', [
    ('unknown_tool', 422), ('missing', 422), ('outside', 422), ('not_an_image', 422), ('raw', 422),
    ('bad_base64', 422), ('both', 422), ('neither', 422), ('drop_folder_itself', 422),
])
def test_refuses(edition_client, library, case, status):
    source = _jpeg(library['work'] / 'ok.jpg')
    kwargs = {'source': source}
    tool = 'antigravity-gemini'
    if case == 'unknown_tool':
        tool = 'midjourney'
    elif case == 'missing':
        kwargs = {'source': 'nope.jpg'}
    elif case == 'outside':
        kwargs = {'source': _jpeg(library['work'].parent / 'elsewhere.jpg')}
    elif case == 'not_an_image':
        open(library['work'] / 'fake.jpg', 'w').write('not a jpeg')
        kwargs = {'source': 'fake.jpg'}
    elif case == 'raw':
        open(library['work'] / 'edit.dng', 'wb').write(b'\0' * 64)
        kwargs = {'source': 'edit.dng'}
    elif case == 'bad_base64':
        kwargs = {'image_data': 'not base64!'}
    elif case == 'both':
        kwargs = {'source': source, 'image_data': _b64(source)}
    elif case == 'neither':
        kwargs = {}
    elif case == 'drop_folder_itself':
        kwargs = {'source': '.'}
    r = _import(edition_client, library, tool=tool, **kwargs)
    assert r.status_code == status, r.text
    assert library['scans'] == []
    assert _library_files(library) == ['IMG_1.JPG', 'IMG_2.JPG']


def test_the_file_is_taken_back_out_when_its_row_cannot_be_written(edition_client, library):
    """A primary-key clash on the INSERT leaves no unlinked file behind and keeps the source."""
    clash = str(library['folder'] / 'IMG_1_agy_1.JPG')
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('INSERT INTO photo_ai_edits (edit_path, source_path, tool, revision) VALUES (?, ?, ?, ?)',
                     (clash, library['second'], 'antigravity-gemini', 1))
    source = _jpeg(library['work'] / 'r.jpg')
    r = _import(edition_client, library, 'r.jpg')
    assert r.status_code == 500, r.text
    assert _library_files(library) == ['IMG_1.JPG', 'IMG_2.JPG']
    assert os.path.exists(source)
    assert library['scans'] == []


def test_an_edit_link_follows_its_photo_row(library):
    """Once the edit is a photo, deleting or moving that row updates ``edit_path``; unscanned links stay."""
    edit = str(library['folder'] / 'IMG_1_agy_1.JPG')
    pending = str(library['folder'] / 'IMG_1_agy_2.JPG')
    moved = str(library['folder'] / 'IMG_1_agy_1b.JPG')
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.executemany('INSERT INTO photo_ai_edits (edit_path, source_path, tool, revision) VALUES (?, ?, ?, ?)',
                         [(edit, library['original'], 'antigravity-gemini', 1),
                          (pending, library['original'], 'antigravity-gemini', 2)])
        conn.execute('INSERT INTO photos (path, filename) VALUES (?, ?)', (edit, 'IMG_1_agy_1.JPG'))
        conn.execute('UPDATE photos SET path = ? WHERE path = ?', (moved, edit))
        assert [r[0] for r in conn.execute('SELECT edit_path FROM photo_ai_edits WHERE source_path = ? '
                                           'ORDER BY revision', (library['original'],))] == [moved, pending]
        conn.execute('DELETE FROM photos WHERE path = ?', (moved,))
        assert [r[0] for r in conn.execute('SELECT edit_path FROM photo_ai_edits WHERE source_path = ?',
                                           (library['original'],))] == [pending]


def test_unknown_original_is_404(edition_client, library):
    r = edition_client.post('/api/photo/ai_edits/import', json={
        'original_path': library['prefix'] + 'nope.jpg', 'source_file': _jpeg(library['work'] / 'x.jpg'),
        'tool': 'antigravity-gemini'})
    assert r.status_code == 404


def test_needs_edition(regular_client, library):
    assert _import(regular_client, library, _jpeg(library['work'] / 'x.jpg')).status_code in (401, 403)
    assert library['scans'] == []


class _User:
    def __init__(self, superadmin=False, edition=True, trusted=False):
        self.is_superadmin, self.is_edition, self.trusted_local_editing = superadmin, edition, trusted


@pytest.mark.parametrize('multi,user,open_install,refused', [
    (True, _User(superadmin=False), False, 'Superadmin access required'),
    (True, _User(superadmin=True), False, None),
    (False, _User(), True, 'Set viewer.edition_password to enable the scan trigger'),
    (False, _User(), False, None),
])
def test_the_import_scan_follows_the_scan_access_rule(monkeypatch, multi, user, open_install, refused):
    spawned = []
    monkeypatch.setattr(scan_router, 'scan_feature_refusal', lambda u: None)
    monkeypatch.setattr(scan_router, 'is_multi_user_enabled', lambda: multi)
    monkeypatch.setattr(scan_router, '_is_open_install', lambda key: open_install)
    monkeypatch.setattr(scan_router, '_library_job_conflict_detail', lambda: None)
    monkeypatch.setattr(scan_router, '_spawn_scan',
                        lambda targets, reported, flags=(): spawned.append((targets, flags)))
    monkeypatch.setitem(scan_router._scan_state, 'running', False)
    assert scan_router.start_file_scan(user, ['/p/x_agy_1.jpg']) == refused
    # Only the new file, with --ai-edit: no library-wide passes for one imported edit.
    assert spawned == ([] if refused else [(['/p/x_agy_1.jpg'], ('--ai-edit',))])


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



def _scan_edit(library, seed_photos_prefix, target, **row):
    seed_photos_prefix(str(library['folder']) + os.sep + 'IMG_1_agy', [{
        'path': target, 'filename': os.path.basename(target), 'aggregate': 5.0,
        'category': 'default', 'date_taken': '2026:02:01 10:00:00', **row}])


def test_an_edit_joins_its_originals_burst_as_a_non_lead_frame(edition_client, library, seed_photos_prefix):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET burst_group_id = 4242, is_burst_lead = 1, tags = ? WHERE path = ?',
                     ('party,cake', library['original']))
    target = _import(edition_client, library, _jpeg(library['work'] / 'j.jpg')).json()['edit_path']
    _scan_edit(library, seed_photos_prefix, target, is_burst_lead=1)
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        assert join_ai_edits_to_original_sets(conn, [target, '/not/an/edit.jpg']) == 1
        rows = dict(conn.execute('SELECT path, burst_group_id || ":" || is_burst_lead || ":" || COALESCE(tags, "") '
                                 'FROM photos WHERE path IN (?, ?)', (library['original'], target)).fetchall())
    assert rows == {library['original']: '4242:1:party,cake', target: '4242:0:party,cake'}


def test_an_original_on_its_own_starts_a_burst_with_its_edit(edition_client, library, seed_photos_prefix):
    target = _import(edition_client, library, _jpeg(library['work'] / 'k.jpg')).json()['edit_path']
    _scan_edit(library, seed_photos_prefix, target, tags='own')
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET burst_group_id = NULL WHERE path = ?', (library['original'],))
        join_ai_edits_to_original_sets(conn, [target])
        (og, ol), (eg, el, tags) = (
            conn.execute('SELECT burst_group_id, is_burst_lead FROM photos WHERE path = ?', (library['original'],)).fetchone(),
            conn.execute('SELECT burst_group_id, is_burst_lead, tags FROM photos WHERE path = ?', (target,)).fetchone())
    assert og is not None and og == eg and (ol, el) == (1, 0)
    assert tags == 'own'
