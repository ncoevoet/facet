# Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · [Deutsch](../de/README.md) · **Italiano** · [Español](../es/README.md) · [Português](../pt/README.md)

Valutazione della qualità delle foto che analizza le immagini utilizzando CLIP, TOPIQ, SAMP-Net, InsightFace e OpenCV per valutare le foto in termini di estetica, qualità dei volti, nitidezza tecnica, colore, esposizione e composizione.

## Funzionalità

- **Punteggio multi-modello** - valutazione estetica con TOPIQ (0.93 SRCC) o CLIP+MLP, con profili VRAM configurabili
- **Tagging semantico** - tag generati automaticamente tramite CLIP (paesaggio, ritratto, tramonto, ecc.)
- **Riconoscimento facciale** - rilevamento, punteggio di qualità, rilevamento di occhi chiusi e raggruppamento di persone tramite HDBSCAN
- **Analisi della composizione** - SAMP-Net (14 modelli) o punteggio basato su regole
- **Analisi tecnica** - nitidezza, colore, esposizione, gamma dinamica, rumore, contrasto
- **Sistema di categorie** - oltre 30 categorie di contenuto con pesi di punteggio specifici per categoria
- **Galleria web** - SPA FastAPI + Angular con filtri, ordinamento, riconoscimento facciale e confronto a coppie
- **Elaborazione in batch** - batching GPU a flusso continuo con dimensioni di batch regolate automaticamente

## Avvio rapido

```bash
# Installa le dipendenze
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Valuta le foto
python facet.py /path/to/photos

# Visualizza i risultati
python viewer.py
# Apri http://localhost:5000
```

## Documentazione

| Documento | Descrizione |
|----------|-------------|
| [Installazione](INSTALLATION.md) | Requisiti, configurazione GPU, dipendenze |
| [Comandi](COMMANDS.md) | Riferimento di tutti i comandi CLI |
| [Configurazione](CONFIGURATION.md) | Riferimento completo di `scoring_config.json` |
| [Punteggio](SCORING.md) | Categorie, pesi, guida alla regolazione |
| [Riconoscimento facciale](FACE_RECOGNITION.md) | Flusso di lavoro dei volti, raggruppamento, gestione delle persone |
| [Visualizzatore](VIEWER.md) | Funzionalità e utilizzo della galleria web |

## Profili VRAM

| Profilo | VRAM GPU | Modelli | Ideale per |
|---------|----------|--------|----------|
| `legacy` | Nessuna GPU | CLIP+MLP + SAMP-Net + tagging CLIP (CPU) | Nessuna GPU, 8GB+ di RAM |
| `8gb` | 6-14GB | CLIP+MLP + SAMP-Net + tagging CLIP | GPU di fascia media |
| `16gb` | 16GB+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Migliore accuratezza estetica |
| `24gb` | 24GB+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Migliore accuratezza + spiegazioni della composizione |

## Tipi di file supportati

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — richiede `pillow-heif`
- **File RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) - ignorati se esiste un JPEG/HEIC corrispondente

## Risoluzione dei problemi

| Problema | Soluzione |
|-------|----------|
| "externally-managed-environment" | Usa un ambiente virtuale |
| Elaborazione lenta | Verifica il profilo VRAM, usa `--single-pass` per GPU con molta VRAM |
| Il rilevamento dei volti non usa la GPU | Installa `onnxruntime-gpu` |
| exiftool mancante | Opzionale — installalo tramite il gestore di pacchetti del sistema per risultati ottimali, altrimenti `exifread` gestisce tutti i formati RAW |

Consulta [Installazione](INSTALLATION.md) per istruzioni dettagliate sulla configurazione.
