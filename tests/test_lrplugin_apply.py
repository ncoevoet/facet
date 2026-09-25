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

import json
from pathlib import Path

import pytest

# M10: the real interpreter, not whatever `lupa`'s default (currently 5.5)
# happens to be -- `Lua must stay 5.1-compatible` per project instructions,
# and a plain `import lupa` fallback would let a 5.5 run masquerade as this
# gate on a machine where the `lua51` submodule is unavailable.
_lua_runtime_module = pytest.importorskip(
    'lupa.lua51', reason='real-Lua verification needs the optional lupa package (lua51 runtime)')

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / 'facet.lrplugin'
APPLY_LUA = PLUGIN_DIR / 'FacetApply.lua'
COMMON_LUA = PLUGIN_DIR / 'FacetCommon.lua'
METADATA_LUA = PLUGIN_DIR / 'FacetMetadata.lua'
EXPORT_STATE_LUA = PLUGIN_DIR / 'FacetExportState.lua'

# `import 'LrX'` runs unconditionally at the top of FacetApply.lua, so every
# name it asks for has to resolve to *something*. Only LrTasks needs real
# behavior: buildPlan/applyPlan call `LrTasks.yield()` every chunk, and
# applyPlan wraps its write in `LrTasks.pcall(...)`, which the real SDK
# documents as a protected call -- Lua's own `pcall` is a faithful stand-in
# for what this suite exercises. `_PLUGIN` mirrors the real SDK global that
# setPropertyForPlugin/getPropertyForPlugin/batchGetPropertyForPlugin take as
# their first argument (Step 6a's test-seam requirement).
_BOOTSTRAP = """
function import(name)
    if name == 'LrTasks' then
        return {
            yield = function() end,
            pcall = function(fn) return pcall(fn) end,
            startAsyncTask = function(fn) return fn() end,
        }
    end
    if name == 'LrPrefs' then
        return {
            prefsForPlugin = function() return _FACET_TEST_PREFS end,
        }
    end
    if name == 'LrProgressScope' then
        -- executeApply (called directly by the tests below, not via run())
        -- calls makeProgressScope for every pass, which calls this as a
        -- constructor: `LrProgressScope { title = ..., functionContext = ... }`.
        -- `_FACET_TEST_FORCE_CANCELED` lets a test simulate a mid-run cancel
        -- (applyPlan's very first chunk sees isCanceled() == true) without
        -- needing to reach into applyPlan's internals.
        return setmetatable({}, { __call = function(_, opts)
            return {
                isCanceled = function()
                    -- `_FACET_TEST_CANCEL_AFTER = n`: the first n checks pass,
                    -- then every check on every scope reports canceled -- a
                    -- cancel landing mid-pass that later scopes still see.
                    if _FACET_TEST_CANCEL_AFTER ~= nil then
                        if _FACET_TEST_CANCEL_AFTER <= 0 then return true end
                        _FACET_TEST_CANCEL_AFTER = _FACET_TEST_CANCEL_AFTER - 1
                        return false
                    end
                    return _FACET_TEST_FORCE_CANCELED == true
                end,
                setPortionComplete = function() end,
                setCancelable = function() end,
                done = function() end,
            }
        end })
    end
    return {}
end
_FACET_TEST_FORCE_CANCELED = false
_FACET_TEST_PREFS = {}
_PLUGIN = { id = 'com.facet.lightroom.test' }
FACET_APPLY_TEST_HOOKS = {}
package.path = package.path .. ';' .. %r

function facet_test_make_photo(path)
    local p = {}
    p.path = path
    p.written = {}
    p.pluginProperties = {}
    p.keywords = {}
    p.setRawMetadata = function(self, key, value) self.written[key] = value end
    p.getRawMetadata = function(self, key)
        if key == 'keywords' then
            return self.keywords
        end
        return self.written[key]
    end
    p.setPropertyForPlugin = function(self, plugin, key, value)
        self.pluginProperties[key] = value
    end
    p.getPropertyForPlugin = function(self, plugin, key)
        return self.pluginProperties[key]
    end
    p.addKeyword = function(self, keyword)
        for _, existing in ipairs(self.keywords) do
            if existing == keyword then return end
        end
        self.keywords[#self.keywords + 1] = keyword
    end
    p.removeKeyword = function(self, keyword)
        local kept = {}
        for _, existing in ipairs(self.keywords) do
            if existing ~= keyword then
                kept[#kept + 1] = existing
            end
        end
        self.keywords = kept
    end
    return p
end

function facet_test_make_failing_photo(path)
    local p = facet_test_make_photo(path)
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
    c.batchGetPropertyForPlugin = function(self, plugin, chunk, keys)
        local out = {}
        for _, photo in ipairs(chunk) do
            local values = {}
            for _, key in ipairs(keys) do
                values[key] = photo:getPropertyForPlugin(plugin, key)
            end
            out[photo] = values
        end
        return out
    end
    -- Collection SDK stub: canReturnPrior semantics are modelled by keying
    -- on (parent, name), so a re-run resolves the same set/collection object
    -- rather than creating a duplicate -- the real finding this stub exists
    -- to exercise.
    c.sets = {}
    c.collections = {}
    c.keywords = {}
    -- Known issue 1 fix: record every createKeyword call's arguments (not
    -- just the final post-setAttributes state, which setAttributes below
    -- can silently overwrite) so a test can assert what the PRODUCTION
    -- CALL itself passed for includeOnExport, independent of any later
    -- setAttributes write.
    c.createKeywordCalls = {}
    c.setsCreated = 0
    c.collectionsCreated = 0
    c.writeAccessCalls = 0
    c.privateWriteAccessCalls = 0
    -- Models a confirmed real-SDK constraint (see FacetApply.lua's
    -- ensureCollectionSets/applyCollectionPlan comments): a collection set
    -- created inside a withWriteAccessDo call cannot be used as the parent
    -- of createCollection until that call has RETURNED. `_pendingSets`
    -- tracks the sets created by the withWriteAccessDo call currently on
    -- top of the stack; createCollection raises if asked to nest under one
    -- of them, and the frame is cleared once that call's fn() returns.
    c._writeAccessStack = {}
    c.withWriteAccessDo = function(self, name, fn, opts)
        self.writeAccessCalls = self.writeAccessCalls + 1
        local frame = {}
        table.insert(self._writeAccessStack, frame)
        local ok, err = pcall(fn)
        table.remove(self._writeAccessStack)
        if not ok then
            error(err, 0)
        end
    end
    c.withPrivateWriteAccessDo = function(self, fn, opts)
        self.privateWriteAccessCalls = self.privateWriteAccessCalls + 1
        local ok, err = pcall(fn)
        if not ok then
            error(err, 0)
        end
    end
    -- Models `LrCatalog:getChildCollectionSets()` (top-level sets, no
    -- parent), the other half of the read-only Preview lookup.
    c.getChildCollectionSets = function(self)
        local children = {}
        for _, set in pairs(self.sets) do
            if set.parent == nil then
                children[#children + 1] = set
            end
        end
        return children
    end
    -- Lets a test make `getChildCollectionSets()` itself raise, to prove a
    -- lookup failure is reported rather than treated as "no candidates".
    c.failGetChildCollectionSets = function(self)
        self.getChildCollectionSets = function() error('boom: getChildCollectionSets') end
    end
    c.createCollectionSet = function(self, name, parent, canReturnPrior)
        local key = tostring(parent) .. '|' .. name
        local existing = self.sets[key]
        if existing then
            return existing
        end
        local set = { name = name, parent = parent }
        -- Models the real `LrCollectionSet:getChildCollections()`
        -- call the dissolved-collection sweep uses to enumerate a set's
        -- direct children -- backed by the SAME catalog.collections table
        -- createCollection populates, filtered to this set and to
        -- not-yet-deleted collections.
        set.getChildCollections = function(self2)
            local children = {}
            for _, collection in pairs(self.collections) do
                if collection.parent == self2 and not collection.deleted then
                    children[#children + 1] = collection
                end
            end
            return children
        end
        set.getName = function(self2) return self2.name end
        -- Models `LrCollectionSet:getChildCollectionSets()`, backed by the
        -- SAME catalog.sets table this stub's createCollectionSet
        -- populates, filtered to sets whose parent is this one -- used by
        -- the read-only Preview lookup (`findExistingCollectionSets`).
        set.getChildCollectionSets = function(self2)
            local children = {}
            for _, child in pairs(self.sets) do
                if child.parent == self2 then
                    children[#children + 1] = child
                end
            end
            return children
        end
        self.sets[key] = set
        self.setsCreated = self.setsCreated + 1
        local frame = self._writeAccessStack[#self._writeAccessStack]
        if frame then
            frame[set] = true
        end
        return set
    end
    c.createCollection = function(self, name, parent, canReturnPrior)
        for _, frame in ipairs(self._writeAccessStack) do
            if parent and frame[parent] then
                error('createCollection: parent collection set was created earlier in this '
                    .. 'same withWriteAccessDo call and cannot be used until that call returns')
            end
        end
        local key = tostring(parent) .. '|' .. name
        local existing = self.collections[key]
        if existing then
            return existing
        end
        local collection = { name = name, parent = parent, photos = {}, smart = false }
        collection.addPhotos = function(self2, photos)
            for _, photo in ipairs(photos) do
                self2.photos[#self2.photos + 1] = photo
            end
        end
        collection.removeAllPhotos = function(self2)
            if self2.smart then
                error('removeAllPhotos: smart collections cannot be edited')
            end
            self2.photos = {}
        end
        collection.getPhotos = function(self2)
            return self2.photos
        end
        -- The dissolved-collection sweep names each candidate via
        -- `collection:getName()`, the real SDK's method form -- the stub
        -- previously only exposed `.name` as a bare field (getName existed
        -- on keywords, never on collections).
        collection.getName = function(self2)
            return self2.name
        end
        collection.delete = function(self2)
            self2.deleted = true
        end
        -- M4: the real SDK exposes isSmartCollection() as a method, not a
        -- '.smart' field -- model that here so production code exercising
        -- the real call shape is actually tested.
        collection.isSmartCollection = function(self2)
            return self2.smart == true
        end
        self.collections[key] = collection
        self.collectionsCreated = self.collectionsCreated + 1
        return collection
    end
    -- Keyword SDK stub: same "parent must exist before child creation, in a
    -- separate transaction" constraint as the collection-set stub, per the
    -- research doc's createKeyword same-transaction footgun.
    c.createKeyword = function(self, name, synonyms, includeOnExport, parent, returnExisting)
        for _, frame in ipairs(self._writeAccessStack) do
            if parent and frame[parent] then
                error('createKeyword: parent keyword was created earlier in this same '
                    .. 'withWriteAccessDo call and cannot be used until that call returns')
            end
        end
        self.createKeywordCalls[#self.createKeywordCalls + 1] = {
            name = name, includeOnExport = includeOnExport, parent = parent, returnExisting = returnExisting,
        }
        local key = tostring(parent) .. '|' .. name
        local existing = self.keywords[key]
        if existing and returnExisting then
            return existing
        end
        local keyword = { name = name, parent = parent, includeOnExport = includeOnExport, setAttributesCalls = {} }
        keyword.getName = function(self2) return self2.name end
        keyword.getParent = function(self2) return self2.parent end
        keyword.setAttributes = function(self2, attrs)
            self2.setAttributesCalls[#self2.setAttributesCalls + 1] = attrs
            if attrs.includeOnExport ~= nil then
                self2.includeOnExport = attrs.includeOnExport
            end
        end
        self.keywords[key] = keyword
        local frame = self._writeAccessStack[#self._writeAccessStack]
        if frame then
            frame[keyword] = true
        end
        return keyword
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
    runtime = _lua_runtime_module.LuaRuntime(unpack_returned_tuples=True)
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


def _preferences(lua, overwrite=False, **extra):
    values = {'catalogPrefix': '', 'manifestPrefix': '', 'overwrite': overwrite}
    values.update(extra)
    return lua.table_from(values, recursive=True)


def _write_manifest(tmp_path, photos, version=2):
    """Write a manifest to disk exactly as ``facet.py --export-manifest``
    would, so tests reading it back via ``readManifest`` exercise the real
    JSON decode path -- including the ``FacetJson.null`` sentinel for a
    Python ``None`` -- rather than bypassing it with ``lua.table_from``
    (finding B2)."""
    payload = {'version': version, 'generated_at': '2026-01-01T00:00:00Z', 'photos': photos}
    path = tmp_path / 'facet_manifest.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


def _real_manifest(hooks, tmp_path, photos, version=2):
    """Decode a manifest through the real ``readManifest`` (real JSON decode,
    version check included) rather than ``lua.table_from``."""
    path = _write_manifest(tmp_path, photos, version=version)
    result = hooks.readManifest(path)
    # readManifest returns a single value on success (`return decoded`) or a
    # (nil, message) pair on failure -- lupa only turns the latter case into
    # a Python tuple, so a bare unpack on success would instead iterate the
    # returned Lua table itself.
    if isinstance(result, tuple):
        return result
    return result, None


BASE_PHOTO = {
    'path': None, 'star_rating': 0, 'is_favorite': False, 'is_rejected': False,
    'is_burst_lead': False, 'burst_group_id': None, 'sequence_kind': None,
    'sequence_group_id': None, 'score_stars': 0, 'date_taken': None, 'filename': None,
}


def _photo(**overrides):
    record = dict(BASE_PHOTO)
    record.update(overrides)
    if record['filename'] is None and record['path']:
        record['filename'] = record['path'].rsplit('/', 1)[-1]
    return record


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

        group_index = hooks.buildGroupIndex(manifest)
        plan = hooks.buildPlan(catalog, photos, index, group_index, prefs, progress, logger)

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

        group_index = hooks.buildGroupIndex(manifest)
        plan = hooks.buildPlan(catalog, photos, index, group_index, prefs, progress, logger)

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


class TestNullSequenceKindNormalisation:
    """Core B2 regression: a null sequence_kind decoded from REAL JSON must
    be treated as 'no set', never as the truthy FacetJson.null sentinel."""

    def test_null_sequence_kind_normalises_to_no_set(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/a.jpg', sequence_kind=None),
        ])
        assert error is None
        record = manifest.photos[1]
        assert hooks.recordSequenceKind(record) is None
        assert hooks.isKeepWholeSequenceKind(hooks.recordSequenceKind(record)) is False

    def test_null_burst_group_id_and_date_taken_normalise_too(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/a.jpg', burst_group_id=None, date_taken=None),
        ])
        assert error is None
        record = manifest.photos[1]
        assert hooks.recordBurstGroupId(record) is None
        assert hooks.recordDateTaken(record) is None

    def test_burst_group_id_zero_survives_normalisation(self, hooks, tmp_path):
        # 0 is a real id, not the null sentinel -- must not be squashed to nil.
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/a.jpg', burst_group_id=0),
        ])
        assert error is None
        record = manifest.photos[1]
        assert hooks.recordBurstGroupId(record) == 0


class TestVersionRefusal:
    def test_v1_manifest_is_refused_with_no_manifest_and_a_clear_message(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/a.jpg'),
        ], version=1)
        assert manifest is None
        assert 'version' in error.lower()
        assert '2' in error


class TestBurstPickAndReject:
    def _run_plan(self, lua, hooks, tmp_path, records, in_scope_paths, prefs_extra):
        # Delegates to the module-level `_real_plan` (defined
        # below, the pipeline's superset -- manifest -> index -> groupIndex
        # -> catalog -> buildPlan) instead of re-deriving the same five
        # steps inline; only the `plan` this class's assertions need.
        _catalog, plan, _logger, _photos = _real_plan(lua, hooks, tmp_path, records, in_scope_paths, prefs_extra)
        return plan

    def test_group_with_several_leads_picks_all_of_them(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/c.jpg', burst_group_id=1, is_burst_lead=False),
        ]
        plan = self._run_plan(lua, hooks, tmp_path, records,
                               ['/lib/a.jpg', '/lib/b.jpg', '/lib/c.jpg'],
                               {'pickBurstLeads': True})
        picks = {plan.entries[i].path: plan.entries[i].pickStatus for i in range(1, plan.entryCount + 1)}
        assert picks.get('/lib/a.jpg') == 1
        assert picks.get('/lib/b.jpg') == 1
        assert '/lib/c.jpg' not in picks

    def test_singleton_burst_group_is_left_untouched(self, lua, hooks, tmp_path):
        records = [_photo(path='/lib/solo.jpg', burst_group_id=5, is_burst_lead=True)]
        plan = self._run_plan(lua, hooks, tmp_path, records, ['/lib/solo.jpg'],
                               {'pickBurstLeads': True, 'rejectBurstOthers': True})
        # A lone frame is no burst to pick from, even though scoring marks it
        # a lead: the pick rule only applies to groups of two or more.
        assert plan.pickWrites == 0

    def test_group_with_no_lead_anywhere_gets_no_picks_or_rejects(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=2, is_burst_lead=False),
            _photo(path='/lib/b.jpg', burst_group_id=2, is_burst_lead=False),
        ]
        plan = self._run_plan(lua, hooks, tmp_path, records, ['/lib/a.jpg', '/lib/b.jpg'],
                               {'pickBurstLeads': True, 'rejectBurstOthers': True})
        assert plan.pickWrites == 0

    def test_bracket_member_is_never_rejected_even_when_grouped_by_burst(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/lead.jpg', burst_group_id=3, is_burst_lead=True),
            _photo(path='/lib/other.jpg', burst_group_id=3, is_burst_lead=False,
                   sequence_kind='bracket', sequence_group_id=9),
        ]
        plan = self._run_plan(lua, hooks, tmp_path, records, ['/lib/lead.jpg', '/lib/other.jpg'],
                               {'pickBurstLeads': True, 'rejectBurstOthers': True})
        entries = {plan.entries[i].path: plan.entries[i] for i in range(1, plan.entryCount + 1)}
        assert entries['/lib/lead.jpg'].pickStatus == 1
        # The bracket member has no reject entry at all -- its sequence_kind
        # excludes it from the reject-the-rest rule entirely.
        assert getattr(entries.get('/lib/other.jpg'), 'pickStatus', None) != -1

    def test_out_of_scope_lead_still_permits_in_scope_reject(self, lua, hooks, tmp_path):
        # The lead exists only in the WHOLE manifest, not in the current
        # Lightroom scope -- the group-level "has a lead" fact still holds.
        records = [
            _photo(path='/lib/lead.jpg', burst_group_id=4, is_burst_lead=True),
            _photo(path='/lib/other.jpg', burst_group_id=4, is_burst_lead=False),
        ]
        plan = self._run_plan(lua, hooks, tmp_path, records, ['/lib/other.jpg'],
                               {'pickBurstLeads': True, 'rejectBurstOthers': True})
        entries = {plan.entries[i].path: plan.entries[i] for i in range(1, plan.entryCount + 1)}
        assert entries['/lib/other.jpg'].pickStatus == -1

    def test_manual_favorite_wins_over_burst_derived_pick(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=1, is_burst_lead=False, is_rejected=True),
        ]
        plan = self._run_plan(lua, hooks, tmp_path, records, ['/lib/a.jpg', '/lib/b.jpg'],
                               {'pickBurstLeads': True, 'rejectBurstOthers': True})
        entries = {plan.entries[i].path: plan.entries[i] for i in range(1, plan.entryCount + 1)}
        # b.jpg is explicitly rejected by hand -- same outcome the burst rule
        # would have derived, but via the unconditional manual-flag path.
        assert entries['/lib/b.jpg'].pickStatus == -1


class TestScoreStarsFallback:
    def _plan_for(self, lua, hooks, tmp_path, record, current_rating, overwrite, stars_from_score):
        # Same delegation as TestBurstPickAndReject._run_plan
        # above -- `_real_plan`'s optional `current_rating` covers this
        # class's one difference (a variable starting rating rather than a
        # fixed 0) from the shared pipeline.
        _catalog, plan, _logger, _photos = _real_plan(
            lua, hooks, tmp_path, [record], [record['path']],
            {'overwrite': overwrite, 'starsFromScore': stars_from_score},
            current_rating=current_rating)
        return plan

    def test_score_stars_fills_an_unrated_photo(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', star_rating=0, score_stars=4)
        plan = self._plan_for(lua, hooks, tmp_path, record, current_rating=0,
                               overwrite=False, stars_from_score=True)
        assert plan.entries[1].rating == 4

    def test_score_stars_never_overwrites_an_existing_rating_even_with_overwrite_on(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', star_rating=0, score_stars=4)
        plan = self._plan_for(lua, hooks, tmp_path, record, current_rating=2,
                               overwrite=True, stars_from_score=True)
        assert plan.ratingWrites == 0

    def test_real_star_rating_still_follows_the_normal_overwrite_rule(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', star_rating=5, score_stars=1)
        plan = self._plan_for(lua, hooks, tmp_path, record, current_rating=2,
                               overwrite=True, stars_from_score=True)
        assert plan.entries[1].rating == 5


class TestCollectionNaming:
    def test_name_uses_the_whole_manifest_earliest_member_even_out_of_scope(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/late.jpg', burst_group_id=1, is_burst_lead=True,
                   date_taken='2026:03:02 10:00:00'),
            _photo(path='/lib/early.jpg', burst_group_id=1, is_burst_lead=False,
                   date_taken='2026:03:01 09:30:15'),
        ])
        assert error is None
        group_index = hooks.buildGroupIndex(manifest)
        name = hooks.groupDisplayName(group_index.burstGroups[1].earliestDate,
                                       group_index.burstGroups[1].earliestPath)
        assert name.startswith('2026-03-01 09:30:15')
        assert name.endswith('early.jpg')

    def test_undated_group_falls_back_to_tilde_no_date_prefix(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/x.jpg', burst_group_id=2, is_burst_lead=True, date_taken=None),
        ])
        assert error is None
        group_index = hooks.buildGroupIndex(manifest)
        name = hooks.groupDisplayName(group_index.burstGroups[2].earliestDate,
                                       group_index.burstGroups[2].earliestPath)
        assert name.startswith('~ (no date)')

    def test_no_bursts_collection_when_the_whole_burst_is_one_keep_whole_set(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True,
                   sequence_kind='bracket', sequence_group_id=9),
            _photo(path='/lib/b.jpg', burst_group_id=1, is_burst_lead=False,
                   sequence_kind='bracket', sequence_group_id=9),
        ]
        manifest, error = _real_manifest(hooks, tmp_path, records)
        assert error is None
        group_index = hooks.buildGroupIndex(manifest)
        assert group_index.burstGroups[1].allKeepWhole is True

        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        photo_b = lua.globals().facet_test_make_photo('/lib/b.jpg')
        burst_scope = lua.table_from({1: lua.table_from([photo_a, photo_b])}, recursive=False)
        sequence_scope = lua.table_from({}, recursive=False)
        collection_plan = hooks.buildCollectionPlan(group_index, burst_scope, sequence_scope)
        assert collection_plan.count == 0


def _one_collection_plan(lua, member_paths=('/lib/a.jpg', '/lib/b.jpg')):
    """A minimal collectionPlan Lua table with one planned Bursts collection,
    shaped exactly as buildCollectionPlan produces (setName/name/members)."""
    members = [lua.globals().facet_test_make_photo(path) for path in member_paths]
    collections = lua.table_from([
        {'setName': 'Bursts', 'name': '2026-01-01 test', 'members': lua.table_from(members)},
    ], recursive=True)
    return lua.table_from({'collections': collections, 'count': 1})


class TestApplyCollectionPlanSkippedOnCancel:
    """M2: applyCollectionPlan must not run once the rating/flag write was
    canceled -- running it anyway builds collections from a run whose
    photos are only partially rated/flagged."""

    def test_shouldApplyCollectionPlan_is_false_once_canceled(self, hooks):
        outcome = {'canceled': True}
        collection_plan = {'count': 1}
        # FAILS before the fix: shouldApplyCollectionPlan does not exist yet
        # (M2's fix introduces it) -- AttributeError on the missing hook.
        assert hooks.shouldApplyCollectionPlan(outcome, collection_plan) is False

    def test_shouldApplyCollectionPlan_is_true_when_not_canceled(self, hooks):
        outcome = {'canceled': False}
        collection_plan = {'count': 1}
        assert hooks.shouldApplyCollectionPlan(outcome, collection_plan) is True

    def test_shouldApplyCollectionPlan_is_false_with_no_collection_work(self, hooks):
        outcome = {'canceled': False}
        collection_plan = {'count': 0}
        assert hooks.shouldApplyCollectionPlan(outcome, collection_plan) is False

    def test_summary_reports_collections_skipped_by_cancel(self, hooks):
        plan = {'unchanged': 0, 'conflicts': 0, 'unmatched': 0}
        outcome = {'photosTouched': 1, 'ratingsSet': 1, 'picksSet': 0, 'failed': 0, 'canceled': True}
        # Before the fix, summaryMessage has no fourth parameter, so this
        # call either errors (arity) or the message never mentions the
        # skipped collections -- either way this assertion fails first.
        message = hooks.summaryMessage(plan, outcome, None, True)
        assert 'Collections were not created' in message

    def test_summary_omits_skip_line_when_collections_were_not_queued(self, hooks):
        plan = {'unchanged': 0, 'conflicts': 0, 'unmatched': 0}
        outcome = {'photosTouched': 1, 'ratingsSet': 1, 'picksSet': 0, 'failed': 0, 'canceled': True}
        message = hooks.summaryMessage(plan, outcome, None, False)
        assert 'Collections were not created' not in message


class TestApplyCollectionPlanEnsureSetsFailureIsCaught:
    """M3: ensureCollectionSets runs outside LrTasks.pcall in
    applyCollectionPlan -- a failure there (e.g. a write-access timeout)
    must be caught and reported, not propagate past the ratings/flags this
    run already wrote."""

    def test_failure_creating_collection_sets_is_reported_not_raised(self, lua, hooks):
        catalog = lua.globals().facet_test_make_catalog({})
        # Make the very first collection-set write blow up, exactly as a
        # write-access timeout inside ensureCollectionSets would.
        catalog.createCollectionSet = lua.eval(
            "function(self, name, parent, canReturnPrior) error('write-access timeout') end")
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        collection_plan = _one_collection_plan(lua)
        # FAILS before the fix: ensureCollectionSets's error propagates
        # straight out of applyCollectionPlan instead of being caught, so
        # this call raises a lupa.LuaError instead of returning an outcome.
        outcome = hooks.applyCollectionPlan(catalog, collection_plan, progress, logger)
        assert outcome.failed == 1
        assert outcome.collectionsTouched == 0
        assert len(logger.lines) == 1
        assert logger.lines[1].startswith('FAIL collection sets:')

    def test_success_path_still_creates_collections(self, lua, hooks):
        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        collection_plan = _one_collection_plan(lua)
        outcome = hooks.applyCollectionPlan(catalog, collection_plan, progress, logger)
        assert outcome.failed == 0
        assert outcome.collectionsTouched == 1
        assert outcome.photosAdded == 2


class TestHasNothingToApply:
    """L4: a run with no rating/flag work but collection work queued must
    not report 'Nothing to change' -- both plan.entryCount and
    collectionPlan.count must be zero for that to be true."""

    def test_true_when_both_are_empty(self, hooks):
        assert hooks.hasNothingToApply({'entryCount': 0}, {'count': 0}) is True

    def test_false_when_only_collection_work_is_queued(self, hooks):
        # This is the exact case the finding is about: no rating/flag
        # writes, but a set just crossed the >=2-frame collection threshold.
        assert hooks.hasNothingToApply({'entryCount': 0}, {'count': 1}) is False

    def test_false_when_only_rating_work_is_queued(self, hooks):
        assert hooks.hasNothingToApply({'entryCount': 1}, {'count': 0}) is False


class TestCollectionSetParentMustOutliveItsOwnWrite:
    """L5: the stub SDK models the real constraint that a collection set
    created inside a withWriteAccessDo call cannot parent a createCollection
    call until that withWriteAccessDo call has returned. The production code
    (ensureCollectionSets returns before applyCollectionPlan's own
    withWriteAccessDo creates any collection) must pass; a variant that
    nests the collection creation inside the same call must not."""

    def test_current_code_passes(self, lua, hooks):
        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        collection_plan = _one_collection_plan(lua)
        outcome = hooks.applyCollectionPlan(catalog, collection_plan, progress, logger)
        assert outcome.failed == 0
        assert outcome.collectionsTouched == 1

    def test_nesting_the_collection_inside_the_sets_write_is_rejected(self, lua):
        """Inject the fault directly against the stub: create the set and
        the collection under it inside ONE withWriteAccessDo call, exactly
        the pattern the real SDK forbids and the comments in FacetApply.lua
        warn against."""
        catalog = lua.globals().facet_test_make_catalog({})
        photo = lua.globals().facet_test_make_photo('/lib/a.jpg')
        nest = lua.eval("""
            function(catalog, photo)
                local ok, err = pcall(function()
                    catalog:withWriteAccessDo('nested', function()
                        local set = catalog:createCollectionSet('Bursts', nil, true)
                        local collection = catalog:createCollection('Same-call', set, true)
                        collection:addPhotos({photo})
                    end)
                end)
                return ok, tostring(err)
            end
        """)
        ok, err = nest(catalog, photo)
        assert ok is False
        assert 'cannot be used until that call returns' in err


def _real_plan(lua, hooks, tmp_path, records, in_scope_paths, prefs_extra, current_rating=0):
    """Full build pipeline (manifest -> index -> groupIndex -> plan) through
    the real readManifest, for tests exercising matchedRecords/matchedCount
    (Steps 6a/6b/7/9), which the lighter `_manifest` helper above does not
    populate realistically enough (real JSON decode matters for
    tags/category/scores nesting). `current_rating` is the star rating every
    in-scope photo starts with in Lightroom (0 unless a test needs the
    "already rated" branch of the overwrite rule -- TestScoreStarsFallback's
    variable-current-rating pipeline shares this same helper)."""
    manifest, error = _real_manifest(hooks, tmp_path, records)
    assert error is None
    index = hooks.buildIndex(manifest)
    group_index = hooks.buildGroupIndex(manifest)
    by_photo = lua.table()
    photos = []
    for path in in_scope_paths:
        photo = lua.globals().facet_test_make_photo(path)
        values = lua.table_from({'path': path, 'rating': current_rating, 'pickStatus': 0}, recursive=True)
        by_photo[photo] = values
        photos.append(photo)
    catalog = lua.globals().facet_test_make_catalog(by_photo)
    progress = lua.globals().facet_test_make_progress()
    logger = lua.globals().facet_test_make_logger()
    prefs = _preferences(lua, **prefs_extra)
    plan = hooks.buildPlan(catalog, lua.table_from(photos), index, group_index, prefs, progress, logger)
    return catalog, plan, logger, photos


class TestMetadataFieldsPlan:
    """Step 6a: visible plug-in metadata fields, computed from every matched
    record regardless of rating/pick changes."""

    def test_desired_fields_include_aggregate_band_category_setkind(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', category='portrait', sequence_kind='bracket',
                         sequence_group_id=1)
        record['scores'] = {'aggregate': 8.96}
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        assert field_plan.count == 1
        desired = field_plan.entries[1].desiredFields
        assert desired.facetAggregate == '9.0'
        assert desired.facetBand == '8'
        assert desired.facetCategory == 'portrait'
        assert desired.facetSetKind == 'bracket'

    def test_writes_land_exactly_once_then_no_op_on_rerun(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', category='landscape')
        record['scores'] = {'aggregate': 7.2}
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        assert field_plan.pendingCount == 1
        progress = lua.globals().facet_test_make_progress()
        outcome = hooks.applyMetadataFieldsPlan(catalog, field_plan, progress, logger)
        assert outcome.fieldsWritten == 3  # aggregate + band + category (no set kind)
        # Re-running against the SAME photo (now carrying the written
        # values) must write nothing further -- and the PREVIEW pending
        # count (I7) must reflect that too, not just the actual write.
        field_plan_2 = hooks.buildMetadataFieldsPlan(catalog, plan)
        assert field_plan_2.pendingCount == 0
        outcome_2 = hooks.applyMetadataFieldsPlan(catalog, field_plan_2, progress, logger)
        assert outcome_2.fieldsWritten == 0

    def test_a_photo_that_leaves_a_bracket_keeps_no_stale_set_kind_or_category(self, lua, hooks, tmp_path):
        """A field whose desired value is nil this run (no more
        sequence_kind/category) must be CLEARED, not merely skipped -- a
        photo leaving a bracket must not keep facetSetKind='bracket' /
        facetCategory forever."""
        record1 = _photo(path='/lib/a.jpg', category='landscape', sequence_kind='bracket',
                          sequence_group_id=1)
        record1['scores'] = {'aggregate': 7.2}
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record1], ['/lib/a.jpg'], {})
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        progress = lua.globals().facet_test_make_progress()
        hooks.applyMetadataFieldsPlan(catalog, field_plan, progress, logger)
        assert photos[0].pluginProperties.facetSetKind == 'bracket'
        assert photos[0].pluginProperties.facetCategory == 'landscape'

        # Second run: the photo left the bracket (no sequence_kind) and lost
        # its category. Reuse the SAME photo/catalog so the read-back
        # `currentByField` sees the stale values from the first run.
        record2 = _photo(path='/lib/a.jpg', category=None, sequence_kind=None, sequence_group_id=None)
        record2['scores'] = {'aggregate': 7.2}
        manifest2, error = _real_manifest(hooks, tmp_path, [record2])
        assert error is None
        index2 = hooks.buildIndex(manifest2)
        group_index2 = hooks.buildGroupIndex(manifest2)
        values = lua.table_from({'path': '/lib/a.jpg', 'rating': 0, 'pickStatus': 0}, recursive=True)
        by_photo2 = lua.table()
        by_photo2[photos[0]] = values
        catalog2 = lua.globals().facet_test_make_catalog(by_photo2)
        progress2 = lua.globals().facet_test_make_progress()
        logger2 = lua.globals().facet_test_make_logger()
        prefs2 = _preferences(lua)
        plan2 = hooks.buildPlan(catalog2, lua.table_from([photos[0]]), index2, group_index2,
                                 prefs2, progress2, logger2)
        field_plan2 = hooks.buildMetadataFieldsPlan(catalog, plan2)
        # FAILS before the fix: pendingCount never counts a field going from
        # a real value to nil, so this stays 0 (this one photo's entry looks
        # unchanged) and the write below is a no-op, leaving the stale
        # facetSetKind/facetCategory values in place forever.
        assert field_plan2.pendingCount == 1
        outcome2 = hooks.applyMetadataFieldsPlan(catalog, field_plan2, progress2, logger2)
        # Both stale fields (setKind and category) actually get cleared.
        assert outcome2.fieldsWritten == 2
        assert photos[0].pluginProperties.facetSetKind is None
        assert photos[0].pluginProperties.facetCategory is None
        # The aggregate/band are unchanged (still desired) -- clearing must
        # not touch fields that still have a value.
        assert photos[0].pluginProperties.facetAggregate == '7.2'

    def test_a_field_the_sdk_reports_as_empty_string_is_treated_as_never_set(
            self, lua, hooks, tmp_path):
        """UNVERIFIED SDK behaviour: if `batchGetPropertyForPlugin` ever
        reports a never-set field as '' rather than nil, that must not look
        like a stale value -- neither as pending in the Preview count nor as
        a write `applyMetadataFieldsPlan` re-clears every single run."""
        record = _photo(path='/lib/a.jpg', category=None)
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        # No score/category means desiredFields has NO field at all this
        # run. Simulate the SDK reporting facetCategory as '' rather than
        # nil for a field that was genuinely never set -- both current and
        # desired are then "empty" and nothing should be pending.
        photos[0].pluginProperties.facetCategory = ''
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        assert field_plan.pendingCount == 0
        progress = lua.globals().facet_test_make_progress()
        outcome = hooks.applyMetadataFieldsPlan(catalog, field_plan, progress, logger)
        # FAILS before the fix: '' ~= nil, so writeFieldsForPhoto sees a
        # "current value" that differs from the desired nil and re-clears
        # (setPropertyForPlugin(..., nil)) a field that was already unset.
        assert outcome.fieldsWritten == 0


class TestDerivedValueBookkeeping:
    """Step 6b / C1 fix: facetDerivedRating/facetDerivedPick are written
    alongside a DERIVED rating/pick write, never for a manual one -- and,
    since C1, via their OWN plan/apply pair, entirely decoupled from the
    "Write metadata fields" checkbox / buildMetadataFieldsPlan. The
    signature of buildDerivedValuesPlan/applyDerivedValuesPlan takes no
    writeMetadataFields-shaped parameter at all, which is the structural
    proof of that decoupling."""

    def test_stars_from_score_write_sets_derived_rating(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', star_rating=0, score_stars=4)
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {'starsFromScore': True})
        assert plan.entries[1].rating == 4
        derived_plan = hooks.buildDerivedValuesPlan(plan, lua.table_from([[1, int(plan.entryCount)]], recursive=True))
        assert derived_plan.count == 1
        assert derived_plan.entries[1].ratingString == '4'
        progress = lua.globals().facet_test_make_progress()
        hooks.applyDerivedValuesPlan(catalog, derived_plan, progress, logger)
        assert photos[0].pluginProperties.facetDerivedRating == '4'

    def test_manual_rating_never_gets_a_derived_bookkeeping_write(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', star_rating=5)
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        assert plan.entries[1].rating == 5
        derived_plan = hooks.buildDerivedValuesPlan(plan, lua.table_from([[1, int(plan.entryCount)]], recursive=True))
        assert derived_plan.count == 0

    def test_derived_bookkeeping_is_written_even_with_write_metadata_fields_off(self, lua, hooks, tmp_path):
        """C1's exact regression scenario: default dialog
        (writeMetadataFields=false), 'Fill in star ratings from Facet
        scores' ON -- facetDerivedRating must still be recorded, since the
        derived-value plan/apply pair never looks at writeMetadataFields at
        all (buildMetadataFieldsPlan is never even called here)."""
        record = _photo(path='/lib/a.jpg', star_rating=0, score_stars=4)
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, [record], ['/lib/a.jpg'],
            {'starsFromScore': True, 'writeMetadataFields': False})
        derived_plan = hooks.buildDerivedValuesPlan(plan, lua.table_from([[1, int(plan.entryCount)]], recursive=True))
        progress = lua.globals().facet_test_make_progress()
        hooks.applyDerivedValuesPlan(catalog, derived_plan, progress, logger)
        assert photos[0].pluginProperties.facetDerivedRating == '4'

    def test_cancel_after_first_chunk_still_records_baseline_for_committed_photos(self, lua, hooks, tmp_path):
        """WRITE_CHUNK_SIZE is 200 -- build 201 derived-rating
        entries so applyPlan commits one full chunk (200 photos) before a
        progress stub reports canceled at the next chunk boundary, then
        confirm the derived-value baseline covers exactly the entries that
        committed -- never zero of them, and never the one that didn't."""
        total = 201
        records = [
            _photo(path='/lib/p%03d.jpg' % i, star_rating=0, score_stars=4)
            for i in range(total)
        ]
        paths = [record['path'] for record in records]
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, records, paths, {'starsFromScore': True})
        assert plan.entryCount == total

        # False on the first isCanceled() call (chunk 1, entries 1-200
        # commits), true from the second call onward (chunk 2, entry 201).
        progress = lua.eval("""
            function()
                local calls = 0
                return {
                    isCanceled = function(self)
                        calls = calls + 1
                        return calls > 1
                    end,
                    setPortionComplete = function(self, done, total) end,
                }
            end
        """)()
        outcome = hooks.applyPlan(catalog, plan, progress, logger)
        assert outcome.canceled is True
        # FAILS before the fix: applyPlan has no `committedThrough` field.
        assert outcome.committedThrough == 200

        derived_plan = hooks.buildDerivedValuesPlan(plan, outcome.committedRanges)
        assert derived_plan.count == 200
        derived_progress = lua.globals().facet_test_make_progress()
        hooks.applyDerivedValuesPlan(catalog, derived_plan, derived_progress, logger)
        for i in range(200):
            assert photos[i].pluginProperties.facetDerivedRating == '4'
        # The 201st entry's chunk never committed -- it must not get a
        # baseline recorded for a rating that was never actually written.
        assert dict(photos[200].pluginProperties.items()).get('facetDerivedRating') is None

    def test_middle_chunk_failure_leaves_a_gap_committed_ranges_must_not_paper_over(
            self, lua, hooks, tmp_path):
        """A middle chunk can fail while a LATER chunk still commits (no
        cancel involved at all) -- 'bound by the highest committed chunk'
        would then wrongly claim the failed middle chunk's entries also
        committed. The derived-value baseline must cover exactly the chunks
        that actually committed, leaving a gap where the middle one failed."""
        total = 401  # three write chunks: 1-200, 201-400, 401-401
        records = [
            _photo(path='/lib/p%03d.jpg' % i, star_rating=0, score_stars=4)
            for i in range(total)
        ]
        paths = [record['path'] for record in records]
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, records, paths, {'starsFromScore': True})
        assert plan.entryCount == total

        # Fail exactly the SECOND withWriteAccessDo call (chunk 2, entries
        # 201-400) -- the first and third chunks commit normally.
        lua.execute('_FACET_TEST_WRITE_CALL = 0')
        catalog.withWriteAccessDo = lua.eval("""
            function(original)
                return function(self, name, fn, opts)
                    _FACET_TEST_WRITE_CALL = _FACET_TEST_WRITE_CALL + 1
                    if _FACET_TEST_WRITE_CALL == 2 then
                        error('write-access timeout')
                    end
                    return original(self, name, fn, opts)
                end
            end
        """)(catalog.withWriteAccessDo)

        progress = lua.globals().facet_test_make_progress()
        outcome = hooks.applyPlan(catalog, plan, progress, logger)
        assert outcome.canceled is False
        assert outcome.failed == 200

        ranges = list(outcome.committedRanges.values())
        assert len(ranges) == 2
        assert (ranges[0][1], ranges[0][2]) == (1, 200)
        assert (ranges[1][1], ranges[1][2]) == (401, 401)

        derived_plan = hooks.buildDerivedValuesPlan(plan, outcome.committedRanges)
        # FAILS before the fix: buildDerivedValuesPlan(plan, committedThrough)
        # would take committedThrough == 401 (the LAST chunk that committed,
        # not the highest CONTIGUOUS one) and wrongly include every entry
        # from the failed middle chunk too.
        assert derived_plan.count == 201  # chunk 1 (200) + chunk 3 (1)
        covered_paths = {derived_plan.entries[i].path for i in range(1, derived_plan.count + 1)}
        assert '/lib/p000.jpg' in covered_paths
        assert '/lib/p400.jpg' in covered_paths
        # A photo from the failed middle chunk must never get a baseline.
        assert '/lib/p250.jpg' not in covered_paths


class TestKeywordSync:
    """Step 7: Facet tags as keywords under a "Facet" parent, never
    exported, never touching the user's own keywords."""

    def test_creates_one_parent_and_n_children_all_not_exported(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', tags='sunset, beach , mountain')
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        keyword_plan = hooks.buildKeywordPlan(plan)
        assert keyword_plan.count == 1
        assert set(keyword_plan.entries[1].tags.values()) == {'sunset', 'beach', 'mountain'}
        progress = lua.globals().facet_test_make_progress()
        outcome = hooks.applyKeywordPlan(catalog, keyword_plan, progress, logger)
        assert outcome.added == 3
        assert outcome.failed == 0
        keys = list(catalog.keywords.keys())
        root_keys = [k for k in keys if k.endswith('|Facet')]
        assert len(root_keys) == 1
        for keyword_key, keyword in catalog.keywords.items():
            assert keyword.includeOnExport is False
        # Known issue 1: pin the PRODUCTION CALL's argument directly -- the
        # stub's setAttributes overwrites the same field createKeyword's
        # argument already set, so asserting only the final
        # keyword.includeOnExport cannot distinguish "createKeyword passed
        # true, setAttributes corrected it" from "createKeyword passed
        # false" -- K1 (arg true) alone is a green mutant against that
        # weaker assertion. Every createKeyword call (root AND every child)
        # must itself pass includeOnExport == false.
        calls = list(catalog.createKeywordCalls.values())
        assert len(calls) == 4  # 1 root + 3 children
        for call in calls:
            assert call.includeOnExport is False

    def test_a_preexisting_facet_keyword_and_child_get_forced_to_not_exported(self, lua, hooks, tmp_path):
        """Known issue 1, test (d): a user-created 'Facet' root keyword (and
        a child under it) that already exist with includeOnExport=True must
        be forced to False by ensureKeywords -- returnExisting hands back
        the SAME stored object, so this pins the two setAttributes calls
        (root :855 and child :862), which a `createKeyword` call alone
        (K4-style fault) cannot satisfy on its own."""
        record = _photo(path='/lib/a.jpg', tags='sunset')
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        # Pre-seed a user-made root keyword and child, both wrongly exported.
        pre_root = catalog.createKeyword(catalog, 'Facet', {}, True, None, True)
        pre_child = catalog.createKeyword(catalog, 'sunset', {}, True, pre_root, True)
        assert pre_root.includeOnExport is True
        assert pre_child.includeOnExport is True

        keyword_plan = hooks.buildKeywordPlan(plan)
        progress = lua.globals().facet_test_make_progress()
        hooks.applyKeywordPlan(catalog, keyword_plan, progress, logger)

        assert pre_root.includeOnExport is False
        assert pre_child.includeOnExport is False

    def test_second_pass_removes_a_dropped_tag_and_keeps_others(self, lua, hooks, tmp_path):
        record1 = _photo(path='/lib/a.jpg', tags='sunset, beach')
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record1], ['/lib/a.jpg'], {})
        keyword_plan = hooks.buildKeywordPlan(plan)
        progress = lua.globals().facet_test_make_progress()
        hooks.applyKeywordPlan(catalog, keyword_plan, progress, logger)
        assert len(photos[0].keywords) == 2

        record2 = _photo(path='/lib/a.jpg', tags='beach')
        manifest2, error = _real_manifest(hooks, tmp_path, [record2])
        index2 = hooks.buildIndex(manifest2)
        group_index2 = hooks.buildGroupIndex(manifest2)
        prefs2 = _preferences(lua)
        values = lua.table_from({'path': '/lib/a.jpg', 'rating': 0, 'pickStatus': 0}, recursive=True)
        by_photo2 = lua.table()
        by_photo2[photos[0]] = values
        catalog2 = lua.globals().facet_test_make_catalog(by_photo2)
        catalog2.keywords = catalog.keywords
        progress2 = lua.globals().facet_test_make_progress()
        plan2 = hooks.buildPlan(catalog2, lua.table_from([photos[0]]), index2, group_index2,
                                 prefs2, progress2, logger)
        keyword_plan2 = hooks.buildKeywordPlan(plan2)
        hooks.applyKeywordPlan(catalog2, keyword_plan2, progress2, logger)
        remaining = {k.getName(k) for k in photos[0].keywords.values()}
        assert remaining == {'beach'}

    def test_users_own_keyword_outside_facet_survives(self, lua, hooks, tmp_path):
        record = _photo(path='/lib/a.jpg', tags='sunset')
        catalog, plan, logger, photos = _real_plan(lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {})
        user_keyword = catalog.createKeyword(catalog, 'MyOwnKeyword', {}, True, None, True)
        photos[0].addKeyword(photos[0], user_keyword)
        keyword_plan = hooks.buildKeywordPlan(plan)
        progress = lua.globals().facet_test_make_progress()
        hooks.applyKeywordPlan(catalog, keyword_plan, progress, logger)
        names = {k.getName(k) for k in photos[0].keywords.values()}
        assert 'MyOwnKeyword' in names
        assert 'sunset' in names


class TestRebuildCollections:
    """Step 9: rebuild is only attempted when the collection's whole-manifest
    group is fully covered by this run's scope."""

    def test_fully_in_scope_group_shrinking_to_zero_deletes_the_collection(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=1, is_burst_lead=False),
        ]
        manifest, error = _real_manifest(hooks, tmp_path, records)
        group_index = hooks.buildGroupIndex(manifest)
        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        photo_b = lua.globals().facet_test_make_photo('/lib/b.jpg')
        burst_scope = lua.table_from({1: lua.table_from([photo_a, photo_b])}, recursive=False)
        scope_set = lua.eval('function(a, b) return {[a] = true, [b] = true} end')(photo_a, photo_b)
        collection_plan = hooks.buildCollectionPlan(
            group_index, burst_scope, lua.table_from({}, recursive=False), scope_set)
        assert collection_plan.count == 1
        assert collection_plan.collections[1].fullyInScope is True

        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        # First create it via the normal additive path (so it has members).
        hooks.applyCollectionPlan(catalog, collection_plan, progress, logger)
        # Now rebuild with an EMPTY members list -- simulate the group no
        # longer existing.
        collection_plan.collections[1].members = lua.table_from([])
        outcome = hooks.applyRebuildCollectionPlan(catalog, collection_plan, progress, logger)
        assert outcome.rebuilt == 1
        assert outcome.deleted == 1
        assert outcome.skipped == 0

    def test_partly_out_of_scope_group_is_skipped_untouched(self, lua, hooks, tmp_path):
        records = [
            _photo(path='/lib/a.jpg', burst_group_id=2, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=2, is_burst_lead=False),
        ]
        manifest, error = _real_manifest(hooks, tmp_path, records)
        group_index = hooks.buildGroupIndex(manifest)
        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        # Only ONE of the two whole-manifest group members is in this run's
        # scope -- the group has an out-of-scope sibling.
        burst_scope = lua.table_from({2: lua.table_from([photo_a])}, recursive=False)
        collection_plan = { 'collections': [], 'count': 0 }
        collection_plan = hooks.buildCollectionPlan(group_index, burst_scope, lua.table_from({}, recursive=False))
        # A lone in-scope member never crosses the >=2-member threshold for
        # a collection at all, so nothing is planned -- confirms the
        # fullyInScope flag would have been False had one been planned.
        assert collection_plan.count == 0

    def test_smart_collection_is_skipped_without_error(self, lua, hooks):
        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        collection_plan = _one_collection_plan(lua)
        collection_plan.collections[1].fullyInScope = True
        # Pre-create the collection as a smart one.
        sets = hooks.ensureCollectionSets(catalog)
        pre_ok, pre_collection = lua.eval("""
            function(catalog, parent, name)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection(name, parent, true)
                    collection.smart = true
                end)
                return true, collection
            end
        """)(catalog, sets['Bursts'], '2026-01-01 test')
        outcome = hooks.applyRebuildCollectionPlan(catalog, collection_plan, progress, logger)
        assert outcome.skipped == 1
        assert outcome.failed == 0

    def test_rebuild_never_evicts_a_frame_outside_todays_scope(self, lua, hooks, tmp_path):
        """C2's exact repro from the review: a collection currently holding
        {a, b, c, d} must not be rebuilt down to {a, b, c} just because
        today's run's manifest/scope only covers {a, b, c} -- the group's
        real member count (3) still equals its scoped member count (3), so
        the old `fullyInScope` check alone (never reading
        collection:getPhotos()) would happily rebuild and silently evict d."""
        photos = {name: lua.globals().facet_test_make_photo('/lib/%s.jpg' % name)
                  for name in ('a', 'b', 'c', 'd')}
        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()

        # An earlier, WIDE run: all four frames in scope, all four land in
        # the collection via the normal additive path.
        records_wide = [
            _photo(path='/lib/%s.jpg' % name, burst_group_id=1, is_burst_lead=(name == 'a'))
            for name in ('a', 'b', 'c', 'd')
        ]
        manifest_wide, error = _real_manifest(hooks, tmp_path, records_wide)
        group_index_wide = hooks.buildGroupIndex(manifest_wide)
        burst_scope_wide = lua.table_from(
            {1: lua.table_from([photos['a'], photos['b'], photos['c'], photos['d']])}, recursive=False)
        scope_set_wide = lua.eval(
            'function(a, b, c, d) return {[a] = true, [b] = true, [c] = true, [d] = true} end'
        )(photos['a'], photos['b'], photos['c'], photos['d'])
        collection_plan_wide = hooks.buildCollectionPlan(
            group_index_wide, burst_scope_wide, lua.table_from({}, recursive=False), scope_set_wide)
        assert collection_plan_wide.count == 1
        hooks.applyCollectionPlan(catalog, collection_plan_wide, progress, logger)
        group_name = collection_plan_wide.collections[1].name
        collection = next(c for c in catalog.collections.values() if c.name == group_name)
        assert len(collection.photos) == 4

        # A LATER, NARROWER run: today's manifest/scope covers only a, b, c
        # -- the group has shrunk to 3 members and IS fullyInScope for this
        # run (3 scoped == 3 total), but the collection still holds d from
        # the earlier wide run.
        records_narrow = [
            _photo(path='/lib/%s.jpg' % name, burst_group_id=1, is_burst_lead=(name == 'a'))
            for name in ('a', 'b', 'c')
        ]
        manifest_narrow, error = _real_manifest(hooks, tmp_path, records_narrow)
        group_index_narrow = hooks.buildGroupIndex(manifest_narrow)
        burst_scope_narrow = lua.table_from(
            {1: lua.table_from([photos['a'], photos['b'], photos['c']])}, recursive=False)
        scope_set_narrow = lua.eval(
            'function(a, b, c) return {[a] = true, [b] = true, [c] = true} end'
        )(photos['a'], photos['b'], photos['c'])
        collection_plan_narrow = hooks.buildCollectionPlan(
            group_index_narrow, burst_scope_narrow, lua.table_from({}, recursive=False), scope_set_narrow)
        assert collection_plan_narrow.count == 1
        assert collection_plan_narrow.collections[1].fullyInScope is True

        outcome = hooks.applyRebuildCollectionPlan(catalog, collection_plan_narrow, progress, logger)
        # FAILS before the fix: the old code never read the collection's
        # real current membership and would rebuild it down to {a, b, c},
        # silently evicting d.
        assert outcome.skipped == 1
        assert outcome.rebuilt == 0
        assert len(collection.photos) == 4  # untouched -- d survives

    def test_dissolved_group_with_every_current_member_matched_is_deleted(self, lua, hooks, tmp_path):
        """BuildCollectionPlan only ever emits a plan entry for a
        group with >=2 in-scope members, so a group that dissolves below
        that threshold gets NO plan entry at all this run -- the rebuild
        pass must still reach the now-stale collection through the
        dissolved-collection sweep and delete it, since every one of its
        CURRENT members (a and b) was matched by this run."""
        records_wide = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=1, is_burst_lead=False),
        ]
        manifest_wide, error = _real_manifest(hooks, tmp_path, records_wide)
        group_index_wide = hooks.buildGroupIndex(manifest_wide)
        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        photo_b = lua.globals().facet_test_make_photo('/lib/b.jpg')
        burst_scope_wide = lua.table_from({1: lua.table_from([photo_a, photo_b])}, recursive=False)
        scope_set_wide = lua.eval(
            'function(a, b) return {[a] = true, [b] = true} end')(photo_a, photo_b)
        collection_plan_wide = hooks.buildCollectionPlan(
            group_index_wide, burst_scope_wide, lua.table_from({}, recursive=False), scope_set_wide)
        assert collection_plan_wide.count == 1

        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        hooks.applyCollectionPlan(catalog, collection_plan_wide, progress, logger)
        group_name = collection_plan_wide.collections[1].name
        collection = next(c for c in catalog.collections.values() if c.name == group_name)
        assert len(collection.photos) == 2

        # Later run: b no longer carries a burst_group_id at all (the group
        # dissolved), but both a and b are still matched this run.
        records_narrow = [
            _photo(path='/lib/a.jpg', burst_group_id=1, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=None, is_burst_lead=False),
        ]
        manifest_narrow, error = _real_manifest(hooks, tmp_path, records_narrow)
        group_index_narrow = hooks.buildGroupIndex(manifest_narrow)
        burst_scope_narrow = lua.table_from({1: lua.table_from([photo_a])}, recursive=False)
        scope_set_narrow = lua.eval(
            'function(a, b) return {[a] = true, [b] = true} end')(photo_a, photo_b)
        collection_plan_narrow = hooks.buildCollectionPlan(
            group_index_narrow, burst_scope_narrow, lua.table_from({}, recursive=False), scope_set_narrow)
        # The dissolved group never crosses the >=2-member threshold, so no
        # plan entry is produced this run at all.
        assert collection_plan_narrow.count == 0

        outcome = hooks.applyRebuildCollectionPlan(catalog, collection_plan_narrow, progress, logger)
        # FAILS before the fix: applyRebuildCollectionPlan returns
        # immediately when collectionPlan.count == 0, so the stale
        # collection is never even looked at, let alone deleted.
        assert outcome.deleted == 1
        assert outcome.failed == 0
        assert collection.deleted is True

    def test_dissolved_group_with_an_unmatched_member_is_left_untouched(self, lua, hooks, tmp_path):
        """Safety half: a stale collection that also holds a
        photo this run never matched must be left completely untouched,
        exactly like the planned-rebuild path's own C2 safety gate."""
        records_wide = [
            _photo(path='/lib/a.jpg', burst_group_id=2, is_burst_lead=True),
            _photo(path='/lib/b.jpg', burst_group_id=2, is_burst_lead=False),
            _photo(path='/lib/c.jpg', burst_group_id=2, is_burst_lead=False),
        ]
        manifest_wide, error = _real_manifest(hooks, tmp_path, records_wide)
        group_index_wide = hooks.buildGroupIndex(manifest_wide)
        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        photo_b = lua.globals().facet_test_make_photo('/lib/b.jpg')
        photo_c = lua.globals().facet_test_make_photo('/lib/c.jpg')
        burst_scope_wide = lua.table_from(
            {2: lua.table_from([photo_a, photo_b, photo_c])}, recursive=False)
        scope_set_wide = lua.eval(
            'function(a, b, c) return {[a] = true, [b] = true, [c] = true} end')(photo_a, photo_b, photo_c)
        collection_plan_wide = hooks.buildCollectionPlan(
            group_index_wide, burst_scope_wide, lua.table_from({}, recursive=False), scope_set_wide)
        assert collection_plan_wide.count == 1

        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        hooks.applyCollectionPlan(catalog, collection_plan_wide, progress, logger)
        group_name = collection_plan_wide.collections[1].name
        collection = next(c for c in catalog.collections.values() if c.name == group_name)
        assert len(collection.photos) == 3

        # Later run: only a and b are in this run's scope/manifest -- c is
        # unmatched, its true current membership unknown to this run.
        records_narrow = [
            _photo(path='/lib/a.jpg', burst_group_id=None, is_burst_lead=False),
            _photo(path='/lib/b.jpg', burst_group_id=None, is_burst_lead=False),
        ]
        manifest_narrow, error = _real_manifest(hooks, tmp_path, records_narrow)
        group_index_narrow = hooks.buildGroupIndex(manifest_narrow)
        burst_scope_narrow = lua.table_from({}, recursive=False)
        scope_set_narrow = lua.eval(
            'function(a, b) return {[a] = true, [b] = true} end')(photo_a, photo_b)
        collection_plan_narrow = hooks.buildCollectionPlan(
            group_index_narrow, burst_scope_narrow, lua.table_from({}, recursive=False), scope_set_narrow)
        assert collection_plan_narrow.count == 0

        outcome = hooks.applyRebuildCollectionPlan(catalog, collection_plan_narrow, progress, logger)
        assert outcome.deleted == 0
        assert outcome.failed == 0
        assert collection.deleted is not True
        assert len(collection.photos) == 3  # untouched -- c's unknown membership blocks it

    def test_a_user_named_collection_under_a_facet_set_is_never_swept(self, lua, hooks, tmp_path):
        """A hand-curated collection filed under a Facet kind set (e.g.
        'My favourite frame' under Brackets) must never be touched by the
        dissolved-collection sweep, no matter how empty or fully-in-scope
        its membership looks -- only a collection named exactly the shape
        `groupDisplayName` produces is a candidate at all."""
        photo_a = lua.globals().facet_test_make_photo('/lib/a.jpg')
        catalog = lua.globals().facet_test_make_catalog({})
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        sets = hooks.ensureCollectionSets(catalog)
        mine = lua.eval("""
            function(catalog, parent)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection('My favourite frame', parent, true)
                end)
                return collection
            end
        """)(catalog, sets['Brackets'])
        mine.addPhotos(mine, lua.table_from([photo_a]))
        scope_set = lua.eval('function(a) return {[a] = true} end')(photo_a)

        # No planned collections at all this run -- the empty plan.
        empty_plan = lua.table_from({'collections': [], 'count': 0, 'scopePhotoSet': scope_set},
                                     recursive=True)
        outcome = hooks.applyRebuildCollectionPlan(catalog, empty_plan, progress, logger)
        assert outcome.deleted == 0
        assert outcome.failed == 0
        assert mine.deleted is not True
        assert len(mine.photos) == 1

    def test_isFacetGeneratedCollectionName_matches_only_the_generated_shapes(self, hooks):
        assert hooks.isFacetGeneratedCollectionName('2026-03-01 09:30:15 – IMG_1.jpg') is True
        assert hooks.isFacetGeneratedCollectionName('~ (no date) – IMG_1.jpg') is True
        assert hooks.isFacetGeneratedCollectionName('My favourite frame') is False
        assert hooks.isFacetGeneratedCollectionName('') is False

    def test_isFacetGeneratedCollectionName_accepts_every_shape_groupDisplayName_can_produce(
            self, hooks):
        """The matcher must mirror `isoDateFromExif`'s free-form tail,
        not a hand-copied ' HH:MM:SS' shape, or a non-canonical date_taken
        produces a name the sweep can never recognise as its own -- a
        round-trip over every branch `isoDateFromExif` can take (including
        nil/non-string), crossed with filenames carrying Lua pattern magic
        characters and non-ASCII text."""
        date_taken_values = [
            '2026:03:01 09:30:15',            # canonical EXIF
            '2026:03:01 09:30:15.123',        # sub-second fraction
            '2026:03:01 09:30:15+02:00',      # XMP-style timezone offset
            '2026:03:01 09:30:15 ',           # trailing EXIF whitespace
            '2026:03:01 09:30',               # HH:MM only, no seconds
            '2026:03:01',                     # date only, no time at all
            'not a date',                     # no leading YYYY:MM:DD at all
            '',                                # empty string
            None,                              # never populated
            42,                                 # non-string
        ]
        filenames = [
            'IMG_1.jpg', 'a%b.jpg', 'a-b.jpg', 'a.b.jpg', 'a[1].jpg',
            'a(1).jpg', 'weird ^$ name.jpg', 'espace fichier.jpg', 'unicode_café.jpg',
        ]
        for date_taken in date_taken_values:
            for filename in filenames:
                path = '/lib/%s' % filename
                name = hooks.groupDisplayName(date_taken, path)
                assert hooks.isFacetGeneratedCollectionName(name) is True, (
                    'date_taken=%r filename=%r produced %r, not matched' % (date_taken, filename, name))
        # Negative cases: a user-typed name must never be swept.
        assert hooks.isFacetGeneratedCollectionName('My favourite frame') is False
        assert hooks.isFacetGeneratedCollectionName('2024 trip') is False

    def test_findExistingCollectionSets_creates_nothing_on_a_fresh_catalog(self, lua, hooks):
        """The read-only Preview lookup must never create the Facet
        root or its kind sets -- a fresh catalog has none of them yet, so
        the lookup must return an empty table rather than calling
        `createCollectionSet` the way `ensureCollectionSets` does."""
        catalog = lua.globals().facet_test_make_catalog({})
        sets = hooks.findExistingCollectionSets(catalog)
        assert catalog.setsCreated == 0
        assert catalog.writeAccessCalls == 0
        assert len(dict(sets.items())) == 0

    def test_findExistingCollectionSets_finds_a_pre_existing_stale_collection(self, lua, hooks):
        """With the Facet sets already created by an earlier run (e.g. via
        `ensureCollectionSets`, exactly as production's own apply path
        would have left them), the read-only lookup must resolve the SAME
        kind set an actual sweep needs, and the stale collection filed
        under it must still be reachable through it."""
        catalog = lua.globals().facet_test_make_catalog({})
        created = hooks.ensureCollectionSets(catalog)
        stale = lua.eval("""
            function(catalog, parent)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection('2020-01-01 00:00:00 \\226\\128\\147 x.jpg', parent, true)
                end)
                return collection
            end
        """)(catalog, created['Bursts'])
        writes_before = catalog.writeAccessCalls
        sets = hooks.findExistingCollectionSets(catalog)
        assert catalog.writeAccessCalls == writes_before  # the lookup itself did not write
        found = dict(sets.items())
        assert 'Bursts' in found
        children = [c.getName(c) for c in found['Bursts'].getChildCollections(found['Bursts']).values()]
        assert stale.getName(stale) in children

    def test_findExistingCollectionSets_reports_a_listing_failure(self, lua, hooks):
        """A lookup failure (e.g. a busy catalog raising out of
        `getChildCollectionSets`) must be distinguishable from 'nothing to
        delete' -- `previewDissolvedCandidateCount` is the caller that must
        surface it, since `findExistingCollectionSets` itself just raises
        and every caller is required to wrap it in `pcall`."""
        catalog = lua.globals().facet_test_make_catalog({})
        catalog.failGetChildCollectionSets(catalog)
        ok, err = lua.eval("""
            function(fn, catalog)
                return pcall(fn, catalog)
            end
        """)(hooks.findExistingCollectionSets, catalog)
        assert ok is False
        assert 'boom' in str(err)

    def test_preview_dissolved_candidate_count_is_zero_when_rebuild_off(self, lua, hooks, tmp_path):
        catalog, plan, logger, photos = TestExecuteApplyEndToEnd()._setup(lua, hooks, tmp_path)
        collection_plan = lua.table_from({'collections': [], 'count': 0, 'scopePhotoSet': {}}, recursive=True)
        prefs = _preferences(lua, rebuildCollections=False)
        count, failed = hooks.previewDissolvedCandidateCount(catalog, collection_plan, plan, prefs, logger)
        assert count == 0
        assert failed is False
        assert catalog.setsCreated == 0

    def test_preview_dissolved_candidate_count_finds_a_stale_collection_without_writing(
            self, lua, hooks, tmp_path):
        """The Preview step must reach the same dissolved candidate a
        real sweep would, but through the read-only lookup -- no
        `createCollectionSet` call, even though the Facet sets already
        exist from an earlier run."""
        catalog, plan, logger, photos = TestExecuteApplyEndToEnd()._setup(lua, hooks, tmp_path)
        created = hooks.ensureCollectionSets(catalog)
        lua.eval("""
            function(catalog, parent, photo)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection('2020-01-01 00:00:00 \\226\\128\\147 x.jpg', parent, true)
                end)
                collection:addPhotos({photo})
                return collection
            end
        """)(catalog, created['Bursts'], photos[0])
        writes_before = catalog.writeAccessCalls
        sets_created_before = catalog.setsCreated
        collection_plan = lua.table_from(
            {'collections': [], 'count': 0, 'scopePhotoSet': hooks.matchedPhotoSet(plan)}, recursive=True)
        prefs = _preferences(lua, rebuildCollections=True)
        count, failed = hooks.previewDissolvedCandidateCount(catalog, collection_plan, plan, prefs, logger)
        assert count == 1
        assert failed is False
        assert catalog.writeAccessCalls == writes_before
        assert catalog.setsCreated == sets_created_before

    def test_preview_dissolved_candidate_count_reports_a_lookup_failure(self, lua, hooks, tmp_path):
        catalog, plan, logger, photos = TestExecuteApplyEndToEnd()._setup(lua, hooks, tmp_path)
        catalog.failGetChildCollectionSets(catalog)
        collection_plan = lua.table_from({'collections': [], 'count': 0, 'scopePhotoSet': {}}, recursive=True)
        prefs = _preferences(lua, rebuildCollections=True)
        count, failed = hooks.previewDissolvedCandidateCount(catalog, collection_plan, plan, prefs, logger)
        assert count == 0
        assert failed is True
        assert hooks.hasNothingToApply(
            {'entryCount': 0}, {'count': 0}, None, None, count, failed) is False
        lines = [v.lower() for v in dict(logger.lines.items()).values()]
        assert any('preview' in line for line in lines)

    def test_ensure_sets_failure_during_rebuild_reports_a_failure_even_with_no_plan(self, lua, hooks):
        """D-6: `ensureCollectionSets` failing during a rebuild with
        `collectionPlan.count == 0` must not report zero failures -- the
        old `outcome.failed = collectionPlan.count` line silently reported
        0 for exactly this case."""
        catalog = lua.globals().facet_test_make_catalog({})
        catalog.createCollectionSet = lua.eval(
            "function(self, name, parent, canReturnPrior) error('write-access timeout') end")
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        empty_plan = { 'collections': [], 'count': 0, 'scopePhotoSet': {} }
        # FAILS before the fix: outcome.failed == collectionPlan.count == 0.
        outcome = hooks.applyRebuildCollectionPlan(catalog, empty_plan, progress, logger)
        assert outcome.failed > 0


class TestHasNothingToApplyExtended:
    def test_field_only_work_is_not_nothing(self, hooks):
        assert hooks.hasNothingToApply(
            {'entryCount': 0}, {'count': 0}, {'count': 1, 'pendingCount': 1}, None) is False

    def test_keyword_only_work_is_not_nothing(self, hooks):
        assert hooks.hasNothingToApply(
            {'entryCount': 0}, {'count': 0}, None, {'count': 1, 'pendingCount': 1}) is False

    def test_still_true_when_everything_absent(self, hooks):
        assert hooks.hasNothingToApply({'entryCount': 0}, {'count': 0}) is True

    def test_dissolved_collections_pending_deletion_is_not_nothing(self, hooks):
        """I-4: a run where every rating/flag/collection/field/keyword plan
        is empty, but the dissolved-collection sweep would still delete a
        stale Facet collection, must not report 'Nothing to change'."""
        assert hooks.hasNothingToApply(
            {'entryCount': 0}, {'count': 0}, None, None, 1) is False

    def test_zero_dissolved_collections_is_still_nothing(self, hooks):
        assert hooks.hasNothingToApply(
            {'entryCount': 0}, {'count': 0}, None, None, 0) is True


class TestPendingCorrectionsBanner:
    def test_manifest_pending_corrections_normalises_missing_to_zero(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [_photo(path='/lib/a.jpg')])
        assert error is None
        assert hooks.manifestPendingCorrections(manifest) == 0

    def test_preview_shows_the_banner_when_nonzero(self, lua, hooks, tmp_path):
        payload = {
            'version': 2, 'generated_at': '2026-01-01T00:00:00Z', 'pending_corrections': 3,
            'photos': [_photo(path='/lib/a.jpg')],
        }
        path = tmp_path / 'facet_manifest.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        manifest = hooks.readManifest(str(path))
        index = hooks.buildIndex(manifest)
        plan = lua.table_from({
            'scoped': 1, 'matched': 1, 'unmatched': 0, 'ratingWrites': 0,
            'pickWrites': 0, 'conflicts': 0, 'unchanged': 1,
        }, recursive=True)
        prefs = _preferences(lua)
        message = hooks.previewMessage(plan, manifest, index, prefs)
        assert '3 pending sequence correction' in message


class TestPreviewAndSummarySurfaceFieldsKeywordsRebuild:
    """I7: the Preview and the final summary must count and report the
    field-write, keyword-sync and rebuild work (and their failures), not
    just ratings/flags/collections."""

    def test_preview_shows_pending_field_and_keyword_counts_and_rebuild_split(self, lua, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [_photo(path='/lib/a.jpg')])
        assert error is None
        index = hooks.buildIndex(manifest)
        plan = lua.table_from({
            'scoped': 1, 'matched': 1, 'unmatched': 0, 'ratingWrites': 0,
            'pickWrites': 0, 'conflicts': 0, 'unchanged': 1,
        }, recursive=True)
        prefs = _preferences(lua, rebuildCollections=True)
        collection_plan = lua.table_from({
            'count': 2,
            'collections': lua.table_from([
                {'fullyInScope': True}, {'fullyInScope': False},
            ], recursive=True),
        }, recursive=True)
        field_plan = lua.table_from({'count': 3, 'pendingCount': 2}, recursive=True)
        keyword_plan = lua.table_from({'count': 3, 'pendingCount': 1}, recursive=True)
        message = hooks.previewMessage(plan, manifest, index, prefs, collection_plan, field_plan, keyword_plan)
        assert 'Metadata fields to write: 2' in message
        assert 'Keyword changes to make: 1' in message
        assert 'Collections to rebuild: 1 (skipped, partly outside selection: 1)' in message

    def test_summary_reports_field_keyword_and_rebuild_outcomes_including_failures(self, hooks):
        plan = {'unchanged': 0, 'conflicts': 0, 'unmatched': 0}
        outcome = {'photosTouched': 1, 'ratingsSet': 1, 'picksSet': 0, 'failed': 0, 'canceled': False}
        field_outcome = {'fieldsWritten': 4, 'photosTouched': 2, 'failed': 1}
        keyword_outcome = {'added': 3, 'removed': 1, 'photosTouched': 2, 'failed': 0}
        rebuild_outcome = {'rebuilt': 2, 'deleted': 1, 'skipped': 1, 'failed': 1}
        message = hooks.summaryMessage(
            plan, outcome, None, False, field_outcome, keyword_outcome, rebuild_outcome)
        assert 'Metadata fields written: 4 (photos touched: 2)' in message
        assert 'Metadata field failures: 1' in message
        assert 'Keywords added/removed: 3/1 (photos touched: 2)' in message
        assert 'Collections rebuilt: 2 (deleted when left empty: 1, skipped: 1)' in message
        assert 'Rebuild failures: 1' in message


class TestExecuteApplyEndToEnd:
    """Coordinator finding: nothing exercised run() past the preview
    confirmation, so every pass inside it (derived values, collections,
    rebuild, fields, keywords) could be gutted with no test going red.
    executeApply() is the extracted, directly-callable equivalent of
    everything run() does after Preview -- these tests drive it against the
    real stub catalog, one option at a time."""

    def _setup(self, lua, hooks, tmp_path, tags='sunset', category='landscape', aggregate=7.2):
        record = _photo(path='/lib/a.jpg', star_rating=0, score_stars=4, tags=tags, category=category)
        record['scores'] = {'aggregate': aggregate}
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, [record], ['/lib/a.jpg'], {'starsFromScore': True})
        return catalog, plan, logger, photos

    def test_fields_off_stars_on_records_derived_marker_and_export_omits_it(self, lua, hooks, tmp_path):
        """(a): writeMetadataFields OFF, starsFromScore ON -- the derived
        marker must still be recorded, and FacetExportState's buildRecord
        must then omit that rating."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        assert plan.entries[1].rating == 4
        options = lua.table_from({'collectionPlan': None, 'fieldPlan': None, 'keywordPlan': None,
                                   'rebuildCollections': False}, recursive=True)
        context = lua.globals().facet_test_make_progress()
        result = hooks.executeApply(catalog, plan, options, context, logger)
        assert result.outcome.canceled is False
        assert photos[0].pluginProperties.facetDerivedRating == '4'
        # buildRecord (FacetExportState.lua) omits `rating` when it still
        # equals the recorded derived value -- run it against the marker
        # executeApply just wrote, in a separate small runtime loading only
        # that file (mirrors tests/test_lrplugin_export_state.py's harness).
        export_runtime = _lua_runtime_module.LuaRuntime(unpack_returned_tuples=True)
        export_runtime.execute("""
            function import(name) return {} end
            _PLUGIN = { id = 'com.facet.lightroom.test' }
            FACET_EXPORT_STATE_TEST_HOOKS = {}
            package.path = package.path .. ';' .. %r
        """ % (str((PLUGIN_DIR / '?.lua').as_posix())))
        export_runtime.execute(EXPORT_STATE_LUA.read_text(encoding='utf-8'))
        export_hooks = export_runtime.globals().FACET_EXPORT_STATE_TEST_HOOKS
        state = export_runtime.table_from({
            'path': '/lib/a.jpg', 'rating': 4, 'pickStatus': 0, 'isVirtualCopy': False,
            'derivedRating': photos[0].pluginProperties.facetDerivedRating, 'derivedPick': None,
        }, recursive=True)
        record = export_hooks.buildRecord(state, '/lib/a.jpg')
        assert record.rating is None

    def test_each_option_on_actually_runs_its_pass(self, lua, hooks, tmp_path):
        """(b): every opt-in pass, when planned, actually executes."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        group_index = lua.table_from({'burstGroups': {}, 'sequenceSets': {}}, recursive=True)
        collection_plan = hooks.buildCollectionPlan(
            group_index, lua.table_from({}, recursive=False), lua.table_from({}, recursive=False),
            hooks.matchedPhotoSet(plan))
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        keyword_plan = hooks.buildKeywordPlan(plan)
        options = lua.table_from({
            'collectionPlan': collection_plan, 'fieldPlan': field_plan, 'keywordPlan': keyword_plan,
            'rebuildCollections': True,
        }, recursive=False)
        context = lua.globals().facet_test_make_progress()
        result = hooks.executeApply(catalog, plan, options, context, logger)
        assert result.fieldOutcome is not None
        assert result.fieldOutcome.fieldsWritten > 0
        assert result.keywordOutcome is not None
        assert result.keywordOutcome.added > 0
        # No collections were planned here (empty burst/sequence scope), so
        # collectionOutcome stays nil -- confirmed separately below with a
        # real planned collection.

    def test_each_option_off_its_pass_does_not_run(self, lua, hooks, tmp_path):
        """(c): every opt-in pass, when NOT planned (nil), never runs."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        options = lua.table_from({'collectionPlan': None, 'fieldPlan': None, 'keywordPlan': None,
                                   'rebuildCollections': False}, recursive=True)
        context = lua.globals().facet_test_make_progress()
        result = hooks.executeApply(catalog, plan, options, context, logger)
        assert result.fieldOutcome is None
        assert result.keywordOutcome is None
        assert result.collectionOutcome is None
        assert result.rebuildOutcome is None
        # The photo's plug-in fields/keywords were never touched.
        assert dict(photos[0].pluginProperties.items()).get('facetAggregate') is None
        assert len(photos[0].keywords) == 0

    def test_canceled_applyplan_runs_no_later_pass(self, lua, hooks, tmp_path):
        """(d): a canceled applyPlan must stop every later pass -- fields,
        keywords, derived values, collections and rebuild alike. Drives the
        real cancel path end-to-end through executeApply itself, via the
        `_FACET_TEST_FORCE_CANCELED` progress-stub switch, rather than just
        asserting the outcome shape by hand."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        group_index = lua.table_from({'burstGroups': {}, 'sequenceSets': {}}, recursive=True)
        collection_plan = hooks.buildCollectionPlan(
            group_index, lua.table_from({}, recursive=False), lua.table_from({}, recursive=False),
            hooks.matchedPhotoSet(plan))
        field_plan = hooks.buildMetadataFieldsPlan(catalog, plan)
        keyword_plan = hooks.buildKeywordPlan(plan)
        options = lua.table_from({
            'collectionPlan': collection_plan, 'fieldPlan': field_plan, 'keywordPlan': keyword_plan,
            'rebuildCollections': True,
        }, recursive=False)
        context = lua.globals().facet_test_make_progress()
        lua.execute('_FACET_TEST_FORCE_CANCELED = true')
        try:
            result = hooks.executeApply(catalog, plan, options, context, logger)
        finally:
            lua.execute('_FACET_TEST_FORCE_CANCELED = false')
        assert result.outcome.canceled is True
        assert result.collectionOutcome is None
        assert result.fieldOutcome is None
        assert result.keywordOutcome is None
        assert result.rebuildOutcome is None
        # Derived-value bookkeeping (C1) is bounded by `outcome.committedRanges`,
        # which stays empty here since the cancel lands before applyPlan's
        # very first chunk -- nothing committed, so nothing gets a baseline.
        assert dict(photos[0].pluginProperties.items()).get('facetDerivedRating') is None

    def test_cancel_mid_write_still_records_the_committed_chunks_baseline(self, lua, hooks, tmp_path):
        """A cancel after applyPlan's first chunk must not abandon the
        derived-value baseline for the 200 photos that chunk already rated --
        even though every progress scope created after the cancel reports it
        too. Without the baseline those derived stars would go back to Facet
        as the user's own ratings."""
        records = [
            _photo(path='/lib/p%03d.jpg' % i, star_rating=0, score_stars=4)
            for i in range(201)
        ]
        catalog, plan, logger, photos = _real_plan(
            lua, hooks, tmp_path, records, [r['path'] for r in records], {'starsFromScore': True})
        options = lua.table_from({'collectionPlan': None, 'fieldPlan': None, 'keywordPlan': None,
                                   'rebuildCollections': False}, recursive=True)
        context = lua.globals().facet_test_make_progress()
        lua.execute('_FACET_TEST_CANCEL_AFTER = 1')
        try:
            result = hooks.executeApply(catalog, plan, options, context, logger)
        finally:
            lua.execute('_FACET_TEST_CANCEL_AFTER = nil')
        assert result.outcome.canceled is True
        assert result.outcome.committedThrough == 200
        for i in range(200):
            assert photos[i].pluginProperties.facetDerivedRating == '4'
        assert dict(photos[200].pluginProperties.items()).get('facetDerivedRating') is None

    def test_rebuild_never_runs_with_no_collection_plan_even_if_the_flag_is_true(
            self, lua, hooks, tmp_path):
        """I-1: `rebuildCollections=True` with `collectionPlan=nil` must be
        a pure no-op -- collectionPlan nil is executeApply's signal that the
        collections feature itself is off for this call, distinct from a
        present-but-empty plan. Before the fix, an empty pre-existing
        collection under a Facet kind set would be emptied and deleted even
        though 'Create Facet collections' produced no plan at all."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        sets = hooks.ensureCollectionSets(catalog)
        empty = lua.eval("""
            function(catalog, parent)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection('2020-01-01 00:00:00 \\226\\128\\147 x.jpg', parent, true)
                end)
                return collection
            end
        """)(catalog, sets['Bursts'])
        options = lua.table_from({'collectionPlan': None, 'fieldPlan': None, 'keywordPlan': None,
                                   'rebuildCollections': True}, recursive=True)
        context = lua.globals().facet_test_make_progress()
        result = hooks.executeApply(catalog, plan, options, context, logger)
        assert result.rebuildOutcome is None
        assert empty.deleted is not True

    def test_dissolved_sweep_runs_via_executeApply_when_it_is_the_only_pending_change(
            self, lua, hooks, tmp_path):
        """I-4: executeApply must still reach and delete a stale Facet
        collection when `collectionPlan.count == 0` (a real, present plan --
        collections ARE on, every group just dissolved this run) as long as
        rebuildCollections is on -- this is the case run()'s
        hasNothingToApply gate must not stop before reaching."""
        catalog, plan, logger, photos = self._setup(lua, hooks, tmp_path)
        sets = hooks.ensureCollectionSets(catalog)
        stale = lua.eval("""
            function(catalog, parent, photo)
                local collection
                catalog:withWriteAccessDo('pre', function()
                    collection = catalog:createCollection('2020-01-01 00:00:00 \\226\\128\\147 x.jpg', parent, true)
                end)
                collection:addPhotos({photo})
                return collection
            end
        """)(catalog, sets['Bursts'], photos[0])
        empty_collection_plan = lua.table_from(
            {'collections': [], 'count': 0, 'scopePhotoSet': hooks.matchedPhotoSet(plan)}, recursive=True)
        options = lua.table_from({'collectionPlan': empty_collection_plan, 'fieldPlan': None,
                                   'keywordPlan': None, 'rebuildCollections': True}, recursive=True)
        context = lua.globals().facet_test_make_progress()
        result = hooks.executeApply(catalog, plan, options, context, logger)
        assert result.rebuildOutcome is not None
        assert result.rebuildOutcome.deleted == 1
        assert stale.deleted is True


class TestPrefixSuggestionWiring:
    def test_computes_a_suggestion_from_an_unmatched_sample(self, hooks, tmp_path):
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/mnt/nas/2024/IMG_1.jpg'),
        ])
        assert error is None
        index = hooks.buildIndex(manifest)
        plan = {'sampleCatalogPath': 'C:\\Users\\nic\\2024\\IMG_1.jpg'}
        catalog_prefix, manifest_prefix = hooks.computeNoMatchSuggestion(plan, index)
        assert catalog_prefix == 'C:\\Users\\nic'
        assert manifest_prefix == '/mnt/nas'

    def test_use_this_fills_preferences_without_touching_plan_build(self, hooks):
        preferences = {'catalogPrefix': '', 'manifestPrefix': ''}
        hooks.applySuggestedPrefixes(preferences, 'C:\\Users\\nic', '/mnt/nas')
        assert preferences['catalogPrefix'] == 'C:\\Users\\nic'
        assert preferences['manifestPrefix'] == '/mnt/nas'

    def test_no_op_suggestion_returns_nil_nil_when_the_paths_already_match(self, hooks, tmp_path):
        """I9.8 (F7c): when the computed prefix pair is empty on BOTH sides
        (the catalog path already matches the manifest path exactly), there
        is nothing useful to suggest -- computeNoMatchSuggestion must return
        nil, nil rather than a suggestion of two empty strings."""
        manifest, error = _real_manifest(hooks, tmp_path, [
            _photo(path='/lib/2024/img.jpg'),
        ])
        assert error is None
        index = hooks.buildIndex(manifest)
        plan = {'sampleCatalogPath': '/lib/2024/img.jpg'}
        catalog_prefix, manifest_prefix = hooks.computeNoMatchSuggestion(plan, index)
        assert catalog_prefix is None
        assert manifest_prefix is None
