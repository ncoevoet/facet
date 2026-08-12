# Bewertungssystem

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · **Deutsch** · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · [Português](../pt/SCORING.md)

Fotos werden zunächst einer Kategorie zugeordnet und anschließend mit den Gewichten dieser Kategorie bewertet.

## So funktioniert die Bewertung

1. **Kategorieerkennung** – Das Foto wird auf seinen Inhalt analysiert (Gesichter, Tags, EXIF-Daten)
2. **Filterauswertung** – Die Kategorien werden in Prioritätsreihenfolge ausgewertet, bis eine zutrifft (ein *Bewertungskontext* kann Kategorien pro Album oder Foto vorziehen/ausschließen, ohne die Basisreihenfolge zu ändern – siehe [Bewertungskontexte](#bewertungskontexte))
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

## Bewertungskontexte

Die obige Prioritätsreihenfolge ist global – jedes Foto wird gegen dieselbe Liste ausgewertet. Ein **Bewertungskontext** ist ein benanntes *Delta* über dieser Basisreihenfolge: Er zieht eine kurze Liste von Kategorien an den Anfang und schließt andere vollständig aus, ohne irgendetwas neu zu nummerieren. `default` (leere `promote`-/`excluded`-Listen) ist der Kontext ohne Wirkung, sodass sich für ein Foto nichts ändert, solange ihm nicht explizit ein Kontext zugewiesen wird.

**Effektive Reihenfolge** = `promote` (in der angegebenen Reihenfolge) → die globale Prioritätsreihenfolge abzüglich der vorgezogenen und ausgeschlossenen Namen → `default` zuletzt. Ein Name, der sowohl in `promote` als auch in `excluded` steht, wird vollständig entfernt – `excluded` gewinnt. `ScoringConfig.resolve_context_order()` (`config/scoring_config.py`) berechnet dies einmal pro Kontextname und speichert das Ergebnis zwischen (memoization).

Mitgelieferte Voreinstellungen – bearbeitbar über den Tab **Bewertungskontext** des Viewers (`PUT /api/config/scoring_contexts/{name}`, nur im Bearbeitungsmodus) oder direkt im JSON; die vollständige Feldreferenz siehe [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte):

| Context | Promotes | Excludes |
|---------|----------|----------|
| `default` | – | – |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | – |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | – |
| `wildlife` | `wildlife` | – |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | – |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Nur das *Delta* ist bearbeitbar — den bevorzugten Kopf in die gewünschte Reihenfolge ziehen (oder die Schaltflächen Nach oben / Nach unten verwenden), den Ausschluss einer Kategorie umschalten — nie eine vollständige eigenständige Reihenfolge pro Kontext: die nicht bevorzugten Kategorien behalten immer die globale Prioritätsreihenfolge, sodass eine später hinzugefügte Kategorie nie stillschweigend in sechs getrennten Listen fehlen kann. Die Validierungsregeln siehe [Einen Kontext bearbeiten](CONFIGURATION.md#einen-kontext-bearbeiten).

Ein Kontext wird pro Album zugewiesen (`PUT /api/albums/{id}/scoring_context`, was ihn auf jedes Foto überträgt, das gerade Mitglied ist – bei einem intelligenten Album eine Momentaufnahme, kein Abonnement, siehe [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte)) oder, für ein einzelnes hartnäckiges Foto, als dauerhafte Kategorieüberschreibung angewendet (`POST /api/comparison/override_category`). Beide Hebel werden in einer separaten Tabelle `photo_scoring_overrides` gespeichert statt als Spalten auf `photos` – `save_photo`/`save_photos_batch` schreiben Fotozeilen mit `INSERT OR REPLACE`, was eine neue Spalte auf dieser Zeile beim nächsten erneuten Scan stillschweigend löschen würde. Das Setzen des einen Hebels lässt den anderen unberührt, und beide können unabhängig voneinander zurückgesetzt werden. **Keiner der beiden wirkt sich auf bereits bewertete Fotos aus, bevor nicht eine Neuberechnung erfolgt** – `python facet.py --recompute-average` oder `POST /api/scan/recompute` über den Viewer (prozessübergreifend dagegen abgesichert, dass zwei gleichzeitig laufen – siehe [Das Ändern von Prioritäten erfordert eine Neuberechnung](CONFIGURATION.md#die-globale-priorität-neu-ordnen)). Ist `normalization.per_category` aktiviert, führen Sie die Neuberechnung zweimal aus – siehe [Normalization](CONFIGURATION.md#normalization) dafür, warum der erste Durchlauf anhand der alten Kategorie jedes Fotos normalisiert.

### Die Falle fehlender EXIF-Daten

Eine Neuordnung – ob durch Bearbeiten der globalen Priorität oder durch Vorziehen via Kontext – ändert nur, welche Kategorie *zuerst versucht* wird. Sie kann nicht bewirken, dass die Filter einer Kategorie auf ein Foto zutreffen, auf das sie sonst nicht zuträfen. `config/category_filter.py:122-128` lässt einen numerischen Bereichsfilter grundsätzlich scheitern, sobald der zugrunde liegende Fotowert fehlt oder nicht auswertbar ist, anstatt nur diese Grenze zu überspringen – ein fehlender Wert und ein außerhalb des Bereichs liegender Wert werden identisch behandelt, und die Kategorie wird in beiden Fällen übersprungen.

Konkret: `sports` (Priorität 71) trägt `shutter_speed_max: 0.02`. Eine Tanzaufnahme, die langsamer als 1/50s belichtet wurde, oder ganz ohne auslesbare EXIF-Verschlusszeit, scheitert an diesem Filter, egal wo `sports` in der Auswertungsreihenfolge steht – selbst wenn es durch einen Kontext wie `action_stage` ganz nach vorn gezogen wird. Das Foto fällt durch zur nächstpassenden Kategorie, typischerweise `fashion` (Priorität 43, mit Tag `fashion`, hat ein Gesicht) oder `silhouette` (Priorität 42, Gegenlicht mit Gesicht). **Das ist die mit Abstand nützlichste Prüfung, wenn ein Foto in einer unerwarteten Kategorie landet:** Bevor Sie etwas neu ordnen oder vorziehen, stellen Sie sicher, dass die numerischen Filter der Zielkategorie tatsächlich zu den gespeicherten EXIF-Daten des Fotos passen können, nicht nur zu seinen Tags.

### Die Falle des fehlenden Tags

Die EXIF-Falle oben setzt voraus, dass die Tag-Ebene bereits getroffen hat – `required_tags` hat ihre eigene Version desselben Problems: Ein Filter kann nicht auf einen Tag zutreffen, den es im CLIP-Vokabular überhaupt nicht gibt. Vor dem Commit `917dd94` deckte nichts in `scoring_config.json` Tanz ab: Ein Bild, das der Tagger als Tanz, Performance oder Bühne beschrieb, traf auf keinen der `required_tags` von `sports` (`sports`, `motion`, `athlete`, `competition`, `action_sport`) zu und fiel direkt durch zum `default`-Rückfall – `sports` über `action_stage` vorzuziehen änderte daran nichts, denn eine Beförderung ordnet nur um, *wann* eine Kategorie versucht wird, niemals, ob ihre Filter zutreffen.

`sports.tags.dance` trägt jetzt 11 CLIP-Prompts (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), und `dance` wurde zu `sports.filters.required_tags` hinzugefügt, sodass ein getaggtes Tanzfoto diesen Filter jetzt besteht. Das macht `sports` für Tanzinhalte *erreichbar* – es hebt die Verschlusszeit-Falle oben nicht auf: Ein Tanzbild mit langsamer Verschlusszeit oder ganz ohne EXIF kann jetzt die Tag-Prüfung bestehen und trotzdem an `shutter_speed_max: 0.02` scheitern und landet dann genau wie dort beschrieben bei `fashion` oder `silhouette`.

**Bereits vorhandene Fotos behalten ihre bisherigen Tags** – das neue Vokabular ändert nur, was der Tagger ab jetzt vergibt. Verschlagworten Sie die Bibliothek mit `python facet.py --recompute-tags` neu, um es rückwirkend anzuwenden.

### Die globale Priorität neu ordnen

`GET/POST /api/config/category_priorities` (Edition-geschützt) liest und schreibt die Basisreihenfolge, gegen die jeder Kontext sein Delta bildet. `POST` erwartet `{"order": [name, ...]}` – eine mengengleiche Permutation aller Kategorienamen außer `default` – und **permutiert die vorhandenen Prioritätswerte auf die neue Reihenfolge**, statt sie neu durchzunummerieren (10/20/30/…): Die Multimenge der Prioritäten bleibt unverändert, sodass die Zahlen in der obigen Tabelle aussagekräftig bleiben und die Eindeutigkeit konstruktionsbedingt erhalten bleibt. `default` (Priorität 999) ist fest am Ende verankert und von der Neuordnung ausgeschlossen. Jeder Schreibvorgang legt zunächst eine zeitgestempelte Kopie `.backup.<timestamp>` von `scoring_config.json` an; dieser Writer teilt sich nun eine Sperre mit dem Gewichtseditor (`update_category_weights`), da das vorherige ungeschützte Read-Modify-Write dazu führen konnte, dass ein gleichzeitiges Speichern der beiden die Änderungen des jeweils anderen stillschweigend verwarf.

Die Neuordnung allein verändert nicht die gespeicherte `category` eines Fotos – führen Sie anschließend eine Neuberechnung aus (`--recompute-average` oder `POST /api/scan/recompute`), um sie anzuwenden.

**Bekannte Einschränkung:** `api/types.py` erstellt die Typ-/Filter-Dropdown-Liste der Galerie einmalig beim Import aus `ScoringConfig.get_categories()`. Eine Prioritätsänderung wirkt sich sofort auf die tatsächliche Kategoriezuordnung aus (jeder Bewertungs- und Neuberechnungsaufruf liest die Konfiguration erneut von der Festplatte), aber das Typ-Dropdown der Galerie behält seine alte Reihenfolge bei, bis der Viewer-Prozess neu gestartet wird. Das Filtern selbst ist davon nicht betroffen – die Neuordnung fügt keine Kategorienamen hinzu oder entfernt welche.

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

**Gewichte vorschlagen** beantwortet auch eine engere Frage als das CV-Gate oben: Wie gut stimmen die *aktuell live* verwendeten Gewichte dieser Kategorie bereits mit Ihren eigenen Vergleichen überein? Ein Klick liefert `accuracy_before` — den Prozentsatz der gelabelten Paare dieser Kategorie (A/B-Stimmen, Aussortieren und aus Bewertungen abgeleitete Paare), deren Gewinner die live verwendeten Gewichte korrekt vorhersagen — neben `accuracy_after`, derselben Kennzahl für die vorgeschlagenen Gewichte. Beide werden bei jedem Ausführen nebeneinander im Tab „Gewichtsvorschläge" und in der Seitenleiste des Tabs „A/B-Vergleich" angezeigt (`GET /api/comparison/learned_weights`, `optimization/weight_optimizer.py:optimize_weights_direct`). Wie das CLI-Gate benötigt dies `min_comparisons_for_optimization` (Standard 30) gelabelte Paare für diese Kategorie — darunter meldet die Schaltfläche das Defizit statt einer Zahl.

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
