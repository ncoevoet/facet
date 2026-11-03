"""``--recompute-iqa`` streams: pending rowids first, then one decoded batch at a time.

Torch-free: scorers are deterministic stubs, every schema comes from ``init_database``.
The helpers are small private copies of the idiom in ``test_recompute_iqa_unscorable.py``
because this module needs a PRIVATE database (tracemalloc isolation, a second connection
mutating rows mid-pass); ``seeded_photos`` writes into the shared session DB.

A stub cannot prove that real models score identically across batch compositions; that
is the GPU dump comparison done outside the suite.
"""

import contextlib
import math
import tracemalloc
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageStat

import processing.scorer as scorer_mod
from db import get_connection
from db.schema import init_database

_SCANNED = '2026-01-01 00:00:00'
_COLS = ('aesthetic_iaa', 'face_quality_iqa', 'liqe_score')
_MODEL_COL = {'topiq_iaa': 'aesthetic_iaa', 'topiq_nr_face': 'face_quality_iqa',
              'liqe': 'liqe_score'}
_DECLINE_WIDTH, _NONE_WIDTH = 301, 302  # the face stub declines / returns None for these widths


def _jpeg(size=(300, 300), colour=(120, 130, 140)):
    buf = BytesIO()
    Image.new('RGB', size, colour).save(buf, 'JPEG')
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(scorer_mod, 'tqdm', lambda it, **kw: it)


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "iqa.db")
    init_database(path)
    return path


def _insert(db_path, rows):
    with get_connection(db_path, row_factory=False) as conn:
        for row in rows:
            cols = list(row)
            conn.execute(
                f"INSERT INTO photos ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [row[c] for c in cols])
        conn.commit()


def _exec(db_path, sql, params=()):
    with get_connection(db_path, row_factory=False) as conn:
        conn.execute(sql, params)
        conn.commit()


def _photo(n, **extra):
    row = {'path': f'/p{n:04d}.jpg', 'filename': f'p{n:04d}.jpg',
           'thumbnail': _jpeg(colour=(10 + n % 200, 90, 40)), 'face_count': 1,
           'scanned_at': _SCANNED}
    row.update(extra)
    return row


def _state(db_path):
    with get_connection(db_path, row_factory=False) as conn:
        scores = conn.execute(
            "SELECT path, aesthetic_iaa, face_quality_iqa, liqe_score FROM photos ORDER BY path"
        ).fetchall()
        declines = conn.execute(
            "SELECT photo_path, model, scan_fingerprint FROM iqa_declined "
            "ORDER BY photo_path, model").fetchall()
        # Everything the pass must not touch.
        other = conn.execute(
            "SELECT path, filename, face_count, scanned_at, thumbnail FROM photos ORDER BY path"
        ).fetchall()
    return scores, declines, other


class _Stub:
    """Deterministic scorer: the score is a function of the image alone."""

    def __init__(self, model, on_call=None, fail_on_call=None, unload_error=None):
        self.model = model
        self.calls = 0
        self.sizes = []
        self.unloaded = 0
        self.last_declined = set()
        self.on_call = on_call
        self.fail_on_call = fail_on_call
        self.unload_error = unload_error

    @staticmethod
    def value(model, img):
        offset = {'topiq_iaa': 0.0, 'topiq_nr_face': 1.0, 'liqe': 2.0}.get(model, 3.0)
        return img.size[0] / 7 + ImageStat.Stat(img).mean[0] / 50 + offset

    def score_batch(self, images):
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.fail_on_call == self.calls:
            raise KeyboardInterrupt
        self.sizes.append(len(images))
        self.last_declined = set()
        out = []
        for i, img in enumerate(images):
            if self.model == 'topiq_nr_face' and img.size[0] == _DECLINE_WIDTH:
                self.last_declined.add(i)
                out.append(None)
            elif self.model == 'topiq_nr_face' and img.size[0] == _NONE_WIDTH:
                out.append(None)
            else:
                out.append(self.value(self.model, img))
        return out

    def unload(self):
        self.unloaded += 1
        if self.unload_error is not None:
            raise self.unload_error


def _facet(db_path, scorers):
    from processing.scorer import Facet
    facet = Facet.__new__(Facet)
    facet.db_path = db_path
    facet.config = SimpleNamespace(get_extended_iqa_settings=lambda: {})
    facet._make_iqa_scorer = lambda name: scorers[name]
    return facet


def _counters(columns=_COLS):
    return {'updated': {c: 0 for c in columns}, 'errors': 0, 'declined': 0, 'liqe_too_small': 0}


def _scorers(**kw):
    return {m: _Stub(m, **kw) for m in _MODEL_COL}


# ---------------------------------------------------------------------------
# Identity against an inline per-image oracle
# ---------------------------------------------------------------------------

def _mixed_rows():
    rows = [_photo(n) for n in range(1, 8)]
    rows.append(_photo(8, face_count=0))                                   # faceless
    rows.append(_photo(9, thumbnail=b'not an image'))                      # corrupt
    rows.append(_photo(10, thumbnail=None))                                # no thumbnail
    rows.append(_photo(11, thumbnail=_jpeg((100, 50))))                    # LIQE too small
    rows.append(_photo(12, thumbnail=_jpeg((_DECLINE_WIDTH, 300))))        # face model declines
    rows.append(_photo(13, thumbnail=_jpeg((_NONE_WIDTH, 300))))           # face model returns None
    rows.append(_photo(14))                                                # valid decline row
    rows.append(_photo(15))                                                # stale decline row
    rows.append(_photo(16, aesthetic_iaa=1.0, face_quality_iqa=2.0, liqe_score=3.0))  # all scored
    rows.append(_photo(17, aesthetic_iaa=1.0))                             # partly scored
    rows.append(_photo(18, thumbnail=_jpeg((_DECLINE_WIDTH, 310))))        # second decline, same batch
    return rows


def _seed_mixed(db_path):
    _insert(db_path, _mixed_rows())
    _exec(db_path, "INSERT INTO iqa_declined (photo_path, model, scan_fingerprint) "
                   "SELECT path, 'topiq_nr_face', scanned_at || '|' || length(thumbnail) "
                   "FROM photos WHERE path = '/p0014.jpg'")
    _exec(db_path, "INSERT INTO iqa_declined (photo_path, model, scan_fingerprint) "
                   "VALUES ('/p0015.jpg', 'topiq_nr_face', 'stale')")


def _oracle(db_path):
    """Expected end state, computed per image in rowid order with no batching."""
    with get_connection(db_path, row_factory=False) as conn:
        rows = conn.execute(
            "SELECT path, thumbnail, face_count, aesthetic_iaa, face_quality_iqa, liqe_score, "
            "scanned_at || '|' || length(thumbnail), "
            "EXISTS (SELECT 1 FROM iqa_declined d WHERE d.photo_path = photos.path "
            "AND d.model = 'topiq_nr_face' "
            "AND d.scan_fingerprint = photos.scanned_at || '|' || length(photos.thumbnail)) "
            "FROM photos ORDER BY rowid").fetchall()
        old_declines = conn.execute(
            "SELECT photo_path, model, scan_fingerprint FROM iqa_declined").fetchall()
    scores, declines = {}, {(p, m): f for p, m, f in old_declines}
    errors = declined = liqe_small = 0
    updated = {c: 0 for c in _COLS}
    for path, blob, faces, iaa, face, liqe, fp, has_decline in rows:
        scores[path] = {'aesthetic_iaa': iaa, 'face_quality_iqa': face, 'liqe_score': liqe}
        if blob is None:
            continue
        needs = []
        if iaa is None:
            needs.append('aesthetic_iaa')
        if face is None and (faces or 0) > 0 and not has_decline:
            needs.append('face_quality_iqa')
        if liqe is None:
            needs.append('liqe_score')
        if not needs:
            continue
        try:
            img = Image.open(BytesIO(blob))
            img.load()
        except Exception:
            errors += 1
            continue
        if 'liqe_score' in needs and min(img.size) < 224:
            liqe_small += 1
            needs.remove('liqe_score')
        img = img.convert('RGB')
        for col in needs:
            model = next(m for m, c in _MODEL_COL.items() if c == col)
            if model == 'topiq_nr_face' and img.size[0] == _DECLINE_WIDTH:
                declines[(path, model)] = fp
                declined += 1
            elif model == 'topiq_nr_face' and img.size[0] == _NONE_WIDTH:
                pass
            else:
                scores[path][col] = round(_Stub.value(model, img), 2)
                updated[col] += 1
    return scores, sorted((p, m, f) for (p, m), f in declines.items()), {
        'updated': updated, 'errors': errors, 'declined': declined, 'liqe_too_small': liqe_small}


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize("batch_size", [1, 3, 64])
def test_streamed_pass_equals_per_image_oracle(db, monkeypatch, batch_size, workers):
    monkeypatch.setattr(scorer_mod, '_IQA_DECODE_WORKERS', workers)
    _seed_mixed(db)
    before = _state(db)
    exp_scores, exp_declines, exp_counters = _oracle(db)
    counters = _counters()

    _facet(db, _scorers())._run_iqa_pass(list(_MODEL_COL), batch_size, counters)

    scores, declines, other = _state(db)
    assert {p: dict(zip(_COLS, vals)) for p, *vals in scores} == exp_scores
    assert declines == exp_declines
    assert counters == exp_counters
    assert other == before[2]  # thumbnails and every other column untouched
    assert exp_counters['errors'] == 1 and exp_counters['liqe_too_small'] == 1  # the fixture bites
    assert exp_counters['declined'] == 2  # two declines in one batch: counted per row


def test_batches_follow_rowid_order_and_batch_size(db):
    _insert(db, [_photo(n) for n in range(1, 8)])
    scorers = _scorers()
    _facet(db, scorers)._run_iqa_pass(['topiq_iaa'], 3, _counters())
    assert scorers['topiq_iaa'].sizes == [3, 3, 1]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def _build_pending_db(path, n):
    init_database(path)
    buf = BytesIO()
    Image.new('RGB', (16, 16)).save(buf, 'JPEG', comment=b'x' * 8000)
    blob = buf.getvalue()
    with get_connection(path, row_factory=False) as conn:
        conn.executemany(
            "INSERT INTO photos (path, filename, thumbnail, face_count, scanned_at) "
            "VALUES (?, ?, ?, 1, ?)",
            ((f'/m{i:06d}.jpg', f'm{i}.jpg', blob, _SCANNED) for i in range(n)))
        conn.commit()
    return len(blob) * n


class _ConstScorer:
    last_declined = frozenset()

    def score_batch(self, images):
        return [5.0] * len(images)

    def unload(self):
        pass


def _peak_bytes(path):
    facet = _facet(path, {'topiq_iaa': _ConstScorer()})
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        facet._run_iqa_pass(['topiq_iaa'], 64, _counters(('aesthetic_iaa',)))
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_peak_python_memory_is_flat_in_pending_rows(tmp_path):
    small, large = str(tmp_path / "2k.db"), str(tmp_path / "10k.db")
    _build_pending_db(small, 2000)
    blobs_10k = _build_pending_db(large, 10000)

    peak_2k, peak_10k = _peak_bytes(small), _peak_bytes(large)

    assert peak_10k < 0.15 * blobs_10k, (peak_10k, blobs_10k)
    assert peak_10k <= 1.5 * peak_2k + (1 << 20), (peak_2k, peak_10k)
    with get_connection(large, row_factory=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE aesthetic_iaa IS NULL"
                            ).fetchone()[0] == 0


def test_thumbnails_are_only_read_by_the_per_batch_fetch(db, monkeypatch):
    _insert(db, [_photo(n) for n in range(1, 8)])
    statements = []
    real = scorer_mod.get_connection

    @contextlib.contextmanager
    def traced(*a, **kw):
        with real(*a, **kw) as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(scorer_mod, 'get_connection', traced)
    _facet(db, _scorers())._run_iqa_pass(['topiq_iaa'], 3, _counters())

    selects = [s for s in statements if s.lstrip().upper().startswith('SELECT')]
    reading = [s for s in selects if 'THUMBNAIL' in s.upper().split(' FROM ')[0]]
    assert len(reading) == math.ceil(7 / 3)
    assert all('rowid IN' in s for s in reading)
    assert any('SELECT rowid FROM photos' in s for s in selects)


# ---------------------------------------------------------------------------
# Rows that change between the pre-select and their batch's fetch
# ---------------------------------------------------------------------------

def _mid_pass(db_path, sql):
    done = []

    def hook(call):
        if not done:  # first score_batch: the pass has not written yet, so no lock is held
            done.append(True)
            _exec(db_path, sql)
    return hook


@pytest.mark.parametrize("sql", [
    "DELETE FROM photos WHERE path = '/p0004.jpg'",
    "UPDATE photos SET thumbnail = NULL WHERE path = '/p0004.jpg'",
])
def test_row_gone_before_its_batch_is_dropped_silently(db, sql):
    _insert(db, [_photo(n) for n in range(1, 6)])
    scorers = {'topiq_iaa': _Stub('topiq_iaa', on_call=_mid_pass(db, sql))}
    counters = _counters(('aesthetic_iaa',))

    _facet(db, scorers)._run_iqa_pass(['topiq_iaa'], 2, counters)

    scores = {p: a for p, a, *_ in _state(db)[0]}
    assert scores['/p0001.jpg'] is not None and scores['/p0005.jpg'] is not None
    assert scores.get('/p0004.jpg') is None
    assert counters['errors'] == 0
    assert counters['updated']['aesthetic_iaa'] == 4


def test_row_scored_elsewhere_before_its_batch_is_not_rescored(db):
    _insert(db, [_photo(n) for n in range(1, 6)])
    hook = _mid_pass(db, "UPDATE photos SET aesthetic_iaa = 9.5 WHERE path = '/p0005.jpg'")
    scorers = {'topiq_iaa': _Stub('topiq_iaa', on_call=hook)}

    _facet(db, scorers)._run_iqa_pass(['topiq_iaa'], 2, _counters(('aesthetic_iaa',)))

    scores = {p: a for p, a, *_ in _state(db)[0]}
    assert scores['/p0005.jpg'] == 9.5
    assert sum(scorers['topiq_iaa'].sizes) == 4


# ---------------------------------------------------------------------------
# Interruption, errors and cleanup
# ---------------------------------------------------------------------------

def test_interrupt_keeps_committed_batches_unloads_and_resumes(db):
    _insert(db, [_photo(n) for n in range(1, 8)])
    scorer = _Stub('topiq_iaa', fail_on_call=3)

    with pytest.raises(KeyboardInterrupt):
        _facet(db, {'topiq_iaa': scorer})._run_iqa_pass(
            ['topiq_iaa'], 2, _counters(('aesthetic_iaa',)))

    done = {p: a for p, a, *_ in _state(db)[0]}
    assert [p for p, v in done.items() if v is not None] == [
        '/p0001.jpg', '/p0002.jpg', '/p0003.jpg', '/p0004.jpg']
    assert scorer.unloaded == 1

    resumed = _Stub('topiq_iaa')
    _facet(db, {'topiq_iaa': resumed})._run_iqa_pass(
        ['topiq_iaa'], 2, _counters(('aesthetic_iaa',)))
    assert sum(resumed.sizes) == 3

    ref_db = db + ".ref"
    init_database(ref_db)
    _insert(ref_db, [_photo(n) for n in range(1, 8)])
    _facet(ref_db, {'topiq_iaa': _Stub('topiq_iaa')})._run_iqa_pass(
        ['topiq_iaa'], 2, _counters(('aesthetic_iaa',)))
    assert _state(db)[0] == _state(ref_db)[0]


class _Boom(_Stub):
    def score_batch(self, images):
        raise ValueError("original")


def test_unload_error_does_not_hide_the_original_error_nor_skip_other_unloads(db):
    _insert(db, [_photo(1)])
    scorers = {
        'topiq_iaa': _Stub('topiq_iaa', unload_error=RuntimeError("unload boom")),
        'liqe': _Boom('liqe'),
    }

    with pytest.raises(ValueError, match="original"):
        _facet(db, scorers)._run_iqa_pass(['topiq_iaa', 'liqe'], 4, _counters())

    assert scorers['topiq_iaa'].unloaded == 1 and scorers['liqe'].unloaded == 1


def test_model_load_failure_unloads_the_models_already_loaded(db):
    _insert(db, [_photo(1)])
    first = _Stub('topiq_iaa')
    facet = _facet(db, {})

    def make(name):
        if name == 'topiq_iaa':
            return first
        raise RuntimeError("out of memory")
    facet._make_iqa_scorer = make

    with pytest.raises(RuntimeError, match="out of memory"):
        facet._run_iqa_pass(['topiq_iaa', 'liqe'], 4, _counters())

    assert first.unloaded == 1


def test_unexpected_decode_worker_error_aborts_the_pass_and_unloads(db, monkeypatch):
    _insert(db, [_photo(n) for n in range(1, 4)])

    def boom(blob, cols):
        raise RuntimeError("decoder bug")
    monkeypatch.setattr(scorer_mod, '_decode_iqa_thumbnail', boom)
    scorer = _Stub('topiq_iaa')

    with pytest.raises(RuntimeError, match="decoder bug"):
        _facet(db, {'topiq_iaa': scorer})._run_iqa_pass(
            ['topiq_iaa'], 2, _counters(('aesthetic_iaa',)))

    assert scorer.unloaded == 1
    assert all(a is None for _, a, *_ in _state(db)[0])


def test_nothing_pending_unloads_and_returns(db):
    _insert(db, [_photo(1, aesthetic_iaa=4.0)])
    scorer = _Stub('topiq_iaa')
    _facet(db, {'topiq_iaa': scorer})._run_iqa_pass(
        ['topiq_iaa'], 4, _counters(('aesthetic_iaa',)))
    assert scorer.calls == 0 and scorer.unloaded == 1
