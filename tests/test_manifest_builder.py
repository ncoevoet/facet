"""Tests for processing/xmp_export.build_manifest and db/sequence_overrides.count_pending_groups.

Step 1 (shared manifest builder) + Step 8 (pending-corrections count) of the
Lightroom-flow spec. The real viewer route (Step 10, ``GET
/api/lightroom/manifest``) lands in a later wave; until then this compares
``build_manifest`` directly against the CLI's own ``--export-manifest``
subprocess output, which is the next-best thing to the route comparison the
spec's Step 1 verify calls for.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from config.scoring_config import ScoringConfig
from db.schema import init_database
from db.sequence_overrides import count_pending_groups
from processing.xmp_export import build_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PY = REPO_ROOT / 'venv' / 'bin' / 'python'
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
FACET = str(REPO_ROOT / 'facet.py')


def _seed(db_path, path, **overrides):
    row = {
        'path': path, 'filename': Path(path).name, 'aggregate': 7.0,
        'category': 'default', 'star_rating': 0, 'is_favorite': 0,
        'is_rejected': 0, 'is_burst_lead': 0,
    }
    row.update(overrides)
    conn = sqlite3.connect(db_path)
    cols = list(row.keys())
    conn.execute(
        f"INSERT INTO photos ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [row[c] for c in cols],
    )
    conn.commit()
    conn.close()


class TestBuildManifestMatchesCli:
    def test_viewer_style_call_and_cli_produce_the_same_photos(self, tmp_path):
        db_path = str(tmp_path / 'm.db')
        init_database(db_path)
        _seed(db_path, str(tmp_path / 'a.jpg'), aggregate=8.5, star_rating=4, is_favorite=1)
        _seed(db_path, str(tmp_path / 'b.jpg'), aggregate=3.0, is_rejected=1)

        cli_result = subprocess.run(
            [PY, FACET, '--db', db_path, '--export-manifest'],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert cli_result.returncode == 0, cli_result.stderr
        cli_manifest = json.loads((tmp_path / 'facet_manifest.json').read_text())

        # Viewer-style call (I1): pass the RAW xmp_export.score_to_rating
        # block exactly as api/routers/lightroom.py does -- unmodified, on
        # the shipped default where `enabled` is False. The forcing must live
        # inside build_manifest itself; if a caller had to remember to force
        # it (as this test used to, which made it a tautology V1 rejected),
        # this assertion would see score_stars == 0 while the CLI reports the
        # real star mapping.
        sr_cfg = dict(ScoringConfig(None, validate=False).config
                      .get('xmp_export', {}).get('score_to_rating', {}))
        assert not sr_cfg.get('enabled')  # shipped default -- not pre-forced by this test
        direct_manifest = build_manifest(db_path, score_to_rating=sr_cfg)

        cli_manifest.pop('generated_at')
        direct_manifest.pop('generated_at')
        assert cli_manifest == direct_manifest
        assert any(p['score_stars'] > 0 for p in direct_manifest['photos'])

    def test_paths_scope_narrows_to_the_given_list(self, tmp_path):
        db_path = str(tmp_path / 'm.db')
        init_database(db_path)
        a, b = str(tmp_path / 'a.jpg'), str(tmp_path / 'b.jpg')
        _seed(db_path, a)
        _seed(db_path, b)

        manifest = build_manifest(db_path, paths=[a])

        assert {p['path'] for p in manifest['photos']} == {a}

    def test_empty_paths_list_yields_no_photos(self, tmp_path):
        db_path = str(tmp_path / 'm.db')
        init_database(db_path)
        _seed(db_path, str(tmp_path / 'a.jpg'))

        manifest = build_manifest(db_path, paths=[])

        assert manifest['photos'] == []

    def test_paths_scope_chunks_the_in_list_and_preserves_aggregate_order(
        self, tmp_path, monkeypatch,
    ):
        """Build_manifest's own `paths` IN-query must be chunked
        (an unchunked IN list fails past SQLite's variable limit on a large
        whole-view manifest), and the per-chunk results must be merged back
        into the same `aggregate DESC` order a single unchunked query gives --
        shrink the chunk size so a handful of paths already crosses more than
        one chunk boundary."""
        import processing.xmp_export as xmp_export_module
        monkeypatch.setattr(xmp_export_module, '_MANIFEST_PATH_CHUNK', 2)

        db_path = str(tmp_path / 'chunk.db')
        init_database(db_path)
        paths = []
        for i in range(5):
            p = str(tmp_path / f'p{i}.jpg')
            # Deliberately seeded out of aggregate order.
            _seed(db_path, p, aggregate=float(i))
            paths.append(p)
        # A NULL aggregate must sort LAST, matching SQLite's own
        # ``ORDER BY aggregate DESC`` (NULLs last), not first as a naive
        # ``-(aggregate or 0)`` sort key would put it alongside a real 0.0.
        null_path = str(tmp_path / 'p_null.jpg')
        _seed(db_path, null_path, aggregate=None)
        expected_order = list(reversed(paths)) + [null_path]
        paths.append(null_path)

        manifest = build_manifest(db_path, paths=list(reversed(paths)))

        assert [p['path'] for p in manifest['photos']] == expected_order


class TestPendingCorrectionsCount:
    def _seed_overrides(self, db_path, rows):
        conn = sqlite3.connect(db_path)
        for path, kind, group_key in rows:
            conn.execute(
                "INSERT INTO photo_sequence_overrides "
                "(photo_path, sequence_kind, override_group_key, source, applied_at) "
                "VALUES (?, ?, ?, 'user', NULL)",
                (path, kind, group_key),
            )
        conn.commit()
        conn.close()

    def test_counts_groups_not_rows(self, tmp_path):
        db_path = str(tmp_path / 'p.db')
        init_database(db_path)
        self._seed_overrides(db_path, [
            (str(tmp_path / 'g1_a.jpg'), 'bracket', 'group-1'),
            (str(tmp_path / 'g1_b.jpg'), 'bracket', 'group-1'),
            (str(tmp_path / 'g1_c.jpg'), 'bracket', 'group-1'),
            (str(tmp_path / 'ungrouped.jpg'), None, None),
        ])

        assert count_pending_groups(conn=sqlite3.connect(db_path)) == 2

    def test_applied_rows_are_excluded(self, tmp_path):
        db_path = str(tmp_path / 'p2.db')
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source, applied_at) "
            "VALUES (?, 'bracket', 'g1', 'user', '2026-01-01T00:00:00Z')",
            (str(tmp_path / 'done.jpg'),),
        )
        conn.commit()
        conn.close()

        assert count_pending_groups(conn=sqlite3.connect(db_path)) == 0

    def test_root_scope_excludes_applied_and_other_root_groups(self, tmp_path):
        """I2: the AND/OR precedence bug spliced `root`'s `path = ? OR path
        LIKE ?` onto `applied_at IS NULL AND override_group_key IS NOT NULL`
        without parentheses, so the LIKE branch dropped both predicates and
        counted applied + grouped rows from under root too."""
        db_path = str(tmp_path / 'p4.db')
        init_database(db_path)
        lib_a = str(tmp_path / 'lib_a')
        self._seed_overrides(db_path, [
            # 3-row pending group under /lib_a -- should count as 1.
            (f"{lib_a}/g1.jpg", 'bracket', 'g1'),
            (f"{lib_a}/g2.jpg", 'bracket', 'g1'),
            (f"{lib_a}/g3.jpg", 'bracket', 'g1'),
        ])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source, applied_at) "
            "VALUES (?, 'bracket', 'g2', 'user', '2026-01-01T00:00:00Z')",
            (f"{lib_a}/applied1.jpg",),
        )
        conn.execute(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source, applied_at) "
            "VALUES (?, 'bracket', 'g2', 'user', '2026-01-01T00:00:00Z')",
            (f"{lib_a}/applied2.jpg",),
        )
        conn.commit()
        conn.close()
        self._seed_overrides(db_path, [
            (str(tmp_path / 'elsewhere' / 'g3.jpg'), 'panorama', 'g3'),
        ])

        conn = sqlite3.connect(db_path)
        assert count_pending_groups(root=lib_a, conn=conn) == 1
        assert count_pending_groups(conn=sqlite3.connect(db_path)) == 2
        conn.close()

    def test_paths_scope_only_counts_the_given_selection(self, tmp_path):
        """I3: the viewer manifest's pending_corrections must be scoped to
        the resolved selection, not library-wide."""
        db_path = str(tmp_path / 'p5.db')
        init_database(db_path)
        a = str(tmp_path / 'a.jpg')
        _seed(db_path, a)
        self._seed_overrides(db_path, [
            (str(tmp_path / 'elsewhere' / 'z.jpg'), 'panorama', 'g1'),
        ])

        manifest = build_manifest(db_path, paths=[a])

        assert manifest['pending_corrections'] == 0

    def test_manifest_carries_pending_corrections_field(self, tmp_path):
        db_path = str(tmp_path / 'p3.db')
        init_database(db_path)
        _seed(db_path, str(tmp_path / 'a.jpg'))
        self._seed_overrides(db_path, [
            (str(tmp_path / 'g1_a.jpg'), 'bracket', 'group-1'),
            (str(tmp_path / 'g1_b.jpg'), 'bracket', 'group-1'),
            (str(tmp_path / 'ungrouped.jpg'), None, None),
        ])

        manifest = build_manifest(db_path)

        assert manifest['pending_corrections'] == 2


class TestExportManifestCliWarning:
    def test_stdout_warns_when_pending_corrections_exist(self, tmp_path):
        db_path = str(tmp_path / 'w.db')
        init_database(db_path)
        _seed(db_path, str(tmp_path / 'a.jpg'))
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source, applied_at) "
            "VALUES (?, 'bracket', 'g1', 'user', NULL)",
            (str(tmp_path / 'b.jpg'),),
        )
        conn.commit()
        conn.close()

        result = subprocess.run(
            [PY, FACET, '--db', db_path, '--export-manifest'],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert 'pending sequence correction' in result.stdout

    def test_no_warning_when_nothing_pending(self, tmp_path):
        db_path = str(tmp_path / 'w2.db')
        init_database(db_path)
        _seed(db_path, str(tmp_path / 'a.jpg'))

        result = subprocess.run(
            [PY, FACET, '--db', db_path, '--export-manifest'],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert 'pending sequence correction' not in result.stdout
