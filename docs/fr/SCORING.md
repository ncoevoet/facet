# Système de scoring

> 🌐 [English](../SCORING.md) · **Français** · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · [Português](../pt/SCORING.md) · [简体中文](../zh/SCORING.md)

Les photos sont classées dans une catégorie, puis notées avec les poids de cette catégorie.

Les valeurs absentes ou NULL de subject_sharpness, subject_prominence, subject_placement, bg_separation et face_quality_iqa sont exclues du score pondéré. Leur poids positif est redistribué aux métriques disponibles ; zéro reste valide. Si toutes les entrées pondérées manquent, la valeur neutre est 5.0. Les exclusions de licence passent en premier. Les poids livrés restent inchangés. `--optimize-weights` laisse un poids inchangé lorsque l’ensemble de comparaisons n’a aucune valeur pour cette métrique. Pour renseigner la saillance, exécutez `--recompute-saliency`, puis `--recompute-average`.

## Fonctionnement du scoring

1. **Détection de la catégorie** - La photo est analysée pour son contenu (visages, tags, données EXIF)
2. **Évaluation des filtres** - Les catégories sont évaluées par ordre de priorité jusqu'à ce qu'une corresponde (un [contexte de notation](#contextes-de-notation) peut modifier cet ordre par album ou par photo)
3. **Application des poids** - Les poids spécifiques à la catégorie sont appliqués aux métriques
4. **Application des modificateurs** - Bonus, pénalités et indicateurs de comportement appliqués
5. **Score final** - Somme pondérée bornée à la plage 0-10

## Catégories

`scoring_config.json` définit 34 catégories (33 nommées plus `default`), évaluées par ordre de priorité croissant jusqu'à ce qu'une corresponde. La priorité la plus basse l'emporte. La liste complète figure dans le tableau `categories` ; voici les principales :

| Priorité | Catégorie | Méthode de détection |
|----------|----------|------------------|
| 8 | `art` | Tags : painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags : aurora, astrophotography, stars, milky way, ET luminance moyenne ≤ 0.30 |
| 15 | `concert` | Tags : concert |
| 35 | `group_portrait` | Ratio visage ≥ 5 % ET is_group_portrait |
| 42 | `silhouette` | A un visage ET `is_silhouette` (le plus grand visage est sombre sur un environnement plus clair) |
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

Sur les profils à étiquetage CLIP (`legacy`/`8gb`, et `16gb`/`24gb` quand leur tagger VLM ne s'exécute pas), un scan étiquette chaque photo avant de calculer sa catégorie : la catégorie stockée utilise donc les étiquettes. Une exécution avec un seul `--pass NAME` n'étiquette pas.

**Silhouette.** `is_silhouette` provient d'une règle de pixels fondée sur le visage (voir [Filtres booléens](#filtres-booléens)), pas d'une étiquette.

- Quand `exposure.silhouette_detection` vaut `true` (valeur par défaut), l'agrégat d'une silhouette ignore la pénalité d'écrêtage.
- Un scan stocke `exposure_score` avec la pénalité d'écrêtage. `--recompute-average` le recalcule sans elle pour toute photo marquée `is_silhouette`, quelle que soit la valeur de `exposure.silhouette_detection`.
- Pour recalculer les drapeaux d'une bibliothèque existante, lancez `python facet.py --recompute-silhouette`, puis `--recompute-average` deux fois (voir [COMMANDS.md](COMMANDS.md)).

**Astro.** Une photo doit avoir une étiquette astro *et* une luminance moyenne d'au plus 0.30 (`luminance_max`). Une scène lumineuse étiquetée `aurora` ou `stars` n'est pas astro, et une photo sans luminance stockée ne correspond jamais. Si votre `scoring_config.json` a son propre tableau `categories`, ajoutez vous-même `"luminance_max": 0.30` à `astro.filters` ; `python facet.py --doctor` vous prévient quand il manque.

## Contextes de notation

Un **contexte de notation** change l'ordre des catégories pour certaines photos sans toucher aux priorités globales. Il promeut quelques catégories en tête et en exclut d'autres. `default` (`promote`/`excluded` vides) ne change rien, et les photos l'utilisent tant que vous n'en attribuez pas un autre.

**Ordre effectif** = `promote` (dans l'ordre donné) → l'ordre de priorité global, moins les noms promus et exclus → `default` en dernier. Un nom présent à la fois dans `promote` et dans `excluded` est retiré : `excluded` l'emporte.

Préréglages livrés, modifiables depuis l'onglet **Contexte de notation** de la visionneuse ou dans le JSON (référence des champs : [Contextes de notation](CONFIGURATION.md#contextes-de-notation)) :

| Contexte | Promeut | Exclut |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Vous ne modifiez que la liste des catégories promues (mode édition ; glisser, ou monter/descendre) et les exclusions. Les autres catégories conservent toujours l'ordre global, si bien qu'une catégorie ajoutée plus tard ne manque jamais dans un contexte. Règles de validation : [Modifier un contexte](CONFIGURATION.md#modifier-un-contexte).

**Attribuer un contexte :**

- **Par album.** S'applique à chaque photo présente dans l'album à cet instant. C'est un instantané, une fois pour toutes : les photos ajoutées plus tard à un album intelligent ne le reçoivent pas. Voir [Contextes de notation](CONFIGURATION.md#contextes-de-notation).
- **Par photo.** Un remplacement de catégorie persistant pour une seule photo.

Les deux survivent aux nouveaux scans et peuvent être réinitialisés séparément.

**Aucun des deux ne prend effet sur des photos déjà notées avant un recalcul :** lancez `python facet.py --recompute-average`, ou recalculez depuis la visionneuse (voir [Modifier les priorités nécessite un recalcul](CONFIGURATION.md#réorganiser-la-priorité-globale)). Si `normalization.per_category` est activé, lancez-le deux fois (voir [Normalisation](CONFIGURATION.md#normalisation)).

### Le piège des données EXIF manquantes

Réorganiser ne change que la catégorie *essayée en premier*. Cela ne peut pas faire correspondre les filtres d'une catégorie. Un filtre de plage numérique échoue quand la valeur de la photo est manquante ou illisible, exactement comme si elle était hors plage.

Exemple : `sports` (priorité 71) porte `shutter_speed_max: 0.02`. Une photo de danse prise à une vitesse plus lente que 1/50s, ou sans vitesse d'obturation lisible, échoue à ce filtre même quand `action_stage` promeut `sports` en tête. Elle retombe sur la catégorie suivante qui correspond, typiquement `fashion` (priorité 43, taguée `fashion`, contient un visage) ou `silhouette` (priorité 42, contre-jour avec un visage).

**Quand une photo atterrit dans une catégorie inattendue, vérifiez d'abord ceci :** les filtres numériques de la catégorie visée peuvent-ils correspondre aux données EXIF stockées de la photo, et pas seulement à ses tags ?

### Le piège du tag manquant

`required_tags` échoue de la même façon : un filtre ne peut pas correspondre à un tag absent du vocabulaire. Les `required_tags` de `sports` sont `sports`, `motion`, `athlete`, `competition`, `action_sport` et `dance`.

`sports.tags.dance` porte 11 prompts CLIP (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), et `dance` figure dans `sports.filters.required_tags`. Une photo de danse taguée peut atteindre `sports`, mais une photo à vitesse lente ou sans EXIF échoue quand même à `shutter_speed_max: 0.02`.

**Les photos existantes conservent leurs tags.** Un changement de vocabulaire n'affecte que les nouveaux étiquetages ; lancez `python facet.py --recompute-tags` pour l'appliquer à la bibliothèque.

### Réorganiser la priorité globale

Vous pouvez réorganiser la priorité globale dans la visionneuse (mode édition). La réorganisation permute les numéros de priorité existants entre les catégories au lieu de les renuméroter, si bien que les nombres du tableau ci-dessus restent pertinents. `default` (priorité 999) reste toujours en dernier. Chaque écriture prend d'abord une copie horodatée `.backup.<timestamp>` de `scoring_config.json`.

Réorganiser ne change la `category` stockée d'aucune photo : lancez un recalcul ensuite.

**Limitation connue :** la liste déroulante de type de la galerie conserve son ancien ordre jusqu'au redémarrage de la visionneuse. La correspondance et le filtrage utilisent immédiatement le nouvel ordre.

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
| `is_silhouette` | Le plus grand visage est sombre sur un environnement clair (voir ci-dessous). Une photo sans visage n'est jamais une silhouette |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurable, défaut : 4) |

**Règle `is_silhouette`.** La luminosité moyenne (luma, 0-1) des 60 % centraux du cadre du visage est inférieure à 0.12, et la bande autour du cadre (de 0.2 à 0.75 de la taille du cadre vers l'extérieur de chaque côté, rognée à l'image) est plus claire de plus de 0.20. Ni l'étiquette CLIP `silhouette` ni l'histogramme de l'image entière ne le définissent.

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
| `quality_percent` | Qualité héritée | Ajouté à `aesthetic_percent` avant le calcul (pas de signal distinct) | — |
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

**`quality_percent` compte dans `aesthetic`.** La métrique de qualité n'a pas de score propre : le `quality_percent` d'une catégorie est donc redistribué dans `aesthetic` ; il est ajouté à `aesthetic_percent` avant le calcul, et les poids totalisent toujours 100. Les versions précédentes perdaient cette part dans l'agrégat ; lancez `--recompute-average` une fois après la mise à jour pour la retrouver. Les catégories ne changent pas.

## Modificateurs

Ajustent le comportement de scoring par catégorie :

| Modificateur | Type | Description |
|----------|------|-------------|
| `bonus` | float | Ajouté au score final (ex. 0.5) |
| `noise_tolerance_multiplier` | float | Échelle de la pénalité de bruit (0.5 = moitié) |
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

**Pas de sujet, pas de nombre.** Quand aucun sujet n'est trouvé, `subject_sharpness`, `subject_placement` et `bg_separation` sont stockés NULL (tout comme `power_point_score` quand il n'y a pas de cadre de sujet), `subject_prominence` vaut 0.0 et `subject_bbox` est NULL.

- Les filtres de plage de la galerie ignorent un NULL (`min_subject_sharpness=0` ne renvoie pas une photo sans sujet). Les statistiques l'excluent des moyennes, et l'interface l'affiche comme absent.
- Les entrées de saillance NULL suivent la règle des valeurs manquantes ci-dessus ; les poids livrés restent inchangés.
- Les versions précédentes stockaient un 5.0 neutre. Les lignes existantes le gardent jusqu'à ce que `--recompute-saliency` et `--recompute-composition-cpu` les réécrivent.

**Quand la saillance échoue**, rien n'est écrit ; Facet ne stocke jamais un nombre neutre pour un résultat en échec. Une photo jamais notée garde NULL dans les cinq colonnes de saillance (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`), comme une photo scannée avant l'existence de la saillance. Règles de reprise et de taille de lot : [Saillance du sujet](COMMANDS.md#saillance-du-sujet).

## Dimensions IQA supplémentaires

Trois modèles de qualité additionnels :

| Clé de poids | Modèle | Description |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérite esthétique entraîné sur AVA, distinct du score esthétique de qualité technique. Idéal pour les catégories art/créatif. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Évaluation de la qualité de la zone du visage. Idéal pour les catégories portrait. |
| `liqe_percent` | LIQE | Score de qualité accompagné d'un diagnostic de distorsion (flou de bougé, surexposition, bruit). |

Ces modèles s'exécutent dans le cadre du pipeline de scoring par défaut sur chaque profil, y compris le profil `legacy` sur CPU (plus lent), et partagent la VRAM avec TOPIQ sur un GPU. Ajoutez leurs clés de poids à toute catégorie où l'évaluation est utile.

**Quand un modèle supplémentaire ne peut pas noter une photo**, il stocke NULL dans la colonne de ce modèle (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) au lieu d'un 5,0 neutre. Cela se produit quand TOPIQ NR-Face ne trouve aucun visage, ou quand le petit côté de l'image pour LIQE est inférieur à 224 px ; Aesthetic V2.5, s'il est activé, peut échouer sur n'importe quelle image. Une erreur de mémoire du CPU n'est pas retentée avec une taille de lot plus petite.

- Un face_quality_iqa NULL suit la règle ci-dessus ; les autres entrées supplémentaires NULL restent imputées à la valeur neutre 5,0.
- **Galerie :** un filtre de plage sur Esthétique (IAA), Qualité du visage (IQA), LIQE ou Aesthetic V2.5 ne retient pas une photo sans score (`min_face_quality_iqa=0` écarte une photo sans visage). Un tri croissant sur ces colonnes, sur Q-ReAlign ou sur DeQA place les photos sans score en dernier, dans la galerie comme dans les albums.
- **Anciennes valeurs neutres de 5,0 :** elles restent tant que `--repair-neutral-iqa` ne les a pas effacées ; lancez ensuite `--recompute-iqa` puis `--recompute-average`, ou rescannez avec `--force`.
- **Échec du modèle principal** (TOPIQ sur `16gb` et `24gb`) : la photo est enregistrée comme échouée au lieu d'être sauvegardée avec un 5,0 neutre. Une nouvelle photo est reprise par le scan suivant ; une photo déjà stockée garde sa ligne et est retentée par `--retry-failed all` (un `--retry-failed` sans argument ne couvre que le dernier scan ayant enregistré des échecs) ou par un nouveau scan avec `--force`.

Règles de reprise de chaque commande : [Modèles de qualité supplémentaires](COMMANDS.md#modèles-de-qualité-supplémentaires).

### Signaux supplémentaires (hors agrégat par défaut)

| Colonne | Source | Description |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP en cache | Score esthétique gratuit (0-10) dérivé des embeddings en cache ; **ne fait pas** partie de l'`aggregate` par défaut |

`aesthetic_clip` projette l'embedding de chaque image sur un « axe esthétique » construit à partir de prompts texte, et n'exige donc aucune inférence d'image supplémentaire.

- Renseignez-le avec `python scripts/compute_aesthetic_clip.py --db <path>`.
- Évaluez-le avec `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- SRCC AVA ≈ 0,52 sur le jeu de 500 photos `ava_test/` (contre 0,94 pour `aesthetic_iaa`). Utilisez-le comme pré-filtre bon marché ou lorsque TOPIQ-IAA n'est pas disponible.

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

Le filtre « Meilleurs choix » de la galerie utilise un score pondéré personnalisé :

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Calcul du score :**
- Avec visage (face_ratio ≥ 20 %) : les quatre métriques contribuent
- Sans visage : `face_quality_percent` redistribué à parts égales (moitié chacun) vers `aesthetic` et `composition` (avec les poids par défaut : aesthetic 0.40, composition 0.30)

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

Un assistant MCP peut lire ces pondérations et simuler un changement sans rien modifier : `explain_score` (pourquoi une photo a obtenu son score), `category_weights` et `preview_weights` (une simulation approximative avec les changements de rang). Voir [Scores et pondérations](AGENTS.md#scores-et-pondérations).

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
3. Cliquez sur le bouton « Comparer »

### Interface de comparaison

- Photos côte à côte
- Clavier : ← (gauche gagne), → (droite gagne), T (égalité), S (passer). Les boutons à l'écran sont libellés **A** / **B**.
- La barre de progression montre les comparaisons par rapport au minimum de 50

### Sources de comparaison

Les comparaisons portent un marqueur `source` afin que l'optimiseur puisse les pondérer selon leur fiabilité :

- `vote` — votes A/B explicites depuis l'interface de comparaison
- `culling` — dérivés automatiquement des décisions de tri de rafales/photos similaires : chaque
  photo rejetée est appariée à un maximum de deux photos conservées du même groupe
  (plafonné à 12 paires par groupe). Les photos conservées gagnent. Les votes explicites sur la même
  paire ne sont jamais écrasés.
- `rating` — paires synthétiques générées à partir des notes en étoiles et des favoris

Examiner les groupes de rafales dans la galerie enrichit donc aussi le jeu d'entraînement.

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

**Comment fonctionne l'ajustement.** L'optimiseur cherche les poids qui prédisent le mieux le gagnant de chaque comparaison (un modèle de Bradley-Terry).

- Les sources comptent selon leur fiabilité : vote 1.0, rating 0.7, culling 0.5.
- Une **égalité** compte comme une demi-victoire plus une demi-défaite.
- L'ajustement est **ancré sur vos poids actuels** : avec peu de comparaisons, il reste proche d'eux.
- Il utilise les mêmes métriques 0-10 que l'agrégat (y compris `liqe`, `aesthetic_iaa`, `face_quality_iqa` et la saillance du sujet), avec netteté des yeux, netteté technique et couleur normalisées par les percentiles enregistrés par le dernier `--recompute-average`.
- `quality_percent` est replié dans `aesthetic`, comme le fait le scoreur ; l'application écrit `quality_percent: 0`.

**Les poids ne sont appliqués que s'ils se généralisent.** La décision repose sur des comparaisons réservées : validation croisée à 5 plis avec des **plis groupés par photo** (aucune photo n'est à la fois dans les paires d'entraînement et dans les paires réservées).

- Un **test exact de McNemar unilatéral** vérifie si les nouveaux poids gagnent significativement plus des paires sur lesquelles les deux jeux de poids divergent.
- Les poids ne sont appliqués que si `p < 0.05` **et** que le gain réservé est d'au moins 2 points de pourcentage. Sinon l'exécution consigne les chiffres et n'écrit rien.
- Passez `--optimize-force` pour appliquer quand même. Si le test ne peut pas s'exécuter (trop peu de groupes de photos indépendants), rien n'est appliqué sauf si vous forcez.
- Chaque catégorie exige au moins 30 comparaisons **décisives** (une photo l'a emporté) **dans cette catégorie**. Les égalités et les autres catégories ne comptent pas.

Exemple de journal :

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**Appliquer conserve le niveau de la catégorie.** `--optimize-weights` change la façon dont les photos d'une catégorie se classent entre elles, pas face aux autres catégories. Il décale `modifiers.bonus` pour annuler le décalage moyen du score de la catégorie.

- Le bonus reste dans [-5, 5] ; le journal indique quand cette limite s'applique.
- Une catégorie sans entrée dans `categories` (`others`) n'a pas de bonus et n'est pas recentrée.
- Restaurer un instantané de poids restaure poids **et** bonus. Les anciens instantanés, ceux de `calibrate.py` et ceux de `others` laissent le bonus intact.
- Le bouton **Appliquer** de la visionneuse et les modifications manuelles dans l'onglet Poids ne recentrent pas le bonus ; seul `--optimize-weights` le fait.

**Après une mise à jour, ré-entraînez le classeur personnel et la tête keeper (`--train-ranker`, `--train-keeper`), puis lancez `--recompute-average`.** Ils lisent désormais la netteté des yeux, la netteté technique et la couleur normalisées par percentiles, et un modèle enregistré par une version précédente ne peut pas détecter le changement.

Cadence recommandée :

```bash
python facet.py --mine-insights          # quel signal existe, dérive, santé
python facet.py --sync-label-comparisons # rafraîchir les paires dérivées des notes
python facet.py --optimize-weights       # apprendre les poids de toutes les sources
python facet.py --recompute-average      # appliquer + persister l'instantané de percentiles
```

### Réglage des poids dans l'interface

Pendant la comparaison, le panneau d'aperçu des poids montre les changements de score au fil des curseurs, et **Suggérer les poids** propose des valeurs optimisées. L'enregistrement et le recalcul fonctionnent comme dans l'[Option A : via la galerie](#option-a-via-la-galerie-recommandée).

**Suggérer les poids** affiche deux chiffres, dans l'onglet Suggestions de poids et dans la barre latérale de la comparaison A/B :

- `accuracy_before` : la fréquence à laquelle les poids actuels prédisent le gagnant des paires étiquetées de cette catégorie.
- `accuracy_after` : la même mesure pour les poids suggérés. Elle est mesurée sur les paires qui ont servi à l'ajustement, elle est donc optimiste.

**Appliquer** n'est proposé que si le même test de McNemar réservé que dans la CLI est franchi (`suggest_changes` est vrai). La validation croisée ne s'exécute que lorsque le gain optimiste atteint 2 points de pourcentage (`?use_cv=true` l'exécute toujours). La visionneuse exige `min_comparisons_for_optimization` (50 par défaut) comparaisons décisives dans la catégorie, là où la CLI en exige 30. En dessous, elle indique « Need at least N decisive comparisons (have K) ».

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
