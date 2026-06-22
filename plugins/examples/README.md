# Facet Plugin Examples

Runnable plugin reference implementations. Copy a file into the project's
top-level `plugins/` directory (drop the `.example` suffix) and enable
plugins in `scoring_config.json`:

```json
"plugins": {
  "enabled": true,
  "webhooks": [],
  "actions": {}
}
```

## Available examples

| File | Trigger | What it does |
|------|---------|--------------|
| `slack_webhook.py.example` | `on_high_score` | Posts a one-line Slack message (via a Slack incoming-webhook URL) when a photo scores above the threshold. |
| `copy_to_folder.py.example` | `on_high_score` | Hard-links (or copies, across filesystems) each photo above the threshold into a destination folder, preserving its directory structure. |
| `score_publisher.py.example` | `on_score_complete` | Writes each finished score as a JSON line to a rolling log file (works with `tail -F` or a log shipper). |

## Webhook payload shape

Outgoing HTTP webhooks (configured under `plugins.webhooks` in
`scoring_config.json`) POST a JSON body of the form:

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/2026/01/IMG_1234.cr3",
    "aggregate": 9.4,
    "aesthetic": 8.9,
    "comp_score": 9.1,
    "category": "portrait",
    "tags": ["portrait", "golden_hour"]
  }
}
```

`event` is one of:

* `on_score_complete` — every photo, once scoring finishes
* `on_new_photo` — first time a photo is added to the DB
* `on_burst_detected` — when a burst group is identified
* `on_high_score` — only when `aggregate` clears `plugins.high_score_threshold`
  (default 8.0). A per-webhook `min_score` (default 0.0) can filter further.

A formal JSON Schema for the payload lives in
`plugins/examples/webhook_payload.schema.json` if you want to validate
incoming requests on the receiving side.

## Security notes

* Webhook URLs are validated on delivery (and by the test endpoint).
  Only `http`/`https` are allowed; hostnames that resolve to a private,
  loopback, or link-local address (including the cloud metadata IP
  `169.254.169.254`) are rejected and logged.

* The request connects to the resolved IP with the original hostname in
  the `Host` header, so a DNS-rebinding swap cannot redirect a validated
  URL to a private address mid-flight.

* Delivery is best-effort: a 5xx, timeout, or transport error is logged
  but not retried. For at-least-once delivery, queue and retry on the
  receiving side.

* Outbound timeout is 10 seconds.
