# Installazione

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · **Italiano** · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md)

Facet funziona sulla tua macchina. Scegli la sezione che corrisponde alla tua
configurazione, copia il blocco e hai finito. La metà [Avanzate](#avanzate) in fondo
serve solo quando ne hai bisogno.

## Quale installazione fa per me?

| La tua situazione | Vai a |
|----------------|-------|
| Windows, macOS o Linux, e vuoi solo che funzioni | [Installa con Docker](#installa-con-docker) |
| Linux o macOS, e preferisci non usare i container | [Installa senza Docker](#installa-senza-docker) |
| Un NAS, o un server che vuoi raggiungere da altre macchine | [Distribuzione](DEPLOYMENT.md) |

## Quale profilo si adatta al mio hardware?

Facet include quattro *profili*. Un profilo è semplicemente un insieme di modelli IA
dimensionato per la tua macchina — ne scegli uno durante l'installazione e puoi
cambiarlo in seguito.

| Il tuo hardware | Profilo | Cosa ottieni |
|---------------|---------|--------------|
| Nessuna scheda grafica | `legacy` | Tutto funziona — punteggio, volti, tag, selezione, la galleria — solo più lentamente. |
| Scheda NVIDIA, 6–14 GB | `8gb` | Gli stessi modelli di `legacy`, eseguiti sulla scheda grafica invece che sul processore. |
| Scheda NVIDIA, 14–20 GB | `16gb` | Il punteggio fotografico più accurato, oltre a tag e didascalie IA scritti dalla macchina. |
| Scheda NVIDIA, 20 GB o più | `24gb` | I modelli più grandi, più spiegazioni scritte della composizione di una foto. |
| Mac Apple Silicon (M1–M4) | scelto per te | Facet usa i core grafici del Mac e dimensiona il profilo in base alla tua memoria. |

Non sai quanta memoria ha la tua scheda? Salta pure — il blocco *Rilevamento automatico*
qui sotto lo scopre al posto tuo.

## Installa con Docker

Ti serve [Docker](https://docs.docker.com/get-started/get-docker/). Se la tua macchina
ha una scheda NVIDIA, ti serve anche l'
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
in modo che Docker possa raggiungerla — su Windows questo significa eseguire Facet dentro
WSL2 ([guida passo passo](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia)).

Ogni blocco qui sotto parte da zero. Scegline **uno**.

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

### Comandi di uso quotidiano

La galleria è vuota finché non valuti le tue foto. Dentro Docker la tua cartella foto si
chiama sempre `/data/photos`, qualunque sia il suo nome sulla tua macchina:

```bash
docker compose exec facet python facet.py /data/photos   # valuta le tue foto
docker compose logs -f                                   # osserva cosa sta facendo
docker compose down                                      # fermalo
```

Per riavviarlo in seguito, riesegui la stessa riga `docker compose … up -d` che hai
usato sopra.

## Installa senza Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` trova la tua scheda grafica, installa tutto ciò che le corrisponde e compila
la galleria web. Poi, ogni volta che usi Facet:

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

Su un Mac Apple Silicon questo usa automaticamente i core grafici del Mac. Poi, ogni
volta che usi Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # valuta le tue foto
python viewer.py                       # avvia la galleria
```

Apri <http://localhost:5000>.

> **Porta 5000 già occupata?** macOS la usa per AirPlay. Avvia la galleria con
> `python viewer.py --port 5001` e apri invece <http://localhost:5001>.

### Windows

Usa [Docker](#installa-con-docker). Per usare una scheda NVIDIA su Windows, segui la
[guida WSL2](DEPLOYMENT.md#windows-wsl2-con-una-gpu-nvidia) — è il percorso testato.

## Primo avvio: cosa aspettarsi

- **Un download.** La prima scansione scarica i modelli IA per il tuo profilo — circa
  4,7 GB per `legacy`, 6,9 GB per `8gb`, 14,6 GB per `16gb`, 19,1 GB per `24gb`
  (dettaglio completo in [Dimensioni dei download](#dimensioni-dei-download)). Succede
  una sola volta; le esecuzioni successive partono subito.
- **Nessuna configurazione.** Non c'è nulla da configurare. Facet crea il proprio
  database alla prima scansione e viene fornito con impostazioni già funzionanti.
- **Le tue foto non vengono modificate.** La scansione si limita a leggerle; i risultati
  finiscono nel database di Facet. Riscrivere voti e parole chiave nei tuoi file è
  un'azione separata, che avvii tu ([Interoperabilità](INTEROP.md)).
- **Tempo.** Una prima scansione di una libreria grande richiede tempo, ed è nettamente
  più lenta su un processore che su una scheda grafica. L'avanzamento viene mostrato
  via via, e puoi sfogliare la galleria mentre lavora.

## Verifica che funzioni

```bash
python facet.py --doctor                             # senza Docker
docker compose exec facet python facet.py --doctor   # con Docker
```

Questo stampa cosa ha trovato Facet: la tua scheda grafica, il profilo scelto e ciò che
manca. Se la galleria è in esecuzione, <http://localhost:5000/health> risponde `ok`.

Qualcosa non funziona? Vedi [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze)
e [Problemi di rilevamento della GPU](#problemi-di-rilevamento-della-gpu) più sotto.

---

# Avanzate

Tutto ciò che segue è facoltativo: cosa fa davvero l'installazione, come modificarla, e
il riferimento completo alle dipendenze.

- [Impostazioni Docker che puoi modificare](#impostazioni-docker-che-puoi-modificare)
- [Scegliere il profilo manualmente](#scegliere-il-profilo-manualmente)
- [Installazione manuale, senza install.sh](#installazione-manuale-senza-installsh)
- [Opzioni di install.sh e scorciatoie del Makefile](#opzioni-di-installsh-e-scorciatoie-del-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime per il rilevamento dei volti](#onnx-runtime-per-il-rilevamento-dei-volti)
- [Clustering dei volti su GPU con RAPIDS cuML](#clustering-dei-volti-su-gpu-con-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Dimensioni dei download](#dimensioni-dei-download)
- [Dipendenze](#dipendenze)
- [Requisiti delle funzionalità](#requisiti-delle-funzionalità)
- [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze)
- [Client Angular](#client-angular)

## Impostazioni Docker che puoi modificare

Le leve di distribuzione risiedono in `.env` (copia `.env.example`):

| Chiave | Predefinito | Scopo |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Cartella host montata in lettura-scrittura su `/data/photos` (scrivibile per permettere di scrivere i sidecar XMP accanto agli originali) |
| `PORT` | `5000` | Porta host per la galleria |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — sovrascrive `models.vram_profile` senza modificare alcun JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Percorso del database dentro il container, mantenuto sul bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` della configurazione | Innesco del riaddestramento del ranker personale, per chi valuta molte foto |

Un `scoring_config.default.json` sanificato è incorporato nell'immagine come
configurazione di partenza. `docker-entrypoint.sh` lo copia, solo al primo avvio, nel
file persistente `./facet-config/scoring_config.json` che `docker-compose.yml` monta già
(come `FACET_CONFIG=/config/scoring_config.json` dentro il container) — quindi il
container funziona senza alcuna configurazione lato host, e ogni scrittura della
configurazione a runtime (la migrazione della password del viewer, i pesi, le priorità, i
contesti di scoring) ora sopravvive a un `docker compose down && up`. Modifica
direttamente `./facet-config/scoring_config.json` per personalizzare a mano pesi,
password del viewer o categorie; un file già esistente non viene mai sovrascritto.

Le cache dei modelli risiedono in volumi con nome gestiti da Docker (`facet-hf-cache`,
`facet-torch-cache`, `facet-insightface`, `facet-pretrained`), quindi l'immagine non
legge mai le cache della tua macchina e i modelli sopravvivono ai riavvii.
`docker compose down -v` li elimina e forza un nuovo download.

L'immagine include `exiftool` ma **non** darktable, quindi il download opzionale del
profilo RAW/darktable del viewer resta inerte a meno di estendere l'immagine con un
binario `darktable-cli`. Tutto il resto funziona comunque.

## Scegliere il profilo manualmente

I file per profilo (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) impostano ciascuno
`FACET_VRAM_PROFILE` e, per i profili GPU, riservano il dispositivo NVIDIA.
`docker-compose.gpu.yml` è l'alternativa generica: riserva la GPU ma lascia il profilo
alla `vram_profile` propria della configurazione (predefinito `auto`).

Due immagini vengono pubblicate a partire da un solo `Dockerfile`:
`ghcr.io/ncoevoet/facet:latest` è una build snella solo CPU (~3,3 GB decompressa su
disco, valore approssimativo — scaricarla trasferisce meno, 4,18 GB compressi; vedi
[Dimensioni dei download](#dimensioni-dei-download)), `ghcr.io/ncoevoet/facet:latest-cuda`
include CUDA e RAPIDS cuML (~21 GB decompressa su disco, approssimativo; 7,33 GB
compressi da scaricare) ed è quella scaricata dai profili GPU. Entrambe sono solo
`linux/amd64` — su una macchina ARM,
compila in locale con `docker compose build` invece di scaricare l'immagine.
`docker compose build` (o `up --build`) compila sempre a partire da questo repository;
vedi gli argomenti di build `BASE_IMAGE`, `STRIP_TORCH` e `INSTALL_CUML` nel `Dockerfile`.

Senza Docker, la stessa scelta è una variabile d'ambiente o una chiave di configurazione:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Le soglie esatte applicate da `auto` sono in
[Configurazione › Rilevamento automatico della VRAM](CONFIGURATION.md#rilevamento-automatico-della-vram).

## Installazione manuale, senza install.sh

Richiede Python 3.12 (funziona anche 3.10+) e Node.js 20+ per la build della galleria.

```bash
# 1. Crea e attiva un ambiente virtuale
python3 -m venv venv
source venv/bin/activate

# 2. Installa prima PyTorch, con l'URL dell'indice corrispondente alla tua versione CUDA.
#    cu128 è per CUDA 12.8+/13.x; usa cu118 per CUDA 11.8, cu124 per CUDA 12.4.
#    In caso di dubbio, copia il comando da https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Installa il resto in un colpo solo, così pip può risolvere l'intero grafo insieme.
#    requirements.txt include già transformers e accelerate, necessari per
#    i modelli SigLIP/BiRefNet/VLM usati dai profili 8gb+.
pip install -r requirements.txt

# 4. Installa UN SOLO ONNX Runtime per il rilevamento dei volti (vedi la tabella sotto)
pip install onnxruntime-gpu>=1.17.0   # oppure: pip install onnxruntime>=1.15.0

# 5. Compila la galleria web
cd client && npm install && npx ng build && cd ..

# 6. Eseguilo
python facet.py /path/to/photos
python viewer.py
```

Verifica l'ambiente in un'unica riga:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Riscontri errori? Vedi [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze).

## Opzioni di install.sh e scorciatoie del Makefile

`install.sh` individua un Python 3.10+, crea il `venv`, rileva il sistema operativo e la
GPU (Apple Silicon → Metal, altrimenti `nvidia-smi` → build CUDA corrispondente),
installa PyTorch, la variante corretta di ONNX Runtime, `requirements.txt`,
`transformers` e `accelerate`, verifica la presenza di `exiftool`, compila il client
Angular e controlla ogni import.

| Flag | Effetto |
|------|--------|
| `--cpu` | Forza PyTorch solo per CPU (senza CUDA) |
| `--cuda VERSION` | Sovrascrive la versione di CUDA rilevata (es. `--cuda 12.8`) |
| `--skip-client` | Salta la compilazione del frontend Angular |
| `--no-uv` | Usa pip invece di uv |

| Target Make | Esegue |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, rilevamento automatico o solo CPU |
| `make client` | Ricompila il frontend Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU o NVIDIA |
| `make test` / `make test-cov` | pytest, con o senza coverage |
| `make clean` | Rimuove `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool offre la migliore estrazione EXIF per ogni formato. Senza di esso Facet ricade
su `exifread` (una libreria Python che gestisce tutti i formati RAW), poi su PIL (solo
JPEG/TIFF/DNG).

| Sistema operativo | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Scarica da [exiftool.org](https://exiftool.org/) |

## ONNX Runtime per il rilevamento dei volti

Il rilevamento dei volti (InsightFace) funziona su ONNX Runtime, disponibile in varianti
CPU e GPU. Installane esattamente una:

| Configurazione | Comando |
|--------|---------|
| Solo CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Verifica la tua versione di CUDA con `nvidia-smi` — viene stampata nell'angolo in alto a
destra. Per passare da un'installazione CPU a GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## Clustering dei volti su GPU con RAPIDS cuML

Per database di volti di grandi dimensioni (oltre 80k volti), cuML accelera
notevolmente il clustering. Richiede un ambiente conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# oppure: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

Quando cuML è disponibile, il clustering usa automaticamente la GPU
(`face_clustering.use_gpu` in `scoring_config.json`). L'immagine Docker CUDA lo include
già, quindi i profili containerizzati `8gb`/`16gb`/`24gb` eseguono il clustering sulla
GPU senza passaggi aggiuntivi; `legacy` esegue sempre il clustering sul processore.

## Apple Silicon (Metal/MPS)

Non serve alcun pacchetto GPU separato. Installa con `bash install.sh`, poi verifica che
`python facet.py --doctor` riporti `Facet runtime device: mps`. Facet abilita per
impostazione predefinita il fallback su CPU di PyTorch per gli operatori non supportati.
Per confrontare:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Imposta `FACET_DEVICE=cpu` per disattivare l'accelerazione, oppure `FACET_DEVICE=mps`
per richiederla (e fallire in modo chiaro se non è disponibile). InsightFace resta sul
processore perché è un modello ONNX Runtime, non un modello PyTorch.

Metal non ha memoria video dedicata, quindi `vram_profile: "auto"` viene dimensionato
sulla memoria unificata totale:

| Memoria unificata totale | Profilo scelto da `auto` |
|----------------------|----------------------------|
| meno di 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB e oltre | `24gb` |

Ogni soglia richiede all'incirca il doppio dell'impronta di memoria dei modelli del
profilo, perché la memoria unificata è condivisa con macOS, il window server e ogni
altra applicazione in esecuzione — un Mac che ricorre allo swap è più lento di uno su un
profilo più piccolo. Un profilo configurato esplicitamente viene sempre rispettato così
com'è, quindi impostane uno per scavalcare queste soglie in entrambe le direzioni.

## Dimensioni dei download

I modelli si scaricano al primo utilizzo in `~/.cache/huggingface/` (modelli Hugging
Face), `~/.cache/torch/hub/` (pesi PyIQA) e `~/.insightface/` (rilevamento/riconoscimento
dei volti), oppure nei volumi Docker con nome. `samp_net.pth`, `u2netp.pth`,
`face_landmarker.task` e `aesthetic_predictor_weights.pth` della testa estetica CLIP-MLP
(solo `legacy`/`8gb`) finiscono tutti in `pretrained_models/`, risolto rispetto alla radice
del repository anziché alla directory di lavoro del processo — in Docker è il volume
montato `facet-pretrained`, quindi nessuno di essi viene riscaricato alla ricreazione del
container. Nessun peso dei modelli è incorporato nell'immagine.

Le dimensioni seguenti sono decimali (GB = 10⁹ byte, MB = 10⁶ byte), misurate dalle
cache dei modelli locali e dall'API di Hugging Face.

| Modello | Dimensione | Profili |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embedding + tagging CLIP + estetica CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Testa estetica MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | solo `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embedding) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (tagging VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (tagging VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composizione) | 4,430 GB | nessun profilo per impostazione predefinita — solo se imposti manualmente `composition_model: "qwen2-vl-2b"` **e** `processing.mode: "single-pass"` |
| InsightFace buffalo_l (volti) | 289 MB scaricati / 630 MB su disco (lo zip resta accanto ai file `.onnx` estratti) | tutti |
| Pesi SAMP-Net (composizione) | 183 MB | tutti |
| U2-Net-P (sotto-modello di salienza di SAMP-Net) | 4,7 MB | stessi profili di SAMP-Net |
| BiRefNet_dynamic (salienza del soggetto) | 445 MB | tutti |
| TOPIQ NR (modello estetico) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estetica complementare) | 873 MB | tutti |
| TOPIQ NR-Face (qualità dei volti complementare) | 376 MB | tutti |
| LIQE (qualità/distorsione complementare) | 708 MB | tutti |
| timm resnet50.a1_in1k (backbone PyIQA condiviso) | 102 MB | tutti |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **attivo di default** (`"auto"` si risolve in attivo su ogni profilo tranne `legacy`) |

Totali per profilo (download): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` con `composition_model: "qwen2-vl-2b"` e
`processing.mode: "single-pass"` 23,56 GB (la sostituzione manuale rimpiazza
SAMP-Net/U2-Net-P invece di sommarsi ad essi).

Per riferimento, scaricare l'immagine Docker stessa (prima di qualsiasi download di
modelli) trasferisce `ghcr.io/ncoevoet/facet:latest` a 4,18 GB compressi e
`:latest-cuda` a 7,33 GB compressi, secondo gli attuali manifest del registro.

Modelli opzionali non conteggiati nei totali sopra:

| Modello | Dimensione | Attivazione |
|-------|------|----------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | disattivato di default |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | disattivato di default, **deprecato** (AGPL-3.0, non mantenuto a monte — preferire `qrealign`) |
| Helsinki-NLP OPUS-MT, per lingua di destinazione (traduzione delle didascalie) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | solo per le lingue attivate |
| MediaPipe `face_landmarker.task` | 3,76 MB | solo se `mediapipe` è installato |

`reverse_geocoder` non richiede alcun download: i suoi dati sono inclusi nel wheel.

I pesi SAMP-Net provengono dalla
[release model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)
del progetto. Se il download fallisce (rete offline o con restrizioni) vedrai
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` — scarica il file
manualmente e posizionalo in `pretrained_models/samp_net.pth`.

## Dipendenze

### Pacchetti richiesti

| Pacchetto | Scopo |
|---------|---------|
| `torch`, `torchvision` | Framework di deep learning (installato separatamente, vedi sopra) |
| `open-clip-torch` | Embedding/tagging CLIP (profili legacy/8gb) |
| `pyiqa` | TOPIQ e altri modelli di qualità/estetica |
| `opencv-python` | Elaborazione delle immagini |
| `pillow` | Caricamento delle immagini |
| `imagehash` | Hashing percettivo per il rilevamento delle raffiche |
| `rawpy` | Supporto file RAW |
| `fastapi`, `uvicorn` | Server API |
| `pyjwt` | Autenticazione JWT |
| `numpy` | Operazioni numeriche |
| `tqdm` | Barre di avanzamento |
| `exifread` | Estrazione dei metadati EXIF |
| `insightface` | Rilevamento e riconoscimento dei volti |
| `transformers`, `accelerate` | Modelli SigLIP/BiRefNet/VLM (profili 8gb+) |
| `scipy` | Calcolo scientifico |
| `hdbscan` | Clustering dei volti (include scikit-learn) |
| `reverse_geocoder` | Geocodifica inversa per il GPS |
| `psutil` | Auto-tuning dell'elaborazione in batch (monitoraggio di sistema) |
| `aiosqlite` | SQLite asincrono per gli endpoint di lettura di FastAPI |
| `sqlite-vec` | KNN su disco per ricerca semantica e somiglianza (ricorre alla cache di embedding NumPy in memoria se mancante) |

Tutti questi sono presenti in `requirements.txt`; nessun profilo richiede pacchetti di
base aggiuntivi.

### Pacchetti opzionali

Ognuno abilita una funzionalità; senza di esso la funzionalità viene saltata o si usa un
fallback.

| Pacchetto | Abilita / scopo | Senza di esso |
|---------|-------------------|-----------|
| `watchdog` | Modalità watch (il daemon `--watch` riesamina i nuovi file) — **non in `requirements.txt`**; viene incluso solo tramite `pip install .[watch]`, quindi chi usa direttamente `requirements.txt` non ottiene `--watch` | `--watch` non disponibile |
| `pillow-heif` | Decodifica HEIF/HEIC | I file HEIF/HEIC vengono saltati |
| `rawpy` | Decodifica RAW (CR2/CR3/NEF/ARW/…) | I file RAW vengono saltati (già in `requirements.txt` di base) |
| `cuml`, `cupy` | Clustering dei volti accelerato da GPU (conda + CUDA) | Il clustering viene eseguito su CPU tramite `hdbscan` (predefinito) |
| `onnxruntime-gpu` | Rilevamento dei volti accelerato da GPU | CPU `onnxruntime` (più lento) |
| `aesthetic-predictor-v2-5` | Tier IQA esteso — scorer `aesthetic_v25` (`pip install -e .[iqa-extended]`; `iqa_extended.aesthetic_v25` in `scoring_config.json`, disattivato per impostazione predefinita). **Deprecato** — AGPL-3.0, non mantenuto dal 2024-12-18; preferisci `qrealign`, che non richiede alcun pacchetto aggiuntivo (incluso nella dipendenza di base `pyiqa`) | `aesthetic_v25` non disponibile |
| `darktable-cli` (sistema) | Esportazione RAW/profili darktable dal viewer | Viene offerto solo il download originale/incorporato |
| `exiftool` (sistema) | Migliore estrazione EXIF/GPS | Ricorre a `exifread`, poi a PIL |

## Requisiti delle funzionalità

La maggior parte di Facet funziona ovunque (CPU, qualsiasi profilo). Alcune
funzionalità richiedono una GPU, un **profilo VRAM** superiore, un pacchetto opzionale,
oppure la **password di modifica** del viewer o il ruolo **superadmin**. Tag utilizzati
in tutta la documentazione:
`[GPU]` · `[16gb/24gb]` (profilo VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Funzionalità | GPU | Profilo | Autenticazione | Pacchetto opzionale |
|---------|:---:|---------|:----:|------------------|
| Punteggio / scansione (base) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Estetica TOPIQ | sì | `16gb`/`24gb` | — | — |
| IQA supplementare (TOPIQ IAA, NR-Face, LIQE) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Embedding SigLIP 2 | sì | `16gb`/`24gb` | — | — |
| Tagging VLM (Qwen3.5) | sì | `16gb`/`24gb` | — | — |
| Modello compositivo (SAMP-Net) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Composizione (Qwen2-VL) | sì | `24gb` | — | — |
| Salienza del soggetto (BiRefNet) | opzionale | qualsiasi (`legacy` = CPU) | — | — |
| Didascalie IA (genera / visualizza) | sì | `16gb`/`24gb` | — | — |
| Didascalie IA (modifica) | sì | `16gb`/`24gb` | edition | — |
| Critica VLM | sì | `16gb`/`24gb` | — | — |
| Rilevamento / estrazione volti (InsightFace) | consigliata (la CPU funziona, ma lentamente) | qualsiasi | — | — |
| Clustering dei volti (HDBSCAN) | no (CPU) | qualsiasi | — | `cuml`/`cupy` (accelerazione GPU opzionale) |
| Ricerca semantica | no | qualsiasi | — | `sqlite-vec` (ripiega su NumPy) |
| Decodifica RAW / HEIF | no | qualsiasi | — | `rawpy` / `pillow-heif` |
| Modalità watch (`--watch`) | no | qualsiasi | — | `watchdog` |
| Estrazione GPS / esportazione darktable | no | qualsiasi | — | `exiftool` / `darktable-cli` |
| Valutazioni, preferiti, modifiche a volti e persone, selezione | no | qualsiasi | edition | — |
| Avvio delle scansioni dall'interfaccia web | no | qualsiasi | superadmin | — |
| Multi-utente (valutazioni e ruoli per utente) | no | qualsiasi | basata sui ruoli | — |

> Il *clustering* dei volti viene eseguito su CPU per impostazione predefinita
> (`hdbscan` standalone); `cuml`/`cupy` aggiungono solo un'accelerazione GPU opzionale —
> **non** sono obbligatori. La password di modifica e i ruoli utente sono configurati in
> `scoring_config.json` — vedi [Configurazione](CONFIGURATION.md) per l'autenticazione.

> Nessuna GPU locale? Punta il tagging VLM, le didascalie e la critica verso un server
> Ollama remoto o compatibile con OpenAI tramite `vlm_backend` in `scoring_config.json`
> — queste funzionalità funzionano allora anche sui profili CPU `legacy`/`8gb`.

## Risoluzione dei conflitti di dipendenze

Facet ha molte dipendenze ML (`torch`, `open-clip-torch`, `insightface`, ecc.) che a
loro volta richiedono le proprie dipendenze transitive. pip risolve le dipendenze in
sequenza, il che può portare a errori a catena in cui l'installazione di un pacchetto ne
danneggia un altro.

**Sintomi:** l'installazione dei pacchetti uno per uno genera errori che chiedono di
installare ancora un altro pacchetto; conflitti di versione tra `torch`, `numpy`,
`huggingface-hub` o `open-clip-torch`; `pip install` riesce ma `import` fallisce in fase
di esecuzione.

**1. Installa tutto in una volta** — `pip install -r requirements.txt` fornisce a pip
l'intero grafo delle dipendenze da risolvere. Non installare i pacchetti individualmente
(`pip install open-clip-torch && pip install insightface && ...`); questo impedisce a
pip di risolvere il grafo completo.

**2. Usa [uv](https://docs.astral.sh/uv/) invece di pip** — `uv` risolve in anticipo il
grafo completo delle dipendenze prima di installare qualsiasi cosa, evitando conflitti a
catena:

```bash
pip install uv
uv pip install -r requirements.txt
# Con l'indice CUDA per PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Ricomincia da capo** — se il tuo ambiente è già in uno stato danneggiato, esegui
`deactivate`, `rm -rf venv`, e rifai [Installazione manuale, senza install.sh](#installazione-manuale-senza-installsh)
(oppure riesegui semplicemente `install.sh`).

### Problemi di rilevamento della GPU

Se la tua GPU non viene rilevata (comune con schede più recenti), esegui lo strumento
diagnostico:

```bash
python facet.py --doctor
```

Verifica il supporto CUDA di PyTorch e la compatibilità del driver, e suggerisce il
comando pip corretto. Puoi anche simulare l'hardware per i test:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Client Angular

Necessario solo per lo sviluppo o build personalizzate — `install.sh` e l'immagine
Docker lo compilano già.

```bash
cd client
npm install
npm run build    # Build di produzione → client/dist/
npm start        # Server di sviluppo su http://localhost:4200 (inoltra le API a :5000)
```

> **Avvisi di `npm audit`:** Angular include un albero profondo di dipendenze
> transitive e `npm audit` segnalerà problemi, la maggior parte dei quali
> riguarda dipendenze di sviluppo usate al momento della build che non
> arrivano mai al browser. Esamina l'elenco prima di eseguire
> `npm audit fix` — potrebbe silenziosamente effettuare il downgrade o
> rimuovere pacchetti.
