# Bewertungssystem

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · **Deutsch** · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md)

Fotos werden zunächst einer Kategorie zugeordnet und anschließend mit den Gewichten dieser Kategorie bewertet.

## So funktioniert die Bewertung

1. **Kategorieerkennung** – Das Foto wird auf seinen Inhalt analysiert (Gesichter, Tags, EXIF-Daten)
2. **Filterauswertung** – Die Kategorien werden in Prioritätsreihenfolge ausgewertet, bis eine zutrifft
3. **Gewichtsanwendung** – Kategoriespezifische Gewichte werden auf die Metriken angewendet
4. **Modifikatoranwendung** – Boni, Strafen und Verhaltensflags werden angewendet
5. **Endwertung** – Gewichtete Summe, begrenzt auf den Bereich 0–10

## Kategorien

`scoring_config.json` definiert 34 Kategorien (33 benannte plus `default`), die in aufsteigender Prioritätsreihenfolge ausgewertet werden, bis eine zutrifft. Die niedrigere Priorität gewinnt. Die vollständige Liste befindet sich im Array `categories`; die wichtigsten:

| Priorität | Kategorie | Erkennungsmethode |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Gesichtsanteil ≥ 5 % UND is_group_portrait |
| 42 | `silhouette` | Hat Gesicht UND is_silhouette |
| 45 | `portrait` | Gesichtsanteil ≥ 5 %, nicht silhouette/group/mono |
| 46 | `portrait_bw` | Monochromes Porträt (Gesicht ≥ 5 %) |
| 55 | `macro` | Tags: macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Tags: animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Verschluss 1–10 Sekunden |
| 85 | `night` | Helligkeit < 0,15 |
| 88 | `monochrome` | is_monochrome (Sättigung < 5 %) |
| 95 | `street` | Tags: street, urban_culture |
| 96 | `human_others` | Hat Gesicht UND Gesichtsanteil < 5 % |
| 100 | `landscape` | Tags: landscape, mountain, beach, forest, ... |
| 999 | `default` | Rückfall (kein Filter) |

Weitere tag-basierte Kategorien sind `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic` und `weather`.

## Kategoriedefinition

Jede Kategorie in `scoring_config.json` besteht aus diesen Komponenten:

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
  },
  "tags": {}
}
```

## Filter-Referenz

### Numerische Bereichsfilter

| Filter | Feld | Beschreibung |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Gesichtsfläche als Anteil (0.0–1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Anzahl der Gesichter |
| `iso_min` / `iso_max` | `ISO` | Kamera-ISO |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Belichtungszeit (Sekunden) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Helligkeit (0.0–1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Brennweite (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Blendenzahl |

### Boolesche Filter

| Filter | Beschreibung |
|--------|-------------|
| `has_face` | Mindestens ein Gesicht erkannt |
| `is_monochrome` | Sättigung < 5 % |
| `is_silhouette` | Gegenlicht mit starken Schatten/Lichtern |
| `is_group_portrait` | face_count >= `min_faces_for_group` (konfigurierbar, Standard: 4) |

### Tag-Filter

| Filter | Beschreibung |
|--------|-------------|
| `required_tags` | Liste der Tags, die das Foto haben muss |
| `excluded_tags` | Liste der Tags, die das Foto NICHT haben darf |
| `tag_match_mode` | `"any"` (Standard) oder `"all"` |

## Gewichtsschlüssel

Alle Gewichte verwenden das Suffix `_percent`. Sie werden von `get_weights()` normalisiert, sodass die Summen nicht exakt 100 ergeben müssen – sie aber bei 100 zu halten, hält die Wertungen auf der Skala 0–10.

| Schlüssel | Metrik | Quelle | Am besten für |
|-----|--------|--------|----------|
| `aesthetic_percent` | Visuelle Anziehungskraft | TOPIQ oder CLIP+MLP | Alle |
| `quality_percent` | Veraltete Qualität | In `aesthetic` umverteilt (kein separates Signal) | — |
| `face_quality_percent` | Gesichtsklarheit | InsightFace | Porträts |
| `eye_sharpness_percent` | Augenschärfe | InsightFace-Landmarken | Porträts |
| `tech_sharpness_percent` | Gesamtschärfe | Laplace-Varianz | Landschaften |
| `composition_percent` | Komposition | SAMP-Net oder regelbasiert | Alle |
| `exposure_percent` | Belichtungsausgleich | Histogrammanalyse | Alle |
| `color_percent` | Farbharmonie | HSV-Analyse | Farbfotos |
| `contrast_percent` | Tonwertkontrast | Histogrammbreite | S&W |
| `dynamic_range_percent` | Tonwertumfang | Histogrammanalyse | HDR, Landschaften |
| `isolation_percent` | Motivtrennung | Gesicht vs. Hintergrund | Porträts, Wildtiere |
| `leading_lines_percent` | Führungslinien | Kantenerkennung | Architektur |
| `power_point_percent` | Drittelregel | Motivplatzierung | Alle |
| `saturation_percent` | Farbsättigung | HSV-Analyse | Lebendige Fotos |
| `noise_percent` | Rauschniveau | Rauschschätzung | Schwaches Licht |
| `face_sharpness_percent` | Schärfe des Gesichtsbereichs | Gesichtsanalyse | Porträts |
| `aesthetic_iaa_percent` | Künstlerischer ästhetischer Wert | TOPIQ IAA (AVA-trainiert) | Kunst, kreativ |
| `face_quality_iqa_percent` | Gesichtsqualität (IQA) | TOPIQ NR-Face | Porträts |
| `liqe_percent` | LIQE-Qualitätswertung | LIQE | Diagnostik |
| `subject_sharpness_percent` | Schärfe des Motivbereichs | BiRefNet + Laplace | Porträts, Wildtiere |
| `subject_prominence_percent` | Anteil der Motivfläche | BiRefNet | Makro, Wildtiere |
| `subject_placement_percent` | Drittelregel des Motivs | BiRefNet | Alle |
| `bg_separation_percent` | Hintergrundtrennung | BiRefNet | Porträts, Makro |

## Modifikatoren

Passen das Bewertungsverhalten pro Kategorie an:

| Modifikator | Typ | Beschreibung |
|----------|------|-------------|
| `bonus` | float | Zur Endwertung addiert (z. B. 0,5) |
| `noise_tolerance_multiplier` | float | Skaliert die Rauschstrafe (0,5 = halb) |
| `iso_tolerance_multiplier` | float | Skaliert die ISO-Strafe |
| `min_saturation_bonus` | float | Bonus für hohe Sättigung |
| `contrast_bonus` | float | Bonus für hohen Kontrast |
| `_skip_clipping_penalty` | bool | Belichtungs-Clipping-Strafe überspringen |
| `_skip_oversaturation_penalty` | bool | Übersättigungsstrafe überspringen |
| `_clipping_multiplier` | float | Skaliert die Clipping-Strafe |
| `_apply_blink_penalty` | bool | Blinzelerkennungsstrafe anwenden |

## Dimensionen der Motiverkennung

Vier aus der BiRefNet-Motivsegmentierung abgeleitete Dimensionen:

| Gewichtsschlüssel | Metrik | Beschreibung |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Motivschärfe | Fokusqualität des Motivbereichs im Vergleich zum Hintergrund. Hoch = scharfes Motiv, weicher Hintergrund. |
| `subject_prominence_percent` | Motivhervorhebung | Motivfläche als Anteil des Bildausschnitts. Hoch bei Makro und eng gerahmten Motiven, niedrig bei weiten Szenen. |
| `subject_placement_percent` | Motivplatzierung | Drittelregel-Wertung für den Schwerpunkt des Motivs. |
| `bg_separation_percent` | Hintergrundtrennung | Unterschied des Kantengradienten an der Motivgrenze (Bokeh-Qualität). |

Verwenden Sie `subject_sharpness_percent` und `bg_separation_percent` für Porträts/Wildtiere; `subject_prominence_percent` für Makro.

## Ergänzende IQA-Dimensionen

Drei zusätzliche Qualitätsmodelle:

| Gewichtsschlüssel | Modell | Beschreibung |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | AVA-trainierter ästhetischer Wert, unterschieden von der auf technische Qualität ausgerichteten Ästhetikwertung. Am besten für Kunst-/Kreativkategorien. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Qualitätsbewertung des Gesichtsbereichs. Am besten für Porträtkategorien. |
| `liqe_percent` | LIQE | Qualitätswertung plus eine Verzerrungsdiagnose (Bewegungsunschärfe, Überbelichtung, Rauschen). |

Diese Modelle laufen als Teil der Standard-Bewertungspipeline und teilen sich VRAM mit TOPIQ. Fügen Sie ihre Gewichtsschlüssel jeder Kategorie hinzu, in der die Bewertung nützlich ist.

### Ergänzende Signale (nicht im Standard-Gesamtwert)

| Spalte | Quelle | Beschreibung |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + zwischengespeichertes CLIP/SigLIP-Embedding | Eine kostenlose ergänzende Ästhetikwertung (0–10), abgeleitet aus zwischengespeicherten Bild-Embeddings durch Projektion auf eine „Ästhetikachse", die aus positiven/negativen Textprompts gebildet wird. Keine zusätzliche Bildinferenz beim Scannen. **Nicht** Teil des Standard-`aggregate`. Befüllen Sie diese mit `python scripts/compute_aesthetic_clip.py --db <path>`. Benchmarken Sie mit `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. AVA-SRCC ≈ 0,52 auf dem 500-Foto-Set `ava_test/` (gegenüber 0,94 für `aesthetic_iaa`) – nützlich als günstiger Vorfilter oder wenn TOPIQ-IAA nicht verfügbar ist. |

## Kategorie-Tags (CLIP-Vokabular)

Tags lösen tag-basierte Kategorien aus und werden mittels CLIP-Ähnlichkeit abgeglichen:

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Jeder Schlüssel ist der kanonische Tag-Name, und das Array enthält Synonyme für den CLIP-Abgleich.

## Bewertung der Beste Auswahl

Der „Beste Auswahl"-Filter des Viewers verwendet eine benutzerdefinierte gewichtete Wertung:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Wertungsberechnung:**
- Mit Gesicht (Gesichtsanteil ≥ 20 %): Alle vier Metriken tragen bei
- Ohne Gesicht: `face_quality_percent` wird auf `aesthetic` und `composition` umverteilt

## VRAM-Profil-Überlegungen

Die Standardgewichte sind für **TOPIQ** (0,93 SRCC) optimiert, das Ästhetikmodell für alle Profile.

| Profil | Ästhetikmodell | Embeddings | Tagger | Empfehlungen |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Beste Genauigkeit, Standardgewichte |
| `16gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Standardgewichte |
| `8gb` | CLIP+MLP (0,76 SRCC) | CLIP ViT-L-14 | CLIP-Ähnlichkeit | Standardgewichte funktionieren gut |
| `legacy` | CLIP+MLP auf CPU | CLIP ViT-L-14 | CLIP-Ähnlichkeit | Standardgewichte, langsamer |

Alle Profile führen zusätzlich ergänzende PyIQA-Modelle aus (TOPIQ IAA, TOPIQ NR-Face, LIQE) und optional BiRefNet_dynamic für die Motiverkennung.

Führen Sie `--compute-recommendations` nach dem Profilwechsel aus, um die Wertungsverteilungen zu analysieren.

## Workflow zur Gewichtsfeinabstimmung

### Option A: Über den Viewer (empfohlen)

1. Öffnen Sie `/stats` → Tab **Kategorien** → Untertab **Gewichte**
2. Bearbeitungsmodus entsperren
3. Wählen Sie eine Kategorie aus dem Editor-Dropdown
4. Passen Sie die Regler an – die live aktualisierte **Vorschau der Wertungsverteilung** zeigt die geschätzte Auswirkung
5. Klicken Sie auf **Speichern** und dann auf **Wertungen neu berechnen**, um die Änderungen anzuwenden

Der Viewer führt im Hintergrund `--recompute-category` aus und aktualisiert nur Fotos in dieser Kategorie.

### Option B: Über die CLI

#### 1. Aktuelle Wertungen analysieren

```bash
python facet.py --compute-recommendations
```

Zeigt:
- Wertungsverteilungen pro Kategorie
- Korrelationsanalyse der Gewichte
- Vorgeschlagene Anpassungen

#### 2. Gewichte anpassen

Bearbeiten Sie die Kategoriegewichte in `scoring_config.json`. Stellen Sie sicher, dass sie sich zu 100 summieren.

#### 3. Wertungen neu berechnen

```bash
python facet.py --recompute-average               # Alle Kategorien
python facet.py --recompute-category portrait      # Einzelne Kategorie (schneller)
```

Verwendet gespeicherte Embeddings – keine GPU nötig.

#### 4. Änderungen validieren

```bash
python facet.py --compute-recommendations
```

Vergleichen Sie die Verteilungen vorher/nachher.

## Modus für paarweisen Vergleich

Trainieren Sie Gewichte durch den Vergleich von Fotopaaren:

### Einrichtung

1. Setzen Sie ein nicht leeres `edition_password` in der Konfiguration: `"viewer": { "edition_password": "your-password" }`
2. Starten Sie den Viewer: `python viewer.py`
3. Klicken Sie auf die Schaltfläche „Vergleichen"

### Vergleichsoberfläche

- Fotos nebeneinander
- Tastatur: A (links gewinnt), B (rechts gewinnt), T (unentschieden), S (überspringen)
- Der Fortschrittsbalken zeigt die Vergleiche in Richtung des Minimums von 50 an

### Vergleichsquellen

Vergleiche tragen eine Markierung `source`, damit der Optimierer sie nach Zuverlässigkeit gewichten kann:

- `vote` – explizite A/B-Stimmen aus der Vergleichsoberfläche
- `culling` – automatisch aus Serienbild-/Ähnlichkeits-Auswahlentscheidungen
  abgeleitet: Jedes abgelehnte Foto wird gegen bis zu zwei behaltene Fotos aus
  derselben Gruppe gepaart (begrenzt auf 12 Paare pro Gruppe). Behaltene Fotos
  gewinnen. Explizite Stimmen zum selben Paar werden niemals überschrieben.
- `rating` – synthetische Paare, generiert aus Sternebewertungen und Favoriten

Das Überprüfen von Serienbildgruppen im Viewer erweitert daher den Trainingsdatensatz
für die Gewichtsoptimierung ohne zusätzlichen Aufwand.

### Gewichtsoptimierung

```bash
# Vergleichsstatistiken prüfen
python facet.py --comparison-stats

# Gewichte aus Vergleichen optimieren (nur angewendet, wenn sie generalisieren)
python facet.py --optimize-weights --optimize-category portrait

# Trainingsdaten auf bestimmte Quellen beschränken
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Anwenden, auch wenn das Held-out-Kriterium nicht erfüllt ist
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Auf alle Fotos anwenden
python facet.py --recompute-average
```

### Pipeline von Labels zu Gewichten

Über explizite A/B-Stimmen hinaus speisen zwei weitere Label-Ströme den Optimierer:

1. **Auswahlentscheidungen** werden bei jeder Serienbild-/Ähnlichkeits-Bestätigung
   automatisch erfasst (`source='culling'`).
2. **Sternebewertungen, Favoriten und Ablehnungen** werden mit `python facet.py --sync-label-comparisons`
   in synthetische Paare materialisiert (`source='rating'`). Ein erneuter Lauf
   synchronisiert aus den aktuellen Labels neu, sodass zurückgezogene Bewertungen verschwinden.

Der Optimierer gewichtet jede Quelle nach Zuverlässigkeit (vote 1.0, rating 0.7,
culling 0.5), wenn er die Bradley-Terry-Likelihood maximiert. Er trainiert auf dem
exakten 0–10-Metrikvektor, den der Scorer verwendet (einschließlich `liqe`, `aesthetic_iaa`,
`face_quality_iqa` und der Motiverkennungs-Metriken), sodass die optimierten Gewichte
direkt auf die Produktivbewertung abgebildet werden.

Gewichte werden **nur angewendet, wenn sie generalisieren**: Die endgültigen Gewichte werden auf
allen Vergleichen angepasst, aber die Entscheidung, sie zu schreiben, ist an die Held-out-k-fold-Genauigkeit
gekoppelt, nicht an die Trainingsgenauigkeit. Liegt der Held-out-Gewinn gegenüber den aktuellen Gewichten
unter dem Schwellenwert (Standard 2 pp), meldet der Lauf die Zahlen und schreibt
nichts – verwenden Sie `--optimize-force`, um dies zu übersteuern. Die Optimierung erfolgt pro Kategorie und
benötigt gelabelte Vergleiche **für diese Kategorie**; Kategorien ohne Stimmen
können nicht aus Daten abgestimmt werden.

Empfohlene Kadenz:

```bash
python facet.py --mine-insights          # welches Signal existiert, Drift, Zustand
python facet.py --sync-label-comparisons # bewertungsabgeleitete Paare aktualisieren
python facet.py --optimize-weights       # Gewichte aus allen Quellen lernen
python facet.py --recompute-average      # anwenden + Perzentil-Snapshot persistieren
```

### Gewichtsfeinabstimmung in der Benutzeroberfläche

1. Öffnen Sie das Panel „Gewichtungsvorschau" während des Vergleichs
2. Passen Sie die Regler an, um Wertungsänderungen in Echtzeit zu sehen
3. Klicken Sie auf „Gewichte vorschlagen" für optimierte Werte
4. Aktualisieren Sie die Konfiguration manuell

## Eigene Kategorien hinzufügen

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

Fügen Sie sie dem Array `categories` in `scoring_config.json` hinzu und führen Sie dann `--recompute-average` aus (oder `--recompute-category underwater` nur für die neue Kategorie).

## Workflow-Beispiele

### Konzertkategorie feinabstimmen

```bash
# scoring_config.json bearbeiten:
# Kategorie "concert" suchen, anpassen:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

Oder verwenden Sie den Gewichtseditor des Viewers unter `/stats` → Kategorien → Gewichte für eine Live-Vorschau und Neuberechnung mit einem Klick.

### Zum 8gb-Profil wechseln

```bash
# Bearbeiten: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analysieren
# Bei Bedarf aesthetic_percent in den Kategorien reduzieren
python facet.py --recompute-average
```

### Unterwasserkategorie hinzufügen

1. Kategoriedefinition hinzufügen (siehe oben)
2. `python facet.py --validate-categories` ausführen
3. `python facet.py --recompute-average` ausführen
