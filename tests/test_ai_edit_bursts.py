"""An imported AI edit always sits in its original's burst, and the lead follows ``pick_lead``.

Private ``init_database`` databases only (``.claude/patterns/test-fixtures.md``): the burst pass
rewrites every row's burst state, so it must not run against the shared session database.
"""

import os
import sqlite3

import pytest
from PIL import Image

from config_resolve import defaults_path
from db.ai_edits import join_ai_edits_to_original_sets
from db.schema import init_database
from processing.scorer import process_bursts

BURST = 'ffff0000ffff0000'
# Far from BURST in phash: an edit changes the picture, so it is never "visually similar".
EDITED = '0000ffff0000ffff'


@pytest.fixture
def quiet_plugins(monkeypatch):
    import plugins
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: None)


def _library(tmp_path, frames, edits):
    """``frames``: (path, date, phash, aggregate); ``edits``: (edit_path, source_path)."""
    db_path = str(tmp_path / 'library.db')
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        for path, when, phash, aggregate in frames:
            conn.execute('INSERT INTO photos (path, filename, date_taken, phash, aggregate) VALUES (?,?,?,?,?)',
                         (path, path.rsplit('/', 1)[-1], when, phash, aggregate))
        for edit, source in edits:
            conn.execute("INSERT INTO photo_ai_edits (edit_path, source_path, tool, revision) "
                         "VALUES (?, ?, 'antigravity-gemini', 1)", (edit, source))
    return db_path


def _state(db_path):
    with sqlite3.connect(db_path) as conn:
        return {p: (lead, gid) for p, lead, gid in
                conn.execute('SELECT path, is_burst_lead, burst_group_id FROM photos')}


@pytest.mark.parametrize('edit_date', ['2026:02:01 10:00:01', '2026:02:01 18:30:00', None],
                         ids=['same-moment', 'hours-later', 'no-date'])
def test_a_rescan_keeps_the_edit_in_its_originals_burst_and_the_burst_whole(tmp_path, quiet_plugins, edit_date):
    """The edit sorts between the frames (or far from them) with a phash unlike theirs: before,
    the pass either dropped it or split the original's burst in two around it."""
    frames = [('/lib/IMG_1.JPG', '2026:02:01 10:00:00', BURST, 6.0),
              ('/lib/IMG_1_agy_1.JPG', edit_date, EDITED, 9.0),
              ('/lib/IMG_2.JPG', '2026:02:01 10:00:02', BURST, 7.0),
              ('/lib/IMG_3.JPG', '2026:02:01 10:00:03', BURST, 5.0),
              ('/lib/OTHER.JPG', '2026:03:01 10:00:00', 'f0f0f0f0f0f0f0f0', 6.0)]
    db_path = _library(tmp_path, frames, [('/lib/IMG_1_agy_1.JPG', '/lib/IMG_1.JPG')])
    process_bursts(db_path, config_path=defaults_path())
    state = _state(db_path)
    group = state['/lib/IMG_1.JPG'][1]
    assert group is not None
    assert {p for p, (_, gid) in state.items() if gid == group} == {
        '/lib/IMG_1.JPG', '/lib/IMG_1_agy_1.JPG', '/lib/IMG_2.JPG', '/lib/IMG_3.JPG'}
    # The best score leads, as for any burst: here the edit.
    assert [p for p, (lead, gid) in state.items() if gid == group and lead] == ['/lib/IMG_1_agy_1.JPG']
    assert state['/lib/OTHER.JPG'] == (1, None)


def test_a_standalone_original_and_its_edit_form_a_burst_and_a_second_run_writes_nothing(tmp_path, quiet_plugins):
    frames = [('/lib/IMG_9.JPG', '2026:02:01 10:00:00', BURST, 7.0),
              ('/lib/IMG_9_gpt_1.PNG', None, EDITED, 6.0)]
    db_path = _library(tmp_path, frames, [('/lib/IMG_9_gpt_1.PNG', '/lib/IMG_9.JPG')])
    process_bursts(db_path, config_path=defaults_path())
    state = _state(db_path)
    assert state['/lib/IMG_9.JPG'][0] == 1 and state['/lib/IMG_9_gpt_1.PNG'][0] == 0
    assert state['/lib/IMG_9.JPG'][1] is not None and state['/lib/IMG_9.JPG'][1] == state['/lib/IMG_9_gpt_1.PNG'][1]
    with sqlite3.connect(db_path) as conn:
        before = conn.execute('SELECT group_concat(path || is_burst_lead || burst_group_id) FROM photos').fetchone()
    process_bursts(db_path, config_path=defaults_path())
    with sqlite3.connect(db_path) as conn:
        assert conn.execute('SELECT group_concat(path || is_burst_lead || burst_group_id) FROM photos').fetchone() == before


def test_an_edit_of_an_edit_follows_the_chain_to_its_original(tmp_path, quiet_plugins):
    frames = [('/lib/IMG_5.JPG', '2026:02:01 10:00:00', BURST, 6.0),
              ('/lib/IMG_5_agy_1.JPG', None, EDITED, 6.5),
              ('/lib/IMG_5_agy_1_gpt_1.JPG', None, 'aaaa5555aaaa5555', 6.2)]
    db_path = _library(tmp_path, frames, [('/lib/IMG_5_agy_1.JPG', '/lib/IMG_5.JPG'),
                                          ('/lib/IMG_5_agy_1_gpt_1.JPG', '/lib/IMG_5_agy_1.JPG')])
    process_bursts(db_path, config_path=defaults_path())
    state = _state(db_path)
    assert len({gid for _, gid in state.values()}) == 1 and None not in {gid for _, gid in state.values()}
    assert [p for p, (lead, _) in state.items() if lead] == ['/lib/IMG_5_agy_1.JPG']


def test_the_import_join_lets_an_edit_that_scores_best_lead(tmp_path):
    frames = [('/lib/IMG_1.JPG', '2026:02:01 10:00:00', BURST, 6.1),
              ('/lib/IMG_2.JPG', '2026:02:01 10:00:01', BURST, 5.0),
              ('/lib/IMG_1_agy_1.JPG', None, EDITED, 7.4)]
    db_path = _library(tmp_path, frames, [('/lib/IMG_1_agy_1.JPG', '/lib/IMG_1.JPG')])
    with sqlite3.connect(db_path) as conn:
        conn.executemany('UPDATE photos SET burst_group_id = 7, is_burst_lead = ? WHERE path = ?',
                         [(1, '/lib/IMG_1.JPG'), (0, '/lib/IMG_2.JPG')])
        assert join_ai_edits_to_original_sets(conn, ['/lib/IMG_1_agy_1.JPG']) == 1
    assert _state(db_path) == {'/lib/IMG_1.JPG': (0, 7), '/lib/IMG_2.JPG': (0, 7), '/lib/IMG_1_agy_1.JPG': (1, 7)}


def test_the_import_join_writes_the_originals_tags_through_photo_tags(tmp_path):
    frames = [('/lib/IMG_1.JPG', '2026:02:01 10:00:00', BURST, 6.0),
              ('/lib/IMG_1_agy_1.JPG', None, EDITED, 5.0)]
    db_path = _library(tmp_path, frames, [('/lib/IMG_1_agy_1.JPG', '/lib/IMG_1.JPG')])
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE photos SET tags = 'party,cake' WHERE path = '/lib/IMG_1.JPG'")
        # sync_photo_tags only keeps a populated lookup table in step.
        conn.executemany('INSERT INTO photo_tags (photo_path, tag) VALUES (?, ?)',
                         [('/lib/IMG_1.JPG', 'party'), ('/lib/IMG_1.JPG', 'cake')])
        join_ai_edits_to_original_sets(conn, ['/lib/IMG_1_agy_1.JPG'])
        rows = sorted(t for (t,) in conn.execute(
            "SELECT tag FROM photo_tags WHERE photo_path = '/lib/IMG_1_agy_1.JPG'"))
    assert rows == ['cake', 'party']


def test_an_ai_edit_scan_places_the_resolved_edit_and_skips_the_library_passes(tmp_path, monkeypatch, quiet_plugins):
    """``facet.py IMG_1_agy_1.JPG --ai-edit`` run from the photo's folder, scoring stubbed: the join gets
    the stored (resolved) path, and the bursts / sequences passes never run."""
    import cli_args
    import facet
    import models.model_manager
    import processing.multi_pass
    import processing.scorer
    from config import ScoringConfig

    folder = tmp_path / 'lib'
    folder.mkdir()
    for name in ('IMG_1.JPG', 'IMG_1_agy_1.JPG'):
        Image.new('RGB', (8, 8), (90, 90, 90)).save(folder / name)
    original, edit = (os.path.realpath(folder / n) for n in ('IMG_1.JPG', 'IMG_1_agy_1.JPG'))
    db_path = _library(tmp_path, [(original, '2026:02:01 10:00:00', BURST, 6.0)], [(edit, original)])
    config_path = tmp_path / 'scoring_config.json'
    config_path.write_text('{}', encoding='utf-8')

    class _Scorer:
        def __init__(self, db_path, config_path, multi_pass):
            self.db_path, self.config = db_path, ScoringConfig(config_path, validate=False)

        def filter_unscanned_paths(self, paths):
            return set(paths) - {original}

        def commit(self):
            pass

    def score(paths, name, scorer, manager):
        with sqlite3.connect(db_path) as conn:
            for path in paths:
                conn.execute("INSERT INTO photos (path, filename, phash, aggregate) VALUES (?, ?, ?, 8.0)",
                             (os.path.realpath(path), os.path.basename(path), EDITED))
        return len(paths)

    def library_pass(*args, **kwargs):
        raise AssertionError('an --ai-edit scan ran a library-wide pass')

    monkeypatch.setattr(processing.scorer, 'Facet', _Scorer)
    monkeypatch.setattr(processing.multi_pass, 'run_single_pass', score)
    monkeypatch.setattr(models.model_manager, 'ModelManager', lambda config: None)
    monkeypatch.setattr(processing.scorer, 'process_bursts', library_pass)
    monkeypatch.setattr(facet, 'detect_all_sequences', library_pass)
    monkeypatch.chdir(folder)
    args = cli_args.build_parser().parse_args(
        ['IMG_1_agy_1.JPG', '--ai-edit', '--db', db_path, '--config', str(config_path)])
    args.single_pass_name = 'stub'  # the 'pass' route: one stubbed scoring call

    assert facet._run_scan(args, None) is True
    state = _state(db_path)
    assert state[original][1] is not None and state[edit][1] == state[original][1]
    assert (state[original][0], state[edit][0]) == (0, 1)  # the edit scores best, so it leads
