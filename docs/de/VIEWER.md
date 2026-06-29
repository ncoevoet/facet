# Web-Galerie

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · **Deutsch** · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md)

FastAPI + Angular Single-Page-Application zum Durchsuchen, Filtern und Verwalten von Fotos.

## Inhalt

- [Galerie starten](#galerie-starten) · [Authentifizierung](#authentifizierung) · [Filteroptionen](#filteroptionen) · [Sortierung](#sortierung) · [Galeriefunktionen](#galeriefunktionen)
- [Personenverwaltung](#personenverwaltung) · [Scan auslösen (Superadmin)](#scan-auslösen-superadmin) · [Semantische Suche](#semantische-suche) · [Alben](#alben)
- [KI-Kritik](#ki-kritik) · [KI-Bildbeschreibung](#ki-bildbeschreibung-gpu-16gb24gb-edition) · [Erinnerungen ("Heute vor Jahren")](#erinnerungen-heute-vor-jahren) · [Zeitleisten-Ansicht](#zeitleisten-ansicht) · [Kartenansicht](#kartenansicht) · [Kapseln](#kapseln)
- [Ordner-Ansicht](#ordner-ansicht) · [GPS-Filterdialog](#gps-filterdialog) · [Zusammenführungsvorschläge](#zusammenführungsvorschläge) · [Editor-Export](#editor-export) · [Auswahl](#auswahl) · [Paarweiser Vergleichsmodus](#paarweiser-vergleichsmodus)
- [EXIF-Statistiken](#exif-statistiken) · [Tastenkürzel](#tastenkürzel-galerie) · [Rückgängig](#rückgängig) · [Progressive Web App](#progressive-web-app) · [Mobil](#mobil)
- [Konfiguration](#konfiguration) · [Performance](#performance) · [API-Endpunkte](#api-endpunkte) · [Fehlerbehebung](#fehlerbehebung)

> **Funktionsanforderungen** sind inline gekennzeichnet: `[GPU]` · `[16gb/24gb]` (VRAM-Profil) · `[Edition]` (Bearbeitungspasswort) · `[Superadmin]`. Siehe die [Funktionsmatrix](../README.md#feature-availability--requirements).

## Galerie starten

### Produktion

```bash
python viewer.py
# http://localhost:5000 öffnen
```

Damit werden sowohl die API als auch die vorgebaute Angular-Anwendung auf einem einzigen Port bereitgestellt.

Für höheren Durchsatz im Produktionsmodus ausführen (Uvicorn, kein Auto-Reload). Mit `--workers N` skalieren (Standard 1):

```bash
python viewer.py --production --workers 4
```

### Entwicklung

API-Server und Angular-Dev-Server getrennt ausführen:

```bash
# Terminal 1: API-Server
python viewer.py
# API verfügbar unter http://localhost:5000

# Terminal 2: Angular-Dev-Server mit Hot Reload
cd client && npx ng serve
# http://localhost:4200 öffnen (leitet API-Aufrufe an :5000 weiter)
```

## Authentifizierung

### Einzelbenutzermodus (Standard)

Optionaler Passwortschutz über die Konfiguration:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Wenn gesetzt, müssen sich Benutzer authentifizieren, bevor sie auf die Galerie zugreifen können. Ein optionales `edition_password` gewährt Zugriff auf die Personenverwaltung und den Vergleichsmodus.

### Mehrbenutzermodus

Für Familien-NAS-Szenarien, in denen jedes Mitglied eigene private Fotoverzeichnisse hat. Wird durch Hinzufügen eines `users`-Abschnitts zur `scoring_config.json` aktiviert:

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

Benutzer werden ausschließlich über die CLI angelegt (keine Registrierungs-UI):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Siehe [Konfiguration](CONFIGURATION.md#users) für die vollständige Referenz.

### Rollen

| Rolle | Eigene + geteilte ansehen | Bewerten/Favorisieren | Personen/Gesichter verwalten | Scans auslösen |
|------|:-:|:-:|:-:|:-:|
| `user` | ja | ja | nein | nein |
| `admin` | ja | ja | ja | nein |
| `superadmin` | ja | ja | ja | ja |

### Fotosichtbarkeit

Jeder Benutzer sieht Fotos aus seinen konfigurierten Verzeichnissen sowie aus geteilten Verzeichnissen. Die Sichtbarkeit wird über alle Endpunkte hinweg durchgesetzt: Galerie, Vorschaubilder, Downloads, Statistiken, Filteroptionen und Personenseiten.

### Benutzerspezifische Bewertungen

Im Mehrbenutzermodus werden Sternebewertungen, Favoriten und Ablehnungs-Flags pro Benutzer in der Tabelle `user_preferences` gespeichert. Jeder Benutzer bewertet unabhängig — Alices Favoriten beeinflussen Bobs Ansicht nicht.

So migrieren Sie bestehende Einzelbenutzer-Bewertungen:

```bash
python database.py --migrate-user-preferences --user alice
```

## Filteroptionen

<details><summary>Filter-Seitenleiste — alle Abschnitte aufgeklappt (zum Anzeigen klicken)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Filter-Seitenleiste mit allen aufgeklappten Abschnitten" width="360"></p>
</details>

### Primärfilter

| Filter | Optionen |
|--------|---------|
| **Fototyp** | Beste Auswahl, Porträts, Personen in Szene, Landschaften, Architektur, Natur, Tiere, Kunst & Statuen, Schwarzweiß, Schwaches Licht, Silhouetten, Makro, Astrofotografie, Straßenfotografie, Langzeitbelichtung, Luftaufnahmen & Drohne, Konzerte |
| **Qualitätsstufe** | Gut (6+), Sehr gut (7+), Hervorragend (8+), Beste (9+) |
| **Kamera & Objektiv** | Filterung nach Ausrüstung |
| **Person** | Nach erkannter Person filtern |
| **Kategorie** | Nach Fotokategorie filtern |

### Erweiterte Filter

| Kategorie | Filter |
|----------|---------|
| **Datum** | Start- und Enddatum |
| **Wertungen** | Gesamtwertung, Ästhetik, TOPIQ-Wert, Qualitätswert |
| **Erweiterte Qualität** | Ästhetik IAA (künstlerischer Wert), Gesichtsqualität IQA, LIQE-Wert |
| **Gesichtsmetriken** | Gesichtsqualität, Augenschärfe, Gesichtsschärfe, Gesichtsanteil, Gesichtskonfidenz, Gesichteranzahl |
| **Komposition** | Kompositionswert, Kraftpunkte, Führungslinien, Freistellung, Kompositionsmuster |
| **Motiverkennung** | Motivschärfe, Motivhervorhebung, Motivplatzierung, Hintergrundtrennung |
| **Technik** | Schärfe, Kontrast, Dynamikumfang, Rauschniveau |
| **Farbe** | Farbwert, Sättigung, Helligkeit, Histogrammbreite; Farbtemperatur (warm/kühl/neutral) und Farbtongruppe (erfordert `--recompute-colors`) |
| **Belichtung** | Belichtungswert |
| **Benutzerbewertungen** | Sternebewertung |
| **Kameraeinstellungen** | ISO, Blende (F-Stop-Bereichsregler), Brennweite (Bereichsregler) |
| **Inhalt** | Tags, Monochrom-Umschalter |

### Kompositionsmuster

Nach von SAMP-Net erkannten Mustern filtern:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Sortierung

Sortierbare Spalten nach Kategorie gruppiert (aus `viewer.sort_options`):

| Gruppe | Spalten |
|-------|---------|
| **Allgemein** | Gesamtwertung, Ästhetik, Qualitätswert, Aufnahmedatum, Sternebewertung, Ästhetik (IAA), LIQE-Wert |
| **Gesichtsmetriken** | Gesichtsqualität, Gesichtsqualität (IQA), Augenschärfe, Gesichtsschärfe, Gesichtsanteil, Gesichteranzahl |
| **Technik** | Techn. Schärfe, Kontrast, Rauschniveau |
| **Farbe** | Farbwert, Sättigung |
| **Belichtung** | Belichtungswert, Mittlere Helligkeit, Histogrammbreite, Dynamikumfang |
| **Komposition** | Kompositionswert, Kraftpunktwert, Führungslinien, Freistellungsbonus, Kompositionsmuster |
| **Motiverkennung** | Motivschärfe, Motivhervorhebung, Motivplatzierung, Hintergrundtrennung |

### Mein Geschmack

Eine vollwertige Sortieroption, gestützt auf den `learned_score` des persönlichen Rankers (umbenannt von „Für Sie ausgewählt"). Sie ordnet Fotos danach, was der Ranker aus Ihren A/B-Vergleichen, Bewertungen und Auswahlentscheidungen gelernt hat. Ein Konfidenzabzeichen neben der Sortierung zeigt die gelernte Abdeckung (% der Fotos mit gelerntem Wert) sowie die Held-out-Genauigkeit des Rankers an, sodass Sie einschätzen können, wie sehr Sie der Reihenfolge vertrauen können. Trainieren oder aktualisieren Sie den Ranker mit `python facet.py --train-ranker`.

Gesteuert über `viewer.features.show_my_taste` (Standard: `true`). Der Ranker-Status wird über `GET /api/ranker/status` bereitgestellt.

## Galeriefunktionen

### Fotokarten

- Vorschaubild mit Wertungsabzeichen
- Anklickbare Tags zum schnellen Filtern
- Personen-Avatare für erkannte Gesichter
- Kategorieabzeichen

### Mehrfachauswahl & Sammelaktionen

- Fotos zum Auswählen anklicken, Umschalt+Klick für Bereichsauswahl
- Eine Aktionsleiste erscheint mit Auswahlanzahl und verfügbaren Aktionen
- **Favorit** — Alle ausgewählten als Favorit markieren (hebt Ablehnung auf)
- **Ablehnen** — Alle ausgewählten als abgelehnt markieren (hebt Favorit und Bewertung auf)
- **Bewerten** — Sternebewertung (1–5) für alle ausgewählten setzen oder Bewertung löschen
- **Zu Album hinzufügen** — Auswahl zu einem bestehenden oder neuen Album hinzufügen
- **Dateinamen kopieren** — Ausgewählte Dateinamen in die Zwischenablage kopieren
- **Exportieren** — XMP-Sidecars (Bewertung/Favorit/Ablehnung) neben den ausgewählten Dateien schreiben (siehe [Editor-Export](#editor-export))
- **Herunterladen** — Ausgewählte Fotos herunterladen
- Auswahl mit Escape oder der Schaltfläche „Löschen" aufheben

Sammelaktionen erfordern den Bearbeitungsmodus. Doppelklicken Sie ein beliebiges Foto, um es direkt herunterzuladen.

### Anzeigeoptionen

- **Layout-Modus** – Wechseln zwischen **Raster** (einheitliche Karten) und **Mosaik** (justierte Zeilen, die Seitenverhältnisse beibehalten). Mosaik ist nur auf dem Desktop verfügbar; mobil wird stets das Raster verwendet.
- **Vorschaubildgröße** – Regler zum Anpassen der Karten-/Zeilenhöhe (120–400px, in localStorage gespeichert)
- **Details ausblenden** – Foto-Metadaten auf Karten ausblenden (nur im Rastermodus)
- **Tooltip ausblenden** – Den Hover-Tooltip deaktivieren, der auf dem Desktop Fotodetails anzeigt
- **Blinzler ausblenden** – Fotos mit erkanntem Blinzeln herausfiltern
- **Beste aus Serie** – Nur das am höchsten bewertete Foto jedes Serienbilds anzeigen
- **Endloses Scrollen** – Fotos werden beim Scrollen geladen
- **Schnelles Scrollen (virtualisiert)** – Zeilenfenster-Rendering: Nur Zeilen nahe dem
  Sichtbereich befinden sich im DOM, sodass tiefes Scrollen durch zehntausende Fotos
  reaktionsschnell bleibt. Standardmäßig aktiviert; im Anzeige-Abschnitt der Filter-
  Seitenleiste deaktivieren, falls Layoutprobleme auftreten (der Rastermodus mit
  angezeigten Details verwendet stets das vollständige Rendering, da die Zeilenhöhen
  dort nicht deterministisch sind). In localStorage gespeichert
  (`facet_virtual_scroll`).

### Ähnliche Fotos

Klicken Sie bei einem beliebigen Foto auf die Schaltfläche „Ähnliche", um einen Ähnlichkeitsmodus zu wählen:

- **Visuell** (Standard) — pHash-Hamming-Distanz (70%) + CLIP/SigLIP-Kosinusähnlichkeit (30%). Greift auf CLIP allein zurück, wenn kein pHash verfügbar ist.
- **Farbe** — Histogrammschnittmenge (70%) + Sättigungsdistanz (10%) + Helligkeitsdistanz (10%) + Monochrom-Bonus (10%). Vorfilterung nach Monochrom-Flag und Sättigungsbereich.
- **Person** — Findet Fotos mit derselben Person/denselben Personen. Verwendet `person_id`, wenn verfügbar (schnell), andernfalls Rückgriff auf die Kosinusähnlichkeit der Gesichts-Embeddings.

Verwenden Sie den **Ähnlichkeitsschwellen-Regler** (0–90%), um zu steuern, wie streng der Abgleich ist (im Personenmodus nicht angezeigt). Das Panel unterstützt endloses Scrollen für große Ergebnismengen.

### Filter-Chips

Aktive Filter werden als entfernbare Chips mit Zählern oben in der Galerie angezeigt.

## Personenverwaltung

> Das Durchsuchen von Personen steht allen Betrachtern offen; Umbenennen, Zusammenführen, Avatar-Änderungen und Gesichtszuweisung erfordern `[Edition]`.

### Personenfilter

Das Dropdown zeigt Personen mit Gesichts-Vorschaubildern. Zum Filtern der Galerie anklicken.

### Personengalerie

Klicken Sie auf den Personennamen, um alle ihre Fotos unter `/person/<id>` anzuzeigen.

### Seite „Personen verwalten"

Zugriff über die Header-Schaltfläche oder `/persons`:

| Aktion | Vorgehen |
|--------|--------|
| **Zusammenführen** | Quellperson auswählen, Ziel anklicken, bestätigen |
| **Löschen** | Auf die Löschen-Schaltfläche der Personenkarte klicken |
| **Umbenennen** | Auf den Personennamen klicken, um ihn inline zu bearbeiten |
| **Aufteilen** | Die Gesichter einer Person öffnen, eine Teilmenge auswählen und in eine neue Person aufteilen |
| **Ausblenden** | Ein Cluster aus der Personenliste, den Filtern und den Zusammenführungsvorschlägen ausblenden (umkehrbar) |

## Scan auslösen (Superadmin)

Wenn `viewer.features.show_scan_button` auf `true` steht und der Benutzer die Rolle `superadmin` hat, erscheint im leeren Galerie-Zustand eine Schaltfläche **Fotos scannen, um loszulegen**. Sie wird in `scoring_config.json` auf **`false`** ausgeliefert (Superadmin-Opt-in). Die Schaltfläche öffnet den Scan-Starter-Dialog (`ScanLauncherComponent`).

- Ein Verzeichnis aus der Liste des Starters auswählen und den Scan direkt in der App starten
- Der Starter überträgt den Fortschritt live (SSE mit automatischem Polling-Rückgriff) in einen `mat-progress-bar`, der vom strukturierten `progress`-Feld gesteuert wird, plus einen Auszug der Ausgabezeilen, und aktualisiert die Galerie, sobald der Scan abgeschlossen ist
- Der Scan läuft als Hintergrund-Unterprozess (`facet.py`); nur ein Scan gleichzeitig (globale Sperre)
- Die Verzeichnisauswahl stammt aus `get_all_scan_directories()`, das die `directories` jedes Benutzers, freigegebene Verzeichnisse, `path_mapping`-Ziele und die eigenständige `viewer.scan_directories`-Liste vereint — befüllen Sie letztere (z. B. `/data/photos`), damit Einzelbenutzer-/Docker-Installationen ein auswählbares Ziel haben

Dies ist nützlich, wenn die Galerie auf derselben Maschine läuft, die GPU-Zugriff für die Bewertung hat.

## Semantische Suche

Hybride Suche, die CLIP/SigLIP-Embedding-Ähnlichkeit (70%) mit FTS5-BM25-Textabgleich auf Bildbeschreibungen und Tags (30%) kombiniert. Geben Sie eine Anfrage wie „Sonnenuntergang über Bergen" oder „Kind spielt im Schnee" ein, und die Galerie liefert passende Fotos, sortiert nach kombinierter Wertung.

- Erfordert gespeicherte `clip_embedding`-Daten (während der Bewertung berechnet)
- Verwendet sqlite-vec für KNN-Vektorsuche, sofern installiert, andernfalls Rückgriff auf In-Memory-NumPy
- FTS5-Textsuche auf KI-Bildbeschreibungen/Tags bietet zusätzlichen Schlüsselwortabgleich (zum Aktivieren `database.py --rebuild-fts` ausführen)
- Verwendet dasselbe Embedding-Modell wie das aktive VRAM-Profil (SigLIP 2 für 16gb/24gb, CLIP ViT-L-14 für legacy/8gb)
- `scope=text` beschränkt die Anfrage auf literale FTS5-Treffer im OCR-/Beschreibungstext und überspringt die Embedding-Suche
- Gesteuert über `viewer.features.show_semantic_search` (Standard: `true`)

## Alben

Organisieren Sie Fotos in benannten Alben. Zugriff über die Route `/albums`.

### Manuelle Alben

Erstellen Sie Alben und fügen Sie Fotos aus der Galerie per Mehrfachauswahl hinzu. Alben unterstützen:
- Name und Beschreibung
- Benutzerdefiniertes Titelbild
- Benutzerdefinierte Sortierung
- Albuminhalte unter `/album/:albumId` durchsuchen

### Intelligente Alben

Speichern Sie eine Kombination von Filtern (Kamera, Tag, Person, Zeitraum, Wertungsschwellen usw.) als intelligentes Album. Intelligente Alben aktualisieren sich dynamisch, sobald neue Fotos den gespeicherten Filterkriterien entsprechen. Die Filterkombination wird als JSON in `smart_filter_json` gespeichert.

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Gesteuert über `viewer.features.show_albums` (Standard: `true`).

### Fotofreigabe

Teilen Sie Alben mit externen Nutzern über tokenisierte Links. Für die Ansicht geteilter Alben ist keine Authentifizierung erforderlich.

| Aktion | Vorgehen |
|--------|--------|
| **Teilen** | Album öffnen, auf „Teilen" klicken, um einen teilbaren Link zu erzeugen |
| **Widerrufen** | Auf „Freigabe aufheben" klicken, um das Freigabe-Token ungültig zu machen |
| **Ansehen** | Empfänger öffnen den Link, um das geteilte Album unter `/shared/album/:id` zu durchsuchen |

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

## KI-Kritik

Schlüsselt die Wertungen eines Fotos in Stärken, Schwächen und Vorschläge auf.

### Regelbasierte Kritik

Auf allen VRAM-Profilen verfügbar. Analysiert gespeicherte Metriken (Ästhetik, Komposition, Schärfe, Gesichtsqualität usw.) und erzeugt eine strukturierte Erläuterung der Wertung.

### VLM-Kritik `[GPU]` `[16gb/24gb]`

Verwendet das konfigurierte VLM (Qwen3.5-2B oder Qwen3.5-4B) für eine kontextbewusste Kritik. Erfordert das 16gb- oder 24gb-VRAM-Profil und `viewer.features.show_vlm_critique: true`.

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Gesteuert über `viewer.features.show_critique` (Standard: `true`) und `viewer.features.show_vlm_critique` (Standard: `true`).

**Visuelles „Warum diese Wertung"-Overlay.** Wenn `viewer.features.show_saliency_overlay` auf `true` steht (Standard), erhält der Kritik-Dialog einen **Overlay anzeigen**-Umschalter: Er zeichnet die BiRefNet-Saliency-Karte als durchscheinende Heatmap über das Foto (bei Bedarf aus dem gespeicherten Vorschaubild neu berechnet — `GET /api/saliency_overlay`), plus weiche Boxen pro Gesicht und Augenmarkierungen, die aus gespeicherten Landmarken rekonstruiert werden (`GET /api/photo/face_markers`). Boxen sind grün, wenn die Augen offen sind, und bernsteinfarben bei einem Blinzeln. Die Heatmap ist illustrativ (Vorschaubild-Auflösung), nicht pixelgenau; der Umschalter blendet sich auf Profilen aus, bei denen keine Saliency-Maske erzeugt werden kann.

## KI-Bildbeschreibung `[GPU]` `[16gb/24gb]` `[Edition]`

Erhalten Sie eine KI-generierte Bildbeschreibung in natürlicher Sprache für jedes Foto. Beschreibungen werden bei der ersten Anfrage generiert und in der Datenbankspalte `caption` zwischengespeichert. Beschreibungen können im Bearbeitungsmodus über die Fotodetailseite manuell bearbeitet werden. (Die *Übersetzung* von Beschreibungen läuft auf der CPU — siehe unten.)

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Auch über die CLI für Massengenerierung und Übersetzung verfügbar:

```bash
python facet.py --generate-captions      # Bildbeschreibungen für alle Fotos ohne Beschreibung generieren
python facet.py --translate-captions     # Bildbeschreibungen in die konfigurierte Zielsprache übersetzen
```

Die Übersetzung von Beschreibungen verwendet MarianMT (CPU, keine GPU erforderlich). Konfigurieren Sie die Zielsprache in `scoring_config.json` unter `translation.target_language` (Standard: `"fr"`). Unterstützte Sprachen: Französisch, Deutsch, Spanisch, Italienisch.

Gesteuert über `viewer.features.show_captions` (Standard: `true`). Erfordert das 16gb- oder 24gb-VRAM-Profil für VLM-basierte Bildbeschreibungen.

## Erinnerungen ("Heute vor Jahren")

Durchsuchen Sie Fotos, die am selben Kalendertag in früheren Jahren aufgenommen wurden. Ein Erinnerungsdialog zeigt eine Jahr-für-Jahr-Rückschau passender Fotos.

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Gesteuert über `viewer.features.show_memories` (Standard: `true`).

## Häufige Arbeitsabläufe

- **Einen Urlaub aussortieren** — Kapseln öffnen → nach der automatisch generierten `journey`-Kapsel für die Reisedaten suchen. Jede Kapsel bietet eine Aktion „Als Album speichern".
- **Eine Tag-für-Tag-Durchsicht machen** — Zeitleiste öffnen → nach Gesamtwertung sortieren → das Jahr durchgehen. Die besten Aufnahmen steigen zuerst nach oben, wenn `hide_bursts` und `hide_duplicates` aktiviert sind (Standard: an).
- **Ausgeblendetes anzeigen** — Die Galerie blendet Blinzler / Nicht-Leitfotos von Serienbildern / Nicht-Leitfotos von Duplikaten standardmäßig aus. Wenn mindestens einer dieser Filter aktiv ist und Zeilen ausschließen würde, erscheint über dem Raster ein Banner „N Fotos durch aktuelle Filter ausgeblendet · Alle anzeigen".

## Zeitleisten-Ansicht

Chronologischer Foto-Browser mit datumsbasierter Navigation. Scrollen Sie durch nach Datum organisierte Fotos mit einer Seitenleiste, die verfügbare Jahre und Monate anzeigt.

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Zugriff über die Route `/timeline`. Gesteuert über `viewer.features.show_timeline` (Standard: `true`).

## Kartenansicht

Zeigt Fotos auf einer interaktiven Karte basierend auf den aus EXIF-Daten extrahierten GPS-Koordinaten an. Verwendet Leaflet zur Kartendarstellung mit Clustering bei verschiedenen Zoomstufen.

### Einrichtung

GPS-Koordinaten aus vorhandenen Fotos extrahieren:

```bash
python facet.py --extract-gps    # GPS-Breite/-Länge aus EXIF in die Datenbank extrahieren
```

GPS-Koordinaten werden für neue Fotos auch automatisch während der Bewertung extrahiert.

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Zugriff über die Route `/map`. Gesteuert über `viewer.features.show_map` (Standard: `true`).

## Kapseln

Kuratierte Foto-Diaschows (Slideshows), nach Thema gruppiert. Zugriff über die Route `/capsules`.

### Kapseltypen

Kapseln werden mit mehreren Algorithmen automatisch aus Ihrer Bibliothek generiert:

- **Reise** — über GPS-Clustering erkannte Reisen, mit umgekehrt geocodierten Zielnamen („Reise nach Rom — März 2025")
- **Momente mit [Person]** — beste Fotos jeder erkannten Person
- **Saisonale Palette** — nach Saison + Jahr gruppierte Fotos
- **Goldene Sammlung** — Top 1% nach Gesamtwertung
- **Farbgeschichte** — visuell ähnliche Gruppen über CLIP-Embedding-Clustering
- **Diese Woche, vor Jahren** — erweitertes „Heute vor Jahren" über ±3 Tage
- **Standort** — georeferenzierte Foto-Cluster mit Ortsnamen
- **Favoriten** — favorisierte Fotos nach Jahr und Saison gruppiert
- **Dimensionsbasiert** — automatisch generiert aus Kamera, Objektiv, Kategorie, Kompositionsmuster, Brennweitenbereich, Tageszeit, Sternebewertung und dimensionsübergreifenden Kombinationen

### Slideshow

Klicken Sie auf eine beliebige Kapselkarte, um eine Slideshow zu starten. Funktionen:
- **Themenbezogene Übergänge** — Slide (Reisen), Zoom (Porträts), Ken Burns (golden/saisonal), Crossfade (Standard)
- **Automatische Verkettung** — wenn eine Kapsel endet, zeigt eine Übergangskarte die nächste Kapsel an, bevor es weitergeht
- **Mischen & Fortsetzen** — Fotos werden für Abwechslung gemischt; die Fortsetzungsposition wird pro Kapsel verfolgt
- **Adaptive Gruppierung** — Hochformatfotos werden basierend auf dem Seitenverhältnis des Sichtbereichs nebeneinander gruppiert
- **Als Album speichern** — jede Kapsel als dauerhaftes Album speichern

### Aktualität

Kapseln rotieren nach einem konfigurierbaren Zeitplan (Standard: 24 Stunden). Titelbilder und gesetzte Entdeckungs-Kapseln richten sich nach demselben Rotationszeitraum aus. Die Schaltfläche „Regenerieren" im Header erzwingt eine sofortige Aktualisierung.

### Umgekehrte Geocodierung

Standort- und Reisekapseln zeigen Ortsnamen (z.B. „Paris, Frankreich") statt Koordinaten an. Dies verwendet Offline-Geocoding über das Paket `reverse_geocoder` — keine API-Aufrufe erforderlich. Ergebnisse werden in der Datenbank zwischengespeichert.

Installation: `pip install reverse_geocoder`

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

### Konfiguration

Siehe [Konfiguration — Kapseln](CONFIGURATION.md#capsules) für alle Einstellungen.

## Ordner-Ansicht

Durchsuchen Sie Ihre Fotobibliothek nach Verzeichnisstruktur. Zugriff über die Route `/folders`.

- Brotkrümel-Navigation, um im Verzeichnisbaum nach oben zu wechseln
- Jeder Ordner zeigt ein Titelbild (das am höchsten bewertete Bild in diesem Verzeichnis)
- Klicken Sie auf einen Ordner, um in ihn abzusteigen, oder auf ein Foto, um es in der Galerie zu öffnen
- Berücksichtigt im Mehrbenutzermodus die Verzeichnissichtbarkeit der Benutzer

## GPS-Filterdialog

Filtern Sie Fotos nach geografischem Standort mithilfe eines interaktiven Karten-Pickers:

- Auf die Standortfilter-Schaltfläche klicken, um den Kartendialog zu öffnen
- Auf die Karte klicken oder ziehen, um einen Mittelpunkt festzulegen
- Den Radiusregler anpassen, um den Suchbereich zu steuern
- Fotos innerhalb des gewählten Radius werden in die Galerie gefiltert
- Erfordert GPS-Koordinaten (`--extract-gps` ausführen, wenn Fotos EXIF-GPS-Daten haben)

## Zusammenführungsvorschläge

Finden Sie Personencluster, die dieselbe Person sein könnten. Zugriff über `/merge-suggestions` oder über die Seite „Personen verwalten".

- **Ähnlichkeitsschwellen-Regler** — wie ähnlich zwei Personen aussehen müssen, um vorgeschlagen zu werden (niedriger = mehr Vorschläge, höher = weniger)
- **Zusammenführen** — einen Vorschlag annehmen, um die beiden Personen zusammenzuführen
- **Sammelzusammenführung** — mehrere Vorschläge auswählen und auf einmal zusammenführen
- Verworfene Vorschläge werden gemerkt und nicht erneut vorgeschlagen
- Auch über die CLI verfügbar: `python facet.py --suggest-person-merges`

## Editor-Export

Schreiben Sie Ihre Bewertungen, Favoriten und Ablehnungen als XMP-Sidecars auf die Festplatte, damit externe Editoren (darktable, Lightroom) sie übernehmen. Erfordert den Bearbeitungsmodus.

- **Aus der Galerie** — Fotos auswählen, dann schreibt **Aktionen → Exportieren** ein Sidecar neben jede Datei.
- **Aus einem Album** („Korb") — das gesamte Album als Sidecars exportieren oder die Dateien in ein Zielverzeichnis kopieren/verlinken.
- **Metadaten in Datei schreiben** — die Aktion „Metadaten in Datei schreiben" in der Fotodetailansicht bettet die Bewertung/Schlüsselwörter zusätzlich zum Sidecar direkt in die Originaldatei ein (JPEG/HEIC/TIFF/PNG/DNG über exiftool), sodass das gesamte Foto-Ökosystem sie sieht. Proprietäre RAW-Originale werden niemals verändert. Gesteuert über `viewer.features.show_embed_metadata` (Standard: `true`).

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

## Auswahl

Die Auswahl-Seite (`/culling`, Bearbeitungsmodus) gruppiert nahezu identische Aufnahmen, sodass Sie die beste jeder Gruppe behalten und den Rest ablehnen können. Zwei Gruppenquellen:

- **Serienbild** — zeitlich dicht aufeinanderfolgend aufgenommene Fotos (aus der Serienbilderkennung).
- **Ähnlich** — Fotos, die sich ähneln, unabhängig vom Aufnahmezeitpunkt, gruppiert nach CLIP/SigLIP-Embedding-Ähnlichkeit. Ein Schwellenwertregler steuert, wie streng die Gruppierung ist.

Wählen Sie für jede Gruppe die Behaltefoto(s); das Bestätigen lehnt den Rest ab. Bestätigungen werden verzögert ausgeführt und können rückgängig gemacht werden (siehe [Rückgängig](#rückgängig)).

**Eingegrenzte Auswahl.** Die Dunkelkammer kann über Query-Parameter auf eine Teilmenge eingegrenzt werden: `?album=<id>` beschränkt sie auf ein Album, und `?from=&to=` (EXIF-Aufnahmezeitfenster, die Grundlage von **Diese Szene aussortieren**) beschränkt sie auf eine Szene. Ein Banner zeigt den aktiven Geltungsbereich mit einer **Szene verlassen**-Steuerung; das Abrufen der Serienbildmitglieder bleibt albumbezogen, ignoriert aber das Zeitfenster, sodass ein Serienbild, das über die Szenengrenze hinausreicht, weiterhin alle seine Frames anzeigt.

**„Mein Geschmack"-Chip.** Jede Bestätigung erfasst `source='culling'`-Vergleichszeilen, die den persönlichen Ranker trainieren, sodass der Header einen kleinen Chip „Mein Geschmack · N Vergleiche" zeigt, der sich nach jeder Entscheidung aktualisiert — die KI lernt Ihren Blick, während Sie aussortieren (`GET /api/ranker/status`).

### Lupe / Z-Tasten-Zoom

Drücken Sie **`Z`** in der Einzelansicht-Lightbox, um eine Lupe im Photo-Mechanic-Stil umzuschalten (Einpassen ↔ 2×; Mausrad/`+`/`-`-Zoom bis 800%). Jenseits der Einpassen-Skalierung tauscht der Bereich sein Vorschaubild gegen die vollauflösende `/image`-Quelle, sodass Sie die kritische Schärfe an echten Pixeln beurteilen, ohne die Ansicht zu verlassen. Auf dem Kontaktstreifen der Szenen schaltet `Z` eine Hover-Lupe um, die dem Cursor über einer Kachel folgt (aus dem vollauflösenden Bild gespeist), mit einem einstellbaren Zoom-Regler. Gespeicherte Vorschaubilder sind auf 640px begrenzt, daher ist die Lupe der Weg, um darüber hinaus pixelgenau zu prüfen.

### Abzeichen pro Gesicht

In der Lightbox der Serienbild-/Ähnlichkeitsauswahl trägt jedes erkannte Gesicht seine eigenen Abzeichen — Augen offen/geschlossen, schwacher Ausdruck und Erkennungskonfidenz — statt einer einzigen Blinzel-Markierung auf Fotoebene. Das erleichtert die Auswahl bei Gruppenaufnahmen: Sie sehen auf einen Blick, welches Gesicht geschlossene Augen oder einen schwachen Ausdruck hat. Die Abzeichen werden für eine ganze Gruppe in einem einzigen Batch-Aufruf abgerufen (`POST /api/culling-group/faces`).

**Synchronisierter Vergleich (2-fach / 4-fach).** Der Lightbox-Header hat die Schaltflächen Einzeln / Vergleich 2 / Vergleich 4. Im Vergleichsmodus teilen sich die Bereiche eine gemeinsame Schwenk-/Zoom-Transformation, sodass Mausrad-Zoom oder Ziehen-Schwenken in einem beliebigen Bereich alle auf denselben Bildausschnitt bewegt — die Art, das schärfste Bild einer Serie zu wählen, indem man tatsächlich die Pixel begutachtet. Doppelklick schaltet zwischen Einpassen ↔ Zoom um; jenseits der Einpassen-Skalierung tauscht jeder Bereich faul sein 1920px-Vorschaubild gegen die vollauflösende `/image`-Quelle, damit der Blick gestochen scharf ist. Keine Backend-Änderung — beide Bildrouten existieren bereits. (Touch-Pinch ist noch nicht verdrahtet; verwenden Sie am Desktop das Mausrad.)

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

## Szenen-Ansicht

Gruppieren Sie Serienbild-Leitfotos zu chronologischen „Szenen", sodass Sie eine ganze Aufnahmesession in Erzählreihenfolge auswählen können. Fotos werden anhand von Lücken in der Aufnahmezeit in Szenen unterteilt (eine neue Szene beginnt, wenn zwischen zwei aufeinanderfolgenden Aufnahmen mehr als `scenes.gap_minutes` vergehen, bei spärlichen Aufnahmen adaptiv erweitert), und jeder übermäßig lange Lauf wird unterteilt, sodass ein durchgehend aufgenommenes Ereignis nie zu einer einzigen riesigen Szene zusammenfällt. Jede Szene hat eine primäre Schaltfläche **Diese Szene aussortieren**, die die vollständige Auswahl-Dunkelkammer eingegrenzt auf nur diese Szene öffnet (Serienbilderkennung, Blinzel-Markierungen, Qualitätswertungen, Gesichts-Nahaufnahmen, Lupe), plus einen Streifen für **Schnelles Ablehnen**. Zugriff über die Route `/scenes` (Navigations-Symbol „theaters"); auch pro Album über das Alben-Raster erreichbar.

Wenn narrative Momente berechnet werden (siehe unten), wird jede Szene zusätzlich nach ihrem dominanten Moment betitelt, und `scenes.split_on_moment_change` kann einen langen Lauf dort unterteilen, wo sich der Moment ändert.

## Narrative Momente

Facet kennzeichnet jedes Foto mit dem „Moment" des Ereignisses, das es darstellt — bei einer Hochzeit: Vorbereitung (Braut/Bräutigam), Zeremonieeinzug, Eheversprechen, Ringtausch, erster Kuss, Auszug, Familienfotos, Paar-Porträts, Cocktailstunde, Empfangsdetails, Dinner/Toasts, Tortenanschnitt, erster Tanz, Party, Verabschiedung — oder `other`. Weder Narrative Select noch AfterShoot tun dies; sie gruppieren nur nach Zeit und visueller Ähnlichkeit.

Es ist **Zero-Shot und vollständig lokal**: Das gespeicherte CLIP/SigLIP-Embedding wird per Kosinusähnlichkeit mit gemittelten Text-Prompts für jeden Moment verglichen (L0), durch kleine Gesichts-/Tag-Prioren angepasst (L1) und dann **entlang der Zeitleiste geglättet** mit einem Viterbi-Durchgang, sodass ein isolierter Fehler in den umgebenden Lauf zurückgezogen wird (L2). Ein optionaler VLM-Stichentscheider (L3, 16gb/24gb) kann Frames mit niedriger Konfidenz neu beurteilen. Da es sich nur um ein Skalarprodukt über bereits in der Datenbank befindlichen Embeddings handelt — keine Bilddekodierung, kein Modelldurchlauf pro Bild — ist es günstig und **läuft automatisch am Ende jedes Scans**; die gesamte Bibliothek mit `python facet.py --recompute-moments` erneut verarbeiten.

Momente erscheinen als Szenentitel und als Galerie-Filter (`GET /api/photos?narrative_moment=vows`, Optionen aus `GET /api/filter_options/narrative_moments`). Das Vokabular ist pro Ereignistyp konfigurationsgesteuert — siehe [Konfiguration — Narrative Momente](CONFIGURATION.md#narrative-moments), um Prompts/Schwellen abzustimmen oder ein Nicht-Hochzeits-Genre hinzuzufügen.

- Jede Szene zeigt ihre Leitfotos in Aufnahmereihenfolge
- Tippen Sie Fotos an, um sie für die Auswahl zu markieren; das Bestätigen lehnt sie ab und speist den persönlichen Ranker
- Szenen, die kleiner als `scenes.min_size` sind, werden weggelassen; es werden höchstens `scenes.max_photos` Fotos geladen

API: siehe den Abschnitt [API-Endpunkte](#api-endpunkte) weiter unten.

Gesteuert über `viewer.features.show_scenes` (Standard: `true`). Siehe [Konfiguration — Szenen](CONFIGURATION.md#scenes) für `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` und `adaptive_k`.

## Paarweiser Vergleichsmodus

Bewerten Sie Fotos, indem Sie sie paarweise beurteilen. Die gesammelten Stimmen fließen in die Gewichtungsabstimmung ein. Zugriff über die Route `/compare` (Schaltfläche „Vergleichen" im Header). Erfordert ein nicht leeres `edition_password` (Einzelbenutzer) oder die Rolle `admin`/`superadmin` (Mehrbenutzer).

Die Seite hat vier Tabs:

### Tab „A/B-Vergleich"

Fotopaare nebeneinander. Wählen Sie einen Gewinner, markieren Sie ein Unentschieden oder überspringen Sie. Ein Fortschrittsbalken zählt die Stimmen in Richtung 50, mit laufenden Zählern für A-Siege/B-Siege/Unentschieden. Ein Kategoriefilter begrenzt die Sitzung, und ein Dropdown für die Auswahlstrategie steuert, wie Paare gewählt werden.

| Strategie | Beschreibung |
|----------|-------------|
| `uncertainty` | Fotos mit ähnlichen Wertungen (am aufschlussreichsten) |
| `boundary` | Wertungsbereich 6–8 (mehrdeutige Zone) |
| `active` | Fotos mit den wenigsten Vergleichen (sichert Abdeckung) |
| `random` | Zufällige Paare (Basislinie) |

**Tastenkürzel:**

| Taste | Aktion |
|-----|--------|
| `A` | Linkes Foto gewinnt |
| `B` | Rechtes Foto gewinnt |
| `T` | Unentschieden |
| `S` | Paar überspringen |
| `Escape` | Modal zur Kategorieüberschreibung schließen |

### Tab „Gewichtsvorschläge"

Zeigt die aus Vergleichen gelernten Gewichte gegenüber den aktuellen Gewichten nebeneinander an, mit Modellgenauigkeit vorher/nachher. Die aktuellen Top-10-Fotos und die nach der Neuberechnung vorhergesagten Top 10 werden in benachbarten Spalten als Vorschau gezeigt. **Anwenden** schreibt die vorgeschlagenen Gewichte; **Neu berechnen** bewertet die Kategorie neu, um sie anzuwenden (beides erfordert den Bearbeitungsmodus).

### Tab „Gewichte"

Manueller Gewichtseditor: ein Regler pro Metrik für die ausgewählte Kategorie mit einer Live-Wertungsvorschau. **Speichern** schreibt in `scoring_config.json` (mit einer Sicherung); **Wertungen neu berechnen** wendet sie an; **Zurücksetzen** lädt die gespeicherten Gewichte erneut.

### Tab „Snapshots"

Speichern Sie die aktuellen Gewichte als benannten Snapshot und stellen Sie jeden früheren Snapshot wieder her.

### Kategorieüberschreibung

Um die Kategorie eines Fotos aus der Vergleichsansicht neu zuzuweisen: Bearbeiten Sie das Kategorieabzeichen, wählen Sie eine Zielkategorie, führen Sie „Filterkonflikte analysieren" aus, um zu sehen, welche Filter es ausschließen, und wenden Sie dann die Überschreibung an.

## EXIF-Statistiken

Die Statistik-Seite (`/stats`) bietet Auswertungen über 5 Tabs. Verwenden Sie die Selektoren für **Kategorie** und **Zeitraum** in der Symbolleiste, um alle Diagramme auf eine bestimmte Teilmenge Ihrer Bibliothek zu filtern.

### Tabs

| Tab | Beschreibung |
|-----|-------------|
| **Ausrüstung** | Kameragehäuse, Objektive und Kombinationen (jeweils Top 20) |
| **Aufnahmeeinstellungen** | Verteilungen von ISO, Blende, Brennweite, Verschlusszeit |
| **Zeitverlauf** | Fotos im Zeitverlauf |
| **Kategorien** | Kategorieauswertungen, Gewichtsverwaltung und Wertungskorrelationen |
| **Korrelationen** | Benutzerdefinierte X/Y-Metrik-Korrelationsdiagramme mit Gruppierung |

### Tab „Kategorien"

Vier Untertabs:

| Untertab | Beschreibung |
|---------|-------------|
| **Aufschlüsselung** | Fotoanzahl pro Kategorie, Durchschnittswertungen, Wertungsverteilungs-Histogramme |
| **Gewichte** | Radardiagramm-Vergleich (bis zu 5 Kategorien), Gewichtungs-Heatmap und Gewichtseditor (Bearbeitungsmodus) |
| **Korrelationen** | Pearson-Korrelations-Heatmap, die zeigt, wie jede Dimension die Gesamtwertung beeinflusst, mit Klick-für-Details-Ansicht |
| **Überschneidungen** | Filterüberschneidungsanalyse, die zeigt, welche Kategorien sich passende Fotos teilen |

Jedes Diagramm hat eine umschaltbare `?`-Hilfeschaltfläche, die erklärt, wie es zu lesen ist. Ein globaler Hilfe-Umschalter in der Untertab-Leiste zeigt Erläuterungen für alle Untertabs.

### Gewichtseditor (Bearbeitungsmodus)

Im Untertab „Gewichte" verfügbar, wenn der Bearbeitungsmodus aktiv ist:

1. Eine Kategorie aus dem Dropdown auswählen
2. Die Gewichtsregler anpassen (einer pro Metrik, sollten insgesamt 100% ergeben)
3. „Auf 100 normalisieren" verwenden, um automatisch auszugleichen
4. Den aufklappbaren Abschnitt „Modifikatoren" erweitern, um Boni/Strafen anzupassen
5. Die **Vorschau der Wertungsverteilung** zeigt ein Live-Vorher/Nachher-Histogramm, während Sie die Regler bewegen
6. Auf **Speichern** klicken, um `scoring_config.json` zu aktualisieren (erstellt eine zeitgestempelte Sicherung)
7. Auf **Wertungen neu berechnen** klicken (erscheint nach dem Speichern), um die neuen Gewichte auf alle Fotos dieser Kategorie anzuwenden

Alle Statistiken sind im Mehrbenutzermodus benutzerbewusst — jeder Benutzer sieht nur Auswertungen für seine sichtbaren Fotos.

## Tastenkürzel (Galerie)

| Taste | Aktion |
|-----|--------|
| `←` `→` `↑` `↓` | Tastaturfokus zwischen Fotokarten bewegen (Rasterspalten und Mosaikzeilen) |
| `Enter` | Das fokussierte Foto öffnen |
| `Space` | Das fokussierte Foto auswählen / abwählen |
| `Ctrl+A` | Alle geladenen Fotos auswählen |
| `Escape` | Auswahl aufheben / Filter-Schublade schließen |
| `Shift+Click` | Bereichsauswahl von Fotos zwischen zuletzt ausgewähltem und angeklicktem |
| `Double-click` | Foto öffnen |
| `?` | Die Tastenkürzel-Referenz anzeigen (funktioniert auf jeder Seite) |

## Rückgängig

Sammeloperationen für Favorit/Ablehnen/Bewertung und Auswahl-Bestätigungen zeigen
eine Snackbar mit einer **Rückgängig**-Aktion für ~7 Sekunden. Sammel-Flag-Operationen
werden sofort übernommen und über inverse API-Aufrufe rückgängig gemacht (begrenzt auf
500 Fotos); Auswahl-Bestätigungen werden verzögert — die Gruppe verschwindet sofort,
aber der API-Aufruf wird erst ausgelöst, wenn das Rückgängig-Zeitfenster abgelaufen ist.

## Progressive Web App

Die Galerie liefert ein Web-App-Manifest und einen Angular-Service-Worker (nur
Produktions-Builds): Sie kann auf dem Startbildschirm installiert werden, die App-Shell
lädt offline, und bis zu 1000 Vorschaubilder werden 7 Tage lang LRU-zwischengespeichert.
API-Antworten werden nie zwischengespeichert (außer i18n-Bundles mit einer Aktualitätsstrategie),
und das Abmelden leert den Vorschaubild-Cache, sodass Mehrbenutzer-Setups, die sich einen
Browser teilen, keine Vorschauen zwischen Konten preisgeben können. Eine Snackbar bietet
einen Neuladen an, wenn eine neue Version bereitgestellt wurde.

## Mobil

Auf kleinen Bildschirmen klappt die Sammelauswahl-Leiste zur Auswahlanzahl, Löschen,
Alle auswählen und einer einzigen **Aktionen**-Schaltfläche zusammen, die ein
berührungsfreundliches Bottom-Sheet mit allen Sammeloperationen öffnet (favorisieren,
ablehnen, bewerten, Alben, kopieren, herunterladen).

## Konfiguration

### Anzeigeeinstellungen

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Paginierung

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Dropdown-Limits

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Setzen Sie `min_photos_for_person` höher, um Personen mit wenigen Fotos aus dem Filter-Dropdown auszublenden.

### Qualitätsschwellen

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Standardfilter

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Gewichte für „Beste Auswahl"

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performance

### Große Datenbanken (50k+ Fotos)

Führen Sie diese für bessere Performance aus:

```bash
python database.py --migrate-tags    # 10-50x schnellere Tag-Abfragen
python database.py --refresh-stats   # Aggregationen vorberechnen
python database.py --optimize        # Datenbank defragmentieren
```

### Asynchrones SQLite (optional, für Lesepfade mit hoher Nebenläufigkeit)

`api.database.get_async_db()` ist ein aiosqlite-gestützter asynchroner Kontextmanager
parallel zu `get_db()`. Endpunkte sind derzeit synchron (FastAPI lagert sie an einen
Worker-Thread-Pool aus, was bei typischer Nebenläufigkeit in Ordnung ist). Für Lesepfade
mit hoher Nebenläufigkeit (>5 gleichzeitige Benutzer) können einzelne Endpunkte migriert
werden durch:

1. `def foo(...)` in `async def foo(...)` ändern.
2. `with get_db() as conn:` durch `async with get_async_db() as conn:` ersetzen.
3. Jedes `.execute()` und `.fetchone()` / `.fetchall()` mit `await` versehen.
4. Schreibpfade synchron belassen — aiosqlite serialisiert Schreibvorgänge ohnehin, und
   der Verbindungspool des synchronen Pfads behandelt sie bereits.

Die aussichtsreichsten Kandidaten des Plans sind `/api/photos`, `/api/timeline`,
`/api/search`. Migrieren Sie einen nach dem anderen und benchmarken Sie, bevor Sie ihn produktiv setzen.

### Statistik-Cache

Vorberechnete Aggregationen mit 5-minütiger TTL:
- Gesamte Fotoanzahlen
- Kamera-/Objektivmodellanzahlen
- Personenanzahlen
- Kategorie- und Musteranzahlen

Status prüfen:
```bash
python database.py --stats-info
```

### Verzögertes Laden von Filtern

Filter-Dropdowns werden bei Bedarf über die API geladen:
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## API-Endpunkte

Eine interaktive API-Dokumentation ist unter `/api/docs` (Swagger UI) verfügbar, das OpenAPI-Schema unter `/api/openapi.json`.

### Galerie

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/photos` | Paginierte Fotoliste mit Filtern |
| `GET /api/photo` | Details zu einem einzelnen Foto |
| `GET /api/type_counts` | Fotoanzahlen pro Typ |
| `GET /api/similar_photos/{path}` | Ähnliche Fotos (Modi: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Semantische Text-zu-Bild-Suche (`scope=text` = nur OCR-/Beschreibungstext) |
| `GET /api/critique?path=&mode=` | KI-Kritik (regelbasiert oder VLM) |
| `GET /api/ranker/status` | Status des persönlichen Rankers für die Sortierung „Mein Geschmack" (gelernte Abdeckung %, Held-out-Genauigkeit) |
| `GET /api/config` | Galerie-Konfiguration |

### Authentifizierung

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/auth/login` | Authentifizieren und Token erhalten |
| `POST /api/auth/edition/login` | Bearbeitungsmodus entsperren |
| `POST /api/auth/edition/logout` | Bearbeitungsmodus sperren (Rechte ablegen, angemeldet bleiben) |
| `GET /api/auth/status` | Authentifizierungsstatus prüfen |

### Vorschaubilder und Bilder

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /thumbnail` | Foto-Vorschaubild |
| `GET /face_thumbnail/{id}` | Gesichts-Ausschnitt-Vorschaubild |
| `GET /person_thumbnail/{id}` | Repräsentatives Personen-Vorschaubild |
| `GET /image` | Bild in voller Auflösung |

### Filteroptionen

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/filter_options/cameras` | Kameramodelle mit Anzahlen |
| `GET /api/filter_options/lenses` | Objektivmodelle mit Anzahlen |
| `GET /api/filter_options/tags` | Tags mit Anzahlen |
| `GET /api/filter_options/persons` | Personen mit Anzahlen |
| `GET /api/filter_options/patterns` | Kompositionsmuster |
| `GET /api/filter_options/categories` | Kategorien mit Anzahlen |
| `GET /api/filter_options/apertures` | Eindeutige F-Stop-Werte mit Anzahlen |
| `GET /api/filter_options/focal_lengths` | Eindeutige Brennweiten mit Anzahlen |
| `GET /api/filter_options/colors` | Facetten für Farbtemperatur und Farbtongruppe mit Anzahlen |
| `GET /api/filter_options/metric_ranges` | Beobachtetes Min/Max und Histogramm pro numerischer Metrik (für Reglergrenzen) |

### Sammeloperationen

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Mehrere Fotos als Favorit markieren |
| `POST /api/photos/batch_reject` | Mehrere Fotos als abgelehnt markieren |
| `POST /api/photos/batch_rating` | Sternebewertung für mehrere Fotos setzen |

### Personen

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/persons` | Alle Personen auflisten |
| `POST /api/persons` | Eine neue Person erstellen, optional mit Gesichtern (Bearbeitungsmodus erforderlich). Body: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Unbenannte, automatisch geclusterte Personen mit `face_count >= N` auflisten (Standard aus `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Eine Person umbenennen |
| `POST /api/persons/{id}/assign_faces` | Gesichter per Sammelaktion einer Person zuweisen; leere Alt-Personen werden automatisch gelöscht (Bearbeitungsmodus erforderlich). Body: `{face_ids}` |
| `POST /api/persons/{id}/split` | Eine Teilmenge der Gesichter einer Person in eine neue Person aufteilen (Bearbeitungsmodus erforderlich). Body: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Eine Person aus Liste, Filtern und Zusammenführungsvorschlägen ausblenden |
| `POST /api/persons/{id}/unhide` | Eine zuvor ausgeblendete Person wieder einblenden |
| `POST /api/persons/merge` | Zwei Personen zusammenführen (JSON-Body) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Quellperson in Zielperson zusammenführen |
| `POST /api/persons/merge_batch` | Mehrere Personen auf einmal zusammenführen |
| `POST /api/persons/merge_suggestions/reject` | Einen Zusammenführungsvorschlag verwerfen, sodass er nicht erneut vorgeschlagen wird |
| `POST /api/persons/{id}/delete` | Eine Person löschen |
| `POST /api/persons/delete_batch` | Mehrere Personen auf einmal löschen |

### Alben

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/albums` | Alle Alben auflisten |
| `POST /api/albums` | Album erstellen |
| `GET /api/albums/{id}` | Albumdetails abrufen |
| `PUT /api/albums/{id}` | Album aktualisieren |
| `DELETE /api/albums/{id}` | Album löschen |
| `GET /api/albums/{id}/photos` | Fotos im Album auflisten (paginiert) |
| `POST /api/albums/{id}/photos` | Fotos zum Album hinzufügen |
| `DELETE /api/albums/{id}/photos` | Fotos aus dem Album entfernen |
| `POST /api/albums/{id}/share` | Freigabe-Token erzeugen |
| `DELETE /api/albums/{id}/share` | Freigabe-Token widerrufen |
| `GET /api/shared/album/{id}?token=` | Geteiltes Album ansehen (keine Authentifizierung) |

### Erinnerungen, Zeitleiste, Karte & Bildbeschreibungen

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/memories?date=` | Fotos, die an diesem Datum in früheren Jahren aufgenommen wurden |
| `GET /api/memories/check` | Prüfen, ob für ein Datum Erinnerungen existieren |
| `GET /api/caption?path=` | KI-Bildbeschreibung abrufen oder generieren |
| `PUT /api/caption` | Bildbeschreibung aktualisieren (Bearbeitungsmodus) |
| `GET /api/timeline?cursor=&limit=&direction=` | Paginierte Zeitleisten-Fotos |
| `GET /api/timeline/dates?year=&month=` | Verfügbare Daten für die Navigation |
| `GET /api/timeline/years` | Verfügbare Jahre mit Fotoanzahlen |
| `GET /api/timeline/months` | Verfügbare Monate für ein Jahr |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Georeferenzierte Fotos innerhalb der Grenzen |
| `GET /api/photos/map/count` | Anzahl georeferenzierter Fotos |

### Kapseln

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/capsules` | Paginierte Kapselliste (zwischengespeichert) |
| `GET /api/capsules/{id}/photos` | Fotos für eine bestimmte Kapsel |
| `POST /api/capsules/{id}/save-album` | Kapsel als Album speichern (Bearbeitungsmodus) |

### Statistiken

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/stats/overview` | Zusammenfassung der Gesamtwertungsstatistiken |
| `GET /api/stats/score_distribution` | Histogrammdaten der Wertungsverteilung |
| `GET /api/stats/top_cameras` | Top-Kameras nach Fotoanzahl |
| `GET /api/stats/categories` | Kategorieanzahlen und -durchschnitte |
| `GET /api/stats/gear` | Kamera-/Objektiv-/Kombinationsanzahlen |
| `GET /api/stats/settings` | Verteilungen der Aufnahmeeinstellungen |
| `GET /api/stats/timeline` | Zeitleistendaten |
| `GET /api/stats/correlations` | Benutzerdefinierte Metrikkorrelationen |
| `GET /api/stats/categories/breakdown` | Fotoanzahlen pro Kategorie und Wertungsverteilungen |
| `GET /api/stats/categories/weights` | Kategoriegewichte und -modifikatoren aus der Konfiguration |
| `GET /api/stats/categories/correlations` | Pearson-r-Korrelation pro Dimension pro Kategorie |
| `GET /api/stats/categories/metrics?category=X` | Rohe Metrikwerte für die clientseitige Vorschau |
| `GET /api/stats/categories/overlap` | Filterüberschneidungsanalyse zwischen Kategorien |
| `POST /api/stats/categories/update` | Kategoriegewichte/-modifikatoren aktualisieren (Bearbeitungsmodus) |
| `POST /api/stats/categories/recompute` | Wertungen für eine Kategorie neu berechnen (Bearbeitungsmodus) |

### Vergleichsmodus

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/comparison/next_pair` | Nächstes Fotopaar zum Vergleich abrufen |
| `POST /api/comparison/submit` | Vergleichsergebnis übermitteln |
| `POST /api/comparison/reset` | Vergleichsdaten zurücksetzen |
| `GET /api/comparison/stats` | Statistiken der Vergleichssitzung |
| `GET /api/comparison/history` | Vergangene Vergleiche auflisten |
| `POST /api/comparison/edit` | Ein Vergleichsergebnis bearbeiten |
| `POST /api/comparison/delete` | Einen Vergleich löschen |
| `GET /api/comparison/coverage` | Kategorieabdeckung der Vergleiche |
| `GET /api/comparison/confidence` | Konfidenzmetriken für gelernte Wertungen |
| `GET /api/comparison/photo_metrics` | Rohe Metriken für Fotos |
| `GET /api/comparison/category_weights` | Kategoriegewichte/-filter |
| `GET /api/comparison/learned_weights` | Vorgeschlagene Gewichte aus Vergleichen |
| `POST /api/comparison/preview_score` | Vorschau mit benutzerdefinierten Gewichten |
| `POST /api/comparison/suggest_filters` | Filterkonflikte analysieren |
| `POST /api/comparison/override_category` | Fotokategorie überschreiben |
| `POST /api/recalculate` | Wertungen mit aktuellen Gewichten neu berechnen |

### Serienbild-Auswahl

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/burst-groups` | Serienbildgruppen für die Auswahl auflisten |
| `POST /api/burst-groups/select` | Behaltefotos aus einer Serienbildgruppe auswählen |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Gruppen visuell ähnlicher Fotos |
| `POST /api/similar-groups/select` | Behaltefotos aus einer Ähnlichkeitsgruppe auswählen |
| `GET /api/culling-groups?exclude_rejected=true&similarity_threshold=&page=&per_page=` | Kombinierte Serienbild- und Ähnlichkeitsgruppen. `exclude_rejected` (Standard `true`) blendet Fotos mit `is_rejected=1` aus; Gruppen mit weniger als 2 verbleibenden Fotos werden verworfen |
| `POST /api/culling-groups/confirm` | Auswahlentscheidungen bestätigen |
| `POST /api/culling-group/faces` | Abzeichen pro Gesicht (Augen offen/geschlossen, Ausdruck, Konfidenz) für eine Gruppe, in einem Batch |
| `GET /api/scenes` | Chronologische Szenen von Serienbild-Leitfotos |
| `POST /api/scenes/confirm` | Szenen-Auswahlentscheidungen bestätigen |

### Scan

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Einen Bewertungs-Scan starten |
| `GET /api/scan/status` | Scan-Fortschritt prüfen (strukturiertes `progress`: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Echtzeit-Fortschritt über Server-Sent Events; das Token wird als Query-Parameter übergeben (die `EventSource`-API kann keine Header setzen), mit automatischem Rückgriff auf das Polling von `/status` |
| `GET /api/scan/directories` | Konfigurierte Scan-Verzeichnisse auflisten |

### Gesichtsverwaltung

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/person/{id}/faces` | Gesichter einer Person auflisten |
| `POST /api/person/{id}/avatar` | Avatar-Gesicht einer Person festlegen |
| `GET /api/photo/faces` | In einem Foto erkannte Gesichter auflisten |
| `POST /api/face/{id}/assign` | Ein Gesicht einer Person zuweisen |
| `POST /api/photo/assign_all_faces` | Alle Gesichter in einem Foto einer Person zuweisen |
| `POST /api/photo/unassign_person` | Eine Person von einem Foto entfernen |

### Fotoaktionen

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/photo/set_rating` | Sternebewertung für ein Foto setzen |
| `POST /api/photo/toggle_favorite` | Favoritenstatus umschalten |
| `POST /api/photo/toggle_rejected` | Ablehnungsstatus umschalten |

### Konfigurationsverwaltung

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/config/update_weights` | Bewertungsgewichte aktualisieren |
| `GET /api/config/weight_snapshots` | Gespeicherte Gewichts-Snapshots auflisten |
| `POST /api/config/save_snapshot` | Aktuelle Gewichte als Snapshot speichern |
| `POST /api/config/restore_weights` | Gewichte aus einem Snapshot wiederherstellen |

### Zusammenführungsvorschläge

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/merge_suggestions` | Vorgeschlagene Personenzusammenführungen basierend auf Gesichtsähnlichkeit |

### Ordner

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/folders` | Foto-Ordnerstruktur auflisten |

### Download

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/download/options` | Verfügbare Download-Typen für ein Foto (`path`, optional `is_shared`) |
| `GET /api/download` | Ein Foto herunterladen (`path`, `type=original\|darktable\|raw`, optional `profile`) |

**Download-Typen:**

- `original` — Die Datei unverändert ausliefern (JPG/HEIF) oder rawpy-konvertiert zu JPEG (RAW-Dateien).
- `darktable` — Begleitende RAW-Datei mit einem benannten darktable-Profil konvertieren (erfordert den Parameter `profile`). Greift auf das Original zurück, wenn keine begleitende RAW-Datei existiert.
- `raw` — Die begleitende RAW-Datei unverändert ausliefern (in geteilten Alben nicht verfügbar).

Der Endpunkt `/api/download/options` erkennt begleitende RAW-Dateien automatisch und liefert verfügbare Optionen einschließlich konfigurierter darktable-Profile zurück. Die Galerie verwendet dies, um ein Download-Menü pro Foto zu befüllen.

### Editor-Export

| Endpunkt | Beschreibung |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Ein XMP-Sidecar schreiben |
| `POST /api/export/sidecars` | `[Edition]` Sidecars für explizite Pfade oder eine Filtermenge schreiben |
| `POST /api/photo/embed_metadata` | `[Edition]` Metadaten in die Originaldatei einbetten (JPEG/HEIC/TIFF/PNG/DNG; RAW wird nie verändert) und das Sidecar schreiben |
| `POST /api/albums/{id}/export` | `[Edition]` Album-Export als Sidecars, Kopie oder Symlink |

### Plugins

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/plugins` | Konfigurierte Plugins auflisten |
| `POST /api/plugins/test-webhook` | Ein Webhook-Plugin testen |

### Health

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /health` | Server-Health-Check |
| `GET /ready` | Server-Readiness-Check |
| `GET /metrics` | Metriken im Prometheus-Format: Fotoanzahlen, Embedding-Abdeckung, DB-Größe, Prozessspeicher |

### Internationalisierung

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/i18n/languages` | Verfügbare Sprachen auflisten |
| `GET /api/i18n/{lang}` | Übersetzungen für eine Sprache abrufen |

### Filteroptionen (zusätzlich)

| Endpunkt | Beschreibung |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Koordinaten per umgekehrter Geocodierung in einen Ortsnamen umwandeln |

## Fehlerbehebung

| Problem | Lösung |
|-------|----------|
| Langsames Laden der Seite | `--migrate-tags` und `--optimize` ausführen |
| Filter werden nicht angezeigt | `--stats-info` prüfen, `--refresh-stats` ausführen |
| Personenfilter leer | `--cluster-faces-incremental` ausführen |
| Schaltfläche „Vergleichen" fehlt | Ein nicht leeres `edition_password` setzen (Einzelbenutzer) oder die Rolle `admin`/`superadmin` verwenden (Mehrbenutzer) |
| Passwort funktioniert nicht | `viewer.password` prüfen (Einzelbenutzer) oder den Passwort-Hash verifizieren (Mehrbenutzer) |
| Benutzer kann keine Fotos sehen | `directories` in seiner Benutzerkonfiguration und `shared_directories` prüfen |
| Scan-Schaltfläche fehlt | Erfordert die Rolle `superadmin` und `viewer.features.show_scan_button: true` |
| Suche liefert keine Ergebnisse | Sicherstellen, dass Fotos `clip_embedding`-Daten haben (zuerst Bewertung ausführen) |
| VLM-Kritik nicht verfügbar | Erfordert das 16gb/24gb-VRAM-Profil und `viewer.features.show_vlm_critique: true` |
| Karte zeigt keine Fotos | `--extract-gps` ausführen, um GPS-Spalten zu befüllen; sicherstellen, dass Fotos EXIF-GPS-Daten haben |
| Bildbeschreibungen werden nicht generiert | Erfordert das 16gb/24gb-VRAM-Profil für VLM-Bildbeschreibungen |
| Zeitleiste leer | Sicherstellen, dass Fotos `date_taken`-Werte haben |
| Port 5000 belegt | `python viewer.py --port 5001` ausführen (oder `PORT=5001` setzen). Unter macOS belegt der AirPlay-Empfänger des ControlCenter standardmäßig Port 5000 — entweder einen anderen Port wählen oder den AirPlay-Empfänger unter Systemeinstellungen → Allgemein → AirDrop & Handoff deaktivieren. |
