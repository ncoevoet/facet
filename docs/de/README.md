# Facet-Dokumentation

> 🌐 [English](../README.md) · [Français](../fr/README.md) · **Deutsch** · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md)

Facet ist eine mehrdimensionale Fotoanalyse-Engine: Sie bewertet, ordnet und sortiert
eine lokale Fotobibliothek und stellt dann eine Galerie zum Durchstöbern bereit.
Beginnen Sie mit [Installation](INSTALLATION.md) — sie deckt jede Einrichtung mit
Copy-and-paste-Blöcken ab.

| Dokument | Beschreibung |
|----------|-------------|
| [Installation](INSTALLATION.md) | Einrichtung pro Hardware, mit oder ohne Docker; Abhängigkeiten |
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
- **HEIF/HEIC** (.heic, .heif) — erfordert `pillow-heif`
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — übersprungen, wenn ein passendes JPEG/HEIC vorhanden ist

## Häufige Fragen

| Problem | Antwort |
|-------|--------|
| Welches Profil soll ich verwenden? | [Installation › Welches Profil passt zu meiner Hardware?](INSTALLATION.md#welches-profil-passt-zu-meiner-hardware) |
| "externally-managed-environment" bei der Installation | Eine virtuelle Umgebung verwenden (oder Docker) — siehe [Installation](INSTALLATION.md) |
| Langsame Verarbeitung | Das Profil prüfen; `--single-pass` hilft bei GPUs mit viel VRAM |
| Gesichtserkennung nutzt die GPU nicht | `onnxruntime-gpu` installieren — siehe [Installation › ONNX Runtime für die Gesichtserkennung](INSTALLATION.md#onnx-runtime-für-die-gesichtserkennung) |
| Fehlendes exiftool | Optional — siehe [Installation › exiftool](INSTALLATION.md#exiftool) |
