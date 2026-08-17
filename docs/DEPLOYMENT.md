# Deployment Guide

> 🌐 **English** · [Français](fr/DEPLOYMENT.md) · [Deutsch](de/DEPLOYMENT.md) · [Italiano](it/DEPLOYMENT.md) · [Español](es/DEPLOYMENT.md) · [Português](pt/DEPLOYMENT.md)

Run the Facet viewer on a remote server or NAS.

> **New here?** This guide is for serving Facet to other machines. To get it running on
> your own computer, start with [Installation](INSTALLATION.md).

## Overview

Facet has two workloads:

| Component | Hardware | Purpose |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24GB VRAM) or CPU (8GB+ RAM) | Analyze and score photos |
| **Viewer** (`viewer.py`) | Any machine (low resources) | Serve the web gallery |

Only the viewer needs to run on the server. Score on a workstation, then sync the database.

## Path Mapping

When the scoring machine and the viewer server access photos from different mount points, configure `viewer.path_mapping` in `scoring_config.json` to translate database paths to local disk paths.

**Example:** Photos scored on Windows via UNC/NFS, served from a Linux NAS:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Use **forward slashes** in config keys for readability — backslashes are normalized automatically. This maps DB paths like `\\NAS\share\Photos\2024\IMG_001.jpg` to `/volume1/Photos/2024/IMG_001.jpg`.

Multiple mappings are supported (first match wins):

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos",
      "//NAS/share/Archive": "/volume1/Archive"
    }
  }
}
```

**How it works:**
- The database stores the original scan paths (e.g., `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Thumbnails are stored as BLOBs in the database, so browsing needs no disk access
- Path mapping applies whenever the viewer opens an original file: downloads, full-resolution view, captioning, and critique
- Both UNC paths (`\\server\share`) and drive letters (`Z:\`) are supported
- The first matching prefix wins

## Container Path Semantics

Anything you type into a folder field in the viewer — a "Cull to folder" target, an album's copy/symlink export destination, or `viewer.export.allowed_target_dirs` in `scoring_config.json` — is resolved by the Facet process itself. **In Docker/Podman that process runs inside the container**, so every path is the path *the container* sees: the mount point, never the host-side path.

**Example.** The shipped `docker-compose.yml` mounts your photo folder at `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

To cull rejects into a `rejects` subfolder, enter `/data/photos/rejects` in the dialog — never the host path (`/home/you/Pictures`, `D:\Photos`, …), which the container cannot see at all. The same applies to `viewer.export.allowed_target_dirs`: list the container-side path.

To write somewhere other than the scanned photo tree — a separate export volume, say — mount it into the container first, then add its container-side path to `viewer.export.allowed_target_dirs`:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # extra volume for cull/export output
```

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    }
  }
}
```

A destination that resolves outside every mounted volume is refused (`403`) — Facet's target-dir check runs `os.path.realpath()` on the request *and* on every allowed root, resolving symlinks and `..` before comparing, so a path that only looks right from outside the container (or a symlink pointing outside a mount) still fails the containment test. See [Configuration — Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations) for the full allow-list reference.

**This is not a container-user permission problem.** The `facet` user's UID inside the container commonly differs from your host account's UID, and that can cause a real, separate filesystem-permission failure on a bind mount — but that happens *after* this path check passes, when the copy/symlink/move actually runs, and it is logged server-side with the underlying OS error for the file that failed. A `403 target_dir is not an allowed export location` (or a generic "access denied" in the UI) happens *before* any file is touched and has nothing to do with UIDs.

## Building the Angular Client

The FastAPI server serves the pre-built SPA from `client/dist/client/browser/`. Build it before deployment:

```bash
cd client && npm install && npx ng build && cd ..
```

This needs Node.js 20+ at build time only. The built files are static assets — Node.js is not needed on the server at runtime.

## Synology NAS (DS420j / J-series)

The J-series has an ARM CPU and 1GB RAM and no Docker support. The viewer runs directly with Python.

### Prerequisites

1. **Enable SSH:** DSM > Control Panel > Terminal & SNMP > Enable SSH
2. **Install Python3:** DSM Package Center, or via SSH:
   ```bash
   # Check if available
   python3 --version
   pip3 --version
   ```

### Install

```bash
ssh admin@your-synology-ip

# Create directory
mkdir -p /volume1/facet

# Install dependencies (viewer only)
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Export Lightweight Database

On your scoring workstation, export a stripped-down database for NAS deployment:

```bash
python database.py --export-viewer-db
```

This creates `photo_scores_viewer.db`, which:
- Strips CLIP embeddings, caption embeddings, and face embeddings
- Keeps the per-photo histogram (~2 KB each), which the viewer's RGB histogram widget reads
- Downsizes thumbnails from 640px to 320px
- Typically reduces a 14GB database to ~4-5GB

Exports are incremental: if `photo_scores_viewer.db` already exists, only new and changed photos are synced. Use `--force-export` for a full rebuild:

```bash
python database.py --export-viewer-db --force-export
```

The "Find Similar" feature won't work on the exported database (CLIP embeddings are stripped). Use the scoring machine for that.

### Sync Files

On the scoring machine, build the Angular client first (see [Building the Angular Client](#building-the-angular-client)).

Then sync the viewer and exported database to the NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

The viewer opens `photo_scores_pro.db` by default (overridable with the `DB_PATH` env var). On the NAS, either set `DB_PATH=/volume1/facet/photo_scores_viewer.db` or symlink it:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Original photos must be accessible on the NAS at the path configured in `path_mapping` for downloads to work.

### Low-Memory Configuration

Add `viewer.performance` to `scoring_config.json` on the NAS to reduce memory usage:

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

This overrides the global `performance` settings (which are tuned for scoring) with values suitable for 1GB RAM. See [Configuration](CONFIGURATION.md#viewer-performance) for details.

### Run

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Production (1 worker for 1GB RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Access at `http://your-synology-ip:5000`

### Auto-Start

DSM > Control Panel > Task Scheduler > Create > Triggered Task > User-defined script:

- **Event:** Boot-up
- **User:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Use Synology's built-in reverse proxy:

DSM > Control Panel > Login Portal > Advanced > Reverse Proxy:

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Pair with a Let's Encrypt certificate from DSM > Control Panel > Security > Certificate.

## Synology NAS (Plus / x86 series)

Plus-series NAS supports Docker (Container Manager).

### Running the published image

Install exactly as in [Installation › Install with Docker](INSTALLATION.md#install-with-docker):
`docker compose up -d` for a CPU NAS, or the per-profile block if the box has an NVIDIA
card. The `.env` knobs and the config mount are documented in
[Installation › Docker settings you can change](INSTALLATION.md#docker-settings-you-can-change).
What follows is only what differs on a NAS.

**Both published images are `linux/amd64` (x86_64) only.** That covers x86 NAS hardware (Synology Plus/x86, UGREEN, UnifyDrive, and anything running Coolify, Portainer or plain Docker on an Intel/AMD CPU). There is no `arm64` image: cross-building a multi-gigabyte ML stack under QEMU costs hours per tag, and the CUDA variant is x86-only regardless. On an ARM NAS or a Raspberry Pi, build locally with `docker compose build` instead of pulling — `docker compose up` keeps `build: .` underneath the `image:` key for exactly this case.

**Budget the disk.** Unpacked, the CPU image is approximately 3.3 GB on disk and the
CUDA image approximately 21 GB (approximate, not reverified against the current build;
pulling either transfers less, compressed — see [Image size](#image-size) below), plus
the model weights each profile downloads at first run (`legacy` 4.69 GB, `8gb` 6.93 GB,
`16gb` 14.55 GB, `24gb` 19.13 GB — full table in
[Installation › Download sizes](INSTALLATION.md#download-sizes)). `docker compose down -v`
deletes the model volumes and forces a re-download.

**Versioned tags.** `:latest` and `:latest-cuda` move on every release; pin a version
(`:1.7.2`, `:1.7`, `:1.7.2-cuda`, …) on a NAS you do not want changing under you. Both
variants build from the same `Dockerfile` via the `BASE_IMAGE`, `STRIP_TORCH` and
`INSTALL_CUML` build args, set per variant in `.github/workflows/docker-publish.yml`. That
workflow also accepts a manual `workflow_dispatch` run, which republishes `latest` /
`latest-cuda` off `master` without cutting a release or minting a versioned tag.

For a viewer-only NAS where the image must stay small (no CUDA), build a slim image instead. Note the CI guard requires every `COPY` source to be git-tracked, so the build context must include the listed files:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite
COPY viewer.py config.py database.py tagger.py scoring_config.json ./
COPY api/ api/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Mount photos for downloads
    restart: always
```

## Windows (WSL2) with an NVIDIA GPU

Run the full GPU scoring + viewer stack in Docker on Windows via WSL2 — without
Docker Desktop. This keeps everything (the Linux distro, its Docker images, and
`/var/lib/docker`) on a **data drive** (e.g. `D:`), which matters when the system
drive `C:` is short on space.

**Prerequisites:** a recent NVIDIA driver on Windows (`nvidia-smi` works at the
Windows prompt — the driver provides WSL2 CUDA passthrough; you do **not** install
a driver inside WSL).

### 1. Install WSL2 (admin, one-time)

In an **elevated** PowerShell, then reboot if asked:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Install a distro whose disk lives on the data drive

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` puts the distro's `ext4.vhdx` under `D:\wsl\facet`, so Docker's image
store stays off `C:`. `--no-launch` skips the interactive first-run user prompt;
the commands below run as `root`, which is fine for a single-purpose box.

### 3. Enable systemd (needed for the docker service)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Install Docker CE + the NVIDIA Container Toolkit (inside the distro)

```bash
wsl -d facet -u root
# --- inside the distro ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Docker repo (fall back to the newest supported codename if yours is too new):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# NVIDIA toolkit repo (distribution-agnostic):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 has no nvidia cgroup
systemctl enable --now docker
# Verify GPU passthrough:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Run Facet

The repo on the Windows drive is visible inside WSL at `/mnt/d/...`. From there, run the
block for your card from
[Installation › Install with Docker](INSTALLATION.md#install-with-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # or your card's file
curl -s localhost:5000/health          # -> ok
```

Add `--build` to build from the checkout instead of pulling the published image. GPU
profiles (`8gb`/`16gb`/`24gb`) cluster faces on the GPU via the baked-in RAPIDS cuML; the
`legacy` profile always clusters on CPU. First run downloads the profile's models into the
named volumes; reset them with `docker compose down -v`.

### Reproducible, self-contained image

- **Sticky versions.** The image builds from `requirements.lock.txt` — a full
  `pip freeze` of a validated container with `torch`/`torchvision` + `nvidia-*`
  stripped (the CUDA base image provides those). This prevents silent drift to
  untested releases. (Example this guards against: transformers 5.3 changed
  Qwen3.5 vision batching and broke the VLM tagger until the padding fix
  landed; `kornia`, required by
  BiRefNet, is not pulled in by transformers and must be pinned.) Regenerate after
  an intentional upgrade: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **GPU face clustering baked in.** RAPIDS cuML (`cuml-cu12`) ships in the image,
  so the GPU profiles (8gb/16gb/24gb) cluster faces on the GPU (HDBSCAN via
  `face_clustering.use_gpu="auto"`); the legacy profile — and any host with no CUDA
  device — always clusters on CPU. cuML is the single largest dependency (~5.75 GB;
  see the size breakdown below).
- **No host coupling.** Model caches are named volumes, not host binds; the
  container runs unprivileged (the default entrypoint drops to the `facet` user).
- **Lean build context.** `.dockerignore` excludes local-only bulk (`conda/`,
  sample datasets, `*.db`, caches, dev artifacts) — keep new large local
  directories out of the context by adding them there.

### Image size

Neither published image contains model weights — those download at first run into the
named volumes ([per-profile totals](INSTALLATION.md#download-sizes)). Budget disk for the
image **plus** those volumes.

| Image | Compressed download | On disk (approx.) | Base |
|-------|------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 4.18 GB | ~3.3 GB | `python:3.12-slim` + CPU-wheel PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 7.33 GB | ~21 GB | CUDA PyTorch + RAPIDS cuML |

"Compressed download" is what `docker pull` transfers, measured from the current
`ghcr.io/ncoevoet/facet` registry manifests. "On disk" is the unpacked image footprint
after decompression; those figures were not reverified against the current `:latest`
digest for this pass, so treat them as an approximate planning number rather than a
precise current measurement.

The CPU image is dominated by the ML dependency stack (~1.9 GB) rather than PyTorch
itself (~960 MB), plus system libs (~288 MB) and the base OS (~150 MB). In the CUDA image
the GPU stack dominates: RAPIDS cuML ~5.75 GB, CUDA runtime libs ~3.7 GB, PyTorch and
Triton ~1.9 GB, the ML deps ~1.9 GB, base OS and conda ~2-3 GB.

## Generic Linux Server

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Or use the wrapper (defaults to 1 worker; pass `--workers N` for more):

```bash
python viewer.py --production --workers 4
```

### Uvicorn + Nginx

```nginx
server {
    listen 80;
    server_name photos.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 50M;
    }
}
```

Add HTTPS:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Systemd Service

```ini
# /etc/systemd/system/facet.service
[Unit]
Description=Facet Viewer
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/facet
ExecStart=/usr/local/bin/uvicorn api:create_app --factory --host 127.0.0.1 --port 5000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now facet
```

### Caddy (auto HTTPS)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Workflow

```
 Scoring Machine (GPU)                      Server / NAS
 ─────────────────────                      ─────────────
 python facet.py /photos
         │
         ├─ database.py --export-viewer-db
         │       │
         │       └─ photo_scores_viewer.db ──rsync──▶ viewer.py serves gallery
         └─ scoring_config.json ────────────────────▶ (with path_mapping +
                                                       viewer.performance)
                                                        │
                                                 http://nas:5000
```

Re-run the export and `rsync` after each scoring session to update the database on the server. For high-memory servers, you can sync the full `photo_scores_pro.db` directly instead of exporting.

### One library job at a time

A scan, `--recompute-average`, `--upgrade-db` and a ranker training run each rewrite the whole database, so Facet allows only one of them at a time: every one takes a lock file at `<db_dir>/.facet_cache/library.lock`, and a second job refuses to start, naming the one already running.

That lock is a kernel file lock, so it excludes jobs **on one machine only**. When the database is reached over SMB/CIFS — a Windows workstation scoring photos on a NAS share, for example — each machine takes its own copy of the lock and neither sees the other. Facet detects the mount and logs a warning when it takes the lock, but it cannot enforce anything across hosts: run library jobs from one machine at a time. NFS between Linux clients is not affected — there `flock` becomes a POSIX record lock that the server arbitrates.

## Secret Storage and Rotation

One secret signs every login session (JWT) and every photo-frame link. It is **not** a `scoring_config.json` key: it lives in `.facet_secret` next to the config, created mode `0600` on first run and gitignored.

It used to be the `share_secret` key inside `scoring_config.json`. That file is git-tracked, so the value generated on first boot was committed and published — the secret this project shipped is public and must be treated as burned. On the next start Facet moves any leftover `share_secret` into the secret file, deletes the key from the config and logs a warning. A value Facet itself published is replaced rather than carried over, which logs everyone out on purpose.

| Where | How |
|-------|-----|
| Default | `.facet_secret` beside `scoring_config.json`, mode `0600` |
| Container / orchestrator | `FACET_JWT_SECRET` environment variable — read first, never written to disk |
| Rotation | `python database.py --rotate-secret`, then restart the viewer |

In Docker, `/app` is the container's writable layer, so a secret created there is lost when the container is recreated — everyone is logged out on every image update. Set `FACET_JWT_SECRET` in `docker-compose.yml`, or bind-mount the file with `- ./.facet_secret:/app/.facet_secret`.

Rotate whenever the secret may have been read by someone else: a config that was once committed, a leaked backup, a departing administrator. Rotation invalidates every session and every signed frame URL, so users log in again and kiosk devices re-fetch their links.

With `--workers > 1` every worker reads the same file, so a JWT signed by one verifies in all of them — **once that file exists**. A first boot with `--workers > 1` and no `.facet_secret` yet is the exception: each worker mints its own secret and only one of them wins the write, so a session opened against one worker is rejected by the others until the server is restarted. Create the secret before the first multi-worker start — run `python database.py --rotate-secret` once, start once with `--workers 1`, or set `FACET_JWT_SECRET`.

The same divergence becomes permanent when the install directory is not writable: the server logs an error and runs on an in-memory secret, so every session dies on each restart and each worker signs with a different key. Set `FACET_JWT_SECRET` there.

Back the file up alongside the database — restoring a database without it logs everyone out.

## Multi-User Setup

To give each user a private set of photo directories, add a `users` section to `scoring_config.json`. See [Configuration](CONFIGURATION.md#users) for the full reference.

### Quick start

```bash
# On the scoring machine, add users
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Then edit `scoring_config.json`:

```json
{
  "users": {
    "alice": {
      "password_hash": "...",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "...",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family"
    ]
  }
}
```

Directory paths must match the photo paths stored in the database. If you use `viewer.path_mapping`, the directories should use the **mapped** paths (as they appear on the viewer host).

### Migrating existing ratings

If you had ratings in single-user mode, migrate them to a user:

```bash
python database.py --migrate-user-preferences --user alice
```

### Scan button

To allow the superadmin to trigger photo scans from the viewer UI (only useful when the viewer runs on the GPU machine):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Continuous Backups with Litestream

The SQLite database can grow to tens of gigabytes (`photo_scores_pro.db` reaches ~14 GB after scoring 20k+ photos), and a re-scan costs GPU time. [Litestream](https://litestream.io/) streams the WAL to S3, B2, GCS, SFTP, or another local disk continuously, with point-in-time restore down to a few seconds.

Facet does not bundle Litestream. Install it once on the host running the viewer/scoring; it runs as a sidecar process, transparent to the application.

Facet already uses WAL mode (`db/connection.py:apply_pragmas`), and the periodic checkpoint thread (default every 30 min, configurable via `performance.wal_checkpoint_minutes`) keeps the WAL bounded. Reads stay unblocked during replication.

### Minimal Litestream config

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Cheap object storage; replace with the bucket of your choice.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # keep 3 days of point-in-time history
        snapshot-interval: 24h        # full snapshot once per day
        validation-interval: 6h       # detect corruption early
```

### Systemd unit

```ini
# /etc/systemd/system/litestream.service
[Unit]
Description=Litestream continuous SQLite replication
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/litestream replicate -config /etc/litestream.yml
Restart=always
User=facet
EnvironmentFile=/etc/litestream.env

[Install]
WantedBy=multi-user.target
```

`litestream.env` holds the AWS / B2 credentials so they stay out of the YAML.

### Restore drill

Practice this before you need it:

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# verify
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# swap in
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Cost ballpark

For the 14 GB DB with ~50 MB/day of WAL churn during active scoring, expect:
- ~$0.30/month for storage on S3 Standard
- ~$0.05/month for PUT operations
Negligible compared to a re-scan: ~50 GPU-hours on a 16 GB RTX.
