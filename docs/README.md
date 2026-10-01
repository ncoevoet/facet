# Facet documentation

> 🌐 **English** · [Français](fr/README.md) · [Deutsch](de/README.md) · [Italiano](it/README.md) · [Español](es/README.md) · [Português](pt/README.md) · [简体中文](zh/README.md)

Facet is a multi-dimensional photo analysis engine: it scores, ranks and culls a local
photo library, then serves a gallery to browse it. Start with
[Installation](INSTALLATION.md) — it covers every setup in copy/paste blocks.

| Document | Description |
|----------|-------------|
| [Installation](INSTALLATION.md) | Setup per hardware, with or without Docker; dependencies |
| [Getting Started](GETTING_STARTED.md) | First-run walkthrough: install to scan, review, teach, discard, tag and export |
| [Commands](COMMANDS.md) | All CLI commands reference |
| [Configuration](CONFIGURATION.md) | Full `scoring_config.json` reference |
| [Scoring](SCORING.md) | Categories, weights, tuning guide |
| [Face Recognition](FACE_RECOGNITION.md) | Face workflow, clustering, person management |
| [Viewer](VIEWER.md) | Web gallery features and usage |
| [Interop](INTEROP.md) | Round-tripping ratings/tags with Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Syncing ratings and favorites with Immich, plus the inbound webhook |
| [Deployment](DEPLOYMENT.md) | NAS, remote servers, HTTPS, backups, multi-user |

## Supported file types

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — requires `pillow-heif`; Canon HDR PQ `.HIF` stills are tone-mapped to SDR sRGB
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — skipped when a matching JPEG/HEIC exists
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — 16-bit greyscale is scaled to 8-bit, an alpha channel is composited over white, and animated GIF/WebP score the first frame; TIFF is converted to JPEG for the browser. PNG, WebP and TIFF carry EXIF when the writer stored it; GIF and BMP cannot, so `date_taken` and camera/lens stay empty for those two
- **AVIF** (.avif) — requires a Pillow built with AVIF support (native from `pillow>=11.3`); HDR PQ AVIF stills are tone-mapped to SDR sRGB, the same treatment Canon `.HIF` gets; EXIF is read when present

## Common questions

| Issue | Answer |
|-------|--------|
| Which profile should I use? | [Installation › Which profile fits my hardware?](INSTALLATION.md#which-profile-fits-my-hardware) |
| "externally-managed-environment" on install | Use a virtual environment (or Docker) — see [Installation](INSTALLATION.md) |
| Slow processing | Check the profile; `--single-pass` helps on high-VRAM GPUs |
| Face detection not using the GPU | Install `onnxruntime-gpu` — see [Installation](INSTALLATION.md#onnx-runtime-for-face-detection) |
| Missing exiftool | Optional — see [Installation › exiftool](INSTALLATION.md#exiftool) |
