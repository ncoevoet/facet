"""Tests for similarity group computation (api/similarity_groups.py)."""

import json
import struct
import time
from unittest import mock

import numpy as np
import pytest

from api.similarity_groups import _split_oversized, compute_similarity_groups
from utils.embedding import bytes_to_normalized_embedding as decode_embedding


class TestDecodeEmbedding:
    """Tests for decode_embedding."""

    def test_none_input(self):
        assert decode_embedding(None) is None

    def test_empty_blob(self):
        assert decode_embedding(b"") is None

    def test_valid_embedding(self):
        values = [1.0, 2.0, 3.0, 4.0]
        blob = struct.pack(f"{len(values)}f", *values)
        result = decode_embedding(blob)

        assert result is not None
        assert result.shape == (4,)
        assert result.dtype == np.float32
        # Should be normalized to unit length
        assert abs(np.linalg.norm(result) - 1.0) < 1e-6

    def test_zero_vector_returns_none(self):
        values = [0.0, 0.0, 0.0]
        blob = struct.pack(f"{len(values)}f", *values)
        assert decode_embedding(blob) is None

    def test_single_dimension(self):
        blob = struct.pack("1f", 5.0)
        result = decode_embedding(blob)
        assert result is not None
        assert result.shape == (1,)
        assert abs(result[0] - 1.0) < 1e-6

    def test_preserves_direction(self):
        """Normalization should preserve the direction of the embedding."""
        values = [3.0, 4.0]
        blob = struct.pack("2f", *values)
        result = decode_embedding(blob)
        # Direction ratio should be preserved: 3/4
        assert abs(result[0] / result[1] - 0.75) < 1e-6


class TestComputeSimilarityGroups:
    """Tests for compute_similarity_groups."""

    @pytest.fixture(autouse=True)
    def _physical_catalog(self):
        # A MagicMock connection answers every probe, so it would look logical.
        with mock.patch("api.logical_culling.has_groups", return_value=False):
            yield

    def _make_embedding_blob(self, values):
        """Helper to pack float values into a blob."""
        return struct.pack(f"{len(values)}f", *values)

    def test_unvalidated_legacy_cache_recomputes(self):
        """A fresh pre-validation cache cannot authorize paths."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "value": json.dumps([{"paths": ["/private.jpg"], "best_path": "/private.jpg", "count": 1}]),
            "updated_at": time.time(),
        }
        mock_conn.execute.return_value.fetchall.return_value = []
        assert compute_similarity_groups(conn=mock_conn) == []

    def test_stale_cache_recomputes(self):
        """Recomputes groups when cache is stale (>1 hour)."""
        mock_conn = mock.MagicMock()
        # Stale cache
        mock_conn.execute.return_value.fetchone.return_value = {
            "value": "[]",
            "updated_at": time.time() - 7200,  # 2 hours old
        }
        # No photos
        mock_conn.execute.return_value.fetchall.return_value = []

        result = compute_similarity_groups(conn=mock_conn)
        assert result == []

    def test_empty_database(self):
        """Returns empty list when no photos have embeddings."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None  # No cache
        mock_conn.execute.return_value.fetchall.return_value = []

        result = compute_similarity_groups(conn=mock_conn)
        assert result == []

    def test_single_photo_returns_empty(self):
        """Returns empty list when only one photo exists."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None  # No cache
        mock_conn.execute.return_value.fetchall.return_value = [
            {"path": "/a.jpg", "clip_embedding": self._make_embedding_blob([1.0, 0.0]), "aggregate": 8.0},
        ]

        result = compute_similarity_groups(conn=mock_conn)
        assert result == []

    def test_similar_photos_grouped(self):
        """Photos with similar embeddings are grouped together."""
        # Two nearly identical embeddings + one different
        emb_a = self._make_embedding_blob([1.0, 0.0, 0.0])
        emb_b = self._make_embedding_blob([0.99, 0.01, 0.0])
        emb_c = self._make_embedding_blob([0.0, 0.0, 1.0])

        mock_conn = mock.MagicMock()
        # First call: cache check (fetchone) returns None
        # Second call: fetchall returns photos
        call_count = [0]
        def execute_side_effect(*args, **kwargs):
            result = mock.MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # cache check
                result.fetchone.return_value = None
            if call_count[0] == 2:
                # photo query
                result.fetchall.return_value = [
                    {"path": "/a.jpg", "clip_embedding": emb_a, "aggregate": 8.0},
                    {"path": "/b.jpg", "clip_embedding": emb_b, "aggregate": 9.0},
                    {"path": "/c.jpg", "clip_embedding": emb_c, "aggregate": 5.0},
                ]
            return result

        mock_conn.execute.side_effect = execute_side_effect

        result = compute_similarity_groups(conn=mock_conn, threshold=0.9, min_size=2)

        # a and b should be grouped (cosine sim ~0.9998), c is different
        assert len(result) == 1
        group = result[0]
        assert group["count"] == 2
        assert set(group["paths"]) == {"/a.jpg", "/b.jpg"}
        assert group["best_path"] == "/b.jpg"  # higher aggregate

    def test_threshold_filtering(self):
        """High threshold excludes moderately similar photos."""
        emb_a = self._make_embedding_blob([1.0, 0.0])
        emb_b = self._make_embedding_blob([0.7, 0.7])  # cosine sim ~0.707

        mock_conn = mock.MagicMock()
        call_count = [0]
        def execute_side_effect(*args, **kwargs):
            result = mock.MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.fetchone.return_value = None
            if call_count[0] == 2:
                result.fetchall.return_value = [
                    {"path": "/a.jpg", "clip_embedding": emb_a, "aggregate": 8.0},
                    {"path": "/b.jpg", "clip_embedding": emb_b, "aggregate": 7.0},
                ]
            return result

        mock_conn.execute.side_effect = execute_side_effect

        # High threshold: should NOT group them
        result = compute_similarity_groups(conn=mock_conn, threshold=0.95, min_size=2)
        assert len(result) == 0

    def test_min_size_filtering(self):
        """Groups smaller than min_size are excluded."""
        emb_a = self._make_embedding_blob([1.0, 0.0])
        emb_b = self._make_embedding_blob([0.99, 0.01])

        mock_conn = mock.MagicMock()
        call_count = [0]
        def execute_side_effect(*args, **kwargs):
            result = mock.MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.fetchone.return_value = None
            if call_count[0] == 2:
                result.fetchall.return_value = [
                    {"path": "/a.jpg", "clip_embedding": emb_a, "aggregate": 8.0},
                    {"path": "/b.jpg", "clip_embedding": emb_b, "aggregate": 7.0},
                ]
            return result

        mock_conn.execute.side_effect = execute_side_effect

        # min_size=3 should filter out a pair
        result = compute_similarity_groups(conn=mock_conn, threshold=0.9, min_size=3)
        assert len(result) == 0

    def test_creates_conn_when_none(self):
        """When conn=None, creates a connection and closes it."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.fetchall.return_value = []

        with mock.patch("api.similarity_groups.get_db_connection", return_value=mock_conn):
            result = compute_similarity_groups(conn=None)

        assert result == []
        mock_conn.close.assert_called_once()

    def test_groups_sorted_by_count_desc(self):
        """Result groups are sorted by count descending."""
        # 3 photos that are similar to each other, and 2 that are similar
        emb_a = self._make_embedding_blob([1.0, 0.0, 0.0])
        emb_b = self._make_embedding_blob([0.99, 0.01, 0.0])
        emb_c = self._make_embedding_blob([0.98, 0.02, 0.0])
        emb_d = self._make_embedding_blob([0.0, 1.0, 0.0])
        emb_e = self._make_embedding_blob([0.01, 0.99, 0.0])

        mock_conn = mock.MagicMock()
        call_count = [0]
        def execute_side_effect(*args, **kwargs):
            result = mock.MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                result.fetchone.return_value = None
            if call_count[0] == 2:
                result.fetchall.return_value = [
                    {"path": "/a.jpg", "clip_embedding": emb_a, "aggregate": 5.0},
                    {"path": "/b.jpg", "clip_embedding": emb_b, "aggregate": 6.0},
                    {"path": "/c.jpg", "clip_embedding": emb_c, "aggregate": 7.0},
                    {"path": "/d.jpg", "clip_embedding": emb_d, "aggregate": 8.0},
                    {"path": "/e.jpg", "clip_embedding": emb_e, "aggregate": 9.0},
                ]
            return result

        mock_conn.execute.side_effect = execute_side_effect

        result = compute_similarity_groups(conn=mock_conn, threshold=0.9, min_size=2)

        assert len(result) == 2
        # Group with 3 photos should come first
        assert result[0]["count"] == 3
        assert result[1]["count"] == 2


class TestSplitOversized:
    """A component over max_group_size used to be dropped whole, hiding every photo in it."""

    @staticmethod
    def _arc(count, degrees):
        angles = np.radians(np.arange(count) * degrees)
        return np.stack([np.cos(angles), np.sin(angles)], axis=1)

    def test_a_chain_is_cut_where_its_ends_stop_resembling_each_other(self):
        # 3 degrees apart: neighbours are ~0.9986 alike, but one end is nowhere near the other.
        matrix = self._arc(60, 3.0)
        pieces = [m for m, _ in _split_oversized(matrix, list(range(60)), 0.85, 50)]
        assert sorted(i for p in pieces for i in p) == list(range(60))
        assert all(len(p) <= 50 for p in pieces)

    def test_a_chain_no_threshold_can_cut_is_chunked_in_capture_order(self):
        # Neighbours are cos(0.1 deg) alike, above every stepped threshold.
        matrix = self._arc(120, 0.1)
        pieces = [m for m, _ in _split_oversized(matrix, list(range(120)), 0.85, 50)]
        assert [len(p) for p in pieces] == [40, 40, 40]
        assert pieces[0] == list(range(40))

    def test_a_component_within_the_limit_is_untouched(self):
        pieces = _split_oversized(self._arc(5, 1.0), list(range(5)), 0.85, 50)
        assert pieces == [([0, 1, 2, 3, 4], 0.85)]

    @staticmethod
    def _two_arcs_one_weak_link():
        # Two tight arcs (20 and 35 frames, neighbours 0.1 degree apart) whose closest
        # frames are 30.7 degrees apart: cos = 0.860, above 0.85 but below 0.87.
        angles = np.concatenate([np.arange(20) * 0.1, 1.9 + 30.7 + np.arange(35) * 0.1])
        rad = np.radians(angles)
        return np.stack([np.cos(rad), np.sin(rad)], axis=1)

    def test_a_chain_is_cut_at_its_weak_link_by_tightening(self):
        # 55 > 40 at 0.85, one component; the first tightening (0.87) breaks the
        # link. The contiguous-chunk fallback would cut 28 + 27, not 20 + 35.
        pieces = _split_oversized(self._two_arcs_one_weak_link(), list(range(55)), 0.85, 40)
        assert sorted(m for m, _ in pieces) == [list(range(20)), list(range(20, 55))]
        assert all(t == pytest.approx(0.87) for _, t in pieces)

    def test_compute_reports_the_threshold_a_split_piece_formed_at(self):
        blobs = [struct.pack("2f", *row) for row in self._two_arcs_one_weak_link()]
        rows = [{"path": f"/{i:03}.jpg", "clip_embedding": b, "aggregate": 5.0} for i, b in enumerate(blobs)]
        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        conn.execute.return_value.fetchall.return_value = rows
        with mock.patch("api.logical_culling.has_groups", return_value=False), \
                mock.patch("api.similarity_groups._get_similarity_config", return_value={
                    'default_threshold': 0.85, 'min_group_size': 2, 'max_photos': 10000, 'max_group_size': 40}):
            groups = compute_similarity_groups(conn=conn, threshold=0.85, min_size=2, use_cache=False)
        assert sorted(g["count"] for g in groups) == [20, 35]
        assert all(g["threshold"] == pytest.approx(0.87) for g in groups)

    def test_compute_keeps_an_oversized_scene_instead_of_dropping_it(self):
        blobs = [struct.pack("2f", *row) for row in self._arc(120, 0.1)]
        rows = [{"path": f"/{i:03}.jpg", "clip_embedding": b, "aggregate": 5.0} for i, b in enumerate(blobs)]
        conn = mock.MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        conn.execute.return_value.fetchall.return_value = rows
        with mock.patch("api.logical_culling.has_groups", return_value=False):
            groups = compute_similarity_groups(conn=conn, threshold=0.85, min_size=2, use_cache=False)
        assert sum(g["count"] for g in groups) == 120
        assert max(g["count"] for g in groups) <= 50
