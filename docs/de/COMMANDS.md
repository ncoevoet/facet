# Befehlsreferenz

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · **Deutsch** · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md)

[Scannen](#scanning) · [Vorschau & Export](#preview--export) · [Neuberechnungen](#recompute-operations) · [Gesichtserkennung](#face-recognition) · [Thumbnail-Verwaltung](#thumbnail-management) · [Diagnose](#diagnostics) · [Modellinformationen](#model-information) · [Gewichtungsoptimierung](#weight-optimization-pairwise-comparison) · [Konfiguration](#configuration) · [Verschlagwortung](#tagging) · [Datenbankvalidierung](#database-validation) · [Datenbankpflege](#database-maintenance) · [Web-Viewer](#web-viewer) · [Häufige Arbeitsabläufe](#common-workflows)

> Anforderungs-Tags, die nachstehend verwendet werden: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM-Profil). Siehe die [Funktionsmatrix](../README.md#feature-availability--requirements).

## Scannen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path` | Verzeichnis scannen (Multi-Pass-Modus, automatische VRAM-Erkennung) |
| `python facet.py /path --force` | Bereits verarbeitete Dateien erneut scannen |
| `python facet.py /path --single-pass` | Single-Pass-Modus erzwingen (alle Modelle gleichzeitig) |
| `python facet.py /path --pass quality` | Nur den TOPIQ-Qualitäts-Pass ausführen |
| `python facet.py /path --pass quality-iaa` | Nur die TOPIQ-IAA-Bewertung des ästhetischen Verdienstes ausführen |
| `python facet.py /path --pass quality-face` | Nur die TOPIQ-NR-Face-Qualitätsbewertung ausführen |
| `python facet.py /path --pass quality-liqe` | Nur LIQE-Qualität + Verzerrungsdiagnose ausführen |
| `python facet.py /path --pass tags` | Nur den Verschlagwortungs-Pass ausführen (Modell hängt vom VRAM-Profil ab) |
| `python facet.py /path --pass composition` | Nur die SAMP-Net-Erkennung von Kompositionsmustern ausführen |
| `python facet.py /path --pass faces` | Nur die InsightFace-Gesichtserkennung ausführen |
| `python facet.py /path --pass embeddings` | Nur die CLIP/SigLIP-Embedding-Extraktion ausführen |
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

**Single-Pass (`--single-pass`):** lädt alle Modelle gleichzeitig. Schneller, benötigt mehr VRAM.

**Bestimmter Pass (`--pass NAME`):** nur einen Pass ausführen, um bestimmte Metriken zu aktualisieren, ohne vollständig neu zu verarbeiten. Verfügbare Pässe:

| Pass | Modell | Ausgabe | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic`-Score (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa`-Score (künstlerisches Verdienst vs. technische Qualität, AVA-trainiert) | Geteilt mit TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa`-Score (eigens für Gesichtsqualität entwickelt) | Geteilt mit TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + Verzerrungsdiagnose (Unschärfe, Überbelichtung, Rauschen) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Semantische Tags aus dem konfigurierten Vokabular | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 Muster) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Gesichtserkennung, Landmarken, Blinzelerkennung, Erkennungs-Embeddings | ~2 GB |
| `embeddings` | CLIP ViT-L-14 oder SigLIP 2 NaFlex | `clip_embedding`-BLOB für Ähnlichkeit/Verschlagwortung | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Vorschau & Export

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path --dry-run` | 10 Beispielfotos bewerten, ohne zu speichern |
| `python facet.py /path --dry-run --dry-run-count 20` | 20 Beispielfotos bewerten |
| `python facet.py --export-csv` | Alle Scores in eine CSV mit Zeitstempel exportieren |
| `python facet.py --export-csv output.csv` | In eine bestimmte CSV-Datei exportieren |
| `python facet.py --export-json` | Alle Scores in eine JSON mit Zeitstempel exportieren |
| `python facet.py --export-json output.json` | In eine bestimmte JSON-Datei exportieren |
| `python facet.py --import-sidecars` | Bewertungen/Labels/Tags aus `<image>.xmp`-Sidecars zurück in die DB importieren (alle Fotos) |
| `python facet.py --import-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums importieren |
| `python facet.py --import-sidecars --user alice` | Mehrbenutzermodus: Bewertungen in Alices `user_preferences` importieren statt in die globalen Spalten (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars` | `<image>.xmp`-Sidecars aus der DB für alle Fotos schreiben/zusammenführen (nur Sidecar) |
| `python facet.py --export-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums exportieren |
| `python facet.py --export-sidecars --user alice` | Mehrbenutzermodus: Alices `user_preferences`-Bewertungen exportieren statt der globalen Spalten (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars --embed-originals` | Metadaten zusätzlich **in der Datei** für JPEG/HEIC/TIFF/PNG/DNG einbetten (schreibt die Originale neu) |
| `python facet.py --export-sidecars --score-to-stars` | `xmp:Rating` aus dem aggregierten Score für Fotos ableiten, die Sie nicht manuell bewertet haben (eine manuelle Bewertung/Favorit/Ablehnung gewinnt immer) |

> **Zwei-Wege-Metadatensynchronisierung.** Facet schreibt Bewertungen, Farblabels, Schlüsselwörter, Bildunterschriften und benannte Gesichtsregionen in eine standardmäßige `<image>.xmp`-Sidecar, die das Ökosystem liest (Lightroom, darktable, digiKam, immich, …); das Originalbild wird nie verändert, es sei denn, Sie entscheiden sich dafür mit `--export-sidecars --embed-originals` (nur JPEG/HEIC/TIFF/PNG/DNG — RAW wird nie angetastet). Das Einbetten und die sichere Schlüsselwort-Vereinigungszusammenführung erfordern **exiftool**; ohne es greift Facet auf eine abhängigkeitsfreie reine XML-Sidecar zurück.
>
> **Vorbehalt.** `--import-sidecars` löst Bewertungen/Labels *„neueste gewinnt"* gegen das `scanned_at` des Fotos (letzter Scan) auf, nicht gegen eine pro-Bewertung-Bearbeitungszeit — eine Sidecar, die neuer als der letzte Scan ist, kann also eine Bewertung überschreiben, die Sie in Facet danach geändert haben. Führen Sie `--import-sidecars` vor dem Neubewerten aus, wenn der externe Editor die Quelle der Wahrheit ist, und `python database.py --migrate-tags` nach dem Import, wenn Sie die `photo_tags`-Lookup-Tabelle verwenden.

## Neuberechnungen

Diese Befehle aktualisieren bestimmte Metriken, leiten neue Daten ab (KI-Bildunterschriften, GPS, Embeddings) oder analysieren die Datenbank — alles, ohne die vollständige Bewertungspipeline erneut auszuführen. Die meisten verwenden gespeicherte Thumbnails/Landmarken erneut und sind CPU-leicht, aber die KI-/Extraktionszeilen (z. B. `--generate-captions`) und die aus-dem-Bild-neuberechnenden Zeilen sind GPU-intensiv.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --recompute-average` | Aggregierte Scores aus gespeicherten Embeddings neu berechnen (neu ableitbar; kein DB-Snapshot — zum Zurückrollen einen Gewichtungs-Snapshot wiederherstellen und neu berechnen) |
| `python facet.py --recompute-category portrait` | Scores nur für eine einzelne Kategorie neu berechnen |
| `python facet.py --recompute-tags` | Alle Fotos mit dem konfigurierten Modell neu verschlagworten |
| `python facet.py --recompute-tags-vlm` | Alle Fotos mit dem VLM-Tagger neu verschlagworten |
| `python facet.py --detect-moments` | Neue Fotos mit ihrem narrativen Moment kennzeichnen (caption-semantisch, Zero-Shot + zeitliche Glättung; läuft am Ende jedes Scans automatisch). Kodiert jede neue Bildunterschrift einmal in `caption_embedding`, dann Kosinus über gespeicherte Vektoren — der erste vollständige Backfill über eine bestehende Bibliothek ist GPU-empfohlen; fügen Sie `--limit N` hinzu, um es an einer Stichprobe zu prüfen. Wenn `narrative_moments.vlm_tiebreak.enabled` gesetzt ist (16gb/24gb-Profile), werden Frames mit niedrigem Posterior / niedriger Marge vom Profil-VLM neu klassifiziert |
| `python facet.py --recompute-moments` | Narrative Momente für die gesamte Bibliothek neu kennzeichnen (glättet die vollständige Zeitachse erneut). Fügen Sie `--dry-run --verbose` hinzu, um die Top-3-Momente pro Foto ohne Schreiben vorab anzuzeigen. Berücksichtigt zudem die `narrative_moments.vlm_tiebreak`-VLM-Neuklassifizierung von Frames mit niedriger Konfidenz, wenn aktiviert (16gb/24gb) |
| `python facet.py --discover-moments` | Ein bibliotheksspezifisches Moment-Vokabular vorschlagen, indem die gespeicherten Bildunterschrift-Embeddings geclustert (HDBSCAN) und jedes Cluster anhand seiner Bildunterschriften benannt werden. Schreibt `scoring_config.discovered.json` zur Überprüfung — überschreibt niemals die aktive Konfiguration. Führen Sie zuerst `--detect-moments` aus, um `caption_embedding` zu befüllen; passen Sie die Granularität mit `--discover-min-cluster-size N` an |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Metriken der Motiv-Salienz neu berechnen (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Komposition neu berechnen, regelbasiert (CPU, beliebiges Profil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Komposition mit SAMP-Net neu berechnen |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Ergänzende IQA-Metriken (TOPIQ IAA, NR-Face, LIQE) aus gespeicherten Thumbnails neu berechnen |
| `python facet.py --recompute-ocr` | In-Bild-Text in `ocr_text` aus Thumbnails extrahieren (opt-in; ohne OCR-Engine wirkungslos; danach `--rebuild-fts` ausführen, um zu indizieren) |
| `python facet.py --recompute-colors` | Dominanten Farbton + warme/kalte Farbtemperatur aus Thumbnails extrahieren (CPU, schnell) in `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Schema migrieren und die vollständige Backfill-Kette ausführen: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotent; überspringt schwere Schritte wie das Erstellen von Bildunterschriften. |
| `python facet.py --recompute-blinks` | Blinzelerkennung aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-eyes-expression` | Augen-offen- + Ausdrucks-Scores aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-burst` | Serienbild-Erkennungsgruppen neu berechnen |
| `python facet.py --detect-duplicates` | Doppelte Fotos via pHash erkennen |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Kosinus-Schwellenwerte für Beinahe-Duplikate auswerten (Präzisions-/Recall-Tabelle mit Labels, sonst Verteilung der Kandidaten-Kosinuswerte) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` KI-Bildunterschriften für Fotos mit VLM erzeugen. Wenn `narrative_moments.caption_min_confidence > 0`, werden nicht gekennzeichnete / `other` / unter dem Schwellenwert liegende Fotos übersprungen (derselbe Filter gilt für den On-Demand-Bildunterschrift-Endpunkt) |
| `python facet.py --translate-captions` | Englische Bildunterschriften in die konfigurierte Zielsprache übersetzen (CPU, MarianMT) |
| `python facet.py --extract-gps` | GPS-Koordinaten aus EXIF-Daten in Datenbankspalten extrahieren |
| `python facet.py --rescan-gps` | GPS-Koordinaten aus EXIF für alle Fotos neu extrahieren (überschreibt vorhandene) |
| `python facet.py --recompute-embeddings` | CLIP/SigLIP-Embeddings für alle Fotos neu berechnen (nach Modellwechsel erforderlich) |
| `python facet.py --score-topiq` | TOPIQ-Qualitätsscores aus gespeicherten Thumbnails nachfüllen (GPU erforderlich) |
| `python facet.py --backfill-focal-35mm` | 35-mm-äquivalente Brennweite aus EXIF für Fotos nachfüllen, denen sie fehlt |
| `python facet.py --compute-recommendations` | Datenbank analysieren, Bewertungszusammenfassung anzeigen |
| `python facet.py --compute-recommendations --verbose` | Detaillierte Statistiken anzeigen |
| `python facet.py --compute-recommendations --apply-recommendations` | Bewertungskorrekturen automatisch anwenden |
| `python facet.py --compute-recommendations --simulate` | Voraussichtliche Änderungen vorab anzeigen |

### Ergänzende Qualitätsmodelle

Drei zusätzliche PyIQA-Modelle bewerten über den primären TOPIQ-Ästhetik-Score hinaus. Sie teilen sich den VRAM mit TOPIQ und laufen als Teil der standardmäßigen Multi-Pass-Pipeline.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trainiertes künstlerisches ästhetisches Verdienst, getrennt von der technischen Qualität. Gespeichert als `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): Qualitätsbewertung der Gesichtsregion. Gespeichert als `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): Qualitätsscore plus eine Diagnose des Verzerrungstyps (z. B. Bewegungsunschärfe, Überbelichtung, Rauschen). Gespeichert als `liqe_score`.

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

Erfordert `transformers` (~2 GB VRAM).

### Verschlagwortungsmodelle

Das Verschlagwortungsmodell wird pro VRAM-Profil ausgewählt:

| Profil | Modell | Funktionsweise |
|---------|-------|-------------|
| `legacy` | CLIP-Ähnlichkeit | Kosinus-Ähnlichkeit zwischen Bild-Embedding und Tag-Text-Embeddings. Kein zusätzliches Modell laden. |
| `8gb` | CLIP-Ähnlichkeit | Wie legacy, auf gespeicherten CLIP-ViT-L-14-Embeddings. |
| `16gb` | Qwen3.5-2B | Multimodales Modell für semantische Szenenverschlagwortung. |
| `24gb` | Qwen3.5-4B | Größeres multimodales Modell. |

Alle Tagger ordnen die Ausgabe dem konfigurierten Tag-Vokabular zu. Verwenden Sie `--recompute-tags`, um mit dem Standardmodell des Profils neu zu verschlagworten, oder `--recompute-tags-vlm` für VLM-basierte Neuverschlagwortung.

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
| `python facet.py --extract-faces-gpu-force` | Alle Gesichter löschen und neu extrahieren (GPU) |
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

Liest die EXIF-Orientierung aus den Originaldateien und rotiert die gespeicherten Thumbnail-Bytes; für Fotos, die verarbeitet wurden, bevor es eine EXIF-Behandlung gab. Es liest nur den EXIF-Header und das gespeicherte Thumbnail, nicht die vollständigen Bilder.

## Diagnose

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --doctor` | Diagnoseprüfungen ausführen (Python, GPU, Abhängigkeiten, Konfiguration, Datenbank) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | GPU-Hardware für die Diagnose simulieren |

Berichtet die Python-Version, den PyTorch/CUDA-Build, die GPU-Erkennung und den Treiber, die Empfehlung für das VRAM-Profil, optionale Abhängigkeiten und den Konfigurations-/Datenbankstatus. Wenn PyTorch die GPU nicht sehen kann, `nvidia-smi` aber schon, gibt es den `pip install`-Befehl zur Behebung des CUDA-Builds aus.

`--simulate-gpu NAME` und `--simulate-vram GB` testen das Verhalten mit anderer Hardware. Beide erfordern `--doctor`; `--simulate-vram` erfordert `--simulate-gpu`.

## Modellinformationen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --list-models` | Verfügbare Modelle und VRAM-Anforderungen anzeigen |

## Gewichtungsoptimierung (Paarweiser Vergleich)

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --comparison-stats` | Statistiken paarweiser Vergleiche anzeigen |
| `python facet.py --optimize-weights` | Gewichtungen aus Vergleichen optimieren und speichern (alle Quellen, zuverlässigkeitsgewichtet); nur angewendet, wenn die ausgelassene k-fache Genauigkeit die aktuellen Gewichtungen übertrifft |
| `python facet.py --optimize-weights --optimize-force` | Optimierte Gewichtungen anwenden, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Trainingsdaten auf bestimmte Vergleichsquellen beschränken |
| `python facet.py --optimize-weights --optimize-category portrait` | Nur auf einer Kategorie trainieren und deren v4-`categories[].weights`-Block schreiben |
| `python facet.py --auto-tune-categories` | **Nur Superadmin** (im Mehrbenutzermodus `--user` übergeben): Pro-Kategorie-Bereitschaft der Vergleichslabels für die automatische Feinabstimmung der gemeinsamen globalen Gewichtungen berichten. Stub — berichtet nur die Bereitschaft; die Auto-Apply-Schleife ist bis zum Vorliegen von Labels zurückgestellt |
| `python facet.py --sync-label-comparisons` | Aus Bewertungen abgeleitete Paare (source=rating) aus Sternebewertungen/Favoriten/Ablehnungen neu aufbauen |
| `python facet.py --train-ranker` | Den persönlichen Ranker über [Embedding + Scores] trainieren und learned_scores schreiben (abhängig von der ausgelassenen k-fachen Genauigkeit gegenüber der aggregierten Baseline) |
| `python facet.py --train-ranker --ranker-category portrait` | Den Ranker nur auf einer Kategorie trainieren |
| `python facet.py --train-ranker --train-ranker-force` | learned_scores schreiben, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --report-unreviewed-bursts` | Berichten, wie viele Serienbild-Gruppen ungeprüft bleiben (nur lesend) |
| `python facet.py --eval-iqa-srcc` | Spearman-SRCC jeder IQA-/Ästhetik-Metrik gegenüber Ihren Sternebewertungen berichten (nur lesend) |
| `python facet.py --mine-insights` | Data-Mining-Bericht: Label-Inventar, Metrik-Label-Korrelationen, Kategorienverteilung, Perzentil-Drift, Vergleichsgesundheit |
| `python facet.py --mine-insights report.json` | Dasselbe, schreibt zusätzlich den vollständigen Bericht als JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Bewertungsgewichtungen pro Kategorie gegen den [AVA-Datensatz](https://github.com/imfing/ava_downloader) kalibrieren, indem die SRCC gegenüber den AVA-Mean-Opinion-Scores maximiert wird (nur lesend; gibt vorgeschlagene Gewichtungen aus) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Auf bestimmte Kategorien beschränken und die optimierten Gewichtungen zurück in `scoring_config.json` schreiben |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Den Optimierer wählen (`de` = differentielle Evolution, Standard; `nelder-mead` = lokaler Simplex) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Auch gegen die semantischen AVA-Tags kalibrieren (`--ava-tags-only`, um ausschließlich Tags zu verwenden; `--apply-filters`, um auch die Filterschwellenwerte der Kategorien feinabzustimmen) |

## Konfiguration

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --validate-categories` | Kategoriekonfigurationen validieren |

## Verschlagwortung

| Befehl | Beschreibung |
|---------|-------------|
| `python tag_existing.py` | Tags zu nicht verschlagworteten Fotos mit gespeicherten CLIP-Embeddings hinzufügen |
| `python tag_existing.py --dry-run` | Tags vorab anzeigen, ohne zu speichern |
| `python tag_existing.py --threshold 0.25` | Benutzerdefinierter Ähnlichkeitsschwellenwert (Standard: 0.22) |
| `python tag_existing.py --max-tags 3` | Tags pro Foto begrenzen (Standard: 5) |
| `python tag_existing.py --force` | Alle Fotos neu verschlagworten |
| `python tag_existing.py --db custom.db` | Benutzerdefinierte Datenbank verwenden |
| `python tag_existing.py --config my.json` | Benutzerdefinierte Konfiguration verwenden |

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
| `python database.py` | Schema initialisieren/aktualisieren |
| `python database.py --info` | Schemainformationen anzeigen |
| `python database.py --migrate-tags` | photo_tags-Lookup befüllen (10-50x schnellere Abfragen) |
| `python database.py --rebuild-fts` | FTS5-Volltextsuchindex aus Bildunterschriften/Tags neu aufbauen |
| `python database.py --populate-vec` | sqlite-vec-Vektorsuchtabelle aus Embeddings befüllen |
| `python database.py --refresh-stats` | Statistik-Cache aktualisieren |
| `python database.py --stats-info` | Cache-Status und -Alter anzeigen |
| `python database.py --vacuum` | Speicher zurückgewinnen, defragmentieren |
| `python database.py --analyze` | Statistiken des Query-Planers aktualisieren |
| `python database.py --optimize` | VACUUM und ANALYZE ausführen |
| `python database.py --backup` | Einen WAL-sicheren DB-Snapshot mit Zeitstempel schreiben (rotiert auf `--keep N`, Standard 3) |
| `python database.py --export-viewer-db` | Leichtgewichtige Viewer-Datenbank exportieren (entfernt BLOBs, verkleinert Thumbnails; inkrementell, wenn die Ausgabe vorhanden ist) |
| `python database.py --export-viewer-db --force-export` | Vollständigen Re-Export erzwingen, auch wenn die Viewer-DB bereits vorhanden ist |
| `python database.py --cleanup-orphaned-persons` | Personen ohne zugehörige Gesichter entfernen |
| `python database.py --cleanup-missing-photos` | Fotos, die nicht mehr auf der Festplatte sind, aus der Datenbank entfernen (kaskadierende Löschungen bereinigen Tags, erkannte Gesichter usw.; löscht außerdem Album-Mitgliedschaften, den Vektorindex und macht den Statistik-Cache ungültig) |
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
