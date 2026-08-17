# Next session plan — after the 2026-08-17 contract / cull / test program

The previous plan is fully executed and archived as `completed-plan-post-1.13.0.md`.
That work is `aa23e8b..ea16c2d` — 33 commits, pushed to master, CI green on all four jobs.

## Where things stand

**Baselines measured at session end:** python `3256 passed, 7 skipped`; client
`111 files, 1931 tests`; ruff, both leaf typechecks, `ng lint` and both i18n gates clean.
CI runs all of it plus a Windows job.

**What landed**, one line each: two i18n CI gates and a *real* client typecheck (the
documented one compiled nothing and always exited 0); an API↔client contract test that
now asserts wire **types** across 13 endpoints; a test-quality sweep removing the fixtures
that made failure impossible; 0/1-flag and nullable-`aggregate` normalisation; cull
correctness for multi-frame sets; the CodeQL taint class killed at source; and
cull×sequence documentation in six languages.

**Read before re-deriving anything:**
- `.claude/reports/review-2026-08-17-phase-abc.md` — the review that found a data-loss bug
  *after* every gate was green. Its finding numbers are referenced below.
- `.claude/specs/post-1.13.0-todo.md` — working notes and the browser-test recipe. Its
  checkboxes are stale; the git log is authoritative.

---

## 1. Phase D — `response_model` + generated TS  (large, untouched)

Unchanged from when it was scoped: **4 of 188 routes declare a `response_model`** (all in
`api/routers/auth.py`) against **73 client call sites with a declared type**, plus ~38
called with none. No codegen tooling exists anywhere in the repo.

**The trap, verified on 3 of 3 spot-checks — do not skip it.** `api/models/gallery.py` is
not a starting point:

- `GalleryResponse` requires `total_count`; `api_photos` emits `total`. Attaching it as-is
  500s every gallery request.
- `SimilarPhotosResponse` requires a `weights` no code path emits.
- `response_model` **filters** by default, so `total`, `per_page` and `hidden_summary` —
  all consumed by `gallery.store.ts` — would be silently stripped, breaking the gallery
  with a 200.
- 7 of its 8 models are dead; only `GalleryParams` (a request model) is live.

Fix the models to match the handlers, never the reverse, one endpoint at a time with the
contract test green after each. Every optional column must be `Optional[...] = None`:
`build_photo_select_columns` composes the column list at query time from
`PHOTO_BASE_COLS ∪ (PHOTO_OPTIONAL_COLS ∩ the DB's actual columns)`.

**DECIDED 2026-08-17: Phase D will generate the TypeScript types from OpenAPI.** The open
question below still stands and is not answered by that choice — it is what the choice
*costs*, and it must be settled before the first generated type lands.

**Decide this before starting.** `tests/test_api_contract.py` now parses the TS interfaces
and asserts wire types — for optional fields too, as of 2026-08-17 — with six documented
exceptions (`_KNOWN_WIRE_TYPE_EXCEPTIONS`, one per member of `PHOTO_FLAG_FIELDS`: they
arrive as SQLite 0/1 because the client coerces at ingest rather than changing the wire).
If types become **generated** from OpenAPI, that test's premise changes — client and
server could no longer disagree by construction, and those exceptions become a question
about the wire itself rather than about a declaration. Either narrow the contract test
to the hand-written interfaces, or retire it for `Photo`.

verify per endpoint: contract test green **and** the endpoint's response byte-compared
before/after. Not "tests pass" — the failure mode is a silently *smaller* 200.

## 2. E1 — the bracket-render judgment  (needs your eyes, not code)

`raw_decode.faithful_bracket_render` ships **on**, rendering a −3.42 EV frame at mean
5.8/255. Correct, measured, never actually looked at across a library.

Easier now than the last plan assumed: `--check-raw-rendering` was made **kind-aware and
path-mapped** this session, so it renders a bracketed frame under the profile it will
really get, and no longer reports "No readable RAW photos found" on a mapped library. Try
it before writing any contact-sheet script.

**Sample the distribution, not set 68.** 226 bracket sets / 775 frames; **176 are
3-frame**; only 5 exceed a 5.4 EV span. Set 68 is the library's widest at 6.74 EV, so its
5.8/255 is the worst case, not the representative one — judging on it alone biases toward
reverting. Take ~6 sets: 2 narrow (±1 EV), 2 mid, 2 wide.

Recorded ladder for set 68 (means, in EV order −3.42 / −1.74 / 0.00 / +1.58 / +3.32):
as-shipped `53.7 / 52.7 / 51.7 / 77.0 / 134.5`; preview `10.5 / 29.0 / 66.2 / 124.8 / 184.0`;
faithful `5.8 / 16.5 / 38.5 / 80.4 / 139.8`.

Do **not** point the viewer at `photo_scores_pro.db`. It has no read-only mode
(`api/database.py` connects with a plain path and `apply_pragmas` issues
`PRAGMA journal_mode = WAL`, a header write), and its set panels render the **stored**
thumbnail — `render_version` is NULL on all 126,661 rows, so they show the pre-1.13.0
render and are actively misleading for this comparison.

Reverting is one config key with no data migration: `db/render_version.py:54-71` derives
the expected stamp from `renders_faithfully`, pinned by `tests/test_render_version.py`.

## 3. Leftovers from the review

Both 🔵 SUGGESTED findings are now settled (2026-08-17):

- **F22 — DECIDED, keep in place.** `api/routers/export.py:442` `_reassign_dead_leads` stays
  where it is. `move_rejects` / `trash_rejects` touch only the filesystem, so a removed
  panorama lead keeps satisfying `HIDE_PANORAMAS_SQL` until a rescan prunes the row; moving
  the re-pick into the detection pass would leave the whole set invisible in the default
  gallery until the next `--detect-sequences`. Its docstring already carries this rationale.
  The finding was SUGGESTED, and relocating a DB write out of a destructive endpoint's path
  is a behaviour change with a user-visible failure mode — not a cleanup.
- **F23 — DONE, no work needed.** `tests/test_api_contract.py` already routes every photo
  seed through `conftest.py`'s `seed_photos_prefix` (14 call sites). The two remaining
  `sqlite3.connect(DB_PATH)` calls in that file are not the seed idiom: line 247 reads
  `PRAGMA table_info(photos)` and line 466 writes a `stats_cache` row.

---

## 4. Known and unfixed — read before touching these

- **CORRECTED 2026-08-17 — `CullingConfirmBody.group_id: int` is right; there is no latent
  422.** The earlier claim that `burst_group_id` is a TEXT column was wrong. `db/schema.py:61`
  declares it `INTEGER` (as it does `duplicate_group_id:69` and `sequence_group_id:75`), both
  writers push Python ints (`processing/scorer.py:2751`, `utils/duplicate.py:214`), a live
  `GET /api/photos` returns a JSON int, and the real library reports `typeof = 'integer'`
  across all 20 013 distinct groups. The actual error was on the **client**, which declared
  `burst_group_id` / `duplicate_group_id` as `string | null` — fixed, along with the badge
  bug that hid behind it (`burst_group_id` counts from **0**, and `photo-card.component.ts`
  gated the "Best" badge on a truthiness test, so the first burst group could never show it).
- **A bracket that loses its base exposure cannot be repaired.** The lead re-pick added
  this session helps panoramas only: `HIDE_BRACKETS_SQL` keys on `sequence_ev_offset = 0`,
  a physical fact of the exposure rather than a movable mark. Documented at the function.
- **Mixed-group rule is deliberate**: a burst group containing a sequence frame keeps that
  frame out of comparison pairs but can still reject it — a bad tile is still a bad photo.
  Pinned by a test. 62 of 20013 real burst groups are mixed.
- **RESOLVED 2026-08-17 — `mapGearItem`'s positional coupling is gone.** `api_stats_gear`
  now aliases every aggregate and reads rows by key (`_gear_rows` in `api/routers/stats.py`),
  and the three copy-pasted camera/lens/combo blocks are one helper, so adding a column can
  no longer shift a value onto the wrong key. Evidence: the `/api/stats/gear` response is
  byte-identical before and after, on a fixture that exercises both the six `or 0`
  fallbacks and the six fields that pass NULL through as JSON `null`.
- **Many i18n keys are unreferenced** — 813 of 2166 when last counted (bundles are now 2188
  keys). The audit gate checks both directions but not reachability.
- **Tailwind v4 `cursor-pointer`**: the preflight sets `button { cursor: default }`, no gate
  catches it, and the next button added will need it again. A lint rule was considered and
  deliberately not added.

## 5. Working notes

- **Follow groundwork's SPEC phase.** It was skipped last session because the main thread
  had just done the exploration; the rule now says explicitly that this is not a reason.
  Spawn the sub-agent, let it write `.claude/specs/<slug>.md`.
- **Phase 7 REVIEW is new and earned its place.** Reviewing the integrated diff found a bug
  that destroyed photos the user had explicitly kept — after 3223 tests, ruff, both
  typechecks and lint were all green. Budget for it; one pass is not enough on a large diff.
- **Briefing parallel agents**: exclusive file lists; name the neighbours siblings hold;
  forbid `git checkout`/`stash`/`reset`; require foreground verification (four agents
  stalled waiting on watchers that never existed); require pasted failing-first evidence.
  See the `feedback_subagent_briefing_rules` memory.
- **`.claude/patterns/test-fixtures.md` is new** — read it before writing a test that needs
  photo rows. Three suites had hand-rolled partial `photos` schemas, one blind to 39 of 50
  optional columns.
- Browser testing: full recipe in `post-1.13.0-todo.md`. Chrome refuses ports 5060/5061
  (`ERR_UNSAFE_PORT`), and `pkill -f "viewer.py --port N"` matches and kills your own shell.
- Quota check: `bash ~/.claude/plugins/marketplaces/ncoevoet-loop/skills/goal-loop/scripts/watch-quota.sh --once`
