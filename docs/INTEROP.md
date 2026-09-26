# Editor Interop Recipes

> 🌐 **English** · [Français](fr/INTEROP.md) · [Deutsch](de/INTEROP.md) · [Italiano](it/INTEROP.md) · [Español](es/INTEROP.md) · [Português](pt/INTEROP.md) · [简体中文](zh/INTEROP.md)

Practical, step-by-step recipes for round-tripping Facet's ratings, labels, and tags with the external editors and DAM tools people actually use. This page assumes you already know *that* Facet writes XMP — see [Commands — Preview & Export](COMMANDS.md#preview--export) for the full `--export-sidecars` / `--import-sidecars` flag reference and the field mapping (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## The RAW sidecar naming gotcha

Facet names a sidecar `<image><ext>.xmp` — e.g. `IMG_1234.CR2.xmp` next to `IMG_1234.CR2` — the same convention darktable and digiKam use. **Lightroom Classic and Capture One expect the opposite: `IMG_1234.xmp`, with the raw extension stripped.** Neither app will discover a Facet-written sidecar for a proprietary RAW file (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — everything except DNG), and Facet's own `--import-sidecars` won't find a sidecar an Adobe-ecosystem app wrote for the same RAW either. This is a naming mismatch between ecosystems, not a bug on either side.

It does **not** affect:
- **JPEG, HEIC, TIFF, PNG, DNG** — pass `--embed-originals` and Facet writes the metadata *into the file itself* (via exiftool), so there is no sidecar name for Lightroom/Capture One to miss.
- **digiKam** — checks both naming conventions and finds Facet's sidecar either way (see [digiKam](#digikam) below).
- **darktable** — uses the same `<image><ext>.xmp` convention as Facet (see [darktable](#darktable) below).

**GIF, WebP, BMP and AVIF are the exception — the mismatch hits them hardest.** They sit outside Facet's embeddable set, so `--embed-originals` does nothing for them and their only round-trip vehicle is an XMP sidecar carrying Facet's naming (`photo.webp.xmp`). The mismatch above therefore applies to these four exactly as it does to proprietary RAW: digiKam and darktable find the sidecar, Lightroom Classic and Capture One do not.

So for a Lightroom or Capture One workflow: use `--embed-originals` for anything in the embeddable set (JPEG, HEIC, TIFF, PNG, DNG), and expect the sidecar round-trip to be silent (no error, just nothing read) for proprietary RAW files — and for GIF, WebP, BMP and AVIF. If you shoot RAW+JPEG, the JPEG companion is the practical interop vehicle — the RAW rides along on disk, untouched, while Facet's database keeps the authoritative rating.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (add a path to scope it, e.g. `--export-sidecars /photos/2026-wedding`). Add `--embed-originals` to also write directly into JPEG/HEIC/TIFF/PNG/DNG files.
2. In Lightroom Classic's Library module, select the photos (Ctrl/Cmd+A for all) and choose **Metadata → Read Metadata from File(s)**. Lightroom overwrites its catalog's rating, color label, and keywords from the sidecar (or the embedded metadata, for the formats above).

Facet's reject marker (`xmp:Rating = -1`) reads back as Lightroom's Reject flag. A Facet favorite writes `xmp:Label = Yellow`, which Lightroom shows as the **Yellow color label** — not the Pick flag. If your Lightroom workflow keys off Picks rather than color labels, add a color-label-to-pick step, or filter by the Yellow label instead.

A `python facet.py --export-manifest` feed (path, category, every score, tags, and the same rating columns as `--export-sidecars` — including per-user ratings via `--export-manifest --user alice` on a multi-user install) now exists for tools that want Facet's data without parsing XMP — see [Commands — Preview & Export](COMMANDS.md#preview--export). The Facet plug-in below consumes it.

**Manifest version 2.** The manifest now also carries `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` and a top-level `pending_corrections` count (manual bracket/panorama corrections not yet applied by a detection run — re-run `--detect-panoramas`). The plug-in uses the per-photo fields for the burst pick/reject and star-fallback options below, and surfaces `pending_corrections` as a warning line in its Preview so you know a re-run of detection may still change which frames are leads. There is no backward-compatible read path: a plug-in built for version 2 refuses a version-1 manifest outright with a dialog telling you to re-export, and an older plug-in cannot read a version-2 manifest either. If you see that dialog, just re-run `--export-manifest`.

In the viewer, the gallery's **Export to editor** dialog offers the same manifest as a **Download Lightroom manifest** button, scoped to the same selection/filter set as the sidecar export next to it — see [Editor Export](VIEWER.md#editor-export). It writes the identical `facet_manifest.json` shape `--export-manifest` does, so the plug-in dialog above works the same way regardless of which side generated the file.

### The Facet plug-in (star ratings, pick flags, metadata fields and keywords)

`facet.lrplugin/` in the Facet repository is a Lightroom Classic plug-in that writes Facet's star rating and favorite/reject state **straight into the catalog**. It exists because two things above cannot be fixed from the XMP side: Lightroom never finds a Facet sidecar for a proprietary RAW file, and XMP has no channel at all for Lightroom's Pick flag. The plug-in reads a manifest file, so it never talks to the Facet server, needs no password, and works while Facet is not running — and because it matches photos by path rather than by sidecar, **a RAW-only library works exactly like a JPEG one**.

The plug-in registers two **Library → Plug-in Extras** menu items: **Facet: Apply ratings and flags...** (the manifest → catalog direction, documented in this section) and **Facet: Export Lightroom State to Facet...** (the reverse direction — see [Lightroom → Facet](#lightroom--facet) below).

**Install** (once):

1. Copy the `facet.lrplugin` folder to the machine running Lightroom. On macOS, zip it first — Finder treats a `.lrplugin` folder as a bundle.
2. In Lightroom Classic: **File → Plug-in Manager → Add**, select the `facet.lrplugin` folder, then **Done**.

**Use** (each time you want Facet's verdict in the catalog):

1. `python facet.py --export-manifest /photos/2026-wedding` (the path scopes the export; the file always lands as `facet_manifest.json` in the current directory). Copy it to the Lightroom machine if Facet runs elsewhere.
2. In the Library module, select the photos, then **Library → Plug-in Extras → Facet: Apply ratings and flags...**
3. Point the dialog at `facet_manifest.json`. The path is remembered for next time.
4. **If Facet scanned the photos from another machine, fill in the two path prefixes.** The manifest stores the paths of the machine that did the scanning (`/volume1/photos/...` on a NAS), and Lightroom holds the desktop's (`Z:\photos\...`). Enter the Lightroom prefix and the Facet prefix that mean the same folder; leave both empty when the two agree. Getting this wrong is the one first-run failure that matters — it simply matches nothing.
5. Choose the scope: the selected photos (default), or every photo of the current folder.
6. Press **Preview...**. **Nothing is written yet.** The plug-in reports how many photos it matched in the manifest, how many it did not, and how many ratings and flags it would set. If the matched count is 0, it shows a sample Lightroom path next to a sample manifest path so you can see what the prefixes must be.
7. Press **Apply**. Progress is shown and can be cancelled; a summary dialog reports what was set, skipped, and not found.

**What it writes** — nothing else, and never to your image files:

| Facet state | Lightroom field |
|---|---|
| `star_rating` 1-5 | star rating |
| favorite | Pick flag |
| rejected | Reject flag |

A Facet star rating of 0 means "no opinion" (see `xmp_export.score_to_rating`) and is never written.

**Overwrite semantics** — by default the plug-in never argues with you: it sets a star rating only when the photo is *unrated* in Lightroom, and a pick/reject flag only when the photo is *unflagged*. Anything you rated or flagged by hand is left alone and counted as "kept as they are" in the preview. Tick **Overwrite ratings and flags that are already set in Lightroom** to replace them instead. This mirrors `only_when_unrated` in `xmp_export.score_to_rating`, so the plug-in and the sidecar path treat your manual edits the same way.

**New dialog options** (all opt-in, each persisted for next time):

- **Fill in star ratings from Facet scores for photos you have not rated** — when a photo has no `star_rating` in the manifest (or it is 0) but Facet's `aggregate` score maps to a star count, that derived rating fills in the gap. Because it is a fallback for an *unrated* photo, not a real manifest rating, it **never overwrites an existing Lightroom rating — even with Overwrite ticked.** A real manifest `star_rating` still follows the normal overwrite rule above unchanged.
- **Pick the recommended frame of each burst** — for every burst group with at least 2 members in the manifest, every member the manifest marks `is_burst_lead` (a burst can keep more than one frame) is set to Picked. A lone frame that the manifest never grouped with siblings is never touched by this option, and a burst group with no `is_burst_lead` member anywhere in the manifest is skipped entirely (nothing to pick from). A manual Pick/Reject flag you already set — or a Facet favorite/reject in the manifest — always wins over this derived pick.
- **Reject the other frames** (nested under the pick option, enabled only alongside it) — sets every burst member that is *not* the lead to Rejected, with two exceptions: a member of a bracket, panorama, or HDR panorama is never rejected by this rule, no matter that its `burst_group_id` also groups it with siblings — those sets are kept whole; and a group with no lead anywhere in the manifest (see above) gets no rejects either.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — for every group with at least 2 matched photos in your current scope, creates or reuses a collection named `<yyyy-mm-dd HH:MM:SS> – <filename>` (the earliest member's capture time and filename; `~ (no date) – <filename>` when the earliest member has no capture time), nested under `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` or `Facet › HDR panoramas` as appropriate. A plain burst group whose members are *all* already part of one bracket/panorama/HDR-panorama set gets no separate Bursts collection, since it would just duplicate the one under Brackets/Panoramas/HDR panoramas. **Re-running only adds** photos to a collection it finds again — it never removes any, so a collection can go stale relative to a set that later gets re-grouped or re-detected (a photo dropped from a bracket on a later scan is not dropped from the collection). Collection names collide when two different groups' earliest members share the same capture time to the second and the same filename — two cameras that both happened to write `IMG_0001` at the same timestamp end up sharing one collection instead of getting one each. This is a known limitation, not a bug to report.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (nested under the option above) — instead of only adding, clears and refills a collection, but only when the collection AND its whole group are entirely inside the current scope; a collection that is only partly covered (some members outside the run's selection) or points at a smart/unresolved collection is left untouched and counted as skipped, and the summary reports how many were rebuilt, deleted, skipped and failed. It also reaches a Facet collection whose group DISSOLVED this run (no longer at least 2 in-scope members, so no plan entry at all) — that collection is emptied and deleted too, but only when every photo it currently holds was matched by this run; one holding any photo outside this run is left untouched. Rebuild is only ever offered — and only ever runs — while **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** is on; unticking that option turns Rebuild off too. The dissolved-collection sweep only ever touches a collection whose name matches the shape Facet itself generates (an ISO date-time, or the undated `~ (no date)`, followed by ` – <filename>`), so a collection you named yourself under a Facet set is never emptied or deleted. When the sweep has anything to delete, the Preview adds a `Facet collections to delete: N` line, and the sweep runs even when it is the only pending change, rather than being reported as nothing to change.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — writes the aggregate score (e.g. `8.4`), a whole-point band (`0`-`10`), the category and the set kind into Facet's own plug-in metadata fields, visible in the Metadata panel and usable in the Library Filter/smart collections as text (`sdktext:`) criteria — for example, a smart collection matching the band field as "any of 8, 9, 10". A field that no longer applies to a photo (for example, it left a bracket, so the set kind is gone) is cleared rather than left stale — otherwise a smart collection or Library Filter criterion built on that field keeps matching a photo that no longer qualifies. Adobe's SDK only admits a plug-in's own fields into the search vocabulary as text or enum, never as a numeric range, so there is still no "aggregate > 8" smart collection; band is the closest text-only substitute. Two further bookkeeping properties (the rating/pick value this run derived) are written alongside but kept out of the Library Filter and smart-collection criteria — see the reverse-export note under [Lightroom → Facet](#lightroom--facet). **UNVERIFIED against a live catalog:** whether a titleless metadata field is actually invisible in the Metadata panel and Library Filter is not confirmed against the Lightroom SDK docs alone, so the two bookkeeping properties are marked `searchable = false, browsable = false` as the safer, confirmed fallback rather than relying on an unconfirmed title-omission behaviour — they may still be visible in some Lightroom Classic versions.
- **Create "Facet" keywords from Facet tags (never included on export)** — creates a `Facet` root keyword with one child per Facet tag your photos carry, and sets each photo's `Facet ›` child keywords to exactly match its manifest tags (adds and removes as tags change between runs). Every keyword this option creates or touches has `Include on Export` turned off, so Facet's auto-tags never leak into a JPEG/TIFF export or a client gallery. Your own keywords outside the `Facet` root are read (to detect a pre-existing top-level `Facet` keyword, which is adopted as the root) but are never added, removed or written by this option; any child keyword you put under that adopted `Facet` root yourself is treated as stale and removed.

**Why collections, not stacks.** Lightroom's SDK has no call to create or manage a Stack — `stackInFolder`/`stackPositionInFolder` are read-only on `LrPhoto`. A collection is the closest writable substitute, and `canReturnPrior` means re-running the plug-in resolves the same collection rather than duplicating it. If you want an actual Lightroom stack, select a collection's photos and use **Photo → Stacking → Group into Stack** (Ctrl/Cmd+G) yourself — the plug-in cannot do this step for you.

**Limitations**, honestly:

- **Pick flags are catalog-only.** That is Lightroom's design, not the plug-in's: Lightroom never writes the pick flag to XMP, so it reaches no other application and is lost if you rebuild the catalog from the files. Star ratings do survive, via **Metadata → Save Metadata to File(s)**.
- **The metadata-field smart-collection route is still text-only.** Adobe's SDK admits a plug-in's own fields into the search vocabulary only as text or enum (`sdktext:`); the numeric operators (`>`, `<`, `in range`) belong to Lightroom's built-in criteria alone. The band field above is the closest text-only substitute for "aggregate > 8"; routing the raw score through the **star rating** (the fill-in option above) remains the only channel Lightroom itself filters and sorts numerically.
- **Undo** works one batch at a time: the plug-in writes in chunks of 200 photos, so Ctrl/Cmd+Z reverts 200 photos per press.
- Tick **Write facet-apply.log next to the manifest** before a run if you need to see, line by line, which paths matched and what was written.

### Lightroom → Facet

**Ratings, picks and rejects — Lightroom wins (via the plug-in).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** opens a save panel (no default file name or location) to write a Lightroom state file (one record per photo: `path`, and `rating`/`pick` only when they still need to travel — see below). Feed it back with `python facet.py --import-lightroom facet_lightroom_state.json` (add `--user alice` on a multi-user install; required there) or, in the viewer, the gallery's **Export to editor** dialog's **Import Lightroom state…** button, which posts the file's contents straight to the server. Lightroom's value wins unconditionally for every key present in a record — CLI and viewer share one `processing/lightroom_sync.py` importer, reporting `matched`/`unmatched`/`changed` counts:

| Lightroom state | Facet result |
|---|---|
| Pick flag = Picked (`pick = 1`) | favorite = on, rejected = off |
| Pick flag = Rejected (`pick = -1`) | favorite = off, rejected = on |
| Pick flag = none (`pick = 0`) | favorite = off, rejected = off |
| star rating (`rating`, 0-5) | `star_rating` (`0` clears it) |

A record that omits `rating` or `pick` entirely leaves Facet's corresponding value untouched — the export only includes a key when Lightroom's current value differs from what the Apply direction itself last derived for that photo (two hidden, non-searchable plug-in properties record that baseline), so re-exporting an untouched photo writes an empty record and changes nothing. Because Lightroom wins unconditionally, exporting also clears a Facet rating/favorite/reject on any exported photo the Apply direction never touched — an unrated, unflagged photo in Lightroom (`pick = 0`, no `rating`) overwrites an existing Facet star rating or favorite/reject with "none". A successful import that changes anything also rebuilds the rating-derived training pairs and nudges the same idle-triggered auto-retrain every other rating write does. Virtual copies are deduped to their master by path before export, preferring the master when both exist for the same file.

**Ratings, labels and keywords via XMP.** Separately, and still one-way in this direction:

1. In Lightroom, select the photos and choose **Metadata → Save Metadata to File(s)** (Ctrl/Cmd+S). This flushes the catalog's rating/label/keywords into the XMP sidecar (RAW) or embeds them in the file itself (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (optionally scoped to a path) reads them back into Facet's database.

### Conflict rules

- **Ratings and labels are newest-wins**, compared between the sidecar's `xmp:MetadataDate` and the photo's `scanned_at` (the last time Facet scored it) — not a per-rating edit timestamp. A sidecar newer than the last scan can override a rating you changed in Facet *after* that scan. Keep the round trip simple: export → Lightroom reads → edit in Lightroom → Lightroom saves → import, without re-rating inside Facet in between.
- **Tags and keywords are always merged** (union, deduped) in both directions — Lightroom keywords never wipe Facet's auto-tags, and vice versa.
- **Multi-user** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): ratings route to Alice's `user_preferences` row instead of the global columns. Keywords stay global regardless of `--user` — they are shared across users.
- Run `python database.py --migrate-tags` after `--import-sidecars` if you rely on the `photo_tags` lookup table, so tag filters see the merged keywords immediately.

## Capture One

Capture One never writes into the original file or into a continuously-synced XMP sidecar the way Lightroom's autosave does — it keeps its own adjustments in `.cos` settings (Sessions) or its catalog database, and its **Sync Metadata** preference has a bidirectional "Full Sync" mode that can silently overwrite whichever side wrote last. Running a two-way loop through that setting risks losing either Facet's or Capture One's edits. The safe pattern is **one-way, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. In Capture One, leave **Preferences → General → Sync Metadata** at its default (not "Full Sync").
3. Select the imported images, right-click, and choose **Load Metadata** to pull the rating/label/keywords from the sidecar (or embedded metadata) into Capture One's catalog fields once.

Treat Facet as the upstream source of truth for AI-derived ratings and tags for that shoot: do the one-time `Load Metadata` pull, then make further picks inside Capture One without wiring its metadata sync back into Facet's sidecar. If you want Capture One's picks back in Facet, export them from Capture One to XMP explicitly and run `--import-sidecars` on that folder as a separate, deliberate step rather than an automatic sync — and remember the [RAW sidecar naming gotcha](#the-raw-sidecar-naming-gotcha) above: this only works for JPEG/HEIC/TIFF/PNG/DNG, since Capture One also names RAW sidecars `<image>.xmp` rather than Facet's `<image><ext>.xmp`.

## digiKam

As of digiKam 9.1.0 (released 2026-06-07), digiKam reads XMP sidecars natively — no exiftool needed on digiKam's side — and it looks for both naming conventions (`<image><ext>.xmp` first, falling back to `<image>.xmp`), so it finds Facet's sidecars for RAW files without the gotcha above. After `python facet.py --export-sidecars`, open (or refresh) the folder in digiKam and it picks up the rating, color label, keywords, and named face regions automatically, as long as **Settings → Configure digiKam → Metadata → Read from sidecar files** is enabled (the default).

### Batch Queue Manager hook

You can fold a Facet re-import into a digiKam Batch Queue Manager (BQM) workflow with the **Custom Script** tool, so photos you rate or label in digiKam flow back into Facet's database without leaving digiKam. Enable **Settings → Configure digiKam → Metadata → Write to sidecar files** so digiKam persists your edits to `<image>.xmp` immediately, then add a queue whose only tool is Custom Script:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` are digiKam's per-file placeholders (BQM runs the script through `/bin/bash` on Linux/macOS and expects an output file, hence the `cp` passthrough). Because `--import-sidecars` scans the whole folder, running it once per photo in a large batch is redundant, if harmless (it's idempotent — unchanged photos are skipped). For big batches, skip the BQM hook and just run `python facet.py --import-sidecars /path/to/folder` once by hand after the queue finishes.

## darktable

darktable already has first-class treatment in [Configuration — Viewer](CONFIGURATION.md#viewer) (`viewer.raw_processor.darktable` export profiles/styles) and [Viewer — Download](VIEWER.md#api-endpoints) (`type=darktable` conversions). On the XMP side: darktable authors its own `<image><ext>.xmp` to store its edit history, and Facet's exiftool-backed sidecar writer merges into that same file in place — the `darktable:history`/mask nodes are preserved, never overwritten. No separate recipe is needed here; the two-way sidecar behavior described above for Lightroom (export/import, newest-wins, tag union) applies the same way, without the RAW naming mismatch since darktable and Facet agree on `<image><ext>.xmp`.

**Caveat: darktable's own XMP reload is unreliable.** Independent of Facet's write path, re-importing an image that darktable has already edited can make darktable overwrite the sidecar's edit history with a blank one instead of loading it back — an open upstream bug ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), reported 2026-03-15) that the "check for new/updated xmp files on start" preference does not protect against. Facet is not the cause (the exiftool merge above already preserves `darktable:history`), but the risk sits in the read-back step this page's round trip depends on. Practical workaround, following the same one-shot discipline as the Capture One recipe above: after `--export-sidecars`, don't bulk re-import an already-edited folder — reload sidecars for just the images Facet touched and confirm the edit history is still there before trusting the rest of the batch.

## How Facet merges

| Field | Facet writes | Facet reads back | Conflict rule |
|---|---|---|---|
| Star rating / reject | `xmp:Rating` (`-1` = rejected) | `xmp:Rating` | Newest-wins vs. `scanned_at` |
| Color label | `xmp:Label` (`Red` = rejected, `Yellow` = favorite) | `xmp:Label` | Newest-wins vs. `scanned_at` |
| Tags / keywords | `dc:subject` (flat, includes named-face person names) | `dc:subject` | Always merged (union, deduped) |
| Hierarchical tags | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<name>`) | Not re-imported | Export-only |
| Caption | `dc:description` (+ `IPTC:Caption-Abstract` via exiftool) | Not re-imported | Export-only |
| Named face regions | MWG `mwg-rs:RegionList` (center-normalized, `Type=Face`) | Not re-imported | Export-only; read natively by digiKam, **not** read by Lightroom (a known Adobe limitation — Lightroom only consumes MWG regions it wrote itself) |

See [Commands — Preview & Export](COMMANDS.md#preview--export) for the full CLI reference (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
