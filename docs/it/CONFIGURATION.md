# Riferimento di configurazione

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · **Italiano** · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md) · [简体中文](../zh/CONFIGURATION.md)

Ogni impostazione è distribuita in `config/scoring_config.default.json`. Il tuo `scoring_config.json` la sovrascrive chiave per chiave — vedi [Valori predefiniti e il tuo override](#valori-predefiniti-e-il-tuo-override). Dopo una modifica, esegui `python facet.py --recompute-average` per aggiornare i punteggi (nessuna GPU necessaria).

## Indice

- [Valori predefiniti e il tuo override](#valori-predefiniti-e-il-tuo-override)
- [Utenti](#users)
- [Scansione](#scanning)
- [Categorie](#categories)
- [Contesti di punteggio](#contesti-di-punteggio)
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
- [Decodifica RAW](#decodifica-raw)
- [Mappatura dei toni HDR PQ](#mappatura-dei-toni-hdr-pq)
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
- [OCR](#ocr)
- [Timeline](#timeline)
- [Mappa](#map)
- [Traduzione](#translation)

---

## Valori predefiniti e il tuo override

`scoring_config.json` contiene **solo ciò che hai modificato**. Facet lo risolve sopra `config/scoring_config.default.json`, quindi qualunque cosa tu ometta mantiene il valore fornito. Un'installazione nuova non ha alcun `scoring_config.json` e funziona con i valori predefiniti.

Per aumentare il peso estetico dei ritratti e impostare una password di edizione, l'intero file è:

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

Come i due file vengono combinati:

- **Gli oggetti si fondono chiave per chiave.** `{"performance": {"mmap_size_mb": 4096}}` cambia solo quell'impostazione; `cache_size_mb` e ogni altra chiave di `performance` mantengono il valore fornito.
- **Gli array sostituiscono in blocco.** Un array `categories` nel tuo file sostituisce completamente quello fornito. L'ordine conta (`categories` è a prima corrispondenza vincente, `scoring_contexts.*.promote` è letto in ordine) e omettere una categoria dal tuo array la elimina.

Per cambiare un solo peso in una sola categoria, copia l'intero array `categories` da `config/scoring_config.default.json`, modificalo e conservalo nel tuo file.

### Aggiornare un'installazione esistente

Non c'è nulla da fare: un `scoring_config.json` completo di una versione precedente continua a funzionare. Qualunque scrittura di Facet sul file (salvare pesi o priorità nel visualizzatore, un cambio di soglia panorama, il primo login che aggiorna una password in chiaro, una scansione in cui `validate_weights` corregge i pesi) lo riscrive come override ed elimina ogni chiave uguale al predefinito fornito.

Per compattarlo su richiesta, con prima una copia di backup in `0600`:

```bash
python database.py --compact-config
```

Il risultato si risolve esattamente sulla stessa configurazione.

> **Nota:** Un valore uguale al predefinito fornito non resta nel tuo file. Se una versione successiva cambia quel predefinito, cambia anche il tuo comportamento. Per fissare un valore, deve essere diverso dal predefinito.


## Users

Modalità multiutente opzionale. Quando la chiave `users` contiene almeno un utente, il login per utente sostituisce l'autenticazione con password unica.

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
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`), generato da `--add-user` |
| `display_name` | string | Mostrato nell'intestazione dell'interfaccia |
| `role` | string | `user`, `admin` o `superadmin` |
| `directories` | array | Directory di foto private di questo utente (confronto: vedi [Directory condivise](#directory-condivise)) |

### Directory condivise

`shared_directories` (allo stesso livello degli oggetti utente) elenca le directory che ogni utente può vedere. Le voci di `directories` e `shared_directories` vengono confrontate con i percorsi memorizzati dallo scanner:

- La distinzione tra maiuscole e minuscole ASCII è ignorata su Windows e macOS, e per le voci UNC o con lettera di unità su qualsiasi host.
- Altrove (per esempio su Linux) le maiuscole contano: scrivi ogni voce esattamente come l'ha memorizzata lo scanner.
- Non gestiti: differenze di maiuscole non ASCII e un'unità mappata che l'host non sa risolvere.
- Una voce vuota non concede nulla.

### Ruoli

| Ruolo | Vede le proprie + condivise | Valuta/preferisce | Gestisce persone/volti | Avvia scansioni |
|------|:-:|:-:|:-:|:-:|
| `user` | sì | sì | no | no |
| `admin` | sì | sì | sì | no |
| `superadmin` | sì | sì | sì | sì |

### Aggiungere utenti

Gli utenti vengono creati solo dalla CLI; non esiste un'interfaccia o un'API di registrazione:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Richiede la password, scrive l'hash in scoring_config.json
```

Poi modifica `scoring_config.json` per impostare le sue `directories`.

### Compatibilità con le versioni precedenti

- Nessuna chiave `users` = modalità monoutente (comportamento invariato).
- `viewer.password` e `viewer.edition_password` vengono ignorate in modalità multiutente.
- Le valutazioni esistenti nella tabella `photos` restano per la modalità monoutente; `--migrate-user-preferences` le copia.

---

## Scanning

Controlla quali directory visita la scansione.

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Salta le directory il cui nome inizia con `.` |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | Glob di nomi di cartella saltati a qualsiasi profondità |

Note su `skip_directories`:
- I glob usano `fnmatch`, distinguono le maiuscole e confrontano solo il nome della cartella.
- I predefiniti coprono `@eaDir` di Synology (le sue miniature `SYNOPHOTO_THUMB_*.jpg`), `#recycle`, `#snapshot` e `@Recycle` di QNAP.
- L'elenco sostituisce quello predefinito; `[]` disattiva l'esclusione per nome. La radice della scansione non viene mai saltata.
- Le foto già indicizzate da queste cartelle restano nel database.

---

## Categories

Array di definizioni di categoria. Vedi [Punteggio](SCORING.md) per la guida completa alle categorie.

Ogni categoria ha:
- `name` - Identificatore della categoria
- `priority` - Più basso = priorità più alta (valutata per prima)
- `filters` - Condizioni di corrispondenza
- `weights` - Pesi delle metriche di punteggio (la somma deve essere 100)
- `modifiers` - Regolazioni del comportamento
- `tags` - Vocabolario CLIP per la corrispondenza basata sui tag

> **Pesi di forma e armonia cromatica.** Il blocco `weights` di ogni categoria ha cinque chiavi compilate da `--recompute-form`: `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` e `color_harmony_percent`. Sono fornite a `0`, quindi i punteggi non cambiano finché non ne assegni un peso (poi esegui `--recompute-average`). I pesi sommano comunque a 100.

> **`quality_percent` conta come `aesthetic`.** La qualità non ha un punteggio proprio, quindi `quality_percent` viene sommato ad `aesthetic_percent` prima del calcolo. Vedi [SCORING.md](SCORING.md).

> **La categoria `astro` inclusa richiede un fotogramma scuro.** Oltre a uno dei suoi tag richiede `luminance_max: 0.30` (luminanza media al massimo 0.30), quindi una scena luminosa etichettata `aurora` o `stars` non è `astro`. Se il tuo `scoring_config.json` ha un proprio array `categories`, la sua voce `astro` non riceve questo filtro: aggiungi `"luminance_max": 0.30` a `astro.filters`, oppure elimina l'array. `python facet.py --doctor` stampa un «Config notice» quando `astro` non ha `luminance_max`. Poi esegui `--recompute-average` (dopo un aggiornamento: prima `--recompute-silhouette`, poi `--recompute-average` due volte; vedi [COMMANDS.md](COMMANDS.md)).

---

## Contesti di punteggio

Un contesto di punteggio cambia quale categoria vince per un album o una foto. Promuove in testa alcune categorie dell'ordine globale di `categories` ed esclude le altre; le restanti mantengono il proprio ordine di priorità. Usalo quando l'ordine globale sceglie la categoria sbagliata per uno scatto: un fotogramma di danza in controluce taggato `sports` viene catturato da `silhouette` (priorità 42) prima di `sports` (priorità 71). I cursori dei pesi non possono risolverlo, perché cambiano solo come viene valutata la categoria selezionata.

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| Campo | Descrizione |
|-------|-------------|
| `label_key` | Chiave i18n per il nome visualizzato del contesto |
| `promote` | Categorie spostate in testa all'ordine di valutazione, nell'ordine indicato |
| `excluded` | Categorie mai corrispondenti sotto questo contesto |
| `suggest_from_moments` | Valori di `narrative_moment` che suggeriscono questo contesto per un album (`GET /api/albums/{id}/suggested_context`, vedi [VIEWER.md](VIEWER.md)) |

**Ordine effettivo** = `promote` (in ordine) → l'ordine di priorità globale senza i nomi promossi ed esclusi → `default` (la categoria di ripiego, priorità 999) per ultima.

- Un nome presente sia in `promote` sia in `excluded` viene escluso.
- `default` non può mai essere promossa o esclusa.
- Nessun contesto, o un nome sconosciuto, usa il semplice ordine globale (un nome sconosciuto registra un avviso).
- `python facet.py --validate-categories` segnala nomi di categoria sconosciuti, nomi presenti in entrambi gli elenchi e voci `suggest_from_moments` che non sono chiavi di `narrative_moments.event_types.<default_event_type>`. Altrimenti i refusi passano in silenzio.

Preset forniti (`default` è vuoto, quindi nulla cambia finché non assegni un contesto):

| Contesto | Promuove | Esclude | Suggerito dai momenti |
|---------|----------|----------|------------------------|
| `default` | — | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` | `sports`, `concert`, `nightlife` |
| `party_event` | `group_portrait`, `candid`, `food` | — | `celebration`, `group_gathering`, `dining` |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — | `portrait`, `children` |
| `wildlife` | `wildlife` | — | `nature_wildlife`, `pets` |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — | `scenic_landscape`, `mountains`, `snow_winter` |
| `motorsport` | `sports`, `vehicle` | `silhouette` | `sports`, `road_vehicle` |

### Aggiungere un proprio contesto

Aggiungi una chiave sotto `scoring_contexts` e funziona come un preset fornito: puoi assegnarla a un album e modificarla nella scheda **Contesto di punteggio**.

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

Se `label_key` non ha traduzione, il selettore mostra il **`name`** del contesto (per esempio `dance_comp`). Aggiungi la chiave a tutti e sei i pacchetti `i18n/translations/*.json` per ottenere un'etichetta localizzata.

### Modificare un contesto

Nella scheda **Contesto di punteggio** del visualizzatore (riservata alla modalità edizione, `PUT /api/config/scoring_contexts/{name}`), trascina o sposta le categorie nell'elenco promosso, fai clic su una categoria per attivarne o disattivarne l'esclusione, poi salva.

- Sono modificabili solo `promote` e `excluded`; `label_key`, `suggest_from_moments` e gli altri contesti restano come erano.
- Il salvataggio viene rifiutato quando il contesto non esiste, quando una voce non è una categoria esistente, quando `default` compare in uno dei due elenchi o quando `promote` ripete un nome. Un nome in entrambi gli elenchi è accettato (vince `excluded`); una ripetizione in `excluded` viene compattata.
- Ogni salvataggio conserva una copia `.backup.<timestamp>` con marca temporale della configurazione.
- Modificare un contesto non ricategorizza le foto: esegui un ricalcolo subito dopo (vedi [Modificare le priorità richiede un ricalcolo](#riordinare-la-priorità-globale)). La scheda ha un pulsante **Ricalcola ora**.

### Assegnare un contesto

Assegna un contesto **per album** con `PUT /api/albums/{id}/scoring_context` (riservato alla modalità edizione).

- Si applica a ogni foto dell'album in quel momento, tranne alle foto il cui contesto hai impostato a mano.
- Una foto aggiunta in seguito a un album manuale eredita il contesto. Una nuova foto che corrisponde al filtro di un album intelligente no; richiama di nuovo `PUT` per riapplicarlo.
- Un album intelligente usa il proprio filtro salvato, non gli interruttori di nascondimento della galleria, quindi può coprire più foto di quante ne mostri la sua vista galleria.
- `DELETE /api/albums/{id}/scoring_context` rimuove il contesto dalle foto impostate da questo album. Le scelte manuali restano.
- Rimuovere foto da un album (`DELETE /api/albums/{id}/photos`) ne rimuove il contesto di questo album. Una foto ancora presente in un altro album con un contesto prende il contesto di quell'album.
- `GET /api/albums/{id}/suggested_context` propone un contesto a partire dal `narrative_moment` dominante dell'album, tramite `suggest_from_moments`. Non cambia nulla.

Per una singola foto ostinata, usa una **sovrascrittura categoria**: `POST /api/comparison/override_category` (riservato alla modalità edizione) imposta direttamente la categoria e `POST /api/comparison/clear_category_override` la rimuove. Una sovrascrittura prevale su qualsiasi contesto.

Le sovrascritture e i contesti sopravvivono alle riscansioni. Un filtro numerico continua a fallire quando il suo valore EXIF è mancante, qualunque sia il contesto — vedi [Punteggio — la trappola dei dati EXIF mancanti](SCORING.md#la-trappola-dei-dati-exif-mancanti).

### Riordinare la priorità globale

`GET|POST /api/config/category_priorities` (riservato alla modalità edizione) legge e salva l'ordine globale da cui parte ogni contesto. Il visualizzatore riordina i numeri di priorità esistenti invece di rinumerarli.

- `default` (priorità 999) resta sempre ultima e non può essere spostata.
- Una categoria con priorità mancante o duplicata riceve al salvataggio un nuovo valore oltre il massimo attuale.
- Ogni salvataggio conserva una copia `.backup.<timestamp>` con marca temporale di `scoring_config.json`; le 20 più recenti vengono mantenute.

**Cambiare le priorità richiede un ricalcolo.** Un riordino non cambia la `category` memorizzata di alcuna foto. Esegui `python facet.py --recompute-average`, oppure avvia `POST /api/scan/recompute` dal visualizzatore (riservato alla modalità edizione) e segui `GET /api/scan/recompute_status`.

- Un ricalcolo e una scansione non possono girare insieme: la CLI rifiuta, e il visualizzatore indica quale job detiene la libreria.
- Due scansioni avviate da un terminale ricevono solo un avviso (`--resume` rifiuta).
- Con `normalization.per_category` abilitato, un ricalcolo potrebbe dover essere eseguito due volte — vedi [Normalization](#normalization).

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

Soglie di punteggio. Resta solo `blink_penalty_percent`. Se una foto sia un ritratto, uno scatto notturno o una lunga esposizione lo decidono i `filters` di ciascuna categoria (vedi [Categories](#categories)), non questo blocco.

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `blink_penalty_percent` | `50` | Moltiplicatore del punteggio quando viene rilevato un battito di palpebre (0,5x) |

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
| `silhouette_detection` | `true` | Se `true`, una foto contrassegnata `is_silhouette` salta la penalità di clipping nel suo punteggio aggregato. Il flag in sé non è configurabile: deriva da una regola fissa basata sul volto (vedi [SCORING.md](SCORING.md)) |

---

## Penalties

Penalità al punteggio per problemi tecnici.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Rumore superiore a questo valore attiva la penalità |
| `noise_max_penalty_points` | `1.5` | Penalità massima per il rumore |
| `noise_penalty_per_sigma` | `0.3` | Punti per sigma oltre la soglia |
| `leading_lines_blend_percent` | `30` | Fusione nel comp_score |
| `oversaturation_threshold` | `0.9` | Soglia di saturazione media |
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


> **Nota:** Con `per_category` abilitato, un solo ricalcolo non basta a stabilizzare. I percentili sono raggruppati per la categoria *memorizzata* di ogni foto prima che il ricalcolo la riassegni. Dopo una modifica che sposta foto tra categorie (priorità, un contesto di punteggio, un override di categoria), esegui `--recompute-average` due volte.

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
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
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
        "composition_model": "samp-net",
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
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
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
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Profilo attivo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`); `FACET_VRAM_PROFILE` lo sovrascrive (vedi sotto) |
| `keep_in_ram` | `"auto"` | Mantiene i modelli in RAM tra i blocchi multi-passaggio (`"auto"`, `"always"`, `"never"`); `auto` controlla prima la RAM libera |
| `ram_cache_reserve_gb` | `4.0` (opzionale, assente dal file fornito) | RAM (GB) da lasciare libera accanto a un modello in cache con `"auto"` |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelli PyIQA da eseguire per questo profilo (tutti e quattro i profili eseguono il set completo) |
| `profiles.*.saliency_enabled` | `true` (tutti i profili) | Esegue la saliency del soggetto BiRefNet per questo profilo |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modello di embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) o `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Dimensioni dell'embedding (1152 per SigLIP 2) |
| `clip.tag_threshold_percent` | `8` | Similarità minima per una corrispondenza di **tag** con il tagger SigLIP 2 dei profili 16gb/24gb (sostituisce `similarity_threshold_percent`) |
| `clip.search_threshold_percent` | `5` | Similarità minima per la ricerca semantica (`GET /api/search`); numero intero `0-50` |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modello CLIP legacy (profili legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesi pre-addestrati legacy |
| `clip_legacy.embedding_dim` | `768` | Dimensioni dell'embedding legacy |
| `clip_legacy.tag_threshold_percent` | `8` | Stessa soglia dei tag per il tagger CLIP legacy/8gb; `tagging.max_tags` limita il numero |
| `clip_legacy.search_threshold_percent` | `15` | Soglia di ricerca semantica sul profilo legacy/8gb; numero intero `0-50` |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Modello per l'opt-in manuale `composition_model: "qwen2-vl-2b"` (nessun profilo lo usa) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modello di tagging per il profilo 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Immagini per batch di inferenza VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modello di tagging per il profilo 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Immagini per batch di inferenza VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modello di saliency BiRefNet |
| `saliency.resolution` | `1024` | Risoluzione di inferenza |
| `saliency.mask_threshold` | `0.3` | Soglia sigmoide per la maschera binaria del soggetto |
| `saliency.min_subject_pixels` | `50` | Pixel minimi del soggetto perché venga considerato rilevato |

Note:
- **`ram_cache_reserve_gb`:** un modello viene mantenuto solo finché la RAM libera supera la sua dimensione più questa riserva. `"always"` salta il controllo; `"never"` non mette nulla in cache. Deve essere un numero >= 0, altrimenti la scansione si ferma all'avvio. Sotto pressione di memoria la cache rilascia per primo il modello che servirà più tardi (vedi [Come funziona il multi-passaggio](#come-funziona-il-multi-passaggio)).
- **Soglie dei tag e della ricerca:** `tag_threshold_percent` governa il tagging (scansione, `--recompute-tags`, `tag_existing.py`). `search_threshold_percent` è il predefinito del cursore di ricerca 0-50% della galleria (`search_threshold_default` in `/api/config`). Il predefinito SigLIP `5` favorisce il richiamo: su un campione di 34 foto ha mantenuto tutte le 21 corrispondenze vere e ha lasciato passare 3 non corrispondenze su 13.

**Ricerca semantica e libreria incorporata con un profilo diverso:** `GET /api/search` sceglie l'encoder di testo e la sua `search_threshold_percent` da quello tra `clip` / `clip_legacy` che corrisponde alla dimensione di embedding *memorizzata*, non al `vram_profile` attivo. Una libreria incorporata con CLIP a 768 dimensioni e sfogliata su una macchina 16gb cerca quindi con `clip_legacy`. Se la dimensione memorizzata non corrisponde a nessuno dei due blocchi, viene usato il blocco del profilo attivo.

### Rilevamento automatico della VRAM

Quando `vram_profile` è `"auto"` (predefinito), Facet rileva la VRAM GPU all'avvio e sceglie il profilo più grande che ci sta:

| VRAM rilevata | Profilo selezionato |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Nessuna GPU | `legacy` (usa la RAM di sistema) |

Una GPU CUDA conta solo se PyTorch riesce a vederla. Senza dispositivi visibili (per esempio `CUDA_VISIBLE_DEVICES=''`), la scansione viene eseguita sulla CPU, riporta 0 GB di VRAM e seleziona `legacy`. `FACET_DEVICE=cuda` senza dispositivi visibili si ferma con «FACET_DEVICE=cuda was requested, but that device is not available».

**Le schede da 10-14GB possono scegliere l'insieme completo delle funzionalità.** Il rilevamento automatico sceglie ancora `8gb` sotto i 14GB. Imposta `"vram_profile": "16gb"` o `FACET_VRAM_PROFILE=16gb` per eseguire SigLIP 2, TOPIQ, il tagging Qwen3.5-2B, Q-ReAlign e la salienza. I modelli vengono poi eseguiti in quattro passaggi, o tre su una scheda che riporta 11,8 GiB o più (vedi [Raggruppamento dinamico dei passaggi](#raggruppamento-dinamico-dei-passaggi)). Una foto che la salienza non riesce ancora a valutare memorizza NULL e registra un ERROR.

> **Avvertenza:** Passare una libreria `8gb` esistente a `16gb` cambia il modello di embedding (CLIP ViT-L-14 768 dimensioni → SigLIP 2 1152 dimensioni). Riscansiona o esegui `--recompute-embeddings`, altrimenti la libreria mescola due dimensioni di embedding. Fino ad allora, la ricerca si comporta come descritto in *Ricerca semantica e libreria incorporata con un profilo diverso* in [Models](#models).

---

### Override tramite la variabile d'ambiente `FACET_VRAM_PROFILE`

`FACET_VRAM_PROFILE` sovrascrive `models.vram_profile` al caricamento, così un'unica configurazione montata può servire ogni profilo Docker. Valori accettati: `auto`, `legacy`, `8gb`, `16gb`, `24gb`; qualsiasi altro valore viene ignorato con un avviso. Gli overlay Docker Compose (`docker-compose.{legacy,8gb,16gb,24gb}.yml`) la impostano per te.

L'override non viene mai riscritto in `scoring_config.json`. Un `vram_profile` impostato nel file continua ad applicarsi quando la variabile non è impostata.

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

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

Impostazioni di batching GPU e multi-passaggio.

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

- **`gpu_batch_size`**: immagini elaborate insieme in un singolo forward pass sulla GPU. Limitato dalla VRAM; la regolazione automatica lo riduce quando la memoria GPU supera il limite.
- **`ram_chunk_size`**: immagini mantenute in RAM tra i passaggi del modello (solo multi-passaggio), così ogni immagine viene letta dal disco una volta per blocco. Limitato da `memory_limit_percent`. La regolazione automatica lo riduce subito quando la memoria supera il limite, e lo aumenta solo dopo un blocco il cui utilizzo di *picco* è rimasto sotto il limite.

### Riferimento delle impostazioni

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mode` | `"auto"` | Modalità di elaborazione: `auto`, `multi-pass`, `single-pass`. Solo `single-pass` seleziona il single-pass; `auto` esegue sempre il multi-pass |
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
| `memory_limit_percent` | `85` | Percentuale del limite di memoria effettivo (limite cgroup sotto un tetto del container, altrimenti RAM host) |
| `cpu_target_percent` | `85` | Obiettivo di utilizzo della CPU |
| `metrics_print_interval_seconds` | `30` | Intervallo di stampa delle statistiche |
| **thumbnails** | | |
| `photo_size` | `640` | Dimensione della miniatura archiviata (pixel) |
| `photo_quality` | `80` | Qualità JPEG della miniatura |
| `face_padding_ratio` | `0.3` | Padding intorno ai ritagli dei volti |

### Modalità di elaborazione

| Modalità | Descrizione |
|------|-------------|
| `auto` | Esegue sempre il multi-pass (predefinito); solo `single-pass` seleziona il single-pass |
| `multi-pass` | Caricamento sequenziale dei modelli (funziona con VRAM limitata) |
| `single-pass` | Tutti i modelli caricati contemporaneamente (molta VRAM); solo profili `legacy`/`8gb` |

Su `16gb`/`24gb` (estetica TOPIQ), `single-pass` registra un avviso ed esegue il multi-passaggio, tranne in modalità commerciale (vedi [Licenze](#licenze)).

### Come funziona il multi-passaggio

Invece di caricare tutti i modelli contemporaneamente, il multi-passaggio:

1. Carica le immagini in blocchi RAM (predefinito `ram_chunk_size`: 32)
2. Per ogni blocco, esegue i modelli in sequenza: carica modello → elabora blocco → scarica modello
3. Combina i risultati in un passaggio di aggregazione finale

Ogni immagine viene decodificata una sola volta per blocco e condivisa da tutti i passaggi. I passaggi sono raggruppati per adattarsi alla VRAM disponibile, quindi i VLM più grandi funzionano anche su schede piccole.

- I thread di caricamento calcolano anche EXIF, metriche tecniche, composizione basata su regole, hash percettivo e una copia condivisa da 1024 px per i modelli pyiqa e Q-ReAlign.
- Un errore di composizione fa fallire solo quella foto. Viene registrato in `scan_failures` con la fase `composition`; riprova con `--retry-failed`.
- Su una GPU CUDA, un blocco viene decodificato mentre si caricano i modelli successivi, quando la memoria libera dell'host lo consente e `keep_in_ram` non è `"never"`. Altrimenti (e sempre su CPU e Apple MPS) viene decodificato prima. I risultati sono identici in entrambi i casi.
- Quando la memoria scarseggia prima di un blocco, la cache RAM rilascia per primo il modello che servirà più tardi e mantiene libero `ram_cache_reserve_gb`.
- Il riepilogo della scansione riporta `Plane rebuilds`, `I/O wait (scan thread blocked on decode)` e `Decode wall`.

### Comportamento della regolazione automatica

Facet monitora l'utilizzo delle risorse e si regola come segue. `memory_limit_percent` è misurato rispetto al limite di memoria *effettivo*: il limite cgroup sotto un tetto del container (Docker `mem_limit`, Podman `--memory`, Kubernetes `resources.limits.memory`), altrimenti la RAM dell'host. Quindi `85` contro un tetto di 8GB è ~6,8GB.

| Metrica | Azione |
|--------|--------|
| Memoria GPU > limite | Riduce `gpu_batch_size` del 25% |
| Utilizzo memoria > limite | Riduce `ram_chunk_size` del 25% (immediatamente) |
| Un blocco terminato il cui utilizzo massimo è rimasto < (limite - 20%) | Aumenta `ram_chunk_size` del 25% |
| CPU > obiettivo | Suggerisce meno worker |
| Timeout della coda > 5% | Suggerisce più worker |

### Raggruppamento dinamico dei passaggi

Quando la VRAM lo consente, più modelli vengono eseguiti nello stesso passaggio:

| VRAM | Passaggio 1 | Passaggio 2 | Passaggio 3 | Passaggio 4 |
|---|---|---|---|---|
| 8GB (profilo `8gb`) | CLIP | Q-ReAlign + salienza | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12GB\* (profilo `16gb`, opt-in) | Tagger Qwen3.5 + Q-ReAlign | SigLIP + salienza + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16GB (profilo `16gb`) | Tagger Qwen3.5 + SigLIP + TOPIQ | Q-ReAlign + salienza + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24GB (profilo `24gb`) | Tagger Qwen3.5 4B + SigLIP + Q-ReAlign + salienza | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35GB+ (profilo `24gb`) | Tutti i modelli insieme (single-pass) | - | - | - |

Le righe sono i piani per schede che riportano 8,0, 11,7, 15,99 e 23,99 GiB di VRAM totale; 34,8 GiB o più pianifica un singolo passaggio. Il pianificatore tiene liberi 1,3 GiB per CUDA, ONNX Runtime e il desktop. Una scheda da 12GB non viene selezionata automaticamente (vedi [Rilevamento automatico della VRAM](#rilevamento-automatico-della-vram)): imposta `"vram_profile": "16gb"` o `FACET_VRAM_PROFILE=16gb`.

\* La riga 12GB è per una scheda che riporta 11,7 GiB. Una scheda che riporta 11,8 GiB o più (ad esempio 11,99 GiB) pianifica invece tre passaggi: tagger Qwen3.5 + Q-ReAlign; SigLIP + salienza + TOPIQ; TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace.

### Opzioni CLI

```bash
# Predefinito: multi-passaggio automatico con raggruppamento ottimale
python facet.py /path/to/photos

# Forza il singolo passaggio (tutti i modelli caricati contemporaneamente; solo profili legacy/8gb, su 16gb/24gb avviso e multi-pass)
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

## Decodifica RAW

Come i file RAW vengono trasformati in pixel. Facet usa due profili:

- **Profilo metriche**: la demosaicizzazione da cui viene calcolato ogni punteggio (e lo spazio di pixel dei riquadri dei volti e di `image_width`/`image_height`). Un unico guadagno di esposizione fisso per tutta la libreria, nessun adattamento per scatto.
- **Profilo di visualizzazione**: ciò che mostrano la miniatura memorizzata, la galleria e `/image`. Preferisce l'anteprima incorporata dalla fotocamera (la curva tonale e l'esposizione proprie della fotocamera), e ricade sulla demosaicizzazione delle metriche.

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| Impostazione | Predefinito | Descrizione |
|---------------|-------------|-------------|
| `bright` | `1.62` | Guadagno di esposizione fisso per ogni demosaicizzazione (`1.0` = il livello proprio di LibRaw; `1.62` ≈ il +0,7 EV di darktable) |
| `prefer_embedded_preview` | `true` | Mostra l'anteprima della fotocamera quando c'è; `false` demosaicizza tutto (più lento, senza la curva tonale della fotocamera) |
| `preview_min_sensor_ratio` | `0.5` | Quota del sensore che un'anteprima deve coprire perché `/image` la usi invece di demosaicizzare |
| `viewer_concurrency` | `3` | Numero massimo di demosaicizzazioni RAW simultanee per `/image` e `/thumbnail` del viewer, separate da `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | Mostra i fotogrammi di bracketing senza alcuna correzione (nessuna anteprima, nessun guadagno `bright`); vedi [sotto](#i-fotogrammi-di-un-bracketing-vengono-renderizzati-senza-correzioni) |

Note:
- `bright` è l'unica costante arbitraria qui. Verificala sulla tua libreria con `--check-raw-rendering` prima di una grande scansione.
- Nikon, Pentax, Samsung e Canon CR3 incorporano un'anteprima quasi a piena dimensione (0,98-0,99). Panasonic si colloca a 0,52. Olympus, Fuji, Sony e DNG ne incorporano una piccola (0,29-0,49), quindi demosaicizzano.

### Compromesso di memoria

`viewer_concurrency` e `processing.raw_decode_concurrency` sono budget separati. Nel caso peggiore entrambi sono in corso contemporaneamente, e ogni demosaicizzazione ha un picco di circa 200-400 MB. Abbassa `viewer_concurrency` su un host con memoria limitata. In pratica solo i file Sony, Fuji, Olympus e DNG usano il budget del viewer, perché gli altri hanno un'anteprima abbastanza grande.

### Perché non c'è una luminosità automatica

La luminosità automatica di LibRaw si adatta a ogni fotogramma, quindi un bracketing esce con ogni fotogramma a circa la stessa luminosità. Il guadagno fisso mantiene la vera scala di esposizione tra i fotogrammi.

Aumentare `bright` schiarisce ogni rendering. Le metriche di esposizione si spostano con esso: esegui di nuovo `--recompute-average` dopo averlo cambiato, e riscansiona per riscrivere le metriche stesse.

### I fotogrammi di un bracketing vengono renderizzati senza correzioni

Una foto il cui `sequence_kind` è `bracket` o `hdr_panorama` viene mostrata senza anteprima della fotocamera e senza guadagno `bright`. Entrambi taglierebbero le alte luci che stai valutando in un bracketing. Un `panorama` semplice non è interessato.

Dove si applica:
- `/image` (vista dettaglio, lente di confronto, lente di selezione), renderizzato al volo.
- Le schede della galleria e la griglia di confronto, dopo `--refresh-thumbnails`.
- `GET /api/download` con `type=original`.

Non interessati: `type=raw` (il RAW non toccato), `type=darktable` (l'esportazione con aspetto elaborato), `GET /api/photo/cull_preview` (renderizzato da darktable-cli) e il punteggio.

Il rilevamento delle sequenze viene eseguito dopo una scansione, quindi esegui prima `--detect-sequences`, poi `--refresh-thumbnails`, perché le schede seguano.

Imposta `faithful_bracket_render` su `false` per renderizzare i bracketing come qualsiasi altra foto.

### Migrare una libreria scansionata prima di questo profilo

Le miniature e gli istogrammi vengono memorizzati al momento della scansione, quindi cambiare il profilo non modifica le foto già scansionate. `photos.render_version` registra quale rendering ha prodotto ciascuna miniatura memorizzata:

- `NULL`: precedente al marcatore
- `1`: prima l'anteprima della fotocamera, guadagno `bright` sul demosaicing di riserva (ciò che memorizza ogni scansione)
- `2`: nessuna anteprima e nessun guadagno, per un fotogramma di bracketing (lo memorizza solo `--refresh-thumbnails`)

Solo due cose aggiornano le miniature memorizzate:
- **Una nuova scansione** riscrive la miniatura e l'istogramma, e marca sempre `1`.
- **`--refresh-thumbnails`** riscrive le miniature RAW e marca `1` o `2` in base al `sequence_kind` attuale. Ricostruisce ogni riga, quindi rieseguilo dopo una modifica di `bright` o un passaggio di `--detect-sequences`.

La vista dettaglio (`/image`) è sempre aggiornata; la griglia della galleria cambia solo dopo una delle due operazioni sopra.

La galleria mostra un banner rimovibile che conta le foto ancora sul rendering precedente. Può restare indietro fino a un'ora; `python database.py --refresh-stats` lo aggiorna subito.

Un rendering che risulta completamente nero (ad esempio un RW2 Panasonic troncato) viene rifiutato, registrato con il nome del file e ritentato in un'esecuzione successiva.

---

## Mappatura dei toni HDR PQ

Le foto Canon HDR PQ (`.HIF`) portano la funzione di trasferimento PQ (SMPTE ST 2084) su primari BT.2020, fino a 10.000 nit. I modelli di qualità e le miniature richiedono sRGB SDR a 8 bit, quindi Facet decodifica un'immagine PQ alla profondità nativa della fotocamera, la converte in sRGB e la mappa nei toni. Questo blocco controlla tale mappatura.

Si applica **solo** alle immagini il cui profilo colore NCLX dichiara il trasferimento PQ (caratteristica 16). HEIF SDR, HLG e JPEG passano invariati, qualunque cosa dica `enabled`. I fotogrammi ruotati (orientazione EXIF diversa da 1) escono dritti, anche sul percorso a profondità nativa: con pillow-heif 1.6 e successivi il piano viene ruotato prima della mappatura dei toni.


```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Mappa nei toni le immagini PQ in SDR; `false` le lascia scure e slavate (solo per il debug) |
| `method` | `hable` | Curva di tono: `hable` (filmica, come nel filtro `tonemap` di ffmpeg) oppure `clip` (lineare con taglio netto, solo come riferimento) |
| `white_point.mode` | `percentile` | Come viene scelto il punto di bianco per immagine: `percentile`, `max` (pixel più luminoso) o `fixed` (`fixed_nits`) |
| `white_point.percentile` | `99.99` | Percentile usato in modalità `percentile` |
| `white_point.min_nits` | `100.0` | Soglia inferiore per il punto di bianco; un fotogramma scuro non viene mai normalizzato sotto il bianco di riferimento SDR |
| `white_point.max_nits` | `1200.0` | Soglia superiore in modalità `percentile`; limita quanto un fotogramma insolitamente luminoso possa spingere la curva verso il basso |
| `white_point.fixed_nits` | `1000.0` | Punto di bianco usato in modalità `fixed` |
| `chroma_preserve` | `per_channel` | `per_channel` (più luminoso, leggero spostamento di tinta nelle alte luci) oppure `max_channel` (preserva la tinta, leggermente più scuro) |

La modalità `max` lascia che un pixel caldo in una scena notturna scurisca l'intero fotogramma; `percentile` lo evita.

### Perché il punto di bianco è per immagine

Un punto di bianco fisso a 100 nit taglia al bianco puro tutto ciò che è più luminoso, e le foto HDR reali raggiungono picchi da centinaia a migliaia di nit. Facet normalizza invece su un punto di bianco per immagine, come ffmpeg (`vf_tonemap.c`). Il p99.99 predefinito, vincolato a 100-1200 nit, mantiene la texture delle alte luci e ignora i pixel caldi isolati.

### Perché la decodifica avviene alla profondità nativa della fotocamera

Decodificare il PQ a 8 bit prima della mappatura dei toni posterizza le sfumature morbide. Facet chiede al decodificatore HEIF la profondità propria del file (10 bit sulle fotocamere attuali) e riduce a 8 bit solo dopo la curva dei toni. Il guadagno si vede sul contenuto morbido (cieli limpidi, fondali da studio, bokeh marcato); i flag di clipping e `exposure_score` restano invariati sulle foto reali. Un decodificatore che non può fornire la profondità nativa ricade sugli 8 bit.

**Riferimenti.** EOTF PQ: SMPTE ST 2084:2014. Curva Hable e picco per
fotogramma: ffmpeg `vf_tonemap.c` (John Hable, “Filmic Tonemapping Operators”,
2010). Matrice BT.2020 to sRGB: BT.2020-2 / IEC 61966-2-1 con D65. OETF sRGB:
IEC 61966-2-1. Caratteristica di trasferimento NCLX 16: ISO/IEC 23001-8 /
ITU-T H.273.

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

## Notifiche di aggiornamento

Avvisa gli utenti di edizione quando esiste una versione più recente di Facet. È distinto dal messaggio del browser «È disponibile una nuova versione — Ricarica».

- La versione in esecuzione è mostrata in fondo al menu utente per chiunque possa aprire il viewer.
- Un'immagine costruita con `--build-arg FACET_BUILD=<branch>@<commit>` mostra anche quella riga di build. `/api/config` restituisce entrambe come `version` e `build`, solo a chi può leggere la libreria.
- Il server interroga GitHub al massimo una volta per `interval_days`, senza token né dati della libreria. Un controllo fallito appare come «nessun aggiornamento noto».
- Solo gli utenti di edizione vedono l'avviso, al massimo una volta a settimana per browser.

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---|---|---|
| `enabled` | `true` | `false` disattiva il controllo; non viene mai richiesto nulla |
| `check_url` | API GitHub dell'ultima release | Dove cercare l'ultima versione pubblicata |
| `interval_days` | `7` | Per quanto tempo un risultato resta in cache prima di chiedere di nuovo |

---

## Rilevamento delle sequenze

Etichetta i bracketing di esposizione perché non vengano trattati come scatti in competizione. L'esposizione di ogni fotogramma proviene da `f_stop` / `shutter_speed` / `ISO` memorizzati (`EV = log2(N^2 / t) - log2(ISO / 100)`), quindi una libreria esistente viene etichettata senza una nuova scansione.

Una serie è un bracketing quando i suoi fotogrammi:
- provengono dalla stessa fotocamera, ciascuno entro `max_gap_seconds` dal precedente;
- mantengono la stessa inquadratura (`max_hamming` sul pHash);
- formano una scala regolare di esposizioni distinte, in qualsiasi ordine di scatto (con lo scatto base per primo `0, -, +` funziona come dallo scuro al chiaro), che copre `min_span_stops`, su almeno `min_frames` fotogrammi.

Ogni fotogramma riceve `sequence_ev_offset`, la sua esposizione rispetto al fotogramma di base, con il segno delle etichette AEB di una fotocamera (`-2` scuro, `+2` chiaro). La base è il piolo centrale. Con un numero pari di fotogrammi, la base è il fotogramma centrale che taglia meno estremi del proprio istogramma (il più vecchio in caso di parità); una serie dispari come `(-2, 0, +2)` usa sempre il suo fotogramma centrale. Quando un gruppo di raffica è esattamente un bracketing, la galleria mostra il suo fotogramma di base.

Si avvia con `--detect-sequences`; viene eseguito anche al termine di ogni scansione, dopo il
raggruppamento delle raffiche.

**Le correzioni manuali coprono anche i bracket.** Segna a mano un bracket sfuggito dalla galleria o dalla selezione (« Segna come bracket »). Servono ≥2 fotogrammi, ciascuno con dati di esposizione utilizzabili, mai due alla stessa esposizione. Vedi [docs/VIEWER.md — Panorami e bracket di esposizione](VIEWER.md#panorami-e-bracket-di-esposizione).

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---|---|---|
| `enabled` | `true` | Disattiva completamente il rilevamento del bracketing |
| `max_gap_seconds` | `3.0` | Intervallo massimo tra due scatti consecutivi di una serie |
| `max_hamming` | `10` | Distanza pHash ammessa tra gli scatti (stessa inquadratura) |
| `min_frames` | `3` | Serie più breve considerata un bracketing. `2` è opzionale — vedi l'avvertenza sotto |
| `min_step_stops` | `0.5` | Minimo scarto di EV che conta come variazione voluta |
| `min_span_stops` | `1.0` | Escursione minima tra lo scatto più scuro e il più chiaro |
| `step_tolerance_stops` | `0.34` | Irregolarità ammessa tra i passi (un terzo di stop) |

**Perché `min_frames` vale `3` per impostazione predefinita.** Due fotogrammi a uno stop di distanza sembrano identici sia che siano un bracketing AEB a due scatti sia una rapida correzione dell'esposizione. Con `2`, la maggior parte delle serie aggiuntive trovate su una libreria di prova non erano bracketing. Una coppia può inoltre essere ciò che resta di una serie da tre scatti, e allora la base (`sequence_ev_offset` `0`) può finire sul fotogramma sbagliato mentre `hide_brackets` (attivo per impostazione predefinita) nasconde l'altro. Imposta `2` solo se scatti in bracketing AEB a due fotogrammi e accetti alcuni falsi positivi.

---

## Rilevamento dei panorami

Etichetta i fotogrammi sorgente dei panorami, che il rilevamento delle raffiche altrimenti nasconderebbe come scatti in competizione. Il rilevamento abbina caratteristiche SIFT tra miniature memorizzate da 640px consecutive; non richiede decodifica degli originali, modelli né dipendenze aggiuntive.

- Una panoramica si sposta con costanza in una direzione; una raffica oscilla attorno a un punto. Le panoramiche normali e HDR sono tipi separati, distinti in base all'escursione di esposizione.
- La precisione misurata è ~96% su una libreria di prova. Alcuni panorami verticali o con poche posizioni vengono mancati.
- Puoi correggere in entrambe le direzioni con l'override per insieme.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Disattivare completamente il rilevamento dei panorami |
| `max_gap_seconds` | `30.0` | Intervallo massimo fra fotogrammi consecutivi di una panoramica |
| `min_frames` | `8` | Serie più breve considerata un panorama (filtro più forte; i non-panorami avevano 6 fotogrammi o meno) |
| `min_drift` | `0.43` | Spostamento totale, in larghezze di inquadratura, perché una serie conti |
| `min_inliers` | `25` | Corrispondenze RANSAC necessarie per validare una coppia |
| `max_step` | `0.9` | Passo singolo più ampio, in larghezze di inquadratura — oltre è uno stacco di scena |
| `back_tolerance` | `0.02` | Arretramento tollerato su un passo prima che la serie termini |
| `max_ortho` | `0.15` | Deriva laterale tollerata sull'intera panoramica |
| `ortho_ratio` | `0.25` | Margine laterale aggiuntivo proporzionale allo spostamento, per non penalizzare le serie lunghe |
| `step_ortho_abs` | `0.02` | Spostamento laterale tollerato in un singolo passo prima di leggerlo come ricomposizione |
| `step_ortho_ratio` | `0.5` | Lo stesso limite come frazione del passo |
| `hdr_min_span_stops` | `1.5` | Escursione di esposizione oltre la quale una panoramica è un panorama HDR |
| `sift_features` | `400` | Caratteristiche per miniatura; il costo cresce con il quadrato di questo valore |
| `match_ratio` | `0.75` | Rapporto di Lowe che una corrispondenza deve superare per essere tenuta |
| `workers` | `0` | Processi paralleli; `0` sceglie in base ai core |
| `probe_stride` | `8` | Fotogrammi fra i sondaggi economici che scartano le raffiche ordinarie |
| `probe_min_drift` | `0.05` | Movimento sotto il quale un sondaggio dichiara ferma la serie |
| `max_run_frames` | `500` | Serie più lunga misurata (limita la memoria, ~220 KB per fotogramma per worker) |

Note:
- `sift_features` richiede circa 2,3 ms per coppia di fotogrammi a 400, e circa 0,12 s a 3000.
- Modificare un'impostazione non fa nulla finché il rilevamento non viene rieseguito: usa `--detect-panoramas` (o l'azione di riesecuzione del viewer), che rimisura l'intera libreria.
- Il passaggio panorama dopo una scansione, `--recompute-average` o `--recompute-burst` rimisura solo le serie modificate. Modificare qualsiasi impostazione diversa da `enabled` e `workers` lo fa rimisurare tutto.
- Le tue correzioni si applicano al passaggio successivo. Due passaggi su una libreria invariata trovano gli stessi insiemi con gli stessi numeri di gruppo.

---

## Burst Scoring

Pesi usati dalla selezione delle raffiche per scegliere lo scatto migliore in ciascun gruppo di raffica. I pesi dovrebbero sommare a 1,0.

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

Trova le foto duplicate nell'intera libreria: candidati pHash permissivi, confermati da un controllo di similarità sugli embedding.

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
| `similarity_threshold_percent` | `90` | Soglia pHash rigorosa (90% = distanza di Hamming <= 6 su 64 bit); l'unico test quando una delle due foto non ha un embedding |
| `prefilter_hamming` | `12` | Facoltativo (assente dal file fornito). Soglia di Hamming permissiva per i candidati quando entrambe le foto hanno embedding (almeno pari alla soglia rigorosa) |
| `embedding_cosine_threshold` | `0.90` | Facoltativo (assente dal file fornito). Un candidato si unisce solo se il coseno SigLIP/CLIP è >= questo valore |

- `python facet.py --detect-duplicates` rileva e raggruppa i duplicati.
- `python facet.py --sweep-dedup-thresholds [labels.json]` valuta la soglia coseno: con un JSON di etichette stampa precisione/richiamo, altrimenti la distribuzione dei coseni dei candidati e quante corrispondenze pHash rigorose la soglia rifiuta.

---

## Extended IQA tier (optional)

Scorer di qualità aggiuntivi che scrivono le proprie colonne; non sostituiscono mai TOPIQ. Vengono eseguiti durante una normale scansione. Un errore di caricamento o di VRAM viene registrato e lascia la colonna a `NULL`; la scansione prosegue.

- `qrealign` ha come predefinito `"auto"`: **attivo** per i profili `8gb`/`16gb`/`24gb`, **disattivato** per `legacy`/CPU.
- `aesthetic_v25` e `deqa` sono **DISATTIVATI per impostazione predefinita**.

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| Impostazione | Predefinito | Valori accettati | Colonna | Descrizione |
|---------|---------|-----------------|--------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | IQA estetica Q-ReAlign-Mini 0.8B (Apache-2.0, ~2-3GB VRAM/RAM, senza pyiqa) |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini` (0.8B) o `lite` (4B); anche il modello principale in `licensing.mode: "commercial"` |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (testa SigLIP, ~2GB); **deprecato**, preferisci `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16GB+; altrimenti saltata e lasciata a NULL) |

Note:
- **Ordinamento:** ogni metrica compare nel menu di ordinamento del viewer quando almeno una foto ha un punteggio (**Q-ReAlign (estetica)**, **Aesthetic v2.5**, **DeQA**). Le foto non valutate vanno in fondo.
- `qrealign_score` contiene il compito estetico; la qualità usa `quality_score`.
- `aesthetic_v25` richiede il pacchetto `aesthetic-predictor-v2-5`. Ha licenza AGPL-3.0 e non è più mantenuto a monte dal 2024-12-18.

**Installa le dipendenze facoltative** per ciò che abiliti: `pip install -e .[iqa-extended]` (aggiunge `aesthetic-predictor-v2-5`), oppure decommenta la riga corrispondente in `requirements.txt`. DeQA-Score viene scaricato tramite `transformers`.

Ogni metrica è disponibile per l'aggregato pesato con peso 0, quindi `--recompute-average` non cambia nulla finché non le assegni un peso. `python facet.py --eval-iqa-srcc` misura quanto ogni metrica corrisponde alle tue valutazioni a stelle.

**Esposizione nel viewer.** I valori popolati compaiono nel pannello **Quality** dei dettagli della foto (`Q-ReAlign`, `Aesthetic V2.5`, `DeQA`), con slider di intervallo sotto **Extended Quality** nei filtri della galleria (`min_qrealign`/`max_qrealign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`).

> **Avvertenza:** Le foto scansionate prima di abilitare una metrica hanno `NULL` lì, e qualsiasi minimo o massimo sul suo slider le nasconde. Esegui una nuova scansione prima di filtrare su una metrica appena abilitata.

**Robustezza.** DeQA-Score esegue codice di modello remoto (`trust_remote_code`). Se fallisce su un'immagine (cambio di firma, output anomalo, OOM), il `deqa_score` di quell'immagine resta `NULL` e la scansione continua.

---

## Licenze

Controlla quali componenti di modelli Facet può caricare. Vedi [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md) per la tabella delle licenze per componente.

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| Impostazione | Predefinito | Valori accettati | Descrizione |
|---------|---------|-------------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` carica tutti i modelli; `"commercial"` carica solo componenti sicuri per uso commerciale |
| `allow_unclear` | `false` | `true` / `false` | In modalità commerciale, consente anche i componenti con licenza *incerta* (SAMP-Net, U2-Net-P, la testa estetica CLIP-MLP di LAION); deve essere un booleano JSON |

In modalità `"commercial"`:
- `pyiqa` (TOPIQ, HyperIQA, LIQE, ...) e InsightFace non vengono mai importati né scaricati.
- Estetica e qualità provengono da Q-ReAlign, la composizione dall'analizzatore basato su regole.
- I volti usano il rilevamento YuNet, gli embedding SFace a 128 dimensioni e, facoltativamente, occhi/sorriso MediaPipe e la qualità del volto OFIQ.
- `liqe` e `aesthetic_iaa` restano `NULL`. `deqa` (licenza *incerta*) richiede `allow_unclear`. `aesthetic_v25` (AGPL) non è mai disponibile.
- Un componente rifiutato interrompe la scansione all'avvio con un `LicenceError` che nomina il componente e il suo sostituto.
- `--score-topiq`, `--recompute-iqa` (modelli pyiqa) e `--recompute-composition-gpu` terminano con quel messaggio.
- I componenti con licenza non commerciale restano rifiutati anche con `allow_unclear`.

Nulla di quanto qui scritto costituisce consulenza legale.

Override tramite variabili d'ambiente (possono solo restringere; un valore non valido blocca l'avvio):

| Variabile | Effetto |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` forza la modalità commerciale; `default` o vuota = nessun override |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`, `false`, `no`, `off` forzano `allow_unclear` a off; `1`, `true`, `yes`, `on` o vuota = nessun override |

Il viewer passa `FACET_LICENSING_MODE=commercial` e, quando la sua policy vieta i componenti incerti, `FACET_LICENSING_ALLOW_UNCLEAR=0` a ogni processo `facet.py` che avvia. Una stringa come `"false"` per `licensing.allow_unclear` viene rifiutata all'avvio.

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
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confidenza minima di rilevamento (solo InsightFace) |
| `min_face_size` | `20` | Dimensione minima del volto in pixel (solo InsightFace) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio per il rilevamento del battito di palpebre |
| `min_faces_for_group` | `4` | Volti minimi per classificare come ritratto di gruppo (ricalcolato con `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Facoltativo (assente dal file fornito). Carica InsightFace `landmark_3d_68` per la posa della testa (yaw/pitch/roll); ~5MB, solo informativo |
| `eyes_closed_max` | `4.0` | Punteggio occhi aperti (0–10) pari o inferiore al quale la camera oscura di selezione segnala un battito di ciglia (anelli dei volti, cursore occhi) |
| `poor_expression_min` | `4.0` | Punteggio sorriso/espressione (0–10) sotto il quale la camera oscura segnala un'espressione debole |
| `blendshapes.enabled` | `true` | Usa i blendshape MediaPipe per `eyes_open_score` / `smile_score` se installato, altrimenti la geometria dei punti di riferimento |
| `blendshapes.min_crop_size` | `192` | I volti il cui ritaglio con padding è più piccolo di questo valore (px, lato più corto) usano il punteggio geometrico |
| `blendshapes.blink_pose_gate_deg` | `null` | Solo modalità commerciale (MediaPipe): soglia della posa della testa in gradi; `null` = disattivata |

Note:
- Il rilevatore YuNet della modalità commerciale usa valori fissi (confidenza 0,7, 30 px) e ignora `min_confidence_percent` e `min_face_size`.
- MediaPipe richiede il bundle `face_landmarker.task`. Installalo con `pip install mediapipe==0.10.35 --no-deps`, mai con un semplice `pip install mediapipe`. Vedi [FACE_RECOGNITION.md](FACE_RECOGNITION.md#segnali-di-espressione-per-volto-occhi-aperti--sorriso).
- `blink_pose_gate_deg`: un volto il cui |yaw| o |pitch| la supera non riceve alcun verdetto di battito né punteggio occhi aperti / sorriso (NULL), perché una testa girata sembra avere gli occhi chiusi. Nessuna soglia tra 20° e 45° ha migliorato il rilevamento dei battiti su una libreria di prova, quindi è fornita disattivata. Deve essere un numero positivo; si applica alle foto scansionate di recente (`is_blink` cambia alla nuova scansione).

---

## Face Clustering

Clustering HDBSCAN per il riconoscimento dei volti.

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Abilita il clustering dei volti |
| `min_faces_per_person` | `2` | Foto minime per persona |
| `min_samples` | `2` | Parametro min_samples di HDBSCAN |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Dimensione delle foglie dell'albero (solo CPU) |
| `use_gpu` | `"auto"` | Modalità GPU: `auto`, `always`, `never` |
| `thresholds_by_model` | vedi JSON | Per modello di riconoscimento: `auto_merge_distance_percent` e `merge_threshold`. Valori predefiniti: ArcFace `15` / `0.6`, SFace `27.5` / `0.65` |

`merge_threshold` (similarità dei centroidi per l'abbinamento) e `auto_merge_distance_percent` (distanza di unione automatica) vengono lette da `thresholds_by_model` per il modello di riconoscimento **attivo** (ArcFace per impostazione predefinita, SFace in modalità commerciale). Un modello senza voce è un errore. Le stesse chiavi impostate direttamente sotto `face_clustering` non vengono più lette.

**Note sul clustering GPU (`use_gpu`):**

- Richiede i pacchetti facoltativi `cuml` + `cupy`. L'immagine Docker GPU include cuML.
- Il profilo `legacy` esegue sempre il clustering su CPU, qualunque cosa dica `use_gpu`.
- Senza un dispositivo CUDA utilizzabile, il clustering ricade su HDBSCAN su CPU.
- `always` avvisa e usa la CPU se cuML manca; anche un errore GPU durante il clustering ricade sulla CPU.

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
| `memory_limit_percent` | `80` | Percentuale del limite di memoria effettivo (limite cgroup sotto un tetto del container, altrimenti RAM host) |
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

**Nota:** La soglia dei tag CLIP/SigLIP è `tag_threshold_percent` nel blocco del profilo attivo: `models.clip` per `16gb`/`24gb`, `models.clip_legacy` per `legacy`/`8gb`. La vecchia chiave `similarity_threshold_percent` non viene più letta. Se l'avevi personalizzata, copia il valore in `tag_threshold_percent`; il caricamento della configurazione e `python facet.py --doctor` segnalano la vecchia chiave.

Al termine di una scansione, il passaggio di tagging viene saltato (con una riga di log) quando `enabled` è `false` o nessuna foto ha sia un embedding sia un elenco di tag vuoto. Le foto a cui nessun tag corrisponde mai restano in attesa, quindi il modello viene comunque caricato a ogni scansione. `python tag_existing.py` (con o senza `--force`) e `python facet.py --tag-untagged` vengono sempre eseguiti.

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
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "panel",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
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
| `edition_password` | `""` | Password per sbloccare la modalità di modifica; vuoto = sola lettura (eccetto con `trusted_local_editing`) |
| `trusted_local_editing` | `false` | Concede i diritti di modifica a un browser sullo stesso computer, senza password. Vedi [Modifica locale attendibile](#modifica-locale-attendibile) |
| `place_search_url` | `"https://photon.komoot.io/api"` | Endpoint Photon per la ricerca **Cerca online** della galleria; `""` la disattiva. Vedi [Ricerca online di luoghi](#ricerca-online-di-luoghi) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Confronti decisivi (pareggi esclusi) necessari in una categoria prima che vengano suggeriti i pesi |
| `pair_selection_strategy` | `"learning"` | Strategia di coppia: `learning`, `uncertainty`, `boundary`, `active`, `random` |
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
| `needs_naming_min_faces` | `5` | Numero minimo di volti perché un cluster appaia in «Da nominare» in `/persons`; `1` elenca ogni persona senza nome |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome del binario darktable-cli o percorso assoluto |
| `darktable.profiles` | `[]` | Array di profili di esportazione darktable con nome (vedi sotto) |
| `darktable.profiles[].name` | *(obbligatorio)* | Nome visualizzato del profilo (usato nel menu di download e nel parametro API `profile`) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` per l'esportazione ad alta qualità |
| `darktable.profiles[].width` | *(ometti)* | Larghezza massima di output (ometti per la risoluzione piena) |
| `darktable.profiles[].height` | *(ometti)* | Altezza massima di output (ometti per la risoluzione piena) |
| `darktable.profiles[].style` | *(ometti)* | Nome dello stile darktable applicato durante l'esportazione (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | `false` passa `--apply-custom-presets false`, quindi si applica solo lo `style` esplicito |
| `darktable.profiles[].extra_args` | `[]` | Argomenti CLI aggiuntivi (es. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Stili darktable offerti come anteprima elaborata nello studio di selezione; vuoto nasconde il selettore |
| `darktable.cull_styles[].name` | *(obbligatorio)* | Nome dello stile darktable (passato a `--style`) |
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
| `sort` | `"aggregate"` | Colonna di ordinamento predefinita (un ordinamento ricordato dal browser prevale; vedi [Ordinamento](VIEWER.md#ordinamento)) |
| `sort_direction` | `"DESC"` | Direzione di ordinamento predefinita (`"ASC"` o `"DESC"`) |
| `hide_blinks` | `true` | Nasconde per impostazione predefinita le foto con battito di palpebre |
| `hide_bursts` | `true` | Mostra per impostazione predefinita solo la migliore della raffica |
| `hide_duplicates` | `true` | Nasconde per impostazione predefinita le foto duplicate non principali |
| `hide_brackets` | `true` | Mostra per impostazione predefinita solo l'esposizione base di ogni bracketing |
| `hide_panoramas` | `true` | Mostrare per impostazione predefinita un solo fotogramma per panorama |
| `hide_details` | `true` | Nasconde per impostazione predefinita i dettagli della foto sulle schede |
| `tooltip_mode` | `"panel"` | Attivazione del tooltip: `"hover"`, `"click"`, `"off"` o `"panel"` (barra ancorata); sostituisce `hide_tooltip` |
| `panel_activation` | `"both"` | Gesto che cambia la foto della barra ancorata in modalità `"panel"`: `"hover"`, `"click"` o `"both"` |
| `hide_rejected` | `true` | Nasconde per impostazione predefinita le foto rifiutate |
| `gallery_mode` | `"mosaic"` | Layout predefinito della galleria (`"grid"` o `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origini consentite per CORS; aggiungi il tuo dominio o l'URL del reverse proxy in caso di hosting remoto |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(predefinito sicuro per la SPA)_ | Header Content-Security-Policy; `""` lo disattiva, oppure fornisci una policy più restrittiva |
| `security_headers.hsts` | `false` | Invia `Strict-Transport-Security`. Abilita solo quando il viewer è servito via HTTPS. |
| **Altro** | | |
| `cache_ttl_seconds` | `3600` | TTL delle cache in memoria di statistiche/query; tienilo più lungo di un calcolo completo delle statistiche (può richiedere minuti) |
| `notification_duration_ms` | `2000` | Durata del toast |
| `moment_confidence_min` | `0` | Le etichette dei momenti sotto questa confidenza (0–1) appaiono attenuate con «(incerto)»; `0` = mai attenuate |

Note:
- **`trusted_local_editing`** vale solo quando `password` e `edition_password` sono entrambe vuote su un'installazione a utente singolo. Copre ogni route riservata all'edizione, scansioni incluse, e permette alla finestra «Collega un assistente» di creare un token di assistente Modifica completa per le richieste `/mcp` dalla stessa macchina.

> **Avvertenza:** Non abilitare mai `trusted_local_editing` dietro un reverse proxy sullo stesso host.

- **`pair_selection_strategy`:** `learning` sceglie all'inizio coppie diverse, poi coppie che il modello classifica in modo incoerente.
- **`darktable.cull_styles`** alimentano `GET /api/photo/cull_preview`. Ogni stile **deve già esistere** nella configurazione di darktable dell'utente che esegue il viewer.
- La Content-Security-Policy predefinita consente le risorse proprie della SPA: script/stile del tema inline, Google Fonts, tile OpenStreetMap e l'API della stessa origine.
- `moment_confidence_min` attenua le etichette nell'intestazione Scene, nell'intestazione dei gruppi di scena della Selezione e nel tooltip della galleria.

### Badge delle schede e clipping

`viewer.badges` attiva o disattiva i singoli badge della scheda in galleria. I badge più vecchi valgono `true` per impostazione predefinita, quindi ometterlo non cambia nulla.

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| Chiave | Predefinito | Descrizione |
|--------|-------------|-------------|
| `badges.favorite` | `true` | Badge a cuore su una foto preferita (modalità edizione) |
| `badges.star_rating` | `true` | Badge stella e contatore su una foto valutata (modalità edizione) |
| `badges.rejected` | `true` | Badge pollice verso su una foto rifiutata (modalità edizione) |
| `badges.sequence_kind` | `true` | Badge della serie (sequenza/bracketing/panorama/duplicato), mostrato mentre il rispettivo interruttore di occultamento comprime la serie |
| `badges.sequence_override_pending` | `true` | Badge orologio per una correzione panorama in attesa del prossimo rilevamento |
| `badges.stack` | `true` | Badge livelli con il numero di membri sulle schede di una pila di foto manuale; un clic apre la pila |
| `badges.keeper_hint` | `true` | Freccia «esiste uno scatto migliore in questo gruppo» dal modello di selezione appreso |
| `badges.best_of_burst` | `true` | Badge «Migliore» sullo scatto guida di una raffica, mostrato solo con `hide_bursts` disattivato |
| `badges.clipping_highlight` | `true` | Badge per una foto le cui alte luci superano `clipping.badge_percent` |
| `badges.clipping_shadow` | `false` | Idem per le ombre chiuse (disattivato: spesso intenzionale in silhouette, notte, low-key) |

Disattivare `badges.stack` nasconde solo il badge; il pulsante della scheda «Apri pila di foto» continua a funzionare.

`viewer.clipping` definisce «tagliato» una sola volta per il badge della scheda, i marcatori dell'istogramma e il filtro della galleria.

| Chiave | Predefinito | Descrizione |
|--------|-------------|-------------|
| `badge_percent` | `5` | Percentuale di pixel, nel peggiore dei canali R/G/B, oltre la quale la scheda riceve il badge (circa 1 foto su 25 su un campione) |
| `indicator_percent` | `1` | Soglia dei marcatori R/G/B dell'istogramma stesso |
| `histogram_mode` | `"rgb"` | Predefinito per l'istogramma del **pannello dei dettagli**: `"luma"`, `"rgb"`, `"r"`, `"g"` o `"b"` |
| `tooltip_histogram_mode` | `"luma"` | Predefinito per la scheda Istogramma del **pannello laterale** (`tooltip_mode: "panel"`), gli stessi cinque valori |

Note:
- La scelta dell'istogramma di un utente è memorizzata in `localStorage` (`facet_histogram_mode`, `facet_histogram_mode_tooltip`) e prevale su questi predefiniti. Le due impostazioni sono indipendenti.
- Le bolle **Hover** e **Click** non mostrano alcun istogramma.

**Il clipping è misurato per canale, esattamente ai bin 0 e 255.** È memorizzato in `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` come quota di pixel del peggior canale. Differisce dai flag `shadow_clipped` / `highlight_clipped`, che coprono le bande di luminanza 0–30 e 225–255 e alimentano `exposure_score`.

**`NULL` significa sconosciuto, mai pulito.** Una foto con un istogramma memorizzato più vecchio non ha dati di canale, quindi non riceve alcun badge e non corrisponde a nessun lato del filtro della galleria. `python facet.py --backfill-clipping` riempie le colonne dagli istogrammi memorizzati; non decodifica immagini e può essere ripreso.

### Funzionalità

Attiva o disattiva le funzionalità opzionali per ridurre l'uso della memoria o semplificare l'interfaccia:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
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
| `show_scan_button` | `false` | Mostra il pulsante di avvio scansione (nessuna GPU necessaria; vedi le note) |
| `metrics_enabled` | `false` | Abilita l'endpoint Prometheus pubblico `GET /metrics` (vedi l'avvertenza sotto) |
| `show_semantic_search` | `true` | Mostra la barra di ricerca semantica (ricerca testo-immagine usando gli embedding CLIP/SigLIP) |
| `show_albums` | `true` | Mostra la funzionalità album (crea, gestisci e sfoglia album di foto) |
| `show_critique` | `true` | Mostra il pulsante di critica AI sulle schede delle foto (analisi del punteggio basata su regole) |
| `show_vlm_critique` | `true` | Abilita la critica VLM (profilo 16gb/24gb); `false` quando la chiave è assente |
| `show_embed_metadata` | `true` | Mostra "Scrivi metadati nel file" in modalità di modifica (incorpora valutazioni/parole chiave tramite exiftool) |
| `show_memories` | `true` | Mostra la finestra dei ricordi "In questo giorno" (foto scattate nella stessa data degli anni precedenti) |
| `show_captions` | `true` | Mostra le didascalie generate dall'AI sulle schede delle foto |
| `show_timeline` | `true` | Mostra la vista timeline per la navigazione cronologica con navigazione per data |
| `show_map` | `true` | Mostra la vista mappa GPS (richiede Leaflet); `false` quando la chiave è assente |
| `show_capsules` | `true` | Mostra la vista Capsule (diaporame di foto curate raggruppate per tema) |
| `show_folders` | `true` | Mostra la navigazione per cartelle della struttura delle directory delle foto |
| `show_scenes` | `true` | Mostra la vista Scene (`/scenes`), con le foto principali delle raffiche raggruppate in scene cronologiche |
| `show_my_taste` | `true` | Mostra l'ordinamento "My Taste" del ranker personale, con un badge di confidenza |
| `show_social_export` | `true` | Mostra il menu di download **Ritaglio social** (solo edizione). Vedi [Esportazione social](#esportazione-social) |
| `show_portfolio_export` | `true` | Mostra l'azione dell'album **Esporta portfolio** (solo edizione). Vedi [Esportazione portfolio](#esportazione-portfolio) |
| `show_proofing` | `false` | Abilita la revisione del cliente sugli album condivisi. Vedi [Revisione del cliente](#revisione-del-cliente) |

Note:
- **`show_scan_button`:** visibile al superadmin in modalità multiutente, o a una sessione di modifica sbloccata in modalità utente singolo. Le scansioni girano solo su CPU con il profilo `legacy`. Una sessione trusted-local (`trusted_local_editing`) può avviare la scansione senza.
- **Ottimizzazione della memoria:** `show_similar_button: false` impedisce il caricamento di numpy, riducendo la memoria del viewer.

> **Avvertenza:** `metrics_enabled` espone conteggi di foto/persone/volti, dimensione del DB e memoria del processo. Abilitalo solo dove la rete dello scraper può raggiungerlo, mai su Internet pubblico.

### Revisione del cliente

`viewer.features.show_proofing` (predefinito `false`) trasforma qualsiasi album condiviso in una pagina di revisione del cliente. Un cliente con il link di condivisione (e l'eventuale `viewer.proofing.pin`) può mettere cuori alle foto e lasciare commenti senza un account. Il proprietario li rivede da una finestra riservata all'edizione sulla scheda dell'album. Le scelte dei clienti non toccano mai le valutazioni del proprietario né addestrano il ranker personale.

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
| `proofing.pin` | `""` | PIN facoltativo che un cliente deve inserire con il link di condivisione; vuoto = nessun PIN (i tentativi hanno un limite di frequenza) |
| `proofing.session_minutes` | `1440` | Durata della sessione del cliente in minuti (24h); termina subito se l'album non è più condiviso o la revisione è disattivata |

### Mappatura dei percorsi

Mappa i percorsi del database su percorsi locali, per quando le foto sono state valutate su una macchina (es. Windows con percorsi UNC) e il viewer gira su un'altra (es. un NAS Linux).

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
| `path_mapping` | `{}` | Prefisso di origine → prefisso di destinazione, applicato durante la lettura dei file da disco |

**Come funziona:**
- Si applica solo durante la **lettura dei file da disco** (immagini a piena risoluzione, download, critica VLM). I percorsi del database non vengono mai modificati.
- I backslash e gli slash vengono normalizzati: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` corrispondono entrambi.
- Le mappature vengono valutate in ordine; vince il primo prefisso corrispondente.
- Le destinazioni della mappatura vengono aggiunte automaticamente all'elenco di directory consentite multiutente.

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

Quando impostata, gli utenti devono accedere prima di usare il viewer.

### Modifica locale attendibile

Permette a un viewer a utente singolo, usato solo da un browser sullo stesso computer, di modificare senza password di modifica:

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

Si applica solo quando **sia** `viewer.password` **sia** `viewer.edition_password` sono vuote, la modalità multiutente è disattivata e la configurazione è stata caricata senza errori. Impostare una password di modifica la disattiva. Non imposta né rivela alcuna password, non cambia i token e non abilita l'amministrazione multiutente.

Facet controlla ogni richiesta. Una richiesta è attendibile solo se valgono tutte queste condizioni:

- il peer TCP è un indirizzo di loopback (un peer IPv4 mappato come `::ffff:127.0.0.1` è valutato in base al suo indirizzo IPv4);
- c'è esattamente un header `Host`, e vale `localhost`, `127.0.0.1` o `[::1]`, con una porta facoltativa;
- la richiesta non porta alcun header `Forwarded`, `Via`, `X-Real-IP`, `X-Client-IP`, `True-Client-IP`, `CF-Connecting-IP`, `X-Original-Forwarded-For` o `X-Forwarded-*`;
- un `Origin` o un `Referer`, se presente, indica esattamente schema, host e porta, senza credenziali (un `Origin` con percorso, query o frammento viene rifiutato); un `Sec-Fetch-Site`, se presente, è `same-origin` o `none`.

Qualsiasi altra richiesta è trattata come se l'opzione fosse disattivata, comprese le richieste GET.

Una richiesta attendibile ha pieni diritti di modifica su ogni route riservata all'edizione: valutazioni, confronti, selezione (incluso **Scarta in cartella**, che sposta o cestina file, e l'eliminazione per foto), album, persone e volti, pesi, priorità e contesti di punteggio, incorporamento dei metadati ed esportazioni, ricalcoli e job panorama, generazione di didascalie e critiche. Può anche avviare una scansione senza `viewer.features.show_scan_button`. Il flusso di avanzamento della scansione accetta un token di flusso trusted-local solo dalla stessa macchina locale.

**Assistenti.** La finestra «Collega un assistente» può allora creare un token **Modifica completa** (richiede comunque `viewer.mcp.enabled`).

- Il token agisce come `edition` solo per le richieste `/mcp` che superano i controlli sopra: `http://localhost:<porta>` o `127.0.0.1`, su `:5000` o sul proxy di sviluppo `ng serve` `:4200`.
- Da un client LAN, da un URL con nome host o `0.0.0.0`, o in un deployment Docker, agisce come `readonly`. Impostare una qualsiasi password lo rende `readonly`; rimuoverla lo ripristina.
- Gli strumenti di eliminazione richiedono comunque `viewer.mcp.allow_destructive`. Vedi [Agenti IA (MCP)](AGENTS.md).
- Su un'installazione aperta, creare, elencare e revocare i token degli assistenti funziona solo da una richiesta che supera questi controlli (o da una sessione di edizione quando `viewer.edition_password` è impostata), qualunque cosa dica `trusted_local_editing`.
- `ng serve --host 0.0.0.0`, o un proxy sullo stesso host che non aggiunge alcun header di inoltro, permette a un client LAN di passare con `Host: localhost`. Un reverse proxy deve inviare `X-Forwarded-For` o `Forwarded`.

> **Attenzione:** Solo il controllo di loopback è un vero confine; gli altri header provengono dal client. Un reverse proxy, tunnel o port forward sullo stesso host che non aggiunge nessuno degli header sopra appare identico al tuo browser. Non abilitare mai questa opzione dietro un reverse proxy sullo stesso host. Finché è attiva, ogni processo locale e ogni account del computer può modificare.

### Ricerca online di luoghi

`viewer.place_search_url` ha come valore predefinito `https://photon.komoot.io/api`.

- Imposta `""` per disattivare la ricerca di indirizzi/attività, oppure punta a un endpoint Photon HTTP(S) auto-ospitato (senza credenziali, parametri di query o frammenti).
- Il browser conosce solo `place_search_enabled`, mai l'URL.
- Le ricerche richiedono l'accesso di edizione e un clic esplicito su **Cerca online**. Non ci sono tentativi ripetuti né reindirizzamenti.
- Una richiesta scade dopo cinque secondi; la risoluzione DNS segue il resolver del sistema operativo e può richiedere più tempo.

Vedi [Ricerca online di luoghi](VIEWER.md#ricerca-online-di-luoghi) per privacy, cache e limiti. La [policy della demo Photon](https://github.com/komoot/photon#demo-server) consente un uso ragionevole del progetto senza garanzie di disponibilità; la [documentazione dell'API Photon](https://github.com/komoot/photon/blob/master/docs/api-v1.md) definisce il suo formato GeoJSON.

### Prestazioni del viewer

Sovrascrive le impostazioni globali di `performance` solo per il viewer, ad es. su un NAS con poca memoria.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Dimensione dell'I/O mappato in memoria di SQLite |
| `cache_size_mb` | `128` | Dimensione della cache di SQLite |
| `wal_checkpoint_minutes` | `30` | Facoltativo (assente dal file fornito). Minuti tra i checkpoint WAL in background del viewer; `0` li disattiva |
| `slow_request_ms` | `1000` | Registra le richieste API del viewer più lente di questo valore (WARNING, marcatore `SLOW`); `0` lo disattiva |

Il checkpoint periodico (`PRAGMA wal_checkpoint(TRUNCATE)`) mantiene piccolo il file WAL nelle installazioni di lunga durata; un checkpoint viene eseguito anche allo spegnimento pulito.

---

## Storage

Dove vengono archiviati miniature ed embedding: colonne BLOB nel database SQLite (predefinito), oppure file su disco per mantenere il database più piccolo.

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
| `filesystem_path` | `"./storage"` | Directory di base per la modalità filesystem (`<path>/thumbnails/` e `<path>/embeddings/`) |

**Dettagli della modalità filesystem:**
- I file sono nominati in base all'hash SHA-256 del percorso della foto, in sottodirectory di due caratteri (es. `thumbnails/a3/a3f8..._640.jpg`).
- L'eliminazione di una foto rimuove tutte le sue dimensioni di miniatura e i suoi file di embedding.
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

Ogni webhook riceve una POST JSON. Gli indirizzi privati e di loopback sono bloccati:

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

Diaporame curati raggruppati per tema, generati dalla tua libreria e memorizzati in cache per `freshness_hours`.

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

Le capsule di luogo e viaggio usano il reverse geocoding offline tramite il pacchetto `reverse_geocoder` (dataset GeoNames locale, ~30MB, nessuna chiamata API). I risultati sono memorizzati in cache con risoluzione a griglia di 0,1° (~11km).

Installazione: `pip install reverse_geocoder`

Imposta `"reverse_geocoding": false` per disabilitare e ricadere sulla visualizzazione delle coordinate.

## Similarity Groups

Impostazioni per la selezione delle foto simili, che raggruppa le foto visivamente simili tramite gli embedding CLIP/SigLIP:

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
| `default_threshold` | `0.85` | Similarità coseno minima (0,0–1,0) perché due foto contino come simili; più basso = gruppi più grandi e più larghi |
| `min_group_size` | `2` | Numero minimo di foto necessarie per formare un gruppo di similarità |
| `max_photos` | `10000` | Foto massime caricate per il confronto (il costo cresce come O(n²)) |
| `max_group_size` | `50` | Foto massime per gruppo; i gruppi più grandi vengono suddivisi |

## Auto-Cull

Selezione automatica con un solo pulsante per la camera oscura di selezione (`POST /api/culling/auto`, riservata all'edizione). Seleziona un intero ambito in un solo passaggio: tutti i gruppi, oppure solo raffiche / simili / scene, eventualmente limitati a un album o a un intervallo di date. Ogni gruppo conserva la sua foto migliore più tutto ciò che rientra in un margine fissato dal rigore (come per il cursore della camera oscura), almeno un minimo per gruppo, e rifiuta il resto.

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
| `default_strictness` | `50` | Budget di conservazione (0–100) quando la richiesta omette `strictness`; più alto conserva meno foto per gruppo |
| `highlights_min` | `8.0` | Punteggio aggregato minimo perché la foto migliore di un gruppo entri nell'album facoltativo **Highlights** all'applicazione |

- `dry_run` è attivo per impostazione predefinita e restituisce un'anteprima di conservazione/scarto per gruppo.
- L'applicazione registra confronti `source='culling'` e conta per un auto-riaddestramento. Vedi [Visualizzatore web — Selezione automatica](VIEWER.md#selezione-automatica).
- Le stesse impostazioni alimentano `python facet.py --auto-cull` (vedi [Selezione](COMMANDS.md#selezione-da-terminale)); le sue regole provengono dalla configurazione del server, non da `--config`.

## Riaddestramento automatico

Controlla quando il ranker personale («I miei gusti») si riaddestra. Ogni conferma di scarto e ogni modifica di valutazione si aggiunge a un contatore per utente. Superare `threshold` arma il riaddestramento, che parte quando sei rimasto inattivo per `idle_seconds`, così non rallenta le tue valutazioni.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `threshold` | `25` | Nuovi confronti necessari prima che un riaddestramento venga armato; aumentalo se valuti lotti molto grandi |
| `idle_seconds` | `60` | Secondi senza attività di valutazione/scarto prima che parta il riaddestramento armato; `0` lo avvia subito |
| `backend` | `"native"` | `"native"` addestra in locale; `"external"` conserva soltanto preferenze e conteggi. Vedi [Backend di apprendimento esterno](#backend-di-apprendimento-esterno) |

Le variabili d'ambiente sovrascrivono `threshold` e `idle_seconds` (comode con Docker):

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variabile | Sovrascrive |
|-----------|-------------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- Un `threshold` o `idle_seconds` non valido ricade sul valore JSON, poi sul valore predefinito integrato. Entrambi vengono letti all'avvio; le modifiche richiedono un riavvio.
- Un `auto_retrain.backend` non valido ricade su `"external"` (vedi sotto).
- Un riaddestramento che non batte il modello attuale sui dati riservati non salva nulla.

### Backend di apprendimento esterno

`"backend": "external"` conserva valutazioni, confronti e conteggi in sospeso, ma non addestra né valuta mai localmente il ranker personale, la testa di selezione o i pesi appresi. Usalo quando un flusso separato, gestito dall'operatore, addestra e pubblica i punteggi. Facet non avvia alcun worker esterno.

In modalità esterna:
- I comandi manuali del ranker personale, della testa di selezione e dell'apprendimento dei pesi segnalano che l'addestramento è rinviato.
- Le probabilità di conservazione non sono disponibili; le risposte di Confronto sui pesi appresi e sulla confidenza riportano `available: false`.
- Il punteggio normale delle foto e i voti non sono interessati.

Un blocco `auto_retrain` malformato, un `backend` diverso da `"native"` o `"external"`, o una configurazione illeggibile selezionano la modalità esterna e registrano un avviso. Una configurazione valida senza chiave `backend` usa la modalità nativa.

## Profili di scarto per genere

Preset per genere che impostano ogni controllo di scarto con un clic, da un selettore nella camera oscura di selezione. Lo sport conserva solo il fotogramma più nitido di una lunga raffica; i matrimoni conservano più varianti e richiedono occhi aperti; i concerti allentano i controlli su occhi/espressione; la fauna selvatica elimina il controllo sui volti.

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
| `profiles.<id>.strictness` | Budget di conservazione (0–100) per l'auto-scarto con questo preset |
| `profiles.<id>.eyes_closed_max` | Punteggio occhi aperti (0–10) pari o inferiore al quale un volto è considerato chiuso (sovrascrive `face_detection.eyes_closed_max`) |
| `profiles.<id>.poor_expression_min` | Punteggio espressione/sorriso (0–10) sotto il quale un volto è considerato scarso (sovrascrive `face_detection.poor_expression_min`) |
| `profiles.<id>.keep_min_per_group` | Minimo per gruppo sull'insieme conservato dall'auto-scarto |
| `profiles.<id>.similarity_threshold` | Soglia di raggruppamento per similarità (percentuale) applicata dalla camera oscura quando il preset è selezionato |

`GET /api/culling/profiles` restituisce l'elenco ordinato dei preset e il predefinito. `POST /api/culling/auto` e `POST /api/culling-group/faces` accettano un id `profile` facoltativo; un `strictness`/`min_keep_per_group` esplicito nella richiesta prevale sul preset.

## Scenes

Impostazioni per la vista Scene, che raggruppa le foto principali delle raffiche in scene cronologiche (suddivise sugli intervalli nel tempo di scatto) per la selezione in ordine narrativo:

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
| `gap_minutes` | `20.0` | Intervallo tra due foto principali di raffica consecutive che avvia una nuova scena (il limite inferiore quando `adaptive` è attivo) |
| `min_size` | `2` | Foto minime perché una scena venga mostrata |
| `max_photos` | `5000` | Foto principali di raffica massime caricate per il raggruppamento in scene |
| `max_scene_size` | `60` | Le scene più grandi vengono suddivise di nuovo in corrispondenza dei loro maggiori intervalli interni |
| `adaptive` | `true` | Amplia l'intervallo a `adaptive_k × mediana` degli intervalli dello scatto (più stretto per scatti rapidi, più largo per viaggi radi) |
| `adaptive_k` | `6.0` | Moltiplicatore applicato all'intervallo mediano quando `adaptive` è attivo |
| `split_on_moment_change` | `false` | Con i momenti narrativi calcolati, suddivide anche dove il momento dominante cambia per `moment_split_min_run` fotogrammi |
| `moment_split_min_run` | `4` | Fotogrammi consecutivi per cui un nuovo momento deve durare per forzare un confine di scena |

## Narrative Moments

Etichetta senza addestramento il "momento" di scena o attività di ogni foto. Il vocabolario **general** predefinito copre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` oppure `other`. `wedding` è incluso come genere opt-in. `--detect-moments` li popola (viene eseguito anche alla fine di ogni scansione); compaiono come nomi di scena e come filtro della galleria.

Facet confronta la didascalia AI di ogni foto, codificata una sola volta e memorizzata (`caption_embedding`), con i prompt testuali di ciascun momento e tiene la corrispondenza migliore. Senza didascalia usa l'embedding dell'immagine. Le didascalie corrispondono in modo più netto, quindi il segnale `caption` ha soglie più alte del ripiego `image`, regolate per backend. I valori `transformers` (SigLIP) sono predefiniti prudenti; regolali di nuovo se usi un profilo SigLIP.

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
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
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
| `default_event_type` | `"general"` | Vocabolario `event_types` attivo (`general` = 20 momenti; `wedding` opt-in) |
| `pooling` | `"max"` | Punteggio per momento = la migliore corrispondenza di un singolo prompt |
| `caption_min_confidence` | `0` | Se > 0, la generazione delle didascalie salta le foto non etichettate, `other` o al di sotto di questa confidenza; `0` = nessun gate |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Sotto questo coseno top-1 una foto è `other` (indicizzato per segnale, poi per backend) |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Divario coseno top-1/top-2 minimo; al di sotto il fotogramma è `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Piccole spinte su volti/tag che rompono solo i quasi-pareggi; `weight` limita ogni spinta |
| `priors.caption_tag_scale` | `0.25` | Riduce le regole `tag` sul segnale della didascalia; le regole strutturali mantengono il peso pieno |
| `priors.rules` | (set generale) | Elenco di regole `{kind, when, boost}` (vedi sotto) |
| `priors.event_types.<et>.rules` | override `wedding` | Regole che **sostituiscono** le `rules` globali quando quel vocabolario è attivo |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Levigatura della timeline tra fotogrammi vicini (`weight=0` = nessuna) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Su 16gb/24gb, riclassifica con il VLM del profilo solo i fotogrammi a bassa confidenza o a basso margine |
| `event_types` | `general` + `wedding` | Per ogni tipo di evento `{moment: [sinonimi di prompt]}`; imposta `default_event_type` per cambiare genere o aggiungere il tuo |

Formato di `priors.rules`:
- `kind`: `structural` (geometria dei volti) oppure `tag`.
- `when` (devono corrispondere tutti): `is_group_portrait`, `face_count_min`/`face_count_max`, `face_ratio_min`/`face_ratio_max`, `tags_any`, `tags_all`.
- `boost`: `{momento: quantità}`. Un momento assente dal vocabolario attivo viene ignorato.

Il confronto VLM per gli spareggi viene eseguito durante `--detect-moments` / `--recompute-moments`.

> **Costo del backfill delle didascalie.** Gli embedding delle didascalie vengono calcolati una sola volta e memorizzati. Una scansione codifica solo le sue nuove didascalie, ma il primo passaggio su una libreria esistente le codifica tutte: veloce su GPU, ore su CPU. Esegui `python facet.py --detect-moments` una volta (GPU consigliata); aggiungi `--limit N` per provare prima su un campione.

**Scoprire un vocabolario specifico per la libreria.** `python facet.py --discover-moments` raggruppa i vettori `caption_embedding` memorizzati, assegna un nome a ogni gruppo a partire dalle sue didascalie e scrive un blocco `event_types.discovered` in `scoring_config.discovered.json`. Non modifica mai la configurazione attiva. Per adottarlo, copia `discovered` in `event_types`, imposta `default_event_type` su `discovered` ed esegui `--recompute-moments`. `--discover-min-cluster-size N` controlla la granularità (più piccolo = più momenti, più fini).

## OCR

Ricerca del testo nelle foto: legge le parole *all'interno* delle tue foto (cartelli stradali, insegne di negozi, pettorali di gara, dorsi di libri, diapositive, lavagne, documenti scansionati) in `photos.ocr_text`. Quel testo è poi ricercabile dalla casella di ricerca della galleria come qualsiasi didascalia o tag; `GET /api/search?scope=text` cerca solo nei campi di testo.

**Disattivato per impostazione predefinita**, e richiede l'installazione di un motore:

```bash
pip install easyocr           # o: pip install -e .[ocr]
```

Poi abilitalo ed esegui il passaggio:

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # solo le foto mai valutate
python facet.py --recompute-text   # rilegge l'intera libreria
```

| Chiave | Predefinito | Descrizione |
|-----|---------|-------------|
| `enabled` | `false` | Interruttore principale; `--detect-text` rifiuta di essere eseguito finché è `false` |
| `languages` | `["en", "fr"]` | Codici lingua passati al motore; una sola famiglia di script per esecuzione (easyocr rifiuta ad es. `en` + `ja`) |
| `min_confidence` | `0.4` | Scarta i rilevamenti valutati al di sotto di questo valore (0–1); aumentalo contro il rumore, abbassalo per il testo debole |
| `full_resolution` | `false` | Esegue l'OCR sull'originale invece che sulla miniatura da 640px (molto più lento; ripiega sulla miniatura se offline) |

Note:
- `ocr_text` è `NULL` finché una foto non viene valutata e `''` quando non contiene testo. `--detect-text` legge solo le foto `NULL`; `--recompute-text` rilegge tutto.
- **Non serve `--rebuild-fts`:** il passaggio aggiorna l'indice di ricerca mentre scrive. `python database.py --rebuild-fts` serve solo per un database creato prima dell'OCR, e `init_database` se ne occupa per te.
- La miniatura da 640px risolve già cartelli, poster e intestazioni di documenti.

**Motori.** `easyocr` (Apache-2.0, PyTorch) è quello predefinito e riutilizza lo stack esistente di Facet. I suoi pesi (~113MB) vengono scaricati dalle release GitHub del progetto al primo avvio. Il binario `tesseract` con `pytesseract` viene usato quando easyocr è assente, ma legge peggio il testo delle scene. Se nessuno dei due è installato, il passaggio termina con un errore.

**Costo.** Circa 0,4s per miniatura su CPU, quindi una libreria da 50.000 foto è un lavoro notturno una tantum; le scansioni successive aggiungono solo foto nuove. Una GPU viene usata automaticamente quando torch ne segnala una.

## Destinazioni di esportazione e scarto

Esportazione di album (`POST /api/albums/{id}/export`, modalità `copy`/`symlink`) e scarto in cartella (`POST /api/cull/apply`, azioni `copy_keeps` / `move_rejects`) scrivono in un `target_dir`. Deve risolversi sotto una radice consentita, altrimenti la richiesta viene rifiutata prima di toccare qualsiasi file.

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `allowed_target_dirs` | *(chiave assente)* | Radici aggiuntive in cui esportazione e scarto in cartella possono scrivere, oltre alle directory di scansione (sempre consentite) |
| `cull.allow_trash` | `false` | Consente l'azione `trash_rejects` dello scarto in cartella (cestino del sistema tramite `send2trash`, recuperabile); disattivato nasconde l'opzione |

**Serie multi-scatto e azioni collettive.** Con `hide_brackets` / `hide_panoramas` attivi (il predefinito, vedi [Visualizzatore web — Filtri predefiniti](VIEWER.md#filtri-predefiniti)), una selezione contiene solo il fotogramma rappresentativo di ogni serie, quindi le azioni collettive agiscono solo su quel fotogramma. L'opzione `include_sequence_siblings` dello scarto in cartella estende una foto corrispondente all'intera serie; vedi [Visualizzatore web — Scarta in cartella § Serie multi-scatto](VIEWER.md#scarta-in-cartella).

**Ordine di risoluzione.** Le radici consentite sono `allowed_target_dirs`, poi ogni directory di scansione (per utente, condivisa e i target di `path_mapping`). Esportare dentro l'albero fotografico non richiede configurazione; una destinazione al di fuori richiede una voce qui. Link simbolici e `..` vengono risolti prima del controllo (`os.path.realpath()`), quindi un link che punta fuori da una radice consentita viene rifiutato.

**Chiuso per impostazione predefinita (fail-closed).** Senza `allowed_target_dirs` né directory di scansione, l'esportazione copia/symlink/sposta viene rifiutata.

**Risoluzione dei problemi di "accesso negato".** L'interfaccia web mostra un toast generico "Accesso negato". Per scoprirne il motivo, apri la scheda Rete del browser, trova la richiesta fallita `/api/cull/apply` o `/api/albums/{id}/export` e leggi il campo `detail`: o questa allow-list, o una sessione di edizione scaduta. Un vero errore di permessi del filesystem è diverso: la richiesta riesce, il conteggio `errors` della risposta è diverso da zero e il log del server contiene un traceback per file. Per il caso del container vedi [Deployment — Semantica dei percorsi nel container](DEPLOYMENT.md#semantica-dei-percorsi-nel-container).

Vedi [Visualizzatore web — Scarta in cartella](VIEWER.md#scarta-in-cartella) e [Visualizzatore web — Esportazione per editor](VIEWER.md#esportazione-per-editor).

## Esportazione social

Preset di ritaglio per i rapporti d'aspetto dei social, inquadrati sul soggetto (`GET /api/photo/social_crop`, riservato all'edizione). Ogni preset ritaglia l'originale a piena risoluzione al rettangolo più grande di quel rapporto, centrato sul soggetto. Il soggetto è il riquadro BiRefNet (`photos.subject_bbox`), altrimenti l'unione dei riquadri dei volti, altrimenti il centro dell'immagine. Vedi [Visualizzatore web — Download](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Percorso i18n con punti per il nome visualizzato del preset (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Rapporto d'aspetto obiettivo come `"l:h"` (es. `1:1`, `4:5`, `9:16`) |
| `jpeg_quality` | `92` | Qualità JPEG del ritaglio esportato |

Controllato da `viewer.features.show_social_export` (predefinito `true`). Il riquadro del soggetto è scritto dalla passata di salienza in fase di scansione e da `--recompute-saliency`; le foto più vecchie usano il ritaglio sui volti o al centro.

## Esportazione portfolio

Esporta un album come galleria HTML statica e autonoma che puoi caricare su qualsiasi hosting web (`POST /api/albums/{album_id}/export-portfolio`, solo edizione).

- La cartella di output contiene `index.html` (griglia di miniature e lightbox, senza riferimenti esterni o CDN), una cartella `assets/` di JPEG con nomi sequenziali (nessun percorso della libreria) e un `manifest.json`.
- Ogni foto usa l'**originale**, ridotto a `max_edge`, oppure la miniatura da 640px memorizzata quando l'originale è irraggiungibile. Il manifest registra quale.
- Riesportare riscrive solo i propri file.

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
| `max_photos` | `500` | Gli album più grandi vengono rifiutati (l'esportazione è sincrona) |
| `max_edge` | `2048` | Limite del lato lungo (px) per gli originali esportati; la richiesta può sovrascriverlo (limitato 256–8000) |
| `jpeg_quality` | `88` | Qualità JPEG delle immagini esportate |

Il `target_dir` usa la stessa allow-list delle altre esportazioni (`viewer.export.allowed_target_dirs` più le directory di scansione — vedi [Destinazioni di esportazione e scarto](#destinazioni-di-esportazione-e-scarto)). Controllato da `viewer.features.show_portfolio_export` (predefinito `true`). Vedi [Visualizzatore web — Esportazione portfolio](VIEWER.md#esportazione-portfolio).

## Endpoint agente (MCP)

Espone gli strumenti descritti in [Agenti IA (MCP)](AGENTS.md) su `POST /mcp`: lettura, controllo della scheda aperta e, a seconda del livello del token, modifica di valutazioni, tag e album, selezione ed eliminazione. È attivo per impostazione predefinita.

Su un'installazione aperta (senza `viewer.password`):
- `/mcp` serve solo una chiave anonima di sola lettura, che non mostra nulla che l'`/api` aperta non mostri già.
- Un nuovo token è `readonly`, a meno che `viewer.trusted_local_editing` sia attivo o la sessione abbia effettuato l'accesso con `viewer.edition_password`: entrambi possono creare un token con modifica completa, che modifica solo per le richieste dalla stessa macchina.
- I token possono essere creati, elencati e revocati solo dal computer su cui gira Facet (o in una sessione di edizione quando `viewer.edition_password` è impostata).

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| Chiave | Predefinito | Descrizione |
|-----|---------|-------------|
| `enabled` | `true` | Interruttore generale di `/mcp` e `/api/mcp/*` |
| `bridge` | `true` | Consente il ponte verso la scheda del browser (`/api/mcp/bridge`) così gli strumenti `ui_*` raggiungono una scheda; richiede un solo worker |
| `max_rows` | `100` | Numero massimo di righe in un risultato di strumento (da 1 a 500); le righe in eccesso impostano `truncated: true` |
| `max_bytes` | `60000` | Dimensione serializzata massima di un risultato di strumento in byte (da 4000 a 500000). |
| `max_image_bytes` | `262144` | Dimensione massima dell'immagine di `get_thumbnail` o `contact_sheet` (da 32768 a 2097152); non conteggiata in `max_bytes` |
| `call_timeout_s` | `30` | Timeout di una chiamata di strumento in secondi (da 1 a 300), anche l'attesa di `ui_*` per la scheda (`tab_timeout`) |
| `semantic_timeout_s` | `120` | Timeout di `semantic_search` in secondi (da 1 a 300); carica il modello di embedding e richiede più tempo. |
| `rate_per_min` | `120` | Chiamate di strumento al minuto per token (minimo 1). |
| `write_rate_per_min` | `30` | Chiamate di scrittura al minuto per token (minimo 1), separate perché le letture non affamino le scritture |
| `tool_profile` | `"full"` | `"full"` elenca ogni strumento consentito; `"core"` elenca un insieme di 11 strumenti per i modelli piccoli |
| `allow_destructive` | `false` | Consente `delete_photos`, `move_rejects`/`trash_rejects` di `cull_apply` e `assign_faces` con `allow_reassign` |
| `inpage_tools` | `true` | Consente a una scheda autenticata di chiamare gli strumenti del server dalla pagina (`GET /api/mcp/inpage_tools`, `POST /api/mcp/call`) |
| `allowed_origins` | `[]` | Origini del browser aggiuntive (es. `["https://photos.example.com"]`) autorizzate ad aprire il ponte della scheda dietro un proxy che riscrive `Host`; non è la chiave CORS `viewer.allowed_origins` |

Note:
- **`enabled: false`** disattiva `/mcp` e `/api/mcp/*` (il ponte si chiude con il codice 4404). **`bridge: false`** rifiuta il ponte e fa restituire un errore agli strumenti `ui_*`.
- **`write_rate_per_min`** vale per gli strumenti di scrittura, inclusa la simulazione di `cull_apply` e `delete_photos`; vedi [Agenti IA](AGENTS.md#modificare-la-libreria).
- **`"core"`** elenca `status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`. Cambia solo l'elenco; gli altri strumenti restano chiamabili se il livello della chiave lo consente. Qualsiasi altro valore equivale a `"full"`. Vedi [Agenti IA](AGENTS.md#livelli-di-autorizzazione).
- **`allow_destructive: false`** nasconde `delete_photos`; gli altri due rispondono `feature_disabled` indicando questa chiave. Vedi [Agenti IA](AGENTS.md#azioni-distruttive-anteprima-poi-conferma).
- **`inpage_tools`** esegue gli strumenti come la sessione, al suo livello attuale. Disattivato, `features.mcp_inpage` è false in `/api/auth/status`. Vedi [Agenti IA](AGENTS.md#webmcp-nella-pagina-agenti-del-browser).
- I numeri fuori intervallo vengono riportati nei limiti; un valore di tipo errato usa il predefinito. Le modifiche si applicano al ricaricamento della configurazione, senza riavvio.

## Cornice digitale / Chiosco

Distribuisce gli «scatti migliori» curati a dispositivi in modalità chiosco senza login: cornici digitali smart, dashboard Home Assistant, display in stile ImmichFrame / Immich-Kiosk. Tre endpoint usano un token statico: `GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`. Un elenco `tokens` vuoto disabilita la funzione (gli endpoint rispondono 404). Le risposte non contengono mai percorsi di file; le foto sono indirizzate da un id firmato.

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
| `tokens` | `[]` | Token di cornice, una stringa casuale lunga per dispositivo; rimuovine uno per revocarlo. **Vuoto = funzione disattivata.** |
| `count` | `20` | Numero predefinito di foto restituite da `/api/frame/photos` |
| `max_count` | `100` | Limite rigido del parametro di query `count` |
| `min_aggregate` | `7.0` | Punteggio aggregato minimo perché una foto venga curata |
| `max_edge` | `1920` | Limite del lato lungo (px) dei JPEG serviti; il parametro `max_edge` può solo abbassarlo |
| `favorites_only` | `false` | Se `true`, vengono curate solo le foto preferite |
| `categories` | `[]` | Elenco consentito di nomi di categoria (vuoto = tutte) |

Genera un token con `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

La curatela esclude le foto rifiutate, spazzatura (`junk_kind`) e con occhi chiusi, applica i filtri di punteggio, preferiti e categorie, poi sceglie un campione casuale ponderato per punteggio. La ricetta Home Assistant è in [Visualizzatore web — Cornice digitale / Chiosco](VIEWER.md#cornice-digitale--chiosco).

> **Avvertenza:** Un token di cornice non è un login utente. In [modalità multiutente](#users) ignora le `directories` private di ciascun utente e può leggere le foto di tutti gli utenti, non solo `shared_directories`. Emetti token di cornice solo dove ogni utente lo accetta.

## Caricamento automatico dal telefono

Un endpoint **WebDAV** minimale su `/dav` consente alle app di caricamento automatico dal telefono (PhotoSync e simili) di inviare foto in una **cartella di ingresso** (inbox), che `facet.py --watch` valuta poi. L'accesso usa HTTP Basic con **credenziali di dispositivo condiviso** (`username` / `password`), non un account utente.

- `/dav` restituisce **404** finché `username`, `password` e `inbox_dir` non sono tutti impostati.
- Ogni operazione resta dentro `inbox_dir`; traversal dei percorsi, percorsi assoluti e fughe tramite link simbolici vengono rifiutati.
- I caricamenti vengono scritti in modo atomico e limitati a `max_file_mb`.

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

| Impostazione | Predef. | Descrizione |
|--------------|---------|-------------|
| `username` | `""` | Nome utente HTTP Basic (credenziale di dispositivo condiviso). **Vuoto = funzione disattivata.** |
| `password` | `""` | Password HTTP Basic; usa una stringa casuale lunga. **Vuoto = funzione disattivata.** |
| `inbox_dir` | `""` | Percorso assoluto della cartella di ingresso, creata su richiesta. **Vuoto = funzione disattivata.** |
| `max_file_mb` | `500` | Limite di dimensione per file (MB); un caricamento più grande viene interrotto e non lascia alcun file parziale |

Punta `inbox_dir` a una directory scansionata (o a una sua sottodirectory) affinché `facet.py --watch` valuti i caricamenti man mano che arrivano.

Metodi supportati: `OPTIONS`, `PROPFIND` (profondità 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (niente `LOCK`/`UNLOCK`). Un'intestazione `Authorization` mancante o errata riceve `WWW-Authenticate: Basic realm="Facet upload"`. La ricetta PhotoSync e un test rapido con `curl` sono in [Visualizzatore web — Caricamento automatico dal telefono](VIEWER.md#caricamento-automatico-dal-telefono).

## Junk Sweep

Segnala la "spazzatura" non fotografica (screenshot, documenti scansionati, ricevute, meme, diapositive di presentazione) a partire dall'**embedding immagine memorizzato**, senza decodificare l'immagine. Ogni tipo ha un elenco di prompt testuali, e il prompt più vicino conta per quel tipo.

- Una foto viene segnalata solo quando il suo miglior tipo di spazzatura raggiunge `min_confidence` **e** supera di `min_margin` il miglior prompt `not_junk`.
- Altrimenti viene memorizzata come `not_junk` (valutata, pulita). `NULL` significa non ancora valutata.
- `--detect-junk` etichetta solo le foto `NULL` (viene eseguito anche a fine scansione); `--recompute-junk` ricontrolla l'intera libreria.
- I risultati vanno in `photos.junk_kind`, rivisti nella coda **Junk Sweep** del visualizzatore ([VIEWER.md](VIEWER.md#pulizia-degli-scarti)).

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `enabled` | `true` | Esegue il rilevamento di spazzatura durante `--detect-junk` / `--recompute-junk` e al termine della scansione |
| `prompt_template` | `"{desc}"` | Stringa di formato applicata a ogni prompt (`{desc}` = il prompt); invariato per impostazione predefinita |
| `pooling` | `"max"` | Combina i punteggi dei prompt per tipo tramite `max` (miglior prompt singolo) o `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Punteggio minimo per il miglior tipo di spazzatura (per backend; i punteggi CLIP/`open_clip` sono più bassi di quelli SigLIP/`transformers`) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Quanto il miglior tipo di spazzatura deve superare il miglior prompt di contrasto `not_junk` prima che la foto venga segnalata |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinonimi di prompt]}`; aggiungi, rimuovi o rinomina i tipi liberamente |
| `not_junk_prompts` | 8 prompt fotografici | Prompt che descrivono fotografie autentiche, che tengono le foto genuine fuori dalla coda |

## AI Critique

Impostazioni del prompt per la critica VLM (profili 16gb/24gb). La critica fornisce al VLM la scomposizione del punteggio, le penalità e l'EXIF e mostra la sua risposta come Osservazione / Valutazione / Suggerimenti.

- La Valutazione copre composizione, colore & luce, messa a fuoco/PdC & esecuzione tecnica, e soggetto & momento, confrontati con le metriche.
- Viene memorizzata nella cache per foto (`photos.vlm_critique`, traduzioni in `vlm_critique_translated`); `refresh` la rigenera.
- Viene eseguita sulla miniatura memorizzata, quindi funziona anche con i file RAW.

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

## VLM Backend

Sceglie dove viene eseguito il modello visione-linguaggio per didascalie/tag. `local` (predefinito) usa il modello Qwen integrato dei profili 16gb/24gb. I due backend remoti usano un server esterno, quindi didascalie e tagging VLM funzionano anche sui **profili legacy/8gb che non includono alcun VLM locale**.

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
| `type` | `"local"` | `local` (Qwen integrato), `ollama` (API REST di Ollama) oppure `openai_compatible` (LM Studio, vLLM, OpenRouter, …) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base del server Ollama (le immagini vanno a `POST /api/generate`) |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag del modello Ollama (deve essere un modello vision già scaricato sul server) |
| `ollama.timeout_seconds` | `120` | Timeout per richiesta per le chiamate Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base **incluso il suffisso `/v1`** (le richieste vanno a `{base_url}/chat/completions`, con l'immagine come URI di dati `image_url`) |
| `openai_compatible.api_key` | `""` | Inviato come `Authorization: Bearer <chiave>`; lascia vuoto per i server locali senza autenticazione |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nome del modello passato all'endpoint |
| `openai_compatible.timeout_seconds` | `120` | Timeout per richiesta per le chiamate compatibili OpenAI |

Il backend gestisce le didascalie (`--generate-captions` e `/api/caption`), la critica VLM (`/api/critique?mode=vlm`), il ri-tagging VLM (`--recompute-tags-vlm`) e lo spareggio VLM dei momenti narrativi. Una richiesta remota non riuscita fa fallire solo quella foto (registrata nel log, nessun tag o didascalia). Il tagging durante la scansione usa ancora il tagger del profilo; esegui `--recompute-tags-vlm` per applicare un backend remoto a una libreria esistente.

## Distortion Attributes

Etichette indicative di distorsione. `--recompute-distortions` confronta l'embedding CLIP/SigLIP memorizzato di ogni foto con prompt per i difetti comuni (sfocatura da movimento, dominante di colore, eccessiva nitidezza, …) e memorizza quelli probabili. Non influiscono mai sul punteggio; appaiono come chip di avviso nella finestra di critica.

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
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura softmax sui punteggi dei prompt, per backend di embedding (le scale differiscono, come in `narrative_moments`) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilità minima perché un'etichetta di distorsione venga mantenuta |
| `vocabulary` | `{}` | Override facoltativo dei prompt integrati (`{attributo: [sinonimi di prompt]}`); vuoto = valori predefiniti |

## Skin Tone

Controllo indicativo del tono della pelle nei ritratti. `--recompute-skin-tone` misura il colore delle guance sulle miniature dei volti memorizzate e segnala i ritratti la cui pelle vira verso il verde, il magenta, il blu o il giallo. Non influisce mai sul punteggio; il risultato appare come nota nella finestra di critica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Distanza CIEDE2000 minima dai toni naturali della pelle prima che venga segnalata una dominante di colore |

## Immich Sync

Sincronizzazione unidirezionale delle valutazioni a stelle e dei preferiti di Facet verso un server [Immich](https://immich.app/) tramite la sua API REST. Gli asset vengono abbinati tramite `originalPath` attraverso `path_map`. Esegui `--immich-sync` (prima verifica con `--immich-test`); vedi [Comandi — Immich Sync](COMMANDS.md#immich-sync).

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
      "rejected": false,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "webhook": {
      "token_env": "",
      "header": "x-facet-token",
      "max_pending": 500
    },
    "timeout_seconds": 30
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `url` | `""` | URL di base del server Immich (es. `http://nas:2283`) |
| `api_key` | `""` | Chiave API di Immich, inviata come intestazione `x-api-key` |
| `owner_id` | `""` | ID esatto del proprietario, facoltativo; gli asset che ne sono privi o appartengono ad altri vengono ignorati |
| `library_id` | `""` | ID esatto della libreria, facoltativo; vuoto = nessun filtro di libreria |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Riscritture di prefisso dai percorsi di Facet a `originalPath` di Immich; vince il primo `facet_prefix` corrispondente |
| `push.ratings` | `true` | Invia le valutazioni a stelle (si scrive solo 1–5, mai 0/−1) |
| `push.favorites` | `true` | Invia il contrassegno di preferito |
| `push.rejected` | `false` | Invia `rating: -1` per le foto rifiutate in Facet. Richiede `push.ratings` |
| `push.top_picks_album` | `""` | Nome facoltativo di un album Immich che raccoglie le foto inviate sopra la soglia di valutazione. Vuoto = nessun album |
| `push.top_picks_min_rating` | `4` | Valutazione a stelle minima perché una foto venga aggiunta a `top_picks_album` |
| `webhook.token_env` | `""` | Variabile d'ambiente che contiene il segreto condiviso del webhook in entrata; vuoto o non impostato disabilita il webhook |
| `webhook.header` | `"x-facet-token"` | Intestazione in cui il workflow di Immich invia il token |
| `webhook.max_pending` | `500` | Limite massimo dell'elenco dei percorsi memorizzati ma non ancora valutati, segnalato dalla sincronizzazione successiva |
| `timeout_seconds` | `30` | Timeout REST per richiesta |

`--immich-sync` supporta `--dry-run` (abbina ogni asset, non scrive nulla) e `--user` (invia le valutazioni di `user_preferences` di quell'utente in modalità multiutente). Facet usa solo l'API REST e non tocca mai il database di Immich.

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
| `photos_per_group` | `30` | Foto caricate per gruppo di data; valori più alti ne mostrano di più per data ma rendono le pagine più pesanti |

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
| `cluster_zoom_threshold` | `10` | Livello di zoom in cui i marcatori singoli sostituiscono i cluster; da 1 (mondo) a 18 (strada) |

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
| `target_language` | `"fr"` | Lingua di destinazione per `--translate-captions`: `fr`, `de`, `es`, `it`, `pt` (portoghese brasiliano) |

La traduzione usa i modelli Helsinki-NLP MarianMT sulla CPU; non serve alcuna GPU.

## Aesthetic CLIP (R2)

Un punteggio estetico aggiuntivo calcolato dagli embedding CLIP/SigLIP memorizzati in cache e da prompt testuali. Usa `scripts/benchmark_aesthetic.py` per misurare l'effetto di una modifica dei prompt su AVA.

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

Gli array vuoti usano i valori predefiniti di `analyzers/aesthetic_clip.py`. Riesegui il benchmark AVA prima di modificarli: i valori predefiniti ottengono un SRCC ~0,52 su `ava_test/`, e le modifiche lo fanno facilmente scendere a ~0,30.

## Adding alternative VLM tagger / critique models (R3)

La chiave `tagging_model` di ogni profilo (es. `qwen3.5-2b`) indica una voce di modello nella stessa sezione `models`. Per provare un altro VLM (Pixtral-12B, InternVL-2.5, ecc.):

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

Nessuna modifica al codice necessaria. Confronta ~30 foto affiancate prima di renderlo il valore predefinito.

## Secret del server

Il secret che firma i token di sessione e i link della cornice digitale **non** è una chiave di questo file. Risiede in `.facet_secret`, accanto a `scoring_config.json` (modo `0600`, ignorato da git), e viene generato al primo avvio.

- Override: la variabile d'ambiente `FACET_JWT_SECRET`.
- Rotazione: `python database.py --rotate-secret`.

Un `share_secret` di un'installazione precedente viene spostato in quel file al riavvio successivo e rimosso da `scoring_config.json`. Vedi [Archiviazione e rotazione del secret](DEPLOYMENT.md#archiviazione-e-rotazione-del-secret).
