# Contributing to Facet

Facet is a photo analysis engine with a Python/FastAPI backend and an Angular 22 frontend.

## Development Setup

Fork the repository on GitHub, then:

```bash
# Clone your fork and set up the Python environment
git clone https://github.com/<you>/facet.git
cd facet
bash install.sh          # venv/, PyTorch for your GPU, deps, Angular build
source venv/bin/activate

# Run the web viewer (serves API + Angular SPA on port 5000)
python viewer.py

# Run scoring in preview mode (no database writes)
python facet.py /path/to/photos --dry-run

# Check your environment
python facet.py --doctor
```

Prefer to set the environment up yourself? See
[Installation › Install by hand](docs/INSTALLATION.md#install-by-hand-without-installsh).

Using an AI coding assistant? Point it at [`AGENTS.md`](AGENTS.md) and [`CLAUDE.md`](CLAUDE.md):
they collect the project rules and the feedback that comes up most in review.

## Architecture Overview

| Directory | Responsibility |
|-----------|---------------|
| `facet.py` | Main CLI entry point, `ModelManager` (VRAM-aware model loading), `BatchProcessor` (GPU batching) |
| `api/` | FastAPI application. Routers in `api/routers/`, Pydantic types in `api/types.py` and `api/models/` |
| `config/` | `ScoringConfig` (weights/thresholds from `scoring_config.json`), `CategoryFilter`, `PercentileNormalizer` |
| `models/` | Vision model wrappers: TOPIQ, CLIP, SigLIP, VLM taggers (Qwen), SAMP-Net, BiRefNet |
| `processing/` | Scoring pipeline: `batch_processor`, `multi_pass` (pass orchestration), `scorer` (aggregates) |
| `analyzers/` | Technical metrics, face analysis, composition analysis |
| `faces/` | Face detection, HDBSCAN clustering, merge analysis |
| `db/` | SQLite schema, connection pool, stats cache, maintenance utilities |
| `utils/` | Image loading, burst detection, duplicate detection, embedding helpers |
| `i18n/` | Translations for 7 languages (`en`, `fr`, `de`, `es`, `it`, `pt`, `zh`) |
| `client/` | Angular 22 SPA with standalone components and signal-based state |

Other entry points: `viewer.py` (FastAPI server), `database.py` (schema migrations, stats, optimization).

## Common Changes

- **New scoring metric** — follow [`.claude/patterns/new-metric-checklist.md`](.claude/patterns/new-metric-checklist.md) (schema, scorer, config, model pass, API filter, client, i18n).
- **New API endpoint** — add a router in `api/routers/` (e.g. `albums.py`), register it in `api/__init__.py`, define models in `api/types.py` or `api/models/`, then run `cd client && npm run gen:api` and commit the regenerated `schema.d.ts`.
- **New or renamed UI strings** — update all 7 files in `i18n/translations/`, then `cd client && npm run gen:i18n`. See [`.claude/patterns/i18n-sync.md`](.claude/patterns/i18n-sync.md).

## Code Style

### Python

- No backward-compatibility fallbacks. When renaming config keys, methods or APIs, update every reference and remove the old name.
- Use the `logging` module, never `print()`.
- Type hints on function signatures.

### Angular

- Tailwind CSS utilities only; no custom CSS classes in component `styles`. Use the `host` property for `:host` styling (e.g. `host: { class: 'block h-full' }`).
- Use pipes in templates, not method calls.
- Prefer signals and `computed()` over RxJS for component state. Standalone components throughout.
- Icon-only buttons need an `aria-label` (CI checks this). Never use a raw i18n key as a label; translate it.
- Show dates as `dd/MM/yyyy`.

### i18n

- Keys use the full dot-path from the JSON root: `ui.buttons.remove`, not `buttons.remove`.
- Every key exists in all 7 language files.

## Tests

- **A new test must fail when your fix is removed.** Check it: revert the fix, see the test fail, restore. Tests that only check a response's shape, or mock away the code they claim to cover, are sent back.
- Build test databases with `db.schema.init_database` or the `seeded_photos` / `seed_photos_prefix` fixtures in `tests/conftest.py`, never a hand-written `CREATE TABLE photos`. See [`.claude/patterns/test-fixtures.md`](.claude/patterns/test-fixtures.md). The only exceptions are schema-migration tests (which must construct the *old* schema to migrate from) and minimal-schema tests that prove the schema itself; everything else — even a two-column stub — goes through the fixtures, because a hand-rolled schema keeps passing after the real one gains a column.
- For auth, use the `edition_client` / `regular_client` / `superadmin_client` / `anonymous_client` fixtures or `app.dependency_overrides`, never `mock.patch` on a FastAPI dependency (it silently does nothing).

## Before You Open a PR

Run what CI runs:

```bash
venv/bin/python -m ruff check .
venv/bin/python -m pytest tests/ -q
python scripts/check_mypy_ratchet.py     # from a venv holding only mypy
python scripts/audit_i18n.py             # translation bundles match en.json

cd client
npm test
npx ng lint
npx tsc --noEmit -p tsconfig.app.json && npx tsc --noEmit -p tsconfig.spec.json
npm run gen:api && npm run gen:i18n      # commit any change these produce
```

Typecheck the two projects above, not the root `tsconfig.json`: it compiles nothing and always passes.

Optional local hooks run ruff, the auth-mock guard and the commit-message guard (no `Claude-Session:` or
`Co-Authored-By: Claude` trailers; CI rejects them too):

```bash
pip install pre-commit
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Without pre-commit, use `git config core.hooksPath .githooks` instead. Pick one: `pre-commit install` refuses
to run while `core.hooksPath` is set.

## Pull Requests

- Branch from `master`. Keep each PR to a single concern.
- Update the English docs in `docs/` when you change behaviour.
- If you changed frontend code, rebuild the Angular client (`cd client && npm run build`) before submitting.
- Add a `CHANGELOG.md` entry under `## [Unreleased]`, in the matching section (`### Added`, `### Fixed`, ...).
- **Don't edit the translated docs** (`docs/<lang>/`, `README.<lang>.md`). The maintainer updates the translations.
- Leave **Allow edits by maintainers** on. The maintainer may push fixes to your branch, so pull before pushing again, and never force-push.
- CI on a fork waits for maintainer approval before it runs. A PR is merged once every required check is green on its latest commit.
