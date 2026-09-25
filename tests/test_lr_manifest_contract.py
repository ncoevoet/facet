"""Contract test between ``facet.py --export-manifest`` and the Lightroom plug-in.

The Lua reader in ``facet.lrplugin/FacetApply.lua`` cannot be executed here (no
Lua, no Lightroom), so the two sides can drift silently: renaming a manifest
key in ``facet.py`` would leave the plug-in matching zero photos, or writing no
ratings, with no error anywhere.

The Lua source names every manifest key it reads in a ``FIELD_*`` constant.
This test extracts those constants with a regex — crude, but it fails loudly
the moment either side is renamed — and checks them against a manifest produced
by the real exporter, including the JSON types the Lua code type-checks on
(``type(stars) ~= 'number'``, ``record[FIELD_IS_FAVORITE] == true``).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PY = REPO_ROOT / 'venv' / 'bin' / 'python'
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
FACET = str(REPO_ROOT / 'facet.py')
DATABASE = str(REPO_ROOT / 'database.py')

PLUGIN_DIR = REPO_ROOT / 'facet.lrplugin'
APPLY_LUA = PLUGIN_DIR / 'FacetApply.lua'
INFO_LUA = PLUGIN_DIR / 'Info.lua'

FIELD_CONSTANT_PATTERN = re.compile(r"^local (FIELD_[A-Z_]+) = '([a-z_]+)'$", re.MULTILINE)
MANIFEST_VERSION_PATTERN = re.compile(r"^local MANIFEST_VERSION = (\d+)$", re.MULTILINE)
METADATA_CONSTANT_PATTERN = re.compile(r"^local (METADATA_[A-Z_]+) = '(\w+)'$", re.MULTILINE)
PICK_STATUS_PATTERN = re.compile(r"^local (PICK_STATUS_[A-Z_]+) = (-?\d+)$", re.MULTILINE)
MENU_FILE_PATTERN = re.compile(r"file = '([\w.]+)'")

# What the Lua reader expects, and where. ``type(...) is`` is deliberate:
# ``isinstance(True, int)`` is True in Python, but a JSON ``true`` where the
# Lua side does ``type(stars) ~= 'number'`` would silently skip every rating.
TOP_LEVEL_FIELDS = {'version': int, 'generated_at': str, 'photos': list}
PHOTO_FIELDS = {'path': str, 'star_rating': int, 'is_favorite': bool, 'is_rejected': bool}
# Nullable fields added in manifest v2: presence and type are asserted
# separately (a value or None), never folded into PHOTO_FIELDS' strict
# type check.
NULLABLE_PHOTO_FIELDS = {'burst_group_id': int, 'sequence_kind': str, 'sequence_group_id': int}
# Every other manifest key the Lua reader names in a FIELD_* constant but
# does not type-check the way PHOTO_FIELDS/NULLABLE_PHOTO_FIELDS do (either
# read straight off the record with its own ad hoc check, like
# is_burst_lead/score_stars/date_taken, or a plain field like filename).
OTHER_FIELD_NAMES = {'is_burst_lead', 'score_stars', 'date_taken', 'filename'}

# Lightroom's own raw-metadata keys, per the LrPhoto SDK reference. A typo
# here is unobservable without Lightroom: setRawMetadata would simply not
# reach the field the plug-in claims to write.
LIGHTROOM_METADATA_KEYS = {
    'METADATA_PATH': 'path',
    'METADATA_RATING': 'rating',
    'METADATA_PICK_STATUS': 'pickStatus',
}
LIGHTROOM_PICK_STATUS = {
    'PICK_STATUS_PICKED': 1,
    'PICK_STATUS_NONE': 0,
    'PICK_STATUS_REJECTED': -1,
}


def _lua_source() -> str:
    return APPLY_LUA.read_text(encoding='utf-8')


def _sanitized_env():
    env = {k: v for k, v in os.environ.items() if 'TOKEN' not in k and 'SECRET' not in k}
    env.pop('DB_PATH', None)
    return env


@pytest.fixture(scope='module')
def exported_manifest(tmp_path_factory):
    """Run the real exporter over a seeded DB and return the parsed manifest."""
    tmp_path = tmp_path_factory.mktemp('lr_manifest')
    db_path = tmp_path / 'contract.db'
    result = subprocess.run([PY, DATABASE, '--db', str(db_path)],
                            capture_output=True, text=True, env=_sanitized_env())
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db_path)
    # burst_group_id can legitimately be 0 (a row id / group counter, not a
    # boolean) -- seeded here as a non-trivial, falsy-but-real value so a
    # truthiness bug in either the exporter or the plug-in would show up.
    conn.execute(
        "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
        "is_favorite, is_rejected, is_burst_lead, burst_group_id, sequence_kind, "
        "sequence_group_id) VALUES "
        "('/library/keep.jpg', 'keep.jpg', 8.5, 'portrait', 4, 1, 0, 0, 0, NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
        "is_favorite, is_rejected, is_burst_lead, burst_group_id, sequence_kind, "
        "sequence_group_id) VALUES "
        "('/library/reject.jpg', 'reject.jpg', 3.0, 'default', 0, 0, 1, 1, 1, 'bracket', 7)"
    )
    conn.commit()
    conn.close()

    result = subprocess.run([PY, FACET, '--db', str(db_path), '--export-manifest'],
                            capture_output=True, text=True, cwd=str(tmp_path),
                            env=_sanitized_env())
    assert result.returncode == 0, result.stderr
    return json.loads((tmp_path / 'facet_manifest.json').read_text(encoding='utf-8'))


class TestLuaConstants:
    def test_plugin_files_exist(self):
        assert APPLY_LUA.exists()
        assert INFO_LUA.exists()
        assert (PLUGIN_DIR / 'FacetJson.lua').exists()

    def test_info_menu_entry_points_at_a_real_file(self):
        # Lightroom reports a broken menu entry only when the user clicks it.
        referenced = MENU_FILE_PATTERN.findall(INFO_LUA.read_text(encoding='utf-8'))
        assert referenced, 'Info.lua declares no menu file'
        for name in referenced:
            assert (PLUGIN_DIR / name).exists(), f'Info.lua points at a missing {name}'

    def test_field_constants_cover_exactly_the_contract(self):
        found = {value for _, value in FIELD_CONSTANT_PATTERN.findall(_lua_source())}
        expected = set(TOP_LEVEL_FIELDS) | set(PHOTO_FIELDS) | set(NULLABLE_PHOTO_FIELDS) | OTHER_FIELD_NAMES
        assert found == expected, (
            'The Lua reader and this contract disagree on the manifest keys. '
            f'Only in Lua: {sorted(found - expected)}; only here: {sorted(expected - found)}'
        )

    def test_lightroom_metadata_keys_are_spelled_the_sdk_way(self):
        found = dict(METADATA_CONSTANT_PATTERN.findall(_lua_source()))
        assert found == LIGHTROOM_METADATA_KEYS

    def test_pick_status_values_match_the_sdk(self):
        found = {name: int(value) for name, value in PICK_STATUS_PATTERN.findall(_lua_source())}
        assert found == LIGHTROOM_PICK_STATUS


class TestManifestMatchesLuaReader:
    def test_version_constant_matches_the_exporter(self, exported_manifest):
        declared = MANIFEST_VERSION_PATTERN.search(_lua_source())
        assert declared, 'MANIFEST_VERSION not found in the Lua source'
        # The plug-in refuses any other version with an error dialog, so a bump
        # on either side without the other is a hard failure for every user.
        assert int(declared.group(1)) == exported_manifest['version']

    def test_top_level_fields_and_types(self, exported_manifest):
        for name, expected_type in TOP_LEVEL_FIELDS.items():
            assert name in exported_manifest, f'manifest is missing {name!r}'
            assert type(exported_manifest[name]) is expected_type, (
                f'{name!r} is {type(exported_manifest[name]).__name__}, '
                f'the plug-in expects {expected_type.__name__}'
            )

    def test_photo_fields_and_types(self, exported_manifest):
        photos = exported_manifest['photos']
        assert photos, 'the seeded export produced no photos'
        for photo in photos:
            for name, expected_type in PHOTO_FIELDS.items():
                assert name in photo, f'photo row is missing {name!r}'
                assert type(photo[name]) is expected_type, (
                    f'{name!r} is {type(photo[name]).__name__}, '
                    f'the plug-in expects {expected_type.__name__}'
                )

    def test_flags_are_json_booleans_not_integers(self, exported_manifest):
        # The Lua side compares with ``== true``: a 0/1 integer would make the
        # plug-in silently write no pick flags at all.
        photos = {photo['path']: photo for photo in exported_manifest['photos']}
        assert photos['/library/keep.jpg']['is_favorite'] is True
        assert photos['/library/keep.jpg']['is_rejected'] is False
        assert photos['/library/reject.jpg']['is_rejected'] is True

    def test_star_rating_is_an_integer_in_lightrooms_range(self, exported_manifest):
        for photo in exported_manifest['photos']:
            assert 0 <= photo['star_rating'] <= 5

    def test_nullable_fields_are_present_and_correctly_typed_or_none(self, exported_manifest):
        for photo in exported_manifest['photos']:
            for name, expected_type in NULLABLE_PHOTO_FIELDS.items():
                assert name in photo, f'photo row is missing {name!r}'
                assert photo[name] is None or type(photo[name]) is expected_type, (
                    f'{name!r} is {type(photo[name]).__name__}, expected None or '
                    f'{expected_type.__name__}'
                )

    def test_score_stars_is_an_integer_in_lightrooms_range(self, exported_manifest):
        for photo in exported_manifest['photos']:
            assert isinstance(photo['score_stars'], int)
            assert 0 <= photo['score_stars'] <= 5

    def test_burst_group_id_can_be_zero_without_being_dropped(self, exported_manifest):
        # burst_group_id=0 is a real, falsy-but-present value -- must survive
        # the export as 0, never coerced to None by a truthiness check.
        photos = {photo['path']: photo for photo in exported_manifest['photos']}
        assert photos['/library/keep.jpg']['burst_group_id'] == 0

    def test_sequence_fields_carry_the_seeded_bracket(self, exported_manifest):
        photos = {photo['path']: photo for photo in exported_manifest['photos']}
        assert photos['/library/reject.jpg']['sequence_kind'] == 'bracket'
        assert photos['/library/reject.jpg']['sequence_group_id'] == 7
        assert photos['/library/keep.jpg']['sequence_kind'] is None
        assert photos['/library/keep.jpg']['sequence_group_id'] is None

    def test_score_stars_is_derived_even_with_score_to_rating_disabled(self, tmp_path_factory):
        """score_stars mirrors --export-sidecars's derive_stars idiom: the
        manifest forces the configured `xmp_export.score_to_rating` block's
        `enabled` True for this one computation, never mutating the live
        config on disk. The shipped default has `enabled: false` (star
        rating from aggregate is opt-in for XMP sidecars), so a high-aggregate
        photo must still get a star_stars rating in the manifest -- the
        Lightroom plug-in has no other source for it."""
        tmp_path = tmp_path_factory.mktemp('lr_manifest_disabled')
        db_path = tmp_path / 'disabled.db'
        result = subprocess.run([PY, DATABASE, '--db', str(db_path)],
                                capture_output=True, text=True, env=_sanitized_env())
        assert result.returncode == 0, result.stderr

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
            "is_favorite, is_rejected, is_burst_lead, burst_group_id) VALUES "
            "('/library/high.jpg', 'high.jpg', 9.5, 'portrait', 0, 0, 0, 0, 0)"
        )
        conn.commit()
        conn.close()

        result = subprocess.run([PY, FACET, '--db', str(db_path), '--export-manifest'],
                                capture_output=True, text=True, cwd=str(tmp_path),
                                env=_sanitized_env())
        assert result.returncode == 0, result.stderr
        manifest = json.loads((tmp_path / 'facet_manifest.json').read_text(encoding='utf-8'))
        photos = {photo['path']: photo for photo in manifest['photos']}
        assert photos['/library/high.jpg']['score_stars'] == 5
