# Ricette di interoperabilità con gli editor

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · **Italiano** · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Ricette passo dopo passo per portare valutazioni, etichette e tag di Facet da e verso Lightroom, Capture One, digiKam e darktable. Per il riferimento completo delle opzioni `--export-sidecars` / `--import-sidecars` e la mappatura dei campi (`xmp:Rating`, `xmp:Label`, `dc:subject`), vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione).

Gli originali non vengono mai modificati a meno che tu non chieda l'incorporamento: `--embed-originals` da riga di comando, oppure **Scrivi metadati nel file** nel visualizzatore.

## Cosa viene trasferito

Le posizioni manuali e le decisioni di revisione vengono trasferite solo quando esporti i metadati nel visualizzatore o esegui `--export-sidecars`.

- **GPS** usa `exif:GPSLatitude` / `exif:GPSLongitude`. Vengono esportate solo le posizioni impostate a mano, così il GPS rilevato dalla scansione non sostituisce mai quello del file. `--embed-originals` scrive anche il GPS EXIF negli originali supportati. Cancellare una posizione esporta una cancellazione esplicita; un campo mancante non cancella mai una posizione in importazione.
- **Data di scatto.** Una data corretta viene esportata come `exif:DateTimeOriginal` (e come EXIF `DateTimeOriginal` con `--embed-originals`). Dopo **Usa data del file**, l'esportazione successiva la rimuove dal sidecar, ma lascia intatta una data scritta da un altro editor.
- **Conserva e rifiuta.** Conserva è indipendente da stelle e preferiti. Rifiutare cancella Conserva, stelle e preferito.

Il namespace XMP di Facet, `https://github.com/ncoevoet/facet/ns/1.0/`, aggiunge:

| Tag | Valori | Scopo |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | Decisione di revisione di Facet |
| `facet:GPSState` | `set`, `cleared` | Se Facet ha impostato o cancellato la posizione |
| `facet:DateState` | `set` | La data di scatto del sidecar proviene da Facet |
| `facet:KeywordState` | JSON (`version` 1; elenchi `owned`, `deleted`, `ai`, `manual`) | Quali parole chiave ha scritto Facet |
| `facet:RegionOwner` | `Facet` | Le regioni di volti MWG scritte da Facet |

`facet:KeywordState` permette a `--reconcile-keywords` di rimuovere solo i nomi di proprietà di Facet e impedisce che una vecchia etichetta IA diventi un tag manuale in importazione. `facet:RegionOwner` permette a ExifTool di sostituire solo le regioni di volti di Facet.

Come `--import-sidecars` applica una decisione di Facet:

- Applica una decisione quando i campi di revisione standard concordano con essa o sono assenti.
- Se lo stato di rifiuto standard non concorda, un altro editor ha modificato i campi standard. Facet ignora la propria decisione privata e usa il controllo «vince il più recente» della data di scansione sui campi standard.
- Anche una decisione esportata insieme ai campi di revisione standard usa il controllo «vince il più recente», così un export più vecchio non può annullare una decisione più recente. Fa eccezione una foto senza ancora uno stato di revisione (né stelle, né preferito, né Conserva, né rifiuto): una libreria riscansionata recupera comunque le sue decisioni.
- Le importazioni della sola decisione restano esplicite (le richiedi tu) e vengono applicate senza il controllo della data di scansione.

Altre regole:

- Il GPS manuale già presente in Facet viene conservato a meno che tu non aggiunga `--overwrite-manual-gps`. Le coordinate non valide o incomplete vengono ignorate.
- `--user alice` limita importazioni ed esportazioni alle cartelle visibili di quell'utente e alle sue decisioni private. Il GPS resta condiviso. Senza `--user`, la CLI lavora sullo stato globale.
- Le importazioni globali (senza `--user`), incluse le anteprime con `--dry-run`, non richiedono la chiave di accesso del visualizzatore.
- Con ExifTool, l'esportazione si fonde nei sidecar esistenti. Senza, l'esportazione lascia intatto un sidecar d'editor esistente e scrive un file di ripiego.
- Le esportazioni con ExifTool richiedono le definizioni dei tag incluse in Facet. Se mancano, l'esportazione si interrompe prima di modificare qualsiasi cosa; reinstalla Facet.

## L'insidia del nome dei sidecar RAW

Facet esporta `IMG_1234.CR2.xmp` accanto a `IMG_1234.CR2` (la convenzione del nome completo di darktable). Lightroom Classic e Capture One usano generalmente `IMG_1234.xmp` per i RAW proprietari. I nomi esportati non cambiano mai.

Per JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` scrive invece nel file. GIF/WebP/BMP/AVIF/JPEG XL e i RAW proprietari richiedono comunque un sidecar con il nome corrispondente.

In importazione, scegli la convenzione dei nomi con `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (predefinito): legge `<image.ext>.xmp` o `<image.ext>.facet.xmp`, quello modificato per ultimo. A parità vince il principale.
- `basename`: legge `<image>.xmp` (viene tolta solo l'ultima estensione). I sidecar con nome completo vengono ignorati.
- `auto`: accetta il tipo che esiste. Se esistono entrambi, la foto viene saltata perché ambigua; scegli invece `full` o `basename`.

Con `basename` e `auto`, un nome base condiviso da più immagini (ad es. `same.CR3` e `same.jpg`) viene rifiutato, anche se una sola è nell'ambito. Per queste usa sidecar con nome completo. `same_v1.jpg` ha un nome base diverso e va bene.

- Un file a doppia estensione come `IMG.CR2.jpg` non legge mai `IMG.CR2.xmp`, che appartiene a `IMG.CR2`. Lo stesso vale per il ripiego `.facet.xmp` di un'altra immagine.
- Discrepanze, ambiguità e sidecar illeggibili vengono segnalate. Facet non prova un'altra convenzione dopo un errore di analisi.
- Il riepilogo conta ogni foto interessata, inclusi i sidecar ignorati a causa della convenzione scelta. Gli avvisi mostrano un esempio per tipo.
- Nessun file viene rinominato.

L'importazione non richiede ExifTool. La fusione in esportazione, l'incorporamento e i rettangoli di volti MWG richiedono ExifTool. Senza, Facet lascia intatto un sidecar d'editor esistente e scrive `<image.ext>.facet.xmp` senza rettangoli di volti. Gli altri editor non cercano quel nome, quindi passalo deliberatamente.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (aggiungi un percorso per limitare l'ambito, ad esempio `--export-sidecars /photos/2026-wedding`). Aggiungi `--embed-originals` per scrivere anche direttamente nei file JPEG/HEIC/TIFF/PNG/DNG.
2. Nel modulo Libreria di Lightroom Classic, seleziona le foto (Ctrl/Cmd+A per tutte) e scegli **Metadati → Leggi metadati dal file**. Lightroom sostituisce valutazione, etichetta colore e parole chiave con quelle del sidecar (o dei metadati incorporati).

Il marcatore di rifiuto di Facet (`xmp:Rating = -1`) viene riletto come il flag Rifiuta di Lightroom. Un preferito di Facet scrive `xmp:Label = Yellow`, che Lightroom mostra come **etichetta colore Gialla**, non come flag Seleziona (Pick). Per ottenere i Pick, usa il plug-in qui sotto oppure filtra sull'etichetta Gialla.

`python facet.py --export-manifest` scrive i dati di Facet senza XMP: percorso, categoria, tutti i punteggi, tag e le stesse colonne di valutazione di `--export-sidecars`. Usa `--export-manifest --user alice` per le valutazioni per utente. Vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione). Lo legge il plug-in Facet qui sotto.

**Manifest versione 2** aggiunge `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` e un conteggio di primo livello `pending_corrections`. Quel conteggio è il numero di correzioni manuali di bracket/panorama non ancora applicate; riesegui `--detect-panoramas` per applicarle. Il plug-in lo mostra come avviso nella sua Anteprima. Un plug-in di versione 2 rifiuta un manifest di versione 1 (e viceversa); se vedi quella finestra, esegui di nuovo `--export-manifest`.

Nel viewer, la finestra **Export to editor** della galleria ha un pulsante **Download Lightroom manifest** per la stessa selezione o filtro — vedi [Editor Export](VIEWER.md#esportazione-per-editor). Produce lo stesso `facet_manifest.json` di `--export-manifest`.

### Il plug-in Facet (valutazioni a stelle, flag Pick, campi di metadati e parole chiave)

`facet.lrplugin/`, nel repository di Facet, è un plug-in per Lightroom Classic. Scrive le valutazioni a stelle e lo stato preferito/rifiutato di Facet **direttamente nel catalogo**. Risolve due cose che l'XMP non può: Lightroom non trova mai un sidecar di Facet per i RAW proprietari, e l'XMP non può portare il flag Pick di Lightroom.

Il plug-in legge un file manifest. Non contatta mai il server di Facet, non richiede password e funziona anche a Facet spento. Abbina le foto per percorso, quindi **una libreria di soli RAW funziona come una di JPEG**.

Aggiunge due voci in **Libreria → Extra plug-in**:

- **Facet: Apply ratings and flags...** — manifest → catalogo (questa sezione).
- **Facet: Export Lightroom State to Facet...** — catalogo → Facet, vedi [Lightroom → Facet](#lightroom--facet).

**Installazione** (una sola volta):

1. Copia la cartella `facet.lrplugin` sulla macchina con Lightroom. Su macOS comprimila prima in zip: il Finder tratta una cartella `.lrplugin` come un bundle.
2. In Lightroom Classic: **File → Gestione plug-in → Aggiungi**, seleziona la cartella `facet.lrplugin`, poi **Fine**.

**Uso:**

1. `python facet.py --export-manifest /photos/2026-wedding` (il percorso limita l'ambito; il file è sempre `facet_manifest.json` nella directory corrente). Se serve, copialo sulla macchina con Lightroom.
2. Nel modulo Libreria seleziona le foto, poi **Libreria → Extra plug-in → Facet: Apply ratings and flags...**
3. Indica alla finestra il file `facet_manifest.json`. Il percorso viene ricordato.
4. **Se Facet ha analizzato le foto su un'altra macchina, compila i due prefissi di percorso.** Il manifest contiene i percorsi della macchina che ha fatto la scansione (ad es. `/volume1/photos/...` su un NAS); Lightroom ha quelli della postazione (ad es. `Z:\photos\...`). Inserisci il prefisso Lightroom e il prefisso Facet per la stessa cartella. Lasciali entrambi vuoti se i percorsi coincidono. Se sono sbagliati, non corrisponde nulla.
5. Scegli l'ambito: le foto selezionate (predefinito) oppure l'intera cartella corrente.
6. Premi **Preview...**. **Non viene ancora scritto nulla.** Mostra quante foto corrispondono, quante no e cosa imposterebbe. Se non corrisponde nulla, mostra un percorso Lightroom di esempio accanto a uno del manifest, così puoi correggere i prefissi.
7. Premi **Apply**. Puoi annullare durante l'avanzamento. Un riepilogo mostra cosa è stato impostato, saltato e non trovato.

**Cosa scrive** (mai nei tuoi file immagine):

| Stato Facet | Campo Lightroom |
|---|---|
| `star_rating` 1-5 | valutazione a stelle |
| preferito | flag Seleziona (Pick) |
| rifiutato | flag Rifiuta (Reject) |

Una valutazione Facet pari a 0 significa «nessun parere» e non viene mai scritta.

**Regola di sovrascrittura.** Per impostazione predefinita il plug-in imposta una valutazione solo su una foto *non valutata* in Lightroom, e un flag solo su una *senza flag*. Le tue valutazioni e i tuoi flag restano e vengono contati come «kept as they are». Spunta **Overwrite ratings and flags that are already set in Lightroom** per sostituirli. L'esportazione dei sidecar segue la stessa regola (`xmp_export.score_to_rating.only_when_unrated`, predefinito `true`).

**Opzioni della finestra** (tutte disattivate per impostazione predefinita, memorizzate tra le esecuzioni):

- **Fill in star ratings from Facet scores for photos you have not rated** — se il manifest non ha `star_rating` (o è 0), il punteggio `aggregate` viene convertito in stelle. Questo ripiego **non sovrascrive mai una valutazione Lightroom esistente, nemmeno con Overwrite spuntata.**
- **Pick the recommended frame of each burst** — in ogni gruppo di raffica con almeno 2 membri, ogni membro segnato `is_burst_lead` viene impostato su Pick (una raffica può conservarne più di uno). I fotogrammi isolati e i gruppi senza fotogramma guida vengono saltati. I tuoi flag Pick/Reject e i preferiti/rifiuti di Facet vincono sempre.
- **Reject the other frames** (solo con l'opzione pick) — rifiuta ogni membro della raffica che non è il fotogramma guida. I membri di un bracket, panorama o panorama HDR non vengono mai rifiutati, e i gruppi senza fotogramma guida non ricevono rifiuti.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — per ogni gruppo con almeno 2 foto corrispondenti nell'ambito, crea o riusa una collezione sotto `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` o `Facet › HDR panoramas`.
  - Nome: `<yyyy-mm-dd HH:MM:SS> – <filename>` del membro più antico, oppure `~ (no date) – <filename>` se non ha un orario di scatto.
  - Una raffica i cui membri appartengono tutti a un solo set bracket o panorama non ottiene una collezione Bursts separata.
  - **Rieseguire aggiunge soltanto foto.** Una foto che in seguito esce da un set resta nella sua collezione.
  - Limite noto: due gruppi i cui membri più antichi condividono lo stesso secondo di scatto e lo stesso nome file (ad es. due fotocamere che scrivono `IMG_0001`) condividono una sola collezione.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (solo con l'opzione precedente) — svuota e riempie di nuovo una collezione, ma solo quando la collezione e tutto il suo gruppo rientrano nell'ambito corrente. Le collezioni coperte solo in parte e le collezioni intelligenti vengono saltate.
    - Svuota ed elimina anche la collezione di un gruppo che si è dissolto in questa esecuzione, ma solo se ogni foto che contiene è stata trovata da questa esecuzione.
    - Tocca solo le collezioni il cui nome ha il formato proprio di Facet (data-ora oppure `~ (no date)`, poi ` – <filename>`). Le collezioni che hai nominato tu non vengono mai toccate.
    - L'anteprima mostra una riga `Facet collections to delete: N` quando c'è qualcosa da eliminare. Il riepilogo riporta le collezioni ricostruite, eliminate, saltate e fallite.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — scrive il punteggio aggregato (ad es. `8.4`), una fascia intera (`0`-`10`), la categoria e il tipo di set nei campi di metadati propri di Facet. Compaiono nel pannello Metadati e funzionano come criteri testuali (`sdktext:`) nel Filtro libreria e nelle collezioni intelligenti, ad es. fascia «una tra 8, 9, 10». Un campo che non si applica più viene svuotato. Vengono scritte anche due proprietà di servizio nascoste (la valutazione e il pick derivati da questa esecuzione); sono escluse dalla ricerca ma in alcune versioni di Lightroom Classic potrebbero comunque essere visibili (non verificato).
- **Create "Facet" keywords from Facet tags (never included on export)** — crea una parola chiave radice `Facet` con un figlio per ogni tag (IA e [tag manuali](#tag-manuali-e-parole-chiave-xmp)). I figli `Facet ›` di ogni foto vengono impostati in modo da corrispondere ai suoi tag, quindi un tag rimosso in Facet sparisce al successivo Apply. `Include on Export` è disattivato per tutti, così non finiscono mai in esportazioni o gallerie per il cliente. Le tue parole chiave fuori dalla radice `Facet` non vengono mai modificate. Una parola chiave `Facet` di primo livello già esistente viene adottata come radice, e ogni figlio che vi hai aggiunto tu viene rimosso.

**Perché collezioni e non stack.** L'SDK di Lightroom non può creare stack. Per raggruppare in stack le foto di una collezione, selezionale e usa **Foto → Raggruppamento → Raggruppa in stack** (Ctrl/Cmd+G).

**Limiti:**

- **I flag Pick restano nel catalogo.** Lightroom non li scrive mai nell'XMP, quindi nessun'altra app li vede, e ricostruire il catalogo dai file li perde. Le valutazioni a stelle sopravvivono tramite **Metadati → Salva metadati nel file**.
- **Nessuna collezione intelligente numerica sui campi Facet.** I campi dei plug-in sono solo testuali (`sdktext:`); gli operatori numerici (`>`, `<`, «è compreso tra») funzionano solo sui campi integrati di Lightroom. Usa il campo fascia, oppure l'opzione di riempimento delle stelle, che Lightroom ordina e filtra numericamente.
- **L'annullamento** ripristina un lotto di 200 foto per ogni Ctrl/Cmd+Z.
- Spunta **Write facet-apply.log next to the manifest** per registrare quali percorsi hanno corrisposto e cosa è stato scritto.

### Lightroom → Facet

**Valutazioni, pick e rifiuti — vince Lightroom (tramite il plug-in).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** apre un pannello di salvataggio. Il file contiene un record per foto: `path`, più `rating`/`pick` quando devono viaggiare.
2. Importalo con `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` è obbligatorio su un'installazione multiutente), oppure con **Import Lightroom state…** nella finestra **Export to editor** della galleria.

Il valore di Lightroom vince per ogni campo di un record. L'importazione riporta i conteggi `matched`/`unmatched`/`changed`.

| Stato Lightroom | Risultato Facet |
|---|---|
| Flag Pick = Selezionata (`pick = 1`) | preferito = attivo, rifiutato = disattivo |
| Flag Pick = Rifiutata (`pick = -1`) | preferito = disattivo, rifiutato = attivo |
| Flag Pick = nessuno (`pick = 0`) | preferito = disattivo, rifiutato = disattivo |
| valutazione a stelle (`rating`, 0-5) | `star_rating` (`0` la azzera) |

- Un record senza `rating` o `pick` lascia intatto quel valore di Facet. L'esportazione include un campo solo quando il valore di Lightroom differisce da quello impostato dall'ultimo Apply, quindi una foto non toccata non cambia nulla.
- Le copie virtuali vengono unite al proprio originale prima dell'esportazione.
- Un'importazione riuscita che cambia qualcosa aggiorna le coppie di addestramento e arma l'auto-riaddestramento, come qualsiasi modifica di valutazione.

> **Attenzione:** poiché vince Lightroom, una foto che il passaggio Apply non ha mai toccato e che in Lightroom è senza valutazione e senza flag (`pick = 0`, nessun `rating`) azzera in importazione la sua valutazione a stelle, il preferito e il rifiuto in Facet.

**Valutazioni, etichette e parole chiave via XMP** (a senso unico):

1. In Lightroom, seleziona le foto e scegli **Metadati → Salva metadati nel file** (Ctrl/Cmd+S). Questo scrive valutazione, etichetta e parole chiave nel sidecar XMP (RAW) o nel file (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` legge i sidecar RAW. I nomi base RAW/JPEG condivisi vengono rifiutati. Questo comando non legge i metadati incorporati. Le parole chiave importate diventano tag manuali.

### Regole di conflitto

- **Tag e parole chiave vengono uniti per impostazione predefinita.** Le esportazioni aggiungono parole chiave Facet; `--reconcile-keywords` rimuove inoltre i nomi obsoleti di proprietà di Facet. Le importazioni aggiungono tag manuali e non sostituiscono mai i tag IA. Vedi [Tag manuali e parole chiave XMP](#tag-manuali-e-parole-chiave-xmp).
- **Multiutente** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): le valutazioni vanno alle valutazioni di Alice (`user_preferences`) invece che a quelle globali. Le parole chiave sono sempre globali: i tag manuali sono condivisi.
- Le parole chiave importate vengono memorizzate in `photo_manual_tags`, che i filtri sui tag leggono direttamente. Dopo `--import-sidecars` non serve `python database.py --migrate-tags`.

## Capture One

Capture One mantiene le proprie impostazioni in file `.cos` (Sessioni) o nel catalogo. La sua modalità «Full Sync» di **Sync Metadata** può sovrascrivere il lato che ha scritto per ultimo, quindi un ciclo bidirezionale può perdere modifiche. Usa un flusso **a senso unico, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. In Capture One, lascia **Preferences → General → Sync Metadata** al valore predefinito (non "Full Sync").
3. Seleziona le immagini, fai clic destro e scegli **Load Metadata** per caricare una volta valutazione, etichetta e parole chiave.

Poi continua a lavorare in Capture One senza sincronizzazione automatica. Per riportare in Facet l'XMP salvato, esegui `--import-sidecars /path/to/shoot --sidecar-naming basename` per i sidecar RAW senza estensione, oppure `full` per i nomi completi. I nomi base RAW/JPEG condivisi vengono rifiutati. Questo legge i sidecar, non i metadati incorporati.

## digiKam

Le [impostazioni sidecar di digiKam](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) usano una sola convenzione: `filename.ext.xmp` per impostazione predefinita, oppure `filename.xmp` con **Sidecar file names are compatible with commercial programs** attivato. Non le prova entrambe.

- **Facet → digiKam:** usa l'impostazione a nome completo, attiva **Read from sidecar files**, rileggi i metadati dai file e verifica i campi.
- **digiKam → Facet:** passa `--sidecar-naming full` o `basename` in base alla tua impostazione di digiKam.

Stelle, etichette colore e flag di selezione hanno significati leggermente diversi in ciascuna app, quindi verifica il risultato.

### Hook del Batch Queue Manager

Puoi eseguire un'importazione Facet dal **Custom Script** del Batch Queue Manager (BQM) di digiKam. Prima attiva la scrittura dei sidecar, salva l'impostazione dei nomi e applica le modifiche ai metadati in attesa (digiKam può ritardare le scritture). Questo esempio presuppone sidecar a nome completo; usa `basename` solo per una raccolta senza nomi base condivisi:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sono i segnaposto per file di digiKam. Il BQM si aspetta un file di output, da cui il `cp`. `--import-sidecars` analizza l'intera cartella, quindi eseguirlo per ogni foto è ridondante ma innocuo. Per lotti grandi, esegui `python facet.py --import-sidecars /path/to/folder` una sola volta al termine della coda.

## darktable

Vedi [Configurazione — Viewer](CONFIGURATION.md#viewer) (profili e stili di esportazione `viewer.raw_processor.darktable`) e [Viewer — Download](VIEWER.md#download) (conversioni `type=darktable`).

darktable memorizza la propria cronologia di modifiche in un proprio `<immagine><ext>.xmp`. Lo scrittore ExifTool di Facet si fonde in quel file e conserva i nodi `darktable:history` e delle maschere. Il comportamento dei sidecar descritto sopra per Lightroom (esportazione/importazione, vince il più recente, unione dei tag) si applica così com'è, e non c'è alcuna discrepanza nei nomi RAW: entrambi usano `<immagine><ext>.xmp`.

**Versione di ExifTool:**

- Si consiglia la **13.28 o successiva**.
- Le modifiche dei volti richiedono la **12.65 o successiva**. Le versioni più vecchie o sconosciute saltano le modifiche dei volti con un avviso ed esportano il resto.
- Le versioni **da 13.23 a 13.27** corrompono i sidecar che contengono la cronologia di darktable, quindi Facet rifiuta di scrivere con esse e ti chiede di aggiornare. L'immagine Docker fissa una versione sicura. I pacchetti di distribuzione possono non farlo (il `libimage-exiftool-perl` di Debian trixie è alla 13.25).

> **Attenzione:** darktable stesso può cancellare la cronologia di modifiche quando reimporta un'immagine già modificata: può sovrascrivere la cronologia del sidecar con una vuota. È un bug upstream aperto ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), segnalato il 2026-03-15), e la preferenza "check for new/updated xmp files on start" non lo previene. Dopo `--export-sidecars`, non reimportare in blocco una cartella già modificata. Ricarica solo le immagini che Facet ha toccato e verifica prima la loro cronologia.

## Tag manuali e parole chiave XMP

Facet conserva i tag che digiti tu (vedi [Galleria web — Tag manuali](VIEWER.md#tag-manuali)) in `photo_manual_tags`, separati dai tag IA di `photos.tags`. Una nuova scansione o una nuova etichettatura non li tocca mai.

- **Esportazione.** Ogni scrittore di parole chiave emette prima i tag IA, poi i tag manuali, poi i nomi delle persone, senza duplicati e senza distinguere maiuscole e minuscole. Questo vale per `--export-sidecars`, per le azioni di esportazione XMP e «Scrivi metadati nel file» della galleria, e per il manifest di Lightroom (`--export-manifest`, `/api/lightroom/manifest`).
- **Importazione.** `--import-sidecars` legge le parole chiave piatte da `dc:subject` e i percorsi gerarchici separatamente da `lr:hierarchicalSubject`. Le parole chiave piatte vengono normalizzate come i tag digitati: senza spazi ai bordi, minuscole, al massimo 64 caratteri, 50 tag manuali per foto. Ognuna diventa un tag manuale con origine `xmp`, a meno che:
  - sia già uno dei tag IA o dei nomi di persona della foto,
  - duplichi un percorso presente esplicitamente in `lr:hierarchicalSubject`,
  - contenga una virgola o un carattere di controllo, oppure
  - superi il limite.
- **La rimozione delle parole chiave è esplicita.** Per impostazione predefinita le esportazioni si limitano ad aggiungere. `--export-sidecars /path --reconcile-keywords` (richiede ExifTool) rimuove anche i nomi che Facet aveva scritto in precedenza e che non sono più in Facet. Le parole chiave che Facet non ha mai scritto non vengono mai rimosse, anche se il nome coincide, e i vecchi sidecar senza marcatori non conferiscono a Facet alcuna proprietà. Se riaggiungi in un altro editor una parola chiave rimossa, Facet può importarla di nuovo e da allora la considera esterna. Le parole chiave sono condivise anche con `--user`.
- **Le parole chiave di Facet vincono in esportazione.** Una parola chiave ancora presente in Facet viene riscritta anche se un altro editor l'ha rimossa dal file. Per rimuoverla definitivamente, rimuovi il tag in Facet. La riconciliazione non elimina mai tag da Facet.
- Nomi come `2024`, `1.50`, `1e3`, `true`, `false` e `null` mantengono la grafia.
- Se Facet non riesce a leggere i metadati di un file esistente, l'esportazione si interrompe prima di scrivere.
- **Il manifest di Lightroom, invece, propaga le rimozioni.** L'opzione per le parole chiave del plug-in riscrive i figli `Facet ›` di ogni foto a ogni Apply.
- **I tag IA restano tag IA.** I sidecar registrano quali parole chiave erano IA e quali manuali, così una nuova etichettatura non trasforma una vecchia parola chiave IA in un tag manuale. I sidecar di versioni più vecchie di Facet mantengono il vecchio comportamento additivo.
- **Gerarchie.** I percorsi importati vengono aggiunti alla gerarchia condivisa; i nomi piatti contenenti `|` o `/` non creano da soli una gerarchia. I percorsi contrassegnati come generati da Facet non vengono importati come assegnazioni manuali, salvo che siano anche contrassegnati come manuali. Un sidecar di Facet 1.28 o precedente contiene `facet:KeywordState` ma non `facet:HierarchyState`; i suoi percorsi `Category|` e `People|` sono considerati generati e vengono ignorati, compresi quelli digitati da un utente, e ogni percorso ignorato compare nell’anteprima dell’importazione come `legacy_generated_path`. Le esportazioni includono assegnazioni esplicite e percorsi generati di categorie/persone. Per impostazione predefinita l’esportazione aggiunge percorsi; `--reconcile-keywords` rimuove solo quelli obsoleti di proprietà di Facet e conserva quelli esterni.
- **Limiti di proprietà:** 10.000 nomi per elenco e 1.024 caratteri per nome. Un'esportazione che li superasse si interrompe prima di scrivere. Archivia e ripulisci a mano un sidecar simile prima di ricominciare.
- **Le parole chiave importate da una versione precedente di Facet restano dove sono.** Le versioni precedenti univano le parole chiave in `photos.tags`, dove sembrano tag IA, e nulla le migra. Per trasformarne una in tag manuale, svuota o rietichetta `photos.tags`, poi esegui di nuovo `--import-sidecars` — oppure aggiungi il tag a mano.
- **File spostati o rinominati.** I tag manuali sono legati al percorso del catalogo. Dopo aver spostato i file, usa la [procedura di ricollegamento](RELINK.md) con revisione preliminare per aggiornare il percorso e conservare i tag; la sola scansione della nuova posizione non li trasferisce.
- **`--export-csv` e `--export-json` restano solo IA.** Il loro valore `tags` non contiene tag manuali.

## Come fonde Facet

| Campo | Facet scrive | Facet rilegge | Regola di conflitto |
|---|---|---|---|
| Valutazione (stelle/rifiuto) | `xmp:Rating` (`-1` = rifiutata) | `xmp:Rating` | Orologi di revisione; fallback storico scansione |
| Etichetta colore | `xmp:Label` (`Red` = rifiutata, `Yellow` = preferita) | `xmp:Label` | Orologi di revisione; fallback storico scansione |
| Tag / parole chiave | `dc:subject` (piatto, tag IA + tag manuali, include i nomi delle persone riconosciute) | `dc:subject` (memorizzato come tag manuali) | Additivo per impostazione predefinita; `--reconcile-keywords` rimuove solo nomi obsoleti di Facet; gli import restano additivi ([Tag manuali e parole chiave XMP](#tag-manuali-e-parole-chiave-xmp)) |
| Tag gerarchici | `lr:hierarchicalSubject` (assegnazioni esplicite e percorsi generati di categorie/persone) | `lr:hierarchicalSubject` (assegnazioni alla gerarchia condivisa) | Importazione additiva; la riconciliazione in esportazione rimuove solo percorsi obsoleti di Facet |
| Didascalia | `dc:description` lingua predefinita (+ `IPTC:Caption-Abstract` tramite exiftool) | Non reimportato | Solo esportazione |
| Zone volto nominate | `mwg-rs:RegionList` + `facet:RegionOwner=Facet` MWG (centrata-normalizzata, `Type=Face`) | Non reimportato | Solo esportazione; letto nativamente da digiKam, **non** letto da Lightroom (una limitazione nota di Adobe — Lightroom consuma solo le zone MWG che ha scritto lui stesso) |

Vedi [Comandi — Anteprima ed esportazione](COMMANDS.md#anteprima-ed-esportazione) per il riferimento CLI completo (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**Cancellazioni del GPS.** Se un sidecar ha sia i campi GPS standard sia un vecchio `facet:GPSState=cleared`, prevale una coppia completa e valida di latitudine/longitudine. Una coppia parziale o non valida viene ignorata e non cancella mai una posizione. Solo una coppia assente o vuota più il marcatore di cancellazione cancella il GPS. Il GPS manuale resta protetto a meno che tu non chieda di sovrascriverlo.

**Didascalie.** Con ExifTool, l'esportazione aggiorna solo la lingua predefinita (`x-default`) di `dc:description` e conserva le altre lingue. Una didascalia vuota in Facet lascia intatte quelle esistenti. Senza ExifTool, Facet scrive una didascalia nella lingua predefinita e, quando esiste un sidecar d'editor, scrive invece in `<image>.facet.xmp`.

**Regioni dei volti.** Con ExifTool, l'esportazione sostituisce solo i rettangoli MWG contrassegnati con `facet:RegionOwner=Facet`.

- Le regioni senza marcatore, incluse quelle delle vecchie versioni di Facet, restano. Dopo l'aggiornamento, un vecchio volto senza marcatore e la sua nuova copia marcata possono comparire entrambi, e cancellare i volti lascia quello vecchio.
- Le esportazioni ripetute sostituiscono le copie marcate; non si accumulano.
- Se le dimensioni dell'immagine differiscono da quelle su cui sono state disegnate le regioni esistenti (o sono sconosciute), le modifiche dei volti vengono saltate con un avviso. Valutazione, etichetta, parole chiave e GPS vengono comunque esportati.
- Metadati dei volti illeggibili o non validi interrompono prima di scrivere l'esportazione o l'incorporamento di una singola foto.
- Lo scrittore di ripiego (senza ExifTool) non esporta rettangoli di volti.
- Una regione marcata che modifichi altrove resta di Facet. Rimuovi il suo marcatore di proprietà per tenerla come tua.

> **Attenzione:** le scritture su file separati non sono atomiche. Un errore di I/O o una modifica esterna durante l'esportazione può lasciare alcuni file aggiornati e altri no.

Se la verifica della versione di ExifTool fallisce, Facet la ripete la volta successiva. Finché la versione è sconosciuta, le regioni dei volti vengono saltate e il resto viene esportato. Le versioni difettose note vengono sempre rifiutate.

## Anteprima di importazione dei sidecar e conflitti di revisione

Esegui `--import-sidecars /path --dry-run` per vedere il piano in JSON prima di scrivere: il sidecar scelto, i campi prima/dopo, le parole chiave da aggiungere, l'orario di origine e i motivi di salto/conflitto. L'anteprima apre il database in sola lettura e non lo modifica mai. L'applicazione rilegge tutto, quindi l'anteprima non è un token da riutilizzare.

Se il database è assente, illeggibile o non valido, l'anteprima termina con codice 1 e non lo crea né lo ripara. `--dry-run-count` limita solo i campioni di scansione, non le anteprime di importazione.

`--sidecar-fields review,gps,keywords` seleziona quali gruppi importare; ometti un gruppo per saltarlo.

- **review** importa insieme stelle, preferito, rifiuto e Conserva, così un conflitto non applica mai metà decisione.
- **gps** conserva le posizioni manuali a meno che non venga indicato `--overwrite-manual-gps`.
- **keywords** sono additive e condivise, anche con `--user`.

**Orologi di modifica.** Facet registra quando ogni campo di revisione è stato modificato l'ultima volta, per foto e account, reset inclusi. Un sidecar più vecchio di quella modifica è un conflitto `newer_local_edit`, e quel gruppo di revisione resta invariato. `--overwrite-sidecar-review` supera questo e il controllo della data di scansione. Un'origine `local` indica un autore sconosciuto, non necessariamente una persona. Didascalie, volti e GPS esterno senza marcatore non vengono mai importati.

- I campi modificati prima che Facet iniziasse a registrare le modifiche non hanno un orario di modifica noto. Si applica la regola della data di scansione, segnalata come `untracked_legacy_edit`.
- L'anteprima apre anche i database più vecchi senza aggiornarli; un campo Conserva mancante viene letto come indeciso.
- L'orario del sidecar è `xmp:MetadataDate`, oppure la data di modifica del file se manca o non è valida.
- I dettagli elencano le prime 1.000 foto nell'ambito e 100 note per foto, con i conteggi di ciò che è stato omesso.

Gli orologi di modifica restano nel proprio database. Una nuova esportazione del viewer non copia orologi di modifica dello scanner né percorsi dei sidecar. Un'esportazione incrementale conserva gli orologi propri del viewer, quindi i reset fatti nel viewer (comprese le valutazioni per utente eliminate) sopravvivono. I valori dello scanner che il viewer non ha mai modificato continuano ad aggiornarsi.

> **Attenzione:** un database del viewer creato da una build non rilasciata precedente alla 1.24.0 può contenere orologi dello scanner copiati. Ora contano come modifiche del viewer, quindi quei campi smettono di seguire gli aggiornamenti dello scanner. Esegui un backup e verifica quel database prima di ricostruirlo: una ricostruzione completa scarta le modifiche locali del viewer.
