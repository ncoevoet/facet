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

digiKam legge nativamente i sidecar XMP — nessun bisogno di exiftool lato digiKam — e cerca entrambe le convenzioni di nome (prima `<immagine><ext>.xmp`, poi come ripiego `<immagine>.xmp`), quindi trova i sidecar di Facet per i file RAW senza l'insidia descritta sopra. Dopo `python facet.py --export-sidecars`, apri (o aggiorna) la cartella in digiKam: recupera automaticamente valutazione, etichetta colore, parole chiave e zone volto nominate, purché **Settings → Configure digiKam → Metadata → Read from sidecar files** sia attivo (il predefinito).

### Hook del Batch Queue Manager

Puoi integrare una reimportazione di Facet in un flusso Batch Queue Manager (BQM) di digiKam con lo strumento **Custom Script**, così le foto che valuti o etichetti in digiKam rifluiscono nel database di Facet senza uscire da digiKam. Attiva **Settings → Configure digiKam → Metadata → Write to sidecar files** perché digiKam persista subito le tue modifiche in `<immagine>.xmp`, poi aggiungi una coda il cui unico strumento è Custom Script:

```bash
#!/bin/bash
python /percorso/di/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sono i segnaposto per file di digiKam (il BQM esegue lo script tramite `/bin/bash` su Linux/macOS e si aspetta un file di output, da cui il passaggio `cp`). Poiché `--import-sidecars` analizza l'intera cartella, eseguirlo una volta per ogni foto in un lotto numeroso è ridondante, anche se innocuo (è idempotente — le foto invariate vengono saltate). Per lotti grandi, evita l'hook BQM ed esegui semplicemente a mano `python facet.py --import-sidecars /percorso/della/cartella` una volta terminata la coda.

## darktable

darktable riceve già un trattamento di prim'ordine in [Configurazione — Viewer](CONFIGURATION.md#viewer) (profili/stili di esportazione `viewer.raw_processor.darktable`) e [Viewer — Download](VIEWER.md#endpoint-api) (conversioni `type=darktable`). Sul fronte XMP: darktable scrive il proprio `<immagine>.xmp` per memorizzare la sua cronologia di modifiche, e lo scrittore di sidecar di Facet, basato su exiftool, si fonde in quello stesso file sul posto — i nodi `darktable:history`/maschere vengono preservati, mai sovrascritti. Non serve una ricetta separata qui: il comportamento bidirezionale del sidecar descritto sopra per Lightroom (esportazione/importazione, vince il più recente, unione dei tag) si applica allo stesso modo, senza l'insidia del nome RAW poiché darktable e Facet concordano su `<immagine><ext>.xmp`.

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
