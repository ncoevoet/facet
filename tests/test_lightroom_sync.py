"""Tests for processing/lightroom_sync.py (Step 2/3/5a of the Lightroom-flow spec)."""

import sqlite3

import pytest

from db.schema import init_database
from processing.lightroom_sync import (
    FORMAT,
    FORMAT_VERSION,
    InvalidLightroomStateFile,
    import_lightroom_state,
    validate_lightroom_state,
)


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "lr.db")
    init_database(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO photos (path, filename, aggregate, category, star_rating, "
        "is_favorite, is_rejected) VALUES (?, 'a.jpg', 7.0, 'default', 2, 1, 0)",
        ("/lib/a.jpg",),
    )
    conn.execute(
        "INSERT INTO photos (path, filename, aggregate, category, star_rating, "
        "is_favorite, is_rejected) VALUES (?, 'b.jpg', 6.0, 'default', 3, 0, 0)",
        ("/lib/b.jpg",),
    )
    conn.commit()
    conn.close()
    return path


def _fetch(db_path, path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?",
        (path,),
    ).fetchone()
    conn.close()
    return dict(row)


class TestImportLightroomStateSingleUser:
    def test_clears_existing_favorite_and_rating(self, db):
        records = [{"path": "/lib/a.jpg", "rating": 0, "pick": -1}]

        result = import_lightroom_state(db, records)

        assert result.matched == 1
        assert result.unmatched == 0
        assert result.changed == 1
        row = _fetch(db, "/lib/a.jpg")
        assert row["star_rating"] == 0
        assert row["is_favorite"] == 0
        assert row["is_rejected"] == 1

    def test_rating_only_record_leaves_pick_flags_untouched(self, db):
        records = [{"path": "/lib/a.jpg", "rating": 5}]

        result = import_lightroom_state(db, records)

        assert result.changed == 1
        row = _fetch(db, "/lib/a.jpg")
        assert row["star_rating"] == 5
        assert row["is_favorite"] == 1  # untouched, was already 1
        assert row["is_rejected"] == 0

    def test_unmatched_path_is_counted_not_errored(self, db):
        records = [{"path": "/lib/a.jpg", "rating": 4}, {"path": "/lib/nope.jpg", "rating": 1}]

        result = import_lightroom_state(db, records)

        assert result.matched == 1
        assert result.unmatched == 1

    def test_no_change_when_values_already_match(self, db):
        records = [{"path": "/lib/a.jpg", "rating": 2, "pick": 1}]

        result = import_lightroom_state(db, records)

        assert result.matched == 1
        assert result.changed == 0

    def test_pick_zero_clears_favorite_and_reject(self, db):
        """Locked decision: `pick == 0` clears BOTH flags, single-user mode (I9.1 / F1)."""
        records = [{"path": "/lib/a.jpg", "pick": 0}]

        result = import_lightroom_state(db, records)

        assert result.matched == 1
        assert result.changed == 1
        row = _fetch(db, "/lib/a.jpg")
        assert row["is_favorite"] == 0
        assert row["is_rejected"] == 0

    def test_case_insensitive_fallback_with_collision_refusal(self, db, tmp_path):
        path = str(tmp_path / "collide.db")
        init_database(path)
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, category) "
            "VALUES ('/Lib/X.jpg', 'X.jpg', 5.0, 'default')"
        )
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, category) "
            "VALUES ('/lib/x.jpg', 'x.jpg', 5.0, 'default')"
        )
        conn.commit()
        conn.close()

        result = import_lightroom_state(path, [{"path": "/LIB/X.JPG", "rating": 3}])

        assert result.matched == 0
        assert result.unmatched == 1


class TestImportLightroomStateMultiUser:
    def test_writes_user_preferences_not_photos(self, db, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        records = [{"path": "/lib/b.jpg", "rating": 4, "pick": 1}]

        result = import_lightroom_state(db, records, user_id="alice")

        assert result.matched == 1
        assert result.changed == 1
        # global photos row untouched
        assert _fetch(db, "/lib/b.jpg") == {"star_rating": 3, "is_favorite": 0, "is_rejected": 0}
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        urow = conn.execute(
            "SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
            "WHERE user_id = 'alice' AND photo_path = '/lib/b.jpg'"
        ).fetchone()
        conn.close()
        assert dict(urow) == {"star_rating": 4, "is_favorite": 1, "is_rejected": 0}

    def test_pick_zero_clears_favorite_and_reject_per_user(self, db, monkeypatch):
        """Same locked decision as the single-user test, per-user mode (I9.1 / F1)."""
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO user_preferences (user_id, photo_path, star_rating, is_favorite, "
            "is_rejected) VALUES ('alice', '/lib/a.jpg', 3, 1, 0)"
        )
        conn.commit()
        conn.close()

        result = import_lightroom_state(db, [{"path": "/lib/a.jpg", "pick": 0}], user_id="alice")

        assert result.matched == 1
        assert result.changed == 1
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        urow = dict(conn.execute(
            "SELECT is_favorite, is_rejected FROM user_preferences "
            "WHERE user_id = 'alice' AND photo_path = '/lib/a.jpg'"
        ).fetchone())
        conn.close()
        assert urow == {"is_favorite": 0, "is_rejected": 0}

    def test_disabled_multi_user_writes_global_columns(self, db, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
        records = [{"path": "/lib/b.jpg", "rating": 4}]

        import_lightroom_state(db, records, user_id="alice")

        assert _fetch(db, "/lib/b.jpg")["star_rating"] == 4
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0]
        conn.close()
        assert count == 0

    def test_explicit_per_user_true_overrides_api_config(self, db, monkeypatch):
        """I4: the CLI resolves per_user from --config and must not have it
        silently re-derived from api.config.is_multi_user_enabled(), which
        reads a possibly different file. Passing per_user=True explicitly
        must write to user_preferences even if api.config disagrees."""
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
        records = [{"path": "/lib/b.jpg", "rating": 4}]

        import_lightroom_state(db, records, user_id="alice", per_user=True)

        # global photos row untouched
        assert _fetch(db, "/lib/b.jpg")["star_rating"] == 3
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        urow = conn.execute(
            "SELECT star_rating FROM user_preferences "
            "WHERE user_id = 'alice' AND photo_path = '/lib/b.jpg'"
        ).fetchone()
        conn.close()
        assert dict(urow) == {"star_rating": 4}

    def test_explicit_per_user_false_overrides_api_config(self, db, monkeypatch):
        """Mirror of the above: per_user=False must write global columns even
        if api.config.is_multi_user_enabled() says True (I4)."""
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        records = [{"path": "/lib/b.jpg", "rating": 4}]

        import_lightroom_state(db, records, user_id="alice", per_user=False)

        assert _fetch(db, "/lib/b.jpg")["star_rating"] == 4
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0]
        conn.close()
        assert count == 0


class TestVisibilityScoping:
    """A caller-resolved ``visibility`` clause must restrict which
    DB rows a record may match, so a directory-scoped caller cannot use
    matched/unmatched counts as an existence oracle for, or write ratings
    against, an out-of-scope photo."""

    def test_record_outside_visibility_counts_unmatched_and_is_not_written(self, db):
        records = [
            {"path": "/lib/a.jpg", "rating": 5},
            {"path": "/lib/b.jpg", "rating": 4},
        ]

        result = import_lightroom_state(
            db, records, user_id="alice", visibility=("photos.path LIKE ?", ["/lib/a%"]),
        )

        assert result.matched == 1
        assert result.unmatched == 1
        assert result.changed == 1
        # /lib/b.jpg is outside visibility -- must be untouched despite being
        # a real, matching row when visibility is not applied.
        assert _fetch(db, "/lib/b.jpg") == {"star_rating": 3, "is_favorite": 0, "is_rejected": 0}

    def test_no_visibility_restriction_matches_every_row(self, db):
        """Baseline: omitting ``visibility`` (the CLI's own call) is unrestricted."""
        records = [{"path": "/lib/a.jpg", "rating": 5}, {"path": "/lib/b.jpg", "rating": 4}]

        result = import_lightroom_state(db, records, user_id="alice")

        assert result.matched == 2
        assert result.unmatched == 0


class TestValidateLightroomStateFile:
    def test_valid_document_returns_photos(self):
        photos = validate_lightroom_state(
            {"format": FORMAT, "version": FORMAT_VERSION, "photos": [{"path": "/a.jpg", "rating": 3}]}
        )
        assert photos == [{"path": "/a.jpg", "rating": 3}]

    def test_manifest_file_is_rejected(self):
        """A facet_manifest.json fed here by mistake must be refused (B7)."""
        manifest_like = {
            "version": 2,
            "generated_at": "2026-01-01T00:00:00Z",
            "photos": [{"path": "/a.jpg", "scores": {"aggregate": 8.0}}],
        }
        with pytest.raises(InvalidLightroomStateFile):
            validate_lightroom_state(manifest_like)

    def test_missing_format_and_version_is_rejected(self):
        with pytest.raises(InvalidLightroomStateFile):
            validate_lightroom_state({"photos": []})

    def test_record_with_only_pick_leaves_rating_key_absent(self):
        photos = validate_lightroom_state(
            {"format": FORMAT, "version": FORMAT_VERSION, "photos": [{"path": "/a.jpg", "pick": 1}]}
        )
        assert "rating" not in photos[0]

    def test_rating_zero_present_is_valid(self):
        photos = validate_lightroom_state(
            {"format": FORMAT, "version": FORMAT_VERSION, "photos": [{"path": "/a.jpg", "rating": 0}]}
        )
        assert photos[0]["rating"] == 0

    def test_bad_rating_type_is_rejected(self):
        with pytest.raises(InvalidLightroomStateFile):
            validate_lightroom_state(
                {"format": FORMAT, "version": FORMAT_VERSION, "photos": [{"path": "/a.jpg", "rating": 9}]}
            )

    def test_bad_pick_value_is_rejected(self):
        with pytest.raises(InvalidLightroomStateFile):
            validate_lightroom_state(
                {"format": FORMAT, "version": FORMAT_VERSION, "photos": [{"path": "/a.jpg", "pick": 2}]}
            )

    def test_non_list_photos_is_rejected(self):
        with pytest.raises(InvalidLightroomStateFile):
            validate_lightroom_state({"format": FORMAT, "version": FORMAT_VERSION, "photos": "nope"})


class TestRetrainNudge:
    def test_fires_auto_retrain_then_sync_in_order_with_resolved_scope(self, db, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        calls = []

        def fake_retrain(db_path, user_id, added=1, conn=None):
            calls.append(("retrain", user_id, added))

        def fake_sync(db_path, user_id=None, **kwargs):
            calls.append(("sync", user_id))

        monkeypatch.setattr("api.db_helpers.trigger_auto_retrain", fake_retrain)
        monkeypatch.setattr("optimization.label_pairs.sync_label_comparisons", fake_sync)

        import_lightroom_state(db, [{"path": "/lib/a.jpg", "rating": 5}], user_id="alice")

        assert calls == [("retrain", "alice", 1), ("sync", "alice")]

    def test_single_user_import_leaves_other_global_comparisons_intact(self, db, monkeypatch):
        """Guards against label_pairs.py's global DELETE getting worse under
        this importer (N8): unrelated rating-sourced comparisons for OTHER
        photos must survive an import that only changes one photo's rating.
        """
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, category, star_rating) "
            "VALUES ('/lib/c.jpg', 'c.jpg', 9.0, 'default', 5)"
        )
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES ('/lib/b.jpg', '/lib/c.jpg', 'a', 'rating')"
        )
        conn.commit()
        conn.close()

        import_lightroom_state(db, [{"path": "/lib/a.jpg", "rating": 5}])

        conn = sqlite3.connect(db)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE source = 'rating'"
        ).fetchone()[0]
        conn.close()
        # sync_label_comparisons regenerates from current labels; b/c both now
        # carry ratings so the pair is regenerated rather than lost outright.
        assert remaining >= 1

    def test_import_error_in_retrain_nudge_is_swallowed(self, db, monkeypatch):
        """An ImportError resolving api.db_helpers/optimization.label_pairs
        (or raised by either callee) must not propagate past the already-committed
        write -- mirrors api/routers/faces.py's _run_rating_sync exactly."""
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)

        def raise_import_error(*args, **kwargs):
            raise ImportError("boom")

        monkeypatch.setattr("api.db_helpers.trigger_auto_retrain", raise_import_error)
        monkeypatch.setattr("optimization.label_pairs.sync_label_comparisons", raise_import_error)

        result = import_lightroom_state(db, [{"path": "/lib/a.jpg", "rating": 5}])

        assert result.matched == 1
        assert result.changed == 1

    def test_legacy_raw_user_id_does_not_wipe_global_comparisons(self, db, monkeypatch):
        """I9.2 / F3b: a password-protected single-user viewer passes the raw
        id '_legacy' through api.auth (never None), while multi-user mode is
        OFF. `_nudge_retrain` must resolve `scope = None` in that case (from
        `per_user`, not the raw `user_id`) -- feeding '_legacy' straight to
        `sync_label_comparisons` would read an EMPTY user_preferences scope
        and delete every global rating-sourced comparison. Assert the exact
        surviving set, not merely `>= 1` (too weak to fail on this fault).
        """
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, category, star_rating) "
            "VALUES ('/lib/c.jpg', 'c.jpg', 9.0, 'default', 5)"
        )
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES ('/lib/b.jpg', '/lib/c.jpg', 'a', 'rating')"
        )
        conn.commit()
        conn.close()

        import_lightroom_state(db, [{"path": "/lib/a.jpg", "rating": 5}], user_id="_legacy")

        conn = sqlite3.connect(db)
        pairs = {frozenset(p) for p in conn.execute(
            "SELECT photo_a_path, photo_b_path FROM comparisons WHERE source = 'rating'"
        ).fetchall()}
        conn.close()
        # The b/c pair (unrelated to this import) must survive regardless of
        # what else got regenerated. Feeding the raw '_legacy' id to
        # sync_label_comparisons reads an EMPTY user_preferences scope and
        # wipes every global pair, including this one.
        assert frozenset({"/lib/b.jpg", "/lib/c.jpg"}) in pairs
