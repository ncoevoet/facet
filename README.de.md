# Facet

> 🌐 [English](README.md) · [Français](README.fr.md) · **Deutsch** · [Italiano](README.it.md) · [Español](README.es.md) · [Português](README.pt.md)

Facet ist eine lokale Engine zur Fotoanalyse und Bildauswahl. Sie bewertet jedes Bild anhand von 9 Dimensionen — von der ästhetischen Qualität bis zur Gesichtsschärfe — und ermöglicht anschließend das Durchstöbern, Aussortieren und Organisieren über eine Web-Galerie. Alles läuft auf Ihrem Rechner; keine Cloud, keine Konten, keine API-Schlüssel.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-21-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet in Aktion — Galerie, Bewertung pro Foto, Auswahl, Kapseln, Zeitleiste, Karte und Statistiken" width="100%">
</p>

## Funktionsweise

1. **Scannen** — Richten Sie Facet auf einen Ordner mit Fotos. Jedes Bild wird auf Qualität, Komposition und Gesichter analysiert. Unterstützt JPG, HEIF/HEIC und 10 RAW-Formate (CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF).
2. **Durchstöbern** — Öffnen Sie die Web-Galerie, um Ihre Bibliothek mit Filtern, Suche und mehreren Ansichtsmodi zu erkunden.
3. **Aussortieren** — Facet erkennt Serienbilder, markiert Blinzler, gruppiert ähnliche Fotos und hebt die beste Auswahl hervor.

Die GPU wird automatisch erkannt und ist optional. Facet läuft rein über CPU oder mit bis zu 24 GB VRAM.

## Funktionen

### Bewerten

Jedes Foto wird anhand von 9 Dimensionen bewertet: ästhetische Qualität, Komposition, Gesichtsqualität, Augenschärfe, technische Schärfe, Farbe, Belichtung, Motiverkennung und Dynamikumfang. Fotos werden nach Inhalt kategorisiert (Porträt, Landschaft, Makro, Straße usw. — über 30 Kategorien) und mit kategoriespezifischen Gewichten bewertet. Ein Filter **Beste Auswahl** ordnet die Bibliothek anhand einer kombinierten Wertung.

Bewegen Sie den Mauszeiger über ein beliebiges Foto, um einen Tooltip mit der Wertungsaufschlüsselung und EXIF-Daten zu sehen.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Hover-Tooltip mit Wertungsaufschlüsselung" width="100%">

### Aussortieren

- **Serienbilderkennung** — gruppiert Schnellfeuer-Aufnahmen und wählt automatisch die beste anhand von Schärfe, Qualität und Blinzelerkennung aus
- **Ähnlichkeitsgruppen** — findet visuell ähnliche Fotos in der gesamten Bibliothek, unabhängig vom Aufnahmezeitpunkt
- **Szenen** — gruppiert eine Aufnahmesession anhand der zeitlichen Abstände in chronologische „Szenen“, sodass Sie in Erzählreihenfolge aussortieren; antippen zum Markieren, bestätigen zum Ablehnen
- **Müll aufräumen** — Zero-Shot-Erkennung von nicht-fotografischem Ballast (Screenshots, Dokumente, Belege, Memes, Folien) mit einer schnellen Review-Warteschlange: jeden Kandidaten behalten oder verwerfen, oder alle auf einmal verwerfen
- **Auswahl-Badges pro Gesicht** — der Auswahl-Viewer zeigt Badges pro Gesicht (Augen offen/geschlossen, Ausdruck, Erkennungssicherheit) statt einer einzigen fotoweiten Blinzelmarkierung
- **Blinzelerkennung** — markiert Aufnahmen mit geschlossenen Augen, um sie mit einem Klick auszublenden oder abzulehnen
- **Duplikaterkennung** — identifiziert nahezu identische Bilder über perzeptuelles Hashing

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Serienbildauswahl" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Ähnlichkeitsgruppen für die Auswahl" width="100%"></td>
</tr></table>

### Durchstöbern

- **Galeriemodi** — Mosaik (ausgerichtete Zeilen, die Seitenverhältnisse beibehalten) und Raster (einheitliche Karten mit Metadaten-Overlay)
- **Filter** — Zeitraum, Inhalts-Tag, Kompositionsmuster, Kamera, Objektiv, Person, Qualitätsstufe, Sternebewertung und benutzerdefinierte Metrikbereiche
- **Semantische Suche** — geben Sie eine natürlichsprachliche Anfrage wie „Sonnenuntergang am Strand“ ein und finden Sie passende Fotos über Embedding- und Textsuche
- **Zeitleiste** — chronologischer Browser mit Jahr-/Monatsnavigation und unendlichem Scrollen
- **Karte** — geotaggte Fotos auf einer interaktiven Karte mit Markierungs-Clustering
- **Kapseln** — thematische Diashows: Reisen mit Ortsnamen, goldene Sammlung, saisonale Paletten, Fotos einer Person und mehr
- **Ordner** — Durchsuchen nach Verzeichnisstruktur mit Brotkrumennavigation und Titelfotos
- **Erinnerungen** — „An diesem Tag“: Fotos vom selben Datum in vorherigen Jahren
- **Diashow** — Vollbildmodus mit thematischen Übergängen, automatischer Verkettung zwischen Kapseln und Tastatursteuerung

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Filter-Seitenleiste" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Ergebnisse der semantischen Suche" width="100%"></td>
</tr></table>

<details><summary>Filter-Seitenleiste — alle Abschnitte aufgeklappt (zum Anzeigen klicken)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Filter-Seitenleiste mit allen aufgeklappten Optionen" width="380"></p>
</details>

**Workflow-Tipps:**
- Für eine chronologische Durchsicht über eine Reise oder ein Jahr öffnen Sie **`/timeline`** — sortieren Sie nach Gesamtwertung, um die besten Aufnahmen eines Tages durchzugehen, oder blättern Sie Monat für Monat.
- Die Ansicht **`/capsules`** generiert thematische Diaporamas (Reisen, „Gesichter von“, saisonal, golden), die Sie als Alben speichern können.
- Die Galerie blendet Blinzler, Nicht-Leitbilder von Serienbildern und Duplikate standardmäßig aus. Wenn das Banner **„N Fotos durch aktuelle Filter ausgeblendet“** erscheint, klicken Sie auf „Alle anzeigen“, um die Ansicht zu erweitern.

### Organisieren

- **Gesichtserkennung** — automatische Gesichtserkennung, Gruppierung in Personen und Blinzelerkennung. Durchsuchen, umbenennen, zusammenführen und organisieren Sie Personencluster über die Verwaltungsoberfläche. **Zusammenführungsvorschläge** finden ähnlich aussehende Cluster, die dieselbe Person sein könnten.
- **Alben** — manuelle Sammlungen per Drag-and-Drop oder intelligente Alben, die sich automatisch aus gespeicherten Filterkombinationen füllen
- **Bewertungen & Favoriten** — Sternebewertungen (1–5), Favoriten und Ablehnungsmarkierungen. Wechseln Sie mit einem einzigen Klick durch die Bewertungen.
- **Tags** — KI-generierte Inhalts-Tags mit konfigurierbarem Vokabular. Klicken Sie auf ein beliebiges Tag, um die Galerie zu filtern.
- **Stapelverarbeitung** — Mehrfachauswahl mit Umschalt+Klick, Strg+Klick oder Strg+A (alles auswählen). Setzen Sie Bewertungen, schalten Sie Favoriten um, markieren Sie Ablehnungen oder fügen Sie mehrere Elemente zu Alben hinzu — mit einer 7-Sekunden-Rückgängig-Funktion für jede Stapelaktion.
- **Tastatur zuerst** — Pfeiltasten navigieren durch die Galerie, Eingabetaste öffnet, Leertaste wählt aus; drücken Sie überall `?` für die Tastenkürzelübersicht.

<img src="docs/screenshots/albums.jpg" alt="Alben — manuelle und intelligente Sammlungen" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Seite zur Personenverwaltung" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Personengalerie" width="100%"></td>
</tr></table>

### Verstehen

- **Statistiken** — Dashboards für Ausrüstungsnutzung, Kategorieaufschlüsselung, Aufnahme-Zeitverlauf und Metrik-Korrelationen
- **KI-Kritik** — Wertungsaufschlüsselung, die den Beitrag jeder Metrik zeigt; VLM-Bewertung in natürlicher Sprache `[GPU]` `[16gb/24gb]`
- **Gewichtungsfeinabstimmung** — Editor für kategoriespezifische Gewichte mit Live-Wertungsvorschau. Der A/B-Fotovergleich lernt aus Ihren Entscheidungen und schlägt optimierte Gewichte vor.
- **Sortierung „Mein Geschmack“** — sortieren Sie die Galerie nach der gelernten Wertung des persönlichen Rankers, mit einem Konfidenz-Badge, das die gelernte Abdeckung und die Holdout-Genauigkeit anzeigt
- **Lernen aus Labels** — Auswahlentscheidungen, Sternebewertungen, Favoriten und Ablehnungen fließen in den Gewichtsoptimierer ein (`--sync-label-comparisons`, `--mine-insights`)
- **Snapshots** — Gewichtskonfigurationen speichern, wiederherstellen und vergleichen
- **Histogramm** — Helligkeitshistogramm im Foto-Tooltip und in der Detailansicht
- **KI-Beschreibungen** `[GPU]` `[16gb/24gb]` `[Edition]` — Textbeschreibungen, bearbeitbar und in 5 Sprachen übersetzbar

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Ausrüstungsstatistiken" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Kategorieanalyse" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Aufnahme-Zeitverlauf" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Metrik-Korrelationen" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="Dialog zur KI-Kritik" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="Snapshots" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Schieberegler für Kategoriegewichte" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="A/B-Fotovergleich" width="100%"></td>
</tr></table>

### Teilen

- **Albumfreigabe** — generieren Sie teilbare Links für jedes Album, ohne dass sich Empfänger anmelden müssen. Widerrufen Sie den Zugriff jederzeit.
- **Foto-Download** — laden Sie einzelne Fotos oder Auswahlen aus der Galerie herunter
- **Export** — exportieren Sie alle Wertungen als CSV oder JSON zur externen Analyse

### Mehr

- **Dunkel- & Hellmodus** mit 10 Akzentfarbschemata; berücksichtigt die Systemeinstellung
- **Responsiv** — passt sich von Mobilgeräten bis zum Desktop an, mit einem touch-freundlichen Bereich für Stapelaktionen auf kleinen Bildschirmen
- **Installierbare PWA** — Web-App-Manifest + Service Worker: Installation auf dem Startbildschirm, Offline-App-Shell, zwischengespeicherte Vorschaubilder
- **Virtualisierte Galerie** — rendert unabhängig von der Bibliotheksgröße nur eine Handvoll DOM-Knoten, sodass das Scrollen auch bei mehr als 100.000 Fotos schnell bleibt
- **Fortsetzbare Scans** — unterbrochene Scans werden fortgesetzt (`--resume`), fehlgeschlagene Dateien werden erfasst und können erneut versucht werden (`--retry-failed`), der Fortschritt wird live an die Web-Oberfläche gestreamt
- **6 Sprachen** — Englisch, Französisch, Deutsch, Spanisch, Italienisch, brasilianisches Portugiesisch
- **Mehrbenutzerbetrieb** — benutzerspezifische Verzeichnisse, Bewertungen und rollenbasierter Zugriff
- **Plugins & Webhooks** — benutzerdefinierte Aktionen, die bei Bewertungsereignissen ausgelöst werden
- **Scannen über die Web-Oberfläche** — lösen Sie Scans über den Browser aus (Superadmin-Rolle)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Mobile Galerie" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Tablet-Galerie" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Desktop-Mosaik" width="100%"></td>
</tr></table>

## Was Sie benötigen

Der Großteil von Facet läuft auf **jedem Rechner (CPU)** — Bewertung, Gesichtserkennung, Auswahl, die Galerie, Suche, Alben und Metadaten-Export funktionieren alle ohne GPU. Eine **GPU** (mit dem `16gb`- oder `24gb`-Profil) schaltet die leistungsstärksten Modelle frei: TOPIQ-Ästhetikbewertung, SigLIP-2-Embeddings, VLM-Tagging, KI-Beschreibungen und -Kritik sowie Motiverkennung. Keine lokale GPU? Richten Sie das VLM-Tagging/die Beschreibungen/die Kritik über `vlm_backend` in `scoring_config.json` auf einen entfernten **Ollama**- oder **OpenAI-kompatiblen** Server aus — diese Funktionen laufen dann auch auf den CPU-Profilen `legacy`/`8gb`. Im Viewer benötigen Bearbeitungsaktionen (Bewertungen, Gesichter, Auswahl) das **Bearbeitungspasswort**, und das Auslösen von Scans erfordert die **Superadmin**-Rolle.

→ Vollständige Anforderungen pro Funktion (GPU, VRAM-Profil, optionale Pakete, Auth): **[Installation › Funktionsanforderungen](docs/de/INSTALLATION.md#funktionsanforderungen)**.

## Ist Facet das Richtige für Sie?

Facet bewertet, ordnet und sortiert eine lokale Fotobibliothek und stellt eine Galerie zum Durchstöbern bereit. Es läuft auf Ihrer eigenen Hardware und hält Fotos aus der Cloud heraus.

**Gut geeignet, wenn Sie:**

- eine große lokale Bibliothek haben und Ihre besten Aufnahmen finden sowie Serienbilder und Beinahe-Duplikate aussortieren möchten;
- eine Bewertung von Qualität, Komposition und Gesichtern wünschen, die Sie auf Ihren eigenen Geschmack abstimmen können (sie lernt aus Ihren A/B-Vergleichen);
- selbstgehostet und privat bevorzugen — kein Cloud-Upload, kein Konto, kein Abonnement;
- bereits in Lightroom, darktable, digiKam oder immich bearbeiten — Facet schreibt Bewertungen, Labels, Stichwörter, Beschreibungen und benannte Gesichtsregionen in `.xmp`-Sidecars (Originale standardmäßig unangetastet) und kann sie optional in JPEG/HEIC/TIFF/PNG/DNG einbetten (die Galerie-Aktion „Metadaten in Datei schreiben" oder `--export-sidecars --embed-originals`) und liest externe Bearbeitungen mit `--import-sidecars` wieder ein.

**Wahrscheinlich nichts für Sie, wenn Sie wünschen:**

- einen schlüsselfertigen, mobilen, cloudgestützten Google-Fotos-Ersatz mit automatischem Telefon-Backup;
- RAW-Bearbeitung oder -Entwicklung — Facet bewertet und organisiert, es bearbeitet nicht;
- eine Desktop-App ohne jegliche Einrichtung — sie benötigt Python, und die besten Modelle benötigen eine GPU.

**Wie es sich zu anderen Tools verhält**

- Selbstgehostete Bibliotheken (Immich, PhotoPrism) konzentrieren sich auf Organisieren, Suche und Backup. Facet ergänzt sie um Qualitätsbewertung, Ranking und einen Auswahl-Workflow, den sie nicht bieten, hat aber keine mobile App und kein integriertes Backup/Sync.
- KI-Auswahl-Apps (Aftershoot, Narrative, FilterPixel) sind ausgefeilte kommerzielle Auswahltools, oft mit integrierter Bearbeitung. Facet ist kostenlos, lokal, umfassender (Galerie, Suche, Gesichter) und seine Bewertung ist anpassbar — aber es ist ein Einzelentwicklerprojekt ohne deren Support oder RAW-Bearbeitung.
- Editoren und Kataloge (Lightroom, darktable, digiKam) entwickeln und verwalten Fotos. Facet ergänzt sie über die oben beschriebene XMP-Metadaten-Interoperabilität, anstatt sie zu ersetzen.

Die Ästhetikwertung ist modellbasiert und ungefähr; rechnen Sie damit, die Gewichte an Ihren Geschmack anzupassen.

## Schnellstart

### Docker (empfohlen)

```bash
docker compose up
# http://localhost:5000 öffnen
```

Dies läuft im CPU-Modus — es ist keine GPU erforderlich, um eine vorhandene Bibliothek zu durchstöbern und bereitzustellen. Binden Sie Ihr Fotoverzeichnis in `docker-compose.yml` ein.

**GPU-Beschleunigung** (optional) erfordert eine NVIDIA-GPU und das [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). Aktivieren Sie sie mit der Override-Datei:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

### Manuelle Installation

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # erkennt die GPU automatisch, erstellt das venv, installiert alles

source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py /photos  # Fotos bewerten
python viewer.py         # Web-Viewer starten → http://localhost:5000
```

> **macOS:** Der AirPlay-Empfänger des ControlCenters belegt standardmäßig Port 5000. Wenn Sie „Address already in use“ sehen, führen Sie `python viewer.py --port 5001` aus.

Das Installationsskript erkennt automatisch Ihre CUDA-Version, installiert die passende PyTorch-Variante, baut das Angular-Frontend und überprüft alle Importe. Optionen: `--cpu` (CPU erzwingen), `--cuda 12.8` (CUDA-Version überschreiben), `--skip-client` (Frontend-Build überspringen).

<details>
<summary>Schritt-für-Schritt-Anleitung zur manuellen Installation</summary>

```bash
# 1. exiftool installieren (optional, aber empfohlen)
# Ubuntu/Debian: sudo apt install libimage-exiftool-perl
# macOS:         brew install exiftool

# 2. Virtuelle Umgebung erstellen
python -m venv venv && source venv/bin/activate

# 3. PyTorch mit CUDA installieren (wähle deine Version unter https://pytorch.org/get-started/locally)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 4. Python-Abhängigkeiten installieren (alle auf einmal — siehe Fehlerbehebung bei Konflikten)
pip install -r requirements.txt

# 5. ONNX Runtime für die Gesichtserkennung installieren (wähle EINE)
pip install onnxruntime-gpu>=1.17.0   # GPU (CUDA 12.x)
# pip install onnxruntime>=1.15.0     # CPU-Fallback

# 6. Angular-Frontend bauen
cd client && npm install && npx ng build && cd ..

# 7. Fotos bewerten und Viewer starten
python facet.py /path/to/photos
python viewer.py
```
</details>

Führen Sie `python facet.py --doctor` aus, um GPU-Probleme zu diagnostizieren. Siehe [Installation](docs/de/INSTALLATION.md) für VRAM-Profile, VLM-Tagging-Pakete (16gb/24gb), optionale Abhängigkeiten und [Fehlerbehebung bei Abhängigkeitskonflikten](docs/de/INSTALLATION.md#troubleshooting-dependency-conflicts).

## Dokumentation

| Dokument | Beschreibung |
|----------|-------------|
| [Installation](docs/de/INSTALLATION.md) | Anforderungen, GPU-Einrichtung, VRAM-Profile, Abhängigkeiten |
| [Befehle](docs/de/COMMANDS.md) | Referenz aller CLI-Befehle |
| [Konfiguration](docs/de/CONFIGURATION.md) | Vollständige Referenz zu `scoring_config.json` |
| [Bewertung](docs/de/SCORING.md) | Kategorien, Gewichte, Leitfaden zur Feinabstimmung |
| [Gesichtserkennung](docs/de/FACE_RECOGNITION.md) | Gesichts-Workflow, Clustering, Personenverwaltung |
| [Viewer](docs/de/VIEWER.md) | Funktionen und Nutzung der Web-Galerie |
| [Interop](docs/de/INTEROP.md) | Bewertungen/Tags mit Lightroom, Capture One, digiKam, darktable austauschen |
| [Bereitstellung](docs/de/DEPLOYMENT.md) | Produktivbereitstellung (Synology NAS, Linux, Docker) |
| [Mitwirken](CONTRIBUTING.md) | Entwicklungseinrichtung, Architektur, Code-Stil |

## Lizenz

[MIT](LICENSE)
