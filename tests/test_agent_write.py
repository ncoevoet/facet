"""Agent write tools over /mcp: grants, SET semantics, scope checks, the confirmation nonce.

Real auth chain (``agent_app``), real routes, seeded rows in the shared session DB.
Moves happen in ``tmp_path``; ``send2trash`` is replaced by a delete so nothing
reaches the developer's trash.
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api import config as api_config
from api.agent import limits, nonce
from api.agent.internal_client import ROUTE_ALLOWLIST
from api.agent.tools_write import WRITE_TOOL_LEVELS
from tests.conftest import _TEST_DB_FILE, AGENT_DIR, intercept_internal_call

ROWS = [
    {"path": AGENT_DIR + f"w{i}.jpg", "filename": f"w{i}.jpg", "aggregate": 5.0 + i,
     "star_rating": 1, "is_favorite": 0, "is_rejected": 0} for i in range(4)
] + [{"path": AGENT_DIR + "junk1.jpg", "filename": "junk1.jpg", "aggregate": 1.0, "junk_kind": "blurry"}]
P = [row["path"] for row in ROWS]


@pytest.fixture()
def photos(seed_photos_prefix):
    wipe_prefs()
    yield seed_photos_prefix(AGENT_DIR, ROWS)
    wipe_prefs()


@pytest.fixture(autouse=True)
def fresh_clock():
    yield
    limits.set_clock(None)


def db_row(sql, *args):
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def wipe_prefs():
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", (AGENT_DIR + "%",))
    conn.commit()
    conn.close()


def photo_col(path, col):
    return db_row(f"SELECT {col} FROM photos WHERE path = ?", path)[0]


def pref(user, path):
    return db_row("SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
                  "WHERE user_id = ? AND photo_path = ?", user, path)


@pytest.fixture()
def edition(agent_app):
    env = agent_app("legacy", allow_destructive=True)
    return env, env.token(env.login(edition=True), "edition")


@pytest.fixture()
def counting(monkeypatch):
    """Record every upstream tool name the internal client is asked to call."""
    calls = []
    intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
    return calls


class TestGrantMatrix:
    ARGS = {
        "set_rating": {"paths": [P[0]], "rating": 2}, "set_favorite": {"paths": [P[0]], "value": True},
        "set_rejected": {"paths": [P[0]], "value": True},
        "batch_set_rating": {"paths": [P[0]], "rating": 2}, "batch_set_favorite": {"paths": [P[0]]},
        "batch_set_rejected": {"paths": [P[0]]}, "create_album": {"name": "x"},
        "album_add_photos": {"album_id": 999999, "paths": [P[0]]},
        "album_remove_photos": {"album_id": 999999, "paths": [P[0]]},
        "add_tags": {"tags": ["t"], "paths": [P[0]]}, "remove_tags": {"tags": ["t"], "paths": [P[0]]},
        "junk_list": {}, "junk_reject": {"paths": [P[0]]}, "junk_clear": {"paths": [P[0]]},
        "cull_apply": {"action": "copy_keeps", "paths": [P[0]]}, "delete_photos": {"paths": [P[0]]},
        "assign_faces": {"person_id": 999999, "face_ids": [1]},
        "set_caption": {"path": P[0], "caption": "x"}, "export_metadata": {"paths": [P[0]]},
        "override_sequence": {"paths": [AGENT_DIR + "nope1.jpg", AGENT_DIR + "nope2.jpg"], "kind": "panorama"},
        "clear_sequence_override": {"paths": [AGENT_DIR + "nope1.jpg"]},
        "override_category": {"path": AGENT_DIR + "nope1.jpg", "category": "portrait"},
        "clear_category_override": {"path": AGENT_DIR + "nope1.jpg"},
        "group_compare": {"paths": [P[0]], "by": "faces"}, "cull_report": {},
        "start_scan": {"directories": [AGENT_DIR]}, "scan_status": {}, "comparison_status": {},
        "explain_score": {"path": P[0]}, "category_weights": {},
        "preview_weights": {"category": "portrait", "weights": {"aesthetic": 1}},
        # Arguments that stop at the tool's own guard (no digest, no snapshot, an unknown category): the matrix
        # must never start a recompute or write the install's config.
        "apply_weights": {"category": "portrait", "weights": {"aesthetic": 1}},
        "list_weight_snapshots": {}, "restore_weight_snapshot": {"snapshot_id": 999999},
        "recompute_scores": {"category": "zzz-no-such-category"}, "recompute_status": {},
        "learned_weights": {"category": "portrait"}, "misassigned_categories": {"category": "portrait", "scan": 1},
        "override_categories": {"category": "zzz-no-such-category", "paths": [AGENT_DIR + "nope1.jpg"]},
    }
    READ_ONLY = ("junk_list", "scan_status", "comparison_status", "group_compare", "cull_report",
                 "explain_score", "category_weights", "preview_weights", "list_weight_snapshots",
                 "recompute_status", "learned_weights", "misassigned_categories")

    def test_every_write_tool_has_args_and_a_level(self):
        assert set(self.ARGS) == set(WRITE_TOOL_LEVELS)

    def test_write_routes_never_default_to_readonly(self):
        for name, spec in ROUTE_ALLOWLIST.items():
            if spec.write:
                assert spec.min_level != "readonly", name

    def test_matrix_multi_user(self, agent_app, photos, counting):
        env = agent_app("multi")
        tokens = {
            "readonly": env.token(env.login("root"), "readonly"),
            "user": env.token(env.login("alice"), "user"),
            "edition": env.token(env.login("root"), "edition"),
        }
        for level, token in tokens.items():
            for tool, floor in WRITE_TOOL_LEVELS.items():
                counting.clear()
                result = env.call(token, tool, self.ARGS[tool])
                refused = result.get("error") == "forbidden_level" and "token's level" in result["message"]
                allowed = ("readonly", "user", "edition").index(level) >= \
                    ("readonly", "user", "edition").index(floor)
                assert refused is (not allowed), (level, tool, result)
                if refused:
                    assert counting == [], (level, tool, counting)

    def test_legacy_user_token_is_capped_to_readonly(self, agent_app, photos, counting):
        env = agent_app("legacy")
        resp = env.mint(env.login(), "user")
        token = resp.json()["token"] if resp.status_code == 200 else env.token(env.login(), "readonly")
        result = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        assert result["error"] == "forbidden_level" and counting == []
        assert photo_col(P[0], "star_rating") == 1

    def test_admin_readonly_token_cannot_rate(self, agent_app, photos):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})["error"] == "forbidden_level"
        assert pref("root", P[0]) is None

    def test_write_tools_are_not_read_only_and_destructive_hint_only_on_two(self, edition):
        env, token = edition
        api_config.VIEWER_CONFIG.setdefault("features", {})["show_scan_button"] = True
        tools = {t["name"]: t for t in env.rpc(token, "tools/list").json()["result"]["tools"]}
        for name in WRITE_TOOL_LEVELS:
            hints = tools[name]["annotations"]
            assert hints["readOnlyHint"] is (name in TestGrantMatrix.READ_ONLY), name
            assert hints["destructiveHint"] is (name in ("cull_apply", "delete_photos")), name


class TestPerPhotoTools:
    def alice(self, agent_app):
        env = agent_app("multi")
        return env, env.token(env.login("alice"), "user")

    def test_rating_lands_in_user_preferences_not_photos(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert result["ok"] and result["data"]["affected"] == 1
        assert pref("alice", P[0])[0] == 5
        assert photo_col(P[0], "star_rating") == 1

    def test_set_is_idempotent(self, agent_app, photos):
        env, token = self.alice(agent_app)
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        again = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert again["data"]["affected"] == 0 and again["data"]["already"] == 1
        assert again["data"]["results"] == [{"path": P[0], "outcome": "already"}]

    def test_unfavourite_of_a_non_favourite_does_not_toggle(self, agent_app, photos, counting):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_favorite", {"paths": [P[0]], "value": False})
        assert result["data"]["already"] == 1 and "toggle_favorite" not in counting
        result = env.call(token, "set_favorite", {"paths": [P[0]], "value": True})
        assert result["data"]["affected"] == 1 and counting.count("toggle_favorite") == 1
        assert env.call(token, "set_favorite", {"paths": [P[0]], "value": True})["data"]["already"] == 1
        assert counting.count("toggle_favorite") == 1

    def test_reject_then_unreject(self, agent_app, photos):
        env, token = self.alice(agent_app)
        assert env.call(token, "set_rejected", {"paths": [P[1]], "value": True})["data"]["affected"] == 1
        assert pref("alice", P[1])[2] == 1
        assert env.call(token, "set_rejected", {"paths": [P[1]], "value": False})["data"]["affected"] == 1
        assert pref("alice", P[1])[2] == 0

    def test_cap_of_50(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [f"{AGENT_DIR}n{i}.jpg" for i in range(51)], "rating": 1})
        assert result["error"] == "too_large"
        assert env.call(token, "set_rating", {"paths": [], "rating": 1})["error"] == "invalid_input"

    def test_unknown_path_is_skipped_not_fatal(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [AGENT_DIR + "nope.jpg", P[0]], "rating": 4})
        assert result["ok"] and result["data"]["affected"] == 1
        assert result["data"]["skipped"] == [{"path": AGENT_DIR + "nope.jpg", "reason": "not_found"}]

    def test_one_users_agent_cannot_touch_anothers_ratings(self, agent_app, photos):
        env, token = self.alice(agent_app)
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert pref("root", P[0]) is None
        root = env.token(env.login("root"), "user")
        assert env.call(root, "set_rating", {"paths": [P[0]], "rating": 2})["ok"]
        assert pref("alice", P[0])[0] == 5 and pref("root", P[0])[0] == 2

    def test_a_user_without_the_directory_cannot_rate_it(self, agent_app, photos):
        env = agent_app("multi")
        bob = env.token(env.login("bob"), "user")
        result = env.call(bob, "set_rating", {"paths": [P[0]], "rating": 5})
        assert result["data"]["skipped"][0]["reason"] == "not_found"
        assert pref("bob", P[0]) is None

    def test_write_timeout_is_outcome_unknown_and_stops(self, agent_app, photos, monkeypatch):
        env, token = self.alice(agent_app)
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/photo/set_rating"):
                raise httpx.ReadTimeout("slow")
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        result = env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 4})
        assert result["error"] == "outcome_unknown" and "do not blindly retry" in result["message"]
        assert result["in_doubt"] == P[0] and result["not_attempted"] == 1

    def test_busy_library_is_library_busy(self, agent_app, photos, monkeypatch):
        env, token = self.alice(agent_app)
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/photo/set_rating"):
                return httpx.Response(503, json={"detail": "database is locked"})
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["error"] == "library_busy"

    def test_write_rate_limit_is_separate_from_reads(self, agent_app, photos):
        env = agent_app("multi", write_rate_per_min=2)
        token = env.token(env.login("alice"), "user")
        for _ in range(2):
            assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 3})["ok"]
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 3})["error"] == "rate_limited"
        assert env.call(token, "status")["ok"]


class TestBatchTools:
    def test_paths_scope_sets_photos_in_single_password_mode(self, edition, photos):
        env, token = edition
        result = env.call(token, "batch_set_rating", {"paths": P[:2], "rating": 4})
        assert result["data"]["affected"] == 2
        assert [photo_col(p, "star_rating") for p in P[:3]] == [4, 4, 1]
        assert env.call(token, "batch_set_favorite", {"paths": [P[0]]})["data"]["affected"] == 1
        assert photo_col(P[0], "is_favorite") == 1
        assert env.call(token, "batch_set_rejected", {"paths": P[:2], "exclude": [P[1]]})["data"]["affected"] == 1
        assert photo_col(P[1], "is_rejected") == 0

    def view(self, env):
        return {"path_prefix": AGENT_DIR}

    def test_filter_scope_needs_a_matching_expected_count(self, edition, photos):
        env, token = edition
        headers = env.login(edition=True)
        total = env.client.get("/api/photos/count", params=self.view(env), headers=headers).json()["total"]
        assert total == 5
        args = {"filters": self.view(env), "rating": 5}
        assert env.call(token, "batch_set_rating", args)["error"] == "invalid_input"
        wrong = env.call(token, "batch_set_rating", {**args, "expected_count": total + 1})
        assert wrong["error"] == "invalid_input" and wrong["actual_count"] == total
        assert [photo_col(p, "star_rating") for p in P[:4]] == [1, 1, 1, 1]  # nothing written
        right = env.call(token, "batch_set_rating", {**args, "expected_count": total})
        assert right["ok"] and right["data"]["affected"] == total
        assert photo_col(P[0], "star_rating") == 5

    def test_both_or_neither_target_and_misspelled_filter(self, edition, photos):
        env, token = edition
        both = env.call(token, "batch_set_favorite", {"paths": [P[0]], "filters": {}, "expected_count": 1})
        assert both["error"] == "invalid_input"
        assert env.call(token, "batch_set_favorite", {})["error"] == "invalid_input"
        typo = env.call(token, "batch_set_favorite", {"filters": {"path_prefx": AGENT_DIR}, "expected_count": 1})
        assert typo["error"] == "invalid_input"
        assert env.call(token, "batch_set_favorite", {"paths": [f"/x/{i}" for i in range(1001)]})["error"] == "too_large"

    def test_albums(self, edition, photos):
        env, token = edition
        album = env.call(token, "create_album", {"name": "agent album"})["data"]
        added = env.call(token, "album_add_photos", {"album_id": album["id"], "paths": P[:2]})
        assert added["ok"] and added["data"]["added"] == 2
        removed = env.call(token, "album_remove_photos", {"album_id": album["id"], "paths": [P[0]]})
        assert removed["data"]["photo_count"] == 1
        assert env.call(token, "album_add_photos", {"album_id": 987654, "paths": [P[0]]})["error"] == "not_found"
        env.client.delete(f"/api/albums/{album['id']}", headers=env.login(edition=True))

    def test_manual_tags(self, edition, photos):
        env, token = edition
        assert env.call(token, "add_tags", {"tags": ["alpha", "beta"], "paths": P[:2]})["data"]["affected"] == 4
        assert db_row("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ?", P[0])[0] == 2
        assert env.call(token, "remove_tags", {"tags": ["alpha"], "paths": P[:2]})["data"]["affected"] == 2
        assert db_row("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ? AND tag = 'alpha'", P[0])[0] == 0
        env.call(token, "remove_tags", {"tags": ["beta"], "paths": P[:2]})

    def test_junk_sweep(self, edition, photos):
        env, token = edition
        listed = env.call(token, "junk_list", {"kind": "blurry"})
        assert [r["path"] for r in listed["data"]["rows"]] == [P[4]]
        assert env.call(token, "junk_reject", {"paths": [P[4]]})["data"]["affected"] == 1
        assert photo_col(P[4], "is_rejected") == 1
        assert env.call(token, "junk_clear", {"paths": [P[4]]})["data"]["affected"] == 1
        assert photo_col(P[4], "junk_kind") == "not_junk"
        assert env.call(token, "junk_clear", {"paths": [P[0]] * 51})["error"] == "too_large"


def test_user_floor_message_names_edition_on_a_single_password_install(agent_app, photos):
    env = agent_app("legacy")
    token = env.token(env.login(), "readonly")
    refused = env.call(token, "set_rejected", {"paths": [P[0]], "value": True})
    assert refused["error"] == "forbidden_level" and "needs edition" in refused["message"]
    multi = agent_app("multi")
    viewer = multi.token(multi.login("alice"), "readonly")
    assert "needs user" in multi.call(viewer, "set_rejected", {"paths": [P[0]], "value": True})["message"]


def test_filter_scope_resolves_the_same_set_as_search_photos(edition, photos, monkeypatch):
    env, token = edition
    monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_blinks", True)
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.execute("UPDATE photos SET is_blink = 1 WHERE path = ?", (P[3],))
    conn.commit()
    conn.close()
    filters = {"path_prefix": AGENT_DIR}
    seen = env.call(token, "search_photos", {"filters": filters})["data"]["total"]
    assert seen == 4
    result = env.call(token, "batch_set_rating", {"filters": filters, "rating": 5, "expected_count": seen})
    assert result["ok"], result
    assert result["data"]["affected"] == 4 and photo_col(P[3], "star_rating") == 1


def _disk_library(edition, seed_photos_prefix, tmp_path, monkeypatch, subdir, rows, extra_files=()):
    """Write each row's file (b'JPG') and the extra ``(name, bytes)`` files under ``tmp_path/subdir``, seed the
    rows, and allow export/trash there. ``rows`` are ``(file name, row fields)``; returns the shared namespace."""
    env, token = edition
    root = os.path.realpath(tmp_path)
    src = os.path.join(root, subdir)
    os.makedirs(src)
    seeded = []
    for name, fields in rows:
        path = os.path.join(src, name)
        with open(path, "wb") as handle:
            handle.write(b"JPG")
        seeded.append({"path": path, "filename": name, **fields})
    for name, data in extra_files:
        with open(os.path.join(src, name), "wb") as handle:
            handle.write(data)
    seed_photos_prefix(src + "/", seeded)
    monkeypatch.setattr("api.routers.export._allowed_export_roots", lambda: [root])
    monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": True})
    monkeypatch.setattr("send2trash.send2trash", os.remove)
    return SimpleNamespace(env=env, token=token, src=src, target=os.path.join(root, "out"),
                           paths=[row["path"] for row in seeded])


@pytest.fixture()
def panorama(edition, seed_photos_prefix, tmp_path, monkeypatch):
    """Three rejected frames of one panorama set on disk."""
    lib = _disk_library(edition, seed_photos_prefix, tmp_path, monkeypatch, "pano", [
        (f"p{index}.jpg", {"is_rejected": 1, "sequence_kind": "panorama", "sequence_group_id": 9,
                           "is_sequence_lead": 1 if index == 1 else 0}) for index in range(3)])
    lib.lead = lib.paths[1]
    return lib


class TestSequenceSiblingsAreBoundToTheNonce:
    def test_delete_lists_the_siblings_and_binds_the_flag(self, panorama):
        def call(**kw):
            return panorama.env.call(panorama.token, "delete_photos", {"paths": [panorama.lead], **kw})
        plain = call()["data"]
        assert plain["would_trash_count"] == 1
        wide = call(include_sequence_siblings=True)["data"]
        assert wide["would_trash_count"] == 3 and wide["sequence_siblings_count"] == 2
        flipped = call(dry_run=False, confirm=wide["confirm"])
        assert flipped["error"] == "confirmation_required"
        assert all(os.path.exists(p) for p in panorama.paths)
        fresh = call(include_sequence_siblings=True)["data"]
        done = call(include_sequence_siblings=True, dry_run=False, confirm=fresh["confirm"])
        assert done["ok"] and len(done["data"]["deleted"]) == 3
        assert not any(os.path.exists(p) for p in panorama.paths)

    def test_cull_apply_binds_the_flag(self, panorama):
        def call(**kw):
            return panorama.env.call(panorama.token, "cull_apply", {
                "action": "move_rejects", "target_dir": panorama.target, "paths": [panorama.lead], **kw})
        plain = call()["data"]
        assert plain["would_move_count"] == 1
        wide = call(include_sequence_siblings=True)["data"]
        assert wide["would_move_count"] == 3 and wide["sequence_siblings"] == 2
        assert call(dry_run=False, confirm=wide["confirm"])["error"] == "confirmation_required"
        assert all(os.path.exists(p) for p in panorama.paths)
        fresh = call(include_sequence_siblings=True)["data"]
        done = call(include_sequence_siblings=True, dry_run=False, confirm=fresh["confirm"])
        assert done["ok"] and done["data"]["moved"] == 3


@pytest.fixture()
def library(edition, seed_photos_prefix, tmp_path, monkeypatch):
    """Four photos on disk: r1, r2 rejected, k1 kept (r1 has a RAW companion)."""
    lib = _disk_library(edition, seed_photos_prefix, tmp_path, monkeypatch, "src", [
        ("r1.jpg", {"is_rejected": 1}), ("r2.jpg", {"is_rejected": 1}), ("k1.jpg", {"is_rejected": 0})],
        [("r1.CR2", b"RAW")])
    lib.r1, lib.r2, lib.k1 = lib.paths
    lib.listing = lambda d: sorted(os.listdir(d)) if os.path.isdir(d) else []
    return lib


class TestCullApply:
    def args(self, lib, **extra):
        return {"action": "move_rejects", "target_dir": lib.target, "paths": [lib.r1, lib.r2], **extra}

    def dry(self, lib, **extra):
        result = lib.env.call(lib.token, "cull_apply", self.args(lib, **extra))
        assert result["ok"], result
        return result["data"]

    def test_dry_run_moves_nothing_and_issues_a_nonce(self, library):
        data = self.dry(library)
        assert data["dry_run"] is True and data["would_move_count"] == 2 and data["confirm"]
        assert library.listing(library.target) == []

    def test_apply_without_a_dry_run_is_refused(self, library):
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.src) == ["k1.jpg", "r1.CR2", "r1.jpg", "r2.jpg"]

    def test_dry_run_then_apply_moves_files_without_companions_by_default(self, library):
        confirm = self.dry(library)["confirm"]
        done = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert done["ok"] and done["data"]["moved"] == 2
        assert library.listing(library.target) == ["r1.jpg", "r2.jpg"]
        assert library.listing(library.src) == ["k1.jpg", "r1.CR2"]

    def test_companions_follow_only_when_asked(self, library):
        data = self.dry(library, include_companions=True)
        assert data["would_move_count"] == 3
        done = library.env.call(library.token, "cull_apply", self.args(
            library, include_companions=True, dry_run=False, confirm=data["confirm"]))
        assert done["ok"] and "r1.CR2" in library.listing(library.target)

    def test_nonce_is_single_use(self, library):
        confirm = self.dry(library)["confirm"]
        args = self.args(library, dry_run=False, confirm=confirm)
        assert library.env.call(library.token, "cull_apply", args)["ok"]
        assert library.env.call(library.token, "cull_apply", args)["error"] == "confirmation_required"

    def test_garbage_nonce_is_refused(self, library):
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm="nope"))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.target) == []

    def test_target_set_changed_since_the_dry_run(self, library):
        confirm = self.dry(library)["confirm"]
        headers = library.env.login(edition=True)
        resp = library.env.client.post("/api/photo/toggle_rejected", json={"photo_path": library.r2}, headers=headers)
        assert resp.status_code == 200
        result = library.env.call(library.token, "cull_apply", self.args(
            library, dry_run=False, confirm=confirm))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.target) == [] and os.path.exists(library.r1)

    def test_nonce_is_bound_to_the_request_options_and_the_token(self, library):
        confirm = self.dry(library)["confirm"]
        other_set = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "paths": [library.r1],
            "dry_run": False, "confirm": confirm})
        assert other_set["error"] == "confirmation_required"
        confirm = self.dry(library)["confirm"]
        env = library.env
        second = env.token(env.login(edition=True), "edition", name="other")
        stolen = env.call(second, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert stolen["error"] == "confirmation_required"
        # A stranger presenting it did not burn the owner's.
        assert env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))["ok"]

    def test_nonce_expires(self, library):
        confirm = self.dry(library)["confirm"]
        later = time.monotonic() + nonce.TTL_SECONDS + 1
        limits.set_clock(lambda: later)
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert result["error"] == "confirmation_required"
        assert os.path.exists(library.r1)

    def test_kept_photo_is_excluded_by_state_and_not_moved(self, library):
        data = self.dry(library, paths=[library.r1, library.k1])
        assert data["excluded_by_state"] == 1 and data["would_move_count"] == 1
        library.env.call(library.token, "cull_apply", self.args(
            library, paths=[library.r1, library.k1], dry_run=False, confirm=data["confirm"]))
        assert os.path.exists(library.k1) and not os.path.exists(library.r1)

    def test_copy_keeps_needs_no_nonce(self, library):
        done = library.env.call(library.token, "cull_apply", {
            "action": "copy_keeps", "target_dir": library.target, "paths": [library.k1], "dry_run": False})
        assert done["ok"] and done["data"]["copied"] == 1
        assert library.listing(library.target) == ["k1.jpg"]

    def test_trash_is_refused_upstream_when_disabled(self, library, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": False})
        result = library.env.call(library.token, "cull_apply", {"action": "trash_rejects", "paths": [library.r1]})
        assert result["ok"] is False and "allow_trash" in result["message"]
        assert os.path.exists(library.r1)

    def test_filter_scope_requires_expected_count(self, library, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_rejected", True)
        filters = {"path_prefix": library.src + "/", "show_rejected": True}
        result = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters})
        assert result["error"] == "invalid_input"
        wrong = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters, "expected_count": 7})
        assert wrong["error"] == "invalid_input" and wrong["actual_count"] == 2
        ok_run = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters, "expected_count": 2})
        assert ok_run["ok"] and ok_run["data"]["would_move_count"] == 2

    def test_filters_hide_rejected_photos_like_search_photos_unless_shown(self, library, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_rejected", True)
        scope = {"path_prefix": library.src + "/"}
        searched = library.env.call(library.token, "search_photos", {"filters": scope, "show": False})
        assert searched["data"]["total"] == 1
        keeps = library.env.call(library.token, "cull_apply", {
            "action": "copy_keeps", "target_dir": library.target, "filters": scope,
            "expected_count": searched["data"]["total"]})
        assert keeps["ok"] is True, keeps
        refused = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": scope, "expected_count": 3})
        assert refused["error"] == "invalid_input" and refused["actual_count"] == 1

    def test_a_file_missing_on_disk_is_skipped_with_a_reason(self, library):
        os.remove(library.r2)
        data = self.dry(library)
        assert data["skipped"] == [library.r2] and "skipped_reason" in data
        assert "disk" in data["skipped_reason"]

    def test_non_edition_tokens_are_refused(self, library, agent_app):
        env = agent_app("multi")
        for level in ("readonly", "user"):
            token = env.token(env.login("alice"), level)
            result = env.call(token, "cull_apply", self.args(library))
            assert result["error"] == "forbidden_level"

    def test_real_run_timeout_is_outcome_unknown(self, library, monkeypatch):
        confirm = self.dry(library)["confirm"]
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/cull/apply") and kw.get("json", {}).get("dry_run") is False:
                raise httpx.ReadTimeout("slow")
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert result["error"] == "outcome_unknown"


class TestDeletePhotos:
    def count(self, lib):
        return db_row("SELECT COUNT(*) FROM photos WHERE path LIKE ?", lib.src + "/%")[0]

    def test_dry_run_deletes_nothing_then_apply_deletes_exactly_the_confirmed_set(self, library):
        def call(**kw):
            return library.env.call(library.token, "delete_photos", {"paths": [library.r1, library.k1], **kw})
        dry = call()["data"]
        assert dry["dry_run"] is True and dry["would_trash_count"] == 2 and self.count(library) == 3
        done = call(dry_run=False, confirm=dry["confirm"])
        assert done["ok"] and sorted(done["data"]["deleted"]) == sorted([library.r1, library.k1])
        assert self.count(library) == 1 and os.path.exists(library.r2)
        assert not os.path.exists(library.r1) and os.path.exists(os.path.join(library.src, "r1.CR2"))

    def test_apply_without_confirm_or_after_the_set_changed(self, library):
        def call(paths, **kw):
            return library.env.call(library.token, "delete_photos", {"paths": paths, **kw})
        assert call([library.r1], dry_run=False)["error"] == "confirmation_required"
        dry = call([library.r1, library.r2])["data"]
        os.remove(library.r2)
        again = call([library.r1, library.r2], dry_run=False, confirm=dry["confirm"])
        assert again["error"] == "confirmation_required" and self.count(library) == 3

    def test_user_token_is_refused(self, library, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        assert env.call(token, "delete_photos", {"paths": [library.r1]})["error"] == "forbidden_level"
        assert os.path.exists(library.r1)


class TestNonceModule:
    def test_digest_ignores_order_and_binds_options(self):
        assert nonce.digest(["b", "a"], {"x": 1}) == nonce.digest(["a", "b"], {"x": 1})
        assert nonce.digest(["a"], {"x": 1}) != nonce.digest(["a"], {"x": 2})

    def test_consume_semantics(self):
        digest = nonce.digest(["a"], {})
        value = nonce.issue(1, "act", digest)
        assert not nonce.consume(2, "act", digest, value)
        assert not nonce.consume(1, "other", digest, value)
        assert nonce.consume(1, "act", digest, value)
        assert not nonce.consume(1, "act", digest, value)
        burnt = nonce.issue(1, "act", digest)
        assert not nonce.consume(1, "act", nonce.digest(["b"], {}), burnt)
        assert not nonce.consume(1, "act", digest, burnt)

    def test_store_is_bounded(self):
        for _ in range(nonce.MAX_PENDING + 20):
            nonce.issue(1, "act", "h")
        assert len(nonce._pending) <= nonce.MAX_PENDING

    def test_one_token_cannot_flush_another_tokens_pending_nonce(self):
        nonce.reset()
        digest = nonce.digest(["a"], {})
        victim = nonce.issue(1, "act", digest)
        for _ in range(nonce.MAX_PENDING * 2):
            nonce.issue(2, "act", "h")
        assert nonce.consume(1, "act", digest, victim)
        assert sum(1 for entry in nonce._pending.values() if entry[0] == 2) <= nonce.MAX_PENDING_PER_OWNER

    def test_global_cap_evicts_the_issuers_own_entries_first(self):
        nonce.reset()
        others = nonce.MAX_PENDING // nonce.MAX_PENDING_PER_OWNER - 1
        for token in range(2, 2 + others):
            for _ in range(nonce.MAX_PENDING_PER_OWNER):
                nonce.issue(token, "act", "h")
        for _ in range(30):
            nonce.issue(1, "act", "h")
        assert len(nonce._pending) == nonce.MAX_PENDING
        assert sum(1 for entry in nonce._pending.values() if entry[0] != 1) == others * nonce.MAX_PENDING_PER_OWNER

    def test_global_cap_full_of_other_tokens_refuses_instead_of_evicting(self):
        nonce.reset()
        others = nonce.MAX_PENDING // nonce.MAX_PENDING_PER_OWNER
        for token in range(2, 2 + others):
            for _ in range(nonce.MAX_PENDING_PER_OWNER):
                nonce.issue(token, "act", "h")
        before = dict(nonce._pending)
        with pytest.raises(nonce.NonceCapacityError):
            nonce.issue(1, "act", "h")
        assert nonce._pending == before


class TestSetCaption:
    def call(self, edition, path, caption):
        env, token = edition
        return env.call(token, "set_caption", {"path": path, "caption": caption})

    def test_set_then_get_photo_returns_it_and_the_translation_is_cleared(self, edition, photos):
        conn = sqlite3.connect(_TEST_DB_FILE.name)
        conn.execute("UPDATE photos SET caption_translated = 'ancienne' WHERE path = ?", (P[0],))
        conn.commit()
        conn.close()
        result = self.call(edition, P[0], "a red door")
        assert result["ok"] and result["data"]["already"] is False
        env, token = edition
        assert env.call(token, "get_photo", {"path": P[0]})["data"]["caption"] == "a red door"
        assert photo_col(P[0], "caption_translated") is None

    def test_the_same_text_again_is_already_and_writes_nothing(self, edition, photos, counting):
        self.call(edition, P[1], "same")
        counting.clear()
        again = self.call(edition, P[1], "same")
        assert again["data"]["already"] is True and "set_caption" not in counting

    def test_an_empty_string_clears_the_caption(self, edition, photos):
        self.call(edition, P[2], "to clear")
        cleared = self.call(edition, P[2], "")
        assert cleared["ok"] and cleared["data"]["caption"] is None
        assert photo_col(P[2], "caption") is None

    def test_a_caption_over_2000_characters_is_invalid_input(self, edition, photos):
        assert self.call(edition, P[0], "x" * 2001)["error"] == "invalid_input"

    def test_a_readonly_token_is_forbidden(self, agent_app, photos):
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        assert env.call(token, "set_caption", {"path": P[0], "caption": "x"})["error"] == "forbidden_level"


def file_hashes(directory):
    import hashlib
    return {name: hashlib.md5(open(os.path.join(directory, name), "rb").read()).hexdigest()
            for name in sorted(os.listdir(directory)) if not name.endswith(".xmp")}


class TestExportMetadata:
    def export(self, lib, paths, **extra):
        return lib.env.call(lib.token, "export_metadata", {"paths": paths, **extra})

    def test_two_photos_get_sidecars_and_the_originals_are_untouched(self, library):
        before = file_hashes(library.src)
        result = self.export(library, [library.r1, library.k1])
        assert result["ok"], result
        data = result["data"]
        assert data["written"] == 2 and data["errors"] == 0 and data["sidecars_count"] == 2
        assert len([n for n in os.listdir(library.src) if n.endswith(".xmp")]) == 2
        assert file_hashes(library.src) == before

    def test_a_path_with_no_file_on_disk_is_counted_as_skipped(self, library, photos):
        data = self.export(library, [library.k1, P[0]])["data"]
        assert data["written"] == 1 and data["skipped"] == 1 and "skipped_reason" in data

    def test_more_than_100_paths_is_too_large(self, library):
        assert self.export(library, [f"/x/{i}.jpg" for i in range(101)])["error"] == "too_large"

    def test_an_exiftool_refusal_is_reported_not_swallowed(self, library, monkeypatch):
        def refuse(*args, **kwargs):
            raise RuntimeError("exiftool 13.25 corrupts XMP sidecars (bug in 13.23-13.27)")
        monkeypatch.setattr("api.routers.export.write_metadata", refuse)
        data = self.export(library, [library.r1, library.k1])["data"]
        assert data["written"] == 0 and data["errors"] == 2 and "13.23-13.27" in data["first_error"]

    def test_the_call_uses_the_dedicated_timeout_not_call_timeout_s(self, library, monkeypatch):
        seen = {}

        def spy(tool, kw):
            if tool == "export_metadata":
                seen["timeout"] = kw["timeout"]

        intercept_internal_call(monkeypatch, spy)
        self.export(library, [library.k1])
        assert seen["timeout"] == 180 != api_config.mcp_settings()["call_timeout_s"]

    def test_a_user_token_is_forbidden(self, agent_app, library):
        env = agent_app("legacy")
        token = env.token(env.login(), "user")
        assert env.call(token, "export_metadata", {"paths": [library.k1]})["error"] == "forbidden_level"


class TestFilterScopedBatchBeyondTheRouteCap:
    """A filter scope reaches the route as filters, so it may exceed the 1000 paths a path list takes."""
    PREFIX = AGENT_DIR + "big/"

    def test_1100_photo_filter_batch_is_written_and_every_photo_is_marked_agent_made(self, edition, seed_photos_prefix):
        env, token = edition
        rows = [{"path": f"{self.PREFIX}b{i:04d}.jpg", "filename": f"b{i:04d}.jpg", "aggregate": 5.0,
                 "star_rating": 1} for i in range(1100)]
        seed_photos_prefix(self.PREFIX, rows)
        scope = {"path_prefix": self.PREFIX}
        result = env.call(token, "batch_set_rating", {"filters": scope, "expected_count": 1100, "rating": 4})
        assert result["ok"], result
        assert result["data"]["affected"] == 1100
        assert db_row("SELECT COUNT(*) FROM photos WHERE path LIKE ? AND star_rating = 4", self.PREFIX + "%")[0] == 1100
        assert db_row("SELECT COUNT(*) FROM rating_provenance WHERE photo_path LIKE ?", self.PREFIX + "%")[0] == 1100


# ---- create_album from filters / the view / a set of photos ------------------------------------

ALBUM_DIR = "/agent-album-seeded/"


@pytest.fixture()
def album_headers(edition):
    """One edition session per test (the login route is rate-limited)."""
    return edition[0].login(edition=True)


@pytest.fixture()
def album_cleanup(edition, album_headers):
    """Delete every album a test made (the shared session DB outlives the test)."""
    env, _ = edition
    ids = []
    yield ids
    headers = album_headers
    for album_id in ids:
        env.client.delete(f"/api/albums/{album_id}", headers=headers)


def _album_rows():
    from api.types import TYPE_FILTERS
    rows = [
        {"path": ALBUM_DIR + "lead.jpg", "filename": "lead.jpg", "aggregate": 9.0, "burst_group_id": 7,
         "is_burst_lead": 1, "date_taken": "2026:03:01 10:00:00", "is_favorite": 1, "star_rating": 5},
        {"path": ALBUM_DIR + "follow1.jpg", "filename": "follow1.jpg", "aggregate": 8.0, "burst_group_id": 7,
         "is_burst_lead": 0, "date_taken": "2026:03:01 10:00:01"},
        {"path": ALBUM_DIR + "follow2.jpg", "filename": "follow2.jpg", "aggregate": 7.0, "burst_group_id": 7,
         "is_burst_lead": 0, "date_taken": "2026:03:01 10:00:02"},
        {"path": ALBUM_DIR + "dup_lead.jpg", "filename": "dup_lead.jpg", "aggregate": 6.0, "duplicate_group_id": 3,
         "is_duplicate_lead": 1, "is_monochrome": 1},
        {"path": ALBUM_DIR + "dup_copy.jpg", "filename": "dup_copy.jpg", "aggregate": 6.0, "duplicate_group_id": 3,
         "is_duplicate_lead": 0},
        {"path": ALBUM_DIR + "rejected.jpg", "filename": "rejected.jpg", "aggregate": 5.0, "is_rejected": 1,
         "star_rating": 4},
        {"path": ALBUM_DIR + "fav_rejected.jpg", "filename": "fav_rejected.jpg", "aggregate": 4.0, "is_favorite": 1,
         "is_rejected": 1},
        {"path": ALBUM_DIR + "plain.jpg", "filename": "plain.jpg", "aggregate": 3.0, "star_rating": 2,
         "date_taken": "2025:06:01 10:00:00"},
    ]
    for name in TYPE_FILTERS:
        if name != "top_picks":
            rows.append({"path": ALBUM_DIR + f"cat_{name}.jpg", "filename": f"cat_{name}.jpg", "aggregate": 4.5,
                         "category": name})
    return rows


@pytest.fixture()
def album_photos(seed_photos_prefix):
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    seed_photos_prefix(ALBUM_DIR, _album_rows())
    conn.execute("INSERT INTO persons (id, name) VALUES (9001, 'Album Person')")
    conn.executemany(
        "INSERT INTO faces (photo_path, face_index, embedding, person_id) VALUES (?, 0, x'00', 9001)",
        [(ALBUM_DIR + "lead.jpg",), (ALBUM_DIR + "plain.jpg",)])
    conn.commit()
    yield
    conn.execute("DELETE FROM faces WHERE person_id = 9001")
    conn.execute("DELETE FROM persons WHERE id = 9001")
    conn.commit()
    conn.close()


def _album_page_total(env, stored_json_text, headers, hide_toggles=True):
    """What the album page lists: ``/api/photos`` with the stored filters + the viewer's hide toggles."""
    import json
    from api.agent.album_filters import query_form
    from api.agent.tools_read import _hide_defaults
    from api.models.gallery import query_value
    query = query_form(json.loads(stored_json_text))
    if hide_toggles:
        query.update({k: query_value(v) for k, v in _hide_defaults({}).items()})
        if "favorites_only" in query:  # the page applies the store's rule (exclusiveHidePatch): favourites win
            query.pop("hide_rejected", None)
    resp = env.client.get("/api/photos", params={**query, "per_page": 1}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["total"]


def _album_listing_total(env, album_id, headers):
    """What the album's OWN listing route returns: the stored JSON read back by ``_normalize_smart_filters``."""
    resp = env.client.get(f"/api/albums/{album_id}/photos", params={"per_page": 1}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["total"]


def _unhidden_search_total(env, token, filters):
    """``search_photos`` with every hide toggle off: the row set the album listing (no display toggles) must equal."""
    from api.agent.tools_read import HIDE_DEFAULT_KEYS
    unhidden = {**filters, **{key: False for key in HIDE_DEFAULT_KEYS if key not in filters}}
    return env.call(token, "search_photos", {"filters": unhidden, "show": False, "per_page": 1})["data"]["total"]


PARITY_CASES = {
    "person": {"person": "9001"},
    "type_top_picks": {"type": "top_picks"},
    "favorites_only": {"favorites_only": True},
    "is_monochrome": {"is_monochrome": True},
    "dates": {"date_from": "2026-03-01", "date_to": "2026-03-02"},
    "path_prefix": {"path_prefix": ALBUM_DIR},
    "score_range": {"min_score": 5, "max_score": 7.5},
    "star_rating": {"min_star_rating": 3},
}


class TestSmartAlbumParity:
    """``create_album(filters)`` == ``search_photos(filters)`` == the album page (stored filters + hide toggles)."""

    def test_hiding_discriminates_in_the_seed(self, edition, album_photos, album_headers):
        env, _ = edition
        headers = album_headers
        with_hide = _album_page_total(env, "{}", headers, hide_toggles=True)
        without = _album_page_total(env, "{}", headers, hide_toggles=False)
        assert without > with_hide

    @pytest.mark.parametrize("case", sorted(PARITY_CASES))
    def test_totals_agree_on_every_surface(self, edition, album_photos, album_cleanup, album_headers, case):
        env, token = edition
        filters = PARITY_CASES[case]
        created = env.call(token, "create_album", {"name": f"parity {case}", "filters": filters})
        assert created["ok"], created
        album_cleanup.append(created["data"]["id"])
        searched = env.call(token, "search_photos", {"filters": filters, "show": False, "per_page": 1})
        page = _album_page_total(env, created["data"]["smart_filter_json"], album_headers)
        assert created["data"]["photo_count"] == searched["data"]["total"] == page
        assert _album_listing_total(env, created["data"]["id"], album_headers) == _unhidden_search_total(
            env, token, filters)
        # The server reads both name forms, so only the stored keys can show a skipped rename: the Angular
        # album page reads person_id / type / semanticQuery and ignores their contract spellings.
        from api.agent.ui_tools import CONTRACT_TO_CLIENT_KEY
        assert not set(json.loads(created["data"]["smart_filter_json"])) & set(CONTRACT_TO_CLIENT_KEY)
        assert created["data"]["is_smart"] is True
        if case not in ("type_top_picks", "empty"):
            assert 0 < page

    def test_every_configured_category_agrees(self, edition, album_photos, album_cleanup, album_headers, monkeypatch):
        from api.types import TYPE_FILTERS
        monkeypatch.setattr(limits, "check_rate", lambda *args: (True, 0.0))  # ~70 calls, past the write window
        env, token = edition
        headers = album_headers
        for name in TYPE_FILTERS:
            if name == "top_picks":
                continue
            created = env.call(token, "create_album", {"name": f"parity {name}", "filters": {"category": name}})
            assert created["ok"], (name, created)
            album_cleanup.append(created["data"]["id"])
            searched = env.call(token, "search_photos", {"filters": {"category": name}, "show": False,
                                                         "per_page": 1})
            assert created["data"]["photo_count"] == searched["data"]["total"] >= 1, name
            assert _album_page_total(env, created["data"]["smart_filter_json"], headers) == searched["data"]["total"], name
            assert _album_listing_total(env, created["data"]["id"], headers) == _unhidden_search_total(
                env, token, {"category": name}), name

    def test_a_favourites_album_keeps_a_rejected_favourite_on_every_surface(self, edition, album_photos,
                                                                           album_cleanup, album_headers):
        """``favorites_only`` and ``hide_rejected`` are exclusive: the count, the page and the listing agree."""
        env, token = edition
        created = env.call(token, "create_album", {"name": "favs", "filters": {"favorites_only": True}})
        album_cleanup.append(created["data"]["id"])
        listing = env.client.get(f"/api/albums/{created['data']['id']}/photos", params={"per_page": 50},
                                 headers=album_headers).json()
        assert ALBUM_DIR + "fav_rejected.jpg" in [p["path"] for p in listing["photos"]]
        assert created["data"]["photo_count"] == listing["total"]
        assert _album_page_total(env, created["data"]["smart_filter_json"], album_headers) == listing["total"]

    def test_stored_json_is_the_client_form_without_hide_toggles(self, edition, album_photos, album_cleanup):
        import json
        env, token = edition
        created = env.call(token, "create_album", {"name": "form", "filters": {
            "person": 9001, "category": "portrait", "favorites_only": True, "min_score": 6}})
        album_cleanup.append(created["data"]["id"])
        assert json.loads(created["data"]["smart_filter_json"]) == {
            "person_id": "9001", "type": "portrait", "favorites_only": True, "min_score": "6"}

    def test_unmatched_filters_warn_and_count_zero(self, edition, album_photos, album_cleanup):
        env, token = edition
        created = env.call(token, "create_album", {"name": "none", "filters": {"path_prefix": "/nowhere-at-all/"}})
        album_cleanup.append(created["data"]["id"])
        assert created["data"]["photo_count"] == 0 and "warning" in created["data"]

    @pytest.mark.parametrize("filters", [
        {"exclude_tags": "x"}, {"require_tags": "x"}, {"is_silhouette": True}, {"junk_kind": "blurry"},
        {"narrative_moment": "other"}, {"min_rating": 3}, {"min_aggregate": 5}, {"show_rejected": True},
        {"hide_bursts": False}, {"hide_rejected": True}, {"gps_lat": 1.0}, {"album_id": 5},
    ])
    def test_unsupported_filters_are_refused_and_create_nothing(self, edition, album_photos, filters):
        env, token = edition
        before = db_row("SELECT COUNT(*) FROM albums")[0]
        refused = env.call(token, "create_album", {"name": "refused", "filters": filters})
        assert refused["error"] == "unsupported_filters" and refused["keys"] == sorted(filters)
        assert db_row("SELECT COUNT(*) FROM albums")[0] == before

    def test_an_ineffective_unsupported_value_is_not_an_unsupported_refusal(self, edition, album_photos, album_cleanup):
        env, token = edition
        created = env.call(token, "create_album", {"name": "ok", "filters": {"show_rejected": False, "min_score": 5}})
        assert created["ok"], created
        album_cleanup.append(created["data"]["id"])

    @pytest.mark.parametrize("filters", [{}, {"show_rejected": False}, {"type": ""}, {"favorites_only": False},
                                         {"tag": ""}, {"path_prefix": ""}, {"camera": ""}])
    def test_filters_that_store_nothing_are_refused_not_saved_as_the_whole_library(
            self, edition, album_photos, filters):
        env, token = edition
        before = db_row("SELECT COUNT(*) FROM albums")[0]
        refused = env.call(token, "create_album", {"name": "everything", "filters": filters})
        assert refused["error"] == "invalid_input" and "no storable filter" in refused["message"], refused
        assert db_row("SELECT COUNT(*) FROM albums")[0] == before

    def test_type_with_category_and_unknown_category_are_invalid_input(self, edition, album_photos):
        env, token = edition
        both = env.call(token, "create_album", {"name": "x", "filters": {"type": "portrait", "category": "macro"}})
        assert both["error"] == "invalid_input"
        unknown = env.call(token, "create_album", {"name": "x", "filters": {"category": "no-such-category"}})
        assert unknown["error"] == "invalid_input"

    def test_more_than_one_of_filters_paths_target_is_invalid_input(self, edition, album_photos):
        env, token = edition
        before = db_row("SELECT COUNT(*) FROM albums")[0]
        refused = env.call(token, "create_album", {"name": "x", "filters": {}, "paths": [ALBUM_DIR + "plain.jpg"]})
        assert refused["error"] == "invalid_input"
        assert db_row("SELECT COUNT(*) FROM albums")[0] == before


GOLDEN = Path(__file__).resolve().parent.parent / "client/src/app/features/gallery/testing/smart-album-stored.json"


@pytest.mark.parametrize("key", ["semantic_query", "semanticQuery", "semantic_threshold", "search_threshold",
                                 "similar_to", "similarity_mode", "min_similarity"])
def test_semantic_and_similar_keys_are_refused_in_both_name_forms(key):
    from api.agent import album_filters
    refusal, stored = album_filters.to_stored({"min_score": 5, key: "x"})
    assert refusal["error"] == "unsupported_filters" and refusal["keys"] == [key]
    assert stored == {}


def test_stored_form_equals_the_golden_fixture_the_client_loads():
    """The same file the gallery's vitest loads: what the tool stores is what the album page reads back."""
    from api.agent import album_filters
    golden = json.loads(GOLDEN.read_text())
    refusal, stored = album_filters.to_stored(golden["contract_filters"])
    assert refusal is None
    assert stored == golden["stored"]
    assert json.loads(album_filters.stored_json(stored)) == golden["stored"]


class TestCreateAlbumFromPaths:
    """``paths`` -> a fixed album, created and filled by one call; never ``ok`` for a half-done one."""

    def album_paths(self, album_id):
        conn = sqlite3.connect(_TEST_DB_FILE.name)
        try:
            return [r[0] for r in conn.execute(
                "SELECT photo_path FROM album_photos WHERE album_id = ? ORDER BY position", (album_id,))]
        finally:
            conn.close()

    def test_created_and_filled_with_the_unknown_path_reported_as_skipped(self, edition, photos, album_cleanup):
        env, token = edition
        unknown = AGENT_DIR + "never-scanned.jpg"
        result = env.call(token, "create_album", {"name": "fixed", "paths": [P[0], unknown, P[1]]})
        assert result["ok"], result
        album_cleanup.append(result["data"]["id"])
        data = result["data"]
        assert data["added"] == 2 and data["photo_count"] == 2 and data["skipped"] == [unknown]
        assert data["skipped_count"] == 1 and "warning" not in data
        assert data["is_smart"] is False
        assert self.album_paths(data["id"]) == [P[0], P[1]]

    def test_every_path_unknown_warns_instead_of_a_silent_ok(self, edition, photos, album_cleanup):
        env, token = edition
        unknown = [AGENT_DIR + "never-1.jpg", AGENT_DIR + "never-2.jpg"]
        result = env.call(token, "create_album", {"name": "nothing", "paths": unknown})
        assert result["ok"], result
        album_cleanup.append(result["data"]["id"])
        data = result["data"]
        assert data["added"] == 0 and data["photo_count"] == 0 and data["skipped_count"] == 2
        assert "warning" in data and self.album_paths(data["id"]) == []

    def test_too_many_paths_create_no_album(self, edition, photos):
        env, token = edition
        before = db_row("SELECT COUNT(*) FROM albums")[0]
        result = env.call(token, "create_album", {"name": "huge", "paths": [f"/x/{i}.jpg" for i in range(1001)]})
        assert result["error"] == "too_large"
        assert db_row("SELECT COUNT(*) FROM albums")[0] == before

    def test_a_failed_add_keeps_the_empty_album_and_says_so(self, edition, photos, album_cleanup, monkeypatch):
        env, token = edition
        intercept_internal_call(monkeypatch, lambda tool, kw: {
            "ok": False, "error": "library_busy", "message": "The library is busy; retry in a moment"
        } if tool == "album_add_photos" else None)
        result = env.call(token, "create_album", {"name": "half done", "paths": P[:3]})
        assert result["ok"] is False and result["error"] == "library_busy"
        assert result["created"] is True and result["added"] == 0 and result["not_attempted"] == 3
        album_cleanup.append(result["album_id"])
        assert db_row("SELECT COUNT(*) FROM albums WHERE id = ?", result["album_id"])[0] == 1
        assert self.album_paths(result["album_id"]) == []

    def test_an_unknown_outcome_is_in_doubt(self, edition, photos, album_cleanup, monkeypatch):
        env, token = edition
        intercept_internal_call(monkeypatch, lambda tool, kw: {
            "ok": False, "error": "outcome_unknown", "message": "timed out"
        } if tool == "album_add_photos" else None)
        result = env.call(token, "create_album", {"name": "in doubt", "paths": P[:2]})
        assert result["error"] == "outcome_unknown" and result["in_doubt"] and result["created"] is True
        album_cleanup.append(result["album_id"])

    def test_a_failed_create_adds_nothing(self, edition, photos, monkeypatch):
        env, token = edition
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool) or (
            {"ok": False, "error": "library_busy", "message": "busy"} if tool == "create_album" else None))
        result = env.call(token, "create_album", {"name": "never", "paths": P[:2]})
        assert result["error"] == "library_busy" and "album_add_photos" not in calls

    def test_in_page_the_add_leg_reports_changed_paths(self, edition, photos, album_cleanup, album_headers):
        env, _ = edition
        headers = album_headers
        resp = env.client.post("/api/mcp/call", headers={**headers, "X-Facet-Agent-Session": "tab-a"},
                               json={"tool": "create_album", "arguments": {"name": "inpage fixed", "paths": P[:2]}})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"], body
        album_cleanup.append(body["data"]["id"])
        assert body["changed_paths"] == P[:2]


def test_manual_review_filter_is_boolean_in_stored_album_and_in_query_contract():
    from api.agent import album_filters
    from api.agent.tools_common import MCP_FILTER_KEYS
    assert 'manual_faces_need_review' in MCP_FILTER_KEYS
    refusal, stored = album_filters.to_stored({'manual_faces_need_review': '1'})
    assert refusal is None
    assert stored == {'manual_faces_need_review': True}
    assert album_filters.query_form(stored) == {'manual_faces_need_review': '1'}
