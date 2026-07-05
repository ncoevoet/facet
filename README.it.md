# Facet

> 🌐 [English](README.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Italiano** · [Español](README.es.md) · [Português](README.pt.md)

Facet è un motore locale di analisi e selezione delle foto. Assegna a ogni immagine un punteggio su 9 dimensioni — dalla qualità estetica alla nitidezza dei volti — e ti permette poi di sfogliare, selezionare e organizzare attraverso una galleria web. Tutto viene eseguito sulla tua macchina; nessun cloud, account o chiave API.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-21-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/hero-mosaic.jpg" alt="Facet — galleria a mosaico delle Migliori scelte" width="100%">
</p>

## Come funziona

1. **Scansione** — Indica a Facet una cartella di foto. Ogni immagine viene analizzata per qualità, composizione e volti. Supporta JPG, HEIF/HEIC e 10 formati RAW (CR2, CR3, NEF, ARW, RAF, RW2, DNG, ORF, SRW, PEF).
2. **Sfogliare** — Apri la galleria web per esplorare la tua libreria con filtri, ricerca e più modalità di visualizzazione.
3. **Selezione** — Facet rileva le raffiche, segnala gli occhi chiusi, raggruppa le foto simili e mette in evidenza le migliori scelte.

La GPU viene rilevata automaticamente ed è opzionale. Facet funziona solo su CPU oppure con un massimo di 24 GB di VRAM.

## Funzionalità

### Punteggio

A ogni foto viene assegnato un punteggio su 9 dimensioni: qualità estetica, composizione, qualità del volto, nitidezza degli occhi, nitidezza tecnica, colore, esposizione, salienza del soggetto e gamma dinamica. Le foto vengono categorizzate per contenuto (ritratto, paesaggio, macro, street, ecc. — oltre 30 categorie) e valutate con pesi specifici per categoria. Un filtro **Migliori scelte** classifica la libreria in base a un punteggio combinato.

Passa il puntatore su una foto per vedere un tooltip con il dettaglio del punteggio e i dati EXIF.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Tooltip al passaggio del mouse con dettaglio del punteggio" width="100%">

### Selezione

- **Rilevamento raffiche** — raggruppa gli scatti in rapida successione e seleziona automaticamente il migliore in base a nitidezza, qualità e rilevamento degli occhi chiusi
- **Gruppi di somiglianza** — trova le foto visivamente simili in tutta la libreria, indipendentemente da quando sono state scattate
- **Scene** — raggruppa una sessione in "scene" cronologiche in base agli intervalli tra gli scatti, così da selezionare nell'ordine del racconto; tocca per contrassegnare e conferma per rifiutare
- **Pulizia degli scarti** — rilevamento zero-shot di file non fotografici superflui (screenshot, documenti, ricevute, meme, diapositive) con una coda di revisione rapida: conserva o rifiuta ogni candidato, oppure rifiutali tutti in una volta
- **Badge per volto nella selezione** — il visualizzatore di selezione mostra badge per ogni volto (occhi aperti/chiusi, espressione, confidenza di rilevamento) invece di un singolo contrassegno di occhi chiusi a livello di foto
- **Rilevamento occhi chiusi** — segnala gli scatti con gli occhi chiusi da nascondere o rifiutare con un clic
- **Rilevamento duplicati** — identifica le immagini quasi identiche tramite hashing percettivo

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Selezione delle raffiche" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Gruppi di somiglianza per la selezione" width="100%"></td>
</tr></table>

### Sfogliare

- **Modalità galleria** — mosaico (righe giustificate che preservano le proporzioni) e griglia (schede uniformi con sovrapposizione dei metadati)
- **Filtri** — intervallo di date, tag di contenuto, modello compositivo, fotocamera, obiettivo, persona, livello di qualità, valutazione a stelle e intervalli di metriche personalizzati
- **Ricerca semantica** — digita una query in linguaggio naturale come "tramonto in spiaggia" e trova le foto corrispondenti tramite embedding e ricerca testuale
- **Cronologia** — browser cronologico con navigazione per anno/mese e scorrimento infinito
- **Mappa** — foto geolocalizzate su una mappa interattiva con clustering dei marcatori
- **Capsule** — presentazioni a tema: viaggi con nomi dei luoghi, collezione dorata, tavolozze stagionali, foto di una persona e altro ancora
- **Cartelle** — sfoglia per struttura di directory con navigazione tramite breadcrumb e foto di copertina
- **Ricordi** — "Accadde oggi": foto della stessa data negli anni precedenti
- **Presentazione** — modalità a schermo intero con transizioni a tema, concatenamento automatico tra capsule e controlli da tastiera

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Barra laterale dei filtri" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Risultati della ricerca semantica" width="100%"></td>
</tr></table>

<details><summary>Barra laterale dei filtri — tutte le sezioni espanse (clicca per visualizzare)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Barra laterale dei filtri con tutte le opzioni espanse" width="380"></p>
</details>

**Suggerimenti per il flusso di lavoro:**
- Per una revisione cronologica di un viaggio o di un anno, apri **`/timeline`** — ordina per aggregato per scorrere i migliori scatti di una giornata, oppure naviga mese per mese.
- La vista **`/capsules`** genera diaporami a tema (viaggi, "Volti di", stagionali, dorate) che puoi salvare come album.
- La galleria nasconde per impostazione predefinita gli occhi chiusi, le raffiche non principali e i duplicati. Quando compare il banner **"N foto nascoste dai filtri attivi"**, clicca su "Mostra tutte" per espandere la vista.

### Organizzare

- **Riconoscimento facciale** — rilevamento automatico dei volti, raggruppamento in persone e rilevamento degli occhi chiusi. Cerca, rinomina, unisci e organizza i cluster di persone dall'interfaccia di gestione. I **suggerimenti di unione** individuano i cluster dall'aspetto simile che potrebbero essere la stessa persona.
- **Album** — raccolte manuali con trascinamento, oppure album intelligenti che si popolano automaticamente da combinazioni di filtri salvate
- **Valutazioni e preferiti** — valutazioni a stelle (1–5), preferiti e contrassegni di rifiuto. Scorri le valutazioni con un solo clic.
- **Tag** — tag di contenuto generati dall'IA con vocabolario configurabile. Clicca su un tag qualsiasi per filtrare la galleria.
- **Operazioni in batch** — selezione multipla con Shift+clic, Ctrl+clic o Ctrl+A (seleziona tutto). Imposta valutazioni, attiva/disattiva i preferiti, contrassegna i rifiuti o aggiungi agli album in blocco — con annullamento di 7 secondi per ogni azione in batch.
- **Priorità alla tastiera** — i tasti freccia navigano la galleria, Invio apre, Spazio seleziona; premi `?` in qualsiasi punto per il riferimento delle scorciatoie.

<img src="docs/screenshots/albums.jpg" alt="Album — raccolte manuali e intelligenti" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Pagina Gestisci persone" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Galleria della persona" width="100%"></td>
</tr></table>

### Comprendere

- **Statistiche** — dashboard per l'utilizzo dell'attrezzatura, la suddivisione per categoria, la cronologia degli scatti e le correlazioni tra metriche
- **Critica IA** — dettaglio del punteggio che mostra il contributo di ogni metrica; valutazione in linguaggio naturale VLM `[GPU]` `[16gb/24gb]`
- **Regolazione dei pesi** — editor dei pesi per categoria con anteprima del punteggio in tempo reale. Il confronto A/B tra foto impara dalle tue scelte e suggerisce pesi ottimizzati.
- **Ordinamento "I miei gusti"** — ordina la galleria in base al punteggio appreso dal ranker personale, con un badge di confidenza che mostra la copertura appresa e l'accuratezza su dati di validazione
- **Apprendimento dalle etichette** — le decisioni di selezione, le valutazioni a stelle, i preferiti e i rifiuti alimentano l'ottimizzatore dei pesi (`--sync-label-comparisons`, `--mine-insights`)
- **Snapshot** — salva, ripristina e confronta le configurazioni dei pesi
- **Istogramma** — istogramma della luminanza nel tooltip della foto e nella vista di dettaglio
- **Didascalie IA** `[GPU]` `[16gb/24gb]` `[Edition]` — descrizioni testuali, modificabili e traducibili in 5 lingue

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Statistiche dell'attrezzatura" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Analisi per categoria" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Cronologia degli scatti" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Correlazioni tra metriche" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="Finestra di dialogo Critica IA" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="Snapshot" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Cursori dei pesi per categoria" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="Confronto A/B tra foto" width="100%"></td>
</tr></table>

### Condividere

- **Condivisione di album** — genera link condivisibili per qualsiasi album, senza richiedere l'accesso ai destinatari. Revoca l'accesso in qualsiasi momento.
- **Download delle foto** — scarica singole foto o selezioni dalla galleria
- **Esportazione** — esporta tutti i punteggi in CSV o JSON per l'analisi esterna

### Altro

- **Modalità scura e chiara** con 10 temi di colore d'accento; rispetta la preferenza di sistema
- **Reattiva** — si adatta da mobile a desktop, con un pannello di azioni in blocco ottimizzato per il tocco sugli schermi piccoli
- **PWA installabile** — manifest dell'app web + service worker: installa nella schermata principale, shell dell'app offline, miniature memorizzate nella cache
- **Galleria virtualizzata** — renderizza solo una manciata di nodi DOM indipendentemente dalle dimensioni della libreria, così lo scorrimento resta veloce con oltre 100k foto
- **Scansioni riprendibili** — le scansioni interrotte riprendono (`--resume`), i file falliti vengono tracciati e ritentabili (`--retry-failed`), il progresso viene trasmesso all'interfaccia web
- **6 lingue** — inglese, francese, tedesco, spagnolo, italiano, portoghese brasiliano
- **Multi-utente** — directory, valutazioni e accesso basato sui ruoli per utente
- **Plugin e webhook** — azioni personalizzate attivate dagli eventi di punteggio
- **Scansione dall'interfaccia web** — avvia le scansioni dal browser (ruolo superadmin)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Galleria mobile" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Galleria tablet" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Mosaico desktop" width="100%"></td>
</tr></table>

## Cosa ti serve

La maggior parte di Facet funziona su **qualsiasi macchina (CPU)** — punteggio, rilevamento dei volti, selezione, galleria, ricerca, album ed esportazione dei metadati funzionano tutti senza una GPU. Una **GPU** (con il profilo `16gb` o `24gb`) sblocca i modelli più potenti: punteggio estetico TOPIQ, embedding SigLIP 2, tagging VLM, didascalie e critica IA, e salienza del soggetto. Niente GPU locale? Indirizza il tagging/le didascalie/la critica VLM verso un server **Ollama** o **compatibile OpenAI** remoto tramite `vlm_backend` in `scoring_config.json` — queste funzionalità funzionano allora anche sui profili CPU `legacy`/`8gb`. Nel viewer, le azioni di modifica (valutazioni, volti, selezione) richiedono la **password di modifica**, e l'avvio delle scansioni richiede il ruolo **superadmin**.

→ Requisiti completi per ciascuna funzionalità (GPU, profilo VRAM, pacchetti opzionali, autenticazione): **[Installazione › Requisiti delle funzionalità](docs/it/INSTALLATION.md#requisiti-delle-funzionalità)**.

## Facet fa per te?

Facet assegna punteggi, classifica e seleziona una libreria fotografica locale e serve una galleria per sfogliarla. Funziona sul tuo hardware e mantiene le foto fuori dal cloud.

**Una buona scelta se:**

- hai una grande libreria locale e vuoi trovare i tuoi scatti migliori e selezionare raffiche e quasi-duplicati;
- vuoi un punteggio di qualità, composizione e volti che puoi regolare secondo i tuoi gusti (impara dai tuoi confronti A/B);
- preferisci l'auto-hosting e la privacy — nessun caricamento sul cloud, nessun account, nessun abbonamento;
- già modifichi in Lightroom, darktable, digiKam o immich — Facet scrive valutazioni, etichette, parole chiave, didascalie e regioni di volti nominati nei sidecar `.xmp` (originali intatti per impostazione predefinita) e può facoltativamente incorporarli nei file per JPEG/HEIC/TIFF/PNG/DNG (azione "Scrivi metadati su file" della galleria o `--export-sidecars --embed-originals`), e rilegge le modifiche esterne con `--import-sidecars`.

**Probabilmente non fa per te se vuoi:**

- una sostituzione chiavi in mano, mobile e basata sul cloud di Google Photos con backup automatico dal telefono;
- modifica o sviluppo RAW — Facet assegna punteggi e organizza, non modifica;
- un'app desktop a configurazione zero — richiede Python, e i modelli migliori richiedono una GPU.

**Come si rapporta agli altri strumenti**

- Le librerie self-hosted (Immich, PhotoPrism) si concentrano su organizzazione, ricerca e backup. Facet aggiunge il punteggio di qualità, la classificazione e un flusso di lavoro di selezione che esse non offrono, ma non ha app mobile né backup/sincronizzazione integrati.
- Le app di selezione IA (Aftershoot, Narrative, FilterPixel) sono selezionatori commerciali raffinati, spesso con la modifica integrata. Facet è gratuito, locale, più ampio (galleria, ricerca, volti) e il suo punteggio è regolabile — ma è un progetto di un singolo sviluppatore senza il loro supporto né la modifica RAW.
- Gli editor e i cataloghi (Lightroom, darktable, digiKam) sviluppano e gestiscono le foto. Facet li completa tramite l'interoperabilità dei metadati XMP descritta sopra anziché sostituirli.

Il punteggio estetico è basato su modelli ed è approssimativo; aspettati di dover regolare i pesi per adattarli ai tuoi gusti.

## Avvio rapido

### Docker (consigliato)

```bash
docker compose up
# Apri http://localhost:5000
```

Questo viene eseguito in modalità CPU — nessuna GPU richiesta per sfogliare e servire una libreria esistente. Monta la tua directory di foto in `docker-compose.yml`.

L'**accelerazione GPU** (opzionale) richiede una GPU NVIDIA e il [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html). Attivala con il file di override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

### Installazione manuale

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # rileva automaticamente la GPU, crea il venv, installa tutto

source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py /photos  # valuta le foto
python viewer.py         # avvia il viewer web → http://localhost:5000
```

> **macOS:** AirPlay Receiver di ControlCenter occupa la porta 5000 per impostazione predefinita. Se vedi "Address already in use", esegui `python viewer.py --port 5001`.

Lo script di installazione rileva automaticamente la tua versione di CUDA, installa la variante corretta di PyTorch, compila il frontend Angular e verifica tutti gli import. Opzioni: `--cpu` (forza CPU), `--cuda 12.8` (sovrascrive la versione di CUDA), `--skip-client` (salta la compilazione del frontend).

<details>
<summary>Installazione manuale passo passo</summary>

```bash
# 1. Installa exiftool (opzionale ma consigliato)
# Ubuntu/Debian: sudo apt install libimage-exiftool-perl
# macOS:         brew install exiftool

# 2. Crea l'ambiente virtuale
python -m venv venv && source venv/bin/activate

# 3. Installa PyTorch con CUDA (scegli la tua versione su https://pytorch.org/get-started/locally)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 4. Installa le dipendenze Python (tutte insieme — vedi Risoluzione dei problemi in caso di conflitti)
pip install -r requirements.txt

# 5. Installa ONNX Runtime per il rilevamento dei volti (scegline UNO)
pip install onnxruntime-gpu>=1.17.0   # GPU (CUDA 12.x)
# pip install onnxruntime>=1.15.0     # ripiego su CPU

# 6. Compila il frontend Angular
cd client && npm install && npx ng build && cd ..

# 7. Valuta le foto e avvia il viewer
python facet.py /path/to/photos
python viewer.py
```
</details>

Esegui `python facet.py --doctor` per diagnosticare i problemi della GPU. Vedi [Installazione](docs/it/INSTALLATION.md) per i profili VRAM, i pacchetti di tagging VLM (16gb/24gb), le dipendenze opzionali e la [risoluzione dei conflitti tra dipendenze](docs/it/INSTALLATION.md#troubleshooting-dependency-conflicts).

## Documentazione

| Documento | Descrizione |
|----------|-------------|
| [Installazione](docs/it/INSTALLATION.md) | Requisiti, configurazione GPU, profili VRAM, dipendenze |
| [Comandi](docs/it/COMMANDS.md) | Riferimento di tutti i comandi CLI |
| [Configurazione](docs/it/CONFIGURATION.md) | Riferimento completo di `scoring_config.json` |
| [Punteggio](docs/it/SCORING.md) | Categorie, pesi, guida alla regolazione |
| [Riconoscimento facciale](docs/it/FACE_RECOGNITION.md) | Flusso di lavoro dei volti, clustering, gestione delle persone |
| [Viewer](docs/it/VIEWER.md) | Funzionalità e utilizzo della galleria web |
| [Interoperabilità](docs/it/INTEROP.md) | Scambiare valutazioni/tag con Lightroom, Capture One, digiKam, darktable |
| [Distribuzione](docs/it/DEPLOYMENT.md) | Distribuzione in produzione (NAS Synology, Linux, Docker) |
| [Contribuire](CONTRIBUTING.md) | Configurazione di sviluppo, architettura, stile del codice |

## Licenza

[MIT](LICENSE)
