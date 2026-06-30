# VLM / Tagging Model Change Checklist

When adding, upgrading, renaming, or removing a VLM tagging/caption model, update ALL of
these locations. The `tagging_model` profile string (e.g. `qwen3.5-2b`) → tagger key
(e.g. `qwen3_5_tagger`) → config block (e.g. `qwen3_5_2b`) mapping is **duplicated across
~6 sites**; missing one causes a *silent* fallthrough to CLIP, not an error.

> Real regression this prevents: commit `3cf0604` renamed the 16/24gb `tagging_model` to
> `qwen3.5-2b/4b` and added the config blocks + loaders, but never updated
> `multi_pass._select_models` (and 4 other routing sites), so VLM tagging silently used CLIP
> on every scan. Caught only by inspecting the routing end-to-end.

## Config
1. **`scoring_config.json`** → `models.profiles.<profile>.tagging_model` — the profile's
   tagger string (and the profile `description`).
2. **`scoring_config.json`** → `models.<config_key>` — the model block
   (`{model_path, torch_dtype, max_new_tokens, vlm_batch_size}`). `model_path` must be a real
   HF repo — **verify it exists** (`curl -s -o /dev/null -w "%{http_code}" https://huggingface.co/api/models/<repo>`)
   and that its `config.json` `architectures` has the expected class with `vision_config`.

## Model loading
3. **`models/model_manager.py`** — `_model_loaders` dict: `'<tagger_key>': lambda: self._load_vlm_tagger('<config_key>')`.
4. **`models/model_manager.py`** — `_load_vlm_tagger` `key_map`: `'<config_key>': '<tagger_key>'`.
5. **`models/model_manager.py`** — `MODEL_VRAM_REQUIREMENTS` **and** `MODEL_RAM_REQUIREMENTS`:
   add a `<tagger_key>` entry (the default fallback is only 4GB / 2GB → mis-sized chunk planning if omitted).
6. **`models/vlm_tagger.py`** — only if a NEW model *family/architecture*: family detection
   (`__init__`), `default_paths`, `family_labels`, and the model-class import branch in `load()`.

## Routing (the sites 3cf0604 missed — all string/key matches)
7. **`processing/multi_pass.py`** — `_select_models()`: `tagging_model` string → `models.append('<tagger_key>')` (with VRAM gate).
8. **`processing/multi_pass.py`** — `_run_model_pass()`: add `<tagger_key>` to the `_pass_vlm_tagger` dispatch tuple, or the selected model silently no-ops.
9. **`processing/multi_pass.py`** — `_handle_oom()`: add a `<tagger_key>` → fallback entry.
10. **`processing/multi_pass.py`** — `run_single_pass()` (`--pass tags`): `tag_model` string → `model_name`.
11. **`processing/multi_pass.py`** — `--list-models` output table (informational).
12. **`facet.py`** — `_MOMENT_VLM_KEYS` (moment VLM tiebreak): string → tagger key.
13. **`facet.py`** — `--recompute-tags-vlm` block: `tag_model` → `model_key`.
14. **`facet.py`** — `--recompute-tags` VLM branch: add the string to the `elif tag_model in (...)` tuple **and** the inline `{...}[tag_model]` dict (KeyError if the tuple matches but the dict doesn't).
15. **`facet.py`** — the recompute-iqa / tagging `model_key_map` (~L1336): string → config_key.
16. **`api/routers/caption.py`** — `_resolve_vlm_config` `model_key_map`: string → config_key.

## Tests
17. **`tests/test_multi_pass.py`** → `TestTaggingModelRouting` — assert each profile string routes to its tagger AND that the tagger is dispatchable by `_run_model_pass`.

## Docs (English + translations fr/de/it/es/pt)
18. **`CLAUDE.md`** — VRAM profile table + the "Tagging:" line under Key Implementation Details.
19. **`docs/{,fr/,de/,it/,es/,pt/}{README,SCORING,COMMANDS,CONFIGURATION,VIEWER,INSTALLATION}.md`** — model names per `.claude/patterns/i18n-sync.md`.

## Verify before claiming done
- `grep -rniE 'qwen3[._]5|<old_name>' --include=*.py --include=*.json .` returns nothing stale.
- Trace one profile end-to-end: `tagging_model` string → tagger key → config block → real `model_path`.
- `python -m pytest tests/test_multi_pass.py tests/test_model_manager.py tests/test_caption.py`.

> **DRY follow-up:** sites 7–16 each re-implement the same string→key map. A single shared
> `tagging_model_to_key()` helper would collapse them and kill this bug class.
