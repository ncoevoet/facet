# Bereitstellungsleitfaden

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · **Deutsch** · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md)

Betreiben Sie den Facet-Viewer auf einem entfernten Server oder NAS.

> **Neu hier?** Dieser Leitfaden ist für die Bereitstellung von Facet auf anderen
> Rechnern. Um es auf Ihrem eigenen Rechner zum Laufen zu bringen, beginnen Sie mit
> [Installation](INSTALLATION.md).

## Überblick

Facet hat zwei Arbeitslasten:

| Komponente | Hardware | Zweck |
|-----------|----------|---------|
| **Bewertung** (`facet.py`) | GPU (6-24 GB VRAM) oder CPU (8 GB RAM Minimum, 12 GB empfohlen, mehr für die Profile `16gb`/`24gb` — siehe [Speicherlimits für Container](#speicherlimits-für-container)) | Fotos analysieren und bewerten |
| **Viewer** (`viewer.py`) | Beliebige Maschine (geringe Ressourcen) | Web-Galerie bereitstellen |

Nur der Viewer muss auf dem Server laufen. Bewerten Sie auf einer Workstation und synchronisieren Sie dann die Datenbank.

## Pfadzuordnung

Wenn die Bewertungsmaschine und der Viewer-Server über unterschiedliche Einhängepunkte auf Fotos zugreifen, konfigurieren Sie `viewer.path_mapping` in `scoring_config.json`, um Datenbankpfade in lokale Festplattenpfade zu übersetzen.

**Beispiel:** Fotos werden unter Windows über UNC/NFS bewertet und von einem Linux-NAS bereitgestellt:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Verwenden Sie zur besseren Lesbarkeit **Schrägstriche** in Konfigurationsschlüsseln — Backslashes werden automatisch normalisiert. Dies ordnet DB-Pfade wie `\\NAS\share\Photos\2024\IMG_001.jpg` dem Pfad `/volume1/Photos/2024/IMG_001.jpg` zu.

Mehrere Zuordnungen werden unterstützt (die erste Übereinstimmung gewinnt):

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

**So funktioniert es:**
- Die Datenbank speichert die ursprünglichen Scan-Pfade (z. B. `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Vorschaubilder werden als BLOBs in der Datenbank gespeichert, sodass das Durchsuchen keinen Festplattenzugriff erfordert
- Die Pfadzuordnung greift immer dann, wenn der Viewer eine Originaldatei öffnet: Downloads, Vollauflösungsansicht, Beschreibung und Kritik
- Sowohl UNC-Pfade (`\\server\share`) als auch Laufwerksbuchstaben (`Z:\`) werden unterstützt
- Das erste übereinstimmende Präfix gewinnt

## Pfadsemantik im Container

Alles, was Sie in ein Ordnerfeld im Viewer eingeben — ein Ziel für „In Ordner aussortieren", das Kopier-/Symlink-Exportziel eines Albums, oder `viewer.export.allowed_target_dirs` in `scoring_config.json` — wird vom Facet-Prozess selbst aufgelöst. **Unter Docker/Podman läuft dieser Prozess innerhalb des Containers**, sodass jeder Pfad der Pfad ist, den *der Container* sieht: der Einhängepunkt, niemals der host-seitige Pfad.

**Beispiel.** Die mitgelieferte `docker-compose.yml` hängt Ihren Fotoordner unter `/data/photos` ein:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Um Abgelehnte in einen Unterordner `rejects` auszusortieren, geben Sie im Dialog `/data/photos/rejects` ein — niemals den Host-Pfad (`/home/sie/Bilder`, `D:\Fotos`, …), den der Container überhaupt nicht sehen kann. Dasselbe gilt für `viewer.export.allowed_target_dirs`: Geben Sie den containerseitigen Pfad an.

Um an einen anderen Ort als den gescannten Fotobaum zu schreiben — etwa ein separates Export-Volume —, hängen Sie es zuerst in den Container ein und fügen Sie dann seinen containerseitigen Pfad zu `viewer.export.allowed_target_dirs` hinzu:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # zusätzliches Volume für Cull-/Export-Ausgabe
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

Ein Ziel, das außerhalb jedes eingehängten Volumes liegt, wird abgelehnt (`403`) — Facets Ziel-Verzeichnis-Prüfung führt `os.path.realpath()` sowohl auf die Anfrage *als auch* auf jede erlaubte Wurzel aus, löst dabei Symlinks und `..` auf, bevor sie vergleicht — ein Pfad, der nur von außerhalb des Containers richtig aussieht (oder ein Symlink, der aus einem Mount hinausweist), besteht die Containment-Prüfung trotzdem nicht. Siehe [Konfiguration — Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung) für die vollständige Allowlist-Referenz.

**Das ist kein Rechteproblem des Container-Benutzers.** Die UID des `facet`-Benutzers im Container unterscheidet sich häufig von der Ihres Host-Kontos, und das kann auf einem Bind-Mount ein echtes, separates Dateisystem-Rechteproblem verursachen — aber das geschieht *nachdem* diese Pfadprüfung bestanden wurde, wenn das Kopieren/Verlinken/Verschieben tatsächlich läuft, und es wird serverseitig mit dem zugrunde liegenden Betriebssystemfehler für die fehlgeschlagene Datei protokolliert. Ein `403 target_dir is not an allowed export location` (oder ein allgemeines „Zugriff verweigert" in der Oberfläche) geschieht *bevor* irgendeine Datei berührt wird und hat nichts mit UIDs zu tun.

## Erstellen des Angular-Clients

Der FastAPI-Server stellt die vorab erstellte SPA aus `client/dist/client/browser/` bereit. Erstellen Sie sie vor der Bereitstellung:

```bash
cd client && npm install && npx ng build && cd ..
```

Dies erfordert Node.js 20+ nur zur Build-Zeit. Die erstellten Dateien sind statische Assets — Node.js wird auf dem Server zur Laufzeit nicht benötigt.

## Synology NAS (DS420j / J-Serie)

Die J-Serie hat eine ARM-CPU, 1 GB RAM und keine Docker-Unterstützung. Der Viewer läuft direkt mit Python.

### Voraussetzungen

1. **SSH aktivieren:** DSM > Systemsteuerung > Terminal & SNMP > SSH aktivieren
2. **Python3 installieren:** DSM Paket-Zentrum oder über SSH:
   ```bash
   # Prüfen, ob verfügbar
   python3 --version
   pip3 --version
   ```

### Installation

```bash
ssh admin@your-synology-ip

# Verzeichnis erstellen
mkdir -p /volume1/facet

# Abhängigkeiten installieren (nur Viewer)
pip3 install fastapi uvicorn pyjwt pillow
```

### Leichtgewichtige Datenbank exportieren

Exportieren Sie auf Ihrer Bewertungs-Workstation eine reduzierte Datenbank für die NAS-Bereitstellung:

```bash
python database.py --export-viewer-db
```

Dies erstellt `photo_scores_viewer.db`, die:
- CLIP-Embeddings, Bildunterschrift-Embeddings und Gesichts-Embeddings entfernt
- Das Histogramm pro Foto (~2 KB) behält, das das RGB-Histogramm-Widget der Galerie liest
- Vorschaubilder von 640px auf 320px verkleinert
- Eine 14-GB-Datenbank typischerweise auf ~4-5 GB reduziert

Exporte erfolgen inkrementell: Wenn `photo_scores_viewer.db` bereits existiert, werden nur neue und geänderte Fotos synchronisiert. Verwenden Sie `--force-export` für eine vollständige Neuerstellung:

```bash
python database.py --export-viewer-db --force-export
```

Die Funktion „Ähnliche finden“ funktioniert auf der exportierten Datenbank nicht (CLIP-Embeddings sind entfernt). Verwenden Sie dafür die Bewertungsmaschine.

### Dateien synchronisieren

Erstellen Sie auf der Bewertungsmaschine zuerst den Angular-Client:

```bash
cd client && npm install && npx ng build && cd ..
```

Synchronisieren Sie dann den Viewer und die exportierte Datenbank auf das NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

Der Viewer öffnet standardmäßig `photo_scores_pro.db` (überschreibbar mit der Umgebungsvariablen `DB_PATH`). Setzen Sie auf dem NAS entweder `DB_PATH=/volume1/facet/photo_scores_viewer.db` oder legen Sie einen Symlink an:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Originalfotos müssen auf dem NAS unter dem in `path_mapping` konfigurierten Pfad zugänglich sein, damit Downloads funktionieren.

### Konfiguration für wenig Speicher

Fügen Sie `viewer.performance` zu `scoring_config.json` auf dem NAS hinzu, um den Speicherverbrauch zu reduzieren:

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

Dies überschreibt die globalen `performance`-Einstellungen (die auf die Bewertung abgestimmt sind) mit Werten, die für 1 GB RAM geeignet sind. Siehe [Konfiguration](CONFIGURATION.md#viewer-performance) für Details.

### Ausführen

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Produktion (1 Worker für 1 GB RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Zugriff unter `http://your-synology-ip:5000`

### Automatischer Start

DSM > Systemsteuerung > Aufgabenplaner > Erstellen > Ausgelöste Aufgabe > Benutzerdefiniertes Skript:

- **Ereignis:** Hochfahren
- **Benutzer:** root
- **Skript:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Verwenden Sie den integrierten Reverse-Proxy von Synology:

DSM > Systemsteuerung > Anmeldeportal > Erweitert > Reverse-Proxy:

| Quelle | Ziel |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Kombinieren Sie dies mit einem Let's-Encrypt-Zertifikat aus DSM > Systemsteuerung > Sicherheit > Zertifikat.

## Synology NAS (Plus / x86-Serie)

NAS der Plus-Serie unterstützen Docker (Container Manager).

Das Repository liefert eine `Dockerfile`, `docker-compose.yml` und `docker-compose.gpu.yml` im Stammverzeichnis. Das Image bündelt den vollständigen Bewertungs- + Viewer-Stack auf einer CUDA-PyTorch-Basis, erstellt den Angular-Client und stellt Port 5000 bereit. Der Viewer läuft standardmäßig im CPU-Modus; die GPU-Überschreibung muss aktiv hinzugeschaltet werden.

### Das veröffentlichte Image ausführen

Installieren Sie genau wie unter [Installation › Installation mit Docker](INSTALLATION.md#installation-mit-docker):
`docker compose up -d` für ein CPU-NAS, oder den profilspezifischen Block, wenn das
Gerät eine NVIDIA-Karte hat. Die `.env`-Einstellungen und der Konfigurations-Mount sind
unter [Installation › Docker-Einstellungen, die Sie ändern können](INSTALLATION.md#docker-einstellungen-die-sie-ändern-können)
dokumentiert. Was folgt, ist nur das, was sich auf einem NAS unterscheidet.

**Beide veröffentlichten Images sind ausschließlich `linux/amd64` (x86_64).** Das deckt x86-NAS-Hardware ab (Synology Plus/x86, UGREEN, UnifyDrive und alles, was Coolify, Portainer oder ein gewöhnliches Docker auf einer Intel-/AMD-CPU betreibt). Es gibt kein `arm64`-Image: Das Cross-Compilieren eines mehrere Gigabyte großen ML-Stacks unter QEMU kostet Stunden pro Tag, und die CUDA-Variante ist ohnehin nur für x86 verfügbar. Bauen Sie es auf einem ARM-NAS oder einem Raspberry Pi stattdessen lokal mit `docker compose build`, statt es zu ziehen – `docker compose up` behält `build: .` unterhalb des Schlüssels `image:` genau für diesen Fall bei.

**Planen Sie den Speicherplatz.** Entpackt ist das CPU-Image etwa 3,3 GB groß und das
CUDA-Image etwa 21 GB (ungefähre Werte, nicht gegen den aktuellen Build reverifiziert;
der Download selbst überträgt weniger, komprimiert — siehe [Image-Größe](#image-größe)
weiter unten), dazu kommen die Modellgewichte, die jedes Profil beim ersten Lauf
herunterlädt (`legacy` 4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB, `24gb` 19,13 GB —
vollständige Tabelle unter
[Installation › Downloadgrößen](INSTALLATION.md#downloadgrößen)). `docker compose down -v`
löscht die Modell-Volumes und erzwingt einen erneuten Download.

**Versionierte Tags.** `:latest` und `:latest-cuda` bewegen sich bei jedem Release; pinnen Sie eine Version (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, …) auf einem NAS, das sich nicht unter Ihnen ändern soll. Beide Varianten werden aus demselben `Dockerfile` über die Build-Argumente `BASE_IMAGE`, `STRIP_TORCH` und `INSTALL_CUML` gebaut, pro Variante gesetzt in `.github/workflows/docker-publish.yml`. Dieser Workflow akzeptiert auch einen manuellen `workflow_dispatch`-Lauf, der `latest`/`latest-cuda` ausgehend von `master` erneut veröffentlicht, ohne dass dafür ein Release geschnitten oder ein versionierter Tag geprägt werden muss.

Für ein reines Viewer-NAS, bei dem das Image klein bleiben muss (kein CUDA), erstellen Sie stattdessen ein schlankes Image. Beachten Sie, dass der CI-Schutz verlangt, dass jede `COPY`-Quelle von Git verfolgt wird, sodass der Build-Kontext die aufgeführten Dateien enthalten muss:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite
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
      - /volume1/Photos:/volume1/Photos:ro  # Fotos für Downloads einhängen
    restart: always
```

## Speicherlimits für Container

Facet liest jetzt das Cgroup-Speicherlimit des Containers (`memory.max` bei cgroup v2, `memory.limit_in_bytes` bei v1) statt des gesamten RAM des Hosts, und bemisst danach die Pass-Gruppierung (welche Modelle gemeinsam geladen werden), die RAM-Chunk-Größe, das CPU-Caching der Modelle und die RAW-Dekodier-Nebenläufigkeit. Vor diesem Fix wurde all das anhand des Host-RAM bemessen: `psutil.virtual_memory()` liest `/proc/meminfo`, was Docker nicht virtualisiert, sodass ein `mem_limit` stillschweigend ignoriert wurde — ein Container, der weit unter dem RAM des Hosts gedeckelt war, plante sich weiterhin so, als stünde ihm der gesamte Host-RAM zur Verfügung, und wurde vom OOM-Killer beendet ([Issue #111](https://github.com/ncoevoet/facet/issues/111)).

Das Reproduzieren des Bugs mit einem veröffentlichten Image von vor dem Fix (v1.7.2) zeigt den Mechanismus: Ein Container im `8gb`-Profil, gedeckelt auf `--memory=8g` auf einem Host mit 47 GB, protokolliert `Mode: CPU-only (47GB RAM)` — den RAM des Hosts, nicht den des Containers — und plant einen einzigen Pass mit `clip + topiq_iaa + topiq_nr_face + liqe + saliency + samp_net + insightface [~15.0GB RAM]`. Er wird (`OOMKilled`, Exit-Code 137) beendet, bevor auch nur ein Chunk der 200 Fotos fertig ist. Bei einem Cgroup-Limit von 512 MB meldet der korrigierte Reader 0,500 GB, wo `/proc/meminfo` weiterhin die 46,8 GB des Hosts meldet.

### Empfohlener Mindestspeicher pro Profil

Modellgewichte sind nur ein Teil des Speicher-Peaks — die Torch-Laufzeitumgebung, der dekodierte Bild-Chunk und die Aktivierungen pro Schicht kommen hinzu — behandeln Sie diese Werte also als Untergrenzen, nicht als Budgets. Die Zeile `legacy`/`8gb` stützt sich jetzt auf reale Container-Tests — 50-Foto-Scans, die bei beiden Profilen mit `--memory=8g` erfolgreich abschließen (siehe unten); die Zeilen `16gb` und `24gb` bleiben vorläufige Platzhalter ohne realen Testlauf dahinter.

| VRAM-Profil | Modellgewichte (gesamt) | Empfohlener Container-Speicher |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB Minimum, 12 GB empfohlen (CPU) |
| `16gb` | 22,0 GB | mindestens 18 GB (vorläufig) |
| `24gb` | 25,0 GB | mindestens 18 GB (vorläufig) |

**GPU und CPU sind hier nicht austauschbar, und die 12-GB-Zahl oben ist eine GPU-Zahl.** Auf einer RTX 3080 erreichte das `8gb`-Profil des Meldungsautors einen Peak von 9,23 GB System-RAM für 405 Fotos, selbst mit `ram_chunk_size: 12` und `num_workers: 2`, und gelang mit `mem_limit: 12g`. Auf einer GPU liegen die Modellgewichte im VRAM; der RAM des Containers hält hauptsächlich den dekodierten Bild-Chunk, weshalb diese Zahl so viel kleiner ist als das, was reines CPU braucht. Dasselbe `8gb`-Profil auf CPU laufen zu lassen lädt stattdessen das gesamte Modell-Repertoire in den RAM des Containers. Bevor der Nachfolge-Fix zu Issue #111 eine Obergrenze einführte, stieg die Pro-Pass-Kapazität des Planers direkt mit dem Container-Limit, was den Plan mit wachsendem Limit schlechter machte, nicht besser: Ein 8-GB-Limit ergab 4 Pässe mit bis zu 6,0 GB, was in dem Pass mit `topiq_nr_face + liqe + saliency` (deklariert 6,0 GB, Peak-RSS 10,46 GB) zu einem OOM führte; ein 12-GB-Limit brach auf nur noch 2 Pässe mit bis zu 10,0 GB zusammen und führte ebenfalls zu einem OOM. Der Speicherregler griff bei dem 12-GB-Limit tatsächlich ein — `Evicted 1 model(s) from RAM cache: topiq_iaa` ist eine echte Log-Zeile —, aber das war der Regler, der eingreift und trotzdem nicht ausreicht, nicht das, was den Lauf gerettet hat.

Die Obergrenze hält die Pro-Pass-Kapazität jetzt bei 5,0 GB, egal wie groß das Container-Limit gemeldet wird, sodass sie nicht mehr mit dem Container mitwächst: Das `8gb`-Profil auf CPU plant unabhängig vom Limit immer dieselben 5 Pässe — `Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`, `Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`, `Pass 5: insightface [~2.0GB RAM]`.

Diese starre Form allein reichte immer noch nicht aus, weil zwei Dinge außerhalb des Pass-Plans das Budget aufbrauchten. Die automatische Chunk-Größenanpassung wuchs auf dem Speichertief zwischen den Pässen — jedes Entladen lässt die Auslastung fast bis auf den Boden fallen, und drei solcher Messwerte in Folge lasen sich wie Spielraum —, sodass `ram_chunk_size` gleich im allerersten Chunk von 10 auf 500 hochschnellte und der zweite versuchte, alle verbleibenden Fotos auf einmal zu dekodieren. Und das Entladen eines Modells gab dem Kernel nichts zurück: glibc behielt die freigegebenen Blöcke in seinen Arenen, sodass der Prozess einen Höchststand hielt, der von seinem ersten Pass gesetzt wurde, und jeder spätere Pass auf Speicher lief, den er nicht nutzen konnte. Da das Wachstum jetzt anhand des Peaks jedes einzelnen Chunks entschieden und der freigegebene Heap explizit zurückgegeben wird, schließt ein 50-Foto-Scan mit `--memory=8g` bei beiden Profilen ab — `legacy` erreicht dabei einen Peak von 7,26 GB und `8gb` von 7,56 GB anonymem Speicher, fünf Chunks von je zehn, Exit-Code 0, kein OOM-Kill und kein protokollierter Scan-Fehler.

**8 GB sind eine Untergrenze, kein komfortables Budget.** Beide Läufe endeten innerhalb von etwa einem halben Gigabyte der Grenze, bei 18-20 MP JPEGs; größere Bilder, RAW-Dekodierung oder ein stärker ausgelasteter Host werden diesen Spielraum aufzehren, weshalb 12 GB die Empfehlung und nicht das Minimum sind. Anonymer Speicher ist die Zahl, die es zu beobachten gilt — nicht das MemUsage von `docker stats` und nicht das `memory.current` der Cgroup, die beide rückgewinnbaren Seiten-Cache mitzählen, sodass Ersteres das reale Risiko unterschätzt und Letzteres nahe am Container-Limit hängen bleibt, egal wie viel Spielraum tatsächlich noch da ist. Bei einem 16-GB-Container wurden mindestens 12,55 GB anonymer Speicher gemessen, was auch erklärt, warum ein früherer 12-GB-Lauf getötet wurde, bevor diese beiden Fixes eingespielt waren, und das deckt sich mit dem vom Meldungsautor berichteten Peak von 9,23 GB auf GPU — demselben Modell-Repertoire, minus dem, was in der VRAM statt im Container-RAM liegt. Ein GPU-Nutzer, der sich an den CPU-Zahlen hier orientiert, würde überdimensionieren; ein CPU-Nutzer, der sich an der GPU-Zahl orientiert, würde unterdimensionieren — verwenden Sie, was zu der Art passt, wie Ihr Container tatsächlich läuft.

Allgemeiner: `MODEL_RAM_REQUIREMENTS` beziffert nur die Gewichtskosten. Der reale Speicher-Peak trägt zusätzlich die Torch-Laufzeitumgebung, den dekodierten Bild-Chunk und die Aktivierungen pro Schicht, von denen keines in dieser Zahl steckt — wer einen Container allein anhand der Spalte Modellgewichte (gesamt) dimensioniert, unterdimensioniert ihn.

Die Schätzungen für `16gb` und `24gb` haben weiterhin überhaupt keinen realen Lauf hinter sich, weder auf GPU noch auf CPU; betrachten Sie 18 GB als vorläufigen Platzhalter, nicht als validierte Untergrenze.

Setzen Sie das Limit in `docker-compose.yml` (oder einer Override-Datei):

```yaml
services:
  facet:
    mem_limit: 16g
```

### Die Pass-Gruppierung hat eine Obergrenze und gar keine Untergrenze

Facets Pass-Planer bemisst jeden CPU-Pass am Cgroup-Speicherlimit des Containers abzüglich einer Reserve von 2 GB für die Torch-Laufzeitumgebung, gedeckelt bei 5 GB — eine Obergrenze, die einen Pass unabhängig von der Größe des Limits nie weiter wachsen lässt. Unter diesem Limit gibt es keine Untergrenze: Ein Container mit wenig Spielraum nach der Reserve erhält ein kleines Budget, das bis auf null sinken kann, was schlicht ein Modell pro Pass isoliert.

Ist überhaupt kein Container-Speicherlimit gesetzt, stammt das Budget stattdessen aus dem System-RAM: was die Maschine neben ihrem Betriebssystem hält (1 GB dafür reserviert), geteilt durch 1,6 — das gemessene Verhältnis von realer RSS zum deklarierten Modellgewicht. Auch dieser Pfad hat keine Untergrenze: Ein 4-GB-Host bemisst 1,9 GB pro Pass, ein 2-GB-Host 0,6 GB. Frühere Versionen hielten hier ein optimistisches Minimum von 4 GB — genau der auf dieser Seite beschriebene Defekt im Gewand von Bare Metal: Er plante einen 5-GB-Pass in einer 4-GB-Maschine.

Ein Modell, das größer als das Budget ist, bekommt trotzdem einen eigenen Pass, statt aufgeteilt zu werden, und **jeder** solche Pass wird in einer Warnung benannt, nicht nur der schwerste: Bei einem Container-Limit von 4 GB beträgt die Kapazität 2 GB, und das `24gb`-Profil plant weiterhin einen 8,0-GB-Pass, weil `qwen3_5_4b_tagger` allein 8 GB benötigt und nicht geteilt werden kann, egal wie klein das Budget ist. Dimensionieren Sie einen Container niemals kleiner als das größte einzelne Modell im verwendeten Profil.

## Windows (WSL2) mit einer NVIDIA-GPU

Führen Sie den vollständigen GPU-Scoring- + Viewer-Stack in Docker unter Windows über WSL2 aus — ohne Docker Desktop. Das hält alles (die Linux-Distribution, ihre Docker-Images und `/var/lib/docker`) auf einem **Datenlaufwerk** (z. B. `D:`), was wichtig ist, wenn auf dem Systemlaufwerk `C:` wenig Platz ist.

**Voraussetzungen:** ein aktueller NVIDIA-Treiber unter Windows (`nvidia-smi` funktioniert an der Windows-Eingabeaufforderung — der Treiber stellt das WSL2-CUDA-Passthrough bereit; Sie installieren **keinen** Treiber innerhalb von WSL).

### 1. WSL2 installieren (Admin, einmalig)

In einer **erhöhten** (als Administrator ausgeführten) PowerShell, danach bei Bedarf neu starten:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Eine Distribution installieren, deren Datenträger auf dem Datenlaufwerk liegt

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` legt die `ext4.vhdx` der Distribution unter `D:\wsl\facet` ab, sodass der Image-Speicher von Docker nicht auf `C:` liegt. `--no-launch` überspringt die interaktive Erstlauf-Abfrage; die folgenden Befehle laufen als `root`, was für eine Maschine mit einem einzigen Verwendungszweck unproblematisch ist.

### 3. systemd aktivieren (für den Docker-Dienst erforderlich)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Docker CE + das NVIDIA Container Toolkit installieren (innerhalb der Distribution)

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

### 5. Facet ausführen

Das Repository auf dem Windows-Laufwerk ist innerhalb von WSL unter `/mnt/d/...`
sichtbar. Führen Sie von dort aus den Block für Ihre Karte aus
[Installation › Installation mit Docker](INSTALLATION.md#installation-mit-docker) aus:

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # oder die Datei für Ihre Karte
curl -s localhost:5000/health          # -> ok
```

Fügen Sie `--build` hinzu, um aus dem Checkout zu bauen, statt das veröffentlichte
Image zu ziehen. GPU-Profile (`8gb`/`16gb`/`24gb`) clustern Gesichter über das
eingebaute RAPIDS cuML auf der GPU; das `legacy`-Profil clustert immer auf der CPU.
Der erste Lauf lädt die Modelle des Profils in die benannten Volumes herunter; setzen
Sie sie mit `docker compose down -v` zurück.

### Reproduzierbares, autarkes Image

- **Fixierte Versionen.** Das Image wird aus `requirements.lock.txt` gebaut — einem vollständigen `pip freeze` eines validierten Containers, aus dem `torch`/`torchvision` und `nvidia-*` entfernt wurden (das CUDA-Basis-Image liefert diese bereits). Das verhindert stille Drift zu ungetesteten Releases. (Beispiel, wovor dies schützt: transformers 5.3 hat das Vision-Batching von Qwen3.5 geändert und den VLM-Tagger kaputtgemacht, bis der Padding-Fix landete; `kornia`, von BiRefNet benötigt, wird nicht von transformers mitgezogen und muss fixiert werden.) Nach einem bewussten Upgrade neu erzeugen: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **GPU-Gesichts-Clusterbildung eingebaut.** RAPIDS cuML (`cuml-cu12`) ist im Image enthalten, sodass die GPU-Profile (8gb/16gb/24gb) Gesichter auf der GPU clustern (HDBSCAN über `face_clustering.use_gpu="auto"`); das legacy-Profil — und jeder Host ohne CUDA-Gerät — clustert immer auf der CPU. cuML ist die mit Abstand größte Abhängigkeit (~5,75 GB; siehe die Größenaufschlüsselung unten).
- **Keine Host-Kopplung.** Modell-Caches sind benannte Volumes, keine Host-Bind-Mounts; der Container läuft ohne erhöhte Rechte (der Standard-Entrypoint wechselt zum Benutzer `facet`).
- **Schlanker Build-Kontext.** `.dockerignore` schließt lokalen Bulk-Inhalt aus (`conda/`, Beispieldatensätze, `*.db`, Caches, Entwicklungs-Artefakte) — halten Sie neue große lokale Verzeichnisse aus dem Kontext heraus, indem Sie sie dort ergänzen.

### Image-Größe

Keines der veröffentlichten Images enthält Modellgewichte — diese werden beim ersten
Start in die benannten Volumes heruntergeladen ([Summen pro Profil](INSTALLATION.md#downloadgrößen)).
Planen Sie Speicherplatz für das Image **plus** diese Volumes ein.

| Image | Komprimierter Download | Auf der Platte (ca.) | Basis |
|-------|------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 4,18 GB | ~3,3 GB | `python:3.12-slim` + CPU-Wheel-PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 7,33 GB | ~21 GB | CUDA-PyTorch + RAPIDS cuML |

„Komprimierter Download" ist das, was `docker pull` überträgt, gemessen anhand der
aktuellen `ghcr.io/ncoevoet/facet`-Registry-Manifeste. „Auf der Platte" ist der
entpackte Image-Fußabdruck nach der Dekomprimierung; diese Werte wurden für diesen
Durchgang nicht gegen den aktuellen `:latest`-Digest reverifiziert — behandeln Sie sie
als ungefähre Planungsgröße, nicht als präzise aktuelle Messung.

Das CPU-Image wird vom ML-Abhängigkeits-Stack dominiert (~1,9 GB) und nicht von
PyTorch selbst (~960 MB), dazu kommen System-Bibliotheken (~288 MB) und das Basis-OS
(~150 MB). Im CUDA-Image dominiert der GPU-Stack: RAPIDS cuML ~5,75 GB,
CUDA-Laufzeitbibliotheken ~3,7 GB, PyTorch und Triton ~1,9 GB, die ML-Abhängigkeiten
~1,9 GB, Basis-OS und conda ~2-3 GB.

## Generischer Linux-Server

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Oder verwenden Sie den Wrapper (Standard ist 1 Worker; übergeben Sie `--workers N` für mehr):

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

HTTPS hinzufügen:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Systemd-Dienst

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

### Caddy (automatisches HTTPS)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Arbeitsablauf

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

Führen Sie nach jeder Bewertungssitzung den Export und `rsync` erneut aus, um die Datenbank auf dem Server zu aktualisieren. Bei Servern mit viel Speicher können Sie die vollständige `photo_scores_pro.db` direkt synchronisieren, statt zu exportieren.

### Immer nur ein Bibliotheksauftrag

Ein Scan, `--recompute-average`, `--upgrade-db` und ein Training des persönlichen Rankers schreiben jeweils die gesamte Datenbank neu, daher lässt Facet nur einen davon gleichzeitig zu: Jeder nimmt eine Sperrdatei unter `<db_dir>/.facet_cache/library.lock`, und ein zweiter Auftrag verweigert den Start und nennt den bereits laufenden.

Diese Sperre ist eine Kernel-Dateisperre und schließt Aufträge daher **nur auf einer Maschine** aus. Wenn die Datenbank über SMB/CIFS erreicht wird — etwa eine Windows-Workstation, die Fotos auf einer NAS-Freigabe bewertet —, nimmt jede Maschine ihre eigene Kopie der Sperre und keine sieht die andere. Facet erkennt die Einhängung und protokolliert beim Nehmen der Sperre eine Warnung, kann aber maschinenübergreifend nichts erzwingen: Führen Sie Bibliotheksaufträge immer nur von einer Maschine aus. NFS zwischen Linux-Clients ist nicht betroffen — dort wird `flock` zu einer POSIX-Datensatzsperre, die der Server arbitriert.

## Speicherung und Rotation des Secrets

Ein einziges Secret signiert jede Anmeldesitzung (JWT) und jeden Fotorahmen-Link. Es ist **kein** Schlüssel in `scoring_config.json`: Es liegt in `.facet_secret` neben der Konfiguration, wird beim ersten Start mit Modus `0600` angelegt und von git ignoriert.

Früher war es der Schlüssel `share_secret` in `scoring_config.json`. Diese Datei wird von git verfolgt, sodass der beim ersten Start erzeugte Wert commitet und veröffentlicht wurde — das von diesem Projekt ausgelieferte Secret ist öffentlich und muss als kompromittiert gelten. Beim nächsten Start verschiebt Facet ein übriggebliebenes `share_secret` in die Secret-Datei, entfernt den Schlüssel aus der Konfiguration und protokolliert eine Warnung. Ein Wert, den Facet selbst veröffentlicht hat, wird ersetzt statt übernommen — das meldet absichtlich alle ab.

| Ort | Vorgehen |
|-----|----------|
| Standard | `.facet_secret` neben `scoring_config.json`, Modus `0600` |
| Container / Orchestrator | Umgebungsvariable `FACET_JWT_SECRET` — wird zuerst gelesen, nie auf die Platte geschrieben |
| Rotation | `python database.py --rotate-secret`, danach den Viewer neu starten |

Unter Docker ist `/app` die beschreibbare Schicht des Containers: Ein dort erzeugtes Secret geht beim Neuerstellen des Containers verloren — bei jedem Image-Update werden alle abgemeldet. Setzen Sie `FACET_JWT_SECRET` in `docker-compose.yml` oder binden Sie die Datei mit `- ./.facet_secret:/app/.facet_secret` ein.

Rotieren Sie, sobald das Secret von jemand anderem gelesen worden sein könnte: eine einmal commitete Konfiguration, ein geleaktes Backup, ein ausscheidender Administrator. Die Rotation entwertet jede Sitzung und jede signierte Rahmen-URL: Benutzer melden sich neu an, Kiosk-Geräte holen sich neue Links.

Mit `--workers > 1` lesen alle Worker dieselbe Datei, sodass ein von einem signiertes JWT in allen gültig ist — **sobald diese Datei existiert**. Ein erster Start mit `--workers > 1` und noch ohne `.facet_secret` ist die Ausnahme: Jeder Worker erzeugt sein eigenes Secret und nur einer gewinnt den Schreibvorgang, sodass eine an einem Worker geöffnete Sitzung von den anderen abgelehnt wird, bis der Server neu gestartet wird. Legen Sie das Secret vor dem ersten Multi-Worker-Start an — führen Sie einmal `python database.py --rotate-secret` aus, starten Sie einmal mit `--workers 1`, oder setzen Sie `FACET_JWT_SECRET`.

Dieselbe Divergenz wird dauerhaft, wenn das Installationsverzeichnis nicht beschreibbar ist: Der Server protokolliert einen Fehler und läuft mit einem Secret im Arbeitsspeicher, sodass jede Sitzung bei jedem Neustart verfällt und jeder Worker mit einem anderen Schlüssel signiert. Setzen Sie dort `FACET_JWT_SECRET`.

Sichern Sie die Datei zusammen mit der Datenbank — eine ohne sie wiederhergestellte Datenbank meldet alle ab.

## Mehrbenutzer-Einrichtung

Um jedem Benutzer einen privaten Satz von Fotoverzeichnissen zu geben, fügen Sie einen Abschnitt `users` zu `scoring_config.json` hinzu. Siehe [Konfiguration](CONFIGURATION.md#users) für die vollständige Referenz.

### Schnellstart

```bash
# Auf der Bewertungsmaschine Benutzer hinzufügen
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Bearbeiten Sie dann `scoring_config.json`:

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

Verzeichnispfade müssen mit den in der Datenbank gespeicherten Fotopfaden übereinstimmen. Wenn Sie `viewer.path_mapping` verwenden, sollten die Verzeichnisse die **zugeordneten** Pfade verwenden (wie sie auf dem Viewer-Host erscheinen).

### Vorhandene Bewertungen migrieren

Wenn Sie Bewertungen im Einzelbenutzermodus hatten, migrieren Sie diese zu einem Benutzer:

```bash
python database.py --migrate-user-preferences --user alice
```

### Scan-Schaltfläche

Um dem Superadmin zu erlauben, Fotoscans über die Viewer-Benutzeroberfläche auszulösen (nur sinnvoll, wenn der Viewer auf der GPU-Maschine läuft):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Kontinuierliche Backups mit Litestream

Die SQLite-Datenbank kann auf zehntausende Gigabyte anwachsen (`photo_scores_pro.db` erreicht ~14 GB nach der Bewertung von über 20.000 Fotos), und ein erneuter Scan kostet GPU-Zeit. [Litestream](https://litestream.io/) streamt das WAL kontinuierlich zu S3, B2, GCS, SFTP oder einer anderen lokalen Festplatte, mit Point-in-Time-Wiederherstellung bis auf wenige Sekunden genau.

Facet bündelt Litestream nicht. Installieren Sie es einmal auf dem Host, der den Viewer/die Bewertung ausführt; es läuft als Sidecar-Prozess, transparent für die Anwendung.

Facet verwendet bereits den WAL-Modus (`db/connection.py:apply_pragmas`), und der periodische Checkpoint-Thread (standardmäßig alle 30 Min., konfigurierbar über `performance.wal_checkpoint_minutes`) hält das WAL begrenzt. Lesevorgänge bleiben während der Replikation unblockiert.

### Minimale Litestream-Konfiguration

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

### Systemd-Unit

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

`litestream.env` enthält die AWS-/B2-Anmeldedaten, damit sie aus dem YAML herausgehalten werden.

### Wiederherstellungsübung

Üben Sie dies, bevor Sie es benötigen:

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

### Kosten-Richtwert

Für die 14-GB-Datenbank mit ~50 MB/Tag WAL-Aufkommen während aktiver Bewertung können Sie erwarten:
- ~0,30 $/Monat für Speicher auf S3 Standard
- ~0,05 $/Monat für PUT-Operationen
Vernachlässigbar im Vergleich zu einem erneuten Scan: ~50 GPU-Stunden auf einer 16-GB-RTX.
