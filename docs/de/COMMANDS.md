# Befehlsreferenz

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · **Deutsch** · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · [简体中文](../zh/COMMANDS.md)

[Scannen](#scannen) · [Vorschau & Export](#vorschau--export) · [Neuberechnungen](#neuberechnungen) · [Gesichtserkennung](#gesichtserkennung) · [Thumbnail-Verwaltung](#thumbnail-verwaltung) · [Diagnose](#diagnose) · [Modellinformationen](#modellinformationen) · [Gewichtungsoptimierung](#gewichtungsoptimierung-paarweiser-vergleich) · [Konfiguration](#konfiguration) · [Verschlagwortung](#verschlagwortung) · [Datenbankvalidierung](#datenbankvalidierung) · [Datenbankpflege](#datenbankpflege) · [Web-Viewer](#web-viewer) · [Häufige Arbeitsabläufe](#häufige-arbeitsabläufe)

> Anforderungs-Tags, die nachstehend verwendet werden: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM-Profil). Siehe die [Funktionsmatrix](../README.md#feature-availability--requirements).

## Scannen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path` | Verzeichnis scannen (Multi-Pass-Modus, automatische VRAM-Erkennung) |
| `python facet.py /path --force` | Bereits verarbeitete Dateien erneut scannen |
| `python facet.py /path --single-pass` | Single-Pass-Modus erzwingen (alle Modelle gleichzeitig). Setzt den CLIP+MLP-Kopf der Profile `legacy`/`8gb` voraus; bei `16gb`/`24gb` erscheint eine Warnung und es läuft Multi-Pass (außerhalb des kommerziellen Modus) |
| `python facet.py /path --pass quality` | Nur den TOPIQ-Qualitäts-Pass ausführen |
| `python facet.py /path --pass quality-iaa` | Nur die TOPIQ-IAA-Bewertung des ästhetischen Verdienstes ausführen |
| `python facet.py /path --pass quality-face` | Nur die TOPIQ-NR-Face-Qualitätsbewertung ausführen |
| `python facet.py /path --pass quality-liqe` | Nur LIQE-Qualität + Verzerrungsdiagnose ausführen |
| `python facet.py /path --pass tags` | Nur den Verschlagwortungs-Pass ausführen (Modell hängt vom VRAM-Profil ab) |
| `python facet.py /path --pass composition` | Nur die SAMP-Net-Erkennung von Kompositionsmustern ausführen |
| `python facet.py /path --pass faces` | Nur die InsightFace-Gesichtserkennung ausführen |
| `python facet.py /path --pass embeddings` | Nur die CLIP/SigLIP-Embedding-Extraktion ausführen (ein einzelner `--pass`-Lauf schreibt keine Tags) |
| `python facet.py /path --pass saliency` | Nur die BiRefNet-Erkennung der Motiv-Salienz ausführen |
| `python facet.py /path --db custom.db` | Benutzerdefinierte Datenbankdatei verwenden |
| `python facet.py /path --config my.json` | Benutzerdefinierte Bewertungskonfiguration verwenden |
| `python facet.py --resume` | Den letzten unterbrochenen/fehlgeschlagenen Scan fortsetzen — einschließlich eines durch SIGKILL/OOM/Stromausfall hart abgestürzten Scans (ein Lauf, der noch als `running` markiert ist und dessen Heartbeat älter als `processing.scan_stale_seconds` ist, Standard 120). Verwendet dessen Verzeichnisse erneut; mit `--force` werden Dateien übersprungen, die seit dem Start dieses Laufs bereits neu bewertet wurden. Verweigert, wenn ein anderer Scan tatsächlich aktiv zu sein scheint. |
| `python facet.py --retry-failed` | Nur die Dateien erneut verarbeiten, die während des letzten Scan-Laufs fehlgeschlagen sind (`--retry-failed all` für Fehler über alle Läufe hinweg) |
| `python facet.py /path --force-since 2026-01-01` | Wie `--force`, aber nur Fotos erneut verarbeiten, die zuletzt vor dem Datum gescannt wurden |
| `python facet.py /path --watch` | Weiterlaufen und erneut scannen, sobald neue Fotos auftauchen (erfordert `pip install watchdog`; `--watch-debounce N` stellt die Ruhephase ein, Standard 30 s) |
| `python facet.py /path --force-low-space` | Die Speicherplatzprüfung vor dem Scan überspringen (auch fortfahren, wenn das Volume für die Thumbnails/Embeddings, die der Scan schreiben wird, zu klein erscheint) |

### Scan-Buchhaltung

Jeder Scan zeichnet eine Zeile in `scan_runs` auf (Status, Modus, Verzeichnisse, Zähler)
und pro-Datei-Fehler in `scan_failures` (Pfad, Phase, Fehler). Das Unterbrechen eines
Scans mit Strg+C markiert den Lauf als `interrupted`, sodass `--resume` ihn aufnehmen kann;
fehlgeschlagene Dateien sind sichtbar und erneut versuchbar, statt bei jedem inkrementellen
Scan stillschweigend erneut versucht zu werden. Die CLI gibt außerdem strukturierte
`@FACET_PROGRESS`-JSON-Zeilen aus (Phase, aktuell/gesamt, ETA), die die Scan-API des
Viewers im `progress`-Feld von `/api/scan/status` und im SSE-Stream bereitstellt.

### Verarbeitungsmodi

**Multi-Pass (Standard):** erkennt den VRAM und lädt die Modelle nacheinander. Jeder Pass lädt sein Modell, verarbeitet alle Fotos und entlädt es dann, um VRAM freizugeben, sodass hochwertige Modelle auch mit begrenztem VRAM laufen.

**Single-Pass (`--single-pass`):** lädt alle Modelle gleichzeitig. Schneller, benötigt mehr VRAM. Die Ästhetik wird mit dem CLIP+MLP-Kopf bewertet, daher gilt der Modus für die Profile `legacy` und `8gb`. Bei `16gb` und `24gb` ist das Ästhetikmodell TOPIQ, das nur der Multi-Pass-Scan ausführt; eine Single-Pass-Anforderung (`--single-pass` oder `processing.mode: "single-pass"`) protokolliert deshalb eine Warnung und läuft stattdessen als Multi-Pass. `--pass NAME` und `--dry-run` überspringen diese Prüfung. Im kommerziellen Modus bleibt Single-Pass verfügbar, weil dort das native Q-ReAlign die Ästhetik bewertet. Erreicht ein Single-Pass-Batch dennoch den Scorer ohne Ästhetikkopf, schlägt er fehl: Seine Fotos werden in `scan_failures` erfasst und nicht gespeichert.

**Hinweis zum Upgrade:** Frühere Versionen speicherten bei einem Single-Pass-Scan unter `16gb`/`24gb` für jedes Foto eine neutrale Ästhetik von 5,0. Diese Zeilen finden Sie mit `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL` (ein Multi-Pass-Scan schreibt immer `topiq_score`). Es gibt keinen Reparaturbefehl, da TOPIQ das Bild braucht: Scannen Sie die betroffenen Ordner im Multi-Pass-Modus mit `--force` neu.

**Bestimmter Pass (`--pass NAME`):** nur einen Pass ausführen, um bestimmte Metriken zu aktualisieren, ohne vollständig neu zu verarbeiten. Verfügbare Pässe:

| Pass | Modell | Ausgabe | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic`-Score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa`-Score (künstlerisches Verdienst vs. technische Qualität, AVA-trainiert) | Geteilt mit TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa`-Score (eigens für Gesichtsqualität entwickelt) | Geteilt mit TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + Verzerrungsdiagnose (Unschärfe, Überbelichtung, Rauschen) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantische Tags aus dem konfigurierten Vokabular | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 Muster) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Gesichtserkennung, Landmarken, Blinzelerkennung, Erkennungs-Embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 oder SigLIP 2 NaFlex | `clip_embedding`-BLOB für Ähnlichkeit/Verschlagwortung | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

## Vorschau & Export

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path --dry-run` | 10 Beispielfotos bewerten, ohne zu speichern. Bei `16gb`/`24gb` zeigt die Ästhetikspalte `n/a`, weil TOPIQ nur in einem echten Scan läuft (der kommerzielle Modus zeigt stattdessen den Q-ReAlign-Wert); der Gesamtwert zählt die fehlende Ästhetik als neutrale 5.0 |
| `python facet.py /path --dry-run --dry-run-count 20` | 20 Beispielfotos bewerten |
| `python facet.py --export-csv` | Alle Scores in eine CSV mit Zeitstempel exportieren (die Spalte `tags` enthält nur KI-Tags; [manuelle Tags](VIEWER.md#manuelle-tags) sind nicht enthalten) |
| `python facet.py --export-csv output.csv` | In eine bestimmte CSV-Datei exportieren |
| `python facet.py --export-json` | In eine JSON mit Zeitstempel exportieren; das Objekt `scores` jedes Fotos enthält jede gespeicherte Metrikspalte (NULL, nicht endliche Zahlen und BLOBs als `null`; Spalten, die ein älteres Schema nicht hat, entfallen). `tags` enthält nur KI-Tags, wie beim CSV. Ein Ausgabepfad, der die Datenbank oder ihre `-wal`/`-shm`/`-journal` ist, wird abgelehnt |
| `python facet.py --export-json output.json` | In eine bestimmte JSON-Datei exportieren |
| `python facet.py --export-manifest` | Ein kompaktes JSON-Manifest (Pfad, Kategorie, Scores, Tags, Sternebewertung, Favorit/Abgelehnt, Serien-Leitbild) nach `facet_manifest.json` exportieren — für externe Werkzeuge wie ein Lightroom-Classic-Plugin (`tags` = KI- plus manuelle Tags) |
| _Manifest Version 2_ | Fügt jedem Foto `burst_group_id`, `sequence_kind`, `sequence_group_id` und `score_stars` (der Gesamt-Score, umgerechnet über `xmp_export.score_to_rating`) hinzu, für die neuen Serien-Auswahl/Ablehnungs- und Sterne-Ersatz-Optionen des Facet-Zusatzmoduls — siehe [docs/INTEROP.md](INTEROP.md#das-facet-zusatzmodul-sternebewertungen-pick-flags-metadatenfelder-und-stichwörter). Ein für diese Version gebautes Zusatzmodul weist ein älteres Manifest zurück und bittet um erneuten Export |
| `python facet.py --export-manifest /path` | Manifest auf Fotos unterhalb eines Pfad-Teilbaums beschränken |
| `python facet.py --export-manifest --user alice` | Mehrbenutzermodus: exportiert Alices `user_preferences`-Bewertungen in das Manifest statt der globalen Spalten (Tags und Scores bleiben global) |
| `python facet.py --import-lightroom DATEI` | Importiert den vom Zusatzmodul exportierten Lightroom-Bewertungs-/Pick-/Ablehnungs-Status (`facet_lightroom_state.json`, siehe [Lightroom → Facet](INTEROP.md#lightroom--facet) in docs/INTEROP.md) — Lightroom gewinnt für jedes Feld, das die Datei enthält. Gibt `matched=… unmatched=… changed=…` aus |
| `python facet.py --import-lightroom DATEI --user alice` | Mehrbenutzermodus: schreibt in Alices `user_preferences`-Zeile statt in die globalen Spalten; auf einer Mehrbenutzer-Installation **erforderlich** — sonst verweigert, damit ein Import nie stillschweigend im falschen Geltungsbereich landet |
| `python facet.py --import-sidecars` | Bewertungen/Labels/Tags aus `<image>.xmp`-Sidecars zurück in die DB importieren (alle Fotos); Stichwörter, die Facet noch nicht kennt, werden zu [manuellen Tags](INTEROP.md#manuelle-tags-und-xmp-stichwörter) |
| `python facet.py --import-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums importieren |
| `python facet.py --import-sidecars --user alice` | Mehrbenutzermodus: Bewertungen in Alices `user_preferences` importieren statt in die globalen Spalten (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars` | `<image>.xmp`-Sidecars aus der DB für alle Fotos schreiben/zusammenführen (nur Sidecar) |
| `python facet.py --export-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums exportieren |
| `python facet.py --export-sidecars --user alice` | Mehrbenutzermodus: Alices `user_preferences`-Bewertungen exportieren statt der globalen Spalten (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars --embed-originals` | Metadaten zusätzlich **in der Datei** für JPEG/HEIC/TIFF/PNG/DNG einbetten (schreibt die Originale neu) |
| `python facet.py --export-sidecars --score-to-stars` | `xmp:Rating` aus dem aggregierten Score für Fotos ableiten, die Sie nicht manuell bewertet haben (eine manuelle Bewertung/Favorit/Ablehnung gewinnt immer) |

> **Zwei-Wege-Metadatensynchronisierung.** Facet schreibt Bewertungen, Farblabels, Schlüsselwörter, Bildunterschriften und benannte Gesichtsregionen in eine standardmäßige `<image>.xmp`-Sidecar, die das Ökosystem liest (Lightroom, darktable, digiKam, immich, …); das Originalbild wird nie verändert, es sei denn, Sie entscheiden sich dafür mit `--export-sidecars --embed-originals` (nur JPEG/HEIC/TIFF/PNG/DNG — RAW wird nie angetastet). Das Einbetten und die sichere Schlüsselwort-Vereinigungszusammenführung erfordern **exiftool**; ohne es greift Facet auf eine abhängigkeitsfreie reine XML-Sidecar zurück. Geschriebene Stichwörter sind die KI-Tags plus Ihre [manuellen Tags](VIEWER.md#manuelle-tags), und ein einmal geschriebenes Stichwort wird von einem späteren Export nie wieder aus einem Sidecar entfernt (siehe [Manuelle Tags und XMP-Stichwörter](INTEROP.md#manuelle-tags-und-xmp-stichwörter)).
>
> **Vorbehalt.** `--import-sidecars` löst Bewertungen/Labels *„neueste gewinnt"* gegen das `scanned_at` des Fotos (letzter Scan) auf, nicht gegen eine pro-Bewertung-Bearbeitungszeit — eine Sidecar, die neuer als der letzte Scan ist, kann also eine Bewertung überschreiben, die Sie in Facet danach geändert haben. Führen Sie `--import-sidecars` vor dem Neubewerten aus, wenn der externe Editor die Quelle der Wahrheit ist. Importierte Stichwörter landen in der Tabelle der manuellen Tags, die die Tag-Filter direkt lesen, daher ist danach kein `--migrate-tags` nötig.
>
> **`--export-manifest` vs. `--export-csv`/`--export-json`.** Das optionale Argument des Manifests grenzt ein, *welche Fotos* exportiert werden (wie bei `--export-sidecars`), nicht den Namen der Ausgabedatei — es (über)schreibt immer `facet_manifest.json` im Arbeitsverzeichnis, da es dazu gedacht ist, an Ort und Stelle für ein Werkzeug neu erzeugt zu werden, das einen festen Pfad wieder einliest. Es enthält dieselben Werte `star_rating`/`is_favorite`/`is_rejected` wie `--export-sidecars` — standardmäßig die globalen Spalten, oder bei Angabe von `--user` die `user_preferences`-Zeile des benannten Benutzers, sodass eine Mehrbenutzer-Installation kein Manifest voller Nullen mehr exportiert — zusätzlich `is_burst_lead` (immer global), eine übergeordnete Zählung `pending_corrections` (manuelle Bracket-/Panorama-Korrekturen, die von einem Erkennungslauf noch nicht angewendet wurden — eine Zählung größer null gibt nach dem Export eine einzeilige Warnung mit `--detect-panoramas` aus), und wird als kompaktes (nicht formatiertes) JSON geschrieben — bei ~100.000 Fotos würde die `indent=2`-Ausgabe von `--export-json` auf mehrere zehn Megabyte anwachsen, ohne dass ein maschineller Leser davon profitiert.
>
> **`--import-lightroom` ist die Umkehrung von `--export-manifest`.** Es liest den Export des Zusatzmoduls selbst (`facet_lightroom_state.json`, ein *anderes* Dateiformat — `{"format":"facet-lightroom-state","version":1,"photos":[...]}` — vor jeder DB-Schreibung validiert und abgelehnt, falls es nicht passt), niemals das Manifest selbst, und wendet Lightrooms Pick/Bewertung als gewinnenden Wert für jedes Feld an, das ein Datensatz trägt; ein ausgelassenes Feld lässt Facets eigenen Wert unberührt. Eine Änderung stößt denselben bewertungsabgeleiteten Trainingspaar-Neuaufbau und Auto-Retrain-Anstoß an wie jede andere Bewertungs-Schreibung.

### Immich-Synchronisierung

Übertragen Sie Ihre Facet-Bewertungen und Favoriten an einen [Immich](https://immich.app/)-Server über dessen REST-API (Einweg — Facet → Immich). Assets werden anhand von `originalPath` über die Pfad-Präfix-Zuordnungen im `immich`-Konfigurationsblock aufgelöst, in einem einzigen gebündelten Suchdurchlauf.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --immich-test` | Konnektivität und Authentifizierung gegen den konfigurierten Immich-Server prüfen (`immich.url` + `immich.api_key`, gesendet als `x-api-key`) |
| `python facet.py --immich-sync` | Sternebewertungen (1–5) und Favoriten an Immich übertragen, Assets anhand von `originalPath` auflösen. Berücksichtigt `--dry-run` (löst auf, schreibt aber nie) und `--user` (benutzerspezifische Bewertungen im Mehrbenutzermodus) |
| `python facet.py --immich-sync --dry-run` | Jedes Asset auflösen und melden, was sich ändern würde, ohne zu schreiben |

Bewertungen folgen Immichs versionssicherer Richtlinie (nur 1–5, nie 0/−1); ein optionales Top-Picks-Album sammelt Fotos oberhalb eines Bewertungsschwellenwerts. Nur REST — keine direkte Kopplung an die Immich-Datenbank. Siehe [Konfiguration — Immich-Synchronisierung](CONFIGURATION.md#immich-sync) für den vollständigen Block.

## Neuberechnungen

Diese Befehle aktualisieren bestimmte Metriken, leiten neue Daten ab (KI-Bildunterschriften, GPS, Embeddings) oder analysieren die Datenbank — alles, ohne die vollständige Bewertungspipeline erneut auszuführen. Die meisten verwenden gespeicherte Thumbnails/Landmarken erneut und sind CPU-leicht, aber die KI-/Extraktionszeilen (z. B. `--generate-captions`) und die aus-dem-Bild-neuberechnenden Zeilen sind GPU-intensiv.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --recompute-average` | Aggregierte Scores aus gespeicherten Embeddings neu berechnen (neu ableitbar; kein DB-Snapshot — zum Zurückrollen einen Gewichtungs-Snapshot wiederherstellen und neu berechnen). Führen Sie nach dem Upgrade von 1.20 oder früher zuerst `--recompute-silhouette` aus, dann diesen Befehl zweimal: Der erste Durchlauf über eine Bibliothek, die zuletzt von älterem Code aggregiert wurde, speichert die Perzentile, an denen er normalisiert, daher ändert der zweite Durchlauf noch einige Zeilen |
| `python facet.py --recompute-category portrait` | Scores nur für eine einzelne Kategorie neu berechnen |
| `python facet.py --tag-untagged` | Verschlagwortet nur Fotos, die noch keine Tags haben, aus den gespeicherten Embeddings (kein Bildzugriff). Dieselbe Arbeit, die ein Scan am Ende erledigt; damit lassen sich Lücken füllen, ohne bereits Verschlagwortetes neu zu bearbeiten |
| `python facet.py --recompute-tags` | Alle Fotos mit dem konfigurierten Modell neu verschlagworten |
| `python facet.py --recompute-tags-vlm` | Alle Fotos mit dem VLM-Tagger neu verschlagworten |
| `python facet.py --detect-moments` | Neue Fotos mit ihrem narrativen Moment kennzeichnen (caption-semantisch, Zero-Shot + zeitliche Glättung; läuft am Ende jedes Scans automatisch). Kodiert jede neue Bildunterschrift einmal in `caption_embedding`, dann Kosinus über gespeicherte Vektoren — der erste vollständige Backfill über eine bestehende Bibliothek ist GPU-empfohlen; fügen Sie `--limit N` hinzu, um es an einer Stichprobe zu prüfen. Wenn `narrative_moments.vlm_tiebreak.enabled` gesetzt ist (16gb/24gb-Profile), werden Frames mit niedrigem Posterior / niedriger Marge vom Profil-VLM neu klassifiziert |
| `python facet.py --recompute-moments` | Narrative Momente für die gesamte Bibliothek neu kennzeichnen (glättet die vollständige Zeitachse erneut). Fügen Sie `--dry-run --verbose` hinzu, um die Top-3-Momente pro Foto ohne Schreiben vorab anzuzeigen. Berücksichtigt zudem die `narrative_moments.vlm_tiebreak`-VLM-Neuklassifizierung von Frames mit niedriger Konfidenz, wenn aktiviert (16gb/24gb) |
| `python facet.py --discover-moments` | Ein bibliotheksspezifisches Moment-Vokabular vorschlagen, indem die gespeicherten Bildunterschrift-Embeddings geclustert (HDBSCAN) und jedes Cluster anhand seiner Bildunterschriften benannt werden. Schreibt `scoring_config.discovered.json` zur Überprüfung — überschreibt niemals die aktive Konfiguration. Führen Sie zuerst `--detect-moments` aus, um `caption_embedding` zu befüllen; passen Sie die Granularität mit `--discover-min-cluster-size N` an |
| `python facet.py --detect-junk` | Nicht-fotografischen Müll (Screenshots, Dokumente, Belege, Memes, Folien) in neuen/unbewerteten Fotos per Zero-Shot-CLIP über gespeicherte Embeddings kennzeichnen; läuft am Ende jedes Scans automatisch. Saubere Fotos werden als `not_junk` markiert, sodass erneute Läufe sie nie wieder scannen; fügen Sie `--dry-run --verbose` hinzu, um Scores pro Foto ohne Schreiben vorab anzuzeigen |
| `python facet.py --recompute-junk` | `junk_kind` für die gesamte Bibliothek neu bewerten (alle Fotos mit gespeichertem Embedding) |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Metriken der Motiv-Salienz neu berechnen (BiRefNet_dynamic). Ein Foto, dessen Salienz fehlschlägt (z. B. wegen Speichermangels), wird als ERROR protokolliert und nicht geschrieben: Eine nie bewertete Zeile bleibt NULL und wird vom nächsten Lauf erneut ausgewählt, und mit `--force` behält eine Zeile, die bereits Salienzwerte hat, ihre gespeicherten Werte. Auf CUDA wird die Batchgröße aus dem freien VRAM abgeleitet. |
| `python facet.py --recompute-composition-cpu` | Komposition neu berechnen, regelbasiert (CPU, beliebiges Profil). Ein Foto, dessen Vorschaubild keinen Motivrahmen hat, erhält ein NULL-`power_point_score` (das frühere neutrale 5.0 wird auf NULL umgeschrieben; ein nicht dekodierbares Vorschaubild behält seinen Wert) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Komposition mit SAMP-Net neu berechnen |
| `python facet.py --recompute-iqa` | `[GPU]` Ergänzende IQA-Metriken (TOPIQ IAA, NR-Face, LIQE) aus gespeicherten Thumbnails neu berechnen. Auf allen Profilen aktiviert (legacy läuft auf der CPU, langsamer); GPU dringend empfohlen. Füllt nur Spalten, die NULL sind. NR-Face überspringt Fotos ohne erkanntes Gesicht; LIQE überspringt ein Foto, dessen gespeichertes Thumbnail eine kurze Seite unter 224 px hat (in der Zusammenfassung gezählt, nichts gespeichert); ein Foto, das NR-Face ablehnt (im Thumbnail wurde kein Gesicht gefunden), wird in der Tabelle `iqa_declined` vermerkt und erst nach einem Neuscan des Fotos erneut versucht (ein Upgrade von pyiqa oder der NR-Face-Gewichte löscht diese Einträge nicht: mit `--force` neu scannen oder `--refresh-thumbnails` ausführen); jeder andere Fehlschlag (Speichermangel, unerwarteter Fehler) bleibt NULL und wird vom nächsten Lauf erneut ausgewählt. Ein bereits gespeicherter Wert (auch eine neutrale 5,0 einer früheren Version) wird nie ersetzt: Löschen Sie solche Werte zuerst mit `--repair-neutral-iqa`. Siehe [Ergänzende Qualitätsmodelle](#ergänzende-qualitätsmodelle) |
| `python facet.py --detect-text` | Extrahiert Text im Bild (Schilder, Poster, Dokumente) über OCR aus gespeicherten Thumbnails in `ocr_text` und macht ihn über die Suchleiste der Galerie durchsuchbar. Überspringt bereits ausgewertete Fotos, sodass erneute Läufe nur neue lesen. Optional: benötigt `ocr.enabled` in `scoring_config.json` plus `pip install easyocr` — siehe [Konfiguration — OCR](CONFIGURATION.md#ocr) |
| `python facet.py --recompute-text` | OCR für die gesamte Bibliothek erneut ausführen, wobei bereits von `--detect-text` ausgewertete Fotos neu gelesen werden |
| `python facet.py --recompute-colors` | Dominanten Farbton + warme/kalte Farbtemperatur aus Thumbnails extrahieren (CPU, schnell) in `dominant_hue` / `color_temp` |
| `python facet.py --recompute-form` | Die fünf erklärbaren Form-/Farbmetriken neu berechnen — Links-rechts-Symmetrie, visuelle Balance, Kantenorientierungs-Entropie, Box-Counting-Fraktalkomplexität und Matsuda-Farbtonvorlagen-Farbharmonie — aus gespeicherten Thumbnails (CPU, kein Modell). Sie erscheinen in der Kritik-Aufschlüsselung, den Vorschlägen und dem Foto-Tooltip und sind als Kategoriegewichte verfügbar (mit 0 ausgeliefert) |
| `python facet.py --recompute-skin-tone` | Natürlichkeit des Porträt-Hauttons aus gespeicherten Gesichts-Thumbnails + Landmarken neu berechnen (Wangen-CIELAB-Chroma gegen einen CCT-Hautlocus, CIEDE2000; CPU, kein Modell). Nur beratend — erscheint als Kritik-Hinweis, keine Aggregat-Kopplung |
| `python facet.py --recompute-distortions` | Jedes Foto mit wahrscheinlichen Verzerrungsattributen kennzeichnen (Bewegungsunschärfe, Farbstich, Überschärfung, …) via Zero-Shot-ExIQA-artige kontrastive Prompts über das gespeicherte CLIP/SigLIP-Embedding, dann einen Spearman-Korrelationsbericht gegen `liqe_score` / `noise_sigma` ausgeben. Nur beratend (Kritik-Warnungs-Chips), keine Aggregat-Kopplung |
| `python facet.py --upgrade-db` | Schema migrieren und die vollständige Backfill-Kette ausführen: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. Idempotent; überspringt schwere Schritte wie das Erstellen von Bildunterschriften. |
| `python facet.py --recompute-blinks` | Blinzelerkennung aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-eyes-expression` | Augen-offen- + Ausdrucks-Scores aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-face-signals` | Augen-offen- + Lächel-Scores pro Gesicht aus den gespeicherten 106-Punkt-Landmarken nachfüllen (CPU, schnell; kein Modell). Läuft auch als Schritt von `--upgrade-db` |
| `python facet.py --recompute-burst` | Serienbild-Erkennungsgruppen neu berechnen (schreibt nur die Zeilen, deren Serienbild-Zustand sich geändert hat, und protokolliert `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Erkennt bewusste Mehrbild-Serien: zuerst Belichtungsreihen aus den gespeicherten EXIF-Daten, dann Panoramen anhand der Vorschaubild-Geometrie, und setzt das Leitbild jeder Serie auf die Basisbelichtung. Läuft am Ende jedes Scans und als Schritt von `--upgrade-db`. Voraussetzung für die Auswahl-Granularitäten **Belichtungsreihen** / **Panoramen** / **HDR-Panoramen** des Viewers und dafür, dass `hide_brackets` / `hide_panoramas` überhaupt etwas zu filtern haben — keiner der beiden bewirkt etwas, solange keine Serie beschriftet ist. Da jeder Lauf die gesamte Bibliothek von Grund auf neu beschriftet, leitet ein erneuter Aufruf (oder `--detect-panoramas`) auch das repräsentative Bild einer Serie neu ab, nachdem das vorherige aussortiert wurde |
| `python facet.py --detect-panoramas` | Erkennt Panorama-Serien durch geometrischen Abgleich der gespeicherten Vorschaubilder (gesamte Bibliothek, CPU, keine Bilddekodierung). Führt zuerst den Bracket-Durchlauf aus, wie `--detect-sequences`: Ein HDR-Panorama ist an jeder Position bracketiert, beide müssen im Gleichschritt bleiben. Dieselbe Voraussetzung wie `--detect-sequences` für die Auswahl-Granularitäten Panorama/HDR-Panorama und den Schalter `hide_panoramas` |
| `python facet.py --detect-duplicates` | Doppelte Fotos via pHash erkennen (schreibt nur die Zeilen, deren Duplikat-Zustand sich geändert hat, und protokolliert `Duplicate state: N rows changed`; ein zweiter Lauf meldet 0) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Kosinus-Schwellenwerte für Beinahe-Duplikate auswerten (Präzisions-/Recall-Tabelle mit Labels, sonst Verteilung der Kandidaten-Kosinuswerte) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` KI-Bildunterschriften für Fotos mit VLM erzeugen. Wenn `narrative_moments.caption_min_confidence > 0`, werden nicht gekennzeichnete / `other` / unter dem Schwellenwert liegende Fotos übersprungen (derselbe Filter gilt für den On-Demand-Bildunterschrift-Endpunkt) |
| `python facet.py --translate-captions` | Englische Bildunterschriften in die konfigurierte Zielsprache übersetzen (CPU, MarianMT) |
| `python facet.py --extract-gps` | GPS-Koordinaten aus EXIF-Daten in Datenbankspalten extrahieren. Fotos, deren Standort im Viewer gesetzt wurde, werden übersprungen. |
| `python facet.py --rescan-gps` | GPS-Koordinaten aus EXIF für alle Fotos neu extrahieren (überschreibt vorhandene). Fotos, deren Standort im Viewer gesetzt wurde, werden übersprungen. |
| `python facet.py --recompute-embeddings` | CLIP/SigLIP-Embeddings für alle Fotos neu berechnen (nach Modellwechsel erforderlich) |
| `python facet.py --score-topiq` | `topiq_score` mit TOPIQ für jedes Foto mit gespeichertem Thumbnail neu berechnen (GPU erforderlich). Es gibt keinen NULL-Filter, bestehende Werte werden daher überschrieben; ein Foto, das TOPIQ nicht bewerten kann, behält seinen gespeicherten Wert |
| `python facet.py --backfill-focal-35mm` | 35-mm-äquivalente Brennweite aus EXIF für Fotos nachfüllen, denen sie fehlt |
| `python facet.py --backfill-clipping` | Leitet die Beschnitt-Prozentsätze pro Kanal aus den gespeicherten Histogrammen ab. Nur Datenbank (keine Bilddekodierung) und fortsetzbar; Fotos, deren Histogramm älter als das RGB-Format ist, bleiben unbekannt (NULL) |
| `python facet.py --recompute-silhouette` | Leitet `is_silhouette` mit der gesichtsbezogenen Regel (siehe [SCORING.md](SCORING.md)) aus den gespeicherten Vorschaubildern und Gesichtsrahmen neu ab. Nur Datenbank (kein Dekodieren des Originalbilds), fortsetzbar (Commit pro Batch) und schreibt nur diese Spalte; berücksichtigt das globale `--dry-run` (meldet, was sich ändern würde, schreibt nichts). Der Bericht teilt die Fotos danach ein, wie ihre gespeicherten Gesichtsrahmen zum Vorschaubild stehen (`exact`, `scaled`, `count_mismatch`, `other`; die für `count_mismatch` verwendete Zuordnung wurde nicht validiert). Ein Foto, dessen Gesichtsrahmen es nicht auf dem Vorschaubild platzieren kann, wird als 0 (keine Silhouette) geschrieben, ebenso ein Foto ohne Gesichter. Fotos mit `face_count` NULL oder mit Gesichtern, aber ohne gespeichertes Vorschaubild, behalten ihr Flag und werden als `skipped_face_count_null` / `skipped_no_thumbnail` gezählt. Führen Sie danach `--recompute-average` aus, damit Wertungen und Kategorien dem neuen Flag folgen |
| `python facet.py --repair-int-columns` | Repariert INTEGER-Spalten in `photos`, deren gespeicherter Wert ein REAL ist — die SQLite-Affinität ist keine Einschränkung, daher bleibt ein von einem externen Werkzeug geschriebener gebrochener ISO-Wert als REAL erhalten. Rundet jeden Wert an Ort und Stelle (ein Wert, den SQLite nicht als Ganzzahl halten kann — nicht endlich oder jenseits von 2^53 — wird NULL) und lässt alles andere unberührt. Nur Datenbank (keine Bilddekodierung). Die API rundet nicht reparierte Zeilen beim Lesen, die Galerie funktioniert also auch ohne; Filter und Sortierungen vergleichen jedoch den tatsächlich gespeicherten Wert — führen Sie es aus, damit ein als ISO 63 angezeigtes Foto nicht von einem ISO-Bereich übersehen wird |
| `python facet.py --repair-neutral-iqa` | Löscht die neutrale 5,0, die Versionen vor 1.20 in `aesthetic_iaa`, `face_quality_iqa` und `liqe_score` für Fotos speicherten, die ein Modell nicht bewerten konnte: Jeder Wert, der in diesen drei Spalten genau 5,0 beträgt, wird in einer Transaktion auf NULL gesetzt, und die zwischengespeicherten Wertebereiche der Galerie werden verworfen. Gibt die Anzahl pro Spalte aus. Es berührt weder `aesthetic`, `topiq_score`, `aesthetic_v25` noch `quality_score` (dort ist ein echter Wert von 5,00 vom falschen nicht zu unterscheiden, und `aesthetic` ist bei `legacy`/`8gb` die CLIP+MLP-Spalte). Ein echter Wert, der genau auf 5,00 rundet, wird ebenfalls gelöscht und von `--recompute-iqa` aus dem gespeicherten Thumbnail neu gefüllt; der neue Wert kann daher geringfügig abweichen. Anschließend `--recompute-iqa` ausführen, um die Spalten neu zu füllen, danach `--recompute-average`; die Reparatur selbst verschiebt keinen Gesamtwert, weil NULL als neutral zählt. Ein laufender Viewer liefert die neuen Filterbereiche ab seiner nächsten Anfrage, ohne Neustart; eine bereits geöffnete Galerieseite behält die alten, die die gelöschten 5,0-Werte noch mitzählen, bis sie neu geladen wird. Nur Datenbank (keine Bilddekodierung); mit `--dry-run` wird der Aufruf abgelehnt (Exit-Code 2); in keiner `--upgrade-db`-Kette enthalten |
| `python facet.py --compute-recommendations` | Datenbank analysieren, Bewertungszusammenfassung anzeigen |
| `python facet.py --compute-recommendations --verbose` | Detaillierte Statistiken anzeigen |
| `python facet.py --compute-recommendations --apply-recommendations` | Bewertungskorrekturen automatisch anwenden |
| `python facet.py --compute-recommendations --simulate` | Voraussichtliche Änderungen vorab anzeigen |

### Ergänzende Qualitätsmodelle

Drei zusätzliche PyIQA-Modelle bewerten über den primären TOPIQ-Ästhetik-Score hinaus. Sie teilen sich den VRAM mit TOPIQ und laufen als Teil der standardmäßigen Multi-Pass-Pipeline.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trainiertes künstlerisches ästhetisches Verdienst, getrennt von der technischen Qualität. Gespeichert als `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): Qualitätsbewertung der Gesichtsregion. Gespeichert als `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): Qualitätsscore plus eine Diagnose des Verzerrungstyps (z. B. Bewegungsunschärfe, Überbelichtung, Rauschen). Gespeichert als `liqe_score`.

Ein Foto, das ein Modell nicht bewerten kann (für NR-Face kein Gesicht, das sein Detektor findet; für LIQE eine kurze Seite unter 224 px), speichert in dieser Spalte NULL statt einer neutralen 5,0; zuvor wird ein GPU-Out-of-Memory-Fehler mit halber Batchgröße wiederholt, bis hinunter zu einem Bild. `--recompute-iqa` füllt nur NULL-Spalten, überspringt NR-Face für Fotos mit `face_count` 0 und führt für die beiden erwarteten Fälle kein Modell erneut aus: Ein Thumbnail, dessen kurze Seite unter 224 px liegt, sobald seine lange Kante auf 1024 px begrenzt ist, wird für LIQE übersprungen (beurteilt am Bild-Header, ohne Dekodierung) und in der Zusammenfassung gezählt (gespeichert wird nichts, daher prüft jeder Lauf den Header erneut); ein Foto, das NR-Face ablehnt („No face detected“ im Thumbnail), wird in der Tabelle `iqa_declined` vermerkt und nicht erneut versucht, bis ein Neuscan, der das Foto neu schreibt (z. B. mit `--force`), `--refresh-thumbnails` oder `--fix-thumbnail-rotation` den Eintrag ungültig macht. Jeder andere Fehlschlag (GPU-Out-of-Memory, ein unerwarteter Fehler) wird nirgends gespeichert, und das Foto wird vom nächsten Lauf erneut ausgewählt. Ein bereits gespeicherter Wert, auch eine neutrale 5,0 aus einer früheren Version, wird nie ersetzt: Löschen Sie solche Werte mit `--repair-neutral-iqa` und führen Sie danach `--recompute-iqa` und `--recompute-average` aus, oder scannen Sie das Foto neu (z. B. mit `--force`). Mit `--pass quality`, `quality-iaa`, `quality-face` und `quality-liqe` behält ein Foto, dessen Modell fehlschlägt, seinen gespeicherten Wert. Ein vollständiger Scan erfasst ein Foto, dessen primäres TOPIQ-Modell fehlschlägt, in `scan_failures` (erneut versuchen mit `--retry-failed`); `--pass quality` erfasst nichts. Siehe [Ergänzende IQA-Dimensionen](SCORING.md#ergänzende-iqa-dimensionen).

### Benchmarks & ergänzende Scores

| Befehl | Beschreibung |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Die Spalte `aesthetic_clip` befüllen, indem zwischengespeicherte CLIP/SigLIP-Embeddings auf eine aus Text abgeleitete Ästhetik-Achse projiziert werden. Keine zusätzliche Bildinferenz. Nicht Teil des Standard-`aggregate`. Siehe [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | SRCC + PLCC gegen die AVA-Mean-Opinion-Score-Ground-Truth für jede befüllte Score-Spalte in der DB berechnen. Nützlich beim Hinzufügen oder Feinabstimmen einer Modellvariante. |

### Motiv-Salienz

`--pass saliency` und `--recompute-saliency` verwenden BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, über `transformers`), um eine binäre Motivmaske zu erzeugen, und leiten dann vier Metriken ab:

- **Motivschärfe**: Laplace-Varianz auf der Motivregion vs. Hintergrund — ob das Motiv im Fokus ist.
- **Motivprominenz**: Motivfläche / Bildfläche — hoch bei einem dominanten Motiv (z. B. Makro).
- **Motivplatzierung**: Drittelregel-Score für den Schwerpunkt des Motivs.
- **Hintergrundtrennung**: Kantengradient-Differenz zwischen Motivgrenze und Hintergrund — Bokeh-Qualität.

Erfordert `transformers` (~3 GB VRAM). Auf CUDA wird die Batchgröße aus dem freien VRAM abgeleitet (etwa 2,4 GiB pro Bild bei 1024 px, zwischen 1 und 8 Bildern) und nach einem Out-of-Memory-Fehler halbiert, bis hinunter zu einem Bild. Schlägt die Salienz für ein Foto trotzdem fehl, wird ein ERROR protokolliert und es werden keine Werte gespeichert: Das Foto bleibt NULL, wenn es nie bewertet wurde (und zählt im Gesamtwert als neutral, wie Fotos, die vor der Salienz gescannt wurden), behält mit `--recompute-saliency` und `--pass saliency` seine gespeicherten Werte, wenn es bereits Salienzwerte hatte (ein vollständiger Neuscan, z. B. mit `--force`, speichert dafür NULL, wie bei einem nie bewerteten Foto), und `--recompute-saliency` wählt es erneut aus. Siehe [Dimensionen der Motiverkennung](SCORING.md#dimensionen-der-motiverkennung).

Ein Foto ohne erkennbares Motiv speichert NULL für Motivschärfe, Motivplatzierung und Hintergrundtrennung (und, aus dem Kompositionsschritt, für `power_point_score`, wenn es keinen Motivrahmen gibt), Prominenz 0.0 und ein NULL-`subject_bbox`; frühere Versionen speicherten ein neutrales 5.0. Bestehende Zeilen behalten die 5.0, bis `--recompute-saliency` und `--recompute-composition-cpu` sie umschreiben. `--recompute-saliency` wählt ein Foto aus, dessen `subject_prominence` nie gespeichert wurde — nie bewertet oder ein fehlgeschlagener Lauf — sowie eines, das bewertet wurde, bevor die Spalte `subject_bbox` existierte (positive Prominenz, aber noch kein Rahmen), außerdem ein Foto ohne Motiv, das noch die neutrale 5.0 einer früheren Version trägt und von einem Lauf umgeschrieben wird; ein Foto ohne Motiv ist ein Endergebnis und wird bei späteren Läufen nicht erneut gemessen. Eine NULL-Metrik zählt im Gesamtwert weiterhin neutral; siehe [SCORING.md](SCORING.md).

### Verschlagwortungsmodelle

Das Verschlagwortungsmodell wird pro VRAM-Profil ausgewählt:

| Profil | Modell | Funktionsweise |
|---------|-------|-------------|
| `legacy` | CLIP-Ähnlichkeit | Kosinus-Ähnlichkeit zwischen Bild-Embedding und Tag-Text-Embeddings. Kein zusätzliches Modell laden. |
| `8gb` | CLIP-Ähnlichkeit | Wie legacy, auf gespeicherten CLIP-ViT-L-14-Embeddings. |
| `16gb` | Qwen3.5-2B | Multimodales Modell für semantische Szenenverschlagwortung. |
| `24gb` | Qwen3.5-4B | Größeres multimodales Modell. |

Alle Tagger ordnen die Ausgabe dem konfigurierten Tag-Vokabular zu. Verwenden Sie `--recompute-tags`, um mit dem Standardmodell des Profils neu zu verschlagworten, oder `--recompute-tags-vlm` für VLM-basierte Neuverschlagwortung.

**Wann Tags geschrieben werden.** Auf den CLIP-Ähnlichkeitsprofilen (`legacy`/`8gb` sowie `16gb`/`24gb`, wenn der VLM-Tagger-Durchgang nicht eingeplant ist) vergibt ein Multi-Pass-Scan die Tags im Embedding-Durchgang; Kategorie und Gesamtwert beim Scan sehen die Tags also bereits. Der Tag-Schritt nach dem Scan ist nur ein Fallback für noch ungetaggte Fotos. Ein einzelner `--pass`-Lauf (etwa `--pass embeddings`) schreibt keine Tags, und `--pass tags` auf einem CLIP-Profil bricht weiterhin ab und verweist auf `--recompute-tags`. Bestehende Zeilen behalten ihre Kategorie bis `--recompute-average`.

### Embedding-Modelle

Zwei Embedding-Modelle verfügbar, ausgewählt pro VRAM-Profil über `clip_config`:

| Konfiguration | Modell | Dimensionen | Verwendet von |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb-, 24gb-Profile |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy-, 8gb-Profile |

Embeddings treiben die semantische Verschlagwortung, Duplikaterkennung, Ähnliche-Fotos-Suche und CLIP+MLP-Ästhetik (legacy/8gb) an. Ein Modellwechsel erfordert das erneute Embedding aller Fotos (`--force`, `--pass embeddings` oder `--recompute-embeddings`).

## Gesichtserkennung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Gesichter für neue Fotos extrahieren (GPU, parallel) |
| `python facet.py --extract-faces-gpu-force` | Alle Gesichter löschen und neu extrahieren (GPU; im kommerziellen Modus mit dem permissiven Extraktor; benannte Personen bleiben erhalten) |
| `python facet.py --cluster-faces-incremental` | HDBSCAN-Clustering, behält alle Personen bei (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, behält nur benannte Personen bei (CPU) |
| `python facet.py --cluster-faces-force` | Vollständiges Re-Clustering, löscht alle Personen (CPU) |
| `python facet.py --suggest-person-merges` | Mögliche Personenzusammenführungen vorschlagen |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Strengeren Schwellenwert verwenden |
| `python facet.py --refill-face-thumbnails-incremental` | Fehlende Thumbnails erzeugen (CPU, parallel) |
| `python facet.py --refill-face-thumbnails-force` | ALLE Thumbnails neu erzeugen (CPU, parallel) |

## Thumbnail-Verwaltung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Rotation gespeicherter Thumbnails anhand der EXIF-Orientierung korrigieren |
| `python facet.py --refresh-thumbnails` | RAW-Thumbnails aus der kamerainternen Vorschau neu erstellen |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Dasselbe, mit mehr parallelen Lesevorgängen |

Liest die EXIF-Orientierung aus den Originaldateien und rotiert die gespeicherten Thumbnail-Bytes; für Fotos, die verarbeitet wurden, bevor es eine EXIF-Behandlung gab. Es liest nur den EXIF-Header und das gespeicherte Thumbnail, nicht die vollständigen Bilder.

`--refresh-thumbnails` rendert das gespeicherte Thumbnail jedes RAW-Fotos neu durch das Anzeigeprofil (zuerst die Kameravorschau, als Fallback das Demosaicing — siehe [CONFIGURATION.md](CONFIGURATION.md#raw-decode)). Es ist die Migration für eine Bibliothek, die gescannt wurde, bevor dieses Profil existierte: Von einem älteren Scan geschriebene Thumbnails tragen LibRaws automatische Aufhellung pro Aufnahme, die die Belichtungsunterschiede zwischen den Aufnahmen einer Belichtungsreihe einebnet. Es wird kein Modell geladen und keine Score-Spalte berührt — nur `photos.thumbnail` wird neu geschrieben.

Der Befehl ist durch den Speicherdurchsatz begrenzt, nicht durch die CPU, daher skaliert sein Aufwand mit der Bibliotheksgröße und der Geschwindigkeit der Festplatte oder des Netzlaufwerks der Bibliothek, nicht mit der Kernzahl der Maschine. `--refresh-thumbnails-workers` (Standard 8) legt fest, wie viele Dateien gleichzeitig gelesen werden: auf einem schnellen Netzlaufwerk erhöhen, wo jeder Lesevorgang wartend verbringt, auf einer langsamen lokalen Festplatte verringern. Es begrenzt auch die vollständigen Demosaicing-Vorgänge, auf die ein RAW ohne Vorschau zurückfällt, sodass sehr hohe Werte Arbeitsspeicher kosten.

Er ist fortsetzbar. Jeder committete Batch merkt sich, wie weit er gekommen ist, sodass ein mit Ctrl+C (oder durch ein getrenntes Laufwerk) gestoppter Lauf eine konsistente Datenbank hinterlässt, und der nächste `--refresh-thumbnails` dort fortsetzt, wo er aufgehört hat. Ein abgeschlossener Lauf löscht die Markierung, sodass ein späteres erneutes Ausführen von vorn beginnt.

Ein Foto, dessen frisches Rendering komplett schwarz zurückkommt, behält sein bestehendes Thumbnail und wird namentlich protokolliert. Das ist keine Paranoia: Ein schwer beschädigtes Panasonic-RW2 schlägt beim Dekodieren nicht fehl — LibRaw füllt es mit Nullen zu einem gültigen, formatfüllenden schwarzen Bild auf, statt fehlzuschlagen — sodass ohne diese Prüfung eine beschädigte Datei ein gutes Thumbnail stillschweigend durch ein schwarzes ersetzen würde. Ein solches Foto bleibt ungestempelt und wird beim nächsten Lauf erneut versucht, sodass es genügt, die Datei zu reparieren.

Ein Foto, das zu einer Belichtungsreihe gehört, wird ohne Kameravorschau und ohne jegliche Belichtungsverstärkung neu gerendert, sodass seine Kachel zeigt, was der Sensor aufgezeichnet hat (siehe [CONFIGURATION.md](CONFIGURATION.md#bracketed-frames-render-uncorrected)). Da die Zugehörigkeit zu einer Belichtungsreihe aus der Sequenzerkennung stammt, die nach einem Scan läuft, führen Sie diesen Befehl nach `--detect-sequences` aus, damit diese Kacheln das Rendering übernehmen.

### Was ein gespeichertes Thumbnail aktualisiert

Gespeicherte Thumbnails werden zur Scanzeit gebacken, sodass eine Bibliothek, die vor der Existenz des Anzeigeprofils gescannt wurde, im Galerie-Raster weiterhin das alte Rendering zeigt. `photos.render_version` verzeichnet, welche Pipeline das Thumbnail jeder Zeile erzeugt hat, und zwei Wege bringen es auf den aktuellen Stand:

| Weg | Deckt ab | Kosten |
|------|--------|------|
| Ein erneuter Scan (`python facet.py <verzeichnis>`) | Alles, was er scannt, Thumbnail und Histogramm | Vollständiger Scoring-Lauf |
| `--refresh-thumbnails` | Das Thumbnail jeder RAW-Zeile | Speicherbegrenzt, Stunden bei einer großen Bibliothek |

**Nichts geschieht von allein.** Die Detailansicht ist immer aktuell, weil `/image` in Echtzeit rendert, aber das Galerie-Raster liest `photos.thumbnail`, und keine Menge an Durchsuchen schreibt es neu. Genau dafür ist `--refresh-thumbnails` da, und deshalb zeigt die Galerie ein schließbares Banner, das die noch wartenden Zeilen zählt.

Die Zählung im Banner stammt aus einem `stats_cache`-Eintrag mit einer TTL von einer Stunde, direkt aktualisiert durch `--refresh-thumbnails` und durch `python database.py --refresh-stats`, sodass sie nach einem Scan hinter der Realität zurückbleiben kann.

## Diagnose

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --doctor` | Diagnoseprüfungen ausführen (Python, GPU, ONNX Runtime, Abhängigkeiten, Konfiguration, Datenbank) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | GPU-Hardware für die Diagnose simulieren |

Berichtet die Python-Version, den PyTorch/CUDA-Build, die GPU-Erkennung und den Treiber, das ONNX-Runtime-Paket mit Version und Execution Providers (läuft Facet auf CUDA, zusätzlich eine Testsitzung mit einem einzigen Knoten, die belegt, dass der GPU-Build wirklich lädt), die Empfehlung für das VRAM-Profil, optionale Abhängigkeiten und den Konfigurations-/Datenbankstatus. Wenn PyTorch die GPU nicht sehen kann, `nvidia-smi` aber schon, gibt es den `pip install`-Befehl zur Behebung des CUDA-Builds aus. Ist ONNX Runtime der falsche Build, kann es auf CUDA nicht laden oder ist es defekt (beide Pakete installiert oder der Import scheitert), gibt es den Befehl zur Reparatur aus (siehe [Installation › ONNX Runtime für die Gesichtserkennung](INSTALLATION.md#onnx-runtime-für-die-gesichtserkennung)).

`--simulate-gpu NAME` und `--simulate-vram GB` testen das Verhalten mit anderer Hardware. Beide erfordern `--doctor`; `--simulate-vram` erfordert `--simulate-gpu`.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --check-raw-rendering` | 20 stichprobenartig ausgewählte RAW-Fotos unter den alten und aktuellen Dekodiereinstellungen rendern |
| `python facet.py --check-raw-rendering 50` | Stattdessen 50 Fotos als Stichprobe |

Nur lesend: Es dekodiert eine Zufallsstichprobe direkt von der Festplatte und gibt die mittlere Leuchtdichte aus, die jedes Rendering erzeugt — LibRaws automatische Aufhellung pro Aufnahme, das Demosaicing mit fester Verstärkung für die Metriken und die kamerainterne Vorschau, die Thumbnails und Viewer verwenden. Damit lässt sich `raw_decode.bright` an eigenen Dateien prüfen, bevor man sich auf einen Scan oder einen `--refresh-thumbnails`-Lauf festlegt; die Spalten für festen Gain und Vorschau erhalten die Belichtungsleiter einer Belichtungsreihe, die Spalte für automatische Aufhellung ebnet sie ein.

## Modellinformationen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --list-models` | Verfügbare Modelle und VRAM-Anforderungen anzeigen |

## Gewichtungsoptimierung (Paarweiser Vergleich)

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --comparison-stats` | Statistiken paarweiser Vergleiche anzeigen |
| `python facet.py --optimize-weights` | Gewichte aus Vergleichen optimieren und speichern (alle Quellen, nach Zuverlässigkeit gewichtet); nur angewendet, wenn sie die aktuellen Gewichte bei Vergleichen schlagen, die vom Training ausgenommen waren (5-fache Kreuzvalidierung, die jedes Foto in einem Fold hält, dann ein einseitiger McNemar-Test mit p < 0.05 und mindestens 2 Prozentpunkten Gewinn). Beim Anwenden wird auch der `modifiers.bonus` der Kategorie neu zentriert, sodass ihre Fotos umsortiert statt alle nach oben oder unten verschoben werden; siehe [SCORING.md](SCORING.md) |
| `python facet.py --optimize-weights --optimize-force` | Optimierte Gewichte auch anwenden, wenn sie den Held-out-Test nicht bestehen (oder er nicht ausgeführt werden konnte) |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Trainingsdaten auf bestimmte Vergleichsquellen beschränken |
| `python facet.py --optimize-weights --optimize-category portrait` | Nur auf einer Kategorie trainieren und deren v4-`categories[].weights`-Block schreiben |
| `python facet.py --auto-tune-categories` | **Nur Superadmin** (im Mehrbenutzermodus `--user` übergeben): Pro-Kategorie-Bereitschaft der Vergleichslabels für die automatische Feinabstimmung der gemeinsamen globalen Gewichtungen berichten. Stub — berichtet nur die Bereitschaft; die Auto-Apply-Schleife ist bis zum Vorliegen von Labels zurückgestellt |
| `python facet.py --sync-label-comparisons` | Aus Bewertungen abgeleitete Paare (source=rating) aus Sternebewertungen/Favoriten/Ablehnungen neu aufbauen |
| `python facet.py --train-ranker` | Den persönlichen Ranker über [Embedding + Scores] trainieren und learned_scores schreiben (abhängig von der ausgelassenen k-fachen Genauigkeit gegenüber der aggregierten Baseline) |
| `python facet.py --train-ranker --ranker-category portrait` | Den Ranker nur auf einer Kategorie trainieren |
| `python facet.py --train-ranker --train-ranker-force` | learned_scores schreiben, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --train-ranker --user alice` | Training auf die eigenen Vergleiche dieses Benutzers beschränken (plus Alt-Zeilen von vor dem Mehrbenutzermodus) und dessen eigene learned_scores schreiben (Mehrbenutzermodus) |
| `python facet.py --train-keeper` | Den gelernten **Keeper-Ranking-Head** über Ihre Culling-Entscheidungen (`source='culling'`-Paare) trainieren und ihn nur persistieren, wenn er bei der ausgelassenen k-fachen Genauigkeit die Auto-Cull-Heuristikauswahl schlägt. Verbessert die Auto-Cull-Auswahl und das „besseres Foto in dieser Gruppe existiert"-Badge. Fällt auf die Heuristik zurück, bis genug Culling-Paare vorliegen. Läuft, wie `--train-ranker`, automatisch nach Auswahlbestätigungen |
| `python facet.py --train-keeper --train-keeper-force` | Den Keeper-Ranking-Head persistieren, auch wenn seine Genauigkeitsschwelle nicht erreicht wird (berücksichtigt auch `--ranker-category` und `--user`) |
| `python facet.py --report-unreviewed-bursts` | Berichten, wie viele Serienbild-Gruppen ungeprüft bleiben (nur lesend) |
| `python facet.py --eval-iqa-srcc` | Spearman-SRCC jeder IQA-/Ästhetik-Metrik gegenüber Ihren Sternebewertungen berichten (nur lesend) |
| `python facet.py --evaluate-models SLOT` | Kandidatenmodelle für einen Slot (`aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`) danach einordnen, wie oft sie mit Ihren paarweisen Entscheidungen in der Tabelle comparisons übereinstimmen; `--candidates a,b` (`stored:<Spalte>` oder ein registrierter Name) und `--eval-out PFAD` (Standard `.facet_cache/eval/<slot>-<Zeitstempel>.json`) präzisieren dies (nur lesend). Die Gesichts-Slots (`faces-detect`: `yunet`, `yunet@<conf>`, `blazeface`; `faces-recognize`: `sface`, `sface@<Schwelle>`; `faces-centroid`: stimmt SFace-`merge_threshold` / Auto-Merge auf Centroid-Ebene gegen die InsightFace-Personen ab; `blink`: variiert die Blinzel-Schwelle des permissiven Analyzers gegen die gespeicherten InsightFace-Blinzel-Flags) messen stattdessen die Übereinstimmung mit den gespeicherten InsightFace-Gesichtern an einer Stichprobe mit festem Seed und gelten nur für Bibliotheken im Standardmodus; `--limit N` begrenzt die Fotos (Standard 600) bzw. Referenzgesichter (Standard 1200) |
| `python facet.py --mine-insights` | Data-Mining-Bericht: Label-Inventar, Metrik-Label-Korrelationen, Kategorienverteilung, Perzentil-Drift, Vergleichsgesundheit |
| `python facet.py --mine-insights report.json` | Dasselbe, schreibt zusätzlich den vollständigen Bericht als JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Bewertungsgewichtungen pro Kategorie gegen den [AVA-Datensatz](https://github.com/imfing/ava_downloader) kalibrieren, indem die SRCC gegenüber den AVA-Mean-Opinion-Scores maximiert wird (nur lesend; gibt vorgeschlagene Gewichtungen aus) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Auf bestimmte Kategorien beschränken und die optimierten Gewichtungen zurück in `scoring_config.json` schreiben |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Den Optimierer wählen (`de` = differentielle Evolution, Standard; `nelder-mead` = lokaler Simplex) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Auch gegen die semantischen AVA-Tags kalibrieren (`--ava-tags-only`, um ausschließlich Tags zu verwenden; `--apply-filters`, um auch die Filterschwellenwerte der Kategorien feinabzustimmen) |

## Konfiguration

`scoring_config.json` ist eine **Überschreibung**: Sie enthält nur die von Ihnen
geänderten Einstellungen und wird über die in `config/scoring_config.default.json`
ausgelieferten Standardwerte aufgelöst. Eine fehlende Konfigurationsdatei bedeutet
daher eine Installation, die vollständig auf diesen Standardwerten läuft, nicht eine
defekte — siehe [Konfiguration](CONFIGURATION.md#standardwerte-und-ihre-überschreibung).

Die Umgebungsvariable `FACET_CONFIG` liefert, wenn gesetzt, den Standardpfad zu `scoring_config.json` für `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` und `viewer.py`, sofern diese ohne explizites `--config` ausgeführt werden; `--config` überschreibt sie immer. `viewer.py` (und der von ihm gestartete `api/`-Server) hat keine eigene `--config`-Option — `FACET_CONFIG` ist daher der einzige Weg, ihn umzulenken. Benennt die Variable — oder `--config` — eine nicht vorhandene Datei, ist das ein Fehler und keine leere Überschreibung: Ein Pfad, den jemand BENANNT hat und der fehlt, verrät einen Tippfehler oder einen defekten Mount, daher verweigert der Viewer den Auth-Pfad für eine offene Installation, statt zu schließen, dass die Installation keine Passwörter hat, und protokolliert einen Fehler mit dem fehlenden Pfad. Nur der *geerbte* Standardpfad darf fehlen.

Ist keine von beiden gesetzt, lesen `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py` und `calibrate.py` eine `scoring_config.json` im **Arbeitsverzeichnis**, sofern vorhanden — eine Fotosammlung mit eigener Konfiguration wird also mit dieser bewertet — und andernfalls die neben der Installation. Nur dieser geerbte Rückfall darf fehlen: Er bedeutet eine Installation, die mit den ausgelieferten Standardwerten läuft.

Der Viewer `viewer.py` und der von ihm gestartete `api/`-Server machen diesen Umweg über das Arbeitsverzeichnis nie mit: Sie lösen nur `FACET_CONFIG` auf, sonst die Datei neben der Installation — niemals eine `scoring_config.json`, die zufällig in dem Verzeichnis liegt, aus dem heraus sie gestartet wurden. Das ist wichtig, weil die Konfiguration des Viewers diejenige ist, die die Passwörter des Betreibers trägt: Wer ihn aus einer Fotosammlung heraus startet, bekommt nicht deren Konfiguration, und fehlt auch neben der Installation eine, fällt er still auf die ausgelieferten Standardwerte zurück — ein leeres `viewer.edition_password` und kein Viewer-Passwort, sodass jede lesende Route anonym bedient wird.

```bash
# 1. --config hat Vorrang vor allem. Eine fehlende Datei ist hier ein FEHLER, keine leere Überschreibung.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG liefert den Standardpfad, wenn --config fehlt (Docker setzt das).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # liest /config/scoring_config.json
python facet.py --config other.json /photos   # --config hat weiterhin Vorrang

# 3. Keines von beiden: eine Konfiguration im ARBEITSVERZEICHNIS gewinnt bei den
#    CLI-Werkzeugen, eine Fotosammlung kann also ihre eigene mitbringen; viewer.py kennt diesen Schritt nicht -- siehe unten.
cd /photos/client-shoot          # enthält eine eigene scoring_config.json
python /opt/facet/facet.py .     # bewertet mit /photos/client-shoot/scoring_config.json

# 4. Keines von beiden und hier nichts: Rückfall auf die Datei neben der Installation.
cd /tmp
python /opt/facet/facet.py /photos   # liest /opt/facet/scoring_config.json
                                     # fehlt sie dort, laufen die Standardwerte

# 5. viewer.py macht diesen Umweg über das Arbeitsverzeichnis nie mit, anders als Fall 1 bis 4.
cd /photos/client-shoot          # enthält eine eigene scoring_config.json -- hier wirkungslos
python /opt/facet/viewer.py      # liest weiterhin /opt/facet/scoring_config.json (oder $FACET_CONFIG)
```

Nur Fall 4 und 5 dürfen nichts finden. Fall 1 und 2 nennen einen Pfad, daher bricht eine fehlende Datei den Befehl ab, statt still mit Werten zu bewerten, die niemand gewählt hat.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --validate-categories` | Kategoriekonfigurationen validieren |

## Verschlagwortung

| Befehl | Beschreibung |
|---------|-------------|
| `python tag_existing.py` | Tags zu nicht verschlagworteten Fotos mit gespeicherten CLIP-Embeddings hinzufügen |
| `python tag_existing.py --dry-run` | Tags vorab anzeigen, ohne zu speichern |
| `python tag_existing.py --threshold 0.25` | Eigene Ähnlichkeitsschwelle (Standard: `tag_threshold_percent` des aktiven Profils, ausgeliefert als 8, also 0.08) |
| `python tag_existing.py --max-tags 3` | Tags pro Foto begrenzen (Standard: 5) |
| `python tag_existing.py --force` | Alle Fotos neu verschlagworten |
| `python tag_existing.py --db custom.db` | Benutzerdefinierte Datenbank verwenden |
| `python tag_existing.py --config my.json` | Benutzerdefinierte Konfiguration verwenden |

Auf einem CUDA-Rechner kodiert ein SigLIP-Profil (`16gb`, `24gb`) das Tag-Vokabular jetzt in fp16, wie es der Single-Pass-Scorer schon tat; `tag_existing.py` hat es früher in fp32 geladen. `python tag_existing.py`, `python tag_existing.py --force`, `python facet.py --tag-untagged` und der Verschlagwortungsschritt am Ende eines Scans nutzen denselben Loader. Gemessen an 49 Fotos änderte sich das Tag-Set bei 2 davon (4 %): Führen Sie `python tag_existing.py --force` erneut aus, um früher verschlagwortete Fotos neu zu verschlagworten. CPU und die CLIP-ViT-L-14-Profile (`legacy`, `8gb`) bleiben unverändert.

Der Verschlagwortungsschritt am Ende eines Scans lädt dieses Modell nur, wenn er etwas zu tun hat. Er wird mit einer Logzeile übersprungen, wenn `tagging.enabled` auf `false` steht oder wenn kein Foto auf Tags wartet (ein gespeichertes Embedding, aber keine Tags); ein Scan, der nichts zu verschlagworten hat, lädt dafür kein SigLIP 2 oder CLIP mehr neu. `python tag_existing.py`, `--force` und `--tag-untagged` sind nicht betroffen.

## Datenbankvalidierung

| Befehl | Beschreibung |
|---------|-------------|
| `python validate_db.py` | Datenbankkonsistenz validieren (interaktiv) |
| `python validate_db.py --auto-fix` | Alle Probleme automatisch beheben |
| `python validate_db.py --report-only` | Berichten, ohne nachzufragen |
| `python validate_db.py --db custom.db` | Benutzerdefinierte Datenbank validieren |

Prüft: Score-Bereiche, Gesichtsmetriken, BLOB-Beschädigung, Embedding-Größen, verwaiste Gesichter, statistische Ausreißer.

## Datenbankpflege

| Befehl | Beschreibung |
|---------|-------------|
| `python database.py` | Schema initialisieren/aktualisieren. Baut außerdem fehlende Galerie- und Post-Scan-Indizes, wie ein Scan bei seinem Start, und protokolliert vor und nach jedem eine Zeile (siehe [VIEWER.md](VIEWER.md#galerie-indizes-und-zähler-cache)). Der erste Lauf nach dem Upgrade von 1.20 baut neun davon; bei einer Bibliothek mit 130.000 Fotos brauchte allein `idx_gallery_aggregate` 45,6 bis 54,1 s, `idx_post_scan` zusammen mit `idx_date_asc_cover`, allein gebaut, auf einem ruhigen Rechner etwa 55 s, auf einem ausgelasteten bis zu etwa 67 s. Bei einer großen Bibliothek einmal vor dem Start des Viewers ausführen, der sie sonst im Hintergrund baut und währenddessen Speichern ablehnt, solange ein Index geschrieben wird. |
| `python database.py --info` | Schemainformationen anzeigen |
| `python database.py --migrate-tags` | Einmaliger Aufbau der photo_tags-Lookup-Tabelle (10-50x schnellere Abfragen). Ist sie gefüllt, halten Scans, `--recompute-tags`, `--recompute-tags-vlm` und `tag_existing.py` sie pro Foto aktuell; eine nie gefüllte Tabelle wird nie implizit gefüllt, und Leser nutzen bis dahin den `LIKE`-Fallback |
| `python database.py --rebuild-fts` | FTS5-Volltextsuchindex aus Bildunterschriften/Tags neu aufbauen |
| `python database.py --populate-vec` | sqlite-vec-Vektorsuchtabelle aus Embeddings befüllen |
| `python database.py --refresh-stats` | Statistik-Cache aktualisieren |
| `python database.py --compact-config` | `scoring_config.json` als die Überschreibung umschreiben, die sie ist, und dabei jeden Wert verwerfen, der dem ausgelieferten Standard entspricht (verlustfrei; legt zuerst eine Sicherung mit `0600` an) |
| `python database.py --stats-info` | Cache-Status und -Alter anzeigen |
| `python database.py --vacuum` | Speicher zurückgewinnen, defragmentieren |
| `python database.py --analyze` | Statistiken des Query-Planers aktualisieren |
| `python database.py --optimize` | VACUUM und ANALYZE ausführen |
| `python database.py --backup` | Einen WAL-sicheren DB-Snapshot mit Zeitstempel schreiben (rotiert auf `--keep N`, Standard 3) |
| `python database.py --export-viewer-db` | Leichtgewichtige Viewer-Datenbank exportieren (entfernt BLOBs, verkleinert Thumbnails; inkrementell, wenn die Ausgabe vorhanden ist) |
| `python database.py --export-viewer-db --force-export` | Vollständigen Re-Export erzwingen, auch wenn die Viewer-DB bereits vorhanden ist |
| `python database.py --cleanup-orphaned-persons` | Personen ohne zugehörige Gesichter entfernen |
| `python database.py --cleanup-missing-photos` | Fotos, die nicht mehr auf der Festplatte sind, aus der Datenbank entfernen (kaskadierende Löschungen bereinigen Tags, erkannte Gesichter usw.; löscht außerdem Album-Mitgliedschaften und den Vektorindex und macht den Statistik-Cache ungültig, außer dem darin gespeicherten Bibliothekszustand — Perzentil-Snapshot, Immich-Synchronisationsstand, trainierte Keeper-Heads und Ranker-Metriken sowie die Marker für Thumbnail-Aktualisierung und Reparatur; die Vergleichszähler des automatischen Neutrainings werden zurückgesetzt) |
| `python database.py --cleanup-missing-photos --dry-run` | Fehlende Dateien vorab anzeigen, ohne zu löschen |
| `python database.py --cleanup-missing-photos --force` | Auch fortfahren, wenn jedes Foto fehlend erscheint (Schutz vor dem Löschen von allem, wenn ein Volume nicht eingehängt ist) |
| `python database.py --migrate-storage-fs` | Thumbnails und Embeddings aus Datenbank-BLOBs in das Dateisystem migrieren |
| `python database.py --migrate-storage-db` | Thumbnails und Embeddings aus dem Dateisystem zurück in die Datenbank migrieren |
| `python database.py --add-user alice --role admin` | Einen Benutzer hinzufügen (fragt nach Passwort) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Benutzer mit Anzeigenamen hinzufügen |
| `python database.py --migrate-user-preferences --user alice` | Bewertungen von photos in user_preferences kopieren |

**Performance-Tipp:** Bei großen Datenbanken (50k+ Fotos) `--migrate-tags`, `--rebuild-fts` und `--populate-vec` einmal ausführen, dann regelmäßig `--optimize`.

## Web-Viewer

| Befehl | Beschreibung |
|---------|-------------|
| `python viewer.py` | Server unter http://localhost:5000 starten (API + Angular SPA) |
| `python viewer.py --port 5001` | An einen anderen Port binden (oder die Umgebungsvariable `PORT` setzen; Standard 5000) |
| `python viewer.py --host 127.0.0.1` | An eine bestimmte Schnittstelle binden (Standard `0.0.0.0`) |
| `python viewer.py --production` | Produktionsmodus (uvicorn-Worker) |
| `python viewer.py --production --workers 4` | Produktionsmodus mit N Workern (Standard 1) |

## Auto-Cull im Terminal

Auto-Cull ohne Oberfläche: die Terminal-Variante des [Auto-Culls](VIEWER.md#auto-cull) des Viewers. Ablehnungen werden in die Datenbank geschrieben; Originale werden nie verschoben oder gelöscht, und `--copy-keepers` kopiert die behaltenen Fotos in einen Ordner.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Sortiert aus, was schon in der Datenbank ist, begrenzt auf `PATH` (ein Ordner oder eine Datei); ohne Argument oder mit `all` die ganze Bibliothek. **Probelauf: zeigt den Plan und ändert nichts** |
| `python facet.py /path --auto-cull` | Scannen, dann aussortieren: scannt `/path` tatsächlich und sortiert dann die Fotos darin aus. Abgelehnt zusammen mit `--auto-cull PATH`, `--resume`, `--retry-failed` und `--watch` |
| `--apply` | Schreibt das Aussortieren: Ablehnungen, Markierungen geprüfter Gruppen und `source='culling'`-Vergleichspaare |
| `--copy-keepers DIR` | Kopiert jedes nicht abgelehnte Foto im Geltungsbereich mit seinen gleichnamigen RAW- / `.xmp`-Begleitdateien nach `DIR` |
| `--cull-strictness N` | Behalte-Budget 0–100, höher behält weniger pro Gruppe (Standard: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Mindestanzahl behaltener Fotos pro Gruppe (Standard `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Welche Gruppen aussortiert werden (Standard `all`) |
| `--cull-min-score X` | Lehnt zusätzlich Einzelfotos ab, deren Gesamtwertung unter `X` liegt |
| `--cull-trim-brackets` | Lehnt zusätzlich redundante Aufnahmen von Belichtungsreihen ab (das `trim_brackets` des Viewers) |
| `--user NAME` | Wessen Bewertungen und Ablehnungen verwendet werden; bei einer Mehrbenutzer-Installation **erforderlich** |

- **Standardmäßig Probelauf.** Ohne `--apply` wird nichts geschrieben: keine Ablehnung, kein Vergleichspaar, keine Cache-Zeile, und der Ordner von `--copy-keepers` wird nicht angelegt. Der Befehl gibt eine Zusammenfassung aus: `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` und mit `--copy-keepers` zusätzlich `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` im Probelauf). `--apply` betrifft nur das Aussortieren: Scannen-dann-aussortieren scannt immer zuerst tatsächlich, und das Aussortieren läuft nur, wenn der Scan abgeschlossen wurde. `--dry-run` wird mit `--auto-cull` abgelehnt. Die eine Ausnahme: Existiert ein trainiertes Keeper-Modell, kann sein Laden `scoring_config.json` neu schreiben, wenn seine Gewichte korrigiert werden müssen (bestehendes Verhalten, geteilt mit dem Auto-Cull des Viewers).
- **Regeln.** Gruppen folgen denselben Regeln wie das [Auto-Cull des Viewers](VIEWER.md#auto-cull): Jede behält ihr bestes Foto plus alles innerhalb der Strenge-Marge, begrenzt durch `--cull-min-keep`; Belichtungsreihen, Panoramen und HDR-Panoramen bleiben vollständig erhalten. `--apply` erfasst Ablehnungen und Vergleichspaare genau wie `POST /api/culling/auto`; ein Highlights-Album wird nicht gefüllt. Die Einstellungen [`auto_cull`](CONFIGURATION.md#auto-cull), `burst_scoring` und `similarity_groups` stammen aus der **Server**-Konfiguration (`FACET_CONFIG` oder der Standardpfad), nicht aus `--config`; weichen beide im Mehrbenutzermodus voneinander ab, endet der Befehl mit Code 1.
- **Geltungsbereich.** Der Geltungsbereich vergleicht lokale echte Pfade; Zeilen, die vor dem Setzen eines `path_mapping` gespeichert wurden, lassen sich nicht nach Ordner eingrenzen — verwenden Sie `all` oder scannen Sie neu. Ein Serienbild, eine Belichtungsreihe oder ein Panorama mit Mitgliedern außerhalb des Geltungsbereichs wird vollständig übersprungen und in `spanning_skipped` gezählt; Ähnlichkeits- und Szenengruppen werden nur innerhalb des Geltungsbereichs berechnet.
- **`--cull-min-score` gibt es nur in der Kommandozeile** und ist vorsichtig: Es berührt nie Aufnahmen von Belichtungsreihen oder Panoramen, Fotos ohne Wertung, Favoriten, Fotos mit Sternebewertung, mit **Behalten** markierte Fotos oder ein Foto, das ein früheres Aussortieren schon behalten oder abgelehnt hat (wird nie erneut nach Wertung beurteilt); ein zweiter Lauf lehnt daher nichts Neues ab. Mitglieder von Serienbild-Gruppen bleiben immer verschont; Mitglieder von Ähnlichkeitsgruppen nur, wenn der Gruppierungsdurchlauf die Gruppe gefunden hat (nach bestem Bemühen: Er liest die neuesten `similarity_groups.max_photos` Fotos im Geltungsbereich, Standard `10000`, und verwirft Cluster größer als `similarity_groups.max_group_size`, Standard `50`); Mitglieder einer Szenengruppe nur mit `--cull-group-by scene` — mit dem Standard `all` wird ein Foto, das nur das Zeitfenster einer Szene teilt, also weiterhin nach Wertung beurteilt.
- **Kopieren.** `--copy-keepers` kopiert jedes nicht abgelehnte Foto im Geltungsbereich samt gleichnamigen RAW- und `.xmp`-Begleitdateien, nie ein abgelehntes Foto oder dessen Begleitdateien; gleichnamige Dateien aus verschiedenen Ordnern erhalten das Suffix `_1`, und ein erneuter Lauf in denselben Ordner überspringt identische Dateien (gleiche Größe und Zeit, als `already_present` gezählt). `DIR` darf den Geltungsbereich oder die Bibliotheksordner weder gleichen, noch darin liegen, noch sie enthalten (auch im Probelauf geprüft, Code 1), sonst würde der nächste Scan die Kopien aufnehmen. Dateien werden über die Positivliste der Scan-Verzeichnisse aufgelöst (`users.*.directories` / `viewer.scan_directories` in der Server-Konfiguration): Wird deshalb jedes Foto übersprungen, endet der Befehl mit Code 3 und nennt diese Schlüssel. Außerdem wird ein Ordner abgelehnt, der sich mit einer von Facet gespeicherten, früher gescannten Wurzel überschneidet.
- **Benutzer.** Bei einer Mehrbenutzer-Installation ist `--user` erforderlich (Code 1 ohne Angabe oder mit unbekanntem Benutzer). Bei einer Einzelbenutzer-Installation wird `--user` mit einer Warnung ignoriert, und der Befehl sieht alle Fotos, auch wenn ein Viewer-Passwort gesetzt ist. `--apply` nimmt die Bibliothekssperre; ein Probelauf nimmt keine.
- **Aufruffehler (Code 2).** `--apply`, `--copy-keepers` oder ein `--cull-*` ohne `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` oder `--watch` mit `--auto-cull`; `--auto-cull PATH` zusammen mit Positionsverzeichnissen; Strenge außerhalb von 0–100 oder `--cull-min-keep` unter 1. `--apply` ist jetzt ein exaktes Flag, die Abkürzung wählt also nicht mehr `--apply-recommendations`.
- **Exit-Codes.** `0` Erfolg (Probelauf und null Gruppen eingeschlossen); `1` Fehler bei Voraussetzung, Konfiguration oder Datenbank (fehlende Datenbank, fehlendes `--user`, Kopierziel überlappt die Bibliothek); `2` Aufruffehler; `75` `--apply` fand die Bibliothekssperre von einem anderen Auftrag gehalten; `3` das Aussortieren war erfolgreich, aber der Kopierschritt hatte Fehler oder kopierte nichts, weil jedes Foto übersprungen wurde. Ein Probelauf, dessen behaltene Fotos alle von der Positivliste der Scan-Verzeichnisse übersprungen würden, endet ebenfalls mit Code `3`. Bei Scannen-dann-aussortieren protokolliert ein unterbrochener Scan, dass das Aussortieren übersprungen wurde.
- **Nachtrainieren.** Der Timer für das automatische Nachtrainieren überlebt den CLI-Prozess nicht: Der Vergleichszähler bleibt erhalten, und das Nachtrainieren läuft bei der nächsten Viewer-Aktion oder mit einem `--train-*`-Befehl. Der erste Lauf kann `.facet_secret` anlegen (der Import der API-Schicht tut das, wie bei `--report-unreviewed-bursts`).

## Häufige Arbeitsabläufe

### Ersteinrichtung
```bash
python facet.py /path/to/photos     # Alle Fotos bewerten (automatischer Multi-Pass)
python facet.py --cluster-faces-incremental # Gesichter clustern
python database.py --migrate-tags    # Schnelle Tag-Abfragen aktivieren
python viewer.py                    # Ergebnisse ansehen
```

### Nach Konfigurationsänderungen
```bash
python facet.py --recompute-average                # Alle Scores mit neuen Gewichtungen aktualisieren
python facet.py --recompute-category portrait      # Nur eine Kategorie aktualisieren (schneller)
```

### Einrichtung der Gesichtserkennung
```bash
python facet.py /path               # Gesichter während des Scans extrahieren
python facet.py --cluster-faces-incremental     # In Personen gruppieren
python facet.py --suggest-person-merges         # Duplikate finden
# /persons im Viewer verwenden, um zusammenzuführen/umzubenennen
```

### Eine Aufnahmesession im Terminal aussortieren
```bash
python facet.py --auto-cull /photos/wedding                    # Plan ansehen, nichts wird geschrieben
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                           # Ablehnen, dann die behaltenen Fotos kopieren
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Scannen, dann aussortieren
```

### Mehrbenutzer-Einrichtung
```bash
# Benutzer hinzufügen (fragt nach Passwort)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# scoring_config.json bearbeiten, um directories und shared_directories festzulegen
# Vorhandene Bewertungen zu einem Benutzer migrieren
python database.py --migrate-user-preferences --user alice
```

### Verschlagwortungsmodell wechseln
```bash
# scoring_config.json bearbeiten: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Mit neuem Modell neu verschlagworten
```

### VRAM-Profil wechseln
```bash
# scoring_config.json bearbeiten: "vram_profile": "auto"
# Oder bestimmtes verwenden: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Verteilungen prüfen
python facet.py --recompute-average        # Neue Gewichtungen anwenden
```
