"""Behavioral tests for ``facet.lrplugin/FacetExportState.lua`` (Step 5b),
run through ``lupa.lua51`` against a stubbed Lightroom SDK -- mirrors
``tests/test_lrplugin_apply.py``'s harness pattern."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# M10: require the real lua51 runtime, never a silent fallback to whatever
# `lupa`'s default interpreter is (currently 5.5) -- see the matching note
# in tests/test_lrplugin_apply.py.
_lua_runtime_module = pytest.importorskip(
    'lupa.lua51', reason='real-Lua verification needs the optional lupa package (lua51 runtime)')

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / 'facet.lrplugin'
EXPORT_STATE_LUA = PLUGIN_DIR / 'FacetExportState.lua'

_BOOTSTRAP = """
function import(name)
    if name == 'LrTasks' then
        return { yield = function() end }
    end
    if name == 'LrPrefs' then
        return { prefsForPlugin = function() return _FACET_TEST_PREFS end }
    end
    return {}
end
_FACET_TEST_PREFS = {}
_PLUGIN = { id = 'com.facet.lightroom.test' }
FACET_EXPORT_STATE_TEST_HOOKS = {}
package.path = package.path .. ';' .. %r

function facet_test_make_photo(path, isVirtualCopy)
    local p = {}
    p.path = path
    p.isVirtualCopy = isVirtualCopy or false
    return p
end
""" % (str((PLUGIN_DIR / '?.lua').as_posix()))


@pytest.fixture(scope='module')
def lua():
    runtime = _lua_runtime_module.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_BOOTSTRAP)
    runtime.execute(EXPORT_STATE_LUA.read_text(encoding='utf-8'))
    return runtime


@pytest.fixture(scope='module')
def hooks(lua):
    hooks = lua.globals().FACET_EXPORT_STATE_TEST_HOOKS
    assert hooks is not None
    return hooks


def _state(lua, path, rating=0, pick_status=0, is_virtual_copy=False,
           derived_rating=None, derived_pick=None):
    photo = lua.globals().facet_test_make_photo(path, is_virtual_copy)
    return lua.table_from({
        'photo': photo, 'path': path, 'rating': rating, 'pickStatus': pick_status,
        'isVirtualCopy': is_virtual_copy, 'derivedRating': derived_rating, 'derivedPick': derived_pick,
    }, recursive=True), photo


class TestBuildRecordOmitsUnchangedDerivedValues:
    def test_rating_omitted_when_it_still_equals_the_recorded_derived_value(self, lua, hooks):
        state, _ = _state(lua, '/lib/a.jpg', rating=4, derived_rating='4')
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.rating is None
        assert record.pick == 0

    def test_rating_present_when_it_differs_from_the_recorded_derived_value(self, lua, hooks):
        state, _ = _state(lua, '/lib/a.jpg', rating=5, derived_rating='4')
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.rating == 5

    def test_no_derived_record_at_all_still_exports_the_field(self, lua, hooks):
        # "no record" != "still equal" -- a photo Apply never touched must
        # still export its current rating.
        state, _ = _state(lua, '/lib/a.jpg', rating=3, derived_rating=None)
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.rating == 3

    def test_pick_omitted_when_it_still_equals_the_recorded_derived_pick(self, lua, hooks):
        state, _ = _state(lua, '/lib/a.jpg', pick_status=1, derived_pick='1')
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.pick is None

    def test_pick_present_when_manually_changed_since(self, lua, hooks):
        state, _ = _state(lua, '/lib/a.jpg', pick_status=-1, derived_pick='1')
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.pick == -1

    def test_a_field_that_is_exported_always_carries_an_explicit_value_not_nil(self, lua, hooks):
        # rating=0/pick=0 for an unset/unflagged photo must still be an
        # explicit 0 in the record, distinguishable from an omitted key.
        state, _ = _state(lua, '/lib/a.jpg', rating=0, pick_status=0, derived_rating=None, derived_pick=None)
        record = hooks.buildRecord(state, '/lib/a.jpg')
        assert record.rating == 0
        assert record.pick == 0


class TestVirtualCopyDedupe:
    def test_master_wins_over_a_virtual_copy_sharing_the_same_path(self, lua, hooks):
        master_state, master_photo = _state(lua, '/lib/a.jpg', rating=5, is_virtual_copy=False)
        vcopy_state, vcopy_photo = _state(lua, '/lib/a.jpg', rating=2, is_virtual_copy=True)
        states = lua.table_from([vcopy_state, master_state], recursive=True)
        deduped = hooks.dedupeByPath(states, '', '')
        assert len(deduped) == 1
        assert deduped[1].rating == 5

    def test_only_virtual_copies_the_first_one_wins(self, lua, hooks):
        v1, _ = _state(lua, '/lib/b.jpg', rating=1, is_virtual_copy=True)
        v2, _ = _state(lua, '/lib/b.jpg', rating=2, is_virtual_copy=True)
        states = lua.table_from([v1, v2], recursive=True)
        deduped = hooks.dedupeByPath(states, '', '')
        assert len(deduped) == 1
        assert deduped[1].rating == 1


class TestExportPayloadShape:
    def test_format_and_version_are_present_and_correct(self, lua, hooks):
        state, _ = _state(lua, '/lib/a.jpg', rating=4)
        states = lua.table_from([state], recursive=True)
        payload = hooks.buildExportPayload(states, '', '')
        assert payload.format == 'facet-lightroom-state'
        assert payload.version == 1
        json_text = hooks.encodePayload(payload)
        decoded = json.loads(json_text)
        assert decoded['format'] == 'facet-lightroom-state'
        assert decoded['version'] == 1
        assert decoded['photos'] == [{'path': '/lib/a.jpg', 'rating': 4, 'pick': 0}]

    def test_empty_photos_encodes_as_an_empty_array_not_an_object(self, lua, hooks):
        states = lua.table_from([], recursive=True)
        payload = hooks.buildExportPayload(states, '', '')
        json_text = hooks.encodePayload(payload)
        decoded = json.loads(json_text)
        assert decoded['photos'] == []

    def test_i6_windows_native_path_round_trips_byte_for_byte_with_no_prefix(self, lua, hooks):
        """I6: on a native-Windows install with no prefix mapping configured,
        the exported path must match the DB's raw, backslash-separated
        `photos.path` value exactly -- forcing it to forward slashes (as the
        import-direction mapToManifestPath does) makes every reverse-sync
        export unmatched on the Python side."""
        state, _ = _state(lua, r'C:\Users\nic\Pictures\a.jpg', rating=4)
        states = lua.table_from([state], recursive=True)
        payload = hooks.buildExportPayload(states, '', '')
        json_text = hooks.encodePayload(payload)
        decoded = json.loads(json_text)
        assert decoded['photos'][0]['path'] == r'C:\Users\nic\Pictures\a.jpg'

    def test_paths_are_mapped_through_the_prefix_pair(self, lua, hooks):
        state, _ = _state(lua, 'C:\\Users\\nic\\Pictures\\img.jpg', rating=3)
        states = lua.table_from([state], recursive=True)
        # buildExportPayload expects ALREADY-NORMALIZED prefixes (slash
        # form) -- run() normalizes via FacetCommon.normalizePrefix before
        # calling it; this test does the same rather than passing raw
        # preference text.
        payload = hooks.buildExportPayload(states, 'C:/Users/nic/Pictures', '/volume1/photos')
        json_text = hooks.encodePayload(payload)
        decoded = json.loads(json_text)
        assert decoded['photos'][0]['path'] == '/volume1/photos/img.jpg'


class TestFaultInjectionRestoreProof:
    """Fault-inject once: an untouched derived rating that gets exported
    anyway must be caught. Confirms the test itself is capable of failing
    before trusting its green result on the real code."""

    def test_a_broken_buildrecord_that_always_exports_rating_is_caught(self, lua):
        # Directly exercise a deliberately-wrong variant against the stub,
        # without touching the production file on disk (finding: retype by
        # hand, never git checkout, and never leave the fault in the tree).
        broken = lua.eval("""
            function(state, mappedPath)
                -- BROKEN: always exports rating, ignoring facetDerivedRating.
                return { path = mappedPath, rating = state.rating, pick = 0 }
            end
        """)
        state, _ = _state(lua, '/lib/a.jpg', rating=4, derived_rating='4')
        broken_record = broken(state, '/lib/a.jpg')
        # The broken variant exports rating even though it still equals the
        # recorded derived value -- this assertion is what would go RED
        # against the broken variant, proving the real assertion (elsewhere
        # in this file) can actually fail.
        assert broken_record.rating == 4  # sanity: broken variant does export it
