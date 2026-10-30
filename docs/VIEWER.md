# Web Viewer

> 🌐 **English** · [Français](fr/VIEWER.md) · [Deutsch](de/VIEWER.md) · [Italiano](it/VIEWER.md) · [Español](es/VIEWER.md) · [Português](pt/VIEWER.md) · [简体中文](zh/VIEWER.md)

The viewer is a FastAPI + Angular web app for browsing, filtering, culling and managing your photos.

## Contents

- [Starting the Viewer](#starting-the-viewer) · [Authentication](#authentication) · [Filtering Options](#filtering-options) · [Sorting](#sorting) · [Review decisions](#review-decisions) · [Gallery Features](#gallery-features)
- [Panoramas and exposure brackets](#panoramas-and-exposure-brackets)
- [Person Management](#person-management) · [Scan Trigger](#scan-trigger) · [Semantic Search](#semantic-search) · [Albums](#albums)
- [AI Critique](#ai-critique) · [AI Captioning](#ai-captioning-gpu-16gb24gb-edition) · [Memories ("On This Day")](#memories-on-this-day) · [Timeline View](#timeline-view) · [Map View](#map-view) · [Capsules](#capsules)
- [Folders View](#folders-view) · [GPS Filter Dialog](#gps-filter-dialog) · [Merge Suggestions](#merge-suggestions) · [Editor Export](#editor-export) · [Download](#download) · [Culling](#culling) · [Junk Sweep](#junk-sweep) · [Pairwise Comparison Mode](#pairwise-comparison-mode)
- [EXIF Statistics](#exif-statistics) · [Keyboard Shortcuts](#keyboard-shortcuts-gallery) · [Undo](#undo) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile) · [Photo Frame / Kiosk Endpoint](#photo-frame--kiosk-endpoint) · [Phone Auto-Upload](#phone-auto-upload)
- [Configuration](#configuration-2) · [Performance](#performance) · [API Endpoints](#api-endpoints) · [JPEG XL photos](#jpeg-xl-photos) · [Troubleshooting](#troubleshooting)

> **Feature requirements** are tagged inline: `[GPU]` · `[16gb/24gb]` (VRAM profile) · `[Edition]` (edition password) · `[Superadmin]`. See the [feature matrix](INSTALLATION.md#feature-requirements).

> **AI assistants**: Facet can serve its tools to MCP-capable assistants. With the right token level they can search, change and cull the library. See [AI Agents (MCP)](AGENTS.md).

## Starting the Viewer

### Production

```bash
python viewer.py
# Open http://localhost:5000
```

This serves the API and the pre-built Angular app on one port.

For higher throughput, run production mode (Uvicorn, no auto-reload). Add `--workers N` to scale (default 1):

```bash
python viewer.py --production --workers 4
```

### Development

Run the API server and the Angular dev server separately:

```bash
# Terminal 1: API server
python viewer.py
# API available at http://localhost:5000

# Terminal 2: Angular dev server with hot reload
cd client && npx ng serve
# Open http://localhost:4200 (proxies API calls to :5000)
```

## Authentication

### Single-User Mode (Default)

Protect the viewer with an optional password:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Two passwords control access:

- **`viewer.password`** decides who may *browse*. Empty means anyone can browse the whole library. Set, users must log in first.
- **`viewer.edition_password`** is required for every edit: ratings, favorites and rejects, culling, albums, person and face management, comparison mode, weight and priority changes, and exports. Empty (the shipped default) makes the install **read-only**: edits are refused with `403` ("Set viewer.edition_password to enable editing").

On-demand AI generation (captions, VLM critiques) also needs the edition password. Without it you get only what is already cached (`source: "none"` or `vlm_available: false`). With no edition password, the gallery also hides existing star, favourite and reject badges, as it does for non-edition viewers on a password-protected install.

Restart the viewer after setting `viewer.edition_password`: the config is not hot-reloaded.

> **Warning:** with an empty `viewer.password` (the shipped default), anyone who can reach the viewer's port can browse the library and download the originals. `viewer.py` listens on all interfaces by default (`--host 0.0.0.0`, which the Docker image relies on). Set `viewer.password` before exposing it beyond your own machine, or bind to loopback with `--host 127.0.0.1`. In Docker, publish the port as `127.0.0.1:5000:5000`. The viewer logs a startup warning while `viewer.password` is empty (unless told to bind loopback).

Login also sets the session token in an `HttpOnly` `SameSite=Lax` cookie, so thumbnails and the scan progress stream load on password-protected installs. The cookie is honored for read-only requests (GET/HEAD) only; edits still need the Bearer token. Logging out (`POST /api/auth/logout`) clears it.

### Multi-User Mode

For a family NAS where each member has private photo folders. Add a `users` section to `scoring_config.json`:

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

Write each `directories` and `shared_directories` entry exactly as the scanner stored the path. Matching ignores ASCII case on Windows, macOS, and for UNC or drive-letter entries. It is case-sensitive everywhere else (Linux, for example). Non-ASCII case differences, and a mapped drive the host cannot resolve, do not match.

Create users from the CLI (there is no registration page):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

See [Configuration](CONFIGURATION.md#users) for the full reference.

### Roles

| Role | View own + shared | Rate/favorite | Manage persons/faces | Trigger scans |
|------|:-:|:-:|:-:|:-:|
| `user` | yes | yes | no | no |
| `admin` | yes | yes | yes | no |
| `superadmin` | yes | yes | yes | yes |

### Photo Visibility

Each user sees photos from their own directories plus the shared directories. This applies everywhere: gallery, thumbnails, downloads, stats, filter options and person pages.

### Per-User Ratings

In multi-user mode, star ratings, favorites and rejects are stored per user in the `user_preferences` table. Alice's favorites don't affect Bob's view.

To migrate existing single-user ratings:

```bash
python database.py --migrate-user-preferences --user alice
```

## Filtering Options

Gallery text search keeps Unicode words and treats filename punctuation as word boundaries. `IMG_0042.JPG` searches for the prefixes `IMG`, `0042` and `JPG` together. Cyrillic and CJK terms work. FTS operators such as `OR` are treated as literal words.

### Sidebar Tabs

The filter sidebar groups its sections into five tabs, shown as icons (hover for the name). A small badge on an icon counts the active filters inside that tab, and the tab keeps its name for screen readers ("Browse, 2 active"). The last tab you used is remembered in this browser (`facet_sidebar_tab`). Browse, Quality and Subject keep collapsible panels, each remembering whether it is open; Review and Display have none.

| Tab | Sections |
|-----|----------|
| **Browse** | Semantic Search, Persons, Date Range, Content, Albums, Location, Folder, Equipment |
| **Review** | One menu row each for the decision, then bursts, duplicates, blinks, brackets, panoramas and rejected, a star rating, Favorites and Monochrome toggles and, for editors, *Manual faces need review* and *Panorama corrections* |
| **Quality** | Quality, Color & Quality, Extended Quality, Technical, Exposure & Range (how good the image is) |
| **Subject** | Face Metrics, Composition, Subject Saliency, Moments (what is in the frame) |
| **Display** | View (card size, layout, fast scrolling, card actions) |

The header, **Find a filter**, the smart-album notice and the filename search stay above the tabs on every tab, so `/` works from any of them. Typing in **Find a filter** hides the tabs and lists the matching sliders from all of them.

The count next to **Filters** is the total of all active filters. A min/max range counts once, and so does the location filter. The filename search and *Similar to* have no section, so they are counted in this total only, and so is a filter on a metric this install hides, so that **Reset Filters** can still clear it. **Reset Filters** (with a tooltip) appears next to the count while at least one filter is active; the plain **X** at the far right only closes the sidebar on narrow screens.

On the Review tab, the decision and each set (for example Duplicates) is one row showing its current value (such as Hidden, Shown or Only these) that opens a menu of choices, each with a one-line explanation. A row left on its default value does not count toward the tab or header badge. *Only* and *Hidden* exclude each other. While a decision is chosen, Rejected is locked, and its tooltip says why. The star button sets a minimum rating: each click raises it by one, and the click after 5, or after a maximum that came in from a link, clears it. It shares a row with the icon-only Favorites and Monochrome toggles, which have tooltips. On the Quality and Subject tabs, hovering a setting's name explains what is scored and by which model, and the Review controls have tooltips too.

<details><summary>Full filter sidebar — every section expanded (click to view)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="The five filter sidebar tabs side by side: Browse, Review, Quality, Subject and Display" width="900"></p>
</details>

### Primary Filters

| Filter | Options |
|--------|---------|
| **Photo Type** | Top Picks, Portraits, People in Scene, Landscapes, Architecture, Nature, Animals, Art & Statues, Black & White, Low Light, Silhouettes, Macro, Astrophotography, Street, Long Exposure, Aerial & Drone, Concerts |
| **Quality Level** | Good (6+), Great (7+), Excellent (8+), Best (9+) |
| **Camera & Lens** | Equipment-based filtering |
| **Person** | Filter by recognized person |
| **Category** | Filter by photo category |

### Advanced Filters

| Category | Filters |
|----------|---------|
| **Date** | Start and end date |
| **Scores** | Aggregate, aesthetic, TOPIQ score, quality score |
| **Extended Quality** | Aesthetic IAA (artistic merit), Face Quality IQA, LIQE score |
| **Face Metrics** | Face quality, eye sharpness, face sharpness, face ratio, face confidence, face count |
| **Composition** | Composition score, power points, leading lines, isolation, composition pattern |
| **Subject Saliency** | Subject sharpness, subject prominence, subject placement, background separation |
| **Technical** | Sharpness, contrast, dynamic range, noise level |
| **Color** | Color score, saturation, luminance, histogram spread; color temperature and hue bucket (need `--recompute-colors`) |
| **Exposure** | Exposure score |
| **User Ratings** | Star rating |
| **Camera Settings** | ISO, aperture (f-stop range slider), focal length (range slider) |
| **Content** | Tags, monochrome toggle |
| **Moments** | Narrative moment confidence (0–1 slider: `min_moment_confidence` / `max_moment_confidence`) |

Some range filters match only photos that have a value, so even a filter starting at 0 excludes unscored photos:

- **Aesthetic IAA, Face Quality IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA**: a photo the model could not score has no value. An ascending sort on these lists it last, in the gallery and in albums. See [Supplementary IQA Dimensions](SCORING.md#supplementary-iqa-dimensions).
- **Subject Sharpness, Subject Placement, Background Separation, Power Points**: a photo with no detectable subject has no value, and the detail panel omits the row. Subject Prominence is 0.0 for such a photo. See [SCORING.md](SCORING.md).

### Composition Patterns

Filter by the 8 patterns SAMP-Net detects (from `models/samp_net.py`):
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Sorting

The sort button in the header (and mobile toolbar) shows the current sort's icon; its tooltip reads `Sort by: <current sort>`. It opens a grouped menu of every sort. The ascending/descending toggle sits next to it. Alternate scoring models use short labels (IAA, 2.5, Q-R, DeQA, LIQE and IQA).

**Remembered sort.** The gallery opens on the sort you last picked, overriding `viewer.defaults.sort`. The choice is stored per browser in `localStorage`, not per account.

- Only a pick in the sort menu is remembered. A sort from a shared link or an assistant is not, and a link's own `sort` wins.
- Picking the configured default again, or resetting the filters, forgets the choice.
- **Relevance** is never remembered, because it needs a search query.

Shutter speeds sort by duration, so `1/250` and `0.004` are equal. Missing or invalid values sort last in either direction.

Sortable columns by group (from `viewer.sort_options`):

| Group | Columns |
|-------|---------|
| **General** | Aggregate Score, Aesthetic, Quality Score, Date Taken, Star Rating, Aesthetic (IAA), LIQE Score, Q-ReAlign (Aesthetic), DeQA, Aesthetic v2.5 (the last three appear once a photo has that score) |
| **Face Metrics** | Face Quality, Face Quality (IQA), Eye Sharpness, Face Sharpness, Face Ratio, Face Count |
| **Technical** | Tech Sharpness, Contrast, Noise Level |
| **Color** | Color Score, Saturation |
| **Exposure** | Exposure Score, Mean Luminance, Histogram Spread, Dynamic Range |
| **Composition** | Composition Score, Power Point Score, Leading Lines, Isolation Bonus, Composition Pattern |
| **Subject Saliency** | Subject Sharpness, Subject Prominence, Subject Placement, Background Separation |
| **Content** | Moment Confidence (NULLs sink) |

### My Taste

Sorts by the personal ranker's `learned_score`: what it has learned from your A/B comparisons, ratings and culling decisions. A badge next to the sort shows coverage (% of photos with a learned score) and the ranker's held-out accuracy, so you can judge how far to trust it. Train or refresh the ranker with `python facet.py --train-ranker`.

Controlled by `viewer.features.show_my_taste` (default: `true`). Ranker status: `GET /api/ranker/status`.

### Metrics hidden in commercial mode

With `licensing.mode` set to `commercial`, the viewer hides metrics whose models cannot be used commercially: LIQE, Aesthetic IAA, Face Quality IQA (unless OFIQ is installed), DeQA (unless `licensing.allow_unclear` is set) and Aesthetic V2.5. Their filters, chips and sort options disappear; `/api/config` lists them in `unavailable_metrics`. On the Weight Tuning page their sliders stay visible but disabled, and scoring drops and renormalises those weights. Restart the viewer after changing the licensing mode.

## Review decisions

Use **Review status → Needs review** in the gallery to work through undecided photos. This view sorts by **Date Taken, oldest first**; you can reverse it or narrow it by date, folder or album. Choosing a review status exits semantic and Similar Photos searches.

- **Keep** a photo you want; **Reject** one you don't. Either removes it from Needs review. Find kept photos with the **Kept** status filter.
- Keep is independent of favorites and star ratings.
- Keep and **Reset decision** are in photo detail, the context menu and bulk actions. Press **K** (remappable, see [Keyboard Shortcuts](#keyboard-shortcuts-gallery)) to keep the current photo. In photo detail, Keep toggles.
- **Reset decision** clears Keep and Reject without touching stars or favorite.
- Decisions survive reloads, restarts and rescans. On multi-user installs they belong to the current user.
- Confirming a culling group marks its keepers as Kept. Existing ratings and favorites are not converted into Keep decisions.

**Progress counts.** The gallery shows **undecided**, **kept** and **rejected** counts for the whole visible folder, album or filtered scope, not just the loaded page. The percentage is `(kept + rejected) / total`. The Review status and Hide rejected toggles do not shrink the total; other filters do.

**Resume a queue.** **Review undecided** starts a queue. **Continue reviewing** reopens your most recent Needs review queue on this browser at its first remaining undecided photo.

- The bookmark is per browser and per signed-in identity (up to 20 identities). It does not sync across devices.
- Changing filters does not replace it unless you open another Needs review queue.
- Album queues use the album's current saved criteria.
- Temporary burst/sequence groups are not bookmarked, because a rescan can renumber them.
- Logging out clears every review-queue bookmark on this browser.

**Floating notices.** Review progress, **Continue reviewing**, the hidden-photos notice, the active-filters notice (with **Reset all filters**) and the thumbnail-migration notice stack at the bottom right.

- Each card's × hides it for the current browser tab. It returns in a new tab, or when the notice changes (another scope, a changed hidden count, a filter added or removed).
- To hide review progress for good, use the user menu's **Hide review progress** / **Show review progress**. This is stored per browser and also hides the **Review undecided** button.
- After a few seconds idle the stack folds into a small count pill. Hover or click it to unfold.

## Gallery Features

### Manual photo stacks

Select **2–1000 explicit photos**, then choose **Stack photos** on the selection bar or press **S** to open the full-page editor at `/stacks/edit`. A whole-view selection cannot create a stack. S opens a preview; it never saves directly. User menu → **Customize shortcuts** changes the gallery binding, and the toolbar tooltip, Help and `?` reference show the current key. If an older saved mapping already uses S, that binding is preserved and Stack starts **Unassigned** until you choose a free key. Editing access is required. A photo belongs to one manual stack per owner. The page centers a zoomable preview above a persistent thumbnail strip. Click a thumbnail or use `←`/`→` to focus a photo, then choose its cover, order or remove controls. Use the zoom button, wheel or double-click to inspect details.

Use **Cmd+Shift+S** or **Ctrl+Shift+S** to stack explicit unstacked photos immediately in selection order, with the first selected photo as cover. Existing stack members open the editor for review. Success clears the committed selection, and Undo restores it; cancellation or failure retains it. Escape in the editor returns to the originating gallery without saving.

**Reject while stacking.** Focus a photo in the full-page editor or stack editor dialog and use **Reject** or **R**. The focused frame in the Suggested stacks darkroom has the same action; open the darkroom first to choose it. Reject immediately saves the ordinary review decision, clearing Keep, favorite and stars, and excludes only that photo from the proposed stack. It never deletes or writes original files. The count and dimmed darkroom thumbnails show exclusions. Undo restores prior review values and relevant draft membership without replacing later order or cover choices; later review edits can prevent Undo. Already-rejected photos remain until explicitly excluded, without another review decision. Grouping still waits for Save; leaving without saving does not undo Reject.

When selected photos already belong to stacks, **Combine stacks** is the default: the preview includes their other members. **Selected photos only** moves just the explicitly selected photos. The editor shows selected and resulting counts, extra members and a source-effects summary; expand its details to inspect each source stack. Members left behind stay together when at least two remain; a lone remainder becomes unstacked, and an empty source disappears. Excluding a photo from the new stack leaves it in its source under those same rules. The final stack and all affected photos are each limited to 1000; unavailable or partially visible sources are refused. Switching policies preserves surviving order, cover and exclusions.

Review the server-refreshed preview, then choose **Stack photos** to save. The page stays open to inspect the result; the notification offers **Undo** while it remains available and revisions still match. **Continue editing** fetches a fresh preview before another save. **Back to gallery** returns to the originating gallery or album with its exact URL and expires the previous Undo. Leaving without saving discards grouping changes; an explicit Reject persists. A browser reload restores the selection only for the same account, after fresh authorization; opening the URL without valid selection state offers a way back.

Open the count badge or a stacked photo to browse permitted members in the photo viewer. The thumbnail strip, previous/next buttons and position counter follow stored stack order; arrow keys stay within the stack. **Manage stack** opens a secondary dialog: click a thumbnail or use Left/Right to inspect its large preview, choose **Cover**, reorder with the arrow buttons, or remove members. Opening that editor alone retains ordinary membership editing: removing a member un-stacks it, removing the cover selects the first surviving member, and fewer than two members or **Unstack** dissolves the stack. Explicitly **Add selected photos** from another stack switches to the regroup preview and its two policies. Organization edits preserve files and review values; the separate explicit Reject action changes review values immediately.

- Rating, Keep/Reject, metadata, download, album and delete actions never expand a stack implicitly.

**In the gallery.** A stack folds into one tile; **Expand all stacks** is a remembered preference. Filters and album membership apply to individual photos: the cover shows if it matches, otherwise the first matching member does. Stack browsing bypasses automatic burst/duplicate hiding. Timeline and map show individual photos.

**Selecting.** Selecting a folded tile selects only the displayed photo. Open the stack and use **Select all N members** for all of them. **Select all in view**, percentile selection and assistant `target:view` include every matching photo, folded members too, and whole-view actions show the real photo count first. In API/assistant summaries, `total` counts displayed tiles and `photo_total` counts photos.

**Privacy and persistence.**

- Stacks are private to their owner (the installation, in single-user mode). Editing needs edition access.
- They are absent from public shares and viewer exports. A partially visible stack is read-only.
- Rescans keep cover, order and membership. Ordinary database backups keep stacks.
- Full viewer-database exports omit stacks and smart albums whose filters name a private stack, plus smart albums with unreadable filters (invalid JSON, excessive nesting, or over 1 MiB). Incremental updates keep the destination's own albums and stacks.
- [Immich stack import/push](IMMICH.md#manual-stack-import-and-push) is a separate CLI operation.

**Suggested stacks** opens the full-page review at `/culling?mode=stacks`, with the current gallery filters and a return to the originating gallery or album. Editing access is required. It reviews existing duplicate and burst groups, ignoring burst/duplicate hiding so every member appears.

- In the grid, `↑`/`↓` select a group, **Enter** opens its darkroom and **S** stacks it with the proposed cover. In the darkroom, `←`/`→` focus a frame and **S** or **Enter** stacks with that frame as cover. **X** skips; stacking and skipping offer Undo.
- **Reject** or **R** in the darkroom excludes the focused photo. Stack saves only remaining photos and requires at least two. Skip dismisses the original proposal. With too few photos you can still inspect excluded frames, switch groups, Undo, Skip or go Back. The rejection stays saved after finishing a proposal. Undoing Stack or Skip restores that proposal’s exclusions; a later suggestion starts a fresh draft.
- The darkroom retains a large zoomable preview, loupe, comparison and thumbnail strip. **Z** toggles zoom, **P** focus peaking, **G** cycles the composition grid, **F** fullscreen, and **Escape** returns to the group grid. **Edit members** opens a secondary dialog; reducing a suggestion to one photo offers **Skip this stack**.
- Skips are stored per account until the group's members change. Groups containing already-stacked photos or bracket/panorama frames are skipped; overlapping groups are skipped whole, preferring duplicate groups.
- The header counts loaded suggestions, not the library total. Batches contain at most 20 proposals and 2000 photos (1000 per group). The next batch loads automatically only after every loaded suggestion is stacked or skipped. **Reload suggestions** reloads the same scope; **Back to gallery** returns to the origin.
- Not offered in pinned lists, Similar Photos or semantic search. Stack and Skip never change review decisions or originals. Only the explicit Reject action changes the photo’s review values.

### Photo Cards

- Thumbnail with score badge. Hover it to see where the score sits in your library ("Top 18% of the library").
- Clickable tags for quick filtering
- Person avatars for recognized faces
- Category badge
- Right-click (or Shift+F10) opens the [context menu](#multi-select--bulk-actions)

In photo detail, metrics sit in icon tabs: EXIF data (when present), Quality, Composition (with subject saliency), Technical and Histogram. The last tab you opened is remembered. Each score sits beside its library distribution, with the photo's bar highlighted; hover a bar for the photo's rank and the library range. Placement is computed over the whole library, not the current filters, to the nearest of 20 bars.

### Multi-Select & Bulk Actions

Click photos to select; Shift+Click selects a range. An action bar appears at the bottom-left with icon buttons (hover for labels). Bulk actions need edition mode.

- **Favorite** — mark all as favorite (clears rejected)
- **Reject** — mark all as rejected (clears favorite and rating)
- **Rate** — set or clear a 1–5 star rating
- **Add to album** — add to an existing or new album
- **Edit tags** — add or remove a [manual tag](#manual-tags) on every selected photo
- **Select all** — with an empty selection, selects every photo the filters match, not just loaded pages. With photos already selected, it adds the loaded photos and offers to widen to the whole view. Whole-view actions confirm the exact photo count first.
- **Invert** — swap the selection for its complement. From an empty selection that is the whole view. From a non-empty selection it stays within loaded photos: pick keepers, invert, reject.
- **Compare** — open 2–4 photos side by side with synced pan and zoom (scroll to zoom, drag to pan, double-click to reset). Panes switch to full resolution when zoomed.
- **Copy filenames** — copy filenames to the clipboard. A whole-view copy confirms first; over 10 000 photos is refused.
- **Export** — write XMP sidecars next to the files (see [Editor Export](#editor-export))
- **Cull to folder** — copy keeps, or move/trash rejects, to a folder (see [Cull to folder](#cull-to-folder))
- **Delete** — send photos to the OS trash (see [Delete](#delete)). Shown only when `viewer.cull.allow_trash` is on. Disabled for a "select all in view" selection: select photos explicitly.
- **Download** — download the selected photos
- Clear the selection with Escape or the Clear button.

Double-click a photo to open it.

**Context menu.** Right-click a photo, or focus it and press Shift+F10 / the Menu key.

- On a photo inside a multi-photo selection, it acts on the whole selection with the bar's actions (except Invert and Select all), including **Edit tags**.
- On any other photo, it acts on that photo only and adds Open photo, Find Similar, Why This Score?, Write metadata to file and Assign face to person (when the photo has unassigned faces), subject to their gates.
- Culling one photo from the menu removes only that photo from the selection.
- Not offered on touch-first devices (`hover: none` and `pointer: coarse`); use the Actions sheet there.

### Keep Top N%

The **Keep top %** control in the toolbar (edition mode) culls the whole filtered view in one step. Set a percentage. Facet ranks the view by the **current sort** (aggregate, My Taste, Top Picks, sharpness…), keeps the top share and **selects the rest**. Reject them from the action bar, after deselecting any you want to spare.

- Nothing is moved or deleted; it only fills the selection. Rejects still train My Taste.
- The selection is capped at 5000 photos. On a larger view, narrow the filter (album, date, person…).
- Under the default `hide_brackets` / `hide_panoramas`, a bracket or panorama set counts as **one** photo.

### Assistant-pinned list

When an assistant connected through [AI Agents (MCP)](AGENTS.md) shows you an exact list of photos, the gallery displays it in the assistant's order. A status line says how many photos were chosen; **Show the usual view** restores your filters.

- While the list is shown, the filter bar, tag chips, person avatars, **Find Similar** and filter-scoped actions (such as **Keep top N%**) are hidden. Changing the album still replaces the list.
- Showing a list clears your selection and the side panel.
- The assistant's writes appear without a reload: changed cards refresh and deleted photos leave the list. A photo `cull_apply` moved or trashed stays. One "Assistant changed N photos" notice appears per burst of changes. See [Live updates](AGENTS.md#live-updates).

**Assistant active chip.** While an assistant works in your tab, an **Assistant active** chip shows in the header for a few seconds after each write or command. Click it for **Assistant activity**: the last 50 actions of this session (lost on reload), with tool, photo count and time. Actions that named photos have **Show photos**. When the assistant asks, the tab tells it which photo your cursor is on (`focused`) and what you did since its last look (`user_activity`). Nothing is sent unprompted. See [Control your open tab](AGENTS.md#control-your-open-tab).

### Cull to folder

**Cull to folder…** on the bulk-action bar (edition mode) copies keeps, or moves/trashes rejects, to a target folder. Trash means the OS trash, never a permanent delete, and needs `viewer.cull.allow_trash`.

- **Every run starts as a dry run.** You see a preview before anything is written; move/trash run only with an explicit `dry_run=false`.
- **The server picks the files from each photo's own state.** Copy acts only on keeps, move/trash only on rejects. Anything else is reported as `excluded_by_state`. The client cannot hand over a list of files to delete.
- **Companions are opt-in.** Rejecting a JPEG does not take its RAW unless you tick **Include companion RAW / XMP** (`include_companions`).
- On macOS and Windows, companion RAW files keep their on-disk names, including uppercase extensions; on Windows, `.xmp` sidecars do too.

**Trash rejects availability.** The "Trash rejects" option appears only when `viewer.cull.allow_trash` is on *and* the `send2trash` package is installed (`/api/config` reports `cull.trash_available: true`). Otherwise the dialog says why: "the `send2trash` package is not installed" or "an administrator disabled trashing".

**Multi-frame sets.** With the default `hide_brackets` / `hide_panoramas`, the selection holds only a bracket's base exposure or a panorama's middle frame. So by default, culling a set acts on that **one** file. Two opt-in boxes widen it:

- **Include companion RAW / XMP** (`include_companions`) adds the same frame's RAW and `.xmp` sidecar.
- **Include sequence siblings** (`include_sequence_siblings`) adds the set's other frames, but only those whose own keep/reject state matches the action. Kept frames are never trashed because a sibling was rejected. A frame you deselected is never pulled back in.
- The preview always reports how many sibling frames exist (`sequence_siblings`). `matched` tells "nothing qualified" apart from an empty result.
- Moving or trashing a set's lead promotes a surviving sibling, so the set stays visible.
- To pick an exact subset of a set, open it with the photo detail's "open this set in the gallery" action first. That view shows every frame.

A filter-scoped cull follows the same filter rules as the gallery, Photo Type included. A view over 10 000 photos is refused rather than truncated, even for a dry run: narrow it (album, date, person…) and retry. Details: [API.md](API.md).

**Where you can write.** Without `viewer.export.allowed_target_dirs`, Facet writes only inside your scan directories. A subfolder of the photo tree (e.g. `_rejected`) works with no setup. For a folder elsewhere, add it to `viewer.export.allowed_target_dirs`. See [Configuration — Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations). In Docker/Podman, paths resolve **inside the container** — see [Deployment — Container Path Semantics](DEPLOYMENT.md#container-path-semantics).

**"Access denied" on every action.** This is a deliberate refusal: the target folder is not allowed, or your edition session expired. Check the failed request's `detail` field in the browser's Network tab. A real filesystem problem looks different: partial success with a nonzero `errors` count, and the OS error in the server log.

### Delete

**Delete** in photo detail and on the selection bar sends files straight to the OS trash (recoverable, via `send2trash`). It is separate from Cull to folder and from the `/culling` darkroom. It uses the same `viewer.cull.allow_trash` flag.

- **The library entry goes at once.** Unlike Cull to folder, the photo's row is removed as soon as its file is trashed; no `--cleanup-missing-photos` needed. A companion RAW pulled in that was scanned as its own photo goes too.
- **Explicit selection only.** Up to 10000 paths; "select all in view" is disabled.
- **Scope.** The named file only by default. **Include companion RAW / XMP** (`include_companions`) and **Include sequence siblings** (`include_sequence_siblings`) widen it, as in Cull to folder. Both default off.
- **Bracket base exposures are protected.** A bracket's base frame (`sequence_ev_offset = 0`) is refused (`refused_bracket_lead`) unless you include siblings; then the whole bracket goes together. A deleted panorama lead promotes a surviving sibling.
- **Partial results.** Each path is reported separately. A refused bracket lead does not stop the rest. A file whose trash attempt failed (`errors`) keeps its row.
- **Files already missing from disk.** **Also remove library entries whose file is already missing from disk** (on by default) removes those rows too, reported as `removed_missing`. Unchecked, they come back in `skipped` with their rows kept. A path outside the scan directories, or in a missing or empty folder (an offline volume), always stays in `skipped`. Use `--cleanup-missing-photos` to sweep a whole library.

Response fields and status codes: [API.md](API.md).

### Display Options

- **Layout Mode** — **Grid** (uniform cards) or **Mosaic** (justified rows keeping aspect ratios), at every screen width.
- **Thumbnail Size** — card/row height slider (120–400px, saved in localStorage)
- **Hide Details** — hide metadata on cards (grid mode only)
- **Tooltip** — how photo details appear: **Side panel** (default), **Hover**, **Click** or **Off**.
  - The side panel shows full details in the right-hand drawer, laid out like photo detail. It follows hover and click, so it works on touch screens. It keeps the last photo when the cursor leaves the grid.
  - Clicking a photo holds the panel on it until you press **Deselect** (which also deselects the photo). **Escape** does the same and clears the selection.
  - The panel shares the drawer with the filters; opening the filters hides it. It needs a viewport at least 1280px wide.
  - **Hover** and **Click** show a short bubble: category, aggregate and rank, aesthetic, composition, sharpness, exposure, and one EXIF line.
- **Customize card buttons** — reorder and show/hide the buttons on a card's hover row. Nine actions are available: find similar, why-this-score, write metadata, assign a face, open the duplicate group, burst group, bracket/panorama set or photo stack, and open the photo page. Group buttons appear only on photos in such a group. Duplicate-group and photo-stack buttons are on by default; the others are opt-in. Saved per browser.
- **Hide Blinks** — hide photos with detected blinks
- **Blinks Only / Duplicates Only** — show only blinked photos, or every member of each duplicate group. The hide toggles are suspended for that view.
- **Show Rejected Only** — list only your rejected photos. Process them with select-all and **Cull to folder**, or with **Trash all rejects (to OS trash)** in Culling. Both cap filter scope at 10,000 photos; narrow by date or album for more, and turn off the group-hiding filters to include every rejected frame. Disabled while a review status is selected.
- **Best of Burst** — show only the top-scored photo of each burst
- **Best of bracket** — show only each bracket's base exposure. **On by default.** Independent of Best of Burst, because a bracket's burst lead is not always its base exposure.
- **Best of panorama** — show only the middle frame of each panorama or HDR-panorama set. **On by default.**
- **Infinite Scroll** — photos load as you scroll
- **Fast Scrolling (virtualized)** — renders only rows near the viewport, so deep scrolling stays fast. On by default. Turn it off in the sidebar's Display tab if you hit layout issues. Grid mode with details shown always renders fully. Saved in localStorage (`facet_virtual_scroll`).

### Similar Photos

Click **Similar** on a photo and choose a mode:

- **Visual** (default) — pHash similarity (70%) + CLIP/SigLIP similarity (30%). When two photos share only one of the two signals, it counts at full weight; photos sharing neither are never listed. All matches above the threshold are returned, page by page. If the photo has neither signal, rescan it with `--force` (a plain `python facet.py <dir>` skips processed files).
- **Color** — histogram intersection (70%) + saturation distance (10%) + luminance distance (10%) + monochrome bonus (10%). Pre-filters by monochrome flag and saturation range.
- **Person** — photos with the same person(s), by `person_id` when available, otherwise face embedding similarity.

The **similarity threshold slider** (0–90%) sets how strict matching is (not in person mode). Results scroll infinitely.

### Filter Chips

Active filters appear as removable chips with counts at the top of the gallery.

### Manual Tags

Manual tags are tags you type yourself, kept next to the AI tags. They are stored apart (`photo_manual_tags`, not the photo's `tags` column), so rescans and retags never wipe them.

- **Where they show.** In photo **detail** only, as chips marked differently from AI tags. Cards and tooltips show AI tags.
- **Who can edit.** Edition users. On an install without `viewer.edition_password` they are read-only. AI tags cannot be removed.
- **Bulk editing.** Select photos and use **Edit tags** (selection bar, mobile Actions sheet, or context menu) to add or remove one tag. Whole-view selections work. Photos already holding 50 manual tags are skipped; `count` reports photos actually changed.
- **Format.** Tags are trimmed, lowercased and whitespace-collapsed (NFC). Max 64 characters, max 50 per photo. Empty tags, commas and control characters are rejected. A tag equal to one of the photo's AI tags is not stored.
- **Search and filters see them.** The tag filter, text search, semantic search (`/api/search`, except the caption-only text scope), the tag dropdown, statistics and sidecar/embed/Lightroom exports all use AI + manual tags. Text search matches a manual tag as a whole phrase.
- **Exceptions.** Capsules count AI tags only. Manual tags never affect scores, categories or narrative moments.
- **Hidden from share links.** Share-link viewers never see them. A shared smart album still applies the owner's saved filter.
- **Shared by all users.** In multi-user mode any edition user can remove a tag another added.
- **Not undoable.** [Undo](#undo) does not cover them. A removed tag can return from a sidecar; see [Conflict rules](INTEROP.md#conflict-rules).
- **Imported tags.** `--import-sidecars` stores unknown sidecar keywords (not AI tags, not person names) as manual tags with source `xmp`.
- **Tied to the file path.** Moving or renaming a file loses its manual tags.

## Panoramas and exposure brackets

A panorama's frames are meant to be stitched and a bracket's to be merged; they are not competing takes. Burst detection alone would group them and hide all but one, so Facet detects these sets separately.

**In the gallery.** `Best of bracket` and `Best of panorama` (both on by default) show one frame per set: a bracket's base exposure, a panorama's middle frame. That frame carries a small icon next to the star and heart: plain sweep, HDR sweep or exposure bracket. The icon appears only while the toggle is hiding the rest of the set.

**In culling.** The granularity menu offers `Exposure brackets`, `Panoramas` and `HDR panoramas` as their own feeds, never merged into `All`. Every frame starts kept, and confirming a set records no comparison pairs, so the ranker is not trained on how a set was shot.

**Correcting a set.** Detection gets about 4% of sets wrong. Corrections are sticky: they survive every later detection run. Both need edition mode, at least two frames, and can be undone from the snackbar.

- **False positive** (not a panorama, or plain vs HDR): use the correction menu on the group's action bar in culling.
- **Missed panorama**: select its frames in the gallery and choose *Mark as a set* → *Mark as one panorama*.

**Marking a missed bracket.** For an exposure ladder detected as an ordinary burst:

- In the darkroom, a plain burst group (no frame already in a bracket or panorama) offers *Mark as bracket*.
- In the gallery selection bar, use *Mark as a set* → *Mark as one bracket*.
- The frames must form a real ladder: at least 2 frames, each with exposure data (f-stop, shutter speed, ISO) and a capture date, and no two at the same exposure value. Otherwise the mark is refused with a message and nothing is saved.
- Marking frames that overlap an existing marked bracket extends it. The combined set must still be a valid ladder.
- The darkroom feed hides rejected frames, so a darkroom mark never includes a rejected rung.
- A `bracket` group offers *Drop the correction* instead.
- If a marked frame disappears or loses its exposure or date data, the whole set waits until every member qualifies again.
- **Marking wins over panorama detection**: a detected panorama containing marked frames is dropped on the next run.

**Corrections apply on the next detection run.** A correction is saved at once and shown as pending: a clock badge on the gallery tile, a *Correction pending* chip in culling. The culling page shows a banner with a **Re-run detection** button. The sidebar's *Panorama corrections* filter (edition only, on the Review tab) lists pending corrections library-wide. *Drop the correction* removes one later.

**Tuning it.** The Panoramas tab under Compare holds the calibrated thresholds: minimum frames, minimum sweep, longest gap and HDR exposure spread. Saving them changes nothing until you re-run detection (the button is beside Save). See [CONFIGURATION.md](CONFIGURATION.md#panorama-detection).

## Person Management

> Browsing persons is open to all viewers; renaming, merging, avatar changes and face assignment require `[Edition]`.

### Person Filter

The dropdown lists persons with face thumbnails. Click one to filter the gallery.

### Person Gallery

Click a person's name to see all their photos at `/person/<id>`. On the Manage Persons page, double-clicking a person card (named, unnamed in Needs naming, or ignored) opens the gallery on that person's photos; double-clicks on the name field, checkbox and buttons are left to them.

**Naming from the gallery.** When the gallery is filtered by a person (`?person_id=95`), that person's chip in the active-filter row shows their face and name, or **Unnamed**, outlined as a nudge; its × (**Remove from filter**) takes the person out of the filter. For edition users, two buttons sit before the ×. **Rename** (the pencil) renames the person in place: the name field reads "Who is this? Type or pick a name" for an unnamed person and "Rename or merge into…" for a named one, its suggestions show each person's face, name and photo count, and **Save** or **Cancel** closes it (Escape cancels too). The name is always saved first (`POST /api/persons/{id}/rename`); when other groups already carry it (case and spaces ignored, whether or not they are among the suggestions), the chip then offers the same merge as the Manage Persons page (see **Rename** below), and after a merge the gallery switches to the person kept. **More** (⋮) opens the person menu: **See all photos of {name}**, **Find more faces of {name}** and **Ignore** (**Restore** for an ignored person). When the gallery's hide toggles keep some of the person's photos out of view, the gallery notices give the hidden count, broken down into burst, blink, duplicate, bracket and panorama photos, so you know to show them before naming.

### Manage Persons Page

In edition mode the page has two tabs, **Named (N)** and **Needs naming (N)**, and always opens on **Named**. **Needs naming** lists the unnamed clusters, each with a name field; **Named** holds the named persons, with ignored ones in a collapsible **Ignored** section at its bottom. Read-only users see only the named grid. Name suggestions, here as on the gallery's person chip and the photo's face menu, show each person's face, name and photo count. On **Needs naming** the sort menu offers **Face count** and **Newest**. When nobody is left to name, the tab reads "Everyone is named. New faces that need a name will appear here."

Open it from the header button or `/persons`:

| Action | How To |
|--------|--------|
| **Merge** | Select source person, click target, confirm |
| **Delete** | Click delete button on person card |
| **Rename** | Click person name to edit inline. When other groups already carry the name (case and surrounding spaces ignored), a confirm shows a tile per person (face, name, face count), all selected, with the person that will be kept marked: the largest of the selected, which keeps its spelling. Deselect a namesake, or cancel, to keep it apart. A merge cannot be undone |
| **Split** | Open a person's faces, select a subset, split them into a new person |
| **Find more faces** | The person-search button on a person card, or **Find more faces of {name}** in a person menu, lists faces that look like that person, best match first, scored against the person's centroid (`GET /api/person/{id}/possible_faces`). Under **Whose faces to include**, three chips each show their count: **Ungrouped** and **Unnamed groups**, on by default, and **Named people**, off. A face that belongs to a named person carries a **from {name}** badge, and ticking one shows a warning that adding moves it to this person. Above the faces, **Groups that look alike** lists other clusters whose centroid looks like this person's (the unnamed ones, plus the named ones while **Named people** is on); each shows its picture, its name or **Unnamed group**, its face count and **{percent}% alike**, with **Merge all** to fold the whole group into this person. Merging a named group asks first, and a merge cannot be undone. Each face is badged **Strong** (50 % alike or more) or **Possible**, with its percentage, and **How close a match** sets the threshold: a signal-bars button showing `≥NN%` that opens the level menu, with five levels, **Very strict** 60 %, **Strict** 50 %, **Normal** 35 % (the default), **Loose** 25 % and **Very loose** 20 %. When no face qualifies, the dialog reads "No faces look like {name} (closest: N%)." and offers **Try Loose** or **Include named people**. When a search would compare too many faces, it searches ungrouped faces only; if that is still too many, it asks for a **Year** to search in. **Select all strong**, Shift-click for a range and Space on a focused face speed up ticking, and the Add button shows how many are ticked. Adding recomputes the centroid, so the next round is ranked against what you just confirmed; faces you leave unticked are not offered again while the dialog is open |
| **Ignore** | Ignore a cluster (staff, strangers): the ⊘ button on a card, also on Needs naming cards. Ignored persons leave the persons list, Needs naming, filters, merge suggestions and Find more, and are listed in the collapsible **Ignored** section at the bottom of the **Named** tab, with **Restore** (`GET /api/persons?hidden_only=true`). It uses the same `is_hidden` flag as before. Ignoring applies at once and shows a notification with **Undo** for 10 seconds, here and in every person menu. |

### Faces on the photo

In the photo view, a box shows around each detected face while the pointer is over the photo, and hovering a face shows its name (red box: not named yet). Boxes follow zoom and pan, and dragging or double-clicking on a face still pans or resets the zoom. An unnamed face's box is also dashed, so it does not rely on colour, and every box has a dark outline to stay visible on any background. Unless the boxes are **Off**, Tab moves between faces from the keyboard, each announced by its name (or as an unknown face), and Enter or Space opens its menu. On a touch screen a tap opens a face's menu only while the boxes are shown (the boxes are set to **Always**, or, unless they are **Off**, the face belongs to the person the gallery is filtered to); otherwise a tap on the photo does nothing to the face. In edition mode, clicking a face opens a menu: **Change person…** (or **Name this face…**) to pick an existing person or type a new name, **Find more faces of …** for that person (see Find more faces above), and **Not …** to take that one face off that person (`POST /api/face/{id}/unassign`); the person's other faces in the photo stay theirs. Faces whose stored dimensions cannot be trusted are not drawn. The boxes come from `GET /api/photo/faces`, which returns each face's `box` normalised to the frame. Any face that belongs to a person, named or not, also offers **See all photos of …** (or **See all photos of this group**), which opens the gallery filtered to that person; this one works in read-only mode too. A toolbar button cycles the face boxes through three states, remembered per browser: **Off** (no boxes, and faces cannot be clicked or focused), **On hover** (the default, as described above) and **Always** (every box and name stays shown). When the gallery is filtered to a person, that person's faces stay boxed with a thicker line, unless the boxes are **Off**. **Use as …'s picture** makes the clicked face the person's card picture; a person that gains faces without having a picture gets its most confident one automatically. In the gallery, when it is filtered to one person, each thumbnail outlines that person's face in red, so a cluster's photos show which face it is about before you name it. In the right panel's **Persons** list, clicking a person's avatar opens the same menu as clicking that face's box, even when the boxes are **Off**; **See all photos of …** in that menu opens the gallery.

### Mark a missed face

In edition mode, open a photo and choose **Mark a missing face**, even when no faces were detected. Draw a rectangle (or type its coordinates), pick an existing person or enter a new name, then **Save**. Cancel saves nothing.

Saving, editing or removing a manual face updates the photo’s face boxes and people without reopening the photo.

- Use the same editor to adjust, reassign or remove a manual mark.
- Manual marks stay linked to their person through rescans and viewer synchronization. They do not train recognition or change face-quality scores.
- The editor works from the original image, so RAW and rotated photos line up. Without the original you can list and remove marks, but not draw.
- A mark that cannot be verified shows as **Needs review**. Marks from earlier preview builds need one review: open the original, edit and save the mark.
- A replaced picture flags its marks. A subtle retouch or small re-crop of the same size may go unnoticed. Metadata writes, remounts and other hosts keep marks current.
- The editor reuses one decoded frame of up to 128 MiB; larger frames may need another decode. The limit is fixed.
- Deleted marks stay deleted during later synchronization.
- Changes live in the library database; originals and sidecars are not touched.

> **Warning:** a forced viewer database rebuild replaces viewer-only edits, manual marks included, with the source database. Export or back them up first. Normal incremental synchronization keeps them.

The legacy `viewer.performance.face_cache_size` setting is ignored and can be removed.

## Scan Trigger

Start a scan from the browser. The Scan button appears when **both** hold:

- `viewer.features.show_scan_button` is `true` (it ships **`false`**).
- You have scan access: the `superadmin` role in multi-user mode, or an edition session on a single-user install with a non-empty `viewer.edition_password`.

On an open single-user install (empty `viewer.edition_password`, the default), nobody can scan from the browser. Exception: under `viewer.trusted_local_editing`, a trusted-local browser session, or a local assistant with a Full-editing token, can scan without `show_scan_button` or an edition password.

The button sits on the empty gallery (**Scan photos to get started**) and at the end of the header (**Scan for new photos**; bottom bar on small screens). Both open the scan launcher:

- Pick a directory from the list and start the scan.
- Live progress and output lines stream into the dialog. The gallery refreshes when the scan ends.
- The scan runs `facet.py` in the background; one scan at a time.
- The directory list combines each user's `directories`, shared directories, `path_mapping` targets and `viewer.scan_directories`. Seed `viewer.scan_directories` (e.g. `/data/photos`) so single-user and Docker installs have a target.

No GPU is required — see [Which profile fits my hardware?](INSTALLATION.md#which-profile-fits-my-hardware) and [No graphics card](INSTALLATION.md#no-graphics-card). The scan runs on the viewer's machine, so it is fastest when that machine has a GPU.

To rescore existing photos without scanning new files, use `POST /api/scan/recompute` (edition only) — see [Category Priority & Scoring Contexts](#category-priority--scoring-contexts).

## Semantic Search

Type a query like "sunset over mountains" and get matching photos. Ranking blends CLIP/SigLIP embedding similarity (70%) with FTS5 BM25 text matching on captions and tags (30%).

- **Requirements.** Photos need stored `clip_embedding` data (computed during scoring). Run `database.py --rebuild-fts` to enable the caption/tag text part.
- **Model.** Uses the active VRAM profile's embedding model (SigLIP 2 for 16gb/24gb, CLIP ViT-L-14 for legacy/8gb), or whichever of `models.clip`/`clip_legacy` matches the stored embeddings (see [CONFIGURATION.md](CONFIGURATION.md)).
- **Speed.** Installing sqlite-vec speeds up search; otherwise Facet keeps an in-memory matrix. The first query on a large library can take several seconds.
- **Threshold.** The match threshold defaults to `models.clip.search_threshold_percent` (`5%`) or `models.clip_legacy.search_threshold_percent` (15%), separate from `tag_threshold_percent`. The gallery slider spans 0–50%; `/api/config`'s `search_threshold_default` sets its start. Even `0%` rejects negative similarity. The 5% SigLIP default favours recall — see `clip.search_threshold_percent` in [CONFIGURATION.md](CONFIGURATION.md).
- **Text only.** `scope=text` restricts the query to literal FTS5 matches in OCR/caption text.
- **Works with every gallery filter**, including the hide toggles. With the defaults, hidden burst, duplicate, bracket and panorama members, blinks and rejects stay hidden.
- **No result cap.** The gallery pages results and shows the true total.
- **Relevance sort.** With a query active, the sort defaults to **Relevance** (best match first). Clearing the query restores the default sort.
- **Selection.** Select all covers only the loaded photos; whole-view scope is not available here.
- Controlled by `viewer.features.show_semantic_search` (default: `true`).

Results report `similarity` (the blended score) and `embedding_similarity` (the raw cosine tested against the threshold, absent on text-only hits). Gallery parameters `semantic_q`, `semantic_threshold` and `sort=relevance` are documented in [API.md](API.md).

## Albums

Organize photos into named albums at `/albums`. Controlled by `viewer.features.show_albums` (default: `true`).

### Manual Albums

Create albums and add photos from the gallery with multi-select. Albums support:
- Name and description
- Custom cover photo
- Custom ordering
- Browse album contents at `/album/:albumId`

### Smart Albums

Save a filter combination (camera, tag, person, dates, score thresholds…) as a smart album. It updates as new photos match. The filters are stored as JSON in `smart_filter_json`.

### Scoring Context

An album can carry a scoring context that decides which category wins for its photos, independent of the global priority — see [Scoring Contexts](CONFIGURATION.md#scoring-contexts). Set it from the album's dialog (edition mode).

- Setting it stamps the context onto the album's **current** members. A photo with its own manual override is left alone.
- A smart album's members come from its saved filter, ignoring the gallery's hide toggles, so the count can exceed what the album view shows.
- Photos added to a manual album later inherit the context. New matches of a smart album do not; set the context again.
- **Clear context** (not the same as choosing `default`) removes the stamp. A photo still in another album with a context gets that context instead.
- Facet can suggest a context from the album's dominant narrative moment (via each context's `suggest_from_moments`). It writes nothing until you confirm.
- Run a recompute (`POST /api/scan/recompute`) for the new context to change stored categories.

Endpoints and response counts: [API.md](API.md#albums).

### Portfolio Export

Turn a manual album into a self-contained static HTML gallery. With `viewer.features.show_portfolio_export` on (default `true`) and edition unlocked, each manual album card has **Export portfolio**. Choose a title, target folder and whether to include captions.

- The output holds `index.html` (a thumbnail grid with a built-in lightbox, no external or CDN references, works offline), an `assets/` folder of sequentially named JPEGs (no library paths leaked) and a `manifest.json`.
- Each photo uses the original, downscaled to `portfolio.max_edge`, or the stored 640px thumbnail if the original is unreachable.
- The target folder must be in the export allow-list (`viewer.export.allowed_target_dirs` plus scan directories, see [Configuration — Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations)).
- Albums over `portfolio.max_photos` (default 500) are refused.
- Re-exporting rewrites only the export's own files.

See [Portfolio Export configuration](CONFIGURATION.md#portfolio-export). Endpoint: `POST /api/albums/{album_id}/export-portfolio`.

### Photo Sharing

Share albums through tokenized links. Viewing a shared album needs no login.

| Action | How To |
|--------|--------|
| **Share** | Open album, click "Share" button to generate a shareable link |
| **Revoke** | Click "Unshare" to invalidate the share token |
| **View** | Recipients open the link to browse the shared album at `/shared/album/:id` |

### Client Proofing

Let a client pick favorites from a delivery. With `viewer.features.show_proofing` on (default `false`), a share link can run in **proofing mode**: the client opens it, enters a PIN if set (`viewer.proofing.pin`), then **hearts** photos and leaves **comments**.

- Client picks are stored apart (`album_client_picks`) and never touch your favorites or ratings, or train the ranker.
- Read the picks from an `[Edition]` dialog on the album card.
- Sessions last `viewer.proofing.session_minutes` (default 24h) and end when the album is unshared or proofing is turned off.

See [Configuration — Client Proofing](CONFIGURATION.md#client-proofing).

## AI Critique

Explains a photo's score as strengths, weaknesses and suggestions. Controlled by `viewer.features.show_critique` (default: `true`).

### Rule-Based Critique

Available on every VRAM profile. Facet recomputes the score from the photo's stored metrics and the current configuration, and shows the calculation.

- **Category** is the one the current formula assigns (honouring a category override and scoring context). It can differ from the stored category until the next `--recompute-average`.
- **Breakdown rows** show each 0–10 input the scorer weights (higher is better, so noise and dynamic range read as quality), with weight and contribution.
- **Net adjustments and rounding** (bonus, blink multiplier, clipping, noise and oversaturation penalties, clamping) reconciles the rows with the **Current calculation** total, shown beside the **Stored score**.
- **Detected conditions** lists blink and a skin-tone cast.
- Sharpness, color and eye sharpness use the percentile snapshot from the last `--recompute-average`. A library that has only been scanned uses the scan's values.
- **Advisory rows**, shown only when computed: form and color harmony (symmetry, balance, edge-orientation entropy, fractal complexity, Matsuda color harmony; `--recompute-form`), distortion chips (motion blur, color cast, oversharpening…; `--recompute-distortions`) and a skin-tone note for portraits (`--recompute-skin-tone`). They explain the photo but do not change the aggregate.

If the calculation is unavailable, only the stored score is shown, with the fix:

| Reason | Fix |
|--------|-----|
| Outdated schema | `python database.py` |
| Normalization snapshot unavailable | Retry, then `python facet.py --recompute-average` |
| Invalid stored metrics | Rescan with `--force` |

The dialog also tells a photo that is *not scored yet* from one whose *stored score is unusable*.

### VLM Critique `[GPU]` `[16gb/24gb]`

Uses the configured VLM (Qwen3.5-2B or Qwen3.5-4B) for a context-aware critique. Needs the 16gb or 24gb profile, `viewer.features.show_vlm_critique` set to `true` (the default) and an edition session to generate. Without edition, only a cached critique is shown and `vlm_available` is `false`. The dialog generates through `POST /api/critique/vlm` (edition only; concurrent requests for one photo share a single generation); `GET /api/critique` only reads what is cached and never generates, translates or writes.

- The prompt (`critique.vlm`) includes the score breakdown, stored and recalculated scores, detected conditions and EXIF.
- The reply reads **Observation / Assessment / Suggestions**. It is cached per photo (`photos.vlm_critique`), translated when an edition session opens it in the target language (stored then, and served as stored thereafter), and **Regenerate** recomputes it. Without an edition session you see the untranslated text unless a stored translation already exists.
- It runs on the stored thumbnail, so RAW files work.

**Visual "why this score" overlay.** With `viewer.features.show_saliency_overlay` on (default `true`), the critique dialog has **Show overlay**. It draws the BiRefNet saliency map as a heatmap (`GET /api/saliency_overlay`), plus face boxes and eye markers from stored landmarks (`GET /api/photo/face_markers`). Boxes are green for open eyes, amber for a blink. The heatmap is thumbnail-resolution, so it is approximate. The toggle hides on profiles that cannot produce a saliency mask.

## AI Captioning `[GPU]` `[16gb/24gb]` `[Edition]`

Get a natural-language caption for any photo. An edition session generates it on first request; it is then cached in the `caption` column. Edit captions in photo detail (edition mode). An open, read-only install never generates one. `POST /api/caption` generates (and translates) it; `GET /api/caption` only returns the stored caption or translation and never generates, translates or writes.

Bulk generation and translation from the CLI:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

Translation uses MarianMT on CPU (no GPU needed). Set the language with `translation.target_language` (default: `"fr"`). Supported: French, German, Spanish, Italian.

Controlled by `viewer.features.show_captions` (default: `true`). Without the 16gb/24gb profile or a remote `vlm_backend`, the Generate caption button is hidden and critiques stay rule-based.

## Memories ("On This Day")

See photos taken on today's date in earlier years. Memories opens a randomized full-screen slideshow.

Controlled by `viewer.features.show_memories` (default: `true`).

## Common workflows

- **Cull a vacation** — open Capsules and find the `journey` capsule for the trip. Each capsule can be saved as an album.
- **Review day by day** — open Timeline and drill into years → months → days. Click a day to open the gallery filtered to it.
- **Show what's hidden** — the gallery hides blinks and non-lead bursts and duplicates by default. When something is hidden, a "N photos hidden by current filters · Show all" notice appears at the bottom right.
- **Come back to your filters** — the header's photos icon returns to the gallery with the filters, sort and position you left. Double-tap it, or reset the filters, to start from defaults.

## Timeline View

Browse chronologically: years drill down to months, then to a calendar of days. Each tile shows a photo count and a cover photo. Click a day to open the gallery filtered to that date; sort there.

The five gallery hide toggles (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`) apply, defaulting to `viewer.defaults`, so tile counts match what the gallery shows. When something is hidden, a `visibility_off` button appears in the toolbar ("Some photos are hidden by your filters"); click it to clear all five.

Open `/timeline`. Controlled by `viewer.features.show_timeline` (default: `true`).

## Map View

See photos on an interactive Leaflet map, clustered by zoom level, from their EXIF GPS coordinates.

### Setup

Extract GPS coordinates from existing photos:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

New photos get their coordinates during scoring.

Open `/map`. Controlled by `viewer.features.show_map` (default: `true`). Map backgrounds come from OpenStreetMap and need an internet connection, even in the installed app.

### Saved places and manual GPS

**Find photos without a location.** In the filters, open **Location** and enable **No geolocation**. It can be saved in a smart album. It turns off when you start a semantic/similar search or pick a map radius.

**Set one photo's location.** In edition mode, open **Add location** or **Edit location** on a photo. Search **Saved places**, choose a **Recent location**, drop a pin or type coordinates. **Save** applies it.

**Set many at once.** Select photos and choose **Set location** (selection bar, mobile actions or context menu).

- **Only photos missing a location** is on by default; turn it off to replace existing locations.
- **Preview location changes** shows how many will change or be skipped. If anything changes in between, preview again.
- Up to 1000 visible photos per batch, whole-view selections included.

**Saved places.** Pick a point and use **Save this place** with a name (e.g. "Work"), or bookmark a geotagged photo's point. Rename or delete from the list; that does not move photos already assigned. Each editor has a private list: up to 100 saved places and 20 recent points.

**Manual locations stick.** A location set in the viewer survives rescans and EXIF re-extraction, including a cleared one. **Use the file's location** drops the override and re-reads the file's GPS (or clears it if the file has none).

**Writing to files.** Saving never writes the image file. An explicit metadata export writes manual locations (and explicit clears) to the XMP sidecar: in the viewer or with `--export-sidecars`. Embedding (**Write metadata to file**, or `--embed-originals`) also writes EXIF GPS into supported originals. See [INTEROP](INTEROP.md).

### Online place search

Use **Address or business → Search online** to look up a place with Photon (OpenStreetMap data, © OpenStreetMap contributors). The query is sent only when you click **Search online** or press Enter. Choose a result to preview, then **Save**. Saved places and coordinates work offline.

- `viewer.place_search_url` (default `https://photon.komoot.io/api`) points to the provider. Use a self-hosted Photon, or `""` to disable lookup.
- The public demo has no availability guarantee. Use one viewer worker with it, since each worker has its own rate limit.
- Queries take 3–200 Unicode code points and return up to five results within five seconds, in a response of at most 64 KiB. Result labels are capped at 600 Unicode characters.
- A per-process cache holds 128 searches for 15 minutes. In multi-user mode each account sees only its own entries, but the 128-entry capacity and the provider throttle are shared across the process.
- Facet waits at least one second between provider calls and never sends two at once.
- Facet does not log queries. Configure your reverse proxy not to log query strings.

## Capsules

Themed slideshows grouped by theme, place, people and time. Open `/capsules` and click a capsule to play it.

### Capsule Types

Facet generates capsules from your library:

- **Journey** — trips detected via GPS clustering, with reverse-geocoded destination names ("Journey to Rome — March 2025")
- **Moments with [Person]** — best photos of each recognized person
- **Seasonal Palette** — photos grouped by season + year
- **Golden Collection** — top 1% by aggregate score
- **Color Story** — visually similar groups via CLIP embedding clustering
- **This Week, Years Ago** — extended "On This Day" across ±3 days
- **Location** — geotagged photo clusters with place names
- **Favorites** — favorited photos grouped by year and season
- **Dimension-based** — by camera, lens, category, composition pattern, focal length range, time of day, star rating, and combinations

### Slideshow

Click a capsule card to start a slideshow:
- **Themed transitions** — slide (journeys), zoom (portraits), kenburns (golden/seasonal), crossfade (default)
- **Auto-chaining** — when a capsule ends, a card previews the next one
- **Shuffle & resume** — photos are shuffled; your position is kept per capsule
- **Adaptive grouping** — portrait photos are shown side by side to fit the screen
- **Save as album** — keep any capsule as an album

### Freshness

Capsules rotate on a schedule (default: 24 hours). **Regenerate** in the header refreshes them now.

### Reverse Geocoding

Location and journey capsules show place names (e.g., "Paris, France") using the offline `reverse_geocoder` package. No API calls; results are cached in the database.

Install: `pip install reverse_geocoder`

### Configuration

See [Configuration — Capsules](CONFIGURATION.md#capsules) for all settings.

## Folders View

Browse by directory at `/folders`.

- Breadcrumbs move up the tree.
- Each folder shows its highest-scoring photo as cover.
- Click a folder to open it, or a photo to open it in the gallery.
- Each folder card has a filter action that opens the gallery restricted to that folder.
- In multi-user mode, you see only your directories.

### Folder Filter

The filter sidebar's **Folder** section has **Choose folder…**, a picker that walks the tree. Applying it restricts the gallery to that folder **and its subfolders**. It shows as a chip, combines with other filters, survives a reload (`path_prefix` URL parameter) and saves into smart albums.

It narrows the photo grid only. Sidebar dropdowns, type counts, statistics, timeline, map and search stay library-wide.

## GPS Filter Dialog

Filter photos by location with a map picker:

- Click the location filter button to open the map.
- Click or drag to set a center point.
- Adjust the radius slider.
- Photos within the radius appear in the gallery.
- Requires GPS coordinates (run `--extract-gps` if photos have EXIF GPS data).

## Merge Suggestions

Find person clusters that may be the same person. Open `/merge-suggestions` or go through the Manage Persons page.

- **Similarity threshold slider** — lower shows more suggestions, higher fewer
- **Merge** — accept a suggestion
- **Batch merge** — merge several suggestions at once
- Dismissed suggestions are not proposed again
- CLI: `python facet.py --suggest-person-merges`

## Editor Export

Write ratings, favorites and rejects to XMP sidecars so darktable, Lightroom and other editors pick them up. Requires edition mode.

- **From the gallery** — select photos, then **Actions → Export** writes a sidecar next to each file.
- **From an album** — export the whole album as sidecars, or copy/symlink its files to a folder (same allow-list as [Cull to folder](#cull-to-folder)). Albums use their stored membership, smart albums included.
- **Write metadata to file** — in photo detail, embeds rating and keywords into the original (JPEG/HEIC/TIFF/PNG/DNG via exiftool) as well as writing the sidecar. Proprietary RAW files are never modified. Controlled by `viewer.features.show_embed_metadata` (default: `true`).
- **Lightroom** (edition mode) — **Download Lightroom manifest** saves `facet_manifest.json` for the dialog's selection, for the `facet.lrplugin` **Facet: Apply ratings and flags...** step. **Import Lightroom state…** reads the `facet_lightroom_state.json` from the plug-in's **Facet: Export Lightroom State to Facet...** menu (Lightroom wins for rating and pick/reject) and reports matched/unmatched/changed counts. No `--import-lightroom` run is needed. See [Lightroom Classic](INTEROP.md#lightroom-classic).

**Limits and progress.**

- Exports are capped at 10,000 photos, for selections, filtered views and albums alike. A larger set is refused before anything is written; narrow the filters and retry.
- Exports run in the background, with progress and written/skipped/error counts. **Stop after current file** cancels between files; completed sidecars stay.
- Only one library job runs at a time. While an export runs, scans, recomputes and automatic retraining wait or are refused, and an export is refused while one of them runs.
- Closing the dialog stops watching progress, not the export.
- Reopen Export to editor to see your 20 most recent exports. **Retry unfinished files** starts a new job for failed, skipped and unprocessed files. A file interrupted mid-write may be written again.

## Download

Download photos from photo detail or the selection bar. The per-photo download menu lists the types available for that photo, including configured darktable profiles:

- **Original** (`original`) — the file as-is (JPG/HEIF), or a RAW converted to JPEG with the same rendering the viewer shows. A bracketed frame therefore downloads without exposure correction — see [CONFIGURATION.md](CONFIGURATION.md#bracketed-frames-render-uncorrected).
- **darktable** (`darktable`) — the companion RAW converted with a named darktable profile. Falls back to the original if there is no companion RAW.
- **RAW** (`raw`) — the companion RAW file as-is. Not available in shared albums.

**Saliency-aware social crop.** With `viewer.features.show_social_export` on (default `true`) and edition unlocked, the photo detail download bar has a **Social crop** menu. It lists `social_export.presets` (square 1:1, portrait 4:5, story 9:16 by default). Choosing one downloads a full-resolution JPEG cropped to that aspect and centered on the subject. The subject comes from the BiRefNet subject box (`photos.subject_bbox`, from `--recompute-saliency`), else the detected faces, else the center. The menu tooltip shows which was used (`saliency` / `faces` / `center`).

Endpoints: [API.md — Download](API.md#download).

## Culling

The culling page (`/culling`, edition mode) groups near-identical shots so you keep the best of each and reject the rest. Pick the keeper(s) in each group; confirming rejects the others. Confirms are deferred and can be undone (see [Undo](#undo)).

**Granularity** (the first toolbar control) chooses how photos are grouped:

- **All** (default) — bursts and similar groups merged.
- **Bursts** — photos shot close together in time.
- **Similar** — photos that look alike whatever their time, by CLIP/SigLIP similarity. A slider sets how strict.
- **Scenes** — chronological capture-time runs, each headed by its time span and main narrative moment. Needs `viewer.features.show_scenes`.
- **Exposure brackets** — sets found by [`--detect-sequences`](COMMANDS.md), base exposure first, each frame badged with its compensation (`-2 EV` … `+2 EV`).
- **Panoramas** — sweeps found by [`--detect-panoramas`](COMMANDS.md), in capture order, middle frame marked.
- **HDR panoramas** — panorama sweeps with an exposure spread past `hdr_min_span_stops`. A tripod HDR set first appears under **Exposure brackets** and moves here (as `hdr_panorama`) once the panorama pass recognizes the sweep. If it never does, it stays a bracket.

**Keep-whole sets.** Exposure brackets, Panoramas and HDR panoramas are not part of **All**. Every frame starts kept and confirming records no comparison pairs. Double-click ("keep only this one") does nothing there. These feeds ignore the gallery's `hide_*` toggles and show every frame. To drop flanking exposures, use auto-cull's bracket trimming (below).

A group left with fewer than 2 frames after already-rejected photos are removed is dropped from the feed.

**Sorting.** The **sort mode** (easiest first, most redundant, best, most recent, needs comparisons, **oldest first**) sits beside the granularity, with an arrow button that reverses it. Oldest first also orders photos *inside* each group by capture time, which suits brackets and pans.

Granularity, sort and category persist in `localStorage`. Controls that don't apply are hidden (no sort or threshold in scene mode; no scope button without manual albums). On small screens the toolbar becomes a scrollable bottom bar.

**Trash all rejects (to OS trash).** This toolbar button previews every rejected photo visible to you across the library, hidden frames included. It ignores album, date and gallery filters. **Apply** sends the files to the OS trash on the Facet machine. Unlike **Delete**, library rows and decisions stay, for My Taste.

- Needs edition access, `viewer.cull.allow_trash` and trash support.
- Capped at 10,000 photos. For more, use Show Rejected Only in the gallery, narrow by date or album, and use Cull to folder → Trash rejects in batches. Turn off group-hiding filters to include every rejected frame.
- Companion RAW/XMP files are opt-in.
- If the resolved files, options or destination changed since the preview, Apply is refused; preview again. The check compares file names and settings, not file contents, and does not lock the files.
- A filesystem failure partway leaves completed files trashed; the dialog stays open for a new preview.
- In containers, trash and recovery depend on the server's filesystem.

> **Warning:** on a shared library, Trash all rejects uses only *your* rejections. It trashes the shared files even if another user kept, favourited or rated them. Check the preview.

**Scoped culling.** Narrow the darkroom with URL parameters: `?group_by=scene` for scenes, `?album=<id>` for an album, `?from=&to=` for a capture-time window (EXIF text or ISO dates such as `2026-06-01`). A banner shows the scope with **Exit scene**. Bursts that cross the window's edge still show all their frames.

**Date range.** The **date range** button (icon `date_range`) offers **Last 7 days**, **Last 30 days**, **This year**, **Last year**, **Custom range...** and **All dates**. Dates show as dd/MM/yyyy.

- It combines with the album scope. Photos without a capture date drop out of a dated range.
- Presets resolve when picked, so a bookmarked "Last 7 days" is a fixed window.
- The range lives in the URL only (`?from=2026-07-01&to=2026-07-31`), not in `localStorage`.
- Changing it reloads the feed: a pending confirm is committed, unconfirmed selections and skips are dropped.

**My Taste line.** Every confirm records `source='culling'` comparisons that train the personal ranker. The Help dialog (user menu → Help) shows "My Taste · N comparisons" (`GET /api/ranker/status`) and lists the culling shortcuts.

**Genre profiles.** The **Profile** selector applies a genre preset that sets strictness, keeper budget, similarity threshold and the eyes-closed / poor-expression face cutoffs at once. Sports keeps only the sharpest of a burst, weddings keep more eyes-open variants, concerts and wildlife relax the face gates. The choice and the strictness slider persist in `localStorage`. Changing a knob by hand shows "Custom". Presets live in [`cull_profiles`](CONFIGURATION.md#genre-aware-culling-profiles) (`GET /api/culling/profiles`).

### Auto-cull

**Auto-cull** in the toolbar culls a whole scope in one pass.

1. Pick the scope: all groups, or only bursts / similars / scenes, optionally an album or date window.
2. Set **strictness** (higher keeps fewer per group).
3. Preview. Each group keeps its best photo plus anything within the strictness margin (at least a per-group minimum), and rejects the rest.
4. Confirm. Rejections are recorded, kept photos are marked **Kept**, and My Taste learns from it.

- The preview is a **dry run**: nothing is written.
- An optional **Highlights** album collects each group's best photo scoring at least `auto_cull.highlights_min`.
- A "better photo in this group" badge flags groups where auto-cull would keep a different frame than the current lead.
- When a keeper-ranking head is trained and passes its accuracy gate, it picks the keeper (`keeper_prob`). Otherwise the usual heuristic does.
- The button is hidden in the keep-whole granularities. In a mixed scope, brackets are decided first.
- Configure with the [`auto_cull`](CONFIGURATION.md#auto-cull) block (`POST /api/culling/auto`). Run it from the terminal with `python facet.py --auto-cull` — see [Culling](COMMANDS.md#culling).

**Trimming redundant brackets** (`trim_brackets`, off by default) is the only way auto-cull ever reduces a set. When a bracket's base exposure clips neither shadows nor highlights, the flanking frames add nothing, so only the base frame is kept. Sets whose base clipping was never measured are left alone.

### Assistant plan mode

When an assistant connected through [AI Agents (MCP)](AGENTS.md) previews an auto-cull (`auto_cull`, or `ui_show_culling_plan`), your open tab loads that plan on `/culling`. It is the normal darkroom (loupe `Z`, compare 2-up / 4-up, peaking), with the plan's keepers preselected.

- A banner reads **Assistant plan · x/y confirmed · Exit**.
- Each group has a chip such as **#3 · reason · suggested keep 2 / reject 1**. A blue header chip is the assistant's note on the group.
- A dot on a frame means you changed it from the plan.
- A dashed **Assistant: keep** / **Assistant: reject** badge is the assistant's suggestion, with its reason in the tooltip. Click it (or Enter/Space) to apply it; you still confirm the group.
- Confirm group by group as usual, with the countdown and **Undo**. Plan-mode confirms never add to a highlights album.
- A confirmed burst or similar group leaves the plan. A confirmed scene group is not recorded, so the next preview may propose it again.
- Confirming a burst rejects only the members shown; members outside the album or date window are untouched.
- Sort and threshold are locked. Moving the strictness slider or changing the **date range** re-plans; your flips and confirmed groups carry over. **All dates** may hit the plan cap (`plan_truncated`).
- **Exit**, or changing grouping, scope or sort, leaves plan mode. Leaving `/culling` and coming back restores it; reloading drops it.
- If the library changed since the preview, a notice says the plan is out of date. Oversized groups are left out and counted in a notice.

The assistant reads your progress with `ui_get_context` (`culling`: confirmed, pending and changed groups) and applies nothing from the tab itself. See [Plan mode on `/culling`](AGENTS.md#results-are-shown-in-your-tab).

### Fullscreen

Press **`F`** (or the header toggle) to review full screen with no app chrome. Press `F` or `Esc` to exit.

Press **`S`** (or the header's stack button) to stack the open group with the focused frame as cover. Decisions are untouched and Undo is offered. Not offered for groups with bracket or panorama frames, or with a photo already in a stack.

### Loupe / Z-key zoom

Press **`Z`** in single view to toggle a loupe (fit ↔ 2×; wheel or `+`/`-` up to 800%). Zoomed past fit, the pane loads the full-resolution `/image`, so you judge focus on real pixels. Thumbnails are 640px and the fit view is a render of up to 1920px; the loupe goes beyond that.

- On the Scenes contact strip, `Z` toggles a hover magnifier with a zoom slider.
- Panes show the stored thumbnail first, then swap to the sharp render. The next and previous frames are prefetched (except with Data Saver on).
- A render that cannot start within 5 s is replaced by the thumbnail for 60 seconds.

**Darkroom hover loupe.** A round magnifier follows the cursor over the main frame, each compare pane and the face close-ups, showing full-resolution pixels. A toolbar toggle turns it on or off (on by default, saved per browser). It pauses while the frame is zoomed past fit, works in fullscreen and follows `←`/`→`.

### Per-Face Badges

In the culling lightbox, each face carries its own badges: eyes open/closed, poor expression and detection confidence. You can see which face in a group shot has closed eyes. Fetched per group with `POST /api/culling-group/faces`.

**Face panel.** Face crops are coloured green / orange / red from their eyes-open and smile scores.

- **Eyes** and **smile** sliders tune what counts as a blink or weak expression. They start at `face_detection.eyes_closed_max` and `face_detection.poor_expression_min` (both default `4.0`).
- **Size** (64–256 px, steps of 16, default `112px`) resizes the crops. Slider values are saved per browser.
- After using a slider with the mouse, the arrow keys go back to the darkroom (`←`/`→` frame, `↑`/`↓` keep/reject). Tab onto a slider to adjust it by keyboard.

**Subject close-up strip (non-face groups).** For groups without significant faces (wildlife, macro, products), the darkroom shows each frame's main subject side by side, cropped from the BiRefNet subject box. Each crop has a sharpness badge (10 = sharpest in the group) and a green / amber / red ring. Click a crop to jump to that photo. No model runs (`POST /api/culling-group/subjects`). For an existing library, run `python facet.py --recompute-saliency` (GPU) first; until then the strip does not appear.

**Key subject (zoom target + key person).** Zooming (**`Z`**, double-click or the first wheel step) lands on the frame's key subject instead of the center: its best face, or the subject box if it has none. Once you pan or zoom a frame yourself, Facet stops re-framing it. A named person who wins gets an amber name pill in the face strip. Named people in the middle distance beat bigger strangers; a tiny background face does not win. Nothing is stored. Boxes are fractions of the full frame (`normalized_frame_xyxy`). Endpoints: `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Synced compare (2-up / 4-up).** The header's Single / Compare 2 / Compare 4 buttons switch views. In compare mode all panes share one pan/zoom, so you compare the identical crop. Double-click toggles fit ↔ zoom. At fit each pane shows `/thumbnail?size=1920`; zoomed, it loads the full-resolution `/image`. Touch pinch is not wired yet; use the mouse wheel.

**Swipe to keep or reject (touch).** On a touch device, drag the frame right to keep or left to reject. It tilts and tints green (KEEP) or red (REJECT).

- Past 35% of the width (at least 48px), releasing commits the same decision as `↑` / `↓` and moves to the next frame. Short of that, it springs back.
- A vertical drag is ignored.
- Each swipe shows **Undo**, which restores the decision and returns to that frame.
- Only in single view, at fit scale, with a finger or stylus. A one-line hint shows until dismissed.

**Edited-look preview.** In single view, the **palette** menu lists "Original" plus each configured darktable style, so you can cull on the developed look.

- Facet renders the original through darktable-cli (`--style`, bounded to `preview_max_edge`). On failure it reverts to Original.
- The style stays for the current group and resets when you reopen the darkroom.
- Shown only when a style is configured **and** darktable-cli is found. Styles must exist in the darktable config of the user running the viewer.
- Renders are cached on disk.
- Endpoint: `GET /api/photo/cull_preview?path=&style=` (edition). Configure via [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#raw-decode).

## Scenes View

A **read-only** view of the library as chronological scenes, in story order with date/moment headers and a hover loupe. Open to **all authenticated users**.

- A new scene starts when more than `scenes.gap_minutes` pass between shots (widened on sparse shoots). Very long runs are split.
- Open it from an album's **Display scenes of this album** action in the Albums grid; a picker switches albums. There is no Scenes item in the main nav.
- Each scene has an edition-only **Cull this scene** button that opens [Culling](#culling) on that scene (`/culling?group_by=scene&album=&from=&to=`).
- With narrative moments computed, each scene is titled by its main moment, and `scenes.split_on_moment_change` can split a run where the moment changes.
- Scenes smaller than `scenes.min_size` are omitted; at most `scenes.max_photos` photos load.

Controlled by `viewer.features.show_scenes` (default: `true`). See [Configuration — Scenes](CONFIGURATION.md#scenes) for `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` and `adaptive_k`.

## Narrative Moments

Facet labels each photo with the activity it shows. The default **general** vocabulary: celebration, dining, beach, water activity, mountains, nature & wildlife, cityscape, travel landmark, concert, sports, group gathering, portrait, children, pets, nightlife, ceremony, scenic landscape, snow & winter, home indoor, road & vehicle, or `other`. A `wedding` vocabulary is available as an opt-in genre.

- It runs locally, with no extra model pass: each photo's AI caption is matched against each moment's text prompts (the image embedding is used when there is no caption). Timeline smoothing fixes isolated misreads.
- An optional VLM tie-breaker (16gb/24gb) re-checks low-confidence frames.
- It **runs automatically at the end of every scan**. The first pass over an existing library encodes every caption (GPU recommended). Relabel everything with `python facet.py --recompute-moments`.
- Moments appear as scene titles and a gallery filter (`GET /api/photos?narrative_moment=beach`, options from `GET /api/filter_options/narrative_moments`).
- The vocabulary is configurable — see [Configuration — Narrative Moments](CONFIGURATION.md#narrative-moments).

**Moment confidence.** Each label has a confidence (`narrative_moment_confidence`). Labels below `viewer.moment_confidence_min` (default `0` = never dim) appear dimmed with "(uncertain)" in the Scenes and Culling headers and the tooltip. Confidence is also a sort (**Moment Confidence**, under Content) and a 0–1 range filter (`min_moment_confidence` / `max_moment_confidence`, sidebar **Moments** section).

## Junk Sweep

A quick review queue for screenshots, scanned documents, receipts, memes and slides. Run `python facet.py --detect-junk` (it also runs after each scan) to fill `junk_kind`. See [Configuration — Junk Sweep](CONFIGURATION.md#junk-sweep).

Open **Junk Sweep** in the nav (`/junk`, edition only):

- **Kind filter chips** — "All kinds" plus one chip per kind with its count (`GET /api/filter_options/junk_kinds`).
- **Candidate count** — counts down as you decide.
- **Keep** — removes the photo from the queue **for good** (`not_junk`); later `--detect-junk` runs skip it.
- **Reject** — marks the photo rejected (nothing is deleted).
- **Reject all shown** — rejects every loaded candidate, after confirmation.
- **Loupe** — press **`Z`** (or the toolbar toggle) to magnify fine text.

Junk photos stay visible in the normal gallery. Filter for them with `?junk_kind=<kind>` or `?junk_kind=any` (excludes `not_junk`).

Controlled by `viewer.features.show_junk_sweep` (default: `true`).

## Pairwise Comparison Mode

Rank photos by judging two at a time; the votes feed weight tuning. Open `/compare` (Compare button in the header). Requires a non-empty `edition_password` (single-user) or `admin`/`superadmin` role (multi-user).

### A/B Compare tab

Pick a winner, mark a tie or skip. A progress bar counts toward 50 votes, with A-wins/B-wins/tie totals. A category filter scopes the session; a strategy dropdown chooses pairs:

| Strategy | Description |
|----------|-------------|
| `learning` | Default. Diverse pairs first, then pairs the personal ranker disagrees on most (most informative) |
| `uncertainty` | Photos with similar scores (most informative) |
| `boundary` | 6–8 score range (ambiguous zone) |
| `active` | Photos with the fewest comparisons (ensures coverage) |
| `random` | Random pairs (baseline) |

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `A` | Left photo wins |
| `B` | Right photo wins |
| `T` | Tie |
| `S` | Skip pair |
| `Escape` | Close category override modal |

### Weight Suggestions tab

Compares the weights learned from your votes with the current ones, with model accuracy before/after and the top 10 photos now vs. after recompute.

- **Apply** writes the suggested weights; **Recompute** rescores the category (both edition mode).
- **Apply** appears only when the suggestion beats the current weights on held-out comparisons (`suggest_changes`, the same test as `--optimize-weights`, see [COMMANDS.md](COMMANDS.md)).
- Unlike `--optimize-weights`, **Apply** does not re-centre the category's bonus, so its mean score can move.

### Weights tab

A slider per metric for the selected category, with a live score preview. **Save** writes `scoring_config.json` (with a backup); **Recompute Scores** applies it; **Reset** reloads the stored weights.

### Snapshots tab

Save the current weights as a named snapshot and restore any earlier one. A snapshot also restores the category's bonus (`modifiers.bonus`). Snapshots from before 1.21, from `calibrate.py`, or for `others` carry no bonus and leave it unchanged.

### Category Priority & Scoring Contexts

Categories are checked in ascending `priority` order; the first match wins. See [Filter Evaluation](SCORING.md#how-scoring-works) and [Scoring Contexts](CONFIGURATION.md#scoring-contexts). Two edition-only tools change this without editing `scoring_config.json`:

- **Global priority** — reorder the base evaluation order.
- **Scoring contexts** — presets (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) that promote some categories and exclude others, without changing the global order. Edit any non-`default` preset in the **Scoring Context** tab: drag (or move up/down) the promoted categories, toggle exclusions, save. A category listed in both wins as excluded. `label_key` and `suggest_from_moments` are not editable here. Assign a context per album (see [Scoring Context](#scoring-context)) or per photo (below).

Neither rescores photos by itself. Afterwards, run a recompute (`POST /api/scan/recompute`) and watch `GET /api/scan/recompute_status`. A scan or recompute already running from a terminal blocks a new one from the viewer. With `normalization.per_category` on, one recompute may not fully converge — see [Normalization](CONFIGURATION.md#normalization) and [Reordering the global priority](CONFIGURATION.md#reordering-the-global-priority).

**Category collisions** (`GET /api/stats/categories/overlap`) shows which higher-priority category is capturing a category's photos. Per category it lists **Assigned**, **Matches filters** (if evaluated alone) and **Captured by higher priority** (`matched - assigned`, floored at 0). **Top colliding pairs** ranks categories by shared photos. The `default` catch-all is left out, since it matches everything.

### Category Override

Reassign a photo's category from the comparison view: edit the category badge, choose a category, run "Analyze Filter Conflicts" to see which filters exclude it, then apply. The override is sticky: it survives recomputes until you clear it (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

The photo lightbox has the same actions under **Set scoring category…** / **Clear override** (edition only). The chevron in the category chip opens **why isn't this a different category?**: pick a category and it lists the filters that exclude the photo and what each would need, e.g. *"Raise shutter_speed_max from 0.02 to 0.033"*. This shows when a category is unreachable for a photo, which reordering cannot fix (`POST /api/comparison/suggest_filters`).

## EXIF Statistics

The Stats page (`/stats`) has 5 tabs. The **category** and **date range** selectors filter every chart. In multi-user mode each user sees statistics for their own visible photos.

### Tabs

| Tab | Description |
|-----|-------------|
| **Equipment** | Camera bodies, lenses, and combos (top 20 each) |
| **Shooting Settings** | ISO, aperture, focal length, shutter speed distributions |
| **Timeline** | Photos over time |
| **Categories** | Category analytics, weight management, and score correlations |
| **Correlations** | Custom X/Y metric correlation charts with grouping |

### Categories Tab

Four sub-tabs:

| Sub-tab | Description |
|---------|-------------|
| **Breakdown** | Photo counts per category, average scores, score distribution histograms |
| **Weights** | Radar chart comparison (up to 5 categories), weight heatmap, and weight editor (edition mode) |
| **Correlations** | Pearson correlation heatmap showing how each dimension influences the aggregate, click-to-detail view |
| **Overlap** | Filter overlap analysis showing which categories share matching photos |

Each chart has a `?` button explaining how to read it; a toggle in the sub-tab bar shows all explanations.

### Weight Editor (Edition Mode)

In the Weights sub-tab, with edition mode on:

1. Select a category from the dropdown
2. Adjust the weight sliders (one per metric, should sum to 100%)
3. Use "Normalize to 100" to auto-balance
4. Expand the Modifiers section to adjust bonuses/penalties
5. The **Score Distribution Preview** shows a live before/after histogram
6. Click **Save** to update `scoring_config.json` (creates a timestamped backup)
7. Click **Recompute Scores** (appears after save) to apply the weights to that category

## Keyboard Shortcuts (Gallery)

Single-key shortcuts are inactive while focus is in a text field, menu or list.

| Key | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Move the current-photo marker between photo cards (grid columns and mosaic rows) |
| `Enter` | Open the focused photo |
| `Space` | Select / deselect the focused photo |
| `Ctrl+A` / `Cmd+A` | Select all — the whole filtered view from an empty selection, otherwise the loaded photos |
| `Escape` | Clear selection (in side-panel mode, also releases the held photo) / close filter drawer |
| `Shift+Click` | Range-select photos between last selected and clicked |
| `Double-click` | Open photo |
| `Shift+F10` / `Menu` | Open the context menu of the focused photo card (right-click does the same) |
| `1`–`5` | Rate the focused photo 1–5 stars (edition mode; auto-advances to the next photo) |
| `K` | Keep the focused photo (edition mode) |
| `F` | Favourite / unfavourite the focused photo (edition mode) |
| `X` or `0` | Reject / un-reject the focused photo (edition mode; auto-advances) |
| `/` | Focus the toolbar search (shown from 1360 px wide); narrower, opens the filter sidebar's search |
| `S` | Open the stack editor for the explicit selection (edition mode; remappable, can be left Unassigned) |
| `Ctrl+Shift+S` / `Cmd+Shift+S` | Stack the explicit unstacked selection at once in selection order, the first photo as cover (edition mode; existing stack members open the editor) |
| `B` | Show / hide the filter sidebar |
| `V` | Switch between grid and mosaic layout |
| `?` | Show the keyboard shortcuts reference (every page; also in user menu → Help) |

**Remap keys.** `K`, `F`, `X`, `/`, `B`, `V` and `S` are defaults. User menu → **Customize shortcuts** lets you click an action and press a new key (`Esc` or `Tab` cancels). Digits, `Space` and `?` are reserved, and a key already in use is refused. **Reset all** restores the defaults. The mapping is stored per browser (`localStorage`). The photo page uses the same keys, and the `?` reference always shows the keys in effect.

**Current photo.** The photo that rating, favorite and reject keys act on has a 4px outline; other cards dim to 50%. Nothing is marked until you move onto a photo. Clicking a photo moves the marker to it. Returning from a photo leaves the marker on the last one you viewed. The focused-card hint appears only in edition mode with `viewer.features.show_rating_controls` on.

**On the photo page**, `1`–`5`, the favourite key and the reject key (`F` and `X` by default; `0` also rejects) act on the open photo, in edition mode with `viewer.features.show_rating_controls` on. They do not advance; use `←` `→`. The `?` reference lists them under *Photo view*.

## Undo

Batch favorite/reject/rating changes and culling confirms show a snackbar with **Undo** for ~7 seconds.

- Batch flag changes apply at once and are undone by reversing them (up to 500 photos).
- Culling confirms are deferred: the group disappears at once, but nothing is saved until the undo window ends.
- [Manual tag](#manual-tags) edits are not undoable.

For older changes, see [Organization history](#organization-history).

## Progressive Web App

Production builds can be installed to the home screen. The app shell loads offline, and up to 1000 thumbnails are cached for 7 days (larger sizes, such as the darkroom's 1920 px renders, rely on the browser cache). API responses are never cached, except translation bundles. A snackbar offers a reload when a new version is deployed.

> **Warning:** logout clears the app's thumbnail cache but not the browser's HTTP cache, which can keep viewed images (thumbnails, renders, full-resolution images) for up to a year. Accounts that must not see each other's photos should not share a browser profile.

## Mobile

On small screens the floating selection card keeps the count and the clear, select-all and invert buttons, plus an **Actions** button. It opens a bottom sheet with every bulk operation (favorite, reject, rate, albums, copy, download). A compare button appears when the selection fits the compare view.

## Photo Frame / Kiosk Endpoint

Smart photo frames, Home Assistant dashboards and ImmichFrame / Immich-Kiosk style displays can pull your best shots without logging in. There is **no client UI**: devices call the endpoints with a long-lived **frame token** from the `frame` config block. With `frame.tokens` empty (the default), the feature is off and every endpoint returns 404.

- **What is shown.** Photos come from the whole library, not one user's folders. Rejected, junk and blink photos are excluded. `frame.min_aggregate` (default 7.0) sets the score floor; `frame.favorites_only` and `frame.categories` narrow it further.
- **Variety.** Photos are a score-weighted random sample, so you see different good shots rather than the same few.
- **No file paths.** Each photo is addressed by an opaque signed id, so a token holder cannot learn where your files live or browse other rows.

| Endpoint | Returns | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` capped at `frame.max_count` (default 100), defaults to `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | the photo JPEG — original downscaled to `max_edge` (capped by `frame.max_edge`, default 1920), or the stored thumbnail if the original is unreachable | long immutable |
| `GET /api/frame/next?token=` | one random curated JPEG, different on every call — for simple frames and Home Assistant | `no-store` |

### Generating a token

A token is any string you choose. Use a long random one and treat it like a password:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add it to `frame.tokens` in `scoring_config.json`. List one per device; remove one to revoke it:

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Home Assistant recipe

`/api/frame/next` works as a Home Assistant [generic camera](https://www.home-assistant.io/integrations/generic/); every refresh pulls a new shot:

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # refresh every ~20s
```

Add the camera to a Picture Glance / Picture Entity card to get a self-updating photo frame.

For an **ImmichFrame-style** client that runs its own slideshow, poll `GET /api/frame/photos?token=…&count=30` for ids, then fetch each `GET /api/frame/image/{id}?token=…&max_edge=1920`. Ids are stable and images are cached long-term, so each photo downloads once.

## Phone Auto-Upload

Push photos from your phone into Facet. A small **WebDAV** server at `/dav` lets PhotoSync (or any WebDAV client) upload into an **inbox directory**. Put the inbox inside a scanned directory and run `facet.py --watch` on it: each photo is scored as it arrives.

- **Separate credentials.** Access uses HTTP Basic with a shared device login from the `upload` block (`upload.username` / `upload.password`), not a user account.
- **Off by default.** `/dav` returns **404** until `upload.username`, `upload.password` and `upload.inbox_dir` are all set.
- **Confined to the inbox.** Nothing outside `upload.inbox_dir` is reachable. Files are capped at `upload.max_file_mb` (default 500).
- **Methods:** `OPTIONS`, `PROPFIND` (depth 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` are not implemented; upload apps work without them.

### Configuration

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Keep `inbox_dir` under a scanned directory so `--watch` sees uploads:

```bash
python facet.py /photos --watch
```

### PhotoSync recipe

1. In PhotoSync, add a **WebDAV** configuration (Configure → Add Configuration → WebDAV).
2. **URL / Server**: `http://<host>:5000/dav/` (`https://` behind a reverse proxy).
3. **Username / Password**: your `upload.username` / `upload.password`.
4. **Target folder**: the root (`/`) for the inbox, or a subfolder.
5. On the Facet host, watch the inbox so uploads are scored:

   ```bash
   python facet.py /photos --watch
   ```

### curl smoke test

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (or `204 No Content` when overwriting) means the file reached the inbox; `--watch` scores it shortly after.

## Configuration

### Display Settings

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Pagination

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Dropdown Limits

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Raise `min_photos_for_person` to hide persons with few photos from the filter dropdown.

### Quality Thresholds

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Default Filters

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Top Picks Weights

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performance

### Large Databases (50k+ photos)

Run these for better performance:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

`--migrate-tags` is a one-time setup. Afterwards, scans, `--recompute-tags`, `--recompute-tags-vlm` and `tag_existing.py` keep the tag table current. Until you run it, tag filters use a slower fallback.

Check the statistics cache (5-minute lifetime) with:

```bash
python database.py --stats-info
```

### Gallery Indexes and the Count Cache

Facet adds indexes that keep gallery pages and counts fast on large libraries. On a 130k-photo library they took the default page from about 1.2 s to 26 to 38 ms with the count cached, and about 104 ms right after a database change.

- **Built once, in the background.** The first viewer start after an upgrade builds missing indexes while the viewer already serves. On a 130k-photo library the largest index took 45 to 55 s to build and about 106 to 111 MB of extra database size. While an index is written, saves are briefly refused with a "try again in a moment" message. A `python facet.py` scan or `python database.py` run builds them first instead. See [DEPLOYMENT.md](DEPLOYMENT.md#viewer-start-and-the-gallery-indexes) for writes during the build, shutdown, `--workers N` and Docker.
- **Writes get slightly slower**: about 0.5 to 0.7 ms more per row when a column these indexes carry changes.
- **Count cache.** Gallery counts are cached for 5 minutes. Any change from a process on the same host (including `--detect-junk` and `--recompute-*`) refreshes them. A change made from another machine over a network share shows up when the cache expires.

## API Endpoints

The HTTP API reference is in [API.md](API.md). Interactive docs are served at `/api/docs`.

## JPEG XL photos

Facet scans JPEG XL (`.jxl`) with the core `imagecodecs` dependency, included in standard installs and Docker. No extra package is needed; scans skip `.jxl` only if that codec is unavailable.

- **Viewing.** Browsers that accept `image/jxl` get the original file; others get a JPEG. Gallery thumbnails are JPEGs.
- **Metadata.** Originals stay `.jxl`. Review edits go to sidecars, not into the file.
- **Animations.** Only the first frame is used.
- **Color.** A JXL that reconstructs a JPEG keeps its ICC profile and previews are converted to sRGB. For native JXL, the embedded color profile is not available, so scores and previews of wide-gamut or HDR files may not be color-accurate. Original downloads keep their bit depth and profile.
- **Limits.** Decoding checks the Pillow pixel limit before allocating pixels, and container-header inspection stops at 4,096 boxes. Encoded and decompressed EXIF are each limited to 16 MiB; oversized EXIF is dropped and the image stays readable. At most five JPEG conversions are cached. Files with unsupported extra-channel layouts are refused.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Slow page load | Run `--migrate-tags` and `--optimize` |
| Filters not showing | Check `--stats-info`, run `--refresh-stats` |
| Person filter empty | Run `--cluster-faces-incremental` |
| Compare button missing | Set a non-empty `edition_password` (single-user) or use `admin`/`superadmin` role (multi-user) |
| Password not working | Check `viewer.password` (single-user) or verify password hash (multi-user) |
| User can't see photos | Check `directories` in their user config and `shared_directories` |
| Scan button missing | Needs `viewer.features.show_scan_button: true` plus scan access — see [Scan Trigger](#scan-trigger) |
| Search returns no results | Ensure photos have `clip_embedding` data (run scoring first) |
| Search says Apple Silicon acceleration is busy | Retry once the current model task finishes |
| VLM critique unavailable | Needs the 16gb/24gb profile, `viewer.features.show_vlm_critique: true` and an edition session |
| Map shows no photos | Run `--extract-gps`; check photos have EXIF GPS data |
| Captions not generating | Requires 16gb/24gb VRAM profile for VLM captioning |
| Timeline empty | Ensure photos have `date_taken` values |
| Port 5000 in use | Run `python viewer.py --port 5001` (or set `PORT=5001`). On macOS, AirPlay Receiver uses 5000: pick another port or turn it off in System Settings → General → AirDrop & Handoff. |

### Review saved manual faces

Find photos whose saved face rectangles need checking. On the gallery sidebar's Review tab, enable **Manual faces need review** (editors). Open a photo's face editor and adjust and save, or delete, each flagged rectangle. The photo then leaves the list. The filter works in smart albums and whole-view selections, and shows as a removable chip.

- The list reflects the last scan or editor check, not live file watching. Scans check photos with manual marks even with face detection off.
- Opening the editor rechecks the original and is authoritative.
- Marks carried over by a relink (`relink_unverified`) stay flagged until saved again in the editor.
- Reviewing never changes original files. Viewer-database exports and updates keep the review status.

## Capture-date correction

Fix a wrong camera clock. In edition mode, choose **Correct capture date** from the calendar icon by the photo's date, or from the gallery selection bar. Up to 1000 visible photos, "Select all in view" included.

- **Shift by** (default): choose **Earlier** or **Later** and enter Days, Hours, Minutes and Seconds. Default: 1 hour later. Quick buttons −1 h, +1 h, −1 d and +1 d add to the shift.
- **Set exact time**: enter the correct date and time of a reference photo (the open photo, or the first dated photo of the selection; not for "Select all in view"). The shift is derived from it.
- The shift must be nonzero and at most ±366 days.
- A summary states the shift ("1 h 30 min later"), and the preview shows changed/skipped counts and the first 20 old/new timestamps.
- **Apply correction (N)** applies it. If something changed meanwhile, an error offers **Preview** to refresh.

**What changes.**

- Camera time is shifted as-is: no timezone or daylight-saving logic.
- Only complete `YYYY:MM:DD HH:MM:SS` or `YYYY-MM-DD[T or space]HH:MM:SS` dates are supported. Unknown, date-only, timezone/subsecond and invalid dates are skipped.
- Corrected dates survive rescans and incremental viewer database exports.
- **Use file date** removes the correction and rereads the file. No file date means an unknown capture date.
- Applying a correction never writes the original or changes its file time. XMP export writes `exif:DateTimeOriginal`; **Write metadata to file** also updates EXIF `DateTimeOriginal` in supported formats.
- Burst and sequence groups are not recomputed; rerun detection if you need regrouping.

Endpoints: `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — see [API.md](API.md).

## Organization history

Review and revert your recent edits across the library. In edition mode, open **Organization history** from the clock icon in the main navigation (after On This Day). Expand an entry to see exact before/after values, then **Revert this entry**.

- **What is recorded:** GPS, capture dates, review decisions, stars, favorites and manual stacks. Not files or face recognition.
- GPS and capture dates are shared library values. Review decisions, stars and favorites are your own.
- The short Undo and assistant activity list are separate.
- **Limits.** The latest **50 entries per account**, each up to **1000 photos and 1 MiB** of values. Larger filtered review actions are split into parts; revert restores one part. A stack replacement can cover up to 2000 photos in one entry.
- History survives restarts and incremental viewer database updates. A fresh/full viewer export starts empty. It does not sync to another database.
- **Revert is all or nothing.** It is refused if any photo's value changed since, even if changed back. Another account's private review edit does not block yours. Rescans, imports and Undo can also invalidate older entries.
- An entry is hidden when one of its photos is deleted or no longer visible to you.
- A revert adds its own entry and marks the original as reverted.

## Faces without names

Find unassigned faces and unnamed person groups: `Filters → Persons → Faces without names` (`faces_need_names=true`). Use + to assign a face, or name a group in People. Photos without detected faces are excluded.

Read-only users can browse this filter; assigning or naming needs edition access.

## Assigning people

The **Assign face to person** picker lists first up to 12 people you recently assigned in this browser (per signed-in identity). Other named people follow by face count in photos you can see. Search and paging cover everyone.

- A person becomes recent only after a successful assignment or manual-face save.
- Only person IDs are stored locally. Signing out clears the list.

## Refresh metadata and preview

Re-read a photo's metadata and rebuild its preview without a full rescan. Manual annotations, ratings, faces and AI scores stay. Originals are never written. Rescan if changed pixels need new scores or face detection.

- Up to 100 selected photos; whole-view selections are not supported.
- Missing source values do not clear stored ones. Without `exiftool`, only the preview is refreshed.
- Manual GPS and dates are kept.
- It is refused while another library job is running; retry later.
- Each photo saves separately; retry processes the failures.
- Until the next rescan, histograms use the new preview and colour-similarity search skips the photo.
