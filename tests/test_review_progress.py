"""Review counts use the complete visible scope, independent of pagination."""
import sqlite3

import pytest

from db import DEFAULT_DB_PATH


@pytest.mark.parametrize("client_name", ["edition_client", "regular_client"])
def test_review_progress_ignores_active_decision_and_paging(request, client_name, seed_photos_prefix):
    client = request.getfixturevalue(client_name)
    prefix = "/review-progress/"
    seed_photos_prefix(prefix, [
        {"path": prefix + str(i) + ".jpg", "filename": str(i) + ".jpg", "camera_model": camera,
         "is_kept": kept, "is_rejected": rejected}
        for i, (camera, kept, rejected) in enumerate([
            ("ProgressCam", 0, 0), ("ProgressCam", 1, 0), ("ProgressCam", 1, 1),
            ("OtherCam", 0, 0)])])
    response = client.get("/api/photos/review_progress", params={"path_prefix": prefix,
        "camera": "ProgressCam", "review_status": "undecided", "hide_rejected": "1", "per_page": 1, "page": 5})
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 3, "undecided": 1, "kept": 1, "rejected": 1}


def test_review_progress_private_preferences_and_visibility(regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    prefix = "/review-progress-private/"
    monkeypatch.setitem(config._FULL_CONFIG, "users", {"u1": {"directories": [prefix + "visible"]}})
    visible, hidden = prefix + "visible/a.jpg", prefix + "hidden/b.jpg"
    seed_photos_prefix(prefix, [{"path": p, "filename": "a.jpg", "is_kept": 1} for p in [visible, hidden]])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_rejected) VALUES('u1', ?, 1)", [visible])
        conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_kept) VALUES('bob', ?, 1)", [visible])
    try:
        response = regular_client.get("/api/photos/review_progress", params={"path_prefix": prefix})
        assert response.status_code == 200, response.text
        assert response.json() == {"total": 1, "undecided": 0, "kept": 0, "rejected": 1}
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", [prefix + "%"])


def test_review_progress_empty_and_missing_album(regular_client):
    response = regular_client.get("/api/photos/review_progress", params={"path_prefix": "/missing-progress/"})
    assert response.status_code == 200, response.text
    assert response.json() == {"total": 0, "undecided": 0, "kept": 0, "rejected": 0}
    assert regular_client.get("/api/photos/review_progress", params={"album_id": 987654321}).status_code == 404


def test_review_progress_album_scope_and_access(edition_client, regular_client, seed_photos_prefix, album_factory, monkeypatch):
    prefix = "/review-progress-album/"
    seed_photos_prefix(prefix, [{"path": prefix + n + ".jpg", "filename": n + ".jpg", "is_kept": int(n == "a")}
                               for n in ["a", "b", "outside"]])
    album = album_factory(prefix, "review-progress-token", "Progress")(member_names=["a.jpg", "b.jpg"])
    response = edition_client.get("/api/photos/review_progress", params={"album_id": album})
    assert response.json() == {"total": 2, "undecided": 1, "kept": 1, "rejected": 0}
    monkeypatch.setattr("api.routers.albums.is_access_controlled_install", lambda: True)
    assert regular_client.get("/api/photos/review_progress", params={"album_id": album}).status_code == 403


def test_review_progress_retains_base_smart_review_criterion(edition_client, seed_photos_prefix):
    prefix = "/review-progress-smart/"
    seed_photos_prefix(prefix, [{"path": prefix + n + ".jpg", "filename": n + ".jpg", "is_kept": int(n == "a")}
                               for n in ["a", "b"]])
    response = edition_client.get("/api/photos/review_progress", params={"path_prefix": prefix,
        "scope_review_status": "kept", "review_status": "undecided"})
    assert response.json() == {"total": 1, "undecided": 0, "kept": 1, "rejected": 0}
    assert edition_client.get("/api/photos/review_progress", params={"scope_review_status": "bogus"}).status_code == 422
