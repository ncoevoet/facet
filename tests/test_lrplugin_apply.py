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
    -- Collection SDK stub: canReturnPrior semantics are modelled by keying
    -- on (parent, name), so a re-run resolves the same set/collection object
    -- rather than creating a duplicate -- the real finding this stub exists
    -- to exercise.
    c.sets = {}
    c.collections = {}
    c.setsCreated = 0
    c.collectionsCreated = 0
    c.writeAccessCalls = 0
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
    c.createCollectionSet = function(self, name, parent, canReturnPrior)
        local key = tostring(parent) .. '|' .. name
        local existing = self.sets[key]
        if existing then
            return existing
        end
        local set = { name = name, parent = parent }
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
        local collection = { name = name, parent = parent, photos = {} }
        collection.addPhotos = function(self2, photos)
            for _, photo in ipairs(photos) do
                self2.photos[#self2.photos + 1] = photo
            end
        end
        self.collections[key] = collection
        self.collectionsCreated = self.collectionsCreated + 1
        return collection
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
        manifest, error = _real_manifest(hooks, tmp_path, records)
        assert error is None
        index = hooks.buildIndex(manifest)
        group_index = hooks.buildGroupIndex(manifest)

        by_photo = lua.table()
        photos = []
        for path in in_scope_paths:
            photo = lua.globals().facet_test_make_photo(path)
            values = lua.table_from({'path': path, 'rating': 0, 'pickStatus': 0}, recursive=True)
            by_photo[photo] = values
            photos.append(photo)
        catalog = lua.globals().facet_test_make_catalog(by_photo)
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        prefs = _preferences(lua, **prefs_extra)
        plan = hooks.buildPlan(catalog, lua.table_from(photos), index, group_index, prefs, progress, logger)
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
        manifest, error = _real_manifest(hooks, tmp_path, [record])
        assert error is None
        index = hooks.buildIndex(manifest)
        group_index = hooks.buildGroupIndex(manifest)
        photo = lua.globals().facet_test_make_photo(record['path'])
        values = lua.table_from({'path': record['path'], 'rating': current_rating, 'pickStatus': 0},
                                 recursive=True)
        by_photo = lua.table()
        by_photo[photo] = values
        catalog = lua.globals().facet_test_make_catalog(by_photo)
        progress = lua.globals().facet_test_make_progress()
        logger = lua.globals().facet_test_make_logger()
        prefs = _preferences(lua, overwrite=overwrite, starsFromScore=stars_from_score)
        return hooks.buildPlan(catalog, lua.table_from([photo]), index, group_index, prefs, progress, logger)

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
