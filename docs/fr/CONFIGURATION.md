# Référence de configuration

> 🌐 [English](../CONFIGURATION.md) · **Français** · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md)

Tous les réglages se trouvent dans `scoring_config.json`. Après modification, lancez `python facet.py --recompute-average` pour mettre à jour les scores (aucun GPU requis).

## Table des matières

- [Utilisateurs](#utilisateurs)
- [Analyse](#analyse)
- [Catégories](#catégories)
- [Scoring](#scoring)
- [Seuils](#seuils)
- [Composition](#composition)
- [Ajustements EXIF](#ajustements-exif)
- [Exposition](#exposition)
- [Pénalités](#pénalités)
- [Normalisation](#normalisation)
- [Modèles](#modèles)
- [Modèles d'évaluation de la qualité](#modèles-dévaluation-de-la-qualité)
- [Traitement](#traitement)
- [Détection de rafales](#détection-de-rafales)
- [Scoring des rafales](#scoring-des-rafales)
- [Détection de doublons](#détection-de-doublons)
- [Détection de visages](#détection-de-visages)
- [Regroupement de visages](#regroupement-de-visages)
- [Traitement des visages](#traitement-des-visages)
- [Détection monochrome](#détection-monochrome)
- [Étiquetage](#étiquetage)
- [Tags autonomes](#tags-autonomes)
- [Analyse statistique](#analyse-statistique)
- [Galerie web](#galerie-web)
- [Performance](#performance)
- [Stockage](#stockage)
- [Plugins](#plugins)
- [Capsules](#capsules)
- [Groupes de similarité](#groupes-de-similarité)
- [Chronologie](#chronologie)
- [Carte](#carte)
- [Traduction](#traduction)

---

## Utilisateurs

Mode multi-utilisateur facultatif. Lorsque la clé `users` est présente (avec au moins un utilisateur), l'authentification par mot de passe unique est remplacée par une connexion par utilisateur.

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### Champs utilisateur

| Champ | Type | Description |
|-------|------|-------------|
| `password_hash` | chaîne | Empreinte PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Générée par la CLI `--add-user`. |
| `display_name` | chaîne | Affiché dans l'en-tête de l'interface |
| `role` | chaîne | `user`, `admin` ou `superadmin` |
| `directories` | tableau | Répertoires de photos privés de cet utilisateur |

### Répertoires partagés

La clé `shared_directories` (sœur des objets utilisateur) liste les répertoires visibles par tous les utilisateurs.

### Rôles

| Rôle | Voir ses propres + partagés | Noter/favori | Gérer personnes/visages | Déclencher des analyses |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Ajouter des utilisateurs

Les utilisateurs sont créés uniquement via la CLI — il n'y a ni interface ni API d'inscription :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Demande le mot de passe, écrit l'empreinte dans scoring_config.json
```

Après avoir ajouté un utilisateur, modifiez `scoring_config.json` pour configurer ses `directories`.

### Rétrocompatibilité

- Absence de clé `users` = mode mono-utilisateur historique (comportement inchangé)
- `viewer.password` et `viewer.edition_password` sont ignorés en mode multi-utilisateur
- Les notes existantes dans la table `photos` restent valables pour le mode mono-utilisateur ; utilisez `--migrate-user-preferences` pour les copier

---

## Analyse

Contrôle le comportement de l'analyse des répertoires.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Ignorer les répertoires commençant par `.` lors de l'analyse des photos |

---

## Catégories

Tableau de définitions de catégories. Voir [Scoring](SCORING.md) pour la documentation détaillée des catégories.

Chaque catégorie possède :
- `name` - Identifiant de la catégorie
- `priority` - Plus bas = priorité plus élevée (évalué en premier)
- `filters` - Conditions de correspondance
- `weights` - Poids des métriques de scoring (la somme doit faire 100)
- `modifiers` - Ajustements de comportement
- `tags` - Vocabulaire CLIP pour la correspondance par tag

---

## Scoring

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `score_min` | `0.0` | Score minimum possible |
| `score_max` | `10.0` | Score maximum possible |
| `score_precision` | `2` | Nombre de décimales pour les scores |

---

## Seuils

Seuils de détection pour la catégorisation automatique.

```json
{
  "thresholds": {
    "portrait_face_ratio_percent": 5,
    "blink_penalty_percent": 50,
    "night_luminance_threshold": 0.15,
    "night_iso_threshold": 3200,
    "long_exposure_shutter_threshold": 1.0,
    "astro_shutter_threshold": 10.0
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `portrait_face_ratio_percent` | `5` | Visage > 5 % du cadre = portrait |
| `blink_penalty_percent` | `50` | Multiplicateur de score lors d'un clignement détecté (0,5×) |
| `night_luminance_threshold` | `0.15` | Luminance moyenne inférieure = nuit |
| `night_iso_threshold` | `3200` | ISO supérieur = faible luminosité |
| `long_exposure_shutter_threshold` | `1.0` | Vitesse > 1 s = pose longue |
| `astro_shutter_threshold` | `10.0` | Vitesse > 10 s = astrophotographie |

---

## Composition

Scoring de composition basé sur des règles (utilisé lorsque SAMP-Net n'est pas actif).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Poids du placement selon la règle des tiers |
| `line_weight` | `1.0` | Poids des lignes directrices |

---

## Ajustements EXIF

Ajustements de scoring automatiques basés sur les réglages de l'appareil.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Réduire la pénalité de netteté pour les hauts ISO |
| `aperture_isolation_boost` | `true` | Augmenter l'isolation pour les grandes ouvertures (f/1.4–f/2.8) |

---

## Exposition

Contrôle l'analyse de l'exposition et la détection de l'écrêtage.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Signaler si > 15 % de pixels noir pur |
| `highlight_clip_threshold_percent` | `10` | Signaler si > 10 % de pixels blanc pur |
| `silhouette_detection` | `true` | Détecter les silhouettes intentionnelles |

---

## Pénalités

Pénalités de score pour les problèmes techniques.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "bimodality_threshold": 2.5,
    "bimodality_penalty_points": 0.5,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_pixel_percent": 5,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Un bruit supérieur déclenche une pénalité |
| `noise_max_penalty_points` | `1.5` | Pénalité de bruit maximale |
| `noise_penalty_per_sigma` | `0.3` | Points par sigma au-delà du seuil |
| `bimodality_threshold` | `2.5` | Coefficient de bimodalité de l'histogramme |
| `bimodality_penalty_points` | `0.5` | Pénalité pour les histogrammes bimodaux |
| `leading_lines_blend_percent` | `30` | Intégration dans comp_score |
| `oversaturation_threshold` | `0.9` | Seuil de saturation moyenne |
| `oversaturation_pixel_percent` | `5` | Réservé à la détection au niveau du pixel |
| `oversaturation_penalty_points` | `0.5` | Pénalité de sursaturation |

**Formule de pénalité de bruit :**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalisation

Contrôle la façon dont les métriques brutes sont mises à l'échelle en scores de 0 à 10.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `method` | `"percentile"` | Méthode de normalisation |
| `percentile_target` | `90` | 90ᵉ percentile = score de 10,0 |
| `per_category` | `true` | Normalisation spécifique à la catégorie |
| `category_min_samples` | `50` | Photos minimum pour la normalisation par catégorie |

---

## Modèles

Sélectionne les modèles utilisés selon le profil VRAM.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": [],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (8GB+ RAM)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "qwen2-vl-2b",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "similarity_threshold_percent": 8
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "similarity_threshold_percent": 22
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "florence_2_large": {
      "model_path": "florence-community/Florence-2-large",
      "torch_dtype": "float32",
      "vlm_batch_size": 4,
      "max_new_tokens": 256
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth",
      "download_url": "https://github.com/bcmi/Image-Composition-Assessment-with-SAMP/releases/download/v1.0/samp_net.pth",
      "input_size": 384,
      "patterns": [
        "none", "center", "rule_of_thirds", "golden_ratio", "triangle",
        "horizontal", "vertical", "diagonal", "symmetric", "curved",
        "radial", "vanishing_point", "pattern", "fill_frame"
      ]
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Profil actif (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Conserver les modèles en RAM entre les passes multi-passes (`"auto"`, `"always"`, `"never"`). `auto` vérifie la RAM disponible avant la mise en cache. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modèles PyIQA à exécuter pour ce profil (vide sur `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Exécuter la saillance du sujet BiRefNet pour ce profil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modèle d'embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (historique) |
| `clip.embedding_dim` | `1152` | Dimensions de l'embedding (1152 pour SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similarité cosinus CLIP minimale pour une correspondance de tag |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modèle CLIP historique (profils legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Poids pré-entraînés historiques |
| `clip_legacy.embedding_dim` | `768` | Dimensions de l'embedding historique |
| `clip_legacy.similarity_threshold_percent` | `22` | Seuil de correspondance de tag pour le CLIP historique |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Chemin HuggingFace (VLM de composition 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modèle d'étiquetage pour le profil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Images par lot d'inférence VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modèle d'étiquetage pour le profil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Images par lot d'inférence VLM |
| `florence_2_large.model_path` | `"florence-community/Florence-2-large"` | Modèle Florence-2 (étiqueteur alternatif) |
| `florence_2_large.vlm_batch_size` | `4` | Images par lot d'inférence Florence-2 |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modèle de saillance BiRefNet |
| `saliency.resolution` | `1024` | Résolution d'inférence |
| `saliency.mask_threshold` | `0.3` | Seuil sigmoïde pour le masque binaire du sujet |
| `saliency.min_subject_pixels` | `50` | Pixels de sujet minimum pour considérer un sujet comme détecté |
| `samp_net.input_size` | `384` | Taille d'entrée du modèle de composition |

### Détection automatique de la VRAM

Lorsque `vram_profile` vaut `"auto"` (par défaut), le système détecte la VRAM GPU disponible au démarrage et sélectionne le plus grand profil qui tient :

| VRAM détectée | Profil sélectionné |
|---------------|------------------|
| ≥ 20 Go | `24gb` |
| ≥ 14 Go | `16gb` |
| ≥ 6 Go | `8gb` |
| Pas de GPU | `legacy` (utilise la RAM système) |

---

## Modèles d'évaluation de la qualité

Sélectionne le modèle qui évalue la qualité/esthétique de l'image, via la bibliothèque [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `model` | `"auto"` | Modèle de qualité : `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` utilise `topiq`. |
| `prefer_llm` | `false` | Préférer un évaluateur basé sur un LLM lorsqu'il est disponible |

### Modèles de qualité disponibles

SRCC = coefficient de corrélation de rang de Spearman sur le benchmark KonIQ-10k (1,0 = parfait).

| Modèle | SRCC | VRAM | Notes |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2 Go | Par défaut (`auto`) ; ossature ResNet50 avec attention descendante |
| `hyperiqa` | 0.90 | ~2 Go | Hyper-réseau, adaptatif au contenu |
| `dbcnn` | 0.90 | ~2 Go | CNN à double branche (distorsions synthétiques + authentiques) |
| `musiq` | 0.87 | ~2 Go | Transformeur multi-échelle ; gère toute résolution |
| `clipiqa+` | 0.86 | ~4 Go | CLIP avec invites de qualité apprises |
| `clip-mlp` | 0.76 | ~4 Go | CLIP ViT-L-14 historique + tête MLP |

### Changer de modèle de qualité

1. Modifiez `scoring_config.json` :
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Re-noter les photos existantes (facultatif) :
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Traitement

Réglages de traitement unifiés pour le traitement par lots GPU et le mode multi-passes.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Concepts clés

**`gpu_batch_size`** - Nombre d'images traitées ensemble sur le GPU en une seule passe avant. Limité par la VRAM. Auto-ajusté : réduit lorsque la mémoire GPU dépasse la limite.

**`ram_chunk_size`** - Nombre d'images mises en cache en RAM entre les passes de modèles (mode multi-passes uniquement). Réduit les E/S disque en chargeant les images une seule fois par lot. Limité par la RAM système. Auto-ajusté : réduit lorsque la mémoire système dépasse la limite.

### Référence des réglages

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `mode` | `"auto"` | Mode de traitement : `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Images par lot GPU (limité par la VRAM) |
| `ram_chunk_size` | `32` | Images par lot RAM (multi-passes) |
| `num_workers` | `4` | Threads de chargement d'images |
| `load_workers` | `num_workers` | Threads de chargement de lots multi-passes (plafonné à 8, `1` = séquentiel) |
| `raw_decode_concurrency` | `0` (auto) | Décodages RAW simultanés maximum ; dimensionné automatiquement selon CPU/RAM (1-4), `1` = entièrement sérialisé |
| `raw_decode_timeout_seconds` | `120` | Abandonner un décodage RAW bloqué après ce délai (`0` = désactivé) ; l'analyse échoue rapidement après plusieurs blocages |
| `exif_prefetch` | `true` | Mode single-pass : précharger les EXIF en arrière-plan au lieu de bloquer le thread GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Activer l'auto-ajustement |
| `monitor_interval_seconds` | `5` | Intervalle de vérification des ressources |
| `tuning_interval_images` | `32` | Réajuster toutes les N images |
| `min_processing_workers` | `1` | Threads de chargement minimum |
| `max_processing_workers` | `32` | Threads de chargement maximum |
| `min_gpu_batch_size` | `2` | Taille de lot GPU minimale |
| `max_gpu_batch_size` | `32` | Taille de lot GPU maximale |
| `min_ram_chunk_size` | `10` | Taille de lot RAM minimale |
| `max_ram_chunk_size` | `128` | Taille de lot RAM maximale |
| `memory_limit_percent` | `85` | Limite d'utilisation de la mémoire système |
| `cpu_target_percent` | `85` | Cible d'utilisation du CPU |
| `metrics_print_interval_seconds` | `30` | Intervalle d'affichage des stats |
| **thumbnails** | | |
| `photo_size` | `640` | Taille de la miniature stockée (pixels) |
| `photo_quality` | `80` | Qualité JPEG de la miniature |
| `face_padding_ratio` | `0.3` | Marge autour des recadrages de visage |

### Modes de traitement

| Mode | Description |
|------|-------------|
| `auto` | Sélectionne automatiquement le mode multi-passes ou single-pass selon la VRAM |
| `multi-pass` | Chargement séquentiel des modèles (fonctionne avec une VRAM limitée) |
| `single-pass` | Tous les modèles chargés à la fois (nécessite une VRAM élevée) |

### Fonctionnement du mode multi-passes

Au lieu de charger tous les modèles à la fois, le mode multi-passes :

1. Charge les images par lots en RAM (`ram_chunk_size` par défaut : 32)
2. Pour chaque lot, exécute les modèles séquentiellement : charger le modèle → traiter le lot → décharger le modèle
3. Combine les résultats dans une passe d'agrégation finale

Chaque image est chargée une fois par lot, et les passes sont regroupées pour tenir dans la VRAM disponible, de sorte que les plus gros VLM d'étiquetage/composition s'exécutent même avec une VRAM limitée.

### Comportement de l'auto-ajustement

Le système surveille l'utilisation des ressources et s'ajuste :

| Métrique | Action |
|--------|--------|
| Mémoire GPU > limite | Réduire `gpu_batch_size` de 25 % |
| RAM système > limite | Réduire `ram_chunk_size` de 25 % |
| RAM système < (limite - 20 %) | Augmenter `ram_chunk_size` de 25 % |
| CPU > cible | Suggérer moins de workers |
| Délais d'attente de la file > 5 % | Suggérer plus de workers |

### Regroupement dynamique des passes

Lorsque la VRAM le permet, plusieurs petits modèles s'exécutent ensemble :

| VRAM | Passe 1 | Passe 2 |
|------|--------|--------|
| 8 Go | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12 Go | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16 Go | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM d'étiquetage |
| 24 Go+ | Tous les modèles ensemble (single-pass) | - |

### Options CLI

```bash
# Par défaut : multi-passes automatique avec regroupement optimal
python facet.py /path/to/photos

# Forcer le single-pass (tous les modèles chargés à la fois)
python facet.py /path --single-pass

# Exécuter une passe spécifique uniquement
python facet.py /path --pass quality       # TOPIQ uniquement
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérite esthétique)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualité + distorsion)
python facet.py /path --pass tags          # Étiqueteur configuré uniquement
python facet.py /path --pass composition   # SAMP-Net uniquement
python facet.py /path --pass faces         # InsightFace uniquement
python facet.py /path --pass embeddings    # Embeddings CLIP/SigLIP uniquement
python facet.py /path --pass saliency      # Saillance du sujet BiRefNet

# Lister les modèles disponibles
python facet.py --list-models
```

---

## Détection de rafales

Regroupe les photos similaires prises en succession rapide.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Seuil de similarité de l'empreinte d'image |
| `time_window_minutes` | `0.8` | Temps maximum entre les photos |
| `rapid_burst_seconds` | `0.4` | Photos dans ce délai automatiquement regroupées |

---

## Scoring des rafales

Poids utilisés par le tri de rafales pour calculer un score composite afin de sélectionner la meilleure prise au sein de chaque groupe de rafale. La somme des poids devrait faire 1,0.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Poids du score agrégat global |
| `weight_aesthetic` | `0.25` | Poids du score de qualité esthétique |
| `weight_sharpness` | `0.2` | Poids du score de netteté technique |
| `weight_blink` | `0.15` | Poids de pénalité pour les clignements détectés (plus élevé = pénalité plus forte) |

---

## Détection de doublons

Détecte les photos en doublon de façon globale par comparaison d'empreinte perceptuelle (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Filtre pHash strict (90 % = distance de Hamming <= 6 sur 64 bits) ; utilisé comme seul critère lorsqu'un embedding manque pour l'une des photos |
| `prefilter_hamming` | `12` | Filtre Hamming large d'étape 1 pour l'ensemble de candidats lorsque les deux photos ont des embeddings (forcé à être >= au filtre strict) |
| `embedding_cosine_threshold` | `0.90` | Filtre cosinus SigLIP/CLIP d'étape 2 : un candidat pHash large ne fusionne que si le cosinus est >= à cette valeur |

La détection est en deux étapes : candidats pHash larges (rappel) confirmés par un filtre cosinus d'embedding serré (précision). Les photos sans embedding retombent sur le critère strict pHash seul, donc le comportement est inchangé en l'absence d'embeddings.

Lancez `python facet.py --detect-duplicates` pour détecter et regrouper les doublons. Lancez `python facet.py --sweep-dedup-thresholds [labels.json]` pour évaluer le filtre cosinus — avec un JSON de labels, il affiche un tableau précision/rappel, sinon la distribution cosinus des candidats et le nombre de collisions pHash strictes que le filtre rejette.

---

## Niveau IQA étendu (facultatif)

Évaluateurs de qualité lourds/expérimentaux, **désactivés par défaut** et **jamais en remplacement de TOPIQ** — ils ajoutent uniquement des colonnes supplémentaires lorsqu'ils sont explicitement activés. Une fois activés, les évaluateurs étendus s'exécutent **pendant une analyse normale** et écrivent leurs propres colonnes ; un échec de chargement/VRAM est journalisé et la colonne reste `NULL` (l'analyse n'est jamais interrompue).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Réglage | Défaut | Valeurs acceptées | Colonne | Description |
|---------|---------|-----------------|--------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA basé sur LLM Q-Align (adossé à pyiqa). `"4bit"` (~6-8 Go VRAM) est le choix pratique sur une carte de 16 Go ; `"8bit"` ~12-14 Go ; pleine précision (`true`) nécessite 16 Go+. Le 4/8 bits requiert `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (tête SigLIP, ~2 Go). Nécessite le paquet `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16 Go+ ; ignoré et laissé NULL sinon). |

**Installez les dépendances facultatives** correspondant à ce que vous activez : `pip install -e .[iqa-extended]` (ajoute `aesthetic-predictor-v2-5` + `bitsandbytes`), ou décommentez les lignes correspondantes dans `requirements.txt`. Q-Align lui-même est livré avec `pyiqa` ; DeQA-Score se télécharge via `transformers`.

Une fois activée, chaque métrique est exposée à l'agrégat pondéré mais avec un poids 0 par défaut, donc `--recompute-average` est identique octet par octet jusqu'à ce que vous lui attribuiez un poids. Lancez `python facet.py --eval-iqa-srcc` pour mesurer à quel point chaque métrique classe votre bibliothèque par rapport à vos propres notes en étoiles.

**Affichage dans la galerie web.** Lorsque l'une de ces colonnes est renseignée, la galerie affiche la valeur dans le panneau **Qualité** du détail de la photo (`Q-Align`, `Aesthetic V2.5`, `DeQA`) et expose un curseur de plage correspondant dans la barre latérale de filtres de la galerie sous **Qualité étendue** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Les photos analysées avant l'activation du niveau ont simplement `NULL` dans ces colonnes et ne sont pas affectées par les filtres.

**Robustesse.** DeQA-Score charge du code distant `trust_remote_code` dont la signature de la fonction forward varie selon les révisions de checkpoint ; son évaluateur est défensif — tout échec de prédiction (mauvaise signature, forme de sortie inattendue, OOM) est intercepté et le `deqa_score` de l'image reste `NULL` plutôt que de faire planter l'analyse.

---

## Détection de visages

Réglages de détection de visages InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confiance de détection minimale |
| `min_face_size` | `20` | Taille de visage minimale en pixels |
| `blink_ear_threshold` | `0.28` | Ratio d'aspect de l'œil (EAR) pour la détection de clignement |
| `min_faces_for_group` | `4` | Visages minimum pour classer comme portrait de groupe (recalculé lors de `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Charger le module InsightFace `landmark_3d_68` pour l'extraction de la pose de la tête (lacet/tangage/roulis). Coûte ~5 Mo de poids ONNX supplémentaires. Actuellement informatif ; de futures améliorations de profil/silhouette le liront. |

---

## Regroupement de visages

Regroupement HDBSCAN pour la reconnaissance faciale.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6,
    "chunk_size": 10000
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `enabled` | `true` | Activer le regroupement de visages |
| `min_faces_per_person` | `2` | Photos minimum par personne |
| `min_samples` | `2` | Paramètre min_samples de HDBSCAN |
| `auto_merge_distance_percent` | `15` | Fusion automatique dans cette distance |
| `clustering_algorithm` | `"best"` | Algorithme HDBSCAN |
| `leaf_size` | `40` | Taille de feuille de l'arbre (CPU uniquement) |
| `use_gpu` | `"auto"` | Mode GPU : `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similarité de centroïde pour la correspondance |
| `chunk_size` | `10000` | Taille de lot de traitement |

**Algorithmes de regroupement :**

| Algorithme | Complexité | Idéal pour |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Données de haute dimension (recommandé) |
| `boruvka_kdtree` | O(n log n) | Données de basse dimension |
| `prims_balltree` | O(n²) | Mémoire limitée, haute dimension |
| `prims_kdtree` | O(n²) | Mémoire limitée, basse dimension |
| `best` | Auto | Laisser HDBSCAN décider |

---

## Traitement des visages

Contrôle l'extraction des visages et la génération de miniatures.

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Ratio de marge pour les recadrages de visage |
| `use_db_thumbnails` | `true` | Utiliser les miniatures stockées |
| `face_thumbnail_size` | `640` | Taille de miniature en pixels |
| `face_thumbnail_quality` | `90` | Qualité JPEG |
| `extract_workers` | `2` | Workers d'extraction parallèles |
| `extract_batch_size` | `16` | Taille de lot d'extraction |
| `refill_workers` | `4` | Workers de réapprovisionnement de miniatures |
| `refill_batch_size` | `100` | Taille de lot de réapprovisionnement |
| **auto_tuning** | | |
| `enabled` | `true` | Activer l'ajustement basé sur la mémoire |
| `memory_limit_percent` | `80` | Limite d'utilisation de la mémoire |
| `min_batch_size` | `8` | Taille de lot minimale |
| `monitor_interval_seconds` | `5` | Intervalle de vérification |

---

## Détection monochrome

Détection des photos en noir et blanc.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Saturation moyenne < 5 % = monochrome |

---

## Étiquetage

Réglages généraux d'étiquetage. Le modèle d'étiquetage est configuré par profil dans `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `enabled` | `true` | Activer l'étiquetage |
| `max_tags` | `5` | Tags maximum par photo |

**Note :** les réglages spécifiques à CLIP comme `similarity_threshold_percent` se trouvent dans la section `models.clip`.

### Modèles d'étiquetage disponibles

Configurés via `models.profiles.*.tagging_model` :

| Modèle | VRAM | Style de tags | Notes |
|-------|------|-----------|-------|
| `clip` | 0 (réutilise les embeddings) | Ambiance/atmosphère (dramatic, golden_hour, vintage) | Aucun chargement de modèle supplémentaire ; détection d'objets moins littérale |
| `qwen3.5-2b` | ~4 Go | Scènes structurées (landscape, architecture, reflection) | Nécessite transformers + VRAM supplémentaire |
| `qwen3.5-4b` | ~8 Go | Scènes détaillées avec nuance | VRAM plus élevée ; inférence plus lente |
| `florence-2` | ~2 Go | Objets littéraux (sky, water, building) | Sur-étiquette les termes génériques ; la correspondance basée sur les légendes est fragile |

### Modèles d'étiquetage par défaut selon le profil

| Profil | Modèle d'étiquetage | Modèle d'embedding |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Réétiqueter les photos

```bash
python facet.py --recompute-tags       # Réétiqueter avec le modèle configuré par profil
python facet.py --recompute-tags-vlm   # Réétiqueter avec l'étiqueteur VLM
```

---

## Tags autonomes

Tags avec des listes de synonymes qui ne sont liés à aucune catégorie spécifique. Ils sont disponibles pour toutes les photos quelle que soit l'attribution de catégorie. Chaque clé est le nom du tag ; la valeur est une liste de synonymes pour la correspondance CLIP/VLM.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Ajoutez de nouveaux tags autonomes en fournissant une clé et une liste de synonymes. Les tags définis ici sont fusionnés avec les tags spécifiques aux catégories pour former le vocabulaire de tags complet.

---

## Analyse statistique

Seuils pour `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Avertir si l'esthétique maximale est en dessous |
| `aesthetic_target` | `9.5` | Cible pour aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Seuil de qualité « haute valeur » |
| `quality_weight_threshold_percent` | `10` | Avertir si le poids de qualité ≤ cette valeur |
| `correlation_dominant_threshold` | `0.5` | Avertissement « signal dominant » |
| `category_min_samples` | `50` | Photos minimum par catégorie |
| `category_imbalance_threshold` | `0.5` | Avertissement d'écart de score |
| `score_clustering_std_threshold` | `1.0` | Avertir si l'écart-type < cette valeur |
| `top_score_threshold` | `8.5` | Avertir si l'agrégat maximal < cette valeur |
| `exposure_avg_threshold` | `8.0` | Avertir si l'exposition moyenne > cette valeur |

---

## Galerie web

Affichage et comportement de la galerie web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "uncertainty",
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": []
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "tooltip_mode": "hover",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 60,
    "notification_duration_ms": 2000,
    "path_mapping": {}
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `default_category` | `""` | Filtre de catégorie par défaut |
| `edition_password` | `""` | Mot de passe pour déverrouiller le mode édition (vide = désactivé) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Minimum pour l'optimisation |
| `pair_selection_strategy` | `"uncertainty"` | Stratégie par défaut |
| `show_current_scores` | `true` | Afficher les scores pendant la comparaison |
| **pagination** | | |
| `default_per_page` | `64` | Photos par page |
| **dropdowns** | | |
| `max_cameras` | `50` | Appareils maximum dans le menu déroulant |
| `max_lenses` | `50` | Objectifs maximum |
| `max_persons` | `50` | Personnes maximum |
| `max_tags` | `20` | Tags maximum |
| `min_photos_for_person` | `10` | Masquer les personnes ayant moins de photos du menu déroulant |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Valeur minimale de face_count pour qu'un groupe auto-clusterisé apparaisse dans la section « À nommer » de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nom du binaire darktable-cli ou chemin absolu |
| `darktable.profiles` | `[]` | Tableau de profils d'export darktable nommés (voir ci-dessous) |
| `darktable.profiles[].name` | *(requis)* | Nom d'affichage du profil (utilisé dans le menu de téléchargement et le paramètre API `profile`) |
| `darktable.profiles[].hq` | `true` | Passer `--hq true` pour un export de haute qualité |
| `darktable.profiles[].width` | *(omis)* | Largeur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].height` | *(omis)* | Hauteur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].extra_args` | `[]` | Arguments CLI supplémentaires (ex : `["--style", "monochrome"]`) |
| **display** | | |
| `tags_per_photo` | `4` | Tags affichés sur les cartes |
| `card_width_px` | `168` | Largeur de carte |
| `image_width_px` | `160` | Largeur d'image |
| `image_jpeg_quality` | `96` | Qualité JPEG pour la conversion RAW/HEIF dans `/api/download` et `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Taille de miniature minimale (px) |
| `thumbnail_slider.max_px` | `400` | Taille de miniature maximale (px) |
| `thumbnail_slider.default_px` | `168` | Taille de miniature par défaut (px) |
| `thumbnail_slider.step_px` | `8` | Incrément de pas du curseur (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Taille de miniature |
| `jpeg_quality` | `80` | Qualité JPEG |
| `crop_padding_ratio` | `0.2` | Marge de visage |
| `min_crop_size_px` | `20` | Taille de recadrage minimale |
| **quality_thresholds** | | |
| `good` | `6` | Seuil « bon » |
| `great` | `7` | Seuil « très bon » |
| `excellent` | `8` | Seuil « excellent » |
| `best` | `9` | Seuil « meilleur » |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimum pour Meilleurs choix |
| `top_picks_min_face_ratio` | `0.2` | Ratio de visage pour les poids |
| `low_light_max_luminance` | `0.2` | Seuil de faible luminosité |
| **defaults** | | |
| `type` | `""` | Filtre de type de photo par défaut (ex : `"portraits"`, `"landscapes"` ou `""` pour Toutes) |
| `sort` | `"aggregate"` | Colonne de tri par défaut |
| `sort_direction` | `"DESC"` | Direction de tri par défaut (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Masquer les photos avec clignement par défaut |
| `hide_bursts` | `true` | N'afficher que la meilleure de la rafale par défaut |
| `hide_duplicates` | `true` | Masquer les photos en doublon non principales par défaut |
| `hide_details` | `true` | Masquer les détails des photos sur les cartes par défaut |
| `tooltip_mode` | `"hover"` | Déclencheur d'infobulle : `"hover"`, `"click"` ou `"off"`. Remplace l'ancien booléen `hide_tooltip`. |
| `hide_rejected` | `true` | Masquer les photos rejetées par défaut |
| `gallery_mode` | `"mosaic"` | Disposition de galerie par défaut (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origines CORS autorisées pour le serveur FastAPI. Ajoutez votre domaine ou l'URL du reverse proxy lors d'un hébergement distant. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(valeur par défaut compatible SPA)_ | Valeur de l'en-tête Content-Security-Policy. Par défaut, une politique autorisant les propres ressources du SPA (script/style de thème inline, Google Fonts, tuiles OpenStreetMap, API de même origine). Définir à `""` pour désactiver, ou fournir une politique plus stricte. |
| `security_headers.hsts` | `false` | Envoyer `Strict-Transport-Security`. À activer uniquement lorsque la galerie est servie via HTTPS. |
| **Autres** | | |
| `cache_ttl_seconds` | `60` | TTL du cache de requêtes |
| `notification_duration_ms` | `2000` | Durée des notifications toast |

### Fonctionnalités

Activez ou désactivez les fonctionnalités facultatives pour réduire l'utilisation de la mémoire ou simplifier l'interface :

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_rating_badge": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `show_similar_button` | `true` | Afficher le bouton « Similaires » sur les cartes photo (utilise numpy pour la similarité CLIP) |
| `show_merge_suggestions` | `true` | Activer la fonctionnalité de suggestions de fusion sur la page de gestion des personnes |
| `show_rating_controls` | `true` | Afficher les contrôles de note (étoiles) et de favori |
| `show_rating_badge` | `true` | Afficher le badge de note sur les cartes photo |
| `show_scan_button` | `false` | Afficher le bouton de déclenchement d'analyse pour les utilisateurs superadmin (nécessite un GPU sur l'hôte de la galerie) |
| `metrics_enabled` | `false` | Activer le point de terminaison Prometheus public `GET /metrics`. Désactivé par défaut — il expose le nombre de photos/personnes/visages, la taille de la base et la mémoire du processus ; à activer uniquement lorsque le point de terminaison est accessible depuis le réseau du scraper, pas depuis l'internet public. |
| `show_semantic_search` | `true` | Afficher la barre de recherche sémantique (recherche texte-vers-image avec les embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Afficher la fonctionnalité d'albums (créer, gérer et parcourir des albums de photos) |
| `show_critique` | `true` | Afficher le bouton de critique IA sur les cartes photo (ventilation du score basée sur des règles) |
| `show_vlm_critique` | `false` | Activer le mode de critique alimenté par VLM (nécessite un profil VRAM 16gb/24gb) |
| `show_memories` | `true` | Afficher la boîte de dialogue Souvenirs « Ce jour-là » (photos prises à la même date les années précédentes) |
| `show_captions` | `true` | Afficher les légendes générées par IA sur les cartes photo |
| `show_timeline` | `true` | Afficher la vue chronologie pour un parcours chronologique avec navigation par date |
| `show_map` | `false` | Afficher la vue carte avec les emplacements de photos géolocalisées (nécessite Leaflet ; désactivé par défaut car les photos peuvent manquer de données GPS) |

**Optimisation de la mémoire :** définir `show_similar_button: false` empêche le chargement de numpy, réduisant l'empreinte mémoire de la galerie. La fonctionnalité de photos similaires calcule la similarité cosinus des embeddings CLIP, ce qui nécessite numpy.

### Mappage de chemins

Mappez les chemins de la base de données vers les chemins du système de fichiers local. Utile lorsque les photos ont été notées sur une machine (ex : Windows avec des chemins UNC) mais que la galerie tourne sur une autre (ex : NAS Linux avec des points de montage).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `path_mapping` | `{}` | Dictionnaire de préfixe source vers préfixe destination. Lors du service d'images en pleine taille ou de la critique VLM, les chemins de la base commençant par un préfixe source sont réécrits pour utiliser le préfixe destination. |

**Fonctionnement :**
- S'applique uniquement lors de la **lecture de fichiers depuis le disque** (service d'images en pleine taille, téléchargements de fichiers, critique VLM). Les chemins de la base de données ne sont jamais modifiés.
- La normalisation barre oblique inverse/barre oblique est gérée automatiquement : `\\NAS\Photos\img.jpg` et `//NAS/Photos/img.jpg` correspondent tous deux.
- Les mappages sont évalués dans l'ordre ; le premier préfixe correspondant l'emporte.
- Les cibles de mappage de chemins sont automatiquement incluses dans la liste d'autorisation des répertoires d'analyse pour les contrôles de sécurité multi-utilisateur.

**Exemple :** une base remplie sous Windows stocke des chemins comme `\\NAS\Photos\2024\IMG_001.jpg`. Sous Linux, le même partage est monté sur `/mnt/nas/Photos`. Configurez :

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protection par mot de passe

Protection par mot de passe facultative pour la galerie :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Une fois définie, les utilisateurs doivent s'authentifier avant d'accéder à la galerie.

### Performance de la galerie

Surcharge les réglages globaux `performance` lors de l'exécution de la galerie. Utile pour un déploiement NAS à faible mémoire où la notation nécessite beaucoup de ressources mais pas la galerie.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Surcharge de la taille mmap SQLite pour les connexions de la galerie. `0` désactive le mmap. |
| `cache_size_mb` | *(global)* | Surcharge de la taille de cache SQLite pour les connexions de la galerie |
| `pool_size` | `5` | Taille du pool de connexions (réduire pour les systèmes à faible mémoire) |
| `thumbnail_cache_size` | `2000` | Entrées maximum dans le cache en mémoire de redimensionnement des miniatures |
| `face_cache_size` | `500` | Entrées maximum dans le cache en mémoire des miniatures de visage |

Lorsqu'elles ne sont pas définies, la galerie utilise les valeurs globales `performance`. Voir [Déploiement](DEPLOYMENT.md) pour les réglages NAS recommandés.

---

## Performance

Réglages de performance de la base de données.

```json
{
  "performance": {
    "mmap_size_mb": 12288,
    "cache_size_mb": 64,
    "wal_checkpoint_minutes": 30,
    "slow_request_ms": 1000
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `mmap_size_mb` | `12288` | Taille des E/S mappées en mémoire SQLite |
| `cache_size_mb` | `64` | Taille du cache SQLite |
| `wal_checkpoint_minutes` | `30` | Intervalle en minutes pour le `PRAGMA wal_checkpoint(TRUNCATE)` en arrière-plan de la galerie. Empêche le gonflement du WAL sur les déploiements de longue durée. Définir à `0` pour désactiver. |
| `slow_request_ms` | `1000` | Les requêtes de l'API de la galerie plus lentes que ce nombre de millisecondes sont journalisées au niveau WARNING avec un marqueur `SLOW`. Définir à `0` pour désactiver. |

---

## Stockage

Contrôle l'emplacement de stockage des miniatures et des embeddings. Par défaut, ce sont des colonnes BLOB dans la base SQLite ; le mode système de fichiers les stocke à la place sous forme de fichiers sur le disque, ce qui réduit la taille de la base.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `mode` | `"database"` | Backend de stockage : `"database"` (BLOB SQLite) ou `"filesystem"` (fichiers sur disque) |
| `filesystem_path` | `"./storage"` | Répertoire de base pour le mode système de fichiers. Les miniatures sont stockées dans `<path>/thumbnails/` et les embeddings dans `<path>/embeddings/`, organisés en sous-répertoires par hash de contenu. |

**Détails du mode système de fichiers :**
- Les fichiers sont organisés par hash SHA-256 du chemin de la photo, avec des sous-répertoires à deux caractères pour éviter trop de fichiers dans un même répertoire (ex : `thumbnails/a3/a3f8..._640.jpg`).
- Supprimer une photo supprime toutes les tailles de miniature et fichiers d'embedding associés.
- Le répertoire est créé automatiquement à la première utilisation.

---

## Plugins

Système de plugins piloté par événements pour réagir aux événements de notation. Les plugins peuvent être des modules Python, des webhooks ou des actions intégrées.

### Configuration

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Clé | Défaut | Description |
|-----|---------|-------------|
| `enabled` | `false` | Interrupteur principal — lorsque faux, aucun événement n'est émis |
| `high_score_threshold` | `8.0` | Score agrégat minimum pour déclencher les événements `on_high_score` |
| `webhooks` | `[]` | Liste des points de terminaison webhook recevant des charges utiles JSON POST |
| `actions` | `{}` | Actions intégrées nommées déclenchées par des événements |

### Événements pris en charge

| Événement | Déclencheur | Charge utile |
|-------|---------|---------|
| `on_score_complete` | Après notation de chaque photo | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Lorsqu'une photo entre dans la base | Identique à `on_score_complete` |
| `on_high_score` | Lorsque l'agrégat ≥ `high_score_threshold` | Identique à `on_score_complete` |
| `on_burst_detected` | Lorsqu'un groupe de rafale est identifié | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Écrire un plugin

Placez un fichier `.py` dans le répertoire `plugins/`. Définissez des fonctions nommées d'après les événements que vous voulez gérer :

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Voir `plugins/example_plugin.py.example` pour l'interface complète.

### Webhooks

Chaque webhook reçoit un POST JSON avec protection SSRF (les adresses privées/loopback sont bloquées) :

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Options de webhook : `url` (requis), `events` (liste de noms d'événements), `min_score` (agrégat minimum pour déclencher).

### Actions intégrées

| Action | Description | Options |
|--------|-------------|---------|
| `copy_to_folder` | Copier la photo dans un dossier | `folder`, `min_score` |
| `send_notification` | Journaliser une notification | `min_score` |

### Points de terminaison API

| Méthode | Chemin | Description |
|--------|------|-------------|
| `GET` | `/api/plugins` | Lister les plugins, webhooks et actions chargés |
| `POST` | `/api/plugins/test-webhook` | Envoyer une charge utile de test à une URL de webhook |

---

## Capsules

Diaporamas de photos sélectionnées, regroupés par thème. Les capsules sont auto-générées à partir de votre bibliothèque de photos et mises en cache avec un TTL configurable.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Réglages globaux

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Score agrégat minimum pour qu'une photo soit incluse dans les capsules |
| `max_photos_per_capsule` | `40` | Photos maximum par capsule (diversité MMR appliquée au-delà de 5) |
| `max_photo_overlap` | `0.2` | Fraction maximale de photos partagées entre deux capsules avant que la déduplication n'en supprime une |
| `mmr_lambda` | `0.5` | Poids de diversité MMR : 0 = maximiser la diversité, 1 = maximiser la qualité |
| `freshness_hours` | `24` | TTL du cache et période de rotation des photos de couverture et des capsules amorcées |
| `reverse_geocoding` | `true` | Activer le géocodage inverse hors ligne pour les titres de capsules d'emplacement/voyage (nécessite le paquet `reverse_geocoder`) |

### Types de capsules

| Type | Description |
|------|-------------|
| `journey` | Voyages détectés via le regroupement GPS + écarts temporels. Les titres incluent le nom de la destination lorsque le géocodage est activé. |
| `faces_of` | Meilleures photos de chaque personne reconnue |
| `seasonal` | Photos regroupées par saison + année |
| `golden` | Top 1 % par score agrégat |
| `color_story` | Groupes visuellement similaires via le regroupement des embeddings CLIP |
| `this_week` | « Cette semaine, il y a des années » — « Ce jour-là » étendu sur ±3 jours |
| `location` | Groupes de photos géolocalisées avec noms de lieux géocodés inversement |
| `person_pair` | Paires de personnes nommées apparaissant ensemble |
| `seeded` | Découverte basée sur des amorces via le temps, la similarité, la personne, le tag, l'emplacement, l'ambiance |
| `progress` | « Votre photographie s'améliore » à partir des tendances de score trimestrielles |
| `color_palette` | « Couleur du mois » à partir des profils de saturation/monochrome |
| `rare_pair` | Paires de personnes peu fréquentes dans les photos à haut score |
| `favorites` | Photos mises en favori regroupées par année et saison |

### Capsules basées sur les dimensions

Générées automatiquement à partir des colonnes de la base de données :

| Dimension | Regroupe par |
|-----------|-----------|
| `year` | Année extraite de date_taken |
| `month` | Année-mois extraits de date_taken |
| `week` | Année-semaine extraites de date_taken |
| `camera` | Modèle d'appareil |
| `lens` | Modèle d'objectif |
| `tag` | Tags de photo (nécessite la table `photo_tags`) |
| `day_of_week` | Jour de la semaine (dimanche–samedi) |
| `composition` | Motif de composition SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Tranches de focale : ultra grand-angle (<24 mm), grand-angle (24–35 mm), standard (36–70 mm), portrait (71–135 mm), téléobjectif (136–300 mm), super téléobjectif (300 mm+) |
| `category` | Catégorie de contenu de la photo (portrait, landscape, street, etc.) |
| `time_of_day` | Tranches horaires : golden morning, morning, midday, afternoon, golden evening, night |
| `star_rating` | Notes en étoiles de l'utilisateur (1–5 étoiles) |

Des combinaisons inter-dimensionnelles sont également générées (ex : camera × year, focal_range × category, category × year).

### Transitions de diaporama

Chaque type de capsule est associé à une transition de diapositive thématique :

| Transition | Utilisée par | Effet |
|-----------|---------|--------|
| `crossfade` | Par défaut | Échange d'opacité de 300 ms |
| `slide` | journey, location, this_week | Glissement depuis la droite (500 ms) |
| `zoom` | faces_of, color_story | Échelle 1,05→1,0 avec fondu (400 ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lent 1,0→1,08 sur la durée de la diapositive |

### Géocodage inverse

Les capsules d'emplacement et de voyage utilisent le géocodage inverse hors ligne via le paquet `reverse_geocoder` (jeu de données GeoNames local, ~30 Mo, aucun appel API). Les résultats sont mis en cache dans la table de base de données `location_names` à une résolution de grille de 0,1° (~11 km).

Installation : `pip install reverse_geocoder`

Définir `"reverse_geocoding": false` pour désactiver et revenir à l'affichage des coordonnées.

## Groupes de similarité

Réglages pour la fonctionnalité de tri IA des photos similaires, qui regroupe les photos visuellement similaires à l'aide des embeddings CLIP/SigLIP :

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Similarité cosinus minimale (0,0–1,0) pour considérer deux photos comme visuellement similaires. Des valeurs plus basses produisent des groupes plus grands mais avec moins de similarité visuelle. |
| `min_group_size` | `2` | Nombre minimum de photos requis pour former un groupe de similarité |
| `max_photos` | `10000` | Photos maximum à charger pour le calcul de similarité (coût O(n²)). Augmentez pour les bibliothèques plus grandes au détriment du temps de calcul. |
| `max_group_size` | `50` | Photos maximum par groupe de similarité. Les groupes plus grands sont scindés pour garder l'interface utilisable. |

## Chronologie

Réglages pour la vue chronologie chronologique :

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `photos_per_group` | `30` | Nombre de photos chargées par groupe de date dans la vue chronologie. Des valeurs plus élevées affichent plus de photos par date mais alourdissent la page. |

## Carte

Réglages pour la vue carte interactive :

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Niveau de zoom auquel les marqueurs individuels remplacent les groupes. Des valeurs plus basses affichent les marqueurs individuels plus tôt (plus de détail à un zoom plus large). Plage : 1 (monde) à 18 (rue). |

## Traduction

Réglages pour la traduction des légendes IA via MarianMT :

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `target_language` | `"fr"` | Code de langue cible pour `--translate-captions`. Pris en charge : `fr` (français), `de` (allemand), `es` (espagnol), `it` (italien). Utilise les modèles MarianMT Helsinki-NLP (CPU, aucun GPU requis). |

## CLIP esthétique (R2)

Score esthétique supplémentaire dérivé des embeddings CLIP/SigLIP mis en cache via projection textuelle. Les invites sont ajustables par l'utilisateur pour le benchmarking AVA — voir `scripts/benchmark_aesthetic.py` pour mesurer l'impact SRCC de tout changement.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Les tableaux vides retombent sur les valeurs par défaut du module intégrées dans `analyzers/aesthetic_clip.py`. N'ajustez pas ces valeurs sans relancer le benchmark AVA — les valeurs par défaut obtiennent un SRCC ~0,52 sur `ava_test/` et des changements peuvent facilement régresser à ~0,30.

## Ajouter des modèles VLM d'étiquetage / critique alternatifs (R3)

La clé `tagging_model` de chaque profil VRAM (ex : `qwen3.5-2b`) renvoie à une entrée de modèle dans la même section `models`. Pour expérimenter avec un VLM différent (Pixtral-12B, InternVL-2.5, etc.) :

1. Ajoutez une entrée de modèle sous `models` :
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Pointez un profil vers celui-ci :
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Lancez `python facet.py --recompute-tags-vlm` pour réétiqueter.

Aucun changement de code requis. Validez la qualité via un contrôle ponctuel côte à côte sur ~30 photos avant de promouvoir en tant que valeur par défaut.

## Secret de partage

Chaîne hexadécimale de 64 caractères auto-générée pour les jetons de session/partage :

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Générée automatiquement au premier lancement si absente.
