# Reconnaissance faciale

> 🌐 [English](../FACE_RECOGNITION.md) · **Français** · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md) · [简体中文](../zh/FACE_RECOGNITION.md)

Facet utilise InsightFace pour la détection des visages et HDBSCAN pour regrouper les visages en personnes.

## Vue d'ensemble

1. **Détection** - le modèle InsightFace buffalo_l détecte les visages et extrait des embeddings de 512 dimensions
2. **Regroupement** - HDBSCAN regroupe les embeddings similaires en clusters de personnes
3. **Gestion** - galerie web pour fusionner, renommer et organiser les personnes

## Workflow complet

### Étape 1 : Extraire les visages

Pendant l'analyse des photos, les visages sont extraits automatiquement :

```bash
python facet.py /path/to/photos
```

Pour les photos existantes sans visages :

```bash
python facet.py --extract-faces-gpu-incremental  # Nouvelles photos uniquement
python facet.py --extract-faces-gpu-force        # Toutes les photos (supprime l'existant)
```

### Étape 2 : Regrouper les visages

Regrouper les visages similaires en personnes :

```bash
python facet.py --cluster-faces-incremental  # Préserve les personnes existantes
```

**Modes de regroupement :**

| Commande | Comportement |
|---------|----------|
| `--cluster-faces-incremental` | Préserve toutes les personnes, rattache les nouveaux visages aux existants |
| `--cluster-faces-incremental-named` | Préserve uniquement les personnes nommées |
| `--cluster-faces-force` | Supprime toutes les personnes, re-regroupement complet |

### Étape 3 : Examiner et fusionner

Trouver les clusters de personnes en doublon :

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Plus strict
```

Ouvre le navigateur sur la page des suggestions de fusion.

### Étape 4 : Gestion dans la visionneuse

Le travail restant se déroule dans la visionneuse web, en suivant le pipeline **Extraire → Regrouper → Fusionner → Gérer** :

- **Fusionnez** les clusters en double sur la page Suggestions de fusion.
- **Gérez** les personnes (fusionner, fusion par lot, scinder, masquer, renommer, supprimer) sur la page Gérer les personnes.

Voir [Intégration à la galerie](#intégration-à-la-galerie) pour la référence complète de l'interface.

## Configuration

### Détection des visages

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Paramètre | Défaut | Description |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confiance de détection minimale |
| `min_face_size` | `20` | Taille de visage minimale en pixels (InsightFace uniquement, voir la note) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio pour la détection des clignements |

En mode commercial, le détecteur YuNet utilise des valeurs fixes (confiance 0,7, 30 px) et ignore `min_confidence_percent` et `min_face_size`.

### Regroupement des visages

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Paramètre | Défaut | Description |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Nombre minimal de photos pour créer une personne |
| `min_samples` | `2` | Paramètre min_samples de HDBSCAN |
| `thresholds_by_model` | voir JSON | Par modèle : `auto_merge_distance_percent` et `merge_threshold` (ArcFace `15` / `0.6`, SFace `27.5` / `0.65`) |
| `use_gpu` | `"auto"` | Mode GPU : `auto`, `always`, `never` |

### Traitement des visages

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
    "refill_batch_size": 100
  }
}
```

## Algorithmes de regroupement

Pour le regroupement sur CPU, choisissez l'algorithme en fonction de la taille du jeu de données :

| Algorithme | Complexité | Recommandé pour |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Haute dimension (recommandé pour 50K+ visages) |
| `boruvka_kdtree` | O(n log n) | Données en basse dimension |
| `prims_balltree` | O(n²) | Petits jeux de données, mémoire limitée |
| `prims_kdtree` | O(n²) | Petits jeux de données |
| `best` | Auto | Laisser HDBSCAN décider |

**Note de performance :** pour les grands jeux de données, utilisez `boruvka_balltree`. Avec 80K visages, il s'achève en 2 à 5 minutes, là où les algorithmes exacts peuvent se bloquer.

## Regroupement GPU (cuML)

Pour les grands jeux de données (80K+ visages), le regroupement GPU via RAPIDS cuML est plus rapide que sur CPU.

### Installation

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Configuration

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Mode | Comportement |
|------|----------|
| `"auto"` | Utiliser le GPU si cuML est disponible, repli sur CPU |
| `"always"` | Essayer le GPU, avertir et se replier s'il est indisponible |
| `"never"` | Toujours utiliser le CPU |

**Note :** cuML utilise sa propre implémentation de HDBSCAN. Les paramètres `algorithm` et `leaf_size` ne s'appliquent qu'au regroupement sur CPU.

### Le GPU et le CPU ne produisent pas des groupes identiques

Avec les mêmes visages et les mêmes paramètres, cuML produit un peu plus de groupes, plus petits, que le regroupement CPU (environ 1,1 à 1,2× plus). Qui est groupé avec qui reste à peu près identique, mais le *nombre* de groupes diffère entre une exécution GPU et une exécution CPU.

**cuML n'est pas non plus déterministe.** Deux exécutions GPU sur les mêmes visages donnent des nombres de groupes quasi identiques mais des étiquettes différentes.

- **Les identifiants de personnes ne sont pas reproductibles d'une exécution à l'autre.** Nommez les personnes qui comptent ; les personnes nommées restent stables.
- **Ne comparez pas deux regroupements par étiquette.** Comparez plutôt l'appartenance des visages.

Le regroupement CPU avec un `algorithm` fixe est déterministe pour une même entrée.

### Regroupement et personnes déjà nommées

Tous les modes sauf `--cluster-faces-force` conservent les enregistrements de personnes existants, mais tous recalculent la personne de chaque visage.

- **Les interruptions sont sans danger.** Les changements sont écrits en une seule étape à la fin ; une exécution arrêtée avant cela ne change rien.
- **Modifications dans la visionneuse pendant une exécution.** Un visage que vous réaffectez pendant que l'exécution écrit ses résultats (les dernières secondes) conserve votre choix, et l'exécution journalise combien elle en a ignorés. Un enregistrement envoyé à ce moment attend la fin de l'exécution ; s'il attend plus de 5 s, il est refusé avec « library busy » et doit être répété. Une modification faite plus tôt, pendant que les visages sont encore regroupés, est écrasée.

Un groupe reconstruit est rendu à une personne existante lorsque :

1. son embedding moyen se situe à moins de `merge_threshold` (0,6 cosinus par défaut pour ArcFace, 0,65 pour SFace) du centroïde stocké de cette personne, **ou**
2. au moins la moitié de ses visages appartenaient à cette personne avant l'exécution.

La règle 2 compte pour les personnes photographiées pendant de nombreuses années : leurs visages se découpent en sous-groupes serrés qui se retrouvent loin du centroïde moyen unique. Sans elle, la plupart des visages des personnes nommées ne leur seraient pas rendus.

Comme la règle 2 s'en remet à l'affectation précédente, une erreur ancienne est reconduite. Utilisez `--cluster-faces-force` pour repartir de zéro. Lorsque les visages d'un groupe se répartissent exactement à égalité entre deux personnes, c'est la personne qui possède le visage déjà affecté de plus petit numéro du groupe qui l'emporte.

## Détection des clignements

Utilise l'Eye Aspect Ratio (EAR) calculé à partir des 106 points de repère d'InsightFace.

### Fonctionnement

L'EAR mesure le rapport entre la hauteur et la largeur de l'œil. Lorsque les yeux se ferment, l'EAR descend sous le seuil.

### Configuration

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Un seuil plus bas = détection plus stricte (plus de photos marquées comme clignements).

### Recalculer après un changement de seuil

```bash
python facet.py --recompute-blinks
```

Ne traite que les photos comportant des visages, aucun GPU nécessaire.

## Qualité de visage OFIQ optionnelle (mode commercial)

En mode commercial, le modèle restreint de qualité de visage est indisponible. Comme remplacement optionnel, installez `python-ofiq` (liaisons UNICEF sur OFIQ du BSI, ISO/IEC 29794-5 ; MIT) :

```bash
pip install python-ofiq
```

- Des wheels n'existent que pour Linux x86-64 et macOS arm64 (sous Windows, utilisez WSL2 ou Docker). Il fonctionne avec numpy 2 et OpenCV 4.8+.
- Au premier usage, Facet télécharge les modèles OFIQ (environ 400 Mo, MIT/Apache-2.0, SHA-256 épinglé) dans `pretrained_models/ofiq/`.
- Le score OFIQ (0-100) est divisé par 10 et stocké dans `face_quality_iqa`. La valeur d'une photo est 0,7 x son pire visage + 0,3 x la moyenne.
- Sans `python-ofiq`, la colonne reste NULL et son poids est réparti sur les autres métriques.

## Signaux d'expression par visage (yeux ouverts + sourire)

Chaque visage stocke deux scores de 0 à 10, utilisés par le panneau de visages du tri et les scores au niveau de la photo : `eyes_open_score` (10 = grand ouvert, 0 = complètement fermé) et `smile_score` (5 = neutre, 10 = large sourire, 0 = moue).

Deux moteurs les produisent, sur la même échelle :

1. **Géométrie (toujours disponible).** Calculée à partir des 106 points de repère InsightFace
   stockés : l'Eye Aspect Ratio pour les yeux, le soulèvement des coins de la bouche pour le sourire.
   `--recompute-face-signals` peut les recalculer sans GPU et sans lire d'image.
2. **Blendshapes MediaPipe (optionnel).** Pendant l'analyse et l'extraction des visages, chaque
   recadrage de visage passe par le MediaPipe Face Landmarker, dont les blendshapes
   (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) correspondent aux mêmes échelles. Il lit mieux
   les yeux fermés, les sourires discrets et les têtes tournées, donc sa valeur **remplace**
   la valeur géométrique. Si MediaPipe ou son modèle est absent, ou si le recadrage est trop
   petit, la valeur géométrique est conservée.

### Installer MediaPipe

MediaPipe est optionnel. Installez-le **sans** son `opencv-contrib-python` embarqué,
qui entrerait en conflit avec l'`opencv-python` de Facet (les deux fournissent `cv2`) :

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Ne lancez jamais un simple `pip install mediapipe`.

### Modèle

Le modèle `face_landmarker.task` (~3,6 Mio, Apache-2.0) est téléchargé à la première utilisation
vers `pretrained_models/face_landmarker.task`. Hors ligne, téléchargez-le depuis
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
et placez-le à cet emplacement. Si le téléchargement échoue, Facet avertit une fois et utilise la géométrie.

### Configuration

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled` (défaut `true`) : utiliser les blendshapes quand MediaPipe et le modèle sont
  disponibles. Mettre à `false` pour forcer la géométrie seule.
- `min_crop_size` (défaut `192`) : les visages dont le recadrage rembourré est plus petit que
  cette valeur (px, côté le plus court) utilisent la géométrie plutôt qu'un recadrage agrandi.
- `blink_pose_gate_deg` (défaut `null` = désactivé) : analyseur MediaPipe du mode commercial uniquement. Un visage tourné de plus de ce nombre de degrés (|yaw| ou |pitch|) n'a ni verdict de clignement ni score yeux ouverts / sourire, car une tête tournée ressemble à des yeux fermés. Les tests n'ont trouvé aucun seuil entre 20° et 45° qui améliore les résultats : il est donc désactivé par défaut ; ne le définissez que si votre bibliothèque contient beaucoup de visages très tournés. Doit être un nombre positif. S'applique aux photos nouvellement analysées ; les valeurs `is_blink` existantes ne changent qu'au rescan.

### Recalcul

`--recompute-face-signals` n'utilise que les points de repère stockés : il est **géométrie seule** et
n'exécute pas MediaPipe. Pour rafraîchir les scores MediaPipe, ré-extrayez les visages avec
`--extract-faces-gpu-force`.

## Miniatures de visages

Les miniatures sont stockées dans la base de données pour un affichage rapide.

### Stockage

- Générées pendant l'analyse à partir des images en pleine résolution
- Stockées dans la colonne `faces.face_thumbnail` sous forme de BLOBs JPEG (~5 à 10 Ko chacune)
- Utilisées par le regroupement et la galerie au lieu d'être régénérées

### Régénération

```bash
# Générer les miniatures manquantes
python facet.py --refill-face-thumbnails-incremental

# Régénérer TOUTES les miniatures
python facet.py --refill-face-thumbnails-force
```

Les deux commandes utilisent le traitement parallèle pour plus de rapidité.

## Schéma de base de données

### Table faces

| Colonne | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Clé primaire |
| `photo_path` | TEXT | Clé étrangère vers photos |
| `face_index` | INTEGER | Index au sein de la photo |
| `embedding` | BLOB | Embedding de visage de 512 dimensions |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Coins de la boîte englobante |
| `confidence` | REAL | Confiance de détection |
| `person_id` | INTEGER | Clé étrangère vers persons |
| `face_thumbnail` | BLOB | Miniature JPEG |
| `landmark_2d_106` | BLOB | 106 points de repère (détection des clignements) |
| `embedding_model` | TEXT | Étiquette du modèle de reconnaissance (par défaut `arcface_buffalo_l`) |

### Table persons

| Colonne | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Clé primaire |
| `name` | TEXT | Nom de la personne (NULL = regroupé automatiquement) |
| `representative_face_id` | INTEGER | Meilleur visage pour l'avatar |
| `face_count` | INTEGER | Nombre de visages |
| `centroid` | BLOB | Embedding du centroïde du cluster |
| `auto_clustered` | INTEGER | 1 si généré automatiquement |
| `face_thumbnail` | BLOB | Miniature d'avatar de la personne |
| `is_hidden` | INTEGER | 1 = exclu des filtres/suggestions |

## Modes incrémental et forcé

### Regroupement incrémental

- Préserve toutes les personnes existantes (nommées et regroupées automatiquement)
- Ne regroupe que les nouveaux visages non assignés
- Rattache les nouveaux clusters aux personnes existantes via la similarité de centroïde
- Met à jour les centroïdes après fusion

**À utiliser quand :** vous ajoutez de nouvelles photos à une collection existante

### Regroupement forcé

- Supprime TOUTES les personnes, y compris celles nommées
- Re-regroupement complet à partir de zéro

**À utiliser quand :** vous repartez de zéro ou changez l'algorithme en profondeur

### Regroupement incrémental nommé

- Préserve uniquement les personnes nommées
- Supprime les personnes regroupées automatiquement
- Re-regroupe tous les visages non nommés

**À utiliser quand :** vous conservez des noms organisés tout en rafraîchissant les clusters détectés automatiquement

## Intégration à la galerie

### Filtre par personne

- Le menu déroulant affiche les personnes avec leurs miniatures de visages
- Filtrer la galerie par personne

### Galerie d'une personne

- Cliquez sur une personne dans le menu déroulant pour voir toutes ses photos
- Cliquer sur une personne applique un filtre `person_id` à la galerie (pas de route dédiée par personne)

### Page Gérer les personnes

Accès via le bouton d'en-tête ou `/persons` :

- **Vue en grille** - toutes les personnes reconnues
- **Fusionner** - sélectionnez la source, cliquez sur la cible, confirmez
- **Fusion par lot** - sélectionnez plusieurs personnes et fusionnez-les dans une seule cible
- **Scinder** - déplacez les visages sélectionnés vers une nouvelle personne
- **Masquer** - exclure un cluster de la liste, des filtres et des suggestions de fusion
- **Supprimer** - retirez le cluster de personne
- **Renommer** - cliquez sur le nom pour le modifier en ligne

### Créer une personne

Vous pouvez nommer un visage que le clusterer a manqué directement depuis la galerie :

1. Sur une carte photo, ouvrez les actions de personne et choisissez un visage non assigné.
2. Dans le sélecteur de personne, choisissez **Créer une nouvelle personne** et saisissez un nom.
3. Le visage est rattaché à la nouvelle personne (`auto_clustered = 0`).

Un visage qui appartient déjà à une autre personne est déplacé, et une personne laissée sans visage est supprimée. En mode multi-utilisateur, vous ne pouvez rattacher que des visages issus de photos de vos propres répertoires ou de répertoires partagés. API : `POST /api/persons` (voir [API.md](../API.md)).

### À nommer

La page Gérer les personnes liste les grands clusters non nommés dans un onglet **À nommer**, chacun avec un champ de nom. Un cluster y apparaît lorsqu'il compte au moins `viewer.persons.needs_naming_min_faces` visages (défaut `5`).

Non nommé signifie sans nom ou avec un nom vide, que le cluster vienne du regroupement ou d'une division ; les personnes masquées (ignorées) en sont exclues. L'onglet n'apparaît qu'en mode édition, à côté de **Nommées**, qui ne liste que les personnes nommées, si bien que chacune n'apparaît qu'une fois ; la page s'ouvre sur **Nommées**.

### Page Suggestions de fusion

Accès via `/merge-suggestions` ou le bouton « Suggestions de fusion » de la page Gérer les personnes :

- Présente des paires de personnes dont les visages se ressemblent
- **Curseur de seuil** — seuil de similarité (plus bas = plus de suggestions)
- **Fusion en un clic** — fusionne une paire suggérée
- **Fusion par lot** — fusionne plusieurs suggestions à la fois

### Cartes de photos

- De petites miniatures de visages (avatars) sont affichées pour les personnes reconnues
- Configurable via `viewer.face_thumbnails.output_size_px`

## Marqueur d'espace d'embedding (sécurité du modèle de reconnaissance)

Chaque visage stocke dans `embedding_model` le modèle de reconnaissance qui l'a produit (par défaut `arcface_buffalo_l`, le modèle InsightFace `buffalo_l` / ArcFace `w600k_r50`). Les embeddings de modèles différents ne sont pas comparables : le regroupement n'utilise donc que les visages du modèle **actif**. Une étiquette `NULL` compte comme ArcFace. Si des visages d'un autre modèle sont présents, Facet les exclut et journalise un avertissement.

### Changer de modèle de reconnaissance (ex. AdaFace) — plan différé

AdaFace (meilleur regroupement des visages flous ou candides) n'est **pas encore implémenté**. L'adopter nécessiterait une ré-extraction et un re-regroupement complets (`--extract-faces-gpu-force` puis `--cluster-faces-force`), car les embeddings ArcFace et AdaFace ne sont pas comparables.

### Bibliothèques mixtes, ré-extraction et valeurs inconnues

- **Bibliothèques mixtes.** Une bibliothèque peut contenir à la fois des visages ArcFace (512-d) et SFace (128-d). Le regroupement, les suggestions de fusion, la recherche de personne similaire et les centroïdes n'utilisent chacun qu'un modèle à la fois (`persons.centroid_model` l'indique).
  - Les modes incrémental et « personnes nommées seulement » ne touchent ni les visages ni les personnes de l'autre modèle.
  - `--cluster-faces-force` efface toutes les affectations de visages et supprime toutes les personnes, nommées comprises, quel que soit le modèle.
  - Pour faire passer une bibliothèque au modèle actif, lancez `--extract-faces-gpu-force` (extracteur permissif en mode commercial ; les personnes nommées sont conservées), puis `--cluster-faces-incremental`.
- **Avertissements.** Un scan avertit quand des visages stockés utilisent un autre modèle que l'actif, et `--doctor` le signale aussi. En mode commercial, `--doctor` liste ce qu'un scan charge réellement (YuNet, SFace, Q-ReAlign, plus OFIQ lorsque `python-ofiq` est installé). Sur CUDA, un scan avertit une fois quand InsightFace tourne sur le CPU ; voir la section ONNX Runtime de `--doctor` et [Installation › ONNX Runtime pour la détection de visages](INSTALLATION.md#onnx-runtime-pour-la-détection-de-visages).
- **Les personnes nommées survivent à la ré-extraction.** `--extract-faces-gpu-force` rend chaque visage re-détecté à la personne nommée dont l'ancienne boîte de visage le recouvre (IoU >= 0,5, un pour un). Les visages sans correspondance attendent le prochain regroupement. Une exécution interrompue reprend à l'extraction suivante. Rescanner une photo conserve ses personnes nommées de la même façon.
- **Inconnu n'est pas zéro.** Sans MediaPipe, l'analyseur permissif ne peut pas mesurer les yeux, le sourire ni les clignements, ils sont donc stockés à NULL ; les filtres et pénalités de clignement traitent NULL comme « pas un clignement ». Si la passe visages d'une photo échoue, `face_count`, `face_ratio` et `is_group_portrait` sont NULL et ses visages stockés sont conservés ; elle est notée comme sans visage jusqu'à son prochain scan.

## Dépannage

| Problème | Solution |
|-------|----------|
| Le regroupement se bloque | Utilisez l'algorithme `boruvka_balltree` |
| Trop de petits clusters | Augmentez `min_faces_per_person` |
| Les visages ne se regroupent pas | Diminuez `merge_threshold` |
| Le regroupement GPU échoue | Vérifiez l'installation de cuML, utilisez `"never"` pour forcer le CPU |
| Miniatures manquantes | Exécutez `--refill-face-thumbnails-incremental` |
| Détection de clignement erronée | Ajustez `blink_ear_threshold`, exécutez `--recompute-blinks` |
| Avertissement « Excluded N faces from non-active embedding space » | Un changement de modèle de reconnaissance a laissé des embeddings mélangés — exécutez `--extract-faces-gpu-force` puis `--cluster-faces-incremental` |
