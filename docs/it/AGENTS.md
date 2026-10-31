# Agenti IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · **Italiano** · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet può fungere da server [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), così un assistente IA compatibile con MCP può cercare e ispezionare la tua libreria con i filtri della galleria. Espone quattordici strumenti di lettura che non modificano nulla e quindici strumenti `ui_*` che pilotano la scheda del browser che hai aperto (pagina, filtri, selezione) senza scrivere dati della libreria. I token con un livello sufficiente possono anche [modificare la libreria](#modificare-la-libreria) (valutazioni, indicatori, tag, album, selezione ed eliminazione) e usare la [camera oscura](#camera-oscura-gruppi-di-selezione).

## Attivarlo

L'endpoint è **attivo per impostazione predefinita**. Per spegnerlo, imposta `viewer.mcp.enabled` su `false` in `scoring_config.json` (vedi [Endpoint agente (MCP)](CONFIGURATION.md#endpoint-agente-mcp)), poi riavvia il viewer o ricarica la configurazione. `/mcp` e ogni route `/api/mcp/*` rispondono allora 404.

**Installazioni aperte.** Senza `viewer.password` l'installazione è considerata aperta, anche se `viewer.edition_password` è impostata. In un'installazione aperta:

- i token sono `readonly`, a meno che `viewer.trusted_local_editing` sia attivo, oppure il token è di modifica completa, creato in una sessione con la password di modifica e usato dallo stesso computer (vedi sotto);
- l'endpoint serve solo una chiave anonima in sola lettura, che non concede nulla che l'`/api` aperta non conceda già;
- i token si gestiscono solo dal computer su cui gira Facet, o in una sessione di modifica quando `viewer.edition_password` è impostata (vedi [Creare un token](#creare-un-token)).

L'endpoint è `POST /mcp` sulla porta del viewer: Streamable HTTP, senza stato, risposte JSON semplici (`GET` risponde 405). Solo il ponte della scheda, `/api/mcp/bridge`, è un WebSocket; vedi [Controllare la scheda aperta](#controllare-la-scheda-aperta).

## Creare un token

Il modo più semplice è il browser:

1. Con `viewer.mcp.enabled` attivo, apri il menu dell'account e scegli **Collega un assistente**.
2. Inserisci un **Nome** e scegli **Cosa può fare l'assistente**: **Solo lettura e controllo**, **Agisci come me** o **Modifica completa**. Un token non può superare la sessione che lo crea.
3. Fai clic su **Crea token**. La finestra mostra **Incolla questo nel tuo assistente**, un prompt già pronto che contiene il token. Viene mostrato una sola volta: fai clic su **Copia il prompt**, incollalo nel tuo assistente e fai clic su **Fatto**.

**Gestisci i token (N)** elenca i tuoi token con l'ultimo utilizzo e permette di revocarne uno. Una riga di stato indica se questa scheda è connessa, così gli assistenti possono pilotarla.

La finestra offre solo i livelli che il server concederà:

- un'installazione aperta offre **Solo lettura e controllo**, più **Modifica completa** nei casi indicati sotto;
- **Agisci come me** compare solo sulle installazioni multiutente;
- **Modifica completa** compare solo in una sessione di modifica; su un'installazione aperta significa un browser sullo stesso computer con `viewer.trusted_local_editing` attivo, oppure una sessione con accesso tramite `viewer.edition_password` (il token modifica allora solo dallo stesso computer).

Il prompt indica il livello effettivamente concesso. In un'installazione aperta, aperta da un'altra macchina senza una sessione di modifica, la finestra mostra «In un'installazione aperta i token dell'assistente si gestiscono solo dal computer su cui gira Facet. Imposta viewer.password per gestirli da un'altra macchina.» al posto del modulo.

Alternativa da script (curl):

Un assistente si autentica con un token personale che inizia con `fct_`. Creane uno con una richiesta autenticata. Il token viene restituito **una sola volta**; Facet conserva solo il suo hash SHA-256:

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

La risposta contiene il testo in chiaro in `token`.

- `GET /api/mcp/tokens` elenca i tuoi token (mai il segreto); `DELETE /api/mcp/tokens/{id}` ne revoca uno.
- Un superadmin può elencare i token di tutti i proprietari con `?all=1` e revocarne qualsiasi.
- Ogni proprietario può avere al massimo 20 token attivi.
- Queste route rifiutano le credenziali di un agente, quindi un assistente non può mai creare, elencare o revocare token.

In un'installazione aperta (senza `viewer.password`) queste route rifiutano inoltre ogni richiesta che non arriva dal computer su cui gira Facet:

- una richiesta passata da un reverse proxy (qualsiasi header `Forwarded`, `X-Forwarded-*` o `X-Real-IP`);
- una richiesta a un IP della rete locale o a un nome host invece di `localhost`, `127.0.0.1` o `[::1]`;
- una richiesta che arriva dalla rete bridge di Docker.

Esegui la ricetta qui sopra sull'host di Facet (via SSH su un NAS; in Docker, `docker compose exec facet python -c "import urllib.request ..."`, perché l'immagine non ha curl), oppure imposta `viewer.password`. Una sessione autenticata con `viewer.edition_password` è accettata da qualsiasi macchina. Un reverse proxy deve inviare `X-Forwarded-For` o `Forwarded`, altrimenti viene trattato come la macchina locale.

## Collegare il tuo assistente

Il prompt della finestra contiene tutto ciò di cui un assistente ha bisogno: il nome del server `facet`, l'URL (`http://<host>/mcp`), il trasporto (Streamable HTTP), l'intestazione `Authorization: Bearer fct_...`, il livello concesso e una chiamata allo strumento `status` per verificare la connessione. Incollalo nel tuo assistente, oppure aggiungi tu stesso il server al tuo client MCP. Usa HTTPS quando il viewer è raggiungibile oltre la tua macchina: il token viaggia in un'intestazione a ogni chiamata.

## Livelli di autorizzazione

Un token viene creato con un livello concesso: `readonly`, `user` o `edition`. A ogni chiamata il livello **effettivo** è ricalcolato come il più basso tra quello concesso e quello attuale del proprietario. Ogni strumento ha il proprio livello minimo, verificato prima di qualsiasi lettura o scrittura; un token di livello inferiore riceve `forbidden_level`.

- **Installazioni con password unica** non hanno il livello `user`. Un livello `user` è limitato a `readonly` alla creazione e il livello effettivo è `edition` o `readonly`. Gli strumenti contrassegnati `user` in [Modificare la libreria](#modificare-la-libreria) richiedono quindi un token `edition`; un token di livello inferiore riceve `forbidden_level`, indicando che serve `edition`. Un token `edition` richiede una sessione di modifica e funziona solo finché la password di modifica non cambia.
- **Installazioni multiutente.** Se il proprietario viene retrocesso, un token `edition` scende a `user`. Una promozione non porta mai un token oltre il livello concesso.
- **Installazioni aperte** (nessun `viewer.password`, anche se `viewer.edition_password` è impostata). I token appartengono a un proprietario condiviso `_anonymous` e sono `readonly`, a meno che `viewer.trusted_local_editing` sia attivo o il token proviene da una sessione di modifica (i due punti successivi).
- **Modifica locale su un'installazione aperta.** Con `viewer.trusted_local_editing` attivo, la finestra Collega può creare **Modifica completa** da un browser sullo stesso computer. Servono ancora `viewer.mcp.enabled` e un token (una chiamata senza token resta 401).
  - Il token è `edition` solo per le richieste `/mcp` provenienti dalla stessa macchina: peer in loopback, URL `http://localhost:<port>` o `127.0.0.1` e nessuna intestazione di proxy. Valgono sia `:4200` (il proxy di sviluppo di `ng serve`) sia `:5000`.
  - Qualsiasi altra richiesta diventa `readonly`, anche se il prompt dice Modifica completa: un client della rete locale, un URL con nome host o `0.0.0.0`, o una distribuzione Docker.
  - Impostare una qualsiasi password abbassa il token a `readonly`; rimuovere la password lo ripristina.
  - Gli strumenti di eliminazione richiedono ancora `viewer.mcp.allow_destructive`.
  - La scansione (`start_scan`, `scan_status`) funziona senza `viewer.features.show_scan_button`, come per il browser locale.
- **Password di modifica su un'installazione aperta.** Con `viewer.edition_password` impostata e senza `viewer.password`, una sessione con accesso tramite la password di modifica può creare **Modifica completa**, da qualsiasi computer; ogni altra sessione riceve `readonly`.
  - Il token è `edition` solo per le richieste `/mcp` che superano lo stesso controllo di stesso computer visto sopra. Un client della LAN o una richiesta tramite proxy riceve `readonly`: il token è un segreto al portatore su un'installazione che chiunque può leggere.
  - Cambiare o cancellare la password di modifica lo riporta a `readonly`; creane uno nuovo dopo la modifica.
  - La scansione richiede ancora `viewer.features.show_scan_button`, come una sessione di modifica nel browser. Gli strumenti di eliminazione richiedono ancora `viewer.mcp.allow_destructive`.

> **Avvertenza:** `ng serve --host 0.0.0.0`, o qualsiasi proxy sullo stesso host che non aggiunga intestazioni di proxy, lascia passare come locale un client della rete locale che invii `Host: localhost`. A proteggere `/mcp` resta allora solo il token.

Un token smette di funzionare quando cambiano le credenziali del suo proprietario: la password del viewer o di modifica (modalità password unica), la password del proprietario (modalità multiutente) oppure l'eliminazione dell'account del proprietario. Risponde allora 401.

## Strumenti

I quattordici strumenti dati sono di sola lettura:

| Strumento | Cosa fa |
|------|--------------|
| `search_photos` | Filtra e ordina la libreria come la galleria, applicando le esclusioni predefinite del visualizzatore (occhi chiusi, raffiche, duplicati, bracketing, panorami, scartate) salvo che il filtro le imposti (riporta `hidden_summary`). Mostrato per impostazione predefinita nella scheda aperta (vedi sotto); `fields` aggiunge qualsiasi colonna della foto |
| `semantic_search` | Trova foto per significato, o per parole nelle didascalie con `scope: "text"` Le righe restituite vengono fissate nella scheda. `filters` restringono la ricerca come quelli della galleria, e ogni riga porta la sua `similarity`. |
| `get_photo` | Dettaglio completo di una foto dal suo percorso (senza istogramma); oppure `target: "selection"` (con `tab_id`) per l'unica foto selezionata |
| `get_photo_stack` | Legge la pila locale per percorso esatto, o null |
| `get_thumbnail` | Guardare una foto: la miniatura come parte immagine (`size` da 160 a 640, predefinito 512). Si usa una dimensione minore se il JPEG supererebbe `viewer.mcp.max_image_bytes`; `too_large` se nessuna è sufficiente; oppure `target: "selection"` (con `tab_id`) per l'unica foto selezionata |
| `contact_sheet` | Guardare da 1 a 16 foto come un'unica griglia numerata (`columns` da 2 a 4, lato più lungo 1024). La parte di testo elenca `legend` (numero della cella e percorso, nell'ordine richiesto) e `unavailable` (celle lasciate vuote perché la foto manca o non è visibile); oppure `target: "selection"` per le foto selezionate (al massimo 16) |
| `possible_faces` | Volti simili a una persona riconosciuta: similarità coseno con il centroide della persona, i migliori per primi, solo lo stesso modello di embedding. `scope` è `unassigned` (predefinito), `unnamed` (volti senza gruppo o in un gruppo che nessuno ha nominato), `other_persons` o `all`; `min_similarity` è 0,30 per impostazione predefinita; `limit` fino a 100. Una scansione oltre 192000 volti è rifiutata (`too_large`): restringere con `scope`, `path_prefix`, `date_from` o `date_to`. Le foto sono mostrate nella scheda. Ogni riga include il campo `owner` (`ungrouped`, `unnamed_group` o `named`). `candidates` è il numero di volti nell'ambito che puoi vedere, prima del controllo della dimensione dell'embedding; `faces_scanned` è il numero di righe effettivamente valutate. |
| `similar_photos` | Foto simili a una foto, per embedding visivo o per colore; `min_similarity` (da 0 a 1) imposta la soglia |
| `filter_options` | Il vocabolario accettato da un filtro: fotocamere, obiettivi, tag, persone, pattern, categorie, momenti narrativi, tipi di scarto, intervalli delle metriche |
| `list_persons` | Persone riconosciute, filtrabili per nome; `show: true` apre `/persons` con questa ricerca |
| `list_albums` | Album visibili al proprietario del token; `show: true` apre `/albums` con questa ricerca |
| `library_stats` | Statistiche della libreria: `kind` sceglie il riepilogo di dimensione e punteggi (predefinito) o qualsiasi dato della pagina Statistiche (vedi sotto) |
| `status` | Chi è il token, il suo livello effettivo, i flag del server e le schede aperte che può pilotare |
| `available_actions` | Le attività che si applicano ora alla scheda aperta e a questo token, ciascuna con i suoi strumenti; gli strumenti oltre il livello del token non sono elencati |

Note sui filtri:

- `show_rejected` è un booleano: `true` elenca solo le foto scartate, `false` o omesso dà l'elenco normale. Gli agenti possono impostarlo con `ui_set_gallery_filters` per mostrare nella scheda le ricerche delle sole scartate. Anche gli album intelligenti possono salvarlo (false viene omesso).
- Un `review_status` esplicito determina lo stato di revisione al posto di `show_rejected` o `hide_rejected`, e disattiva `show_rejected` nella scheda.
- `show_rejected: true` con `favorites_only: true` viene rifiutato dalle modifiche della scheda e dalla creazione di album intelligenti (`invalid_input`). Una ricerca restituisce comunque l'intersezione, ma segnala `shown_in_tab.reason: invalid_combination` e lascia invariata la scheda.
- Anche `blinks_only` e `duplicates_only` sono booleani. `true` mantiene solo le foto contrassegnate come occhi chiusi, o i membri di un gruppo di duplicati (guide incluse). Come `show_rejected`, mostrano ognuna di queste foto indipendentemente dagli interruttori di nascondimento.

## I risultati compaiono nella tua scheda

- **Le ricerche compaiono nella tua scheda.** `search_photos`, `semantic_search` e `similar_photos` accettano `show` (predefinito `true`). Dopo una ricerca riuscita sulla prima pagina, il server la mostra nella scheda Facet aperta, così vedi ciò che l'assistente ha trovato senza dover chiedere.
  - `search_photos` e `similar_photos` applicano la stessa query alla scheda, sostituendone i filtri.
  - `semantic_search` fissa esattamente le righe restituite (ordine di somiglianza, al massimo `limit`, con o senza `filters` o `scope`) come elenco scelto dall'assistente (`shown_in_tab.mode` è `paths`), perché la vista semantica propria della scheda filtra e ordina in modo diverso.
  - `show: false` serve per le sonde intermedie e i conteggi; agli assistenti si dice di non chiedere mai se mostrare i risultati.
- Il risultato contiene `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, oppure `{"applied": false, "reason"}`. Motivi: `error` (la visualizzazione stessa è fallita), `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (la scheda può ancora applicarla), `forbidden`, `invalid_input`, `upstream_error`, `page_not_first`, `empty_result`, `unsupported_filters` (con `keys`), `invalid_combination`, `unsaved_decisions`, `navigation_refused` (la scheda ha rifiutato la navigazione), `comparison_open` (l'utente è su `/compare`) e `modal_open` (una finestra di dialogo, un bottom sheet o una presentazione è aperta nella scheda). Una visualizzazione fallita non fa mai fallire la ricerca. Passa `tab_id` per scegliere una scheda. Quando le righe vengono accorciate, `next_page` (con `suggested_per_page`) indica la pagina che continua subito dopo l'ultima riga restituita; quando le pagine non possono esprimerlo, `next_offset` lo dà come offset di riga.
- Viene mostrata solo la prima pagina (la scheda pagina da sola durante lo scorrimento). Un risultato vuoto non viene mostrato, così mantieni la vista precedente. Una ricerca con filtri per cui la barra laterale della galleria non ha un campo (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`) non viene mai applicata parzialmente.
- Una visualizzazione lascia `/photo` per la galleria. Lascia `/culling` solo se l'utente non vi ha decisioni non confermate (altrimenti `unsaved_decisions`), e su `/compare` viene rifiutata con `comparison_open`. Azzera una selezione dell'intera vista. In una pagina di album torna prima alla galleria, così i filtri salvati dell'album non vengono mai sovrascritti. Una ricerca il cui conteggio alimenta `expected_count` di uno strumento di scrittura deve usare `show: false`.
- `list_albums`, `list_persons` e `junk_list` accettano `show` (predefinito `false`: sono per lo più ricerche di nomi). Con `show: true` aprono `/albums`, `/persons` o `/junk` con esattamente quella query; una query vuota cancella la ricerca della pagina e reimposta gli altri filtri. `junk_list` mostra solo la prima pagina (altrimenti `page_not_first`) e mai un elenco vuoto (`empty_result`). `shown_in_tab` riporta gli stessi motivi di una ricerca, con `mode` `route`. `list_culling_groups` non ha `show`: usa `ui_show_culling_group`.
- `ui_show_photos` fissa un elenco esatto di foto, mostrate nel tuo ordine finché una modifica dei filtri non lo sostituisce. `ui_get_context` indica se è mostrato un elenco fissato. L'elenco è semplice: nessun gruppo, segno o etichetta. Per rivedere un piano di selezione, l'assistente usa `auto_cull`, che apre il piano nella [camera oscura](#camera-oscura-gruppi-di-selezione) (`/culling`).
- **Modalità piano su `/culling`.** `ui_show_culling_plan` (chiamato da `auto_cull` in una prova) carica un piano `auto_cull` nella camera oscura. Ottieni gli stessi gruppi, bordi tieni/scarta, lente e confronto della selezione manuale, con le foto da tenere del piano preselezionate. Vedi [Modalità piano dell'assistente](VIEWER.md#modalità-piano-dellassistente).
  - L'utente vede un banner «Piano dell'assistente · x/y confermati · Esci», un chip «#n · motivo · suggerito: tenere N / scartare M» per gruppo, e conferma gruppo per gruppo come al solito. Ordinamento e soglia sono disattivati; il cursore del rigore resta utilizzabile.
  - Spostare il cursore, o cambiare l'intervallo di date nella barra degli strumenti, ripianifica (nuovo `plan_digest`). I gruppi che hai invertito mantengono la tua scelta. Un gruppo si riforma come confermato quando ricade dentro un gruppo che hai confermato, gruppi di scena compresi; con `group_by=all`, un burst confermato le cui foto tenute ricompaiono in un gruppo similar più grande viene riproposto (i tuoi scarti restano applicati). I gruppi saltati tornano. Una conferma il cui conto alla rovescia è ancora in corso viene registrata subito. Conferma, salta e «conferma tutto» sono sospesi finché non arriva il nuovo piano.
  - Un intervallo di date più stretto riporta le inversioni e i gruppi confermati in base all'insieme di foto. I gruppi fuori dalla finestra spariscono e una notifica segnala le inversioni perse. **Tutte le date** ripianifica l'intera libreria e può raggiungere il limite del piano (`plan_truncated`).
  - **Esci**, o un cambio di raggruppamento, di ambito album/scena o di ordinamento, lascia la modalità piano. Uscire da `/culling` e tornare ripristina il piano. Un ricaricamento completo della pagina lo scarta ma mantiene nell'URL il suo album e le sue date (`?from=`, `?to=`), su un flusso manuale. Le conferme in modalità piano non aggiungono mai highlight.
  - **Badge di suggerimento.** `ui_suggest_culling` segna le foto da tenere o scartare, con un breve motivo (un badge tratteggiato), e aggiunge note ai gruppi (un chip nell'intestazione). Un clic su un badge inverte quella foto; senza clic nulla cambia. I segni sopravvivono ai cambi del cursore o dell'intervallo di date e a una nuova visualizzazione dello stesso piano; un piano diverso, **Esci** o l'uscita dalla modalità piano li cancella. I badge compaiono solo sulle miniature del gruppo, non nella vista a schermo intero né nei gruppi confermati o saltati.
  - La risposta dell'assistente elenca i percorsi non conservati: `redundant` (già la scelta del piano), `closed` (gruppo confermato o saltato) e `missing` (non nel piano). Le note di un gruppo che hai confermato, saltato o stai confermando sono elencate in `groups_closed`. `suggestions_total` e `notes_total` indicano ciò che la scheda conserva (al massimo 300 suggerimenti e 100 note).
- **Leggere i tuoi progressi.** `ui_get_context.culling` è `null` fuori dalla modalità piano. In modalità piano restituisce `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}`:
  - `confirmed`: i numeri dei gruppi del piano la cui conferma è andata a buon fine.
  - `pending`: i gruppi che hai invertito rispetto al piano senza confermarli.
  - `untouched`: il numero degli altri gruppi.
  - `changed`: ogni gruppo le cui foto tenute differiscono dal piano, come `{type, group_id, number, keep_paths, reject_paths}`.
  - `plan_truncated` è `true` quando il piano stesso ha raggiunto il tetto di gruppi o di foto ed elenca solo una parte dei gruppi.
  - Un blocco troppo grande per una risposta (il tetto di 100 KiB della scheda, o quello del server) ha le liste accorciate e `truncated` impostato a `true`. I conteggi veri restano in `groups_total`, `confirmed_count`, `pending_count` e `changed_count`.
  - `culling.scope` (`{album_id, date_from, date_to}`) è la finestra per cui il piano è stato calcolato.
  - `suggestions_open` (`[{path, action}]`) elenca i segni ancora in attesa del tuo clic, `suggestions_accepted` i segni la cui foto hai portato nello stato suggerito e `suggestions_total` i segni sulle foto conservati nella scheda (non le note di gruppo). `suggestions_open_count` riporta la lunghezza reale quando quella lista viene tagliata.

  Non ridecidere mai un gruppo confermato. Un gruppo burst o similar confermato esce dall'anteprima successiva. Un gruppo scene confermato non è registrato da nessuna parte e può essere riproposto, quindi passa `changed` come `keep_paths` / `remove_paths` alla prossima prova e alla sua applicazione. `auto_cull` prende le date solo dai propri argomenti: passa le date di `culling.scope` insieme a `culling.changed` alla prossima prova (il nuovo piano sostituisce quello mostrato). Spostare il cursore o l'intervallo di date ripianifica, quindi rileggi `ui_get_context` prima della prossima prova.
- **Impostazioni predefinite della selezione.** `ui_get_context` restituisce anche `culling_defaults`, `{profile, strictness}`: le impostazioni che `auto_cull` usa quando non riceve né l'una né l'altra (vedi **Impostazioni dalla scheda** sotto [Camera oscura](#camera-oscura-gruppi-di-selezione)). Sono memorizzate per browser, quindi due schede le condividono. `culling_defaults.strictness` è il valore vivo e memorizzato del cursore: `null` quando è memorizzato solo un profilo, 100 quando non è memorizzato nulla. Un piano dato con sia un profilo sia una `strictness` memorizza entrambi. Spostare il cursore fuori dalla modalità piano cancella il profilo memorizzato (miscela personalizzata); in modalità piano lo mantiene.
- **Date.** Gli strumenti di selezione (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) accettano una data ISO (`2026-06-01`), una data e ora ISO (`2026-06-01T08:30:00` o con spazio) o la forma EXIF (`2026:06:01 08:30:00`). Un `date_to` senza ora copre l'intera giornata. Gli strumenti a granularità di giorno (`library_stats`, `possible_faces`, i conteggi di `cull_report` e i gruppi della camera oscura) accettano solo una data e rifiutano un'ora con `invalid_input`.
- Le righe contengono fotocamera, obiettivo, apertura, tempo di posa, ISO, lunghezza focale e `is_monochrome`. `fields` (sui tre strumenti di ricerca) aggiunge qualsiasi altra colonna della foto tranne i dati di immagine e di embedding, ad esempio `leading_lines_score`. `learned_score` è valorizzato solo ordinando per esso. Quando il limite di byte accorcia le righe, il risultato aggiunge `returned` (e `next_offset` o `suggested_per_page`).
- `library_stats` accetta `kind` (predefinito `overview`: dimensione, conteggi per tipo e riepilogo dei punteggi). Il `basis` della panoramica indica cosa conta ogni totale. `total_photos` conta le foto che puoi vedere entro `date_from`/`date_to` e la categoria (tutte se non ne è indicata alcuna); ignora gli interruttori di nascondimento e include le foto scartate. `type_counts` applica gli interruttori di nascondimento e ignora data e categoria. Gli altri valori sono di sola lettura e restituiscono i dati della pagina Statistiche; le liste lunghe sono tagliate a 50 voci con `truncated: true`:

| Valore di kind | Dati |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | I pannelli della pagina Statistiche; accettano `date_from`, `date_to` e `category`. `correlations` accetta anche `x`, `y` (elenco separato da virgole), `group_by` e `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Statistiche per categoria (senza parametri) |
| `timeline_dates`, `timeline_months` | Numero di foto per giorno o per mese; richiedono `year` (`timeline_dates` accetta anche `month`) |
| `timeline_years` | Numero di foto per anno |

## Controllare la scheda aperta

Accanto agli strumenti dati, il server elenca sempre quindici strumenti `ui_*` che agiscono sulla scheda Facet che hai aperto: cambiano pagina, modificano filtri o selezione e rileggono ciò che vedi. Non scrivono mai dati della libreria, quindi basta un token `readonly`.

| Strumento | Cosa fa |
|-----------|---------|
| `ui_navigate` | Andare a una pagina (galleria, persone, album, statistiche, ...) |
| `ui_set_gallery_filters` | Unire una modifica ai filtri e all'ordinamento della galleria (`null` rimuove un filtro, `replace: true` riparte da zero) |
| `ui_get_gallery_view` | Route, filtri attivi, totale dei risultati, primi percorsi di foto visibili e numero di foto selezionate; restituisce anche `album_filter_json` (i filtri come li memorizzerebbe un album intelligente) e `filters_scopable` (se descrivono l'intera vista) |
| `ui_get_context` | La pagina aperta (route), lo stato della galleria (totale, numero caricato, se è mostrato un elenco fissato), il numero di foto selezionate e le `actions` che qui si applicano al tuo token; inoltre `focused` (la foto su cui si trova l'utente), `culling` (il piano dell'assistente su `/culling`: gruppi confermati, in sospeso e modificati, e lo `scope` per cui è stato calcolato), `culling_defaults` (`{profile, strictness}`: il profilo memorizzato e il rigore vivo e memorizzato del cursore, per browser; `auto_cull` usa entrambi quando non gliene viene dato nessuno) e `user_activity` (ciò che l'utente ha fatto), e accetta `activity_since` (vedi sotto); inoltre `page` e `overlays` (vedi sotto) |
| `ui_open_photo` | Aprire una foto |
| `ui_open_album` | Aprire un album (fisso o smart) tramite `album_id`; un id sconosciuto o inaccessibile risponde `not_found` |
| `ui_show_photos` | Mostra esattamente questi `paths` (fino a 200) in questo ordine come elenco della galleria; quelli irraggiungibili tornano in `missing`. Qualsiasi modifica dei filtri sostituisce l'elenco |
| `ui_select_photos` | Selezionare `paths` espliciti, o l'intera vista filtrata con `select_view: true`, in modalità `replace`, `add` o `remove` |
| `ui_clear_selection` | Svuotare la selezione |
| `ui_get_selection` | Lo `scope` (`paths` o `view`) e il `count`, con i `paths` oppure, per una vista, i `filters` e gli `excluded_paths` |
| `ui_next_page` | Caricare la pagina successiva della galleria |
| `ui_show_culling_group` | Aprire la camera oscura su un gruppo, identificato da `(type, group_id)` (account edition) |
| `ui_show_culling_plan` | Apre la camera oscura su un piano `auto_cull` (`plan_digest` e `request` dell'anteprima, `focus` facoltativo: numero di gruppo), con le foto da tenere del piano preselezionate perché tu le inverta e le confermi (account di modifica). `auto_cull` lo chiama per te in una prova. Lo stesso digest del piano già mostrato sposta solo il focus; uno diverso sostituisce il piano ed è rifiutato come `unsaved_decisions` finché hai decisioni non confermate, e come `plan_changed` quando la libreria è cambiata dopo l'anteprima, e come `plan_load_failed` quando la scheda non ha potuto caricare il piano per un altro motivo |
| `ui_suggest_culling` | Finché un piano è mostrato su `/culling`, segna le foto che terresti o scarteresti (`photos`: `path`, `action`, `reason`, fino a 100) e i gruppi da commentare (`groups`: il `path` di una foto del gruppo e una `note`, fino a 50); un motivo o una nota è lungo al massimo 200 caratteri. Vedi un badge per foto e un chip per gruppo, e nulla cambia finché non fai clic su un badge. Le chiamate si fondono per percorso, `replace: true` scarta prima tutto ciò che è conservato, e `replace` con liste vuote cancella tutto. Risponde `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}`; i rifiuti sono `no_plan` (la scheda non ha alcun piano), `too_large` (la scheda conserva al massimo 300 suggerimenti e 100 note: usa `replace`) e `forbidden_level` (solo account edition). Con più schede aperte, passa il `tab_id` di `shown_in_tab` o `status` |
| `ui_show_comparison` | Aprire la pagina del confronto a coppie, facoltativamente su una categoria, una strategia e un `tab` (`ab`, `snapshots`, `suggestions`, `weights`); apre solo la pagina, i vincitori li scegli tu |

Come funziona:

- **Connessione.** Finché sei connesso e `viewer.mcp.enabled` e `viewer.mcp.bridge` sono entrambi `true`, ogni scheda Facet apre un WebSocket della stessa origine verso `/api/mcp/bridge`, autenticato con la tua sessione nel primo messaggio. Il ponte è attivo per impostazione predefinita. Imposta `viewer.mcp.bridge` su `false` per disattivarlo: le schede allora non si connettono affatto e gli strumenti `ui_*` rispondono con un errore esplicito.
- **Di chi sono le schede.** Uno strumento raggiunge solo le schede del proprietario del token. Con una password unica tutte le sessioni sono lo stesso utente; su un'installazione aperta ogni scheda appartiene all'utente condiviso `_anonymous`, comprese le sessioni edition.
- **Livelli delle schede.** Ogni scheda porta il livello della sessione che l'ha aperta. Un token pilota solo le schede di livello pari o superiore al proprio livello effettivo: un token `edition` non usa mai una scheda con sessione di sola consultazione, mentre un token `readonly` può pilotare una scheda `edition`.
  - Installazione con password unica: un token è inoltre limitato dalla sessione che lo ha creato. Uno creato da una sessione di sola consultazione raggiunge solo le schede di consultazione, mai la scheda edition (un token precedente a questa regola è limitato al proprio livello).
  - Installazione aperta: un token raggiunge solo le schede di consultazione, mai una scheda `edition`, tranne la scheda di modifica locale qui sotto. Un token di modifica completa creato in una sessione con la password di modifica raggiunge una scheda `edition` se usato dallo stesso computer.
  - Con `viewer.trusted_local_editing` su un'installazione aperta, una scheda che supera il controllo «stessa macchina» si registra come `edition` e scende a `readonly` entro un ping quando l'opzione viene disattivata. Le schede della rete locale o inoltrate restano `readonly`. Un token usato dalla macchina locale raggiunge quella scheda qualunque sia il livello con cui è stato creato. Un token usato dalla rete locale non la raggiunge mai e riceve `no_tab`, con un messaggio che spiega che una richiesta non locale non può pilotare una scheda di modifica locale.
  - Una scheda può essere sostituita solo da una di livello pari o superiore: una sessione di sola consultazione che riusa il `tab_id` di una scheda edition viene rifiutata con 4409. Oltre il limite di schede per utente, esce per prima la scheda di livello più basso.
  - `status` elenca solo le schede che il token può pilotare e riporta `out_of_reach_tabs`, il numero di schede aperte che non può pilotare.
- **Più schede.** Viene usata l'ultima che ha avuto il focus e il campo `tab` del risultato lo indica. Passa `tab_id` (elencato da `status`) per sceglierne un'altra.
- Una scheda rifiuta ciò che il suo account non può fare (per esempio `/culling` per un account senza edition) e lo strumento restituisce quel rifiuto.
- Ciò che una scheda restituisce non è affidabile: profondità, lunghezza delle stringhe e delle liste sono limitate e il tutto è contenuto da `max_bytes`.
- Errori: `no_tab` (nessuna scheda collegata o aperta, o ponte disattivato: apri Facet in un browser e accedi), `tab_timeout` (nessuna risposta entro `call_timeout_s`) e `tab_outdated` (la scheda aperta non conosce lo strumento; ricarica la pagina dopo un aggiornamento di Facet).
- Il ponte accetta prima il WebSocket e poi lo rifiuta con un codice di chiusura, non con uno stato HTTP: 4404 se l'endpoint o il ponte è disattivato (la scheda resta allora disconnessa finché la pagina non viene ricaricata), 4403 se `Origin` manca o non è consentito, 4401 per una sessione mancante o rifiutata.
- **Reverse proxy.** Deve inoltrare l'upgrade WebSocket per `/api/mcp/bridge`; vedi [Distribuzione](DEPLOYMENT.md). Se riscrive l'intestazione `Host`, indica l'origine pubblica in `viewer.mcp.allowed_origins` (per esempio `["https://photos.example.com"]`): l'origine della pagina deve corrispondere all'host o essere in elenco.
- **Cosa sta facendo l'utente.** `ui_get_context` restituisce anche:
  - `focused`, `{path}`: la foto sotto il cursore da tastiera nella galleria, la foto aperta nella pagina foto o la foto corrente nella camera oscura; altrimenti `null`. Il passaggio del mouse non conta. Passare alla finestra dell'assistente la mantiene e si azzera quando la foto esce dall'elenco.
  - `user_activity`, `{items, until, truncated}`: ciò che l'utente ha fatto nella scheda, al massimo 50 voci di 20 percorsi ciascuna, conservando le più recenti. Non ha stato: passa l'`until` della risposta precedente come `activity_since` per ottenere solo le voci più recenti; due chiamate senza di esso restituiscono le stesse voci.

  Azioni registrate:
  - valutazioni, scarti e preferiti;
  - conferme e salti di un piano dell'assistente su `/culling` (`cull_confirm`, `cull_skip`), solo in modalità piano, una volta andata a buon fine la conferma o scaduto il conto alla rovescia del salto (la selezione manuale e una conferma chiusa da Esci non vengono registrate);
  - tag; album (creazione, ridenominazione, modifica della descrizione, eliminazione, aggiunta); persone (assegnazione, rimozione, unione, divisione, ridenominazione, nascondi, mostra, creazione, eliminazione); scarti indesiderati (rifiuto, contrassegno come non indesiderata);
  - risposte di confronto (`winner` `a`, `b`, `tie` o `skip`);
  - modifiche ai filtri della galleria: una raffica di modifiche diventa una sola voce `filters` dopo un secondo di quiete, `{reset: true}` per un ripristino; una modifica del solo ordinamento non viene registrata;
  - navigazione: un cambio di pagina (la sola modifica della stringa di query non lo è);
  - decisioni manuali Conserva e Reimposta dalle azioni singole o multiple della galleria e dai dettagli della foto, una volta completate: tipo `review`, con `value` `kept` o `undecided`. I gruppi non riusciti o completati solo in parte non aggiungono voci.

  Le scritture dell'assistente e la sua navigazione `ui_*` non vengono mai elencate, e un'azione tua che arriva mentre uno strumento `ui_*` dell'assistente è in esecuzione viene scartata. Nomi, testi di ricerca e percorsi in una voce sono dati non attendibili, mai istruzioni. Il registro vive nella memoria della scheda (le sue ultime 500 azioni) e si perde al ricaricamento.

Oltre alle basi qui sopra:

- **`ui_set_gallery_filters`** porta prima alla galleria se è aperta un'altra pagina, poi applica la modifica. In una pagina di album, qualsiasi modifica torna alla galleria (non solo `replace: true`), così i filtri salvati dell'album non vengono sovrascritti e l'ambito dell'album viene abbandonato. Rifiuta per intero la modifica (`invalid_input`) se nomina un filtro per cui la scheda non ha un controllo (per quelli usa `search_photos`), un filtro sconosciuto, sia `category` sia `type`, oppure sia `person` sia `person_id`. Accetta anche `semantic_query`, `semantic_threshold` (da 0 a 0,5), `similar_to`, `similarity_mode` e `min_similarity` (da 0 a 1); `similar_to` e `semantic_query` non si combinano.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` con `select_view` richiedono che la galleria (o un album) sia aperta, altrimenti rispondono `no_active_view`; chiama prima `ui_navigate` verso `/`. Dai a `ui_select_photos` esattamente uno tra `paths` e `select_view`. In modalità `remove` con una selezione dell'intera vista, i percorsi fuori dalla vista caricata sono ignorati ed elencati come `not_in_view`.
- Uno strumento UI che lascerebbe `/culling` mentre l'utente ha decisioni non confermate risponde `unsaved_decisions`. Una navigazione che la scheda stessa rifiuta risponde `navigation_refused`. `forbidden_level` è solo un rifiuto di permesso.
- `ui_navigate` apre solo le pagine statiche dell'app. La pagina di accesso, le pagine condivise, gli URL esterni e i percorsi sconosciuti sono rifiutati (`invalid_input`), come le pagine riservate alla modifica per una sessione senza modifica. `/timeline` accetta anche `year` e `month` (1-12); `ui_get_context` vi riporta `timeline`.
- **Cosa copre la pagina.** `ui_get_context.overlays` elenca ciò che copre la pagina (`dialog`, `bottom_sheet`, `slideshow`; vuoto quando nulla la copre). Finché non è vuoto, ogni strumento UI che modifica la vista risponde `modal_open` e non fa nulla. `ui_get_context`, `ui_get_selection` e `ui_get_gallery_view` rispondono comunque, e una ricerca mostrata con `show` riporta `shown_in_tab.reason` `modal_open` (la ricerca in sé riesce). Conta ogni finestra di dialogo, comprese quelle delle scorciatoie e dell'edizione, tranne quella di collegamento dell'assistente; menu, selettori, tooltip e snackbar non contano.
- **Stato della pagina.** `ui_get_context.page` è `{id, ...stato}` su queste pagine e `null` su ogni altra:
  - `/persons` (`persons`: `search`, `sort`, `sort_direction`, `show_hidden`)
  - `/albums` (`albums`: `search`, `sort`, `type`)
  - `/stats` (`stats`: `tab`, `category`, `date_from`, `date_to`)
  - `/map` (`map`: `date_from`, `date_to`)
  - `/timeline` (`timeline`: `date_from`, `date_to`, `sort`)
  - `/scenes` (`scenes`: `album_id`, `total`)
  - `/culling` (`culling`: `mode` (`cull` o `stacks`))
  - `/compare` (`compare`: `tab` (`snapshots`, `ab`, `suggestions`, `weights`, `context` o `panorama`), `category`, `strategy`, `pair_a`, `pair_b`, `pair_loading`). `tab` è `null` finché non si sceglie una categoria; la coppia è `null` finché la scheda A/B non è mostrata.

  I valori sono letti in tempo reale e il testo libero è tagliato a 200 caratteri. Una scheda più vecchia omette `page` e `overlays`.
- La riga di stato nella finestra **Collega un assistente** mostra se questa scheda è connessa; `status` elenca le schede aperte e i loro id.
- Una scheda smette di riconnettersi quando la sua sessione viene rifiutata (accedi di nuovo). Aspetta il tuo ritorno se un'altra tua scheda ha preso il suo posto.

## Aggiornamenti in tempo reale

Quando un assistente modifica delle foto con uno strumento di scrittura, le tue schede Facet aperte lo seguono senza ricaricare.

- **Galleria.** Le schede modificate si aggiornano sul posto, l'elenco fissato dell'assistente viene mantenuto e una foto eliminata dalla libreria (`delete_photos`) ne esce. Una foto che `cull_apply` ha spostato o messo nel cestino mantiene la sua riga nella libreria, quindi resta in un elenco fissato; le viste che nascondono le foto scartate (l'impostazione predefinita) la nascondono già. Una scrittura che non può nominare le sue foto (vedi sotto) ricarica la vista, tenendo a schermo le righe attuali e la tua selezione fino all'arrivo delle nuove. Le viste di ricerca semantica e di foto simili aggiornano le foto già mostrate e non ne tolgono mai.
- **Pagina della foto.** Rilegge la sua foto; una foto eliminata dalla libreria ti riporta indietro.
- **Camera oscura** (`/culling`). Aggiorna sul posto scarto, preferito e valutazione, mostra un indicatore Scartata e mantiene le tue decisioni. Davanti a una modifica che non sa delimitare ricarica solo se non c'è nulla in gioco; altrimenti mostra un banner Ricarica finché non ricarichi.
- **Un solo avviso per raffica.** Le modifiche sono raggruppate (antirimbalzo di 400 ms, al massimo 2 s) in un unico avviso «L'assistente ha modificato N foto».
- **Una voce per chiamata dell'assistente** nel pannello attività, etichettata con il nome dello strumento nella tua lingua (o il nome grezzo se non ha etichetta), con le foto dell'intera chiamata contate insieme. Oltre 200 foto la voce non ne nomina nessuna, quindi la vista si ricarica e non c'è il pulsante **Mostra le foto**. Dopo l'applicazione di `auto_cull`, **Mostra le foto** fissa le foto che ha scartato (fino a 200).
- **Quali scritture.** Valutazioni, preferiti, scarti, tag, didascalie, appartenenza agli album, selezioni, eliminazioni, correzioni di sequenza e di categoria, assegnazioni di volti, svuotamento degli scarti e conferme della camera oscura. Letture, prove, scritture rifiutate, creazione di album, esportazione dei metadati e scansioni non aggiornano. Una scrittura che va in timeout (`outcome_unknown`) aggiorna comunque, perché può essere andata a buon fine; una ancora in corso in quel momento compare al successivo aggiornamento o ricaricamento.
- **Scritture senza ambito.** Una scrittura su una vista `filters`, una che include i fotogrammi fratelli di un insieme, una su più di 200 foto, o una che non nomina alcun percorso ricarica la vista invece di aggiornare schede nominate.
- **Il ponte deve essere attivo.** Una scrittura fatta tramite `/mcp` raggiunge le tue schede attraverso il ponte della scheda, quindi `viewer.mcp.bridge` deve essere `true`. Una scrittura fatta dalla pagina stessa (`POST /api/mcp/call`) usa la sua risposta (`changed_paths`) e aggiorna anche con il ponte disattivato.
- **Solo lo stesso processo.** Con `viewer.py --workers N` l'avviso può mancare una scheda (vedi [Limitazioni note](#limitazioni-note)).
- **Dopo un aggiornamento, ricarica le schede aperte.** L'elenco degli strumenti è cambiato, quindi una scheda aperta risponde `tab_outdated` finché non viene ricaricata.

## WebMCP nella pagina (agenti del browser)

Oltre all'endpoint `/mcp`, una scheda con accesso effettuato offre gli stessi strumenti `ui_*` agli agenti che girano dentro il browser, tramite l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un assistente nativo del browser vede esattamente gli strumenti elencati sopra, li esegue nella scheda che stai guardando e non richiede alcun token.

- **Solo contesto sicuro.** Facet registra gli strumenti solo su HTTPS o `localhost`. Su HTTP semplice non vengono offerti; la connessione con token continua a funzionare.
- Vengono registrati quando `viewer.mcp.enabled` è true e hai effettuato l'accesso, e rimossi all'uscita.
- L'oggetto è `document.modelContext` (il vecchio alias `navigator.modelContext` non è fornito). È un polyfill, installato solo se il browser non ne ha uno nativo, e non può essere disinstallato: può esistere prima dell'accesso senza alcuno strumento Facet e resta dopo l'uscita con un elenco di strumenti vuoto.
- Gli strumenti fanno le stesse cose, limitate dallo stesso livello di account, della tabella qui sopra. Un agente del browser legge lo stesso elenco `actions` tramite `ui_get_context`.
- **Strumenti della libreria nella pagina.** La scheda offre anche gli strumenti propri del server (ricerca, valutazioni, tag, album, camera oscura, report):
  - `GET /api/mcp/inpage_tools` li elenca, con lo schema di ogni strumento, il suo `required_level` e il `level` attuale della sessione.
  - `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`) ne esegue uno come la tua sessione autenticata, attraverso lo stesso wrapper di `/mcp`, quindi livelli, anteprime, valori `confirm` e limiti di frequenza si comportano in modo identico. Uno strumento fallito dà una normale busta `ok: false` (HTTP 200). Una chiamata riporta anche `changed` (foto scritte).
- **Livello.** Il più basso tra il livello del tuo accesso e il tuo ruolo attuale, riletto a ogni chiamata: un account retrocesso perde subito le scritture e uno eliminato viene rifiutato (401). Sotto la soglia di uno strumento la risposta è `forbidden_level` («This session's level is readonly; set_rating needs edition: unlock edition in Facet»). In un'installazione con password unica, per scrivere serve la modifica sbloccata.
- **Chi può chiamare.** Solo una persona autenticata. Il token `/mcp` di un agente viene rifiutato su queste route (403), come un `Origin` estraneo; un cookie da solo non autentica mai. Ogni chiamata porta un'intestazione `X-Facet-Agent-Session` (da 1 a 64 lettere, cifre, `_` o `-`; 400 se manca o è malformata). Distingue le schede, quindi un valore `confirm` emesso per una scheda viene rifiutato in un'altra. La sceglie la pagina, quindi separa ma non autentica.
- **Cosa è escluso.** Gli strumenti immagine (`get_thumbnail`, `contact_sheet`) e `available_actions` (usa `ui_get_context`). L'argomento `show` di uno strumento è sempre disattivato, perché il chiamante è la scheda, e `tab_id` viene rifiutato. `status` riporta solo le versioni del server e del contratto UI. `target: "selection"` usa lo `selection_snapshot` inviato dalla pagina (ciò che `ui_get_selection` ha restituito). `create_album` con `target: "view"` richiede l'`album_filter_json` e il `filters_scopable` restituiti da `ui_get_gallery_view` (`invalid_input` senza di essi). Le azioni distruttive seguono ancora `viewer.mcp.allow_destructive`.
- **Gusto.** Come ogni scrittura di un assistente, una chiamata a uno strumento fatta dalla pagina non registra mai confronti e non arma mai il riaddestramento.
- **Interruttore.** `viewer.mcp.inpage_tools` (predefinito `true`) disattiva entrambe le route (404) e azzera `features.mcp_inpage` in `/api/auth/status`. Anche `viewer.mcp.enabled: false` le disattiva.

## Modificare la libreria

Gli strumenti di scrittura stanno nella stessa lista `/mcp` di quelli di lettura. Ciascuno passa dalle route `/api` del viewer, quindi le protezioni della route restano valide, e ciascuno viene conteggiato nel budget `write_rate_per_min`. Il livello è il più basso livello effettivo che può chiamare lo strumento (vedi [Livelli di autorizzazione](#livelli-di-autorizzazione)).

| Strumento | Livello | Cosa fa | Limiti |
|-----------|---------|---------|--------|
| `set_rating` | `user` | Imposta la valutazione a stelle (0-5) delle foto | 50 percorsi |
| `set_favorite` | `user` | Segna o toglie il preferito alle foto (segnare toglie lo scarto) | 50 percorsi |
| `set_rejected` | `user` | Scarta o annulla lo scarto delle foto (scartare rimuove valutazione e preferito) | 50 percorsi |
| `batch_set_rating` | `edition` | Imposta la valutazione di molte foto | 1000 percorsi, oppure `filters` |
| `batch_set_favorite` | `edition` | Segna molte foto come preferite | 1000 percorsi, oppure `filters` |
| `batch_set_rejected` | `edition` | Scarta molte foto | 1000 percorsi, oppure `filters` |
| `add_tags` | `edition` | Aggiunge tag manuali (separati dai tag IA) | 10 tag; 1000 percorsi, oppure `filters` |
| `remove_tags` | `edition` | Rimuove tag manuali | 10 tag; 1000 percorsi, oppure `filters` |
| `create_photo_stack` | `edition` | Crea una pila locale esplicita; restituisce voce Annulla | 2–1000 percorsi |
| `update_photo_stack` | `edition` | Sostituisce membri/ordine e copertina facoltativa; rifiuta revisione obsoleta | 1000 percorsi |
| `unstack_photos` | `edition` | Scioglie una pila; gli originali restano intatti |  |
| `undo_photo_stack` | `edition` | Annulla solo una voce pila disponibile; rifiuta modifiche successive |  |
| `create_album` | `edition` | Crea un album (non idempotente: due volte crea due album): vuoto, oppure da `filters` / `target: "view"` come album intelligente che segue quei filtri, oppure da `paths` / `target: "selection"` come album fisso riempito nella stessa chiamata (`added`, `skipped`). Un album intelligente usa gli interruttori di nascondimento del visualizzatore e in `list_albums` mostra 0 foto. Dei `filters` senza alcun filtro effettivo (`{}`, o solo interruttori di visualizzazione disattivati) vengono rifiutati come `invalid_input`: ometti `filters` per un album vuoto | |
| `album_add_photos` | `edition` | Aggiunge foto a un album (quelle già presenti sono ignorate) | 1000 percorsi |
| `album_remove_photos` | `edition` | Toglie foto da un album; le foto non sono toccate | 1000 percorsi |
| `assign_faces` | `edition` | Sposta volti su una persona; quelli di un'altra persona restano com'erano salvo `allow_reassign`, e il risultato elenca ciò che è stato saltato | 50 id di volto |
| `set_caption` | `edition` | Imposta la didascalia di una foto (semantica di insieme; una didascalia invariata torna come `already`) | 1 foto, 2000 caratteri |
| `export_metadata` | `edition` | Scrive sidecar XMP accanto ai file | 100 percorsi, oppure `filters`, oppure `target` |
| `junk_list` | `readonly` | Elenca i candidati della pulizia degli scarti, eventualmente di un solo `kind`; `show: true` apre `/junk` su quel `kind` | 100 per pagina |
| `junk_reject` | `edition` | Scarta i candidati della pulizia (come `batch_set_rejected`) | 1000 percorsi, oppure `target: "selection"` (solo pagina galleria) |
| `junk_clear` | `edition` | Conserva i candidati: li segna come valutati e a posto perché escano dalla coda | 50 percorsi |
| `cull_apply` | `edition` | Copia le foto da tenere, oppure sposta o cestina quelle scartate ([anteprima, poi conferma](#azioni-distruttive-anteprima-poi-conferma)) | 10000 percorsi, oppure `filters` |
| `delete_photos` | `edition` | Cestina i file ed elimina le loro righe dalla libreria ([anteprima, poi conferma](#azioni-distruttive-anteprima-poi-conferma)) | 1000 percorsi |

### Pile manuali locali

- `get_photo_stack(path)` legge la pila locale di chi chiama, o null. Con visibilità parziale restituisce solo i membri consentiti e la pila è in sola lettura.
- `create_photo_stack(paths, cover_path)` richiede 2–1000 foto esplicite non impilate.
- `update_photo_stack(stack_id, paths, expected_revision, cover_path?)` sostituisce membri e ordine; 0 o 1 membro scioglie il gruppo.
- `unstack_photos(stack_id, expected_revision)` lo scioglie.
- Questi tre richiedono `edition`, più l'UUID e la revisione corrente per le pile esistenti. Non ripetere mai una creazione alla cieca.
- Le modifiche riuscite restituiscono `undo.entry_id`. `undo_photo_stack(entry_id)` (solo edition) verifica che la voce sia una voce pila e rifiuta dopo modifiche successive o perdita di visibilità.
- I percorsi sono lunghi al massimo 4096 caratteri. Nessun file, decisione di revisione o stato Immich remoto cambia; le credenziali globali restano solo da CLI.
- `stack_truncated: true` dopo una modifica grande riuscita significa che la pila è restituita solo come riepilogo UUID/revision/member_count, non come elenco completo di membri modificabili. `undo.entry_id` resta disponibile.

`search_photos` e il contesto della galleria distinguono `total` (elementi visualizzati) da `photo_total` (originali corrispondenti). Usa `photo_total` per `expected_count` nelle scritture filtrate. La selezione dell'intera vista e `target:view` includono i membri ripiegati corrispondenti: mostra il conteggio reale delle foto e l'ambito dell'intera vista prima di applicare. Selezionare una tessera chiusa seleziona solo la foto visualizzata. `user_activity` include `stack` create/update/unstack/undo. `stack_id`/`collapse_stacks` sono solo lato server, non chiavi di filtro della scheda.

- **Gli strumenti `user` richiedono un token edition su un'installazione con password unica**, che non ha un livello intermedio (vedi [Livelli di autorizzazione](#livelli-di-autorizzazione)).
- **Semantica di impostazione.** Gli strumenti per singola foto scrivono solo una differenza rispetto allo stato attuale, quindi ripetere una chiamata è innocuo; ogni percorso riporta `changed` o `already`. Procedono un percorso alla volta e si fermano al primo `library_busy`, `outcome_unknown` o `forbidden_level`, riportando `affected`, i `results` per percorso e `not_attempted`. Gli strumenti batch impostano lo stesso stato.
- **Scegliere le foto.** Gli strumenti batch, dei tag e `cull_apply` accettano O `paths` O `filters` (l'oggetto filtri di `search_photos`), più un elenco `exclude` facoltativo.
  - Un bersaglio `filters` deve avere `expected_count`: il numero di corrispondenze dei filtri prima di `exclude` (il `photo_total` di `search_photos`). Facet ricalcola prima e non scrive nulla se i numeri differiscono (`invalid_input`, con `actual_count`).
  - Le esclusioni predefinite del visualizzatore (comprese le foto scartate) si applicano a `filters` esattamente come in `search_photos`. Quindi per `move_rejects` e `trash_rejects` passa `show_rejected` (o `hide_rejected: false`) sia a `search_photos` sia a `cull_apply`. `copy_keeps` non richiede altro.
- **Di chi è lo stato.** Valutazioni, preferiti e scarti sono quelli del proprietario del token.
- **File saltati.** Una lista `skipped` non vuota di `cull_apply` o `delete_photos` porta un `skipped_reason`: questi percorsi non hanno alcun file leggibile su disco (mancante, spostato o fuori dalle cartelle analizzate) e per loro non è stato fatto nulla.
- **Le foto selezionate dall'utente.** Dove uno strumento accetta `paths`, `target: "selection"` usa invece la selezione della scheda aperta (`tab_id` sceglie la scheda).
  - Una selezione cambiata fra anteprima e conferma risponde `invalid_input` con `selection_changed`; una troppo grande per la risposta della scheda risponde `too_large`. `delete_photos` rilegge la selezione alla conferma.
  - `get_photo`, `get_thumbnail` (esattamente una foto selezionata) e `contact_sheet` (al massimo 16) accettano anche `target: "selection"`, da qualsiasi pagina.
  - `junk_reject` lo accetta solo sulla pagina galleria (altrimenti `invalid_input`).
- **Didascalie ed esportazioni.** `set_caption` memorizza solo il testo. Non viene ricodificata, quindi la ricerca semantica delle didascalie trova il vecchio testo fino a una nuova codifica. L'esportazione incrementale nel database del visualizzatore mantiene una didascalia esistente quando quella di origine è vuota, quindi una didascalia cancellata può tornare con un'esportazione o una scansione successiva. `export_metadata` attende fino a 180 secondi, riporta `written`, `skipped` ed `errors` (il primo messaggio d'errore in `first_error`) e rifiuta di scrivere con exiftool da 13.23 a 13.27.
- **Volti.** `assign_faces` salta, ed elenca, i volti mancanti, già su quella persona, di un'altra persona (salvo `allow_reassign`), di un altro modello di embedding o di una persona nascosta. `assigned_count` è ciò che si è davvero spostato.

### Azioni distruttive: anteprima, poi conferma

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) e `delete_photos` sono contrassegnati `destructiveHint` e girano come simulazione se non chiamati con `dry_run: false`.

1. La simulazione non modifica nulla ed elenca i file che copierebbe, sposterebbe o cestinerebbe (le liste lunghe sono troncate a `max_rows`, con un `<key>_count`). Per `move_rejects`, `trash_rejects` e `delete_photos` restituisce anche un valore `confirm`, monouso e valido per `confirm_expires_in_s` (5 minuti).
2. La chiamata reale (`dry_run: false`) deve passare quel `confirm`. Facet ricalcola i file e le opzioni; se qualcosa è cambiato, la chiamata risponde `confirmation_required`: rifai la simulazione.
3. `copy_keeps` non richiede `confirm`, perché scrive solo copie. Per impostazione predefinita parte comunque con un'anteprima.

Il valore `confirm` è legato al token, all'azione e all'esatto insieme di file più le opzioni. Vive in memoria in un solo processo, quindi un riavvio scarta tutti i valori in sospeso.

**Pratica consigliata:** mostra sempre all'utente il riepilogo della simulazione (conteggi ed elenco dei file) e ottieni la sua approvazione esplicita prima della chiamata `dry_run: false`. Non confermare mai di propria iniziativa.

- `move_rejects` e `trash_rejects` agiscono solo sulle foto che il proprietario ha scartato; le altre sono riportate come `excluded_by_state`. I file RAW e `.xmp` associati (`include_companions`) e gli altri fotogrammi di un bracketing o di un panorama (`include_sequence_siblings`) non sono toccati se non lo attivi.
- **Prerequisiti.** `trash_rejects` e `delete_photos` richiedono `viewer.cull.allow_trash` impostato a `true` (predefinito `false`). Il `target_dir` di `copy_keeps` e `move_rejects` deve trovarsi in una posizione di esportazione consentita: `viewer.export.allowed_target_dirs` più le tue directory di scansione (vedi [Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto)).

> **Avvertenza:** `delete_photos` invia i file al cestino di sistema ed **elimina le loro righe dalla libreria**. Punteggi, tag e valutazioni non sono recuperabili, anche se i file lo sono.

## Correzioni e dati di riferimento

- **Correzioni** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` o `suppress`; almeno 2 percorsi tranne per `suppress`) e `clear_sequence_override` registrano una correzione applicata al prossimo passaggio di rilevamento (il risultato riporta `pending`). `override_category` e `clear_category_override` impostano o rimuovono una categoria persistente che sopravvive alle nuove scansioni e mantiene il contesto di punteggio.
- **Confrontare i fotogrammi** (`readonly`). `group_compare` confronta i fotogrammi di un gruppo di selezione (fino a 12 percorsi) con `by: "faces"` (per fotogramma: numero di volti, ammiccamenti, occhi aperti peggiori, miglior sorriso, `best_path_by_eyes`) o `by: "subjects"` (nitidezza e rilievo del soggetto, `sharpest_path`). È un consiglio, non una decisione.
- **Rapporto di selezione.** `cull_report` riassume un ambito in una chiamata: totale, tenute, scartate, preferite, valutate, da rivedere, ciò che gli interruttori di nascondimento nasconderebbero, scarti, punteggi bassi, le migliori e, con un token edition, i primi gruppi della camera oscura. I motivi si sovrappongono. Il suo `basis` indica quali filtri rispetta ogni conteggio (i conteggi ignorano gli interruttori di nascondimento).
- **Gusto.** `comparison_status` (`edition`) riporta quanti confronti a coppie hai fatto e quanto coprono la libreria. Nessuno strumento invia, modifica o elimina un confronto: ogni risposta è un tuo clic. Le scritture di un assistente (valutazioni, scarti, conferme della camera oscura, `auto_cull`) non registrano mai confronti e non armano mai il riaddestramento automatico; la stessa azione fatta da te nella galleria lo fa ancora. Le valutazioni, i preferiti e gli scarti scritti da un assistente restano fuori anche dalle coppie di addestramento del classificatore personale, finché non valuti tu stesso quella foto.
- **Scansioni.** `start_scan` e `scan_status` (`edition`) avviano e seguono una scansione delle directory configurate. Sono elencati solo se `viewer.features.show_scan_button` è attivo e l'installazione è bloccata (una chiave superadmin in modalità multiutente), oppure per un token locale di modifica completa sotto `viewer.trusted_local_editing`, che non richiede `show_scan_button`. Le scansioni sono additive e rifiutate finché un altro lavoro è in corso (`conflict`). La sincronizzazione con Immich resta da riga di comando. Su un'installazione aperta con `viewer.edition_password` li ottiene anche un token locale di modifica completa creato in una sessione di modifica, ma solo con `show_scan_button` attivo.
- **Risorse.** Il server elenca anche cinque risorse `facet://` in sola lettura: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (ogni filtro di ricerca con il suo dominio di valori, più gli intervalli delle metriche) e `facet://scoring-contexts`. Ognuna mostra la libreria come la vede il proprietario della chiave, limitata a 200 righe e 32 KiB (`truncated` lo indica). Una sesta, `facet://scoring-weights` (i pesi diversi da zero di ogni categoria), è offerta solo alle chiavi `edition`.
- **Scegliere cosa viene elencato.** `viewer.mcp.tool_profile` è `full` (predefinito) o `core`. `core` elenca solo un insieme di 11 strumenti per i modelli piccoli (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`); cambia solo l'elenco, mai ciò che una chiave può chiamare. `viewer.mcp.allow_destructive` (predefinito `false`) controlla `delete_photos` (non elencato se disattivato), le azioni `move_rejects` e `trash_rejects` di `cull_apply` e `assign_faces` con `allow_reassign`; le chiamate rifiutate rispondono `feature_disabled`. Anche gli strumenti oltre il livello di un token non sono elencati.
- **Altri due codici di errore.** `feature_disabled`: una chiave di configurazione disattiva la route, e il messaggio la nomina. `conflict`: la libreria è occupata da un lavoro incompatibile con questo (per esempio una scansione già in corso).

## Punteggi e pesi

Gli assistenti possono leggere i pesi di punteggio e provare a vuoto una modifica. Quattro strumenti scrivono: `apply_weights` e `restore_weight_snapshot` modificano la configurazione, `recompute_scores` riscrive i punteggi e `override_categories` fissa le foto. Ognuno richiede il livello `edition` e un `confirm` in due passaggi da una prova a vuoto o un'anteprima. Le letture non cambiano nulla.

- **Spiegare un punteggio** (`readonly`). `explain_score` (`path`, oppure `target: "selection"` per esattamente una foto selezionata; `top_n` da 1 a 12, predefinito 5) spiega il punteggio di una foto: la sua categoria e perché nessuna categoria a priorità più alta l'ha presa, l'aggregato memorizzato, le metriche principali come `{metric_key, value, weight_percent, contribution}`, il resto come conteggio e somma, punti di forza, punti deboli e penalità.
  - È basata su regole e in sola lettura; non esegue mai il VLM.
  - `weight_percent` è il peso effettivo usato dal calcolo. Può differire dal `*_percent` configurato: `quality` viene incorporato in `aesthetic` e le metriche che questa installazione non esegue vengono rinormalizzate.
  - Richiede `viewer.features.show_critique` (attivo per impostazione predefinita). Se è disattivato, lo strumento non è elencato e `status` lo nomina sotto `hidden_tools.disabled`.
- **Leggere i pesi** (`edition`). `category_weights` restituisce i pesi diversi da zero, i modificatori, i filtri e la priorità di una categoria, oppure i pesi diversi da zero e il bonus di ogni categoria. La risorsa `facet://scoring-weights` contiene lo stesso elenco. Per una categoria restituisce anche `configured_keys`: le chiavi `*_percent` effettivamente presenti nella configurazione della categoria (zeri espliciti inclusi).
- **Simulare una modifica** (`edition`). `preview_weights(category, weights | deltas, sample)` ricalcola fino a `sample` foto della categoria (30 per impostazione predefinita, al massimo 100) con i pesi attuali e con quelli proposti, entrambi normalizzati come fa il calcolo. Indica `weights` (una mappa parziale sovrapposta ai valori attuali) oppure `deltas` (punti percentuali con segno).
  - Riporta prima i cambi di posizione, poi lo scostamento medio, `warnings` e un `preview_digest` monouso (valido 5 minuti, tenuto in memoria da un solo processo).
  - È approssimativa (`basis: "approximate"`): nessuna istantanea dei percentili, nessuna penalità, punteggi limitati a 10. Usa solo le metriche memorizzate e non memorizza nulla.
  - Si applica solo la regola del server (ogni peso da 0 a 100), più un rifiuto quando tutti i pesi sommano a 0 (`all_weights_zero`). Una somma fuori da 95-105 (che il caricatore della configurazione riscala) e una chiave sconosciuta (memorizzata così com'è, scartata da un caricamento con validazione) tornano come `warnings`, non come rifiuti.
  - `bonus` e i modificatori non sono modificabili tramite l'assistente.
  - Una categoria con più di 100 foto viene campionata solo tra le sue 100 migliori e 100 peggiori per aggregato (`sample_scope`).
  - Il digest non è un consenso: mostra prima all'utente la proposta, lo scostamento e `basis_note`.
- **Applicare una modifica** (`edition`). `apply_weights(category, weights | deltas, preview_digest)` scrive una modifica simulata. Ripeti gli STESSI `weights` o `deltas` dati a `preview_weights` e passa il suo `preview_digest`. Senza il digest di questa proposta esatta sui pesi attuali, la chiamata risponde `confirmation_required` e non scrive nulla. Il digest è monouso, legato al token che ha simulato, e nullo se i pesi cambiano.
  - La scrittura passa per la stessa route dell'interfaccia web: i pesi precedenti vengono prima salvati in uno snapshot (`auto:edit`) e il risultato indica quello `snapshot`. Il risultato viene riletto (`verified`).
  - Nessuna foto viene ricalcolata: la risposta riporta `scores_stale: true` e `next: "recompute_scores"`. Punteggi memorizzati, posizioni e galleria cambiano solo dopo quel lavoro.
  - Limite noto: una pagina /compare già aperta conserva i vecchi pesi e li rimanderebbe alla modifica successiva; la risposta porta perciò `reload_compare: true` e l'assistente chiede all'utente di ricaricarla.
- **Snapshot** (`edition`). `list_weight_snapshots(category, limit, offset)` elenca gli snapshot salvati, dal più recente, con i pesi diversi da zero e un indicatore `restorable`. `restore_weight_snapshot(snapshot_id)` è per impostazione predefinita una prova: elenca la modifica e restituisce un `confirm` monouso. L'esecuzione reale (`dry_run: false` più quel `confirm`) risponde `confirmation_required` se nel frattempo i pesi sono cambiati. Prima di sovrascrivere salva i pesi attuali come `auto:pre_restore` (`undo_snapshot_id`), così un ripristino può a sua volta essere annullato. Uno snapshot salvato dall'interfaccia web in un altro formato (nomi di metriche nudi invece di chiavi `*_percent`) risponde `unsupported_snapshot` in entrambe le esecuzioni: ripristinalo da /compare.
- **Ricalcolare** (`edition`). Una modifica dei pesi non ricalcola nulla finché non viene eseguito `recompute_scores(category | all: true)`. Avvia subito il lavoro in background (chiedi prima all'utente) e restituisce `started_at`. `recompute_status(started_at)` riporta poi `running`, `succeeded`, `failed`, `busy` (un altro processo detiene il blocco della libreria) o `idle`; `matches_started_job` dice se lo stato descrive il lavoro avviato.
  - Un solo lavoro alla volta (`conflict`).
  - Il ricalcolo di una categoria riscrive solo quella categoria e non aggiorna i gruppi di raffiche o sequenze (`all` lo fa). Entrambe le esecuzioni salvano lo snapshot dei percentili letto dalla successiva normalizzazione di ogni categoria.
  - Lo stato è tenuto in un solo processo: con più worker una richiesta può finire su uno che non conosce il lavoro.
- **Cosa favoriscono i confronti dell'utente** (`edition`). `learned_weights(category, with_confidence)` esegue l'ottimizzatore sui confronti A/B dell'utente e restituisce solo i `changes` diversi da zero e una `proposal` da passare a `preview_weights`; nulla viene salvato. Invece di inventare un suggerimento risponde `available: false` con un `reason` (`not_enough_comparisons`, `unavailable_if_external` quando il backend di apprendimento è esterno, `optimizer_unavailable`). Quando l'ottimizzatore non trova miglioramenti, dice all'assistente di non proporre una modifica.
- **Correggere le categorie** (`edition`). `misassigned_categories(category, limit, scan)` elenca le foto di una categoria che forse appartengono altrove, tra le `scan` con il punteggio più alto. È un'euristica (`confidence_basis: "heuristic"`), non una prova; non scrive nulla, salta le foto con categoria manuale e scompare con `show_critique`.
  - `stale`: la configurazione attuale colloca la foto in un'altra categoria. Si rimedia con `recompute_scores`, non con una forzatura.
  - `near_miss`: ha mancato di meno del 10 % il primo limite numerico fallito di una categoria con priorità maggiore.
- **Fissare le categorie** (`edition`). `override_categories(category, paths, dry_run, confirm, expected_count)` fissa fino a 50 foto.
  - La prova elenca chi cambierebbe (`would_change`, `already`, `missing`) e restituisce un `confirm` monouso.
  - L'esecuzione reale lo richiede, con un `expected_count` pari a `would_pin`. Anche le foto già nella categoria vengono fissate, così la scelta sopravvive a un ricalcolo successivo. Si ferma al primo errore e riporta `affected`, `remaining` e `failed_path`.
  - Ogni fissaggio è duraturo e ricalcola l'aggregato della foto; `clear_category_override` ne annulla uno.
- `ui_show_comparison` accetta un `tab` (`ab`, `snapshots`, `suggestions`, `weights`) così l'assistente può aprire la pagina in cui l'utente rivede una modifica.

## Prompts

Il server offre anche cinque prompt pronti, elencati da `prompts/list` e filtrati in base al livello del token. Un prompt nomina solo strumenti che il token può chiamare, e uno strumento distruttivo solo dopo la prova a vuoto e la conferma. Ogni chiamata conta nel limite di lettura ed è registrata per nome, mai con i suoi argomenti.

| Prompt | Argomenti | Cosa chiede all'assistente |
|--------|-----------|----------------------------|
| `find_photo` | `description` | Trovare una foto da una descrizione e mostrarla |
| `cull_shoot` | `scope_hint` | Rivedere uno shooting, proporre cosa scartare e, dopo la tua decisione, registrarla con `confirm_culling_groups`; spostare o cestinare avviene solo dopo una prova a vuoto e la tua conferma |
| `build_album` | `theme`, `album_name` | Raccogliere le foto corrispondenti in un nuovo album |
| `tag_people` | `person` | Trovare i volti simili a una persona e assegnare quelli che confermi |
| `teach_taste` | `category` | Aprire la pagina di confronto a coppie nella tua scheda e tenere il conto dei confronti fatti; la risposta a ogni coppia è sempre il tuo clic |

## Camera oscura (gruppi di selezione)

Gli strumenti della camera oscura rispecchiano la pagina `/culling`. Tutti richiedono il livello `edition`, anche quelli che si limitano a elencare.

| Strumento | Cosa fa |
|-----------|---------|
| `list_culling_groups` | Elenca i gruppi (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) con foto e punteggi, ordinabili e limitabili per album o intervallo di date |
| `culling_profiles` | I preset di selezione per genere e quello predefinito |
| `suggest_culling_profile` | Indica il preset adatto a un album o a un intervallo di scatto |
| `keeper_hints` | Indicazioni per foto «in questa raffica esiste uno scatto migliore» per fino a 100 percorsi (vuote se nessuna testa di classificazione è addestrata) |
| `auto_cull` | Selezione automatica di un ambito con un budget di foto da mantenere: anteprima del piano pagina per pagina, poi applicazione con il valore `confirm` |
| `confirm_culling_groups` | Conferma fino a 20 gruppi: tiene i loro `keep_paths`, scarta il resto dei `paths` |

- **Un gruppo è identificato dalla coppia `(type, group_id)`**, mai dal solo `group_id`: gli id dei gruppi simili sono traslati quando vengono uniti alle raffiche.
- **Il valore predefinito `group_by: "all"` restituisce solo raffiche e gruppi simili.** Richiedi esplicitamente `scene`, `bracket`, `panorama` o `hdr_panorama`.
- **Una pagina viene ridotta per stare in `max_bytes` accorciando l'elenco `photos` di ogni gruppo, mai eliminando gruppi.** `photo_count` resta la dimensione reale, `photos_truncated` segnala un elenco tagliato e `has_more` indica se segue un'altra pagina.
- **Bracketing, panorami e panorami HDR si tengono interi.** In `confirm_culling_groups`, `keep_paths` deve coincidere con `paths` per questi tipi (altrimenti `invalid_input`), e `auto_cull` non li divide mai.
- **Un `keep_paths` vuoto scarta ogni fotogramma del gruppo.** La prima chiamata risponde allora `confirmation_required` con un valore `confirm`: mostralo all'utente, poi ripeti la chiamata con quel valore. Se un lotto si ferma su `forbidden_level`, `library_busy` o `rate_limited`, vengono riportati i gruppi già completati.
- **`auto_cull` mostra un'anteprima per impostazione predefinita.** Restituisce la ripartizione mantieni/rifiuta per gruppo, più un valore `confirm` quando resta qualcosa da rifiutare.
  - Ogni chiamata pianifica l'intero ambito e lo restituisce in pagine di gruppi interi. La route impagina a 200 foto, un singolo gruppo più grande ottiene una pagina propria e lo strumento può restituire meno gruppi per rientrare nella dimensione del risultato.
  - Ripeti la chiamata con `cursor` pari al `next_cursor` precedente e `plan_digest` pari al `plan_digest` della pagina con cursore 0 (obbligatorio se `cursor` > 0), finché `next_cursor` non è `null`. Se il piano è cambiato dopo la prima pagina, la chiamata risponde `confirmation_required`: riparti dal cursore 0.
  - Ogni riga porta il suo `number` valido per tutto il piano; `kept` e `rejected` coprono il piano completo.
  - Seleziona un intero intervallo di date in UNA chiamata, mai mese per mese.
- **Un solo `confirm` copre l'intero piano** (valido 300 s, monouso, emesso solo nella pagina con cursore 0). L'applicazione ricalcola il piano e risponde `confirmation_required` se è cambiato dopo l'anteprima. Restituisce solo conteggi (`groups_processed`, `kept`, `rejected`, `highlights_added`). I rifiuti fatti da un assistente non alimentano mai il classificatore personale, a differenza della stessa selezione fatta da te nella galleria.
- **Sostituzioni.** `keep_paths` e `remove_paths` (fino a 1000 ciascuno) sostituiscono singoli fotogrammi del piano. Passa le stesse sostituzioni alla prova che emette il `confirm` e all'applicazione.
  - I percorsi che non sono nel piano sono ignorati e riportati come `ignored_overrides` (i primi 20, con `ignored_overrides_count`).
  - Rifiutati come `invalid_input`, che nomina i percorsi o i gruppi: rimuovere un fotogramma che il piano TIENE in una serie di bracketing, un panorama o un panorama HDR; lasciare un gruppo senza foto tenuta; citare un percorso in entrambi gli elenchi.
  - Rimuovere un fotogramma che il piano già scarta non fa nulla.
  - La regola delle serie vale per i gruppi formati interamente da un solo tipo di serie. Un gruppo che mescola fotogrammi ordinari e di serie non è tenuto per intero, quindi i suoi fotogrammi si possono sostituire come quelli di qualsiasi raffica.
- **L'applicazione non legge mai le inversioni dell'utente dalla scheda.** Per rispettarle, leggi `ui_get_context.culling.changed` e passa i `keep_paths` / `reject_paths` di quei gruppi come `keep_paths` / `remove_paths` alla prova successiva e alla sua applicazione (gli stessi elenchi su entrambe). Un gruppo confermato dall'utente nella scheda esce dal piano: il digest del piano cambia, un `confirm` in sospeso risponde `confirmation_required` e la nuova anteprima non contiene più quel gruppo. Non ridecidere mai.
- **Se l'utente cambia qualcosa tra anteprima e applicazione.** L'applicazione è confrontata con l'anteprima.
  - Una foto di cui l'utente ha cambiato valutazione, preferito o stato di scarto dopo l'anteprima è esclusa e riportata come `skipped_user_changed` (i primi 50 percorsi, con `skipped_user_changed_count`). Un gruppo rimasto senza foto tenuta è saltato per intero e contato in `skipped_user_changed_groups`.
  - Questa esclusione per singola foto vale solo se non sono dati né `keep_paths` né `remove_paths`. Con elenchi espliciti, l'applicazione riesegue la prova e rifiuta qualsiasi modifica del piano, anche uno scarto manuale.
  - Una valutazione, un preferito o uno scarto scritto da chiunque tra anteprima e applicazione conta come modifica, comprese le scritture dell'assistente. Una modifica del piano non spiegata da tali foto è comunque rifiutata come `confirmation_required`.
  - Quando il server non conserva più l'anteprima (più vecchia di 15 minuti, rimossa o tenuta da un altro processo), o il piano ha più di 12000 foto su tutte le pagine, la risposta dice `state_guard: "unavailable"` e vale il rifiuto tutto o niente.
  - La protezione copre solo le richieste dell'assistente; la riga di comando `--auto-cull` è invariata.
- **`scope_dependent_kinds`** indica i tipi di gruppo la cui composizione dipende dall'intervallo di date o dal pool di candidati (`similar`, `scene`, più `bracket` se `trim_brackets` è attivo), con una nota che invita a selezionare l'intero intervallo in una chiamata. Raffiche e panorami non cambiano con l'intervallo, né i bracketing finché `trim_brackets` è disattivato.
- **`show`** (`true` per impostazione predefinita, con `tab_id`). In una prova il piano si apre sulla pagina `/culling` dell'utente tramite `ui_show_culling_plan` (vedi Modalità piano su `/culling` sopra).
  - Il risultato porta `shown_in_tab`: `{"applied": true, ...}`, oppure `applied: false` con i motivi di una visualizzazione di ricerca fallita più `unsaved_decisions` (l'utente ha nella pagina decisioni non confermate), `stack_mode_active` (la pagina è in modalità pile suggerite), `plan_changed` (la libreria è cambiata dopo l'anteprima), `too_large` (le sostituzioni sono troppo grandi per essere inviate alla scheda) e `plan_load_failed` (qualsiasi altro errore di caricamento).
  - Solo la prima pagina (`cursor` 0) carica il piano; una pagina con `cursor` > 0 sposta solo il focus della scheda sul suo primo gruppo.
  - Una visualizzazione fallita non fa mai fallire la chiamata. Un'applicazione non mostra mai.
  - L'aggiornamento in tempo reale di un'applicazione (e, nella pagina, il `show_paths` della risposta `/api/mcp/call`) porta le foto che ha scartato, fino a 200, per il **Mostra le foto** della voce di attività; il risultato dello strumento resta limitato ai conteggi. Un'applicazione che non ha scartato nulla non offre **Mostra le foto**, e una prova non emette alcun aggiornamento in tempo reale.
- **Impostazioni dalla scheda.** Senza `strictness` né `profile`, `auto_cull` pianifica con le impostazioni da cui partirebbe la pagina `/culling` della scheda aperta.
  - Rigore: il valore memorizzato del cursore; se non è mai stato spostato, il rigore proprio del profilo memorizzato, oppure 100 senza profilo.
  - Profilo: il profilo di selezione memorizzato in questo browser, se c'è. Fornisce le sue altre impostazioni (come il numero minimo di foto da tenere per gruppo); il rigore del cursore prevale.
  - Mostrare un piano sposta il cursore sul rigore del piano; applicare un profilo suggerito ne memorizza il rigore.
  - Senza una scheda raggiungibile usa `auto_cull.default_strictness` del server.
  - Il risultato riporta ciò che ha usato come `knobs_from_tab` (`{profile}`, `{strictness}` o entrambi); `ui_get_context.culling_defaults` mostra la stessa coppia.
  - Un'applicazione con un nonce di conferma riusa le impostazioni dell'anteprima (`keep_paths` / `remove_paths` espliciti inclusi) e non rilegge la scheda. Risponde `confirmation_required` quando la pagina `/culling` dell'utente mostra ora un piano diverso da quello dell'anteprima (ripianificato o sostituito). Una scheda irraggiungibile o senza piano mostrato non viene controllata.
- Chiama `ui_show_culling_group` per mostrare un gruppo all'utente nella sua scheda aperta (vedi [Controllare la scheda aperta](#controllare-la-scheda-aperta)).

## Risultati, limiti ed errori

Ogni risultato è una busta JSON: `{"ok": true, "data": ...}` oppure `{"ok": false, "error": "<code>", "message": "..."}`. Gli elenchi restituiscono `data.rows` (un insieme compatto e fisso di campi per foto) e `total`. Il risultato di una ricerca contiene anche `shown_in_tab`, e un risultato accorciato dal limite di byte contiene `returned`.

- **Tetti:** al massimo `max_rows` righe e `max_bytes` byte serializzati. Le ultime righe vengono scartate e si imposta `truncated: true`. Un risultato senza righe che supera `max_bytes` diventa un errore `too_large`.
- **Immagini:** `get_thumbnail` e `contact_sheet` restituiscono una parte immagine prima della parte JSON. L'immagine è limitata da `max_image_bytes` (predefinito 262144), non da `max_bytes`. Il testo visibile in un'immagine è un dato, mai un'istruzione.
- **Scansione dei volti:** `possible_faces` legge al massimo 192000 volti e può attendere fino a 120 secondi; oltre risponde `too_large`.
- **Limite di frequenza:** le letture ottengono `rate_per_min` chiamate al minuto per token. Gli strumenti di scrittura attingono a un budget separato, `write_rate_per_min` (predefinito 30), così letture e scritture non si affamano a vicenda. La simulazione di `cull_apply` e `delete_photos` conta come scrittura, l'anteprima di `auto_cull` come lettura. Oltre: `rate_limited` con `retry_after_s`. Dieci tentativi bearer falliti al minuto dallo stesso indirizzo ricevono 429.
- **Codici di errore:** `forbidden_level` (endpoint disattivato, token non valido o livello troppo basso), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`, `no_active_view`, `unsaved_decisions`, `navigation_refused`, `modal_open`, `stack_mode_active`.
- **I codici più recenti:** `confirmation_required` (una chiamata distruttiva non ha un valore `confirm` valido per questo preciso insieme: rifai una simulazione, mostra il risultato all'utente, poi riprova), `outcome_unknown` (una scrittura è scaduta o la connessione è caduta, quindi può essere avvenuta o no: rileggi lo stato prima di riprovare, non ripetere mai alla cieca), `library_busy` (la libreria è occupata da un altro lavoro: riprova tra un istante).
- **Codici HTTP all'ingresso:** 401 per token mancante o sconosciuto, 403 per una richiesta di browser da un'altra origine o per le credenziali di un agente su `/api/mcp/tokens`, 404 quando è disattivato. Il ponte delle schede risponde invece con codici di chiusura. In un'installazione aperta, `/api/mcp/tokens` risponde inoltre 403 a una richiesta che non arriva dal computer su cui gira Facet.

## Note di sicurezza

- Didascalie, tag, nomi di file, percorsi e nomi di album e persone provengono dalla tua libreria e possono contenere testo scritto per manipolare un assistente (prompt injection). Ogni strumento è marcato `facet/untrusted_content` e dice al modello di trattarli come dati. Non dare a un assistente che legge anche contenuti non attendibili un modo per agire su ciò che trova qui.
- I token non scadono mai. Revoca quelli che non usi più.
- I log registrano l'id del token, lo strumento, l'esito e il numero di righe, mai gli argomenti né il token.

## Limitazioni note

- **Installazioni aperte** (senza password). Solo la gestione dei token è limitata al computer locale, così un peer della rete non può riempire il limite di 20 token. `/mcp`, gli strumenti nella pagina e il ponte della scheda restano raggiungibili da chiunque raggiunga il viewer, come l'utente anonimo condiviso. Imposta una password prima di attivare l'endpoint su una rete.
- **Schede false su un'installazione aperta.** Un client non browser può inviare un `Origin` inventato e un token nullo, registrare una scheda `_anonymous` con il focus, rispondere alle chiamate `ui_*` con dati a sua scelta ed espellere schede reali tramite il limite di 8 schede. Con `viewer.trusted_local_editing`, un processo locale può anche registrare una falsa scheda `edition` (può falsificare `Host` e `Origin` sul WebSocket), ma poteva già agire come il browser. Un client della rete locale no, perché è richiesto un peer in loopback.
- I limiti di frequenza e i contatori di autenticazioni fallite stanno in memoria in ciascun processo; con `viewer.py --workers N` ogni worker conta separatamente.
- Il registro delle schede vive in memoria in un solo processo. Usa un solo worker (`viewer.py --workers 1`, il valore predefinito) se ti affidi agli strumenti `ui_*`; con più worker una chiamata può raggiungere un processo che non conosce la tua scheda e rispondere `no_tab`.
- Un utente può avere al massimo 8 schede collegate; aprirne una nona chiude la più vecchia.
- Nulla viene spinto dalla scheda verso un assistente esterno: questo conosce i progressi del piano e l'attività dell'utente solo chiamando `ui_get_context`. L'applicazione di `auto_cull` non legge la scheda.
- La protezione di stato di `auto_cull` conserva 8 piani per utente per 15 minuti. La memoria delle anteprime è separata: 300 secondi, 64 voci per tutti gli utenti. Entrambe vivono nella memoria di un solo processo; con più worker un'applicazione può raggiungere un processo che non ne ha, e la risposta riporta allora `state_guard: "unavailable"`.
