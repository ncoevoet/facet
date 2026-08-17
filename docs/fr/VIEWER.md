# Visionneuse Web

> 🌐 [English](../VIEWER.md) · **Français** · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md)

Application monopage FastAPI + Angular pour parcourir, filtrer et gérer les photos.

## Sommaire

- [Démarrer la visionneuse](#démarrer-la-visionneuse) · [Authentification](#authentification) · [Options de filtrage](#options-de-filtrage) · [Tri](#tri) · [Fonctionnalités de la galerie](#fonctionnalités-de-la-galerie)
- [Gestion des personnes](#gestion-des-personnes) · [Déclenchement d'un scan (Superadmin)](#déclenchement-dun-scan-superadmin) · [Recherche sémantique](#recherche-sémantique) · [Albums](#albums)
- [Critique IA](#critique-ia) · [Légendage IA](#légendage-ia-gpu-16gb24gb-edition) · [Souvenirs (« Ce jour-là »)](#souvenirs--ce-jour-là-) · [Vue Chronologie](#vue-chronologie) · [Vue Carte](#vue-carte) · [Capsules](#capsules)
- [Vue Dossiers](#vue-dossiers) · [Boîte de dialogue Filtre GPS](#boîte-de-dialogue-filtre-gps) · [Suggestions de fusion](#suggestions-de-fusion) · [Export vers éditeur](#export-vers-éditeur) · [Tri sélectif](#tri-sélectif) · [Nettoyage des indésirables](#nettoyage-des-indésirables) · [Mode de comparaison par paires](#mode-de-comparaison-par-paires)
- [Statistiques EXIF](#statistiques-exif) · [Raccourcis clavier](#raccourcis-clavier-galerie) · [Annuler](#annuler) · [Application web progressive](#application-web-progressive) · [Mobile](#mobile) · [Cadre photo / Kiosque](#cadre-photo--kiosque) · [Envoi automatique depuis le téléphone](#envoi-automatique-depuis-le-téléphone)
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

Filtrer par les motifs détectés par SAMP-Net (le modèle n'en émet que ces
8, dans `models/samp_net.py`) :
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

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
- **Inverser** — Remplacer la sélection par son complément parmi les photos chargées. Choisir celles à garder puis inverser : c'est la façon directe de voir exactement ce qui va disparaître. Limité aux photos chargées, comme « Tout sélectionner », pour ne jamais sélectionner en silence des photos que vous ne voyez pas.
- **Comparer** — Ouvrir 2 à 4 photos sélectionnées côte à côte, panoramique et zoom synchronisés (molette pour zoomer, glisser pour déplacer, double-clic pour réinitialiser ; tous les volets bougent ensemble et passent en pleine résolution au-delà de l'échelle d'ajustement). La même vue que celle du tri, atteignable pour n'importe quel ensemble choisi à la main et non plus seulement pour des vues voisines d'une rafale.
- **Copier les noms de fichiers** — Copier les noms de fichiers sélectionnés dans le presse-papiers
- **Exporter** — Écrire des sidecars XMP (note/favori/rejet) à côté des fichiers sélectionnés (voir [Export vers éditeur](#export-vers-éditeur))
- **Trier vers un dossier** — Copier les gardés, ou déplacer/mettre à la corbeille les rejetés, vers un dossier cible (voir [Trier vers un dossier](#trier-vers-un-dossier))
- **Télécharger** — Télécharger les photos sélectionnées
- Effacez la sélection avec Échap ou le bouton Effacer

Les actions groupées nécessitent le mode édition. Double-cliquez sur n'importe quelle photo pour la télécharger directement.

### Garder le top N%

Un contrôle **Garder le top %** dans la barre d'outils de la galerie (mode édition) transforme toute la vue filtrée en un tri en une étape. Définissez un pourcentage ; le serveur classe la vue actuelle selon le **tri courant** (agrégat, My Taste, coups de cœur, netteté, …), garde cette part supérieure et **sélectionne le reste** — les photos les moins bien classées — afin que vous puissiez les rejeter depuis la barre d'actions (ou désélectionner au préalable celles que vous voulez épargner). Rien n'est déplacé ni supprimé : cela ne fait que peupler la sélection (et chaque rejet continue d'entraîner « My Taste »). La sélection est plafonnée à 5000 photos ; sur une très grande vue, le contrôle vous le signale — affinez le filtre (album, date, personne…) pour agir sur le reste. Le classement s'effectue sur la même vue filtrée par les bascules de masquage que la grille de la galerie, si bien que sous les réglages par défaut `hide_brackets` / `hide_panoramas`, un bracketing ou un panorama compte comme **une seule** photo dans le pourcentage, pas une par image.

### Trier vers un dossier

La boîte de dialogue **Trier vers un dossier…** de la barre d'actions groupées (mode édition) copie les gardés, ou déplace/met à la corbeille les rejetés, vers un dossier cible en une étape (la corbeille du système est conditionnée par `viewer.cull.allow_trash`, jamais une suppression définitive). L'application est sûre par construction : `POST /api/cull/apply` ne fait jamais confiance à la liste de suppression fournie par le client — il redérive côté serveur l'ensemble réellement ciblé par l'action à partir de l'état `is_rejected` propre à chaque photo (la copie n'agit que sur les gardés, le déplacement/la corbeille que sur les rejetés) et signale tout ce qui sort de ce périmètre comme `excluded_by_state` plutôt que d'agir dessus. Chaque appel est par défaut un essai à blanc (dry run) — un aperçu s'exécute toujours avant toute écriture — et le déplacement/la corbeille exigent un `dry_run=false` explicite pour s'exécuter ; inclure le RAW ou le sidecar non touché d'une photo rejetée est optionnel (`include_companions`), afin que rejeter un JPEG dérivé n'entraîne jamais silencieusement son RAW avec lui. Plusieurs outils photo du commerce ont connu des bugs de suppression de la mauvaise sélection ; le point d'entrée d'application de Facet est conçu pour que le client ne puisse jamais spécifier directement un ensemble à supprimer.

**Séries multi-images.** Sous les réglages par défaut `hide_brackets` / `hide_panoramas` (tous deux activés), la sélection de galerie dont part cette boîte de dialogue ne contient que l'exposition de référence d'un bracketing ou l'image médiane marquée d'un panorama — donc, par défaut, trier ainsi un bracketing HDR ou un balayage panoramique copie, déplace ou met à la corbeille ce seul fichier représentatif, jamais le reste de la série. Deux cases à cocher indépendantes et facultatives élargissent ce qui est concerné par l'action : « Inclure le RAW / XMP compagnon » (`include_companions`) ajoute, pour la même image, son RAW compagnon et son sidecar `.xmp` de même radical ; « Inclure les images de la même série » (`include_sequence_siblings`) ajoute chaque autre image partageant le `(sequence_kind, sequence_group_id)` de la photo correspondante — les véritables vues du bracketing ou images du panorama que la galerie masque — **à condition que l'état gardé/rejeté de cette image sœur corresponde à l'action**. Rejeter une vue d'un balayage et cocher cette case déplace ou met à la corbeille cette vue ainsi que toute autre image rejetée de la série, jamais celles que vous avez gardées ; les images sœurs dont l'état ne correspond pas sont comptabilisées dans `excluded_by_state` à la place. L'aperçu indique le nombre d'images sœurs existantes (`sequence_siblings`) même case décochée, de sorte que l'existence d'une série n'est jamais silencieusement invisible, et `matched` distingue « rien dans la sélection n'était éligible à cette action » d'un résultat vide. Déplacer ou mettre à la corbeille l'image de tête d'un panorama/bracketing en re-choisit une survivante comme nouveau `is_sequence_lead`, afin que la série reste visible sous les bascules de masquage par défaut par la suite — la seule écriture en base que fait ce point d'accès par ailleurs limité aux fichiers. Pour choisir à la main un sous-ensemble explicite d'une série plutôt que tout ou rien, ouvrez-la d'abord via l'action « ouvrir cette série dans la galerie » du détail de la photo — son filtre de portée sur la série suspend les quatre bascules de masquage tant qu'il est actif, si bien que chaque image est sélectionnable individuellement. Un appel direct à `POST /api/cull/apply` avec un corps `filters` contourne entièrement les réglages par défaut de la visionneuse : ce sont les propres `filters.hide_brackets` / `filters.hide_panoramas` de l'appelant qui déterminent la portée avant application des images sœurs, pas `viewer.defaults`.

**Où vous pouvez écrire.** Sans `viewer.export.allowed_target_dirs` configuré, les seuls dossiers dans lesquels Facet peut écrire sont vos répertoires de scan — pointez la boîte de dialogue vers un sous-dossier de l'arborescence photo (par exemple `_rejected`) et cela fonctionne sans configuration. Pour utiliser un dossier situé hors de l'arborescence scannée, ajoutez-le d'abord à `viewer.export.allowed_target_dirs` ; tout le reste est refusé avec un `403`, quels que soient les droits du système de fichiers. Voir [Configuration — Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri). En Docker/Podman, le chemin saisi est résolu **à l'intérieur du conteneur**, par rapport à ce qui y est réellement monté — jamais par rapport au système de fichiers hôte — voir [Déploiement — Sémantique des chemins en conteneur](DEPLOYMENT.md#sémantique-des-chemins-en-conteneur).

**« Accès refusé » à chaque action.** Il s'agit d'un `403` — un refus délibéré du contrôle de dossier cible ci-dessus, ou une session d'édition expirée — jamais un problème de droits du système de fichiers ou d'utilisateur conteneur. Le message ne précise pas lequel des deux ; vérifiez le corps de la réponse de la requête échouée dans l'onglet Réseau de votre navigateur pour le champ `detail`. Un vrai problème de droits du système de fichiers se présente différemment : l'action rapporte un succès partiel avec un nombre `errors` non nul, et le serveur journalise l'erreur système sous-jacente pour chaque fichier en échec.

### Options d'affichage

- **Mode de disposition** - Basculez entre **Grille** (cartes uniformes) et **Mosaïque** (lignes justifiées préservant les rapports d'aspect). La mosaïque est réservée au bureau ; le mobile utilise toujours la grille.
- **Taille des vignettes** - Curseur pour ajuster la hauteur des cartes/lignes (120–400px, conservé dans le localStorage)
- **Masquer les détails** - Masquer les métadonnées des photos sur les cartes (mode grille uniquement)
- **Infobulle** - Mode d'affichage des détails : **Survol** (par défaut), **Clic**, **Désactivée** ou **Panneau latéral**. Le panneau latéral ancre les mêmes détails dans le tiroir de droite au lieu de suivre le curseur : une information donnée se trouve toujours au même endroit d'une photo à l'autre, et le panneau conserve la dernière photo survolée au lieu de se vider quand le curseur quitte la grille. Il partage ce tiroir avec la barre de filtres : ouvrir les filtres le masque jusqu'à ce que vous les refermiez, et la grille conserve exactement la largeur qu'elle a lorsque les filtres sont ouverts. Nécessite une fenêtre d'au moins 1280 px.
- **Masquer les clignements** - Filtrer les photos avec des clignements détectés
- **Meilleure de la rafale** - N'afficher que la photo la mieux notée de chaque rafale
- **Meilleure du bracketing** - N'affiche que l'exposition de référence de chaque bracketing détecté, en masquant les vues latérales. **Activé par défaut.** Indépendant de « Meilleure de la rafale » : un quart des bracketings partagent une rafale avec d'autres vues, où la vignette principale n'est pas l'exposition de référence.
- **Meilleure du panorama** - N'affiche que l'image représentative marquée (médiane) de chaque panorama ou panorama HDR détecté, en masquant le reste du balayage. **Activé par défaut.**
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

Un déclencheur apparenté mais distinct, `POST /api/scan/recompute`, réutilise le même verrou de tâche pour renoter les photos existantes sur place (sans nouveau fichier) — voir [Priorité des catégories et contextes de notation](#priorité-des-catégories-et-contextes-de-notation). Contrairement à ce bouton de scan réservé au superadmin, il est réservé au mode édition.

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

### Contexte de notation

Chaque album peut porter un contexte de notation qui détermine quelle catégorie l'emporte pour ses photos membres, indépendamment de l'ordre de priorité global — voir [Contextes de notation](CONFIGURATION.md#contextes-de-notation). `PUT /api/albums/{id}/scoring_context` (réservé au mode édition) le définit et matérialise le même contexte sur chaque photo qui est membre **à cet instant précis** ; `conflicts` dans la réponse compte les membres non manuels qui portaient déjà un contexte différent, `manual_skipped` compte les membres dont le remplacement manuel a été laissé intact (une attribution d'album ne convertit jamais silencieusement le remplacement manuel d'une photo en un contexte venant de l'album), et `updated` compte combien ont réellement été écrites. Un album manuel résout son appartenance à partir de ses lignes `album_photos` ; un album intelligent n'en a aucune, son appartenance est donc résolue en évaluant son `smart_filter_json` enregistré sur la base de données en direct. C'est la **définition de filtre** de l'album, pas « ce que la galerie affichait par hasard » : elle ignore délibérément les préférences d'affichage de la galerie qui masquent les clignements, les rafales, les doublons et les photos rejetées (globales, modifiables en cours d'exécution, et ne faisant pas partie de `smart_filter_json`), si bien que `updated` peut légitimement dépasser le nombre de photos que la propre vue galerie de l'album affiche lorsque ces bascules sont activées — et renvoie `updated: 0` avec un `warning` lorsque le filtre ne correspond actuellement à rien. Dans tous les cas, l'attribution est un instantané ponctuel, pas un abonnement en continu : une photo ajoutée *par la suite* à un album manuel hérite bien automatiquement du contexte, mais une photo qui correspond *plus tard* au filtre d'un album intelligent n'hérite **pas** rétroactivement du contexte — le contexte doit être redéfini (`PUT`) pour capter les nouvelles correspondances. `DELETE /api/albums/{id}/scoring_context` (proposé dans la boîte de dialogue comme une action « Effacer le contexte », distincte du choix du contexte `default`, qui attribue `default` au lieu d'effacer) annule l'attribution exactement sur les membres que cet album avait marqués, sans toucher au remplacement manuel propre à une photo — et lorsqu'une photo ainsi désattribuée est *encore* membre d'un autre album qui déclare lui-même un contexte, elle est réattribuée avec le contexte de cet autre album plutôt que d'être laissée sans catégorie (cette redérivation se limite aux photos précisément retirées d'un album ; la suppression ou l'effacement complet d'un album ne le tente pas). `GET /api/albums/{id}/suggested_context` en propose un à partir du `narrative_moment` dominant détecté de l'album (via la liste `suggest_from_moments` de chaque contexte), avec un niveau de confiance `share` — cet appel n'écrit rien ; l'attribution ci-dessus doit toujours être confirmée explicitement. Un recalcul (`POST /api/scan/recompute`) est nécessaire pour que le nouveau contexte modifie réellement la catégorie stockée d'une photo.

### Export de portfolio

Lorsque `viewer.features.show_portfolio_export` vaut `true` (par défaut) et que le mode édition est déverrouillé, chaque carte d'album manuel gagne une action **Exporter le portfolio**. Elle ouvre une petite boîte de dialogue (titre de la galerie, dossier cible, bascule d'inclusion des légendes) et restitue l'album sous forme de galerie HTML statique autonome — le cas d'usage de thumbsup/sigal, mais natif, sans dépendance à un outil externe. Le répertoire de sortie contient `index.html` (une grille de vignettes responsive en CSS pur avec une visionneuse vanilla-JS intégrée — **zéro** référence externe/CDN, donc entièrement fonctionnelle hors ligne), un dossier `assets/` de JPEG nommés séquentiellement (aucun chemin de bibliothèque divulgué), et un `manifest.json` enregistrant les décomptes et les sources par photo. Chaque photo privilégie l'**original** sur disque (réduit à `portfolio.max_edge`, orientation EXIF appliquée) et se rabat sur la vignette 640 px stockée lorsque l'original est inaccessible (partages réseau hors ligne). L'endpoint est `POST /api/albums/{album_id}/export-portfolio` (réservé au mode édition) ; le `target_dir` est validé par rapport à la même liste d'autorisation (`viewer.export.allowed_target_dirs` plus les répertoires de scan, voir [Configuration — Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri)) que les endpoints d'export copie/déplacement, et les albums dépassant `portfolio.max_photos` (500 par défaut) sont refusés. Réexporter le même album est idempotent — seuls les fichiers propres à l'export sont réécrits. Voir [Configuration de l'export de portfolio](CONFIGURATION.md#export-de-portfolio).

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

## Panoramas et bracketings d'exposition

Les images d'un panorama ont été prises pour être assemblées, celles d'un bracketing pour être fusionnées : ni les unes ni les autres ne sont des prises concurrentes. La détection de rafales ne voit pas la différence — les images arrivent à quelques secondes d'intervalle, d'un même boîtier, à une même focale — et sans cela elle les regroupe et n'en garde qu'une, choisie sur un critère qui ne veut rien dire pour un panoramique.

**Dans la galerie.** « Meilleure du bracketing » et « Meilleure du panorama » (actives par défaut) replient chaque série derrière une image représentative : l'exposition de référence pour un bracketing, l'image médiane pour un panorama. Cette image porte une petite icône en bas, à côté de l'étoile et du cœur, indiquant ce qu'elle représente — balayage simple, balayage HDR ou bracketing — avec une infobulle. L'icône n'apparaît que tant que le filtre correspondant masque réellement le reste de la série.

**Dans le tri.** Le menu de granularité propose « Bracketings d'exposition », « Panoramas » et « Panoramas HDR » comme flux distincts, jamais fondus dans « Tout ». Toutes les images sont marquées « à garder » d'emblée, et valider une série n'enregistre aucune paire de comparaison : préférer un barreau d'une échelle d'exposition, ou une image d'un panoramique, décrit la façon dont la série a été prise, pas la photographie.

**Corriger une série.** La géométrie ne peut pas deviner l'intention — un balayage délibéré et un filé qui suit un sujet mobile donnent la même mesure — donc un taux d'erreur résiduel d'environ 4 % est inhérent. Une correction est persistante et survit à chaque détection ultérieure, qui efface et réécrit les étiquettes qu'elle avait produites.

Les deux sens d'erreur ont chacun leur surface, car on ne les rencontre pas au même endroit. Un **faux positif** se corrige dans le tri, où la série est sous les yeux : la barre d'actions du groupe porte un menu de correction (édition uniquement) proposant « Ce n'est pas un panorama » et le rebasculement entre simple et HDR. Un **oubli** se corrige depuis la galerie, car un balayage non détecté n'apparaît dans aucun groupe de tri : sélectionnez ses images puis « Marquer comme série » → « Marquer comme un panorama » dans la barre de sélection. Les deux s'annulent depuis la notification, et les deux demandent au moins deux images.

Rien n'est réétiqueté immédiatement. Une correction est enregistrée aussitôt et marquée en attente — un badge horloge sur la vignette, une pastille « Correction en attente » sur le groupe de tri — car la détection est une passe par lots sur toute la bibliothèque, bien trop coûteuse pour être relancée à chaque clic. La page de tri affiche une bannière comptant les corrections en attente, avec un bouton **Relancer la détection** ; le filtre « Corrections de panorama » de la barre latérale (édition uniquement, sous Affiner) les liste à l'échelle de la bibliothèque, dans un sens ou dans l'autre. Jusqu'à cette relance, une série supprimée reste groupée comme panorama et une série forcée reste non groupée : la correction est une note adressée au détecteur, pas une étiquette en soi.

**Régler la détection.** L'onglet Panoramas, sous Comparer, expose les seuils réellement calibrés sur des séries étiquetées. Les enregistrer ne change rien en soi : la détection est une passe par lots sur toute la bibliothèque, l'onglet propose donc une relance à côté de l'enregistrement. Voir [CONFIGURATION.md](CONFIGURATION.md).

## Vue Dossiers

Parcourez votre bibliothèque photo par structure de répertoires. Accessible via la route `/folders`.

- Navigation par fil d'Ariane pour remonter dans l'arborescence des répertoires
- Chaque dossier affiche une photo de couverture (l'image la mieux notée de ce répertoire)
- Cliquez sur un dossier pour y descendre, ou sur une photo pour l'ouvrir dans la galerie
- Chaque vignette de dossier propose une action de filtrage qui ouvre la galerie restreinte à ce dossier — disponible sur tous les dossiers, pas seulement les dossiers terminaux
- Respecte la visibilité des répertoires multi-utilisateurs en mode multi-utilisateurs

### Filtre par dossier

Le panneau de filtres de la galerie comporte une section **Dossier**. **Choisir un dossier…** ouvre un
sélecteur qui parcourt l'arborescence niveau par niveau ; l'appliquer restreint la galerie à ce dossier
**et à tous ses sous-dossiers**. Le dossier actif apparaît sous forme de puce de filtre, se combine avec
tous les autres filtres (note, personne, date…), survit à un rechargement via le paramètre d'URL
`path_prefix` et est enregistré dans les albums intelligents.

Le filtre par dossier restreint uniquement la grille de photos — les listes déroulantes du panneau, les
compteurs par type, les statistiques, la chronologie, la carte et la recherche restent à l'échelle de
toute la bibliothèque.

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
- **Depuis un album** (« panier ») — exportez tout l'album sous forme de sidecars, ou copiez/liez symboliquement les fichiers vers un répertoire cible (même liste d'autorisation de destination que [Trier vers un dossier](#trier-vers-un-dossier)).
- **Écrire les métadonnées dans le fichier** — l'action « Écrire les métadonnées dans le fichier » de la page de détail de la photo intègre la note/les mots-clés directement dans le fichier d'origine (JPEG/HEIC/TIFF/PNG/DNG via exiftool) en plus d'écrire le sidecar, de sorte que tout l'écosystème photo les voie. Les originaux RAW propriétaires ne sont jamais modifiés. Contrôlé par `viewer.features.show_embed_metadata` (par défaut : `true`).

API : voir la section [Points d'accès API](#points-daccès-api) ci-dessous.

## Tri sélectif

La page de tri sélectif (`/culling`, mode édition) regroupe les clichés quasi identiques afin que vous puissiez conserver le meilleur de chaque groupe et rejeter le reste. Un sélecteur de **granularité** — la première commande, la plus impactante, de la barre d'outils — choisit la façon dont les photos sont regroupées :

- **Tout** (par défaut) — groupes combinés de rafale + similaires.
- **Rafales** — photos prises dans un court intervalle de temps (issues de la détection de rafales).
- **Similaires** — photos qui se ressemblent quel que soit le moment où elles ont été prises, regroupées par similarité d'embeddings CLIP/SigLIP. Un curseur de seuil contrôle la rigueur du regroupement.
- **Scènes** — groupes de scènes chronologiques (suites de temps de capture), chacun en-tête de son intervalle de temps et de son moment narratif dominant. Conditionné par `viewer.features.show_scenes`.
- **Bracketings d'exposition** — les séries multi-expositions trouvées par [`--detect-sequences`](COMMANDS.md), exposition de référence en tête, chaque vue portant sa correction (`-2 EV` … `+2 EV`). Volontairement absentes de **Tout** : un bracketing est un même sujet photographié plusieurs fois pour être fusionné, pas un ensemble de prises concurrentes ; toutes les vues sont donc marquées « à garder » d'emblée et la validation n'enregistre aucune paire de comparaison — préférer un échelon d'une échelle d'exposition ne dit rien de votre goût. Pour supprimer les expositions latérales, utilisez le rognage de bracketing du tri automatique (ci-dessous).
- **Panoramas** — les séries de balayage assemblé trouvées par [`--detect-panoramas`](COMMANDS.md), dans l'ordre de prise de vue, l'image médiane étant marquée comme représentative de la série. Conservées intactes exactement comme les bracketings d'exposition : toutes les images sont marquées « à garder » d'emblée et la validation n'enregistre aucune paire de comparaison.
- **Panoramas HDR** — les balayages à grande plage dynamique de la même passe de détection (étalement d'exposition dépassant `hdr_min_span_stops`), regroupés et conservés intacts de la même façon. Il n'existe pas de granularité « bracketing HDR » distincte : un jeu HDR sur trépied est bracketé à chaque position, si bien que la passe de bracketing l'étiquette d'abord comme un simple **Bracketing d'exposition**, et ce n'est qu'une fois que la passe de panorama reconnaît le balayage que cette étiquette est remplacée par `hdr_panorama`. Un jeu HDR sur trépied que la passe de panorama ne reconnaît pas n'est pas perdu pour autant — il reste simplement classé sous **Bracketings d'exposition**.

Ces trois granularités (**Bracketings d'exposition**, **Panoramas**, **Panoramas HDR**) sont celles où tout est « conservé intact » : double-cliquer sur une vignette — le geste rapide « ne garder que celle-ci » disponible partout ailleurs — y est sans effet, car un bracketing ou un panoramique a été pris pour être fusionné, pas pour rivaliser, si bien que la chambre noire refuse de le réduire à une seule image. Leurs flux ignorent aussi entièrement les bascules `hide_*` de la galerie — le contraire de la grille de la galerie (qui n'affiche par défaut que l'image représentative d'une série) : toutes les images de chaque série non encore revue y sont visibles pour examen, quoi que la galerie soit configurée pour masquer. Comme pour les groupes de rafale/similaires/scène, une série qui ne compte plus que moins de 2 images survivantes une fois les membres déjà rejetés exclus est retirée du flux plutôt qu'affichée comme un groupe d'une seule image.

Deux commandes de tri accompagnent la granularité : le **mode de tri** (les plus faciles d'abord, les plus redondantes, les meilleures, les plus récentes, celles à comparer, ou **les plus anciennes d'abord**) et un **bouton fléché qui inverse le mode actif**. « Les plus anciennes d'abord » est le seul mode qui ordonne aussi les photos *à l'intérieur* de chaque groupe par ordre de prise de vue, le seul ordre dans lequel un bracketing ou une séquence panoramique se lit correctement.

Pour chaque groupe, choisissez la ou les photos à conserver ; la confirmation rejette le reste. Les confirmations sont différées et peuvent être annulées (voir [Annuler](#annuler)). Les choix de granularité, de tri et de catégorie sont conservés dans le `localStorage`. Les commandes qui ne s'appliquent pas à la granularité courante sont masquées — le menu déroulant de tri et le curseur de seuil de similarité disparaissent en mode scène, et le bouton de portée est masqué lorsque vous n'avez aucun album manuel. Chaque bouton de la barre d'outils et d'action de groupe porte une infobulle, et sur les petits écrans la barre d'outils se détache en une barre inférieure défilante.

**Tri sélectif limité.** La chambre noire peut être restreinte à un sous-ensemble via des paramètres de requête : `?group_by=scene` bascule en granularité scène, `?album=<id>` la limite à un album, et `?from=&to=` (fenêtre de temps de capture EXIF, base de **Trier cette scène**) la limite à une seule scène. Une bannière affiche la portée active avec une commande **Quitter la scène** ; la récupération des membres de la rafale reste limitée à l'album mais ignore la fenêtre, de sorte qu'une rafale chevauchant la limite de la scène montre quand même toutes ses images.

**Puce My Taste.** Chaque confirmation enregistre des lignes de comparaison `source='culling'` qui entraînent le classeur personnel, de sorte que l'en-tête affiche une petite puce « My Taste · N comparaisons » qui se met à jour après chaque décision — l'IA apprend votre œil au fil du tri (`GET /api/ranker/status`).

### Tri automatique

Un bouton **Tri automatique** de la barre d'outils trie toute une portée en une seule passe au lieu de groupe par groupe. Choisissez la portée avec les commandes de granularité/portée (tous les groupes, ou seulement les rafales / similaires / scènes, éventuellement un album ou une fenêtre de dates), réglez une **rigueur** — le budget de conservation, où une valeur plus élevée conserve moins par groupe — et prévisualisez. Chaque groupe conserve sa meilleure photo plus tout ce qui se trouve dans la marge de rigueur (avec un plancher par groupe) et rejette le reste. Le bouton est entièrement masqué dans les trois granularités « conserver intact » (**Bracketings d'exposition**, **Panoramas**, **Panoramas HDR**) — il n'y a rien à y décider, puisque toutes les images de ces séries sont marquées gardées d'emblée. Dans une portée mixte, les bracketings sont décidés en premier, avant les rafales, les similaires et les scènes, si bien que l'exposition de référence d'un bracketing n'est jamais redécidée par un groupe ultérieur qu'elle chevauche aussi.

L'aperçu est une **simulation** (rien n'est écrit) : il montre la répartition conservation/rejet par groupe. Confirmez pour appliquer — les rejets sont enregistrés et, comme tout tri, entraînent « My Taste » ; un album **Highlights** facultatif rassemble de manière idempotente la meilleure photo de chaque groupe notée au moins `auto_cull.highlights_min`. Un badge indicatif « meilleure photo dans ce groupe » signale les groupes où le tri automatique conserverait une image différente de la tête actuelle. `POST /api/culling/auto` ; configuré via le bloc [`auto_cull`](CONFIGURATION.md#auto-cull).

Lorsqu'une tête de classement des photos à conserver (keeper-ranking) est entraînée, `POST /api/culling/auto` choisit la photo à conserver de chaque groupe selon `keeper_prob` dès qu'elle franchit son seuil de précision — sinon, le résultat est identique au bit près à la sélection heuristique.

**Le rognage des bracketings redondants** est optionnel (`trim_brackets`, désactivé par défaut), et c'est le seul chemin du tri automatique qui réduise jamais une série de séquence — partout ailleurs, un bracketing, un panorama ou un panorama HDR qu'une portée mixte vient à toucher reste conservé intact, sans être affecté par la rigueur. Un bracketing justifie ses vues supplémentaires en couvrant la plage que l'exposition de référence écrête ; quand cette référence n'écrête ni les ombres ni les hautes lumières, il n'y avait rien à récupérer et les expositions latérales occupent de l'espace sans apporter de latitude — le cas « je laisse le bracketing activé en permanence ». Seule la vue de référence est conservée — le choix est déterminé par l'image qui est l'exposition de référence, jamais par le score ou la rigueur — et les séries dont la référence n'a jamais été mesurée sont laissées intactes : non mesuré ne veut pas dire non écrêté.

### Plein écran

Appuyez sur **`F`** (ou la bascule d'en-tête) pour piloter l'API Fullscreen du navigateur et examiner bord à bord — la chambre noire remplit l'écran sans habillage de l'application. La touche figure dans la légende des raccourcis de la chambre noire ; appuyez sur `F` ou `Esc` pour quitter.

### Loupe / zoom touche Z

Appuyez sur **`Z`** dans la vue unique de la visionneuse plein écran pour basculer une loupe à la manière de Photo Mechanic (ajusté ↔ 2× ; molette/`+`/`-` zoom jusqu'à 800%). Au-delà de l'échelle d'ajustement, le volet remplace sa vignette par la source `/image` pleine résolution, afin de juger la mise au point critique sur de vrais pixels sans quitter la vue. Sur la bande contact des Scènes, `Z` bascule une loupe de survol qui suit le curseur sur une tuile (provenant de l'image pleine résolution), avec un curseur de zoom ajustable. Les vignettes stockées sont plafonnées à 640px, donc la loupe est le moyen d'examiner les pixels au-delà.

### Badges par visage

Dans la visionneuse plein écran de tri de rafale/similaires, chaque visage détecté porte ses propres badges — yeux ouverts/fermés, mauvaise expression et confiance de détection — au lieu d'un unique indicateur de clignement au niveau de la photo. Cela facilite le tri des photos de groupe : vous voyez d'un coup d'œil quel visage a les yeux fermés ou une expression faible. Les badges sont récupérés pour tout un groupe en un seul appel par lot (`POST /api/culling-group/faces`).

Le **panneau des visages** de la chambre noire code chaque recadrage de visage en vert / orange / rouge à partir de ses scores continus d'ouverture des yeux et de sourire, et ajoute des curseurs de seuil **yeux** et **sourire** en direct pour ajuster à la volée ce qui compte comme un clignement ou une expression faible. Les seuils sont les clés de configuration `face_detection.eyes_closed_max` et `face_detection.poor_expression_min` (toutes deux à `4.0` par défaut) ; les curseurs y démarrent.

**Bande de gros plan du sujet (groupes sans visage).** Pour les rafales / groupes similaires dont les photos n'ont pas de visage marquant — faune, macro, produits, oiseaux — la chambre noire affiche plutôt une bande **sujet** : le sujet clé de chaque image, recadré à partir de la boîte de sujet BiRefNet persistée et aligné côte à côte pour comparer le sujet réel en gros plan (l'idée « AI Close-Up » de Zoner, en natif). Chaque recadrage porte un badge de netteté normalisé sur le groupe (10 = le sujet le plus net du groupe) et un anneau coloré (vert / ambre / rouge) pour faire ressortir l'image parfaitement nette ; cliquer sur un recadrage amène la vue principale sur cette photo. Les recadrages sont découpés dans la vignette stockée sans aucun modèle (`POST /api/culling-group/subjects`) et n'apparaissent que lorsqu'un groupe a des sujets mais pas de visages. Cela ne s'active qu'une fois que les photos portent une boîte de sujet : lancez `python facet.py --recompute-saliency` (GPU) pour la remplir sur une bibliothèque existante — d'ici là, la bande ne s'affiche tout simplement pas.

**Sujet clé (cible du zoom + personne principale).** La chambre noire détermine de quoi — ou de qui — parle chaque image du groupe ouvert : le meilleur de ses visages détectés, ou la boîte de sujet BiRefNet persistée s'il n'y en a aucun, pour tout le groupe en un seul appel (`POST /api/photos/key_subjects`), puis zoome *dessus* : **`Z`**, un double-clic ou le premier cran de molette au-delà de l'échelle d'ajustement amènent la vue 1:1 sur ce point plutôt qu'au milieu de l'image, pour que l'inspection des pixels commence sur le visage qui compte. Dès que vous avez déplacé ou zoomé une image vous-même, la suggestion se retire pour cette image — elle ne recadre jamais un cadrage que vous avez choisi. Lorsque le gagnant est une personne nommée, ce visage porte une pastille ambre avec son nom dans la bande des visages. Les visages priment sur la saillance, et parmi les visages c'est le meilleur mélange de taille relative, de centralité et de statut de personne nommée qui l'emporte : un sujet nommé à moyenne distance bat un inconnu plus grand, mais un point nommé à l'arrière-plan non. Rien n'est stocké, la réponse reflète donc toujours les affectations de visages et de personnes actuelles ; les boîtes sont des fractions de l'image complète (`normalized_frame_xyxy`), jamais de la vignette affichée. `GET /api/photo/key_subject` fournit la même réponse pour une seule photo.

**Comparaison synchronisée (2-up / 4-up).** L'en-tête de la visionneuse plein écran comporte des boutons Single / Compare 2 / Compare 4. En mode comparaison, les volets partagent une seule transformation panoramique/zoom, de sorte que le zoom à la molette ou le panoramique par glissement sur n'importe quel volet les déplace tous vers le cadrage identique — le moyen de choisir l'image la plus nette d'une rafale en examinant vraiment les pixels. Le double-clic bascule ajusté ↔ zoom ; au-delà de l'échelle d'ajustement, chaque volet remplace paresseusement sa vignette 1920px par la source `/image` pleine résolution pour que l'examen soit net. Pas de changement côté backend — les deux routes d'image existent déjà. (Le pincement tactile n'est pas encore câblé ; utilisez la molette sur le bureau.)

**Balayer pour garder ou rejeter (tactile).** Sur un appareil tactile, la vue simple de la chambre noire devient un jeu de cartes à balayer. Faites glisser l'image vers la droite pour la garder, vers la gauche pour la rejeter — elle s'incline et se teinte au passage, en vert avec un badge GARDER, en rouge avec un badge REJETER. Au-delà de 35 % de la largeur de l'image (jamais moins de 48px), le relâchement l'éjecte de ce côté, écrit exactement la décision qu'écrivent les touches `↑` / `↓`, et passe à l'image suivante exactement comme `→`. En deçà, l'image revient en place et rien n'est décidé. Un glissement dont l'axe s'avère vertical est relâché intact dès que cet axe est connu, il reste donc à qui il appartenait. Chaque validation affiche un bandeau avec **Annuler** qui restaure à la fois la décision *et* l'image sur laquelle elle a été prise — un `↑` malencontreux s'annule en appuyant sur `↓`, mais un pouce malencontreux est déjà sur l'image suivante, sans geste inverse à sa portée. Le geste n'est proposé que là où il ne peut en concurrencer un autre — un pointeur grossier (doigt ou stylet, jamais une souris), la vue simple (une grille de comparaison n'a pas d'image unique à décider) et l'échelle d'ajustement, au-delà de laquelle le même glissement *est* le panoramique du volet, dont celui-ci a déjà capturé le pointeur. Une astuce d'une ligne reste sous la première image jusqu'à ce qu'elle soit écartée (mémorisée dans le `localStorage`).

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

### Priorité des catégories et contextes de notation

Les catégories sont évaluées par ordre de `priority` croissant et la première correspondance de filtre l'emporte — voir [Évaluation des filtres](SCORING.md#fonctionnement-du-scoring) et [Contextes de notation](CONFIGURATION.md#contextes-de-notation) pour le modèle complet. Deux leviers réservés au mode édition permettent de gérer cela sans éditer `scoring_config.json` à la main :

- **Priorité globale** — `GET/POST /api/config/category_priorities` liste et réorganise l'ordre d'évaluation de base. `POST` prend une liste ordonnée complète de noms de catégorie et permute les valeurs de priorité existantes selon cet ordre, de sorte que le multi-ensemble (et son unicité) soit préservé plutôt que renuméroté.
- **Contextes de notation** — `GET /api/config/scoring_contexts` liste les préréglages configurés (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) avec, pour chacun, son ordre effectif résolu. Un contexte promeut certaines catégories en tête et en exclut d'autres purement et simplement sans toucher à l'ordre global. Le delta `promote`/`excluded` de chaque préréglage non-`default` est lui-même modifiable depuis ce même onglet **Contexte de notation** — faites glisser la tête promue dans l'ordre voulu (ou utilisez les boutons Monter/Descendre), basculez l'exclusion d'une catégorie, enregistrez — via `PUT /api/config/scoring_contexts/{name}` (réservé au mode édition, corps `{promote, excluded}`) ; il rejette une catégorie inconnue, `default` dans l'une ou l'autre liste, et un doublon dans `promote`, tandis qu'un nom présent dans les deux listes est accepté et `excluded` l'emporte. `label_key` et `suggest_from_moments` ne sont pas modifiables depuis là. Un contexte s'attribue par album (voir [Contexte de notation](#contexte-de-notation) dans la section Albums) ou par photo via le remplacement de catégorie ci-dessous.

Aucun des deux leviers ne renote les photos par lui-même. Après avoir réorganisé les priorités, attribué un contexte, ou défini un remplacement par photo, déclenchez un recalcul (`POST /api/scan/recompute`, réservé au mode édition) puis interrogez `GET /api/scan/recompute_status` pour obtenir `{running, kind, progress, exit_code}`. `/scan/start` comme `/scan/recompute` sont tous deux protégés au niveau inter-processus par `facet.LibraryLock`, pas seulement par le verrou en mémoire de la visionneuse (voir [Réorganiser la priorité globale](CONFIGURATION.md#réorganiser-la-priorité-globale)) : si un recalcul ou un scan est déjà en cours depuis un terminal, la visionneuse refuse toute nouvelle tâche avec un 409 nommant le détenteur — une tâche en ligne de commande et une tâche déclenchée par la visionneuse ne peuvent donc plus entrer en collision. Si `normalization.per_category` est activé, un recalcul unique après un changement affectant les catégories ne converge pas complètement — voir [Normalisation](CONFIGURATION.md#normalisation).

Le panneau **Collisions de catégories** du même onglet (`GET /api/stats/categories/overlap`) sert à répondre, avant toute réorganisation, à la question de savoir quelle catégorie de priorité supérieure capture discrètement les photos d'une catégorie, et en quel nombre. Son tableau indique, par catégorie, combien de photos lui sont actuellement assignées (**Assignées**), combien de photos de la bibliothèque correspondraient à ses filtres si on les évaluait isolément (**Correspondances filtre**), et combien d'entre elles sont captées par une catégorie de priorité supérieure à la place (**Capturées par priorité supérieure**, `matched - assigned`, plafonné à 0). Une liste **Principales paires en collision** en dessous classe les catégories le plus souvent appariées, par nombre de photos partagées. Le repli `default` épinglé est exclu à la fois du tableau et de la liste des paires — il correspond à toutes les photos par construction (un jeu de filtres vide), si bien que l'inclure noierait toute collision réelle.

### Remplacement de catégorie

Pour réaffecter la catégorie d'une photo depuis la vue de comparaison : éditez le badge de catégorie, sélectionnez une catégorie cible, lancez « Analyser les conflits de filtres » pour voir quels filtres l'excluent, puis appliquez le remplacement. Le remplacement est validé par rapport aux noms de catégorie configurés (`POST /api/comparison/override_category`) et est désormais conservé dans la table annexe `photo_scoring_overrides` — contrairement à avant, il survit au prochain recalcul au lieu d'être silencieusement perdu, et la photo conserve la catégorie attribuée manuellement jusqu'à ce qu'elle soit explicitement réinitialisée (`POST /api/comparison/clear_category_override`).

Les deux mêmes actions sont disponibles dans la visionneuse photo sous **Définir la catégorie de notation…** / **Supprimer le remplacement** (mode édition), aux côtés d'un panneau repliable **pourquoi cette photo n'est-elle pas dans une autre catégorie ?**. Choisissez-y une catégorie cible et le panneau indique quels filtres excluent actuellement la photo et ce que chacun devrait devenir — par exemple « Augmenter shutter_speed_max de 0,02 à 0,033 ». C'est le moyen le plus rapide de découvrir qu'une catégorie est inaccessible pour une photo donnée plutôt que simplement devancée, ce qu'un réordonnancement seul ne peut pas corriger. Ce panneau s'appuie sur `POST /api/comparison/suggest_filters`.

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

## Cadre photo / Kiosque

Les appareils kiosque sans connexion — cadres photo connectés, tableaux de bord Home Assistant, affichages de type ImmichFrame / Immich-Kiosk — peuvent récupérer les meilleurs clichés de Facet sans session utilisateur. Il n'y a **aucune interface cliente** : les kiosques consomment directement les points d'accès, authentifiés par un **jeton de cadre** opaque à longue durée de vie configuré dans le bloc de configuration `frame` (`frame.tokens` ; une liste vide désactive toute la fonctionnalité et chaque point d'accès renvoie 404). Les jetons sont comparés à temps constant en octets UTF-8, donc un jeton manquant renvoie 401 et un jeton erroné ou non-ASCII renvoie 403 — jamais 500.

La sélection puise dans toute la bibliothèque : les photos rejetées, indésirables et avec clignement sont exclues, `frame.min_aggregate` (`7.0` par défaut) fixe le score plancher, et les options facultatives `frame.favorites_only` / `frame.categories` l'affinent davantage. Les photos sont renvoyées via un **échantillon aléatoire pondéré par le score** (un mélange du bassin des candidates les mieux notées), afin qu'un cadre montre de la variété parmi vos meilleurs clichés plutôt que la même poignée à chaque fois. Les réponses **ne contiennent jamais de chemins de fichiers** — chaque photo est identifiée par un identifiant signé opaque (le `rowid` de la ligne signé avec le secret du serveur), de sorte qu'un détenteur de jeton ne peut ni énumérer des lignes arbitraires ni apprendre où se trouvent vos fichiers.

| Point d'accès | Réponse | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` plafonné à `frame.max_count` (100 par défaut), par défaut `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | le JPEG de la photo — original sur disque réduit à `max_edge` (plafonné par `frame.max_edge`, 1920 par défaut), avec repli sur la vignette stockée lorsque l'original est inaccessible | longue durée, immuable |
| `GET /api/frame/next?token=` | un JPEG sélectionné aléatoire, différent à chaque appel — le cas du cadre « bête » / de la caméra générique Home Assistant | `no-store` |

### Générer un jeton

Les jetons sont des chaînes opaques que vous inventez — utilisez-en une longue et aléatoire, et traitez-la comme un mot de passe :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Ajoutez le résultat à `frame.tokens` dans `scoring_config.json` (vous pouvez en lister plusieurs — un par appareil — et en révoquer un en le supprimant) :

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Recette Home Assistant

L'URL unique `/api/frame/next` correspond directement à la [caméra générique](https://www.home-assistant.io/integrations/generic/) de Home Assistant — chaque rafraîchissement récupère un nouveau cliché sélectionné.

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # rafraîchit toutes les ~20 s
```

Ajoutez la caméra à une carte Picture Glance / Picture Entity (ou à un tableau de bord sur tablette murale) et elle devient un cadre photo qui se met à jour tout seul.

Pour un client de type **ImmichFrame** qui gère son propre diaporama, interrogez `GET /api/frame/photos?token=…&count=30` pour obtenir la liste des identifiants, puis demandez chaque `GET /api/frame/image/{id}?token=…&max_edge=1920` — les identifiants sont stables et les réponses d'image portent un cache longue durée immuable, si bien qu'un client récupère chaque photo une seule fois et peut lui-même effectuer les fondus enchaînés entre elles.

## Envoi automatique depuis le téléphone

Un point d'accès **WebDAV** minimal sous `/dav` permet aux applications d'envoi automatique depuis le téléphone (PhotoSync, et tout client qui parle WebDAV) de déposer des photos directement dans un **répertoire de réception** Facet. Pointez ce répertoire vers l'un de vos répertoires scannés (ou un sous-répertoire de l'un d'eux) et exécutez `facet.py --watch` dessus : chaque photo envoyée est notée automatiquement dès son arrivée — le modèle de synchronisation mobile de PhotoPrism.

C'est une **simple plomberie d'envoi** — elle ne touche jamais aux sessions utilisateur ni aux JWT. L'accès se fait en HTTP Basic avec des **identifiants d'appareil partagé** configurés dans le bloc `upload` (`upload.username` / `upload.password`), et **non** un compte utilisateur. Tout l'arbre `/dav` renvoie **404 tant qu'il est désactivé** : la fonctionnalité n'est activée que lorsque `upload.username`, `upload.password` et `upload.inbox_dir` sont tous renseignés. Chaque opération est confinée à `upload.inbox_dir` — la traversée, les chemins absolus et les évasions par lien symbolique sont refusés — et les envois sont écrits sur disque de façon atomique, plafonnés à `upload.max_file_mb` (500 par défaut).

Méthodes implémentées : `OPTIONS`, `PROPFIND` (profondeur 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` ne sont pas implémentées (les clients d'envoi traitent leur absence comme un partage non verrouillable).

### Configuration

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

`inbox_dir` doit se trouver sous un répertoire scanné pour que `--watch` détecte les envois :

```bash
python facet.py /photos --watch
```

### Recette PhotoSync

1. Dans PhotoSync, ajoutez une configuration **WebDAV** (Configurer → Ajouter une configuration → WebDAV).
2. **URL / Serveur** : `http://<host>:5000/dav/` (utilisez votre hôte Facet ; `https://` si vous le faites passer par un reverse proxy).
3. **Nom d'utilisateur / Mot de passe** : le `upload.username` / `upload.password` défini ci-dessus.
4. **Dossier cible** : laissez à la racine (`/`) pour déposer dans le répertoire de réception, ou un sous-dossier que PhotoSync crée via `MKCOL`.
5. Sur l'hôte Facet, scannez le répertoire de réception en mode surveillance pour que les envois soient notés à leur arrivée :

   ```bash
   python facet.py /photos --watch
   ```

### Test rapide avec curl

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

Un `201 Created` (ou `204 No Content` en cas d'écrasement) confirme que l'envoi est arrivé dans le répertoire de réception ; `--watch` le note au prochain anti-rebond.

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
      "hide_brackets": true,
      "hide_panoramas": true,
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
| `GET /api/photo/set?path=` | L'ensemble bracketing/panorama/hdr_panorama/rafale/doublon auquel appartient une photo (la séquence l'emporte sur la rafale, la rafale sur le doublon), indexé sur `path` — jamais un identifiant de groupe, que les passes de bracketing et de panorama renumérotent chacune à partir de 1 à chaque exécution |
| `GET /api/photo/histogram?path=&bins=` | Bins de luminance + R/V/B prêts à dessiner (`bins` ∈ 32/64/128/256, 64 par défaut), mesurés lors de l'analyse sur l'image pleine résolution. Chaque canal est mis à l'échelle par un maximum global unique, jamais par le sien. `r`/`g`/`b` valent `null` pour une ligne enregistrée avant le format par canal ; 404 lorsque la ligne n'a aucun histogramme, ce qui indique au widget de retomber sur l'échantillonnage de la miniature |
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
| `PUT /api/albums/{id}/scoring_context` | `[Edition]` Définir le contexte de notation de l'album ; le matérialise sur les membres correspondant au filtre de l'album à cet instant, en laissant de côté le remplacement manuel de chaque membre (les albums intelligents résolvent `smart_filter_json` en direct), renvoie `{updated, conflicts, manual_skipped}` |
| `DELETE /api/albums/{id}/scoring_context` | `[Edition]` Effacer le contexte de notation de l'album et annuler l'attribution sur exactement les membres qu'il avait marqués, renvoie `{ok, cleared}` |
| `GET /api/albums/{id}/suggested_context` | Suggérer un contexte de notation à partir du `narrative_moment` dominant de l'album (suggestion uniquement, n'écrit rien) |
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
| `POST /api/comparison/override_category` | `[Edition]` Définir un remplacement de catégorie persistant par photo (validé par rapport aux noms de catégorie configurés ; survit au prochain recalcul) |
| `POST /api/comparison/clear_category_override` | `[Edition]` Supprimer le remplacement de catégorie d'une photo ; l'évaluation des filtres redécide au prochain recalcul |
| `POST /api/recalculate` | Recalculer les scores avec les poids actuels |

### Tri de rafale

| Point d'accès | Description |
|----------|-------------|
| `GET /api/burst-groups` | Lister les groupes de rafale pour le tri |
| `POST /api/burst-groups/select` | Sélectionner les photos à conserver d'un groupe de rafale |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Groupes de photos visuellement similaires |
| `POST /api/similar-groups/select` | Sélectionner les photos à conserver d'un groupe similaire |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene\|bracket\|panorama\|hdr_panorama&exclude_rejected=true&similarity_threshold=&page=&per_page=` | Groupes de rafale/similaires/scène/séquence pour le tri. `group_by` (par défaut `all`) sélectionne les groupes combinés rafale+similaires, rafale uniquement, similaires uniquement, scènes chronologiques (les groupes de scène ajoutent `type`/`start`/`end`/`moment`/`moment_confidence` ; le paramètre `sort` est ignoré en mode scène), ou l'un des genres de séquence « conserver intact » (`bracket`, `panorama`, `hdr_panorama` — chacun sa propre granularité, jamais fondus dans `all`). `exclude_rejected` (par défaut `true`) masque les photos avec `is_rejected=1` ; les groupes ayant moins de 2 photos restantes sont supprimés. Lorsqu'une tête de classement des photos à conserver est entraînée, chaque photo porte aussi `keeper_prob` et chaque groupe porte `keeper_best_path` |
| `POST /api/culling-groups/confirm` | Confirmer les sélections de tri. Corps `{group_id, type, paths, keep_paths}` ; `type` vaut `burst \| similar \| scene \| bracket \| panorama \| hdr_panorama`. `type:'scene'` enregistre les lignes de comparaison de tri de scène ; les trois genres de séquence rejettent comme les autres mais n'enregistrent aucune paire de comparaison, car préférer un barreau d'une échelle ou une image d'un panoramique ne dit rien du goût |
| `POST /api/culling/auto` | `[Edition]` Tri automatique en un bouton pour toute une portée. Corps `{group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, dry_run, profile?, trim_brackets}` ; `group_by` vaut `all \| burst \| similar \| scene` (les genres de séquence ne sont pas une portée valide ici — voir `trim_brackets`). `profile` nomme un préréglage `cull_profiles` dont sont tirés `strictness`/`min_keep_per_group` lorsqu'ils sont omis. `dry_run` (par défaut `true`) renvoie l'aperçu conservation/rejet par groupe, une application rejette le reste et enregistre les paires de tri. `trim_brackets` (par défaut `false`) rogne en plus les bracketings dont l'exposition de référence n'écrête ni les ombres ni les hautes lumières jusqu'à ne garder que cette vue de référence — le seul chemin du tri automatique qui réduise jamais une série de séquence |
| `GET /api/culling/suggest_profile?album_id=&date_from=&date_to=` | Déduit le type de prise de vue dominant de la portée à partir de ses catégories, moments narratifs, nombres de visages et heures de capture stockés, et nomme le préréglage `cull_profiles` qui lui correspond, avec un niveau de confiance et les décomptes de preuves sur lesquels il se base ; mis en cache par portée. `profile` vaut `null` sous le seuil de dominance ou quand le préréglage correspondant n'est pas configuré |
| `POST /api/culling-groups/override_sequence` | `[Edition]` Enregistre une correction persistante sur ce qu'est un ensemble d'images. Corps `{paths, kind?}` ; `kind` vaut `panorama \| hdr_panorama`, ou est omis pour marquer les images comme n'étant pas du tout un panorama. Enregistrée dans `photo_sequence_overrides` (survit à l'effacement et à la réécriture de `photos.sequence_*` par le détecteur à chaque exécution) ; prend effet au prochain `POST /api/scan/detect_panoramas` |
| `POST /api/culling-groups/clear_sequence_override` | `[Edition]` Supprime une correction de séquence manuelle pour les images indiquées, et les rend au détecteur. Corps `{paths}` |
| `POST /api/culling-group/faces` | Badges par visage (yeux ouverts/fermés, expression, confiance) pour un groupe, en un seul lot |
| `GET /api/photo/key_subject?path=` | De quoi (ou de qui) parle une photo : son visage le mieux classé, sinon sa boîte de saillance persistée, sous forme de boîte + centre `normalized_frame_xyxy`. Résolu à chaque requête depuis les colonnes stockées (aucun modèle, aucun cache) ; `kind:"none"` quand ni l'un ni l'autre n'existe |
| `POST /api/photos/key_subjects` | La même réponse pour jusqu'à 1000 chemins en un seul appel (`key_subjects_by_path`) — la cible du zoom de la chambre noire et le badge de personne principale. Chaque chemin demandé est présent ; ceux qui sont inconnus ou invisibles reviennent en `kind:"none"` plutôt qu'absents |
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
| `POST /api/scan/recompute` | `[Edition]` Déclencher un recalcul des agrégats sur toute la bibliothèque (`--recompute-average`) comme tâche en arrière-plan ; protégé au niveau inter-processus par `facet.LibraryLock`, il refuse donc aussi avec un 409 nommant le détenteur si un scan ou un recalcul est déjà en cours depuis un terminal, pas seulement depuis un autre onglet de la visionneuse. Contrairement à `/start`, ses arguments sont fixés côté serveur et n'acceptent aucune entrée de la requête, il ne nécessite donc pas le rôle superadmin |
| `GET /api/scan/recompute_status` | `[Edition]` Interroger la progression du recalcul : `{running, kind, progress, exit_code}` — omet le flux de journal `output_lines` réservé au superadmin que renvoie `/status` |

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
| `GET /api/config/category_priorities` | `[Edition]` Lister les catégories dans leur ordre de priorité (évaluation) actuel |
| `POST /api/config/category_priorities` | `[Edition]` Réorganiser la priorité d'évaluation des catégories ; permute les valeurs de priorité existantes selon le nouvel ordre plutôt que de les renuméroter |
| `GET /api/config/scoring_contexts` | Lister les contextes de notation configurés, chacun avec son ordre de catégorie effectif résolu |
| `PUT /api/config/scoring_contexts/{name}` | `[Edition]` Réécrit le delta `promote`/`excluded` d'un contexte (corps `{promote, excluded}`) ; rejette une catégorie inconnue, `default` dans l'une ou l'autre liste, et les doublons dans `promote` — un nom présent dans les deux listes est accepté et `excluded` l'emporte |

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
| `POST /api/cull/apply` | `[Edition]` Copier les gardés ou déplacer/mettre à la corbeille les rejetés vers un dossier (voir [Trier vers un dossier](#trier-vers-un-dossier)). Corps `{paths?, filters?, action, target_dir?, include_companions, include_sequence_siblings, dry_run}` — soit `paths`, soit un ensemble `filters` de galerie ; `action` vaut `copy_keeps \| trash_rejects \| move_rejects` ; `include_companions` (par défaut `false`) ajoute le RAW compagnon et le `.xmp` de même radical de chaque fichier ; `include_sequence_siblings` (par défaut `false`) ajoute chaque autre image partageant le `(sequence_kind, sequence_group_id)` d'une photo correspondante **dont le propre état de rejet correspond à l'action**, de sorte qu'une image gardée n'est jamais détruite parce qu'une image sœur a été rejetée ; `dry_run` vaut `true` par défaut. La réponse ajoute `matched` (chemins éligibles à l'action) et `sequence_siblings` (nombre d'images sœurs, indiqué même quand l'option est désactivée) en plus de `skipped` / `excluded_by_state` / `not_visible` |

### Plugins

| Point d'accès | Description |
|----------|-------------|
| `GET /api/plugins` | Lister les plugins configurés |
| `POST /api/plugins/test-webhook` | Tester un plugin de webhook |

### Immich

| Point d'accès | Description |
|----------|-------------|
| `POST /api/immich/webhook` | Reçoit un webhook de workflow Immich et répercute immédiatement la note poussée ; un asset que Facet n'a pas encore noté est mis en file pour le prochain `--immich-sync`. Authentification par jeton statique (`immich.webhook.token_env` ; non défini ⇒ 404) ; ne déclenche jamais de scan. Voir [docs/IMMICH.md](IMMICH.md) |

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
