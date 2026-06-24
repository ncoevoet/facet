# Facet

> 🌐 [English](../README.md) · **Français** · [Deutsch](../de/README.md) · [Italiano](../it/README.md) · [Español](../es/README.md)

Évaluation de la qualité des photos qui analyse les images à l'aide de CLIP, TOPIQ, SAMP-Net, InsightFace et OpenCV pour noter les photos sur l'esthétique, la qualité des visages, la netteté technique, la couleur, l'exposition et la composition.

## Fonctionnalités

- **Notation multi-modèles** - évaluation esthétique TOPIQ (0,93 SRCC) ou CLIP+MLP, avec des profils VRAM configurables
- **Étiquetage sémantique** - tags générés automatiquement à l'aide de CLIP (paysage, portrait, coucher de soleil, etc.)
- **Reconnaissance faciale** - détection, notation de la qualité, détection des clignements et regroupement des personnes via HDBSCAN
- **Analyse de la composition** - SAMP-Net (14 motifs) ou notation basée sur des règles
- **Analyse technique** - netteté, couleur, exposition, plage dynamique, bruit, contraste
- **Système de catégories** - plus de 30 catégories de contenu avec des poids de notation spécifiques à chaque catégorie
- **Galerie web** - SPA FastAPI + Angular avec filtrage, tri, reconnaissance faciale et comparaison par paires
- **Traitement par lots** - traitement GPU en flux continu avec des tailles de lot auto-ajustées

## Démarrage rapide

```bash
# Installer les dépendances
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Noter les photos
python facet.py /path/to/photos

# Afficher les résultats
python viewer.py
# Ouvrir http://localhost:5000
```

## Documentation

| Document | Description |
|----------|-------------|
| [Installation](INSTALLATION.md) | Prérequis, configuration GPU, dépendances |
| [Commandes](COMMANDS.md) | Référence de toutes les commandes CLI |
| [Configuration](CONFIGURATION.md) | Référence complète de `scoring_config.json` |
| [Notation](SCORING.md) | Catégories, poids, guide de réglage |
| [Reconnaissance faciale](FACE_RECOGNITION.md) | Workflow des visages, regroupement, gestion des personnes |
| [Galerie web](VIEWER.md) | Fonctionnalités et utilisation de la galerie web |

## Profils VRAM

| Profil | VRAM GPU | Modèles | Idéal pour |
|---------|----------|--------|----------|
| `legacy` | Pas de GPU | CLIP+MLP + SAMP-Net + étiquetage CLIP (CPU) | Pas de GPU, 8 Go+ de RAM |
| `8gb` | 6-14 Go | CLIP+MLP + SAMP-Net + étiquetage CLIP | GPU de milieu de gamme |
| `16gb` | 16 Go+ | TOPIQ + SAMP-Net + Qwen3.5-2B | Meilleure précision esthétique |
| `24gb` | 24 Go+ | TOPIQ + Qwen2-VL + Qwen3.5-4B | Meilleure précision + explications de composition |

## Types de fichiers pris en charge

- **JPEG** (.jpg, .jpeg)
- **HEIF/HEIC** (.heic, .heif) — nécessite `pillow-heif`
- **Fichiers RAW** (.cr2, .cr3, .nef, .arw, .raf, .rw2, .dng, .orf, .srw, .pef) - ignorés si un JPEG/HEIC correspondant existe

## Dépannage

| Problème | Solution |
|-------|----------|
| « externally-managed-environment » | Utilisez un environnement virtuel |
| Traitement lent | Vérifiez le profil VRAM, utilisez `--single-pass` pour les GPU à forte VRAM |
| La détection des visages n'utilise pas le GPU | Installez `onnxruntime-gpu` |
| exiftool manquant | Optionnel — installez-le via le gestionnaire de paquets du système pour de meilleurs résultats, sinon `exifread` gère tous les formats RAW |

Consultez [Installation](INSTALLATION.md) pour des instructions de configuration détaillées.
