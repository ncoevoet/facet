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

## Small-face labelled set (issue #468)

A hand-labelled set for measuring how many small faces a detector finds. It is separate from
the LFW library above: LFW photos are headshots and cannot show small-face recall.

1. `python -m optimization.face_labels sample --db photo_scores.db --out $TESTDB/facelabels`
   draws candidate photos from your library (opened read-only): about 150 with several faces
   (wide focal lengths, event days, some high-resolution frames) and about 50 with no face for
   false positives. It writes the images and a `manifest.csv` under `--out`.
2. Box every face in [labelme](https://github.com/wkentaro/labelme) with the rectangle tool,
   label `face`, saving the JSON next to each image. A photo with no face still needs a
   saved JSON (zero shapes means "reviewed, no face"; a missing JSON is an import error). If
   labelme greys out Save on an untouched image, draw any box, delete it, then save.
3. `python -m optimization.face_labels import --labelme-dir $TESTDB/facelabels/images --manifest $TESTDB/facelabels/manifest.csv --out $TESTDB/facelabels/labels.json`
4. `python facet.py --evaluate-models faces-detect --face-labels $TESTDB/facelabels/labels.json`
   (see [COMMANDS.md](../docs/COMMANDS.md)). Set `face_detection.min_face_size` to 0 in a
   `--config` to see the `<20 px` bucket.

The images and labels stay local under `$TESTDB` and are never committed: they are your own
photos. The sample is drawn from photos where the shipped detector already found several
faces, so it is biased toward easy scenes; read recall as a comparison between candidates on
the same set, not an absolute rate.

Ship rule (fixed before the run): change a default only if, on this set, recall on faces under
0.5% of the frame rises by at least 10 points with the confidence interval excluding 0, false
positives per no-face photo rise by no more than 0.05, and the face pass on the 16gb profile
gets no more than 30% slower. Otherwise record a null result and keep `det_size` 640. The
report prints the first two checks per candidate and a detector-time slowdown; the real
face-pass timing check is manual.

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

## Reference set: CC-BY-SA files

Reference-set files under CC-BY-SA (any case, used unmodified only) keep their own licence and are not
covered by the repo's MIT licence. They are never derived from, no pixels or thumbnails of them
are committed, and review pages built from them stay local.

## Reference photo set

A fixed set of 537 photos with a recorded output per VRAM profile (`legacy`, `8gb`, `16gb`). It is a
regression guard for model, weight and scoring changes: after a change you scan the set again and the
check shows what moved. Results are reported per case (a category, a face situation, a file format, a
sequence kind, a technical defect), so a regression confined to one case is not hidden by an average
over the whole set.

**Labels are a regression guard, not training data.** `expected_category`, `acceptable_categories` and
the defect `pairs` record what a reviewer judged at curation time so that a change in behaviour shows
up. Do not train, fit or tune weights on them.

### Contents

Everything is described by `testdb/reference_set.json` (`schema_version`, `cases`, `photos`, `pairs`,
`known_gaps`). No photo is committed; only the manifest is.

- **cases**: a closed vocabulary. Each case has a `group`, a `title`, `min_photos` / `max_photos` and
  an optional `known_gap`. A photo lists the cases it belongs to.
- **photos**: id, path inside the set, source URL, `sha256`, `bytes`, `kind` (`download`, or `derived`
  with a `recipe` and `pixel_sha256`), licence, author, attribution, source page and the licence
  evidence the gate recorded. RAW files that only accompany a JPEG are `scored: false`.
- **labels**: a photo may carry `expected_category`, `acceptable_categories`, `labeller` and `reviewed`.
  Labels exist for the 15 categories `portrait`, `portrait_bw`, `group_portrait`, `silhouette`, `art`,
  `macro`, `astro`, `street`, `aerial`, `concert`, `night`, `wildlife`, `architecture`, `food`,
  `landscape`.
- **pairs**: `better` / `worse` photo ids with a `category`, a `defect` (`motion_blur`, `out_of_focus`,
  `clipped_highlights`, `clipped_shadows`, `underexposed`, `overexposed`, `blink`, `closed_eyes`,
  `noise`, `compression`, `colour_cast`, `burst_best_frame`) and a reason. The check asks whether the
  scorer still ranks `better` above `worse`. A category is only checked with at least 10 pairs.
- **known_gaps**: a case that has no usable photos yet, with the reason. Reasons are the machine
  licence gate finding nothing admissible, a visual review dropping a photo that did not fit its case,
  and children (no photo of an identifiable child is accepted, so `face-child` is a gap). The
  categories outside the 15 labelled ones appear as `label-<category>` gaps.

### Licences

Only CC0, CC-BY and public domain photos are accepted. CC-BY-SA is accepted unmodified only (never
used as a derivation base, no pixels or thumbnails committed). NC and ND licences are rejected, as are
AI-generated media and identifiable minors. `testdb/licence_check.py` is the machine gate, and it does
not screen children on its own: it rejects a candidate for a child only when the researcher's metadata
flags one (`child`, or `identifiable_people` together with a Commons category naming children, minors,
girls, boys or kids), and the same holds for AI-generated media (category test only). A first pass let 5
photos of children through; a visual review removed them. Review every new candidate by eye. For
Wikimedia Commons it reads the licence from the Commons API twice independently and both reads must
map to the allowlist; for raw.pixls.us it accepts only samples the site lists as CC0. Attribution
lives per photo in the manifest (`attribution`, `author`, `source_page`, `licence_evidence`). See also
[Reference set: CC-BY-SA files](#reference-set-cc-by-sa-files) above.

### Build the set (about 4.5 GB)

Build into a folder on a data drive, never inside the repo or a git worktree and never on a network
path:

```bash
python testdb/make_reference_set.py --out D:/ref-set
python testdb/make_reference_set.py --out D:/ref-set --verify-only   # no network: re-hash every file
```

It downloads each photo, checks `bytes` and `sha256`, recomputes derived photos from their base and
checks `pixel_sha256`, then writes `manifest.lock.json`. A file failing its hash is renamed to
`<name>.bad`; nothing is deleted. Useful flags: `--only GROUP_OR_CASE`, `--resume` (reuse an existing
`--out`), `--delay` and `--backoff` for the request pacing. Exit code 0 means everything verified.

### Scan a profile

```bash
python testdb/check_reference.py scan --profile 8gb --set-dir D:/ref-set --db D:/ref-scans/8gb-A.db
```

Prerequisite: exiftool >= 13.28 on PATH (Facet refuses to write with 13.23-13.27); without it the scan
warns that EXIF comes from the exifread fallback and is not comparable with an exiftool golden.
The database must be a scratch file. The command refuses the production/default database and any
database holding a photo outside `<set-dir>/photos`. It scans with the override config
`testdb/reference_configs/<profile>.json` (copied next to the database), never writes the operator's
`scoring_config.json`, and fails if that file changed during the scan. After the scan it runs, in
order, `--recompute-average`, `--detect-sequences`, `--detect-duplicates`, `--detect-junk` and
`--detect-moments`; each pass's exit code goes into a sidecar next to the database, and the command
exits 1 if any pass failed. The sidecar also records the `profile`. `--config-dir` selects another
folder of profile configs.

### Record, check, update

```bash
python testdb/check_reference.py record --profile 8gb --set-dir D:/ref-set --db D:/ref-scans/8gb-A.db \
    --out testdb/reference_goldens/8gb.json
python testdb/check_reference.py check  --profile 8gb --set-dir D:/ref-set --db D:/ref-scans/8gb-new.db
python testdb/check_reference.py update --profile 8gb --set-dir D:/ref-set --db D:/ref-scans/8gb-new.db
```

- Every command except `scan` first reads `<set-dir>/manifest.lock.json` (written by
  `make_reference_set.py`) and exits 2 when it is missing or its `file_level_digest` differs from the
  manifest's, and reads the database's pass sidecar and exits 2 when it is missing, shows a failed pass
  or names another profile than `--profile`. `record`, `update` and `tolerances` (including
  `--holdout`) refuse a bad scan like `check` does, so a half-finished scan can never become a golden.
- `record` exports a golden: the scores, faces, categories, composition pattern, flags (blink,
  monochrome, silhouette, group portrait, shadow and highlight clipping), GPS presence (a boolean: the
  coordinates themselves are EXIF inputs), `caption` and set assignments of every scored photo, plus an
  informational environment block. `caption` is VLM free text: it is recorded for reading and never
  compared. Goldens live in `testdb/reference_goldens/<profile>.json`
  and are produced by the recording runs, not edited by hand.
- `check` diffs a scan against the golden (`--golden` to pick another file). `--report-only` prints the
  report and never exits 1. `--json OUT` also writes the report as JSON. Without a tolerances file
  `check` is a setup error (exit 2) unless `--report-only` is given.
- `update` rewrites the golden after an intended change. It prints the report first and refuses when
  more than 20 % of the photos moved unless `--yes` is given (exit 1 in that case, the same code as a
  regression; the golden is left untouched). A golden and a scan that hold different photos are a setup
  error: re-record instead.

### Tolerances

```bash
python testdb/check_reference.py tolerances --profile 8gb --set-dir D:/ref-set \
    --runs A.db B.db --holdout C.db
```

The file is written to `testdb/reference_tolerances/<profile>.json` (`--out` overrides) with a `profile`
key; `check` loads the file of its own `--profile` and exits 2 on a mismatch.
Scan the same profile at least twice on the same machine; the limits (score noise per column, SRCC
floor, tag overlap, face-box overlap, allowed category flips, label margins) come from the spread
between those runs. `--holdout` compares a further, independent run against the derived limits and
prints `HOLD-OUT PASS` or `FAIL` (exit 1), which shows the limits are not tuned to the runs they came
from. The file is written by this command, not by hand. It also holds `attribute_changes_max`: how many
photos per case may change `composition_pattern`, a flag or GPS presence (derived from the spread
between the runs; 0 when they agree).

### Read the report

Sections: (1) overall SRCC per score column, (2) per case (lost faces, category flips, moved scores,
assignment changes, changed composition patterns, flags and GPS presence), (3) the most moved photos, (4) category confusion and photos outside
`acceptable_categories`, (5) pairwise agreement per category, (6) sequence, burst, duplicate, junk and
moment changes, then the violations.

Coverage is exact: a photo in the golden but not in the scan (`photo_not_in_scan`), in the scan but
not in the golden (`photo_not_in_golden`), or a `scored: false` manifest photo that the scan scored
anyway (`unscored_photo_scored`, a companion RAW no longer suppressed) is a violation listed by id; a
golden and a scan with no photo in common is a setup error.

The **NOT CHECKED** block lists what a green run does not cover: pair categories with fewer than 10
pairs or none (`LOW-CONFIDENCE`), `comp-xmp: xmp rating import is not exercised by the scan passes`
(no `--import-sidecars` pass runs) and every known-gap case. Read it before calling a run clean.

Exit codes of `check`: `0` pass (or report-only), `1` past tolerance, `2` setup error (missing set
files or lock, manifest digest differs from the golden or the lock so it must be re-recorded, database
not from the set or refused, golden for another profile, a failed, missing or other-profile scan
sidecar, no tolerances file without `--report-only`, or an unexpected exception: exit 1 only ever
means past tolerance).

### Add a case or a photo

1. Run `python testdb/licence_check.py CANDIDATES.jsonl --out APPROVED.json --rejected REJECTED.json`
   on candidate entries, then `python testdb/make_reference_set.py --pin APPROVED.json --out D:/ref-set`
   to download, hash and merge them into the manifest. `--finalize-gaps` (with `--date` and `--out`)
   recomputes the `known_gap` entries.
2. A new case needs an entry under `cases` (group, title, `min_photos`, `max_photos`).
3. Add labels or pairs only after a visual check. Pairs must name two scored photos.
4. Run the manifest validator tests (`python -m pytest tests -q -k reference`) and
   `make_reference_set.py --verify-only`.
5. Changing a photo changes the manifest digest, so re-record every profile golden; changing only a
   label or a pair does not.
