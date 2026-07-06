# Riferimento di configurazione

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · **Italiano** · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md)

Tutte le impostazioni si trovano in `scoring_config.json`. Dopo averle modificate, esegui `python facet.py --recompute-average` per aggiornare i punteggi (non serve la GPU).

## Indice

- [Utenti](#users)
- [Scansione](#scanning)
- [Categorie](#categories)
- [Punteggio](#scoring)
- [Soglie](#thresholds)
- [Composizione](#composition)
- [Regolazioni EXIF](#exif-adjustments)
- [Esposizione](#exposure)
- [Penalità](#penalties)
- [Normalizzazione](#normalization)
- [Modelli](#models)
- [Modelli di valutazione della qualità](#quality-assessment-models)
- [Elaborazione](#processing)
- [Rilevamento raffiche](#burst-detection)
- [Punteggio raffiche](#burst-scoring)
- [Rilevamento duplicati](#duplicate-detection)
- [Rilevamento volti](#face-detection)
- [Clustering dei volti](#face-clustering)
- [Elaborazione dei volti](#face-processing)
- [Rilevamento monocromatico](#monochrome-detection)
- [Tagging](#tagging)
- [Tag autonomi](#standalone-tags)
- [Analisi](#analysis)
- [Viewer](#viewer)
- [Prestazioni](#performance)
- [Archiviazione](#storage)
- [Plugin](#plugins)
- [Capsule](#capsules)
- [Gruppi di similarità](#similarity-groups)
- [Scene](#scenes)
- [Timeline](#timeline)
- [Mappa](#map)
- [Traduzione](#translation)

---

## Users

Modalità multiutente opzionale. Quando la chiave `users` è presente (con almeno un utente), l'autenticazione a password singola è sostituita dal login per utente.

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

### Campi utente

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Generato dalla CLI `--add-user`. |
| `display_name` | string | Mostrato nell'intestazione dell'interfaccia |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directory di foto private per questo utente |

### Directory condivise

La chiave `shared_directories` (allo stesso livello degli oggetti utente) elenca le directory visibili a tutti gli utenti.

### Ruoli

| Ruolo | Vede le proprie + condivise | Valuta/preferisce | Gestisce persone/volti | Avvia scansioni |
|------|:-:|:-:|:-:|:-:|
| `user` | sì | sì | no | no |
| `admin` | sì | sì | sì | no |
| `superadmin` | sì | sì | sì | sì |

### Aggiungere utenti

Gli utenti vengono creati solo tramite CLI — non esiste un'interfaccia o un'API di registrazione:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Richiede la password, scrive l'hash in scoring_config.json
```

Dopo aver aggiunto un utente, modifica `scoring_config.json` per configurare le sue `directories`.

### Compatibilità con le versioni precedenti

- Nessuna chiave `users` = modalità monoutente legacy (comportamento invariato)
- `viewer.password` e `viewer.edition_password` vengono ignorate in modalità multiutente
- Le valutazioni esistenti nella tabella `photos` rimangono per la modalità monoutente; usa `--migrate-user-preferences` per copiarle

---

## Scanning

Controlla il comportamento della scansione delle directory.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Salta le directory che iniziano con `.` durante la scansione delle foto |

---

## Categories

Array di definizioni di categoria. Vedi [Punteggio](SCORING.md) per la documentazione dettagliata sulle categorie.

Ogni categoria ha:
- `name` - Identificatore della categoria
- `priority` - Più basso = priorità più alta (valutata per prima)
- `filters` - Condizioni di corrispondenza
- `weights` - Pesi delle metriche di punteggio (la somma deve essere 100)
- `modifiers` - Regolazioni del comportamento
- `tags` - Vocabolario CLIP per la corrispondenza basata sui tag

> **Pesi di forma e armonia cromatica.** Il blocco `weights` di ogni categoria include cinque chiavi di metriche esplicabili — `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` e `color_harmony_percent` — popolate da `--recompute-form`. In ogni categoria sono fornite a `0`, quindi gli aggregati restano identici byte per byte finché non ne assegni un peso (poi riesegui `--recompute-average`). I pesi all'interno di una categoria devono comunque sommare a 100.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `score_min` | `0.0` | Punteggio minimo possibile |
| `score_max` | `10.0` | Punteggio massimo possibile |
| `score_precision` | `2` | Cifre decimali per i punteggi |

---

## Thresholds

Soglie di rilevamento per la categorizzazione automatica.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | Volto > 5% dell'inquadratura = ritratto |
| `blink_penalty_percent` | `50` | Moltiplicatore del punteggio quando viene rilevato un battito di palpebre (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminanza media inferiore a questo valore = notte |
| `night_iso_threshold` | `3200` | ISO superiore a questo valore = scarsa illuminazione |
| `long_exposure_shutter_threshold` | `1.0` | Otturatore > 1s = lunga esposizione |
| `astro_shutter_threshold` | `10.0` | Otturatore > 10s = astrofotografia |

---

## Composition

Punteggio di composizione basato su regole (usato quando SAMP-Net non è attivo).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Peso per il posizionamento secondo la regola dei terzi |
| `line_weight` | `1.0` | Peso per le linee guida |

---

## EXIF Adjustments

Regolazioni automatiche del punteggio basate sulle impostazioni della fotocamera.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Riduce la penalità di nitidezza per ISO elevati |
| `aperture_isolation_boost` | `true` | Aumenta l'isolamento per le aperture ampie (f/1.4-f/2.8) |

---

## Exposure

Controlla l'analisi dell'esposizione e il rilevamento del clipping.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Segnala se > 15% dei pixel è nero puro |
| `highlight_clip_threshold_percent` | `10` | Segnala se > 10% dei pixel è bianco puro |
| `silhouette_detection` | `true` | Rileva le silhouette intenzionali |

---

## Penalties

Penalità al punteggio per problemi tecnici.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Rumore superiore a questo valore attiva la penalità |
| `noise_max_penalty_points` | `1.5` | Penalità massima per il rumore |
| `noise_penalty_per_sigma` | `0.3` | Punti per sigma oltre la soglia |
| `bimodality_threshold` | `2.5` | Coefficiente di bimodalità dell'istogramma |
| `bimodality_penalty_points` | `0.5` | Penalità per istogrammi bimodali |
| `leading_lines_blend_percent` | `30` | Fusione nel comp_score |
| `oversaturation_threshold` | `0.9` | Soglia di saturazione media |
| `oversaturation_pixel_percent` | `5` | Riservato al rilevamento a livello di pixel |
| `oversaturation_penalty_points` | `0.5` | Penalità per sovrasaturazione |

**Formula della penalità per il rumore:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Controlla come le metriche grezze vengono scalate in punteggi da 0 a 10.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `method` | `"percentile"` | Metodo di normalizzazione |
| `percentile_target` | `90` | 90° percentile = punteggio di 10,0 |
| `per_category` | `true` | Normalizzazione specifica per categoria |
| `category_min_samples` | `50` | Foto minime per la normalizzazione per categoria |

---

## Models

Seleziona quali modelli vengono usati per ciascun profilo VRAM.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Profilo attivo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Mantiene i modelli in RAM tra i blocchi multi-passaggio (`"auto"`, `"always"`, `"never"`). `auto` verifica la RAM disponibile prima di mettere in cache. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelli PyIQA da eseguire per questo profilo (vuoto su `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Esegue la saliency del soggetto BiRefNet per questo profilo |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modello di embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) o `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Dimensioni dell'embedding (1152 per SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similarità coseno CLIP minima per la corrispondenza di un tag |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modello CLIP legacy (profili legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesi pre-addestrati legacy |
| `clip_legacy.embedding_dim` | `768` | Dimensioni dell'embedding legacy |
| `clip_legacy.similarity_threshold_percent` | `22` | Soglia di corrispondenza dei tag per CLIP legacy |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Percorso HuggingFace (VLM di composizione 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modello di tagging per il profilo 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Immagini per batch di inferenza VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modello di tagging per il profilo 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Immagini per batch di inferenza VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modello di saliency BiRefNet |
| `saliency.resolution` | `1024` | Risoluzione di inferenza |
| `saliency.mask_threshold` | `0.3` | Soglia sigmoide per la maschera binaria del soggetto |
| `saliency.min_subject_pixels` | `50` | Pixel minimi del soggetto perché venga considerato rilevato |
| `samp_net.input_size` | `384` | Dimensione di input del modello di composizione |

### Rilevamento automatico della VRAM

Quando `vram_profile` è `"auto"` (predefinito), il sistema rileva la VRAM GPU disponibile all'avvio e seleziona il profilo più grande compatibile:

| VRAM rilevata | Profilo selezionato |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Nessuna GPU | `legacy` (usa la RAM di sistema) |

---

## Quality Assessment Models

Seleziona il modello che valuta la qualità/estetica dell'immagine, tramite la libreria [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `model` | `"auto"` | Modello di qualità: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Preferisce uno scorer basato su LLM quando disponibile |

### Modelli di qualità disponibili

SRCC = coefficiente di correlazione di rango di Spearman sul benchmark KonIQ-10k (1,0 = perfetto).

| Modello | SRCC | VRAM | Note |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Predefinito (`auto`); backbone ResNet50 con attenzione top-down |
| `hyperiqa` | 0.90 | ~2GB | Hyper-network, adattivo al contenuto |
| `dbcnn` | 0.90 | ~2GB | CNN a doppio ramo (distorsioni sintetiche + autentiche) |
| `musiq` | 0.87 | ~2GB | Transformer multiscala; gestisce qualsiasi risoluzione |
| `clipiqa+` | 0.86 | ~4GB | CLIP con prompt di qualità appresi |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 legacy + testa MLP |

### Cambiare modello di qualità

1. Modifica `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Ricalcola il punteggio delle foto esistenti (facoltativo):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Impostazioni unificate per l'elaborazione batch su GPU e la modalità multi-passaggio.

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

### Concetti chiave

**`gpu_batch_size`** - Quante immagini vengono elaborate insieme sulla GPU in un singolo forward pass. Limitato dalla VRAM. Regolato automaticamente: ridotto quando la memoria GPU supera il limite.

**`ram_chunk_size`** - Quante immagini vengono memorizzate in RAM tra i passaggi del modello (solo in modalità multi-passaggio). Riduce l'I/O su disco caricando le immagini una sola volta per blocco. Limitato dalla RAM di sistema. Regolato automaticamente: ridotto quando la memoria di sistema supera il limite.

### Riferimento delle impostazioni

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mode` | `"auto"` | Modalità di elaborazione: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Immagini per batch GPU (limitato dalla VRAM) |
| `ram_chunk_size` | `32` | Immagini per blocco RAM (multi-passaggio) |
| `num_workers` | `4` | Thread di caricamento immagini |
| `load_workers` | `num_workers` | Thread di caricamento dei blocchi multi-passaggio (limite massimo 8, `1` = sequenziale) |
| `raw_decode_concurrency` | `0` (auto) | Massimo numero di decodifiche RAW simultanee; dimensionato automaticamente da CPU/RAM (1-4), `1` = completamente serializzato |
| `raw_decode_timeout_seconds` | `120` | Abbandona una decodifica RAW bloccata dopo questo ritardo (`0` = disabilitato); la scansione fallisce rapidamente dopo blocchi ripetuti |
| `exif_prefetch` | `true` | Modalità single-pass: precarica gli EXIF in background invece di bloccare il thread GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Abilita la regolazione automatica |
| `monitor_interval_seconds` | `5` | Intervallo di controllo delle risorse |
| `tuning_interval_images` | `32` | Ri-regola ogni N immagini |
| `min_processing_workers` | `1` | Thread di caricamento minimi |
| `max_processing_workers` | `32` | Thread di caricamento massimi |
| `min_gpu_batch_size` | `2` | Dimensione minima del batch GPU |
| `max_gpu_batch_size` | `32` | Dimensione massima del batch GPU |
| `min_ram_chunk_size` | `10` | Dimensione minima del blocco RAM |
| `max_ram_chunk_size` | `128` | Dimensione massima del blocco RAM |
| `memory_limit_percent` | `85` | Limite di utilizzo della memoria di sistema |
| `cpu_target_percent` | `85` | Obiettivo di utilizzo della CPU |
| `metrics_print_interval_seconds` | `30` | Intervallo di stampa delle statistiche |
| **thumbnails** | | |
| `photo_size` | `640` | Dimensione della miniatura archiviata (pixel) |
| `photo_quality` | `80` | Qualità JPEG della miniatura |
| `face_padding_ratio` | `0.3` | Padding intorno ai ritagli dei volti |

### Modalità di elaborazione

| Modalità | Descrizione |
|------|-------------|
| `auto` | Seleziona automaticamente multi-passaggio o singolo passaggio in base alla VRAM |
| `multi-pass` | Caricamento sequenziale dei modelli (funziona con VRAM limitata) |
| `single-pass` | Tutti i modelli caricati contemporaneamente (richiede molta VRAM) |

### Come funziona il multi-passaggio

Invece di caricare tutti i modelli contemporaneamente, il multi-passaggio:

1. Carica le immagini in blocchi RAM (predefinito `ram_chunk_size`: 32)
2. Per ogni blocco, esegue i modelli in sequenza: carica modello → elabora blocco → scarica modello
3. Combina i risultati in un passaggio di aggregazione finale

Ogni immagine viene caricata una sola volta per blocco e i passaggi sono raggruppati per adattarsi alla VRAM disponibile, così i VLM di tagging/composizione più grandi possono essere eseguiti anche con VRAM limitata.

### Comportamento della regolazione automatica

Il sistema monitora l'utilizzo delle risorse e si regola:

| Metrica | Azione |
|--------|--------|
| Memoria GPU > limite | Riduce `gpu_batch_size` del 25% |
| RAM di sistema > limite | Riduce `ram_chunk_size` del 25% |
| RAM di sistema < (limite - 20%) | Aumenta `ram_chunk_size` del 25% |
| CPU > obiettivo | Suggerisce meno worker |
| Timeout della coda > 5% | Suggerisce più worker |

### Raggruppamento dinamico dei passaggi

Quando la VRAM lo consente, più modelli piccoli vengono eseguiti insieme:

| VRAM | Passaggio 1 | Passaggio 2 |
|------|--------|--------|
| 8GB | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12GB | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16GB | CLIP + SAMP-Net + InsightFace + TOPIQ | tagger VLM |
| 24GB+ | Tutti i modelli insieme (single-pass) | - |

### Opzioni CLI

```bash
# Predefinito: multi-passaggio automatico con raggruppamento ottimale
python facet.py /path/to/photos

# Forza il singolo passaggio (tutti i modelli caricati contemporaneamente)
python facet.py /path --single-pass

# Esegui solo un passaggio specifico
python facet.py /path --pass quality       # Solo TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (merito estetico)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualità + distorsione)
python facet.py /path --pass tags          # Solo il tagger configurato
python facet.py /path --pass composition   # Solo SAMP-Net
python facet.py /path --pass faces         # Solo InsightFace
python facet.py /path --pass embeddings    # Solo gli embedding CLIP/SigLIP
python facet.py /path --pass saliency      # Saliency del soggetto BiRefNet

# Elenca i modelli disponibili
python facet.py --list-models
```

---

## Burst Detection

Raggruppa foto simili scattate in rapida successione.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Soglia di similarità dell'hash dell'immagine |
| `time_window_minutes` | `0.8` | Tempo massimo tra le foto |
| `rapid_burst_seconds` | `0.4` | Foto entro questo intervallo raggruppate automaticamente |

---

## Burst Scoring

Pesi usati dalla selezione delle raffiche per calcolare un punteggio composito che individua lo scatto migliore all'interno di ciascun gruppo di raffica. La somma dei pesi dovrebbe essere 1,0.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Peso del punteggio aggregato complessivo |
| `weight_aesthetic` | `0.25` | Peso del punteggio di qualità estetica |
| `weight_sharpness` | `0.2` | Peso del punteggio di nitidezza tecnica |
| `weight_blink` | `0.15` | Peso della penalità per i battiti di palpebre rilevati (più alto = penalità più forte) |

---

## Duplicate Detection

Rileva foto duplicate a livello globale usando il confronto tramite hash percettivo (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Soglia pHash rigorosa (90% = distanza di Hamming <= 6 su 64 bit); usata come unico criterio quando manca un embedding per una delle due foto |
| `prefilter_hamming` | `12` | Override facoltativo (assente dal file fornito). Soglia di Hamming permissiva di stage 1 per l'insieme dei candidati quando entrambe le foto hanno un embedding (forzata a essere >= la soglia rigorosa) |
| `embedding_cosine_threshold` | `0.90` | Override facoltativo (assente dal file fornito). Soglia coseno SigLIP/CLIP di stage 2: un candidato pHash permissivo viene unito solo quando il coseno è >= questo valore |

Il rilevamento avviene in due fasi: candidati pHash permissivi (recall) confermati da una soglia coseno rigorosa sull'embedding (precisione). Le foto senza embedding ricadono sul criterio rigoroso basato solo su pHash, così il comportamento è invariato quando gli embedding sono assenti.

Esegui `python facet.py --detect-duplicates` per rilevare e raggruppare i duplicati. Esegui `python facet.py --sweep-dedup-thresholds [labels.json]` per valutare la soglia coseno — con un JSON di etichette stampa una tabella precisione/recall, altrimenti la distribuzione coseno dei candidati e quante collisioni pHash rigorose la soglia rifiuta.

---

## Extended IQA tier (optional)

Scorer di qualità pesanti/sperimentali, **disattivati per impostazione predefinita** e **mai sostitutivi di TOPIQ** — aggiungono colonne supplementari solo quando esplicitamente abilitati. Quando abilitati, gli scorer estesi vengono eseguiti **durante una normale scansione** e scrivono le proprie colonne; un errore di caricamento/VRAM viene registrato e la colonna è lasciata a `NULL` (la scansione non si interrompe mai).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Impostazione | Predefinito | Valori accettati | Colonna | Descrizione |
|---------|---------|-----------------|--------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA basata su LLM Q-Align (supportata da pyiqa). `"4bit"` (~6-8GB VRAM) è la scelta pratica su una scheda da 16GB; `"8bit"` ~12-14GB; la precisione piena (`true`) richiede 16GB+. 4-/8-bit necessitano di `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (testa SigLIP, ~2GB). Richiede il pacchetto `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16GB+; altrimenti saltata e lasciata a NULL). |

**Installa le dipendenze facoltative** per ciò che abiliti: `pip install -e .[iqa-extended]` (aggiunge `aesthetic-predictor-v2-5` + `bitsandbytes`), oppure decommenta le righe corrispondenti in `requirements.txt`. Q-Align è incluso in `pyiqa`; DeQA-Score viene scaricato tramite `transformers`.

Quando è abilitata, ogni metrica è esposta all'aggregato pesato ma per impostazione predefinita ha peso 0, quindi `--recompute-average` è identico byte per byte finché non le assegni un peso. Esegui `python facet.py --eval-iqa-srcc` per misurare quanto bene ciascuna metrica classifica la tua libreria rispetto alle tue valutazioni a stelle.

**Esposizione nel viewer.** Quando una di queste colonne è popolata, il viewer mostra il valore nel pannello **Quality** dei dettagli della foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) ed espone uno slider di intervallo corrispondente nella barra laterale dei filtri della galleria sotto **Extended Quality** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Le foto scansionate prima dell'abilitazione del tier hanno semplicemente `NULL` in queste colonne e non sono influenzate dai filtri.

**Robustezza.** DeQA-Score carica codice remoto `trust_remote_code` la cui firma di forward varia tra le revisioni del checkpoint; il suo scorer è difensivo — qualsiasi errore di predizione (firma errata, forma di output inattesa, OOM) viene catturato e il `deqa_score` dell'immagine è lasciato a `NULL` invece di far fallire la scansione.

---

## Face Detection

Impostazioni di rilevamento dei volti InsightFace.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confidenza minima di rilevamento |
| `min_face_size` | `20` | Dimensione minima del volto in pixel |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio per il rilevamento del battito di palpebre |
| `min_faces_for_group` | `4` | Volti minimi per classificare come ritratto di gruppo (ricalcolato con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Override facoltativo (assente dal file fornito; valore predefinito del codice `false`). Carica il modulo InsightFace `landmark_3d_68` per l'estrazione della posa della testa (yaw/pitch/roll). Costa ~5MB di pesi ONNX aggiuntivi. Attualmente informativo; futuri perfezionamenti di profilo/silhouette lo leggeranno. |
| `eyes_closed_max` | `4.0` | Punteggio di occhi aperti per singolo volto (0–10) pari o inferiore al quale la camera oscura di selezione segnala un volto come occhi chiusi. Comanda gli anelli rosso/arancione/verde attorno al volto e il cursore della soglia degli occhi (spostato da una costante fissa nel codice) |
| `poor_expression_min` | `4.0` | Punteggio di sorriso/espressione per singolo volto (0–10) sotto il quale la camera oscura segnala un'espressione debole. Comanda l'anello dell'espressione attorno al volto e il relativo cursore (spostato da una costante fissa nel codice) |
| `blendshapes.enabled` | `true` | Usa i punteggi blendshape di MediaPipe (basati sull'aspetto) per `eyes_open_score` / `smile_score` per singolo volto quando MediaPipe e il pacchetto `face_landmarker.task` sono disponibili; se `true` sostituiscono i punteggi di geometria dei punti di riferimento, altrimenti il fallback geometrico si attiva automaticamente. Dipendenza opzionale — installare con `pip install mediapipe==0.10.35 --no-deps` (mai un semplice `pip install mediapipe`). Vedi [FACE_RECOGNITION.md](FACE_RECOGNITION.md#segnali-di-espressione-per-volto-occhi-aperti--sorriso). |
| `blendshapes.min_crop_size` | `192` | I volti il cui ritaglio con padding è più piccolo di questo valore (px, lato più corto) ripiegano sul punteggio geometrico invece di ingrandire un volto minuscolo |

---

## Face Clustering

Clustering HDBSCAN per il riconoscimento dei volti.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Abilita il clustering dei volti |
| `min_faces_per_person` | `2` | Foto minime per persona |
| `min_samples` | `2` | Parametro min_samples di HDBSCAN |
| `auto_merge_distance_percent` | `15` | Unione automatica entro questa distanza |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Dimensione delle foglie dell'albero (solo CPU) |
| `use_gpu` | `"auto"` | Modalità GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similarità del centroide per la corrispondenza |
| `chunk_size` | `10000` | Dimensione del blocco di elaborazione |

**Algoritmi di clustering:**

| Algoritmo | Complessità | Ideale per |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Dati ad alta dimensionalità (consigliato) |
| `boruvka_kdtree` | O(n log n) | Dati a bassa dimensionalità |
| `prims_balltree` | O(n²) | Memoria limitata, alta dimensionalità |
| `prims_kdtree` | O(n²) | Memoria limitata, bassa dimensionalità |
| `best` | Auto | Lascia decidere a HDBSCAN |

---

## Face Processing

Controlla l'estrazione dei volti e la generazione delle miniature.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Rapporto di padding per i ritagli dei volti |
| `use_db_thumbnails` | `true` | Usa le miniature archiviate |
| `face_thumbnail_size` | `640` | Dimensione della miniatura in pixel |
| `face_thumbnail_quality` | `90` | Qualità JPEG |
| `extract_workers` | `2` | Worker di estrazione paralleli |
| `extract_batch_size` | `16` | Dimensione del batch di estrazione |
| `refill_workers` | `4` | Worker di rigenerazione delle miniature |
| `refill_batch_size` | `100` | Dimensione del batch di rigenerazione |
| **auto_tuning** | | |
| `enabled` | `true` | Abilita la regolazione basata sulla memoria |
| `memory_limit_percent` | `80` | Limite di utilizzo della memoria |
| `min_batch_size` | `8` | Dimensione minima del batch |
| `monitor_interval_seconds` | `5` | Intervallo di controllo |

---

## Monochrome Detection

Rilevamento delle foto in bianco e nero.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Saturazione media < 5% = monocromatica |

---

## Tagging

Impostazioni generali di tagging. Il modello di tagging è configurato per profilo in `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Abilita il tagging |
| `max_tags` | `5` | Numero massimo di tag per foto |

**Nota:** le impostazioni specifiche di CLIP come `similarity_threshold_percent` si trovano nella sezione `models.clip`.

### Modelli di tagging disponibili

Configurati tramite `models.profiles.*.tagging_model`:

| Modello | VRAM | Stile dei tag | Note |
|-------|------|-----------|-------|
| `clip` | 0 (riutilizza gli embedding) | Atmosfera/umore (dramatic, golden_hour, vintage) | Nessun caricamento di modello aggiuntivo; rilevamento di oggetti meno letterale |
| `qwen3.5-2b` | ~4GB | Scene strutturate (landscape, architecture, reflection) | Richiede transformers + VRAM extra |
| `qwen3.5-4b` | ~8GB | Scene dettagliate e sfumate | VRAM più alta; inferenza più lenta |

### Modelli di tagging predefiniti per profilo

| Profilo | Modello di tagging | Modello di embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Ri-taggare le foto

```bash
python facet.py --recompute-tags       # Ri-tagga usando il modello configurato per profilo
python facet.py --recompute-tags-vlm   # Ri-tagga usando il tagger VLM
```

---

## Standalone Tags

Tag con liste di sinonimi non legati ad alcuna categoria specifica. Sono disponibili per tutte le foto indipendentemente dalla categoria assegnata. Ogni chiave è il nome del tag; il valore è una lista di sinonimi per la corrispondenza CLIP/VLM.

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

Aggiungi nuovi tag autonomi fornendo una chiave e una lista di sinonimi. I tag qui definiti vengono uniti ai tag specifici per categoria per formare il vocabolario completo dei tag.

---

## Analysis

Soglie per `--compute-recommendations`.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Avvisa se l'estetica massima è sotto questo valore |
| `aesthetic_target` | `9.5` | Obiettivo per aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Soglia di qualità "alto valore" |
| `quality_weight_threshold_percent` | `10` | Avvisa se il peso della qualità è ≤ a questo valore |
| `correlation_dominant_threshold` | `0.5` | Avviso di "segnale dominante" |
| `category_min_samples` | `50` | Foto minime per categoria |
| `category_imbalance_threshold` | `0.5` | Avviso di divario di punteggio |
| `score_clustering_std_threshold` | `1.0` | Avvisa se la dev. standard è < a questo valore |
| `top_score_threshold` | `8.5` | Avvisa se l'aggregato massimo è < a questo valore |
| `exposure_avg_threshold` | `8.0` | Avvisa se l'esposizione media è > a questo valore |

---

## Viewer

Visualizzazione e comportamento della galleria web.

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

> **Nota:** `sort_options` (omesso come `{ ... }` sopra) mappa le colonne del DB sulle etichette dei menu a discesa e viene modificato raramente. Il gruppo **Content** include un ordinamento `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (i NULL finiscono in fondo).

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `default_category` | `""` | Filtro categoria predefinito |
| `edition_password` | `""` | Password per sbloccare la modalità di modifica (vuoto = disabilitato) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Minimo per l'ottimizzazione |
| `pair_selection_strategy` | `"learning"` | Strategia di coppia: `learning` (avvio a freddo per diversità di embedding + disaccordo di rango una volta addestrato), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Pool di candidati casuali all'interno del quale la strategia `learning` campiona le coppie |
| `show_current_scores` | `true` | Mostra i punteggi durante il confronto |
| **pagination** | | |
| `default_per_page` | `64` | Foto per pagina |
| **dropdowns** | | |
| `max_cameras` | `50` | Numero massimo di fotocamere nel menu a discesa |
| `max_lenses` | `50` | Numero massimo di obiettivi |
| `max_persons` | `50` | Numero massimo di persone |
| `max_tags` | `20` | Numero massimo di tag |
| `min_photos_for_person` | `10` | Nasconde dal menu a discesa le persone con meno foto |
| **persons** | | |
| `needs_naming_min_faces` | `5` | face_count minimo perché un cluster auto-generato appaia nella sezione "Da nominare" di `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome del binario darktable-cli o percorso assoluto |
| `darktable.profiles` | `[]` | Array di profili di esportazione darktable con nome (vedi sotto) |
| `darktable.profiles[].name` | *(obbligatorio)* | Nome visualizzato del profilo (usato nel menu di download e nel parametro API `profile`) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` per l'esportazione ad alta qualità |
| `darktable.profiles[].width` | *(ometti)* | Larghezza massima di output (ometti per la risoluzione piena) |
| `darktable.profiles[].height` | *(ometti)* | Altezza massima di output (ometti per la risoluzione piena) |
| `darktable.profiles[].style` | *(ometti)* | Nome dello stile darktable applicato durante l'esportazione (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Quando `false`, passa `--apply-custom-presets false` così solo lo `style` esplicito viene applicato (non i preset auto-applicati) |
| `darktable.profiles[].extra_args` | `[]` | Argomenti CLI aggiuntivi (es. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Stili darktable con nome offerti come anteprima elaborata nello studio di selezione (`GET /api/photo/cull_preview`). Vuoto = il selettore di stile è nascosto. Ogni stile **deve già esistere** nella configurazione darktable dell'utente che esegue il visualizzatore. Il nome viene passato tale e quale a `--style`. |
| `darktable.cull_styles[].name` | *(obbligatorio)* | Nome dello stile darktable (passato a `--style` e validato dall'endpoint) |
| `darktable.cull_styles[].label_key` | *(name)* | Chiave i18n facoltativa per l'etichetta del menu (predefinito: il nome dello stile) |
| `darktable.preview_max_edge` | `1440` | Bordo massimo (px) del rendering dell'anteprima di selezione |
| `darktable.preview_timeout_seconds` | `60` | Timeout di darktable-cli per rendering di anteprima |
| **display** | | |
| `tags_per_photo` | `4` | Tag mostrati sulle schede |
| `card_width_px` | `168` | Larghezza della scheda |
| `image_width_px` | `160` | Larghezza dell'immagine |
| `image_jpeg_quality` | `96` | Qualità JPEG per la conversione RAW/HEIF in `/api/download` e `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Dimensione minima della miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Dimensione massima della miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Dimensione predefinita della miniatura (px) |
| `thumbnail_slider.step_px` | `8` | Incremento dello slider (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Dimensione della miniatura |
| `jpeg_quality` | `80` | Qualità JPEG |
| `crop_padding_ratio` | `0.2` | Padding del volto |
| `min_crop_size_px` | `20` | Dimensione minima del ritaglio |
| **quality_thresholds** | | |
| `good` | `6` | Soglia "buono" |
| `great` | `7` | Soglia "ottimo" |
| `excellent` | `8` | Soglia "eccellente" |
| `best` | `9` | Soglia "il migliore" |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimo per i Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Rapporto volto per i pesi |
| `low_light_max_luminance` | `0.2` | Soglia di scarsa illuminazione |
| **defaults** | | |
| `type` | `""` | Filtro predefinito del tipo di foto (es. `"portraits"`, `"landscapes"`, o `""` per Tutte) |
| `sort` | `"aggregate"` | Colonna di ordinamento predefinita |
| `sort_direction` | `"DESC"` | Direzione di ordinamento predefinita (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Nasconde per impostazione predefinita le foto con battito di palpebre |
| `hide_bursts` | `true` | Mostra per impostazione predefinita solo la migliore della raffica |
| `hide_duplicates` | `true` | Nasconde per impostazione predefinita le foto duplicate non principali |
| `hide_details` | `true` | Nasconde per impostazione predefinita i dettagli della foto sulle schede |
| `tooltip_mode` | `"hover"` | Attivazione del tooltip: `"hover"`, `"click"` o `"off"`. Sostituisce il precedente booleano `hide_tooltip`. |
| `hide_rejected` | `true` | Nasconde per impostazione predefinita le foto rifiutate |
| `gallery_mode` | `"mosaic"` | Layout predefinito della galleria (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origini consentite per CORS del server FastAPI. Aggiungi il tuo dominio o l'URL del reverse proxy quando lo ospiti da remoto. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(predefinito sicuro per la SPA)_ | Valore dell'header Content-Security-Policy. Per impostazione predefinita una policy che consente le risorse della SPA (script/stile di tema inline, Google Fonts, tile OpenStreetMap, API same-origin). Imposta `""` per disabilitare, oppure fornisci una policy più restrittiva. |
| `security_headers.hsts` | `false` | Invia `Strict-Transport-Security`. Abilita solo quando il viewer è servito via HTTPS. |
| **Altro** | | |
| `cache_ttl_seconds` | `60` | TTL della cache delle query |
| `notification_duration_ms` | `2000` | Durata del toast |
| `moment_confidence_min` | `0` | Al di sotto di questo posterior `narrative_moment_confidence` memorizzato (0–1), le etichette dei momenti vengono mostrate attenuate con un suffisso "(uncertain)" nell'intestazione delle Scene, nell'intestazione del gruppo di scena della selezione e nel tooltip della foto in galleria. `0` = non attenuare mai |

### Funzionalità

Attiva o disattiva le funzionalità opzionali per ridurre l'uso della memoria o semplificare l'interfaccia:

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostra il pulsante "Trova simili" sulle schede delle foto (usa numpy per la similarità CLIP) |
| `show_merge_suggestions` | `true` | Abilita la funzionalità di suggerimenti di unione nella pagina di gestione delle persone |
| `show_rating_controls` | `true` | Mostra i controlli di valutazione a stelle e preferiti |
| `show_rating_badge` | `true` | Mostra il badge di valutazione sulle schede delle foto |
| `show_scan_button` | `false` | Mostra il pulsante di avvio scansione per gli utenti superadmin (richiede GPU sull'host del viewer) |
| `metrics_enabled` | `false` | Abilita l'endpoint Prometheus pubblico `GET /metrics`. Disattivato per impostazione predefinita — espone conteggi di foto/persone/volti, dimensione del DB e memoria del processo; abilitalo solo quando l'endpoint è raggiungibile dalla rete dello scraper, non da Internet pubblico. |
| `show_semantic_search` | `true` | Mostra la barra di ricerca semantica (ricerca testo-immagine usando gli embedding CLIP/SigLIP) |
| `show_albums` | `true` | Mostra la funzionalità album (crea, gestisci e sfoglia album di foto) |
| `show_critique` | `true` | Mostra il pulsante di critica AI sulle schede delle foto (analisi del punteggio basata su regole) |
| `show_vlm_critique` | `true` | Abilita la modalità di critica basata su VLM (richiede il profilo VRAM 16gb/24gb). Il codice ricade su `false` quando la chiave è assente. |
| `show_embed_metadata` | `true` | Mostra l'azione "Scrivi metadati nel file" per ogni miniatura in modalità di modifica (incorpora valutazioni/parole chiave nell'immagine originale tramite exiftool) |
| `show_memories` | `true` | Mostra la finestra dei ricordi "In questo giorno" (foto scattate nella stessa data degli anni precedenti) |
| `show_captions` | `true` | Mostra le didascalie generate dall'AI sulle schede delle foto |
| `show_timeline` | `true` | Mostra la vista timeline per la navigazione cronologica con navigazione per data |
| `show_map` | `true` | Mostra la vista mappa con le posizioni delle foto basate sul GPS (richiede Leaflet). Il codice ricade su `false` quando la chiave è assente. |
| `show_capsules` | `true` | Mostra la vista Capsule (diaporame di foto curate raggruppate per tema) |
| `show_folders` | `true` | Mostra la navigazione per cartelle della struttura delle directory delle foto |
| `show_scenes` | `true` | Mostra la vista Scene (`/scenes`) che raggruppa le foto principali delle raffiche in scene cronologiche per la selezione in ordine narrativo |
| `show_my_taste` | `true` | Mostra l'ordinamento "My Taste" basato sul punteggio appreso del ranker personale, con un badge di confidenza per copertura/accuratezza apprese |
| `show_social_export` | `true` | Mostra il menu **Ritaglio social** (solo edizione): ritagli consapevoli del soggetto per i rapporti d'aspetto dei social. Vedi [Esportazione social](#esportazione-social) |
| `show_portfolio_export` | `true` | Mostra l'azione dell'album **Esporta portfolio** (solo edizione): galleria HTML statica autonoma. Vedi [Esportazione portfolio](#esportazione-portfolio) |
| `show_proofing` | `false` | Abilita la revisione del cliente sugli album condivisi: un collegamento di condivisione (più un PIN facoltativo) consente a un cliente senza account di mettere un cuore alle foto e lasciare commenti, che il proprietario dell'album esamina da una finestra di dialogo in modalità di modifica. Disattivata per impostazione predefinita. Vedi [Revisione del cliente](#revisione-del-cliente) |

**Ottimizzazione della memoria:** impostare `show_similar_button: false` impedisce il caricamento di numpy, riducendo l'ingombro di memoria del viewer. La funzionalità delle foto simili calcola la similarità coseno degli embedding CLIP, che richiede numpy.

### Revisione del cliente

`viewer.features.show_proofing` (predefinito `false`) trasforma qualsiasi album condiviso in una superficie di revisione del cliente. Un collegamento di condivisione — facoltativamente protetto da `viewer.proofing.pin` — consente a un cliente senza account di scambiare il token di condivisione con una sessione di breve durata, poi di mettere un cuore alle foto e lasciare commenti. Le scelte risiedono in una tabella dedicata `album_client_picks`, delimitata alle foto di quell'album e completamente isolata dalle valutazioni del proprietario (non toccano mai `photos.is_favorite` / `user_preferences` e non addestrano mai il ranker personale). Il proprietario legge le scelte da una finestra di dialogo in modalità di modifica sulla scheda dell'album.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `features.show_proofing` | `false` | Interruttore principale per la revisione del cliente sugli album condivisi |
| `proofing.pin` | `""` | PIN facoltativo che un cliente deve inserire (insieme al token di condivisione) per aprire una sessione di revisione. Vuoto = nessun PIN. I controlli hanno un limite di frequenza e sono sicuri byte per byte |
| `proofing.session_minutes` | `1440` | Durata in minuti del token di sessione di revisione del cliente (predefinito 24h). Le sessioni si interrompono anche nel momento in cui l'album viene rimosso dalla condivisione o la revisione viene disabilitata |

### Mappatura dei percorsi

Mappa i percorsi del database sui percorsi del filesystem locale. Utile quando le foto sono state valutate su una macchina (es. Windows con percorsi UNC) ma il viewer gira su un'altra (es. NAS Linux con punti di mount).

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `path_mapping` | `{}` | Dizionario da prefisso di origine a prefisso di destinazione. Quando si servono immagini a piena risoluzione o la critica VLM, i percorsi del database che iniziano con un prefisso di origine vengono riscritti per usare il prefisso di destinazione. |

**Come funziona:**
- Si applica solo durante la **lettura dei file da disco** (servizio di immagini a piena risoluzione, download di file, critica VLM). I percorsi del database non vengono mai modificati.
- La normalizzazione tra backslash e slash è gestita automaticamente: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` corrispondono entrambi.
- Le mappature vengono valutate in ordine; vince il primo prefisso corrispondente.
- Le destinazioni della mappatura dei percorsi sono incluse automaticamente nell'elenco di directory di scansione consentite per i controlli di sicurezza multiutente.

**Esempio:** un database popolato su Windows memorizza percorsi come `\\NAS\Photos\2024\IMG_001.jpg`. Su Linux, la stessa condivisione è montata in `/mnt/nas/Photos`. Configura:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protezione con password

Protezione opzionale con password per il viewer:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando impostata, gli utenti devono autenticarsi prima di accedere al viewer.

### Prestazioni del viewer

Sovrascrive le impostazioni globali di `performance` quando si esegue il viewer. Utile per deployment su NAS con poca memoria, dove la valutazione necessita di risorse elevate ma il viewer no.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mmap_size_mb` | *(globale)* | Override della dimensione mmap di SQLite per le connessioni del viewer. `0` disabilita mmap. |
| `cache_size_mb` | *(globale)* | Override della dimensione della cache di SQLite per le connessioni del viewer |
| `pool_size` | `5` | Dimensione del pool di connessioni (riduci per sistemi con poca memoria) |
| `thumbnail_cache_size` | `2000` | Numero massimo di voci nella cache in memoria del ridimensionamento delle miniature |
| `face_cache_size` | `500` | Numero massimo di voci nella cache in memoria delle miniature dei volti |

Quando non impostate, il viewer usa i valori globali di `performance`. Vedi [Deployment](DEPLOYMENT.md) per le impostazioni NAS consigliate.

---

## Performance

Impostazioni delle prestazioni del database.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

> **Nota:** `wal_checkpoint_minutes` è un override facoltativo e **non** è presente nel blocco `performance` fornito (che contiene solo `mmap_size_mb`, `cache_size_mb` e `slow_request_ms`). Aggiungilo esplicitamente per modificare il valore predefinito di `30`.

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Dimensione dell'I/O mappato in memoria di SQLite |
| `cache_size_mb` | `128` | Dimensione della cache di SQLite |
| `wal_checkpoint_minutes` | `30` | Override facoltativo (assente dal file fornito). Intervallo in minuti del `PRAGMA wal_checkpoint(TRUNCATE)` in background del viewer. Previene l'aumento eccessivo del WAL nei deployment a lunga durata. Imposta `0` per disabilitare. |
| `slow_request_ms` | `1000` | Le richieste API del viewer più lente di questo numero di millisecondi vengono registrate a livello WARNING con un marcatore `SLOW`. Imposta `0` per disabilitare. |

---

## Storage

Controlla dove vengono archiviati miniature ed embedding. Il valore predefinito sono colonne BLOB nel database SQLite; la modalità filesystem li archivia invece come file su disco, riducendo la dimensione del database.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mode` | `"database"` | Backend di archiviazione: `"database"` (BLOB SQLite) o `"filesystem"` (file su disco) |
| `filesystem_path` | `"./storage"` | Directory di base per la modalità filesystem. Le miniature sono archiviate in `<path>/thumbnails/` e gli embedding in `<path>/embeddings/`, organizzati in sottodirectory per hash del contenuto. |

**Dettagli della modalità filesystem:**
- I file sono organizzati per hash SHA-256 del percorso della foto, con sottodirectory di due caratteri per evitare troppi file in una sola directory (es. `thumbnails/a3/a3f8..._640.jpg`).
- L'eliminazione di una foto rimuove tutte le dimensioni di miniatura e i file di embedding associati.
- La directory viene creata automaticamente al primo utilizzo.

---

## Plugins

Sistema di plugin orientato agli eventi per reagire agli eventi di valutazione. I plugin possono essere moduli Python, webhook o azioni integrate.

### Configurazione

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

| Chiave | Predefinito | Descrizione |
|-----|---------|-------------|
| `enabled` | `false` | Interruttore principale — quando false, non viene emesso alcun evento |
| `high_score_threshold` | `8.0` | Punteggio aggregato minimo per attivare gli eventi `on_high_score` |
| `webhooks` | `[]` | Elenco di endpoint webhook che ricevono payload JSON via POST |
| `actions` | `{}` | Azioni integrate con nome attivate dagli eventi |

### Eventi supportati

| Evento | Attivazione | Payload |
|-------|---------|---------|
| `on_score_complete` | Dopo che ogni foto è valutata | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Quando una foto entra nel database | Come `on_score_complete` |
| `on_high_score` | Quando l'aggregato ≥ `high_score_threshold` | Come `on_score_complete` |
| `on_burst_detected` | Quando viene identificato un gruppo di raffica | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Scrivere un plugin

Posiziona un file `.py` nella directory `plugins/`. Definisci funzioni con il nome degli eventi che vuoi gestire:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Vedi `plugins/example_plugin.py.example` per l'interfaccia completa.

### Webhook

Ogni webhook riceve una POST JSON con protezione SSRF (gli indirizzi privati/loopback sono bloccati):

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

Opzioni del webhook: `url` (obbligatorio), `events` (lista di nomi di eventi), `min_score` (aggregato minimo per l'attivazione).

### Azioni integrate

| Azione | Descrizione | Opzioni |
|--------|-------------|---------|
| `copy_to_folder` | Copia la foto in una cartella | `folder`, `min_score` |
| `send_notification` | Registra una notifica | `min_score` |

### Endpoint API

| Metodo | Percorso | Descrizione |
|--------|------|-------------|
| `GET` | `/api/plugins` | Elenca plugin, webhook e azioni caricati |
| `POST` | `/api/plugins/test-webhook` | Invia un payload di test a un URL webhook |

---

## Capsules

Diaporame (slideshow) di foto curate raggruppate per tema. Le capsule vengono generate automaticamente dalla tua libreria di foto e memorizzate in cache con un TTL configurabile.

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

### Impostazioni globali

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Punteggio aggregato minimo perché le foto siano incluse nelle capsule |
| `max_photos_per_capsule` | `40` | Foto massime per capsula (diversità MMR applicata oltre 5) |
| `max_photo_overlap` | `0.2` | Frazione massima di foto condivise tra due capsule prima che la deduplica ne rimuova una |
| `mmr_lambda` | `0.5` | Peso della diversità MMR: 0=massimizza la diversità, 1=massimizza la qualità |
| `mmr_moment_weight` | `0.0` | Peso facoltativo che mescola il `narrative_moment_confidence` di ogni foto nella selezione MMR delle capsule. `0.0` = comportamento invariato |
| `freshness_hours` | `24` | TTL della cache e periodo di rotazione per le foto di copertina e le capsule seeded |
| `reverse_geocoding` | `true` | Abilita il reverse geocoding offline per i titoli delle capsule di luogo/viaggio (richiede il pacchetto `reverse_geocoder`) |

### Tipi di capsula

| Tipo | Descrizione |
|------|-------------|
| `journey` | Viaggi rilevati tramite clustering GPS + intervalli temporali. I titoli includono il nome della destinazione quando il geocoding è abilitato. |
| `faces_of` | Migliori foto di ogni persona riconosciuta |
| `seasonal` | Foto raggruppate per stagione + anno |
| `golden` | Primo 1% per punteggio aggregato |
| `color_story` | Gruppi visivamente simili tramite clustering degli embedding CLIP |
| `this_week` | "Questa settimana, anni fa" — On This Day esteso a ±3 giorni |
| `location` | Cluster di foto geolocalizzate con nomi di luogo da reverse geocoding |
| `person_pair` | Coppie di persone con nome che appaiono insieme |
| `seeded` | Scoperta basata su seed tramite tempo, similarità, persona, tag, luogo, umore |
| `progress` | "La tua fotografia sta migliorando" dalle tendenze dei punteggi trimestrali |
| `color_palette` | "Colore del mese" dai profili di saturazione/monocromia |
| `rare_pair` | Coppie di persone poco frequenti in foto con punteggio elevato |
| `favorites` | Foto preferite raggruppate per anno e stagione |

### Capsule basate su dimensioni

Generate automaticamente dalle colonne del database:

| Dimensione | Raggruppata per |
|-----------|-----------|
| `year` | Anno estratto da date_taken |
| `month` | Anno-mese estratto da date_taken |
| `week` | Anno-settimana estratto da date_taken |
| `camera` | Modello di fotocamera |
| `lens` | Modello di obiettivo |
| `tag` | Tag delle foto (richiede la tabella `photo_tags`) |
| `day_of_week` | Giorno della settimana (domenica–sabato) |
| `composition` | Pattern di composizione SAMP-Net (rule_of_thirds, horizontal, ecc.) |
| `focal_range` | Fasce di lunghezza focale: ultra grandangolo (<24mm), grandangolo (24–35mm), standard (36–70mm), ritratto (71–135mm), teleobiettivo (136–300mm), super teleobiettivo (300mm+) |
| `category` | Categoria di contenuto della foto (portrait, landscape, street, ecc.) |
| `time_of_day` | Fasce orarie: mattino dorato, mattino, mezzogiorno, pomeriggio, sera dorata, notte |
| `star_rating` | Valutazioni a stelle dell'utente (1–5 stelle) |

Vengono generate anche combinazioni cross-dimensionali (es. fotocamera × anno, focal_range × categoria, categoria × anno).

### Transizioni della slideshow

Ogni tipo di capsula è associato a una transizione di slide a tema:

| Transizione | Usata da | Effetto |
|-----------|---------|--------|
| `crossfade` | Predefinita | Scambio di opacità di 300ms |
| `slide` | journey, location, this_week | Scivolamento da destra (500ms) |
| `zoom` | faces_of, color_story | Scala 1.05→1.0 con dissolvenza (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 per la durata della slide |

### Reverse geocoding

Le capsule di luogo e viaggio usano il reverse geocoding offline tramite il pacchetto `reverse_geocoder` (dataset GeoNames locale, ~30MB, nessuna chiamata API). I risultati vengono memorizzati nella tabella di database `location_names` con risoluzione di griglia di 0,1° (~11km).

Installazione: `pip install reverse_geocoder`

Imposta `"reverse_geocoding": false` per disabilitare e ricadere sulla visualizzazione delle coordinate.

## Similarity Groups

Impostazioni per la funzionalità di selezione AI delle foto simili, che raggruppa le foto visivamente simili usando gli embedding CLIP/SigLIP:

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Similarità coseno minima (0,0–1,0) per considerare due foto visivamente simili. Valori più bassi producono gruppi più grandi ma con minore similarità visiva. |
| `min_group_size` | `2` | Numero minimo di foto necessarie per formare un gruppo di similarità |
| `max_photos` | `10000` | Foto massime da caricare per il calcolo della similarità (costo O(n²)). Aumenta per librerie più grandi a scapito del tempo di calcolo. |
| `max_group_size` | `50` | Foto massime per gruppo di similarità. I gruppi più grandi vengono suddivisi per mantenere l'interfaccia utilizzabile. |

## Auto-Cull

Selezione automatica con un solo pulsante per la camera oscura di selezione (`POST /api/culling/auto`, riservata alla modalità di modifica). Seleziona un intero ambito — tutti i gruppi, oppure solo raffiche / foto simili / scene, eventualmente ristretto a un album o a una finestra temporale — in un unico passaggio. Ogni gruppo conserva la sua foto migliore più tutto ciò che rientra in un margine derivato dal rigore (lo stesso budget di conservazione del cursore della camera oscura manuale), con un minimo per gruppo, e scarta il resto.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `default_strictness` | `50` | Budget di conservazione (0–100) usato quando la richiesta omette `strictness`. Più alto = conserva meno foto per gruppo (margine più stretto attorno alla migliore del gruppo) |
| `highlights_min` | `8.0` | Punteggio aggregato minimo perché la foto migliore di un gruppo venga raccolta nell'album facoltativo **Highlights** quando viene applicata una selezione automatica (idempotente) |

`dry_run` è attivo per impostazione predefinita e restituisce un'anteprima di conservazione/scarto per gruppo; l'applicazione registra inoltre righe di confronto `source='culling'` e sollecita un riaddestramento automatico. Vedi [Galleria web — Selezione automatica](VIEWER.md#selezione-automatica).

## Profili di scarto per genere

Preset per genere che raggruppano tutti i controlli di scarto in un clic: lo sport conserva solo la foto più nitida di una lunga raffica, i matrimoni conservano più varianti con gli occhi aperti come priorità, i concerti allentano le soglie occhi/espressione, la fauna selvatica rimuove del tutto il filtro del volto umano. La camera oscura di scarto mostra un selettore di preset.

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

| Impostazione | Descrizione |
|---|---|
| `default` | Id del profilo applicato quando nessuno è memorizzato lato client |
| `profiles.<id>.label_key` | Percorso i18n del nome visualizzato del preset (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Budget di conservazione (0–100) immesso nel margine di auto-scarto quando il preset è attivo |
| `profiles.<id>.eyes_closed_max` | Punteggio occhi aperti (0–10) al di sotto del quale un volto è considerato chiuso — sovrascrive `face_detection.eyes_closed_max` nei badge del volto |
| `profiles.<id>.poor_expression_min` | Punteggio espressione/sorriso (0–10) sotto il quale un volto è considerato scarso — sovrascrive `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | Minimo per gruppo sull'insieme conservato dall'auto-scarto |
| `profiles.<id>.similarity_threshold` | Soglia di raggruppamento per similarità (percentuale) applicata dalla camera oscura quando il preset è selezionato |

Endpoint (in sola lettura): `GET /api/culling/profiles` restituisce l'elenco ordinato dei preset e il predefinito. La richiesta di auto-scarto (`POST /api/culling/auto`) e il batch per volto (`POST /api/culling-group/faces`) accettano un `profile` opzionale; uno `strictness`/`min_keep_per_group` esplicito nella richiesta prevale sempre sul preset.

## Scenes

Impostazioni per la vista Scene, che raggruppa le foto principali delle raffiche in scene cronologiche (suddivise per intervalli di tempo di scatto) per la selezione in ordine narrativo:

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Una nuova scena inizia quando trascorrono più di questi minuti tra due foto principali di raffica consecutive (il limite inferiore quando `adaptive` è attivo) |
| `min_size` | `2` | Foto minime perché una scena venga mostrata |
| `max_photos` | `5000` | Foto principali di raffica massime caricate per il raggruppamento in scene |
| `max_scene_size` | `60` | Una scena più grande di questo valore viene suddivisa ricorsivamente in corrispondenza dei suoi maggiori intervalli interni, così un evento scattato in continuità non collassa mai in un'unica scena gigantesca |
| `adaptive` | `true` | Quando attivo, l'intervallo effettivo si amplia a `adaptive_k × mediana` degli intervalli consecutivi dello scatto (si restringe per scatti rapidi, si allarga per vacanze diradate) |
| `adaptive_k` | `6.0` | Moltiplicatore applicato all'intervallo mediano quando `adaptive` è attivo |
| `split_on_moment_change` | `false` | Quando attivo (e i momenti narrativi sono calcolati), suddivide una sequenza temporale in cui il momento dominante cambia e si mantiene per `moment_split_min_run` fotogrammi |
| `moment_split_min_run` | `4` | Isteresi per `split_on_moment_change` — quanti fotogrammi consecutivi un nuovo momento deve persistere per forzare un confine |

## Narrative Moments

Etichettatura zero-shot del "momento" di scena/attività di ogni foto. Il vocabolario **general** predefinito copre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle`, oppure `other` — così funziona su qualsiasi libreria, non solo sui matrimoni (`wedding` è incluso come genere opt-in). Popolata da `--detect-moments` (eseguito automaticamente al termine di ogni scansione) ed esposta come nomi di scena e filtro della galleria. Qualcosa che né Narrative Select né AfterShoot fanno.

Il segnale è **semantico sulla didascalia**: la didascalia AI di ogni foto viene codificata una sola volta con l'encoder testuale e memorizzata (la colonna `caption_embedding`); il momento è il miglior coseno **max-pooled** di quell'embedding della didascalia rispetto ai prompt testuali per momento. L'embedding dell'immagine memorizzato è il ripiego quando una foto non ha didascalia. Il testo della didascalia corrisponde ai prompt dei momenti in modo ~2,4× più netto rispetto all'embedding grezzo dell'immagine, quindi il segnale `caption` adotta soglie più alte rispetto al ripiego `image`; ciascuno è regolato per backend (i coseni di open_clip sono molto più bassi di quelli di SigLIP). I valori `transformers` (SigLIP) sono forniti come valori predefiniti conservativi — riregolali se usi un profilo SigLIP.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Interruttore principale; quando disattivato, `--detect-moments` e l'hook di scansione non fanno nulla |
| `prompt_template` | `"a photo of {desc}"` | Wrapper applicato a ogni prompt prima della codifica |
| `default_event_type` | `"general"` | Quale vocabolario `event_types` è attivo. `general` = 20 momenti agnostici di scena/attività; `wedding` è incluso come genere opt-in |
| `pooling` | `"max"` | Punteggio per momento = il singolo miglior coseno di prompt (max-pool), più discriminante della media |
| `caption_min_confidence` | `0` | Gate sulla qualità della didascalia: quando > 0, `--generate-captions` e l'endpoint di didascalia on-demand saltano le foto non etichettate, `other` o al di sotto di questa confidenza di momento memorizzata. `0` = nessun gate |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Sotto questo coseno top-1 una foto è `other`. Indicizzato per **segnale** (`caption` vs `image`) poi per backend — i coseni di caption sono ~2,4× più alti |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Divario coseno top-1/top-2 minimo; al di sotto il fotogramma è `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Spinte L1 su volti/tag che rompono solo i quasi-pareggi; `weight` limita ogni spinta alla scala del coseno |
| `priors.caption_tag_scale` | `0.25` | Riduce le regole `tag` sul segnale caption (L0 codifica già la didascalia); le regole strutturali mantengono il peso pieno |
| `priors.rules` / `priors.event_types.<et>.rules` | (set generale) | Regole dichiarative `{kind, when, boost}` indipendenti dal vocabolario; un `boost` verso un momento assente dal vocabolario attivo viene ignorato. Le regole per `event_type` sostituiscono l'elenco globale. Riferimento completo dei predicati: doc inglese |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Levigatura L2 della timeline (Viterbi): orientata alla permanenza senza progressione in avanti (il vocabolario agnostico non ha un ordine canonico), applicata in modo leggero (`weight=0` = nessuna levigatura) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Spareggio L3 (ora attivo): quando abilitato sui profili 16gb/24gb, solo i fotogrammi a basso posterior (sotto `min_confidence`) o a margine ridotto (sotto `min_margin`) vengono ri-classificati dal VLM del profilo durante `--detect-moments` / `--recompute-moments` |
| `event_types` | `general` + `wedding` | Per ogni tipo di evento `{moment: [sinonimi di prompt]}`; imposta `default_event_type` per cambiare genere o aggiungere il tuo |

> **Costo del backfill delle didascalie.** Gli embedding delle didascalie vengono calcolati una sola volta e memorizzati, quindi il coseno per foto è poi gratuito. Una scansione codifica solo la sua manciata di nuove didascalie (economico, incrementale), ma il primo passaggio completo su una libreria esistente codifica ogni didascalia — un passaggio in avanti dell'encoder testuale per didascalia, veloce su GPU e ~ore su CPU. Esegui `python facet.py --detect-moments` una volta (GPU consigliata) per quel backfill; aggiungi `--limit N` per verificare prima su un campione.

**Scoprire un vocabolario specifico per la libreria.** L'insieme `general` è un'impostazione predefinita sensata, ma puoi proporre un vocabolario adattato alla *tua* libreria con `python facet.py --discover-moments`: raggruppa i vettori `caption_embedding` memorizzati (HDBSCAN), nomina ogni cluster a partire dalle sue didascalie (una parola chiave più le didascalie più vicine al centroide come prompt già pronti) e scrive il risultato come blocco `event_types.discovered` in `scoring_config.discovered.json`. Rivedilo, copia `discovered` in `event_types` sopra, imposta `default_event_type` su `discovered` ed esegui `--recompute-moments` per adottarlo — la scoperta propone, non riscrive mai la configurazione attiva. `--discover-min-cluster-size N` controlla la granularità (più piccolo = momenti più numerosi e fini).

## Esportazione social

Ritagli consapevoli del soggetto per i rapporti d'aspetto dei social (`GET /api/photo/social_crop`, riservato all'edizione). Ogni preset ritaglia l'originale a piena risoluzione verso un rapporto d'aspetto obiettivo e lo inquadra sul soggetto rilevato — il più grande rettangolo di quel rapporto che entra nell'immagine, centrato sul soggetto con un margine e vincolato ai bordi. Il box del soggetto segue una catena di ripiego: il box del soggetto BiRefNet persistito (`photos.subject_bbox`) → l'unione dei box dei volti rilevati → un ritaglio centrato semplice. Vedi [Visualizzatore web — Download](VIEWER.md#download).

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Percorso i18n con punti per il nome visualizzato del preset (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Rapporto d'aspetto obiettivo come `"l:h"` (es. `1:1`, `4:5`, `9:16`) |
| `subject_margin_percent` | `8` | Margine attorno al box del soggetto (percentuale della sua dimensione) prima di centrare il ritaglio |
| `jpeg_quality` | `92` | Qualità JPEG del ritaglio esportato |

Controllato da `viewer.features.show_social_export` (predefinito `true`). La colonna `photos.subject_bbox` è scritta dalla passata di salienza in fase di scansione e da `--recompute-saliency`; le righe scansionate prima della sua introduzione ripiegano automaticamente sul ritaglio per volti o centrato.

## Esportazione portfolio

Esporta un album come galleria HTML statica e autonoma che un fotografo può caricare su qualsiasi hosting web — senza strumenti esterni (thumbsup/sigal) (`POST /api/albums/{album_id}/export-portfolio`, solo edizione). La directory generata contiene `index.html` (una griglia di miniature responsive solo in CSS più una lightbox vanilla-JS integrata, con **zero** riferimenti esterni/CDN — completamente offline), una cartella `assets/` di JPEG con nomi sequenziali (nessun percorso della libreria viene divulgato) e un `manifest.json`. Ogni foto usa l'**originale** su disco (ridotto a `max_edge`) quando è leggibile e ripiega sulla miniatura da 640 px memorizzata quando l'originale è irraggiungibile (condivisioni di rete offline); la sorgente usata è registrata per foto nel manifest. La generazione è deterministica e idempotente — una riesportazione riscrive solo i propri file.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Impostazione | Predefinito | Descrizione |
|--------------|-------------|-------------|
| `max_photos` | `500` | Gli album più grandi vengono rifiutati con un 400 (l'esportazione è sincrona) |
| `max_edge` | `2048` | Limite del lato lungo (px) per gli originali esportati; la richiesta può sovrascriverlo (limitato 256–8000) |
| `jpeg_quality` | `88` | Qualità JPEG delle immagini esportate |

Il `target_dir` passa attraverso la stessa allow-list degli endpoint di esportazione copia/spostamento (`viewer.export.allowed_target_dirs` più le directory di scansione). Controllato da `viewer.features.show_portfolio_export` (predefinito `true`).

## Cornice digitale / Chiosco

Distribuisce gli «scatti migliori» curati verso dispositivi in modalità chiosco senza login — cornici digitali smart, dashboard Home Assistant, display in stile ImmichFrame / Immich-Kiosk — tramite tre endpoint anonimi con token statico (`GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`). L'accesso è un **token di cornice** opaco e a lunga durata; un elenco `tokens` vuoto disabilita l'intera funzione (ogni endpoint restituisce 404). Le risposte non contengono mai percorsi di file — ogni foto è indirizzata da un id firmato opaco derivato dal `rowid` della riga.

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

| Impostazione | Predefinito | Descrizione |
|--------------|-------------|-------------|
| `tokens` | `[]` | Token di cornice opachi (elenco). **Vuoto = funzione disabilitata (404).** Usa stringhe casuali lunghe, una per dispositivo; rimuovine una per revocarla. Generane una con `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `count` | `20` | Numero predefinito di foto restituite da `/api/frame/photos` |
| `max_count` | `100` | Limite rigido del parametro di query `count` |
| `min_aggregate` | `7.0` | Punteggio aggregato minimo perché una foto venga curata |
| `max_edge` | `1920` | Limite del lato lungo (px) dei JPEG serviti; il parametro `max_edge` può abbassarlo ma mai superarlo |
| `favorites_only` | `false` | Se `true`, vengono curate solo le foto preferite |
| `categories` | `[]` | Elenco consentito di nomi di categoria (vuoto = tutte) |

I token vengono confrontati a tempo costante come byte UTF-8, quindi un token mancante è 401 e un token errato o non ASCII è 403 (mai 500). La curatela esclude le foto rifiutate, spazzatura (`junk_kind`) e con occhi chiusi, poi applica soglia di punteggio / preferiti / categorie; l'insieme restituito è un campione casuale ponderato per punteggio.

Un token di cornice non è un login utente: non porta alcun `user_id` ed è verificato rispetto all'intera libreria, quindi in [modalità multiutente](#users) ignora le `directories` private di ciascun utente e concede accesso in lettura alle foto di tutti gli utenti, non solo a `shared_directories`. Rilascia i token di cornice solo sulle installazioni in cui ogni utente configurato è a suo agio con questo.

## Junk Sweep

Rilevatore zero-shot per file non fotografici "spazzatura" — screenshot, documenti scansionati, ricevute, meme, diapositive di presentazione — sull'**embedding immagine memorizzato** (nessuna decodifica dell'immagine, nessun passaggio del modello per immagine; la stessa struttura dei momenti narrativi senza il livellamento temporale). Ogni tipo porta un elenco di prompt testuali; l'embedding della foto viene valutato per coseno contro ogni prompt e poi **max-pooled** per tipo. Un insieme di prompt di contrasto `not_junk` condiziona la decisione: una foto viene segnalata solo quando il miglior tipo di spazzatura supera `min_confidence` E batte il miglior prompt `not_junk` di `min_margin` — altrimenti viene memorizzata con la sentinella `not_junk` (valutata, pulita). `NULL` significa "non valutata": `--detect-junk` etichetta solo le righe `NULL` (ed è eseguito automaticamente al termine di ogni scansione), mentre `--recompute-junk` rivaluta l'intera libreria. Popola `photos.junk_kind`; la coda di revisione **Junk Sweep** del visualizzatore ([VIEWER.md](VIEWER.md#pulizia-degli-scarti)) la consulta.

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
      "receipt": ["a photo of a receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Esegue il rilevamento di spazzatura durante `--detect-junk` / `--recompute-junk` e al termine della scansione |
| `prompt_template` | `"{desc}"` | Stringa di formato applicata a ogni prompt (`{desc}` = il prompt); identità per impostazione predefinita poiché i prompt sono frasi complete |
| `pooling` | `"max"` | Raggruppa i coseni per prompt in un punteggio per tipo, tramite `max` (miglior prompt singolo, più discriminante) o `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Coseno max-pooled minimo perché il miglior tipo di spazzatura venga considerato (i coseni CLIP/`open_clip` sono più bassi di quelli SigLIP/`transformers`, da cui una soglia propria per ciascun backend) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Quanto il miglior tipo di spazzatura deve superare il miglior prompt di contrasto `not_junk` prima che la foto venga segnalata |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinonimi di prompt]}`; aggiungi, rimuovi o rinomina i tipi liberamente — la colonna e la coda del visualizzatore seguono la configurazione |
| `not_junk_prompts` | 6 prompt fotografici | Insieme di contrasto che descrive fotografie autentiche; il filtro che tiene le foto genuine fuori dalla coda |

## VLM Backend

Sceglie dove viene eseguito il modello visione-linguaggio per didascalie/tag. `local` (predefinito) usa il percorso transformers Qwen in-process, incluso nei profili VRAM 16gb/24gb — nessun cambiamento per le installazioni esistenti. I due backend remoti puntano Facet verso un server esterno così che la generazione di didascalie e il tagging VLM funzionino sui **profili legacy/8gb che non includono alcun VLM locale**: quando è selezionato un backend remoto, le funzionalità VLM non dipendono più dal profilo VRAM.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `type` | `"local"` | Backend: `local` (transformers Qwen in-process), `ollama` (API REST nativa di Ollama), oppure `openai_compatible` (qualsiasi endpoint di chat completions compatibile OpenAI — LM Studio, vLLM, OpenRouter) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base del server Ollama; l'immagine viene inviata come base64 a `POST /api/generate` |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag del modello Ollama (deve essere un modello vision già scaricato sul server) |
| `ollama.timeout_seconds` | `120` | Timeout per richiesta per le chiamate Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base compatibile OpenAI **incluso il suffisso `/v1`**; le richieste vanno a `{base_url}/chat/completions` con l'immagine come URI di dati `image_url` |
| `openai_compatible.api_key` | `""` | Token bearer inviato come `Authorization: Bearer <chiave>`; lascia vuoto per i server locali senza autenticazione |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nome del modello passato all'endpoint |
| `openai_compatible.timeout_seconds` | `120` | Timeout per richiesta per le chiamate compatibili OpenAI |

Il backend condiviso guida la generazione delle didascalie (`--generate-captions` e l'endpoint su richiesta `/api/caption`), la critica VLM (`/api/critique?mode=vlm`), il ri-tagging VLM (`--recompute-tags-vlm`) e lo spareggio VLM dei momenti narrativi. Un fallimento di richiesta remota viene riportato come un fallimento per foto (registrato, tag vuoti / nessuna didascalia) e non fa mai fallire l'esecuzione. Il tagging durante la scansione usa ancora il tagger proprio del profilo; esegui `--recompute-tags-vlm` per applicare un backend remoto a una libreria esistente.

## AI Critique

Configurazione del prompt per la critica basata su VLM (profili 16gb/24gb). La critica inserisce la scomposizione completa delle regole, le penalità e l'EXIF in un prompt a scala configurabile, presenta la risposta come Osservazione / Valutazione / Suggerimenti e la memorizza nella cache per foto in `photos.vlm_critique` (tradotta su richiesta in `vlm_critique_translated`). Viene eseguita sulla miniatura memorizzata, così i file RAW vengono criticati correttamente invece di fallire silenziosamente; `refresh` la rigenera.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Budget di token per la generazione della critica VLM strutturata |

Vedi [Galleria web — Critica IA](VIEWER.md#critica-ia).

## Distortion Attributes

Etichettatura delle distorsioni zero-shot, solo a scopo indicativo. `--recompute-distortions` valuta ogni foto rispetto a prompt contrastivi in stile ExIQA sul suo embedding CLIP/SigLIP memorizzato e memorizza i probabili difetti (sfocatura da movimento, dominante di colore, eccessiva nitidezza, …) in una colonna JSON indicativa. Non alimenta mai l'aggregato; le etichette appaiono come chip di avviso nella finestra di critica.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Calcola gli attributi di distorsione durante `--recompute-distortions` |
| `top_n` | `5` | Numero massimo di etichette di distorsione mantenute per foto |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura softmax sui punteggi dei prompt contrastivi, per backend di embedding (come per `narrative_moments`, i coseni di open_clip e transformers hanno scale diverse) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilità minima perché un'etichetta di distorsione venga mantenuta |
| `vocabulary` | `{}` | Override facoltativo dell'insieme di prompt di distorsione integrato (`{attributo: [sinonimi di prompt]}`); vuoto = valori predefiniti del modulo |

## Skin Tone

Naturalezza del tono della pelle nei ritratti (solo a scopo indicativo). `--recompute-skin-tone` campiona la croma CIELAB delle guance dalle miniature dei volti + punti di riferimento memorizzati e ne misura la distanza CIEDE2000 da un locus della pelle a temperatura di colore correlata, segnalando i ritratti la cui pelle deriva verso il verde / magenta / blu / giallo. Non alimenta mai l'aggregato; il risultato appare come nota sul tono della pelle nella finestra di critica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Delta CIEDE2000 minimo tra la croma della pelle misurata e il locus della pelle prima che venga segnalata una dominante di colore |

## Immich Sync

Sincronizzazione unidirezionale delle valutazioni a stelle e dei preferiti di Facet verso un server [Immich](https://immich.app/) tramite la sua API REST. Gli asset vengono risolti tramite `originalPath` attraverso le mappature di prefisso di percorso configurate, in un unico passaggio di ricerca in blocco. Eseguila con `--immich-sync` (verifica prima con `--immich-test`); vedi [Comandi — Immich Sync](COMMANDS.md#immich-sync).

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `url` | `""` | URL di base del server Immich (es. `http://nas:2283`) |
| `api_key` | `""` | Chiave API di Immich, inviata come intestazione `x-api-key` |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Riscritture di prefisso dai percorsi di Facet ai valori `originalPath` di Immich; il primo `facet_prefix` corrispondente viene sostituito con il suo `immich_prefix` quando si risolve un asset |
| `push.ratings` | `true` | Invia le valutazioni a stelle. La politica di Immich sicura per le versioni viene rispettata — viene scritto solo 1–5, mai 0/−1 |
| `push.favorites` | `true` | Invia il contrassegno di preferito |
| `push.top_picks_album` | `""` | Nome facoltativo di un album Immich che raccoglie le foto inviate sopra la soglia di valutazione. Vuoto = nessun album |
| `push.top_picks_min_rating` | `4` | Valutazione a stelle minima perché una foto venga aggiunta a `top_picks_album` |
| `timeout_seconds` | `30` | Timeout REST per richiesta |

`--immich-sync` rispetta `--dry-run` (risolve ogni asset ma non scrive nulla) e `--user` (invia le valutazioni di `user_preferences` di quell'utente in modalità multiutente). Solo REST — Facet non tocca mai il database di Immich.

## Timeline

Impostazioni per la vista timeline cronologica:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `photos_per_group` | `30` | Numero di foto caricate per gruppo di data nella vista timeline. Valori più alti mostrano più foto per data ma aumentano il peso della pagina. |

## Map

Impostazioni per la vista mappa interattiva:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Livello di zoom al quale i marcatori individuali sostituiscono i cluster. Valori più bassi mostrano i marcatori individuali prima (più dettaglio a zoom più ampio). Intervallo: 1 (mondo) a 18 (strada). |

## Translation

Impostazioni per la traduzione AI delle didascalie tramite MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `target_language` | `"fr"` | Codice della lingua di destinazione per `--translate-captions`. Supportati: `fr` (francese), `de` (tedesco), `es` (spagnolo), `it` (italiano), `pt` (portoghese brasiliano). Usa i modelli Helsinki-NLP MarianMT (CPU, nessuna GPU richiesta). |

## Aesthetic CLIP (R2)

Punteggio estetico supplementare derivato dagli embedding CLIP/SigLIP memorizzati in cache tramite proiezione testuale. I prompt sono regolabili dall'utente per il benchmarking AVA — vedi `scripts/benchmark_aesthetic.py` per misurare l'impatto sull'SRCC di qualsiasi modifica.

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

Gli array vuoti ricadono sui valori predefiniti del modulo integrati in `analyzers/aesthetic_clip.py`. Non regolare questi valori senza rieseguire il benchmark AVA — i valori predefiniti ottengono un SRCC ~0,52 su `ava_test/` e le modifiche possono facilmente regredire a ~0,30.

## Adding alternative VLM tagger / critique models (R3)

La chiave `tagging_model` di ogni profilo VRAM (es. `qwen3.5-2b`) si associa a una voce di modello nella stessa sezione `models`. Per sperimentare con un VLM diverso (Pixtral-12B, InternVL-2.5, ecc.):

1. Aggiungi una voce di modello sotto `models`:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Fai puntare un profilo a essa:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Esegui `python facet.py --recompute-tags-vlm` per ri-taggare.

Nessuna modifica al codice necessaria. Convalida la qualità con un confronto affiancato su ~30 foto prima di promuoverlo a predefinito.

## Share Secret

Stringa esadecimale di 64 caratteri generata automaticamente per i token di sessione/condivisione:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Generata automaticamente al primo avvio se non presente.
