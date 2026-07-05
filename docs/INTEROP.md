# Editor Interop Recipes

> 🌐 **English** · [Français](fr/INTEROP.md) · [Deutsch](de/INTEROP.md) · [Italiano](it/INTEROP.md) · [Español](es/INTEROP.md) · [Português](pt/INTEROP.md)

Practical, step-by-step recipes for round-tripping Facet's ratings, labels, and tags with the external editors and DAM tools people actually use. This page assumes you already know *that* Facet writes XMP — see [Commands — Preview & Export](COMMANDS.md#preview--export) for the full `--export-sidecars` / `--import-sidecars` flag reference and the field mapping (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## The RAW sidecar naming gotcha

Facet names a sidecar `<image><ext>.xmp` — e.g. `IMG_1234.CR2.xmp` next to `IMG_1234.CR2` — the same convention darktable and digiKam use. **Lightroom Classic and Capture One expect the opposite: `IMG_1234.xmp`, with the raw extension stripped.** Neither app will discover a Facet-written sidecar for a proprietary RAW file (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — everything except DNG), and Facet's own `--import-sidecars` won't find a sidecar an Adobe-ecosystem app wrote for the same RAW either. This is a naming mismatch between ecosystems, not a bug on either side.

It does **not** affect:
- **JPEG, HEIC, TIFF, PNG, DNG** — pass `--embed-originals` and Facet writes the metadata *into the file itself* (via exiftool), so there is no sidecar name for Lightroom/Capture One to miss.
- **digiKam** — checks both naming conventions and finds Facet's sidecar either way (see [digiKam](#digikam) below).
- **darktable** — uses the same `<image><ext>.xmp` convention as Facet (see [darktable](#darktable) below).

So for a Lightroom or Capture One workflow: use `--embed-originals` for anything that isn't proprietary RAW, and expect the sidecar round-trip to be silent (no error, just nothing read) for pure RAW files. If you shoot RAW+JPEG, the JPEG companion is the practical interop vehicle — the RAW rides along on disk, untouched, while Facet's database keeps the authoritative rating.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (add a path to scope it, e.g. `--export-sidecars /photos/2026-wedding`). Add `--embed-originals` to also write directly into JPEG/HEIC/TIFF/PNG/DNG files.
2. In Lightroom Classic's Library module, select the photos (Ctrl/Cmd+A for all) and choose **Metadata → Read Metadata from File(s)**. Lightroom overwrites its catalog's rating, color label, and keywords from the sidecar (or the embedded metadata, for the formats above).

Facet's reject marker (`xmp:Rating = -1`) reads back as Lightroom's Reject flag. A Facet favorite writes `xmp:Label = Yellow`, which Lightroom shows as the **Yellow color label** — not the Pick flag. If your Lightroom workflow keys off Picks rather than color labels, add a color-label-to-pick step, or filter by the Yellow label instead.

### Lightroom → Facet

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

digiKam reads XMP sidecars natively — no exiftool needed on digiKam's side — and it looks for both naming conventions (`<image><ext>.xmp` first, falling back to `<image>.xmp`), so it finds Facet's sidecars for RAW files without the gotcha above. After `python facet.py --export-sidecars`, open (or refresh) the folder in digiKam and it picks up the rating, color label, keywords, and named face regions automatically, as long as **Settings → Configure digiKam → Metadata → Read from sidecar files** is enabled (the default).

### Batch Queue Manager hook

You can fold a Facet re-import into a digiKam Batch Queue Manager (BQM) workflow with the **Custom Script** tool, so photos you rate or label in digiKam flow back into Facet's database without leaving digiKam. Enable **Settings → Configure digiKam → Metadata → Write to sidecar files** so digiKam persists your edits to `<image>.xmp` immediately, then add a queue whose only tool is Custom Script:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` are digiKam's per-file placeholders (BQM runs the script through `/bin/bash` on Linux/macOS and expects an output file, hence the `cp` passthrough). Because `--import-sidecars` scans the whole folder, running it once per photo in a large batch is redundant, if harmless (it's idempotent — unchanged photos are skipped). For big batches, skip the BQM hook and just run `python facet.py --import-sidecars /path/to/folder` once by hand after the queue finishes.

## darktable

darktable already has first-class treatment in [Configuration — Viewer](CONFIGURATION.md#viewer) (`viewer.raw_processor.darktable` export profiles/styles) and [Viewer — Download](VIEWER.md#api-endpoints) (`type=darktable` conversions). On the XMP side: darktable authors its own `<image>.xmp` to store its edit history, and Facet's exiftool-backed sidecar writer merges into that same file in place — the `darktable:history`/mask nodes are preserved, never overwritten. No separate recipe is needed here; the two-way sidecar behavior described above for Lightroom (export/import, newest-wins, tag union) applies the same way, without the RAW naming mismatch since darktable and Facet agree on `<image><ext>.xmp`.

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
