# Guida al deployment

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · **Italiano** · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md) · [简体中文](../zh/DEPLOYMENT.md)

Esegui il viewer di Facet su un server remoto o un NAS.

> **Nuovo qui?** Questa guida serve a distribuire Facet su altre macchine. Per farlo
> funzionare sul tuo computer, inizia da [Installazione](INSTALLATION.md).

## Panoramica

Facet ha due carichi di lavoro:

| Componente | Hardware | Scopo |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24GB VRAM) o CPU (8GB minimo di RAM, 12GB consigliato; di più per `12gb`/`16gb`/`24gb`, vedi [Limiti di memoria del container](#limiti-di-memoria-del-container)) | Analizza e valuta le foto |
| **Viewer** (`viewer.py`) | Qualsiasi macchina (poche risorse) | Serve la galleria web |

Solo il viewer deve essere eseguito sul server. Esegui lo scoring su una workstation, poi sincronizza il database.

> **Attenzione:** finché `viewer.password` è vuoto (valore predefinito), chiunque raggiunga la
> porta del viewer può sfogliare l'intera libreria e scaricare gli originali. Imposta
> `viewer.password` prima di aprire la porta oltre la macchina; vedi
> [Modalità utente singolo](VIEWER.md#modalità-utente-singolo-predefinita).

In un'installazione aperta (senza `viewer.password`), i token dell'assistente (**Collega un assistente**)
si gestiscono solo dal computer su cui gira Facet. Dietro Docker o un reverse proxy, imposta
`viewer.password`, oppure esegui la richiesta sull'host
(`docker compose exec facet python -c "import urllib.request ..."`). Un reverse proxy deve
inviare `X-Forwarded-For` o `Forwarded`, altrimenti viene trattato come la macchina locale.

## Mappatura dei percorsi

Quando la macchina di scoring e il viewer vedono le foto sotto percorsi diversi, imposta
`viewer.path_mapping` in `scoring_config.json` per tradurre i percorsi del database in percorsi locali.

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

Questo associa `\\NAS\share\Photos\2024\IMG_001.jpg` a `/volume1/Photos/2024/IMG_001.jpg`.
Usa gli slash nelle chiavi; i backslash vengono normalizzati.

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

- Il database conserva i percorsi originali della scansione (ad es. `\\NAS\share\Photos\2024\IMG_001.jpg`).
- Le miniature stanno nel database, quindi la navigazione non richiede accesso al disco.
- La mappatura si applica ogni volta che il viewer apre un originale: download, vista a
  piena risoluzione, didascalie e critica.
- Funzionano sia i percorsi UNC (`\\server\share`) sia le lettere di unità (`Z:\`).

## Semantica dei percorsi nel container

In Docker/Podman, ogni cartella che digiti nel viewer è un percorso **dentro il container**.
Vale per la destinazione di "Scarta in cartella", per la destinazione di esportazione di un album e
per `viewer.export.allowed_target_dirs`. Usa il punto di montaggio, mai il percorso dell'host.

**Esempio.** Il `docker-compose.yml` fornito monta le tue foto in `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Per spostare gli scarti in una sottocartella `rejects`, inserisci `/data/photos/rejects`, non
`/home/you/Pictures` né `D:\Photos`, che il container non vede.

Per scrivere fuori dall'albero delle foto, monta prima la destinazione, poi indica il suo percorso nel container in
`viewer.export.allowed_target_dirs`:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # volume aggiuntivo per l'output di selezione/esportazione
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

Una destinazione fuori da ogni radice consentita viene rifiutata, dopo aver risolto symlink e `..`.
Vedi [Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto).

**Questo rifiuto non è un problema di permessi.** Avviene prima che qualsiasi file venga toccato. Una
discordanza di uid tra l'utente `facet` del container e il tuo account sull'host è un guasto diverso:
si verifica durante la copia/lo spostamento e viene registrato con l'errore del sistema operativo.

### Dove va il cestino di un container

Con `viewer.cull.allow_trash` attivo, `trash_rejects` usa `send2trash`. Nella disposizione fornita
(foto montate in bind su `/data/photos`, uid 1000, `HOME=/home/facet`), le foto e
`$HOME` stanno su filesystem diversi, quindi i file cestinati vanno nel cestino proprio del volume delle foto:

- file: `/data/photos/.Trash-1000/files/<nome>`
- metadati: `<nome>.trashinfo` (con `Path=` e `DeletionDate=`) in `/data/photos/.Trash-1000/info/`
- la directory viene creata con modo `0700`

`.Trash-1000` è visibile sull'**host**, quindi un semplice `mv` fuori da `files/` ripristina una foto.
Le nuove scansioni lo saltano finché `scanning.skip_hidden_directories` è true (valore predefinito).

Due eccezioni:

- **Nessun bind mount** per le foto (ad es. `docker run` con le foto dentro il container):
  il cestino va in `~/.local/share/Trash` nel container e va **perso quando il container viene
  rimosso**.
- **Podman rootless**: `.Trash-1000` appartiene al subuid dell'host mappato, non al tuo account;
  il ripristino può richiedere `podman unshare`.

Per scegliere tu la destinazione, usa invece `move_rejects` verso un `target_dir`
([Scarta in cartella](VIEWER.md#scarta-in-cartella)).

### Proprietà del file di configurazione

Facet prende possesso solo di un `/config/scoring_config.json` che ha creato lui stesso; un file esistente
mantiene proprietario e permessi. L'unica eccezione (una configurazione che l'utente `facet` del container non può
leggere) e la ricetta per Podman rootless sono in
[Installazione — Proprietà del file nel container](INSTALLATION.md#proprietà-del-file-nel-container).

Con `group_add` di compose (vedi [Condivisioni foto leggibili solo tramite un gruppo](#condivisioni-foto-leggibili-solo-tramite-un-gruppo-group_add)),
il controllo di leggibilità considera anche quei gruppi, quindi una configurazione leggibile tramite un tale gruppo
viene lasciata com'è. Se il controllo `setpriv` stesso fallisce, il file è trattato come illeggibile.

## Compilazione del client Angular

Il server serve la SPA precompilata da `client/dist/client/browser/`. Compilala prima di
distribuire:

```bash
cd client && npm install && npx ng build && cd ..
```

Richiede Node.js 20+ solo al momento della compilazione, non sul server.

## NAS Synology (DS420j / serie J)

La serie J ha una CPU ARM, 1GB di RAM e nessun Docker. Il viewer viene eseguito direttamente con Python.

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
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Esporta il database leggero

Sulla workstation di scoring, esporta un database più piccolo per il NAS:

```bash
python database.py --export-viewer-db
```

Questo crea `photo_scores_viewer.db`, che:

- elimina gli embedding CLIP, delle didascalie e dei volti;
- conserva l'istogramma per foto (~2 KB ciascuno) per il widget dell'istogramma RGB;
- riduce le miniature da 640px a 320px;
- di solito trasforma un database da 14GB in uno da ~4-5GB.

Le esportazioni sono incrementali: vengono sincronizzate solo le foto nuove e modificate. Per una ricostruzione completa:

```bash
python database.py --export-viewer-db --force-export
```

> **Attenzione:** `--force-export` scarta valutazioni, posizioni e tag manuali impostati nel
> viewer sul NAS. Solo un'esportazione incrementale li conserva.

"Trova simili" non funziona sul database esportato (niente embedding). Usa la macchina di
scoring per questo.

**Tag manuali.** L'esportazione include i [tag manuali](VIEWER.md#tag-manuali)
(`photo_manual_tags`). Un'esportazione incrementale aggiunge solo i tag del database di scoring:

- Un tag rimosso sul NAS ritorna se il database di scoring lo ha ancora.
- Un tag aggiunto sul NAS non viene mai copiato indietro; aggiungilo anche sulla macchina di scoring.
- Un tag rimosso sulla macchina di scoring resta sul NAS fino a `--force-export`.
- Il limite di 50 tag per foto non viene applicato nell'unione, quindi una foto può superarlo.

### Sincronizza i file

Compila prima il client Angular ([Compilazione del client Angular](#compilazione-del-client-angular)),
poi sincronizza sul NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` contiene i valori predefiniti forniti, quindi il NAS funziona con quelli. Per usare il tuo
`scoring_config.json`, aggiungilo all'elenco di `rsync`. Controllalo prima: contiene la password del viewer
e le chiavi API in chiaro.

Il viewer apre `photo_scores_pro.db` per impostazione predefinita (sostituibile con `DB_PATH`). Sul NAS,
imposta `DB_PATH=/volume1/facet/photo_scores_viewer.db` oppure crea un collegamento simbolico:

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Per i download, gli originali devono essere raggiungibili sul NAS al percorso di `path_mapping`.

### Configurazione a bassa memoria

Aggiungi `viewer.performance` a `scoring_config.json` sul NAS:

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

Questo sovrascrive le impostazioni globali di `performance` (ottimizzate per lo scoring) con valori per 1GB
di RAM. Vedi [Configurazione](CONFIGURATION.md#prestazioni-del-viewer).

### Esecuzione

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Produzione (1 worker per 1GB di RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Apri `http://your-synology-ip:5000`.

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

Usa il reverse proxy di Synology: DSM > Pannello di controllo > Portale di accesso > Avanzate > Reverse Proxy:

| Origine | Destinazione |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Aggiungi un certificato Let's Encrypt da DSM > Pannello di controllo > Sicurezza > Certificato.

Per il ponte delle schede degli agenti ([Agenti IA](AGENTS.md)), apri la scheda **Intestazione personalizzata**
della regola e scegli **Crea > WebSocket**. Questo aggiunge le intestazioni `Upgrade` e `Connection`
necessarie a `/api/mcp/bridge`. Se la regola riscrive l'intestazione `Host`, indica la tua origine pubblica in
`viewer.mcp.allowed_origins`.

## NAS Synology (serie Plus / x86)

I NAS della serie Plus supportano Docker (Container Manager).

### Eseguire l'immagine pubblicata

Installa come in [Installazione › Installa con Docker](INSTALLATION.md#installa-con-docker):
`docker compose up -d` su un NAS con sola CPU, oppure il blocco per profilo con una scheda NVIDIA. Le
impostazioni di `.env` e il mount della configurazione sono in
[Installazione › Impostazioni Docker che puoi modificare](INSTALLATION.md#impostazioni-docker-che-puoi-modificare).
Qui sotto c'è solo ciò che cambia su un NAS.

**Le immagini sono solo `linux/amd64` (x86_64).** Questo copre l'hardware NAS x86 (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer o Docker semplice su Intel/AMD). Non esiste
un'immagine `arm64`. Su un NAS ARM o un Raspberry Pi, compila in locale con
`docker compose build`; il file compose mantiene `build: .` sotto la chiave `image:` per questo scopo.

**Prevedi il disco:** l'immagine più i modelli che ogni profilo scarica al primo avvio.

- Immagini, decompresse: CPU ~3,34 GB, `latest-cuda` (`sm_75`-`sm_120`) ~13,1 GB,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13,8 GB ([Dimensione dell'immagine](#dimensione-dellimmagine)).
  `docker pull` trasferisce meno, compresso.
- Modelli: `legacy` 4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB, `24gb` 19,32 GB
  ([Dimensioni dei download](INSTALLATION.md#dimensioni-dei-download)).
- `docker compose down -v` elimina i volumi dei modelli e impone un nuovo download.

**Tag con versione.** `:latest`, `:latest-cuda` e `:latest-cuda-legacy` si spostano a ogni
release. Fissa una versione (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) su un NAS
che non vuoi veder cambiare sotto i piedi. Le varianti si compilano da un solo `Dockerfile` tramite gli
argomenti di build `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` e `REQUIREMENTS_LOCK`, impostati in
`.github/workflows/docker-publish.yml`. Un'esecuzione manuale `workflow_dispatch` di quel workflow
ripubblica `latest` / `latest-cuda` / `latest-cuda-legacy` da `master` senza una release.

**Build commerciale.** Aggiungi `--build-arg FACET_LICENSING=commercial` (compose:
`build.args.FACET_LICENSING: commercial`). Salta il lock con restrizioni (`insightface`,
`pyiqa` e le loro dipendenze) e imposta `FACET_LICENSING_MODE=commercial`. Il valore predefinito
`FACET_LICENSING=default` mantiene il comportamento pubblicato. Il lock con restrizioni segue
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` per il lock legacy). Vedi
[Installazione](INSTALLATION.md#installazione-commerciale-e-pacchetti-con-restrizioni).

Per un'immagine piccola solo per il viewer (senza CUDA), compilane una slim. Ogni sorgente di `COPY` deve essere
tracciato da git, ed è per questo che `scoring_config.json` non viene copiato; senza di esso il container
funziona con i valori predefiniti in `config/`.

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

> **Il ponte delle schede degli agenti richiede un solo worker.** Con più di un worker, una chiamata `ui_*` può raggiungere
> un processo che non conosce la tua scheda e risponde `no_tab`. Usa `--workers 1` se usi
> gli [Agenti IA](AGENTS.md).

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Monta le foto per i download
    restart: always
```

### Condivisioni foto leggibili solo tramite un gruppo (`group_add`)

Su un NAS la condivisione delle foto è spesso leggibile solo tramite un gruppo (su Synology, di solito
`users`, gid 100). Dai al container quel gruppo con `group_add`, usando il gid numerico
da `id <your-user>` sul NAS:

```yaml
services:
  facet:
    group_add:
      - "100"
```

L'entrypoint passa da root a `facet` con `setpriv` e mantiene quei gid. Verifica con
`docker compose exec facet grep Groups /proc/1/status`: elenca `1000` più i tuoi gid.

Alternativa: esegui con `user: "1000:1000"` più `group_add`. L'entrypoint allora non esegue né chown
né il seeding di `/config`, quindi ogni mount deve già essere scrivibile dall'uid 1000.

## Limiti di memoria del container

Facet legge il limite di memoria del container (`memory.max` su cgroup v2,
`memory.limit_in_bytes` su v1) invece della RAM dell'host. In base a quel limite dimensiona quali modelli vengono caricati
insieme, la dimensione del chunk RAM, il caching dei modelli e la decodifica RAW. Le versioni precedenti
(v1.7.2 e prima) ignoravano `mem_limit` e potevano essere uccise dall'OOM
([issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Memoria minima consigliata per profilo

I pesi dei modelli sono solo una parte del picco di memoria: il runtime di torch, le immagini decodificate e le
attivazioni si aggiungono. Considera queste cifre come minimi.

| Profilo VRAM | Pesi dei modelli (totale) | Memoria del container consigliata |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB minimo, 12 GB consigliato (CPU) |
| `16gb` | 22,0 GB | almeno 18 GB (provvisorio) |
| `24gb` | 25,0 GB | almeno 18 GB (provvisorio) |

- **GPU e CPU sono diverse.** Su una GPU i pesi stanno nella VRAM e la RAM contiene soprattutto le immagini
  decodificate: un'esecuzione `8gb` su una RTX 3080 (405 foto, `ram_chunk_size: 12`, `num_workers: 2`) ha raggiunto un picco di
  9,23 GB ed è riuscita con `mem_limit: 12g`. Su
  CPU, tutti i modelli si caricano nella RAM. Dimensiona dalla riga che corrisponde a come lo esegui.
- **8 GB sono un minimo su CPU.** Scansioni di 50 foto con `--memory=8g` completate su `legacy` (picco 7,26 GB) e
  `8gb` (7,56 GB), entro circa mezzo gigabyte dal limite su JPEG da 18-20 MP. Fotogrammi più grandi, decodifica
  RAW o un host occupato richiedono di più, da cui i 12 GB consigliati.
- **`16gb` e `24gb` non sono misurati.** 18 GB è un segnaposto provvisorio.
- **Tieni d'occhio la memoria anonima.** Il MemUsage di `docker stats` e il `memory.current` del cgroup
  contano entrambi la cache di pagine recuperabile, quindi sono fuorvianti.
- **Caching dei modelli.** Con `models.keep_in_ram` su `"auto"`, un modello resta in RAM tra un chunk
  e l'altro solo finché la sua dimensione più `models.ram_cache_reserve_gb` (predefinito 4 GB) è libera. Una
  riserva più piccola mette in cache di più ([Configurazione](CONFIGURATION.md#models)).

Su CPU il profilo `8gb` pianifica sempre gli stessi 5 pass, qualunque sia il limite:
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Imposta il limite in `docker-compose.yml` (o in un file di override):

```yaml
services:
  facet:
    mem_limit: 16g
```

### Il raggruppamento dei pass ha un limite massimo, e nessun minimo

- **Con un limite del container**, ogni pass CPU ottiene il limite meno una riserva di 2 GB, con tetto a
  5 GB. Un limite stretto significa un modello per pass.
- **Senza un limite**, il budget è (RAM di sistema − 1 GB) ÷ 1,6. Un host da 4 GB ottiene 1,9 GB per
  pass, uno da 2 GB 0,6 GB.
- **Un modello più grande del budget** ottiene comunque un pass proprio, con un avviso che lo nomina. Per
  esempio `qwen3_5_4b_tagger` (`24gb`) da solo dà un pass da 8,0 GB.

> **Attenzione:** non dimensionare mai un container al di sotto del modello singolo più grande del tuo profilo.

## Windows (WSL2) con una GPU NVIDIA

Esegui lo stack di scoring GPU e viewer in Docker su Windows tramite WSL2, senza Docker
Desktop. Tutto (la distribuzione, le sue immagini, `/var/lib/docker`) resta su un **disco dati**
(ad es. `D:`), utile quando `C:` ha poco spazio.

**Prerequisiti:** un driver NVIDIA recente su Windows (`nvidia-smi` funziona al prompt di Windows).
**Non** installare un driver dentro WSL.

### 1. Installare WSL2 (admin, una tantum)

In una PowerShell **con privilegi elevati**, poi riavvia se richiesto:

```powershell
wsl --install --no-distribution   # solo la piattaforma WSL2, nessuna distribuzione su C:
```

### 2. Installare una distribuzione il cui disco risiede sull'unità dati

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` mette l'`ext4.vhdx` della distribuzione in `D:\wsl\facet`. `--no-launch` salta la
richiesta dell'utente al primo avvio; i comandi qui sotto girano come `root`.

### 3. Abilitare systemd (necessario per il servizio docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # si applica al prossimo avvio
```

### 4. Installare Docker CE + l'NVIDIA Container Toolkit (all'interno della distribuzione)

```bash
wsl -d facet -u root
# --- dentro la distribuzione ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Repository Docker (ripiega sul codename supportato più recente se il tuo è troppo nuovo):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# Repository del toolkit NVIDIA (indipendente dalla distribuzione):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 non ha il cgroup nvidia
systemctl enable --now docker
# Verifica il passthrough della GPU:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Eseguire Facet

Il repository sul disco Windows si trova in `/mnt/d/...` dentro WSL. Esegui il blocco per la tua scheda
da [Installazione › Installa con Docker](INSTALLATION.md#installa-con-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # o il file della tua scheda
curl -s localhost:5000/health          # -> ok
```

Aggiungi `--build` per compilare dal checkout invece di scaricare. I profili GPU
(`8gb`/`12gb`/`16gb`/`24gb`) eseguono il clustering dei volti sulla GPU tramite RAPIDS cuML incluso; `legacy`
lo esegue su CPU. Il primo avvio scarica i modelli nei volumi con nome; reimpostali con
`docker compose down -v`.

### Immagine riproducibile e autonoma

- **Versioni fissate.** L'immagine si compila da `requirements.lock.txt`, un `pip freeze` di un
  container validato senza `torch`/`torchvision` e `nvidia-*` (li fornisce la base CUDA).
  Anche `kornia`, richiesto da BiRefNet, è fissato lì. Rigenera dopo un aggiornamento
  intenzionale: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Clustering dei volti su GPU incluso.** RAPIDS cuML (`cuml-cu12`, ~5,75 GB) permette ai profili GPU
  di eseguire il clustering sulla GPU (`face_clustering.use_gpu="auto"`). `legacy` e gli host senza CUDA
  eseguono il clustering su CPU.
- **Nessun accoppiamento con l'host.** Le cache dei modelli sono volumi con nome; il container gira come
  utente `facet` senza privilegi.
- **Contesto di build snello.** `.dockerignore` esclude il materiale locale voluminoso (`conda/`, dataset di esempio,
  `*.db`, cache); aggiungi lì le nuove cartelle locali grandi.

### Dimensione dell'immagine

Nessuna immagine contiene i pesi dei modelli; vengono scaricati al primo avvio nei volumi con nome
([totali per profilo](INSTALLATION.md#dimensioni-dei-download)). Prevedi il disco per entrambi.

| Immagine | Su disco (misurato) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + PyTorch con wheel CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, da Turing a Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, da Maxwell a Hopper) + RAPIDS cuML |

"Su disco" è la dimensione decompressa (`docker images`). `docker pull` trasferisce meno; le dimensioni
compresse non sono ancora misurate.

## Server Linux generico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Oppure usa il wrapper (1 worker per impostazione predefinita; `--workers N` per averne di più):

```bash
python viewer.py --production --workers 4
```

Il ponte delle schede degli agenti richiede `--workers 1` (vedi
[Eseguire l'immagine pubblicata](#eseguire-limmagine-pubblicata)).

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

Il ponte delle schede degli agenti (`/api/mcp/bridge`, vedi [Agenti IA](AGENTS.md)) è un WebSocket. Richiede
le intestazioni `Upgrade` e `Connection` del secondo blocco `location` e un solo worker
(`--workers 1`, il valore predefinito); altrimenti gli strumenti agente `ui_*` rispondono `no_tab`.

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

Usa `--workers 1` se usi il ponte delle schede degli agenti.

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

Riesegui l'esportazione e `rsync` dopo ogni sessione di scoring. Su un server con molta
memoria, puoi sincronizzare invece il `photo_scores_pro.db` completo.

### Un solo lavoro sulla libreria alla volta

Una scansione, `--recompute-average`, `--upgrade-db` e un addestramento del ranker riscrivono ciascuno il
database, quindi ne gira uno solo alla volta. Un secondo lavoro rifiuta di partire, nomina quello in corso
ed esce con codice 75 (exit 1 se il file di lock in `<db_dir>/.facet_cache/library.lock` è
inutilizzabile).

> **Attenzione:** questo lock funziona **su una sola macchina**. Su SMB/CIFS (ad es. una
> workstation Windows che esegue lo scoring su una condivisione NAS), ogni macchina ha il proprio lock. Facet registra un
> avviso ma non può impedirlo: esegui i lavori sulla libreria da una macchina alla volta. NFS tra
> client Linux va bene.

### Avvio del viewer e indici della galleria

Il primo avvio dopo un aggiornamento dalla 1.20 costruisce gli indici della galleria mancanti
([dettagli](VIEWER.md#indici-della-galleria-e-cache-dei-conteggi)). Su una libreria da ~130k foto
richiede alcuni minuti e aggiunge circa 130 MB al database.

**Consigliato:** dopo l'aggiornamento, esegui `python database.py` (Docker:
`docker compose exec facet python database.py`) una volta **prima** di avviare il viewer. Anche una
scansione `python facet.py` li costruisce al suo avvio.

Se invece li costruisce il viewer:

- Serve mentre costruisce, ma la galleria è lenta e **i salvataggi (valutazioni, scarti, modifiche
  agli album…) possono essere rifiutati** con il messaggio "libreria occupata, riprova".
- Il log mostra `Creating index ...` e `Created index ... in N s` per ogni indice, poi
  `Gallery indexes ready`. `/health` riporta l'avanzamento come `gallery_indexes` (`state`:
  `building`, `ready`, `deferred`, `failed` o `stopped`; `done` su `total`).
- Fermare il viewer mantiene gli indici finiti; il prossimo avvio riprende.
- Se è in corso una scansione o un altro lavoro sulla libreria, il viewer serve senza gli indici e
  registra un avviso. Riavvialo quando il lavoro termina, oppure esegui `python database.py`.
- Se `.facet_cache/library.lock` accanto al database è inutilizzabile (permessi, mount in sola lettura),
  il viewer non costruisce. Correggi il percorso e riavvia.
- Con `--workers N`, un worker costruisce e gli altri servono.
- In Docker, il `start_period` di 30 s dell'healthcheck non richiede modifiche: `/health` risponde durante la costruzione.

Su SQLite precedente alla 3.48.0 (l'immagine CPU include la 3.46.1), il rilevamento dei panorami non può leggere
dal solo nuovo indice; la sua velocità lì non è stata misurata. Su un SQLite diverso dalla 3.51,
le foto con timestamp identici possono essere raggruppate in modo diverso al primo passaggio delle raffiche dopo
l'aggiornamento (vedi il CHANGELOG).

> **Attenzione:** copia o sostituisci il database solo dopo aver fermato il viewer. Mentre gira,
> le modifiche recenti stanno nei file `-wal` e `-shm`, non nel solo `.db`; uno spegnimento pulito
> le unisce (anche con `performance.wal_checkpoint_minutes: 0`). Su Windows il file
> non può essere sostituito affatto mentre il viewer lo tiene aperto.

## Archiviazione e rotazione del secret

Un unico secret firma ogni sessione di login (JWT) e ogni link della cornice digitale. Risiede in
`.facet_secret` accanto alla configurazione (modo `0600`, ignorato da git), non in `scoring_config.json`.

Le versioni precedenti lo memorizzavano come `share_secret` nella configurazione, e il valore fornito era pubblico.
All'avvio, Facet sposta un `share_secret` residuo nel file del secret e rimuove la chiave.
Un valore che Facet stesso ha pubblicato viene sostituito, il che disconnette tutti una volta.

| Dove | Come |
|-------|-----|
| Predefinito | `.facet_secret` accanto a `scoring_config.json`, modo `0600` |
| Container / orchestratore | Variabile d'ambiente `FACET_JWT_SECRET` — letta per prima, mai scritta su disco |
| Rotazione | `python database.py --rotate-secret`, poi riavvia il viewer |

- **Docker:** `/app` è il layer scrivibile del container, quindi un secret creato lì va perso
  alla ricreazione e tutti vengono disconnessi a ogni aggiornamento dell'immagine. Imposta `FACET_JWT_SECRET` in
  `docker-compose.yml`, oppure monta in bind `- ./.facet_secret:/app/.facet_secret`.
- **Ruota** ogni volta che il secret potrebbe essere trapelato (una configurazione committata, un backup trapelato, un
  amministratore che se ne va). Tutti rifanno il login e i dispositivi kiosk recuperano i link della cornice.
- **Più worker:** crea il secret prima del primo avvio con `--workers > 1` (esegui
  `python database.py --rotate-secret` una volta, avvia una volta con `--workers 1`, oppure imposta
  `FACET_JWT_SECRET`). Altrimenti ogni worker ne crea uno proprio e le sessioni si rompono fino al riavvio.
- **Directory di installazione in sola lettura:** il server funziona con un secret in memoria, quindi le sessioni muoiono
  a ogni riavvio. Imposta `FACET_JWT_SECRET`.
- **Includilo nei backup** del database; ripristinare un database senza di esso disconnette tutti.

## Configurazione multi-utente

Per dare a ogni utente un insieme privato di directory di foto, aggiungi una sezione `users` a
`scoring_config.json`. Vedi [Configurazione](CONFIGURATION.md#users).

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

I percorsi delle directory devono corrispondere ai percorsi delle foto nel database. Con `viewer.path_mapping`,
usa i percorsi **mappati** (come visti sull'host del viewer).

### Migrazione delle valutazioni esistenti

Per spostare le valutazioni dell'utente singolo a un utente:

```bash
python database.py --migrate-user-preferences --user alice
```

### Pulsante di scansione

Per consentire al viewer di avviare le scansioni (il superadmin in modalità multiutente; una sessione di modifica su
un'installazione a utente singolo con `viewer.edition_password` non vuota), abilitalo. La scansione gira sulla
macchina del viewer e non richiede GPU ([Nessuna scheda grafica](INSTALLATION.md#nessuna-scheda-grafica)):

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

Il database può crescere fino a decine di gigabyte (~14 GB dopo oltre 20k foto), e una nuova scansione
costa tempo di GPU. [Litestream](https://litestream.io/) trasmette continuamente le modifiche a S3,
B2, GCS, SFTP o un altro disco, con ripristino point-in-time fino a pochi secondi.

Facet non include Litestream. Installalo sull'host che esegue Facet; gira affiancato
senza modifiche a Facet. Il checkpoint periodico del WAL di Facet (ogni 30 min per impostazione predefinita,
`performance.wal_checkpoint_minutes`; `0` lo disattiva, uno spegnimento pulito del viewer esegue comunque il
checkpoint) mantiene piccolo il WAL.

### Configurazione minima di Litestream

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Storage a oggetti economico; sostituisci con il bucket che preferisci.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # conserva 3 giorni di storico point-in-time
        snapshot-interval: 24h        # snapshot completo una volta al giorno
        validation-interval: 6h       # rileva presto la corruzione
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

`litestream.env` contiene le credenziali AWS / B2, fuori dal YAML.

### Esercitazione di ripristino

Esercitati prima di averne bisogno:

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# verifica
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# sostituisci
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Stima dei costi

Per un database da 14 GB con ~50 MB/giorno di rotazione del WAL durante lo scoring attivo:

- ~$0,30/mese per lo storage su S3 Standard
- ~$0,05/mese per le operazioni PUT

Trascurabile rispetto a una nuova scansione: ~50 ore-GPU su una RTX da 16 GB.
