# Editor Interop Recipes

> 🌐 **English** · [Français](fr/INTEROP.md) · [Deutsch](de/INTEROP.md) · [Italiano](it/INTEROP.md) · [Español](es/INTEROP.md) · [Português](pt/INTEROP.md) · [简体中文](zh/INTEROP.md)

Step-by-step recipes for moving Facet's ratings, labels and tags to and from Lightroom, Capture One, digiKam and darktable. For the full `--export-sidecars` / `--import-sidecars` flag reference and field mapping (`xmp:Rating`, `xmp:Label`, `dc:subject`), see [Commands — Preview & Export](COMMANDS.md#preview--export).

Originals are never modified unless you ask for embedding: `--embed-originals` on the command line, or **Write metadata to file** in the viewer.

## What travels

Manual locations and review decisions travel only when you export metadata in the viewer or run `--export-sidecars`.

- **GPS** uses `exif:GPSLatitude` / `exif:GPSLongitude`. Only manually set locations are exported, so scanned GPS never replaces the file's GPS. `--embed-originals` also writes EXIF GPS into supported originals. Clearing a location exports an explicit clear; a missing field never clears a location on import.
- **Capture date.** A corrected date is exported as `exif:DateTimeOriginal` (and as EXIF `DateTimeOriginal` with `--embed-originals`). After **Use file date**, the next export removes it from the sidecar, but leaves alone a date another editor wrote.
- **Keep and reject.** Keep is independent of stars and favorites. Rejecting clears Keep, stars and favorite.

Facet's own XMP namespace, `https://github.com/ncoevoet/facet/ns/1.0/`, adds:

| Tag | Values | Purpose |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | Facet's review decision |
| `facet:GPSState` | `set`, `cleared` | Whether Facet set or cleared the location |
| `facet:DateState` | `set` | The sidecar capture date came from Facet |
| `facet:KeywordState` | JSON (`version` 1; `owned`, `deleted`, `ai`, `manual` lists) | Which keywords Facet wrote |
| `facet:RegionOwner` | `Facet` | The MWG face regions Facet wrote |

`facet:KeywordState` lets `--reconcile-keywords` remove only names Facet owns, and stops an old AI label from turning into a manual tag on import. `facet:RegionOwner` lets ExifTool replace only Facet's face regions.

How `--import-sidecars` applies a Facet decision:

- It applies a decision when the standard review fields agree with it or are absent.
- If the standard rejection state disagrees, another editor changed the standard fields. Facet ignores its private decision and uses the newest-wins scan-time check on the standard fields.
- A decision exported alongside standard review fields also uses the newest-wins check, so an older export cannot undo a newer decision. The exception is a photo with no review state yet (no stars, favorite, Keep or reject): a rescanned library still gets its decisions back.
- Decision-only imports stay explicit (you ask for them) and are applied without the scan-time check.

Other rules:

- Manual GPS already in Facet is kept unless you add `--overwrite-manual-gps`. Invalid or incomplete coordinates are ignored.
- `--user alice` limits imports and exports to that user's visible folders and private decisions. GPS stays shared. Without `--user`, the CLI works on global state.
- Global imports (without `--user`), including `--dry-run` previews, do not need the viewer's login secret.
- With ExifTool, export merges into existing sidecars. Without it, export leaves an existing editor sidecar intact and writes a fallback file.
- ExifTool exports need Facet's bundled tag definitions. If they are missing, export stops before changing anything; reinstall Facet.

## The RAW sidecar naming gotcha

Facet exports `IMG_1234.CR2.xmp` next to `IMG_1234.CR2` (darktable's full-filename convention). Lightroom Classic and Capture One usually use `IMG_1234.xmp` for proprietary RAW. Export names never change.

For JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` writes into the file instead. GIF/WebP/BMP/AVIF/JPEG XL and proprietary RAW still need a sidecar with matching naming.

On import, choose the naming with `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (default): read `<image.ext>.xmp` or `<image.ext>.facet.xmp`, whichever was modified last. The primary wins a tie.
- `basename`: read `<image>.xmp` (only the last extension is stripped). Full-name sidecars are ignored.
- `auto`: accept whichever kind exists. If both exist, the photo is skipped as ambiguous; pick `full` or `basename` instead.

Under `basename` and `auto`, a basename shared by several images (e.g. `same.CR3` and `same.jpg`) is refused, even if only one is in scope. Use full-name sidecars for those. `same_v1.jpg` has a different basename and is fine.

- A double-extension file like `IMG.CR2.jpg` never reads `IMG.CR2.xmp`, which belongs to `IMG.CR2`. The same goes for another image's `.facet.xmp` fallback.
- Mismatches, ambiguity and unreadable sidecars are reported. Facet does not try another naming after a parse failure.
- The summary counts every affected photo, including sidecars ignored because of the chosen naming. Notices show one example per kind.
- No files are renamed.

Import needs no ExifTool. Export merging, embedding and MWG face rectangles need ExifTool. Without it, Facet leaves an existing editor sidecar alone and writes `<image.ext>.facet.xmp` with no face rectangles. Other editors do not look for that name, so hand it over deliberately.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (add a path to scope it, e.g. `--export-sidecars /photos/2026-wedding`). Add `--embed-originals` to also write directly into JPEG/HEIC/TIFF/PNG/DNG files.
2. In Lightroom Classic's Library module, select the photos (Ctrl/Cmd+A for all) and choose **Metadata → Read Metadata from File(s)**. Lightroom replaces its rating, color label and keywords with the sidecar's (or the embedded metadata's).

Facet's reject (`xmp:Rating = -1`) reads back as Lightroom's Reject flag. A Facet favorite writes `xmp:Label = Yellow`, which Lightroom shows as the **Yellow color label**, not a Pick. To get Picks, use the plug-in below or filter on the Yellow label.

`python facet.py --export-manifest` writes Facet's data without XMP: path, category, every score, tags and the same rating columns as `--export-sidecars`. Use `--export-manifest --user alice` for per-user ratings. See [Commands — Preview & Export](COMMANDS.md#preview--export). The Facet plug-in below reads it.

**Manifest version 2** adds `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` and a top-level `pending_corrections` count. That count is the number of manual bracket/panorama corrections not yet applied; re-run `--detect-panoramas` to apply them. The plug-in shows it as a warning in its Preview. A version-2 plug-in refuses a version-1 manifest (and vice versa); re-run `--export-manifest` if you see that dialog.

In the viewer, the gallery's **Export to editor** dialog has a **Download Lightroom manifest** button for the same selection or filter — see [Editor Export](VIEWER.md#editor-export). It produces the same `facet_manifest.json` as `--export-manifest`.

### The Facet plug-in (star ratings, pick flags, metadata fields and keywords)

`facet.lrplugin/` in the Facet repository is a Lightroom Classic plug-in. It writes Facet's star ratings and favorite/reject state **straight into the catalog**. This solves two things XMP cannot: Lightroom never finds a Facet sidecar for proprietary RAW, and XMP cannot carry Lightroom's Pick flag.

The plug-in reads a manifest file. It never contacts the Facet server, needs no password, and works while Facet is stopped. It matches photos by path, so **a RAW-only library works like a JPEG one**.

It adds two **Library → Plug-in Extras** menu items:

- **Facet: Apply ratings and flags...** — manifest → catalog (this section).
- **Facet: Export Lightroom State to Facet...** — catalog → Facet, see [Lightroom → Facet](#lightroom--facet).

**Install** (once):

1. Copy the `facet.lrplugin` folder to the Lightroom machine. On macOS, zip it first: Finder treats a `.lrplugin` folder as a bundle.
2. In Lightroom Classic: **File → Plug-in Manager → Add**, select the `facet.lrplugin` folder, then **Done**.

**Use:**

1. `python facet.py --export-manifest /photos/2026-wedding` (the path scopes the export; the file is always `facet_manifest.json` in the current directory). Copy it to the Lightroom machine if needed.
2. In the Library module, select the photos, then **Library → Plug-in Extras → Facet: Apply ratings and flags...**
3. Point the dialog at `facet_manifest.json`. The path is remembered.
4. **If Facet scanned on another machine, fill in the two path prefixes.** The manifest holds the scanning machine's paths (e.g. `/volume1/photos/...` on a NAS); Lightroom holds the desktop's (e.g. `Z:\photos\...`). Enter the Lightroom prefix and the Facet prefix for the same folder. Leave both empty if the paths agree. If they are wrong, nothing matches.
5. Choose the scope: the selected photos (default) or the whole current folder.
6. Press **Preview...**. **Nothing is written yet.** It shows how many photos matched, how many did not, and what it would set. If nothing matched, it shows a sample Lightroom path next to a sample manifest path so you can fix the prefixes.
7. Press **Apply**. You can cancel during progress. A summary shows what was set, skipped and not found.

**What it writes** (never to your image files):

| Facet state | Lightroom field |
|---|---|
| `star_rating` 1-5 | star rating |
| favorite | Pick flag |
| rejected | Reject flag |

A Facet star rating of 0 means "no opinion" and is never written.

**Overwrite rule.** By default the plug-in only sets a rating on a photo that is *unrated* in Lightroom, and a flag on one that is *unflagged*. Your own ratings and flags are kept and counted as "kept as they are". Tick **Overwrite ratings and flags that are already set in Lightroom** to replace them. Sidecar export follows the same rule (`xmp_export.score_to_rating.only_when_unrated`, default `true`).

**Dialog options** (all off by default, remembered between runs):

- **Fill in star ratings from Facet scores for photos you have not rated** — if the manifest has no `star_rating` (or 0), the `aggregate` score is mapped to stars. This fallback **never overwrites an existing Lightroom rating, even with Overwrite ticked.**
- **Pick the recommended frame of each burst** — in each burst group with at least 2 members, every member marked `is_burst_lead` is Picked (a burst can keep more than one). Lone frames and groups with no lead are skipped. Your own Pick/Reject flags and Facet favorites/rejects always win.
- **Reject the other frames** (only with the pick option) — rejects every non-lead burst member. Members of a bracket, panorama or HDR panorama are never rejected, and groups with no lead get no rejects.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — for each group with at least 2 matched photos in scope, creates or reuses a collection under `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` or `Facet › HDR panoramas`.
  - Name: `<yyyy-mm-dd HH:MM:SS> – <filename>` of the earliest member, or `~ (no date) – <filename>` if it has no capture time.
  - A burst whose members all belong to one bracket or panorama set gets no separate Bursts collection.
  - **Re-running only adds photos.** A photo that later leaves a set stays in its collection.
  - Known limitation: two groups whose earliest members share the same capture second and filename (e.g. two cameras writing `IMG_0001`) share one collection.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (only with the option above) — clears and refills a collection, but only when the collection and its whole group are in the current scope. Partly covered collections and smart collections are skipped.
    - It also empties and deletes the collection of a group that dissolved in this run, but only if every photo in it was matched by this run.
    - It only touches collections whose name has Facet's own format (a date-time or `~ (no date)`, then ` – <filename>`). Collections you named yourself are never touched.
    - The Preview shows a `Facet collections to delete: N` line when there is something to delete. The summary reports rebuilt, deleted, skipped and failed collections.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — writes the aggregate score (e.g. `8.4`), a whole-point band (`0`-`10`), the category and the set kind into Facet's own metadata fields. They show in the Metadata panel and work as text (`sdktext:`) criteria in the Library Filter and smart collections, e.g. band "any of 8, 9, 10". A field that no longer applies is cleared. Two hidden bookkeeping fields (the rating and pick this run derived) are also written; they are excluded from search but may still be visible in some Lightroom Classic versions (unverified).
- **Create "Facet" keywords from Facet tags (never included on export)** — creates a `Facet` root keyword with one child per tag (AI and [manual tags](#manual-tags-and-xmp-keywords)). Each photo's `Facet ›` children are set to match its tags, so a tag removed in Facet disappears at the next Apply. `Include on Export` is off for all of them, so they never leak into exports or client galleries. Your keywords outside the `Facet` root are never changed. An existing top-level `Facet` keyword is adopted as the root, and any child you added under it yourself is removed.

**Why collections, not stacks.** Lightroom's SDK cannot create stacks. To stack a collection's photos, select them and use **Photo → Stacking → Group into Stack** (Ctrl/Cmd+G).

**Limitations:**

- **Pick flags stay in the catalog.** Lightroom never writes them to XMP, so no other app sees them, and rebuilding the catalog from files loses them. Star ratings survive via **Metadata → Save Metadata to File(s)**.
- **No numeric smart collections on Facet fields.** Plug-in fields are text only (`sdktext:`); the numeric operators (`>`, `<`, `in range`) work only on Lightroom's built-in fields. Use the band field, or the star-rating fill-in option, which Lightroom does sort and filter numerically.
- **Undo** reverts one batch of 200 photos per Ctrl/Cmd+Z.
- Tick **Write facet-apply.log next to the manifest** to log which paths matched and what was written.

### Lightroom → Facet

**Ratings, picks and rejects — Lightroom wins (via the plug-in).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** opens a save panel. The file holds one record per photo: `path`, plus `rating`/`pick` when they need to travel.
2. Import it with `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` is required on a multi-user install), or with **Import Lightroom state…** in the gallery's **Export to editor** dialog.

Lightroom's value wins for every field in a record. The import reports `matched`/`unmatched`/`changed` counts.

| Lightroom state | Facet result |
|---|---|
| Pick flag = Picked (`pick = 1`) | favorite = on, rejected = off |
| Pick flag = Rejected (`pick = -1`) | favorite = off, rejected = on |
| Pick flag = none (`pick = 0`) | favorite = off, rejected = off |
| star rating (`rating`, 0-5) | `star_rating` (`0` clears it) |

- A record without `rating` or `pick` leaves that Facet value alone. The export only includes a field when Lightroom's value differs from what the last Apply set, so an untouched photo changes nothing.
- Virtual copies are merged into their master before export.
- A successful import that changes anything refreshes the training pairs and arms the auto-retrain, like any rating change.

> **Warning:** Because Lightroom wins, a photo the Apply step never touched that is unrated and unflagged in Lightroom (`pick = 0`, no `rating`) clears its Facet star rating, favorite and reject on import.

**Ratings, labels and keywords via XMP** (one-way):

1. In Lightroom, select the photos and choose **Metadata → Save Metadata to File(s)** (Ctrl/Cmd+S). This writes rating, label and keywords to the XMP sidecar (RAW) or into the file (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` reads the RAW sidecars. Shared RAW/JPEG basenames are refused. This command does not read embedded metadata. Imported keywords become manual tags.

### Conflict rules

- **Tags and keywords merge by default.** Exports add Facet keywords; `--reconcile-keywords` also removes stale Facet-owned names. Imports add manual tags and never replace AI tags. See [Manual tags and XMP keywords](#manual-tags-and-xmp-keywords).
- **Multi-user** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): ratings go to Alice's own ratings (`user_preferences`) instead of the global ones. Keywords are always global: manual tags are shared.
- Imported keywords are stored in `photo_manual_tags`, which tag filters read directly. No `python database.py --migrate-tags` is needed after `--import-sidecars`.

## Capture One

Capture One keeps its settings in `.cos` files (Sessions) or its catalog. Its **Sync Metadata** "Full Sync" mode can overwrite whichever side wrote last, so a two-way loop can lose edits. Use **one-way, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. In Capture One, leave **Preferences → General → Sync Metadata** at its default (not "Full Sync").
3. Select the images, right-click and choose **Load Metadata** to pull rating, label and keywords in once.

Then keep working in Capture One without automatic sync. To bring saved XMP back into Facet, run `--import-sidecars /path/to/shoot --sidecar-naming basename` for stripped-extension RAW sidecars, or `full` for full filenames. Shared RAW/JPEG basenames are refused. This reads sidecars, not embedded metadata.

## digiKam

digiKam's [sidecar settings](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) use one naming: `filename.ext.xmp` by default, or `filename.xmp` with **Sidecar file names are compatible with commercial programs** enabled. It does not try both.

- **Facet → digiKam:** use the full-name setting, enable **Read from sidecar files**, reread metadata from the files, and check the fields.
- **digiKam → Facet:** pass `--sidecar-naming full` or `basename` to match your digiKam setting.

Stars, color labels and pick flags mean slightly different things in each app, so check the result.

### Batch Queue Manager hook

You can run a Facet import from digiKam's Batch Queue Manager (BQM) **Custom Script** tool. First enable sidecar writing, save the naming setting, and apply pending metadata changes (digiKam may delay writes). This example assumes full-name sidecars; use `basename` only for a collection with no shared basenames:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` are digiKam's per-file placeholders. BQM expects an output file, hence the `cp`. `--import-sidecars` scans the whole folder, so running it per photo is redundant but harmless. For big batches, run `python facet.py --import-sidecars /path/to/folder` once after the queue finishes.

## darktable

See [Configuration — Viewer](CONFIGURATION.md#viewer) (`viewer.raw_processor.darktable` export profiles and styles) and [Viewer — Download](VIEWER.md#download) (`type=darktable` conversions).

darktable stores its edit history in its own `<image><ext>.xmp`. Facet's ExifTool writer merges into that file and keeps the `darktable:history` and mask nodes. The Lightroom sidecar behaviour above (export/import, newest-wins, tag union) applies as-is, and there is no RAW naming mismatch: both use `<image><ext>.xmp`.

**ExifTool version:**

- **13.28 or newer** is recommended.
- Face updates need **12.65 or newer**. Older or unknown versions skip face changes with a warning and export the rest.
- **13.23 through 13.27** corrupt sidecars that carry darktable history, so Facet refuses to write with them and asks you to upgrade. The Docker image pins a safe version. Distribution packages may not (Debian trixie's `libimage-exiftool-perl` is 13.25).

> **Warning:** darktable itself can wipe edit history when re-importing an already-edited image: it may overwrite the sidecar's history with a blank one. This is an open upstream bug ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), reported 2026-03-15), and the "check for new/updated xmp files on start" preference does not prevent it. After `--export-sidecars`, do not bulk re-import an edited folder. Reload only the images Facet touched and check their history first.

## Manual tags and XMP keywords

Facet keeps tags you type (see [Viewer — Manual Tags](VIEWER.md#manual-tags)) in `photo_manual_tags`, separate from the AI tags in `photos.tags`. A rescan or retag never touches them.

- **Export.** Every keyword writer emits AI tags, then manual tags, then person names, deduplicated ignoring case. This covers `--export-sidecars`, the gallery's XMP export and "Write metadata to file" actions, and the Lightroom manifest (`--export-manifest`, `/api/lightroom/manifest`).
- **Import.** `--import-sidecars` reads flat keywords from `dc:subject` and hierarchy paths separately from `lr:hierarchicalSubject`. Flat keywords are normalised like typed tags: trimmed, lowercased, at most 64 characters, 50 manual tags per photo. Each becomes a manual tag with source `xmp`, unless it:
  - is already one of the photo's AI tags or person names,
  - duplicates a path explicitly present in `lr:hierarchicalSubject`,
  - contains a comma or control character, or
  - would exceed the cap.
- **Keyword removal is explicit.** Exports only add by default. `--export-sidecars /path --reconcile-keywords` (needs ExifTool) also removes names Facet wrote earlier that are no longer in Facet. Keywords Facet never wrote are never removed, even if the name matches, and old unmarked sidecars give Facet no ownership. If you re-add a removed keyword in another editor, Facet can import it again and treats it as foreign afterwards. Keywords are shared even with `--user`.
- **Facet's keywords win on export.** A keyword still in Facet is written back even if another editor removed it from the file. To remove it for good, remove the tag in Facet. Reconciliation never deletes tags from Facet.
- Names such as `2024`, `1.50`, `1e3`, `true`, `false` and `null` keep their spelling.
- If Facet cannot read an existing file's metadata, the export stops before writing.
- **The Lightroom manifest does propagate removals.** The plug-in's keyword option rewrites each photo's `Facet ›` children at every Apply.
- **AI tags stay AI tags.** Sidecars record which keywords were AI and which manual, so a retag does not turn an old AI keyword into a manual tag. Sidecars from older Facet versions keep the old additive behaviour.
- **Hierarchies.** Imported paths are added to the shared keyword hierarchy; flat names containing `|` or `/` do not create a hierarchy by themselves. Paths marked as generated by Facet are not imported as manual assignments unless also marked manual. Exports include explicit assignments and generated category/person paths. Export is additive by default; `--reconcile-keywords` removes only stale Facet-owned paths, preserving foreign paths.
- **Ownership limits:** 10,000 names per list and 1,024 characters per name. An export that would exceed them stops before writing. Archive and clean up such a sidecar by hand before starting fresh.
- **Keywords imported by an older Facet stay where they are.** Older versions merged keywords into `photos.tags`, where they look like AI tags, and nothing migrates them. To turn one into a manual tag, clear or retag `photos.tags`, then run `--import-sidecars` again — or add the tag by hand.
- **A moved or renamed file loses its manual tags.** They are tied to the photo's path.
- **`--export-csv` and `--export-json` stay AI-only.** Their `tags` value has no manual tags.

## How Facet merges

| Field | Facet writes | Facet reads back | Conflict rule |
|---|---|---|---|
| Star rating / reject | `xmp:Rating` (`-1` = rejected) | `xmp:Rating` | Tracked review clocks; legacy scan fallback |
| Color label | `xmp:Label` (`Red` = rejected, `Yellow` = favorite) | `xmp:Label` | Tracked review clocks; legacy scan fallback |
| Tags / keywords | `dc:subject` (flat, AI tags + manual tags, includes named-face person names) | `dc:subject` (stored as manual tags) | Additive by default; `--reconcile-keywords` removes only stale Facet-owned names; imports stay additive ([Manual tags and XMP keywords](#manual-tags-and-xmp-keywords)) |
| Hierarchical tags | `lr:hierarchicalSubject` (explicit assignments and generated category/person paths) | `lr:hierarchicalSubject` (shared hierarchy assignments) | Import is additive; export reconciliation removes only stale Facet-owned paths |
| Caption | `dc:description` default language (+ `IPTC:Caption-Abstract` via exiftool) | Not re-imported | Export-only |
| Named face regions | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet` (center-normalized, `Type=Face`) | Not re-imported | Export-only; read natively by digiKam, **not** read by Lightroom (a known Adobe limitation — Lightroom only consumes MWG regions it wrote itself) |

See [Commands — Preview & Export](COMMANDS.md#preview--export) for the full CLI reference (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**GPS clears.** If a sidecar has both standard GPS fields and an old `facet:GPSState=cleared`, a complete valid latitude/longitude pair wins. A partial or invalid pair is ignored and never clears a location. Only a missing or blank pair plus the clear marker clears GPS. Manual GPS stays protected unless you ask to overwrite it.

**Captions.** With ExifTool, export updates only the default (`x-default`) language of `dc:description` and keeps other languages. An empty Facet caption leaves existing captions alone. Without ExifTool, Facet writes a default-language caption and, when an editor sidecar exists, writes to `<image>.facet.xmp` instead.

**Face regions.** With ExifTool, export replaces only MWG rectangles marked `facet:RegionOwner=Facet`.

- Unmarked regions, including those from older Facet versions, are kept. After upgrading, an old unmarked face and its new marked copy can both appear, and clearing faces leaves the old one.
- Repeated exports replace the marked copies; they do not pile up.
- If the image dimensions differ from the ones the existing regions were drawn on (or are unknown), face changes are skipped with a warning. Rating, label, keywords and GPS still export.
- Unreadable or invalid face metadata stops a single-photo export or embed before writing.
- The fallback writer (no ExifTool) exports no face rectangles.
- A marked region you edit elsewhere is still Facet's. Remove its ownership marker to keep it as your own.

> **Warning:** Writes to separate files are not atomic. An I/O failure or an outside change during export can leave some files updated and others not.

If the ExifTool version check fails, Facet retries it next time. While the version is unknown, face regions are skipped and the rest exports. Known-bad versions are always refused.

## Sidecar import preview and review conflicts

Run `--import-sidecars /path --dry-run` to see the JSON plan before writing: the chosen sidecar, before/after fields, keywords to add, source time and skip/conflict reasons. Preview opens the database read-only and never changes it. Apply re-reads everything, so the preview is not a token you replay.

If the database is missing, unreadable or invalid, preview exits with code 1 and does not create or repair it. `--dry-run-count` limits scan samples only, not import previews.

`--sidecar-fields review,gps,keywords` selects which groups to import; leave a group out to skip it.

- **review** imports stars, favorite, rejection and Keep together, so a conflict never applies half a decision.
- **gps** keeps manual locations unless `--overwrite-manual-gps` is given.
- **keywords** are additive and shared, even with `--user`.

**Edit clocks.** Facet records when each review field was last changed, per photo and account, including resets. A sidecar older than that change is a `newer_local_edit` conflict, and that review group is left unchanged. `--overwrite-sidecar-review` overrides this and the scan-time check. A `local` source means an unknown writer, not necessarily a person. Captions, faces, and unmarked external GPS are never imported.

- Fields changed before Facet started recording edits have no known edit time. The scan-time rule applies, reported as `untracked_legacy_edit`.
- Preview also opens older databases without upgrading them; a missing Keep field reads as undecided.
- The sidecar's time is `xmp:MetadataDate`, or the file's modification time if that is missing or invalid.
- Details list the first 1,000 photos in scope and 100 notes per photo, with counts of what was left out.

Edit clocks stay in their own database. A fresh viewer export copies no scanner edit clocks or sidecar paths. An incremental export keeps the viewer's own clocks, so resets made in the viewer (including deleted per-user ratings) survive. Scanner values the viewer never edited keep updating.

> **Warning:** A viewer database built by an unreleased pre-1.24.0 build may hold copied scanner clocks. They now count as viewer edits, so those fields stop following scanner updates. Back up and review that database before rebuilding it: a full rebuild discards viewer-local changes.
