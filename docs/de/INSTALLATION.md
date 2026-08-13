# Installation

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · **Deutsch** · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md)

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

Auf Apple Silicon verwendet das Installationsskript das native macOS-Wheel von PyTorch, und Facet wählt automatisch das Metal-Backend (`mps`). Apples Unified Memory ist kein CUDA-VRAM: Das Modellprofil `auto` wird daher anhand des gesamten Unified Memory bemessen statt anhand eines Werts für dedizierten VRAM, den es dort nicht gibt — siehe [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps). Torch-basierte Modelle — CLIP, SAMP-Net, PyIQA und Salienz — können MPS nutzen; InsightFace läuft über ONNX Runtime auf der CPU. Setzen Sie `FACET_DEVICE=cpu`, um die Beschleunigung zu deaktivieren, oder `FACET_DEVICE=mps`, um MPS zu erzwingen (und klar zu scheitern, wenn es nicht verfügbar ist).

**Optionen:**
| Flag | Wirkung |
|------|--------|
| `--cpu` | Erzwingt reines CPU-PyTorch (kein CUDA) |
| `--cuda VERSION` | Überschreibt die erkannte CUDA-Version (z. B. `--cuda 12.8`) |
| `--skip-client` | Überspringt den Build des Angular-Frontends |
| `--no-uv` | Verwendet pip statt uv |

Ein `Makefile` steht ebenfalls zur Verfügung: `make install`, `make install-cpu`, `make run`, `make doctor`.

### Docker

`docker compose up` zieht ein veröffentlichtes Image von GHCR – kein lokaler Build, keine JSON-Bearbeitung. Zwei Varianten teilen sich ein `Dockerfile`: ein schlankes CPU-Image (`ghcr.io/ncoevoet/facet:latest`) und ein vollständiges CUDA-+-RAPIDS-cuML-Image (`:latest-cuda`) für GPU-Profile. Wählen Sie ein Profil über `FACET_VRAM_PROFILE`.

```bash
cp .env.example .env      # FACET_VRAM_PROFILE + PHOTOS_DIR setzen
docker compose up -d      # zieht :latest (CPU), Standardkonfiguration eingebacken

# GPU / pro Profil — ein Overlay hinzufügen (benötigt das NVIDIA Container Toolkit), zieht :latest-cuda:
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Overlays existieren für `legacy`, `8gb` und `16gb` (`docker-compose.{legacy,8gb,16gb}.yml`). Abhängigkeiten sind in `requirements.lock.txt` fixiert, und die cuML-GPU-Gesichtsclusterbildung ist fest im CUDA-Image enthalten, sodass GPU-Profile sofort auf der GPU clustern; das CPU-Image fällt auf CPU-HDBSCAN zurück. Modelle werden beim ersten Lauf einmalig in die Volumes `facet-hf-cache` / `facet-insightface` / `facet-pretrained` heruntergeladen. Bereitstellungs-Einstellungen liegen in `.env` (`FACET_VRAM_PROFILE`, `PHOTOS_DIR`, `PORT`, `DB_PATH`). `docker compose build` baut weiterhin aus dem Quellcode (siehe `Dockerfile` für die Build-Argumente `BASE_IMAGE`/`STRIP_TORCH`/`INSTALL_CUML`). Die vollständige Docker- + Windows/WSL2-Anleitung finden Sie unter [Deployment](DEPLOYMENT.md).

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

# Zuerst PyTorch mit der korrekten CUDA-Index-URL installieren.
# cu128 zielt auf CUDA 12.8+/13.x ab; für CUDA 11.8 verwenden Sie cu118, für CUDA 12.4 cu124.
# Im Zweifel wählen Sie den passenden Befehl auf https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Abhängigkeiten installieren (alle auf einmal für eine korrekte Abhängigkeitsauflösung).
# requirements.txt enthält bereits transformers und accelerate, benötigt für
# die SigLIP/BiRefNet/VLM-Modelle, die von den 8gb+-Profilen verwendet werden.
pip install -r requirements.txt
```

> **Treten Abhängigkeitsfehler auf?** Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben) weiter unten.

### GPU-Einrichtung

#### Apple Silicon (Metal/MPS)

Es wird kein separates GPU-Paket benötigt. Installieren Sie mit `bash install.sh` und prüfen Sie anschließend, dass `python facet.py --doctor` `Facet runtime device: mps` meldet. Facet aktiviert standardmäßig den CPU-Fallback von PyTorch für nicht unterstützte Operatoren. Zum Vergleich der Performance:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Die Gesichtserkennung von InsightFace bleibt auf der CPU, weil sie ein ONNX-Runtime-Modell ist und kein PyTorch-Modell.

Metal hat keinen dedizierten VRAM, daher wird `vram_profile: "auto"` anhand des vom System gemeldeten gesamten Unified Memory bemessen:

| Gesamter Unified Memory | Von `auto` gewähltes Profil |
|-------------------------|-----------------------------|
| unter 16 GB | `legacy` |
| 16-31 GB | `8gb` |
| 32-47 GB | `16gb` |
| 48 GB und mehr | `24gb` |

Jede Schwelle verlangt etwa das Doppelte des Modellspeicherbedarfs des Profils, denn der Unified Memory wird mit macOS, dem Window-Server und jeder anderen laufenden Anwendung geteilt — ein Mac, der auslagert, ist langsamer als einer mit einem kleineren Profil. Ein ausdrücklich konfiguriertes Profil wird immer so übernommen, wie es konfiguriert ist, auf Metal wie überall sonst: Setzen Sie eines, um diese Schwellen in beide Richtungen zu übersteuern.

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
| `psutil` | Auto-Tuning der Stapelverarbeitung (Systemüberwachung) |
| `aiosqlite` | Asynchrones SQLite für die FastAPI-Lese-Endpunkte |
| `sqlite-vec` | KNN auf Festplatte für Semantische Suche & Ähnlichkeit (greift auf den In-Memory-NumPy-Cache zurück, falls nicht vorhanden) |

Alle diese sind in `requirements.txt` enthalten; kein Profil benötigt zusätzliche Basis-Pakete.

### Optionale Pakete

Jedes schaltet eine Funktion frei; ohne es wird die Funktion übersprungen oder ein Fallback verwendet.

| Paket | Schaltet frei / Zweck | Ohne es |
|---------|-------------------|-----------|
| `watchdog` | Watch-Modus (`--watch`-Daemon scannt neue Dateien erneut) — **nicht in `requirements.txt`**; wird nur über `pip install .[watch]` nachgezogen, sodass direkte `requirements.txt`-Nutzer `--watch` nicht erhalten | `--watch` nicht verfügbar |
| `pillow-heif` | HEIF/HEIC-Dekodierung | HEIF/HEIC-Dateien werden übersprungen |
| `rawpy` | RAW-Dekodierung (CR2/CR3/NEF/ARW/…) | RAW-Dateien werden übersprungen (bereits in der Basis-`requirements.txt`) |
| `cuml`, `cupy` | GPU-gestütztes Gesichtsclustering (conda + CUDA) | Clustering läuft auf der CPU via `hdbscan` (Standard) |
| `onnxruntime-gpu` | GPU-gestützte Gesichtserkennung | CPU-`onnxruntime` (langsamer) |
| `aesthetic-predictor-v2-5` | Erweiterte IQA-Stufe — `aesthetic_v25`-Bewerter (`pip install -e .[iqa-extended]`; `iqa_extended.aesthetic_v25` in `scoring_config.json`, standardmäßig aus). **Veraltet** — AGPL-3.0, seit dem 2024-12-18 unmaintained; bevorzugen Sie `qrealign`, das kein zusätzliches Paket benötigt (es ist Teil der Basisabhängigkeit `pyiqa`) | `aesthetic_v25` nicht verfügbar |
| `darktable-cli` (System) | RAW-/Darktable-Profil-Export aus dem Viewer | Nur Original-/eingebetteter Download angeboten |
| `exiftool` (System) | Beste EXIF-/GPS-Extraktion | Greift auf `exifread`, dann PIL zurück |

## Funktionsanforderungen

Der Großteil von Facet läuft überall (CPU, jedes Profil). Einige Funktionen benötigen eine GPU, ein höheres **VRAM-Profil**, ein optionales Paket oder das **Bearbeitungspasswort** / die **Superadmin**-Rolle des Viewers. In der gesamten Dokumentation verwendete Kennzeichnungen:
`[GPU]` · `[16gb/24gb]` (VRAM-Profil) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Funktion | GPU | Profil | Auth | Optionales Paket |
|---------|:---:|---------|:----:|------------------|
| Bewertung / Scan (Grundfunktion) | optional | beliebig (`legacy` = CPU) | — | — |
| TOPIQ-Ästhetik | ja | `16gb`/`24gb` | — | — |
| Ergänzende IQA (TOPIQ IAA, NR-Face, LIQE) | ja | `8gb`/`16gb`/`24gb` | — | — |
| SigLIP-2-Embeddings | ja | `16gb`/`24gb` | — | — |
| VLM-Tagging (Qwen3.5) | ja | `16gb`/`24gb` | — | — |
| Kompositionsmuster (SAMP-Net) | optional | beliebig (`legacy` = CPU) | — | — |
| Komposition (Qwen2-VL) | ja | `24gb` | — | — |
| Motiverkennung (BiRefNet) | ja | `16gb`/`24gb` | — | — |
| KI-Beschreibungen (erzeugen / ansehen) | ja | `16gb`/`24gb` | — | — |
| KI-Beschreibungen (bearbeiten) | ja | `16gb`/`24gb` | edition | — |
| VLM-Kritik | ja | `16gb`/`24gb` | — | — |
| Gesichtserkennung / -extraktion (InsightFace) | empfohlen (CPU funktioniert, langsam) | beliebig | — | — |
| Gesichtsclustering (HDBSCAN) | nein (CPU) | beliebig | — | `cuml`/`cupy` (optionale GPU-Beschleunigung) |
| Semantische Suche | nein | beliebig | — | `sqlite-vec` (greift auf NumPy zurück) |
| RAW-/HEIF-Decodierung | nein | beliebig | — | `rawpy` / `pillow-heif` |
| Überwachungsmodus (`--watch`) | nein | beliebig | — | `watchdog` |
| GPS-Extraktion / Darktable-Export | nein | beliebig | — | `exiftool` / `darktable-cli` |
| Bewertungen, Favoriten, Gesichts- & Personenbearbeitungen, Auswahl | nein | beliebig | edition | — |
| Scans über die Web-Oberfläche auslösen | nein | beliebig | superadmin | — |
| Mehrbenutzerbetrieb (benutzerspezifische Bewertungen & Rollen) | nein | beliebig | rollenbasiert | — |

> Das Gesichts-*Clustering* läuft standardmäßig über die CPU (eigenständiges `hdbscan`); `cuml`/`cupy` fügen nur optionale GPU-Beschleunigung hinzu — sie sind **nicht** erforderlich. Das Bearbeitungspasswort und die Benutzerrollen werden in `scoring_config.json` konfiguriert — siehe [Konfiguration](CONFIGURATION.md) für die Authentifizierung.

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

**3. Neu beginnen** — falls Ihre Umgebung bereits in einem defekten Zustand ist: `deactivate`, `rm -rf venv` und bauen Sie sie neu auf, indem Sie die Schritte unter [Python-Umgebung](#python-umgebung) oben erneut ausführen.

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

Beim ersten Start lädt Facet automatisch das Embedding-Modell für Ihr Profil herunter:
- CLIP ViT-L-14 (legacy/8gb-Profile): ~1,7 GB — oder SigLIP 2 NaFlex SO400M (16gb/24gb-Profile), größer
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

Die SAMP-Net-Gewichte werden beim ersten Gebrauch automatisch aus dem Model-Weights-Release des Projekts heruntergeladen (`github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth`). Normalerweise ist kein manueller Schritt erforderlich.

Falls der automatische Download fehlschlägt (z. B. offline oder netzwerkbeschränkt), sehen Sie:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Dann manuell herunterladen:
1. Laden Sie `samp_net.pth` aus dem [model-weights-v1-Release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth) herunter (oder, als sekundärer Fallback, von [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view))
2. Datei unter `pretrained_models/samp_net.pth` ablegen
