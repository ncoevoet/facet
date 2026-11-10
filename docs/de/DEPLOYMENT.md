# Bereitstellungsleitfaden

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · **Deutsch** · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md) · [简体中文](../zh/DEPLOYMENT.md)

Betreiben Sie den Facet-Viewer auf einem entfernten Server oder NAS.

> **Neu hier?** Dieser Leitfaden ist für die Bereitstellung von Facet auf anderen
> Rechnern. Um es auf Ihrem eigenen Rechner zu betreiben, beginnen Sie mit
> [Installation](INSTALLATION.md).

## Überblick

Facet hat zwei Arbeitslasten:

| Komponente | Hardware | Zweck |
|-----------|----------|---------|
| **Bewertung** (`facet.py`) | GPU (6-24 GB VRAM) oder CPU (8 GB RAM Minimum, 12 GB empfohlen; mehr für `12gb`/`16gb`/`24gb`, siehe [Speicherlimits für Container](#speicherlimits-für-container)) | Fotos analysieren und bewerten |
| **Viewer** (`viewer.py`) | Beliebige Maschine (geringe Ressourcen) | Web-Galerie bereitstellen |

Nur der Viewer muss auf dem Server laufen. Bewerten Sie auf einer Workstation und synchronisieren Sie dann die Datenbank.

> **Warnung:** Solange `viewer.password` leer ist (Standardwert), kann jeder, der den
> Port des Viewers erreicht, die gesamte Bibliothek durchsuchen und die Originale
> herunterladen. Setzen Sie `viewer.password`, bevor Sie den Port über den Rechner
> hinaus öffnen; siehe [Einzelbenutzermodus](VIEWER.md#einzelbenutzermodus-standard).

Auf einer offenen Installation (ohne `viewer.password`) lassen sich Assistenten-Tokens
(**Assistent verbinden**) nur auf dem Rechner verwalten, auf dem Facet läuft. Setzen Sie
hinter Docker oder einem Reverse-Proxy `viewer.password` oder führen Sie die Anfrage auf
dem Host aus
(`docker compose exec facet python -c "import urllib.request ..."`). Ein Reverse-Proxy
muss `X-Forwarded-For` oder `Forwarded` senden, sonst wird er wie der lokale Rechner
behandelt.

## Pfadzuordnung

Wenn die Bewertungsmaschine und der Viewer Fotos unter unterschiedlichen Pfaden sehen,
setzen Sie `viewer.path_mapping` in `scoring_config.json`, um Datenbankpfade in lokale
Pfade zu übersetzen.

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

Dies ordnet `\\NAS\share\Photos\2024\IMG_001.jpg` dem Pfad `/volume1/Photos/2024/IMG_001.jpg` zu.
Verwenden Sie in Schlüsseln Schrägstriche; Backslashes werden normalisiert.

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

- Die Datenbank behält die ursprünglichen Scan-Pfade (z. B. `\\NAS\share\Photos\2024\IMG_001.jpg`).
- Vorschaubilder liegen in der Datenbank, sodass das Durchsuchen keinen Festplattenzugriff erfordert.
- Die Zuordnung greift immer dann, wenn der Viewer ein Original öffnet: Downloads,
  Vollauflösungsansicht, Beschreibung und Kritik.
- UNC-Pfade (`\\server\share`) und Laufwerksbuchstaben (`Z:\`) funktionieren beide.

## Pfadsemantik im Container

Unter Docker/Podman ist jeder Ordner, den Sie im Viewer eingeben, ein Pfad **innerhalb des Containers**.
Das betrifft ein Ziel für „In Ordner aussortieren“, ein Export-Ziel eines Albums und
`viewer.export.allowed_target_dirs`. Verwenden Sie den Einhängepunkt, niemals den Host-Pfad.

**Beispiel.** Die mitgelieferte `docker-compose.yml` hängt Ihre Fotos unter `/data/photos` ein:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Um Abgelehnte in einen Unterordner `rejects` auszusortieren, geben Sie `/data/photos/rejects` ein, nicht
`/home/sie/Bilder` oder `D:\Fotos`, die der Container nicht sehen kann.

Um außerhalb des Fotobaums zu schreiben, hängen Sie das Ziel zuerst ein und tragen Sie dann seinen
Container-Pfad in `viewer.export.allowed_target_dirs` ein:

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

Ein Ziel außerhalb jeder erlaubten Wurzel wird abgelehnt, nachdem Symlinks und `..` aufgelöst wurden.
Siehe [Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung).

**Diese Ablehnung ist kein Rechteproblem.** Sie geschieht, bevor irgendeine Datei berührt wird. Eine
UID-Abweichung zwischen dem `facet`-Benutzer des Containers und Ihrem Host-Konto ist ein separater
Fehler: Er tritt beim Kopieren/Verschieben auf und wird mit dem Betriebssystemfehler protokolliert.

### Wohin der Container-Papierkorb zeigt

Mit aktivem `viewer.cull.allow_trash` nutzt `trash_rejects` `send2trash`. Im mitgelieferten Layout
(Fotos per Bind-Mount unter `/data/photos`, uid 1000, `HOME=/home/facet`) liegen die Fotos und
`$HOME` auf verschiedenen Dateisystemen, sodass Dateien im Papierkorb im eigenen Papierkorb des Foto-Volumes landen:

- Dateien: `/data/photos/.Trash-1000/files/<name>`
- Metadaten: `<name>.trashinfo` (mit `Path=` und `DeletionDate=`) in `/data/photos/.Trash-1000/info/`
- das Verzeichnis wird mit dem Modus `0700` angelegt

`.Trash-1000` ist auf dem **Host** sichtbar, ein einfaches `mv` aus `files/` heraus stellt ein Foto also wieder her.
Neue Scans überspringen es, solange `scanning.skip_hidden_directories` wahr ist (Standard).

Zwei Ausnahmen:

- **Kein Bind-Mount** für die Fotos (z. B. ein `docker run` mit Fotos im Container):
  der Papierkorb liegt in `~/.local/share/Trash` im Container und geht **beim Entfernen des
  Containers verloren**.
- **Rootless Podman**: `.Trash-1000` gehört der zugeordneten Host-Sub-UID, nicht Ihrem Konto;
  zum Wiederherstellen kann `podman unshare` nötig sein.

Um das Ziel selbst zu wählen, nutzen Sie stattdessen `move_rejects` mit einem `target_dir`
([In Ordner aussortieren](VIEWER.md#in-ordner-aussortieren)).

### Dateibesitz der Konfiguration

Facet übernimmt nur den Besitz einer `/config/scoring_config.json`, die es selbst angelegt hat; eine vorhandene Datei
behält Eigentümer und Rechte. Die eine Ausnahme (eine Konfiguration, die der `facet`-Benutzer des Containers nicht
lesen kann) und das Rezept für rootless Podman stehen unter
[Installation — Dateibesitz im Container](INSTALLATION.md#dateibesitz-im-container).

Mit Compose-`group_add` (siehe [Foto-Freigaben, die nur über eine Gruppe lesbar sind](#foto-freigaben-die-nur-über-eine-gruppe-lesbar-sind-group_add))
nutzt die Lesbarkeitsprüfung auch diese Gruppen, eine über eine solche Gruppe lesbare Konfiguration
bleibt daher unberührt. Schlägt die `setpriv`-Prüfung selbst fehl, gilt die Datei als unlesbar.

## Erstellen des Angular-Clients

Der Server stellt die vorab erstellte SPA aus `client/dist/client/browser/` bereit. Erstellen Sie sie vor
der Bereitstellung:

```bash
cd client && npm ci && npm run build && cd ..
```

Dies erfordert Node.js 24.15.0 oder neuer (innerhalb von 24.x) nur zur Build-Zeit, nicht auf dem Server.

## Synology NAS (DS420j / J-Serie)

Die J-Serie hat eine ARM-CPU, 1 GB RAM und kein Docker. Der Viewer läuft direkt mit Python.

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
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Leichtgewichtige Datenbank exportieren

Exportieren Sie auf der Bewertungs-Workstation eine kleinere Datenbank für das NAS:

```bash
python database.py --export-viewer-db
```

Dies erstellt `photo_scores_viewer.db`, die:

- CLIP-, Bildunterschrift- und Gesichts-Embeddings entfernt;
- das Histogramm pro Foto (~2 KB) für das RGB-Histogramm-Widget behält;
- Vorschaubilder von 640px auf 320px verkleinert;
- startet mit leeren Listen gespeicherter und zuletzt verwendeter Orte; die privaten Orte des Bewertungsrechners werden nicht kopiert;
- eine 14-GB-Datenbank typischerweise auf ~4-5 GB reduziert.

Exporte erfolgen inkrementell: Es werden nur neue und geänderte Fotos synchronisiert. Für eine vollständige Neuerstellung:

```bash
python database.py --export-viewer-db --force-export
```

> **Warnung:** `--force-export` verwirft im Viewer auf dem NAS gesetzte Bewertungen, Standorte,
> manuelle Tags und private gespeicherte oder zuletzt verwendete Orte. Nur ein inkrementeller Export behält sie.

**Abschluss und Wiederholung.** Ein vollständiger Export wird in einer nur für den Eigentümer lesbaren temporären Verzeichnis neben dem Ziel vorbereitet, vom privaten Quellzustand befreit, verdichtet und vor der Veröffentlichung auf SQLite- und Fremdschlüssel-Konsistenz geprüft. Eine neue Ausgabe erscheint erst, wenn sie fertig ist. Das Ersetzen einer vorhandenen Ausgabe nutzt die Backup-Transaktion von SQLite und erhält ihren Inode für offene Leser und WAL-Verbindungen; bei einem Fehler bleibt die vorherige Datenbank erhalten. Eine vorhandene Ausgabe, die keine SQLite-Datenbank ist, wird als Datei ersetzt. Neue Ausgaben und Backup-Snapshots erfordern ein Dateisystem mit Hardlink-Unterstützung. Ohne diese schlägt der Befehl fehl, ohne eine unvollständige Datei zu veröffentlichen; wählen Sie dann ein kompatibles Ausgabeverzeichnis.

Ein inkrementeller Export aktualisiert zuerst das Zielschema und synchronisiert dann einen Quell-Snapshot in einer einzigen Zieltransaktion. Vorschaubilder neuer Fotos werden verkleinert und das Ziel wird auf Integrität geprüft, bevor diese Transaktion beginnt; Viewer-Schreibvorgänge warten daher nur, während die Änderungen angewendet werden. Eine fehlgeschlagene oder unterbrochene Datensynchronisierung macht Änderungen an Fotos, Gesichtern, Tags, Vektoren und Review-Quittungen gemeinsam rückgängig; das Schema-Upgrade kann bestehen bleiben. Beheben Sie die gemeldete Ursache und führen Sie denselben Befehl erneut aus. Ein beschädigtes Vorschaubild eines neuen Fotos ist ein Fehler; es in der Quelle zu reparieren und es erneut zu versuchen erzeugt auch sein Vorschaubild. Vorhandene Vorschaubilder bleiben unverändert. Review-Änderungen, manuelle Tags und gespeicherte/zuletzt verwendete Orte im Ziel bleiben lokal und werden von der inkrementellen Synchronisierung beibehalten.

Ausgabepfade sind wörtliche Dateinamen, auch Namen, die mit `file:` beginnen, auf Dateisystemen, die sie zulassen; SQLite-URI-Parameter werden nicht akzeptiert.

Exporte reservieren freien Speicher für Staging oder Rollback-Journale und schlagen vor dem Kopieren fehl, wenn die Schätzung nicht passt. Ausnahmen und normale Unterbrechungen entfernen die temporäre Kopie; ein hart beendeter Prozess kann neben der Ausgabe ein verstecktes, nur für den Eigentümer lesbares Verzeichnis `.*.export-*` hinterlassen. Entfernen Sie dieses temporäre Verzeichnis, sobald der Exporter beendet ist, und versuchen Sie es erneut. Die alte veröffentlichte Datenbank bleibt der Wiederherstellungspunkt. Die SQLite-Sperren gelten weiterhin: Wiederholen Sie bei Sperrfehlern, wenn der Schreiber im Ziel untätig ist.

Fehlt die Hauptdatei der Ausgabe, ist aber noch eine `-wal`-, `-shm`- oder `-journal`-Begleitdatei vorhanden, bricht der Export ab, ohne sie zu löschen. Schließen Sie alle Nutzer dieser Datenbank und stellen Sie sie wieder her, bevor Sie es erneut versuchen; ein verbliebenes WAL kann Daten der vorherigen Datenbank enthalten.

„Ähnliche finden“ funktioniert auf der exportierten Datenbank nicht (keine Embeddings). Verwenden Sie
dafür die Bewertungsmaschine.

**Manuelle Tags.** Der Export enthält die [manuellen Tags](VIEWER.md#manuelle-tags)
(`photo_manual_tags`). Ein inkrementeller Export fügt nur die Tags der Scoring-Datenbank hinzu:

- Ein auf dem NAS entferntes Tag kehrt zurück, wenn die Scoring-Datenbank es noch hat.
- Ein auf dem NAS hinzugefügtes Tag wird nie zurückkopiert; fügen Sie es auch auf dem Scoring-Rechner hinzu.
- Ein auf dem Scoring-Rechner entferntes Tag bleibt auf dem NAS bis `--force-export`.
- Die Obergrenze von 50 Tags pro Foto wird beim Zusammenführen nicht erzwungen, ein Foto kann sie also überschreiten.

### Dateien synchronisieren

Erstellen Sie zuerst den Angular-Client ([Erstellen des Angular-Clients](#erstellen-des-angular-clients)),
und synchronisieren Sie dann auf das NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` enthält die ausgelieferten Standardwerte, das NAS läuft also auf diesen. Um Ihre eigene
`scoring_config.json` zu verwenden, fügen Sie sie der `rsync`-Liste hinzu. Prüfen Sie sie zuerst: Sie enthält das Viewer-Passwort
und API-Schlüssel im Klartext.

Der Viewer öffnet standardmäßig `photo_scores_pro.db` (überschreibbar mit `DB_PATH`). Setzen Sie auf dem NAS
`DB_PATH=/volume1/facet/photo_scores_viewer.db` oder legen Sie einen Symlink an:

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Für Downloads müssen die Originale auf dem NAS unter dem Pfad aus `path_mapping` erreichbar sein.

### Konfiguration für wenig Speicher

Fügen Sie `viewer.performance` zu `scoring_config.json` auf dem NAS hinzu:

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

Dies überschreibt die globalen `performance`-Einstellungen (auf die Bewertung abgestimmt) mit Werten für 1 GB
RAM. Siehe [Konfiguration](CONFIGURATION.md#viewer-performance).

### Ausführen

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Produktion (1 Worker für 1 GB RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Öffnen Sie `http://your-synology-ip:5000`.

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

Verwenden Sie den Reverse-Proxy von Synology: DSM > Systemsteuerung > Anmeldeportal > Erweitert > Reverse-Proxy:

| Quelle | Ziel |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Ergänzen Sie ein Let's-Encrypt-Zertifikat aus DSM > Systemsteuerung > Sicherheit > Zertifikat.

Für die Tab-Brücke der Agenten ([KI-Agenten](AGENTS.md)) öffnen Sie den Reiter **Benutzerdefinierter Header** der Regel
und wählen **Erstellen > WebSocket**. Das fügt die Header `Upgrade` und `Connection` hinzu, die
`/api/mcp/bridge` braucht. Schreibt die Regel den `Host`-Header um, tragen Sie Ihren öffentlichen Ursprung in
`viewer.mcp.allowed_origins` ein.

## Synology NAS (Plus / x86-Serie)

NAS der Plus-Serie unterstützen Docker (Container Manager).

### Das veröffentlichte Image ausführen

Installieren Sie wie unter [Installation › Installation mit Docker](INSTALLATION.md#installation-mit-docker):
`docker compose up -d` auf einem CPU-NAS, oder den profilspezifischen Block mit einer NVIDIA-Karte. Die
`.env`-Einstellungen und der Konfigurations-Mount stehen unter
[Installation › Docker-Einstellungen, die Sie ändern können](INSTALLATION.md#docker-einstellungen-die-sie-ändern-können).
Unten steht nur, was sich auf einem NAS unterscheidet.

**Die Images sind ausschließlich `linux/amd64` (x86_64).** Das deckt x86-NAS-Hardware ab (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer oder gewöhnliches Docker auf Intel/AMD). Es gibt
kein `arm64`-Image. Bauen Sie auf einem ARM-NAS oder einem Raspberry Pi lokal mit
`docker compose build`; die Compose-Datei behält dafür `build: .` unterhalb des Schlüssels `image:`.

**Planen Sie den Speicherplatz:** das Image plus die Modelle, die jedes Profil beim ersten Lauf herunterlädt.

- Images, entpackt: CPU ~3,34 GB, `latest-cuda` (`sm_75`-`sm_120`) ~13,1 GB,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13,8 GB ([Image-Größe](#image-größe)).
  `docker pull` überträgt weniger, komprimiert.
- Modelle: `legacy` 4,69 GB, `8gb` 6,93 GB, `12gb`/`16gb` 14,55 GB, `24gb` 19,32 GB
  ([Downloadgrößen](INSTALLATION.md#downloadgrößen)).
- `docker compose down -v` löscht die Modell-Volumes und erzwingt einen erneuten Download.

**Versionierte Tags.** `:latest`, `:latest-cuda` und `:latest-cuda-legacy` bewegen sich bei jedem
Release. Pinnen Sie eine Version (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) auf einem NAS,
das sich nicht unter Ihnen ändern soll. Die Varianten werden aus einem `Dockerfile` über die Build-Argumente
`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` und `REQUIREMENTS_LOCK` gebaut, gesetzt in
`.github/workflows/docker-publish.yml`. Ein manueller `workflow_dispatch`-Lauf dieses Workflows
veröffentlicht `latest` / `latest-cuda` / `latest-cuda-legacy` ausgehend von `master` ohne Release erneut.

**Kommerzieller Build.** Fügen Sie `--build-arg FACET_LICENSING=commercial` hinzu (Compose:
`build.args.FACET_LICENSING: commercial`). Das lässt das eingeschränkte Lock weg (`insightface`,
`pyiqa` und deren Abhängigkeiten) und setzt `FACET_LICENSING_MODE=commercial`. Der Standard
`FACET_LICENSING=default` behält das veröffentlichte Verhalten bei. Das eingeschränkte Lock folgt
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` für das Legacy-Lock). Siehe
[Installation](INSTALLATION.md#kommerzielle-installation-und-die-eingeschränkten-pakete).

Für ein kleines Image nur mit Viewer (kein CUDA) bauen Sie ein schlankes. Jede `COPY`-Quelle muss von
Git verfolgt werden, weshalb `scoring_config.json` nicht kopiert wird; ohne sie läuft der Container
auf den Standardwerten in `config/`.

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

> **Die Tab-Brücke für Agenten braucht einen Worker.** Bei mehr als einem Worker kann ein `ui_*`-Aufruf
> einen Prozess erreichen, der Ihren Tab nicht kennt, und `no_tab` melden. Verwenden Sie `--workers 1`, wenn Sie
> [KI-Agenten](AGENTS.md) nutzen.

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

### Foto-Freigaben, die nur über eine Gruppe lesbar sind (`group_add`)

Auf einem NAS ist die Foto-Freigabe oft nur über eine Gruppe lesbar (bei Synology typischerweise
`users`, gid 100). Geben Sie dem Container diese Gruppe über `group_add`, mit der numerischen gid
aus `id <ihr-benutzer>` auf dem NAS:

```yaml
services:
  facet:
    group_add:
      - "100"
```

Der Entrypoint wechselt mit `setpriv` von root zu `facet` und behält diese gids. Prüfen mit
`docker compose exec facet grep Groups /proc/1/status`: Die Ausgabe enthält `1000` plus Ihre gids.

Alternative: mit `user: "1000:1000"` plus `group_add` laufen. Der Entrypoint führt dann weder
chown noch Initialisierung von `/config` aus, alle Mounts müssen also bereits für uid 1000 beschreibbar sein.

## Speicherlimits für Container

Facet liest das Speicherlimit des Containers (`memory.max` bei cgroup v2,
`memory.limit_in_bytes` bei v1) statt des RAM des Hosts. Danach bemisst es, welche Modelle gemeinsam
geladen werden, die RAM-Chunk-Größe, das Modell-Caching und die RAW-Dekodierung. Ältere
Releases (v1.7.2 und davor) ignorierten `mem_limit` und konnten vom OOM-Killer beendet werden
([Issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Empfohlener Mindestspeicher pro Profil

Modellgewichte sind nur ein Teil des Speicher-Peaks: Die Torch-Laufzeitumgebung, dekodierte Bilder und
Aktivierungen kommen hinzu. Behandeln Sie diese Werte als Untergrenzen.

| VRAM-Profil | Modellgewichte (gesamt) | Empfohlener Container-Speicher |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB Minimum, 12 GB empfohlen (CPU) |
| `12gb` / `16gb` | 22,0 GB | mindestens 18 GB (vorläufig) |
| `24gb` | 25,0 GB | mindestens 18 GB (vorläufig) |

- **GPU und CPU unterscheiden sich.** Auf einer GPU liegen die Gewichte im VRAM, und der RAM hält hauptsächlich dekodierte
  Bilder: Ein `8gb`-Lauf auf einer RTX 3080 (405 Fotos, `ram_chunk_size: 12`, `num_workers: 2`) erreichte einen Peak von
  9,23 GB und gelang mit `mem_limit: 12g`. Auf
  der CPU werden alle Modelle in den RAM geladen. Dimensionieren Sie nach der Zeile, die zu Ihrem Betrieb passt.
- **8 GB sind eine Untergrenze auf der CPU.** 50-Foto-Scans mit `--memory=8g` schlossen bei `legacy` (Peak 7,26 GB) und
  `8gb` (7,56 GB) ab, innerhalb von etwa einem halben Gigabyte der Grenze, bei 18-20 MP JPEGs. Größere Bilder, RAW-Dekodierung
  oder ein ausgelasteter Host brauchen mehr, daher werden 12 GB empfohlen.
- **`12gb`, `16gb` und `24gb` sind nicht gemessen.** 18 GB sind ein vorläufiger Platzhalter.
- **`12gb`-VRAM-Spitze: 9,4–11,3 GiB (simuliert).** Spitze der gesamten Karte unter Grenzen von 11,7 und 12,0 GiB, einschließlich etwa 2 GiB Desktop-Nutzung; die PyTorch-Spitze lag bei 6,3 GiB belegt, 8,8 GiB reserviert (Durchlauf des Qwen3.5-Taggers). Gemessen unter einer simulierten 12-GiB-Grenze auf einer 16-GB-Karte; ONNX-Runtime-Modelle (InsightFace) ignorieren die Grenze; nicht auf einer echten 12-GB-Karte gemessen.
- **Beobachten Sie den anonymen Speicher.** Das MemUsage von `docker stats` und das `memory.current` der Cgroup
  zählen beide rückgewinnbaren Seiten-Cache mit und führen daher in die Irre.
- **Modell-Caching.** Mit `models.keep_in_ram` auf `"auto"` bleibt ein Modell zwischen Chunks nur dann im RAM,
  wenn seine Größe plus `models.ram_cache_reserve_gb` (Standard 4 GB) frei ist. Eine kleinere
  Reserve cacht mehr ([Konfiguration](CONFIGURATION.md#models)).

Auf der CPU plant das `8gb`-Profil unabhängig vom Limit immer dieselben 5 Pässe:
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Setzen Sie das Limit in `docker-compose.yml` (oder einer Override-Datei):

```yaml
services:
  facet:
    mem_limit: 16g
```

### Die Pass-Gruppierung hat eine Obergrenze und gar keine Untergrenze

- **Mit Container-Limit** erhält jeder CPU-Pass das Limit abzüglich einer Reserve von 2 GB, gedeckelt bei
  5 GB. Ein knappes Limit bedeutet ein Modell pro Pass.
- **Ohne Limit** ergibt sich das Budget aus (System-RAM − 1 GB) ÷ 1,6. Ein 4-GB-Host erhält 1,9 GB pro
  Pass, ein 2-GB-Host 0,6 GB.
- **Ein Modell, das größer als das Budget ist,** bekommt trotzdem einen eigenen Pass, mit einer Warnung, die es nennt. Zum
  Beispiel ergibt `qwen3_5_4b_tagger` (`24gb`) allein einen 8,0-GB-Pass.

> **Warnung:** Dimensionieren Sie einen Container niemals kleiner als das größte einzelne Modell Ihres Profils.

## Windows (WSL2) mit einer NVIDIA-GPU

Führen Sie den GPU-Bewertungs- und Viewer-Stack in Docker unter Windows über WSL2 aus, ohne Docker
Desktop. Alles (die Distribution, ihre Images, `/var/lib/docker`) bleibt auf einem **Datenlaufwerk**
(z. B. `D:`), nützlich, wenn auf `C:` wenig Platz ist.

**Voraussetzungen:** ein aktueller NVIDIA-Treiber unter Windows (`nvidia-smi` funktioniert an der Windows-Eingabeaufforderung).
Installieren Sie **keinen** Treiber innerhalb von WSL.

### 1. WSL2 installieren (Admin, einmalig)

In einer **erhöhten** (als Administrator ausgeführten) PowerShell, danach bei Bedarf neu starten:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Eine Distribution installieren, deren Datenträger auf dem Datenlaufwerk liegt

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` legt die `ext4.vhdx` der Distribution unter `D:\wsl\facet` ab. `--no-launch` überspringt die
Erstlauf-Abfrage; die folgenden Befehle laufen als `root`.

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

Das Repository auf dem Windows-Laufwerk liegt innerhalb von WSL unter `/mnt/d/...`. Führen Sie den Block für Ihre Karte
aus [Installation › Installation mit Docker](INSTALLATION.md#installation-mit-docker) aus:

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # oder die Datei für Ihre Karte
curl -s localhost:5000/health          # -> ok
```

Fügen Sie `--build` hinzu, um aus dem Checkout zu bauen, statt zu ziehen. GPU-Profile
(`8gb`/`12gb`/`16gb`/`24gb`) clustern Gesichter über das mitgelieferte RAPIDS cuML auf der GPU; `legacy`
clustert auf der CPU. Der erste Lauf lädt Modelle in die benannten Volumes herunter; setzen Sie sie mit
`docker compose down -v` zurück.

### Reproduzierbares, autarkes Image

- **Fixierte Versionen.** Das Image wird aus `requirements.lock.txt` gebaut, einem `pip freeze` eines
  validierten Containers ohne `torch`/`torchvision` und `nvidia-*` (die CUDA-Basis liefert
  diese). `kornia`, von BiRefNet benötigt, wird dort ebenfalls fixiert. Nach einem
  bewussten Upgrade neu erzeugen: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **GPU-Gesichts-Clusterbildung enthalten.** RAPIDS cuML (`cuml-cu12`, ~5,75 GB) lässt GPU-Profile
  auf der GPU clustern (`face_clustering.use_gpu="auto"`). `legacy` und Hosts ohne CUDA
  clustern auf der CPU.
- **Keine Host-Kopplung.** Modell-Caches sind benannte Volumes; der Container läuft als
  unprivilegierter Benutzer `facet`.
- **Schlanker Build-Kontext.** `.dockerignore` schließt lokalen Bulk-Inhalt aus (`conda/`, Beispieldatensätze,
  `*.db`, Caches); ergänzen Sie dort neue große lokale Ordner.

### Image-Größe

Kein Image enthält Modellgewichte; diese werden beim ersten Start in die benannten Volumes heruntergeladen
([Summen pro Profil](INSTALLATION.md#downloadgrößen)). Planen Sie Speicherplatz für beides ein.

| Image | Auf der Platte (gemessen) | Basis |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + CPU-Wheel-PyTorch |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | CUDA-12.8-PyTorch (`sm_75`-`sm_120`, Turing bis Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | CUDA-12.6-PyTorch (`sm_50`-`sm_90`, Maxwell bis Hopper) + RAPIDS cuML |

„Auf der Platte“ ist die entpackte Größe (`docker images`). `docker pull` überträgt weniger; komprimierte
Größen sind noch nicht gemessen.

## Generischer Linux-Server

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Oder verwenden Sie den Wrapper (standardmäßig 1 Worker; `--workers N` für mehr):

```bash
python viewer.py --production --workers 4
```

Die Tab-Brücke für Agenten braucht `--workers 1` (siehe
[Das veröffentlichte Image ausführen](#das-veröffentlichte-image-ausführen)).

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

Die Tab-Brücke für Agenten (`/api/mcp/bridge`, siehe [KI-Agenten](AGENTS.md)) ist ein WebSocket. Sie
braucht die Header `Upgrade` und `Connection` des zweiten `location`-Blocks und einen einzigen Worker
(`--workers 1`, der Standard); sonst antworten die `ui_*`-Agentenwerkzeuge `no_tab`.

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

Verwenden Sie `--workers 1`, wenn Sie die Tab-Brücke für Agenten nutzen.

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

Führen Sie nach jeder Bewertungssitzung den Export und `rsync` erneut aus. Auf einem Server mit viel
Speicher können Sie stattdessen die vollständige `photo_scores_pro.db` synchronisieren.

### Immer nur ein Bibliotheksauftrag

Ein Scan, `--recompute-average`, `--upgrade-db` und ein Training des Rankers schreiben jeweils die
Datenbank neu, daher läuft immer nur einer. Ein zweiter Auftrag verweigert den Start, nennt den laufenden
und endet mit Code 75 (Code 1, wenn die Sperrdatei unter `<db_dir>/.facet_cache/library.lock`
unbrauchbar ist).

> **Warnung:** Diese Sperre wirkt **nur auf einer Maschine**. Über SMB/CIFS (z. B. eine Windows-
> Workstation, die auf eine NAS-Freigabe bewertet) hat jede Maschine ihre eigene Sperre. Facet protokolliert eine
> Warnung, kann es aber nicht verhindern: Führen Sie Bibliotheksaufträge immer nur von einer Maschine aus. NFS zwischen
> Linux-Clients ist unproblematisch.

### Viewer-Start und die Galerie-Indizes

Der erste Start nach einem Upgrade von 1.20 baut fehlende Galerie-Indizes
([Details](VIEWER.md#galerie-indizes-und-zähler-cache)). Bei einer Bibliothek mit ~130k Fotos dauert das
einige Minuten und vergrößert die Datenbank um etwa 130 MB.

**Empfohlen:** Führen Sie nach dem Upgrade einmal `python database.py` (Docker:
`docker compose exec facet python database.py`) aus, **bevor** Sie den Viewer starten. Auch ein
`python facet.py`-Scan baut sie bei seinem Start.

Baut stattdessen der Viewer sie:

- Er liefert während des Baus aus, aber die Galerie ist langsam, und **Speichern (Bewertungen, Ablehnungen, Albumänderungen …)
  kann mit der Meldung „Bibliothek beschäftigt, gleich erneut versuchen“ abgelehnt werden**.
- Das Protokoll zeigt je Index `Creating index ...` und `Created index ... in N s`, danach
  `Gallery indexes ready`. `/health` meldet den Fortschritt als `gallery_indexes` (`state`:
  `building`, `ready`, `deferred`, `failed` oder `stopped`; `done` von `total`).
- Das Stoppen des Viewers behält fertige Indizes; der nächste Start setzt fort.
- Läuft ein Scan oder ein anderer Bibliotheksauftrag, liefert der Viewer ohne die Indizes aus und
  protokolliert eine Warnung. Starten Sie ihn nach dem Ende des Auftrags neu oder führen Sie `python database.py` aus.
- Ist `.facet_cache/library.lock` neben der Datenbank nicht nutzbar (Berechtigungen, schreibgeschützter
  Mount), baut der Viewer nicht. Korrigieren Sie den Pfad und starten Sie neu.
- Mit `--workers N` baut ein Worker, die anderen liefern aus.
- Unter Docker braucht die `start_period` von 30 s des Healthchecks keine Änderung: `/health` antwortet während des Baus.

Auf SQLite älter als 3.48.0 (das CPU-Image liefert 3.46.1) kann die Panorama-Erkennung nicht allein
aus dem neuen Index lesen; ihre Geschwindigkeit dort wurde nicht gemessen. Auf einem anderen SQLite als 3.51
können Fotos mit identischen Zeitstempeln beim ersten Burst-Lauf nach dem Upgrade anders gruppiert werden
(siehe CHANGELOG).

> **Warnung:** Kopieren oder ersetzen Sie die Datenbank nur nach dem Stoppen des Viewers. Solange er läuft,
> liegen jüngste Änderungen in den Dateien `-wal` und `-shm`, nicht allein in der `.db`; ein sauberes Herunterfahren
> führt sie zusammen (auch mit `performance.wal_checkpoint_minutes: 0`). Unter Windows lässt sich die Datei
> gar nicht ersetzen, solange der Viewer sie geöffnet hat.

## Speicherung und Rotation des Secrets

Ein Secret signiert jede Anmeldesitzung (JWT) und jeden Fotorahmen-Link. Es liegt in
`.facet_secret` neben der Konfiguration (Modus `0600`, von git ignoriert), nicht in `scoring_config.json`.

Ältere Versionen speicherten es als `share_secret` in der Konfiguration, und der ausgelieferte Wert war öffentlich.
Beim Start verschiebt Facet ein übriggebliebenes `share_secret` in die Secret-Datei und entfernt den Schlüssel.
Ein Wert, den Facet selbst veröffentlicht hat, wird ersetzt, was alle einmal abmeldet.

| Ort | Vorgehen |
|-----|----------|
| Standard | `.facet_secret` neben `scoring_config.json`, Modus `0600` |
| Container / Orchestrator | Umgebungsvariable `FACET_JWT_SECRET` — wird zuerst gelesen, nie auf die Platte geschrieben |
| Rotation | `python database.py --rotate-secret`, danach den Viewer neu starten |

- **Docker:** `/app` ist die beschreibbare Schicht des Containers, ein dort erzeugtes Secret geht beim Neuerstellen
  verloren, und bei jedem Image-Update werden alle abgemeldet. Setzen Sie `FACET_JWT_SECRET` in
  `docker-compose.yml` oder binden Sie `- ./.facet_secret:/app/.facet_secret` ein.
- **Rotieren** Sie, sobald das Secret abgeflossen sein könnte (eine commitete Konfiguration, ein geleaktes Backup, ein
  ausscheidender Administrator). Alle melden sich neu an, und Kiosk-Geräte holen sich ihre Rahmen-Links neu.
- **Mehrere Worker:** Legen Sie das Secret vor dem ersten Start mit `--workers > 1` an (führen Sie
  einmal `python database.py --rotate-secret` aus, starten Sie einmal mit `--workers 1`, oder setzen Sie
  `FACET_JWT_SECRET`). Sonst erzeugt jeder Worker sein eigenes, und Sitzungen brechen bis zum Neustart.
- **Schreibgeschütztes Installationsverzeichnis:** Der Server läuft mit einem Secret im Arbeitsspeicher, sodass Sitzungen
  bei jedem Neustart verfallen. Setzen Sie `FACET_JWT_SECRET`.
- **Sichern Sie es** zusammen mit der Datenbank; eine ohne sie wiederhergestellte Datenbank meldet alle ab.

## Mehrbenutzer-Einrichtung

Um jedem Benutzer einen privaten Satz von Fotoverzeichnissen zu geben, fügen Sie einen Abschnitt `users` zu
`scoring_config.json` hinzu. Siehe [Konfiguration](CONFIGURATION.md#users).

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

Verzeichnispfade müssen mit den Fotopfaden in der Datenbank übereinstimmen. Verwenden Sie mit `viewer.path_mapping`
die **zugeordneten** Pfade (wie auf dem Viewer-Host).

### Vorhandene Bewertungen migrieren

Um Bewertungen aus dem Einzelbenutzermodus zu einem Benutzer zu übernehmen:

```bash
python database.py --migrate-user-preferences --user alice
```

### Scan-Schaltfläche

Damit der Viewer Scans auslösen kann (der Superadmin im Mehrbenutzermodus; eine Edition-Sitzung bei einer
Einzelbenutzer-Installation mit nicht leerem `viewer.edition_password`), aktivieren Sie sie. Der Scan läuft auf
dem Rechner des Viewers und braucht keine GPU ([Keine Grafikkarte](INSTALLATION.md#keine-grafikkarte)):

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

Die Datenbank kann auf zehn Gigabyte und mehr anwachsen (~14 GB nach über 20k Fotos), und ein erneuter Scan
kostet GPU-Zeit. [Litestream](https://litestream.io/) streamt Änderungen kontinuierlich zu S3,
B2, GCS, SFTP oder einer anderen Festplatte, mit Point-in-Time-Wiederherstellung bis auf wenige Sekunden genau.

Facet bündelt Litestream nicht. Installieren Sie es auf dem Host, auf dem Facet läuft; es läuft daneben,
ohne Änderungen an Facet. Der periodische WAL-Checkpoint von Facet (standardmäßig alle 30 Min.,
`performance.wal_checkpoint_minutes`; `0` deaktiviert ihn, ein sauberes Herunterfahren des Viewers führt trotzdem einen
Checkpoint aus) hält das WAL klein.

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

`litestream.env` enthält die AWS-/B2-Anmeldedaten, außerhalb des YAML.

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

Für eine 14-GB-Datenbank mit ~50 MB/Tag WAL-Aufkommen während aktiver Bewertung:

- ~0,30 $/Monat für Speicher auf S3 Standard
- ~0,05 $/Monat für PUT-Operationen

Vernachlässigbar im Vergleich zu einem erneuten Scan: ~50 GPU-Stunden auf einer 16-GB-RTX.
