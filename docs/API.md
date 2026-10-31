# API Reference

The viewer's HTTP API, grouped by area. For using the gallery, see [Viewer](VIEWER.md).

Interactive documentation is at `/api/docs` (Swagger UI); the OpenAPI schema is at `/api/openapi.json`.

Developers: `cd client && npm run gen:api` regenerates the client types in `client/src/app/core/api/schema.d.ts` from that schema; CI fails if the committed file is stale.

`[Edition]` (or "edition-gated") marks an endpoint that needs an unlocked edition session.

**Contents:** [Conventions](#conventions) · [Gallery](#gallery) · [Authentication](#authentication) · [Thumbnails and Images](#thumbnails-and-images) · [Filter Options](#filter-options) · [Batch Operations](#batch-operations) · [Persons](#persons) · [Albums](#albums) · [Memories, Timeline, Map & Captions](#memories-timeline-map--captions) · [Capsules](#capsules) · [Statistics](#statistics) · [Comparison Mode](#comparison-mode) · [Burst Culling](#burst-culling) · [Scan](#scan) · [Face Management](#face-management) · [Photo Actions](#photo-actions) · [Config Management](#config-management) · [Merge Suggestions](#merge-suggestions) · [Folders](#folders) · [Download](#download) · [Editor Export](#editor-export) · [Plugins](#plugins) · [Immich](#immich) · [Health](#health) · [Internationalization](#internationalization) · [Filter Options (additional)](#filter-options-additional)

## Conventions

- **`hide_*` toggles** (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`): an omitted toggle falls back to `viewer.defaults`, not "off". Send `hide_bursts=0` etc. explicitly to count everything.
- **Batch target contract** (used by `batch_favorite` and the endpoints that reference it): the body holds exactly one of `{photo_paths}` (max 1000) or `{filters}` (same query params as `GET /api/photos`, as strings, no cap). Optional `exclude` (max 1000) only narrows the target. Neither or both: `422`. A `filters` set naming an album: `404` if the album does not exist, `403` if it belongs to another user on an access-controlled install. Response `{success, count}`, `count` = rows actually written.
- **Date parameters** `date_from` / `date_to` accept an ISO date (`2026-06-01`), an ISO datetime or the EXIF form; an unparseable value is `400`.

## Gallery

| Endpoint | Description |
|----------|-------------|
| `GET /api/photos` | Paginated photo list with filters. Params: `semantic_q`, `semantic_threshold` (0 to 1), `sort=relevance` combine a [semantic query](VIEWER.md#semantic-search) with other filters; `blinks_only` / `duplicates_only` (`1`/`true`) keep only blink-flagged photos or duplicate-group members (leads included) and ignore `hide_*`; `collapse_stacks` controls representative paging; `stack_id` opens permitted members without content/hide filters. Response: `total` = display items, `photo_total` = matching originals. Errors: `400` if `sort=relevance` without `semantic_q`; `503` when the model is busy or fails to load. |
| `GET /api/photos/count` | `{ total }`: photos matching the current gallery filters |
| `GET /api/photos/review_progress` | `{ total, undecided, kept, rejected }` for the whole scope behind the current filters, beyond the loaded page. Takes gallery params but ignores `review_status`, `hide_rejected`, `show_rejected`; `scope_review_status` keeps a smart album's own decision criterion. Errors with `semantic_q`: `400` when semantic search is disabled, `503` when the model is busy or fails |
| `GET /api/photos/paths` | `{ total, paths }`: every matching path, unordered, for actions that need filenames (download, copy). Limits: max 10000; above it, `412` naming the count and cap (never truncated). Select-all and filter-scoped actions use `GET /api/photos/count` and are not bound by this cap |
| `POST /api/photos/by_paths` | Named photos in the requested order, through gallery visibility and `filters` (gallery keys; paging/sort keys dropped). Viewer default type and hide toggles are not applied. Body `{paths (1–500), filters}`; response `{photos, total, missing}` (`missing`: up to 200 unknown, invisible or filtered-out paths). Errors: `422` on unknown filter keys |
| `GET /api/photo` | Single photo details |
| `PUT /api/photo/manual_tags` | Add a [manual tag](VIEWER.md#manual-tags) to one photo (edition-gated). Body `{path, tag}`. A tag equal to an AI tag: `200` with `skipped_existing: true`. Errors: `404` unknown/invisible path; `422` invalid tag or photo already at 50 tags |
| `DELETE /api/photo/manual_tags` | Remove a manual tag from one photo (edition-gated). Body `{path, tag}` |
| `GET /api/photo/set?path=` | The bracket/panorama/hdr_panorama/burst/duplicate set a photo belongs to (sequence over burst, burst over duplicate). Keyed on `path`, not a group id (ids are renumbered every run) |
| `GET /api/photo/histogram?path=&bins=` | Draw-ready luminance + R/G/B bins from the full-resolution image at scan time; `bins` ∈ 32/64/128/256, default 64. All channels share one global max. `r`/`g`/`b` are `null` for rows stored before the per-channel format; `404` when the row has no histogram |
| `GET /api/type_counts?hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Photo counts per type for the sidebar chips (`hide_*` fallback applies) |
| `GET /api/similar_photos/{path}` | Similar photos (modes: `visual`, `color`, `person`). Errors: `422` for `limit` outside 1–500, negative `offset`, or `min_similarity` outside 0–1 |
| `GET /api/search?q=&limit=&threshold=&scope=` | Semantic text-to-image search; `scope=text` = OCR/caption text only. Omitted `threshold` uses the active encoder's `models.*.search_threshold_percent` (`/api/config`'s `search_threshold_default`); an explicit value, including `0.0`, overrides it. Only used when an embedding search runs (`scope != 'text'`) |
| `GET /api/critique?path=&mode=&lang=` | AI critique (rule-based, or with `mode=vlm` plus the cached VLM critique). Read-only: never generates, translates or writes; `vlm_available` says whether `POST /api/critique/vlm` can produce one for this caller |
| `POST /api/critique/vlm` | Generate and store the VLM critique (edition mode). Body: `path`, `lang`, `refresh` (regenerate a cached one). Concurrent requests for one photo share a single generation |
| `GET /api/ranker/status` | Personal-ranker status for the "My Taste" sort (learned coverage %, held-out accuracy) |
| `GET /api/config` | Viewer configuration |

## Authentication

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Authenticate and receive token. `503` when the server's configuration cannot be read |
| `POST /api/auth/edition/login` | Unlock edition mode. `503` when the server's configuration cannot be read (not reported as a wrong password) |
| `POST /api/auth/edition/logout` | Lock edition mode (drop privileges, stay authenticated) |
| `GET /api/auth/status` | Check authentication status |

## Thumbnails and Images

| Endpoint | Description |
|----------|-------------|
| `GET /thumbnail` | Photo thumbnail. A `size` above 640 renders from the original at up to 1920 px (never upscaled). Falls back to the stored thumbnail with a 60-second `max-age` when the original is unavailable, the render does not start within 5 s, or the decode is all black |
| `GET /face_thumbnail/{id}` | Face crop thumbnail |
| `GET /person_thumbnail/{id}` | Person representative thumbnail |
| `GET /image` | Full-resolution image. Native JPEG, PNG, GIF, WebP, BMP and AVIF are sent as original bytes. JPEG XL is sent as `.jxl` only if the Accept header lists `image/jxl`, else as JPEG (`Vary: Accept`) |

## Filter Options

| Endpoint | Description |
|----------|-------------|
| `GET /api/filter_options/cameras` | Camera models with counts |
| `GET /api/filter_options/lenses` | Lens models with counts |
| `GET /api/filter_options/tags` | Tags with counts |
| `GET /api/filter_options/persons` | Persons with counts |
| `GET /api/filter_options/patterns` | Composition patterns |
| `GET /api/filter_options/categories` | Categories with counts |
| `GET /api/filter_options/apertures` | Distinct f-stop values with counts |
| `GET /api/filter_options/focal_lengths` | Distinct focal lengths with counts |
| `GET /api/filter_options/colors` | Color temperature and hue-bucket facets with counts |
| `GET /api/filter_options/metric_ranges` | Observed min/max and histogram per numeric metric (for slider bounds) |

## Batch Operations

All endpoints here use the [batch target contract](#conventions).

| Endpoint | Description |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Mark photos as favorite (clears rejected). Body `{photo_paths}` or `{filters}`, optional `exclude`; response `{success, count}` |
| `POST /api/photos/batch_reject` | Mark photos as rejected (clears favorite and rating) |
| `POST /api/photos/batch_review` | Set a review decision: `decision: kept \| undecided \| rejected`. Kept clears rejection (keeps stars/favorites); rejected clears Keep, stars and favorites; undecided clears both. Returns `{success, count}` plus `undo_entry_id` when one explicitly named photo changes to rejected. The receipt uses the existing revision-protected organization-history revert; no-op, bulk and filter-scoped writes omit it. The gallery filters on `review_status=undecided\|kept\|rejected`; omit it for the normal library |
| `POST /api/photos/batch_rating` | Set star rating; required `rating` (0–5) |
| `POST /api/photos/batch_manual_tags` | Add or remove one [manual tag](VIEWER.md#manual-tags) (edition-gated). Required `tag` and `action` (`add` or `delete`). On `add`, photos at the 50-tag cap or whose AI tags contain the tag are skipped (not counted) |
| `POST /api/photos/capture_date/preview` | `[Edition]` Preview a capture-date shift; writes nothing. Body: `photo_paths` or `filters`, optional `exclude`. Required nonzero integer `offset_seconds` within ±31622400. Returns `{changed, skipped, samples, preview_token}` (`samples`: first 20 old/new dates). Limits: more than 1000 photos is `422` |
| `POST /api/photos/capture_date/apply` | `[Edition]` Apply the shift. Same body as `preview` plus its `preview_token`; same response. Marks dates as manually set and records an [Organization history](VIEWER.md#organization-history) entry. `409` if the photos changed since the preview |

## Persons

| Endpoint | Description |
|----------|-------------|
| `GET /api/persons` | List all persons. Search also matches ASCII decimal IDs; non-ASCII digits such as `١` or `１２` match names literally. `named_only=true` leaves out unnamed persons (the persons page does this while Needs naming is shown); `hidden_only=true` lists only the ignored (hidden) ones, except under `sort=assignment`, where it is ignored: hidden persons are never assignment candidates |
| `POST /api/persons` | Create a person, optionally attaching faces (edition-gated). Body `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Unnamed (no or blank name), non-hidden persons with `face_count >= N`, from clustering or a split (default `viewer.persons.needs_naming_min_faces`), largest first and unpaginated |
| `POST /api/persons/{id}/rename` | Rename a person (edition-gated). Body `{name}`; an empty name clears it. Response `{success, name, face_count, same_name_persons}`, where `face_count` is the renamed person's own stored count (the same measure as each namesake's, so the largest merge target is picked like with like) and `same_name_persons` lists `{id, name, face_count}` for the other visible, non-hidden persons with the same name ignoring case and surrounding spaces, largest first, so the viewer can offer a merge. Nothing is merged |
| `POST /api/persons/{id}/assign_faces` | Bulk-attach faces; emptied old persons are auto-deleted (edition-gated). Body `{face_ids, tolerant?, only_unassigned?}`. `tolerant: true` assigns what it can and reports `missing`, `already`, `skipped_model`, `skipped_hidden`, `skipped_assigned`, `assigned_count`. `only_unassigned: true` skips faces owned by another person and requires `tolerant: true` (else `422`) |
| `POST /api/persons/{id}/split` | Split some faces into a new person (edition-gated). Body `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Hide a person from the list, filters and merge suggestions |
| `POST /api/persons/{id}/unhide` | Unhide a hidden person |
| `POST /api/persons/merge` | Merge two persons (JSON body) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Merge source person into target |
| `POST /api/persons/merge_batch` | Merge multiple persons at once |
| `POST /api/persons/merge_suggestions/reject` | Dismiss a merge suggestion permanently |
| `POST /api/persons/{id}/delete` | Delete a person |
| `POST /api/persons/delete_batch` | Delete multiple persons at once |

## Albums

| Endpoint | Description |
|----------|-------------|
| `GET /api/albums` | List all albums |
| `POST /api/albums` | Create album |
| `GET /api/albums/{id}` | Get album details |
| `PUT /api/albums/{id}` | Update album |
| `DELETE /api/albums/{id}` | Delete album |
| `GET /api/albums/{id}/photos` | List photos in album (paginated) |
| `POST /api/albums/{id}/photos` | Add photos to album |
| `DELETE /api/albums/{id}/photos` | Remove photos from album |
| `PUT /api/albums/{id}/scoring_context` | `[Edition]` Set the album's scoring context and apply it to matching members now, skipping manual overrides (smart albums resolve `smart_filter_json` live). Returns `{updated, conflicts, manual_skipped}` |
| `DELETE /api/albums/{id}/scoring_context` | `[Edition]` Clear the album's scoring context from the members it set. Returns `{ok, cleared}` |
| `GET /api/albums/{id}/suggested_context` | Suggest a scoring context from the album's dominant `narrative_moment` (writes nothing) |
| `POST /api/albums/{id}/share` | Generate share token |
| `DELETE /api/albums/{id}/share` | Revoke share token |
| `GET /api/shared/album/{id}?token=` | View shared album (no auth) |
| `POST /api/shared/album/{id}/session` | Exchange a share token (+ optional PIN) for a client proofing session (rate-limited) |
| `PUT /api/shared/album/{id}/picks` | Client upserts a heart/comment on a photo (proofing session) |
| `GET /api/shared/album/{id}/picks` | Client reads their own picks (proofing session) |
| `GET /api/albums/{id}/picks` | `[Edition]` Owner reads all client picks for the album |

## Memories, Timeline, Map & Captions

| Endpoint | Description |
|----------|-------------|
| `GET /api/memories?date=` | Photos taken on this date in previous years |
| `GET /api/memories/check` | Check if memories exist for a date |
| `GET /api/caption?path=&lang=` | Get the stored AI caption (or stored translation). Read-only: never generates, translates or writes; `source: "none"` when nothing is stored |
| `POST /api/caption` | Generate, translate and store the AI caption (edition mode). Body: `path`, `lang`. Concurrent requests for one photo share a single generation |
| `PUT /api/caption` | Update photo caption (edition mode) |
| `GET /api/timeline?cursor=&limit=&direction=&hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Paginated timeline photos (`hide_*` fallback applies) |
| `GET /api/timeline/dates?year=&month=&hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Available dates for navigation |
| `GET /api/timeline/years?hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Available years with photo counts |
| `GET /api/timeline/months?hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Available months for a year |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Geotagged photos within bounds |
| `GET /api/photos/map/count` | Count of geotagged photos |
| `PUT /api/photo/gps` | `[Edition]` Set or clear a photo's GPS. Body `{path, gps_latitude, gps_longitude, saved_place_id?}`; both coordinates null, or finite within latitude ±90 / longitude ±180. Returns the saved coordinates |
| `POST /api/photos/batch_gps` | `[Edition]` Preview, then apply, a location for up to 1000 visible photos; no file writes. Body `{photo_paths}` or `{filters, exclude?}`, paired finite coordinates, optional `saved_place_id`, `only_missing` (default true; false replaces existing locations). Send `preview: true` first, then apply with the returned `preview_token` (detects stale inputs; does not authorize). Returns `changed`, `skipped`, `preview_token`. Errors: `409` stale preview; `412` oversized scope |
| `DELETE /api/photo/gps?path=` | `[Edition]` Drop a hand-set location and re-read the file's GPS (NULL if none). Returns the stored coordinates |
| `GET /api/places/search?q=` | `[Edition]` Bounded Photon place lookup; changes no photos. Errors: `422` invalid query (validation-detail array); `429` with `Retry-After` when throttled; `502` provider failure; `503` lookup disabled |
| `GET /api/places` | `[Edition]` Current editor’s saved places and 20 recent assigned points |
| `POST /api/places` | `[Edition]` Save `{name, latitude, longitude}` as a private named pin. Limits: 100 places; name 1–120 characters |
| `PUT /api/places/{id}` | `[Edition]` Update an owned pin; photos keep their coordinates |
| `DELETE /api/places/{id}` | `[Edition]` Delete an owned pin; photos keep their coordinates |

## Capsules

| Endpoint | Description |
|----------|-------------|
| `GET /api/capsules` | Paginated capsule list (cached) |
| `GET /api/capsules/{id}/photos` | Photos for a specific capsule |
| `POST /api/capsules/{id}/save-album` | Save capsule as album (edition mode) |

## Statistics

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats/overview` | Overall scoring statistics summary |
| `GET /api/stats/score_distribution` | Score distribution histogram data |
| `GET /api/stats/top_cameras` | Top cameras by photo count |
| `GET /api/stats/categories` | Category counts and averages |
| `GET /api/stats/gear` | Camera/lens/combo counts |
| `GET /api/stats/settings` | Shooting settings distributions |
| `GET /api/stats/timeline` | Timeline data |
| `GET /api/stats/correlations` | Custom metric correlations |
| `GET /api/stats/categories/breakdown` | Per-category photo counts and score distributions |
| `GET /api/stats/categories/weights` | Category weights and modifiers from config |
| `GET /api/stats/categories/correlations` | Pearson r correlation per dimension per category |
| `GET /api/stats/categories/overlap` | Filter overlap analysis between categories |
| `POST /api/stats/categories/update` | Update category weights/modifiers (edition mode) |
| `POST /api/stats/categories/recompute` | Recompute scores for a category (edition mode) |

## Comparison Mode

| Endpoint | Description |
|----------|-------------|
| `GET /api/comparison/next_pair` | `[Edition]` Get next photo pair for comparison |
| `POST /api/comparison/submit` | Submit comparison result |
| `POST /api/comparison/reset` | Reset comparison data |
| `GET /api/comparison/stats` | `[Edition]` Comparison session statistics |
| `GET /api/comparison/history` | `[Edition]` List past comparisons |
| `POST /api/comparison/edit` | Edit a comparison result |
| `POST /api/comparison/delete` | Delete a comparison |
| `GET /api/comparison/coverage` | `[Edition]` Category coverage of comparisons |
| `GET /api/comparison/confidence` | `[Edition]` Confidence metrics for learned scores |
| `GET /api/comparison/photo_metrics` | Raw metrics for photos |
| `GET /api/comparison/category_weights` | `[Edition]` Category weights/filters |
| `GET /api/comparison/learned_weights` | `[Edition]` Suggested weights from comparisons; `suggest_changes` is true when they pass the held-out test of `--optimize-weights` |
| `POST /api/comparison/preview_score` | Preview with custom weights |
| `POST /api/comparison/suggest_filters` | Analyze filter conflicts |
| `POST /api/comparison/override_category` | `[Edition]` Set a sticky per-photo category override (must be a configured category; survives recompute) |
| `POST /api/comparison/clear_category_override` | `[Edition]` Remove a photo's category override; filters decide again on the next recompute |
| `POST /api/recalculate` | Recalculate scores with current weights |

## Burst Culling

| Endpoint | Description |
|----------|-------------|
| `GET /api/burst-groups` | List burst groups for culling |
| `POST /api/burst-groups/select` | Select keepers from a burst group |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groups of visually similar photos |
| `POST /api/similar-groups/select` | Select keepers from a similar group |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene\|bracket\|panorama\|hdr_panorama&exclude_rejected=true&similarity_threshold=&page=&per_page=&date_from=&date_to=` | Groups for culling. `group_by` (default `all` = burst+similar merged): `burst`, `similar`, `scene` (chronological; adds `type`/`start`/`end`/`moment`/`moment_confidence`, ignores `sort`), or one sequence kind (`bracket`, `panorama`, `hdr_panorama`, never merged into `all`). `exclude_rejected` (default `true`) hides `is_rejected=1`; groups left with fewer than 2 photos are dropped. With a trained keeper-ranking head, photos carry `keeper_prob` and groups `keeper_best_path`. A date-only `date_to` covers the whole day |
| `POST /api/culling-groups/confirm` | Confirm culling selections. Body `{group_id, type, paths, keep_paths}`; `type` is `burst \| similar \| scene \| bracket \| panorama \| hdr_panorama`. `type:'scene'` records scene-cull comparison rows; sequence kinds record no comparison pairs. For `burst`, only members listed in `paths` are rejected or marked reviewed |
| `POST /api/culling/auto` | `[Edition]` One-button auto-cull for a scope. Body `{group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, dry_run, profile?, trim_brackets, cursor?, keep_paths?, remove_paths?, expected_digest?}`. Details below |
| `POST /api/culling/plan` | `[Edition]` The assistant's auto-cull plan as culling groups, for `/culling` plan mode; writes nothing. Body: the `POST /api/culling/auto` plan inputs (`group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, profile?, trim_brackets, keep_paths?, remove_paths?`) plus optional `expected_digest` (`412` if the plan's digest differs). Returns `{groups, total_groups, plan_digest, truncated, oversize_groups}`; each group adds `plan: {number, keep_paths, group_reason}`, keepers first. `truncated`: list hit the group/photo cap; `oversize_groups`: groups over the confirm route's per-group cap |
| `GET /api/culling/suggest_profile?album_id=&date_from=&date_to=` | Name the `cull_profiles` preset that fits the scope's dominant shoot type, with confidence and evidence counts; cached per scope. `profile` is `null` below the dominance floor or when the preset isn't configured |
| `POST /api/culling-groups/override_sequence` | `[Edition]` Record a sticky correction of what a set of frames is. Body `{paths, kind?}`; `kind` is `panorama \| hdr_panorama \| bracket`, or omitted for "none of these". A `bracket` needs ≥2 frames, all with usable exposure metadata, no two at the same exposure value (else `400`). Stored in `photo_sequence_overrides` (survives the detector rewriting `photos.sequence_*`); applies on the next `POST /api/scan/detect_panoramas` |
| `POST /api/culling-groups/clear_sequence_override` | `[Edition]` Drop a manual sequence correction, handing the frames back to the detector. Body `{paths}` |
| `POST /api/culling-group/faces` | Per-face badges (eyes open/closed, expression, confidence) for a group, in one batch |
| `POST /api/culling-group/subjects` | Subject close-up crops (from the stored BiRefNet subject box) + group-normalized sharpness for a non-face group, in one batch. `has_subject:false` when there is no box or a near-full-frame box |
| `GET /api/photo/key_subject?path=` | What a photo is about: its best-ranked face, else its stored saliency box, as a `normalized_frame_xyxy` box + centre. No model run; `kind:"none"` when neither exists |
| `POST /api/photos/key_subjects` | The same for up to 1000 paths (`key_subjects_by_path`). Every path is present; unknown or invisible ones return `kind:"none"` |
| `POST /api/photos/keeper_hints` | Per-photo "a better shot exists in this group" hints, grouped by `burst_group_id`. Body `{paths}`; returns `{path: {has_better, best_path, keeper_prob}}`, or `{}` when no keeper-ranking head is trained |
| `GET /api/photo/cull_preview?path=&style=` | `[Edition]` Render the original through a configured darktable style (`--style`, bounded to `preview_max_edge`); disk-cached. Errors: `400` unknown style; `503` darktable-cli unavailable; `502` render failure/timeout |
| `GET /api/scenes` | Chronological scenes of burst-lead photos (read-only) |
| `GET /api/filter_options/junk_kinds` | Detected junk kinds with counts (excludes `not_junk`) for the Junk Sweep chips |
| `POST /api/photo/clear_junk` | `[Edition]` Keep a junk candidate: sets its `junk_kind` to `not_junk` so it leaves the queue. Body `{photo_path}` |

**`POST /api/culling/auto` details:**

- `group_by`: `all \| burst \| similar \| scene` (sequence kinds are not valid here).
- `profile` names a `cull_profiles` preset that supplies `strictness`/`min_keep_per_group` when omitted.
- `dry_run` (default `true`) returns the per-group keep/reject preview; an apply rejects the rest and records culling pairs.
- `trim_brackets` (default `false`) trims brackets whose base exposure clips neither shadows nor highlights down to that base frame. It is the only auto-cull path that reduces a sequence set.
- Paging: the whole scope is planned on every call and returned in pages of whole groups (`cursor` in, `next_cursor` out, `null` when complete; 200 photos per page, a larger single group gets its own page), with totals and a `plan_digest`.
- `keep_paths` / `remove_paths` (up to 1000 each) override single frames; stale paths return as `ignored_overrides`. Removing a frame the plan keeps in a bracket, panorama or HDR panorama set is `400`; restating a planned removal is a no-op.
- `expected_digest` on an apply: `412` before any write when the plan changed.

## Scan

**Access rule** for `/start`, `/status`, `/stream_token` and `/directories`: `superadmin` role (multi-user), or an edition session on a locked single-user install (`viewer.edition_password` set). An open single-user install (`viewer.edition_password` empty, the shipped default) answers `403` to every caller, even one holding a valid edition-generation JWT.

| Endpoint | Description |
|----------|-------------|
| `POST /api/scan/start` | Start a scoring scan (access rule above) |
| `GET /api/scan/status` | Scan progress; structured `progress`: `{phase, current, total, eta_seconds}` |
| `GET /api/scan/stream?token=<jwt>` | Real-time progress via Server-Sent Events. Get the token from `GET /api/scan/stream_token` and pass it as a query param (`EventSource` can't set headers), with automatic fallback to polling `/status` |
| `GET /api/scan/directories` | List configured scan directories |
| `POST /api/scan/recompute` | `[Edition]` Run a full-library aggregate recompute (`--recompute-average`) as a background job. Takes only `confirm` and optional `category` (runs `--recompute-category`: that category only, burst and sequence detection skipped). Not bound by the access rule above. Errors: `409` naming the holder when a scan or recompute already runs (viewer or terminal, via `facet.LibraryLock`); `400` unknown category |
| `GET /api/scan/recompute_status` | `[Edition]` Recompute progress: `{running, kind, scope, started_at, progress, exit_code}`; `scope` is `all` or `category:<name>`, `started_at` identifies the job. Omits the `output_lines` log that `/status` returns |

## Face Management

| Endpoint | Description |
|----------|-------------|
| `GET /api/person/{id}/faces` | List faces for a person |
| `GET /api/person/{id}/possible_faces` | Faces closest to the person's centroid, best first (same embedding model only). Query: `scope` (`unassigned` (default), `unnamed`, `other_persons`, `all`; `unnamed` adds faces in clusters nobody has named yet to the unassigned ones, and only `unassigned` is answered from an index), `owners` (optional comma list drawn from `ungrouped`, `unnamed_group`, `named`: keep only faces with such an owner, applied before `limit`; any other token is `422`), `min_similarity`, `limit` (≤ 100), `per_owner` (default `false`; when `true`, `limit` applies to each owner class separately, so up to `limit` faces of each of `ungrouped`, `unnamed_group` and `named`, and `faces` is all of them sorted by similarity, descending; `owners` still selects the classes; `counts`, `best_similarity` and `similar_groups` are unchanged), `path_prefix`, `date_from`, `date_to`. Response `{faces, faces_scanned, candidates, counts, best_similarity, similar_groups}`: each face carries `owner` (`ungrouped` in no person, `unnamed_group` in a person with no or a blank name, `named` otherwise); `counts` is `{ungrouped, unnamed_group, named}`, the scanned faces at or above `min_similarity` per owner, whatever `owners` and `limit` say; `best_similarity` is the highest similarity of every scanned face, the ones below the threshold included (`null` when nothing was scanned), so an empty list can say how close the closest face came; `similar_groups` lists up to 10 `{person_id, name, face_count, similarity}`: other visible, non-hidden persons whose centroid, of the same embedding model, is at least `min_similarity` alike, best first (`name` is `null` for an unnamed group; computed from `persons` alone, for every scope). Errors: `404` unknown/invisible person; `412` no usable centroid, or scan over the server's face ceiling (narrow with `scope`, `path_prefix` or dates; `owners` filters the results, not the scan); `422` bad `owners` |
| `POST /api/person/{id}/avatar` | Set person avatar face |
| `POST /api/person/{id}/face_boxes` | The person's face boxes for a batch of photos, so a gallery filtered to one person outlines every tile in one call. Body `{paths}` (1 to 200, else `422`). Response `{boxes: {path: [[x1, y1, x2, y2], ...]}}`, each box normalised to the frame (0..1). Only faces assigned to that person; a path the caller cannot see, an unknown one, and a photo with no trustworthy box are all omitted |
| `GET /api/photo/faces` | List faces detected in a photo, each with `box` normalised to the frame (0..1), or `null` when the stored dimensions cannot be trusted for it |
| `POST /api/face/{id}/assign` | Assign a face to a person |
| `POST /api/face/{id}/unassign` | Detach that one face from its person (edition-gated); other faces of the person in the same photo are kept. The person's face count and picture are repaired, and a person left with no face is deleted, as `unassign_person` does. Response `{success, face_id, person_id}`, `person_id` being the former owner (even when deleted) or `null`. `404` for an unknown or invisible face |
| `POST /api/photo/assign_all_faces` | Assign all faces in a photo to a person |
| `POST /api/photo/unassign_person` | Unassign a person from every face in a photo; a person left with no face is deleted |

## Photo Actions

| Endpoint | Description |
|----------|-------------|
| `POST /api/photo/set_rating` | Set star rating for a photo |
| `POST /api/photo/toggle_favorite` | Toggle favorite status |
| `POST /api/photo/toggle_rejected` | Toggle rejected status |
| `DELETE /api/photo/capture_date?path=` | `[Edition]` Drop a corrected capture date and re-read the file's own (or clear it if none). Returns `{date_taken, date_manually_set}`. Errors: `409` unsupported file date (manual date kept) or photo changed; `404` file unreadable |
| `GET /api/stacks/by-photo` | Read the owner-private stack for an exact photo path; permitted members only |
| `GET /api/stacks/{stack_id}` | Read an owner-private stack by UUID; partial visibility is read-only |
| `POST /api/stacks/suggestions` | Read-only stack candidates. Body `{filters, include_photos?}` (gallery filters, ignoring stack collapse and burst/duplicate hiding). Returns `{suggestions: [{key, kind, group_id, paths, cover_path, photos}]}`, omitting this account's skipped ones. `include_photos` defaults to `false` (`photos: null`); `true` includes ordered darkroom rows with the caller's marks (see below). Limits: 20 suggestions / 2000 paths / 1000 per group. Errors: `422` invalid/unknown filters; album access and visibility enforced |
| `POST /api/stacks/suggestions/dismissals` | `[Edition]` Skip a suggestion for this account until its membership changes. Body `{kind, paths}` (exact members). Idempotent; `204` |
| `DELETE /api/stacks/suggestions/dismissals/{key}` | `[Edition]` Restore a skipped suggestion (Undo); `204` |
| `POST /api/stacks/regroup/preview` | Read-only preview. Body `{selected_paths, mode?}`: 2–1000 distinct explicit paths; `mode` is `combine` (default, includes source members) or `selected` (moves only selected members). Returns `{selected_paths, mode, paths, cover_path, source_stacks, unstacked_paths, affected_paths, expected_state}`. The SHA-256 `expected_state` binds apply to the reviewed membership snapshot. Missing/invisible inputs or partially visible sources: `409`; invalid input or over 1000 affected photos: `422`. Never writes |
| `POST /api/stacks/regroup/apply` | `[Edition]` Body requires the preview's `selected_paths` and `expected_state`, the same `mode`, and ordered `paths` (2–1000 distinct members drawn from preview `paths`) and member `cover_path`; `mode` defaults to `combine` if omitted. Returns `{stack, undo, affected_paths, changed}`. Rechecks authorization, source membership and revisions transactionally before writes. `409` unavailable/partially visible sources or stale snapshot; `422` invalid input, limits or unrepresentable history; `403` no edition access. Exact unchanged grouping returns `changed: false, undo: null` without a history entry |
| `POST /api/stacks` | `[Edition]` Create from 2–1000 explicit paths and `cover_path`; returns the stack and `undo.entry_id` |
| `PUT /api/stacks/{stack_id}` | `[Edition]` Replace paths/order and optional `cover_path`, with `expected_revision`; 0 or 1 members dissolves the stack |
| `DELETE /api/stacks/{stack_id}` | `[Edition]` Dissolve, with `expected_revision` query; stale or partially visible stacks are refused |
| `GET /api/organization_history` | `[Edition]` The caller's latest 50 [Organization history](VIEWER.md#organization-history) entries, newest first: `{entries: [{id, kind (gps, date or review, stack), created_at, part, parts, reverted, changes: [{path, before, after, revision}]}]}`. Entries naming deleted or invisible photos are omitted. Never cached |
| `POST /api/organization_history/{entry_id}/revert` | `[Edition]` Restore an entry's recorded values; returns `{changed}`. Errors: `404` unknown or invisible entry; `409` already reverted, or a photo changed since |

With `include_photos: true`, each suggestion's `photos` follows its `paths` order, without re-sorting by `burst_score`. Each row declares exactly these 16 fields: `path`, `filename`, `aggregate`, `aesthetic`, `tech_sharpness`, `is_blink`, `is_burst_lead`, `date_taken`, `burst_score`, `eyes_open_score`, `expression_score`, `is_rejected`, `is_kept`, `is_favorite`, `star_rating`, `preview_revision`. Rows use current caller visibility and per-user marks; no shared private-row cache is used. `group_id` identifies the existing detector group; `key` identifies the membership-specific suggestion/dismissal. This read API remains available without edition access; the full-page stack-review UI requires edition access.

Regrouping bounds both the result and the complete affected preview to 1000 photos, including members left in source stacks. A result may exclude previewed members and reorder the remaining ones. Contributing source stacks retain a remainder of two or more photos; a single remainder becomes unstacked. Wholly excluded source stacks keep their membership and revisions. Undo restores the complete recorded change while current revisions still match. These operations change manual organization only, never originals, metadata, ratings, Keep/Reject decisions or culling comparisons.

## Config Management

| Endpoint | Description |
|----------|-------------|
| `POST /api/config/update_weights` | Update scoring weights (used by **Apply** in the Weight Suggestions tab; does not re-centre the category bonus) |
| `GET /api/config/weight_snapshots` | `[Edition]` List saved weight snapshots |
| `POST /api/config/save_snapshot` | Save current weights as snapshot |
| `POST /api/config/restore_weights` | Restore weights from snapshot (and the category bonus, if recorded) |
| `GET /api/config/category_priorities` | `[Edition]` List categories in current priority (evaluation) order |
| `POST /api/config/category_priorities` | `[Edition]` Reorder category evaluation priority (permutes existing priority values, no renumbering) |
| `GET /api/config/scoring_contexts` | List scoring contexts, each with its resolved category order |
| `PUT /api/config/scoring_contexts/{name}` | `[Edition]` Rewrite one context's `promote`/`excluded` delta. Body `{promote, excluded}`. Rejects an unknown context, unknown categories, `default` in either list, and duplicates in `promote` (400); a name in both lists is accepted and `excluded` wins |

## Merge Suggestions

| Endpoint | Description |
|----------|-------------|
| `GET /api/merge_suggestions` | Suggested person merges based on face similarity |

## Folders

| Endpoint | Description |
|----------|-------------|
| `GET /api/folders?hide_blinks=&hide_bursts=&hide_duplicates=&hide_brackets=&hide_panoramas=` | Photo folder structure (`hide_*` fallback applies) |

## Download

| Endpoint | Description |
|----------|-------------|
| `GET /api/download/options` | Download types available for a photo (`path`, optional `is_shared`), including companion RAW and configured darktable profiles |
| `GET /api/download` | Download a photo (`path`, `type=original\|darktable\|raw`, optional `profile`) |
| `GET /api/photo/social_crop` | `[Edition]` Full-resolution JPEG cropped to a social aspect preset (`path`, `preset`) |
| `GET /api/photo/social_crop/preview` | `[Edition]` Only the normalized crop rectangle and framing source for a preset (`path`, `preset`); no original decode |

**Download types:**

- `original`: the file as-is (JPG/HEIF), or RAW converted to JPEG with the viewer's rendering. A bracketed frame downloads with no camera preview and no exposure gain; see [CONFIGURATION.md](CONFIGURATION.md#bracketed-frames-render-uncorrected).
- `darktable`: the companion RAW converted with a named darktable profile (requires `profile`). Falls back to `original` without a companion RAW.
- `raw`: the companion RAW as-is (not available in shared albums).

**Social crop.** Needs `viewer.features.show_social_export` (default `true`) and an unlocked edition. Presets come from `social_export.presets` (square 1:1, portrait 4:5, story 9:16 by default). The crop is the largest rectangle of the target aspect that fits the image, centred on the subject. The `preview` endpoint's framing source is `saliency` (stored BiRefNet box, `photos.subject_bbox`, from the saliency pass or `--recompute-saliency`), `faces` (union of face boxes) or `center`. EXIF orientation is applied before cropping.

## Editor Export

| Endpoint | Description |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Write one XMP sidecar |
| `POST /api/export/sidecars` | `[Edition]` Write sidecars for explicit paths or a filter set. Body `{paths?, filters?, exclude?, overwrite}`; one photo's failure does not stop the others (details in the server log). Limits/errors: see [path-or-filter target](#path-or-filter-target) |
| `POST /api/export/sidecar_jobs` | `[Edition]` Start a bounded background sidecar export (paths or filters, exclude, overwrite); returns a private progress receipt (`202`). Errors: `503 library_busy` with `Retry-After: 5` when the library lock is held; `503` without retry hint when lock or receipt storage is unusable (check logs and library cache permissions); `409` when retrying a still-running export |
| `GET /api/export/sidecar_jobs` | `[Edition]` Up to 20 recent receipts of the caller |
| `GET /api/export/sidecar_jobs/{id}` | `[Edition]` One caller-owned progress receipt |
| `POST /api/export/sidecar_jobs/{id}/cancel` | `[Edition]` Request stop between files; completed writes remain |
| `POST /api/export/sidecar_jobs/{id}/retry` | `[Edition]` New job for failed/skipped/unfinished files with current metadata and visibility (`202`) |
| `POST /api/photo/embed_metadata` | `[Edition]` Embed metadata into the original (JPEG/HEIC/TIFF/PNG/DNG; RAW never modified) and write the sidecar |
| `POST /api/lightroom/manifest` | `[Edition]` Build the `facet_manifest.json` that `--export-manifest` writes, scoped by `{paths?, filters?, exclude?}`; returned as an attachment with the caller's own ratings. Expands to full burst/sequence sets, then applies `exclude` (excluded frames are not re-added). Multi-user: photos outside the caller's visible directories are dropped. Limits: 10000 before expansion, 50000 after (`POST /api/lightroom/import`'s cap); `412` naming count and cap |
| `POST /api/lightroom/import` | `[Edition]` Import the plug-in's Lightroom state (raw JSON body, no multipart) via `processing.lightroom_sync.import_lightroom_state`; Lightroom wins for `rating`/`pick`. Multi-user: records outside the caller's visible directories count as `unmatched`. Response `{matched, unmatched, changed}`. Limits/errors: `413` above 20 MB or 50000 photos (photo count checked after `json.loads`; chunked bodies without `Content-Length` refused once past 20 MB); `400` before any write if the body is not `{"format":"facet-lightroom-state","version":1,...}` |
| `POST /api/albums/{id}/export` | `[Edition]` Album export as sidecars, copy, or symlink |
| `POST /api/cull/apply` | `[Edition]` Copy keeps or move/trash rejects to a folder (see [Cull to folder](VIEWER.md#cull-to-folder)). Body `{paths?, filters?, exclude?, action, target_dir?, include_companions, include_sequence_siblings, dry_run, preview_digest?}`. Details below |
| `POST /api/photos/refresh` | `[Edition]` Refresh metadata and preview. Body `{paths: string[]}` (1–100); returns `{refreshed: string[], failed: [{path, reason}]}`, `reason` ∈ `unavailable`, `changed`, `busy`, `failed`. Errors: `404` (nothing refreshed) a path is unknown or not writable for you; `422` count outside 1–100 or invalid path; `503` another library job runs or storage is unavailable |
| `POST /api/photo/delete` | `[Edition]` Send photos to the OS trash (recoverable; see [Delete](VIEWER.md#delete)). Body `{paths, include_companions, include_sequence_siblings, remove_missing, dry_run}`. Details below |

### Path-or-filter target

Shared by `POST /api/export/sidecars`, `POST /api/lightroom/manifest` and `POST /api/cull/apply`:

- Exactly one of `paths` (max 10000) or a gallery `filters` set. Both: `422`; neither: `400`.
- `exclude` (optional, max 1000) only narrows the target.
- `filters` resolves like `GET /api/photos` (viewer defaults plus `type` preset expansion).
- A `filters` set naming an album: `404` if it does not exist, `403` if it is another user's on an access-controlled install.
- A `filters` set matching more than 10000 photos: `412` naming the count and the cap, never truncated (also on a dry run).

**`POST /api/cull/apply` details:**

- With a `filters` body, `filters.hide_brackets` / `filters.hide_panoramas` decide the scope, not `viewer.defaults`.
- `action`: `copy_keeps \| trash_rejects \| move_rejects`.
- `include_companions` (default `false`): add each file's same-stem companion RAW and `.xmp`.
- `include_sequence_siblings` (default `false`): add every other frame sharing a matched photo's `(sequence_kind, sequence_group_id)` **whose own reject state matches the action**. Excluded paths are never re-added as siblings.
- `dry_run` (default `true`) returns `preview_digest`, a 64-character digest of the resolved files and settings. Send it with Apply: `409` before any write if the preview changed.
- Response adds `matched` and `sequence_siblings` (count, reported even when the flag is off) to `skipped` / `excluded_by_state` / `not_visible`.

**`POST /api/photo/delete` details:**

- Needs `viewer.cull.allow_trash` (same flag as `/api/cull/apply`): `403` when off; `400` when `send2trash` is not installed.
- `paths` only (max 10000); no `filters`/`exclude`, so select-all-in-view cannot use it. Default scope is the named file only.
- `include_companions` (default `false`): add the same-stem RAW and `.xmp`; a companion with its own `photos` row is removed once it trashes.
- `include_sequence_siblings` (default `false`): widen to every frame sharing `(sequence_kind, sequence_group_id)`, as on `/api/cull/apply`.
- A bracket's base exposure (`sequence_ev_offset = 0`) is refused (`refused_bracket_lead`) unless `include_sequence_siblings` deletes the whole bracket. A panorama lead deleted alone hands the lead to a surviving sibling.
- A trashed file's row is deleted at once (no `--cleanup-missing-photos` needed).
- `skipped` (file already missing) keeps its row for `--cleanup-missing-photos`; with `remove_missing` (default `false`) the row is removed and listed in `removed_missing`, not `deleted`. Paths refused by the scan-directory allowlist, or in a missing or empty folder, stay in `skipped`.
- `errors` (trash failed) keep their row.
- `dry_run` defaults to `true`. Per-path response: `{dry_run, would_trash, deleted, not_found, not_visible, refused_bracket_lead, sequence_siblings, skipped, removed_missing, trashed, errors}`.

## Plugins

| Endpoint | Description |
|----------|-------------|
| `GET /api/plugins` | `[Edition]` List configured plugins |
| `POST /api/plugins/test-webhook` | `[Edition]` Test a webhook plugin |

## Immich

| Endpoint | Description |
|----------|-------------|
| `POST /api/immich/webhook` | Receive an Immich workflow webhook and mirror the rating at once; unscored assets wait for the next `--immich-sync`. Never triggers a scan. Static-token auth (`immich.webhook.token_env`; unset: `404`). See [docs/IMMICH.md](IMMICH.md) |
| `GET /api/immich/diagnostics` | Administrator-only status; `check_connection=true` tests connectivity with read-only remote requests |

## Health

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Server health check |
| `GET /ready` | Server readiness check |
| `GET /metrics` | Prometheus-format metrics: photo counts, embedding coverage, DB size, process memory |

## Internationalization

| Endpoint | Description |
|----------|-------------|
| `GET /api/i18n/languages` | List available languages |
| `GET /api/i18n/{lang}` | Get translations for a language |

## Filter Options (additional)

| Endpoint | Description |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Reverse geocode coordinates to place name |
