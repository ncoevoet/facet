# Editor-Interop-Rezepte

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · **Deutsch** · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Schritt-für-Schritt-Rezepte, um Facets Bewertungen, Labels und Tags mit Lightroom, Capture One, digiKam und darktable auszutauschen. Die vollständige Referenz der Optionen `--export-sidecars` / `--import-sidecars` und die Feldzuordnung (`xmp:Rating`, `xmp:Label`, `dc:subject`) finden Sie unter [Befehle — Vorschau & Export](COMMANDS.md#vorschau--export).

Originale werden nie verändert, es sei denn, Sie verlangen das Einbetten: `--embed-originals` auf der Kommandozeile oder **Metadaten in Datei schreiben** im Viewer.

## Was übertragen wird

Manuelle Orte und Bewertungsentscheidungen werden nur übertragen, wenn Sie Metadaten im Viewer exportieren oder `--export-sidecars` ausführen.

- **GPS** verwendet `exif:GPSLatitude` / `exif:GPSLongitude`. Es werden nur manuell gesetzte Orte exportiert, sodass gescanntes GPS nie das GPS der Datei ersetzt. `--embed-originals` schreibt außerdem EXIF-GPS in unterstützte Originale. Das Löschen eines Orts exportiert ein ausdrückliches Löschen; ein fehlendes Feld löscht beim Import nie einen Ort.
- **Aufnahmedatum.** Ein korrigiertes Datum wird als `exif:DateTimeOriginal` exportiert (mit `--embed-originals` auch als EXIF-`DateTimeOriginal`). Nach **Dateidatum verwenden** entfernt der nächste Export es aus dem Sidecar, lässt aber ein von einem anderen Editor geschriebenes Datum unangetastet.
- **Behalten und Ablehnen.** Behalten ist unabhängig von Sternen und Favoriten. Ablehnen löscht Behalten, Sterne und Favorit.

Facets eigener XMP-Namensraum `https://github.com/ncoevoet/facet/ns/1.0/` ergänzt:

| Tag | Werte | Zweck |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | Facets Bewertungsentscheidung |
| `facet:GPSState` | `set`, `cleared` | Ob Facet den Ort gesetzt oder gelöscht hat |
| `facet:DateState` | `set` | Das Aufnahmedatum im Sidecar stammt von Facet |
| `facet:KeywordState` | JSON (`version` 1; Listen `owned`, `deleted`, `ai`, `manual`) | Welche Stichwörter Facet geschrieben hat |
| `facet:RegionOwner` | `Facet` | Die von Facet geschriebenen MWG-Gesichtsregionen |

Mit `facet:KeywordState` entfernt `--reconcile-keywords` nur Namen, die Facet gehören, und ein alter KI-Label wird beim Import nicht zu einem manuellen Tag. Mit `facet:RegionOwner` ersetzt ExifTool nur Facets Gesichtsregionen.

So wendet `--import-sidecars` eine Facet-Entscheidung an:

- Es wendet eine Entscheidung an, wenn die Standard-Bewertungsfelder mit ihr übereinstimmen oder fehlen.
- Weicht der Standard-Ablehnungsstatus ab, hat ein anderer Editor die Standardfelder geändert. Facet ignoriert seine private Entscheidung und nutzt für die Standardfelder die „neueste gewinnt“-Prüfung mit dem Scanzeitpunkt.
- Eine zusammen mit Standard-Bewertungsfeldern exportierte Entscheidung nutzt ebenfalls die „neueste gewinnt“-Prüfung, sodass ein älterer Export eine neuere Entscheidung nicht zurücksetzen kann. Ausnahme ist ein Foto ohne Bewertungsstatus (keine Sterne, kein Favorit, kein Behalten, keine Ablehnung): Eine neu gescannte Bibliothek bekommt ihre Entscheidungen zurück.
- Importe nur der Entscheidung bleiben ausdrücklich (Sie verlangen sie) und werden ohne die Scanzeit-Prüfung angewendet.

Weitere Regeln:

- Manuelles GPS, das bereits in Facet vorhanden ist, bleibt erhalten, außer Sie fügen `--overwrite-manual-gps` hinzu. Ungültige oder unvollständige Koordinaten werden ignoriert.
- `--user alice` beschränkt Importe und Exporte auf die sichtbaren Ordner und privaten Entscheidungen dieses Benutzers. GPS bleibt gemeinsam. Ohne `--user` arbeitet die CLI mit dem globalen Zustand.
- Globale Importe (ohne `--user`), auch Vorschauen mit `--dry-run`, benötigen den Anmeldeschlüssel des Viewers nicht.
- Mit ExifTool wird der Export in vorhandene Sidecars zusammengeführt. Ohne ExifTool lässt der Export ein vorhandenes Editor-Sidecar unangetastet und schreibt eine Ersatzdatei.
- ExifTool-Exporte benötigen die mitgelieferten Facet-Tagdefinitionen. Fehlen sie, stoppt der Export vor jeder Änderung; installieren Sie Facet neu.

## Die RAW-Sidecar-Namensfalle

Facet exportiert `IMG_1234.CR2.xmp` neben `IMG_1234.CR2` (darktables Konvention mit vollständigem Dateinamen). Lightroom Classic und Capture One verwenden für proprietäres RAW gewöhnlich `IMG_1234.xmp`. Exportnamen ändern sich nie.

Für JPEG/HEIC/TIFF/PNG/DNG schreibt `--embed-originals` stattdessen in die Datei. GIF/WebP/BMP/AVIF/JPEG XL und proprietäres RAW benötigen weiterhin ein Sidecar mit passender Benennung.

Beim Import wählen Sie die Benennung mit `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (Standard): liest `<image.ext>.xmp` oder `<image.ext>.facet.xmp`, je nachdem, welche zuletzt geändert wurde. Bei Gleichstand gewinnt die primäre Datei.
- `basename`: liest `<image>.xmp` (nur die letzte Endung entfällt). Sidecars mit vollständigem Namen werden ignoriert.
- `auto`: akzeptiert, was vorhanden ist. Existieren beide, wird das Foto als mehrdeutig übersprungen; wählen Sie stattdessen `full` oder `basename`.

Bei `basename` und `auto` wird ein Basisname, den mehrere Bilder teilen (z. B. `same.CR3` und `same.jpg`), abgelehnt, auch wenn nur eines davon im Umfang liegt. Verwenden Sie dafür Sidecars mit vollständigem Namen. `same_v1.jpg` hat einen anderen Basisnamen und ist unproblematisch.

- Eine Datei mit doppelter Endung wie `IMG.CR2.jpg` liest nie `IMG.CR2.xmp`, das zu `IMG.CR2` gehört. Dasselbe gilt für den `.facet.xmp`-Fallback eines anderen Bildes.
- Abweichungen, Mehrdeutigkeiten und unlesbare Sidecars werden gemeldet. Nach einem Parsefehler probiert Facet keine andere Benennung aus.
- Die Zusammenfassung zählt jedes betroffene Foto, auch Sidecars, die wegen der gewählten Benennung ignoriert wurden. Hinweise zeigen ein Beispiel je Art.
- Es werden keine Dateien umbenannt.

Der Import benötigt kein ExifTool. Exportzusammenführung, Einbettung und MWG-Gesichtsrechtecke benötigen ExifTool. Ohne ExifTool lässt Facet ein vorhandenes Editor-Sidecar in Ruhe und schreibt `<image.ext>.facet.xmp` ohne Gesichtsrechtecke. Andere Editoren suchen nicht nach diesem Namen, geben Sie die Datei also bewusst weiter.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (fügen Sie einen Pfad hinzu, um den Umfang einzugrenzen, z. B. `--export-sidecars /photos/2026-wedding`). Fügen Sie `--embed-originals` hinzu, um zusätzlich direkt in JPEG-/HEIC-/TIFF-/PNG-/DNG-Dateien zu schreiben.
2. Wählen Sie im Bibliotheksmodul von Lightroom Classic die Fotos aus (Strg/Cmd+A für alle) und wählen Sie **Metadaten → Metadaten aus Datei lesen**. Lightroom ersetzt Bewertung, Farblabel und Stichwörter durch die des Sidecars (oder der eingebetteten Metadaten).

Facets Ablehnungsmarker (`xmp:Rating = -1`) wird beim Zurücklesen als Lightrooms Ablehnen-Flag interpretiert. Ein Facet-Favorit schreibt `xmp:Label = Yellow`, was Lightroom als **gelbes Farblabel** anzeigt, nicht als Pick. Für Picks verwenden Sie das Zusatzmodul unten oder filtern nach dem gelben Label.

`python facet.py --export-manifest` schreibt Facets Daten ohne XMP: Pfad, Kategorie, alle Scores, Tags und dieselben Bewertungsspalten wie `--export-sidecars`. Verwenden Sie `--export-manifest --user alice` für benutzerbezogene Bewertungen. Siehe [Befehle — Vorschau & Export](COMMANDS.md#vorschau--export). Das Facet-Zusatzmodul unten liest es.

**Manifest Version 2** ergänzt `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` und eine übergeordnete Zählung `pending_corrections`. Sie gibt die Zahl der manuellen Bracket-/Panorama-Korrekturen an, die noch nicht angewendet wurden; führen Sie `--detect-panoramas` erneut aus, um sie anzuwenden. Das Zusatzmodul zeigt sie als Warnung in seiner Vorschau. Ein Zusatzmodul der Version 2 weist ein Version-1-Manifest zurück (und umgekehrt); führen Sie `--export-manifest` erneut aus, wenn dieser Dialog erscheint.

Im Viewer bietet der Dialog **Export to editor** der Galerie einen Button **Download Lightroom manifest** für dieselbe Auswahl oder denselben Filter — siehe [Editor Export](VIEWER.md#editor-export). Er erzeugt dieselbe `facet_manifest.json` wie `--export-manifest`.

### Das Facet-Zusatzmodul (Sternebewertungen, Pick-Flags, Metadatenfelder und Stichwörter)

`facet.lrplugin/` im Facet-Repository ist ein Lightroom-Classic-Zusatzmodul (Plug-in). Es schreibt Facets Sternebewertungen und den Favorit-/Ablehnungs-Status **direkt in den Katalog**. Das löst zwei Dinge, die XMP nicht kann: Lightroom findet für proprietäres RAW nie ein Facet-Sidecar, und XMP kann Lightrooms Pick-Flag nicht transportieren.

Das Zusatzmodul liest eine Manifestdatei. Es kontaktiert nie den Facet-Server, braucht kein Passwort und funktioniert, während Facet gestoppt ist. Es ordnet Fotos über den Pfad zu, sodass **eine reine RAW-Bibliothek genau wie eine JPEG-Bibliothek funktioniert**.

Es fügt zwei Einträge unter **Bibliothek → Zusatzmoduloptionen** (**Library → Plug-in Extras**) hinzu:

- **Facet: Apply ratings and flags...** — Manifest → Katalog (dieser Abschnitt).
- **Facet: Export Lightroom State to Facet...** — Katalog → Facet, siehe [Lightroom → Facet](#lightroom--facet).

**Installation** (einmalig):

1. Kopieren Sie den Ordner `facet.lrplugin` auf den Rechner, auf dem Lightroom läuft. Unter macOS vorher zippen: Der Finder behandelt einen `.lrplugin`-Ordner als Paket.
2. In Lightroom Classic: **Datei → Zusatzmodul-Manager → Hinzufügen**, den Ordner `facet.lrplugin` auswählen, dann **Fertig**.

**Verwendung:**

1. `python facet.py --export-manifest /photos/2026-wedding` (der Pfad grenzt den Export ein; die Datei landet immer als `facet_manifest.json` im aktuellen Verzeichnis). Kopieren Sie sie bei Bedarf auf den Lightroom-Rechner.
2. Wählen Sie im Bibliotheksmodul die Fotos aus und dann **Bibliothek → Zusatzmoduloptionen → Facet: Apply ratings and flags...**
3. Verweisen Sie im Dialog auf `facet_manifest.json`. Der Pfad wird gemerkt.
4. **Wenn Facet auf einem anderen Rechner gescannt hat, tragen Sie die beiden Pfad-Präfixe ein.** Das Manifest enthält die Pfade des scannenden Rechners (z. B. `/volume1/photos/...` auf einem NAS), Lightroom dagegen die des Arbeitsplatzes (z. B. `Z:\photos\...`). Geben Sie das Lightroom-Präfix und das Facet-Präfix für denselben Ordner an. Lassen Sie beide leer, wenn die Pfade übereinstimmen. Sind sie falsch, wird nichts zugeordnet.
5. Wählen Sie den Umfang: die ausgewählten Fotos (Standard) oder den ganzen aktuellen Ordner.
6. Klicken Sie auf **Preview...**. **Es wird noch nichts geschrieben.** Die Vorschau zeigt, wie viele Fotos zugeordnet wurden, wie viele nicht und was gesetzt würde. Wurde nichts zugeordnet, zeigt sie einen Beispielpfad aus Lightroom neben einem Beispielpfad aus dem Manifest, damit Sie die Präfixe korrigieren können.
7. Klicken Sie auf **Apply**. Sie können während des Fortschritts abbrechen. Eine Zusammenfassung zeigt, was gesetzt, übersprungen und nicht gefunden wurde.

**Was es schreibt** (nie in Ihre Bilddateien):

| Facet-Status | Lightroom-Feld |
|---|---|
| `star_rating` 1-5 | Sternebewertung |
| Favorit | Pick-Flag |
| abgelehnt | Ablehnen-Flag |

Eine Facet-Sternebewertung von 0 bedeutet „keine Meinung“ und wird nie geschrieben.

**Überschreibregel.** Standardmäßig setzt das Zusatzmodul eine Bewertung nur bei einem Foto, das in Lightroom *unbewertet* ist, und ein Flag nur bei einem *ungeflaggten*. Ihre eigenen Bewertungen und Flags bleiben erhalten und werden als „kept as they are“ gezählt. Setzen Sie das Häkchen bei **Overwrite ratings and flags that are already set in Lightroom**, um sie zu ersetzen. Der Sidecar-Export folgt derselben Regel (`xmp_export.score_to_rating.only_when_unrated`, Standard `true`).

**Dialogoptionen** (standardmäßig alle aus, werden zwischen Läufen gemerkt):

- **Fill in star ratings from Facet scores for photos you have not rated** — hat das Manifest keine `star_rating` (oder 0), wird der `aggregate`-Score auf Sterne abgebildet. Dieser Ersatz **überschreibt nie eine vorhandene Lightroom-Bewertung, auch nicht mit angehaktem Overwrite.**
- **Pick the recommended frame of each burst** — in jeder Serien-Gruppe mit mindestens 2 Mitgliedern wird jedes als `is_burst_lead` markierte Mitglied auf Pick gesetzt (eine Serie kann mehr als eines behalten). Einzelbilder und Gruppen ohne Führungsbild werden übersprungen. Ihre eigenen Pick-/Reject-Flags und Facet-Favoriten/-Ablehnungen haben immer Vorrang.
- **Reject the other frames** (nur zusammen mit der Pick-Option) — lehnt jedes Serien-Mitglied ab, das nicht Führungsbild ist. Mitglieder eines Brackets, Panoramas oder HDR-Panoramas werden nie abgelehnt, und Gruppen ohne Führungsbild erhalten keine Ablehnungen.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — legt für jede Gruppe mit mindestens 2 zugeordneten Fotos im Umfang eine Sammlung unter `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` oder `Facet › HDR panoramas` an oder verwendet sie wieder.
  - Name: `<yyyy-mm-dd HH:MM:SS> – <filename>` des frühesten Mitglieds, oder `~ (no date) – <filename>`, wenn es keine Aufnahmezeit hat.
  - Eine Serie, deren Mitglieder alle zu einem Bracket- oder Panorama-Set gehören, erhält keine eigene Bursts-Sammlung.
  - **Erneutes Ausführen fügt nur Fotos hinzu.** Ein Foto, das später ein Set verlässt, bleibt in seiner Sammlung.
  - Bekannte Einschränkung: Zwei Gruppen, deren früheste Mitglieder dieselbe Aufnahmesekunde und denselben Dateinamen teilen (z. B. zwei Kameras, die `IMG_0001` schreiben), teilen sich eine Sammlung.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (nur mit der obigen Option) — leert und befüllt eine Sammlung neu, aber nur, wenn die Sammlung und ihre ganze Gruppe im aktuellen Umfang liegen. Teilweise abgedeckte Sammlungen und intelligente Sammlungen werden übersprungen.
    - Es leert und löscht auch die Sammlung einer Gruppe, die sich in diesem Lauf aufgelöst hat, aber nur, wenn jedes Foto darin von diesem Lauf zugeordnet wurde.
    - Es berührt nur Sammlungen, deren Name Facets eigenes Format hat (Datum und Uhrzeit oder `~ (no date)`, dann ` – <filename>`). Von Ihnen selbst benannte Sammlungen bleiben unangetastet.
    - Die Vorschau zeigt eine Zeile `Facet collections to delete: N`, wenn etwas zu löschen ist. Die Zusammenfassung meldet neu aufgebaute, gelöschte, übersprungene und fehlgeschlagene Sammlungen.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — schreibt den Aggregat-Score (z. B. `8.4`), eine ganze Punktebreite (`0`-`10`), die Kategorie und die Set-Art in Facets eigene Metadatenfelder. Sie erscheinen im Metadaten-Panel und funktionieren als Text-Kriterien (`sdktext:`) im Bibliotheksfilter und in intelligenten Sammlungen, z. B. Punktebreite „eine von 8, 9, 10“. Ein Feld, das nicht mehr zutrifft, wird gelöscht. Zwei versteckte Buchhaltungsfelder (die von diesem Lauf abgeleitete Bewertung und der Pick) werden ebenfalls geschrieben; sie sind von der Suche ausgeschlossen, in manchen Lightroom-Classic-Versionen aber möglicherweise trotzdem sichtbar (nicht verifiziert).
- **Create "Facet" keywords from Facet tags (never included on export)** — legt ein Wurzel-Stichwort `Facet` mit einem Kind pro Tag an (KI- und [manuelle Tags](#manuelle-tags-und-xmp-stichwörter)). Die `Facet ›`-Kinder jedes Fotos werden an seine Tags angepasst; ein in Facet entferntes Tag verschwindet daher beim nächsten Apply. `Include on Export` ist für alle deaktiviert, sodass sie nie in Exporte oder Kundengalerien gelangen. Ihre Stichwörter außerhalb der `Facet`-Wurzel werden nie geändert. Ein vorhandenes Stichwort `Facet` auf oberster Ebene wird als Wurzel übernommen, und jedes Kind, das Sie selbst darunter angelegt haben, wird entfernt.

**Warum Sammlungen statt Stapel.** Lightrooms SDK kann keine Stapel (Stacks) erstellen. Um die Fotos einer Sammlung zu stapeln, wählen Sie sie aus und nutzen **Foto → Stapeln → Zu Stapel gruppieren** (Strg/Cmd+G).

**Grenzen:**

- **Pick-Flags bleiben im Katalog.** Lightroom schreibt sie nie ins XMP, daher sieht keine andere Anwendung sie, und ein Neuaufbau des Katalogs aus den Dateien verliert sie. Sternebewertungen überleben über **Metadaten → Metadaten in Datei speichern**.
- **Keine numerischen intelligenten Sammlungen auf Facet-Feldern.** Zusatzmodul-Felder sind nur Text (`sdktext:`); die numerischen Operatoren (`>`, `<`, „liegt im Bereich“) funktionieren nur bei Lightrooms eingebauten Feldern. Nutzen Sie das Punktebreite-Feld oder die Ersatz-Option für Sternebewertungen, die Lightroom numerisch sortiert und filtert.
- **Rückgängig** nimmt mit jedem Strg/Cmd+Z einen Block von 200 Fotos zurück.
- Setzen Sie das Häkchen bei **Write facet-apply.log next to the manifest**, um zu protokollieren, welche Pfade zugeordnet wurden und was geschrieben wurde.

### Lightroom → Facet

**Bewertungen, Picks und Ablehnungen — Lightroom gewinnt (über das Zusatzmodul).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** öffnet einen Speicherdialog. Die Datei enthält einen Datensatz pro Foto: `path`, sowie `rating`/`pick`, wenn sie übertragen werden müssen.
2. Importieren Sie sie mit `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` ist bei einer Mehrbenutzer-Installation erforderlich) oder über **Import Lightroom state…** im Dialog **Export to editor** der Galerie.

Lightrooms Wert gewinnt für jedes Feld eines Datensatzes. Der Import meldet die Zählungen `matched`/`unmatched`/`changed`.

| Lightroom-Status | Facet-Ergebnis |
|---|---|
| Pick-Flag = Ausgewählt (`pick = 1`) | Favorit = an, abgelehnt = aus |
| Pick-Flag = Abgelehnt (`pick = -1`) | Favorit = aus, abgelehnt = an |
| Pick-Flag = keins (`pick = 0`) | Favorit = aus, abgelehnt = aus |
| Sternebewertung (`rating`, 0-5) | `star_rating` (`0` löscht sie) |

- Ein Datensatz ohne `rating` oder `pick` lässt den entsprechenden Facet-Wert unberührt. Der Export enthält ein Feld nur, wenn sich Lightrooms Wert von dem unterscheidet, was das letzte Apply gesetzt hat; ein unberührtes Foto ändert daher nichts.
- Virtuelle Kopien werden vor dem Export in ihr Original zusammengeführt.
- Ein erfolgreicher Import, der etwas ändert, aktualisiert die Trainingspaare und stößt wie jede Bewertungsänderung das automatische Neutrainieren an.

> **Warnung:** Da Lightroom gewinnt, löscht ein Foto, das der Apply-Schritt nie berührt hat und das in Lightroom unbewertet und ungeflaggt ist (`pick = 0`, kein `rating`), beim Import seine Facet-Sternebewertung, seinen Favoriten und seine Ablehnung.

**Bewertungen, Labels und Stichwörter über XMP** (Einbahnstraße):

1. Wählen Sie in Lightroom die Fotos aus und wählen Sie **Metadaten → Metadaten in Datei speichern** (Strg/Cmd+S). Dadurch werden Bewertung, Label und Stichwörter in das XMP-Sidecar (RAW) oder in die Datei (DNG/JPEG/PSD/TIFF) geschrieben.
2. `python facet.py --import-sidecars /path --sidecar-naming basename` liest die RAW-Sidecars. Geteilte RAW/JPEG-Basisnamen werden abgelehnt. Dieser Befehl liest keine eingebetteten Metadaten. Importierte Stichwörter werden manuelle Tags.

### Konfliktregeln

- **Tags und Stichwörter werden standardmäßig zusammengeführt.** Exporte ergänzen Facet-Stichwörter; `--reconcile-keywords` entfernt zusätzlich veraltete Facet-eigene Namen. Importe ergänzen manuelle Tags und ersetzen nie KI-Tags. Siehe [Manuelle Tags und XMP-Stichwörter](#manuelle-tags-und-xmp-stichwörter).
- **Mehrbenutzerbetrieb** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): Bewertungen gehen in Alices eigene Bewertungen (`user_preferences`) statt in die globalen. Stichwörter sind immer global: Manuelle Tags werden geteilt.
- Importierte Stichwörter landen in `photo_manual_tags`, das die Tag-Filter direkt lesen. Nach `--import-sidecars` ist kein `python database.py --migrate-tags` nötig.

## Capture One

Capture One hält seine Einstellungen in `.cos`-Dateien (Sessions) oder in seinem Katalog. Sein Modus „Full Sync“ bei **Sync Metadata** kann die Seite überschreiben, die zuletzt geschrieben hat, sodass eine bidirektionale Schleife Änderungen verlieren kann. Verwenden Sie **Einbahnstraße, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. Belassen Sie in Capture One **Preferences → General → Sync Metadata** auf dem Standardwert (nicht „Full Sync“).
3. Wählen Sie die Bilder aus, klicken Sie mit der rechten Maustaste und wählen Sie **Load Metadata**, um Bewertung, Label und Stichwörter einmalig zu übernehmen.

Arbeiten Sie danach ohne automatische Synchronisierung in Capture One weiter. Um gespeichertes XMP zurück in Facet zu holen, führen Sie `--import-sidecars /path/to/shoot --sidecar-naming basename` für RAW-Sidecars ohne Bildendung aus, oder `full` für vollständige Dateinamen. Geteilte RAW/JPEG-Basisnamen werden abgelehnt. Das liest Sidecars, keine eingebetteten Metadaten.

## digiKam

Die [Sidecar-Einstellungen von digiKam](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) verwenden eine Benennung: standardmäßig `filename.ext.xmp`, oder `filename.xmp`, wenn **Sidecar file names are compatible with commercial programs** aktiviert ist. Beide werden nicht probiert.

- **Facet → digiKam:** Verwenden Sie die Einstellung mit vollständigem Namen, aktivieren Sie **Read from sidecar files**, lesen Sie die Metadaten aus den Dateien neu ein und prüfen Sie die Felder.
- **digiKam → Facet:** Übergeben Sie `--sidecar-naming full` oder `basename`, passend zu Ihrer digiKam-Einstellung.

Sterne, Farblabels und Pick-Flags bedeuten in jeder Anwendung etwas anderes, prüfen Sie das Ergebnis also.

### Batch-Queue-Manager-Hook

Sie können einen Facet-Import über das Werkzeug **Custom Script** im digiKam Batch Queue Manager (BQM) ausführen. Aktivieren Sie zuerst das Schreiben von Sidecars, speichern Sie die Namenseinstellung und übernehmen Sie ausstehende Metadatenänderungen (digiKam kann Schreibvorgänge verzögern). Das Beispiel setzt Sidecars mit vollständigem Namen voraus; verwenden Sie `basename` nur für eine Sammlung ohne geteilte Basisnamen:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sind digiKams Platzhalter pro Datei. BQM erwartet eine Ausgabedatei, daher das `cp`. `--import-sidecars` durchsucht den ganzen Ordner, daher ist die Ausführung pro Foto redundant, aber harmlos. Führen Sie bei großen Chargen einmal `python facet.py --import-sidecars /path/to/folder` aus, nachdem die Queue abgeschlossen ist.

## darktable

Siehe [Konfiguration — Viewer](CONFIGURATION.md#viewer) (Export-Profile und -Stile `viewer.raw_processor.darktable`) und [Viewer — Download](VIEWER.md#download) (Konvertierungen `type=darktable`).

darktable speichert seinen Bearbeitungsverlauf in seinem eigenen `<bild><ext>.xmp`. Facets ExifTool-Writer führt in diese Datei zusammen und erhält `darktable:history` und die Masken-Knoten. Das oben beschriebene Sidecar-Verhalten für Lightroom (Export/Import, neueste gewinnt, Tag-Vereinigung) gilt unverändert, und es gibt keine RAW-Namensabweichung: Beide verwenden `<bild><ext>.xmp`.

**ExifTool-Version:**

- **13.28 oder neuer** wird empfohlen.
- Gesichtsänderungen benötigen **12.65 oder neuer**. Ältere oder unbekannte Versionen überspringen sie mit Warnung und exportieren den Rest.
- **13.23 bis 13.27** beschädigen Sidecars mit darktable-Verlauf, daher verweigert Facet das Schreiben mit ihnen und bittet um ein Upgrade. Das Docker-Image pinnt eine sichere Version. Distributionspakete tun das möglicherweise nicht (das Paket `libimage-exiftool-perl` von Debian trixie ist 13.25).

> **Warnung:** darktable selbst kann den Bearbeitungsverlauf löschen, wenn ein bereits bearbeitetes Bild erneut importiert wird: Es kann den Verlauf des Sidecars mit einem leeren überschreiben. Das ist ein offener Upstream-Bug ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), gemeldet am 2026-03-15), und die Einstellung „check for new/updated xmp files on start“ verhindert ihn nicht. Importieren Sie nach `--export-sidecars` einen bearbeiteten Ordner nicht pauschal neu. Laden Sie nur die Bilder neu, die Facet angefasst hat, und prüfen Sie zuerst ihren Verlauf.

## Manuelle Tags und XMP-Stichwörter

Facet hält die Tags, die Sie eingeben (siehe [Web-Galerie — Manuelle Tags](VIEWER.md#manuelle-tags)), in `photo_manual_tags`, getrennt von den KI-Tags in `photos.tags`. Ein erneuter Scan oder ein erneutes Tagging berührt sie nie.

- **Export.** Jeder Stichwort-Schreiber gibt zuerst die KI-Tags aus, dann die manuellen Tags, dann Personennamen, ohne Beachtung der Groß-/Kleinschreibung dedupliziert. Das gilt für `--export-sidecars`, die XMP-Export- und „Metadaten in Datei schreiben“-Aktionen der Galerie sowie das Lightroom-Manifest (`--export-manifest`, `/api/lightroom/manifest`).
- **Import.** `--import-sidecars` liest flache Stichwörter aus `dc:subject` und Hierarchiepfade getrennt aus `lr:hierarchicalSubject`. Flache Stichwörter werden wie eingegebene Tags normalisiert: getrimmt, kleingeschrieben, höchstens 64 Zeichen, 50 manuelle Tags pro Foto. Jedes wird zu einem manuellen Tag mit der Quelle `xmp`, außer es
  - ist bereits eines der KI-Tags oder einer der Personennamen des Fotos,
  - dupliziert einen ausdrücklich in `lr:hierarchicalSubject` enthaltenen Pfad,
  - enthält ein Komma oder Steuerzeichen oder
  - würde die Obergrenze überschreiten.
- **Entfernen von Stichwörtern ist ausdrücklich.** Exporte ergänzen standardmäßig nur. `--export-sidecars /path --reconcile-keywords` (benötigt ExifTool) entfernt außerdem Namen, die Facet früher geschrieben hat und die in Facet nicht mehr vorkommen. Stichwörter, die Facet nie geschrieben hat, werden nie entfernt, auch bei gleichem Namen, und alte Sidecars ohne Markierung geben Facet keinen Besitz. Fügen Sie ein entferntes Stichwort in einem anderen Editor wieder hinzu, kann Facet es erneut importieren und behandelt es danach als fremd. Stichwörter bleiben auch mit `--user` gemeinsam.
- **Facets Stichwörter gewinnen beim Export.** Ein weiterhin in Facet vorhandenes Stichwort wird zurückgeschrieben, auch wenn ein anderer Editor es aus der Datei entfernt hat. Um es dauerhaft zu entfernen, entfernen Sie das Tag in Facet. Der Abgleich löscht nie Tags aus Facet.
- Namen wie `2024`, `1.50`, `1e3`, `true`, `false` und `null` behalten ihre Schreibweise.
- Kann Facet die Metadaten einer vorhandenen Datei nicht lesen, stoppt der Export vor dem Schreiben.
- **Das Lightroom-Manifest gibt Entfernungen dagegen weiter.** Die Stichwort-Option des Zusatzmoduls schreibt bei jedem Apply die `Facet ›`-Kinder jedes Fotos neu.
- **KI-Tags bleiben KI-Tags.** Sidecars halten fest, welche Stichwörter KI und welche manuell waren, sodass ein erneutes Tagging ein altes KI-Stichwort nicht zu einem manuellen Tag macht. Sidecars älterer Facet-Versionen behalten das alte additive Verhalten.
- **Hierarchien.** Importierte Pfade werden der gemeinsamen Schlagworthierarchie hinzugefügt; flache Namen mit `|` oder `/` erzeugen allein keine Hierarchie. Als von Facet erzeugt markierte Pfade werden nicht als manuelle Zuweisungen importiert, sofern sie nicht zugleich als manuell markiert sind. Ein Sidecar von Facet 1.28 oder älter trägt `facet:KeywordState`, aber kein `facet:HierarchyState`; seine `Category|`- und `People|`-Pfade gelten als erzeugt und werden übersprungen, auch von Hand eingegebene, und jeder übersprungene Pfad erscheint in der Importvorschau als `legacy_generated_path`. Exporte enthalten explizite Zuweisungen und erzeugte Kategorie-/Personenpfade. Der Export fügt standardmäßig hinzu; `--reconcile-keywords` entfernt nur veraltete Facet-eigene Pfade und bewahrt fremde Pfade.
- **Besitzgrenzen:** 10.000 Namen pro Liste und 1.024 Zeichen pro Name. Ein Export, der sie überschreiten würde, stoppt vor dem Schreiben. Archivieren und bereinigen Sie ein solches Sidecar von Hand, bevor Sie neu beginnen.
- **Von einer älteren Facet-Version importierte Stichwörter bleiben, wo sie sind.** Ältere Versionen führten Stichwörter in `photos.tags` zusammen, wo sie wie KI-Tags aussehen, und keine Migration verschiebt sie. Um eines in ein manuelles Tag umzuwandeln, leeren oder taggen Sie `photos.tags` neu und führen dann `--import-sidecars` erneut aus — oder fügen Sie das Tag von Hand hinzu.
- **Verschobene oder umbenannte Dateien.** Manuelle Tags sind an den Katalogpfad gebunden. Nach dem eigenen Verschieben aktualisiert der geprüfte [Neu-Verknüpfungsablauf](RELINK.md) diesen Pfad und erhält die Tags; ein Scan am neuen Speicherort allein überträgt sie nicht.
- **`--export-csv` und `--export-json` bleiben auf KI beschränkt.** Ihr `tags`-Wert enthält keine manuellen Tags.

## Wie Facet zusammenführt

| Feld | Facet schreibt | Facet liest zurück | Konfliktregel |
|---|---|---|---|
| Bewertung (Sterne/Ablehnung) | `xmp:Rating` (`-1` = abgelehnt) | `xmp:Rating` | Bewertungszeitmarken; bisheriger Scan-Rückfall |
| Farblabel | `xmp:Label` (`Red` = abgelehnt, `Yellow` = Favorit) | `xmp:Label` | Bewertungszeitmarken; bisheriger Scan-Rückfall |
| Tags/Stichwörter | `dc:subject` (flach, KI-Tags + manuelle Tags, enthält Namen erkannter Personen) | `dc:subject` (als manuelle Tags gespeichert) | Standardmäßig additiv; `--reconcile-keywords` entfernt nur veraltete Facet-eigene Namen; Importe bleiben additiv ([Manuelle Tags und XMP-Stichwörter](#manuelle-tags-und-xmp-stichwörter)) |
| Hierarchische Tags | `lr:hierarchicalSubject` (explizite Zuweisungen und erzeugte Kategorie-/Personenpfade) | `lr:hierarchicalSubject` (Zuweisungen zur gemeinsamen Hierarchie) | Import fügt hinzu; Exportabgleich entfernt nur veraltete Facet-eigene Pfade |
| Bildunterschrift | `dc:description` Standardsprache (+ `IPTC:Caption-Abstract` über exiftool) | Nicht zurückimportiert | Nur Export |
| Benannte Gesichtsbereiche | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet` (zentriert-normalisiert, `Type=Face`) | Nicht zurückimportiert | Nur Export; nativ von digiKam gelesen, **nicht** von Lightroom (eine bekannte Adobe-Einschränkung — Lightroom liest nur MWG-Bereiche, die es selbst geschrieben hat) |

Siehe [Befehle — Vorschau & Export](COMMANDS.md#vorschau--export) für die vollständige CLI-Referenz (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**GPS-Löschungen.** Enthält ein Sidecar sowohl Standard-GPS-Felder als auch ein altes `facet:GPSState=cleared`, hat ein vollständiges gültiges Paar aus Breite und Länge Vorrang. Ein unvollständiges oder ungültiges Paar wird ignoriert und löscht nie einen Ort. Nur ein fehlendes oder leeres Paar plus die Löschmarkierung löscht GPS. Manuelles GPS bleibt geschützt, sofern Sie das Überschreiben nicht verlangen.

**Beschriftungen.** Mit ExifTool aktualisiert der Export nur die Standardsprache (`x-default`) von `dc:description` und behält andere Sprachen. Eine leere Facet-Beschriftung lässt vorhandene Beschriftungen unverändert. Ohne ExifTool schreibt Facet eine Beschriftung in der Standardsprache und, wenn ein Editor-Sidecar existiert, stattdessen nach `<image>.facet.xmp`.

**Gesichtsregionen.** Mit ExifTool ersetzt der Export nur MWG-Rechtecke, die mit `facet:RegionOwner=Facet` markiert sind.

- Unmarkierte Regionen, auch die älterer Facet-Versionen, bleiben erhalten. Nach einem Upgrade können ein altes unmarkiertes Gesicht und seine neue markierte Kopie beide erscheinen, und beim Löschen von Gesichtern bleibt das alte.
- Wiederholte Exporte ersetzen die markierten Kopien; sie häufen sich nicht an.
- Weichen die Bildabmessungen von denen ab, auf denen die vorhandenen Regionen gezeichnet wurden (oder sind unbekannt), werden Gesichtsänderungen mit Warnung übersprungen. Bewertung, Label, Stichwörter und GPS werden trotzdem exportiert.
- Unlesbare oder ungültige Gesichtsmetadaten stoppen einen Einzelfoto-Export oder das Einbetten vor dem Schreiben.
- Der Ersatz-Writer (ohne ExifTool) exportiert keine Gesichtsrechtecke.
- Eine markierte Region, die Sie anderswo bearbeiten, gehört weiterhin Facet. Entfernen Sie ihre Besitzmarkierung, um sie als Ihre eigene zu behalten.

> **Warnung:** Schreibvorgänge in getrennte Dateien sind nicht atomar. Ein E/A-Fehler oder eine äußere Änderung während des Exports kann einige Dateien aktualisiert und andere nicht hinterlassen.

Schlägt die Prüfung der ExifTool-Version fehl, wiederholt Facet sie beim nächsten Mal. Solange die Version unbekannt ist, werden Gesichtsregionen übersprungen und der Rest exportiert. Bekannt fehlerhafte Versionen werden immer abgelehnt.

## Sidecar-Importvorschau und Konflikte

Führen Sie `--import-sidecars /path --dry-run` aus, um vor dem Schreiben den JSON-Plan zu sehen: das gewählte Sidecar, Vorher/Nachher-Felder, hinzuzufügende Stichwörter, Quellzeit sowie Überspringungs- und Konfliktgründe. Die Vorschau öffnet die Datenbank schreibgeschützt und ändert sie nie. Anwenden liest alles erneut, die Vorschau ist also kein Token zum Wiederverwenden.

Fehlt die Datenbank, ist sie nicht lesbar oder ungültig, endet die Vorschau mit Exitcode 1 und erstellt oder repariert sie nicht. `--dry-run-count` begrenzt nur Scan-Stichproben, nicht Importvorschauen.

`--sidecar-fields review,gps,keywords` wählt, welche Gruppen importiert werden; lassen Sie eine Gruppe weg, um sie zu überspringen.

- **review** importiert Sterne, Favorit, Ablehnung und Behalten zusammen, sodass ein Konflikt nie eine halbe Entscheidung anwendet.
- **gps** behält manuelle Orte, sofern nicht `--overwrite-manual-gps` angegeben ist.
- **keywords** sind additiv und gemeinsam, auch mit `--user`.

**Änderungszeitmarken.** Facet hält fest, wann jedes Bewertungsfeld zuletzt geändert wurde, je Foto und Konto, einschließlich Zurücksetzungen. Ein Sidecar, das älter als diese Änderung ist, ist ein Konflikt `newer_local_edit`, und diese Bewertungsgruppe bleibt unverändert. `--overwrite-sidecar-review` hebt dies und die Scanzeit-Prüfung auf. Eine Quelle `local` bedeutet einen unbekannten Schreiber, nicht unbedingt eine Person. Beschriftungen, Gesichter und unmarkiertes externes GPS werden nie importiert.

- Felder, die geändert wurden, bevor Facet Änderungen aufzeichnete, haben keine bekannte Änderungszeit. Es gilt die Scanzeit-Regel, gemeldet als `untracked_legacy_edit`.
- Die Vorschau öffnet auch ältere Datenbanken ohne Upgrade; ein fehlendes Behalten-Feld gilt als unentschieden.
- Die Zeit des Sidecars ist `xmp:MetadataDate`, oder die Änderungszeit der Datei, wenn sie fehlt oder ungültig ist.
- Die Details listen die ersten 1.000 Fotos im Umfang und 100 Hinweise pro Foto auf, mit Zählungen des Ausgelassenen.

Änderungszeitmarken bleiben in ihrer eigenen Datenbank. Ein frischer Viewer-Export kopiert keine Scanner-Zeitmarken oder Sidecar-Pfade. Ein inkrementeller Export behält die eigenen Zeitmarken des Viewers, sodass im Viewer vorgenommene Zurücksetzungen (einschließlich gelöschter Benutzerbewertungen) erhalten bleiben. Scanner-Werte, die der Viewer nie bearbeitet hat, werden weiter aktualisiert.

> **Warnung:** Eine Viewer-Datenbank aus einem unveröffentlichten Build vor 1.24.0 kann kopierte Scanner-Zeitmarken enthalten. Sie zählen nun als Viewer-Änderungen, sodass diese Felder Scanner-Updates nicht mehr folgen. Sichern und prüfen Sie diese Datenbank vor einem Neuaufbau: Ein vollständiger Neuaufbau verwirft lokale Viewer-Änderungen.
