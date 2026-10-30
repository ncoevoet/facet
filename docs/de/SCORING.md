# Bewertungssystem

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · **Deutsch** · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · [Português](../pt/SCORING.md) · [简体中文](../zh/SCORING.md)

Fotos werden zunächst einer Kategorie zugeordnet und anschließend mit den Gewichten dieser Kategorie bewertet.

Fehlende oder NULL-Werte für subject_sharpness, subject_prominence, subject_placement, bg_separation und face_quality_iqa werden aus der gewichteten Bewertung ausgeschlossen. Nur ihr positives Gewicht wird auf verfügbare Metriken verteilt; null bleibt ein gültiger Messwert. Fehlen alle gewichteten Eingaben, gilt der neutrale Wert 5.0. Lizenzausschlüsse gelten zuerst. Die ausgelieferten Gewichte bleiben unverändert. Gewichtsanpassung und Vergleichs-/Verteilungsauswertung folgen mit repräsentativen Vergleichsdaten. Für Salienz zuerst `--recompute-saliency`, dann `--recompute-average` ausführen.

## So funktioniert die Bewertung

1. **Kategorieerkennung** – Das Foto wird auf seinen Inhalt analysiert (Gesichter, Tags, EXIF-Daten)
2. **Filterauswertung** – Die Kategorien werden in Prioritätsreihenfolge ausgewertet, bis eine zutrifft (ein [Bewertungskontext](#bewertungskontexte) kann dies pro Album oder Foto ändern)
3. **Gewichtsanwendung** – Kategoriespezifische Gewichte werden auf die Metriken angewendet
4. **Modifikatoranwendung** – Boni, Strafen und Verhaltensflags werden angewendet
5. **Endwertung** – Gewichtete Summe, begrenzt auf den Bereich 0–10

## Kategorien

`scoring_config.json` definiert 34 Kategorien (33 benannte plus `default`), die in aufsteigender Prioritätsreihenfolge ausgewertet werden, bis eine zutrifft. Die niedrigere Priorität gewinnt. Die vollständige Liste befindet sich im Array `categories`; die wichtigsten:

| Priorität | Kategorie | Erkennungsmethode |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way, UND mittlere Leuchtdichte ≤ 0.30 |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Gesichtsanteil ≥ 5 % UND is_group_portrait |
| 42 | `silhouette` | Hat Gesicht UND `is_silhouette` (das größte Gesicht ist dunkel vor hellerer Umgebung) |
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

Auf den CLIP-Tagging-Profilen (`legacy`/`8gb` sowie `16gb`/`24gb`, wenn ihr VLM-Tagger nicht läuft) vergibt ein Scan die Tags jedes Fotos, bevor er dessen Kategorie berechnet; die gespeicherte Kategorie nutzt also die Tags. Ein einzelner `--pass NAME`-Lauf vergibt keine Tags.

**Silhouette.** `is_silhouette` stammt aus einer gesichtsbezogenen Pixelregel (siehe [Boolesche Filter](#boolesche-filter)), nicht aus einem Tag.

- Ist `exposure.silhouette_detection` auf `true` (Standard), überspringt der Gesamtwert einer Silhouette die Clipping-Strafe.
- Ein Scan speichert `exposure_score` mit der Clipping-Strafe. `--recompute-average` berechnet ihn für jedes Foto mit `is_silhouette` ohne die Strafe neu, unabhängig von `exposure.silhouette_detection`.
- Um die Flags einer bestehenden Bibliothek neu abzuleiten, führen Sie `python facet.py --recompute-silhouette` aus, danach `--recompute-average` zweimal (siehe [COMMANDS.md](COMMANDS.md)).

**Astro.** Ein Foto braucht einen Astro-Tag *und* eine mittlere Leuchtdichte von höchstens 0.30 (`luminance_max`). Eine helle Szene mit dem Tag `aurora` oder `stars` ist kein Astro, und ein Foto ohne gespeicherte Leuchtdichte passt nie. Hat Ihre `scoring_config.json` ein eigenes `categories`-Array, tragen Sie `"luminance_max": 0.30` selbst in `astro.filters` ein; `python facet.py --doctor` meldet, wenn er fehlt.

## Bewertungskontexte

Ein **Bewertungskontext** ändert die Kategorienreihenfolge für einige Fotos, ohne die globalen Prioritäten anzutasten. Er zieht einige Kategorien an den Anfang und schließt andere aus. `default` (leere Listen `promote`/`excluded`) ändert nichts, und Fotos verwenden ihn, solange Sie keinen anderen zuweisen.

**Effektive Reihenfolge** = `promote` (in der angegebenen Reihenfolge) → die globale Prioritätsreihenfolge abzüglich der vorgezogenen und ausgeschlossenen Namen → `default` zuletzt. Ein Name, der in `promote` und `excluded` steht, wird entfernt: `excluded` gewinnt.

Mitgelieferte Voreinstellungen, bearbeitbar im Tab **Bewertungskontext** des Viewers oder im JSON (Feldreferenz: [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte)):

| Context | Promotes | Excludes |
|---------|----------|----------|
| `default` | – | – |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | – |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | – |
| `wildlife` | `wildlife` | – |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | – |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Sie bearbeiten nur die Liste der vorgezogenen Kategorien (Bearbeitungsmodus; ziehen oder nach oben/unten verschieben) und die Ausschlüsse. Die übrigen Kategorien behalten immer die globale Reihenfolge, sodass in einem Kontext nie eine neue Kategorie fehlt. Validierungsregeln: [Einen Kontext bearbeiten](CONFIGURATION.md#einen-kontext-bearbeiten).

**Einen Kontext zuweisen:**

- **Pro Album.** Gilt für jedes Foto, das derzeit im Album ist. Es ist eine einmalige Momentaufnahme: Fotos, die später zu einem intelligenten Album hinzukommen, erhalten ihn nicht. Siehe [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte).
- **Pro Foto.** Eine dauerhafte Kategorieüberschreibung für ein einzelnes Foto.

Beide überstehen erneute Scans und lassen sich getrennt zurücksetzen.

**Keiner von beiden wirkt sich auf bereits bewertete Fotos aus, bevor Sie neu berechnen:** Führen Sie `python facet.py --recompute-average` aus oder berechnen Sie im Viewer neu (siehe [Das Ändern von Prioritäten erfordert eine Neuberechnung](CONFIGURATION.md#die-globale-priorität-neu-ordnen)). Ist `normalization.per_category` aktiviert, führen Sie es zweimal aus (siehe [Normalization](CONFIGURATION.md#normalization)).

### Die Falle fehlender EXIF-Daten

Eine Neuordnung ändert nur, welche Kategorie *zuerst versucht* wird. Sie kann nicht bewirken, dass die Filter einer Kategorie zutreffen. Ein numerischer Bereichsfilter scheitert, wenn der Wert des Fotos fehlt oder nicht auswertbar ist, genau so, als läge er außerhalb des Bereichs.

Beispiel: `sports` (Priorität 71) trägt `shutter_speed_max: 0.02`. Eine Tanzaufnahme, die langsamer als 1/50s belichtet wurde oder keine auslesbare Verschlusszeit hat, scheitert an diesem Filter, selbst wenn `action_stage` `sports` an den Anfang zieht. Das Foto fällt durch zur nächsten passenden Kategorie, typischerweise `fashion` (Priorität 43, mit Tag `fashion`, hat ein Gesicht) oder `silhouette` (Priorität 42, Gegenlicht mit Gesicht).

**Landet ein Foto in einer unerwarteten Kategorie, prüfen Sie zuerst dies:** Können die numerischen Filter der Zielkategorie zu den gespeicherten EXIF-Daten des Fotos passen, nicht nur zu seinen Tags?

### Die Falle des fehlenden Tags

`required_tags` scheitert auf dieselbe Weise: Ein Filter kann nicht auf einen Tag zutreffen, der im Vokabular fehlt. Die `required_tags` von `sports` sind `sports`, `motion`, `athlete`, `competition`, `action_sport` und `dance`.

`sports.tags.dance` trägt 11 CLIP-Prompts (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), und `dance` steht in `sports.filters.required_tags`. Ein getaggtes Tanzfoto kann `sports` erreichen, aber eines mit langsamer Verschlusszeit oder ohne EXIF scheitert weiterhin an `shutter_speed_max: 0.02`.

**Bereits vorhandene Fotos behalten ihre Tags.** Eine Vokabularänderung wirkt nur auf neues Tagging; führen Sie `python facet.py --recompute-tags` aus, um sie auf die Bibliothek anzuwenden.

### Die globale Priorität neu ordnen

Sie können die globale Priorität im Viewer neu ordnen (Bearbeitungsmodus). Die Neuordnung tauscht die vorhandenen Prioritätswerte zwischen Kategorien, statt neu zu nummerieren, sodass die Zahlen in der obigen Tabelle aussagekräftig bleiben. `default` (Priorität 999) bleibt immer am Ende. Jeder Schreibvorgang legt zuerst eine zeitgestempelte Kopie `.backup.<timestamp>` von `scoring_config.json` an.

Die Neuordnung ändert nicht die gespeicherte `category` eines Fotos: Führen Sie anschließend eine Neuberechnung aus.

**Bekannte Einschränkung:** Das Typ-Dropdown der Galerie behält seine alte Reihenfolge, bis der Viewer neu gestartet wird. Zuordnung und Filterung nutzen die neue Reihenfolge sofort.

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
| `is_silhouette` | Das größte Gesicht ist dunkel vor heller Umgebung (siehe unten). Ein Foto ohne Gesicht ist nie eine Silhouette |
| `is_group_portrait` | face_count >= `min_faces_for_group` (konfigurierbar, Standard: 4) |

**Regel für `is_silhouette`.** Die mittlere Helligkeit (Luma, 0-1) der zentralen 60 % des Gesichtsrahmens liegt unter 0.12, und das Band um den Rahmen (von 0.2 bis 0.75 der Rahmengröße nach außen auf jeder Seite, am Bildrand beschnitten) ist um mehr als 0.20 heller. Der CLIP-Tag `silhouette` und das Histogramm des ganzen Bildes setzen es nicht.

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
| `quality_percent` | Veraltete Qualität | Vor der Bewertung zu `aesthetic_percent` addiert (kein separates Signal) | — |
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

**`quality_percent` zählt zu `aesthetic`.** Die Qualitätsmetrik hat keinen eigenen Wert, daher wird das `quality_percent` einer Kategorie auf `aesthetic` umverteilt: Es wird vor der Bewertung zu `aesthetic_percent` addiert, und die Gewichte ergeben weiterhin 100. Frühere Versionen verloren diesen Anteil im Gesamtwert; führen Sie nach dem Upgrade einmal `--recompute-average` aus, um ihn zurückzuerhalten. Kategorien ändern sich nicht.

## Modifikatoren

Passen das Bewertungsverhalten pro Kategorie an:

| Modifikator | Typ | Beschreibung |
|----------|------|-------------|
| `bonus` | float | Zur Endwertung addiert (z. B. 0,5) |
| `noise_tolerance_multiplier` | float | Skaliert die Rauschstrafe (0,5 = halb) |
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

**Kein Motiv, keine Zahl.** Wird kein Motiv gefunden, werden `subject_sharpness`, `subject_placement` und `bg_separation` als NULL gespeichert (ebenso `power_point_score`, wenn es keinen Motivrahmen gibt), `subject_prominence` ist 0.0 und `subject_bbox` NULL.

- Die Bereichsfilter der Galerie überspringen ein NULL (`min_subject_sharpness=0` liefert kein Foto ohne Motiv). Statistiken lassen es bei Mittelwerten weg, und die Oberfläche zeigt es als fehlend.
- Der Gesamtwert bewertet ein NULL als neutrale 5.0, sodass sich kein Gesamtwert ändert.
- Frühere Versionen speicherten eine neutrale 5.0. Bestehende Zeilen behalten sie, bis `--recompute-saliency` und `--recompute-composition-cpu` sie umschreiben.

**Wenn die Salienz fehlschlägt**, wird nichts geschrieben; Facet speichert nie eine neutrale Zahl für ein fehlgeschlagenes Ergebnis. Ein nie bewertetes Foto behält NULL in allen fünf Salienz-Spalten (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`) und wird neutral (5.0) bewertet, wie ein Foto, das gescannt wurde, bevor es die Salienz gab. Regeln für Wiederholung und Batchgröße: [Motiv-Salienz](COMMANDS.md#motiv-salienz).

## Ergänzende IQA-Dimensionen

Drei zusätzliche Qualitätsmodelle:

| Gewichtsschlüssel | Modell | Beschreibung |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | AVA-trainierter ästhetischer Wert, unterschieden von der auf technische Qualität ausgerichteten Ästhetikwertung. Am besten für Kunst-/Kreativkategorien. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Qualitätsbewertung des Gesichtsbereichs. Am besten für Porträtkategorien. |
| `liqe_percent` | LIQE | Qualitätswertung plus eine Verzerrungsdiagnose (Bewegungsunschärfe, Überbelichtung, Rauschen). |

Diese Modelle laufen auf jedem Profil als Teil der Standard-Bewertungspipeline, auch auf dem CPU-Profil `legacy` (dort langsamer), und teilen sich auf einer GPU VRAM mit TOPIQ. Fügen Sie ihre Gewichtsschlüssel jeder Kategorie hinzu, in der die Bewertung nützlich ist.

**Wenn ein ergänzendes Modell ein Foto nicht bewerten kann**, speichert es in der Spalte dieses Modells (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) NULL statt einer neutralen 5.0. Das passiert, wenn TOPIQ NR-Face kein Gesicht findet oder LIQE eine kurze Seite unter 224 px erhält; Aesthetic V2.5 kann, sofern aktiviert, bei jedem Bild fehlschlagen. Ein CPU-Speicherfehler wird nicht mit kleinerer Batchgröße wiederholt.

- **Gesamtwert:** Ein NULL wird neutral (5.0) bewertet, sodass sich Gesamtwerte, Kategorien und Rangfolgen nicht ändern.
- **Galerie:** Ein Bereichsfilter auf Ästhetik (IAA), Gesichtsqualität (IQA), LIQE oder Aesthetic V2.5 trifft auf ein unbewertetes Foto nicht zu (`min_face_quality_iqa=0` überspringt ein Foto ohne Gesicht). Eine aufsteigende Sortierung danach, nach Q-ReAlign oder DeQA stellt unbewertete Fotos ans Ende, in der Galerie und in Alben.
- **Alte neutrale 5.0-Werte** bleiben, bis `--repair-neutral-iqa` sie löscht; führen Sie danach `--recompute-iqa` und `--recompute-average` aus, oder scannen Sie mit `--force` neu.
- **Ausfall des primären Modells** (TOPIQ auf `16gb` und `24gb`): Das Foto wird als fehlgeschlagen erfasst, statt mit einer neutralen 5.0 gespeichert zu werden. Ein neues Foto nimmt der nächste Scan auf; ein bereits gespeichertes behält seine Zeile und wird von `--retry-failed all` (ein bloßes `--retry-failed` erfasst nur den letzten Lauf mit Fehlern) oder einem weiteren `--force`-Neuscan erneut verarbeitet.

Wiederholungsregeln für jeden Befehl: [Ergänzende Qualitätsmodelle](COMMANDS.md#ergänzende-qualitätsmodelle).

### Ergänzende Signale (nicht im Standard-Gesamtwert)

| Spalte | Quelle | Beschreibung |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + zwischengespeichertes CLIP/SigLIP-Embedding | Kostenlose Ästhetikwertung (0–10) aus zwischengespeicherten Embeddings; **nicht** im Standard-`aggregate` |

`aesthetic_clip` projiziert jedes Bild-Embedding auf eine „Ästhetikachse“, die aus Textprompts gebildet wird, und braucht daher keine zusätzliche Bildinferenz.

- Befüllen Sie sie mit `python scripts/compute_aesthetic_clip.py --db <path>`.
- Benchmarken Sie mit `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- AVA-SRCC ≈ 0,52 auf dem 500-Foto-Set `ava_test/` (gegenüber 0,94 für `aesthetic_iaa`). Nutzen Sie sie als günstigen Vorfilter oder wenn TOPIQ-IAA nicht verfügbar ist.

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
- Ohne Gesicht: `face_quality_percent` wird gleichmäßig (je zur Hälfte) auf `aesthetic` und `composition` umverteilt (mit den Standardgewichten: aesthetic 0.40, composition 0.30)

## VRAM-Profil-Überlegungen

Die Standardgewichte sind für **TOPIQ** (0,93 SRCC) optimiert, das Ästhetikmodell für alle Profile.

| Profil | Ästhetikmodell | Embeddings | Tagger | Empfehlungen |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Beste Genauigkeit, Standardgewichte |
| `16gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Standardgewichte |
| `8gb` | CLIP+MLP (0,76 SRCC) | CLIP ViT-L-14 | CLIP-Ähnlichkeit | Standardgewichte funktionieren gut |
| `legacy` | CLIP+MLP auf CPU | CLIP ViT-L-14 | CLIP-Ähnlichkeit | Standardgewichte, langsamer |

Alle Profile, auch das CPU-Profil `legacy`, führen zusätzlich ergänzende PyIQA-Modelle aus (TOPIQ IAA, TOPIQ NR-Face, LIQE) und optional BiRefNet_dynamic für die Motiverkennung.

Führen Sie `--compute-recommendations` nach dem Profilwechsel aus, um die Wertungsverteilungen zu analysieren.

## Workflow zur Gewichtsfeinabstimmung

### Option A: Über den Viewer (empfohlen)

1. Öffnen Sie `/stats` → Tab **Kategorien** → Untertab **Gewichte**
2. Bearbeitungsmodus entsperren
3. Wählen Sie eine Kategorie aus dem Editor-Dropdown
4. Passen Sie die Regler an – die live aktualisierte **Vorschau der Wertungsverteilung** zeigt die geschätzte Auswirkung
5. Klicken Sie auf **Speichern** und dann auf **Wertungen neu berechnen**, um die Änderungen anzuwenden

Der Viewer führt im Hintergrund `--recompute-category` aus und aktualisiert nur Fotos in dieser Kategorie.

Ein MCP-Assistent kann diese Gewichte lesen und eine Änderung probeweise durchrechnen, ohne etwas zu ändern: `explain_score` (warum ein Foto seinen Score erhielt), `category_weights` und `preview_weights` (eine Näherungsvorschau mit Rangänderungen). Siehe [Scores und Gewichte](AGENTS.md#scores-und-gewichte).

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
- Tastatur: ← (links gewinnt), → (rechts gewinnt), T (unentschieden), S (überspringen). Die Schaltflächen auf dem Bildschirm sind mit **A** / **B** beschriftet.
- Der Fortschrittsbalken zeigt die Vergleiche in Richtung des Minimums von 50 an

### Vergleichsquellen

Jeder Vergleich hat eine `source`, die der Optimierer nach Zuverlässigkeit gewichtet:

- `vote` – explizite A/B-Stimmen aus der Vergleichsoberfläche
- `culling` – aus Serienbild-/Ähnlichkeits-Auswahlentscheidungen: Jedes abgelehnte
  Foto wird gegen bis zu zwei behaltene Fotos aus seiner Gruppe gepaart (höchstens
  12 Paare pro Gruppe). Behaltene Fotos gewinnen. Explizite Stimmen zum selben Paar
  werden niemals überschrieben.
- `rating` – synthetische Paare aus Sternebewertungen und Favoriten

Das Überprüfen von Serienbildgruppen im Viewer erweitert daher auch den Trainingsdatensatz.

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

Über A/B-Stimmen hinaus speisen zwei weitere Label-Ströme den Optimierer:

1. **Auswahlentscheidungen** werden bei jeder Serienbild-/Ähnlichkeits-Bestätigung
   erfasst (`source='culling'`).
2. **Sternebewertungen, Favoriten und Ablehnungen** werden mit
   `python facet.py --sync-label-comparisons` zu synthetischen Paaren (`source='rating'`).
   Ein erneuter Lauf synchronisiert aus den aktuellen Labels neu, sodass
   zurückgezogene Bewertungen verschwinden.

**So funktioniert die Anpassung.** Der Optimierer findet die Gewichte, die den Gewinner jedes Vergleichs am besten vorhersagen (ein Bradley-Terry-Modell).

- Quellen zählen nach Zuverlässigkeit: vote 1.0, rating 0.7, culling 0.5.
- Ein **Gleichstand** zählt als halber Sieg und halbe Niederlage.
- Die Anpassung ist an **Ihre aktuellen Gewichte verankert**: Bei wenigen Vergleichen bleibt sie nahe an ihnen.
- Sie nutzt dieselben 0–10-Metriken wie der Gesamtwert (einschließlich `liqe`, `aesthetic_iaa`, `face_quality_iqa` und der Motiverkennung), wobei Augenschärfe, technische Schärfe und Farbe nach den Perzentilen normalisiert sind, die das letzte `--recompute-average` gespeichert hat.
- `quality_percent` wird wie im Scorer in `aesthetic` gefaltet; das Anwenden schreibt `quality_percent: 0`.

**Gewichte werden nur angewendet, wenn sie generalisieren.** Die Entscheidung nutzt Held-out-Vergleiche: 5-fache Kreuzvalidierung mit **fotogruppierten Folds** (kein Foto steckt zugleich in Trainings- und Held-out-Paaren).

- Ein **einseitiger exakter McNemar-Test** prüft, ob die neuen Gewichte deutlich mehr der Paare gewinnen, bei denen die beiden Gewichtungen uneins sind.
- Die Gewichte werden nur angewendet, wenn `p < 0.05` **und** der Held-out-Gewinn mindestens 2 Prozentpunkte beträgt. Sonst protokolliert der Lauf die Zahlen und schreibt nichts.
- Mit `--optimize-force` wenden Sie sie trotzdem an. Kann der Test nicht laufen (zu wenige unabhängige Fotogruppen), wird ohne Erzwingen nichts angewendet.
- Jede Kategorie braucht mindestens 30 **entscheidende** Vergleiche (ein Foto hat gewonnen) **in dieser Kategorie**. Gleichstände und andere Kategorien zählen nicht.

Beispielprotokoll:

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**Das Anwenden erhält das Niveau der Kategorie.** `--optimize-weights` ändert, wie die Fotos einer Kategorie untereinander rangieren, nicht gegenüber anderen Kategorien. Es verschiebt `modifiers.bonus`, um die mittlere Wertungsverschiebung der Kategorie auszugleichen.

- Der Bonus bleibt innerhalb von [-5, 5]; das Protokoll meldet, wenn diese Grenze greift.
- Eine Kategorie ohne Eintrag in `categories` (`others`) hat keinen Bonus und wird nicht neu zentriert.
- Das Wiederherstellen eines Gewichts-Snapshots stellt Gewichte **und** Bonus wieder her. Ältere Snapshots, solche von `calibrate.py` und solche für `others` lassen den Bonus unberührt.
- Die Schaltfläche **Anwenden** des Viewers und manuelle Bearbeitungen im Tab „Gewichte“ zentrieren den Bonus nicht neu; nur `--optimize-weights` tut das.

**Trainieren Sie nach dem Upgrade den persönlichen Ranker und den Keeper-Head neu (`--train-ranker`, `--train-keeper`) und führen Sie dann `--recompute-average` aus.** Sie lesen nun nach Perzentilen normalisierte Augenschärfe, technische Schärfe und Farbe, und ein älteres gespeichertes Modell kann die Änderung nicht erkennen.

Empfohlene Kadenz:

```bash
python facet.py --mine-insights          # welches Signal existiert, Drift, Zustand
python facet.py --sync-label-comparisons # bewertungsabgeleitete Paare aktualisieren
python facet.py --optimize-weights       # Gewichte aus allen Quellen lernen
python facet.py --recompute-average      # anwenden + Perzentil-Snapshot persistieren
```

### Gewichtsfeinabstimmung in der Benutzeroberfläche

Während des Vergleichs zeigt das Panel „Gewichtungsvorschau“ die Wertungsänderungen, während Sie die Regler bewegen, und **Gewichte vorschlagen** schlägt optimierte Werte vor. Speichern und Neuberechnen funktionieren wie in [Option A: Über den Viewer](#option-a-über-den-viewer-empfohlen).

**Gewichte vorschlagen** zeigt zwei Kennzahlen, im Tab „Gewichtsvorschläge“ und in der Seitenleiste des Tabs „A/B-Vergleich“:

- `accuracy_before`: wie oft die aktuellen Gewichte den Gewinner der gelabelten Paare dieser Kategorie vorhersagen.
- `accuracy_after`: dasselbe für die vorgeschlagenen Gewichte. Sie wird an den Paaren gemessen, auf denen angepasst wurde, und ist daher optimistisch.

**Anwenden** wird nur angeboten, wenn derselbe Held-out-McNemar-Test wie in der CLI besteht (`suggest_changes` ist wahr). Die Kreuzvalidierung läuft nur, wenn der optimistische Gewinn 2 Prozentpunkte erreicht (`?use_cv=true` führt sie immer aus). Der Viewer benötigt `min_comparisons_for_optimization` (Standard 50) entscheidende Vergleiche in der Kategorie, die CLI dagegen 30. Darunter meldet er „Need at least N decisive comparisons (have K)“.

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
