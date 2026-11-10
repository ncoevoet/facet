# Deployment Guide

> 🌐 **English** · [Français](fr/DEPLOYMENT.md) · [Deutsch](de/DEPLOYMENT.md) · [Italiano](it/DEPLOYMENT.md) · [Español](es/DEPLOYMENT.md) · [Português](pt/DEPLOYMENT.md) · [简体中文](zh/DEPLOYMENT.md)

Run the Facet viewer on a remote server or NAS.

> **New here?** This guide is for serving Facet to other machines. To run it on your own
> computer, start with [Installation](INSTALLATION.md).

## Overview

Facet has two workloads:

| Component | Hardware | Purpose |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24GB VRAM) or CPU (8GB RAM minimum, 12GB recommended; more for `12gb`/`16gb`/`24gb`, see [Container Memory Limits](#container-memory-limits)) | Analyze and score photos |
| **Viewer** (`viewer.py`) | Any machine (low resources) | Serve the web gallery |

Only the viewer needs to run on the server. Score on a workstation, then sync the database.

> **Warning:** while `viewer.password` is empty (the default), anyone who can reach the
> viewer's port can browse the whole library and download the originals. Set
> `viewer.password` before exposing the port beyond the machine; see
> [Single-User Mode](VIEWER.md#single-user-mode-default).

On an open install (no `viewer.password`), assistant tokens (**Connect an assistant**) can
only be managed from the computer running Facet. Behind Docker or a reverse proxy, set
`viewer.password`, or run the request on the host
(`docker compose exec facet python -c "import urllib.request ..."`). A reverse proxy must
send `X-Forwarded-For` or `Forwarded`, otherwise it is treated as the local machine.

## Path Mapping

When the scoring machine and the viewer see photos under different paths, set
`viewer.path_mapping` in `scoring_config.json` to translate database paths to local paths.

**Example:** photos scored on Windows via UNC/NFS, served from a Linux NAS:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

This maps `\\NAS\share\Photos\2024\IMG_001.jpg` to `/volume1/Photos/2024/IMG_001.jpg`.
Use forward slashes in keys; backslashes are normalized.

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

- The database keeps the original scan paths (e.g. `\\NAS\share\Photos\2024\IMG_001.jpg`).
- Thumbnails live in the database, so browsing needs no disk access.
- Mapping applies whenever the viewer opens an original: downloads, full-resolution view,
  captioning and critique.
- UNC paths (`\\server\share`) and drive letters (`Z:\`) both work.

## Container Path Semantics

In Docker/Podman, every folder you type in the viewer is a path **inside the container**.
This covers a "Cull to folder" target, an album export destination and
`viewer.export.allowed_target_dirs`. Use the mount point, never the host path.

**Example.** The shipped `docker-compose.yml` mounts your photos at `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

To cull rejects into a `rejects` subfolder, enter `/data/photos/rejects`, not
`/home/you/Pictures` or `D:\Photos`, which the container cannot see.

To write outside the photo tree, mount the target first, then list its container path in
`viewer.export.allowed_target_dirs`:

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

A destination outside every allowed root is refused, after resolving symlinks and `..`.
See [Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations).

**This refusal is not a permission problem.** It happens before any file is touched. A
uid mismatch between the container's `facet` user and your host account is a separate
failure: it occurs during the copy/move and is logged with the OS error.

### Where a Container's Trash Goes

With `viewer.cull.allow_trash` on, `trash_rejects` uses `send2trash`. In the shipped layout
(photos bind-mounted at `/data/photos`, uid 1000, `HOME=/home/facet`), the photos and
`$HOME` are on different filesystems, so trashed files go to the photo volume's own trash:

- files: `/data/photos/.Trash-1000/files/<name>`
- metadata: `<name>.trashinfo` (with `Path=` and `DeletionDate=`) in `/data/photos/.Trash-1000/info/`
- the directory is created mode `0700`

`.Trash-1000` is visible on the **host**, so a plain `mv` out of `files/` restores a photo.
Rescans skip it while `scanning.skip_hidden_directories` is true (the default).

Two exceptions:

- **No bind mount** for the photos (e.g. `docker run` with photos inside the container):
  trash goes to `~/.local/share/Trash` in the container and is **lost when the container is
  removed**.
- **Rootless Podman**: `.Trash-1000` is owned by the mapped host subuid, not your account;
  restoring may need `podman unshare`.

To choose the destination yourself, use `move_rejects` to a `target_dir` instead
([Cull to folder](VIEWER.md#cull-to-folder)).

### Config File Ownership

Facet only takes ownership of a `/config/scoring_config.json` it created; an existing file
keeps its owner and mode. The one exception (a config the container's `facet` user cannot
read) and the rootless-Podman recipe are in
[Installation — Container file ownership](INSTALLATION.md#container-file-ownership).

With compose `group_add` (see [Photo Shares Readable Only Through a Group](#photo-shares-readable-only-through-a-group-group_add)),
the readability check uses those groups too, so a config readable through such a group is
left alone. If the `setpriv` check itself fails, the file is treated as unreadable.

## Building the Angular Client

The server serves the pre-built SPA from `client/dist/client/browser/`. Build it before
deploying:

```bash
cd client && npm install && npx ng build && cd ..
```

This needs Node.js 20+ at build time only, not on the server.

## Synology NAS (DS420j / J-series)

The J-series has an ARM CPU, 1GB RAM and no Docker. The viewer runs directly with Python.

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

On the scoring workstation, export a smaller database for the NAS:

```bash
python database.py --export-viewer-db
```

This creates `photo_scores_viewer.db`, which:

- drops CLIP, caption and face embeddings;
- keeps the per-photo histogram (~2 KB each) for the RGB histogram widget;
- shrinks thumbnails from 640px to 320px;
- starts with empty saved-place and recent-location lists; the scoring machine's private places are not copied;
- typically turns a 14GB database into ~4-5GB.

Exports are incremental: only new and changed photos are synced. For a full rebuild:

```bash
python database.py --export-viewer-db --force-export
```

> **Warning:** `--force-export` discards ratings, locations, manual tags and private saved/recent places set in the
> viewer on the NAS. Only an incremental export keeps them.

**Completion and retry.** A full export is prepared in an owner-only temporary file beside the destination, stripped of private source state, compacted and checked for SQLite and foreign-key consistency before publication. A new output appears only when ready. Replacing an existing output uses SQLite's backup transaction, preserving its inode for open readers and WAL connections; failure keeps the previous database. New outputs and backup snapshots require a filesystem that supports hard links. If it does not, the command fails without publishing a partial file; choose a compatible output directory.

An incremental export first upgrades the destination schema, then synchronizes one source snapshot in one destination transaction. A failed or interrupted data sync rolls back photo, face, tag, vector and review-receipt changes together; the schema upgrade may remain. Fix the reported cause and rerun the same command. A corrupt new-photo thumbnail is an error, so repairing it in the source and retrying also generates its thumbnail. Existing thumbnails stay unchanged. Destination review edits, manual tags and saved/recent places remain local and are preserved by incremental sync.

Exports reserve free space for staging or rollback journals and fail before copying if the estimate does not fit. Exceptions and normal interrupts remove the temporary copy; a forcibly killed process can leave a hidden owner-only `.*.export-*` file beside the output. Once the exporter has stopped, remove that temporary file and retry. The old published database remains the recovery point. SQLite locking still applies: retry lock errors when the destination writer is idle.

If the output's main file is missing but a `-wal`, `-shm` or `-journal` companion remains, export stops without deleting it. Close users of that database and recover it before retrying; a surviving WAL may contain data that belongs to the previous database.

"Find Similar" does not work on the exported database (no embeddings). Use the scoring
machine for that.

**Manual tags.** The export carries [manual tags](VIEWER.md#manual-tags)
(`photo_manual_tags`). An incremental export only adds the scoring database's tags:

- A tag removed on the NAS comes back if the scoring database still has it.
- A tag added on the NAS is never copied back; add it on the scoring machine too.
- A tag removed on the scoring machine stays on the NAS until `--force-export`.
- The 50-tags-per-photo cap is not enforced on the merge, so a photo can exceed it.

### Sync Files

Build the Angular client first ([Building the Angular Client](#building-the-angular-client)),
then sync to the NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` carries the shipped defaults, so the NAS runs on those. To use your own
`scoring_config.json`, add it to the `rsync` list. Review it first: it holds the viewer
password and API keys in plaintext.

The viewer opens `photo_scores_pro.db` by default (override with `DB_PATH`). On the NAS,
set `DB_PATH=/volume1/facet/photo_scores_viewer.db` or symlink it:

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

For downloads, the originals must be reachable on the NAS at the `path_mapping` path.

### Low-Memory Configuration

Add `viewer.performance` to `scoring_config.json` on the NAS:

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
    }
  }
}
```

This overrides the global `performance` settings (tuned for scoring) with values for 1GB
RAM. See [Configuration](CONFIGURATION.md#viewer-performance).

### Run

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Production (1 worker for 1GB RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Open `http://your-synology-ip:5000`.

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

Use Synology's reverse proxy: DSM > Control Panel > Login Portal > Advanced > Reverse Proxy:

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Add a Let's Encrypt certificate from DSM > Control Panel > Security > Certificate.

For the agent tab bridge ([AI Agents](AGENTS.md)), open the rule's **Custom Header** tab
and choose **Create > WebSocket**. This adds the `Upgrade` and `Connection` headers
`/api/mcp/bridge` needs. If the rule rewrites the `Host` header, list your public origin in
`viewer.mcp.allowed_origins`.

## Synology NAS (Plus / x86 series)

Plus-series NAS supports Docker (Container Manager).

### Running the published image

Install as in [Installation › Install with Docker](INSTALLATION.md#install-with-docker):
`docker compose up -d` on a CPU NAS, or the per-profile block with an NVIDIA card. The
`.env` settings and config mount are in
[Installation › Docker settings you can change](INSTALLATION.md#docker-settings-you-can-change).
Below is only what differs on a NAS.

**The images are `linux/amd64` (x86_64) only.** That covers x86 NAS hardware (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer or plain Docker on Intel/AMD). There is
no `arm64` image. On an ARM NAS or a Raspberry Pi, build locally with
`docker compose build`; the compose file keeps `build: .` under the `image:` key for this.

**Budget the disk:** the image plus the models each profile downloads on first run.

- Images, unpacked: CPU ~3.34 GB, `latest-cuda` (`sm_75`-`sm_120`) ~13.1 GB,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13.8 GB ([Image size](#image-size)).
  `docker pull` transfers less, compressed.
- Models: `legacy` 4.69 GB, `8gb` 6.93 GB, `12gb`/`16gb` 14.55 GB, `24gb` 19.32 GB
  ([Download sizes](INSTALLATION.md#download-sizes)).
- `docker compose down -v` deletes the model volumes and forces a re-download.

**Versioned tags.** `:latest`, `:latest-cuda` and `:latest-cuda-legacy` move on every
release. Pin a version (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) on a NAS
you do not want changing under you. The variants build from one `Dockerfile` via the
`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` and `REQUIREMENTS_LOCK` build args, set in
`.github/workflows/docker-publish.yml`. A manual `workflow_dispatch` run of that workflow
republishes `latest` / `latest-cuda` / `latest-cuda-legacy` from `master` without a release.

**Commercial build.** Add `--build-arg FACET_LICENSING=commercial` (compose:
`build.args.FACET_LICENSING: commercial`). This skips the restricted lock (`insightface`,
`pyiqa` and their dependencies) and sets `FACET_LICENSING_MODE=commercial`. The default
`FACET_LICENSING=default` keeps the published behaviour. The restricted lock follows
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` for the legacy lock). See
[Installation](INSTALLATION.md#commercial-install-and-the-restricted-packages).

For a small viewer-only image (no CUDA), build a slim one. Every `COPY` source must be
git-tracked, which is why `scoring_config.json` is not copied; without it the container
runs on the defaults in `config/`.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

> **Agent tab bridge needs one worker.** With more than one worker, a `ui_*` call can reach
> a process that does not know your tab and answers `no_tab`. Use `--workers 1` if you use
> [AI Agents](AGENTS.md).

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

### Photo Shares Readable Only Through a Group (`group_add`)

On a NAS the photo share is often readable only through a group (on Synology, typically
`users`, gid 100). Give the container that group with `group_add`, using the numeric gid
from `id <your-user>` on the NAS:

```yaml
services:
  facet:
    group_add:
      - "100"
```

The entrypoint drops from root to `facet` with `setpriv` and keeps those gids. Check with
`docker compose exec facet grep Groups /proc/1/status`: it lists `1000` plus your gids.

Alternative: run with `user: "1000:1000"` plus `group_add`. The entrypoint then neither
chowns nor seeds `/config`, so every mount must already be writable by uid 1000.

## Container Memory Limits

Facet reads the container's memory limit (`memory.max` on cgroup v2,
`memory.limit_in_bytes` on v1) instead of the host's RAM. It sizes which models load
together, the RAM chunk size, model caching and RAW decoding against that limit. Older
releases (v1.7.2 and before) ignored `mem_limit` and could be OOM-killed
([issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Recommended minimum memory per profile

Model weights are only part of peak memory: the torch runtime, decoded images and
activations add to it. Treat these as floors.

| VRAM profile | Model weights (total) | Recommended container memory |
|---|---|---|
| `legacy` / `8gb` | 15.0 GB | 12 GB (GPU) / 8 GB minimum, 12 GB recommended (CPU) |
| `12gb` / `16gb` | 22.0 GB | at least 18 GB (provisional) |
| `24gb` | 25.0 GB | at least 18 GB (provisional) |

- **GPU and CPU differ.** On a GPU the weights sit in VRAM, and RAM mainly holds decoded
  images: an `8gb` run on an RTX 3080 (405 photos, `ram_chunk_size: 12`, `num_workers: 2`) peaked at
  9.23 GB and passed at `mem_limit: 12g`. On
  CPU, all models load into RAM. Size from the row that matches how you run.
- **8 GB is a floor on CPU.** 50-photo scans at `--memory=8g` completed on `legacy` (peak 7.26 GB) and
  `8gb` (7.56 GB), within about half a gigabyte of the cap on 18-20 MP JPEGs. Larger frames, RAW
  decoding or a busy host need more, hence 12 GB recommended.
- **`12gb`, `16gb` and `24gb` are unmeasured.** 18 GB is a provisional placeholder.
- **`12gb` VRAM peak: 9.4–11.3 GiB (simulated).** Whole-card peak under 11.7 and 12.0 GiB caps, including about 2 GiB of desktop use; the PyTorch peak was 6.3 GiB allocated, 8.8 GiB reserved (the Qwen3.5 tagger pass). Measured under a simulated 12 GiB cap on a 16 GB card; ONNX Runtime models (InsightFace) ignore the cap; not measured on a real 12 GB card.
- **Watch anonymous memory.** `docker stats` MemUsage and the cgroup's `memory.current`
  both count reclaimable page cache, so they mislead.
- **Model caching.** With `models.keep_in_ram` at `"auto"`, a model stays in RAM between
  chunks only while its size plus `models.ram_cache_reserve_gb` (default 4 GB) is free. A
  smaller reserve caches more ([Configuration](CONFIGURATION.md#models)).

On CPU the `8gb` profile always plans the same 5 passes, whatever the limit:
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Set the limit in `docker-compose.yml` (or an override file):

```yaml
services:
  facet:
    mem_limit: 16g
```

### The pass grouping has a ceiling, and no floor at all

- **With a container limit**, each CPU pass gets the limit minus a 2 GB reserve, capped at
  5 GB. A tight limit means one model per pass.
- **Without a limit**, the budget is (system RAM − 1 GB) ÷ 1.6. A 4 GB host gets 1.9 GB per
  pass, a 2 GB host 0.6 GB.
- **A model larger than the budget** still gets its own pass, with a warning naming it. For
  example `qwen3_5_4b_tagger` (`24gb`) alone gives an 8.0 GB pass.

> **Warning:** never size a container below the largest single model in your profile.

## Windows (WSL2) with an NVIDIA GPU

Run the GPU scoring and viewer stack in Docker on Windows via WSL2, without Docker
Desktop. Everything (the distro, its images, `/var/lib/docker`) stays on a **data drive**
(e.g. `D:`), useful when `C:` is short on space.

**Prerequisites:** a recent NVIDIA driver on Windows (`nvidia-smi` works at the Windows
prompt). Do **not** install a driver inside WSL.

### 1. Install WSL2 (admin, one-time)

In an **elevated** PowerShell, then reboot if asked:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Install a distro whose disk lives on the data drive

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` puts the distro's `ext4.vhdx` under `D:\wsl\facet`. `--no-launch` skips the
first-run user prompt; the commands below run as `root`.

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

The repo on the Windows drive is at `/mnt/d/...` inside WSL. Run the block for your card
from [Installation › Install with Docker](INSTALLATION.md#install-with-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # or your card's file
curl -s localhost:5000/health          # -> ok
```

Add `--build` to build from the checkout instead of pulling. GPU profiles
(`8gb`/`12gb`/`16gb`/`24gb`) cluster faces on the GPU via the bundled RAPIDS cuML; `legacy`
clusters on CPU. The first run downloads models into the named volumes; reset them with
`docker compose down -v`.

### Reproducible, self-contained image

- **Pinned versions.** The image builds from `requirements.lock.txt`, a `pip freeze` of a
  validated container without `torch`/`torchvision` and `nvidia-*` (the CUDA base provides
  them). `kornia`, required by BiRefNet, is pinned there too. Regenerate after an
  intentional upgrade: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **GPU face clustering included.** RAPIDS cuML (`cuml-cu12`, ~5.75 GB) lets GPU profiles
  cluster on the GPU (`face_clustering.use_gpu="auto"`). `legacy`, and hosts without CUDA,
  cluster on CPU.
- **No host coupling.** Model caches are named volumes; the container runs as the
  unprivileged `facet` user.
- **Lean build context.** `.dockerignore` excludes local bulk (`conda/`, sample datasets,
  `*.db`, caches); add new large local folders there.

### Image size

No image contains model weights; those download on first run into the named volumes
([per-profile totals](INSTALLATION.md#download-sizes)). Budget disk for both.

| Image | On disk (measured) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3.34 GB | `python:3.12-slim` + CPU-wheel PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13.1 GB | CUDA 12.8 PyTorch (`sm_75`-`sm_120`, Turing through Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13.8 GB | CUDA 12.6 PyTorch (`sm_50`-`sm_90`, Maxwell through Hopper) + RAPIDS cuML |

"On disk" is the unpacked size (`docker images`). `docker pull` transfers less; compressed
sizes are not measured yet.

## Generic Linux Server

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Or use the wrapper (1 worker by default; `--workers N` for more):

```bash
python viewer.py --production --workers 4
```

The agent tab bridge needs `--workers 1` (see
[Running the published image](#running-the-published-image)).

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

    location /api/mcp/bridge {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_read_timeout 3600s;
    }
}
```

The agent tab bridge (`/api/mcp/bridge`, see [AI Agents](AGENTS.md)) is a WebSocket. It
needs the second `location` block's `Upgrade` and `Connection` headers and a single worker
(`--workers 1`, the default); otherwise the `ui_*` agent tools answer `no_tab`.

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

Use `--workers 1` if you use the agent tab bridge.

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

Re-run the export and `rsync` after each scoring session. On a server with plenty of
memory, you can sync the full `photo_scores_pro.db` instead.

### One library job at a time

A scan, `--recompute-average`, `--upgrade-db` and a ranker training run each rewrite the
database, so only one runs at a time. A second job refuses to start, names the running one,
and exits with code 75 (exit 1 if the lock file at `<db_dir>/.facet_cache/library.lock` is
unusable).

> **Warning:** this lock works on **one machine only**. Over SMB/CIFS (e.g. a Windows
> workstation scoring onto a NAS share), each machine has its own lock. Facet logs a
> warning but cannot prevent it: run library jobs from one machine at a time. NFS between
> Linux clients is fine.

### Viewer start and the gallery indexes

The first start after upgrading from 1.20 builds missing gallery indexes
([details](VIEWER.md#gallery-indexes-and-the-count-cache)). On a ~130k-photo library this
takes a few minutes and adds roughly 130 MB to the database.

**Recommended:** after upgrading, run `python database.py` (Docker:
`docker compose exec facet python database.py`) once **before** starting the viewer. A
`python facet.py` scan also builds them at its start.

If the viewer builds them instead:

- It serves while building, but the gallery is slow and **saves (ratings, rejects, album
  changes…) may be refused** with a "library busy, try again" message.
- The log shows `Creating index ...` and `Created index ... in N s` per index, then
  `Gallery indexes ready`. `/health` reports progress as `gallery_indexes` (`state`:
  `building`, `ready`, `deferred`, `failed` or `stopped`; `done` of `total`).
- Stopping the viewer keeps finished indexes; the next start resumes.
- If a scan or other library job is running, the viewer serves without the indexes and
  logs a warning. Restart it when the job ends, or run `python database.py`.
- If `.facet_cache/library.lock` next to the database is unusable (permissions, read-only
  mount), the viewer does not build. Fix the path and restart.
- With `--workers N`, one worker builds and the others serve.
- In Docker, the healthcheck's 30 s `start_period` needs no change: `/health` answers during the build.

On SQLite older than 3.48.0 (the CPU image ships 3.46.1), panorama detection cannot read
from the new index alone; its speed there was not measured. On a SQLite other than 3.51,
photos with identical timestamps may be grouped differently on the first burst pass after
the upgrade (see the CHANGELOG).

> **Warning:** copy or replace the database only after stopping the viewer. While it runs,
> recent changes sit in the `-wal` and `-shm` files, not the `.db` alone; a clean shutdown
> merges them (also with `performance.wal_checkpoint_minutes: 0`). On Windows the file
> cannot be replaced at all while the viewer has it open.

## Secret Storage and Rotation

One secret signs every login session (JWT) and every photo-frame link. It lives in
`.facet_secret` next to the config (mode `0600`, gitignored), not in `scoring_config.json`.

Older versions stored it as `share_secret` in the config, and the shipped value was public.
On start, Facet moves a leftover `share_secret` into the secret file and removes the key.
A value Facet itself published is replaced, which logs everyone out once.

| Where | How |
|-------|-----|
| Default | `.facet_secret` beside `scoring_config.json`, mode `0600` |
| Container / orchestrator | `FACET_JWT_SECRET` environment variable — read first, never written to disk |
| Rotation | `python database.py --rotate-secret`, then restart the viewer |

- **Docker:** `/app` is the container's writable layer, so a secret created there is lost
  on recreation and everyone is logged out on each image update. Set `FACET_JWT_SECRET` in
  `docker-compose.yml`, or bind-mount `- ./.facet_secret:/app/.facet_secret`.
- **Rotate** whenever the secret may have leaked (a committed config, a leaked backup, a
  departing admin). Everyone logs in again and kiosk devices re-fetch their frame links.
- **Several workers:** create the secret before the first `--workers > 1` start (run
  `python database.py --rotate-secret` once, start once with `--workers 1`, or set
  `FACET_JWT_SECRET`). Otherwise each worker makes its own and sessions break until restart.
- **Read-only install directory:** the server runs on an in-memory secret, so sessions die
  on every restart. Set `FACET_JWT_SECRET`.
- **Back it up** with the database; restoring a database without it logs everyone out.

## Multi-User Setup

To give each user a private set of photo directories, add a `users` section to
`scoring_config.json`. See [Configuration](CONFIGURATION.md#users).

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

Directory paths must match the photo paths in the database. With `viewer.path_mapping`,
use the **mapped** paths (as seen on the viewer host).

### Migrating existing ratings

To move single-user ratings to a user:

```bash
python database.py --migrate-user-preferences --user alice
```

### Scan button

To let the viewer trigger scans (the superadmin in multi-user mode; an edition session on a
single-user install with a non-empty `viewer.edition_password`), enable it. The scan runs on
the viewer's machine and needs no GPU ([No graphics card](INSTALLATION.md#no-graphics-card)):

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

The database can grow to tens of gigabytes (~14 GB after 20k+ photos), and re-scanning
costs GPU time. [Litestream](https://litestream.io/) streams changes continuously to S3,
B2, GCS, SFTP or another disk, with point-in-time restore down to a few seconds.

Facet does not bundle Litestream. Install it on the host running Facet; it runs alongside
without changes to Facet. Facet's periodic WAL checkpoint (every 30 min by default,
`performance.wal_checkpoint_minutes`; `0` disables it, a clean viewer shutdown still
checkpoints) keeps the WAL small.

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

`litestream.env` holds the AWS / B2 credentials, out of the YAML.

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

For a 14 GB database with ~50 MB/day of WAL churn during active scoring:

- ~$0.30/month for storage on S3 Standard
- ~$0.05/month for PUT operations

Negligible compared to a re-scan: ~50 GPU-hours on a 16 GB RTX.
