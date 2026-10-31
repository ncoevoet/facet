# Facet

> 🌐 [English](README.md) · [Français](README.fr.md) · **Deutsch** · [Italiano](README.it.md) · [Español](README.es.md) · [Português](README.pt.md) · [简体中文](README.zh.md)

Facet ist eine lokale Engine zur Fotoanalyse und Bildauswahl. Sie bewertet jedes Bild anhand von 9 Dimensionen — von der ästhetischen Qualität bis zur Gesichtsschärfe — und ermöglicht anschließend das Durchstöbern, Aussortieren und Organisieren über eine Web-Galerie. Alles läuft auf Ihrem Rechner; keine Cloud, keine Konten, keine API-Schlüssel.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-22-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet in Aktion — Galerie, Bewertung pro Foto, Auswahl, Kapseln, Zeitleiste, Karte und Statistiken" width="100%">
</p>

## Funktionsweise

1. **Scannen** — Richten Sie Facet auf einen Ordner mit Fotos. Jedes Bild wird auf Qualität, Komposition und Gesichter analysiert. Unterstützt JPEG, HEIF/HEIC, 10 RAW-Formate, JPEG XL, AVIF, PNG, WebP, TIFF und mehr — siehe [unterstützte Dateitypen](docs/de/README.md#unterstützte-dateitypen).
2. **Durchstöbern** — Öffnen Sie die Web-Galerie, um Ihre Bibliothek mit Filtern, Suche und mehreren Ansichtsmodi zu erkunden.
3. **Aussortieren** — Facet erkennt Serienbilder, markiert Blinzler, gruppiert ähnliche Fotos und hebt die beste Auswahl hervor. Belichtungsreihen und Panorama-/HDR-Sets werden erkannt und vollständig erhalten, statt auseinandergerissen zu werden.

Die GPU wird automatisch erkannt und ist optional. Facet läuft rein über CPU oder mit bis zu 24 GB VRAM.

## Funktionen

### Bewerten

Jedes Foto wird anhand von 9 Dimensionen bewertet: ästhetische Qualität, Komposition, Gesichtsqualität, Augenschärfe, technische Schärfe, Farbe, Belichtung, Motiverkennung und Dynamikumfang. Fotos werden nach Inhalt kategorisiert (Porträt, Landschaft, Makro, Straße usw. — über 30 Kategorien) und mit kategoriespezifischen Gewichten bewertet. Ein Filter **Beste Auswahl** ordnet die Bibliothek anhand einer kombinierten Wertung.

Bewegen Sie den Mauszeiger über ein beliebiges Foto, um die Wertungsaufschlüsselung und EXIF-Daten in der Seitenleiste der Galerie zu sehen, oder wechseln Sie zu einer Hover-Blase, die die wichtigsten Wertungen auf einen Blick zeigt.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Hover-Tooltip mit Wertungsaufschlüsselung" width="100%">

### Aussortieren

- **Serienbilderkennung** — gruppiert Schnellfeuer-Aufnahmen und wählt automatisch die beste anhand von Schärfe, Qualität und Blinzelerkennung aus
- **Sequenzschutz** — Belichtungsreihen, Panoramen und HDR-Panoramen (`--detect-sequences` / `--detect-panoramas`) werden als Sets erkannt; die Auswahl-Dunkelkammer markiert jede Aufnahme eines Sets von vornherein als „behalten“
- **Ähnlichkeitsgruppen** — findet visuell ähnliche Fotos in der gesamten Bibliothek, unabhängig vom Aufnahmezeitpunkt
- **Szenen** — gruppiert eine Aufnahmesession anhand der zeitlichen Abstände in chronologische „Szenen“, sodass Sie in Erzählreihenfolge aussortieren; antippen zum Markieren, bestätigen zum Ablehnen
- **Auto-Cull** — ein Button sortiert einen ganzen Umfang aus (alle Gruppen oder nur Serienbilder / Ähnliche / Szenen, optional auf ein Album oder Zeitfenster eingegrenzt) mit Probelauf-Vorschau, Budget für behaltene Fotos und optionalem Highlights-Album
- **Auto-Cull im Terminal** — `python facet.py --auto-cull [PATH]` zeigt das Aussortieren als Probelauf, `--apply` schreibt es und `--copy-keepers DIR` kopiert die behaltenen Fotos (siehe [docs/de/COMMANDS.md](docs/de/COMMANDS.md#culling))
- **Genre-Profile** — Voreinstellungen für Sport / Hochzeit / Konzert / Wildtiere bündeln Strenge, Budget für behaltene Fotos, Ähnlichkeitsschwelle und Gesichtsprüfungen in einer einzigen Auswahl
- **Vorschau des bearbeiteten Looks** `[Edition]` — rendert ein Foto in der Auswahl-Dunkelkammer durch einen benannten darktable-Stil, sodass Sie anhand des entwickelten Looks statt der flachen RAW-Vorschau aussortieren
- **Motiv-Nahaufnahmen** — Gruppen ohne Gesicht (Wildtiere, Makro, Produkt) werden über einen automatisch zugeschnittenen Motivstreifen mit gruppennormalisierten Schärfe-Badges verglichen
- **Müll aufräumen** — Zero-Shot-Erkennung von nicht-fotografischem Ballast (Screenshots, Dokumente, Belege, Memes, Folien) mit einer schnellen Review-Warteschlange: jeden Kandidaten behalten oder verwerfen, oder alle auf einmal verwerfen
- **Auswahl-Badges pro Gesicht** — der Auswahl-Viewer zeigt Badges pro Gesicht (Augen offen/geschlossen, Ausdruck, Erkennungssicherheit) statt nur einer fotoweiten Blinzelmarkierung; optionale MediaPipe-Blendshapes schärfen die Augen-/Lächeln-Messung
- **Blinzelerkennung** — markiert Aufnahmen mit geschlossenen Augen, um sie mit einem Klick auszublenden oder abzulehnen
- **Duplikaterkennung** — identifiziert nahezu identische Bilder über perzeptuelles Hashing

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Serienbildauswahl" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Ähnlichkeitsgruppen für die Auswahl" width="100%"></td>
</tr></table>

### Durchstöbern

- **Galeriemodi** — Mosaik (ausgerichtete Zeilen, die Seitenverhältnisse beibehalten) und Raster (einheitliche Karten mit Metadaten-Overlay)
- **Filter** — Zeitraum, Inhalts-Tag, Kompositionsmuster, Kamera, Objektiv, Person, Ordner, Qualitätsstufe, Sternebewertung und benutzerdefinierte Metrikbereiche
- **Semantische Suche** — geben Sie eine natürlichsprachliche Anfrage wie „Sonnenuntergang am Strand“ ein und finden Sie passende Fotos über Embedding- und Textsuche
- **Zeitleiste** — chronologischer Browser mit Jahr-/Monatsnavigation und unendlichem Scrollen
- **Karte** — geotaggte Fotos auf einer interaktiven Karte mit Markierungs-Clustering
- **Kapseln** — thematische Diashows: Reisen mit Ortsnamen, goldene Sammlung, saisonale Paletten, Fotos einer Person und mehr
- **Ordner** — Durchsuchen nach Verzeichnisstruktur mit Brotkrumennavigation und Titelfotos
- **Erzählmomente** — Zero-Shot-Labels für Szene/Aktivität (Strand, Feier, Konzert, …) benennen Ihre Szenen, filtern und sortieren die Galerie und speisen die Auswahl für Kapseln
- **Erinnerungen** — „An diesem Tag“: Fotos vom selben Datum in vorherigen Jahren
- **Diashow** — Vollbildmodus mit thematischen Übergängen, automatischer Verkettung zwischen Kapseln und Tastatursteuerung

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Filter-Seitenleiste" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Ergebnisse der semantischen Suche" width="100%"></td>
</tr></table>

<details><summary>Vollständige Filter-Seitenleiste — alle Abschnitte aufgeklappt (zum Anzeigen klicken)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Die fünf Tabs der Filter-Seitenleiste nebeneinander: Durchsuchen, Prüfen, Qualität, Motiv und Anzeige" width="900"></p>
</details>

**Workflow-Tipps:**
- **`/timeline`** führt von Jahren über Monate zu Tagen; klicken Sie auf einen Tag, um die Galerie auf dieses Datum zu öffnen.
- **`/capsules`** erstellt thematische Diashows (Reisen, „Gesichter von“, saisonal, golden), die Sie als Alben speichern können — die bessere Wahl, um die besten Aufnahmen einer Reise auszuwählen.
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
- **Bewertungskontexte** — legen Sie fest, *welche* Kategorie ein Foto bewertet: die Kategoriepriorität neu ordnen, einen benannten Kontext (Action/Bühne, Porträtsitzung, Wildtiere, …) pro Album anwenden oder bei einem Foto eine Kategorie festlegen.
- **Sortierung „Mein Geschmack“** — sortieren Sie die Galerie nach der gelernten Wertung des persönlichen Rankers, mit einem Konfidenz-Badge, das die gelernte Abdeckung und die Holdout-Genauigkeit anzeigt
- **Lernen aus Labels** — Auswahlentscheidungen, Sternebewertungen, Favoriten und Ablehnungen fließen in den Gewichtsoptimierer ein (`--sync-label-comparisons`, `--mine-insights`)
- **Snapshots** — Gewichtskonfigurationen speichern, wiederherstellen und vergleichen
- **Histogramm** — RGB-/Helligkeitshistogramm mit Clipping-Indikatoren, in der Seitenleiste der Galerie und in der Detailansicht
- **KI-Beschreibungen** `[GPU]` `[16gb/24gb]` — Textbeschreibungen, bearbeitbar `[Edition]` und in 5 Sprachen übersetzbar (Ansehen ist offen; Erzeugen und Bearbeiten benötigen Edition)

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
- **Kundenabnahme** — ein freigegebenes Album kann im Abnahmemodus laufen: Kunden vergeben Herzen und hinterlassen Kommentare allein mit dem Link (plus optionaler PIN), vollständig getrennt von Ihren eigenen Bewertungen
- **Automatischer Telefon-Upload** — richten Sie PhotoSync oder eine beliebige WebDAV-App auf den eingebauten Eingang `/dav`; `--watch` bewertet neue Aufnahmen, sobald sie eintreffen
- **Bilderrahmen & Kioske** — ein durch Token geschützter Endpunkt liefert Ihre ausgewählten besten Aufnahmen an smarte Bilderrahmen und Home-Assistant-Dashboards
- **KI-Agenten (MCP)** — ein [Model Context Protocol](https://modelcontextprotocol.io/)-Endpunkt (standardmäßig aktiviert, `viewer.mcp.enabled`) lässt Assistenten die Bibliothek mit widerrufbaren persönlichen Tokens durchsuchen. Höhere Token-Stufen können bewerten, taggen, organisieren und aussortieren; destruktive Aktionen zeigen zuerst eine Vorschau und brauchen eine Bestätigung
- **Portfolio-Export** `[Edition]` — rendert ein Album zu einer eigenständigen statischen HTML-Galerie (keine CDN-Verweise, funktioniert offline), die Sie auf jedem Webhost ablegen können
- **Social-Zuschnitte** `[Edition]` — Exporte in voller Auflösung, auf das erkannte Motiv zugeschnitten, für quadratische, Hochformat- und Story-Seitenverhältnisse
- **Foto-Download** — laden Sie einzelne Fotos oder Auswahlen aus der Galerie herunter
- **Export** — exportieren Sie alle Wertungen als CSV oder JSON zur externen Analyse

### Mehr

- **Dunkel- & Hellmodus** mit 10 Akzentfarbschemata; berücksichtigt die Systemeinstellung
- **Responsiv** — passt sich von Mobilgeräten bis zum Desktop an, mit einem touch-freundlichen Bereich für Stapelaktionen auf kleinen Bildschirmen
- **Installierbare PWA** — Web-App-Manifest + Service Worker: Installation auf dem Startbildschirm, Offline-App-Shell, zwischengespeicherte Vorschaubilder
- **Virtualisierte Galerie** — rendert unabhängig von der Bibliotheksgröße nur eine Handvoll DOM-Knoten, sodass das Scrollen auch bei mehr als 100.000 Fotos schnell bleibt
- **Fortsetzbare Scans** — unterbrochene Scans werden fortgesetzt (`--resume`), fehlgeschlagene Dateien werden erfasst und können erneut versucht werden (`--retry-failed`), der Fortschritt wird live an die Web-Oberfläche gestreamt
- **7 UI-Sprachen** — die Oberfläche ist auf Englisch, Französisch, Deutsch, Spanisch, Italienisch, brasilianischem Portugiesisch und vereinfachtem Chinesisch (简体中文) verfügbar; die Dokumentation gibt es in allen sieben Sprachen
- **Mehrbenutzerbetrieb** — benutzerspezifische Verzeichnisse, Bewertungen und rollenbasierter Zugriff
- **Plugins & Webhooks** — benutzerdefinierte Aktionen, die bei Bewertungsereignissen ausgelöst werden
- **Scannen über die Web-Oberfläche** — lösen Sie Scans über den Browser aus (Superadmin im Mehrbenutzermodus; Edition-Zugriff bei einer Einzelbenutzer-Installation mit Bearbeitungspasswort)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Mobile Galerie" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Tablet-Galerie" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Desktop-Mosaik" width="100%"></td>
</tr></table>

## Was Sie benötigen

- **Jeder Rechner (CPU)** führt den Großteil von Facet aus: Bewertung, Gesichter, Auswahl, die Galerie, Suche, Alben und Metadaten-Export.
- **Apple Silicon** nutzt automatisch das Metal-Backend (`mps`). Das Profil `auto` folgt dem Unified Memory: 32 GB erreichen `16gb`, 48 GB erreichen `24gb`.
- **Eine NVIDIA-GPU** schaltet mit den Profilen `16gb`/`24gb` die leistungsstärksten Modelle frei: TOPIQ, SigLIP 2, VLM-Tagging, KI-Beschreibungen und -Kritik, Motiverkennung.
- **Keine GPU?** Richten Sie VLM-Tagging, Beschreibungen und Kritik über `vlm_backend` in `scoring_config.json` auf einen entfernten **Ollama**- oder **OpenAI-kompatiblen** Server.
- **Bearbeiten im Viewer** (Bewertungen, Gesichter, Auswahl) benötigt das **Bearbeitungspasswort**. Der Scan-Button benötigt `viewer.features.show_scan_button: true` und Edition-Zugriff (die **Superadmin**-Rolle im Mehrbenutzermodus).

→ Vollständige Anforderungen pro Funktion (GPU, VRAM-Profil, optionale Pakete, Auth): **[Installation › Funktionsanforderungen](docs/de/INSTALLATION.md#funktionsanforderungen)**.

## Ist Facet das Richtige für Sie?

Facet bewertet, ordnet und sortiert eine lokale Fotobibliothek und stellt eine Galerie zum Durchstöbern bereit. Es läuft auf Ihrer eigenen Hardware und hält Fotos aus der Cloud heraus.

**Gut geeignet, wenn Sie:**

- eine große lokale Bibliothek haben und Ihre besten Aufnahmen finden sowie Serienbilder und Beinahe-Duplikate aussortieren möchten;
- eine Bewertung von Qualität, Komposition und Gesichtern wünschen, die Sie auf Ihren eigenen Geschmack abstimmen können (sie lernt aus Ihren A/B-Vergleichen);
- selbstgehostet und privat bevorzugen — kein Cloud-Upload, kein Konto, kein Abonnement;
- bereits in Lightroom, darktable, digiKam oder Immich bearbeiten — Facet schreibt Bewertungen, Labels, Stichwörter, Beschreibungen und Gesichtsregionen in `.xmp`-Sidecars (Originale bleiben unangetastet, außer Sie verlangen das Einbetten: die Galerie-Aktion „Metadaten in Datei schreiben“ oder `--export-sidecars --embed-originals`) und liest Bearbeitungen mit `--import-sidecars` wieder ein. Ein Lightroom-Zusatzmodul `facet.lrplugin` ergänzt einen bidirektionalen Ablauf. Siehe [Interop](docs/de/INTEROP.md).

**Wahrscheinlich nichts für Sie, wenn Sie wünschen:**

- einen schlüsselfertigen, mobilen, cloudgestützten Google-Fotos-Ersatz — wobei der automatische Telefon-Upload in einen überwachten Eingang über WebDAV eingebaut ist (PhotoSync-Rezept in der Dokumentation);
- RAW-Bearbeitung oder -Entwicklung — Facet bewertet und organisiert, es bearbeitet nicht;
- eine Desktop-App ohne jegliche Einrichtung — sie benötigt Python, und die besten Modelle benötigen eine GPU.

**Wie es sich zu anderen Tools verhält**

- Selbstgehostete Bibliotheken (Immich, PhotoPrism) konzentrieren sich auf Organisieren, Suche und Backup. Facet ergänzt sie um Qualitätsbewertung, Ranking und einen Auswahl-Workflow, den sie nicht bieten, hat aber keine mobile App und kein Cloud-Backup (der automatische Telefon-Upload über WebDAV ist eingebaut, und Bewertungen lassen sich mit Immich synchronisieren).
- KI-Auswahl-Apps (Aftershoot, Narrative, FilterPixel) sind ausgefeilte kommerzielle Auswahltools, oft mit integrierter Bearbeitung. Facet ist kostenlos, lokal, umfassender (Galerie, Suche, Gesichter) und seine Bewertung ist anpassbar — aber es ist ein Einzelentwicklerprojekt ohne deren Support oder RAW-Bearbeitung.
- Editoren und Kataloge (Lightroom, darktable, digiKam) entwickeln und verwalten Fotos. Facet ergänzt sie über die oben beschriebene XMP-Metadaten-Interoperabilität, anstatt sie zu ersetzen.

Die Ästhetikwertung ist modellbasiert und ungefähr; rechnen Sie damit, die Gewichte an Ihren Geschmack anzupassen.

## Schnellstart

### Docker (empfohlen)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env      # .env öffnen und PHOTOS_DIR auf Ihren Fotoordner setzen
docker compose up -d      # danach http://localhost:5000 öffnen
```

Haben Sie eine NVIDIA-Karte? Verwenden Sie den Block für ihre Größe in
[Installation](docs/de/INSTALLATION.md#installation-mit-docker) — je eine Zeile für
8-GB-, 16-GB- und 24-GB-Karten.

### Ohne Docker (Linux, macOS)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh                        # erkennt Ihre Hardware, installiert alles
source venv/bin/activate
python facet.py /path/to/your/photos   # Fotos bewerten
python viewer.py                       # Galerie → http://localhost:5000
```

> **macOS:** Der AirPlay-Empfänger des ControlCenters belegt standardmäßig Port 5000. Wenn Sie „Address already in use“ sehen, führen Sie `python viewer.py --port 5001` aus.

Vollständige Anleitung: **[Installation](docs/de/INSTALLATION.md)** — Einrichtung pro
Hardware, Downloads beim ersten Start, und
[Fehlerbehebung bei Abhängigkeiten](docs/de/INSTALLATION.md#abhängigkeitskonflikte-beheben).
Führen Sie `python facet.py --doctor` aus, um GPU-Probleme zu diagnostizieren.

Zum ersten Mal hier? Folgen Sie der Anleitung **[Erste Schritte](docs/de/GETTING_STARTED.md)**: scannen, sichten, trainieren, aussortieren, taggen und exportieren.

## Dokumentation

| Dokument | Beschreibung |
|----------|-------------|
| [Installation](docs/de/INSTALLATION.md) | Anforderungen, GPU-Einrichtung, VRAM-Profile, Abhängigkeiten |
| [Erste Schritte](docs/de/GETTING_STARTED.md) | Walkthrough für den ersten Start: von der Installation bis zu Scan, Sichtung, Training, Aussortieren, Tagging und Export |
| [Befehle](docs/de/COMMANDS.md) | Referenz aller CLI-Befehle |
| [Konfiguration](docs/de/CONFIGURATION.md) | Vollständige Referenz zu `scoring_config.json` |
| [Bewertung](docs/de/SCORING.md) | Kategorien, Gewichte, Leitfaden zur Feinabstimmung |
| [Gesichtserkennung](docs/de/FACE_RECOGNITION.md) | Gesichts-Workflow, Clustering, Personenverwaltung |
| [Viewer](docs/de/VIEWER.md) | Funktionen und Nutzung der Web-Galerie |
| [API](docs/API.md) | Referenz der HTTP-API des Viewers |
| [Interop](docs/de/INTEROP.md) | Bewertungen/Tags mit Lightroom, Capture One, digiKam, darktable austauschen |
| [Immich](docs/de/IMMICH.md) | Bewertungen und Favoriten mit Immich synchronisieren, plus der eingehende Webhook |
| [Neu verknüpfen](docs/de/RELINK.md) | Verschobene Fotos neu verknüpfen |
| [KI-Agenten](docs/de/AGENTS.md) | Einen MCP-fähigen Assistenten die Bibliothek mit einem persönlichen Token durchsuchen lassen |
| [Bereitstellung](docs/de/DEPLOYMENT.md) | Produktivbereitstellung (Synology NAS, Linux, Docker) |
| [Mitwirken](CONTRIBUTING.md) | Entwicklungseinrichtung, Architektur, Code-Stil |

## Lizenz

[MIT](LICENSE)

### Lizenzen

Der Code von Facet steht unter der MIT-Lizenz. Einige Standardmodelle sind **nicht** für die kommerzielle Nutzung lizenziert: pyiqa (TOPIQ, LIQE usw.) und die InsightFace-Gewichte. Setzen Sie `licensing.mode: commercial`, um nur freizügig lizenzierte Ersatzmodelle zu verwenden ([Lizenzierung](docs/de/CONFIGURATION.md#lizenzierung), [Modelle von Drittanbietern](docs/de/THIRD_PARTY_MODELS.md)).
