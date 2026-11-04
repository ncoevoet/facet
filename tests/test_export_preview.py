"""Read-only export preview foundation; apply/receipts are a separate stage."""

import hashlib
import os
from pathlib import Path
import sqlite3

import pytest
from fastapi import HTTPException

from api import config
from api.export_preview import _digest, build_export_snapshot, confirm_export_snapshot, verify_export_preview
from api.models.export_preview import ExportPreviewRequest
from db import DEFAULT_DB_PATH
from tests.conftest import symlink_or_skip


@pytest.fixture
def library(tmp_path, seed_photos_prefix, monkeypatch):
    folder = tmp_path / 'photos'
    folder.mkdir()
    paths = [folder / 'alpha.jpg', folder / 'beta.jpg']
    for path in paths:
        path.write_bytes(path.name.encode('utf-8'))
    seed_photos_prefix(str(folder) + '/', [
        {'path': str(path), 'filename': path.name, 'star_rating': 4, 'tags': 'coast', 'caption': 'Preserved caption'}
        for path in paths
    ])
    target = tmp_path / 'delivery'
    target.mkdir()
    monkeypatch.setitem(config.VIEWER_CONFIG, 'export', {'allowed_target_dirs': [str(target)]})
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    return paths, target


def bytes_in(folder):
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob('*') if path.is_file()}


def test_current_packet_check_skips_metadata_for_unrelated_image_names(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from api import export_preview

    source = tmp_path / 'selected.jpg'
    source.write_bytes(b'original')
    for index in range(1000):
        (tmp_path / f'unrelated-{index}.jpg').write_bytes(b'other')
    original_scan = os.scandir
    metadata_reads = []

    class CountedEntry:
        def __init__(self, entry):
            self.entry = entry
            self.path, self.name = entry.path, entry.name

        def is_file(self, **kwargs):
            metadata_reads.append(self.name)
            return self.entry.is_file(**kwargs)

        def is_symlink(self):
            metadata_reads.append(self.name)
            return self.entry.is_symlink()

    @contextmanager
    def counted_scan(path):
        with original_scan(path) as entries:
            yield (CountedEntry(entry) for entry in entries)

    monkeypatch.setattr(export_preview.os, 'scandir', counted_scan)
    export_preview._current_packet_ownership(str(source), [str(source) + '.xmp'])
    assert metadata_reads == []
    # The cached preview index still inspects the whole directory once; only
    # the repeated per-file execution check uses the bounded metadata probe.
    export_preview._packet_ownership(str(source), [str(source) + '.xmp'], {}, [20000])
    assert len(metadata_reads) == 1001


@pytest.mark.parametrize(('source_name', 'other_name', 'packet_tail'), [
    ('shot.jpg', 'shot.jpg.CR2', '.xmp'),
    ('shot.jpg', 'SHOT.JPG.CR2', '.xmp'),
    ('caf\u00e9.jpg', 'cafe\u0301.jpg.CR2', '.xmp'),
    ('shot.jpg', 'shot.jpg.facet.NEF', '.facet.xmp'),
    ('shot.jpg', 'shot.CR2', 'basename'),
])
def test_current_packet_check_preserves_portable_collision_policy(tmp_path, source_name, other_name, packet_tail):
    from api import export_preview

    source = tmp_path / source_name
    source.write_bytes(b'original')
    (tmp_path / other_name).write_bytes(b'competing owner')
    packet = str(source.with_suffix('.xmp')) if packet_tail == 'basename' else str(source) + packet_tail
    for check in (lambda: export_preview._packet_ownership(str(source), [packet], {}, [20000]),
                  lambda: export_preview._current_packet_ownership(str(source), [packet])):
        with pytest.raises(HTTPException) as failure:
            check()
        assert failure.value.status_code == 409
    assert source.read_bytes() == b'original'
    assert not Path(packet).exists()


def test_current_packet_check_ignores_a_matching_directory_but_refuses_a_link(tmp_path):
    from api.export_preview import _current_packet_ownership

    source = tmp_path / 'shot.jpg'
    source.write_bytes(b'original')
    competitor = tmp_path / 'shot.jpg.CR2'
    competitor.mkdir()
    _current_packet_ownership(str(source), [str(source) + '.xmp'])
    competitor.rmdir()
    symlink_or_skip(competitor, source)
    with pytest.raises(HTTPException) as failure:
        _current_packet_ownership(str(source), [str(source) + '.xmp'])
    assert failure.value.status_code == 409


def test_current_packet_check_keeps_the_directory_entry_budget(tmp_path, monkeypatch):
    from api import export_preview

    source = tmp_path / 'shot.jpg'
    source.write_bytes(b'original')
    for index in range(3):
        (tmp_path / str(index)).write_bytes(b'unrelated')
    monkeypatch.setattr(export_preview, '_MAX_DIRECTORY_ENTRIES', 3)
    with pytest.raises(HTTPException) as failure:
        export_preview._current_packet_ownership(str(source), [str(source) + '.xmp'])
    assert failure.value.status_code == 412


def preview(client, **body):
    response = client.post('/api/export/preview', json=body)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def test_sidecar_preview_exact_exclusions_values_and_no_target_writes(edition_client, library):
    paths, target = library
    before = bytes_in(target.parent)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        rows_before = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    body = preview(edition_client, paths=list(map(str, paths)), exclude=[str(paths[1])])
    assert body['selected_paths'] == [str(paths[0])]
    assert body['ready'] == 1 and body['missing'] == 0 and body['writer'] == 'xml'
    item = body['items'][0]
    assert item['target_name'] == 'alpha.jpg.xmp' and item['target_exists'] is False
    assert item['metadata']['star_rating'] == 4 and item['metadata']['caption'] == 'Preserved caption'
    assert bytes_in(target.parent) == before
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == rows_before


def test_copy_preview_resolves_collisions_without_creating_target(edition_client, library):
    paths, target = library
    (target / paths[0].name).write_bytes(b'existing delivery')
    before = bytes_in(target.parent)
    body = preview(edition_client, paths=[str(paths[0])], mode='copy', target_dir=str(target))
    assert body['items'][0]['target_name'] == 'alpha_1.jpg'
    assert body['items'][0]['metadata'] is None
    another = target / 'not-created'
    preview(edition_client, paths=[str(paths[0])], mode='symlink', target_dir=str(another))
    assert not another.exists()
    assert bytes_in(target.parent) == before


def test_companion_bundle_collision_keeps_matching_names_together(edition_client, library):
    paths, target = library
    raw = paths[0].with_suffix('.CR2')
    raw.write_bytes(b'RAW fixture')
    sidecar = Path(str(paths[0]) + '.xmp')
    sidecar.write_text('<xmp/>', encoding='utf-8')
    (target / 'alpha.jpg').write_bytes(b'prior file')
    before = bytes_in(target.parent)
    body = preview(edition_client, paths=[str(paths[0])], mode='copy', target_dir=str(target), include_companions=True)
    assert {item['target_name'] for item in body['items']} == {'alpha_1.jpg', 'alpha_1.CR2', 'alpha_1.jpg.xmp'}
    assert sum(item['companion'] for item in body['items']) == 2
    assert bytes_in(target.parent) == before


def test_ambiguous_raw_jpeg_basename_xmp_refuses_without_writes(edition_client, library):
    paths, target = library
    paths[0].with_suffix('.CR2').write_bytes(b'RAW fixture')
    paths[0].with_suffix('.xmp').write_text('<xmp/>', encoding='utf-8')
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={
        'paths': [str(paths[0])], 'mode': 'copy', 'target_dir': str(target), 'include_companions': True,
    })
    assert response.status_code == 409 and 'ambiguous' in response.text
    assert bytes_in(target.parent) == before


def test_preview_token_is_owner_options_expiry_bound_and_not_an_auth_token(edition_client, library, monkeypatch):
    from api.auth import decode_access_token
    paths, _ = library
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    claims = verify_export_preview(body['preview_token'], request, 'test')
    assert claims['receipt'] == body['receipt_id']
    assert decode_access_token(body['preview_token']) is None
    for other, user in [(request, 'other'), (request.model_copy(update={'overwrite': True}), 'test')]:
        with pytest.raises(HTTPException) as error:
            verify_export_preview(body['preview_token'], other, user)
        assert error.value.status_code == 409
    monkeypatch.setattr('api.export_preview.time.time', lambda: body['expires_at'] + 1)
    with pytest.raises(HTTPException):
        verify_export_preview(body['preview_token'], request, 'test')


@pytest.mark.parametrize('change', ['metadata', 'file'])
def test_effective_metadata_and_file_changes_change_the_confirmation_snapshot(edition_client, library, change):
    paths, _ = library
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    claims = verify_export_preview(body['preview_token'], request, 'test')
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        assert _digest(build_export_snapshot(conn, request, 'test')) == claims['snapshot']
        # Each case starts fresh so a metadata change cannot mask a broken file guard.
        if change == 'metadata':
            conn.execute('UPDATE photos SET star_rating=1 WHERE path=?', (str(paths[0]),))
            conn.commit()
        else:
            paths[0].write_bytes(b'changed source')
        assert _digest(build_export_snapshot(conn, request, 'test')) != claims['snapshot']


@pytest.mark.parametrize('credential', ['actor', 'password', 'edition_password'])
def test_credential_rotation_refuses_confirmation_without_writing(edition_client, library, monkeypatch, credential):
    paths, target = library
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    before = bytes_in(target.parent)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        if credential == 'actor':
            users = config._FULL_CONFIG.get('users', {})
            monkeypatch.setitem(config._FULL_CONFIG, 'users', {
                **users, 'test': {**users.get('test', {}), 'password': 'rotated actor credential'}})
        else:
            monkeypatch.setitem(config.VIEWER_CONFIG, credential, 'rotated viewer credential')
        with pytest.raises(HTTPException) as error:
            confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        assert error.value.status_code == 409
    assert bytes_in(target.parent) == before


def test_explicit_hierarchy_is_in_preview_and_structure_changes_invalidate_confirmation(edition_client, library):
    from db.keyword_hierarchy import assign_path, change_node
    paths, target = library
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        leaf, _ = assign_path(conn, str(paths[0]), ['Places', 'City, Coast'])
        assign_path(conn, str(paths[1]), ['Other', 'Cat'])
    before = bytes_in(target.parent)
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    metadata = body['items'][0]['metadata']
    assert metadata['hierarchy_paths'] == ['Places|City, Coast']
    assert 'Places|City, Coast' in metadata['keywords']
    assert 'Other|Cat' not in metadata['keywords']
    assert bytes_in(target.parent) == before
    claims = verify_export_preview(body['preview_token'], request, 'test')
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        assert _digest(build_export_snapshot(conn, request, 'test')) == claims['snapshot']
        change_node(conn, leaf, writable_paths={str(paths[0])}, name='New name')
        conn.commit()
        assert _digest(build_export_snapshot(conn, request, 'test')) != claims['snapshot']
    assert bytes_in(target.parent) == before


def test_byte_copy_preview_does_not_materialize_unwritten_hierarchy_metadata(edition_client, library):
    from db.keyword_hierarchy import assign_path
    paths, target = library
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        node, _ = assign_path(conn, str(paths[0]), ['Places', 'Coast'])
        original_key = conn.execute('SELECT name_key FROM keyword_nodes WHERE id=?', (node,)).fetchone()[0]
        conn.execute("UPDATE keyword_nodes SET name_key='invalid' WHERE id=?", (node,))
    try:
        before = bytes_in(target.parent)
        refused = edition_client.post('/api/export/preview', json={'paths': [str(paths[0])]})
        assert refused.status_code == 409
        copied = preview(edition_client, paths=[str(paths[0])], mode='copy', target_dir=str(target))
        assert copied['ready'] == 1 and copied['items'][0]['metadata'] is None
        assert bytes_in(target.parent) == before
    finally:
        # Photo cleanup leaves vocabulary in the shared session database.
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('UPDATE keyword_nodes SET name_key=? WHERE id=?', (original_key, node))


def test_unavailable_selection_refuses_before_face_or_file_probes(edition_client, library, monkeypatch):
    paths, _ = library
    monkeypatch.setattr('api.routers.export._fetch_regions_map', lambda *args: pytest.fail('inspected unauthorized regions'))
    monkeypatch.setattr('api.export_preview.resolve_photo_disk_path', lambda *args: pytest.fail('inspected unauthorized file'))
    response = edition_client.post('/api/export/preview', json={'paths': [str(paths[0]), '/not-indexed-private.jpg']})
    assert response.status_code == 409


def test_locked_user_cannot_preview_writes(regular_client, library):
    paths, _ = library
    assert regular_client.post('/api/export/preview', json={'paths': [str(paths[0])]}).status_code == 403


def test_empty_explicit_scope_never_expands_to_library(edition_client, library):
    assert edition_client.post('/api/export/preview', json={'paths': []}).status_code == 422


def test_physical_hardlink_aliases_refuse_before_any_targets(edition_client, library):
    paths, target = library
    paths[1].unlink()
    os.link(paths[0], paths[1])
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={'paths': list(map(str, paths))})
    assert response.status_code == 409
    assert bytes_in(target.parent) == before


def test_source_leaf_symlink_cannot_hide_behind_canonical_resolution(edition_client, library):
    paths, target = library
    paths[1].unlink()
    symlink_or_skip(paths[1], paths[0])
    response = edition_client.post('/api/export/preview', json={'paths': [str(paths[1])]})
    assert response.status_code == 409
    assert not list(target.iterdir())


def test_full_packet_also_claimed_by_double_extension_image_refuses(edition_client, library):
    paths, target = library
    Path(str(paths[0]) + '.xmp').write_text('<xmp/>', encoding='utf-8')
    Path(str(paths[0]) + '.CR2').write_bytes(b'other photo with overlapping basename policy')
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={
        'paths': [str(paths[0])], 'mode': 'copy', 'target_dir': str(target), 'include_companions': True,
    })
    assert response.status_code == 409 and 'ambiguous' in response.text
    assert bytes_in(target.parent) == before


@pytest.mark.parametrize('bad_target', ['directory', 'invalid_xml'])
def test_unwritable_packet_or_unrepresentable_metadata_never_marked_ready(edition_client, library, bad_target):
    paths, target = library
    if bad_target == 'directory':
        Path(str(paths[0]) + '.xmp').mkdir()
    else:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('UPDATE photos SET caption=? WHERE path=?', ('invalid\x00caption', str(paths[0])))
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={'paths': [str(paths[0])], 'overwrite': True})
    assert response.status_code == 409
    assert bytes_in(target.parent) == before


@pytest.mark.parametrize('changed', ['rating', 'source', 'sidecar', 'destination'])
def test_confirm_guard_accepts_unchanged_and_refuses_each_changed_precondition(edition_client, library, changed):
    paths, target = library
    request = ExportPreviewRequest(paths=[str(paths[0])], mode='copy', target_dir=str(target)) if changed == 'destination' else ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        snapshot, receipt = confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        assert receipt == body['receipt_id'] and snapshot['paths'] == [str(paths[0])]
    if changed == 'rating':
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('UPDATE photos SET star_rating=1 WHERE path=?', (str(paths[0]),))
    elif changed == 'source':
        paths[0].write_bytes(b'new source bytes')
    elif changed == 'sidecar':
        Path(str(paths[0]) + '.xmp').write_text('<xmp/>', encoding='utf-8')
    else:
        (target / paths[0].name).write_bytes(b'new destination occupant')
    after_intended_change = bytes_in(target.parent)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(HTTPException) as error:
            confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        assert error.value.status_code == 409
    assert bytes_in(target.parent) == after_intended_change


@pytest.mark.parametrize('alias', ['companion', 'metadata'])
def test_companion_or_metadata_hardlink_cannot_alias_an_original(edition_client, library, alias):
    paths, target = library
    if alias == 'companion':
        os.link(paths[0], paths[0].with_suffix('.CR2'))
        options = {'mode': 'copy', 'target_dir': str(target), 'include_companions': True}
    else:
        os.link(paths[0], Path(str(paths[0]) + '.xmp'))
        options = {'overwrite': True}
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={'paths': [str(paths[0])], **options})
    assert response.status_code == 409
    assert bytes_in(target.parent) == before


def test_case_distinct_images_cannot_claim_one_case_folded_packet_family(edition_client, library):
    paths, target = library
    other = paths[0].with_name('ALPHA.jpg')
    try:
        with other.open('xb') as handle:
            handle.write(b'case-distinct photo')
    except FileExistsError:
        pytest.skip('Filesystem does not allow distinct case variants')
    before = bytes_in(target.parent)
    response = edition_client.post('/api/export/preview', json={'paths': [str(paths[0])]})
    assert response.status_code == 409 and 'ambiguous' in response.text
    assert bytes_in(target.parent) == before


def test_unicode_equivalent_companion_name_keeps_its_entire_suffix():
    from api.export_preview import _filename_tail
    assert _filename_tail('cafe\u0301.CR2', 'caf\u00e9') == '.CR2'
    assert _filename_tail('STRASSE.jpg.xmp', 'stra\u00dfe') == '.jpg.xmp'


def test_receipt_origin_change_alone_invalidates_confirmation(edition_client, library):
    paths, _ = library
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(paths[0]),))
        conn.execute('UPDATE photos SET star_rating=4 WHERE path=?', (str(paths[0]),))
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    sources = body['items'][0]['metadata']['provenance']['review']
    assert next(row for row in sources if row['field'] == 'star_rating')['source'] == 'local'
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE photo_metadata_edits SET source='xmp',source_at='2026-01-01' "
                     "WHERE photo_path=? AND user_id='' AND field='star_rating'", (str(paths[0]),))
        conn.commit()
        with pytest.raises(HTTPException) as error:
            confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        assert error.value.status_code == 409


def test_missing_only_preview_is_visible_but_cannot_confirm_an_empty_job(edition_client, library):
    paths, _ = library
    paths[0].unlink()
    request = ExportPreviewRequest(paths=[str(paths[0])])
    body = preview(edition_client, **request.model_dump())
    assert body['ready'] == 0 and body['missing'] == 1
    assert body['items'][0]['state'] == 'missing'
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(HTTPException) as error:
            confirm_export_snapshot(conn, request, body['preview_token'], 'test')
        assert error.value.status_code == 422
