# Guida al deployment

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · **Italiano** · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md)

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

### Scaricare (pull) l'immagine pubblicata

`docker-compose.yml` e `docker-compose.gpu.yml` includono una chiave `image:` accanto a `build: .`, quindi `docker compose up` **scarica (pull)** un'immagine pre-costruita da GHCR invece di compilare in locale lo stack CPU da ~3,3 GB (o lo stack CUDA da ~21 GB):

```bash
# Solo viewer (CPU) — pulls ghcr.io/ncoevoet/facet:latest
docker compose up -d

# Con GPU NVIDIA per lo scoring (richiede l'NVIDIA Container Toolkit) —
# pulls ghcr.io/ncoevoet/facet:latest-cuda
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`docker compose build` (o `up --build`) continua a compilare a partire dal `Dockerfile` di questo repository per modifiche locali — la chiave `build:` resta sotto `image:` proprio per questo. Anche gli overlay per profilo (`docker-compose.{8gb,16gb,24gb}.yml`) scaricano `:latest-cuda`, poiché tutti e tre sono profili GPU; `docker-compose.legacy.yml` (CPU) scarica l'immagine base `:latest`.

**Due tag pubblicati, un solo Dockerfile.** `ghcr.io/ncoevoet/facet:latest` è una build snella solo CPU (senza runtime CUDA, senza RAPIDS cuML — il clustering dei volti ricade su HDBSCAN su CPU). `ghcr.io/ncoevoet/facet:latest-cuda` è lo stack completo CUDA + cuML descritto in tutto questo documento, identico a un `docker build .` locale. Entrambi provengono dallo stesso `Dockerfile`, parametrizzato tramite argomenti di build (`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`) impostati per variante in `.github/workflows/docker-publish.yml`. I tag versionati (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7-cuda`, …) vengono pubblicati insieme a `latest`/`latest-cuda` a ogni tag git `vX.Y.Z`.

**Pubblicare senza una release.** `.github/workflows/docker-publish.yml` accetta anche un trigger manuale `workflow_dispatch` dal pulsante *Run workflow* della scheda Actions, indipendente dal push del tag `vX.Y.Z` sopra — ricostruisce e ripubblica `latest`/`latest-cuda` a partire dallo stato attuale di `master`, senza dover tagliare una release. Non genera un tag versionato: i pattern `type=semver` di `docker/metadata-action` scattano solo su un vero tag git `vX.Y.Z`, quindi un'esecuzione manuale sposta soltanto `latest`/`latest-cuda`.

**Entrambe le immagini pubblicate sono solo `linux/amd64` (x86_64).** Questo copre l'hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive e qualsiasi cosa esegua Coolify, Portainer o Docker semplice su una CPU Intel/AMD). Non esiste un'immagine `arm64`: la compilazione incrociata di uno stack ML di diversi gigabyte sotto QEMU costa ore per tag, e la variante CUDA è comunque disponibile solo per x86. Su un NAS ARM o un Raspberry Pi, compila in locale con `docker compose build` invece di scaricare l'immagine — `docker compose up` mantiene `build: .` sotto la chiave `image:` proprio per questo caso.

> **Solo alla prima pubblicazione:** un nuovo pacchetto GHCR è **privato** per impostazione predefinita. Dopo la prima esecuzione del workflow `docker-publish`, un proprietario deve impostare `ghcr.io/ncoevoet/facet` su **pubblico** (Impostazioni del pacchetto → Change visibility) — altrimenti il `docker compose up` di un clone appena creato non riesce a scaricare l'immagine e fallisce con un 401. Quel passaggio è già avvenuto per `ghcr.io/ncoevoet/facet` — `:latest` (la build CPU snella, ~3,3 GB) e `:latest-cuda` si scaricano entrambe in modo anonimo già oggi; per ora esistono solo questi due tag, quelli versionati (`:1.7.2`, …) compariranno al primo push di un tag `vX.Y.Z`.

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

## Windows (WSL2) con una GPU NVIDIA

Esegui l'intero stack di scoring + viewer su GPU in Docker su Windows tramite WSL2 — senza Docker Desktop. Questo mantiene tutto (la distribuzione Linux, le sue immagini Docker e `/var/lib/docker`) su un'**unità dati** (es. `D:`), il che conta quando l'unità di sistema `C:` scarseggia di spazio.

**Prerequisiti:** un driver NVIDIA recente su Windows (`nvidia-smi` funziona nel prompt di Windows — il driver fornisce il passthrough CUDA per WSL2; **non** si installa alcun driver dentro WSL).

### 1. Installare WSL2 (admin, una tantum)

In un PowerShell **elevato** (eseguito come amministratore), poi riavvia se richiesto:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Installare una distribuzione il cui disco risiede sull'unità dati

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` colloca il file `ext4.vhdx` della distribuzione sotto `D:\wsl\facet`, in modo che l'archivio immagini di Docker resti fuori da `C:`. `--no-launch` salta il prompt interattivo del primo avvio; i comandi seguenti vengono eseguiti come `root`, il che va bene per una macchina dedicata a un solo scopo.

### 3. Abilitare systemd (necessario per il servizio docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Installare Docker CE + l'NVIDIA Container Toolkit (all'interno della distribuzione)

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

### 5. Compilare ed eseguire Facet, un file per profilo

Il repository sull'unità Windows è visibile dentro WSL in `/mnt/d/...`. L'immagine è **autonoma**: le dipendenze sono fissate in `requirements.lock.txt` (un insieme di versioni testato e congelato — vedi "Immagine riproducibile e autonoma" più sotto) e tutte le cache dei modelli vivono in **volumi con nome** gestiti da Docker, così il container non legge mai le cache dei modelli native dell'host né alcuno stato locale condiviso. I modelli si scaricano una sola volta al primo avvio in quei volumi e persistono.

Scegli il profilo con un file overlay per profilo — senza dover modificare alcun JSON:

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

Ogni overlay imposta `FACET_VRAM_PROFILE` (rispettato da `config/scoring_config.py`, che prevale su `models.vram_profile` nella configurazione — senza modificare alcun JSON) e, per i profili GPU, riserva la GPU NVIDIA. I profili GPU (8gb/16gb/24gb) raggruppano i volti sulla GPU tramite RAPIDS cuML integrato; il profilo legacy raggruppa sempre su CPU. Il `docker-compose.gpu.yml` generico resta disponibile per un'esecuzione GPU semplice che usa il `vram_profile` proprio della configurazione (predefinito `auto`).

Il primo avvio scarica i modelli del profilo nei volumi con nome; reimpostali con `docker compose down -v`.

### Immagine riproducibile e autonoma

- **Versioni fissate.** L'immagine si compila a partire da `requirements.lock.txt` — un `pip freeze` completo di un container validato con `torch`/`torchvision` e `nvidia-*` rimossi (l'immagine base CUDA li fornisce già). Questo previene la deriva silenziosa verso release non testate. (Esempio di cosa previene: transformers 5.3 ha cambiato il batching della visione di Qwen3.5 e rotto il tagger VLM fino all'arrivo del fix di padding; `kornia`, richiesto da BiRefNet, non viene trascinato da transformers e va fissato.) Rigenera dopo un aggiornamento intenzionale: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Clustering dei volti su GPU integrato.** RAPIDS cuML (`cuml-cu12`) è incluso nell'immagine, quindi i profili GPU (8gb/16gb/24gb) raggruppano i volti sulla GPU (HDBSCAN via `face_clustering.use_gpu="auto"`); il profilo legacy — e qualsiasi host senza dispositivo CUDA — raggruppa sempre su CPU. cuML è di gran lunga la dipendenza più grande (~5,75 GB; vedi la ripartizione delle dimensioni più sotto).
- **Nessun accoppiamento con l'host.** Le cache dei modelli sono volumi con nome, non bind mount dell'host; il container viene eseguito senza privilegi (l'entrypoint predefinito passa all'utente `facet`).
- **Contesto di build snello.** `.dockerignore` esclude i contenuti voluminosi solo locali (`conda/`, dataset di esempio, `*.db`, cache, artefatti di sviluppo) — tieni le nuove directory locali di grandi dimensioni fuori dal contesto aggiungendole lì.

### Dimensione dell'immagine e download dei modelli

Due varianti vengono pubblicate dallo stesso `Dockerfile` — **nessuna delle due contiene i pesi dei modelli**:

| Immagine | Dimensione misurata | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | ~3,3 GB | `python:3.12-slim` + PyTorch in wheel CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | ~21 GB | PyTorch CUDA + RAPIDS cuML |

**Immagine CPU** — la dimensione di riferimento per la maggior parte degli utenti, dominata dallo stack di dipendenze ML più che da PyTorch stesso:

| Livello | Dimensione |
|-------|------|
| Dipendenze ML Python (opencv, transformers, insightface, pyiqa, scipy, hdbscan, …) | ~1,9 GB |
| PyTorch + torchvision (wheel CPU) | ~960 MB |
| Librerie di sistema (`libgl1`, `libglib2.0-0`, `exiftool`, `gosu`) | ~288 MB |
| OS di base (`python:3.12-slim`) + codice dell'app | ~150 MB |

**Immagine CUDA** — invariata rispetto all'unica immagine pubblicata in precedenza da questo repository, ancora dominata dallo stack GPU:

| Livello | Dimensione |
|-------|------|
| RAPIDS cuML (clustering dei volti su GPU) | ~5,75 GB |
| Librerie runtime di CUDA (`nvidia-*`) | ~3,7 GB |
| PyTorch + Triton | ~1,9 GB |
| Dipendenze ML Python (transformers, pyiqa, insightface, …) | ~1,9 GB |
| OS di base + conda | ~2-3 GB |

I pesi dei modelli si **scaricano al primo avvio** nei volumi con nome (`facet-hf-cache`, `facet-insightface`, `facet-pretrained`) — mai nell'immagine —, quindi la dimensione su disco dipende dal profilo attivo:

| Modello | Dimensione | Profili |
|-------|------|----------|
| SigLIP 2 NaFlex SO400M (embeddings) | ~4,3 GB | 16gb / 24gb |
| Qwen3.5-2B (tagging) | ~4,2 GB | 16gb |
| Qwen3.5-4B (tagging) | ~8 GB | 24gb |
| Qwen2-VL-2B (composizione) | ~4,2 GB | 24gb |
| CLIP ViT-L-14 (embeddings + tagging) | ~1,6 GB | legacy / 8gb |
| BiRefNet (salienza) | ~424 MB | tutti |
| InsightFace buffalo_l (volti) | ~600 MB | tutti |
| SAMP-Net (composizione) | ~175 MB | tutti |

**Totale download al primo avvio per profilo:** legacy / 8gb ~3-4 GB, 16gb ~10-11 GB, 24gb ~18 GB. Prevedi spazio su disco per l'immagine **più** questi volumi; `docker compose down -v` elimina i volumi e forza un nuovo download al successivo avvio.

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

### Un solo lavoro sulla libreria alla volta

Una scansione, `--recompute-average`, `--upgrade-db` e un addestramento del ranker personale riscrivono ciascuno l'intero database, quindi Facet ne consente uno solo alla volta: ognuno prende un file di lock in `<db_dir>/.facet_cache/library.lock`, e un secondo lavoro rifiuta di partire indicando quello già in corso.

Questo lock è un lock di file del kernel, quindi esclude i lavori **su una sola macchina**. Quando il database è raggiunto via SMB/CIFS — per esempio una workstation Windows che assegna punteggi a foto su una condivisione NAS —, ogni macchina prende la propria copia del lock e nessuna vede l'altra. Facet rileva il mount e registra un avviso quando prende il lock, ma non può imporre nulla tra macchine: esegui i lavori sulla libreria da una sola macchina alla volta. NFS tra client Linux non è interessato: lì `flock` diventa un lock di record POSIX arbitrato dal server.

## Archiviazione e rotazione del secret

Un unico secret firma ogni sessione di login (JWT) e ogni link della cornice digitale. **Non** è una chiave di `scoring_config.json`: risiede in `.facet_secret` accanto alla configurazione, creato con modo `0600` al primo avvio e ignorato da git.

In passato era la chiave `share_secret` in `scoring_config.json`. Quel file è tracciato da git, quindi il valore generato al primo avvio è stato committato e pubblicato — il secret distribuito da questo progetto è pubblico e va considerato compromesso. Al riavvio successivo Facet sposta ogni `share_secret` residuo nel file del secret, elimina la chiave dalla configurazione e registra un avviso. Un valore che Facet stesso ha pubblicato viene sostituito anziché conservato, disconnettendo tutti di proposito.

| Dove | Come |
|------|------|
| Predefinito | `.facet_secret` accanto a `scoring_config.json`, modo `0600` |
| Container / orchestratore | Variabile d'ambiente `FACET_JWT_SECRET` — letta per prima, mai scritta su disco |
| Rotazione | `python database.py --rotate-secret`, poi riavvia il viewer |

Su Docker `/app` è il layer scrivibile del container: un secret creato lì viene perso quando il container viene ricreato — a ogni aggiornamento dell'immagine tutti vengono disconnessi. Imposta `FACET_JWT_SECRET` in `docker-compose.yml`, oppure monta il file con `- ./.facet_secret:/app/.facet_secret`.

Ruota ogni volta che il secret potrebbe essere stato letto da altri: una configurazione committata in passato, un backup trapelato, un amministratore che lascia il progetto. La rotazione invalida ogni sessione e ogni URL firmato della cornice: gli utenti rifanno il login e i dispositivi kiosk recuperano nuovi link.

Con `--workers > 1` tutti i worker leggono lo stesso file, quindi un JWT firmato da uno è valido per tutti. Includi il file nei backup del database — ripristinare un database senza di esso disconnette tutti.

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
