"""Canonical face editing respects the viewer's mapped filesystem boundary."""
from uuid import uuid4

from PIL import Image

from api import config
from api.database import get_db
from tests.conftest import symlink_or_skip


def test_registered_symlink_cannot_escape_allowed_roots(edition_client, tmp_path, monkeypatch, seed_photos_prefix):
    allowed = tmp_path / 'allowed'
    allowed.mkdir()
    hidden = tmp_path / 'hidden.jpg'
    Image.new('RGB', (40, 40), 'green').save(hidden)
    inside = allowed / 'inside.jpg'
    Image.new('RGB', (40, 40), 'red').save(inside)
    linked = allowed / 'link.jpg'
    symlink_or_skip(linked, inside)
    path = str(linked)
    seed_photos_prefix(str(allowed), [{'path': path, 'filename': 'link.jpg'}])
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': [str(allowed)]}}})
    safe_frame = edition_client.get('/api/photo/manual-face-frame', params={'path': path})
    assert safe_frame.status_code == 200
    linked.unlink()
    symlink_or_skip(linked, hidden)
    assert edition_client.get('/image', params={'path': path}).status_code == 404
    assert edition_client.get('/api/photo/manual-face-frame', params={'path': path}).status_code == 404
    body = {'path': path, 'frame_token': safe_frame.json()['frame_token'], 'bbox': [0.1, 0.1, 0.9, 0.9],
            'new_person_name': 'Escaping Person', 'client_id': str(uuid4())}
    assert edition_client.post('/api/photo/manual-faces', json=body).status_code == 404
    with get_db() as conn:
        assert conn.execute('SELECT 1 FROM faces WHERE photo_path=?', (path,)).fetchone() is None


def test_mapped_db_path_uses_contained_pixels_and_retains_logical_identity(edition_client, tmp_path, monkeypatch, seed_photos_prefix):
    disk_root = tmp_path / 'mounted'
    disk_root.mkdir()
    image = disk_root / 'photo.jpg'
    Image.new('RGB', (80, 60), 'blue').save(image)
    prefix = '/manual-mapped-source/'
    path = prefix + 'photo.jpg'
    seed_photos_prefix(prefix, [{'path': path, 'filename': 'photo.jpg'}])
    monkeypatch.setattr(config, '_FULL_CONFIG', {})
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {prefix.rstrip('/'): str(disk_root)})
    frame = edition_client.get('/api/photo/manual-face-frame', params={'path': path})
    assert frame.status_code == 200, frame.text
    body = {'path': path, 'frame_token': frame.json()['frame_token'], 'bbox': [0.1, 0.1, 0.5, 0.8],
            'new_person_name': 'Mapped Person', 'client_id': str(uuid4())}
    created = edition_client.post('/api/photo/manual-faces', json=body)
    assert created.status_code == 201, created.text
    assert created.json()['source_changed'] is False
    listed = edition_client.get('/api/photo/manual-faces', params={'path': path}).json()['regions']
    assert len(listed) == 1 and listed[0]['source_changed'] is False
    with get_db() as conn:
        assert conn.execute('SELECT photo_path FROM faces WHERE id=?', (created.json()['id'],)).fetchone()[0] == path
        from api.routers.export import _fetch_regions_map
        assert len(_fetch_regions_map(conn, [path]).get(path, [])) == 1
    # Repointing the same logical path must invalidate the old frame token.
    replacement = tmp_path / 'replacement'
    replacement.mkdir()
    Image.new('RGB', (80, 60), 'red').save(replacement / 'photo.jpg')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {prefix.rstrip('/'): str(replacement)})
    assert edition_client.post('/api/photo/manual-faces', json={**body, 'client_id': str(uuid4())}).status_code == 409
    assert edition_client.get('/api/photo/manual-faces', params={'path': path}).json()['regions'][0]['source_changed'] is True
