# Installation

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · **Deutsch** · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md)

## Schnellstart

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # erkennt die GPU automatisch, erstellt das venv, installiert alles

# Aktiviere das von install.sh erstellte venv — das Installationsskript kann dies nicht tun
# für dich, weil es in einer Subshell läuft.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # überprüfe deine Einrichtung
```

`install.sh` erstellt die venv, erkennt GPU/CUDA, installiert PyTorch mit der passenden Index-URL, die richtige ONNX-Runtime-Variante, die übrigen Abhängigkeiten und baut das Angular-Frontend.

**Optionen:**
| Flag | Wirkung |
|------|--------|
| `--cpu` | Erzwingt reines CPU-PyTorch (kein CUDA) |
| `--cuda VERSION` | Überschreibt die erkannte CUDA-Version (z. B. `--cuda 12.8`) |
| `--skip-client` | Überspringt den Build des Angular-Frontends |
| `--no-uv` | Verwendet pip statt uv |

Ein `Makefile` steht ebenfalls zur Verfügung: `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Manuelle Installation

### Systemanforderungen

- Python 3.12 (3.10+ unterstützt)
- `exiftool` (Systempaket, optional, aber empfohlen)

#### exiftool installieren

exiftool bietet die beste EXIF-Extraktion für alle Formate. Ohne es greift die App auf `exifread` (Python-Bibliothek, behandelt alle RAW-Formate) und dann auf PIL (nur JPEG/TIFF/DNG) zurück.

| OS | Befehl |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download von [exiftool.org](https://exiftool.org/) |

### Python-Umgebung

```bash
# Virtuelle Umgebung erstellen
python3 -m venv venv
source venv/bin/activate

# Zuerst PyTorch mit der korrekten CUDA-Index-URL installieren
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Abhängigkeiten installieren (alle auf einmal für eine korrekte Abhängigkeitsauflösung).
# requirements.txt enthält bereits transformers und accelerate, benötigt für
# die SigLIP/BiRefNet/VLM-Modelle, die von den 8gb+-Profilen verwendet werden.
pip install -r requirements.txt
```

> **Treten Abhängigkeitsfehler auf?** Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben) weiter unten.

### GPU-Einrichtung

#### PyTorch mit CUDA

Installieren Sie von [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) entsprechend Ihrer CUDA-Version. Das Installationsskript erledigt dies automatisch.

#### ONNX Runtime für die Gesichtserkennung

Wählen Sie EINE Variante passend zu Ihrem Setup:

| Option | Befehl |
|--------|---------|
| Nur CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Prüfen Sie Ihre CUDA-Version:** Führen Sie `nvidia-smi` aus und sehen Sie sich in der oberen rechten Ecke "CUDA Version: X.X" an.

Beim Wechsel von der CPU- zur GPU-Version:
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML für GPU-Gesichtsclustering (optional)

Für große Gesichtsdatenbanken (80K+ Gesichter) beschleunigt GPU-gestütztes Clustering via cuML das Gesichtsclustering erheblich. Erfordert eine conda-Umgebung:

```bash
# Conda-Umgebung mit CUDA-Unterstützung erstellen
conda create -n facet python=3.12
conda activate facet

# cuML installieren (wähle deine CUDA-Version)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternative: pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Weitere Abhängigkeiten installieren
pip install -r requirements.txt
```

Wenn cuML verfügbar ist, nutzt das Gesichtsclustering automatisch die GPU (konfigurierbar über `face_clustering.use_gpu` in `scoring_config.json`).

## Installation überprüfen

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Übersicht der Abhängigkeiten

### Erforderliche Pakete

| Paket | Zweck |
|---------|---------|
| `torch`, `torchvision` | Deep-Learning-Framework (separat installiert, siehe oben) |
| `open-clip-torch` | CLIP-Embeddings/Tagging (legacy/8gb-Profile) |
| `pyiqa` | TOPIQ und weitere Qualitäts-/Ästhetikmodelle |
| `opencv-python` | Bildverarbeitung |
| `pillow` | Bildladen |
| `imagehash` | Perzeptuelles Hashing für die Serienbilderkennung |
| `rawpy` | RAW-Dateiunterstützung |
| `fastapi`, `uvicorn` | API-Server |
| `pyjwt` | JWT-Authentifizierung |
| `numpy` | Numerische Operationen |
| `tqdm` | Fortschrittsbalken |
| `exifread` | EXIF-Metadaten-Extraktion |
| `insightface` | Gesichtserkennung und -wiedererkennung |
| `transformers`, `accelerate` | SigLIP/BiRefNet/VLM-Modelle (8gb+-Profile) |
| `scipy` | Wissenschaftliches Rechnen |
| `hdbscan` | Gesichtsclustering (zieht scikit-learn nach) |
| `reverse_geocoder` | Reverse-Geocoding für GPS |

Alle diese sind in `requirements.txt` enthalten; kein Profil benötigt zusätzliche Basis-Pakete.

### Optionale Pakete

Jedes schaltet eine Funktion frei; ohne es wird die Funktion übersprungen oder ein Fallback verwendet.

| Paket | Schaltet frei / Zweck | Ohne es |
|---------|-------------------|-----------|
| `sqlite-vec>=0.1.6` | KNN auf Festplatte für Semantische Suche & Ähnlichkeit | Greift auf den In-Memory-NumPy-Embedding-Cache zurück |
| `watchdog` | Watch-Modus (`--watch`-Daemon scannt neue Dateien erneut) | `--watch` nicht verfügbar |
| `pillow-heif` | HEIF/HEIC-Dekodierung | HEIF/HEIC-Dateien werden übersprungen |
| `rawpy` | RAW-Dekodierung (CR2/CR3/NEF/ARW/…) | RAW-Dateien werden übersprungen (bereits in der Basis-`requirements.txt`) |
| `cuml`, `cupy` | GPU-gestütztes Gesichtsclustering (conda + CUDA) | Clustering läuft auf der CPU via `hdbscan` (Standard) |
| `onnxruntime-gpu` | GPU-gestützte Gesichtserkennung | CPU-`onnxruntime` (langsamer) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Erweiterte IQA-Stufe (`pip install -e .[iqa-extended]`; `iqa_extended` in `scoring_config.json`, standardmäßig aus) | Erweiterte IQA-Metriken nicht verfügbar |
| `darktable-cli` (System) | RAW-/Darktable-Profil-Export aus dem Viewer | Nur Original-/eingebetteter Download angeboten |
| `exiftool` (System) | Beste EXIF-/GPS-Extraktion | Greift auf `exifread`, dann PIL zurück |

## Abhängigkeitskonflikte beheben

Facet hat viele ML-Abhängigkeiten (`torch`, `open-clip-torch`, `insightface` usw.), die ihre eigenen transitiven Abhängigkeiten nachziehen. pip löst Abhängigkeiten sequenziell auf, was zu kaskadierenden Fehlern führen kann, bei denen die Installation eines Pakets ein anderes beschädigt.

### Symptome

- Die Installation der Pakete einzeln löst Fehler aus, die zur Installation eines weiteren Pakets auffordern
- Versionskonflikte zwischen `torch`, `numpy`, `huggingface-hub` oder `open-clip-torch`
- `pip install` ist erfolgreich, aber `import` schlägt zur Laufzeit fehl

### Lösungen

**1. Alles auf einmal installieren** — gibt pip den vollständigen Abhängigkeitsgraphen zum Auflösen:

```bash
pip install -r requirements.txt
```

Installieren Sie Pakete **nicht** einzeln (`pip install open-clip-torch && pip install insightface && ...`) — dies verhindert, dass pip den vollständigen Graphen auflöst.

**2. Verwenden Sie [uv](https://docs.astral.sh/uv/) statt pip** — `uv` löst den vollständigen Abhängigkeitsgraphen im Voraus auf, bevor irgendetwas installiert wird, und vermeidet so kaskadierende Konflikte:

```bash
# uv installieren
pip install uv

# Alle Abhängigkeiten mit vollständiger Auflösung installieren
uv pip install -r requirements.txt

# Mit CUDA-Index für PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Neu beginnen** — falls Ihre Umgebung bereits in einem defekten Zustand ist:

```bash
deactivate
rm -rf venv
python3 -m venv venv && source venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

### Probleme bei der GPU-Erkennung

Falls Ihre GPU nicht erkannt wird (häufig bei neueren GPUs wie der RTX 5070 Ti), führen Sie das Diagnosewerkzeug aus:

```bash
python facet.py --doctor
```

Dies prüft die CUDA-Unterstützung von PyTorch, die Treiberkompatibilität und schlägt den korrekten pip-install-Befehl vor. Sie können auch GPU-Szenarien zum Testen simulieren:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Erster Start

Beim ersten Start lädt Facet automatisch herunter:
- CLIP-Modell (ViT-L-14): ~1,7 GB
- InsightFace-buffalo_l-Modell: ~400 MB
- SAMP-Net-Gewichte (alle Profile): ~50 MB

Modelle werden an Standardorten zwischengespeichert (`~/.cache/` oder `~/.insightface/`).

## Angular-Client (optional)

Nur für die Entwicklung oder eigene Builds erforderlich; `install.sh` baut ihn bereits.

```bash
cd client
npm install
npm run build    # Produktions-Build → client/dist/
npm start        # Dev-Server unter http://localhost:4200 (leitet die API an :5000 weiter)
```

> **`npm audit`-Warnungen:** Angular zieht einen tiefen Baum transitiver
> Abhängigkeiten nach, und `npm audit` meldet Befunde, von denen die meisten
> in Build-time-Dev-Abhängigkeiten liegen, die nie den Browser erreichen.
> Prüfen Sie die Liste, bevor Sie `npm audit fix` ausführen — es kann
> stillschweigend Pakete herabstufen oder entfernen.

> **macOS Port 5000:** Der AirPlay-Empfänger des Control Centers lauscht
> standardmäßig auf 5000. Starten Sie den Viewer mit `python viewer.py --port 5001`
> (oder setzen Sie die Umgebungsvariable `PORT`), um den Konflikt zu vermeiden.

### SAMP-Net manueller Download

Der automatische Download der SAMP-Net-Gewichte kann fehlschlagen (die URL des GitHub-Release ist nicht mehr verfügbar). Wenn Sie Folgendes sehen:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Manuell herunterladen:
1. Download von [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view)
2. Datei unter `pretrained_models/samp_net.pth` ablegen
