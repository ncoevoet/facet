"""Tests for api/config_writes.py — the locked category priority writer."""

import json
import shutil
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.config_writes import (
    _CONFIG_WRITE_LOCK,
    update_category_priorities,
    update_scoring_context,
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

    def test_unknown_context_raises_400(self, config_copy):
        with pytest.raises(HTTPException) as exc_info:
            update_scoring_context(config_copy, "not_a_real_context", [], [])
        assert exc_info.value.status_code == 400
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
