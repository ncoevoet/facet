# Facet ecosystem research — August 2026

Scan date: **2026-08-12**. Previous scan: 2026-07-01. Focus: changes since ~June 2026.

Method note: claims are labelled **FACT** (retrieved artefact — spec, release note, source file, API
response) or **SPECULATION** (my inference). Claims resting on one source are marked
`UNVERIFIED — needs <observation>`. Facts sourced from a subagent were re-verified by me where
they were load-bearing; those are marked **FACT (independently re-verified)**.

---

## 1. Facet's own signals

### 1.1 Repo trend

**FACT** — `gh api repos/ncoevoet/facet`, retrieved 2026-08-12:

| Metric | Value |
|---|---|
| Stars | 191 |
| Forks | 21 |
| Open issues (incl. PRs) | 1 (only Dependabot PR #88) |
| Watchers/subscribers | 3 |
| Created | 2026-02-16 |
| License | MIT |
| Homepage | https://ncoevoet.github.io/facet/ |

**FACT** — Stars by month (`stargazers` API with `star+json`):

```
2026-02:  59     2026-05:  16     2026-08:  11 (12 days)
2026-03:  15     2026-06:  24
2026-04:  10     2026-07:  56   <- 2.3x jump vs June
```

Forks are flat and low (2–6/month, 21 total). **SPECULATION:** the July spike correlates with the
v1.4.0–v1.7.1 release burst (2026-06-29 → 2026-07-08) and the BrightCoding article (2026-06-11),
but I have no attribution data proving causation.

**FACT** — 14-day traffic (`traffic/views`, `traffic/clones`, retrieved 2026-08-12):
views 1265 / 284 unique; clones 2024 / 320 unique. Clones exceed views, which is unusual and
consistent with CI/Docker pulls rather than human browsing.

**FACT** — Top referrers: Google 384 (110 uniq), github.com 307 (28), **reddit.com 46 (22)**,
chatgpt.com 38 (19), ncoevoet.github.io 25 (12), search.brave.com 13, Bing 7, DuckDuckGo 7,
doubao.com 7, claude.ai 5.

Two things worth noting:
- **reddit.com is the #3 external referrer** with 22 unique visitors in 14 days, so a Reddit thread
  is actively sending traffic. I could not identify it — `www.reddit.com` is not fetchable from this
  environment and site-scoped web searches returned only GitHub topic pages.
  `UNVERIFIED — needs a manual Reddit search, or GitHub's referral path detail which the API does not expose.`
- **chatgpt.com + claude.ai = 43 views (21 uniques)**, i.e. LLMs are recommending Facet. That is a
  discovery channel README wording can influence and analytics cannot measure.

**FACT** — Top content paths: `/` 514, **`docs/INSTALLATION.md` 91 (57 uniq)**, `/issues` 73,
`/pulls` 58, `docs/COMMANDS.md` 32, `/releases` 28, `issues/89` 21.
INSTALLATION.md is by far the most-read doc — 57 unique readers vs 254 for the repo front page, so
roughly **1 in 4 visitors goes straight to install**. That is the highest-leverage document in the repo.

### 1.2 Release cadence

**FACT** — 30 releases total; 19 since 2026-06-11. Since the last scan (2026-07-01):
v1.6.0 (07-02), v1.7.0/v1.7.1 (07-08), v1.7.2 (07-30), v1.8.0/1/2 (08-09), v1.9.0 (08-10),
v1.10.0/v1.10.1 (08-10), v1.11.0 (08-11), v1.11.1 (08-12). That is **11 releases in 6 weeks**.

### 1.3 Issues and discussions — complete inventory

**FACT** — All 18 non-PR issues ever filed are **closed**. There is no open user-facing issue.
Issues filed since 2026-06-01:

| # | Date | Reporter | Subject | State |
|---|---|---|---|---|
| 15 | 06-29 | kidroca | Docker GPU: torch.compile fails, gcc/g++ missing | closed 07-01 |
| 53 | 07-18 | jarppiko | Docker Python version conflicts (pydantic/mpmath/tokenizers) | closed 07-18 |
| 55 | 07-21 | BlueShift-16 | Deadlock: concurrent `KMeans.fit_predict()` in `_color_harmony()` | closed 07-22 |
| 65–70 | 07-30 | profucius | 6 viewer/perf bugs (metric_ranges full scan 55min, stats cache TTL, hide-bursts, failed-request restore, timeline nav) | closed 07-30 |
| 71 | 07-31 | profucius | **[FR]** `path_prefix` folder filter in gallery sidebar | closed 08-08 (PR #87) |
| 72 | 07-31 | profucius | Edition mode desync on JWT expiry | closed 08-08 |
| 73 | 08-03 | profucius | Mobile bottom filter bar cut off | closed 08-08 |
| 76 | 08-03 | profucius | Auto-retrain fires mid-rating-burst → DB locked | closed 08-08 |
| 89 | 08-09 | profucius | Question about the development process (not a bug) | closed 08-12 |

**FACT** — Only 4 discussions exist, ever. Two are active:
- **#14 "Culling"** (gansosilva, 2026-06-27; last activity 2026-08-11) — the single richest feedback thread.
- **#11** "which local LLM does facet use?" (2026-06-05) — answered.
- #5, #3 — dormant since March/June.

**FACT** — 8 external contributor PRs ever, all merged. Most recent:
#77 `feat: add Apple Silicon Metal acceleration` (aeronauty, merged 2026-08-08),
#54 (jarppiko, 07-18), #12 (cre4ture, 06-13), #9 and #8 (zhogov, 06-01 / 05-26).

### 1.4 Feedback NOT yet addressed

I checked each request against the code rather than against the maintainer's reply.

**Shipped (verified in code) — no action needed:**
- gansosilva's asks from 2026-06-28: narrative moments (`models/moment_classifier.py`),
  scene culling (`api/routers/scenes.py`), Photo-Mechanic-style loupe
  (`client/src/app/shared/utils/loupe-state.ts`), learning from culling decisions
  (`learned_scores` table + `optimization/personal_ranker.py`), **PT-BR**
  (`i18n/translations/pt.json`, 113,963 bytes vs en 103,607 — fully populated, not a stub).
- gansosilva's original question — culling filtered by album — shipped: `album_filter_clause` /
  `album_id` parameter throughout `api/routers/burst_culling.py`.
- jarppiko's proposals 1, 2, 3(inverse selection), 5 and 6 — all shipped in 1.9.0–1.11.x.
- profucius's `path_prefix` FR — shipped (PR #87).

**Open — maintainer stated these are not done (2026-08-10 / 08-11), and I confirmed in code:**

1. **`trim_brackets` is API-only.** **FACT (verified)** — it exists solely as a request-model field
   at `api/routers/burst_culling.py:128` and is consumed at line 2054. `grep` across `*.py`, `*.ts`,
   `*.html`, `*.json` finds it nowhere else except `tests/test_auto_cull.py` and one *comment* in
   `client/src/app/features/gallery/burst-culling.component.ts:1597`. There is **no config key and
   no checkbox in the auto-cull dialog** — a shipped capability that no user can reach from the UI.
   The maintainer flagged this himself twice, on 2026-08-10 and again on 2026-08-11.

2. **2-frame brackets are not detected.** **FACT (verified)** — `sequence_detection.min_frames` is
   `3` in both `scoring_config.json` and `utils/sequence.py:48`. jarppiko (2026-08-11) said his
   habitual pattern is **−3EV/0EV pairs**. The maintainer's reply confirms lowering `min_frames` to
   2 makes the *darker* frame the base (because the base is chosen by position in the EV-sorted run,
   `utils/sequence.py`), which is the wrong keeper. This is unresolved demand with a known-bad workaround.

3. **Panorama detector's documented blind spots.** **FACT** — from the maintainer's own reply
   (2026-08-11) plus `scoring_config.json`: `panorama_detection.min_frames` is `8`, so shorter
   sweeps are missed; vertical sweeps are missed by design; thresholds were calibrated on **26
   panoramas and 8 non-panoramas from the maintainer's own library only**. `utils/panorama.py:99`
   allows `min_frames` down to 2, so the tuning knob exists but is uncalibrated for other shooters.

4. **Docked details side panel requires ≥1280px** and is not offered below that
   (maintainer, 2026-08-10; reaffirmed 2026-08-11).

**Cross-cutting observation (SPECULATION):** every substantive feature request in the last 10 weeks
came from **exactly three people** — gansosilva (wedding pro), jarppiko (travel hobbyist),
profucius (10 of the 17 closed issues, per the maintainer's own count in issue #89). With 191 stars,
320 unique cloners in 14 days and 3 watchers, the feedback funnel is extremely narrow relative to
usage. The 57 unique INSTALLATION.md readers per fortnight are essentially all silent.

### 1.5 External coverage

**FACT** — BrightCoding, "Facet: The Local AI Photo Analysis Engine Developers Are Building",
2026-06-11: https://www.blog.brightcoding.dev/2026/06/11/facet-the-revolutionary-local-ai-photo-analysis-engine-developers-are-building
I found **no follow-up article**. The same blog's "20 Game-Changing Developer Tools" roundup
(2026-06-29) does not appear to feature Facet.

**Caution — this article contains factual errors about Facet.** It claims Facet provides
"extensibility through a plugin system" (there is none) and names "Microsoft's AVA" as an aesthetic
model (AVA is a dataset, not a Microsoft model; Facet uses TOPIQ). It reads as LLM-generated content
marketing. **SPECULATION:** since chatgpt.com and claude.ai are measurable referrers, inaccurate
third-party descriptions may be feeding back into what assistants tell users about Facet.

**FACT** — Hacker News: an Algolia API search for "facet photo culling" returned **no** stories or
comments about this project. Facet has never been on HN.

---

## 2. Immich API drift — ACTION REQUIRED

### 2.1 Version state

**FACT (independently re-verified)** — Current stable is **v3.1.0, published 2026-07-29**
(`gh api repos/immich-app/immich/releases/latest`). Immich is far past the 1.x era it was in when
Facet's integration was written: **v2.0.0 on 2025-10-01**, **v3.0.0 on 2026-07-02**.
Breaking changes now cluster at major boundaries with a migration post
(https://immich.app/blog/v3-migration). v3.1.0's only breaking item is dropping iOS 14 in the mobile
app — irrelevant to Facet.

### 2.2 What Facet actually calls

Read from `/home/ncoevoet/work/photoscore/sync/immich.py`:

| Call | Facet usage |
|---|---|
| `GET /api/server/about` | ping + API-key validation |
| `POST /api/search/metadata` | `{originalPath, page}` exact lookup **and** `{page}` full sweep to build a local `originalPath -> id` index |
| `PUT /api/assets` | bulk `{ids, rating, isFavorite}` |
| `GET /api/albums`, `POST /api/albums`, `PUT /api/albums/{id}/assets` | top-picks album |
| auth | `x-api-key` header |

### 2.3 Verification against the live spec

**FACT (independently re-verified)** — I downloaded
`https://raw.githubusercontent.com/immich-app/immich/main/open-api/immich-openapi-specs.json`
(`info.version` = `3.1.0`, 173 paths) and inspected the DTOs directly:

| Endpoint | Exists | `deprecated` | Required permission |
|---|---|---|---|
| `GET /server/about` | yes | false | `server.about` |
| `POST /search/metadata` | yes | false | `asset.read` |
| **`PUT /assets`** | yes | **true** | `asset.update` |
| **`PUT /assets/{id}`** | yes | **true** | `asset.update` |
| `GET /albums` | yes | false | `album.read` |
| `POST /albums` | yes | false | `album.create` |
| `PUT /albums/{id}/assets` | yes | false | **`albumAsset.create`** |

Schemas confirmed unchanged in shape:
- `AssetBulkUpdateDto`: `ids` (required), `rating`, `isFavorite`, … — Facet's payload still valid in shape.
- `MetadataSearchDto`: **`originalPath` is still a request filter**, `page` is still a plain integer
  `[1..]`. `checksum` also available as an alternative matcher.
- `CreateAlbumDto`: `albumName` (required) + `assetIds`. `BulkIdsDto`: `ids` (required).

So **path matching and album handling are safe**. Two real problems follow.

### 2.4 PROBLEM 1 — Facet sends `rating: 0`, which Immich v3 rejects

**FACT (independently re-verified, primary source).** Immich's own server-side validator, fetched
from `https://raw.githubusercontent.com/immich-app/immich/v3.1.0/server/src/dtos/asset.dto.ts`:

```ts
rating: z
  .int()
  .min(-1)
  .max(5)
  .nullish()
  .refine((v) => v !== 0, {
    error: 'Rating must be -1 (rejected), 1–5 (starred), or null (unrated); 0 is not valid',
  })
```

The OpenAPI schema carries the matching note: `x-immich-history: {version: "v3", state: "Updated",
description: "Using 0 as a rating is no longer valid."}`. Note the numeric bounds `[-1, 5]` still
*include* 0 — the rejection is a separate `.refine()`, so a schema-only check would miss this.

**FACT** — `sync/immich.py:279-280` sends exactly that value:

```python
if push_ratings and (rating is not None or prev.get("rating")):
    fields["rating"] = rating if rating is not None else 0
```

This is deliberate and documented in the comment above it (lines 267-271): a row previously pushed
as rated, which the user has since un-rated, "still gets an explicit clear — 0 / false". The module
docstring's claim that Facet "never pushes `rating: 0`" is true only for never-rated rows.

**Blast radius (FACT, traced through the module):** `update_assets` → `_request` → `urlopen` raises
`HTTPError` (a `URLError` subclass) on the 400. The `except (urllib_error.URLError, TimeoutError)`
at the end of the sync attaches `partial_summary` and **re-raises**, so:
1. the sync aborts mid-way through the `for key, ids in groups.items()` loop — groups queued after
   the retraction group are never pushed at all;
2. `_save_synced_state` is never reached, so the tracked state never advances;
3. the next sync recomputes the same retraction and fails identically.

**This is a permanent, self-perpetuating failure that begins the first time a user removes a star
rating from an already-synced photo, on any Immich ≥ v3.0.0 (2026-07-02).** It does not require an
upgrade on Facet's side to trigger — it triggers when the *user's Immich server* is upgraded.

**Fix:** send `None` instead of `0` (`.nullish()` accepts JSON `null`; `json.dumps` renders `None`
as `null`). The downstream state logic is unaffected — `bool(None)` and `bool(0)` are both `False`,
so `active["rating"]` still computes correctly. Same question should be asked of `isFavorite: false`,
which remains valid (plain boolean, no refinement).

**SPECULATION:** the reason this has not been reported is that it needs (a) an Immich ≥ 3.0.0 server,
(b) the optional Immich sync configured, and (c) a rating retraction — and Facet's user base for
this feature is likely very small.

### 2.5 PROBLEM 2 — `PUT /assets` is deprecated, but PATCH is not in the spec

**FACT (independently re-verified)** — both `PUT /assets` and `PUT /assets/{id}` carry
`"deprecated": true` in the v3.1.0 spec, with history
`{version: "v3", state: "Deprecated", replacementId: "updateAssets"}` — note the replacement
operationId is the *same*, i.e. the PATCH alias inherits the operationId.

Source: PR https://github.com/immich-app/immich/pull/28859, quoted by the subagent:
*"Phase 1 (this PR — v3): Both verbs are accepted by the server… A hidden PATCH endpoint is added
alongside each PUT… Phase 2 (v4): Drop PUT, remove `@ApiExcludeEndpoint()`, keep the same operationId."*

**Important correction to that report.** I checked the published spec myself: `/assets` exposes only
`delete`, `post`, `put`, and `/assets/{id}` only `get`, `put`. **There is no PATCH in the OpenAPI
document** — consistent with `@ApiExcludeEndpoint()`. So Facet **cannot cleanly migrate to PATCH
today**; doing so would mean coding against an endpoint Immich deliberately does not publish.

**Assessment:** this is a *watch* item, not an act-now item. PUT works today and there is no
announced v4 date. The right response is a dated note in the code and a re-check when v4 RCs appear.
`UNVERIFIED — needs an Immich v4 release or roadmap announcement to date the removal.`

### 2.6 API-key permission scopes

**FACT (from the spec's `x-immich-permission`, re-verified by me)** — a key driving Facet's sync
needs exactly: `server.about`, `asset.read`, `asset.update`, `album.read`, `album.create`,
**`albumAsset.create`**. The last is the non-obvious one — adding assets to an album is *not*
`album.update`. Facet's docs should list these six.

Granular API-key permissions: server support in PR #11824 (merged 2024-08-15); the UI to create a
scoped key shipped in v1.135.0 (2025-06-18), and `ApiKeyCreateDto.permissions` is now a required
`minItems: 1` array. `UNVERIFIED — whether keys created before scoping were backfilled to full
access; needs an Immich migration note or a live test against an upgraded server.`

Security: **CVE-2026-23896 / GHSA-237r-x578-h5mv**, API-key privilege escalation, fixed in Immich
v2.5.0 (~2026-01-27). Sourced from third-party CVE trackers only — Immich's own advisory page was
not directly retrievable. `UNVERIFIED — needs the GHSA page itself.` This is an Immich-server issue,
not a Facet one; it only matters as advice to users.

### 2.7 Positioning — Immich still has NOT shipped culling or quality scoring

This is strategically the most important finding in the section, and it is well-evidenced.

**FACT** — Immich discussion **#7202, "[Feature] Add an image quality score"**, opened 2024-02-19,
**still open**, 22 upvotes — the highest-upvoted signal I found:
https://github.com/immich-app/immich/discussions/7202
Immich maintainer **bo0tzz** commented on it (2024-05-28, 9 upvotes): *"It would also be nice to use
a score like this to (either automatically or manually) reject low-quality images."*

**FACT** — Newer requests are being closed as duplicates *of that one*, by the same maintainer:
- #24332 "[Feature] Image and Video Culling" (2025-12-02) — closed **DUPLICATE**, bo0tzz replied "#7202".
- #28580 "[Feature] Automatic 'Best Photo' / Great Shot Detection" (2026-05-23) — closed
  **DUPLICATE**, bo0tzz replied "#7202".

#24332's body specifies almost exactly Facet's culling feature set: *"Enter a special review/culling
mode / Mark a photo as flagged or rejected with one keystroke / Rate a photo with one keystroke /
View the flag and star rating from the thumbnail view / Filter images by flagged, unflagged,
rejected, rating…"*

**FACT** — Immich's only native "pick the better one" logic is the duplicates utility
(https://docs.immich.app/features/duplicates-utility/), whose auto-preselect prefers **larger file
size** and **more EXIF metadata**. No sharpness, aesthetic or technical scoring.

**FACT** — Duplicate-workflow demand is live and heavy: a GraphQL discussion search for "duplicate"
in title returns **220** discussions, with at least 8 filed in July–August 2026 alone (#30470 undo
after resolving duplicates, 2026-08-01; #30236 improved duplication workflow, 2026-07-26; #29832
mobile re-upload loops, 2026-07-11; #29810 on-demand similar lookup, 2026-07-10; #29844 weight
keepers by folder, 2026-07-12; #29480 full path when reviewing duplicates, 2026-07-03).

**Conclusion (well-supported):** two years after it was first requested, with a maintainer publicly
in favour, Immich has shipped nothing here and is actively consolidating demand into a single open
thread. Facet's core differentiator is not under threat, and the demand pool is both large and
addressable through the API Facet already speaks. This strongly corroborates roadmap item 2.4
("Facet for Immich" companion).

`UNVERIFIED — Immich's official roadmap page (next.immich.app/roadmap) is a client-side SPA and could
not be rendered; the "not planned" conclusion rests on issue/discussion state and shipped release
notes, not on a roadmap statement.`

---
## 3. Interop targets

### 3.1 darktable — plugin got EASIER

**FACT (independently re-verified via the release page)** — **darktable 5.6.0, released 2026-06-21**
(https://www.darktable.org/2026/06/darktable-5.6.0-released/). **Lua API 9.7.0** (up from 9.6.0 in
5.4.1). New in this release:
- **`darktable.ai` — a Lua AI-inference API**: tensor creation, model loading with GPU provider
  selection, image I/O (from file or from the library with the full edit pipeline applied), raw CFA
  sensor access, DNG output with EXIF preservation.
- **Lua scripts now ship bundled with darktable** rather than requiring a separate community-repo clone.
- `darktable.metadata.exists()`; Metadata-Editor custom fields exposed as `dt_lua_image_t` fields by title.
- `darktable-cli --library <path>` can read history stacks from `library.db` instead of XMP sidecars.

Pre-existing capabilities the deferred plugin would need — `register_event` (import/export hooks),
`register_storage` (custom exporter), GUI panel registration, shelling out to an external process —
remain present; no removals announced beyond the already-absorbed 9.6.0 `dt.new_action` rename.

**Verdict: EASIER.** All additive. `darktable.ai` in particular is interesting: it means a darktable
Lua plugin could in principle call inference in-process, though Facet's own architecture (a separate
scored SQLite library) does not need that.

**Caveat worth adding to INTEROP.md (FACT — two open/weakly-resolved upstream issues):**
- https://github.com/darktable-org/darktable/issues/20537 (filed 2026-03-15, **still open**):
  re-importing an already-edited image can **overwrite the XMP sidecar with a blank one**, wiping
  edit history (reported on 5.4.1/Windows).
- https://github.com/darktable-org/darktable/issues/19728: darktable does **not** reliably auto-detect
  XMP changes made by an external tool even with "look for updated XMP files on startup" enabled.
  Closed only because a user published a workaround Lua script, not because darktable shipped a fix.

`docs/INTEROP.md:67` currently says the two-way sidecar behaviour "applies the same way" for
darktable, without warning that darktable's side of the reload is unreliable. That is the one
substantive doc gap I found. `UNVERIFIED — whether Facet's exiftool merge is clobbered by darktable
5.6 specifically; needs a live round-trip test.`

**Separate doc nit (FACT, read locally):** `docs/INTEROP.md:67` writes darktable's convention as
"`<image>.xmp`" mid-sentence, then correctly says the two "agree on `<image><ext>.xmp`" at the end of
the same sentence. Lines 9 and 14 use the correct form. Cosmetic inconsistency.

### 3.2 Lightroom Classic — unchanged feasibility, WEAKER differentiation

**FACT** — Version timeline: 15.2 (2026-02-20), 15.3 (~April), **15.4 (June 2026)**, 15.4.1
(2026-06-22), **15.5 (2026-08-03, current)**.
Sources: https://www.lightroomqueen.com/whats-new-in-lightroom-2026-06/,
https://www.lightroomqueen.com/whats-new-in-lightroom-2026-08/

**FACT — Adobe's "Assisted Culling" graduated from early access in 15.4 (June 2026)**:
face-level analysis for closed/out-of-focus eyes, a split info panel (overall + per-face scores),
scores on hover in Detail view, filters for Subject Focus / eyes-detected / "Can't Tell" /
reject-exposure / accidental-capture / documents.
https://helpx.adobe.com/lightroom-classic/help/assisted-culling.html
15.4 also added Faces-panel-driven culling and **built-in duplicate detection**.
15.5 (Aug 2026) added AI mask refinement, Flatten AI Edits, Render-to-DNG — **nothing touching
metadata, XMP, ratings or the plugin SDK**.

**FACT — the SDK deprecation scare is a different product.** The **cloud "Lightroom API"** (Firefly
Services, for Lightroom mobile/cloud) reaches **end-of-life 2026-07-31**, migrating to Photoshop API v2:
https://developer.adobe.com/firefly-services/docs/lightroom/getting-started/deprecation-announcement/
This is **not** the Lua-based Lightroom *Classic* plugin SDK, which shows no deprecation notice.
`UNVERIFIED — the exact current LrC SDK version number; developer.adobe.com pages were not fetchable.`

**FACT — a pre-window change that touches Facet's RAW-naming section:** since LrC 15.0 (October
2025) Lightroom writes a **second `.ACR` sidecar** alongside the XMP for heavy edit metadata (masks,
Denoise, Super Resolution). https://helpx.adobe.com/lightroom-classic/help/create-xmp-acr-files.html
**No impact on Facet** — ratings, labels and keywords still live in the XMP sidecar, and the naming
convention is unchanged. INTEROP.md's field mapping and RAW-naming gotcha remain correct.

**Verdict: feasibility unchanged, strategic value LOWER.** The Lua SDK is alive, but Adobe now ships
per-face AI culling natively, so a Facet LrC plugin's pitch shifts from "bring AI culling to LrC" to
"bring *your tuned, local, explainable* scoring to LrC." Note that competitor **pixcull already ships
a Lightroom plugin** (§5), so this is no longer unoccupied ground.

### 3.3 Capture One — no scripting progress, new AI review

**FACT** — Current: **16.8.2, released 2026-06-25**
(https://support.captureone.com/hc/en-us/articles/37047448168093-Capture-One-16-8-2-release-notes).
`UNVERIFIED — a single low-quality aggregator referenced a 16.8.4; needs support.captureone.com.`

**FACT** — Scripting is still **AppleScript/JXA, macOS only**. No Windows scripting API, no official
cross-platform plugin SDK. The community request thread remains unresolved:
https://support.captureone.com/hc/en-us/community/posts/360009390177-Still-no-scripting-for-Windows-users
2026 additions are macOS-only (masking scripting, batch-done file paths, live-view/EXIF capture-time).

**FACT — "Assisted Review" shipped as a beta in 16.8 (2026-05-28)**: flags closed eyes, missed focus,
exposure problems; filterable in the Browser and usable in Smart Albums.
https://support.captureone.com/hc/en-us/articles/35747427882653-Capture-One-16-8-release-notes

XMP round-trip behaviour unchanged; INTEROP.md's one-way recipe and Full-Sync warning remain accurate.

**Verdict: no change.** Capture One remains un-pluggable cross-platform — the deferral is forced by
the vendor, not a Facet choice.

### 3.4 digiKam — VERSION DRIFT in Facet's docs

**FACT — digiKam is no longer on 8.x.** 
- **9.0.0 — 2026-03-08** (full Qt 6.10.1 port, redesigned UI):
  https://www.digikam.org/news/2026-03-08-9.0.0_release_announcement/
- **9.1.0 — 2026-06-07** (current stable):
  https://www.digikam.org/news/2026-06-07-9.1.0_release_announcement/
- 9.2.0 not released as of 2026-08-12; next maintenance release "planned for late 2026".

**Action:** Facet's docs and `.claude/patterns/` reference "digiKam 8.x". Should read 9.x.

**FACT — BQM Custom Script tool untouched**, so Facet's `--import-sidecars` BQM hook recipe in
`docs/INTEROP.md:53-64` remains valid. 9.0 added a G'MIC-Qt BQM processor and ExifTool-backed batch
time adjustment; 9.1's only BQM change was a bugfix (#517863).

**FACT — digiKam's XMP/MWG fidelity IMPROVED**, which is good for Facet:
9.0 fixed "Rating is not stored to all filetypes", "Face-tag export to heic-files", "XMP-mwg-rs Info
not read & written to JPG exif info", and stopped face rejection writing unwanted metadata.
9.1 fixed several rating-filter bugs and a "Write to XMP sidecar only" setting not honoured for rotation.

**FACT** — digiKam's "Image Quality Scanner" (auto-assigns Pick Labels from aesthetic scoring) is
**pre-existing** (renamed from Image Quality Sorter in 8.6, March 2025), not new. No major new AI
feature in 9.0/9.1.

### 3.5 Cross-cutting

**exiftool** — latest found is **13.59 (2026-05-27/28)**, with 2026 additions limited to new
Adobe-written XMP tags, UTF-16 support and camera/lens IDs — nothing touching `xmp:Rating`,
`xmp:Label`, `dc:subject` or MWG regions. `UNVERIFIED for Jun–Aug 2026 — exiftool.org/history.html
404'd during the session; needs a direct fetch or `exiftool -ver`.`

**MWG** — no update found for 2026. No risk to Facet's MWG-region recipe.

**C2PA / Content Credentials** — real and accelerating (**FACT**): 6,000+ members as of January 2026;
capture-side support in Leica M11-P, Nikon Z9/Z8, Sony Alpha, Samsung Galaxy S25, Google Pixel 10;
Adobe writes manifests across Creative Cloud; OpenAI attaches them to generated output.
Sources: https://en.wikipedia.org/wiki/Content_Credentials,
https://www.eyesift.com/faq/c2pa-content-credentials-2026-cryptographic-provenance-adoption/
**No mandate exists** requiring photo tools to support it — adoption is voluntary.
**SPECULATION (my inference, not a documented Facet bug):** C2PA manifests live in a JUMBF box, not
XMP, so Facet's rating/label/tag writes cannot clobber them — but `--embed-originals`, which rewrites
the file via exiftool, could in principle break a signature chain on a C2PA-signed original. Worth a
forward-looking note only; I did not test this.

---

## 4. Demand signals

**Methodology limitation, stated up front:** Reddit was **completely inaccessible** from this
environment — `WebFetch` blocks `reddit.com` and its JSON API, and `site:reddit.com` searches
returned only secondary pages. **Zero Reddit threads were retrieved.** This matters because
reddit.com is Facet's #3 referrer (§1.1). Everything below is Hacker News (via the Algolia API),
GitHub, vendor changelogs and trade press. Reddit findings are absent by necessity, not because the
search came back empty.

### 4.1 Ranked unmet demand

**#1 — Local, keyboard-driven, RAW-aware culling (highest confidence).** The evidence is not one
complaint thread but a wave of independent launches in an eight-week window:
- **Hologram** (Tauri; Pick/Reject/star, keyboard-first with auto-advance, RAW+JPEG auto-pairing,
  embedded-JPEG fast previews, AutoCull via local DINOv2) — Show HN 2026-07-12,
  https://github.com/ThatXliner/Hologram
- **Darkslide** — "keyboard-centric photo editor… killing the catalog", Show HN 2026-07-27
- **Selekt**, **ShotSelect**, **Seula** — same category, macOS-first, offline
This many teams converging on the same shape is strong evidence of unmet demand. Facet already
occupies this space; the risk is discoverability, not capability.

**#2 — Painless migration off Google Photos without losing metadata/albums.** From the **Immich 3.0**
HN thread (650 pts, 294 comments, 2026-07-02/03,
https://github.com/immich-app/immich/discussions/29439):
brewtide: *"Does anyone have any pointers on the best way to import roughly 14 Google takeout chunks
into immich?"*; luke_s: *"I went through the same path as you — I think I even landed up with 14
takeout files as well!"*

**#3 — Face recognition that actually works (accuracy, not privacy).** From the **Ente "Opening Our
Books"** HN thread (289 pts, 110 comments, 2026-07-16, https://ente.com/open/):
stavros: *"Face recognition for people never worked, no matter what I tried, for example."*
cdman: *"I had about 30 photos in it and face recognition just got completely stuck."*
Note this cuts **for** Facet: the 1.11.0 clustering-preservation fix (38% → 96% face retention) is
addressing exactly the failure users complain about elsewhere.

**#4 — Library management is the gap in RAW editors.** From the darktable HN thread (2026-07-29):
ghostly_s cites darktable's own FAQ that it "isn't a direct Lightroom replacement", calling library
management "an afterthought"; redmaple892 uses digiKam for cataloguing to compensate; buildbot notes
Capture One's "superior output quality but inferior media management". This is precisely Facet's
wedge — scoring + culling + gallery, no editing.

**#5 — Client-proofing / per-event sharing.** Ente thread, mock-possum: *"I got into Ente because I
wanted to create photo upload links on a per-event basis."* Plus Show HN **DD Photos App**
(2026-06-22) and **PicPocket** (2026-08-10). Corroborates roadmap 2.8.

**#6 — Self-hosting maintenance burden as an objection.** Ente thread, BeetleB cautions against
self-hosted photo services citing "upgrade failures, database corruption, and maintenance burden".
Relevant given INSTALLATION.md is Facet's most-read doc.

### 4.2 Probe list — honest status

| Probe | Verdict | Confidence |
|---|---|---|
| Batch culling ergonomics (keyboard, reject/keep) | **Strong demand** — §4.1 #1 | High |
| Migration off Google/Apple Photos | **Strong demand** | High |
| RAW+JPEG pairing / preview speed / tethering | Strong, but evidenced by *product features* of new entrants rather than user complaints | Medium |
| Client-proofing galleries | Moderate | Medium |
| Dedupe at scale (100k+) | Weak — one first-person account (HN, 2026-06-22: *"I have 120k photos in iCloud that I'm sure have duplicates"*) | Low–Medium |
| Face recognition **privacy** | Weak — searches surfaced general surveillance stories, not photo-tool privacy objections. Complaints found are about **accuracy** | Low |
| GPU requirement / "NAS without a GPU" | **No in-window thread found** despite targeted searches, incl. a full scan of a 171-comment NAS thread (HN 49131367, 2026-08-01) that mentions Immich on NAS but never GPU/AI | Low — a retrieval gap, not proof of absence |
| Scoring trust / explainability | **No primary community discussion found.** Nearest is vendor marketing (Selekt blog, 2026-02-08, pre-window): *"for a 2,000-image wedding, 10% disagreement means 200 images you need to verify… You lose the flow state. You're auditing rather than creating."* | Low (single vendor source, pre-window) |
| **Video** | **No signal found at all** — HN searches for video-library organisation returned zero in-window hits | High confidence in the *absence* of signal |

The video result is worth recording explicitly: **nothing in this pass puts pressure on Facet's
photo-only decision.** That decision stays informed and unchallenged.

### 4.3 Market movement

**New local-first launches (all Show HN, in-window):** Hologram (07-12), Your Own Gallery (07-17,
https://github.com/TravisBumgarner/your-own-gallery), Darkslide (07-27), DD Photos App (06-22),
PicPocket (08-10).

**Established projects:** Immich 3.0 (~07-02, 650-pt HN thread — the dominant reference point in
self-hosted photos); Ente transparency post (07-16, 289 pts); digiKam 9.1.0 (06-07); PhotoPrism
releases 05-23 / 06-01 / 07-28 (ONNX face pipeline replacing Pigo; `vision.yml` now accepts
HuggingFace/Ollama/OpenAI-compatible model names; native HEIC/AVIF).

**Commercial SaaS:** Imagen AI shipped Face Retouch AI (06-10), "Fast Track" combined cull+edit
(06-17), side-by-side compare with inline technical-issue flagging (06-29) —
https://account.imagen-ai.com/changelog/photo/. Aftershoot tiered $10–$60/mo; no controversy found.

**Correction to a common search artefact:** Canon's "Photo Culling" iOS app (PHIL engine) is **not
new** — it dates to 2021-02-11 despite surfacing in 2026 snippets.

**Read (SYNTHESIS):** the field is bifurcating into commercial cloud AI-culling SaaS iterating on
retouching/automation, and a fresh wave of small local-only keyboard-first cullers rejecting
subscriptions. Facet sits in the second cluster, which is **more crowded than it was pre-June**.

### 4.4 Direct competitor — pixcull

Not in the July roadmap's 17-product survey, and the closest thing to a direct competitor.

**FACT** — https://github.com/ChrisChen667788/pixcull: **100 stars**, 8 forks, Python, MIT, created
**2026-05-18**, last push 2026-08-06. It is #2 behind Facet (191) in the `photo-culling` GitHub
topic. Release cadence is extreme: **v2.43.3 → v2.47.0 between 2026-07-31 and 2026-08-06**.

**FACT (README claims — retrieved from the repo page, i.e. these are the project's own assertions,
which I did not functionally verify):** 6-axis rubric (technical, subject, composition, light,
moment, aesthetic); per-genre verticals (wedding, wildlife, sports, landscape, portrait, event,
journalism, commercial, still-life); local face clustering with a cross-run face library (InsightFace
ArcFace + DBSCAN); GPS clustering; burst-peak ranking; A/B compare with synced 1:1 zoom; XMP/IPTC
export for Lightroom and Capture One; **a bundled Lightroom plugin**; **tether mode** (watches a
folder for live scoring as you shoot); LAN multi-shooter collaboration; an iOS companion app; video
culling with reel assembly and transcription; CLI + web workspace. Models: U²-Net, ArcFace, scene
CNN, wedding-moment CNN, CLIP ViT-L/14, optional BLIP VLM. Claims ~1s/photo **CPU-only on an M2 Pro**.

**Why this matters (SPECULATION, clearly labelled):**
- It ships **two things Facet deferred or lacks**: a Lightroom plugin (roadmap 2.7) and tether mode
  (roadmap second-tier "card/folder ingest"). Facet's `--watch` is adjacent to tethering.
- Its **per-genre verticals** are roadmap second-tier item "genre-aware culling profiles" — now
  shipped by a competitor rather than a hypothesis.
- Its **CPU-only positioning** targets exactly the "NAS without a GPU" audience §4.2 could not find
  forum evidence for, but which Facet's VRAM-profile architecture addresses less directly.
- Facet's real differentiators remain: a **permanent multi-user library with a gallery**, the
  **pairwise personal ranker**, **narrative moments**, **panorama/bracket set detection**, and
  transparent tunable weights. pixcull appears to be a per-shoot batch tool.
- Facet is still ahead on stars (191 vs 100) and far ahead on release discipline.

### 4.5 Facet's own visibility

**FACT** — Zero HN hits for "facet photo scoring" and zero for "ncoevoet" (Algolia `nbHits: 0`).
**FACT** — One external write-up: BrightCoding, 2026-06-11, with **zero comments** — a mention with
no community reaction, and (as noted in §1.5) containing factual errors about Facet.

**SPECULATION:** Facet has never had a front-page moment. Given 191 stars are largely
organic/search-driven (Google is the #1 referrer), and Immich 3.0 drew 650 points on HN in the same
window, the distribution ceiling here is not capability.

---

## 5. Python / Angular ecosystem risk

### 5.1 Locally verified state

**FACT (read from the repo, 2026-08-12):**

| | Pin (`requirements.txt`) | **Lock (`requirements.lock.txt`, committed)** | Local venv |
|---|---|---|---|
| transformers | `>=4.57.0,<5.3` | `5.2.0` | 5.2.0 |
| pillow | `>=10.0.0` | **`12.3.0`** | 12.1.1 |
| PyJWT | `>=2.8.0` | **`2.13.0`** | 2.11.0 |
| fastapi | `>=0.100.0` | `0.141.1` | 0.141.1 |
| starlette | (transitive) | `1.4.1` | 1.4.1 |
| setuptools | `<81` | — | — |
| Angular | — | `21.2.19` (`client/package.json`) | — |

Python 3.12.3 in the venv; `pyproject.toml` `requires-python >=3.10`, classifiers stop at 3.13.

**IMPORTANT CORRECTION to the subagent's framing.** It reported the stale local venv's Pillow 12.1.1
and PyJWT 2.11.0 as CVE-exposed and implied a shipped risk. I checked the committed lock and the
Dockerfile: **`Dockerfile` line 60 installs from `requirements.lock.txt`**, and the lock on master
already pins the **patched** `pillow==12.3.0` and `PyJWT==2.13.0` — landed today in commit
`078f3b1`, "build(deps): bump the python-minor-patch group across 1 directory with 19 updates (#88)".
So **users are not exposed**; only the maintainer's local venv is stale. This is local hygiene
(`venv/bin/pip install -U pillow pyjwt`), not a release-blocking security issue.

For completeness, the advisories are real (**FACT**, GitHub Advisory DB, queried 2026-08-12):
Pillow — 12 advisories published 2026-07-20, several **high**, all fixed in 12.3.0 (heap OOB writes
in `ImageCmsTransform.apply()`, `Image.paste()`/`crop()`, `ImageFilter.RankFilter`; decompression-bomb
bypasses; `WindowsViewer.get_command()` command injection).
PyJWT — 5 advisories published 2026-06-15, incl. **high** `GHSA-xgmm-8j9v-c9wx` (public-key JWK
accepted as HMAC secret → forged HS256), all fixed in 2.13.0.

### 5.2 The one genuine, unresolved item: the transformers ceiling

**FACT (independently re-verified against the GitHub Advisory DB and the advisory text):**
**GHSA-29pf-2h5f-8g72 / CVE-2026-4372**, severity **high, CVSS 7.8**, published 2026-05-26,
updated 2026-07-01. Vulnerable range: **`< 5.3.0`**. First patched: **`5.3.0`**.

Advisory text, quoted: *"an attacker to craft a malicious `config.json` file containing the
`_attn_implementation_internal` field set to an attacker-controlled HuggingFace Hub repository ID.
When a victim loads this model using the standard `AutoModelForCausalLM.from_pretrained()` API, the
library downloads and executes arbitrary Python code from the attacker's repository with the
victim's full OS privileges… **The vulnerability bypasses the `trust_remote_code` security
mechanism**."*

Facet pins `transformers>=4.57.0,<5.3` — **no version in the allowed range is patched.** This is
structural, not drift.

**But this is already assessed and spec'd, not a new discovery.** `.claude/specs/transformers-5-3-vlm-tagger-fix.md`
(mtime 2026-07-08) records that the two Dependabot alerts were **dismissed as `tolerable_risk` on
2026-07-08**, on the documented grounds that the RCE requires loading an attacker-controlled model
and *"Facet only loads pinned trusted models from admin config/constants (verified across every
`from_pretrained()` call site — no untrusted input reaches them)."* My own check corroborates the
shape of that: 19 `from_pretrained()` sites, all taking IDs from config/constants; `trust_remote_code=True`
at 11 of them — which the advisory notes is **irrelevant**, since the bypass works regardless.

The same spec **root-causes and fixes the 5.3 incompatibility with evidence**: transformers 5.3 added
`mm_token_type_ids` (a per-token tensor) to the Qwen3.5 processor output, and
`models/vlm_tagger.py::_batch_qwen3` left-pads only `input_ids`/`attention_mask` while raw-`cat`-ing
every other key on dim 0 — so the new per-token key crashes when sequence lengths differ. The fix
(pad *all* per-token keys; cat only true vision keys) is written out and verified against real
processor output on both 5.2 and 5.3. **The only blocker recorded is that end-to-end validation needs
a GPU box; the spec was written on a CPU-only machine.**

**Assessment:** the residual risk is low *today* (needs a supply-chain compromise of a pinned HF repo,
or a user deliberately configuring an untrusted model — and Facet does invite model swapping). The
real cost is **drift**: transformers is now at **5.15.0 (2026-08-10)**, so the cap is 13 minors behind
and widening, and Dependabot is configured to never propose the lift. A spec-complete task has been
parked for five weeks.

### 5.3 Everything else — no action

**FastAPI** — latest `0.141.1` (2026-07-29); Facet is on it. No 1.0 planned. No breaking changes
found affecting `Depends()`, lifespan, `BackgroundTasks`, response models, `StaticFiles` or WebSockets.

**Starlette** — the 1.x premise is **real**: `1.0.0` shipped 2026-03-22, latest `1.6.0` (2026-08-08);
Facet resolves `1.4.1`. Breaking changes in 1.0 were the removal of `on_startup`/`on_shutdown`,
`@app.route()`/`@app.websocket_route()`, `add_event_handler()`, and requiring explicit `jinja2`.
**Facet is not exposed** — the subagent grepped for all of these and found zero hits; Facet already
uses the `lifespan=` async-context-manager pattern (`api/__init__.py`) and `StaticFiles` only.

**Pydantic** — latest stable `2.13.4` (2026-05-06); no v3 date announced. Facet resolves 2.12.5.
`UNVERIFIED — the subagent observed no Pydantic release of any kind since 2026-05-22 (11 weeks) and
could not explain it; reported as an observation only.`

**Angular** — **FACT (independently re-verified)**: Angular 22 is stable (`22.1.1`, 2026-08-07;
22.0.0 shipped 2026-06-03), and the 21.x line is still patched (`21.2.19`, 2026-07-29). Dependabot
deliberately blocks the 21→22 major, and Facet's own PR #79 (an attempted `@angular/core` 21.2.18 →
22.1.0 bump) was **closed unmerged** — consistent with that policy.
- **Security: no action needed, but zero margin.** **GHSA-jj27-h5hq-8x99 / CVE-2026-69151**, high,
  published **2026-08-03** — Angular i18n XSS via event-handler attributes. Patched versions are
  exactly `22.0.1`, **`21.2.19`**, `20.3.27`. **Facet's pin is `21.2.19` — precisely the patched
  release.** Safe today, but any rollback or stale lockfile below `.19` reintroduces it.
- **Vitest builder (`@angular/build:unit-test`) is stable**, the default for new Angular 21 projects,
  with a `migrate-karma-to-vitest` schematic. `UNVERIFIED — the exact CLI version where Karma is
  fully removed rather than deprecated could not be determined.`
- **Zoneless is stable** (since v20.2); Angular 22 makes `zone.js` fully optional. Angular 22 also
  stabilises Signal Forms and Angular ARIA. All additive — nothing forces a migration.

**torch / numpy / uvicorn / scipy** — all behind by minors only, all within Dependabot's remit.
Python 3.14 is now supported across the torch/numpy/scipy stack, so there is no version to avoid;
Facet's 3.12 is supported to Oct 2028. No action.

---

## 6. RANKED ACTIONABLE ITEMS

Ranked by (evidence strength × user impact) ÷ effort. Items already on
`.claude/specs/improvement-roadmap-2026-07.md` are deliberately excluded unless new evidence changes
their priority.

### 1. Stop Facet sending `rating: 0` to Immich — `sync/immich.py` — **S**
The only confirmed live defect found. `sync/immich.py:280` sends `rating: 0` to clear a previously
pushed rating; Immich's v3 validator rejects it outright (`.refine((v) => v !== 0)`), and because the
`HTTPError` propagates out of the group loop, the sync aborts, `_save_synced_state` never runs, and
**every subsequent sync fails identically**. Triggered by the *user's* Immich upgrade (≥ v3.0.0,
2026-07-02), not by anything Facet ships. Fix: send `None`; the state logic already treats `bool(None)`
and `bool(0)` identically. Add a regression test asserting no payload ever carries `rating == 0`.

### 2. Lift the `transformers < 5.3` cap — `requirements.txt`, `pyproject.toml`, `models/vlm_tagger.py` — **M**
Spec-complete since 2026-07-08 with a root cause proven at the processor level and a written,
forward-and-backward-compatible fix; blocked only on GPU validation. The entire allowed pin range is
vulnerable to CVE-2026-4372 (high, 7.8) — risk-accepted on sound reasoning, but the gap is now 13
minors and Dependabot will never propose the lift. Effort is one session **on a GPU box**; the work
is already designed. Follow `.claude/patterns/vlm-model-change-checklist.md`.

### 3. Surface `trim_brackets` in config and the auto-cull dialog — `api/routers/burst_culling.py`, `client/src/app/features/gallery/burst-culling.component.ts` — **S**
A shipped, tested capability no user can reach: it exists only as a request-model field (line 128),
with no config key and no UI control. The maintainer flagged this himself on 2026-08-10 **and again**
on 2026-08-11 in the same thread. Highest ratio of user-visible value to effort of anything in the
backlog, and it closes the last open thread from Facet's most engaged reporter.

### 4. Document the Immich integration's six API-key scopes and the PUT deprecation — `docs/`, `sync/immich.py` docstring — **S**
Immich now requires granular key permissions (`ApiKeyCreateDto.permissions` is a required
`minItems: 1` array). Facet's sync needs exactly `server.about`, `asset.read`, `asset.update`,
`album.read`, `album.create`, and **`albumAsset.create`** — the last being genuinely non-obvious
(adding assets to an album is not `album.update`). A user with a narrowly scoped key gets an opaque
failure. Also record that `PUT /assets` is `deprecated: true` as of Immich v3 with removal slated for
v4 — **but do not migrate to PATCH yet**: I confirmed the PATCH aliases are *absent from the published
OpenAPI spec* (`@ApiExcludeEndpoint`), so migrating today means coding against an undocumented
endpoint. This is a dated watch-note, not a port.

### 5. Refresh the interop docs — `docs/INTEROP.md` (+ `.claude/patterns/`) — **S**
Three small, verified corrections: (a) digiKam is on **9.x** (9.1.0, 2026-06-07), not 8.x — and its
XMP/MWG fidelity measurably improved in 9.0/9.1, which strengthens Facet's story; (b) add a caveat to
the darktable section that darktable's own XMP reload is unreliable upstream (issues #20537 open since
2026-03-15, and #19728 closed only via a community workaround script), since the doc currently implies
a clean two-way reload; (c) fix the `<image>.xmp` / `<image><ext>.xmp` inconsistency at
`docs/INTEROP.md:67`. Confirmed *not* needed: Lightroom's new `.ACR` sidecar does not affect ratings
or naming, and no recipe is invalidated.

### 6. Support 2-frame exposure brackets — `utils/sequence.py` — **M**
`sequence_detection.min_frames` is 3, so −3EV/0EV pairs are never detected; the maintainer confirmed
that lowering it to 2 picks the **darker** frame as base, because the base is chosen by *position* in
the EV-sorted run. This is the habitual pattern of the reporter whose last report uncovered the
226-swallowed-bracket bug — the highest-yield reporter Facet has. Doing it properly means selecting
the base by clipping analysis or EV sign rather than position, which is why this is M and not S.

**Deliberately not ranked, but worth stating:**
- **Positioning is the biggest untapped lever, and it is unchanged from July.** Immich discussion
  #7202 has been open since 2024-02-19 with 22 upvotes, a maintainer publicly in favour, and newer
  culling/best-shot requests being closed as duplicates *of it* as recently as 2026-05-24. Immich has
  shipped nothing. That validates roadmap 2.4 rather than adding to it, so it stays where it is.
- **Competitive watch: pixcull** (§4.4) went 0 → 100 stars since 2026-05-18 and ships a Lightroom
  plugin, tether mode and per-genre profiles — three things on Facet's deferred/second-tier list. Not
  an action, but it should inform how roadmap 2.7 is framed.
- **The feedback funnel is the narrowest part of the project.** 320 unique cloners in 14 days, 57
  unique INSTALLATION.md readers, and 3 people supplying essentially all feature input. The in-app
  update notifier shipped in 1.9.0 is the natural surface for a "tell me what's missing" pointer —
  but that is a product judgement, not a research finding.
- **Reddit remains unexamined** and is Facet's #3 referrer with 22 unique visitors in 14 days. A
  session with actual Reddit access would likely be the highest-yield follow-up research task.
