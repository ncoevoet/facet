# Immich Integration

> 🌐 **English** · [Français](fr/IMMICH.md) · [Deutsch](de/IMMICH.md) · [Italiano](it/IMMICH.md) · [Español](es/IMMICH.md) · [Português](pt/IMMICH.md) · [简体中文](zh/IMMICH.md)

[Immich](https://immich.app/) stores, backs up and serves your photos. Facet scores, ranks and culls them. This page connects the two:

- Facet's ratings and favorites show up in Immich.
- An upload to Immich tells Facet there is new work waiting.

Both directions use Immich's REST API only. Neither tool touches the other's database.

**Facet requires Immich ≥ 3.0.** Facet clears a rating with `null` and marks a rejection with `-1`. A 2.x server refuses the clear, so stale ratings stay on your assets.

---

## Table of contents

- [How the two see the same file](#how-the-two-see-the-same-file)
- [Step 1 — share the library with Immich](#step-1--share-the-library-with-immich)
- [Step 2 — create an API key](#step-2--create-an-api-key)
- [Step 3 — map the paths](#step-3--map-the-paths)
- [Step 4 — test, then push](#step-4--test-then-push)
- [Pushing rejections](#pushing-rejections)
- [Manual stack import and push](#manual-stack-import-and-push)
- [The inbound webhook](#the-inbound-webhook)
- [Diagnostics in the viewer](#diagnostics-in-the-viewer)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## How the two see the same file

Facet and Immich see the same file on disk under different paths:

- **Facet** uses the absolute path on the machine that runs the scan, e.g. `/mnt/photos/2026/07/IMG_1234.jpg`.
- **Immich** uses its `originalPath`: the path as seen from *inside the Immich container*. That is often `/usr/src/app/upload/…` for uploads, or the mount point of an external library.

You tell Facet the prefix rewrite once, in `immich.path_map`. Every lookup goes through it. If it is wrong, everything reports "unmatched" — see [Troubleshooting](#troubleshooting).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

The map works both ways. `--immich-sync` uses it to find the Immich asset for a Facet path. The webhook uses it to find the Facet photo for an Immich `originalPath`.

## Step 1 — share the library with Immich

The simplest setup is an Immich **external library**: Immich reads the photos where they already are, and Facet scans the same directory.

1. In Immich, go to **Administration → External Libraries → Create Library**, pick the owner, and add an import path for the directory as the Immich container sees it.
2. Bind-mount that directory read-only into the Immich container. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scan the library in Immich (**Scan All Libraries**), and scan the same directory with Facet:

   ```bash
   python facet.py /mnt/photos
   ```

No file is duplicated on disk.

You can also upload to Immich as usual (mobile backup, web uploader) and point Facet at Immich's upload directory. Only the prefixes change. Re-run the Facet scan after uploads, or use `--watch`.

## Step 2 — create an API key

In Immich: **click your avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 lets you limit a key to some scopes. Rating and favorite sync need these (manual stacks need more, see below):

| Scope | What Facet does with it |
|-------|-------------------------|
| `server.about` | `--immich-test` connectivity/auth check |
| `asset.read` | Resolve assets by `originalPath` |
| `asset.update` | Write `rating` and `isFavorite` |
| `album.read` | Find an existing top-picks album by name |
| `album.create` | Create the top-picks album the first time |
| `albumAsset.create` | Add photos to the top-picks album |

You can skip the three album scopes if `push.top_picks_album` is empty. Facet only touches albums when that name is set.

Facet sends the key in an `x-api-key` header. Put it in `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Note:** Facet writes ratings with `PUT /api/assets`. Immich marks it deprecated, but its replacement is not published yet, so Facet keeps using it.

## Step 3 — map the paths

Add one pair per shared root. Rules:

- The first matching prefix wins. It is a plain string match, not a directory match.
- End directory prefixes with `/`.
- Put narrow mappings before broad ones.

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Two roots, two pairs:

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

The shipped placeholder (`{"facet_prefix": "", "immich_prefix": ""}`) passes paths through unchanged. That only works if Facet and Immich see identical absolute paths, which is rare unless Facet runs inside the Immich container.

To find the real value, open a photo in Immich and press `i` for the info panel. Compare its file path with the path Facet shows for the same photo.

## Step 4 — test, then push

```bash
# Connectivity + authentication only. No writes.
python facet.py --immich-test

# Resolve every asset and report what WOULD change. Still no writes.
python facet.py --immich-sync --dry-run

# For real.
python facet.py --immich-sync
```

The sync reports `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / albums created. In a dry run, `updated` counts the assets that would change, and nothing is written. A large `unmatched` count on the first run almost always means the path map is wrong — see [Troubleshooting](#troubleshooting).

What gets pushed:

- **Star ratings 1–5** → Immich's `rating`. An unrated photo pushes nothing.
- **Favorites** → Immich's `isFavorite`.
- **Clears.** If you rated a photo, synced, then reset it to unrated, the next sync sends `rating: null` so Immich clears it too. Facet remembers what it last pushed (in `stats_cache`) for this. It sends `null`, never `0`: Immich v3 rejects `0`, and one rejected batch aborts the whole sync.
- **A top-picks album** (optional), filled with photos rated at least `push.top_picks_min_rating`, when `push.top_picks_album` is set.

In multi-user mode, `--immich-sync --user alice` pushes Alice's own ratings (`user_preferences`) instead of the global ones, and tracks her sync state separately.

## Pushing rejections

Off by default. When on, a photo you reject in Facet's culling view gets Immich's rejected marker:

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

With `push.rejected` on:

- A rejected photo pushes `rating: -1`, Immich v3's "rejected" value.
- **Rejection outranks stars.** A rejected 5-star photo pushes `-1`, not `5`.
- **Un-rejecting clears it.** The photo then pushes its current star rating, or `rating: null` if it has none.
- A rejected photo never joins the top-picks album.
- `push.ratings: false` also turns this off, since `-1` is a rating.

Leave it off if other people (or your phone) browse the Immich library: they will see the `-1`.

## Manual stack import and push

Manual stacks have their own **local CLI plan/apply** workflow, using the usual `--config`, `--db` and `--user` options. Rating and favorite sync is unaffected.

Requirements:

- Immich **≥ 3.0** (Facet also checks stack support at runtime).
- Key permissions: `user.read` and `stack.read` on top of `asset.read`; push also needs `stack.create` and `asset.update`. `stack.update` and `stack.delete` are not needed.
- Multi-user installations must name an existing user.
- The Immich key is never used by stack operations from the web viewer, assistants (MCP) or the upload webhook.

Workflow:

1. Preview. It is read-only on both sides and does not migrate the database.
2. Review the plan and its SHA-256 digest.
3. Apply explicitly.

Options and limits:

- `--stack-id UUID` (repeatable) limits the run to those source stacks.
- `--stack-plan-out` writes a new private JSON file (POSIX mode `0600`) and refuses to overwrite.
- A plan holds at most **1000 groups, 1000 members per group, 20000 total members and 16 MiB**. Use `--stack-id` to narrow it.
- On Windows, pick an output directory whose ACL restricts access to your account; POSIX mode bits do not protect the file there.

Matching rules:

- Every member must map to exactly one indexed, visible, online photo owned by the remote account. One missing or ambiguous member skips the whole group.
- Push only creates a stack from remote assets that are not stacked yet.
- An exact match on members and cover links the two stacks on apply.
- Partial overlaps, different covers, changed membership and unstacked-on-one-side cases are skipped as conflicts. Existing stacks are never updated.
- Only the cover round-trips; the order of other members does not.
- There is no automatic two-way sync, polling or unstack propagation.

Plans, links and receipts are tied to the server, remote account, local owner and path map. Change any of those and the old plan no longer applies. Receipts store outcomes and remote asset IDs, never credentials.

Apply rechecks each group before writing and rereads it afterwards. If a create response is lost, Facet reconciles it before any retry instead of sending it again. Cancelling stops between groups; a later apply picks up from the receipts.

> **Warning:** Immich cannot create a stack conditionally. Another client can change the assets between Facet's last check and the write, and Facet cannot roll that back.

## The inbound webhook

The webhook works the other way round: Immich tells Facet an asset changed, and Facet replies with what it knows.

**It is off by default and never starts a scan.** Instead:

- **Photo known and scored** → Facet pushes its rating and favorite back to Immich straight away. Score a photo, upload it, and the rating lands in Immich without waiting for `--immich-sync`.
- **Photo unknown or not scored yet** → Facet adds the path to a capped pending list, and the next `--immich-sync` logs it.

### Enable it

The token is a secret, so it lives in an environment variable, not in `scoring_config.json` (that file is readable by everyone on most installs). The config names the variable; the variable holds the value.

1. Generate a token and export it where the viewer starts — systemd unit, `docker-compose.yml` or shell profile:

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Name that variable in `scoring_config.json`:

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Restart the viewer (`python viewer.py`).

If `token_env` is empty, or the variable is unset or empty, the endpoint is disabled and returns **404** (like `frame.tokens` and `upload.username`).

### Point Immich at it

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — `Asset uploaded`. Add `Asset updated` if edits should trigger it too.
2. **Action** — **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, at an address the Immich container can reach. If both run in Docker on one host, use the service name (`http://facet:5000/…`), not `localhost`.
4. **Header** — name `x-facet-token`, value your token. The name must match `webhook.header`. `Authorization: Bearer <token>` also works, for proxies that only offer that.
5. Save, then upload one photo to check.

### What the endpoint answers

| Status | Meaning |
|--------|---------|
| `202` | Accepted. The JSON counts this delivery's assets: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | Valid JSON, but no asset Facet recognised. Logged, not an error. |
| `400` | The body was not JSON. |
| `401` | No token in the request. |
| `403` | Wrong token. |
| `404` | The feature is disabled (no token configured). |

Facet reads `originalPath` from the payload, wherever it sits: a bare asset, `{"asset": {…}}`, a list, or any of those under `data` / `items` / `assets`. If the payload has the asset `id`, Facet fetches that asset from Immich and checks its path and owner/library before updating. A mismatch counts as `failed`.

The next sync logs pending paths:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scan those photos (`python facet.py /mnt/photos`) and they leave the list on the following sync. The list keeps at most `max_pending` entries and drops the oldest first.

### Security notes

- The token is compared in constant time; a wrong token gets a flat `403` with no timing signal.
- Serve the viewer over HTTPS unless Immich reaches it over a private network: the token travels in a header on every delivery.
- To rotate the token, change the environment variable and the Immich workflow header together, then restart the viewer.
- The webhook pushes the global rating, not any one user's. For per-user ratings in Immich, leave the webhook off and run `--immich-sync --user <name>` on a schedule.

## Diagnostics in the viewer

Open **Immich diagnostics** from the user menu's **Jobs & diagnostics** submenu. It needs superadmin access in multi-user mode, and edition access (or trusted local editing) in single-user mode.

- Nothing is read from Immich until you click **Test connection**. The test reads the server version and account access and writes nothing.
- Path coverage checks at most 200 indexed photos. It does not confirm that each one matches an Immich asset.
- The last-sync time may predate a change to the configured server.
- The version check does not verify stack permissions.
- Credentials and server paths are never shown.

## Configuration reference

The full `immich` block, with the shipped defaults:

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
  "path_map": [
    { "facet_prefix": "", "immich_prefix": "" }
  ],
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": false,
    "top_picks_album": "",
    "top_picks_min_rating": 4
  },
  "webhook": {
    "token_env": "",
    "header": "x-facet-token",
    "max_pending": 500
  },
  "timeout_seconds": 30
}
```

| Key | Default | Meaning |
|-----|---------|---------|
| `url` | `""` | Immich base URL, `http` or `https`. A trailing slash is trimmed. |
| `api_key` | `""` | API key, sent as `x-api-key`. Empty aborts any sync with a clear error. |
| `owner_id` | `""` | Only match assets with this exact Immich `ownerId`. |
| `library_id` | `""` | Only match assets in this exact Immich `libraryId`. Empty means any library. |
| `path_map` | one empty pair | Prefix rewrites between Facet paths and Immich `originalPath`. First match wins; used both ways. |
| `push.ratings` | `true` | Push star ratings 1–5 (and their clears). |
| `push.favorites` | `true` | Push `isFavorite` (and its clears). |
| `push.rejected` | `false` | Push `rating: -1` for photos rejected in Facet. Requires `push.ratings`. |
| `push.top_picks_album` | `""` | Album name to fill. Empty means Facet never touches albums. |
| `push.top_picks_min_rating` | `4` | Minimum star rating for that album. |
| `webhook.token_env` | `""` | Environment variable holding the webhook secret. Empty disables the endpoint. |
| `webhook.header` | `"x-facet-token"` | Header Immich sends the token in. |
| `webhook.max_pending` | `500` | Maximum length of the pending (unscored) path list. |
| `timeout_seconds` | `30` | Per-request HTTP timeout. |

## Troubleshooting

### Everything comes back `unmatched`

The path map is wrong. This is by far the most common failure.

1. Open a photo in Immich and press `i`. Note the path in the info panel.
2. Find the same photo's path in Facet (the gallery detail panel, or `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. The two paths end the same way. The parts that differ are your `facet_prefix` and `immich_prefix`.

Common traps:

- **Missing trailing slash.** `"/mnt/photos"` → `"/usr/src/app/external"` also rewrites `/mnt/photosXYZ/a.jpg`. End both prefixes with `/`.
- **Host path vs container path.** The Immich path is what the *container* sees. Check with `docker compose exec immich-server ls /usr/src/app/external`.
- **Symlinks and bind mounts.** Immich stores the path it walked. A symlink on one side makes the strings differ.
- **Case and Unicode.** Matching is exact. On a case-insensitive share, `/Photos/` and `/photos/` do not match each other.
- **Immich has not indexed the file yet.** Run **Scan All Libraries** and check the asset exists in Immich.

`--immich-sync --dry-run` logs the first 20 unmatched paths, which usually shows the wrong prefix.

### `--immich-test` fails

- `Unsupported Immich URL scheme` — `url` needs `http://` or `https://`.
- `HTTP 401` — the API key is wrong or revoked.
- `HTTP 403` — the key lacks `server.about`. Re-create it with the six scopes above.
- Connection refused / timeout — wrong port, or Facet cannot reach the container. Test with `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` from the Facet machine.

### The webhook returns 404

The feature is disabled: `webhook.token_env` is empty, or the variable it names is unset or empty *in the viewer's environment*. Exporting it in your shell does not reach a viewer run by systemd or Docker. Set it in the unit or compose file and restart.

### The webhook returns 401 or 403

`401`: no token arrived, so the header name Immich sends does not match `webhook.header`. `403`: the token is wrong. Compare the workflow's header value with the environment variable.

### `ModuleNotFoundError: No module named 'sync'`

The server looks healthy, but the webhook fails when Immich calls it and `--immich-sync` fails outright. Check with:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

If you get `ModuleNotFoundError: No module named 'sync'`, your Docker image is too old. Pull the current image or rebuild from a current checkout.

### Ratings push, but the clears do not

Facet only clears a rating it pushed before, and it remembers those in `stats_cache` in the Facet database. Restoring an older database, or using a fresh one, loses that memory: a rating cleared in the gap stays in Immich. Re-rate and re-clear the photo, or fix it in Immich.

### Ratings appear on the wrong photos

Facet skips ambiguous matches and reports them as `identity_conflicts`:

- one Facet path that matches several Immich assets
- several Facet paths that map to the same Immich path

Nothing is written for those paths; other photos still sync.

A webhook batch is stricter: if several Facet paths claim the same target or asset ID, every eligible entry in the batch is refused and counted as `failed`. Fix overlapping roots in `path_map`, or set `owner_id` and `library_id`, then retry. Do not guess the owner from a person's name or the path.

Immich responses must include `id` and `originalPath`, and must match any configured owner and library. A successful update means Immich accepted it; its own background metadata work may still be running.

### `rating: 0 is not valid`

The Immich server is older than 3.0. Upgrade: Facet needs `null` to clear and `-1` for `push.rejected`, and nothing works around this on 2.x.

---

**See also:** [Commands — Immich Sync](COMMANDS.md#immich-sync) · [Configuration](CONFIGURATION.md) · [Editor Interop Recipes](INTEROP.md) for XMP round-tripping with Lightroom, darktable, and digiKam.
