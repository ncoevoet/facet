# Panorama Detection — design, thresholds and the traps

Consult before touching `utils/panorama.py`, the sequence override table, or any viewer
surface that renders a panorama badge. Everything here is calibration or a falsified
approach — it is the part that cannot be re-derived from the code.

## Why the evidence is geometric

Nothing in stored metadata identifies a pan: one confirmed set was shot with locked
exposure, another on auto. So consecutive frames are matched with SIFT + RANSAC homography
over the stored 640px thumbnails — no original decode, no model, and `opencv-python` was
already a hard dependency.

**The discriminator is cumulative drift, not per-pair shift.** Real panoramas are shot at
~90% overlap, so one step moves 5-18% of the frame — indistinguishable from shake. Over a
run the difference is absolute: a burst wobbles around zero (0.01 frame widths measured),
a sweep marches (0.56-2.83 measured). Requiring every pair to shift would reject every HDR
panorama, whose frames hold still while the bracket fires. The rule is instead "no step
goes backwards and the total marches", which tolerates static bracket steps for free.

`panorama` vs `hdr_panorama` splits on **exposure spread** (`hdr_min_span_stops`), NOT on
how many steps are static — that cannot tell "static because bracketing" from "static
because barely moving", and misclassified six low-drift non-panoramas as HDR.

## Calibration, and the recall you are not getting

Fixed against **26 confirmed panoramas and 8 confirmed non-panoramas** on a 126k library:
**~96% precision, recall deliberately incomplete.** Vertical low-drift sweeps and
few-position panoramas fall below the drift floor, *inside* the confirmed-negative
distribution; no threshold recovers them without admitting reportage. Missing a panorama
costs nothing, mislabelling reportage costs trust.

## Three approaches already falsified — do not retry

Recorded in `utils/panorama.py` for the same reason:

1. **Per-pair shift magnitude** — see above.
2. **Pure-rotation focal recovery** (`K R K^-1`) — ill-conditioned at these overlaps; one
   33-frame sweep recovered focals ranging from 22 to 2461 px.
3. **Exposure lock** — one confirmed set was auto-exposed.

## Cost: whole-library coverage, incremental measurement

The scan tail, `--recompute-average` and `--recompute-burst` call
`detect_all_sequences(..., incremental=True)`. Every candidate run is still resolved and
every label still rewritten — coverage is unchanged — but only runs holding a photo scanned
since the last pass are re-measured; the rest are read back from stored labels
(`utils.panorama.split_runs` / `stored_segments`).

Measuring every run costs **~7 min on a 126k library**, which `--watch` would otherwise pay
per settled batch. The watermark lives in `stats_cache` under `panorama_detection:watermark`
and carries a fingerprint of the geometry-affecting settings, so editing any threshold
invalidates it. The explicit `--detect-panoramas` / `POST /api/scan/detect_panoramas` always
measure everything, and that entry point alone reports a panorama failure rather than
containing it (`contain_failure=False`).

## Overrides: the two fields that must never be conflated

Geometry cannot recover intent, so sticky per-set overrides correct both directions and
survive the pass's clear-and-rewrite. They are keyed on **member paths, never on
`sequence_group_id`**, which is renumbered every run.

Every photo payload carries two distinct fields, both correlated PK lookups appended in
`api.db_helpers.build_photo_select_columns` + `_culling_photo_columns` (not a LEFT JOIN per
caller):

| Field | Means | Drives |
|---|---|---|
| `sequence_override` | a correction exists (`'suppressed'`, or the forced kind) | the gallery filter |
| `sequence_override_pending` | `applied_at IS NULL` — not yet applied | every "pending" badge, chip and banner |

**An override row persists for as long as the correction applies**, so its existence can
never mean "pending". Keying the badge on existence left it, the culling chip and the
re-run banner on screen for ever — silenced only by deleting the correction they described.
`detect_panoramas` stamps `applied_at` at the end of a successful pass.

The gallery `sequence_override=any|suppressed|forced` filter must be an **uncorrelated
`IN`** over the side table, never a correlated `EXISTS` — the latter made SQLite scan all
126k photos (195 ms against 0 ms measured).

## Correction surfaces — why there are two

Each error direction is found somewhere different, so neither surface alone covers both:

- **False positive** → corrected in culling (per-group menu: suppress, or relabel plain ↔ HDR).
- **Miss** → corrected from the gallery selection bar ("Mark as one panorama"), because an
  undetected sweep appears in NO culling group and is unreachable from culling by construction.

Both are edition-gated, need ≥ 2 frames, and register an `UndoService` command rather than
the confirm's 7-second cooldown — the correction lands only at the next run, so blocking for
7s buys nothing.

## API and config

- `GET /api/config/panorama_detection` is **open** (like `GET /api/config/scoring_contexts`) —
  it only describes how the library was labelled. `PUT` is edition-gated under `CONFIG_WRITE_LOCK`.
- `POST /api/scan/detect_panoramas` re-runs detection, required for an edit to reach the
  gallery: detection is a batch pass, not a live query.
- Overrides: `POST /api/culling-groups/override_sequence` / `clear_sequence_override`,
  table `photo_sequence_overrides`.
- Gallery toggle `hide_panoramas` (default `true`), keyed on `is_sequence_lead`; the
  representative tile carries a `sequence_kind` badge (shared `SequenceKindIconPipe`), shown
  only while the matching hide toggle is collapsing the set.
- `GET /api/photo/set?path=` resolves the set (bracket/panorama/hdr_panorama, else burst,
  else duplicate) a photo belongs to, keyed on `path`. It filters by `sequence_kind` before
  grouping by `sequence_group_id` for the same reason every other reader must. The gallery's
  "open this set" scope (`sequence_group_id`/`sequence_kind`/`burst_group_id`/
  `duplicate_group_id` on `GalleryParams`) is deliberately excluded from the URL sync and
  `RANGE_AND_SELECT_KEYS` in `gallery-filters.util.ts` — the group id is not stable across a
  re-run, so it must never be bookmarkable.
- Config block: `panorama_detection`. Thresholds are documented in
  [docs/CONFIGURATION.md](../../docs/CONFIGURATION.md).
