# Facet

> 🌐 [English](../README.md) · [Français](../fr/README.md) · **Deutsch** · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md)

Fotoqualitätsbewertung, die Bilder mit CLIP, TOPIQ, SAMP-Net, InsightFace und OpenCV analysiert, um Fotos hinsichtlich Ästhetik, Gesichtsqualität, technischer Schärfe, Farbe, Belichtung und Komposition zu bewerten.

## Funktionen

- **Multi-Modell-Bewertung** – TOPIQ (0,93 SRCC) oder ästhetische Bewertung mit CLIP+MLP, mit konfigurierbaren VRAM-Profilen
- **Semantisches Tagging** – automatisch generierte Tags mit CLIP (landscape, portrait, sunset usw.)
- **Gesichtserkennung** – Erkennung, Qualitätsbewertung, Blinzeln-Erkennung und Personenclustering über HDBSCAN
- **Kompositionsanalyse** – SAMP-Net (14 Muster) oder regelbasierte Bewertung
- **Technische Analyse** – Schärfe, Farbe, Belichtung, Dynamikumfang, Rauschen, Kontrast
- **Kategoriesystem** – mehr als 30 Inhaltskategorien mit kategoriespezifischen Bewertungsgewichten
- **Web-Galerie** – FastAPI + Angular-SPA mit Filterung, Sortierung, Gesichtserkennung und paarweisem Vergleich
- **Stapelverarbeitung** – kontinuierlich streamendes GPU-Batching mit automatisch abgestimmten Batchgrößen

## Schnellstart

```bash
# Abhängigkeiten installieren
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Fotos bewerten
python facet.py /path/to/photos

# Ergebnisse ansehen
python viewer.py
# http://localhost:5000 öffnen
```

## Dokumentation

| Dokument | Beschreibung |
|----------|-------------|
| [Installation](INSTALLATION.md) | Anforderungen, GPU-Einrichtung, Abhängigkeiten |
| [Befehle](COMMANDS.md) | Referenz aller CLI-Befehle |
| [Konfiguration](CONFIGURATION.md) | Vollständige `scoring_config.json`-Referenz |
| [Bewertung](SCORING.md) | Kategorien, Gewichte, Tuning-Anleitung |
| [Gesichtserkennung](FACE_RECOGNITION.md) | Gesichts-Workflow, Clustering, Personenverwaltung |
| [Viewer](VIEWER.md) | Funktionen und Nutzung der Web-Galerie |
| [Interop](INTEROP.md) | Bewertungen/Tags mit Lightroom, Capture One, digiKam, darktable austauschen |

## VRAM-Profile

| Profil | GPU-VRAM | Modelle | Am besten für |
|---------|----------|--------|----------|
| `legacy` | Keine GPU | CLIP+MLP + SAMP-Net + CLIP-Tagging (CPU) | Keine GPU, 8 GB+ RAM |
| `8gb` | 6–14 GB | CLIP+MLP + SAMP-Net + CLIP-Tagging | Mittelklasse-GPUs |
| `16gb` | 16 GB+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Beste ästhetische Genauigkeit |
| `24gb` | 24 GB+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Beste Genauigkeit + Kompositionserklärungen |

## Unterstützte Dateitypen

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — erfordert `pillow-heif`
- **RAW-Dateien** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) – übersprungen, wenn ein passendes JPEG/HEIC vorhanden ist

## Fehlerbehebung

| Problem | Lösung |
|-------|----------|
| "externally-managed-environment" | Virtuelle Umgebung verwenden |
| Langsame Verarbeitung | VRAM-Profil prüfen, `--single-pass` für GPUs mit viel VRAM verwenden |
| Gesichtserkennung nutzt die GPU nicht | `onnxruntime-gpu` installieren |
| Fehlendes exiftool | Optional — über den System-Paketmanager für beste Ergebnisse installieren, andernfalls verarbeitet `exifread` alle RAW-Formate |

Siehe [Installation](INSTALLATION.md) für detaillierte Einrichtungsanweisungen.
