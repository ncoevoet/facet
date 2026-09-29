"""Pure-Lua coverage for ``FacetCommon.suggestPrefixPair`` (Step 6c), run
through ``lupa.lua51`` directly -- no stub catalog needed, since the helper
is a pure string function."""

from __future__ import annotations

from pathlib import Path

import pytest

# M10: require the real lua51 runtime, never a silent fallback to whatever
# `lupa`'s default interpreter is (currently 5.5) -- see the matching note
# in tests/test_lrplugin_apply.py.
_lua_runtime_module = pytest.importorskip(
    'lupa.lua51', reason='real-Lua verification needs the optional lupa package (lua51 runtime)')

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / 'facet.lrplugin'


@pytest.fixture(scope='module')
def facet_common():
    runtime = _lua_runtime_module.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute("""
        function import(name) return {} end
        package.path = package.path .. ';' .. %r
    """ % (str((PLUGIN_DIR / '?.lua').as_posix())))
    return runtime.execute("return require('FacetCommon')")


@pytest.fixture(scope='module')
def suggest(facet_common):
    return facet_common.suggestPrefixPair


class TestSuggestPrefixPair:
    def test_windows_catalog_backslashes_preserved_on_each_side(self, suggest):
        catalog_prefix, manifest_prefix = suggest(
            r'C:\Users\nic\Pictures\2024\IMG_001.CR2', '/mnt/nas/2024/IMG_001.CR2')
        assert catalog_prefix == r'C:\Users\nic\Pictures'
        assert manifest_prefix == '/mnt/nas'

    def test_no_filename_match_returns_nil_nil(self, suggest):
        catalog_prefix, manifest_prefix = suggest(
            '/a/b/one.jpg', '/x/y/two.jpg')
        assert catalog_prefix is None
        assert manifest_prefix is None

    def test_already_matching_prefixes_return_empty_strings(self, suggest):
        catalog_prefix, manifest_prefix = suggest('/lib/2024/img.jpg', '/lib/2024/img.jpg')
        assert catalog_prefix == ''
        assert manifest_prefix == ''

    def test_non_string_inputs_return_nil_nil(self, suggest):
        catalog_prefix, manifest_prefix = suggest(None, '/x/y.jpg')
        assert catalog_prefix is None
        assert manifest_prefix is None

    def test_m2_unc_leading_double_separator_is_preserved_verbatim(self, suggest):
        """M2: a UNC catalog path starts with a RUN of two separators, not
        one -- dropping to a single leading backslash turns '\\\\NAS\\...'
        into '\\NAS\\...', which normalizes to '/NAS/...' and never
        prefix-matches '//NAS/...' again."""
        catalog_prefix, manifest_prefix = suggest(
            r'\\NAS\photos\2024\IMG_1.CR2', '/volume1/photos/2024/IMG_1.CR2')
        assert catalog_prefix == r'\\NAS'
        assert manifest_prefix == '/volume1'

    def test_m2_posix_double_slash_unc_style_is_also_preserved(self, suggest):
        catalog_prefix, manifest_prefix = suggest(
            '//NAS/photos/2024/IMG_1.CR2', '/volume1/photos/2024/IMG_1.CR2')
        assert catalog_prefix == '//NAS'
        assert manifest_prefix == '/volume1'


class TestMapToManifestPathComponentBoundary:
    """M3: the prefix match requires a path-component boundary right after
    the prefix -- a bare string-prefix match would let '/Volumes/Photos'
    also match the unrelated sibling folder '/Volumes/Photos2/...'."""

    def test_sibling_folder_with_a_longer_name_is_not_mismatched(self, facet_common):
        result = facet_common.mapToManifestPath(
            '/Volumes/Photos2/a.jpg', '/Volumes/Photos', '/data2')
        # Before the fix this would incorrectly become '/data2/2/a.jpg'.
        assert result == '/Volumes/Photos2/a.jpg'

    def test_exact_component_boundary_still_maps(self, facet_common):
        result = facet_common.mapToManifestPath(
            '/Volumes/Photos/a.jpg', '/Volumes/Photos', '/data2')
        assert result == '/data2/a.jpg'

    def test_prefix_equal_to_the_whole_path_still_maps(self, facet_common):
        result = facet_common.mapToManifestPath(
            '/Volumes/Photos', '/Volumes/Photos', '/data2')
        assert result == '/data2'


class TestMapPathForExport:
    """I6: the reverse-sync exporter must round-trip the RAW, native-
    separator path when no prefix mapping is configured, so it matches the
    `photos.path` column's exact stored value (including on a native
    Windows install) -- unlike mapToManifestPath, which always forces
    forward slashes for the (different) import-direction match against the
    manifest's own forward-slash paths."""

    def test_windows_path_is_returned_byte_for_byte_with_no_prefix_configured(self, facet_common):
        result = facet_common.mapPathForExport(r'C:\Users\nic\Pictures\a.jpg', '', '')
        assert result == r'C:\Users\nic\Pictures\a.jpg'

    def test_prefix_mapping_still_normalises_when_configured(self, facet_common):
        # catalogPrefix/manifestPrefix arrive already normalised (forward
        # slashes) -- run() feeds them through FacetCommon.normalizePrefix
        # before either mapToManifestPath or mapPathForExport ever sees them.
        result = facet_common.mapPathForExport(
            r'C:\Users\nic\Pictures\a.jpg', 'C:/Users/nic/Pictures', '/volume1/photos')
        assert result == '/volume1/photos/a.jpg'
