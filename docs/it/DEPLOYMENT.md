# Guida al deployment

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · **Italiano** · [Español](../es/DEPLOYMENT.md)

Esegui il viewer di Facet su un server remoto o un NAS.

## Panoramica

Facet ha due carichi di lavoro:

| Componente | Hardware | Scopo |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24GB VRAM) o CPU (8GB+ RAM) | Analizza e valuta le foto |
| **Viewer** (`viewer.py`) | Qualsiasi macchina (poche risorse) | Serve la galleria web |

Solo il viewer deve essere eseguito sul server. Esegui lo scoring su una workstation, poi sincronizza il database.

## Mappatura dei percorsi

Quando la macchina di scoring e il server viewer accedono alle foto da punti di mount diversi, configura `viewer.path_mapping` in `scoring_config.json` per tradurre i percorsi del database in percorsi del disco locale.

**Esempio:** foto valutate su Windows tramite UNC/NFS, servite da un NAS Linux:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Usa le **barre in avanti** nelle chiavi di configurazione per leggibilità — le barre rovesciate vengono normalizzate automaticamente. Questo mappa i percorsi del DB come `\\NAS\share\Photos\2024\IMG_001.jpg` a `/volume1/Photos/2024/IMG_001.jpg`.

Sono supportate più mappature (vince la prima corrispondenza):

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

**Come funziona:**
- Il database memorizza i percorsi di scansione originali (es. `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Le miniature sono memorizzate come BLOB nel database, quindi la navigazione non richiede accesso al disco
- La mappatura dei percorsi si applica ogni volta che il viewer apre un file originale: download, visualizzazione a piena risoluzione, didascalie e critica
- Sono supportati sia i percorsi UNC (`\\server\share`) che le lettere di unità (`Z:\`)
- Vince il primo prefisso corrispondente

## Compilazione del client Angular

Il server FastAPI serve la SPA precompilata da `client/dist/client/browser/`. Compilala prima del deployment:

```bash
cd client && npm install && npx ng build && cd ..
```

Questo richiede Node.js 20+ solo al momento della compilazione. I file compilati sono asset statici — Node.js non è necessario sul server in fase di esecuzione.

## NAS Synology (DS420j / serie J)

La serie J ha una CPU ARM, 1GB di RAM e nessun supporto per Docker. Il viewer viene eseguito direttamente con Python.

### Prerequisiti

1. **Abilita SSH:** DSM > Pannello di controllo > Terminale e SNMP > Abilita SSH
2. **Installa Python3:** Centro pacchetti DSM, oppure via SSH:
   ```bash
   # Verifica la disponibilità
   python3 --version
   pip3 --version
   ```

### Installazione

```bash
ssh admin@your-synology-ip

# Crea la directory
mkdir -p /volume1/facet

# Installa le dipendenze (solo viewer)
pip3 install fastapi uvicorn pyjwt pillow
```

### Esporta il database leggero

Sulla tua workstation di scoring, esporta un database ridotto per il deployment sul NAS:

```bash
python database.py --export-viewer-db
```

Questo crea `photo_scores_viewer.db`, che:
- Rimuove gli embedding CLIP, i dati dell'istogramma e gli embedding dei volti
- Riduce le miniature da 640px a 320px
- Riduce tipicamente un database di 14GB a ~4-5GB

Le esportazioni sono incrementali: se `photo_scores_viewer.db` esiste già, vengono sincronizzate solo le foto nuove e modificate. Usa `--force-export` per una ricostruzione completa:

```bash
python database.py --export-viewer-db --force-export
```

La funzione "Trova simili" non funzionerà sul database esportato (gli embedding CLIP vengono rimossi). Per questo, usa la macchina di scoring.

### Sincronizza i file

Sulla macchina di scoring, compila prima il client Angular:

```bash
cd client && npm install && npx ng build && cd ..
```

Poi sincronizza il viewer e il database esportato sul NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

Il viewer apre `photo_scores_pro.db` per impostazione predefinita (sovrascrivibile con la variabile d'ambiente `DB_PATH`). Sul NAS, imposta `DB_PATH=/volume1/facet/photo_scores_viewer.db` oppure crea un collegamento simbolico:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Le foto originali devono essere accessibili sul NAS al percorso configurato in `path_mapping` affinché i download funzionino.

### Configurazione a bassa memoria

Aggiungi `viewer.performance` a `scoring_config.json` sul NAS per ridurre l'uso della memoria:

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

Questo sovrascrive le impostazioni globali di `performance` (che sono ottimizzate per lo scoring) con valori adatti a 1GB di RAM. Vedi [Configurazione](CONFIGURATION.md#viewer-performance) per i dettagli.

### Esecuzione

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Produzione (1 worker per 1GB di RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Accedi su `http://your-synology-ip:5000`

### Avvio automatico

DSM > Pannello di controllo > Utilità di pianificazione > Crea > Attività attivata > Script definito dall'utente:

- **Evento:** Avvio
- **Utente:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Usa il reverse proxy integrato di Synology:

DSM > Pannello di controllo > Portale di accesso > Avanzate > Reverse Proxy:

| Origine | Destinazione |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Abbinalo a un certificato Let's Encrypt da DSM > Pannello di controllo > Sicurezza > Certificato.

## NAS Synology (serie Plus / x86)

I NAS della serie Plus supportano Docker (Container Manager).

Il repository include un `Dockerfile`, un `docker-compose.yml` e un `docker-compose.gpu.yml` nella root. L'immagine racchiude lo stack completo di scoring + viewer su una base CUDA PyTorch, compila il client Angular ed espone la porta 5000. Il viewer viene eseguito in modalità CPU per impostazione predefinita; l'override GPU è opzionale.

```bash
# Solo viewer (CPU)
docker compose up -d

# Con GPU NVIDIA per lo scoring (richiede l'NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`scoring_config.json` viene montato come volume (non incorporato nell'immagine), quindi modificalo sull'host e riavvia. Il percorso del database è impostato da `DB_PATH` (predefinito `/app/data/photo_scores_pro.db`). Le cache dei modelli persistono in `./model-cache/` in modo da sopravvivere ai riavvii.

Per un NAS solo viewer in cui l'immagine deve restare piccola (senza CUDA), compila invece un'immagine snella. Nota che la protezione CI richiede che ogni sorgente `COPY` sia tracciata da git, quindi il contesto di build deve includere i file elencati:

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

## Server Linux generico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Oppure usa il wrapper (predefinito 1 worker; passa `--workers N` per averne di più):

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

Aggiungi HTTPS:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Servizio systemd

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

### Caddy (HTTPS automatico)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Flusso di lavoro

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

Riesegui l'esportazione e `rsync` dopo ogni sessione di scoring per aggiornare il database sul server. Per i server con molta memoria, puoi sincronizzare direttamente il `photo_scores_pro.db` completo invece di esportarlo.

## Configurazione multi-utente

Per dare a ogni utente un insieme privato di directory di foto, aggiungi una sezione `users` a `scoring_config.json`. Vedi [Configurazione](CONFIGURATION.md#users) per il riferimento completo.

### Avvio rapido

```bash
# Sulla macchina di scoring, aggiungi gli utenti
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Poi modifica `scoring_config.json`:

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

I percorsi delle directory devono corrispondere ai percorsi delle foto memorizzati nel database. Se usi `viewer.path_mapping`, le directory dovrebbero usare i percorsi **mappati** (come appaiono sull'host del viewer).

### Migrazione delle valutazioni esistenti

Se avevi valutazioni in modalità a utente singolo, migrale a un utente:

```bash
python database.py --migrate-user-preferences --user alice
```

### Pulsante di scansione

Per consentire al superadmin di avviare le scansioni delle foto dall'interfaccia del viewer (utile solo quando il viewer è in esecuzione sulla macchina GPU):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Backup continui con Litestream

Il database SQLite può crescere fino a decine di gigabyte (`photo_scores_pro.db` raggiunge ~14 GB dopo lo scoring di oltre 20k foto) e una nuova scansione costa tempo GPU. [Litestream](https://litestream.io/) trasmette il WAL su S3, B2, GCS, SFTP o un altro disco locale in modo continuo, con ripristino point-in-time fino a pochi secondi.

Facet non include Litestream. Installalo una sola volta sull'host che esegue il viewer/scoring; viene eseguito come processo sidecar, trasparente all'applicazione.

Facet usa già la modalità WAL (`db/connection.py:apply_pragmas`) e il thread di checkpoint periodico (predefinito ogni 30 min, configurabile tramite `performance.wal_checkpoint_minutes`) mantiene il WAL limitato. Le letture restano sbloccate durante la replica.

### Configurazione minima di Litestream

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

### Unità systemd

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

`litestream.env` contiene le credenziali AWS / B2 in modo che restino fuori dal file YAML.

### Esercitazione di ripristino

Esercitati prima di averne bisogno:

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

### Stima dei costi

Per il DB da 14 GB con ~50 MB/giorno di rotazione del WAL durante lo scoring attivo, aspettati:
- ~$0,30/mese per lo storage su S3 Standard
- ~$0,05/mese per le operazioni PUT
Trascurabile rispetto a una nuova scansione: ~50 ore-GPU su una RTX da 16 GB.
