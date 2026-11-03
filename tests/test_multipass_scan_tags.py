"""A multi-pass scan tags from the embedding BEFORE category and aggregate are computed.

On a CLIP-similarity profile (legacy/8gb, and 16gb/24gb when the VLM tagger is
not scheduled) ``tags`` used to arrive only in the post-scan step, so the
scan-time category and aggregate were computed with ``tags=''`` and disagreed
with ``--recompute-average`` on every tag-driven category. ``_pass_clip`` now
tags from the embeddings it just computed, while the model is still loaded.
"""

from pathlib import Path
from unittest import mock

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("cv2")
pytest.importorskip("imagehash")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from db import get_connection, init_database  # noqa: E402
from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402
from processing.scorer import Facet, _load_image_modules  # noqa: E402

_load_image_modules()

# Tag-only categories (no other filter), so the tag alone decides the category.
CATEGORY_TAGS = ('concert', 'vehicle', 'architecture')


class _FakeModelManager:
    device = 'cpu'

    def __init__(self, clip_config=None):
        self._clip_config = clip_config or {'model_name': 'ViT-L-14', 'backend': 'open_clip'}

    def detect_vram(self):
        return 0.0

    def get_clip_config(self):
        return self._clip_config


class _OneHotClip:
    """An image tower whose embedding for image k is the one-hot of tag k's axis."""

    def __init__(self, dim, axis_for_image):
        self.dim = dim
        self.axis_for_image = axis_for_image  # id(PIL image) -> axis

    def preprocess(self, img):
        return torch.tensor([float(self.axis_for_image[id(img)])])

    def encode_image(self, inputs):
        out = torch.zeros((inputs.shape[0], self.dim))
        for row, axis in enumerate(inputs[:, 0].long().tolist()):
            out[row, axis] = 1.0
        return out


def _config():
    from config.scoring_config import ScoringConfig
    from config_resolve import defaults_path

    cfg = ScoringConfig(defaults_path(), validate=False)
    cfg.config['models']['vram_profile'] = '8gb'  # never probe the real GPU
    return cfg


def _text_matrix_for(cfg):
    """encode_text_prompts stand-in: every prompt of tag j is the unit vector e_j."""
    vocab = cfg.get_tag_vocabulary()
    names = list(vocab)
    axis = {name: i for i, name in enumerate(names)}
    rows = [axis[name] for name, descs in vocab.items() for _ in descs]

    def encode(_model, _model_name, _backend, _device, texts):
        assert len(texts) == len(rows)
        matrix = torch.zeros((len(rows), len(names)))
        for r, a in enumerate(rows):
            matrix[r, a] = 1.0
        return matrix

    return encode, axis, len(names)


@pytest.fixture()
def scan(tmp_path):
    """A real Facet (save path + aggregate logic) over a real-schema DB, plus decoded images."""
    cfg = _config()
    db = str(tmp_path / 'scan.db')
    init_database(db)
    facet = Facet.__new__(Facet)
    facet._pending_centroid_persons = set()
    facet.db_path = db
    facet.config = cfg
    facet.aesthetic_head = None

    rng = np.random.default_rng(7)
    paths = []
    for i in range(len(CATEGORY_TAGS)):
        arr = rng.integers(40, 200, (96, 128, 3), dtype=np.uint8)
        path = tmp_path / f'img{i}.jpg'
        Image.fromarray(arr).save(path, quality=90)
        paths.append(str(path))
    return cfg, facet, db, paths


def _processor(facet, pass_groups, manager=None, restricted=False):
    with mock.patch('processing.multi_pass._ensure_imports'):
        proc = ChunkedMultiPassProcessor(
            scorer=facet, model_manager=manager or _FakeModelManager(),
            config={'processing': {'load_workers': 1}},
        )
    proc.pass_groups = pass_groups
    proc.restricted = restricted
    return proc


def _load(proc, paths):
    with mock.patch('exiftool.get_exif_batch', return_value={}):
        return proc._load_images(paths)


def _clip_model_dict(cfg, images, tags=CATEGORY_TAGS):
    encode, axis, dim = _text_matrix_for(cfg)
    model = _OneHotClip(dim, {id(images[p]['pil']): axis[t] for p, t in zip(sorted(images), tags)})
    return {'model': model, 'preprocess': model.preprocess, 'backend': 'open_clip'}, encode


def _run_clip_pass(proc, cfg, images, results):
    model_dict, encode = _clip_model_dict(cfg, images)
    with mock.patch('models.tagger.encode_text_prompts', encode):
        proc._pass_clip(model_dict, images, results)
    return model_dict


def test_clip_profile_scan_category_matches_stored_tags(scan):
    cfg, facet, db, paths = scan
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    results = {p: {} for p in paths}

    _run_clip_pass(proc, cfg, images, results)
    proc._compute_aggregates(results, images)
    proc._save_results(results, images)
    assert proc.metrics['photos_saved'] == len(paths)   # the full save counts what it wrote

    with get_connection(db, row_factory=True) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT path, tags, category, face_count, face_ratio, is_silhouette, "
            "is_group_portrait, is_monochrome, mean_luminance, iso, shutter_speed, "
            "focal_length, f_stop FROM photos ORDER BY path")]
    assert len(rows) == len(paths)

    untagged_categories = set()
    for row, expected_tag in zip(rows, CATEGORY_TAGS):
        assert row['tags'] == expected_tag
        # What --recompute-average derives from the STORED row.
        assert row['category'] == facet._determine_photo_category(row, cfg)
        assert row['category'] == expected_tag
        untagged_categories.add(facet._determine_photo_category(dict(row, tags=''), cfg))
    assert not untagged_categories & set(CATEGORY_TAGS)  # the tags are what decided it


def test_vlm_scheduled_leaves_tags_to_the_vlm(scan):
    cfg, facet, _db, paths = scan
    proc = _processor(facet, [['clip'], ['qwen3_5_tagger']])
    images = _load(proc, paths)
    results = {p: {} for p in paths}
    _run_clip_pass(proc, cfg, images, results)
    assert all('clip_embedding' in r and 'tags' not in r for r in results.values())


def test_restricted_pass_writes_no_tags(scan):
    cfg, facet, _db, paths = scan
    proc = _processor(facet, [['clip']], restricted=True)
    images = _load(proc, paths)
    results = {p: {} for p in paths}
    _run_clip_pass(proc, cfg, images, results)
    assert all('tags' not in r for r in results.values())


def test_tagging_disabled_writes_no_tags(scan):
    cfg, facet, _db, paths = scan
    cfg.config['tagging']['enabled'] = False
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    results = {p: {} for p in paths}
    _run_clip_pass(proc, cfg, images, results)
    assert all('tags' not in r for r in results.values())


def test_cached_tagger_holds_no_model(scan):
    cfg, facet, _db, paths = scan
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    model_dict, encode = _clip_model_dict(cfg, images)

    with mock.patch('models.tagger.encode_text_prompts', side_effect=encode) as spy:
        proc._pass_clip(model_dict, images, {p: {} for p in paths})
        first = proc._clip_tagger
        second_results = {p: {} for p in paths}
        proc._pass_clip(model_dict, images, second_results)

    assert first.model is None
    assert proc._clip_tagger is first
    assert spy.call_count == 1  # the vocabulary is encoded once per scan, not per chunk
    assert [second_results[p]['tags'] for p in paths] == list(CATEGORY_TAGS)


def test_dim_mismatch_embedding_is_skipped_not_fatal(scan):
    """A 768 text tower against the 1152-dim embeddings: no tag, no exception, counted."""
    cfg, facet, _db, paths = scan
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    model_dict, encode = _clip_model_dict(cfg, images)

    def encode_768(*args):
        return torch.ones((encode(*args).shape[0], 768)) / 768 ** 0.5

    model_dict['model'].dim = 1152
    results = {p: {} for p in paths}
    with mock.patch('models.tagger.encode_text_prompts', encode_768):
        proc._pass_clip(model_dict, images, results)

    assert all(r['tags'] is None and r['clip_embedding'] for r in results.values())
    assert proc._clip_tagger.skipped_dim_mismatch == len(paths)


def test_tagger_build_failure_does_not_fail_the_embedding_pass(scan):
    cfg, facet, _db, paths = scan
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    model_dict, _ = _clip_model_dict(cfg, images)
    results = {p: {} for p in paths}
    with mock.patch('models.tagger.encode_text_prompts', side_effect=RuntimeError('no tokenizer')):
        proc._pass_clip(model_dict, images, results)
    assert all(r['clip_embedding'] and 'tags' not in r for r in results.values())


def test_tagger_uses_the_loaded_profile_model_identity(scan):
    """The text tower comes from the model the pass loaded, named by the model manager."""
    cfg, facet, _db, paths = scan
    manager = _FakeModelManager({'model_name': 'google/siglip2-so400m-patch16-naflex',
                                 'backend': 'transformers'})
    proc = _processor(facet, [['clip']], manager=manager)
    images = _load(proc, paths)
    model_dict, encode = _clip_model_dict(cfg, images)
    model_dict['backend'] = 'open_clip'  # the loaded model's own backend wins
    seen = {}

    def spy(model, model_name, backend, device, texts):
        seen.update(model=model, model_name=model_name, backend=backend, device=device)
        return encode(model, model_name, backend, device, texts)

    with mock.patch('models.tagger.encode_text_prompts', spy):
        proc._pass_clip(model_dict, images, {p: {} for p in paths})
    assert seen == {'model': model_dict['model'],
                    'model_name': 'google/siglip2-so400m-patch16-naflex',
                    'backend': 'open_clip', 'device': 'cpu'}


def test_stored_tags_equal_the_post_scan_tagger_output(scan):
    """Same string tag_existing.tag_untagged_photos writes for the same embedding."""
    from tag_existing import tag_untagged_photos

    cfg, facet, db, paths = scan
    proc = _processor(facet, [['clip']])
    images = _load(proc, paths)
    results = {p: {} for p in paths}
    _run_clip_pass(proc, cfg, images, results)
    proc._compute_aggregates(results, images)
    proc._save_results(results, images)

    with get_connection(db, row_factory=False) as conn:
        scan_tags = dict(conn.execute("SELECT path, tags FROM photos").fetchall())
        conn.execute("UPDATE photos SET tags = NULL")  # untag; let the post-scan step redo it
        conn.commit()
    assert tag_untagged_photos(db, proc._clip_tagger, *_tag_params(cfg)) == len(paths)
    with get_connection(db, row_factory=False) as conn:
        assert dict(conn.execute("SELECT path, tags FROM photos").fetchall()) == scan_tags
    assert {str(Path(p).resolve()) for p in paths} == set(scan_tags)


def _tag_params(cfg):
    from utils.tags import get_tag_params

    return get_tag_params(cfg)
