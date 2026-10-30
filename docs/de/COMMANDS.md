# Befehlsreferenz

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · **Deutsch** · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · [简体中文](../zh/COMMANDS.md)

[Scannen](#scannen) · [Vorschau & Export](#vorschau--export) · [Neuberechnungen](#neuberechnungen) · [Gesichtserkennung](#gesichtserkennung) · [Thumbnail-Verwaltung](#thumbnail-verwaltung) · [Diagnose](#diagnose) · [Modellinformationen](#modellinformationen) · [Gewichtungsoptimierung](#gewichtungsoptimierung-paarweiser-vergleich) · [Konfiguration](#konfiguration) · [Verschlagwortung](#verschlagwortung) · [Datenbankvalidierung](#datenbankvalidierung) · [Datenbankpflege](#datenbankpflege) · [Web-Viewer](#web-viewer) · [Häufige Arbeitsabläufe](#häufige-arbeitsabläufe)

> Anforderungs-Tags, die nachstehend verwendet werden: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM-Profil). Siehe die [Funktionsmatrix](INSTALLATION.md#funktionsanforderungen).

## Scannen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path` | Verzeichnis scannen (Multi-Pass, automatische VRAM-Erkennung) |
| `python facet.py /path --force` | Bereits verarbeitete Dateien erneut scannen |
| `python facet.py /path --single-pass` | Alle Modelle gleichzeitig laden; nur `legacy`/`8gb` (siehe [Verarbeitungsmodi](#verarbeitungsmodi)) |
| `python facet.py /path --pass quality` | Nur die TOPIQ-Qualitätsbewertung ausführen |
| `python facet.py /path --pass quality-iaa` | Nur die TOPIQ-IAA-Bewertung des ästhetischen Verdienstes ausführen |
| `python facet.py /path --pass quality-face` | Nur die TOPIQ-NR-Face-Qualitätsbewertung ausführen |
| `python facet.py /path --pass quality-liqe` | Nur LIQE-Qualität + Verzerrungsdiagnose ausführen |
| `python facet.py /path --pass tags` | Nur die Verschlagwortung ausführen (Modell hängt vom VRAM-Profil ab) |
| `python facet.py /path --pass composition` | Nur die SAMP-Net-Erkennung von Kompositionsmustern ausführen |
| `python facet.py /path --pass faces` | Nur die InsightFace-Gesichtserkennung ausführen |
| `python facet.py /path --pass embeddings` | Nur die CLIP/SigLIP-Embedding-Extraktion ausführen (schreibt keine Tags) |
| `python facet.py /path --pass saliency` | Nur die BiRefNet-Erkennung der Motiv-Salienz ausführen |
| `python facet.py /path --db custom.db` | Benutzerdefinierte Datenbankdatei verwenden |
| `python facet.py /path --config my.json` | Benutzerdefinierte Bewertungskonfiguration verwenden |
| `python facet.py --resume` | Den letzten unterbrochenen, fehlgeschlagenen oder abgestürzten Scan fortsetzen |
| `python facet.py --retry-failed` | Dateien erneut verarbeiten, die im letzten Scan fehlgeschlagen sind (`--retry-failed all` für alle Läufe) |
| `python facet.py /path --force-since 2026-01-01` | Wie `--force`, nur für Fotos, die zuletzt vor dem Datum gescannt wurden |
| `python facet.py /path --watch` | Erneut scannen, sobald neue Fotos auftauchen (erfordert `pip install watchdog`; `--watch-debounce N`, Standard 30 s) |
| `python facet.py /path --force-low-space` | Die Speicherplatzprüfung vor dem Scan überspringen |

**`--resume`** setzt auch einen Scan fort, der durch Absturz, Speichermangel oder Stromausfall beendet wurde: einen Lauf, der noch als `running` markiert ist und dessen Heartbeat älter als `processing.scan_stale_seconds` ist (Standard 120). Es verwendet die Verzeichnisse dieses Laufs erneut. Mit `--force` überspringt es Dateien, die seit dem Start des Laufs bereits neu bewertet wurden. Es verweigert den Start, wenn ein anderer Scan noch aktiv zu sein scheint.

### Scan-Buchhaltung

Facet zeichnet jeden Scan (Status, Modus, Verzeichnisse, Zähler) und jeden Fehler pro Datei auf. Strg+C markiert den Lauf als `interrupted`, sodass `--resume` ihn fortsetzen kann. Fehlgeschlagene Dateien werden aufgelistet und nur mit `--retry-failed` erneut versucht. Der Viewer zeigt den Scan-Fortschritt anhand der `@FACET_PROGRESS`-Zeilen der CLI.

### Verarbeitungsmodi

**Multi-Pass (Standard):** erkennt den VRAM und lädt die Modelle nacheinander. Jeder Pass lädt sein Modell, verarbeitet alle Fotos und entlädt es dann, sodass hochwertige Modelle auch mit begrenztem VRAM laufen.

**Single-Pass (`--single-pass`):** lädt alle Modelle gleichzeitig. Schneller, benötigt aber mehr VRAM.

- Die Ästhetik wird mit dem CLIP+MLP-Kopf bewertet, daher gilt der Modus für die Profile `legacy` und `8gb`.
- Bei `16gb` und `24gb` ist das Ästhetikmodell TOPIQ, das nur Multi-Pass ausführt. Eine Single-Pass-Anforderung (`--single-pass` oder `processing.mode: "single-pass"`) protokolliert eine Warnung und läuft als Multi-Pass.
- `--pass NAME` und `--dry-run` überspringen diese Prüfung.
- Im kommerziellen Modus bleibt Single-Pass verfügbar, weil dort das native Q-ReAlign die Ästhetik bewertet.

**Hinweis zum Upgrade:** Frühere Versionen speicherten bei einem Single-Pass-Scan unter `16gb`/`24gb` für jedes Foto eine neutrale Ästhetik von 5,0. Scannen Sie diese Ordner im Multi-Pass-Modus mit `--force` neu. So finden Sie sie: `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Bestimmter Pass (`--pass NAME`):** führt nur einen Pass aus, um einzelne Metriken ohne vollständige Neuverarbeitung zu aktualisieren.

| Pass | Modell | Ausgabe | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic`-Score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (künstlerisches Verdienst, AVA-trainiert) | Geteilt mit TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (Gesichtsqualität) | Geteilt mit TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + Verzerrungsdiagnose (Unschärfe, Überbelichtung, Rauschen) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantische Tags aus dem konfigurierten Vokabular | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 Muster) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Gesichter, Landmarken, Blinzeln, Erkennungs-Embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 oder SigLIP 2 NaFlex | `clip_embedding` für Ähnlichkeit und Verschlagwortung | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

Die Multi-Pass-Messungen verwenden monotone Uhren. EXIF-Batchzeit und summierte Worker-Sekunden der Fallbacks sind in der Dekodierzeit enthalten; parallele Fallbacks können sich überlappen. Aggregation, Vorschaubilder (einschließlich Quelldateilesen) und Speichern ohne Vorschaubilder sind getrennte Intervalle; Speichern enthält Vorbereitung und Commit. Eingeschränkte Durchläufe überspringen Aggregation und Foto-Vorschaubilder. Bestehende Dekodier-/Modellüberlappung und verschachtelte Ebenenrekonstruktionen bleiben unverändert: nicht alle Timer addieren oder EXIF-Worker-Sekunden als Laufzeitanteil interpretieren. Single-Pass ist ausgenommen. Für eine Baseline eine feste Kopie von 500 RAW/JPEG in eine Testdatenbank scannen; Zusammenfassung, Revision, Profil, Worker, Blockgröße, Speicher und Cachebedingungen festhalten. Unter gleichen Bedingungen wiederholen. Kein Referenzdatensatz oder Vorher-/Nachher-Benchmark vorhanden; kein Geschwindigkeitsgewinn behauptet.

## Vorschau & Export

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path --dry-run` | 10 Beispielfotos bewerten, ohne zu speichern |
| `python facet.py /path --dry-run --dry-run-count 20` | 20 Beispielfotos bewerten |
| `python facet.py --export-csv` | Alle Scores in eine CSV mit Zeitstempel exportieren |
| `python facet.py --export-csv output.csv` | In eine bestimmte CSV-Datei exportieren |
| `python facet.py --export-json` | Jede gespeicherte Metrik in eine JSON mit Zeitstempel exportieren |
| `python facet.py --export-json output.json` | In eine bestimmte JSON-Datei exportieren |
| `python facet.py --export-manifest` | `facet_manifest.json` für externe Werkzeuge wie das Lightroom-Classic-Zusatzmodul schreiben |
| `python facet.py --export-manifest /path` | Das Manifest auf Fotos unterhalb eines Pfads beschränken |
| `python facet.py --export-manifest --user alice` | Mehrbenutzermodus: Alices Bewertungen verwenden (Tags und Scores bleiben global) |
| `python facet.py --import-lightroom FILE` | Bewertungen, Picks und Ablehnungen des Zusatzmoduls importieren; Lightroom gewinnt |
| `python facet.py --import-lightroom FILE --user alice` | Mehrbenutzermodus: Alices Bewertungen schreiben; bei einer Mehrbenutzer-Installation **erforderlich** |
| `python facet.py --import-sidecars` | Bewertungen, Labels, Keep/Ablehnung, manuelles GPS und Stichwörter aus XMP-Sidecars importieren |
| `python facet.py --import-sidecars /path` | Nur für Fotos unterhalb eines Pfads importieren |
| `python facet.py --import-sidecars /path --dry-run` | Einen JSON-Plan mit Änderungen und Konflikten ausgeben; schreibt nichts |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Nur diese Gruppen importieren: `review` (Sterne, Favorit, Ablehnung, Keep), `gps`, `keywords` (Standard: alle) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Bewertungsfelder auch über eine neuere lokale Änderung (`newer_local_edit`) hinweg anwenden; zuvor mit `--dry-run` prüfen |
| `python facet.py --import-sidecars --user alice` | Mehrbenutzermodus: Bewertungen und Keep/Ablehnung in Alices Konto importieren, für Fotos, die sie sehen kann |
| `python facet.py --import-sidecars --sidecar-naming full` | `<image.ext>.xmp` / `<image.ext>.facet.xmp` lesen (Standard); die neuere Datei gewinnt |
| `python facet.py --import-sidecars --sidecar-naming basename` | `<image>.xmp` (ohne Endung) lesen; geteilte Basisnamen ablehnen |
| `python facet.py --import-sidecars --sidecar-naming auto` | Beide Benennungen akzeptieren; ein Foto mit beiden überspringen |
| `python facet.py --import-sidecars --overwrite-manual-gps` | In Facet bereits gesetztes manuelles GPS durch das der Sidecar ersetzen |
| `python facet.py --export-sidecars` | `<image>.xmp`-Sidecars für alle Fotos schreiben oder zusammenführen |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Zusätzlich Facet-eigene Stichwörter entfernen, die nicht mehr vorhanden sind (erfordert ExifTool) |
| `python facet.py --export-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfads exportieren |
| `python facet.py --export-sidecars --user alice` | Mehrbenutzermodus: Alices Bewertungen und Keep/Ablehnung exportieren, für Fotos, die sie sehen kann |
| `python facet.py --export-sidecars --embed-originals` | Metadaten zusätzlich **in** JPEG/HEIC/TIFF/PNG/DNG-Originale schreiben |
| `python facet.py --export-sidecars --score-to-stars` | `xmp:Rating` aus dem Score für Fotos setzen, die Sie nicht bewertet haben |

**Probelauf.** Bei `16gb`/`24gb` zeigt die Ästhetikspalte `n/a`, weil TOPIQ nur in einem echten Scan läuft (der kommerzielle Modus zeigt den Q-ReAlign-Wert). Der Gesamtwert zählt sie als neutrale 5.0.

**CSV und JSON.** Die Spalte `tags` enthält nur KI-Tags; [manuelle Tags](VIEWER.md#manuelle-tags) sind nicht enthalten. In der JSON enthält das Objekt `scores` jedes Fotos jede gespeicherte Metrik; NULL, nicht endliche Zahlen und BLOBs werden zu `null`. Der JSON-Export weigert sich, die Datenbank oder ihre `-wal`/`-shm`/`-journal`-Dateien zu überschreiben.

**Manifest.**

- Das optionale Argument grenzt ein, *welche Fotos* exportiert werden. Die Datei heißt immer `facet_manifest.json` im Arbeitsverzeichnis.
- Es enthält `star_rating`/`is_favorite`/`is_rejected` (global oder die des `--user`), `is_burst_lead`, KI- plus manuelle Tags und eine Zählung `pending_corrections`. Eine Zählung größer null gibt eine Warnung mit Verweis auf `--detect-panoramas` aus.
- _Manifest Version 2_ fügt `burst_group_id`, `sequence_kind`, `sequence_group_id` und `score_stars` hinzu (der Score, umgerechnet über `xmp_export.score_to_rating`). Ein dafür gebautes Zusatzmodul weist ein älteres Manifest zurück: erneut exportieren. Siehe [das Facet-Zusatzmodul](INTEROP.md#das-facet-zusatzmodul-sternebewertungen-pick-flags-metadatenfelder-und-stichwörter).

**`--import-lightroom`** liest den eigenen Export des Zusatzmoduls, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), nicht das Manifest. Eine Datei im falschen Format wird vor jedem Schreiben abgelehnt. Lightrooms Wert gewinnt für jedes Feld, das die Datei enthält; ausgelassene Felder behalten Facets Wert. Es gibt `matched=… unmatched=… changed=…` aus. Siehe [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Zwei-Wege-Metadatensynchronisierung.** Facet schreibt Bewertungen, Farblabels, Stichwörter, Bildunterschriften und benannte Gesichtsregionen in eine standardmäßige `<image>.xmp`-Sidecar, die Lightroom, darktable, digiKam, immich und andere lesen.

- Originale werden nie verändert, außer Sie fügen `--embed-originals` hinzu (nur JPEG/HEIC/TIFF/PNG/DNG; RAW wird nie angetastet).
- Stichwörter sind die KI-Tags plus Ihre [manuellen Tags](VIEWER.md#manuelle-tags). Sie werden nur ergänzt, außer `--reconcile-keywords` entfernt solche, die Facet früher geschrieben hat; fremde Stichwörter bleiben erhalten. Siehe [Manuelle Tags und XMP-Stichwörter](INTEROP.md#manuelle-tags-und-xmp-stichwörter).
- Einbetten und Zusammenführen von Stichwörtern erfordern **exiftool**. Ohne es schreibt Facet eine reine XML-Sidecar.

**Sidecar-Import.**

- Importierte Stichwörter werden zu [manuellen Tags](INTEROP.md#manuelle-tags-und-xmp-stichwörter); ein `--migrate-tags` ist nicht nötig.
- Eine Facet-Entscheidung (Keep, Ablehnung oder unentschieden) ohne Standard-Bewertung oder -Label wird ohne die Prüfung gegen den Scanzeitpunkt angewendet.
- Mit `--user` bleiben Stichwörter und GPS global. Mit `--export-sidecars --user` bleiben Stichwörter, GPS und Aufnahmedatum global.
- Wie eine Sidecar gegen lokale Änderungen abgewogen wird: [Sidecar-Importvorschau und Konflikte](INTEROP.md#sidecar-importvorschau-und-konflikte).

### Immich-Synchronisierung

Facet-Bewertungen und Favoriten an einen [Immich](https://immich.app/)-Server übertragen (Einweg, Facet → Immich, nur REST-API). Assets werden anhand von `originalPath` über die Pfad-Präfix-Zuordnungen im `immich`-Konfigurationsblock zugeordnet.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --immich-test` | Verbindung und API-Schlüssel prüfen (`immich.url` + `immich.api_key`, gesendet als `x-api-key`) |
| `python facet.py --immich-sync` | Sternebewertungen (1–5) und Favoriten übertragen; berücksichtigt `--dry-run` und `--user` |
| `python facet.py --immich-sync --dry-run` | Melden, was sich ändern würde, ohne zu schreiben |

Es werden nur Bewertungen 1–5 gesendet (nie 0/−1). Ein optionales Top-Picks-Album sammelt Fotos oberhalb eines Bewertungsschwellenwerts. Siehe [Konfiguration — Immich-Synchronisierung](CONFIGURATION.md#immich-sync).

### Immich-Stapelpläne

Diese akzeptieren `--config`, `--db` und `--user`; im Mehrbenutzermodus ist ein bestehender Eigentümer nötig. Die Vorschau schreibt nie. Anwenden erfordert den geprüften Plan-Digest.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Entfernte Stapel zum lokalen Import prüfen |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Lokale Stapel zur entfernten Erstellung prüfen |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Geprüften Plan anwenden |

- `--stack-id UUID` wiederholen, um Quellgruppen auszuwählen.
- `--stack-plan-out NEW_JSON` schreibt eine neue private Datei (POSIX `0600`) und überschreibt nie eine vorhandene. Wählen Sie unter Windows einen Ordner, dessen ACL den Zugriff auf Ihr Konto beschränkt.
- Grenzen: 1000 Gruppen, 1000 Mitglieder pro Gruppe, insgesamt 20000 Mitglieder, 16 MiB.
- Unvollständige Zuordnungen und Überschneidungen überspringen die ganze Gruppe. Bestehende Gruppen werden nie aktualisiert.

Siehe [Rechte, Konflikte und entfernte Konkurrenz](IMMICH.md#manuelle-stapel-importieren-und-übertragen).

## Neuberechnungen

Diese Befehle aktualisieren Metriken oder leiten neue Daten ab, ohne die vollständige Bewertungspipeline erneut auszuführen. Die meisten verwenden gespeicherte Thumbnails und Landmarken erneut und sind CPU-leicht; die KI-Zeilen (etwa `--generate-captions`) benötigen eine GPU.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --recompute-average` | Aggregierte Scores und Kategorien aus gespeicherten Metriken neu berechnen (kein Bild wird erneut gelesen) |
| `python facet.py --recompute-category portrait` | Scores nur für eine einzelne Kategorie neu berechnen |
| `python facet.py --tag-untagged` | Nur Fotos ohne Tags verschlagworten, aus den gespeicherten Embeddings |
| `python facet.py --recompute-tags` | Alle Fotos mit dem konfigurierten Modell neu verschlagworten |
| `python facet.py --recompute-tags-vlm` | Alle Fotos mit dem VLM-Tagger neu verschlagworten |
| `python facet.py --detect-moments` | Neue Fotos mit ihrem narrativen Moment kennzeichnen (läuft nach jedem Scan) |
| `python facet.py --recompute-moments` | Narrative Momente für die gesamte Bibliothek neu kennzeichnen |
| `python facet.py --discover-moments` | Aus Ihren Bildunterschriften ein Moment-Vokabular in `scoring_config.discovered.json` vorschlagen |
| `python facet.py --detect-junk` | Screenshots, Dokumente, Belege, Memes und Folien kennzeichnen (läuft nach jedem Scan) |
| `python facet.py --recompute-junk` | `junk_kind` für die gesamte Bibliothek neu bewerten |
| `python facet.py --recompute-saliency` | `[GPU]` Motiv-Salienz aus gespeicherten Thumbnails neu berechnen; `--force` wiederholt alle |
| `python facet.py --recompute-composition-cpu` | Komposition regelbasiert neu berechnen (CPU, beliebiges Profil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Komposition mit SAMP-Net neu berechnen |
| `python facet.py --recompute-iqa` | `[GPU]` Fehlende TOPIQ-IAA-, NR-Face- und LIQE-Scores aus gespeicherten Thumbnails füllen. Läuft auf allen Profilen; auf der CPU (`legacy`) deutlich langsamer |
| `python facet.py --detect-text` | Text im Bild in `ocr_text` lesen, damit die Suche ihn findet (optional, siehe Hinweis) |
| `python facet.py --recompute-text` | OCR für die gesamte Bibliothek erneut ausführen |
| `python facet.py --recompute-colors` | Dominanten Farbton und warme/kalte Farbtemperatur in `dominant_hue` / `color_temp` extrahieren (CPU, schnell) |
| `python facet.py --recompute-form` | Symmetrie, Balance, Kantenentropie, fraktale Komplexität und Farbharmonie neu berechnen (CPU) |
| `python facet.py --recompute-skin-tone` | Natürlichkeit des Porträt-Hauttons neu berechnen (CPU; nur beratender Kritik-Hinweis) |
| `python facet.py --recompute-distortions` | Wahrscheinliche Verzerrungen (Bewegungsunschärfe, Farbstich, …) kennzeichnen und mit `liqe_score` / `noise_sigma` korrelieren (beratend) |
| `python facet.py --upgrade-db` | Schema migrieren und die komplette Nachfüllkette ausführen (siehe Hinweis) |
| `python facet.py --recompute-blinks` | Blinzelerkennung aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-eyes-expression` | Augen-offen- + Ausdrucks-Scores aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-face-signals` | Augen-offen- + Lächel-Scores pro Gesicht aus gespeicherten Landmarken nachfüllen (CPU, schnell) |
| `python facet.py --recompute-burst` | Serienbild-Gruppen neu berechnen (protokolliert `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Belichtungsreihen und Panoramen erkennen (läuft nach jedem Scan; siehe Hinweis) |
| `python facet.py --detect-panoramas` | Panorama-Serien aus gespeicherten Thumbnails erkennen (führt zuerst den Bracket-Durchlauf aus; CPU) |
| `python facet.py --detect-duplicates` | Doppelte Fotos via pHash erkennen (protokolliert `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Kosinus-Schwellenwerte für Beinahe-Duplikate auswerten (Präzision/Recall mit Labels) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` KI-Bildunterschriften mit dem VLM erzeugen |
| `python facet.py --translate-captions` | Englische Bildunterschriften in die konfigurierte Sprache übersetzen (CPU, MarianMT) |
| `python facet.py --extract-gps` | EXIF-GPS in die Datenbank kopieren; im Viewer gesetzte Orte werden übersprungen |
| `python facet.py --rescan-gps` | EXIF-GPS für alle Fotos neu extrahieren (überschreibt); im Viewer gesetzte Orte werden übersprungen |
| `python facet.py --recompute-embeddings` | CLIP/SigLIP-Embeddings für alle Fotos neu berechnen (nach einem Modellwechsel nötig) |
| `python facet.py --score-topiq` | `[GPU]` `topiq_score` für jedes Foto mit Thumbnail neu bewerten (überschreibt) |
| `python facet.py --backfill-focal-35mm` | 35-mm-äquivalente Brennweite aus EXIF nachfüllen, wo sie fehlt |
| `python facet.py --backfill-clipping` | Beschnitt-Prozentsätze pro Kanal aus gespeicherten Histogrammen ableiten (fortsetzbar) |
| `python facet.py --recompute-silhouette` | `is_silhouette` mit der gesichtsbezogenen Regel neu ableiten (siehe Hinweis) |
| `python facet.py --repair-int-columns` | Gebrochene Werte runden, die ein externer EXIF-Schreiber in Ganzzahlspalten (etwa ISO) gespeichert hat |
| `python facet.py --repair-neutral-iqa` | Die vor 1.20 gespeicherten falschen neutralen 5.0-IQA-Scores löschen (siehe Hinweis) |
| `python facet.py --compute-recommendations` | Datenbank analysieren, Bewertungszusammenfassung anzeigen |
| `python facet.py --compute-recommendations --verbose` | Detaillierte Statistiken anzeigen |
| `python facet.py --compute-recommendations --apply-recommendations` | Bewertungskorrekturen automatisch anwenden |
| `python facet.py --compute-recommendations --simulate` | Voraussichtliche Änderungen vorab anzeigen |

**`--recompute-average`** legt keinen Snapshot an: Zum Zurückrollen einen Gewichtungs-Snapshot wiederherstellen und neu berechnen. Führen Sie nach dem Upgrade von 1.20 oder früher zuerst `--recompute-silhouette` aus, dann `--recompute-average` zweimal. Der erste Durchlauf speichert neue Perzentile, daher ändert der zweite noch einige Zeilen.

**Momente.**

- `--detect-moments` kodiert jede neue Bildunterschrift einmal in `caption_embedding`. Den ersten Backfill einer bestehenden Bibliothek führt man am besten auf einer GPU aus; mit `--limit N` probieren Sie ihn an einer Stichprobe.
- Fügen Sie `--dry-run --verbose` zu `--recompute-moments` (oder `--detect-junk`) hinzu, um eine Vorschau ohne Schreiben zu sehen.
- `narrative_moments.vlm_tiebreak` (16gb/24gb): Ist `narrative_moments.vlm_tiebreak.enabled` gesetzt, klassifiziert das Profil-VLM Frames mit niedriger Konfidenz neu.
- `--discover-moments` clustert gespeicherte Bildunterschrift-Embeddings und benennt jedes Cluster. Es überschreibt nie die aktive Konfiguration. Führen Sie zuerst `--detect-moments` aus; die Granularität stellen Sie mit `--discover-min-cluster-size N` ein.
- `--generate-captions` überspringt nicht gekennzeichnete, `other`- und Fotos mit niedriger Konfidenz, wenn `narrative_moments.caption_min_confidence > 0`.

**Müll.** Saubere Fotos werden als `not_junk` markiert, sodass spätere Läufe nur neue prüfen.

**`--detect-text`** ist optional: Es erfordert `ocr.enabled` in `scoring_config.json` und `pip install easyocr`. Siehe [Konfiguration — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** findet Belichtungsreihen anhand von EXIF, dann Panoramen anhand der Thumbnail-Geometrie, und setzt das Leitbild jeder Serie auf die Basisbelichtung. Es läuft auch in `--upgrade-db`. Die Culling-Ansichten **Belichtungsreihen** / **Panoramen** / **HDR-Panoramen** des Viewers und die Schalter `hide_brackets` / `hide_panoramas` bewirken nichts, bis es gelaufen ist. Jeder Lauf kennzeichnet die gesamte Bibliothek neu; ein erneuter Aufruf (oder `--detect-panoramas`) wählt daher ein neues repräsentatives Bild, nachdem Sie das alte aussortiert haben.

**`--upgrade-db`** migriert das Schema und führt aus: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. Es ist gefahrlos wiederholbar und überspringt schwere Schritte wie Captioning. Außerdem dreht es HEIF-Thumbnails zurück, die pillow-heif 1.6 quer gelegt hat, samt ihrer Gesichter; Originaldateien werden nie beschrieben. HEIF-Dateien, die es nicht lesen kann, werden beim nächsten Lauf erneut versucht.

**`--recompute-silhouette`** liest nur die Datenbank, committet pro Batch und berücksichtigt `--dry-run`.

- Der Bericht teilt die Fotos danach ein, wie ihre Gesichtsrahmen zum Thumbnail passen: `exact`, `scaled`, `count_mismatch` (Zuordnung nicht validiert), `other`.
- Ein Foto ohne Gesichter oder mit Rahmen, die sich nicht platzieren lassen, wird auf 0 gesetzt.
- Fotos mit `face_count` NULL oder mit Gesichtern, aber ohne Thumbnail, bleiben unberührt (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Führen Sie danach `--recompute-average` aus. Siehe [SCORING.md](SCORING.md).

**`--repair-int-columns`** liest nur die Datenbank. Die Galerie zeigt die Werte auch ohne es korrekt an, aber Bereichsfilter und Sortierungen verwenden den gespeicherten Wert, sodass ein als ISO 63 angezeigtes Foto übersehen werden kann. Werte, die keine Ganzzahlen sein können, werden NULL.

**`--repair-neutral-iqa`** setzt jeden Wert, der genau 5,0 beträgt, in `aesthetic_iaa`, `face_quality_iqa` und `liqe_score` auf NULL und gibt die Anzahl pro Spalte aus.

- Es berührt weder `aesthetic`, `topiq_score`, `aesthetic_v25` noch `quality_score`.
- Ein echter Wert von genau 5,00 wird ebenfalls gelöscht; `--recompute-iqa` füllt ihn neu, möglicherweise geringfügig anders.
- Führen Sie danach `--recompute-iqa` und `--recompute-average` aus.
- Mit `--dry-run` abgelehnt (Exit-Code 2). Nicht Teil von `--upgrade-db`. Laden Sie geöffnete Galerieseiten neu, um die neuen Filterbereiche zu sehen.

### Ergänzende Qualitätsmodelle

Drei PyIQA-Modelle bewerten über die primäre TOPIQ-Ästhetik hinaus. Sie teilen sich den VRAM mit TOPIQ und laufen im standardmäßigen Multi-Pass-Scan.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trainiertes künstlerisches Verdienst, getrennt von der technischen Qualität. Gespeichert als `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): Qualität der Gesichtsregion. Gespeichert als `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): Qualitätsscore plus Verzerrungsdiagnose (Bewegungsunschärfe, Überbelichtung, Rauschen). Gespeichert als `liqe_score`.

Wenn ein Modell ein Foto nicht bewerten kann:

- Es speichert NULL statt einer neutralen 5,0. Ein GPU-Out-of-Memory-Fehler wird zuvor mit halber Batchgröße wiederholt, bis hinunter zu einem Bild.
- LIQE überspringt Thumbnails, deren kurze Seite unter 224 px liegt (nachdem die lange Kante auf 1024 px begrenzt wurde).
- NR-Face überspringt Fotos mit `face_count` 0. Ein Foto, in dem es kein Gesicht findet, wird in `iqa_declined` vermerkt, bis ein Neuscan (`--force`), `--refresh-thumbnails` oder `--fix-thumbnail-rotation` den Eintrag ungültig macht. Ein Upgrade von pyiqa löscht ihn nicht.
- Andere Fehlschläge werden nicht gespeichert; das nächste `--recompute-iqa` versucht es erneut.
- Mit `--pass quality`, `quality-iaa`, `quality-face` und `quality-liqe` behält ein fehlgeschlagenes Foto seinen gespeicherten Wert.
- Ein vollständiger Scan erfasst ein Foto, dessen TOPIQ-Modell fehlschlägt, für `--retry-failed`; `--pass quality` nicht.

`--recompute-iqa` füllt nur NULL-Spalten und ersetzt nie einen gespeicherten Wert, auch keine neutrale 5,0 aus einer früheren Version. Löschen Sie solche Werte mit `--repair-neutral-iqa`, führen Sie dann `--recompute-iqa` und `--recompute-average` aus, oder scannen Sie mit `--force` neu. Siehe [Ergänzende IQA-Dimensionen](SCORING.md#ergänzende-iqa-dimensionen).

### Benchmarks & ergänzende Scores

| Befehl | Beschreibung |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | `aesthetic_clip` aus zwischengespeicherten Embeddings füllen (keine Bildinferenz; nicht im Standard-`aggregate`). Siehe [SCORING.md](SCORING.md#ergänzende-signale-nicht-im-standard-gesamtwert) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | SRCC + PLCC gegen die AVA-Ground-Truth für jede Score-Spalte berechnen |

### Motiv-Salienz

`--pass saliency` und `--recompute-saliency` verwenden BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, über `transformers`, ~3 GB VRAM), um das Motiv zu finden, und leiten dann vier Metriken ab:

- **Motivschärfe**: ob das Motiv im Fokus ist (Laplace-Varianz, Motiv vs. Hintergrund).
- **Motivprominenz**: Motivfläche / Bildfläche. Hoch bei einem dominanten Motiv (z. B. Makro).
- **Motivplatzierung**: Drittelregel-Score für den Schwerpunkt des Motivs.
- **Hintergrundtrennung**: Kantenkontrast zwischen Motiv und Hintergrund (Bokeh-Qualität).

Die Salienz läuft auf allen Profilen; `legacy` führt sie langsamer auf der CPU aus. `--recompute-saliency` arbeitet auch bei offline befindlichem Bibliotheksvolume und ist fortsetzbar. Auf CUDA richtet sich die Batchgröße nach dem freien VRAM (etwa 2,4 GiB pro Bild bei 1024 px, 1 bis 8 Bilder) und wird nach einem Out-of-Memory-Fehler halbiert.

- **Ein fehlgeschlagenes Foto** wird als ERROR protokolliert, und es wird nichts geschrieben. Ein nie bewertetes Foto bleibt NULL und wird vom nächsten `--recompute-saliency` erneut aufgegriffen; eines, das bereits Salienz hatte, behält seine Werte, auch unter `--recompute-saliency --force`. Ein vollständiger Neuscan (etwa `python facet.py --force`) speichert dafür NULL.
- **Ein Foto ohne Motiv** speichert NULL für Schärfe, Platzierung und Trennung, Prominenz 0.0 und ein NULL-`subject_bbox` (sowie ein NULL-`power_point_score` aus dem Kompositionsschritt). Das ist endgültig; es wird nicht erneut gemessen.
- **Ältere Zeilen** speicherten stattdessen eine neutrale 5.0. `--recompute-saliency` und `--recompute-composition-cpu` schreiben sie um. `--recompute-saliency` greift auch Fotos auf, die bewertet wurden, bevor `subject_bbox` existierte.
- Eine NULL-Metrik zählt im Gesamtwert neutral. Siehe [Dimensionen der Motiverkennung](SCORING.md#dimensionen-der-motiverkennung).

### Verschlagwortungsmodelle

Das Verschlagwortungsmodell hängt vom VRAM-Profil ab:

| Profil | Modell | Funktionsweise |
|---------|-------|-------------|
| `legacy` | CLIP-Ähnlichkeit | Kosinus-Ähnlichkeit zwischen Bild-Embedding und Tag-Text-Embeddings. Kein zusätzliches Modell. |
| `8gb` | CLIP-Ähnlichkeit | Wie legacy, auf gespeicherten CLIP-ViT-L-14-Embeddings. |
| `16gb` | Qwen3.5-2B | Multimodales Modell für die Szenenverschlagwortung. |
| `24gb` | Qwen3.5-4B | Größeres multimodales Modell. |

Alle Tagger ordnen ihre Ausgabe dem konfigurierten Tag-Vokabular zu. Mit `--recompute-tags` verschlagworten Sie mit dem Modell des Profils neu, mit `--recompute-tags-vlm` mit dem VLM.

**Wann Tags geschrieben werden.** Auf den CLIP-Ähnlichkeitsprofilen (`legacy`/`8gb` sowie `16gb`/`24gb`, wenn der VLM-Durchgang nicht eingeplant ist) vergibt ein Multi-Pass-Scan die Tags im Embedding-Durchgang; Kategorie und Gesamtwert des Scans nutzen sie also bereits. Ein einzelner `--pass`-Lauf (etwa `--pass embeddings`) schreibt keine Tags. `--pass tags` auf einem CLIP-Profil bricht ab und verweist auf `--recompute-tags`. Bestehende Zeilen behalten ihre Kategorie bis `--recompute-average`.

### Embedding-Modelle

Zwei Embedding-Modelle, pro VRAM-Profil über `clip_config` ausgewählt:

| Konfiguration | Modell | Dimensionen | Verwendet von |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb-, 24gb-Profile |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy-, 8gb-Profile |

Embeddings treiben Verschlagwortung, Duplikaterkennung, Ähnliche-Fotos-Suche und die CLIP+MLP-Ästhetik (legacy/8gb) an. Ein Modellwechsel erfordert das erneute Embedding aller Fotos (`--force`, `--pass embeddings` oder `--recompute-embeddings`).

## Gesichtserkennung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Gesichter für neue Fotos extrahieren (GPU, parallel) |
| `python facet.py --extract-faces-gpu-force` | Alle Gesichter löschen und neu extrahieren (GPU; benannte Personen bleiben erhalten; im kommerziellen Modus permissiver Extraktor) |
| `python facet.py --cluster-faces-incremental` | HDBSCAN-Clustering, behält alle Personen bei (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, behält nur benannte Personen bei (CPU) |
| `python facet.py --cluster-faces-force` | Vollständiges Re-Clustering, löscht alle Personen (CPU) |
| `python facet.py --suggest-person-merges` | Mögliche Personenzusammenführungen vorschlagen |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Strengeren Schwellenwert verwenden |
| `python facet.py --refill-face-thumbnails-incremental` | Fehlende Gesichts-Thumbnails erzeugen (CPU, parallel) |
| `python facet.py --refill-face-thumbnails-force` | ALLE Gesichts-Thumbnails neu erzeugen (CPU, parallel) |

## Thumbnail-Verwaltung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Gespeicherte Thumbnails an die EXIF-Orientierung anpassen |
| `python facet.py --refresh-thumbnails` | RAW-Thumbnails aus der kamerainternen Vorschau neu erstellen |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Dasselbe, mit mehr parallelen Lesevorgängen |

**`--fix-thumbnail-rotation`** ist für Fotos gedacht, die verarbeitet wurden, bevor die EXIF-Orientierung berücksichtigt wurde. Es liest nur den EXIF-Header und das gespeicherte Thumbnail.

**`--refresh-thumbnails`** rendert das gespeicherte Thumbnail jedes RAW-Fotos neu durch das Anzeigeprofil (zuerst die Kameravorschau, als Fallback das Demosaicing; siehe [CONFIGURATION.md](CONFIGURATION.md#raw-dekodierung)). Verwenden Sie es für eine Bibliothek, die gescannt wurde, bevor dieses Profil existierte: Ältere Thumbnails ebnen die Belichtungsunterschiede zwischen den Aufnahmen einer Belichtungsreihe ein. Es lädt kein Modell und ändert keinen Score.

- **Geschwindigkeit** hängt vom Durchsatz der Festplatte oder des Netzwerks ab, nicht von der CPU. `--refresh-thumbnails-workers` (Standard 8) legt fest, wie viele Dateien gleichzeitig gelesen werden: auf einem schnellen Netzlaufwerk erhöhen, auf einer langsamen lokalen Festplatte verringern. Sehr hohe Werte kosten Arbeitsspeicher.
- **Fortsetzbar.** Mit Strg+C stoppen, und der nächste Lauf macht dort weiter, wo er aufgehört hat. Ein abgeschlossener Lauf beginnt beim nächsten Mal von vorn.
- **Schwarze Renderings** (etwa von einem abgeschnittenen RAW) werden verworfen: Das Foto behält sein altes Thumbnail, wird namentlich protokolliert und beim nächsten Lauf erneut versucht.
- **Aufnahmen von Belichtungsreihen** werden ohne Kameravorschau und ohne Belichtungsverstärkung gerendert, sodass jede Kachel zeigt, was der Sensor aufgezeichnet hat (siehe [CONFIGURATION.md](CONFIGURATION.md#belichtungsreihen-werden-unkorrigiert-gerendert)). Führen Sie es nach `--detect-sequences` aus.

### Was ein gespeichertes Thumbnail aktualisiert

Thumbnails entstehen beim Scan, sodass eine Bibliothek, die vor der Existenz des Anzeigeprofils gescannt wurde, im Galerie-Raster weiterhin das alte Rendering zeigt. Zwei Wege aktualisieren sie:

| Weg | Deckt ab | Kosten |
|------|--------|------|
| Ein erneuter Scan (`python facet.py <dir>`) | Alles, was er scannt, Thumbnail und Histogramm | Vollständiger Scoring-Lauf |
| `--refresh-thumbnails` | Das Thumbnail jeder RAW-Zeile | Speicherbegrenzt, Stunden bei einer großen Bibliothek |

**Nichts geschieht von allein.** Die Detailansicht rendert immer frisch, aber das Galerie-Raster zeigt das gespeicherte Thumbnail. Ein schließbares Banner zählt die noch wartenden Zeilen. Die Zählung kann nach einem Neuscan bis zu eine Stunde hinterherhinken; `--refresh-thumbnails` und `python database.py --refresh-stats` aktualisieren sie.

## Diagnose

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --doctor` | Diagnoseprüfungen ausführen (Python, GPU, ONNX Runtime, Abhängigkeiten, Konfiguration, Datenbank) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | GPU-Hardware für die Diagnose simulieren |

`--doctor` berichtet die Python-Version, den PyTorch/CUDA-Build, GPU und Treiber, den ONNX-Runtime-Build mit Providern, das empfohlene VRAM-Profil, optionale Abhängigkeiten und den Konfigurations-/Datenbankstatus. Auf CUDA lädt es ONNX Runtime zusätzlich testweise auf der GPU. Ist PyTorch oder ONNX Runtime der falsche Build, gibt es den `pip install`-Befehl zur Behebung aus (siehe [ONNX Runtime für die Gesichtserkennung](INSTALLATION.md#onnx-runtime-für-die-gesichtserkennung)).

`--simulate-gpu NAME` und `--simulate-vram GB` erfordern `--doctor`; `--simulate-vram` erfordert außerdem `--simulate-gpu`.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --check-raw-rendering` | 20 stichprobenartig ausgewählte RAW-Fotos unter den alten und aktuellen Dekodiereinstellungen rendern |
| `python facet.py --check-raw-rendering 50` | Stattdessen 50 Fotos als Stichprobe |

Nur lesend. Es gibt die mittlere Helligkeit jedes Renderings aus: LibRaws automatische Aufhellung, das Demosaicing mit fester Verstärkung und die Kameravorschau. Damit prüfen Sie `raw_decode.bright` an Ihren Dateien vor einem Scan oder `--refresh-thumbnails`. Die Spalten für festen Gain und Vorschau erhalten die Belichtungsstufen einer Belichtungsreihe; die automatische Aufhellung ebnet sie ein.

## Modellinformationen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --list-models` | Verfügbare Modelle und VRAM-Anforderungen anzeigen |

## Gewichtungsoptimierung (Paarweiser Vergleich)

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --comparison-stats` | Statistiken paarweiser Vergleiche anzeigen |
| `python facet.py --optimize-weights` | Gewichte aus Ihren Vergleichen optimieren; nur angewendet, wenn sie einen Held-out-Test bestehen (siehe Hinweis) |
| `python facet.py --optimize-weights --optimize-force` | Optimierte Gewichte auch anwenden, wenn sie den Test nicht bestehen |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Nur auf diesen Vergleichsquellen trainieren |
| `python facet.py --optimize-weights --optimize-category portrait` | Eine Kategorie trainieren und deren v4-`categories[].weights`-Block schreiben |
| `python facet.py --auto-tune-categories` | **Nur Superadmin** (im Mehrbenutzermodus `--user`): Bereitschaft der Labels pro Kategorie berichten (nur Bericht) |
| `python facet.py --sync-label-comparisons` | Aus Bewertungen abgeleitete Paare (source=rating) aus Sternen, Favoriten und Ablehnungen neu aufbauen |
| `python facet.py --train-ranker` | Den persönlichen Ranker trainieren und learned_scores schreiben, wenn er den Gesamtwert schlägt |
| `python facet.py --train-ranker --ranker-category portrait` | Den Ranker auf einer Kategorie trainieren |
| `python facet.py --train-ranker --train-ranker-force` | learned_scores schreiben, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --train-ranker --user alice` | Auf den Vergleichen dieses Benutzers trainieren und dessen learned_scores schreiben (Mehrbenutzermodus) |
| `python facet.py --train-keeper` | Den **Keeper-Ranking-Head** aus Ihren Culling-Entscheidungen trainieren (siehe Hinweis) |
| `python facet.py --train-keeper --train-keeper-force` | Den Head auch behalten, wenn er die Schwelle nicht erreicht (berücksichtigt auch `--ranker-category` und `--user`) |
| `python facet.py --report-unreviewed-bursts` | Serienbild-Gruppen zählen, die noch nicht geprüft wurden (nur lesend) |
| `python facet.py --eval-iqa-srcc` | Berichten, wie gut jede IQA-/Ästhetik-Metrik zu Ihren Sternebewertungen passt (SRCC; nur lesend) |
| `python facet.py --evaluate-models SLOT` | Kandidatenmodelle für einen Slot danach einordnen, wie gut sie mit Ihren Auswahlen übereinstimmen (nur lesend; siehe Hinweis) |
| `python facet.py --mine-insights` | Bericht zu Labels, Metrikkorrelationen, Kategorien, Perzentil-Drift und Vergleichen |
| `python facet.py --mine-insights report.json` | Dasselbe, schreibt zusätzlich den vollständigen Bericht als JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Kategoriegewichtungen gegen den [AVA-Datensatz](https://github.com/imfing/ava_downloader) kalibrieren (nur lesend; gibt Vorschläge aus) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Auf diese Kategorien beschränken und die Gewichtungen in `scoring_config.json` schreiben |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Den Optimierer wählen (`de` = differentielle Evolution, Standard; `nelder-mead` = lokaler Simplex) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Auch AVA-Tags verwenden (`--ava-tags-only` nur für Tags; `--apply-filters`, um Filterschwellenwerte abzustimmen) |

**`--optimize-weights`** trainiert auf allen Vergleichsquellen, nach Zuverlässigkeit gewichtet. Neue Gewichte werden nur angewendet, wenn sie die aktuellen bei zurückgehaltenen Vergleichen schlagen (5-fache Kreuzvalidierung, einseitiger McNemar-Test, p < 0.05, Gewinn von mindestens 2 Prozentpunkten). Beim Anwenden wird auch der `modifiers.bonus` der Kategorie neu zentriert, sodass ihre Fotos umsortiert statt alle verschoben werden. Siehe [SCORING.md](SCORING.md).

**`--train-keeper`** lernt aus `source='culling'`-Paaren und wird nur behalten, wenn er bei zurückgehaltenen Daten die Auto-Cull-Heuristik schlägt. Er speist die Auto-Cull-Auswahl und das Badge „besseres Foto in dieser Gruppe vorhanden“. Solange nicht genug Culling-Paare vorliegen, wird die Heuristik verwendet. Er trainiert beim selben Auslöser wie `--train-ranker` nach.

**`--evaluate-models SLOT`**-Slots: `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` wählt Kandidaten (`stored:<column>` oder ein registrierter Name).
- `--eval-out PATH` legt die Ausgabe fest (Standard `.facet_cache/eval/<slot>-<timestamp>.json`).
- Die Gesichts-Slots vergleichen mit den gespeicherten InsightFace-Gesichtern statt mit Ihren Auswahlen und eignen sich daher nur für Bibliotheken im Standardmodus: `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<threshold>`), `faces-centroid` (stimmt SFace-`merge_threshold` / Auto-Merge ab), `blink` (variiert die Schwelle des permissiven Blinzel-Analyzers).
- `--limit N` begrenzt die Fotos (Standard 600) bzw. Referenzgesichter (Standard 1200).

## Konfiguration

`scoring_config.json` ist eine **Überschreibung**: Sie enthält nur die von Ihnen geänderten Einstellungen, über den Standardwerten in `config/scoring_config.default.json`. Ohne Konfigurationsdatei läuft Facet mit den Standardwerten. Siehe [Konfiguration](CONFIGURATION.md#standardwerte-und-ihre-überschreibung).

Welche Datei gelesen wird:

1. `--config` hat immer Vorrang.
2. Sonst `FACET_CONFIG`, falls gesetzt. Sie gilt für `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` und `viewer.py`. `viewer.py` hat kein `--config`, dies ist also seine einzige Überschreibung.
3. Sonst, für die CLI-Werkzeuge (nicht `viewer.py`), eine `scoring_config.json` im **Arbeitsverzeichnis**, sodass eine Fotosammlung ihre eigene Konfiguration mitbringen kann.
4. Sonst die Datei neben der Installation. Fehlt auch sie, gelten die ausgelieferten Standardwerte.

Ein Pfad, den `--config` oder `FACET_CONFIG` nennt und der nicht existiert, ist ein Fehler und kein „Standardwerte verwenden“. Der Viewer protokolliert den fehlenden Pfad und verweigert den Start im offenen Modus.

> **Warnung:** `viewer.py` liest nie eine `scoring_config.json` aus dem Verzeichnis, in dem Sie ihn starten. Starten Sie ihn aus einer Fotosammlung heraus und hat die Installation keine Konfiguration, läuft er mit den Standardwerten: ein leeres `viewer.edition_password` und kein Viewer-Passwort, sodass jeder stöbern kann.

```bash
# 1. --config hat Vorrang vor allem. Eine fehlende Datei ist ein Fehler.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG liefert den Standard, wenn --config fehlt (Docker setzt das).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # liest /config/scoring_config.json
python facet.py --config other.json /photos   # --config hat weiterhin Vorrang

# 3. Keines von beiden: eine Konfiguration im ARBEITSVERZEICHNIS gewinnt bei den CLI-Werkzeugen.
cd /photos/client-shoot          # enthält eine eigene scoring_config.json
python /opt/facet/facet.py .     # bewertet mit /photos/client-shoot/scoring_config.json

# 4. Keines von beiden und hier nichts: Rückfall auf die Konfiguration neben der Installation.
cd /tmp
python /opt/facet/facet.py /photos   # liest /opt/facet/scoring_config.json
                                     # fehlt sie dort = es laufen die ausgelieferten Standardwerte

# 5. viewer.py macht den Schritt über das Arbeitsverzeichnis nie mit.
cd /photos/client-shoot          # enthält eine eigene scoring_config.json -- hier irrelevant
python /opt/facet/viewer.py      # liest weiterhin /opt/facet/scoring_config.json (oder $FACET_CONFIG)
```

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --validate-categories` | Kategoriekonfigurationen validieren |

## Verschlagwortung

| Befehl | Beschreibung |
|---------|-------------|
| `python tag_existing.py` | Nicht verschlagwortete Fotos aus gespeicherten CLIP-Embeddings verschlagworten |
| `python tag_existing.py --dry-run` | Tags vorab anzeigen, ohne zu speichern |
| `python tag_existing.py --threshold 0.25` | Eigene Ähnlichkeitsschwelle (Standard: `tag_threshold_percent` des Profils, ausgeliefert als 8, also 0.08) |
| `python tag_existing.py --max-tags 3` | Tags pro Foto begrenzen (Standard: 5) |
| `python tag_existing.py --force` | Alle Fotos neu verschlagworten |
| `python tag_existing.py --db custom.db` | Benutzerdefinierte Datenbank verwenden |
| `python tag_existing.py --config my.json` | Benutzerdefinierte Konfiguration verwenden |

Auf CUDA kodieren die SigLIP-Profile (`16gb`, `24gb`) das Tag-Vokabular jetzt in fp16, was die Tags einiger weniger Fotos ändert. Führen Sie `python tag_existing.py --force` aus, um früher verschlagwortete Fotos neu zu verschlagworten. CPU und die Profile `legacy`/`8gb` bleiben unverändert.

Der Verschlagwortungsschritt am Ende eines Scans wird übersprungen, wenn `tagging.enabled` auf `false` steht oder kein Foto auf Tags wartet.

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
| `python database.py` | Schema initialisieren oder aktualisieren und fehlende Indizes bauen (siehe Hinweis) |
| `python database.py --info` | Schemainformationen anzeigen |
| `python database.py --migrate-tags` | Einmaliger Aufbau der Tag-Lookup-Tabelle (10-50x schnellere Tag-Filter) |
| `python database.py --rebuild-fts` | Volltextsuchindex aus Bildunterschriften und Tags neu aufbauen |
| `python database.py --populate-vec` | sqlite-vec-Vektorsuchtabelle aus Embeddings füllen |
| `python database.py --refresh-stats` | Statistik-Cache aktualisieren |
| `python database.py --compact-config` | Jeden Wert, der dem ausgelieferten Standard entspricht, aus `scoring_config.json` entfernen (legt zuerst eine `0600`-Sicherung an) |
| `python database.py --stats-info` | Cache-Status und -Alter anzeigen |
| `python database.py --vacuum` | Speicher zurückgewinnen, defragmentieren |
| `python database.py --analyze` | Statistiken des Query-Planers aktualisieren |
| `python database.py --optimize` | VACUUM und ANALYZE ausführen |
| `python database.py --backup` | Einen WAL-sicheren Snapshot mit Zeitstempel schreiben (behält `--keep N`, Standard 3) |
| `python database.py --export-viewer-db` | Leichtgewichtige Viewer-Datenbank exportieren (keine BLOBs, kleinere Thumbnails; inkrementell) |
| `python database.py --export-viewer-db --force-export` | Vollständigen Re-Export erzwingen |
| `python database.py --cleanup-orphaned-persons` | Personen ohne Gesichter entfernen |
| `python database.py --cleanup-missing-photos` | Fotos entfernen, die nicht mehr auf der Festplatte sind, samt Tags, Gesichtern und Albumeinträgen |
| `python database.py --cleanup-missing-photos --dry-run` | Fehlende Dateien auflisten, ohne zu löschen |
| `python database.py --cleanup-missing-photos --force` | Auch fortfahren, wenn jedes Foto fehlend erscheint (siehe Warnung) |
| `python database.py --relink-photos` | Pfade selbst verschobener Fotos aktualisieren (standardmäßig Vorschau). Siehe [Verschobene Fotos neu verknüpfen](#verschobene-fotos-neu-verknüpfen) |
| `python database.py --migrate-storage-fs` | Thumbnails und Embeddings aus der Datenbank in das Dateisystem verschieben |
| `python database.py --migrate-storage-db` | Thumbnails und Embeddings aus dem Dateisystem zurück in die Datenbank verschieben |
| `python database.py --add-user alice --role admin` | Einen Benutzer hinzufügen (fragt nach Passwort) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Benutzer mit Anzeigenamen hinzufügen |
| `python database.py --migrate-user-preferences --user alice` | Bewertungen von photos in user_preferences kopieren |

**`python database.py`** baut außerdem fehlende Galerie-Indizes (siehe [VIEWER.md](VIEWER.md#galerie-indizes-und-zähler-cache)). Führen Sie es bei einer großen Bibliothek einmal vor dem Start des Viewers aus; es kann etwa eine Minute dauern. Sonst baut der Viewer sie im Hintergrund und lehnt währenddessen Speichern ab.

**`--migrate-tags`** ist nur einmal nötig. Danach halten Scans, `--recompute-tags`, `--recompute-tags-vlm` und `tag_existing.py` die Tabelle aktuell. Solange sie nicht gefüllt ist, nutzen Tag-Filter eine langsamere `LIKE`-Suche.

**`--cleanup-missing-photos`** leert außerdem den Vektorindex und setzt die Vergleichszähler des automatischen Neutrainings zurück. Bibliothekszustand wie trainierte Modelle, Immich-Synchronisationsstand und der Perzentil-Snapshot bleibt erhalten.

> **Warnung:** Ohne `--force` bricht `--cleanup-missing-photos` ab, wenn jedes Foto fehlend erscheint, was meist bedeutet, dass ein Volume nicht eingehängt ist. Prüfen Sie den Mount, bevor Sie `--force` hinzufügen.

**Performance-Tipp:** Bei großen Datenbanken (50k+ Fotos) `--migrate-tags`, `--rebuild-fts` und `--populate-vec` einmal ausführen, dann gelegentlich `--optimize`.

## Web-Viewer

| Befehl | Beschreibung |
|---------|-------------|
| `python viewer.py` | Server unter http://localhost:5000 starten (API + Angular SPA) |
| `python viewer.py --port 5001` | An einen anderen Port binden (oder die Umgebungsvariable `PORT` setzen; Standard 5000) |
| `python viewer.py --host 127.0.0.1` | An eine bestimmte Schnittstelle binden (Standard `0.0.0.0`) |
| `python viewer.py --production` | Produktionsmodus (uvicorn-Worker) |
| `python viewer.py --production --workers 4` | Produktionsmodus mit N Workern (Standard 1) |

## Culling

Auto-Cull ohne Oberfläche: die Terminal-Variante des [Auto-Culls](VIEWER.md#auto-cull) des Viewers. Ablehnungen werden in die Datenbank geschrieben. Originale werden nie verschoben oder gelöscht; `--copy-keepers` kopiert die behaltenen Fotos in einen Ordner.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Fotos aussortieren, die bereits in der Datenbank unter `PATH` liegen (Ordner oder Datei; ohne Angabe oder `all` = ganze Bibliothek). **Standardmäßig Probelauf** |
| `python facet.py /path --auto-cull` | `/path` scannen, dann die Fotos darin aussortieren |
| `--apply` | Das Aussortieren schreiben: Ablehnungen, Markierungen geprüfter Gruppen und `source='culling'`-Vergleichspaare |
| `--copy-keepers DIR` | Jedes nicht abgelehnte Foto im Geltungsbereich mit seinen gleichnamigen RAW- / `.xmp`-Begleitdateien nach `DIR` kopieren |
| `--cull-strictness N` | Behalte-Budget 0–100, höher behält weniger pro Gruppe (Standard: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Mindestanzahl behaltener Fotos pro Gruppe (Standard `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Welche Gruppen aussortiert werden (Standard `all`) |
| `--cull-min-score X` | Zusätzlich Einzelfotos ablehnen, deren Gesamtwertung unter `X` liegt |
| `--cull-trim-brackets` | Zusätzlich redundante Aufnahmen von Belichtungsreihen ablehnen (das `trim_brackets` des Viewers) |
| `--user NAME` | Wessen Bewertungen und Ablehnungen verwendet werden; bei einer Mehrbenutzer-Installation **erforderlich** |

- **Probelauf.** Ohne `--apply` wird nichts geschrieben, und der Ordner von `--copy-keepers` wird nicht angelegt. Die Zusammenfassung nennt `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` und mit `--copy-keepers` zusätzlich `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` im Probelauf). `--dry-run` selbst wird abgelehnt. Muss ein trainiertes Keeper-Modell seine Gewichte korrigieren, kann sein Laden dennoch `scoring_config.json` neu schreiben.
- **Scannen-dann-aussortieren** scannt immer tatsächlich; das Aussortieren läuft nur, wenn der Scan abgeschlossen wurde. Es lässt sich nicht mit `--auto-cull PATH`, `--resume`, `--retry-failed` oder `--watch` kombinieren.
- **Regeln.** Wie beim [Auto-Cull des Viewers](VIEWER.md#auto-cull): Jede Gruppe behält ihr bestes Foto plus alles innerhalb der Strenge-Marge, mindestens `--cull-min-keep`. Belichtungsreihen, Panoramen und HDR-Panoramen bleiben vollständig erhalten. `--apply` markiert behaltene Fotos als **Behalten** und erfasst Vergleichspaare wie `POST /api/culling/auto`; ein Highlights-Album wird nicht gefüllt.
- **Konfiguration.** Die Einstellungen [`auto_cull`](CONFIGURATION.md#auto-cull), `burst_scoring` und `similarity_groups` stammen aus der **Server**-Konfiguration (`FACET_CONFIG` oder der Standardpfad), nicht aus `--config`. Weichen beide im Mehrbenutzermodus voneinander ab, endet der Befehl mit Code 1.
- **Geltungsbereich.** Er vergleicht lokale echte Pfade; Zeilen, die vor dem Setzen eines `path_mapping` gespeichert wurden, lassen sich daher nicht nach Ordner eingrenzen: verwenden Sie `all` oder scannen Sie neu. Ein Serienbild, eine Belichtungsreihe oder ein Panorama, das teilweise außerhalb des Geltungsbereichs liegt, wird vollständig übersprungen (`spanning_skipped`). Ähnlichkeits- und Szenengruppen werden innerhalb des Geltungsbereichs berechnet.
- **`--cull-min-score`** (nur CLI) lehnt nie Aufnahmen von Belichtungsreihen oder Panoramen, Fotos ohne Wertung, Favoriten, bewertete oder mit **Keep** markierte Fotos oder Fotos ab, die ein früheres Aussortieren schon beurteilt hat; ein zweiter Lauf lehnt daher nichts Neues ab. Mitglieder von Serienbild-Gruppen bleiben immer verschont. Mitglieder von Ähnlichkeitsgruppen bleiben verschont, wenn die Gruppierung sie gefunden hat (sie liest die neuesten `similarity_groups.max_photos` Fotos im Geltungsbereich, Standard `10000`, und verwirft Gruppen über `similarity_groups.max_group_size`, Standard `50`). Mitglieder einer Szenengruppe bleiben nur unter `--cull-group-by scene` verschont.
- **Kopieren.** Abgelehnte Fotos und ihre Begleitdateien werden nie kopiert. Gleichnamige Dateien aus verschiedenen Ordnern erhalten das Suffix `_1`; ein erneuter Lauf überspringt identische Dateien (`already_present`). `DIR` darf weder der Geltungsbereich, die Bibliothek oder ein von Facet gescannter Ordner sein noch einen davon enthalten oder darin liegen (Code 1, auch im Probelauf geprüft). Dateien müssen innerhalb der Positivliste der Scan-Verzeichnisse liegen (`users.*.directories` / `viewer.scan_directories`); wird deshalb jedes Foto übersprungen, endet der Befehl mit Code 3.
- **Benutzer.** Bei einer Mehrbenutzer-Installation ist `--user` erforderlich (Code 1 ohne Angabe oder mit unbekanntem Benutzer). Bei einer Einzelbenutzer-Installation wird `--user` mit einer Warnung ignoriert, und der Befehl sieht alle Fotos, auch wenn ein Viewer-Passwort gesetzt ist. `--apply` nimmt die Bibliothekssperre; ein Probelauf nimmt keine.
- **Aufruffehler (Code 2).** `--apply`, `--copy-keepers` oder ein `--cull-*` ohne `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` oder `--watch` mit `--auto-cull`; `--auto-cull PATH` zusammen mit Positionsverzeichnissen; Strenge außerhalb von 0–100; `--cull-min-keep` unter 1. `--apply` muss vollständig ausgeschrieben werden (es kürzt `--apply-recommendations` nicht mehr ab).
- **Exit-Codes.** `0` Erfolg (Probelauf und null Gruppen eingeschlossen); `1` Fehler bei Voraussetzung, Konfiguration oder Datenbank; `2` Aufruffehler; `75` die Bibliothekssperre wird von einem anderen Auftrag gehalten; `3` das Aussortieren war erfolgreich, aber das Kopieren hatte Fehler oder kopierte nichts (ein Probelauf, in dem jedes behaltene Foto übersprungen würde, endet ebenfalls mit `3`).
- **Nachtrainieren** läuft nicht innerhalb der CLI. Der Vergleichszähler bleibt erhalten, und das Nachtrainieren läuft bei der nächsten Viewer-Aktion oder mit einem `--train-*`-Befehl. Der erste Lauf kann `.facet_secret` anlegen.

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
python facet.py --auto-cull /photos/wedding                     # Plan ansehen, nichts wird geschrieben
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Ablehnen, dann die behaltenen Fotos kopieren
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

## Verschobene Fotos neu verknüpfen

Nach einem selbst ausgeführten Dateiumzug zeigt `python database.py --relink-photos` die Zuordnungen von altem zu neuem Pfad vorab an und erhält die Datenbankdaten jedes Fotos. Die Vorschau ist Standard.

- **Anwenden** erfordert die gespeicherte Plan-ID und `--acknowledge-unverified-identity`, weil Facet nicht beweisen kann, dass die neue Datei das Original ist. Stoppen Sie Viewer und Scanner und prüfen Sie zuerst den Plan.
- **Abgelehnt** werden: Pfade außerhalb Ihrer konfigurierten Wurzeln oder der Benutzersichtbarkeit, Kopien, mehrdeutige Namen, veraltete Pläne und Pfadzuordnungen.
- **Begleitdateien** müssen ausdrücklich benannt werden; die Typen umfassen `sidecar_facet` für `photo.ext.facet.xmp`. Manuelle Rechtecke benötigen eine Prüfung im Editor. Der Immich-Zustand bleibt unverändert.
- **Pläne** werden privat gespeichert (0600 unter POSIX).
- **Mounts:** Ein lesbarer Ordner beweist keinen eingehängten Datenträger, daher bleibt `source_mount_status` bei `not_verified`. Bestätigen Sie, dass das Original verschoben wurde und nicht offline ist.
- **Exit-Codes:** 75 bedeutet, dass ein anderer Auftrag die Bibliothekssperre hält; 1, dass die Sperre unbenutzbar ist. Die Vorschau nimmt keine Sperre.

Den vollständigen Vertrag und Beispiele finden Sie unter [Ein fehlendes Foto neu verknüpfen](RELINK.md).
