# Installazione

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · **Italiano** · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md) · [简体中文](../zh/INSTALLATION.md)

Facet funziona sulla tua macchina. Scegli la sezione che corrisponde alla tua
configurazione e copia il blocco. La parte [Avanzate](#avanzate) serve solo quando ne hai bisogno.

## Quale installazione fa per me?

Le due strade eseguono lo stesso Facet; scambiano la semplicità di installazione con le
prestazioni. Scegli quella che fa per te.

| | Docker | Senza Docker |
|---|---|---|
| Installazione | Un comando: tutto è nell'immagine | `install.sh` (Linux, macOS) o l'installer per Windows crea un ambiente Python sulla macchina |
| Aggiornamento | Scaricare la nuova immagine | Aggiornare il codice e rieseguire `install.sh`, oppure installare il nuovo installer per Windows |
| Prestazioni | Un container si frappone tra Facet e i tuoi file e la scheda grafica; su Windows gira dentro WSL2 | Facet usa direttamente la scheda grafica e i file della macchina |

| La tua situazione | Vai a |
|----------------|-------|
| Windows, macOS o Linux, in un container | [Installa con Docker](#installa-con-docker) |
| Windows, macOS o Linux, senza container | [Installa senza Docker](#installa-senza-docker) |
| Un NAS, o un server che vuoi raggiungere da altre macchine | [Distribuzione](DEPLOYMENT.md) |

## Quale profilo si adatta al mio hardware?

Un *profilo* è un insieme di modelli IA dimensionato per la tua macchina. Ne scegli uno durante
l'installazione e puoi cambiarlo in seguito.

| Il tuo hardware | Profilo | Cosa ottieni |
|---------------|---------|--------------|
| Nessuna scheda grafica | `legacy` | Tutto funziona, solo più lentamente. |
| Scheda NVIDIA, 6–14 GB | `8gb` | I modelli di `legacy`, eseguiti sulla scheda grafica. |
| Scheda NVIDIA, 14–20 GB | `16gb` | Il punteggio più accurato, oltre a tag e didascalie IA. |
| Scheda NVIDIA, 20 GB o più | `24gb` | I modelli più grandi, più spiegazioni scritte della composizione. |
| Mac Apple Silicon (M1–M4) | scelto per te | Usa i core grafici del Mac; profilo dimensionato in base alla memoria. |

Non sai quanta memoria ha la tua scheda? Usa il blocco *Rilevamento automatico* qui sotto.

## Installa con Docker

Ti serve [Docker](https://docs.docker.com/get-started/get-docker/). Con una scheda NVIDIA ti serve
anche l'
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
Su Windows questo significa eseguire Facet dentro WSL2
([guida passo passo](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia)).

Ogni blocco parte da zero. Scegline **uno**.

### Rilevamento automatico dell'hardware

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # apri .env e imposta PHOTOS_DIR sulla tua cartella foto
docker compose up -d
```

Apri <http://localhost:5000>.

### Nessuna scheda grafica

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # apri .env e imposta PHOTOS_DIR sulla tua cartella foto
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Apri <http://localhost:5000>.

### Scheda grafica da 8 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # apri .env e imposta PHOTOS_DIR sulla tua cartella foto
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Apri <http://localhost:5000>.

### Scheda grafica da 16 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # apri .env e imposta PHOTOS_DIR sulla tua cartella foto
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Apri <http://localhost:5000>.

### Scheda grafica da 24 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # apri .env e imposta PHOTOS_DIR sulla tua cartella foto
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Apri <http://localhost:5000>.

### Scheda NVIDIA meno recente (Maxwell, Pascal, Volta)

I blocchi GPU qui sopra e `docker-compose.gpu.yml` scaricano `ghcr.io/ncoevoet/facet:latest-cuda`,
che copre `sm_75`-`sm_120` (da Turing a Blackwell).

Per una scheda Maxwell, Pascal (GTX 900/serie 10) o Volta (ad es. Titan V), modifica la riga
`image:` nel file compose che hai usato (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` o
`.gpu.yml`) prima di `docker compose up -d`:

- da `ghcr.io/ncoevoet/facet:latest-cuda`
- a `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, da Maxwell a Hopper)

Questo tag di immagine `-cuda-legacy` non c'entra con `docker-compose.legacy.yml`, che seleziona
il profilo `legacy` solo CPU. Le schede più vecchie di Maxwell (Kepler, Fermi) non hanno un'immagine
CUDA: usa il blocco [Nessuna scheda grafica](#nessuna-scheda-grafica).

### Comandi di uso quotidiano

La galleria resta vuota finché non valuti le tue foto. Dentro Docker la tua cartella foto è
sempre `/data/photos`:

```bash
docker compose exec facet python facet.py /data/photos   # valuta le tue foto
docker compose logs -f                                   # guarda cosa sta facendo
docker compose down                                      # fermalo
```

Per riavviarlo, riesegui la riga `docker compose … up -d` che hai usato sopra.

## Installa senza Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` individua la tua scheda grafica, installa i pacchetti corrispondenti e compila la
galleria web. Poi, ogni volta:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # valuta le tue foto
python viewer.py                       # avvia la galleria
```

Apri <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

Su Apple Silicon usa automaticamente i core grafici. Poi, ogni volta:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # valuta le tue foto
python viewer.py                       # avvia la galleria
```

Apri <http://localhost:5000>.

> **Porta 5000 già occupata?** macOS la usa per AirPlay. Esegui
> `python viewer.py --port 5001` e apri <http://localhost:5001>.

### Windows

Un installer per utente (MSI) installa Facet senza diritti di amministratore:

| Cartella | Contenuto |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | il programma, sostituito a ogni aggiornamento |
| `%LOCALAPPDATA%\Facet\venv` | l'ambiente Python, creato al termine dell'installer |
| `%LOCALAPPDATA%\Facet\data` | il database (`photo_scores_pro.db`) e i log |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Ottenere l'installer.** Nessuna release lo include ancora. Costruiscilo da un clone con
`installer\build-msi.ps1` (servono WiX 3.14, `uv` e il client compilato; lo script indica dove
trovare WiX), oppure scarica l'artefatto `facet-msi` di un'esecuzione del workflow *Windows
install (MSI)*. La costruzione richiede Node.js 22.22.3 o successivo per il client (22.14
fallisce su `npm run build`).

**Primo avvio.** L'installer avvia la creazione dell'ambiente Python appena termina. L'ambiente occupa circa 6 GB, e la cache di download di uv
(`%LOCALAPPDATA%\uv\cache`) ne occupa altrettanti. La voce *Facet* del menu Start esegue la
configurazione se non è mai stata completata, e di nuovo dopo un aggiornamento che cambia le
dipendenze di Facet. Sceglie la build di PyTorch per la tua scheda NVIDIA e il suo driver come
fa `install.sh`, oppure la build per CPU senza scheda NVIDIA. Se la build GPU installata non
raggiunge la scheda, l'installazione si ferma e lo spiega: aggiorna il driver, oppure esegui
`Setup-Facet.ps1 -Force -Cpu`.

Se la galleria non riesce ad avviarsi (porta occupata, errore di configurazione, nessuna
risposta dopo 90 s), la finestra della voce del menu Start mostra l'errore e attende Invio.
Dopo 90 s senza risposta la galleria resta in esecuzione e può ancora avviarsi.

**Ogni giorno:**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # valutare le foto; gli argomenti in più vanno a facet.py
.\Start-Facet.ps1                # la galleria, su http://localhost:5000
.\Stop-Facet.ps1                 # fermare la galleria e ogni scansione
```

La galleria risponde solo su questo computer. `Start-Facet.ps1 -Lan` la apre agli altri
dispositivi e si rifiuta di partire finché `viewer.password` non è impostato nella
configurazione.

**Un solo modo di scrivere ogni cartella.** Facet salva ogni foto con il percorso da cui è stata
scansionata: `\\NAS\Photos` e la stessa condivisione collegata come `Z:\` sono per lui due
cartelle diverse, e scansionarle entrambe aggiunge ogni foto due volte. Scegline una e tienila.

**Computer gestiti.** I collegamenti eseguono gli script PowerShell non firmati di Facet con `-ExecutionPolicy Bypass`. Un criterio di esecuzione impostato tramite Criteri di gruppo ha la precedenza, quindi su un PC gestito gli script potrebbero non avviarsi; chiedi al suo amministratore di consentirli.

**La disinstallazione** (Impostazioni, App) ferma Facet e rimuove il programma, i collegamenti,
l'ambiente Python ed ExifTool (anche sotto un `FACET_HOME` personalizzato), e conserva `data` e
`config`. Quello che non riesce a cancellare è elencato in `data\logs\uninstall.log`. La cache di
download di uv (`%LOCALAPPDATA%\uv\cache`) e i modelli scaricati restano (`.cache`, `.insightface`
nella tua cartella utente). Un aggiornamento mantiene una cartella di installazione
personalizzata e ricrea l'ambiente solo se le dipendenze di Facet sono cambiate.

**Spostare una libreria da Docker.** Il database salva il percorso completo di ogni foto, e
l'installazione Windows vede le stesse foto sotto un altro (`\\NAS\Photos\...` invece di
`/data/photos/...`). Copia il database in `data`, ferma Facet, poi riscrivi i percorsi, prima
con una prova a vuoto:

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

Lo strumento tiene una copia del database (`photo_scores_pro.db.before-rewrite-<ora>`), si
rifiuta di unire una foto già scansionata con il nuovo percorso e svuota l'indice vettoriale,
che `..\venv\Scripts\python.exe database.py --db ..\data\photo_scores_pro.db --populate-vec`
ricostruisce. La cronologia degli annullamenti di prima dello spostamento non si applica più.
Questi comandi presuppongono la cartella di installazione predefinita. Un prefisso vecchio e
uno nuovo, di cui uno è dentro l'altro (per esempio da `D:\Photos` a `D:\Photos\new`), vengono
rifiutati; passa da un prefisso temporaneo.

Docker funziona anche su Windows; per una scheda NVIDIA, segui la [guida WSL2](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia).

## Primo avvio: cosa aspettarsi

- **Un download.** La prima scansione scarica i modelli per il tuo profilo: circa 4,7 GB per
  `legacy`, 6,9 GB per `8gb`, 14,6 GB per `16gb`, 19,3 GB per `24gb`
  ([Dimensioni dei download](#dimensioni-dei-download)). Succede una sola volta.
- **Nessuna configurazione per scansionare.** Facet crea il proprio database alla prima scansione.
- **Sola lettura finché non imposti una password.** Per modificare (valutare, selezionare, album, persone), imposta
  `viewer.edition_password` in `scoring_config.json` e riavvia il viewer. Con il
  `docker-compose.yml` fornito, l'immagine ne genera una al primo avvio.
- **Le tue foto non vengono modificate.** La scansione si limita a leggerle. Riscrivere voti e parole chiave
  nei file è un'azione separata, che attivi tu ([Interoperabilità](INTEROP.md)).
- **Tempo.** Una prima scansione di una libreria grande richiede tempo, di più su un processore che su una
  scheda grafica. Puoi sfogliare la galleria mentre lavora.

## Verifica che funzioni

```bash
python facet.py --doctor                             # senza Docker
docker compose exec facet python facet.py --doctor   # con Docker
```

Mostra la tua scheda grafica, il profilo scelto e tutto ciò che manca. Mentre la galleria
è in esecuzione, <http://localhost:5000/health> risponde `ok`.

Qualcosa non va? Vedi [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze)
e [Problemi di rilevamento della GPU](#problemi-di-rilevamento-della-gpu).

---

# Avanzate

Facoltativo: cosa fa l'installazione, come cambiarla e il riferimento delle dipendenze.

- [Impostazioni Docker che puoi modificare](#impostazioni-docker-che-puoi-modificare)
- [Scegliere il profilo manualmente](#scegliere-il-profilo-manualmente)
- [Installazione manuale, senza install.sh](#installazione-manuale-senza-installsh)
- [Opzioni di install.sh e scorciatoie del Makefile](#opzioni-di-installsh-e-scorciatoie-del-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime per il rilevamento dei volti](#onnx-runtime-per-il-rilevamento-dei-volti)
- [OpenCV in versione headless](#opencv-in-versione-headless)
- [Clustering dei volti su GPU con RAPIDS cuML](#clustering-dei-volti-su-gpu-con-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Dimensioni dei download](#dimensioni-dei-download)
- [Dipendenze](#dipendenze)
- [Requisiti delle funzionalità](#requisiti-delle-funzionalità)
- [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze)
- [Client Angular](#client-angular)

## Impostazioni Docker che puoi modificare

Le impostazioni di distribuzione stanno in `.env` (copia `.env.example`):

| Chiave | Predefinito | Scopo |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Cartella dell'host montata in lettura-scrittura in `/data/photos` (così si possono scrivere i sidecar XMP) |
| `PORT` | `5000` | Porta dell'host per la galleria |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb`; sostituisce `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Percorso del database nel container, sul bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` della configurazione | Innesco del riaddestramento del ranker personale, per chi valuta molto |

`scoring_config.json` è il tuo **override**. I valori forniti stanno in
`config/scoring_config.default.json` dentro l'immagine. Il tuo file contiene solo ciò che
hai cambiato; tutto il resto mantiene il valore fornito e segue gli aggiornamenti. Vedi
[Configurazione](CONFIGURATION.md#valori-predefiniti-e-il-tuo-override) e
[il riferimento completo delle chiavi](CONFIGURATION.md).

Al primo avvio, `docker-entrypoint.sh` crea `./facet-config/scoring_config.json`:

- `docker-compose.yml` lo monta in bind come `FACET_CONFIG=/config/scoring_config.json`, così le
  modifiche di configurazione fatte nel viewer sopravvivono a `docker compose down && up`.
- Con compose, contiene un `viewer.edition_password` generato, stampato una sola volta in
  `docker compose logs facet`. Un semplice `docker run` senza `FACET_CONFIG` crea un override
  vuoto e nessuna password.
- Un file esistente non viene mai sovrascritto, e il suo proprietario e i suoi permessi restano come sono.

### Proprietà del file nel container

Facet esegue `chown` e `chmod` solo su un `scoring_config.json` che ha creato lui stesso.

Un'eccezione: se una configurazione esistente non è **leggibile** dall'utente `facet` del container
(uid 1000), l'entrypoint ne prende possesso e lo dice su stderr. Una configurazione illeggibile
ti bloccherebbe fuori dall'interfaccia. Per mantenere la proprietà, rendila invece leggibile:
`chmod o+r facet-config/scoring_config.json`.

Con Podman/Docker rootless, il tuo file appartiene a un uid in cui l'utente `facet` del container
non può trasformarsi. Rendilo **scrivibile dall'utente del container mantenendone tu la proprietà**:

```bash
# 100999 = il subuid host a cui è mappato l'utente facet nel container (uid 1000);
# leggi il tuo da un file già creato dal container: stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

Il file resta tuo e modificabile, e le scritture di Facet lo mantengono tale. Alternative:
`podman unshare chown` per modificare un file di proprietà del container, oppure `--userns=keep-id` (o un
override `user:` di compose) così l'utente del container *sei tu*.

> **Attenzione — aggiornamento da un vecchio file compose.** Le versioni precedenti montavano
> `- ./scoring_config.json:/app/scoring_config.json`. Il file compose fornito non lo fa più.
> Se adotti il nuovo, **sposta prima la tua configurazione**, altrimenti i tuoi pesi,
> le categorie e la password del viewer non vengono più letti:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Se mantieni il tuo `docker-compose.yml` con il vecchio mount, `./facet-config` viene creato
> da quel file e non si perde nulla.
>
> Una configurazione portata dal vecchio setup è una copia completa dei vecchi valori predefiniti. Funziona ancora, ma le tue
> modifiche sono difficili da individuare. Esegui `python database.py --compact-config` (Docker:
> `docker compose exec facet python database.py --compact-config`) per ridurla a ciò che hai
> cambiato. Prima crea un backup `0600` e si risolve nella stessa configurazione.

Le cache dei modelli stanno in volumi con nome (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) e sopravvivono ai riavvii. `docker compose down -v`
li elimina e impone un nuovo download.

L'immagine include `exiftool` ma **non** darktable. Il download RAW/profilo darktable del viewer
resta disattivato a meno che tu non aggiunga un binario `darktable-cli` all'immagine.

## Scegliere il profilo manualmente

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` impostano ciascuno `FACET_VRAM_PROFILE`; quelli GPU riservano anche il
  dispositivo NVIDIA.
- `docker-compose.gpu.yml` riserva la GPU e lascia il profilo al `vram_profile` della
  configurazione (predefinito `auto`).

Vengono pubblicate tre immagini:

| Immagine | Contenuto | Decompressa |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Build CPU snella | 3,34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, incl. serie RTX 50); predefinita per `8gb`/`16gb`/`24gb` | 13,1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper); vedi [Scheda NVIDIA meno recente](#scheda-nvidia-meno-recente-maxwell-pascal-volta) | 13,8 GB |

- Entrambe le immagini CUDA includono `onnxruntime-gpu` (1.26.0, CUDA 12) al posto di `onnxruntime`, così il
  rilevamento dei volti gira sulla GPU. L'immagine CPU mantiene `onnxruntime`.
- Tutte e tre sono solo `linux/amd64`. Su ARM, compila in locale con `docker compose build`.
- `docker compose build` (o `up --build`) compila da questo repository. Argomenti di build:
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (vedi il `Dockerfile`).

Senza Docker, usa la variabile d'ambiente o la chiave di configurazione:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Le soglie usate da `auto` sono in
[Configurazione › Rilevamento automatico della VRAM](CONFIGURATION.md#rilevamento-automatico-della-vram).

## Installazione commerciale e pacchetti con restrizioni

`insightface` e `pyiqa` (più `openai-clip`, `facexlib` e `onnxruntime`, che servono solo a
loro) distribuiscono pesi di modelli con termini non commerciali. Non sono nell'installazione di base. Stanno
negli extra `faces-insightface` e `iqa` e in `requirements.restricted.txt` (più
`requirements.restricted.lock.txt` e `requirements.legacy.restricted.lock.txt` per Docker).

> **Modifica incompatibile.** `pip install -e .` e `pip install -r requirements.txt` da soli non
> includono più insightface né pyiqa. Usa `pip install -e .[all]` oppure
> `pip install -r requirements.txt -r requirements.restricted.txt`. `install.sh` e
> l'immagine Docker predefinita installano entrambi.

| Obiettivo | Comando |
|------|---------|
| Tutto (predefinito) | `bash install.sh`, oppure `pip install -e .[all]` |
| Sicuro per uso commerciale | `bash install.sh --commercial` |
| Sicuro per uso commerciale, a mano | `pip install -r requirements.txt`, poi `pip install -e .[commercial]` e `pip install mediapipe==0.10.35 --no-deps` |
| Sicuro per uso commerciale, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` e l'extra `faces-insightface` installano `onnxruntime` per CPU.
  Su una macchina CUDA, fai seguire il comando GPU di
  [ONNX Runtime per il rilevamento dei volti](#onnx-runtime-per-il-rilevamento-dei-volti). `bash install.sh`
  e le immagini CUDA lo fanno già.
- Installa sempre `mediapipe` con `--no-deps`, altrimenti il suo `opencv-contrib-python` installa due volte
  il namespace `cv2`. L'extra `commercial` dichiara le sue dipendenze di runtime (`absl-py`,
  `flatbuffers`).
- `python-ofiq` (binding OFIQ per la qualità del volto) ha wheel solo per Linux x86-64 e macOS arm64.
  Installalo a mano con `pip install python-ofiq` dove disponibile.

Installare in modo commerciale non cambia la modalità. Impostala nel tuo override:
`{ "licensing": { "mode": "commercial" } }`. Anche l'argomento di build Docker imposta
`FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` mostra la modalità di licenza attiva
e, in modalità commerciale, i componenti che una scansione caricherebbe (YuNet, SFace, Q-ReAlign).

## Installazione manuale, senza install.sh

Richiede Python 3.12 (funziona con 3.10+) e Node.js 20+ per la compilazione della galleria.

```bash
# 1. Crea e attiva un ambiente virtuale
python3 -m venv venv
source venv/bin/activate

# 2. Installa prima PyTorch, in base alla tua versione di CUDA:
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    Conta anche la tua SCHEDA: Maxwell/Pascal/Volta (GTX 900/serie 10, Titan V) richiedono cu126,
#    anche con un driver CUDA 12.8. Verifica: `nvidia-smi --query-gpu=compute_cap --format=csv`
#    Hai dubbi? Copia il comando da https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Installa il resto in un colpo solo, così pip risolve l'intero grafo
pip install -r requirements.txt -r requirements.restricted.txt

# 4. Solo CUDA, DOPO il passo 3: sostituisci ONNX Runtime con la versione GPU (in base alla build CUDA di PyTorch)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # PyTorch CUDA 12.x (cu124, cu126, cu128)
# Solo CPU, o CUDA 11.8 (cu118): tieni quello installato dal passo 3, oppure reinstallalo con
# pip install "onnxruntime>=1.15.0"

# 5. DOPO i passi 3 e 4: tieni solo la build headless di OpenCV (quella con interfaccia grafica richiede libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Compila la galleria web
cd client && npm install && npx ng build && cd ..

# 7. Eseguilo
python facet.py /path/to/photos
python viewer.py
```

L'ordine dei passi conta: per i pacchetti che condividono file (`onnxruntime`/`onnxruntime-gpu`,
`opencv-python`/`opencv-python-headless`) vince quello installato per ultimo.
`install.sh` applica automaticamente il limite della scheda ed entrambe le sostituzioni.

Verifica l'ambiente:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Errori? Vedi [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze).

## Opzioni di install.sh e scorciatoie del Makefile

`install.sh`:

1. trova un Python 3.10+ e crea il `venv`;
2. rileva il sistema operativo e la GPU (Apple Silicon → Metal, altrimenti `nvidia-smi` → build CUDA corrispondente);
3. installa PyTorch, `requirements.txt`, `transformers` e `accelerate`;
4. sostituisce con l'[ONNX Runtime](#onnx-runtime-per-il-rilevamento-dei-volti) giusto e con la
   [build headless di OpenCV](#opencv-in-versione-headless);
5. verifica la presenza di `exiftool`, compila il client Angular e controlla ogni import (stato di uscita 1 se uno fallisce).

| Flag | Effetto |
|------|--------|
| `--cpu` | Forza PyTorch solo CPU (senza CUDA) |
| `--cuda VERSION` | Sostituisce la versione CUDA rilevata (ad es. `--cuda 12.8`) |
| `--skip-client` | Salta la compilazione del frontend Angular |
| `--no-uv` | Usa pip invece di uv |
| `--commercial` | Installazione sicura per uso commerciale: salta insightface, pyiqa e ONNX Runtime, installa mediapipe con `--no-deps`; imposta tu stesso `licensing.mode` su `commercial` |

| Target di Make | Esegue |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, rilevamento automatico o solo CPU |
| `make client` | Ricompila il frontend Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU o NVIDIA |
| `make test` / `make test-cov` | pytest, con o senza coverage |
| `make clean` | Rimuove `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool offre la migliore estrazione EXIF per ogni formato. Senza di esso Facet ricade su
`exifread` (gestisce tutti i formati RAW), poi su PIL (solo JPEG/TIFF/DNG).

| Sistema operativo | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Scarica da [exiftool.org](https://exiftool.org/) |

## ONNX Runtime per il rilevamento dei volti

Il rilevamento dei volti (InsightFace) gira su ONNX Runtime: `onnxruntime` (CPU) oppure
`onnxruntime-gpu` (CUDA). I due condividono la directory `onnxruntime/`, quindi ne può essere installato uno solo; vince l'ultimo
che pip installa. `insightface` dipende dalla build CPU, quindi installarlo
(`requirements.restricted.txt`, `pip install -e .[all]`, l'extra `faces-insightface`)
riporta la build CPU. Su una macchina CUDA, installa il pacchetto GPU **dopo** questi,
rimuovendo prima entrambi i nomi.

`bash install.sh` lo fa su x86_64 con un PyTorch CUDA 12, poi prova una vera sessione CUDA
(come fa `--doctor`). Rieseguilo per riparare un `venv` rotto o passare da CPU a GPU. Le
immagini Docker CUDA fanno lo stesso. Le installazioni CPU, CUDA 11.8 (cu118), macOS, l'immagine CPU e
aarch64 (nessuna wheel `onnxruntime-gpu` per CUDA 12) mantengono `onnxruntime`.

A mano, scegli la riga per la build CUDA del tuo **PyTorch**:

| Build di PyTorch | Comando |
|---------------|---------|
| Solo CPU, o CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Fai corrispondere PyTorch, non il driver.** La versione CUDA mostrata da `nvidia-smi` è la più recente che il
  driver supporta; un driver CUDA 13 esegue comunque il PyTorch cu128. `python facet.py --doctor`
  mostra la build di PyTorch nella riga `CUDA (compiled)`.
- **Mantieni l'intervallo di versioni.** `onnxruntime-gpu` 1.19–1.26 sono build CUDA 12; la 1.27+ richiede
  librerie CUDA 13. Un'installazione senza vincoli sembra a posto ma gira in silenzio sulla CPU. Per un PyTorch CUDA
  13 installato a mano, `"onnxruntime-gpu>=1.27.0"` corrisponde (non testato).
- **CUDA 11.8 non ha una build GPU utilizzabile.** Il vecchio `onnxruntime-gpu` per CUDA 11 richiede cuDNN 8,
  ma il PyTorch cu118 usa cuDNN 9. Per il rilevamento dei volti su GPU, aggiorna il driver a uno che riporti
  CUDA 12.4 o successiva e riesegui `install.sh`.
- **Metti il requisito tra virgolette.** Senza virgolette, `pip install onnxruntime-gpu>=1.19.0,<1.27` crea un
  file vuoto chiamato `=1.19.0,` e fallisce con `1.27: No such file or directory`. Elimina quel file.
- **Disinstalla entrambi i nomi.** `pip uninstall onnxruntime` seguito da `pip install onnxruntime-gpu`
  lascia `import onnxruntime` un pacchetto vuoto, e InsightFace fallisce con
  `module 'onnxruntime' has no attribute 'InferenceSession'`.

Dopo la sostituzione, `pip check` riporta "insightface ... requires onnxruntime, which is not
installed" (`uv pip check`: "The package `insightface` requires `onnxruntime`, but it's not
installed"). È innocuo: `onnxruntime-gpu` fornisce lo stesso modulo. Allo stesso modo, dopo
la sostituzione di OpenCV, il fatto che `insightface` e `facexlib` richiedano `opencv-python` è innocuo. Un successivo
`pip install -r requirements.txt` riporta OpenCV con interfaccia grafica; rifai la
[sostituzione di OpenCV](#opencv-in-versione-headless) oppure riesegui `install.sh`.

**Verifica:** la sezione **ONNX Runtime** di `python facet.py --doctor` elenca pacchetto,
versione e provider di esecuzione, e avvisa (con la correzione) quando sono installati entrambi i pacchetti
o l'import fallisce. Su CUDA esegue una sessione di prova; la riga `CUDA session` è OK solo quando
gira davvero su `CUDAExecutionProvider`. La prova richiede il pacchetto `onnx` e viene saltata
su CPU e in modalità commerciale. Anche una scansione su CUDA avvisa una volta quando InsightFace gira sulla CPU.

In Docker, una riparazione dentro il container va persa al successivo `docker run`: scarica un'immagine
aggiornata o ricompila. Le immagini CUDA impostano `onnxruntime-gpu` 1.26.0 tramite l'argomento di build
`ORT_GPU_VERSION`; non impostare mai la 1.27 o successive (CUDA 13).

## OpenCV in versione headless

`opencv-python` (con interfaccia grafica) e `opencv-python-headless` condividono la directory `cv2/`; vince l'ultimo
installato. Le dipendenze di Facet li portano entrambi. La build con interfaccia grafica richiede `libGL.so.1`, che
Debian, WSL e gli host minimali non hanno, quindi `import cv2` fallisce con
`ImportError: libGL.so.1: cannot open shared object file`. Facet non apre finestre OpenCV,
quindi la build headless basta.

`bash install.sh` mantiene solo la build headless in ogni modalità, compresa `--commercial`.
Le immagini Docker non sono interessate (installano `libgl1`). Per riparare un `venv` a mano,
sostituisci `<version>` con la versione che `pip list` mostra per uno dei due pacchetti:

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

La sezione **OpenCV** di `python facet.py --doctor` mostra `[OK]` quando `cv2` si importa, oppure
l'errore di import e il comando di riparazione con la tua versione già inserita. Avere entrambi i pacchetti con un
import funzionante va bene (le immagini Docker includono entrambi, con `libgl1`). Se un import fondamentale come
`cv2` fallisce, `install.sh` stampa "Installation finished with errors" ed esce con
stato 1.

## Clustering dei volti su GPU con RAPIDS cuML

Per grandi database di volti (80k+ volti), cuML accelera molto il clustering. Richiede conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# oppure: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt installa opencv-python, la build con interfaccia grafica (richiede libGL.so.1): tieni solo quella headless
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

Con cuML installato, il clustering usa automaticamente la GPU (`face_clustering.use_gpu` in
`scoring_config.json`). Le immagini Docker CUDA lo includono, quindi i container `8gb`/`16gb`/`24gb`
eseguono il clustering sulla GPU. `legacy` lo esegue sempre sul processore.

## Apple Silicon (Metal/MPS)

Non serve nessun pacchetto GPU aggiuntivo. Installa con `bash install.sh`, poi verifica che
`python facet.py --doctor` riporti `Facet runtime device: mps`. Facet abilita il fallback su
CPU di PyTorch per gli operatori non supportati. Per confrontare:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` disattiva l'accelerazione; `FACET_DEVICE=mps` la richiede e fallisce se non è
  disponibile. `FACET_DEVICE=cuda` fallisce allo stesso modo quando PyTorch non vede alcun dispositivo CUDA
  (ad es. `CUDA_VISIBLE_DEVICES=''`).
- InsightFace resta sul processore (è un modello ONNX Runtime).
- I punteggi TOPIQ possono differire leggermente da CPU/CUDA. Su MPS, una foto i cui lati non sono
  multipli di 32 viene prima ritagliata al centro (1024×682 diventa 1024×672).

`vram_profile: "auto"` dimensiona il profilo in base alla memoria unificata totale:

| Memoria unificata totale | Profilo scelto da `auto` |
|----------------------|----------------------------|
| meno di 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB e oltre | `24gb` |

Ogni soglia è circa il doppio dell'ingombro dei modelli del profilo, perché macOS e le altre app
condividono quella memoria. Un Mac che va in swap è più lento di uno con un profilo più piccolo. Un profilo
impostato esplicitamente viene sempre usato così com'è.

### Memoria su un Mac

Se Monitoraggio Attività mostra Facet che usa più memoria di quella del Mac, o lo swap continua a crescere
durante una scansione, prova questi rimedi in ordine.

**1. Limita il pool di memoria di PyTorch:**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` significa «il working set consigliato del Mac, non oltre». Un pass può allora fermarsi con «out of
memory» invece di andare in swap, il che è meglio di un Mac che si blocca.

**I pesi si caricano uno alla volta.** Su macOS Facet imposta `HF_DEACTIVATE_ASYNC_LOAD=1` per
impostazione predefinita, perché il caricamento concorrente può far andare in crash una scansione su MPS. Nulla da configurare; imposta
tu stesso `HF_DEACTIVATE_ASYNC_LOAD=0` per riavere il caricamento concorrente.

**2. Disattiva i due modelli opzionali più pesanti.** Aggiungi solo queste chiavi a
`scoring_config.json`:

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` disattiva il rilevamento del soggetto; `qrealign` disattiva un modello di qualità
aggiuntivo. Estetica, composizione, volti e qualità tecnica vengono comunque valutati. Usa la chiave del profilo del tuo
Mac: `"16gb"` con 32-47GB, `"24gb"` con 48GB e oltre.

**3. Elabora meno foto alla volta:**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Imposta tutti e tre, altrimenti l'auto-regolazione sposta la dimensione del chunk tra `min_ram_chunk_size` e
`max_ram_chunk_size`.

## Dimensioni dei download

I modelli si scaricano al primo utilizzo in:

- `~/.cache/huggingface/` (modelli Hugging Face)
- `~/.cache/torch/hub/` (pesi PyIQA)
- `~/.insightface/` (rilevamento/riconoscimento dei volti)
- `pretrained_models/` nella radice del repository: `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task` e `aesthetic_predictor_weights.pth` (solo `legacy`/`8gb`)

In Docker sono volumi con nome (`pretrained_models/` è `facet-pretrained`), quindi nulla
viene riscaricato quando il container viene ricreato. Nessun peso è incorporato nell'immagine.

Le dimensioni sono decimali (GB = 10⁹ byte, MB = 10⁶ byte).

| Modello | Dimensione | Profili |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embedding + tagging CLIP + estetica CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Testa Aesthetic-MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | solo `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embedding) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (tagging VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (tagging VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composizione) | 4,430 GB | nessuno per impostazione predefinita; vedi nota 1 |
| InsightFace buffalo_l (volti) | 289 MB di download / 630 MB su disco (lo zip resta accanto ai file `.onnx`) | tutti |
| Pesi SAMP-Net (composizione) | 183 MB | tutti |
| U2-Net-P (sotto-modello di salienza di SAMP-Net) | 4,7 MB | come SAMP-Net |
| BiRefNet_dynamic (salienza del soggetto) | 445 MB | tutti |
| TOPIQ NR (modello estetico) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estetica supplementare) | 873 MB | tutti |
| TOPIQ NR-Face (qualità del volto supplementare) | 376 MB | tutti |
| LIQE (qualità/distorsione supplementare) | 708 MB | tutti |
| timm resnet50.a1_in1k (backbone PyIQA condiviso) | 102 MB | tutti |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **attivo per impostazione predefinita** (`"auto"`) |

1. Qwen2-VL-2B si carica solo se imposti `composition_model: "qwen2-vl-2b"` **e**
   `processing.mode: "single-pass"`, sostituendo SAMP-Net/U2-Net-P. Fuori dalla modalità commerciale
   funziona solo su `legacy`/`8gb`: su `16gb`/`24gb` il single-pass ricade sul multi-pass,
   che non ha un pass Qwen2-VL.

Totali per profilo (download): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` con composizione Qwen2-VL 23,56 GB (solo modalità commerciale, vedi nota 1).

Le immagini Docker stesse, prima di qualsiasi download di modelli: `latest` 3,34 GB decompressa,
`latest-cuda` 13,1 GB, `latest-cuda-legacy` 13,8 GB
([Distribuzione › Dimensione dell'immagine](DEPLOYMENT.md#dimensione-dellimmagine)). Le dimensioni di download
compresse non sono ancora misurate.

Modelli facoltativi, non inclusi nei totali:

| Modello | Dimensione | Attivazione |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | disattivato per impostazione predefinita |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | disattivato per impostazione predefinita, **deprecato** (preferisci `qrealign`) |
| Helsinki-NLP OPUS-MT, per lingua di destinazione (traduzione delle didascalie) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | solo per le lingue che abiliti |
| MediaPipe `face_landmarker.task` | 3,76 MB | solo quando `mediapipe` è installato |

`reverse_geocoder` non richiede download; i suoi dati sono inclusi nella wheel.

I pesi di SAMP-Net provengono dalla
[release model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
Se vedi `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (rete offline o
con restrizioni), scarica il file e mettilo in `pretrained_models/samp_net.pth`.

## Dipendenze

### Pacchetti richiesti

| Pacchetto | Scopo |
|---------|---------|
| `torch`, `torchvision` | Framework di deep learning (installato separatamente, vedi sopra) |
| `open-clip-torch` | Embedding/tagging CLIP (profili legacy/8gb) |
| `pyiqa` | TOPIQ e altri modelli di qualità/estetica |
| `opencv-python` | Elaborazione delle immagini |
| `pillow` | Caricamento immagini, incl. PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF richiede pillow>=11.3) |
| `imagehash` | Hashing percettivo per il rilevamento delle raffiche |
| `rawpy` | Supporto ai file RAW |
| `fastapi`, `uvicorn` | Server API |
| `pyjwt` | Autenticazione JWT |
| `numpy` | Operazioni numeriche |
| `tqdm` | Barre di avanzamento |
| `exifread` | Estrazione dei metadati EXIF |
| `insightface` | Rilevamento e riconoscimento dei volti |
| `transformers`, `accelerate` | Modelli SigLIP/BiRefNet/VLM (profili 8gb+) |
| `scipy` | Calcolo scientifico |
| `hdbscan` | Clustering dei volti (porta con sé scikit-learn) |
| `reverse_geocoder` | Geocodifica inversa per il GPS |
| `psutil` | Auto-regolazione dell'elaborazione a lotti (monitoraggio del sistema) |
| `aiosqlite` | SQLite asincrono per gli endpoint di lettura FastAPI |
| `sqlite-vec` | Ricerca semantica su disco (ripiega su una cache NumPy in memoria); `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | Foto JPEG XL e anteprime dei DNG uniti di Lightroom Classic 13+ (HDR/Panorama/Enhance) |

Tutti questi sono in `requirements.txt` tranne `pyiqa` e `insightface`, che sono in `requirements.restricted.txt` (vedi [Installazione commerciale e pacchetti con restrizioni](#installazione-commerciale-e-pacchetti-con-restrizioni)). Nessun profilo richiede pacchetti di base aggiuntivi.

### Pacchetti opzionali

Ognuno sblocca una funzionalità; senza di esso la funzionalità viene saltata o si usa un'alternativa.

| Pacchetto | Sblocca | Senza di esso |
|---------|---------|-----------|
| `watchdog` | Modalità watch (`--watch`); **non è in `requirements.txt`**, installa con `pip install .[watch]` | `--watch` non disponibile |
| `pillow-heif` | Decodifica HEIF/HEIC | File HEIF/HEIC saltati |
| `rawpy` | Decodifica RAW (CR2/CR3/NEF/ARW/…), già in `requirements.txt` | File RAW saltati |
| `cuml`, `cupy` | Clustering dei volti su GPU (conda + CUDA) | Clustering su CPU tramite `hdbscan` (predefinito) |
| `onnxruntime-gpu` | Rilevamento dei volti su GPU, **al posto di** `onnxruntime` ([dettagli](#onnx-runtime-per-il-rilevamento-dei-volti)) | `onnxruntime` per CPU (più lento) |
| `aesthetic-predictor-v2-5` | Scorer `aesthetic_v25` (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, disattivato per impostazione predefinita). **Deprecato** (AGPL-3.0, non mantenuto dal 2024-12-18); preferisci `qrealign`, che non richiede pacchetti aggiuntivi | `aesthetic_v25` non disponibile |
| `darktable-cli` (di sistema) | Esportazione RAW/profilo darktable dal viewer | Solo download dell'originale/incorporato |
| `exiftool` (di sistema) | Migliore estrazione EXIF/GPS | Ricade su `exifread`, poi PIL |

## Requisiti delle funzionalità

La maggior parte di Facet funziona ovunque (CPU, qualsiasi profilo). Alcune funzionalità richiedono una GPU, un **profilo
VRAM** superiore, un pacchetto opzionale, oppure la **password di modifica** del viewer o il ruolo
**superadmin**. Tag utilizzati nella documentazione:
`[GPU]` · `[16gb/24gb]` (profilo VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Funzionalità | GPU | Profilo | Autenticazione | Pacchetto opzionale |
|---------|:---:|---------|:----:|------------------|
| Punteggio / scansione (base) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Estetica TOPIQ | sì | `16gb`/`24gb` | — | — |
| IQA supplementare (TOPIQ IAA, NR-Face, LIQE) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Embedding SigLIP 2 | sì | `16gb`/`24gb` | — | — |
| Tagging VLM (Qwen3.5) | sì | `16gb`/`24gb` | — | — |
| Modello compositivo (SAMP-Net) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Salienza del soggetto (BiRefNet) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Didascalie IA (genera / visualizza) | sì | `16gb`/`24gb` | edition (generazione) | — |
| Didascalie IA (modifica) | sì | `16gb`/`24gb` | edition | — |
| Critica VLM | sì | `16gb`/`24gb` | edition (generazione) | — |
| Rilevamento / estrazione volti (InsightFace) | consigliata (la CPU funziona, ma lentamente) | qualsiasi | — | — |
| Clustering dei volti (HDBSCAN) | no (CPU) | qualsiasi | — | `cuml`/`cupy` (accelerazione GPU opzionale) |
| Ricerca semantica | no | qualsiasi | — | `sqlite-vec` (ripiega su NumPy) |
| Decodifica RAW / HEIF | no | qualsiasi | — | `rawpy` / `pillow-heif` |
| Modalità watch (`--watch`) | no | qualsiasi | — | `watchdog` |
| Estrazione GPS / esportazione darktable | no | qualsiasi | — | `exiftool` / `darktable-cli` |
| Valutazioni, preferiti, modifiche a volti e persone, selezione | no | qualsiasi | edition | — |
| Avvio delle scansioni dall'interfaccia web | no | qualsiasi | edition (utente singolo) / superadmin (multiutente) | — |
| Multi-utente (valutazioni e ruoli per utente) | no | qualsiasi | basata sui ruoli | — |

La password di modifica e i ruoli utente sono impostati in `scoring_config.json`; vedi
[Configurazione](CONFIGURATION.md).

> Nessuna GPU locale? Punta il tagging VLM, le didascalie e la critica verso un server Ollama remoto o
> compatibile con OpenAI tramite `vlm_backend` in `scoring_config.json`. Queste funzionalità
> funzionano allora anche sui profili `legacy`/`8gb`.

## Risoluzione dei conflitti di dipendenze

I pacchetti ML di Facet (`torch`, `open-clip-torch`, `insightface`, …) portano con sé molte
dipendenze, e installarli uno a uno può farli entrare in conflitto.

**Sintomi:** ogni installazione chiede ancora un altro pacchetto; conflitti di versione tra
`torch`, `numpy`, `huggingface-hub` o `open-clip-torch`; `pip install` riesce ma
`import` fallisce.

**1. Installa tutto in una volta:** `pip install -r requirements.txt`, così pip risolve l'intero
grafo. Non installare i pacchetti singolarmente
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Usa [uv](https://docs.astral.sh/uv/)**: `uv` risolve l'intero grafo prima di
installare:

```bash
pip install uv
uv pip install -r requirements.txt
# Con l'indice CUDA per PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Ricomincia da capo:** `deactivate`, `rm -rf venv`, e rifai
l'[installazione manuale](#installazione-manuale-senza-installsh) (oppure riesegui `install.sh`).

### Problemi di rilevamento della GPU

Se la tua GPU non viene rilevata (comune con le schede più recenti), esegui:

```bash
python facet.py --doctor
```

Controlla il supporto CUDA di PyTorch e il driver, e suggerisce il comando pip giusto. Intercetta anche
ciò che `torch.cuda.is_available()` non vede: una GPU per cui il PyTorch installato non ha kernel (ad es. serie RTX 50 su una build CUDA
precedente alla 12.8). In quel caso Facet ricade sulla CPU invece di andare in crash, e `--doctor` indica
la correzione: in Docker, il tag di immagine giusto (`ghcr.io/ncoevoet/facet:latest-cuda-legacy` per
Maxwell/Pascal/Volta); su bare metal, il giusto `--index-url`.

Per simulare l'hardware a scopo di test:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Client Angular

Serve solo per lo sviluppo o per build personalizzate; `install.sh` e l'immagine Docker
lo compilano già.

```bash
cd client
npm install
npm run build    # Build di produzione → client/dist/
npm start        # Server di sviluppo su http://localhost:4200 (inoltra l'API a :5000)
```

> **Avvisi di `npm audit`:** la maggior parte dei risultati riguarda dipendenze di sviluppo usate in fase di build che non
> arrivano mai al browser. Esaminali prima di eseguire `npm audit fix`, che può effettuare il downgrade o
> rimuovere dei pacchetti.
