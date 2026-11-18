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
2. Each flow in `flows/` owns one folder of the library. A flow that changes its folder first restores
   it (`seed_library.py reset <folder>`), so the flows run in any order and survive `--repeat-each`.
   A photo a flow deletes goes to `e2e/.work/xdg-data/Trash`, never to your own Trash.
3. `fixtures.ts` fails a flow on any page error, `console.error` or 5xx response, even when the
   assertions pass. It also names the URL behind a "Failed to load resource" message.

## When a flow fails

- `npx playwright show-trace test-results/<flow>/trace.zip` shows the page before and after
  every step, with the network calls and the console.
- `playwright-report/index.html` holds the run, with the screenshot of each failure (video is off: it would
  need Playwright's ffmpeg download).

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
| `05-route-smoke` | Each top-level page (`/albums`, `/capsules`, `/compare`, `/culling`, `/folders`, `/junk`, `/map`, `/persons`, `/scenes`, `/stats`, `/timeline`) loads on its own URL with no page error, console error or 5xx |
| `06-photo-page` | A double click on a gallery card opens that photo's page; the Quality panel carries the seeded score, the Histogram tab swaps the panel, and Back returns to the gallery |
| `07-album-lifecycle` | An album made through the API lists on `/albums`, opens to its photo, and leaves `/albums` once deleted while its photo stays in the library |
| `08-edition-gate` | Without the edition password a delete and an album create are refused, a wrong password is refused, and no photo is deleted |
| `09-gallery-sort-filter` | The gallery orders by score, flips on Ascending, and narrows by camera and by a minimum score; removing the chip restores the folder |
| `10-gallery-search` | A caption word narrows the grid to its photo, survives a reload, and clearing it restores the folder |
| `11-gallery-select-and-rate` | Review > Favorite and Review > Rate 4 in the selection bar apply to both selected photos; the favourites filter and the photo page read them back |
| `12-culling-confirm` | `/culling` proposes a keeper per burst; flipping a frame to kept and confirming rejects only the frame left out, and the gallery hides it |
| `13-login-ui` | The Edition dialog refuses a wrong password in place and unlocks with the right one; unlocked state survives a reload |
| `14-photo-page-review` | Rating, Favorite and Keep set on the photo page are read back after a reload |
| `15-photo-compare` | Two selected photos open the compare workspace (Reference / Candidate), the candidate can be promoted, and the page redirects without a selection |
| `16-timeline-and-folders` | The timeline month counts the day's photos and links to them; the Folders page filters the gallery to the clicked folder |
| `17-photo-page-metadata` | A caption, a manual tag and a one-hour capture-date shift made on the photo page are still shown after a reload |
| `18-add-to-new-album` | Add to Album > New Album from the selection bar creates the album with the selected photo only; deleting the album keeps the photo |
| `19-delete-selection` | Delete… in the selection bar: Cancel keeps both photos, confirming removes only the selected one |
| `20-persons` | The seeded person is listed, an in-place rename survives a reload, and View photos opens the gallery on that person's two photos |
| `21-map` | The two GPS photos give two single-photo markers (the third has no GPS); a marker opens a popup that closes |
| `22-shared-album` | A shared album opens by its link with no login, a wrong token is refused, and unsharing kills the old link |
| `23-scan-launcher` | The scan launcher (behind `features.show_scan_button`) offers the library folder, already chosen; no scan is started |
| `24-customize-shortcuts` | Rebinding Toggle favorite to G survives a reload; Reset all restores F |
| `25-connect-assistant` | A named assistant token is created (its prompt shown once), listed under Manage tokens and revoked |
| `26-download-selection` | Download saves each selected original; Copy filenames puts their names on the clipboard |
| `27-display-settings` | The Fast scrolling switch in Display persists across a reload |
| `28-portfolio-export` | Export portfolio waits for a target folder (allow-listed in the seed config) and writes the album's static site there |

Not covered yet: merge suggestions and the other persons tabs (the unnamed seed cluster does not reach "Needs naming"),
starting a scan (it would run the scoring models), the library export, and settings beyond the Display switches.

The edition login route allows 5 attempts a minute per address, so flows reuse one token (`editionToken` caches it,
`unlockEdition` hands it to the page) and only `13-login-ui` and `08-edition-gate` type or send a password. A flow that
provokes a 4xx on purpose declares it with `expectFailedLoad`.
