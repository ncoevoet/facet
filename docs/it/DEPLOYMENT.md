# Guida al deployment

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · **Italiano** · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md)

Esegui il viewer di Facet su un server remoto o un NAS.

> **Nuovo qui?** Questa guida serve a distribuire Facet su altre macchine. Per farlo
> funzionare sul tuo computer, inizia da [Installazione](INSTALLATION.md).

## Panoramica

Facet ha due carichi di lavoro:

| Componente | Hardware | Scopo |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24GB VRAM) o CPU (8GB minimo di RAM, 12GB consigliato, di più per i profili `16gb`/`24gb` — vedi [Limiti di memoria del container](#limiti-di-memoria-del-container)) | Analizza e valuta le foto |
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

## Semantica dei percorsi nel container

Qualsiasi cosa digiti in un campo cartella nel viewer — una destinazione "Scarta in cartella", la destinazione di esportazione copia/symlink di un album, oppure `viewer.export.allowed_target_dirs` in `scoring_config.json` — viene risolta dal processo Facet stesso. **Su Docker/Podman quel processo gira dentro il container**, quindi ogni percorso è il percorso che *il container* vede: il punto di montaggio, mai il percorso lato host.

**Esempio.** Il `docker-compose.yml` fornito monta la tua cartella fotografica su `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Per scartare gli elementi rifiutati in una sottocartella `rejects`, inserisci `/data/photos/rejects` nella finestra di dialogo — mai il percorso host (`/home/tu/Immagini`, `D:\Foto`, …), che il container non può vedere affatto. Lo stesso vale per `viewer.export.allowed_target_dirs`: elenca il percorso lato container.

Per scrivere altrove rispetto all'albero fotografico scansionato — ad esempio un volume di esportazione separato — montalo prima nel container, quindi aggiungi il suo percorso lato container a `viewer.export.allowed_target_dirs`:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # volume aggiuntivo per l'output di cull/export
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

Una destinazione che si risolve al di fuori di ogni volume montato viene rifiutata (`403`) — il controllo del target-dir di Facet esegue `os.path.realpath()` sia sulla richiesta *sia* su ogni radice consentita, risolvendo symlink e `..` prima del confronto, quindi un percorso che sembra corretto solo dall'esterno del container (o un symlink che punta fuori da un mount) fallisce comunque il test di contenimento. Vedi [Configurazione — Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto) per il riferimento completo dell'allow-list.

**Questo non è un problema di permessi dell'utente del container.** La UID dell'utente `facet` all'interno del container spesso differisce da quella del tuo account host, e questo può causare un vero e separato problema di permessi del filesystem su un bind mount — ma ciò accade *dopo* che questo controllo del percorso è stato superato, quando la copia/symlink/spostamento viene effettivamente eseguita, e viene registrato lato server con l'errore del sistema operativo sottostante per il file non riuscito. Un `403 target_dir is not an allowed export location` (o un generico "accesso negato" nell'interfaccia) avviene *prima* che qualsiasi file venga toccato e non ha nulla a che fare con le UID.

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
- Rimuove gli embedding CLIP, gli embedding delle didascalie e gli embedding dei volti
- Mantiene l'istogramma per foto (~2 KB ciascuno), letto dal widget istogramma RGB della galleria
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

Questo sovrascrive le impostazioni globali di `performance` (che sono ottimizzate per lo scoring) con valori adatti a 1GB di RAM. Vedi [Configurazione](CONFIGURATION.md#prestazioni-del-viewer) per i dettagli.

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

### Eseguire l'immagine pubblicata

Installa esattamente come in [Installazione › Installa con Docker](INSTALLATION.md#installa-con-docker):
`docker compose up -d` per un NAS solo CPU, oppure il blocco per profilo se la macchina
ha una scheda NVIDIA. Le leve di `.env` e il mount della configurazione sono documentati
in [Installazione › Impostazioni Docker che puoi modificare](INSTALLATION.md#impostazioni-docker-che-puoi-modificare).
Quanto segue è solo ciò che cambia su un NAS.

**Tutte e tre le immagini pubblicate sono solo `linux/amd64` (x86_64).** Questo copre l'hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive e qualsiasi cosa esegua Coolify, Portainer o Docker semplice su una CPU Intel/AMD). Non esiste un'immagine `arm64`: la compilazione incrociata di uno stack ML di diversi gigabyte sotto QEMU costa ore per tag, e le varianti CUDA sono comunque disponibili solo per x86. Su un NAS ARM o un Raspberry Pi, compila in locale con `docker compose build` invece di scaricare l'immagine — `docker compose up` mantiene `build: .` sotto la chiave `image:` proprio per questo caso.

**Prevedi lo spazio su disco.** Decompressa, l'immagine CPU occupa circa 3,34 GB su
disco, l'immagine CUDA (`latest-cuda`, `sm_75`-`sm_120`) circa 13,1 GB, e l'immagine
CUDA legacy (`latest-cuda-legacy`, `sm_50`-`sm_90`) circa 13,8 GB — vedi
[Dimensione dell'immagine](#dimensione-dellimmagine) più sotto per come sono state
misurate; `docker pull` trasferisce meno di così, compresso. Prevedi spazio su
disco per l'immagine **più** i pesi dei modelli scaricati da ogni profilo al primo avvio
(`legacy` 4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB, `24gb` 19,13 GB — tabella
completa in [Installazione › Dimensioni dei download](INSTALLATION.md#dimensioni-dei-download)).
`docker compose down -v` elimina i volumi dei modelli e forza un nuovo download.

**Tag versionati.** `:latest`, `:latest-cuda` e `:latest-cuda-legacy` si spostano a ogni release; fissa una versione (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) su un NAS che non vuoi veder cambiare sotto di te. Tutte e tre le varianti si compilano dallo stesso `Dockerfile` tramite gli argomenti di build `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` e `REQUIREMENTS_LOCK`, impostati per variante in `.github/workflows/docker-publish.yml`. Quel workflow accetta anche un'esecuzione manuale `workflow_dispatch`, che ripubblica `latest` / `latest-cuda` / `latest-cuda-legacy` a partire da `master` senza tagliare una release né generare un tag versionato.

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

## Limiti di memoria del container

Facet ora legge il limite di memoria del cgroup del container (`memory.max` su cgroup v2, `memory.limit_in_bytes` su v1) invece della RAM totale dell'host, e dimensiona in base a quel limite il raggruppamento dei pass (quali modelli vengono caricati insieme), la dimensione del chunk RAM, il caching dei modelli su CPU e la concorrenza di decodifica RAW. Prima di questa correzione, tutto ciò era dimensionato in base alla RAM dell'host: `psutil.virtual_memory()` legge `/proc/meminfo`, che Docker non virtualizza, quindi un `mem_limit` veniva ignorato silenziosamente — un container limitato ben al di sotto della RAM dell'host continuava a pianificarsi come se avesse a disposizione l'intera RAM dell'host, e veniva ucciso dall'OOM ([issue #111](https://github.com/ncoevoet/facet/issues/111)).

Riprodurre il bug su un'immagine pubblicata precedente alla correzione (v1.7.2) mostra il meccanismo: un container in profilo `8gb` limitato a `--memory=8g` su un host da 47 GB registra `Mode: CPU-only (47GB RAM)` — la RAM dell'host, non quella del container — e pianifica un unico pass che raggruppa `clip + topiq_iaa + topiq_nr_face + liqe + saliency + samp_net + insightface [~15.0GB RAM]`. Viene ucciso (`OOMKilled`, codice di uscita 137) prima di terminare anche un solo lotto delle 200 foto. Di fronte a un limite di cgroup di 512 MB, il lettore corretto riporta 0,500 GB dove `/proc/meminfo` continua a riportare i 46,8 GB dell'host.

### Memoria minima consigliata per profilo

I pesi dei modelli sono solo una parte del picco di memoria — il runtime di torch, il chunk di immagine decodificata e le attivazioni per livello si aggiungono — quindi considera queste cifre come minimi, non come budget. La riga `legacy`/`8gb` ora si basa su test reali in container — scansioni di 50 foto completate con `--memory=8g` su entrambi i profili (vedi sotto); le righe `16gb` e `24gb` restano segnaposto provvisori senza alcuna misurazione reale alle spalle.

| Profilo VRAM | Pesi dei modelli (totale) | Memoria del container consigliata |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB minimo, 12 GB consigliato (CPU) |
| `16gb` | 22,0 GB | almeno 18 GB (provvisorio) |
| `24gb` | 25,0 GB | almeno 18 GB (provvisorio) |

**GPU e CPU non sono interscambiabili qui, e la cifra di 12 GB sopra è una cifra GPU.** Su una RTX 3080, il profilo `8gb` dell'autore della segnalazione ha raggiunto un picco di 9,23 GB di RAM di sistema per 405 foto, anche con `ram_chunk_size: 12` e `num_workers: 2`, ed è riuscito con `mem_limit: 12g`. Su una GPU, i pesi dei modelli risiedono nella VRAM; la RAM del container contiene principalmente il chunk di immagine decodificata, ed è per questo che quella cifra è molto più piccola di ciò di cui ha bisogno la sola CPU. Eseguire lo stesso profilo `8gb` su CPU carica invece l'intero catalogo di modelli nella RAM del container. Prima che la correzione di follow-up dell'issue #111 aggiungesse un tetto, la capacità per pass del pianificatore cresceva direttamente con il limite del container, il che peggiorava il piano, non lo migliorava, al crescere del limite: un limite di 8 GB produceva 4 pass che arrivavano fino a 6,0 GB, causando un OOM nel pass che raggruppa `topiq_nr_face + liqe + saliency` (6,0 GB dichiarati, picco RSS di 10,46 GB); un limite di 12 GB collassava a sole 2 pass che arrivavano fino a 10,0 GB, causando anch'esso un OOM. Il regolatore di memoria è effettivamente intervenuto al limite di 12 GB — `Evicted 1 model(s) from RAM cache: topiq_iaa` è una riga di log reale — ma era il regolatore che interviene e comunque non basta, non ciò che ha salvato l'esecuzione.

Il tetto ora mantiene la capacità per pass a 5,0 GB indipendentemente da quanto sia grande il limite del container, quindi smette di crescere con il container: il profilo `8gb` su CPU pianifica sempre gli stessi 5 pass qualunque sia il limite — `Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`, `Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`, `Pass 5: insightface [~2.0GB RAM]`.

Questa forma fissa da sola non bastava ancora, perché due elementi al di fuori del piano dei pass consumavano il budget. L'auto-regolazione della dimensione del lotto cresceva sul minimo di memoria tra un pass e l'altro — ogni scaricamento fa scendere l'uso quasi al livello minimo, e tre letture di questo tipo di fila venivano lette come margine disponibile — così `ram_chunk_size` è passato da 10 a 500 già nel primissimo lotto, e il secondo ha provato a decodificare tutte le foto rimanenti in un colpo solo. E scaricare un modello non restituiva nulla al kernel: glibc tratteneva i blocchi liberati nelle sue arene, così il processo manteneva un picco massimo fissato dal suo primo pass, e ogni pass successivo girava sopra memoria che non poteva usare. Con la crescita ora decisa in base al picco di ciascun lotto e l'heap liberato restituito esplicitamente, una scansione di 50 foto con `--memory=8g` si completa su entrambi i profili — `legacy` con un picco di 7,26 GB e `8gb` di 7,56 GB di memoria anonima, cinque lotti da dieci, codice di uscita 0, nessun OOM e nessun errore di scansione registrato.

**8 GB sono un minimo, non un budget comodo.** Entrambe le esecuzioni si sono concluse entro circa mezzo gigabyte dal limite, su JPEG da 18-20 MP; immagini più grandi, la decodifica RAW o un host più occupato erodranno quel margine, motivo per cui 12 GB è la raccomandazione anziché il minimo. La memoria anonima è la cifra da tenere d'occhio — non il MemUsage di `docker stats` né il `memory.current` del cgroup, che contano entrambi la cache di pagine recuperabile, per cui il primo sottostima il rischio reale e il secondo resta ancorato vicino al limite del container indipendentemente da quanto margine ci sia davvero. Un container da 16 GB è stato misurato con almeno 12,55 GB di memoria anonima, il che spiega anche perché un'esecuzione precedente da 12 GB fu uccisa prima che questi due fix arrivassero, e coincide con il picco di 9,23 GB riportato dall'autore della segnalazione su GPU — lo stesso catalogo di modelli, meno ciò che risiede nella VRAM invece che nella RAM del container. Un utente GPU che dimensionasse in base ai numeri CPU qui sovradimensionerebbe; un utente CPU che dimensionasse in base alla cifra GPU sottodimensionerebbe — usa quella che corrisponde a come gira realmente il tuo container.

Più in generale: `MODEL_RAM_REQUIREMENTS` valuta solo il costo dei pesi. Il picco reale di RSS porta in aggiunta il runtime di torch, il chunk di immagine decodificata e le attivazioni per livello, nessuno dei quali è in quella cifra — dimensionare un container basandosi solo sulla colonna pesi dei modelli (totale) lo sottodimensionerà.

Le stime per `16gb` e `24gb` non hanno ancora alcuna esecuzione reale alle spalle, né su GPU né su CPU; considera 18 GB come un segnaposto provvisorio, non un minimo convalidato.

Imposta il limite in `docker-compose.yml` (o in un file di override):

```yaml
services:
  facet:
    mem_limit: 16g
```

### Il raggruppamento dei pass ha un limite massimo, e nessun minimo

Il pianificatore dei pass di Facet stabilisce il budget di ogni pass CPU al limite di memoria del cgroup del container meno una riserva di 2 GB per il runtime di torch, con un tetto di 5 GB che non fa mai crescere un pass oltre, per quanto grande sia il limite. Non esiste un minimo sotto quel limite: un container con poco margine dopo la riserva riceve un budget piccolo, che può scendere fino a zero, il che isola semplicemente un modello per pass.

In assenza totale di un limite di memoria del container, il budget viene invece dalla RAM di sistema: quanto la macchina tiene oltre al proprio sistema operativo (1 GB riservato a esso), diviso per 1,6 — il rapporto misurato tra la RSS reale e il peso dichiarato dei modelli. Nemmeno questo percorso ha un minimo: un host da 4 GB stabilisce un budget di 1,9 GB per pass e uno da 2 GB di 0,6 GB. Le versioni precedenti mantenevano qui un minimo ottimistico di 4 GB, che era esattamente il difetto descritto in questa pagina vestito da bare metal: pianificava un pass da 5 GB dentro una macchina da 4 GB.

Un modello più grande del budget ottiene comunque un proprio pass invece di essere diviso, e **ognuno** di questi pass viene nominato in un avviso, non solo il più pesante: con un limite del container di 4 GB, la capacità è di 2 GB, e il profilo `24gb` pianifica comunque un pass da 8,0 GB, perché `qwen3_5_4b_tagger` da solo richiede 8 GB e non può essere diviso, per quanto piccolo sia il budget. Non dimensionare mai un container al di sotto del modello singolo più grande del profilo che usi.

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

### 5. Eseguire Facet

Il repository sull'unità Windows è visibile dentro WSL in `/mnt/d/...`. Da lì, esegui il
blocco per la tua scheda da
[Installazione › Installa con Docker](INSTALLATION.md#installa-con-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # o il file della tua scheda
curl -s localhost:5000/health          # -> ok
```

Aggiungi `--build` per compilare dal checkout invece di scaricare l'immagine pubblicata.
I profili GPU (`8gb`/`16gb`/`24gb`) raggruppano i volti sulla GPU tramite RAPIDS cuML
integrato; il profilo `legacy` raggruppa sempre su CPU. Il primo avvio scarica i modelli
del profilo nei volumi con nome; reimpostali con `docker compose down -v`.

### Immagine riproducibile e autonoma

- **Versioni fissate.** L'immagine si compila a partire da `requirements.lock.txt` — un `pip freeze` completo di un container validato con `torch`/`torchvision` e `nvidia-*` rimossi (l'immagine base CUDA li fornisce già). Questo previene la deriva silenziosa verso release non testate. (Esempio di cosa previene: transformers 5.3 ha cambiato il batching della visione di Qwen3.5 e rotto il tagger VLM fino all'arrivo del fix di padding; `kornia`, richiesto da BiRefNet, non viene trascinato da transformers e va fissato.) Rigenera dopo un aggiornamento intenzionale: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Clustering dei volti su GPU integrato.** RAPIDS cuML (`cuml-cu12`) è incluso nell'immagine, quindi i profili GPU (8gb/16gb/24gb) raggruppano i volti sulla GPU (HDBSCAN via `face_clustering.use_gpu="auto"`); il profilo legacy — e qualsiasi host senza dispositivo CUDA — raggruppa sempre su CPU. cuML è di gran lunga la dipendenza più grande (~5,75 GB; vedi la ripartizione delle dimensioni più sotto).
- **Nessun accoppiamento con l'host.** Le cache dei modelli sono volumi con nome, non bind mount dell'host; il container viene eseguito senza privilegi (l'entrypoint predefinito passa all'utente `facet`).
- **Contesto di build snello.** `.dockerignore` esclude i contenuti voluminosi solo locali (`conda/`, dataset di esempio, `*.db`, cache, artefatti di sviluppo) — tieni le nuove directory locali di grandi dimensioni fuori dal contesto aggiungendole lì.

### Dimensione dell'immagine

Nessuna delle tre immagini pubblicate contiene i pesi dei modelli — questi si
scaricano al primo avvio nei volumi con nome ([totali per profilo](INSTALLATION.md#dimensioni-dei-download)).
Prevedi spazio su disco per l'immagine **più** questi volumi.

| Immagine | Su disco (misurato) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + PyTorch in wheel CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, da Turing a Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, da Maxwell a Hopper) + RAPIDS cuML |

Tutte e tre le immagini di base sono cambiate in questa release (issue #119). "Su
disco" è l'ingombro dell'immagine decompressa, misurato localmente (`docker
images`) su immagini compilate da questo branch — una scomposizione per
componente (RAPIDS cuML vs. runtime CUDA vs. PyTorch vs. OS di base) non è stata
rimisurata per questo passaggio. `docker pull` trasferisce un download compresso
più piccolo di queste cifre; una colonna "download compresso" tornerà qui una
volta pubblicate queste immagini e disponibile un manifest di registro reale da
cui misurarlo.

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

Con `--workers > 1` tutti i worker leggono lo stesso file, quindi un JWT firmato da uno è valido per tutti — **una volta che quel file esiste**. Un primo avvio con `--workers > 1` e senza `.facet_secret` è l'eccezione: ogni worker genera il proprio secret e uno solo vince la scrittura, così una sessione aperta su un worker viene rifiutata dagli altri finché il server non viene riavviato. Crea il secret prima del primo avvio multi-worker — esegui una volta `python database.py --rotate-secret`, avvia una volta con `--workers 1`, oppure imposta `FACET_JWT_SECRET`.

La stessa divergenza diventa permanente quando la directory di installazione non è scrivibile: il server registra un errore e funziona con un secret in memoria, quindi ogni sessione muore a ogni riavvio e ogni worker firma con una chiave diversa. Lì imposta `FACET_JWT_SECRET`.

Includi il file nei backup del database — ripristinare un database senza di esso disconnette tutti.

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
