# Konfigurationsreferenz

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · **Deutsch** · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md)

Alle Einstellungen befinden sich in `scoring_config.json`. Führen Sie nach einer Änderung `python facet.py --recompute-average` aus, um die Bewertungen zu aktualisieren (keine GPU erforderlich).

## Inhaltsverzeichnis

- [Benutzer](#users)
- [Scannen](#scanning)
- [Kategorien](#categories)
- [Bewertung](#scoring)
- [Schwellenwerte](#thresholds)
- [Komposition](#composition)
- [EXIF-Anpassungen](#exif-adjustments)
- [Belichtung](#exposure)
- [Abzüge](#penalties)
- [Normalisierung](#normalization)
- [Modelle](#models)
- [Modelle zur Qualitätsbewertung](#quality-assessment-models)
- [Verarbeitung](#processing)
- [Serienbild-Erkennung](#burst-detection)
- [Serienbild-Bewertung](#burst-scoring)
- [Duplikat-Erkennung](#duplicate-detection)
- [Gesichtserkennung](#face-detection)
- [Gesichts-Clustering](#face-clustering)
- [Gesichtsverarbeitung](#face-processing)
- [Monochrom-Erkennung](#monochrome-detection)
- [Verschlagwortung](#tagging)
- [Eigenständige Tags](#standalone-tags)
- [Analyse](#analysis)
- [Viewer](#viewer)
- [Performance](#performance)
- [Speicherung](#storage)
- [Plugins](#plugins)
- [Capsules](#capsules)
- [Ähnlichkeitsgruppen](#similarity-groups)
- [Szenen](#scenes)
- [Timeline](#timeline)
- [Karte](#map)
- [Übersetzung](#translation)

---

## Users

Optionaler Mehrbenutzermodus. Wenn der Schlüssel `users` vorhanden ist (mit mindestens einem Benutzer), wird die Authentifizierung mit einem einzigen Passwort durch eine benutzerspezifische Anmeldung ersetzt.

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### Benutzerfelder

| Feld | Typ | Beschreibung |
|-------|------|-------------|
| `password_hash` | string | PBKDF2-HMAC-SHA256-Hash (`salt_hex:dk_hex`). Erzeugt durch das CLI `--add-user`. |
| `display_name` | string | Wird in der UI-Kopfzeile angezeigt |
| `role` | string | `user`, `admin` oder `superadmin` |
| `directories` | array | Private Fotoverzeichnisse für diesen Benutzer |

### Geteilte Verzeichnisse

Der Schlüssel `shared_directories` (Geschwisterelement der Benutzerobjekte) listet Verzeichnisse auf, die für alle Benutzer sichtbar sind.

### Rollen

| Rolle | Eigene + geteilte ansehen | Bewerten/Favorisieren | Personen/Gesichter verwalten | Scans auslösen |
|------|:-:|:-:|:-:|:-:|
| `user` | ja | ja | nein | nein |
| `admin` | ja | ja | ja | nein |
| `superadmin` | ja | ja | ja | ja |

### Benutzer hinzufügen

Benutzer werden ausschließlich über das CLI erstellt — es gibt keine Registrierungs-UI oder -API:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Fragt nach dem Passwort und schreibt den Hash in scoring_config.json
```

Bearbeiten Sie nach dem Hinzufügen eines Benutzers die `scoring_config.json`, um dessen `directories` zu konfigurieren.

### Abwärtskompatibilität

- Kein `users`-Schlüssel = klassischer Einzelbenutzermodus (unverändertes Verhalten)
- `viewer.password` und `viewer.edition_password` werden im Mehrbenutzermodus ignoriert
- Vorhandene Bewertungen in der Tabelle `photos` bleiben für den Einzelbenutzermodus erhalten; verwenden Sie `--migrate-user-preferences`, um sie zu kopieren

---

## Scanning

Steuert das Verhalten beim Scannen von Verzeichnissen.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Überspringt Verzeichnisse, die mit `.` beginnen, beim Scannen von Fotos |

---

## Categories

Array von Kategoriedefinitionen. Siehe [Bewertung](SCORING.md) für die detaillierte Kategoriedokumentation.

Jede Kategorie hat:
- `name` - Kategoriebezeichner
- `priority` - Niedriger = höhere Priorität (wird zuerst ausgewertet)
- `filters` - Bedingungen für die Zuordnung
- `weights` - Gewichte der Bewertungsmetriken (Summe muss 100 ergeben)
- `modifiers` - Verhaltensanpassungen
- `tags` - CLIP-Vokabular für tagbasierte Zuordnung

> **Form- & Farbharmonie-Gewichte.** Der `weights`-Block jeder Kategorie trägt fünf erklärbare Metrik-Schlüssel — `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` und `color_harmony_percent` — befüllt durch `--recompute-form`. Sie werden in jeder Kategorie mit `0` ausgeliefert, sodass Aggregate byte-identisch bleiben, bis Sie einem ein Gewicht geben (führen Sie dann `--recompute-average` erneut aus). Die Gewichte innerhalb einer Kategorie müssen weiterhin in Summe 100 ergeben.

---

## Scoring

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `score_min` | `0.0` | Minimal mögliche Bewertung |
| `score_max` | `10.0` | Maximal mögliche Bewertung |
| `score_precision` | `2` | Nachkommastellen der Bewertungen |

---

## Thresholds

Erkennungsschwellen für die automatische Kategorisierung.

```json
{
  "thresholds": {
    "portrait_face_ratio_percent": 5,
    "blink_penalty_percent": 50,
    "night_luminance_threshold": 0.15,
    "night_iso_threshold": 3200,
    "long_exposure_shutter_threshold": 1.0,
    "astro_shutter_threshold": 10.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | Gesicht > 5 % des Bildes = Porträt |
| `blink_penalty_percent` | `50` | Bewertungsmultiplikator bei erkanntem Blinzeln (0,5x) |
| `night_luminance_threshold` | `0.15` | Mittlere Leuchtdichte unterhalb dieses Werts = Nacht |
| `night_iso_threshold` | `3200` | ISO über diesem Wert = wenig Licht |
| `long_exposure_shutter_threshold` | `1.0` | Verschlusszeit > 1 s = Langzeitbelichtung |
| `astro_shutter_threshold` | `10.0` | Verschlusszeit > 10 s = Astrofotografie |

---

## Composition

Regelbasierte Kompositionsbewertung (verwendet, wenn SAMP-Net nicht aktiv ist).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Gewicht für die Platzierung nach Drittelregel |
| `line_weight` | `1.0` | Gewicht für Führungslinien |

---

## EXIF Adjustments

Automatische Bewertungsanpassungen basierend auf Kameraeinstellungen.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Reduziert den Schärfeabzug bei hohem ISO-Wert |
| `aperture_isolation_boost` | `true` | Verstärkt die Freistellung bei offenen Blenden (f/1.4–f/2.8) |

---

## Exposure

Steuert die Belichtungsanalyse und die Erkennung von Beschnitt (Clipping).

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Markieren, wenn > 15 % der Pixel reines Schwarz sind |
| `highlight_clip_threshold_percent` | `10` | Markieren, wenn > 10 % der Pixel reines Weiß sind |
| `silhouette_detection` | `true` | Erkennt beabsichtigte Silhouetten |

---

## Penalties

Bewertungsabzüge für technische Probleme.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "bimodality_threshold": 2.5,
    "bimodality_penalty_points": 0.5,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_pixel_percent": 5,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Rauschen oberhalb dieses Werts löst einen Abzug aus |
| `noise_max_penalty_points` | `1.5` | Maximaler Rauschabzug |
| `noise_penalty_per_sigma` | `0.3` | Punkte pro Sigma oberhalb des Schwellenwerts |
| `bimodality_threshold` | `2.5` | Bimodalitätskoeffizient des Histogramms |
| `bimodality_penalty_points` | `0.5` | Abzug für bimodale Histogramme |
| `leading_lines_blend_percent` | `30` | Einmischung in comp_score |
| `oversaturation_threshold` | `0.9` | Schwellenwert für mittlere Sättigung |
| `oversaturation_pixel_percent` | `5` | Reserviert für Erkennung auf Pixelebene |
| `oversaturation_penalty_points` | `0.5` | Abzug für Übersättigung |

**Formel für den Rauschabzug:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Steuert, wie Rohmetriken auf Bewertungen von 0–10 skaliert werden.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `method` | `"percentile"` | Normalisierungsmethode |
| `percentile_target` | `90` | 90. Perzentil = Bewertung von 10,0 |
| `per_category` | `true` | Kategoriespezifische Normalisierung |
| `category_min_samples` | `50` | Mindestanzahl an Fotos für die kategoriespezifische Normalisierung |

---

## Models

Wählt aus, welche Modelle je VRAM-Profil verwendet werden.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": [],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (8GB+ RAM)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "qwen2-vl-2b",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "similarity_threshold_percent": 8
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "similarity_threshold_percent": 22
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth",
      "download_url": "https://github.com/bcmi/Image-Composition-Assessment-with-SAMP/releases/download/v1.0/samp_net.pth",
      "input_size": 384,
      "patterns": [
        "none", "center", "rule_of_thirds", "golden_ratio", "triangle",
        "horizontal", "vertical", "diagonal", "symmetric", "curved",
        "radial", "vanishing_point", "pattern", "fill_frame"
      ]
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Aktives Profil (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Modelle zwischen Multi-Pass-Chunks im RAM halten (`"auto"`, `"always"`, `"never"`). `auto` prüft vor dem Caching den verfügbaren RAM. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | PyIQA-Modelle, die für dieses Profil ausgeführt werden (leer bei `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | BiRefNet-Subjekt-Saliency für dieses Profil ausführen |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | SigLIP 2 NaFlex Embedding-Modell (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) oder `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Embedding-Dimensionen (1152 für SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Minimale CLIP-Kosinusähnlichkeit für eine Tag-Übereinstimmung |
| `clip_legacy.model_name` | `"ViT-L-14"` | Legacy-CLIP-Modell (Profile legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Legacy-Pretrained-Gewichte |
| `clip_legacy.embedding_dim` | `768` | Legacy-Embedding-Dimensionen |
| `clip_legacy.similarity_threshold_percent` | `22` | Tag-Übereinstimmungsschwelle für Legacy-CLIP |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | HuggingFace-Pfad (Kompositions-VLM für 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Verschlagwortungsmodell für das Profil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Bilder pro VLM-Inferenz-Batch |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Verschlagwortungsmodell für das Profil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Bilder pro VLM-Inferenz-Batch |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | BiRefNet-Saliency-Modell |
| `saliency.resolution` | `1024` | Inferenzauflösung |
| `saliency.mask_threshold` | `0.3` | Sigmoid-Schwellenwert für die binäre Subjektmaske |
| `saliency.min_subject_pixels` | `50` | Mindestanzahl an Subjektpixeln, um ein Subjekt als erkannt zu werten |
| `samp_net.input_size` | `384` | Eingabegröße des Kompositionsmodells |

### Automatische VRAM-Erkennung

Wenn `vram_profile` auf `"auto"` (Standard) gesetzt ist, erkennt das System beim Start den verfügbaren GPU-VRAM und wählt das größte passende Profil aus:

| Erkannter VRAM | Ausgewähltes Profil |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Keine GPU | `legacy` (verwendet System-RAM) |

---

## Quality Assessment Models

Wählt das Modell aus, das Bildqualität/Ästhetik bewertet, über die Bibliothek [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `model` | `"auto"` | Qualitätsmodell: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` verwendet `topiq`. |
| `prefer_llm` | `false` | Bevorzugt einen LLM-basierten Bewerter, sofern verfügbar |

### Verfügbare Qualitätsmodelle

SRCC = Spearman-Rangkorrelationskoeffizient auf dem KonIQ-10k-Benchmark (1,0 = perfekt).

| Modell | SRCC | VRAM | Anmerkungen |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Standard (`auto`); ResNet50-Backbone mit Top-down-Attention |
| `hyperiqa` | 0.90 | ~2GB | Hyper-Netzwerk, inhaltsadaptiv |
| `dbcnn` | 0.90 | ~2GB | Dual-Branch-CNN (synthetische + authentische Störungen) |
| `musiq` | 0.87 | ~2GB | Multi-Scale-Transformer; verarbeitet jede Auflösung |
| `clipiqa+` | 0.86 | ~4GB | CLIP mit gelernten Quality-Prompts |
| `clip-mlp` | 0.76 | ~4GB | Legacy CLIP ViT-L-14 + MLP-Head |

### Qualitätsmodelle wechseln

1. Bearbeiten Sie `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Vorhandene Fotos neu bewerten (optional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Vereinheitlichte Verarbeitungseinstellungen für die GPU-Batch-Verarbeitung und den Multi-Pass-Modus.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Schlüsselkonzepte

**`gpu_batch_size`** - Wie viele Bilder zusammen auf der GPU in einem einzigen Forward-Pass verarbeitet werden. Durch den VRAM begrenzt. Automatisch optimiert: wird reduziert, wenn der GPU-Speicher das Limit überschreitet.

**`ram_chunk_size`** - Wie viele Bilder zwischen Modelldurchläufen im RAM zwischengespeichert werden (nur Multi-Pass-Modus). Reduziert Disk-I/O, indem Bilder einmal pro Chunk geladen werden. Durch den System-RAM begrenzt. Automatisch optimiert: wird reduziert, wenn der Systemspeicher das Limit überschreitet.

### Einstellungsreferenz

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mode` | `"auto"` | Verarbeitungsmodus: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Bilder pro GPU-Batch (VRAM-begrenzt) |
| `ram_chunk_size` | `32` | Bilder pro RAM-Chunk (Multi-Pass) |
| `num_workers` | `4` | Threads zum Laden von Bildern |
| `load_workers` | `num_workers` | Threads zum Laden von Multi-Pass-Chunks (auf 8 begrenzt, `1` = sequenziell) |
| `raw_decode_concurrency` | `0` (auto) | Maximale gleichzeitige RAW-Dekodierungen; automatisch aus CPU/RAM bemessen (1–4), `1` = vollständig serialisiert |
| `raw_decode_timeout_seconds` | `120` | Abbruch einer hängenden RAW-Dekodierung nach dieser Verzögerung (`0` = deaktiviert); der Scan bricht nach wiederholten Hängern schnell ab |
| `exif_prefetch` | `true` | Single-Pass-Modus: EXIF im Hintergrund vorab laden, statt den GPU-Thread zu blockieren |
| **auto_tuning** | | |
| `enabled` | `true` | Auto-Tuning aktivieren |
| `monitor_interval_seconds` | `5` | Intervall der Ressourcenprüfung |
| `tuning_interval_images` | `32` | Alle N Bilder neu optimieren |
| `min_processing_workers` | `1` | Minimale Lade-Threads |
| `max_processing_workers` | `32` | Maximale Lade-Threads |
| `min_gpu_batch_size` | `2` | Minimale GPU-Batchgröße |
| `max_gpu_batch_size` | `32` | Maximale GPU-Batchgröße |
| `min_ram_chunk_size` | `10` | Minimale RAM-Chunkgröße |
| `max_ram_chunk_size` | `128` | Maximale RAM-Chunkgröße |
| `memory_limit_percent` | `85` | Limit für die Systemspeicherauslastung |
| `cpu_target_percent` | `85` | Zielwert für die CPU-Auslastung |
| `metrics_print_interval_seconds` | `30` | Intervall für die Statistikausgabe |
| **thumbnails** | | |
| `photo_size` | `640` | Größe gespeicherter Thumbnails (Pixel) |
| `photo_quality` | `80` | JPEG-Qualität der Thumbnails |
| `face_padding_ratio` | `0.3` | Rand um Gesichtsausschnitte |

### Verarbeitungsmodi

| Modus | Beschreibung |
|------|-------------|
| `auto` | Wählt anhand des VRAM automatisch Multi-Pass oder Single-Pass aus |
| `multi-pass` | Sequenzielles Laden der Modelle (funktioniert mit begrenztem VRAM) |
| `single-pass` | Alle Modelle gleichzeitig geladen (erfordert viel VRAM) |

### Funktionsweise von Multi-Pass

Anstatt alle Modelle gleichzeitig zu laden, geht Multi-Pass wie folgt vor:

1. Lädt Bilder in RAM-Chunks (Standard `ram_chunk_size`: 32)
2. Führt für jeden Chunk die Modelle sequenziell aus: Modell laden → Chunk verarbeiten → Modell entladen
3. Kombiniert die Ergebnisse in einem abschließenden Aggregationsdurchlauf

Jedes Bild wird einmal pro Chunk geladen, und Durchläufe werden so gruppiert, dass sie in den verfügbaren VRAM passen, sodass auch die größeren Tagger-/Kompositions-VLMs selbst bei begrenztem VRAM laufen.

### Auto-Tuning-Verhalten

Das System überwacht die Ressourcennutzung und passt an:

| Metrik | Aktion |
|--------|--------|
| GPU-Speicher > Limit | `gpu_batch_size` um 25 % reduzieren |
| System-RAM > Limit | `ram_chunk_size` um 25 % reduzieren |
| System-RAM < (Limit − 20 %) | `ram_chunk_size` um 25 % erhöhen |
| CPU > Ziel | Weniger Worker vorschlagen |
| Queue-Timeouts > 5 % | Mehr Worker vorschlagen |

### Dynamische Durchlauf-Gruppierung

Wenn der VRAM es zulässt, laufen mehrere kleine Modelle zusammen:

| VRAM | Durchlauf 1 | Durchlauf 2 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | Tagger-VLM |
| 24GB+ | Alle Modelle zusammen (Single-Pass) | - |

### CLI-Optionen

```bash
# Standard: automatischer Multi-Pass mit optimaler Gruppierung
python facet.py /path/to/photos

# Single-Pass erzwingen (alle Modelle gleichzeitig geladen)
python facet.py /path --single-pass

# Nur einen bestimmten Durchlauf ausführen
python facet.py /path --pass quality       # nur TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (ästhetischer Wert)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (Qualität + Verzerrung)
python facet.py /path --pass tags          # nur konfigurierter Tagger
python facet.py /path --pass composition   # nur SAMP-Net
python facet.py /path --pass faces         # nur InsightFace
python facet.py /path --pass embeddings    # nur CLIP/SigLIP-Embeddings
python facet.py /path --pass saliency      # BiRefNet-Subjekt-Saliency

# Verfügbare Modelle auflisten
python facet.py --list-models
```

---

## Burst Detection

Gruppiert ähnliche Fotos, die in schneller Folge aufgenommen wurden.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Schwellenwert für die Image-Hash-Ähnlichkeit |
| `time_window_minutes` | `0.8` | Maximale Zeit zwischen Fotos |
| `rapid_burst_seconds` | `0.4` | Fotos innerhalb dieser Zeit werden automatisch gruppiert |

---

## Burst Scoring

Gewichte, die beim Serienbild-Culling verwendet werden, um eine zusammengesetzte Bewertung für die Auswahl der besten Aufnahme innerhalb jeder Serienbildgruppe zu berechnen. Die Gewichte sollten in der Summe 1,0 ergeben.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Gewicht der Gesamtbewertung (Aggregate) |
| `weight_aesthetic` | `0.25` | Gewicht der ästhetischen Qualitätsbewertung |
| `weight_sharpness` | `0.2` | Gewicht der technischen Schärfebewertung |
| `weight_blink` | `0.15` | Abzugsgewicht für erkanntes Blinzeln (höher = stärkerer Abzug) |

---

## Duplicate Detection

Erkennt Duplikate global mittels Vergleich des Perceptual Hash (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Strikte pHash-Schranke (90 % = Hamming-Distanz <= 6 von 64 Bits); wird als alleiniges Kriterium verwendet, wenn für eines der beiden Fotos ein Embedding fehlt |
| `prefilter_hamming` | `12` | Optionale Überschreibung (in der ausgelieferten Datei nicht vorhanden). Lockere Hamming-Schranke der Stufe 1 für die Kandidatenmenge, wenn beide Fotos Embeddings besitzen (auf >= die strikte Schranke angehoben) |
| `embedding_cosine_threshold` | `0.90` | Optionale Überschreibung (in der ausgelieferten Datei nicht vorhanden). SigLIP/CLIP-Kosinus-Schranke der Stufe 2: Ein Kandidat mit lockerem pHash wird nur zusammengeführt, wenn der Kosinus >= diesem Wert ist |

Die Erkennung erfolgt zweistufig: lockere pHash-Kandidaten (Recall), bestätigt durch eine enge Embedding-Kosinus-Schranke (Precision). Fotos ohne Embedding fallen auf das strikte pHash-only-Kriterium zurück, sodass sich das Verhalten nicht ändert, wenn keine Embeddings vorhanden sind.

Führen Sie `python facet.py --detect-duplicates` aus, um Duplikate zu erkennen und zu gruppieren. Führen Sie `python facet.py --sweep-dedup-thresholds [labels.json]` aus, um die Kosinus-Schranke zu bewerten — mit einer Labels-JSON gibt es eine Precision/Recall-Tabelle aus, andernfalls die Kandidaten-Kosinus-Verteilung und wie viele strikte pHash-Kollisionen die Schranke verwirft.

---

## Extended IQA tier (optional)

Schwere/experimentelle Qualitätsbewerter, **standardmäßig AUS** und **niemals ein Ersatz für TOPIQ** — sie fügen ergänzende Spalten nur hinzu, wenn sie ausdrücklich aktiviert werden. Wenn aktiviert, laufen die erweiterten Bewerter **während eines normalen Scans** und schreiben ihre eigenen Spalten; ein Lade-/VRAM-Fehler wird protokolliert und die Spalte bleibt `NULL` (der Scan bricht nie ab).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Einstellung | Standard | Zulässige Werte | Spalte | Beschreibung |
|---------|---------|-----------------|--------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | Q-Align LLM-basierte IQA (pyiqa-gestützt). `"4bit"` (~6–8GB VRAM) ist die praktische Wahl auf einer 16GB-Karte; `"8bit"` ~12–14GB; volle Präzision (`true`) braucht 16GB+. 4-/8-Bit benötigen `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (SigLIP-Head, ~2GB). Erfordert das Paket `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | DeQA-Score VLM IQA (16GB+ GPU; andernfalls übersprungen & NULL belassen). |

**Installieren Sie die optionalen Abhängigkeiten** für das, was Sie aktivieren: `pip install -e .[iqa-extended]` (fügt `aesthetic-predictor-v2-5` + `bitsandbytes` hinzu) oder kommentieren Sie die entsprechenden Zeilen in `requirements.txt` aus. Q-Align selbst wird mit `pyiqa` ausgeliefert; DeQA-Score wird über `transformers` heruntergeladen.

Wenn aktiviert, fließt jede Metrik in das gewichtete Aggregate ein, hat jedoch standardmäßig das Gewicht 0, sodass `--recompute-average` byte-identisch bleibt, bis Sie ihr ein Gewicht zuweisen. Führen Sie `python facet.py --eval-iqa-srcc` aus, um zu messen, wie gut jede Metrik Ihre Bibliothek gegenüber Ihren eigenen Sternebewertungen einordnet.

**Anzeige im Viewer.** Wenn eine dieser Spalten befüllt ist, zeigt der Viewer den Wert im **Quality**-Panel der Fotodetailansicht (`Q-Align`, `Aesthetic V2.5`, `DeQA`) und stellt einen passenden Bereichsregler in der Filter-Seitenleiste der Galerie unter **Extended Quality** bereit (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Fotos, die gescannt wurden, bevor das Tier aktiviert war, haben in diesen Spalten einfach `NULL` und sind von den Filtern unberührt.

**Robustheit.** DeQA-Score lädt remote `trust_remote_code`-Code, dessen Forward-Signatur über Checkpoint-Revisionen hinweg variiert; sein Bewerter ist defensiv — jeder Vorhersagefehler (falsche Signatur, unerwartete Ausgabeform, OOM) wird abgefangen und der `deqa_score` des Bildes bleibt `NULL`, statt den Scan abstürzen zu lassen.

---

## Face Detection

InsightFace-Einstellungen zur Gesichtserkennung.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Minimale Erkennungskonfidenz |
| `min_face_size` | `20` | Minimale Gesichtsgröße in Pixeln |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio für die Blinzelerkennung |
| `min_faces_for_group` | `4` | Mindestanzahl an Gesichtern für die Klassifizierung als Gruppenporträt (bei `--recompute-average` neu berechnet) |
| `enable_3d_landmarks` | `false` | Optionale Überschreibung (in der ausgelieferten Datei nicht vorhanden; Code-Standard `false`). Lädt das InsightFace-Modul `landmark_3d_68` für die Extraktion der Kopfhaltung (yaw/pitch/roll). Kostet ~5MB zusätzliche ONNX-Gewichte. Derzeit nur informativ; künftige Profil-/Silhouetten-Verfeinerungen werden dies auslesen. |
| `eyes_closed_max` | `4.0` | Augen-offen-Score pro Gesicht (0–10), bei oder unter dem die Culling-Dunkelkammer ein Gesicht als blinzelnd markiert. Steuert die roten/orangen/grünen Gesichtsringe und den Augen-Schwellenwert-Schieberegler (von einer fest codierten Konstante verschoben) |
| `poor_expression_min` | `4.0` | Lächel-/Ausdrucks-Score pro Gesicht (0–10), unter dem die Dunkelkammer einen schwachen Ausdruck markiert. Steuert den Ausdrucks-Gesichtsring und den Schieberegler (von einer fest codierten Konstante verschoben) |
| `blendshapes.enabled` | `true` | Verwendet erscheinungsbasierte MediaPipe-Blendshape-Scores für `eyes_open_score` / `smile_score` pro Gesicht, wenn MediaPipe und das `face_landmarker.task`-Bündel verfügbar sind; bei `true` ersetzen sie die Landmark-Geometrie-Scores, andernfalls läuft automatisch der Geometrie-Fallback. Optionale Abhängigkeit — installieren mit `pip install mediapipe==0.10.35 --no-deps` (niemals ein einfaches `pip install mediapipe`). Siehe [FACE_RECOGNITION.md](FACE_RECOGNITION.md#ausdruckssignale-pro-gesicht-augen-offen--lächeln). |
| `blendshapes.min_crop_size` | `192` | Gesichter, deren gepolsterter Ausschnitt kleiner als dieser Wert ist (px, kürzere Seite), fallen auf den geometrischen Score zurück, statt ein winziges Gesicht hochzuskalieren |

---

## Face Clustering

HDBSCAN-Clustering für die Gesichtserkennung.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6,
    "chunk_size": 10000
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Gesichts-Clustering aktivieren |
| `min_faces_per_person` | `2` | Mindestanzahl an Fotos pro Person |
| `min_samples` | `2` | HDBSCAN-Parameter min_samples |
| `auto_merge_distance_percent` | `15` | Automatisch zusammenführen innerhalb dieser Distanz |
| `clustering_algorithm` | `"best"` | HDBSCAN-Algorithmus |
| `leaf_size` | `40` | Blattgröße des Baums (nur CPU) |
| `use_gpu` | `"auto"` | GPU-Modus: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Zentroid-Ähnlichkeit für die Zuordnung |
| `chunk_size` | `10000` | Chunkgröße der Verarbeitung |

**Clustering-Algorithmen:**

| Algorithmus | Komplexität | Am besten für |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Hochdimensionale Daten (empfohlen) |
| `boruvka_kdtree` | O(n log n) | Niedrigdimensionale Daten |
| `prims_balltree` | O(n²) | Speicherbeschränkt, hochdimensional |
| `prims_kdtree` | O(n²) | Speicherbeschränkt, niedrigdimensional |
| `best` | Auto | HDBSCAN entscheiden lassen |

---

## Face Processing

Steuert die Gesichtsextraktion und die Thumbnail-Erzeugung.

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
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Randverhältnis für Gesichtsausschnitte |
| `use_db_thumbnails` | `true` | Gespeicherte Thumbnails verwenden |
| `face_thumbnail_size` | `640` | Thumbnail-Größe in Pixeln |
| `face_thumbnail_quality` | `90` | JPEG-Qualität |
| `extract_workers` | `2` | Parallele Extraktions-Worker |
| `extract_batch_size` | `16` | Batchgröße der Extraktion |
| `refill_workers` | `4` | Worker zum Nachfüllen von Thumbnails |
| `refill_batch_size` | `100` | Batchgröße des Nachfüllens |
| **auto_tuning** | | |
| `enabled` | `true` | Speicherbasiertes Tuning aktivieren |
| `memory_limit_percent` | `80` | Limit für die Speicherauslastung |
| `min_batch_size` | `8` | Minimale Batchgröße |
| `monitor_interval_seconds` | `5` | Prüfintervall |

---

## Monochrome Detection

Erkennung von Schwarzweißfotos.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Mittlere Sättigung < 5 % = monochrom |

---

## Tagging

Allgemeine Verschlagwortungseinstellungen. Das Verschlagwortungsmodell wird pro Profil in `models.profiles.*.tagging_model` konfiguriert.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Verschlagwortung aktivieren |
| `max_tags` | `5` | Maximale Anzahl Tags pro Foto |

**Hinweis:** CLIP-spezifische Einstellungen wie `similarity_threshold_percent` befinden sich im Abschnitt `models.clip`.

### Verfügbare Verschlagwortungsmodelle

Konfiguriert über `models.profiles.*.tagging_model`:

| Modell | VRAM | Tag-Stil | Anmerkungen |
|-------|------|-----------|-------|
| `clip` | 0 (verwendet Embeddings erneut) | Stimmung/Atmosphäre (dramatic, golden_hour, vintage) | Kein zusätzliches Modell zu laden; weniger wörtliche Objekterkennung |
| `qwen3.5-2b` | ~4GB | Strukturierte Szenen (landscape, architecture, reflection) | Erfordert transformers + zusätzlichen VRAM |
| `qwen3.5-4b` | ~8GB | Detaillierte Szenen mit Nuancen | Höherer VRAM-Bedarf; langsamere Inferenz |

### Standard-Verschlagwortungsmodelle pro Profil

| Profil | Verschlagwortungsmodell | Embedding-Modell |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Fotos neu verschlagworten

```bash
python facet.py --recompute-tags       # Neu verschlagworten mit dem pro Profil konfigurierten Modell
python facet.py --recompute-tags-vlm   # Neu verschlagworten mit dem VLM-Tagger
```

---

## Standalone Tags

Tags mit Synonymlisten, die an keine bestimmte Kategorie gebunden sind. Diese stehen für alle Fotos unabhängig von der Kategoriezuordnung zur Verfügung. Jeder Schlüssel ist der Tag-Name; der Wert ist eine Liste von Synonymen für die CLIP/VLM-Übereinstimmung.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Fügen Sie neue eigenständige Tags hinzu, indem Sie einen Schlüssel und eine Liste von Synonymen angeben. Hier definierte Tags werden mit den kategoriespezifischen Tags zusammengeführt, um das vollständige Tag-Vokabular zu bilden.

---

## Analysis

Schwellenwerte für `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Warnen, wenn die maximale Ästhetik darunter liegt |
| `aesthetic_target` | `9.5` | Zielwert für aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Qualitätsschwelle für „hohen Wert“ |
| `quality_weight_threshold_percent` | `10` | Warnen, wenn das Qualitätsgewicht ≤ diesem Wert ist |
| `correlation_dominant_threshold` | `0.5` | Warnung „dominantes Signal“ |
| `category_min_samples` | `50` | Mindestanzahl an Fotos pro Kategorie |
| `category_imbalance_threshold` | `0.5` | Warnung bei Bewertungsabstand |
| `score_clustering_std_threshold` | `1.0` | Warnen, wenn die Standardabweichung < diesem Wert ist |
| `top_score_threshold` | `8.5` | Warnen, wenn das maximale Aggregate < diesem Wert ist |
| `exposure_avg_threshold` | `8.0` | Warnen, wenn die durchschnittliche Belichtung > diesem Wert ist |

---

## Viewer

Anzeige und Verhalten der Web-Galerie.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "tooltip_mode": "hover",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 60,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Hinweis:** `sort_options` (oben als `{ ... }` ausgelassen) ordnet DB-Spalten Dropdown-Bezeichnungen zu und wird selten bearbeitet. Die **Content**-Gruppe enthält eine Sortierung `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (NULL-Werte werden zuletzt einsortiert).

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_category` | `""` | Standard-Kategoriefilter |
| `edition_password` | `""` | Passwort zum Freischalten des Editionsmodus (leer = deaktiviert) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Minimum für die Optimierung |
| `pair_selection_strategy` | `"learning"` | Paarstrategie: `learning` (Embedding-Diversität für den Kaltstart + Rang-Uneinigkeit nach dem Training), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Zufälliger Kandidatenpool, innerhalb dessen die `learning`-Strategie Paare zieht |
| `show_current_scores` | `true` | Bewertungen während des Vergleichs anzeigen |
| **pagination** | | |
| `default_per_page` | `64` | Fotos pro Seite |
| **dropdowns** | | |
| `max_cameras` | `50` | Maximale Anzahl Kameras im Dropdown |
| `max_lenses` | `50` | Maximale Anzahl Objektive |
| `max_persons` | `50` | Maximale Anzahl Personen |
| `max_tags` | `20` | Maximale Anzahl Tags |
| `min_photos_for_person` | `10` | Personen mit weniger Fotos im Dropdown ausblenden |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Minimale face_count, damit ein automatisch geclustertes Cluster im Abschnitt „Needs naming“ von `/persons` erscheint |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Name oder absoluter Pfad der darktable-cli-Binärdatei |
| `darktable.profiles` | `[]` | Array benannter darktable-Exportprofile (siehe unten) |
| `darktable.profiles[].name` | *(erforderlich)* | Anzeigename des Profils (verwendet im Download-Menü und im API-Parameter `profile`) |
| `darktable.profiles[].hq` | `true` | Übergibt `--hq true` für hochwertigen Export |
| `darktable.profiles[].width` | *(weglassen)* | Maximale Ausgabebreite (für volle Auflösung weglassen) |
| `darktable.profiles[].height` | *(weglassen)* | Maximale Ausgabehöhe (für volle Auflösung weglassen) |
| `darktable.profiles[].style` | *(weglassen)* | Name des darktable-Stils, der beim Export angewendet wird (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Bei `false` wird `--apply-custom-presets false` übergeben, sodass nur der explizite `style` gerendert wird (keine automatisch angewandten Presets) |
| `darktable.profiles[].extra_args` | `[]` | Zusätzliche CLI-Argumente (z. B. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Benannte darktable-Stile, die im Aussortier-Studio als bearbeitete Vorschau angeboten werden (`GET /api/photo/cull_preview`). Leer = die Stilauswahl ist ausgeblendet. Jeder Stil **muss bereits** in der darktable-Konfiguration des Viewer-Benutzers vorhanden sein. Der Name wird unverändert an `--style` übergeben. |
| `darktable.cull_styles[].name` | *(erforderlich)* | darktable-Stilname (an `--style` übergeben und vom Endpoint validiert) |
| `darktable.cull_styles[].label_key` | *(name)* | Optionaler i18n-Schlüssel für die Menübeschriftung (Standard: der Stilname) |
| `darktable.preview_max_edge` | `1440` | Maximale Kantenlänge (px) der Aussortier-Vorschau |
| `darktable.preview_timeout_seconds` | `60` | darktable-cli-Zeitlimit pro Vorschau-Render |
| **display** | | |
| `tags_per_photo` | `4` | Auf Karten angezeigte Tags |
| `card_width_px` | `168` | Kartenbreite |
| `image_width_px` | `160` | Bildbreite |
| `image_jpeg_quality` | `96` | JPEG-Qualität für die RAW/HEIF-Konvertierung in `/api/download` und `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Minimale Thumbnail-Größe (px) |
| `thumbnail_slider.max_px` | `400` | Maximale Thumbnail-Größe (px) |
| `thumbnail_slider.default_px` | `168` | Standard-Thumbnail-Größe (px) |
| `thumbnail_slider.step_px` | `8` | Schrittweite des Reglers (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Thumbnail-Größe |
| `jpeg_quality` | `80` | JPEG-Qualität |
| `crop_padding_ratio` | `0.2` | Gesichtsrand |
| `min_crop_size_px` | `20` | Minimale Ausschnittgröße |
| **quality_thresholds** | | |
| `good` | `6` | Schwelle „Gut“ |
| `great` | `7` | Schwelle „Sehr gut“ |
| `excellent` | `8` | Schwelle „Ausgezeichnet“ |
| `best` | `9` | Schwelle „Beste“ |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimum für Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Gesichtsanteil für die Gewichtung |
| `low_light_max_luminance` | `0.2` | Schwelle für wenig Licht |
| **defaults** | | |
| `type` | `""` | Standard-Fototypfilter (z. B. `"portraits"`, `"landscapes"` oder `""` für Alle) |
| `sort` | `"aggregate"` | Standard-Sortierspalte |
| `sort_direction` | `"DESC"` | Standard-Sortierrichtung (`"ASC"` oder `"DESC"`) |
| `hide_blinks` | `true` | Blinzelfotos standardmäßig ausblenden |
| `hide_bursts` | `true` | Standardmäßig nur das beste Serienbild anzeigen |
| `hide_duplicates` | `true` | Nicht führende Duplikatfotos standardmäßig ausblenden |
| `hide_details` | `true` | Fotodetails auf Karten standardmäßig ausblenden |
| `tooltip_mode` | `"hover"` | Tooltip-Auslöser: `"hover"`, `"click"` oder `"off"`. Ersetzt das frühere boolesche `hide_tooltip`. |
| `hide_rejected` | `true` | Abgelehnte Fotos standardmäßig ausblenden |
| `gallery_mode` | `"mosaic"` | Standard-Galerie-Layout (`"grid"` oder `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Per CORS erlaubte Origins für den FastAPI-Server. Fügen Sie beim Remote-Hosting Ihre Domain oder Reverse-Proxy-URL hinzu. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(SPA-sicherer Standard)_ | Wert des Content-Security-Policy-Headers. Standardmäßig eine Policy, die die eigenen Ressourcen der SPA erlaubt (Inline-Theme-Skript/-Stil, Google Fonts, OpenStreetMap-Kacheln, Same-Origin-API). Auf `""` setzen zum Deaktivieren oder eine strengere Policy angeben. |
| `security_headers.hsts` | `false` | `Strict-Transport-Security` senden. Nur aktivieren, wenn der Viewer über HTTPS ausgeliefert wird. |
| **Sonstiges** | | |
| `cache_ttl_seconds` | `60` | TTL des Abfrage-Caches |
| `notification_duration_ms` | `2000` | Dauer der Toast-Benachrichtigung |
| `moment_confidence_min` | `0` | Unterhalb dieser gespeicherten `narrative_moment_confidence`-Posteriori (0–1) werden Moment-Labels abgeblendet und mit dem Suffix „(uncertain)“ im Szenen-Header, im Culling-Szenengruppen-Header und im Galerie-Foto-Tooltip dargestellt. `0` = nie abblenden |

### Features

Schalten Sie optionale Features um, um den Speicherverbrauch zu senken oder die UI zu vereinfachen:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_rating_badge": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `show_similar_button` | `true` | Schaltfläche „Find Similar“ auf Fotokarten anzeigen (nutzt numpy für CLIP-Ähnlichkeit) |
| `show_merge_suggestions` | `true` | Funktion für Zusammenführungsvorschläge auf der Personenverwaltungsseite aktivieren |
| `show_rating_controls` | `true` | Steuerelemente für Sternebewertung und Favorit anzeigen |
| `show_rating_badge` | `true` | Bewertungs-Badge auf Fotokarten anzeigen |
| `show_scan_button` | `false` | Scan-Auslöser-Schaltfläche für Superadmin-Benutzer anzeigen (erfordert GPU auf dem Viewer-Host) |
| `metrics_enabled` | `false` | Den öffentlichen Prometheus-Endpunkt `GET /metrics` aktivieren. Standardmäßig aus — er legt Foto-/Personen-/Gesichtszählungen, DB-Größe und Prozessspeicher offen; nur aktivieren, wenn der Endpunkt aus dem Scraper-Netz erreichbar ist, nicht aus dem öffentlichen Internet. |
| `show_semantic_search` | `true` | Semantische Suchleiste anzeigen (Text-zu-Bild-Suche mit CLIP/SigLIP-Embeddings) |
| `show_albums` | `true` | Album-Funktion anzeigen (Fotoalben erstellen, verwalten und durchsuchen) |
| `show_critique` | `true` | Schaltfläche für KI-Kritik auf Fotokarten anzeigen (regelbasierte Bewertungsaufschlüsselung) |
| `show_vlm_critique` | `true` | VLM-gestützten Kritikmodus aktivieren (erfordert VRAM-Profil 16gb/24gb). Der Code fällt auf `false` zurück, wenn der Schlüssel fehlt. |
| `show_embed_metadata` | `true` | Die Pro-Thumbnail-Aktion „Write metadata to file“ im Editionsmodus anzeigen (bettet Bewertungen/Schlüsselwörter über exiftool in das Originalbild ein) |
| `show_memories` | `true` | Dialog „On This Day“-Erinnerungen anzeigen (Fotos, die am selben Datum in früheren Jahren aufgenommen wurden) |
| `show_captions` | `true` | KI-generierte Bildunterschriften auf Fotokarten anzeigen |
| `show_timeline` | `true` | Timeline-Ansicht für chronologisches Durchsuchen mit Datumsnavigation anzeigen |
| `show_map` | `true` | Kartenansicht mit GPS-basierten Fotopositionen anzeigen (erfordert Leaflet). Der Code fällt auf `false` zurück, wenn der Schlüssel fehlt. |
| `show_capsules` | `true` | Die Capsules-Ansicht anzeigen (kuratierte Foto-Diaschauen nach Thema gruppiert) |
| `show_folders` | `true` | Ordnerbasiertes Durchsuchen der Fotoverzeichnisstruktur anzeigen |
| `show_scenes` | `true` | Die Szenen-Ansicht (`/scenes`) anzeigen, die führende Serienbildfotos in chronologische Szenen für ein Culling in Erzählreihenfolge gruppiert |
| `show_my_taste` | `true` | Die Sortierung „My Taste“ anzeigen, gestützt auf den gelernten Score des persönlichen Rankers, mit einem Konfidenz-Badge für gelernte Abdeckung / Genauigkeit |
| `show_social_export` | `true` | Zeigt das editionsbeschränkte Menü **Social-Zuschnitt** (motivbewusste Zuschnitte für Social-Seitenverhältnisse). Siehe [Social-Export](#social-export) |
| `show_portfolio_export` | `true` | Zeigt die editionsbeschränkte Album-Aktion **Portfolio exportieren** (eigenständige statische HTML-Galerie). Siehe [Portfolio-Export](#portfolio-export) |
| `show_proofing` | `false` | Client-Proofing für geteilte Alben aktivieren: Ein Freigabelink (plus optionale PIN) erlaubt einem kontolosen Client, Fotos mit einem Herz zu markieren und Kommentare zu hinterlassen, die der Albumbesitzer aus einem editionsbeschränkten Dialog überprüft. Standardmäßig aus. Siehe [Client-Proofing](#client-proofing) |

**Speicheroptimierung:** Wenn `show_similar_button: false` gesetzt wird, verhindert dies, dass numpy geladen wird, und reduziert so den Speicherbedarf des Viewers. Die Funktion für ähnliche Fotos berechnet die Kosinusähnlichkeit der CLIP-Embeddings, was numpy erfordert.

### Client-Proofing

`viewer.features.show_proofing` (Standard `false`) verwandelt jedes geteilte Album in eine Client-Proofing-Oberfläche. Ein Freigabelink — optional durch `viewer.proofing.pin` abgesichert — erlaubt einem Client ohne Konto, das Freigabe-Token gegen eine kurzlebige Sitzung einzutauschen und dann Fotos mit einem Herz zu markieren und Kommentare zu hinterlassen. Die Auswahlen liegen in einer eigenen `album_client_picks`-Tabelle, sind auf die Fotos dieses Albums beschränkt und vollständig von den Bewertungen des Besitzers isoliert (sie berühren nie `photos.is_favorite` / `user_preferences` und trainieren nie den persönlichen Ranker). Der Besitzer liest die Auswahlen aus einem editionsbeschränkten Dialog auf der Albumkarte.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `features.show_proofing` | `false` | Hauptschalter für Client-Proofing auf geteilten Alben |
| `proofing.pin` | `""` | Optionale PIN, die ein Client (zusammen mit dem Freigabe-Token) eingeben muss, um eine Proofing-Sitzung zu öffnen. Leer = keine PIN. Prüfungen sind ratenbegrenzt und byte-sicher |
| `proofing.session_minutes` | `1440` | Lebensdauer in Minuten eines Client-Proofing-Sitzungstokens (Standard 24 h). Sitzungen enden außerdem in dem Moment, in dem die Albumfreigabe aufgehoben oder Proofing deaktiviert wird |

### Path Mapping

Bildet Datenbankpfade auf lokale Dateisystempfade ab. Nützlich, wenn Fotos auf einem Rechner bewertet wurden (z. B. Windows mit UNC-Pfaden), der Viewer aber auf einem anderen läuft (z. B. Linux-NAS mit Mountpoints).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `path_mapping` | `{}` | Dict aus Quellpräfix zu Zielpräfix. Beim Ausliefern von Bildern in voller Größe oder von VLM-Kritik werden Datenbankpfade, die mit einem Quellpräfix beginnen, so umgeschrieben, dass sie das Zielpräfix verwenden. |

**Funktionsweise:**
- Gilt nur beim **Lesen von Dateien von der Festplatte** (Ausliefern von Bildern in voller Größe, Datei-Downloads, VLM-Kritik). Datenbankpfade werden nie verändert.
- Die Normalisierung von Backslash/Forward-Slash erfolgt automatisch: `\\NAS\Photos\img.jpg` und `//NAS/Photos/img.jpg` passen beide.
- Zuordnungen werden in Reihenfolge ausgewertet; das erste passende Präfix gewinnt.
- Path-Mapping-Ziele werden für die Sicherheitsprüfungen im Mehrbenutzermodus automatisch in die Allowlist der Scan-Verzeichnisse aufgenommen.

**Beispiel:** Eine unter Windows befüllte Datenbank speichert Pfade wie `\\NAS\Photos\2024\IMG_001.jpg`. Unter Linux ist derselbe Share unter `/mnt/nas/Photos` eingebunden. Konfigurieren Sie:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Passwortschutz

Optionaler Passwortschutz für den Viewer:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Wenn gesetzt, müssen sich Benutzer authentifizieren, bevor sie auf den Viewer zugreifen können.

### Viewer-Performance

Überschreibt die globalen `performance`-Einstellungen beim Betrieb des Viewers. Nützlich für speicherarme NAS-Deployments, bei denen die Bewertung viele Ressourcen benötigt, der Viewer jedoch nicht.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Überschreibung der SQLite-mmap-Größe für Viewer-Verbindungen. `0` deaktiviert mmap. |
| `cache_size_mb` | *(global)* | Überschreibung der SQLite-Cache-Größe für Viewer-Verbindungen |
| `pool_size` | `5` | Größe des Verbindungspools (für speicherarme Systeme reduzieren) |
| `thumbnail_cache_size` | `2000` | Maximale Einträge im In-Memory-Cache für die Thumbnail-Skalierung |
| `face_cache_size` | `500` | Maximale Einträge im In-Memory-Cache für Gesichts-Thumbnails |

Wenn nicht gesetzt, verwendet der Viewer die globalen `performance`-Werte. Siehe [Deployment](DEPLOYMENT.md) für empfohlene NAS-Einstellungen.

---

## Performance

Performance-Einstellungen der Datenbank.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

> **Hinweis:** `wal_checkpoint_minutes` ist eine optionale Überschreibung und **nicht** im ausgelieferten `performance`-Block enthalten (der nur `mmap_size_mb`, `cache_size_mb` und `slow_request_ms` enthält). Fügen Sie ihn explizit hinzu, um den Standardwert von `30` zu ändern.

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Größe des speicher-gemappten I/O von SQLite |
| `cache_size_mb` | `128` | SQLite-Cache-Größe |
| `wal_checkpoint_minutes` | `30` | Optionale Überschreibung (in der ausgelieferten Datei nicht vorhanden). Intervall in Minuten für das Hintergrund-`PRAGMA wal_checkpoint(TRUNCATE)` des Viewers. Verhindert WAL-Aufblähung bei langlaufenden Deployments. Auf `0` setzen zum Deaktivieren. |
| `slow_request_ms` | `1000` | Viewer-API-Anfragen, die langsamer als diese Anzahl Millisekunden sind, werden auf WARNING mit einem `SLOW`-Marker protokolliert. Auf `0` setzen zum Deaktivieren. |

---

## Storage

Steuert, wo Thumbnails und Embeddings gespeichert werden. Standard sind BLOB-Spalten in der SQLite-Datenbank; der Filesystem-Modus speichert sie stattdessen als Dateien auf der Festplatte, was die Datenbankgröße reduziert.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mode` | `"database"` | Speicher-Backend: `"database"` (SQLite-BLOBs) oder `"filesystem"` (Dateien auf der Festplatte) |
| `filesystem_path` | `"./storage"` | Basisverzeichnis für den Filesystem-Modus. Thumbnails werden in `<path>/thumbnails/` und Embeddings in `<path>/embeddings/` gespeichert, organisiert in Unterverzeichnisse nach Content-Hash. |

**Details zum Filesystem-Modus:**
- Dateien werden nach dem SHA-256-Hash des Fotopfads organisiert, mit zweistelligen Unterverzeichnissen, um zu viele Dateien in einem Verzeichnis zu vermeiden (z. B. `thumbnails/a3/a3f8..._640.jpg`).
- Das Löschen eines Fotos entfernt alle zugehörigen Thumbnail-Größen und Embedding-Dateien.
- Das Verzeichnis wird bei der ersten Verwendung automatisch erstellt.

---

## Plugins

Ereignisgesteuertes Plugin-System zum Reagieren auf Bewertungsereignisse. Plugins können Python-Module, Webhooks oder integrierte Aktionen sein.

### Konfiguration

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Schlüssel | Standard | Beschreibung |
|-----|---------|-------------|
| `enabled` | `false` | Hauptschalter — wenn false, werden keine Ereignisse ausgelöst |
| `high_score_threshold` | `8.0` | Minimale Gesamtbewertung, um `on_high_score`-Ereignisse auszulösen |
| `webhooks` | `[]` | Liste von Webhook-Endpunkten, die JSON-POST-Payloads empfangen |
| `actions` | `{}` | Benannte integrierte Aktionen, die durch Ereignisse ausgelöst werden |

### Unterstützte Ereignisse

| Ereignis | Auslöser | Payload |
|-------|---------|---------|
| `on_score_complete` | Nachdem jedes Foto bewertet wurde | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Wenn ein Foto in die Datenbank aufgenommen wird | Wie `on_score_complete` |
| `on_high_score` | Wenn aggregate ≥ `high_score_threshold` | Wie `on_score_complete` |
| `on_burst_detected` | Wenn eine Serienbildgruppe erkannt wird | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Ein Plugin schreiben

Legen Sie eine `.py`-Datei im Verzeichnis `plugins/` ab. Definieren Sie Funktionen, die nach den Ereignissen benannt sind, die Sie behandeln möchten:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Siehe `plugins/example_plugin.py.example` für die vollständige Schnittstelle.

### Webhooks

Jeder Webhook erhält einen JSON-POST mit SSRF-Schutz (private/Loopback-Adressen werden blockiert):

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Webhook-Optionen: `url` (erforderlich), `events` (Liste von Ereignisnamen), `min_score` (minimale Gesamtbewertung zum Auslösen).

### Integrierte Aktionen

| Aktion | Beschreibung | Optionen |
|--------|-------------|---------|
| `copy_to_folder` | Foto in einen Ordner kopieren | `folder`, `min_score` |
| `send_notification` | Eine Benachrichtigung protokollieren | `min_score` |

### API-Endpunkte

| Methode | Pfad | Beschreibung |
|--------|------|-------------|
| `GET` | `/api/plugins` | Geladene Plugins, Webhooks und Aktionen auflisten |
| `POST` | `/api/plugins/test-webhook` | Eine Test-Payload an eine Webhook-URL senden |

---

## Capsules

Kuratierte Foto-Diaschauen (Slideshows), nach Thema gruppiert. Capsules werden automatisch aus Ihrer Fotobibliothek generiert und mit einer konfigurierbaren TTL zwischengespeichert.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Globale Einstellungen

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Minimale Gesamtbewertung, damit Fotos in Capsules aufgenommen werden |
| `max_photos_per_capsule` | `40` | Maximale Anzahl Fotos pro Capsule (MMR-Diversität wird ab 5 angewendet) |
| `max_photo_overlap` | `0.2` | Maximaler Anteil gemeinsamer Fotos zwischen zwei Capsules, bevor die Deduplizierung eine entfernt |
| `mmr_lambda` | `0.5` | MMR-Diversitätsgewicht: 0 = Diversität maximieren, 1 = Qualität maximieren |
| `mmr_moment_weight` | `0.0` | Optionales Gewicht, das die `narrative_moment_confidence` jedes Fotos in die MMR-Auswahl der Capsules einfließen lässt. `0.0` = unverändertes Verhalten |
| `freshness_hours` | `24` | Cache-TTL und Rotationsperiode für Titelbilder und Seeded-Capsules |
| `reverse_geocoding` | `true` | Offline-Reverse-Geocoding für Titel von Location-/Journey-Capsules aktivieren (erfordert das Paket `reverse_geocoder`) |

### Capsule-Typen

| Typ | Beschreibung |
|------|-------------|
| `journey` | Reisen, erkannt über GPS-Clustering + zeitliche Lücken. Titel enthalten den Zielnamen, wenn Geocoding aktiviert ist. |
| `faces_of` | Beste Fotos jeder erkannten Person |
| `seasonal` | Fotos gruppiert nach Jahreszeit + Jahr |
| `golden` | Top 1 % nach Gesamtbewertung |
| `color_story` | Visuell ähnliche Gruppen über CLIP-Embedding-Clustering |
| `this_week` | „This Week, Years Ago“ — erweitertes „On This Day“ über ±3 Tage |
| `location` | Geotagged-Fotocluster mit reverse-geocodierten Ortsnamen |
| `person_pair` | Paare benannter Personen, die zusammen erscheinen |
| `seeded` | Seed-basierte Entdeckung über Zeit, Ähnlichkeit, Person, Tag, Ort, Stimmung |
| `progress` | „Your Photography is Improving“ aus vierteljährlichen Bewertungstrends |
| `color_palette` | „Color of the Month“ aus Sättigungs-/Monochrom-Profilen |
| `rare_pair` | Seltene Personenpaare in hoch bewerteten Fotos |
| `favorites` | Favorisierte Fotos gruppiert nach Jahr und Jahreszeit |

### Dimensionsbasierte Capsules

Automatisch aus Datenbankspalten generiert:

| Dimension | Gruppiert nach |
|-----------|-----------|
| `year` | Aus date_taken extrahiertes Jahr |
| `month` | Aus date_taken extrahiertes Jahr-Monat |
| `week` | Aus date_taken extrahierte Jahr-Woche |
| `camera` | Kameramodell |
| `lens` | Objektivmodell |
| `tag` | Foto-Tags (erfordert die Tabelle `photo_tags`) |
| `day_of_week` | Wochentag (Sonntag–Samstag) |
| `composition` | SAMP-Net-Kompositionsmuster (rule_of_thirds, horizontal usw.) |
| `focal_range` | Brennweiten-Klassen: Ultraweitwinkel (<24mm), Weitwinkel (24–35mm), Standard (36–70mm), Porträt (71–135mm), Tele (136–300mm), Supertele (300mm+) |
| `category` | Inhaltskategorie des Fotos (portrait, landscape, street usw.) |
| `time_of_day` | Zeit-Klassen: goldener Morgen, Morgen, Mittag, Nachmittag, goldener Abend, Nacht |
| `star_rating` | Sternebewertungen der Benutzer (1–5 Sterne) |

Es werden auch dimensionsübergreifende Kombinationen generiert (z. B. camera × year, focal_range × category, category × year).

### Slideshow-Übergänge

Jeder Capsule-Typ wird auf einen thematischen Folienübergang abgebildet:

| Übergang | Verwendet von | Effekt |
|-----------|---------|--------|
| `crossfade` | Standard | 300ms Deckkraft-Wechsel |
| `slide` | journey, location, this_week | Von rechts hereingleiten (500ms) |
| `zoom` | faces_of, color_story | Skalierung 1.05→1.0 mit Überblendung (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Langsamer Zoom 1.0→1.08 über die Foliendauer |

### Reverse Geocoding

Location- und Journey-Capsules verwenden Offline-Reverse-Geocoding über das Paket `reverse_geocoder` (lokaler GeoNames-Datensatz, ~30MB, keine API-Aufrufe). Ergebnisse werden in der Datenbanktabelle `location_names` bei einer Rasterauflösung von 0,1° (~11km) zwischengespeichert.

Installation: `pip install reverse_geocoder`

Setzen Sie `"reverse_geocoding": false`, um es zu deaktivieren und auf die Koordinatenanzeige zurückzufallen.

## Similarity Groups

Einstellungen für die KI-Funktion zum Culling ähnlicher Fotos, die visuell ähnliche Fotos mithilfe von CLIP/SigLIP-Embeddings gruppiert:

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Minimale Kosinusähnlichkeit (0,0–1,0), um zwei Fotos als visuell ähnlich zu betrachten. Niedrigere Werte erzeugen größere Gruppen, aber mit geringerer visueller Ähnlichkeit. |
| `min_group_size` | `2` | Minimale Anzahl an Fotos, um eine Ähnlichkeitsgruppe zu bilden |
| `max_photos` | `10000` | Maximale Anzahl an Fotos, die für die Ähnlichkeitsberechnung geladen werden (O(n²)-Kosten). Für größere Bibliotheken auf Kosten der Rechenzeit erhöhen. |
| `max_group_size` | `50` | Maximale Anzahl an Fotos pro Ähnlichkeitsgruppe. Größere Gruppen werden aufgeteilt, um die UI nutzbar zu halten. |

## Auto-Cull

Ein-Knopf-Auto-Cull für die Culling-Dunkelkammer (`POST /api/culling/auto`, editionsbeschränkt). Es culled einen ganzen Bereich — alle Gruppen oder nur Serienbilder / Ähnliche / Szenen, optional auf ein Album oder ein Datumsfenster eingegrenzt — in einem einzigen Durchgang. Jede Gruppe behält ihr bestes Foto plus alles innerhalb einer aus der Strenge abgeleiteten Marge (dasselbe Behalte-Budget wie der Schieberegler der manuellen Dunkelkammer), begrenzt durch ein Minimum pro Gruppe, und lehnt den Rest ab.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_strictness` | `50` | Behalte-Budget (0–100), das verwendet wird, wenn die Anfrage `strictness` auslässt. Höher = weniger Fotos pro Gruppe behalten (engere Marge um das beste Foto der Gruppe) |
| `highlights_min` | `8.0` | Minimaler aggregierter Score für das beste Foto einer Gruppe, damit es beim Anwenden eines Auto-Culls in das optionale **Highlights**-Album aufgenommen wird (idempotent) |

`dry_run` ist standardmäßig aktiv und liefert eine Behalte-/Ablehnen-Vorschau pro Gruppe; ein Anwenden zeichnet zusätzlich `source='culling'`-Vergleichszeilen auf und stößt ein automatisches Nachtrainieren an. Siehe [Web-Viewer — Auto-Cull](VIEWER.md#auto-cull).

## Genre-spezifische Aussortier-Profile

Genre-Vorlagen, die alle Aussortier-Regler in einem Klick bündeln: Sport behält nur das schärfste Bild einer langen Serie, Hochzeiten behalten mehr Varianten mit Priorität auf offenen Augen, Konzerte lockern die Augen-/Ausdruck-Schwellen, Tierwelt entfernt den menschlichen Gesichtsfilter ganz. Die Aussortier-Dunkelkammer zeigt eine Vorlagenauswahl.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Einstellung | Beschreibung |
|---|---|
| `default` | Profil-ID, wenn clientseitig keine gespeichert ist |
| `profiles.<id>.label_key` | i18n-Pfad für den Anzeigenamen der Vorlage (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Behalte-Budget (0–100), das in die Auto-Aussortier-Marge einfließt, wenn diese Vorlage aktiv ist |
| `profiles.<id>.eyes_closed_max` | Augen-offen-Wert (0–10), ab dem ein Gesicht als geschlossen gilt — überschreibt `face_detection.eyes_closed_max` in den Gesichts-Badges |
| `profiles.<id>.poor_expression_min` | Ausdrucks-/Lächeln-Wert (0–10), unter dem ein Gesicht als schlecht gilt — überschreibt `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | Untergrenze pro Gruppe für die Behalte-Menge der Auto-Aussortierung |
| `profiles.<id>.similarity_threshold` | Ähnlichkeits-Gruppierungsschwelle (Prozent), die bei aktiver Vorlage angewandt wird |

Endpunkt (schreibgeschützt): `GET /api/culling/profiles` liefert die geordnete Vorlagenliste und den Standard. Die Auto-Aussortier-Anfrage (`POST /api/culling/auto`) und der Gesichts-Batch (`POST /api/culling-group/faces`) akzeptieren ein optionales `profile`; ein explizites `strictness`/`min_keep_per_group` in der Anfrage hat immer Vorrang vor der Vorlage.

## Scenes

Einstellungen für die Szenen-Ansicht, die führende Serienbildfotos in chronologische Szenen gruppiert (aufgeteilt nach Aufnahmezeit-Lücken) für ein Culling in Erzählreihenfolge:

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Eine neue Szene beginnt, wenn zwischen aufeinanderfolgenden führenden Serienbildfotos mehr als so viele Minuten vergehen (die Untergrenze, wenn `adaptive` aktiv ist) |
| `min_size` | `2` | Mindestanzahl an Fotos, damit eine Szene angezeigt wird |
| `max_photos` | `5000` | Maximale Anzahl führender Serienbildfotos, die für die Szenengruppierung geladen werden |
| `max_scene_size` | `60` | Eine Szene, die größer als dies ist, wird rekursiv an ihren größten internen Lücken weiter aufgeteilt, sodass ein durchgehend fotografiertes Ereignis nie zu einer einzigen riesigen Szene zusammenfällt |
| `adaptive` | `true` | Wenn aktiv, weitet sich die effektive Lücke auf `adaptive_k × Median` der aufeinanderfolgenden Lücken der Aufnahme (enger bei schnellem Fotografieren, lockerer bei spärlichen Urlauben) |
| `adaptive_k` | `6.0` | Multiplikator, der auf die Median-Lücke angewendet wird, wenn `adaptive` aktiv ist |
| `split_on_moment_change` | `false` | Wenn aktiv (und narrative Momente berechnet werden), wird ein Zeitabschnitt weiter aufgeteilt, in dem sich der dominante Moment ändert und für `moment_split_min_run` Frames hält |
| `moment_split_min_run` | `4` | Hysterese für `split_on_moment_change` — wie viele aufeinanderfolgende Frames ein neuer Moment bestehen muss, um eine Grenze zu erzwingen |

## Narrative Moments

Zero-Shot-Labelling des Szenen-/Aktivitäts-„Moments” jedes Fotos. Das standardmäßige **general**-Vokabular umfasst `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` oder `other` — sodass es mit jeder Bibliothek funktioniert, nicht nur mit Hochzeiten (`wedding` wird als optionales Genre mitgeliefert). Befüllt durch `--detect-moments` (läuft automatisch am Ende jedes Scans) und als Szenennamen sowie als Galeriefilter dargestellt. Etwas, das weder Narrative Select noch AfterShoot bieten.

Das Signal ist **caption-semantisch**: Die KI-Bildunterschrift jedes Fotos wird einmal mit dem Text-Tower kodiert und gespeichert (Spalte `caption_embedding`); der Moment ist der beste **max-gepoolte** (max-pooled) Kosinus dieses Bildunterschrift-Embeddings gegenüber den Text-Prompts pro Moment. Das gespeicherte Bild-Embedding dient als Rückfalloption, wenn ein Foto keine Bildunterschrift hat. Bildunterschriftstext passt ~2,4× sauberer zu den Moment-Prompts als das rohe Bild-Embedding, weshalb das `caption`-Signal höhere Schwellen trägt als die `image`-Rückfalloption; beide werden pro Backend abgestimmt (open_clip-Kosinuswerte fallen deutlich niedriger aus als die von SigLIP). Die `transformers`-Werte (SigLIP) werden als konservative Standardwerte ausgeliefert — stimmen Sie sie neu ab, wenn Sie ein SigLIP-Profil verwenden.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": { "enabled": true, "weight": 0.04 },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Hauptschalter; wenn aus, sind `--detect-moments` und der Scan-Hook ein No-op |
| `prompt_template` | `"a photo of {desc}"` | Wrapper, der vor dem Encoding auf jeden Prompt angewendet wird |
| `default_event_type` | `"general"` | Welches `event_types`-Vokabular aktiv ist. `general` = 20 agnostische Szenen-/Aktivitäts-Momente; `wedding` wird als optionales Genre mitgeliefert |
| `pooling` | `"max"` | Score pro Moment = der einzelne beste Prompt-Kosinus (max-pool), trennschärfer als Mittelung |
| `caption_min_confidence` | `0` | Qualitätsgate für Bildunterschriften: wenn > 0, überspringen `--generate-captions` und der On-Demand-Bildunterschriften-Endpunkt Fotos, die ungelabelt, `other` oder unterhalb dieser gespeicherten Moment-Konfidenz sind. `0` = kein Gate |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Liegt der Top-1-Kosinus darunter, wird ein Foto als `other` gelabelt. Aufgeschlüsselt nach **Signal** (`caption` vs. `image`), dann nach Backend — caption-Kosinuswerte fallen ~2,4× höher aus |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Minimaler Kosinusabstand zwischen Top-1 und Top-2; darunter ist der Frame `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | L1-Anstöße aus Gesicht/Tag, die nur knappe Gleichstände auflösen; `weight` begrenzt jeden Boost auf Kosinus-Skala |
| `priors.caption_tag_scale` | `0.25` | Dämpft `tag`-Regeln beim Caption-Signal (L0 kodiert die Bildunterschrift bereits); strukturelle Regeln behalten ihr volles Gewicht |
| `priors.rules` / `priors.event_types.<et>.rules` | (allgemeines Set) | Deklarative `{kind, when, boost}`-Regeln, vokabularunabhängig; ein `boost` auf ein im aktiven Vokabular fehlendes Moment wird stillschweigend übersprungen. Pro-`event_type`-Regeln ersetzen die globale Liste. Vollständige Prädikat-Referenz: englische Doku |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | L2-Timeline-Glättung (Viterbi): bleibe-lastig ohne Vorwärtsprogression (das agnostische Vokabular hat keine kanonische Reihenfolge), nur leicht angewendet (`weight=0` = keine Glättung) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | L3-Tie-Break (jetzt aktiv): wenn auf 16gb/24gb-Profilen aktiviert, werden nur Frames mit geringer Posteriori (unter `min_confidence`) oder geringem Abstand (unter `min_margin`) während `--detect-moments` / `--recompute-moments` vom Profil-VLM neu klassifiziert |
| `event_types` | `general` + `wedding` | Pro Ereignistyp `{moment: [Prompt-Synonyme]}`; setzen Sie `default_event_type`, um das Genre zu wechseln, oder fügen Sie Ihr eigenes hinzu |

> **Kosten des Caption-Backfills.** Bildunterschrift-Embeddings werden einmal berechnet und gespeichert, sodass der Kosinus pro Foto danach kostenlos ist. Ein Scan kodiert nur seine wenigen neuen Bildunterschriften (günstig, inkrementell), aber der erste vollständige Durchlauf über eine bestehende Bibliothek kodiert jede Bildunterschrift — ein Text-Tower-Vorwärtsdurchlauf pro Bildunterschrift, schnell auf GPU und ~Stunden auf CPU. Führen Sie `python facet.py --detect-moments` einmal aus (GPU empfohlen) für diesen Backfill; fügen Sie `--limit N` hinzu, um es zuerst an einer Stichprobe zu prüfen.

**Ein bibliotheksspezifisches Vokabular entdecken.** Das `general`-Set ist ein sinnvoller Standard, aber Sie können mit `python facet.py --discover-moments` ein auf *Ihre* Bibliothek zugeschnittenes Vokabular vorschlagen: Es clustert die gespeicherten `caption_embedding`-Vektoren (HDBSCAN), benennt jedes Cluster anhand seiner Bildunterschriften (ein Schlüsselwort plus die dem Zentroid am nächsten liegenden Bildunterschriften als gebrauchsfertige Prompts) und schreibt das Ergebnis als `event_types.discovered`-Block in `scoring_config.discovered.json`. Überprüfen Sie es, kopieren Sie `discovered` in `event_types` oben, setzen Sie `default_event_type` auf `discovered` und führen Sie `--recompute-moments` aus, um es zu übernehmen — die Entdeckung schlägt vor, sie überschreibt niemals die aktive Konfiguration. `--discover-min-cluster-size N` steuert die Granularität (kleiner = mehr, feinere Momente).

## Social-Export

Zuschneide-Vorlagen für Social-Media-Seitenverhältnisse mit Motiverkennung (`GET /api/photo/social_crop`, editionsbeschränkt). Jede Vorlage schneidet das Original in voller Auflösung auf ein Zielseitenverhältnis und rahmt es um das erkannte Motiv — das größte Rechteck dieses Seitenverhältnisses, das ins Bild passt, zentriert auf dem Motiv mit einem Rand und an den Rändern begrenzt. Die Motivbox folgt einer Fallback-Kette: die gespeicherte BiRefNet-Motivbox (`photos.subject_bbox`) → die Vereinigung der erkannten Gesichtsboxen → ein einfacher zentrierter Zuschnitt. Siehe [Web-Viewer — Download](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "subject_margin_percent": 8,
    "jpeg_quality": 92
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | i18n-Punktpfad für den Anzeigenamen der Vorlage (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Zielseitenverhältnis als `"b:h"` (z. B. `1:1`, `4:5`, `9:16`) |
| `subject_margin_percent` | `8` | Spielraum um die Motivbox (Prozent ihrer Größe), bevor der Zuschnitt zentriert wird |
| `jpeg_quality` | `92` | JPEG-Qualität des exportierten Zuschnitts |

Gesteuert durch `viewer.features.show_social_export` (Standard `true`). Die Spalte `photos.subject_bbox` wird vom Saliency-Durchlauf beim Scannen und von `--recompute-saliency` geschrieben; vor ihrer Einführung gescannte Zeilen greifen automatisch auf den Gesichts- oder zentrierten Zuschnitt zurück.

## Portfolio-Export

Exportieren Sie ein Album als eigenständige statische HTML-Galerie, die eine Fotografin auf jedem Webhoster ablegen kann — ohne externes Werkzeug (thumbsup/sigal) (`POST /api/albums/{album_id}/export-portfolio`, editionsbeschränkt). Das erzeugte Verzeichnis enthält `index.html` (ein responsives, rein per CSS umgesetztes Miniaturraster plus eine eingebettete Vanilla-JS-Lightbox mit **null** externen/CDN-Verweisen — vollständig offline), einen Ordner `assets/` mit fortlaufend benannten JPEGs (kein Bibliothekspfad wird preisgegeben) und eine `manifest.json`. Jedes Foto nutzt das **Original** auf der Festplatte (auf `max_edge` verkleinert), wenn es lesbar ist, und greift auf das gespeicherte 640-px-Thumbnail zurück, wenn das Original nicht erreichbar ist (offline Netzlaufwerke); die verwendete Quelle wird pro Foto im Manifest festgehalten. Die Erzeugung ist deterministisch und idempotent — ein erneuter Export überschreibt nur seine eigenen Dateien.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `max_photos` | `500` | Größere Alben werden mit einem 400 abgelehnt (der Export ist synchron) |
| `max_edge` | `2048` | Obergrenze der langen Kante (px) für exportierte Originale; die Anfrage kann sie überschreiben (auf 256–8000 begrenzt) |
| `jpeg_quality` | `88` | JPEG-Qualität der exportierten Bilder |

Das `target_dir` durchläuft dieselbe Allowlist wie die Kopier-/Verschiebe-Export-Endpunkte (`viewer.export.allowed_target_dirs` plus die Scan-Verzeichnisse). Gesteuert durch `viewer.features.show_portfolio_export` (Standard `true`).

## Bilderrahmen / Kiosk

Liefert kuratierte „beste Aufnahmen" an anmeldungsfreie Kiosk-Geräte — smarte Bilderrahmen, Home-Assistant-Dashboards, Anzeigen im Stil von ImmichFrame / Immich-Kiosk — über drei anonyme Endpunkte mit statischem Token (`GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`). Der Zugriff erfolgt über ein langlebiges, undurchsichtiges **Rahmen-Token**; eine leere `tokens`-Liste deaktiviert die gesamte Funktion (jeder Endpunkt gibt 404 zurück). Antworten enthalten niemals Dateipfade — jede Foto wird über eine undurchsichtige signierte Kennung adressiert, die aus der `rowid` der Zeile abgeleitet ist.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `tokens` | `[]` | Undurchsichtige Rahmen-Tokens (Liste). **Leer = Funktion deaktiviert (404).** Verwenden Sie lange Zufallszeichenketten, eine pro Gerät; entfernen Sie eine, um sie zu widerrufen. Erzeugen mit `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `count` | `20` | Standardanzahl der von `/api/frame/photos` zurückgegebenen Fotos |
| `max_count` | `100` | Harte Obergrenze für den Abfrageparameter `count` |
| `min_aggregate` | `7.0` | Mindest-Aggregatwert, damit ein Foto kuratiert wird |
| `max_edge` | `1920` | Obergrenze der langen Kante (px) für ausgelieferte JPEGs; der Parameter `max_edge` kann sie senken, aber nie darüber anheben |
| `favorites_only` | `false` | Wenn `true`, werden nur favorisierte Fotos kuratiert |
| `categories` | `[]` | Positivliste von Kategorienamen (leer = alle) |

Tokens werden konstantzeitlich als UTF-8-Bytes verglichen, sodass ein fehlendes Token 401 und ein falsches oder Nicht-ASCII-Token 403 ergibt (nie 500). Die Kuratierung schließt abgelehnte, Junk- (`junk_kind`) und Blinzel-Fotos aus und wendet dann Score-Schwelle / Favoriten / Kategorien an; das zurückgegebene Set ist eine score-gewichtete Zufallsstichprobe.

Ein Rahmen-Token ist keine Benutzeranmeldung: Es trägt keine `user_id` und wird gegen die gesamte Bibliothek geprüft, sodass es im [Mehrbenutzermodus](#users) die privaten `directories` jedes Benutzers ignoriert und Lesezugriff auf die Fotos aller Benutzer gewährt, nicht nur auf `shared_directories`. Geben Sie Rahmen-Token nur auf Installationen aus, bei denen jeder konfigurierte Benutzer damit einverstanden ist.

## Automatischer Upload vom Telefon

Ein minimaler **WebDAV**-Endpunkt unter `/dav`, damit Foto-Auto-Upload-Apps (PhotoSync u. a.) Fotos in ein **Eingangsverzeichnis** (Inbox) hochladen können, das `facet.py --watch` anschließend automatisch bewertet — das Mobil-Sync-Muster von PhotoPrism. Reine Upload-Infrastruktur: berührt niemals Benutzersitzungen oder JWTs. Der Zugriff erfolgt per HTTP Basic mit **Zugangsdaten für gemeinsam genutzte Geräte** (`username` / `password`), nicht mit einem Benutzerkonto. Der gesamte `/dav`-Baum liefert **404, solange die Funktion deaktiviert ist** — sie ist nur aktiv, wenn `username`, `password` und `inbox_dir` alle gesetzt sind. Jede Operation ist auf `inbox_dir` beschränkt (Traversal / absolute Pfade / Symlink-Ausbruch werden abgewiesen), und Uploads werden atomar auf die Festplatte geschrieben, begrenzt durch `max_file_mb`.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `username` | `""` | HTTP-Basic-Benutzername (Zugangsdaten für gemeinsam genutztes Gerät). **Leer = Funktion deaktiviert (404).** |
| `password` | `""` | HTTP-Basic-Passwort (Zugangsdaten für gemeinsam genutztes Gerät). **Leer = Funktion deaktiviert (404).** Verwenden Sie eine lange Zufallszeichenfolge. |
| `inbox_dir` | `""` | Absoluter Pfad des Eingangsverzeichnisses. **Leer = Funktion deaktiviert (404).** Richten Sie es auf eines der gescannten Verzeichnisse (oder ein Unterverzeichnis), damit `facet.py --watch` Uploads beim Eintreffen bewertet. Wird bei Bedarf angelegt. |
| `max_file_mb` | `500` | Größenlimit pro Datei (MB); ein Upload, der es überschreitet, bricht mit `413` ab und hinterlässt keine Teildatei. |

Die Zugangsdaten werden in konstanter Zeit als UTF-8-Bytes verglichen; ein fehlender oder falscher `Authorization`-Header ergibt ein `401` mit `WWW-Authenticate: Basic realm="Facet upload"`. Implementierte Methoden: `OPTIONS`, `PROPFIND` (Tiefe 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (`LOCK`/`UNLOCK` sind nicht implementiert). Das PhotoSync-Rezept und ein `curl`-Schnelltest sind in der Web-Viewer-Dokumentation beschrieben.

## Junk Sweep

Zero-Shot-Detektor für nicht-fotografischen „Müll" — Screenshots, gescannte Dokumente, Belege, Memes, Präsentationsfolien — über das **gespeicherte Bild-Embedding** (kein Bild-Decode, kein Modelldurchlauf pro Bild; dieselbe Form wie bei narrativen Momenten, nur ohne die zeitliche Glättung). Jede Art trägt eine Liste von Text-Prompts; das Embedding des Fotos wird per Kosinus gegen jeden Prompt bewertet und pro Art **max-gepoolt**. Ein `not_junk`-Kontrast-Prompt-Set steuert die Entscheidung: Ein Foto wird nur markiert, wenn die beste Müll-Art `min_confidence` überschreitet UND den besten `not_junk`-Prompt um `min_margin` schlägt — andernfalls wird es mit der Sentinel `not_junk` gespeichert (bewertet, sauber). `NULL` bedeutet „nicht bewertet": `--detect-junk` beschriftet nur `NULL`-Zeilen (und läuft automatisch am Ende jedes Scans), während `--recompute-junk` die gesamte Bibliothek neu bewertet. Füllt `photos.junk_kind`; die **Junk-Sweep**-Review-Warteschlange des Viewers ([VIEWER.md](VIEWER.md#müll-aufräumen)) liest diese Spalte.

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Führt die Müllerkennung während `--detect-junk` / `--recompute-junk` und am Scan-Ende aus |
| `prompt_template` | `"{desc}"` | Formatstring, der auf jeden Prompt angewendet wird (`{desc}` = der Prompt); standardmäßig Identität, da die Prompts vollständige Sätze sind |
| `pooling` | `"max"` | Poolt die Kosinuswerte pro Prompt zu einem Wert pro Art, via `max` (bester einzelner Prompt, trennschärfer) oder `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Minimaler max-gepoolter Kosinus, damit die beste Müll-Art berücksichtigt wird (CLIP/`open_clip`-Kosinuswerte liegen niedriger als SigLIP/`transformers`, daher hat jedes Backend eine eigene Schwelle) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Wie weit die beste Müll-Art den besten `not_junk`-Kontrast-Prompt schlagen muss, bevor das Foto markiert wird |
| `kinds` | screenshot/document/receipt/meme/slide | `{art: [Prompt-Synonyme]}`; fügen Sie Arten frei hinzu, entfernen oder benennen Sie sie um — Spalte und Viewer-Warteschlange folgen der Konfiguration |
| `not_junk_prompts` | 8 Foto-Prompts | Kontrast-Set, das echte Fotografien beschreibt; der Filter, der echte Fotos aus der Warteschlange heraushält |

## VLM Backend

Wählt, wo das Vision-Language-Modell für Bildunterschriften/Tags läuft. `local` (Standard) verwendet den In-Process-transformers-Qwen-Pfad, der mit den VRAM-Profilen 16gb/24gb ausgeliefert wird — keine Änderung für bestehende Installationen. Die beiden entfernten Backends verweisen Facet auf einen externen Server, sodass Bildbeschreibung und VLM-Tagging auf den **legacy/8gb-Profilen ohne lokales VLM** funktionieren: Wenn ein entferntes Backend ausgewählt ist, hängen die VLM-Funktionen nicht mehr vom VRAM-Profil ab.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `type` | `"local"` | Backend: `local` (In-Process-transformers-Qwen), `ollama` (native Ollama-REST-API) oder `openai_compatible` (beliebiger OpenAI-Chat-Completions-Endpunkt — LM Studio, vLLM, OpenRouter) |
| `ollama.base_url` | `"http://localhost:11434"` | Basis-URL des Ollama-Servers; das Bild wird als Base64 an `POST /api/generate` gesendet |
| `ollama.model` | `"qwen2.5vl:7b"` | Ollama-Modell-Tag (muss ein Vision-Modell sein, das auf dem Server bereits geladen wurde) |
| `ollama.timeout_seconds` | `120` | Timeout pro Anfrage für Ollama-Aufrufe |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | OpenAI-kompatible Basis-URL **einschließlich des `/v1`-Suffixes**; Anfragen gehen an `{base_url}/chat/completions`, mit dem Bild als `image_url`-Daten-URI |
| `openai_compatible.api_key` | `""` | Bearer-Token, gesendet als `Authorization: Bearer <schlüssel>`; für schlüssellose lokale Server leer lassen |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | An den Endpunkt übergebener Modellname |
| `openai_compatible.timeout_seconds` | `120` | Timeout pro Anfrage für OpenAI-kompatible Aufrufe |

Das gemeinsame Backend steuert die Bildbeschreibung (`--generate-captions` und den On-Demand-Endpunkt `/api/caption`), die VLM-Kritik (`/api/critique?mode=vlm`), das VLM-Re-Tagging (`--recompute-tags-vlm`) und den VLM-Tie-Breaker für narrative Momente. Ein Fehlschlag einer entfernten Anfrage wird als Fehler pro Foto protokolliert (leere Tags / keine Bildunterschrift) und lässt den Lauf nie abstürzen. Das In-Scan-Tagging verwendet weiterhin den eigenen Tagger des Profils; führen Sie `--recompute-tags-vlm` aus, um ein entferntes Backend auf eine bestehende Bibliothek anzuwenden.

## AI Critique

Prompt-Konfiguration für die VLM-gestützte Kritik (16gb/24gb-Profile). Die Kritik fügt die vollständige Regelaufschlüsselung, Strafen und EXIF in einen konfigurierbaren Leiter-Prompt ein, rendert die Antwort als Observation / Assessment / Suggestions und speichert sie pro Foto in `photos.vlm_critique` (bei Bedarf übersetzt in `vlm_critique_translated`). Sie läuft gegen das gespeicherte Thumbnail, sodass RAW-Dateien korrekt kritisiert werden, statt still zu scheitern; `refresh` regeneriert.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Token-Budget für die Generierung der strukturierten VLM-Kritik |

Siehe [Web-Viewer — KI-Kritik](VIEWER.md#ki-kritik).

## Distortion Attributes

Zero-Shot-Verzerrungskennzeichnung, nur beratend. `--recompute-distortions` bewertet jedes Foto gegen ExIQA-artige kontrastive Prompts über sein gespeichertes CLIP/SigLIP-Embedding und speichert die wahrscheinlichen Defekte (Bewegungsunschärfe, Farbstich, Überschärfung, …) als beratende JSON-Spalte. Es fließt nie in das Aggregat ein; die Labels erscheinen als Warnungs-Chips im Kritik-Dialog.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Verzerrungsattribute während `--recompute-distortions` berechnen |
| `top_n` | `5` | Maximale Anzahl an Verzerrungs-Labels, die pro Foto behalten werden |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Softmax-Temperatur über die kontrastiven Prompt-Scores, pro Embedding-Backend (wie bei `narrative_moments` laufen open_clip- und transformers-Kosinuswerte auf unterschiedlichen Skalen) |
| `thresholds.<backend>.min_confidence` | `0.6` | Minimale Wahrscheinlichkeit, damit ein Verzerrungs-Label behalten wird |
| `vocabulary` | `{}` | Optionale Überschreibung des integrierten Verzerrungs-Prompt-Sets (`{attribute: [prompt synonyms]}`); leer = Modul-Standards |

## Skin Tone

Natürlichkeit des Porträt-Hauttons (nur beratend). `--recompute-skin-tone` entnimmt Wangen-CIELAB-Chroma aus gespeicherten Gesichts-Thumbnails + Landmarken und misst deren CIEDE2000-Distanz zu einem Hautlocus mit korrelierter Farbtemperatur, wodurch Porträts markiert werden, deren Haut ins Grüne / Magenta / Blaue / Gelbe driftet. Es fließt nie in das Aggregat ein; das Ergebnis erscheint als Hautton-Hinweis im Kritik-Dialog.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Minimaler CIEDE2000-Delta zwischen dem gemessenen Haut-Chroma und dem Hautlocus, bevor ein Farbstich markiert wird |

## Immich Sync

Einweg-Synchronisierung von Facet-Sternebewertungen und -Favoriten zu einem [Immich](https://immich.app/)-Server über dessen REST-API. Assets werden anhand von `originalPath` über die konfigurierten Pfad-Präfix-Zuordnungen aufgelöst, in einem einzigen gebündelten Suchdurchlauf. Führen Sie es mit `--immich-sync` aus (prüfen Sie zuerst mit `--immich-test`); siehe [Befehle — Immich-Synchronisierung](COMMANDS.md#immich-synchronisierung).

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "timeout_seconds": 30
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `url` | `""` | Basis-URL des Immich-Servers (z. B. `http://nas:2283`) |
| `api_key` | `""` | Immich-API-Schlüssel, gesendet als `x-api-key`-Header |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Präfix-Umschreibungen von Facet-Pfaden zu Immich-`originalPath`-Werten; das erste passende `facet_prefix` wird beim Auflösen eines Assets durch sein `immich_prefix` ersetzt |
| `push.ratings` | `true` | Sternebewertungen übertragen. Immichs versionssichere Richtlinie wird berücksichtigt — nur 1–5 wird geschrieben, nie 0/−1 |
| `push.favorites` | `true` | Das Favoriten-Flag übertragen |
| `push.top_picks_album` | `""` | Optionaler Immich-Albumname, der übertragene Fotos oberhalb des Bewertungsschwellenwerts sammelt. Leer = kein Album |
| `push.top_picks_min_rating` | `4` | Minimale Sternebewertung, damit ein Foto zu `top_picks_album` hinzugefügt wird |
| `timeout_seconds` | `30` | REST-Timeout pro Anfrage |

`--immich-sync` berücksichtigt `--dry-run` (löst jedes Asset auf, schreibt aber nichts) und `--user` (überträgt die `user_preferences`-Bewertungen dieses Benutzers im Mehrbenutzermodus). Nur REST — Facet berührt nie die Immich-Datenbank.

## Timeline

Einstellungen für die chronologische Timeline-Ansicht:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `photos_per_group` | `30` | Anzahl der Fotos, die pro Datumsgruppe in der Timeline-Ansicht geladen werden. Höhere Werte zeigen mehr Fotos pro Datum, erhöhen aber das Seitengewicht. |

## Map

Einstellungen für die interaktive Kartenansicht:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Zoomstufe, ab der einzelne Marker die Cluster ersetzen. Niedrigere Werte zeigen einzelne Marker früher (mehr Details bei größerem Zoom). Bereich: 1 (Welt) bis 18 (Straße). |

## Translation

Einstellungen für die KI-Übersetzung von Bildunterschriften über MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `target_language` | `"fr"` | Zielsprachcode für `--translate-captions`. Unterstützt: `fr` (Französisch), `de` (Deutsch), `es` (Spanisch), `it` (Italienisch), `pt` (brasilianisches Portugiesisch). Verwendet Helsinki-NLP MarianMT-Modelle (CPU, keine GPU erforderlich). |

## Aesthetic CLIP (R2)

Ergänzende Ästhetikbewertung, abgeleitet aus zwischengespeicherten CLIP/SigLIP-Embeddings über Textprojektion. Prompts sind für das AVA-Benchmarking benutzerseitig anpassbar — siehe `scripts/benchmark_aesthetic.py`, um die SRCC-Auswirkung einer Änderung zu messen.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Leere Arrays fallen auf die in `analyzers/aesthetic_clip.py` fest eingebauten Modulstandards zurück. Passen Sie diese nicht an, ohne den AVA-Benchmark erneut auszuführen — die Standards erreichen SRCC ~0,52 auf `ava_test/`, und Änderungen können leicht auf ~0,30 zurückfallen.

## Adding alternative VLM tagger / critique models (R3)

Der `tagging_model`-Schlüssel jedes VRAM-Profils (z. B. `qwen3.5-2b`) verweist auf einen Modelleintrag im selben `models`-Abschnitt. Um mit einem anderen VLM (Pixtral-12B, InternVL-2.5 usw.) zu experimentieren:

1. Fügen Sie einen Modelleintrag unter `models` hinzu:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Verweisen Sie ein Profil darauf:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Führen Sie `python facet.py --recompute-tags-vlm` aus, um neu zu verschlagworten.

Keine Codeänderungen erforderlich. Validieren Sie die Qualität über eine Seite-an-Seite-Stichprobe an ~30 Fotos, bevor Sie es zum Standard machen.

## Share Secret

Automatisch generierter 64-stelliger Hex-String für Session-/Sharing-Tokens:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Wird beim ersten Start automatisch generiert, falls nicht vorhanden.
