# Deployment Guide

Deploy the Facet viewer on a remote server or NAS to browse your photo library from any device.

## Overview

Facet has two distinct workloads:

| Component | Hardware | Purpose |
|-----------|----------|---------|
| **Scoring** (`photos.py`) | GPU (6-24GB VRAM) or CPU (8GB+ RAM) | Analyze and score photos |
| **Viewer** (`viewer.py`) | Any machine (low resources) | Serve the web gallery |

Only the viewer needs to run on the server. Scoring is done on your workstation, then the database is synced.

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
- Database stores the original scan paths (e.g., `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Thumbnails are stored as BLOBs in the database (no disk access needed for browsing)
- Path mapping only applies to **file downloads** (single and batch ZIP)
- Both UNC paths (`\\server\share`) and drive letters (`Z:\`) are supported
- The first matching prefix wins

## Synology NAS (DS420j / J-series)

The J-series has an ARM CPU and 1GB RAM. No Docker support. The viewer runs directly with Python.

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
pip3 install flask gunicorn pillow
```

### Export Lightweight Database

On your scoring workstation, export a stripped-down database for NAS deployment:

```bash
python database.py --export-viewer-db
```

This creates `photo_scores_viewer.db` which:
- Strips CLIP embeddings, histogram data, face embeddings (~445MB saved)
- Downsizes thumbnails from 640px to 320px (~75% space saved per thumbnail)
- Typically reduces a 14GB database to ~4-5GB

The "Find Similar" feature won't work on the exported database (CLIP embeddings are stripped). Use the scoring machine for that.

### Sync Files

From your scoring machine, sync the viewer and exported database:

```bash
rsync -avz \
  viewer.py person_viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  viewer/ comparison/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

On the NAS, rename or symlink the exported database:
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
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 viewer:app
```

Access at `http://your-synology-ip:5000`

### Auto-Start

DSM > Control Panel > Task Scheduler > Create > Triggered Task > User-defined script:

- **Event:** Boot-up
- **User:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 viewer:app >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Use Synology's built-in reverse proxy:

DSM > Control Panel > Login Portal > Advanced > Reverse Proxy:

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Pair with a Let's Encrypt certificate from DSM > Control Panel > Security > Certificate.

## Synology NAS (Plus / x86 series)

Plus-series NAS supports Docker (Container Manager). This is the cleanest approach.

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install flask gunicorn
COPY viewer.py person_viewer.py config.py database.py tagger.py scoring_config.json ./
COPY viewer/ viewer/
COPY comparison/ comparison/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--timeout", "120", "viewer:app"]
```

### Docker Compose

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

## Generic Linux Server

### Gunicorn

```bash
pip install flask gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 viewer:app
```

### Gunicorn + Nginx

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
ExecStart=/usr/local/bin/gunicorn -w 4 -b 127.0.0.1:5000 --timeout 120 viewer:app
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
 python photos.py /photos
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

## Multi-User Setup

For family NAS scenarios where each member has private photo directories, add a `users` section to `scoring_config.json`. See [Configuration](CONFIGURATION.md#users) for the full reference.

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
