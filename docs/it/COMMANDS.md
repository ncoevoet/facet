# Riferimento dei comandi

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · **Italiano** · [Español](../es/COMMANDS.md)

[Scansione](#scansione) · [Anteprima ed esportazione](#anteprima-ed-esportazione) · [Operazioni di ricalcolo](#operazioni-di-ricalcolo) · [Riconoscimento facciale](#riconoscimento-facciale) · [Gestione delle miniature](#gestione-delle-miniature) · [Diagnostica](#diagnostica) · [Informazioni sui modelli](#informazioni-sui-modelli) · [Ottimizzazione dei pesi](#ottimizzazione-dei-pesi-confronto-a-coppie) · [Configurazione](#configurazione) · [Tagging](#tagging) · [Validazione del database](#validazione-del-database) · [Manutenzione del database](#manutenzione-del-database) · [Visualizzatore web](#visualizzatore-web) · [Flussi di lavoro comuni](#flussi-di-lavoro-comuni)

> Tag dei requisiti usati di seguito: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (profilo VRAM). Vedi la [matrice delle funzionalità](../README.md#feature-availability--requirements).

## Scansione

| Comando | Descrizione |
|---------|-------------|
| `python facet.py /path` | Scansiona una directory (modalità multi-pass, rilevamento automatico della VRAM) |
| `python facet.py /path --force` | Riscansiona i file già elaborati |
| `python facet.py /path --single-pass` | Forza la modalità single-pass (tutti i modelli in una volta) |
| `python facet.py /path --pass quality` | Esegue solo il passaggio di valutazione qualità TOPIQ |
| `python facet.py /path --pass quality-iaa` | Esegue solo la valutazione del merito estetico TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Esegue solo la valutazione qualità TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Esegue solo la diagnosi qualità + distorsioni LIQE |
| `python facet.py /path --pass tags` | Esegue solo il passaggio di tagging (il modello dipende dal profilo VRAM) |
| `python facet.py /path --pass composition` | Esegue solo il rilevamento dei modelli compositivi SAMP-Net |
| `python facet.py /path --pass faces` | Esegue solo il rilevamento dei volti InsightFace |
| `python facet.py /path --pass embeddings` | Esegue solo l'estrazione degli embedding CLIP/SigLIP |
| `python facet.py /path --pass saliency` | Esegue solo il rilevamento della salienza del soggetto BiRefNet |
| `python facet.py /path --db custom.db` | Usa un file di database personalizzato |
| `python facet.py /path --config my.json` | Usa una configurazione di punteggio personalizzata |
| `python facet.py --resume` | Riprende l'ultima scansione interrotta/fallita (riutilizza le sue directory; con `--force`, salta i file già rivalutati dall'inizio di quella esecuzione) |
| `python facet.py --retry-failed` | Rielabora solo i file falliti durante l'ultima esecuzione di scansione (`--retry-failed all` per i fallimenti di tutte le esecuzioni) |
| `python facet.py /path --force-since 2026-01-01` | Come `--force`, ma rielabora solo le foto scansionate l'ultima volta prima della data |
| `python facet.py /path --watch` | Rimane in esecuzione e riscansiona ogni volta che compaiono nuove foto (richiede `pip install watchdog`; `--watch-debounce N` regola il periodo di inattività, predefinito 30s) |

### Registrazione delle scansioni

Ogni scansione registra una riga in `scan_runs` (stato, modalità, directory, contatori)
e gli errori per singolo file in `scan_failures` (percorso, fase, errore). Interrompere una
scansione con Ctrl+C contrassegna l'esecuzione come `interrupted` così che `--resume` possa riprenderla;
i file falliti sono visibili e ritentabili invece di essere ritentati silenziosamente a ogni
scansione incrementale. La CLI emette inoltre righe JSON strutturate `@FACET_PROGRESS`
(fase, attuale/totale, ETA) che l'API di scansione del visualizzatore espone nel
campo `progress` di `/api/scan/status` e nel flusso SSE.

### Modalità di elaborazione

**Multi-pass (predefinita):** rileva la VRAM e carica i modelli in sequenza. Ogni passaggio carica il proprio modello, elabora tutte le foto, poi lo scarica per liberare la VRAM, così i modelli di alta qualità possono essere eseguiti anche con VRAM limitata.

**Single-pass (`--single-pass`):** carica tutti i modelli in una volta. Più veloce, richiede più VRAM.

**Passaggio specifico (`--pass NAME`):** esegue un solo passaggio, per aggiornare metriche specifiche senza una rielaborazione completa. Passaggi disponibili:

| Passaggio | Modello | Output | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | punteggio `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | punteggio `aesthetic_iaa` (merito artistico vs qualità tecnica, addestrato su AVA) | Condivisa con TOPIQ |
| `quality-face` | TOPIQ NR-Face | punteggio `face_quality_iqa` (qualità del volto dedicata) | Condivisa con TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnosi delle distorsioni (sfocatura, sovraesposizione, rumore) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Tag semantici dal vocabolario configurato | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (14 modelli) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Rilevamento volti, punti di riferimento, rilevamento occhi chiusi, embedding di riconoscimento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 o SigLIP 2 NaFlex | BLOB `clip_embedding` per somiglianza/tagging | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 GB |

## Anteprima ed esportazione

| Comando | Descrizione |
|---------|-------------|
| `python facet.py /path --dry-run` | Valuta 10 foto campione senza salvare |
| `python facet.py /path --dry-run --dry-run-count 20` | Valuta 20 foto campione |
| `python facet.py --export-csv` | Esporta tutti i punteggi in un CSV con data e ora |
| `python facet.py --export-csv output.csv` | Esporta in un file CSV specifico |
| `python facet.py --export-json` | Esporta tutti i punteggi in un JSON con data e ora |
| `python facet.py --export-json output.json` | Esporta in un file JSON specifico |

## Operazioni di ricalcolo

Questi comandi aggiornano metriche specifiche senza una rielaborazione completa delle foto.

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --recompute-average` | Ricalcola i punteggi aggregati (crea un backup) |
| `python facet.py --recompute-category portrait` | Ricalcola i punteggi solo per una singola categoria |
| `python facet.py --recompute-tags` | Riassegna i tag a tutte le foto usando il modello configurato |
| `python facet.py --recompute-tags-vlm` | Riassegna i tag a tutte le foto usando il tagger VLM |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Ricalcola le metriche di salienza del soggetto (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Ricalcola la composizione, basata su regole (CPU, qualsiasi profilo) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Ricalcola la composizione con SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Ricalcola le metriche IQA supplementari (TOPIQ IAA, NR-Face, LIQE) dalle miniature memorizzate |
| `python facet.py --recompute-ocr` | Estrae il testo presente nell'immagine in `ocr_text` dalle miniature (opzionale; nessun effetto senza un motore OCR; esegui `--rebuild-fts` dopo per indicizzare) |
| `python facet.py --recompute-colors` | Estrae la tonalità dominante + la temperatura colore caldo/freddo dalle miniature (CPU, veloce) in `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Migra lo schema ed esegue l'intera catena di backfill: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotente; salta i passaggi pesanti come la generazione delle didascalie. |
| `python facet.py --recompute-blinks` | Ricalcola il rilevamento degli occhi chiusi dai punti di riferimento memorizzati (CPU, veloce) |
| `python facet.py --recompute-eyes-expression` | Ricalcola i punteggi di occhi aperti + espressione dai punti di riferimento memorizzati (CPU, veloce) |
| `python facet.py --recompute-burst` | Ricalcola i gruppi di rilevamento raffica |
| `python facet.py --detect-duplicates` | Rileva le foto duplicate tramite pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Valuta le soglie di coseno per i quasi-duplicati (tabella precisione/richiamo con le etichette, altrimenti distribuzione coseno dei candidati) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Genera didascalie AI per le foto usando un VLM |
| `python facet.py --translate-captions` | Traduce le didascalie inglesi nella lingua di destinazione configurata (CPU, MarianMT) |
| `python facet.py --extract-gps` | Estrae le coordinate GPS dai dati EXIF nelle colonne del database |
| `python facet.py --rescan-gps` | Riestrae le coordinate GPS dall'EXIF per tutte le foto (sovrascrive quelle esistenti) |
| `python facet.py --recompute-embeddings` | Ricalcola gli embedding CLIP/SigLIP per tutte le foto (necessario dopo il cambio di modello) |
| `python facet.py --score-topiq` | Riempie i punteggi di qualità TOPIQ dalle miniature memorizzate (richiede GPU) |
| `python facet.py --backfill-focal-35mm` | Riempie la lunghezza focale equivalente a 35mm dall'EXIF per le foto che ne sono prive |
| `python facet.py --compute-recommendations` | Analizza il database, mostra un riepilogo dei punteggi |
| `python facet.py --compute-recommendations --verbose` | Mostra statistiche dettagliate |
| `python facet.py --compute-recommendations --apply-recommendations` | Applica automaticamente le correzioni dei punteggi |
| `python facet.py --compute-recommendations --simulate` | Visualizza in anteprima le modifiche previste |

### Modelli di qualità supplementari

Tre modelli PyIQA aggiuntivi valutano oltre il punteggio estetico principale TOPIQ. Condividono la VRAM con TOPIQ e vengono eseguiti come parte della pipeline multi-pass predefinita.

- **TOPIQ IAA** (`--pass quality-iaa`): merito estetico artistico addestrato su AVA, separato dalla qualità tecnica. Memorizzato come `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): valutazione della qualità della regione del volto. Memorizzato come `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): punteggio di qualità più una diagnosi del tipo di distorsione (es. sfocatura da movimento, sovraesposizione, rumore). Memorizzato come `liqe_score`.

### Benchmark e punteggi supplementari

| Comando | Descrizione |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Popola la colonna `aesthetic_clip` proiettando gli embedding CLIP/SigLIP memorizzati su un asse estetico derivato dal testo. Nessuna inferenza aggiuntiva sulle immagini. Non fa parte dell'`aggregate` predefinito. Vedi [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcola SRCC + PLCC rispetto al riferimento mean-opinion-score di AVA per ogni colonna di punteggio popolata nel DB. Utile quando si aggiunge o si regola una variante di modello. |

### Salienza del soggetto

`--pass saliency` e `--recompute-saliency` usano BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, tramite `transformers`) per generare una maschera binaria del soggetto, poi ne derivano quattro metriche:

- **Nitidezza del soggetto**: varianza laplaciana sulla regione del soggetto rispetto allo sfondo — se il soggetto è a fuoco.
- **Prominenza del soggetto**: area del soggetto / area dell'inquadratura — elevata per un soggetto dominante (es. macro).
- **Posizionamento del soggetto**: punteggio della regola dei terzi per il centroide del soggetto.
- **Separazione dallo sfondo**: differenza di gradiente dei bordi tra il confine del soggetto e lo sfondo — qualità del bokeh.

Richiede `transformers` (~2 GB di VRAM).

### Modelli di tagging

Il modello di tagging è selezionato per ogni profilo VRAM:

| Profilo | Modello | Come funziona |
|---------|-------|-------------|
| `legacy` | Somiglianza CLIP | Somiglianza coseno tra l'embedding dell'immagine e gli embedding del testo dei tag. Nessun caricamento di modello aggiuntivo. |
| `8gb` | Somiglianza CLIP | Come legacy, sugli embedding CLIP ViT-L-14 memorizzati. |
| `16gb` | Qwen3.5-2B | Modello multimodale per il tagging semantico delle scene. |
| `24gb` | Qwen3.5-4B | Modello multimodale più grande. |

Tutti i tagger mappano l'output sul vocabolario di tag configurato. Usa `--recompute-tags` per riassegnare i tag con il modello predefinito del profilo, o `--recompute-tags-vlm` per il re-tagging basato su VLM.

### Modelli di embedding

Sono disponibili due modelli di embedding, selezionati per ogni profilo VRAM tramite `clip_config`:

| Config | Modello | Dimensioni | Usato da |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | profili 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | profili legacy, 8gb |

Gli embedding alimentano il tagging semantico, il rilevamento dei duplicati, la ricerca di foto simili e l'estetica CLIP+MLP (legacy/8gb). Il cambio di modello richiede di ricalcolare gli embedding di tutte le foto (`--force`, `--pass embeddings`, o `--recompute-embeddings`).

## Riconoscimento facciale

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Estrae i volti per le nuove foto (GPU, parallelo) |
| `python facet.py --extract-faces-gpu-force` | Elimina tutti i volti e li riestrae (GPU) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, preserva tutte le persone (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, preserva solo le persone con nome (CPU) |
| `python facet.py --cluster-faces-force` | Riclustering completo, elimina tutte le persone (CPU) |
| `python facet.py --suggest-person-merges` | Suggerisce potenziali unioni di persone |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa una soglia più rigorosa |
| `python facet.py --refill-face-thumbnails-incremental` | Genera le miniature mancanti (CPU, parallelo) |
| `python facet.py --refill-face-thumbnails-force` | Rigenera TUTTE le miniature (CPU, parallelo) |

## Gestione delle miniature

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Corregge la rotazione delle miniature memorizzate usando l'orientamento EXIF |

Legge l'orientamento EXIF dai file originali e ruota i byte della miniatura memorizzata; per le foto elaborate prima dell'esistenza della gestione EXIF. Legge solo l'intestazione EXIF e la miniatura memorizzata, non le immagini complete.

## Diagnostica

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --doctor` | Esegue controlli diagnostici (Python, GPU, dipendenze, configurazione, database) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula l'hardware GPU per la diagnostica |

Riporta la versione di Python, la build PyTorch/CUDA, il rilevamento della GPU e il driver, la raccomandazione del profilo VRAM, le dipendenze opzionali e lo stato di configurazione/database. Quando PyTorch non vede la GPU ma `nvidia-smi` sì, stampa il comando `pip install` per correggere la build CUDA.

`--simulate-gpu NAME` e `--simulate-vram GB` testano il comportamento con hardware diverso. Entrambi richiedono `--doctor`; `--simulate-vram` richiede `--simulate-gpu`.

## Informazioni sui modelli

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --list-models` | Mostra i modelli disponibili e i requisiti di VRAM |

## Ottimizzazione dei pesi (confronto a coppie)

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --comparison-stats` | Mostra le statistiche dei confronti a coppie |
| `python facet.py --optimize-weights` | Ottimizza e salva i pesi dai confronti (tutte le fonti, ponderati per affidabilità); applicati solo se l'accuratezza k-fold sui dati esclusi supera i pesi attuali |
| `python facet.py --optimize-weights --optimize-force` | Applica i pesi ottimizzati anche se il vincolo di accuratezza non è soddisfatto |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Limita i dati di addestramento a fonti di confronto specifiche |
| `python facet.py --optimize-weights --optimize-category portrait` | Addestra solo su una categoria e scrive il suo blocco v4 `categories[].weights` |
| `python facet.py --sync-label-comparisons` | Ricostruisce le coppie derivate dalle valutazioni (source=rating) da valutazioni a stelle/preferiti/scartate |
| `python facet.py --train-ranker` | Addestra il ranker personale su [embedding + punteggi] e scrive learned_scores (vincolato all'accuratezza k-fold sui dati esclusi rispetto al riferimento aggregato) |
| `python facet.py --train-ranker --ranker-category portrait` | Addestra il ranker solo su una categoria |
| `python facet.py --train-ranker --train-ranker-force` | Scrive learned_scores anche se il vincolo di accuratezza non è soddisfatto |
| `python facet.py --report-unreviewed-bursts` | Riporta quanti gruppi di raffica restano da esaminare (sola lettura) |
| `python facet.py --eval-iqa-srcc` | Riporta lo Spearman SRCC di ogni metrica IQA/estetica rispetto alle tue valutazioni a stelle (sola lettura) |
| `python facet.py --mine-insights` | Report di data-mining: inventario delle etichette, correlazioni metrica-etichetta, distribuzione delle categorie, deriva dei percentili, salute dei confronti |
| `python facet.py --mine-insights report.json` | Lo stesso, scrive anche il report completo come JSON |

## Configurazione

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --validate-categories` | Valida le configurazioni delle categorie |

## Tagging

| Comando | Descrizione |
|---------|-------------|
| `python tag_existing.py` | Aggiunge tag alle foto senza tag usando gli embedding CLIP memorizzati |
| `python tag_existing.py --dry-run` | Visualizza in anteprima i tag senza salvare |
| `python tag_existing.py --threshold 0.25` | Soglia di somiglianza personalizzata (predefinita: 0.22) |
| `python tag_existing.py --max-tags 3` | Limita i tag per foto (predefinito: 5) |
| `python tag_existing.py --force` | Riassegna i tag a tutte le foto |
| `python tag_existing.py --db custom.db` | Usa un database personalizzato |
| `python tag_existing.py --config my.json` | Usa una configurazione personalizzata |

## Validazione del database

| Comando | Descrizione |
|---------|-------------|
| `python validate_db.py` | Valida la coerenza del database (interattivo) |
| `python validate_db.py --auto-fix` | Corregge automaticamente tutti i problemi |
| `python validate_db.py --report-only` | Riporta senza chiedere conferma |
| `python validate_db.py --db custom.db` | Valida un database personalizzato |

Controlli: intervalli dei punteggi, metriche dei volti, corruzione dei BLOB, dimensioni degli embedding, volti orfani, valori statistici anomali.

## Manutenzione del database

| Comando | Descrizione |
|---------|-------------|
| `python database.py` | Inizializza/aggiorna lo schema |
| `python database.py --info` | Mostra le informazioni sullo schema |
| `python database.py --migrate-tags` | Popola la tabella di lookup photo_tags (query 10-50x più veloci) |
| `python database.py --rebuild-fts` | Ricostruisce l'indice di ricerca full-text FTS5 da didascalie/tag |
| `python database.py --populate-vec` | Popola la tabella di ricerca vettoriale sqlite-vec dagli embedding |
| `python database.py --refresh-stats` | Aggiorna la cache delle statistiche |
| `python database.py --stats-info` | Mostra lo stato e l'età della cache |
| `python database.py --vacuum` | Recupera spazio, deframmenta |
| `python database.py --analyze` | Aggiorna le statistiche del pianificatore di query |
| `python database.py --optimize` | Esegue VACUUM e ANALYZE |
| `python database.py --export-viewer-db` | Esporta un database leggero per il visualizzatore (rimuove i BLOB, riduce le miniature; incrementale se l'output esiste) |
| `python database.py --export-viewer-db --force-export` | Forza una ri-esportazione completa, anche se il DB del visualizzatore esiste già |
| `python database.py --cleanup-orphaned-persons` | Rimuove le persone senza volti associati |
| `python database.py --cleanup-missing-photos` | Rimuove dal database le foto non più presenti su disco (le eliminazioni a cascata ripuliscono tag, volti rilevati, ecc.; cancella anche le appartenenze agli album, l'indice vettoriale e invalida la cache delle statistiche) |
| `python database.py --cleanup-missing-photos --dry-run` | Visualizza in anteprima i file mancanti senza eliminare |
| `python database.py --cleanup-missing-photos --force` | Procede anche quando ogni foto sembra mancante (protezione contro l'eliminazione di tutto quando un volume è smontato) |
| `python database.py --migrate-storage-fs` | Migra le miniature e gli embedding dai BLOB del database al filesystem |
| `python database.py --migrate-storage-db` | Migra le miniature e gli embedding dal filesystem di nuovo al database |
| `python database.py --add-user alice --role admin` | Aggiunge un utente (richiede la password) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Aggiunge un utente con nome visualizzato |
| `python database.py --migrate-user-preferences --user alice` | Copia le valutazioni da photos a user_preferences |

**Suggerimento sulle prestazioni:** per database di grandi dimensioni (oltre 50k foto), esegui `--migrate-tags`, `--rebuild-fts` e `--populate-vec` una volta, poi `--optimize` periodicamente.

## Visualizzatore web

| Comando | Descrizione |
|---------|-------------|
| `python viewer.py` | Avvia il server su http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Associa una porta diversa (o imposta la variabile d'ambiente `PORT`; predefinita 5000) |
| `python viewer.py --host 127.0.0.1` | Associa un'interfaccia specifica (predefinita `0.0.0.0`) |
| `python viewer.py --production` | Modalità produzione (worker uvicorn) |
| `python viewer.py --production --workers 4` | Modalità produzione con N worker (predefinito 1) |

## Flussi di lavoro comuni

### Configurazione iniziale
```bash
python facet.py /path/to/photos     # Valuta tutte le foto (multi-pass automatico)
python facet.py --cluster-faces-incremental # Raggruppa i volti
python database.py --migrate-tags    # Abilita query sui tag più veloci
python viewer.py                    # Visualizza i risultati
```

### Dopo modifiche alla configurazione
```bash
python facet.py --recompute-average                # Aggiorna tutti i punteggi con i nuovi pesi
python facet.py --recompute-category portrait      # Aggiorna solo una categoria (più veloce)
```

### Configurazione del riconoscimento facciale
```bash
python facet.py /path               # Estrae i volti durante la scansione
python facet.py --cluster-faces-incremental     # Raggruppa in persone
python facet.py --suggest-person-merges         # Trova i duplicati
# Usa /persons nel visualizzatore per unire/rinominare
```

### Configurazione multi-utente
```bash
# Aggiungi utenti (richiede la password)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Modifica scoring_config.json per impostare directories e shared_directories
# Migra le valutazioni esistenti a un utente
python database.py --migrate-user-preferences --user alice
```

### Cambiare il modello di tagging
```bash
# Modifica scoring_config.json: "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Riassegna i tag con il nuovo modello
```

### Cambiare il profilo VRAM
```bash
# Modifica scoring_config.json: "vram_profile": "auto"
# Oppure usa uno specifico: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Controlla le distribuzioni
python facet.py --recompute-average        # Applica i nuovi pesi
```
