# i18n Sync Pattern

## Languages
All 5 translation files must stay in sync: `en.json`, `fr.json`, `de.json`, `es.json`, `it.json`

## Key Structure
Translation keys use **full dot-path from JSON root**:
- `ui.buttons.remove` (not `buttons.remove`)
- `ui.tooltip.aesthetic` (not `tooltip.aesthetic`)

## Adding New Keys
1. Add to `en.json` first (source of truth)
2. Add translated values to all other 4 files in the same location
3. Verify key paths match exactly across all files

## Common Sections
| JSON Path | Purpose |
|-----------|---------|
| `ui.tooltip.*` | Photo detail tooltip labels |
| `ui.sidebar.*` | Filter sidebar section headers |
| `ui.gallery.*_range` | Filter chip labels |
| `ui.buttons.*` | Action buttons |
| `dialog.*` | Dialog/modal strings |
| `manage_persons.*` | Face recognition management |

## Verification
After adding keys, check that Angular templates using `translate` pipe resolve correctly:
```
{{ 'ui.tooltip.new_key' | translate }}
```
