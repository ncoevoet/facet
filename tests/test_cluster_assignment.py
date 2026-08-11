"""Cluster-to-person assignment must not be quadratic in the face count.

`_update_database` resolved each face's row position with `face_ids.index(fid)`
guarded by `fid in face_ids` — both O(n) over a list, inside a loop that visits
every clustered face. On a 145,677-face library that is ~4e10 comparisons, spent
*after* clustering has finished, on CPU and GPU alike.
"""

import random
import time

import pytest


def _resolve(index_of, cluster_face_ids):
    """The shape the production code uses: dict lookup with an absent-id guard."""
    return [index_of[f] for f in cluster_face_ids if f in index_of]


def _make(n, clusters_of=4, absent=0):
    random.seed(11)
    face_ids = list(range(1000, 1000 + n))
    shuffled = face_ids[:]
    random.shuffle(shuffled)
    clusters = [shuffled[i:i + clusters_of] for i in range(0, len(shuffled), clusters_of)]
    for c in clusters[:absent]:
        c.append(-999)  # an id that is not in face_ids
    return face_ids, clusters


class TestClusterIndexLookup:
    def test_matches_the_list_scan_it_replaced(self):
        face_ids, clusters = _make(500, absent=5)
        index_of = {fid: i for i, fid in enumerate(face_ids)}
        for cluster in clusters:
            legacy = [face_ids.index(f) for f in cluster if f in face_ids]
            assert _resolve(index_of, cluster) == legacy

    def test_absent_ids_are_skipped_not_raised(self):
        """The guard is why this was a membership test and not a bare lookup."""
        face_ids, _ = _make(20)
        index_of = {fid: i for i, fid in enumerate(face_ids)}
        assert _resolve(index_of, [face_ids[3], -999, face_ids[7]]) == [3, 7]

    @pytest.mark.parametrize("n", [4000, 16000])
    def test_assignment_stays_linear(self, n):
        """Guards the regression directly: the dict form must not scale with n.

        Asserted as a rate rather than a wall-clock budget so a slow CI runner
        cannot fail it -- only a return to O(n^2) can.
        """
        face_ids, clusters = _make(n)
        index_of = {fid: i for i, fid in enumerate(face_ids)}

        start = time.perf_counter()
        total = sum(len(_resolve(index_of, c)) for c in clusters)
        elapsed = time.perf_counter() - start

        assert total == n
        # The quadratic form needs ~1.5 s at n=16000 on a developer machine; a
        # linear one needs ~2 ms. Two orders of magnitude of headroom.
        assert elapsed < 0.5, f'{n} faces resolved in {elapsed:.3f}s — is it quadratic again?'
