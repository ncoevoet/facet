# Immich Integration

> 🌐 **English** · [Français](fr/IMMICH.md) · [Deutsch](de/IMMICH.md) · [Italiano](it/IMMICH.md) · [Español](es/IMMICH.md) · [Português](pt/IMMICH.md)

Facet and [Immich](https://immich.app/) do different jobs on the same photos. Immich is the library: it ingests, backs up, and serves them to your phone. Facet is the judgement: it scores, ranks, and culls them. This page wires the two together so the verdicts Facet reaches show up as ratings and favorites in Immich, and so an upload to Immich tells Facet there is new work waiting.

The link is REST-only in both directions. Facet never touches Immich's database, and Immich never touches Facet's.

**Facet requires Immich ≥ 3.0.** Older servers reject the rating semantics Facet depends on: `null` to clear a rating and `-1` to mark one rejected. On a 2.x server the clear is refused and stale ratings stay stuck on your assets forever.

---

## Table of contents

- [How the two see the same file](#how-the-two-see-the-same-file)
- [Step 1 — share the library with Immich](#step-1--share-the-library-with-immich)
- [Step 2 — create an API key](#step-2--create-an-api-key)
- [Step 3 — map the paths](#step-3--map-the-paths)
- [Step 4 — test, then push](#step-4--test-then-push)
- [Pushing rejections](#pushing-rejections)
- [The inbound webhook](#the-inbound-webhook)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## How the two see the same file

Everything here rests on one idea: **the same photo on disk, seen from two containers**.

Facet knows a photo by its absolute path on the machine that runs the scan — `/mnt/photos/2026/07/IMG_1234.jpg`. Immich knows the same file by its own `originalPath`, which is whatever that file looks like from *inside the Immich container* — often `/usr/src/app/upload/…` for uploaded assets, or the mount point you gave an external library.

Neither side can guess the other's view, so you tell Facet the prefix rewrite once (`immich.path_map`) and every lookup in both directions goes through it. Get this right and the rest is mechanical; get it wrong and everything silently reports "unmatched" — see [Troubleshooting](#troubleshooting).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

The mapping is used both ways: outbound (`--immich-sync` translates a Facet path to find the asset) and inbound (the webhook translates Immich's `originalPath` back to find the photo).

## Step 1 — share the library with Immich

The cleanest arrangement is an **external library**: Immich reads the photos where they already live, rather than owning a second copy. Facet scans the same directory from its own side.

1. In Immich, go to **Administration → External Libraries → Create Library**, pick the owner, and add an import path pointing at the directory as the Immich container sees it.
2. Make sure that directory is bind-mounted read-only into the Immich container. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scan the library from Immich's UI (**Scan All Libraries**), and scan the same directory with Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Both tools now hold a row per file. Nothing is duplicated on disk.

If instead you upload into Immich normally (mobile auto-backup, the web uploader) and point Facet at Immich's own upload directory, the integration works exactly the same — only the prefixes differ. In that case Immich owns the file layout, so re-run the Facet scan after uploads (or use `--watch`).

## Step 2 — create an API key

In Immich: **click your avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 lets you scope a key rather than granting it everything. Facet needs exactly six scopes:

| Scope | What Facet does with it |
|-------|-------------------------|
| `server.about` | `--immich-test` connectivity/auth check |
| `asset.read` | Resolve assets by `originalPath` |
| `asset.update` | Write `rating` and `isFavorite` |
| `album.read` | Find an existing top-picks album by name |
| `album.create` | Create the top-picks album the first time |
| `albumAsset.create` | Add photos to the top-picks album |

Drop the last three if you leave `push.top_picks_album` empty — Facet only touches albums when that name is set.

The key is sent as an `x-api-key` header on every request. Put it in `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **A note on `PUT /api/assets`.** Facet writes ratings with `PUT /api/assets`, which Immich's OpenAPI document marks *deprecated*. The replacement `PATCH` aliases are announced but **absent from the published spec**, so there is nothing to migrate to yet — `PUT` remains the only endpoint that actually exists, and Facet keeps using it. Every Immich path Facet touches lives in `ImmichClient` (`sync/immich.py`), so the day the `PATCH` routes ship, the change is one class.

## Step 3 — map the paths

Add one pair per root you share. The first pair whose `facet_prefix` matches a photo wins:

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

Leave the shipped placeholder (`{"facet_prefix": "", "immich_prefix": ""}`) alone and paths pass through unchanged — correct only when Facet and Immich genuinely see identical absolute paths, which is the case if you run Facet inside the Immich container's namespace and almost never otherwise.

To read the real value, open any photo in Immich, press `i` for the info panel, and compare the file path shown there with the path Facet reports for the same photo.

## Step 4 — test, then push

```bash
# Connectivity + authentication only. No writes.
python facet.py --immich-test

# Resolve every asset and report what WOULD change. Still no writes.
python facet.py --immich-sync --dry-run

# For real.
python facet.py --immich-sync
```

The sync reports `matched` / `unmatched` / `updated` / `skipped (unrated)` / albums created. A first run with a large `unmatched` count almost always means the path map is wrong — see [Troubleshooting](#troubleshooting).

What gets pushed:

- **Star ratings 1–5** → Immich's `rating`. A photo you never rated pushes nothing.
- **Favorites** → Immich's `isFavorite`.
- **Clears.** If you rated a photo 5, synced, then reset it to unrated, the next sync sends `rating: null` so Immich forgets it too. Facet remembers what it last pushed (in the `stats_cache` side table) precisely so this transition is not lost. It is `null` and never `0` — Immich v3 rejects `0` outright, and one rejected batch aborts the whole sync.
- **An optional top-picks album**, filled from `push.top_picks_min_rating`, when `push.top_picks_album` names one.

In multi-user mode, `--immich-sync --user alice` pushes Alice's `user_preferences` ratings instead of the global columns, and tracks its state under her own scope.

## Pushing rejections

Off by default. Turn it on and a photo you rejected in Facet's culling darkroom gets Immich's own rejected marker:

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

- A rejected photo pushes `rating: -1`, Immich v3's value for "rejected".
- **Rejection outranks stars.** A rejected 5-star photo pushes `-1`, not `5` — you threw it away, and that is the fact worth mirroring.
- **Un-rejecting clears it.** A photo that pushed `-1` and is later un-rejected pushes its current star rating instead, or `rating: null` if it has none. Same tracked-state mechanism as any other clear.
- A rejected photo never joins the top-picks album.
- `push.ratings: false` suppresses it. `-1` is a rating write, so a config that disabled rating pushes does not get one smuggled back in.

Leave it off if other people (or your phone) look at the Immich library: a `-1` is visible there, and "rejected in Facet" is a working judgement you may not want broadcast.

## The inbound webhook

Everything above is Facet → Immich. The webhook is the other direction: Immich tells Facet that an asset just changed, and Facet answers immediately with what it knows about it.

**It is off by default and it never starts a scan.** A webhook is an unauthenticated-by-session call from another daemon; letting one spawn GPU work would hand any token holder a way to flatten your machine. What it does instead:

- **Photo known and scored** → its rating/favorite is pushed straight back to Immich, right then, as a single-asset update. This is what closes the loop after a scan: score a photo, upload it, and the rating lands in Immich without waiting for the next `--immich-sync`.
- **Photo unknown or not scored yet** → the path is remembered in a bounded, deduplicated pending list, and the next `--immich-sync` logs it. Nothing is scanned.

### Enable it

The token is a shared secret, so it lives in the environment, never in `scoring_config.json` (that file is rewritten in place by several endpoints and is world-readable on most installs). Config names the *variable*; the variable holds the *value*.

1. Generate a token and export it wherever the viewer starts — your systemd unit, `docker-compose.yml`, or shell profile:

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

An empty `token_env`, or a variable that is unset or empty, disables the endpoint entirely — it returns **404**, exactly like `frame.tokens` and `upload.username`. There is no half-open state.

### Point Immich at it

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — pick the asset event you want mirrored. `Asset uploaded` is the useful one; add `Asset updated` if you also want edits to re-trigger.
2. **Action** — choose **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, using an address the Immich container can actually reach. If both run in Docker on one host, that is the service name (`http://facet:5000/…`), not `localhost`.
4. **Header** — name `x-facet-token`, value the token you generated. The name must match `webhook.header`; rename both together if your setup needs a different one. `Authorization: Bearer <token>` is accepted too, for proxies that only offer that.
5. Save, then upload one photo to confirm.

### What the endpoint answers

| Status | Meaning |
|--------|---------|
| `202` | Body understood. The JSON tally counts the assets in *this* delivery: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | Valid JSON, but no asset Facet recognised. Logged, not an error — the payload shape is Immich's to change. |
| `400` | The body was not JSON at all. |
| `401` | No token in the request. |
| `403` | Wrong token. |
| `404` | The feature is disabled (no token configured). |

Facet reads `originalPath` out of the payload and is deliberately liberal about where it sits — a bare asset object, `{"asset": {…}}`, a list, or any of those nested under `data` / `items` / `assets` all work. If the payload carries the asset `id`, Facet uses it and skips a lookup round-trip.

Pending paths are reported by the next sync:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scan those photos (`python facet.py /mnt/photos`) and they drop off the list on the following sync. The list is capped at `max_pending` entries, oldest dropped first, so a chatty Immich can never grow it without limit.

### Security notes

- The token is compared constant-time. A wrong token is a flat `403` with no timing signal.
- Serve the viewer over HTTPS if Immich reaches it across anything less trusted than a private bridge network — the token rides in a header on every delivery.
- Rotate by changing the environment variable and the Immich workflow header together, then restarting the viewer.
- The webhook reads the global rating columns, so in multi-user mode it mirrors the shared/global rating, not any one user's overlay. If per-user ratings are what you want in Immich, leave the webhook off and use `--immich-sync --user <name>` on a schedule.

## Configuration reference

The full `immich` block, with the shipped defaults:

```json
"immich": {
  "url": "",
  "api_key": "",
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
| `path_map` | one empty pair | Prefix rewrites between Facet paths and Immich `originalPath` values. First match wins; used in both directions. |
| `push.ratings` | `true` | Push star ratings 1–5 (and their clears). |
| `push.favorites` | `true` | Push `isFavorite` (and its clears). |
| `push.rejected` | `false` | Push `rating: -1` for photos rejected in Facet. Requires `push.ratings`. |
| `push.top_picks_album` | `""` | Album name to fill. Empty means Facet never touches albums. |
| `push.top_picks_min_rating` | `4` | Minimum star rating for that album. |
| `webhook.token_env` | `""` | Name of the environment variable holding the webhook secret. Empty ⇒ the endpoint 404s. |
| `webhook.header` | `"x-facet-token"` | Header Immich sends the token in. |
| `webhook.max_pending` | `500` | Cap on the remembered-but-unscored path list. |
| `timeout_seconds` | `30` | Per-request HTTP timeout. |

## Troubleshooting

### Everything comes back `unmatched`

The path map is wrong — this is the failure by a wide margin.

1. Open a photo in Immich and press `i`. Note the path in the info panel.
2. Find the same photo's path in Facet (the gallery detail panel, or `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. The two share a *suffix*. What differs is the prefix, and those two prefixes are exactly `facet_prefix` and `immich_prefix`.

Common traps:

- **A missing trailing slash.** `"/mnt/photos"` → `"/usr/src/app/external"` rewrites `/mnt/photosXYZ/a.jpg` too. Always end both prefixes with `/`.
- **Host path vs container path.** The Immich path is what the *container* sees. `docker compose exec immich-server ls /usr/src/app/external` settles it.
- **Symlinks and bind mounts.** Immich stores the path it walked. If your library is reached through a symlink on one side, the strings differ even though the file is one.
- **Case and Unicode.** Comparison is exact. A library on a case-insensitive share can hold both `/Photos/` and `/photos/`; only the stored spelling matches.
- **Immich has not indexed the file yet.** Run **Scan All Libraries** and check the asset actually exists in Immich before blaming the map.

`--immich-sync --dry-run` names the first 20 unmatched paths in the log; that list usually identifies the wrong prefix on sight.

### `--immich-test` fails

- `Unsupported Immich URL scheme` — `url` needs `http://` or `https://`.
- `HTTP 401` — the API key is wrong or was revoked.
- `HTTP 403` — the key is valid but lacks `server.about`. Re-create it with the six scopes above.
- Connection refused / timeout — the port is wrong, or Facet cannot reach the container. Test with `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` from the machine that runs Facet.

### The webhook returns 404

The feature is disabled. Either `webhook.token_env` is empty, or the variable it names is unset or empty *in the viewer's own environment*. Exporting it in your interactive shell does nothing for a systemd- or Docker-managed viewer — set it in the unit file or compose file and restart.

### The webhook returns 401 or 403

`401` means no token arrived: the header name Immich sends does not match `webhook.header`. `403` means a token arrived and was wrong — compare the workflow's header value against the environment variable, character for character.

### Ratings push, but the clears do not

Facet only sends a clear for a photo it has actually pushed before; that memory lives in `stats_cache` in the Facet database. Restoring an older database (or running against a fresh one) loses it, and a rating cleared during the gap will not be un-set in Immich. Re-rate and re-clear the photo, or fix it in Immich directly.

### Ratings appear on the wrong photos

Two files with the same `originalPath` cannot happen inside Immich, but two *Facet* roots mapping onto one Immich prefix can collide. Check that your `path_map` pairs do not overlap: the first matching pair wins, so a broad pair listed before a narrow one swallows it.

### `rating: 0 is not valid`

The Immich server is older than 3.0. Upgrade — Facet's clear semantics need `null`, and `push.rejected` needs `-1`; there is no fallback that works on 2.x.

---

**See also:** [Commands — Immich Sync](COMMANDS.md#immich-sync) · [Configuration](CONFIGURATION.md) · [Editor Interop Recipes](INTEROP.md) for XMP round-tripping with Lightroom, darktable, and digiKam.
