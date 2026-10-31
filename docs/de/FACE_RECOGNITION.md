# Gesichtserkennung

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · **Deutsch** · [Italiano](../it/FACE_RECOGNITION.md) · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md) · [简体中文](../zh/FACE_RECOGNITION.md)

Facet verwendet InsightFace zur Gesichtserkennung und HDBSCAN, um Gesichter zu Personen zu clustern.

## Überblick

1. **Erkennung** – Das InsightFace-Modell buffalo_l erkennt Gesichter und extrahiert 512-dimensionale Embeddings
2. **Clustering** – HDBSCAN gruppiert ähnliche Embeddings zu Personen-Clustern
3. **Verwaltung** – Web-Viewer zum Zusammenführen, Umbenennen und Organisieren von Personen

## Vollständiger Arbeitsablauf

### Schritt 1: Gesichter extrahieren

Während des Foto-Scans werden Gesichter automatisch extrahiert:

```bash
python facet.py /path/to/photos
```

Für vorhandene Fotos ohne Gesichter:

```bash
python facet.py --extract-faces-gpu-incremental  # Nur neue Fotos
python facet.py --extract-faces-gpu-force        # Alle Fotos (löscht vorhandene)
```

### Schritt 2: Gesichter clustern

Ähnliche Gesichter zu Personen gruppieren:

```bash
python facet.py --cluster-faces-incremental  # Erhält vorhandene Personen
```

**Clustering-Modi:**

| Befehl | Verhalten |
|---------|----------|
| `--cluster-faces-incremental` | Behält alle Personen bei, ordnet neue den vorhandenen zu |
| `--cluster-faces-incremental-named` | Behält nur benannte Personen bei |
| `--cluster-faces-force` | Löscht alle Personen, vollständiges Re-Clustering |

### Schritt 3: Überprüfen und zusammenführen

Doppelte Personen-Cluster finden:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Strenger
```

Öffnet den Browser mit der Seite der Zusammenführungsvorschläge.

### Schritt 4: Verwaltung im Viewer

Die verbleibende Arbeit erfolgt im Web-Viewer, entlang der Pipeline **Extrahieren → Clustern → Zusammenführen → Verwalten**:

- **Zusammenführen** doppelter Cluster auf der Seite mit Zusammenführungsvorschlägen.
- **Verwalten** von Personen (zusammenführen, Stapel-Zusammenführung, aufteilen, ausblenden, umbenennen, löschen) auf der Seite „Personen verwalten“.

Siehe [Viewer-Integration](#viewer-integration) für die vollständige Referenz der Benutzeroberfläche.

## Konfiguration

### Gesichtserkennung

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Mindestkonfidenz der Erkennung |
| `min_face_size` | `20` | Mindestgröße des Gesichts in Pixeln (nur InsightFace, siehe Hinweis) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio für die Blinzelerkennung |

Im kommerziellen Modus verwendet der YuNet-Detektor feste Werte (0,7 Konfidenz, 30 px) und ignoriert `min_confidence_percent` und `min_face_size`.

### Gesichts-Clustering

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Mindestanzahl Fotos, um eine Person zu erstellen |
| `min_samples` | `2` | HDBSCAN-Parameter min_samples |
| `thresholds_by_model` | siehe JSON | Pro Modell: `auto_merge_distance_percent` und `merge_threshold` (ArcFace `15` / `0.6`, SFace `27.5` / `0.65`) |
| `use_gpu` | `"auto"` | GPU-Modus: `auto`, `always`, `never` |

### Gesichtsverarbeitung

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100
  }
}
```

## Clustering-Algorithmen

Wählen Sie für CPU-Clustering den Algorithmus je nach Datensatzgröße:

| Algorithmus | Komplexität | Am besten geeignet für |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Hochdimensionale Daten (empfohlen für 50K+ Gesichter) |
| `boruvka_kdtree` | O(n log n) | Niedrigdimensionale Daten |
| `prims_balltree` | O(n²) | Kleine Datensätze, speicherbeschränkt |
| `prims_kdtree` | O(n²) | Kleine Datensätze |
| `best` | Auto | HDBSCAN entscheiden lassen |

**Leistungshinweis:** Verwenden Sie für große Datensätze `boruvka_balltree`. Mit 80K Gesichtern wird es in 2-5 Minuten abgeschlossen, wo exakte Algorithmen hängen bleiben können.

## GPU-Clustering (cuML)

Für große Datensätze (80K+ Gesichter) ist GPU-Clustering über RAPIDS cuML schneller als CPU.

### Installation

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Konfiguration

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Modus | Verhalten |
|------|----------|
| `"auto"` | GPU verwenden, falls cuML verfügbar, Rückfall auf CPU |
| `"always"` | GPU versuchen, warnen und auf CPU zurückfallen, falls nicht verfügbar |
| `"never"` | Immer CPU verwenden |

**Hinweis:** cuML verwendet seine eigene HDBSCAN-Implementierung. Die Parameter `algorithm` und `leaf_size` gelten nur für CPU-Clustering.

### GPU und CPU liefern nicht dieselben Cluster

Bei gleichen Gesichtern und Parametern bildet cuML etwas mehr, kleinere Cluster als das CPU-Clustering (etwa 1,1–1,2× so viele). Wer mit wem gruppiert wird, bleibt etwa gleich, aber die *Anzahl* der Cluster unterscheidet sich zwischen einem GPU- und einem CPU-Lauf.

**cuML ist zudem nicht deterministisch.** Zwei GPU-Läufe über dieselben Gesichter ergeben nahezu gleiche Clusterzahlen, aber unterschiedliche Labels.

- **Personen-IDs sind zwischen Läufen nicht reproduzierbar.** Benennen Sie die Personen, die Ihnen wichtig sind; benannte Personen bleiben stabil.
- **Vergleichen Sie zwei Clustering-Läufe nicht über die Labels.** Vergleichen Sie stattdessen die Zugehörigkeit der Gesichter.

CPU-Clustering mit festem `algorithm` ist für dieselbe Eingabe deterministisch.

### Erneutes Clustern und bereits benannte Personen

Alle Modi außer `--cluster-faces-force` behalten die Personendatensätze, aber alle berechnen die Person jedes Gesichts neu.

- **Unterbrechungen sind unbedenklich.** Änderungen werden am Ende in einem Schritt geschrieben; ein zuvor gestoppter Lauf ändert nichts.
- **Änderungen im Viewer während eines Laufs.** Ein Gesicht, das Sie neu zuordnen, während der Lauf seine Ergebnisse schreibt (die letzten Sekunden), behält Ihre Zuordnung, und der Lauf protokolliert, wie viele er übersprungen hat. Ein dann gesendetes Speichern wartet auf den Lauf; eines, das länger als 5 s wartet, wird mit „library busy“ abgelehnt und muss wiederholt werden. Eine frühere Änderung, während die Gesichter noch geclustert werden, wird überschrieben.

Ein neu gebildeter Cluster wird einer vorhandenen Person zurückgegeben, wenn entweder:

1. sein mittleres Embedding innerhalb von `merge_threshold` (Standard 0,6 Kosinus für ArcFace, 0,65 für SFace) zum gespeicherten Zentroid dieser Person liegt, **oder**
2. mindestens die Hälfte seiner Gesichter vor dem Lauf zu dieser Person gehörte.

Regel 2 ist wichtig für Personen, die über viele Jahre fotografiert wurden: Ihre Gesichter teilen sich in enge Untercluster, die weit vom einzelnen gemittelten Zentroid entfernt liegen. Ohne sie würden die meisten Gesichter benannter Personen nicht an sie zurückgegeben.

Da Regel 2 der früheren Zuordnung folgt, wird ein alter Fehler fortgeschrieben. Verwenden Sie `--cluster-faces-force`, um von Grund auf neu zu beginnen. Verteilen sich die Gesichter eines Clusters gleichmäßig auf zwei Personen, gewinnt die Person, der das niedrigstnummerierte bereits zugeordnete Gesicht des Clusters gehört.

## Blinzelerkennung

Verwendet die Eye Aspect Ratio (EAR) aus den 106-Punkt-Landmarken von InsightFace.

### Funktionsweise

EAR misst das Verhältnis von Augenhöhe zu Augenbreite. Wenn sich die Augen schließen, fällt der EAR unter den Schwellenwert.

### Konfiguration

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Niedrigerer Schwellenwert = strengere Erkennung (mehr Fotos werden als Blinzler markiert).

### Nach Schwellenwertänderung neu berechnen

```bash
python facet.py --recompute-blinks
```

Verarbeitet nur Fotos mit Gesichtern, keine GPU erforderlich.

## Optionale OFIQ-Gesichtsqualität (kommerzieller Modus)

Im kommerziellen Modus ist das eingeschränkte Gesichtsqualitätsmodell nicht verfügbar. Als optionalen Ersatz installieren Sie `python-ofiq` (UNICEF-Bindings für BSI OFIQ, ISO/IEC 29794-5; MIT):

```bash
pip install python-ofiq
```

- Es gibt nur Wheels für Linux x86-64 und macOS arm64 (unter Windows: WSL2 oder Docker). Es verträgt sich mit numpy 2 und OpenCV 4.8+.
- Bei der ersten Nutzung lädt Facet die OFIQ-Modelle (ca. 400 MB, MIT/Apache-2.0, SHA-256 festgelegt) nach `pretrained_models/ofiq/`.
- OFIQs Wert (0-100) wird durch 10 geteilt und in `face_quality_iqa` gespeichert. Der Wert eines Fotos ist 0,7 x sein schlechtestes Gesicht + 0,3 x der Mittelwert.
- Ohne `python-ofiq` bleibt die Spalte NULL, und ihr Gewicht wird auf die übrigen Metriken verteilt.

## Ausdruckssignale pro Gesicht (Augen offen + Lächeln)

Jedes Gesicht speichert zwei 0–10-Werte, die vom Gesichts-Panel der Auswahl und von den Werten auf Fotoebene verwendet werden: `eyes_open_score` (10 = weit geöffnet, 0 = vollständig geschlossen) und `smile_score` (5 = neutral, 10 = breites Lächeln, 0 = missmutiger Ausdruck).

Zwei Backends erzeugen sie auf derselben Skala:

1. **Geometrie (immer verfügbar).** Berechnet aus den gespeicherten
   106-Punkt-Landmarken von InsightFace: Eye Aspect Ratio für die Augen,
   Mundwinkel-Anhebung für das Lächeln. `--recompute-face-signals` kann sie ohne
   GPU und ohne Bilder zu lesen nachträglich berechnen.
2. **MediaPipe-Blendshapes (optional).** Beim Scannen und bei der Gesichtsextraktion
   wird der Ausschnitt jedes Gesichts durch den MediaPipe Face Landmarker geführt,
   dessen Blendshapes (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) auf dieselben
   Skalen abgebildet werden. Er erkennt geschlossene Augen, subtile Lächeln und
   gedrehte Köpfe besser, daher **ersetzt** sein Wert den geometrischen. Fehlt
   MediaPipe oder sein Modell, oder ist der Ausschnitt zu klein, bleibt der
   geometrische Wert erhalten.

### MediaPipe installieren

MediaPipe ist optional. Installieren Sie es **ohne** das gebündelte
`opencv-contrib-python`, das mit Facets `opencv-python` kollidieren würde (beide
liefern `cv2`):

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Führen Sie niemals ein einfaches `pip install mediapipe` aus.

### Modellbündel

Das Bündel `face_landmarker.task` (~3,6 MiB, Apache-2.0) wird bei der ersten
Verwendung nach `pretrained_models/face_landmarker.task` heruntergeladen. Laden Sie
es offline von
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
herunter und legen Sie es dort ab. Schlägt der Download fehl, warnt Facet einmal
und verwendet die Geometrie.

### Konfiguration

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled` (Standard `true`): Blendshapes verwenden, wenn MediaPipe und das
  Modell verfügbar sind. Auf `false` setzen, um ausschließlich Geometrie zu erzwingen.
- `min_crop_size` (Standard `192`): Gesichter, deren gepolsterter Ausschnitt kleiner
  als dieser Wert ist (px, kürzere Seite), verwenden die Geometrie statt eines
  hochskalierten Ausschnitts.
- `blink_pose_gate_deg` (Standard `null` = aus): nur der MediaPipe-Analyzer des kommerziellen Modus. Ein Gesicht, das um mehr als diese Gradzahl gedreht ist (|Yaw| oder |Pitch|), erhält kein Blinzel-Urteil und keinen Augen-offen-/Lächeln-Score, da ein gedrehter Kopf wie geschlossene Augen wirkt. Beim Testen half kein Grenzwert zwischen 20° und 45°, daher ist er standardmäßig aus; setzen Sie ihn nur, wenn Ihre Bibliothek viele stark gedrehte Gesichter enthält. Er muss eine positive Zahl sein. Er gilt für neu gescannte Fotos; vorhandene `is_blink`-Werte ändern sich erst bei einem erneuten Scan.

### Neuberechnung

`--recompute-face-signals` verwendet ausschließlich gespeicherte Landmarken: Es ist
**rein geometrisch** und führt MediaPipe nicht aus. Um die MediaPipe-Scores zu
aktualisieren, extrahieren Sie die Gesichter mit `--extract-faces-gpu-force` erneut.

## Gesichts-Miniaturansichten

Miniaturansichten werden für eine schnelle Anzeige in der Datenbank gespeichert.

### Speicherung

- Während des Scans aus Bildern in voller Auflösung erzeugt
- In der Spalte `faces.face_thumbnail` als JPEG-BLOBs gespeichert (~5-10KB pro Stück)
- Von Clustering und Viewer genutzt, statt sie neu zu erzeugen

### Neuerzeugung

```bash
# Fehlende Vorschaubilder generieren
python facet.py --refill-face-thumbnails-incremental

# ALLE Vorschaubilder neu generieren
python facet.py --refill-face-thumbnails-force
```

Beide Befehle nutzen Parallelverarbeitung für mehr Geschwindigkeit.

## Datenbankschema

### Tabelle faces

| Spalte | Typ | Beschreibung |
|--------|------|-------------|
| `id` | INTEGER | Primärschlüssel |
| `photo_path` | TEXT | Fremdschlüssel zu photos |
| `face_index` | INTEGER | Index innerhalb des Fotos |
| `embedding` | BLOB | 512-dimensionales Gesichts-Embedding |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Ecken des Begrenzungsrahmens |
| `confidence` | REAL | Erkennungskonfidenz |
| `person_id` | INTEGER | Fremdschlüssel zu persons |
| `face_thumbnail` | BLOB | JPEG-Miniaturansicht |
| `landmark_2d_106` | BLOB | 106-Punkt-Landmarken (Blinzelerkennung) |
| `embedding_model` | TEXT | Tag des Erkennungsmodells (Standard `arcface_buffalo_l`) |

### Tabelle persons

| Spalte | Typ | Beschreibung |
|--------|------|-------------|
| `id` | INTEGER | Primärschlüssel |
| `name` | TEXT | Personenname (NULL = automatisch geclustert) |
| `representative_face_id` | INTEGER | Bestes Gesicht für den Avatar |
| `face_count` | INTEGER | Anzahl der Gesichter |
| `centroid` | BLOB | Zentroid-Embedding des Clusters |
| `auto_clustered` | INTEGER | 1 wenn automatisch erzeugt |
| `face_thumbnail` | BLOB | Avatar-Miniaturansicht der Person |
| `is_hidden` | INTEGER | 1 = von Filtern/Vorschlägen ausgeschlossen |

## Inkrementeller vs. erzwungener Modus

### Inkrementelles Clustering

- Behält alle vorhandenen Personen bei (benannte und automatisch geclusterte)
- Clustert nur neue, nicht zugewiesene Gesichter
- Ordnet neue Cluster vorhandenen Personen über die Zentroid-Ähnlichkeit zu
- Aktualisiert die Zentroide nach dem Zusammenführen

**Verwenden, wenn:** Neue Fotos zu einer vorhandenen Sammlung hinzugefügt werden

### Erzwungenes Clustering

- Löscht ALLE Personen, einschließlich benannter
- Vollständiges Re-Clustering von Grund auf

**Verwenden, wenn:** Neu begonnen wird oder größere Algorithmusänderungen anstehen

### Inkrementell-benanntes Clustering

- Behält nur benannte Personen bei
- Löscht automatisch geclusterte Personen
- Clustert alle unbenannten Gesichter neu

**Verwenden, wenn:** Kuratierte Namen erhalten bleiben sollen, während automatisch erkannte Cluster aktualisiert werden

## Viewer-Integration

### Personenfilter

- Das Dropdown zeigt Personen mit Gesichts-Miniaturansichten
- Galerie nach Person filtern

### Personen-Galerie

- Auf eine Person im Dropdown klicken, um alle ihre Fotos zu sehen
- Ein Klick auf eine Person wendet einen `person_id`-Filter auf die Galerie an (keine eigene Route pro Person)

### Seite „Personen verwalten“

Zugriff über die Header-Schaltfläche oder `/persons`:

- **Rasteransicht** – Alle erkannten Personen
- **Zusammenführen** – Quelle auswählen, Ziel anklicken, bestätigen
- **Stapel-Zusammenführung** – Mehrere Personen auswählen und in ein Ziel zusammenführen
- **Aufteilen** – Ausgewählte Gesichter in eine neue Person verschieben
- **Ausblenden** – Einen Cluster aus der Liste, den Filtern und den Zusammenführungsvorschlägen ausschließen
- **Löschen** – Personen-Cluster entfernen
- **Umbenennen** – Auf den Namen klicken, um ihn inline zu bearbeiten

### Eine Person erstellen

Sie können ein vom Clusterer übersehenes Gesicht direkt aus der Galerie heraus benennen:

1. Öffnen Sie auf einer Fotokarte die Personen-Aktionen und wählen Sie ein nicht zugewiesenes Gesicht.
2. Wählen Sie im Personen-Auswähler **Neue Person erstellen** und geben Sie einen Namen ein.
3. Das Gesicht wird der neuen Person zugeordnet (`auto_clustered = 0`).

Ein Gesicht, das bereits einer anderen Person gehört, wird verschoben, und eine Person
ohne Gesichter wird gelöscht. Im Mehrbenutzermodus dürfen Sie nur Gesichter aus Fotos
in Ihren eigenen oder geteilten Verzeichnissen anhängen. API: `POST /api/persons`
(siehe [API.md](../API.md)).

### Zu benennen

Die Seite „Personen verwalten“ listet große unbenannte Cluster im Reiter
**Zu benennen** auf, jeweils mit einem Namensfeld. Ein Cluster erscheint dort, wenn er
mindestens `viewer.persons.needs_naming_min_faces` Gesichter hat (Standard `5`).

Unbenannt heißt ohne oder mit leerem Namen, ob der Cluster aus dem Clustering oder einer Aufteilung stammt; ausgeblendete (ignorierte) Personen fehlen. Der Reiter erscheint nur im Bearbeitungsmodus, neben **Benannt**, das nur benannte Personen listet, sodass jede Person einmal erscheint; die Seite öffnet auf **Benannt**.

### Seite mit Zusammenführungsvorschlägen

Zugriff über `/merge-suggestions` oder die Schaltfläche „Zusammenführungsvorschläge“ auf der Seite „Personen verwalten“:

- Zeigt Paare von Personen, deren Gesichter ähnlich aussehen
- **Schieberegler für den Schwellenwert** — Ähnlichkeitsgrenze (niedriger = mehr Vorschläge)
- **Ein-Klick-Zusammenführung** — ein vorgeschlagenes Paar zusammenführen
- **Stapel-Zusammenführung** — mehrere Vorschläge auf einmal zusammenführen

### Foto-Karten

- Kleine Gesichts-Miniaturansichten (Avatare) werden für erkannte Personen angezeigt
- Konfigurierbar über `viewer.face_thumbnails.output_size_px`

## Embedding-Raum-Marker (Sicherheit des Erkennungsmodells)

Jedes Gesicht speichert in `embedding_model` das Erkennungsmodell, das es erzeugt hat (Standard `arcface_buffalo_l`, das InsightFace-Modell `buffalo_l` / ArcFace `w600k_r50`). Embeddings verschiedener Modelle sind nicht vergleichbar, daher verwendet das Clustering nur die Gesichter des **aktiven** Modells. Ein `NULL`-Tag zählt als ArcFace. Sind Gesichter eines anderen Modells vorhanden, schließt Facet sie aus und protokolliert eine Warnung.

### Wechsel des Erkennungsmodells (z. B. AdaFace) — aufgeschobener Plan

AdaFace (besseres Clustering unscharfer oder spontaner Gesichter) ist **noch nicht implementiert**. Seine Einführung erforderte eine vollständige Neu-Extraktion und ein Re-Clustering (`--extract-faces-gpu-force`, dann `--cluster-faces-force`), da ArcFace- und AdaFace-Embeddings nicht vergleichbar sind.

### Gemischte Bibliotheken, Neu-Extraktion und unbekannte Werte

- **Gemischte Bibliotheken.** Eine Bibliothek kann ArcFace- (512-d) und SFace-Gesichter (128-d) gleichzeitig enthalten. Clustering, Zusammenführungsvorschläge, die Suche nach ähnlichen Personen und Zentroide verwenden jeweils ein Modell zur Zeit (`persons.centroid_model` hält fest, welches).
  - Die inkrementellen und die Nur-benannte-Modi lassen Gesichter und Personen des anderen Modells unberührt.
  - `--cluster-faces-force` löscht alle Gesicht→Person-Zuordnungen und alle Personen, auch benannte, unabhängig vom Modell.
  - Um eine Bibliothek auf das aktive Modell umzustellen, führen Sie `--extract-faces-gpu-force` aus (im kommerziellen Modus der permissive Extraktor; benannte Personen bleiben erhalten), danach `--cluster-faces-incremental`.
- **Warnungen.** Ein Scan warnt, wenn gespeicherte Gesichter ein anderes als das aktive Modell verwenden, und `--doctor` meldet es ebenfalls. Im kommerziellen Modus listet `--doctor` auf, was ein Scan tatsächlich lädt (YuNet, SFace, Q-ReAlign sowie OFIQ, wenn `python-ofiq` installiert ist). Auf CUDA warnt ein Scan einmal, wenn InsightFace auf der CPU läuft; siehe den ONNX-Runtime-Abschnitt von `--doctor` und [Installation › ONNX Runtime für die Gesichtserkennung](INSTALLATION.md#onnx-runtime-für-die-gesichtserkennung).
- **Benannte Personen überleben die Neu-Extraktion.** `--extract-faces-gpu-force` gibt jedes neu erkannte Gesicht an die benannte Person zurück, deren alte Gesichts-Box es überlappt (IoU >= 0,5, eins zu eins). Nicht zugeordnete Gesichter warten auf den nächsten Clustering-Lauf. Ein unterbrochener Lauf wird bei der nächsten Extraktion fortgesetzt. Das erneute Scannen eines Fotos erhält benannte Personen auf dieselbe Weise.
- **Unbekannt ist nicht null.** Ohne MediaPipe kann der permissive Analyzer Augen, Lächeln und Blinzeln nicht messen, daher werden sie als NULL gespeichert; Blink-Filter und -Abzüge behandeln NULL als „kein Blinzeln“. Schlägt der Gesichtsdurchlauf eines Fotos fehl, sind `face_count`, `face_ratio` und `is_group_portrait` NULL, und seine gespeicherten Gesichter bleiben erhalten; es wird bis zum erneuten Scan als ohne Gesicht bewertet.

## Fehlerbehebung

| Problem | Lösung |
|-------|----------|
| Clustering hängt | Algorithmus `boruvka_balltree` verwenden |
| Zu viele kleine Cluster | `min_faces_per_person` erhöhen |
| Gesichter werden nicht gruppiert | `merge_threshold` verringern |
| GPU-Clustering schlägt fehl | cuML-Installation prüfen, `"never"` verwenden, um CPU zu erzwingen |
| Miniaturansichten fehlen | `--refill-face-thumbnails-incremental` ausführen |
| Falsche Blinzelerkennung | `blink_ear_threshold` anpassen, `--recompute-blinks` ausführen |
| Warnung „Excluded N faces from non-active embedding space“ | Eine Änderung des Erkennungsmodells hat gemischte Embeddings hinterlassen – `--extract-faces-gpu-force`, dann `--cluster-faces-incremental` ausführen |
