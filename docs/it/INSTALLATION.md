# Installazione

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · **Italiano** · [Español](../es/INSTALLATION.md)

## Avvio rapido

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # rileva automaticamente la GPU, crea il venv, installa tutto

# Attiva il venv creato da install.sh — lo script di installazione non può farlo
# al posto tuo perché viene eseguito in una subshell.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # verifica la tua configurazione
```

`install.sh` crea il venv, rileva GPU/CUDA, installa PyTorch con l'index URL corrispondente, la variante corretta di ONNX Runtime, le restanti dipendenze e compila il frontend Angular.

**Opzioni:**
| Flag | Effetto |
|------|--------|
| `--cpu` | Forza PyTorch solo per CPU (senza CUDA) |
| `--cuda VERSION` | Sovrascrive la versione di CUDA rilevata (es. `--cuda 12.8`) |
| `--skip-client` | Salta la compilazione del frontend Angular |
| `--no-uv` | Usa pip invece di uv |

È disponibile anche un `Makefile`: `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Installazione manuale

### Requisiti di sistema

- Python 3.12 (supportato 3.10+)
- `exiftool` (pacchetto di sistema, opzionale ma consigliato)

#### Installazione di exiftool

exiftool offre la migliore estrazione EXIF per tutti i formati. Senza di esso, l'app ricorre a `exifread` (libreria Python, gestisce tutti i formati RAW) e poi a PIL (solo JPEG/TIFF/DNG).

| Sistema operativo | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Scarica da [exiftool.org](https://exiftool.org/) |

### Ambiente Python

```bash
# Crea l'ambiente virtuale
python3 -m venv venv
source venv/bin/activate

# Installa prima PyTorch con l'URL dell'indice CUDA corretto
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Installa le dipendenze (tutte insieme per una corretta risoluzione delle dipendenze).
# requirements.txt include già transformers e accelerate, necessari per
# i modelli SigLIP/BiRefNet/VLM usati dai profili 8gb+.
pip install -r requirements.txt
```

> **Riscontri errori di dipendenze?** Consulta [Risoluzione dei conflitti di dipendenze](#risoluzione-dei-conflitti-di-dipendenze) più sotto.

### Configurazione GPU

#### PyTorch con CUDA

Installa da [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) in base alla tua versione di CUDA. Lo script di installazione lo fa automaticamente.

#### ONNX Runtime per il rilevamento dei volti

Scegline UNO in base alla tua configurazione:

| Opzione | Comando |
|--------|---------|
| Solo CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Verifica la tua versione di CUDA:** esegui `nvidia-smi` e guarda l'angolo in alto a destra per "CUDA Version: X.X".

Se passi dalla versione CPU a quella GPU:
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML per il clustering dei volti su GPU (opzionale)

Per database di volti di grandi dimensioni (oltre 80K volti), il clustering accelerato da GPU tramite cuML velocizza notevolmente il clustering dei volti. Richiede un ambiente conda:

```bash
# Crea l'ambiente conda con supporto CUDA
conda create -n facet python=3.12
conda activate facet

# Installa cuML (scegli la tua versione di CUDA)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternativa: pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Installa le altre dipendenze
pip install -r requirements.txt
```

Quando cuML è disponibile, il clustering dei volti utilizza automaticamente la GPU (configurabile tramite `face_clustering.use_gpu` in `scoring_config.json`).

## Verifica dell'installazione

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Riepilogo delle dipendenze

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

Tutti questi sono presenti in `requirements.txt`; nessun profilo richiede pacchetti di base aggiuntivi.

### Pacchetti opzionali

Ognuno abilita una funzionalità; senza di esso la funzionalità viene saltata o si usa un fallback.

| Pacchetto | Abilita / scopo | Senza di esso |
|---------|-------------------|-----------|
| `sqlite-vec>=0.1.6` | KNN su disco per ricerca semantica e somiglianza | Ricorre alla cache di embedding NumPy in memoria |
| `watchdog` | Modalità watch (il daemon `--watch` riesamina i nuovi file) | `--watch` non disponibile |
| `pillow-heif` | Decodifica HEIF/HEIC | I file HEIF/HEIC vengono saltati |
| `rawpy` | Decodifica RAW (CR2/CR3/NEF/ARW/…) | I file RAW vengono saltati (già in `requirements.txt` di base) |
| `cuml`, `cupy` | Clustering dei volti accelerato da GPU (conda + CUDA) | Il clustering viene eseguito su CPU tramite `hdbscan` (predefinito) |
| `onnxruntime-gpu` | Rilevamento dei volti accelerato da GPU | CPU `onnxruntime` (più lento) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Tier IQA esteso (`pip install -e .[iqa-extended]`; `iqa_extended` in `scoring_config.json`, disattivato per impostazione predefinita) | Metriche IQA estese non disponibili |
| `darktable-cli` (sistema) | Esportazione RAW/profili darktable dal viewer | Viene offerto solo il download originale/incorporato |
| `exiftool` (sistema) | Migliore estrazione EXIF/GPS | Ricorre a `exifread`, poi a PIL |

## Risoluzione dei conflitti di dipendenze

Facet ha molte dipendenze ML (`torch`, `open-clip-torch`, `insightface`, ecc.) che a loro volta richiedono le proprie dipendenze transitive. pip risolve le dipendenze in sequenza, il che può portare a errori a catena in cui l'installazione di un pacchetto ne danneggia un altro.

### Sintomi

- L'installazione dei pacchetti uno per uno genera errori che chiedono di installare ancora un altro pacchetto
- Conflitti di versione tra `torch`, `numpy`, `huggingface-hub` o `open-clip-torch`
- `pip install` riesce ma `import` fallisce in fase di esecuzione

### Soluzioni

**1. Installa tutto in una volta** — fornisce a pip l'intero grafo delle dipendenze da risolvere:

```bash
pip install -r requirements.txt
```

**Non** installare i pacchetti individualmente (`pip install open-clip-torch && pip install insightface && ...`) — questo impedisce a pip di risolvere il grafo completo.

**2. Usa [uv](https://docs.astral.sh/uv/) invece di pip** — `uv` risolve in anticipo il grafo completo delle dipendenze prima di installare qualsiasi cosa, evitando conflitti a catena:

```bash
# Installa uv
pip install uv

# Installa tutte le dipendenze con risoluzione completa
uv pip install -r requirements.txt

# Con l'indice CUDA per PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Ricomincia da capo** — se il tuo ambiente è già in uno stato danneggiato:

```bash
deactivate
rm -rf venv
python3 -m venv venv && source venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

### Problemi di rilevamento della GPU

Se la tua GPU non viene rilevata (comune con GPU più recenti come la RTX 5070 Ti), esegui lo strumento diagnostico:

```bash
python facet.py --doctor
```

Questo verifica il supporto CUDA di PyTorch, la compatibilità del driver e suggerisce il comando pip install corretto. Puoi anche simulare scenari GPU per i test:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Primo avvio

Al primo avvio, Facet scarica automaticamente:
- Modello CLIP (ViT-L-14): ~1,7 GB
- Modello InsightFace buffalo_l: ~400 MB
- Pesi SAMP-Net (tutti i profili): ~50 MB

I modelli vengono memorizzati nella cache in posizioni standard (`~/.cache/` o `~/.insightface/`).

## Client Angular (opzionale)

Necessario solo per lo sviluppo o build personalizzate; `install.sh` lo compila già.

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

> **Porta 5000 su macOS:** il ricevitore AirPlay di ControlCenter è in ascolto
> sulla porta 5000 per impostazione predefinita. Avvia il viewer con
> `python viewer.py --port 5001` (oppure imposta la variabile d'ambiente
> `PORT`) per evitare il conflitto.

### Download manuale di SAMP-Net

Il download automatico dei pesi SAMP-Net potrebbe non riuscire (l'URL della release su GitHub non è più disponibile). Se vedi:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Scaricalo manualmente:
1. Scarica da [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view)
2. Posiziona il file in `pretrained_models/samp_net.pth`
