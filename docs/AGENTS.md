# AI Agents (MCP)

> 🌐 **English** · [Français](fr/AGENTS.md) · [Deutsch](de/AGENTS.md) · [Italiano](it/AGENTS.md) · [Español](es/AGENTS.md) · [Português](pt/AGENTS.md) · [简体中文](zh/AGENTS.md)

Facet can act as a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server, so an MCP-capable AI assistant can search and inspect your library with the gallery's filters. It exposes fourteen read tools that change nothing and fifteen `ui_*` tools that drive the browser tab you have open (page, filters, selection) without writing library data. Tokens with a high enough level can also [change things](#changing-things) (ratings, flags, tags, albums, culling and deletion) and work the [darkroom](#darkroom-culling-groups).

## Enable it

The endpoint is **on by default**. To turn it off, set `viewer.mcp.enabled` to `false` in `scoring_config.json` (see [Agent Endpoint (MCP)](CONFIGURATION.md#agent-endpoint-mcp)), then restart the viewer or reload the configuration. `/mcp` and every `/api/mcp/*` route then answer 404.

**Open installs.** Without `viewer.password` the install counts as open, even if `viewer.edition_password` is set. On an open install:

- tokens are `readonly` unless `viewer.trusted_local_editing` is on, or the token is a Full-editing one minted in an edition-password session and used from the same computer (see below);
- the endpoint serves only a read-only anonymous key, which grants nothing the open `/api` does not already grant;
- tokens can be managed only from the computer running Facet, or in an edition session when `viewer.edition_password` is set (see [Mint a token](#mint-a-token)).

The endpoint is `POST /mcp` on the viewer's own port: Streamable HTTP, stateless, plain JSON responses (`GET` answers 405). Only the tab bridge, `/api/mcp/bridge`, is a WebSocket; see [Control your open tab](#control-your-open-tab).

## Mint a token

The easiest way is the browser:

1. With `viewer.mcp.enabled` on, open the account menu and choose **Connect an assistant**.
2. Enter a **Name** and pick **What the assistant may do**: **Read and pilot only**, **Act as me** or **Full editing**. A token cannot out-rank the session that creates it.
3. Click **Create token**. The dialog shows **Paste this into your assistant**, a ready-made prompt that contains the token. It is shown once: click **Copy prompt**, paste it into your assistant and click **Done**.

**Manage tokens (N)** lists your tokens with their last use and revokes one. A status line says whether this tab is connected, so assistants can drive it.

The dialog only offers levels the server will grant:

- an open install offers **Read and pilot only**, plus **Full editing** in the cases listed below;
- **Act as me** appears only on multi-user installs;
- **Full editing** appears only in an edition session; on an open install that means a browser on the same computer under `viewer.trusted_local_editing`, or a session logged in with `viewer.edition_password` (the token then edits only from the same computer).

The prompt states the level actually granted. On an open install, opened from another machine without an edition session, the dialog shows "Assistant tokens on an open install can only be managed from the computer running Facet. Set viewer.password to manage them from another machine." instead of the form.

Scripted alternative (curl):

An assistant authenticates with a personal token that starts with `fct_`. Mint one with an authenticated request. The token is returned **once**; Facet stores only its SHA-256 hash:

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

The response carries the plaintext in `token`.

- `GET /api/mcp/tokens` lists your tokens (never the secret); `DELETE /api/mcp/tokens/{id}` revokes one.
- A superadmin can list every owner's tokens with `?all=1` and revoke any of them.
- Each owner can hold at most 20 live tokens.
- These routes refuse an agent's own credential, so an assistant can never mint, list or revoke tokens.

On an open install (no `viewer.password`) these routes also refuse any request that does not come from the computer running Facet:

- a request through a reverse proxy (any `Forwarded`, `X-Forwarded-*` or `X-Real-IP` header);
- a request to a LAN IP or hostname instead of `localhost`, `127.0.0.1` or `[::1]`;
- a request through Docker's bridge network.

Run the recipe above on the Facet host (over SSH on a NAS; in Docker, `docker compose exec facet python -c "import urllib.request ..."`, because the image has no curl), or set `viewer.password`. A session logged in with `viewer.edition_password` is accepted from any machine. A reverse proxy must send `X-Forwarded-For` or `Forwarded`, or it is treated as the local machine.

## Connect your assistant

The dialog's prompt holds everything an assistant needs: the server name `facet`, the URL (`http://<host>/mcp`), the transport (Streamable HTTP), the header `Authorization: Bearer fct_...`, the granted level, and a call to the `status` tool to check the connection. Paste it into your assistant, or add the server to your MCP client yourself. Use HTTPS when the viewer is reachable beyond your machine: the token travels in a header on every call.

## Permission levels

A token is minted with a grant: `readonly`, `user` or `edition`. On every call the **effective** level is recomputed as the lower of the grant and the owner's current level. Each tool has its own minimum level, checked before anything is read or written; a lower token gets `forbidden_level`.

- **Single-password installs** have no `user` level. A `user` grant is capped to `readonly` at mint time, and the effective level is `edition` or `readonly`. The tools marked `user` under [Changing things](#changing-things) therefore need an `edition` token; a lower token gets `forbidden_level`, saying it needs `edition`. An `edition` token needs an edition session and works only while the edition password is unchanged.
- **Multi-user installs.** If the owner is demoted, an `edition` token drops to `user`. A promotion never raises a token above its grant.
- **Open installs** (no `viewer.password`, even if `viewer.edition_password` is set). Tokens belong to a shared `_anonymous` owner and are `readonly`, unless `viewer.trusted_local_editing` is on or the token comes from an edition session (next two bullets).
- **Local editing on an open install.** With `viewer.trusted_local_editing` on, the Connect dialog can mint **Full editing** from a browser on the same computer. `viewer.mcp.enabled` and a token are still needed (a call without a token stays 401).
  - The token is `edition` only for `/mcp` requests from the same machine: a loopback peer, an `http://localhost:<port>` or `127.0.0.1` URL, and no proxy headers. Both `:4200` (the `ng serve` dev proxy) and `:5000` qualify.
  - Any other request resolves to `readonly`, even if the prompt says Full editing: a LAN client, a hostname or `0.0.0.0` URL, or a Docker deployment.
  - Setting any password lowers the token to `readonly`; clearing the password restores it.
  - Delete tools still need `viewer.mcp.allow_destructive`.
  - Scanning (`start_scan`, `scan_status`) works without `viewer.features.show_scan_button`, as it does for the local browser.
- **Edition password on an open install.** With `viewer.edition_password` set and no `viewer.password`, a session logged in with the edition password can mint **Full editing**, from any machine; any other session gets `readonly`.
  - The token is `edition` only for `/mcp` requests that pass the same-machine check above. A LAN client or a proxied request gets `readonly`: the token is a bearer secret on an install anyone can read.
  - Changing or clearing the edition password lowers it to `readonly`; mint a new one after the change.
  - Scanning still needs `viewer.features.show_scan_button`, as for an edition browser session. Delete tools still need `viewer.mcp.allow_destructive`.

> **Warning:** `ng serve --host 0.0.0.0`, or any proxy on the same host that adds no proxy headers, lets a LAN client that sends `Host: localhost` pass as local. Only the token then protects `/mcp`.

A token stops working when its owner's credentials change: the viewer or edition password (single-password mode), the owner's password (multi-user mode), or the owner's account being deleted. It then answers 401.

## Tools

The fourteen data tools are read-only:

| Tool | What it does |
|------|--------------|
| `search_photos` | Filter and sort the library like the gallery, with the viewer's default hide toggles (blinks, bursts, duplicates, brackets, panoramas, rejected) applied unless the filter sets them (reports `hidden_summary`). Shown in your open tab by default (see below); `fields` adds any photo column |
| `semantic_search` | Find photos by meaning, or by words in captions with `scope: "text"` The rows it returns are pinned in the tab. `filters` narrow the search like the gallery's, and each row carries its `similarity`. |
| `get_photo` | Full detail of one photo by its path (the histogram is left out); or `target: "selection"` (with `tab_id`) for the one selected photo |
| `get_photo_stack` | Read the local stack for an exact path, or null |
| `get_thumbnail` | Look at one photo: its thumbnail as an image part (`size` 160 to 640, default 512). A smaller size is used when the JPEG would exceed `viewer.mcp.max_image_bytes`; `too_large` when none fits; or `target: "selection"` (with `tab_id`) for the one selected photo |
| `contact_sheet` | Look at 1 to 16 photos as one numbered grid image (`columns` 2 to 4, longest edge 1024). The text part lists `legend` (tile number to path, in request order) and `unavailable` (tiles left blank because the photo is missing or not visible); or `target: "selection"` for the selected photos (at most 16) |
| `possible_faces` | Faces that look like one recognised person: cosine similarity to the person's centroid, best first, same embedding model only. `scope` is `unassigned` (default), `unnamed` (faces in no group or in a group nobody has named), `other_persons` or `all`; `min_similarity` defaults to 0.30; `limit` up to 100. Each row carries an `owner` field (`ungrouped`, `unnamed_group` or `named`). A scan above 192000 faces is refused (`too_large`): narrow it with `scope`, `path_prefix`, `date_from` or `date_to`. The photos are shown in your tab. `candidates` is the count of faces in scope you can see, before the embedding-dimension check; `faces_scanned` is the number of rows actually scored. |
| `similar_photos` | Photos similar to one photo, by visual embedding or by colour; `min_similarity` (0 to 1) sets the floor |
| `filter_options` | The vocabulary a filter accepts: cameras, lenses, tags, persons, patterns, categories, narrative moments, junk kinds, metric ranges |
| `list_persons` | Recognised people, optionally filtered by name; `show: true` opens `/persons` with this search |
| `list_albums` | Albums the token's owner can see; `show: true` opens `/albums` with this search |
| `library_stats` | Library statistics: `kind` selects the size and score overview (default) or any Stats page data (see below) |
| `status` | Who the token is, its effective level and the server flags and the open tabs it can drive |
| `available_actions` | The jobs that apply to your open tab and this token right now, each with its tools; tools above the token's level are not listed |

Filter notes:

- `show_rejected` is a boolean: `true` lists only rejected photos; `false` or omitted gives the normal listing. Agents can set it with `ui_set_gallery_filters` to show rejected-only searches in the tab. Smart albums can store it too (false is omitted).
- An explicit `review_status` decides the review state instead of `show_rejected` or `hide_rejected`, and clears `show_rejected` in the tab.
- `show_rejected: true` with `favorites_only: true` is refused by tab patches and smart-album creation (`invalid_input`). A search still returns the intersection, but reports `shown_in_tab.reason: invalid_combination` and leaves the tab unchanged.
- `blinks_only` and `duplicates_only` are booleans too. `true` keeps only blink-flagged photos, or members of a duplicate group (leads included). Like `show_rejected`, they show every such photo regardless of the hide toggles.

## Results are shown in your tab

- **Searches are shown in your tab.** `search_photos`, `semantic_search` and `similar_photos` take `show` (default `true`). After a successful first-page search, the server shows it in your open Facet tab, so you see what the assistant found without asking.
  - `search_photos` and `similar_photos` apply the same query to the tab, replacing its filters.
  - `semantic_search` pins exactly the rows it returned (similarity order, at most `limit`, with or without `filters` or `scope`) as an assistant-chosen list (`shown_in_tab.mode` is `paths`), because the tab's own semantic view filters and sorts differently.
  - `show: false` is for intermediate probes and counts; assistants are told never to ask whether to show results.
- The result carries `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, or `{"applied": false, "reason"}`. Reasons: `error` (the show itself failed), `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (the tab may still apply it), `forbidden`, `invalid_input`, `upstream_error`, `page_not_first`, `empty_result`, `unsupported_filters` (with `keys`), `invalid_combination`, `unsaved_decisions`, `navigation_refused` (the tab declined the navigation), `comparison_open` (the user is on `/compare`) and `modal_open` (a dialog, bottom sheet or slideshow is open in the tab). A failed show never fails the search. Pass `tab_id` to choose a tab. When rows are trimmed, `next_page` (with `suggested_per_page`) names the page that continues right after the last returned row; when pages cannot express that point, `next_offset` gives it as a row offset.
- Only the first page is shown (the tab pages itself as you scroll). An empty result is not shown, so you keep your previous view. A search using filters the gallery sidebar has no field for (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`) is never partly applied.
- A show leaves `/photo` for the gallery. It leaves `/culling` only when the user holds no unconfirmed decisions there (otherwise `unsaved_decisions`), and on `/compare` it is refused with `comparison_open`. It clears a whole-view selection. On an album page it first goes back to the gallery, so the album's saved filters are never overwritten. A search whose count feeds a write tool's `expected_count` should use `show: false`.
- `list_albums`, `list_persons` and `junk_list` take `show` (default `false`: they are mostly name lookups). With `show: true` they open `/albums`, `/persons` or `/junk` with exactly that query; an empty query clears the page's search and resets its other filters. `junk_list` shows only its first page (`page_not_first` otherwise) and never an empty list (`empty_result`). `shown_in_tab` has the same reasons as a search, with `mode` `route`. `list_culling_groups` has no `show`: use `ui_show_culling_group`.
- `ui_show_photos` pins an exact list of photos, shown in your order until any filter change replaces it. `ui_get_context` reports whether a pinned list is shown. The list is plain: no groups, marks or labels. To review a cull plan, the assistant uses `auto_cull`, which opens the plan in the [darkroom](#darkroom-culling-groups) (`/culling`).
- **Plan mode on `/culling`.** `ui_show_culling_plan` (called by `auto_cull` on a dry run) loads an `auto_cull` plan into the darkroom. You get the same groups, keep/reject borders, loupe and compare as manual culling, with the plan's keepers pre-selected. See [Assistant plan mode](VIEWER.md#assistant-plan-mode).
  - The user sees a banner "Assistant plan · x/y confirmed · Exit", a chip "#n · reason · suggested keep N / reject M" per group, and confirms group by group as usual. Sort and threshold are disabled; the strictness slider stays usable.
  - Moving the slider, or changing the toolbar date range, re-plans (a new `plan_digest`). Groups you flipped keep your choice. A group re-forms as confirmed when it falls inside a group you confirmed, scene groups included; with `group_by=all`, a confirmed burst whose keepers reappear inside a larger similar group is offered again (your rejections stay applied). Skipped groups come back. A confirm still counting down is committed at once. Confirm, skip and "confirm all" pause until the new plan arrives.
  - Narrowing the date range carries flips and confirmed groups over by photo set. Groups outside the window drop out, and a notice reports the flips lost. **All dates** re-plans the whole library and may hit the plan cap (`plan_truncated`).
  - **Exit**, or changing the grouping, the album/scene scope or the sort, leaves plan mode. Leaving `/culling` and coming back restores the plan. A full page reload drops it but keeps its album and dates in the URL (`?from=`, `?to=`), on a manual feed. Confirms in plan mode never add highlights.
  - **Suggestion badges.** `ui_suggest_culling` marks photos to keep or reject, with a short reason (a dashed badge), and adds notes to groups (a header chip). One click on a badge flips that photo; without a click nothing changes. Marks survive slider and date-range changes and a re-show of the same plan; a different plan, **Exit** or leaving plan mode clears them. Badges show on group tiles only, not in full-screen view or in confirmed or skipped groups.
  - The assistant's answer lists the paths not stored: `redundant` (already the plan's choice), `closed` (confirmed or skipped group) and `missing` (not in the plan). Notes for a group you confirmed, skipped or are confirming are listed as `groups_closed`. `suggestions_total` and `notes_total` give what the tab holds (at most 300 suggestions and 100 notes).
- **Reading your progress.** `ui_get_context.culling` is `null` outside plan mode. In plan mode it returns `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}`:
  - `confirmed`: plan group numbers whose confirm has landed.
  - `pending`: groups you flipped away from the plan and have not confirmed.
  - `untouched`: the number of other groups.
  - `changed`: every group whose keepers differ from the plan, as `{type, group_id, number, keep_paths, reject_paths}`.
  - `plan_truncated` is `true` when the plan itself hit its group or photo cap and lists only part of the groups.
  - A block too large for one answer (the tab's 100 KiB cap, or the server's) has shortened lists and `truncated` set to `true`. The true counts stay in `groups_total`, `confirmed_count`, `pending_count` and `changed_count`.
  - `culling.scope` (`{album_id, date_from, date_to}`) is the window the plan was computed for.
  - `suggestions_open` (`[{path, action}]`) lists marks still waiting for your click, `suggestions_accepted` the marks whose photo you put in the suggested state, and `suggestions_total` the photo marks the tab holds (not group notes). `suggestions_open_count` gives the true length when that list is cut.

  Never re-decide a confirmed group. A confirmed burst or similar group leaves the next preview. A confirmed scene group is not recorded anywhere and may be proposed again, so pass `changed` as `keep_paths` / `remove_paths` on the next dry run and on its apply. `auto_cull` takes dates only from its own arguments: pass `culling.scope`'s dates together with `culling.changed` on the next dry run (the new plan replaces the one shown). Moving the slider or the date range re-plans, so read `ui_get_context` again before the next dry run.
- **Culling defaults.** `ui_get_context` also returns `culling_defaults`, `{profile, strictness}`: the knobs `auto_cull` uses when given neither (see **Knobs from the tab** under [Darkroom](#darkroom-culling-groups)). They are stored per browser, so two tabs share them. `culling_defaults.strictness` is the slider's live, stored value: `null` when only a profile is stored, 100 when neither is. A plan given both a profile and a `strictness` stores both. Moving the slider outside plan mode clears the stored profile (a custom mix); in plan mode it keeps it.
- **Dates.** Culling tools (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) accept an ISO date (`2026-06-01`), an ISO datetime (`2026-06-01T08:30:00`, or with a space) or the EXIF form (`2026:06:01 08:30:00`). A date-only `date_to` covers the whole day. Day-granular tools (`library_stats`, `possible_faces`, `cull_report` counts and darkroom sets) accept only a date and refuse a time of day as `invalid_input`.
- Rows carry camera, lens, aperture, shutter speed, ISO, focal length and `is_monochrome`. `fields` (on the three search tools) adds any other photo column except image and embedding data, for example `leading_lines_score`. `learned_score` is filled only when sorting by it. When the byte cap trims rows, the result adds `returned` (and `next_offset` or `suggested_per_page`).
- `library_stats` takes `kind` (default `overview`: size, type counts and score overview). The overview's `basis` says what each total counts. `total_photos` counts the photos you can see within `date_from`/`date_to` and the category (all of them when none is given); it ignores the hide toggles and includes rejected photos. `type_counts` applies the hide toggles and ignores date and category. The other kinds are read-only and return the Stats page's data; long lists are cut at 50 entries with `truncated: true`:

| Kind | Data |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | The Stats page panels; they accept `date_from`, `date_to` and `category`. `correlations` also takes `x`, `y` (comma list), `group_by` and `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Category statistics (no parameters) |
| `timeline_dates`, `timeline_months` | Photo counts per day or per month; they need `year` (`timeline_dates` also takes `month`) |
| `timeline_years` | Photo counts per year |

## Control your open tab

Next to the data tools, the server always lists fifteen `ui_*` tools that act on the Facet tab you have open: they move the page, change the filters or the selection, and read back what you see. They never write library data, so a `readonly` token is enough.

| Tool | What it does |
|------|--------------|
| `ui_navigate` | Go to a page (gallery, persons, albums, stats, ...) |
| `ui_set_gallery_filters` | Merge a patch into the gallery filters and sort (`null` removes a filter, `replace: true` starts from none) |
| `ui_get_gallery_view` | Route, active filters, total matches, the first visible photo paths and the selection count; also `album_filter_json` (the filters as a smart album would store them) and `filters_scopable` (whether they describe the whole view) |
| `ui_get_context` | The open page (route), the gallery state (total, loaded count, whether a pinned list is shown), the selection count and the `actions` that apply to your token here; also `focused` (the photo the user is on), `culling` (the assistant's plan on `/culling`: confirmed, pending and changed groups, and the `scope` it was computed for), `culling_defaults` (`{profile, strictness}`: the stored profile and the slider's live, stored strictness, per browser; `auto_cull` uses both when given neither) and `user_activity` (what the user did), and accepts `activity_since` (see below); also `page` and `overlays` (see below) |
| `ui_open_photo` | Open one photo |
| `ui_open_album` | Open one album (fixed or smart) by `album_id`; an unknown or inaccessible id answers `not_found` |
| `ui_show_photos` | Show exactly these `paths` (up to 200) in this order as the gallery's list; unreachable ones come back as `missing`. Any filter change replaces the list |
| `ui_select_photos` | Select explicit `paths`, or the whole filtered view with `select_view: true`, with mode `replace`, `add` or `remove` |
| `ui_clear_selection` | Clear the selection |
| `ui_get_selection` | The `scope` (`paths` or `view`) and `count`, with the `paths`, or for a view the `filters` and `excluded_paths` |
| `ui_next_page` | Load the next page of the gallery |
| `ui_show_culling_group` | Open the darkroom on one group, identified by `(type, group_id)` (edition accounts) |
| `ui_show_culling_plan` | Open the darkroom on an `auto_cull` plan (`plan_digest` and `request` from the preview, optional `focus` group number), with the plan's keepers pre-selected for you to flip and confirm (edition accounts). `auto_cull` calls it for you on a dry run. The same digest as the plan already shown only moves the focus; a different one replaces the plan and is refused as `unsaved_decisions` while you hold decisions you have not confirmed, and as `plan_changed` when the library moved since the preview, and as `plan_load_failed` when the tab could not load the plan for any other reason |
| `ui_suggest_culling` | While a plan is shown on `/culling`, mark photos you would keep or reject (`photos`: `path`, `action`, `reason`, up to 100) and groups you want to comment (`groups`: the `path` of any photo of the group, and a `note`, up to 50); a reason or note is at most 200 characters. You see a badge per photo and a chip per group, and nothing changes unless you click a badge. Calls merge by path, `replace: true` drops everything held first, and `replace` with empty lists clears. Answers `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}`; refusals are `no_plan` (the tab holds no plan), `too_large` (the tab holds at most 300 suggestions and 100 notes: use `replace`) and `forbidden_level` (edition accounts only). With several tabs open, pass the `tab_id` from `shown_in_tab` or `status` |
| `ui_show_comparison` | Open the pairwise comparison page, optionally on one category, strategy and `tab` (`ab`, `snapshots`, `suggestions`, `weights`); it only opens the page, you pick the winners |

How it works:

- **Connection.** While you are signed in and both `viewer.mcp.enabled` and `viewer.mcp.bridge` are true, every Facet tab opens a same-origin WebSocket to `/api/mcp/bridge`, authenticated with your session in its first message. The bridge is on by default. Set `viewer.mcp.bridge` to `false` to turn it off: tabs then do not connect at all, and the `ui_*` tools answer a clear error.
- **Whose tabs.** A tool only reaches the tabs of the token's owner. On a single-password install every session is the same user; on an open install every tab belongs to the shared `_anonymous` user, edition logins included.
- **Tab levels.** Each tab carries the level of the session that opened it. A token only drives tabs at or above its effective level: an `edition` token never uses a viewer-only tab, while a `readonly` token may drive an `edition` tab.
  - Single-password install: a token is also capped by the session that minted it. One minted from a viewer-only session reaches only viewer-level tabs, never the edition tab (a token minted before this rule is capped at its own level).
  - Open install: a token reaches only viewer-level tabs, never an `edition` tab, except the local editing tab below. A Full-editing token minted in an edition-password session reaches an `edition` tab when used from the same computer.
  - Under `viewer.trusted_local_editing` on an open install, a tab that passes the same-machine check registers at `edition`, and drops to `readonly` within one ping when the option is turned off. LAN or forwarded tabs stay `readonly`. A token used from the local machine reaches that tab whatever level it was minted at. A token used from the LAN never does and gets `no_tab`, with a message saying a non-local request cannot steer a local editing tab.
  - A tab can only be replaced by one of equal or higher level: a viewer-only session reusing an edition tab's `tab_id` is refused with 4409. Past the per-user tab cap, the lowest-level tab goes first.
  - `status` lists only the tabs the token can drive, and reports `out_of_reach_tabs`, the number of open tabs it cannot.
- **Several tabs.** The most recently focused one is used, and the result's `tab` field says so. Pass `tab_id` (listed by `status`) to choose another.
- A tab refuses what its account may not do (for example `/culling` for a non-edition account), and the tool returns that refusal.
- What a tab sends back is untrusted: it is bounded in depth, string length and list length, and capped by `max_bytes`.
- Errors: `no_tab` (no tab is connected or open, or the bridge is off: open Facet in a browser and sign in), `tab_timeout` (no answer within `call_timeout_s`) and `tab_outdated` (the open tab does not know the tool; reload the page after upgrading Facet).
- The bridge accepts the WebSocket and then refuses it with a close code, not an HTTP status: 4404 when the endpoint or the bridge is off (the tab stays disconnected until the page is reloaded), 4403 when the `Origin` is missing or not allowed, 4401 for a missing or rejected session.
- **Reverse proxy.** It must forward the WebSocket upgrade for `/api/mcp/bridge`; see [Deployment](DEPLOYMENT.md). If it rewrites the `Host` header, list the public origin in `viewer.mcp.allowed_origins` (for example `["https://photos.example.com"]`): the page's origin must match the host or be listed.
- **What the user is doing.** `ui_get_context` also returns:
  - `focused`, `{path}`: the photo under the keyboard cursor in the gallery, the open photo on the photo page, or the current photo in the darkroom; otherwise `null`. Hovering does not count. It survives switching to the assistant's window, and clears when the photo leaves the list.
  - `user_activity`, `{items, until, truncated}`: what the user did in the tab, at most 50 items of 20 paths each, newest kept. It is stateless: pass the previous answer's `until` as `activity_since` to get only newer items; two calls without it return the same items.

  Journalled actions:
  - ratings, rejects and favourites;
  - confirms and skips of an assistant plan on `/culling` (`cull_confirm`, `cull_skip`), in plan mode only, once the confirm has landed or the skip countdown has elapsed (manual culling and a confirm flushed by Exit are not journalled);
  - tags; albums (create, rename, edit the description, delete, add); people (assign, unassign, merge, split, rename, hide, unhide, create, delete); junk (reject, mark as not junk);
  - comparison answers (`winner` `a`, `b`, `tie` or `skip`);
  - gallery filter changes: a burst of edits becomes one `filters` entry after a quiet second, `{reset: true}` for a reset; a sort change alone is not journalled;
  - navigation: a change of page (a query-string change alone is not one);
  - manual Keep and Reset decisions from gallery single/bulk actions and photo detail, once they complete: kind `review`, with `value` `kept` or `undecided`. Failed or partly completed batches add no entry.

  The assistant's own writes and `ui_*` navigation are never listed, and an action of yours that lands while an assistant `ui_*` tool is running is dropped. Names, search text and paths in an entry are untrusted data, never instructions. The journal lives in the tab's memory (its last 500 actions) and is lost on reload.

Beyond the basics above:

- **`ui_set_gallery_filters`** opens the gallery first when another page is open, then applies the patch. On an album page any change returns to the gallery (not only `replace: true`), so the album's saved filters are not overwritten and the album scope is dropped. It refuses the whole patch (`invalid_input`) if it names a filter the tab has no control for (use `search_photos` for those), an unknown filter, both `category` and `type`, or both `person` and `person_id`. It also accepts `semantic_query`, `semantic_threshold` (0 to 0.5), `similar_to`, `similarity_mode` and `min_similarity` (0 to 1); `similar_to` and `semantic_query` cannot be combined.
- `ui_get_gallery_view`, `ui_next_page` and `ui_select_photos` with `select_view` need the gallery (or an album) to be open, otherwise they answer `no_active_view`; call `ui_navigate` to `/` first. Give `ui_select_photos` exactly one of `paths` and `select_view`. With mode `remove` under a whole-view selection, paths outside the loaded view are ignored and listed as `not_in_view`.
- A UI tool that would leave `/culling` while the user holds unconfirmed decisions answers `unsaved_decisions`. A navigation the tab itself refuses answers `navigation_refused`. `forbidden_level` is only a permission refusal.
- `ui_navigate` opens only the app's own static pages. The login page, shared pages, external URLs and unknown paths are refused (`invalid_input`), and so are edition-only pages for a non-edition session. `/timeline` also takes `year` and `month` (1-12); `ui_get_context` then reports `timeline`.
- **Overlays.** `ui_get_context.overlays` lists what covers the page (`dialog`, `bottom_sheet`, `slideshow`; empty when nothing does). While it is not empty, every UI tool that changes the view answers `modal_open` and does nothing. `ui_get_context`, `ui_get_selection` and `ui_get_gallery_view` still answer, and a search shown with `show` reports `shown_in_tab.reason` `modal_open` (the search itself succeeds). Every dialog counts, shortcuts and edition dialogs included, except the connect-assistant dialog; menus, selects, tooltips and snackbars do not.
- **Page state.** `ui_get_context.page` is `{id, ...state}` on these pages, and `null` on every other page:
  - `/persons` (`persons`: `search`, `sort`, `sort_direction`, `show_hidden`)
  - `/albums` (`albums`: `search`, `sort`, `type`)
  - `/stats` (`stats`: `tab`, `category`, `date_from`, `date_to`)
  - `/map` (`map`: `date_from`, `date_to`)
  - `/timeline` (`timeline`: `date_from`, `date_to`, `sort`)
  - `/scenes` (`scenes`: `album_id`, `total`)
  - `/culling` (`culling`: `mode` (`cull` or `stacks`))
  - `/compare` (`compare`: `tab` (`snapshots`, `ab`, `suggestions`, `weights`, `context` or `panorama`), `category`, `strategy`, `pair_a`, `pair_b`, `pair_loading`). `tab` is `null` until a category is chosen; the pair is `null` while the A/B tab is not shown.

  Values are read live, and free text is cut at 200 characters. An older tab omits `page` and `overlays`.
- The **Connect an assistant** dialog's status line shows whether this tab is connected; `status` lists open tabs and their ids.
- A tab stops reconnecting once its session is rejected (sign in again). It waits until you return to it after another of your tabs took over.

## Live updates

When an assistant changes photos through a write tool, your open Facet tabs follow without a reload.

- **Gallery.** Changed cards update in place, an assistant's pinned list is kept, and a photo removed from the library (`delete_photos`) leaves it. A photo that `cull_apply` moved or trashed keeps its library row, so it stays in a pinned list; views that hide rejected photos (the default) already hide it. A write that cannot name its photos (see below) reloads the view, keeping the current rows and your selection on screen until the new rows arrive. Semantic-search and similar-photo views refresh the photos already shown and never remove one.
- **Photo page.** It refetches its photo; a photo removed from the library takes you back.
- **Darkroom** (`/culling`). It patches reject, favourite and rating in place, shows a Rejected marker and keeps your own decisions. For a change it cannot scope, it reloads only when nothing is at stake; otherwise it shows a Reload banner until you reload.
- **One notice per burst.** Changes are batched (400 ms trailing debounce, 2 s at most) into one "Assistant changed N photos" notice.
- **One entry per assistant call** in the activity panel, labelled with the tool's name in your language (or its raw name if it has no label), counting the photos of the whole call. Above 200 photos the entry names none, so the view reloads and there is no **Show photos** button. After an `auto_cull` apply, **Show photos** pins the photos it rejected (up to 200).
- **Which writes.** Ratings, favourites, rejects, tags, captions, album membership, culls, deletes, sequence and category overrides, face assignments, junk clearing and darkroom confirmations. Reads, dry runs, refused writes, album creation, metadata export and scans do not refresh. A write that times out (`outcome_unknown`) still refreshes, since it may have landed; one still running then shows up on the next refresh or reload.
- **Unscoped writes.** A write targeting a `filters` view, one that includes set siblings, one over 200 photos, or one that names no paths reloads the view instead of refreshing named cards.
- **The bridge must be on.** A write made over `/mcp` reaches your tabs through the tab bridge, so `viewer.mcp.bridge` must be `true`. A write made by the page itself (`POST /api/mcp/call`) uses its response (`changed_paths`) and updates even with the bridge off.
- **Same process only.** With `viewer.py --workers N` the notice can miss a tab (see [Known limitations](#known-limitations)).
- **After an upgrade, reload your open tabs.** The tool list changed, so an open tab answers `tab_outdated` until reloaded.

## In-page WebMCP (browser agents)

Besides the `/mcp` endpoint, a signed-in tab offers the same `ui_*` tools to agents that run inside the browser, through the W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API (`document.modelContext`). A browser-native assistant sees exactly the tools listed above, runs them in the tab you are looking at, and needs no token.

- **Secure context only.** Facet registers the tools only on HTTPS or `localhost`. On plain HTTP they are not offered; the token-based connection keeps working.
- They are registered when `viewer.mcp.enabled` is true and you are signed in, and removed when you sign out.
- The object is `document.modelContext` (the deprecated `navigator.modelContext` alias is not provided). It is a polyfill, installed only when the browser has no native one, and cannot be uninstalled: it can exist before you sign in with no Facet tools, and stays with an empty tool list after you sign out.
- The tools do the same things, bounded by the same account level, as in the table above. A browser agent reads the same `actions` list through `ui_get_context`.
- **Library tools in the page.** The tab also offers the server's own tools (search, ratings, tags, albums, darkroom, reports):
  - `GET /api/mcp/inpage_tools` lists them, with each tool's schema, its `required_level` and the session's current `level`.
  - `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`) runs one as your signed-in session, through the same wrapper as `/mcp`, so levels, previews, `confirm` values and rate limits behave the same. A failed tool is a normal `ok: false` envelope (HTTP 200). A call also reports `changed` (photos written).
- **Level.** The lower of your sign-in's level and your live role, read on every call: a demoted account loses its writes at once and a deleted one is refused (401). Below a tool's floor the answer is `forbidden_level` ("This session's level is readonly; set_rating needs edition: unlock edition in Facet"). On a single-password install, writing needs edition unlocked.
- **Who may call.** Only a signed-in person. An agent's own `/mcp` token is refused on these routes (403), and so is a foreign `Origin`; a cookie alone never authenticates. Every call carries an `X-Facet-Agent-Session` header (1 to 64 letters, digits, `_` or `-`; 400 if missing or malformed). It tells tabs apart, so a `confirm` value issued to one tab is refused in another. The page chooses it, so it separates tabs but does not authenticate.
- **What is left out.** The image tools (`get_thumbnail`, `contact_sheet`) and `available_actions` (use `ui_get_context`). A tool's `show` argument is always off, because the tab is the caller, and `tab_id` is refused. `status` reports only the server and UI-contract versions. `target: "selection"` uses the `selection_snapshot` the page sends (what `ui_get_selection` returned). `create_album` with `target: "view"` needs the `album_filter_json` and `filters_scopable` that `ui_get_gallery_view` returned (`invalid_input` without them). Destructive actions still follow `viewer.mcp.allow_destructive`.
- **Taste.** Like any assistant write, a tool call from the page never records comparisons and never arms the retrain.
- **Switch.** `viewer.mcp.inpage_tools` (default `true`) turns both routes off (404) and clears `features.mcp_inpage` in `/api/auth/status`. `viewer.mcp.enabled: false` turns them off too.

## Changing things

Write tools are in the same `/mcp` list as the read tools. Each goes through the viewer's own `/api` routes, so the routes' checks still apply, and each counts against the `write_rate_per_min` budget. The level is the lowest effective level that may call the tool (see [Permission levels](#permission-levels)).

| Tool | Level | What it does | Caps |
|------|-------|--------------|------|
| `set_rating` | `user` | Set the star rating (0-5) of photos | 50 paths |
| `set_favorite` | `user` | Mark or unmark photos as favourite (marking clears rejected) | 50 paths |
| `set_rejected` | `user` | Reject or un-reject photos (rejecting clears rating and favourite) | 50 paths |
| `batch_set_rating` | `edition` | Set the rating of many photos | 1000 paths, or `filters` |
| `batch_set_favorite` | `edition` | Mark many photos as favourite | 1000 paths, or `filters` |
| `batch_set_rejected` | `edition` | Reject many photos | 1000 paths, or `filters` |
| `add_tags` | `edition` | Add manual tags (kept apart from the AI tags) | 10 tags; 1000 paths, or `filters` |
| `remove_tags` | `edition` | Remove manual tags | 10 tags; 1000 paths, or `filters` |
| `create_photo_stack` | `edition` | Create an explicit local stack; returns Undo entry | 2–1000 paths |
| `update_photo_stack` | `edition` | Replace explicit members/order and optional cover; stale revision refuses | 1000 paths |
| `unstack_photos` | `edition` | Dissolve a stack; originals stay intact |  |
| `undo_photo_stack` | `edition` | Undo an available stack entry only; later changes refuse |  |
| `create_album` | `edition` | Create an album (not idempotent: twice makes two albums): empty, or from `filters` / `target: "view"` as a smart album that follows those filters, or from `paths` / `target: "selection"` as a fixed album filled in the same call (`added`, `skipped`). Smart albums show the viewer's own hide toggles and read 0 photos in `list_albums`. `filters` that hold no effective filter (`{}`, or only display toggles set to off) are refused as `invalid_input`: omit `filters` for an empty album | |
| `album_add_photos` | `edition` | Add photos to an album (already present ones are ignored) | 1000 paths |
| `album_remove_photos` | `edition` | Remove photos from an album; the photos are untouched | 1000 paths |
| `assign_faces` | `edition` | Move faces to a person; faces another person owns are left alone unless `allow_reassign` is set, and the result lists what was skipped | 50 face ids |
| `set_caption` | `edition` | Set a photo's caption (set semantics; an unchanged caption comes back as `already`) | 1 photo, 2000 characters |
| `export_metadata` | `edition` | Write XMP sidecars next to the files | 100 paths, or `filters`, or `target` |
| `junk_list` | `readonly` | List junk-sweep candidates, optionally of one `kind`; `show: true` opens `/junk` on that kind | 100 per page |
| `junk_reject` | `edition` | Reject junk-sweep candidates (same as `batch_set_rejected`) | 1000 paths, or `target: "selection"` (gallery page only) |
| `junk_clear` | `edition` | Keep candidates: mark them evaluated-clean so they leave the queue | 50 paths |
| `cull_apply` | `edition` | Copy the keepers, or move or trash the rejects ([preview then confirm](#destructive-actions-preview-then-confirm)) | 10000 paths, or `filters` |
| `delete_photos` | `edition` | Trash the files and delete their library rows ([preview then confirm](#destructive-actions-preview-then-confirm)) | 1000 paths |

### Local manual stacks

- `get_photo_stack(path)` reads the caller's local stack, or null. With partial visibility it returns only permitted members, and the stack is read-only.
- `create_photo_stack(paths, cover_path)` needs 2–1000 explicit unstacked photos.
- `update_photo_stack(stack_id, paths, expected_revision, cover_path?)` replaces membership and order; 0 or 1 members dissolve the group.
- `unstack_photos(stack_id, expected_revision)` dissolves it.
- These three need `edition`, plus the UUID and current revision for existing stacks. Never retry a create blindly.
- Successful changes return `undo.entry_id`. `undo_photo_stack(entry_id)` (edition only) checks that the entry is a stack entry, and refuses after later edits or loss of visibility.
- Paths are at most 4096 characters. No files, review decisions or remote Immich state change; global credentials stay CLI-only.
- `stack_truncated: true` on a large successful change means the stack is returned only as a UUID/revision/member_count summary, not a complete editable member list. `undo.entry_id` is still available.

`search_photos` and gallery context separate `total` (displayed items) from `photo_total` (matching originals). Use `photo_total` for a filter write's `expected_count`. Whole-view selections and `target:view` include folded matching members, so show the real photo count and the whole-view scope before applying. Selecting one collapsed tile selects only its displayed photo. `user_activity` includes `stack` create/update/unstack/undo. `stack_id`/`collapse_stacks` are server-only, not tab-filter keys.

- **The `user` tools need an edition token on a single-password install**, which has no middle level (see [Permission levels](#permission-levels)).
- **Set semantics.** The per-photo tools write only a difference from the current state, so repeating a call is harmless; each path reports `changed` or `already`. They run one path at a time and stop at the first `library_busy`, `outcome_unknown` or `forbidden_level`, reporting `affected`, the per-path `results` and `not_attempted`. The batch tools set the same state.
- **Choosing the photos.** The batch, tag and `cull_apply` tools take EITHER `paths` OR `filters` (the `search_photos` filter object), plus an optional `exclude` list.
  - A `filters` target needs `expected_count`: the filters' match count before `exclude` (`search_photos` `photo_total`). Facet counts again first and writes nothing if the numbers differ (`invalid_input`, with `actual_count`).
  - The viewer's default hide toggles (including rejected photos) apply to `filters` exactly as in `search_photos`. So for `move_rejects` and `trash_rejects`, pass `show_rejected` (or `hide_rejected: false`) to BOTH `search_photos` and `cull_apply`. `copy_keeps` needs nothing extra.
- **Whose state.** Ratings, favourites and rejections are the token owner's own.
- **Skipped files.** A non-empty `skipped` list from `cull_apply` or `delete_photos` comes with a `skipped_reason`: those paths have no readable file on disk (missing, moved, or outside the scan directories), and nothing was done for them.
- **The photos the user selected.** Where a tool takes `paths`, `target: "selection"` uses the open tab's selection instead (`tab_id` picks the tab).
  - A selection that changed between preview and confirm answers `invalid_input` with `selection_changed`; one too big for the tab's reply answers `too_large`. `delete_photos` re-reads the selection on confirm.
  - `get_photo`, `get_thumbnail` (exactly one selected photo) and `contact_sheet` (at most 16) also take `target: "selection"`, from any page.
  - `junk_reject` takes it only on the gallery page (`invalid_input` otherwise).
- **Captions and exports.** `set_caption` stores the text only. It is not re-embedded, so semantic caption search matches the old text until a re-embed. The incremental viewer-database export keeps an existing caption when the source one is empty, so a cleared caption may come back after a later export or scan. `export_metadata` waits up to 180 seconds, reports `written`, `skipped` and `errors` (the first error text in `first_error`), and refuses to write with exiftool 13.23 to 13.27.
- **Faces.** `assign_faces` skips and lists faces that are missing, already on that person, owned by another person (unless `allow_reassign`), on another embedding model or on a hidden person. `assigned_count` is what actually moved.

### Destructive actions: preview then confirm

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) and `delete_photos` are flagged `destructiveHint` and do a dry run unless called with `dry_run: false`.

1. The dry run changes nothing and lists the files it would copy, move or trash (long lists are cut to `max_rows`, with a `<key>_count`). For `move_rejects`, `trash_rejects` and `delete_photos` it also returns a `confirm` value, single use and valid for `confirm_expires_in_s` (5 minutes).
2. The real call (`dry_run: false`) must pass that `confirm`. Facet re-resolves the files and options; if anything changed, the call answers `confirmation_required`: dry-run again.
3. `copy_keeps` needs no `confirm`, since it only writes copies. It still previews by default.

The `confirm` value is bound to the token, the action and the exact file set and options. It is held in one process's memory, so a restart discards every pending value.

**Recommended practice:** always show the user the dry-run summary (counts and file list) and get explicit approval before the `dry_run: false` call. Never confirm on your own initiative.

- `move_rejects` and `trash_rejects` act only on photos the owner rejected; others are reported as `excluded_by_state`. Companion RAW and `.xmp` files (`include_companions`) and the other frames of a bracket or panorama (`include_sequence_siblings`) are untouched unless you opt in.
- **Prerequisites.** `trash_rejects` and `delete_photos` need `viewer.cull.allow_trash` set to `true` (default `false`). The `target_dir` of `copy_keeps` and `move_rejects` must be under an allowed export location: `viewer.export.allowed_target_dirs` plus your scan directories (see [Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations)).

> **Warning:** `delete_photos` sends the files to the OS trash and **deletes their library rows**. Scores, tags and ratings cannot be recovered, even if the files are.

## Corrections and reference data

- **Corrections** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` or `suppress`; at least 2 paths except for `suppress`) and `clear_sequence_override` record a correction applied at the next detection pass (the result reports `pending`). `override_category` and `clear_category_override` set or clear a sticky category that survives rescans and keeps the scoring context.
- **Comparing frames** (`readonly`). `group_compare` compares the frames of one culling group (up to 12 paths) `by: "faces"` (per frame: face count, blinks, worst eyes-open, best smile, `best_path_by_eyes`) or `by: "subjects"` (subject sharpness and prominence, `sharpest_path`). It is advice, not a decision.
- **Cull report.** `cull_report` summarises a scope in one call: total, kept, rejected, favourites, rated, unreviewed, what the hide toggles would hide, junk, low scores, the top keepers and, with an edition token, the first darkroom sets. Reasons overlap. Its `basis` states which filters each count honours (counts ignore the hide toggles).
- **Taste.** `comparison_status` (`edition`) reports how many pairwise comparisons you have made and how well they cover the library. No tool submits, edits or deletes a comparison: each answer is your own click. Assistant writes (ratings, rejections, darkroom confirms, `auto_cull`) never record comparisons and never arm the automatic retrain; the same action made by you in the gallery still does. Ratings, favourites and rejections written by an assistant are also left out of the personal ranker's training pairs, until you rate that photo yourself.
- **Scans.** `start_scan` and `scan_status` (`edition`) start and follow a scan of the configured directories. They are listed only when `viewer.features.show_scan_button` is on and the install is locked (a superadmin key in multi-user mode), or to a Full-editing local token under `viewer.trusted_local_editing`, which does not need `show_scan_button`. Scans are additive and refused while another job runs (`conflict`). Immich sync stays on the command line. On an open install with `viewer.edition_password`, a local Full-editing token minted in an edition session gets them too, but only with `show_scan_button` on.
- **Resources.** The server also lists five read-only `facet://` resources: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (every search filter with its value domain, plus the metric ranges) and `facet://scoring-contexts`. Each shows the library as the key's owner sees it, capped at 200 rows and 32 KiB (`truncated` says so). A sixth, `facet://scoring-weights` (every category's non-zero weights), is offered to `edition` keys only.
- **Choosing what is listed.** `viewer.mcp.tool_profile` is `full` (default) or `core`. `core` lists only an 11-tool set for small models (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`); it changes the listing only, never what a key may call. `viewer.mcp.allow_destructive` (default `false`) gates `delete_photos` (not listed when off), the `move_rejects` and `trash_rejects` actions of `cull_apply`, and `assign_faces` with `allow_reassign`; refused calls answer `feature_disabled`. Tools above a token's level are not listed either.
- **Two more error codes.** `feature_disabled`: a configuration key switches the route off, and the message names it. `conflict`: the library is busy with a job that excludes this one (for example a scan already running).

## Scoring and weights

Assistants can read the scoring weights and dry-run a change. Four tools write: `apply_weights` and `restore_weight_snapshot` change the config, `recompute_scores` rewrites scores and `override_categories` pins photos. Each needs the `edition` level and a two-step `confirm` from a dry run or preview. The reads change nothing.

- **Explaining a score** (`readonly`). `explain_score` (`path`, or `target: "selection"` for exactly one selected photo; `top_n` 1-12, default 5) explains one photo's score: its category and why no higher-priority category took it, the stored aggregate, the top metrics as `{metric_key, value, weight_percent, contribution}`, the rest as a count and a sum, strengths, weaknesses and penalties.
  - It is rule-based and read-only; it never runs the VLM.
  - `weight_percent` is the effective weight the scorer used. It can differ from the configured `*_percent`: `quality` is folded into `aesthetic`, and metrics this install does not run are renormalised away.
  - It needs `viewer.features.show_critique` (on by default). When that is off, the tool is not listed and `status` names it under `hidden_tools.disabled`.
- **Reading the weights** (`edition`). `category_weights` returns one category's non-zero weights, modifiers, filters and priority, or every category's non-zero weights and bonus. The `facet://scoring-weights` resource carries the same list. For one category it also returns `configured_keys`: the `*_percent` keys the category's configuration actually holds (explicit zeros included).
- **Previewing a change** (`edition`). `preview_weights(category, weights | deltas, sample)` re-scores up to `sample` photos of the category (default 30, at most 100) under the current and the proposed weights, both normalised the way the scorer does. Give `weights` (a partial map merged over the current values) or `deltas` (signed percentage points).
  - It reports the rank changes first, then the mean shift, `warnings` and a single-use `preview_digest` (valid 5 minutes, held by one process).
  - It is approximate (`basis: "approximate"`): no percentile snapshot, no penalties, scores capped at 10. It uses stored metrics only and stores nothing.
  - Only the server's own rule is enforced (each weight 0 to 100), plus a refusal when all weights sum to 0 (`all_weights_zero`). A sum outside 95 to 105 (which the config loader rescales) and an unknown key (stored as typed, dropped by a validating load) come back as `warnings`, not refusals.
  - `bonus` and the modifiers cannot be edited through the assistant.
  - A category with more than 100 photos is sampled from its best and worst 100 by aggregate only (`sample_scope`).
  - The digest is not consent: show the user the proposal, the shift and `basis_note` first.
- **Applying a change** (`edition`). `apply_weights(category, weights | deltas, preview_digest)` writes a previewed change. Repeat the SAME `weights` or `deltas` you gave `preview_weights` and pass its `preview_digest`. Without the digest of this exact proposal over the current weights, the call answers `confirmation_required` and writes nothing. The digest is single-use, bound to the token that previewed, and void once the weights change.
  - The write goes through the same route as the web UI: the previous weights are snapshotted first (`auto:edit`), and the result names that `snapshot`. The result is read back (`verified`).
  - It re-scores nothing: the answer says `scores_stale: true` and `next: "recompute_scores"`. Stored scores, ranks and the gallery change only after that job.
  - Known limitation: an already open /compare page holds the old weights and would post them back on its next edit, so the answer carries `reload_compare: true` and the assistant tells the user to reload it.
- **Snapshots** (`edition`). `list_weight_snapshots(category, limit, offset)` lists the saved snapshots, newest first, with their non-zero weights and a `restorable` flag. `restore_weight_snapshot(snapshot_id)` is a dry run by default: it lists the change and returns a single-use `confirm`. The real run (`dry_run: false` plus that `confirm`) answers `confirmation_required` if the weights changed meanwhile. Before overwriting, it snapshots the current weights as `auto:pre_restore` (`undo_snapshot_id`), so a restore can itself be restored. A snapshot the web UI saved in another format (bare metric names instead of `*_percent` keys) answers `unsupported_snapshot` on both runs: restore it from /compare.
- **Recomputing** (`edition`). A weight change re-scores nothing until `recompute_scores(category | all: true)` runs. It starts the background job at once (ask the user first) and returns `started_at`. `recompute_status(started_at)` then reports `running`, `succeeded`, `failed`, `busy` (another process holds the library lock) or `idle`; `matches_started_job` says whether the status is about the job that was started.
  - One job runs at a time (`conflict`).
  - A category recompute rewrites only that category and does not refresh burst or sequence groups (`all` does). Either run saves the percentile snapshot that every category's next normalisation reads.
  - The status is held in one process: with several workers, a poll can reach one that knows nothing about the job.
- **What the user's comparisons favour** (`edition`). `learned_weights(category, with_confidence)` runs the optimizer on the user's own A/B comparisons and returns only the non-zero `changes` and a `proposal` to pass to `preview_weights`; nothing is stored. Instead of inventing a suggestion it answers `available: false` with a `reason` (`not_enough_comparisons`, `unavailable_if_external` when the learning backend is external, `optimizer_unavailable`). When the optimizer found no improvement, it tells the assistant not to propose a change.
- **Fixing categories** (`edition`). `misassigned_categories(category, limit, scan)` lists photos of a category that may belong elsewhere, among the best-scored `scan` photos. It is a heuristic (`confidence_basis: "heuristic"`), not proof, writes nothing, skips photos with a manual category, and is hidden with `show_critique`.
  - `stale`: the current configuration puts the photo in another category. Fix it with `recompute_scores`, not an override.
  - `near_miss`: it missed a higher-priority category's first failing numeric bound by under 10%.
- **Pinning categories** (`edition`). `override_categories(category, paths, dry_run, confirm, expected_count)` pins up to 50 photos.
  - The dry run lists who would change (`would_change`, `already`, `missing`) and returns a single-use `confirm`.
  - The real run needs it plus an `expected_count` equal to `would_pin`. Photos already in the category are pinned too, so the pin survives a later recompute. It stops at the first failure and reports `affected`, `remaining` and `failed_path`.
  - Each pin is sticky and recomputes that photo's aggregate; `clear_category_override` undoes one.
- `ui_show_comparison` takes a `tab` (`ab`, `snapshots`, `suggestions`, `weights`) so the assistant can open the page where the user reviews a change.

## Prompts

The server also offers five ready-made prompts, listed by `prompts/list` and filtered by the token's level. A prompt only names tools the token can call, and a destructive tool only behind its dry run and confirmation. Each call counts against the read rate limit and is logged by name, never with its arguments.

| Prompt | Arguments | What it asks the assistant to do |
|--------|-----------|-----------------------------------|
| `find_photo` | `description` | Find a photo from a description and show it |
| `cull_shoot` | `scope_hint` | Review a shoot, propose what to reject and, once you decide, record your decisions with `confirm_culling_groups`; moving or trashing happens only after a dry run and your confirmation |
| `build_album` | `theme`, `album_name` | Collect matching photos into a new album |
| `tag_people` | `person` | Find faces that look like a person and assign the ones you confirm |
| `teach_taste` | `category` | Open the pairwise comparison page in your tab and track how many comparisons you have made; the answer to each pair is always your own click |

## Darkroom (culling groups)

The darkroom tools mirror the `/culling` page. All of them need the `edition` level, including the listing ones.

| Tool | What it does |
|------|--------------|
| `list_culling_groups` | List groups (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) with their photos and scores, sortable and scoped by album or date window |
| `culling_profiles` | The genre-aware culling presets and the default one |
| `suggest_culling_profile` | Name the preset that fits an album or a capture-time window |
| `keeper_hints` | Per-photo "a better shot exists in this burst" hints for up to 100 paths (empty when no keeper head is trained) |
| `auto_cull` | Auto-cull a scope under a keeper budget: preview the plan page by page, then apply it with the `confirm` value |
| `confirm_culling_groups` | Confirm up to 20 groups: keep their `keep_paths`, reject the rest of their `paths` |

- **A group is identified by the pair `(type, group_id)`**, never by `group_id` alone: similar-group ids are offset when merged with bursts.
- **The default `group_by: "all"` returns bursts plus similar groups only.** Ask for `scene`, `bracket`, `panorama` or `hdr_panorama` explicitly.
- **A page is trimmed to fit `max_bytes` by shortening each group's `photos` list, never by dropping groups.** `photo_count` stays the true size, `photos_truncated` marks a cut list, and `has_more` says whether another page follows.
- **Brackets, panoramas and HDR panoramas are kept whole.** In `confirm_culling_groups`, `keep_paths` must equal `paths` for these types (otherwise `invalid_input`), and `auto_cull` never splits them.
- **Empty `keep_paths` rejects every frame of the group.** The first call then answers `confirmation_required` with a `confirm` value: show the user, then repeat the call with it. If a batch stops on `forbidden_level`, `library_busy` or `rate_limited`, the groups already done are reported.
- **`auto_cull` previews by default.** It returns the keep/reject split per group, plus a `confirm` value when something is left to reject.
  - Every call plans the whole scope and returns it in pages of whole groups. The route pages at 200 photos, a single larger group gets its own page, and the tool may return fewer groups to fit the result size.
  - Repeat the call with `cursor` set to the previous `next_cursor`, and `plan_digest` set to the cursor-0 page's `plan_digest` (required when `cursor` > 0), until `next_cursor` is `null`. If the plan changed since the first page, the call answers `confirmation_required`: restart from cursor 0.
  - Each row carries its plan-wide `number`; `kept` and `rejected` cover the full plan.
  - Cull a whole date range in ONE call, never month by month.
- **One `confirm` covers the full plan** (valid 300 s, single use, issued on the cursor-0 page only). The apply recomputes the plan and answers `confirmation_required` if it changed since the preview. It returns counts only (`groups_processed`, `kept`, `rejected`, `highlights_added`). Rejections made by an assistant never feed the personal ranker, unlike the same cull made by you in the gallery.
- **Overrides.** `keep_paths` and `remove_paths` (up to 1000 each) override single frames of the plan. Pass the same overrides on the dry run that issues the `confirm` and on the apply.
  - Paths not in the plan are ignored and reported as `ignored_overrides` (the first 20, with `ignored_overrides_count`).
  - Refused as `invalid_input`, naming the paths or groups: removing a frame the plan KEEPS in a bracket, panorama or HDR panorama set; leaving a group without a keeper; listing a path in both lists.
  - Removing a frame the plan already rejects does nothing.
  - The set rule only covers groups made entirely of one set kind. A group mixing ordinary frames with set frames is not kept whole, so its frames can be overridden like those of any burst.
- **The apply never reads the user's flips from the tab.** To honour them, read `ui_get_context.culling.changed` and pass those groups' `keep_paths` / `reject_paths` as `keep_paths` / `remove_paths` on the next dry run and on its apply (the same lists on both). A group the user confirmed in the tab leaves the plan: the plan digest moves, a pending `confirm` answers `confirmation_required`, and the new preview no longer contains that group. Never re-decide it.
- **If the user changes something between preview and apply.** The apply is checked against the preview.
  - A photo whose rating, favourite or reject state the user changed since the preview is left out and reported as `skipped_user_changed` (the first 50 paths, with `skipped_user_changed_count`). A group left without a keeper is skipped whole and counted in `skipped_user_changed_groups`.
  - This per-photo skip applies only when neither `keep_paths` nor `remove_paths` is given. With explicit lists, the apply re-runs the dry run and refuses any plan change, a manual reject included.
  - A rating, favourite or reject written by anyone between preview and apply counts as a change, the assistant's own writes included. A plan change not explained by such photos is still refused as `confirmation_required`.
  - When the server no longer holds the preview (older than 15 minutes, evicted, or held by another process), or the plan has more than 12000 photos in all pages, the answer says `state_guard: "unavailable"` and the all-or-nothing refusal applies.
  - The guard covers assistant requests only; the command line `--auto-cull` is unchanged.
- **`scope_dependent_kinds`** names the group kinds whose membership depends on the date range or the candidate pool (`similar`, `scene`, plus `bracket` when `trim_brackets` is on), with a note to cull the whole range in one call. Bursts and panoramas do not change with the range, and neither do brackets unless `trim_brackets` is on.
- **`show`** (default `true`, with `tab_id`). On a dry run the plan opens on the user's `/culling` page through `ui_show_culling_plan` (see Plan mode on `/culling` above).
  - The result carries `shown_in_tab`: `{"applied": true, ...}`, or `applied: false` with the reasons of a failed search show plus `unsaved_decisions` (the user holds unconfirmed decisions on the page), `stack_mode_active` (the page is in Suggested stacks mode), `plan_changed` (the library moved since the preview), `too_large` (the overrides are too big to send to the tab) and `plan_load_failed` (any other load failure).
  - Only the first page (`cursor` 0) loads the plan; a page with `cursor` > 0 only moves the tab's focus to its first group.
  - A failed show never fails the call. An apply never shows.
  - An apply's live update (and, in-page, the `/api/mcp/call` response's `show_paths`) carries the photos it rejected, up to 200, for the activity entry's **Show photos**; the tool result stays counts only. An apply that rejected nothing offers no **Show photos**, and a dry run emits no live update.
- **Knobs from the tab.** Given neither `strictness` nor `profile`, `auto_cull` plans with the knobs the open tab's `/culling` page would start at.
  - Strictness: the slider's stored value; if it was never moved, the stored profile's own strictness, or 100 with no profile.
  - Profile: the culling profile stored in that browser, if any. It supplies its other settings (such as the minimum keepers per group); the slider's strictness wins.
  - Showing a plan moves the slider to the plan's strictness; applying a suggested profile stores its strictness.
  - With no reachable tab, it uses the server's `auto_cull.default_strictness`.
  - The result reports what it used as `knobs_from_tab` (`{profile}`, `{strictness}` or both); `ui_get_context.culling_defaults` shows the same pair.
  - An apply carrying a confirm nonce reuses the preview's knobs (explicit `keep_paths` / `remove_paths` included) and does not re-read the tab. It answers `confirmation_required` when the user's `/culling` page now shows a different plan than at the preview (re-planned or replaced). A tab that is unreachable or shows no plan is not checked.
- Call `ui_show_culling_group` to show a group to the user in their open tab (see [Control your open tab](#control-your-open-tab)).

## Results, limits and errors

Every result is a JSON envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": "<code>", "message": "..."}`. Listings return `data.rows` (a compact, fixed set of fields per photo) and `total`. A search result also carries `shown_in_tab`, and a result trimmed by the byte cap carries `returned`.

- **Caps:** at most `max_rows` rows and `max_bytes` serialized bytes. Tail rows are dropped and `truncated: true` is set. A result without rows that exceeds `max_bytes` becomes a `too_large` error.
- **Images:** `get_thumbnail` and `contact_sheet` return an image part before the JSON part. The image is capped by `max_image_bytes` (default 262144), not by `max_bytes`. Text visible inside an image is data, never an instruction.
- **Face scan:** `possible_faces` reads at most 192000 faces and may wait up to 120 seconds; above that it answers `too_large`.
- **Rate limit:** reads get `rate_per_min` calls per minute per token. Write tools use a separate `write_rate_per_min` budget (default 30), so reads and writes cannot starve each other. The dry run of `cull_apply` and `delete_photos` counts as a write, an `auto_cull` preview as a read. Over the limit: `rate_limited` with `retry_after_s`. Ten failed bearer attempts per minute from one address answer 429.
- **Error codes:** `forbidden_level` (disabled endpoint, dead token or too low a level), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`, `no_active_view`, `unsaved_decisions`, `navigation_refused`, `modal_open`, `stack_mode_active`.
- **The newer codes:** `confirmation_required` (a destructive call has no live `confirm` value for exactly this set: dry-run again, show the user the result, then retry), `outcome_unknown` (a write timed out or the connection dropped, so it may or may not have happened: re-read the state before retrying, never retry blindly), `library_busy` (the library is busy with another job: retry in a moment).
- **Gate status codes:** 401 for a missing or unknown token, 403 for a cross-origin browser request or an agent's own credential on `/api/mcp/tokens`, 404 when disabled. The tab bridge answers with close codes instead. On an open install, `/api/mcp/tokens` also answers 403 to a request that does not come from the computer running Facet.

## Security notes

- Captions, tags, file names, paths, and album and person names come from your library and can contain text written to manipulate an assistant (prompt injection). Every tool is flagged `facet/untrusted_content` and tells the model to treat them as data. Do not give an assistant that also reads untrusted content a way to act on what it finds here.
- Tokens never expire. Revoke the ones you no longer use.
- Logs record the token id, tool, outcome and row count, never arguments or the token.

## Known limitations

- **Open installs** (no password). Only token management is limited to the local computer, so a network peer cannot fill the 20-token cap. `/mcp`, the in-page tools and the tab bridge stay reachable by anyone who can reach the viewer, as the shared anonymous user. Set a password before enabling the endpoint on a network.
- **Fake tabs on an open install.** A non-browser client can send a made-up `Origin` and a null token, register a focused `_anonymous` tab, answer `ui_*` calls with data of its choosing, and evict real tabs through the 8-tab cap. Under `viewer.trusted_local_editing`, a local process can also register a fake `edition` tab (it can forge `Host` and `Origin` on the WebSocket), but it could already act as the browser. A LAN client cannot, since a loopback peer is required.
- Rate limits and failed-authentication counters live in memory in each process; with `viewer.py --workers N` each worker counts separately.
- The tab registry lives in memory in one process. Use a single worker (`viewer.py --workers 1`, the default) when you rely on `ui_*` tools; with several workers a call can reach a process that does not know your tab and answers `no_tab`.
- A user can have at most 8 tabs connected; opening a ninth closes the oldest.
- Nothing is pushed from the tab to an external assistant: it learns about the user's plan progress and activity only by calling `ui_get_context`. The `auto_cull` apply does not read the tab.
- The `auto_cull` state guard keeps 8 plans per user for 15 minutes. The preview memory is separate: 300 seconds, 64 entries across all users. Both live in one process's memory; with several workers an apply can reach a process that holds neither, and the answer then says `state_guard: "unavailable"`.
