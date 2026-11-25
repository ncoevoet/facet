# Spec: Reference photo set + golden outputs + check command + ground-truth labels (GitHub issue #393)

Final spec path after approval: `.claude/specs/issue-393-reference-set.md`.
Locked decisions (not reopened): FULL #393 (all case groups, goldens legacy/8gb/16gb, `check_reference.py`, `expected_category` labels + preference pairs, docs); agent-researched open-licence candidates (CC0 / CC-BY / public domain only) that the USER approves before any download; no binaries in the repo; delivery in staged PRs. The set later feeds the #434 scan-phase profile.

## Objective + success criteria
- S1. On a clean clone, `python testdb/make_reference_set.py --out <dir>` rebuilds the set and every sha256 in `testdb/reference_set.json` matches; a single flipped byte makes it exit non-zero naming the file.
- S2. Every case in the manifest has 3-5 photos, or is a `known_gaps` entry with a reason. A validator test fails on a case with 0-2 photos and no gap, or a gap that also has photos.
- S3. Every file has `licence` in {CC0, CC-BY-*, PD} with `author`, `source_page` and an attribution string. A validator test rejects any other licence value, including "unknown", CC-BY-NC, CC-BY-ND. Amendment 2026-10-30: CC-BY-SA is allowed for any case, used unmodified only, with `share_alike_ok: true`, author, licence, source page and a non-empty `change_notice`; never derived, never a derivation base, no modified or derived binary, thumbnail or preview kept.
- S4. Per profile (legacy, 8gb, 16gb) a golden exists; `check_reference.py --profile P` passes against its own golden on the recording machine.
- S5. Injected changes fail the check and the per-case report names the cases: (a) perturb one score in a golden copy, (b) swap the tagger for a different one (e.g. 16gb scanned with `tagging_model` of 8gb), (c) change one category priority.
- S6. Every scoring category has `expected_category` on its case photos and >= 10 defect-based pairs, or a known gap. The check prints the per-category confusion matrix and pairwise agreement and exits non-zero when either regresses past tolerance.
- S7. Docs: `testdb/README.md` section, one line in `.claude/patterns/vlm-model-change-checklist.md`, `docs/COMMANDS.md` entry if any facet.py flag is added (none planned), translations only where a translated doc is touched (see step 14).
- S8. The set contains what #434 needs: RAW + JPEG mix, >= 1 file >= 40 MP, same-stem RAW+JPEG companions, a bracket, a panorama set (>= 8 frames).

## Files to create / change
Create:
- `testdb/reference_set.json` (manifest, the contract)
- `testdb/make_reference_set.py` (fetch + hash-verify)
- `testdb/reference_common.py` (manifest load/validate, case vocabulary, shared by fetch and check; mirrors `lfw_common.py`)
- `testdb/record_reference.py` (scan + export a golden; or a `--record` mode of check_reference, see step 8)
- `testdb/check_reference.py` (diff vs golden, per-case report, labels)
- `testdb/reference_goldens/{legacy,8gb,16gb}.json` (+ `24gb.json` optional); text, small, committed
- `testdb/reference_labels.json` only if labels are split from the manifest (default: NOT split, labels live in the manifest, `pairs` top level)
- `testdb/reference_configs/{legacy,8gb,16gb,24gb}.json` (config overrides pinning `models.vram_profile`; see step 7)
- `tests/test_reference_set.py` (manifest validator, golden diff logic, label metrics; pure logic, synthetic data)
- `.claude/candidates/issue-393-candidates.md` is NOT created; the candidate list is presented in chat / a plan file, then its approved subset is written into the manifest (step 3)
Change:
- `testdb/README.md` (new section; keep the existing LFW gate table untouched, `ci_compare.py` parses it)
- `.claude/patterns/vlm-model-change-checklist.md` (one line under "Verify before claiming done")
- `CLAUDE.md` only the patterns/docs pointer line if the maintainer wants it (UNVERIFIED preference; default: no change)
- `.github/workflows/` unchanged (GPU CI wiring is out of scope)

## Verified premises (file:line) and UNVERIFIED premises
Verified:
- V1. Issue #393 body read in full via `gh issue view 393 -R ncoevoet/facet`; no comments.
- V2. `testdb/make_lfw_subset.py` is deterministic (sorted names, first N) and writes ground truth CSV beside the photos (`make_lfw_subset.py:19-28, 55-58`); pattern to copy: argparse + `__doc__` first line, `--out`, deterministic order.
- V3. `testdb/lfw_common.py` holds shared helpers imported by sibling scripts via bare `from lfw_common import ...` (`make_references.py:22`); scripts run as `python testdb/x.py`, so `reference_common` must be imported the same bare way.
- V4. `testdb/ci_compare.py:30-40` parses the README gate table by row prefix and the `Measure` / `CPU` header; adding a new README section must not alter those rows or the header (`ci_compare.py:42-55`).
- V5. RAW suppression: `facet.py:1795-1822` builds `jpeg_dir_stems` keyed on `(resolved parent dir, stem.lower())` over `JPEG_EXTENSIONS | HEIF_EXTENSIONS` and drops a RAW with a same-dir same-stem JPEG/HEIF from `todo_list`. Consequence: the companion cases (RAW+JPEG same stem) must live in a directory where the RAW is intentionally skipped; a RAW to be SCORED must have no same-stem JPEG/HEIF in its directory. The layout therefore separates `photos/companions/` (pairs, expect only the JPEG scored) from `photos/raw/`.
- V6. Profile is selected by config `models.vram_profile` (default `"auto"`, `config/scoring_config.default.json:3255`) and resolved by `check_vram_profile_compatibility` (`facet.py:559` etc.); there is no `--profile` CLI flag in `cli_args.py` (grep found none). `--config` and `--db` exist (`cli_args.py:467-469`). So `--profile` of the new check must write a config override, not pass a flag.
- V7. `PHOTOS_COLUMNS` in `db/schema.py:22` holds 113 columns (counted by script). Score and label columns relevant to a golden are listed in step 8. BLOB columns to exclude: `thumbnail`, `clip_embedding`, `caption_embedding`, `histogram_data` (CLAUDE.md "BLOB columns"; `histogram_data` excluded from the golden, its derived stats `histogram_spread`, `mean_luminance`, `histogram_bimodality` kept).
- V8. Faces live in table `faces` (`face_index`, `bbox_x1..y2`, `confidence`, `eyes_open_score`, `smile_score`, `person_id`; read from `db/schema.py` FACES columns); face_count in `photos.face_count`. Per-face bbox is available for IoU.
- V9. Detection passes exist as CLI flags: `--detect-panoramas` (`cli_args.py:127`), `--detect-sequences` (bracket + panorama, `cli_args.py:125-130`), `--detect-moments` (`:144`), `--detect-junk` (`:148`), `--recompute-average` (`:118`). `--detect-moments` needs the VLM caption + `caption_embedding` (CLAUDE.md schema notes), so legacy/8gb goldens will have `narrative_moment` NULL or CLIP-derived; golden must record NULL as NULL (NULL = never evaluated, not clean).
- V10. `SCANNABLE_IMAGE_EXTENSIONS` is defined at `utils/image_loading.py:99`; `.jxl` drops out when `imagecodecs.JPEGXL` is unavailable (CLAUDE.md). JXL-preview DNG case needs imagecodecs present.
- V11. Test-fixture rule: tests build schema via `db.schema.init_database` (`.claude/patterns/test-fixtures.md`); the golden-diff unit tests here need no photos table except where they read a scratch DB, and then must use `init_database`.
- V12. `/d/photo-llm/.gitignore:32` ignores `photos/`; `testdb/` is tracked. The fetched set must go to a user folder on D: (e.g. `D:\facet-scratch\reference_set`), never inside the repo and never under C: (memory: temp on D:).
- V13. Existing CI face gate (`.github/workflows/face-gate.yml`) triggers on paths including `testdb/`; changes under `testdb/` will therefore trigger the face-gate workflow (~5 min per job). Accepted; the new files must not break `ci_compare.py` (V4).
UNVERIFIED (resolve in the step named):
- U1. That a fully deterministic scan exists: GPU nondeterminism (cuDNN, TF32), batching order and onnxruntime provider make scores vary run to run. Resolved ONLY by step 9 stability runs; tolerances are not chosen before them.
- U2. That open-licence sources exist for: Canon CR3/CR2, Nikon NEF, Sony ARW, Fuji RAF, Panasonic RW2, Olympus ORF, Pentax PEF, a Lightroom-merged DNG with JPEG XL preview, an HDR PQ `.hif`, an SDR `.HIF`, CMYK JPEG, 16-bit TIFF/PNG source, EXIF orientations 1-8 with real content, AEB 3/5-frame brackets, an 8+ frame panorama set, a >= 40 MP file with a permissive licence. Resolved by step 2 research; unfound ones become `known_gaps` (never substituted). Known likely sources to try: raw.pixls.us (CC0 RAW samples), Wikimedia Commons (licence per file), Unsplash is NOT acceptable (Unsplash licence is not CC0), Pexels/Pixabay are NOT acceptable (custom licences), NASA/Library of Congress/Smithsonian Open Access (PD/CC0), Flickr Commons (per-file). Synthetic derivations of a CC0 base (resize, re-encode, strip EXIF, rotate via EXIF orientation tag, ICC convert, CMYK convert, JPEG quality 20, grayscale/sepia) are allowed for geometry/format/metadata/near-duplicate cases ONLY if the recipe is in the manifest and the output hash is verified; this keeps the download count and licensing surface small (decision default; see Open questions Q2).
- U3. Whether the HEIF/HDR PQ decode path works on this Windows box (`pillow-heif`); only checked when such a candidate is approved.
- U4. Whether `--pass`/scan can be run in an isolated config without touching the operator's `scoring_config.json` (writes go via `api.config.write_user_config`; a pointed `--config` path should be read-only for a scan, UNVERIFIED). Resolved in step 7.
- U5. The exact SQL/column names of the face tables beyond those listed in V8; step 8 reads `db/schema.py` again when building the export.
- U6. Time/VRAM numbers in the estimate below are projections from the memory note (RTX, 16 GB) and the README's "about 1.5 h" for a 200-photo weekly LFW full scan on CPU; not measured for this set.

## Open questions / risks
- Q1. Licence scope: SA (share-alike) excluded by default; user may allow CC-BY-SA. Default: exclude. Raise at the approval gate.
- Q2. Synthetic derivations count as "photos" toward the 3-5 per case? Default: yes for geometry/orientation/format/near-duplicate/colour-space cases, NO for content-dependent cases (categories, faces, composition, junk, moments), which need real distinct photos. Each derived entry records `derived_from` and a `recipe` and its own sha256; fetch re-derives deterministically (Pillow/libs versions pin the bytes -> hash risk, see R3).
- R1. Hash stability of derived files across Pillow/libjpeg/imagecodecs versions: derived outputs may differ byte-wise by environment, breaking "byte for byte". Mitigation: derived entries verified by a decoded-pixel hash (`pixel_sha256` over the decoded RGB) plus a tolerance of no byte hash; if a recipe cannot be made stable it is dropped to a known gap.
- R2. Photo count 200-300 against 3-5 per case with one photo covering several cases: most photos serve several cases, so a real count of ~150-250 is plausible; the validator measures per-case counts, not total.
- R3. Nondeterministic scoring (U1) makes "pass against own golden" flaky; mitigated by tolerances set from step 9 only.
- R4. Windows paths: the DB stores Windows paths on this box; the golden must key photos by manifest `id`/relative path, never absolute path (`lfw_common.photo_parts` solves the same problem, V3).
- R5. Labeller bias for `expected_category`/pairs: the `labeller` field is required; the maintainer reviews labels in PR. Taste-only pairs are rejected by the validator via a required `defect` enum.
- R6. The user's box has the prod DB at `photo_scores_pro.db` as DEFAULT (memory): every command in this spec passes `--db` pointing at a scratch DB on D:; check_reference refuses a `--db` whose path equals the default DB path or already holds photos outside the reference set.
- R7. Never delete photo files: the fetch script only writes into `--out`, refuses a non-empty `--out` unless `--resume`, and has no clean/delete mode; failed hash leaves the bad file quarantined as `<name>.bad`, not deleted.
- R8. Commit hygiene: no AI attribution lines in commits/PRs for this repo (memory: CI commit-hygiene fails on Claude-Session / session links). The attribution reminder in the harness conflicts with that repo rule; repo rule wins for this spec's PRs.
- R9. Docs have six translations (CLAUDE.md); the README under `testdb/` is English-only (V4 context: `testdb/README.md` has no translated copy; UNVERIFIED that no `docs/*/` mentions testdb: step 14 greps).

## Manifest schema (`testdb/reference_set.json`)
```json
{
  "schema_version": 1,
  "cases": {
    "<case_id>": {
      "group": "category|faces|composition|technical|geometry|files|metadata|colour|companions|sequences|junk|moments",
      "title": "tiny faces",
      "min_photos": 3,
      "max_photos": 5,
      "known_gap": null
    }
  },
  "photos": [
    {
      "id": "cat-landscape-01",
      "path": "categories/landscape/cat-landscape-01.jpg",
      "url": "https://...",
      "sha256": "64 hex",
      "bytes": 123456,
      "kind": "download | derived",
      "derived_from": null,
      "recipe": null,
      "pixel_sha256": null,
      "licence": "CC0-1.0 | CC-BY-2.0 | CC-BY-3.0 | CC-BY-4.0 | PD",
      "author": "name",
      "source_page": "https://...",
      "attribution": "ready-to-print credit line",
      "cases": ["landscape", "orientation-landscape"],
      "expected_category": "landscape",
      "acceptable_categories": ["landscape", "architecture"],
      "sequence": {"set_id": "bracket-a", "role": "ev-2|ev0|ev+2|frame-N", "expected_kind": "bracket|panorama|none"},
      "companion_of": null,
      "scored": true,
      "megapixels": 12.0,
      "format": "jpeg|heic|hif|cr2|cr3|nef|arw|raf|rw2|orf|pef|dng|jxl|tiff|png",
      "notes": ""
    }
  ],
  "pairs": [
    {"better": "tech-sharp-03", "worse": "tech-motion-02", "category": "landscape",
     "defect": "motion_blur|out_of_focus|clipped_highlights|clipped_shadows|underexposed|overexposed|blink|closed_eyes|noise|compression|colour_cast|burst_best_frame",
     "reason": "free text", "labeller": "github-login or agent+reviewer"}
  ],
  "known_gaps": [
    {"case": "raw-pef", "reason": "no CC0/CC-BY PEF sample found as of 2026-MM-DD"}
  ]
}
```
Rules enforced by `reference_common.validate()` (tested in `tests/test_reference_set.py`, each rule with a failing fixture):
- `cases` vocabulary is closed: a photo `cases` entry not in `cases` is an error. Case ids per the issue list: the 15 categories (`portrait portrait_bw group_portrait silhouette art macro astro street aerial concert night wildlife architecture food landscape`), boundary near-misses (`boundary-street-urban`, `boundary-night-concert`, plus others found at curation), faces (`face-one face-two face-crowd10 face-tiny face-profile face-occluded-hand face-mask face-sunglasses face-blink face-smile face-child face-motion-blur face-nonhuman face-animal face-none`), composition (`samp-global samp-horizontal samp-vertical samp-triangular samp-surround samp-quarter samp-cross samp-rule-of-thirds`, `subject-centred subject-edge subject-small subject-fill`), technical (`tech-sharp tech-oof tech-motion tech-glass tech-noise-iso tech-jpeg-heavy tech-under tech-over tech-clip-shadow tech-clip-highlight tech-clip-single-channel tech-cast tech-bw tech-sepia tech-stylised`), geometry (`geo-portrait geo-landscape geo-square geo-wide geo-ge40mp geo-le640`), files (`fmt-jpeg fmt-heic fmt-hif-hdr-pq fmt-hif-sdr raw-cr2 raw-cr3 raw-nef raw-arw raw-raf raw-rw2 raw-orf raw-pef raw-dng raw-dng-lrmerged-jxl`), metadata (`exif-orient-1`..`exif-orient-8 exif-none gps-present gps-absent`), colour (`icc-adobergb icc-displayp3 icc-none cmyk bit-16`), companions (`comp-raw-jpeg comp-xmp`), sequences (`seq-bracket3 seq-bracket5 seq-panorama-ge8 seq-panorama-le6-negative seq-burst-obvious seq-burst-ambiguous dup-edited dup-resized`), junk (`junk-screenshot junk-document junk-receipt junk-meme junk-slide junk-lookalike-real`), moments (`moment-<name>` per `narrative_moment` vocabulary read from the config at step 1).
- per case: `min_photos <= count <= max_photos` (defaults 3 and 5) unless `known_gap` set; a gap case must have 0 photos.
- licence in the allowed set; `author`, `source_page`, `attribution` non-empty; `sha256` 64 hex; `kind=derived` requires `derived_from` (an existing id), `recipe`, `pixel_sha256`.
- `expected_category` is one of the categories in the default config's `categories` (read from `config/scoring_config.default.json`, not a hardcoded list) and is a member of its own `acceptable_categories`.
- `pairs`: `better` and `worse` exist; both `scored`; same `category` as both photos' `expected_category`; `defect` in the enum; no duplicate pair; no pair with the same id twice.
- `sequence.set_id` members share `expected_kind`; a panorama-ge8 set has >= 8 members, panorama-le6-negative has 3-6 and `expected_kind: none`.
- `companion_of` points to an existing id in the same directory with the same stem; `scored: false` is the RAW of a companion pair (V5).
- Unique `id`, unique `path`, paths relative, no `..`.

Directory layout of the built set (`--out`): `photos/<group>/<id>.<ext>`; companions under `photos/companions/` (RAW + JPEG same stem, only JPEG scored, V5); bracket/panorama sets in one directory per set; RAW singles under `photos/raw/` with no same-stem JPEG. `--out` also receives `manifest.lock.json` (copy of the verified manifest hashes, for the check to confirm the folder it reads).

## Golden file format (`testdb/reference_goldens/<profile>.json`)
Text JSON, sorted keys, 2-space indent, one trailing newline, floats rounded to 4 decimals in the file (the tolerances, not the rounding, define equality). Committed. Never contains absolute paths, thumbnails, embeddings or histogram blobs.
```json
{
  "golden_version": 1,
  "profile": "16gb",
  "manifest_sha256": "hash of reference_set.json at record time",
  "environment": {
    "recorded_at": "ISO date",
    "facet_version": "...", "git_commit": "...", "config_version_hash": "...",
    "models": {"embedding": "<id>", "aesthetic": "...", "tagger": "...", "iqa": ["..."],
               "saliency": "...", "composition": "...", "face": "buffalo_l"},
    "hf_commits": {"<repo>": "<commit sha from HF cache snapshot dir>"},
    "libs": {"python": "", "torch": "", "transformers": "", "onnxruntime": "", "open_clip_torch": "", "pyiqa": "", "pillow": "", "numpy": "", "imagecodecs": ""},
    "hardware": {"gpu": "name", "vram_mb": 0, "driver": "", "cuda": "", "os": ""}
  },
  "photos": {
    "<manifest id>": {
      "scores": {"aggregate": 0.0, "aesthetic": 0.0, "...": 0.0},
      "category": "landscape", "tags": ["..."], "caption": "...",
      "face_count": 1, "faces": [{"bbox": [x1,y1,x2,y2], "confidence": 0.0}],
      "composition_pattern": "...", "subject_bbox": [x1,y1,x2,y2], "subject_coverage": 0.0,
      "flags": {"is_blink": 0, "is_monochrome": 0, "is_silhouette": 0, "shadow_clipped": 0, "highlight_clipped": 0},
      "sequence": {"kind": null, "group": "<canonical set label>", "ev_offset": null, "is_lead": 0},
      "burst": {"group": null, "is_lead": 0}, "duplicate": {"group": null, "is_lead": 0},
      "junk_kind": "not_junk|screenshot|...|null", "narrative_moment": "other|...|null"
    }
  }
}
```
- Score columns recorded (from `PHOTOS_COLUMNS`, V7): aggregate, aesthetic, quality_score, topiq_score, aesthetic_iaa, face_quality_iqa, liqe_score, aesthetic_clip, qrealign_score, aesthetic_v25, deqa_score, face_quality, eye_sharpness, face_sharpness, eyes_open_score, expression_score, face_ratio, tech_sharpness, color_score, exposure_score, comp_score, isolation_bonus, power_point_score, leading_lines_score, subject_sharpness, subject_prominence, subject_placement, bg_separation, noise_sigma, dynamic_range_stops, contrast_score, mean_saturation, histogram_spread, mean_luminance, histogram_bimodality, channel_clip_shadow_pct, channel_clip_highlight_pct, dominant_hue, color_temp, form_symmetry, form_balance, form_edge_entropy, form_fractal, color_harmony, skin_tone_delta, skin_tone_cast, learned_score, narrative_moment_confidence, plus `image_width`, `image_height`. NULL stays null (never coerced). A column absent from a profile's scan is recorded as null, not omitted (so a newly populated column shows as a change).
- Bursts/sequence group ids are renumbered every run (CLAUDE.md invariants), so the golden stores membership as the sorted tuple of manifest ids per set, keyed by `(kind, canonical label = smallest member id)`, never raw ids.
- The golden for the same profile is recorded on one machine; other hardware compares with the hardware-class tolerance (step 9).

## Tolerances plan (values are NOT set in the first PRs)
`testdb/reference_tolerances.json` is created only in the stability PR (step 9) from measured run-to-run noise; until then `check_reference.py` runs in `--report-only` and refuses to exit non-zero from tolerance, and `--update` is allowed. Metrics and how each default is derived:
- per-score absolute delta: tolerance_per_column = max(3 x observed std over >= 2 (target 3) repeat scans, 0.02 floor); a column with zero observed noise gets the floor (UNVERIFIED that floors are right).
- SRCC over the set per column: lower bound = (min observed repeat-run SRCC) - 0.005.
- tag Jaccard per photo: lower bound = min observed repeat Jaccard over the set minus 0.05; reported mean and worst.
- category flips: allowed count per case = max observed flips between repeats (expected 0 for deterministic CPU).
- face-count change: 0 allowed per photo unless repeat runs show jitter.
- sequence/junk/moment assignment change: 0 allowed unless repeat jitter.
- bbox IoU (faces, subject): lower bound = min observed repeat IoU minus 0.02.
- label metrics: confusion-matrix errors per category must not exceed the recorded count; pairwise agreement per category must not drop below recorded - 0 (labels are deterministic given the golden-independent scan? NO: agreement derives from scan scores, so it gets the same repeat-noise margin, measured in step 9).
Different-hardware comparison (e.g. golden recorded on GPU, checked on CPU) uses a documented looser class `--hardware-class cross` (2x the same-machine tolerance, UNVERIFIED sensible), exit semantics identical.

## Steps

1. **Manifest schema, validator and case vocabulary (PR 1, no photos).**
   - description: `reference_common.py` with `load_manifest`, `validate`, closed case vocabulary, licence allowlist; `reference_set.json` with the case table only (all cases, empty `photos`, `pairs`) plus `schema_version`. Moment case list is read from `config/scoring_config.default.json` `narrative_moments` at this step.
   - key decision: case vocabulary lives in the manifest `cases` block (the contract per the issue), not hardcoded Python; Python only supplies the group list and the licence allowlist.
   - default: closed vocabulary, `min_photos 3`, `max_photos 5`; categories list read from the default config so a new category cannot be missing.
   - verify: `venv/bin/python -m pytest tests/test_reference_set.py -q` with one failing fixture per rule (unknown case id, case with 2 photos and no gap, gap with photos, licence "CC-BY-NC-4.0", derived without recipe, pair across categories, duplicate pair, bad `expected_category`); each fixture asserts the specific error message. A deliberate edit of the shipped manifest (delete one case's `known_gap` while empty) must fail the same test on the real file (inject and retype-restore, confirm `git status --porcelain`).
   - affected files: `testdb/reference_common.py`, `testdb/reference_set.json`, `tests/test_reference_set.py`.

2. **Candidate research (agent work, no downloads).**
   - description: for each case, find 3-5 candidate sources with licence evidence, produce the candidate list in the format below. Pure web research (WebSearch/WebFetch of metadata pages only, no image downloads).
   - key decision: which hosts are admissible. Default admissible: raw.pixls.us (CC0), Wikimedia Commons (per-file licence, record the file page), NASA / Smithsonian Open Access / Library of Congress / Rijksmuseum (CC0/PD), Flickr Commons with CC0/CC-BY/PD per photo, PD Mark/CC0 sets. Inadmissible: Unsplash, Pexels, Pixabay (custom licences), any CC-BY-NC/ND/SA, "free for personal use", AI-generated images, anything with a person identifiable AND no model release when the source is not Commons-with-consent (default: prefer images where the licence page itself is CC; flag identifiable minors/faces of children as needing user decision, since face-child is a required case).
   - default: candidate list format (one block per case, YAML-like so the approval can be answered inline):
     ```
     case: face-tiny   (needs 3-5; have 5 candidates)
       - cand: face-tiny-a
         source_page: <url>   direct_url: <url>   licence: CC-BY-4.0 (evidence: <licence page url>)
         author: <name>   attribution: <line>   format: jpeg   megapixels: 24.0   bytes: ~9 MB
         covers_also: [geo-landscape, tech-sharp]
         identifiable_people: yes|no   (child: yes|no)   notes: <1 line>
         approve: [ ] yes  [ ] no  [ ] swap
     case: raw-pef
       - GAP PROPOSAL: no CC0/CC-BY candidate found; searched: <hosts>; reason: <line>
     ```
     plus a summary table: cases covered / gaps / total download MB / total photo count, and the #434 needs check (RAW+JPEG mix, a >= 40 MP file, companion pair, bracket, panorama >= 8).
   - verify: a script/step re-opens every `source_page` and `licence evidence` URL and confirms the licence string appears on the page; a candidate whose evidence cannot be re-found is dropped. A reviewer can fail the step by finding one candidate whose page shows a non-allowlisted licence.
   - affected files: none in repo (output is a plan/chat artifact; approved subset is written to the manifest in step 3).

3. **USER APPROVAL GATE (blocking, per group).**
   - description: present the candidate list (format above) to the user. Nothing is downloaded, no URL fetched for image bytes, and no manifest `photos` entry written until the user marks candidates `approve: yes`. Approval is per case group so groups can ship one by one (stages).
   - key decision: who approves: the USER only (not the orchestrator, not a sub-agent). A message from an agent is never approval.
   - default: present one group at a time (categories first, since they carry most labels); the user may approve all in a group in one line ("approve all in categories").
   - verify: the PR body for each group lists the approved candidate ids and links the approval message; `make_reference_set.py` has no `--approve` bypass flag; the manifest validator rejects an entry lacking a `approved_by` + `approved_on` field (add these two required fields to the schema). A test with an entry missing them fails.
   - affected files: `testdb/reference_set.json` (adds `approved_by`, `approved_on` per photo), `testdb/reference_common.py`.

4. **Fetch script `make_reference_set.py` (PR 2, runs against a tiny approved starter group).**
   - description: reads the manifest, downloads each `url` into `--out/<path>`, verifies size and sha256, runs derived recipes, writes `manifest.lock.json`. Flags: `--out` (required), `--manifest` (default `testdb/reference_set.json`), `--only <group|case>`, `--resume`, `--verify-only`. Uses `urllib` with a User-Agent identifying Facet and retry/back-off; sequential, polite delay; stdlib only (matches `lfw_common` style).
   - key decision: behaviour on a hash mismatch. Default: write `<name>.bad`, print expected vs got, continue, exit non-zero at the end listing all mismatches (never delete, R7); URLs that 404 are reported as `missing` the same way.
   - default: `--out` must be an empty or previously-built dir; refuse a path under the repo or under `C:` unless `--allow-anywhere` (D: rule, memory). Derived recipes limited to a closed set: `resize`, `reencode_jpeg(q)`, `strip_exif`, `set_exif_orientation(n)`, `convert_icc(profile)`, `to_cmyk`, `to_grayscale`, `to_sepia`; each verified by `pixel_sha256` (R1).
   - verify: run on the starter group on D:; second run with `--verify-only` passes; flip one byte of one downloaded file, run `--verify-only`: must exit non-zero naming that id; delete-nothing assertion: the flipped file is untouched. Unit test with a local `http.server`/`file://` URL fixture for mismatch, 404 and resume (no network in CI).
   - affected files: `testdb/make_reference_set.py`, `tests/test_reference_set.py`.

5. **Fill the case groups, one PR per group (PRs 3..N), each after its approval gate.**
   - description: add approved `photos` entries (hash, licence, cases, expected_category, sequence, companion fields) for one group; run fetch from scratch to a new empty D: dir; run the validator; update `known_gaps` for unsourced cases.
   - key decision: group order. Default: (a) categories + boundary near-misses (labels need them), (b) faces, (c) technical (supplies most pairs), (d) composition/subject, (e) geometry + colour + metadata, (f) files/RAW brands + companions + #434 needs (>= 40 MP, RAW+JPEG), (g) sequences (brackets, panoramas, bursts, duplicates), (h) junk, (i) moments. Reason: (a) and (c) unlock the labels PR; (f) and (g) unlock #434, so they come before junk/moments if the user prioritises #434 (ask at the gate).
   - verify: fresh fetch of the group into an empty D: dir passes `--verify-only`; validator passes; `git diff --stat` shows only JSON (no binary: add a test asserting no file in `testdb/` exceeds 1 MB or has an image extension).
   - affected files: `testdb/reference_set.json`.

6. **Labels: `expected_category`, `acceptable_categories`, `pairs` (PR after groups a+c).**
   - description: add label fields; pairs only from defect cases in one category (`defect` enum). Pair target >= 10 per category, else listed as low-confidence known gap in `known_gaps` (`case: "pairs-<category>"`).
   - key decision: labeller identity. Default: an agent proposes, the maintainer reviews in the PR; `labeller` records `"<github-login> (reviewed)"`; unreviewed labels are rejected by the validator (field `reviewed: true` required).
   - verify: validator test for each rule in the schema section; `check_reference.py --labels-only` (step 10) on a scratch scan prints a non-empty confusion matrix; a deliberately mislabelled photo (temporary edit, restored by retyping) appears in the "outside accepted set" list.
   - affected files: `testdb/reference_set.json`, `tests/test_reference_set.py`.

7. **Profile configs and isolated scanning.**
   - description: `testdb/reference_configs/<profile>.json` override files setting only `models.vram_profile` (and, for determinism, anything the stability runs show matters, e.g. batch size 1 if needed), passed with `--config`. A runner (`check_reference.py --scan`) invokes `python facet.py <set dir> --config <override> --db <scratch db>` then the post passes `--recompute-average`, `--detect-sequences`, `--detect-junk`, `--detect-moments`, `--cluster-faces-incremental` is NOT run (not golden-relevant).
   - key decision: whether the scan may write the operator's config (U4). Default: runner copies the override to a scratch dir on D: and points `--config` there; before relying on it, a test runs the scan config path under a read-only temp and asserts the repo `scoring_config.json` mtime/hash unchanged.
   - verify: `git status --porcelain scoring_config.json` and a hash of the operator's config before/after a scan are identical; the runner refuses a `--db` equal to the default DB path (R6) and a DB with rows outside the manifest (unit-tested with `init_database` DB, V11).
   - affected files: `testdb/reference_configs/*.json`, `testdb/check_reference.py`.

8. **Golden export and the diff engine (`record_reference.py` or `check_reference.py --record`).**
   - description: read a scratch DB (`photos`, `faces`, via `db.schema` column lists, excluding BLOBs) and emit the golden JSON; the diff engine computes per-photo/per-case/overall metrics. Photos map to manifest ids via relative path under `--set-dir`, handling Windows `\` paths (R4). Environment block collects model ids from the resolved config, HF commits from the HF cache snapshot directory names (`D:\llm_cache` hub cache), `importlib.metadata` versions, `nvidia-smi`/torch device props.
   - key decision: golden values for pass-dependent columns when a pass did not run (e.g. `deqa_score` off): record null (V7 note), and record `profile` + `config_version_hash` so a config change is visible.
   - default: record, not auto-update; `--update` requires an existing golden and prints the diff summary first, and refuses without `--yes` when more than 20% of photos moved (guards accidental re-record).
   - verify: unit tests build a DB via `init_database`, insert 3 photos with distinct BLOBs, export, assert no BLOB column appears and NULLs stay null; diff tests perturb a score, flip a category, drop a face, change a bbox, move a photo between bracket sets and assert each is reported under the right case with the right metric. A "perturb nothing" run asserts exit 0.
   - affected files: `testdb/check_reference.py`, `testdb/record_reference.py` (only if split), `tests/test_reference_set.py`.

9. **Record goldens and stability runs (compute-heavy; PR "goldens: legacy").**
   - description: for each profile, scan the full set at least twice from empty DBs (target 3 for GPU profiles), compare the runs with each other, derive tolerances (section above), write `reference_tolerances.json`, then record the golden from the first run.
   - key decision: tolerance values come ONLY from measured noise (U1). If two same-machine runs differ in category or face count on any photo, the cause is investigated (nondeterministic batching, TF32) and either pinned in `reference_configs` or the metric widened and documented; it is never silently widened.
   - default: record legacy first (CPU, slowest but most reproducible, also CI-feasible later), then 8gb, then 16gb; 24gb only if the user asks.
   - verify: for each profile, run B (second scan) vs golden from run A: must pass; run C with an injected perturbation (`--inject` test hook is NOT added; instead edit a copy of the golden score by hand) must fail naming the case. Record both exit codes in the PR body.
   - affected files: `testdb/reference_goldens/*.json`, `testdb/reference_tolerances.json`.

10. **Per-case report, overall report, label metrics, exit codes.**
    - description: report sections: (1) overall metrics; (2) per-case table (`tiny faces: 2 of 5 lost a face`, `night: 3 category flips`) computed from each photo's `cases`; (3) top-N most-moved photos by normalised delta; (4) category confusion matrix (rows expected_category, columns scored category) and list of photos outside `acceptable_categories`; (5) pairwise agreement per category with flipped pairs listed, categories under 10 pairs marked LOW-CONFIDENCE and not counted as pass; (6) sequence/junk/moment assignment changes. Exit 0 pass, 1 past tolerance, 2 setup error (missing set files, manifest hash mismatch vs golden, DB not from the set). `--json` writes a machine report.
    - key decision: low-confidence categories (<10 pairs): report, never pass silently, but do they fail the exit code? Default: they do not fail (they are listed as known gaps) but are printed in a separate "NOT CHECKED" block so a green run cannot be read as full coverage.
    - default: `--update` rewrites only the golden (never the manifest labels), prints what changed.
    - verify: tests with synthetic golden/scan pairs for each section; a test that a regression only in the minority case (`face-tiny`) fails even when the overall SRCC stays within tolerance (the issue's core requirement); a test for exit code 2 on a mismatched manifest hash.
    - affected files: `testdb/check_reference.py`, `tests/test_reference_set.py`.

11. **Docs.**
    - description: `testdb/README.md` section "Reference photo set": build, scan per profile, check, update, adding a case, known gaps, attribution, the explicit "labels are a guard, not training data" statement. One line in `.claude/patterns/vlm-model-change-checklist.md` "Verify before claiming done": run `check_reference.py` before and after any model change.
    - key decision: keep the existing LFW gate table/header byte-identical (V4).
    - default: English only for `testdb/` (no translated copies exist there; step 11 grep `docs/` for `testdb` to confirm none need an update, R9).
    - verify: `python testdb/ci_compare.py --baseline testdb/README.md <two identical sample reports>` still parses the gate table (use the repo's CI report fixtures if any, else the three lines of the table are diffed unchanged via `git diff -U0 testdb/README.md` showing no hunk in the table); `grep -rn testdb docs/` listed in the PR.
    - affected files: `testdb/README.md`, `.claude/patterns/vlm-model-change-checklist.md`.

12. **#434 hand-off check (no code).**
    - description: assert the built set satisfies S8: has RAW and JPEG, >= 40 MP file (from manifest `megapixels`), a companion pair, a bracket, a panorama >= 8 frames. Implemented as a validator mode `--require-434` run by a test on the shipped manifest once groups f and g land.
    - key decision: if any of these are known gaps, #434 gets a documented alternative (a synthetic derived file) rather than a delayed #393.
    - default: derived 40 MP file (upscaled CC0 base) is acceptable for #434 timing but is NOT counted as covering `geo-ge40mp` realism (marked `kind: derived`).
    - verify: the test fails when the manifest has no >= 40 MP file (assert on a copy with that entry removed).
    - affected files: `tests/test_reference_set.py`, `testdb/reference_common.py`.

## Staged PR breakdown (order and what each proves)
1. PR 1 schema + validator + case table + tests (steps 1, partial 3): proves the contract is enforceable and can fail; no photos, no network.
2. PR 2 fetch script + tests with a local fixture server (step 4) + one tiny approved starter group: proves byte-for-byte rebuild and tamper detection.
3. PR 3 categories + boundary cases (step 5a) with `expected_category` (step 6 part): proves category labelling is loadable.
4. PR 4 technical + faces groups with the first `pairs` (5b, 5c, 6): proves defect pairs reach >= 10 per category or are flagged.
5. PR 5 diff engine + profile configs + export (steps 7, 8, 10): proves the check fails on injected changes using synthetic data (no GPU needed).
6. PR 6 legacy golden + stability runs + tolerances (step 9, legacy): proves the check passes its own golden on a real scan; first real noise numbers.
7. PR 7 8gb golden, PR 8 16gb golden (step 9): same proof per profile; 16gb includes the tagger-swap injection (S5b).
8. PRs 9..N remaining case groups (composition, geometry/colour/metadata, files/RAW/companions, sequences, junk, moments) each after its approval gate; each goldens-affecting group requires re-recording the goldens in that PR or a follow-up (golden is tied to `manifest_sha256`; a manifest change without a re-record makes the check exit 2, by design).
9. PR last: docs (step 11) and #434 hand-off test (step 12); docs may instead land with PR 5 and be extended.
Order caveat: because a golden is tied to the manifest hash, record goldens only after the set is complete or accept re-recording per group (compute cost in the estimate). Default: complete groups before recording the real goldens, and use a small throwaway golden in PR 5 tests (synthetic only).

## Compute / time estimate (UNVERIFIED projections, U6)
- Fetch: 150-250 photos, mean ~8 MB with RAW (20-60 MB each) and the >= 40 MP file: about 2-4 GB total, ~10-30 min on a normal link; disk 4-6 GB incl. scratch on D:.
- Curation/research: the dominant cost, several agent sessions plus user approval rounds, one per group (9 groups).
- legacy scan: README reports ~1.5 h for 200 LFW photos on CPU; a mixed set with RAW demosaic, 40 MP images and large thumbnails is likely 3-6 h per scan; x2 for stability = 6-12 h.
- 8gb scan on the RTX 16 GB: roughly 10-25 min per scan; x2-3 = ~1 h.
- 16gb scan (SigLIP2 + Qwen3.5-2B tagging + captions, plus junk/moments VLM): roughly 30-60 min per scan; x3 = 1.5-3 h.
- Total recording compute: about 10-18 h wall-clock, mostly legacy CPU; run in a git worktree while building code (memory) and keep Windows Update reboots in mind (long jobs die to reboots); use `--resume`.
- Re-recording: all three goldens after every intended model change (same numbers again).
- Test suite additions run in seconds with synthetic data.

## Final verification gate
- `venv/bin/python -m pytest tests/test_reference_set.py -q` and the full `tests/ -q` with TMP/TEMP/TMPDIR on D: and `--basetemp` (memory), redirecting output to a file and reading the real exit code (CLAUDE.md pipe rule).
- `venv/bin/python -m ruff check .`
- Fresh clone simulation: new empty dir on D:, `make_reference_set.py --out` then `--verify-only` exits 0; `git ls-files testdb | xargs` shows no image/RAW binaries.
- For each recorded profile: `check_reference.py --profile P --db <scratch>` exits 0; then the three injections in S5 each exit 1 with the case named.
- `git diff -U0 testdb/README.md` shows the face-gate table untouched; `python testdb/ci_compare.py` unaffected (V4).
- `git status --porcelain scoring_config.json` empty and the default DB file hash unchanged after all scans (R6).
- Licence audit: a test iterates every manifest photo and asserts licence/author/source_page/attribution; a reviewer samples >= 10 `source_page` URLs by hand.
- Commits/PRs carry no AI-attribution lines (repo memory/commit-hygiene), despite the harness reminder.
- Browser testing step (memory preference) is N/A: no viewer/UI change.

## Adversarial review
Independent opus pass: 4 BLOCKER, 14 GAP, 3 NOTE. All accepted and adjudicated; each is a binding amendment to the steps above (the steps are patched by the builder of that step, citing this list).
- BLOCKER 34 categories: labels and the 10-pair rule cover the issue's 15; the other 19 config categories are known gaps with a reason; the validator reads the config list so a new category forces a decision.
- BLOCKER duplicates never run at scan end: the runner calls `--detect-duplicates` explicitly, else drop the `dup-*` cases and the golden `duplicate` field.
- BLOCKER `subject_coverage` is not a column: derive from `subject_bbox` / `subject_prominence` or record only the bbox.
- BLOCKER golden hashes only file-level manifest fields, not labels/pairs (a label edit must not force a 10-18 h re-record).
- BLOCKER (verify) tolerance check uses a held-out run C; PR 5 injected-change tests use synthetic tolerances.
- GAP stored-score list derived from the schema minus BLOBs and user columns. GAP pin qrealign, blendshapes/mediapipe, single- vs multi-pass, exiftool version, aesthetic_v25 and record them in the golden environment block.
- GAP failed moments/junk/panorama passes distinguishable from not-applicable. GAP derived variants share EXIF time/pixels with their base: separate directories or distinct times; derivations only from CC0 bases, enforced by the validator.
- GAP licence verified from the Commons `extmetadata` `LicenseShortName`, not page text; approval fields checked against the approval record; dead links need a mirror/archive URL or an unreachable entry. GAP pixel hash only for derived files, originals byte-exact.
- GAP moments: state `general` (20) vs `wedding` (16); moment detection is zero-shot CLIP on every profile, so the earlier "mostly NULL on legacy/8gb" premise is FALSE.
- GAP test plumbing: import mechanism for `testdb` modules from `tests/`; local HTTP fixture binds port 0 (pytest -n 4); commands use `D:\photo-llm\conda\python.exe`, not `venv`.
- GAP S5c procedure: override carries the whole `categories` list plus `--recompute-average`; add `xmp` format and a sidecar rating/keywords field; `.HIF` vs `.hif` case-sensitive; DB-safety refusal restated in steps 8 and 10. NOTE `make_references.py` import is line 21, not 22.
- Amendment 2026-10-30: CC-BY-SA allowed for any case, used unmodified only (flag, change_notice, no derivation, no pixels; NC/ND still rejected).

## Amendment 2026-11-25 (maintainer decisions, binding over the steps above)
- **Single PR** for the whole of #393; the staged breakdown is build order only. Branch rebased on master each wave, pushed (no PR) after each wave.
- **Fully automated, no per-group user approval.** Step 3's user gate is replaced by a machine licence gate, `testdb/licence_check.py`:
  - Wikimedia Commons files: licence read from the API `extmetadata.LicenseShortName` (and `UsageTerms`/`AttributionRequired`), fetched twice independently; both reads must map to the allowlist (`LICENCE_PATTERN`, or CC-BY-SA under `_check_share_alike`). Author/attribution from `Artist`/`Credit`, HTML stripped.
  - raw.pixls.us: CC0 by site policy, recorded with the sample page as evidence.
  - Rejected automatically: any other licence, missing/ambiguous metadata, `Category:Images of minors`-style or "child" content where a person is identifiable (face-child becomes a known gap unless a non-identifiable/PD historical source exists), AI-generated media (`Category:AI-generated images` / `Generated by AI` templates).
  - Accepted entries carry `approved_by: "licence-check"`, `approved_on` (run date) and `licence_evidence` (API URL + the raw `LicenseShortName` value). The validator requires `licence_evidence` whenever `approved_by == "licence-check"`.
  - The maintainer reviews the final manifest in the single PR; that review is the human gate.
- Everything else (no prod DB, D: only, never delete files, no AI attribution in commits) unchanged.

## Progress log (orchestrator checkpoint)
- 2026-11-25 wave 1-3 DONE, pushed to `origin/feat/reference-set-393` (HEAD 6d7dc1f81): validator, `make_reference_set.py` (fetch/verify/pin/--finalize-gaps, recipes), `licence_check.py` (machine gate), `check_reference.py` (scan/record/check/update/tolerances), 346 tests green.
- Set built at `D:\facet-scratch\refset-393` (4.6 GB, 575 photos verified, 15 known gaps). Candidates in `.claude/.scratch/393-candidates-*.jsonl`; last gate run `D:\facet-scratch\tmp\393-run5\`.
- Deviation: `learned_score` excluded from goldens (depends on the user's own comparisons).
- Sequence cases (`seq-*`) min 2 sets; `comp-raw-jpeg` 6-10 photos (3-5 pairs).
- NEXT: (4) visual case-fit + child check of every photo, which also proposes `expected_category`/`acceptable_categories`; drop failing case memberships, re-run `--finalize-gaps`; (5) defect `pairs` + `reviewed`/`labeller` fields; (6) stability scans + goldens for legacy/8gb/16gb via `check_reference.py scan` (scratch DBs on D:, never the prod DB); (7) docs (`testdb/README.md`, model-change checklist line); (8) full gates, open the single PR, merge on green CI.
- 2026-11-25 wave 4-5 DONE (commit 8f195bbaf, local): visual review of all 575 photos (3 agents, verdicts in `D:\facet-scratch\tmp\393-visual\verdicts-s{1,2,3}.jsonl`, applied by `apply.py` there): 5 child photos removed, 34 memberships dropped, 6 refilled from in-set evidence; 537 photos, 226 labelled, 47 pairs (`pairs.py`: weak defects pair only with curated `<category>-NN` photos); checked pair categories architecture 14 / landscape 11 / night 11, the rest `pairs-*` gaps. Validator fix: `scored: null` counts as scored in pairs. Test fixtures decoupled from the shipped manifest; 347 reference tests green.
- Set dir for scans: `D:\facet-scratch\refset-393b` (hardlinks of exactly the 537 manifest files, `--verify-only` 537 OK). The old `refset-393` still holds the 38 dropped files (never deleted).
- NEXT: (6) scans into `D:\facet-scratch\tmp\393-scans\<profile>-{A,B,C}.db` (8gb-A first as the end-to-end proof), `tolerances --runs A B --holdout C`, `record` from A; then legacy and 16gb; (7) docs agent writing `testdb/README.md` section + checklist line; (8) full gates, push, single PR.
- 2026-11-25 wave 6 in progress. Commits: 287d707e5 (per-profile tolerances `testdb/reference_tolerances/<profile>.json` + README section), c84defe05 (refuter fixes I1-I10: coverage, attribute/GPS compare, unscored RAW, pass sidecar + profile + manifest.lock required, #434 hand-off test). Refuter report: `D:\facet-scratch\tmp\393-refuter.md` (MINORs M2, M4-M12 deliberately not done).
- Scans: chain `D:\facet-scratch\tmp\393-scans\chain.sh 8gb 16gb legacy` (exiftool from `D:\facet-scratch\tools\exiftool`, resumable: skips runs with a passes.json). 8gb A/B/C done (21/10/9 min, all passes exit 0). Set dir `refset-393b` now has `manifest.lock.json`.
- 8gb tolerances: hold-out C PASS (529 photos, 0 violations), but aggregate/leading_lines/bg_separation limits were blown up by 3 RAF files: LibRaw X-Trans demosaic is NON-DETERMINISTIC (3 decodes of raw-raf-05 -> 3 pixel hashes; NEF identical). Fix in progress: per-photo noise allowances (worktree `D:\facet-scratch\wt-393-fix`, branch fix/393-refuter), then re-derive 8gb tolerances, record golden from 8gb-A, check 8gb-B, S5 injections. Report the RAF nondeterminism in the PR body (Facet product finding, not fixed here).
- 2026-11-25 wave 6 DONE. Scans: 4 per profile (A/B/C derive tolerances, D is the hold-out), all passes exit 0, exiftool 13.45 on PATH; 8gb ~9-10 min, 16gb ~16 min, legacy ~8 min per scan on this box. All 9 B/C/D checks clean (0 violations, 524 photos compared: 529 scored minus 5 RAF).
  - Design changes forced by measurement: RAF values are NOT compared (LibRaw X-Trans demosaic random per decode; per-photo allowances from 3 runs failed the 16gb hold-out: raw-raf-03 aggregate +1.05 and a category flip) — presence only, listed under NOT CHECKED. SALIENCY_NOISE_FLOOR (subject_placement 0.0693, bg_separation 0.2252, subject_sharpness 0.0346) from 8gb A/B/C, since legacy A/B/C agreed by chance and legacy-D moved 0.04.
  - Injection proofs on the final tolerances, each exit 1: aggregate +0.5 on aerial-01 (x3 profiles), landscape priority 100->50 via --recompute-average (x3: 179/158/179 flips), 16gb tagger swapped to clip (301 flips, tag jaccard 0.29-0.40). Scripts: D:\facet-scratch\tmp\393-inject\inject{8,16,L}.py.
  - NEXT: rebase on master, CHANGELOG entry, final gates (reference tests, full suite with exiftool on PATH, ruff, mypy ratchet), push, open the single PR.
