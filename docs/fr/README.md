# Documentation Facet

> 🌐 [English](../README.md) · **Français** · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md) · [Português](../pt/README.md) · [简体中文](../zh/README.md)

Facet est un moteur d'analyse photo multi-dimensionnel : il évalue, classe et trie une
bibliothèque de photos locale, puis sert une galerie pour la parcourir. Commencez par
[Installation](INSTALLATION.md) — elle couvre chaque configuration avec des blocs à
copier-coller.

| Document | Description |
|----------|-------------|
| [Installation](INSTALLATION.md) | Configuration par matériel, avec ou sans Docker ; dépendances |
| [Prise en main](GETTING_STARTED.md) | Parcours de premier lancement : de l'installation à l'analyse, au tri, à l'apprentissage, à l'écartement, au tagging et à l'export |
| [Commandes](COMMANDS.md) | Référence de toutes les commandes CLI |
| [Configuration](CONFIGURATION.md) | Référence complète de `scoring_config.json` |
| [Évaluation](SCORING.md) | Catégories, poids, guide de réglage |
| [Reconnaissance faciale](FACE_RECOGNITION.md) | Flux des visages, regroupement, gestion des personnes |
| [Visualiseur](VIEWER.md) | Fonctionnalités et utilisation de la galerie web |
| [API](../API.md) | Référence de l'API HTTP du visualiseur |
| [Interopérabilité](INTEROP.md) | Faire circuler notes/tags avec Lightroom, Capture One, digiKam, darktable |
| [Immich](IMMICH.md) | Synchroniser notes et favoris avec Immich, plus le webhook entrant |
| [Déploiement](DEPLOYMENT.md) | NAS, serveurs distants, HTTPS, sauvegardes, multi-utilisateur |
| [Relier](RELINK.md) | Relier une photo déplacée |

## Types de fichiers pris en charge

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC/HIF** (.heic, .heif, .hif) — nécessite `pillow-heif` ; les images `.HIF` Canon HDR PQ sont tonemappées en sRGB SDR
- **RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) — ignoré lorsqu'un JPEG/HEIC correspondant existe. Un RAW que LibRaw ne sait pas décoder (une fusion Lightroom `-HDR.dng` / `-Pano.dng`, ou un boîtier plus récent que LibRaw) est évalué à partir de son plus grand aperçu intégré via `exiftool` ; l'aperçu doit mesurer au moins 1024 px sur le grand côté. Lightroom Classic 13+ stocke cet aperçu en JPEG XL, que Facet décode directement
- **PNG, GIF, WebP, BMP, TIFF** (.png, .gif, .webp, .bmp, .tif, .tiff) — les niveaux de gris 16 bits sont mis à l'échelle en 8 bits, un canal alpha est composé sur fond blanc, et les GIF/WebP animés sont évalués sur leur première image. Le TIFF est converti en JPEG pour le navigateur. Le PNG, le WebP et le TIFF contiennent l'EXIF quand le logiciel d'écriture l'a enregistré ; le GIF et le BMP ne le peuvent pas, donc pour eux `date_taken` et l'appareil/objectif restent vides
- **AVIF** (.avif) — nécessite un Pillow compilé avec la prise en charge AVIF (native à partir de `pillow>=11.3`) ; les images HDR PQ sont tonemappées en sRGB SDR ; l'EXIF est lu quand il est présent
- **JPEG XL** (.jxl) — fonctionne directement grâce à la dépendance principale `imagecodecs`, Docker compris. Le HDR n'est pas tonemappé, les fichiers animés sont évalués sur leur première image, et l'EXIF valide est lu quand il est présent. Les JPEG reconstruits conservent la gestion ICC ; les profils colorimétriques JXL natifs ne sont pas disponibles

## Questions fréquentes

| Problème | Réponse |
|-------|--------|
| Quel profil dois-je utiliser ? | [Installation › Quel profil correspond à mon matériel ?](INSTALLATION.md#quel-profil-correspond-à-mon-matériel) |
| « externally-managed-environment » à l'installation | Utilisez un environnement virtuel (ou Docker) — voir [Installation](INSTALLATION.md) |
| Traitement lent | Vérifiez le profil ; `--single-pass` peut aider sur les profils `legacy`/`8gb` avec beaucoup de VRAM (hors mode commercial, `12gb`/`16gb`/`24gb` exécutent toujours le multi-pass) |
| La détection de visages n'utilise pas le GPU | Lancez `python facet.py --doctor` (section ONNX Runtime), puis installez `onnxruntime-gpu` à la place de `onnxruntime`, jamais à côté — voir [Installation](INSTALLATION.md#onnx-runtime-pour-la-détection-de-visages) |
| exiftool manquant | Optionnel — voir [Installation › exiftool](INSTALLATION.md#exiftool) |
