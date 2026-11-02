"""An assistant reads the user-marked objects of a photo over /mcp, through the route allowlist.

[REAL] ``agent_app`` (real auth chain), the real routes and side tables.
"""

import pytest

from api.agent.internal_client import ROUTE_ALLOWLIST
from tests.conftest import AGENT_DIR, agent_db as db

PREFIX = AGENT_DIR + "objs/"
SHOT = PREFIX + "bottles.jpg"
OTHER = PREFIX + "plain.jpg"


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, [
        {"path": SHOT, "filename": "bottles.jpg", "aggregate": 6.0, "category": "default"},
        {"path": OTHER, "filename": "plain.jpg", "aggregate": 6.0, "category": "default"},
    ])
    env = agent_app("legacy")
    yield env, env.token(env.login(), "readonly")
    db("DELETE FROM photo_objects WHERE photo_path LIKE ?", PREFIX + "%")


def test_the_route_is_allowlisted_read_only():
    spec = ROUTE_ALLOWLIST["photo_objects"]
    assert (spec.method, spec.template, spec.min_level, spec.write) == ("GET", "/api/photo/objects", "readonly", False)


def test_get_photo_carries_the_marks_a_readonly_assistant_can_act_on(world):
    env, token = world
    db("INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2) VALUES (?, 'remove', 0.1, 0.2, 0.3, 0.6)", SHOT)
    data = env.call(token, "get_photo", {"path": SHOT})["data"]
    assert [(o["label"], o["box"]) for o in data["objects"]] == [("remove", [0.1, 0.2, 0.3, 0.6])]


def test_a_photo_without_marks_has_an_empty_list(world):
    env, token = world
    assert env.call(token, "get_photo", {"path": OTHER})["data"]["objects"] == []
