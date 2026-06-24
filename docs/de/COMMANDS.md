# Befehlsreferenz

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · **Deutsch** · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md)

[Scannen](#scannen) · [Vorschau & Export](#vorschau--export) · [Neuberechnungsoperationen](#neuberechnungsoperationen) · [Gesichtserkennung](#gesichtserkennung) · [Vorschaubild-Verwaltung](#vorschaubild-verwaltung) · [Diagnose](#diagnose) · [Modellinformationen](#modellinformationen) · [Gewichtsoptimierung](#gewichtsoptimierung-paarweiser-vergleich) · [Konfiguration](#konfiguration) · [Verschlagwortung](#verschlagwortung) · [Datenbankvalidierung](#datenbankvalidierung) · [Datenbankwartung](#datenbankwartung) · [Web-Viewer](#web-viewer) · [Häufige Arbeitsabläufe](#häufige-arbeitsabläufe)

> Unten verwendete Anforderungs-Tags: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (VRAM-Profil). Siehe die [Funktionsmatrix](../../README.md#feature-availability--requirements).

## Scannen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py /path` | Verzeichnis scannen (Multi-Pass-Modus, automatische VRAM-Erkennung) |
| `python facet.py /path --force` | Bereits verarbeitete Dateien neu scannen |
| `python facet.py /path --single-pass` | Single-Pass-Modus erzwingen (alle Modelle gleichzeitig) |
| `python facet.py /path --pass quality` | Nur den TOPIQ-Qualitätsbewertungsdurchlauf ausführen |
| `python facet.py /path --pass quality-iaa` | Nur die TOPIQ-IAA-Bewertung des ästhetischen Werts ausführen |
| `python facet.py /path --pass quality-face` | Nur die TOPIQ-NR-Face-Qualitätsbewertung ausführen |
| `python facet.py /path --pass quality-liqe` | Nur LIQE-Qualität + Verzerrungsdiagnose ausführen |
| `python facet.py /path --pass tags` | Nur den Verschlagwortungsdurchlauf ausführen (Modell hängt vom VRAM-Profil ab) |
| `python facet.py /path --pass composition` | Nur die SAMP-Net-Kompositionsmustererkennung ausführen |
| `python facet.py /path --pass faces` | Nur die InsightFace-Gesichtserkennung ausführen |
| `python facet.py /path --pass embeddings` | Nur die CLIP/SigLIP-Embedding-Extraktion ausführen |
| `python facet.py /path --pass saliency` | Nur die BiRefNet-Motiverkennung ausführen |
| `python facet.py /path --db custom.db` | Benutzerdefinierte Datenbankdatei verwenden |
| `python facet.py /path --config my.json` | Benutzerdefinierte Bewertungskonfiguration verwenden |
| `python facet.py --resume` | Den letzten unterbrochenen/fehlgeschlagenen Scan fortsetzen (verwendet dessen Verzeichnisse erneut; mit `--force` werden Dateien übersprungen, die seit dem Start dieses Laufs bereits neu bewertet wurden) |
| `python facet.py --retry-failed` | Nur die Dateien neu verarbeiten, die während des letzten Scan-Laufs fehlgeschlagen sind (`--retry-failed all` für Fehler über alle Läufe hinweg) |
| `python facet.py /path --force-since 2026-01-01` | Wie `--force`, verarbeitet aber nur Fotos neu, die zuletzt vor dem Datum gescannt wurden |
| `python facet.py /path --watch` | Weiterlaufen und neu scannen, sobald neue Fotos erscheinen (erfordert `pip install watchdog`; `--watch-debounce N` stellt die Ruhephase ein, Standard 30 s) |

### Scan-Protokollierung

Jeder Scan zeichnet eine Zeile in `scan_runs` auf (Status, Modus, Verzeichnisse, Zähler)
und dateispezifische Fehler in `scan_failures` (Pfad, Phase, Fehler). Das Unterbrechen
eines Scans mit Strg+C markiert den Lauf als `interrupted`, damit `--resume` ihn
wieder aufnehmen kann; fehlgeschlagene Dateien sind sichtbar und erneut verarbeitbar,
statt bei jedem inkrementellen Scan stillschweigend wiederholt zu werden. Die CLI gibt
außerdem strukturierte `@FACET_PROGRESS`-JSON-Zeilen aus (Phase, aktuell/gesamt, ETA),
die die Scan-API des Viewers im Feld `progress` von `/api/scan/status` und im
SSE-Stream bereitstellt.

### Verarbeitungsmodi

**Multi-Pass (Standard):** erkennt VRAM und lädt Modelle nacheinander. Jeder Durchlauf lädt sein Modell, verarbeitet alle Fotos und entlädt es dann, um VRAM freizugeben, sodass hochwertige Modelle selbst bei begrenztem VRAM laufen.

**Single-Pass (`--single-pass`):** lädt alle Modelle gleichzeitig. Schneller, benötigt mehr VRAM.

**Spezifischer Durchlauf (`--pass NAME`):** nur einen Durchlauf ausführen, um bestimmte Metriken zu aktualisieren, ohne vollständige Neuverarbeitung. Verfügbare Durchläufe:

| Durchlauf | Modell | Ausgabe | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | `aesthetic`-Wertung (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa`-Wertung (künstlerischer Wert vs. technische Qualität, AVA-trainiert) | Geteilt mit TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa`-Wertung (speziell für Gesichtsqualität) | Geteilt mit TOPIQ |
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
| `python facet.py --export-csv` | Alle Wertungen in eine CSV mit Zeitstempel exportieren |
| `python facet.py --export-csv output.csv` | In eine bestimmte CSV-Datei exportieren |
| `python facet.py --export-json` | Alle Wertungen in eine JSON mit Zeitstempel exportieren |
| `python facet.py --export-json output.json` | In eine bestimmte JSON-Datei exportieren |
| `python facet.py --import-sidecars` | Bewertungen/Labels/Tags aus `<image>.xmp`-Sidecars zurück in die DB importieren (alle Fotos) |
| `python facet.py --import-sidecars /path` | Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums importieren |
| `python facet.py --import-sidecars --user alice` | Mehrbenutzermodus: Bewertungen in die `user_preferences` von Alice statt in die globalen Spalten importieren (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars` | Schreibt/führt `<image>.xmp`-Sidecars aus der DB für alle Fotos zusammen (nur Sidecar) |
| `python facet.py --export-sidecars /path` | Exportiert Sidecars nur für Fotos unterhalb eines Pfad-Teilbaums |
| `python facet.py --export-sidecars --user alice` | Mehrbenutzermodus: Bewertungen aus den `user_preferences` von Alice statt aus den globalen Spalten exportieren (Schlüsselwörter bleiben global) |
| `python facet.py --export-sidecars --embed-originals` | Bettet die Metadaten zusätzlich **in die Datei** für JPEG/HEIC/TIFF/PNG/DNG ein (überschreibt die Originale) |

> **Bidirektionale Metadaten-Synchronisation.** Facet schreibt Bewertungen, Farblabels, Schlüsselwörter, Beschreibungen und benannte Gesichtsregionen in einen standardmäßigen `<image>.xmp`-Sidecar, den das gesamte Ökosystem liest (Lightroom, darktable, digiKam, immich, …). **Standardmäßig wird das Originalbild nie verändert** – nur der Sidecar wird geschrieben/zusammengeführt. Um die Metadaten *in die Datei* für JPEG/HEIC/TIFF/PNG/DNG einzubetten (damit auch Editoren, die Sidecars ignorieren, sie sehen), aktivieren Sie dies ausdrücklich: die Aktion **„Metadaten in Datei schreiben"** pro Miniaturbild im Viewer oder der Befehl `--export-sidecars --embed-originals`. RAW-Originale werden nie verändert. Das Einbetten und das sichere Zusammenführen von Sidecars erfordern **exiftool** (vorhandene/fremde Schlüsselwörter werden gelesen und in die Vereinigung übernommen, nie gelöscht); ohne es greift Facet auf einen abhängigkeitsfreien reinen XML-Sidecar zurück. `--import-sidecars` ist die umgekehrte Richtung: Es fügt externe Änderungen zurück in Facet ein – Bewertungen/Labels gelten *neuestes-gewinnt* (nach `xmp:MetadataDate`, sonst Sidecar-mtime, gegenüber dem `scanned_at` des Fotos), und Schlüsselwörter werden zusammengeführt (Vereinigung), sodass Facets Auto-Tags nie verloren gehen.
>
> **Einschränkungen.** Der fotoseitige Zeitstempel für *neuestes-gewinnt* ist `scanned_at` (der letzte Scan), keine Bewertungs-Bearbeitungszeit – ein Sidecar, das neuer als der letzte Scan ist, kann daher eine Bewertung überschreiben, die Sie *nach* diesem Scan in Facet geändert haben. Führen Sie `--import-sidecars` vor dem erneuten Bewerten in Facet aus, wenn der externe Editor maßgeblich ist. Standardmäßig arbeiten die CLI-Befehle `--import-sidecars` / `--export-sidecars` mit den **globalen Einzelbenutzer**-Bewertungsspalten. Im Mehrbenutzermodus übergeben Sie `--user <name>`, um stattdessen die Bewertungen aus den `user_preferences` dieses Benutzers zu lesen/schreiben (Schlüsselwörter bleiben in beiden Fällen global). Wenn Sie die `photo_tags`-Lookup-Tabelle verwenden, führen Sie anschließend `python database.py --migrate-tags` aus.

## Neuberechnungsoperationen

Diese Befehle aktualisieren bestimmte Metriken ohne vollständige Neuverarbeitung der Fotos.

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --recompute-average` | Gesamtwertungen neu berechnen (erstellt ein Backup) |
| `python facet.py --recompute-category portrait` | Wertungen nur für eine einzelne Kategorie neu berechnen |
| `python facet.py --recompute-tags` | Alle Fotos mit dem konfigurierten Modell neu verschlagworten |
| `python facet.py --recompute-tags-vlm` | Alle Fotos mit dem VLM-Tagger neu verschlagworten |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Motiverkennungsmetriken neu berechnen (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Komposition neu berechnen, regelbasiert (CPU, beliebiges Profil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Komposition mit SAMP-Net neu berechnen |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Ergänzende IQA-Metriken (TOPIQ IAA, NR-Face, LIQE) aus gespeicherten Vorschaubildern neu berechnen |
| `python facet.py --recompute-ocr` | In Bildern enthaltenen Text aus Vorschaubildern in `ocr_text` extrahieren (Opt-in; ohne OCR-Engine wirkungslos; danach `--rebuild-fts` ausführen, um zu indexieren) |
| `python facet.py --recompute-colors` | Dominanten Farbton + warme/kalte Farbtemperatur aus Vorschaubildern extrahieren (CPU, schnell) in `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Schema migrieren und die vollständige Backfill-Kette ausführen: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotent; überspringt aufwändige Schritte wie die Beschreibungserzeugung. |
| `python facet.py --recompute-blinks` | Blinzelerkennung aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-eyes-expression` | Werte für offene Augen + Ausdruck aus gespeicherten Landmarken neu berechnen (CPU, schnell) |
| `python facet.py --recompute-burst` | Serienbild-Erkennungsgruppen neu berechnen |
| `python facet.py --detect-duplicates` | Duplikate via pHash erkennen |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Kosinus-Schwellenwerte für Beinahe-Duplikate auswerten (Präzision/Recall-Tabelle mit Labels, sonst Kandidaten-Kosinus-Verteilung) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` KI-Beschreibungen für Fotos mit VLM erzeugen |
| `python facet.py --translate-captions` | Englische Beschreibungen in die konfigurierte Zielsprache übersetzen (CPU, MarianMT) |
| `python facet.py --extract-gps` | GPS-Koordinaten aus EXIF-Daten in Datenbankspalten extrahieren |
| `python facet.py --rescan-gps` | GPS-Koordinaten für alle Fotos erneut aus EXIF extrahieren (überschreibt vorhandene) |
| `python facet.py --recompute-embeddings` | CLIP/SigLIP-Embeddings für alle Fotos neu berechnen (nach Modellwechsel erforderlich) |
| `python facet.py --score-topiq` | TOPIQ-Qualitätswertungen aus gespeicherten Vorschaubildern nachtragen (GPU erforderlich) |
| `python facet.py --backfill-focal-35mm` | 35-mm-äquivalente Brennweite aus EXIF für Fotos nachtragen, denen sie fehlt |
| `python facet.py --compute-recommendations` | Datenbank analysieren, Bewertungsübersicht anzeigen |
| `python facet.py --compute-recommendations --verbose` | Detaillierte Statistiken anzeigen |
| `python facet.py --compute-recommendations --apply-recommendations` | Bewertungskorrekturen automatisch anwenden |
| `python facet.py --compute-recommendations --simulate` | Vorschau der prognostizierten Änderungen |

### Ergänzende Qualitätsmodelle

Drei zusätzliche PyIQA-Modelle bewerten über die primäre TOPIQ-Ästhetikwertung hinaus. Sie teilen sich den VRAM mit TOPIQ und laufen als Teil der standardmäßigen Multi-Pass-Pipeline.

- **TOPIQ IAA** (`--pass quality-iaa`): AVA-trainierter künstlerisch-ästhetischer Wert, getrennt von der technischen Qualität. Gespeichert als `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): Qualitätsbewertung der Gesichtsregion. Gespeichert als `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): Qualitätswertung plus Diagnose des Verzerrungstyps (z. B. Bewegungsunschärfe, Überbelichtung, Rauschen). Gespeichert als `liqe_score`.

### Benchmarks & ergänzende Wertungen

| Befehl | Beschreibung |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Befüllt die Spalte `aesthetic_clip`, indem zwischengespeicherte CLIP/SigLIP-Embeddings auf eine textbasierte Ästhetikachse projiziert werden. Keine zusätzliche Bildinferenz. Nicht Teil des Standard-`aggregate`. Siehe [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Berechnet SRCC + PLCC gegen die AVA-Mean-Opinion-Score-Referenzdaten für jede befüllte Wertungsspalte in der DB. Nützlich beim Hinzufügen oder Abstimmen einer Modellvariante. |

### Motiverkennung

`--pass saliency` und `--recompute-saliency` verwenden BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`), um eine binäre Motivmaske zu erzeugen, und leiten daraus vier Metriken ab:

- **Motivschärfe**: Laplace-Varianz auf der Motivregion vs. Hintergrund – ob das Motiv scharf ist.
- **Motivhervorhebung**: Motivfläche / Bildfläche – hoch bei einem dominanten Motiv (z. B. Makro).
- **Motivplatzierung**: Drittel-Regel-Wertung für den Motivschwerpunkt.
- **Hintergrundtrennung**: Kantengradient-Differenz zwischen Motivgrenze und Hintergrund – Bokeh-Qualität.

Erfordert `transformers` (~2 GB VRAM).

### Verschlagwortungsmodelle

Das Verschlagwortungsmodell wird je VRAM-Profil ausgewählt:

| Profil | Modell | Funktionsweise |
|---------|-------|-------------|
| `legacy` | CLIP-Ähnlichkeit | Kosinus-Ähnlichkeit zwischen Bild-Embedding und Tag-Text-Embeddings. Kein zusätzliches Laden eines Modells. |
| `8gb` | CLIP-Ähnlichkeit | Wie legacy, auf gespeicherten CLIP-ViT-L-14-Embeddings. |
| `16gb` | Qwen3.5-2B | Multimodales Modell für semantische Szenenverschlagwortung. |
| `24gb` | Qwen3.5-4B | Größeres multimodales Modell. |

Alle Tagger bilden die Ausgabe auf das konfigurierte Tag-Vokabular ab. Verwenden Sie `--recompute-tags`, um mit dem Standardmodell des Profils neu zu verschlagworten, oder `--recompute-tags-vlm` für die VLM-basierte Neuverschlagwortung.

### Embedding-Modelle

Zwei Embedding-Modelle stehen zur Verfügung, ausgewählt je VRAM-Profil über `clip_config`:

| Konfiguration | Modell | Dimensionen | Verwendet von |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | 16gb-, 24gb-Profile |
| `clip_legacy` | CLIP ViT-L-14 | 768 | legacy-, 8gb-Profile |

Embeddings treiben semantische Verschlagwortung, Duplikaterkennung, die Suche nach ähnlichen Fotos und die CLIP+MLP-Ästhetik (legacy/8gb) an. Ein Modellwechsel erfordert ein erneutes Embedding aller Fotos (`--force`, `--pass embeddings` oder `--recompute-embeddings`).

## Gesichtserkennung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Gesichter für neue Fotos extrahieren (GPU, parallel) |
| `python facet.py --extract-faces-gpu-force` | Alle Gesichter löschen und neu extrahieren (GPU) |
| `python facet.py --cluster-faces-incremental` | HDBSCAN-Clustering, behält alle Personen bei (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, behält nur benannte Personen bei (CPU) |
| `python facet.py --cluster-faces-force` | Vollständiges Neu-Clustering, löscht alle Personen (CPU) |
| `python facet.py --suggest-person-merges` | Mögliche Personenzusammenführungen vorschlagen |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Strengeren Schwellenwert verwenden |
| `python facet.py --refill-face-thumbnails-incremental` | Fehlende Vorschaubilder erzeugen (CPU, parallel) |
| `python facet.py --refill-face-thumbnails-force` | ALLE Vorschaubilder neu erzeugen (CPU, parallel) |

## Vorschaubild-Verwaltung

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Drehung gespeicherter Vorschaubilder anhand der EXIF-Ausrichtung korrigieren |

Liest die EXIF-Ausrichtung aus den Originaldateien und dreht die gespeicherten Vorschaubild-Bytes; für Fotos, die vor der Einführung der EXIF-Verarbeitung verarbeitet wurden. Es liest nur den EXIF-Header und das gespeicherte Vorschaubild, nicht die vollständigen Bilder.

## Diagnose

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --doctor` | Diagnoseprüfungen ausführen (Python, GPU, Abhängigkeiten, Konfiguration, Datenbank) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | GPU-Hardware für die Diagnose simulieren |

Meldet Python-Version, PyTorch/CUDA-Build, GPU-Erkennung und -Treiber, VRAM-Profilempfehlung, optionale Abhängigkeiten sowie Konfigurations-/Datenbankstatus. Wenn PyTorch die GPU nicht sieht, `nvidia-smi` aber schon, wird der `pip install`-Befehl zur Korrektur des CUDA-Builds ausgegeben.

`--simulate-gpu NAME` und `--simulate-vram GB` testen das Verhalten mit anderer Hardware. Beide erfordern `--doctor`; `--simulate-vram` erfordert `--simulate-gpu`.

## Modellinformationen

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --list-models` | Verfügbare Modelle und VRAM-Anforderungen anzeigen |

## Gewichtsoptimierung (paarweiser Vergleich)

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --comparison-stats` | Statistiken paarweiser Vergleiche anzeigen |
| `python facet.py --optimize-weights` | Gewichte aus Vergleichen optimieren und speichern (alle Quellen, zuverlässigkeitsgewichtet); nur angewendet, wenn die Held-out-k-Fold-Genauigkeit die aktuellen Gewichte übertrifft |
| `python facet.py --optimize-weights --optimize-force` | Optimierte Gewichte anwenden, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Trainingsdaten auf bestimmte Vergleichsquellen beschränken |
| `python facet.py --optimize-weights --optimize-category portrait` | Nur auf einer Kategorie trainieren und deren v4-`categories[].weights`-Block schreiben |
| `python facet.py --sync-label-comparisons` | Aus Bewertungen abgeleitete Paare (source=rating) aus Sternebewertungen/Favoriten/Ablehnungen neu aufbauen |
| `python facet.py --train-ranker` | Den persönlichen Ranker über [Embedding + Wertungen] trainieren und learned_scores schreiben (abhängig von der Held-out-k-Fold-Genauigkeit gegenüber der Aggregate-Baseline) |
| `python facet.py --train-ranker --ranker-category portrait` | Den Ranker nur auf einer Kategorie trainieren |
| `python facet.py --train-ranker --train-ranker-force` | learned_scores schreiben, auch wenn die Genauigkeitsschwelle nicht erreicht wird |
| `python facet.py --report-unreviewed-bursts` | Melden, wie viele Serienbildgruppen unüberprüft bleiben (schreibgeschützt) |
| `python facet.py --eval-iqa-srcc` | Spearman-SRCC jeder IQA-/Ästhetikmetrik gegenüber Ihren Sternebewertungen melden (schreibgeschützt) |
| `python facet.py --mine-insights` | Data-Mining-Bericht: Label-Inventar, Metrik-Label-Korrelationen, Kategorieverteilung, Perzentil-Drift, Vergleichsgesundheit |
| `python facet.py --mine-insights report.json` | Dasselbe, schreibt zusätzlich den vollständigen Bericht als JSON |

## Konfiguration

| Befehl | Beschreibung |
|---------|-------------|
| `python facet.py --validate-categories` | Kategoriekonfigurationen validieren |

## Verschlagwortung

| Befehl | Beschreibung |
|---------|-------------|
| `python tag_existing.py` | Tags zu nicht verschlagworteten Fotos anhand gespeicherter CLIP-Embeddings hinzufügen |
| `python tag_existing.py --dry-run` | Tags ohne Speichern in der Vorschau anzeigen |
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
| `python validate_db.py --report-only` | Nur melden, ohne Nachfrage |
| `python validate_db.py --db custom.db` | Benutzerdefinierte Datenbank validieren |

Prüfungen: Wertungsbereiche, Gesichtsmetriken, BLOB-Beschädigung, Embedding-Größen, verwaiste Gesichter, statistische Ausreißer.

## Datenbankwartung

| Befehl | Beschreibung |
|---------|-------------|
| `python database.py` | Schema initialisieren/aktualisieren |
| `python database.py --info` | Schemainformationen anzeigen |
| `python database.py --migrate-tags` | photo_tags-Lookup befüllen (10-50x schnellere Abfragen) |
| `python database.py --rebuild-fts` | FTS5-Volltextsuchindex aus Beschreibungen/Tags neu aufbauen |
| `python database.py --populate-vec` | sqlite-vec-Vektorsuchtabelle aus Embeddings befüllen |
| `python database.py --refresh-stats` | Statistik-Cache aktualisieren |
| `python database.py --stats-info` | Cache-Status und -Alter anzeigen |
| `python database.py --vacuum` | Speicherplatz freigeben, defragmentieren |
| `python database.py --analyze` | Statistiken des Query-Planers aktualisieren |
| `python database.py --optimize` | VACUUM und ANALYZE ausführen |
| `python database.py --export-viewer-db` | Leichtgewichtige Viewer-Datenbank exportieren (entfernt BLOBs, verkleinert Vorschaubilder; inkrementell, falls Ausgabe existiert) |
| `python database.py --export-viewer-db --force-export` | Vollständigen Re-Export erzwingen, auch wenn die Viewer-DB bereits existiert |
| `python database.py --cleanup-orphaned-persons` | Personen ohne zugeordnete Gesichter entfernen |
| `python database.py --cleanup-missing-photos` | Nicht mehr auf der Festplatte vorhandene Fotos aus der Datenbank entfernen (kaskadierende Löschungen bereinigen Tags, erkannte Gesichter usw.; entfernt außerdem Albumzugehörigkeiten, den Vektorindex und macht den Statistik-Cache ungültig) |
| `python database.py --cleanup-missing-photos --dry-run` | Fehlende Dateien in der Vorschau anzeigen, ohne zu löschen |
| `python database.py --cleanup-missing-photos --force` | Fortfahren, auch wenn jedes Foto als fehlend erscheint (Schutz dagegen, alles zu löschen, wenn ein Volume nicht eingehängt ist) |
| `python database.py --migrate-storage-fs` | Vorschaubilder und Embeddings aus Datenbank-BLOBs in das Dateisystem migrieren |
| `python database.py --migrate-storage-db` | Vorschaubilder und Embeddings aus dem Dateisystem zurück in die Datenbank migrieren |
| `python database.py --add-user alice --role admin` | Einen Benutzer hinzufügen (fragt nach Passwort) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Benutzer mit Anzeigenamen hinzufügen |
| `python database.py --migrate-user-preferences --user alice` | Bewertungen von photos nach user_preferences kopieren |

**Leistungstipp:** Führen Sie bei großen Datenbanken (50k+ Fotos) `--migrate-tags`, `--rebuild-fts` und `--populate-vec` einmal aus und dann regelmäßig `--optimize`.

## Web-Viewer

| Befehl | Beschreibung |
|---------|-------------|
| `python viewer.py` | Server unter http://localhost:5000 starten (API + Angular-SPA) |
| `python viewer.py --port 5001` | An einen anderen Port binden (oder die Umgebungsvariable `PORT` setzen; Standard 5000) |
| `python viewer.py --host 127.0.0.1` | An eine bestimmte Schnittstelle binden (Standard `0.0.0.0`) |
| `python viewer.py --production` | Produktionsmodus (Uvicorn-Worker) |
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
python facet.py --recompute-average                # Alle Wertungen mit neuen Gewichten aktualisieren
python facet.py --recompute-category portrait      # Nur eine Kategorie aktualisieren (schneller)
```

### Einrichtung der Gesichtserkennung
```bash
python facet.py /path               # Gesichter während des Scans extrahieren
python facet.py --cluster-faces-incremental     # In Personen gruppieren
python facet.py --suggest-person-merges         # Duplikate finden
# Verwenden Sie /persons im Viewer zum Zusammenführen/Umbenennen
```

### Mehrbenutzer-Einrichtung
```bash
# Benutzer hinzufügen (fragt nach Passwort)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# scoring_config.json bearbeiten, um directories und shared_directories festzulegen
# Bestehende Bewertungen zu einem Benutzer migrieren
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
# Oder spezifisch verwenden: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Verteilungen prüfen
python facet.py --recompute-average        # Neue Gewichte anwenden
```
