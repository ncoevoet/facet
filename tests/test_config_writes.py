"""Tests for api/config_writes.py — the locked category priority writer."""

import shutil
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.config_writes import _CONFIG_WRITE_LOCK, update_category_priorities
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


class TestConfigWriteLock:
    """A shared lock serializes concurrent config writes so none are lost."""

    def test_lock_is_a_real_lock(self):
        assert hasattr(_CONFIG_WRITE_LOCK, "acquire")
        assert hasattr(_CONFIG_WRITE_LOCK, "release")

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
