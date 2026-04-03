"""Tests for similarity group computation (api/similarity_groups.py)."""

import json
import struct
import time
from unittest import mock

import numpy as np

from api.similarity_groups import compute_similarity_groups
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

    def _make_embedding_blob(self, values):
        """Helper to pack float values into a blob."""
        return struct.pack(f"{len(values)}f", *values)

    def test_returns_cached_result(self):
        """Returns cached groups when cache is fresh."""
        cached_groups = [{"paths": ["/a.jpg", "/b.jpg"], "best_path": "/a.jpg", "count": 2}]
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "value": json.dumps(cached_groups),
            "updated_at": time.time(),  # Fresh cache
        }

        result = compute_similarity_groups(conn=mock_conn)
        assert result == cached_groups

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
