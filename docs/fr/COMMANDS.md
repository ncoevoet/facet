# Référence des commandes

> 🌐 [English](../COMMANDS.md) · **Français** · [Deutsch](../de/COMMANDS.md) · [Italiano](../it/COMMANDS.md) · [Español](../es/COMMANDS.md) · [Português](../pt/COMMANDS.md) · [简体中文](../zh/COMMANDS.md)

[Analyse](#analyse) · [Aperçu et export](#aperçu-et-export) · [Opérations de recalcul](#opérations-de-recalcul) · [Reconnaissance faciale](#reconnaissance-faciale) · [Gestion des miniatures](#gestion-des-miniatures) · [Diagnostics](#diagnostics) · [Informations sur les modèles](#informations-sur-les-modèles) · [Optimisation des poids](#optimisation-des-poids-comparaison-par-paires) · [Configuration](#configuration) · [Étiquetage](#étiquetage) · [Validation de la base de données](#validation-de-la-base-de-données) · [Maintenance de la base de données](#maintenance-de-la-base-de-données) · [Visionneuse web](#visionneuse-web) · [Flux de travail courants](#flux-de-travail-courants)

> Étiquettes d'exigence utilisées ci-dessous : `[GPU]` · `[8gb/16gb/24gb]` / `[16gb/24gb]` / `[24gb]` (profil VRAM). Voir la [matrice des fonctionnalités](INSTALLATION.md#exigences-par-fonctionnalité).

## Analyse

| Commande | Description |
|---------|-------------|
| `python facet.py /path` | Analyse un répertoire (multi-passes, détection automatique de la VRAM) |
| `python facet.py /path --force` | Réanalyse les fichiers déjà traités |
| `python facet.py /path --single-pass` | Charge tous les modèles en même temps ; profils `legacy`/`8gb` uniquement (voir [Modes de traitement](#modes-de-traitement)) |
| `python facet.py /path --pass quality` | Exécute uniquement la notation de qualité TOPIQ |
| `python facet.py /path --pass quality-iaa` | Exécute uniquement la notation du mérite esthétique TOPIQ IAA |
| `python facet.py /path --pass quality-face` | Exécute uniquement la notation de qualité TOPIQ NR-Face |
| `python facet.py /path --pass quality-liqe` | Exécute uniquement le diagnostic qualité + distorsion LIQE |
| `python facet.py /path --pass tags` | Exécute uniquement l'étiquetage (le modèle dépend du profil VRAM) |
| `python facet.py /path --pass composition` | Exécute uniquement la détection de motifs de composition SAMP-Net |
| `python facet.py /path --pass faces` | Exécute uniquement la détection de visages InsightFace |
| `python facet.py /path --pass embeddings` | Exécute uniquement l'extraction d'embeddings CLIP/SigLIP (n'écrit aucune étiquette) |
| `python facet.py /path --pass saliency` | Exécute uniquement la détection de saillance du sujet BiRefNet |
| `python facet.py /path --db custom.db` | Utilise un fichier de base de données personnalisé |
| `python facet.py /path --config my.json` | Utilise une configuration de notation personnalisée |
| `python facet.py --resume` | Reprend la dernière analyse interrompue, en échec ou plantée |
| `python facet.py --retry-failed` | Retraite les fichiers en échec lors de la dernière analyse (`--retry-failed all` pour toutes les exécutions) |
| `python facet.py /path --force-since 2026-01-01` | Comme `--force`, mais uniquement pour les photos analysées pour la dernière fois avant cette date |
| `python facet.py /path --watch` | Réanalyse dès que de nouvelles photos apparaissent (nécessite `pip install watchdog` ; `--watch-debounce N`, 30 s par défaut) |
| `python facet.py /path --force-low-space` | Ignore la vérification d'espace libre avant l'analyse |

**`--resume`** récupère aussi une analyse tuée par un plantage, un manque de mémoire ou une coupure de courant : une exécution encore marquée `running` dont le heartbeat est plus ancien que `processing.scan_stale_seconds` (120 par défaut). Il réutilise les répertoires de cette exécution. Avec `--force`, il ignore les fichiers déjà re-notés depuis le démarrage de l'exécution. Il refuse de démarrer si une autre analyse semble active.

### Suivi des analyses

Facet enregistre chaque analyse (statut, mode, répertoires, compteurs) et chaque erreur par fichier. Ctrl+C marque l'exécution `interrupted`, ce qui permet à `--resume` de la poursuivre. Les fichiers en échec sont listés et ne sont retentés qu'avec `--retry-failed`. La visionneuse affiche la progression de l'analyse à partir des lignes `@FACET_PROGRESS` de la CLI.

### Modes de traitement

**Multi-passes (par défaut) :** détecte la VRAM et charge les modèles un par un. Chaque passe charge son modèle, traite toutes les photos, puis le décharge, de sorte que des modèles de haute qualité s'exécutent même avec une VRAM limitée.

**Passe unique (`--single-pass`) :** charge tous les modèles en même temps. Plus rapide, mais nécessite plus de VRAM.

- L'esthétique est notée par la tête CLIP+MLP, ce mode vaut donc pour les profils `legacy` et `8gb`.
- Sur `16gb` et `24gb`, le modèle d'esthétique est TOPIQ, que seul le multi-passes exécute. Une demande de passe unique (`--single-pass` ou `processing.mode: "single-pass"`) journalise un avertissement et s'exécute en multi-passes.
- `--pass NAME` et `--dry-run` ignorent cette vérification.
- Le mode commercial conserve la passe unique, car Q-ReAlign natif y note l'esthétique.

**Note de mise à jour :** les versions antérieures enregistraient une esthétique neutre de 5,0 pour chaque photo d'une analyse en passe unique sur `16gb`/`24gb`. Réanalysez ces dossiers avec `--force` en multi-passes. Pour les retrouver : `SELECT path FROM photos WHERE scoring_model = 'topiq' AND aesthetic = 5.0 AND topiq_score IS NULL`.

**Passe spécifique (`--pass NAME`) :** exécute une seule passe, pour mettre à jour certaines métriques sans retraitement complet.

| Passe | Modèle | Sortie | VRAM |
|------|-------|--------|------|
| `quality` | TOPIQ | Score `aesthetic` (0-10) | ~2 Go |
| `quality-iaa` | TOPIQ IAA | `aesthetic_iaa` (mérite artistique, entraîné sur AVA) | Partagé avec TOPIQ |
| `quality-face` | TOPIQ NR-Face | `face_quality_iqa` (qualité du visage) | Partagé avec TOPIQ |
| `quality-liqe` | LIQE | `liqe_score` + diagnostic de distorsion (flou, surexposition, bruit) | ~2 Go |
| `tags` | CLIP / Qwen VLM | Étiquettes sémantiques depuis le vocabulaire configuré | 0-16 Go |
| `composition` | SAMP-Net | `composition_pattern` (8 motifs) + `comp_score` | ~2 Go |
| `faces` | InsightFace buffalo_l | Visages, points de repère, clignements, embeddings de reconnaissance | ~2 Go |
| `embeddings` | CLIP ViT-L-14 ou SigLIP 2 NaFlex | `clip_embedding` pour la similarité et l'étiquetage | 4-5 Go |
| `saliency` | BiRefNet_dynamic | `subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation` | ~3 Go |

Les mesures multi-passes utilisent une horloge monotone. Le temps EXIF du lot et la somme des secondes de travail des replis sont inclus dans le décodage ; les replis parallèles peuvent se chevaucher. Agrégation, vignettes (lecture source comprise) et sauvegarde hors vignettes sont des intervalles séparés ; la sauvegarde inclut préparation et commit. Les passes restreintes ignorent agrégation et vignettes photo. Les chevauchements décodage/modèles et les reconstructions imbriquées restent inchangés : ne pas additionner tous les compteurs ni convertir les secondes de travail EXIF en pourcentage mural. Le mode mono-passe est exclu. Pour une référence, analyser une copie fixe de 500 RAW/JPEG dans une base temporaire et conserver le résumé, la révision, le profil, les workers, la taille des blocs, le stockage et les conditions de cache. Répéter à conditions identiques. Aucun jeu de référence ni benchmark avant/après fourni ; aucun gain revendiqué.

## Aperçu et export

| Commande | Description |
|---------|-------------|
| `python facet.py /path --dry-run` | Note 10 photos d'échantillon sans enregistrer |
| `python facet.py /path --dry-run --dry-run-count 20` | Note 20 photos d'échantillon |
| `python facet.py --export-csv` | Exporte tous les scores vers un CSV horodaté |
| `python facet.py --export-csv output.csv` | Exporte vers un fichier CSV précis |
| `python facet.py --export-json` | Exporte toutes les métriques stockées vers un JSON horodaté |
| `python facet.py --export-json output.json` | Exporte vers un fichier JSON précis |
| `python facet.py --export-manifest` | Écrit `facet_manifest.json` pour des outils externes comme le module externe Lightroom Classic |
| `python facet.py --export-manifest /path` | Limite le manifeste aux photos sous un chemin |
| `python facet.py --export-manifest --user alice` | Mode multi-utilisateurs : utilise les notes d'Alice (étiquettes et scores restent globaux) |
| `python facet.py --import-lightroom FILE` | Importe les notes, picks et rejets du module externe ; Lightroom gagne |
| `python facet.py --import-lightroom FILE --user alice` | Mode multi-utilisateurs : écrit les notes d'Alice ; **obligatoire** sur une installation multi-utilisateurs |
| `python facet.py --import-sidecars` | Importe notes, libellés, Keep/rejet, GPS manuel et mots-clés depuis les sidecars XMP |
| `python facet.py --import-sidecars /path` | Importe uniquement pour les photos sous un chemin |
| `python facet.py --import-sidecars /path --dry-run` | Affiche un plan JSON des changements et des conflits ; n'écrit rien |
| `python facet.py --import-sidecars /path --sidecar-fields keywords,gps` | Importe uniquement ces groupes : `review` (étoiles, favori, rejet, Keep), `gps`, `keywords` (défaut : tous) |
| `python facet.py --import-sidecars /path --overwrite-sidecar-review` | Applique les champs de revue même par-dessus une modification locale plus récente (`newer_local_edit`) ; à prévisualiser d'abord avec `--dry-run` |
| `python facet.py --import-sidecars --user alice` | Mode multi-utilisateurs : importe notes et Keep/rejet dans le compte d'Alice, pour les photos qu'elle voit |
| `python facet.py --import-sidecars --sidecar-naming full` | Lit `<image.ext>.xmp` / `<image.ext>.facet.xmp` (défaut) ; le fichier le plus récent gagne |
| `python facet.py --import-sidecars --sidecar-naming basename` | Lit `<image>.xmp` (extension retirée) ; refuse les noms de base partagés |
| `python facet.py --import-sidecars --sidecar-naming auto` | Accepte l'un ou l'autre nommage ; ignore une photo qui a les deux |
| `python facet.py --import-sidecars --overwrite-manual-gps` | Remplace le GPS manuel déjà défini dans Facet par celui du sidecar |
| `python facet.py --export-sidecars` | Écrit ou fusionne les sidecars `<image>.xmp` pour toutes les photos |
| `python facet.py --export-sidecars /path --reconcile-keywords` | Retire aussi les mots-clés appartenant à Facet qui ne sont plus présents (ExifTool requis) |
| `python facet.py --export-sidecars /path` | Exporte les sidecars uniquement pour les photos sous un chemin |
| `python facet.py --export-sidecars --user alice` | Mode multi-utilisateurs : exporte les notes et Keep/rejet d'Alice, pour les photos qu'elle voit |
| `python facet.py --export-sidecars --embed-originals` | Écrit aussi les métadonnées **dans** les originaux JPEG/HEIC/TIFF/PNG/DNG |
| `python facet.py --export-sidecars --score-to-stars` | Définit `xmp:Rating` à partir du score pour les photos que vous n'avez pas notées |

**Simulation.** Sur `16gb`/`24gb`, la colonne d'esthétique affiche `n/a`, car TOPIQ ne s'exécute que dans une vraie analyse (le mode commercial affiche le score Q-ReAlign). L'agrégat la compte comme un 5,0 neutre.

**CSV et JSON.** La colonne `tags` ne contient que les tags IA ; les [tags manuels](VIEWER.md#tags-manuels) n'y figurent pas. Dans le JSON, l'objet `scores` de chaque photo porte toutes les métriques stockées ; NULL, les nombres non finis et les BLOB deviennent `null`. L'export JSON refuse d'écrire sur la base de données ou sur ses fichiers `-wal`/`-shm`/`-journal`.

**Manifeste.**

- L'argument optionnel limite *quelles photos* sont exportées. Le fichier est toujours `facet_manifest.json` dans le répertoire courant.
- Il porte `star_rating`/`is_favorite`/`is_rejected` (globaux, ou ceux de l'utilisateur `--user`), `is_burst_lead`, les tags IA et manuels, et un compteur `pending_corrections`. Un compteur non nul affiche un avertissement qui renvoie vers `--detect-panoramas`.
- _manifeste version 2_ ajoute `burst_group_id`, `sequence_kind`, `sequence_group_id` et `score_stars` (le score converti via `xmp_export.score_to_rating`). Un module externe compilé pour cette version refuse un manifeste plus ancien : réexportez. Voir [le module externe Facet](INTEROP.md#le-module-externe-facet-notes-drapeaux-pick-champs-de-métadonnées-et-mots-clés).

**`--import-lightroom`** lit l'export propre au module externe, `facet_lightroom_state.json` (`{"format":"facet-lightroom-state","version":1,"photos":[...]}`), et non le manifeste. Un fichier au mauvais format est refusé avant toute écriture. La valeur de Lightroom gagne pour chaque champ que le fichier porte ; les champs omis gardent la valeur de Facet. Il affiche `matched=… unmatched=… changed=…`. Voir [Lightroom → Facet](INTEROP.md#lightroom--facet).

**Synchronisation bidirectionnelle des métadonnées.** Facet écrit les notes, libellés de couleur, mots-clés, légendes et régions de visages nommés dans un sidecar `<image>.xmp` standard que lisent Lightroom, darktable, digiKam, immich et d'autres.

- Les originaux ne sont jamais modifiés, sauf avec `--embed-originals` (JPEG/HEIC/TIFF/PNG/DNG uniquement ; le RAW n'est jamais touché).
- Les mots-clés sont les tags IA plus vos [tags manuels](VIEWER.md#tags-manuels). Ils sont seulement ajoutés, sauf si `--reconcile-keywords` retire ceux que Facet avait écrits auparavant ; les mots-clés étrangers sont conservés. Voir [Tags manuels et mots-clés XMP](INTEROP.md#tags-manuels-et-mots-clés-xmp).
- L'intégration et la fusion des mots-clés nécessitent **exiftool**. Sans lui, Facet écrit un sidecar XML simple.

**Import des sidecars.**

- Les mots-clés importés deviennent des [tags manuels](INTEROP.md#tags-manuels-et-mots-clés-xmp) ; `--migrate-tags` n'est pas nécessaire.
- Une décision Facet (Keep, rejet ou indécis) sans note ni libellé standard est appliquée sans la vérification liée à la date de l'analyse.
- Avec `--user`, mots-clés et GPS restent globaux. Avec `--export-sidecars --user`, mots-clés, GPS et date de prise de vue restent globaux.
- Comment un sidecar est comparé aux modifications locales : [Prévisualiser les imports et les conflits](INTEROP.md#prévisualiser-les-imports-et-les-conflits).

### Synchronisation Immich

Poussez les notes et favoris Facet vers un serveur [Immich](https://immich.app/) (à sens unique, Facet → Immich, API REST uniquement). Les ressources sont appariées par `originalPath` grâce aux correspondances de préfixes de chemin du bloc de configuration `immich`.

| Commande | Description |
|---------|-------------|
| `python facet.py --immich-test` | Vérifie la connexion et la clé d'API (`immich.url` + `immich.api_key`, envoyée comme `x-api-key`) |
| `python facet.py --immich-sync` | Pousse les notes en étoiles (1–5) et les favoris ; honore `--dry-run` et `--user` |
| `python facet.py --immich-sync --dry-run` | Rapporte ce qui changerait sans rien écrire |

Seules les notes de 1 à 5 sont envoyées (jamais 0/−1). Un album facultatif de coups de cœur rassemble les photos au-dessus d'un seuil de note. Voir [Configuration — Synchronisation Immich](CONFIGURATION.md#synchronisation-immich).

### Plans de piles Immich

Ces commandes acceptent `--config`, `--db` et `--user` ; en mode multi-utilisateurs, un propriétaire existant est requis. L'aperçu n'écrit jamais. L'application exige l'empreinte du plan examiné.

| CLI | |
|---|---|
| `python facet.py --immich-stacks-plan import --stack-plan-out NEW_JSON` | Prévisualiser les piles distantes à importer localement |
| `python facet.py --immich-stacks-plan push --stack-id UUID --stack-plan-out NEW_JSON` | Prévisualiser les piles locales à créer à distance |
| `python facet.py --immich-stacks-apply PLAN_JSON --ack-stack-plan SHA256` | Appliquer le plan examiné |

- Répétez `--stack-id UUID` pour choisir les groupes source.
- `--stack-plan-out NEW_JSON` écrit un nouveau fichier privé (POSIX `0600`) et n'en écrase jamais un. Sous Windows, choisissez un dossier dont l'ACL limite l'accès à votre compte.
- Limites : 1000 groupes, 1000 membres par groupe, 20000 membres au total, 16 MiB.
- Les correspondances incomplètes et les chevauchements font ignorer tout le groupe. Les groupes existants ne sont jamais mis à jour.

Voir [permissions, conflits et limites de concurrence distante](IMMICH.md#piles-manuelles-import-et-envoi).

## Opérations de recalcul

Ces commandes mettent à jour des métriques ou dérivent de nouvelles données sans réexécuter l'intégralité du pipeline de notation. La plupart réutilisent les miniatures et points de repère stockés et sont légères pour le CPU ; les lignes IA (comme `--generate-captions`) nécessitent un GPU.

| Commande | Description |
|---------|-------------|
| `python facet.py --recompute-average` | Recalcule les scores agrégés et les catégories à partir des métriques stockées (aucune image n'est relue) |
| `python facet.py --recompute-category portrait` | Recalcule les scores d'une seule catégorie |
| `python facet.py --tag-untagged` | Étiquette uniquement les photos sans tags, à partir des embeddings stockés |
| `python facet.py --recompute-tags` | Ré-étiquette toutes les photos avec le modèle configuré |
| `python facet.py --recompute-tags-vlm` | Ré-étiquette toutes les photos avec l'étiqueteur VLM |
| `python facet.py --detect-moments` | Étiquette les nouvelles photos avec leur moment narratif (s'exécute après chaque analyse) |
| `python facet.py --recompute-moments` | Ré-étiquette les moments narratifs de toute la bibliothèque |
| `python facet.py --discover-moments` | Propose un vocabulaire de moments à partir de vos légendes dans `scoring_config.discovered.json` |
| `python facet.py --detect-junk` | Signale captures d'écran, documents, reçus, mèmes et diapositives (s'exécute après chaque analyse) |
| `python facet.py --recompute-junk` | Réévalue `junk_kind` pour toute la bibliothèque |
| `python facet.py --recompute-saliency` | `[GPU]` Recalcule la saillance du sujet à partir des miniatures stockées ; `--force` refait tout |
| `python facet.py --recompute-composition-cpu` | Recalcule la composition, basé sur des règles (CPU, tout profil) |
| `python facet.py --recompute-composition-gpu` | `[GPU]` Recalcule la composition avec SAMP-Net |
| `python facet.py --recompute-iqa` | `[GPU]` Remplit les scores TOPIQ IAA, NR-Face et LIQE manquants à partir des miniatures stockées. Fonctionne sur tous les profils ; sur CPU (`legacy`), c'est bien plus lent |
| `python facet.py --detect-text` | Lit le texte présent dans l'image vers `ocr_text` pour que la recherche le trouve (optionnel, voir la note) |
| `python facet.py --recompute-text` | Relance l'OCR sur toute la bibliothèque |
| `python facet.py --recompute-colors` | Extrait la teinte dominante et la température chaude/froide vers `dominant_hue` / `color_temp` (CPU, rapide) |
| `python facet.py --recompute-form` | Recalcule symétrie, équilibre, entropie des contours, complexité fractale et harmonie colorimétrique (CPU) |
| `python facet.py --recompute-skin-tone` | Recalcule le naturel du teint des portraits (CPU ; simple note de critique indicative) |
| `python facet.py --recompute-distortions` | Étiquette les distorsions probables (flou de bougé, dominante colorée, …) et les corrèle avec `liqe_score` / `noise_sigma` (indicatif) |
| `python facet.py --upgrade-db` | Migre le schéma et exécute la chaîne de remplissage complète (voir la note) |
| `python facet.py --recompute-blinks` | Recalcule la détection de clignement à partir des points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-eyes-expression` | Recalcule les scores yeux ouverts + expression à partir des points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-face-signals` | Remplit rétroactivement les scores yeux ouverts + sourire par visage à partir des points de repère stockés (CPU, rapide) |
| `python facet.py --recompute-burst` | Recalcule les groupes de rafales (journalise `Burst state: N rows changed`) |
| `python facet.py --detect-sequences` | Détecte les bracketings d'exposition et les panoramas (s'exécute après chaque analyse ; voir la note) |
| `python facet.py --detect-panoramas` | Détecte les panoramas à partir des miniatures stockées (exécute d'abord la passe des bracketings ; CPU) |
| `python facet.py --detect-duplicates` | Détecte les photos en double via pHash (journalise `Duplicate state: N rows changed`) |
| `python facet.py --sweep-dedup-thresholds [labels.json]` | Évalue les seuils de cosinus des quasi-doublons (précision/rappel avec labels) |
| `python facet.py --generate-captions` | `[GPU]` `[16gb/24gb]` Génère des légendes IA avec le VLM |
| `python facet.py --translate-captions` | Traduit les légendes anglaises vers la langue configurée (CPU, MarianMT) |
| `python facet.py --extract-gps` | Copie le GPS EXIF dans la base de données ; ignore les lieux définis dans la visionneuse |
| `python facet.py --rescan-gps` | Réextrait le GPS EXIF de toutes les photos (écrase) ; ignore les lieux définis dans la visionneuse |
| `python facet.py --recompute-embeddings` | Recalcule les embeddings CLIP/SigLIP de toutes les photos (requis après un changement de modèle) |
| `python facet.py --score-topiq` | `[GPU]` Recalcule `topiq_score` pour chaque photo ayant une miniature (écrase) |
| `python facet.py --backfill-focal-35mm` | Remplit la focale équivalente 35 mm depuis l'EXIF là où elle manque |
| `python facet.py --backfill-clipping` | Dérive les pourcentages d'écrêtage par canal depuis les histogrammes stockés (reprenable) |
| `python facet.py --recompute-silhouette` | Recalcule `is_silhouette` avec la règle fondée sur le visage (voir la note) |
| `python facet.py --repair-int-columns` | Arrondit les valeurs fractionnaires qu'un outil EXIF externe a stockées dans des colonnes entières (comme l'ISO) |
| `python facet.py --repair-neutral-iqa` | Efface les faux scores IQA neutres de 5,0 stockés avant la 1.20 (voir la note) |
| `python facet.py --compute-recommendations` | Analyse la base de données et affiche un résumé de notation |
| `python facet.py --compute-recommendations --verbose` | Affiche des statistiques détaillées |
| `python facet.py --compute-recommendations --apply-recommendations` | Applique automatiquement les correctifs de notation |
| `python facet.py --compute-recommendations --simulate` | Prévisualise les changements projetés |

**`--recompute-average`** ne garde aucun instantané : pour revenir en arrière, restaurez un instantané de poids et recalculez. Après une mise à jour depuis la 1.20 ou une version antérieure, lancez d'abord `--recompute-silhouette`, puis `--recompute-average` deux fois. La première passe enregistre de nouveaux percentiles, si bien que la seconde modifie encore certaines lignes.

**Moments.**

- `--detect-moments` encode chaque nouvelle légende une seule fois dans `caption_embedding`. Le premier remplissage d'une bibliothèque existante se fait de préférence sur GPU ; ajoutez `--limit N` pour l'essayer sur un échantillon.
- Ajoutez `--dry-run --verbose` à `--recompute-moments` (ou `--detect-junk`) pour prévisualiser sans écrire.
- `narrative_moments.vlm_tiebreak` (16gb/24gb) : quand `narrative_moments.vlm_tiebreak.enabled` est activé, le VLM du profil reclasse les images à faible confiance.
- `--discover-moments` regroupe les embeddings de légende stockés et nomme chaque groupe. Il ne réécrit jamais la configuration active. Exécutez d'abord `--detect-moments` ; ajustez avec `--discover-min-cluster-size N`.
- `--generate-captions` ignore les photos non étiquetées, `other` et à faible confiance quand `narrative_moments.caption_min_confidence > 0`.

**Indésirables.** Les photos propres sont marquées `not_junk`, donc les exécutions suivantes ne vérifient que les nouvelles.

**`--detect-text`** est optionnel : il nécessite `ocr.enabled` dans `scoring_config.json` et `pip install easyocr`. Voir [Configuration — OCR](CONFIGURATION.md#ocr).

**`--detect-sequences`** trouve les bracketings d'exposition d'après l'EXIF, puis les panoramas d'après la géométrie des miniatures, et place la photo de tête de chaque rafale sur son exposition de référence. Il s'exécute aussi dans `--upgrade-db`. Les vues de tri **Bracketings d'exposition** / **Panoramas** / **Panoramas HDR** de la visionneuse et les bascules `hide_brackets` / `hide_panoramas` ne font rien tant qu'il n'a pas été exécuté. Chaque exécution réétiquette toute la bibliothèque, donc le relancer (ou relancer `--detect-panoramas`) choisit une nouvelle image représentative après que vous avez trié l'ancienne.

**`--upgrade-db`** migre le schéma et exécute : extract-gps, detect-duplicates, recompute-iqa, saliency, composition-cpu, burst, blinks, eyes-expression, face-signals, average. Il est sans danger à relancer et saute les étapes lourdes comme le sous-titrage. Il redresse aussi les miniatures HEIF laissées couchées par pillow-heif 1.6, avec leurs visages ; les fichiers originaux ne sont jamais écrits. Les fichiers HEIF qu'il ne peut pas lire sont retentés à l'exécution suivante.

**`--recompute-silhouette`** ne lit que la base de données, valide par lot et honore `--dry-run`.

- Le rapport regroupe les photos selon la façon dont leurs cadres de visages s'alignent sur la miniature : `exact`, `scaled`, `count_mismatch` (appariement non validé), `other`.
- Une photo sans visage, ou dont les cadres ne peuvent pas être situés, est mise à 0.
- Les photos dont `face_count` est NULL, ou avec des visages mais sans miniature, sont laissées telles quelles (`skipped_face_count_null` / `skipped_no_thumbnail`).
- Lancez ensuite `--recompute-average`. Voir [SCORING.md](SCORING.md).

**`--repair-int-columns`** ne lit que la base de données. La galerie les affiche correctement sans cela, mais les filtres de plage et les tris utilisent la valeur stockée, donc une photo affichée à ISO 63 peut être manquée. Les valeurs qui ne peuvent pas être des entiers deviennent NULL.

**`--repair-neutral-iqa`** met à NULL toute valeur exactement égale à 5,0 dans `aesthetic_iaa`, `face_quality_iqa` et `liqe_score`, et affiche le nombre par colonne.

- Il ne touche pas à `aesthetic`, `topiq_score`, `aesthetic_v25` ni `quality_score`.
- Un vrai score d'exactement 5,00 est aussi effacé ; `--recompute-iqa` le remplit de nouveau, avec une valeur parfois légèrement différente.
- Lancez ensuite `--recompute-iqa` et `--recompute-average`.
- Refusé avec `--dry-run` (code de sortie 2). Absent de `--upgrade-db`. Rechargez les pages de galerie ouvertes pour voir les nouvelles plages de filtres.

### Modèles de qualité supplémentaires

Trois modèles PyIQA notent au-delà de l'esthétique TOPIQ principale. Ils partagent la VRAM avec TOPIQ et s'exécutent dans l'analyse multi-passes par défaut.

- **TOPIQ IAA** (`--pass quality-iaa`) : mérite artistique entraîné sur AVA, distinct de la qualité technique. Stocké dans `aesthetic_iaa`.
- **TOPIQ NR-Face** (`--pass quality-face`) : qualité de la région du visage. Stocké dans `face_quality_iqa`.
- **LIQE** (`--pass quality-liqe`) : score de qualité plus un diagnostic de distorsion (flou de bougé, surexposition, bruit). Stocké dans `liqe_score`.

Quand un modèle ne peut pas noter une photo :

- Il stocke NULL, et non un 5,0 neutre. Une erreur de mémoire insuffisante du GPU est d'abord retentée avec la moitié de la taille de lot, jusqu'à une seule image.
- LIQE ignore les miniatures dont le petit côté est inférieur à 224 px (après avoir borné le grand côté à 1024 px).
- NR-Face ignore les photos avec `face_count` 0. Une photo où il ne trouve aucun visage est mémorisée dans `iqa_declined` jusqu'à une réanalyse (`--force`), `--refresh-thumbnails` ou `--fix-thumbnail-rotation`. Mettre à jour pyiqa ne l'efface pas.
- Les autres échecs ne sont pas stockés ; le prochain `--recompute-iqa` réessaie.
- Avec `--pass quality`, `quality-iaa`, `quality-face` et `quality-liqe`, une photo en échec garde sa valeur stockée.
- Une analyse complète consigne une photo dont le modèle TOPIQ échoue, pour `--retry-failed` ; `--pass quality` ne le fait pas.

`--recompute-iqa` ne remplit que les colonnes NULL et ne remplace jamais une valeur stockée, y compris un 5,0 neutre d'une version antérieure. Effacez-les avec `--repair-neutral-iqa`, puis lancez `--recompute-iqa` et `--recompute-average`, ou réanalysez avec `--force`. Voir [Dimensions IQA supplémentaires](SCORING.md#dimensions-iqa-supplémentaires).

### Benchmarks et scores supplémentaires

| Commande | Description |
|---------|-------------|
| `python scripts/compute_aesthetic_clip.py --db <path>` | Remplit `aesthetic_clip` à partir des embeddings en cache (aucune inférence d'image ; absent de l'`aggregate` par défaut). Voir [SCORING.md](SCORING.md#signaux-supplémentaires-hors-agrégat-par-défaut) |
| `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>` | Calcule le SRCC + PLCC par rapport à la vérité terrain AVA pour chaque colonne de score |

### Saillance du sujet

`--pass saliency` et `--recompute-saliency` utilisent BiRefNet-dynamic (`ZhengPeng7/BiRefNet_dynamic`, via `transformers`, ~3 Go de VRAM) pour trouver le sujet, puis dérivent quatre métriques :

- **Netteté du sujet** : le sujet est-il net (variance laplacienne, sujet vs arrière-plan).
- **Prééminence du sujet** : surface du sujet / surface du cadre. Élevée pour un sujet dominant (par ex. macro).
- **Placement du sujet** : score de règle des tiers pour le centroïde du sujet.
- **Séparation de l'arrière-plan** : contraste de contour entre le sujet et l'arrière-plan (qualité du bokeh).

La saillance s'exécute sur tous les profils ; `legacy` l'exécute sur CPU, plus lentement. `--recompute-saliency` fonctionne avec le volume de la bibliothèque hors ligne et est reprenable. Sur CUDA, la taille de lot suit la VRAM libre (environ 2,4 GiB par image à 1024 px, de 1 à 8 images) et est divisée par deux après une erreur de mémoire insuffisante.

- **Une photo en échec** est journalisée en ERROR et rien n'est écrit. Une photo jamais notée reste à NULL et est reprise par le prochain `--recompute-saliency` ; une photo qui avait déjà une saillance garde ses valeurs, même avec `--recompute-saliency --force`. Une nouvelle analyse complète (par exemple `python facet.py --force`) stocke NULL pour elle.
- **Une photo sans sujet** stocke NULL pour la netteté, le placement et la séparation, une prééminence de 0.0 et un `subject_bbox` NULL (et un `power_point_score` NULL issu de l'étape de composition). C'est définitif : elle n'est plus mesurée.
- **Les anciennes lignes** stockaient un 5.0 neutre à la place. `--recompute-saliency` et `--recompute-composition-cpu` les réécrivent. `--recompute-saliency` reprend aussi les photos notées avant l'existence de `subject_bbox`.
- Une métrique NULL compte comme neutre dans l'agrégat. Voir [Dimensions de la saillance du sujet](SCORING.md#dimensions-de-la-saillance-du-sujet).

### Modèles d'étiquetage

Le modèle d'étiquetage dépend du profil VRAM :

| Profil | Modèle | Fonctionnement |
|---------|-------|-------------|
| `legacy` | Similarité CLIP | Similarité cosinus entre les embeddings d'image et de texte d'étiquette. Aucun modèle supplémentaire. |
| `8gb` | Similarité CLIP | Identique à legacy, sur les embeddings CLIP ViT-L-14 stockés. |
| `16gb` | Qwen3.5-2B | Modèle multimodal pour l'étiquetage de scène. |
| `24gb` | Qwen3.5-4B | Modèle multimodal plus grand. |

Tous les étiqueteurs mappent leur sortie vers le vocabulaire d'étiquettes configuré. Utilisez `--recompute-tags` pour ré-étiqueter avec le modèle du profil, ou `--recompute-tags-vlm` pour le VLM.

**Quand les étiquettes sont écrites.** Sur les profils de similarité CLIP (`legacy`/`8gb`, et `16gb`/`24gb` quand la passe VLM n'est pas planifiée), une analyse multi-passes étiquette pendant la passe d'embeddings : la catégorie et l'agrégat de l'analyse les utilisent donc déjà. Une exécution avec un seul `--pass` (par exemple `--pass embeddings`) n'écrit aucune étiquette. `--pass tags` sur un profil CLIP s'arrête en renvoyant vers `--recompute-tags`. Les lignes existantes gardent leur catégorie jusqu'à `--recompute-average`.

### Modèles d'embedding

Deux modèles d'embedding, sélectionnés par profil VRAM via `clip_config` :

| Config | Modèle | Dimensions | Utilisé par |
|--------|-------|-----------|---------|
| `clip` | SigLIP 2 NaFlex SO400M | 1152 | profils 16gb, 24gb |
| `clip_legacy` | CLIP ViT-L-14 | 768 | profils legacy, 8gb |

Les embeddings alimentent l'étiquetage, la détection de doublons, la recherche de photos similaires et l'esthétique CLIP+MLP (legacy/8gb). Changer de modèle nécessite de ré-embedder toutes les photos (`--force`, `--pass embeddings` ou `--recompute-embeddings`).

## Reconnaissance faciale

| Commande | Description |
|---------|-------------|
| `python facet.py --extract-faces-gpu-incremental` | Extrait les visages des nouvelles photos (GPU, parallèle) |
| `python facet.py --extract-faces-gpu-force` | Supprime tous les visages et les réextrait (GPU ; les personnes nommées sont conservées ; extracteur permissif en mode commercial) |
| `python facet.py --cluster-faces-incremental` | Clustering HDBSCAN, conserve toutes les personnes (CPU) |
| `python facet.py --cluster-faces-incremental-named` | Clustering, conserve uniquement les personnes nommées (CPU) |
| `python facet.py --cluster-faces-force` | Re-clustering complet, supprime toutes les personnes (CPU) |
| `python facet.py --suggest-person-merges` | Suggère des fusions de personnes possibles |
| `python facet.py --suggest-person-merges --merge-threshold 0.7` | Utilise un seuil plus strict |
| `python facet.py --refill-face-thumbnails-incremental` | Génère les miniatures de visages manquantes (CPU, parallèle) |
| `python facet.py --refill-face-thumbnails-force` | Régénère TOUTES les miniatures de visages (CPU, parallèle) |

## Gestion des miniatures

| Commande | Description |
|---------|-------------|
| `python facet.py --fix-thumbnail-rotation` | Fait pivoter les miniatures stockées pour qu'elles correspondent à l'orientation EXIF |
| `python facet.py --refresh-thumbnails` | Reconstruit les miniatures RAW à partir de l'aperçu intégré par le boîtier |
| `python facet.py --refresh-thumbnails --refresh-thumbnails-workers 16` | Idem, avec plus de lectures en parallèle |

**`--fix-thumbnail-rotation`** concerne les photos traitées avant la prise en charge de l'orientation EXIF. Il ne lit que l'en-tête EXIF et la miniature stockée.

**`--refresh-thumbnails`** régénère la miniature stockée de chaque photo RAW à travers le profil d'affichage (aperçu du boîtier en priorité, démosaïçage en repli ; voir [CONFIGURATION.md](CONFIGURATION.md#décodage-raw)). Utilisez-le sur une bibliothèque analysée avant l'existence de ce profil : les anciennes miniatures aplatissent les écarts d'exposition entre les vues d'un bracketing. Il ne charge aucun modèle et ne modifie aucun score.

- **La vitesse** dépend du débit du disque ou du réseau, pas du CPU. `--refresh-thumbnails-workers` (8 par défaut) définit le nombre de fichiers lus en même temps : augmentez-le sur un montage réseau rapide, réduisez-le sur un disque local lent. Des valeurs très élevées coûtent en mémoire.
- **Reprenable.** Arrêtez-le avec Ctrl-C et l'exécution suivante reprend où elle s'était arrêtée. Une exécution terminée repart de zéro la fois suivante.
- **Les rendus noirs** (par exemple d'un RAW tronqué) sont écartés : la photo garde son ancienne miniature, est journalisée par son nom et est retentée à l'exécution suivante.
- **Les vues de bracketing** sont rendues sans l'aperçu du boîtier ni gain d'exposition, de sorte que chaque vignette montre ce que le capteur a enregistré (voir [CONFIGURATION.md](CONFIGURATION.md#les-vues-dun-bracketing-saffichent-sans-correction)). Lancez-le après `--detect-sequences`.

### Ce qui met à jour une miniature stockée

Les miniatures sont créées au moment de l'analyse, donc une bibliothèque analysée avant l'existence du profil d'affichage garde l'ancien rendu dans la grille de la galerie. Deux choses les mettent à jour :

| Chemin | Couvre | Coût |
|------|--------|------|
| Une réanalyse (`python facet.py <répertoire>`) | Tout ce qu'elle analyse, miniature et histogramme | Analyse complète |
| `--refresh-thumbnails` | La miniature de chaque ligne RAW | Limité par le stockage, des heures sur une grande bibliothèque |

**Rien ne se passe tout seul.** La vue détail est toujours rendue à neuf, mais la grille de la galerie affiche la miniature stockée. Une bannière rejetable compte les lignes encore en attente. Ce compte peut retarder jusqu'à une heure après une réanalyse ; `--refresh-thumbnails` et `python database.py --refresh-stats` le mettent à jour.

## Diagnostics

| Commande | Description |
|---------|-------------|
| `python facet.py --doctor` | Exécute des contrôles de diagnostic (Python, GPU, ONNX Runtime, dépendances, config, base de données) |
| `python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16` | Simule du matériel GPU pour les diagnostics |

`--doctor` rapporte la version de Python, la build PyTorch/CUDA, le GPU et le pilote, la build et les fournisseurs d'ONNX Runtime, le profil VRAM recommandé, les dépendances optionnelles et l'état de la config et de la base de données. Sur CUDA, il teste aussi le chargement d'ONNX Runtime sur le GPU. Quand PyTorch ou ONNX Runtime n'est pas la bonne build, il affiche la commande `pip install` qui la corrige (voir [ONNX Runtime pour la détection de visages](INSTALLATION.md#onnx-runtime-pour-la-détection-de-visages)).

`--simulate-gpu NAME` et `--simulate-vram GB` nécessitent `--doctor` ; `--simulate-vram` nécessite aussi `--simulate-gpu`.

| Commande | Description |
|---------|-------------|
| `python facet.py --check-raw-rendering` | Rend 20 photos RAW échantillonnées avec les anciens et les nouveaux réglages de décodage |
| `python facet.py --check-raw-rendering 50` | Échantillonne 50 photos à la place |

Lecture seule. Elle affiche la luminance moyenne de chaque rendu : la luminosité automatique de LibRaw, le démosaïçage à gain fixe et l'aperçu du boîtier. Utilisez-la pour vérifier `raw_decode.bright` sur vos fichiers avant une analyse ou `--refresh-thumbnails`. Les colonnes fixe et aperçu conservent les écarts d'exposition d'un bracketing ; la luminosité automatique les aplatit.

## Informations sur les modèles

| Commande | Description |
|---------|-------------|
| `python facet.py --list-models` | Affiche les modèles disponibles et les exigences de VRAM |

## Optimisation des poids (comparaison par paires)

| Commande | Description |
|---------|-------------|
| `python facet.py --comparison-stats` | Affiche les statistiques de comparaison par paires |
| `python facet.py --optimize-weights` | Optimise les poids à partir de vos comparaisons ; appliqués seulement s'ils réussissent un test sur données écartées (voir la note) |
| `python facet.py --optimize-weights --optimize-force` | Applique les poids optimisés même s'ils échouent au test |
| `python facet.py --optimize-weights --optimize-sources vote,culling` | Entraîne uniquement sur ces sources de comparaison |
| `python facet.py --optimize-weights --optimize-category portrait` | Entraîne une catégorie et écrit son bloc `categories[].weights` v4 |
| `python facet.py --auto-tune-categories` | **Superadmin uniquement** (`--user` en mode multi-utilisateurs) : rapporte l'état de préparation des labels par catégorie (rapport uniquement) |
| `python facet.py --sync-label-comparisons` | Reconstruit les paires dérivées des notes (source=rating) à partir des étoiles, favoris et rejets |
| `python facet.py --train-ranker` | Entraîne le classeur personnel et écrit learned_scores s'il bat l'agrégat |
| `python facet.py --train-ranker --ranker-category portrait` | Entraîne le classeur sur une seule catégorie |
| `python facet.py --train-ranker --train-ranker-force` | Écrit learned_scores même si le seuil de précision n'est pas atteint |
| `python facet.py --train-ranker --user alice` | Entraîne sur les comparaisons de cet utilisateur et écrit ses learned_scores (mode multi-utilisateurs) |
| `python facet.py --train-keeper` | Entraîne la **tête de classement des photos à conserver** à partir de vos décisions de tri (voir la note) |
| `python facet.py --train-keeper --train-keeper-force` | Conserve la tête même si son seuil n'est pas atteint (respecte aussi `--ranker-category` et `--user`) |
| `python facet.py --report-unreviewed-bursts` | Compte les groupes de rafales pas encore examinés (lecture seule) |
| `python facet.py --eval-iqa-srcc` | Rapporte la concordance de chaque métrique IQA/esthétique avec vos notes en étoiles (SRCC ; lecture seule) |
| `python facet.py --evaluate-models SLOT` | Classe les modèles candidats d'un slot selon leur accord avec vos choix (lecture seule ; voir la note) |
| `python facet.py --mine-insights` | Rapport sur les labels, corrélations de métriques, catégories, dérive des percentiles et comparaisons |
| `python facet.py --mine-insights report.json` | Idem, et écrit le rapport complet en JSON |
| `python calibrate.py --db <path> --ava-annotations AVA.txt` | Calibre les poids de catégorie par rapport au [jeu de données AVA](https://github.com/imfing/ava_downloader) (lecture seule ; affiche des propositions) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --categories landscape,portrait --apply` | Limite à ces catégories et écrit les poids dans `scoring_config.json` |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --method nelder-mead` | Choisit l'optimiseur (`de` = évolution différentielle, par défaut ; `nelder-mead` = simplexe local) |
| `python calibrate.py --db <path> --ava-annotations AVA.txt --ava-tags` | Utilise aussi les étiquettes AVA (`--ava-tags-only` pour les étiquettes seules ; `--apply-filters` pour ajuster les seuils de filtre) |

**`--optimize-weights`** s'entraîne sur toutes les sources de comparaison, pondérées par la fiabilité. Les nouveaux poids ne sont appliqués que s'ils battent les actuels sur des comparaisons écartées (validation croisée à 5 plis, test de McNemar unilatéral, p < 0.05, gain d'au moins 2 points de pourcentage). L'application recentre aussi le `modifiers.bonus` de la catégorie : ses photos sont réordonnées au lieu d'être toutes décalées. Voir [SCORING.md](SCORING.md).

**`--train-keeper`** apprend à partir des paires `source='culling'` et n'est conservé que s'il bat l'heuristique du tri automatique sur des données écartées. Il alimente les choix du tri automatique et le badge « une meilleure photo existe dans ce groupe ». Tant qu'il n'y a pas assez de paires de tri, l'heuristique est utilisée. Il se réentraîne sur le même déclencheur que `--train-ranker`.

**`--evaluate-models SLOT`** slots : `aesthetic`, `quality`, `faces-detect`, `faces-recognize`, `faces-centroid`, `blink`, `face-quality`, `end-to-end`.

- `--candidates a,b` choisit les candidats (`stored:<colonne>` ou un nom enregistré).
- `--eval-out PATH` définit la sortie (par défaut `.facet_cache/eval/<slot>-<horodatage>.json`).
- Les slots de visages se comparent aux visages InsightFace stockés plutôt qu'à vos choix, ils ne conviennent donc qu'aux bibliothèques en mode par défaut : `faces-detect` (`yunet`, `yunet@<conf>`, `blazeface`), `faces-recognize` (`sface`, `sface@<seuil>`), `faces-centroid` (règle le `merge_threshold` de SFace / la fusion automatique), `blink` (balaie le seuil de clignement permissif).
- `--limit N` plafonne les photos (600 par défaut) ou les visages de référence (1200 par défaut).

## Configuration

`scoring_config.json` est une **surcharge** : il ne contient que les réglages que vous avez modifiés, par-dessus `config/scoring_config.default.json`. Sans fichier de configuration, Facet tourne sur les valeurs par défaut. Voir [Configuration](CONFIGURATION.md#valeurs-par-défaut-et-votre-surcharge).

Quel fichier est lu :

1. `--config` l'emporte toujours.
2. Sinon `FACET_CONFIG`, s'il est défini. Elle s'applique à `facet.py`, `database.py`, `tag_existing.py`, `diagnostics.py`, `calibrate.py` et `viewer.py`. `viewer.py` n'a pas de `--config` : c'est donc son seul moyen d'être redirigé.
3. Sinon, pour les outils CLI (pas `viewer.py`), un `scoring_config.json` dans le **répertoire de travail**, de sorte qu'une photothèque puisse embarquer sa propre configuration.
4. Sinon le fichier situé à côté de l'installation. S'il est absent, les valeurs par défaut livrées s'appliquent.

Un chemin désigné par `--config` ou `FACET_CONFIG` qui n'existe pas est une erreur, pas un « utiliser les valeurs par défaut ». La visionneuse journalise le chemin manquant et refuse de démarrer en mode ouvert.

> **Avertissement :** `viewer.py` ne lit jamais un `scoring_config.json` du répertoire où vous le lancez. Si vous le démarrez depuis une photothèque et que la racine de l'installation n'a pas de configuration, il tourne sur les valeurs par défaut : un `viewer.edition_password` vide et aucun mot de passe de visionneuse, donc tout le monde peut parcourir.

```bash
# 1. --config prime sur tout. Un fichier manquant est une ERREUR.
python facet.py --config /srv/facet/wedding.json /photos/wedding

# 2. $FACET_CONFIG fournit la valeur par défaut si --config est omis (Docker le définit).
export FACET_CONFIG=/config/scoring_config.json
python facet.py /photos            # lit /config/scoring_config.json
python facet.py --config other.json /photos   # --config prime toujours

# 3. Aucun des deux : un config du RÉPERTOIRE DE TRAVAIL prime pour les outils CLI.
cd /photos/client-shoot          # contient son propre scoring_config.json
python /opt/facet/facet.py .     # noté avec /photos/client-shoot/scoring_config.json

# 4. Aucun des deux et rien ici : repli sur le config situé à côté de l'installation.
cd /tmp
python /opt/facet/facet.py /photos   # lit /opt/facet/scoring_config.json
                                     # absent = tourne sur les valeurs par défaut livrées

# 5. viewer.py ne passe jamais par le répertoire de travail.
cd /photos/client-shoot          # contient son propre scoring_config.json -- sans effet ici
python /opt/facet/viewer.py      # lit toujours /opt/facet/scoring_config.json (ou $FACET_CONFIG)
```

| Commande | Description |
|---------|-------------|
| `python facet.py --validate-categories` | Valide les configurations de catégorie |

## Étiquetage

| Commande | Description |
|---------|-------------|
| `python tag_existing.py` | Étiquette les photos non étiquetées à partir des embeddings CLIP stockés |
| `python tag_existing.py --dry-run` | Prévisualise les étiquettes sans enregistrer |
| `python tag_existing.py --threshold 0.25` | Seuil de similarité personnalisé (par défaut : le `tag_threshold_percent` du profil, livré à 8, soit 0.08) |
| `python tag_existing.py --max-tags 3` | Limite les étiquettes par photo (par défaut : 5) |
| `python tag_existing.py --force` | Ré-étiquette toutes les photos |
| `python tag_existing.py --db custom.db` | Utilise une base de données personnalisée |
| `python tag_existing.py --config my.json` | Utilise une configuration personnalisée |

Sur CUDA, les profils SigLIP (`16gb`, `24gb`) encodent désormais le vocabulaire d'étiquettes en fp16, ce qui change les étiquettes de quelques photos. Lancez `python tag_existing.py --force` pour ré-étiqueter les photos étiquetées auparavant. Le CPU et les profils `legacy`/`8gb` ne changent pas.

L'étape d'étiquetage en fin d'analyse est ignorée quand `tagging.enabled` vaut `false` ou qu'aucune photo n'attend d'étiquettes.

## Validation de la base de données

| Commande | Description |
|---------|-------------|
| `python validate_db.py` | Valide la cohérence de la base de données (interactif) |
| `python validate_db.py --auto-fix` | Corrige automatiquement tous les problèmes |
| `python validate_db.py --report-only` | Rapporte sans demander de confirmation |
| `python validate_db.py --db custom.db` | Valide une base de données personnalisée |

Vérifications : plages de scores, métriques de visages, corruption de BLOB, tailles d'embeddings, visages orphelins, valeurs statistiques aberrantes.

## Maintenance de la base de données

| Commande | Description |
|---------|-------------|
| `python database.py` | Initialise ou met à niveau le schéma et construit les index manquants (voir la note) |
| `python database.py --info` | Affiche les informations du schéma |
| `python database.py --migrate-tags` | Mise en place unique de la table de recherche des étiquettes (filtres d'étiquettes 10 à 50 fois plus rapides) |
| `python database.py --rebuild-fts` | Reconstruit l'index de recherche plein texte à partir des légendes et étiquettes |
| `python database.py --populate-vec` | Remplit la table de recherche vectorielle sqlite-vec à partir des embeddings |
| `python database.py --refresh-stats` | Rafraîchit le cache de statistiques |
| `python database.py --compact-config` | Retire de `scoring_config.json` toute valeur égale à la valeur par défaut livrée (prend d'abord une sauvegarde en `0600`) |
| `python database.py --stats-info` | Affiche l'état et l'ancienneté du cache |
| `python database.py --vacuum` | Récupère de l'espace, défragmente |
| `python database.py --analyze` | Met à jour les statistiques du planificateur de requêtes |
| `python database.py --optimize` | Exécute VACUUM et ANALYZE |
| `python database.py --backup` | Écrit un instantané horodaté et sûr pour le WAL (conserve `--keep N`, 3 par défaut) |
| `python database.py --export-viewer-db` | Exporte une base de données de visionneuse allégée (sans BLOB, miniatures réduites ; incrémental) |
| `python database.py --export-viewer-db --force-export` | Force une réexportation complète |
| `python database.py --cleanup-orphaned-persons` | Supprime les personnes sans visages |
| `python database.py --cleanup-missing-photos` | Supprime les photos qui ne sont plus sur le disque, avec leurs étiquettes, visages et entrées d'albums |
| `python database.py --cleanup-missing-photos --dry-run` | Liste les fichiers manquants sans supprimer |
| `python database.py --cleanup-missing-photos --force` | Procède même si toutes les photos semblent manquantes (voir l'avertissement) |
| `python database.py --relink-photos` | Met à jour les chemins des photos que vous avez déplacées vous-même (aperçu par défaut). Voir [Relier des photos déplacées](#relier-des-photos-déplacées) |
| `python database.py --migrate-storage-fs` | Déplace les miniatures et embeddings de la base de données vers le système de fichiers |
| `python database.py --migrate-storage-db` | Déplace les miniatures et embeddings du système de fichiers vers la base de données |
| `python database.py --add-user alice --role admin` | Ajoute un utilisateur (demande un mot de passe) |
| `python database.py --add-user alice --role user --display-name "Alice"` | Ajoute un utilisateur avec un nom d'affichage |
| `python database.py --migrate-user-preferences --user alice` | Copie les notes des photos vers user_preferences |

**`python database.py`** construit aussi les index manquants de la galerie (voir [VIEWER.md](VIEWER.md#index-de-la-galerie-et-cache-des-comptages)). Sur une grande bibliothèque, lancez-le une fois avant de démarrer la visionneuse ; cela peut prendre environ une minute. Sinon la visionneuse les construit en arrière-plan et refuse les enregistrements entre-temps.

**`--migrate-tags`** n'est nécessaire qu'une fois. Ensuite, les analyses, `--recompute-tags`, `--recompute-tags-vlm` et `tag_existing.py` tiennent la table à jour. Tant qu'elle n'est pas peuplée, les filtres d'étiquettes utilisent une recherche `LIKE` plus lente.

**`--cleanup-missing-photos`** vide aussi l'index vectoriel et remet à zéro les compteurs de comparaisons du réentraînement automatique. L'état de la bibliothèque (modèles entraînés, état de synchronisation Immich, instantané de percentiles) est conservé.

> **Avertissement :** sans `--force`, `--cleanup-missing-photos` s'arrête quand toutes les photos semblent manquantes, ce qui signifie généralement qu'un volume est démonté. Vérifiez le montage avant d'ajouter `--force`.

**Astuce de performance :** pour les grandes bases de données (50k+ photos), exécutez `--migrate-tags`, `--rebuild-fts` et `--populate-vec` une fois, puis `--optimize` de temps en temps.

## Visionneuse web

| Commande | Description |
|---------|-------------|
| `python viewer.py` | Démarre le serveur sur http://localhost:5000 (API + SPA Angular) |
| `python viewer.py --port 5001` | Lie un autre port (ou définit la variable d'environnement `PORT` ; 5000 par défaut) |
| `python viewer.py --host 127.0.0.1` | Lie une interface précise (`0.0.0.0` par défaut) |
| `python viewer.py --production` | Mode production (workers uvicorn) |
| `python viewer.py --production --workers 4` | Mode production avec N workers (1 par défaut) |

## Tri en ligne de commande

Tri automatique sans interface : la version terminal du [tri automatique](VIEWER.md#tri-automatique) de la visionneuse. Les rejets sont écrits dans la base de données. Les originaux ne sont jamais déplacés ni supprimés ; `--copy-keepers` copie les photos conservées vers un dossier.

| Commande | Description |
|---------|-------------|
| `python facet.py --auto-cull [PATH]` | Trie les photos déjà dans la base sous `PATH` (dossier ou fichier ; aucun ou `all` = toute la bibliothèque). **Simulation par défaut** |
| `python facet.py /path --auto-cull` | Analyse `/path`, puis trie les photos qu'il contient |
| `--apply` | Écrit le tri : rejets, marques de groupes revus et paires de comparaison `source='culling'` |
| `--copy-keepers DIR` | Copie dans `DIR` chaque photo non rejetée de la portée, avec ses compagnons RAW / `.xmp` de même nom |
| `--cull-strictness N` | Budget de photos conservées de 0 à 100, plus élevé = moins de photos conservées par groupe (défaut : `auto_cull.default_strictness`) |
| `--cull-min-keep N` | Nombre minimal de photos conservées par groupe (défaut `1`) |
| `--cull-group-by {all,burst,similar,scene}` | Groupes à trier (défaut `all`) |
| `--cull-min-score X` | Rejette aussi les photos isolées dont le score global est inférieur à `X` |
| `--cull-trim-brackets` | Rejette aussi les vues redondantes des bracketings d'exposition (le `trim_brackets` de la visionneuse) |
| `--user NAME` | Utilisateur dont les notes et rejets sont utilisés ; **obligatoire** sur une installation multi-utilisateurs |

- **Simulation.** Sans `--apply`, rien n'est écrit et le dossier de `--copy-keepers` n'est pas créé. Le récapitulatif liste `groups`, `kept`, `rejected_by_groups`, `rejected_by_score`, `spanning_skipped` et, avec `--copy-keepers`, `keepers`, `copied`, `already_present`, `skipped`, `errors` (`would_reject_*` / `would_copy` en simulation). `--dry-run` lui-même est refusé. Si un modèle de photos à conserver entraîné doit voir ses poids corrigés, son chargement peut quand même réécrire `scoring_config.json`.
- **Analyse puis tri** analyse toujours réellement ; le tri ne s'exécute que si l'analyse s'est terminée. Il ne peut pas être combiné avec `--auto-cull PATH`, `--resume`, `--retry-failed` ni `--watch`.
- **Règles.** Les mêmes que le [tri automatique de la visionneuse](VIEWER.md#tri-automatique) : chaque groupe conserve sa meilleure photo plus toutes celles dans la marge de sévérité, au moins `--cull-min-keep`. Les bracketings, panoramas et panoramas HDR sont conservés entiers. `--apply` marque les photos conservées **Conserver** et enregistre les paires de comparaison comme `POST /api/culling/auto` ; aucun album Coups de cœur n'est rempli.
- **Config.** Les réglages [`auto_cull`](CONFIGURATION.md#tri-automatique), `burst_scoring` et `similarity_groups` viennent de la configuration du **serveur** (`FACET_CONFIG` ou le chemin par défaut), pas de `--config`. Si les deux divergent sur le mode multi-utilisateurs, la commande se termine avec le code 1.
- **Portée.** Elle correspond aux chemins réels locaux, donc les lignes enregistrées avant la définition d'un `path_mapping` ne peuvent pas être limitées par dossier : utilisez `all` ou réanalysez. Une rafale, un bracketing ou un panorama en partie hors portée est ignoré en entier (`spanning_skipped`). Les groupes de photos similaires et de scènes sont calculés à l'intérieur de la portée.
- **`--cull-min-score`** (CLI uniquement) ne rejette jamais les vues de bracketing ou de panorama, les photos sans score, les favoris, les photos notées ou **Conserver**, ni les photos qu'un tri précédent a déjà jugées, si bien qu'une deuxième exécution ne rejette rien de nouveau. Il épargne toujours les membres d'une rafale. Il épargne les membres d'un groupe de photos similaires quand le calcul des groupes les a trouvés (il lit les `similarity_groups.max_photos` photos les plus récentes de la portée, `10000` par défaut, et écarte les groupes plus grands que `similarity_groups.max_group_size`, `50` par défaut). Il n'épargne les membres d'un groupe de scène qu'avec `--cull-group-by scene`.
- **Copie.** Les photos rejetées et leurs compagnons ne sont jamais copiés. Les fichiers de même nom venant de dossiers différents reçoivent un suffixe `_1` ; une relance ignore les fichiers identiques (`already_present`). `DIR` ne doit ni être, ni contenir, ni se trouver dans la portée, la bibliothèque ou un dossier que Facet a déjà analysé (code 1, vérifié aussi en simulation). Les fichiers doivent se trouver dans la liste blanche des dossiers analysés (`users.*.directories` / `viewer.scan_directories`) ; si toutes les photos sont ignorées à cause d'elle, la commande se termine avec le code 3.
- **Utilisateurs.** Sur une installation multi-utilisateurs, `--user` est obligatoire (code 1 sans lui, ou avec un utilisateur inconnu). Sur une installation mono-utilisateur, `--user` est ignoré avec un avertissement et la commande voit toutes les photos même si un mot de passe de visionneuse est défini. `--apply` prend le verrou de la bibliothèque ; une simulation n'en prend aucun.
- **Erreurs d'usage (code 2).** `--apply`, `--copy-keepers` ou un `--cull-*` sans `--auto-cull` ; `--dry-run`, `--resume`, `--retry-failed` ou `--watch` avec `--auto-cull` ; `--auto-cull PATH` avec des dossiers positionnels ; sévérité hors de 0–100 ; `--cull-min-keep` inférieur à 1. `--apply` doit être tapé en entier (il n'abrège plus `--apply-recommendations`).
- **Codes de sortie.** `0` succès (simulation et zéro groupe compris) ; `1` échec de prérequis, de configuration ou de base de données ; `2` erreur d'usage ; `75` le verrou de la bibliothèque est détenu par un autre travail ; `3` le tri a réussi mais la copie a eu des erreurs ou n'a rien copié (une simulation où toutes les photos à conserver seraient ignorées se termine aussi avec le code `3`).
- **Réentraînement.** Il ne s'exécute pas dans la CLI. Le compteur de comparaisons persiste, et le réentraînement a lieu à la prochaine action dans la visionneuse ou avec une commande `--train-*`. La première exécution peut créer `.facet_secret`.

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

### Trier une séance depuis le terminal
```bash
python facet.py --auto-cull /photos/wedding                     # Aperçu du plan, rien n'est écrit
python facet.py --auto-cull /photos/wedding --apply \
    --copy-keepers ~/wedding-keepers                             # Rejette, puis copie les photos conservées
python facet.py /photos/new-shoot --auto-cull --apply --cull-min-score 5   # Analyse, puis tri
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
# Modifie scoring_config.json : "tagging": {"model": "clip"}
python facet.py --recompute-tags     # Ré-étiquette avec le nouveau modèle
```

### Changement de profil VRAM
```bash
# Modifie scoring_config.json : "vram_profile": "auto"
# Ou utilise un profil spécifique : "vram_profile": "8gb"
python facet.py --compute-recommendations  # Vérifie les distributions
python facet.py --recompute-average        # Applique les nouveaux poids
```

## Relier des photos déplacées

Après avoir déplacé vous-même des fichiers, `python database.py --relink-photos` prévisualise les correspondances ancien → nouveau chemin et conserve les données en base de chaque photo. L'aperçu est le mode par défaut.

- **Appliquer** exige l'ID du plan enregistré et `--acknowledge-unverified-identity`, car Facet ne peut pas prouver que le nouveau fichier est l'original. Arrêtez les visionneuses et les analyses, et examinez d'abord le plan.
- **Refusés :** les chemins hors de vos racines configurées ou de la visibilité de l'utilisateur, les copies, les noms ambigus, les plans périmés et les correspondances de chemins.
- **Les compagnons** doivent être listés explicitement ; les types incluent `sidecar_facet` pour `photo.ext.facet.xmp`. Les rectangles manuels nécessitent une révision dans l'éditeur. L'état Immich reste inchangé.
- **Les plans** sont enregistrés en privé (0600 sous POSIX).
- **Montages :** un dossier lisible ne prouve pas qu'un volume est monté, donc `source_mount_status` reste `not_verified`. Confirmez que l'original a été déplacé, et non mis hors ligne.
- **Codes de sortie :** 75 signifie qu'un autre travail détient le verrou de la bibliothèque ; 1 signifie que le verrou est inutilisable. L'aperçu ne prend aucun verrou.

Voir [Relier une photo déplacée](RELINK.md) pour le contrat complet et des exemples.
