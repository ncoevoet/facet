# New Metric Checklist

When adding a new scoring metric to Facet, update all of these locations:

## Backend
1. **`db/schema.py`** — Add column (`REAL` or `TEXT`) to `photos` table
2. **`api/db_helpers.py`** — Add to `PHOTO_OPTIONAL_COLS` list
3. **`processing/scorer.py`** — Add to `metrics_map` in `calculate_aggregate_logic()`
4. **`scoring_config.json`** — Add model config + wire into category weights if needed
5. **`processing/multi_pass.py`** — Register pass and model selection logic
6. **`models/model_manager.py`** — Add loader, VRAM/RAM requirements, CPU cacheable if applicable

## API
7. **`api/routers/gallery.py`** — Add `add_range_filter()` call + `normalize_params()` entries (min/max)

## Client
8. **`client/src/app/shared/models/photo.model.ts`** — Add field (`number | null`)
9. **`client/src/app/features/gallery/photo-tooltip.component.ts`** — Add display in relevant section
10. **`client/src/app/features/gallery/gallery.store.ts`** — Add filter fields to interface + defaults + all 4 `stringKeys` arrays
11. **`client/src/app/app.ts`** — Add `RANGE_CHIPS` entry for filter chip display
12. **`client/src/app/features/gallery/gallery-filter-sidebar.component.ts`** — Add slider in relevant section

## Sort Options
13. **`scoring_config.json`** → `viewer.sort_options` — Add sort option in appropriate group

## i18n (all 5 languages)
14. **`i18n/translations/{en,fr,de,es,it}.json`** — Add keys for:
    - `ui.tooltip.<metric>` — Tooltip label
    - `ui.sidebar.<section>` — Section header (if new section)
    - `ui.gallery.<metric>_range` — Filter chip label
