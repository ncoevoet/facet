"""Real packet/DB coverage for explicit flat-keyword reconciliation."""
import sqlite3
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests import exiftool_fake

from db.manual_tags import delete_manual_tag, insert_manual_tag, load_manual_tags
from db.schema import init_database
from processing.xmp_export import NS_DC, NS_RDF, XmpRating, build_xmp, export_sidecars, exiftool_available, write_metadata
from processing.xmp_import import import_sidecars, parse_sidecar
from processing.xmp_keywords import reconcile_keywords


def database(tmp_path):
    path = tmp_path / 'test.db'
    init_database(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def packet_keywords(sidecar):
    return parse_sidecar(str(sidecar))['tags']


_KEYWORD_TAGS = {'Subject': 'XMP-dc:Subject', 'Keywords': 'IPTC:Keywords',
                 'HierarchicalSubject': 'XMP-lr:HierarchicalSubject'}


def _reads_keywords(args, field):
    """``'xml'`` only for the exact-name XML read of ``field``; every other read gets the JSON answer."""
    requested = {arg.lstrip('-') for arg in args if arg.startswith('-') and ':' in arg}
    return 'xml' if '-X' in args and _KEYWORD_TAGS[field] in requested else 'json'


def exact_keyword_xml(field, values, *, error=False):
    groups = {'Subject': 'XMP/XMP-dc', 'Keywords': 'IPTC/IPTC', 'HierarchicalSubject': 'XMP/XMP-lr'}
    root = ET.Element(f'{{{NS_RDF}}}RDF')
    desc = ET.SubElement(root, f'{{{NS_RDF}}}Description')
    node = ET.SubElement(desc, f'{{http://ns.exiftool.org/{groups[field]}/1.0/}}{field}')
    bag = ET.SubElement(node, f'{{{NS_RDF}}}Bag')
    for value in values:
        ET.SubElement(bag, f'{{{NS_RDF}}}li').text = value
    if error:
        ET.SubElement(desc, '{http://ns.exiftool.org/ExifTool/1.0/}Error').text = 'read failed'
    return ET.tostring(root, encoding='unicode')


def add_external_keyword(sidecar, keyword):
    packet = ET.parse(sidecar)
    bag = packet.find(f'.//{{{NS_DC}}}subject/{{{NS_RDF}}}Bag')
    if bag is None:
        desc = packet.find(f'.//{{{NS_RDF}}}Description')
        bag = ET.SubElement(ET.SubElement(desc, f'{{{NS_DC}}}subject'), f'{{{NS_RDF}}}Bag')
    ET.SubElement(bag, f'{{{NS_RDF}}}li').text = keyword
    packet.write(sidecar, encoding='utf-8', xml_declaration=True)


def test_foreign_name_collision_and_external_readd_are_never_claimed():
    flat, state = reconcile_keywords(['Foreign', 'same'], ['same', 'owned'], ai=['owned'])
    assert state['owned'] == ['owned']
    assert state['ai'] == ['owned']
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == ['Foreign', 'same']
    assert state['deleted'] == ['owned']
    flat, state = reconcile_keywords([*flat, 'owned'], ['owned'], state, reconcile=True)
    assert state['owned'] == []
    assert state['deleted'] == []
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == ['Foreign', 'same', 'owned']


@pytest.mark.parametrize('reconcile', [False, True])
def test_external_readd_expires_tombstone_without_local_readdition(reconcile):
    flat, state = reconcile_keywords([], ['beach'])
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert state['deleted'] == ['beach']
    flat, state = reconcile_keywords(['BEACH'], [], state, reconcile=reconcile)
    assert flat == ['BEACH']
    assert state['deleted'] == []
    assert state['owned'] == []
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == ['BEACH']


def test_facet_writing_absent_deleted_name_clears_tombstone_and_reclaims_it():
    flat, state = reconcile_keywords([], ['beach'])
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    flat, state = reconcile_keywords(flat, ['beach'], state, reconcile=True)
    assert flat == ['beach']
    assert state['owned'] == ['beach']
    assert state['deleted'] == []


@pytest.mark.parametrize('reconcile', [False, True])
def test_external_removal_does_not_silently_delete_current_facet_keywords(reconcile):
    _, state = reconcile_keywords([], ['beach'])
    flat, state = reconcile_keywords([], ['beach'], state, reconcile=reconcile)
    assert flat == ['beach']
    assert state['owned'] == ['beach']


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_deleted_manual_keyword_can_be_readded_externally_and_foreign_nodes_survive(tmp_path):
    from PIL import Image
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    original = image.read_bytes()
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text(build_xmp(XmpRating(tags=['foreign'])), encoding='utf-8')
    # Simulate an older external packet with no Facet ownership.
    packet = ET.parse(sidecar)
    for node in packet.iter():
        for key in list(node.attrib):
            if key.endswith('KeywordState'):
                del node.attrib[key]
    packet.write(sidecar, encoding='utf-8')
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'machine'))
        insert_manual_tag(conn, str(image), 'delete-me')
        conn.commit()
        assert export_sidecars(conn)['written'] == 1
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine', 'delete-me'}
        delete_manual_tag(conn, str(image), 'delete-me')
        conn.commit()
        # Additive default explicitly retains old keywords until reconciliation.
        export_sidecars(conn)
        assert 'delete-me' in packet_keywords(sidecar)
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine'}
        assert 'delete-me' in parse_sidecar(str(sidecar))['keyword_state']['deleted']
        # External editors often preserve private markers while copying subjects.
        add_external_keyword(sidecar, 'DELETE-ME')
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['delete-me', 'foreign']
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'foreign', 'machine', 'DELETE-ME'}
        assert parse_sidecar(str(sidecar))['keyword_state']['deleted'] == []
        # Subsequent reconciles cannot delete this now-foreign occurrence.
        delete_manual_tag(conn, str(image), 'delete-me')
        conn.commit()
        export_sidecars(conn, reconcile_keywords=True)
        assert 'DELETE-ME' in packet_keywords(sidecar)
        assert image.read_bytes() == original
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
@pytest.mark.parametrize('reconcile', [False, True])
def test_real_external_readd_survives_export_before_import(tmp_path, reconcile):
    from PIL import Image
    image = tmp_path / 'readd.jpg'
    Image.new('RGB', (16, 16)).save(image)
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
        insert_manual_tag(conn, str(image), 'beach')
        conn.commit()
        export_sidecars(conn)
        delete_manual_tag(conn, str(image), 'beach')
        conn.commit()
        export_sidecars(conn, reconcile_keywords=True)
        sidecar = Path(str(image) + '.xmp')
        assert parse_sidecar(str(sidecar))['keyword_state']['deleted'] == ['beach']
        add_external_keyword(sidecar, 'BEACH')
        export_sidecars(conn, reconcile_keywords=reconcile)
        assert packet_keywords(sidecar) == ['BEACH']
        assert parse_sidecar(str(sidecar))['keyword_state']['deleted'] == []
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['beach']
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_retag_does_not_turn_previous_ai_into_manual_and_manual_duplicate_restores(tmp_path):
    from PIL import Image
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (10, 10)).save(image)
    sidecar = Path(str(image) + '.xmp')
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'old-ai, shared'))
        insert_manual_tag(conn, str(image), 'shared')
        insert_manual_tag(conn, str(image), 'manual')
        conn.commit()
        export_sidecars(conn)
        conn.execute('UPDATE photos SET tags=?', ('new-ai',))
        conn.commit()
        # An old exported AI label must not become a permanent manual label.
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual', 'shared']
        export_sidecars(conn, reconcile_keywords=True)
        assert set(packet_keywords(sidecar)) == {'new-ai', 'manual', 'shared'}
        # Re-addition expires deletion authority, not the AI provenance that
        # prevents an old machine label becoming a permanent manual tag.
        add_external_keyword(sidecar, 'old-ai')
        conn.execute('DELETE FROM photo_manual_tags')
        conn.commit()
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual', 'shared']
    finally:
        conn.close()


def test_fallback_tracks_ai_and_manual_provenance_without_exiftool(tmp_path, monkeypatch):
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'original')
    rating = XmpRating(tags=['ai', 'manual'], ai_tags=['ai'], manual_tags=['manual'])
    write_metadata(str(image), rating)
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
        conn.commit()
        import_sidecars(conn)
        assert load_manual_tags(conn, str(image)) == ['manual']
        before = Path(str(image) + '.xmp').read_bytes()
        with pytest.raises(RuntimeError, match='requires ExifTool'):
            write_metadata(str(image), XmpRating(), reconcile_keywords=True)
        assert Path(str(image) + '.xmp').read_bytes() == before
    finally:
        conn.close()


@pytest.mark.parametrize('naming', ['full', 'basename', 'auto'])
def test_provenance_and_external_readds_follow_selected_naming_policy(tmp_path, naming):
    import json
    from processing.xmp_export import NS_FACET
    image = tmp_path / 'photo.CR2'
    image.write_bytes(b'generated placeholder')
    sidecar = Path(str(image) + '.xmp') if naming == 'full' else tmp_path / 'photo.xmp'
    packet = ET.fromstring(build_xmp(XmpRating(tags=['old-ai', 'restored'])))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', json.dumps({
        'version': 1, 'owned': [], 'deleted': ['restored'], 'ai': ['old-ai'], 'manual': []}))
    sidecar.write_bytes(ET.tostring(packet))
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'new-ai'))
        conn.commit()
        assert import_sidecars(conn, sidecar_naming=naming)['tags_added'] == 1
        assert load_manual_tags(conn, str(image)) == ['restored']
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_keyword_reconciliation_respects_user_visibility(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
    visible = tmp_path / 'alice.jpg'
    hidden = tmp_path / 'bob.jpg'
    monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path = ?', [str(visible)]))
    conn = database(tmp_path)
    try:
        for image in (visible, hidden):
            Image.new('RGB', (10, 10)).save(image)
            conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'old'))
        conn.commit()
        export_sidecars(conn)
        hidden_packet = Path(str(hidden) + '.xmp').read_bytes()
        conn.execute('UPDATE photos SET tags=?', ('new',))
        conn.commit()
        assert export_sidecars(conn, user_id='alice', reconcile_keywords=True)['written'] == 1
        assert packet_keywords(Path(str(visible) + '.xmp')) == ['new']
        assert Path(str(hidden) + '.xmp').read_bytes() == hidden_packet
        import_sidecars(conn, user_id='alice')
        assert load_manual_tags(conn, str(hidden)) == []
    finally:
        conn.close()


@pytest.mark.parametrize('payload', [
    '[]', '{}', '[null]', '[{"Error":"cannot read file"}]',
    '[{"Subject":{"bad":"shape"}}]', '[{"Subject":[["nested"]]}]', '[{"Subject":null}]',
    '[{"Error":null}]', 'not json', '{"KeywordState":null}',
    '[{"Error":"cannot read state"}]',
])
def test_failed_structured_reads_preserve_existing_packet_bytes(tmp_path, monkeypatch, payload):
    """One merged read serves all families, so ANY malformed family response —
    or a malformed record as a whole — must refuse the export before a write
    starts and leave the existing packet bytes untouched."""
    import subprocess
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    before = build_xmp(XmpRating(tags=['foreign'])).encode()
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        assert '-overwrite_original' not in args, 'metadata write must never start after failed read'
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr='')
    exiftool_fake.install(monkeypatch, run)
    with pytest.raises(RuntimeError, match='Cannot read|Unsupported'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['own']), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
@pytest.mark.parametrize('marker', ['not json', '{"version":2}', '{"version":1,"owned":"wrong"}'])
def test_invalid_marker_is_refused_without_modifying_valid_xml(tmp_path, marker):
    from processing.xmp_export import NS_FACET
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    packet = ET.fromstring(build_xmp(XmpRating(tags=['foreign'])))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', marker)
    before = ET.tostring(packet)
    sidecar.write_bytes(before)
    with pytest.raises(RuntimeError, match='Unsupported or invalid'):
        write_metadata(str(image), XmpRating(tags=['own']), reconcile_keywords=True)
    assert sidecar.read_bytes() == before


def test_outbound_provenance_growth_refuses_before_writing_and_keeps_tombstones(tmp_path, monkeypatch):
    import json
    from processing import xmp_export as xe
    from processing.xmp_export import NS_FACET
    from processing.xmp_keywords import MAX_STATE_NAMES, serialize_keyword_state
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    names = [f'old-{i}' for i in range(MAX_STATE_NAMES)]
    previous = {'version': 1, 'owned': names, 'deleted': [], 'ai': names, 'manual': []}
    packet = ET.fromstring(build_xmp(XmpRating()))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', serialize_keyword_state(previous))
    before = ET.tostring(packet)
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        import subprocess
        assert '-overwrite_original' not in args
        record = {'KeywordState': json.dumps(previous)} if '-XMP-facet:KeywordState' in args else {'Subject': names}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps([record]), stderr='')
    exiftool_fake.install(monkeypatch, run)
    with pytest.raises(RuntimeError, match='safe packet bounds.*Deletion markers were not discarded'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['new-ai'], ai_tags=['new-ai']), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize('tags', [['x' * 1025], [f'tag{i}' for i in range(10001)]])
def test_unrepresentable_new_keyword_state_never_creates_fallback_packet(tmp_path, monkeypatch, tags):
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'photo.jpg'
    with pytest.raises(RuntimeError, match='safe packet bounds'):
        write_metadata(str(image), XmpRating(tags=tags))
    assert not Path(str(image) + '.xmp').exists()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_embedded_marker_and_unicode_case_normalization_preserve_foreign_collision(tmp_path):
    from PIL import Image
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    from utils.exiftool_process import run_exiftool_process
    result = run_exiftool_process(['exiftool', '-overwrite_original', '-XMP-dc:Subject=CAFÉ', str(image)], timeout=30)
    assert result.returncode == 0, result.stderr
    write_metadata(str(image), XmpRating(tags=['Cafe\u0301', 'Straße'], manual_tags=['Straße']), embed_original=True)
    state, _ = xe._read_keyword_states(str(image), xe._resolve_exiftool(), timeout=30)
    assert state['owned'] == ['Straße']  # NFC/case-equal foreign CAFÉ is never claimed.
    result = run_exiftool_process(['exiftool', '-overwrite_original', '-XMP-dc:Subject=CAFÉ', '-XMP-dc:Subject=STRASSE', str(image)], timeout=30)
    assert result.returncode == 0, result.stderr
    write_metadata(str(image), XmpRating(), embed_original=True, reconcile_keywords=True)
    flat, _, _ = xe._read_existing_metadata(str(image), xe._resolve_exiftool(), timeout=30, strict=True)
    assert flat == ['CAFÉ']
    state, _ = xe._read_keyword_states(str(image), xe._resolve_exiftool(), timeout=30)
    assert state['deleted'] == ['Straße']


def test_explicit_null_marker_is_invalid_before_any_write(tmp_path, monkeypatch):
    import subprocess
    from processing import xmp_export as xe
    image = tmp_path / 'photo.jpg'
    sidecar = Path(str(image) + '.xmp')
    before = build_xmp(XmpRating(tags=['foreign'])).encode()
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'fake-exiftool')
    def run(args, **kwargs):
        assert '-overwrite_original' not in args
        payload = '[{"KeywordState":null}]' if '-XMP-facet:KeywordState' in args else '[{}]'
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr='')
    exiftool_fake.install(monkeypatch, run)
    with pytest.raises(RuntimeError, match='Unsupported or invalid'):
        xe._run_exiftool(str(sidecar), XmpRating(), timeout=1, reconcile=True)
    assert sidecar.read_bytes() == before


def test_foreign_case_and_normalization_display_variants_are_not_collapsed():
    foreign = ['CAFÉ', 'Cafe\u0301', 'café']
    flat, state = reconcile_keywords(foreign, ['café'])
    assert flat == foreign
    assert state['owned'] == []
    flat, state = reconcile_keywords(flat, [], state, reconcile=True)
    assert flat == foreign


@pytest.mark.parametrize('value,expected', [(2024, ['2024']), (2.5, ['2.5']), (True, ['true']), (False, ['false']),
                                           ([2024, 'holiday', 2.5], ['2024', 'holiday', '2.5'])])
@pytest.mark.parametrize('field', ['Subject', 'Keywords', 'HierarchicalSubject'])
def test_exiftool_numeric_keyword_json_is_stringified(monkeypatch, value, expected, field):
    import json
    import subprocess
    from processing import xmp_export as xe
    exiftool_fake.install(monkeypatch, lambda args:
                        subprocess.CompletedProcess(args, 0, stdout=exact_keyword_xml(field, expected)
                                                    if _reads_keywords(args, field) == 'xml'
                                                    else json.dumps([{field: value}])))
    flat, hierarchical, _ = xe._read_existing_metadata('existing.xmp', 'exiftool', timeout=1, strict=True)
    assert (hierarchical if field == 'HierarchicalSubject' else flat) == expected


def test_raw_json_keyword_tokens_preserve_exact_lexical_names(monkeypatch):
    import subprocess
    from processing import xmp_export as xe
    exiftool_fake.install(monkeypatch, lambda args:
                        subprocess.CompletedProcess(args, 0,
                            stdout=exact_keyword_xml('Subject', ['true', 'false', 'null', '1.50', '1e3', '2024'])
                            if _reads_keywords(args, 'Subject') == 'xml'
                            else '[{"Subject":[true,false,"null",1.50,1e3,2024]}]'))
    flat, _, _ = xe._read_existing_metadata('existing.xmp', 'exiftool', timeout=1, strict=True)
    assert flat == ['true', 'false', 'null', '1.50', '1e3', '2024']


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
@pytest.mark.parametrize('reconcile', [False, True])
@pytest.mark.parametrize('embed', [False, True])
def test_real_numeric_keywords_survive_cli_writer_paths(tmp_path, embed, reconcile, seed_keywords):
    import subprocess
    from PIL import Image
    from processing import xmp_export as xe
    image = tmp_path / 'year.jpg'
    Image.new('RGB', (16, 16)).save(image)
    sidecar = Path(str(image) + '.xmp')
    packet = ET.fromstring(build_xmp(XmpRating()))
    ET.SubElement(packet.find(f'.//{{{NS_RDF}}}Description'), '{urn:foreign:keep}Extension').text = 'untouched'
    source = tmp_path / 'seed.xmp'
    source.write_bytes(ET.tostring(packet))
    if embed:
        subprocess.run(['exiftool', '-overwrite_original', '-XMP<=' + str(source), str(image)],
                       check=True, capture_output=True)
    else:
        sidecar.write_bytes(source.read_bytes())
    target = image if embed else sidecar
    names = seed_keywords([target], ['True', 'FALSE', 'tRuE', 'true', 'false', 'null', '1.50', '1e3', '2024'],
                          '-IPTC:Keywords=FALSE', '-XMP-lr:HierarchicalSubject=tRuE')
    conn = database(tmp_path)
    try:
        conn.execute('INSERT INTO photos(path,tags) VALUES (?,?)', (str(image), 'facet-tag'))
        conn.commit()
        for _ in range(2):
            assert export_sidecars(conn, embed_original=embed, reconcile_keywords=reconcile)['written'] == 1
            flat, hierarchy, _ = xe._read_existing_metadata(str(target), xe._resolve_exiftool(), timeout=30, strict=True)
            assert flat == [*names, 'facet-tag']
            assert hierarchy == ['tRuE']
            raw = subprocess.check_output(['exiftool', '-b', '-XMP', str(target)])
            assert ET.fromstring(raw).find('.//{urn:foreign:keep}Extension').text == 'untouched'
    finally:
        conn.close()


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_control_character_keyword_beside_a_boolean_survives_embedding(tmp_path, monkeypatch):
    from PIL import Image
    from processing import xmp_export as xe
    from utils.exiftool_process import run_exiftool_process
    image = tmp_path / 'bell.jpg'
    Image.new('RGB', (16, 16)).save(image)
    names = ['True', 'bell\x07x', 'café']
    seeded_write = run_exiftool_process(
        ['exiftool', '-q', '-overwrite_original', *[f'-IPTC:Keywords={name}' for name in names], str(image)],
        timeout=30)
    assert seeded_write.returncode == 0, seeded_write.stderr
    seeded = run_exiftool_process(['exiftool', '-j', '-IPTC:Keywords', str(image)], timeout=30)
    assert seeded.returncode == 0, seeded.stderr
    assert xe._exiftool_record(seeded.stdout)['Keywords'] == [True, *names[1:]]
    write_metadata(str(image), XmpRating.from_row({'path': str(image), 'tags': 'dog'}), embed_original=True)
    # XMP cannot hold U+0007 (ExifTool writes it as '.'); IPTC must keep it, never -X's base64 text.
    readback = run_exiftool_process(['exiftool', '-j', '-IPTC:Keywords', str(image)], timeout=30)
    assert readback.returncode == 0, readback.stderr
    keywords = xe._exiftool_record(readback.stdout)
    assert keywords['Keywords'] == [True, *names[1:], 'dog']


@pytest.mark.parametrize('xml', ['not xml', '<empty/>', exact_keyword_xml('Keywords', ['True']),
                                 exact_keyword_xml('Subject', ['True'], error=True)])
def test_failed_exact_boolean_read_refuses_before_writing(tmp_path, monkeypatch, xml):
    import subprocess
    from processing import xmp_export as xe
    sidecar = tmp_path / 'photo.jpg.xmp'
    before = build_xmp(XmpRating(tags=['True'])).encode('utf-8')
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'mock-exiftool')
    subject_reads = []
    def run(args, **kwargs):
        assert '-overwrite_original' not in args
        if _reads_keywords(args, 'Subject') == 'xml':
            subject_reads.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=xml)
        return subprocess.CompletedProcess(args, 0, stdout='[{"Subject":true}]')
    exiftool_fake.install(monkeypatch, run)
    with pytest.raises(RuntimeError, match='Cannot read existing keywords'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['own']), timeout=1)
    assert subject_reads
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize('failure', [OSError('read failed'), subprocess.TimeoutExpired('exiftool', 1)])
def test_exact_boolean_read_io_failure_refuses_before_writing(tmp_path, monkeypatch, failure):
    import subprocess
    from processing import xmp_export as xe
    sidecar = tmp_path / 'photo.jpg.xmp'
    before = build_xmp(XmpRating(tags=['True'])).encode('utf-8')
    sidecar.write_bytes(before)
    monkeypatch.setattr(xe, '_resolve_exiftool', lambda: 'mock-exiftool')
    subject_reads = []
    def run(args, **kwargs):
        assert '-overwrite_original' not in args
        if _reads_keywords(args, 'Subject') == 'xml':
            subject_reads.append(args)
            raise failure
        return subprocess.CompletedProcess(args, 0, stdout='[{"Subject":true}]')
    exiftool_fake.install(monkeypatch, run)
    # One budget covers every read, so the combined state read that precedes
    # the injected failure must fit in it too: 0.05 s did not on a slow Windows
    # runner, which then refused at that read ("Cannot read face metadata").
    with pytest.raises(RuntimeError, match='Cannot read existing keywords'):
        xe._run_exiftool(str(sidecar), XmpRating(tags=['own']), timeout=1)
    assert subject_reads
    assert sidecar.read_bytes() == before
