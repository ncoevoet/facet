"""Private library bytes always require authorization before cache reuse."""

from io import BytesIO

import pytest
from PIL import Image

from api import config
from api.auth import hash_password


def _change_password(): config._FULL_CONFIG["users"]["root"]["password_hash"] = hash_password("rotated")
def _demote(): config._FULL_CONFIG["users"]["root"]["role"] = "user"
def _delete(): del config._FULL_CONFIG["users"]["root"]


@pytest.mark.parametrize("change", [_change_password, _demote, _delete], ids=["password", "demote", "delete"])
@pytest.mark.parametrize("route,extra", [("/thumbnail", {}), ("/thumbnail", {"size": 1920}), ("/image", {})])
def test_private_image_revalidation_checks_live_session(
        agent_app, seed_photos_prefix, tmp_path, route, extra, change):
    env = agent_app("multi")
    config._FULL_CONFIG["users"]["root"]["directories"] = [str(tmp_path)]
    path = tmp_path / "private.jpg"
    data = BytesIO()
    Image.new("RGB", (64, 48), "red").save(data, "JPEG")
    path.write_bytes(data.getvalue())
    seed_photos_prefix(str(tmp_path), [{"path": str(path), "thumbnail": data.getvalue()}])
    headers = env.login("root")
    params = {"path": str(path), **extra}
    first = env.client.get(route, params=params, headers=headers)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, no-cache, must-revalidate"
    assert {"Authorization", "Cookie"} <= set(first.headers["vary"].split(", "))
    conditional = {**headers, "If-None-Match": first.headers["etag"]}
    cached = env.client.get(route, params=params, headers=conditional)
    assert cached.status_code == 304
    for header in ("cache-control", "vary", "etag"):
        assert cached.headers[header] == first.headers[header]
    change()
    refused = env.client.get(route, params=params, headers=conditional)
    # A stale session degrades to an anonymous caller, who sees no rows: 404,
    # never a 304 that would confirm the bytes to a revoked account.
    assert refused.status_code == 404
    assert "etag" not in refused.headers
    env.client.cookies.set("facet_auth", headers["Authorization"].split(" ", 1)[1])
    by_cookie = env.client.get(route, params=params, headers={"If-None-Match": first.headers["etag"]})
    assert by_cookie.status_code == 404
    assert "etag" not in by_cookie.headers
