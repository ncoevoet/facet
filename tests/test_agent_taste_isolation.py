"""Agent-originated writes never train the taste model; the same writes by a person still do.

[REAL] ``agent_app`` (real auth chain), real routes, seeded burst rows. The two recording sinks are
observed, not mocked away: ``comparisons`` rows are counted, and the ranker nudge
(``trigger_auto_retrain``, patched where ``faces`` and ``burst_culling`` import it) and the rating-sync scheduler (``_mint_rating_comparisons``) are
wrapped by recorders that still call through.
"""

import sqlite3

import pytest

from api import db_helpers
from api.routers import burst_culling, faces
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "taste/"
ROWS = [{"path": PREFIX + f"t{i}.jpg", "filename": f"t{i}.jpg", "date_taken": f"1998:01:01 10:00:{i:02d}",
         "aggregate": 9.0 - 3 * i, "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
         "burst_group_id": 5151, "is_burst_lead": 1 if i == 0 else 0, "star_rating": 0}
        for i in range(3)]
PATHS = [row["path"] for row in ROWS]
GROUP = {"type": "burst", "group_id": 5151, "paths": PATHS, "keep_paths": PATHS[:1]}


def comparisons() -> int:
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT COUNT(*) FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                            (PREFIX + "%", PREFIX + "%")).fetchone()[0]


def arms(args, kwargs) -> bool:
    """Whether a call would arm the retrain: ``trigger_auto_retrain`` itself ignores ``added <= 0``."""
    return (args[2] if len(args) > 2 else kwargs.get("added", 1)) > 0


@pytest.fixture()
def world(agent_app, seed_photos_prefix, monkeypatch):
    seed_photos_prefix(PREFIX, ROWS)
    nudges, mints = [], []
    real_nudge, real_mint = db_helpers.trigger_auto_retrain, faces._mint_rating_comparisons
    for module in (db_helpers, faces, burst_culling):
        monkeypatch.setattr(module, "trigger_auto_retrain",
                            lambda *a, _real=real_nudge, **k: (nudges.append(a) if arms(a, k) else None, _real(*a, **k))[1])
    monkeypatch.setattr(faces, "_mint_rating_comparisons", lambda *a, **k: (mints.append(a), real_mint(*a, **k))[1])
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition"), nudges, mints
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                     (PREFIX + "%", PREFIX + "%"))
        conn.execute("DELETE FROM rating_provenance WHERE photo_path LIKE ?", (PREFIX + "%",))


def test_confirm_culling_groups_via_mcp_adds_zero_comparisons_and_does_not_arm_retrain(world):
    env, token, nudges, _ = world
    before = comparisons()
    result = env.call(token, "confirm_culling_groups", {"groups": [GROUP]})
    assert result["ok"] and result["data"]["rows"][0]["rejected"] == 2, result
    assert comparisons() == before and nudges == []


def test_ui_confirm_still_records_comparisons(world):
    env, _, nudges, _ = world
    before = comparisons()
    resp = env.client.post("/api/culling-groups/confirm", json=GROUP, headers=env.login(edition=True))
    assert resp.status_code == 200, resp.text
    assert comparisons() > before and nudges


def test_mcp_set_rating_set_rejected_mint_no_comparisons(world):
    env, token, nudges, mints = world
    assert env.call(token, "set_rating", {"paths": PATHS[:1], "rating": 5})["data"]["affected"] == 1
    assert env.call(token, "set_favorite", {"paths": PATHS[1:2], "value": True})["data"]["affected"] == 1
    assert env.call(token, "set_rejected", {"paths": PATHS[2:], "value": True})["data"]["affected"] == 1
    assert mints == [] and nudges == []
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": PATHS[0], "rating": 4},
                           headers=env.login(edition=True))
    assert resp.status_code == 200 and len(mints) == 1


def test_auto_cull_apply_via_mcp_records_nothing(world):
    env, token, nudges, _ = world
    scope = {"group_by": "burst", "date_from": "1998:01:01 00:00:00", "date_to": "1998:01:01 23:59:59",
             "strictness": 0}
    preview = env.call(token, "auto_cull", scope)
    assert preview["ok"] and preview["data"]["rejected"], preview
    before = comparisons()
    done = env.call(token, "auto_cull", {**scope, "dry_run": False, "confirm": preview["confirm"]})
    assert done["ok"], done
    assert comparisons() == before and nudges == []


EXTRA = PREFIX + "human/"


def pairs_touching(paths):
    from db import get_connection
    from optimization.label_pairs import generate_rating_pairs
    with get_connection(_TEST_DB_FILE.name) as conn:
        found = generate_rating_pairs(conn)
    return [p for p in found if set(p[:2]) & set(paths)]


@pytest.fixture()
def labelled(world, seed_photos_prefix):
    """Three photos the assistant rates 5 / 5 / 1, and one the person rated 1 (the only human label)."""
    seed_photos_prefix(EXTRA, [{"path": EXTRA + "h.jpg", "filename": "h.jpg", "aggregate": 5.0, "star_rating": 1}])
    env, token, nudges, mints = world
    for path, rating in zip(PATHS, (5, 5, 1)):
        assert env.call(token, "set_rating", {"paths": [path], "rating": rating})["data"]["affected"] == 1
    return env, token


def test_agent_rated_photos_never_reach_the_rating_pairs(labelled):
    assert pairs_touching(PATHS) == [], "an assistant's labels are not the user's taste"


def test_a_person_rerating_an_agent_photo_makes_it_count_again(labelled):
    env, _ = labelled
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": PATHS[0], "rating": 5},
                           headers=env.login(edition=True))
    assert resp.status_code == 200
    touching = pairs_touching(PATHS)
    assert touching and all(PATHS[0] in pair[:2] for pair in touching), touching
    assert not pairs_touching(PATHS[1:])


def test_a_filter_scoped_agent_batch_never_reaches_the_rating_pairs(world, seed_photos_prefix):
    env, token, _, _ = world
    seed_photos_prefix(EXTRA, [{"path": EXTRA + "h.jpg", "filename": "h.jpg", "aggregate": 5.0, "star_rating": 1}])
    scope = {"path_prefix": PREFIX, "hide_bursts": False}
    done = env.call(token, "batch_set_rating", {"rating": 3, "filters": scope, "exclude": [EXTRA + "h.jpg"],
                                         "expected_count": len(PATHS) + 1})
    assert done["ok"] and done["data"]["affected"] == len(PATHS), done
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": EXTRA + "h.jpg", "rating": 5},
                           headers=env.login(edition=True))
    assert resp.status_code == 200
    assert pairs_touching(PATHS) == [], "a filter-scoped assistant batch is not the user's taste"


def test_a_person_rerating_after_a_filter_scoped_agent_batch_counts_again(world):
    env, token, _, _ = world
    done = env.call(token, "batch_set_rating", {"rating": 3, "filters": {"path_prefix": PREFIX, "hide_bursts": False},
                                           "expected_count": len(PATHS)})
    assert done["ok"], done
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": PATHS[0], "rating": 5},
                           headers=env.login(edition=True))
    assert resp.status_code == 200
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        marked = {r[0] for r in conn.execute("SELECT photo_path FROM rating_provenance WHERE photo_path LIKE ?",
                                             (PREFIX + "%",))}
    assert marked == set(PATHS[1:]), "the person's write cleared only the mark on the photo they rated"


# --- Provenance at every reject site -------------------------------------------------------------------
DR = PREFIX + "dr/"


def _members(kind, extra=None):
    paths = [DR + f"{kind}{i}.jpg" for i in range(2)]
    rows = [{"path": p, "filename": p.rsplit("/", 1)[1], "aggregate": 5.0, "star_rating": 0, **(extra or {})}
            for p in paths]
    return paths, rows


def _marked(paths):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return {r[0] for r in conn.execute(
            f"SELECT photo_path FROM rating_provenance WHERE photo_path IN ({','.join('?' * len(paths))})", paths)}


def _mark(paths):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.executemany("INSERT OR REPLACE INTO rating_provenance (user_id, photo_path, star_rating, is_favorite, "
                         "is_rejected) VALUES ('', ?, 0, 0, 1)", [(p,) for p in paths])


GROUP_KINDS = {
    "burst": {"burst_group_id": 6161},
    "similar": {},
    "scene": {},
}


@pytest.mark.parametrize("kind", sorted(GROUP_KINDS))
def test_darkroom_confirm_marks_provenance_for_an_agent_and_clears_it_for_a_person(world, seed_photos_prefix, kind):
    env, token, _, _ = world
    paths, rows = _members(kind, GROUP_KINDS[kind])
    seed_photos_prefix(DR, rows)
    group = {"type": kind, "group_id": GROUP_KINDS[kind].get("burst_group_id", 1), "paths": paths,
             "keep_paths": paths[:1]}
    done = env.call(token, "confirm_culling_groups", {"groups": [group]})
    assert done["ok"] and done["data"]["rows"][0]["rejected"] == 1, done
    assert _marked(paths) == {paths[1]}, f"an assistant's {kind} reject must be marked"
    _mark(paths)
    resp = env.client.post("/api/culling-groups/confirm", json=group, headers=env.login(edition=True))
    assert resp.status_code == 200, resp.text
    assert _marked(paths) == {paths[0]}, f"a person's {kind} reject clears the mark of the photo it rejects"


def test_auto_cull_apply_marks_provenance_for_an_agent_and_clears_it_for_a_person(world):
    env, token, _, _ = world
    scope = {"group_by": "burst", "date_from": "1998:01:01 00:00:00", "date_to": "1998:01:01 23:59:59",
             "strictness": 0}
    preview = env.call(token, "auto_cull", scope)
    assert preview["ok"] and preview["data"]["rejected"], preview
    done = env.call(token, "auto_cull", {**scope, "dry_run": False, "confirm": preview["confirm"]})
    assert done["ok"], done
    marked = _marked(PATHS)
    assert marked and marked <= set(PATHS[1:]), marked
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        # Restore the whole decision before the second run; Keep protects a frame too.
        conn.execute("UPDATE photos SET is_rejected = 0, is_kept = 0 WHERE path LIKE ?", (PREFIX + "t%",))
        conn.execute("UPDATE photos SET burst_reviewed = 0 WHERE path LIKE ?", (PREFIX + "t%",))
    _mark(PATHS[1:])
    resp = env.client.post("/api/culling/auto", json={**scope, "dry_run": False}, headers=env.login(edition=True))
    assert resp.status_code == 200 and resp.json()["rejected"], resp.text
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        rejected = {r[0] for r in conn.execute("SELECT path FROM photos WHERE path LIKE ? AND is_rejected = 1",
                                               (PREFIX + "t%",))}
    assert rejected and not (_marked(PATHS) & rejected), "a person's auto-cull clears the marks of what it rejects"


# --- Which labels an assistant write marks ---------------------------------------------------------------
def test_an_agent_write_that_changes_nothing_leaves_the_persons_label_training(world):
    """User favourites t0 and rejects t2; the assistant re-asserts t0 favourite (no change) and favourites t1."""
    env, token, _, _ = world
    headers = env.login(edition=True)
    assert env.client.post("/api/photo/toggle_favorite", json={"photo_path": PATHS[0]}, headers=headers).status_code == 200
    assert env.client.post("/api/photo/toggle_rejected", json={"photo_path": PATHS[2]}, headers=headers).status_code == 200
    assert (PATHS[0], PATHS[2]) in {p[:2] for p in pairs_touching(PATHS)}
    done = env.call(token, "batch_set_favorite", {"paths": PATHS[:2]})
    assert done["ok"], done
    assert _marked(PATHS) == {PATHS[1]}, "only the photo the assistant actually changed is marked"
    assert (PATHS[0], PATHS[2]) in {p[:2] for p in pairs_touching(PATHS)}, "the person's favourite > reject pair survives"


def test_an_agent_filter_batch_marks_only_what_it_changed_and_keeps_existing_marks(world):
    env, token, _, _ = world
    headers = env.login(edition=True)
    assert env.client.post("/api/photo/set_rating", json={"photo_path": PATHS[0], "rating": 3}, headers=headers).status_code == 200
    scope = {"path_prefix": PREFIX, "hide_bursts": False}
    done = env.call(token, "batch_set_rating", {"rating": 3, "filters": scope, "expected_count": len(PATHS)})
    assert done["ok"], done
    assert _marked(PATHS) == set(PATHS[1:])
    again = env.call(token, "batch_set_rating", {"rating": 3, "filters": scope, "expected_count": len(PATHS)})
    assert again["ok"], again
    assert _marked(PATHS) == set(PATHS[1:]), "a path already marked stays marked when a later write changes nothing"


@pytest.mark.parametrize("agent", [True, False])
def test_sequence_confirm_marks_provenance_only_for_an_agent(world, seed_photos_prefix, agent):
    """The assistant tool refuses a keep-whole set, so the sequence site is driven over HTTP with the ``mcp`` claim."""
    from api.auth import create_access_token, decode_access_token
    env, _, _, _ = world
    paths, rows = _members("bracket", {"sequence_kind": "bracket", "sequence_group_id": 6162})
    seed_photos_prefix(DR, rows)
    headers = env.login(edition=True)
    if agent:
        claims = decode_access_token(headers["Authorization"].split(" ", 1)[1])
        headers = {"Authorization": "Bearer " + create_access_token({**claims, "mcp": True})}
    else:
        _mark(paths)
    group = {"type": "bracket", "group_id": 6162, "paths": paths, "keep_paths": paths[:1]}
    resp = env.client.post("/api/culling-groups/confirm", json=group, headers=headers)
    assert resp.status_code == 200 and resp.json()["rejected"] == 1, resp.text
    assert _marked(paths) == ({paths[1]} if agent else {paths[0]})
