# Documentazione di Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · **Italiano** · [Español](../es/README.md) · [Português](../pt/README.md)

Facet è un motore di analisi fotografica multidimensionale: valuta, classifica e seleziona
una libreria fotografica locale, poi serve una galleria per sfogliarla. Inizia da
[Installazione](INSTALLATION.md) — copre ogni configurazione con blocchi copia/incolla.

| Documento | Descrizione |
|----------|-------------|
| [Installazione](INSTALLATION.md) | Configurazione per hardware, con o senza Docker; dipendenze |
| [Comandi](COMMANDS.md) | Riferimento di tutti i comandi CLI |
| [Configurazione](CONFIGURATION.md) | Riferimento completo di `scoring_config.json` |
| [Punteggio](SCORING.md) | Categorie, pesi, guida alla regolazione |
| [Riconoscimento facciale](FACE_RECOGNITION.md) | Flusso di lavoro dei volti, raggruppamento, gestione delle persone |
| [Visualizzatore](VIEWER.md) | Funzionalità e utilizzo della galleria web |
| [Interoperabilità](INTEROP.md) | Scambiare valutazioni/tag con Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Sincronizzare valutazioni e preferiti con Immich, più il webhook in entrata |
| [Distribuzione](DEPLOYMENT.md) | NAS, server remoti, HTTPS, backup, multi-utente |

## Tipi di file supportati

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — richiede `pillow-heif`
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — ignorati se esiste un JPEG/HEIC corrispondente

## Domande comuni

| Problema | Risposta |
|-------|--------|
| Quale profilo dovrei usare? | [Installazione › Quale profilo si adatta al mio hardware?](INSTALLATION.md#quale-profilo-si-adatta-al-mio-hardware) |
| "externally-managed-environment" all'installazione | Usa un ambiente virtuale (o Docker) — vedi [Installazione](INSTALLATION.md) |
| Elaborazione lenta | Verifica il profilo; `--single-pass` aiuta su GPU con molta VRAM |
| Il rilevamento dei volti non usa la GPU | Installa `onnxruntime-gpu` — vedi [Installazione](INSTALLATION.md#onnx-runtime-per-il-rilevamento-dei-volti) |
| exiftool mancante | Opzionale — vedi [Installazione › exiftool](INSTALLATION.md#exiftool) |
