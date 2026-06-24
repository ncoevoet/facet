# Riferimento di configurazione

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · **Italiano** · [Español](../es/CONFIGURATION.md)

Tutte le impostazioni si trovano in `scoring_config.json`. Dopo averle modificate, esegui `python facet.py --recompute-average` per aggiornare i punteggi (non serve la GPU).

## Indice

- [Utenti](#utenti)
- [Scansione](#scansione)
- [Categorie](#categorie)
- [Punteggio](#punteggio)
- [Soglie](#soglie)
- [Composizione](#composizione)
- [Aggiustamenti EXIF](#aggiustamenti-exif)
- [Esposizione](#esposizione)
- [Penalità](#penalità)
- [Normalizzazione](#normalizzazione)
- [Modelli](#modelli)
- [Modelli di valutazione della qualità](#modelli-di-valutazione-della-qualità)
- [Elaborazione](#elaborazione)
- [Rilevamento raffiche](#rilevamento-raffiche)
- [Punteggio delle raffiche](#punteggio-delle-raffiche)
- [Rilevamento duplicati](#rilevamento-duplicati)
- [Rilevamento volti](#rilevamento-volti)
- [Clustering dei volti](#clustering-dei-volti)
- [Elaborazione dei volti](#elaborazione-dei-volti)
- [Rilevamento monocromatico](#rilevamento-monocromatico)
- [Tagging](#tagging)
- [Tag autonomi](#tag-autonomi)
- [Analisi](#analisi)
- [Galleria web](#galleria-web)
- [Prestazioni](#prestazioni)
- [Archiviazione](#archiviazione)
- [Plugin](#plugin)
- [Capsule](#capsule)
- [Gruppi di somiglianza](#gruppi-di-somiglianza)
- [Cronologia](#cronologia)
- [Mappa](#mappa)
- [Traduzione](#traduzione)

---

## Utenti

Modalità multi-utente opzionale. Quando la chiave `users` è presente (con almeno un utente), l'autenticazione a password unica viene sostituita dal login per singolo utente.

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
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Generato dal comando CLI `--add-user`. |
| `display_name` | string | Mostrato nell'intestazione dell'interfaccia |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directory di foto private per questo utente |

### Directory condivise

La chiave `shared_directories` (allo stesso livello degli oggetti utente) elenca le directory visibili a tutti gli utenti.

### Ruoli

| Ruolo | Vede proprie + condivise | Valuta/preferito | Gestisce persone/volti | Avvia scansioni |
|------|:-:|:-:|:-:|:-:|
| `user` | sì | sì | no | no |
| `admin` | sì | sì | sì | no |
| `superadmin` | sì | sì | sì | sì |

### Aggiunta di utenti

Gli utenti vengono creati solo tramite CLI — non esiste un'interfaccia o un'API di registrazione:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Richiede la password, scrive l'hash in scoring_config.json
```

Dopo aver aggiunto un utente, modifica `scoring_config.json` per configurare le sue `directories`.

### Compatibilità con le versioni precedenti

- Nessuna chiave `users` = modalità legacy a utente singolo (comportamento invariato)
- `viewer.password` e `viewer.edition_password` vengono ignorati in modalità multi-utente
- Le valutazioni esistenti nella tabella `photos` restano per la modalità a utente singolo; usa `--migrate-user-preferences` per copiarle

---

## Scansione

Controlla il comportamento di scansione delle directory.

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

## Categorie

Array di definizioni di categoria. Vedi [Punteggio](SCORING.md) per la documentazione dettagliata sulle categorie.

Ogni categoria ha:
- `name` - Identificatore della categoria
- `priority` - Più basso = priorità più alta (valutato per primo)
- `filters` - Condizioni di corrispondenza
- `weights` - Pesi delle metriche di punteggio (devono sommare a 100)
- `modifiers` - Aggiustamenti del comportamento
- `tags` - Vocabolario CLIP per la corrispondenza basata sui tag

---

## Punteggio

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

## Soglie

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
| `blink_penalty_percent` | `50` | Moltiplicatore del punteggio quando viene rilevato un battito di ciglia (0.5x) |
| `night_luminance_threshold` | `0.15` | Luminanza media sotto questo valore = notte |
| `night_iso_threshold` | `3200` | ISO superiore a questo valore = scarsa illuminazione |
| `long_exposure_shutter_threshold` | `1.0` | Otturatore > 1s = lunga esposizione |
| `astro_shutter_threshold` | `10.0` | Otturatore > 10s = astrofotografia |

---

## Composizione

Punteggio compositivo basato su regole (usato quando SAMP-Net non è attivo).

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

## Aggiustamenti EXIF

Aggiustamenti automatici del punteggio basati sulle impostazioni della fotocamera.

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
| `aperture_isolation_boost` | `true` | Aumenta l'isolamento per aperture ampie (f/1.4-f/2.8) |

---

## Esposizione

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
| `shadow_clip_threshold_percent` | `15` | Segnala se > 15% dei pixel sono nero puro |
| `highlight_clip_threshold_percent` | `10` | Segnala se > 10% dei pixel sono bianco puro |
| `silhouette_detection` | `true` | Rileva le silhouette intenzionali |

---

## Penalità

Penalità sul punteggio per problemi tecnici.

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
| `oversaturation_pixel_percent` | `5` | Riservato per il rilevamento a livello di pixel |
| `oversaturation_penalty_points` | `0.5` | Penalità per sovrasaturazione |

**Formula della penalità per il rumore:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalizzazione

Controlla come le metriche grezze vengono scalate in punteggi 0-10.

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
| `percentile_target` | `90` | 90° percentile = punteggio di 10.0 |
| `per_category` | `true` | Normalizzazione specifica per categoria |
| `category_min_samples` | `50` | Numero minimo di foto per la normalizzazione per categoria |

---

## Modelli

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
    "florence_2_large": {
      "model_path": "florence-community/Florence-2-large",
      "torch_dtype": "float32",
      "vlm_batch_size": 4,
      "max_new_tokens": 256
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
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Esegue la salienza del soggetto BiRefNet per questo profilo |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modello di embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) o `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Dimensioni dell'embedding (1152 per SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Somiglianza coseno CLIP minima per la corrispondenza di un tag |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modello CLIP legacy (profili legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesi pre-addestrati legacy |
| `clip_legacy.embedding_dim` | `768` | Dimensioni dell'embedding legacy |
| `clip_legacy.similarity_threshold_percent` | `22` | Soglia di corrispondenza dei tag per CLIP legacy |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Percorso HuggingFace (VLM di composizione 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modello di tagging per il profilo 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Immagini per batch di inferenza VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modello di tagging per il profilo 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Immagini per batch di inferenza VLM |
| `florence_2_large.model_path` | `"florence-community/Florence-2-large"` | Modello Florence-2 (tagger alternativo) |
| `florence_2_large.vlm_batch_size` | `4` | Immagini per batch di inferenza Florence-2 |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modello di salienza BiRefNet |
| `saliency.resolution` | `1024` | Risoluzione di inferenza |
| `saliency.mask_threshold` | `0.3` | Soglia sigmoide per la maschera binaria del soggetto |
| `saliency.min_subject_pixels` | `50` | Pixel minimi del soggetto per considerare un soggetto come rilevato |
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

## Modelli di valutazione della qualità

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
| `prefer_llm` | `false` | Preferisce uno scorer basato su LLM quando ne è disponibile uno |

### Modelli di qualità disponibili

SRCC = Spearman Rank Correlation Coefficient sul benchmark KonIQ-10k (1.0 = perfetto).

| Modello | SRCC | VRAM | Note |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Predefinito (`auto`); backbone ResNet50 con attenzione top-down |
| `hyperiqa` | 0.90 | ~2GB | Iper-rete, adattiva al contenuto |
| `dbcnn` | 0.90 | ~2GB | CNN a doppio ramo (distorsioni sintetiche + autentiche) |
| `musiq` | 0.87 | ~2GB | Transformer multi-scala; gestisce qualsiasi risoluzione |
| `clipiqa+` | 0.86 | ~4GB | CLIP con prompt di qualità appresi |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 legacy + testa MLP |

### Cambiare modello di qualità

1. Modifica `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Rivaluta le foto esistenti (opzionale):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Elaborazione

Impostazioni unificate di elaborazione per l'elaborazione GPU in batch e la modalità multi-passaggio.

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

**`gpu_batch_size`** - Quante immagini vengono elaborate insieme sulla GPU in un singolo passaggio in avanti. Limitato dalla VRAM. Regolato automaticamente: ridotto quando la memoria GPU supera il limite.

**`ram_chunk_size`** - Quante immagini vengono memorizzate in cache nella RAM tra i passaggi del modello (solo modalità multi-passaggio). Riduce l'I/O su disco caricando le immagini una sola volta per blocco. Limitato dalla RAM di sistema. Regolato automaticamente: ridotto quando la memoria di sistema supera il limite.

### Riferimento delle impostazioni

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mode` | `"auto"` | Modalità di elaborazione: `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Immagini per batch GPU (limitato dalla VRAM) |
| `ram_chunk_size` | `32` | Immagini per blocco RAM (multi-passaggio) |
| `num_workers` | `4` | Thread di caricamento delle immagini |
| `load_workers` | `num_workers` | Thread di caricamento dei blocchi multi-passaggio (limitati a 8, `1` = sequenziale) |
| `raw_decode_concurrency` | `0` (auto) | Decodifiche RAW simultanee massime; dimensionate automaticamente da CPU/RAM (1-4), `1` = completamente serializzato |
| `raw_decode_timeout_seconds` | `120` | Abbandona una decodifica RAW bloccata dopo questo ritardo (`0` = disabilitato); la scansione fallisce rapidamente dopo blocchi ripetuti |
| `exif_prefetch` | `true` | Modalità single-pass: precarica gli EXIF in background invece di bloccare il thread GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Abilita la regolazione automatica |
| `monitor_interval_seconds` | `5` | Intervallo di controllo delle risorse |
| `tuning_interval_images` | `32` | Riregola ogni N immagini |
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
| `face_padding_ratio` | `0.3` | Margine attorno ai ritagli dei volti |

### Modalità di elaborazione

| Modalità | Descrizione |
|------|-------------|
| `auto` | Seleziona automaticamente multi-pass o single-pass in base alla VRAM |
| `multi-pass` | Caricamento sequenziale dei modelli (funziona con VRAM limitata) |
| `single-pass` | Tutti i modelli caricati contemporaneamente (richiede VRAM elevata) |

### Come funziona il multi-passaggio

Invece di caricare tutti i modelli contemporaneamente, il multi-passaggio:

1. Carica le immagini in blocchi RAM (predefinito `ram_chunk_size`: 32)
2. Per ogni blocco, esegue i modelli in sequenza: carica modello → elabora blocco → scarica modello
3. Combina i risultati in un passaggio finale di aggregazione

Ogni immagine viene caricata una sola volta per blocco e i passaggi vengono raggruppati per adattarsi alla VRAM disponibile, così i VLM più grandi per tagger/composizione funzionano anche con VRAM limitata.

### Comportamento della regolazione automatica

Il sistema monitora l'utilizzo delle risorse e si adatta:

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
# Predefinito: multi-pass automatico con raggruppamento ottimale
python facet.py /path/to/photos

# Forza single-pass (tutti i modelli caricati contemporaneamente)
python facet.py /path --single-pass

# Esegue solo un passaggio specifico
python facet.py /path --pass quality       # Solo TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (merito estetico)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualità + distorsione)
python facet.py /path --pass tags          # Solo il tagger configurato
python facet.py /path --pass composition   # Solo SAMP-Net
python facet.py /path --pass faces         # Solo InsightFace
python facet.py /path --pass embeddings    # Solo embedding CLIP/SigLIP
python facet.py /path --pass saliency      # Salienza del soggetto BiRefNet

# Elenca i modelli disponibili
python facet.py --list-models
```

---

## Rilevamento raffiche

Raggruppa le foto simili scattate in rapida successione.

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
| `similarity_threshold_percent` | `70` | Soglia di somiglianza dell'hash dell'immagine |
| `time_window_minutes` | `0.8` | Tempo massimo tra le foto |
| `rapid_burst_seconds` | `0.4` | Le foto entro questo intervallo vengono raggruppate automaticamente |

---

## Punteggio delle raffiche

Pesi usati dalla selezione delle raffiche per calcolare un punteggio composito che seleziona lo scatto migliore all'interno di ciascun gruppo di raffica. I pesi dovrebbero sommare a 1.0.

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
| `weight_blink` | `0.15` | Peso della penalità per i battiti di ciglia rilevati (più alto = penalità più forte) |

---

## Rilevamento duplicati

Rileva le foto duplicate a livello globale tramite il confronto di hash percettivo (pHash).

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
| `similarity_threshold_percent` | `90` | Soglia pHash rigida (90% = distanza di Hamming <= 6 su 64 bit); usata come unico criterio quando manca un embedding per una delle due foto |
| `prefilter_hamming` | `12` | Soglia di Hamming permissiva di fase 1 per l'insieme di candidati quando entrambe le foto hanno embedding (forzata a essere >= la soglia rigida) |
| `embedding_cosine_threshold` | `0.90` | Soglia coseno SigLIP/CLIP di fase 2: un candidato a pHash permissivo viene unito solo quando il coseno >= di questo valore |

Il rilevamento è a due fasi: candidati a pHash permissivo (recall) confermati da una soglia coseno di embedding stretta (precisione). Le foto senza embedding ricadono sul criterio rigido basato solo su pHash, quindi il comportamento è invariato quando gli embedding sono assenti.

Esegui `python facet.py --detect-duplicates` per rilevare e raggruppare i duplicati. Esegui `python facet.py --sweep-dedup-thresholds [labels.json]` per valutare la soglia coseno — con un JSON di etichette stampa una tabella di precisione/recall, altrimenti la distribuzione coseno dei candidati e quante collisioni a pHash rigido la soglia rifiuta.

---

## Livello IQA esteso (opzionale)

Scorer di qualità pesanti/sperimentali, **disattivati per impostazione predefinita** e **mai un sostituto di TOPIQ** — aggiungono colonne supplementari solo quando esplicitamente abilitati. Quando abilitati, gli scorer estesi vengono eseguiti **durante una normale scansione** e scrivono le proprie colonne; un errore di caricamento/VRAM viene registrato e la colonna viene lasciata a `NULL` (la scansione non si interrompe mai).

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
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA basata su LLM Q-Align (supportata da pyiqa). `"4bit"` (~6-8GB VRAM) è la scelta pratica su una scheda da 16GB; `"8bit"` ~12-14GB; piena precisione (`true`) richiede 16GB+. 4-/8-bit richiedono `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (testa SigLIP, ~2GB). Richiede il pacchetto `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU da 16GB+; altrimenti saltata e lasciata a NULL). |

**Installa le dipendenze opzionali** per ciò che abiliti: `pip install -e .[iqa-extended]` (aggiunge `aesthetic-predictor-v2-5` + `bitsandbytes`), oppure scommenta le righe corrispondenti in `requirements.txt`. Q-Align stesso è incluso in `pyiqa`; DeQA-Score viene scaricato tramite `transformers`.

Quando abilitata, ogni metrica è esposta all'aggregato ponderato ma per impostazione predefinita ha peso 0, quindi `--recompute-average` è identico byte per byte finché non le assegni un peso. Esegui `python facet.py --eval-iqa-srcc` per misurare quanto bene ciascuna metrica classifica la tua libreria rispetto alle tue valutazioni a stelle.

**Visualizzazione nella galleria.** Quando una di queste colonne è popolata, la galleria mostra il valore nel pannello **Qualità** del dettaglio foto (`Q-Align`, `Aesthetic V2.5`, `DeQA`) ed espone un cursore di intervallo corrispondente nella barra laterale dei filtri della galleria sotto **Qualità estesa** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Le foto scansionate prima dell'abilitazione del livello hanno semplicemente `NULL` in queste colonne e non sono interessate dai filtri.

**Robustezza.** DeQA-Score carica codice remoto `trust_remote_code` la cui firma forward varia tra le revisioni dei checkpoint; il suo scorer è difensivo — qualsiasi errore di previsione (firma errata, forma di output inattesa, OOM) viene intercettato e il `deqa_score` dell'immagine viene lasciato a `NULL` invece di far crashare la scansione.

---

## Rilevamento volti

Impostazioni di rilevamento volti InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confidenza di rilevamento minima |
| `min_face_size` | `20` | Dimensione minima del volto in pixel |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio per il rilevamento del battito di ciglia |
| `min_faces_for_group` | `4` | Numero minimo di volti per classificare come ritratto di gruppo (ricalcolato con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Carica il modulo InsightFace `landmark_3d_68` per l'estrazione della posa della testa (yaw/pitch/roll). Costa ~5MB di pesi ONNX aggiuntivi. Attualmente informativo; future raffinazioni di profilo/silhouette lo leggeranno. |

---

## Clustering dei volti

Clustering HDBSCAN per il riconoscimento facciale.

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
| `min_faces_per_person` | `2` | Numero minimo di foto per persona |
| `min_samples` | `2` | Parametro min_samples di HDBSCAN |
| `auto_merge_distance_percent` | `15` | Unione automatica entro questa distanza |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Dimensione della foglia dell'albero (solo CPU) |
| `use_gpu` | `"auto"` | Modalità GPU: `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Somiglianza dei centroidi per la corrispondenza |
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

## Elaborazione dei volti

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
| `crop_padding` | `0.3` | Rapporto di margine per i ritagli dei volti |
| `use_db_thumbnails` | `true` | Usa le miniature archiviate |
| `face_thumbnail_size` | `640` | Dimensione della miniatura in pixel |
| `face_thumbnail_quality` | `90` | Qualità JPEG |
| `extract_workers` | `2` | Worker di estrazione paralleli |
| `extract_batch_size` | `16` | Dimensione del batch di estrazione |
| `refill_workers` | `4` | Worker per il riempimento delle miniature |
| `refill_batch_size` | `100` | Dimensione del batch di riempimento |
| **auto_tuning** | | |
| `enabled` | `true` | Abilita la regolazione basata sulla memoria |
| `memory_limit_percent` | `80` | Limite di utilizzo della memoria |
| `min_batch_size` | `8` | Dimensione minima del batch |
| `monitor_interval_seconds` | `5` | Intervallo di controllo |

---

## Rilevamento monocromatico

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
| `saturation_threshold_percent` | `5` | Saturazione media < 5% = monocromatico |

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
| `clip` | 0 (riusa gli embedding) | Atmosfera/mood (dramatic, golden_hour, vintage) | Nessun caricamento di modello aggiuntivo; rilevamento di oggetti meno letterale |
| `qwen3.5-2b` | ~4GB | Scene strutturate (landscape, architecture, reflection) | Richiede transformers + VRAM aggiuntiva |
| `qwen3.5-4b` | ~8GB | Scene dettagliate con sfumature | VRAM maggiore; inferenza più lenta |
| `florence-2` | ~2GB | Oggetti letterali (sky, water, building) | Eccessivo tagging di termini generici; la corrispondenza basata su didascalia è fragile |

### Modelli di tagging predefiniti per profilo

| Profilo | Modello di tagging | Modello di embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Ri-tagging delle foto

```bash
python facet.py --recompute-tags       # Ri-tagga usando il modello configurato per profilo
python facet.py --recompute-tags-vlm   # Ri-tagga usando il tagger VLM
```

---

## Tag autonomi

Tag con liste di sinonimi non legati a nessuna categoria specifica. Sono disponibili per tutte le foto indipendentemente dall'assegnazione di categoria. Ogni chiave è il nome del tag; il valore è una lista di sinonimi per la corrispondenza CLIP/VLM.

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

Aggiungi nuovi tag autonomi fornendo una chiave e una lista di sinonimi. I tag definiti qui vengono uniti ai tag specifici delle categorie per formare il vocabolario completo dei tag.

---

## Analisi

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
| `quality_weight_threshold_percent` | `10` | Avvisa se il peso della qualità ≤ di questo |
| `correlation_dominant_threshold` | `0.5` | Avviso di "segnale dominante" |
| `category_min_samples` | `50` | Numero minimo di foto per categoria |
| `category_imbalance_threshold` | `0.5` | Avviso di divario di punteggio |
| `score_clustering_std_threshold` | `1.0` | Avvisa se la deviazione standard < di questo |
| `top_score_threshold` | `8.5` | Avvisa se l'aggregato massimo < di questo |
| `exposure_avg_threshold` | `8.0` | Avvisa se l'esposizione media > di questo |

---

## Galleria web

Visualizzazione e comportamento della galleria web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "uncertainty",
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
        "extra_args": []
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
    "path_mapping": {}
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `default_category` | `""` | Filtro di categoria predefinito |
| `edition_password` | `""` | Password per sbloccare la modalità di modifica (vuoto = disabilitato) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Minimo per l'ottimizzazione |
| `pair_selection_strategy` | `"uncertainty"` | Strategia predefinita |
| `show_current_scores` | `true` | Mostra i punteggi durante il confronto |
| **pagination** | | |
| `default_per_page` | `64` | Foto per pagina |
| **dropdowns** | | |
| `max_cameras` | `50` | Numero massimo di fotocamere nel menu a tendina |
| `max_lenses` | `50` | Numero massimo di obiettivi |
| `max_persons` | `50` | Numero massimo di persone |
| `max_tags` | `20` | Numero massimo di tag |
| `min_photos_for_person` | `10` | Nasconde dal menu a tendina le persone con meno foto |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Valore minimo di face_count perché un cluster raggruppato automaticamente appaia nella sezione "Da nominare" di `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome del binario darktable-cli o percorso assoluto |
| `darktable.profiles` | `[]` | Array di profili di esportazione darktable con nome (vedi sotto) |
| `darktable.profiles[].name` | *(obbligatorio)* | Nome visualizzato del profilo (usato nel menu di download e nel parametro API `profile`) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` per l'esportazione ad alta qualità |
| `darktable.profiles[].width` | *(omettere)* | Larghezza massima di output (omettere per risoluzione piena) |
| `darktable.profiles[].height` | *(omettere)* | Altezza massima di output (omettere per risoluzione piena) |
| `darktable.profiles[].extra_args` | `[]` | Argomenti CLI aggiuntivi (es. `["--style", "monochrome"]`) |
| **display** | | |
| `tags_per_photo` | `4` | Tag mostrati sulle schede |
| `card_width_px` | `168` | Larghezza della scheda |
| `image_width_px` | `160` | Larghezza dell'immagine |
| `image_jpeg_quality` | `96` | Qualità JPEG per la conversione RAW/HEIF in `/api/download` e `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Dimensione minima della miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Dimensione massima della miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Dimensione predefinita della miniatura (px) |
| `thumbnail_slider.step_px` | `8` | Incremento del cursore (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Dimensione della miniatura |
| `jpeg_quality` | `80` | Qualità JPEG |
| `crop_padding_ratio` | `0.2` | Margine del volto |
| `min_crop_size_px` | `20` | Dimensione minima del ritaglio |
| **quality_thresholds** | | |
| `good` | `6` | Soglia "buono" |
| `great` | `7` | Soglia "ottimo" |
| `excellent` | `8` | Soglia "eccellente" |
| `best` | `9` | Soglia "migliore" |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimo per Migliori scelte |
| `top_picks_min_face_ratio` | `0.2` | Rapporto volto per i pesi |
| `low_light_max_luminance` | `0.2` | Soglia di bassa luminosità |
| **defaults** | | |
| `type` | `""` | Filtro di tipo foto predefinito (es. `"portraits"`, `"landscapes"` o `""` per Tutte) |
| `sort` | `"aggregate"` | Colonna di ordinamento predefinita |
| `sort_direction` | `"DESC"` | Direzione di ordinamento predefinita (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Nasconde le foto con occhi chiusi per impostazione predefinita |
| `hide_bursts` | `true` | Mostra solo la migliore della raffica per impostazione predefinita |
| `hide_duplicates` | `true` | Nasconde le foto duplicate non principali per impostazione predefinita |
| `hide_details` | `true` | Nasconde i dettagli delle foto sulle schede per impostazione predefinita |
| `tooltip_mode` | `"hover"` | Attivazione del tooltip: `"hover"`, `"click"` o `"off"`. Sostituisce il precedente booleano `hide_tooltip`. |
| `hide_rejected` | `true` | Nasconde le foto rifiutate per impostazione predefinita |
| `gallery_mode` | `"mosaic"` | Layout predefinito della galleria (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origini CORS consentite per il server FastAPI. Aggiungi il tuo dominio o l'URL del reverse proxy quando ospiti da remoto. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(predefinito sicuro per SPA)_ | Valore dell'header Content-Security-Policy. Per impostazione predefinita usa una policy che consente le risorse proprie della SPA (script/stile del tema inline, Google Fonts, tile OpenStreetMap, API stesso-origine). Imposta a `""` per disabilitare, o fornisci una policy più restrittiva. |
| `security_headers.hsts` | `false` | Invia `Strict-Transport-Security`. Abilita solo quando la galleria è servita su HTTPS. |
| **Other** | | |
| `cache_ttl_seconds` | `60` | TTL della cache delle query |
| `notification_duration_ms` | `2000` | Durata del toast |

### Funzionalità

Attiva/disattiva le funzionalità opzionali per ridurre l'uso della memoria o semplificare l'interfaccia:

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
      "show_map": true
    }
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `show_similar_button` | `true` | Mostra il pulsante "Trova simili" sulle schede foto (usa numpy per la somiglianza CLIP) |
| `show_merge_suggestions` | `true` | Abilita la funzionalità di suggerimenti di unione nella pagina di gestione persone |
| `show_rating_controls` | `true` | Mostra i controlli di valutazione a stelle e preferito |
| `show_rating_badge` | `true` | Mostra il badge di valutazione sulle schede foto |
| `show_scan_button` | `false` | Mostra il pulsante di avvio scansione per gli utenti superadmin (richiede GPU sull'host della galleria) |
| `metrics_enabled` | `false` | Abilita l'endpoint Prometheus pubblico `GET /metrics`. Disabilitato per impostazione predefinita — espone conteggi di foto/persone/volti, dimensione del DB e memoria del processo; abilitalo solo quando l'endpoint è raggiungibile dalla rete dello scraper, non da internet pubblico. |
| `show_semantic_search` | `true` | Mostra la barra di ricerca semantica (ricerca testo-immagine usando embedding CLIP/SigLIP) |
| `show_albums` | `true` | Mostra la funzionalità Album (crea, gestisci e sfoglia album di foto) |
| `show_critique` | `true` | Mostra il pulsante di critica AI sulle schede foto (analisi del punteggio basata su regole) |
| `show_vlm_critique` | `false` | Abilita la modalità di critica con tecnologia VLM (richiede profilo VRAM 16gb/24gb) |
| `show_memories` | `true` | Mostra la finestra di dialogo dei Ricordi "Questo giorno" (foto scattate nella stessa data in anni precedenti) |
| `show_captions` | `true` | Mostra le didascalie generate dall'AI sulle schede foto |
| `show_timeline` | `true` | Mostra la vista Cronologia per la navigazione cronologica con navigazione per data |
| `show_map` | `false` | Mostra la vista Mappa con le posizioni delle foto basate su GPS (richiede Leaflet; disabilitato per impostazione predefinita poiché le foto potrebbero non avere dati GPS) |

**Ottimizzazione della memoria:** impostare `show_similar_button: false` impedisce il caricamento di numpy, riducendo l'impronta di memoria della galleria. La funzionalità di foto simili calcola la somiglianza coseno degli embedding CLIP, che richiede numpy.

### Mappatura dei percorsi

Mappa i percorsi del database ai percorsi del filesystem locale. Utile quando le foto sono state valutate su una macchina (es. Windows con percorsi UNC) ma la galleria viene eseguita su un'altra (es. NAS Linux con punti di montaggio).

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
| `path_mapping` | `{}` | Dizionario di prefisso di origine verso prefisso di destinazione. Quando si servono immagini a piena dimensione o critica VLM, i percorsi del database che iniziano con un prefisso di origine vengono riscritti per usare il prefisso di destinazione. |

**Come funziona:**
- Si applica solo quando si **leggono file dal disco** (serving di immagini a piena dimensione, download di file, critica VLM). I percorsi del database non vengono mai modificati.
- La normalizzazione tra barra rovesciata/barra in avanti è gestita automaticamente: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` corrispondono entrambi.
- Le mappature vengono valutate in ordine; il primo prefisso corrispondente vince.
- Le destinazioni della mappatura dei percorsi vengono incluse automaticamente nell'elenco delle directory di scansione consentite per i controlli di sicurezza multi-utente.

**Esempio:** un database popolato su Windows archivia percorsi come `\\NAS\Photos\2024\IMG_001.jpg`. Su Linux, la stessa condivisione è montata in `/mnt/nas/Photos`. Configura:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protezione con password

Protezione opzionale con password per la galleria:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando impostata, gli utenti devono autenticarsi prima di accedere alla galleria.

### Prestazioni della galleria

Sostituisce le impostazioni globali `performance` durante l'esecuzione della galleria. Utile per le distribuzioni su NAS a bassa memoria, dove la valutazione richiede risorse elevate ma la galleria no.

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
| `mmap_size_mb` | *(globale)* | Override della dimensione mmap SQLite per le connessioni della galleria. `0` disabilita mmap. |
| `cache_size_mb` | *(globale)* | Override della dimensione della cache SQLite per le connessioni della galleria |
| `pool_size` | `5` | Dimensione del pool di connessioni (ridurre per sistemi a bassa memoria) |
| `thumbnail_cache_size` | `2000` | Numero massimo di voci nella cache in memoria di ridimensionamento delle miniature |
| `face_cache_size` | `500` | Numero massimo di voci nella cache in memoria delle miniature dei volti |

Quando non impostata, la galleria usa i valori globali `performance`. Vedi [Distribuzione](DEPLOYMENT.md) per le impostazioni NAS consigliate.

---

## Prestazioni

Impostazioni delle prestazioni del database.

```json
{
  "performance": {
    "mmap_size_mb": 12288,
    "cache_size_mb": 64,
    "wal_checkpoint_minutes": 30,
    "slow_request_ms": 1000
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mmap_size_mb` | `12288` | Dimensione dell'I/O mappato in memoria SQLite |
| `cache_size_mb` | `64` | Dimensione della cache SQLite |
| `wal_checkpoint_minutes` | `30` | Intervallo in minuti per il `PRAGMA wal_checkpoint(TRUNCATE)` in background della galleria. Previene il gonfiamento del WAL nelle distribuzioni a lunga esecuzione. Imposta a `0` per disabilitare. |
| `slow_request_ms` | `1000` | Le richieste API della galleria più lente di questo numero di millisecondi vengono registrate a livello WARNING con un marcatore `SLOW`. Imposta a `0` per disabilitare. |

---

## Archiviazione

Controlla dove vengono archiviati le miniature e gli embedding. Per impostazione predefinita sono colonne BLOB nel database SQLite; la modalità filesystem li archivia invece come file su disco, riducendo la dimensione del database.

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
| `filesystem_path` | `"./storage"` | Directory di base per la modalità filesystem. Le miniature vengono archiviate in `<path>/thumbnails/` e gli embedding in `<path>/embeddings/`, organizzati in sottodirectory per hash del contenuto. |

**Dettagli della modalità filesystem:**
- I file sono organizzati per hash SHA-256 del percorso della foto, con sottodirectory di due caratteri per evitare troppi file in una directory (es. `thumbnails/a3/a3f8..._640.jpg`).
- L'eliminazione di una foto rimuove tutte le dimensioni di miniatura e i file di embedding associati.
- La directory viene creata automaticamente al primo utilizzo.

---

## Plugin

Sistema di plugin guidato da eventi per reagire agli eventi di valutazione. I plugin possono essere moduli Python, webhook o azioni integrate.

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
| `webhooks` | `[]` | Lista di endpoint webhook che ricevono payload JSON POST |
| `actions` | `{}` | Azioni integrate con nome attivate dagli eventi |

### Eventi supportati

| Evento | Attivazione | Payload |
|-------|---------|---------|
| `on_score_complete` | Dopo che ogni foto è stata valutata | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
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

Ogni webhook riceve un POST JSON con protezione SSRF (gli indirizzi privati/loopback sono bloccati):

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

Opzioni del webhook: `url` (obbligatorio), `events` (lista di nomi di evento), `min_score` (aggregato minimo per l'attivazione).

### Azioni integrate

| Azione | Descrizione | Opzioni |
|--------|-------------|---------|
| `copy_to_folder` | Copia la foto in una cartella | `folder`, `min_score` |
| `send_notification` | Registra una notifica | `min_score` |

### Endpoint API

| Metodo | Percorso | Descrizione |
|--------|------|-------------|
| `GET` | `/api/plugins` | Elenca plugin, webhook e azioni caricati |
| `POST` | `/api/plugins/test-webhook` | Invia un payload di prova a un URL webhook |

---

## Capsule

Diaporame di foto curati (presentazioni) raggruppati per tema. Le capsule vengono generate automaticamente dalla tua libreria di foto e memorizzate in cache con un TTL configurabile.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
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
| `min_aggregate` | `6.0` | Punteggio aggregato minimo per includere le foto nelle capsule |
| `max_photos_per_capsule` | `40` | Numero massimo di foto per capsula (la diversità MMR si applica sopra 5) |
| `max_photo_overlap` | `0.2` | Frazione massima di foto condivise tra due capsule prima che la deduplica ne rimuova una |
| `mmr_lambda` | `0.5` | Peso di diversità MMR: 0=massimizza la diversità, 1=massimizza la qualità |
| `freshness_hours` | `24` | TTL della cache e periodo di rotazione per le foto di copertina e le capsule seeded |
| `reverse_geocoding` | `true` | Abilita la geocodifica inversa offline per i titoli delle capsule di posizione/viaggio (richiede il pacchetto `reverse_geocoder`) |

### Tipi di capsula

| Tipo | Descrizione |
|------|-------------|
| `journey` | Viaggi rilevati tramite clustering GPS + intervalli temporali. I titoli includono il nome della destinazione quando la geocodifica è abilitata. |
| `faces_of` | Migliori foto di ogni persona riconosciuta |
| `seasonal` | Foto raggruppate per stagione + anno |
| `golden` | Top 1% per punteggio aggregato |
| `color_story` | Gruppi visivamente simili tramite clustering di embedding CLIP |
| `this_week` | "Questa settimana, anni fa" — Questo giorno esteso su ±3 giorni |
| `location` | Cluster di foto geotaggate con nomi di luogo da geocodifica inversa |
| `person_pair` | Coppie di persone con nome che appaiono insieme |
| `seeded` | Scoperta basata su seed tramite tempo, somiglianza, persona, tag, posizione, mood |
| `progress` | "La tua fotografia sta migliorando" dalle tendenze trimestrali dei punteggi |
| `color_palette` | "Colore del mese" dai profili di saturazione/monocromatici |
| `rare_pair` | Coppie di persone infrequenti in foto ad alto punteggio |
| `favorites` | Foto preferite raggruppate per anno e stagione |

### Capsule basate su dimensioni

Generate automaticamente dalle colonne del database:

| Dimensione | Raggruppa per |
|-----------|-----------|
| `year` | Anno estratto da date_taken |
| `month` | Anno-mese estratto da date_taken |
| `week` | Anno-settimana estratto da date_taken |
| `camera` | Modello di fotocamera |
| `lens` | Modello di obiettivo |
| `tag` | Tag delle foto (richiede la tabella `photo_tags`) |
| `day_of_week` | Giorno della settimana (domenica–sabato) |
| `composition` | Modello compositivo SAMP-Net (rule_of_thirds, horizontal, ecc.) |
| `focal_range` | Fasce di lunghezza focale: ultra grandangolo (<24mm), grandangolo (24–35mm), standard (36–70mm), ritratto (71–135mm), teleobiettivo (136–300mm), super teleobiettivo (300mm+) |
| `category` | Categoria di contenuto della foto (portrait, landscape, street, ecc.) |
| `time_of_day` | Fasce orarie: golden morning, morning, midday, afternoon, golden evening, night |
| `star_rating` | Valutazioni a stelle dell'utente (1–5 stelle) |

Vengono generate anche combinazioni cross-dimensionali (es. camera × year, focal_range × category, category × year).

### Transizioni della presentazione

Ogni tipo di capsula è associato a una transizione di diapositiva a tema:

| Transizione | Usata da | Effetto |
|-----------|---------|--------|
| `crossfade` | Predefinito | Scambio di opacità di 300ms |
| `slide` | journey, location, this_week | Scorre da destra (500ms) |
| `zoom` | faces_of, color_story | Scala 1.05→1.0 con dissolvenza (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1.0→1.08 per la durata della diapositiva |

### Geocodifica inversa

Le capsule di posizione e viaggio usano la geocodifica inversa offline tramite il pacchetto `reverse_geocoder` (dataset GeoNames locale, ~30MB, nessuna chiamata API). I risultati vengono memorizzati in cache nella tabella del database `location_names` a una risoluzione di griglia di 0.1° (~11km).

Installazione: `pip install reverse_geocoder`

Imposta `"reverse_geocoding": false` per disabilitare e ricadere sulla visualizzazione delle coordinate.

## Gruppi di somiglianza

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
| `default_threshold` | `0.85` | Somiglianza coseno minima (0.0–1.0) per considerare due foto come visivamente simili. Valori più bassi producono gruppi più grandi ma con minore somiglianza visiva. |
| `min_group_size` | `2` | Numero minimo di foto richiesto per formare un gruppo di somiglianza |
| `max_photos` | `10000` | Numero massimo di foto da caricare per il calcolo della somiglianza (costo O(n²)). Aumentalo per librerie più grandi a scapito del tempo di calcolo. |
| `max_group_size` | `50` | Numero massimo di foto per gruppo di somiglianza. I gruppi più grandi vengono suddivisi per mantenere l'interfaccia utilizzabile. |

## Cronologia

Impostazioni per la vista cronologica della timeline:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `photos_per_group` | `30` | Numero di foto caricate per gruppo di data nella vista Cronologia. Valori più alti mostrano più foto per data ma aumentano il peso della pagina. |

## Mappa

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

## Traduzione

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
| `target_language` | `"fr"` | Codice della lingua di destinazione per `--translate-captions`. Supportati: `fr` (francese), `de` (tedesco), `es` (spagnolo), `it` (italiano). Usa i modelli MarianMT di Helsinki-NLP (CPU, nessuna GPU richiesta). |

## CLIP estetico (R2)

Punteggio estetico supplementare derivato dagli embedding CLIP/SigLIP memorizzati in cache tramite proiezione testuale. I prompt sono regolabili dall'utente per il benchmark AVA — vedi `scripts/benchmark_aesthetic.py` per misurare l'impatto SRCC di qualsiasi modifica.

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

Gli array vuoti ricadono sui valori predefiniti del modulo integrati in `analyzers/aesthetic_clip.py`. Non regolarli senza rieseguire il benchmark AVA — i valori predefiniti ottengono SRCC ~0.52 su `ava_test/` e le modifiche possono facilmente regredire a ~0.30.

## Aggiunta di modelli VLM tagger / critica alternativi (R3)

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
2. Punta un profilo verso di esso:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Esegui `python facet.py --recompute-tags-vlm` per ri-taggare.

Nessuna modifica al codice necessaria. Convalida la qualità tramite un controllo a campione fianco a fianco su ~30 foto prima di promuoverlo a predefinito.

## Segreto di condivisione

Stringa esadecimale di 64 caratteri generata automaticamente per i token di sessione/condivisione:

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Generata automaticamente al primo avvio se non presente.
