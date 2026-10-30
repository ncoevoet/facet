# Sistema di punteggio

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · **Italiano** · [Español](../es/SCORING.md) · [Português](../pt/SCORING.md) · [简体中文](../zh/SCORING.md)

Le foto vengono classificate in una categoria e poi valutate con i pesi di quella categoria.

I valori assenti o NULL di subject_sharpness, subject_prominence, subject_placement, bg_separation e face_quality_iqa sono esclusi dal punteggio ponderato. Solo il loro peso positivo viene redistribuito alle metriche disponibili; zero rimane valido. Se mancano tutti gli ingressi ponderati, si usa il valore neutro 5.0. Le esclusioni di licenza si applicano prima. I pesi predefiniti non cambiano. La taratura e la valutazione di confronti e distribuzioni richiedono dati rappresentativi e saranno affrontate in seguito. Per completare la salienza, eseguire `--recompute-saliency`, poi `--recompute-average`.

## Come funziona il punteggio

1. **Rilevamento della categoria** - La foto viene analizzata per il contenuto (volti, tag, dati EXIF)
2. **Valutazione dei filtri** - Le categorie vengono valutate in ordine di priorità finché una non corrisponde (un [contesto di punteggio](#contesti-di-punteggio) può cambiare questo ordine per album o per foto)
3. **Applicazione dei pesi** - I pesi specifici della categoria vengono applicati alle metriche
4. **Applicazione dei modificatori** - Bonus, penalità e flag di comportamento vengono applicati
5. **Punteggio finale** - Somma ponderata limitata all'intervallo 0-10

## Categorie

`scoring_config.json` definisce 34 categorie (33 nominate più `default`), valutate in ordine di priorità crescente finché una non corrisponde. La priorità più bassa vince. L'elenco completo si trova nell'array `categories`; le principali:

| Priorità | Categoria | Metodo di rilevamento |
|----------|----------|------------------|
| 8 | `art` | Tag: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tag: aurora, astrophotography, stars, milky way, E luminanza media ≤ 0.30 |
| 15 | `concert` | Tag: concert |
| 35 | `group_portrait` | Rapporto volto ≥ 5% E is_group_portrait |
| 42 | `silhouette` | Ha un volto E `is_silhouette` (il volto più grande è scuro su un ambiente più chiaro) |
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

Sui profili con tagging CLIP (`legacy`/`8gb`, e `16gb`/`24gb` quando il loro tagger VLM non viene eseguito) una scansione etichetta ogni foto prima di calcolarne la categoria, quindi la categoria memorizzata usa i tag. Un'esecuzione con un solo `--pass NAME` non etichetta.

**Silhouette.** `is_silhouette` deriva da una regola di pixel basata sul volto (vedi [Filtri booleani](#filtri-booleani)), non da un tag.

- Quando `exposure.silhouette_detection` è `true` (il predefinito), l'aggregato di una silhouette salta la penalità di clipping.
- Una scansione memorizza `exposure_score` con la penalità di clipping. `--recompute-average` lo ricalcola senza penalità per ogni foto contrassegnata `is_silhouette`, qualunque sia il valore di `exposure.silhouette_detection`.
- Per ricavare di nuovo i flag di una libreria esistente, esegui `python facet.py --recompute-silhouette`, poi `--recompute-average` due volte (vedi [COMMANDS.md](COMMANDS.md)).

**Astro.** Una foto deve avere un tag astro *e* una luminanza media di al massimo 0.30 (`luminance_max`). Una scena luminosa etichettata `aurora` o `stars` non è astro, e una foto senza luminanza memorizzata non corrisponde mai. Se il tuo `scoring_config.json` ha un proprio array `categories`, aggiungi tu stesso `"luminance_max": 0.30` a `astro.filters`; `python facet.py --doctor` ti avvisa quando manca.

## Contesti di punteggio

Un **contesto di punteggio** cambia l'ordine delle categorie per alcune foto senza toccare le priorità globali. Promuove in testa alcune categorie ed esclude le altre. `default` (con `promote`/`excluded` vuoti) non cambia nulla, e le foto lo usano finché non ne assegni un altro.

**Ordine effettivo** = `promote` (nell'ordine indicato) → l'ordine di priorità globale senza i nomi promossi ed esclusi → `default` per ultimo. Un nome presente sia in `promote` sia in `excluded` viene rimosso: vince `excluded`.

Preset forniti di serie, modificabili dalla scheda **Contesto di punteggio** del visualizzatore o nel JSON (riferimento dei campi: [Contesti di punteggio](CONFIGURATION.md#contesti-di-punteggio)):

| Contesto | Promuove | Esclude |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Modifichi solo l'elenco delle categorie promosse (modalità edizione; trascina, oppure sposta su/giù) e le esclusioni. Le altre categorie mantengono sempre l'ordine globale, quindi una categoria nuova non manca mai da un contesto. Regole di validazione: [Modificare un contesto](CONFIGURATION.md#modificare-un-contesto).

**Assegnare un contesto:**

- **Per album.** Si applica a ogni foto che è nell'album in questo momento. È un'istantanea una tantum: le foto aggiunte in seguito a un album intelligente non lo ricevono. Vedi [Contesti di punteggio](CONFIGURATION.md#contesti-di-punteggio).
- **Per foto.** Una sovrascrittura di categoria persistente per una singola foto.

Entrambi sopravvivono alle nuove scansioni e possono essere azzerati separatamente.

**Nessuno dei due ha effetto sulle foto già valutate finché non esegui un ricalcolo:** esegui `python facet.py --recompute-average`, oppure ricalcola dal visualizzatore (vedi [Cambiare le priorità richiede un ricalcolo](CONFIGURATION.md#riordinare-la-priorità-globale)). Con `normalization.per_category` abilitato, eseguilo due volte (vedi [Normalization](CONFIGURATION.md#normalization)).

### La trappola dei dati EXIF mancanti

Riordinare cambia solo quale categoria viene *provata per prima*. Non può far corrispondere i filtri di una categoria. Un filtro di intervallo numerico fallisce quando il valore della foto è mancante o non interpretabile, esattamente come se fosse fuori intervallo.

Esempio: `sports` (priorità 71) porta `shutter_speed_max: 0.02`. Un fotogramma di danza scattato più lento di 1/50s, o senza alcun tempo di posa leggibile, fallisce quel filtro anche quando `action_stage` promuove `sports` in prima posizione. Scivola verso la prima categoria successiva che corrisponde, tipicamente `fashion` (priorità 43, taggata `fashion`, ha un volto) o `silhouette` (priorità 42, controluce con un volto).

**Quando una foto finisce in una categoria inattesa, controlla prima questo:** i filtri numerici della categoria di destinazione possono corrispondere ai dati EXIF memorizzati della foto, non solo ai suoi tag?

### La trappola del tag mancante

`required_tags` fallisce allo stesso modo: un filtro non può corrispondere a un tag assente dal vocabolario. I `required_tags` di `sports` sono `sports`, `motion`, `athlete`, `competition`, `action_sport` e `dance`.

`sports.tags.dance` porta 11 prompt CLIP (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), e `dance` è in `sports.filters.required_tags`. Una foto di danza taggata può raggiungere `sports`, ma una a otturatore lento o senza EXIF fallisce comunque su `shutter_speed_max: 0.02`.

**Le foto esistenti mantengono i tag che hanno già.** Un cambio di vocabolario riguarda solo i nuovi tagging; esegui `python facet.py --recompute-tags` per applicarlo alla libreria.

### Riordinare la priorità globale

Puoi riordinare la priorità globale nel visualizzatore (modalità edizione). Il riordino permuta i numeri di priorità esistenti tra le categorie invece di rinumerarli, quindi i numeri nella tabella qui sopra restano significativi. `default` (priorità 999) resta sempre ultima. Ogni scrittura crea prima una copia con timestamp `.backup.<timestamp>` di `scoring_config.json`.

Il riordino non cambia la `category` memorizzata di alcuna foto: esegui poi un ricalcolo.

**Limitazione nota:** il menu a discesa del tipo nella galleria mantiene il vecchio ordine finché il visualizzatore non viene riavviato. La corrispondenza e il filtraggio usano subito il nuovo ordine.

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
| `is_silhouette` | Il volto più grande è scuro su un ambiente chiaro (vedi sotto). Una foto senza volto non è mai una silhouette |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurabile, predefinito: 4) |

**Regola di `is_silhouette`.** La luminosità media (luma, 0-1) del 60 % centrale del riquadro del volto è inferiore a 0.12, e la fascia attorno al riquadro (da 0.2 a 0.75 della dimensione del riquadro verso l'esterno su ogni lato, ritagliata all'inquadratura) è più chiara di oltre 0.20. Né il tag CLIP `silhouette` né l'istogramma dell'intero fotogramma la impostano.

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
| `quality_percent` | Qualità legacy | Sommato a `aesthetic_percent` prima del calcolo (nessun segnale separato) | — |
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

**`quality_percent` conta come `aesthetic`.** La metrica qualità non ha un punteggio proprio, quindi il `quality_percent` di una categoria viene ridistribuito in `aesthetic`: viene sommato a `aesthetic_percent` prima del calcolo, e i pesi sommano sempre 100. Le versioni precedenti perdevano quella quota nell'aggregato; esegui `--recompute-average` una volta dopo l'aggiornamento per recuperarla. Le categorie non cambiano.

## Modificatori

Regolano il comportamento del punteggio per categoria:

| Modificatore | Tipo | Descrizione |
|----------|------|-------------|
| `bonus` | float | Aggiunto al punteggio finale (es. 0.5) |
| `noise_tolerance_multiplier` | float | Scala la penalità per il rumore (0.5 = metà) |
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

**Nessun soggetto, nessun numero.** Quando non si trova alcun soggetto, `subject_sharpness`, `subject_placement` e `bg_separation` vengono memorizzati come NULL (come `power_point_score` quando non c'è un riquadro del soggetto), `subject_prominence` è 0.0 e `subject_bbox` è NULL.

- I filtri di intervallo della galleria saltano un NULL (`min_subject_sharpness=0` non restituisce una foto senza soggetto). Le statistiche lo escludono dalle medie e l'interfaccia lo mostra come assente.
- L'aggregato conta un NULL come un 5.0 neutro, quindi nessun aggregato cambia.
- Le versioni precedenti memorizzavano un 5.0 neutro. Le righe esistenti lo mantengono finché `--recompute-saliency` e `--recompute-composition-cpu` non le riscrivono.

**Quando la salienza fallisce**, non viene scritto nulla; Facet non memorizza mai un numero neutro per un risultato fallito. Una foto mai valutata mantiene NULL in tutte e cinque le colonne di salienza (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`) e ottiene un punteggio neutro (5.0), come una foto scansionata prima che esistesse la salienza. Regole di ripetizione e dimensione del batch: [Salienza del soggetto](COMMANDS.md#salienza-del-soggetto).

## Dimensioni IQA supplementari

Tre modelli di qualità aggiuntivi:

| Chiave del peso | Modello | Descrizione |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Merito estetico addestrato su AVA, distinto dal punteggio estetico di qualità tecnica. Ideale per le categorie arte/creatività. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Valutazione della qualità della regione del volto. Ideale per le categorie ritratto. |
| `liqe_percent` | LIQE | Punteggio di qualità più una diagnosi delle distorsioni (mosso, sovraesposizione, rumore). |

Questi modelli vengono eseguiti come parte della pipeline di punteggio predefinita su ogni profilo, compreso il profilo `legacy` su CPU (più lento), e condividono la VRAM con TOPIQ su una GPU. Aggiungi le loro chiavi di peso a qualsiasi categoria in cui la valutazione sia utile.

**Quando un modello supplementare non riesce a valutare una foto**, memorizza NULL nella colonna di quel modello (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) invece di un 5.0 neutro. Succede quando TOPIQ NR-Face non trova alcun volto, o quando LIQE riceve un lato corto inferiore a 224 px; Aesthetic V2.5, se attivato, può fallire su qualsiasi immagine. Un errore di memoria della CPU non viene ritentato con una dimensione di batch inferiore.

- **Aggregato:** un NULL vale come neutro (5.0), quindi punteggi, categorie e classifiche non cambiano.
- **Galleria:** un filtro di intervallo su Estetica (IAA), Qualità volto (IQA), LIQE o Aesthetic V2.5 non include una foto senza punteggio (`min_face_quality_iqa=0` salta una foto senza volti). Un ordinamento crescente su questi, su Q-ReAlign o su DeQA mette le foto senza punteggio in fondo, nella galleria e negli album.
- **I vecchi valori neutri 5.0** restano finché `--repair-neutral-iqa` non li cancella; poi esegui `--recompute-iqa` e `--recompute-average`, oppure riscansiona con `--force`.
- **Errore del modello principale** (TOPIQ sui profili `16gb` e `24gb`): la foto viene registrata come fallita invece di essere salvata con un 5.0 neutro. Una foto nuova viene ripresa dalla scansione successiva; una già memorizzata conserva la propria riga e viene ritentata da `--retry-failed all` (un `--retry-failed` senza argomento copre solo l'ultima esecuzione con errori) o da un'altra scansione con `--force`.

Regole di ripetizione per ogni comando: [Modelli di qualità supplementari](COMMANDS.md#modelli-di-qualità-supplementari).

### Segnali supplementari (non inclusi nell'aggregato predefinito)

| Colonna | Origine | Descrizione |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP in cache | Punteggio estetico gratuito (0-10) dagli embedding in cache; **non** fa parte dell'`aggregate` predefinito |

`aesthetic_clip` proietta l'embedding di ogni immagine su un "asse estetico" costruito da prompt testuali, quindi non richiede alcuna inferenza aggiuntiva sull'immagine.

- Popolalo con `python scripts/compute_aesthetic_clip.py --db <path>`.
- Esegui il benchmark con `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- AVA SRCC ≈ 0.52 sul set di 500 foto `ava_test/` (rispetto a 0.94 per `aesthetic_iaa`). Usalo come pre-filtro economico o quando TOPIQ-IAA non è disponibile.

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
- Senza volto: `face_quality_percent` ridistribuito in parti uguali (metà ciascuno) su `aesthetic` e `composition` (con i pesi predefiniti: aesthetic 0.40, composition 0.30)

## Considerazioni sui profili VRAM

I pesi predefiniti sono ottimizzati per **TOPIQ** (0.93 SRCC), il modello estetico di tutti i profili.

| Profilo | Modello estetico | Embedding | Tagger | Raccomandazioni |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Migliore accuratezza, pesi predefiniti |
| `16gb` | TOPIQ (0.93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Pesi predefiniti |
| `8gb` | CLIP+MLP (0.76 SRCC) | CLIP ViT-L-14 | Somiglianza CLIP | I pesi predefiniti funzionano bene |
| `legacy` | CLIP+MLP su CPU | CLIP ViT-L-14 | Somiglianza CLIP | Pesi predefiniti, più lento |

Tutti i profili, compreso il profilo `legacy` su CPU, eseguono inoltre i modelli PyIQA supplementari (TOPIQ IAA, TOPIQ NR-Face, LIQE) e, facoltativamente, BiRefNet_dynamic per la salienza del soggetto.

Esegui `--compute-recommendations` dopo aver cambiato profilo per analizzare le distribuzioni dei punteggi.

## Flusso di lavoro per la regolazione dei pesi

### Opzione A: tramite il visualizzatore (consigliato)

1. Apri `/stats` → scheda **Categorie** → sotto-scheda **Pesi**
2. Sblocca la modalità di modifica
3. Seleziona una categoria dal menu a tendina dell'editor
4. Regola i cursori — l'**Anteprima distribuzione punteggi** in tempo reale mostra l'impatto stimato
5. Clicca **Salva** poi **Ricalcola punteggi** per applicare

Il visualizzatore esegue `--recompute-category` dietro le quinte, aggiornando solo le foto di quella categoria.

Un assistente MCP può leggere questi pesi e simulare una modifica senza toccare nulla: `explain_score` (perché una foto ha ottenuto il suo punteggio), `category_weights` e `preview_weights` (un'anteprima approssimativa con i cambi di posizione). Vedere [Punteggi e pesi](AGENTS.md#punteggi-e-pesi).

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
- Tastiera: ← (vince sinistra), → (vince destra), T (pari), S (salta). I pulsanti a schermo sono etichettati **A** / **B**.
- La barra di avanzamento mostra i confronti verso il minimo di 50

### Origini dei confronti

Ogni confronto ha un `source`, che l'ottimizzatore pesa in base all'affidabilità:

- `vote` — voti A/B espliciti dall'interfaccia di confronto
- `culling` — dalle decisioni di selezione di raffiche/foto simili: ogni foto scartata viene
  abbinata a un massimo di due foto mantenute dello stesso gruppo (al massimo 12 coppie per
  gruppo). Le foto mantenute vincono. I voti espliciti sulla stessa coppia non vengono mai
  sovrascritti.
- `rating` — coppie sintetiche generate dalle valutazioni a stelle e dai preferiti

Esaminare i gruppi di raffiche nel visualizzatore amplia quindi anche il set di addestramento.

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

Oltre ai voti A/B, due flussi di etichette alimentano l'ottimizzatore:

1. **Le decisioni di selezione** vengono catturate a ogni conferma di raffica/foto simili (`source='culling'`).
2. **Valutazioni a stelle, preferiti e rifiuti** diventano coppie sintetiche con
   `python facet.py --sync-label-comparisons` (`source='rating'`). La riesecuzione
   risincronizza dalle etichette correnti, quindi le valutazioni ritirate scompaiono.

**Come funziona l'adattamento.** L'ottimizzatore cerca i pesi che predicono meglio il vincitore di ogni confronto (un modello di Bradley-Terry).

- Le origini contano in base all'affidabilità: vote 1.0, rating 0.7, culling 0.5.
- Un **pareggio** conta come mezza vittoria e mezza sconfitta.
- L'adattamento è **ancorato ai tuoi pesi attuali**: con pochi confronti resta vicino ad essi.
- Usa le stesse metriche 0-10 dell'aggregato (inclusi `liqe`, `aesthetic_iaa`, `face_quality_iqa` e la salienza del soggetto), con nitidezza degli occhi, nitidezza tecnica e colore normalizzati per i percentili salvati dall'ultimo `--recompute-average`.
- `quality_percent` viene ripiegato in `aesthetic`, come fa lo scorer; l'applicazione scrive `quality_percent: 0`.

**I pesi si applicano solo se generalizzano.** La decisione si basa su confronti riservati (held-out): validazione incrociata a 5 fold con **fold raggruppati per foto** (nessuna foto compare insieme nelle coppie di addestramento e in quelle riservate).

- Un **test esatto di McNemar unilaterale** verifica se i nuovi pesi vincono in modo significativo più coppie fra quelle su cui i due insiemi di pesi non concordano.
- I pesi si applicano solo quando `p < 0.05` **e** il guadagno sulle coppie riservate è di almeno 2 punti percentuali. Altrimenti l'esecuzione registra i numeri e non scrive nulla.
- Passa `--optimize-force` per applicarli comunque. Se il test non può essere eseguito (troppo pochi gruppi indipendenti di foto), non viene applicato nulla a meno di forzare.
- Ogni categoria richiede almeno 30 confronti **decisivi** (una foto ha vinto) **in quella categoria**. I pareggi e le altre categorie non contano.

Log di esempio:

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**L'applicazione mantiene il livello della categoria.** `--optimize-weights` cambia come le foto di una categoria si ordinano tra loro, non rispetto alle altre categorie. Sposta `modifiers.bonus` per annullare lo spostamento medio del punteggio della categoria.

- Il bonus resta entro [-5, 5]; il log segnala quando questo limite si applica.
- Una categoria senza voce in `categories` (`others`) non ha bonus e non viene ricentrata.
- Ripristinare un'istantanea dei pesi ripristina pesi **e** bonus. Le istantanee più vecchie, quelle di `calibrate.py` e quelle per `others` lasciano intatto il bonus.
- Il pulsante **Applica** del viewer e le modifiche manuali nella scheda Pesi non ricentrano il bonus; lo fa solo `--optimize-weights`.

**Dopo l'aggiornamento, riaddestra il ranker personale e la head keeper (`--train-ranker`, `--train-keeper`), poi esegui `--recompute-average`.** Ora leggono nitidezza degli occhi, nitidezza tecnica e colore normalizzati per percentili, e un modello salvato da una versione precedente non può rilevare il cambiamento.

Cadenza consigliata:

```bash
python facet.py --mine-insights          # quale segnale esiste, drift, salute
python facet.py --sync-label-comparisons # aggiorna le coppie derivate dalle valutazioni
python facet.py --optimize-weights       # apprende i pesi da tutte le origini
python facet.py --recompute-average      # applica + persiste lo snapshot dei percentili
```

### Regolazione dei pesi nell'interfaccia

Durante il confronto, il pannello Anteprima pesi mostra le variazioni di punteggio mentre muovi i cursori, e **Suggerisci pesi** propone valori ottimizzati. Salvare e ricalcolare funzionano come in [Opzione A: tramite il visualizzatore](#opzione-a-tramite-il-visualizzatore-consigliato).

**Suggerisci pesi** mostra due valori, nella scheda Suggerimenti pesi e nella barra laterale del Confronto A/B:

- `accuracy_before`: quanto spesso i pesi attuali predicono il vincitore delle coppie etichettate di questa categoria.
- `accuracy_after`: lo stesso per i pesi suggeriti. È misurato sulle coppie su cui è stato adattato, quindi è ottimistico.

**Applica** viene offerto solo quando passa lo stesso test di McNemar riservato della CLI (`suggest_changes` è vero). La validazione incrociata viene eseguita solo quando il guadagno ottimistico raggiunge 2 punti percentuali (`?use_cv=true` la esegue sempre). Il viewer richiede `min_comparisons_for_optimization` (predefinito 50) confronti decisivi nella categoria, dove la CLI ne richiede 30. Sotto, riporta «Need at least N decisive comparisons (have K)».

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
