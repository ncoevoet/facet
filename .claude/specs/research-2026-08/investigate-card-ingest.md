# Investigation brief — Card/folder ingest

**Repo:** `/home/ncoevoet/work/photoscore` (Facet) · branch `feat/improvements-2026-08`
**Roadmap line:** `.claude/specs/improvement-roadmap-2026-07.md:83` — *"Card/folder ingest (rename templates, destination rules → auto-scan)"*, second tier, effort **M**
**Precedents cited by the roadmap:** Photo Mechanic (commercial); Rapid Photo Downloader (`https://damonlynch.net/rapid/`)
**Adjacent, SHELVED:** `.claude/specs/facet-roadmap.md:159-182` item 6b — `viewer.py --cull` SD-import onboarding wizard
**Adjacent, SHIPPED (do not confuse):** WebDAV inbox `api/routers/webdav.py`; `--watch` polling `processing/watcher.py`

**VERDICT: BUILD-DIFFERENTLY** — build the copy/date-foldering engine, **drop the rename-template half entirely**, and be honest that its full value is gated on item 6b being unshelved. Rationale in §7.

---

## 1. Repo side — what primitives actually exist

### 1.1 Detecting a mounted card — **NOTHING**

No code anywhere enumerates removable-media mount points. `grep` over the tree for `/media`, `/run/media`, `/Volumes` returns only one hit: the **prose** of the shelved 6b spec (`.claude/specs/facet-roadmap.md:171`), which *proposes* a safe-roots list `(/media, /mnt, /run/media, /Volumes, $HOME)` for a live directory browser. It is not implemented. There is no `psutil.disk_partitions` call, no udev/`gio` integration, no mount watcher.

**Consequence:** any "insert card → Facet notices" behaviour is greenfield. It is also *exactly* the surface 6b already scoped and shelved, so building it CLI-side now would be the second implementation of a design nobody has validated once.

### 1.2 Copying files with templates — **copy: yes (HTTP-coupled). Templates: nothing.**

| Primitive | Location | Reusable for ingest? |
|---|---|---|
| `_copy_or_link_into(paths, target_dir, mode)` — `shutil.copy2` or `os.symlink`, per-file try/except, returns `(copied, skipped, errors)` | `api/routers/export.py:296` | **Pattern yes, code no.** Raises `HTTPException`, calls `resolve_photo_disk_path` (DB-backed). CLI must not import FastAPI. |
| `_unique_dest(target_dir, filename)` — numeric-suffix collision avoidance | `api/routers/export.py:402` | **Pattern yes** — this is the never-overwrite policy already shipped. |
| `_validate_target_dir` (realpath + allow-list, fail-closed) / `_contained_dest` | `api/routers/export.py:255,281` | HTTP-coupled; the *shape* is the canonical containment idiom in this repo. |
| `_companion_files(disk_path)` — companion RAW + `.xmp` sidecar siblings | `api/routers/export.py:325` | Same idea needed at ingest, but source-side (group by `(dir, stem)`), no DB. |
| `_contained(root, *parts)` | `processing/portfolio_export.py:44` | Non-HTTP containment helper — closest existing clean analogue. |
| Atomic streamed write: temp file in the destination dir + `os.replace` | `api/routers/webdav.py:230-246` | **Directly instructive.** This is how the repo already lands a file safely; ingest should mirror it (`.part` temp + `os.replace`) so a yanked card never leaves a half-file that a later scan indexes. |

**No template/token engine exists.** `strftime` is used in 8 places (`db/maintenance.py:203`, `api/config_writes.py:69`, `analyzers/capsule_generator.py:592`, …) but always with a hardcoded pattern. There is no user-supplied filename pattern anywhere in the codebase.

### 1.3 Triggering a scan on new files — **three working paths, all reusable**

1. **Plain CLI.** `python facet.py <dir>` → `facet.py:1206` walks `args.photo_paths`, filters to `{'.jpg','.jpeg'} | HEIF_EXTENSIONS | RAW_EXTENSIONS` (`facet.py:1200`), then `Facet.filter_unscanned_paths` (`processing/scorer.py:2609`) drops anything already keyed in `photos.path`. **Incremental detection is pure path-primary-key membership** — no mtime, no hash. So *copying a file into an already-scanned tree and re-running the scan picks it up, and re-running over unchanged files is a no-op.* This is the single most important fact for ingest: **the "auto-scan" half of the roadmap line is already free.**
2. **`--watch` daemon.** `processing/watcher.py:62 run_watch_loop` — watchdog observer (inotify, falling back to `PollingObserver` on `OSError`, i.e. NAS), a debounced `_PendingChanges` accumulator (`:27`), then `subprocess.run(cmd)` of a fresh `facet.py` (`:114`), 3-strikes failure bail (`:24`). `_build_scan_command` (`:54`) is the exact "spawn a scan as a child" idiom ingest should copy.
3. **Viewer API.** `api/routers/scan.py:130 start_scan` — superadmin-gated, `Popen` + reader thread, SSE at `:267`, argv rebuilt from the server-side allow-list at `:169` so args are provably server-origin. `_spawn_fixed_library_job` (`:377`) is the shared fixed-argv spawner.

**`api/scan_runtime.py` does not exist.** The 6b spec proposes extracting it out of `api/routers/scan.py`; that extraction has not happened. Any viewer-side ingest surface inherits that same refactor debt.

### 1.4 Config keys around upload/scan directories

Top-level `scoring_config.json` keys (verified by loading the shipped file): `upload` = `{username:"", password:"", inbox_dir:"", max_file_mb:500}` — **all empty by default, which 404s the whole `/dav` tree** (`api/routers/webdav.py:66`). `viewer.scan_directories` = `[]`. `viewer.export` is **absent** from the shipped config, so `_allowed_export_roots` (`api/routers/export.py:238`) currently falls back to the scan directories only.

`config/scoring_config.schema.json` declares 21 top-level `properties` and **no `additionalProperties: false`** — `upload`, `frame`, `storage` etc. are all unlisted and validate fine. **Adding an `ingest` block therefore requires no schema change** (adding one is optional polish; `tests/test_config_schema.py::test_shipped_config_is_valid` stays green either way).

### 1.5 Free-space guard — **exists, directly reusable**

`db/maintenance.py:127 check_disk_space(target_path, needed_bytes, margin=1.2) -> (ok, free, required)`. Probes the volume of `target_path` (dir, or the file's dirname) with `shutil.disk_usage`. Calling convention and the operator escape hatch are both already modelled at `facet.py:1341-1355`: estimate → check → on failure log GB-needed vs GB-free and `exit(1)` unless `--force-low-space` (`facet.py:1727`). Ingest should reuse *both* the function and the flag idiom verbatim; unlike the scan's `bytes_per_photo_estimate` heuristic, ingest knows the **exact** byte total (sum of `os.path.getsize` over the source set), so its guard is strictly more accurate than the one already shipped.

### 1.6 LibraryLock — **ingest does not need it; the scan it spawns takes it itself**

`facet.LibraryLock` (`facet.py:970`) is a `flock`-based cross-process mutex over `<db_dir>/.facet_cache/library.lock`, acquired via `_acquire_library_lock(args, LIBRARY_JOB_*)` for anything in `LIBRARY_JOB_ARGS` (`facet.py:630`). The scan takes it at `facet.py:3559`.

**An ingest run writes zero DB rows.** It copies files and prints a summary. It must therefore *not* hold the lock — holding it would block the very scan it wants to hand off to. The precedent is already written down in the test suite: `tests/test_scan.py:1616 _LOCK_EXEMPT_WRITERS['watch']` — *"a supervisor that spawns scans; the scan it spawns takes the lock, and the daemon itself must not hold it for days."* `--ingest` is the same shape.

⚠️ **Hard gate discovered:** `tests/test_scan.py:1644 TestLibraryJobCoverage` asserts (a) every argparse `dest` is classified into exactly one of `LIBRARY_JOB_ARGS` / `_LOCK_EXEMPT_WRITERS` / `_JOB_MODIFIERS` / `_READ_ONLY_LIBRARY_COMMANDS` / `_NON_LIBRARY_WRITERS`, and (b) no classification names a dead flag. **A new flag fails the suite until it is classified.** This is by design and is a required step, not an incident.

### 1.7 What the DB can and cannot tell you about "already imported"

`PHOTOS_COLUMNS` (`db/schema.py:18-172`) has **no content hash and no file size**. The only hash is `phash` (`db/schema.py:99`) — a *perceptual* hash written during scoring (`processing/batch_processor.py:325`, `processing/scorer.py:1265`) via `imagehash.phash(pil_img)`, i.e. it requires a **full image decode**, RAW included. It cannot be computed cheaply at ingest time and it is not a file-identity hash (two different JPEG renditions of one RAW share it).

Available at ingest time, cheaply and indexed:
- `photos.path` — PRIMARY KEY.
- `photos.filename` — `idx_filename` (`db/schema.py:274`).
- `photos.date_taken` — `idx_date_taken` (`db/schema.py:256`), stored in raw EXIF form.

So the honest dedupe options are: **destination-path existence** (free, no DB), **size+mtime match against an existing destination file** (one `stat`), and a **`SELECT filename` advisory probe** for "this name already exists elsewhere in the library." Content hashing is possible but is a deliberate, opt-in cost (see §4).

---

## 2. Rapid Photo Downloader — what its template syntax actually is, and what subset to take

Fetched from `https://damonlynch.net/rapid/documentation/`:

- **Date/time tokens:** 27 preset choices — `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD`, `MMDDYYYY`, `DDMMYYYY`, full/abbreviated month and weekday names, `HHMMSS`, `HH-MM-SS`, combinable ad libitum ("combine the options to fit your liking, e.g. `YYYY-MM`"). Three date sources: capture metadata, today, download-session time.
- **Filename tokens:** `Name` (stem), `Image number` (camera sequence, configurable digit count).
- **Metadata tokens:** aperture, ISO, exposure time, focal length, camera make/model (full + shortened), serial number, shutter count, owner name.
- **Sequence tokens:** four kinds — *Downloads Today* (resets daily), *Stored number* (persistent), *Session number* (per run), *Sequence letters* (`a…z, aa…zz`). All increment **on successful download**, i.e. they are persistent mutable state RPD owns.
- **Dedupe:** *"Rapid Photo Downloader compares a file's size, name, and modification time to determine if it has downloaded it before."* — **attribute-based, not hash-based.** Confirms that a size+name+mtime rule is the mature-precedent behaviour, not a shortcut.
- **Verification:** the documentation **does not describe any checksum or hash verification** of downloads or backups.
- **Backup:** multiple simultaneous destinations, mirrored structure, overwrite-or-skip policy on collision.

**Minimal compatible subset to adopt — and what to reject:**

| RPD feature | Take? | Why |
|---|---|---|
| Date-based **subfolder** generation | ✅ **Take** | The one thing rsync genuinely cannot do. This is the feature. |
| RPD's `YYYY`/`MM`/`DD` token dialect | ❌ **Reject** | Python `strftime` (`%Y/%Y-%m-%d`) is already the syntax this codebase uses in 8 places and needs zero parser, zero docs table, zero tests. Inventing a second date dialect is pure cost. Ship `{date:%Y/%Y-%m-%d}` — one placeholder, one `strftime` call. |
| **Rename** templates | ❌ **Reject** (see §7) | Highest risk, lowest value; breaks JPEG+RAW pairing and sidecar association. |
| Sequence numbers (*Downloads Today* / *Stored number*) | ❌ **Reject** | Persistent mutable counters = new state to own, migrate, reset, and reason about across concurrent runs. Never worth it for a rename feature we're not shipping. |
| Metadata tokens (ISO/aperture/serial) | ❌ **Reject** | Nobody folders by aperture. Cost is a token table + 10 tests each. |
| size+name+mtime dedupe | ✅ **Take** | Mature precedent, one `stat` call, no re-read of the card. |
| Multi-destination backup | ❌ **Reject** | That is what a backup tool is for. |
| Copy verification | ✅ **Take, but go further than RPD** | RPD doesn't verify at all. Cheap size+mtime assert by default; opt-in checksum. |

---

## 3. Template engine — exactly what to reuse, ~15 lines

**EXIF read before the copy:** `exiftool/exiftool_batch.py:267 get_exif_batch(image_paths, chunk_size=50, timeout_per_chunk=30)` → `dict[path_str, {date_taken, camera_model, lens_model, iso, f_stop, shutter_speed, focal_length, focal_length_35mm, gps_latitude, gps_longitude}]`. Backed by a persistent `exiftool -stay_open` process (`ExifToolBatch`, `:21`) with a chunked-subprocess fallback (`get_metadata_batch`, `:133`, invoked as `['exiftool','-j','-n'] + chunk`). Handles every RAW format Facet supports. Re-exported as `from exiftool import get_exif_batch` (`exiftool/__init__.py`) — the import used at `facet.py:2234` and `processing/batch_processor.py:95`.

**Date parse:** `utils/date_utils.py:6 parse_date(date_str)` accepts `%Y:%m:%d %H:%M:%S` — the exact shape exiftool's `DateTimeOriginal` returns under `-n` (verified: `-n` affects numeric tags, not date formatting). Returns `datetime` or `None`.

**Therefore the entire engine is:**

```python
dt = parse_date(exif.get('date_taken')) or datetime.fromtimestamp(os.path.getmtime(src))
subdir = dest_template.format(date=dt)     # "{date:%Y/%Y-%m-%d}" -> "2026/2026-08-12"
```

`str.format` already implements `{date:%Y-%m-%d}` via `datetime.__format__`. **No parser, no token table, no new module.** Guardrails needed: reject a template containing `..` or an absolute prefix, reject any field name other than `date`, and realpath-contain the rendered path under the destination root (idiom: `api/routers/export.py:281`).

**Do NOT reuse** `processing/scorer.py:2213 Scorer.get_exif_data` — it is a 4-tier fallback ladder (exiftool → subprocess → exifread → Pillow) but it is a *method on the scorer class*, whose module pulls torch, pyiqa, insightface and the whole model stack. Importing it for a file-copy tool would be a multi-second, multi-GB import. Ingest uses `get_exif_batch` + `os.path.getmtime` as the fallback, which is sufficient because a mistimed folder is recoverable and a 6-second import is not worth avoiding it.

**RAW extension set to walk:** `utils/image_loading.py:31 RAW_EXTENSIONS` + `HEIF_EXTENSIONS` + `{'.jpg','.jpeg'}` — identical to `facet.py:1200`. `processing/watcher.py:19 WATCH_SUFFIXES` is a hardcoded duplicate of the same set; **do not add a third copy** — import the shared constants (and note the watcher duplication as pre-existing, out of scope to fix here per the surgical rule).

---

## 4. Safety analysis

### 4.1 Source is removable media and may vanish mid-copy

The failure to design for is not "the card is missing at startup" — it is **the card yanked at file 400 of 900**. Consequences and mitigations:

- `shutil.copy2` on a vanished source raises `OSError` mid-stream, leaving a **truncated destination file**. If that file has a `.jpg` extension, the very next scan indexes a corrupt image into `photos`, and because incremental detection is path-keyed (`processing/scorer.py:2609`) it will **never be re-examined**. This is the single worst failure mode in the whole feature.
  → **Mitigation (mandatory):** copy to `<dest>.facet-ingest-<rand>.part` in the *destination directory*, `fsync`, verify, then `os.replace`. Exactly the WebDAV `PUT` idiom (`api/routers/webdav.py:230-246`, `_TMP_PREFIX`/`_TMP_SUFFIX`/`_safe_unlink`). A partial file then never carries a photo extension and is invisible to both the scanner and the watcher (`.part` ∉ `WATCH_SUFFIXES`).
- Enumerate the source **once, up front** (full list + sizes), so an ejection produces "copied 400/900, source disappeared" rather than a silently short run.
- On any `OSError` whose `errno` is `ENODEV`/`EIO`/`ENOENT` on the source root: **abort the whole run**, do not continue to the next file, and **do not spawn the scan.** Report what landed.

### 4.2 Destination collision policy — never overwrite

Three-way, in this order:
1. **Identical file already there** (same size *and* same mtime, ±2 s for FAT32's 2-second mtime granularity): **skip, count as `already_present`.** This is RPD's rule and it makes re-running an interrupted ingest idempotent.
2. **Different file, same name:** numeric suffix — `IMG_0042.CR3` → `IMG_0042-1.CR3`. Reuse the `_unique_dest` policy (`api/routers/export.py:402`).
3. **Never `os.replace` onto an existing path.** The temp-file dance targets a name proven free (or suffixed) immediately before the rename; a TOCTOU loser gets another suffix.

`os.makedirs(subdir, exist_ok=True)` per rendered date folder; containment-check the rendered path before creating anything.

### 4.3 Free space

`check_disk_space(dest_root, total_source_bytes, margin=1.05)` before copying a single byte, refuse with the GB-needed/GB-free message and a `--force-low-space` escape (mirror `facet.py:1341-1355`). Margin can be tighter than the scan's 1.2 because the byte total is measured, not estimated — but keep headroom for the thumbnails/embeddings the follow-up scan will write into the DB **if the DB lives on the same volume** (check `os.stat().st_dev` equality; if same, add the scan's own `bytes_per_photo_estimate × count`).

### 4.4 LibraryLock

**Ingest: no lock.** It writes no DB rows. Classify as `_LOCK_EXEMPT_WRITERS` in `tests/test_scan.py:1616` with the same justification string shape as `watch`.
**Post-copy scan: locks itself.** Spawned as a `subprocess` of `facet.py` exactly like `processing/watcher.py:114`, so it takes `LIBRARY_JOB_SCAN` in its own process (`facet.py:3559`). If another library job holds the lock, the child exits cleanly with the conflict message — ingest reports "copied N; scan deferred (library busy)" and exits 0. **The copy is not wasted work if the scan can't run**; a later `facet.py <dir>` or a running `--watch` picks the files up, because detection is path-keyed.

### 4.5 Delete-on-verify

Available as `--ingest-clear-card`, but **recommend NOT shipping it in v1**. It is the only irreversible operation in the feature; cameras reformat cards more reliably than an unlink loop; and the checksum verification it must be gated behind doubles the read cost of the card. If it ships anyway: require `--ingest-verify checksum` to have *passed for that file*, delete per-file only after its own verify, never `rmtree` a directory, and never touch a file the run skipped as `already_present`.

### 4.6 Path traversal / template abuse

`dest_template` is user-supplied and renders into a filesystem path. Even for a local CLI, apply the repo's fail-closed idiom: reject `..` segments, reject `os.path.isabs`, reject any `{field}` other than `date`, and `realpath`-contain the final path under the destination root (`api/routers/export.py:281`). This matters *disproportionately* because the module is the natural backend for a future 6b/viewer endpoint, where the template becomes attacker-influenced. Getting containment right once, in the module, is what makes that later reuse safe.

---

## 5. Deliverable shape

### 5.1 New files

| Path | Contents | Est. lines |
|---|---|---|
| `processing/ingest.py` | `IngestPlan` / `IngestResult` dataclasses; `plan_ingest(source, dest_root, dest_template, db_path)` → per-file `(src, rendered_dest, action)` where action ∈ `copy|skip_present|skip_in_library`; `run_ingest(plan, verify, force_low_space)`; `render_dest(template, dt)`; `_group_companions(files)`. **No FastAPI, no torch, no DB writes.** | ~230 |
| `tests/test_ingest.py` | Unit tests, `tmp_path` only, no GPU, no models. | ~280 |

### 5.2 Changed files

| Path | Change |
|---|---|
| `facet.py` | New `ingest_group = parser.add_argument_group('Ingest')` with the flags below; dispatch **before** `if not args.photo_paths` (`facet.py:3543`), because `--ingest` supplies its own paths; on success spawn the scan via the `_build_scan_command` idiom. ~35 lines. |
| `tests/test_scan.py` | Classify `ingest` into `_LOCK_EXEMPT_WRITERS` (`:1616`) and the modifier flags into `_JOB_MODIFIERS` (`:1623`). **Required — the suite fails otherwise.** |
| `scoring_config.json` | New top-level `ingest` block (§5.4). |
| `docs/COMMANDS.md` + `docs/{fr,de,it,es,pt}/COMMANDS.md` | New "Card / folder ingest" subsection under `## Scanning` (`docs/COMMANDS.md:9`), mirroring the one-row `--watch` treatment at `:30`. |
| `docs/CONFIGURATION.md` + 5 translations | The `ingest` config block. Precedent: the WebDAV commit added 24 lines × 6 CONFIGURATION.md files. |
| `CHANGELOG.md`, `CLAUDE.md` | One line each; `CLAUDE.md` only if an invariant is worth carrying (the `.part`-then-`os.replace` rule is). |

**No** new dependency (`pyproject.toml` untouched — everything is stdlib + the already-required `exiftool` binary, itself already optional with fallbacks). **No** schema change (`config/scoring_config.schema.json` has no `additionalProperties: false`). **No** DB migration. **No** i18n bundle changes (CLI-only ⇒ `client/src/assets/i18n/*` untouched, `test_audit_i18n.py` unaffected).

### 5.3 CLI flags

```
--ingest SOURCE              Copy photos from SOURCE (card/folder) into the library, then scan
--ingest-dest DIR            Destination root (default: ingest.dest_root, else the first viewer.scan_directories entry)
--ingest-template TPL        Destination subfolder template (default: ingest.default_dest_template)
--ingest-verify {size,checksum}   Post-copy verification (default: size)
--ingest-dry-run             Print the plan (src -> dest, action) and exit; copy nothing
--ingest-no-scan             Copy only; do not spawn the follow-up scan
```

Deliberately **absent**: `--ingest-rename` (§7), `--ingest-clear-card` (§4.5), any card auto-detect (§1.1).

### 5.4 Config block

```json
"ingest": {
  "dest_root": "",
  "default_dest_template": "{date:%Y/%Y-%m-%d}",
  "verify": "size",
  "scan_after_ingest": true,
  "skip_hidden": true
}
```

`dest_root: ""` = unset ⇒ fall back to `viewer.scan_directories[0]`; if that is also empty, refuse with an actionable message (fail-closed, matching `_validate_target_dir`'s posture at `api/routers/export.py:255`). Document that empty means "not configured", not "anywhere" — the repo has been bitten by that inversion before (`CLAUDE.md` "Key Configuration Defaults" table).

### 5.5 Effort

**2 sessions.** Session 1: `processing/ingest.py` + `tests/test_ingest.py` + the CLI flag/dispatch/classification. Session 2: verification pass on a real card or a simulated one, docs ×6, CHANGELOG, review.

Calibration against comparable shipped features in this repo:
- `--watch` (`136895b`): 6 files, +177 lines, no tests. Simpler than ingest (no filesystem writes to get right).
- WebDAV inbox (`9a7b3bc`): 327-line router + 6 CONFIGURATION.md files + VIEWER.md. Ingest is ~⅔ that, plus a real test file the WebDAV commit skipped.

A viewer surface would be a **separate +2–3 sessions** and should not be attempted before item 6b's `api/scan_runtime.py` extraction lands (§1.3).

---

## 6. Step list, each with a verify

1. **`processing/ingest.py` — enumeration + planning (no writes).** Walk `source` with `os.walk` honouring `skip_hidden`, filter on the shared `RAW_EXTENSIONS | HEIF_EXTENSIONS | {'.jpg','.jpeg'}`, batch-read EXIF via `get_exif_batch`, render each destination, classify each as `copy` / `skip_present` / `skip_in_library`.
   *key decision:* date source when EXIF is absent. *default:* `os.path.getmtime` — a card always has an mtime, and a wrong folder is recoverable where a crash is not.
   → **verify:** `pytest tests/test_ingest.py -k plan` — a `tmp_path` fixture with a JPEG whose `DateTimeOriginal` is known renders `2026/2026-08-12/IMG_0001.JPG`; an EXIF-less file falls back to its mtime folder; a hidden dir is excluded.
2. **Template rendering + containment.** `render_dest` rejects `..`, absolute templates, and any field but `date`; final path realpath-contained under `dest_root`.
   → **verify:** parametrised test asserting `{date:%Y}/../../etc`, `/etc/{date:%Y}`, and `{camera}` each raise; `{date:%Y/%Y-%m-%d}` renders correctly.
3. **Free-space guard.** `check_disk_space(dest_root, total_bytes, 1.05)`; add the scan's own estimate when `st_dev(dest_root) == st_dev(db_path)`; refuse unless `--force-low-space`.
   → **verify:** test patching `db.maintenance.shutil.disk_usage` (the exact idiom already used at `tests/test_backup.py:81`) asserts refusal, and that `force_low_space=True` proceeds.
4. **Copy engine.** Per file: `.part` temp in the destination dir → `shutil.copyfileobj` → `fsync` → verify → `os.replace` onto a name proven free (or numeric-suffixed) → `shutil.copystat`. Any source `OSError` aborts the run and `_safe_unlink`s the temp.
   → **verify:** (a) test that a mid-copy source failure leaves **no** file with a photo extension in the destination and **one** fewer copied; (b) test that a destination collision with different content produces `IMG_0001-1.JPG` and leaves the original byte-identical; (c) test that re-running the same ingest reports every file `already_present` and rewrites nothing (compare `st_mtime_ns` before/after).
5. **Companion grouping.** Group source files by `(dirname, stem.lower())` so a JPEG+RAW pair lands in the *same* destination folder even if only one of them carries EXIF.
   *key decision:* whose date wins for the pair. *default:* the RAW's, falling back to whichever member has EXIF — because `facet.py:1272-1280` pairs on `(dir, stem)` and splitting a pair across two date folders silently breaks that pairing, causing the RAW to be scored as a separate photo.
   → **verify:** test with `IMG_1.CR3` (EXIF-dated) + `IMG_1.JPG` (EXIF-less) asserts both land in one directory with the same stem.
6. **CLI wiring + lock classification.** Add the flags, dispatch before the `photo_paths` requirement check (`facet.py:3543`), spawn the scan with the `_build_scan_command` idiom unless `--ingest-no-scan`, classify every new dest in `tests/test_scan.py`.
   → **verify:** `venv/bin/python -m pytest tests/test_scan.py -k LibraryJobCoverage tests/test_cli.py -q` green; `venv/bin/python facet.py --ingest <tmp> --ingest-dest <tmp2> --ingest-dry-run` prints a plan and exits 0 **without importing torch** (assert with `-X importtime | grep -c torch` = 0, or a test asserting `'torch' not in sys.modules`).
7. **End-to-end on real files.** Ingest a throwaway folder of ~30 mixed JPEG/RAW into a scratch library, let the spawned scan run.
   → **verify:** destination tree matches the template; `sqlite3 <db> "SELECT COUNT(*) FROM photos WHERE path LIKE '<dest>%'"` equals the copied count; a second identical ingest copies 0 and scans 0; `git diff scoring_config.json` empty.
8. **Docs ×6 + CHANGELOG.**
   → **verify:** `grep -c 'ingest' docs/COMMANDS.md docs/{fr,de,it,es,pt}/COMMANDS.md` non-zero for all six; `venv/bin/python -m ruff check .` clean; full `venv/bin/python -m pytest tests/ -q` green (capture `${PIPESTATUS[0]}`).

**Final gate:** full pytest green + ruff clean + the step-7 e2e observed (not inferred) + a deliberate mid-copy interruption (`kill -9` during a large RAW copy) leaving zero photo-extension files in the destination.

---

## 7. Skeptical assessment — why BUILD-DIFFERENTLY, not BUILD

### What the roadmap line asks for vs what is defensible

The line is *"rename templates, destination rules → auto-scan"*. Three parts. Evidence says they have wildly different value:

**"→ auto-scan" is already shipped, twice.** Detection is path-primary-key membership (`processing/scorer.py:2609`), so any file dropped into a scanned tree is picked up by the next `facet.py <dir>`, and `--watch` (`processing/watcher.py`) automates that. Building "auto-scan" would be building nothing.

**"destination rules" is the real gap and it is genuinely small.** EXIF-date foldering is the one thing `rsync -a --ignore-existing` cannot do, and it is ~15 lines here (§3) because `get_exif_batch` and `parse_date` already exist. This is worth building.

**"rename templates" should be dropped.** Concretely:
- Renaming breaks JPEG+RAW pairing. `facet.py:1272-1280` pairs on `(dirname, stem.lower())`; a rename template that produces different stems for `IMG_0042.JPG` and `IMG_0042.CR3` — which any template involving a per-file sequence number does — causes the RAW to be scored as a **separate photo**, silently doubling the library.
- It orphans `.xmp` sidecars, which the repo's own cull path resolves by stem (`api/routers/export.py:325 _companion_files`).
- RPD's own rename tokens require four kinds of persistent, mutable sequence counters. That is new state to own, reset, migrate and reason about concurrently — for a cosmetic result.
- The camera filename is the user's index back to the physical card. Photo Mechanic users rename because they file by job code for clients; that is a pro workflow Facet does not otherwise serve anywhere.

Cost/benefit is strongly negative. **Drop it, and say so in the docs so the roadmap line is closed rather than left half-done.**

### Does the rest duplicate `rsync` + `--watch` for too little gain?

Partly, and this deserves a straight answer. For a CLI-comfortable user, the alternative already exists and is one line:

```
exiftool -o . '-Directory<DateTimeOriginal' -d ~/Photos/%Y/%Y-%m-%d /media/card/DCIM
```

That covers copy + EXIF date foldering. What it does *not* cover: a free-space pre-check, `.part`-atomic writes against a yanked card, idempotent re-runs, JPEG+RAW co-location when only one carries EXIF, and the scan handoff. Those are real, and four of the five are the difference between "works" and "silently corrupts a library" — §4.1 is not hypothetical, because a truncated `.jpg` that lands in a scanned tree is **permanently** cached by path-keyed incremental detection.

So the gain over `rsync` is a safety gain, not a convenience gain. That is worth ~230 lines. It is not worth a template DSL.

### The audience objection — the strongest argument against building at all

The user who wants card ingest is either:
1. a pro who already owns Photo Mechanic or runs RPD — a CLI flag in a scoring engine will not displace either; or
2. the non-CLI user from the 6b origin (`.claude/specs/facet-roadmap.md:160`, Reddit: *"far too complex … I should be prompted for the SD mount by the browser on launch"*) — **for whom a CLI flag is worth exactly zero.**

Neither audience is served by `--ingest` alone. The roadmap itself rates it **M / second tier**, which is consistent.

**This is why the recommendation is BUILD-DIFFERENTLY rather than BUILD:** build `processing/ingest.py` as a **clean, FastAPI-free, DB-free library module** whose value proposition is explicitly *"the safe copy engine that item 6b's wizard will call"*, with a thin CLI as its first (and testable) consumer. Scoped that way it is 2 sessions, has no dependencies, cannot regress scoring, and turns 6b's hardest un-scoped piece — "what happens to the files" — into solved, tested code. Scoped as "Photo Mechanic for Facet" it is a multi-session template engine serving nobody.

**If item 6b is definitively never going to be built, downgrade this to SKIP.** The CLI-only version's marginal value over `exiftool -o . '-Directory<...'` + `--watch` does not justify 2 sessions on its own. That conditional is the honest bottom line, and it is a decision for the maintainer, not something this brief can settle.

### Unverified / open questions

- **UNVERIFIED — needs a real card:** FAT32/exFAT mtime granularity (2 s) and timezone handling on the mtime fallback path. The ±2 s tolerance in §4.2 is derived from the FAT spec, not observed here. Needs one test against an actual SD card before the `already_present` rule can be called correct.
- **UNVERIFIED — needs measurement:** `get_exif_batch` throughput over ~1000 RAW files on a slow card reader. `facet.py:2247` uses `chunk_size=500, timeout_per_chunk=120` for NAS, suggesting the defaults (50/30 s) may time out on slow media. Measure before choosing the ingest chunk size.
- **Open:** whether `exiftool` being *absent* should block ingest. It is optional everywhere else in the repo (four-tier fallback at `processing/scorer.py:2213`). Suggested default: fall back to file mtime with a one-line warning, since a mistimed folder is a nuisance and a hard failure is a blocker — but this is a real fork worth confirming.
