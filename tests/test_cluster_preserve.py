"""Re-clustering must not orphan the people a user has already named.

`--cluster-faces-incremental` clears every face->person assignment and rebuilds
it, re-attaching a cluster to a person only when the cluster's mean embedding is
within `merge_threshold` of that person's single stored centroid.

That rule fails exactly where curation matters most. A person represented by one
averaged vector but photographed over years spans a broad region; HDBSCAN splits
them into tight sub-clusters that each sit far from the mean, so each one fails
the threshold and becomes a new anonymous person. Measured on a 145,677-face
library: named people kept 48% of their faces overall, the largest kept 4-19%,
while small visually-consistent ones kept over 90%.
"""

import numpy as np
import pytest

from faces.clusterer import FaceClusterer


@pytest.fixture
def clusterer(tmp_path):
    return FaceClusterer(str(tmp_path / "faces.db"))


class TestPreviousOwnerByMajority:
    def test_hands_a_cluster_back_to_its_previous_owner(self, clusterer):
        preserved = {1: 42, 2: 42, 3: 42, 4: 99}
        assert clusterer._previous_owner_by_majority([1, 2, 3, 4], preserved) == 42

    def test_exactly_half_is_enough(self, clusterer):
        """PRESERVED_MAJORITY is 0.5 inclusive: a tie with unknowns still resolves."""
        preserved = {1: 42, 2: 42}
        assert clusterer._previous_owner_by_majority([1, 2, 3, 4], preserved) == 42

    def test_a_genuinely_mixed_cluster_is_left_to_the_centroid_rule(self, clusterer):
        """Two people evenly split: neither reaches a majority, so answer nothing
        rather than hand the cluster to whoever contributed one face more."""
        preserved = {1: 42, 2: 42, 3: 99, 4: 99, 5: 99}
        assert clusterer._previous_owner_by_majority([1, 2, 3, 4, 5], preserved) == 99
        preserved = {1: 42, 2: 99, 3: 7}
        assert clusterer._previous_owner_by_majority([1, 2, 3], preserved) is None

    def test_all_new_faces_answer_nothing(self, clusterer):
        assert clusterer._previous_owner_by_majority([1, 2, 3], {}) is None

    def test_faces_with_no_previous_owner_do_not_count_toward_the_majority(self, clusterer):
        """One known owner out of five is not a majority, even though it is the
        only vote cast."""
        assert clusterer._previous_owner_by_majority([1, 2, 3, 4, 5], {1: 42}) is None


class TestTheRegressionItFixes:
    """The shape that lost 25,580 faces: a broad person split into sub-clusters."""

    @staticmethod
    def _centroid(vectors):
        c = np.mean(vectors, axis=0)
        return c / (np.linalg.norm(c) + 1e-10)

    def test_subclusters_of_a_broad_person_fail_the_centroid_rule(self):
        """Establishes the premise: this is why the fallback is needed at all."""
        rng = np.random.default_rng(11)
        dim, merge_threshold = 64, 0.6

        # A person photographed across three eras: three tight lobes, far apart.
        lobes = []
        for _ in range(3):
            axis = rng.normal(size=dim)
            axis /= np.linalg.norm(axis)
            lobe = axis + rng.normal(scale=0.02, size=(40, dim))
            lobes.append(lobe / np.linalg.norm(lobe, axis=1, keepdims=True))

        person_centroid = self._centroid(np.vstack(lobes))
        similarities = [float(np.dot(self._centroid(lobe), person_centroid)) for lobe in lobes]

        assert all(s < merge_threshold for s in similarities), (
            f'expected every sub-cluster to fail the {merge_threshold} threshold, got {similarities}')

    def test_history_recovers_what_the_centroid_rule_orphans(self, clusterer):
        """Same three lobes, now with the previous assignment available."""
        person_id = 42
        preserved = {face_id: person_id for face_id in range(120)}

        for lobe_start in (0, 40, 80):
            cluster = list(range(lobe_start, lobe_start + 40))
            assert clusterer._previous_owner_by_majority(cluster, preserved) == person_id
