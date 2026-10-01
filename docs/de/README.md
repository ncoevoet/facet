# Facet-Dokumentation

> 🌐 [English](../README.md) · [Français](../fr/README.md) · **Deutsch** · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md) · [简体中文](../zh/README.md)

Facet ist eine mehrdimensionale Fotoanalyse-Engine: Sie bewertet, ordnet und sortiert
eine lokale Fotobibliothek und stellt dann eine Galerie zum Durchstöbern bereit.
Beginnen Sie mit [Installation](INSTALLATION.md) — sie deckt jede Einrichtung mit
Copy-and-paste-Blöcken ab.

| Dokument | Beschreibung |
|----------|-------------|
| [Installation](INSTALLATION.md) | Einrichtung pro Hardware, mit oder ohne Docker; Abhängigkeiten |
| [Erste Schritte](GETTING_STARTED.md) | Walkthrough für den ersten Start: von der Installation bis zu Scan, Sichtung, Training, Aussortieren, Tagging und Export |
| [Befehle](COMMANDS.md) | Referenz aller CLI-Befehle |
| [Konfiguration](CONFIGURATION.md) | Vollständige `scoring_config.json`-Referenz |
| [Bewertung](SCORING.md) | Kategorien, Gewichte, Tuning-Anleitung |
| [Gesichtserkennung](FACE_RECOGNITION.md) | Gesichts-Workflow, Clustering, Personenverwaltung |
| [Viewer](VIEWER.md) | Funktionen und Nutzung der Web-Galerie |
| [Interop](INTEROP.md) | Bewertungen/Tags mit Lightroom, Capture One, digiKam, darktable austauschen |
| [Immich](IMMICH.md) | Bewertungen und Favoriten mit Immich synchronisieren, plus der eingehende Webhook |
| [Bereitstellung](DEPLOYMENT.md) | NAS, entfernte Server, HTTPS, Backups, Mehrbenutzerbetrieb |

## Unterstützte Dateitypen

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — erfordert `pillow-heif`; Canon-HDR-PQ-`.HIF`-Aufnahmen werden auf SDR-sRGB tone-gemappt
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — übersprungen, wenn ein passendes JPEG/HEIC vorhanden ist
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — 16-Bit-Graustufen werden auf 8 Bit skaliert, ein Alphakanal wird auf Weiß compositet, und animierte GIF/WebP werden anhand des ersten Frames bewertet; TIFF wird für den Browser in JPEG umgewandelt. PNG, WebP und TIFF enthalten EXIF, sofern das schreibende Programm es gespeichert hat; GIF und BMP können das nicht, daher bleiben bei diesen beiden `date_taken` sowie Kamera/Objektiv leer
- **AVIF** (.avif) — erfordert ein Pillow, das mit AVIF-Unterstützung gebaut wurde (nativ ab `pillow>=11.3`); HDR-PQ-AVIF-Aufnahmen werden wie Canon-`.HIF` auf SDR-sRGB tone-gemappt; EXIF wird gelesen, wenn es vorhanden ist

## Häufige Fragen

| Problem | Antwort |
|-------|--------|
| Welches Profil soll ich verwenden? | [Installation › Welches Profil passt zu meiner Hardware?](INSTALLATION.md#welches-profil-passt-zu-meiner-hardware) |
| "externally-managed-environment" bei der Installation | Eine virtuelle Umgebung verwenden (oder Docker) — siehe [Installation](INSTALLATION.md) |
| Langsame Verarbeitung | Das Profil prüfen; `--single-pass` hilft bei GPUs mit viel VRAM |
| Gesichtserkennung nutzt die GPU nicht | `onnxruntime-gpu` installieren — siehe [Installation › ONNX Runtime für die Gesichtserkennung](INSTALLATION.md#onnx-runtime-für-die-gesichtserkennung) |
| Fehlendes exiftool | Optional — siehe [Installation › exiftool](INSTALLATION.md#exiftool) |
