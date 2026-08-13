# facet.lrplugin — in-Lightroom validation checklist (phase 2, 2026-08-12)

Built on `feat/improvements-2026-08` (`6b92d53`). Verified here: luaparser AST parse,
decoder suite (52 assertions) + applier end-to-end vs a stubbed LR SDK (75 assertions,
17 scenarios) under real Lua 5.5, Lua 5.1 static compat sweep, 10-test python manifest
contract, mutation-checked. NOT verified: anything only Lightroom Classic can run.

## Checklist (report back per step; screenshots where marked 📷)

- **A. Install** — copy `facet.lrplugin/` to the LR machine (zip first on macOS).
  File ▸ Plug-in Manager ▸ Add ▸ select folder. 📷 the Plug-in Manager row — must read
  "Installed and running"; report any red status verbatim.
- **B. Menu** — Library module, select ~20 photos, Library ▸ Plug-in Extras. 📷
  Confirm "Facet: Apply ratings and flags…" present and enabled.
- **C. Settings dialog** — 📷. Check nothing clipped; Browse… opens the picker over
  the dialog and fills the field.
- **D. Dry run (critical)** — point at a `facet_manifest.json` (from
  `facet.py --export-manifest`), scope = Selected, overwrite OFF, debug log ON.
  Preview… 📷. Sanity-check MATCHED vs NOT FOUND, then Cancel → confirm NO photo changed.
- **E. Path mapping** — if MATCHED is 0, the dialog prints a sample LR path beside a
  sample manifest path; fill the prefix pair from them and repeat D.
- **F. Apply** — repeat D then Apply. 📷 progress bar (does a cancel ✗ appear?) and the
  summary dialog. Verify in grid: stars appear, favorites = white Pick flag, rejects =
  black Reject flag, hand-rated photos unchanged.
- **G. Undo** — Ctrl/Cmd+Z once; report how many photos revert (expected 200 = one chunk).
- **H. Overwrite** — hand-rate a photo differently, run with overwrite ON, confirm replaced.
- **I. Folder scope** — pick a folder, scope = "All photos of the current folder";
  report "Photos in scope" vs the folder's real count.
- **J. Scale + cancel** — a ≥5k folder: preview and apply elapsed times, LR responsiveness,
  cancel mid-write behavior.
- **K.** Send back `facet-apply.log` (next to the manifest) + LR version/OS.

## Assumptions only LR can settle (suspect list if something misbehaves)

1. `LrSdkVersion = 15.0` in Info.lua — if the plugin refuses to load, suspect this first.
2. `LrProgressScope:setCancelable(true)` — pcall-guarded; a missing cancel ✗ is cosmetic.
3. `catalog:getActiveSources()`→`:getPhotos()` folder scope — degrades to a warning.
4. `getTargetPhotos()` on empty selection = whole filmstrip (preview count is the net).
5. `runOpenPanel` from a button inside a modal (wrapped in startAsyncTask) — step C.
6. `batchGetRawMetadata` keyed by photo object; unrated = `nil` or `0` (both handled).
7. `withWriteAccessDo(name, fn, {timeout=30})` semantics — LrTasks.pcall-wrapped.
8. `setRawMetadata('pickStatus', ±1)` actually flips the flag — the phase's whole point (F).
9. Undo granularity = one step per 200-photo chunk (G).
10. LrView properties (`width_in_chars`, `share`, radio groups) on Win vs macOS (C).
11. `require 'FacetJson'` resolving inside the bundle; `io.open` append for the log.
12. Lua 5.1 compat — static sweep only; executed under 5.5 here.

## GPU-box handoff (same branch, same trip)

- `pip install -r requirements.lock.txt` in the box's venv (transformers 5.15.0,
  pyiqa 0.1.16, safetensors 0.8.0).
- transformers 5.15 GPU checklist (recorded in requirements.lock.txt header):
  `--recompute-tags-vlm` on mixed sizes under 16gb, same under 24gb (Qwen3.5-4B never
  loaded locally), a caption + critique run, VRAM/OOM watch, Docker rebuild from the lock.
- Q-ReAlign A/B: `venv/bin/python scripts/qrealign_ab.py --db photo_scores_pro.db
  --sample 2000 --device cuda` (resumable; verdict table prints the ship gate).
  Swap/deprecation decisions only after the gate passes.
