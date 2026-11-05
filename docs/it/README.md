# Documentazione di Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · **Italiano** · [Español](../es/README.md) · [Português](../pt/README.md) · [简体中文](../zh/README.md)

Facet è un motore di analisi fotografica multidimensionale: valuta, classifica e seleziona
una libreria fotografica locale, poi serve una galleria per sfogliarla. Inizia da
[Installazione](INSTALLATION.md) — copre ogni configurazione con blocchi copia/incolla.

| Documento | Descrizione |
|----------|-------------|
| [Installazione](INSTALLATION.md) | Configurazione per hardware, con o senza Docker; dipendenze |
| [Per iniziare](GETTING_STARTED.md) | Percorso del primo avvio: dall'installazione a scansione, revisione, addestramento, scarto, tag ed esportazione |
| [Comandi](COMMANDS.md) | Riferimento di tutti i comandi CLI |
| [Configurazione](CONFIGURATION.md) | Riferimento completo di `scoring_config.json` |
| [Punteggio](SCORING.md) | Categorie, pesi, guida alla regolazione |
| [Riconoscimento facciale](FACE_RECOGNITION.md) | Flusso di lavoro dei volti, raggruppamento, gestione delle persone |
| [Visualizzatore](VIEWER.md) | Funzionalità e utilizzo della galleria web |
| [API](../API.md) | Riferimento dell'API HTTP del visualizzatore |
| [Interoperabilità](INTEROP.md) | Scambiare valutazioni/tag con Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizzare valutazioni e preferiti con Immich, più il webhook in entrata |
| [Distribuzione](DEPLOYMENT.md) | NAS, server remoti, HTTPS, backup, multi-utente |
| [Ricollegare](RELINK.md) | Ricollegare foto spostate |

## Tipi di file supportati

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — richiede `pillow-heif`; gli scatti `.HIF` Canon HDR PQ sono sottoposti a tone mapping in sRGB SDR
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — ignorati se esiste un JPEG/HEIC corrispondente. Un RAW che LibRaw non riesce a decodificare (un'unione `-HDR.dng` / `-Pano.dng` di Lightroom, o una fotocamera più recente di LibRaw) viene valutato dalla sua anteprima incorporata più grande tramite `exiftool`; l'anteprima deve misurare almeno 1024 px sul lato lungo. Lightroom Classic 13+ salva quell'anteprima come JPEG XL, che Facet decodifica direttamente
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — la scala di grigi a 16 bit viene scalata a 8 bit, un canale alfa viene composito su sfondo bianco, e i GIF/WebP animati vengono valutati sul primo fotogramma; il TIFF viene convertito in JPEG per il browser. PNG, WebP e TIFF contengono l'EXIF quando il programma che li ha scritti lo ha salvato; GIF e BMP non possono, quindi per questi due `date_taken` e fotocamera/obiettivo restano vuoti
- **AVIF** (.avif) — richiede un Pillow compilato con il supporto AVIF (nativo a partire da `pillow>=11.3`); gli scatti AVIF HDR PQ vengono sottoposti a tone mapping in sRGB SDR, come i `.HIF` Canon; l'EXIF viene letto quando è presente
- **JPEG XL** (.jxl) — funziona subito tramite la dipendenza di base `imagecodecs`, Docker incluso. L'HDR non è sottoposto a tone mapping, i file animati vengono valutati sul primo fotogramma e l'EXIF valido viene letto quando è presente. I JPEG ricostruiti mantengono la gestione del colore ICC; i profili colore JXL nativi non sono disponibili

## Domande comuni

| Problema | Risposta |
|-------|--------|
| Quale profilo dovrei usare? | [Installazione › Quale profilo si adatta al mio hardware?](INSTALLATION.md#quale-profilo-si-adatta-al-mio-hardware) |
| "externally-managed-environment" all'installazione | Usa un ambiente virtuale (o Docker) — vedi [Installazione](INSTALLATION.md) |
| Elaborazione lenta | Verifica il profilo. `--single-pass` può aiutare sui profili `legacy`/`8gb` con molta VRAM; `12gb`/`16gb`/`24gb` eseguono sempre il multi-pass (tranne in modalità commerciale) |
| Il rilevamento dei volti non usa la GPU | Esegui `python facet.py --doctor` (sezione ONNX Runtime), poi installa `onnxruntime-gpu` al posto di `onnxruntime`, mai accanto — vedi [Installazione](INSTALLATION.md#onnx-runtime-per-il-rilevamento-dei-volti) |
| exiftool mancante | Opzionale — vedi [Installazione › exiftool](INSTALLATION.md#exiftool) |
