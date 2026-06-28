# Référence des commandes

> 🌐 [English](../COMMANDS.md) · **Français** · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md)

[Analyse](#analyse) · [Aperçu et export](#aperçu-et-export) · [Opérations de recalcul](#opérations-de-recalcul) · [Reconnaissance faciale](#reconnaissance-faciale) · [Gestion des miniatures](#gestion-des-miniatures) · [Diagnostics](#diagnostics) · [Informations sur les modèles](#informations-sur-les-modèles) · [Optimisation des poids](#optimisation-des-poids-comparaison-par-paires) · [Configuration](#configuration) · [Étiquetage](#étiquetage) · [Validation de la base de données](#validation-de-la-base-de-données) · [Maintenance de la base de données](#maintenance-de-la-base-de-données) · [Galerie web](#galerie-web) · [Flux de travail courants](#flux-de-travail-courants)

> Étiquettes d'exigences utilisées ci-dessous : `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (profil VRAM). Voir la [matrice des fonctionnalités](../../README.md#feature-availability--requirements).

## Analyse

| Commande | Description |
|---------|-------------|
| `python facet.py /path` | Analyse un répertoire (mode multi-passes, détection automatique de la VRAM) |
| `python facet.py /path --force` | Réanalyse les fichiers déjà traités |
| `python facet.py /path --single-pass` | Force le mode passe unique (tous les modèles à la fois) |
| `python facet.py /path --pass quality` | Exécute uniquement la passe de scoring qualité TOPIQ |
| `python facet.py /path --pass quality-iaa` | Exécute uniquement le scoring du mérite esthétique TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Exécute uniquement le scoring qualité TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Exécute uniquement le diagnostic qualité + distorsion LIQE |
| `python facet.py /path --pass tags` | Exécute uniquement la passe d'étiquetage (le modèle dépend du profil VRAM) |
| `python facet.py /path --pass composition` | Exécute uniquement la détection des motifs de composition SAMP-Net |
| `python facet.py /path --pass faces` | Exécute uniquement la détection de visages InsightFace |
| `python facet.py /path --pass embeddings` | Exécute uniquement l'extraction des embeddings CLIP/SigLIP |
| `python facet.py /path --pass saliency` | Exécute uniquement la détection de la saillance du sujet BiRefNet |
| `python facet.py /path --db custom.db` | Utilise un fichier de base de données personnalisé |
| `python facet.py /path --config my.json` | Utilise une configuration de scoring personnalisée |
| `python facet.py --resume` | Reprend la dernière analyse interrompue/échouée — y compris une analyse brutalement stoppée par SIGKILL/OOM/coupure de courant (une exécution toujours marquée `running` dont le battement de cœur est plus ancien que `processing.scan_stale_seconds`, par défaut 120). Réutilise ses répertoires ; avec `--force`, ignore les fichiers déjà re-scorés depuis le démarrage de cette analyse. Refuse si une autre analyse semble réellement active. |
| `python facet.py --retry-failed` | Retraite uniquement les fichiers qui ont échoué lors de la dernière analyse (`--retry-failed all` pour les échecs de toutes les analyses) |
| `python facet.py /path --force-since 2026-01-01` | Comme `--force`, mais retraite uniquement les photos analysées pour la dernière fois avant la date |
| `python facet.py /path --watch` | Reste en exécution et réanalyse dès que de nouvelles photos apparaissent (nécessite `pip install watchdog` ; `--watch-debounce N` règle la période de calme, par défaut 30 s) |
| `python facet.py /path --force-low-space` | Ignore le garde-fou d'espace libre pré-analyse (continue même lorsque le volume semble trop petit pour les miniatures/embeddings que l'analyse va écrire) |

### Suivi des analyses

Chaque analyse enregistre une ligne dans `scan_runs` (statut, mode, répertoires, compteurs)
et les erreurs par fichier dans `scan_failures` (chemin, étape, erreur). Interrompre une
analyse avec Ctrl+C marque l'exécution comme `interrupted` afin que `--resume` puisse la
reprendre ; les fichiers en échec sont visibles et retraitables au lieu d'être silencieusement
réessayés à chaque analyse incrémentale. La CLI émet également des lignes JSON structurées
`@FACET_PROGRESS` (phase, courant/total, ETA) que l'API d'analyse de la galerie expose dans le
champ `progress` de `/api/scan/status` et du flux SSE.

### Modes de traitement

**Multi-passes (par défaut) :** détecte la VRAM et charge les modèles séquentiellement. Chaque passe charge son modèle, traite toutes les photos, puis le décharge pour libérer la VRAM, de sorte que des modèles de haute qualité fonctionnent même avec une VRAM limitée.

**Passe unique (`--single-pass`) :** charge tous les modèles en une fois. Plus rapide, nécessite davantage de VRAM.

**Passe spécifique (`--pass NAME`) :** exécute une seule passe, pour mettre à jour des métriques précises sans retraitement complet. Passes disponibles :

| Passe | Modèle | Sortie | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | Score `aesthetic` (0-10) | ~2 Go |
| `quality-iaa` | TOPIQ IAA | Score `aesthetic_iaa` (mérite artistique vs qualité technique, entraîné sur AVA) | Partagée avec TOPIQ |
| `quality-face` | TOPIQ NR-Face | Score `face_quality_iqa` (qualité du visage dédiée) | Partagée avec TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnostic de distorsion (flou, surexposition, bruit) | ~2 Go |
| `tags` | CLIP / Qwen VLM | Tags sémantiques depuis le vocabulaire configuré | 0-16 Go |
| `composition` | SAMP-Net | `composition_pattern` (14 motifs) + `comp_score` | ~2 Go |
| `faces` | InsightFace buffalo_l | Détection de visages, points de repère, détection de clignement, embeddings de reconnaissance | ~2 Go |
| `embeddings` | CLIP ViT-L-14 ou SigLIP 2 NaFlex | BLOB `clip_embedding` pour similarité/étiquetage | 4-5 Go |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 Go |

## Aperçu et export

| Commande | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Score 10 photos d'échantillon sans enregistrer |
| `python facet.py /path --dry-run --dry-run-count 20` | Score 20 photos d'échantillon |
| `python facet.py --export-csv` | Exporte tous les scores vers un CSV horodaté |
| `python facet.py --export-csv output.csv` | Exporte vers un fichier CSV spécifique |
| `python facet.py --export-json` | Exporte tous les scores vers un JSON horodaté |
| `python facet.py --export-json output.json` | Exporte vers un fichier JSON spécifique |
| `python facet.py --import-sidecars` | Importe les notes/libellés/tags depuis les fichiers annexes `<image>.xmp` vers la base de données (toutes les photos) |
| `python facet.py --import-sidecars /path` | Importe les fichiers annexes uniquement pour les photos sous une arborescence de chemin |
| `python facet.py --import-sidecars --user alice` | Mode multi-utilisateur : importe les notes dans les `user_preferences` d'Alice au lieu des colonnes globales (les mots-clés restent globaux) |
| `python facet.py --export-sidecars` | Écrit/fusionne les fichiers annexes `<image>.xmp` depuis la base pour toutes les photos (fichier annexe uniquement) |
| `python facet.py --export-sidecars /path` | Exporte les fichiers annexes uniquement pour les photos sous une arborescence de chemin |
| `python facet.py --export-sidecars --user alice` | Mode multi-utilisateur : exporte les notes des `user_preferences` d'Alice au lieu des colonnes globales (les mots-clés restent globaux) |
| `python facet.py --export-sidecars --embed-originals` | Intègre aussi les métadonnées **dans le fichier** pour les JPEG/HEIC/TIFF/PNG/DNG (réécrit les originaux) |
| `python facet.py --export-sidecars --score-to-stars` | Dérive `xmp:Rating` du score agrégé pour les photos que vous n'avez pas notées manuellement (une note/un favori/un rejet manuel l'emporte toujours) |

> **Synchronisation des métadonnées dans les deux sens.** Facet écrit les notes, libellés de couleur, mots-clés, légendes et régions de visages nommés dans un fichier annexe `<image>.xmp` standard que tout l'écosystème lit (Lightroom, darktable, digiKam, immich, …). **Par défaut, l'image originale n'est jamais modifiée** — seul le fichier annexe est écrit/fusionné. Pour intégrer les métadonnées *dans le fichier* pour les JPEG/HEIC/TIFF/PNG/DNG (afin que les éditeurs qui ignorent les fichiers annexes les voient aussi), activez-le explicitement : l'action **« Écrire les métadonnées dans le fichier »** par vignette dans la galerie, ou la commande `--export-sidecars --embed-originals`. Les originaux RAW ne sont jamais modifiés. L'intégration et la fusion sûre des fichiers annexes nécessitent **exiftool** (les mots-clés existants/externes sont lus et fusionnés dans l'union, jamais effacés) ; sans lui, Facet se rabat sur un fichier annexe en XML pur, sans dépendance. `--import-sidecars` est la direction inverse : il réintègre les modifications externes dans Facet — les notes/libellés s'appliquent selon le principe *le plus récent l'emporte* (d'après `xmp:MetadataDate`, sinon la date de modification du fichier annexe, comparée au `scanned_at` de la photo), et les mots-clés sont fusionnés (union), de sorte que les tags automatiques de Facet ne sont jamais perdus.
>
> **Limitations.** L'horodatage côté photo pour *le plus récent l'emporte* est `scanned_at` (le dernier scan), et non une date d'édition de la note — un fichier annexe plus récent que le dernier scan peut donc écraser une note modifiée dans Facet *après* ce scan. Exécutez `--import-sidecars` avant de re-noter dans Facet si l'éditeur externe fait foi. Les commandes `--import-sidecars` / `--export-sidecars` opèrent sur les colonnes de notes **globales mono-utilisateur** ; en mode multi-utilisateur, passez `--user <nom>` pour lire/écrire les notes des `user_preferences` de cet utilisateur (les mots-clés restent globaux dans les deux cas). Si vous utilisez la table de recherche `photo_tags`, exécutez `python database.py --migrate-tags` après l'import.

## Opérations de recalcul

Ces commandes mettent à jour des métriques précises sans retraitement complet des photos.

| Commande | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcule les scores agrégés à partir des embeddings stockés (re-dérivable ; aucun instantané de la base de données — pour annuler, restaurez un instantané de poids puis recalculez) |
| `python facet.py --recompute-category portrait` | Recalcule les scores d'une seule catégorie |
| `python facet.py --recompute-tags` | Réétiquette toutes les photos avec le modèle configuré |
| `python facet.py --recompute-tags-vlm` | Réétiquette toutes les photos avec l'étiqueteur VLM |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Recalcule les métriques de saillance du sujet (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Recalcule la composition, basée sur des règles (CPU, tous profils) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcule la composition avec SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Recalcule les métriques IQA supplémentaires (TOPIQ IAA, NR-Face, LIQE) depuis les miniatures stockées |
| `python facet.py --recompute-ocr` | Extrait le texte présent dans l'image vers `ocr_text` depuis les miniatures (optionnel ; sans effet sans moteur OCR ; exécutez `--rebuild-fts` ensuite pour indexer) |
| `python facet.py --recompute-colors` | Extrait la teinte dominante + la température de couleur chaude/froide depuis les miniatures (CPU, rapide) vers `dominant_hue` / `color_temp` |
| `python facet.py --upgrade-db` | Migre le schéma et exécute la chaîne complète de remplissage : extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, average. Idempotent ; ignore les étapes lourdes comme le sous-titrage. |
| `python facet.py --recompute-blinks` | Recalcule la détection de clignement depuis les points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-eyes-expression` | Recalcule les scores d'yeux ouverts + expression depuis les points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-burst` | Recalcule les groupes de détection de rafales |
| `python facet.py --detect-duplicates` | Détecte les photos en doublon via pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Évalue les seuils de cosinus de quasi-doublon (table précision/rappel avec étiquettes, sinon distribution cosinus des candidats) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Génère des légendes IA pour les photos via VLM |
| `python facet.py --translate-captions` | Traduit les légendes anglaises vers la langue cible configurée (CPU, MarianMT) |
| `python facet.py --extract-gps` | Extrait les coordonnées GPS depuis les données EXIF vers des colonnes de la base de données |
| `python facet.py --rescan-gps` | Réextrait les coordonnées GPS depuis EXIF pour toutes les photos (écrase les existantes) |
| `python facet.py --recompute-embeddings` | Recalcule les embeddings CLIP/SigLIP pour toutes les photos (requis après un changement de modèle) |
| `python facet.py --score-topiq` | Remplit les scores de qualité TOPIQ depuis les miniatures stockées (GPU requis) |
| `python facet.py --backfill-focal-35mm` | Remplit la focale équivalente 35 mm depuis EXIF pour les photos qui en manquent |
| `python facet.py --compute-recommendations` | Analyse la base de données, affiche un résumé du scoring |
| `python facet.py --compute-recommendations --verbose` | Affiche des statistiques détaillées |
| `python facet.py --compute-recommendations --apply-recommendations` | Applique automatiquement les correctifs de scoring |
| `python facet.py --compute-recommendations --simulate` | Prévisualise les changements projetés |

### Modèles de qualité supplémentaires

Trois modèles PyIQA additionnels notent au-delà du score esthétique TOPIQ principal. Ils partagent la VRAM avec TOPIQ et s'exécutent dans le cadre du pipeline multi-passes par défaut.

- **TOPIQ IAA** (`--pass quality-iaa`) : mérite esthétique artistique entraîné sur AVA, distinct de la qualité technique. Stocké dans `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`) : évaluation de la qualité de la région du visage. Stocké dans `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`) : score de qualité plus un diagnostic du type de distorsion (par ex. flou de mouvement, surexposition, bruit). Stocké dans `liqe_score`.

### Bancs d'essai et scores supplémentaires

| Commande | Description |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Remplit la colonne `aesthetic_clip` en projetant les embeddings CLIP/SigLIP en cache sur un axe esthétique dérivé du texte. Aucune inférence d'image supplémentaire. Ne fait pas partie de l'`aggregate` par défaut. Voir [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcule le SRCC + PLCC par rapport à la vérité terrain du mean-opinion-score d'AVA pour chaque colonne de score remplie dans la base de données. Utile lors de l'ajout ou du réglage d'une variante de modèle. |

### Saillance du sujet

`--pass saliency` et `--recompute-saliency` utilisent BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`) pour générer un masque binaire du sujet, puis dérivent quatre métriques :

- **Netteté du sujet** : variance laplacienne sur la région du sujet vs le fond — indique si le sujet est net.
- **Proéminence du sujet** : surface du sujet / surface du cadre — élevée pour un sujet dominant (par ex. macro).
- **Placement du sujet** : score de la règle des tiers pour le centroïde du sujet.
- **Séparation du fond** : différence de gradient de contour entre la frontière du sujet et le fond — qualité du bokeh.

Nécessite `transformers` (~2 Go de VRAM).

### Modèles d'étiquetage

Le modèle d'étiquetage est sélectionné selon le profil VRAM :

| Profil | Modèle | Fonctionnement |
|---------|-------|-------------|
| `legacy` | Similarité CLIP | Similarité cosinus entre l'embedding de l'image et les embeddings texte des tags. Aucun chargement de modèle supplémentaire. |
| `8gb` | Similarité CLIP | Identique à legacy, sur les embeddings CLIP ViT-L-14 stockés. |
| `16gb` | Qwen3.5-2B | Modèle multimodal pour l'étiquetage sémantique des scènes. |
| `24gb` | Qwen3.5-4B | Modèle multimodal plus grand. |

Tous les étiqueteurs associent la sortie au vocabulaire de tags configuré. Utilisez `--recompute-tags` pour réétiqueter avec le modèle par défaut du profil, ou `--recompute-tags-vlm` pour un réétiquetage basé sur VLM.

### Modèles d'embedding

Deux modèles d'embedding disponibles, sélectionnés selon le profil VRAM via `clip_config` :

| Config | Modèle | Dimensions | Utilisé par |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | Profils 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | Profils legacy, 8gb |

Les embeddings alimentent l'étiquetage sémantique, la détection de doublons, la recherche de photos similaires et l'esthétique CLIP+MLP (legacy/8gb). Changer de modèle nécessite de recalculer les embeddings de toutes les photos (`--force`, `--pass embeddings` ou `--recompute-embeddings`).

## Reconnaissance faciale

| Commande | Description |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrait les visages des nouvelles photos (GPU, parallèle) |
| `python facet.py --extract-faces-gpu-force` | Supprime tous les visages et les réextrait (GPU) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, préserve toutes les personnes (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, préserve uniquement les personnes nommées (CPU) |
| `python facet.py --cluster-faces-force` | Reclustering complet, supprime toutes les personnes (CPU) |
| `python facet.py --suggest-person-merges` | Suggère des fusions potentielles de personnes |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Utilise un seuil plus strict |
| `python facet.py --refill-face-thumbnails-incremental` | Génère les miniatures manquantes (CPU, parallèle) |
| `python facet.py --refill-face-thumbnails-force` | Régénère TOUTES les miniatures (CPU, parallèle) |

## Gestion des miniatures

| Commande | Description |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Corrige la rotation des miniatures stockées à partir de l'orientation EXIF |

Lit l'orientation EXIF des fichiers originaux et fait pivoter les octets de la miniature stockée ; pour les photos traitées avant l'existence de la gestion EXIF. Il ne lit que l'en-tête EXIF et la miniature stockée, pas les images complètes.

## Diagnostics

| Commande | Description |
|---------|-------------|
| `python facet.py --doctor` | Exécute des contrôles de diagnostic (Python, GPU, dépendances, config, base de données) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simule du matériel GPU pour les diagnostics |

Rapporte la version de Python, la build PyTorch/CUDA, la détection du GPU et le pilote, la recommandation de profil VRAM, les dépendances optionnelles et l'état config/base de données. Lorsque PyTorch ne voit pas le GPU mais que `nvidia-smi` le voit, il affiche la commande `pip install` permettant de corriger la build CUDA.

`--simulate-gpu NAME` et `--simulate-vram GB` testent le comportement avec un matériel différent. Les deux nécessitent `--doctor` ; `--simulate-vram` nécessite `--simulate-gpu`.

## Informations sur les modèles

| Commande | Description |
|---------|-------------|
| `python facet.py --list-models` | Affiche les modèles disponibles et les exigences en VRAM |

## Optimisation des poids (comparaison par paires)

| Commande | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Affiche les statistiques de comparaison par paires |
| `python facet.py --optimize-weights` | Optimise et enregistre les poids depuis les comparaisons (toutes sources, pondéré par fiabilité) ; appliqué uniquement si la précision en validation croisée k-fold dépasse les poids actuels |
| `python facet.py --optimize-weights --optimize-force` | Applique les poids optimisés même si le seuil de précision n'est pas atteint |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Restreint les données d'entraînement à des sources de comparaison spécifiques |
| `python facet.py --optimize-weights --optimize-category portrait` | Entraîne sur une seule catégorie et écrit son bloc v4 `categories[].weights` |
| `python facet.py --auto-tune-categories` | **Superadmin uniquement** (passez `--user` en mode multi-utilisateur) : signale la disponibilité des étiquettes de comparaison par catégorie pour l'auto-ajustement des poids globaux partagés. Ébauche — signale uniquement la disponibilité ; la boucle d'application automatique est différée en attendant les étiquettes |
| `python facet.py --sync-label-comparisons` | Reconstruit les paires dérivées des notes (source=rating) depuis les notes en étoiles/favoris/rejets |
| `python facet.py --train-ranker` | Entraîne le classeur personnel sur [embedding + scores] et écrit learned_scores (conditionné à la précision en validation croisée k-fold vs la base de référence agrégée) |
| `python facet.py --train-ranker --ranker-category portrait` | Entraîne le classeur sur une seule catégorie |
| `python facet.py --train-ranker --train-ranker-force` | Écrit learned_scores même si le seuil de précision n'est pas atteint |
| `python facet.py --report-unreviewed-bursts` | Indique combien de groupes de rafales restent à examiner (lecture seule) |
| `python facet.py --eval-iqa-srcc` | Indique le SRCC de Spearman de chaque métrique IQA/esthétique vs vos notes en étoiles (lecture seule) |
| `python facet.py --mine-insights` | Rapport de data-mining : inventaire des étiquettes, corrélations métrique-étiquette, distribution par catégorie, dérive des percentiles, santé des comparaisons |
| `python facet.py --mine-insights report.json` | Idem, écrit aussi le rapport complet au format JSON |

## Configuration

| Commande | Description |
|---------|-------------|
| `python facet.py --validate-categories` | Valide les configurations de catégories |

## Étiquetage

| Commande | Description |
|---------|-------------|
| `python tag_existing.py` | Ajoute des tags aux photos non étiquetées via les embeddings CLIP stockés |
| `python tag_existing.py --dry-run` | Prévisualise les tags sans enregistrer |
| `python tag_existing.py --threshold 0.25` | Seuil de similarité personnalisé (par défaut : 0.22) |
| `python tag_existing.py --max-tags 3` | Limite le nombre de tags par photo (par défaut : 5) |
| `python tag_existing.py --force` | Réétiquette toutes les photos |
| `python tag_existing.py --db custom.db` | Utilise une base de données personnalisée |
| `python tag_existing.py --config my.json` | Utilise une configuration personnalisée |

## Validation de la base de données

| Commande | Description |
|---------|-------------|
| `python validate_db.py` | Valide la cohérence de la base de données (interactif) |
| `python validate_db.py --auto-fix` | Corrige automatiquement tous les problèmes |
| `python validate_db.py --report-only` | Rapporte sans demander de confirmation |
| `python validate_db.py --db custom.db` | Valide une base de données personnalisée |

Vérifie : plages de scores, métriques de visage, corruption de BLOB, tailles d'embedding, visages orphelins, valeurs aberrantes statistiques.

## Maintenance de la base de données

| Commande | Description |
|---------|-------------|
| `python database.py` | Initialise/met à niveau le schéma |
| `python database.py --info` | Affiche les informations du schéma |
| `python database.py --migrate-tags` | Remplit la table de recherche photo_tags (requêtes 10-50x plus rapides) |
| `python database.py --rebuild-fts` | Reconstruit l'index de recherche plein texte FTS5 depuis les légendes/tags |
| `python database.py --populate-vec` | Remplit la table de recherche vectorielle sqlite-vec depuis les embeddings |
| `python database.py --refresh-stats` | Rafraîchit le cache de statistiques |
| `python database.py --stats-info` | Affiche l'état et l'ancienneté du cache |
| `python database.py --vacuum` | Récupère l'espace, défragmente |
| `python database.py --analyze` | Met à jour les statistiques du planificateur de requêtes |
| `python database.py --optimize` | Exécute VACUUM et ANALYZE |
| `python database.py --backup` | Écrit un instantané de la base de données horodaté et compatible WAL (rotation jusqu'à `--keep N`, par défaut 3) |
| `python database.py --export-viewer-db` | Exporte une base de données de galerie allégée (supprime les BLOB, réduit les miniatures ; incrémentale si la sortie existe) |
| `python database.py --export-viewer-db --force-export` | Force une réexportation complète, même si la base de la galerie existe déjà |
| `python database.py --cleanup-orphaned-persons` | Supprime les personnes sans visage associé |
| `python database.py --cleanup-missing-photos` | Supprime de la base de données les photos qui ne sont plus sur le disque (les suppressions en cascade nettoient les tags, les visages détectés, etc. ; vide aussi les appartenances aux albums, l'index vectoriel et invalide le cache de statistiques) |
| `python database.py --cleanup-missing-photos --dry-run` | Prévisualise les fichiers manquants sans supprimer |
| `python database.py --cleanup-missing-photos --force` | Procède même lorsque toutes les photos semblent manquantes (garde-fou contre la suppression de tout lorsqu'un volume est démonté) |
| `python database.py --migrate-storage-fs` | Migre les miniatures et embeddings des BLOB de la base de données vers le système de fichiers |
| `python database.py --migrate-storage-db` | Migre les miniatures et embeddings du système de fichiers vers la base de données |
| `python database.py --add-user alice --role admin` | Ajoute un utilisateur (demande un mot de passe) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Ajoute un utilisateur avec un nom d'affichage |
| `python database.py --migrate-user-preferences --user alice` | Copie les notes de photos vers user_preferences |

**Astuce de performance :** Pour les grandes bases de données (50k+ photos), exécutez `--migrate-tags`, `--rebuild-fts` et `--populate-vec` une fois, puis `--optimize` périodiquement.

## Galerie web

| Commande | Description |
|---------|-------------|
| `python viewer.py` | Démarre le serveur sur http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Lie un port différent (ou définissez la variable d'environnement `PORT` ; par défaut 5000) |
| `python viewer.py --host 127.0.0.1` | Lie une interface spécifique (par défaut `0.0.0.0`) |
| `python viewer.py --production` | Mode production (workers uvicorn) |
| `python viewer.py --production --workers 4` | Mode production avec N workers (par défaut 1) |

## Flux de travail courants

### Configuration initiale
```bash
python facet.py /path/to/photos     # Noter toutes les photos (multi-passes automatique)
python facet.py --cluster-faces-incremental # Regrouper les visages
python database.py --migrate-tags    # Activer les requêtes de tags rapides
python viewer.py                    # Afficher les résultats
```

### Après modification de la configuration
```bash
python facet.py --recompute-average                # Mettre à jour tous les scores avec les nouveaux poids
python facet.py --recompute-category portrait      # Mettre à jour une seule catégorie (plus rapide)
```

### Configuration de la reconnaissance faciale
```bash
python facet.py /path               # Extraire les visages pendant l'analyse
python facet.py --cluster-faces-incremental     # Regrouper en personnes
python facet.py --suggest-person-merges         # Détecter les doublons
# Utiliser /persons dans la galerie web pour fusionner/renommer
```

### Configuration multi-utilisateurs
```bash
# Ajouter des utilisateurs (demande le mot de passe)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Modifier scoring_config.json pour définir directories et shared_directories
# Migrer les notes existantes vers un utilisateur
python database.py --migrate-user-preferences --user alice
```

### Changer de modèle d'étiquetage
```bash
# Modifier scoring_config.json : "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Re-taguer avec le nouveau modèle
```

### Changer de profil VRAM
```bash
# Modifier scoring_config.json : "vram_profile": "auto"
# Ou utiliser une valeur précise : "vram_profile": "8gb"
python facet.py --compute-recommendations  # Vérifier les distributions
python facet.py --recompute-average        # Appliquer les nouveaux poids
```
