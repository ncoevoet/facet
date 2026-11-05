# Browser flows (Playwright)

End-to-end flows that drive the real viewer (`viewer.py --production`) in Chrome, step by step,
for paths the unit and component tests cannot see: several clicks in a row, the service worker's
thumbnail cache, what the gallery shows after a server-side change. See #464.

## Run

```bash
cd client
npm ci
npx ng build                     # the flows test the production build
FACET_E2E_PYTHON=../venv/bin/python npm run e2e
```

- **Browser:** the installed Chrome (`channel: 'chrome'`), so nothing is downloaded. Set
  `FACET_E2E_CHANNEL=chromium` after `npx playwright install chromium` to use Playwright's own.
- **Python:** `FACET_E2E_PYTHON` is the interpreter with Facet's dependencies (default `python`).
- **Port:** 5099 (`FACET_E2E_PORT`).
- Not part of `npm run test`.

## What a run does

1. `seed_library.py serve` rebuilds `e2e/.work/`. It writes a config with an edition password,
   a database made by `db.schema.init_database`, and a library of synthetic solid-colour photos
   whose rows are written directly. There are no models and no scan, so the seed takes about a
   second. It then starts the viewer on that library.
2. Each flow in `flows/` owns one folder of the library, so the flows do not depend on one another.
3. `fixtures.ts` fails a flow on any page error, `console.error` or 5xx response, even when the
   assertions pass. It also names the URL behind a "Failed to load resource" message.

## When a flow fails

- `npx playwright show-trace test-results/<flow>/trace.zip` shows the page before and after
  every step, with the network calls and the console.
- `playwright-report/index.html` holds the run, with the screenshot and video of each failure.

## Writing a flow

- One spec per user journey, with numbered `test.step`s, so a failure names its step.
- Select by role and accessible name (`getByRole('button', { name: … })`), never by CSS classes.
- No fixed sleeps: use `expect` (which retries) or wait for a response.
- Keep the service worker on (the default here). A stale-cache bug only shows with it.
- To check that the right picture is on screen, sample a pixel (`centrePixel`) rather than
  trusting the `src`.
- A flow for a fixed bug must fail with that fix removed. Check it once by hand.

| Flow | Checks |
|---|---|
| `01-ai-edit-burst-strip` | The gallery shows a burst once, as its leading AI edit; the original's strip labels the edit "AI edit" and opens it |
| `02-hide-bursts` | Hide bursts folds each burst behind its lead; Show all brings every frame back |
| `03-reused-name-new-picture` | An edit imported under a deleted edit's name shows the new picture, not the cached thumbnail (fails without `apply_ai_edit_captions`' fresh `preview_revision`) |
| `04-delete-burst-lead` | Deleting the AI edit that leads its burst keeps the burst in the gallery (fails without `_reassign_dead_burst_leads`) |
