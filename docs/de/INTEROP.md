# Editor-Interop-Rezepte

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · **Deutsch** · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md)

Praktische Schritt-für-Schritt-Rezepte, um Facets Bewertungen, Labels und Tags mit den externen Editoren und DAM-Tools auszutauschen, die tatsächlich verwendet werden. Diese Seite setzt voraus, dass Sie bereits wissen, *dass* Facet XMP schreibt — siehe [Befehle — Vorschau & Export](COMMANDS.md#preview--export) für die vollständige Referenz der Optionen `--export-sidecars` / `--import-sidecars` und die Feldzuordnung (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## Die RAW-Sidecar-Namensfalle

Facet benennt ein Sidecar `<bild><ext>.xmp` — z. B. `IMG_1234.CR2.xmp` neben `IMG_1234.CR2` — dieselbe Konvention, die darktable und digiKam verwenden. **Lightroom Classic und Capture One erwarten das Gegenteil: `IMG_1234.xmp`, ohne die RAW-Dateiendung.** Keine der beiden Anwendungen findet ein von Facet geschriebenes Sidecar für eine proprietäre RAW-Datei (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — alles außer DNG), und Facets eigenes `--import-sidecars` findet umgekehrt auch kein Sidecar, das eine Anwendung aus dem Adobe-Ökosystem für dieselbe RAW-Datei geschrieben hat. Es handelt sich um eine zwischen den Ökosystemen nicht übereinstimmende Namenskonvention, nicht um einen Fehler auf einer der beiden Seiten.

Betroffen sind **nicht**:
- **JPEG, HEIC, TIFF, PNG, DNG** — übergeben Sie `--embed-originals`, und Facet schreibt die Metadaten *direkt in die Datei* (über exiftool), sodass es keinen Sidecar-Namen gibt, den Lightroom/Capture One übersehen könnten.
- **digiKam** — prüft beide Namenskonventionen und findet Facets Sidecar in jedem Fall (siehe [digiKam](#digikam) weiter unten).
- **darktable** — verwendet dieselbe Konvention `<bild><ext>.xmp` wie Facet (siehe [darktable](#darktable) weiter unten).

Für einen Lightroom- oder Capture-One-Workflow gilt also: Verwenden Sie `--embed-originals` für alles, was keine proprietäre RAW-Datei ist, und rechnen Sie damit, dass der Sidecar-Roundtrip bei reinen RAW-Dateien stillschweigend nichts bewirkt (kein Fehler, es wird einfach nichts gelesen). Wenn Sie in RAW+JPEG fotografieren, ist die begleitende JPEG-Datei das praktische Interop-Vehikel — die RAW-Datei bleibt unverändert auf der Festplatte liegen, während Facets Datenbank die maßgebliche Bewertung führt.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (fügen Sie einen Pfad hinzu, um den Umfang einzugrenzen, z. B. `--export-sidecars /fotos/hochzeit-2026`). Fügen Sie `--embed-originals` hinzu, um zusätzlich direkt in JPEG-/HEIC-/TIFF-/PNG-/DNG-Dateien zu schreiben.
2. Wählen Sie im Bibliotheksmodul von Lightroom Classic die Fotos aus (Strg/Cmd+A für alle) und wählen Sie **Metadaten → Metadaten aus Datei lesen**. Lightroom überschreibt Bewertung, Farblabel und Stichwörter seines Katalogs aus dem Sidecar (oder den eingebetteten Metadaten, für die oben genannten Formate).

Facets Ablehnungsmarker (`xmp:Rating = -1`) wird beim Zurücklesen als Lightrooms Ablehnen-Flag interpretiert. Ein Facet-Favorit schreibt `xmp:Label = Yellow`, was Lightroom als **gelbes Farblabel** anzeigt — nicht als Pick-Flag. Wenn Ihr Lightroom-Workflow auf Pick-Flags statt auf Farblabels basiert, fügen Sie einen Umwandlungsschritt Farblabel → Pick hinzu, oder filtern Sie stattdessen nach dem gelben Label.

### Lightroom → Facet

1. Wählen Sie in Lightroom die Fotos aus und wählen Sie **Metadaten → Metadaten in Datei speichern** (Strg/Cmd+S). Dadurch werden Bewertung, Label und Stichwörter des Katalogs in das XMP-Sidecar (RAW) geschrieben oder direkt in die Datei eingebettet (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (optional auf einen Pfad eingegrenzt) liest sie zurück in Facets Datenbank.

### Konfliktregeln

- **Bewertungen und Labels folgen der Regel „neueste gewinnt"**, verglichen zwischen dem `xmp:MetadataDate` des Sidecars und dem `scanned_at` des Fotos (dem letzten Zeitpunkt, an dem Facet es bewertet hat) — nicht einem Zeitstempel pro Bewertung. Ein Sidecar, das neuer ist als der letzte Scan, kann eine Bewertung überschreiben, die Sie *nach* diesem Scan in Facet geändert haben. Halten Sie den Roundtrip einfach: Export → Lightroom liest → Bearbeitung in Lightroom → Lightroom speichert → Import, ohne zwischendurch in Facet neu zu bewerten.
- **Tags und Stichwörter werden immer zusammengeführt** (Vereinigung, dedupliziert) in beide Richtungen — Lightroom-Stichwörter löschen nie Facets automatische Tags, und umgekehrt.
- **Mehrbenutzerbetrieb** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): Bewertungen werden in Alices `user_preferences`-Zeile geleitet statt in die globalen Spalten. Stichwörter bleiben unabhängig von `--user` global — sie werden zwischen Benutzern geteilt.
- Führen Sie nach `--import-sidecars` `python database.py --migrate-tags` aus, wenn Sie die Nachschlagetabelle `photo_tags` verwenden, damit Tag-Filter die zusammengeführten Stichwörter sofort sehen.

## Capture One

Capture One schreibt nie in die Originaldatei oder in ein kontinuierlich synchronisiertes XMP-Sidecar, wie es Lightrooms automatisches Speichern tut — es hält seine eigenen Anpassungen in `.cos`-Einstellungsdateien (Sessions) oder seiner Katalogdatenbank, und seine Einstellung **Sync Metadata** hat einen bidirektionalen „Full Sync"-Modus, der stillschweigend überschreiben kann, welche Seite zuletzt geschrieben hat. Eine bidirektionale Schleife über diese Einstellung laufen zu lassen, riskiert den Verlust entweder von Facets oder von Capture Ones Änderungen. Das sichere Muster ist **Einbahnstraße, Facet → Capture One**:

1. `python facet.py --export-sidecars /pfad/zur/session --embed-originals`.
2. Belassen Sie in Capture One **Preferences → General → Sync Metadata** auf dem Standardwert (nicht „Full Sync").
3. Wählen Sie die importierten Bilder aus, klicken Sie mit der rechten Maustaste, und wählen Sie **Load Metadata**, um Bewertung, Label und Stichwörter aus dem Sidecar (oder den eingebetteten Metadaten) einmalig in die Katalogfelder von Capture One zu übernehmen.

Betrachten Sie Facet als vorgelagerte Quelle der Wahrheit für KI-abgeleitete Bewertungen und Tags dieser Session: Führen Sie den einmaligen Import über `Load Metadata` durch, treffen Sie dann weitere Entscheidungen in Capture One, ohne dessen Metadaten-Synchronisierung zurück in Facets Sidecar zu verdrahten. Wenn Sie Capture Ones Entscheidungen zurück in Facet übernehmen möchten, exportieren Sie sie explizit aus Capture One nach XMP und führen Sie `--import-sidecars` für diesen Ordner als separaten, bewussten Schritt aus statt als automatische Synchronisierung — und denken Sie an die [RAW-Sidecar-Namensfalle](#die-raw-sidecar-namensfalle) oben: Dies funktioniert nur für JPEG/HEIC/TIFF/PNG/DNG, da Capture One RAW-Sidecars ebenfalls `<bild>.xmp` statt Facets `<bild><ext>.xmp` benennt.

## digiKam

digiKam liest XMP-Sidecars nativ — auf digiKam-Seite ist kein exiftool nötig — und es sucht nach beiden Namenskonventionen (zuerst `<bild><ext>.xmp`, dann als Fallback `<bild>.xmp`), sodass es Facets Sidecars für RAW-Dateien ohne die obige Falle findet. Öffnen (oder aktualisieren) Sie nach `python facet.py --export-sidecars` den Ordner in digiKam: Es übernimmt automatisch Bewertung, Farblabel, Stichwörter und benannte Gesichtsbereiche, solange **Settings → Configure digiKam → Metadata → Read from sidecar files** aktiviert ist (der Standard).

### Batch-Queue-Manager-Hook

Sie können einen Facet-Reimport in einen digiKam-Batch-Queue-Manager-Workflow (BQM) mit dem Werkzeug **Custom Script** einbinden, sodass Fotos, die Sie in digiKam bewerten oder labeln, in Facets Datenbank zurückfließen, ohne digiKam zu verlassen. Aktivieren Sie **Settings → Configure digiKam → Metadata → Write to sidecar files**, damit digiKam Ihre Änderungen sofort in `<bild>.xmp` persistiert, und fügen Sie dann eine Queue hinzu, deren einziges Werkzeug Custom Script ist:

```bash
#!/bin/bash
python /pfad/zu/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sind digiKams Platzhalter pro Datei (BQM führt das Skript unter Linux/macOS über `/bin/bash` aus und erwartet eine Ausgabedatei, daher die `cp`-Weiterleitung). Da `--import-sidecars` den gesamten Ordner durchsucht, ist die Ausführung einmal pro Foto in einer großen Charge redundant, wenn auch harmlos (sie ist idempotent — unveränderte Fotos werden übersprungen). Verzichten Sie bei großen Chargen auf den BQM-Hook und führen Sie stattdessen einfach einmal von Hand `python facet.py --import-sidecars /pfad/zum/ordner` aus, nachdem die Queue abgeschlossen ist.

## darktable

darktable wird bereits erstklassig behandelt in [Konfiguration — Viewer](CONFIGURATION.md#viewer) (Export-Profile/-Stile `viewer.raw_processor.darktable`) und [Viewer — Download](VIEWER.md#api-endpunkte) (Konvertierungen `type=darktable`). Auf der XMP-Seite: darktable schreibt sein eigenes `<bild>.xmp`, um seinen Bearbeitungsverlauf zu speichern, und Facets exiftool-gestützter Sidecar-Writer führt an derselben Datei eine In-Place-Zusammenführung durch — die Knoten `darktable:history`/Masken bleiben erhalten und werden nie überschrieben. Ein separates Rezept ist hier nicht nötig: Das oben für Lightroom beschriebene bidirektionale Sidecar-Verhalten (Export/Import, neueste gewinnt, Tag-Vereinigung) gilt hier genauso, ohne die RAW-Namensfalle, da sich darktable und Facet auf `<bild><ext>.xmp` einigen.

## Wie Facet zusammenführt

| Feld | Facet schreibt | Facet liest zurück | Konfliktregel |
|---|---|---|---|
| Bewertung (Sterne/Ablehnung) | `xmp:Rating` (`-1` = abgelehnt) | `xmp:Rating` | Neueste gewinnt, vs. `scanned_at` |
| Farblabel | `xmp:Label` (`Red` = abgelehnt, `Yellow` = Favorit) | `xmp:Label` | Neueste gewinnt, vs. `scanned_at` |
| Tags/Stichwörter | `dc:subject` (flach, enthält Namen aus benannten Gesichtsbereichen) | `dc:subject` | Immer zusammengeführt (Vereinigung, dedupliziert) |
| Hierarchische Tags | `lr:hierarchicalSubject` (`Category\|<kat>`, `People\|<name>`) | Nicht zurückimportiert | Nur Export |
| Bildunterschrift | `dc:description` (+ `IPTC:Caption-Abstract` über exiftool) | Nicht zurückimportiert | Nur Export |
| Benannte Gesichtsbereiche | MWG `mwg-rs:RegionList` (zentriert-normalisiert, `Type=Face`) | Nicht zurückimportiert | Nur Export; nativ von digiKam gelesen, **nicht** von Lightroom (eine bekannte Adobe-Einschränkung — Lightroom liest nur MWG-Bereiche, die es selbst geschrieben hat) |

Siehe [Befehle — Vorschau & Export](COMMANDS.md#preview--export) für die vollständige CLI-Referenz (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
