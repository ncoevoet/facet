# Galleria web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · **Italiano** · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md) · [简体中文](../zh/VIEWER.md)

La galleria è un'app web FastAPI + Angular per sfogliare, filtrare, selezionare e gestire le tue foto.

## Contenuti

- [Avvio della galleria](#avvio-della-galleria) · [Autenticazione](#autenticazione) · [Opzioni di filtraggio](#opzioni-di-filtraggio) · [Ordinamento](#ordinamento) · [Decisioni di revisione](#decisioni-di-revisione) · [Funzionalità della galleria](#funzionalità-della-galleria)
- [Panorami e bracket di esposizione](#panorami-e-bracket-di-esposizione)
- [Gestione delle persone](#gestione-delle-persone) · [Avvio scansione](#avvio-scansione) · [Ricerca semantica](#ricerca-semantica) · [Album](#album)
- [Critica IA](#critica-ia) · [Didascalie IA](#didascalie-ia-gpu-16gb24gb-edition) · [Ricordi ("In questo giorno")](#ricordi-in-questo-giorno) · [Vista cronologia](#vista-cronologia) · [Vista mappa](#vista-mappa) · [Capsule](#capsule)
- [Vista cartelle](#vista-cartelle) · [Finestra filtro GPS](#finestra-filtro-gps) · [Suggerimenti di unione](#suggerimenti-di-unione) · [Esportazione per editor](#esportazione-per-editor) · [Download](#download) · [Selezione](#selezione) · [Pulizia degli scarti](#pulizia-degli-scarti) · [Modalità di confronto a coppie](#modalità-di-confronto-a-coppie)
- [Statistiche EXIF](#statistiche-exif) · [Scorciatoie da tastiera](#scorciatoie-da-tastiera-galleria) · [Annulla](#annulla) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile) · [Cornice digitale / Chiosco](#cornice-digitale--chiosco) · [Caricamento automatico dal telefono](#caricamento-automatico-dal-telefono)
- [Configurazione](#configurazione-3) · [Prestazioni](#prestazioni) · [Endpoint API](#endpoint-api) · [Foto JPEG XL](#foto-jpeg-xl) · [Risoluzione dei problemi](#risoluzione-dei-problemi)

> **I requisiti delle funzionalità** sono indicati in linea: `[GPU]` · `[16gb/24gb]` (profilo VRAM) · `[Edition]` (password di modifica) · `[Superadmin]`. Vedi la [matrice delle funzionalità](INSTALLATION.md#requisiti-delle-funzionalità).

> **Assistenti IA**: Facet può mettere i suoi strumenti a disposizione degli assistenti compatibili con MCP. Con il livello di token giusto possono cercare, modificare e selezionare la libreria. Vedi [Assistenti IA (MCP)](AGENTS.md).

## Avvio della galleria

### Produzione

```bash
python viewer.py
# Apri http://localhost:5000
```

Serve l'API e l'app Angular precompilata su un'unica porta.

Per un throughput più alto, usa la modalità produzione (Uvicorn, senza ricaricamento automatico). Aggiungi `--workers N` per scalare (predefinito 1):

```bash
python viewer.py --production --workers 4
```

### Sviluppo

Esegui separatamente il server API e il server di sviluppo Angular:

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

Proteggi la galleria con una password facoltativa:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Due password controllano l'accesso:

- **`viewer.password`** decide chi può *sfogliare*. Vuota, chiunque può sfogliare l'intera libreria. Impostata, gli utenti devono prima accedere.
- **`viewer.edition_password`** è richiesta per ogni modifica: valutazioni, preferiti e scarti, selezione, album, gestione di persone e volti, modalità di confronto, modifiche a pesi e priorità, ed esportazioni. Vuota (il valore predefinito fornito), l'installazione è **in sola lettura**: le modifiche vengono rifiutate con `403` ("Set viewer.edition_password to enable editing").

Anche la generazione IA su richiesta (didascalie, critiche VLM) richiede la password di modifica. Senza, ottieni solo ciò che è già in cache (`source: "none"` o `vlm_available: false`). Senza password di modifica, la galleria nasconde anche i badge esistenti di stelle, preferiti e scarti, come fa per i visualizzatori senza modifica su un'installazione protetta da password.

Riavvia la galleria dopo aver impostato `viewer.edition_password`: la configurazione non viene ricaricata a caldo.

> **Avviso:** con `viewer.password` vuota (il valore predefinito fornito), chiunque raggiunga la porta della galleria può sfogliare la libreria e scaricare gli originali. `viewer.py` ascolta su tutte le interfacce per impostazione predefinita (`--host 0.0.0.0`, su cui si basa l'immagine Docker). Imposta `viewer.password` prima di esporla oltre il tuo computer, oppure usa solo il loopback con `--host 127.0.0.1`. In Docker, pubblica la porta come `127.0.0.1:5000:5000`. La galleria registra un avviso all'avvio finché `viewer.password` è vuota (a meno che non sia associata al loopback).

Il login imposta anche il token di sessione in un cookie `HttpOnly` `SameSite=Lax`, così miniature e flusso di avanzamento della scansione si caricano sulle installazioni protette da password. Il cookie vale solo per le richieste in sola lettura (GET/HEAD); le modifiche richiedono ancora il token Bearer. Il logout (`POST /api/auth/logout`) lo cancella.

### Modalità multiutente

Per un NAS di famiglia in cui ogni membro ha cartelle di foto private. Aggiungi una sezione `users` a `scoring_config.json`:

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

Scrivi ogni voce di `directories` e `shared_directories` esattamente come lo scanner ha memorizzato il percorso. Il confronto ignora le maiuscole ASCII su Windows, macOS e per le voci UNC o con lettera di unità. Altrove (Linux, per esempio) distingue le maiuscole. Le differenze di maiuscole non ASCII e un'unità mappata che l'host non riesce a risolvere non corrispondono.

Crea gli utenti dalla CLI (non esiste una pagina di registrazione):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Vedi [Configurazione](CONFIGURATION.md#users) per il riferimento completo.

### Ruoli

| Ruolo | Vedere proprie + condivise | Valutare/preferire | Gestire persone/volti | Avviare scansioni |
|------|:-:|:-:|:-:|:-:|
| `user` | sì | sì | no | no |
| `admin` | sì | sì | sì | no |
| `superadmin` | sì | sì | sì | sì |

### Visibilità delle foto

Ogni utente vede le foto delle proprie directory più quelle delle directory condivise. Vale ovunque: galleria, miniature, download, statistiche, opzioni di filtro e pagine delle persone.

### Valutazioni per utente

In modalità multiutente, valutazioni a stelle, preferiti e scarti sono memorizzati per utente nella tabella `user_preferences`. I preferiti di Alice non influenzano la vista di Bob.

Per migrare le valutazioni esistenti di un utente singolo:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opzioni di filtraggio

La ricerca testuale della galleria conserva le parole Unicode e tratta la punteggiatura dei nomi file come confine di parola. `IMG_0042.JPG` cerca insieme i prefissi `IMG`, `0042` e `JPG`. I termini cirillici e CJK funzionano. Gli operatori FTS come `OR` sono trattati come parole letterali.

### Schede della barra laterale

La barra laterale dei filtri raggruppa le sue sezioni in cinque schede, mostrate come icone (passa il mouse per vedere il nome). Un piccolo badge su un'icona conta i filtri attivi della scheda, e la scheda mantiene il suo nome per gli screen reader («Sfoglia, 2 attivi»). L'ultima scheda usata viene ricordata in questo browser (`facet_sidebar_tab`). Sfoglia, Qualità e Soggetto hanno pannelli comprimibili, ciascuno dei quali ricorda se è aperto; Revisione e Visualizzazione non ne hanno.

| Scheda | Sezioni |
|--------|---------|
| **Sfoglia** | Ricerca semantica, Persone, Intervallo date, Contenuto, Album, Posizione, Cartella, Attrezzatura |
| **Revisione** | Una riga con menu ciascuna per la decisione, poi per raffiche, duplicati, occhi chiusi, bracketing, panorami e scartate, una valutazione a stelle, gli interruttori Preferiti e Monocromo e, per gli editor, *Volti manuali da verificare* e *Correzioni panorama* |
| **Qualità** | Qualità, Colore e qualità, Qualità estesa, Tecnica, Esposizione & Gamma (quanto è buona l'immagine) |
| **Soggetto** | Metriche volti, Composizione, Salienza del soggetto, Momenti (cosa c'è nell'inquadratura) |
| **Visualizzazione** | Vista (dimensione delle schede, layout, scorrimento rapido, azioni delle schede) |

L'intestazione, **Cerca un filtro**, l'avviso dell'album intelligente e la ricerca per nome file restano sopra le schede in ogni scheda, quindi `/` funziona da tutte. Digitare in **Cerca un filtro** nasconde le schede ed elenca i cursori corrispondenti di tutte.

Il numero accanto a **Filtri** è il totale di tutti i filtri attivi. Un intervallo min/max conta una volta, come il filtro di posizione. La ricerca per nome file e *Simile a* non hanno una sezione e sono contati solo in questo totale, come un filtro su una metrica che questa installazione nasconde, così che **Ripristina filtri** possa comunque cancellarlo. **Ripristina filtri** (con descrizione al passaggio) compare accanto al numero finché almeno un filtro è attivo; la semplice **X** all'estrema destra chiude soltanto la barra laterale sugli schermi stretti.

Nella scheda Revisione, la decisione e ogni gruppo (ad esempio Duplicati) è una riga che mostra il valore attuale (come Nascoste, Mostrate o Solo queste) e apre un menu di scelte, ciascuna con una spiegazione di una riga. Una riga lasciata sul valore predefinito non conta nel badge della scheda né dell'intestazione. *Solo* e *Nascoste* si escludono a vicenda. Finché è scelta una decisione, Scartate è bloccata e la sua descrizione ne spiega il motivo. Il pulsante a stella imposta una valutazione minima: ogni clic la aumenta di uno, e il clic dopo 5, o dopo un massimo arrivato da un link, la cancella. Condivide una riga con gli interruttori Preferiti e Monocromo, solo icona e con descrizioni al passaggio. Nelle schede Qualità e Soggetto, passare sul nome di un'impostazione spiega cosa viene valutato e da quale modello, e anche i controlli di Revisione hanno descrizioni al passaggio.

<details><summary>Barra laterale dei filtri completa — tutte le sezioni espanse (clicca per vedere)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Le cinque schede della barra laterale dei filtri affiancate: Sfoglia, Revisione, Qualità, Soggetto e Visualizzazione" width="900"></p>
</details>

### Filtri primari

| Filtro | Opzioni |
|--------|---------|
| **Tipo di foto** | Migliori scelte, Ritratti, Persone nella scena, Paesaggi, Architettura, Natura, Animali, Arte e statue, Bianco e nero, Poca luce, Silhouette, Macro, Astrofotografia, Street, Lunga esposizione, Aerea e drone, Concerti |
| **Livello di qualità** | Buona (6+), Ottima (7+), Eccellente (8+), Migliore (9+) |
| **Fotocamera e obiettivo** | Filtro basato sull'attrezzatura |
| **Persona** | Filtra per persona riconosciuta |
| **Categoria** | Filtra per categoria di foto |

### Filtri avanzati

| Categoria | Filtri |
|----------|---------|
| **Data** | Data di inizio e di fine |
| **Punteggi** | Aggregato, estetica, punteggio TOPIQ, punteggio di qualità |
| **Qualità estesa** | Aesthetic IAA (merito artistico), Face Quality IQA, punteggio LIQE |
| **Metriche volti** | Qualità del volto, nitidezza degli occhi, nitidezza del volto, rapporto del volto, confidenza del volto, numero di volti |
| **Composizione** | Punteggio di composizione, punti di forza, linee guida, isolamento, modello compositivo |
| **Salienza del soggetto** | Nitidezza del soggetto, prominenza del soggetto, posizionamento del soggetto, separazione dallo sfondo |
| **Tecnica** | Nitidezza, contrasto, gamma dinamica, livello di rumore |
| **Colore** | Punteggio colore, saturazione, luminanza, ampiezza dell'istogramma; temperatura colore e fascia di tonalità (richiedono `--recompute-colors`) |
| **Esposizione** | Punteggio di esposizione |
| **Valutazioni utente** | Valutazione a stelle |
| **Impostazioni fotocamera** | ISO, diaframma (cursore a intervallo f-stop), lunghezza focale (cursore a intervallo) |
| **Contenuto** | Tag, interruttore monocromatico |
| **Momenti** | Confidenza del momento narrativo (cursore 0–1: `min_moment_confidence` / `max_moment_confidence`) |

Alcuni filtri a intervallo corrispondono solo alle foto che hanno un valore, quindi anche un filtro che parte da 0 esclude le foto senza punteggio:

- **Aesthetic IAA, Face Quality IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA**: una foto che il modello non ha potuto valutare non ha valore. Un ordinamento crescente su queste la elenca per ultima, nella galleria e negli album. Vedi [Dimensioni IQA supplementari](SCORING.md#dimensioni-iqa-supplementari).
- **Nitidezza del soggetto, Posizionamento del soggetto, Separazione dallo sfondo, Punti di forza**: una foto senza soggetto rilevabile non ha valore e il pannello dettagli omette la riga. La prominenza del soggetto vale 0.0 per tale foto. Vedi [SCORING.md](SCORING.md).

### Modelli compositivi

Filtra per gli 8 modelli rilevati da SAMP-Net (da `models/samp_net.py`):
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Ordinamento

Il pulsante di ordinamento nell'intestazione (e nella barra mobile) mostra l'icona dell'ordinamento attuale; il suo tooltip dice `Sort by: <ordinamento attuale>`. Apre un menu raggruppato con tutti gli ordinamenti. Accanto c'è l'interruttore crescente/decrescente. I modelli di punteggio alternativi usano etichette brevi (IAA, 2.5, Q-R, DeQA, LIQE e IQA).

**Ordinamento memorizzato.** La galleria si apre sull'ultimo ordinamento scelto, che prevale su `viewer.defaults.sort`. La scelta è memorizzata per browser in `localStorage`, non per account.

- Viene ricordata solo una scelta fatta nel menu di ordinamento. Un ordinamento da un link condiviso o da un assistente no, e l'`sort` del link prevale.
- Scegliere di nuovo il valore predefinito configurato, o reimpostare i filtri, cancella la scelta.
- La **Pertinenza** non viene mai ricordata, perché richiede una query di ricerca.

Le velocità dell'otturatore si ordinano per durata, quindi `1/250` e `0.004` sono uguali. I valori mancanti o non validi vanno in fondo in entrambe le direzioni.

Colonne ordinabili per gruppo (da `viewer.sort_options`):

| Gruppo | Colonne |
|-------|---------|
| **Generale** | Punteggio aggregato, Estetica, Punteggio di qualità, Data di scatto, Valutazione a stelle, Estetica (IAA), Punteggio LIQE, Q-ReAlign (Estetica), DeQA, Estetica v2.5 (gli ultimi tre compaiono quando una foto ha quel punteggio) |
| **Metriche volti** | Qualità del volto, Qualità del volto (IQA), Nitidezza degli occhi, Nitidezza del volto, Rapporto del volto, Numero di volti |
| **Tecnica** | Nitidezza tecnica, Contrasto, Livello di rumore |
| **Colore** | Punteggio colore, Saturazione |
| **Esposizione** | Punteggio di esposizione, Luminanza media, Ampiezza dell'istogramma, Gamma dinamica |
| **Composizione** | Punteggio di composizione, Punteggio dei punti di forza, Linee guida, Bonus di isolamento, Modello compositivo |
| **Salienza del soggetto** | Nitidezza del soggetto, Prominenza del soggetto, Posizionamento del soggetto, Separazione dallo sfondo |
| **Contenuto** | Confidenza del momento (i NULL vanno in fondo) |

### I miei gusti

Ordina per `learned_score` del ranker personale: ciò che ha appreso dai tuoi confronti A/B, dalle valutazioni e dalle decisioni di selezione. Un badge accanto all'ordinamento mostra la copertura (% di foto con un punteggio appreso) e l'accuratezza del ranker su dati tenuti fuori, così puoi giudicare quanto fidarti. Addestra o aggiorna il ranker con `python facet.py --train-ranker`.

Controllato da `viewer.features.show_my_taste` (predefinito: `true`). Stato del ranker: `GET /api/ranker/status`.

### Metriche nascoste in modalità commerciale

Con `licensing.mode` impostato su `commercial`, la galleria nasconde le metriche i cui modelli non possono essere usati commercialmente: LIQE, Aesthetic IAA, Face Quality IQA (a meno che OFIQ sia installato), DeQA (a meno che `licensing.allow_unclear` sia impostato) e Aesthetic V2.5. Spariscono i loro filtri, chip e opzioni di ordinamento; `/api/config` le elenca in `unavailable_metrics`. Nella pagina di regolazione dei pesi i loro cursori restano visibili ma disattivati, e il punteggio scarta e rinormalizza quei pesi. Riavvia la galleria dopo aver cambiato la modalità di licenza.

## Decisioni di revisione

Usa **Stato revisione → Da esaminare** nella galleria per smaltire le foto non ancora decise. Questa vista ordina per **Data di scatto, dalle più vecchie**; puoi invertirla o restringerla per data, cartella o album. Scegliere uno stato di revisione esce dalle ricerche semantiche e di foto simili.

- **Conserva** una foto che vuoi; **Rifiuta** una che non vuoi. Entrambe la tolgono da Da esaminare. Trova le foto conservate con il filtro di stato **Conservate**.
- Conserva è indipendente da preferiti e valutazioni a stelle.
- Conserva e **Reimposta decisione** sono nel dettaglio della foto, nel menu contestuale e nelle azioni di gruppo. Premi **K** (rimappabile, vedi [Scorciatoie da tastiera](#scorciatoie-da-tastiera-galleria)) per conservare la foto corrente. Nel dettaglio della foto, Conserva alterna.
- **Reimposta decisione** cancella Conserva e Rifiuta senza toccare stelle o preferito.
- Le decisioni sopravvivono a ricaricamenti, riavvii e nuove scansioni. Nelle installazioni multiutente appartengono all'utente corrente.
- Confermare un gruppo di selezione segna le sue foto conservate come Conservate. Valutazioni e preferiti esistenti non vengono convertiti in decisioni Conserva.

**Conteggi di avanzamento.** La galleria mostra i conteggi **da decidere**, **conservate** e **rifiutate** per l'intera cartella, album o ambito filtrato visibile, non solo per la pagina caricata. La percentuale è `(conservate + rifiutate) / totale`. Gli interruttori Stato revisione e Nascondi scartate non riducono il totale; gli altri filtri sì.

**Riprendere una coda.** **Rivedi le indecise** avvia una coda. **Continua revisione** riapre la tua coda Da esaminare più recente su questo browser alla prima foto indecisa rimasta.

- Il segnalibro è per browser e per identità connessa (fino a 20 identità). Non si sincronizza tra dispositivi.
- Cambiare i filtri non lo sostituisce, a meno che tu apra un'altra coda Da esaminare.
- Le code degli album usano i criteri salvati correnti dell'album.
- I gruppi temporanei di raffica/serie non vengono salvati come segnalibro, perché una nuova scansione può rinumerarli.
- Il logout cancella ogni segnalibro delle code di revisione su questo browser.

**Avvisi fluttuanti.** L'avanzamento della revisione, **Continua revisione**, l'avviso delle foto nascoste, l'avviso dei filtri attivi (con **Reimposta tutti i filtri**) e l'avviso di migrazione delle miniature si impilano in basso a destra.

- La × di ogni scheda la nasconde per la scheda corrente del browser. Ritorna in una nuova scheda, o quando l'avviso cambia (altro ambito, conteggio di nascoste cambiato, filtro aggiunto o rimosso).
- Per nascondere per sempre l'avanzamento della revisione, usa **Nascondi avanzamento revisione** / **Mostra avanzamento revisione** nel menu utente. È memorizzato per browser e nasconde anche il pulsante **Rivedi le indecise**.
- Dopo qualche secondo di inattività la pila si ripiega in una piccola pillola con il conteggio. Passaci sopra o cliccala per aprirla.

## Funzionalità della galleria

### Pile di foto manuali

Seleziona **2–1000 foto esplicite**, poi **Impila foto** nella barra di selezione o premi **S** per aprire l’editor a pagina intera in `/stacks/edit`. La selezione dell’intera vista non crea pile. S apre un’anteprima, senza salvare direttamente. Menu utente → **Personalizza le scorciatoie** cambia il tasto della galleria; il suggerimento, Aiuto e il riferimento `?` mostrano quello attuale. Se una configurazione precedente usa già S, viene mantenuta e Impila rimane **Non assegnato** finché non scegli un tasto libero. Servono permessi di modifica. Una foto appartiene a una sola pila per proprietario. La pagina centra un’anteprima con zoom sopra una striscia di miniature permanente. Fai clic su una miniatura o usa `←`/`→` per selezionare una foto, poi i suoi comandi di copertina, ordine o rimozione dalla pila. Pulsante zoom, rotellina o doppio clic mostrano i dettagli.

Usa **Cmd+Maiusc+S** o **Ctrl+Maiusc+S** per impilare subito le foto esplicite non impilate nell’ordine di selezione, con la prima come copertina. I membri di pile esistenti aprono l’editor. Il successo cancella la selezione salvata e Annulla la ripristina; annullamento o errore la conserva. Escape nell’editor torna alla galleria originale senza salvare.

**Rifiutare durante l’impilamento.** Seleziona una foto nell’editor a pagina intera o nella sua finestra e usa **Rifiuta** o **R**. La foto attiva nella camera oscura delle pile suggerite ha la stessa azione; aprila prima per scegliere la foto. Rifiuta salva subito la normale decisione, cancella Conserva, preferito e stelle ed esclude solo quella foto dalla pila proposta. Non elimina né modifica file originali. Conteggio e miniature attenuate mostrano le esclusioni. Annulla ripristina i valori precedenti e l’appartenenza alla bozza pertinente senza sostituire successive scelte di ordine o copertina; modifiche successive possono impedire Annulla. Le foto già rifiutate restano fino all’esclusione esplicita, senza un’altra decisione. Il raggruppamento attende Salva; uscire senza salvare non annulla Rifiuta.

Se le foto selezionate appartengono già a pile, **Unisci pile** è l’opzione iniziale: l’anteprima include gli altri membri. **Solo foto selezionate** sposta soltanto la selezione esplicita. L’editor mostra i conteggi selezionato e finale, i membri aggiuntivi e un riepilogo degli effetti; espandi i dettagli per ogni pila di origine. Almeno due membri rimasti conservano la pila; uno solo torna indipendente e un’origine vuota scompare. Escludere una foto dalla nuova pila la lascia nell’origine secondo le stesse regole. La pila finale e tutte le foto interessate hanno un limite di 1000 ciascuno; origini non disponibili o parzialmente visibili vengono rifiutate. Cambiare modalità conserva ordine, copertina ed esclusioni ancora applicabili.

Controlla l’anteprima aggiornata dal server e scegli **Impila foto** per salvare. La pagina rimane aperta per esaminare il risultato; la notifica offre **Annulla** finché è disponibile e le revisioni corrispondono. **Continua a modificare** carica una nuova anteprima prima di salvare di nuovo. **Torna alla galleria** ritorna alla galleria o all’album di origine con l’URL esatto e fa scadere l’Annulla precedente. Uscire senza salvare scarta il raggruppamento; un rifiuto esplicito persiste. Ricaricare il browser ripristina la selezione solo per lo stesso account, dopo una nuova autorizzazione; aprire l’URL senza una selezione valida offre un modo per tornare indietro.

Il badge o una foto impilata apre il visualizzatore con miniature, pulsanti precedente/successiva e contatore nell’ordine memorizzato. Le frecce restano nella pila. **Gestisci pila** apre una finestra di dialogo secondaria: fai clic su una miniatura o usa Sinistra/Destra per l’anteprima grande, scegli **Copertina**, riordina con i pulsanti freccia o rimuovi membri. Aprirlo da solo mantiene la normale modifica: i membri rimossi diventano indipendenti, togliere la copertina sceglie il primo membro rimasto e meno di due membri o **Separa la pila** scioglie la pila. **Aggiungi foto selezionate** da un’altra pila attiva esplicitamente l’anteprima di raggruppamento e le due modalità. Le modifiche di raggruppamento conservano file e valori di revisione; Rifiuta esplicito cambia subito i valori di revisione.

- Le azioni di valutazione, Conserva/Rifiuta, metadati, download, album ed eliminazione non espandono mai una pila implicitamente.

**Nella galleria.** Una pila si ripiega in una tessera; **Espandi tutte le pile** è una preferenza ricordata. Filtri e appartenenza agli album si applicano alle singole foto: la copertina compare se corrisponde, altrimenti compare il primo membro che corrisponde. Sfogliare una pila aggira il nascondimento automatico di raffiche/duplicati. Cronologia e mappa mostrano le singole foto.

**Selezione.** Selezionare una tessera ripiegata seleziona solo la foto mostrata. Apri la pila e usa **Seleziona tutti i N membri** per selezionarli tutti. **Seleziona tutta la vista**, la selezione per percentile e `target:view` dell'assistente includono ogni foto corrispondente, anche i membri ripiegati, e le azioni sull'intera vista mostrano prima il numero reale di foto. Nei riepiloghi API/assistente, `total` conta le tessere mostrate e `photo_total` conta le foto.

**Privacy e persistenza.**

- Le pile sono private del loro proprietario (l'installazione, in modalità utente singolo). Modificarle richiede l'accesso di modifica.
- Sono assenti dalle condivisioni pubbliche e dalle esportazioni della galleria. Una pila parzialmente visibile è in sola lettura.
- Le nuove scansioni mantengono copertina, ordine e appartenenza. I normali backup del database mantengono le pile.
- Le esportazioni complete del database della galleria omettono le pile e gli album intelligenti i cui filtri nominano una pila privata, oltre agli album intelligenti con filtri illeggibili (JSON non valido, annidamento eccessivo o oltre 1 MiB). Gli aggiornamenti incrementali mantengono gli album e le pile propri della destinazione.
- L'[importazione/invio di pile Immich](IMMICH.md#importare-e-inviare-pile-manuali) è un'operazione CLI separata.

**Pile suggerite** apre la revisione a pagina intera in `/culling?mode=stacks`, con i filtri correnti e il ritorno alla galleria o all’album di origine. Servono permessi di modifica. Esamina gruppi di duplicati e raffiche esistenti senza nasconderne i membri.

- Nella griglia, `↑`/`↓` selezionano un gruppo, **Invio** apre la camera oscura e **S** lo impila con la copertina proposta. Nella camera oscura, `←`/`→` selezionano una foto e **S** o **Invio** impilano con quella copertina. **X** salta il gruppo; impilare e saltare offrono Annulla.
- **Rifiuta** o **R** nella camera oscura esclude la foto attiva. Impila salva le foto rimaste e ne richiede almeno due. Salta ignora la proposta originale. Se ne restano poche puoi esaminare le escluse, cambiare gruppo, annullare, saltare o tornare indietro. Il rifiuto resta salvato dopo aver completato una proposta. Annullare Impila o Salta ne ripristina le esclusioni; un suggerimento successivo avvia una nuova bozza.
- La camera oscura conserva l’anteprima grande con zoom, la lente, il confronto e la striscia di miniature. **Z** attiva lo zoom, **P** l’evidenziazione della messa a fuoco, **F** lo schermo intero; **G** scorre le griglie di composizione; **Esc** torna alla griglia dei gruppi. **Modifica membri** apre una finestra secondaria; ridurre la proposta a una foto offre **Salta questa pila**.
- I gruppi saltati sono memorizzati per account finché non cambiano i membri. Sono esclusi gruppi con foto già impilate o fotogrammi di bracketing/panorama; i gruppi sovrapposti sono esclusi interamente, privilegiando i duplicati.
- L’intestazione conta le proposte caricate, non il totale della libreria. Ogni lotto contiene al massimo 20 proposte e 2000 foto (1000 per gruppo). Il successivo si carica automaticamente solo dopo aver impilato o saltato tutte le proposte caricate. **Ricarica i suggerimenti** ricarica lo stesso ambito; **Torna alla galleria** ritorna all’origine.
- Non disponibile negli elenchi fissati, Foto simili o ricerca semantica. Impila e Salta non cambiano decisioni di revisione né originali. Solo Rifiuta esplicito cambia i valori di revisione.

### Schede foto

- Miniatura con badge del punteggio. Passaci sopra per vedere dove si colloca il punteggio nella tua libreria ("Top 18% of the library").
- Tag cliccabili per un filtro rapido
- Avatar delle persone per i volti riconosciuti
- Badge della categoria
- Il clic destro (o Maiusc+F10) apre il [menu contestuale](#selezione-multipla-e-azioni-di-gruppo)

Nel dettaglio della foto, le metriche stanno in schede con icona: dati EXIF (se presenti), Qualità, Composizione (con salienza del soggetto), Tecnica e Istogramma. L'ultima scheda aperta viene ricordata. Ogni punteggio si trova accanto alla sua distribuzione nella libreria, con la barra della foto evidenziata; passa sopra una barra per vedere la posizione della foto e l'intervallo della libreria. La collocazione è calcolata sull'intera libreria, non sui filtri correnti, sulla più vicina di 20 barre.

### Selezione multipla e azioni di gruppo

Clicca le foto per selezionarle; Maiusc+clic seleziona un intervallo. In basso a sinistra compare una barra delle azioni con pulsanti a icona (passaci sopra per le etichette). Le azioni di gruppo richiedono la modalità di modifica.

- **Preferito** — segna tutte come preferite (cancella lo scarto)
- **Rifiuta** — segna tutte come scartate (cancella preferito e valutazione)
- **Valuta** — imposta o cancella una valutazione da 1 a 5 stelle
- **Aggiungi all'album** — aggiungi a un album esistente o nuovo
- **Modifica tag** — aggiungi o rimuovi un [tag manuale](#tag-manuali) su ogni foto selezionata
- **Seleziona tutto** — con una selezione vuota, seleziona ogni foto che i filtri trovano, non solo le pagine caricate. Con foto già selezionate, aggiunge quelle caricate e propone di estendere all'intera vista. Le azioni sull'intera vista confermano prima il numero esatto di foto.
- **Inverti** — sostituisce la selezione con il suo complemento. Da una selezione vuota è l'intera vista. Da una selezione non vuota resta tra le foto caricate: scegli le foto da conservare, inverti, rifiuta.
- **Confronta** — apri 2–4 foto affiancate con pan e zoom sincronizzati (scorri per fare zoom, trascina per spostare, doppio clic per reimpostare). I riquadri passano alla piena risoluzione quando ingranditi.
- **Copia nomi file** — copia i nomi file negli appunti. Una copia dell'intera vista chiede prima conferma; oltre 10 000 foto viene rifiutata.
- **Esporta** — scrive sidecar XMP accanto ai file (vedi [Esportazione per editor](#esportazione-per-editor))
- **Scarta in cartella** — copia le foto conservate, o sposta/cestina quelle scartate, in una cartella (vedi [Scarta in cartella](#scarta-in-cartella))
- **Elimina** — invia le foto al cestino del sistema (vedi [Elimina](#elimina)). Mostrato solo quando `viewer.cull.allow_trash` è attivo. Disattivato per una selezione "seleziona tutta la vista": seleziona le foto esplicitamente.
- **Scarica** — scarica le foto selezionate
- Cancella la selezione con Esc o il pulsante Cancella.

Doppio clic su una foto per aprirla.

**Menu contestuale.** Clic destro su una foto, oppure mettila a fuoco e premi Maiusc+F10 / il tasto Menu.

- Su una foto dentro una selezione di più foto, agisce sull'intera selezione con le azioni della barra (tranne Inverti e Seleziona tutto), inclusa **Modifica tag**.
- Su qualsiasi altra foto, agisce solo su quella foto e aggiunge Apri foto, Trova simili, Perché questo punteggio?, Scrivi metadati nel file e Assegna volto a persona (quando la foto ha volti non assegnati), secondo le rispettive condizioni.
- Selezionare una foto dal menu la rimuove soltanto dalla selezione.
- Non disponibile sui dispositivi touch-first (`hover: none` e `pointer: coarse`); usa invece il pannello Azioni.

### Tieni il top N%

Il controllo **Tieni top %** nella barra degli strumenti (modalità di modifica) seleziona l'intera vista filtrata in un solo passaggio. Imposta una percentuale. Facet ordina la vista secondo l'**ordinamento corrente** (aggregato, I miei gusti, Migliori scelte, nitidezza…), conserva la quota migliore e **seleziona il resto**. Rifiutale dalla barra delle azioni, dopo aver deselezionato quelle che vuoi risparmiare.

- Nulla viene spostato o eliminato; riempie soltanto la selezione. I rifiuti continuano ad addestrare I miei gusti.
- La selezione è limitata a 5000 foto. Su una vista più grande, restringi il filtro (album, data, persona…).
- Con i `hide_brackets` / `hide_panoramas` predefiniti, una serie di bracket o panorama conta come **una** foto.

### Elenco fissato dall'assistente

Quando un assistente collegato tramite [Assistenti IA (MCP)](AGENTS.md) ti mostra un elenco esatto di foto, la galleria lo visualizza nell'ordine dell'assistente. Una riga di stato dice quante foto sono state scelte; **Torna alla vista abituale** ripristina i tuoi filtri.

- Mentre l'elenco è mostrato, la barra dei filtri, i chip dei tag, gli avatar delle persone, **Trova simili** e le azioni legate ai filtri (come **Tieni il top N%**) sono nascosti. Cambiare album sostituisce comunque l'elenco.
- Mostrare un elenco cancella la selezione e il pannello laterale.
- Le scritture dell'assistente compaiono senza ricaricare: le schede modificate si aggiornano e le foto eliminate escono dall'elenco. Una foto spostata o cestinata da `cull_apply` resta. Compare un solo avviso "Assistant changed N photos" per ogni raffica di modifiche. Vedi [Aggiornamenti in tempo reale](AGENTS.md#aggiornamenti-in-tempo-reale).

**Chip Assistente attivo.** Mentre un assistente lavora nella tua scheda, un chip **Assistente attivo** compare nell'intestazione per qualche secondo dopo ogni scrittura o comando. Cliccalo per **Attività dell'assistente**: le ultime 50 azioni di questa sessione (perse al ricaricamento), con strumento, numero di foto e ora. Le azioni che nominavano foto hanno **Mostra le foto**. Quando l'assistente lo chiede, la scheda gli dice su quale foto si trova il cursore (`focused`) e che cosa hai fatto dalla sua ultima occhiata (`user_activity`). Nulla viene inviato spontaneamente. Vedi [Controllare la scheda aperta](AGENTS.md#controllare-la-scheda-aperta).

### Scarta in cartella

**Scarta in cartella…** nella barra delle azioni di gruppo (modalità di modifica) copia le foto conservate, o sposta/cestina quelle scartate, in una cartella di destinazione. Cestino significa il cestino del sistema, mai un'eliminazione permanente, e richiede `viewer.cull.allow_trash`.

- **Ogni esecuzione parte come esecuzione a vuoto.** Vedi un'anteprima prima che venga scritto qualcosa; sposta/cestina partono solo con un `dry_run=false` esplicito.
- **Il server sceglie i file dallo stato di ogni foto.** La copia agisce solo sulle conservate, sposta/cestina solo sulle scartate. Tutto il resto è riportato come `excluded_by_state`. Il client non può passare un elenco di file da eliminare.
- **I file collegati sono opzionali.** Rifiutare un JPEG non porta con sé il suo RAW, a meno che tu spunti **Includi RAW compagno / XMP** (`include_companions`).
- Su macOS e Windows, i file RAW collegati mantengono i nomi su disco, comprese le estensioni maiuscole; su Windows, anche i sidecar `.xmp`.

**Disponibilità di «Cestina gli scartati».** L'opzione "Cestina gli scartati" compare solo quando `viewer.cull.allow_trash` è attivo *e* il pacchetto `send2trash` è installato (`/api/config` riporta `cull.trash_available: true`). Altrimenti la finestra ne spiega il motivo: "the `send2trash` package is not installed" o "an administrator disabled trashing".

**Serie multi-scatto.** Con i `hide_brackets` / `hide_panoramas` predefiniti, la selezione contiene solo l'esposizione di base di un bracket o il fotogramma centrale di un panorama. Quindi, per impostazione predefinita, selezionare una serie agisce su **quel** solo file. Due caselle facoltative la estendono:

- **Includi RAW compagno / XMP** (`include_companions`) aggiunge il RAW e il sidecar `.xmp` dello stesso fotogramma.
- **Includi fotogrammi della serie** (`include_sequence_siblings`) aggiunge gli altri fotogrammi della serie, ma solo quelli il cui stato conserva/scarta corrisponde all'azione. I fotogrammi conservati non vengono mai cestinati perché un fratello è stato scartato. Un fotogramma che hai deselezionato non viene mai riportato dentro.
- L'anteprima riporta sempre quanti fotogrammi fratelli esistono (`sequence_siblings`). `matched` distingue "nessuno idoneo" da un risultato vuoto.
- Spostare o cestinare il capofila di una serie promuove un fratello rimasto, così la serie resta visibile.
- Per scegliere un sottoinsieme esatto di una serie, aprila prima con l'azione "apri questa serie nella galleria" del dettaglio foto. Quella vista mostra ogni fotogramma.

Una selezione legata ai filtri segue le stesse regole di filtro della galleria, Tipo di foto incluso. Una vista oltre 10 000 foto viene rifiutata invece che troncata, anche per un'esecuzione a vuoto: restringila (album, data, persona…) e riprova. Dettagli: [API.md](../API.md).

**Dove puoi scrivere.** Senza `viewer.export.allowed_target_dirs`, Facet scrive solo dentro le tue directory di scansione. Una sottocartella dell'albero delle foto (per es. `_rejected`) funziona senza configurazione. Per una cartella altrove, aggiungila a `viewer.export.allowed_target_dirs`. Vedi [Configurazione — Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto). In Docker/Podman i percorsi si risolvono **all'interno del container** — vedi [Distribuzione — Semantica dei percorsi nel container](DEPLOYMENT.md#semantica-dei-percorsi-nel-container).

**"Accesso negato" a ogni azione.** È un rifiuto deliberato: la cartella di destinazione non è consentita, oppure la tua sessione di modifica è scaduta. Controlla il campo `detail` della richiesta fallita nella scheda Rete del browser. Un vero problema del filesystem ha un aspetto diverso: successo parziale con un conteggio `errors` diverso da zero e l'errore del sistema operativo nel log del server.

### Elimina

**Elimina** nel dettaglio foto e nella barra di selezione invia i file direttamente al cestino del sistema (recuperabile, tramite `send2trash`). È separato da Scarta in cartella e dalla camera oscura `/culling`. Usa lo stesso flag `viewer.cull.allow_trash`.

- **La voce della libreria sparisce subito.** A differenza di Scarta in cartella, la riga della foto viene rimossa non appena il file è cestinato; non serve `--cleanup-missing-photos`. Anche un RAW collegato incluso che era stato scansionato come foto a sé sparisce.
- **Solo selezione esplicita.** Fino a 10000 percorsi; "seleziona tutta la vista" è disattivato.
- **Ambito.** Per impostazione predefinita solo il file indicato. **Includi RAW compagno / XMP** (`include_companions`) e **Includi fotogrammi della serie** (`include_sequence_siblings`) lo estendono, come in Scarta in cartella. Entrambi sono disattivati per impostazione predefinita.
- **Le esposizioni di base dei bracket sono protette.** Il fotogramma di base di un bracket (`sequence_ev_offset = 0`) viene rifiutato (`refused_bracket_lead`) a meno che includi i fratelli; allora l'intero bracket va insieme. Il capofila di un panorama eliminato promuove un fratello rimasto.
- **Risultati parziali.** Ogni percorso è riportato separatamente. Un capofila di bracket rifiutato non ferma il resto. Un file il cui tentativo di cestinare è fallito (`errors`) mantiene la sua riga.
- **File già assenti dal disco.** **Rimuovi anche le voci della libreria il cui file è già assente dal disco** (attivo per impostazione predefinita) rimuove anche quelle righe, riportate come `removed_missing`. Disattivato, tornano in `skipped` con le righe mantenute. Un percorso fuori dalle directory di scansione, o in una cartella mancante o vuota (un volume offline), resta sempre in `skipped`. Usa `--cleanup-missing-photos` per ripulire un'intera libreria.

Campi della risposta e codici di stato: [API.md](../API.md).

### Opzioni di visualizzazione

- **Modalità layout** — **Griglia** (schede uniformi) o **Mosaico** (righe giustificate che mantengono le proporzioni), a ogni larghezza dello schermo.
- **Dimensione miniatura** — cursore dell'altezza di scheda/riga (120–400px, salvato in localStorage)
- **Nascondi dettagli** — nasconde i metadati sulle schede (solo modalità griglia)
- **Tooltip** — come appaiono i dettagli della foto: **Pannello laterale** (predefinito), **Al passaggio**, **Al clic** o **Disattivato**.
  - Il pannello laterale mostra i dettagli completi nel cassetto di destra, organizzato come il dettaglio della foto. Segue passaggio e clic, quindi funziona sugli schermi touch. Mantiene l'ultima foto quando il cursore lascia la griglia.
  - Cliccare una foto tiene il pannello su di essa finché non premi **Deseleziona** (che deseleziona anche la foto). **Esc** fa lo stesso e cancella la selezione.
  - Il pannello condivide il cassetto con i filtri; aprire i filtri lo nasconde. Richiede una finestra larga almeno 1280px.
  - **Al passaggio** e **Al clic** mostrano un breve fumetto: categoria, aggregato e posizione, estetica, composizione, nitidezza, esposizione e una riga EXIF.
- **Personalizza i pulsanti della scheda** — riordina e mostra/nascondi i pulsanti nella riga al passaggio di una scheda. Sono disponibili nove azioni: trova simili, perché-questo-punteggio, scrivi metadati, assegna un volto, apri il gruppo di duplicati, la raffica, la serie bracket/panorama o la pila di foto, e apri la pagina della foto. I pulsanti di gruppo compaiono solo sulle foto che appartengono a un tale gruppo. I pulsanti del gruppo di duplicati e della pila di foto sono attivi per impostazione predefinita; gli altri sono facoltativi. Salvato per browser.
- **Nascondi occhi chiusi** — nasconde le foto con occhi chiusi rilevati
- **Solo occhi chiusi / Solo duplicati** — mostra solo le foto con occhi chiusi, o ogni membro di ciascun gruppo di duplicati. Gli interruttori di nascondimento sono sospesi per quella vista.
- **Mostra solo scartate** — elenca solo le tue foto scartate. Elaborale con seleziona-tutto e **Scarta in cartella**, o con **Cestina tutte le foto scartate (nel cestino del sistema)** in Selezione. Entrambi limitano l'ambito del filtro a 10.000 foto; restringi per data o album per averne di più, e disattiva i filtri che nascondono i gruppi per includere ogni fotogramma scartato. Disattivato mentre è selezionato uno stato di revisione.
- **Migliore della raffica** — mostra solo la foto con il punteggio più alto di ogni raffica
- **Migliore del bracketing** — mostra solo l'esposizione di base di ogni bracket. **Attivo per impostazione predefinita.** Indipendente da Migliore della raffica, perché il capofila di raffica di un bracket non è sempre la sua esposizione di base.
- **Migliore del panorama** — mostra solo il fotogramma centrale di ogni serie panorama o panorama HDR. **Attivo per impostazione predefinita.**
- **Scorrimento infinito** — le foto si caricano mentre scorri
- **Scorrimento rapido (virtualizzato)** — disegna solo le righe vicine all'area visibile, così lo scorrimento in profondità resta veloce. Attivo per impostazione predefinita. Disattivalo nella scheda Visualizzazione della barra laterale se incontri problemi di layout. La modalità griglia con dettagli mostrati si disegna sempre per intero. Salvato in localStorage (`facet_virtual_scroll`).

### Foto simili

Clicca **Simili** su una foto e scegli una modalità:

- **Visivo** (predefinito) — somiglianza pHash (70%) + somiglianza CLIP/SigLIP (30%). Quando due foto condividono solo uno dei due segnali, conta a peso pieno; le foto che non ne condividono nessuno non vengono mai elencate. Vengono restituite, pagina per pagina, tutte le corrispondenze sopra la soglia. Se la foto non ha nessuno dei due segnali, riscansionala con `--force` (un semplice `python facet.py <dir>` salta i file già elaborati).
- **Colore** — intersezione degli istogrammi (70%) + distanza di saturazione (10%) + distanza di luminanza (10%) + bonus monocromatico (10%). Pre-filtra per flag monocromatico e intervallo di saturazione.
- **Persona** — foto con le stesse persone, per `person_id` quando disponibile, altrimenti per somiglianza dell'embedding del volto.

Il **cursore della soglia di somiglianza** (0–90%) imposta quanto è rigoroso l'abbinamento (non in modalità persona). I risultati scorrono all'infinito.

### Chip dei filtri

I filtri attivi compaiono come chip rimovibili con i conteggi in cima alla galleria.

### Tag manuali

I tag manuali sono tag che digiti tu, conservati accanto ai tag IA. Sono memorizzati a parte (`photo_manual_tags`, non nella colonna `tags` della foto), quindi nuove scansioni e nuove assegnazioni di tag non li cancellano mai.

- **Dove compaiono.** Solo nel **dettaglio** della foto, come chip contrassegnati in modo diverso dai tag IA. Schede e tooltip mostrano i tag IA.
- **Chi può modificarli.** Gli utenti con modifica. Su un'installazione senza `viewer.edition_password` sono in sola lettura. I tag IA non si possono rimuovere.
- **Modifica di gruppo.** Seleziona le foto e usa **Modifica tag** (barra di selezione, pannello Azioni mobile o menu contestuale) per aggiungere o rimuovere un tag. Funzionano anche le selezioni dell'intera vista. Le foto che hanno già 50 tag manuali vengono saltate; `count` riporta le foto effettivamente modificate.
- **Formato.** I tag vengono ripuliti agli estremi, messi in minuscolo e con gli spazi compattati (NFC). Massimo 64 caratteri, massimo 50 per foto. Tag vuoti, virgole e caratteri di controllo vengono rifiutati. Un tag uguale a uno dei tag IA della foto non viene memorizzato.
- **Ricerca e filtri li raggiungono.** Il filtro dei tag, la ricerca testuale, la ricerca semantica (`/api/search`, tranne l'ambito testuale solo didascalie), il menu dei tag, le statistiche e le esportazioni sidecar/incorporate/Lightroom usano tutti tag IA + manuali. La ricerca testuale trova un tag manuale come frase intera.
- **Eccezioni.** Le capsule contano solo i tag IA. I tag manuali non influenzano mai punteggi, categorie o momenti narrativi.
- **Nascosti ai link di condivisione.** I visualizzatori dei link di condivisione non li vedono mai. Un album intelligente condiviso applica comunque il filtro salvato del proprietario.
- **Condivisi da tutti gli utenti.** In modalità multiutente qualsiasi utente con modifica può rimuovere un tag aggiunto da un altro.
- **Non annullabili.** [Annulla](#annulla) non li copre. Un tag rimosso può tornare da un sidecar; vedi [Regole di conflitto](INTEROP.md#regole-di-conflitto).
- **Tag importati.** `--import-sidecars` memorizza come tag manuali con origine `xmp` le parole chiave sconosciute dei sidecar (non tag IA, non nomi di persone).
- **Legati al percorso del file.** Spostare o rinominare un file ne fa perdere i tag manuali.

## Panorami e bracket di esposizione

I fotogrammi di un panorama sono pensati per essere uniti in un'unica immagine e quelli di un bracket per essere fusi; non sono scatti in concorrenza. Il solo rilevamento delle raffiche li raggrupperebbe e ne nasconderebbe tutti tranne uno, quindi Facet rileva queste serie separatamente.

**Nella galleria.** `Migliore del bracketing` e `Migliore del panorama` (entrambi attivi per impostazione predefinita) mostrano un fotogramma per serie: l'esposizione di base di un bracket, il fotogramma centrale di un panorama. Quel fotogramma porta una piccola icona accanto alla stella e al cuore: panoramica semplice, panoramica HDR o bracket di esposizione. L'icona compare solo mentre l'interruttore nasconde il resto della serie.

**Nella selezione.** Il menu della granularità offre `Bracketing di esposizione`, `Panorami` e `Panorami HDR` come feed propri, mai uniti a `Tutto`. Ogni fotogramma parte conservato e confermare una serie non registra coppie di confronto, quindi il ranker non viene addestrato su come è stata scattata una serie.

**Correggere una serie.** Il rilevamento sbaglia circa il 4% delle serie. Le correzioni sono persistenti: sopravvivono a ogni successiva esecuzione del rilevamento. Entrambe richiedono la modalità di modifica, almeno due fotogrammi, e si possono annullare dalla snackbar.

- **Falso positivo** (non è un panorama, o semplice vs HDR): usa il menu di correzione nella barra delle azioni del gruppo in Selezione.
- **Panorama non rilevato**: seleziona i suoi fotogrammi nella galleria e scegli *Segna come serie* → *Segna come un unico panorama*.

**Segnare un bracket non rilevato.** Per una scala di esposizioni rilevata come raffica ordinaria:

- Nella camera oscura, un gruppo di raffica semplice (nessun fotogramma già in un bracket o panorama) offre *Segna come bracket*.
- Nella barra di selezione della galleria, usa *Segna come serie* → *Segna come un unico bracket*.
- I fotogrammi devono formare una vera scala: almeno 2 fotogrammi, ciascuno con dati di esposizione (f-stop, tempo di posa, ISO) e una data di scatto, e due mai alla stessa esposizione. Altrimenti la marcatura viene rifiutata con un messaggio e non si salva nulla.
- Segnare fotogrammi che si sovrappongono a un bracket già segnato lo estende. La serie combinata deve comunque essere una scala valida.
- Il feed della camera oscura nasconde i fotogrammi scartati, quindi una marcatura dalla camera oscura non include mai uno scalino scartato.
- Un gruppo `bracket` offre invece *Rimuovi la correzione*.
- Se un fotogramma segnato sparisce o perde i dati di esposizione o di data, l'intera serie attende finché ogni membro non è di nuovo idoneo.
- **Segnare prevale sul rilevamento del panorama**: un panorama rilevato che contiene fotogrammi segnati viene scartato alla successiva esecuzione.

**Le correzioni si applicano alla successiva esecuzione del rilevamento.** Una correzione viene salvata subito e mostrata come in sospeso: un badge a orologio sulla tessera della galleria, un chip *Correzione in sospeso* in Selezione. La pagina di selezione mostra un banner con un pulsante **Rilancia il rilevamento**. Il filtro *Correzioni dei panorami* della barra laterale (solo modifica, nella scheda Revisione) elenca le correzioni in sospeso in tutta la libreria. *Rimuovi la correzione* ne rimuove una in seguito.

**Regolare il rilevamento.** La scheda Panorami sotto Confronta contiene le soglie calibrate: fotogrammi minimi, ampiezza minima della panoramica, intervallo più lungo e dispersione di esposizione HDR. Salvarle non cambia nulla finché non rilanci il rilevamento (il pulsante è accanto a Salva). Vedi [CONFIGURATION.md](CONFIGURATION.md#rilevamento-dei-panorami).

## Gestione delle persone

> Sfogliare le persone è aperto a tutti i visualizzatori; rinominare, unire, cambiare avatar e assegnare volti richiedono `[Edition]`.

### Filtro persona

Il menu a tendina elenca le persone con le miniature dei volti. Cliccane una per filtrare la galleria.

### Galleria della persona

Clicca il nome di una persona per vedere tutte le sue foto su `/person/<id>`. Nella pagina Gestisci persone, un doppio clic su una scheda (con nome, senza nome in «Da nominare» o ignorata) apre la galleria sulle foto di quella persona; i doppi clic su campo nome, casella e pulsanti restano a loro.

**Nominare dalla galleria.** Quando la galleria è filtrata su una persona (`?person_id=95`), la sua etichetta nella riga dei filtri attivi mostra il suo volto e il suo nome, o **Senza nome**, contornato come promemoria; la sua × (**Rimuovi dal filtro**) toglie la persona dal filtro. Per gli utenti in modalità modifica, prima della × ci sono due pulsanti. **Rinomina** (la matita) rinomina la persona sul posto: il campo nome mostra «Chi è? Scrivi o scegli un nome» per una persona senza nome e «Rinomina o unisci a…» per una con nome, i suoi suggerimenti mostrano volto, nome e numero di foto di ogni persona, e **Salva** o **Annulla** lo chiude (anche Esc annulla). Il nome viene sempre salvato per primo (`POST /api/persons/{id}/rename`); se altri gruppi lo portano già (maiuscole e spazi ignorati, che siano o no tra i suggerimenti), l'etichetta propone poi la stessa unione della pagina Gestisci persone (vedi **Rinomina** più sotto), e dopo un'unione la galleria passa alla persona mantenuta. **Altro** (⋮) apre il menu della persona: **Vedi tutte le foto di {name}**, **Trova altri volti di {name}** e **Ignora** (**Ripristina** per una persona ignorata). Quando le opzioni di nascondimento della galleria tengono fuori vista alcune foto della persona, gli avvisi della galleria ne indicano il numero, suddiviso tra foto di raffica, di occhi chiusi, duplicate, di bracketing e di panorama, così da mostrarle prima di nominare.

### Pagina Gestisci persone

In modalità modifica la pagina ha due schede, **Con nome (N)** e **Da nominare (N)**, e si apre sempre su **Con nome**. **Da nominare** elenca i cluster senza nome, ciascuno con un campo nome; **Con nome** raccoglie le persone con un nome, con quelle ignorate in una sezione richiudibile **Ignorate** in fondo. Gli utenti in sola lettura vedono solo la griglia delle persone con nome. I suggerimenti di nome, qui come nell'etichetta persona della galleria e nel menu dei volti della foto, mostrano volto, nome e numero di foto di ogni persona. Su **Da nominare** il menu di ordinamento offre **Numero di volti** e **Più recenti**. Quando non resta nessuno da nominare, la scheda mostra «Tutti hanno un nome. I nuovi volti da nominare compariranno qui.»

Aprila dal pulsante nell'intestazione o da `/persons`:

| Azione | Come |
|--------|--------|
| **Unisci** | Seleziona la persona di origine, clicca quella di destinazione, conferma |
| **Elimina** | Clicca il pulsante elimina sulla scheda della persona |
| **Rinomina** | Clicca il nome della persona per modificarlo in linea. Se altri gruppi portano già quel nome (maiuscole e spazi attorno ignorati), una conferma mostra un riquadro per persona (volto, nome, numero di volti), tutti selezionati, con la persona che verrà mantenuta evidenziata: la più grande fra le selezionate, che ne conserva la grafia. Deseleziona un omonimo, o annulla, per tenerlo separato. Un'unione non può essere annullata |
| **Dividi** | Apri i volti di una persona, seleziona un sottoinsieme, dividilo in una nuova persona |
| **Trova altri volti** | Il pulsante di ricerca sulla scheda di una persona, o **Trova altri volti di {name}** in un menu persona, elenca i volti che le somigliano, i più simili per primi, confrontati con il centroide della persona (`GET /api/person/{id}/possible_faces`). In **Quali volti includere**, tre chip mostrano ciascuno il proprio conteggio: **Senza gruppo** e **Gruppi senza nome**, attivi per impostazione predefinita, e **Persone con nome**, disattivato. Un volto che appartiene a una persona con nome porta un'etichetta **da {name}**, e spuntarne uno mostra un avviso: aggiungerlo lo sposta su questa persona. Sopra i volti, **Gruppi simili** elenca altri cluster il cui centroide somiglia a quello della persona (quelli senza nome, più quelli con nome mentre **Persone con nome** è attivo); ognuno mostra la sua foto, il nome o **Gruppo senza nome**, il numero di volti e **{percent}% simile**, con **Unisci tutto** per incorporare l'intero gruppo in questa persona. Unire un gruppo con nome chiede conferma, e un'unione non si può annullare. Ogni volto porta **Forte** (somiglianza del 50 % o più) o **Possibile**, con la percentuale, e **Quanto simile** fissa la soglia: un pulsante a barre di segnale che mostra `≥NN%` e apre il menu dei livelli, con cinque livelli, **Molto rigoroso** 60 %, **Rigoroso** 50 %, **Normale** 35 % (predefinito), **Ampio** 25 % e **Molto ampio** 20 %. Se nessun volto supera la soglia, la finestra mostra «Nessun volto somiglia a {name} (il più vicino: N%).» e propone **Prova Ampio** o **Includi le persone con nome**. Se una ricerca dovesse confrontare troppi volti, cerca solo tra i volti senza gruppo; se sono ancora troppi, chiede un **Anno** in cui cercare. **Seleziona i forti**, Maiusc+clic per un intervallo e Spazio sul volto attivo velocizzano la selezione, e il pulsante Aggiungi mostra quanti sono spuntati. L'aggiunta ricalcola il centroide, quindi il giro successivo è ordinato in base a ciò che hai appena confermato; i volti lasciati deselezionati non vengono riproposti finché la finestra resta aperta |
| **Ignora** | Ignorare un cluster (personale, sconosciuti): il pulsante ⊘ di una scheda, anche sulle schede «Da nominare». Le persone ignorate escono da elenco, «Da nominare», filtri, suggerimenti di unione e ricerca volti, e compaiono nella sezione richiudibile **Ignorate** in fondo alla scheda **Con nome**, con **Ripristina** (`GET /api/persons?hidden_only=true`). Usa lo stesso flag `is_hidden` di prima. Ignorare ha effetto subito e mostra per 10 secondi una notifica con **Annulla**, qui e in ogni menu persona. |

### Volti sulla foto

Nella vista foto compare un riquadro attorno a ogni volto rilevato mentre il puntatore è sulla foto, e passando su un volto se ne vede il nome (riquadro rosso: non ancora nominato). I riquadri seguono zoom e spostamento, e trascinare o fare doppio clic su un volto continua a spostare la vista o a reimpostare lo zoom. Il riquadro di un volto senza nome è anche tratteggiato, per non affidarsi al solo colore, e ogni riquadro ha un contorno scuro per restare visibile su qualsiasi sfondo. A meno che i riquadri siano su **Disattivato**, da tastiera Tab passa da un volto all'altro, ognuno annunciato con il suo nome (o come volto sconosciuto), e Invio o Spazio ne apre il menu. Su uno schermo touch, un tocco apre il menu di un volto solo mentre i riquadri sono mostrati (i riquadri sono su **Sempre**, oppure, tranne che su **Disattivato**, il volto è della persona su cui è filtrata la galleria); altrimenti toccare la foto non fa nulla al volto. In modalità modifica, un clic su un volto apre un menu: **Cambia persona…** (o **Dai un nome a questo volto…**) per scegliere una persona esistente o scrivere un nuovo nome, **Trova altri volti di …** per quella persona e **Non è …** per staccare solo quel volto da quella persona (`POST /api/face/{id}/unassign`); gli altri suoi volti nella foto restano suoi. I volti le cui dimensioni salvate non sono affidabili non vengono disegnati. I riquadri vengono da `GET /api/photo/faces`, che restituisce il `box` di ogni volto normalizzato all'inquadratura. Ogni volto che appartiene a una persona, con o senza nome, offre anche **Vedi tutte le foto di …** (o **Vedi tutte le foto di questo gruppo**), che apre la galleria filtrata su quella persona; funziona anche in sola lettura. Un pulsante della barra fa passare i riquadri fra tre stati, ricordati per browser: **Disattivato** (nessun riquadro, e i volti non si possono cliccare né raggiungere da tastiera), **Al passaggio** (il predefinito, come descritto sopra) e **Sempre** (tutti i riquadri e i nomi restano visibili). Se la galleria è filtrata su una persona, i suoi volti restano incorniciati con un tratto più spesso, a meno che i riquadri siano su **Disattivato**. **Usa come foto di …** rende il volto cliccato la foto della scheda; una persona che riceve volti senza avere una foto prende automaticamente il più affidabile. Nella galleria filtrata su una persona, ogni miniatura evidenzia il suo volto in rosso, per vedere a quale volto si riferisce un cluster prima di nominarlo. Nell'elenco **Persone** del pannello destro, un clic sull'avatar di una persona apre lo stesso menu di un clic sul riquadro di quel volto, anche con i riquadri su **Disattivato**; **Vedi tutte le foto di …** in quel menu apre la galleria.

### Segnare un volto non rilevato

In modalità di modifica, apri una foto e scegli **Segna un volto mancante**, anche se non sono stati rilevati volti. Disegna un rettangolo (o digita le coordinate), scegli una persona esistente o inserisci un nuovo nome, poi **Salva**. Annulla non salva nulla.

Salvare, modificare o rimuovere un volto manuale aggiorna i riquadri e le persone della foto senza riaprirla.

- Usa lo stesso editor per regolare, riassegnare o rimuovere una marcatura manuale.
- Le marcature manuali restano collegate alla loro persona attraverso nuove scansioni e sincronizzazione della galleria. Non addestrano il riconoscimento né cambiano i punteggi di qualità del volto.
- L'editor lavora sull'immagine originale, quindi le foto RAW e ruotate sono allineate. Senza l'originale puoi elencare e rimuovere le marcature, ma non disegnare.
- Una marcatura che non si può verificare appare come **Da verificare**. Le marcature di versioni di anteprima precedenti richiedono una revisione: apri l'originale, modifica e salva la marcatura.
- Un'immagine sostituita segnala le sue marcature. Un ritocco sottile o un piccolo ritaglio delle stesse dimensioni può passare inosservato. Scritture di metadati, rimontaggi e altri host mantengono aggiornate le marcature.
- L'editor riutilizza un fotogramma decodificato fino a 128 MiB; fotogrammi più grandi possono richiedere un'altra decodifica. Il limite è fisso.
- Le marcature eliminate restano eliminate durante la sincronizzazione successiva.
- Le modifiche risiedono nel database della libreria; originali e sidecar non vengono toccati.

> **Avviso:** una ricostruzione forzata del database della galleria sostituisce le modifiche presenti solo nella galleria, comprese le marcature manuali, con il database di origine. Esportale o fanne un backup prima. La normale sincronizzazione incrementale le mantiene.

L'impostazione legacy `viewer.performance.face_cache_size` viene ignorata e si può rimuovere.

## Avvio scansione

Avvia una scansione dal browser. Il pulsante Scansione compare quando **entrambe** le condizioni valgono:

- `viewer.features.show_scan_button` è `true` (viene fornito **`false`**).
- Hai accesso alla scansione: il ruolo `superadmin` in modalità multiutente, o una sessione di modifica su un'installazione a utente singolo con `viewer.edition_password` non vuota.

Su un'installazione aperta a utente singolo (`viewer.edition_password` vuota, il valore predefinito), nessuno può avviare scansioni dal browser. Eccezione: con `viewer.trusted_local_editing`, una sessione del browser locale fidata, o un assistente locale con un token di modifica completa, può avviare una scansione senza `show_scan_button` né password di modifica.

Il pulsante si trova nella galleria vuota (**Scansiona le foto per iniziare**) e in fondo all'intestazione (**Scansiona nuove foto**; barra inferiore sugli schermi piccoli). Entrambi aprono l'avvio scansione:

- Scegli una directory dall'elenco e avvia la scansione.
- Avanzamento in tempo reale e righe di output scorrono nella finestra. La galleria si aggiorna al termine della scansione.
- La scansione esegue `facet.py` in background; una scansione alla volta.
- L'elenco delle directory combina le `directories` di ogni utente, le directory condivise, i target di `path_mapping` e `viewer.scan_directories`. Imposta `viewer.scan_directories` (per es. `/data/photos`) così le installazioni a utente singolo e Docker hanno una destinazione.

Non serve alcuna GPU — vedi [Quale profilo si adatta al mio hardware?](INSTALLATION.md#quale-profilo-si-adatta-al-mio-hardware) e [Nessuna scheda grafica](INSTALLATION.md#nessuna-scheda-grafica). La scansione gira sulla macchina della galleria, quindi è più veloce se quella macchina ha una GPU.

Per rivalutare foto esistenti senza scansionare nuovi file, usa `POST /api/scan/recompute` (solo modifica) — vedi [Priorità delle categorie e contesti di punteggio](#priorità-delle-categorie-e-contesti-di-punteggio).

## Ricerca semantica

Digita una query come "sunset over mountains" e ottieni le foto corrispondenti. Il ranking combina la somiglianza degli embedding CLIP/SigLIP (70%) con la corrispondenza testuale FTS5 BM25 su didascalie e tag (30%).

- **Requisiti.** Le foto devono avere dati `clip_embedding` memorizzati (calcolati durante la valutazione). Esegui `database.py --rebuild-fts` per abilitare la parte testuale di didascalie/tag.
- **Modello.** Usa il modello di embedding del profilo VRAM attivo (SigLIP 2 per 16gb/24gb, CLIP ViT-L-14 per legacy/8gb), o quello tra `models.clip`/`clip_legacy` che corrisponde agli embedding memorizzati (vedi [CONFIGURATION.md](CONFIGURATION.md)).
- **Velocità.** Installare sqlite-vec accelera la ricerca; altrimenti Facet mantiene una matrice in memoria. La prima query su una libreria grande può richiedere alcuni secondi.
- **Soglia.** La soglia di corrispondenza è per impostazione predefinita `models.clip.search_threshold_percent` (`5%`) o `models.clip_legacy.search_threshold_percent` (15%), separata da `tag_threshold_percent`. Il cursore della galleria copre 0–50%; `search_threshold_default` di `/api/config` ne imposta l'inizio. Anche `0%` rifiuta la somiglianza negativa. Il 5% predefinito di SigLIP favorisce il richiamo — vedi `clip.search_threshold_percent` in [CONFIGURATION.md](CONFIGURATION.md).
- **Solo testo.** `scope=text` limita la query alle corrispondenze FTS5 letterali nel testo OCR/delle didascalie.
- **Funziona con ogni filtro della galleria**, compresi gli interruttori di nascondimento. Con i valori predefiniti, i membri nascosti di raffiche, duplicati, bracket e panorami, gli occhi chiusi e gli scarti restano nascosti.
- **Nessun limite ai risultati.** La galleria impagina i risultati e mostra il totale reale.
- **Ordinamento per pertinenza.** Con una query attiva, l'ordinamento predefinito è **Pertinenza** (migliore corrispondenza per prima). Cancellare la query ripristina l'ordinamento predefinito.
- **Selezione.** Seleziona tutto copre solo le foto caricate; l'ambito dell'intera vista qui non è disponibile.
- Controllato da `viewer.features.show_semantic_search` (predefinito: `true`).

I risultati riportano `similarity` (il punteggio combinato) e `embedding_similarity` (il coseno grezzo verificato rispetto alla soglia, assente nelle corrispondenze solo testo). I parametri della galleria `semantic_q`, `semantic_threshold` e `sort=relevance` sono documentati in [API.md](../API.md).

## Album

Organizza le foto in album con nome su `/albums`. Controllato da `viewer.features.show_albums` (predefinito: `true`).

### Album manuali

Crea album e aggiungi foto dalla galleria con la selezione multipla. Gli album supportano:
- Nome e descrizione
- Foto di copertina personalizzata
- Ordinamento personalizzato
- Sfoglia il contenuto dell'album su `/album/:albumId`

### Album intelligenti

Salva una combinazione di filtri (fotocamera, tag, persona, date, soglie di punteggio…) come album intelligente. Si aggiorna man mano che nuove foto corrispondono. I filtri sono memorizzati come JSON in `smart_filter_json`.

### Contesto di punteggio

Un album può portare un contesto di punteggio che decide quale categoria vince per le sue foto, indipendentemente dalla priorità globale — vedi [Contesti di punteggio](CONFIGURATION.md#contesti-di-punteggio). Impostalo dalla finestra dell'album (modalità di modifica).

- Impostarlo applica il contesto ai membri **attuali** dell'album. Una foto con una sovrascrittura manuale propria viene lasciata com'è.
- I membri di un album intelligente provengono dal suo filtro salvato, ignorando gli interruttori di nascondimento della galleria, quindi il conteggio può superare ciò che la vista dell'album mostra.
- Le foto aggiunte in seguito a un album manuale ereditano il contesto. Le nuove corrispondenze di un album intelligente no; imposta di nuovo il contesto.
- **Rimuovi contesto** (non è lo stesso che scegliere `default`) rimuove l'applicazione. Una foto ancora in un altro album con un contesto riceve invece quel contesto.
- Facet può suggerire un contesto dal momento narrativo dominante dell'album (tramite `suggest_from_moments` di ogni contesto). Non scrive nulla finché non confermi.
- Esegui un ricalcolo (`POST /api/scan/recompute`) perché il nuovo contesto cambi le categorie memorizzate.

Endpoint e conteggi delle risposte: [API.md](../API.md#albums).

### Esportazione portfolio

Trasforma un album manuale in una galleria HTML statica autonoma. Con `viewer.features.show_portfolio_export` attivo (predefinito `true`) e la modifica sbloccata, ogni scheda di album manuale ha **Esporta portfolio**. Scegli un titolo, la cartella di destinazione e se includere le didascalie.

- L'output contiene `index.html` (una griglia di miniature con lightbox incorporato, senza riferimenti esterni o a CDN, funziona offline), una cartella `assets/` di JPEG con nomi sequenziali (nessun percorso della libreria rivelato) e un `manifest.json`.
- Ogni foto usa l'originale, ridimensionato a `portfolio.max_edge`, o la miniatura memorizzata da 640px se l'originale non è raggiungibile.
- La cartella di destinazione deve essere nell'elenco consentito delle esportazioni (`viewer.export.allowed_target_dirs` più le directory di scansione, vedi [Configurazione — Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto)).
- Gli album oltre `portfolio.max_photos` (predefinito 500) vengono rifiutati.
- Riesportare riscrive solo i file propri dell'esportazione.

Vedi [Configurazione dell'esportazione portfolio](CONFIGURATION.md#esportazione-portfolio). Endpoint: `POST /api/albums/{album_id}/export-portfolio`.

### Condivisione foto

Condividi gli album tramite link con token. Visualizzare un album condiviso non richiede il login.

| Azione | Come |
|--------|--------|
| **Condividi** | Apri l'album, clicca il pulsante "Condividi" per generare un link condivisibile |
| **Revoca** | Clicca "Annulla condivisione" per invalidare il token di condivisione |
| **Visualizza** | I destinatari aprono il link per sfogliare l'album condiviso su `/shared/album/:id` |

### Revisione del cliente

Lascia che un cliente scelga i preferiti da una consegna. Con `viewer.features.show_proofing` attivo (predefinito `false`), un link di condivisione può funzionare in **modalità revisione**: il cliente lo apre, inserisce un PIN se impostato (`viewer.proofing.pin`), poi mette un **cuore** alle foto e lascia **commenti**.

- Le scelte del cliente sono memorizzate a parte (`album_client_picks`) e non toccano mai i tuoi preferiti o le valutazioni, né addestrano il ranker.
- Leggi le scelte da una finestra `[Edition]` sulla scheda dell'album.
- Le sessioni durano `viewer.proofing.session_minutes` (predefinito 24h) e terminano quando l'album non è più condiviso o la revisione viene disattivata.

Vedi [Configurazione — Revisione del cliente](CONFIGURATION.md#revisione-del-cliente).

## Critica IA

Spiega il punteggio di una foto come punti di forza, debolezze e suggerimenti. Controllato da `viewer.features.show_critique` (predefinito: `true`).

### Critica basata su regole

Disponibile su ogni profilo VRAM. Facet ricalcola il punteggio dalle metriche memorizzate della foto e dalla configurazione corrente, e mostra il calcolo.

- La **categoria** è quella che la formula corrente assegna (rispettando una sovrascrittura di categoria e il contesto di punteggio). Può differire dalla categoria memorizzata fino al successivo `--recompute-average`.
- Le **righe di scomposizione** mostrano ogni input 0–10 che lo scorer pesa (più alto è meglio, quindi rumore e gamma dinamica si leggono come qualità), con peso e contributo.
- Gli **adeguamenti netti e l'arrotondamento** (bonus, moltiplicatore degli occhi chiusi, clipping, penalità per rumore e sovrasaturazione, limitazione) riconciliano le righe con il totale del **Calcolo attuale**, mostrato accanto al **Punteggio salvato**.
- Le **condizioni rilevate** elencano gli occhi chiusi e una dominante del tono della pelle.
- Nitidezza, colore e nitidezza degli occhi usano lo snapshot dei percentili dell'ultimo `--recompute-average`. Una libreria solo scansionata usa i valori della scansione.
- Le **righe indicative**, mostrate solo se calcolate: forma e armonia cromatica (simmetria, equilibrio, entropia dell'orientamento dei bordi, complessità frattale, armonia cromatica di Matsuda; `--recompute-form`), chip degli attributi di distorsione (sfocatura da movimento, dominante di colore, eccessiva nitidezza…; `--recompute-distortions`) e una nota sul tono della pelle per i ritratti (`--recompute-skin-tone`). Spiegano la foto ma non cambiano l'aggregato.

Se il calcolo non è disponibile, viene mostrato solo il punteggio salvato, con il rimedio:

| Motivo | Rimedio |
|--------|--------|
| Schema obsoleto | `python database.py` |
| Snapshot di normalizzazione non disponibile | Riprova, poi `python facet.py --recompute-average` |
| Metriche memorizzate non valide | Riscansiona con `--force` |

La finestra distingue anche una foto *non ancora valutata* da una il cui *punteggio salvato è inutilizzabile*.

### Critica VLM `[GPU]` `[16gb/24gb]`

Usa il VLM configurato (Qwen3.5-2B o Qwen3.5-4B) per una critica sensibile al contesto. Richiede il profilo 16gb o 24gb, `viewer.features.show_vlm_critique` impostato su `true` (il valore predefinito) e una sessione di modifica per generarla. Senza modifica, viene mostrata solo una critica in cache e `vlm_available` è `false`. La finestra genera tramite `POST /api/critique/vlm` (solo modifica; le richieste simultanee per una stessa foto condividono una sola generazione); `GET /api/critique` legge soltanto la cache e non genera, non traduce e non scrive mai.

- Il prompt (`critique.vlm`) include la scomposizione del punteggio, i punteggi salvati e ricalcolati, le condizioni rilevate e l'EXIF.
- La risposta si legge come **Osservazione / Valutazione / Suggerimenti**. Viene messa in cache per foto (`photos.vlm_critique`), tradotta quando una sessione di modifica la apre nella lingua di destinazione (poi salvata e servita così com'è), e **Rigenera** la ricalcola. Senza una sessione di modifica vedi il testo non tradotto, a meno che non esista già una traduzione salvata.
- Funziona sulla miniatura memorizzata, quindi i file RAW vanno bene.

**Overlay visivo "perché questo punteggio".** Con `viewer.features.show_saliency_overlay` attivo (predefinito `true`), la finestra della critica ha **Mostra overlay**. Disegna la mappa di salienza BiRefNet come mappa di calore (`GET /api/saliency_overlay`), più i riquadri dei volti e i segnalini degli occhi dai punti di riferimento memorizzati (`GET /api/photo/face_markers`). I riquadri sono verdi per occhi aperti, ambra per occhi chiusi. La mappa di calore ha la risoluzione della miniatura, quindi è approssimativa. L'interruttore si nasconde sui profili che non possono produrre una maschera di salienza.

## Didascalie IA `[GPU]` `[16gb/24gb]` `[Edition]`

Ottieni una didascalia in linguaggio naturale per qualsiasi foto. Una sessione di modifica la genera alla prima richiesta; poi viene messa in cache nella colonna `caption`. Modifica le didascalie nel dettaglio foto (modalità di modifica). Un'installazione aperta in sola lettura non ne genera mai. `POST /api/caption` la genera (e la traduce); `GET /api/caption` restituisce solo la didascalia o la traduzione salvata e non genera, non traduce e non scrive mai.

Generazione e traduzione di gruppo dalla CLI:

```bash
python facet.py --generate-captions      # Genera didascalie per tutte le foto senza didascalia
python facet.py --translate-captions     # Traduce le didascalie nella lingua di destinazione configurata
```

La traduzione usa MarianMT su CPU (non serve la GPU). Imposta la lingua con `translation.target_language` (predefinito: `"fr"`). Supportate: francese, tedesco, spagnolo, italiano.

Controllato da `viewer.features.show_captions` (predefinito: `true`). Senza il profilo 16gb/24gb o un `vlm_backend` remoto, il pulsante Genera didascalia è nascosto e le critiche restano basate su regole.

## Ricordi ("In questo giorno")

Guarda le foto scattate nella data di oggi negli anni passati. Ricordi apre una presentazione a schermo intero in ordine casuale.

Controllato da `viewer.features.show_memories` (predefinito: `true`).

## Flussi di lavoro comuni

- **Selezionare una vacanza** — apri Capsule e trova la capsula `journey` del viaggio. Ogni capsula può essere salvata come album.
- **Eseguire una revisione giorno per giorno** — apri Cronologia e scendi in anni → mesi → giorni. Clicca un giorno per aprire la galleria filtrata su di esso.
- **Mostrare ciò che è nascosto** — la galleria nasconde per impostazione predefinita occhi chiusi, raffiche e duplicati non capofila. Quando qualcosa è nascosto, in basso a destra compare un avviso "N photos hidden by current filters · Show all".
- **Torna ai tuoi filtri** — l'icona delle foto nell'intestazione riporta alla galleria con i filtri, l'ordinamento e la posizione che avevi lasciato. Toccala due volte, o reimposta i filtri, per ripartire dai valori predefiniti.

## Vista cronologia

Sfoglia in ordine cronologico: gli anni scendono ai mesi, poi a un calendario dei giorni. Ogni tessera mostra il numero di foto e una foto di copertina. Clicca un giorno per aprire la galleria filtrata su quella data; ordina lì.

I cinque interruttori di nascondimento della galleria (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`) si applicano, con `viewer.defaults` come valori iniziali, quindi i conteggi delle tessere corrispondono a ciò che mostra la galleria. Quando qualcosa è nascosto, nella barra degli strumenti compare un pulsante `visibility_off` ("Some photos are hidden by your filters"); cliccalo per cancellarli tutti e cinque.

Apri `/timeline`. Controllato da `viewer.features.show_timeline` (predefinito: `true`).

## Vista mappa

Guarda le foto su una mappa Leaflet interattiva, raggruppate per livello di zoom, dalle loro coordinate GPS EXIF.

### Configurazione

Estrai le coordinate GPS dalle foto esistenti:

```bash
python facet.py --extract-gps    # Estrae lat/lng GPS dall'EXIF nel database
```

Le nuove foto ottengono le coordinate durante la valutazione.

Apri `/map`. Controllato da `viewer.features.show_map` (predefinito: `true`). Gli sfondi della mappa provengono da OpenStreetMap e richiedono una connessione a Internet, anche nell'app installata.

### Luoghi salvati e GPS manuale

**Trovare foto senza posizione.** Nei filtri, apri **Posizione** e attiva **Senza geolocalizzazione**. Può essere salvato in un album intelligente. Si disattiva quando avvii una ricerca semantica/di simili o scegli un raggio sulla mappa.

**Impostare la posizione di una foto.** In modalità di modifica, apri **Aggiungi posizione** o **Modifica posizione** su una foto. Cerca tra i **Luoghi salvati**, scegli una **Posizione recente**, posiziona un segnaposto o digita le coordinate. **Salva** la applica.

**Impostarne molte insieme.** Seleziona le foto e scegli **Imposta posizione** (barra di selezione, azioni mobili o menu contestuale).

- **Solo foto senza posizione** è attivo per impostazione predefinita; disattivalo per sostituire le posizioni esistenti.
- **Anteprima delle modifiche di posizione** mostra quante cambieranno o verranno saltate. Se nel frattempo cambia qualcosa, ripeti l'anteprima.
- Fino a 1000 foto visibili per lotto, comprese le selezioni dell'intera vista.

**Luoghi salvati.** Scegli un punto e usa **Salva questo luogo** con un nome (per es. "Work"), oppure aggiungi ai segnalibri il punto di una foto geolocalizzata. Rinomina o elimina dall'elenco; ciò non sposta le foto già assegnate. Ogni editor ha un elenco privato: fino a 100 luoghi salvati e 20 punti recenti.

**Le posizioni manuali restano.** Una posizione impostata nella galleria sopravvive a nuove scansioni e a una nuova estrazione EXIF, anche una cancellata. **Usa la posizione del file** elimina la sovrascrittura e rilegge il GPS del file (o lo cancella se il file non ne ha).

**Scrittura nei file.** Salvare non scrive mai il file immagine. Un'esportazione esplicita dei metadati scrive le posizioni manuali (e le cancellazioni esplicite) nel sidecar XMP: nella galleria o con `--export-sidecars`. L'incorporamento (**Scrivi metadati nel file**, o `--embed-originals`) scrive anche il GPS EXIF negli originali supportati. Vedi [INTEROP](INTEROP.md).

### Ricerca online di luoghi

Usa **Indirizzo o attività → Cerca online** per cercare un luogo con Photon (dati OpenStreetMap, © OpenStreetMap contributors). La query viene inviata solo quando clicchi **Cerca online** o premi Invio. Scegli un risultato per vederne l'anteprima, poi **Salva**. I luoghi salvati e le coordinate funzionano offline.

- `viewer.place_search_url` (predefinito `https://photon.komoot.io/api`) indica il provider. Usa un Photon self-hosted, o `""` per disattivare la ricerca.
- La demo pubblica non offre garanzie di disponibilità. Usa un solo worker della galleria con essa, poiché ogni worker ha il proprio limite di frequenza.
- Le query richiedono 3–200 punti di codice Unicode e restituiscono fino a cinque risultati entro cinque secondi, in una risposta di al massimo 64 KiB. Le etichette dei risultati sono limitate a 600 caratteri Unicode.
- Una cache per processo contiene 128 ricerche per 15 minuti. In modalità multiutente ogni account vede solo le proprie voci, ma la capacità di 128 voci e il limite del provider sono condivisi dall'intero processo.
- Facet attende almeno un secondo tra le chiamate al provider e non ne invia mai due insieme.
- Facet non registra le query. Configura il tuo reverse proxy perché non registri le stringhe di query.

## Capsule

Presentazioni a tema raggruppate per tema, luogo, persone e tempo. Apri `/capsules` e clicca una capsula per riprodurla.

### Tipi di capsula

Facet genera capsule dalla tua libreria:

- **Viaggio** — viaggi rilevati tramite clustering GPS, con nomi di destinazione da geocodifica inversa ("Journey to Rome — March 2025")
- **Momenti con [Persona]** — le migliori foto di ogni persona riconosciuta
- **Tavolozza stagionale** — foto raggruppate per stagione + anno
- **Collezione d'oro** — il top 1% per punteggio aggregato
- **Storia di colori** — gruppi visivamente simili tramite clustering di embedding CLIP
- **Questa settimana, anni fa** — "In questo giorno" esteso a ±3 giorni
- **Luogo** — cluster di foto geolocalizzate con nomi di luogo
- **Preferiti** — foto preferite raggruppate per anno e stagione
- **Basate su dimensione** — per fotocamera, obiettivo, categoria, modello compositivo, intervallo di lunghezza focale, ora del giorno, valutazione a stelle e combinazioni

### Presentazione

Clicca una scheda di capsula per avviare una presentazione:
- **Transizioni a tema** — scorrimento (viaggi), zoom (ritratti), kenburns (oro/stagionali), dissolvenza incrociata (predefinita)
- **Concatenamento automatico** — quando una capsula finisce, una scheda mostra l'anteprima della successiva
- **Mescola e riprendi** — le foto sono mescolate; la tua posizione è mantenuta per capsula
- **Raggruppamento adattivo** — le foto verticali sono mostrate affiancate per adattarsi allo schermo
- **Salva come album** — conserva qualsiasi capsula come album

### Aggiornamento

Le capsule ruotano secondo una pianificazione (predefinito: 24 ore). **Rigenera** nell'intestazione le aggiorna subito.

### Geocodifica inversa

Le capsule di luogo e di viaggio mostrano i nomi dei luoghi (per es. "Paris, France") usando il pacchetto offline `reverse_geocoder`. Nessuna chiamata API; i risultati sono messi in cache nel database.

Installa: `pip install reverse_geocoder`

### Configurazione

Vedi [Configurazione — Capsule](CONFIGURATION.md#capsules) per tutte le impostazioni.

## Vista cartelle

Sfoglia per directory su `/folders`.

- Le briciole di pane risalgono l'albero.
- Ogni cartella mostra come copertina la sua foto con il punteggio più alto.
- Clicca una cartella per aprirla, o una foto per aprirla nella galleria.
- Ogni scheda di cartella ha un'azione di filtro che apre la galleria limitata a quella cartella.
- In modalità multiutente vedi solo le tue directory.

### Filtro per cartella

La sezione **Cartella** della barra laterale dei filtri ha **Scegli cartella…**, un selettore che percorre l'albero. Applicarlo limita la galleria a quella cartella **e alle sue sottocartelle**. Compare come chip, si combina con altri filtri, sopravvive a un ricaricamento (parametro URL `path_prefix`) e si salva negli album intelligenti.

Restringe solo la griglia delle foto. I menu a tendina della barra laterale, i conteggi per tipo, le statistiche, la cronologia, la mappa e la ricerca restano su tutta la libreria.

## Finestra filtro GPS

Filtra le foto per posizione con un selettore su mappa:

- Clicca il pulsante del filtro di posizione per aprire la mappa.
- Clicca o trascina per impostare un punto centrale.
- Regola il cursore del raggio.
- Le foto entro il raggio compaiono nella galleria.
- Richiede le coordinate GPS (esegui `--extract-gps` se le foto hanno dati GPS EXIF).

## Suggerimenti di unione

Trova gruppi di persone che potrebbero essere la stessa persona. Apri `/merge-suggestions` oppure passa dalla pagina Gestisci persone.

- **Cursore della soglia di somiglianza** — più basso mostra più suggerimenti, più alto meno
- **Unisci** — accetta un suggerimento
- **Unione di gruppo** — unisce più suggerimenti insieme
- I suggerimenti scartati non vengono più proposti
- CLI: `python facet.py --suggest-person-merges`

## Esportazione per editor

Scrivi valutazioni, preferiti e scarti nei sidecar XMP così darktable, Lightroom e altri editor li recepiscono. Richiede la modalità di modifica.

- **Dalla galleria** — seleziona le foto, poi **Azioni → Esporta** scrive un sidecar accanto a ogni file.
- **Da un album** — esporta l'intero album come sidecar, oppure copia/collega simbolicamente i suoi file in una cartella (stesso elenco consentito di [Scarta in cartella](#scarta-in-cartella)). Gli album usano la loro appartenenza memorizzata, album intelligenti compresi.
- **Scrivi metadati nel file** — nel dettaglio foto, incorpora valutazione e parole chiave nell'originale (JPEG/HEIC/TIFF/PNG/DNG tramite exiftool) oltre a scrivere il sidecar. I file RAW proprietari non vengono mai modificati. Controllato da `viewer.features.show_embed_metadata` (predefinito: `true`).
- **Lightroom** (modalità di modifica) — **Download Lightroom manifest** salva `facet_manifest.json` per la selezione della finestra, per il passo **Facet: Apply ratings and flags...** di `facet.lrplugin`. **Import Lightroom state…** legge `facet_lightroom_state.json` dal menu **Facet: Export Lightroom State to Facet...** del plug-in (vince Lightroom per valutazione e pick/scarto) e riporta i conteggi di corrispondenti/non corrispondenti/modificati. Non serve eseguire `--import-lightroom`. Vedi [Lightroom Classic](INTEROP.md#lightroom-classic).

**Limiti e avanzamento.**

- Le esportazioni sono limitate a 10.000 foto, per selezioni, viste filtrate e album allo stesso modo. Un insieme più grande viene rifiutato prima che venga scritto qualcosa; restringi i filtri e riprova.
- Le esportazioni girano in background, con avanzamento e conteggi di scritti/saltati/errori. **Ferma dopo il file corrente** annulla tra un file e l'altro; i sidecar completati restano.
- Solo un lavoro sulla libreria alla volta. Mentre un'esportazione è in corso, scansioni, ricalcoli e riaddestramento automatico attendono o vengono rifiutati, e un'esportazione viene rifiutata mentre uno di essi è in corso.
- Chiudere la finestra smette di seguire l'avanzamento, non l'esportazione.
- Riapri Esporta per l'editor per vedere le tue 20 esportazioni più recenti. **Riprova i file incompleti** avvia un nuovo lavoro per i file falliti, saltati e non elaborati. Un file interrotto a metà scrittura può essere riscritto.

## Download

Scarica le foto dal dettaglio foto o dalla barra di selezione. Il menu di download per foto elenca i tipi disponibili per quella foto, compresi i profili darktable configurati:

- **Originale** (`original`) — il file così com'è (JPG/HEIF), o un RAW convertito in JPEG con lo stesso rendering mostrato dalla galleria. Un fotogramma di un bracket viene quindi scaricato senza correzione dell'esposizione — vedi [CONFIGURATION.md](CONFIGURATION.md#i-fotogrammi-di-un-bracketing-vengono-renderizzati-senza-correzioni).
- **darktable** (`darktable`) — il RAW collegato convertito con un profilo darktable con nome. Ripiega sull'originale se non c'è un RAW collegato.
- **RAW** (`raw`) — il file RAW collegato così com'è. Non disponibile negli album condivisi.

**Ritaglio social basato sulla salienza.** Con `viewer.features.show_social_export` attivo (predefinito `true`) e la modifica sbloccata, la barra di download del dettaglio foto ha un menu **Ritaglio social**. Elenca `social_export.presets` (quadrato 1:1, verticale 4:5, storia 9:16 per impostazione predefinita). Sceglierne uno scarica un JPEG a piena risoluzione ritagliato a quella proporzione e centrato sul soggetto. Il soggetto proviene dal riquadro del soggetto BiRefNet (`photos.subject_bbox`, da `--recompute-saliency`), altrimenti dai volti rilevati, altrimenti dal centro. Il tooltip del menu mostra quale è stato usato (`saliency` / `faces` / `center`).

Endpoint: [API.md — Download](../API.md#download).

## Selezione

La pagina di selezione (`/culling`, modalità di modifica) raggruppa scatti quasi identici così conservi il migliore di ciascuno e rifiuti il resto. Scegli la/le foto da conservare in ogni gruppo; confermare rifiuta le altre. Le conferme sono differite e si possono annullare (vedi [Annulla](#annulla)).

La **granularità** (il primo controllo della barra degli strumenti) sceglie come vengono raggruppate le foto:

- **Tutto** (predefinito) — raffiche e gruppi di simili uniti.
- **Raffiche** — foto scattate ravvicinate nel tempo.
- **Simili** — foto che si assomigliano a prescindere dal tempo, per somiglianza CLIP/SigLIP. Un cursore imposta il rigore.
- **Scene** — sequenze cronologiche per ora di scatto, ciascuna con l'intervallo di tempo e il momento narrativo principale in testa. Richiede `viewer.features.show_scenes`.
- **Bracketing di esposizione** — serie trovate da [`--detect-sequences`](COMMANDS.md), esposizione di base per prima, ogni fotogramma con il badge della sua compensazione (`-2 EV` … `+2 EV`).
- **Panorami** — panoramiche trovate da [`--detect-panoramas`](COMMANDS.md), in ordine di scatto, fotogramma centrale segnato.
- **Panorami HDR** — panoramiche con una dispersione di esposizione oltre `hdr_min_span_stops`. Una serie HDR su treppiede compare prima sotto **Bracketing di esposizione** e si sposta qui (come `hdr_panorama`) quando il passaggio dei panorami riconosce la panoramica. Se non la riconosce mai, resta un bracket.

**Serie da conservare intere.** Bracketing di esposizione, Panorami e Panorami HDR non fanno parte di **Tutto**. Ogni fotogramma parte conservato e confermare non registra coppie di confronto. Il doppio clic ("conserva solo questa") lì non fa nulla. Questi feed ignorano gli interruttori `hide_*` della galleria e mostrano ogni fotogramma. Per eliminare le esposizioni laterali, usa il taglio dei bracket della selezione automatica (sotto).

Un gruppo che resta con meno di 2 fotogrammi dopo la rimozione delle foto già scartate esce dal feed.

**Ordinamento.** La **modalità di ordinamento** (più facili prima, più ridondanti, migliori, più recenti, richiedono confronti, **più vecchie prima**) sta accanto alla granularità, con un pulsante freccia che la inverte. Più vecchie prima ordina per ora di scatto anche le foto *dentro* ogni gruppo, utile per bracket e panoramiche.

Granularità, ordinamento e categoria persistono in `localStorage`. I controlli che non si applicano sono nascosti (nessun ordinamento o soglia in modalità scene; nessun pulsante di ambito senza album manuali). Sugli schermi piccoli la barra degli strumenti diventa una barra inferiore scorrevole.

**Cestina tutte le foto scartate (nel cestino del sistema).** Questo pulsante della barra degli strumenti mostra l'anteprima di ogni foto scartata visibile a te in tutta la libreria, fotogrammi nascosti compresi. Ignora album, data e filtri della galleria. **Applica** invia i file al cestino del sistema della macchina di Facet. A differenza di **Elimina**, righe della libreria e decisioni restano, per I miei gusti.

- Richiede l'accesso di modifica, `viewer.cull.allow_trash` e il supporto al cestino.
- Limitato a 10.000 foto. Per averne di più, usa Mostra solo scartate nella galleria, restringi per data o album e usa Scarta in cartella → Cestina gli scartati a lotti. Disattiva i filtri che nascondono i gruppi per includere ogni fotogramma scartato.
- I file RAW/XMP collegati sono opzionali.
- Se i file risolti, le opzioni o la destinazione sono cambiati dall'anteprima, Applica viene rifiutato; ripeti l'anteprima. Il controllo confronta nomi di file e impostazioni, non il contenuto dei file, e non blocca i file.
- Un errore del filesystem a metà lascia cestinati i file già completati; la finestra resta aperta per una nuova anteprima.
- Nei container, cestino e recupero dipendono dal filesystem del server.

> **Avviso:** su una libreria condivisa, Cestina tutte le foto scartate usa solo *i tuoi* rifiuti. Cestina i file condivisi anche se un altro utente li ha conservati, preferiti o valutati. Controlla l'anteprima.

**Selezione delimitata.** Restringi la camera oscura con parametri URL: `?group_by=scene` per le scene, `?album=<id>` per un album, `?from=&to=` per una finestra di ora di scatto (testo EXIF o date ISO come `2026-06-01`). Un banner mostra l'ambito con **Esci dalla scena**. Le raffiche che superano il bordo della finestra mostrano comunque tutti i loro fotogrammi.

**Intervallo di date.** Il pulsante **intervallo di date** (icona `date_range`) offre **Ultimi 7 giorni**, **Ultimi 30 giorni**, **Quest'anno**, **Anno scorso**, **Intervallo personalizzato...** e **Tutte le date**. Le date sono mostrate come dd/MM/yyyy.

- Si combina con l'ambito dell'album. Le foto senza data di scatto escono da un intervallo con date.
- I preset si risolvono quando scelti, quindi un "Ultimi 7 giorni" nei segnalibri è una finestra fissa.
- L'intervallo vive solo nell'URL (`?from=2026-07-01&to=2026-07-31`), non in `localStorage`.
- Cambiarlo ricarica il feed: una conferma in sospeso viene eseguita, le selezioni non confermate e i salti vengono scartati.

**Riga I miei gusti.** Ogni conferma registra confronti `source='culling'` che addestrano il ranker personale. La finestra Aiuto (menu utente → Aiuto) mostra "My Taste · N comparisons" (`GET /api/ranker/status`) ed elenca le scorciatoie della selezione.

**Profili per genere.** Il selettore **Profilo** applica un preset di genere che imposta in un colpo solo rigore, budget di foto conservate, soglia di somiglianza e le soglie dei volti per occhi chiusi / espressione scarsa. Lo sport conserva solo la più nitida di una raffica, i matrimoni conservano più varianti con occhi aperti, concerti e fauna selvatica allentano le soglie sui volti. La scelta e il cursore del rigore persistono in `localStorage`. Cambiare a mano una manopola mostra "Custom". I preset stanno in [`cull_profiles`](CONFIGURATION.md#profili-di-scarto-per-genere) (`GET /api/culling/profiles`).

### Selezione automatica

**Selezione automatica** nella barra degli strumenti seleziona un intero ambito in un solo passaggio.

1. Scegli l'ambito: tutti i gruppi, o solo raffiche / simili / scene, facoltativamente un album o una finestra di date.
2. Imposta il **rigore** (più alto ne conserva meno per gruppo).
3. Anteprima. Ogni gruppo conserva la sua foto migliore più tutto ciò che rientra nel margine di rigore (almeno un minimo per gruppo), e rifiuta il resto.
4. Conferma. I rifiuti vengono registrati, le foto conservate sono segnate come **Conservate**, e I miei gusti impara da essi.

- L'anteprima è un'**esecuzione a vuoto**: non viene scritto nulla.
- Un album **Highlights** facoltativo raccoglie la migliore foto di ogni gruppo con punteggio di almeno `auto_cull.highlights_min`.
- Un badge "foto migliore in questo gruppo" segnala i gruppi in cui la selezione automatica conserverebbe un fotogramma diverso dal capofila attuale.
- Quando una head di ranking delle foto da conservare è addestrata e supera il suo vincolo di accuratezza, sceglie lei la foto da conservare (`keeper_prob`). Altrimenti lo fa l'euristica abituale.
- Il pulsante è nascosto nelle granularità da conservare intere. In un ambito misto, i bracket vengono decisi per primi.
- Si configura con il blocco [`auto_cull`](CONFIGURATION.md#auto-cull) (`POST /api/culling/auto`). Eseguila dal terminale con `python facet.py --auto-cull` — vedi [Selezione da terminale](COMMANDS.md#selezione-da-terminale).

**Il taglio dei bracketing ridondanti** (`trim_brackets`, disattivato per impostazione predefinita) è l'unico modo in cui la selezione automatica riduce una serie. Quando l'esposizione di base di un bracket non satura né le ombre né le alte luci, i fotogrammi laterali non aggiungono nulla, quindi si conserva solo il fotogramma di base. Le serie la cui saturazione di base non è mai stata misurata vengono lasciate stare.

### Modalità piano dell'assistente

Quando un assistente collegato tramite [Assistenti IA (MCP)](AGENTS.md) mostra l'anteprima di una selezione automatica (`auto_cull`, o `ui_show_culling_plan`), la tua scheda aperta carica quel piano su `/culling`. È la normale camera oscura (lente `Z`, confronto 2-up / 4-up, peaking), con le foto da conservare del piano preselezionate.

- Un banner dice **Piano dell'assistente · x/y confermati · Esci**.
- Ogni gruppo ha un chip come **#3 · motivo · suggerito: tenere 2 / scartare 1**. Un chip blu nell'intestazione è la nota dell'assistente sul gruppo.
- Un punto su un fotogramma significa che l'hai cambiato rispetto al piano.
- Un badge tratteggiato **Assistente: tenere** / **Assistente: scartare** è il suggerimento dell'assistente, con il motivo nel tooltip. Cliccalo (o Invio/Spazio) per applicarlo; confermi comunque tu il gruppo.
- Conferma gruppo per gruppo come al solito, con il conto alla rovescia e **Annulla**. Le conferme in modalità piano non aggiungono mai a un album highlights.
- Un gruppo di raffica o di simili confermato esce dal piano. Un gruppo di scene confermato non viene registrato, quindi la prossima anteprima può riproporlo.
- Confermare una raffica rifiuta solo i membri mostrati; i membri fuori dalla finestra di album o date non vengono toccati.
- Ordinamento e soglia sono bloccati. Muovere il cursore del rigore o cambiare l'**intervallo di date** ripianifica; le tue inversioni e i gruppi confermati si mantengono. **Tutte le date** può raggiungere il limite del piano (`plan_truncated`).
- **Esci**, o cambiare raggruppamento, ambito od ordinamento, esce dalla modalità piano. Lasciare `/culling` e tornare la ripristina; ricaricare la scarta.
- Se la libreria è cambiata dopo l'anteprima, un avviso dice che il piano è obsoleto. I gruppi troppo grandi vengono lasciati fuori e contati in un avviso.

L'assistente legge il tuo avanzamento con `ui_get_context` (`culling`: gruppi confermati, in sospeso e modificati) e non applica nulla dalla scheda stessa. Vedi [Modalità piano su `/culling`](AGENTS.md#i-risultati-compaiono-nella-tua-scheda).

### Schermo intero

Premi **`F`** (o l'interruttore nell'intestazione) per rivedere a schermo intero senza elementi dell'app. Premi `F` o `Esc` per uscire.

Premi **`S`** (o il pulsante pila nell'intestazione) per impilare il gruppo aperto con il fotogramma a fuoco come copertina. Le decisioni restano intatte e viene offerto Annulla. Non disponibile per gruppi con fotogrammi di bracket o panorama, o con una foto già in una pila.

### Lente / zoom con tasto Z

Premi **`Z`** nella vista singola per attivare una lente (adatta ↔ 2×; rotella o `+`/`-` fino all'800%). Ingrandendo oltre l'adattamento, il riquadro carica `/image` a piena risoluzione, così giudichi la messa a fuoco sui pixel reali. Le miniature sono da 640px e la vista adattata è un rendering fino a 1920px; la lente va oltre.

- Sulla striscia di contatto delle Scene, `Z` attiva una lente d'ingrandimento al passaggio con un cursore di zoom.
- I riquadri mostrano prima la miniatura memorizzata, poi passano al rendering nitido. I fotogrammi successivo e precedente vengono precaricati (tranne con il risparmio dati attivo).
- Un rendering che non riesce a partire entro 5 s viene sostituito dalla miniatura per 60 secondi.

**Lente al passaggio del mouse della camera oscura.** Una lente d'ingrandimento rotonda segue il cursore sul fotogramma principale, su ogni riquadro di confronto e sui primi piani dei volti, mostrando pixel a piena risoluzione. Un interruttore nella barra degli strumenti la attiva o disattiva (attiva per impostazione predefinita, salvata per browser). Si ferma mentre il fotogramma è ingrandito oltre l'adattamento, funziona a schermo intero e segue `←`/`→`.

### Badge per volto

Nel lightbox di selezione, ogni volto porta i propri badge: occhi aperti/chiusi, espressione scarsa e confidenza del rilevamento. Puoi vedere quale volto di una foto di gruppo ha gli occhi chiusi. Recuperati per gruppo con `POST /api/culling-group/faces`.

**Pannello dei volti.** I ritagli dei volti sono colorati verde / arancione / rosso in base ai punteggi di occhi aperti e sorriso.

- I cursori **Occhi** e **sorriso** regolano ciò che conta come occhi chiusi o espressione debole. Partono da `face_detection.eyes_closed_max` e `face_detection.poor_expression_min` (entrambi predefiniti `4.0`).
- **Dimensione** (64–256 px, a passi di 16, predefinita `112px`) ridimensiona i ritagli. I valori dei cursori sono salvati per browser.
- Dopo aver usato un cursore con il mouse, i tasti freccia tornano alla camera oscura (`←`/`→` fotogramma, `↑`/`↓` conserva/rifiuta). Usa Tab su un cursore per regolarlo da tastiera.

**Striscia di primo piano del soggetto (gruppi senza volti).** Per i gruppi senza volti significativi (fauna selvatica, macro, prodotti), la camera oscura mostra affiancato il soggetto principale di ogni fotogramma, ritagliato dal riquadro del soggetto BiRefNet. Ogni ritaglio ha un badge di nitidezza (10 = la più nitida del gruppo) e un anello verde / ambra / rosso. Clicca un ritaglio per saltare a quella foto. Nessun modello viene eseguito (`POST /api/culling-group/subjects`). Per una libreria esistente, esegui prima `python facet.py --recompute-saliency` (GPU); fino ad allora la striscia non compare.

**Soggetto chiave (bersaglio dello zoom + persona principale).** Ingrandire (**`Z`**, doppio clic o il primo passo della rotella) atterra sul soggetto chiave del fotogramma invece che al centro: il suo volto migliore, o il riquadro del soggetto se non ne ha. Dopo che hai spostato o ingrandito tu un fotogramma, Facet smette di reinquadrarlo. Una persona con nome che vince riceve una pillola ambra con il nome nella striscia dei volti. Le persone con nome a media distanza battono sconosciuti più grandi; un volto minuscolo sullo sfondo non vince. Nulla viene memorizzato. I riquadri sono frazioni del fotogramma intero (`normalized_frame_xyxy`). Endpoint: `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Confronto sincronizzato (2-up / 4-up).** I pulsanti Singola / Confronta 2 / Confronta 4 dell'intestazione cambiano vista. In modalità confronto tutti i riquadri condividono un unico pan/zoom, così confronti lo stesso identico ritaglio. Alla misura adattata ogni riquadro mostra `/thumbnail?size=1920`; ingrandito, carica `/image` a piena risoluzione. Il pizzico touch non è ancora collegato; usa la rotella del mouse. Il doppio clic alterna adatta ↔ zoom.

**Scorri per mantenere o rifiutare (tocco).** Su un dispositivo touch, trascina il fotogramma a destra per conservare o a sinistra per rifiutare. Si inclina e si tinge di verde (KEEP) o rosso (REJECT).

- Oltre il 35% della larghezza (almeno 48px), rilasciare conferma la stessa decisione di `↑` / `↓` e passa al fotogramma successivo. Prima di quel punto, torna indietro.
- Un trascinamento verticale viene ignorato.
- Ogni scorrimento mostra **Annulla**, che ripristina la decisione e torna a quel fotogramma.
- Solo nella vista singola, alla scala adattata, con un dito o uno stilo. Un suggerimento di una riga resta finché non viene chiuso.

**Anteprima dell'aspetto elaborato.** Nella vista singola, il menu **tavolozza** elenca "Originale" più ogni stile darktable configurato, così puoi selezionare sull'aspetto sviluppato.

- Facet renderizza l'originale tramite darktable-cli (`--style`, limitato a `preview_max_edge`). In caso di errore torna a Originale.
- Lo stile resta per il gruppo corrente e si azzera quando riapri la camera oscura.
- Mostrato solo quando uno stile è configurato **e** darktable-cli viene trovato. Gli stili devono esistere nella configurazione darktable dell'utente che esegue la galleria.
- I rendering sono messi in cache su disco.
- Endpoint: `GET /api/photo/cull_preview?path=&style=` (modifica). Configura tramite [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#decodifica-raw).

## Vista Scene

Una vista in **sola lettura** della libreria come scene cronologiche, in ordine di racconto con intestazioni di data/momento e una lente al passaggio. Aperta a **tutti gli utenti autenticati**.

- Una nuova scena inizia quando passano più di `scenes.gap_minutes` tra gli scatti (ampliato sugli shooting rarefatti). Le sequenze molto lunghe vengono divise.
- Aprila dall'azione **Mostra le scene di questo album** di un album nella griglia Album; un selettore cambia album. Non c'è una voce Scene nella navigazione principale.
- Ogni scena ha un pulsante **Seleziona questa scena** solo per la modifica che apre [Selezione](#selezione) su quella scena (`/culling?group_by=scene&album=&from=&to=`).
- Con i momenti narrativi calcolati, ogni scena ha come titolo il suo momento principale, e `scenes.split_on_moment_change` può dividere una sequenza dove il momento cambia.
- Le scene più piccole di `scenes.min_size` vengono omesse; si caricano al massimo `scenes.max_photos` foto.

Controllato da `viewer.features.show_scenes` (predefinito: `true`). Vedi [Configurazione — Scene](CONFIGURATION.md#scenes) per `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` e `adaptive_k`.

## Momenti narrativi

Facet etichetta ogni foto con l'attività che mostra. Il vocabolario **general** predefinito: celebration, dining, beach, water activity, mountains, nature & wildlife, cityscape, travel landmark, concert, sports, group gathering, portrait, children, pets, nightlife, ceremony, scenic landscape, snow & winter, home indoor, road & vehicle, oppure `other`. Un vocabolario `wedding` è disponibile come genere facoltativo.

- Gira in locale, senza un passaggio di modello aggiuntivo: la didascalia IA di ogni foto viene confrontata con i prompt testuali di ogni momento (si usa l'embedding dell'immagine quando non c'è una didascalia). La regolarizzazione lungo la cronologia corregge le letture errate isolate.
- Un tie-breaker VLM facoltativo (16gb/24gb) ricontrolla i fotogrammi a bassa confidenza.
- **Viene eseguito automaticamente al termine di ogni scansione.** Il primo passaggio su una libreria esistente codifica ogni didascalia (GPU consigliata). Rietichetta tutto con `python facet.py --recompute-moments`.
- I momenti compaiono come titoli delle scene e come filtro della galleria (`GET /api/photos?narrative_moment=beach`, opzioni da `GET /api/filter_options/narrative_moments`).
- Il vocabolario è configurabile — vedi [Configurazione — Momenti narrativi](CONFIGURATION.md#narrative-moments).

**Confidenza del momento.** Ogni etichetta ha una confidenza (`narrative_moment_confidence`). Le etichette sotto `viewer.moment_confidence_min` (predefinito `0` = mai attenuare) appaiono attenuate con "(uncertain)" nelle intestazioni di Scene e Selezione e nel tooltip. La confidenza è anche un ordinamento (**Confidenza del momento**, sotto Contenuto) e un filtro a intervallo 0–1 (`min_moment_confidence` / `max_moment_confidence`, sezione **Momenti** della barra laterale).

## Pulizia degli scarti

Una coda di revisione rapida per screenshot, documenti scansionati, ricevute, meme e diapositive. Esegui `python facet.py --detect-junk` (viene eseguito anche dopo ogni scansione) per riempire `junk_kind`. Vedi [Configurazione — Pulizia degli scarti](CONFIGURATION.md#junk-sweep).

Apri **Pulizia** nella navigazione (`/junk`, solo modifica):

- **Chip di filtro per tipo** — "Tutti i tipi" più un chip per tipo con il suo conteggio (`GET /api/filter_options/junk_kinds`).
- **Conteggio candidati** — scende man mano che decidi.
- **Conserva** — toglie la foto dalla coda **per sempre** (`not_junk`); le successive esecuzioni di `--detect-junk` la saltano.
- **Rifiuta** — segna la foto come scartata (non viene eliminato nulla).
- **Rifiuta tutto** — rifiuta ogni candidato caricato, dopo conferma.
- **Lente** — premi **`Z`** (o l'interruttore nella barra degli strumenti) per ingrandire il testo fine.

Le foto scarto restano visibili nella galleria normale. Filtrale con `?junk_kind=<kind>` o `?junk_kind=any` (esclude `not_junk`).

Controllato da `viewer.features.show_junk_sweep` (predefinito: `true`).

## Modalità di confronto a coppie

Ordina le foto giudicandone due alla volta; i voti alimentano la regolazione dei pesi. Apri `/compare` (pulsante Confronta nell'intestazione). Richiede una `edition_password` non vuota (utente singolo) o il ruolo `admin`/`superadmin` (multiutente).

### Scheda Confronto A/B

Scegli un vincitore, segna un pareggio o salta. Una barra di avanzamento conta fino a 50 voti, con i totali di vittorie A/vittorie B/pareggi. Un filtro di categoria delimita la sessione; un menu a tendina di strategia sceglie le coppie:

| Strategia | Descrizione |
|----------|-------------|
| `learning` | Predefinita. Prima coppie diverse, poi le coppie su cui il ranker personale è più in disaccordo (le più informative) |
| `uncertainty` | Foto con punteggi simili (le più informative) |
| `boundary` | Intervallo di punteggio 6–8 (zona ambigua) |
| `active` | Foto con meno confronti (garantisce la copertura) |
| `random` | Coppie casuali (riferimento) |

**Scorciatoie da tastiera:**

| Tasto | Azione |
|-----|--------|
| `A` | Vince la foto a sinistra |
| `B` | Vince la foto a destra |
| `T` | Pareggio |
| `S` | Salta la coppia |
| `Escape` | Chiude la finestra di sovrascrittura categoria |

### Scheda Suggerimenti pesi

Confronta i pesi appresi dai tuoi voti con quelli attuali, con l'accuratezza del modello prima/dopo e le prime 10 foto ora rispetto a dopo il ricalcolo.

- **Applica** scrive i pesi suggeriti; **Ricalcola** rivaluta la categoria (entrambi in modalità di modifica).
- **Applica** compare solo quando il suggerimento batte i pesi attuali su confronti tenuti fuori (`suggest_changes`, lo stesso test di `--optimize-weights`, vedi [COMMANDS.md](COMMANDS.md)).
- A differenza di `--optimize-weights`, **Applica** non ricentra il bonus della categoria, quindi il suo punteggio medio può spostarsi.

### Scheda Pesi

Un cursore per metrica per la categoria selezionata, con un'anteprima dal vivo del punteggio. **Salva** scrive `scoring_config.json` (con un backup); **Ricalcola punteggi** lo applica; **Ripristina** ricarica i pesi memorizzati.

### Scheda Istantanee

Salva i pesi correnti come istantanea con nome e ripristina una qualsiasi precedente. Un'istantanea ripristina anche il bonus della categoria (`modifiers.bonus`). Le istantanee precedenti alla 1.21, da `calibrate.py`, o per `others` non portano un bonus e lo lasciano invariato.

### Priorità delle categorie e contesti di punteggio

Le categorie vengono controllate in ordine crescente di `priority`; vince la prima che corrisponde. Vedi [Valutazione dei filtri](SCORING.md#come-funziona-il-punteggio) e [Contesti di punteggio](CONFIGURATION.md#contesti-di-punteggio). Due strumenti solo per la modifica cambiano questo senza modificare `scoring_config.json`:

- **Priorità globale** — riordina l'ordine di valutazione di base.
- **Contesti di punteggio** — preset (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) che promuovono alcune categorie ed escludono altre, senza cambiare l'ordine globale. Modifica qualsiasi preset non `default` nella scheda **Contesto di punteggio**: trascina (o sposta su/giù) le categorie promosse, attiva le esclusioni, salva. Una categoria elencata in entrambi vince come esclusa. `label_key` e `suggest_from_moments` non sono modificabili qui. Assegna un contesto per album (vedi [Contesto di punteggio](#contesto-di-punteggio)) o per foto (sotto).

Nessuno dei due rivaluta le foto da solo. Poi esegui un ricalcolo (`POST /api/scan/recompute`) e osserva `GET /api/scan/recompute_status`. Una scansione o un ricalcolo già in corso da un terminale impedisce di avviarne uno nuovo dalla galleria. Con `normalization.per_category` attivo, un ricalcolo può non convergere del tutto — vedi [Normalizzazione](CONFIGURATION.md#normalization) e [Riordinare la priorità globale](CONFIGURATION.md#riordinare-la-priorità-globale).

**Collisioni tra categorie** (`GET /api/stats/categories/overlap`) mostra quale categoria a priorità più alta cattura le foto di una categoria. Per categoria elenca **Assegnate**, **Corrispondenze filtri** (se valutata da sola) e **Catturate da priorità superiore** (`matched - assigned`, con minimo 0). **Coppie con più collisioni** ordina le categorie per foto condivise. Il catch-all `default` è escluso, perché corrisponde a tutto.

### Sovrascrittura categoria

Riassegna la categoria di una foto dalla vista di confronto: modifica il badge della categoria, scegli una categoria, esegui "Analyze Filter Conflicts" per vedere quali filtri la escludono, poi applica. La sovrascrittura è persistente: sopravvive ai ricalcoli finché non la rimuovi (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

Il lightbox della foto ha le stesse azioni sotto **Imposta categoria di punteggio…** / **Rimuovi sovrascrittura** (solo modifica). La freccia nel chip della categoria apre **perché questa foto non è in un'altra categoria?**: scegli una categoria ed elenca i filtri che escludono la foto e che cosa servirebbe a ciascuno, per es. *"Raise shutter_speed_max from 0.02 to 0.033"*. Questo compare quando una categoria è irraggiungibile per una foto, cosa che un riordino non può risolvere (`POST /api/comparison/suggest_filters`).

## Statistiche EXIF

La pagina Statistiche (`/stats`) ha 5 schede. I selettori di **categoria** e **intervallo di date** filtrano ogni grafico. In modalità multiutente ogni utente vede le statistiche delle proprie foto visibili.

### Schede

| Scheda | Descrizione |
|-----|-------------|
| **Attrezzatura** | Corpi macchina, obiettivi e combinazioni (i primi 20 ciascuno) |
| **Impostazioni di scatto** | Distribuzioni di ISO, diaframma, lunghezza focale, tempo di posa |
| **Cronologia** | Foto nel tempo |
| **Categorie** | Analisi delle categorie, gestione dei pesi e correlazioni dei punteggi |
| **Correlazioni** | Grafici di correlazione personalizzati X/Y tra metriche con raggruppamento |

### Scheda Categorie

Quattro sotto-schede:

| Sotto-scheda | Descrizione |
|---------|-------------|
| **Ripartizione** | Conteggi di foto per categoria, punteggi medi, istogrammi di distribuzione dei punteggi |
| **Pesi** | Confronto con grafico radar (fino a 5 categorie), mappa di calore dei pesi ed editor dei pesi (modalità di modifica) |
| **Correlazioni** | Mappa di calore della correlazione di Pearson che mostra come ogni dimensione influenza l'aggregato, vista di dettaglio al clic |
| **Sovrapposizione** | Analisi della sovrapposizione dei filtri che mostra quali categorie condividono foto corrispondenti |

Ogni grafico ha un pulsante `?` che spiega come leggerlo; un interruttore nella barra delle sotto-schede mostra tutte le spiegazioni.

### Editor dei pesi (modalità di modifica)

Nella sotto-scheda Pesi, con la modalità di modifica attiva:

1. Seleziona una categoria dal menu a tendina
2. Regola i cursori dei pesi (uno per metrica, dovrebbero sommare 100%)
3. Usa "Normalizza a 100" per bilanciare automaticamente
4. Espandi la sezione Modificatori per regolare bonus/penalità
5. L'**Anteprima distribuzione punteggi** mostra un istogramma prima/dopo dal vivo
6. Clicca **Salva** per aggiornare `scoring_config.json` (crea un backup con data e ora)
7. Clicca **Ricalcola punteggi** (compare dopo il salvataggio) per applicare i pesi a quella categoria

## Scorciatoie da tastiera (galleria)

Le scorciatoie a tasto singolo sono inattive mentre il fuoco è in un campo di testo, menu o elenco.

| Tasto | Azione |
|-----|--------|
| `←` `→` `↑` `↓` | Sposta il segnaposto della foto corrente tra le schede (colonne della griglia e righe del mosaico) |
| `Enter` | Apre la foto a fuoco |
| `Space` | Seleziona / deseleziona la foto a fuoco |
| `Ctrl+A` / `Cmd+A` | Seleziona tutto — l'intera vista filtrata da una selezione vuota, altrimenti le foto caricate |
| `Escape` | Cancella la selezione (in modalità pannello laterale rilascia anche la foto tenuta) / chiude il cassetto dei filtri |
| `Shift+Click` | Seleziona un intervallo di foto tra l'ultima selezionata e quella cliccata |
| `Double-click` | Apre la foto |
| `Shift+F10` / `Menu` | Apre il menu contestuale della scheda foto a fuoco (il clic destro fa lo stesso) |
| `1`–`5` | Valuta la foto a fuoco da 1 a 5 stelle (modalità di modifica; passa automaticamente alla foto successiva) |
| `K` | Conserva la foto a fuoco (modalità di modifica) |
| `F` | Aggiunge / toglie dai preferiti la foto a fuoco (modalità di modifica) |
| `X` o `0` | Rifiuta / annulla il rifiuto della foto a fuoco (modalità di modifica; avanza automaticamente) |
| `/` | Mette a fuoco la ricerca della barra degli strumenti (mostrata da 1360 px di larghezza); più stretta, apre la ricerca della barra laterale dei filtri |
| `S` | Apre l'editor delle pile per la selezione esplicita (modalità di modifica; rimappabile, può restare non assegnato) |
| `Ctrl+Maiusc+S` / `Cmd+Maiusc+S` | Impila subito la selezione esplicita non impilata nell’ordine di selezione, con la prima foto come copertina (modalità di modifica; i membri di pile esistenti aprono l’editor) |
| `B` | Mostra / nasconde la barra laterale dei filtri |
| `V` | Passa tra layout a griglia e a mosaico |
| `?` | Mostra il riferimento delle scorciatoie da tastiera (ogni pagina; anche nel menu utente → Aiuto) |

**Rimappare i tasti.** `K`, `F`, `X`, `/`, `B`, `V` e `S` sono valori predefiniti. Menu utente → **Personalizza le scorciatoie** permette di cliccare un'azione e premere un nuovo tasto (`Esc` o `Tab` annulla). Cifre, `Space` e `?` sono riservati, e un tasto già in uso viene rifiutato. **Ripristina tutto** ripristina i valori predefiniti. La mappatura è memorizzata per browser (`localStorage`). La pagina della foto usa gli stessi tasti, e il riferimento `?` mostra sempre i tasti in vigore.

**Foto corrente.** La foto su cui agiscono i tasti di valutazione, preferito e rifiuto ha un contorno di 4px; le altre schede si attenuano al 50%. Nulla è segnato finché non ti sposti su una foto. Cliccare una foto sposta il segnaposto su di essa. Tornando da una foto, il segnaposto resta sull'ultima visualizzata. Il suggerimento della scheda a fuoco compare solo in modalità di modifica con `viewer.features.show_rating_controls` attivo.

**Nella pagina della foto**, `1`–`5`, il tasto preferito e il tasto rifiuta (`F` e `X` per impostazione predefinita; anche `0` rifiuta) agiscono sulla foto aperta, in modalità di modifica con `viewer.features.show_rating_controls` attivo. Non avanzano; usa `←` `→`. Il riferimento `?` li elenca sotto *Photo view*.

## Annulla

Le modifiche di gruppo a preferito/rifiuto/valutazione e le conferme di selezione mostrano una snackbar con **Annulla** per ~7 secondi.

- Le modifiche di gruppo ai flag si applicano subito e si annullano invertendole (fino a 500 foto).
- Le conferme di selezione sono differite: il gruppo sparisce subito, ma nulla viene salvato finché la finestra di annullamento non termina.
- Le modifiche ai [tag manuali](#tag-manuali) non sono annullabili.

Per modifiche più vecchie, vedi [Cronologia delle modifiche](#cronologia-delle-modifiche).

## Progressive Web App

Le build di produzione possono essere installate nella schermata iniziale. La shell dell'app si carica offline, e fino a 1000 miniature sono messe in cache per 7 giorni (le dimensioni più grandi, come i rendering da 1920 px della camera oscura, si affidano alla cache del browser). Le risposte API non vengono mai messe in cache, tranne i pacchetti di traduzione. Una snackbar propone un ricaricamento quando viene distribuita una nuova versione.

> **Avviso:** il logout cancella la cache delle miniature dell'app ma non la cache HTTP del browser, che può conservare le immagini viste (miniature, rendering, immagini a piena risoluzione) fino a un anno. Gli account che non devono vedere le foto l'uno dell'altro non dovrebbero condividere un profilo del browser.

## Mobile

Sugli schermi piccoli la scheda di selezione fluttuante mantiene il conteggio e i pulsanti cancella, seleziona tutto e inverti, più un pulsante **Azioni**. Apre un pannello inferiore con ogni operazione di gruppo (preferito, rifiuto, valutazione, album, copia, download). Compare un pulsante di confronto quando la selezione si adatta alla vista di confronto.

## Cornice digitale / Chiosco

Cornici fotografiche smart, dashboard Home Assistant e display in stile ImmichFrame / Immich-Kiosk possono prelevare i tuoi scatti migliori senza accedere. Non c'è **alcuna interfaccia client**: i dispositivi chiamano gli endpoint con un **token di cornice** di lunga durata dal blocco di configurazione `frame`. Con `frame.tokens` vuoto (il valore predefinito), la funzione è disattivata e ogni endpoint restituisce 404.

- **Che cosa viene mostrato.** Le foto provengono dall'intera libreria, non dalle cartelle di un utente. Le foto scartate, scarto e con occhi chiusi sono escluse. `frame.min_aggregate` (predefinito 7.0) imposta la soglia di punteggio; `frame.favorites_only` e `frame.categories` restringono ulteriormente.
- **Varietà.** Le foto sono un campione casuale ponderato per punteggio, così vedi scatti buoni diversi invece delle stesse poche.
- **Nessun percorso di file.** Ogni foto è indirizzata da un id opaco firmato, così chi ha un token non può sapere dove stanno i tuoi file né sfogliare altre righe.

| Endpoint | Restituisce | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` limitato a `frame.max_count` (predefinito 100), predefinito `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | il JPEG della foto — originale ridimensionato a `max_edge` (limitato da `frame.max_edge`, predefinito 1920), o la miniatura memorizzata se l'originale non è raggiungibile | long immutable |
| `GET /api/frame/next?token=` | un JPEG selezionato a caso, diverso a ogni chiamata — per cornici semplici e Home Assistant | `no-store` |

### Generare un token

Un token è una stringa a tua scelta. Usane una lunga e casuale e trattala come una password:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Aggiungilo a `frame.tokens` in `scoring_config.json`. Elencane uno per dispositivo; rimuovine uno per revocarlo:

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Ricetta Home Assistant

`/api/frame/next` funziona come [telecamera generica](https://www.home-assistant.io/integrations/generic/) di Home Assistant; ogni aggiornamento preleva un nuovo scatto:

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # aggiorna ogni ~20s
```

Aggiungi la telecamera a una scheda Picture Glance / Picture Entity per ottenere una cornice fotografica che si aggiorna da sola.

Per un client in stile **ImmichFrame** che gestisce una propria presentazione, interroga `GET /api/frame/photos?token=…&count=30` per gli id, poi recupera ciascuno con `GET /api/frame/image/{id}?token=…&max_edge=1920`. Gli id sono stabili e le immagini sono messe in cache a lungo termine, quindi ogni foto viene scaricata una sola volta.

## Caricamento automatico dal telefono

Invia le foto dal telefono a Facet. Un piccolo server **WebDAV** su `/dav` permette a PhotoSync (o a qualsiasi client WebDAV) di caricare in una **directory di ingresso**. Metti la directory di ingresso dentro una directory scansionata ed esegui `facet.py --watch` su di essa: ogni foto viene valutata appena arriva.

- **Credenziali separate.** L'accesso usa HTTP Basic con un login di dispositivo condiviso dal blocco `upload` (`upload.username` / `upload.password`), non un account utente.
- **Disattivato per impostazione predefinita.** `/dav` restituisce **404** finché `upload.username`, `upload.password` e `upload.inbox_dir` non sono tutti impostati.
- **Confinato alla directory di ingresso.** Nulla fuori da `upload.inbox_dir` è raggiungibile. I file sono limitati a `upload.max_file_mb` (predefinito 500).
- **Metodi:** `OPTIONS`, `PROPFIND` (profondità 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` non sono implementati; le app di caricamento funzionano senza.

### Configurazione

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Tieni `inbox_dir` sotto una directory scansionata così `--watch` vede i caricamenti:

```bash
python facet.py /photos --watch
```

### Ricetta PhotoSync

1. In PhotoSync, aggiungi una configurazione **WebDAV** (Configure → Add Configuration → WebDAV).
2. **URL / Server**: `http://<host>:5000/dav/` (`https://` dietro un reverse proxy).
3. **Nome utente / Password**: i tuoi `upload.username` / `upload.password`.
4. **Cartella di destinazione**: la radice (`/`) per la directory di ingresso, o una sottocartella.
5. Sull'host di Facet, osserva la directory di ingresso così i caricamenti vengono valutati:

   ```bash
   python facet.py /photos --watch
   ```

### Test rapido con curl

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (o `204 No Content` in caso di sovrascrittura) significa che il file è arrivato nella directory di ingresso; `--watch` lo valuta poco dopo.

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

Aumenta `min_photos_for_person` per nascondere dal menu del filtro le persone con poche foto.

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
      "hide_brackets": true,
      "hide_panoramas": true,
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

Esegui questi comandi per migliori prestazioni:

```bash
python database.py --migrate-tags    # Query sui tag 10-50 volte più veloci
python database.py --refresh-stats   # Precalcola le aggregazioni
python database.py --optimize        # Deframmenta il database
```

`--migrate-tags` è una configurazione una tantum. Poi scansioni, `--recompute-tags`, `--recompute-tags-vlm` e `tag_existing.py` mantengono aggiornata la tabella dei tag. Finché non lo esegui, i filtri sui tag usano un ripiego più lento.

Controlla la cache delle statistiche (durata di 5 minuti) con:

```bash
python database.py --stats-info
```

### Indici della galleria e cache dei conteggi

Facet aggiunge indici che mantengono veloci pagine e conteggi della galleria sulle librerie grandi. Su una libreria da 130k foto hanno portato la pagina predefinita da circa 1,2 s a 26–38 ms con il conteggio in cache, e circa 104 ms subito dopo una modifica del database.

- **Costruiti una volta, in background.** Il primo avvio della galleria dopo un aggiornamento costruisce gli indici mancanti mentre la galleria già serve. Su una libreria da 130k foto l'indice più grande ha richiesto da 45 a 55 s per essere costruito e circa 106–111 MB di dimensione aggiuntiva del database. Mentre un indice viene scritto, i salvataggi vengono brevemente rifiutati con un messaggio "riprova tra un momento". Una scansione `python facet.py` o un'esecuzione di `python database.py` li costruisce prima invece. Vedi [DEPLOYMENT.md](DEPLOYMENT.md#avvio-del-viewer-e-indici-della-galleria) per scritture durante la costruzione, spegnimento, `--workers N` e Docker.
- **Le scritture diventano leggermente più lente**: circa 0,5–0,7 ms in più per riga quando cambia una colonna portata da questi indici.
- **Cache dei conteggi.** I conteggi della galleria sono messi in cache per 5 minuti. Qualsiasi modifica da un processo sullo stesso host (inclusi `--detect-junk` e `--recompute-*`) li aggiorna. Una modifica fatta da un'altra macchina tramite una condivisione di rete compare quando la cache scade.

## Endpoint API

Il riferimento dell'API HTTP è in [API.md](../API.md). La documentazione interattiva è servita su `/api/docs`.

## Foto JPEG XL

Facet scansiona JPEG XL (`.jxl`) con la dipendenza principale `imagecodecs`, inclusa nelle installazioni standard e in Docker. Non serve alcun pacchetto aggiuntivo; le scansioni saltano `.jxl` solo se quel codec non è disponibile.

- **Visualizzazione.** I browser che accettano `image/jxl` ricevono il file originale; gli altri ricevono un JPEG. Le miniature della galleria sono JPEG.
- **Metadati.** Gli originali restano `.jxl`. Le modifiche di revisione vanno nei sidecar, non nel file.
- **Animazioni.** Si usa solo il primo fotogramma.
- **Colore.** Un JXL che ricostruisce un JPEG mantiene il suo profilo ICC e le anteprime sono convertite in sRGB. Per un JXL nativo, il profilo colore incorporato non è disponibile, quindi punteggi e anteprime di file ad ampia gamma o HDR possono non essere accurati nel colore. I download degli originali mantengono profondità di bit e profilo.
- **Limiti.** La decodifica verifica il limite di pixel di Pillow prima di allocare i pixel, e l'ispezione dell'intestazione del contenitore si ferma a 4.096 box. EXIF codificato e decompresso sono limitati ciascuno a 16 MiB; un EXIF eccessivo viene scartato e l'immagine resta leggibile. Vengono messe in cache al massimo cinque conversioni JPEG. I file con layout di canali extra non supportati vengono rifiutati.

## Risoluzione dei problemi

| Problema | Soluzione |
|-------|----------|
| Caricamento lento delle pagine | Esegui `--migrate-tags` e `--optimize` |
| I filtri non compaiono | Controlla `--stats-info`, esegui `--refresh-stats` |
| Filtro persone vuoto | Esegui `--cluster-faces-incremental` |
| Pulsante Confronta mancante | Imposta una `edition_password` non vuota (utente singolo) o usa il ruolo `admin`/`superadmin` (multiutente) |
| La password non funziona | Controlla `viewer.password` (utente singolo) o verifica l'hash della password (multiutente) |
| L'utente non vede le foto | Controlla `directories` nella sua configurazione utente e `shared_directories` |
| Pulsante Scansione mancante | Richiede `viewer.features.show_scan_button: true` più l'accesso alla scansione — vedi [Avvio scansione](#avvio-scansione) |
| La ricerca non restituisce risultati | Assicurati che le foto abbiano dati `clip_embedding` (esegui prima la valutazione) |
| La ricerca dice che l'accelerazione Apple Silicon è occupata | Riprova quando l'attività del modello in corso termina |
| Critica VLM non disponibile | Richiede il profilo 16gb/24gb, `viewer.features.show_vlm_critique: true` e una sessione di modifica |
| La mappa non mostra foto | Esegui `--extract-gps`; controlla che le foto abbiano dati GPS EXIF |
| Le didascalie non vengono generate | Richiede il profilo VRAM 16gb/24gb per le didascalie VLM |
| Cronologia vuota | Assicurati che le foto abbiano valori `date_taken` |
| Porta 5000 in uso | Esegui `python viewer.py --port 5001` (o imposta `PORT=5001`). Su macOS, AirPlay Receiver usa la 5000: scegli un'altra porta o disattivalo in Impostazioni di Sistema → Generali → AirDrop e Handoff. |

### Verificare i riquadri manuali dei volti salvati

Trova le foto i cui rettangoli di volto salvati vanno controllati. Nella scheda Revisione della barra laterale della galleria, attiva **Volti manuali da verificare** (editor). Apri l'editor dei volti di una foto e regola e salva, o elimina, ogni rettangolo segnalato. La foto esce poi dall'elenco. Il filtro funziona negli album intelligenti e nelle selezioni dell'intera vista, e compare come chip rimovibile.

- L'elenco riflette l'ultima scansione o il controllo dell'editor, non un monitoraggio dei file in tempo reale. Le scansioni controllano le foto con marcature manuali anche con il rilevamento dei volti disattivato.
- Aprire l'editor ricontrolla l'originale ed è autorevole.
- Le marcature riportate da un relink (`relink_unverified`) restano segnalate finché non vengono salvate di nuovo nell'editor.
- La revisione non modifica mai i file originali. Le esportazioni e gli aggiornamenti del database della galleria mantengono lo stato di revisione.

## Correzione della data di scatto

Correggi l'orologio sbagliato di una fotocamera. In modalità di modifica, scegli **Correggi data di scatto** dall'icona del calendario accanto alla data della foto, o dalla barra di selezione della galleria. Fino a 1000 foto visibili, "Seleziona tutta la vista" incluso.

- **Sposta di** (predefinito): scegli **Prima** o **Dopo** e inserisci Giorni, Ore, Minuti e Secondi. Predefinito: 1 ora dopo. I pulsanti rapidi −1 h, +1 h, −1 d e +1 d si sommano allo spostamento.
- **Imposta ora esatta**: inserisci la data e l'ora corrette di una foto di riferimento (la foto aperta, o la prima foto datata della selezione; non per "Seleziona tutta la vista"). Lo spostamento ne viene derivato.
- Lo spostamento deve essere diverso da zero e al massimo ±366 giorni.
- Un riepilogo indica lo spostamento ("1 h 30 min later"), e l'anteprima mostra i conteggi di modificate/saltate e le prime 20 marche temporali vecchie/nuove.
- **Applica correzione (N)** la applica. Se nel frattempo è cambiato qualcosa, un errore offre **Anteprima** per aggiornare.

**Che cosa cambia.**

- L'ora della fotocamera viene spostata così com'è: nessuna logica di fuso orario o ora legale.
- Sono supportate solo date complete `YYYY:MM:DD HH:MM:SS` o `YYYY-MM-DD[T o spazio]HH:MM:SS`. Le date sconosciute, solo data, con fuso orario/sottosecondi e non valide vengono saltate.
- Le date corrette sopravvivono a nuove scansioni ed esportazioni incrementali del database della galleria.
- **Usa data del file** rimuove la correzione e rilegge il file. Nessuna data nel file significa data di scatto sconosciuta.
- Applicare una correzione non scrive mai l'originale né cambia l'ora del file. L'esportazione XMP scrive `exif:DateTimeOriginal`; **Scrivi metadati nel file** aggiorna anche l'EXIF `DateTimeOriginal` nei formati supportati.
- I gruppi di raffica e di serie non vengono ricalcolati; ripeti il rilevamento se ti serve raggrupparli di nuovo.

Endpoint: `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — vedi [API.md](../API.md).

## Cronologia delle modifiche

Rivedi e annulla le tue modifiche recenti in tutta la libreria. In modalità di modifica, apri **Cronologia delle modifiche** dall'icona dell'orologio nella navigazione principale (dopo In questo giorno). Espandi una voce per vedere i valori esatti prima/dopo, poi **Ripristina questa voce**.

- **Che cosa viene registrato:** GPS, date di scatto, decisioni di revisione, stelle, preferiti e pile manuali. Non file né riconoscimento dei volti.
- GPS e date di scatto sono valori condivisi della libreria. Decisioni di revisione, stelle e preferiti sono tuoi.
- Il breve Annulla e l'elenco di attività dell'assistente sono separati.
- **Limiti.** Le ultime **50 voci per account**, ciascuna fino a **1000 foto e 1 MiB** di valori. Le azioni di revisione filtrate più grandi vengono divise in parti; il ripristino ripristina una parte. Una sostituzione di pila può coprire fino a 2000 foto in una voce.
- La cronologia sopravvive a riavvii e aggiornamenti incrementali del database della galleria. Un'esportazione nuova/completa della galleria parte vuota. Non si sincronizza con un altro database.
- **Il ripristino è tutto o niente.** Viene rifiutato se il valore di una qualsiasi foto è cambiato da allora, anche se è stato rimesso com'era. La modifica privata di revisione di un altro account non blocca la tua. Anche nuove scansioni, importazioni e Annulla possono invalidare voci più vecchie.
- Una voce è nascosta quando una delle sue foto viene eliminata o non è più visibile a te.
- Un ripristino aggiunge una propria voce e segna l'originale come ripristinato.

## Volti senza nome

Trova i volti non assegnati e i gruppi di persone senza nome: `Filtri → Persone → Volti senza nome` (`faces_need_names=true`). Usa + per assegnare un volto, o dai un nome a un gruppo in Persone. Le foto senza volti rilevati sono escluse.

Gli utenti in sola lettura possono sfogliare questo filtro; assegnare o dare un nome richiede l'accesso di modifica.

## Assegnare persone

Il selettore **Assegna volto a persona** elenca per prime fino a 12 persone che hai assegnato di recente in questo browser (per identità connessa). Le altre persone con nome seguono per numero di volti nelle foto che puoi vedere. Ricerca e paginazione coprono tutti.

- Una persona diventa recente solo dopo un'assegnazione riuscita o il salvataggio di un volto manuale.
- Vengono memorizzati in locale solo gli ID delle persone. Disconnettersi cancella l'elenco.

## Aggiorna metadati e anteprima

Rileggi i metadati di una foto e ricostruisci la sua anteprima senza una nuova scansione completa. Annotazioni manuali, valutazioni, volti e punteggi IA restano. Gli originali non vengono mai scritti. Riscansiona se i pixel modificati richiedono nuovi punteggi o un nuovo rilevamento dei volti.

- Fino a 100 foto selezionate; le selezioni dell'intera vista non sono supportate.
- I valori di origine mancanti non cancellano quelli memorizzati. Senza `exiftool`, viene aggiornata solo l'anteprima.
- GPS e date manuali vengono mantenuti.
- Viene rifiutato mentre è in corso un altro lavoro sulla libreria; riprova più tardi.
- Ogni foto viene salvata separatamente; il nuovo tentativo elabora i fallimenti.
- Fino alla successiva scansione, gli istogrammi usano la nuova anteprima e la ricerca per somiglianza di colore salta la foto.
