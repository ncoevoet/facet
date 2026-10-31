# Installation

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · **Deutsch** · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md) · [简体中文](../zh/INSTALLATION.md)

Facet läuft auf Ihrem eigenen Rechner. Wählen Sie den Abschnitt, der zu Ihrer Einrichtung
passt, und kopieren Sie den Block. Der Teil [Fortgeschritten](#fortgeschritten) ist nur da,
wenn Sie ihn brauchen.

## Welche Installation passt zu mir?

Beide Wege führen dasselbe Facet aus; sie tauschen einfache Installation gegen Leistung.
Wählen Sie den, der zu Ihnen passt.

| | Docker | Ohne Docker |
|---|---|---|
| Installation | Ein Befehl: alles steckt im Image | `install.sh` (Linux, macOS) oder das Windows-Installationsprogramm richtet eine Python-Umgebung auf dem Rechner ein |
| Aktualisieren | Das neue Image holen | Den Code aktualisieren und `install.sh` erneut ausführen, oder das neue Windows-Installationsprogramm installieren |
| Leistung | Ein Container liegt zwischen Facet und Ihren Dateien und der Grafikkarte; unter Windows läuft er in WSL2 | Facet nutzt Grafikkarte und Dateien des Rechners direkt |

| Ihre Situation | Weiter zu |
|----------------|-------|
| Windows, macOS oder Linux, in einem Container | [Installation mit Docker](#installation-mit-docker) |
| Windows, macOS oder Linux, ohne Container | [Installation ohne Docker](#installation-ohne-docker) |
| Ein NAS, oder ein Server, den Sie von anderen Rechnern aus erreichen wollen | [Bereitstellung](DEPLOYMENT.md) |

## Welches Profil passt zu meiner Hardware?

Ein *Profil* ist ein Satz von KI-Modellen, der auf Ihren Rechner zugeschnitten ist. Sie
wählen eines bei der Installation und können es später ändern.

| Ihre Hardware | Profil | Was Sie erhalten |
|---------------|---------|--------------|
| Keine Grafikkarte | `legacy` | Alles funktioniert, nur langsamer. |
| NVIDIA-Karte, 6–14 GB | `8gb` | Die Modelle von `legacy`, ausgeführt auf der Grafikkarte. |
| NVIDIA-Karte, 14–20 GB | `16gb` | Die stärkste Bewertung, plus KI-Tags und Bildbeschreibungen. |
| NVIDIA-Karte, 20 GB oder mehr | `24gb` | Die größten Modelle, plus geschriebene Erklärungen zur Komposition. |
| Apple-Silicon-Mac (M1–M4) | für Sie gewählt | Nutzt die Grafikkerne des Mac; das Profil richtet sich nach dem Speicher. |

Nicht sicher, wie viel Speicher Ihre Karte hat? Nutzen Sie den Block *Meine Hardware
automatisch erkennen* weiter unten.

## Installation mit Docker

Sie benötigen [Docker](https://docs.docker.com/get-started/get-docker/). Mit einer NVIDIA-Karte
brauchen Sie außerdem das
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
Unter Windows bedeutet das, Facet innerhalb von WSL2 auszuführen
([Schritt-für-Schritt-Anleitung](DEPLOYMENT.md#windows-wsl2-mit-einer-nvidia-gpu)).

Jeder Block beginnt bei null. Wählen Sie **einen**.

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

### Ältere NVIDIA-Karte (Maxwell, Pascal, Volta)

Die GPU-Blöcke oben und `docker-compose.gpu.yml` ziehen `ghcr.io/ncoevoet/facet:latest-cuda`,
das `sm_75`-`sm_120` abdeckt (Turing bis Blackwell).

Für eine Maxwell-, Pascal- (GTX-900/10-Serie) oder Volta-Karte (z. B. Titan V) ändern Sie
vor `docker compose up -d` die `image:`-Zeile in der verwendeten Compose-Datei
(`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` oder `.gpu.yml`):

- von `ghcr.io/ncoevoet/facet:latest-cuda`
- auf `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, Maxwell bis Hopper)

Dieser Image-Tag `-cuda-legacy` hat nichts mit `docker-compose.legacy.yml` zu tun, das das
reine CPU-Profil `legacy` wählt. Karten älter als Maxwell (Kepler, Fermi) haben kein
CUDA-Image: Verwenden Sie den Block [Keine Grafikkarte](#keine-grafikkarte).

### Befehle für den Alltag

Die Galerie ist leer, bis Sie Ihre Fotos bewerten. Innerhalb von Docker heißt Ihr
Fotoordner immer `/data/photos`:

```bash
docker compose exec facet python facet.py /data/photos   # Ihre Fotos bewerten
docker compose logs -f                                   # beobachten, was gerade passiert
docker compose down                                      # stoppen
```

Um erneut zu starten, führen Sie die oben verwendete Zeile `docker compose … up -d` noch
einmal aus.

## Installation ohne Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` erkennt Ihre Grafikkarte, installiert die passenden Pakete und baut die
Web-Galerie. Danach, jedes Mal:

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

Auf Apple Silicon nutzt dies automatisch die Grafikkerne. Danach, jedes Mal:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # Ihre Fotos bewerten
python viewer.py                       # Galerie starten
```

Öffnen Sie <http://localhost:5000>.

> **Port 5000 ist bereits belegt?** macOS nutzt ihn für AirPlay. Starten Sie
> `python viewer.py --port 5001` und öffnen Sie <http://localhost:5001>.

### Windows

Ein Installationsprogramm pro Benutzer (MSI) richtet Facet ohne Administratorrechte ein:

| Ordner | Inhalt |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | das Programm, wird bei jedem Update ersetzt |
| `%LOCALAPPDATA%\Facet\venv` | die Python-Umgebung, erstellt, sobald das Installationsprogramm fertig ist |
| `%LOCALAPPDATA%\Facet\data` | die Datenbank (`photo_scores_pro.db`) und die Protokolle |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Das Installationsprogramm beschaffen.** Noch kein Release enthält eines. Bauen Sie es aus
einem Klon mit `installer\build-msi.ps1` (es braucht WiX 3.14, `uv` und den gebauten Client und
sagt, wo es WiX gibt), oder laden Sie das Artefakt `facet-msi` eines Laufs des Workflows
*Windows install (MSI)* herunter. Zum Bauen braucht es Node.js 22.22.3 oder neuer für den
Client (22.14 scheitert bei `npm run build`).

**Erster Start.** Das Installationsprogramm startet die Einrichtung der Python-Umgebung, sobald
es fertig ist. Die Umgebung ist etwa 6 GB groß, und der
Download-Cache von uv (`%LOCALAPPDATA%\uv\cache`) braucht noch einmal etwa so viel. Der
Startmenü-Eintrag *Facet* führt die Einrichtung aus, wenn sie nie abgeschlossen wurde, und
erneut nach einem Update, das die Abhängigkeiten von Facet ändert. Er wählt den PyTorch-Build
für Ihre NVIDIA-Karte und deren Treiber so, wie es `install.sh` tut, oder den CPU-Build ohne
NVIDIA-Karte. Erreicht der installierte GPU-Build die Karte nicht, bricht die Einrichtung mit
einer Erklärung ab: Treiber aktualisieren, oder `Setup-Facet.ps1 -Force -Cpu` ausführen.

Kann die Galerie nicht starten (Port belegt, Einrichtung fehlgeschlagen, nach 90 s keine
Antwort), zeigt das Fenster des Startmenü-Eintrags den Fehler und wartet auf die Eingabetaste.
Nach 90 s ohne Antwort bleibt die Galerie gestartet und kann noch hochkommen.

**Im Alltag:**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # Fotos bewerten; weitere Argumente gehen an facet.py
.\Start-Facet.ps1                # die Galerie, unter http://localhost:5000
.\Stop-Facet.ps1                 # Galerie und laufende Scans beenden
```

Die Galerie antwortet nur auf diesem Rechner. `Start-Facet.ps1 -Lan` öffnet sie für andere
Geräte und startet erst, wenn `viewer.password` in der Konfiguration gesetzt ist.

**Eine Schreibweise pro Ordner.** Facet speichert jedes Foto unter dem Pfad, über den es gescannt
wurde; `\\NAS\Photos` und dieselbe Freigabe als Laufwerk `Z:\` sind für Facet zwei verschiedene
Ordner: Wer beide scannt, hat jedes Foto doppelt. Wählen Sie eine Schreibweise und bleiben Sie dabei.

**Verwaltete Rechner.** Die Verknüpfungen starten Facets unsignierte PowerShell-Skripte mit `-ExecutionPolicy Bypass`. Eine per Gruppenrichtlinie gesetzte Ausführungsrichtlinie hat Vorrang, sodass die Skripte auf einem verwalteten PC womöglich nicht laufen; bitten Sie die Administration, sie zuzulassen.

**Die Deinstallation** (Einstellungen, Apps) beendet Facet und entfernt das Programm, die
Verknüpfungen, die Python-Umgebung und ExifTool (auch unter einem eigenen `FACET_HOME`) und
behält `data` und `config`. Was sie nicht löschen kann, steht in `data\logs\uninstall.log`. Der
Download-Cache von uv (`%LOCALAPPDATA%\uv\cache`) und die heruntergeladenen Modelle bleiben
(`.cache`, `.insightface` in Ihrem Benutzerordner). Ein Update behält einen eigenen
Installationsordner und richtet die Umgebung nur neu ein, wenn sich die Abhängigkeiten von Facet
geändert haben.

**Eine Bibliothek aus Docker übernehmen.** Die Datenbank speichert den vollständigen Pfad
jedes Fotos, und die Windows-Installation sieht dieselben Fotos unter einem anderen
(`\\NAS\Photos\...` statt `/data/photos/...`). Kopieren Sie die Datenbank nach `data`,
beenden Sie Facet und schreiben Sie dann die Pfade um, zuerst als Probelauf:

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

Das Werkzeug behält eine Kopie der Datenbank (`photo_scores_pro.db.before-rewrite-<Zeit>`),
verweigert das Zusammenführen eines Fotos, das schon unter dem neuen Pfad gescannt wurde, und
leert den Vektorindex, den `..\venv\Scripts\python.exe database.py --db
..\data\photo_scores_pro.db --populate-vec` neu aufbaut. Der Rückgängig-Verlauf von vor dem
Umzug gilt danach nicht mehr. Diese Befehle gehen vom Standard-Installationsordner aus. Ein
alter und ein neuer Präfix, von denen einer im anderen liegt (zum Beispiel `D:\Photos` nach
`D:\Photos\new`), werden abgelehnt; gehen Sie über einen temporären Präfix.

Docker läuft auch unter Windows; für eine NVIDIA-Karte folgen Sie der [WSL2-Anleitung](DEPLOYMENT.md#windows-wsl2-mit-einer-nvidia-gpu).

## Erster Start: was Sie erwartet

- **Ein Download.** Der erste Scan lädt die Modelle für Ihr Profil herunter: etwa 4,7 GB
  für `legacy`, 6,9 GB für `8gb`, 14,6 GB für `16gb`, 19,3 GB für `24gb`
  ([Downloadgrößen](#downloadgrößen)). Das geschieht einmalig.
- **Keine Einrichtung zum Scannen.** Facet erstellt seine Datenbank beim ersten Scan.
- **Schreibgeschützt, bis Sie ein Passwort setzen.** Zum Bearbeiten (bewerten, aussortieren,
  Alben, Personen) setzen Sie `viewer.edition_password` in `scoring_config.json` und starten
  den Viewer neu. Mit der mitgelieferten `docker-compose.yml` erzeugt das Image beim ersten
  Start eines.
- **Ihre Fotos werden nicht verändert.** Der Scan liest sie nur. Bewertungen und
  Schlagwörter zurück in die Dateien zu schreiben, ist eine separate Option
  ([Interop](INTEROP.md)).
- **Zeit.** Ein erster Scan einer großen Bibliothek dauert eine Weile, auf einem Prozessor
  länger als auf einer Grafikkarte. Sie können die Galerie durchstöbern, während er läuft.

## Prüfen, ob es funktioniert hat

```bash
python facet.py --doctor                             # ohne Docker
docker compose exec facet python facet.py --doctor   # mit Docker
```

Dies gibt Ihre Grafikkarte, das gewählte Profil und alles Fehlende aus. Wenn die Galerie
läuft, antwortet <http://localhost:5000/health> mit `ok`.

Funktioniert etwas nicht? Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben)
und [Probleme bei der GPU-Erkennung](#probleme-bei-der-gpu-erkennung).

---

# Fortgeschritten

Optional: was die Installation tut, wie Sie sie ändern, und die Abhängigkeitsreferenz.

- [Docker-Einstellungen, die Sie ändern können](#docker-einstellungen-die-sie-ändern-können)
- [Das Profil selbst wählen](#das-profil-selbst-wählen)
- [Manuelle Installation ohne install.sh](#manuelle-installation-ohne-installsh)
- [install.sh-Optionen und Makefile-Kurzbefehle](#installsh-optionen-und-makefile-kurzbefehle)
- [exiftool](#exiftool)
- [ONNX Runtime für die Gesichtserkennung](#onnx-runtime-für-die-gesichtserkennung)
- [OpenCV Headless-Build](#opencv-headless-build)
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
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Host-Ordner, les- und schreibbar unter `/data/photos` eingehängt (damit XMP-Sidecars geschrieben werden können) |
| `PORT` | `5000` | Host-Port für die Galerie |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb`; überschreibt `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Datenbankpfad im Container, auf dem `./data`-Bind-Mount |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` der Konfiguration | Auslöser für das Neutrainieren des persönlichen Rankers, für Nutzer mit vielen Bewertungen |

`scoring_config.json` ist Ihre **Überschreibung**. Die ausgelieferten Werte liegen in
`config/scoring_config.default.json` innerhalb des Images. Ihre Datei enthält nur, was Sie
geändert haben; alles andere behält den ausgelieferten Wert und folgt Upgrades. Siehe
[Konfiguration](CONFIGURATION.md#standardwerte-und-ihre-überschreibung) und
[die vollständige Schlüsselreferenz](CONFIGURATION.md).

Beim ersten Start legt `docker-entrypoint.sh` `./facet-config/scoring_config.json` an:

- `docker-compose.yml` hängt sie als `FACET_CONFIG=/config/scoring_config.json` per
  Bind-Mount ein, sodass im Viewer vorgenommene Konfigurationsänderungen
  `docker compose down && up` überstehen.
- Unter Compose enthält sie ein generiertes `viewer.edition_password`, einmalig ausgegeben
  in `docker compose logs facet`. Ein einfaches `docker run` ohne `FACET_CONFIG` erzeugt
  eine leere Überschreibung und kein Passwort.
- Eine bestehende Datei wird nie überschrieben, und ihr Eigentümer und ihre Rechte bleiben
  unangetastet.

### Dateibesitz im Container

Facet führt `chown` und `chmod` nur für ein `scoring_config.json` aus, das es selbst
angelegt hat.

Eine Ausnahme: Ist eine bestehende Konfiguration für den `facet`-Benutzer des Containers
(uid 1000) nicht **lesbar**, übernimmt der Entrypoint ihren Besitz und meldet dies auf
stderr. Eine unlesbare Konfiguration würde Sie aus der Oberfläche aussperren. Um den Besitz
zu behalten, machen Sie sie stattdessen lesbar:
`chmod o+r facet-config/scoring_config.json`.

Unter rootless Podman/Docker gehört Ihre Datei einem uid, den der `facet`-Benutzer des
Containers nicht annehmen kann. Machen Sie sie **für den Container-Benutzer beschreibbar,
während Sie Eigentümer bleiben**:

```bash
# 100999 = die Host-Subuid, auf die der facet-Benutzer im Container (uid 1000) abgebildet wird;
# Ihre steht auf einer bereits vom Container erzeugten Datei: stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

Die Datei bleibt Ihre und bearbeitbar, und Facets Schreibvorgänge erhalten das so.
Alternativen: `podman unshare chown`, um eine dem Container gehörende Datei zu bearbeiten,
oder `--userns=keep-id` (bzw. eine `user:`-Angabe im Compose), damit der Container-Benutzer
Sie selbst ist.

> **Warnung — Upgrade von einer älteren Compose-Datei.** Frühere Versionen hängten
> `- ./scoring_config.json:/app/scoring_config.json` ein. Die ausgelieferte Compose-Datei
> tut das nicht mehr. Wenn Sie die neue übernehmen, **verschieben Sie Ihre Konfiguration
> zuerst**, sonst werden Ihre Gewichte, Kategorien und Ihr Viewer-Passwort nicht mehr gelesen:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Behalten Sie Ihre eigene `docker-compose.yml` mit dem alten Mount, wird `./facet-config`
> aus dieser Datei befüllt, und es geht nichts verloren.
>
> Eine mitgenommene Konfiguration ist eine vollständige Kopie der alten Standardwerte. Sie
> funktioniert weiter, aber Ihre Änderungen sind schwer zu erkennen. Führen Sie
> `python database.py --compact-config` aus (unter Docker:
> `docker compose exec facet python database.py --compact-config`), um sie auf das zu
> reduzieren, was Sie geändert haben. Es legt zuerst eine Sicherung mit `0600` an und löst
> sich auf dieselbe Konfiguration auf.

Modell-Caches liegen in benannten Volumes (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) und überdauern Neustarts. `docker compose down -v`
löscht sie und erzwingt einen erneuten Download.

Das Image bündelt `exiftool`, aber **nicht** darktable. Der RAW-/Darktable-Profil-Download
des Viewers bleibt aus, es sei denn, Sie fügen dem Image eine `darktable-cli`-Binärdatei hinzu.

## Das Profil selbst wählen

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` setzen jeweils `FACET_VRAM_PROFILE`; die GPU-Dateien
  reservieren außerdem das NVIDIA-Gerät.
- `docker-compose.gpu.yml` reserviert die GPU und überlässt das Profil dem
  `vram_profile` der Konfiguration (Standard `auto`).

Drei Images werden veröffentlicht:

| Image | Inhalt | Entpackt |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Schlanker CPU-Build | 3,34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, einschl. RTX-50-Serie); Standard für `8gb`/`16gb`/`24gb` | 13,1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper); siehe [Ältere NVIDIA-Karte](#ältere-nvidia-karte-maxwell-pascal-volta) | 13,8 GB |

- Beide CUDA-Images liefern `onnxruntime-gpu` (1.26.0, CUDA 12) anstelle von
  `onnxruntime` mit, sodass die Gesichtserkennung auf der GPU läuft. Das CPU-Image behält
  `onnxruntime`.
- Alle drei sind ausschließlich `linux/amd64`. Bauen Sie auf ARM lokal mit
  `docker compose build`.
- `docker compose build` (oder `up --build`) baut aus diesem Repository. Build-Argumente:
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (siehe `Dockerfile`).

Ohne Docker verwenden Sie die Umgebungsvariable oder den Konfigurationsschlüssel:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Die Schwellenwerte, die `auto` anwendet, stehen unter
[Konfiguration › Automatische VRAM-Erkennung](CONFIGURATION.md#automatische-vram-erkennung).

## Kommerzielle Installation und die eingeschränkten Pakete

`insightface` und `pyiqa` (mit `openai-clip`, `facexlib` und `onnxruntime`, die nur sie
benötigen) liefern Modellgewichte unter nichtkommerziellen Bedingungen. Sie gehören nicht
zur Basisinstallation. Sie liegen in den Extras `faces-insightface` und `iqa` sowie in
`requirements.restricted.txt` (plus `requirements.restricted.lock.txt` und
`requirements.legacy.restricted.lock.txt` für Docker).

> **Breaking Change.** `pip install -e .` und `pip install -r requirements.txt` allein
> enthalten insightface und pyiqa nicht mehr. Verwenden Sie `pip install -e .[all]` oder
> `pip install -r requirements.txt -r requirements.restricted.txt`. `install.sh` und das
> Standard-Docker-Image installieren beides.

| Ziel | Befehl |
|------|---------|
| Alles (Standard) | `bash install.sh` oder `pip install -e .[all]` |
| Kommerziell unbedenklich | `bash install.sh --commercial` |
| Kommerziell unbedenklich, von Hand | `pip install -r requirements.txt`, dann `pip install -e .[commercial]` und `pip install mediapipe==0.10.35 --no-deps` |
| Kommerziell unbedenklich, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` und das Extra `faces-insightface` installieren das
  CPU-`onnxruntime`. Führen Sie auf einem CUDA-Rechner danach den GPU-Befehl aus
  [ONNX Runtime für die Gesichtserkennung](#onnx-runtime-für-die-gesichtserkennung) aus.
  `bash install.sh` und die CUDA-Images tun das bereits.
- Installieren Sie `mediapipe` immer mit `--no-deps`, sonst installiert dessen
  `opencv-contrib-python` den `cv2`-Namensraum doppelt. Das Extra `commercial` deklariert
  dessen Laufzeitabhängigkeiten (`absl-py`, `flatbuffers`).
- `python-ofiq` (die OFIQ-Gesichtsqualitäts-Bindings) bietet nur Wheels für Linux x86-64
  und macOS arm64. Installieren Sie es dort, wo verfügbar, von Hand mit
  `pip install python-ofiq`.

Eine kommerzielle Installation schaltet den Modus nicht um. Setzen Sie ihn in Ihrer
Überschreibung: `{ "licensing": { "mode": "commercial" } }`. Das Docker-Build-Argument
setzt außerdem `FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` zeigt den
aktiven Lizenzmodus und im kommerziellen Modus die Komponenten, die ein Scan laden würde
(YuNet, SFace, Q-ReAlign).

## Manuelle Installation ohne install.sh

Erfordert Python 3.12 (3.10+ funktioniert) und Node.js 20+ für den Galerie-Build.

```bash
# 1. Virtuelle Umgebung erstellen und aktivieren
python3 -m venv venv
source venv/bin/activate

# 2. Zuerst PyTorch installieren, passend zu Ihrer CUDA-Version:
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    Auch Ihre KARTE zählt: Maxwell/Pascal/Volta (GTX 900/10-Serie, Titan V) brauchen cu126,
#    selbst mit einem CUDA-12.8-Treiber. Prüfen: `nvidia-smi --query-gpu=compute_cap --format=csv`
#    Im Zweifel kopieren Sie den Befehl von https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Den Rest in einem Rutsch installieren, damit pip den gesamten Graphen auflöst
pip install -r requirements.txt -r requirements.restricted.txt

# 4. Nur CUDA, NACH Schritt 3: die GPU-ONNX-Runtime einsetzen (passend zu Ihrem PyTorch-CUDA-Build)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # CUDA 12.x PyTorch (cu124, cu126, cu128)
# Nur CPU oder CUDA 11.8 (cu118): Behalten Sie, was Schritt 3 installiert hat, oder installieren Sie es neu mit
# pip install "onnxruntime>=1.15.0"

# 5. NACH Schritt 3 und 4: nur den Headless-Build von OpenCV behalten (der GUI-Build braucht libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Die Web-Galerie bauen
cd client && npm install && npx ng build && cd ..

# 7. Ausführen
python facet.py /path/to/photos
python viewer.py
```

Die Reihenfolge der Schritte ist wichtig: Bei Paketen, die sich Dateien teilen
(`onnxruntime`/`onnxruntime-gpu`, `opencv-python`/`opencv-python-headless`), gewinnt das
zuletzt installierte. `install.sh` wendet die Untergrenze für die Karte und beide Tausche
automatisch an.

Überprüfen Sie die Umgebung:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Fehler? Siehe [Abhängigkeitskonflikte beheben](#abhängigkeitskonflikte-beheben).

## install.sh-Optionen und Makefile-Kurzbefehle

`install.sh`:

1. sucht ein Python 3.10+ und legt das `venv` an;
2. erkennt das Betriebssystem und die GPU (Apple Silicon → Metal, sonst `nvidia-smi` → passender CUDA-Build);
3. installiert PyTorch, `requirements.txt`, `transformers` und `accelerate`;
4. tauscht die richtige [ONNX Runtime](#onnx-runtime-für-die-gesichtserkennung) und den
   [Headless-Build von OpenCV](#opencv-headless-build) ein;
5. prüft auf `exiftool`, baut den Angular-Client und verifiziert jeden Import (Exit-Status 1, wenn einer fehlschlägt).

| Flag | Wirkung |
|------|--------|
| `--cpu` | Erzwingt reines CPU-PyTorch (kein CUDA) |
| `--cuda VERSION` | Überschreibt die erkannte CUDA-Version (z. B. `--cuda 12.8`) |
| `--skip-client` | Überspringt den Build des Angular-Frontends |
| `--no-uv` | Verwendet pip statt uv |
| `--commercial` | Kommerziell unbedenkliche Installation: ohne insightface, pyiqa und ONNX Runtime, mediapipe mit `--no-deps`; `licensing.mode` setzen Sie selbst auf `commercial` |

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
`exifread` zurück (verarbeitet alle RAW-Formate), dann auf PIL (nur JPEG/TIFF/DNG).

| OS | Befehl |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download von [exiftool.org](https://exiftool.org/) |

## ONNX Runtime für die Gesichtserkennung

Die Gesichtserkennung (InsightFace) läuft über ONNX Runtime: `onnxruntime` (CPU) oder
`onnxruntime-gpu` (CUDA). Beide teilen sich das Verzeichnis `onnxruntime/`, daher kann nur
eines installiert sein; das zuletzt von pip installierte gewinnt. `insightface` hängt vom
CPU-Build ab, daher bringt seine Installation (`requirements.restricted.txt`,
`pip install -e .[all]`, das Extra `faces-insightface`) den CPU-Build zurück. Installieren
Sie auf einem CUDA-Rechner das GPU-Paket **nach** diesen und entfernen Sie zuvor beide Namen.

`bash install.sh` erledigt das auf x86_64 mit einem CUDA-12-PyTorch und testet danach eine
echte CUDA-Sitzung (wie `--doctor`). Führen Sie es erneut aus, um ein defektes `venv` zu
reparieren oder zwischen CPU und GPU zu wechseln. Die CUDA-Docker-Images tun dasselbe.
CPU-Installationen, CUDA 11.8 (cu118), macOS, das CPU-Image und aarch64 (kein
CUDA-12-Wheel von `onnxruntime-gpu`) behalten `onnxruntime`.

Wählen Sie von Hand die Zeile für Ihren **PyTorch**-CUDA-Build:

| PyTorch-Build | Befehl |
|---------------|---------|
| Nur CPU oder CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Richten Sie sich nach PyTorch, nicht nach dem Treiber.** Die CUDA-Version, die
  `nvidia-smi` ausgibt, ist die neueste, die der Treiber unterstützt; ein CUDA-13-Treiber
  führt weiterhin das cu128-PyTorch aus. `python facet.py --doctor` zeigt den Build von
  PyTorch in der Zeile `CUDA (compiled)`.
- **Behalten Sie den Versionsbereich.** `onnxruntime-gpu` 1.19–1.26 sind CUDA-12-Builds;
  1.27+ benötigen CUDA-13-Bibliotheken. Eine unbegrenzte Installation wirkt in Ordnung,
  läuft aber unbemerkt auf der CPU. Für ein von Hand installiertes CUDA-13-PyTorch passt
  `"onnxruntime-gpu>=1.27.0"` (ungetestet).
- **CUDA 11.8 hat keinen brauchbaren GPU-Build.** Das alte CUDA-11-`onnxruntime-gpu`
  benötigt cuDNN 8, aber das cu118-PyTorch nutzt cuDNN 9. Für Gesichtserkennung auf der GPU
  aktualisieren Sie den Treiber auf einen, der CUDA 12.4 oder neuer meldet, und führen
  `install.sh` erneut aus.
- **Setzen Sie die Anforderung in Anführungszeichen.** Ohne sie legt
  `pip install onnxruntime-gpu>=1.19.0,<1.27` eine leere Datei namens `=1.19.0,` an und
  scheitert mit `1.27: No such file or directory`. Löschen Sie diese Datei.
- **Deinstallieren Sie beide Namen.** `pip uninstall onnxruntime` gefolgt von
  `pip install onnxruntime-gpu` hinterlässt `import onnxruntime` als leeres Paket, und
  InsightFace scheitert mit `module 'onnxruntime' has no attribute 'InferenceSession'`.

Nach dem Tausch meldet `pip check`: „insightface ... requires onnxruntime, which is not
installed“ (`uv pip check`: „The package `insightface` requires `onnxruntime`, but it's not
installed“). Das ist harmlos: `onnxruntime-gpu` stellt dasselbe Modul bereit. Ebenso ist es
nach dem OpenCV-Tausch harmlos, dass `insightface` und `facexlib` `opencv-python` verlangen.
Ein späteres `pip install -r requirements.txt` bringt das GUI-OpenCV zurück; wiederholen
Sie den [OpenCV-Tausch](#opencv-headless-build) oder führen Sie `install.sh` erneut aus.

**Prüfen:** Der Abschnitt **ONNX Runtime** von `python facet.py --doctor` listet Paket,
Version und Execution Providers und warnt (mit der Abhilfe), wenn beide Pakete installiert
sind oder der Import scheitert. Auf CUDA führt er eine Testsitzung aus; die Zeile
`CUDA session` ist nur OK, wenn sie wirklich auf `CUDAExecutionProvider` läuft. Der Test
benötigt das Paket `onnx` und entfällt auf der CPU und im kommerziellen Modus. Ein Scan auf
CUDA warnt außerdem einmal, wenn InsightFace auf der CPU läuft.

In Docker geht eine Reparatur im Container beim nächsten `docker run` verloren: Ziehen Sie
ein aktuelles Image oder bauen Sie es neu. Die CUDA-Images setzen `onnxruntime-gpu` 1.26.0
über das Build-Argument `ORT_GPU_VERSION`; setzen Sie nie 1.27 oder neuer (CUDA 13).

## OpenCV Headless-Build

`opencv-python` (GUI) und `opencv-python-headless` teilen sich das Verzeichnis `cv2/`; das
zuletzt installierte gewinnt. Die Abhängigkeiten von Facet ziehen beide nach. Der GUI-Build
braucht `libGL.so.1`, das Debian, WSL und schlanke Hosts nicht mitbringen, daher scheitert
`import cv2` mit `ImportError: libGL.so.1: cannot open shared object file`. Facet öffnet
keine OpenCV-Fenster, der Headless-Build genügt also.

`bash install.sh` behält in jedem Modus nur den Headless-Build, auch bei `--commercial`.
Die Docker-Images sind nicht betroffen (sie installieren `libgl1`). Um ein `venv` von Hand
zu reparieren, ersetzen Sie `<version>` durch die Version, die `pip list` für eines der
beiden Pakete zeigt:

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

Der Abschnitt **OpenCV** von `python facet.py --doctor` zeigt `[OK]`, wenn sich `cv2`
importieren lässt, sonst den Importfehler und den Reparaturbefehl mit Ihrer eingesetzten
Version. Beide Pakete bei funktionierendem Import sind in Ordnung (die Docker-Images
liefern beide mit `libgl1`). Scheitert ein Kern-Import wie `cv2`, gibt `install.sh`
„Installation finished with errors“ aus und endet mit Status 1.

## GPU-Gesichtsclustering mit RAPIDS cuML

Für große Gesichtsdatenbanken (80.000+ Gesichter) beschleunigt cuML das Clustering stark.
Es benötigt conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# oder: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt installiert opencv-python, den GUI-Build (braucht libGL.so.1): nur den Headless-Build behalten
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

Ist cuML installiert, nutzt das Clustering automatisch die GPU (`face_clustering.use_gpu`
in `scoring_config.json`). Die CUDA-Docker-Images bündeln es, sodass
`8gb`/`16gb`/`24gb`-Container auf der GPU clustern. `legacy` clustert immer auf dem
Prozessor.

## Apple Silicon (Metal/MPS)

Es wird kein zusätzliches GPU-Paket benötigt. Installieren Sie mit `bash install.sh` und
prüfen Sie dann, ob `python facet.py --doctor` `Facet runtime device: mps` meldet. Facet
aktiviert den CPU-Fallback von PyTorch für nicht unterstützte Operatoren. Zum Vergleich:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` deaktiviert die Beschleunigung; `FACET_DEVICE=mps` verlangt sie und
  scheitert, wenn sie nicht verfügbar ist. `FACET_DEVICE=cuda` scheitert genauso, wenn
  PyTorch kein CUDA-Gerät sieht (z. B. `CUDA_VISIBLE_DEVICES=''`).
- InsightFace bleibt auf dem Prozessor (es ist ein ONNX-Runtime-Modell).
- TOPIQ-Werte können leicht von CPU/CUDA abweichen. Auf MPS wird ein Foto, dessen Seiten
  keine Vielfachen von 32 sind, zuerst mittig zugeschnitten (aus 1024×682 wird 1024×672).

`vram_profile: "auto"` bemisst das Profil anhand des gesamten Unified Memory:

| Gesamter Unified Memory | Von `auto` gewähltes Profil |
|----------------------|----------------------------|
| unter 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB und mehr | `24gb` |

Jede Schwelle beträgt etwa das Doppelte des Modellspeicherbedarfs des Profils, weil macOS
und andere Anwendungen diesen Speicher mitnutzen. Ein Mac, der auslagert, ist langsamer als
einer mit einem kleineren Profil. Ein ausdrücklich gesetztes Profil wird immer so
übernommen, wie es steht.

### Speicher auf einem Mac

Wenn die Aktivitätsanzeige zeigt, dass Facet mehr Speicher nutzt, als der Mac hat, oder
der Swap-Speicher während eines Scans weiter wächst, versuchen Sie diese Schritte in dieser
Reihenfolge.

**1. Begrenzen Sie den Speicherpool von PyTorch:**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` bedeutet „die vom Mac empfohlene Arbeitsspeichergröße, nicht mehr“. Ein Durchlauf
kann dann mit „out of memory“ abbrechen, statt zu swappen, was besser ist, als wenn der Mac
zum Stillstand kommt.

**Gewichte werden einzeln geladen.** Unter macOS setzt Facet standardmäßig
`HF_DEACTIVATE_ASYNC_LOAD=1`, weil gleichzeitiges Laden einen Scan auf MPS zum Absturz
bringen kann. Es gibt nichts zu konfigurieren; setzen Sie selbst `HF_DEACTIVATE_ASYNC_LOAD=0`,
um das gleichzeitige Laden zurückzubekommen.

**2. Deaktivieren Sie die beiden aufwendigsten optionalen Modelle.** Fügen Sie
`scoring_config.json` nur diese Schlüssel hinzu:

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` schaltet die Motiverkennung ab; `qrealign` schaltet ein zusätzliches
Qualitätsmodell ab. Ästhetik, Komposition, Gesichter und technische Qualität werden weiterhin
bewertet. Nutzen Sie den Profil-Schlüssel Ihres Mac: `"16gb"` bei 32-47GB, `"24gb"` ab 48GB.

**3. Verarbeiten Sie weniger Fotos auf einmal:**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Setzen Sie alle drei, sonst verschiebt die automatische Abstimmung die Chunk-Größe zwischen
`min_ram_chunk_size` und `max_ram_chunk_size`.

## Downloadgrößen

Modelle werden bei der ersten Verwendung heruntergeladen nach:

- `~/.cache/huggingface/` (Hugging-Face-Modelle)
- `~/.cache/torch/hub/` (PyIQA-Gewichte)
- `~/.insightface/` (Gesichtserkennung)
- `pretrained_models/` in der Repository-Wurzel: `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task` und `aesthetic_predictor_weights.pth` (nur `legacy`/`8gb`)

In Docker sind dies benannte Volumes (`pretrained_models/` ist `facet-pretrained`), sodass
bei einer Neuerstellung des Containers nichts erneut heruntergeladen wird. Keine Gewichte
sind ins Image eingebacken.

Die Größen sind dezimal (GB = 10⁹ Byte, MB = 10⁶ Byte).

| Modell | Größe | Profile |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (Embeddings + CLIP-Tagging + CLIP-MLP-Ästhetik) | 1,711 GB | `legacy`/`8gb` |
| Ästhetik-MLP-Kopf (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | nur `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (Embeddings) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (VLM-Tagging) | 4,571 GB | `16gb` |
| Qwen3.5-4B (VLM-Tagging) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (Komposition) | 4,430 GB | standardmäßig keines; siehe Anmerkung 1 |
| InsightFace buffalo_l (Gesichter) | 289 MB Download / 630 MB auf der Platte (das Zip bleibt neben den `.onnx`-Dateien erhalten) | alle |
| SAMP-Net-Gewichte (Komposition) | 183 MB | alle |
| U2-Net-P (Salienz-Untermodell von SAMP-Net) | 4,7 MB | wie SAMP-Net |
| BiRefNet_dynamic (Motiverkennung) | 445 MB | alle |
| TOPIQ NR (Ästhetikmodell) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (ergänzende Ästhetik) | 873 MB | alle |
| TOPIQ NR-Face (ergänzende Gesichtsqualität) | 376 MB | alle |
| LIQE (ergänzende Qualität/Verzerrung) | 708 MB | alle |
| timm resnet50.a1_in1k (gemeinsames PyIQA-Backbone) | 102 MB | alle |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **standardmäßig aktiv** (`"auto"`) |

1. Qwen2-VL-2B wird nur geladen, wenn Sie `composition_model: "qwen2-vl-2b"` **und**
   `processing.mode: "single-pass"` setzen; es ersetzt SAMP-Net/U2-Net-P. Außerhalb des
   kommerziellen Modus funktioniert das nur bei `legacy`/`8gb`: Bei `16gb`/`24gb` fällt
   Single-Pass auf Multi-Pass zurück, das keinen Qwen2-VL-Pass hat.

Summen pro Profil (Download): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` mit Qwen2-VL-Komposition 23,56 GB (nur im kommerziellen Modus, siehe Anmerkung 1).

Die Docker-Images selbst, vor jedem Modell-Download: `latest` 3,34 GB entpackt,
`latest-cuda` 13,1 GB, `latest-cuda-legacy` 13,8 GB
([Bereitstellung › Image-Größe](DEPLOYMENT.md#image-größe)). Komprimierte Downloadgrößen
sind noch nicht gemessen.

Optionale Modelle, nicht in den Summen enthalten:

| Modell | Größe | Auslöser |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | standardmäßig aus |
| SigLIP-so400m-patch14-384-Backbone (`iqa_extended.aesthetic_v25`) | 3,515 GB | standardmäßig aus, **veraltet** (`qrealign` vorziehen) |
| Helsinki-NLP OPUS-MT, pro Zielsprache (Untertitel-Übersetzung) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | nur für die Sprachen, die Sie aktivieren |
| MediaPipe `face_landmarker.task` | 3,76 MB | nur wenn `mediapipe` installiert ist |

`reverse_geocoder` braucht keinen Download; seine Daten sind im Wheel enthalten.

Die SAMP-Net-Gewichte stammen aus dem
[model-weights-v1-Release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
Sehen Sie `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (offline oder
eingeschränktes Netzwerk), laden Sie die Datei herunter und legen Sie sie unter
`pretrained_models/samp_net.pth` ab.

## Abhängigkeiten

### Erforderliche Pakete

| Paket | Zweck |
|---------|---------|
| `torch`, `torchvision` | Deep-Learning-Framework (separat installiert, siehe oben) |
| `open-clip-torch` | CLIP-Embeddings/Tagging (legacy/8gb-Profile) |
| `pyiqa` | TOPIQ und weitere Qualitäts-/Ästhetikmodelle |
| `opencv-python` | Bildverarbeitung |
| `pillow` | Bildladen, einschließlich PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF erfordert pillow>=11.3) |
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
| `sqlite-vec` | Semantische Suche auf der Festplatte (greift auf einen In-Memory-NumPy-Cache zurück); `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | JPEG-XL-Fotos und Vorschauen zusammengefügter Lightroom-Classic-13+-DNGs (HDR/Panorama/Verbessern) |

Alle diese sind in `requirements.txt` enthalten, außer `pyiqa` und `insightface`, die in `requirements.restricted.txt` stehen (siehe [Kommerzielle Installation und die eingeschränkten Pakete](#kommerzielle-installation-und-die-eingeschränkten-pakete)). Kein Profil benötigt zusätzliche Basis-Pakete.

### Optionale Pakete

Jedes schaltet eine Funktion frei; ohne es wird die Funktion übersprungen oder ein
Fallback verwendet.

| Paket | Schaltet frei | Ohne es |
|---------|---------|-----------|
| `watchdog` | Watch-Modus (`--watch`); **nicht in `requirements.txt`**, Installation mit `pip install .[watch]` | `--watch` nicht verfügbar |
| `pillow-heif` | HEIF/HEIC-Dekodierung | HEIF/HEIC-Dateien werden übersprungen |
| `rawpy` | RAW-Dekodierung (CR2/CR3/NEF/ARW/…), bereits in `requirements.txt` | RAW-Dateien werden übersprungen |
| `cuml`, `cupy` | GPU-Gesichtsclustering (conda + CUDA) | Clustering auf der CPU via `hdbscan` (Standard) |
| `onnxruntime-gpu` | GPU-Gesichtserkennung, **anstelle von** `onnxruntime` ([Details](#onnx-runtime-für-die-gesichtserkennung)) | CPU-`onnxruntime` (langsamer) |
| `aesthetic-predictor-v2-5` | Bewerter `aesthetic_v25` (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, standardmäßig aus). **Veraltet** (AGPL-3.0, seit 2024-12-18 unmaintained); bevorzugen Sie `qrealign`, das kein zusätzliches Paket benötigt | `aesthetic_v25` nicht verfügbar |
| `darktable-cli` (System) | RAW-/Darktable-Profil-Export aus dem Viewer | Nur Original-/eingebetteter Download angeboten |
| `exiftool` (System) | Beste EXIF-/GPS-Extraktion | Greift auf `exifread`, dann PIL zurück |

## Funktionsanforderungen

Der Großteil von Facet läuft überall (CPU, jedes Profil). Einige Funktionen benötigen eine
GPU, ein höheres **VRAM-Profil**, ein optionales Paket oder das **Bearbeitungspasswort** /
die **Superadmin**-Rolle des Viewers. In der Dokumentation verwendete Kennzeichnungen:
`[GPU]` · `[16gb/24gb]` (VRAM-Profil) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Funktion | GPU | Profil | Auth | Optionales Paket |
|---------|:---:|---------|:----:|------------------|
| Bewertung / Scan (Grundfunktion) | optional | beliebig (`legacy` = CPU) | — | — |
| TOPIQ-Ästhetik | ja | `16gb`/`24gb` | — | — |
| Ergänzende IQA (TOPIQ IAA, NR-Face, LIQE) | optional | beliebig (`legacy` = CPU) | — | — |
| SigLIP-2-Embeddings | ja | `16gb`/`24gb` | — | — |
| VLM-Tagging (Qwen3.5) | ja | `16gb`/`24gb` | — | — |
| Kompositionsmuster (SAMP-Net) | optional | beliebig (`legacy` = CPU) | — | — |
| Motiverkennung (BiRefNet) | optional | beliebig (`legacy` = CPU) | — | — |
| KI-Beschreibungen (erzeugen / ansehen) | ja | `16gb`/`24gb` | edition (Erzeugen) | — |
| KI-Beschreibungen (bearbeiten) | ja | `16gb`/`24gb` | edition | — |
| VLM-Kritik | ja | `16gb`/`24gb` | edition (Erzeugen) | — |
| Gesichtserkennung / -extraktion (InsightFace) | empfohlen (CPU funktioniert, langsam) | beliebig | — | — |
| Gesichtsclustering (HDBSCAN) | nein (CPU) | beliebig | — | `cuml`/`cupy` (optionale GPU-Beschleunigung) |
| Semantische Suche | nein | beliebig | — | `sqlite-vec` (greift auf NumPy zurück) |
| RAW-/HEIF-Dekodierung | nein | beliebig | — | `rawpy` / `pillow-heif` |
| Überwachungsmodus (`--watch`) | nein | beliebig | — | `watchdog` |
| GPS-Extraktion / Darktable-Export | nein | beliebig | — | `exiftool` / `darktable-cli` |
| Bewertungen, Favoriten, Gesichts- & Personenbearbeitungen, Aussortieren | nein | beliebig | edition | — |
| Scans über die Web-Oberfläche auslösen | nein | beliebig | edition (Einzelbenutzer) / superadmin (Mehrbenutzer) | — |
| Mehrbenutzerbetrieb (benutzerspezifische Bewertungen & Rollen) | nein | beliebig | rollenbasiert | — |

Das Bearbeitungspasswort und die Benutzerrollen werden in `scoring_config.json` gesetzt;
siehe [Konfiguration](CONFIGURATION.md).

> Keine lokale GPU? Richten Sie VLM-Tagging, Beschreibungen und Kritik mit `vlm_backend` in
> `scoring_config.json` auf einen entfernten Ollama- oder OpenAI-kompatiblen Server aus.
> Diese Funktionen laufen dann auch auf den Profilen `legacy`/`8gb`.

## Abhängigkeitskonflikte beheben

Die ML-Pakete von Facet (`torch`, `open-clip-torch`, `insightface`, …) ziehen viele
Abhängigkeiten nach, und ihre einzelne Installation kann sich gegenseitig beschädigen.

**Symptome:** Jede Installation verlangt noch ein weiteres Paket; Versionskonflikte zwischen
`torch`, `numpy`, `huggingface-hub` oder `open-clip-torch`; `pip install` gelingt, aber
`import` scheitert.

**1. Alles auf einmal installieren:** `pip install -r requirements.txt`, damit pip den
vollständigen Graphen löst. Installieren Sie Pakete nicht einzeln
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Verwenden Sie [uv](https://docs.astral.sh/uv/)**: `uv` löst den ganzen Graphen vor der
Installation auf:

```bash
pip install uv
uv pip install -r requirements.txt
# Mit dem CUDA-Index für PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Neu beginnen:** `deactivate`, `rm -rf venv`, und wiederholen Sie
[Manuelle Installation](#manuelle-installation-ohne-installsh) (oder führen Sie `install.sh`
erneut aus).

### Probleme bei der GPU-Erkennung

Wenn Ihre GPU nicht erkannt wird (häufig bei neueren Karten), führen Sie aus:

```bash
python facet.py --doctor
```

Es prüft die CUDA-Unterstützung von PyTorch und den Treiber und schlägt den richtigen
pip-Befehl vor. Es erkennt auch, was `torch.cuda.is_available()` übersieht: eine GPU, für
die das installierte PyTorch keine Kernel mitbringt (z. B. RTX-50er-Serie bei einem Build
vor CUDA 12.8). In diesem Fall fällt Facet auf die CPU zurück, statt abzustürzen, und
`--doctor` benennt die Abhilfe: in Docker den richtigen Image-Tag
(`ghcr.io/ncoevoet/facet:latest-cuda-legacy` für Maxwell/Pascal/Volta); auf Bare Metal die
richtige `--index-url`.

Um Hardware zum Testen zu simulieren:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular-Client

Nur für die Entwicklung oder eigene Builds erforderlich; `install.sh` und das Docker-Image
bauen ihn bereits.

```bash
cd client
npm install
npm run build    # Produktions-Build → client/dist/
npm start        # Dev-Server unter http://localhost:4200 (leitet die API an :5000 weiter)
```

> **`npm audit`-Warnungen:** Die meisten Befunde liegen in Build-time-Dev-Abhängigkeiten,
> die nie den Browser erreichen. Prüfen Sie sie, bevor Sie `npm audit fix` ausführen, das
> Pakete herabstufen oder entfernen kann.
