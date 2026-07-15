# Visionneuse Web

> 🌐 [English](../VIEWER.md) · **Français** · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md)

Application monopage FastAPI + Angular pour parcourir, filtrer et gérer les photos.

## Sommaire

- [Démarrer la visionneuse](#démarrer-la-visionneuse) · [Authentification](#authentification) · [Options de filtrage](#options-de-filtrage) · [Tri](#tri) · [Fonctionnalités de la galerie](#fonctionnalités-de-la-galerie)
- [Gestion des personnes](#gestion-des-personnes) · [Déclenchement d'un scan (Superadmin)](#déclenchement-dun-scan-superadmin) · [Recherche sémantique](#recherche-sémantique) · [Albums](#albums)
- [Critique IA](#critique-ia) · [Légendage IA](#légendage-ia-gpu-16gb24gb-edition) · [Souvenirs (« Ce jour-là »)](#souvenirs--ce-jour-là-) · [Vue Chronologie](#vue-chronologie) · [Vue Carte](#vue-carte) · [Capsules](#capsules)
- [Vue Dossiers](#vue-dossiers) · [Boîte de dialogue Filtre GPS](#boîte-de-dialogue-filtre-gps) · [Suggestions de fusion](#suggestions-de-fusion) · [Export vers éditeur](#export-vers-éditeur) · [Tri sélectif](#tri-sélectif) · [Nettoyage des indésirables](#nettoyage-des-indésirables) · [Mode de comparaison par paires](#mode-de-comparaison-par-paires)
- [Statistiques EXIF](#statistiques-exif) · [Raccourcis clavier](#raccourcis-clavier-galerie) · [Annuler](#annuler) · [Application web progressive](#application-web-progressive) · [Mobile](#mobile)
- [Configuration](#configuration) · [Performances](#performances) · [Points d'accès API](#points-daccès-api) · [Dépannage](#dépannage)

> **Les prérequis des fonctionnalités** sont indiqués en ligne : `[GPU]` · `[16gb/24gb]` (profil VRAM) · `[Edition]` (mot de passe d'édition) · `[Superadmin]`. Voir la [matrice des fonctionnalités](../README.md#feature-availability--requirements).

## Démarrer la visionneuse

### Production

```bash
python viewer.py
# Open http://localhost:5000
```

Cela sert à la fois l'API et l'application Angular pré-compilée sur un seul port.

Pour un débit supérieur, lancez en mode production (Uvicorn, sans rechargement automatique). Ajoutez `--workers N` pour monter en charge (1 par défaut) :

```bash
python viewer.py --production --workers 4
```

### Développement

Lancez le serveur d'API et le serveur de développement Angular séparément :

```bash
# Terminal 1: API server
python viewer.py
# API available at http://localhost:5000

# Terminal 2: Angular dev server with hot reload
cd client && npx ng serve
# Open http://localhost:4200 (proxies API calls to :5000)
```

## Authentification

### Mode mono-utilisateur (par défaut)

Protection facultative par mot de passe via la configuration :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Lorsqu'il est défini, les utilisateurs doivent s'authentifier avant d'accéder à la visionneuse. Un `edition_password` facultatif donne accès à la gestion des personnes et au mode de comparaison.

### Mode multi-utilisateurs

Pour les scénarios de NAS familial où chaque membre dispose de répertoires photo privés. Activé en ajoutant une section `users` à `scoring_config.json` :

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

Les utilisateurs sont créés uniquement via la CLI (pas d'interface d'inscription) :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Voir [Configuration](CONFIGURATION.md#users) pour la référence complète.

### Rôles

| Rôle | Voir les siennes + partagées | Noter/favoris | Gérer personnes/visages | Déclencher des scans |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Visibilité des photos

Chaque utilisateur voit les photos de ses répertoires configurés ainsi que des répertoires partagés. La visibilité est appliquée sur tous les points d'accès : galerie, vignettes, téléchargements, statistiques, options de filtrage et pages des personnes.

### Notes par utilisateur

En mode multi-utilisateurs, les notes en étoiles, les favoris et les indicateurs de rejet sont stockés par utilisateur dans la table `user_preferences`. Chaque utilisateur note indépendamment — les favoris d'Alice n'affectent pas la vue de Bob.

Pour migrer des notes mono-utilisateur existantes :

```bash
python database.py --migrate-user-preferences --user alice
```

## Options de filtrage

<details><summary>Barre latérale de filtres complète — toutes les sections développées (cliquer pour voir)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Filter sidebar with every section expanded" width="360"></p>
</details>

### Filtres principaux

| Filtre | Options |
|--------|---------|
| **Type de photo** | Coups de cœur, Portraits, Personnes en scène, Paysages, Architecture, Nature, Animaux, Art & statues, Noir & blanc, Faible luminosité, Silhouettes, Macro, Astrophotographie, Rue, Pose longue, Aérien & drone, Concerts |
| **Niveau de qualité** | Bon (6+), Très bon (7+), Excellent (8+), Meilleur (9+) |
| **Appareil & objectif** | Filtrage basé sur l'équipement |
| **Personne** | Filtrer par personne reconnue |
| **Catégorie** | Filtrer par catégorie de photo |

### Filtres avancés

| Catégorie | Filtres |
|----------|---------|
| **Date** | Date de début et de fin |
| **Scores** | Agrégat, esthétique, score TOPIQ, score de qualité |
| **Qualité étendue** | Esthétique IAA (mérite artistique), Qualité du visage IQA, score LIQE |
| **Métriques de visage** | Qualité du visage, netteté des yeux, netteté du visage, proportion du visage, confiance de détection, nombre de visages |
| **Composition** | Score de composition, points de force, lignes directrices, isolation, motif de composition |
| **Saillance du sujet** | Netteté du sujet, prééminence du sujet, placement du sujet, séparation de l'arrière-plan |
| **Technique** | Netteté, contraste, plage dynamique, niveau de bruit |
| **Couleur** | Score de couleur, saturation, luminance, étalement de l'histogramme ; température de couleur (chaude/froide/neutre) et tranche de teinte (nécessite `--recompute-colors`) |
| **Exposition** | Score d'exposition |
| **Notes utilisateur** | Note en étoiles |
| **Réglages de l'appareil** | ISO, ouverture (curseur de plage de diaphragme), focale (curseur de plage) |
| **Contenu** | Tags, bascule monochrome |
| **Moments** | Confiance du moment narratif (curseur de plage 0–1 : `min_moment_confidence` / `max_moment_confidence`) |

### Motifs de composition

Filtrer par les motifs détectés par SAMP-Net :
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Tri

Colonnes triables regroupées par catégorie (depuis `viewer.sort_options`) :

| Groupe | Colonnes |
|-------|---------|
| **Général** | Score agrégé, Esthétique, Score de qualité, Date de prise de vue, Note en étoiles, Esthétique (IAA), Score LIQE |
| **Métriques de visage** | Qualité du visage, Qualité du visage (IQA), Netteté des yeux, Netteté du visage, Proportion du visage, Nombre de visages |
| **Technique** | Netteté technique, Contraste, Niveau de bruit |
| **Couleur** | Score de couleur, Saturation |
| **Exposition** | Score d'exposition, Luminance moyenne, Étalement de l'histogramme, Plage dynamique |
| **Composition** | Score de composition, Score des points de force, Lignes directrices, Bonus d'isolation, Motif de composition |
| **Saillance du sujet** | Netteté du sujet, Prééminence du sujet, Placement du sujet, Séparation de l'arrière-plan |
| **Contenu** | Confiance du moment (les NULL coulent) |

### My Taste

Une option de tri de premier ordre adossée au `learned_score` du classeur personnel (renommée depuis « Sélectionnées pour vous »). Elle ordonne les photos selon ce que le classeur a appris de vos comparaisons A/B, de vos notes et de vos décisions de tri. Un badge de confiance à côté du tri affiche la couverture apprise (% de photos disposant d'un score appris) et la précision en validation du classeur, afin de juger du degré de confiance à accorder à l'ordre. Entraînez ou rafraîchissez le classeur avec `python facet.py --train-ranker`.

Contrôlé par `viewer.features.show_my_taste` (par défaut : `true`). L'état du classeur est exposé via `GET /api/ranker/status`.

## Fonctionnalités de la galerie

### Cartes de photo

- Vignette avec badge de score
- Tags cliquables pour un filtrage rapide
- Avatars de personnes pour les visages reconnus
- Badge de catégorie

### Sélection multiple & actions groupées

- Cliquez sur les photos pour les sélectionner, Maj+Clic pour une sélection par plage
- Une barre d'actions apparaît avec le nombre d'éléments sélectionnés et les actions disponibles
- **Favori** — Marquer toute la sélection comme favorite (efface le rejet)
- **Rejeter** — Marquer toute la sélection comme rejetée (efface le favori et la note)
- **Noter** — Définir une note en étoiles (1–5) pour toute la sélection, ou effacer la note
- **Ajouter à un album** — Ajouter la sélection à un album existant ou nouveau
- **Copier les noms de fichiers** — Copier les noms de fichiers sélectionnés dans le presse-papiers
- **Exporter** — Écrire des sidecars XMP (note/favori/rejet) à côté des fichiers sélectionnés (voir [Export vers éditeur](#export-vers-éditeur))
- **Télécharger** — Télécharger les photos sélectionnées
- Effacez la sélection avec Échap ou le bouton Effacer

Les actions groupées nécessitent le mode édition. Double-cliquez sur n'importe quelle photo pour la télécharger directement.

### Options d'affichage

- **Mode de disposition** - Basculez entre **Grille** (cartes uniformes) et **Mosaïque** (lignes justifiées préservant les rapports d'aspect). La mosaïque est réservée au bureau ; le mobile utilise toujours la grille.
- **Taille des vignettes** - Curseur pour ajuster la hauteur des cartes/lignes (120–400px, conservé dans le localStorage)
- **Masquer les détails** - Masquer les métadonnées des photos sur les cartes (mode grille uniquement)
- **Masquer l'infobulle** - Désactiver l'infobulle au survol qui affiche les détails de la photo sur le bureau
- **Masquer les clignements** - Filtrer les photos avec des clignements détectés
- **Meilleure de la rafale** - N'afficher que la photo la mieux notée de chaque rafale
- **Défilement infini** - Les photos se chargent à mesure que vous défilez
- **Défilement rapide (virtualisé)** - Rendu fenêtré par ligne : seules les lignes
  proches de la zone d'affichage sont dans le DOM, de sorte que le défilement en
  profondeur à travers des dizaines de milliers de photos reste réactif. Activé par
  défaut ; désactivez-le dans la section Affichage de la barre latérale de filtres
  si vous rencontrez des problèmes de mise en page (le mode grille avec les détails
  affichés utilise toujours le rendu complet, car les hauteurs de ligne n'y sont pas
  déterministes). Conservé dans le localStorage (`facet_virtual_scroll`).

### Photos similaires

Cliquez sur le bouton « Similaires » de n'importe quelle photo pour choisir un mode de similarité :

- **Visuel** (par défaut) — distance de Hamming pHash (70%) + similarité cosinus CLIP/SigLIP (30%). Bascule sur CLIP seul lorsqu'aucun pHash n'est disponible.
- **Couleur** — Intersection d'histogrammes (70%) + distance de saturation (10%) + distance de luminance (10%) + bonus monochrome (10%). Préfiltre par l'indicateur monochrome et la plage de saturation.
- **Personne** — Trouve les photos contenant la ou les mêmes personnes. Utilise `person_id` lorsqu'il est disponible (rapide), sinon bascule sur la similarité cosinus des embeddings de visages.

Utilisez le **curseur de seuil de similarité** (0–90%) pour contrôler la rigueur de la correspondance (non affiché en mode personne). Le panneau prend en charge le défilement infini pour les grands ensembles de résultats.

### Puces de filtre

Les filtres actifs sont affichés sous forme de puces amovibles avec des compteurs en haut de la galerie.

## Gestion des personnes

> La consultation des personnes est ouverte à tous les visiteurs ; le renommage, la fusion, le changement d'avatar et l'attribution de visages nécessitent `[Edition]`.

### Filtre par personne

Le menu déroulant affiche les personnes avec des vignettes de visage. Cliquez pour filtrer la galerie.

### Galerie d'une personne

Cliquez sur le nom d'une personne pour voir toutes ses photos à `/person/<id>`.

### Page Gérer les personnes

Accessible via le bouton d'en-tête ou `/persons` :

| Action | Comment faire |
|--------|--------|
| **Fusionner** | Sélectionnez la personne source, cliquez sur la cible, confirmez |
| **Supprimer** | Cliquez sur le bouton de suppression de la carte de la personne |
| **Renommer** | Cliquez sur le nom de la personne pour l'éditer en ligne |
| **Scinder** | Ouvrez les visages d'une personne, sélectionnez un sous-ensemble, scindez-les en une nouvelle personne |
| **Masquer** | Masquez un cluster de la liste des personnes, des filtres et des suggestions de fusion (réversible) |

## Déclenchement d'un scan (Superadmin)

Lorsque `viewer.features.show_scan_button` vaut `true` et que l'utilisateur a le rôle `superadmin`, un bouton **Scanner des photos pour commencer** apparaît dans l'état de galerie vide. Il est livré réglé sur **`false`** dans `scoring_config.json` (activation explicite par le superadmin). Le bouton ouvre la boîte de dialogue de lancement de scan (`ScanLauncherComponent`).

- Choisissez un répertoire dans la liste du lanceur et démarrez le scan dans l'application
- Le lanceur diffuse la progression en direct (SSE avec repli automatique sur le polling) dans une `mat-progress-bar` pilotée par le champ structuré `progress`, plus une queue de lignes de sortie, et rafraîchit la galerie à la fin du scan
- Le scan s'exécute comme un sous-processus en arrière-plan (`facet.py`) ; un seul scan à la fois (verrou global)
- Les choix de répertoires proviennent de `get_all_scan_directories()`, qui réunit les `directories` de chaque utilisateur, les répertoires partagés, les cibles `path_mapping` et la liste autonome `viewer.scan_directories` — renseignez cette dernière (p. ex. `/data/photos`) pour que les installations mono-utilisateur / Docker disposent d'une cible sélectionnable

C'est utile lorsque la visionneuse tourne sur la même machine que celle disposant d'un accès GPU pour le scoring.

## Recherche sémantique

Recherche hybride combinant la similarité des embeddings CLIP/SigLIP (70%) avec la correspondance textuelle FTS5 BM25 sur les légendes et les tags (30%). Tapez une requête comme « sunset over mountains » ou « child playing in snow » et la visionneuse renvoie les photos correspondantes classées par score combiné.

- Nécessite des données `clip_embedding` stockées (calculées pendant le scoring)
- Utilise sqlite-vec pour la recherche vectorielle KNN lorsqu'il est installé, sinon bascule sur NumPy en mémoire
- La recherche textuelle FTS5 sur les légendes/tags IA fournit une correspondance par mots-clés supplémentaire (lancez `database.py --rebuild-fts` pour l'activer)
- Utilise le même modèle d'embedding que le profil VRAM actif (SigLIP 2 pour 16gb/24gb, CLIP ViT-L-14 pour legacy/8gb)
- `scope=text` restreint la requête aux correspondances FTS5 littérales dans le texte OCR/légende et ignore la recherche par embedding
- Contrôlé par `viewer.features.show_semantic_search` (par défaut : `true`)

## Albums

Organisez les photos en albums nommés. Accessible via la route `/albums`.

### Albums manuels

Créez des albums et ajoutez des photos depuis la galerie à l'aide de la sélection multiple. Les albums prennent en charge :
- Un nom et une description
- Une photo de couverture personnalisée
- Un ordre personnalisé
- La consultation du contenu de l'album à `/album/:albumId`

### Albums intelligents

Enregistrez une combinaison de filtres (appareil, tag, personne, plage de dates, seuils de score, etc.) en tant qu'album intelligent. Les albums intelligents se mettent à jour dynamiquement à mesure que de nouvelles photos correspondent aux critères de filtre enregistrés. La combinaison de filtres est stockée en JSON dans `smart_filter_json`.

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Contrôlé par `viewer.features.show_albums` (par défaut : `true`).

### Partage de photos

Partagez des albums avec des utilisateurs externes via des liens à jeton. Aucune authentification requise pour consulter les albums partagés.

| Action | Comment faire |
|--------|--------|
| **Partager** | Ouvrez l'album, cliquez sur le bouton « Partager » pour générer un lien partageable |
| **Révoquer** | Cliquez sur « Ne plus partager » pour invalider le jeton de partage |
| **Consulter** | Les destinataires ouvrent le lien pour parcourir l'album partagé à `/shared/album/:id` |

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

### Épreuvage client

Lorsque `viewer.features.show_proofing` est activé (par défaut `false`), un lien d'album partagé peut fonctionner en **mode épreuvage** : le client (sans compte) ouvre le lien de partage, saisit éventuellement un code PIN (`viewer.proofing.pin`), puis peut **mettre un cœur** aux photos et laisser des **commentaires** — un moyen léger de laisser un client choisir ses favoris parmi une livraison.

Les sélections du client sont totalement isolées de votre bibliothèque. Elles vivent dans une table dédiée `album_client_picks`, sont limitées aux photos de cet album, et ne touchent jamais vos propres favoris/notes (`photos.is_favorite` / `user_preferences`) ni n'entraînent le classeur personnel. En tant que propriétaire, vous lisez les sélections depuis une boîte de dialogue `[Edition]` sur la carte de l'album. Les sessions sont éphémères (`viewer.proofing.session_minutes`, par défaut 24 h) et cessent de fonctionner dès que l'album n'est plus partagé ou que l'épreuvage est désactivé.

Contrôlé par `viewer.features.show_proofing` (par défaut : `false`). Voir [Configuration — Épreuvage client](CONFIGURATION.md#client-proofing).

## Critique IA

Décompose les scores d'une photo en forces, faiblesses et suggestions.

### Critique basée sur des règles

Disponible sur tous les profils VRAM. Analyse les métriques stockées (esthétique, composition, netteté, qualité du visage, etc.) et génère une explication structurée du score.

La décomposition fait aussi apparaître les lignes explicables de **forme et d'harmonie colorimétrique** (symétrie, équilibre, entropie d'orientation des contours, complexité fractale, harmonie colorimétrique Matsuda — renseignées par `--recompute-form`), des **puces d'attributs de distorsion** pour tout défaut probable (flou de bougé, dominante colorée, suraccentuation, … — issues de `--recompute-distortions`), et une **note de teint** pour les portraits dont le chroma de peau s'écarte du naturel (`--recompute-skin-tone`). Ces trois éléments sont indicatifs — ils expliquent la photo, ils ne modifient pas l'agrégat — et chaque ligne ne s'affiche que lorsque sa colonne sous-jacente est renseignée.

### Critique VLM `[GPU]` `[16gb/24gb]`

Utilise le VLM configuré (Qwen3.5-2B ou Qwen3.5-4B) pour une critique tenant compte du contexte. Nécessite un profil VRAM 16gb ou 24gb et `viewer.features.show_vlm_critique: true`.

Le prompt est un prompt à paliers configurable (`critique.vlm`) qui injecte la décomposition complète des règles, les pénalités et l'EXIF, et la réponse est restituée sous forme **Observation / Évaluation / Suggestions**. Le résultat est mis en cache par photo (`photos.vlm_critique`) et traduit à la demande, avec un bouton **Régénérer** pour le recalculer. Il s'exécute sur la vignette stockée, si bien que les fichiers RAW sont critiqués correctement au lieu d'échouer en silence.

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Contrôlé par `viewer.features.show_critique` (par défaut : `true`) et `viewer.features.show_vlm_critique` (par défaut : `true`).

**Calque visuel « pourquoi ce score ».** Lorsque `viewer.features.show_saliency_overlay` vaut `true` (par défaut), la boîte de dialogue de critique gagne une bascule **Afficher le calque** : elle dessine la carte de saillance BiRefNet sous forme de carte de chaleur translucide par-dessus la photo (recalculée à la demande à partir de la vignette stockée — `GET /api/saliency_overlay`), plus des boîtes douces par visage et des marqueurs d'yeux reconstruits à partir des points de repère stockés (`GET /api/photo/face_markers`). Les boîtes sont vertes lorsque les yeux sont ouverts, ambre en cas de clignement. La carte de chaleur est illustrative (résolution de la vignette), pas exacte au pixel près ; la bascule se masque elle-même sur les profils où aucun masque de saillance ne peut être produit.

## Légendage IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenez une légende en langage naturel générée par IA pour n'importe quelle photo. Les légendes sont générées à la première demande et mises en cache dans la colonne de base de données `caption`. Les légendes peuvent être éditées manuellement en mode édition via la page de détail de la photo. (La *traduction* des légendes s'exécute sur le CPU — voir ci-dessous.)

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Également disponible via la CLI pour la génération et la traduction en masse :

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

La traduction des légendes utilise MarianMT (CPU, pas de GPU requis). Configurez la langue cible dans `scoring_config.json` sous `translation.target_language` (par défaut : `"fr"`). Langues prises en charge : français, allemand, espagnol, italien.

Contrôlé par `viewer.features.show_captions` (par défaut : `true`). Nécessite un profil VRAM 16gb ou 24gb pour le légendage basé sur VLM.

## Souvenirs (« Ce jour-là »)

Parcourez les photos prises à la même date du calendrier les années précédentes. L'ouverture des Souvenirs lance un diaporama plein écran aléatoire des photos correspondantes plutôt qu'une grille ; l'infobulle du bouton de navigation explique précisément ce qu'il fait.

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Contrôlé par `viewer.features.show_memories` (par défaut : `true`).

## Workflows courants

- **Trier des vacances** — ouvrez Capsules → recherchez la capsule `journey` générée automatiquement pour les dates du voyage. Chaque capsule offre une action Enregistrer comme album.
- **Parcourir une revue jour par jour** — ouvrez Chronologie → triez par agrégat → avancez à travers l'année. Les meilleurs clichés remontent en premier lorsque vous avez activé `hide_bursts` et `hide_duplicates` (par défaut : activés).
- **Afficher ce qui est masqué** — la galerie masque par défaut les clignements / rafales non-leaders / doublons non-leaders. Lorsqu'au moins un de ces filtres est actif et exclurait des lignes, une bannière « N photos masquées par les filtres actuels · Tout afficher » apparaît au-dessus de la grille.

## Vue Chronologie

Navigateur de photos chronologique avec navigation par date. Faites défiler les photos organisées par date avec une barre latérale affichant les années et les mois disponibles.

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Accessible via la route `/timeline`. Contrôlé par `viewer.features.show_timeline` (par défaut : `true`).

## Vue Carte

Visualisez les photos sur une carte interactive en fonction des coordonnées GPS extraites des données EXIF. Utilise Leaflet pour le rendu de la carte avec un regroupement aux différents niveaux de zoom.

### Configuration

Extraire les coordonnées GPS des photos existantes :

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

Les coordonnées GPS sont aussi extraites automatiquement pendant le scoring des nouvelles photos.

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Accessible via la route `/map`. Contrôlé par `viewer.features.show_map` (par défaut : `true`).

## Capsules

Diaporamas de photos sélectionnées regroupés par thème, lieu, personnes et période — cliquez sur une capsule pour la lire. Accessible via la route `/capsules`.

### Types de capsules

Les capsules sont générées automatiquement à partir de votre bibliothèque en utilisant plusieurs algorithmes :

- **Journey** — voyages détectés via le regroupement GPS, avec des noms de destination géocodés en sens inverse (« Journey to Rome — March 2025 »)
- **Moments with [Person]** — meilleures photos de chaque personne reconnue
- **Seasonal Palette** — photos regroupées par saison + année
- **Golden Collection** — top 1% par score agrégé
- **Color Story** — groupes visuellement similaires via le clustering d'embeddings CLIP
- **This Week, Years Ago** — « Ce jour-là » étendu sur ±3 jours
- **Location** — clusters de photos géolocalisées avec noms de lieux
- **Favorites** — photos favorites regroupées par année et saison
- **Basées sur des dimensions** — générées automatiquement à partir de l'appareil, l'objectif, la catégorie, le motif de composition, la plage de focale, le moment de la journée, la note en étoiles, ainsi que des combinaisons inter-dimensionnelles

### Diaporama

Cliquez sur n'importe quelle carte de capsule pour démarrer un diaporama. Fonctionnalités :
- **Transitions thématiques** — slide (journeys), zoom (portraits), kenburns (golden/seasonal), crossfade (par défaut)
- **Enchaînement automatique** — lorsqu'une capsule se termine, une carte de transition montre la capsule suivante avant de continuer
- **Mélange & reprise** — les photos sont mélangées pour la variété ; la position de reprise est suivie par capsule
- **Regroupement adaptatif** — les photos en portrait sont regroupées côte à côte selon le rapport d'aspect de la zone d'affichage
- **Enregistrer comme album** — enregistrez n'importe quelle capsule en tant qu'album permanent

### Fraîcheur

Les capsules tournent selon un calendrier configurable (par défaut : 24 heures). Les photos de couverture et les capsules de découverte amorcées s'alignent sur la même période de rotation. Le bouton « Régénérer » dans l'en-tête force un rafraîchissement immédiat.

### Géocodage inverse

Les capsules de lieu et de voyage affichent des noms de lieux (p. ex. « Paris, France ») au lieu de coordonnées. Cela utilise un géocodage hors ligne via le paquet `reverse_geocoder` — aucun appel API nécessaire. Les résultats sont mis en cache dans la base de données.

Installation : `pip install reverse_geocoder`

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

### Configuration

Voir [Configuration — Capsules](CONFIGURATION.md#capsules) pour tous les réglages.

## Vue Dossiers

Parcourez votre bibliothèque photo par structure de répertoires. Accessible via la route `/folders`.

- Navigation par fil d'Ariane pour remonter dans l'arborescence des répertoires
- Chaque dossier affiche une photo de couverture (l'image la mieux notée de ce répertoire)
- Cliquez sur un dossier pour y descendre, ou sur une photo pour l'ouvrir dans la galerie
- Respecte la visibilité des répertoires multi-utilisateurs en mode multi-utilisateurs

## Boîte de dialogue Filtre GPS

Filtrez les photos par emplacement géographique à l'aide d'un sélecteur de carte interactif :

- Cliquez sur le bouton de filtre de localisation pour ouvrir la boîte de dialogue de la carte
- Cliquez ou faites glisser sur la carte pour définir un point central
- Ajustez le curseur de rayon pour contrôler la zone de recherche
- Les photos situées dans le rayon sélectionné sont filtrées dans la galerie
- Nécessite des coordonnées GPS (lancez `--extract-gps` si les photos ont des données GPS EXIF)

## Suggestions de fusion

Trouvez les clusters de personnes susceptibles de désigner le même individu. Accessible via `/merge-suggestions` ou depuis la page Gérer les personnes.

- **Curseur de seuil de similarité** — à quel point deux personnes doivent se ressembler pour être suggérées (plus bas = plus de suggestions, plus haut = moins)
- **Fusionner** — acceptez une suggestion pour fusionner les deux personnes
- **Fusion par lot** — sélectionnez plusieurs suggestions et fusionnez-les en une fois
- Les suggestions rejetées sont mémorisées et ne sont plus proposées
- Également disponible via la CLI : `python facet.py --suggest-person-merges`

## Export vers éditeur

Écrivez vos notes, favoris et rejets sur le disque sous forme de sidecars XMP, afin que les éditeurs externes (darktable, Lightroom) les reprennent. Nécessite le mode édition.

- **Depuis la galerie** — sélectionnez des photos, puis **Actions → Exporter** écrit un sidecar à côté de chaque fichier.
- **Depuis un album** (« panier ») — exportez tout l'album sous forme de sidecars, ou copiez/liez symboliquement les fichiers vers un répertoire cible.
- **Écrire les métadonnées dans le fichier** — l'action « Écrire les métadonnées dans le fichier » de la page de détail de la photo intègre la note/les mots-clés directement dans le fichier d'origine (JPEG/HEIC/TIFF/PNG/DNG via exiftool) en plus d'écrire le sidecar, de sorte que tout l'écosystème photo les voie. Les originaux RAW propriétaires ne sont jamais modifiés. Contrôlé par `viewer.features.show_embed_metadata` (par défaut : `true`).

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

## Tri sélectif

La page de tri sélectif (`/culling`, mode édition) regroupe les clichés quasi identiques afin que vous puissiez conserver le meilleur de chaque groupe et rejeter le reste. Un sélecteur de **granularité** — la première commande, la plus impactante, de la barre d'outils — choisit la façon dont les photos sont regroupées :

- **Tout** (par défaut) — groupes combinés de rafale + similaires.
- **Rafales** — photos prises dans un court intervalle de temps (issues de la détection de rafales).
- **Similaires** — photos qui se ressemblent quel que soit le moment où elles ont été prises, regroupées par similarité d'embeddings CLIP/SigLIP. Un curseur de seuil contrôle la rigueur du regroupement.
- **Scènes** — groupes de scènes chronologiques (suites de temps de capture), chacun en-tête de son intervalle de temps et de son moment narratif dominant. Conditionné par `viewer.features.show_scenes`.

Pour chaque groupe, choisissez la ou les photos à conserver ; la confirmation rejette le reste. Les confirmations sont différées et peuvent être annulées (voir [Annuler](#annuler)). Les choix de granularité, de tri et de catégorie sont conservés dans le `localStorage`. Les commandes qui ne s'appliquent pas à la granularité courante sont masquées — le menu déroulant de tri et le curseur de seuil de similarité disparaissent en mode scène, et le bouton de portée est masqué lorsque vous n'avez aucun album manuel. Chaque bouton de la barre d'outils et d'action de groupe porte une infobulle, et sur les petits écrans la barre d'outils se détache en une barre inférieure défilante.

**Tri sélectif limité.** La chambre noire peut être restreinte à un sous-ensemble via des paramètres de requête : `?group_by=scene` bascule en granularité scène, `?album=<id>` la limite à un album, et `?from=&to=` (fenêtre de temps de capture EXIF, base de **Trier cette scène**) la limite à une seule scène. Une bannière affiche la portée active avec une commande **Quitter la scène** ; la récupération des membres de la rafale reste limitée à l'album mais ignore la fenêtre, de sorte qu'une rafale chevauchant la limite de la scène montre quand même toutes ses images.

**Puce My Taste.** Chaque confirmation enregistre des lignes de comparaison `source='culling'` qui entraînent le classeur personnel, de sorte que l'en-tête affiche une petite puce « My Taste · N comparaisons » qui se met à jour après chaque décision — l'IA apprend votre œil au fil du tri (`GET /api/ranker/status`).

### Tri automatique

Un bouton **Tri automatique** de la barre d'outils trie toute une portée en une seule passe au lieu de groupe par groupe. Choisissez la portée avec les commandes de granularité/portée (tous les groupes, ou seulement les rafales / similaires / scènes, éventuellement un album ou une fenêtre de dates), réglez une **rigueur** — le budget de conservation, où une valeur plus élevée conserve moins par groupe — et prévisualisez. Chaque groupe conserve sa meilleure photo plus tout ce qui se trouve dans la marge de rigueur (avec un plancher par groupe) et rejette le reste.

L'aperçu est une **simulation** (rien n'est écrit) : il montre la répartition conservation/rejet par groupe. Confirmez pour appliquer — les rejets sont enregistrés et, comme tout tri, entraînent « My Taste » ; un album **Highlights** facultatif rassemble de manière idempotente la meilleure photo de chaque groupe notée au moins `auto_cull.highlights_min`. Un badge indicatif « meilleure photo dans ce groupe » signale les groupes où le tri automatique conserverait une image différente de la tête actuelle. `POST /api/culling/auto` ; configuré via le bloc [`auto_cull`](CONFIGURATION.md#auto-cull).

Lorsqu'une tête de classement des photos à conserver (keeper-ranking) est entraînée, `POST /api/culling/auto` choisit la photo à conserver de chaque groupe selon `keeper_prob` dès qu'elle franchit son seuil de précision — sinon, le résultat est identique au bit près à la sélection heuristique.

### Plein écran

Appuyez sur **`F`** (ou la bascule d'en-tête) pour piloter l'API Fullscreen du navigateur et examiner bord à bord — la chambre noire remplit l'écran sans habillage de l'application. La touche figure dans la légende des raccourcis de la chambre noire ; appuyez sur `F` ou `Esc` pour quitter.

### Loupe / zoom touche Z

Appuyez sur **`Z`** dans la vue unique de la visionneuse plein écran pour basculer une loupe à la manière de Photo Mechanic (ajusté ↔ 2× ; molette/`+`/`-` zoom jusqu'à 800%). Au-delà de l'échelle d'ajustement, le volet remplace sa vignette par la source `/image` pleine résolution, afin de juger la mise au point critique sur de vrais pixels sans quitter la vue. Sur la bande contact des Scènes, `Z` bascule une loupe de survol qui suit le curseur sur une tuile (provenant de l'image pleine résolution), avec un curseur de zoom ajustable. Les vignettes stockées sont plafonnées à 640px, donc la loupe est le moyen d'examiner les pixels au-delà.

### Badges par visage

Dans la visionneuse plein écran de tri de rafale/similaires, chaque visage détecté porte ses propres badges — yeux ouverts/fermés, mauvaise expression et confiance de détection — au lieu d'un unique indicateur de clignement au niveau de la photo. Cela facilite le tri des photos de groupe : vous voyez d'un coup d'œil quel visage a les yeux fermés ou une expression faible. Les badges sont récupérés pour tout un groupe en un seul appel par lot (`POST /api/culling-group/faces`).

Le **panneau des visages** de la chambre noire code chaque recadrage de visage en vert / orange / rouge à partir de ses scores continus d'ouverture des yeux et de sourire, et ajoute des curseurs de seuil **yeux** et **sourire** en direct pour ajuster à la volée ce qui compte comme un clignement ou une expression faible. Les seuils sont les clés de configuration `face_detection.eyes_closed_max` et `face_detection.poor_expression_min` (toutes deux à `4.0` par défaut) ; les curseurs y démarrent.

**Bande de gros plan du sujet (groupes sans visage).** Pour les rafales / groupes similaires dont les photos n'ont pas de visage marquant — faune, macro, produits, oiseaux — la chambre noire affiche plutôt une bande **sujet** : le sujet clé de chaque image, recadré à partir de la boîte de sujet BiRefNet persistée et aligné côte à côte pour comparer le sujet réel en gros plan (l'idée « AI Close-Up » de Zoner, en natif). Chaque recadrage porte un badge de netteté normalisé sur le groupe (10 = le sujet le plus net du groupe) et un anneau coloré (vert / ambre / rouge) pour faire ressortir l'image parfaitement nette ; cliquer sur un recadrage amène la vue principale sur cette photo. Les recadrages sont découpés dans la vignette stockée sans aucun modèle (`POST /api/culling-group/subjects`) et n'apparaissent que lorsqu'un groupe a des sujets mais pas de visages. Cela ne s'active qu'une fois que les photos portent une boîte de sujet : lancez `python facet.py --recompute-saliency` (GPU) pour la remplir sur une bibliothèque existante — d'ici là, la bande ne s'affiche tout simplement pas.

**Comparaison synchronisée (2-up / 4-up).** L'en-tête de la visionneuse plein écran comporte des boutons Single / Compare 2 / Compare 4. En mode comparaison, les volets partagent une seule transformation panoramique/zoom, de sorte que le zoom à la molette ou le panoramique par glissement sur n'importe quel volet les déplace tous vers le cadrage identique — le moyen de choisir l'image la plus nette d'une rafale en examinant vraiment les pixels. Le double-clic bascule ajusté ↔ zoom ; au-delà de l'échelle d'ajustement, chaque volet remplace paresseusement sa vignette 1920px par la source `/image` pleine résolution pour que l'examen soit net. Pas de changement côté backend — les deux routes d'image existent déjà. (Le pincement tactile n'est pas encore câblé ; utilisez la molette sur le bureau.)

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

## Vue Scènes

Une consultation en **lecture seule** de votre bibliothèque regroupée en « scènes » chronologiques — des suites de temps de capture présentées dans l'ordre du récit avec une grille, une loupe au survol et des en-têtes de date/moment. Ouverte à **tous les utilisateurs authentifiés** (lecture seule comme édition). Les photos sont divisées en scènes par les intervalles de temps de capture (une nouvelle scène commence lorsque plus de `scenes.gap_minutes` s'écoulent entre deux clichés consécutifs, élargi de manière adaptative sur les séances clairsemées), et toute suite trop longue est sous-divisée pour qu'un événement photographié en continu ne s'effondre jamais en une seule scène géante.

Le seul point d'entrée est le bouton d'action **Afficher les scènes de cet album** par album dans la grille des Albums (un sélecteur de portée d'album à l'intérieur de la consultation permet de changer la portée). Il n'y a pas d'entrée Scènes dans la navigation principale. Chaque scène porte un bouton **Trier cette scène** réservé à l'édition qui pointe en profondeur vers la surface de [Tri sélectif](#tri-sélectif) en granularité scène (`/culling?group_by=scene&album=&from=&to=`) ; les utilisateurs en édition peuvent aussi atteindre Scènes-en-tri-sélectif directement depuis la navigation Tri sélectif. La consultation elle-même n'a ni grille de rejet ni confirmation groupée — tout le tri passe désormais par la surface de Tri sélectif unifiée.

Lorsque les moments narratifs sont calculés (ci-dessous), chaque scène est également intitulée par son moment dominant, et `scenes.split_on_moment_change` peut sous-diviser une longue suite là où le moment change.

## Moments narratifs

Facet étiquette chaque photo avec le « moment » scène/activité qu'elle dépeint. Le vocabulaire **general** par défaut est agnostique de la bibliothèque — celebration, dining, beach, water activity, mountains, nature & wildlife, cityscape, travel landmark, concert, sports, group gathering, portrait, children, pets, nightlife, ceremony, scenic landscape, snow & winter, home indoor, road & vehicle — ou `other` (un vocabulaire `wedding` est fourni comme genre activable à la demande). Ni Narrative Select ni AfterShoot ne le font ; ils regroupent uniquement par temps et similarité visuelle.

Il est **zero-shot et entièrement local**, et repose sur la **sémantique de la légende** : la légende IA de chaque photo est encodée une seule fois et stockée, et le moment est le meilleur cosinus **max-pooled** de cet embedding de légende au regard des prompts textuels de chaque moment (L0) — l'embedding d'image stocké sert de repli lorsqu'une photo n'a pas de légende. Le signal de légende correspond aux moments ~2,4× plus nettement que l'image brute. De petits a priori de visage/tag départagent les quasi-égalités (L1), puis une passe de Viterbi **lisse le long de la chronologie** de sorte qu'une lecture isolée erronée soit ramenée dans la suite environnante (L2). Un départage VLM facultatif (L3, 16gb/24gb) peut réévaluer les images à faible confiance. Les embeddings de légende sont calculés une seule fois puis réutilisés, si bien que le ré-étiquetage est un produit scalaire peu coûteux sur des vecteurs stockés — pas de décodage d'image, pas de passe de modèle par image ; il **s'exécute automatiquement à la fin de chaque scan** (en n'encodant que les nouvelles légendes). La première passe complète sur une bibliothèque existante encode chaque légende (GPU recommandé) ; ré-étiquetez toute la bibliothèque avec `python facet.py --recompute-moments`.

Les moments apparaissent comme titres de scène et comme filtre de galerie (`GET /api/photos?narrative_moment=beach`, options depuis `GET /api/filter_options/narrative_moments`). Le vocabulaire est piloté par la configuration selon le type d'événement — voir [Configuration — Narrative Moments](CONFIGURATION.md#narrative-moments) pour ajuster les prompts/seuils ou changer de genre.

**Confiance du moment.** Chaque étiquette stocke une confiance a posteriori (`narrative_moment_confidence`). Les étiquettes en dessous de `viewer.moment_confidence_min` (par défaut `0` = jamais atténuées) s'affichent en atténué avec un suffixe « (incertain) » dans l'en-tête des Scènes, l'en-tête de groupe de scène du Tri sélectif et l'infobulle de photo de la galerie (qui affiche aussi le % de confiance). La confiance est aussi une option de tri — **Confiance du moment** (les NULL coulent) sous le groupe Contenu — et un filtre de plage de galerie (`min_moment_confidence` / `max_moment_confidence`, un curseur 0–1 dans la section **Moments** de la barre latérale).

- Chaque scène montre ses photos leaders dans l'ordre de capture
- Triez une scène depuis son bouton **Trier cette scène**, qui ouvre la surface de tri restreinte à cette scène
- Les scènes plus petites que `scenes.min_size` sont omises ; au plus `scenes.max_photos` photos sont chargées

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

Contrôlé par `viewer.features.show_scenes` (par défaut : `true`). Voir [Configuration — Scenes](CONFIGURATION.md#scenes) pour `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` et `adaptive_k`.

## Nettoyage des indésirables

Une file de revue rapide pour les fichiers non photographiques « indésirables » qui s'accumulent dans une bibliothèque d'amateur — captures d'écran, documents scannés, reçus, mèmes et diapositives de présentation. La détection est zero-shot sur les embeddings d'image stockés (voir [Configuration — Nettoyage des indésirables](CONFIGURATION.md#nettoyage-des-indésirables)) ; exécutez `python facet.py --detect-junk` (ou laissez-le s'exécuter automatiquement en fin de scan) pour peupler `junk_kind`.

Ouvrez-la depuis le bouton de navigation **Nettoyage** (la route `/junk`, réservée à l'édition). La page réutilise la grille de la galerie et affiche chaque candidat signalé :

- **Puces de filtre par type** — « Tous les types » plus une puce par type détecté avec son compte (depuis `GET /api/filter_options/junk_kinds`). Cliquez pour restreindre la file à un seul type.
- **Conserver** (par photo) — efface l'étiquette d'indésirable pour que la photo quitte la file **définitivement** : elle est marquée comme évaluée-propre (`not_junk`) et n'est plus jamais signalée par un `--detect-junk` ultérieur.
- **Rejeter** (par photo) — marque la photo comme rejetée en utilisant la même plomberie de rejet que partout ailleurs (rien n'est supprimé du disque).
- **Tout rejeter** — un rejet groupé de tous les candidats actuellement chargés, derrière une boîte de dialogue de confirmation.
- **Loupe** — appuyez sur **`Z`** (ou le bouton de la barre d'outils) pour une loupe au survol façon Photo Mechanic, afin de lire le texte fin avant de décider.

Les photos indésirables ne sont **pas** masquées de la galerie normale — elles restent visibles jusqu'à ce que vous filtriez pour les voir. Filtrez n'importe quelle vue de galerie avec `?junk_kind=<type>` (exact) ou `?junk_kind=any` (tout indésirable, exclut la sentinelle `not_junk`).

Contrôlé par `viewer.features.show_junk_sweep` (par défaut : `true`).

## Mode de comparaison par paires

Classez les photos en les jugeant deux à la fois. Les votes accumulés alimentent l'ajustement des poids. Accessible via la route `/compare` (bouton Comparer dans l'en-tête). Nécessite un `edition_password` non vide (mono-utilisateur) ou un rôle `admin`/`superadmin` (multi-utilisateurs).

La page comporte quatre onglets :

### Onglet Comparaison A/B

Paires de photos côte à côte. Choisissez un gagnant, marquez une égalité, ou passez. Une barre de progression suit les votes vers 50, avec un décompte courant des victoires A/victoires B/égalités. Un filtre de catégorie restreint la session, et un menu déroulant de stratégie de sélection contrôle la façon dont les paires sont choisies.

| Stratégie | Description |
|----------|-------------|
| `uncertainty` | Photos avec des scores similaires (les plus informatives) |
| `boundary` | Plage de score 6–8 (zone ambiguë) |
| `active` | Photos avec le moins de comparaisons (garantit la couverture) |
| `random` | Paires aléatoires (référence) |

**Raccourcis clavier :**

| Touche | Action |
|-----|--------|
| `A` | La photo de gauche gagne |
| `B` | La photo de droite gagne |
| `T` | Égalité |
| `S` | Passer la paire |
| `Escape` | Fermer la fenêtre de remplacement de catégorie |

### Onglet Suggestions de poids

Affiche les poids appris des comparaisons face aux poids actuels, côte à côte, avec la précision du modèle avant/après. Le top 10 actuel des photos et le top 10 prédit après recalcul sont prévisualisés dans des colonnes adjacentes. **Appliquer** écrit les poids suggérés ; **Recalculer** rescore la catégorie pour les appliquer (les deux nécessitent le mode édition).

### Onglet Poids

Éditeur manuel de poids : un curseur par métrique pour la catégorie sélectionnée avec un aperçu de score en direct. **Enregistrer** écrit dans `scoring_config.json` (avec une sauvegarde) ; **Recalculer les scores** les applique ; **Réinitialiser** recharge les poids stockés.

### Onglet Instantanés

Enregistrez les poids actuels sous forme d'instantané nommé et restaurez n'importe quel instantané antérieur.

### Remplacement de catégorie

Pour réaffecter la catégorie d'une photo depuis la vue de comparaison : éditez le badge de catégorie, sélectionnez une catégorie cible, lancez « Analyser les conflits de filtres » pour voir quels filtres l'excluent, puis appliquez le remplacement.

## Statistiques EXIF

La page Statistiques (`/stats`) fournit des analyses réparties sur 5 onglets. Utilisez les sélecteurs **catégorie** et **plage de dates** dans la barre d'outils pour filtrer tous les graphiques sur un sous-ensemble spécifique de votre bibliothèque.

### Onglets

| Onglet | Description |
|-----|-------------|
| **Équipement** | Boîtiers, objectifs et combinaisons (top 20 de chaque) |
| **Réglages de prise de vue** | Distributions ISO, ouverture, focale, vitesse d'obturation |
| **Chronologie** | Photos dans le temps |
| **Catégories** | Analyses de catégorie, gestion des poids et corrélations de scores |
| **Corrélations** | Graphiques de corrélation X/Y personnalisés avec regroupement |

### Onglet Catégories

Quatre sous-onglets :

| Sous-onglet | Description |
|---------|-------------|
| **Répartition** | Nombre de photos par catégorie, scores moyens, histogrammes de distribution des scores |
| **Poids** | Comparaison par graphique radar (jusqu'à 5 catégories), carte de chaleur des poids et éditeur de poids (mode édition) |
| **Corrélations** | Carte de chaleur de corrélation de Pearson montrant comment chaque dimension influence l'agrégat, vue détaillée au clic |
| **Chevauchement** | Analyse du chevauchement des filtres montrant quelles catégories partagent des photos correspondantes |

Chaque graphique dispose d'un bouton d'aide `?` activable expliquant comment le lire. Une bascule d'aide globale dans la barre des sous-onglets affiche les explications pour tous les sous-onglets.

### Éditeur de poids (mode édition)

Disponible dans le sous-onglet Poids lorsque le mode édition est actif :

1. Sélectionnez une catégorie dans le menu déroulant
2. Ajustez les curseurs de poids (un par métrique, la somme devrait faire 100%)
3. Utilisez « Normaliser à 100 » pour rééquilibrer automatiquement
4. Développez la section Modificateurs repliable pour ajuster les bonus/pénalités
5. L'**Aperçu de la distribution des scores** affiche un histogramme avant/après en direct à mesure que vous déplacez les curseurs
6. Cliquez sur **Enregistrer** pour mettre à jour `scoring_config.json` (crée une sauvegarde horodatée)
7. Cliquez sur **Recalculer les scores** (apparaît après l'enregistrement) pour appliquer les nouveaux poids à toutes les photos de cette catégorie

Toutes les statistiques tiennent compte de l'utilisateur en mode multi-utilisateurs — chaque utilisateur voit les analyses pour ses seules photos visibles.

## Raccourcis clavier (galerie)

| Touche | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Déplacer le focus clavier entre les cartes de photo (colonnes de grille et lignes de mosaïque) |
| `Enter` | Ouvrir la photo focalisée |
| `Space` | Sélectionner / désélectionner la photo focalisée |
| `Ctrl+A` | Sélectionner toutes les photos chargées |
| `Escape` | Effacer la sélection / fermer le tiroir de filtres |
| `Shift+Click` | Sélection par plage des photos entre la dernière sélectionnée et celle cliquée |
| `Double-click` | Ouvrir la photo |
| `?` | Afficher la référence des raccourcis clavier (fonctionne sur chaque page) |

## Annuler

Les opérations groupées de favori/rejet/notation et les confirmations de tri sélectif affichent une infobulle (snackbar)
avec une action **Annuler** pendant environ 7 secondes. Les opérations groupées d'indicateurs sont validées
immédiatement et annulées via des appels API inverses (plafonnées à 500 photos) ; les confirmations
de tri sélectif sont différées — le groupe disparaît instantanément mais l'appel API ne se déclenche
qu'une fois la fenêtre d'annulation écoulée.

## Application web progressive

La visionneuse fournit un manifeste d'application web et un service worker Angular (builds de
production uniquement) : elle peut être installée sur l'écran d'accueil, le shell de l'application se
charge hors ligne, et jusqu'à 1000 vignettes sont mises en cache LRU pendant 7 jours. Les réponses API
ne sont jamais mises en cache (sauf les bundles i18n avec une stratégie de fraîcheur), et la déconnexion
efface le cache des vignettes afin que les configurations multi-utilisateurs partageant un navigateur ne
puissent pas fuiter d'aperçus entre les comptes. Une infobulle propose un rechargement lorsqu'une nouvelle
version a été déployée.

## Mobile

Sur les petits écrans, la barre de sélection groupée se réduit au nombre d'éléments sélectionnés,
au bouton Effacer, au bouton Tout sélectionner et à un unique bouton **Actions** qui ouvre une feuille
inférieure tactile avec toutes les opérations groupées (favori, rejet, notation, albums, copie,
téléchargement).

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

Augmentez `min_photos_for_person` pour masquer du menu déroulant de filtre les personnes ayant peu de photos.

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

### Poids des coups de cœur

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

## Performances

### Grandes bases de données (50k+ photos)

Lancez ces commandes pour de meilleures performances :

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

### SQLite asynchrone (optionnel, pour les chemins de lecture à forte concurrence)

`api.database.get_async_db()` est un gestionnaire de contexte asynchrone adossé à aiosqlite,
parallèle à `get_db()`. Les points d'accès sont actuellement synchrones (FastAPI les délègue
à un pool de threads de travail, ce qui convient à une concurrence typique). Pour les chemins de
lecture à forte concurrence (>5 utilisateurs simultanés), les points d'accès individuels peuvent être
migrés en :

1. Remplaçant `def foo(...)` par `async def foo(...)`.
2. Remplaçant `with get_db() as conn:` par `async with get_async_db() as conn:`.
3. Mettant un `await` devant chaque `.execute()` et `.fetchone()` / `.fetchall()`.
4. Gardant les chemins d'écriture synchrones — aiosqlite sérialise les écritures de toute façon, et le pool
   de connexions du chemin synchrone les gère déjà.

Les candidats les plus sollicités du plan sont `/api/photos`, `/api/timeline`,
`/api/search`. Migrez-les un à la fois et mesurez les performances avant de promouvoir.

### Cache de statistiques

Agrégations précalculées avec un TTL de 5 minutes :
- Nombre total de photos
- Nombre de modèles d'appareil/objectif
- Nombre de personnes
- Nombre de catégories et de motifs

Vérifier l'état :
```bash
python database.py --stats-info
```

### Chargement paresseux des filtres

Les menus déroulants de filtre se chargent à la demande via l'API :
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

## Points d'accès API

La documentation interactive de l'API est disponible à `/api/docs` (Swagger UI) et le schéma OpenAPI à `/api/openapi.json`.

### Galerie

| Point d'accès | Description |
|----------|-------------|
| `GET /api/photos` | Liste paginée de photos avec filtres |
| `GET /api/photo` | Détails d'une seule photo |
| `GET /api/type_counts` | Nombre de photos par type |
| `GET /api/similar_photos/{path}` | Photos similaires (modes : `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Recherche sémantique texte-vers-image (`scope=text` = texte OCR/légende uniquement) |
| `GET /api/critique?path=&mode=&refresh=` | Critique IA (basée sur des règles ou VLM) ; `refresh=true` régénère la critique VLM mise en cache |
| `GET /api/ranker/status` | État du classeur personnel pour le tri « My Taste » (% de couverture apprise, précision en validation) |
| `GET /api/config` | Configuration de la visionneuse |

### Authentification

| Point d'accès | Description |
|----------|-------------|
| `POST /api/auth/login` | S'authentifier et recevoir un jeton |
| `POST /api/auth/edition/login` | Déverrouiller le mode édition |
| `POST /api/auth/edition/logout` | Verrouiller le mode édition (retirer les privilèges, rester authentifié) |
| `GET /api/auth/status` | Vérifier l'état de l'authentification |

### Vignettes et images

| Point d'accès | Description |
|----------|-------------|
| `GET /thumbnail` | Vignette de photo |
| `GET /face_thumbnail/{id}` | Vignette de recadrage de visage |
| `GET /person_thumbnail/{id}` | Vignette représentative d'une personne |
| `GET /image` | Image pleine résolution |

### Options de filtrage

| Point d'accès | Description |
|----------|-------------|
| `GET /api/filter_options/cameras` | Modèles d'appareil avec comptages |
| `GET /api/filter_options/lenses` | Modèles d'objectif avec comptages |
| `GET /api/filter_options/tags` | Tags avec comptages |
| `GET /api/filter_options/persons` | Personnes avec comptages |
| `GET /api/filter_options/patterns` | Motifs de composition |
| `GET /api/filter_options/categories` | Catégories avec comptages |
| `GET /api/filter_options/apertures` | Valeurs de diaphragme distinctes avec comptages |
| `GET /api/filter_options/focal_lengths` | Focales distinctes avec comptages |
| `GET /api/filter_options/colors` | Facettes de température de couleur et de tranche de teinte avec comptages |
| `GET /api/filter_options/metric_ranges` | Min/max observés et histogramme par métrique numérique (pour les bornes des curseurs) |

### Opérations par lot

| Point d'accès | Description |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marquer plusieurs photos comme favorites |
| `POST /api/photos/batch_reject` | Marquer plusieurs photos comme rejetées |
| `POST /api/photos/batch_rating` | Définir une note en étoiles pour plusieurs photos |

### Personnes

| Point d'accès | Description |
|----------|-------------|
| `GET /api/persons` | Lister toutes les personnes |
| `POST /api/persons` | Créer une nouvelle personne, en y attachant éventuellement des visages (réservé à l'édition). Corps : `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Lister les personnes auto-regroupées non nommées avec `face_count >= N` (par défaut depuis `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renommer une personne |
| `POST /api/persons/{id}/assign_faces` | Attacher des visages en masse à une personne ; les anciennes personnes vides sont auto-supprimées (réservé à l'édition). Corps : `{face_ids}` |
| `POST /api/persons/{id}/split` | Scinder un sous-ensemble des visages d'une personne en une nouvelle personne (réservé à l'édition). Corps : `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Masquer une personne de la liste, des filtres et des suggestions de fusion |
| `POST /api/persons/{id}/unhide` | Réafficher une personne précédemment masquée |
| `POST /api/persons/merge` | Fusionner deux personnes (corps JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Fusionner la personne source dans la cible |
| `POST /api/persons/merge_batch` | Fusionner plusieurs personnes en une fois |
| `POST /api/persons/merge_suggestions/reject` | Rejeter une suggestion de fusion afin qu'elle ne soit plus proposée |
| `POST /api/persons/{id}/delete` | Supprimer une personne |
| `POST /api/persons/delete_batch` | Supprimer plusieurs personnes en une fois |

### Albums

| Point d'accès | Description |
|----------|-------------|
| `GET /api/albums` | Lister tous les albums |
| `POST /api/albums` | Créer un album |
| `GET /api/albums/{id}` | Obtenir les détails d'un album |
| `PUT /api/albums/{id}` | Mettre à jour un album |
| `DELETE /api/albums/{id}` | Supprimer un album |
| `GET /api/albums/{id}/photos` | Lister les photos d'un album (paginées) |
| `POST /api/albums/{id}/photos` | Ajouter des photos à un album |
| `DELETE /api/albums/{id}/photos` | Retirer des photos d'un album |
| `POST /api/albums/{id}/share` | Générer un jeton de partage |
| `DELETE /api/albums/{id}/share` | Révoquer un jeton de partage |
| `GET /api/shared/album/{id}?token=` | Consulter un album partagé (sans authentification) |
| `POST /api/shared/album/{id}/session` | Échange un jeton de partage (+ PIN facultatif) contre une session d'épreuvage client (limité en débit) |
| `PUT /api/shared/album/{id}/picks` | Le client insère/met à jour un cœur/commentaire sur une photo (session d'épreuvage) |
| `GET /api/shared/album/{id}/picks` | Le client lit ses propres sélections (session d'épreuvage) |
| `GET /api/albums/{id}/picks` | `[Edition]` Le propriétaire lit toutes les sélections des clients pour l'album |

### Souvenirs, Chronologie, Carte & Légendes

| Point d'accès | Description |
|----------|-------------|
| `GET /api/memories?date=` | Photos prises à cette date les années précédentes |
| `GET /api/memories/check` | Vérifier si des souvenirs existent pour une date |
| `GET /api/caption?path=` | Obtenir ou générer une légende IA |
| `PUT /api/caption` | Mettre à jour la légende d'une photo (mode édition) |
| `GET /api/timeline?cursor=&limit=&direction=` | Photos de chronologie paginées |
| `GET /api/timeline/dates?year=&month=` | Dates disponibles pour la navigation |
| `GET /api/timeline/years` | Années disponibles avec comptages de photos |
| `GET /api/timeline/months` | Mois disponibles pour une année |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Photos géolocalisées dans les limites |
| `GET /api/photos/map/count` | Nombre de photos géolocalisées |

### Capsules

| Point d'accès | Description |
|----------|-------------|
| `GET /api/capsules` | Liste paginée de capsules (mise en cache) |
| `GET /api/capsules/{id}/photos` | Photos d'une capsule spécifique |
| `POST /api/capsules/{id}/save-album` | Enregistrer une capsule comme album (mode édition) |

### Statistiques

| Point d'accès | Description |
|----------|-------------|
| `GET /api/stats/overview` | Résumé général des statistiques de scoring |
| `GET /api/stats/score_distribution` | Données d'histogramme de distribution des scores |
| `GET /api/stats/top_cameras` | Meilleurs appareils par nombre de photos |
| `GET /api/stats/categories` | Comptages et moyennes par catégorie |
| `GET /api/stats/gear` | Comptages appareil/objectif/combinaison |
| `GET /api/stats/settings` | Distributions des réglages de prise de vue |
| `GET /api/stats/timeline` | Données de chronologie |
| `GET /api/stats/correlations` | Corrélations de métriques personnalisées |
| `GET /api/stats/categories/breakdown` | Comptages de photos et distributions de scores par catégorie |
| `GET /api/stats/categories/weights` | Poids et modificateurs de catégorie depuis la config |
| `GET /api/stats/categories/correlations` | Corrélation r de Pearson par dimension par catégorie |
| `GET /api/stats/categories/metrics?category=X` | Valeurs de métriques brutes pour l'aperçu côté client |
| `GET /api/stats/categories/overlap` | Analyse du chevauchement des filtres entre catégories |
| `POST /api/stats/categories/update` | Mettre à jour les poids/modificateurs de catégorie (mode édition) |
| `POST /api/stats/categories/recompute` | Recalculer les scores d'une catégorie (mode édition) |

### Mode de comparaison

| Point d'accès | Description |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obtenir la prochaine paire de photos à comparer |
| `POST /api/comparison/submit` | Soumettre un résultat de comparaison |
| `POST /api/comparison/reset` | Réinitialiser les données de comparaison |
| `GET /api/comparison/stats` | Statistiques de session de comparaison |
| `GET /api/comparison/history` | Lister les comparaisons passées |
| `POST /api/comparison/edit` | Éditer un résultat de comparaison |
| `POST /api/comparison/delete` | Supprimer une comparaison |
| `GET /api/comparison/coverage` | Couverture des comparaisons par catégorie |
| `GET /api/comparison/confidence` | Métriques de confiance pour les scores appris |
| `GET /api/comparison/photo_metrics` | Métriques brutes des photos |
| `GET /api/comparison/category_weights` | Poids/filtres de catégorie |
| `GET /api/comparison/learned_weights` | Poids suggérés à partir des comparaisons |
| `POST /api/comparison/preview_score` | Aperçu avec des poids personnalisés |
| `POST /api/comparison/suggest_filters` | Analyser les conflits de filtres |
| `POST /api/comparison/override_category` | Remplacer la catégorie d'une photo |
| `POST /api/recalculate` | Recalculer les scores avec les poids actuels |

### Tri de rafale

| Point d'accès | Description |
|----------|-------------|
| `GET /api/burst-groups` | Lister les groupes de rafale pour le tri |
| `POST /api/burst-groups/select` | Sélectionner les photos à conserver d'un groupe de rafale |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groupes de photos visuellement similaires |
| `POST /api/similar-groups/select` | Sélectionner les photos à conserver d'un groupe similaire |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene&exclude_rejected=true&similarity_threshold=&page=&per_page=` | Groupes de rafale/similaires/scène pour le tri. `group_by` (par défaut `all`) sélectionne les groupes combinés rafale+similaires, rafale uniquement, similaires uniquement, ou scènes chronologiques (les groupes de scène ajoutent `type`/`start`/`end`/`moment`/`moment_confidence` ; le paramètre `sort` est ignoré en mode scène). `exclude_rejected` (par défaut `true`) masque les photos avec `is_rejected=1` ; les groupes ayant moins de 2 photos restantes sont supprimés. Lorsqu'une tête de classement des photos à conserver est entraînée, chaque photo porte aussi `keeper_prob` et chaque groupe porte `keeper_best_path` |
| `POST /api/culling-groups/confirm` | Confirmer les sélections de tri (rafale, similaires ou scène). Corps `{group_id, type, paths, keep_paths}` ; `type:'scene'` enregistre les lignes de comparaison de tri de scène |
| `POST /api/culling/auto` | `[Edition]` Tri automatique en un bouton pour toute une portée. Corps `{group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, dry_run}` ; `dry_run` (par défaut `true`) renvoie l'aperçu conservation/rejet par groupe, une application rejette le reste et enregistre les paires de tri |
| `POST /api/culling-group/faces` | Badges par visage (yeux ouverts/fermés, expression, confiance) pour un groupe, en un seul lot |
| `POST /api/photos/keeper_hints` | Indices par photo « une meilleure photo existe dans ce groupe » pour le badge de la galerie/visionneuse, regroupés par `burst_group_id`. Corps `{paths}` ; renvoie `{path: {has_better, best_path, keeper_prob}}`. Dépend du modèle — renvoie `{}` si aucune tête de classement des photos à conserver n'est entraînée |
| `GET /api/scenes` | Scènes chronologiques de photos leaders de rafale (consultation en lecture seule) |
| `GET /api/filter_options/junk_kinds` | Types d'indésirables détectés avec leur compte (exclut la sentinelle `not_junk`) pour les puces du Nettoyage des indésirables |
| `POST /api/photo/clear_junk` | `[Edition]` Conserve un candidat indésirable — remet son `junk_kind` à `not_junk` afin qu'il quitte la file définitivement. Corps `{photo_path}` |

### Scan

| Point d'accès | Description |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Démarrer un scan de scoring |
| `GET /api/scan/status` | Vérifier la progression du scan (champ structuré `progress` : `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progression en temps réel via Server-Sent Events ; le jeton est passé en paramètre de requête (l'API `EventSource` ne peut pas définir d'en-têtes), avec repli automatique sur le polling de `/status` |
| `GET /api/scan/directories` | Lister les répertoires de scan configurés |

### Gestion des visages

| Point d'accès | Description |
|----------|-------------|
| `GET /api/person/{id}/faces` | Lister les visages d'une personne |
| `POST /api/person/{id}/avatar` | Définir le visage avatar d'une personne |
| `GET /api/photo/faces` | Lister les visages détectés dans une photo |
| `POST /api/face/{id}/assign` | Attribuer un visage à une personne |
| `POST /api/photo/assign_all_faces` | Attribuer tous les visages d'une photo à une personne |
| `POST /api/photo/unassign_person` | Détacher une personne d'une photo |

### Actions sur les photos

| Point d'accès | Description |
|----------|-------------|
| `POST /api/photo/set_rating` | Définir la note en étoiles d'une photo |
| `POST /api/photo/toggle_favorite` | Basculer le statut de favori |
| `POST /api/photo/toggle_rejected` | Basculer le statut de rejet |

### Gestion de la configuration

| Point d'accès | Description |
|----------|-------------|
| `POST /api/config/update_weights` | Mettre à jour les poids de scoring |
| `GET /api/config/weight_snapshots` | Lister les instantanés de poids enregistrés |
| `POST /api/config/save_snapshot` | Enregistrer les poids actuels comme instantané |
| `POST /api/config/restore_weights` | Restaurer les poids depuis un instantané |

### Suggestions de fusion

| Point d'accès | Description |
|----------|-------------|
| `GET /api/merge_suggestions` | Fusions de personnes suggérées en fonction de la similarité des visages |

### Dossiers

| Point d'accès | Description |
|----------|-------------|
| `GET /api/folders` | Lister la structure des dossiers de photos |

### Téléchargement

| Point d'accès | Description |
|----------|-------------|
| `GET /api/download/options` | Types de téléchargement disponibles pour une photo (`path`, `is_shared` facultatif) |
| `GET /api/download` | Télécharger une photo (`path`, `type=original\|darktable\|raw`, `profile` facultatif) |

**Types de téléchargement :**

- `original` — Servir le fichier tel quel (JPG/HEIF) ou converti en JPEG via rawpy (fichiers RAW).
- `darktable` — Convertir le RAW associé avec un profil darktable nommé (nécessite le paramètre `profile`). Bascule sur l'original si aucun RAW associé n'existe.
- `raw` — Servir le fichier RAW associé tel quel (non disponible dans les albums partagés).

Le point d'accès `/api/download/options` détecte automatiquement les fichiers RAW associés et renvoie les options disponibles, y compris les profils darktable configurés. La visionneuse l'utilise pour peupler un menu de téléchargement par photo.

### Export vers éditeur

| Point d'accès | Description |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Écrire un sidecar XMP |
| `POST /api/export/sidecars` | `[Edition]` Écrire des sidecars pour des chemins explicites ou un ensemble de filtres |
| `POST /api/photo/embed_metadata` | `[Edition]` Intégrer les métadonnées dans le fichier d'origine (JPEG/HEIC/TIFF/PNG/DNG ; RAW jamais modifié) et écrire le sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Export d'album sous forme de sidecars, copie ou lien symbolique |

### Plugins

| Point d'accès | Description |
|----------|-------------|
| `GET /api/plugins` | Lister les plugins configurés |
| `POST /api/plugins/test-webhook` | Tester un plugin de webhook |

### Santé

| Point d'accès | Description |
|----------|-------------|
| `GET /health` | Vérification de l'état du serveur |
| `GET /ready` | Vérification de l'état de préparation du serveur |
| `GET /metrics` | Métriques au format Prometheus : nombre de photos, couverture des embeddings, taille de la BD, mémoire du processus |

### Internationalisation

| Point d'accès | Description |
|----------|-------------|
| `GET /api/i18n/languages` | Lister les langues disponibles |
| `GET /api/i18n/{lang}` | Obtenir les traductions d'une langue |

### Options de filtrage (supplémentaires)

| Point d'accès | Description |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Géocoder en sens inverse des coordonnées en nom de lieu |

## Dépannage

| Problème | Solution |
|-------|----------|
| Chargement de page lent | Lancez `--migrate-tags` et `--optimize` |
| Les filtres ne s'affichent pas | Vérifiez `--stats-info`, lancez `--refresh-stats` |
| Filtre par personne vide | Lancez `--cluster-faces-incremental` |
| Bouton Comparer manquant | Définissez un `edition_password` non vide (mono-utilisateur) ou utilisez le rôle `admin`/`superadmin` (multi-utilisateurs) |
| Mot de passe ne fonctionne pas | Vérifiez `viewer.password` (mono-utilisateur) ou vérifiez le hash du mot de passe (multi-utilisateurs) |
| Un utilisateur ne voit pas de photos | Vérifiez `directories` dans sa configuration utilisateur et `shared_directories` |
| Bouton de scan manquant | Nécessite le rôle `superadmin` et `viewer.features.show_scan_button: true` |
| La recherche ne renvoie aucun résultat | Assurez-vous que les photos ont des données `clip_embedding` (lancez d'abord le scoring) |
| Critique VLM indisponible | Nécessite un profil VRAM 16gb/24gb et `viewer.features.show_vlm_critique: true` |
| La carte n'affiche aucune photo | Lancez `--extract-gps` pour peupler les colonnes GPS, assurez-vous que les photos ont des données GPS EXIF |
| Les légendes ne se génèrent pas | Nécessite un profil VRAM 16gb/24gb pour le légendage VLM |
| Chronologie vide | Assurez-vous que les photos ont des valeurs `date_taken` |
| Port 5000 occupé | Lancez `python viewer.py --port 5001` (ou définissez `PORT=5001`). Sur macOS, le récepteur AirPlay de ControlCenter occupe 5000 par défaut — choisissez un autre port ou désactivez le récepteur AirPlay dans Réglages Système → Général → AirDrop et Handoff. |
