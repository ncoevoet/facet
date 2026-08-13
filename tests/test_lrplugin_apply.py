"""Behavioral tests for ``facet.lrplugin/FacetApply.lua``, executed under a
real Lua interpreter (via ``lupa``) against a stubbed Lightroom SDK.

``tests/test_lr_manifest_contract.py`` covers the manifest *shape* contract
with regexes, since it cannot execute Lua at all. This suite is the
complement: it actually runs the plug-in's logic, so it needs a Lua runtime.
``lupa`` bundles one (no system Lua install required) -- when it is missing
the whole module is skipped rather than failed, since real-Lua verification
is a nice-to-have on top of the regex contract, not this repo's only gate.

The functions under test are declared ``local`` in FacetApply.lua -- deliberately
not exported, since Lightroom runs the file directly rather than ``require``-ing
it as a module. To reach them without changing that, the bottom of the file has
a test seam: if a ``FACET_APPLY_TEST_HOOKS`` global exists before the chunk
runs, it is filled in and the file returns before reaching its real entry
point (``LrFunctionContext.postAsyncTaskWithContext``). Lightroom itself never
sets that global, so production loads are unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

lupa = pytest.importorskip('lupa', reason='real-Lua verification needs the optional lupa package')

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / 'facet.lrplugin'
APPLY_LUA = PLUGIN_DIR / 'FacetApply.lua'

# `import 'LrX'` runs unconditionally at the top of FacetApply.lua, so every
# name it asks for has to resolve to *something*. Only LrTasks needs real
# behavior: buildPlan/applyPlan call `LrTasks.yield()` every chunk, and
# applyPlan wraps its write in `LrTasks.pcall(...)`, which the real SDK
# documents as a protected call -- Lua's own `pcall` is a faithful stand-in
# for what this suite exercises.
_BOOTSTRAP = """
function import(name)
    if name == 'LrTasks' then
        return {
            yield = function() end,
            pcall = function(fn) return pcall(fn) end,
            startAsyncTask = function(fn) return fn() end,
        }
    end
    return {}
end
FACET_APPLY_TEST_HOOKS = {}
package.path = package.path .. ';' .. %r

function facet_test_make_photo(path)
    local p = {}
    p.path = path
    p.written = {}
    p.setRawMetadata = function(self, key, value) self.written[key] = value end
    return p
end

function facet_test_make_failing_photo(path)
    local p = {}
    p.path = path
    p.setRawMetadata = function(self, key, value) error('boom') end
    return p
end

function facet_test_make_catalog(byPhoto)
    local c = {}
    c.batchGetRawMetadata = function(self, chunk, keys)
        local out = {}
        for _, photo in ipairs(chunk) do
            out[photo] = byPhoto[photo]
        end
        return out
    end
    return c
end

function facet_test_make_progress()
    return {
        isCanceled = function(self) return false end,
        setPortionComplete = function(self, done, total) end,
    }
end

function facet_test_make_logger()
    local logger = { misses = 0, lines = {} }
    logger.write = function(message) logger.lines[#logger.lines + 1] = message end
    return logger
end
""" % (str((PLUGIN_DIR / '?.lua').as_posix()))


@pytest.fixture(scope='module')
def lua():
    """A Lua runtime with FacetApply.lua loaded and its hooks exposed."""
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_BOOTSTRAP)
    runtime.execute(APPLY_LUA.read_text(encoding='utf-8'))
    return runtime


@pytest.fixture(scope='module')
def hooks(lua):
    hooks = lua.globals().FACET_APPLY_TEST_HOOKS
    assert hooks is not None, (
        'FacetApply.lua did not reach its FACET_APPLY_TEST_HOOKS seam -- '
        'the file structure changed in a way this suite needs updating for.'
    )
    return hooks


def _manifest(lua, photos):
    """Build a decoded-manifest Lua table from plain Python photo dicts."""
    return lua.table_from({'photos': lua.table_from(photos, recursive=True)}, recursive=True)


def _preferences(lua, overwrite=False):
    return lua.table_from(
        {'catalogPrefix': '', 'manifestPrefix': '', 'overwrite': overwrite}, recursive=True,
    )


class TestBuildIndexCollisionPoisoning:
    """Case-only path collisions must never let last-write-wins hand a
    lowercase fallback to the wrong photo (the finding this fix addresses)."""

    def test_no_collision_when_only_one_path_folds_to_a_key(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/only.jpg', 'star_rating': 4, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 0
        # The case-insensitive fallback still works when it is unambiguous.
        record = hooks.findRecord(index, '/LIB/ONLY.JPG')
        assert record is not None
        assert record.star_rating == 4

    def test_repeating_the_same_exact_path_is_not_a_case_collision(self, lua, hooks):
        # Two manifest rows for the identical (same-case) path are a data
        # quality issue, not the case-fold ambiguity this fix targets.
        manifest = _manifest(lua, [
            {'path': '/Lib/dup.jpg', 'star_rating': 3, 'is_favorite': False, 'is_rejected': False},
            {'path': '/Lib/dup.jpg', 'star_rating': 5, 'is_favorite': True, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 0
        assert index.count == 2

    def test_two_distinct_paths_differing_only_by_case_poison_the_slot(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/IMG_1.jpg', 'star_rating': 5, 'is_favorite': True, 'is_rejected': False},
            {'path': '/lib/img_1.jpg', 'star_rating': 2, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 1
        # Exact-case lookups are untouched by the collision -- each path
        # still resolves to its own record.
        assert hooks.findRecord(index, '/Lib/IMG_1.jpg').star_rating == 5
        assert hooks.findRecord(index, '/lib/img_1.jpg').star_rating == 2

    def test_findrecord_refuses_the_poisoned_fallback(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/IMG_1.jpg', 'star_rating': 5, 'is_favorite': True, 'is_rejected': False},
            {'path': '/lib/img_1.jpg', 'star_rating': 2, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        # A third casing that matches neither manifest entry exactly must
        # not silently fall back to either colliding record.
        assert hooks.findRecord(index, '/LIB/Img_1.JPG') is None

    def test_three_way_collision_counts_the_slot_once(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/a.jpg', 'star_rating': 1, 'is_favorite': False, 'is_rejected': False},
            {'path': '/lib/A.jpg', 'star_rating': 2, 'is_favorite': False, 'is_rejected': False},
            {'path': '/LIB/a.JPG', 'star_rating': 3, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 1
        assert hooks.findRecord(index, '/lib/a.jpg') is None


class TestBuildPlanNeverAppliesTheWrongPhotosRating:
    """End-to-end regression for the bug the finding described: a catalog
    photo whose exact-case path is not in the manifest, but whose case-folded
    path collides between two different manifest entries, must land as
    unmatched -- never silently rated from either colliding record."""

    def test_ambiguous_catalog_photo_is_unmatched_not_misrated(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/IMG_1.jpg', 'star_rating': 5, 'is_favorite': True, 'is_rejected': False},
            {'path': '/lib/img_1.jpg', 'star_rating': 2, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 1

        photo = lua.globals().facet_test_make_photo('/LIB/Img_1.JPG')
        values = lua.table_from({'path': '/LIB/Img_1.JPG', 'rating': 0, 'pickStatus': 0}, recursive=True)
        by_photo = lua.table()
        by_photo[photo] = values
        catalog = lua.globals().facet_test_make_catalog(by_photo)
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        photos = lua.table_from([photo])
        prefs = _preferences(lua)

        plan = hooks.buildPlan(catalog, photos, index, prefs, progress, logger)

        assert plan.matched == 0
        assert plan.unmatched == 1
        assert plan.entryCount == 0
        # Neither the 5-star nor the 2-star manifest rating was applied.
        assert dict(photo.written.items()) == {}

    def test_unambiguous_catalog_photo_still_matches_via_fallback(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/solo.jpg', 'star_rating': 4, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        assert index.collisions == 0

        photo = lua.globals().facet_test_make_photo('/LIB/SOLO.JPG')
        values = lua.table_from({'path': '/LIB/SOLO.JPG', 'rating': 0, 'pickStatus': 0}, recursive=True)
        by_photo = lua.table()
        by_photo[photo] = values
        catalog = lua.globals().facet_test_make_catalog(by_photo)
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        photos = lua.table_from([photo])
        prefs = _preferences(lua)

        plan = hooks.buildPlan(catalog, photos, index, prefs, progress, logger)

        assert plan.matched == 1
        assert plan.entryCount == 1
        assert plan.entries[1].rating == 4


class TestPreviewMessageSurfacesCollisions:
    def test_collision_line_appears_next_to_the_unmatched_count(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/IMG_1.jpg', 'star_rating': 5, 'is_favorite': True, 'is_rejected': False},
            {'path': '/lib/img_1.jpg', 'star_rating': 2, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        plan = lua.table_from({
            'scoped': 1, 'matched': 0, 'unmatched': 1, 'ratingWrites': 0,
            'pickWrites': 0, 'conflicts': 0, 'unchanged': 0,
            'sampleCatalogPath': '/LIB/Img_1.JPG', 'sampleMappedPath': '/LIB/Img_1.JPG',
        }, recursive=True)
        prefs = _preferences(lua)
        message = hooks.previewMessage(plan, manifest, index, prefs)
        lines = message.split('\n')
        unmatched_i = next(i for i, line in enumerate(lines) if line.startswith('NOT FOUND'))
        assert 'Ambiguous by case only' in lines[unmatched_i + 1]
        assert lines[unmatched_i + 1].endswith('1')

    def test_no_collision_line_when_the_manifest_has_none(self, lua, hooks):
        manifest = _manifest(lua, [
            {'path': '/Lib/solo.jpg', 'star_rating': 4, 'is_favorite': False, 'is_rejected': False},
        ])
        index = hooks.buildIndex(manifest)
        plan = lua.table_from({
            'scoped': 1, 'matched': 1, 'unmatched': 0, 'ratingWrites': 1,
            'pickWrites': 0, 'conflicts': 0, 'unchanged': 0,
            'sampleCatalogPath': '/Lib/solo.jpg', 'sampleMappedPath': '/Lib/solo.jpg',
        }, recursive=True)
        prefs = _preferences(lua)
        message = hooks.previewMessage(plan, manifest, index, prefs)
        assert 'Ambiguous by case only' not in message


class TestResolveField:
    """Table-driven coverage for the field-resolution helper buildPlan now
    shares between the rating and pick-status decisions (finding: duplicated
    6-deep-nested field resolution)."""

    @pytest.mark.parametrize(('current', 'wanted', 'empty', 'overwrite', 'expected'), [
        # Nothing wanted: always a no-op, never a conflict.
        (3, None, 0, False, (None, False)),
        # Empty field: the wanted value is written.
        (0, 5, 0, False, (5, False)),
        # Empty field, wanted value already matches "empty" semantics: no-op.
        (5, 5, 0, False, (None, False)),
        # Hand-set field, differs from wanted, overwrite off: conflict.
        (3, 5, 0, False, (None, True)),
        # Hand-set field, already matches wanted: quietly fine.
        (5, 5, 0, False, (None, False)),
        # Overwrite on: always writes when it differs, regardless of current.
        (3, 5, 0, True, (5, False)),
        # Overwrite on, already correct: no-op.
        (5, 5, 0, True, (None, False)),
    ])
    def test_matrix(self, hooks, current, wanted, empty, overwrite, expected):
        assert hooks.resolveField(current, wanted, empty, overwrite) == expected


class TestWriteField:
    """Coverage for the pcall-write helper applyPlan now shares between the
    rating and pick-status writes (finding: duplicated pcall-write blocks)."""

    def test_successful_write_returns_true_and_logs_nothing(self, lua, hooks):
        photo = lua.globals().facet_test_make_photo('/p.jpg')
        logger = lua.globals().facet_test_make_logger()
        ok = hooks.writeField(photo, 'rating', 5, 'rating', '/p.jpg', logger)
        assert ok is True
        assert photo.written.rating == 5
        assert len(logger.lines) == 0

    def test_failed_write_returns_false_and_logs_the_label_and_path(self, lua, hooks):
        photo = lua.globals().facet_test_make_failing_photo('/q.jpg')
        logger = lua.globals().facet_test_make_logger()
        ok = hooks.writeField(photo, 'pickStatus', 1, 'flag', '/q.jpg', logger)
        assert ok is False
        assert len(logger.lines) == 1
        assert logger.lines[1].startswith('FAIL flag /q.jpg:')
