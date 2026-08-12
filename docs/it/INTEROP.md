# Ricette di interoperabilità con gli editor

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · **Italiano** · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md)

Ricette pratiche, passo dopo passo, per far circolare in entrambe le direzioni le valutazioni, le etichette e i tag di Facet con gli editor esterni e gli strumenti di gestione fototeca (DAM) che i fotografi usano davvero. Questa pagina presuppone che tu sappia già *che* Facet scrive XMP — vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione) per il riferimento completo delle opzioni `--export-sidecars` / `--import-sidecars` e la mappatura dei campi (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## L'insidia del nome dei sidecar RAW

Facet chiama un sidecar `<immagine><ext>.xmp` — ad esempio `IMG_1234.CR2.xmp` accanto a `IMG_1234.CR2` — la stessa convenzione usata da darktable e digiKam. **Lightroom Classic e Capture One si aspettano il contrario: `IMG_1234.xmp`, senza l'estensione RAW.** Nessuno dei due troverà un sidecar scritto da Facet per un file RAW proprietario (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — tutto tranne il DNG), e il `--import-sidecars` di Facet non troverà a sua volta un sidecar scritto da un'applicazione dell'ecosistema Adobe per lo stesso RAW. È un disallineamento di convenzioni tra ecosistemi, non un difetto dell'uno o dell'altro.

Questo **non** riguarda:
- **JPEG, HEIC, TIFF, PNG, DNG** — passa `--embed-originals` e Facet scrive i metadati *direttamente nel file* (tramite exiftool), quindi non c'è alcun nome di sidecar che Lightroom/Capture One possano perdere.
- **digiKam** — verifica entrambe le convenzioni di nome e trova comunque il sidecar di Facet (vedi [digiKam](#digikam) più sotto).
- **darktable** — usa la stessa convenzione `<immagine><ext>.xmp` di Facet (vedi [darktable](#darktable) più sotto).

Quindi, per un flusso Lightroom o Capture One: usa `--embed-originals` per tutto ciò che non è RAW proprietario, e aspettati che il roundtrip via sidecar resti silenzioso (nessun errore, semplicemente nulla viene letto) per i file RAW puri. Se scatti in RAW+JPEG, il JPEG di accompagnamento è il veicolo pratico di interoperabilità — il RAW resta sul disco, intatto, mentre il database di Facet conserva la valutazione autorevole.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (aggiungi un percorso per limitare l'ambito, ad esempio `--export-sidecars /foto/matrimonio-2026`). Aggiungi `--embed-originals` per scrivere anche direttamente nei file JPEG/HEIC/TIFF/PNG/DNG.
2. Nel modulo Libreria di Lightroom Classic, seleziona le foto (Ctrl/Cmd+A per tutte) e scegli **Metadati → Leggi metadati dal file**. Lightroom sovrascrive la valutazione, l'etichetta colore e le parole chiave del suo catalogo a partire dal sidecar (o dai metadati incorporati, per i formati sopra indicati).

Il marcatore di rifiuto di Facet (`xmp:Rating = -1`) viene riletto come il flag Rifiuta di Lightroom. Un preferito di Facet scrive `xmp:Label = Yellow`, che Lightroom mostra come **etichetta colore Gialla** — non come flag Seleziona (Pick). Se il tuo flusso Lightroom si basa sui flag Pick anziché sulle etichette colore, aggiungi un passaggio di conversione etichetta-colore → pick, oppure filtra invece sull'etichetta Gialla.

Un feed `python facet.py --export-manifest` (percorso, categoria, tutti i punteggi, tag e le stesse colonne di valutazione di `--export-sidecars`) esiste ora per gli strumenti che vogliono i dati di Facet senza analizzare l'XMP — vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione). È proprio questo feed che il plug-in Facet descritto qui sotto consuma.

### Il plug-in Facet (valutazioni a stelle e flag Pick)

`facet.lrplugin/`, nel repository di Facet, è un plug-in per Lightroom Classic che scrive la valutazione a stelle e lo stato preferito/rifiutato di Facet **direttamente nel catalogo**. Esiste perché due delle cose descritte sopra non sono risolvibili dal lato XMP: Lightroom non trova mai un sidecar di Facet per un file RAW proprietario, e l'XMP non ha alcun canale per il flag Seleziona (Pick) di Lightroom. Il plug-in legge un file manifest: non parla mai con il server di Facet, non richiede password e funziona anche a Facet spento — e poiché abbina le foto per percorso anziché per sidecar, **una libreria interamente RAW funziona esattamente come una libreria JPEG**.

**Installazione** (una sola volta):

1. Copia la cartella `facet.lrplugin` sulla macchina che esegue Lightroom. Su macOS comprimila prima in zip — il Finder tratta una cartella `.lrplugin` come un bundle.
2. In Lightroom Classic: **File → Gestione plug-in → Aggiungi**, seleziona la cartella `facet.lrplugin`, poi **Fine**.

**Uso** (ogni volta che vuoi il verdetto di Facet nel catalogo):

1. `python facet.py --export-manifest /foto/matrimonio-2026` (il percorso limita l'ambito; il file viene sempre scritto come `facet_manifest.json` nella directory corrente). Copialo sulla macchina con Lightroom se Facet gira altrove.
2. Nel modulo Libreria seleziona le foto, poi **Libreria → Extra plug-in → Facet: Apply ratings and flags...** (l'interfaccia del plug-in è in inglese).
3. Indica il file `facet_manifest.json`. Il percorso viene ricordato per la volta successiva.
4. **Se Facet ha analizzato le foto da un'altra macchina, compila i due prefissi di percorso.** Il manifest contiene i percorsi della macchina che ha fatto la scansione (`/volume1/photos/...` su un NAS), mentre Lightroom conosce quelli della postazione (`Z:\photos\...`). Inserisci il prefisso Lightroom e il prefisso Facet che indicano la stessa cartella; lasciali entrambi vuoti quando coincidono. È l'unico errore al primo avvio che conta davvero — semplicemente non abbina nulla.
5. Scegli l'ambito: le foto selezionate (predefinito) oppure tutte le foto della cartella corrente.
6. Premi **Preview...** (Anteprima). **Non viene ancora scritto nulla.** Il plug-in indica quante foto ha trovato nel manifest, quante no, e quante valutazioni e flag imposterebbe. Se il numero di corrispondenze è 0, mostra un percorso di esempio di Lightroom accanto a uno del manifest, così vedi come devono essere i prefissi.
7. Premi **Apply** (Applica). L'avanzamento è visibile e annullabile; una finestra di riepilogo riporta ciò che è stato impostato, saltato e non trovato.

**Cosa scrive** — nient'altro, e mai nei tuoi file immagine:

| Stato Facet | Campo Lightroom |
|---|---|
| `star_rating` 1-5 | valutazione a stelle |
| preferito | flag Seleziona (Pick) |
| rifiutato | flag Rifiuta (Reject) |

Una valutazione Facet pari a 0 significa «nessun parere» (vedi `xmp_export.score_to_rating`) e non viene mai scritta.

**Semantica di sovrascrittura** — per impostazione predefinita il plug-in non ti contraddice mai: imposta una valutazione solo se la foto è *non valutata* in Lightroom, e un flag solo se la foto è *senza flag*. Tutto ciò che hai valutato o contrassegnato a mano resta intatto e viene contato come «kept as they are» (lasciate come sono) nell'anteprima. Spunta **Overwrite ratings and flags that are already set in Lightroom** per sostituirle comunque. Questo rispecchia `only_when_unrated` in `xmp_export.score_to_rating`, così il plug-in e il percorso sidecar trattano allo stesso modo le tue modifiche manuali.

**Limiti**, in tutta onestà:

- **I flag Pick esistono solo nel catalogo.** È una scelta di Lightroom, non del plug-in: Lightroom non scrive mai il flag Pick nell'XMP, quindi non raggiunge nessun'altra applicazione e va perso se ricostruisci il catalogo dai file. Le valutazioni a stelle invece sopravvivono, tramite **Metadati → Salva metadati nel file**.
- **I punteggi di Facet non vengono aggiunti come campi di metadati di Lightroom**, quindi non esiste una raccolta dinamica «aggregate > 8». L'SDK di Adobe ammette i campi propri di un plug-in nel vocabolario di ricerca solo come testo o enumerazione (`sdktext:`); gli operatori numerici (`>`, `<`, «è compreso tra») restano riservati ai criteri integrati di Lightroom. Far passare il punteggio dalla **valutazione a stelle** è deliberato: è l'unico canale che Lightroom stesso filtra e ordina numericamente.
- **Senso unico.** Le valutazioni che modifichi poi in Lightroom tornano a Facet tramite il giro XMP descritto sopra, non tramite il plug-in.
- **L'annullamento** funziona un lotto alla volta: il plug-in scrive a blocchi di 200 foto, quindi Ctrl/Cmd+Z annulla 200 foto per volta.
- Spunta **Write facet-apply.log next to the manifest** prima di un'esecuzione se ti serve vedere, riga per riga, quali percorsi hanno trovato corrispondenza e cosa è stato scritto.

### Lightroom → Facet

1. In Lightroom, seleziona le foto e scegli **Metadati → Salva metadati nel file** (Ctrl/Cmd+S). Questo riversa la valutazione, l'etichetta e le parole chiave del catalogo nel sidecar XMP (RAW) oppure le incorpora direttamente nel file (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (eventualmente limitato a un percorso) le rilegge nel database di Facet.

### Regole di conflitto

- **Valutazioni ed etichette seguono la regola "vince il più recente"**, confrontando `xmp:MetadataDate` del sidecar con `scanned_at` della foto (l'ultima volta che Facet l'ha valutata) — non un timestamp per singola valutazione. Un sidecar più recente dell'ultima scansione può sovrascrivere una valutazione che hai modificato in Facet *dopo* quella scansione. Mantieni semplice il roundtrip: esportazione → Lightroom legge → modifica in Lightroom → Lightroom salva → importazione, senza rivalutare in Facet nel frattempo.
- **Tag e parole chiave vengono sempre uniti** (unione, deduplicati) in entrambe le direzioni — le parole chiave di Lightroom non cancellano mai i tag automatici di Facet, e viceversa.
- **Multiutente** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): le valutazioni vengono instradate nella riga `user_preferences` di Alice invece che nelle colonne globali. Le parole chiave restano globali indipendentemente da `--user` — sono condivise tra utenti.
- Esegui `python database.py --migrate-tags` dopo `--import-sidecars` se usi la tabella di lookup `photo_tags`, così i filtri sui tag vedono subito le parole chiave unite.

## Capture One

Capture One non scrive mai nel file originale né in un sidecar XMP sincronizzato in continuo come fa il salvataggio automatico di Lightroom — mantiene le proprie regolazioni in file `.cos` (Sessioni) o nel proprio database del catalogo, e la sua preferenza **Sync Metadata** ha una modalità bidirezionale "Full Sync" che può sovrascrivere silenziosamente il lato che ha scritto per ultimo. Far girare un ciclo bidirezionale tramite quell'impostazione rischia di perdere le modifiche di Facet o quelle di Capture One. Lo schema sicuro è **a senso unico, Facet → Capture One**:

1. `python facet.py --export-sidecars /percorso/dello/scatto --embed-originals`.
2. In Capture One, lascia **Preferences → General → Sync Metadata** al suo valore predefinito (non "Full Sync").
3. Seleziona le immagini importate, fai clic destro e scegli **Load Metadata** per far entrare una sola volta la valutazione, l'etichetta e le parole chiave dal sidecar (o dai metadati incorporati) nei campi del catalogo di Capture One.

Considera Facet come la fonte di verità a monte per le valutazioni e i tag derivati dall'IA di quello scatto: esegui l'importazione una tantum tramite `Load Metadata`, poi effettua ulteriori scelte in Capture One senza ricollegare la sua sincronizzazione dei metadati al sidecar di Facet. Se vuoi riportare le scelte di Capture One in Facet, esportale esplicitamente da Capture One a XMP ed esegui `--import-sidecars` su quella cartella come passaggio separato e deliberato piuttosto che come sincronizzazione automatica — e ricorda l'[insidia del nome dei sidecar RAW](#linsidia-del-nome-dei-sidecar-raw) sopra: questo funziona solo per JPEG/HEIC/TIFF/PNG/DNG, poiché anche Capture One chiama i sidecar RAW `<immagine>.xmp` anziché il `<immagine><ext>.xmp` di Facet.

## digiKam

A partire da digiKam 9.1.0 (rilasciata il 2026-06-07), digiKam legge nativamente i sidecar XMP — nessun bisogno di exiftool lato digiKam — e cerca entrambe le convenzioni di nome (prima `<immagine><ext>.xmp`, poi come ripiego `<immagine>.xmp`), quindi trova i sidecar di Facet per i file RAW senza l'insidia descritta sopra. Dopo `python facet.py --export-sidecars`, apri (o aggiorna) la cartella in digiKam: recupera automaticamente valutazione, etichetta colore, parole chiave e zone volto nominate, purché **Settings → Configure digiKam → Metadata → Read from sidecar files** sia attivo (il predefinito).

### Hook del Batch Queue Manager

Puoi integrare una reimportazione di Facet in un flusso Batch Queue Manager (BQM) di digiKam con lo strumento **Custom Script**, così le foto che valuti o etichetti in digiKam rifluiscono nel database di Facet senza uscire da digiKam. Attiva **Settings → Configure digiKam → Metadata → Write to sidecar files** perché digiKam persista subito le tue modifiche in `<immagine>.xmp`, poi aggiungi una coda il cui unico strumento è Custom Script:

```bash
#!/bin/bash
python /percorso/di/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sono i segnaposto per file di digiKam (il BQM esegue lo script tramite `/bin/bash` su Linux/macOS e si aspetta un file di output, da cui il passaggio `cp`). Poiché `--import-sidecars` analizza l'intera cartella, eseguirlo una volta per ogni foto in un lotto numeroso è ridondante, anche se innocuo (è idempotente — le foto invariate vengono saltate). Per lotti grandi, evita l'hook BQM ed esegui semplicemente a mano `python facet.py --import-sidecars /percorso/della/cartella` una volta terminata la coda.

## darktable

darktable riceve già un trattamento di prim'ordine in [Configurazione — Viewer](CONFIGURATION.md#viewer) (profili/stili di esportazione `viewer.raw_processor.darktable`) e [Viewer — Download](VIEWER.md#endpoint-api) (conversioni `type=darktable`). Sul fronte XMP: darktable scrive il proprio `<immagine><ext>.xmp` per memorizzare la sua cronologia di modifiche, e lo scrittore di sidecar di Facet, basato su exiftool, si fonde in quello stesso file sul posto — i nodi `darktable:history`/maschere vengono preservati, mai sovrascritti. Non serve una ricetta separata qui: il comportamento bidirezionale del sidecar descritto sopra per Lightroom (esportazione/importazione, vince il più recente, unione dei tag) si applica allo stesso modo, senza l'insidia del nome RAW poiché darktable e Facet concordano su `<immagine><ext>.xmp`.

**Attenzione: il ricaricamento dell'XMP da parte di darktable non è affidabile.** Indipendentemente dal percorso di scrittura di Facet, reimportare un'immagine che darktable ha già modificato può far sì che darktable sovrascriva la cronologia di modifiche del sidecar con una vuota invece di ricaricarla — un bug upstream aperto ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), segnalato il 2026-03-15) da cui la preferenza "check for new/updated xmp files on start" non protegge. Facet non ne è la causa (la fusione tramite exiftool sopra preserva già `darktable:history`), ma il rischio sta proprio nel passaggio di rilettura da cui dipende il roundtrip di questa pagina. Soluzione pratica, seguendo la stessa disciplina "una tantum" della ricetta Capture One sopra: dopo `--export-sidecars`, non reimportare in blocco una cartella già modificata — ricarica i sidecar solo per le immagini che Facet ha appena toccato, e verifica che la cronologia di modifiche sia ancora presente prima di fidarti del resto del lotto.

## Come fonde Facet

| Campo | Facet scrive | Facet rilegge | Regola di conflitto |
|---|---|---|---|
| Valutazione (stelle/rifiuto) | `xmp:Rating` (`-1` = rifiutata) | `xmp:Rating` | Vince il più recente, vs `scanned_at` |
| Etichetta colore | `xmp:Label` (`Red` = rifiutata, `Yellow` = preferita) | `xmp:Label` | Vince il più recente, vs `scanned_at` |
| Tag / parole chiave | `dc:subject` (piatto, include i nomi delle persone dalle zone volto nominate) | `dc:subject` | Sempre unito (unione, deduplicato) |
| Tag gerarchici | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<nome>`) | Non reimportato | Solo esportazione |
| Didascalia | `dc:description` (+ `IPTC:Caption-Abstract` tramite exiftool) | Non reimportato | Solo esportazione |
| Zone volto nominate | `mwg-rs:RegionList` MWG (centrata-normalizzata, `Type=Face`) | Non reimportato | Solo esportazione; letto nativamente da digiKam, **non** letto da Lightroom (una limitazione nota di Adobe — Lightroom consuma solo le zone MWG che ha scritto lui stesso) |

Vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione) per il riferimento CLI completo (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
