# Contributing to Facet

Facet is a multi-dimensional photo analysis engine with a Python/FastAPI backend and an Angular 20 frontend. This guide covers the essentials for getting started and making changes.

## Development Setup

```bash
# Clone and set up Python environment
git clone git@github.com:ncoevoet/facet.git
cd facet
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install PyTorch with CUDA separately (adjust for your CUDA version)
# See https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# Build the Angular frontend
cd client
npm install
npx ng build
cd ..

# Run the web viewer (serves API + Angular SPA on port 5000)
python viewer.py

# Run scoring in preview mode (no database writes)
python facet.py /path/to/photos --dry-run

# Check your environment
python facet.py --doctor
```

## Architecture Overview

| Directory | Responsibility |
|-----------|---------------|
| `facet.py` | Main CLI entry point, `ModelManager` (VRAM-aware model loading), `BatchProcessor` (GPU batching) |
| `api/` | FastAPI application. Routers live in `api/routers/` (15 route modules: gallery, faces, albums, search, critique, etc.). Pydantic types in `api/types.py` and `api/models/`. |
| `config/` | `ScoringConfig` (weights/thresholds from `scoring_config.json`), `CategoryFilter` (rule evaluation), `PercentileNormalizer` |
| `models/` | Vision model wrappers: TOPIQ, CLIP, SigLIP, VLM taggers (Qwen), SAMP-Net (composition), BiRefNet (saliency) |
| `processing/` | Scoring pipeline: `batch_processor` (continuous GPU inference), `multi_pass` (pass orchestration), `scorer` (aggregate calculation) |
| `analyzers/` | Technical metrics, face analysis, composition analysis |
| `faces/` | Face detection (`processor`), HDBSCAN clustering (`clusterer`), merge analysis |
| `db/` | SQLite schema, connection pool, stats cache, maintenance utilities |
| `utils/` | Image loading, burst detection, duplicate detection, embedding helpers |
| `i18n/` | Translations for 5 languages (`en`, `fr`, `de`, `es`, `it`) |
| `client/` | Angular 20 SPA with standalone components and signal-based state management |

Other entry points: `viewer.py` (FastAPI server), `database.py` (schema migrations, stats, optimization).

## Adding a New Scoring Metric

Follow the checklist at [`.claude/patterns/new-metric-checklist.md`](.claude/patterns/new-metric-checklist.md). The high-level steps:

1. **Schema** -- Add column in `db/schema.py`
2. **Scorer** -- Wire into `processing/scorer.py` aggregate calculation
3. **Config** -- Add to `VALID_WEIGHT_COLUMNS` in `config/scoring_config.py` and set weights in `scoring_config.json`
4. **Model** -- Add loader in `models/model_manager.py`, register pass in `processing/multi_pass.py`
5. **API** -- Add range filter in `api/routers/gallery.py`
6. **Client** -- Add to photo model, tooltip, gallery store, filter sidebar, and sort options
7. **i18n** -- Add keys in all 5 translation files

## Adding a New API Endpoint

1. Create a router file in `api/routers/` (follow existing patterns, e.g., `api/routers/albums.py`)
2. Register the router in `api/__init__.py`
3. Define request/response models in `api/types.py` or `api/models/`
4. Add any user-facing strings to all 5 files in `i18n/translations/` using full dot-path keys (e.g., `ui.buttons.export`, not `buttons.export`)

## Code Style

### Python

- No backward-compatibility fallbacks. When renaming config keys, methods, or APIs, update all references and remove old names entirely.
- Use structured logging (the `logging` module), never `print()`.
- Type hints on function signatures.

### Angular

- Pure Tailwind CSS utilities only. Never define custom CSS classes in component `styles`.
- Use Angular `host` property for `:host` styling (e.g., `host: { class: 'block h-full' }`).
- Use pipes for template data transformation, not method calls (avoids unnecessary change detection).
- Prefer signals and `computed()` over RxJS for component state.
- Standalone components throughout.

### i18n

- Translation keys use the full dot-path from the JSON root: `ui.buttons.remove`, not `buttons.remove`.
- When adding or renaming strings, update all 5 language files. See [`.claude/patterns/i18n-sync.md`](.claude/patterns/i18n-sync.md).

## Testing

- **Angular**: Jest (`cd client && npx jest`)
- **Python**: pytest (`pytest`)
- **System diagnostics**: `python facet.py --doctor` (checks Python, GPU, dependencies, config, database)

## Pull Requests

- Branch from `master`.
- Keep PRs focused on a single concern.
- Include a test plan in the PR description.
- Rebuild the Angular client (`cd client && npx ng build`) before submitting if you changed frontend code.
