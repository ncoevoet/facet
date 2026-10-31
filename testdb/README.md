# Face test library (LFW) and a second Facet on port 5010

> **Status: a REGRESSION gate for face work, not a quality gate.**
> The library is mostly centred headshots, and it **has known issues with multiple faces in a
> photo and needs work**: bystanders have no identity, the primary face is taken as the one
> nearest the centre (a rule, not a label), and nothing records how many faces a photo really
> has. **Testing on non-headshot photos (groups, crowds, turned heads, children, lookalikes) is
> critical** and is not covered here. Passing it means "nothing got worse", not "it works on
> real photos".

A family-free face test: 200 photos of 20 public figures from LFW (Labeled Faces in the Wild,
see [Source](#source-lfw)), one folder per person, so face grouping and naming have a known answer. It runs as a second
Facet (same image as the main install) with its own port, photos, database and settings, so a
personal library is never touched, and screenshots of it can be shared.

| | Main Facet | Test Facet |
|---|---|---|
| URL | http://localhost:5000 | http://localhost:5010 |
| Photos | your library | `$TESTDB/photos` (read-only) |
| Database / settings | `data/`, `facet-config/` | `$TESTDB/data`, `$TESTDB/config` |
| Image | your compose image | `IMAGE=` (default `ghcr.io/ncoevoet/facet:latest-cuda`) |
| Model caches | the compose project's named volumes | the same volumes, shared read-only (`MAIN_PROJECT=`, default `facet`; `CACHE_MODE=rw` to let it download) |

`TESTDB` is any empty folder; it ends up holding `download/`, `photos/`, `references/`,
`data/` and `config/`.

## Gate for face-feature changes

Run both scores below on the change and compare with the baseline. **Pass = no line worse.**
Baseline: an 8 GB-profile GPU scan of this library followed by `--cluster-faces-incremental`,
re-recorded on an RTX 4070 Ti SUPER (native Windows, CUDA). Grouping can differ slightly on other
hardware, so record your own baseline first.

| Measure | GPU 8gb | CPU (CI, legacy profile) | Better is |
|---|---|---|---|
| Photos in the library | 200 | 200 | must stay |
| Faces detected | 221 | 221 | must not drop |
| Photos with no face found (accepted detector failures, see Known failures) | 3 | 3 | lower (bonus) |
| `seed_names.py --score`: primary faces right / wrong | 197 / 0 of 197 | 197 / 0 of 197 | more / must stay 0 |
| `seed_names.py --score`: bystanders wrongly given a person's name | 3 of 24 | 3 of 24 | lower |
| `seed_names.py --score`: photos with one name on 2+ faces | 2 | 2 | 0 |
| `open_set_eval.py`, 3 references, T = 0.35: primary right / wrong | 196 / 0 of 196 | 196 / 0 of 196 | must stay |
| `open_set_eval.py`, 3 references, T = 0.35: bystanders named | 0 of 24 | 0 of 24 | must stay 0 |

GPU and CPU give the same result: both form 20 face groups, and the remaining errors are all in
Abdullah_Gul_0008 and _0009. An earlier GPU baseline (194 right, 10 of 24, 5 photos, 22 groups)
did not reproduce on a fresh scan.

CI runs it without a GPU (`.github/workflows/face-gate.yml`): one job builds the library, then
Linux (direct install) and Docker (the CPU image) each scan it on the legacy profile, group,
name and report with `ci_report.py`. `ci_compare.py` fails the run if the reports differ, or
if the report is worse than the **CPU column above on any line**: it reads the column from
this table, so the documented baseline and the check cannot drift. Right answers and
detected faces must not drop and errors must not rise, so a pipeline that finds or names
nothing fails too. A change that improves a line updates the CPU column in the same pull
request. CPU and GPU grouping can differ slightly, so the GPU baseline is recorded by hand.

When it runs, and how deep:

| Trigger | Scan | Time per job |
|---|---|---|
| Pull requests and pushes to `master` that touch face code (`facet.py`, `analyzers/face*.py`, `faces/`, `utils/onnx_runtime.py`, `cli_args.py`, `processing/`, `models/`, `db/`, `config/`, the lock files, `pyproject.toml`, the `Dockerfile`, `testdb/`) | face pass only (`facet.py --pass faces`) | about 5 min |
| Weekly, or by hand (*Run workflow* with `full_scan`) | the whole scoring pipeline | about 1.5 h |

The report depends only on the face pass (InsightFace): a face-pass-only scan of the
library gives the same report as a full scan, measured on CPU. The weekly full scan proves
that stays true. A new push cancels the run it replaces.

A quality claim ("better on real photos") needs a separate, private, hand-checked sample.

## Build the library (once)

1. Download LFW with scikit-learn (~290 MB on disk; the Facet image has scikit-learn):

   ```
   docker run --rm -v $TESTDB/download:/dl --entrypoint python $IMAGE -c \
     "from sklearn.datasets import fetch_lfw_people; fetch_lfw_people(data_home='/dl', min_faces_per_person=10)"
   ```

2. Pick 20 people x 10 photos (deterministic: sorted names, the first 20 with 10+ photos):

   ```
   docker run --rm -v $PWD/testdb:/tool:ro -v $TESTDB:/tdb --entrypoint python $IMAGE \
     /tool/make_lfw_subset.py --lfw /tdb/download/lfw_home/lfw_funneled --out /tdb/photos
   ```

   `people.csv` beside the photos lists folder, person and photo count: the ground truth.

3. Settings: `$TESTDB/config/scoring_config.json` with at least a `viewer.edition_password`,
   `viewer.scan_directories: ["/data/photos"]`, `viewer.features.show_scan_button: true` and
   `viewer.persons.needs_naming_min_faces: 1`.

## Run, scan, group

```
TESTDB=... docker compose -p facet-test -f testdb/docker-compose.testdb.yml up -d
docker exec facet-test python facet.py /data/photos               # a few minutes on a GPU
docker exec facet-test python facet.py --cluster-faces-incremental
```

It does not restart after a reboot (`restart: "no"`); start it again with the same command.
After rebuilding the image, restart the test Facet too. Stop it with
`docker compose -p facet-test -f testdb/docker-compose.testdb.yml down` (its database and
settings stay in `$TESTDB`). Both Facets share one GPU: do not scan both at once.

## Score 1: grouping and naming (`seed_names.py`)

`seed_names.py` names each person's largest face group "Person NN" (NN = the folder number in
`people.csv`); split-off groups, ungrouped faces and bystanders stay unnamed, so Find more and
the naming tools have real work. With `--apply` it writes `reference.csv` and
`answer_key.csv` beside the database (`--score` writes the answer key); a plain run only
reports.

`--apply` refuses to run unless every photo folder in the database is listed in
`people.csv`, and never renames a person who already has a name (other than an earlier
run's "Person NN"), so run against the wrong container it changes nothing.

```
docker cp testdb/. facet-test:/app/data/testdb/
docker exec facet-test python /app/data/testdb/seed_names.py --db /app/data/photo_scores_pro.db --apply
docker exec facet-test python /app/data/testdb/seed_names.py --db /app/data/photo_scores_pro.db --score   # after testing
```

Faces come in two sets. **Known**: the person in the file name, the face nearest the centre
(LFW crops around them), if it is within 45 px of it; primary faces sit at most 31 px from the
centre and bystanders at least 67 px, so when the detector misses the person no bystander is
promoted, and the photo counts as "person not detected". **Unknown**: every other face, a bystander, labelled `Unknown 01`,
`Unknown 02`... (one label per face; bystanders' identities are not in the data). `--score`
reports known faces right / wrong / unnamed (manual faces are not part of the test); bystanders left alone (unnamed, hidden, or named
"Unknown...") vs. wrongly given a person's name; and photos where one name sits on two or more
faces, which is always wrong. Face size does not separate bystanders from the person: misnamed
bystanders were 66-122 px, correctly-left ones 41-118 px, primary faces median 135 px.

## Score 2: open-set naming (`make_references.py`, `open_set_eval.py`)

Know the 20 people first, then name each face or call it Unknown:

1. **Enroll**: up to 3 reference photos per person from LFW photos NOT in the test library.
   Bill McBride has no spare photo, so his first test photo is his reference and is left out
   of the score.
2. **Test** (read-only): every face Facet detected is compared with the 20 references (same
   ArcFace model; manual faces, which have no embedding, are skipped). Best similarity >= T names it; below T it is Unknown.
3. **Score** against the answer key: primary face right / wrong / Unknown; bystanders
   Unknown / named, for T from 0.20 to 0.60.

```
docker run --rm -v $PWD/testdb:/tool:ro -v $TESTDB:/tdb --entrypoint python $IMAGE \
  /tool/make_references.py --lfw /tdb/download/lfw_home/lfw_funneled --photos /tdb/photos --out /tdb/references
docker run --rm -v $PWD/testdb:/tool:ro -v $TESTDB/references:/data/references:ro -v $TESTDB/data:/app/data \
  -v ${MAIN_PROJECT:-facet}_facet-insightface:/home/facet/.insightface -e HOME=/home/facet --entrypoint python $IMAGE \
  /tool/open_set_eval.py --db /app/data/photo_scores_pro.db --refs /data/references
```

Baseline (200 photos, 197 with a face, 196 primary faces scored, 24 bystanders):

| References | T with no mistakes | At T = 0.35 |
|---|---|---|
| 1 per person | 0.25-0.30 | 194 right, 0 wrong, 2 Unknown; bystanders 24/24 Unknown |
| 3 per person | 0.25-0.40 | 196 right, 0 wrong; bystanders 24/24 Unknown |

No primary face was given the wrong name at any T; raising T only turns right answers into
Unknown. On this easy set the open-set test is saturated: it can catch a regression, not show
an improvement.

## Known failures

- **One name on two faces in the same photo.** A person cannot appear twice in one photo, yet
  grouping puts bystanders in the main person's group: 2 photos (Abdullah_Gul_0008 x3,
  Abdullah_Gul_0009 x2). `--score` counts them; a good result is 0.
- **A bystander given a known person's name.** All 3 in the baseline are the bystanders of
  Abdullah_Gul_0008 and _0009, grouped as Abdullah Gul. Counted under "bystanders wrongly given
  a name".
- **Accepted detector failures:** no face is found in Andre_Agassi_0008, Anna_Kournikova_0001
  and Arnold_Schwarzenegger_0001 under the shipped detector and settings (InsightFace
  buffalo_l, `face_detection.min_confidence_percent` 65, `min_face_size` 20 px). Counted as
  misses; finding them is a bonus, not a goal.

## Improvement items

1. **Golden face count with Gemini (or another VLM).** Have it list every face per photo with
   attributes (box, facing, how much is hidden, real person vs picture/screen, blur), no names.
   One shared rule then decides a countable face for both it and Facet (at least 20 px, not the
   back of a head, less than half hidden, a real person in the scene), so an aggressive VLM is
   not scored against Facet for faces Facet was never meant to find. Match faces by box overlap
   (IoU >= 0.5) and send misses and extras to a short list for review by eye; calibrate on a
   few known photos first. LFW photos only.
2. **A non-headshot set**: group and crowd photos with turned heads and small faces, where
   multi-face handling is actually exercised.
3. **Bystander identities**: the same bystander in two photos gets two Unknown labels today.

## Source: LFW

The photos are downloaded from LFW each time the library is built; none are stored in this
repository or redistributed, because LFW carries no explicit licence.

Gary B. Huang, Manu Ramesh, Tamara Berg and Erik Learned-Miller. *Labeled Faces in the Wild:
A Database for Studying Face Recognition in Unconstrained Environments.* University of
Massachusetts, Amherst, Technical Report 07-49, October 2007.
http://vis-www.cs.umass.edu/lfw/

LFW photos are 250x250 and carry no capture date, so scenes and the timeline do not apply.
