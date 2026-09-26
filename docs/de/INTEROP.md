# Editor-Interop-Rezepte

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · **Deutsch** · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Praktische Schritt-für-Schritt-Rezepte, um Facets Bewertungen, Labels und Tags mit den externen Editoren und DAM-Tools auszutauschen, die tatsächlich verwendet werden. Diese Seite setzt voraus, dass Sie bereits wissen, *dass* Facet XMP schreibt — siehe [Befehle — Vorschau & Export](COMMANDS.md#preview--export) für die vollständige Referenz der Optionen `--export-sidecars` / `--import-sidecars` und die Feldzuordnung (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## Die RAW-Sidecar-Namensfalle

Facet benennt ein Sidecar `<bild><ext>.xmp` — z. B. `IMG_1234.CR2.xmp` neben `IMG_1234.CR2` — dieselbe Konvention, die darktable und digiKam verwenden. **Lightroom Classic und Capture One erwarten das Gegenteil: `IMG_1234.xmp`, ohne die RAW-Dateiendung.** Keine der beiden Anwendungen findet ein von Facet geschriebenes Sidecar für eine proprietäre RAW-Datei (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — alles außer DNG), und Facets eigenes `--import-sidecars` findet umgekehrt auch kein Sidecar, das eine Anwendung aus dem Adobe-Ökosystem für dieselbe RAW-Datei geschrieben hat. Es handelt sich um eine zwischen den Ökosystemen nicht übereinstimmende Namenskonvention, nicht um einen Fehler auf einer der beiden Seiten.

Betroffen sind **nicht**:
- **JPEG, HEIC, TIFF, PNG, DNG** — übergeben Sie `--embed-originals`, und Facet schreibt die Metadaten *direkt in die Datei* (über exiftool), sodass es keinen Sidecar-Namen gibt, den Lightroom/Capture One übersehen könnten.
- **digiKam** — prüft beide Namenskonventionen und findet Facets Sidecar in jedem Fall (siehe [digiKam](#digikam) weiter unten).
- **darktable** — verwendet dieselbe Konvention `<bild><ext>.xmp` wie Facet (siehe [darktable](#darktable) weiter unten).

**GIF, WebP, BMP und AVIF sind die Ausnahme — sie trifft die Diskrepanz am härtesten.** Sie liegen außerhalb von Facets einbettbarer Menge, `--embed-originals` bewirkt für sie also nichts, und ihr einziges Roundtrip-Vehikel ist ein XMP-Sidecar mit Facets Namensschema (`photo.webp.xmp`). Die oben beschriebene Diskrepanz gilt für diese vier daher genauso wie für proprietäre RAW-Dateien: digiKam und darktable finden das Sidecar, Lightroom Classic und Capture One nicht.

Für einen Lightroom- oder Capture-One-Workflow gilt also: Verwenden Sie `--embed-originals` für alles aus der einbettbaren Menge (JPEG, HEIC, TIFF, PNG, DNG), und rechnen Sie damit, dass der Sidecar-Roundtrip bei proprietären RAW-Dateien — und bei GIF, WebP, BMP und AVIF — stillschweigend nichts bewirkt (kein Fehler, es wird einfach nichts gelesen). Wenn Sie in RAW+JPEG fotografieren, ist die begleitende JPEG-Datei das praktische Interop-Vehikel — die RAW-Datei bleibt unverändert auf der Festplatte liegen, während Facets Datenbank die maßgebliche Bewertung führt.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (fügen Sie einen Pfad hinzu, um den Umfang einzugrenzen, z. B. `--export-sidecars /fotos/hochzeit-2026`). Fügen Sie `--embed-originals` hinzu, um zusätzlich direkt in JPEG-/HEIC-/TIFF-/PNG-/DNG-Dateien zu schreiben.
2. Wählen Sie im Bibliotheksmodul von Lightroom Classic die Fotos aus (Strg/Cmd+A für alle) und wählen Sie **Metadaten → Metadaten aus Datei lesen**. Lightroom überschreibt Bewertung, Farblabel und Stichwörter seines Katalogs aus dem Sidecar (oder den eingebetteten Metadaten, für die oben genannten Formate).

Facets Ablehnungsmarker (`xmp:Rating = -1`) wird beim Zurücklesen als Lightrooms Ablehnen-Flag interpretiert. Ein Facet-Favorit schreibt `xmp:Label = Yellow`, was Lightroom als **gelbes Farblabel** anzeigt — nicht als Pick-Flag. Wenn Ihr Lightroom-Workflow auf Pick-Flags statt auf Farblabels basiert, fügen Sie einen Umwandlungsschritt Farblabel → Pick hinzu, oder filtern Sie stattdessen nach dem gelben Label.

Ein `python facet.py --export-manifest`-Feed (Pfad, Kategorie, alle Scores, Tags und dieselben Bewertungsspalten wie `--export-sidecars` — einschließlich benutzerbezogener Bewertungen über `--export-manifest --user alice` auf einer Mehrbenutzer-Installation) existiert jetzt für Werkzeuge, die Facets Daten ohne XMP-Parsing wollen — siehe [Befehle — Vorschau & Export](COMMANDS.md#preview--export). Genau diesen Feed liest das unten beschriebene Facet-Zusatzmodul.

**Manifest Version 2.** Das Manifest trägt jetzt zusätzlich `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` und eine übergeordnete Zählung `pending_corrections` (manuelle Bracket-/Panorama-Korrekturen, die von einem Erkennungslauf noch nicht angewendet wurden — führen Sie `--detect-panoramas` erneut aus). Das Zusatzmodul nutzt die Felder pro Foto für die Serien-Auswahl/Ablehnungs- und Sterne-Ersatz-Optionen unten und zeigt `pending_corrections` als Warnzeile in seiner Vorschau, damit Sie wissen, dass ein erneuter Lauf der Erkennung noch ändern kann, welche Aufnahmen führend sind. Es gibt keinen abwärtskompatiblen Lesepfad: Ein für Version 2 gebautes Zusatzmodul weist ein Version-1-Manifest rundweg zurück, mit einem Dialog, der Sie zum erneuten Export aufruft, und ein älteres Zusatzmodul kann ein Version-2-Manifest ebenfalls nicht lesen. Sehen Sie diesen Dialog, führen Sie einfach `--export-manifest` erneut aus.

Im Viewer bietet der Dialog **Export to editor** der Galerie dasselbe Manifest über einen Button **Download Lightroom manifest** an, eingegrenzt auf dieselbe Auswahl/denselben Filter wie der danebenliegende Sidecar-Export — siehe [Editor Export](VIEWER.md#editor-export). Er schreibt genau dieselbe `facet_manifest.json`-Form wie `--export-manifest`, sodass der Zusatzmodul-Dialog unten unabhängig davon funktioniert, welche Seite die Datei erzeugt hat.

### Das Facet-Zusatzmodul (Sternebewertungen, Pick-Flags, Metadatenfelder und Stichwörter)

`facet.lrplugin/` im Facet-Repository ist ein Lightroom-Classic-Zusatzmodul (Plug-in), das Facets Sternebewertung und den Favorit-/Ablehnungs-Status **direkt in den Katalog** schreibt. Es existiert, weil zwei der oben genannten Punkte von der XMP-Seite aus nicht zu lösen sind: Lightroom findet für eine proprietäre RAW-Datei nie ein Facet-Sidecar, und XMP hat überhaupt keinen Kanal für Lightrooms Pick-Flag. Das Zusatzmodul liest eine Manifestdatei, spricht also nie mit dem Facet-Server, braucht kein Passwort und funktioniert auch, wenn Facet nicht läuft — und weil es Fotos über den Pfad statt über Sidecars zuordnet, **verhält sich eine reine RAW-Bibliothek genau wie eine JPEG-Bibliothek**.

Das Zusatzmodul registriert zwei Einträge unter **Bibliothek → Zusatzmoduloptionen** (**Library → Plug-in Extras**): **Facet: Apply ratings and flags...** (die Richtung Manifest → Katalog, in diesem Abschnitt beschrieben) und **Facet: Export Lightroom State to Facet...** (die umgekehrte Richtung — siehe [Lightroom → Facet](#lightroom--facet) unten).

**Installation** (einmalig):

1. Kopieren Sie den Ordner `facet.lrplugin` auf den Rechner, auf dem Lightroom läuft. Unter macOS vorher zippen — der Finder behandelt einen `.lrplugin`-Ordner als Paket.
2. In Lightroom Classic: **Datei → Zusatzmodul-Manager → Hinzufügen**, den Ordner `facet.lrplugin` auswählen, dann **Fertig**.

**Verwendung** (jedes Mal, wenn Facets Urteil in den Katalog soll):

1. `python facet.py --export-manifest /fotos/hochzeit-2026` (der Pfad grenzt den Export ein; die Datei landet immer als `facet_manifest.json` im aktuellen Verzeichnis). Kopieren Sie sie auf den Lightroom-Rechner, falls Facet anderswo läuft.
2. Wählen Sie im Bibliotheksmodul die Fotos aus und dann **Bibliothek → Zusatzmoduloptionen → Facet: Apply ratings and flags...** (die Oberfläche des Zusatzmoduls ist englisch).
3. Verweisen Sie im Dialog auf `facet_manifest.json`. Der Pfad wird für das nächste Mal gemerkt.
4. **Wenn Facet die Fotos von einem anderen Rechner aus gescannt hat, tragen Sie die beiden Pfad-Präfixe ein.** Das Manifest enthält die Pfade des scannenden Rechners (`/volume1/photos/...` auf einem NAS), Lightroom dagegen die des Arbeitsplatzes (`Z:\photos\...`). Geben Sie das Lightroom-Präfix und das Facet-Präfix an, die denselben Ordner bezeichnen; lassen Sie beide leer, wenn sie übereinstimmen. Das ist der einzige Fehler beim ersten Lauf, der wirklich zählt — er führt schlicht dazu, dass nichts zugeordnet wird.
5. Wählen Sie den Umfang: die ausgewählten Fotos (Standard) oder alle Fotos des aktuellen Ordners.
6. Klicken Sie auf **Preview...** (Vorschau). **Es wird noch nichts geschrieben.** Das Zusatzmodul meldet, wie viele Fotos es im Manifest gefunden hat, wie viele nicht, und wie viele Bewertungen und Flags es setzen würde. Steht die Trefferzahl auf 0, zeigt es einen Beispielpfad aus Lightroom neben einem Beispielpfad aus dem Manifest, damit Sie sehen, wie die Präfixe lauten müssen.
7. Klicken Sie auf **Apply** (Anwenden). Der Fortschritt wird angezeigt und lässt sich abbrechen; ein Abschlussdialog meldet, was gesetzt, übersprungen und nicht gefunden wurde.

**Was es schreibt** — und sonst nichts, und nie in Ihre Bilddateien:

| Facet-Status | Lightroom-Feld |
|---|---|
| `star_rating` 1-5 | Sternebewertung |
| Favorit | Pick-Flag |
| abgelehnt | Ablehnen-Flag |

Eine Facet-Bewertung von 0 bedeutet „keine Meinung" (siehe `xmp_export.score_to_rating`) und wird nie geschrieben.

**Überschreib-Semantik** — standardmäßig widerspricht das Zusatzmodul Ihnen nie: Es setzt eine Sternebewertung nur, wenn das Foto in Lightroom *unbewertet* ist, und ein Flag nur, wenn das Foto *ungeflaggt* ist. Alles, was Sie von Hand bewertet oder geflaggt haben, bleibt unangetastet und wird in der Vorschau als „kept as they are" (unverändert belassen) gezählt. Setzen Sie das Häkchen bei **Overwrite ratings and flags that are already set in Lightroom**, um sie doch zu ersetzen. Das entspricht `only_when_unrated` in `xmp_export.score_to_rating`, sodass Zusatzmodul und Sidecar-Weg Ihre manuellen Änderungen gleich behandeln.

**Neue Dialogoptionen** (alle optional, jede wird für nächstes Mal gespeichert):

- **Fill in star ratings from Facet scores for photos you have not rated** — wenn ein Foto im Manifest keine `star_rating` hat (oder sie 0 ist), Facets `aggregate`-Score aber auf eine Sternezahl abbildet, füllt diese abgeleitete Bewertung die Lücke. Da dies ein Ersatz für ein *unbewertetes* Foto ist und keine echte Manifest-Bewertung, **überschreibt sie nie eine bereits vorhandene Lightroom-Bewertung — selbst wenn Overwrite angehakt ist.** Eine echte Manifest-`star_rating` folgt weiterhin unverändert der normalen Überschreib-Regel oben.
- **Pick the recommended frame of each burst** — für jede Serien-Gruppe mit mindestens 2 Mitgliedern im Manifest wird jedes Mitglied, das das Manifest als `is_burst_lead` markiert (eine Serie kann mehr als ein Bild behalten), auf Auswahl (Pick) gesetzt. Ein einzelnes Bild, das das Manifest nie mit Geschwistern gruppiert hat, wird von dieser Option nie berührt, und eine Serien-Gruppe ohne ein einziges `is_burst_lead`-Mitglied im gesamten Manifest wird komplett übersprungen (nichts, wovon abgeleitet werden könnte). Ein von Hand gesetztes Pick/Reject-Flag — oder ein Facet-Favorit/Ablehnung im Manifest — hat immer Vorrang vor dieser abgeleiteten Auswahl.
- **Reject the other frames** (verschachtelt unter der obigen Option, nur zusammen mit ihr aktivierbar) — setzt jedes Serien-Mitglied, das *nicht* die Führungsaufnahme ist, auf Ablehnung (Reject), mit zwei Ausnahmen: Ein Mitglied eines Belichtungsbrackets, Panoramas oder HDR-Panoramas wird durch diese Regel nie abgelehnt, unabhängig davon, dass seine `burst_group_id` es auch mit Geschwistern gruppiert — diese Sets werden vollständig erhalten; und eine Gruppe ohne Führungsaufnahme irgendwo im Manifest (siehe oben) erhält ebenfalls keine Ablehnungen.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — legt für jede Gruppe mit mindestens 2 passenden Fotos im aktuellen Umfang eine Sammlung namens `<yyyy-mm-dd HH:MM:SS> – <filename>` an oder findet eine wieder (Aufnahmezeit und Dateiname des frühesten Mitglieds; `~ (no date) – <filename>`, wenn dieses Mitglied keine Aufnahmezeit hat), verschachtelt unter `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` bzw. `Facet › HDR panoramas`. Eine einfache Serien-Gruppe, deren Mitglieder *alle* bereits vollständig zu einem Bracket-/Panorama-/HDR-Panorama-Set gehören, erhält keine eigene Bursts-Sammlung, da das die Sammlung unter Brackets/Panoramas/HDR panoramas nur doppeln würde. **Erneutes Ausführen fügt nur hinzu** — Fotos werden zu einer wiedergefundenen Sammlung ergänzt, aber nie entfernt, sodass eine Sammlung gegenüber einem später neu gruppierten oder neu erkannten Set veralten kann (ein aus einem Bracket entferntes Foto bei einem späteren Scan wird nicht aus der Sammlung entfernt). Sammlungsnamen kollidieren auch, wenn die frühesten Mitglieder zweier verschiedener Gruppen dieselbe Aufnahmezeit auf die Sekunde genau und denselben Dateinamen teilen — zwei Kameras, die beide `IMG_0001` zum selben Zeitpunkt geschrieben haben, teilen sich am Ende eine Sammlung statt jeweils eine eigene zu bekommen. Das ist eine bekannte Einschränkung, kein zu meldender Fehler.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (verschachtelt unter der obigen Option) — statt nur hinzuzufügen, leert und befüllt eine Sammlung neu, aber nur, wenn die Sammlung UND ihre gesamte Gruppe vollständig im Umfang dieses Laufs liegen; eine nur teilweise abgedeckte Sammlung (manche Mitglieder außerhalb der Auswahl) oder eine intelligente/nicht aufgelöste Sammlung bleibt unangetastet und wird als übersprungen gezählt, und die Zusammenfassung meldet, wie viele neu aufgebaut, gelöscht, übersprungen und fehlgeschlagen wurden. Sie erreicht auch eine Facet-Sammlung, deren Gruppe in diesem Lauf AUFGELÖST wurde (nicht mehr mindestens 2 Mitglieder im Umfang, also kein Planeintrag) — diese Sammlung wird ebenfalls geleert und gelöscht, aber nur, wenn jedes Foto darin von diesem Lauf gefunden wurde; eine Sammlung mit einem Foto außerhalb dieses Laufs bleibt unangetastet. Rebuild wird nur angeboten — und läuft nur — solange **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** aktiviert ist; das Deaktivieren dieser Option schaltet auch Rebuild ab. Der Durchlauf für aufgelöste Sammlungen berührt nur eine Sammlung, deren Name genau der von Facet selbst erzeugten Form entspricht (eine ISO-Datum-Uhrzeit oder das undatierte `~ (no date)`, gefolgt von ` – <filename>`), sodass eine von Ihnen selbst benannte Sammlung unter einer Facet-Menge nie geleert oder gelöscht wird. Hat der Durchlauf etwas zu löschen, fügt die Preview eine Zeile `Facet collections to delete: N` hinzu, und der Durchlauf läuft auch dann, wenn er die einzige anstehende Änderung ist, statt als „nichts zu ändern“ gemeldet zu werden.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — schreibt den `aggregate`-Score (z. B. `8.4`), eine ganze Punktebreite (`0`-`10`), die Kategorie und die Set-Art in Facets eigene Zusatzmodul-Metadatenfelder, sichtbar im Metadaten-Panel und nutzbar als Text-Kriterium (`sdktext:`) im Bibliotheksfilter/in intelligenten Sammlungen — etwa eine intelligente Sammlung, die die Punktebreite auf „eine von 8, 9, 10" abgleicht. Ein Feld, das nicht mehr auf ein Foto zutrifft (z. B. weil es einen Bracket verlassen hat und die Set-Art damit verschwunden ist), wird gelöscht statt veraltet stehen zu bleiben — sonst würde eine intelligente Sammlung oder ein Bibliotheksfilter-Kriterium auf Basis dieses Felds weiterhin ein Foto treffen, auf das es nicht mehr zutrifft. Adobes SDK lässt die eigenen Felder eines Zusatzmoduls nur als Text oder Enum ins Suchvokabular, nie als numerischen Bereich — es gibt also weiterhin keine intelligente Sammlung „aggregate > 8"; die Punktebreite ist der nächstliegende textbasierte Ersatz. Zwei weitere Buchhaltungs-Eigenschaften (die von diesem Lauf abgeleitete Bewertung/der Pick) werden gleich mitgeschrieben, bleiben aber außerhalb von Bibliotheksfilter und intelligenten Sammlungskriterien — siehe die Anmerkung zum Rück-Export unter [Lightroom → Facet](#lightroom--facet). **NICHT VERIFIZIERT an einem echten Katalog:** Ob ein titelloses Metadatenfeld im Metadaten-Panel und Bibliotheksfilter tatsächlich unsichtbar ist, ist allein aus der Lightroom-SDK-Dokumentation nicht bestätigt; die beiden Buchhaltungs-Eigenschaften sind deshalb als `searchable = false, browsable = false` markiert — der sicherere, bestätigte Ersatz statt eines unbestätigten Titel-Weglassungs-Verhaltens — sie könnten in manchen Lightroom-Classic-Versionen trotzdem sichtbar sein.
- **Create "Facet" keywords from Facet tags (never included on export)** — legt ein Wurzel-Stichwort `Facet` mit einem Kind pro Facet-Tag Ihrer Fotos an und hält die `Facet ›`-Kind-Stichwörter jedes Fotos exakt in Übereinstimmung mit seinen Manifest-Tags (fügt hinzu und entfernt, wenn sich Tags zwischen Läufen ändern). Jedes Stichwort, das diese Option anlegt oder berührt, hat `Include on Export` deaktiviert, sodass Facets automatische Tags nie in einen JPEG-/TIFF-Export oder eine Kundengalerie durchsickern. Ihre eigenen Stichwörter außerhalb der `Facet`-Wurzel werden von dieser Option nie gelesen, hinzugefügt oder entfernt.

**Warum Sammlungen statt Stapel.** Lightrooms SDK hat keinen Aufruf, um einen Stapel (Stack) zu erstellen oder zu verwalten — `stackInFolder`/`stackPositionInFolder` sind auf `LrPhoto` nur lesbar. Eine Sammlung ist der nächstliegende schreibbare Ersatz, und `canReturnPrior` bewirkt, dass ein erneuter Lauf des Zusatzmoduls dieselbe Sammlung wiederfindet, statt sie zu duplizieren. Wenn Sie einen echten Lightroom-Stapel wollen, wählen Sie die Fotos einer Sammlung aus und nutzen Sie selbst **Foto → Stapeln → Zu Stapel gruppieren** (Strg/Cmd+G) — diesen Schritt kann das Zusatzmodul nicht für Sie übernehmen.

**Grenzen**, ehrlich benannt:

- **Pick-Flags existieren nur im Katalog.** Das ist Lightrooms Entwurf, nicht der des Zusatzmoduls: Lightroom schreibt das Pick-Flag nie ins XMP, es erreicht also keine andere Anwendung und geht verloren, wenn Sie den Katalog aus den Dateien neu aufbauen. Sternebewertungen überleben dagegen über **Metadaten → Metadaten in Datei speichern**.
- **Der Metadatenfeld-Weg für intelligente Sammlungen bleibt textbasiert.** Adobes SDK lässt die eigenen Felder eines Zusatzmoduls nur als Text oder Enum (`sdktext:`) in das Suchvokabular; die numerischen Operatoren (`>`, `<`, „liegt im Bereich") bleiben Lightrooms eingebauten Kriterien vorbehalten. Das Punktebreite-Feld oben ist der nächstliegende textbasierte Ersatz für „aggregate > 8"; den rohen Score über die **Sternebewertung** (die Ersatz-Option oben) zu führen bleibt der einzige Kanal, den Lightroom selbst numerisch filtert und sortiert.
- **Rückgängig** funktioniert stapelweise: Das Zusatzmodul schreibt in Blöcken von 200 Fotos, Strg/Cmd+Z nimmt also 200 Fotos auf einmal zurück.
- Setzen Sie vor einem Lauf das Häkchen bei **Write facet-apply.log next to the manifest**, wenn Sie Zeile für Zeile sehen müssen, welche Pfade zugeordnet wurden und was geschrieben wurde.

### Lightroom → Facet

**Bewertungen, Picks und Ablehnungen — Lightroom gewinnt (über das Zusatzmodul).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** schreibt `facet_lightroom_state.json` (ein Datensatz pro Foto: `path`, sowie `rating`/`pick` nur, wenn sie noch reisen müssen — siehe unten) neben das Manifest. Spielen Sie es mit `python facet.py --import-lightroom facet_lightroom_state.json` zurück (fügen Sie `--user alice` bei einer Mehrbenutzer-Installation hinzu; dort erforderlich) oder, im Viewer, über den Button **Import Lightroom state…** im Dialog **Export to editor** der Galerie, der den Dateiinhalt direkt an den Server sendet. Lightrooms Wert gewinnt bedingungslos für jeden im Datensatz vorhandenen Schlüssel — CLI und Viewer teilen sich denselben Importer `processing/lightroom_sync.py`, der die Zählungen `matched`/`unmatched`/`changed` meldet:

| Lightroom-Status | Facet-Ergebnis |
|---|---|
| Pick-Flag = Ausgewählt (`pick = 1`) | Favorit = an, abgelehnt = aus |
| Pick-Flag = Abgelehnt (`pick = -1`) | Favorit = aus, abgelehnt = an |
| Pick-Flag = keins (`pick = 0`) | Favorit = aus, abgelehnt = aus |
| Sternebewertung (`rating`, 0-5) | `star_rating` (`0` löscht sie) |

Ein Datensatz, der `rating` oder `pick` ganz auslässt, lässt Facets entsprechenden Wert unberührt — der Export enthält einen Schlüssel nur, wenn Lightrooms aktueller Wert von dem abweicht, was die Apply-Richtung zuletzt selbst für dieses Foto abgeleitet hat (zwei versteckte, nicht durchsuchbare Zusatzmodul-Eigenschaften merken sich diese Grundlinie), sodass ein erneuter Export eines unberührten Fotos einen leeren Datensatz schreibt und nichts ändert. Ein erfolgreicher Import, der etwas ändert, baut außerdem dieselben bewertungsabgeleiteten Trainingspaare neu und stößt denselben leerlaufgetriggerten automatischen Neu-Trainingslauf an wie jede andere Bewertungs-Schreibung. Virtuelle Kopien werden vor dem Export nach Pfad auf ihr Original reduziert, wobei das Original bevorzugt wird, wenn beide für dieselbe Datei existieren.

**Bewertungen, Label und Stichwörter über XMP.** Getrennt davon, und weiterhin in dieser Richtung eine Einbahnstraße:

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

Seit digiKam 9.1.0 (veröffentlicht am 2026-06-07) liest digiKam XMP-Sidecars nativ — auf digiKam-Seite ist kein exiftool nötig — und es sucht nach beiden Namenskonventionen (zuerst `<bild><ext>.xmp`, dann als Fallback `<bild>.xmp`), sodass es Facets Sidecars für RAW-Dateien ohne die obige Falle findet. Öffnen (oder aktualisieren) Sie nach `python facet.py --export-sidecars` den Ordner in digiKam: Es übernimmt automatisch Bewertung, Farblabel, Stichwörter und benannte Gesichtsbereiche, solange **Settings → Configure digiKam → Metadata → Read from sidecar files** aktiviert ist (der Standard).

### Batch-Queue-Manager-Hook

Sie können einen Facet-Reimport in einen digiKam-Batch-Queue-Manager-Workflow (BQM) mit dem Werkzeug **Custom Script** einbinden, sodass Fotos, die Sie in digiKam bewerten oder labeln, in Facets Datenbank zurückfließen, ohne digiKam zu verlassen. Aktivieren Sie **Settings → Configure digiKam → Metadata → Write to sidecar files**, damit digiKam Ihre Änderungen sofort in `<bild>.xmp` persistiert, und fügen Sie dann eine Queue hinzu, deren einziges Werkzeug Custom Script ist:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sind digiKams Platzhalter pro Datei (BQM führt das Skript unter Linux/macOS über `/bin/bash` aus und erwartet eine Ausgabedatei, daher die `cp`-Weiterleitung). Da `--import-sidecars` den gesamten Ordner durchsucht, ist die Ausführung einmal pro Foto in einer großen Charge redundant, wenn auch harmlos (sie ist idempotent — unveränderte Fotos werden übersprungen). Verzichten Sie bei großen Chargen auf den BQM-Hook und führen Sie stattdessen einfach einmal von Hand `python facet.py --import-sidecars /pfad/zum/ordner` aus, nachdem die Queue abgeschlossen ist.

## darktable

darktable wird bereits erstklassig behandelt in [Konfiguration — Viewer](CONFIGURATION.md#viewer) (Export-Profile/-Stile `viewer.raw_processor.darktable`) und [Viewer — Download](VIEWER.md#api-endpunkte) (Konvertierungen `type=darktable`). Auf der XMP-Seite: darktable schreibt sein eigenes `<bild><ext>.xmp`, um seinen Bearbeitungsverlauf zu speichern, und Facets exiftool-gestützter Sidecar-Writer führt an derselben Datei eine In-Place-Zusammenführung durch — die Knoten `darktable:history`/Masken bleiben erhalten und werden nie überschrieben. Ein separates Rezept ist hier nicht nötig: Das oben für Lightroom beschriebene bidirektionale Sidecar-Verhalten (Export/Import, neueste gewinnt, Tag-Vereinigung) gilt hier genauso, ohne die RAW-Namensfalle, da sich darktable und Facet auf `<bild><ext>.xmp` einigen.

**Vorbehalt: darktables eigenes XMP-Neuladen ist unzuverlässig.** Unabhängig von Facets Schreibpfad kann ein erneuter Import eines von darktable bereits bearbeiteten Bildes dazu führen, dass darktable den Bearbeitungsverlauf des Sidecars mit einem leeren überschreibt, statt ihn zu laden — ein offener Upstream-Bug ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), gemeldet am 2026-03-15), vor dem die Einstellung „check for new/updated xmp files on start" nicht schützt. Facet ist nicht die Ursache (die exiftool-Zusammenführung oben erhält `darktable:history` bereits), aber das Risiko liegt genau in dem Rücklese-Schritt, auf den der Roundtrip dieser Seite angewiesen ist. Praktischer Workaround, nach demselben Einmal-Prinzip wie im Capture-One-Rezept oben: Importieren Sie nach `--export-sidecars` keinen bereits bearbeiteten Ordner pauschal neu — laden Sie Sidecars nur für die Bilder neu, die Facet gerade angefasst hat, und prüfen Sie, dass der Bearbeitungsverlauf noch vorhanden ist, bevor Sie dem Rest der Charge vertrauen.

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
