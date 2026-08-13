# Facet Improvement Roadmap — August 2026

Synthesized 2026-08-12 from 3 parallel research passes (ecosystem, competitors, candidate models) plus 2 build-readiness investigations (LR plugin, card ingest) and a code-verified status audit of the July roadmap (which is fully consumed except the LR Lua plugin). Full reports committed alongside in [`research-2026-08/`](research-2026-08/); every item below carries its evidence. Effort: S ≤ 1 session, M = 2–5, L = multi-week.

**Standing exclusions (do not re-propose):** video indexing, funding buttons, first-party mobile app, photobook automation, PIAA (closed 2026-07-07 with recorded re-open conditions).

## Already fixed during this synthesis (wave 1 / 1.5)

- **Immich `rating: 0` wedge** — Immich v3 rejects 0 (`asset.dto.ts` `.nullish()` + refine, verified upstream); the sync's clear path sent 0, one clear aborted the batch before `synced_state` advanced → every later sync failed. Fixed: clear = `null` (`63caecc`).
- **ruff 0.16 default-widening** — bare `ruff check .` gate pinned to `E,F,W --ignore E501` (`a30d7bd`); Dependabot #88 verified locally and merged.
- **Portfolio BLOB-before-bound** (`515435a`); **i18n orphan keys + fr NBSP** (`e48bfd7`); **local venv pillow/pyjwt** synced to lock (no repo change).
- **`trim_brackets` unreachable from UI** — backend shipped, client never sent it; wiring checkbox + i18n ×6 in flight (sonnet agent).

## Top tier — converging signals

### A1. Immich webhook receiver — "Facet as Immich's scoring brain" (M) ⭐ strategic
**Evidence:** Immich v3.0.0 (2026-07-02) shipped a workflow webhook action (PR #29258, merged 2026-06-26) that POSTs asset data to any URL with a custom auth header. Immich has declined native quality scoring twice (PR #26968 closed; #22791 "rejected as opinionated"); culling request #7202 open since 2024 with maintainer sympathy and duplicates closed against it as recently as 2026-05-24. The one HN breakout in this space (309 pts) was Immich-adjacent tooling. Facet already owns the outbound half (`sync/immich.py`).
**Sketch:** new inbound endpoint (token-authed, SSRF-conscious) receiving Immich workflow webhooks → resolve asset → enqueue scan of the underlying file (shared external-library folder, path_map already exists) → on scored, push rating back through the existing sync. Docs page describing the full loop (Immich workflow → Facet → rating/album back). Touches: new `api/routers/` router or `sync/immich.py` companion, config block, docs.
**Positioning note (from competitor scan):** "local AI" is no longer a differentiator (Aftershoot CEO committed to on-device, 2026-06-01); transparency + tunability + library scale + Immich integration is the defensible story.

### A2. Shoot-type auto-detection → cull-profile pre-selection (S–M)
**Evidence:** Narrative auto-detects shoot type (2026-06-10; expanded 2026-07-30); FilterPixel still asks. Facet's `cull_profiles` resolve from a caller-supplied name (`api/routers/burst_culling.py:290`) and every inference input (moments, categories, faces, time clustering) is already in the DB.
**Sketch:** a resolver that infers the dominant genre for a scope (album/date-range) from stored moments/categories/face stats and pre-selects the profile in the auto-cull dialog (user can override; inference is a suggestion, never silent). Backend: small scoring over existing columns; client: default the profile dropdown + "suggested" badge.

### A3. Key-subject resolver + subject-aware zoom (M)
**Evidence:** three independent ships in one window — Aftershoot key-subject prioritisation (2026-05-28), Narrative Key People (2026-06-10), Narrative Smart Zoom to key subject (2026-07-30). Facet has faces, persons, and BiRefNet `subject_bbox` but no "who/what is this photo about" resolver.
**Sketch:** per-photo key-subject = named-person priority (largest/most-central known face) else saliency bbox; store nothing new (compute from existing columns); use it to (a) default the synced-zoom target in the culling lightbox, (b) badge the key person in grid/lightbox. Client-heavy; backend is a small endpoint or an extension of existing photo payloads.

### A4. Focus peaking + composition-grid overlays in the culling lightbox (S)
**Evidence:** table-stakes in Narrative/FilterPixel; Facet's lightbox has synced N-up zoom but no focus visualization. Laplacian-based edge map on the already-served image, client-side canvas overlay (no model, no backend), plus optional rule-of-thirds/golden-ratio grid lines.
**Sketch:** client-only: canvas filter over the lightbox image at ≥1:1 zoom + a grid toggle; reuses the existing overlay idiom from the saliency/eye overlay work. i18n ×6 for two toggles.

### A5. Transformers cap lift to 5.15 (M, GPU-validation gated)
**Evidence:** spec complete since 2026-07-08 (`.claude/specs/transformers-5-3-vlm-tagger-fix.md`); entire allowed `<5.3` range carries CVE-2026-4372 (7.8 high, patched exactly in 5.3.0); transformers now 5.15 — 13 minors of drift Dependabot will never propose (cap). Risk-accepted in July for lack of GPU validation.
**Sketch:** apply the spec on the branch; CPU-verifiable parts (imports, processors, config plumb) + test suite; the VLM tagging/caption inference validation needs the GPU box — ship gated exactly like the spec prescribes, with the GPU checklist in the PR description. — **pending models-research agent input on 5.x state.**

### A6. In-photo OCR text search (M)
**Evidence:** competitor scan (Excire/Peakto/Mylio momentum; PhotoPrism requests). Deferred pending models-research verdict on a suitable local OCR (license + size); FTS5 infra already exists (`photos_fts`) so storage/search side is cheap.

## Second tier

| Item | Evidence / note | Effort |
|---|---|---|
| Surface the SRCC evaluator in the viewer | competitor scan #6; scoring-transparency story | S |
| Immich docs: six API-key scopes + PUT-deprecation note (PATCH aliases absent from OpenAPI — do NOT port) | ecosystem #4, verified against spec | S |
| INTEROP.md refresh: digiKam 9.x (9.1.0, 2026-06-07), darktable XMP-reload caveat (upstream #20537), line-67 `<image>.xmp` inconsistency | ecosystem #5 | S |
| 2-frame bracket support (−3/0 pairs): needs EV-sign/clipping base selection, not position | ecosystem #6 | M |
| Card/folder ingest as a library module + CLI (`processing/ingest.py`, ~230 lines: atomic `.part`+`os.replace`, size-verify default, no rename templates — they break `(dir,stem)` RAW pairing; no card auto-detect — that's 6b's surface) | investigation: **BUILD-DIFFERENTLY**, 2 sessions; **downgrades to SKIP if wizard 6b is permanently dead — maintainer call** | M |
| Guest face self-filter on proofing albums ("show only photos of me") | competitor scan; privacy design is the blocker — needs a design pass first | M |
| Push `rating: -1` for Facet-rejected photos to Immich (v3 DTO supports -1 = rejected) | noticed during the rating-null fix; opt-in | S |
| Cull-safety docs note: LR 15.4 was pulled (2026-06-20) for a delete-rejected data-loss bug; Facet's server-side re-derivation (`excluded_by_state`, fully tested in `tests/test_cull.py`) prevents that class | competitor scan | S (docs) |

## Candidate models (verdicts, 2026-08-12 pass)

**Applied during synthesis:** venv synced to lock (pyiqa 0.1.16); `torch_dtype=`→`dtype=` shim removed at `api/routers/search.py:189`; `requirements.txt` pyiqa floor raised to `>=0.1.16` so non-lockfile installs resolve a qrealign-capable release.

| Item | Verdict | Why |
|---|---|---|
| **Q-ReAlign `qrealign-mini` 0.8B** into the extended IQA tier, replacing Q-Align | SHIP, hard-gated on a local A/B | Apache-2.0 (HF-verified), 2.21 GB, vendor SRCC 0.879–0.896 vs Q-Align 0.869; retires the S-Lab non-commercial license. No paper / no independent replication — the local A/B is the gate, all numbers are vendor claims until then. |
| **VLM-FIQA prompt** (zero-shot face quality on the already-loaded Qwen tagger) | INVESTIGATE | MIT, FG 2026, zero new weights; untested below ~4B; its metric is under published attack. |
| **Deprecate `aesthetic_v25`** | INVESTIGATE (couple to Q-ReAlign A/B) | AGPL-3.0 inside an MIT network service; unmaintained since 2024-12-18; superseded if Q-ReAlign ships. |
| Embeddings / composition / VLM upgrades | NONE | SigLIP 2 SO400M unbeaten (TIPSv2 loses zero-shot by 4.3 pts — wrong direction for tag/ExIQA prompting); SAMP-Net no successor; no in-window VLM beats Qwen3.5-2B/4B (Gemma 4 E4B measurably loses, and needs transformers ≥5.5 — blocked by the cap anyway). |
| **DSL-FIQA, GenCrop** | **CLOSED permanently** | DSL-FIQA: still no LICENSE, dead since 2024-09. GenCrop: weights "coming soon" since 2023, one commit ever. Independently confirmed twice this session. |

**Negative results (do not re-research):** SigLIP 3, `Qwen/Qwen3.5-VL-*`, InternVL 4.x, Florence-3, Pixtral 2, MetaCLIP 3, Jina CLIP v3 — none exist as of 2026-08-12. Facet's Qwen3.5-2B/4B are natively multimodal, load-test-verified. Facet has no `BitsAndBytesConfig` path at all — any "fits at 4-bit" claim carries hidden plumbing cost. License metadata routinely disagrees between HF weights and code repos (Q-ReAlign, ProCrop, DSL-FIQA) — always check both.

## Lightroom plugin — verdict: BUILD-DIFFERENTLY (brief: `investigate-lr-plugin.md`)

The July sketch ("scores as *filterable* LR metadata") is **impossible**: LR custom metadata has no numeric type — smart collections reach plugin fields only as `sdktext:` text/enum, verified against the LrC 15.1 SDK guide (2025-11-26) and unchanged since 11.4. Plugin metadata is also catalog-only (never reaches XMP/files). Reframe as a **Facet→Lightroom applier**: native stars + **pick flags** (`setRawMetadata('pickStatus', ±1)` — the real differentiator; XMP has no pick channel and `INTEROP.md` documents favourite≠pick as unfixable) + label/keywords + an **enum score band** (reusing `score_to_rating.thresholds`) for smart collections; read-only string fields explain sub-scores in the panel. Feed it a **manifest file**, not the API (Facet has no API-key mechanism; JWTs rotate; offline file wins). `--export-json` already emits ~the right payload; needs path scoping, compact output, rating columns. WildlifeAI (AI scorer plugin) independently converged on this exact design; lrc-immich-plugin is the wrong model. No batch-write API exists — default to selected/folder scope, cancellable progress, diff-before-write; 100k throughput UNVERIFIED. Effort 3.5–5 sessions, ~half unverifiable without Lightroom. **Hard condition: if the maintainer won't test in LR Classic, phases ≥2 are SKIP.** Build order: (1) manifest export — verifiable here, useful alone; (2) stars+picks plugin; (3) band/keywords/panel; (4) measure before advertising.

## Wave-2 lock (this session)

| # | Item | Agent | Files owned |
|---|---|---|---|
| W2-1 | Immich track: webhook receiver MVP (A1) + opt-in `rating:-1` rejected push + API-key-scopes doc note | opus | new `api/routers/` receiver, `sync/immich.py`, `integrations` config block, Immich docs sections |
| W2-2 | Culling UX: shoot-type auto-suggestion (A2, both ends) + focus peaking & grid overlay (A4) | opus | `api/routers/burst_culling.py`, `burst-culling.component.*`, i18n ×6 |
| W2-3 | LR phase 1: `--export-manifest` + INTEROP.md refresh (digiKam 9.x, darktable #20537 caveat, line-67 fix) | sonnet | `facet.py` export block, `processing/`, `docs/INTEROP.md` ×6 |
| W2-4 | Transformers cap lift per `.claude/specs/transformers-5-3-vlm-tagger-fix.md`, honestly gated (GPU validation itemized for the user) | opus | `requirements*.txt`, `models/vlm_tagger.py` + spec-listed sites |
| W2-5 | Docs batch: cull-safety note (LR 15.4 pull story) + SRCC-evaluator surfacing investigation (report-only unless trivial) | sonnet | `docs/` minus INTEROP.md |

**Gated on maintainer decisions (next session):** LR plugin phases 2–3 (needs LR Classic testing commitment); card-ingest module (SKIP if wizard 6b is permanently dead); Q-ReAlign A/B + aesthetic_v25 deprecation (GPU box); key-subject resolver (A3) and 2-frame brackets as stretch.

## Explicitly rejected this cycle

- **C2PA preservation** — investigation-first item only; current behaviour unverified; no user demand signal yet.
- **Visual rule builder** over the plugin engine — below the line until the plugin engine has external users.
- **Tether/LAN multi-shooter** (pixcull's lead) — hardware-bound, niche vs Facet's library-scale strengths; revisit on demand signal.

## Research gaps (carried)

- Reddit unfetchable from this environment yet is Facet's #3 referrer — a session with Reddit access is the highest-yield follow-up.
- Facet has never appeared on HN (Algolia 0 hits) — a Show HN telling the Immich-integration story (A1) is the distribution move, after A1 ships.
