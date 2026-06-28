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

```bash
# Nur Viewer (CPU)
docker compose up -d

# Mit NVIDIA-GPU zur Bewertung (erfordert das NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

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
