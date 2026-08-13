# Investigation brief — Lightroom Classic Lua plugin for Facet

Date: 2026-08-12 · Repo: `/home/ncoevoet/work/photoscore` · Branch: `feat/improvements-2026-08`
Roadmap item: `.claude/specs/improvement-roadmap-2026-07.md:51` (§2.7 — docs shipped, plugin deferred)

**Verdict: BUILD-DIFFERENTLY.** The July sketch's headline — *"Lua plugin exposing Facet scores as
filterable LR metadata"* — is **not achievable as written**. Adobe's SDK cannot give a numeric custom
field numeric filtering. But two *other* gaps in the current XMP flow are real, verified, and only a
plugin can close them. Build a "Facet → Lightroom applier", not a "score metadata provider".

---

## 0. Evidence provenance

Everything in §2 is from **primary Adobe sources obtained and read this session**, not from memory:

| Source | How obtained | Date |
|---|---|---|
| *Adobe Photoshop Lightroom Classic SDK Programmers Guide* (LrC **15.1**) | PDF downloaded, `pdftotext -layout` | PDF `CreationDate 2025-11-26`; SDK `Readme.txt` build `202512101606-1bb801a8` |
| Same guide, LrC **11.4** | ditto | PDF `CreationDate 2022-05-30` |
| LrC 15.1 **API Reference** `LrPhoto.html`, `LrCatalog.html` | downloaded, HTML-stripped | ships with the 15.1 SDK |
| `bmachek/lrc-immich-plugin` full Lua source | `gh api .../contents/...` | v4.3.2 |
| `NiyaNagi/WildlifeAI` (AI bird scores → LR) | `gh api` | — |
| Adobe's own `custommetadatasample.lrdevplugin` | `gh api` | Adobe © 2008, shipped in 15.1 SDK |

Mirrors used (Adobe's own `developer.adobe.com/lightroom-classic/` is a JS SPA that WebFetch cannot
read): `ostark/lightroom-knowhow` → `sdk-source/Manual/…SDK Guide.pdf` (11.4);
`manuzzi-photo/LightroomClassicSplitImagePlugin` → `AdobeDocs/LrC_15/…` (15.1, complete SDK drop).
File hashes were not checked, but the 11.4 and 15.1 PDFs carry Adobe's own FrameMaker/PDF-Library
producer metadata and the 15.1 text is a near-identical diff of the 11.4 text — consistent with
genuine Adobe drops, not fabrications.

**Web search budget was exhausted at the start of this session** (200/200). All web evidence above came
via WebFetch and `gh api`. Two consequences, stated honestly: AfterShoot's and Narrative's internal
mechanisms could **not** be re-verified (see §3.4), and no 2026 LR-SDK news beyond the 15.1 drop was
searched for.

---

## 1. Repo side — what exists today

### 1.1 The XMP flow (shipped, working)

`processing/xmp_export.py` (654 lines) is mature and does more than the task brief implies:

- `score_to_stars()` (l.132) maps `aggregate` → 1-5 stars via descending cut-points
  (`xmp_export.score_to_rating.thresholds`, default `[9.0, 8.0, 7.0, 5.5]`); below the lowest cut-point
  → **0 stars = "no opinion"**, deliberately not 1 star.
- `apply_score_mapping()` (l.189): any manual signal (rating/favourite/reject) wins when
  `only_when_unrated` (default true).
- `xmp_values()` (l.222): `is_rejected` → `xmp:Rating = -1` + `Label = Red`; `is_favorite` →
  `Label = Yellow`.
- Two writers: exiftool (merges, preserves `darktable:history`, unions foreign keywords) and a
  dependency-free pure-XML fallback that diverts to `<img>.facet.xmp` rather than clobber.
- Also writes `dc:description`, `lr:hierarchicalSubject` (`Category|<cat>`, `People|<name>`), and MWG
  `mwg-rs:RegionList` face regions.

### 1.2 The two documented holes the plugin could fill

Both are stated in `docs/INTEROP.md` as *known, unfixable-from-Facet's-side* limitations:

1. **The RAW sidecar naming gotcha** (`docs/INTEROP.md:9`). Facet writes `IMG_1234.CR2.xmp`;
   Lightroom expects `IMG_1234.xmp`. *"Neither app will discover a Facet-written sidecar for a
   proprietary RAW file (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — everything except DNG)."*
   → **A RAW-only Lightroom shooter gets nothing at all from Facet today.** The documented workaround
   is "shoot RAW+JPEG and use the JPEG as the interop vehicle", which is not a workaround for most
   people.
2. **Favourite ≠ Pick** (`docs/INTEROP.md:25). *"A Facet favorite writes `xmp:Label = Yellow`, which
   Lightroom shows as the Yellow color label — not the Pick flag."* XMP has no channel for LR's pick
   flag. → Users who cull by P/X flags (i.e. most Lightroom cullers) must translate by hand.

Secondary: `--embed-originals` writes into the user's JPEG/HEIC/TIFF/DNG originals. Some users will
never accept that; for them the entire non-RAW path is off too.

### 1.3 The data a plugin would consume — already exported

`facet.py:3479-3518` — **`--export-json` already exists** and emits precisely the payload a plugin
needs, per photo: `path`, `filename`, `date_taken`, `category`, `scores{aggregate, aesthetic,
comp_score, face_quality, tech_sharpness, exposure_score, color_score}`, `tags`, `camera_model`,
`lens_model`. (`--export-csv` at l.3443 is the same column set.) Documented at `docs/COMMANDS.md:71`.

Three defects for this use case, all small:
- **No path scoping.** `SELECT … FROM photos` — whole library, always. (`processing/xmp_export.py:570`
  `build_root_filter()` already exists and is exactly the missing piece.)
- **`json.dump(..., indent=2)`** — pretty-printed. At ~350 B/photo that is ~35 MB for 100k photos, to
  be parsed by a pure-Lua JSON decoder inside Lightroom.
- **No rating columns.** It omits `star_rating` / `is_favorite` / `is_rejected`, which the plugin needs
  for the pick-flag and stars mapping. It also omits `is_burst_lead` / sequence state.

### 1.4 The API surface, if the plugin went live instead of offline

- `GET /api/photo?path=…` — `api/routers/gallery.py:486`, auth = `get_optional_user` (**optional**).
  Single photo, keyed by the exact DB path. `GET /api/photos` (l.670) is the paged gallery, same
  optional auth.
- Auth for a desktop client: `POST /api/auth/login` (`api/routers/auth.py:27`) → JWT. On an open
  install (`viewer.password = ""`, the shipped default) it returns a token without a password, and the
  optional-auth endpoints work with no token at all.
- **There is no API-key mechanism.** `grep -rn "X-API-Key\|api_key" api/` returns nothing. The only
  `api_key` in the repo is *outbound* — `sync/immich.py`'s Immich key.
- The token-authed things that DO exist are all wrong-shaped for this:
  - `/api/frame/*` — static frame tokens, but the router is a **kiosk sampler**: it returns randomly
    sampled photos by signed rowid, has no path lookup, and 404s the whole feature when
    `frame.tokens` is empty (the default).
  - share-client tokens (`api/auth.py:277`) are scoped to a single album for proofing.
  - Almost every write/export endpoint is `Depends(require_edition)`.
- JWTs are bound to a password generation (`api/auth.py:42-92`): rotating `viewer.password` invalidates
  every stored token. A plugin holding a long-lived JWT breaks silently on password rotation.

**Conclusion (design question 1): read a Facet-produced manifest, not the API.** Reasons, weighed:

| | Manifest (offline file) | Live API |
|---|---|---|
| Server must be running | No | Yes |
| Auth | None needed | Store the viewer password or a JWT that dies on rotation; no API-key concept exists |
| Reachability | n/a | NAS/VPN/hostname/TLS-cert pain on a laptop |
| Freshness | Stale until re-exported | Live |
| Per-photo lookup | Parse once, hash by path | 1 HTTP round-trip per photo (LrHttp yields; 100k photos is hours) |
| Fits Facet's identity | Local-first, matches `--export-sidecars` | Introduces Facet's first inbound desktop-client auth story |
| Lua cost | Vendor `JSON.lua` (55 KB, as immich does) | Vendor `JSON.lua` **and** HTTP/auth/retry code |

The API adds an auth design problem Facet does not currently have, for freshness the user can get by
re-running one command. **Manifest wins.** (The immich plugin's live-API design is not a counter-example
— it *uploads* to a service whose whole point is being a server. Facet's DB is on the same person's
machine.)

Note a third option the brief did not list: **the plugin reads Facet's `.xmp` sidecars directly.**
This is genuinely viable — Lua has `io.open`, so the plugin can read `IMG_1234.CR2.xmp` even though
*Lightroom* will not, sidestepping the naming gotcha. But it means writing an XMP/RDF parser in Lua,
and the sidecar carries only stars/label/keywords — not `aggregate` or the sub-scores, which are the
whole point. Rejected in favour of the manifest.

---

## 2. Lightroom SDK — verified capabilities and the hard limit

### 2.1 SDK state

Current: **Lightroom Classic 15.1 SDK**, build `202512101606-1bb801a8` (10 Dec 2025); guide PDF dated
26 Nov 2025. Highest `LrSdkVersion` observed in public `Info.lua` files: `15.0` (4 hits);
`16.0`: 0 hits. No signing, notarisation, or registration is required anywhere in the guide — a plugin
is a folder named `MyPlugin.lrplugin` that the user adds in the Plug-in Manager; on macOS that suffix
makes it a bundle, and `.lrdevplugin` is the dev-time suffix (guide l.1320-1324).

### 2.2 What custom metadata can do (Adobe, 15.1 guide, ch. 4 pp. 70-76)

```
dataType  string  … The value is one of these strings:
    string — The field value must have a string value.
    enum   — … one of the allowed values specified in the values entry …
    url    — … accompanied by a button that treats the text value as a URL …

searchable  Boolean  … When true, this field is stored in a separate table and indexed for faster
            searching; this also means that the field can be chosen by a user as a search criterion
            for smart collections. Strings stored in this field must not exceed 511 bytes.

browsable   Boolean  … Use only when title is provided and searchable is true. When true, this field
            can be used as a filter in the Library metadata browser.
```

So: yes to the Metadata panel, yes to smart collections, yes to the Library filter bar. Confirmed by
Adobe's own sample (`custommetadatasample.lrdevplugin/CustomMetadataDefinition.lua`) and by both
shipping precedents (immich `MetadataProvider.lua`; WildlifeAI `MetadataDefinition.lua`, which declares
11 fields — including `wai_quality` and `wai_rating` — **all as `dataType='string'`**).

### 2.3 The hard limit (this is the finding that kills the original sketch)

Guide ch. 4, "Searching for photos by metadata values", `criteria`:

```
"allPluginMetadata"            Any searchable plug-in-defined metadata.
sdktext:plugin_id.field_name   A specific, searchable, plug-in-defined field (with datatype text or enum).
sdktext:plugin_id.*            All searchable fields defined by a specific plug-in (with datatype text or enum).
```

and `operation`:

```
• For string values: contains / contains all / contains words / does not contain / starts with /
  ends with / are empty / are not empty / is / is not
• For enumerated values: == (is), != (is not)
• For number and rating values: == != > < >= <= in ("is in range", end value in value2)
```

**The numeric operators are only reachable by built-in number/rating criteria. Plugin fields enter the
search vocabulary exclusively through the `sdktext:` namespace — "with datatype text or enum".** There
is no `sdknumber:`. A Facet aggregate of `8.7` stored in `facetAggregate` can never satisfy
`aggregate > 8` in a smart collection. It also cannot sort numerically anywhere except by accident of
lexicographic ordering.

This is **not stale doc rot**: diffing the 11.4 (May 2022) and 15.1 (Nov 2025) chapter 4 texts shows
only pagination and line-wrap differences. The same page still carries Adobe's *"limitations … which
will be addressed in future versions"* preamble — unchanged for 3.5 years and four major releases.
Treat it as permanent.

Also permanent, same page, and worth stating plainly:

> *"Values stored in custom metadata fields are stored only in Lightroom Classic's database. In the
> current release, a plug-in cannot link custom metadata fields to XMP values or save them with the
> image file."*

So plugin metadata is **catalog-only**: it does not survive export, does not round-trip to XMP, does
not reach any other app, and is lost if the user rebuilds the catalog. That is an argument for the
plugin *complementing* the XMP flow, never replacing it.

### 2.4 The two viable ways to get numeric-ish filtering

1. **An `enum` band field.** `facetBand` with values `9+ Exceptional / 8-9 Excellent / 7-8 Good /
   5.5-7 Fair / <5.5`. Enum supports `==` / `!=` in smart collections → *"Facet Band is 9+"* is a
   clean, first-class, one-click smart collection. Bands map naturally onto the star cut-points already
   in `xmp_export.score_to_rating.thresholds`, so Facet has one threshold list, not two.
2. **Zero-padded fixed-width strings** for the raw values (`"08.72"`, not `"8.72"`). Then
   `starts with "09"` selects the 9.x band, and lexicographic sort in the filter bar happens to be
   numerically correct. Ugly in the panel, but it makes the raw value both readable and coarsely
   filterable. Worth doing for `facetAggregate`.

Neither gives true range queries. Say so in the README rather than let a user discover it.

### 2.5 What the plugin CAN write that XMP cannot — verified

`LrPhoto:setRawMetadata(key, value)` (15.1 API ref, "First supported in version 2.0"; must be inside
`catalog:withWriteAccessDo` or `withProlongedWriteAccessDo`). Writable keys include:

- `rating` — *"(number) The user rating of the file (either nil or number of stars)"*
- `colorNameForLabel` — `'red' | 'yellow' | 'green' | 'blue' | 'purple' | 'none'`
- **`pickStatus` — *"(number) 1 for flag status 'picked', 0 for 'not set', -1 for 'rejected'"*, first
  supported in SDK 4.0.** ← This is the gap in `docs/INTEROP.md:25`, closed.
- plus `title`, `caption`, `headline`, the full IPTC creator/location block, `gps`, …
- keywords via `photo:addKeyword(LrKeyword)`.

Also available: `catalog:findPhotoByPath(path)` (SDK 2.0) — exact-path lookup, which is how a
manifest keyed by absolute path binds to catalog photos.

### 2.6 Performance-relevant APIs

- Bulk **read** is batched: `catalog:batchGetRawMetadata(photos, keys)`,
  `batchGetFormattedMetadata`, `batchGetPropertyForPlugin` (all SDK 3.0).
- Bulk **write is not**. Grepping every `batch*` symbol in `LrCatalog.html` + `LrPhoto.html` yields
  exactly those three — **there is no `batchSetPropertyForPlugin` and no `batchSetRawMetadata`.**
  Writes are one `setPropertyForPlugin(_PLUGIN, fieldId, value)` call per photo *per field*.
- `catalog:withProlongedWriteAccessDo{title, caption, pluginName, func}` — shows a warning, then a
  modal progress dialog, blocks the rest of the LR UI; *"Call LrTasks.yield() periodically."* Optional
  `timeoutParams`. This is the correct gate for a bulk apply.

### 2.7 Sandbox reality (relevant risks only)

From the guide + the two shipping plugins: `LrHttp` exists but *"Must be used within a task"*;
`io.open` / `io.popen` work (the community reference is explicit, and plugins rely on it); `os.execute`
is gone — `LrTasks.execute()` replaces it; there is no `package`/`module` system (`import()` for SDK
namespaces, `require()` for plugin-local files); `Info.lua` runs in a stricter environment where
`import`/`require` are unavailable. **No filesystem sandbox** — a plugin reads any path the user can
read, which is what makes the manifest approach work. Nothing here blocks the design.

---

## 3. Precedents

### 3.1 `bmachek/lrc-immich-plugin` (v4.3.2) — the cited precedent

23 Lua files. Relevant shape:

```lua
-- Info.lua
LrSdkVersion = 3.0,  LrSdkMinimumVersion = 3.0,
LrToolkitIdentifier = "lrc-immich-plugin",
LrInitPlugin = "Init.lua",
LrExportServiceProvider = { … "ExportServiceProvider.lua" … "PublishServiceProvider.lua" },
LrMetadataProvider = "MetadataProvider.lua",
LrLibraryMenuItems = { { title = "Import from Immich", file = "ImportDialog.lua" }, … },
LrPluginInfoProvider = "PluginInfo.lua",
```

Its whole `MetadataProvider.lua` is **one field** (`immichAssetId`, string, readOnly, browsable,
searchable) — the classic "private cross-reference id" use. The bulk (`ImmichAPI.lua` 41 KB,
`PublishTask.lua` 33 KB, `ExportTask.lua` 30 KB) is upload/publish machinery Facet does not need.
`Init.lua` shows the idiom: hoist every `import()` into globals once, vendor `JSON.lua`, keep the API
key in `LrPrefs.prefsForPlugin()`. `MetadataTask.lua` shows the write idiom, including
`withPrivateWriteAccessDo(fn, { timeout = 5 })` with an explanatory comment about waiting for the
catalog lock.

**Takeaway: it is the wrong precedent for the metadata half.** Copy its scaffolding
(Init/prefs/JSON/logging/PluginInfo dialog), not its architecture.

### 3.2 `NiyaNagi/WildlifeAI` — the *right* precedent

An AI bird-photo scorer that surfaces per-photo quality in LR. `LrSdkVersion = 12.0`,
`LrSdkMinimumVersion = 6.0`. It declares 11 custom fields — every score field `dataType='string',
searchable=true, browsable=true` — **plus** `LrMetadataTagsetFactory = 'Tagset.lua'` and a large
`LrPluginMenuItems` / `LrLibraryMenuItems` list (`Analyze Selected Photos`, `Force Reprocess`,
`Configure…`, `Stack Based on Scene and Quality…`). Its README describes doing exactly what §2.5
implies: *"1-5 star ratings automatically applied"*, *"automatically picks your best shots and rejects
blurry ones"*, *"Quality>80-89"* bucket keywords, hierarchical `WildlifeAI > Species > Robin`.

That an independent AI-scoring plugin converged on **string custom fields for display + native stars/
flags/labels/bucket-keywords for filtering** is the strongest available corroboration that §2.3's limit
is real and that §4's design is the one that survives contact with Lightroom.

Caveat: WildlifeAI's README is heavily marketing-styled and its badge links are placeholders
(`github.com/your-repo/...`), so treat its *claims* as unverified; its **code** is what is cited here.

### 3.3 Adobe's own sample

`custommetadatasample.lrdevplugin` (© 2008, still shipped verbatim in the 15.1 SDK) defines exactly
one field per representative type — `string` (browsable+searchable), a read-only `string`, an `enum`
with `allowPluginToSetOtherValues = true`, and a `url`. Nothing numeric. The sample being byte-identical
across 17 years of SDK releases is itself evidence about Adobe's investment level here.

### 3.4 AfterShoot / Narrative — **UNVERIFIED**

Could not be confirmed this session: `aftershoot.com` returned HTTP 403 to WebFetch,
`help.aftershoot.com` did not resolve, the Narrative help article 404'd, and `narrative.so/select`
says only *"Ship direct to Lightroom … 1-click import"* with no mechanism. Web search was unavailable.

What is on record *in this repo* (`.claude/specs/improvement-roadmap-2026-07.md:53`, citing
`aftershoot.com/blog/workflow-between-aftershoot-lightroom/`): *"AfterShoot's documented LR workflow is
literally 'write XMP, then Read Metadata from Files'."* If that still holds, both market leaders reach
Lightroom through stars/labels/keywords — i.e. through the channel Facet **already** implements — and
neither ships a custom-metadata plugin. That would make the plugin a differentiator rather than
table stakes. **Needs `UNVERIFIED — needs a successful fetch of the AfterShoot workflow doc and
Narrative's LR export doc` before it is repeated as fact.**

---

## 4. Minimal viable plugin

### 4.1 Reframed objective

Not *"expose Facet scores as filterable LR metadata"* (§2.3 forbids it). Instead:

> **Apply Facet's verdict to Lightroom's own fields, and show the reasoning in the panel.**
> Native fields (stars, pick flag, colour label, keywords, enum band) carry the *filtering*; read-only
> custom string fields carry the *explanation*.

This delivers §1.2's two documented holes and works identically for RAW-only libraries.

### 4.2 File layout

```
lr_plugin/facet.lrplugin/
  Info.lua                  LrToolkitIdentifier = 'com.facet.lightroom'
                            LrSdkVersion = 15.0, LrSdkMinimumVersion = 6.0
                            LrInitPlugin, LrMetadataProvider, LrMetadataTagsetFactory,
                            LrPluginInfoProvider, LrLibraryMenuItems (3 entries)
  Init.lua                  hoist imports to globals, prefs defaults, LrLogger  (immich idiom)
  MetadataDefinition.lua    the 8 fields below + schemaVersion
  Tagset.lua                a "Facet" tagset so the panel shows the fields grouped
  FacetManifest.lua         read + JSON-decode + index by normalised path
  PathMap.lua               facet_prefix → lightroom_prefix, separator normalisation
  ApplyTask.lua             the whole apply loop (progress, write gate, counters)
  PluginInfoDialogSections.lua  manifest path picker, path-map rows, apply-toggles
  PluginInfo.lua
  JSON.lua                  vendored (immich vendors the same 55 KB pure-Lua decoder)
  icons/
```

Nine hand-written Lua files. For scale: the immich plugin is 23 files / ~250 KB because it is a
publish service; this is a metadata-and-menu plugin.

### 4.3 Fields

Read-only, `title` set, in a "Facet" tagset. Aggregate + the 4 sub-scores that already drive the Top
Picks weighting (`aggregate 30 / aesthetic 28 / composition 18 / face_quality 24`, per `CLAUDE.md`) —
that is the defensible "top-N" cut, plus `tech_sharpness` because it is the one users argue with.

| id | dataType | searchable | browsable | value |
|---|---|---|---|---|
| `facetBand` | **enum** | ✔ | ✔ | `9+ / 8-9 / 7-8 / 5.5-7 / <5.5` — **the only clean smart-collection field** |
| `facetAggregate` | string | ✔ | ✔ | zero-padded `"08.72"` (§2.4.2) |
| `facetCategory` | string | ✔ | ✔ | `photos.category` |
| `facetAesthetic` | string | ✖ | ✖ | display only |
| `facetComposition` | string | ✖ | ✖ | display only |
| `facetFaceQuality` | string | ✖ | ✖ | display only |
| `facetSharpness` | string | ✖ | ✖ | display only |
| `facetSyncedAt` | string | ✖ | ✖ | manifest timestamp — makes "is this stale?" answerable |

`searchable` off for the four display-only fields is deliberate: each searchable field costs an extra
indexed catalog table (Adobe's own wording), and none of them can be range-queried anyway.
`allowPluginToSetOtherValues = true` on the enum, so a threshold change can't hard-error a Lua write.

### 4.4 Native writes (the actual value), each user-toggleable

| Facet state | LR write | Why it matters |
|---|---|---|
| `aggregate` → `score_to_stars` | `setRawMetadata('rating', n)` | same thresholds as XMP — one source of truth |
| `is_favorite` | `setRawMetadata('pickStatus', 1)` | **impossible via XMP** — `docs/INTEROP.md:25` |
| `is_rejected` | `setRawMetadata('pickStatus', -1)` + `colorNameForLabel='red'` | ditto |
| `category` | `addKeyword` under a `Facet > Category > …` root | hierarchical, filterable, exportable |
| band | `addKeyword` under `Facet > Band > 8-9` | survives export, unlike custom metadata (§2.3) |

Default all toggles **off except stars**, and never overwrite a non-nil existing `rating`/`pickStatus`
unless the user ticks "overwrite my manual picks" — mirroring `only_when_unrated` in
`xmp_export.score_to_rating`, so the plugin and the XMP path behave the same way.

### 4.5 Ingest + trigger

Menu items under `Library ▸ Plug-in Extras`:
1. **`Facet: Apply scores to selected photos`** (`enabledWhen='photosSelected'`) — the default path.
2. **`Facet: Apply scores to this folder`**.
3. **`Facet: Settings…`** (also reachable from the Plug-in Manager).

Flow: read manifest → build `path → record` map → `catalog:getTargetPhotos()` →
`batchGetRawMetadata(photos, {'path','rating','pickStatus'})` (one call) → map each LR path back
through `PathMap` → `withProlongedWriteAccessDo` → per photo `setPropertyForPlugin` ×8 (+ native
writes) → `LrTasks.yield()` every N → report `applied / not-in-manifest / skipped-manual`.

No "sync the whole catalog" button. §5.3 explains why.

### 4.6 Facet-side changes

| File | Change |
|---|---|
| `facet.py` (~l.1920 arg group, ~l.3479 handler) | `--export-manifest [PATH]`: accepts a directory scope (reuse `processing/xmp_export.build_root_filter`), adds `star_rating/is_favorite/is_rejected` + `is_burst_lead` to the SELECT, emits **compact** JSON (`separators=(',',':')`, no `indent`) with a `{"version":1,"generated_at":…,"photos":[…]}` envelope. Leave `--export-json` untouched (it is a documented user-facing format). |
| `tests/test_export.py` | scope filter, compact output, envelope keys, rating columns present |
| `docs/COMMANDS.md` | one row next to l.71 |
| `docs/INTEROP.md` | a "Lightroom plugin" section under §Lightroom Classic, explicitly stating the two things it fixes **and** that plugin metadata is catalog-only (§2.3) and cannot range-filter (§2.3) |
| `docs/{fr,de,it,es,pt}/{COMMANDS,INTEROP}.md` | per `.claude/patterns/i18n-sync.md` — 10 files |
| `README.md` (+5 translations) | one line in the interop list |
| `lr_plugin/README.md` | install steps, the honest limits |

No API change. No new endpoint. No new auth. That is the point.

### 4.7 Effort

| Phase | Sessions | Verifiable by an agent? |
|---|---|---|
| Facet `--export-manifest` + tests + docs/i18n | 1 | ✔ pytest |
| Plugin Lua (9 files) | 1.5-2 | ✖ — no Lua/LR runtime here; syntax only, via the SDK's bundled `luac` |
| Real-run debugging in LR Classic (mac + win paths, 1k-photo folder) | 1-2 | ✖ — **requires the user to own and drive LR Classic** |

**3.5-5 sessions**, of which roughly half cannot be verified without the user at a Lightroom install.

---

## 5. Risks

**5.1 Unverifiable by the agent — the biggest one.** There is no Lightroom Classic (and no Lua) in this
environment. Every runtime claim about the plugin would be `UNVERIFIED` until the user tests it. The
`.lrplugin` can be syntax-checked with the `luac` binaries Adobe ships in the SDK, and nothing more.
Do not start this unless the user is willing to be the test harness.

**5.2 Path mapping is mandatory, not a nicety.** Facet stores the *Facet host's* absolute paths
(`/volume1/photos/…` on a NAS); Lightroom holds the *desktop's* (`Z:\photos\…`, `/Volumes/photos/…`).
`api/config.py:365 map_disk_path()` exists but maps DB→*server*-local for serving files — wrong
direction, wrong host. The plugin needs its own prefix-pair preference, precisely like
`sync/immich.py`'s `immich.path_map`. Also needs `\`↔`/` normalisation and case-insensitive matching on
Windows (`findPhotoByPath` takes a `caseSensitivity` argument — use it). Get this wrong and the plugin
silently matches zero photos, which is the single most likely first-run failure.

**5.3 Catalog write throughput — `UNVERIFIED, needs a measurement`.** No batch-write API exists (§2.6).
Eight custom fields × 100k photos = 800k individual `setPropertyForPlugin` calls, plus native writes,
inside a gate that **blocks the entire Lightroom UI**. I have no measured per-call cost and will not
invent one. Mitigations, in order: default to selected photos; folder-scoped as the widest option;
`withProlongedWriteAccessDo` with a cancellable `LrProgressScope`; `LrTasks.yield()` every ~100 photos;
skip writes whose value is unchanged (`batchGetPropertyForPlugin` first — it *is* batched); write
`searchable` fields last. Measure on a real 10k folder before promising anything about 100k.

**5.4 Catalog-only, non-portable data (§2.3).** Custom metadata never reaches XMP, exports, or another
machine, and dies with a catalog rebuild. This is why §4.4 also writes *keywords* — those survive.
It must be said out loud in the docs or it becomes a bug report.

**5.5 Schema churn.** Changing `searchable` on a field requires bumping that field's `version`
(Adobe: *"If you make a change to a field definition that is incompatible with the previous definition
(for example, changing the value of `searchable`), you must bump the field's version number"*), and
`schemaVersion` + `updateFromEarlierSchemaVersion` for the set. Get the field list right on day one;
migrations here are user-visible and run inside a write gate.

**5.6 Distribution — a non-risk.** No signing, no notarisation, no Adobe review. Ship the
`facet.lrplugin` folder in the repo and in the GitHub release; the user adds it in the Plug-in Manager.
Only macOS quirk: `.lrplugin` becomes a bundle in Finder, so zip it rather than expecting a folder copy.

**5.7 Scope creep into a publish service.** The immich precedent makes "and it could also export/publish
to Facet" tempting. That is a different, much larger product (its `PublishTask.lua` alone is 33 KB) and
Facet already has `/dav`, the frame API, and Immich push. Out of scope.

---

## 6. Verdict

**BUILD-DIFFERENTLY**, and only if the user will test it in Lightroom.

**Do not build** the July sketch. "Filterable LR metadata" from numeric scores is impossible: plugin
fields reach the search vocabulary only as `sdktext:` text-or-enum, and numeric operators belong to
built-in criteria alone (§2.3, verified in both the 11.4 and 15.1 guides).

**Do build** a Facet→Lightroom *applier*, justified by two gaps this repo already documents as
unfixable from the XMP side:
- RAW-only Lightroom libraries get **nothing** today (`docs/INTEROP.md:9`). The plugin reads Facet's own
  manifest and writes into the catalog, so the naming mismatch stops mattering.
- Facet's favourite/reject cannot become LR's Pick/Reject flag over XMP (`docs/INTEROP.md:25`).
  `setRawMetadata('pickStatus', ±1)` does exactly that (§2.5).

Plus, for free: no `--embed-originals` writing into originals, no "Read Metadata from Files" step that
overwrites catalog-side edits, and a panel showing *why* Facet scored a frame the way it did.

**If the user will not test in Lightroom, SKIP.** An untestable plugin is worse than the honest XMP
recipe already shipped in `docs/INTEROP.md`.

### Suggested build order (each phase independently useful)

1. `--export-manifest` + tests + docs. Ships value alone (any tool can consume it). Fully verifiable here.
2. Plugin phase 1: metadata provider + tagset + apply-to-selection writing **stars and pick flags only**.
   That is the whole differentiator, in the smallest plugin that can carry it.
3. Plugin phase 2: enum band, keywords, sub-score panel fields, folder scope.
4. Measure §5.3 on a real folder before advertising any catalog size.
