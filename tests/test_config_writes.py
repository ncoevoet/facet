"""Tests for api/config_writes.py — the locked category priority writer."""

import json
import os
import shutil
import stat
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

from api.auth import _is_hashed, upgrade_legacy_password
from api.config import CONFIG_WRITE_LOCK, atomic_write_json
from api.config_writes import (
    BACKUP_FILE_MODE,
    MAX_CONFIG_BACKUPS,
    update_category_priorities,
    update_category_weights,
    update_scoring_context,
    write_owner_only_backup,
)
from config.scoring_config import ScoringConfig

REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring_config.json"


@pytest.fixture
def config_copy(tmp_path):
    """A private, disposable copy of the real scoring_config.json."""
    dest = tmp_path / "scoring_config.json"
    shutil.copy2(REPO_CONFIG_PATH, dest)
    return dest


def _non_default_names(config_path):
    cfg = ScoringConfig(str(config_path), validate=False)
    return [c["name"] for c in cfg.get_categories() if c["name"] != "default"]


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


_GROUP_WRITABLE_MODE = 0o664
_SENSITIVE_CONFIG = '{"viewer": {"password": "plaintext-pw"}, "share_secret": "aaaa"}'


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits do not apply on Windows")
class TestOwnerOnlyBackupPrimitive:
    """H2/H3: a config backup carries every secret scoring_config.json does.

    ``shutil.copy2`` — what every backup writer here and in ``api.auth`` used
    to call — copies the MODE along with the bytes, so each one landed at the
    config's own 0664 holding ``share_secret``, ``users.*.password_hash`` and,
    for the password upgrade, the plaintext password just typed. Unlike the
    config itself, whose group read bit a co-deployed CLI needs, a backup has
    no reader but its owner.
    """

    def _sensitive_source(self, tmp_path):
        source = tmp_path / "scoring_config.json"
        source.write_text(_SENSITIVE_CONFIG)
        os.chmod(source, _GROUP_WRITABLE_MODE)
        return source

    def test_the_backup_is_owner_only_whatever_the_source_mode(self, tmp_path):
        source = self._sensitive_source(tmp_path)

        backup = write_owner_only_backup(source, tmp_path / "scoring_config.json.backup")

        assert _mode_of(backup) == BACKUP_FILE_MODE
        assert Path(backup).read_text() == _SENSITIVE_CONFIG

    def test_the_source_mode_is_left_alone(self, tmp_path):
        """Only the copy is restricted: the config keeps whatever it had."""
        source = self._sensitive_source(tmp_path)

        write_owner_only_backup(source, tmp_path / "scoring_config.json.backup")

        assert _mode_of(source) == _GROUP_WRITABLE_MODE

    def test_the_destination_is_created_owner_only(self, tmp_path):
        """Created at 0600, not created-then-chmodded: an ``os.open`` mode
        argument leaves no window, a following ``chmod`` does."""
        source = self._sensitive_source(tmp_path)
        backup_path = tmp_path / "scoring_config.json.backup"
        creations = []
        real_open = os.open

        def _recording_open(path, flags, mode=0o777, **kwargs):
            if str(path) == str(backup_path):
                creations.append(mode)
            return real_open(path, flags, mode, **kwargs)

        with mock.patch("api.config_writes.os.open", _recording_open):
            write_owner_only_backup(source, backup_path)

        assert creations == [BACKUP_FILE_MODE]

    def test_a_reused_backup_name_is_tightened_before_it_holds_anything(self, tmp_path):
        """The creation mode does nothing when the name already exists.

        Every install that ran an older Facet has exactly that: a
        ``scoring_config.json.backup`` sitting at 0664. The bytes must not land
        in it at that mode and be tightened afterwards, so the mode is asserted
        at the moment the first byte is written — the window a plain ``chmod``
        after the copy leaves open.
        """
        source = self._sensitive_source(tmp_path)
        backup_path = tmp_path / "scoring_config.json.backup"
        backup_path.write_text("stale")
        os.chmod(backup_path, _GROUP_WRITABLE_MODE)
        modes_while_writing = []
        real_copyfileobj = shutil.copyfileobj

        def _recording_copyfileobj(source_file, destination_file, *args, **kwargs):
            modes_while_writing.append(_mode_of(backup_path))
            return real_copyfileobj(source_file, destination_file, *args, **kwargs)

        with mock.patch("api.config_writes.shutil.copyfileobj", _recording_copyfileobj):
            write_owner_only_backup(source, backup_path)

        assert modes_while_writing == [BACKUP_FILE_MODE]
        assert _mode_of(backup_path) == BACKUP_FILE_MODE
        assert backup_path.read_text() == _SENSITIVE_CONFIG

    def test_timestamped_backups_of_a_real_write_are_owner_only(self, config_copy):
        """The end-to-end shape: this checkout accumulated nine 0664 backups
        holding a 64-character ``share_secret`` this way."""
        os.chmod(config_copy, _GROUP_WRITABLE_MODE)

        backup_path = update_scoring_context(config_copy, "action_stage", ["wildlife"], [])

        assert _mode_of(backup_path) == BACKUP_FILE_MODE
        assert _mode_of(config_copy) == _GROUP_WRITABLE_MODE


class TestUpdateCategoryPriorities:
    """update_category_priorities permutes existing priority values onto a new order."""

    def test_order_matches_request(self, config_copy):
        new_order = list(reversed(_non_default_names(config_copy)))

        update_category_priorities(config_copy, new_order)

        cfg = ScoringConfig(str(config_copy), validate=False)
        result_names = [c["name"] for c in cfg.get_categories() if c["name"] != "default"]
        assert result_names == new_order

    def test_priority_multiset_unchanged(self, config_copy):
        before = ScoringConfig(str(config_copy), validate=False)
        before_priorities = sorted(c["priority"] for c in before.get_categories() if c["name"] != "default")
        new_order = list(reversed(_non_default_names(config_copy)))

        update_category_priorities(config_copy, new_order)

        after = ScoringConfig(str(config_copy), validate=False)
        after_priorities = sorted(c["priority"] for c in after.get_categories() if c["name"] != "default")
        assert after_priorities == before_priorities

    def test_default_priority_untouched(self, config_copy):
        before = ScoringConfig(str(config_copy), validate=False)
        default_priority_before = before.get_category_config("default")["priority"]
        new_order = list(reversed(_non_default_names(config_copy)))

        update_category_priorities(config_copy, new_order)

        after = ScoringConfig(str(config_copy), validate=False)
        assert after.get_category_config("default")["priority"] == default_priority_before
        assert default_priority_before == 999

    def test_validate_categories_clean_after_reorder(self, config_copy):
        new_order = list(reversed(_non_default_names(config_copy)))

        update_category_priorities(config_copy, new_order)

        cfg = ScoringConfig(str(config_copy), validate=False)
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is True
        assert issues == []

    def test_backup_file_is_written(self, config_copy):
        original_contents = config_copy.read_text()
        new_order = list(reversed(_non_default_names(config_copy)))

        backup_path = update_category_priorities(config_copy, new_order)

        assert backup_path is not None
        assert Path(backup_path).read_text() == original_contents

    def test_missing_category_raises_400(self, config_copy):
        order = _non_default_names(config_copy)[:-1]

        with pytest.raises(HTTPException) as exc_info:
            update_category_priorities(config_copy, order)
        assert exc_info.value.status_code == 400
        assert "missing" in exc_info.value.detail.lower()

    def test_unknown_category_raises_400(self, config_copy):
        order = _non_default_names(config_copy) + ["not_a_real_category"]

        with pytest.raises(HTTPException) as exc_info:
            update_category_priorities(config_copy, order)
        assert exc_info.value.status_code == 400
        assert "unknown" in exc_info.value.detail.lower()

    def test_duplicate_category_raises_400(self, config_copy):
        order = _non_default_names(config_copy)
        order[1] = order[0]

        with pytest.raises(HTTPException) as exc_info:
            update_category_priorities(config_copy, order)
        assert exc_info.value.status_code == 400
        assert "duplicate" in exc_info.value.detail.lower()

    def test_invalid_order_leaves_the_file_untouched(self, config_copy):
        original_contents = config_copy.read_text()
        order = _non_default_names(config_copy)[:-1]

        with pytest.raises(HTTPException):
            update_category_priorities(config_copy, order)
        assert config_copy.read_text() == original_contents

    def test_default_in_submitted_order_is_ignored(self, config_copy):
        """DEFECT 5 regression: GET includes 'default' in the evaluation
        order it returns, but POST's validation excludes it from the current
        names -- echoing GET's output back verbatim used to 400 as an
        'unknown category'. 'default' is pinned last regardless, so it must
        be accepted and ignored rather than rejected."""
        reversed_order = list(reversed(_non_default_names(config_copy)))
        order_with_default = reversed_order + ["default"]

        update_category_priorities(config_copy, order_with_default)

        cfg = ScoringConfig(str(config_copy), validate=False)
        result_names = [c["name"] for c in cfg.get_categories() if c["name"] != "default"]
        assert result_names == reversed_order

    def test_missing_priority_is_healed_instead_of_crashing_or_blocking(self, config_copy):
        """DEFECT M2/M3 regression: a category with a None priority previously
        crashed ``sorted()`` with an opaque TypeError, and a later fix turned
        that into a hard 400 -- which left a hand-edited config with no
        in-app way to fix it, since this endpoint is the only priority
        writer. ``validate_categories`` tolerates a missing priority as a
        logged issue, not a hard error, so this endpoint must agree: heal it
        and still honor the requested order."""
        data = json.loads(config_copy.read_text())
        target = next(c for c in data["categories"] if c["name"] != "default")
        del target["priority"]
        config_copy.write_text(json.dumps(data))

        order = _non_default_names(config_copy)

        update_category_priorities(config_copy, order)

        cfg = ScoringConfig(str(config_copy), validate=False)
        result_names = [c["name"] for c in cfg.get_categories() if c["name"] != "default"]
        assert result_names == order
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is True
        assert issues == []

    def test_duplicate_existing_priority_is_healed_instead_of_silently_misordering(self, config_copy):
        """DEFECT M2/M3 regression: the docstring once claimed priority
        uniqueness is 'guaranteed by construction', which was false -- the
        multiset of existing priorities was preserved verbatim, so a
        pre-existing collision (e.g. 'astro' colliding with 'art') made a
        full reversal return 200 OK while silently producing the wrong
        order. A later fix hard-rejected this instead, which left the
        Priorities tab permanently dead for a config it can't self-repair.
        Heal the collision (assign a fresh value past the current maximum)
        and still honor the requested order."""
        data = json.loads(config_copy.read_text())
        non_default = [c for c in data["categories"] if c["name"] != "default"]
        non_default[1]["priority"] = non_default[0]["priority"]
        config_copy.write_text(json.dumps(data))

        order = list(reversed(_non_default_names(config_copy)))

        update_category_priorities(config_copy, order)

        cfg = ScoringConfig(str(config_copy), validate=False)
        result_names = [c["name"] for c in cfg.get_categories() if c["name"] != "default"]
        assert result_names == order
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is True
        assert issues == []


def _raising_get_db():
    """A get_db stand-in for tests that don't need the best-effort weight
    snapshot: record_category_snapshot swallows any exception from get_db()
    and just logs a warning, so this keeps these tests from needing a real DB."""
    raise RuntimeError("no db needed for this test")


class TestUpdateCategoryWeightsBackupPruning:
    """DEBT A5#3: update_category_weights(backup=True) was the only writer
    passing prune=False to _backup_config, so modifier/filter edits
    accumulated ~88KB backups unbounded. It must prune like every other
    config-backup writer (update_category_priorities, update_scoring_context)."""

    def test_backup_prunes_old_files_to_the_shared_limit(self, config_copy):
        config_path = str(config_copy)
        directory = os.path.dirname(config_path)
        prefix = os.path.basename(config_path) + ".backup."
        for i in range(MAX_CONFIG_BACKUPS + 5):
            shutil.copy2(config_path, os.path.join(directory, f"{prefix}stale{i:03d}"))
        backups_before = [f for f in os.listdir(directory) if f.startswith(prefix)]
        assert len(backups_before) > MAX_CONFIG_BACKUPS

        category = _non_default_names(config_copy)[0]
        update_category_weights(
            config_path, category, "test:prune", _raising_get_db,
            not_found_detail="missing",
            modifiers={"bonus": 0.1},
            backup=True,
        )

        backups_after = [f for f in os.listdir(directory) if f.startswith(prefix)]
        assert len(backups_after) <= MAX_CONFIG_BACKUPS


def _context(config_path, name):
    return ScoringConfig(str(config_path), validate=False).get_scoring_contexts()[name]


def _effective_order(config_path, name):
    cfg = ScoringConfig(str(config_path), validate=False)
    return [cat_name for cat_name, _ in cfg.resolve_context_order(name)]


class TestUpdateScoringContext:
    """update_scoring_context rewrites one context's promote/excluded delta."""

    CONTEXT = "action_stage"

    def test_promote_and_excluded_are_persisted(self, config_copy):
        update_scoring_context(config_copy, self.CONTEXT, ["wildlife", "sports"], ["macro"])

        context = _context(config_copy, self.CONTEXT)
        assert context["promote"] == ["wildlife", "sports"]
        assert context["excluded"] == ["macro"]

    def test_label_key_and_suggested_moments_are_preserved(self, config_copy):
        before = _context(config_copy, self.CONTEXT)

        update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        after = _context(config_copy, self.CONTEXT)
        assert after["label_key"] == before["label_key"]
        assert after["suggest_from_moments"] == before["suggest_from_moments"]

    def test_other_contexts_are_untouched(self, config_copy):
        before = _context(config_copy, "wildlife")

        update_scoring_context(config_copy, self.CONTEXT, ["macro"], [])

        assert _context(config_copy, "wildlife") == before

    def test_resolve_context_order_reflects_the_new_delta(self, config_copy):
        update_scoring_context(config_copy, self.CONTEXT, ["wildlife", "sports"], ["silhouette", "macro"])

        order = _effective_order(config_copy, self.CONTEXT)
        assert order[:2] == ["wildlife", "sports"]
        assert "silhouette" not in order
        assert "macro" not in order
        assert order[-1] == "default"

    def test_non_promoted_categories_keep_the_global_order(self, config_copy):
        """The delta model's whole point: only the promoted head moves."""
        promoted = ["wildlife", "sports"]
        global_rest = [name for name in _non_default_names(config_copy) if name not in promoted]

        update_scoring_context(config_copy, self.CONTEXT, promoted, [])

        assert _effective_order(config_copy, self.CONTEXT) == promoted + global_rest + ["default"]

    def test_empty_delta_matches_the_plain_priority_order(self, config_copy):
        update_scoring_context(config_copy, self.CONTEXT, [], [])

        assert _effective_order(config_copy, self.CONTEXT) == _non_default_names(config_copy) + ["default"]

    def test_validate_categories_clean_after_write(self, config_copy):
        update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], ["macro"])

        ok, issues = ScoringConfig(str(config_copy), validate=False).validate_categories(verbose=False)
        assert ok is True
        assert issues == []

    def test_backup_file_is_written(self, config_copy):
        original_contents = config_copy.read_text()

        backup_path = update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        assert backup_path is not None
        assert Path(backup_path).read_text() == original_contents

    def test_unknown_context_raises_404(self, config_copy):
        """An unknown named resource is a 404, matching how the sibling
        ``update_category_weights`` answers a category that isn't configured.
        The 400s below stay 400s: those are bodies that cannot be applied."""
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, "not_a_real_context", [], [])
        assert exc_info.value.status_code == 404
        assert "not_a_real_context" in exc_info.value.detail

    def test_unknown_promoted_category_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, self.CONTEXT, ["not_a_real_category"], [])
        assert exc_info.value.status_code == 400
        assert "not_a_real_category" in exc_info.value.detail
        assert "promote" in exc_info.value.detail

    def test_unknown_excluded_category_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, self.CONTEXT, [], ["not_a_real_category"])
        assert exc_info.value.status_code == 400
        assert "not_a_real_category" in exc_info.value.detail
        assert "excluded" in exc_info.value.detail

    def test_default_category_in_promote_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, self.CONTEXT, ["default"], [])
        assert exc_info.value.status_code == 400
        assert "default" in exc_info.value.detail

    def test_default_category_in_excluded_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, self.CONTEXT, [], ["default"])
        assert exc_info.value.status_code == 400
        assert "default" in exc_info.value.detail

    def test_duplicate_promoted_category_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, self.CONTEXT, ["wildlife", "wildlife"], [])
        assert exc_info.value.status_code == 400
        assert "wildlife" in exc_info.value.detail
        assert "uplicate" in exc_info.value.detail

    def test_rejected_write_leaves_the_file_untouched(self, config_copy):
        original_contents = config_copy.read_text()

        with pytest.raises(HTTPException):
            update_scoring_context(config_copy, self.CONTEXT, ["not_a_real_category"], [])
        assert config_copy.read_text() == original_contents

    def test_category_in_both_lists_is_accepted_and_excluded_wins(self, config_copy):
        """Documented behaviour, preserved rather than rejected: a name in both
        lists is dropped from the order entirely."""
        update_scoring_context(config_copy, self.CONTEXT, ["wildlife", "macro"], ["macro"])

        context = _context(config_copy, self.CONTEXT)
        assert context["promote"] == ["wildlife", "macro"]
        assert context["excluded"] == ["macro"]
        assert "macro" not in _effective_order(config_copy, self.CONTEXT)

    def test_duplicate_exclusions_are_collapsed(self, config_copy):
        update_scoring_context(config_copy, self.CONTEXT, [], ["macro", "macro"])

        assert _context(config_copy, self.CONTEXT)["excluded"] == ["macro"]

    def test_malformed_context_entry_is_healed_instead_of_crashing(self, config_copy):
        """A hand-edited config can leave a context as a list or string;
        ``resolve_context_order`` tolerates that, so the writer must too rather
        than 500ing on item assignment."""
        data = json.loads(config_copy.read_text())
        data["scoring_contexts"][self.CONTEXT] = ["broken"]
        config_copy.write_text(json.dumps(data))

        update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        assert _context(config_copy, self.CONTEXT) == {"promote": ["wildlife"], "excluded": []}

    def test_concurrent_context_writes_never_corrupt_the_file(self, config_copy):
        deltas = [(["wildlife"], ["macro"]), (["sports"], [])]

        def _write(delta):
            update_scoring_context(config_copy, self.CONTEXT, *delta)

        threads = [threading.Thread(target=_write, args=(deltas[i % 2],)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ok, issues = ScoringConfig(str(config_copy), validate=False).validate_categories(verbose=False)
        assert ok is True
        assert issues == []


class _SameSecondClock:
    """A clock whose successive readings differ only below the second."""

    def __init__(self):
        self._readings = 0

    def now(self):
        self._readings += 1
        return datetime(2026, 8, 9, 12, 0, 0, self._readings * 1000)


class TestAtomicConfigWrite:
    """The config writer must not change the file's permissions or lose data."""

    CONTEXT = "action_stage"
    GROUP_READABLE_MODE = 0o664
    OWNER_ONLY_MODE = 0o600

    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    @pytest.mark.skipif(sys.platform == 'win32', reason="POSIX chmod permission bits do not apply on Windows")
    @pytest.mark.parametrize("mode", [GROUP_READABLE_MODE, OWNER_ONLY_MODE])
    def test_existing_permissions_are_preserved(self, config_copy, mode):
        """``tempfile.mkstemp`` creates its file 0600, so an unfixed writer
        silently locked a co-deployed CLI out of the config it shares."""
        os.chmod(config_copy, mode)

        update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        assert self._mode(config_copy) == mode

    @pytest.mark.skipif(sys.platform == 'win32', reason="POSIX directory fsync is not supported on Windows")
    def test_payload_is_fsynced_before_the_rename(self, config_copy):
        """Rename-atomic is not crash-durable: without the flush the rename can
        land while the replacement's bytes are still only in the page cache."""
        calls = []
        real_fsync, real_replace = os.fsync, os.replace

        def _record_fsync(fd):
            calls.append("fsync")
            return real_fsync(fd)

        def _record_replace(src, dst):
            calls.append("replace")
            return real_replace(src, dst)

        with mock.patch("os.fsync", _record_fsync), mock.patch("os.replace", _record_replace):
            update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        assert calls == ["fsync", "replace", "fsync"]

    def test_two_writes_in_one_second_keep_distinct_backups(self, config_copy):
        """A second-granular stamp made the second save overwrite the first
        backup, so the ``backup`` path returned no longer held what the caller
        was promised."""
        first_contents = config_copy.read_text()

        with mock.patch("api.config_writes.datetime", _SameSecondClock()):
            first_backup = update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])
            second_contents = config_copy.read_text()
            second_backup = update_scoring_context(config_copy, self.CONTEXT, ["sports"], [])

        assert first_backup != second_backup
        assert Path(first_backup).read_text() == first_contents
        assert Path(second_backup).read_text() == second_contents


class TestConfigWriteLock:
    """A shared lock serializes concurrent config writes so none are lost."""

    def test_lock_is_a_real_lock(self):
        assert hasattr(CONFIG_WRITE_LOCK, "acquire")
        assert hasattr(CONFIG_WRITE_LOCK, "release")

    def test_concurrent_writes_never_corrupt_the_file(self, config_copy):
        names = _non_default_names(config_copy)
        orders = [names, list(reversed(names))]

        def _write(order):
            update_category_priorities(config_copy, order)

        threads = [threading.Thread(target=_write, args=(orders[i % 2],)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        cfg = ScoringConfig(str(config_copy), validate=False)
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is True
        assert issues == []


_PLAINTEXT_PASSWORD = "legacy-plaintext-pw"
_WRITE_WINDOW_SECONDS = 0.4


class TestWritersOfDifferentPartsShareOneLock:
    """``api.auth`` rewrites ``viewer.password`` in the same file this module
    rewrites contexts and priorities in. While they held two different locks,
    whichever read first won and the other's update was lost wholesale — not
    corrupted, silently reverted."""

    CONTEXT = "action_stage"

    def _delayed_write(self, delay):
        """Widen one writer's read-modify-write window so the other lands inside it."""
        def _write(path, data):
            time.sleep(delay)
            atomic_write_json(path, data)
        return _write

    def test_neither_update_is_lost(self, config_copy):
        data = json.loads(config_copy.read_text())
        data["viewer"]["password"] = _PLAINTEXT_PASSWORD
        config_copy.write_text(json.dumps(data))

        import api.config as api_config

        def _write_context():
            update_scoring_context(config_copy, self.CONTEXT, ["wildlife"], [])

        def _upgrade_password():
            upgrade_legacy_password("password", _PLAINTEXT_PASSWORD)

        with (
            mock.patch("api.config_writes.atomic_write_json", self._delayed_write(_WRITE_WINDOW_SECONDS)),
            mock.patch.object(api_config, "_CONFIG_PATH", str(config_copy)),
            mock.patch.object(api_config, "reload_config", lambda: None),
        ):
            context_writer = threading.Thread(target=_write_context)
            password_writer = threading.Thread(target=_upgrade_password)
            context_writer.start()
            time.sleep(_WRITE_WINDOW_SECONDS / 4)
            password_writer.start()
            context_writer.join()
            password_writer.join()

        written = json.loads(config_copy.read_text())
        assert written["scoring_contexts"][self.CONTEXT]["promote"] == ["wildlife"]
        assert _is_hashed(written["viewer"]["password"])
