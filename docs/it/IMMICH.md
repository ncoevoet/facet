# Integrazione con Immich

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · [Deutsch](../de/IMMICH.md) · **Italiano** · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md)

Facet e [Immich](https://immich.app/) svolgono compiti diversi sulle stesse foto. Immich è la libreria: le acquisisce, ne esegue il backup e le serve al tuo telefono. Facet è il giudizio: le valuta, le classifica e le seleziona. Questa pagina collega i due strumenti in modo che i verdetti raggiunti da Facet compaiano come valutazioni e preferiti in Immich, e in modo che un caricamento su Immich segnali a Facet che c'è nuovo lavoro in attesa.

Il collegamento è solo REST in entrambe le direzioni. Facet non tocca mai il database di Immich, e Immich non tocca mai quello di Facet.

**Facet richiede Immich ≥ 3.0.** I server più vecchi rifiutano la semantica delle valutazioni da cui Facet dipende: `null` per azzerare una valutazione e `-1` per marcarne una come rifiutata. Su un server 2.x l'azzeramento viene rifiutato e le valutazioni obsolete restano bloccate sui tuoi asset per sempre.

---

## Indice

- [Come i due vedono lo stesso file](#come-i-due-vedono-lo-stesso-file)
- [Passaggio 1 — condividi la libreria con Immich](#passaggio-1--condividi-la-libreria-con-immich)
- [Passaggio 2 — crea una chiave API](#passaggio-2--crea-una-chiave-api)
- [Passaggio 3 — mappa i percorsi](#passaggio-3--mappa-i-percorsi)
- [Passaggio 4 — verifica, poi invia](#passaggio-4--verifica-poi-invia)
- [Invio dei rifiuti](#invio-dei-rifiuti)
- [Il webhook in entrata](#il-webhook-in-entrata)
- [Riferimento di configurazione](#riferimento-di-configurazione)
- [Risoluzione dei problemi](#risoluzione-dei-problemi)

---

## Come i due vedono lo stesso file

Tutto qui si basa su un'unica idea: **la stessa foto su disco, vista da due container**.

Facet conosce una foto dal suo percorso assoluto sulla macchina che esegue la scansione — `/mnt/photos/2026/07/IMG_1234.jpg`. Immich conosce lo stesso file tramite il proprio `originalPath`, ossia l'aspetto che quel file ha *dall'interno del container di Immich* — spesso `/usr/src/app/upload/…` per gli asset caricati, oppure il punto di mount assegnato a una libreria esterna.

Nessuno dei due lati può indovinare il punto di vista dell'altro, quindi indichi a Facet la riscrittura di prefisso una sola volta (`immich.path_map`) e ogni ricerca in entrambe le direzioni passa da lì. Se questo è corretto, il resto è meccanico; se è sbagliato, tutto riporta silenziosamente «unmatched» — vedi [Risoluzione dei problemi](#risoluzione-dei-problemi).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La mappatura viene usata in entrambe le direzioni: in uscita (`--immich-sync` traduce un percorso di Facet per trovare l'asset) e in entrata (il webhook traduce `originalPath` di Immich per ritrovare la foto).

## Passaggio 1 — condividi la libreria con Immich

La soluzione più pulita è una **libreria esterna**: Immich legge le foto dove già si trovano, invece di possedere una seconda copia. Facet scansiona la stessa directory dal proprio lato.

1. In Immich, vai su **Administration → External Libraries → Create Library**, scegli il proprietario, e aggiungi un percorso di importazione che punti alla directory così come la vede il container di Immich.
2. Assicurati che quella directory sia montata in bind, in sola lettura, nel container di Immich. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scansiona la libreria dall'interfaccia di Immich (**Scan All Libraries**), e scansiona la stessa directory con Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Entrambi gli strumenti ora possiedono una riga per ogni file. Nulla viene duplicato su disco.

Se invece carichi in Immich normalmente (backup automatico da mobile, il caricatore web) e punti Facet verso la directory di upload di Immich, l'integrazione funziona esattamente allo stesso modo — cambiano solo i prefissi. In quel caso è Immich a possedere la struttura dei file, quindi riesegui la scansione di Facet dopo i caricamenti (oppure usa `--watch`).

## Passaggio 2 — crea una chiave API

In Immich: **click your avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 permette di limitare lo scope di una chiave invece di concederle tutto. Facet ha bisogno esattamente di sei scope:

| Scope | Cosa ne fa Facet |
|-------|-------------------------|
| `server.about` | Controllo di connettività/autenticazione di `--immich-test` |
| `asset.read` | Risolve gli asset tramite `originalPath` |
| `asset.update` | Scrive `rating` e `isFavorite` |
| `album.read` | Trova un album delle scelte migliori esistente in base al nome |
| `album.create` | Crea l'album delle scelte migliori la prima volta |
| `albumAsset.create` | Aggiunge foto all'album delle scelte migliori |

Ometti gli ultimi tre se lasci `push.top_picks_album` vuoto — Facet tocca gli album solo quando quel nome è impostato.

La chiave viene inviata come intestazione `x-api-key` a ogni richiesta. Inseriscila in `scoring_config.json`:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Una nota su `PUT /api/assets`.** Facet scrive le valutazioni con `PUT /api/assets`, che il documento OpenAPI di Immich segna come *deprecato*. Gli alias `PATCH` sostitutivi sono annunciati ma **assenti dalla specifica pubblicata**, quindi non c'è ancora nulla verso cui migrare — `PUT` resta l'unico endpoint effettivamente esistente, e Facet continua a usarlo. Ogni percorso Immich toccato da Facet vive in `ImmichClient` (`sync/immich.py`), quindi il giorno in cui le rotte `PATCH` verranno rilasciate, la modifica sarà confinata a una sola classe.

## Passaggio 3 — mappa i percorsi

Aggiungi una coppia per ogni radice che condividi. Vince la prima coppia il cui `facet_prefix` corrisponde a una foto:

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

Lascia intatto il placeholder di serie (`{"facet_prefix": "", "immich_prefix": ""}`) e i percorsi passano invariati — corretto solo quando Facet e Immich vedono davvero percorsi assoluti identici, il che accade se esegui Facet dentro il namespace del container di Immich, e quasi mai altrimenti.

Per leggere il valore reale, apri una qualsiasi foto in Immich, premi `i` per il pannello informazioni, e confronta il percorso del file mostrato lì con il percorso che Facet riporta per la stessa foto.

## Passaggio 4 — verifica, poi invia

```bash
# Solo connettività + autenticazione. Nessuna scrittura.
python facet.py --immich-test

# Risolve ogni asset e riporta cosa CAMBIEREBBE. Ancora nessuna scrittura.
python facet.py --immich-sync --dry-run

# Per davvero.
python facet.py --immich-sync
```

La sincronizzazione riporta `matched` / `unmatched` / `updated` / `skipped (unrated)` / album creati. Una prima esecuzione con un conteggio `unmatched` elevato significa quasi sempre che la mappatura dei percorsi è sbagliata — vedi [Risoluzione dei problemi](#risoluzione-dei-problemi).

Cosa viene inviato:

- **Valutazioni a stelle 1–5** → il `rating` di Immich. Una foto che non hai mai valutato non invia nulla.
- **Preferiti** → `isFavorite` di Immich.
- **Azzeramento.** Se hai valutato una foto 5, hai sincronizzato, e poi l'hai riportata a non valutata, la sincronizzazione successiva invia `rating: null` così che anche Immich se ne dimentichi. Facet ricorda cosa ha inviato l'ultima volta (nella tabella satellite `stats_cache`) proprio per non perdere questa transizione. È `null` e mai `0` — Immich v3 rifiuta `0` categoricamente, e un solo batch rifiutato interrompe l'intera sincronizzazione.
- **Un album delle scelte migliori facoltativo**, popolato a partire da `push.top_picks_min_rating`, quando `push.top_picks_album` ne indica uno.

In modalità multiutente, `--immich-sync --user alice` invia le valutazioni di `user_preferences` di Alice invece delle colonne globali, e tiene traccia del proprio stato nel suo scope personale.

## Invio dei rifiuti

Disattivato per impostazione predefinita. Attivalo e una foto che hai rifiutato nella camera oscura di selezione di Facet riceve anche il proprio marcatore di rifiutata in Immich:

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
- **Il rifiuto prevale sulle stelle.** Una foto rifiutata con 5 stelle invia `-1`, non `5` — l'hai scartata, ed è questo il fatto che vale la pena rispecchiare.
- **Annullare il rifiuto lo azzera.** Una foto che aveva inviato `-1` e che viene successivamente ripristinata dal rifiuto invia invece la sua valutazione a stelle attuale, oppure `rating: null` se non ne ha una. Stesso meccanismo di stato tracciato di ogni altro azzeramento.
- Una foto rifiutata non entra mai a far parte dell'album delle scelte migliori.
- `push.ratings: false` lo sopprime. `-1` è una scrittura di valutazione, quindi una configurazione che ha disattivato l'invio delle valutazioni non se ne vede reintrodurre una di nascosto.

Lascialo disattivato se altre persone (o il tuo telefono) guardano la libreria Immich: un `-1` è visibile lì, e «rifiutata in Facet» è un giudizio di lavoro che potresti non voler diffondere.

## Il webhook in entrata

Tutto quanto sopra è Facet → Immich. Il webhook è la direzione opposta: Immich comunica a Facet che un asset è appena cambiato, e Facet risponde immediatamente con ciò che sa a riguardo.

**È disattivato per impostazione predefinita e non avvia mai una scansione.** Un webhook è una chiamata proveniente da un altro demone che non passa per l'autenticazione di sessione; lasciargliene generare un carico GPU darebbe a chiunque possieda il token un modo per mettere in ginocchio la tua macchina. Ecco cosa fa invece:

- **Foto conosciuta e valutata** → la sua valutazione/preferito viene inviata immediatamente a Immich, seduta stante, come aggiornamento di un singolo asset. È quello che chiude il ciclo dopo una scansione: valuti una foto, la carichi, e la valutazione arriva in Immich senza dover aspettare il successivo `--immich-sync`.
- **Foto sconosciuta o non ancora valutata** → il percorso viene memorizzato in un elenco di attesa limitato e deduplicato, e il successivo `--immich-sync` lo registra nel log. Nessuna scansione viene avviata.

### Attivalo

Il token è un segreto condiviso, quindi vive nell'ambiente, mai in `scoring_config.json` (quel file viene riscritto sul posto da diversi endpoint ed è leggibile da chiunque nella maggior parte delle installazioni). La configurazione nomina la *variabile*; la *variabile* contiene il *valore*.

1. Genera un token ed esportalo ovunque venga avviato il viewer — la tua unit systemd, `docker-compose.yml`, o il profilo della shell:

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

Un `token_env` vuoto, oppure una variabile non impostata o vuota, disabilita completamente l'endpoint — restituisce **404**, esattamente come `frame.tokens` e `upload.username`. Non esiste uno stato intermedio.

### Punta Immich verso questo endpoint

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — scegli l'evento sull'asset che vuoi rispecchiare. `Asset uploaded` è quello utile; aggiungi `Asset updated` se vuoi che anche le modifiche riattivino l'invio.
2. **Action** — scegli **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, usando un indirizzo che il container di Immich possa effettivamente raggiungere. Se entrambi girano in Docker sullo stesso host, si tratta del nome del servizio (`http://facet:5000/…`), non `localhost`.
4. **Header** — nome `x-facet-token`, valore il token che hai generato. Il nome deve corrispondere a `webhook.header`; rinomina entrambi insieme se la tua configurazione ne richiede uno diverso. È accettato anche `Authorization: Bearer <token>`, per i proxy che offrono solo quello.
5. Salva, poi carica una foto per confermare.

### Cosa risponde l'endpoint

| Stato | Significato |
|--------|---------|
| `202` | Corpo compreso. Il riepilogo JSON riporta `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON valido, ma nessun asset che Facet riconosce. Registrato nel log, non un errore — la forma del payload è di competenza di Immich e può cambiare. |
| `400` | Il corpo non era affatto JSON. |
| `401` | Nessun token nella richiesta. |
| `403` | Token errato. |
| `404` | La funzionalità è disattivata (nessun token configurato). |

Facet legge `originalPath` dal payload ed è deliberatamente permissivo su dove si trovi — un oggetto asset nudo, `{"asset": {…}}`, un elenco, o uno qualunque di questi annidato sotto `data` / `items` / `assets` funziona. Se il payload porta l'`id` dell'asset, Facet lo usa e salta un giro di ricerca.

I percorsi in attesa vengono riportati dalla sincronizzazione successiva:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scansiona quelle foto (`python facet.py /mnt/photos`) e spariranno dall'elenco alla sincronizzazione successiva. L'elenco è limitato a `max_pending` voci, con le più vecchie scartate per prime, così un Immich chiacchierone non può mai farlo crescere senza limiti.

### Note sulla sicurezza

- Il token viene confrontato a tempo costante. Un token errato restituisce semplicemente `403`, senza alcun segnale temporale.
- Servi il viewer via HTTPS se Immich lo raggiunge attraverso qualcosa di meno affidabile di una rete bridge privata — il token viaggia in un'intestazione a ogni invio.
- Ruota il token cambiando insieme la variabile d'ambiente e l'intestazione del workflow di Immich, poi riavviando il viewer.
- Il webhook legge le colonne di valutazione globali, quindi in modalità multiutente rispecchia la valutazione condivisa/globale, non la sovrapposizione di un singolo utente. Se in Immich vuoi le valutazioni per utente, lascia disattivato il webhook e usa `--immich-sync --user <nome>` secondo una pianificazione.

## Riferimento di configurazione

Il blocco `immich` completo, con i valori predefiniti forniti di serie:

```json
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
```

| Impostazione | Predefinito | Descrizione |
|-----|---------|---------|
| `url` | `""` | URL di base di Immich, `http` o `https`. Uno slash finale viene rimosso. |
| `api_key` | `""` | Chiave API, inviata come `x-api-key`. Se vuota, interrompe ogni sincronizzazione con un errore chiaro. |
| `path_map` | una coppia vuota | Riscritture di prefisso tra i percorsi di Facet e i valori `originalPath` di Immich. Vince la prima corrispondenza; usato in entrambe le direzioni. |
| `push.ratings` | `true` | Invia le valutazioni a stelle 1–5 (e i relativi azzeramenti). |
| `push.favorites` | `true` | Invia `isFavorite` (e i relativi azzeramenti). |
| `push.rejected` | `false` | Invia `rating: -1` per le foto rifiutate in Facet. Richiede `push.ratings`. |
| `push.top_picks_album` | `""` | Nome dell'album da popolare. Vuoto significa che Facet non tocca mai gli album. |
| `push.top_picks_min_rating` | `4` | Valutazione a stelle minima per quell'album. |
| `webhook.token_env` | `""` | Nome della variabile d'ambiente che contiene il segreto del webhook. Vuoto ⇒ l'endpoint restituisce 404. |
| `webhook.header` | `"x-facet-token"` | Intestazione in cui Immich invia il token. |
| `webhook.max_pending` | `500` | Limite massimo dell'elenco dei percorsi memorizzati ma non ancora valutati. |
| `timeout_seconds` | `30` | Timeout HTTP per singola richiesta. |

## Risoluzione dei problemi

### Tutto risulta `unmatched`

La mappatura dei percorsi è sbagliata — è di gran lunga il problema più frequente.

1. Apri una foto in Immich e premi `i`. Annota il percorso nel pannello informazioni.
2. Trova il percorso della stessa foto in Facet (il pannello dettagli della galleria, oppure `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. I due condividono un *suffisso*. Ciò che differisce è il prefisso, e quei due prefissi sono esattamente `facet_prefix` e `immich_prefix`.

Trappole comuni:

- **Uno slash finale mancante.** `"/mnt/photos"` → `"/usr/src/app/external"` riscrive anche `/mnt/photosXYZ/a.jpg`. Termina sempre entrambi i prefissi con `/`.
- **Percorso host contro percorso container.** Il percorso di Immich è quello visto dal *container*. `docker compose exec immich-server ls /usr/src/app/external` chiarisce la questione.
- **Symlink e bind mount.** Immich memorizza il percorso che ha percorso durante la scansione. Se la tua libreria viene raggiunta tramite un symlink da un lato, le stringhe differiscono anche se il file è uno solo.
- **Maiuscole/minuscole e Unicode.** Il confronto è esatto. Una libreria su una condivisione case-insensitive può contenere sia `/Photos/` sia `/photos/`; corrisponde solo la grafia effettivamente memorizzata.
- **Immich non ha ancora indicizzato il file.** Esegui **Scan All Libraries** e verifica che l'asset esista davvero in Immich prima di dare la colpa alla mappatura.

`--immich-sync --dry-run` elenca nel log i primi 20 percorsi unmatched; quell'elenco di solito individua a colpo d'occhio il prefisso sbagliato.

### `--immich-test` fallisce

- `Unsupported Immich URL scheme` — `url` deve iniziare con `http://` o `https://`.
- `HTTP 401` — la chiave API è sbagliata o è stata revocata.
- `HTTP 403` — la chiave è valida ma le manca `server.about`. Ricreala con i sei scope elencati sopra.
- Connessione rifiutata / timeout — la porta è sbagliata, oppure Facet non riesce a raggiungere il container. Verifica con `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` dalla macchina che esegue Facet.

### Il webhook restituisce 404

La funzionalità è disattivata. O `webhook.token_env` è vuoto, oppure la variabile che indica non è impostata o è vuota *nell'ambiente del viewer stesso*. Esportarla nella tua shell interattiva non ha alcun effetto per un viewer gestito da systemd o Docker — impostala nel file unit o nel file compose e riavvia.

### Il webhook restituisce 401 o 403

`401` significa che non è arrivato alcun token: il nome dell'intestazione inviata da Immich non corrisponde a `webhook.header`. `403` significa che è arrivato un token, ma era sbagliato — confronta il valore dell'intestazione del workflow con la variabile d'ambiente, carattere per carattere.

### Le valutazioni vengono inviate, ma gli azzeramenti no

Facet invia un azzeramento solo per una foto che ha effettivamente inviato in precedenza; questa memoria vive in `stats_cache` nel database di Facet. Ripristinare un database più vecchio (o partire da uno nuovo) la fa perdere, e una valutazione azzerata durante quell'intervallo non verrà rimossa in Immich. Rivaluta e riazzera la foto, oppure correggila direttamente in Immich.

### Le valutazioni compaiono sulle foto sbagliate

Due file con lo stesso `originalPath` non possono esistere dentro Immich, ma due radici *Facet* che si mappano su un unico prefisso Immich possono collidere. Verifica che le tue coppie `path_map` non si sovrappongano: vince la prima coppia corrispondente, quindi una coppia ampia elencata prima di una più specifica la inghiotte.

### `rating: 0 is not valid`

Il server Immich è più vecchio della 3.0. Aggiornalo — la semantica di azzeramento di Facet richiede `null`, e `push.rejected` richiede `-1`; non esiste alcun fallback che funzioni sulla 2.x.

---

**Vedi anche:** [Comandi — Immich Sync](COMMANDS.md#immich-sync) · [Configurazione](CONFIGURATION.md) · [Ricette di interoperabilità con gli editor](INTEROP.md) per il roundtrip XMP con Lightroom, darktable e digiKam.
