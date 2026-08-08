# Bereitstellungsleitfaden

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · **Deutsch** · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md)

Betreiben Sie den Facet-Viewer auf einem entfernten Server oder NAS.

## Überblick

Facet hat zwei Arbeitslasten:

| Komponente | Hardware | Zweck |
|-----------|----------|---------|
| **Bewertung** (`facet.py`) | GPU (6-24 GB VRAM) oder CPU (8 GB+ RAM) | Fotos analysieren und bewerten |
| **Viewer** (`viewer.py`) | Beliebige Maschine (geringe Ressourcen) | Web-Galerie bereitstellen |

Nur der Viewer muss auf dem Server laufen. Bewerten Sie auf einer Workstation und synchronisieren Sie dann die Datenbank.

## Pfadzuordnung

Wenn die Bewertungsmaschine und der Viewer-Server über unterschiedliche Einhängepunkte auf Fotos zugreifen, konfigurieren Sie `viewer.path_mapping` in `scoring_config.json`, um Datenbankpfade in lokale Festplattenpfade zu übersetzen.

**Beispiel:** Fotos werden unter Windows über UNC/NFS bewertet und von einem Linux-NAS bereitgestellt:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Verwenden Sie zur besseren Lesbarkeit **Schrägstriche** in Konfigurationsschlüsseln — Backslashes werden automatisch normalisiert. Dies ordnet DB-Pfade wie `\\NAS\share\Photos\2024\IMG_001.jpg` dem Pfad `/volume1/Photos/2024/IMG_001.jpg` zu.

Mehrere Zuordnungen werden unterstützt (die erste Übereinstimmung gewinnt):

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

**So funktioniert es:**
- Die Datenbank speichert die ursprünglichen Scan-Pfade (z. B. `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Vorschaubilder werden als BLOBs in der Datenbank gespeichert, sodass das Durchsuchen keinen Festplattenzugriff erfordert
- Die Pfadzuordnung greift immer dann, wenn der Viewer eine Originaldatei öffnet: Downloads, Vollauflösungsansicht, Beschreibung und Kritik
- Sowohl UNC-Pfade (`\\server\share`) als auch Laufwerksbuchstaben (`Z:\`) werden unterstützt
- Das erste übereinstimmende Präfix gewinnt

## Erstellen des Angular-Clients

Der FastAPI-Server stellt die vorab erstellte SPA aus `client/dist/client/browser/` bereit. Erstellen Sie sie vor der Bereitstellung:

```bash
cd client && npm install && npx ng build && cd ..
```

Dies erfordert Node.js 20+ nur zur Build-Zeit. Die erstellten Dateien sind statische Assets — Node.js wird auf dem Server zur Laufzeit nicht benötigt.

## Synology NAS (DS420j / J-Serie)

Die J-Serie hat eine ARM-CPU, 1 GB RAM und keine Docker-Unterstützung. Der Viewer läuft direkt mit Python.

### Voraussetzungen

1. **SSH aktivieren:** DSM > Systemsteuerung > Terminal & SNMP > SSH aktivieren
2. **Python3 installieren:** DSM Paket-Zentrum oder über SSH:
   ```bash
   # Prüfen, ob verfügbar
   python3 --version
   pip3 --version
   ```

### Installation

```bash
ssh admin@your-synology-ip

# Verzeichnis erstellen
mkdir -p /volume1/facet

# Abhängigkeiten installieren (nur Viewer)
pip3 install fastapi uvicorn pyjwt pillow
```

### Leichtgewichtige Datenbank exportieren

Exportieren Sie auf Ihrer Bewertungs-Workstation eine reduzierte Datenbank für die NAS-Bereitstellung:

```bash
python database.py --export-viewer-db
```

Dies erstellt `photo_scores_viewer.db`, die:
- CLIP-Embeddings, Histogrammdaten und Gesichts-Embeddings entfernt
- Vorschaubilder von 640px auf 320px verkleinert
- Eine 14-GB-Datenbank typischerweise auf ~4-5 GB reduziert

Exporte erfolgen inkrementell: Wenn `photo_scores_viewer.db` bereits existiert, werden nur neue und geänderte Fotos synchronisiert. Verwenden Sie `--force-export` für eine vollständige Neuerstellung:

```bash
python database.py --export-viewer-db --force-export
```

Die Funktion „Ähnliche finden“ funktioniert auf der exportierten Datenbank nicht (CLIP-Embeddings sind entfernt). Verwenden Sie dafür die Bewertungsmaschine.

### Dateien synchronisieren

Erstellen Sie auf der Bewertungsmaschine zuerst den Angular-Client:

```bash
cd client && npm install && npx ng build && cd ..
```

Synchronisieren Sie dann den Viewer und die exportierte Datenbank auf das NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

Der Viewer öffnet standardmäßig `photo_scores_pro.db` (überschreibbar mit der Umgebungsvariablen `DB_PATH`). Setzen Sie auf dem NAS entweder `DB_PATH=/volume1/facet/photo_scores_viewer.db` oder legen Sie einen Symlink an:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Originalfotos müssen auf dem NAS unter dem in `path_mapping` konfigurierten Pfad zugänglich sein, damit Downloads funktionieren.

### Konfiguration für wenig Speicher

Fügen Sie `viewer.performance` zu `scoring_config.json` auf dem NAS hinzu, um den Speicherverbrauch zu reduzieren:

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

Dies überschreibt die globalen `performance`-Einstellungen (die auf die Bewertung abgestimmt sind) mit Werten, die für 1 GB RAM geeignet sind. Siehe [Konfiguration](CONFIGURATION.md#viewer-performance) für Details.

### Ausführen

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Produktion (1 Worker für 1 GB RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Zugriff unter `http://your-synology-ip:5000`

### Automatischer Start

DSM > Systemsteuerung > Aufgabenplaner > Erstellen > Ausgelöste Aufgabe > Benutzerdefiniertes Skript:

- **Ereignis:** Hochfahren
- **Benutzer:** root
- **Skript:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Verwenden Sie den integrierten Reverse-Proxy von Synology:

DSM > Systemsteuerung > Anmeldeportal > Erweitert > Reverse-Proxy:

| Quelle | Ziel |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Kombinieren Sie dies mit einem Let's-Encrypt-Zertifikat aus DSM > Systemsteuerung > Sicherheit > Zertifikat.

## Synology NAS (Plus / x86-Serie)

NAS der Plus-Serie unterstützen Docker (Container Manager).

Das Repository liefert eine `Dockerfile`, `docker-compose.yml` und `docker-compose.gpu.yml` im Stammverzeichnis. Das Image bündelt den vollständigen Bewertungs- + Viewer-Stack auf einer CUDA-PyTorch-Basis, erstellt den Angular-Client und stellt Port 5000 bereit. Der Viewer läuft standardmäßig im CPU-Modus; die GPU-Überschreibung muss aktiv hinzugeschaltet werden.

### Das veröffentlichte Image herunterladen (Pull)

`docker-compose.yml` und `docker-compose.gpu.yml` tragen neben `build: .` einen `image:`-Schlüssel, sodass `docker compose up` ein vorgefertigtes Image von GHCR **zieht** (pull), statt den ca. 3,3-GB-CPU-Stack (bzw. den ca. 21-GB-CUDA-Stack) lokal zu bauen:

```bash
# Nur Viewer (CPU) — zieht ghcr.io/ncoevoet/facet:latest
docker compose up -d

# Mit NVIDIA-GPU zur Bewertung (erfordert das NVIDIA Container Toolkit) —
# zieht ghcr.io/ncoevoet/facet:latest-cuda
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`docker compose build` (oder `up --build`) baut weiterhin aus dem `Dockerfile` in diesem Repository für lokales Experimentieren – genau dafür bleibt der `build:`-Schlüssel unterhalb von `image:` erhalten. Die profilspezifischen Overlays (`docker-compose.{8gb,16gb,24gb}.yml`) ziehen ebenfalls `:latest-cuda`, da alle drei GPU-Profile sind; `docker-compose.legacy.yml` (CPU) zieht das Basis-Image `:latest`.

**Zwei veröffentlichte Tags, ein Dockerfile.** `ghcr.io/ncoevoet/facet:latest` ist ein schlanker, reiner CPU-Build (keine CUDA-Laufzeitumgebung, kein RAPIDS cuML – die Gesichts-Clusterbildung fällt auf CPU-HDBSCAN zurück). `ghcr.io/ncoevoet/facet:latest-cuda` ist der vollständige CUDA-+-cuML-Stack, wie er im gesamten Dokument beschrieben wird, unverändert gegenüber einem lokalen `docker build .`. Beide stammen aus demselben `Dockerfile`, parametrisiert über Build-Argumente (`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`), die pro Variante in `.github/workflows/docker-publish.yml` gesetzt werden. Versionierte Tags (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7-cuda`, …) werden bei jedem `vX.Y.Z`-Git-Tag zusätzlich zu `latest`/`latest-cuda` veröffentlicht.

**Veröffentlichen ohne Release.** `.github/workflows/docker-publish.yml` akzeptiert auch einen manuellen `workflow_dispatch`-Trigger über den *Run workflow*-Button im Actions-Tab, unabhängig vom `vX.Y.Z`-Tag-Push oben – er baut `latest`/`latest-cuda` neu und veröffentlicht sie erneut, ausgehend vom aktuellen Stand von `master`, ohne dass dafür ein Release geschnitten werden muss. Er erzeugt keinen versionierten Tag: Die `type=semver`-Muster von `docker/metadata-action` feuern nur bei einem echten `vX.Y.Z`-Git-Tag, sodass ein manueller Lauf ausschließlich `latest`/`latest-cuda` verschiebt.

**Beide veröffentlichten Images sind ausschließlich `linux/amd64` (x86_64).** Das deckt x86-NAS-Hardware ab (Synology Plus/x86, UGREEN, UnifyDrive und alles, was Coolify, Portainer oder ein gewöhnliches Docker auf einer Intel-/AMD-CPU betreibt). Es gibt kein `arm64`-Image: Das Cross-Compilieren eines mehrere Gigabyte großen ML-Stacks unter QEMU kostet Stunden pro Tag, und die CUDA-Variante ist ohnehin nur für x86 verfügbar. Bauen Sie es auf einem ARM-NAS oder einem Raspberry Pi stattdessen lokal mit `docker compose build`, statt es zu ziehen – `docker compose up` behält `build: .` unterhalb des Schlüssels `image:` genau für diesen Fall bei.

> **Nur bei der ersten Veröffentlichung:** Ein neues GHCR-Paket ist standardmäßig **privat**. Nach dem ersten Lauf des `docker-publish`-Workflows muss ein Owner `ghcr.io/ncoevoet/facet` auf **öffentlich** umstellen (Paket-Einstellungen → Change visibility) – andernfalls schlägt `docker compose up` bei einem frischen Klon mit einem 401-Fehler beim Pull fehl. Dieser Wechsel ist für `ghcr.io/ncoevoet/facet` bereits erfolgt – `:latest` (der schlanke CPU-Build, ~3,3 GB) und `:latest-cuda` lassen sich heute beide anonym ziehen; bisher existieren nur diese beiden Tags, versionierte Tags (`:1.7.2`, …) erscheinen erst beim ersten Push eines `vX.Y.Z`-Tags.

`scoring_config.json` wird als Volume eingehängt (nicht ins Image eingebacken), sodass Sie es auf dem Host bearbeiten und neu starten können. Der Datenbankpfad wird durch `DB_PATH` festgelegt (Standard `/app/data/photo_scores_pro.db`). Modell-Caches bleiben unter `./model-cache/` erhalten, sodass sie Neustarts überdauern.

Für ein reines Viewer-NAS, bei dem das Image klein bleiben muss (kein CUDA), erstellen Sie stattdessen ein schlankes Image. Beachten Sie, dass der CI-Schutz verlangt, dass jede `COPY`-Quelle von Git verfolgt wird, sodass der Build-Kontext die aufgeführten Dateien enthalten muss:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow
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

## Windows (WSL2) mit einer NVIDIA-GPU

Führen Sie den vollständigen GPU-Scoring- + Viewer-Stack in Docker unter Windows über WSL2 aus — ohne Docker Desktop. Das hält alles (die Linux-Distribution, ihre Docker-Images und `/var/lib/docker`) auf einem **Datenlaufwerk** (z. B. `D:`), was wichtig ist, wenn auf dem Systemlaufwerk `C:` wenig Platz ist.

**Voraussetzungen:** ein aktueller NVIDIA-Treiber unter Windows (`nvidia-smi` funktioniert an der Windows-Eingabeaufforderung — der Treiber stellt das WSL2-CUDA-Passthrough bereit; Sie installieren **keinen** Treiber innerhalb von WSL).

### 1. WSL2 installieren (Admin, einmalig)

In einer **erhöhten** (als Administrator ausgeführten) PowerShell, danach bei Bedarf neu starten:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Eine Distribution installieren, deren Datenträger auf dem Datenlaufwerk liegt

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` legt die `ext4.vhdx` der Distribution unter `D:\wsl\facet` ab, sodass der Image-Speicher von Docker nicht auf `C:` liegt. `--no-launch` überspringt die interaktive Erstlauf-Abfrage; die folgenden Befehle laufen als `root`, was für eine Maschine mit einem einzigen Verwendungszweck unproblematisch ist.

### 3. systemd aktivieren (für den Docker-Dienst erforderlich)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Docker CE + das NVIDIA Container Toolkit installieren (innerhalb der Distribution)

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

### 5. Facet bauen und ausführen, eine Datei pro Profil

Das Repository auf dem Windows-Laufwerk ist innerhalb von WSL unter `/mnt/d/...` sichtbar. Das Image ist **autark**: Abhängigkeiten sind in `requirements.lock.txt` fixiert (ein getesteter, eingefrorener Versionssatz — siehe „Reproduzierbares, autarkes Image“ weiter unten), und alle Modell-Caches liegen in von Docker verwalteten **benannten Volumes**, sodass der Container niemals die nativen Modell-Caches des Hosts oder gemeinsam genutzten lokalen Zustand liest. Modelle werden beim ersten Start einmal in diese Volumes heruntergeladen und bleiben erhalten.

Wählen Sie das Profil über eine Overlay-Datei pro Profil — ohne jede JSON-Bearbeitung:

```bash
cd /mnt/d/photo-llm
# legacy (CPU-only): CLIP ViT-L-14 + CLIP-MLP aesthetic + CLIP tagging
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d --build
# 8gb (GPU): CLIP + TOPIQ + SAMP-Net + faces + saliency
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d --build
# 16gb (GPU): SigLIP2 + TOPIQ + Qwen3.5-2B tagging + BiRefNet saliency
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d --build

curl -s localhost:5000/health          # -> ok
```

Jedes Overlay setzt `FACET_VRAM_PROFILE` (berücksichtigt von `config/scoring_config.py`, überschreibt `models.vram_profile` in der Konfiguration — ohne jede JSON-Bearbeitung) und reserviert für die GPU-Profile die NVIDIA-GPU. Die GPU-Profile (8gb/16gb/24gb) clustern Gesichter über das eingebaute RAPIDS cuML auf der GPU; das legacy-Profil clustert immer auf der CPU. Das generische `docker-compose.gpu.yml` bleibt für einen einfachen GPU-Lauf mit dem eigenen `vram_profile` der Konfiguration (Standard `auto`) erhalten.

Der erste Start lädt die Modelle des Profils in die benannten Volumes; setzen Sie sie mit `docker compose down -v` zurück.

### Reproduzierbares, autarkes Image

- **Fixierte Versionen.** Das Image wird aus `requirements.lock.txt` gebaut — einem vollständigen `pip freeze` eines validierten Containers, aus dem `torch`/`torchvision` und `nvidia-*` entfernt wurden (das CUDA-Basis-Image liefert diese bereits). Das verhindert stille Drift zu ungetesteten Releases. (Beispiel, wovor dies schützt: transformers 5.3+ hat das Vision-Batching von Qwen3.5 geändert und den VLM-Tagger kaputtgemacht; `kornia`, von BiRefNet benötigt, wird nicht von transformers mitgezogen und muss fixiert werden.) Nach einem bewussten Upgrade neu erzeugen: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **GPU-Gesichts-Clusterbildung eingebaut.** RAPIDS cuML (`cuml-cu12`) ist im Image enthalten, sodass die GPU-Profile (8gb/16gb/24gb) Gesichter auf der GPU clustern (HDBSCAN über `face_clustering.use_gpu="auto"`); das legacy-Profil — und jeder Host ohne CUDA-Gerät — clustert immer auf der CPU. cuML ist die mit Abstand größte Abhängigkeit (~5,75 GB; siehe die Größenaufschlüsselung unten).
- **Keine Host-Kopplung.** Modell-Caches sind benannte Volumes, keine Host-Bind-Mounts; der Container läuft ohne erhöhte Rechte (der Standard-Entrypoint wechselt zum Benutzer `facet`).
- **Schlanker Build-Kontext.** `.dockerignore` schließt lokalen Bulk-Inhalt aus (`conda/`, Beispieldatensätze, `*.db`, Caches, Entwicklungs-Artefakte) — halten Sie neue große lokale Verzeichnisse aus dem Kontext heraus, indem Sie sie dort ergänzen.

### Image-Größe und Modell-Downloads

Zwei Varianten werden aus demselben `Dockerfile` veröffentlicht — **keine enthält Modellgewichte**:

| Image | Gemessene Größe | Basis |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | ~3,3 GB | `python:3.12-slim` + CPU-Wheel-PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | ~21 GB | CUDA-PyTorch + RAPIDS cuML |

**CPU-Image** — die für die meisten Nutzer maßgebliche Größe, dominiert vom ML-Abhängigkeits-Stack und nicht von PyTorch selbst:

| Layer | Größe |
|-------|------|
| Python-ML-Abhängigkeiten (opencv, transformers, insightface, pyiqa, scipy, hdbscan, …) | ~1,9 GB |
| PyTorch + torchvision (CPU-Wheels) | ~960 MB |
| System-Bibliotheken (`libgl1`, `libglib2.0-0`, `exiftool`, `gosu`) | ~288 MB |
| Basis-OS (`python:3.12-slim`) + Anwendungscode | ~150 MB |

**CUDA-Image** — unverändert gegenüber dem einzigen Image, das dieses Repository zuvor veröffentlicht hat, weiterhin vom GPU-Stack dominiert:

| Layer | Größe |
|-------|------|
| RAPIDS cuML (Gesichts-Clusterbildung auf der GPU) | ~5,75 GB |
| CUDA-Laufzeitbibliotheken (`nvidia-*`) | ~3,7 GB |
| PyTorch + Triton | ~1,9 GB |
| Python-ML-Abhängigkeiten (transformers, pyiqa, insightface, …) | ~1,9 GB |
| Basis-OS + conda | ~2-3 GB |

Modellgewichte werden **beim ersten Start heruntergeladen**, in die benannten Volumes (`facet-hf-cache`, `facet-insightface`, `facet-pretrained`) — nie in das Image —, sodass die Größe auf der Festplatte vom aktiven Profil abhängt:

| Modell | Größe | Profile |
|-------|------|----------|
| SigLIP 2 NaFlex SO400M (Embeddings) | ~4,3 GB | 16gb / 24gb |
| Qwen3.5-2B (Verschlagwortung) | ~4,2 GB | 16gb |
| Qwen3.5-4B (Verschlagwortung) | ~8 GB | 24gb |
| Qwen2-VL-2B (Komposition) | ~4,2 GB | 24gb |
| CLIP ViT-L-14 (Embeddings + Verschlagwortung) | ~1,6 GB | legacy / 8gb |
| BiRefNet (Saliency) | ~424 MB | alle |
| InsightFace buffalo_l (Gesichter) | ~600 MB | alle |
| SAMP-Net (Komposition) | ~175 MB | alle |

**Download-Gesamtsumme beim ersten Start pro Profil:** legacy / 8gb ~3-4 GB, 16gb ~10-11 GB, 24gb ~18 GB. Planen Sie Speicherplatz für das Image **plus** diese Volumes ein; `docker compose down -v` löscht die Volumes und erzwingt beim nächsten Start einen erneuten Download.

## Generischer Linux-Server

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Oder verwenden Sie den Wrapper (Standard ist 1 Worker; übergeben Sie `--workers N` für mehr):

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

HTTPS hinzufügen:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Systemd-Dienst

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

### Caddy (automatisches HTTPS)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Arbeitsablauf

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

Führen Sie nach jeder Bewertungssitzung den Export und `rsync` erneut aus, um die Datenbank auf dem Server zu aktualisieren. Bei Servern mit viel Speicher können Sie die vollständige `photo_scores_pro.db` direkt synchronisieren, statt zu exportieren.

## Mehrbenutzer-Einrichtung

Um jedem Benutzer einen privaten Satz von Fotoverzeichnissen zu geben, fügen Sie einen Abschnitt `users` zu `scoring_config.json` hinzu. Siehe [Konfiguration](CONFIGURATION.md#users) für die vollständige Referenz.

### Schnellstart

```bash
# Auf der Bewertungsmaschine Benutzer hinzufügen
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Bearbeiten Sie dann `scoring_config.json`:

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

Verzeichnispfade müssen mit den in der Datenbank gespeicherten Fotopfaden übereinstimmen. Wenn Sie `viewer.path_mapping` verwenden, sollten die Verzeichnisse die **zugeordneten** Pfade verwenden (wie sie auf dem Viewer-Host erscheinen).

### Vorhandene Bewertungen migrieren

Wenn Sie Bewertungen im Einzelbenutzermodus hatten, migrieren Sie diese zu einem Benutzer:

```bash
python database.py --migrate-user-preferences --user alice
```

### Scan-Schaltfläche

Um dem Superadmin zu erlauben, Fotoscans über die Viewer-Benutzeroberfläche auszulösen (nur sinnvoll, wenn der Viewer auf der GPU-Maschine läuft):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Kontinuierliche Backups mit Litestream

Die SQLite-Datenbank kann auf zehntausende Gigabyte anwachsen (`photo_scores_pro.db` erreicht ~14 GB nach der Bewertung von über 20.000 Fotos), und ein erneuter Scan kostet GPU-Zeit. [Litestream](https://litestream.io/) streamt das WAL kontinuierlich zu S3, B2, GCS, SFTP oder einer anderen lokalen Festplatte, mit Point-in-Time-Wiederherstellung bis auf wenige Sekunden genau.

Facet bündelt Litestream nicht. Installieren Sie es einmal auf dem Host, der den Viewer/die Bewertung ausführt; es läuft als Sidecar-Prozess, transparent für die Anwendung.

Facet verwendet bereits den WAL-Modus (`db/connection.py:apply_pragmas`), und der periodische Checkpoint-Thread (standardmäßig alle 30 Min., konfigurierbar über `performance.wal_checkpoint_minutes`) hält das WAL begrenzt. Lesevorgänge bleiben während der Replikation unblockiert.

### Minimale Litestream-Konfiguration

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

### Systemd-Unit

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

`litestream.env` enthält die AWS-/B2-Anmeldedaten, damit sie aus dem YAML herausgehalten werden.

### Wiederherstellungsübung

Üben Sie dies, bevor Sie es benötigen:

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

### Kosten-Richtwert

Für die 14-GB-Datenbank mit ~50 MB/Tag WAL-Aufkommen während aktiver Bewertung können Sie erwarten:
- ~0,30 $/Monat für Speicher auf S3 Standard
- ~0,05 $/Monat für PUT-Operationen
Vernachlässigbar im Vergleich zu einem erneuten Scan: ~50 GPU-Stunden auf einer 16-GB-RTX.
