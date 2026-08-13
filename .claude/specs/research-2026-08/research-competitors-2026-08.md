# Facet competitive scan — what changed May → Aug 2026

Scan date: **2026-08-12**. Previous scan: 2026-07-01. Window of interest: ~May 2026 → Aug 2026.

## Method & confidence rules

- Every factual claim below carries a URL and a date.
- **SHIPPED** = present in a dated release note / changelog / release tag. **ANNOUNCED** = publicly stated, not yet in a release artifact. **UNVERIFIED** = single source, or a secondary source only.
- Claims about *what a product's code does at runtime* are not verifiable from marketing pages; where that matters it is labelled.
- Facet-side claims (what Facet already has) were checked against this repo's source, not from memory. Files cited inline.

---

## 1. Commercial culling tools

### 1.1 Aftershoot — the big one this window

**SHIPPED 2026-05-28**: Aftershoot's largest-ever release, turning a culler into a full workflow suite (cull → RAW edit → retouch → client gallery → print sales).

- Announcement coverage: [PhotoRumors, 2026-06-06](http://photorumors.com/2026/06/06/aftershoot-the-workflow-is-now-complete-and-ai-that-works-for-you-not-against-you/) (states release date 2026-05-28); [SLR Lounge, 2026-05-29](https://www.slrlounge.com/aftershoot-complete-photographer-workflow-platform-from-culling-to-client-galleries/); [Digital Camera World, 2026-06-01](https://www.digitalcameraworld.com/tech/software/tired-of-switching-between-different-photo-editors-big-aftershoot-update-means-never-having-to-leave-as-it-adds-raw-editing-and-organizing-features); [Fstoppers, 2026-06-15](https://fstoppers.com/software/aftershoot-just-became-entire-ai-photography-workflow-903026).

Culling-specific changes (three independent sources agree):
- **Smarter duplicate/variation grouping** — burst frames and minor expression variations group together; *different crops of the same frame group separately* (intentional-variation recognition). Company claims **"~20% tighter culls"** (vendor-reported number, not independently measured — treat as marketing).
- **Cull to target** — specify the number of keepers you want ([PhotoRumors](http://photorumors.com/2026/06/06/aftershoot-the-workflow-is-now-complete-and-ai-that-works-for-you-not-against-you/), 2026-06-06).
- **Key-subject prioritisation** — the AI decides which subject(s) matter per frame and judges the frame on them.
- **Binary selection states** and an explicit UI split between **"AI Automated Cull"** vs **"AI Assisted Cull"** modes.
- Fewer sliders in the customisation menu (deliberate simplification).

**Aftershoot Galleries** (new product, beta): client proofing with favouriting + commenting, **face scanning so a guest can filter the gallery to photos of themselves**, face-based access control for multi-client deliveries, print integration (WHCC, Bay Photo, Atkins), 100 GB free during beta ([SLR Lounge](https://www.slrlounge.com/aftershoot-complete-photographer-workflow-platform-from-culling-to-client-galleries/), 2026-05-29).

Pricing ([SLR Lounge](https://www.slrlounge.com/aftershoot-complete-photographer-workflow-platform-from-culling-to-client-galleries/), 2026-05-29; [DCW](https://www.digitalcameraworld.com/tech/software/tired-of-switching-between-different-photo-editors-big-aftershoot-update-means-never-having-to-leave-as-it-adds-raw-editing-and-organizing-features), 2026-06-01): Culling $10/mo, Editing $30/mo, Retouching $20/mo, Complete $45/mo.

**Positioning signal that matters most**: CEO Harshit Dwivedi explicitly committed to **"on-device AI as opposed to cloud-based AI"** ([DCW, 2026-06-01](https://www.digitalcameraworld.com/tech/software/tired-of-switching-between-different-photo-editors-big-aftershoot-update-means-never-having-to-leave-as-it-adds-raw-editing-and-organizing-features)). **Local processing is no longer a Facet differentiator against the commercial field** — it is now table stakes. Facet's remaining structural differentiators are: self-hosted *server* (not a desktop app), open source, whole-library/archive scale rather than per-shoot, and transparent tunable weights.

**Facet mapping**: cull-to-target = **already ahead** (Facet has keeper budget + Highlights tier). Duplicate/variation grouping = **near-parity** (burst/duplicate/bracket/panorama detection with override corrections). Key-subject prioritisation = **GAP**. Guest face self-filter in shared galleries = **GAP**. Automated-vs-assisted mode split = **near-parity** (auto-cull vs manual lightbox exist, but not framed as two named modes).

### 1.2 Narrative Select — highest-cadence competitor, and the clearest gap source

Narrative's [public changelog](https://narrative.so/changelog) is the single most useful primary source in this scan. Dated entries in-window:

| Version | Date | What shipped |
|---|---|---|
| v2.1.27 | 2026-04-16 | **Auto-rate with First Pass** — writes a metadata star rating from the AI assessment; batch-switch AI Presets in Lightroom |
| v2.1.28 | 2026-05-15 | **Close-ups for non-face images** (crops to the key element — animal, object, person facing away); Fullscreen Mode; batch cropping |
| v2.1.29 | 2026-05-28 | **People Filter (beta)**; **AI First Pass extended to photos without people**, rated by sharpness; HEIC support |
| v2.1.31 | 2026-06-10 | **Key People identification** (AI flags the most likely key people with a blue icon in the Close-ups panel); **automatic shoot-type detection**; refined scene detection (fewer oversized scenes, fewer unnecessary splits) |
| v2.1.32 | 2026-06-18 | Faster zoomed navigation; scene-cover preloading; multi-card import loads all project images |
| v2.2.0 | 2026-07-16 | Zoom minimap; **filter inversion** (modifier key shows everything *except* the filter); batch crop/level/aspect; selection management |
| v2.3.0 | 2026-07-30 | German UI; **multi-destination ingest**; Sony A7 V / A7R VI RAW; **Smart Zoom jumps to the key subject when no faces are detected**; **shoot-type detection extended to Family, Maternity, Newborn, Pet, Senior**; improved "Eyes Closed" / "Mid Blink" accuracy; People Filter on by default |

**The two patterns to take seriously:**

1. **Automatic shoot-type detection** (v2.1.31, 2026-06-10; expanded v2.3.0, 2026-07-30). Narrative infers the genre from the content and adapts, rather than asking. This is now shipped in the market twice over — FilterPixel also has genre-specific models, but *asks the user to pick* ([FilterPixel](https://filterpixel.com/ai-photo-culling-software)). Narrative auto-detects. That is the differentiator.
2. **Key-subject / key-people ranking** (v2.1.31 + v2.3.0 Smart Zoom + v2.1.28 non-face close-ups). Both Narrative and Aftershoot converged on this independently in the same window. Users will now expect the app to know *who/what the photo is about* and to judge and zoom accordingly.

**Facet mapping**: scene grouping = **near-parity** (`api/routers/scenes.py` groups burst leads + standalone photos by capture-time gaps into scenes, cache-only, feeds the personal ranker). Auto-rate from AI = **near-parity** (score→stars XMP mapping exists). Person filter = **already have**. Eyes/blink quality = **already have** (per-face eyes/smile with threshold sliders). Auto shoot-type detection = **GAP** — Facet's `cull_profiles` (balanced/wedding/sports/concert/wildlife in `scoring_config.json`) are resolved from a caller-supplied name in `api/routers/burst_culling.py:290` (`_resolve_cull_profile(profile)`), never inferred. Key-subject ranking + zoom-to-subject = **GAP**.

### 1.3 Imagen — culling is now a first-class product line, not an add-on

From the [Imagen changelog](https://account.imagen-ai.com/changelog/photo/):

| Version | Date | What shipped |
|---|---|---|
| v26.9 | 2026-04-26 | Batch editing launched from culling projects; photo labelling to track batch progress |
| v26.14 | 2026-06-10 | **Face Retouch** with three styles (Clean, Polished, Refined), no masks/sliders |
| v26.15 | 2026-06-17 | **Fast Track** — set preferences once, culling and editing run as one continuous flow |
| v26.16 | 2026-06-29 | **Side-by-side comparison with zoom**; **technical-issue flags surfaced in both grid and loupe views** |

Imagen also markets **"Cull to Exact Number"** ([Imagen](https://imagen-ai.com/valuable-tips/ai-photo-selection/)) — marketing page, undated, so treat the *date* as UNVERIFIED even though the feature clearly exists.

**Facet mapping**: side-by-side compare with synced zoom = **already ahead** (fullscreen keyboard lightbox with synced N-up zoom). Cull to exact number = **already have**. Technical-issue flags surfaced in the grid = **near-parity / partial** — Facet computes every metric but the pattern of a compact "this frame has a problem" badge on the grid tile is worth auditing against `client/src/app/features/gallery`.

### 1.4 FilterPixel

- **SHIPPED 2026-04-04** (just before the window, but it frames everything since): **DeepCull**, marketed as "memory-based culling" that "thinks like you" ([FilterPixel blog index](https://filterpixel.com/blog/tag/filterpixel-updates), post dated 2026-04-04). The deep-link to the post 404s, so the *substance* of DeepCull is **UNVERIFIED** — only the title and date are confirmed.
- Genre-specific models: user selects genre (conference, sports, concert, wedding, portrait) and DeepCull loads a model trained for it; claims **Score + Reason explanations for every pick**; claims 2:58 for 3,000 photos ([FilterPixel](https://filterpixel.com/ai-photo-culling-software)). All of these are **vendor self-published comparison pages** — UNVERIFIED, and note that FilterPixel authors "best culling software" listicles that rank FilterPixel first, so its benchmark numbers should not be repeated as fact.
- 2026 incremental: ~20% faster culling, new filters (hugs, baby, kisses), improved face-orientation recognition, HEIC/PSD support ([FilterPixel](https://filterpixel.com/best-ai-photo-culling-software)) — UNVERIFIED, undated marketing page.
- Only two dated posts exist in the Apr–Aug 2026 window on the updates tag ([index](https://filterpixel.com/blog/tag/filterpixel-updates)): DeepCull (2026-04-04) and a feature walkthrough (2026-06-29).

**Facet mapping**: learned-from-you culling = **near-parity** (personal ranker from pairwise comparisons + learned keeper-ranking head). Score + Reason = **already ahead** (VLM critique with per-dimension verdicts). Genre models = **near-parity, manual selection on both sides**.

### 1.5 Optyx — no evidence of shipping in the window

- `www.optyx.app/blog` release notes stop at **v2.0.0 (2021-06-20)**; the whole post list predates 2023 ([Optyx blog](https://www.optyx.app/blog/)). `blog.optyx.app` redirect-loops.
- The only recent material is a third-party review updated **2026-05-19** ([Shotkit](https://shotkit.com/optyx-ai-photo-selection-tool/)), which states Optyx runs as a native desktop app processing locally **but still requires an internet connection for the AI analysis** — UNVERIFIED, single secondary source, and in tension with "processes images locally".
- Pricing reported at $9.99/mo Pro, free tier no longer capped at 100 photos — UNVERIFIED (secondary).

**Conclusion: no verifiable Optyx release in May–Aug 2026.** Treat as dormant/low-signal until proven otherwise.

### 1.6 Photo Mechanic — not competing on AI at all

- Latest build **2026.6 build 9175**: custom keyboard shortcuts for the IPTC Info dialog, variable evaluation in SmugMug upload paths, expanded format support ([Camera Bits](https://home.camerabits.com/photo-mechanic-update-with-new-custom-keyboard-shortcuts-avif-support-and-more/)) — date of that post not confirmed from the page itself; the [What's New page](https://home.camerabits.com/whats-new-in-photo-mechanic/) carries no dated 2026 entries. Version string UNVERIFIED as to date.
- **ANNOUNCED, not shipped**: C2PA / Content Authenticity support — "not yet in public beta, no public release timeline" as of **2026-02-26** ([PetaPixel](https://petapixel.com/2026/02/26/photo-mechanic-to-support-c2pa-giving-photographers-proof-of-authorship/)).
- Photo Mechanic ships **no AI culling, no automatic selection**. Its moat is raw speed and metadata fidelity.

---

## 2. Editors / DAMs

### 2.1 Adobe Lightroom — Assisted Culling went per-person, and shipped badly

**Baseline (pre-window, do not read as new)**: Assisted Culling launched at Adobe MAX Oct 2025; a Feb 2026 update improved blur/closed-eye/framing accuracy ([Fstoppers](https://fstoppers.com/lightroom/lightroom-classic-february-2026-update-firefly-webp-and-smarter-culling-900377)).

**SHIPPED 2026-06-18 — Lightroom Classic 15.4 / Desktop 9.4 / Mobile 11.4** ([Adobe community announcement](https://community.adobe.com/announcements-673/lightroom-classic-v15-4-is-live-cull-people-shots-faster-auto-detect-duplicates-sync-keywords-everywhere-1627070); [Adobe blog, 2026-06-15](https://blog.adobe.com/en/publish/2026/06/15/from-culling-to-compositing-new-creative-cloud-innovations-across-every-stage-of-your-workflow); [Lightroom Queen, June 2026](https://www.lightroomqueen.com/whats-new-in-lightroom-2026-06/)):

- **Faces panel in Assisted Culling** (out of early access): **per-person Eye Focus and Eyes Open scores** — a six-person group shot flags exactly which person blinked.
- **Auto-Detect Duplicates**: catalog-wide, cross-folder exact-duplicate scan that groups into stacks. Nothing is auto-deleted. Described as "requested for over a decade."
- **Stacking** that groups near-duplicates and **recommends the strongest frame**.
- **Customisable filters, dials and overrides to tune Assisted Culling aggressiveness** ([PetaPixel, 2026-06-15](https://petapixel.com/2026/06/15/adobe-adds-more-user-control-to-ai-features-inside-lightroom-and-photoshop/)).

**The cautionary tale**: 15.4 was **pulled on 2026-06-20** after a data-loss bug — using "Delete Rejected Photos" while inside the new Duplicates view deleted *everything in view*, not just the rejects. Fixed in **15.4.1, 2026-06-22** ([Lightroom Queen](https://www.lightroomqueen.com/whats-new-in-lightroom-2026-06/); forum thread corroboration UNVERIFIED — primary forum text not directly fetchable, but two independent secondary write-ups agree).

**SHIPPED 2026-08-03 — 15.5 / 9.5 / 11.5**: masking Feather/Edge, Render to DNG, Generative Expand, Animate. **No culling, face or duplicate changes** ([Lightroom Queen, Aug 2026](https://www.lightroomqueen.com/whats-new-in-lightroom-2026-08/)).

No Adobe MAX 2026 material exists in-window (MAX has not occurred as of 2026-08-12).

**Facet mapping**: per-face eyes/focus scoring = **already have** (per-face eyes/smile quality with threshold sliders — Facet reached this before Lightroom). Tunable aggressiveness = **already have** (`cull_profiles` strictness + threshold sliders). Catalog-wide duplicate detection = **already have**. Recommend-strongest-in-stack = **already have** (best-of-burst). The data-loss bug **validates Facet's existing guardrail design** — `POST /api/cull/apply` re-derives the target set server-side from the user's own `is_rejected` state and reports `excluded_by_state` rather than trusting the client's view. Adobe just shipped the exact bug that invariant prevents. Worth keeping as a regression test and, honestly, worth saying out loud in Facet's docs.

### 2.2 Capture One — AI culling as filterable metadata

**SHIPPED 2026-05-28 — Capture One 16.8** (note: **there is no "Capture One 17"** — the product is still on the 16.x line, correcting a premise in the brief) ([phototools.org](https://phototools.org/news/capture-one-16-8-enhanced-denoise-tethering)):

- **Assisted Review (Beta)** — tags images for closed eyes, missed focus and exposure problems. The tags are **filterable in the Browser, usable as Smart Album criteria, and combinable with star ratings and colour tags**. Capture One explicitly positions it as "a filtering aid rather than an automatic delete or final-selection tool," and it does not auto-apply on import ([Capture One support article](https://support.captureone.com/hc/en-us/articles/35841394167837-Assisted-Review-Beta) — existence confirmed via search index, direct fetch 403, so the exact wording is UNVERIFIED).
- **Enhanced Denoise** — new AI denoise engine that runs in the background while you keep culling; Bayer RAW only.

**SHIPPED 2026-07-15 — 16.8.4**: album syncing, mask syncing in Multi-User Sessions, batch import/sorting Actions. No new AI culling. (UNVERIFIED — single aggregated source, [release-notes index](https://support.captureone.com/hc/en-us/categories/360000430178-Release-notes) 403-blocked to direct fetch.)

**Facet mapping**: **near-parity, and the design lesson is the important part** — Capture One made AI verdicts *first-class filter dimensions* that compose with the user's own ratings, rather than a separate AI-only mode. Facet's filter sidebar already exposes metric ranges, so this is mostly a framing/UX audit rather than new capability.

### 2.3 Excire — the most culling-relevant DAM release of the window

**SHIPPED 2026-06-16 — Excire Foto 2027** ([Excire announcement](https://excire.com/en/excire-foto-2027-is-here/); [PetaPixel, 2026-06-19](https://petapixel.com/2026/06/19/excire-foto-2027-promises-a-feature-rich-and-powerful-photo-management-experience/)):

- **AI text recognition / OCR search** — find photos by text visible *inside* them (street signs, storefronts, athlete bib numbers, product labels).
- **Survey View** — a dedicated culling workspace for comparing, rating and selecting, with a **3×3 composition grid overlay and focus peaking**.
- World Map view, new visual Timeline, AI-powered filter bar, HEIC/PSD support, a second database for large catalogues, better panorama handling.

Important: the underlying aesthetics-score / eye-sharpness / sequence-grouping engine is **not new** — it shipped in Excire Foto 2025 and Excire Search 2026 (2025-09-17, [PetaPixel](https://petapixel.com/2025/09/17/ai-powered-excire-search-2026-aims-to-redefine-lightroom-workflows/)), both pre-window.

**Facet mapping**: aesthetics + eye sharpness + grouping = **near-parity/ahead**. **Focus peaking and composition-grid overlays in the culling view = GAP** (small). **In-photo OCR search = GAP.**

### 2.4 Peakto, Mylio, ACDSee, Zoner — little or nothing on culling

- **Peakto (CYME)**: **SHIPPED 2026-06-24, v2.7.10 "Mont Caroux"** — new Peakto Connect UI, stability/performance work specifically for "ingesting and running AI tasks", web-annotation propagation, video crash fix ([Apple App Store version history](https://apps.apple.com/us/app/ai-media-organizer-peakto/id1633496874?mt=12) — primary source). **No new AI culling capability**; the global AI culling + cross-library/cross-storage dedup engine is pre-window (v2.6, 2026-01-14, [PetaPixel](https://petapixel.com/2026/01/14/peakto-2-6-tracks-down-all-your-duplicate-photos-no-matter-where-they-are/)). No releases found after 2026-06-24.
- **Mylio Photos**: in-window releases are **v24.8-7901 (2026-07-28)** — new Sony ILCE-7RM6/7M5 support, DNG/JPEG XL, RAW-rendering fixes — and **v24.8-7902 (2026-08-11)** — one crash fix ([official change log](https://support.mylio.com/change-log-and-release-notes), directly fetched). **No AI culling, best-shot, face/eye or search features in the window.**
- **ACDSee**: last dated release is **19.1 on 2026-04-15** (RAW support for 10 cameras, minor fixes) — [official release notes](https://www.acdsee.com/en/support/photo-studio-ultimate/release-notes/acuw19en/), directly fetched. **No in-window release.** An "ACDSee 2027" with generative fill / object removal / portrait mode is **RUMOR — UNVERIFIED, single indirect source** (forum snippets only, primary 403, no official page, no date) — and note it is a *generative editing* move, not a culling move.
- **Zoner Studio**: **SHIPPED 2026-06-16/17, Build 696, "Summer 2026 Update"** ([PetaPixel, 2026-06-16](https://petapixel.com/2026/06/16/zoner-studios-summer-update-targets-real-world-photo-workflows/); [SLR Lounge, 2026-06-17](https://www.slrlounge.com/zoner-studios-2026-summer-update-brings-focus-stacking-panorama-stitching-and-smarter-raw-library-workflows/); [Zoner](https://www.zoner.com/en/summer-2026-update)) — Photo Stacking suite (focus stacking, exposure blending, panorama stitching, long-exposure simulation, remove-moving-objects), **improved Autostack plus a new Detect Stack** that groups bursts/series more accurately at import, a rebuilt cross-metadata Search panel, and Smart Healing. An in-app **"AI Assistant"** is mentioned by one outlet but no reachable source describes what it does — **UNVERIFIED, do not treat as a culling feature**. **No face/eye detection and no aesthetic scoring.**

---

## 3. Self-hosted OSS — the field Facet actually lives in

Repo metadata pulled live from the GitHub API on 2026-08-12.

| Project | Stars | Last push | Last release | Verdict |
|---|---|---|---|---|
| [Immich](https://github.com/immich-app/immich) | 110,289 | 2026-08-12 | v3.1.0 (2026-07-29) | Dominant, fast-moving, **no quality scoring** |
| [PhotoPrism](https://github.com/photoprism/photoprism) | 40,061 | 2026-08-11 | 2026-07-28 | Active; pluggable vision models; **no quality scoring** |
| [LibrePhotos](https://github.com/LibrePhotos/librephotos) | 8,022 | 2026-08-11 | 1.0.3 (2026-06-27) | Revitalised: monorepo + new face engine |
| [PiGallery2](https://github.com/bpatrik/pigallery2) | 2,256 | 2026-07-05 | 3.5.2 (2026-01-24) | Maintenance only |
| [Damselfly](https://github.com/webreaper/damselfly) | 1,781 | 2026-06-24 | 4.5.3 (2026-01-14) | Near-dormant |
| [HomeGallery](https://github.com/xemle/home-gallery) | 1,171 | 2026-06-25 | none in window | Maintenance only |

### 3.1 Immich v3.0.0 — Workflows + a WASM plugin system

**SHIPPED 2026-07-02** ([release discussion #29439](https://github.com/immich-app/immich/discussions/29439); [GitHub release v3.0.0](https://github.com/immich-app/immich/releases/tag/v3.0.0), published 2026-07-02).

- **Workflows (preview)** — drag-and-drop automation builder at Utilities > Workflows: a *trigger*, then a chain of *filter* and *action* steps. Both a visual editor and a JSON editor (so configs are shareable), plus premade templates. The underlying PR [#26727](https://github.com/immich-app/immich/pull/26727) **merged 2026-05-18**.
- Plugin runtime is **WebAssembly via Extism**, sandboxed, with plugins authorable in TypeScript, Rust or Go ([DeepWiki: Workflow and Plugin System](https://deepwiki.com/immich-app/immich/3.7-workflow-and-plugin-system)) — DeepWiki is auto-generated from the repo, so treat the language list as UNVERIFIED against the source.
- Triggers seen: `AssetCreate`, `AssetMetadataExtraction`. Filters shipped/added across v3.0.x–v3.1.0 include date, file type, **server file path** (v3.1.0, 2026-07-29) and **EXIF metadata string comparisons** (v3.1.0, numeric comparisons "expected to come soon").
- Other v3 headlines: non-destructive mobile editing, HLS real-time transcoding (preview), Recently Added page, integrity checks (untracked/missing/checksum-mismatch detection).
- v3.1.0 (2026-07-29) is quality-of-life only: upload wakelock, undo archive, OIDC role sync, etc.

- **A `webhook` workflow action shipped.** PR [#29258 "feat: webhook workflow action"](https://github.com/immich-app/immich/pull/29258) — verified via the API as **`merged: true`, `merged_at: 2026-06-26`**. It POSTs asset data to an arbitrary URL and supports a custom header (e.g. for authentication). This is the highest-leverage single fact in this scan; see opportunity #1.
- **OCR is now a mature, first-class Immich feature**, not an experiment: 39 OCR-titled issues/PRs since 2026-01-01, including GPU-acceleration work across OpenVINO and ROCm ([#30541](https://github.com/immich-app/immich/issues/30541), [#29560](https://github.com/immich-app/immich/issues/29560)), mobile OCR overlay positioning, copyable text on rotated pages, and rotation-precedence fixes as recently as [2026-08-09](https://github.com/immich-app/immich/pull/30682).

**The demand signal**: the [Workflow feature-request megathread #29167](https://github.com/immich-app/immich/discussions/29167) (opened **2026-06-17**, 47+ comments) shows what self-hosters want automated — CLIP/smart-search filters with similarity thresholds, person/face triggers, path regex → dynamic album creation, auto-tagging, auto-archive/trash, **auto-stacking of RAW+JPG and of burst duplicates**, dry-run before activation, cron scheduling. Curation requests are proxied through crude signals (*resolution* as a stand-in for "low quality"). **Nobody is asking Immich for aesthetic scoring — because nobody expects it there.**

**Immich has explicitly declined opinionated quality scoring.** PR [#26968 "feat(server): multi-factor quality scoring for duplicate resolution"](https://github.com/immich-app/immich/pull/26968) (opened 2026-03-17) proposed a weighted 0–100 score over pixel count, bit depth, colour gamut, Live Photo presence, compression efficiency, file size and metadata richness — purely to pick which *duplicate* to keep. Verified via the API: **`state: closed`, `merged: false`, `merged_at: null`** — it was never merged. Its own description notes a prior attempt (#22791) was "rejected as opinionated". This is the strongest evidence in the whole scan that **Facet's core value proposition is structurally safe from Immich**: the project's maintainers treat subjective ranking as out of scope, twice.

**Operational note for Facet**: Immich v3 carries breaking API changes. Facet's client (`sync/immich.py`) uses only `GET /api/server/about`, `POST /api/search/metadata`, `PUT /api/assets`, `GET /api/albums`, `POST /api/albums`, `PUT /api/albums/{id}/assets`. Cross-checked against the [v3 migration guide](https://immich.app/blog/v3-migration): the `shared`→`isShared` rename on `GET /albums` does not affect Facet (it sends no query params); the album response dropping `assets`/`owner` does not affect it (it reads only `albumName` and `id`); `page` is already sent as a Python `int` so the number→integer tightening on `POST /search/*` is fine. `PUT /albums/:id/assets` is listed with "access removed", meaning is ambiguous from the guide. **Static review says Facet's Immich sync is v3-compatible — UNVERIFIED at runtime; needs one live call against an Immich v3 instance to confirm.**

### 3.2 PhotoPrism — pluggable vision backends, still no scoring

- **SHIPPED 2026-05-23** ([release notes](https://docs.photoprism.app/release-notes/#may-23-2026)): ONNX-based face recognition **fully replaces the legacy Pigo detector** ([#5508](https://github.com/photoprism/photoprism/issues/5508)); redesigned Info Sidebar allows editing metadata/albums/labels and **manually tagging faces without leaving the fullscreen viewer** ([#4966](https://github.com/photoprism/photoprism/issues/4966), [#1548](https://github.com/photoprism/photoprism/issues/1548)); `vision.yml` now accepts mixed-case model names so **any Hugging Face, Ollama or OpenAI-compatible identifier works** ([#5594](https://github.com/photoprism/photoprism/issues/5594)); Vulkan hwaccel via FFmpeg 8; native HEIC/AVIF reader.
- **SHIPPED 2026-06-01** ([release notes](https://docs.photoprism.app/release-notes/#june-1-2026)): service release — free-disk-space threshold that halts indexing/import/upload before the volume fills ([#5613](https://github.com/photoprism/photoprism/issues/5613)).
- **SHIPPED 2026-07-28** ([release notes](https://docs.photoprism.app/release-notes/#july-28-2026)): interactive **equirectangular 360° photo/video viewing** ([#5623](https://github.com/photoprism/photoprism/issues/5623)); max thumbnail/video resolution raised to **16K** ([#5669](https://github.com/photoprism/photoprism/issues/5669)); inline multi-page PDF viewer ([#5488](https://github.com/photoprism/photoprism/issues/5488)); **GPS coordinates and face regions imported from both XMP sidecars ([#5712](https://github.com/photoprism/photoprism/issues/5712)) and embedded XMP ([#5751](https://github.com/photoprism/photoprism/issues/5751))**; camera/lens make+model editable via CLI and API ([#5663](https://github.com/photoprism/photoprism/issues/5663)); Settings reorganised with a dedicated Accessibility section.
- PhotoPrism's AI surface is **captions, labels, face recognition, NSFW detection** across three engines (built-in TensorFlow at 224px, Ollama at 720px, OpenAI at 720px), configured in `vision.yml` with run modes (auto/manual/on-index/on-schedule), sampling params and confidence thresholds ([docs](https://docs.photoprism.app/user-guide/ai/)). **The docs contain nothing on quality scoring, aesthetic ranking, culling or best-shot selection.**

**Signal**: `vision.yml` is the pattern to note — a declarative, provider-agnostic config for local/remote VLMs with per-task run modes and confidence thresholds. Facet's `vlm_backend` config is comparable; PhotoPrism's *scheduling* semantics (on-index / on-schedule) are the part Facet can learn from.

**Facet mapping**: MWG face regions in XMP = **already have** (Facet's XMP interop covers MWG faces). 360°/equirect = out of scope. Provider-agnostic VLM config = **near-parity**.

### 3.3 LibrePhotos — quietly rebuilt

- **SHIPPED 2026-06-21** ([release 2026w25](https://github.com/LibrePhotos/librephotos/releases/tag/2026w25)): moved to a **monorepo** (backend, frontend, mobile, docs, deploy in one repo with history preserved), and migrated **face recognition from dlib to InsightFace / ArcFace on ONNX Runtime, producing 512-dim embeddings**.
- Then **1.0.0 on 2026-06-26** (switch to semantic versioning), 1.0.1/1.0.2 same day (GPU image fixes), **1.0.3 on 2026-06-27** (authorization-hardening regression fix — non-admin users saw validation popups after `GET /api/user/` was narrowed to a public-safe serializer).

**Facet mapping**: Facet already uses InsightFace buffalo_l. LibrePhotos has now converged on the same stack — **Facet is at parity on face tech and ahead on everything downstream of it** (clustering UX, per-face quality, blink/smile).

### 3.4 PiGallery2, Damselfly, HomeGallery — no competitive movement

- **Damselfly**: `master` last committed **2026-01-14**; the `develop` branch shows a burst of Dockerfile/UI commits on **2026-06-24** but no release since **4.5.3 (2026-01-14)**. Effectively stalled.
- **PiGallery2**: last release **3.5.2 (2026-01-24)**; repo pushed 2026-07-05. Maintenance.
- **HomeGallery**: no release in the window; recent commits (2026-05-18 → 2026-06-22) are security hardening (proxy trust, social-tag escaping) and dependency bumps. Maintenance.

None of the three added AI culling, quality scoring or best-shot selection in the window.

---

## 4. New OSS entrants in 2026

A broad GitHub API sweep (17 query variants, sorted by stars and by recency) shows **200+ repos matching "photo culling" created or pushed in 2026** — the overwhelming majority at 0–2 stars, single-commit Tauri/Swift/Electron shells with AI-generated-looking READMEs. The niche is saturated with noise. The ones with genuine traction:

### 4.1 pixcull — the closest thing to a direct Facet competitor

[ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull) — **100★, MIT, created 2026-05-18, last push 2026-08-06**, Python + SwiftUI, macOS (Apple Silicon & Intel). Verified via the GitHub API on 2026-08-12.

Self-described: *"Local-first AI photo culling for professional photographers — 6-axis rubric, XMP/IPTC export, Lightroom & Capture One ready."* Release cadence is extreme — **v2.44.2 through v2.47.0 all shipped between 2026-08-02 and 2026-08-06**.

From its README and [v0.9 roadmap charter](https://github.com/ChrisChen667788/pixcull/blob/main/docs/ROADMAP-v0.9-charter.md) (dated 2026-05-23), features already shipped across v0.7–v0.8: A/B comparison window, **style clone V1→V2 (CLIP-based)**, **tethered live scoring**, **LAN multi-shooter collaboration**, client share links + **QR short links**, structured CSV/JSON export, EN/JA/ZH i18n, Lightroom-grade Library/Loupe UI, PDF audit export. The v0.9 charter is explicitly *not* about features — it is brand identity, motion design and a ⌘K command palette, on the self-assessment that pixcull is already "a competent product, not an iconic one".

**Overlap with Facet is substantial** (local-first, multi-axis scoring, CLIP style learning, Lr/C1 XMP round-trip, client share). **Facet is ahead on**: server/multi-user architecture, cross-platform (pixcull is macOS-only), library-scale archive features, face recognition depth, panorama/bracket handling. **pixcull is ahead on**: tethered live scoring, LAN multi-shooter sync, QR share links, and — notably — it is expanding into **video** (v2.42–v2.45 added a video cut/render chain and speaker diarization), which Facet has deliberately ruled out.

### 4.2 Other real entrants

| Repo | Stars | Created | Push | Note |
|---|---|---|---|---|
| [ProjectKestrel](https://github.com/SanjaySoniLV/ProjectKestrel) | 49 | 2025-06-18 | 2026-08-09 | Bird photography: burst→scene grouping, **sharpness ranking**, species tagging, "Culling Assistant" that moves rejects and never deletes. Microsoft Store + DMG, own domain, donations, "Perch" story-sharing companion. The most *productised* of the batch. AGPLv3. |
| [oaklensart/fixxer](https://github.com/oaklensart/fixxer) | 64 | 2025-11-10 | 2026-07-05 | CLI/TUI: Ollama/OpenAI vision for naming, **BRISQUE quality scoring**, CLIP burst grouping, SHA256-verified moves into Tier A/B/C folders. |
| [Abhash-Chakraborty/Find](https://github.com/Abhash-Chakraborty/Find) | 34 | 2025-11-03 | 2026-08-11 | Local-first image intelligence platform: FastAPI + pgvector, YOLO26-nano, BLIP, PaddleOCR, SigLIP, InsightFace, HDBSCAN. In GSSoC 2026, so it has contributor inflow. |
| [openphotos-ca/openphotos](https://github.com/openphotos-ca/openphotos) | 41 | 2025-10-13 | 2026-07-02 | Rust self-hosted platform, E2EE locked albums, iOS app. An Immich alternative, not a culler. |
| [cfelicio/ShotSieve](https://github.com/cfelicio/ShotSieve) | 7 | 2026-04-25 | 2026-07-26 | Small, but conceptually the sharpest: **"compare models on the same library before trusting one for a bigger culling pass"**, shipped as CPU/CUDA/DirectML/MPS packages. |
| [rsyncOSX/RawCull](https://github.com/rsyncOSX/RawCull) | 13 | 2026-02-19 | 2026-08-12 | Sony ARW macOS culler; candid README — the CLIP/SAM-3 AI branch needs unreleased macOS 27 betas and is currently broken. |
| [glebis/cull](https://github.com/glebis/cull) | 10 | 2026-05-13 | 2026-08-10 | "Obsidian for images": SQLite + CLIP/DINOv2 + UMAP, **MCP server for agent-assisted sorting**. |
| [prime-radiant-inc/teststrip](https://github.com/prime-radiant-inc/teststrip) | 9 | 2026-07-10 | 2026-08-08 | Explicitly "not ready for use". Catalog-first with SQLite as truth + XMP mirroring — architecturally the same philosophy as Facet's side tables. Company-backed. |

Also worth tracking though not new: [julyx10/lap](https://github.com/julyx10/lap) — **1,866★**, created 2024-08-11, pushed **2026-08-11**, Vue/Tauri, "offline-first photo manager for large local libraries", 9 languages, desktop for macOS/Windows/Linux. No aesthetic scoring, so not a scoring competitor, but by far the highest-star local-first DAM in this sweep and a benchmark for polish.

### 4.3 Hacker News, 2026

| Date | Pts/Comments | Item |
|---|---|---|
| 2026-01-08 | 2/0 | [ShutterSnap — AI cleanup of Photos.app similar photos](https://news.ycombinator.com/item?id=46542524) |
| 2026-02-03 | 1/0 | [Lap — local-first AI photo manager (Tauri + Vue 3)](https://news.ycombinator.com/item?id=46872908) |
| 2026-02-17 | 2/0 | [Lap — fast photo browsing (Rust + Tauri)](https://news.ycombinator.com/item?id=47050377) |
| 2026-03-07 | 1/0 | [Kino — FOSS Lightroom alternative with video (macOS)](https://news.ycombinator.com/item?id=47283025) |
| 2026-03-09 | 1/1 | [Pu-erh Lab — CUDA-accelerated RAW editor](https://news.ycombinator.com/item?id=47311123) |
| 2026-03-21 | 4/0 | [OpenPhotos](https://news.ycombinator.com/item?id=47464856) |
| 2026-03-26 | 3/0 | [Photo Triager — cull RAW on iPhone/iPad with XMP sidecars](https://news.ycombinator.com/item?id=47535322) |
| 2026-04-20 | 5/2 | [Local Elixir/Python pipeline curating 14,000 RAW photos](https://news.ycombinator.com/item?id=47829271) |
| 2026-07-12 | 5/0 | [Hologram — photo management and culling with Tauri](https://news.ycombinator.com/item?id=48885810) |
| 2026-01-28 | **309/124** | ["My ridiculously robust photo management system (Immich edition)"](https://news.ycombinator.com/item?id=46794971) |

**Read on this**: every 2026 Show HN in the culling space landed at 1–5 points with near-zero discussion. The one thread that *did* break out (309 pts) was about bolting tooling onto Immich. The community's centre of gravity is "improve my Immich stack", not "adopt a new dedicated culler". Two implications for Facet: (a) standalone-culler launches do not get organic attention, so distribution should lean on the Immich-adjacent crowd; (b) **"local-first / no cloud upload" is the universal pitch of every single entrant** — it no longer differentiates anything, in OSS or commercial.

---

## 5. Cross-cutting signals

1. **On-device AI is now table stakes, not a differentiator.** Aftershoot committed to it publicly ([DCW, 2026-06-01](https://www.digitalcameraworld.com/tech/software/tired-of-switching-between-different-photo-editors-big-aftershoot-update-means-never-having-to-leave-as-it-adds-raw-editing-and-organizing-features)); Narrative runs a local RAW engine; every OSS entrant leads with it. Facet must differentiate on *depth of scoring, transparency and library scale* instead.
2. **The culler is becoming the whole workflow.** Aftershoot (cull→edit→retouch→gallery→print) and Imagen (Fast Track: cull+edit as one flow, 2026-06-17) both collapsed the pipeline in the same six weeks. Facet's equivalent boundary is cull→XMP handoff to a real editor; that is a legitimate, defensible scope choice, but the market is normalising "never leave the app".
3. **"What is this photo about?" is the new frontier.** Key-people (Narrative 2026-06-10), key-subject prioritisation (Aftershoot 2026-05-28), non-face close-ups (Narrative 2026-05-15), smart zoom to key subject (Narrative 2026-07-30). Three products, one window, same idea.
4. **Genre-awareness is shifting from a setting to an inference.** FilterPixel asks; Narrative now detects (2026-06-10, expanded 2026-07-30).
5. **Automation-by-rules landed in self-hosted.** Immich Workflows (merged 2026-05-18, shipped 2026-07-02) plus a WASM plugin runtime and a merged webhook action (2026-06-26). Self-hosters will increasingly expect a rules builder in any library tool.
6. **Per-person rather than per-photo scoring became the mainstream framing.** Lightroom's Faces panel gives each person their own Eye Focus / Eyes Open verdict (2026-06-18); Capture One tags closed eyes per image (2026-05-28); Excire has per-face sharpness. Facet reached this first — the signal is that it is now *expected*, so it should be foregrounded in positioning rather than treated as an advanced feature.
7. **The trust posture has converged on "advisory, never destructive."** Adobe, Capture One and Excire all explicitly describe their culling AI as a filtering aid; Capture One says so in as many words; ProjectKestrel's culling assistant "moves rejects, never deletes." Lightroom's pulled 15.4 shows the cost of getting this wrong.
8. **In-photo OCR search crossed into table stakes.** Excire Foto 2027 shipped it as a headline (2026-06-16) and Immich has industrialised it (GPU backends, mobile overlay, 39 issues in 2026). A photo tool that cannot find the photo with the sign in it now looks dated.
6. **C2PA / Content Credentials is becoming an ecosystem-wide metadata concern.** Signing at capture ships on Leica M11/Q3/SL3, Sony A1 II/A9 III, Nikon Z8/Z9/Zf, Canon R1/R5 II, Samsung S26; Adobe reads, preserves and writes credentials; Photo Mechanic announced support 2026-02-26 ([PetaPixel](https://petapixel.com/2026/02/26/photo-mechanic-to-support-c2pa-giving-photographers-proof-of-authorship/); [C2PA adoption tracker, 2026-04-12](https://editorsweblog.org/2026/04/12/c2pa-adoption-tracker-platforms-content-credentials-2026)). Camera-body specifics are UNVERIFIED (single aggregator source). For Facet the risk is *passive*: a cull/XMP-write pipeline that silently invalidates or strips a capture signature is a correctness bug for pros.

---

## 6. Facet position summary

**Already ahead** — cull-to-target/keeper budget, synced N-up zoom compare, per-dimension VLM critique (vs FilterPixel's "Score + Reason"), transparent tunable ensemble weights, held-out SRCC evaluation of every metric against the user's own ratings (`optimization/iqa_eval.py`, `--eval-iqa-srcc`; no competitor exposes anything comparable), panorama/bracket sequence handling, self-hosted multi-user server, per-face eyes/smile scoring (reached before Lightroom's Faces panel), server-side destructive-action guardrails (the exact class of bug that pulled Lightroom 15.4).

**Near-parity** — duplicate/burst/variation grouping, scene grouping (`api/routers/scenes.py`), learned-from-you ranking, genre profiles, auto-rate to stars, XMP/MWG interop, face tech (LibrePhotos converged on the same InsightFace/ArcFace stack 2026-06-21), event/webhook plugin system (`plugins/__init__.py`), AI verdicts as filter dimensions (Capture One framing).

**Genuine gaps** — see ranked list below.

**Strategic finding**: Immich has now declined opinionated quality scoring **twice** (PR #26968 closed unmerged; #22791 "rejected as opinionated"), while simultaneously shipping a webhook workflow action that lets any external service be called on asset creation. The dominant self-hosted platform has explicitly left Facet's core competency vacant *and* built the socket to plug into it.

---

## 7. Ranked gap-closing opportunities

Ranked by (impact × evidence of market demand) ÷ effort. Effort: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ a month+.

### 1. Become the scoring brain for Immich, via its own webhook action — impact HIGH, effort **M**

The highest-leverage finding in this scan. Immich merged a **webhook workflow action on 2026-06-26** ([PR #29258](https://github.com/immich-app/immich/pull/29258), verified `merged: true`) that POSTs asset data to an arbitrary URL with a custom auth header, and shipped it in v3.0.0 on 2026-07-02. Simultaneously, Immich has refused opinionated quality scoring twice ([#26968](https://github.com/immich-app/immich/pull/26968) closed unmerged; #22791 "rejected as opinionated"). And the community's centre of gravity is demonstrably "improve my Immich stack" — the only photo thread to break out on HN in 2026 was exactly that, at 309 points ([HN](https://news.ycombinator.com/item?id=46794971)), while every standalone-culler Show HN died at 1–5 points. **Facet does not need to win attention away from Immich; it needs to be the thing Immich users bolt on.**

*Integration sketch*: Facet already owns the outbound half — `sync/immich.py` resolves assets via `POST /api/search/metadata` and pushes ratings with `PUT /api/assets`. The missing half is inbound. Add a webhook receiver router (`api/routers/immich_hook.py`) that accepts Immich's asset payload, authenticates on the shared-secret header Immich sends, maps `originalPath` through the existing `map_facet_path` path-map logic in `sync/immich.py`, and enqueues a scan/score for that single asset through `processing/scan_state.py` rather than scoring inline (the POST must return fast). On completion, the existing push path writes the rating — and optionally tags/album membership — back to Immich, closing the loop. Ship it with a documented copy-pasteable Immich workflow template (trigger `AssetCreate` → webhook → Facet) in `docs/`, because the template *is* the distribution. Guard the endpoint the way `/dav` and `/api/frame/*` already are: shared-secret only, never a user session.

*Caveat*: whether third parties can install custom **WASM plugins** into Immich is **UNVERIFIED** — the docs describe only the bundled `@immich/plugin-core`. The webhook route deliberately avoids needing that answer.

### 2. Auto-detect the shoot type and pre-select the cull profile — impact HIGH, effort **S–M**

Two vendors converged on genre-awareness, and Narrative moved it from a setting to an inference (v2.1.31 2026-06-10; expanded to Family/Maternity/Newborn/Pet/Senior in v2.3.0 2026-07-30). Facet already has all the inputs and all the outputs — only the inference is missing.

*Integration sketch*: Facet's `cull_profiles` in `scoring_config.json` (balanced/wedding/sports/concert/wildlife) are resolved purely from a caller-supplied name at `api/routers/burst_culling.py:290` via `_resolve_cull_profile(profile)`. Add a `detect_cull_profile(scope)` helper that aggregates already-stored signals over an album or scan run — tag histogram from `photo_tags`, `face_ratio`/face-count distribution, capture-time density, `category` mix — and maps them to a profile with a confidence value, reusing the same declarative rule shape as `config/category_filter.py` so the mapping stays config-driven rather than hard-coded. Surface it as a *suggestion* in `client/src/app/features/gallery/burst-culling.component.ts` ("Looks like a wedding — use the Wedding profile?") with one-click accept and never silent application, matching Facet's existing "pending correction" convention. Extend `GET /api/cull/profiles` with the detected profile + confidence rather than adding a new endpoint. This also composes with the existing `scoring_contexts` delta mechanism.

### 3. Key-subject identification and subject-aware zoom — impact HIGH, effort **M**

The single strongest convergent signal in the window: Aftershoot key-subject prioritisation (2026-05-28), Narrative Key People (2026-06-10), Narrative non-face close-ups (2026-05-15), Narrative Smart Zoom to key subject when no face is present (2026-07-30). Users will expect the app to know who the photo is about.

*Integration sketch*: Facet already stores everything needed — `faces` rows with bbox and person id, and BiRefNet saliency (`api/routers/saliency.py`, `analyzers/`). Add a key-subject resolver in `processing/scorer.py` (or a small `analyzers/key_subject.py`) that ranks faces per photo by a combination of bbox area, distance to the saliency centroid, sharpness at the face region, and recurrence of that `person_id` across the album — falling back to the saliency blob's bounding box when no face is detected. Persist as a side table (`photo_key_subject`) *not* a `photos` column, per the `INSERT OR REPLACE` invariant in CLAUDE.md. Consume it in two places: weight face-quality terms toward the key subject rather than averaging all faces, and make the lightbox zoom key (`client/src/app/features/gallery`) jump to the key-subject box instead of frame centre.

### 4. Focus peaking and composition-grid overlays in the culling lightbox — impact MED-HIGH, effort **S**

Excire made **Survey View — a culling workspace with a 3×3 composition grid and focus peaking** — a headline feature of Excire Foto 2027 (2026-06-16). It is the cheapest item on this list and it lands squarely inside Facet's strongest existing surface: the fullscreen keyboard culling lightbox with synced N-up zoom. Focus peaking in particular is what lets a human *verify* the machine's sharpness verdict at 100%, which is exactly the trust gap every "why should I believe the score" objection points at.

*Integration sketch*: pure client-side work in `client/src/app/features/gallery` — no backend, no schema, no scoring change. Render two toggleable overlays on the lightbox canvas: a composition grid (thirds, and reuse the golden-ratio/vanishing-point pattern already detected by SAMP-Net and stored per photo, so the overlay can show *the* pattern Facet actually matched rather than a generic 3×3), and a focus-peaking mask computed in a canvas/WebGL pass over the displayed image at zoom. Bind both to keyboard toggles consistent with the existing lightbox shortcuts, persist the toggle state in viewer settings. Because Facet already stores `composition_pattern`, the grid overlay is a differentiator rather than a copy — Excire draws a static 3×3; Facet can draw the line the image was actually scored against.

### 5. In-photo OCR text search — impact MED-HIGH, effort **M**

Two independent shipments in the window make this table stakes rather than a nice-to-have: Excire Foto 2027 shipped OCR search as a headline (2026-06-16), and Immich has industrialised it — 39 OCR issues/PRs in 2026 including OpenVINO and ROCm GPU backends, mobile overlay positioning, and rotation fixes as recent as 2026-08-09. Facet's search is strong on *semantics* (CLIP/SigLIP embeddings, FTS5 over captions and tags) and blind to *text in the frame* — bib numbers, signage, storefronts, jersey names, slide content.

*Integration sketch*: add an optional OCR pass as a new analyzer in `analyzers/`, invoked from `processing/multi_pass.py` so it inherits the existing VRAM-profile and batching machinery rather than inventing its own scheduling. Keep the model dependency optional and degrade silently when absent — the same contract `mediapipe` blendshapes already use. Store extracted text in a side table (`photo_ocr`), never a `photos` column, per the `INSERT OR REPLACE` rescan invariant, and feed it into the existing `photos_fts` FTS5 index alongside captions and tags so `/api/search` picks it up with no query rewrite. Expose it as a scoped filter in the search UI. Scope discipline: extract and index text only — do not build a document viewer, and do not attempt layout/overlay rendering in v1.

### 6. Surface the SRCC evaluator in the viewer — impact MED, effort **S**

ShotSieve's entire pitch is "compare models on the same library before trusting one", and every competitor's marketing invites the question "why should I believe your score". Facet already computes a *better* answer than anyone ships — `optimization/iqa_eval.py` reports held-out Spearman correlation of every stored metric (`aesthetic`, `topiq_score`, `aesthetic_iaa`, `face_quality_iqa`, `liqe_score`, `qalign_score`, `deqa_score`, `aggregate`, …) against the user's own star ratings, via `--eval-iqa-srcc`. It is CLI-only and therefore invisible to almost everyone.

*Integration sketch*: expose the existing evaluator through `api/routers/stats.py` as a cached read-only endpoint (reuse the `stats_cache` table with a TTL — this is expensive and rarely changes) and render it in `client/src/app/features/stats` as a ranked table: "how well does each metric predict *your* taste on *your* library". Allow re-running against a chosen ground-truth column. Near-zero backend work — it is a presentation layer over a finished computation — and it converts an existing hidden strength into the most credible trust-building screen in the product.

### Below the line — considered, not in the top 6

- **Guest face self-service filter on proofing albums** (Aftershoot Galleries, 2026-05-29 — guests filter a delivered gallery to photos of themselves). Real value for event work, effort **M**, and Facet owns both halves already (proofing with picks/comments/PIN, plus the face/person graph). Held back only because the privacy design is the hard part: it needs anonymous face thumbnails for self-identification rather than exposing `persons.name`, with the selection bound to the share token server-side. Would extend `api/routers/proofing.py` and the share settings in `api/routers/albums.py`. Strong candidate for the *next* cycle.
- **Visual rule builder over the existing plugin system** (Immich Workflows, 2026-07-02; megathread #29167). Facet already has the engine — `plugins/__init__.py` dispatches `on_score_complete`, `on_new_photo`, `on_burst_detected`, `on_high_score` to modules, webhooks and actions like `copy_to_folder` — but it is JSON-only. A builder over `api/routers/plugins.py` (rules as `{trigger, filters[], action}` reusing `config/category_filter.py` predicates, plus a dry-run count endpoint, all under `CONFIG_WRITE_LOCK`) is effort **M**. Ranked below opportunity #1 because integrating *with* Immich's builder beats duplicating it.
- **C2PA / Content Credentials preservation** — effort **S**, but scope it as an *investigation first*: run a camera-signed file through `processing/xmp_export.py` and the exiftool embed path and check with `exiftool` whether the manifest survives. **Whether Facet currently preserves or strips C2PA is UNVERIFIED.** Do not attempt to sign anything. Justified by capture-time signing now shipping across Leica/Sony/Nikon/Canon/Samsung bodies and Photo Mechanic's 2026-02-26 announcement, but it is hygiene, not a growth feature.

### Explicitly not recommended

- **Tethered live scoring / LAN multi-shooter sync** (pixcull v0.7–v0.8). Genuinely differentiating for event pros, but effort **L** and orthogonal to Facet's archive/library architecture.
- **Print sales, client commerce** (Aftershoot Galleries). Off-mission for a local-first self-hosted tool.
- **Video** (pixcull v2.42+, Excire, Kino). Previously and deliberately ruled out for Facet; nothing in this scan changes that.
- **Becoming an editor** (Aftershoot RAW editor, Imagen Fast Track). The market is collapsing cull→edit into one app, but Facet's XMP handoff to Lightroom/C1/darktable is the better boundary for a self-hosted tool, and competing with a full RAW editor is effort **L** against entrenched incumbents.
- **Chasing "local processing" as a differentiator in messaging.** It is now claimed by Aftershoot, Narrative, Optyx, pixcull and every OSS entrant. Lead with transparency, tunability and library scale instead.
