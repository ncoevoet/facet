# Reconnaissance faciale

> 🌐 [English](../FACE_RECOGNITION.md) · **Français** · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md)

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

### Étape 4 : Examiner les suggestions de fusion

L'interface web à `/merge-suggestions` présente des paires de clusters de personnes susceptibles d'être le même individu :

- Ajustez le **curseur de seuil de similarité** pour contrôler le degré de prudence des suggestions
- Examinez chaque suggestion côte à côte avec les miniatures de visages
- **Fusion en un clic** pour combiner deux personnes, ou **fusion par lot** pour traiter plusieurs suggestions à la fois
- Disponible également en ligne de commande : `python facet.py --suggest-person-merges --merge-threshold 0.7`

### Étape 5 : Gestion manuelle

Dans la galerie web :
- Accédez à `/persons` pour la gestion des personnes
- Fusionner : sélectionnez la personne source, cliquez sur la cible, confirmez
- Fusion par lot : sélectionnez plusieurs personnes et fusionnez-les dans une seule cible
- Scinder : déplacez un sous-ensemble des visages d'une personne vers une nouvelle personne (si la source se retrouve vide, elle est supprimée)
- Masquer : marquez un cluster `is_hidden` pour l'exclure de la liste, des filtres et des suggestions de fusion (réversible)
- Renommer : cliquez sur le nom de la personne pour le modifier en ligne
- Supprimer : retirez le cluster de personne

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
| `min_face_size` | `20` | Taille de visage minimale en pixels |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio pour la détection des clignements |

### Regroupement des visages

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

| Paramètre | Défaut | Description |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Nombre minimal de photos pour créer une personne |
| `min_samples` | `2` | Paramètre min_samples de HDBSCAN |
| `merge_threshold` | `0.6` | Similarité de centroïde pour le rattachement |
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
- URL : `/person/<id>`

### Page Gérer les personnes

Accès via le bouton d'en-tête ou `/persons` :

- **Vue en grille** - toutes les personnes reconnues
- **Fusionner** - sélectionnez la source, cliquez sur la cible, confirmez
- **Fusion par lot** - sélectionnez plusieurs personnes et fusionnez-les dans une seule cible
- **Scinder** - déplacez les visages sélectionnés vers une nouvelle personne
- **Masquer** - exclure un cluster de la liste, des filtres et des suggestions de fusion
- **Supprimer** - retirez le cluster de personne
- **Renommer** - cliquez sur le nom pour le modifier en ligne

### Page Suggestions de fusion

Accès via `/merge-suggestions` ou le bouton « Suggestions de fusion » de la page Gérer les personnes :

- Présente des paires de personnes aux embeddings de visages similaires susceptibles d'être le même individu
- **Curseur de seuil** — contrôle le seuil de similarité (plus bas = plus de suggestions)
- **Fusion en un clic** — fusionnez instantanément une paire suggérée
- **Fusion par lot** — sélectionnez plusieurs suggestions et fusionnez-les toutes en une fois

### Cartes de photos

- De petites miniatures de visages (avatars) sont affichées pour les personnes reconnues
- Configurable via `viewer.face_thumbnails.output_size_px`

## Marqueur d'espace d'embedding (sécurité du modèle de reconnaissance)

Chaque ligne de visage porte une étiquette `embedding_model` (colonne de `faces`, par défaut
`arcface_buffalo_l` — l'actuel modèle de reconnaissance InsightFace `buffalo_l` / ArcFace `w600k_r50`).
Les embeddings produits par des modèles de reconnaissance **différents** vivent dans des
espaces vectoriels **incompatibles** et ne doivent jamais être regroupés ensemble — le faire
produit silencieusement des personnes erronées, sans aucune erreur.

`FaceClusterer.load_embeddings()` ne charge donc que l'espace d'embedding **actif**
(`ACTIVE_EMBEDDING_MODEL` dans `faces/clusterer.py` ; une étiquette `NULL` est traitée
comme l'ancien espace ArcFace) et émet un avertissement bien visible si des visages d'un autre
espace sont présents et exclus. Il s'agit d'une protection de compatibilité ascendante : elle
rend sûr par construction un futur changement de modèle de reconnaissance.

### Changer de modèle de reconnaissance (ex. AdaFace) — plan différé

Une amélioration de qualité telle qu'**AdaFace** (marge adaptative à la qualité, meilleur
regroupement des visages flous/candides) est intégrable comme backend 512-d optionnel (même
chemin de stockage, même HDBSCAN), mais n'est **pas encore implémentée** car elle ne peut être
validée sans données réelles. La réaliser correctement nécessite :

1. **Poids + backbone** — un checkpoint AdaFace (ex. `adaface_ir101_webface12m`)
   ainsi que son backbone IResNet ; un nouveau téléchargement dans le cache de modèles.
2. **Crops alignés** — calculer l'embedding à partir d'un crop aligné 112×112
   `norm_crop(img, face.kps, 112)` au moment de l'extraction (les kps existent sur l'objet
   `face` d'InsightFace mais ne sont pas persistés, donc AdaFace ne peut pas être recalculé
   hors ligne — il doit s'exécuter pendant l'extraction). Vérifier que le BGR/la normalisation
   correspondent au checkpoint.
3. **Bascule de configuration** — ajouter `face_detection.recognition_model: arcface|adaface`
   et en déduire `ACTIVE_EMBEDDING_MODEL` ; étiqueter les nouveaux visages en conséquence.
4. **Ré-extraction + re-regroupement complets** — `--extract-faces-gpu-force` puis
   `--cluster-faces-force`, car les embeddings ArcFace et AdaFace ne sont pas
   comparables. Le marqueur d'espace d'embedding ci-dessus empêche qu'une base à moitié
   migrée regroupe silencieusement les deux espaces (elle avertit et exclut à la place).
5. **Validation de la qualité** — mesurer la qualité des clusters par rapport à des identités
   étiquetées ; « ça tourne et émet des vecteurs 512-d » ne prouve pas que le prétraitement est correct.

## Dépannage

| Problème | Solution |
|-------|----------|
| Le regroupement se bloque | Utilisez l'algorithme `boruvka_balltree` |
| Trop de petits clusters | Augmentez `min_faces_per_person` |
| Les visages ne se regroupent pas | Diminuez `merge_threshold` |
| Le regroupement GPU échoue | Vérifiez l'installation de cuML, utilisez `"never"` pour forcer le CPU |
| Miniatures manquantes | Exécutez `--refill-face-thumbnails-incremental` |
| Détection de clignement erronée | Ajustez `blink_ear_threshold`, exécutez `--recompute-blinks` |
| Avertissement « Excluded N faces from non-active embedding space » | Un changement de modèle de reconnaissance a laissé des embeddings mélangés — exécutez `--extract-faces-gpu-force` puis `--cluster-faces-force` |
