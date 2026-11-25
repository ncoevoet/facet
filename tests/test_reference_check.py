"""Reference-set regression check (issue #393): synthetic DBs only, no facet scan, no GPU.

Every DB is built with ``db.schema.init_database`` (never a hand-rolled CREATE TABLE); the
photo rows carry fake BLOBs so an export that leaked one would show up.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

TESTDB = Path(__file__).resolve().parent.parent / "testdb"
if str(TESTDB) not in sys.path:
    sys.path.insert(0, str(TESTDB))

import check_reference as cr  # noqa: E402
import reference_common as rc  # noqa: E402
from db.schema import PHOTOS_COLUMNS, init_database  # noqa: E402

N = 12
FACE_IDS = ["p00", "p01", "p02", "p03"]
BRACKET_A = ["p04", "p05", "p06"]
BRACKET_B = ["p07", "p08", "p09"]
LANDSCAPE = [f"p{i:02d}" for i in range(4, N)]
TOLERANCES = {
    "profile": "16gb",
    "score_abs": {"_default": 0.05},
    "srcc_min": {"aggregate": 0.9},
    "tag_jaccard_min": 0.5,
    "category_flips_max": {"_default": 0},
    "face_count_change_max": 0,
    "assignment_changes_max": {"_default": 0},
    "bbox_iou_min": 0.9,
    "label": {"min_pairs": 10, "pair_agreement_margin": 0, "confusion_errors_margin": 0},
}


def case_of(pid):
    if pid in FACE_IDS:
        return ["face-tiny"]
    cases = ["landscape"]
    if pid in BRACKET_A + BRACKET_B:
        cases.append("seq-bracket3")
    return cases


def make_manifest():
    photos = []
    for i in range(N):
        pid = f"p{i:02d}"
        face = pid in FACE_IDS
        photos.append({
            "id": pid, "path": f"cat/{pid}.jpg", "url": "https://example.org/x", "sha256": f"{i:064x}",
            "bytes": 100 + i, "kind": "download", "derived_from": None, "recipe": None,
            "pixel_sha256": None, "format": "jpeg", "megapixels": 1.0, "companion_of": None,
            "scored": True, "cases": case_of(pid),
            "expected_category": "portrait" if face else "landscape",
            "acceptable_categories": ["portrait"] if face else ["landscape", "architecture"],
        })
    landscape = [p for p in photos if p["expected_category"] == "landscape"]
    pairs = [
        {"better": landscape[j]["id"], "worse": landscape[i]["id"], "category": "landscape",
         "defect": "noise"}
        for i in range(len(landscape)) for j in range(i + 1, len(landscape))
    ][:10]
    cases = {c: {"group": "category", "known_gap": None} for c in ("face-tiny", "landscape", "seq-bracket3")}
    cases["raw-pef"] = {"group": "files", "known_gap": "no sample"}
    return {"schema_version": 1, "cases": cases, "photos": photos, "pairs": pairs, "known_gaps": []}


def base_row(i, set_dir):
    pid = f"p{i:02d}"
    face = pid in FACE_IDS
    return {
        "path": str(Path(set_dir) / "photos" / "cat" / f"{pid}.jpg"),
        "filename": f"{pid}.jpg",
        "aggregate": 4.0 + i * 0.4, "aesthetic": 3.0 + i * 0.3, "topiq_score": 5.0 + i * 0.1,
        "face_ratio": None if not face else 0.01,
        "face_count": 1 if face else 0,
        "category": "portrait" if face else "landscape",
        "tags": "b,a" if not face else "face,a",
        "caption": f"caption {pid}",
        "composition_pattern": "rule_of_thirds",
        "subject_bbox": "[0.1, 0.1, 0.6, 0.6]",
        "thumbnail": b"\xff" * 64, "clip_embedding": b"\x02" * 32, "histogram_data": b"\x03" * 16,
        "caption_embedding": b"\x04" * 16,
        "junk_kind": "not_junk", "narrative_moment": None,
        "is_burst_lead": 0, "is_sequence_lead": 0, "is_duplicate_lead": 0,
    }


FACE_BBOX = (10, 10, 50, 50)


def build_db(tmp_path, name, set_dir, edit=None, brackets=None):
    """A scan DB for the synthetic set; ``edit(rows, faces)`` mutates it before insertion."""
    db = tmp_path / name
    init_database(str(db), build_photo_indexes=False)
    rows = [base_row(i, set_dir) for i in range(N)]
    brackets = brackets or {1: BRACKET_A, 2: BRACKET_B}
    for group, members in brackets.items():
        for pid in members:
            row = rows[int(pid[1:])]
            row.update(sequence_kind="bracket", sequence_group_id=group, sequence_ev_offset=0.0)
    faces = {pid: [FACE_BBOX] for pid in FACE_IDS}
    if edit:
        edit(rows, faces)
    conn = sqlite3.connect(db)
    for row in rows:
        keys = list(row)
        conn.execute(f"INSERT INTO photos ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                     [row[k] for k in keys])
    for pid, boxes in faces.items():
        path = rows[int(pid[1:])]["path"]
        for index, box in enumerate(boxes):
            conn.execute(
                "INSERT INTO faces (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (path, index, b"\x05" * 8, *box, 0.9))
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def world(tmp_path):
    set_dir = tmp_path / "set"
    manifest = make_manifest()
    for photo in manifest["photos"]:
        target = set_dir / "photos" / photo["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), "utf8")
    golden_path = tmp_path / "golden.json"
    tol_path = tmp_path / "tol.json"
    tol_path.write_text(json.dumps(TOLERANCES), "utf8")
    golden_db = build_db(tmp_path, "golden.db", set_dir)
    return {"tmp": tmp_path, "set": set_dir, "manifest": manifest, "manifest_path": manifest_path,
            "golden": golden_path, "tol": tol_path, "golden_db": golden_db}


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    """The environment block needs torch and git; the logic under test does not."""
    monkeypatch.setattr(cr, "collect_environment", lambda *a, **k: {"recorded_at": "2026-11-25"})


def record(world):
    cr.main(["record", "--profile", "16gb", "--set-dir", str(world["set"]), "--manifest", str(world["manifest_path"]),
             "--db", str(world["golden_db"]), "--out", str(world["golden"])])


def run_check(world, db, *extra, tolerances=True, command="check"):
    argv = [command, "--profile", "16gb", "--set-dir", str(world["set"]), "--manifest",
            str(world["manifest_path"]), "--db", str(db), "--golden", str(world["golden"])]
    if tolerances and command == "check":
        argv += ["--tolerances", str(world["tol"])]
    return cr.main(argv + list(extra))


def report_of(world, db, tolerances=TOLERANCES):
    manifest = world["manifest"]
    golden = json.loads(world["golden"].read_text("utf8"))
    current = cr.build_golden(db, world["set"], manifest, "16gb", {})
    return cr.compare(golden, current, manifest, tolerances)


def find(report, case, metric_prefix):
    return [v for v in report["violations"] if v["case"] == case and v["metric"].startswith(metric_prefix)]


@pytest.fixture
def recorded(world):
    record(world)
    return world


# --------------------------------------------------------------------------- export

def test_score_columns_exclude_blobs_and_excluded_names():
    blobs = {name for name, decl in PHOTOS_COLUMNS if decl.startswith("BLOB")}
    names = {name for name, _ in PHOTOS_COLUMNS}
    assert not blobs & set(cr.SCORE_COLUMNS)
    assert not cr.EXCLUDED_REAL & set(cr.SCORE_COLUMNS)
    assert cr.EXCLUDED_REAL <= names
    assert "aggregate" in cr.SCORE_COLUMNS and "deqa_score" in cr.SCORE_COLUMNS


def test_export_has_no_blobs_and_null_stays_null(recorded):
    text = recorded["golden"].read_text("utf8")
    golden = json.loads(text)
    for forbidden in ("thumbnail", "embedding", "histogram_data", "face_thumbnail", "\\xff"):
        assert forbidden not in text
    p05, p00 = golden["photos"]["p05"], golden["photos"]["p00"]
    assert p05["scores"]["face_ratio"] is None
    assert p05["scores"]["deqa_score"] is None
    assert p05["narrative_moment"] is None
    assert p05["junk_kind"] == "not_junk"
    assert p00["faces"] == [{"bbox": list(FACE_BBOX), "confidence": 0.9}]
    assert p05["tags"] == ["a", "b"]
    assert golden["manifest_sha256"] == rc.file_level_digest(recorded["manifest"])
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert str(recorded["set"]) not in text


def test_golden_write_is_deterministic_and_rounded():
    data = {"b": 1.123456789, "a": [0.00004, {"z": 2, "y": None}]}
    first = cr.dump_json(data)
    assert first == cr.dump_json(json.loads(first))
    assert '"b": 1.1235' in first and first.index('"a"') < first.index('"b"')


def test_sets_are_keyed_by_smallest_member_not_raw_group_id(recorded):
    golden = json.loads(recorded["golden"].read_text("utf8"))
    assert golden["sets"]["sequence"] == [
        {"kind": "bracket", "label": "p04", "members": BRACKET_A},
        {"kind": "bracket", "label": "p07", "members": BRACKET_B},
    ]
    assert golden["photos"]["p05"]["sequence"]["group"] == "p04"


def test_relative_path_handles_backslashes_and_case():
    assert cr.relative_path("D:\\Set\\Photos\\cat\\a.jpg", "d:/set") == "cat/a.jpg"
    assert cr.relative_path("D:\\elsewhere\\a.jpg", "d:/set") is None


# --------------------------------------------------------------------------- diff engine

def test_perturb_nothing_exits_zero(recorded):
    same = build_db(recorded["tmp"], "same.db", recorded["set"])
    assert run_check(recorded, same) == 0
    assert report_of(recorded, same)["violations"] == []


def test_renumbered_groups_are_not_a_change(recorded):
    renumbered = build_db(recorded["tmp"], "renum.db", recorded["set"], brackets={9: BRACKET_B, 3: BRACKET_A})
    assert run_check(recorded, renumbered) == 0


def test_score_perturbation_is_reported_under_its_cases(recorded):
    def edit(rows, faces):
        rows[5]["aggregate"] += 0.2
    report = report_of(recorded, build_db(recorded["tmp"], "s.db", recorded["set"], edit))
    for case in ("seq-bracket3", "landscape", cr.OVERALL):
        hit = find(report, case, "score_abs:aggregate")
        assert [v["photo"] for v in hit] == ["p05"]
    assert not find(report, "face-tiny", "score_abs")
    assert report["most_moved"][0]["photo"] == "p05"


def test_category_flip_is_reported(recorded):
    def edit(rows, faces):
        rows[10]["category"] = "architecture"
    db = build_db(recorded["tmp"], "f.db", recorded["set"], edit)
    report = report_of(recorded, db)
    assert find(report, "landscape", "category_flips")[0]["value"] == 1
    assert not find(report, "face-tiny", "category_flips")
    assert report["labels"]["outside_accepted"] == []  # architecture is acceptable for landscape
    assert run_check(recorded, db) == 1


def test_dropped_face_is_reported_under_face_tiny(recorded, capsys):
    def edit(rows, faces):
        rows[0]["face_count"] = 0
        faces["p00"] = []
    db = build_db(recorded["tmp"], "d.db", recorded["set"], edit)
    report = report_of(recorded, db)
    assert [v["photo"] for v in find(report, "face-tiny", "face_count")] == ["p00"]
    assert report["cases"]["face-tiny"]["faces_lost_photos"] == 1
    run_check(recorded, db)
    assert "face-tiny: 1 of 4 lost a face" in capsys.readouterr().out


def test_moved_bbox_is_reported_by_iou(recorded):
    def edit(rows, faces):
        faces["p01"] = [(30, 30, 70, 70)]
    report = report_of(recorded, build_db(recorded["tmp"], "b.db", recorded["set"], edit))
    assert [v["photo"] for v in find(report, "face-tiny", "face_bbox_iou")] == ["p01"]
    assert not find(report, "face-tiny", "face_count")


def test_photo_moved_between_bracket_sets(recorded):
    db = build_db(recorded["tmp"], "m.db", recorded["set"],
                  brackets={1: ["p04", "p05"], 2: ["p06", *BRACKET_B]})
    report = report_of(recorded, db)
    hit = find(report, "seq-bracket3", "assignment:sequence")
    assert hit and hit[0]["value"] == 6
    assert not find(report, "face-tiny", "assignment")
    assert run_check(recorded, db) == 1


def test_minority_case_regression_fails_although_overall_srcc_is_fine(recorded):
    def edit(rows, faces):
        rows[2]["face_count"] = 0
        faces["p02"] = []
    db = build_db(recorded["tmp"], "minority.db", recorded["set"], edit)
    report = report_of(recorded, db)
    assert report["srcc"]["aggregate"] == pytest.approx(1.0)
    assert not find(report, cr.OVERALL, "srcc")
    assert find(report, "face-tiny", "face_count")
    assert run_check(recorded, db) == 1


def test_report_only_never_exits_one(recorded):
    def edit(rows, faces):
        rows[2]["face_count"] = 0
        faces["p02"] = []
    db = build_db(recorded["tmp"], "ro.db", recorded["set"], edit)
    assert run_check(recorded, db, tolerances=False) == 0
    assert run_check(recorded, db, "--report-only") == 0
    assert report_of(recorded, db, tolerances=None)["violations"] == []


def test_report_sections_and_json(recorded, capsys):
    db = build_db(recorded["tmp"], "r.db", recorded["set"])
    out_json = recorded["tmp"] / "report.json"
    assert run_check(recorded, db, "--json", str(out_json)) == 0
    text = capsys.readouterr().out
    for heading in ("(1) overall", "(2) per case", "(3) top", "(4) category confusion",
                    "(5) pairwise agreement", "(6) sequence", "NOT CHECKED"):
        assert heading in text
    assert "known gap case: raw-pef" in text
    assert "pairs-portrait: no pairs (LOW-CONFIDENCE)" in text
    assert json.loads(out_json.read_text("utf8"))["photos"] == N


# --------------------------------------------------------------------------- labels

def test_label_metrics_confusion_outside_and_pairs(recorded):
    def edit(rows, faces):
        rows[11]["category"] = "street"
    report = report_of(recorded, build_db(recorded["tmp"], "l.db", recorded["set"], edit))
    labels = report["labels"]
    assert labels["confusion"]["landscape"] == {"landscape": 7, "street": 1}
    assert labels["outside_accepted"] == [{"id": "p11", "expected": "landscape", "got": "street"}]
    assert labels["agreement"]["landscape"]["pairs"] == 10
    assert not labels["agreement"]["landscape"]["low_confidence"]
    assert find(report, "landscape", "confusion_errors")


def test_pair_agreement_drop_is_a_violation_and_few_pairs_are_not_checked(recorded):
    def edit(rows, faces):
        rows[4]["aggregate"] = 9.5
    report = report_of(recorded, build_db(recorded["tmp"], "pa.db", recorded["set"], edit))
    assert find(report, "landscape", "pair_agreement")
    assert report["labels"]["agreement"]["landscape"]["flipped"]
    trimmed = dict(recorded["manifest"], pairs=recorded["manifest"]["pairs"][:3])
    golden = json.loads(recorded["golden"].read_text("utf8"))
    current = cr.build_golden(build_db(recorded["tmp"], "pb.db", recorded["set"]), recorded["set"], trimmed, "16gb", {})
    short = cr.compare(golden, current, trimmed, TOLERANCES)
    assert short["labels"]["agreement"]["landscape"]["low_confidence"]
    assert any("pairs-landscape: 3 pair(s)" in line for line in short["labels"]["not_checked"])
    assert not find(short, "landscape", "pair_agreement")


# --------------------------------------------------------------------------- setup errors

def test_digest_mismatch_exits_two(recorded, capsys):
    manifest = recorded["manifest"]
    manifest["photos"][0]["sha256"] = "f" * 64
    recorded["manifest_path"].write_text(json.dumps(manifest), "utf8")
    db = build_db(recorded["tmp"], "dg.db", recorded["set"])
    assert run_check(recorded, db) == 2
    assert "manifest digest" in capsys.readouterr().err


def test_label_edit_does_not_change_the_digest(recorded):
    manifest = recorded["manifest"]
    manifest["photos"][0]["expected_category"] = "art"
    manifest["pairs"] = []
    recorded["manifest_path"].write_text(json.dumps(manifest), "utf8")
    assert run_check(recorded, build_db(recorded["tmp"], "lb.db", recorded["set"])) == 0


def test_foreign_path_exits_two(recorded, capsys):
    def edit(rows, faces):
        extra = dict(base_row(0, "/elsewhere"))
        extra["path"] = "/elsewhere/photos/cat/stranger.jpg"
        rows.append(extra)
    db = build_db(recorded["tmp"], "foreign.db", recorded["set"], edit)
    assert run_check(recorded, db) == 2
    assert "outside" in capsys.readouterr().err


def test_missing_set_file_exits_two(recorded, capsys):
    (recorded["set"] / "photos" / "cat" / "p03.jpg").unlink()
    assert run_check(recorded, build_db(recorded["tmp"], "mf.db", recorded["set"])) == 2
    assert "set file missing" in capsys.readouterr().err


def test_db_missing_a_photo_exits_two(recorded):
    def edit(rows, faces):
        rows.pop()
    assert run_check(recorded, build_db(recorded["tmp"], "short.db", recorded["set"], edit)) == 2


def test_failed_scan_pass_exits_two(recorded, capsys):
    db = build_db(recorded["tmp"], "fp.db", recorded["set"])
    cr.passes_path(db).write_text(json.dumps({"passes": [{"name": "detect-moments", "exit_code": 1}]}), "utf8")
    assert run_check(recorded, db) == 2
    assert "detect-moments (exit 1)" in capsys.readouterr().err


def test_default_db_is_refused(recorded, monkeypatch, capsys):
    db = build_db(recorded["tmp"], "default.db", recorded["set"])
    monkeypatch.setenv("DB_PATH", str(db))
    assert run_check(recorded, db) == 2
    assert "default/production" in capsys.readouterr().err


def test_production_db_name_is_refused(recorded, tmp_path):
    db = build_db(tmp_path, "photo_scores_pro.db", recorded["set"])
    assert run_check(recorded, db) == 2
    with pytest.raises(cr.SetupError):
        cr.refuse_protected_db(db)


# --------------------------------------------------------------------------- update

def test_update_refuses_above_twenty_percent_without_yes(recorded, capsys):
    def edit(rows, faces):
        for row in rows[:6]:
            row["aggregate"] += 1.0
    db = build_db(recorded["tmp"], "u.db", recorded["set"], edit)
    before = recorded["golden"].read_text("utf8")
    assert run_check(recorded, db, command="update") == 1
    assert recorded["golden"].read_text("utf8") == before
    assert "pass --yes" in capsys.readouterr().out
    assert run_check(recorded, db, "--yes", command="update") == 0
    assert recorded["golden"].read_text("utf8") != before
    assert run_check(recorded, db) == 0


def test_update_small_change_needs_no_yes_and_needs_an_existing_golden(recorded):
    def edit(rows, faces):
        rows[8]["aggregate"] += 1.0
    db = build_db(recorded["tmp"], "u2.db", recorded["set"], edit)
    assert run_check(recorded, db, command="update") == 0
    recorded["golden"].unlink()
    assert run_check(recorded, db, command="update") == 2


# --------------------------------------------------------------------------- tolerances

def test_tolerances_floors_and_holdout(recorded, capsys):
    set_dir, tmp = recorded["set"], recorded["tmp"]
    run_a = build_db(tmp, "ra.db", set_dir)
    run_b = build_db(tmp, "rb.db", set_dir)
    out = tmp / "derived.json"
    base = ["tolerances", "--profile", "16gb", "--set-dir", str(set_dir), "--manifest",
            str(recorded["manifest_path"]), "--runs", str(run_a), str(run_b), "--out", str(out)]
    assert cr.main(base) == 0
    derived = json.loads(out.read_text("utf8"))
    assert derived["score_abs"]["aggregate"] == cr.SCORE_FLOOR == derived["score_abs"]["_default"]
    assert derived["srcc_min"]["aggregate"] == pytest.approx(1.0 - cr.SRCC_MARGIN)
    assert derived["tag_jaccard_min"] == pytest.approx(1.0 - cr.JACCARD_MARGIN)
    assert derived["bbox_iou_min"] == pytest.approx(1.0 - cr.IOU_MARGIN)
    assert derived["category_flips_max"]["_default"] == 0 and derived["face_count_change_max"] == 0
    assert cr.main(base + ["--holdout", str(build_db(tmp, "rc.db", set_dir))]) == 0
    assert "HOLD-OUT PASS" in capsys.readouterr().out

    def edit(rows, faces):
        rows[7]["aggregate"] += 0.5
    assert cr.main(base + ["--holdout", str(build_db(tmp, "rd.db", set_dir, edit))]) == 1
    assert "HOLD-OUT FAIL" in capsys.readouterr().out


def test_tolerances_widen_to_observed_noise(recorded):
    def edit(rows, faces):
        rows[7]["aggregate"] += 0.3
    manifest = recorded["manifest"]
    exports = [cr.build_golden(build_db(recorded["tmp"], "na.db", recorded["set"]), recorded["set"], manifest, "16gb", {}),
               cr.build_golden(build_db(recorded["tmp"], "nb.db", recorded["set"], edit), recorded["set"], manifest, "16gb", {})]
    derived = cr.derive_tolerances(exports, manifest, "16gb")
    assert derived["score_abs"]["aggregate"] == pytest.approx(3 * 0.3 / 2 ** 0.5, abs=1e-3)
    assert derived["score_abs"]["topiq_score"] == cr.SCORE_FLOOR
    with pytest.raises(cr.SetupError):
        cr.derive_tolerances(exports[:1], manifest, "16gb")


def test_tolerances_default_to_the_per_profile_path(recorded, monkeypatch):
    set_dir, tmp = recorded["set"], recorded["tmp"]
    monkeypatch.setattr(cr, "TOLERANCES_DIR", tmp / "tols")
    runs = [str(build_db(tmp, "da.db", set_dir)), str(build_db(tmp, "db.db", set_dir))]
    base = ["--profile", "16gb", "--set-dir", str(set_dir), "--manifest", str(recorded["manifest_path"])]
    assert cr.main(["tolerances", *base, "--runs", *runs]) == 0
    written = tmp / "tols" / "16gb.json"
    assert json.loads(written.read_text("utf8"))["profile"] == "16gb"
    assert run_check(recorded, build_db(tmp, "dc.db", set_dir), tolerances=False) == 0


def test_check_loads_the_per_profile_default(recorded, monkeypatch):
    tmp = recorded["tmp"]
    monkeypatch.setattr(cr, "TOLERANCES_DIR", tmp / "tols")
    (tmp / "tols").mkdir()
    loose = dict(TOLERANCES, score_abs={"_default": 5.0})
    (tmp / "tols" / "16gb.json").write_text(json.dumps(loose), "utf8")

    def edit(rows, faces):
        rows[7]["aggregate"] += 1.0
    assert run_check(recorded, build_db(tmp, "pd.db", recorded["set"], edit), tolerances=False) == 0


def test_check_refuses_tolerances_of_another_profile(recorded, capsys):
    other = recorded["tmp"] / "other.json"
    other.write_text(json.dumps(dict(TOLERANCES, profile="8gb")), "utf8")
    db = build_db(recorded["tmp"], "mm.db", recorded["set"])
    assert run_check(recorded, db, "--tolerances", str(other), tolerances=False) == 2
    assert "for profile '8gb', not '16gb'" in capsys.readouterr().err


def test_check_refuses_tolerances_without_a_profile(recorded, capsys):
    bare = recorded["tmp"] / "bare.json"
    bare.write_text(json.dumps({k: v for k, v in TOLERANCES.items() if k != "profile"}), "utf8")
    db = build_db(recorded["tmp"], "np.db", recorded["set"])
    assert run_check(recorded, db, "--tolerances", str(bare), tolerances=False) == 2
    assert "for profile None" in capsys.readouterr().err


@pytest.mark.parametrize("present", [False, True])
def test_scan_warns_when_exiftool_is_missing(world, monkeypatch, capsys, present):
    monkeypatch.setattr(cr.shutil, "which", lambda name: "exiftool" if present else None)
    monkeypatch.setattr(cr, "run_scan", lambda *a, **k: 0)
    argv = ["scan", "--profile", "16gb", "--set-dir", str(world["set"]), "--manifest",
            str(world["manifest_path"]), "--db", str(world["tmp"] / "s.db")]
    assert cr.main(argv) == 0
    assert ("WARNING: exiftool not found" in capsys.readouterr().out) is (not present)


# --------------------------------------------------------------------------- scan

def test_scan_argv_sequence_and_pass_sidecar(world):
    tmp = world["tmp"]
    config_dir = tmp / "cfgs"
    config_dir.mkdir()
    (config_dir / "16gb.json").write_text('{"models": {"vram_profile": "16gb"}}', "utf8")
    operator = tmp / "scoring_config.json"
    operator.write_text("{}", "utf8")
    db = tmp / "scan.db"
    calls = []

    def runner(argv, env):
        calls.append((argv, env))
        return 3 if "--detect-moments" in argv else 0

    failed = cr.run_scan("16gb", world["set"], db, config_dir, runner=runner, facet_py="facet.py",
                         operator_config=operator)
    assert failed == 1
    flags = [argv[2] if argv[2].startswith("--") else "scan" for argv, _ in calls]
    assert flags == ["scan", "--recompute-average", "--detect-sequences", "--detect-duplicates",
                     "--detect-junk", "--detect-moments"]
    scratch_config = str(db) + ".config" + __import__("os").sep + "16gb.json"
    for argv, env in calls:
        assert argv[0] == sys.executable and argv[1] == "facet.py"
        assert argv[argv.index("--db") + 1] == str(db)
        assert argv[argv.index("--config") + 1] == scratch_config
        assert env["PYTHONHASHSEED"] == "0"
    assert calls[0][0][2] == str(world["set"] / "photos")
    sidecar = json.loads(cr.passes_path(db).read_text("utf8"))
    assert [(p["name"], p["exit_code"]) for p in sidecar["passes"]][-2:] == [("detect-junk", 0), ("detect-moments", 3)]
    assert Path(scratch_config).read_text("utf8") == (config_dir / "16gb.json").read_text("utf8")


def test_scan_refusals_and_operator_config_guard(world, monkeypatch):
    tmp = world["tmp"]
    runner = lambda argv, env: 0  # noqa: E731
    operator = tmp / "scoring_config.json"
    operator.write_text("{}", "utf8")
    with pytest.raises(cr.SetupError, match="default/production"):
        cr.run_scan("16gb", world["set"], tmp / "photo_scores_pro.db", runner=runner, operator_config=operator)
    monkeypatch.setenv("DB_PATH", str(tmp / "mine.db"))
    with pytest.raises(cr.SetupError, match="default/production"):
        cr.run_scan("16gb", world["set"], tmp / "mine.db", runner=runner, operator_config=operator)
    foreign = build_db(tmp, "foreign.db", "/elsewhere")
    with pytest.raises(cr.SetupError, match="outside"):
        cr.run_scan("16gb", world["set"], foreign, runner=runner, operator_config=operator)

    def tampering(argv, env):
        operator.write_text('{"changed": true}', "utf8")
        return 0
    with pytest.raises(cr.SetupError, match="changed during the scan"):
        cr.run_scan("16gb", world["set"], tmp / "ok.db", runner=tampering, operator_config=operator)


def test_shipped_override_configs_pin_the_profile():
    for profile in cr.PROFILES:
        data = json.loads((cr.CONFIG_DIR / f"{profile}.json").read_text("utf8"))
        assert data["models"] == {"vram_profile": profile}
        assert data["processing"]["mode"] == "multi-pass"


def test_hf_commits_reads_snapshot_dirs(tmp_path):
    snap = tmp_path / "models--org--name" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    config = {"a": {"model": "org/name", "path": "not/cached"}, "b": ["plain"]}
    assert cr.hf_commits(config, tmp_path) == {"org/name": ["abc123"]}
