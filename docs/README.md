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
| [API](API.md) | Viewer HTTP API reference |
| [Interop](INTEROP.md) | Round-tripping ratings/tags with Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Syncing ratings and favorites with Immich, plus the inbound webhook |
| [Deployment](DEPLOYMENT.md) | NAS, remote servers, HTTPS, backups, multi-user |
| [Relink](RELINK.md) | Relink moved photos |

## Supported file types

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — requires `pillow-heif`; Canon HDR PQ `.HIF` stills are tone-mapped to SDR sRGB
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — skipped when a matching JPEG/HEIC exists. A RAW that LibRaw can't decode (a Lightroom `-HDR.dng` / `-Pano.dng` merge, or a camera newer than LibRaw) is scored from its largest embedded preview via `exiftool`; the preview must be at least 1024 px on the long edge. Lightroom Classic 13+ stores that preview as JPEG XL, which Facet decodes directly
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — 16-bit greyscale is scaled to 8-bit, an alpha channel is composited over white, and animated GIF/WebP score the first frame. TIFF is converted to JPEG for the browser. PNG, WebP and TIFF carry EXIF when the writer stored it; GIF and BMP cannot, so `date_taken` and camera/lens stay empty for them
- **AVIF** (.avif) — requires a Pillow built with AVIF support (native from `pillow>=11.3`); HDR PQ stills are tone-mapped to SDR sRGB; EXIF is read when present
- **JPEG XL** (.jxl) — works out of the box through the core `imagecodecs` dependency, Docker included. HDR is not tone-mapped, animated files score the first frame, and valid EXIF is read when present. Reconstructed JPEGs keep ICC color management; native JXL color profiles are not available

## Common questions

| Issue | Answer |
|-------|--------|
| Which profile should I use? | [Installation › Which profile fits my hardware?](INSTALLATION.md#which-profile-fits-my-hardware) |
| "externally-managed-environment" on install | Use a virtual environment (or Docker) — see [Installation](INSTALLATION.md) |
| Slow processing | Check the profile. `--single-pass` can help on the `legacy`/`8gb` profiles with plenty of VRAM; `12gb`/`16gb`/`24gb` always run multi-pass (except in commercial mode) |
| Face detection not using the GPU | Run `python facet.py --doctor` (ONNX Runtime section), then install `onnxruntime-gpu` in place of `onnxruntime`, never beside it — see [Installation](INSTALLATION.md#onnx-runtime-for-face-detection) |
| Missing exiftool | Optional — see [Installation › exiftool](INSTALLATION.md#exiftool) |
