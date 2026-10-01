# Per iniziare

> 🌐 [English](../GETTING_STARTED.md) · [Français](../fr/GETTING_STARTED.md) · [Deutsch](../de/GETTING_STARTED.md) · **Italiano** · [Español](../es/GETTING_STARTED.md) · [Português](../pt/GETTING_STARTED.md) · [简体中文](../zh/GETTING_STARTED.md)

Una guida per la prima sessione, per il lavoro più comune: hai appena scattato o importato un
gruppo di foto e vuoi ottenere un insieme curato. Segue sei passaggi — importare, raggruppare
le foto simili, insegnare a Facet i tuoi gusti, scartare, taggare, esportare — e rimanda alla
pagina che spiega ciascuno invece di ripeterlo.

![Percorso guidato della galleria Facet](../screenshots/walkthrough.gif)

## Prima di iniziare

### 1. Imposta una password di edizione

Una nuova installazione è in **sola lettura**. Puoi sfogliare (soggetto a `viewer.password`,
se ne hai impostata una), ma ogni modifica — valutazioni, selezione, volti, album, tag e il
pulsante di scansione — viene rifiutata finché non imposti `viewer.edition_password` in
`scoring_config.json` e riavvii il viewer (la configurazione non viene ricaricata a caldo).

Con il `docker-compose.yml` incluso non devi inventarne una: l'immagine genera una password
al primo avvio e la stampa una sola volta. Leggila con:

```bash
docker compose logs facet
```

Poi accedi come editor dalla galleria. Dettagli: [Modalità utente singolo](VIEWER.md#modalità-utente-singolo-predefinita) e [Impostazioni Docker che puoi modificare](INSTALLATION.md#impostazioni-docker-che-puoi-modificare).

![Accesso come editor](../screenshots/getting-started-edition-login.jpg)

### 2. Scegli un metodo di installazione

Docker è la via più breve su Windows, macOS e Linux; l'installazione nativa è per chi
preferisce non usare i container. [Quale installazione fa per me?](INSTALLATION.md#quale-installazione-fa-per-me)
contiene la tabella.

Due cose mettono in difficoltà con i container:

- **Configurazione e proprietà dei file.** Il container gira come uid 1000, che Podman
  rootless mappa su un subuid dell'host, quindi i file che crea in `./facet-config` potrebbero
  non appartenere al tuo utente. Vedi
  [Proprietà del file nel container](INSTALLATION.md#proprietà-del-file-nel-container).
- **I percorsi sono quelli del container, non dell'host.** Scansioni `/data/photos`, non
  `~/Pictures`. Vedi [Semantica dei percorsi nel container](DEPLOYMENT.md#semantica-dei-percorsi-nel-container).

### 3. Nessuna GPU? Nessun problema

Tutto — punteggi, volti, tag, selezione, il pulsante di scansione — funziona su un processore
con il profilo CPU `legacy`; è solo più lento. Leggi
[Nessuna scheda grafica](INSTALLATION.md#nessuna-scheda-grafica) e
[Quale profilo si adatta al mio hardware?](INSTALLATION.md#quale-profilo-si-adatta-al-mio-hardware). Una scheda
non è mai una condizione perché il pulsante di scansione compaia.

### 4. Attenzione alla memoria

Un container con un limite di memoria può essere terminato a metà scansione sui profili più
grandi. Consulta
[Limiti di memoria del container](DEPLOYMENT.md#limiti-di-memoria-del-container) prima di impostarne uno; su un
Mac vedi [Memoria su un Mac](INSTALLATION.md#memoria-su-un-mac).

## Il flusso di lavoro

### Passaggio 1: importare le immagini

Metti le tue foto nella cartella a cui punta Facet (JPEG, HEIF/HEIC, PNG e i formati RAW più
comuni — vedi [tipi di file supportati](README.md#tipi-di-file-supportati)) e scansionala. Puoi
farlo dal terminale ([Scansione](COMMANDS.md#scansione)) o dal browser:

- Imposta `viewer.features.show_scan_button` su `true` (di serie è disattivato).
- Utente singolo: serve una password di edizione **e** aver effettuato l'accesso come editor.
  Multiutente: serve il ruolo superadmin.
- Aggiungi la cartella a `viewer.scan_directories` così l'avvio ha qualcosa da proporre.

Un pulsante **Scansiona nuove foto** compare allora sopra la griglia della galleria a ogni
larghezza dello schermo, non solo nella galleria vuota. Regole complete: [Avvio scansione](VIEWER.md#avvio-scansione). La prima
scansione scarica i modelli di IA una sola volta ([Primo avvio](INSTALLATION.md#primo-avvio-cosa-aspettarsi)).

![Pulsante di scansione sopra la galleria](../screenshots/getting-started-scan-button.jpg)

### Passaggio 2: trovare duplicati, raffiche e foto simili

Facet raggruppa da solo i fotogrammi di raffica, i quasi-duplicati, i bracket di esposizione e
i panorami, e la galleria **nasconde per impostazione predefinita la maggior parte di un
gruppo** così vedi un solo rappresentante. Se il numero di foto ti sembra inferiore al
previsto, sono gli interruttori di occultamento, non file mancanti — vedi
[Opzioni di visualizzazione](VIEWER.md#opzioni-di-visualizzazione) e [Filtri predefiniti](VIEWER.md#filtri-predefiniti).
Per vedere un intero gruppo affiancato, apri [Foto simili](VIEWER.md#foto-simili) o la camera
oscura di [Selezione](VIEWER.md#selezione); i gruppi che devono restare interi sono descritti in
[Panorami e bracket di esposizione](VIEWER.md#panorami-e-bracket-di-esposizione).

![Selezione delle raffiche](../screenshots/burst-culling.jpg)

### Passaggio 3: insegnare a Facet quale preferisci

Ogni scelta che fai durante la selezione, e ogni scelta A/B nella modalità di confronto, è un
segnale. Facet ne ricava una classifica personale e la espone come **I miei gusti**
([I miei gusti](VIEWER.md#i-miei-gusti)). Scegli «questa batte quella» nella
[Modalità di confronto a coppie](VIEWER.md#modalità-di-confronto-a-coppie), oppure semplicemente seleziona — la schermata
[Selezione](VIEWER.md#selezione) registra ciò che tieni e ciò che scarti. Il ranker si riaddestra
da solo dopo un numero sufficiente di nuove scelte, e solo quando ti fermi
([Riaddestramento automatico](CONFIGURATION.md#riaddestramento-automatico)).

![Confronto tra due foto](../screenshots/getting-started-teach.jpg)

### Passaggio 4: scartare ciò che non vuoi

Rifiuta le foto durante la selezione, oppure seleziona un gruppo e agisci su di esso
([Selezione multipla e azioni di gruppo](VIEWER.md#selezione-multipla-e-azioni-di-gruppo)):
[Tieni il top N%](VIEWER.md#tieni-il-top-n), [Scarta in cartella](VIEWER.md#scarta-in-cartella) o
[Elimina](VIEWER.md#elimina). Scarta in cartella mostra un'anteprima come prova a secco finché non
la applichi. Elimina invia subito i file al cestino del sistema, e solo se
`viewer.cull.allow_trash` è attivo (di serie è `false`).
[Annulla](VIEWER.md#annulla) copre le modifiche ai flag in blocco e le conferme della selezione, non queste operazioni
sui file. Le cartelle in cui una selezione può scrivere sono una lista consentita: le tue
cartelle di scansione più `viewer.export.allowed_target_dirs`, quindi una sottocartella
dell'albero delle foto funziona senza configurazione, mentre una cartella esterna viene
rifiutata finché non la aggiungi. Vedi
[Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto). Per
selezionare da terminale: [Selezionare uno shooting da terminale](COMMANDS.md#selezionare-uno-shooting-da-terminale).

Le foto che elimini fuori da Facet lasciano la loro riga nel database finché non esegui la pulizia in
[Manutenzione del database](COMMANDS.md#manutenzione-del-database).

![Azioni di gruppo su una selezione](../screenshots/getting-started-discard.jpg)

### Passaggio 5: aggiungere tag e metadati alle foto tenute

Facet tagga le foto automaticamente, e puoi aggiungere anche **i tuoi tag**: nella vista di
dettaglio della foto per una singola foto, o dalle azioni di gruppo per una selezione. I tag
manuali sopravvivono alle riscansioni, il filtro per tag e la ricerca li trovano, e sono
nascosti nei link di condivisione. Le parole chiave dei sidecar XMP esterni vengono importate
come tag manuali; rimuovere un tag in Facet non lo rimuove dai sidecar che Facet ha già
scritto. Vedi [Tag manuali](VIEWER.md#tag-manuali) e
[Tag manuali e parole chiave XMP](INTEROP.md#tag-manuali-e-parole-chiave-xmp). Per portare valutazioni
e parole chiave in Lightroom, Capture One, digiKam o darktable, vedi [Interoperabilità](INTEROP.md)
(serve [exiftool](INSTALLATION.md#exiftool) per l'incorporamento).

![Finestra dei tag manuali](../screenshots/getting-started-manual-tags.jpg)

### Passaggio 6: esportare l'insieme curato

Metti le foto tenute in un album ed esporta da lì, oppure usa
[Esportazione per editor](VIEWER.md#esportazione-per-editor) per passare il lavoro a un editor, o
[Scarta in cartella](VIEWER.md#scarta-in-cartella) per copiare le foto tenute in una cartella. Vale la
stessa lista consentita di destinazioni del passaggio 4
([Destinazioni di esportazione e scarto](CONFIGURATION.md#destinazioni-di-esportazione-e-scarto)).

![Esportazione di un album](../screenshots/getting-started-export.jpg)

## Come proseguire

[Viewer](VIEWER.md) per ogni funzionalità della galleria, [Comandi](COMMANDS.md) per il terminale,
[Punteggi](SCORING.md) per regolare ciò che rende buona una foto, e
[Deployment](DEPLOYMENT.md) per un NAS o un server condiviso.
