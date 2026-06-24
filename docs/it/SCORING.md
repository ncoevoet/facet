# Sistema di punteggio

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · **Italiano** · [Español](../es/SCORING.md)

Le foto vengono classificate in una categoria e poi valutate con i pesi di quella categoria.

## Come funziona il punteggio

1. **Rilevamento della categoria** - La foto viene analizzata per il contenuto (volti, tag, dati EXIF)
2. **Valutazione dei filtri** - Le categorie vengono valutate in ordine di priorità finché una non corrisponde
3. **Applicazione dei pesi** - I pesi specifici della categoria vengono applicati alle metriche
4. **Applicazione dei modificatori** - Bonus, penalità e flag di comportamento vengono applicati
5. **Punteggio finale** - Somma ponderata limitata all'intervallo 0-10

## Categorie

`scoring_config.json` definisce 34 categorie (33 nominate più `default`), valutate in ordine di priorità crescente finché una non corrisponde. La priorità più bassa vince. L'elenco completo si trova nell'array `categories`; le principali:

| Priorità | Categoria | Metodo di rilevamento |
|----------|----------|------------------|
| 8 | `art` | Tag: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tag: aurora, astrophotography, stars, milky way |
| 15 | `concert` | Tag: concert |
| 35 | `group_portrait` | Rapporto volto ≥ 5% E is_group_portrait |
| 42 | `silhouette` | Ha un volto E is_silhouette |
| 45 | `portrait` | Rapporto volto ≥ 5%, non silhouette/gruppo/mono |
| 46 | `portrait_bw` | Ritratto monocromatico (volto ≥ 5%) |
| 55 | `macro` | Tag: macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Tag: animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Otturatore 1-10 secondi |
| 85 | `night` | Luminanza < 0.15 |
| 88 | `monochrome` | is_monochrome (saturazione < 5%) |
| 95 | `street` | Tag: street, urban_culture |
| 96 | `human_others` | Ha un volto E rapporto volto < 5% |
| 100 | `landscape` | Tag: landscape, mountain, beach, forest, ... |
| 999 | `default` | Ripiego (nessun filtro) |

Altre categorie basate sui tag includono `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic` e `weather`.

## Definizione di una categoria

Ogni categoria in `scoring_config.json` ha questi componenti:

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

## Riferimento dei filtri

### Filtri per intervallo numerico

| Filtro | Campo | Descrizione |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Area del volto come frazione (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Numero di volti |
| `iso_min` / `iso_max` | `ISO` | ISO della fotocamera |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Tempo di esposizione (secondi) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Luminosità (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Lunghezza focale (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Numero f del diaframma |

### Filtri booleani

| Filtro | Descrizione |
|--------|-------------|
| `has_face` | Almeno un volto rilevato |
| `is_monochrome` | Saturazione < 5% |
| `is_silhouette` | Controluce con ombre/alte luci marcate |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurabile, predefinito: 4) |

### Filtri per tag

| Filtro | Descrizione |
|--------|-------------|
| `required_tags` | Elenco di tag che la foto deve avere |
| `excluded_tags` | Elenco di tag che la foto NON deve avere |
| `tag_match_mode` | `"any"` (predefinito) o `"all"` |

## Chiavi dei pesi

Tutti i pesi usano il suffisso `_percent`. Vengono normalizzati da `get_weights()`, quindi i totali non devono essere esattamente uguali a 100 — ma mantenerli a 100 conserva i punteggi sulla scala 0-10.

| Chiave | Metrica | Origine | Ideale per |
|-----|--------|--------|----------|
| `aesthetic_percent` | Attrattiva visiva | TOPIQ o CLIP+MLP | Tutte |
| `quality_percent` | Qualità legacy | Ridistribuita in `aesthetic` (nessun segnale separato) | — |
| `face_quality_percent` | Chiarezza del volto | InsightFace | Ritratti |
| `eye_sharpness_percent` | Nitidezza degli occhi | Landmark InsightFace | Ritratti |
| `tech_sharpness_percent` | Nitidezza complessiva | Varianza laplaciana | Paesaggi |
| `composition_percent` | Composizione | SAMP-Net o basata su regole | Tutte |
| `exposure_percent` | Bilanciamento dell'esposizione | Analisi dell'istogramma | Tutte |
| `color_percent` | Armonia dei colori | Analisi HSV | Foto a colori |
| `contrast_percent` | Contrasto tonale | Ampiezza dell'istogramma | B/N |
| `dynamic_range_percent` | Gamma tonale | Analisi dell'istogramma | HDR, paesaggi |
| `isolation_percent` | Separazione del soggetto | Volto vs sfondo | Ritratti, fauna selvatica |
| `leading_lines_percent` | Linee guida | Rilevamento dei bordi | Architettura |
| `power_point_percent` | Regola dei terzi | Posizionamento del soggetto | Tutte |
| `saturation_percent` | Saturazione dei colori | Analisi HSV | Foto vivaci |
| `noise_percent` | Livello di rumore | Stima del rumore | Bassa luminosità |
| `face_sharpness_percent` | Nitidezza della regione del volto | Analisi del volto | Ritratti |
| `aesthetic_iaa_percent` | Merito estetico artistico | TOPIQ IAA (addestrato su AVA) | Arte, creatività |
| `face_quality_iqa_percent` | Qualità del volto (IQA) | TOPIQ NR-Face | Ritratti |
| `liqe_percent` | Punteggio di qualità LIQE | LIQE | Diagnostica |
| `subject_sharpness_percent` | Nitidezza della regione del soggetto | BiRefNet + laplaciano | Ritratti, fauna selvatica |
| `subject_prominence_percent` | Rapporto dell'area del soggetto | BiRefNet | Macro, fauna selvatica |
| `subject_placement_percent` | Regola dei terzi del soggetto | BiRefNet | Tutte |
| `bg_separation_percent` | Separazione dello sfondo | BiRefNet | Ritratti, macro |

## Modificatori

Regolano il comportamento del punteggio per categoria:

| Modificatore | Tipo | Descrizione |
|----------|------|-------------|
| `bonus` | float | Aggiunto al punteggio finale (es. 0.5) |
| `noise_tolerance_multiplier` | float | Scala la penalità per il rumore (0.5 = metà) |
| `iso_tolerance_multiplier` | float | Scala la penalità per gli ISO |
| `min_saturation_bonus` | float | Bonus per alta saturazione |
| `contrast_bonus` | float | Bonus per alto contrasto |
| `_skip_clipping_penalty` | bool | Salta la penalità per il clipping dell'esposizione |
| `_skip_oversaturation_penalty` | bool | Salta la penalità per la sovrasaturazione |
| `_clipping_multiplier` | float | Scala la penalità per il clipping |
| `_apply_blink_penalty` | bool | Applica la penalità per il rilevamento degli occhi chiusi |

## Dimensioni della salienza del soggetto

Quattro dimensioni derivate dalla segmentazione del soggetto di BiRefNet:

| Chiave del peso | Metrica | Descrizione |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Nitidezza del soggetto | Qualità della messa a fuoco della regione del soggetto rispetto allo sfondo. Alta = soggetto nitido, sfondo morbido. |
| `subject_prominence_percent` | Prominenza del soggetto | Area del soggetto come frazione dell'inquadratura. Alta per macro e soggetti inquadrati da vicino, bassa per scene ampie. |
| `subject_placement_percent` | Posizionamento del soggetto | Punteggio della regola dei terzi per il centro di massa del soggetto. |
| `bg_separation_percent` | Separazione dello sfondo | Differenza del gradiente dei bordi al confine del soggetto (qualità del bokeh). |

Usa `subject_sharpness_percent` e `bg_separation_percent` per ritratti/fauna selvatica; `subject_prominence_percent` per la macro.

## Dimensioni IQA supplementari

Tre modelli di qualità aggiuntivi:

| Chiave del peso | Modello | Descrizione |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Merito estetico addestrato su AVA, distinto dal punteggio estetico di qualità tecnica. Ideale per le categorie arte/creatività. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Valutazione della qualità della regione del volto. Ideale per le categorie ritratto. |
| `liqe_percent` | LIQE | Punteggio di qualità più una diagnosi delle distorsioni (mosso, sovraesposizione, rumore). |

Questi modelli vengono eseguiti come parte della pipeline di punteggio predefinita e condividono la VRAM con TOPIQ. Aggiungi le loro chiavi di peso a qualsiasi categoria in cui la valutazione sia utile.

### Segnali supplementari (non inclusi nell'aggregato predefinito)

| Colonna | Origine | Descrizione |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP in cache | Un punteggio estetico supplementare gratuito (0-10) derivato dagli embedding delle immagini in cache proiettandoli su un "asse estetico" costruito da prompt testuali positivi/negativi. Nessuna inferenza aggiuntiva sull'immagine al momento della scansione. **Non** fa parte dell'`aggregate` predefinito. Popola con `python scripts/compute_aesthetic_clip.py --db <path>`. Esegui benchmark con `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. AVA SRCC ≈ 0.52 sul set di 500 foto `ava_test/` (rispetto a 0.94 per `aesthetic_iaa`) — utile come pre-filtro economico o quando TOPIQ-IAA non è disponibile. |

## Tag delle categorie (vocabolario CLIP)

I tag attivano le categorie basate sui tag e vengono abbinati usando la somiglianza CLIP:

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Ogni chiave è il nome del tag canonico e l'array contiene i sinonimi per l'abbinamento CLIP.

## Punteggio Migliori scelte

Il filtro "Migliori scelte" del visualizzatore usa un punteggio ponderato personalizzato:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Calcolo del punteggio:**
- Con volto (rapporto volto ≥ 20%): tutte e quattro le metriche contribuiscono
- Senza volto: `face_quality_percent` ridistribuito su `aesthetic` e `composition`

## Considerazioni sui profili VRAM

I pesi predefiniti sono ottimizzati per **TOPIQ** (0.93 SRCC), il modello estetico di tutti i profili.

| Profilo | Modello estetico | Embedding | Tagger | Raccomandazioni |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Migliore accuratezza, pesi predefiniti |
| `16gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Pesi predefiniti |
| `8gb` | CLIP+MLP (0.76 SRCC) | CLIP ViT-L-14 | Somiglianza CLIP | I pesi predefiniti funzionano bene |
| `legacy` | CLIP+MLP su CPU | CLIP ViT-L-14 | Somiglianza CLIP | Pesi predefiniti, più lento |

Tutti i profili eseguono inoltre i modelli PyIQA supplementari (TOPIQ IAA, TOPIQ NR-Face, LIQE) e, facoltativamente, BiRefNet_dynamic per la salienza del soggetto.

Esegui `--compute-recommendations` dopo aver cambiato profilo per analizzare le distribuzioni dei punteggi.

## Flusso di lavoro per la regolazione dei pesi

### Opzione A: tramite il visualizzatore (consigliato)

1. Apri `/stats` → scheda **Categorie** → sotto-scheda **Pesi**
2. Sblocca la modalità di modifica
3. Seleziona una categoria dal menu a tendina dell'editor
4. Regola i cursori — l'**Anteprima distribuzione punteggi** in tempo reale mostra l'impatto stimato
5. Clicca **Salva** poi **Ricalcola punteggi** per applicare

Il visualizzatore esegue `--recompute-category` dietro le quinte, aggiornando solo le foto di quella categoria.

### Opzione B: tramite CLI

#### 1. Analizza i punteggi attuali

```bash
python facet.py --compute-recommendations
```

Mostra:
- Distribuzioni dei punteggi per categoria
- Analisi della correlazione dei pesi
- Aggiustamenti suggeriti

#### 2. Regola i pesi

Modifica i pesi delle categorie in `scoring_config.json`. Assicurati che la somma sia 100.

#### 3. Ricalcola i punteggi

```bash
python facet.py --recompute-average               # Tutte le categorie
python facet.py --recompute-category portrait      # Singola categoria (più veloce)
```

Usa gli embedding memorizzati - nessuna GPU necessaria.

#### 4. Convalida le modifiche

```bash
python facet.py --compute-recommendations
```

Confronta le distribuzioni prima/dopo.

## Modalità di confronto a coppie

Addestra i pesi confrontando coppie di foto:

### Configurazione

1. Imposta una `edition_password` non vuota nella configurazione: `"viewer": { "edition_password": "your-password" }`
2. Avvia il visualizzatore: `python viewer.py`
3. Clicca il pulsante "Confronta"

### Interfaccia di confronto

- Foto affiancate
- Tastiera: A (vince sinistra), B (vince destra), T (pari), S (salta)
- La barra di avanzamento mostra i confronti verso il minimo di 50

### Origini dei confronti

I confronti portano un marcatore `source` così che l'ottimizzatore possa pesarli in base all'affidabilità:

- `vote` — voti A/B espliciti dall'interfaccia di confronto
- `culling` — derivati automaticamente dalle decisioni di selezione di raffiche/foto simili: ogni
  foto scartata viene abbinata a un massimo di due foto mantenute dello stesso gruppo
  (con un limite di 12 coppie per gruppo). Le foto mantenute vincono. I voti espliciti sulla stessa
  coppia non vengono mai sovrascritti.
- `rating` — coppie sintetiche generate dalle valutazioni a stelle e dai preferiti

Esaminare i gruppi di raffiche nel visualizzatore amplia quindi il set di addestramento per
l'ottimizzazione dei pesi senza alcuno sforzo aggiuntivo.

### Ottimizzazione dei pesi

```bash
# Controlla le statistiche dei confronti
python facet.py --comparison-stats

# Ottimizza i pesi dai confronti (applicati solo se generalizzano)
python facet.py --optimize-weights --optimize-category portrait

# Limita i dati di addestramento a origini specifiche
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Applica anche se la soglia held-out non è soddisfatta
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Applica a tutte le foto
python facet.py --recompute-average
```

### Pipeline da etichetta a peso

Oltre ai voti A/B espliciti, altri due flussi di etichette alimentano l'ottimizzatore:

1. **Le decisioni di selezione** vengono catturate automaticamente a ogni
   conferma di raffica/foto simili (`source='culling'`).
2. **Valutazioni a stelle, preferiti e rifiuti** vengono materializzati in coppie
   sintetiche con `python facet.py --sync-label-comparisons` (`source='rating'`).
   La riesecuzione risincronizza dalle etichette correnti, quindi le valutazioni ritirate scompaiono.

L'ottimizzatore pesa ogni origine in base all'affidabilità (vote 1.0, rating 0.7,
culling 0.5) quando massimizza la verosimiglianza di Bradley-Terry. Si addestra sul
vettore esatto delle metriche 0-10 usato dal calcolatore di punteggi (inclusi `liqe`, `aesthetic_iaa`,
`face_quality_iqa` e le metriche di salienza del soggetto), così i pesi ottimizzati corrispondono
direttamente al punteggio di produzione.

I pesi vengono **applicati solo se generalizzano**: i pesi finali sono adattati su
tutti i confronti, ma la decisione di scriverli è subordinata all'accuratezza
k-fold held-out, non all'accuratezza di addestramento. Se il guadagno held-out rispetto ai pesi correnti
è inferiore alla soglia (predefinito 2 pp) l'esecuzione riporta i numeri e non scrive
nulla — passa `--optimize-force` per forzare. L'ottimizzazione è per categoria e
richiede confronti etichettati **per quella categoria**; le categorie senza voti
non possono essere regolate dai dati.

Cadenza consigliata:

```bash
python facet.py --mine-insights          # quale segnale esiste, drift, salute
python facet.py --sync-label-comparisons # aggiorna le coppie derivate dalle valutazioni
python facet.py --optimize-weights       # apprende i pesi da tutte le origini
python facet.py --recompute-average      # applica + persiste lo snapshot dei percentili
```

### Regolazione dei pesi nell'interfaccia

1. Apri il pannello Anteprima pesi durante il confronto
2. Regola i cursori per vedere le variazioni di punteggio in tempo reale
3. Clicca "Suggerisci pesi" per i valori ottimizzati
4. Aggiorna manualmente la configurazione

## Aggiunta di categorie personalizzate

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

Aggiungi all'array `categories` in `scoring_config.json`, poi esegui `--recompute-average` (o `--recompute-category underwater` solo per la nuova categoria).

## Esempi di flusso di lavoro

### Regolare la categoria Concerto

```bash
# Modifica scoring_config.json:
# Trova la categoria "concert", regola:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

Oppure usa l'editor dei pesi del visualizzatore in `/stats` → Categorie → Pesi per l'anteprima in tempo reale e il ricalcolo con un clic.

### Passare al profilo 8gb

```bash
# Modifica: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analizza
# Riduci aesthetic_percent nelle categorie se necessario
python facet.py --recompute-average
```

### Aggiungere la categoria Underwater

1. Aggiungi la definizione della categoria (vedi sopra)
2. Esegui `python facet.py --validate-categories`
3. Esegui `python facet.py --recompute-average`
