# Riferimento dei comandi

> 🌐 [English](../COMMANDS.md) · [Français](../fr/COMMANDS.md) · [Deutsch](../de/COMMANDS.md) · **Italiano** · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · [简体中文](../zh/COMMANDS.md)

[Scansione](#scansione) · [Anteprima ed esportazione](#anteprima-ed-esportazione) · [Operazioni di ricalcolo](#operazioni-di-ricalcolo) · [Riconoscimento facciale](#riconoscimento-facciale) · [Gestione delle miniature](#gestione-delle-miniature) · [Diagnostica](#diagnostica) · [Informazioni sui modelli](#informazioni-sui-modelli) · [Ottimizzazione dei pesi](#ottimizzazione-dei-pesi-confronto-a-coppie) · [Configurazione](#configurazione) · [Tagging](#tagging) · [Validazione del database](#validazione-del-database) · [Manutenzione del database](#manutenzione-del-database) · [Visualizzatore web](#visualizzatore-web) · [Flussi di lavoro comuni](#flussi-di-lavoro-comuni)

> Tag dei requisiti usati di seguito: `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (profilo VRAM). Vedi la [matrice delle funzionalità](INSTALLATION.md#requisiti-delle-funzionalità).

## Scansione

| Comando | Descrizione |
|---------|-------------|
| `python facet.py /path` | Scansiona una directory (multi-pass, rilevamento automatico della VRAM) |
| `python facet.py /path --force` | Riscansiona i file già elaborati |
| `python facet.py /path --single-pass` | Carica tutti i modelli in una volta; solo `legacy`/`8gb` (vedi [Modalità di elaborazione](#modalità-di-elaborazione)) |
| `python facet.py /path --pass quality` | Esegue solo la valutazione qualità TOPIQ |
| `python facet.py /path --pass quality-iaa` | Esegue solo la valutazione del merito estetico TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Esegue solo la valutazione qualità TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Esegue solo la diagnosi qualità + distorsioni LIQE |
| `python facet.py /path --pass tags` | Esegue solo il tagging (il modello dipende dal profilo VRAM) |
| `python facet.py /path --pass composition` | Esegue solo il rilevamento dei modelli compositivi SAMP-Net |
| `python facet.py /path --pass faces` | Esegue solo il rilevamento dei volti InsightFace |
| `python facet.py /path --pass embeddings` | Esegue solo l'estrazione degli embedding CLIP/SigLIP (non scrive tag) |
| `python facet.py /path --pass saliency` | Esegue solo il rilevamento della salienza del soggetto BiRefNet |
| `python facet.py /path --db custom.db` | Usa un file di database personalizzato |
| `python facet.py /path --config my.json` | Usa una configurazione di punteggio personalizzata |
| `python facet.py --resume` | Riprende l'ultima scansione interrotta, fallita o terminata in modo anomalo |
| `python facet.py --retry-failed` | Rielabora i file falliti nell'ultima scansione (`--retry-failed all` per ogni esecuzione) |
| `python facet.py /path --force-since 2026-01-01` | Come `--force`, solo per le foto scansionate l'ultima volta prima della data |
| `python facet.py /path --watch` | Riscansiona quando compaiono nuove foto (richiede `pip install watchdog`; `--watch-debounce N`, predefinito 30s) |
| `python facet.py /path --force-low-space` | Salta il controllo dello spazio libero prima della scansione |

**`--resume`** recupera anche una scansione terminata da un crash, da memoria esaurita o da un'interruzione di corrente: un'esecuzione ancora contrassegnata come `running` il cui heartbeat è più vecchio di `processing.scan_stale_seconds` (predefinito 120). Riutilizza le directory di quell'esecuzione. Con `--force`, salta i file già rivalutati dall'inizio dell'esecuzione. Rifiuta di partire se un'altra scansione sembra attiva.

### Registrazione delle scansioni

Facet registra ogni scansione (stato, modalità, directory, contatori) e ogni errore per singolo file. Ctrl+C contrassegna l'esecuzione come `interrupted`, così `--resume` può riprenderla. I file falliti vengono elencati e ritentati solo con `--retry-failed`. Il visualizzatore mostra l'avanzamento della scansione dalle righe `@FACET_PROGRESS` della CLI.

### Modalità di elaborazione

**Multi-pass (predefinita):** rileva la VRAM e carica i modelli uno alla volta. Ogni passaggio carica il proprio modello, elabora tutte le foto, poi lo scarica, così i modelli di alta qualità funzionano anche con VRAM limitata.

**Single-pass (`--single-pass`):** carica tutti i modelli in una volta. Più veloce, ma richiede più VRAM.

- Valuta l'estetica con la head CLIP+MLP, quindi si applica ai profili `legacy` e `8gb`.
- Su `16gb` e `24gb` il modello estetico è TOPIQ, che viene eseguito solo in multi-pass. Una richiesta single-pass (`--single-pass` o `processing.mode: "single-pass"`) registra un avviso ed esegue il multi-pass.
- `--pass NAME` e `--dry-run` saltano questo controllo.
- La modalità commerciale mantiene il single-pass, perché lì l'estetica è valutata dal Q-ReAlign nativo.

**Nota di aggiornamento:** le versioni precedenti salvavano un'estetica neutra di 5,0 per ogni foto di una scansione single-pass su `16gb`/`24gb`. Riscansiona quelle cartelle con `--force` in multi-pass. Per trovarle: `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Passaggio specifico (`--pass NAME`):** esegue un solo passaggio, per aggiornare alcune metriche senza una rielaborazione completa.

| Passaggio | Modello | Output | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | punteggio `aesthetic` (0-10) | ~2 GB |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (merito artistico, addestrato su AVA) | Condivisa con TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (qualità del volto) | Condivisa con TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnosi delle distorsioni (sfocatura, sovraesposizione, rumore) | ~2 GB |
| `tags` | CLIP / Qwen VLM | Tag semantici dal vocabolario configurato | 0-16 GB |
| `composition` | SAMP-Net | `composition_pattern` (8 modelli) + `comp_score` | ~2 GB |
| `faces` | InsightFace buffalo_l | Volti, punti di riferimento, occhi chiusi, embedding di riconoscimento | ~2 GB |
| `embeddings` | CLIP ViT-L-14 o SigLIP 2 NaFlex | `clip_embedding` per somiglianza e tagging | 4-5 GB |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 GB |

Le misure multi-pass usano orologi monotoni. Il tempo EXIF del lotto e la somma dei secondi di lavoro dei fallback sono inclusi nella decodifica; i fallback paralleli possono sovrapporsi. Aggregazione, miniature (lettura sorgente inclusa) e salvataggio senza miniature sono intervalli separati; il salvataggio comprende preparazione e commit. I passaggi limitati saltano aggregazione e miniature fotografiche. Sovrapposizione decodifica/modelli e ricostruzioni annidate restano invariate: non sommare tutti i timer né interpretare i secondi di lavoro EXIF come percentuale del tempo totale. Il passaggio singolo è escluso. Per una baseline, analizzare una copia fissa di 500 RAW/JPEG in un database temporaneo e conservare riepilogo, revisione, profilo, worker, dimensione dei blocchi, archiviazione e condizioni cache. Ripetere nelle stesse condizioni. Nessuna raccolta di riferimento o benchmark prima/dopo disponibile; nessun aumento di velocità dichiarato.

## Anteprima ed esportazione

| Comando | Descrizione |
|---------|-------------|
| `python facet.py /path --dry-run` | Valuta 10 foto campione senza salvare |
| `python facet.py /path --dry-run --dry-run-count 20` | Valuta 20 foto campione |
| `python facet.py --export-csv` | Esporta tutti i punteggi in un CSV con data e ora |
| `python facet.py --export-csv output.csv` | Esporta in un file CSV specifico |
| `python facet.py --export-json` | Esporta ogni metrica memorizzata in un JSON con data e ora |
| `python facet.py --export-json output.json` | Esporta in un file JSON specifico |
| `python facet.py --export-manifest` | Scrive `facet_manifest.json` per strumenti esterni come il plug-in di Lightroom Classic |
| `python facet.py --export-manifest /path` | Limita il manifesto alle foto sotto un percorso |
| `python facet.py --export-manifest --user alice` | Modalità multiutente: usa le valutazioni di Alice (tag e punteggi restano globali) |
| `python facet.py --import-lightroom FILE` | Importa valutazioni, pick e rifiuti del plug-in; vince Lightroom |
| `python facet.py --import-lightroom FILE --user alice` | Modalità multiutente: scrive le valutazioni di Alice; **obbligatorio** su un'installazione multiutente |
| `python facet.py --import-sidecars` | Importa valutazioni, etichette, Conserva/Rifiuta, GPS manuale e parole chiave dai sidecar XMP |
| `python facet.py --import-sidecars /path` | Importa solo per le foto sotto un percorso |
| `python facet.py --import-sidecars /path --dry-run` | Stampa un piano JSON di modifiche e conflitti; non scrive nulla |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Importa solo questi gruppi: `review` (stelle, preferito, rifiuto, Conserva), `gps`, `keywords` (predefinito: tutti) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Applica i campi di revisione anche su una modifica locale più recente (`newer_local_edit`); esamina prima con `--dry-run` |
| `python facet.py --import-sidecars --user alice` | Modalità multiutente: importa valutazioni e Conserva/Rifiuta nell'account di Alice, per le foto che può vedere |
| `python facet.py --import-sidecars --sidecar-naming full` | Legge `<image.ext>.xmp` / `<image.ext>.facet.xmp` (predefinito); vince il file più recente |
| `python facet.py --import-sidecars --sidecar-naming basename` | Legge `<image>.xmp` (senza estensione); rifiuta i nomi base condivisi |
| `python facet.py --import-sidecars --sidecar-naming auto` | Accetta entrambi i nomi; salta una foto che li ha entrambi |
| `python facet.py --import-sidecars --overwrite-manual-gps` | Sostituisce il GPS manuale già impostato in Facet con quello del sidecar |
| `python facet.py --export-sidecars` | Scrive o unisce i sidecar `<image>.xmp` per tutte le foto |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Rimuove anche le parole chiave di Facet non più presenti (richiede ExifTool) |
| `python facet.py --export-sidecars /path` | Esporta i sidecar solo per le foto sotto un percorso |
| `python facet.py --export-sidecars --user alice` | Modalità multiutente: esporta valutazioni e Conserva/Rifiuta di Alice, per le foto che può vedere |
| `python facet.py --export-sidecars --embed-originals` | Scrive i metadati anche **dentro** gli originali JPEG/HEIC/TIFF/PNG/DNG |
| `python facet.py --export-sidecars --score-to-stars` | Imposta `xmp:Rating` dal punteggio per le foto che non hai valutato |

**Dry run.** Su `16gb`/`24gb` la colonna estetica mostra `n/a`, perché TOPIQ viene eseguito solo in una scansione reale (la modalità commerciale mostra il punteggio Q-ReAlign). L'aggregato la conta come un 5,0 neutro.

**CSV e JSON.** La colonna `tags` contiene solo i tag IA; i [tag manuali](VIEWER.md#tag-manuali) non sono inclusi. Nel JSON, l'oggetto `scores` di ogni foto contiene ogni metrica memorizzata; NULL, numeri non finiti e BLOB diventano `null`. L'esportazione JSON rifiuta di scrivere sul database o sui suoi file `-wal`/`-shm`/`-journal`.

**Manifesto.**

- L'argomento opzionale limita *quali foto* vengono esportate. Il file è sempre `facet_manifest.json` nella directory di lavoro.
- Contiene `star_rating`/`is_favorite`/`is_rejected` (globali, o quelli di `--user`), `is_burst_lead`, tag IA più manuali e un conteggio `pending_corrections`. Un conteggio diverso da zero stampa un avviso che rimanda a `--detect-panoramas`.
- _manifest versione 2_ aggiunge `burst_group_id`, `sequence_kind`, `sequence_group_id` e `score_stars` (il punteggio convertito tramite `xmp_export.score_to_rating`). Un plug-in compilato per questa versione rifiuta un manifesto più vecchio: riesporta. Vedi [il plug-in Facet](INTEROP.md#il-plug-in-facet-valutazioni-a-stelle-flag-pick-campi-di-metadati-e-parole-chiave).

**`--import-lightroom`** legge l'esportazione propria del plug-in, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), non il manifesto. Un file in formato errato viene rifiutato prima di qualsiasi scrittura. Il valore di Lightroom vince per ogni campo che il file porta; i campi omessi mantengono il valore di Facet. Stampa `matched=… unmatched=… changed=…`. Vedi [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Sincronizzazione bidirezionale dei metadati.** Facet scrive valutazioni, etichette colore, parole chiave, didascalie e regioni di volti nominati in un sidecar `<image>.xmp` standard letto da Lightroom, darktable, digiKam, immich e altri.

- Gli originali non vengono mai modificati, a meno che tu non aggiunga `--embed-originals` (solo JPEG/HEIC/TIFF/PNG/DNG; i RAW non vengono mai toccati).
- Le parole chiave sono i tag IA più i tuoi [tag manuali](VIEWER.md#tag-manuali). Vengono solo aggiunte, a meno che `--reconcile-keywords` rimuova quelle scritte in precedenza da Facet; le parole chiave esterne vengono conservate. Vedi [Tag manuali e parole chiave XMP](INTEROP.md#tag-manuali-e-parole-chiave-xmp).
- L'incorporamento e l'unione delle parole chiave richiedono **exiftool**. Senza, Facet scrive un sidecar XML semplice.

**Importazione dei sidecar.**

- Le parole chiave importate diventano [tag manuali](INTEROP.md#tag-manuali-e-parole-chiave-xmp); non serve `--migrate-tags`.
- Una decisione Facet (Conserva, Rifiuta o indeciso) senza valutazione o etichetta standard viene applicata senza il controllo sulla data di scansione.
- Con `--user`, parole chiave e GPS restano globali. Con `--export-sidecars --user`, parole chiave, GPS e data di scatto restano globali.
- Come un sidecar viene confrontato con le modifiche locali: [Anteprima di importazione e conflitti](INTEROP.md#anteprima-di-importazione-dei-sidecar-e-conflitti-di-revisione).

### Immich Sync

Invia le valutazioni e i preferiti di Facet a un server [Immich](https://immich.app/) (unidirezionale, Facet → Immich, solo API REST). Gli asset vengono abbinati tramite `originalPath` attraverso le mappature di prefisso di percorso nel blocco di configurazione `immich`.

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --immich-test` | Verifica la connessione e la chiave API (`immich.url` + `immich.api_key`, inviata come `x-api-key`) |
| `python facet.py --immich-sync` | Invia le valutazioni a stelle (1–5) e i preferiti; rispetta `--dry-run` e `--user` |
| `python facet.py --immich-sync --dry-run` | Riporta cosa cambierebbe senza scrivere |

Vengono inviate solo le valutazioni 1–5 (mai 0/−1). Un album facoltativo delle scelte migliori raccoglie le foto sopra una soglia di valutazione. Vedi [Configurazione — Immich Sync](CONFIGURATION.md#immich-sync).

### Piani per pile Immich

Accettano `--config`, `--db` e `--user`; in modalità multiutente serve un proprietario esistente. L'anteprima non scrive mai. L'applicazione richiede il digest del piano esaminato.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Anteprima delle pile remote da importare |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Anteprima delle pile locali da creare a distanza |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Applica il piano esaminato |

- Ripeti `--stack-id UUID` per scegliere i gruppi sorgente.
- `--stack-plan-out NEW_JSON` scrive un nuovo file privato (POSIX `0600`) e non ne sovrascrive mai uno. Su Windows, scegli una cartella la cui ACL limiti l'accesso al tuo account.
- Limiti: 1000 gruppi, 1000 membri per gruppo, 20000 membri in totale, 16 MiB.
- Mappature incomplete e sovrapposizioni saltano l'intero gruppo. Le pile esistenti non vengono mai aggiornate.

Vedi [permessi, conflitti e concorrenza remota](IMMICH.md#importare-e-inviare-pile-manuali).

## Operazioni di ricalcolo

Questi comandi aggiornano metriche o derivano nuovi dati senza rieseguire l'intera pipeline di valutazione. La maggior parte riutilizza miniature e punti di riferimento memorizzati ed è leggera per la CPU; le righe AI (come `--generate-captions`) richiedono una GPU.

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --recompute-average` | Ricalcola punteggi aggregati e categorie dalle metriche memorizzate (nessuna immagine viene riletta) |
| `python facet.py --recompute-category portrait` | Ricalcola i punteggi solo per una categoria |
| `python facet.py --tag-untagged` | Assegna i tag solo alle foto che non ne hanno ancora, dagli embedding memorizzati |
| `python facet.py --recompute-tags` | Riassegna i tag a tutte le foto con il modello configurato |
| `python facet.py --recompute-tags-vlm` | Riassegna i tag a tutte le foto con il tagger VLM |
| `python facet.py --detect-moments` | Etichetta le nuove foto con il loro momento narrativo (eseguito dopo ogni scansione) |
| `python facet.py --recompute-moments` | Rietichetta i momenti narrativi dell'intera libreria |
| `python facet.py --discover-moments` | Propone un vocabolario di momenti dalle tue didascalie in `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | Segnala screenshot, documenti, ricevute, meme e diapositive (eseguito dopo ogni scansione) |
| `python facet.py --recompute-junk` | Rivaluta `junk_kind` per l'intera libreria |
| `python facet.py --recompute-saliency` | `[GPU]` Ricalcola la salienza del soggetto dalle miniature memorizzate; `--force` rifà tutto |
| `python facet.py --recompute-composition-cpu` | Ricalcola la composizione, basata su regole (CPU, qualsiasi profilo) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Ricalcola la composizione con SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` Riempie i punteggi mancanti di TOPIQ IAA, NR-Face e LIQE dalle miniature memorizzate. Attivo su ogni profilo; su CPU (`legacy`) è molto più lento |
| `python facet.py --detect-text` | Legge il testo presente nell'immagine in `ocr_text` perché la ricerca lo trovi (opzionale, vedi nota) |
| `python facet.py --recompute-text` | Riesegue l'OCR sull'intera libreria |
| `python facet.py --recompute-colors` | Estrae tonalità dominante e temperatura caldo/freddo in `dominant_hue` / `color_temp` (CPU, veloce) |
| `python facet.py --recompute-form` | Ricalcola simmetria, equilibrio, entropia dei bordi, complessità frattale e armonia cromatica (CPU) |
| `python facet.py --recompute-skin-tone` | Ricalcola la naturalezza del tono della pelle nei ritratti (CPU; solo nota indicativa nella critica) |
| `python facet.py --recompute-distortions` | Etichetta le probabili distorsioni (sfocatura da movimento, dominante di colore, …) e le correla con `liqe_score` / `noise_sigma` (indicativo) |
| `python facet.py --upgrade-db` | Migra lo schema ed esegue l'intera catena di backfill (vedi nota) |
| `python facet.py --recompute-blinks` | Ricalcola il rilevamento degli occhi chiusi dai punti di riferimento memorizzati (CPU, veloce) |
| `python facet.py --recompute-eyes-expression` | Ricalcola i punteggi di occhi aperti + espressione dai punti di riferimento memorizzati (CPU, veloce) |
| `python facet.py --recompute-face-signals` | Riempie i punteggi di occhi aperti + sorriso per singolo volto dai punti di riferimento memorizzati (CPU, veloce) |
| `python facet.py --recompute-burst` | Ricalcola i gruppi di raffica (registra `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Rileva bracketing di esposizione e panorami (eseguito dopo ogni scansione; vedi nota) |
| `python facet.py --detect-panoramas` | Rileva i panorami dalle miniature memorizzate (esegue prima la passata dei bracket; CPU) |
| `python facet.py --detect-duplicates` | Rileva le foto duplicate tramite pHash (registra `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Valuta le soglie di coseno per i quasi-duplicati (precisione/richiamo con le etichette) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Genera didascalie AI con il VLM |
| `python facet.py --translate-captions` | Traduce le didascalie inglesi nella lingua configurata (CPU, MarianMT) |
| `python facet.py --extract-gps` | Copia il GPS EXIF nel database; salta le posizioni impostate nel visualizzatore |
| `python facet.py --rescan-gps` | Riestrae il GPS EXIF per tutte le foto (sovrascrive); salta le posizioni impostate nel visualizzatore |
| `python facet.py --recompute-embeddings` | Ricalcola gli embedding CLIP/SigLIP per tutte le foto (necessario dopo un cambio di modello) |
| `python facet.py --score-topiq` | `[GPU]` Ricalcola `topiq_score` per ogni foto con una miniatura (sovrascrive) |
| `python facet.py --backfill-focal-35mm` | Riempie la lunghezza focale equivalente a 35mm dall'EXIF dove manca |
| `python facet.py --backfill-clipping` | Deriva le percentuali di clipping per canale dagli istogrammi memorizzati (riprendibile) |
| `python facet.py --recompute-silhouette` | Ricalcola `is_silhouette` con la regola basata sul volto (vedi nota) |
| `python facet.py --repair-int-columns` | Arrotonda i valori frazionari che uno scrittore EXIF esterno ha memorizzato in colonne intere (come ISO) |
| `python facet.py --repair-neutral-iqa` | Cancella i falsi punteggi IQA neutri di 5,0 memorizzati prima della 1.20 (vedi nota) |
| `python facet.py --compute-recommendations` | Analizza il database e mostra un riepilogo dei punteggi |
| `python facet.py --compute-recommendations --verbose` | Mostra statistiche dettagliate |
| `python facet.py --compute-recommendations --apply-recommendations` | Applica automaticamente le correzioni dei punteggi |
| `python facet.py --compute-recommendations --simulate` | Visualizza in anteprima le modifiche previste |

**`--recompute-average`** non conserva alcuno snapshot: per annullare, ripristina uno snapshot dei pesi e ricalcola. Dopo l'aggiornamento dalla 1.20 o da una versione precedente, esegui prima `--recompute-silhouette`, poi `--recompute-average` due volte. La prima passata memorizza i nuovi percentili, quindi la seconda cambia ancora alcune righe.

**Momenti.**

- `--detect-moments` codifica ogni nuova didascalia una sola volta in `caption_embedding`. Il primo backfill di una libreria esistente è meglio farlo con una GPU; aggiungi `--limit N` per provarlo su un campione.
- Aggiungi `--dry-run --verbose` a `--recompute-moments` (o a `--detect-junk`) per l'anteprima senza scrivere.
- `narrative_moments.vlm_tiebreak` (16gb/24gb): quando `narrative_moments.vlm_tiebreak.enabled` è impostato, il VLM del profilo riclassifica i fotogrammi a bassa confidenza.
- `--discover-moments` raggruppa gli embedding delle didascalie memorizzati e dà un nome a ogni gruppo. Non riscrive mai la configurazione attiva. Esegui prima `--detect-moments`; regola con `--discover-min-cluster-size N`.
- `--generate-captions` salta le foto non etichettate, `other` e a bassa confidenza quando `narrative_moments.caption_min_confidence > 0`.

**Junk.** Le foto pulite sono marcate `not_junk`, così le esecuzioni successive controllano solo quelle nuove.

**`--detect-text`** è opzionale: richiede `ocr.enabled` in `scoring_config.json` e `pip install easyocr`. Vedi [Configurazione — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** trova i bracketing di esposizione dagli EXIF, poi i panorami dalla geometria delle miniature, e porta lo scatto principale di ogni raffica sulla sua esposizione di base. Viene eseguito anche in `--upgrade-db`. Le viste di selezione **Bracketing di esposizione** / **Panorami** / **Panorami HDR** del visualizzatore e gli interruttori `hide_brackets` / `hide_panoramas` non fanno nulla finché non è stato eseguito. Ogni esecuzione rietichetta l'intera libreria, quindi rilanciarlo (o `--detect-panoramas`) sceglie un nuovo fotogramma rappresentativo dopo che hai selezionato il vecchio.

**`--upgrade-db`** migra lo schema ed esegue: extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. È sicuro da rieseguire e salta i passaggi pesanti come le didascalie. Raddrizza anche le miniature HEIF lasciate di lato da pillow-heif 1.6, insieme ai loro volti; i file originali non vengono mai scritti. I file HEIF che non riesce a leggere vengono ritentati all'esecuzione successiva.

**`--recompute-silhouette`** legge solo il database, conferma a lotti e rispetta `--dry-run`.

- Il rapporto raggruppa le foto in base a come i loro riquadri dei volti si allineano alla miniatura: `exact`, `scaled`, `count_mismatch` (corrispondenza non validata), `other`.
- Una foto senza volti, o i cui riquadri non possono essere collocati, viene impostata a 0.
- Le foto con `face_count` NULL, o con volti ma senza miniatura, restano invariate (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Esegui poi `--recompute-average`. Vedi [SCORING.md](SCORING.md).

**`--repair-int-columns`** legge solo il database. La galleria li mostra correttamente anche senza, ma filtri per intervallo e ordinamenti usano il valore memorizzato, quindi una foto mostrata a ISO 63 può sfuggire. I valori che non possono essere interi diventano NULL.

**`--repair-neutral-iqa`** imposta a NULL ogni valore esattamente 5,0 in `aesthetic_iaa`, `face_quality_iqa` e `liqe_score`, e stampa il conteggio per colonna.

- Non tocca `aesthetic`, `topiq_score`, `aesthetic_v25` né `quality_score`.
- Anche un punteggio reale esattamente 5,00 viene cancellato; `--recompute-iqa` lo riempie di nuovo, forse con una leggera differenza.
- Esegui poi `--recompute-iqa` e `--recompute-average`.
- Rifiutato con `--dry-run` (codice di uscita 2). Non fa parte di `--upgrade-db`. Ricarica le pagine di galleria aperte per vedere i nuovi intervalli dei filtri.

### Modelli di qualità supplementari

Tre modelli PyIQA valutano oltre il punteggio estetico principale TOPIQ. Condividono la VRAM con TOPIQ e vengono eseguiti nella scansione multi-pass predefinita.

- **TOPIQ IAA** (`--pass quality-iaa`): merito artistico addestrato su AVA, separato dalla qualità tecnica. Memorizzato come `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`): qualità della regione del volto. Memorizzato come `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`): punteggio di qualità più una diagnosi delle distorsioni (sfocatura da movimento, sovraesposizione, rumore). Memorizzato come `liqe_score`.

Quando un modello non riesce a valutare una foto:

- Memorizza NULL, non un 5,0 neutro. Un errore di memoria GPU esaurita viene prima ritentato con metà della dimensione del batch, fino a una sola immagine.
- LIQE salta le miniature con lato corto inferiore a 224 px (dopo aver limitato il lato lungo a 1024 px).
- NR-Face salta le foto con `face_count` 0. Una foto in cui non trova alcun volto viene ricordata in `iqa_declined` fino a una nuova scansione (`--force`), `--refresh-thumbnails` o `--fix-thumbnail-rotation`. Aggiornare pyiqa non la cancella.
- Gli altri errori non vengono memorizzati; il successivo `--recompute-iqa` riprova.
- Con `--pass quality`, `quality-iaa`, `quality-face` e `quality-liqe`, una foto fallita mantiene il valore memorizzato.
- Una scansione completa registra una foto il cui modello TOPIQ fallisce, per `--retry-failed`; `--pass quality` no.

`--recompute-iqa` riempie solo le colonne NULL e non sostituisce mai un valore memorizzato, compreso un 5,0 neutro di una versione precedente. Cancellali con `--repair-neutral-iqa`, poi esegui `--recompute-iqa` e `--recompute-average`, oppure riscansiona con `--force`. Vedi [Dimensioni IQA supplementari](SCORING.md#dimensioni-iqa-supplementari).

### Benchmark e punteggi supplementari

| Comando | Descrizione |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Riempie `aesthetic_clip` dagli embedding in cache (nessuna inferenza sulle immagini; non fa parte dell'`aggregate` predefinito). Vedi [SCORING.md](SCORING.md#segnali-supplementari-non-inclusi-nellaggregato-predefinito) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcola SRCC + PLCC rispetto al riferimento AVA per ogni colonna di punteggio |

### Salienza del soggetto

`--pass saliency` e `--recompute-saliency` usano BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, tramite `transformers`, ~3 GB di VRAM) per trovare il soggetto, poi ne derivano quattro metriche:

- **Nitidezza del soggetto**: il soggetto è a fuoco (varianza laplaciana, soggetto rispetto allo sfondo).
- **Prominenza del soggetto**: area del soggetto / area dell'inquadratura. Alta per un soggetto dominante (es. macro).
- **Posizionamento del soggetto**: punteggio della regola dei terzi per il centroide del soggetto.
- **Separazione dallo sfondo**: contrasto dei bordi tra soggetto e sfondo (qualità del bokeh).

La salienza gira su ogni profilo; `legacy` la esegue su CPU, più lentamente. `--recompute-saliency` funziona con il volume della libreria offline ed è riprendibile. Su CUDA la dimensione del batch segue la VRAM libera (circa 2,4 GiB per immagine a 1024 px, da 1 a 8 immagini) e si dimezza dopo un errore di memoria esaurita.

- **Una foto fallita** viene registrata come ERROR e non viene scritto nulla. Una foto mai valutata resta NULL e viene ripresa dal successivo `--recompute-saliency`; una che aveva già la salienza mantiene i suoi valori, anche con `--recompute-saliency --force`. Una nuova scansione completa (ad esempio `python facet.py --force`) memorizza NULL per essa.
- **Una foto senza soggetto** memorizza NULL per nitidezza, posizionamento e separazione, prominenza 0.0 e un `subject_bbox` NULL (e `power_point_score` NULL dal passaggio di composizione). È un risultato definitivo; non viene misurata di nuovo.
- **Le righe più vecchie** memorizzavano invece un 5.0 neutro. `--recompute-saliency` e `--recompute-composition-cpu` le riscrivono. `--recompute-saliency` riprende anche le foto valutate prima che esistesse `subject_bbox`.
- Una metrica facoltativa NULL è esclusa dall'aggregato e il suo peso viene redistribuito alle metriche presenti; solo se mancano tutte, l'aggregato usa il valore neutro 5.0. Vedi [Sistema di punteggio](SCORING.md).

### Modelli di tagging

Il modello di tagging dipende dal profilo VRAM:

| Profilo | Modello | Come funziona |
|---------|-------|-------------|
| `legacy` | Somiglianza CLIP | Somiglianza coseno tra gli embedding dell'immagine e del testo dei tag. Nessun modello aggiuntivo. |
| `8gb` | Somiglianza CLIP | Come legacy, sugli embedding CLIP ViT-L-14 memorizzati. |
| `16gb` | Qwen3.5-2B | Modello multimodale per il tagging delle scene. |
| `24gb` | Qwen3.5-4B | Modello multimodale più grande. |

Tutti i tagger mappano l'output sul vocabolario di tag configurato. Usa `--recompute-tags` per riassegnare i tag con il modello del profilo, o `--recompute-tags-vlm` per il VLM.

**Quando vengono scritti i tag.** Sui profili a similarità CLIP (`legacy`/`8gb`, e `16gb`/`24gb` quando il passaggio VLM non è pianificato), una scansione multi-pass assegna i tag durante il passaggio degli embedding, quindi categoria e aggregato della scansione li usano già. Un'esecuzione con un solo `--pass` (per esempio `--pass embeddings`) non scrive tag. `--pass tags` su un profilo CLIP si ferma e rimanda a `--recompute-tags`. Le righe esistenti mantengono la loro categoria fino a `--recompute-average`.

### Modelli di embedding

Due modelli di embedding, selezionati per profilo VRAM tramite `clip_config`:

| Config | Modello | Dimensioni | Usato da |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | profili 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | profili legacy, 8gb |

Gli embedding alimentano il tagging, il rilevamento dei duplicati, la ricerca di foto simili e l'estetica CLIP+MLP (legacy/8gb). Il cambio di modello richiede di ricalcolare gli embedding di tutte le foto (`--force`, `--pass embeddings` o `--recompute-embeddings`).

## Riconoscimento facciale

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Estrae i volti per le nuove foto (GPU, parallelo) |
| `python facet.py --extract-faces-gpu-force` | Elimina tutti i volti e li riestrae (GPU; le persone con nome vengono conservate; estrattore permissivo in modalità commerciale) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, conserva tutte le persone (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, conserva solo le persone con nome (CPU) |
| `python facet.py --cluster-faces-force` | Riclustering completo, elimina tutte le persone (CPU) |
| `python facet.py --suggest-person-merges` | Suggerisce possibili unioni di persone |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Usa una soglia più rigorosa |
| `python facet.py --refill-face-thumbnails-incremental` | Genera le miniature dei volti mancanti (CPU, parallelo) |
| `python facet.py --refill-face-thumbnails-force` | Rigenera TUTTE le miniature dei volti (CPU, parallelo) |

## Gestione delle miniature

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Ruota le miniature memorizzate secondo l'orientamento EXIF |
| `python facet.py --refresh-thumbnails` | Ricostruisce le miniature RAW dall'anteprima incorporata dalla fotocamera |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Lo stesso, con più letture in parallelo |

**`--fix-thumbnail-rotation`** serve per le foto elaborate prima che l'orientamento EXIF fosse gestito. Legge solo l'intestazione EXIF e la miniatura memorizzata.

**`--refresh-thumbnails`** ridisegna la miniatura memorizzata di ogni foto RAW attraverso il profilo di visualizzazione (prima l'anteprima della fotocamera, poi la demosaicizzazione come ripiego; vedi [CONFIGURATION.md](CONFIGURATION.md#decodifica-raw)). Usalo su una libreria scansionata prima che esistesse quel profilo: le miniature più vecchie appiattiscono le differenze di esposizione tra gli scatti di un bracket. Non carica alcun modello e non cambia alcun punteggio.

- **La velocità** dipende dal throughput del disco o della rete, non dalla CPU. `--refresh-thumbnails-workers` (predefinito 8) imposta quanti file vengono letti contemporaneamente: aumentalo su un mount di rete veloce, riducilo su un disco locale lento. Valori molto alti costano memoria.
- **Riprendibile.** Fermalo con Ctrl-C e la volta successiva riprende da dove si era fermato. Un'esecuzione completata riparte da zero la volta dopo.
- **I rendering neri** (per esempio da un RAW troncato) vengono scartati: la foto mantiene la vecchia miniatura, viene registrata per nome e ritentata all'esecuzione successiva.
- **Gli scatti di un bracket** vengono ridisegnati senza l'anteprima della fotocamera né il guadagno di esposizione, così ogni riquadro mostra ciò che il sensore ha registrato (vedi [CONFIGURATION.md](CONFIGURATION.md#i-fotogrammi-di-un-bracketing-vengono-renderizzati-senza-correzioni)). Eseguilo dopo `--detect-sequences`.

### Cosa aggiorna una miniatura memorizzata

Le miniature vengono generate al momento della scansione, quindi una libreria scansionata prima che esistesse il profilo di visualizzazione mantiene il vecchio rendering nella griglia di galleria. Due cose le aggiornano:

| Percorso | Copre | Costo |
|------|--------|------|
| Una nuova scansione (`python facet.py <dir>`) | Tutto ciò che scansiona, miniatura e istogramma | Scansione completa |
| `--refresh-thumbnails` | La miniatura di ogni riga RAW | Limitato dallo storage, ore su una libreria grande |

**Non succede nulla da solo.** La vista dettaglio è sempre aggiornata, ma la griglia di galleria mostra la miniatura memorizzata. Un banner rimovibile conta le righe ancora in attesa. Il conteggio può restare indietro fino a un'ora dopo una nuova scansione; `--refresh-thumbnails` e `python database.py --refresh-stats` lo aggiornano.

## Diagnostica

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --doctor` | Esegue controlli diagnostici (Python, GPU, ONNX Runtime, dipendenze, configurazione, database) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simula l'hardware GPU per la diagnostica |

`--doctor` riporta la versione di Python, la build PyTorch/CUDA, la GPU e il driver, la build e i provider di ONNX Runtime, il profilo VRAM consigliato, le dipendenze opzionali e lo stato di configurazione/database. Su CUDA prova anche a caricare ONNX Runtime sulla GPU. Quando PyTorch o ONNX Runtime è la build sbagliata, stampa il comando `pip install` che la corregge (vedi [ONNX Runtime per il rilevamento dei volti](INSTALLATION.md#onnx-runtime-per-il-rilevamento-dei-volti)).

`--simulate-gpu NAME` e `--simulate-vram GB` richiedono `--doctor`; `--simulate-vram` richiede anche `--simulate-gpu`.

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --check-raw-rendering` | Renderizza 20 foto RAW campionate con le vecchie e le attuali impostazioni di decodifica |
| `python facet.py --check-raw-rendering 50` | Campiona invece 50 foto |

Sola lettura. Stampa la luminanza media di ogni rendering: la luminosità automatica di LibRaw, la demosaicizzazione a guadagno fisso e l'anteprima della fotocamera. Usalo per verificare `raw_decode.bright` sui tuoi file prima di una scansione o di `--refresh-thumbnails`. Le colonne fisso e anteprima mantengono i passi di esposizione di un bracket; la luminosità automatica li appiattisce.

## Informazioni sui modelli

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --list-models` | Mostra i modelli disponibili e i requisiti di VRAM |

## Ottimizzazione dei pesi (confronto a coppie)

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --comparison-stats` | Mostra le statistiche dei confronti a coppie |
| `python facet.py --optimize-weights` | Ottimizza i pesi dai tuoi confronti; applicati solo se superano un test su dati tenuti fuori (vedi nota) |
| `python facet.py --optimize-weights --optimize-force` | Applica i pesi ottimizzati anche se non superano il test |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Addestra solo su queste fonti di confronto |
| `python facet.py --optimize-weights --optimize-category portrait` | Addestra una categoria e scrive il suo blocco v4 `categories[].weights` |
| `python facet.py --auto-tune-categories` | **Solo superadmin** (`--user` in modalità multiutente): segnala la disponibilità delle etichette per categoria (solo report) |
| `python facet.py --sync-label-comparisons` | Ricostruisce le coppie derivate dalle valutazioni (source=rating) da stelle, preferiti e rifiuti |
| `python facet.py --train-ranker` | Addestra il ranker personale e scrive learned_scores se batte l'aggregato |
| `python facet.py --train-ranker --ranker-category portrait` | Addestra il ranker su una categoria |
| `python facet.py --train-ranker --train-ranker-force` | Scrive learned_scores anche se il vincolo di accuratezza non è soddisfatto |
| `python facet.py --train-ranker --user alice` | Addestra sui confronti di quell'utente e scrive i suoi learned_scores (modalità multiutente) |
| `python facet.py --train-keeper` | Addestra il **keeper-ranking head** dalle tue decisioni di selezione (vedi nota) |
| `python facet.py --train-keeper --train-keeper-force` | Conserva la head anche se il suo vincolo non è soddisfatto (rispetta anche `--ranker-category` e `--user`) |
| `python facet.py --report-unreviewed-bursts` | Conta i gruppi di raffica non ancora esaminati (sola lettura) |
| `python facet.py --eval-iqa-srcc` | Riporta quanto ogni metrica IQA/estetica concorda con le tue valutazioni a stelle (SRCC; sola lettura) |
| `python facet.py --evaluate-models SLOT` | Classifica i modelli candidati per uno slot in base alla concordanza con le tue scelte (sola lettura; vedi nota) |
| `python facet.py --mine-insights` | Report su etichette, correlazioni tra metriche, categorie, deriva dei percentili e confronti |
| `python facet.py --mine-insights report.json` | Lo stesso, e scrive il report completo come JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibra i pesi delle categorie rispetto al [dataset AVA](https://github.com/imfing/ava_downloader) (sola lettura; stampa le proposte) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Limita a queste categorie e scrive i pesi in `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Sceglie l'ottimizzatore (`de` = evoluzione differenziale, predefinito; `nelder-mead` = simplesso locale) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Usa anche i tag AVA (`--ava-tags-only` solo per i tag; `--apply-filters` per regolare le soglie dei filtri) |

**`--optimize-weights`** si addestra su tutte le fonti di confronto, pesate per affidabilità. I nuovi pesi vengono applicati solo se battono quelli attuali su confronti tenuti fuori (validazione incrociata a 5 fold, test di McNemar unilaterale, p < 0.05, guadagno di almeno 2 punti percentuali). L'applicazione ricentra anche il `modifiers.bonus` della categoria, così le sue foto vengono riordinate invece di salire o scendere tutte insieme. Vedi [SCORING.md](SCORING.md).

**`--train-keeper`** apprende dalle coppie `source='culling'` e viene conservato solo se batte l'euristica della selezione automatica su dati tenuti fuori. Alimenta le scelte della selezione automatica e il badge "esiste una foto migliore in questo gruppo". Finché non ci sono abbastanza coppie di selezione, si usa l'euristica. Si riaddestra con lo stesso innesco di `--train-ranker`.

**`--evaluate-models SLOT`** slot: `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` sceglie i candidati (`stored:<colonna>` o un nome registrato).
- `--eval-out PATH` imposta l'output (predefinito `.facet_cache/eval/<slot>-<timestamp>.json`).
- Gli slot dei volti confrontano con i volti InsightFace memorizzati invece che con le tue scelte, quindi valgono solo per librerie in modalità predefinita: `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<soglia>`), `faces-centroid` (regola il `merge_threshold` di SFace / l'unione automatica), `blink` (fa variare la soglia permissiva degli occhi chiusi).
- `--limit N` limita le foto (predefinito 600) o i volti di riferimento (predefinito 1200).

## Configurazione

`scoring_config.json` è un **override**: contiene solo le impostazioni che hai cambiato, sopra `config/scoring_config.default.json`. Senza file di configurazione, Facet usa i valori predefiniti. Vedi [Configurazione](CONFIGURATION.md#valori-predefiniti-e-il-tuo-override).

Quale file viene letto:

1. `--config` prevale sempre.
2. Altrimenti `FACET_CONFIG`, se impostata. Vale per `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` e `viewer.py`. `viewer.py` non ha `--config`, quindi questo è il suo unico override.
3. Altrimenti, per gli strumenti CLI (non `viewer.py`), un `scoring_config.json` nella **directory di lavoro**, così una libreria può portare con sé la propria configurazione.
4. Altrimenti il file accanto all'installazione. Se manca, si applicano i valori predefiniti forniti.

Un percorso indicato da `--config` o `FACET_CONFIG` che non esiste è un errore, non "usa i valori predefiniti". Il visualizzatore registra il percorso mancante e rifiuta di avviarsi in modalità aperta.

> **Avviso:** `viewer.py` non legge mai un `scoring_config.json` dalla directory da cui lo avvii. Se lo avvii da una libreria e la radice dell'installazione non ha una configurazione, gira con i valori predefiniti: un `viewer.edition_password` vuoto e nessuna password del visualizzatore, quindi chiunque può navigare.

```bash
# 1. --config prevale su tutto. Un file mancante è un errore.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG fornisce il valore predefinito se --config è omesso (Docker lo imposta).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # legge /config/scoring_config.json
python facet.py --config other.json /photos   # --config prevale comunque

# 3. Nessuno dei due: una configurazione nella DIRECTORY DI LAVORO prevale per gli strumenti CLI.
cd /photos/client-shoot          # contiene il proprio scoring_config.json
python /opt/facet/facet.py .     # valutato con /photos/client-shoot/scoring_config.json

# 4. Nessuno dei due e nulla qui: ripiego sulla configurazione accanto all'installazione.
cd /tmp
python /opt/facet/facet.py /photos   # legge /opt/facet/scoring_config.json
                                     # assente = si usano i valori predefiniti forniti

# 5. viewer.py non esegue mai il passaggio della directory di lavoro.
cd /photos/client-shoot          # contiene il proprio scoring_config.json -- qui è irrilevante
python /opt/facet/viewer.py      # legge comunque /opt/facet/scoring_config.json (o $FACET_CONFIG)
```

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --validate-categories` | Valida le configurazioni delle categorie |

## Tagging

| Comando | Descrizione |
|---------|-------------|
| `python tag_existing.py` | Assegna i tag alle foto senza tag dagli embedding CLIP memorizzati |
| `python tag_existing.py --dry-run` | Visualizza in anteprima i tag senza salvare |
| `python tag_existing.py --threshold 0.25` | Soglia di somiglianza personalizzata (predefinita: il `tag_threshold_percent` del profilo, fornito come 8, cioè 0.08) |
| `python tag_existing.py --max-tags 3` | Limita i tag per foto (predefinito: 5) |
| `python tag_existing.py --force` | Riassegna i tag a tutte le foto |
| `python tag_existing.py --db custom.db` | Usa un database personalizzato |
| `python tag_existing.py --config my.json` | Usa una configurazione personalizzata |

Su CUDA, i profili SigLIP (`16gb`, `24gb`) ora codificano il vocabolario dei tag in fp16, il che cambia i tag di alcune foto. Esegui `python tag_existing.py --force` per riassegnare i tag alle foto etichettate in precedenza. CPU e profili `legacy`/`8gb` restano invariati.

Il passaggio di tagging al termine di una scansione viene saltato quando `tagging.enabled` è `false` o nessuna foto è in attesa di tag.

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
| `python database.py` | Inizializza o aggiorna lo schema e costruisce gli indici mancanti (vedi nota) |
| `python database.py --info` | Mostra le informazioni sullo schema |
| `python database.py --migrate-tags` | Configurazione una tantum della tabella di ricerca dei tag (filtri sui tag 10-50 volte più veloci) |
| `python database.py --rebuild-fts` | Ricostruisce l'indice di ricerca full-text da didascalie e tag |
| `python database.py --populate-vec` | Riempie la tabella di ricerca vettoriale sqlite-vec dagli embedding |
| `python database.py --refresh-stats` | Aggiorna la cache delle statistiche |
| `python database.py --compact-config` | Elimina da `scoring_config.json` ogni valore uguale al predefinito fornito (prende prima un backup in `0600`) |
| `python database.py --stats-info` | Mostra lo stato e l'età della cache |
| `python database.py --vacuum` | Recupera spazio, deframmenta |
| `python database.py --analyze` | Aggiorna le statistiche del pianificatore di query |
| `python database.py --optimize` | Esegue VACUUM e ANALYZE |
| `python database.py --backup` | Scrive uno snapshot con data e ora, sicuro per il WAL (ne conserva `--keep N`, predefinito 3) |
| `python database.py --export-viewer-db` | Esporta un database leggero per il visualizzatore (senza BLOB, miniature più piccole; incrementale) |
| `python database.py --export-viewer-db --force-export` | Forza una riesportazione completa |
| `python database.py --cleanup-orphaned-persons` | Rimuove le persone senza volti |
| `python database.py --cleanup-missing-photos` | Rimuove le foto non più presenti su disco, con i loro tag, volti e voci degli album |
| `python database.py --cleanup-missing-photos --dry-run` | Elenca i file mancanti senza eliminare |
| `python database.py --cleanup-missing-photos --force` | Procede anche quando ogni foto sembra mancante (vedi avviso) |
| `python database.py --relink-photos` | Aggiorna i percorsi delle foto che hai spostato tu (anteprima predefinita). Vedi [Ricollegare foto spostate](#ricollegare-foto-spostate) |
| `python database.py --migrate-storage-fs` | Sposta miniature ed embedding dal database al filesystem |
| `python database.py --migrate-storage-db` | Sposta miniature ed embedding dal filesystem di nuovo al database |
| `python database.py --add-user alice --role admin` | Aggiunge un utente (richiede la password) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Aggiunge un utente con nome visualizzato |
| `python database.py --migrate-user-preferences --user alice` | Copia le valutazioni da photos a user_preferences |

**`python database.py`** costruisce anche gli indici mancanti della galleria (vedi [VIEWER.md](VIEWER.md#indici-della-galleria-e-cache-dei-conteggi)). Su una libreria grande, eseguilo una volta prima di avviare il visualizzatore; può richiedere circa un minuto. Altrimenti il visualizzatore li costruisce in background e nel frattempo rifiuta i salvataggi.

**`--migrate-tags`** serve una sola volta. Dopo, scansioni, `--recompute-tags`, `--recompute-tags-vlm` e `tag_existing.py` mantengono la tabella aggiornata. Finché non è popolata, i filtri sui tag usano una ricerca `LIKE` più lenta.

**`--cleanup-missing-photos`** svuota anche l'indice vettoriale e azzera i contatori dei confronti del riaddestramento automatico. Lo stato della libreria, come i modelli addestrati, lo stato di sincronizzazione Immich e lo snapshot dei percentili, viene conservato.

> **Avviso:** senza `--force`, `--cleanup-missing-photos` si ferma quando ogni foto risulta mancante, il che di solito significa che un volume non è montato. Controlla il mount prima di aggiungere `--force`.

**Suggerimento sulle prestazioni:** per database di grandi dimensioni (oltre 50k foto), esegui `--migrate-tags`, `--rebuild-fts` e `--populate-vec` una volta, poi `--optimize` di tanto in tanto.

## Visualizzatore web

| Comando | Descrizione |
|---------|-------------|
| `python viewer.py` | Avvia il server su http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Usa una porta diversa (o imposta la variabile d'ambiente `PORT`; predefinita 5000) |
| `python viewer.py --host 127.0.0.1` | Associa un'interfaccia specifica (predefinita `0.0.0.0`) |
| `python viewer.py --production` | Modalità produzione (worker uvicorn) |
| `python viewer.py --production --workers 4` | Modalità produzione con N worker (predefinito 1) |

## Selezione da terminale

Selezione automatica senza interfaccia: la versione da terminale della [selezione automatica](VIEWER.md#selezione-automatica) del visualizzatore. I rifiuti vengono scritti nel database. Gli originali non vengono mai spostati né eliminati; `--copy-keepers` copia le foto conservate in una cartella.

| Comando | Descrizione |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Seleziona le foto già nel database sotto `PATH` (cartella o file; nessuno o `all` = intera libreria). **Dry run per impostazione predefinita** |
| `python facet.py /path --auto-cull` | Scansiona `/path`, poi seleziona le foto al suo interno |
| `--apply` | Scrive la selezione: rifiuti, marcature dei gruppi rivisti e coppie di confronto `source='culling'` |
| `--copy-keepers DIR` | Copia in `DIR` ogni foto non rifiutata dell'ambito, con i file collegati RAW / `.xmp` dallo stesso nome |
| `--cull-strictness N` | Budget di foto conservate 0–100, più alto = meno foto conservate per gruppo (predefinito: `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Numero minimo di foto conservate per gruppo (predefinito `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Quali gruppi selezionare (predefinito `all`) |
| `--cull-min-score X` | Rifiuta anche le foto singole con punteggio aggregato inferiore a `X` |
| `--cull-trim-brackets` | Rifiuta anche gli scatti ridondanti dei bracketing di esposizione (il `trim_brackets` del visualizzatore) |
| `--user NAME` | Di chi usare valutazioni e rifiuti; **obbligatorio** in un'installazione multiutente |

- **Dry run.** Senza `--apply` non viene scritto nulla e la cartella di `--copy-keepers` non viene creata. Il riepilogo elenca `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` e, con `--copy-keepers`, `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` in un dry run). `--dry-run` stesso è rifiutato. Se un modello di foto da conservare addestrato ha i pesi da correggere, il suo caricamento può comunque riscrivere `scoring_config.json`.
- **Scansione poi selezione** scansiona sempre davvero; la selezione parte solo se la scansione è terminata. Non si può combinare con `--auto-cull PATH`, `--resume`, `--retry-failed` o `--watch`.
- **Regole.** Come nella [selezione automatica del visualizzatore](VIEWER.md#selezione-automatica): ogni gruppo conserva la sua foto migliore più tutto ciò che rientra nel margine di rigore, almeno `--cull-min-keep`. Bracketing, panorami e panorami HDR restano interi. `--apply` segna le foto conservate come **Conserva** e registra le coppie di confronto come `POST /api/culling/auto`; nessun album Highlights viene riempito.
- **Configurazione.** Le impostazioni [`auto_cull`](CONFIGURATION.md#auto-cull), `burst_scoring` e `similarity_groups` provengono dalla configurazione del **server** (`FACET_CONFIG` o il percorso predefinito), non da `--config`. Se i due divergono sulla modalità multiutente, il comando termina con codice 1.
- **Ambito.** L'ambito confronta i percorsi reali locali, quindi le righe salvate prima dell'impostazione di un `path_mapping` non possono essere limitate per cartella: usa `all` o ripeti la scansione. Una raffica, un bracketing o un panorama in parte fuori ambito viene saltato per intero (`spanning_skipped`). I gruppi di simili e di scene sono calcolati dentro l'ambito.
- **`--cull-min-score`** (solo CLI) non rifiuta mai scatti di bracketing o panorama, foto senza punteggio, preferite, valutate o segnate con **Conserva**, né foto già giudicate da una selezione precedente, quindi una seconda esecuzione non rifiuta nulla di nuovo. Risparmia sempre i membri di una raffica. Risparmia i membri di un gruppo di simili quando il raggruppamento li ha trovati (legge le `similarity_groups.max_photos` foto più recenti dell'ambito, predefinito `10000`, e scarta i gruppi oltre `similarity_groups.max_group_size`, predefinito `50`). Risparmia i membri di un gruppo di scene solo con `--cull-group-by scene`.
- **Copia.** Le foto rifiutate e i loro file collegati non vengono mai copiati. I file omonimi di cartelle diverse ricevono il suffisso `_1`; una nuova esecuzione salta i file identici (`already_present`). `DIR` non deve essere, contenere né trovarsi dentro l'ambito, la libreria o qualsiasi cartella che Facet ha scansionato (codice 1, verificato anche in dry run). I file devono trovarsi nell'elenco di cartelle di scansione consentite (`users.*.directories` / `viewer.scan_directories`); se per questo motivo ogni foto viene saltata, il comando termina con codice 3.
- **Utenti.** In un'installazione multiutente `--user` è obbligatorio (codice 1 se manca o se l'utente è sconosciuto). In un'installazione a utente singolo `--user` è ignorato con un avviso e il comando vede tutte le foto anche con una password del visualizzatore impostata. `--apply` prende il blocco della libreria; un dry run no.
- **Errori d'uso (codice 2).** `--apply`, `--copy-keepers` o un `--cull-*` senza `--auto-cull`; `--dry-run`, `--resume`, `--retry-failed` o `--watch` con `--auto-cull`; `--auto-cull PATH` con cartelle posizionali; rigore fuori da 0–100; `--cull-min-keep` inferiore a 1. `--apply` va scritto per intero (non abbrevia più `--apply-recommendations`).
- **Codici di uscita.** `0` successo (dry run e zero gruppi inclusi); `1` errore di prerequisito, configurazione o database; `2` errore d'uso; `75` il blocco della libreria è tenuto da un altro lavoro; `3` la selezione è riuscita ma la copia ha avuto errori o non ha copiato nulla (anche un dry run in cui ogni foto da conservare verrebbe saltata termina con `3`).
- **Riaddestramento** non viene eseguito dentro la CLI. Il contatore dei confronti persiste, e il riaddestramento parte alla prossima azione nel visualizzatore o con un comando `--train-*`. La prima esecuzione può creare `.facet_secret`.

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

### Selezionare uno shooting da terminale
```bash
python facet.py --auto-cull /photos/wedding                     # Anteprima del piano, nulla viene scritto
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Rifiuta, poi copia le foto conservate
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Scansiona, poi seleziona
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

## Ricollegare foto spostate

Dopo aver spostato i file personalmente, `python database.py --relink-photos` mostra un'anteprima delle mappature percorso vecchio → nuovo e conserva i dati di database di ogni foto. L'anteprima è predefinita.

- **Applicare** richiede l'ID del piano salvato e `--acknowledge-unverified-identity`, perché Facet non può provare che il nuovo file sia l'originale. Arresta visualizzatori e scansioni e rivedi prima il piano.
- **Rifiutati:** percorsi fuori dalle radici configurate o dalla visibilità degli utenti, copie, nomi ambigui, piani obsoleti e mappature dei percorsi.
- **File collegati** devono essere elencati esplicitamente; i tipi includono `sidecar_facet` per `photo.ext.facet.xmp`. I rettangoli manuali richiedono la revisione nell'editor. Lo stato Immich non cambia.
- **Piani** vengono salvati privatamente (0600 su POSIX).
- **Mount:** una cartella leggibile non prova che un volume sia montato, quindi `source_mount_status` resta `not_verified`. Conferma che l'originale sia stato spostato e non sia offline.
- **Codici di uscita:** 75 significa che un altro lavoro tiene il blocco della libreria; 1 significa che il blocco è inutilizzabile. L'anteprima non prende alcun blocco.

Vedi [Ricollegare una foto mancante](RELINK.md) per il contratto completo ed esempi.
