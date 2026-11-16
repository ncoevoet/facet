"""``process_bursts`` reads through the covering index and writes only what changed
(post-scan speed spec, Step 2).

Pinned here:

* parity: on a tie-heavy ~400-row library the stored ``(is_burst_lead, burst_group_id)`` of every row,
  and the ``on_burst_detected`` payloads, equal what HEAD's grouping produces
  (``tests/_post_scan_reference_burst.py``). The oracle takes its ROW ORDER from HEAD's own
  statement run by SQLite, not from the Python sort key under test;
* idempotence, in isolation: a second call logs ``0 rows changed`` and no other connection sees a
  committed write. (Through the scan pipeline the bracket pass rewrites ``is_burst_lead`` on promoted
  leads, so the count there is legitimately nonzero; this test is scoped to ``process_bursts`` alone);
* the production ``_BURST_ROWS_SQL`` plans ``USING COVERING INDEX idx_post_scan``, with a control
  that drops the index and sees the plan flip.

Private ``init_database`` databases only (``.claude/patterns/test-fixtures.md``): this pass rewrites
every row, so it must not touch the shared session database.
"""

import json
import logging
import random
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pytest

from config import ScoringConfig
from config_resolve import defaults_path
from db.schema import init_database
from processing.scorer import _BURST_ROWS_SQL, process_bursts
from tests._post_scan_reference_burst import head_order_plan, reference_bursts
from tests.test_post_scan_indexes import MIN_COVERING_SQLITE

HEAD_ORDER_PLAN = "SCAN photos USING INDEX idx_date_taken_desc"


def _flip(value, bits):
    for b in bits:
        value ^= 1 << b
    return value


def _hex(value):
    return f"{value:016x}"


def _build_library(db_path, seed, with_faces=True, with_learned=True):
    """~400 photo rows designed to bite. Returns the number of rows inserted.

    * clusters 400 s apart (well outside the 48 s window), each of several timestamps, THREE frames
      per timestamp (equal ``date_taken``: the tie order is the whole point), with many frames sharing
      every score so ``pick_lead`` ties and the first-in-order frame wins;
    * phashes within a few bits of the cluster base, plus frames 22-30 bits away (only the relaxed
      rapid-burst threshold admits those, and only when ``shares_person`` agrees) and frames 40+ away;
    * NULL ``date_taken`` rows with a phash, a text that is not a date, an ISO ``T`` date, an empty
      phash;
    * NULL-phash rows carrying a stale ``burst_group_id``;
    * stale state on phash rows: a group that no longer exists, a non-winner stored as a lead, a NULL
      lead;
    * persons on some faces, ``learned_scores`` rows that count (global) and rows that must not
      (per-user, per-category).
    """
    rng = random.Random(seed)
    init_database(db_path)
    start = datetime(2024, 5, 1, 10, 0, 0)

    rows = []   # dicts

    def stale():
        return {
            'is_burst_lead': rng.choice([None, 0, 1]),
            'burst_group_id': rng.choice([None, None, None, 0, 1, 2, 3, 7, 30, 999]),
        }

    def frame(path, when, phash, **kw):
        row = {
            'path': path, 'date_taken': when, 'phash': phash,
            'aggregate': rng.choice([5.0, 6.0, 6.0, 7.0]),
            'face_count': rng.choice([0, 1, 1, 2]),
            'eyes_open_score': rng.choice([None, 3.0, 9.0]),
            'expression_score': rng.choice([None, 5.0, 8.0]),
            'tech_sharpness': rng.choice([None, 5.0, 7.0]),
        }
        row.update(stale())
        row.update(kw)
        rows.append(row)
        return row

    for c in range(100):
        base = start + timedelta(seconds=c * 400)
        base_hash = rng.getrandbits(64)
        ts = base
        for k in range(rng.choice([1, 2, 2, 3])):
            ts = ts + timedelta(seconds=rng.choice([0, 1, 3, 9, 20]) if k else 0)
            when = ts.strftime('%Y:%m:%d %H:%M:%S')
            for f in range(3 if rng.random() < 0.6 else rng.choice([1, 2])):
                kind = rng.random()
                if kind < 0.70:
                    bits = rng.sample(range(64), rng.choice([0, 0, 1, 2, 4, 6]))
                elif kind < 0.85:
                    bits = rng.sample(range(64), rng.choice([22, 26, 30]))
                else:
                    bits = rng.sample(range(64), 44)
                frame(f"/lib/c{c:03d}/t{k}f{f}.jpg", when, _hex(_flip(base_hash, bits)))

    # A cluster where EVERYTHING ties: only the pinned order decides the winner.
    tie_hash = _hex(rng.getrandbits(64))
    for f in range(3):
        frame(f"/lib/alltie/f{f}.jpg", '2024:08:01 09:00:00', tie_hash,
              aggregate=6.0, face_count=0, eyes_open_score=None, expression_score=None,
              tech_sharpness=None)

    # Not-quite-dates. The same phash on all of them: only the date handling separates them.
    odd_hash = _hex(rng.getrandbits(64))
    for n in range(6):
        frame(f"/lib/nodate/{n}.jpg", None, odd_hash)
    for n in range(3):
        frame(f"/lib/baddate/{n}.jpg", 'not a date', odd_hash)
    frame("/lib/iso/0.jpg", '2024-05-01T10:00:00', _hex(rng.getrandbits(64)))
    frame("/lib/iso/1.jpg", '2024-05-01T10:00:00', _hex(rng.getrandbits(64)))
    frame("/lib/emptyphash/0.jpg", '2024:05:01 10:00:00', '')

    # No phash: stand outside the grouping, keep their stored group id.
    for n in range(15):
        frame(f"/lib/nophash/{n}.jpg", rng.choice([None, '2024:05:01 10:00:00']), None,
              is_burst_lead=rng.choice([None, 0, 1]), burst_group_id=rng.choice([None, 7, 12]))

    rng.shuffle(rows)       # rowid order must not follow path or date order

    conn = sqlite3.connect(db_path)
    try:
        for i, row in enumerate(rows):
            cols = list(row)
            conn.execute(
                f"INSERT INTO photos (filename, {', '.join(cols)}) "
                f"VALUES (?, {', '.join('?' * len(cols))})",
                (f"{i}.jpg", *row.values()),
            )
        if with_faces:
            emb = np.zeros(512, dtype=np.float32).tobytes()
            for row in rows:
                if row['phash'] and rng.random() < 0.35:
                    for fi in range(rng.choice([1, 1, 2])):
                        conn.execute(
                            "INSERT INTO faces (photo_path, face_index, embedding, person_id) "
                            "VALUES (?, ?, ?, ?)",
                            (row['path'], fi, emb, rng.choice([1, 2, 3, None])),
                        )
        if with_learned:
            for row in rows:
                if row['phash'] and rng.random() < 0.3:
                    user, category = rng.choice([(None, None)] * 3 + [('alice', None), (None, 'portrait')])
                    conn.execute(
                        "INSERT INTO learned_scores (photo_path, learned_score, user_id, category) "
                        "VALUES (?, ?, ?, ?)",
                        (row['path'], rng.choice([2.0, 5.0, 9.5]), user, category),
                    )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _stored(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {p: (lead, gid) for p, lead, gid in
                conn.execute("SELECT path, is_burst_lead, burst_group_id FROM photos")}
    finally:
        conn.close()


def _settings():
    burst = ScoringConfig(defaults_path()).get_burst_detection_settings()
    pct = burst.get('similarity_threshold_percent', 88)
    return (int(64 * (1 - pct / 100)),
            burst.get('time_window_minutes', 60),
            burst.get('rapid_burst_seconds', 5))


class _Recorder:
    def __init__(self):
        self.events = []

    def emit(self, name, payload):
        self.events.append((name, payload))


@pytest.fixture
def recorder(monkeypatch):
    import plugins
    rec = _Recorder()
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: rec)
    return rec


PARITY_CASES = [
    pytest.param(1, True, True, id="seed1-faces-learned"),
    pytest.param(2, True, True, id="seed2-faces-learned"),
    pytest.param(3, False, False, id="seed3-no-faces-no-learned"),
]


@pytest.mark.parametrize("seed, with_faces, with_learned", PARITY_CASES)
def test_burst_state_and_events_match_the_head_grouping(
        tmp_path, recorder, caplog, seed, with_faces, with_learned):
    db_path = str(tmp_path / "burst.db")
    count = _build_library(db_path, seed, with_faces, with_learned)
    assert count >= 350

    # The oracle's row order is the plan the Python pin was derived from.
    assert any(HEAD_ORDER_PLAN in line for line in head_order_plan(db_path)), head_order_plan(db_path)

    max_hamming, window, rapid = _settings()
    expected, expected_events, expected_groups = reference_bursts(db_path, max_hamming, window, rapid)
    before = _stored(db_path)
    assert expected_groups > 40, "fixture too tame: it must produce many groups"
    assert len({gid for _lead, gid in expected.values() if gid is not None}) == expected_groups

    with caplog.at_level(logging.INFO):
        process_bursts(db_path, config_path=defaults_path())

    after = _stored(db_path)
    mismatches = {p: (before[p], after[p], expected[p]) for p in expected if after[p] != expected[p]}
    assert not mismatches, f"{len(mismatches)} rows differ from HEAD, first: {list(mismatches.items())[:3]}"
    assert [payload for _name, payload in recorder.events] == expected_events
    assert {name for name, _payload in recorder.events} == {'on_burst_detected'}

    # The log line counts exactly the rows whose stored pair was wrong.
    expected_changed = sum(1 for p in expected if before[p] != expected[p])
    assert expected_changed > 0
    assert f"Burst state: {expected_changed} rows changed" in caplog.text
    assert f"Assigned {expected_groups} burst groups" in caplog.text


def test_fixture_exercises_the_cases_it_claims(tmp_path):
    """The parity test only bites if the data has these shapes: assert it does."""
    db_path = str(tmp_path / "burst.db")
    _build_library(db_path, 1)
    max_hamming, window, rapid = _settings()
    state, events, _ = reference_bursts(db_path, max_hamming, window, rapid)
    before = _stored(db_path)

    conn = sqlite3.connect(db_path)
    try:
        same_ts = conn.execute(
            "SELECT COUNT(*) FROM (SELECT date_taken FROM photos WHERE phash IS NOT NULL "
            "AND date_taken IS NOT NULL GROUP BY date_taken HAVING COUNT(*) >= 3)"
        ).fetchone()[0]
        null_dates = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE phash IS NOT NULL AND date_taken IS NULL").fetchone()[0]
        nophash = dict(conn.execute("SELECT path, burst_group_id FROM photos WHERE phash IS NULL"))
    finally:
        conn.close()
    assert same_ts >= 30
    assert null_dates >= 6
    # NULL-phash rows: leads forced to 1, stored group id kept.
    assert nophash and all(state[p] == (1, gid) for p, gid in nophash.items())
    # Stale state of every kind is present before the run and gone after the reference.
    assert any(lead is None for lead, _ in before.values())
    assert any(lead == 1 and state[p][0] == 0 for p, (lead, _) in before.items() if p not in nophash)
    live_ids = {gid for _, gid in state.values() if gid is not None}
    assert any(gid is not None and gid not in live_ids for gid in
               (g for p, (_, g) in before.items() if p not in nophash))
    assert any(len(e['paths']) >= 3 for e in events)


def test_second_run_in_isolation_writes_nothing(tmp_path, recorder, caplog):
    db_path = str(tmp_path / "burst.db")
    _build_library(db_path, 2)
    process_bursts(db_path, config_path=defaults_path())
    settled = _stored(db_path)

    observer = sqlite3.connect(db_path)
    try:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        recorder.events.clear()
        caplog.clear()
        with caplog.at_level(logging.INFO):
            process_bursts(db_path, config_path=defaults_path())
        # data_version moves when ANOTHER connection commits a change to the file.
        assert observer.execute("PRAGMA data_version").fetchone()[0] == version
    finally:
        observer.close()

    assert "Burst state: 0 rows changed" in caplog.text
    assert _stored(db_path) == settled
    # The events are a function of the grouping, not of what was written: they repeat.
    assert recorder.events


def test_a_row_that_leaves_its_group_is_written_back_to_null(tmp_path, recorder):
    """Two near-identical frames form a group; their stored state is then made stale in every
    direction. There is no blanket reset, so each stale field must be repaired by name."""
    db_path = str(tmp_path / "burst.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    rows = [
        # (path, date, phash, aggregate, stored lead, stored gid)
        ("/a.jpg", "2024:01:01 12:00:00", "ffff0000ffff0000", 7.0, 0, 5),         # winner stored as non-lead
        ("/b.jpg", "2024:01:01 12:00:00", "ffff0000ffff0000", 6.0, 1, 5),         # non-winner stored as lead
        ("/lone.jpg", "2024:03:03 12:00:00", "0123456789abcdef", 6.0, None, 999), # singleton in a dead group
        ("/nophash.jpg", "2024:01:01 12:00:00", None, 6.0, None, 42),
    ]
    for path, when, phash, agg, lead, gid in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, phash, aggregate, is_burst_lead, burst_group_id) "
            "VALUES (?,?,?,?,?,?,?)", (path, path, when, phash, agg, lead, gid))
    conn.commit()
    conn.close()

    process_bursts(db_path, config_path=defaults_path())
    assert _stored(db_path) == {
        "/a.jpg": (1, 0),
        "/b.jpg": (0, 0),
        "/lone.jpg": (1, None),         # the dead group id is cleared, not left behind
        "/nophash.jpg": (1, 42),        # a phash-less row keeps whatever group id it had
    }


def test_a_library_without_a_single_phash_is_left_untouched(tmp_path, recorder, caplog):
    db_path = str(tmp_path / "burst.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for n, lead in enumerate([None, 0, 1]):
        conn.execute("INSERT INTO photos (path, filename, is_burst_lead, burst_group_id) VALUES (?,?,?,?)",
                     (f"/p{n}.jpg", f"p{n}.jpg", lead, 9))
    conn.commit()
    conn.close()
    before = _stored(db_path)

    with caplog.at_level(logging.INFO):
        process_bursts(db_path, config_path=defaults_path())

    assert _stored(db_path) == before          # HEAD returned before any reset
    assert "Burst state" not in caplog.text
    assert recorder.events == []


# --------------------------------------------------------------------------------------
# Plan guards on the PRODUCTION statement
# --------------------------------------------------------------------------------------

def _plan(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql)]
    finally:
        conn.close()


def _main_scan(plan):
    return [line for line in plan if line.startswith(("SCAN photos", "SEARCH photos"))]


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < MIN_COVERING_SQLITE,
    reason=f"SQLite {sqlite3.sqlite_version} is older than {MIN_COVERING_SQLITE}: the planner "
           "does not answer this read from idx_post_scan alone")
def test_burst_read_is_a_covering_scan_of_idx_post_scan(tmp_path):
    db_path = str(tmp_path / "burst.db")
    _build_library(db_path, 1, with_faces=False, with_learned=False)

    plan = _plan(db_path, _BURST_ROWS_SQL)
    scan = _main_scan(plan)
    assert scan == ["SCAN photos USING COVERING INDEX idx_post_scan"], plan

    # Control: without the index the same SQL is no longer a covering read, so the assertion
    # above can fail.
    conn = sqlite3.connect(db_path)
    conn.execute("DROP INDEX idx_post_scan")
    conn.commit()
    conn.close()
    control = _main_scan(_plan(db_path, _BURST_ROWS_SQL))
    assert control and "idx_post_scan" not in control[0], control
    assert "COVERING INDEX" not in control[0], control


def test_head_burst_statement_still_plans_the_pinned_order(tmp_path):
    """The Python tie order is the order of this plan (NULL dates first, equal dates by
    DESCENDING rowid). Any other plan means the pin no longer reproduces HEAD: stop.

    The oracle names the index with ``INDEXED BY`` (an older planner picks another one), so
    this guards the walk itself: an index scan in that order, never a temp B-tree sort."""
    db_path = str(tmp_path / "burst.db")
    _build_library(db_path, 1, with_faces=False, with_learned=False)
    plan = head_order_plan(db_path)
    assert HEAD_ORDER_PLAN in plan[0], plan


def test_burst_embedding_cosine_gate_splits_false_phash_matches(tmp_path):
    """Incidental pHash matches within the time window stay separate when embeddings diverge."""
    from utils.embedding import embedding_to_bytes

    db_path = str(tmp_path / "burst_cos.db")
    init_database(db_path)
    emb_a = embedding_to_bytes(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
    emb_b = embedding_to_bytes(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, phash, clip_embedding, aggregate) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("/a.jpg", "a.jpg", "2024:05:01 10:00:00", "0" * 16, emb_a, 7.0),
        )
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, phash, clip_embedding, aggregate) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("/b.jpg", "b.jpg", "2024:05:01 10:00:05", "0" * 16, emb_b, 8.0),
        )
        conn.commit()
    finally:
        conn.close()

    cfg_path = tmp_path / "burst_config.json"
    cfg_path.write_text(json.dumps({
        "burst_detection": {
            "similarity_threshold_percent": 70,
            "time_window_minutes": 0.8,
            "rapid_burst_seconds": 0.4,
            "embedding_cosine_threshold": 0.75,
        }
    }), encoding="utf-8")

    process_bursts(db_path, config_path=str(cfg_path))

    stored = _stored(db_path)
    assert stored["/a.jpg"] == (1, None)
    assert stored["/b.jpg"] == (1, None)


@pytest.mark.parametrize("emb_b", [
    None,
    np.array([0.0, 1.0, 0.0], dtype=np.float32),
], ids=["missing", "other-dimension"])
def test_burst_embedding_cosine_gate_stays_open_when_a_pair_is_not_comparable(tmp_path, emb_b):
    """A photo with no embedding, or one of another width, is grouped on pHash alone."""
    from utils.embedding import embedding_to_bytes

    db_path = str(tmp_path / "burst_cos_open.db")
    init_database(db_path)
    emb_a = embedding_to_bytes(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
    blob_b = None if emb_b is None else embedding_to_bytes(emb_b)
    conn = sqlite3.connect(db_path)
    try:
        for path, date, emb, aggregate in (
            ("/a.jpg", "2024:05:01 10:00:00", emb_a, 7.0),
            ("/b.jpg", "2024:05:01 10:00:05", blob_b, 8.0),
        ):
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, phash, clip_embedding, aggregate) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (path, path[1:], date, "0" * 16, emb, aggregate),
            )
        conn.commit()
    finally:
        conn.close()
    cfg_path = tmp_path / "burst_config.json"
    cfg_path.write_text(json.dumps({"burst_detection": {
        "similarity_threshold_percent": 70, "time_window_minutes": 0.8,
        "rapid_burst_seconds": 0.4, "embedding_cosine_threshold": 0.75,
    }}), encoding="utf-8")
    process_bursts(db_path, config_path=str(cfg_path))
    stored = _stored(db_path)
    assert stored["/a.jpg"][1] is not None and stored["/a.jpg"][1] == stored["/b.jpg"][1]
    assert (stored["/a.jpg"][0], stored["/b.jpg"][0]) == (0, 1)
