"""scanning.skip_directories: name-glob pruning of the scan walk (issue #207)."""

import json
import logging
import os
from pathlib import Path

import pytest

from config.scoring_config import ScoringConfig
from config_resolve import defaults_path

DEFAULT_GLOBS = ["@eaDir", "#recycle", "#snapshot", "@Recycle"]


def _gather(paths, settings):
    from facet import _gather_scan_files
    # (files, dead_roots): the pruning tests exercise roots that exist, so the
    # dead-root half stays empty.
    return _gather_scan_files([str(p) for p in paths], settings)[0]


def _names(files):
    return sorted(f.name for f in files)


def _touch(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def _tree(root):
    for rel in ("a/img.jpg", "a/@eaDir/SYNOPHOTO_THUMB_M.jpg", "#recycle/z.jpg",
                "a/b/@eaDir/deep.jpg", "a/b/keep.jpg", "#snapshot/s.jpg",
                "q/@Recycle/r.jpg", "a/.hidden/h.jpg"):
        _touch(root, rel)


class TestConfigDefault:
    def test_resolved_default_lists_synology_and_qnap_dirs(self):
        cfg = ScoringConfig(defaults_path(), validate=False)
        assert cfg.get_scanning_settings()["skip_directories"] == DEFAULT_GLOBS

    def test_bare_config_fallback_has_same_default(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"categories": []}))
        cfg = ScoringConfig(str(p), validate=False)
        cfg.config.pop("scanning", None)
        assert cfg.get_scanning_settings()["skip_directories"] == DEFAULT_GLOBS

    def test_schema_accepts_default_and_rejects_bad_type(self, tmp_path):
        pytest.importorskip("jsonschema")
        cfg = ScoringConfig(defaults_path(), validate=False)
        assert not [e for e in cfg.validate_schema() if "scanning" in e]
        cfg.config["scanning"]["skip_directories"] = 5
        assert [e for e in cfg.validate_schema() if "scanning" in e]


class TestGather:
    def test_defaults_prune_at_depth_one_and_two(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True,
                                     "skip_directories": DEFAULT_GLOBS})
        assert _names(files) == ["img.jpg", "keep.jpg"]

    def test_globs_active_when_hidden_skip_disabled(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": False,
                                     "skip_directories": DEFAULT_GLOBS})
        assert _names(files) == ["h.jpg", "img.jpg", "keep.jpg"]

    def test_empty_list_disables_glob_pruning(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True,
                                     "skip_directories": []})
        assert len(files) == 7

    def test_custom_glob_replaces_default(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True,
                                     "skip_directories": ["b"]})
        assert "keep.jpg" not in _names(files)
        assert "SYNOPHOTO_THUMB_M.jpg" in _names(files)

    def test_match_is_case_sensitive(self, tmp_path):
        _touch(tmp_path, "@EADIR/x.jpg")
        files = _gather([tmp_path], {"skip_directories": DEFAULT_GLOBS})
        assert _names(files) == ["x.jpg"]

    def test_wildcard_glob(self, tmp_path):
        _touch(tmp_path, "tmp_1/x.jpg")
        _touch(tmp_path, "ok/y.jpg")
        files = _gather([tmp_path], {"skip_directories": ["tmp_*"]})
        assert _names(files) == ["y.jpg"]

    def test_root_inside_matching_dir_is_scanned(self, tmp_path):
        f = _touch(tmp_path, "@eaDir/photos/p.jpg")
        assert _names(_gather([tmp_path / "@eaDir" / "photos"],
                              {"skip_directories": DEFAULT_GLOBS})) == ["p.jpg"]
        assert _names(_gather([f], {"skip_directories": DEFAULT_GLOBS})) == ["p.jpg"]

    def test_string_value_is_one_item_list(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True,
                                     "skip_directories": "@eaDir"})
        assert "SYNOPHOTO_THUMB_M.jpg" not in _names(files)
        assert "z.jpg" in _names(files)

    @pytest.mark.parametrize("bad", [None, 5, {"a": 1}])
    def test_non_list_warns_and_prunes_nothing(self, tmp_path, caplog, bad):
        _tree(tmp_path)
        with caplog.at_level(logging.WARNING, logger="facet"):
            files = _gather([tmp_path], {"skip_hidden_directories": True,
                                         "skip_directories": bad})
        assert "z.jpg" in _names(files)
        assert any("skip_directories" in r.getMessage() for r in caplog.records)

    def test_non_string_items_skipped(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True,
                                     "skip_directories": [1, None, "@eaDir"]})
        assert "SYNOPHOTO_THUMB_M.jpg" not in _names(files)
        assert "z.jpg" in _names(files)

    def test_missing_key_means_no_globs(self, tmp_path):
        _tree(tmp_path)
        files = _gather([tmp_path], {"skip_hidden_directories": True})
        assert "z.jpg" in _names(files)

    def test_skip_raw_excludes_raw_files_when_enabled(self, tmp_path):
        _touch(tmp_path, "shot.jpg")
        _touch(tmp_path, "shot.cr2")
        _touch(tmp_path, "other.nef")
        assert _names(_gather([tmp_path], {"skip_raw": False})) == ["other.nef", "shot.cr2", "shot.jpg"]
        assert _names(_gather([tmp_path], {"skip_raw": True})) == ["shot.jpg"]


@pytest.mark.parametrize('operation', ['resolve', 'exists', 'is_file'])
def test_unreadable_root_does_not_discard_other_roots(tmp_path, monkeypatch, operation):
    from facet import _gather_scan_files
    blocked = tmp_path / 'blocked'
    blocked.mkdir()
    good = _touch(tmp_path, 'valid/ok.jpg')
    original = getattr(Path, operation)

    def denied(self, *args, **kwargs):
        if self == blocked:
            raise PermissionError(13, 'Permission denied', str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, operation, denied)
    files, dead = _gather_scan_files([str(blocked), str(good.parent)], {})
    assert files == [good]
    assert dead == [str(blocked)]


@pytest.mark.skipif(os.name == 'nt' or getattr(os, 'geteuid', lambda: 0)() == 0,
                    reason='requires POSIX permission checks as a non-root user')
def test_root_with_inaccessible_parent_is_classified_as_dead(tmp_path):
    from facet import _gather_scan_files
    blocked = tmp_path / 'blocked'
    hidden = blocked / 'photos'
    hidden.mkdir(parents=True)
    good = _touch(tmp_path, 'valid/ok.jpg')
    blocked.chmod(0)
    try:
        files, dead = _gather_scan_files([str(hidden), str(good.parent)], {})
        assert files == [good]
        assert dead == [str(hidden)]
    finally:
        blocked.chmod(0o700)


class TestPathsUnder:
    """--recompute-saliency <paths> scopes the recompute to those files and folders."""

    @pytest.fixture
    def lib(self, tmp_path):
        root = tmp_path.resolve()
        rel = ["trip/a.jpg", "trip/day2/b.jpg", "trip2/c.jpg", "other/d.jpg"]
        return root, [str(root / r) for r in rel]

    def test_directory_takes_its_whole_subtree(self, lib):
        from facet import _paths_under
        root, paths = lib
        assert _paths_under(paths, [root / "trip"]) == paths[:2]

    def test_sibling_sharing_a_name_prefix_is_not_claimed(self, lib):
        from facet import _paths_under
        root, paths = lib
        assert paths[2] not in _paths_under(paths, [root / "trip"])

    def test_exact_file_matches_itself_only(self, lib):
        from facet import _paths_under
        root, paths = lib
        assert _paths_under(paths, [root / "other" / "d.jpg"]) == [paths[3]]

    def test_several_roots_union(self, lib):
        from facet import _paths_under
        root, paths = lib
        assert _paths_under(paths, [root / "trip2", str(root / "other") + "/"]) == paths[2:]

    def test_no_roots_match_nothing(self, lib):
        from facet import _paths_under
        assert _paths_under(lib[1], []) == []
