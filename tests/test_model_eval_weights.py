"""Tests for the ``weights`` slot of optimization/model_eval.py (--evaluate-models weights).

Every DB is a private temp file built with ``db.schema.init_database`` (mirroring the
``eval_db`` fixture in test_model_eval.py) rather than the shared session DB, because
``evaluate()`` takes a path. Scores come from the real ``calculate_aggregate_logic``;
nothing is stubbed, so a break in the config-variant plumbing fails here.
"""

import copy
import gc
import hashlib
import json
import os
import sqlite3

import pytest

import config_resolve
import licensing
from cli_args import build_parser
from config import ScoringConfig
from db.schema import init_database
from optimization import model_eval as me
from processing.scorer import SERVED_ROW_COLUMNS, Facet, unavailable_for_config

# photo A: strong aesthetic, weak face quality; photo B: the reverse
PHOTO_A = ('/w/a.jpg', 8.0, 2.0)
PHOTO_B = ('/w/b.jpg', 4.0, 9.0)


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def _write_json(path, payload):
    with open(path, 'w') as f:
        json.dump(payload, f)
    return str(path)


@pytest.fixture
def base_cfg(tmp_path):
    """An empty override file: the baseline resolves to the shipped defaults."""
    return _write_json(tmp_path / 'base.json', {})


@pytest.fixture
def categories(base_cfg):
    return copy.deepcopy(config_resolve.load_resolved(base_cfg, named=True)['categories'])


def _candidate(tmp_path, categories, name, **portrait_percent):
    cats = copy.deepcopy(categories)
    portrait = next(c for c in cats if c['name'] == 'portrait')
    portrait['weights'].update(portrait_percent)
    return _write_json(tmp_path / f'{name}.json', {'categories': cats})


def _insert_photo(conn, path, aesthetic, face_quality, face_count=1, face_ratio=0.3):
    conn.execute(
        "INSERT INTO photos (path, filename, aesthetic, face_quality, face_count, face_ratio, liqe_score) "
        "VALUES (?, ?, ?, ?, ?, ?, 9.0)",
        (path, os.path.basename(path), aesthetic, face_quality, face_count, face_ratio))


def _stamp_aggregates(db, cfg_path):
    """Store, for every photo, the aggregate the baseline scorer produces."""
    scorer = Facet.__new__(Facet)
    scorer.config = ScoringConfig(cfg_path, validate=False)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(f"SELECT {', '.join(SERVED_ROW_COLUMNS)} FROM photos")]
    for row in rows:
        prepared = Facet.prepare_scoring_row(row, scorer.config, None)
        conn.execute("UPDATE photos SET aggregate = ? WHERE path = ?",
                     (round(scorer.calculate_aggregate_logic(prepared)[0], 2), row['path']))
    conn.commit()
    conn.close()


def _build_db(tmp_path, n_pairs=30, winner='b', cfg_path=None):
    db = str(tmp_path / 'w.db')
    init_database(db)
    conn = sqlite3.connect(db)
    for path, aesthetic, face_quality in (PHOTO_A, PHOTO_B):
        _insert_photo(conn, path, aesthetic, face_quality)
    _insert_photo(conn, '/w/landscape.jpg', 6.0, None, face_count=0, face_ratio=0.0)
    for _ in range(n_pairs):  # user_id stays NULL
        conn.execute("INSERT INTO comparisons (photo_a_path, photo_b_path, winner) VALUES (?, ?, ?)",
                     (PHOTO_A[0], PHOTO_B[0], winner))
    conn.commit()
    conn.close()
    if cfg_path:
        _stamp_aggregates(db, cfg_path)
    # Fold the WAL into the main file so sha256/mtime compare a quiescent DB.
    gc.collect()  # init_database leaves its connection to the garbage collector
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()
    return db


def _run(db, cfg_path, candidates, tmp_path, **kwargs):
    return me.evaluate(db, 'weights', candidates=candidates, out=str(tmp_path / 'r.json'),
                       config_path=cfg_path, **kwargs)


def test_weights_is_a_slot_and_the_cli_choice():
    action = next(a for a in build_parser()._actions if '--evaluate-models' in a.option_strings)
    assert set(action.choices) == set(me.SLOTS)
    assert build_parser().parse_args(['--evaluate-models', 'weights']).evaluate_models == 'weights'
    with pytest.raises(SystemExit):
        build_parser().parse_args(['--evaluate-models', 'weightz'])


def test_identical_candidate_changes_nothing(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path)
    same = _candidate(tmp_path, categories, 'same')
    report = _run(db, base_cfg, [same], tmp_path)
    assert report['slot'] == 'weights' and report['n_decisive_pairs'] == 30
    for block in report['modes'].values():
        for bucket, cand in block['candidates'][same].items():
            base = block['baseline'][bucket]
            assert cand['dist'] == base['dist']
            if cand['n_pairs']:
                assert cand['delta'] == 0.0
                if cand['status'] == 'ok':
                    assert (cand['delta_ci_low'], cand['delta_ci_high']) == (0.0, 0.0)
            if cand['dist']:
                assert cand['mean_abs_delta'] == 0.0


@pytest.mark.parametrize('winner, sign', [('b', 1), ('a', -1)])
def test_moving_weight_to_face_quality_moves_portrait_agreement(tmp_path, base_cfg, categories, winner, sign):
    db = _build_db(tmp_path, winner=winner)
    fq_heavy = _candidate(tmp_path, categories, 'fq', aesthetic_percent=0, face_quality_percent=46)
    report = _run(db, base_cfg, [fq_heavy], tmp_path)
    for block in report['modes'].values():
        base = block['baseline']['portrait']
        cand = block['candidates'][fq_heavy]['portrait']
        assert base['n_pairs'] == 30 and cand['status'] == 'ok'
        assert base['agreement'] == (0.0 if winner == 'b' else 1.0)
        assert sign * cand['delta'] > 0
        assert cand['mean_abs_delta'] > 0
    assert report['ship_check'][fq_heavy]['portrait']['agreement_not_lower'] is (sign > 0)


@pytest.mark.parametrize('n_pairs, status', [(29, 'insufficient_pairs'), (30, 'ok')])
def test_decisive_pair_minimum(tmp_path, base_cfg, categories, n_pairs, status):
    db = _build_db(tmp_path, n_pairs=n_pairs)
    cand = _candidate(tmp_path, categories, 'fq', aesthetic_percent=0, face_quality_percent=46)
    report = _run(db, base_cfg, [cand], tmp_path)
    block = report['modes']['default']
    assert block['baseline']['portrait']['status'] == status
    row = block['candidates'][cand]['portrait']
    assert row['status'] == status and row['n_pairs'] == n_pairs
    if status == 'insufficient_pairs':
        assert row['delta_ci_low'] is None and row['delta_ci_high'] is None
        assert row['agreement'] is not None
        assert report['ship_check'][cand]['portrait']['agreement_not_lower'] is False


def test_commercial_variant_has_its_own_unavailable_set(tmp_path, base_cfg, categories, monkeypatch):
    real = licensing.importlib.util.find_spec
    monkeypatch.setattr(licensing.importlib.util, 'find_spec',
                        lambda name, *a: None if name == 'ofiq' else real(name, *a))
    base = ScoringConfig(base_cfg, validate=False)
    commercial = me._config_variant(base, base.config, 'commercial')
    default = me._config_variant(base, base.config, 'default')
    assert commercial.config['licensing']['mode'] == 'commercial'
    assert {'liqe', 'aesthetic_iaa'} <= unavailable_for_config(commercial)
    assert unavailable_for_config(default) == frozenset()
    assert base.config['licensing']['mode'] == 'default'  # the baseline itself is untouched

    db = _build_db(tmp_path)
    cand = _candidate(tmp_path, categories, 'same')
    report = _run(db, base_cfg, [cand], tmp_path)
    assert 'face_quality_iqa' in report['modes']['commercial']['unavailable']
    assert {'liqe', 'aesthetic_iaa'} <= set(report['modes']['commercial']['unavailable'])
    assert report['modes']['default']['unavailable'] == []
    # Each mode is scored with its own variant: liqe counts in default, is dropped in commercial.
    assert (report['modes']['default']['baseline']['portrait']['dist']['mean']
            != report['modes']['commercial']['baseline']['portrait']['dist']['mean'])
    assert report['modes']['default']['meaningful'] and report['modes']['commercial']['meaningful']


def test_commercial_baseline_marks_default_block_not_meaningful(tmp_path, categories):
    cfg = _write_json(tmp_path / 'commercial.json', {'licensing': {'mode': 'commercial'}})
    db = _build_db(tmp_path)
    cand = _candidate(tmp_path, categories, 'fq', aesthetic_percent=0, face_quality_percent=46)
    report = _run(db, cfg, [cand], tmp_path)
    assert report['modes']['default']['meaningful'] is False and report['modes']['default']['reason']
    assert report['modes']['commercial']['meaningful'] is True
    # The unmeaningful block is ignored: the verdict follows the commercial block alone.
    commercial = report['modes']['commercial']['candidates'][cand]['portrait']
    base = report['modes']['commercial']['baseline']['portrait']
    assert report['ship_check'][cand]['portrait']['agreement_not_lower'] is (
        commercial['agreement'] >= base['agreement'])


def test_baseline_recompute_reproduces_the_stored_aggregate(tmp_path, base_cfg):
    db = _build_db(tmp_path, cfg_path=base_cfg)
    cand = _write_json(tmp_path / 'same.json', {
        'categories': config_resolve.load_resolved(base_cfg, named=True)['categories']})
    assert _run(db, base_cfg, [cand], tmp_path)['baseline_match_rate'] == 1.0


def test_report_shape(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path)
    cand = _candidate(tmp_path, categories, 'same')
    report = _run(db, base_cfg, [cand], tmp_path)
    assert json.load(open(tmp_path / 'r.json')) == report
    assert report['min_decisive_pairs'] == 30 and report['n_orphan_pairs'] == 0
    row = report['modes']['default']['candidates'][cand]['portrait']
    assert {'agreement', 'ci_low', 'ci_high', 'n_pairs', 'coverage', 'status', 'delta',
            'delta_ci_low', 'delta_ci_high', 'dist', 'mean_abs_delta',
            'face_quality_iqa_coverage'} <= set(row)
    assert {'n_photos', 'mean', 'std', 'p10', 'p50', 'p90'} == set(row['dist'])
    assert row['face_quality_iqa_coverage'] == 0.0
    assert set(report['modes']['default']['baseline']) >= {'overall', 'portrait', 'mixed'}


def test_orphan_pairs_are_counted_not_fatal(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path, n_pairs=0)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO comparisons (photo_a_path, photo_b_path, winner) VALUES (?, '/w/gone.jpg', 'a')",
                 (PHOTO_A[0],))
    conn.commit()
    conn.close()
    gc.collect()
    report = _run(db, base_cfg, [_candidate(tmp_path, categories, 'same')], tmp_path)
    assert report['n_orphan_pairs'] == 1 and report['modes']['default']['baseline']['overall']['n_pairs'] == 0


def test_read_only_database_and_config_untouched(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path)
    cand = _candidate(tmp_path, categories, 'fq', aesthetic_percent=0, face_quality_percent=46)
    before = (_sha(db), os.stat(db).st_mtime_ns, _sha(base_cfg), _sha(cand))
    _run(db, base_cfg, [cand], tmp_path)
    assert (_sha(db), os.stat(db).st_mtime_ns, _sha(base_cfg), _sha(cand)) == before
    assert not any(p.startswith('.scoring_config.tmp') for p in os.listdir(tmp_path))


def test_candidate_config_does_not_alias_the_baseline(tmp_path, base_cfg, categories):
    base = ScoringConfig(base_cfg, validate=False)
    cand_path = _candidate(tmp_path, categories, 'fq', aesthetic_percent=0, face_quality_percent=46)
    merged = me._load_weight_candidate(cand_path, base.config)
    cand = me._config_variant(base, merged, 'default')
    twin = me._config_variant(base, base.config, 'default')
    assert cand.get_weights('portrait')['aesthetic'] == 0
    assert twin.get_weights('portrait')['aesthetic'] > 0
    assert base.get_weights('portrait')['aesthetic'] > 0


def test_guards(tmp_path, base_cfg, categories, monkeypatch):
    db = _build_db(tmp_path)
    good = _candidate(tmp_path, categories, 'good')
    with pytest.raises(ValueError, match='--candidates'):
        _run(db, base_cfg, None, tmp_path)
    with pytest.raises(ValueError, match='duplicate'):
        _run(db, base_cfg, [good, good], tmp_path)
    extra = _write_json(tmp_path / 'extra.json', {'categories': categories, 'thresholds': {}})
    with pytest.raises(ValueError, match="exactly the 'categories' key"):
        _run(db, base_cfg, [extra], tmp_path)
    no_cats = _write_json(tmp_path / 'nocats.json', {'thresholds': {}})
    with pytest.raises(ValueError, match="'categories'"):
        _run(db, base_cfg, [no_cats], tmp_path)
    reordered = _write_json(tmp_path / 'reordered.json', {'categories': list(reversed(categories))})
    with pytest.raises(ValueError, match='only each category'):
        _run(db, base_cfg, [reordered], tmp_path)
    retagged = copy.deepcopy(categories)
    retagged[0]['tags'] = {'x': ['x']}
    with pytest.raises(ValueError, match='only each category'):
        _run(db, base_cfg, [_write_json(tmp_path / 'retagged.json', {'categories': retagged})], tmp_path)
    monkeypatch.setenv(licensing.LICENSING_MODE_ENV, 'commercial')
    with pytest.raises(ValueError, match='unset it'):
        _run(db, base_cfg, [good], tmp_path)


def test_mixed_bucket_never_gets_a_ship_verdict(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path, n_pairs=0)
    conn = sqlite3.connect(db)
    for _ in range(30):
        conn.execute("INSERT INTO comparisons (photo_a_path, photo_b_path, winner) VALUES (?, ?, 'a')",
                     (PHOTO_A[0], '/w/landscape.jpg'))
    conn.commit()
    conn.close()
    gc.collect()
    cand = _candidate(tmp_path, categories, 'same')
    report = _run(db, base_cfg, [cand], tmp_path)
    assert report['modes']['default']['baseline']['mixed']['n_pairs'] == 30
    assert report['ship_check'][cand]['mixed']['agreement_not_lower'] is False


def test_candidate_weight_validation(tmp_path, base_cfg, categories):
    db = _build_db(tmp_path)
    typo = _candidate(tmp_path, categories, 'typo', face_qualty_percent=8)
    with pytest.raises(ValueError, match="unknown weight key 'face_qualty_percent'"):
        _run(db, base_cfg, [typo], tmp_path)
    for name, value in (('frac', 8.5), ('neg', -1), ('text', '8')):
        bad = _candidate(tmp_path, categories, name, face_quality_percent=value)
        with pytest.raises(ValueError, match='non-negative integer'):
            _run(db, base_cfg, [bad], tmp_path)


def test_candidate_file_errors_name_the_file(tmp_path, base_cfg):
    db = _build_db(tmp_path)
    missing = str(tmp_path / 'missing.json')
    with pytest.raises(ValueError, match='missing.json'):
        _run(db, base_cfg, [missing], tmp_path)
    broken = tmp_path / 'broken.json'
    broken.write_text('{nope', encoding='utf-8')
    with pytest.raises(ValueError, match='broken.json'):
        _run(db, base_cfg, [str(broken)], tmp_path)
    not_list = _write_json(tmp_path / 'notlist.json', {'categories': {}})
    with pytest.raises(ValueError, match='notlist.json'):
        _run(db, base_cfg, [not_list], tmp_path)
