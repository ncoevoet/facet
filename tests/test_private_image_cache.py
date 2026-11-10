"""Private library bytes always require authorization before cache reuse."""

from io import BytesIO

import pytest
from PIL import Image

from api import config
from api.auth import hash_password


@pytest.mark.parametrize("route,extra", [("/thumbnail", {}), ("/thumbnail", {"size": 1920}), ("/image", {})])
def test_private_image_revalidation_checks_live_session(agent_app, seed_photos_prefix, tmp_path, route, extra):
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
    config._FULL_CONFIG["users"]["root"]["password_hash"] = hash_password("rotated")
    refused = env.client.get(route, params=params, headers=conditional)
    assert refused.status_code not in (200, 206, 304)
    env.client.cookies.set("facet_auth", headers["Authorization"].split(" ", 1)[1])
    assert env.client.get(route, params=params, headers={"If-None-Match": first.headers["etag"]}).status_code not in (200, 206, 304)
