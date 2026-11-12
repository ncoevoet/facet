"""Explicit hierarchy transport, separate from literal flat keyword names."""

import hashlib
import json
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from db.keyword_hierarchy import (
    HierarchyError, assign_path, create_keyword_hierarchy_schema, load_hierarchy_map,
    photo_hierarchies, remove_assignment,
)
from processing.xmp_export import (
    NS_DC, NS_FACET, NS_LR, NS_RDF, XmpRating, build_xmp, exiftool_available, write_metadata,
)
from processing.xmp_import import import_sidecars


def values(root, namespace, field):
    return [node.text for node in root.findall(f'.//{{{namespace}}}{field}/{{{NS_RDF}}}Bag/{{{NS_RDF}}}li')]


def state(root, field):
    desc = root.find(f'.//{{{NS_RDF}}}Description')
    return json.loads(desc.get(f'{{{NS_FACET}}}{field}'))


def test_explicit_paths_keep_commas_slashes_and_generated_provenance_separate():
    rating = XmpRating.from_row({'tags': ['literal|flat', 'literal/slash'],
        'hierarchy_paths': ['Places|City, Coast', 'Animals|Wild/Cat'],
        'category': 'portrait', 'person_names': ['Alice']})
    root = ET.fromstring(build_xmp(rating))
    assert values(root, NS_LR, 'hierarchicalSubject') == [
        'Category|portrait', 'People|Alice', 'Places|City, Coast', 'Animals|Wild/Cat']
    assert values(root, NS_DC, 'subject') == [
        'literal|flat', 'literal/slash', 'Alice', 'Places|City, Coast', 'Animals|Wild/Cat']
    marker = state(root, 'HierarchyState')
    assert marker['ai'] == ['Category|portrait', 'People|Alice']
    assert marker['manual'] == ['Places|City, Coast', 'Animals|Wild/Cat']
    assert state(root, 'KeywordState')['manual'] == marker['manual']
    for invalid in ['Animals|Cat', ['Animals||Cat'], [1], ['a'] * 51]:
        with pytest.raises(HierarchyError):
            XmpRating.from_row({'hierarchy_paths': invalid})


def test_bulk_loader_is_scoped_bounded_and_read_only():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
        before = list(conn.iterdump())
        assert load_hierarchy_map(conn, ['visible']) == {}
        assert list(conn.iterdump()) == before
        create_keyword_hierarchy_schema(conn)
        conn.executemany('INSERT INTO photos VALUES(?)', [('visible',), ('hidden',)])
        leaf, _ = assign_path(conn, 'visible', ['Visible', 'Cat'], source='xmp', imported_path='VISIBLE|cat')
        hidden, _ = assign_path(conn, 'hidden', ['Private', 'Cat'])
        # Invalid unrelated private ancestry must not even enter this read.
        conn.execute("UPDATE keyword_nodes SET name_key='broken' WHERE id=?", (hidden,))
        before = list(conn.iterdump())
        result = load_hierarchy_map(conn, ['visible', 'visible'])
        assert result == {'visible': [{'node_id': leaf, 'segments': ['Visible', 'Cat'],
            'source': 'xmp', 'exported_path': 'VISIBLE|cat'}]}
        assert load_hierarchy_map(conn, []) == {}
        with pytest.raises(HierarchyError, match='budget'):
            load_hierarchy_map(conn, ['visible'], max_bytes=1)
        assert list(conn.iterdump()) == before


def test_import_roundtrip_uses_only_explicit_paths_and_respects_removed_assignments(tmp_path):
    from db.schema import init_database
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'original fixture bytes')
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text(build_xmp(XmpRating(tags=['literal|flat', 'literal/slash'],
        hierarchy_paths=['Animals|Domestic|Cat', 'Animals|Wild|Cat'],
        category='portrait', person_names=['Alice'])), encoding='utf-8')
    db = tmp_path / 'catalog.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('INSERT INTO photos(path,tags) VALUES(?,?)', (str(image), 'machine'))
        conn.commit()
        before = list(conn.iterdump())
        planned = import_sidecars(conn, fields=['keywords'], dry_run=True)
        assert planned['hierarchy_updated'] == 2
        assert list(conn.iterdump()) == before
        result = import_sidecars(conn, fields=['keywords'])
        assert result['hierarchy_updated'] == 2
        assigned = photo_hierarchies(conn, str(image))
        assert [item['exported_path'] for item in assigned] == ['Animals|Domestic|Cat', 'Animals|Wild|Cat']
        tags = {row[0] for row in conn.execute('SELECT tag FROM photo_manual_tags')}
        assert tags == {'literal|flat', 'literal/slash', 'alice'}
        assert conn.execute('SELECT tags FROM photos').fetchone()[0] == 'machine'
        assert import_sidecars(conn, fields=['keywords'])['hierarchy_updated'] == 0
        remove_assignment(conn, str(image), assigned[0]['node_id'])
        conn.commit()
        before = list(conn.iterdump())
        assert import_sidecars(conn, fields=['keywords'])['hierarchy_updated'] == 0
        assert list(conn.iterdump()) == before
        assert image.read_bytes() == b'original fixture bytes'


def test_legacy_facet_packet_without_hierarchy_state_skips_generated_category_and_people(tmp_path):
    """Facet <= 1.28 wrote Category|/People| paths with a KeywordState but no HierarchyState."""
    from db.schema import init_database
    legacy, foreign = tmp_path / 'legacy.jpg', tmp_path / 'foreign.jpg'
    root = ET.fromstring(build_xmp(XmpRating(hierarchy_paths=['Places|Coast'],
                                             category='portrait', person_names=['Alice'])))
    root.find(f'.//{{{NS_RDF}}}Description').attrib.pop(f'{{{NS_FACET}}}HierarchyState')
    Path(str(legacy) + '.xmp').write_bytes(ET.tostring(root))
    root.find(f'.//{{{NS_RDF}}}Description').attrib.pop(f'{{{NS_FACET}}}KeywordState')
    Path(str(foreign) + '.xmp').write_bytes(ET.tostring(root))
    db = tmp_path / 'catalog.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for image in (legacy, foreign):
            image.write_bytes(b'fixture')
            conn.execute('INSERT INTO photos(path,category) VALUES(?,?)', (str(image), 'portrait'))
        conn.commit()
        preview = import_sidecars(conn, fields=['keywords'], dry_run=True)
        by_path = {entry['path']: entry['diagnostics'] for entry in preview['entries']}
        # The legacy rule cannot tell a typed path from a generated one, so each one it sets aside is reported.
        assert [d for d in by_path[str(legacy)] if d['reason'] == 'legacy_generated_path'] == [
            {'field': 'hierarchy', 'value': 'Category|portrait', 'reason': 'legacy_generated_path'},
            {'field': 'hierarchy', 'value': 'People|Alice', 'reason': 'legacy_generated_path'}]
        assert not [d for d in by_path.get(str(foreign), []) if d['reason'] == 'legacy_generated_path']
        import_sidecars(conn, fields=['keywords'])
        assert [item['exported_path'] for item in photo_hierarchies(conn, str(legacy))] == ['Places|Coast']
        # Another editor's packet carries no Facet marker: its Category| path is the user's.
        assert [item['exported_path'] for item in photo_hierarchies(conn, str(foreign))] == [
            'Category|portrait', 'People|Alice', 'Places|Coast']


def test_released_schema_dry_run_plans_hierarchy_without_migration(tmp_path):
    image = tmp_path / 'old.jpg'
    image.write_bytes(b'original')
    Path(str(image) + '.xmp').write_text(build_xmp(XmpRating(hierarchy_paths=['Places|Coast'])), encoding='utf-8')
    db = tmp_path / 'old.db'
    with sqlite3.connect(db) as conn:
        schema = Path(__file__).parent / 'fixtures' / 'photo_stacks_v1_23_1_schema.sql'
        conn.executescript(schema.read_text(encoding='utf-8'))
        conn.execute('INSERT INTO photos(path) VALUES(?)', (str(image),))
        conn.commit()
        tables_before = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    before = db.read_bytes()
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        result = import_sidecars(conn, fields=['keywords'], dry_run=True)
        assert result['hierarchy_updated'] == 1
        assert result['entries'][0]['changes']['hierarchy']['assigned'] == ['Places|Coast']
        assert [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")] == [row[0] for row in tables_before]
    assert db.read_bytes() == before


def test_import_cap_and_user_authority_refuse_without_creating_speculative_nodes():
    from db.keyword_hierarchy import plan_path_import
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
        conn.execute("INSERT INTO photos VALUES('photo')")
        create_keyword_hierarchy_schema(conn)
        assign_path(conn, 'photo', ['Owned', 'Cat'])
        before = list(conn.iterdump())
        plan, diagnostics = plan_path_import(conn, 'photo', ['owned|CAT'])
        assert plan == [] and diagnostics[0]['reason'] == 'local_hierarchy_edit'
        plan, diagnostics = plan_path_import(conn, 'photo', [f'New|Tag{i}' for i in range(50)])
        assert plan == [] and diagnostics[-1]['reason'] == 'hierarchy_cap'
        assert list(conn.iterdump()) == before


def test_generated_path_formatting_changes_do_not_mint_manual_classifications(tmp_path):
    from db.schema import init_database
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'original')
    root = ET.fromstring(build_xmp(XmpRating(person_names=['Alice'], hierarchy_paths=['Places|Coast'])))
    for node in root.findall(f'.//{{{NS_LR}}}hierarchicalSubject/{{{NS_RDF}}}Bag/{{{NS_RDF}}}li'):
        node.text = ' People  | ALICE ' if node.text == 'People|Alice' else ' Places | Coast '
    ET.ElementTree(root).write(str(image) + '.xmp', encoding='utf-8')
    db = tmp_path / 'catalog.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('INSERT INTO photos(path) VALUES(?)', (str(image),))
        conn.commit()
        result = import_sidecars(conn, fields=['keywords'])
        assert result['hierarchy_updated'] == 1
        assert [item['exported_path'] for item in photo_hierarchies(conn, str(image))] == [' Places | Coast ']
        # The normalized explicit LR counterpart also identifies its flat compatibility duplicate.
        assert {row[0] for row in conn.execute('SELECT tag FROM photo_manual_tags')} == {'alice'}


@pytest.mark.parametrize(('paths', 'cap', 'expected'), [(['One', 'Two'], 1, 1), (['Shared|One', 'Shared|Two'], 3, 2)])
def test_multi_photo_preview_reserves_vocabulary_budget_and_deduplicates_shared_ancestors(tmp_path, monkeypatch, paths, cap, expected):
    from db.schema import init_database
    monkeypatch.setattr('db.keyword_hierarchy.MAX_NODES', cap)
    db = tmp_path / 'catalog.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for index, path in enumerate(paths):
            image = tmp_path / f'{index}.jpg'
            image.write_bytes(b'original')
            Path(str(image) + '.xmp').write_text(build_xmp(XmpRating(hierarchy_paths=[path])), encoding='utf-8')
            conn.execute('INSERT INTO photos(path) VALUES(?)', (str(image),))
        conn.commit()
        before = list(conn.iterdump())
        preview = import_sidecars(conn, fields=['keywords'], dry_run=True)
        assert list(conn.iterdump()) == before
        applied = import_sidecars(conn, fields=['keywords'])
        assert preview['hierarchy_updated'] == applied['hierarchy_updated'] == expected
        assert [entry['changes'] for entry in preview['entries']] == [entry['changes'] for entry in applied['entries']]
        assert conn.execute('SELECT COUNT(*) FROM keyword_nodes').fetchone()[0] == cap


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_real_exiftool_reconciles_only_owned_hierarchy_and_preserves_foreign_packet(tmp_path):
    from PIL import Image
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    original = hashlib.sha256(image.read_bytes()).hexdigest()
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text('''<x:xmpmeta xmlns:x="adobe:ns:meta/"
      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:lr="http://ns.adobe.com/lightroom/1.0/" xmlns:dt="http://darktable.sf.net/">
      <rdf:RDF><rdf:Description dt:history_end="7"><lr:hierarchicalSubject><rdf:Bag>
      <rdf:li>Animals|Domestic|Cat</rdf:li><rdf:li>Foreign|001</rdf:li><rdf:li>Foreign|TRUE</rdf:li>
      </rdf:Bag></lr:hierarchicalSubject></rdf:Description></rdf:RDF></x:xmpmeta>''', encoding='utf-8')
    rating = XmpRating(hierarchy_paths=['Animals|Domestic|Cat', 'Places|City, Coast'],
                       category='portrait', person_names=['Alice'])
    for _ in range(2):
        write_metadata(str(image), rating)
    root = ET.parse(sidecar).getroot()
    assert values(root, NS_LR, 'hierarchicalSubject') == [
        'Animals|Domestic|Cat', 'Foreign|001', 'Foreign|TRUE',
        'Category|portrait', 'People|Alice', 'Places|City, Coast']
    from db.schema import init_database
    db = tmp_path / 'roundtrip.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('INSERT INTO photos(path) VALUES(?)', (str(image),))
        conn.commit()
        assert import_sidecars(conn, fields=['keywords'])['hierarchy_updated'] == 4
        assert {item['exported_path'] for item in photo_hierarchies(conn, str(image))} == {
            'Animals|Domestic|Cat', 'Foreign|001', 'Foreign|TRUE', 'Places|City, Coast'}
    # Default additive export retains removed assignments until explicit reconcile.
    write_metadata(str(image), XmpRating())
    assert 'Places|City, Coast' in values(ET.parse(sidecar).getroot(), NS_LR, 'hierarchicalSubject')
    write_metadata(str(image), XmpRating(), reconcile_keywords=True)
    root = ET.parse(sidecar).getroot()
    assert values(root, NS_LR, 'hierarchicalSubject') == ['Animals|Domestic|Cat', 'Foreign|001', 'Foreign|TRUE']
    # A later edit/export must still reconcile against both ownership markers.
    write_metadata(str(image), rating)
    assert values(ET.parse(sidecar).getroot(), NS_LR, 'hierarchicalSubject') == [
        'Animals|Domestic|Cat', 'Foreign|001', 'Foreign|TRUE',
        'Category|portrait', 'People|Alice', 'Places|City, Coast']
    write_metadata(str(image), XmpRating(), reconcile_keywords=True)
    root = ET.parse(sidecar).getroot()
    assert values(root, NS_LR, 'hierarchicalSubject') == ['Animals|Domestic|Cat', 'Foreign|001', 'Foreign|TRUE']
    history = '{http://darktable.sf.net/}history_end'
    assert any(node.get(history) == '7' or (node.tag == history and node.text == '7') for node in root.iter())
    assert hashlib.sha256(image.read_bytes()).hexdigest() == original
    before = sidecar.read_bytes()
    broken = ET.parse(sidecar)
    marker = f'{{{NS_FACET}}}HierarchyState'
    for node in broken.iter():
        if marker in node.attrib:
            node.set(marker, '{invalid')
        if node.tag == marker:
            node.text = '{invalid'
    broken.write(sidecar, encoding='utf-8')
    malformed = sidecar.read_bytes()
    with pytest.raises(RuntimeError, match='ownership'):
        write_metadata(str(image), rating)
    assert sidecar.read_bytes() == malformed and malformed != before
    assert hashlib.sha256(image.read_bytes()).hexdigest() == original
