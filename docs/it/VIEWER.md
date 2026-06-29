# Galleria web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · **Italiano** · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md)

Applicazione a pagina singola FastAPI + Angular per sfogliare, filtrare e gestire le foto.

## Contenuti

- [Avvio della galleria](#avvio-della-galleria) · [Autenticazione](#autenticazione) · [Opzioni di filtraggio](#opzioni-di-filtraggio) · [Ordinamento](#ordinamento) · [Funzionalità della galleria](#funzionalità-della-galleria)
- [Gestione delle persone](#gestione-delle-persone) · [Avvio scansione (Superadmin)](#avvio-scansione-superadmin) · [Ricerca semantica](#ricerca-semantica) · [Album](#album)
- [Critica IA](#critica-ia) · [Didascalie IA](#didascalie-ia-gpu-16gb24gb-edition) · [Ricordi ("In questo giorno")](#ricordi-in-questo-giorno) · [Vista cronologia](#vista-cronologia) · [Vista mappa](#vista-mappa) · [Capsule](#capsule)
- [Vista cartelle](#vista-cartelle) · [Finestra filtro GPS](#finestra-filtro-gps) · [Suggerimenti di unione](#suggerimenti-di-unione) · [Esportazione per editor](#esportazione-per-editor) · [Selezione](#selezione) · [Modalità di confronto a coppie](#modalità-di-confronto-a-coppie)
- [Statistiche EXIF](#statistiche-exif) · [Scorciatoie da tastiera](#scorciatoie-da-tastiera-galleria) · [Annulla](#annulla) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile)
- [Configurazione](#configurazione) · [Prestazioni](#prestazioni) · [Endpoint API](#endpoint-api) · [Risoluzione dei problemi](#risoluzione-dei-problemi)

> **I requisiti delle funzionalità** sono indicati in linea: `[GPU]` · `[16gb/24gb]` (profilo VRAM) · `[Edition]` (password di modifica) · `[Superadmin]`. Vedi la [matrice delle funzionalità](../README.md#feature-availability--requirements).

## Avvio della galleria

### Produzione

```bash
python viewer.py
# Apri http://localhost:5000
```

Questo serve sia l'API sia l'applicazione Angular pre-compilata su un'unica porta.

Per un throughput maggiore, esegui in modalità di produzione (Uvicorn, senza ricaricamento automatico). Aggiungi `--workers N` per scalare (predefinito 1):

```bash
python viewer.py --production --workers 4
```

### Sviluppo

Esegui separatamente il server API e il dev server Angular:

```bash
# Terminale 1: server API
python viewer.py
# API disponibile su http://localhost:5000

# Terminale 2: server di sviluppo Angular con hot reload
cd client && npx ng serve
# Apri http://localhost:4200 (inoltra le chiamate API a :5000)
```

## Autenticazione

### Modalità utente singolo (predefinita)

Protezione facoltativa con password tramite configurazione:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando impostata, gli utenti devono autenticarsi prima di accedere alla galleria. Una `edition_password` facoltativa garantisce l'accesso alla gestione delle persone e alla modalità di confronto.

### Modalità multiutente

Per scenari di NAS familiari in cui ogni membro ha directory di foto private. Si abilita aggiungendo una sezione `users` a `scoring_config.json`:

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

Gli utenti vengono creati solo tramite CLI (nessuna interfaccia di registrazione):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Vedi [Configurazione](CONFIGURATION.md#users) per il riferimento completo.

### Ruoli

| Ruolo | Visualizza propri + condivise | Valuta/preferisci | Gestisci persone/volti | Avvia scansioni |
|------|:-:|:-:|:-:|:-:|
| `user` | sì | sì | no | no |
| `admin` | sì | sì | sì | no |
| `superadmin` | sì | sì | sì | sì |

### Visibilità delle foto

Ogni utente vede le foto delle proprie directory configurate più le directory condivise. La visibilità è applicata su tutti gli endpoint: galleria, miniature, download, statistiche, opzioni di filtro e pagine delle persone.

### Valutazioni per utente

In modalità multiutente, le valutazioni a stelle, i preferiti e i contrassegni di scarto sono memorizzati per utente nella tabella `user_preferences`. Ogni utente valuta in modo indipendente: i preferiti di Alice non influenzano la vista di Bob.

Per migrare le valutazioni esistenti di un utente singolo:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opzioni di filtraggio

<details><summary>Barra laterale dei filtri completa — ogni sezione espansa (clicca per visualizzare)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Barra laterale dei filtri con ogni sezione espansa" width="360"></p>
</details>

### Filtri primari

| Filtro | Opzioni |
|--------|---------|
| **Tipo di foto** | Migliori scelte, Ritratti, Persone nella scena, Paesaggi, Architettura, Natura, Animali, Arte e statue, Bianco e nero, Bassa luminosità, Silhouette, Macro, Astrofotografia, Street, Lunga esposizione, Aereo e drone, Concerti |
| **Livello di qualità** | Buono (6+), Ottimo (7+), Eccellente (8+), Migliore (9+) |
| **Fotocamera e obiettivo** | Filtraggio in base all'attrezzatura |
| **Persona** | Filtra per persona riconosciuta |
| **Categoria** | Filtra per categoria di foto |

### Filtri avanzati

| Categoria | Filtri |
|----------|---------|
| **Data** | Data di inizio e di fine |
| **Punteggi** | Aggregato, estetica, punteggio TOPIQ, punteggio qualità |
| **Qualità estesa** | Estetica IAA (merito artistico), Qualità volto IQA, punteggio LIQE |
| **Metriche volti** | Qualità volto, nitidezza occhi, nitidezza volto, rapporto volto, confidenza volto, numero di volti |
| **Composizione** | Punteggio composizione, punti di forza, linee guida, isolamento, modello compositivo |
| **Salienza del soggetto** | Nitidezza soggetto, prominenza soggetto, posizionamento soggetto, separazione sfondo |
| **Tecnica** | Nitidezza, contrasto, gamma dinamica, livello di rumore |
| **Colore** | Punteggio colore, saturazione, luminanza, ampiezza istogramma; temperatura colore (caldo/freddo/neutro) e gruppo di tonalità (richiede `--recompute-colors`) |
| **Esposizione** | Punteggio esposizione |
| **Valutazioni utente** | Valutazione a stelle |
| **Impostazioni fotocamera** | ISO, apertura (cursore di intervallo f-stop), lunghezza focale (cursore di intervallo) |
| **Contenuto** | Tag, interruttore monocromatico |

### Modelli compositivi

Filtra per modelli rilevati da SAMP-Net:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Ordinamento

Colonne ordinabili raggruppate per categoria (da `viewer.sort_options`):

| Gruppo | Colonne |
|-------|---------|
| **Generale** | Punteggio aggregato, Estetica, Punteggio qualità, Data di scatto, Valutazione a stelle, Estetica (IAA), Punteggio LIQE |
| **Metriche volti** | Qualità volto, Qualità volto (IQA), Nitidezza occhi, Nitidezza volto, Rapporto volto, Numero di volti |
| **Tecnica** | Nitidezza tecnica, Contrasto, Livello di rumore |
| **Colore** | Punteggio colore, Saturazione |
| **Esposizione** | Punteggio esposizione, Luminanza media, Ampiezza istogramma, Gamma dinamica |
| **Composizione** | Punteggio composizione, Punteggio punti di forza, Linee guida, Bonus isolamento, Modello compositivo |
| **Salienza del soggetto** | Nitidezza soggetto, Prominenza soggetto, Posizionamento soggetto, Separazione sfondo |

### I miei gusti

Un'opzione di ordinamento di prima classe, basata sul `learned_score` del ranker personale (rinominata da "Scelte per te"). Ordina le foto in base a ciò che il ranker ha appreso dai tuoi confronti A/B, dalle valutazioni e dalle decisioni di selezione. Un badge di confidenza accanto all'ordinamento mostra la copertura appresa (% di foto con un punteggio appreso) e l'accuratezza del ranker su dati di validazione, così da poter giudicare quanto fidarsi dell'ordinamento. Addestra o aggiorna il ranker con `python facet.py --train-ranker`.

Controllato da `viewer.features.show_my_taste` (predefinito: `true`). Lo stato del ranker è esposto tramite `GET /api/ranker/status`.

## Funzionalità della galleria

### Schede foto

- Miniatura con badge del punteggio
- Tag cliccabili per un filtraggio rapido
- Avatar delle persone per i volti riconosciuti
- Badge della categoria

### Selezione multipla e azioni di gruppo

- Clicca sulle foto per selezionarle, Maiusc+Clic per la selezione di un intervallo
- Compare una barra delle azioni con il conteggio della selezione e le azioni disponibili
- **Preferito** — Contrassegna tutte le selezionate come preferite (rimuove lo scarto)
- **Rifiuta** — Contrassegna tutte le selezionate come scartate (rimuove preferito e valutazione)
- **Valuta** — Imposta la valutazione a stelle (1–5) per tutte le selezionate, o azzera la valutazione
- **Aggiungi all'album** — Aggiungi le selezionate a un album esistente o nuovo
- **Copia nomi file** — Copia i nomi dei file selezionati negli appunti
- **Esporta** — Scrivi i sidecar XMP (valutazione/preferito/scarto) accanto ai file selezionati (vedi [Esportazione per editor](#esportazione-per-editor))
- **Scarica** — Scarica le foto selezionate
- Annulla la selezione con Esc o con il pulsante Cancella

Le azioni di gruppo richiedono la modalità di modifica. Fai doppio clic su una foto qualsiasi per scaricarla direttamente.

### Opzioni di visualizzazione

- **Modalità layout** - Passa tra **Griglia** (schede uniformi) e **Mosaico** (righe giustificate che preservano le proporzioni). Il mosaico è solo per desktop; su mobile si usa sempre la griglia.
- **Dimensione miniatura** - Cursore per regolare l'altezza delle schede/righe (120–400px, salvato in localStorage)
- **Nascondi dettagli** - Nascondi i metadati delle foto sulle schede (solo modalità griglia)
- **Nascondi tooltip** - Disabilita il tooltip al passaggio del mouse che mostra i dettagli della foto su desktop
- **Nascondi occhi chiusi** - Filtra le foto con battiti di ciglia rilevati
- **Migliore della raffica** - Mostra solo la foto con il punteggio più alto di ogni raffica
- **Scorrimento infinito** - Le foto si caricano man mano che scorri
- **Scorrimento rapido (virtualizzato)** - Rendering a finestra di righe: solo le righe
  vicine al viewport sono nel DOM, così lo scorrimento profondo attraverso decine di
  migliaia di foto rimane reattivo. Attivo per impostazione predefinita; disabilitalo
  nella sezione Visualizzazione della barra laterale dei filtri se riscontri problemi
  di layout (la modalità griglia con dettagli visibili usa sempre il rendering completo,
  poiché le altezze delle righe non sono deterministiche in quel caso). Salvato in
  localStorage (`facet_virtual_scroll`).

### Foto simili

Clicca il pulsante "Simili" su una foto qualsiasi per scegliere una modalità di somiglianza:

- **Visivo** (predefinito) — distanza di Hamming pHash (70%) + somiglianza coseno CLIP/SigLIP (30%). Ricade su CLIP soltanto quando non è disponibile alcun pHash.
- **Colore** — Intersezione istogramma (70%) + distanza di saturazione (10%) + distanza di luminanza (10%) + bonus monocromatico (10%). Pre-filtra in base al flag monocromatico e all'intervallo di saturazione.
- **Persona** — Trova le foto contenenti le stesse persone. Usa `person_id` quando disponibile (veloce), altrimenti ricade sulla somiglianza coseno degli embedding dei volti.

Usa il **cursore della soglia di somiglianza** (0–90%) per controllare quanto è rigida la corrispondenza (non mostrato in modalità persona). Il pannello supporta lo scorrimento infinito per insiemi di risultati di grandi dimensioni.

### Chip dei filtri

I filtri attivi sono mostrati come chip rimovibili con i relativi conteggi in cima alla galleria.

## Gestione delle persone

> La consultazione delle persone è aperta a tutti i visualizzatori; rinominare, unire, cambiare gli avatar e assegnare i volti richiede `[Edition]`.

### Filtro persona

Il menu a tendina mostra le persone con le miniature dei volti. Clicca per filtrare la galleria.

### Galleria della persona

Clicca sul nome di una persona per visualizzare tutte le sue foto in `/person/<id>`.

### Pagina Gestisci persone

Accessibile tramite il pulsante nell'intestazione o `/persons`:

| Azione | Come fare |
|--------|--------|
| **Unisci** | Seleziona la persona di origine, clicca quella di destinazione, conferma |
| **Elimina** | Clicca il pulsante di eliminazione sulla scheda della persona |
| **Rinomina** | Clicca sul nome della persona per modificarlo in linea |
| **Dividi** | Apri i volti di una persona, seleziona un sottoinsieme, dividili in una nuova persona |
| **Nascondi** | Nascondi un cluster dall'elenco delle persone, dai filtri e dai suggerimenti di unione (reversibile) |

## Avvio scansione (Superadmin)

Quando `viewer.features.show_scan_button` è `true` e l'utente ha il ruolo `superadmin`, nello stato di galleria vuota compare un pulsante **Scansiona le foto per iniziare**. Viene fornito impostato su **`false`** in `scoring_config.json` (opt-in per il superadmin). Il pulsante apre la finestra di avvio della scansione (`ScanLauncherComponent`).

- Scegli una directory dall'elenco del launcher e avvia la scansione direttamente nell'app
- Il launcher trasmette l'avanzamento in tempo reale (SSE con fallback automatico al polling) in una `mat-progress-bar` pilotata dal campo strutturato `progress`, oltre a una coda di righe di output, e aggiorna la galleria al termine della scansione
- La scansione viene eseguita come sottoprocesso in background (`facet.py`); una sola scansione alla volta (blocco globale)
- Le scelte di directory provengono da `get_all_scan_directories()`, che unisce le `directories` di ciascun utente, le directory condivise, le destinazioni di `path_mapping` e l'elenco autonomo `viewer.scan_directories` — popola quest'ultimo (ad es. `/data/photos`) affinché le installazioni a utente singolo / Docker abbiano una destinazione selezionabile

Questo è utile quando la galleria viene eseguita sulla stessa macchina che ha accesso alla GPU per la valutazione.

## Ricerca semantica

Ricerca ibrida che combina la somiglianza degli embedding CLIP/SigLIP (70%) con la corrispondenza testuale FTS5 BM25 su didascalie e tag (30%). Digita una query come "tramonto sulle montagne" o "bambino che gioca nella neve" e la galleria restituisce le foto corrispondenti ordinate per punteggio combinato.

- Richiede i dati `clip_embedding` memorizzati (calcolati durante la valutazione)
- Usa sqlite-vec per la ricerca vettoriale KNN quando installato, ricade su NumPy in memoria
- La ricerca testuale FTS5 su didascalie/tag IA fornisce una corrispondenza per parole chiave aggiuntiva (esegui `database.py --rebuild-fts` per abilitarla)
- Usa lo stesso modello di embedding del profilo VRAM attivo (SigLIP 2 per 16gb/24gb, CLIP ViT-L-14 per legacy/8gb)
- `scope=text` limita la query alle corrispondenze FTS5 letterali nel testo OCR/didascalia e salta la ricerca tramite embedding
- Controllato da `viewer.features.show_semantic_search` (predefinito: `true`)

## Album

Organizza le foto in album denominati. Accessibile tramite la rotta `/albums`.

### Album manuali

Crea album e aggiungi foto dalla galleria usando la selezione multipla. Gli album supportano:
- Nome e descrizione
- Foto di copertina personalizzata
- Ordinamento personalizzato
- Consultazione del contenuto dell'album in `/album/:albumId`

### Album intelligenti

Salva una combinazione di filtri (fotocamera, tag, persona, intervallo di date, soglie di punteggio, ecc.) come album intelligente. Gli album intelligenti si aggiornano dinamicamente man mano che nuove foto corrispondono ai criteri di filtro salvati. La combinazione di filtri è memorizzata come JSON in `smart_filter_json`.

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Controllato da `viewer.features.show_albums` (predefinito: `true`).

### Condivisione foto

Condividi gli album con utenti esterni tramite collegamenti con token. Non è richiesta alcuna autenticazione per visualizzare gli album condivisi.

| Azione | Come fare |
|--------|--------|
| **Condividi** | Apri l'album, clicca il pulsante "Condividi" per generare un collegamento condivisibile |
| **Revoca** | Clicca "Annulla condivisione" per invalidare il token di condivisione |
| **Visualizza** | I destinatari aprono il collegamento per sfogliare l'album condiviso in `/shared/album/:id` |

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

## Critica IA

Scompone i punteggi di una foto in punti di forza, punti deboli e suggerimenti.

### Critica basata su regole

Disponibile su tutti i profili VRAM. Analizza le metriche memorizzate (estetica, composizione, nitidezza, qualità volto, ecc.) e genera una spiegazione strutturata del punteggio.

### Critica VLM `[GPU]` `[16gb/24gb]`

Usa il VLM configurato (Qwen3.5-2B o Qwen3.5-4B) per una critica consapevole del contesto. Richiede il profilo VRAM 16gb o 24gb e `viewer.features.show_vlm_critique: true`.

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Controllato da `viewer.features.show_critique` (predefinito: `true`) e `viewer.features.show_vlm_critique` (predefinito: `true`).

**Overlay visivo "perché questo punteggio".** Quando `viewer.features.show_saliency_overlay` è `true` (predefinito), la finestra di critica acquisisce un interruttore **Mostra overlay**: disegna la mappa di salienza BiRefNet come heatmap traslucida sopra la foto (ricalcolata su richiesta dalla miniatura memorizzata — `GET /api/saliency_overlay`), oltre a riquadri soft per volto e marcatori degli occhi ricostruiti dai landmark memorizzati (`GET /api/photo/face_markers`). I riquadri sono verdi quando gli occhi sono aperti, ambra in caso di occhi chiusi. La heatmap è illustrativa (risoluzione della miniatura), non esatta a livello di pixel; l'interruttore si nasconde sui profili in cui non è producibile alcuna maschera di salienza.

## Didascalie IA `[GPU]` `[16gb/24gb]` `[Edition]`

Ottieni una didascalia in linguaggio naturale generata dall'IA per qualsiasi foto. Le didascalie vengono generate alla prima richiesta e memorizzate nella cache nella colonna `caption` del database. Le didascalie possono essere modificate manualmente in modalità di modifica tramite la pagina di dettaglio della foto. (La *traduzione* delle didascalie viene eseguita su CPU — vedi sotto.)

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Disponibile anche tramite CLI per la generazione e la traduzione di massa:

```bash
python facet.py --generate-captions      # Genera didascalie per tutte le foto senza didascalia
python facet.py --translate-captions     # Traduci le didascalie nella lingua di destinazione configurata
```

La traduzione delle didascalie usa MarianMT (CPU, nessuna GPU richiesta). Configura la lingua di destinazione in `scoring_config.json` sotto `translation.target_language` (predefinito: `"fr"`). Lingue supportate: francese, tedesco, spagnolo, italiano.

Controllato da `viewer.features.show_captions` (predefinito: `true`). Richiede il profilo VRAM 16gb o 24gb per le didascalie basate su VLM.

## Ricordi ("In questo giorno")

Sfoglia le foto scattate nella stessa data di calendario negli anni precedenti. Una finestra dei ricordi mostra una retrospettiva anno per anno delle foto corrispondenti.

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Controllato da `viewer.features.show_memories` (predefinito: `true`).

## Flussi di lavoro comuni

- **Selezionare una vacanza** — apri Capsule → cerca la capsula `journey` generata automaticamente per le date del viaggio. Ogni capsula offre un'azione Salva come album.
- **Eseguire una revisione giorno per giorno** — apri Cronologia → ordina per aggregato → scorri attraverso l'anno. Gli scatti migliori emergono per primi quando hai abilitato `hide_bursts` e `hide_duplicates` (predefiniti: attivi).
- **Mostrare ciò che è nascosto** — la galleria nasconde per impostazione predefinita i battiti di ciglia / le raffiche non principali / i duplicati non principali. Quando almeno uno di questi filtri è attivo ed escluderebbe delle righe, sopra la griglia compare un banner "N foto nascoste dai filtri attivi · Mostra tutte".

## Vista cronologia

Browser di foto cronologico con navigazione basata sulle date. Scorri tra le foto organizzate per data con una barra laterale che mostra gli anni e i mesi disponibili.

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Accessibile tramite la rotta `/timeline`. Controllato da `viewer.features.show_timeline` (predefinito: `true`).

## Vista mappa

Visualizza le foto su una mappa interattiva in base alle coordinate GPS estratte dai dati EXIF. Usa Leaflet per il rendering della mappa con clustering a diversi livelli di zoom.

### Configurazione

Estrai le coordinate GPS dalle foto esistenti:

```bash
python facet.py --extract-gps    # Estrai lat/lng GPS da EXIF nel database
```

Le coordinate GPS vengono estratte automaticamente anche durante la valutazione delle nuove foto.

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Accessibile tramite la rotta `/map`. Controllato da `viewer.features.show_map` (predefinito: `true`).

## Capsule

Diaporama di foto curati (presentazioni) raggruppati per tema. Accessibile tramite la rotta `/capsules`.

### Tipi di capsula

Le capsule vengono generate automaticamente dalla tua libreria usando più algoritmi:

- **Viaggio** — viaggi rilevati tramite clustering GPS, con nomi delle destinazioni ottenuti tramite geocodifica inversa ("Viaggio a Roma — Marzo 2025")
- **Momenti con [Persona]** — le migliori foto di ogni persona riconosciuta
- **Tavolozza stagionale** — foto raggruppate per stagione + anno
- **Collezione d'oro** — il primo 1% per punteggio aggregato
- **Storia di colori** — gruppi visivamente simili tramite clustering degli embedding CLIP
- **Questa settimana, anni fa** — "In questo giorno" esteso su ±3 giorni
- **Posizione** — cluster di foto geolocalizzate con nomi di luoghi
- **Preferiti** — foto preferite raggruppate per anno e stagione
- **Basate su dimensione** — generate automaticamente da fotocamera, obiettivo, categoria, modello compositivo, intervallo di lunghezza focale, ora del giorno, valutazione a stelle e combinazioni intersezionali

### Presentazione

Clicca su una scheda di capsula qualsiasi per avviare una presentazione. Caratteristiche:
- **Transizioni a tema** — slide (viaggi), zoom (ritratti), kenburns (oro/stagionale), crossfade (predefinito)
- **Concatenamento automatico** — quando una capsula termina, una scheda di transizione mostra la capsula successiva prima di continuare
- **Mescola e riprendi** — le foto vengono mescolate per varietà; la posizione di ripresa è tracciata per ogni capsula
- **Raggruppamento adattivo** — le foto in formato verticale vengono raggruppate affiancate in base alle proporzioni del viewport
- **Salva come album** — salva qualsiasi capsula come album permanente

### Aggiornamento

Le capsule ruotano secondo una pianificazione configurabile (predefinito: 24 ore). Le foto di copertina e le capsule di scoperta seminate si allineano allo stesso periodo di rotazione. Il pulsante "Rigenera" nell'intestazione forza un aggiornamento immediato.

### Geocodifica inversa

Le capsule di posizione e di viaggio mostrano i nomi dei luoghi (ad es. "Parigi, Francia") invece delle coordinate. Questo usa la geocodifica offline tramite il pacchetto `reverse_geocoder` — non sono necessarie chiamate API. I risultati vengono memorizzati nella cache del database.

Installazione: `pip install reverse_geocoder`

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

### Configurazione

Vedi [Configurazione — Capsule](CONFIGURATION.md#capsules) per tutte le impostazioni.

## Vista cartelle

Sfoglia la tua libreria di foto in base alla struttura delle directory. Accessibile tramite la rotta `/folders`.

- Navigazione tramite breadcrumb per risalire l'albero delle directory
- Ogni cartella mostra una foto di copertina (l'immagine con il punteggio più alto in quella directory)
- Clicca su una cartella per entrarvi, oppure clicca su una foto per aprirla nella galleria
- Rispetta la visibilità delle directory multiutente in modalità multiutente

## Finestra filtro GPS

Filtra le foto per posizione geografica usando un selettore di mappa interattivo:

- Clicca il pulsante del filtro di posizione per aprire la finestra della mappa
- Clicca o trascina sulla mappa per impostare un punto centrale
- Regola il cursore del raggio per controllare l'area di ricerca
- Le foto entro il raggio selezionato vengono filtrate nella galleria
- Richiede le coordinate GPS (esegui `--extract-gps` se le foto hanno dati GPS EXIF)

## Suggerimenti di unione

Trova cluster di persone che potrebbero essere lo stesso individuo. Accessibile tramite `/merge-suggestions` o dalla pagina Gestisci persone.

- **Cursore della soglia di somiglianza** — quanto due persone devono assomigliarsi per essere suggerite (più basso = più suggerimenti, più alto = meno)
- **Unisci** — accetta un suggerimento per unire le due persone
- **Unione di gruppo** — seleziona più suggerimenti e uniscili in una sola volta
- I suggerimenti ignorati vengono ricordati e non riproposti
- Disponibile anche tramite CLI: `python facet.py --suggest-person-merges`

## Esportazione per editor

Scrivi su disco le tue valutazioni, preferiti e scarti come sidecar XMP, così che gli editor esterni (darktable, Lightroom) li rilevino. Richiede la modalità di modifica.

- **Dalla galleria** — seleziona le foto, quindi **Azioni → Esporta** scrive un sidecar accanto a ogni file.
- **Da un album** ("paniere") — esporta l'intero album come sidecar, oppure copia/crea collegamenti simbolici dei file in una directory di destinazione.
- **Scrivi metadati nel file** — l'azione "Scrivi metadati nel file" della pagina di dettaglio incorpora la valutazione/le parole chiave direttamente nel file originale (JPEG/HEIC/TIFF/PNG/DNG tramite exiftool) oltre a scrivere il sidecar, così che l'intero ecosistema fotografico le veda. I file RAW proprietari originali non vengono mai modificati. Controllato da `viewer.features.show_embed_metadata` (predefinito: `true`).

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

## Selezione

La pagina di selezione (`/culling`, modalità di modifica) raggruppa gli scatti quasi identici in modo da poter conservare il migliore di ciascuno e scartare il resto. Due fonti di gruppi:

- **Raffica** — foto scattate ravvicinate nel tempo (dal rilevamento delle raffiche).
- **Simile** — foto che si assomigliano indipendentemente da quando sono state scattate, raggruppate per somiglianza degli embedding CLIP/SigLIP. Un cursore di soglia controlla quanto è rigido il raggruppamento.

Per ogni gruppo, scegli quale/quali conservare; la conferma scarta il resto. Le conferme sono differite e possono essere annullate (vedi [Annulla](#annulla)).

**Selezione delimitata.** La camera oscura può essere ristretta a un sottoinsieme tramite parametri di query: `?album=<id>` la limita a un album, e `?from=&to=` (finestra temporale di scatto EXIF, alla base di **Seleziona questa scena**) la limita a una sola scena. Un banner mostra l'ambito attivo con un controllo **Esci dalla scena**; il recupero dei membri della raffica rimane delimitato all'album ma ignora la finestra, così che una raffica a cavallo del confine della scena mostri comunque tutti i suoi fotogrammi.

**Chip I miei gusti.** Ogni conferma registra righe di confronto `source='culling'` che addestrano il ranker personale, così l'intestazione mostra un piccolo chip "I miei gusti · N confronti" che si aggiorna dopo ogni decisione — l'IA impara il tuo occhio mentre selezioni (`GET /api/ranker/status`).

### Lente / zoom con tasto Z

Premi **`Z`** nel lightbox a vista singola per attivare una lente in stile Photo Mechanic (adatta ↔ 2×; zoom con rotellina/`+`/`-` fino all'800%). Oltre la scala di adattamento il riquadro sostituisce la sua miniatura con la sorgente `/image` a piena risoluzione, così puoi giudicare la messa a fuoco critica sui pixel reali senza lasciare la vista. Sulla striscia provini delle Scene, `Z` attiva una lente d'ingrandimento al passaggio del mouse che segue il cursore su una tessera (proveniente dall'immagine a piena risoluzione), con un cursore di zoom regolabile. Le miniature memorizzate si fermano a 640px, perciò la lente è il modo per esaminare i pixel oltre tale limite.

### Badge per volto

Nel lightbox di selezione delle raffiche/foto simili, ogni volto rilevato porta i propri badge — occhi aperti/chiusi, espressione scadente e confidenza di rilevamento — anziché un'unica indicazione di occhi chiusi a livello di foto. Questo rende più facile selezionare le foto di gruppo: puoi vedere a colpo d'occhio quale volto ha gli occhi chiusi o un'espressione debole. I badge vengono recuperati per un intero gruppo in un'unica chiamata batch (`POST /api/culling-group/faces`).

**Confronto sincronizzato (2-up / 4-up).** L'intestazione del lightbox ha i pulsanti Singolo / Confronta 2 / Confronta 4. In modalità di confronto i riquadri condividono un'unica trasformazione di pan/zoom, così lo zoom con la rotellina o il trascinamento su un riquadro qualsiasi sposta tutti gli altri sullo stesso identico ritaglio — il modo per scegliere il fotogramma più nitido di una raffica esaminando davvero i pixel. Il doppio clic alterna adatta ↔ zoom; oltre la scala di adattamento ogni riquadro sostituisce in modo lazy la sua miniatura da 1920px con la sorgente `/image` a piena risoluzione, così l'ingrandimento resta nitido. Nessuna modifica al backend — entrambe le rotte dell'immagine esistono già. (Il pinch tattile non è ancora collegato; sul desktop usa la rotellina.)

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

## Vista Scene

Raggruppa le foto guida delle raffiche in "scene" cronologiche, così da poter selezionare un intero servizio fotografico in ordine narrativo. Le foto vengono suddivise in scene in base agli intervalli temporali di scatto (una nuova scena inizia quando trascorrono più di `scenes.gap_minutes` tra due scatti consecutivi, ampliati adattivamente nei servizi con pochi scatti), e qualsiasi sequenza troppo lunga viene ulteriormente suddivisa affinché un evento ripreso in continuità non collassi in un'unica scena gigantesca. Ogni scena ha un pulsante principale **Seleziona questa scena** che apre la camera oscura di selezione completa delimitata a quella sola scena (rilevamento delle raffiche, indicazioni di occhi chiusi, punteggi di qualità, primi piani dei volti, lente), oltre a una striscia di **Rifiuto rapido**. Accessibile tramite la rotta `/scenes` (icona di navigazione "theaters"); raggiungibile anche per album dalla griglia degli Album.

Quando vengono calcolati i momenti narrativi (più sotto), ogni scena viene inoltre titolata dal suo momento dominante, e `scenes.split_on_moment_change` può ulteriormente suddividere una sequenza lunga in cui il momento cambia.

## Momenti narrativi

Facet etichetta ogni foto con il "momento" di scena/attività che raffigura. Il vocabolario **general** predefinito è agnostico rispetto alla libreria — celebrazioni, pasti, spiaggia, attività acquatiche, montagna, natura e fauna selvatica, paesaggio urbano, monumenti di viaggio, concerti, sport, raduni di gruppo, ritratti, bambini, animali domestici, vita notturna, cerimonie, paesaggi panoramici, neve e inverno, interni domestici, strade e veicoli — oppure `other` (un vocabolario `wedding` è incluso come genere opt-in). Né Narrative Select né AfterShoot fanno questo; raggruppano solo per tempo e somiglianza visiva.

È **zero-shot e completamente locale**, ed è **semantico sulla didascalia**: la didascalia AI di ogni foto viene codificata una sola volta e memorizzata, e il momento è il miglior coseno **max-pooled** di quell'embedding della didascalia rispetto ai prompt testuali di ogni momento (L0) — l'embedding dell'immagine memorizzato è il ripiego quando una foto non ha didascalia. Il segnale della didascalia corrisponde ai momenti in modo ~2,4× più netto rispetto all'immagine grezza. Piccoli prior di volto/tag rompono i quasi-pareggi (L1), poi un passaggio Viterbi **regolarizza lungo la cronologia** affinché una lettura errata isolata venga riportata nella sequenza circostante (L2). Un tie-breaker VLM facoltativo (L3, 16gb/24gb) può rigiudicare i fotogrammi a bassa confidenza. Gli embedding delle didascalie vengono calcolati una sola volta e riutilizzati, quindi rietichettare è un prodotto scalare economico su vettori memorizzati — nessuna decodifica dell'immagine, nessun passaggio del modello per immagine; **viene eseguito automaticamente al termine di ogni scansione** (codificando solo le nuove didascalie). Il primo passaggio completo su una libreria esistente codifica ogni didascalia (GPU consigliata); ri-elabora l'intera libreria con `python facet.py --recompute-moments`.

I momenti emergono come titoli di scena e come filtro della galleria (`GET /api/photos?narrative_moment=beach`, opzioni da `GET /api/filter_options/narrative_moments`). Il vocabolario è guidato dalla configurazione per tipo di evento — vedi [Configurazione — Momenti narrativi](CONFIGURATION.md#narrative-moments) per regolare prompt/soglie o cambiare genere.

- Ogni scena mostra le sue foto guida in ordine di scatto
- Tocca le foto per segnarle per la selezione; la conferma le scarta e alimenta il ranker personale
- Le scene più piccole di `scenes.min_size` vengono omesse; vengono caricate al massimo `scenes.max_photos` foto

API: vedi la sezione [Endpoint API](#endpoint-api) più sotto.

Controllato da `viewer.features.show_scenes` (predefinito: `true`). Vedi [Configurazione — Scene](CONFIGURATION.md#scenes) per `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` e `adaptive_k`.

## Modalità di confronto a coppie

Classifica le foto giudicandole due alla volta. I voti accumulati alimentano la regolazione dei pesi. Accessibile tramite la rotta `/compare` (pulsante Confronta nell'intestazione). Richiede una `edition_password` non vuota (utente singolo) o il ruolo `admin`/`superadmin` (multiutente).

La pagina ha quattro schede:

### Scheda Confronto A/B

Coppie di foto affiancate. Scegli un vincitore, segna un pareggio o salta. Una barra di avanzamento traccia i voti verso 50, con conteggi correnti di vittorie A/vittorie B/pareggi. Un filtro di categoria delimita la sessione, e un menu a tendina di strategia di selezione controlla come vengono scelte le coppie.

| Strategia | Descrizione |
|----------|-------------|
| `uncertainty` | Foto con punteggi simili (più informative) |
| `boundary` | Intervallo di punteggio 6–8 (zona ambigua) |
| `active` | Foto con il minor numero di confronti (assicura la copertura) |
| `random` | Coppie casuali (riferimento) |

**Scorciatoie da tastiera:**

| Tasto | Azione |
|-----|--------|
| `A` | Vince la foto a sinistra |
| `B` | Vince la foto a destra |
| `T` | Pareggio |
| `S` | Salta la coppia |
| `Escape` | Chiudi la finestra di sovrascrittura della categoria |

### Scheda Suggerimenti pesi

Mostra i pesi appresi dai confronti rispetto ai pesi correnti, affiancati, con l'accuratezza del modello prima/dopo. Le prime 10 foto attuali e le prime 10 foto previste dopo il ricalcolo vengono visualizzate in anteprima in colonne adiacenti. **Applica** scrive i pesi suggeriti; **Ricalcola** rivaluta la categoria per applicarli (entrambi richiedono la modalità di modifica).

### Scheda Pesi

Editor manuale dei pesi: un cursore per ogni metrica della categoria selezionata con un'anteprima del punteggio in tempo reale. **Salva** scrive su `scoring_config.json` (con un backup); **Ricalcola punteggi** li applica; **Ripristina** ricarica i pesi memorizzati.

### Scheda Istantanee

Salva i pesi correnti come istantanea denominata e ripristina qualsiasi istantanea precedente.

### Sovrascrittura categoria

Per riassegnare la categoria di una foto dalla vista di confronto: modifica il badge della categoria, seleziona una categoria di destinazione, esegui "Analizza conflitti filtri" per vedere quali filtri la escludono, quindi applica la sovrascrittura.

## Statistiche EXIF

La pagina Statistiche (`/stats`) fornisce analisi su 5 schede. Usa i selettori **categoria** e **intervallo di date** nella barra degli strumenti per filtrare tutti i grafici su un sottoinsieme specifico della tua libreria.

### Schede

| Scheda | Descrizione |
|-----|-------------|
| **Attrezzatura** | Corpi macchina, obiettivi e combinazioni (top 20 ciascuno) |
| **Impostazioni di scatto** | Distribuzioni di ISO, apertura, lunghezza focale, tempo di esposizione |
| **Cronologia** | Foto nel tempo |
| **Categorie** | Analisi delle categorie, gestione dei pesi e correlazioni dei punteggi |
| **Correlazioni** | Grafici di correlazione personalizzati di metriche X/Y con raggruppamento |

### Scheda Categorie

Quattro sotto-schede:

| Sotto-scheda | Descrizione |
|---------|-------------|
| **Dettaglio** | Conteggio foto per categoria, punteggi medi, istogrammi di distribuzione dei punteggi |
| **Pesi** | Confronto con grafico radar (fino a 5 categorie), mappa di calore dei pesi ed editor dei pesi (modalità di modifica) |
| **Correlazioni** | Mappa di calore della correlazione di Pearson che mostra come ogni dimensione influenza l'aggregato, vista clicca-per-dettaglio |
| **Sovrapposizione** | Analisi della sovrapposizione dei filtri che mostra quali categorie condividono foto corrispondenti |

Ogni grafico ha un pulsante di aiuto `?` attivabile che spiega come leggerlo. Un interruttore di aiuto globale nella barra delle sotto-schede mostra le spiegazioni per tutte le sotto-schede.

### Editor dei pesi (modalità di modifica)

Disponibile nella sotto-scheda Pesi quando la modalità di modifica è attiva:

1. Seleziona una categoria dal menu a tendina
2. Regola i cursori dei pesi (uno per metrica, dovrebbero sommare a 100%)
3. Usa "Normalizza a 100" per bilanciare automaticamente
4. Espandi la sezione comprimibile Modificatori per regolare bonus/penalità
5. L'**Anteprima distribuzione punteggi** mostra un istogramma prima/dopo in tempo reale mentre muovi i cursori
6. Clicca **Salva** per aggiornare `scoring_config.json` (crea un backup con marca temporale)
7. Clicca **Ricalcola punteggi** (compare dopo il salvataggio) per applicare i nuovi pesi a tutte le foto di quella categoria

Tutte le statistiche sono consapevoli dell'utente in modalità multiutente — ogni utente vede le analisi solo per le proprie foto visibili.

## Scorciatoie da tastiera (galleria)

| Tasto | Azione |
|-----|--------|
| `←` `→` `↑` `↓` | Sposta il focus della tastiera tra le schede foto (colonne della griglia e righe del mosaico) |
| `Enter` | Apri la foto a fuoco |
| `Space` | Seleziona / deseleziona la foto a fuoco |
| `Ctrl+A` | Seleziona tutte le foto caricate |
| `Escape` | Cancella la selezione / chiudi il pannello dei filtri |
| `Shift+Click` | Selezione di un intervallo di foto tra l'ultima selezionata e quella cliccata |
| `Double-click` | Apri la foto |
| `?` | Mostra il riferimento delle scorciatoie da tastiera (funziona su ogni pagina) |

## Annulla

Le operazioni di gruppo di preferito/rifiuto/valutazione e le conferme di selezione mostrano
una snackbar con un'azione **Annulla** per circa 7 secondi. Le operazioni di gruppo sui
contrassegni vengono confermate immediatamente e annullate tramite chiamate API inverse
(limitate a 500 foto); le conferme di selezione sono differite — il gruppo scompare
istantaneamente ma la chiamata API parte solo allo scadere della finestra di annullamento.

## Progressive Web App

La galleria include un manifest di web app e un service worker Angular (solo build di
produzione): può essere installata nella schermata principale, lo shell dell'app si carica
offline e fino a 1000 miniature vengono memorizzate in cache LRU per 7 giorni. Le risposte
API non vengono mai memorizzate in cache (tranne i bundle i18n con una strategia di
aggiornamento), e la disconnessione cancella la cache delle miniature in modo che le
configurazioni multiutente che condividono un browser non possano far trapelare le anteprime
tra gli account. Una snackbar offre un ricaricamento quando è stata distribuita una nuova versione.

## Mobile

Sugli schermi piccoli la barra di selezione di gruppo si riduce al conteggio della selezione,
ai pulsanti cancella, seleziona tutto e a un unico pulsante **Azioni** che apre un foglio inferiore
adatto al tocco con tutte le operazioni di gruppo (preferito, rifiuto, valutazione, album, copia,
download).

## Configurazione

### Impostazioni di visualizzazione

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Impaginazione

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Limiti dei menu a tendina

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Imposta `min_photos_for_person` su un valore più alto per nascondere dal menu a tendina dei filtri le persone con poche foto.

### Soglie di qualità

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Filtri predefiniti

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Pesi delle migliori scelte

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Prestazioni

### Database di grandi dimensioni (50k+ foto)

Esegui questi comandi per prestazioni migliori:

```bash
python database.py --migrate-tags    # query dei tag 10-50x più veloci
python database.py --refresh-stats   # Precalcola le aggregazioni
python database.py --optimize        # Deframmenta il database
```

### SQLite asincrono (opt-in, per percorsi di lettura ad alta concorrenza)

`api.database.get_async_db()` è un gestore di contesto asincrono basato su aiosqlite,
parallelo a `get_db()`. Gli endpoint sono attualmente sincroni (FastAPI li delega a un
pool di thread worker, il che va bene a concorrenze tipiche). Per percorsi di lettura ad
alta concorrenza (>5 utenti simultanei), i singoli endpoint possono essere migrati così:

1. Cambia `def foo(...)` in `async def foo(...)`.
2. Sostituisci `with get_db() as conn:` con `async with get_async_db() as conn:`.
3. `await` su ogni `.execute()` e `.fetchone()` / `.fetchall()`.
4. Mantieni sincroni i percorsi di scrittura — aiosqlite serializza comunque le scritture, e
   il pool di connessioni del percorso sincrono le gestisce già.

I candidati più caldi del piano sono `/api/photos`, `/api/timeline`,
`/api/search`. Migra uno alla volta e fai benchmark prima di promuovere.

### Cache delle statistiche

Aggregazioni precalcolate con TTL di 5 minuti:
- Conteggi totali delle foto
- Conteggi dei modelli di fotocamera/obiettivo
- Conteggi delle persone
- Conteggi delle categorie e dei modelli

Controlla lo stato:
```bash
python database.py --stats-info
```

### Caricamento differito dei filtri

I menu a tendina dei filtri si caricano su richiesta tramite API:
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## Endpoint API

La documentazione interattiva delle API è disponibile in `/api/docs` (Swagger UI) e lo schema OpenAPI in `/api/openapi.json`.

### Galleria

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/photos` | Elenco foto impaginato con filtri |
| `GET /api/photo` | Dettagli di una singola foto |
| `GET /api/type_counts` | Conteggi foto per tipo |
| `GET /api/similar_photos/{path}` | Foto simili (modalità: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Ricerca semantica testo-immagine (`scope=text` = solo testo OCR/didascalia) |
| `GET /api/critique?path=&mode=` | Critica IA (basata su regole o VLM) |
| `GET /api/ranker/status` | Stato del ranker personale per l'ordinamento "I miei gusti" (% di copertura appresa, accuratezza su dati di validazione) |
| `GET /api/config` | Configurazione della galleria |

### Autenticazione

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/auth/login` | Autenticati e ricevi un token |
| `POST /api/auth/edition/login` | Sblocca la modalità di modifica |
| `POST /api/auth/edition/logout` | Blocca la modalità di modifica (rimuove i privilegi, resti autenticato) |
| `GET /api/auth/status` | Controlla lo stato di autenticazione |

### Miniature e immagini

| Endpoint | Descrizione |
|----------|-------------|
| `GET /thumbnail` | Miniatura della foto |
| `GET /face_thumbnail/{id}` | Miniatura del ritaglio del volto |
| `GET /person_thumbnail/{id}` | Miniatura rappresentativa della persona |
| `GET /image` | Immagine a piena risoluzione |

### Opzioni di filtro

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/filter_options/cameras` | Modelli di fotocamera con conteggi |
| `GET /api/filter_options/lenses` | Modelli di obiettivo con conteggi |
| `GET /api/filter_options/tags` | Tag con conteggi |
| `GET /api/filter_options/persons` | Persone con conteggi |
| `GET /api/filter_options/patterns` | Modelli compositivi |
| `GET /api/filter_options/categories` | Categorie con conteggi |
| `GET /api/filter_options/apertures` | Valori f-stop distinti con conteggi |
| `GET /api/filter_options/focal_lengths` | Lunghezze focali distinte con conteggi |
| `GET /api/filter_options/colors` | Facet di temperatura colore e gruppo di tonalità con conteggi |
| `GET /api/filter_options/metric_ranges` | Min/max osservati e istogramma per ogni metrica numerica (per i limiti dei cursori) |

### Operazioni di gruppo

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Contrassegna più foto come preferite |
| `POST /api/photos/batch_reject` | Contrassegna più foto come scartate |
| `POST /api/photos/batch_rating` | Imposta la valutazione a stelle per più foto |

### Persone

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/persons` | Elenca tutte le persone |
| `POST /api/persons` | Crea una nuova persona, allegando facoltativamente dei volti (riservato alla modalità di modifica). Corpo: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Elenca le persone raggruppate automaticamente senza nome con `face_count >= N` (predefinito da `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Rinomina una persona |
| `POST /api/persons/{id}/assign_faces` | Allega in blocco volti a una persona; le vecchie persone vuote vengono eliminate automaticamente (riservato alla modalità di modifica). Corpo: `{face_ids}` |
| `POST /api/persons/{id}/split` | Dividi un sottoinsieme dei volti di una persona in una nuova persona (riservato alla modalità di modifica). Corpo: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Nascondi una persona dall'elenco, dai filtri e dai suggerimenti di unione |
| `POST /api/persons/{id}/unhide` | Mostra di nuovo una persona precedentemente nascosta |
| `POST /api/persons/merge` | Unisci due persone (corpo JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Unisci la persona di origine in quella di destinazione |
| `POST /api/persons/merge_batch` | Unisci più persone in una sola volta |
| `POST /api/persons/merge_suggestions/reject` | Ignora un suggerimento di unione in modo che non venga riproposto |
| `POST /api/persons/{id}/delete` | Elimina una persona |
| `POST /api/persons/delete_batch` | Elimina più persone in una sola volta |

### Album

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/albums` | Elenca tutti gli album |
| `POST /api/albums` | Crea un album |
| `GET /api/albums/{id}` | Ottieni i dettagli dell'album |
| `PUT /api/albums/{id}` | Aggiorna l'album |
| `DELETE /api/albums/{id}` | Elimina l'album |
| `GET /api/albums/{id}/photos` | Elenca le foto nell'album (impaginato) |
| `POST /api/albums/{id}/photos` | Aggiungi foto all'album |
| `DELETE /api/albums/{id}/photos` | Rimuovi foto dall'album |
| `POST /api/albums/{id}/share` | Genera un token di condivisione |
| `DELETE /api/albums/{id}/share` | Revoca il token di condivisione |
| `GET /api/shared/album/{id}?token=` | Visualizza l'album condiviso (nessuna autenticazione) |

### Ricordi, Cronologia, Mappa e didascalie

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/memories?date=` | Foto scattate in questa data negli anni precedenti |
| `GET /api/memories/check` | Controlla se esistono ricordi per una data |
| `GET /api/caption?path=` | Ottieni o genera una didascalia IA |
| `PUT /api/caption` | Aggiorna la didascalia della foto (modalità di modifica) |
| `GET /api/timeline?cursor=&limit=&direction=` | Foto cronologiche impaginate |
| `GET /api/timeline/dates?year=&month=` | Date disponibili per la navigazione |
| `GET /api/timeline/years` | Anni disponibili con conteggi di foto |
| `GET /api/timeline/months` | Mesi disponibili per un anno |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Foto geolocalizzate entro i confini |
| `GET /api/photos/map/count` | Conteggio delle foto geolocalizzate |

### Capsule

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/capsules` | Elenco capsule impaginato (in cache) |
| `GET /api/capsules/{id}/photos` | Foto di una capsula specifica |
| `POST /api/capsules/{id}/save-album` | Salva la capsula come album (modalità di modifica) |

### Statistiche

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/stats/overview` | Riepilogo generale delle statistiche di valutazione |
| `GET /api/stats/score_distribution` | Dati dell'istogramma di distribuzione dei punteggi |
| `GET /api/stats/top_cameras` | Fotocamere principali per numero di foto |
| `GET /api/stats/categories` | Conteggi e medie delle categorie |
| `GET /api/stats/gear` | Conteggi di fotocamere/obiettivi/combinazioni |
| `GET /api/stats/settings` | Distribuzioni delle impostazioni di scatto |
| `GET /api/stats/timeline` | Dati della cronologia |
| `GET /api/stats/correlations` | Correlazioni di metriche personalizzate |
| `GET /api/stats/categories/breakdown` | Conteggi foto per categoria e distribuzioni dei punteggi |
| `GET /api/stats/categories/weights` | Pesi e modificatori delle categorie dalla configurazione |
| `GET /api/stats/categories/correlations` | Correlazione di Pearson r per dimensione per categoria |
| `GET /api/stats/categories/metrics?category=X` | Valori grezzi delle metriche per l'anteprima lato client |
| `GET /api/stats/categories/overlap` | Analisi della sovrapposizione dei filtri tra categorie |
| `POST /api/stats/categories/update` | Aggiorna pesi/modificatori della categoria (modalità di modifica) |
| `POST /api/stats/categories/recompute` | Ricalcola i punteggi per una categoria (modalità di modifica) |

### Modalità di confronto

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/comparison/next_pair` | Ottieni la prossima coppia di foto da confrontare |
| `POST /api/comparison/submit` | Invia il risultato del confronto |
| `POST /api/comparison/reset` | Azzera i dati di confronto |
| `GET /api/comparison/stats` | Statistiche della sessione di confronto |
| `GET /api/comparison/history` | Elenca i confronti passati |
| `POST /api/comparison/edit` | Modifica il risultato di un confronto |
| `POST /api/comparison/delete` | Elimina un confronto |
| `GET /api/comparison/coverage` | Copertura per categoria dei confronti |
| `GET /api/comparison/confidence` | Metriche di confidenza per i punteggi appresi |
| `GET /api/comparison/photo_metrics` | Metriche grezze delle foto |
| `GET /api/comparison/category_weights` | Pesi/filtri della categoria |
| `GET /api/comparison/learned_weights` | Pesi suggeriti dai confronti |
| `POST /api/comparison/preview_score` | Anteprima con pesi personalizzati |
| `POST /api/comparison/suggest_filters` | Analizza i conflitti dei filtri |
| `POST /api/comparison/override_category` | Sovrascrivi la categoria di una foto |
| `POST /api/recalculate` | Ricalcola i punteggi con i pesi correnti |

### Selezione delle raffiche

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/burst-groups` | Elenca i gruppi di raffica per la selezione |
| `POST /api/burst-groups/select` | Seleziona i conservati da un gruppo di raffica |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Gruppi di foto visivamente simili |
| `POST /api/similar-groups/select` | Seleziona i conservati da un gruppo di foto simili |
| `GET /api/culling-groups?exclude_rejected=true&similarity_threshold=&page=&per_page=` | Gruppi combinati di raffiche e foto simili. `exclude_rejected` (predefinito `true`) nasconde le foto con `is_rejected=1`; i gruppi con meno di 2 foto rimanenti vengono scartati |
| `POST /api/culling-groups/confirm` | Conferma le selezioni di selezione |
| `POST /api/culling-group/faces` | Badge per volto (occhi aperti/chiusi, espressione, confidenza) per un gruppo, in un'unica chiamata batch |
| `GET /api/scenes` | Scene cronologiche delle foto guida delle raffiche |
| `POST /api/scenes/confirm` | Conferma le selezioni di selezione delle scene |

### Scansione

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Avvia una scansione di valutazione |
| `GET /api/scan/status` | Controlla l'avanzamento della scansione (campo strutturato `progress`: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Avanzamento in tempo reale tramite Server-Sent Events; il token viene passato come parametro di query (l'API `EventSource` non può impostare header), con fallback automatico al polling di `/status` |
| `GET /api/scan/directories` | Elenca le directory di scansione configurate |

### Gestione dei volti

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/person/{id}/faces` | Elenca i volti di una persona |
| `POST /api/person/{id}/avatar` | Imposta il volto avatar della persona |
| `GET /api/photo/faces` | Elenca i volti rilevati in una foto |
| `POST /api/face/{id}/assign` | Assegna un volto a una persona |
| `POST /api/photo/assign_all_faces` | Assegna tutti i volti di una foto a una persona |
| `POST /api/photo/unassign_person` | Rimuovi l'assegnazione di una persona da una foto |

### Azioni sulle foto

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/photo/set_rating` | Imposta la valutazione a stelle di una foto |
| `POST /api/photo/toggle_favorite` | Attiva/disattiva lo stato di preferito |
| `POST /api/photo/toggle_rejected` | Attiva/disattiva lo stato di scartato |

### Gestione della configurazione

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/config/update_weights` | Aggiorna i pesi di valutazione |
| `GET /api/config/weight_snapshots` | Elenca le istantanee dei pesi salvate |
| `POST /api/config/save_snapshot` | Salva i pesi correnti come istantanea |
| `POST /api/config/restore_weights` | Ripristina i pesi da un'istantanea |

### Suggerimenti di unione

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/merge_suggestions` | Unioni di persone suggerite in base alla somiglianza dei volti |

### Cartelle

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/folders` | Elenca la struttura delle cartelle delle foto |

### Download

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/download/options` | Tipi di download disponibili per una foto (`path`, `is_shared` facoltativo) |
| `GET /api/download` | Scarica una foto (`path`, `type=original\|darktable\|raw`, `profile` facoltativo) |

**Tipi di download:**

- `original` — Serve il file così com'è (JPG/HEIF) o convertito in JPEG tramite rawpy (file RAW).
- `darktable` — Converte il RAW associato con un profilo darktable denominato (richiede il parametro `profile`). Ricade sull'originale se non esiste alcun RAW associato.
- `raw` — Serve il file RAW associato così com'è (non disponibile negli album condivisi).

L'endpoint `/api/download/options` rileva automaticamente i file RAW associati e restituisce le opzioni disponibili, inclusi i profili darktable configurati. La galleria lo usa per popolare un menu di download per foto.

### Esportazione per editor

| Endpoint | Descrizione |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Scrivi un sidecar XMP |
| `POST /api/export/sidecars` | `[Edition]` Scrivi i sidecar per percorsi espliciti o per un insieme di filtri |
| `POST /api/photo/embed_metadata` | `[Edition]` Incorpora i metadati nel file originale (JPEG/HEIC/TIFF/PNG/DNG; RAW mai modificato) e scrivi il sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Esportazione album come sidecar, copia o collegamento simbolico |

### Plugin

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/plugins` | Elenca i plugin configurati |
| `POST /api/plugins/test-webhook` | Testa un plugin webhook |

### Stato di salute

| Endpoint | Descrizione |
|----------|-------------|
| `GET /health` | Controllo dello stato di salute del server |
| `GET /ready` | Controllo della prontezza del server |
| `GET /metrics` | Metriche in formato Prometheus: conteggi foto, copertura degli embedding, dimensione del DB, memoria del processo |

### Internazionalizzazione

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/i18n/languages` | Elenca le lingue disponibili |
| `GET /api/i18n/{lang}` | Ottieni le traduzioni per una lingua |

### Opzioni di filtro (aggiuntive)

| Endpoint | Descrizione |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Geocodifica inversa delle coordinate in un nome di luogo |

## Risoluzione dei problemi

| Problema | Soluzione |
|-------|----------|
| Caricamento pagina lento | Esegui `--migrate-tags` e `--optimize` |
| I filtri non compaiono | Controlla `--stats-info`, esegui `--refresh-stats` |
| Filtro persona vuoto | Esegui `--cluster-faces-incremental` |
| Pulsante Confronta mancante | Imposta una `edition_password` non vuota (utente singolo) o usa il ruolo `admin`/`superadmin` (multiutente) |
| Password non funzionante | Controlla `viewer.password` (utente singolo) o verifica l'hash della password (multiutente) |
| L'utente non vede le foto | Controlla `directories` nella sua configurazione utente e `shared_directories` |
| Pulsante di scansione mancante | Richiede il ruolo `superadmin` e `viewer.features.show_scan_button: true` |
| La ricerca non restituisce risultati | Assicurati che le foto abbiano i dati `clip_embedding` (esegui prima la valutazione) |
| Critica VLM non disponibile | Richiede il profilo VRAM 16gb/24gb e `viewer.features.show_vlm_critique: true` |
| La mappa non mostra foto | Esegui `--extract-gps` per popolare le colonne GPS, assicurati che le foto abbiano dati GPS EXIF |
| Le didascalie non vengono generate | Richiede il profilo VRAM 16gb/24gb per le didascalie VLM |
| Cronologia vuota | Assicurati che le foto abbiano valori `date_taken` |
| Porta 5000 in uso | Esegui `python viewer.py --port 5001` (o imposta `PORT=5001`). Su macOS, il Ricevitore AirPlay di ControlCenter occupa la porta 5000 per impostazione predefinita — scegli un'altra porta oppure disabilita il Ricevitore AirPlay in Impostazioni di Sistema → Generali → AirDrop e Handoff. |
