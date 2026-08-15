# Installation

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · **Deutsch** · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md)

Facet läuft auf Ihrem eigenen Rechner. Wählen Sie den Abschnitt, der zu Ihrer Einrichtung
passt, kopieren Sie den Block, und Sie sind fertig. Die Hälfte [Fortgeschritten](#fortgeschritten)
am Ende ist nur da, wenn Sie sie brauchen.

## Welche Installation passt zu mir?

| Ihre Situation | Weiter zu |
|----------------|-------|
| Windows, macOS oder Linux, und Sie wollen es einfach zum Laufen bringen | [Installation mit Docker](#installation-mit-docker) |
| Linux oder macOS, und Sie bevorzugen keine Container | [Installation ohne Docker](#installation-ohne-docker) |
| Ein NAS, oder ein Server, den Sie von anderen Rechnern aus erreichen wollen | [Bereitstellung](DEPLOYMENT.md) |

## Welches Profil passt zu meiner Hardware?

Facet bringt vier *Profile* mit. Ein Profil ist einfach ein Satz von KI-Modellen, der auf
Ihren Rechner zugeschnitten ist — Sie wählen eines bei der Installation und können es
später ändern.

| Ihre Hardware | Profil | Was Sie erhalten |
|---------------|---------|--------------|
| Keine Grafikkarte | `legacy` | Alles funktioniert — Bewertung, Gesichter, Tags, Auswahl, die Galerie — nur langsamer. |
| NVIDIA-Karte, 6–14 GB | `8gb` | Dieselben Modelle wie bei `legacy`, ausgeführt auf der Grafikkarte statt auf dem Prozessor. |
| NVIDIA-Karte, 14–20 GB | `16gb` | Die stärkste Fotobewertung, plus KI-Tags und vom Rechner geschriebene Bildbeschreibungen. |
| NVIDIA-Karte, 20 GB oder mehr | `24gb` | Die größten Modelle, plus geschriebene Erklärungen zur Bildkomposition. |
| Apple-Silicon-Mac (M1–M4) | für Sie gewählt | Facet nutzt die Grafikkerne des Mac und bemisst das Profil anhand Ihres Speichers. |

Nicht sicher, wie viel Speicher Ihre Karte hat? Überspringen Sie das — der Block
**Automatische Erkennung** weiter unten findet es für Sie heraus.

## Installation mit Docker

Sie benötigen [Docker](https://docs.docker.com/get-started/get-docker/). Wenn Ihr Rechner
über eine NVIDIA-Karte verfügt, benötigen Sie außerdem das
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html),
damit Docker darauf zugreifen kann — unter Windows bedeutet das, Facet innerhalb von WSL2
auszuführen ([Schritt-für-Schritt-Anleitung](DEPLOYMENT.md#windows-wsl2-mit-einer-nvidia-gpu)).

Jeder Block unten beginnt bei null. Wählen Sie **einen**.

### Meine Hardware automatisch erkennen

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose up -d
```

Öffnen Sie <http://localhost:5000>.

### Keine Grafikkarte

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Öffnen Sie <http://localhost:5000>.

### 8-GB-Grafikkarte

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Öffnen Sie <http://localhost:5000>.

### 16-GB-Grafikkarte

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Öffnen Sie <http://localhost:5000>.

### 24-GB-Grafikkarte

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Öffnen Sie <http://localhost:5000>.

### Befehle für den Alltag

Die Galerie ist leer, bis Sie Ihre Fotos bewerten. Innerhalb von Docker heißt Ihr
Fotoordner immer `/data/photos`, egal wie er auf Ihrem Rechner heißt:

```bash
docker compose exec facet python facet.py /data/photos   # Ihre Fotos bewerten
docker compose logs -f                                   # beobachten, was gerade passiert
docker compose down                                      # stoppen
```

Um es später erneut zu starten, führen Sie dieselbe `docker compose … up -d`-Zeile
erneut aus, die Sie oben verwendet haben.

## Installation ohne Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` findet Ihre Grafikkarte, installiert alles Passende und baut die
Web-Galerie. Danach, jedes Mal, wenn Sie Facet verwenden:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # Ihre Fotos bewerten
python viewer.py                       # Galerie starten
```

Öffnen Sie <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

Auf einem Apple-Silicon-Mac nutzt dies automatisch die Grafikkerne des Mac. Danach,
jedes Mal, wenn Sie Facet verwenden:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # Ihre Fotos bewerten
python viewer.py                       # Galerie starten
```

Öffnen Sie <http://localhost:5000>.

> **Port 5000 bereits belegt?** macOS nutzt ihn für AirPlay. Starten Sie die Galerie
> stattdessen mit `python viewer.py --port 5001` und öffnen Sie <http://localhost:5001>.

### Windows

Verwenden Sie [Docker](#installation-mit-docker). Um eine NVIDIA-Karte unter Windows zu
nutzen, folgen Sie der [WSL2-Anleitung](DEPLOYMENT.md#windows-wsl2-mit-einer-nvidia-gpu)
— das ist der getestete Weg.

## Erster Start: was Sie erwartet

- **Ein Download.** Der erste Scan lädt die KI-Modelle für Ihr Profil herunter — etwa
  3–4 GB für `legacy` und `8gb`, 10–11 GB für `16gb`, 18 GB für `24gb`. Das geschieht
  einmalig; spätere Läufe starten sofort.
- **Keine Einrichtung.** Es gibt nichts zu konfigurieren. Facet erstellt seine Datenbank
  beim ersten Scan und liefert funktionierende Einstellungen mit.
- **Ihre Fotos werden nicht verändert.** Der Scan liest sie nur; die Ergebnisse landen in
  Facets eigener Datenbank. Bewertungen und Schlagwörter zurück in Ihre Dateien zu
  schreiben, ist eine separate Aktion, die Sie selbst auslösen ([Interop](INTEROP.md)).
- **Zeit.** Ein erster Scan einer großen Bibliothek dauert eine Weile und ist auf einem
  Prozessor deutlich langsamer als auf einer Grafikkarte. Der Fortschritt wird laufend
  ausgegeben, und Sie können die Galerie durchstöbern, während sie läuft.

## Prüfen, ob es funktioniert hat

```bash
python facet.py --doctor                             # ohne Docker
docker compose exec facet python facet.py --doctor   # mit Docker
```

Dies gibt aus, was Facet gefunden hat: Ihre Grafikkarte, das gewählte Profil und alles
Fehlende. Wenn die Galerie läuft, antwortet <http://localhost:5000/health> mit `ok`.

Funktioniert etwas nicht? Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben)
und [Probleme bei der GPU-Erkennung](#probleme-bei-der-gpu-erkennung) weiter unten.

---

# Fortgeschritten

Alles ab hier ist optional: was die Installation tatsächlich tut, wie Sie sie ändern,
und die vollständige Abhängigkeitsreferenz.

- [Docker-Einstellungen, die Sie ändern können](#docker-einstellungen-die-sie-ändern-können)
- [Das Profil selbst wählen](#das-profil-selbst-wählen)
- [Manuelle Installation ohne install.sh](#manuelle-installation-ohne-installsh)
- [install.sh-Optionen und Makefile-Kurzbefehle](#installsh-optionen-und-makefile-kurzbefehle)
- [exiftool](#exiftool)
- [ONNX Runtime für die Gesichtserkennung](#onnx-runtime-für-die-gesichtserkennung)
- [GPU-Gesichtsclustering mit RAPIDS cuML](#gpu-gesichtsclustering-mit-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Downloadgrößen](#downloadgrößen)
- [Abhängigkeiten](#abhängigkeiten)
- [Funktionsanforderungen](#funktionsanforderungen)
- [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben)
- [Angular-Client](#angular-client)

## Docker-Einstellungen, die Sie ändern können

Bereitstellungs-Einstellungen liegen in `.env` (kopieren Sie `.env.example`):

| Schlüssel | Standard | Zweck |
|-----|---------|------|
| `PHOTOS_DIR` | `./photos` | Host-Ordner, lesbar/schreibbar unter `/data/photos` eingehängt (beschreibbar, damit XMP-Sidecars neben den Originalen geschrieben werden können) |
| `PORT` | `5000` | Host-Port für die Galerie |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — überschreibt `models.vram_profile`, ohne JSON zu bearbeiten |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Datenbankpfad im Container, gehalten auf dem `./data`-Bind-Mount |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` der Konfiguration | Auslöser für das Neutrainieren des persönlichen Rankers, für Nutzer mit vielen Bewertungen |

Eine bereinigte `scoring_config.default.json` ist als aktive Konfiguration ins Image
eingebacken, sodass der Container ohne jede Host-Einrichtung läuft. Um Gewichte, das
Viewer-Passwort oder Kategorien anzupassen: `cp scoring_config.default.json scoring_config.json`,
bearbeiten Sie sie, und kommentieren Sie dann den Konfigurations-Mount in
`docker-compose.yml` ein.

Modell-Caches liegen in von Docker verwalteten benannten Volumes (`facet-hf-cache`,
`facet-torch-cache`, `facet-insightface`, `facet-pretrained`), sodass das Image nie die
eigenen Caches Ihres Rechners liest und die Modelle Neustarts überdauern.
`docker compose down -v` löscht sie und erzwingt einen erneuten Download.

Das Image bündelt `exiftool`, aber **nicht** darktable, sodass der optionale
RAW-/Darktable-Profil-Download des Viewers inaktiv bleibt, es sei denn, Sie erweitern
das Image um eine `darktable-cli`-Binärdatei. Alles andere funktioniert unabhängig
davon.

## Das Profil selbst wählen

Die profilspezifischen Dateien (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) setzen jeweils
`FACET_VRAM_PROFILE` und reservieren bei den GPU-Profilen das NVIDIA-Gerät.
`docker-compose.gpu.yml` ist die generische Alternative: Sie reserviert die GPU,
überlässt das Profil aber dem eigenen `vram_profile` der Konfiguration (Standard
`auto`).

Zwei Images werden aus einem `Dockerfile` veröffentlicht: `ghcr.io/ncoevoet/facet:latest`
ist ein schlanker CPU-Build (~3,3 GB), `ghcr.io/ncoevoet/facet:latest-cuda` bringt CUDA
und RAPIDS cuML mit (~21 GB) und ist das, was die GPU-Profile ziehen. Beide sind
ausschließlich `linux/amd64` — bauen Sie auf einem ARM-Rechner lokal mit
`docker compose build`, statt zu ziehen. `docker compose build` (oder `up --build`)
baut immer aus diesem Repository; siehe die Build-Argumente `BASE_IMAGE`,
`STRIP_TORCH` und `INSTALL_CUML` im `Dockerfile`.

Ohne Docker ist dieselbe Wahl eine Umgebungsvariable oder ein Konfigurationsschlüssel:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Die genauen Schwellenwerte, die `auto` anwendet, finden Sie unter
[Konfiguration › Automatische VRAM-Erkennung](CONFIGURATION.md#automatische-vram-erkennung).

## Manuelle Installation ohne install.sh

Erfordert Python 3.12 (3.10+ funktioniert) und Node.js 20+ für den Galerie-Build.

```bash
# 1. Virtuelle Umgebung erstellen und aktivieren
python3 -m venv venv
source venv/bin/activate

# 2. Zuerst PyTorch installieren, mit der Index-URL passend zu Ihrer CUDA-Version.
#    cu128 zielt auf CUDA 12.8+/13.x ab; verwenden Sie cu118 für CUDA 11.8, cu124 für CUDA 12.4.
#    Im Zweifel kopieren Sie den Befehl von https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Den Rest in einem Rutsch installieren, damit pip den gesamten Graphen auf einmal auflösen kann.
#    requirements.txt enthält bereits transformers und accelerate, benötigt für die
#    SigLIP/BiRefNet/VLM-Modelle, die von den 8gb+-Profilen verwendet werden.
pip install -r requirements.txt

# 4. EINE ONNX Runtime für die Gesichtserkennung installieren (siehe Tabelle unten)
pip install onnxruntime-gpu>=1.17.0   # oder: pip install onnxruntime>=1.15.0

# 5. Die Web-Galerie bauen
cd client && npm install && npx ng build && cd ..

# 6. Ausführen
python facet.py /path/to/photos
python viewer.py
```

Überprüfen Sie die Umgebung in einer Zeile:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Stoßen Sie auf Fehler? Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben).

## install.sh-Optionen und Makefile-Kurzbefehle

`install.sh` sucht ein Python 3.10+, legt das `venv` an, erkennt das Betriebssystem und
die GPU (Apple Silicon → Metal, sonst `nvidia-smi` → passender CUDA-Build), installiert
PyTorch, die richtige ONNX Runtime, `requirements.txt`, `transformers` und `accelerate`,
prüft auf `exiftool`, baut den Angular-Client und verifiziert jeden Import.

| Flag | Wirkung |
|------|--------|
| `--cpu` | Erzwingt reines CPU-PyTorch (kein CUDA) |
| `--cuda VERSION` | Überschreibt die erkannte CUDA-Version (z. B. `--cuda 12.8`) |
| `--skip-client` | Überspringt den Build des Angular-Frontends |
| `--no-uv` | Verwendet pip statt uv |

| Make-Ziel | Führt aus |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, automatisch erkannt oder nur CPU |
| `make client` | Angular-Frontend neu bauen |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU oder NVIDIA |
| `make test` / `make test-cov` | pytest, mit oder ohne Coverage |
| `make clean` | `venv`, `client/dist`, `client/node_modules` entfernen |

## exiftool

exiftool liefert die beste EXIF-Extraktion für jedes Format. Ohne es greift Facet auf
`exifread` zurück (eine Python-Bibliothek, die alle RAW-Formate verarbeitet), dann auf
PIL (nur JPEG/TIFF/DNG).

| OS | Befehl |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download von [exiftool.org](https://exiftool.org/) |

## ONNX Runtime für die Gesichtserkennung

Die Gesichtserkennung (InsightFace) läuft über ONNX Runtime, das es in CPU- und
GPU-Varianten gibt. Installieren Sie genau eine:

| Setup | Befehl |
|--------|---------|
| Nur CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Prüfen Sie Ihre CUDA-Version mit `nvidia-smi` — sie wird oben rechts angezeigt. So
wechseln Sie eine bestehende Installation von CPU auf GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## GPU-Gesichtsclustering mit RAPIDS cuML

Für große Gesichtsdatenbanken (80.000+ Gesichter) beschleunigt cuML das Clustering
erheblich. Es benötigt eine conda-Umgebung:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# oder: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

Wenn cuML verfügbar ist, nutzt das Clustering automatisch die GPU
(`face_clustering.use_gpu` in `scoring_config.json`). Das Docker-CUDA-Image bringt es
bereits mit, sodass containerisierte `8gb`/`16gb`/`24gb`-Profile ohne zusätzlichen
Schritt auf der GPU clustern; `legacy` clustert immer auf dem Prozessor.

## Apple Silicon (Metal/MPS)

Es wird kein separates GPU-Paket benötigt. Installieren Sie mit `bash install.sh` und
bestätigen Sie anschließend, dass `python facet.py --doctor` `Facet runtime device: mps`
meldet. Facet aktiviert standardmäßig den CPU-Fallback von PyTorch für nicht
unterstützte Operatoren. Zum Vergleich:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Setzen Sie `FACET_DEVICE=cpu`, um die Beschleunigung zu deaktivieren, oder
`FACET_DEVICE=mps`, um sie zu erzwingen (und klar zu scheitern, wenn sie nicht
verfügbar ist). InsightFace bleibt auf dem Prozessor, weil es ein
ONNX-Runtime-Modell ist und kein PyTorch-Modell.

Metal hat keinen dedizierten Grafikspeicher, daher wird `vram_profile: "auto"` anhand
des gesamten Unified Memory bemessen:

| Gesamter Unified Memory | Von `auto` gewähltes Profil |
|----------------------|----------------------------|
| unter 16 GB | `legacy` |
| 16-31 GB | `8gb` |
| 32-47 GB | `16gb` |
| 48 GB und mehr | `24gb` |

Jede Schwelle verlangt etwa das Doppelte des Modellspeicherbedarfs des Profils, denn
der Unified Memory wird mit macOS, dem Window-Server und jeder anderen laufenden
Anwendung geteilt — ein Mac, der auslagert, ist langsamer als einer mit einem
kleineren Profil. Ein ausdrücklich konfiguriertes Profil wird immer so übernommen, wie
es konfiguriert ist — setzen Sie eines, um diese Schwellen in beide Richtungen zu
übersteuern.

## Downloadgrößen

Modelle werden bei der ersten Verwendung nach `~/.cache/` und `~/.insightface/`
heruntergeladen (oder in die benannten Docker-Volumes). Keine Modellgewichte sind ins
Image eingebacken.

| Modell | Größe | Profile |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (Embeddings + Tagging) | ~1,6 GB | `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (Embeddings) | ~4,3 GB | `16gb`/`24gb` |
| Qwen3.5-2B (VLM-Tagging) | ~4,2 GB | `16gb` |
| Qwen3.5-4B (VLM-Tagging) | ~8 GB | `24gb` |
| Qwen2-VL-2B (Komposition) | ~4,2 GB | `24gb` |
| InsightFace buffalo_l (Gesichter) | ~600 MB | alle |
| SAMP-Net-Gewichte (Komposition) | ~175 MB | alle (`24gb` verwendet stattdessen Qwen2-VL) |
| BiRefNet_dynamic (Motiverkennung) | ~424 MB | alle |
| U2-Net-P (Salienz-Hilfsmodell) | ~5 MB | alle |

Summen pro Profil: `legacy`/`8gb` ~3–4 GB · `16gb` ~10–11 GB · `24gb` ~18 GB.

Die SAMP-Net-Gewichte stammen aus dem
[model-weights-v1-Release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)
des Projekts. Falls dieser Download fehlschlägt (offline oder eingeschränktes
Netzwerk), sehen Sie `Failed to download SAMP-Net weights: HTTP Error 404: Not Found`
— laden Sie die Datei manuell herunter und legen Sie sie unter
`pretrained_models/samp_net.pth` ab.

## Abhängigkeiten

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

Alle diese sind in `requirements.txt` enthalten; kein Profil benötigt zusätzliche
Basis-Pakete.

### Optionale Pakete

Jedes schaltet eine Funktion frei; ohne es wird die Funktion übersprungen oder ein
Fallback verwendet.

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

Der Großteil von Facet läuft überall (CPU, jedes Profil). Einige Funktionen benötigen
eine GPU, ein höheres **VRAM-Profil**, ein optionales Paket oder das
**Bearbeitungspasswort** / die **Superadmin**-Rolle des Viewers. In der gesamten
Dokumentation verwendete Kennzeichnungen:
`[GPU]` · `[16gb/24gb]` (VRAM-Profil) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Funktion | GPU | Profil | Auth | Optionales Paket |
|---------|:---:|---------|:----:|------------------|
| Bewertung / Scan (Grundfunktion) | optional | beliebig (`legacy` = CPU) | — | — |
| TOPIQ-Ästhetik | ja | `16gb`/`24gb` | — | — |
| Ergänzende IQA (TOPIQ IAA, NR-Face, LIQE) | optional | beliebig (`legacy` = CPU) | — | — |
| SigLIP-2-Embeddings | ja | `16gb`/`24gb` | — | — |
| VLM-Tagging (Qwen3.5) | ja | `16gb`/`24gb` | — | — |
| Kompositionsmuster (SAMP-Net) | optional | beliebig (`legacy` = CPU) | — | — |
| Komposition (Qwen2-VL) | ja | `24gb` | — | — |
| Motiverkennung (BiRefNet) | optional | beliebig (`legacy` = CPU) | — | — |
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

> Das Gesichts-*Clustering* läuft standardmäßig über die CPU (eigenständiges
> `hdbscan`); `cuml`/`cupy` fügen nur optionale GPU-Beschleunigung hinzu — sie sind
> **nicht** erforderlich. Das Bearbeitungspasswort und die Benutzerrollen werden in
> `scoring_config.json` konfiguriert — siehe [Konfiguration](CONFIGURATION.md) für die
> Authentifizierung.

> Keine lokale GPU? Richten Sie VLM-Tagging, Beschreibungen und Kritik über
> `vlm_backend` in `scoring_config.json` auf einen entfernten Ollama- oder
> OpenAI-kompatiblen Server aus — diese Funktionen laufen dann auch auf den
> CPU-Profilen `legacy`/`8gb`.

## Abhängigkeitskonflikte beheben

Facet hat viele ML-Abhängigkeiten (`torch`, `open-clip-torch`, `insightface` usw.), die
ihre eigenen transitiven Abhängigkeiten nachziehen. pip löst Abhängigkeiten sequenziell
auf, was zu kaskadierenden Fehlern führen kann, bei denen die Installation eines
Pakets ein anderes beschädigt.

**Symptome:** Die Installation der Pakete einzeln löst Fehler aus, die zur Installation
eines weiteren Pakets auffordern; Versionskonflikte zwischen `torch`, `numpy`,
`huggingface-hub` oder `open-clip-torch`; `pip install` ist erfolgreich, aber `import`
schlägt zur Laufzeit fehl.

**1. Alles auf einmal installieren** — `pip install -r requirements.txt` gibt pip den
vollständigen Abhängigkeitsgraphen zum Auflösen. Installieren Sie Pakete **nicht**
einzeln (`pip install open-clip-torch && pip install insightface && ...`) — das
verhindert, dass pip den vollständigen Graphen auflöst.

**2. Verwenden Sie [uv](https://docs.astral.sh/uv/) statt pip** — `uv` löst den
vollständigen Abhängigkeitsgraphen im Voraus auf, bevor irgendetwas installiert wird,
und vermeidet so kaskadierende Konflikte:

```bash
pip install uv
uv pip install -r requirements.txt
# Mit dem CUDA-Index für PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Neu beginnen** — wenn Ihre Umgebung bereits defekt ist: `deactivate`,
`rm -rf venv`, und wiederholen Sie [Manuelle Installation](#manuelle-installation-ohne-installsh)
(oder führen Sie einfach `install.sh` erneut aus).

### Probleme bei der GPU-Erkennung

Wenn Ihre GPU nicht erkannt wird (häufig bei neueren Karten), führen Sie die Diagnose
aus:

```bash
python facet.py --doctor
```

Dies prüft die CUDA-Unterstützung von PyTorch und die Treiberkompatibilität und
schlägt den richtigen pip-Befehl vor. Sie können auch Hardware zum Testen simulieren:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular-Client

Nur für die Entwicklung oder eigene Builds erforderlich — `install.sh` und das
Docker-Image bauen ihn bereits.

```bash
cd client
npm install
npm run build    # Produktions-Build → client/dist/
npm start        # Dev-Server unter http://localhost:4200 (leitet die API an :5000 weiter)
```

> **`npm audit`-Warnungen:** Angular zieht einen tiefen Baum transitiver
> Abhängigkeiten nach, und `npm audit` meldet Befunde, von denen die meisten in
> Build-time-Dev-Abhängigkeiten liegen, die nie den Browser erreichen. Prüfen Sie die
> Liste, bevor Sie `npm audit fix` ausführen — es kann stillschweigend Pakete
> herabstufen oder entfernen.
