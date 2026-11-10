# Integrazione con Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · **Italiano** · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md) · [简体中文](../zh/IMMICH.md)

[Immich](https://immich.app/) archivia, esegue il backup e serve le tue foto. Facet le valuta, le classifica e le seleziona. Questa pagina collega i due strumenti:

- Le valutazioni e i preferiti di Facet compaiono in Immich.
- Un caricamento su Immich segnala a Facet che c'è nuovo lavoro in attesa.

Entrambe le direzioni usano solo l'API REST di Immich. Nessuno dei due strumenti tocca il database dell'altro.

**Facet richiede Immich ≥ 3.0.** Facet azzera una valutazione con `null` e marca un rifiuto con `-1`. Un server 2.x rifiuta l'azzeramento, quindi le valutazioni obsolete restano sui tuoi asset.

---

## Indice

- [Come i due vedono lo stesso file](#come-i-due-vedono-lo-stesso-file)
- [Passaggio 1 — condividi la libreria con Immich](#passaggio-1--condividi-la-libreria-con-immich)
- [Passaggio 2 — crea una chiave API](#passaggio-2--crea-una-chiave-api)
- [Passaggio 3 — mappa i percorsi](#passaggio-3--mappa-i-percorsi)
- [Passaggio 4 — verifica, poi invia](#passaggio-4--verifica-poi-invia)
- [Invio dei rifiuti](#invio-dei-rifiuti)
- [Importare e inviare pile manuali](#importare-e-inviare-pile-manuali)
- [Il webhook in entrata](#il-webhook-in-entrata)
- [Diagnostica nel visualizzatore](#diagnostica-nel-visualizzatore)
- [Riferimento di configurazione](#riferimento-di-configurazione)
- [Risoluzione dei problemi](#risoluzione-dei-problemi)

---

## Come i due vedono lo stesso file

Facet e Immich vedono lo stesso file su disco con percorsi diversi:

- **Facet** usa il percorso assoluto sulla macchina che esegue la scansione, ad es. `/mnt/photos/2026/07/IMG_1234.jpg`.
- **Immich** usa il proprio `originalPath`: il percorso visto *dall'interno del container di Immich*. Spesso è `/usr/src/app/upload/…` per i caricamenti, oppure il punto di mount di una libreria esterna.

Indichi a Facet la riscrittura di prefisso una sola volta, in `immich.path_map`. Ogni ricerca passa da lì. Se è sbagliata, tutto riporta «unmatched» — vedi [Risoluzione dei problemi](#risoluzione-dei-problemi).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La mappatura funziona in entrambe le direzioni. `--immich-sync` la usa per trovare l'asset Immich di un percorso di Facet. Il webhook la usa per trovare la foto di Facet a partire dall'`originalPath` di Immich.

## Passaggio 1 — condividi la libreria con Immich

La soluzione più semplice è una **libreria esterna** di Immich: Immich legge le foto dove già si trovano, e Facet scansiona la stessa directory.

1. In Immich, vai su **Administration → External Libraries → Create Library**, scegli il proprietario, e aggiungi un percorso di importazione per la directory così come la vede il container di Immich.
2. Monta quella directory in bind, in sola lettura, nel container di Immich. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scansiona la libreria in Immich (**Scan All Libraries**), e scansiona la stessa directory con Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Nessun file viene duplicato su disco.

Puoi anche caricare in Immich normalmente (backup da mobile, caricatore web) e puntare Facet verso la directory di upload di Immich. Cambiano solo i prefissi. Riesegui la scansione di Facet dopo i caricamenti, oppure usa `--watch`.

## Passaggio 2 — crea una chiave API

In Immich: **click your avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 permette di limitare una chiave ad alcuni scope. La sincronizzazione di valutazioni e preferiti richiede questi (le pile manuali ne richiedono altri, vedi sotto):

| Scope | Cosa ne fa Facet |
|-------|-------------------------|
| `server.about` | Controllo di connettività/autenticazione di `--immich-test` |
| `asset.read` | Risolve gli asset tramite `originalPath` |
| `asset.update` | Scrive `rating` e `isFavorite` |
| `album.read` | Trova un album delle scelte migliori esistente in base al nome |
| `album.create` | Crea l'album delle scelte migliori la prima volta |
| `albumAsset.create` | Aggiunge foto all'album delle scelte migliori |

Puoi saltare i tre scope degli album se `push.top_picks_album` è vuoto. Facet tocca gli album solo quando quel nome è impostato.

Facet invia la chiave in un'intestazione `x-api-key`. Inseriscila in `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Nota:** Facet scrive le valutazioni con `PUT /api/assets`. Immich lo segna come deprecato, ma il suo sostituto non è ancora pubblicato, quindi Facet continua a usarlo.

## Passaggio 3 — mappa i percorsi

Aggiungi una coppia per ogni radice condivisa. Regole:

- Vince la prima corrispondenza di prefisso. È un confronto letterale tra stringhe, non tra directory.
- Termina i prefissi di directory con `/`.
- Metti le mappature più specifiche prima di quelle più generiche.

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Due radici, due coppie:

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

Il placeholder di serie (`{"facet_prefix": "", "immich_prefix": ""}`) lascia i percorsi invariati. Funziona solo se Facet e Immich vedono percorsi assoluti identici, cosa rara a meno che Facet non giri dentro il container di Immich.

Per trovare il valore reale, apri una foto in Immich e premi `i` per il pannello informazioni. Confronta il percorso del file mostrato lì con il percorso che Facet riporta per la stessa foto.

## Passaggio 4 — verifica, poi invia

```bash
# Solo connettività + autenticazione. Nessuna scrittura.
python facet.py --immich-test

# Risolve ogni asset e riporta cosa CAMBIEREBBE. Ancora nessuna scrittura.
python facet.py --immich-sync --dry-run

# Per davvero.
python facet.py --immich-sync
```

La sincronizzazione riporta `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / album creati. In una simulazione, `updated` conta gli asset che cambierebbero, e non viene scritto nulla. Un conteggio `unmatched` elevato alla prima esecuzione significa quasi sempre che la mappatura dei percorsi è sbagliata — vedi [Risoluzione dei problemi](#risoluzione-dei-problemi).

Cosa viene inviato:

- **Valutazioni a stelle 1–5** → il `rating` di Immich. Una foto non valutata non invia nulla.
- **Preferiti** → `isFavorite` di Immich.
- **Azzeramenti.** Se hai valutato una foto, hai sincronizzato, e poi l'hai riportata a non valutata, la sincronizzazione successiva invia `rating: null` così che anche Immich la azzeri. Facet ricorda cosa ha inviato l'ultima volta (in `stats_cache`) proprio per questo. Invia `null`, mai `0`: Immich v3 rifiuta `0`, e un solo batch rifiutato interrompe l'intera sincronizzazione.
- **Un album delle scelte migliori** (facoltativo), popolato con le foto valutate almeno `push.top_picks_min_rating`, quando `push.top_picks_album` è impostato.

In modalità multiutente, `--immich-sync --user alice` invia le valutazioni personali di Alice (`user_preferences`) invece di quelle globali, e tiene traccia separatamente del suo stato di sincronizzazione.

## Invio dei rifiuti

Disattivato per impostazione predefinita. Se attivo, una foto che rifiuti nella vista di selezione di Facet riceve il marcatore di rifiutata di Immich:

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

Con `push.rejected` attivo:

- Una foto rifiutata invia `rating: -1`, il valore di Immich v3 per «rifiutata».
- **Il rifiuto prevale sulle stelle.** Una foto rifiutata con 5 stelle invia `-1`, non `5`.
- **Annullare il rifiuto lo azzera.** La foto invia allora la sua valutazione a stelle attuale, oppure `rating: null` se non ne ha una.
- Una foto rifiutata non entra mai nell'album delle scelte migliori.
- `push.ratings: false` lo disattiva a sua volta, poiché `-1` è una valutazione.

Lascialo disattivato se altre persone (o il tuo telefono) guardano la libreria Immich: vedranno il `-1`.

## Importare e inviare pile manuali

Le pile manuali hanno un proprio flusso **piano/applicazione dalla CLI locale**, con le consuete opzioni `--config`, `--db` e `--user`. La sincronizzazione di valutazioni e preferiti non ne è toccata.

Requisiti:

- Immich **≥ 3.0** (Facet verifica anche a runtime il supporto alle pile).
- Permessi della chiave: `user.read` e `stack.read` in aggiunta a `asset.read`; l'invio richiede anche `stack.create` e `asset.update`. `stack.update` e `stack.delete` non servono.
- Le installazioni multiutente devono indicare un utente esistente.
- La chiave Immich non viene mai usata dalle operazioni sulle pile dal viewer web, dagli assistenti (MCP) o dal webhook di caricamento.

Flusso:

1. Anteprima. È in sola lettura su entrambi i lati e non migra il database.
2. Controlla il piano e il suo digest SHA-256.
3. Applica esplicitamente.

Opzioni e limiti:

- `--stack-id UUID` (ripetibile) limita l'esecuzione a quelle pile sorgente.
- `--stack-plan-out` scrive un nuovo file JSON privato (modalità POSIX `0600`) e rifiuta di sovrascrivere.
- Un piano contiene al massimo **1000 gruppi, 1000 membri per gruppo, 20000 membri totali e 16 MiB**. Usa `--stack-id` per restringerlo.
- Su Windows, scegli una cartella di destinazione la cui ACL limiti l'accesso al tuo account; i permessi POSIX non proteggono lì il file.

Regole di corrispondenza:

- Ogni membro deve corrispondere esattamente a una foto indicizzata, visibile e disponibile di proprietà dell'account remoto. Un membro mancante o ambiguo fa saltare tutto il gruppo.
- L'invio crea una pila solo da asset remoti non ancora impilati.
- Una corrispondenza esatta di membri e copertina collega le due pile all'applicazione.
- Sovrapposizioni parziali, copertine diverse, membri cambiati e casi di pila separata su un solo lato vengono saltati come conflitti. Le pile esistenti non vengono mai aggiornate.
- Viaggia solo la copertina; l'ordine degli altri membri no.
- Non esistono sincronizzazione bidirezionale automatica, polling né propagazione della separazione delle pile.

Piani, collegamenti e ricevute sono legati a server, account remoto, proprietario locale e mappatura dei percorsi. Se cambia uno di questi, il vecchio piano non è più applicabile. Le ricevute conservano risultati e ID degli asset remoti, mai credenziali.

L'applicazione ricontrolla ogni gruppo prima di scrivere e lo rilegge dopo. Se una risposta di creazione va persa, Facet la riconcilia prima di qualsiasi nuovo tentativo invece di inviarla di nuovo. L'annullamento si ferma tra i gruppi; una successiva applicazione riparte dalle ricevute.

> **Attenzione:** Immich non può creare una pila in modo condizionale. Un altro client può modificare gli asset tra l'ultimo controllo di Facet e la scrittura, e Facet non può annullarlo.

## Il webhook in entrata

Il webhook funziona nel verso opposto: Immich comunica a Facet che un asset è cambiato, e Facet risponde con ciò che sa.

**È disattivato per impostazione predefinita e non avvia mai una scansione.** Invece:

- **Foto conosciuta e valutata** → Facet invia subito a Immich la sua valutazione e il preferito. Valuti una foto, la carichi, e la valutazione arriva in Immich senza attendere `--immich-sync`.
- **Foto sconosciuta o non ancora valutata** → Facet aggiunge il percorso a un elenco di attesa limitato, e il successivo `--immich-sync` lo registra nel log.

### Attivalo

Il token è un segreto, quindi vive in una variabile d'ambiente, non in `scoring_config.json` (quel file è leggibile da chiunque nella maggior parte delle installazioni). La configurazione nomina la variabile; la variabile contiene il valore.

1. Genera un token ed esportalo ovunque venga avviato il viewer — unit systemd, `docker-compose.yml` o profilo della shell:

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Indica il nome di quella variabile in `scoring_config.json`:

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Riavvia il viewer (`python viewer.py`).

Se `token_env` è vuoto, oppure la variabile non è impostata o è vuota, l'endpoint è disabilitato e restituisce **404** (come `frame.tokens` e `upload.username`).

### Punta Immich verso questo endpoint

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — `Asset uploaded`. Aggiungi `Asset updated` se vuoi che anche le modifiche lo attivino.
2. **Action** — **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, a un indirizzo che il container di Immich possa raggiungere. Se entrambi girano in Docker sullo stesso host, usa il nome del servizio (`http://facet:5000/…`), non `localhost`.
4. **Header** — nome `x-facet-token`, valore il tuo token. Il nome deve corrispondere a `webhook.header`. È accettato anche `Authorization: Bearer <token>`, per i proxy che offrono solo quello.
5. Salva, poi carica una foto per verificare.

### Cosa risponde l'endpoint

| Stato | Significato |
|--------|---------|
| `202` | Accettato. Il JSON conta gli asset di questo invio: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON valido, ma nessun asset che Facet riconosce. Registrato nel log, non un errore. |
| `400` | Il corpo non era JSON. |
| `401` | Nessun token nella richiesta. |
| `403` | Token errato. |
| `404` | La funzionalità è disattivata (nessun token configurato). |

Facet legge `originalPath` dal payload, ovunque si trovi: un asset singolo, `{"asset": {…}}`, un elenco, o uno qualsiasi di questi sotto `data` / `items` / `assets`. Se il payload contiene l'`id` dell'asset, Facet lo recupera da Immich e ne verifica percorso e proprietario/libreria prima di aggiornare. Un'incongruenza conta come `failed`.

La sincronizzazione successiva registra nel log i percorsi in attesa:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scansiona quelle foto (`python facet.py /mnt/photos`) e usciranno dall'elenco alla sincronizzazione successiva. L'elenco conserva al massimo `max_pending` voci e scarta per prime le più vecchie.

### Note sulla sicurezza

- Il token viene confrontato a tempo costante; un token errato riceve un semplice `403`, senza alcun segnale temporale.
- Servi il viewer via HTTPS a meno che Immich non lo raggiunga attraverso una rete privata: il token viaggia in un'intestazione a ogni invio.
- Per ruotare il token, cambia insieme la variabile d'ambiente e l'intestazione del workflow di Immich, poi riavvia il viewer.
- Il webhook invia la valutazione globale, non quella di un singolo utente. Per le valutazioni per utente in Immich, lascia disattivato il webhook ed esegui `--immich-sync --user <nome>` secondo una pianificazione.

## Diagnostica nel visualizzatore

Apri **Diagnostica Immich** dal sottomenu **Attività e diagnostica** del menu utente. In modalità multiutente serve l'accesso da superamministratore; in modalità singolo utente serve l'accesso in modalità edizione (o la modifica locale fidata).

- Nulla viene letto da Immich finché non fai clic su **Verifica connessione**. Il test legge la versione del server e l'accesso al conto e non scrive nulla.
- La copertura dei percorsi controlla al massimo 200 foto indicizzate. Non conferma che ciascuna corrisponda a un asset Immich.
- L'ora dell'ultima sincronizzazione può precedere una modifica del server configurato.
- Il controllo della versione non verifica i permessi sulle pile.
- Credenziali e percorsi del server non vengono mai mostrati.

## Riferimento di configurazione

Il blocco `immich` completo, con i valori predefiniti forniti di serie:

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
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
```

| Impostazione | Predefinito | Descrizione |
|-----|---------|---------|
| `url` | `""` | URL di base di Immich, `http` o `https`. Uno slash finale viene rimosso. |
| `api_key` | `""` | Chiave API, inviata come `x-api-key`. Se vuota, interrompe ogni sincronizzazione con un errore chiaro. |
| `owner_id` | `""` | Associa solo gli asset con esattamente questo `ownerId` di Immich. |
| `library_id` | `""` | Associa solo gli asset con esattamente questo `libraryId` di Immich. Vuoto significa qualsiasi libreria. |
| `path_map` | una coppia vuota | Riscritture di prefisso tra i percorsi di Facet e l'`originalPath` di Immich. Vince la prima corrispondenza; usato in entrambe le direzioni. |
| `push.ratings` | `true` | Invia le valutazioni a stelle 1–5 (e i relativi azzeramenti). |
| `push.favorites` | `true` | Invia `isFavorite` (e i relativi azzeramenti). |
| `push.rejected` | `false` | Invia `rating: -1` per le foto rifiutate in Facet. Richiede `push.ratings`. |
| `push.top_picks_album` | `""` | Nome dell'album da popolare. Vuoto significa che Facet non tocca mai gli album. |
| `push.top_picks_min_rating` | `4` | Valutazione a stelle minima per quell'album. |
| `webhook.token_env` | `""` | Variabile d'ambiente che contiene il segreto del webhook. Vuoto disabilita l'endpoint. |
| `webhook.header` | `"x-facet-token"` | Intestazione in cui Immich invia il token. |
| `webhook.max_pending` | `500` | Lunghezza massima dell'elenco dei percorsi in attesa (non ancora valutati). |
| `timeout_seconds` | `30` | Timeout HTTP per singola richiesta. |

## Risoluzione dei problemi

### Tutto risulta `unmatched`

La mappatura dei percorsi è sbagliata. È di gran lunga il problema più frequente.

1. Apri una foto in Immich e premi `i`. Annota il percorso nel pannello informazioni.
2. Trova il percorso della stessa foto in Facet (il pannello dettagli della galleria, oppure `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. I due percorsi finiscono allo stesso modo. Le parti che differiscono sono `facet_prefix` e `immich_prefix`.

Trappole comuni:

- **Uno slash finale mancante.** `"/mnt/photos"` → `"/usr/src/app/external"` riscrive anche `/mnt/photosXYZ/a.jpg`. Termina entrambi i prefissi con `/`.
- **Percorso host contro percorso container.** Il percorso di Immich è quello visto dal *container*. Verifica con `docker compose exec immich-server ls /usr/src/app/external`.
- **Symlink e bind mount.** Immich memorizza il percorso che ha percorso. Un symlink su un lato fa differire le stringhe.
- **Maiuscole/minuscole e Unicode.** Il confronto è esatto. Su una condivisione case-insensitive, `/Photos/` e `/photos/` non corrispondono tra loro.
- **Immich non ha ancora indicizzato il file.** Esegui **Scan All Libraries** e verifica che l'asset esista in Immich.

`--immich-sync --dry-run` registra nel log i primi 20 percorsi unmatched, che di solito mostrano il prefisso sbagliato.

### `--immich-test` fallisce

- `Unsupported Immich URL scheme` — `url` deve iniziare con `http://` o `https://`.
- `HTTP 401` — la chiave API è sbagliata o è stata revocata.
- `HTTP 403` — alla chiave manca `server.about`. Ricreala con i sei scope elencati sopra.
- Connessione rifiutata / timeout — la porta è sbagliata, oppure Facet non riesce a raggiungere il container. Verifica con `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` dalla macchina che esegue Facet.

### Il webhook restituisce 404

La funzionalità è disattivata: `webhook.token_env` è vuoto, oppure la variabile che indica non è impostata o è vuota *nell'ambiente del viewer*. Esportarla nella tua shell non ha effetto su un viewer gestito da systemd o Docker. Impostala nel file unit o nel file compose e riavvia.

### Il webhook restituisce 401 o 403

`401`: non è arrivato alcun token, quindi il nome dell'intestazione inviata da Immich non corrisponde a `webhook.header`. `403`: il token è sbagliato. Confronta il valore dell'intestazione del workflow con la variabile d'ambiente.

### `ModuleNotFoundError: No module named 'sync'`

Il server sembra sano, ma il webhook fallisce quando Immich lo chiama e `--immich-sync` fallisce direttamente. Verifica con:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Se ottieni `ModuleNotFoundError: No module named 'sync'`, la tua immagine Docker è troppo vecchia. Scarica l'immagine attuale oppure ricostruiscila da un checkout aggiornato.

### Le valutazioni vengono inviate, ma gli azzeramenti no

Facet azzera solo una valutazione che ha inviato in precedenza, e le ricorda in `stats_cache` nel database di Facet. Ripristinare un database più vecchio, o usarne uno nuovo, fa perdere questa memoria: una valutazione azzerata nel frattempo resta in Immich. Rivaluta e riazzera la foto, oppure correggila in Immich.

### Le valutazioni compaiono sulle foto sbagliate

Facet salta le corrispondenze ambigue e le riporta come `identity_conflicts`:

- un percorso di Facet che corrisponde a più asset Immich
- più percorsi di Facet che puntano allo stesso percorso Immich

Per quei percorsi non viene scritto nulla; le altre foto si sincronizzano comunque.

Un lotto webhook è più severo: se più percorsi di Facet indicano la stessa destinazione o lo stesso ID di asset, ogni voce idonea del lotto viene rifiutata e contata come `failed`. Correggi le radici sovrapposte in `path_map`, oppure imposta `owner_id` e `library_id`, poi riprova. Non indovinare il proprietario dal nome di una persona o dal percorso.

Le risposte di Immich devono includere `id` e `originalPath`, e devono corrispondere a eventuali proprietario e libreria configurati. Un aggiornamento riuscito significa che Immich lo ha accettato; il suo lavoro sui metadati in background può essere ancora in corso.

### `rating: 0 is not valid`

Il server Immich è più vecchio della 3.0. Aggiornalo: Facet richiede `null` per azzerare e `-1` per `push.rejected`, e nulla aggira questo limite sulla 2.x.

---

**Vedi anche:** [Comandi — Immich Sync](COMMANDS.md#immich-sync) · [Configurazione](CONFIGURATION.md) · [Ricette di interoperabilità con gli editor](INTEROP.md) per il roundtrip XMP con Lightroom, darktable e digiKam.
