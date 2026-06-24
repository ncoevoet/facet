# Système de scoring

> 🌐 [English](../SCORING.md) · **Français** · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md)

Les photos sont classées dans une catégorie, puis notées avec les poids de cette catégorie.

## Fonctionnement du scoring

1. **Détection de la catégorie** - La photo est analysée pour son contenu (visages, tags, données EXIF)
2. **Évaluation des filtres** - Les catégories sont évaluées par ordre de priorité jusqu'à ce qu'une corresponde
3. **Application des poids** - Les poids spécifiques à la catégorie sont appliqués aux métriques
4. **Application des modificateurs** - Bonus, pénalités et indicateurs de comportement appliqués
5. **Score final** - Somme pondérée bornée à la plage 0-10

## Catégories

`scoring_config.json` définit 34 catégories (33 nommées plus `default`), évaluées par ordre de priorité croissant jusqu'à ce qu'une corresponde. La priorité la plus basse l'emporte. La liste complète figure dans le tableau `categories` ; voici les principales :

| Priorité | Catégorie | Méthode de détection |
|----------|----------|------------------|
| 8 | `art` | Tags : painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags : aurora, astrophotography, stars, milky way |
| 15 | `concert` | Tags : concert |
| 35 | `group_portrait` | Ratio visage ≥ 5 % ET is_group_portrait |
| 42 | `silhouette` | Présence d'un visage ET is_silhouette |
| 45 | `portrait` | Ratio visage ≥ 5 %, ni silhouette/groupe/mono |
| 46 | `portrait_bw` | Portrait monochrome (visage ≥ 5 %) |
| 55 | `macro` | Tags : macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Tags : animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Obturation 1-10 secondes |
| 85 | `night` | Luminance < 0,15 |
| 88 | `monochrome` | is_monochrome (saturation < 5 %) |
| 95 | `street` | Tags : street, urban_culture |
| 96 | `human_others` | Présence d'un visage ET ratio visage < 5 % |
| 100 | `landscape` | Tags : landscape, mountain, beach, forest, ... |
| 999 | `default` | Repli (aucun filtre) |

Les autres catégories basées sur les tags incluent `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic` et `weather`.

## Définition d'une catégorie

Chaque catégorie dans `scoring_config.json` comporte ces composants :

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
  },
  "tags": {}
}
```

## Référence des filtres

### Filtres de plage numérique

| Filtre | Champ | Description |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Surface du visage en fraction (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Nombre de visages |
| `iso_min` / `iso_max` | `ISO` | ISO de l'appareil |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Temps d'exposition (secondes) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Luminosité (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Longueur focale (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Ouverture (nombre f) |

### Filtres booléens

| Filtre | Description |
|--------|-------------|
| `has_face` | Au moins un visage détecté |
| `is_monochrome` | Saturation < 5 % |
| `is_silhouette` | Contre-jour avec ombres/hautes lumières marquées |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, défaut : 4) |

### Filtres de tags

| Filtre | Description |
|--------|-------------|
| `required_tags` | Liste des tags que la photo doit posséder |
| `excluded_tags` | Liste des tags que la photo ne doit PAS posséder |
| `tag_match_mode` | `"any"` (défaut) ou `"all"` |

## Clés de poids

Tous les poids utilisent le suffixe `_percent`. Ils sont normalisés par `get_weights()`, donc les totaux n'ont pas besoin de valoir exactement 100 — mais les maintenir à 100 conserve les scores sur l'échelle 0-10.

| Clé | Métrique | Source | Idéale pour |
|-----|--------|--------|----------|
| `aesthetic_percent` | Attrait visuel | TOPIQ ou CLIP+MLP | Toutes |
| `quality_percent` | Qualité (héritée) | Redistribuée dans `aesthetic` (pas de signal distinct) | — |
| `face_quality_percent` | Netteté du visage | InsightFace | Portraits |
| `eye_sharpness_percent` | Netteté des yeux | Points de repère InsightFace | Portraits |
| `tech_sharpness_percent` | Netteté globale | Variance laplacienne | Paysages |
| `composition_percent` | Composition | SAMP-Net ou règles | Toutes |
| `exposure_percent` | Équilibre de l'exposition | Analyse d'histogramme | Toutes |
| `color_percent` | Harmonie des couleurs | Analyse HSV | Photos couleur |
| `contrast_percent` | Contraste tonal | Étendue de l'histogramme | N&B |
| `dynamic_range_percent` | Plage tonale | Analyse d'histogramme | HDR, paysages |
| `isolation_percent` | Séparation du sujet | Visage vs arrière-plan | Portraits, faune |
| `leading_lines_percent` | Lignes directrices | Détection de contours | Architecture |
| `power_point_percent` | Règle des tiers | Placement du sujet | Toutes |
| `saturation_percent` | Saturation des couleurs | Analyse HSV | Photos vives |
| `noise_percent` | Niveau de bruit | Estimation du bruit | Basse lumière |
| `face_sharpness_percent` | Netteté de la zone du visage | Analyse du visage | Portraits |
| `aesthetic_iaa_percent` | Mérite esthétique artistique | TOPIQ IAA (entraîné sur AVA) | Art, créatif |
| `face_quality_iqa_percent` | Qualité du visage (IQA) | TOPIQ NR-Face | Portraits |
| `liqe_percent` | Score de qualité LIQE | LIQE | Diagnostics |
| `subject_sharpness_percent` | Netteté de la zone du sujet | BiRefNet + Laplacien | Portraits, faune |
| `subject_prominence_percent` | Ratio de surface du sujet | BiRefNet | Macro, faune |
| `subject_placement_percent` | Règle des tiers du sujet | BiRefNet | Toutes |
| `bg_separation_percent` | Séparation de l'arrière-plan | BiRefNet | Portraits, macro |

## Modificateurs

Ajustent le comportement de scoring par catégorie :

| Modificateur | Type | Description |
|----------|------|-------------|
| `bonus` | float | Ajouté au score final (ex. 0.5) |
| `noise_tolerance_multiplier` | float | Échelle de la pénalité de bruit (0.5 = moitié) |
| `iso_tolerance_multiplier` | float | Échelle de la pénalité ISO |
| `min_saturation_bonus` | float | Bonus pour une saturation élevée |
| `contrast_bonus` | float | Bonus pour un contraste élevé |
| `_skip_clipping_penalty` | bool | Ignore la pénalité d'écrêtage de l'exposition |
| `_skip_oversaturation_penalty` | bool | Ignore la pénalité de sursaturation |
| `_clipping_multiplier` | float | Échelle de la pénalité d'écrêtage |
| `_apply_blink_penalty` | bool | Applique la pénalité de détection de clignement |

## Dimensions de la saillance du sujet

Quatre dimensions dérivées de la segmentation du sujet par BiRefNet :

| Clé de poids | Métrique | Description |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Netteté du sujet | Qualité de mise au point de la zone du sujet par rapport à l'arrière-plan. Élevée = sujet net, arrière-plan flou. |
| `subject_prominence_percent` | Proéminence du sujet | Surface du sujet en fraction du cadre. Élevée pour la macro et les sujets cadrés serré, faible pour les scènes larges. |
| `subject_placement_percent` | Placement du sujet | Score de règle des tiers pour le centre de masse du sujet. |
| `bg_separation_percent` | Séparation de l'arrière-plan | Différence de gradient de contour à la frontière du sujet (qualité du bokeh). |

Utilisez `subject_sharpness_percent` et `bg_separation_percent` pour le portrait/la faune ; `subject_prominence_percent` pour la macro.

## Dimensions IQA supplémentaires

Trois modèles de qualité additionnels :

| Clé de poids | Modèle | Description |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérite esthétique entraîné sur AVA, distinct du score esthétique de qualité technique. Idéal pour les catégories art/créatif. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Évaluation de la qualité de la zone du visage. Idéal pour les catégories portrait. |
| `liqe_percent` | LIQE | Score de qualité accompagné d'un diagnostic de distorsion (flou de bougé, surexposition, bruit). |

Ces modèles s'exécutent dans le cadre du pipeline de scoring par défaut et partagent la VRAM avec TOPIQ. Ajoutez leurs clés de poids à toute catégorie où l'évaluation est utile.

### Signaux supplémentaires (hors agrégat par défaut)

| Colonne | Source | Description |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP en cache | Un score esthétique supplémentaire gratuit (0-10) dérivé des embeddings d'image en cache par projection sur un « axe esthétique » construit à partir de prompts texte positifs/négatifs. Aucune inférence d'image supplémentaire au moment du scan. **Ne fait pas** partie de l'`aggregate` par défaut. À renseigner avec `python scripts/compute_aesthetic_clip.py --db <path>`. À évaluer avec `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. SRCC AVA ≈ 0,52 sur le jeu de 500 photos `ava_test/` (contre 0,94 pour `aesthetic_iaa`) — utile comme pré-filtre bon marché ou lorsque TOPIQ-IAA n'est pas disponible. |

## Tags de catégorie (vocabulaire CLIP)

Les tags déclenchent les catégories basées sur les tags et sont mis en correspondance via la similarité CLIP :

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Chaque clé est le nom canonique du tag, et le tableau contient les synonymes pour la correspondance CLIP.

## Scoring des Meilleurs choix

Le filtre « Meilleurs choix » de la galerie utilise un score pondéré personnalisé :

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Calcul du score :**
- Avec visage (ratio visage ≥ 20 %) : les quatre métriques contribuent
- Sans visage : `face_quality_percent` redistribué vers `aesthetic` et `composition`

## Considérations selon le profil VRAM

Les poids par défaut sont optimisés pour **TOPIQ** (SRCC 0,93), le modèle esthétique de tous les profils.

| Profil | Modèle esthétique | Embeddings | Tagger | Recommandations |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (SRCC 0,93) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Meilleure précision, poids par défaut |
| `16gb` | TOPIQ (SRCC 0,93) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Poids par défaut |
| `8gb` | CLIP+MLP (SRCC 0,76) | CLIP ViT-L-14 | Similarité CLIP | Les poids par défaut fonctionnent bien |
| `legacy` | CLIP+MLP sur CPU | CLIP ViT-L-14 | Similarité CLIP | Poids par défaut, plus lent |

Tous les profils exécutent en plus les modèles PyIQA supplémentaires (TOPIQ IAA, TOPIQ NR-Face, LIQE) et, en option, BiRefNet_dynamic pour la saillance du sujet.

Exécutez `--compute-recommendations` après avoir changé de profil pour analyser les distributions de scores.

## Flux de réglage des poids

### Option A : via la galerie (recommandée)

1. Ouvrez `/stats` → onglet **Catégories** → sous-onglet **Poids**
2. Déverrouillez le mode édition
3. Sélectionnez une catégorie dans le menu déroulant de l'éditeur
4. Ajustez les curseurs — l'**aperçu de la distribution des scores** en direct montre l'impact estimé
5. Cliquez sur **Enregistrer** puis **Recalculer les scores** pour appliquer

La galerie exécute `--recompute-category` en coulisse, ne mettant à jour que les photos de cette catégorie.

### Option B : via la CLI

#### 1. Analyser les scores actuels

```bash
python facet.py --compute-recommendations
```

Affiche :
- Les distributions de scores par catégorie
- L'analyse de corrélation des poids
- Les ajustements suggérés

#### 2. Ajuster les poids

Modifiez les poids de catégorie dans `scoring_config.json`. Assurez-vous qu'ils totalisent 100.

#### 3. Recalculer les scores

```bash
python facet.py --recompute-average               # Toutes les catégories
python facet.py --recompute-category portrait      # Une seule catégorie (plus rapide)
```

Utilise les embeddings stockés — aucun GPU nécessaire.

#### 4. Valider les changements

```bash
python facet.py --compute-recommendations
```

Comparez les distributions avant/après.

## Mode de comparaison par paires

Entraînez les poids en comparant des paires de photos :

### Mise en place

1. Définissez un `edition_password` non vide dans la config : `"viewer": { "edition_password": "your-password" }`
2. Démarrez la galerie : `python viewer.py`
3. Cliquez sur le bouton « Comparer »

### Interface de comparaison

- Photos côte à côte
- Clavier : A (gauche gagne), B (droite gagne), T (égalité), S (passer)
- La barre de progression montre les comparaisons par rapport au minimum de 50

### Sources de comparaison

Les comparaisons portent un marqueur `source` afin que l'optimiseur puisse les pondérer selon leur fiabilité :

- `vote` — votes A/B explicites depuis l'interface de comparaison
- `culling` — dérivés automatiquement des décisions de tri de rafales/photos similaires : chaque
  photo rejetée est appariée à un maximum de deux photos conservées du même groupe
  (plafonné à 12 paires par groupe). Les photos conservées gagnent. Les votes explicites sur la même
  paire ne sont jamais écrasés.
- `rating` — paires synthétiques générées à partir des notes en étoiles et des favoris

Examiner les groupes de rafales dans la galerie enrichit donc le jeu d'entraînement pour
l'optimisation des poids sans aucun effort supplémentaire.

### Optimisation des poids

```bash
# Vérifier les statistiques de comparaison
python facet.py --comparison-stats

# Optimiser les poids à partir des comparaisons (appliqués seulement si cela généralise)
python facet.py --optimize-weights --optimize-category portrait

# Restreindre les données d'entraînement à des sources spécifiques
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Appliquer même si le seuil de validation tenue à l'écart n'est pas atteint
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Appliquer à toutes les photos
python facet.py --recompute-average
```

### Pipeline étiquette-vers-poids

Au-delà des votes A/B explicites, deux autres flux d'étiquettes alimentent l'optimiseur :

1. **Les décisions de tri** sont capturées automatiquement à chaque
   confirmation de rafale/similaires (`source='culling'`).
2. **Les notes en étoiles, favoris et rejets** sont matérialisés en paires
   synthétiques avec `python facet.py --sync-label-comparisons` (`source='rating'`).
   Une nouvelle exécution resynchronise à partir des étiquettes actuelles, de sorte que les notes retirées disparaissent.

L'optimiseur pondère chaque source selon sa fiabilité (vote 1.0, rating 0.7,
culling 0.5) lors de la maximisation de la vraisemblance de Bradley-Terry. Il s'entraîne sur le
vecteur de métriques 0-10 exact utilisé par le scorer (y compris `liqe`, `aesthetic_iaa`,
`face_quality_iqa` et les métriques de saillance du sujet), de sorte que les poids optimisés correspondent
directement au scoring de production.

Les poids ne sont **appliqués que s'ils généralisent** : les poids finaux sont ajustés sur
toutes les comparaisons, mais la décision de les écrire est conditionnée à la précision en
validation croisée k-fold tenue à l'écart, et non à la précision d'entraînement. Si le gain tenu à l'écart par rapport aux poids actuels
est inférieur au seuil (défaut 2 pp), l'exécution rapporte les chiffres et n'écrit
rien — passez `--optimize-force` pour passer outre. L'optimisation est par catégorie et
nécessite des comparaisons étiquetées **pour cette catégorie** ; les catégories sans vote
ne peuvent pas être réglées à partir des données.

Cadence recommandée :

```bash
python facet.py --mine-insights          # quel signal existe, dérive, santé
python facet.py --sync-label-comparisons # rafraîchir les paires dérivées des notes
python facet.py --optimize-weights       # apprendre les poids de toutes les sources
python facet.py --recompute-average      # appliquer + persister l'instantané de percentiles
```

### Réglage des poids dans l'interface

1. Ouvrez le panneau d'aperçu des poids pendant la comparaison
2. Ajustez les curseurs pour voir les changements de score en temps réel
3. Cliquez sur « Suggérer les poids » pour les valeurs optimisées
4. Mettez à jour la config manuellement

## Ajouter des catégories personnalisées

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

Ajoutez-la au tableau `categories` dans `scoring_config.json`, puis exécutez `--recompute-average` (ou `--recompute-category underwater` pour la nouvelle catégorie uniquement).

## Exemples de flux de travail

### Régler la catégorie Concert

```bash
# Modifier scoring_config.json :
# Trouver la catégorie "concert", ajuster :
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

Ou utilisez l'éditeur de poids de la galerie sous `/stats` → Catégories → Poids pour un aperçu en direct et un recalcul en un clic.

### Passer au profil 8gb

```bash
# Modifier : "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analyser
# Réduire aesthetic_percent dans les catégories si nécessaire
python facet.py --recompute-average
```

### Ajouter la catégorie Underwater

1. Ajoutez la définition de catégorie (voir ci-dessus)
2. Exécutez `python facet.py --validate-categories`
3. Exécutez `python facet.py --recompute-average`
