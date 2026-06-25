# Galerie web

> 🌐 [English](../VIEWER.md) · **Français** · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md)

Application monopage FastAPI + Angular pour parcourir, filtrer et gérer les photos.

## Sommaire

- [Démarrage de la galerie](#démarrage-de-la-galerie) · [Authentification](#authentification) · [Options de filtrage](#options-de-filtrage) · [Tri](#tri) · [Fonctionnalités de la galerie](#fonctionnalités-de-la-galerie)
- [Gestion des personnes](#gestion-des-personnes) · [Déclenchement de scan (Superadmin)](#déclenchement-de-scan-superadmin) · [Recherche sémantique](#recherche-sémantique) · [Albums](#albums)
- [Critique IA](#critique-ia) · [Légendage IA](#légendage-ia-gpu-16gb24gb-edition) · [Souvenirs (« Ce jour-là »)](#souvenirs--ce-jour-là-) · [Vue Chronologie](#vue-chronologie) · [Vue Carte](#vue-carte) · [Capsules](#capsules)
- [Vue Dossiers](#vue-dossiers) · [Boîte de dialogue Filtre GPS](#boîte-de-dialogue-filtre-gps) · [Suggestions de fusion](#suggestions-de-fusion) · [Export vers l'éditeur](#export-vers-léditeur) · [Tri](#tri-1) · [Mode de comparaison par paires](#mode-de-comparaison-par-paires)
- [Statistiques EXIF](#statistiques-exif) · [Raccourcis clavier](#raccourcis-clavier-galerie) · [Annuler](#annuler) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile)
- [Configuration](#configuration) · [Performance](#performance) · [Points de terminaison de l'API](#points-de-terminaison-de-lapi) · [Dépannage](#dépannage)

> Les **prérequis des fonctionnalités** sont indiqués en ligne : `[GPU]` · `[16gb/24gb]` (profil VRAM) · `[Edition]` (mot de passe d'édition) · `[Superadmin]`. Voir la [matrice des fonctionnalités](../README.md#feature-availability--requirements).

## Démarrage de la galerie

### Production

```bash
python viewer.py
# Ouvrir http://localhost:5000
```

Ceci sert à la fois l'API et l'application Angular pré-compilée sur un seul port.

Pour un débit plus élevé, lancez en mode production (Uvicorn, sans rechargement automatique). Ajoutez `--workers N` pour monter en charge (par défaut 1) :

```bash
python viewer.py --production --workers 4
```

### Développement

Lancez le serveur API et le serveur de développement Angular séparément :

```bash
# Terminal 1 : serveur API
python viewer.py
# API disponible sur http://localhost:5000

# Terminal 2 : serveur de développement Angular avec rechargement à chaud
cd client && npx ng serve
# Ouvrir http://localhost:4200 (proxy des appels API vers :5000)
```

## Authentification

### Mode mono-utilisateur (par défaut)

Protection par mot de passe optionnelle via la configuration :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Lorsqu'il est défini, les utilisateurs doivent s'authentifier avant d'accéder à la galerie. Un `edition_password` optionnel donne accès à la gestion des personnes et au mode de comparaison.

### Mode multi-utilisateur

Pour les scénarios de NAS familial où chaque membre dispose de répertoires de photos privés. Activé en ajoutant une section `users` à `scoring_config.json` :

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

Les utilisateurs sont créés uniquement via la CLI (pas d'interface d'inscription) :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Voir [Configuration](CONFIGURATION.md#users) pour la référence complète.

### Rôles

| Rôle | Voir les siennes + partagées | Noter/favori | Gérer personnes/visages | Déclencher des scans |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Visibilité des photos

Chaque utilisateur voit les photos de ses répertoires configurés ainsi que les répertoires partagés. La visibilité est appliquée sur tous les points de terminaison : galerie, miniatures, téléchargements, statistiques, options de filtre et pages des personnes.

### Notes par utilisateur

En mode multi-utilisateur, les notes par étoiles, les favoris et les indicateurs de rejet sont stockés par utilisateur dans la table `user_preferences`. Chaque utilisateur note indépendamment — les favoris d'Alice n'affectent pas la vue de Bob.

Pour migrer les notes mono-utilisateur existantes :

```bash
python database.py --migrate-user-preferences --user alice
```

## Options de filtrage

<details><summary>Barre latérale de filtres — toutes les sections développées (cliquer pour afficher)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Barre latérale de filtres avec toutes les sections développées" width="360"></p>
</details>

### Filtres principaux

| Filtre | Options |
|--------|---------|
| **Type de photo** | Meilleurs choix, Portraits, Personnes dans la scène, Paysages, Architecture, Nature, Animaux, Art et statues, Noir et blanc, Basse lumière, Silhouettes, Macro, Astrophotographie, Rue, Pose longue, Aérien et drone, Concerts |
| **Niveau de qualité** | Bon (6+), Excellent (7+), Excellent (8+), Meilleur (9+) |
| **Appareil et objectif** | Filtrage par équipement |
| **Personne** | Filtrer par personne reconnue |
| **Catégorie** | Filtrer par catégorie de photo |

### Filtres avancés

| Catégorie | Filtres |
|----------|---------|
| **Date** | Date de début et de fin |
| **Scores** | Agrégat, esthétique, score TOPIQ, score de qualité |
| **Qualité étendue** | Esthétique IAA (mérite artistique), Qualité visage IQA, score LIQE |
| **Métriques visage** | Qualité visage, netteté des yeux, netteté visage, ratio visage, confiance visage, nombre de visages |
| **Composition** | Score de composition, points forts, lignes directrices, isolation, motif de composition |
| **Saillance du sujet** | Netteté du sujet, proéminence du sujet, placement du sujet, séparation du fond |
| **Technique** | Netteté, contraste, plage dynamique, niveau de bruit |
| **Couleur** | Score couleur, saturation, luminance, étendue de l'histogramme ; température de couleur (chaude/froide/neutre) et catégorie de teinte (nécessite `--recompute-colors`) |
| **Exposition** | Score d'exposition |
| **Notes utilisateur** | Note (étoiles) |
| **Réglages appareil** | ISO, ouverture (curseur de plage de f-stop), focale (curseur de plage) |
| **Contenu** | Tags, bascule monochrome |

### Motifs de composition

Filtrer par motifs détectés par SAMP-Net :
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Tri

Colonnes triables regroupées par catégorie (depuis `viewer.sort_options`) :

| Groupe | Colonnes |
|-------|---------|
| **Général** | Score agrégé, Esthétique, Score de qualité, Date de prise, Note (étoiles), Esthétique (IAA), Score LIQE |
| **Métriques visage** | Qualité visage, Qualité visage (IQA), Netteté des yeux, Netteté visage, Ratio visage, Nombre de visages |
| **Technique** | Netteté technique, Contraste, Niveau de bruit |
| **Couleur** | Score couleur, Saturation |
| **Exposition** | Score d'exposition, Luminance moyenne, Étendue de l'histogramme, Plage dynamique |
| **Composition** | Score de composition, Score points forts, Lignes directrices, Bonus d'isolation, Motif de composition |
| **Saillance du sujet** | Netteté du sujet, Proéminence du sujet, Placement du sujet, Séparation du fond |

### Mon goût

Une option de tri à part entière, basée sur le `learned_score` du classeur personnel (renommée depuis « Sélection pour vous »). Elle ordonne les photos selon ce que le classeur a appris de vos comparaisons A/B, de vos notes et de vos décisions de tri. Un badge de confiance à côté du tri indique la couverture apprise (% de photos disposant d'un score appris) et la précision du classeur sur des données de validation, pour juger à quel point se fier à l'ordre. Entraînez ou rafraîchissez le classeur avec `python facet.py --train-ranker`.

Contrôlée par `viewer.features.show_my_taste` (par défaut : `true`). L'état du classeur est exposé via `GET /api/ranker/status`.

## Fonctionnalités de la galerie

### Cartes photo

- Miniature avec badge de score
- Tags cliquables pour un filtrage rapide
- Avatars des personnes pour les visages reconnus
- Badge de catégorie

### Sélection multiple et actions groupées

- Cliquez sur les photos pour sélectionner, Maj+Clic pour une sélection de plage
- Une barre d'actions apparaît avec le nombre de sélections et les actions disponibles
- **Favori** — Marquer toute la sélection comme favorite (efface le rejet)
- **Rejeter** — Marquer toute la sélection comme rejetée (efface le favori et la note)
- **Noter** — Définir la note (étoiles) (1–5) pour toute la sélection, ou effacer la note
- **Ajouter à un album** — Ajouter la sélection à un album existant ou nouveau
- **Copier les noms de fichiers** — Copier les noms de fichiers sélectionnés dans le presse-papiers
- **Export** — Écrire des fichiers annexes XMP (note/favori/rejet) à côté des fichiers sélectionnés (voir [Export vers l'éditeur](#export-vers-léditeur))
- **Télécharger** — Télécharger les photos sélectionnées
- Effacer la sélection avec Échap ou le bouton Effacer

Les actions groupées nécessitent le mode édition. Double-cliquez sur une photo pour la télécharger directement.

### Options d'affichage

- **Mode de disposition** - Basculer entre **Grille** (cartes uniformes) et **Mosaïque** (rangées justifiées préservant les rapports d'aspect). La mosaïque est réservée au bureau ; le mobile utilise toujours la grille.
- **Taille des miniatures** - Curseur pour ajuster la hauteur des cartes/rangées (120–400 px, conservé dans localStorage)
- **Masquer les détails** - Masquer les métadonnées des photos sur les cartes (mode grille uniquement)
- **Masquer l'infobulle** - Désactiver l'infobulle au survol qui affiche les détails de la photo sur le bureau
- **Masquer les clignements** - Filtrer les photos avec des clignements détectés
- **Meilleure de la rafale** - Afficher uniquement la photo la mieux notée de chaque rafale
- **Défilement infini** - Les photos se chargent au fur et à mesure du défilement
- **Défilement rapide (virtualisé)** - Rendu par fenêtre de rangées : seules les
  rangées proches de la fenêtre d'affichage sont dans le DOM, de sorte que le
  défilement en profondeur à travers des dizaines de milliers de photos reste
  réactif. Activé par défaut ; désactivez-le dans la section Affichage de la barre
  latérale de filtres si vous rencontrez des problèmes de disposition (le mode
  grille avec détails affichés utilise toujours le rendu complet car les hauteurs
  de rangées n'y sont pas déterministes). Conservé dans
  localStorage (`facet_virtual_scroll`).

### Photos similaires

Cliquez sur le bouton « Similaires » sur n'importe quelle photo pour choisir un mode de similarité :

- **Visuel** (par défaut) — distance de Hamming pHash (70 %) + similarité cosinus CLIP/SigLIP (30 %). Repli sur CLIP uniquement lorsqu'aucun pHash n'est disponible.
- **Couleur** — intersection des histogrammes (70 %) + distance de saturation (10 %) + distance de luminance (10 %) + bonus monochrome (10 %). Pré-filtre par indicateur monochrome et plage de saturation.
- **Personne** — Trouve les photos contenant la ou les mêmes personnes. Utilise `person_id` lorsqu'il est disponible (rapide), sinon repli sur la similarité cosinus des embeddings de visage.

Utilisez le **curseur de seuil de similarité** (0–90 %) pour contrôler la rigueur de la correspondance (non affiché en mode personne). Le panneau prend en charge le défilement infini pour les grands ensembles de résultats.

### Puces de filtre

Les filtres actifs sont affichés sous forme de puces supprimables avec des compteurs en haut de la galerie.

## Gestion des personnes

> La consultation des personnes est ouverte à tous les visiteurs ; le renommage, la fusion, les changements d'avatar et l'assignation de visages nécessitent `[Edition]`.

### Filtre Personne

Le menu déroulant affiche les personnes avec des miniatures de visage. Cliquez pour filtrer la galerie.

### Galerie d'une personne

Cliquez sur le nom d'une personne pour voir toutes ses photos sur `/person/<id>`.

### Page Gérer les personnes

Accès via le bouton d'en-tête ou `/persons` :

| Action | Comment faire |
|--------|--------|
| **Fusionner** | Sélectionner la personne source, cliquer sur la cible, confirmer |
| **Supprimer** | Cliquer sur le bouton de suppression de la carte de la personne |
| **Renommer** | Cliquer sur le nom de la personne pour le modifier en ligne |
| **Séparer** | Ouvrir les visages d'une personne, sélectionner un sous-ensemble, les séparer en une nouvelle personne |
| **Masquer** | Masquer un cluster de la liste des personnes, des filtres et des suggestions de fusion (réversible) |

## Déclenchement de scan (Superadmin)

Lorsque `viewer.features.show_scan_button` vaut `true` et que l'utilisateur a le rôle `superadmin`, un bouton **Scanner des photos pour commencer** apparaît sur l'état de galerie vide. Il est livré réglé sur **`false`** dans `scoring_config.json` (activation à la discrétion du superadmin). Le bouton ouvre la boîte de dialogue de lancement du scan (`ScanLauncherComponent`).

- Choisissez un répertoire dans la liste du lanceur et démarrez le scan dans l'application
- Le lanceur diffuse la progression en direct (SSE avec repli automatique sur le polling) dans une `mat-progress-bar` pilotée par le champ structuré `progress`, plus un aperçu des lignes de sortie, et actualise la galerie une fois le scan terminé
- Le scan s'exécute comme un sous-processus en arrière-plan (`facet.py`) ; un seul scan à la fois (verrou global)
- Les choix de répertoires proviennent de `get_all_scan_directories()`, qui réunit les `directories` de chaque utilisateur, les répertoires partagés, les cibles de `path_mapping` et la liste autonome `viewer.scan_directories` — initialisez cette dernière (par exemple `/data/photos`) afin que les installations mono-utilisateur / Docker disposent d'une cible sélectionnable

Ceci est utile lorsque la galerie s'exécute sur la même machine disposant d'un accès GPU pour le scoring.

## Recherche sémantique

Recherche hybride combinant la similarité des embeddings CLIP/SigLIP (70 %) avec la correspondance textuelle FTS5 BM25 sur les légendes et les tags (30 %). Saisissez une requête comme « coucher de soleil sur les montagnes » ou « enfant jouant dans la neige » et la galerie renvoie les photos correspondantes classées par score combiné.

- Nécessite des données `clip_embedding` stockées (calculées lors du scoring)
- Utilise sqlite-vec pour la recherche vectorielle KNN lorsqu'il est installé, repli sur NumPy en mémoire
- La recherche textuelle FTS5 sur les légendes/tags IA fournit une correspondance par mot-clé supplémentaire (lancez `database.py --rebuild-fts` pour l'activer)
- Utilise le même modèle d'embedding que le profil VRAM actif (SigLIP 2 pour 16gb/24gb, CLIP ViT-L-14 pour legacy/8gb)
- `scope=text` restreint la requête aux correspondances FTS5 littérales dans le texte OCR/légende et ignore la recherche par embedding
- Contrôlé par `viewer.features.show_semantic_search` (par défaut : `true`)

## Albums

Organisez les photos en albums nommés. Accès via la route `/albums`.

### Albums manuels

Créez des albums et ajoutez des photos depuis la galerie à l'aide de la sélection multiple. Les albums prennent en charge :
- Nom et description
- Photo de couverture personnalisée
- Ordre personnalisé
- Parcourir le contenu de l'album sur `/album/:albumId`

### Albums intelligents

Enregistrez une combinaison de filtres (appareil, tag, personne, plage de dates, seuils de score, etc.) comme album intelligent. Les albums intelligents se mettent à jour dynamiquement à mesure que de nouvelles photos correspondent aux critères de filtre enregistrés. La combinaison de filtres est stockée au format JSON dans `smart_filter_json`.

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/albums` | Lister tous les albums |
| `POST /api/albums` | Créer un album |
| `GET /api/albums/{id}` | Obtenir les détails d'un album |
| `PUT /api/albums/{id}` | Mettre à jour un album (nom, description, couverture) |
| `DELETE /api/albums/{id}` | Supprimer un album |
| `GET /api/albums/{id}/photos` | Lister les photos d'un album (prend en charge `page`, `per_page`, `sort`, `sort_direction`) |
| `POST /api/albums/{id}/photos` | Ajouter des photos à un album |
| `DELETE /api/albums/{id}/photos` | Retirer des photos d'un album |

Contrôlé par `viewer.features.show_albums` (par défaut : `true`).

### Partage de photos

Partagez des albums avec des utilisateurs externes via des liens à jetons. Aucune authentification requise pour consulter les albums partagés.

| Action | Comment faire |
|--------|--------|
| **Partager** | Ouvrir l'album, cliquer sur le bouton « Partager » pour générer un lien partageable |
| **Révoquer** | Cliquer sur « Ne plus partager » pour invalider le jeton de partage |
| **Voir** | Les destinataires ouvrent le lien pour parcourir l'album partagé sur `/shared/album/:id` |

### API

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/albums/{id}/share` | Générer un jeton de partage pour un album |
| `DELETE /api/albums/{id}/share` | Révoquer le jeton de partage |
| `GET /api/shared/album/{id}?token=` | Voir l'album partagé (aucune authentification requise) |

## Critique IA

Décompose les scores d'une photo en points forts, points faibles et suggestions.

### Critique basée sur des règles

Disponible sur tous les profils VRAM. Analyse les métriques stockées (esthétique, composition, netteté, qualité visage, etc.) et génère une explication structurée du score.

### Critique VLM `[GPU]` `[16gb/24gb]`

Utilise le VLM configuré (Qwen3.5-2B ou Qwen3.5-4B) pour une critique tenant compte du contexte. Nécessite un profil VRAM 16gb ou 24gb et `viewer.features.show_vlm_critique: true`.

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/critique?path=<photo_path>&mode=rule` | Détail du score basé sur des règles |
| `GET /api/critique?path=<photo_path>&mode=vlm` | Critique propulsée par VLM (nécessite un GPU) |

Contrôlé par `viewer.features.show_critique` (par défaut : `true`) et `viewer.features.show_vlm_critique` (par défaut : `true`).

**Surcouche visuelle « pourquoi ce score ».** Lorsque `viewer.features.show_saliency_overlay` vaut `true` (par défaut), la boîte de dialogue de critique gagne un bouton **Afficher la surcouche** : il dessine la carte de saillance BiRefNet sous forme de carte thermique translucide par-dessus la photo (recalculée à la demande à partir de la miniature stockée — `GET /api/saliency_overlay`), plus des boîtes par visage atténuées et des marqueurs d'yeux reconstruits à partir des landmarks stockés (`GET /api/photo/face_markers`). Les boîtes sont vertes quand les yeux sont ouverts, ambre en cas de clignement. La carte thermique est illustrative (à la résolution de la miniature), non exacte au pixel près ; le bouton se masque de lui-même sur les profils où aucun masque de saillance n'est productible.

## Légendage IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenez une légende en langage naturel générée par IA pour n'importe quelle photo. Les légendes sont générées à la première requête et mises en cache dans la colonne de base de données `caption`. Les légendes peuvent être modifiées manuellement en mode édition via la page de détail de la photo. (La *traduction* des légendes s'exécute sur CPU — voir ci-dessous.)

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/caption?path=<photo_path>` | Obtenir ou générer la légende d'une photo |
| `PUT /api/caption` | Mettre à jour le texte de la légende (mode édition requis) |

Disponible également via la CLI pour la génération et la traduction en masse :

```bash
python facet.py --generate-captions      # Générer des légendes pour toutes les photos sans légende
python facet.py --translate-captions     # Traduire les légendes vers la langue cible configurée
```

La traduction des légendes utilise MarianMT (CPU, aucun GPU requis). Configurez la langue cible dans `scoring_config.json` sous `translation.target_language` (par défaut : `"fr"`). Langues prises en charge : français, allemand, espagnol, italien.

Contrôlé par `viewer.features.show_captions` (par défaut : `true`). Nécessite un profil VRAM 16gb ou 24gb pour le légendage basé sur VLM.

## Souvenirs (« Ce jour-là »)

Parcourez les photos prises à la même date calendaire les années précédentes. Une boîte de dialogue Souvenirs présente une rétrospective année par année des photos correspondantes.

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/memories?date=YYYY-MM-DD` | Obtenir les photos prises à cette date les années précédentes |

Contrôlé par `viewer.features.show_memories` (par défaut : `true`).

## Flux de travail courants

- **Trier des vacances** — ouvrez Capsules → recherchez la capsule `journey` générée automatiquement pour les dates du voyage. Chaque capsule propose une action Enregistrer en album.
- **Faire une revue jour par jour** — ouvrez Chronologie → triez par agrégat → parcourez l'année. Les meilleurs clichés remontent en premier lorsque vous avez activé `hide_bursts` et `hide_duplicates` (par défaut : activés).
- **Afficher ce qui est masqué** — la galerie masque par défaut les clignements / rafales non principales / doublons non principaux. Lorsqu'au moins un de ces filtres est actif et exclurait des rangées, une bannière « N photos masquées par les filtres actuels · Tout afficher » apparaît au-dessus de la grille.

## Vue Chronologie

Navigateur chronologique de photos avec navigation par date. Faites défiler les photos organisées par date avec une barre latérale affichant les années et mois disponibles.

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/timeline?cursor=&limit=&direction=` | Photos de chronologie paginées avec navigation par curseur |
| `GET /api/timeline/dates?year=&month=` | Dates disponibles pour la navigation par année/mois |

Accès via la route `/timeline`. Contrôlé par `viewer.features.show_timeline` (par défaut : `true`).

## Vue Carte

Visualisez les photos sur une carte interactive basée sur les coordonnées GPS extraites des données EXIF. Utilise Leaflet pour le rendu de la carte avec regroupement à différents niveaux de zoom.

### Configuration

Extraire les coordonnées GPS des photos existantes :

```bash
python facet.py --extract-gps    # Extraire les coordonnées GPS (lat/lng) de l'EXIF vers la base de données
```

Les coordonnées GPS sont également extraites automatiquement lors du scoring des nouvelles photos.

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/photos/map?bounds=&zoom=&limit=` | Photos dans les limites de la carte (regroupées par zoom) |
| `GET /api/photos/map/count` | Nombre total de photos géolocalisées |

Accès via la route `/map`. Contrôlé par `viewer.features.show_map` (par défaut : `true`).

## Capsules

Diaporamas de photos organisés et regroupés par thème. Accès via la route `/capsules`.

### Types de capsules

Les capsules sont générées automatiquement à partir de votre bibliothèque à l'aide de plusieurs algorithmes :

- **Voyage** — trajets détectés via le regroupement GPS, avec noms de destination géocodés en sens inverse (« Voyage à Rome — mars 2025 »)
- **Moments avec [Personne]** — meilleures photos de chaque personne reconnue
- **Palette saisonnière** — photos regroupées par saison + année
- **Collection dorée** — top 1 % par score agrégé
- **Palette de couleurs** — groupes visuellement similaires via le regroupement par embedding CLIP
- **Cette semaine, il y a des années** — « Ce jour-là » étendu sur ±3 jours
- **Lieu** — clusters de photos géolocalisées avec noms de lieux
- **Favoris** — photos favorites regroupées par année et saison
- **Basé sur les dimensions** — généré automatiquement à partir de l'appareil, l'objectif, la catégorie, le motif de composition, la plage de focales, le moment de la journée, la note (étoiles) et les combinaisons interdimensionnelles

### Diaporama

Cliquez sur n'importe quelle carte de capsule pour démarrer un diaporama. Fonctionnalités :
- **Transitions thématiques** — slide (voyages), zoom (portraits), kenburns (dorées/saisonnières), crossfade (par défaut)
- **Enchaînement automatique** — lorsqu'une capsule se termine, une carte de transition montre la capsule suivante avant de continuer
- **Mélange et reprise** — les photos sont mélangées pour plus de variété ; la position de reprise est suivie par capsule
- **Regroupement adaptatif** — les photos en mode portrait sont regroupées côte à côte selon le rapport d'aspect de la fenêtre d'affichage
- **Enregistrer en album** — enregistrer n'importe quelle capsule comme album permanent

### Fraîcheur

Les capsules tournent selon un calendrier configurable (par défaut : 24 heures). Les photos de couverture et les capsules de découverte avec graine s'alignent sur la même période de rotation. Le bouton « Régénérer » de l'en-tête force un rafraîchissement immédiat.

### Géocodage inverse

Les capsules de lieu et de voyage affichent les noms de lieux (par exemple « Paris, France ») au lieu des coordonnées. Ceci utilise le géocodage hors ligne via le paquet `reverse_geocoder` — aucun appel d'API nécessaire. Les résultats sont mis en cache dans la base de données.

Installation : `pip install reverse_geocoder`

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/capsules` | Liste paginée des capsules (en cache) |
| `GET /api/capsules/{id}/photos` | Photos d'une capsule spécifique |
| `POST /api/capsules/{id}/save-album` | Enregistrer une capsule comme album (mode édition) |

### Configuration

Voir [Configuration — Capsules](CONFIGURATION.md#capsules) pour tous les paramètres.

## Vue Dossiers

Parcourez votre bibliothèque de photos par structure de répertoires. Accès via la route `/folders`.

- Navigation par fil d'Ariane pour remonter dans l'arborescence des répertoires
- Chaque dossier affiche une photo de couverture (l'image la mieux notée de ce répertoire)
- Cliquez sur un dossier pour y descendre, ou cliquez sur une photo pour l'ouvrir dans la galerie
- Respecte la visibilité des répertoires multi-utilisateur en mode multi-utilisateur

## Boîte de dialogue Filtre GPS

Filtrez les photos par emplacement géographique à l'aide d'un sélecteur de carte interactif :

- Cliquez sur le bouton de filtre par localisation pour ouvrir la boîte de dialogue de carte
- Cliquez ou faites glisser sur la carte pour définir un point central
- Ajustez le curseur de rayon pour contrôler la zone de recherche
- Les photos situées dans le rayon sélectionné sont filtrées dans la galerie
- Nécessite des coordonnées GPS (lancez `--extract-gps` si les photos ont des données GPS EXIF)

## Suggestions de fusion

Trouvez des clusters de personnes qui pourraient être le même individu. Accès via `/merge-suggestions` ou depuis la page Gérer les personnes.

- **Curseur de seuil de similarité** — à quel point deux personnes doivent se ressembler pour être suggérées (plus bas = plus de suggestions, plus haut = moins)
- **Fusionner** — accepter une suggestion pour fusionner les deux personnes
- **Fusion par lot** — sélectionner plusieurs suggestions et les fusionner en une fois
- Les suggestions rejetées sont mémorisées et ne sont plus proposées
- Disponible également via la CLI : `python facet.py --suggest-person-merges`

## Export vers l'éditeur

Écrivez vos notes, favoris et rejets sur le disque sous forme de fichiers annexes XMP, afin que les éditeurs externes (darktable, Lightroom) les récupèrent. Nécessite le mode édition.

- **Depuis la galerie** — sélectionnez des photos, puis **Actions → Export** écrit un fichier annexe à côté de chaque fichier.
- **Depuis un album** (« panier ») — exportez l'album entier sous forme de fichiers annexes, ou copiez/liez (symlink) les fichiers vers un répertoire cible.

### API

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/photo/export_xmp` | Écrire un fichier annexe XMP (`path`, `overwrite` optionnel) |
| `POST /api/export/sidecars` | Écrire des fichiers annexes pour des `paths` explicites ou un ensemble de filtres |
| `POST /api/albums/{id}/export` | Export d'album — `mode` = `sidecars`, `copy` ou `symlink` (les deux derniers nécessitent `target_dir`) |

## Tri

La page de tri (`/culling`, mode édition) regroupe les clichés quasi identiques afin que vous puissiez conserver le meilleur de chacun et rejeter le reste. Deux sources de groupes :

- **Rafale** — photos prises rapprochées dans le temps (issues de la détection de rafales).
- **Similaire** — photos qui se ressemblent indépendamment de leur date de prise, regroupées par similarité d'embedding CLIP/SigLIP. Un curseur de seuil contrôle la rigueur du regroupement.

Pour chaque groupe, choisissez la ou les photos à conserver ; la confirmation rejette le reste. Les confirmations sont différées et peuvent être annulées (voir [Annuler](#annuler)).

### Badges par visage

Dans la visionneuse de tri (rafale/similaire), chaque visage détecté porte ses propres badges — yeux ouverts/fermés, expression médiocre et confiance de détection — au lieu d'un seul indicateur de clignement au niveau de la photo. Le tri des photos de groupe en est facilité : on voit d'un coup d'œil quel visage a les yeux fermés ou une expression faible. Les badges sont récupérés pour tout un groupe en un seul appel par lot (`POST /api/culling-group/faces`).

**Comparaison synchronisée (2 vues / 4 vues).** L'en-tête de la visionneuse comporte les boutons Vue unique / Comparer 2 / Comparer 4. En mode comparaison, les volets partagent une seule transformation de panoramique/zoom : le zoom à la molette ou le panoramique par glissement sur n'importe quel volet les déplace tous vers le cadrage identique — la façon de choisir le cliché le plus net d'une rafale en inspectant réellement les pixels. Le double-clic bascule entre ajuster ↔ zoomer ; au-delà de l'échelle d'ajustement, chaque volet remplace paresseusement sa miniature 1920px par la source `/image` en pleine résolution afin que l'inspection soit nette. Aucun changement côté backend — les deux routes d'image existent déjà. (Le pincement tactile n'est pas encore câblé ; utilisez la molette sur ordinateur de bureau.)

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/burst-groups` | Groupes de rafales pour le tri |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groupes paginés de photos visuellement similaires |
| `GET /api/culling-groups` | Groupes combinés de rafales et de similaires |
| `POST /api/culling-groups/confirm` | Confirmer les sélections de tri |
| `POST /api/culling-group/faces` | Badges par visage (yeux, expression, confiance) pour un groupe, en un seul lot |

## Vue Scènes

Regroupez les photos principales de rafale en « scènes » chronologiques afin de trier toute une séance dans l'ordre du récit. Les photos sont découpées en scènes selon les écarts entre prises de vue (une nouvelle scène commence dès que plus de `scenes.gap_hours` heures s'écoulent entre deux clichés consécutifs). Accès via la route `/scenes` (icône de navigation « theaters »).

- Chaque scène affiche ses photos principales dans l'ordre de prise de vue
- Touchez les photos pour les marquer en vue du tri ; la confirmation les rejette et alimente le classeur personnel
- Les scènes plus petites que `scenes.min_size` sont omises ; au plus `scenes.max_photos` photos sont chargées

### API

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/scenes` | Scènes chronologiques des photos principales de rafale |
| `POST /api/scenes/confirm` | Confirmer les sélections de tri de scène (rejette les photos marquées) |

Contrôlée par `viewer.features.show_scenes` (par défaut : `true`). Voir [Configuration — Scènes](CONFIGURATION.md#scènes) pour `gap_hours`, `min_size` et `max_photos`.

## Mode de comparaison par paires

Classez les photos en les jugeant deux à la fois. Les votes accumulés alimentent le réglage des poids. Accès via la route `/compare` (bouton Comparer dans l'en-tête). Nécessite un `edition_password` non vide (mono-utilisateur) ou un rôle `admin`/`superadmin` (multi-utilisateur).

La page comporte quatre onglets :

### Onglet Comparaison A/B

Paires de photos côte à côte. Choisissez un gagnant, marquez une égalité ou passez. Une barre de progression suit les votes vers 50, avec les compteurs courants de victoires A / victoires B / égalités. Un filtre de catégorie cadre la session, et un menu déroulant de stratégie de sélection contrôle la façon dont les paires sont choisies.

| Stratégie | Description |
|----------|-------------|
| `uncertainty` | Photos aux scores similaires (les plus informatives) |
| `boundary` | Plage de score 6–8 (zone ambiguë) |
| `active` | Photos ayant le moins de comparaisons (assure la couverture) |
| `random` | Paires aléatoires (référence) |

**Raccourcis clavier :**

| Touche | Action |
|-----|--------|
| `A` | La photo de gauche gagne |
| `B` | La photo de droite gagne |
| `T` | Égalité |
| `S` | Passer la paire |
| `Escape` | Fermer la fenêtre modale de remplacement de catégorie |

### Onglet Suggestions de poids

Affiche les poids appris à partir des comparaisons par rapport aux poids actuels, côte à côte, avec la précision du modèle avant/après. Les 10 meilleures photos actuelles et les 10 meilleures photos prédites après recalcul sont prévisualisées dans des colonnes adjacentes. **Appliquer** écrit les poids suggérés ; **Recalculer** réévalue la catégorie pour les appliquer (les deux nécessitent le mode édition).

### Onglet Poids

Éditeur de poids manuel : un curseur par métrique pour la catégorie sélectionnée avec un aperçu de score en direct. **Enregistrer** écrit dans `scoring_config.json` (avec une sauvegarde) ; **Recalculer les scores** les applique ; **Réinitialiser** recharge les poids stockés.

### Onglet Instantanés

Enregistrez les poids actuels comme instantané nommé et restaurez n'importe quel instantané antérieur.

### Remplacement de catégorie

Pour réassigner la catégorie d'une photo depuis la vue de comparaison : modifiez le badge de catégorie, sélectionnez une catégorie cible, lancez « Analyser les conflits de filtre » pour voir quels filtres l'excluent, puis appliquez le remplacement.

## Statistiques EXIF

La page Statistiques (`/stats`) fournit des analyses réparties sur 5 onglets. Utilisez les sélecteurs de **catégorie** et de **plage de dates** dans la barre d'outils pour filtrer tous les graphiques sur un sous-ensemble spécifique de votre bibliothèque.

### Onglets

| Onglet | Description |
|-----|-------------|
| **Équipement** | Boîtiers, objectifs et combos (top 20 chacun) |
| **Réglages de prise de vue** | Distributions ISO, ouverture, focale, vitesse d'obturation |
| **Chronologie** | Photos dans le temps |
| **Catégories** | Analyses des catégories, gestion des poids et corrélations de scores |
| **Corrélations** | Graphiques de corrélation X/Y personnalisés avec regroupement |

### Onglet Catégories

Quatre sous-onglets :

| Sous-onglet | Description |
|---------|-------------|
| **Répartition** | Nombre de photos par catégorie, scores moyens, histogrammes de distribution des scores |
| **Poids** | Comparaison par graphique radar (jusqu'à 5 catégories), carte thermique des poids et éditeur de poids (mode édition) |
| **Corrélations** | Carte thermique de corrélation de Pearson montrant comment chaque dimension influence l'agrégat, vue détaillée au clic |
| **Chevauchement** | Analyse des chevauchements de filtres montrant quelles catégories partagent des photos correspondantes |

Chaque graphique dispose d'un bouton d'aide `?` activable expliquant comment le lire. Une bascule d'aide globale dans la barre des sous-onglets affiche les explications pour tous les sous-onglets.

### Éditeur de poids (mode édition)

Disponible dans le sous-onglet Poids lorsque le mode édition est actif :

1. Sélectionnez une catégorie dans le menu déroulant
2. Ajustez les curseurs de poids (un par métrique, devrait totaliser 100 %)
3. Utilisez « Normaliser à 100 » pour rééquilibrer automatiquement
4. Développez la section repliable Modificateurs pour ajuster les bonus/pénalités
5. L'**aperçu de la distribution des scores** affiche un histogramme avant/après en direct à mesure que vous déplacez les curseurs
6. Cliquez sur **Enregistrer** pour mettre à jour `scoring_config.json` (crée une sauvegarde horodatée)
7. Cliquez sur **Recalculer les scores** (apparaît après l'enregistrement) pour appliquer les nouveaux poids à toutes les photos de cette catégorie

Toutes les statistiques tiennent compte de l'utilisateur en mode multi-utilisateur — chaque utilisateur voit les analyses pour ses photos visibles uniquement.

## Raccourcis clavier (galerie)

| Touche | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Déplacer le focus clavier entre les cartes photo (colonnes en grille et rangées en mosaïque) |
| `Enter` | Ouvrir la photo focalisée |
| `Space` | Sélectionner / désélectionner la photo focalisée |
| `Ctrl+A` | Sélectionner toutes les photos chargées |
| `Escape` | Effacer la sélection / fermer le tiroir de filtres |
| `Shift+Click` | Sélectionner la plage de photos entre la dernière sélectionnée et celle cliquée |
| `Double-click` | Ouvrir la photo |
| `?` | Afficher la référence des raccourcis clavier (fonctionne sur toutes les pages) |

## Annuler

Les opérations groupées de favori/rejet/note et les confirmations de tri affichent
une notification avec une action **Annuler** pendant environ 7 secondes. Les
opérations groupées d'indicateurs sont validées immédiatement et annulées via des
appels d'API inverses (plafonnés à 500 photos) ; les confirmations de tri sont
différées — le groupe disparaît instantanément mais l'appel d'API ne se déclenche
qu'une fois la fenêtre d'annulation écoulée.

## Progressive Web App

La galerie embarque un manifeste d'application web et un service worker Angular
(builds de production uniquement) : elle peut être installée sur l'écran d'accueil,
la coque de l'application se charge hors ligne, et jusqu'à 1000 miniatures sont
mises en cache LRU pendant 7 jours. Les réponses de l'API ne sont jamais mises en
cache (sauf les bundles i18n avec une stratégie de fraîcheur), et la déconnexion
efface le cache des miniatures afin que les configurations multi-utilisateur
partageant un navigateur ne puissent pas divulguer les aperçus entre les comptes.
Une notification propose un rechargement lorsqu'une nouvelle version a été
déployée.

## Mobile

Sur les petits écrans, la barre de sélection groupée se réduit au nombre de
sélections, à effacer, tout sélectionner et un seul bouton **Actions** qui ouvre
une feuille du bas adaptée au tactile avec toutes les opérations groupées (favori,
rejet, note, albums, copie, téléchargement).

## Configuration

### Paramètres d'affichage

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Pagination

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Limites des menus déroulants

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Augmentez `min_photos_for_person` pour masquer les personnes avec peu de photos du menu déroulant de filtre.

### Seuils de qualité

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Filtres par défaut

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Poids des Meilleurs choix

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performance

### Grandes bases de données (50k+ photos)

Lancez ces commandes pour de meilleures performances :

```bash
python database.py --migrate-tags    # Requêtes de tags 10 à 50x plus rapides
python database.py --refresh-stats   # Précalculer les agrégations
python database.py --optimize        # Défragmenter la base de données
```

### SQLite asynchrone (opt-in, pour les chemins de lecture à forte concurrence)

`api.database.get_async_db()` est un gestionnaire de contexte asynchrone reposant
sur aiosqlite, parallèle à `get_db()`. Les points de terminaison sont actuellement
synchrones (FastAPI les délègue à un pool de threads de travail, ce qui convient à
une concurrence typique). Pour les chemins de lecture à forte concurrence
(>5 utilisateurs simultanés), les points de terminaison individuels peuvent être
migrés en :

1. Changer `def foo(...)` en `async def foo(...)`.
2. Remplacer `with get_db() as conn:` par `async with get_async_db() as conn:`.
3. Faire `await` sur chaque `.execute()` et `.fetchone()` / `.fetchall()`.
4. Garder les chemins d'écriture synchrones — aiosqlite sérialise de toute façon
   les écritures, et le pool de connexions du chemin synchrone les gère déjà.

Les candidats les plus sollicités du plan sont `/api/photos`, `/api/timeline`,
`/api/search`. Migrez-les un à la fois et faites des mesures de performance avant de promouvoir.

### Cache des statistiques

Agrégations précalculées avec un TTL de 5 minutes :
- Nombre total de photos
- Nombre de modèles d'appareils/objectifs
- Nombre de personnes
- Nombre de catégories et de motifs

Vérifier l'état :
```bash
python database.py --stats-info
```

### Chargement paresseux des filtres

Les menus déroulants de filtre se chargent à la demande via l'API :
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## Points de terminaison de l'API

La documentation interactive de l'API est disponible sur `/api/docs` (Swagger UI) et le schéma OpenAPI sur `/api/openapi.json`.

### Galerie

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/photos` | Liste de photos paginée avec filtres |
| `GET /api/photo` | Détails d'une photo unique |
| `GET /api/type_counts` | Nombre de photos par type |
| `GET /api/similar_photos/{path}` | Photos similaires (modes : `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Recherche sémantique texte-vers-image (`scope=text` = texte OCR/légende uniquement) |
| `GET /api/critique?path=&mode=` | Critique IA (basée sur des règles ou VLM) |
| `GET /api/ranker/status` | État du classeur personnel pour le tri « Mon goût » (% de couverture apprise, précision sur validation) |
| `GET /api/config` | Configuration de la galerie |

### Authentification

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/auth/login` | S'authentifier et recevoir un jeton |
| `POST /api/auth/edition/login` | Déverrouiller le mode édition |
| `POST /api/auth/edition/logout` | Verrouiller le mode édition (abandonner les privilèges, rester authentifié) |
| `GET /api/auth/status` | Vérifier l'état d'authentification |

### Miniatures et images

| Point de terminaison | Description |
|----------|-------------|
| `GET /thumbnail` | Miniature de la photo |
| `GET /face_thumbnail/{id}` | Miniature de recadrage de visage |
| `GET /person_thumbnail/{id}` | Miniature représentative de la personne |
| `GET /image` | Image en pleine résolution |

### Options de filtre

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/filter_options/cameras` | Modèles d'appareils avec compteurs |
| `GET /api/filter_options/lenses` | Modèles d'objectifs avec compteurs |
| `GET /api/filter_options/tags` | Tags avec compteurs |
| `GET /api/filter_options/persons` | Personnes avec compteurs |
| `GET /api/filter_options/patterns` | Motifs de composition |
| `GET /api/filter_options/categories` | Catégories avec compteurs |
| `GET /api/filter_options/apertures` | Valeurs de f-stop distinctes avec compteurs |
| `GET /api/filter_options/focal_lengths` | Focales distinctes avec compteurs |
| `GET /api/filter_options/colors` | Facettes de température de couleur et de catégorie de teinte avec compteurs |
| `GET /api/filter_options/metric_ranges` | Min/max observés et histogramme par métrique numérique (pour les bornes de curseur) |

### Opérations groupées

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marquer plusieurs photos comme favorites |
| `POST /api/photos/batch_reject` | Marquer plusieurs photos comme rejetées |
| `POST /api/photos/batch_rating` | Définir la note (étoiles) pour plusieurs photos |

### Personnes

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/persons` | Lister toutes les personnes |
| `POST /api/persons` | Créer une nouvelle personne, en y attachant éventuellement des visages (réservé à l'édition). Corps : `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Lister les personnes auto-groupées sans nom avec `face_count >= N` (par défaut depuis `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renommer une personne |
| `POST /api/persons/{id}/assign_faces` | Attacher en masse des visages à une personne ; les anciennes personnes vides sont supprimées automatiquement (réservé à l'édition). Corps : `{face_ids}` |
| `POST /api/persons/{id}/split` | Séparer un sous-ensemble des visages d'une personne en une nouvelle personne (réservé à l'édition). Corps : `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Masquer une personne de la liste, des filtres et des suggestions de fusion |
| `POST /api/persons/{id}/unhide` | Réafficher une personne précédemment masquée |
| `POST /api/persons/merge` | Fusionner deux personnes (corps JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Fusionner la personne source dans la cible |
| `POST /api/persons/merge_batch` | Fusionner plusieurs personnes en une fois |
| `POST /api/persons/merge_suggestions/reject` | Ignorer une suggestion de fusion afin qu'elle ne soit plus proposée |
| `POST /api/persons/{id}/delete` | Supprimer une personne |
| `POST /api/persons/delete_batch` | Supprimer plusieurs personnes en une fois |

### Albums

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/albums` | Lister tous les albums |
| `POST /api/albums` | Créer un album |
| `GET /api/albums/{id}` | Obtenir les détails d'un album |
| `PUT /api/albums/{id}` | Mettre à jour un album |
| `DELETE /api/albums/{id}` | Supprimer un album |
| `GET /api/albums/{id}/photos` | Lister les photos d'un album (paginé) |
| `POST /api/albums/{id}/photos` | Ajouter des photos à un album |
| `DELETE /api/albums/{id}/photos` | Retirer des photos d'un album |
| `POST /api/albums/{id}/share` | Générer un jeton de partage |
| `DELETE /api/albums/{id}/share` | Révoquer le jeton de partage |
| `GET /api/shared/album/{id}?token=` | Voir l'album partagé (sans authentification) |

### Souvenirs, Chronologie, Carte et Légendes

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/memories?date=` | Photos prises à cette date les années précédentes |
| `GET /api/memories/check` | Vérifier si des souvenirs existent pour une date |
| `GET /api/caption?path=` | Obtenir ou générer une légende IA |
| `PUT /api/caption` | Mettre à jour la légende d'une photo (mode édition) |
| `GET /api/timeline?cursor=&limit=&direction=` | Photos de chronologie paginées |
| `GET /api/timeline/dates?year=&month=` | Dates disponibles pour la navigation |
| `GET /api/timeline/years` | Années disponibles avec nombre de photos |
| `GET /api/timeline/months` | Mois disponibles pour une année |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Photos géolocalisées dans les limites |
| `GET /api/photos/map/count` | Nombre de photos géolocalisées |

### Statistiques

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/stats/overview` | Résumé global des statistiques de scoring |
| `GET /api/stats/score_distribution` | Données de l'histogramme de distribution des scores |
| `GET /api/stats/top_cameras` | Meilleurs appareils par nombre de photos |
| `GET /api/stats/categories` | Nombres et moyennes par catégorie |
| `GET /api/stats/gear` | Nombres d'appareils/objectifs/combos |
| `GET /api/stats/settings` | Distributions des réglages de prise de vue |
| `GET /api/stats/timeline` | Données de chronologie |
| `GET /api/stats/correlations` | Corrélations de métriques personnalisées |
| `GET /api/stats/categories/breakdown` | Nombre de photos et distributions de scores par catégorie |
| `GET /api/stats/categories/weights` | Poids et modificateurs des catégories depuis la config |
| `GET /api/stats/categories/correlations` | Corrélation r de Pearson par dimension par catégorie |
| `GET /api/stats/categories/metrics?category=X` | Valeurs brutes de métriques pour l'aperçu côté client |
| `GET /api/stats/categories/overlap` | Analyse des chevauchements de filtres entre catégories |
| `POST /api/stats/categories/update` | Mettre à jour les poids/modificateurs des catégories (mode édition) |
| `POST /api/stats/categories/recompute` | Recalculer les scores d'une catégorie (mode édition) |

### Mode de comparaison

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obtenir la prochaine paire de photos à comparer |
| `POST /api/comparison/submit` | Soumettre un résultat de comparaison |
| `POST /api/comparison/reset` | Réinitialiser les données de comparaison |
| `GET /api/comparison/stats` | Statistiques de session de comparaison |
| `GET /api/comparison/history` | Lister les comparaisons passées |
| `POST /api/comparison/edit` | Modifier un résultat de comparaison |
| `POST /api/comparison/delete` | Supprimer une comparaison |
| `GET /api/comparison/coverage` | Couverture des comparaisons par catégorie |
| `GET /api/comparison/confidence` | Métriques de confiance pour les scores appris |
| `GET /api/comparison/photo_metrics` | Métriques brutes des photos |
| `GET /api/comparison/category_weights` | Poids/filtres des catégories |
| `GET /api/comparison/learned_weights` | Poids suggérés à partir des comparaisons |
| `POST /api/comparison/preview_score` | Aperçu avec des poids personnalisés |
| `POST /api/comparison/suggest_filters` | Analyser les conflits de filtre |
| `POST /api/comparison/override_category` | Remplacer la catégorie d'une photo |
| `POST /api/recalculate` | Recalculer les scores avec les poids actuels |

### Tri des rafales

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/burst-groups` | Lister les groupes de rafales pour le tri |
| `POST /api/burst-groups/select` | Sélectionner les photos à conserver dans un groupe de rafales |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groupes de photos visuellement similaires |
| `POST /api/similar-groups/select` | Sélectionner les photos à conserver dans un groupe similaire |
| `GET /api/culling-groups?exclude_rejected=true&similarity_threshold=&page=&per_page=` | Groupes combinés de rafales et de similaires. `exclude_rejected` (par défaut `true`) masque les photos avec `is_rejected=1` ; les groupes avec moins de 2 photos restantes sont supprimés |
| `POST /api/culling-groups/confirm` | Confirmer les sélections de tri |
| `POST /api/culling-group/faces` | Badges par visage (yeux ouverts/fermés, expression, confiance) pour un groupe, en un seul lot |
| `GET /api/scenes` | Scènes chronologiques des photos principales de rafale |
| `POST /api/scenes/confirm` | Confirmer les sélections de tri de scène |

### Scan

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Démarrer un scan de scoring |
| `GET /api/scan/status` | Vérifier la progression du scan (structuré `progress` : `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progression en temps réel via Server-Sent Events ; le jeton est passé en paramètre de requête (l'API `EventSource` ne peut pas définir d'en-têtes), avec repli automatique sur l'interrogation de `/status` |
| `GET /api/scan/directories` | Lister les répertoires de scan configurés |

### Gestion des visages

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/person/{id}/faces` | Lister les visages d'une personne |
| `POST /api/person/{id}/avatar` | Définir le visage avatar de la personne |
| `GET /api/photo/faces` | Lister les visages détectés dans une photo |
| `POST /api/face/{id}/assign` | Assigner un visage à une personne |
| `POST /api/photo/assign_all_faces` | Assigner tous les visages d'une photo à une personne |
| `POST /api/photo/unassign_person` | Désassigner une personne d'une photo |

### Actions sur les photos

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/photo/set_rating` | Définir la note (étoiles) d'une photo |
| `POST /api/photo/toggle_favorite` | Basculer le statut favori |
| `POST /api/photo/toggle_rejected` | Basculer le statut rejeté |

### Gestion de la configuration

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/config/update_weights` | Mettre à jour les poids de scoring |
| `GET /api/config/weight_snapshots` | Lister les instantanés de poids enregistrés |
| `POST /api/config/save_snapshot` | Enregistrer les poids actuels comme instantané |
| `POST /api/config/restore_weights` | Restaurer les poids depuis un instantané |

### Suggestions de fusion

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/merge_suggestions` | Fusions de personnes suggérées basées sur la similarité des visages |

### Dossiers

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/folders` | Lister la structure des dossiers de photos |

### Téléchargement

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/download/options` | Types de téléchargement disponibles pour une photo (`path`, `is_shared` optionnel) |
| `GET /api/download` | Télécharger une photo (`path`, `type=original\|darktable\|raw`, `profile` optionnel) |

**Types de téléchargement :**

- `original` — Servir le fichier tel quel (JPG/HEIF) ou converti par rawpy en JPEG (fichiers RAW).
- `darktable` — Convertir le RAW associé avec un profil darktable nommé (nécessite le paramètre `profile`). Repli sur l'original si aucun RAW associé n'existe.
- `raw` — Servir le fichier RAW associé tel quel (non disponible dans les albums partagés).

Le point de terminaison `/api/download/options` détecte automatiquement les fichiers RAW associés et renvoie les options disponibles, y compris les profils darktable configurés. La galerie l'utilise pour peupler un menu de téléchargement par photo.

### Export vers l'éditeur

| Point de terminaison | Description |
|----------|-------------|
| `POST /api/photo/export_xmp` | Écrire un fichier annexe XMP (mode édition) |
| `POST /api/export/sidecars` | Écrire des fichiers annexes pour des chemins explicites ou un ensemble de filtres (mode édition) |
| `POST /api/albums/{id}/export` | Export d'album sous forme de fichiers annexes, copie ou symlink (mode édition) |

### Plugins

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/plugins` | Lister les plugins configurés |
| `POST /api/plugins/test-webhook` | Tester un plugin webhook |

### Santé

| Point de terminaison | Description |
|----------|-------------|
| `GET /health` | Vérification de santé du serveur |
| `GET /ready` | Vérification de disponibilité du serveur |
| `GET /metrics` | Métriques au format Prometheus : nombre de photos, couverture des embeddings, taille de la BD, mémoire du processus |

### Internationalisation

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/i18n/languages` | Lister les langues disponibles |
| `GET /api/i18n/{lang}` | Obtenir les traductions pour une langue |

### Options de filtre (supplémentaires)

| Point de terminaison | Description |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Géocoder en sens inverse des coordonnées en nom de lieu |

## Dépannage

| Problème | Solution |
|-------|----------|
| Chargement de page lent | Lancer `--migrate-tags` et `--optimize` |
| Filtres non affichés | Vérifier `--stats-info`, lancer `--refresh-stats` |
| Filtre Personne vide | Lancer `--cluster-faces-incremental` |
| Bouton Comparer manquant | Définir un `edition_password` non vide (mono-utilisateur) ou utiliser le rôle `admin`/`superadmin` (multi-utilisateur) |
| Mot de passe inopérant | Vérifier `viewer.password` (mono-utilisateur) ou vérifier le hachage du mot de passe (multi-utilisateur) |
| Un utilisateur ne voit pas les photos | Vérifier `directories` dans sa configuration utilisateur et `shared_directories` |
| Bouton Scan manquant | Nécessite le rôle `superadmin` et `viewer.features.show_scan_button: true` |
| La recherche ne renvoie aucun résultat | S'assurer que les photos ont des données `clip_embedding` (lancer d'abord le scoring) |
| Critique VLM indisponible | Nécessite un profil VRAM 16gb/24gb et `viewer.features.show_vlm_critique: true` |
| La carte n'affiche aucune photo | Lancer `--extract-gps` pour peupler les colonnes GPS, s'assurer que les photos ont des données GPS EXIF |
| Les légendes ne se génèrent pas | Nécessite un profil VRAM 16gb/24gb pour le légendage VLM |
| Chronologie vide | S'assurer que les photos ont des valeurs `date_taken` |
| Port 5000 utilisé | Lancer `python viewer.py --port 5001` (ou définir `PORT=5001`). Sur macOS, le récepteur AirPlay de ControlCenter occupe 5000 par défaut — choisissez un autre port ou désactivez le récepteur AirPlay dans Réglages Système → Général → AirDrop et Handoff. |
