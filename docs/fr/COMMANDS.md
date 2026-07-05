# Référence des commandes

> 🌐 [English](../COMMANDS.md) · **Français** · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md)

[Analyse](#scanning) · [Aperçu et export](#preview--export) · [Opérations de recalcul](#recompute-operations) · [Reconnaissance faciale](#face-recognition) · [Gestion des miniatures](#thumbnail-management) · [Diagnostics](#diagnostics) · [Informations sur les modèles](#model-information) · [Optimisation des poids](#weight-optimization-pairwise-comparison) · [Configuration](#configuration) · [Étiquetage](#tagging) · [Validation de la base de données](#database-validation) · [Maintenance de la base de données](#database-maintenance) · [Visionneuse web](#web-viewer) · [Flux de travail courants](#common-workflows)

> Étiquettes d'exigence utilisées ci-dessous : `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (profil VRAM). Voir la [matrice des fonctionnalités](../README.md#feature-availability--requirements).

## Analyse

| Commande | Description |
|---------|-------------|
| `python facet.py /path` | Analyse un répertoire (mode multi-passes, détection automatique de la VRAM) |
| `python facet.py /path --force` | Réanalyse les fichiers déjà traités |
| `python facet.py /path --single-pass` | Force le mode passe unique (tous les modèles chargés en même temps) |
| `python facet.py /path --pass quality` | Exécute uniquement la passe de notation qualité TOPIQ |
| `python facet.py /path --pass quality-iaa` | Exécute uniquement la notation du mérite esthétique TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Exécute uniquement la notation de qualité TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Exécute uniquement le diagnostic qualité + distorsion LIQE |
| `python facet.py /path --pass tags` | Exécute uniquement la passe d'étiquetage (le modèle dépend du profil VRAM) |
| `python facet.py /path --pass composition` | Exécute uniquement la détection de motifs de composition SAMP-Net |
| `python facet.py /path --pass faces` | Exécute uniquement la détection de visages InsightFace |
| `python facet.py /path --pass embeddings` | Exécute uniquement l'extraction d'embeddings CLIP/SigLIP |
| `python facet.py /path --pass saliency` | Exécute uniquement la détection de saillance du sujet BiRefNet |
| `python facet.py /path --db custom.db` | Utilise un fichier de base de données personnalisé |
| `python facet.py /path --config my.json` | Utilise une configuration de notation personnalisée |
| `python facet.py --resume` | Reprend la dernière analyse interrompue/en échec — y compris une analyse brutalement arrêtée par SIGKILL/OOM/coupure de courant (une exécution toujours marquée `running` dont le heartbeat est plus ancien que `processing.scan_stale_seconds`, par défaut 120). Réutilise ses répertoires ; avec `--force`, ignore les fichiers déjà re-notés depuis le démarrage de cette exécution. Refuse si une autre analyse semble réellement active. |
| `python facet.py --retry-failed` | Retraite uniquement les fichiers en échec lors de la dernière exécution d'analyse (`--retry-failed all` pour les échecs de toutes les exécutions) |
| `python facet.py /path --force-since 2026-01-01` | Comme `--force`, mais retraite uniquement les photos analysées pour la dernière fois avant la date |
| `python facet.py /path --watch` | Reste actif et réanalyse à chaque apparition de nouvelles photos (nécessite `pip install watchdog` ; `--watch-debounce N` ajuste la période de calme, par défaut 30 s) |
| `python facet.py /path --force-low-space` | Ignore la protection d'espace libre avant analyse (procède même si le volume semble trop petit pour les miniatures/embeddings que l'analyse va écrire) |

### Suivi des analyses

Chaque analyse enregistre une ligne dans `scan_runs` (statut, mode, répertoires, compteurs)
et les erreurs par fichier dans `scan_failures` (chemin, étape, erreur). Interrompre une
analyse avec Ctrl+C marque l'exécution comme `interrupted` afin que `--resume` puisse la
reprendre ; les fichiers en échec sont visibles et réessayables au lieu d'être réessayés
silencieusement à chaque analyse incrémentale. La CLI émet également des lignes JSON
structurées `@FACET_PROGRESS` (phase, courant/total, ETA) que l'API d'analyse de la
visionneuse expose dans le champ `progress` de `/api/scan/status` et du flux SSE.

### Modes de traitement

**Multi-passes (par défaut) :** détecte la VRAM et charge les modèles séquentiellement. Chaque passe charge son modèle, traite toutes les photos, puis le décharge pour libérer la VRAM, de sorte que des modèles de haute qualité s'exécutent même avec une VRAM limitée.

**Passe unique (`--single-pass`) :** charge tous les modèles en même temps. Plus rapide, nécessite plus de VRAM.

**Passe spécifique (`--pass NAME`) :** exécute une seule passe, pour mettre à jour des métriques spécifiques sans retraitement complet. Passes disponibles :

| Passe | Modèle | Sortie | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | Score `aesthetic` (0-10) | ~2 Go |
| `quality-iaa` | TOPIQ IAA | Score `aesthetic_iaa` (mérite artistique vs qualité technique, entraîné sur AVA) | Partagé avec TOPIQ |
| `quality-face` | TOPIQ NR-Face | Score `face_quality_iqa` (qualité de visage dédiée) | Partagé avec TOPIQ |
| `quality-liqe` | LIQE | Score `liqe_score` + diagnostic de distorsion (flou, surexposition, bruit) | ~2 Go |
| `tags` | CLIP / Qwen VLM | Étiquettes sémantiques depuis le vocabulaire configuré | 0-16 Go |
| `composition` | SAMP-Net | `composition_pattern` (14 motifs) + `comp_score` | ~2 Go |
| `faces` | InsightFace buffalo_l | Détection de visages, points de repère, détection de clignement, embeddings de reconnaissance | ~2 Go |
| `embeddings` | CLIP ViT-L-14 ou SigLIP 2 NaFlex | BLOB `clip_embedding` pour similarité/étiquetage | 4-5 Go |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~2 Go |

## Aperçu et export

| Commande | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Note 10 photos d'échantillon sans enregistrer |
| `python facet.py /path --dry-run --dry-run-count 20` | Note 20 photos d'échantillon |
| `python facet.py --export-csv` | Exporte tous les scores vers un CSV horodaté |
| `python facet.py --export-csv output.csv` | Exporte vers un fichier CSV spécifique |
| `python facet.py --export-json` | Exporte tous les scores vers un JSON horodaté |
| `python facet.py --export-json output.json` | Exporte vers un fichier JSON spécifique |
| `python facet.py --import-sidecars` | Importe les notes/libellés/étiquettes depuis les sidecars `<image>.xmp` vers la base de données (toutes les photos) |
| `python facet.py --import-sidecars /path` | Importe les sidecars uniquement pour les photos sous un sous-arbre de chemin |
| `python facet.py --import-sidecars --user alice` | Mode multi-utilisateurs : importe les notes dans le `user_preferences` d'Alice au lieu des colonnes globales (les mots-clés restent globaux) |
| `python facet.py --export-sidecars` | Écrit/fusionne les sidecars `<image>.xmp` depuis la base de données pour toutes les photos (sidecar uniquement) |
| `python facet.py --export-sidecars /path` | Exporte les sidecars uniquement pour les photos sous un sous-arbre de chemin |
| `python facet.py --export-sidecars --user alice` | Mode multi-utilisateurs : exporte les notes `user_preferences` d'Alice au lieu des colonnes globales (les mots-clés restent globaux) |
| `python facet.py --export-sidecars --embed-originals` | Intègre également les métadonnées **dans le fichier** pour JPEG/HEIC/TIFF/PNG/DNG (réécrit les originaux) |
| `python facet.py --export-sidecars --score-to-stars` | Dérive `xmp:Rating` du score agrégé pour les photos que vous n'avez pas notées manuellement (une note/favori/rejet manuel l'emporte toujours) |

> **Synchronisation bidirectionnelle des métadonnées.** Facet écrit les notes, libellés de couleur, mots-clés, légendes et régions de visages nommés dans un sidecar `<image>.xmp` standard que l'écosystème lit (Lightroom, darktable, digiKam, immich, …) ; l'image originale n'est jamais modifiée sauf si vous y consentez avec `--export-sidecars --embed-originals` (JPEG/HEIC/TIFF/PNG/DNG uniquement — le RAW n'est jamais touché). L'intégration et la fusion sûre par union de mots-clés nécessitent **exiftool** ; sans lui, Facet se rabat sur un sidecar XML pur sans dépendance.
>
> **Mise en garde.** `--import-sidecars` résout les notes/libellés selon le principe *le plus récent l'emporte* par rapport au `scanned_at` de la photo (dernière analyse), et non un horodatage d'édition par note — ainsi un sidecar plus récent que la dernière analyse peut écraser une note que vous avez modifiée dans Facet après celle-ci. Exécutez `--import-sidecars` avant de re-noter si l'éditeur externe fait foi, et `python database.py --migrate-tags` après l'import si vous utilisez la table de correspondance `photo_tags`.

### Synchronisation Immich

Poussez vos notes et favoris Facet vers un serveur [Immich](https://immich.app/) via son API REST (à sens unique — Facet → Immich). Les ressources sont résolues par `originalPath` grâce aux correspondances de préfixes de chemin du bloc de configuration `immich`, en une seule passe de recherche groupée.

| Commande | Description |
|---------|-------------|
| `python facet.py --immich-test` | Vérifie la connectivité et l'authentification auprès du serveur Immich configuré (`immich.url` + `immich.api_key`, envoyé comme `x-api-key`) |
| `python facet.py --immich-sync` | Pousse les notes en étoiles (1–5) et les favoris vers Immich, en résolvant les ressources par `originalPath`. Honore `--dry-run` (résout mais n'écrit jamais) et `--user` (notes par utilisateur en mode multi-utilisateurs) |
| `python facet.py --immich-sync --dry-run` | Résout chaque ressource et rapporte ce qui changerait sans rien écrire |

Les notes suivent la politique de compatibilité de version d'Immich (1–5 uniquement, jamais 0/−1) ; un album de coups de cœur facultatif rassemble les photos au-dessus d'un seuil de note. REST uniquement — aucun couplage direct à la base de données Immich. Voir [Configuration — Synchronisation Immich](CONFIGURATION.md#immich-sync) pour le bloc complet.

## Opérations de recalcul

Ces commandes mettent à jour des métriques spécifiques, dérivent de nouvelles données (légendes IA, GPS, embeddings) ou analysent la base de données — le tout sans réexécuter l'intégralité du pipeline de notation. La plupart réutilisent les miniatures/points de repère stockés et sont légères pour le CPU, mais les lignes IA/extraction (par ex. `--generate-captions`) et les lignes de recalcul à partir de l'image sont gourmandes en GPU.

| Commande | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcule les scores agrégés à partir des embeddings stockés (re-dérivable ; pas d'instantané de base de données — annulez en restaurant un instantané de poids et en recalculant) |
| `python facet.py --recompute-category portrait` | Recalcule les scores pour une seule catégorie |
| `python facet.py --recompute-tags` | Ré-étiquette toutes les photos avec le modèle configuré |
| `python facet.py --recompute-tags-vlm` | Ré-étiquette toutes les photos avec l'étiqueteur VLM |
| `python facet.py --detect-moments` | Étiquette les nouvelles photos avec leur moment narratif (sémantique de légende, zero-shot + lissage temporel ; s'exécute automatiquement à la fin de chaque analyse). Encode chaque nouvelle légende une fois dans `caption_embedding`, puis cosinus sur les vecteurs stockés — le premier remplissage rétroactif complet sur une bibliothèque existante est recommandé sur GPU ; ajoutez `--limit N` pour vérifier sur un échantillon. Lorsque `narrative_moments.vlm_tiebreak.enabled` est activé (profils 16gb/24gb), les images à faible postérieur / faible marge sont reclassées par le VLM du profil |
| `python facet.py --recompute-moments` | Ré-étiquette les moments narratifs pour toute la bibliothèque (re-lisse l'ensemble de la chronologie). Ajoutez `--dry-run --verbose` pour prévisualiser les 3 meilleurs moments par photo sans écrire. Honore également la reclassification VLM `narrative_moments.vlm_tiebreak` des images à faible confiance lorsqu'elle est activée (16gb/24gb) |
| `python facet.py --discover-moments` | Propose un vocabulaire de moments propre à la bibliothèque en regroupant les embeddings de légende stockés (HDBSCAN) et en nommant chaque grappe à partir de ses légendes. Écrit `scoring_config.discovered.json` pour examen — ne réécrit jamais la configuration active. Exécutez d'abord `--detect-moments` pour remplir `caption_embedding` ; ajustez la granularité avec `--discover-min-cluster-size N` |
| `python facet.py --detect-junk` | Signale les fichiers non photographiques indésirables (captures d'écran, documents, reçus, mèmes, diapositives) dans les photos nouvelles/non évaluées via CLIP en zero-shot sur les embeddings stockés ; s'exécute automatiquement en fin de scan. Les photos propres sont marquées `not_junk` afin que les ré-exécutions ne les rebalaient jamais ; ajoutez `--dry-run --verbose` pour prévisualiser les scores par photo sans écrire |
| `python facet.py --recompute-junk` | Réévalue `junk_kind` pour toute la bibliothèque (toutes les photos disposant d'un embedding stocké) |
| `python facet.py --recompute-saliency` | `[GPU]` `[16gb/24gb]` Recalcule les métriques de saillance du sujet (BiRefNet_dynamic) |
| `python facet.py --recompute-composition-cpu` | Recalcule la composition, basé sur des règles (CPU, tout profil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcule la composition avec SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` `[8gb/16gb/24gb]` Recalcule les métriques IQA supplémentaires (TOPIQ IAA, NR-Face, LIQE) à partir des miniatures stockées |
| `python facet.py --recompute-ocr` | Extrait le texte présent dans l'image vers `ocr_text` depuis les miniatures (optionnel ; sans effet sans moteur OCR ; exécutez `--rebuild-fts` ensuite pour indexer) |
| `python facet.py --recompute-colors` | Extrait la teinte dominante + la température de couleur chaude/froide depuis les miniatures (CPU, rapide) vers `dominant_hue` / `color_temp` |
| `python facet.py --recompute-form` | Recalcule les cinq métriques explicables de forme/couleur — symétrie gauche-droite, équilibre visuel, entropie d'orientation des contours, complexité fractale par comptage de boîtes et harmonie colorimétrique par gabarit de teinte Matsuda — à partir des miniatures stockées (CPU, sans modèle). Elles apparaissent dans la décomposition de critique, les suggestions et l'infobulle de photo, et sont disponibles comme poids de catégorie (livrées à 0) |
| `python facet.py --recompute-skin-tone` | Recalcule le naturel du teint des portraits à partir des miniatures de visage + points de repère stockés (chroma CIELAB des joues vs un lieu de peau CCT, CIEDE2000 ; CPU, sans modèle). Indicatif uniquement — s'affiche comme note de critique, sans couplage à l'agrégat |
| `python facet.py --recompute-distortions` | Étiquette chaque photo avec ses attributs de distorsion probables (flou de bougé, dominante colorée, suraccentuation, …) via des prompts contrastifs zero-shot de style ExIQA sur l'embedding CLIP/SigLIP stocké, puis affiche un rapport de corrélation de Spearman vs `liqe_score` / `noise_sigma`. Indicatif uniquement (puces d'avertissement de critique), sans couplage à l'agrégat |
| `python facet.py --upgrade-db` | Migre le schéma et exécute la chaîne complète de remplissage : extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. Idempotent ; ignore les étapes lourdes comme l'étiquetage des légendes. |
| `python facet.py --recompute-blinks` | Recalcule la détection de clignement à partir des points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-eyes-expression` | Recalcule les scores d'ouverture des yeux + expression à partir des points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-face-signals` | Remplit rétroactivement les scores d'ouverture des yeux + sourire par visage à partir des points de repère 106 points stockés (CPU, rapide ; sans modèle). S'exécute aussi comme étape de `--upgrade-db` |
| `python facet.py --recompute-burst` | Recalcule les groupes de détection de rafales |
| `python facet.py --detect-duplicates` | Détecte les photos en double via pHash |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Évalue les seuils de cosinus de quasi-doublon (table précision/rappel avec labels, sinon distribution cosinus des candidats) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Génère des légendes IA pour les photos via VLM. Lorsque `narrative_moments.caption_min_confidence > 0`, ignore les photos non étiquetées / `other` / sous le seuil (la même barrière s'applique à l'endpoint de légende à la demande) |
| `python facet.py --translate-captions` | Traduit les légendes anglaises vers la langue cible configurée (CPU, MarianMT) |
| `python facet.py --extract-gps` | Extrait les coordonnées GPS des données EXIF vers les colonnes de la base de données |
| `python facet.py --rescan-gps` | Réextrait les coordonnées GPS depuis l'EXIF pour toutes les photos (écrase l'existant) |
| `python facet.py --recompute-embeddings` | Recalcule les embeddings CLIP/SigLIP pour toutes les photos (requis après un changement de modèle) |
| `python facet.py --score-topiq` | Remplit les scores de qualité TOPIQ à partir des miniatures stockées (GPU requis) |
| `python facet.py --backfill-focal-35mm` | Remplit la focale équivalente 35 mm depuis l'EXIF pour les photos qui en manquent |
| `python facet.py --compute-recommendations` | Analyse la base de données, affiche un résumé de notation |
| `python facet.py --compute-recommendations --verbose` | Affiche des statistiques détaillées |
| `python facet.py --compute-recommendations --apply-recommendations` | Applique automatiquement les correctifs de notation |
| `python facet.py --compute-recommendations --simulate` | Prévisualise les changements projetés |

### Modèles de qualité supplémentaires

Trois modèles PyIQA additionnels notent au-delà du score esthétique TOPIQ principal. Ils partagent la VRAM avec TOPIQ et s'exécutent dans le cadre du pipeline multi-passes par défaut.

- **TOPIQ IAA** (`--pass quality-iaa`) : mérite esthétique artistique entraîné sur AVA, distinct de la qualité technique. Stocké dans `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`) : évaluation de la qualité de la région du visage. Stocké dans `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`) : score de qualité plus un diagnostic du type de distorsion (par ex. flou de bougé, surexposition, bruit). Stocké dans `liqe_score`.

### Benchmarks et scores supplémentaires

| Commande | Description |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Remplit la colonne `aesthetic_clip` en projetant les embeddings CLIP/SigLIP mis en cache sur un axe esthétique dérivé du texte. Aucune inférence d'image supplémentaire. Ne fait pas partie de l'`aggregate` par défaut. Voir [docs/SCORING.md](SCORING.md#supplementary-signals-not-in-default-aggregate). |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcule le SRCC + PLCC par rapport à la vérité terrain des scores moyens d'opinion AVA pour chaque colonne de score remplie dans la base de données. Utile lors de l'ajout ou de l'ajustement d'une variante de modèle. |

### Saillance du sujet

`--pass saliency` et `--recompute-saliency` utilisent BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`) pour générer un masque binaire du sujet, puis dérivent quatre métriques :

- **Netteté du sujet** : variance laplacienne sur la région du sujet vs l'arrière-plan — indique si le sujet est net.
- **Prééminence du sujet** : surface du sujet / surface du cadre — élevée pour un sujet dominant (par ex. macro).
- **Placement du sujet** : score de règle des tiers pour le centroïde du sujet.
- **Séparation de l'arrière-plan** : différence de gradient de contour entre la frontière du sujet et l'arrière-plan — qualité du bokeh.

Nécessite `transformers` (~2 Go de VRAM).

### Modèles d'étiquetage

Le modèle d'étiquetage est sélectionné par profil VRAM :

| Profil | Modèle | Fonctionnement |
|---------|-------|-------------|
| `legacy` | Similarité CLIP | Similarité cosinus entre l'embedding d'image et les embeddings de texte d'étiquette. Aucun chargement de modèle supplémentaire. |
| `8gb` | Similarité CLIP | Identique à legacy, sur les embeddings CLIP ViT-L-14 stockés. |
| `16gb` | Qwen3.5-2B | Modèle multimodal pour l'étiquetage sémantique de scène. |
| `24gb` | Qwen3.5-4B | Modèle multimodal plus grand. |

Tous les étiqueteurs mappent leur sortie vers le vocabulaire d'étiquettes configuré. Utilisez `--recompute-tags` pour ré-étiqueter avec le modèle par défaut du profil, ou `--recompute-tags-vlm` pour un ré-étiquetage basé sur VLM.

### Modèles d'embedding

Deux modèles d'embedding sont disponibles, sélectionnés par profil VRAM via `clip_config` :

| Config | Modèle | Dimensions | Utilisé par |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | profils 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | profils legacy, 8gb |

Les embeddings alimentent l'étiquetage sémantique, la détection de doublons, la recherche de photos similaires et l'esthétique CLIP+MLP (legacy/8gb). Le changement de modèle nécessite de ré-embedder toutes les photos (`--force`, `--pass embeddings` ou `--recompute-embeddings`).

## Reconnaissance faciale

| Commande | Description |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrait les visages des nouvelles photos (GPU, parallèle) |
| `python facet.py --extract-faces-gpu-force` | Supprime tous les visages et les réextrait (GPU) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, préserve toutes les personnes (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, préserve uniquement les personnes nommées (CPU) |
| `python facet.py --cluster-faces-force` | Re-clustering complet, supprime toutes les personnes (CPU) |
| `python facet.py --suggest-person-merges` | Suggère des fusions de personnes potentielles |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Utilise un seuil plus strict |
| `python facet.py --refill-face-thumbnails-incremental` | Génère les miniatures manquantes (CPU, parallèle) |
| `python facet.py --refill-face-thumbnails-force` | Régénère TOUTES les miniatures (CPU, parallèle) |

## Gestion des miniatures

| Commande | Description |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Corrige la rotation des miniatures stockées en utilisant l'orientation EXIF |

Lit l'orientation EXIF des fichiers originaux et fait pivoter les octets de la miniature stockée ; pour les photos traitées avant l'existence de la gestion EXIF. Ne lit que l'en-tête EXIF et la miniature stockée, pas les images complètes.

## Diagnostics

| Commande | Description |
|---------|-------------|
| `python facet.py --doctor` | Exécute des contrôles de diagnostic (Python, GPU, dépendances, config, base de données) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simule du matériel GPU pour les diagnostics |

Rapporte la version de Python, la build PyTorch/CUDA, la détection du GPU et du pilote, la recommandation de profil VRAM, les dépendances optionnelles et l'état de la config/base de données. Lorsque PyTorch ne voit pas le GPU mais que `nvidia-smi` le voit, il affiche la commande `pip install` pour corriger la build CUDA.

`--simulate-gpu NAME` et `--simulate-vram GB` testent le comportement avec différents matériels. Les deux nécessitent `--doctor` ; `--simulate-vram` nécessite `--simulate-gpu`.

## Informations sur les modèles

| Commande | Description |
|---------|-------------|
| `python facet.py --list-models` | Affiche les modèles disponibles et les exigences de VRAM |

## Optimisation des poids (comparaison par paires)

| Commande | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Affiche les statistiques de comparaison par paires |
| `python facet.py --optimize-weights` | Optimise et enregistre les poids à partir des comparaisons (toutes sources, pondéré par fiabilité) ; appliqué uniquement si la précision en validation croisée k-fold dépasse les poids actuels |
| `python facet.py --optimize-weights --optimize-force` | Applique les poids optimisés même si le seuil de précision n'est pas atteint |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Restreint les données d'entraînement à des sources de comparaison spécifiques |
| `python facet.py --optimize-weights --optimize-category portrait` | Entraîne uniquement sur une catégorie et écrit son bloc `categories[].weights` v4 |
| `python facet.py --auto-tune-categories` | **Superadmin uniquement** (passez `--user` en mode multi-utilisateurs) : rapporte l'état de préparation des labels de comparaison par catégorie pour l'auto-ajustement des poids globaux partagés. Stub — rapporte uniquement l'état de préparation ; la boucle d'auto-application est différée en attendant les labels |
| `python facet.py --sync-label-comparisons` | Reconstruit les paires dérivées des notes (source=rating) à partir des notes en étoiles/favoris/rejets |
| `python facet.py --train-ranker` | Entraîne le classeur personnel sur [embedding + scores] et écrit learned_scores (conditionné à la précision en validation croisée k-fold vs la référence agrégée) |
| `python facet.py --train-ranker --ranker-category portrait` | Entraîne le classeur sur une seule catégorie |
| `python facet.py --train-ranker --train-ranker-force` | Écrit learned_scores même si le seuil de précision n'est pas atteint |
| `python facet.py --report-unreviewed-bursts` | Indique combien de groupes de rafales restent non examinés (lecture seule) |
| `python facet.py --eval-iqa-srcc` | Rapporte le SRCC de Spearman de chaque métrique IQA/esthétique vs vos notes en étoiles (lecture seule) |
| `python facet.py --mine-insights` | Rapport d'exploration de données : inventaire des labels, corrélations métrique-label, distribution des catégories, dérive des percentiles, santé des comparaisons |
| `python facet.py --mine-insights report.json` | Idem, écrit aussi le rapport complet en JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibre les poids de notation par catégorie par rapport au [jeu de données AVA](https://github.com/imfing/ava_downloader) en maximisant le SRCC vs les scores moyens d'opinion AVA (lecture seule ; affiche les poids proposés) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Restreint à des catégories spécifiques et réécrit les poids optimisés dans `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Choisit l'optimiseur (`de` = évolution différentielle, par défaut ; `nelder-mead` = simplexe local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Calibre aussi par rapport aux étiquettes sémantiques AVA (`--ava-tags-only` pour utiliser exclusivement les étiquettes ; `--apply-filters` pour ajuster aussi les seuils des filtres de catégorie) |

## Configuration

| Commande | Description |
|---------|-------------|
| `python facet.py --validate-categories` | Valide les configurations de catégorie |

## Étiquetage

| Commande | Description |
|---------|-------------|
| `python tag_existing.py` | Ajoute des étiquettes aux photos non étiquetées en utilisant les embeddings CLIP stockés |
| `python tag_existing.py --dry-run` | Prévisualise les étiquettes sans enregistrer |
| `python tag_existing.py --threshold 0.25` | Seuil de similarité personnalisé (par défaut : 0.22) |
| `python tag_existing.py --max-tags 3` | Limite les étiquettes par photo (par défaut : 5) |
| `python tag_existing.py --force` | Ré-étiquette toutes les photos |
| `python tag_existing.py --db custom.db` | Utilise une base de données personnalisée |
| `python tag_existing.py --config my.json` | Utilise une configuration personnalisée |

## Validation de la base de données

| Commande | Description |
|---------|-------------|
| `python validate_db.py` | Valide la cohérence de la base de données (interactif) |
| `python validate_db.py --auto-fix` | Corrige automatiquement tous les problèmes |
| `python validate_db.py --report-only` | Rapporte sans demander de confirmation |
| `python validate_db.py --db custom.db` | Valide une base de données personnalisée |

Vérifications : plages de scores, métriques de visages, corruption de BLOB, tailles d'embeddings, visages orphelins, valeurs statistiques aberrantes.

## Maintenance de la base de données

| Commande | Description |
|---------|-------------|
| `python database.py` | Initialise/met à niveau le schéma |
| `python database.py --info` | Affiche les informations du schéma |
| `python database.py --migrate-tags` | Remplit la table de correspondance photo_tags (requêtes 10-50x plus rapides) |
| `python database.py --rebuild-fts` | Reconstruit l'index de recherche plein texte FTS5 à partir des légendes/étiquettes |
| `python database.py --populate-vec` | Remplit la table de recherche vectorielle sqlite-vec à partir des embeddings |
| `python database.py --refresh-stats` | Rafraîchit le cache de statistiques |
| `python database.py --stats-info` | Affiche l'état et l'ancienneté du cache |
| `python database.py --vacuum` | Récupère de l'espace, défragmente |
| `python database.py --analyze` | Met à jour les statistiques du planificateur de requêtes |
| `python database.py --optimize` | Exécute VACUUM et ANALYZE |
| `python database.py --backup` | Écrit un instantané horodaté et sûr pour le WAL de la base de données (rotation via `--keep N`, par défaut 3) |
| `python database.py --export-viewer-db` | Exporte une base de données de visionneuse allégée (retire les BLOB, réduit les miniatures ; incrémental si la sortie existe) |
| `python database.py --export-viewer-db --force-export` | Force une réexportation complète, même si la base de données de la visionneuse existe déjà |
| `python database.py --cleanup-orphaned-persons` | Supprime les personnes sans visages associés |
| `python database.py --cleanup-missing-photos` | Supprime de la base de données les photos qui ne sont plus sur le disque (les suppressions en cascade nettoient les étiquettes, les visages détectés, etc. ; vide également les appartenances aux albums, l'index vectoriel et invalide le cache de statistiques) |
| `python database.py --cleanup-missing-photos --dry-run` | Prévisualise les fichiers manquants sans supprimer |
| `python database.py --cleanup-missing-photos --force` | Procède même si toutes les photos semblent manquantes (protection contre la suppression de tout lorsqu'un volume est démonté) |
| `python database.py --migrate-storage-fs` | Migre les miniatures et embeddings des BLOB de base de données vers le système de fichiers |
| `python database.py --migrate-storage-db` | Migre les miniatures et embeddings du système de fichiers vers la base de données |
| `python database.py --add-user alice --role admin` | Ajoute un utilisateur (demande un mot de passe) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Ajoute un utilisateur avec un nom d'affichage |
| `python database.py --migrate-user-preferences --user alice` | Copie les notes de photos vers user_preferences |

**Astuce de performance :** pour les grandes bases de données (50k+ photos), exécutez `--migrate-tags`, `--rebuild-fts` et `--populate-vec` une fois, puis `--optimize` périodiquement.

## Visionneuse web

| Commande | Description |
|---------|-------------|
| `python viewer.py` | Démarre le serveur sur http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Lie un port différent (ou définit la variable d'environnement `PORT` ; par défaut 5000) |
| `python viewer.py --host 127.0.0.1` | Lie une interface spécifique (par défaut `0.0.0.0`) |
| `python viewer.py --production` | Mode production (workers uvicorn) |
| `python viewer.py --production --workers 4` | Mode production avec N workers (par défaut 1) |

## Flux de travail courants

### Configuration initiale
```bash
python facet.py /path/to/photos     # Note toutes les photos (multi-passes auto)
python facet.py --cluster-faces-incremental # Clusterise les visages
python database.py --migrate-tags    # Active les requêtes d'étiquettes rapides
python viewer.py                    # Visualise les résultats
```

### Après des modifications de configuration
```bash
python facet.py --recompute-average                # Met à jour tous les scores avec les nouveaux poids
python facet.py --recompute-category portrait      # Met à jour une seule catégorie (plus rapide)
```

### Configuration de la reconnaissance faciale
```bash
python facet.py /path               # Extrait les visages pendant l'analyse
python facet.py --cluster-faces-incremental     # Regroupe en personnes
python facet.py --suggest-person-merges         # Trouve les doublons
# Utilisez /persons dans la visionneuse pour fusionner/renommer
```

### Configuration multi-utilisateurs
```bash
# Ajoute des utilisateurs (demande un mot de passe)
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
# Modifie scoring_config.json pour définir directories et shared_directories
# Migre les notes existantes vers un utilisateur
python database.py --migrate-user-preferences --user alice
```

### Changement de modèle d'étiquetage
```bash
# Modifie scoring_config.json : "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Ré-étiquette avec le nouveau modèle
```

### Changement de profil VRAM
```bash
# Modifie scoring_config.json : "vram_profile": "auto"
# Ou utilise un profil spécifique : "vram_profile": "8gb"
python facet.py --compute-recommendations  # Vérifie les distributions
python facet.py --recompute-average        # Applique les nouveaux poids
```
