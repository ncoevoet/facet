# Facet

> 🌐 [English](README.md) · **Français** · [Deutsch](README.de.md) · [Italiano](README.it.md) · [Español](README.es.md) · [Português](README.pt.md) · [简体中文](README.zh.md)

Facet est un moteur local d'analyse et de tri de photos. Il évalue chaque image selon 9 dimensions — de la qualité esthétique à la netteté des visages — puis vous permet de parcourir, trier et organiser votre bibliothèque via une galerie web. Tout fonctionne sur votre machine ; aucun cloud, compte ou clé d'API.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Angular](https://img.shields.io/badge/Angular-22-dd0031)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20Docker-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="Facet en action — galerie, notation par photo, tri, capsules, chronologie, carte et statistiques" width="100%">
</p>

## Fonctionnement

1. **Analyse** — Pointez Facet vers un dossier de photos. Chaque image est analysée pour sa qualité, sa composition et ses visages. Prend en charge JPEG, HEIF/HEIC, 10 formats RAW, JPEG XL, AVIF, PNG, WebP, TIFF et plus — voir les [types de fichiers pris en charge](docs/fr/README.md#types-de-fichiers-pris-en-charge).
2. **Parcours** — Ouvrez la galerie web pour explorer votre bibliothèque avec des filtres, une recherche et plusieurs modes d'affichage.
3. **Tri** — Facet détecte les rafales, signale les clignements, regroupe les photos similaires et fait remonter les meilleurs choix. Les bracketings d'exposition et les séries panorama/HDR sont reconnus et conservés intacts plutôt que dispersés par le tri.

Le GPU est détecté automatiquement et reste optionnel. Facet fonctionne en mode CPU uniquement ou avec jusqu'à 24 Go de VRAM.

## Fonctionnalités

### Évaluer

Chaque photo est évaluée selon 9 dimensions : qualité esthétique, composition, qualité des visages, netteté des yeux, netteté technique, couleur, exposition, saillance du sujet et plage dynamique. Les photos sont classées par contenu (portrait, paysage, macro, rue, etc. — plus de 30 catégories) et évaluées avec des poids propres à chaque catégorie. Un filtre **Meilleurs choix** classe la bibliothèque selon un score combiné.

Survolez n'importe quelle photo pour afficher le détail du score et les données EXIF dans le panneau latéral de la galerie, ou passez à une bulle au survol qui résume les notes clés d'un coup d'œil.

<img src="docs/screenshots/hover-tooltip.jpg" alt="Infobulle au survol avec le détail du score" width="100%">

### Trier

- **Détection de rafales** — regroupe les prises de vue en rafale et sélectionne automatiquement la meilleure d'après la netteté, la qualité et la détection des clignements
- **Protection des séries** — les bracketings d'exposition, les panoramas et les panoramas HDR (`--detect-sequences` / `--detect-panoramas`) sont reconnus comme des séries ; la chambre noire de tri démarre avec chaque image d'une série marquée comme conservée
- **Groupes de similarité** — trouve les photos visuellement similaires dans toute la bibliothèque, quel que soit leur moment de prise de vue
- **Scènes** — regroupe une séance en « scènes » chronologiques selon les écarts entre prises de vue, pour trier dans l'ordre du récit ; touchez pour marquer puis confirmez pour rejeter
- **Tri automatique** — un bouton trie tout un périmètre (tous les groupes, ou rafales / similaires / scènes seulement, éventuellement restreint à un album ou une période) avec un aperçu en simulation, un budget de photos conservées et un album Temps forts facultatif
- **Tri automatique en terminal** — `python facet.py --auto-cull [PATH]` prévisualise le tri en simulation, `--apply` l'écrit et `--copy-keepers DIR` copie les photos conservées (voir [docs/fr/COMMANDS.md](docs/fr/COMMANDS.md#tri-en-ligne-de-commande))
- **Profils par genre** — les préréglages sport / mariage / concert / faune regroupent rigueur, budget de photos conservées, seuil de similarité et filtres de visage en un seul choix
- **Aperçu du rendu développé** `[Edition]` — affiche une photo à travers un style darktable nommé dans la chambre noire de tri, pour trier sur le rendu développé plutôt que sur l'aperçu RAW plat
- **Gros plans du sujet** — les groupes sans visage (faune, macro, produit) se comparent sur une bande recadrée automatiquement sur le sujet, avec des badges de netteté normalisés par groupe
- **Nettoyage des indésirables** — détection zero-shot des fichiers non photographiques parasites (captures d'écran, documents, reçus, mèmes, diapositives) avec une file de revue rapide : conservez ou rejetez chaque candidat, ou rejetez-les tous d'un coup
- **Badges par visage au tri** — la visionneuse de tri affiche des badges par visage (yeux ouverts/fermés, expression, confiance de détection) au lieu d'un seul indicateur de clignement au niveau de la photo ; les blendshapes MediaPipe facultatifs affinent la lecture des yeux et du sourire
- **Détection des clignements** — signale les prises aux yeux fermés pour les masquer ou les rejeter en un clic
- **Détection des doublons** — identifie les images quasi identiques par hachage perceptuel

<table><tr>
<td><img src="docs/screenshots/burst-culling.jpg" alt="Tri des rafales" width="100%"></td>
<td><img src="docs/screenshots/similar-photos.jpg" alt="Groupes de similarité pour le tri" width="100%"></td>
</tr></table>

### Parcourir

- **Modes de galerie** — mosaïque (rangées justifiées préservant les proportions) et grille (cartes uniformes avec superposition des métadonnées)
- **Filtres** — plage de dates, tag de contenu, motif de composition, appareil, objectif, personne, dossier, niveau de qualité, note (étoiles) et plages de métriques personnalisées
- **Recherche sémantique** — saisissez une requête en langage naturel comme « coucher de soleil à la plage » et trouvez les photos correspondantes grâce à la recherche par embedding et par texte
- **Chronologie** — navigateur chronologique avec navigation par année/mois et défilement infini
- **Carte** — photos géolocalisées sur une carte interactive avec regroupement des marqueurs
- **Capsules** — diaporamas thématiques : voyages avec noms de lieux, collection dorée, palettes saisonnières, photos d'une personne, et plus encore
- **Dossiers** — parcours par structure de répertoires avec fil d'Ariane et photos de couverture
- **Moments narratifs** — des étiquettes zero-shot de scène et d'activité (plage, fête, concert…) nomment vos scènes, filtrent et trient la galerie, et alimentent la sélection des capsules
- **Souvenirs** — « Ce jour-là » : photos prises à la même date les années précédentes
- **Diaporama** — mode plein écran avec transitions thématiques, enchaînement automatique entre capsules et contrôles au clavier

<table><tr>
<td><img src="docs/screenshots/filter-panel.jpg" alt="Barre latérale de filtres" width="100%"></td>
<td><img src="docs/screenshots/semantic-search.jpg" alt="Résultats de la recherche sémantique" width="100%"></td>
</tr></table>

<details><summary>Barre latérale de filtres — toutes les sections développées (cliquer pour afficher)</summary>
<p align="center"><img src="docs/screenshots/filter-sidebar-full.jpg" alt="Les cinq onglets de la barre latérale de filtres côte à côte : Parcourir, Tri, Qualité, Sujet et Affichage" width="900"></p>
</details>

**Conseils de flux de travail :**
- **`/timeline`** descend des années aux mois puis aux jours ; cliquez sur un jour pour ouvrir la galerie à cette date.
- **`/capsules`** crée des diaporamas thématiques (voyages, « Visages de », saisonniers, dorés) que vous pouvez enregistrer comme albums — le meilleur choix pour sélectionner les meilleures prises d'un voyage.
- La galerie masque par défaut les clignements, les rafales secondaires et les doublons. Lorsque la bannière **« N photos masquées par les filtres actuels »** apparaît, cliquez sur « Tout afficher » pour développer la vue.

### Organiser

- **Reconnaissance faciale** — détection automatique des visages, regroupement en personnes et détection des clignements. Recherchez, renommez, fusionnez et organisez les groupes de personnes depuis l'interface de gestion. Les **suggestions de fusion** repèrent les groupes au visage semblable qui pourraient être la même personne.
- **Albums** — collections manuelles avec glisser-déposer, ou albums intelligents qui se remplissent automatiquement à partir de combinaisons de filtres enregistrées
- **Notes et favoris** — notes (étoiles) (1 à 5), favoris et marqueurs de rejet. Faites défiler les notes en un seul clic.
- **Tags** — tags de contenu générés par IA avec un vocabulaire configurable. Cliquez sur n'importe quel tag pour filtrer la galerie.
- **Opérations par lots** — sélection multiple par Maj+clic, Ctrl+clic ou Ctrl+A (tout sélectionner). Définissez des notes, basculez les favoris, marquez des rejets ou ajoutez à des albums en masse — avec une annulation de 7 secondes pour chaque action par lot.
- **Tout au clavier** — les flèches naviguent dans la galerie, Entrée ouvre, Espace sélectionne ; appuyez sur `?` à tout moment pour afficher l'aide-mémoire des raccourcis.

<img src="docs/screenshots/albums.jpg" alt="Albums — collections manuelles et intelligentes" width="100%">

<table><tr>
<td><img src="docs/screenshots/persons-manage.jpg" alt="Page de gestion des personnes" width="100%"></td>
<td><img src="docs/screenshots/person-gallery.jpg" alt="Galerie d'une personne" width="100%"></td>
</tr></table>

### Comprendre

- **Statistiques** — tableaux de bord sur l'utilisation du matériel, la répartition par catégorie, la chronologie de prise de vue et les corrélations entre métriques
- **Critique IA** — détail du score montrant la contribution de chaque métrique ; évaluation en langage naturel par VLM `[GPU]` `[16gb/24gb]`
- **Réglage des poids** — éditeur de poids par catégorie avec aperçu du score en direct. La comparaison A/B de photos apprend de vos choix et suggère des poids optimisés.
- **Contextes de notation** — choisissez *quelle* catégorie note une photo : réorganisez la priorité des catégories, appliquez un contexte nommé (Action/Scène, Séance portrait, Faune, …) par album, ou fixez une catégorie sur une photo.
- **Tri « Mon goût »** — triez la galerie selon le score appris du classeur personnel, avec un badge de confiance indiquant la couverture apprise et la précision sur données de validation
- **Apprentissage à partir des étiquettes** — les décisions de tri, les notes (étoiles), les favoris et les rejets alimentent l'optimiseur de poids (`--sync-label-comparisons`, `--mine-insights`)
- **Instantanés** — enregistrez, restaurez et comparez des configurations de poids
- **Histogramme** — histogramme RVB/luminance avec indicateurs d'écrêtage, dans le panneau latéral de la galerie et la vue détaillée
- **Légendes IA** `[GPU]` `[16gb/24gb]` — descriptions textuelles, modifiables `[Edition]` et traduisibles en 5 langues (la consultation est ouverte ; la génération et la modification requièrent l'édition)

<table><tr>
<td><img src="docs/screenshots/stats-gear.jpg" alt="Statistiques d'équipement" width="100%"></td>
<td><img src="docs/screenshots/stats-categories.jpg" alt="Analyse par catégorie" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/stats-timeline.jpg" alt="Chronologie de prise de vue" width="100%"></td>
<td><img src="docs/screenshots/stats-correlations.jpg" alt="Corrélations entre métriques" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/critique.jpg" alt="Boîte de dialogue Critique IA" width="100%"></td>
<td><img src="docs/screenshots/snapshots.jpg" alt="Instantanés" width="100%"></td>
</tr></table>

<table><tr>
<td><img src="docs/screenshots/weights-sliders.jpg" alt="Curseurs de poids par catégorie" width="100%"></td>
<td><img src="docs/screenshots/weights-compare.jpg" alt="Comparaison A/B de photos" width="100%"></td>
</tr></table>

### Partager

- **Partage d'albums** — générez des liens partageables pour n'importe quel album, sans connexion requise pour les destinataires. Révoquez l'accès à tout moment.
- **Épreuvage client** — un album partagé peut fonctionner en mode épreuvage : les clients mettent un cœur aux photos et laissent des commentaires avec le seul lien (plus un code PIN facultatif), sans aucun lien avec vos propres notes
- **Envoi automatique depuis le téléphone** — pointez PhotoSync ou toute appli WebDAV vers la boîte de réception `/dav` intégrée ; `--watch` note les nouvelles photos dès leur arrivée
- **Cadres photo et kiosques** — un point d'accès protégé par jeton envoie vos meilleures photos sélectionnées aux cadres photo connectés et aux tableaux de bord Home Assistant
- **Agents IA (MCP)** — un point d'accès [Model Context Protocol](https://modelcontextprotocol.io/) (activé par défaut, `viewer.mcp.enabled`) permet aux assistants de rechercher dans la bibliothèque avec des jetons personnels révocables. Les niveaux de jeton supérieurs peuvent noter, étiqueter, organiser et trier ; les actions destructives sont d'abord prévisualisées et exigent une confirmation
- **Export de portfolio** `[Edition]` — transforme un album en galerie HTML statique autonome (aucune référence CDN, fonctionne hors ligne) à déposer sur n'importe quel hébergeur
- **Recadrages pour les réseaux sociaux** `[Edition]` — exports en pleine résolution cadrés sur le sujet détecté, aux formats carré, portrait et story
- **Téléchargement de photos** — téléchargez des photos individuelles ou des sélections depuis la galerie
- **Export** — exportez tous les scores en CSV ou JSON pour une analyse externe

### En plus

- **Mode sombre et clair** avec 10 thèmes de couleur d'accent ; respecte la préférence du système
- **Adaptatif** — s'adapte du mobile au bureau, avec une feuille d'actions par lot tactile sur les petits écrans
- **PWA installable** — manifeste d'application web + service worker : installation sur l'écran d'accueil, coque d'application hors ligne, miniatures en cache
- **Galerie virtualisée** — n'affiche qu'une poignée de nœuds DOM quelle que soit la taille de la bibliothèque, pour un défilement rapide même au-delà de 100 000 photos
- **Analyses reprenables** — les analyses interrompues reprennent (`--resume`), les fichiers en échec sont suivis et réessayables (`--retry-failed`), la progression est diffusée vers l'interface web
- **7 langues dans l'interface** — l'interface est disponible en anglais, français, allemand, espagnol, italien, portugais brésilien et chinois simplifié (简体中文) ; la documentation est disponible dans les sept langues
- **Multi-utilisateur** — répertoires, notes et accès par rôle propres à chaque utilisateur
- **Plugins et webhooks** — actions personnalisées déclenchées sur les événements d'évaluation
- **Analyse depuis l'interface web** — déclenchez des analyses depuis le navigateur (superadmin en mode multi-utilisateurs ; accès édition sur une installation mono-utilisateur dotée d'un mot de passe d'édition)

<table><tr>
<td width="33%"><img src="docs/screenshots/mobile-gallery.jpg" alt="Galerie sur mobile" width="100%"></td>
<td width="33%"><img src="docs/screenshots/tablet-gallery.jpg" alt="Galerie sur tablette" width="100%"></td>
<td width="33%"><img src="docs/screenshots/gallery-mosaic.jpg" alt="Mosaïque sur ordinateur de bureau" width="100%"></td>
</tr></table>

## Ce dont vous avez besoin

- **N'importe quelle machine (CPU)** exécute l'essentiel de Facet : évaluation, visages, tri, galerie, recherche, albums et export des métadonnées.
- **Apple Silicon** utilise automatiquement le backend Metal (`mps`). Le profil `auto` suit la mémoire unifiée : 32 Go atteint `16gb`, 48 Go atteint `24gb`.
- **Un GPU NVIDIA** avec les profils `16gb`/`24gb` débloque les modèles les plus performants : TOPIQ, SigLIP 2, tagging par VLM, légendes et critique IA, saillance du sujet.
- **Pas de GPU ?** Pointez le tagging, les légendes et la critique VLM vers un serveur **Ollama** ou **compatible OpenAI** distant avec `vlm_backend` dans `scoring_config.json`.
- **L'édition dans le visualiseur** (notes, visages, tri) nécessite le **mot de passe d'édition**. Le bouton Analyser nécessite `viewer.features.show_scan_button: true` et l'accès édition (le rôle **superadmin** en mode multi-utilisateurs).

→ Prérequis complets par fonctionnalité (GPU, profil VRAM, paquets optionnels, authentification) : **[Installation › Exigences par fonctionnalité](docs/fr/INSTALLATION.md#exigences-par-fonctionnalité)**.

## Facet est-il fait pour vous ?

Facet évalue, classe et trie une bibliothèque de photos locale et sert une galerie pour la parcourir. Il fonctionne sur votre propre matériel et garde vos photos hors du cloud.

**Un bon choix si vous :**

- possédez une grande bibliothèque locale et souhaitez trouver vos meilleures prises et écarter les rafales et quasi-doublons ;
- voulez une évaluation de la qualité, de la composition et des visages que vous pouvez régler selon votre propre goût (elle apprend de vos comparaisons A/B) ;
- préférez l'auto-hébergement et la confidentialité — aucun envoi vers le cloud, aucun compte, aucun abonnement ;
- éditez déjà dans Lightroom, darktable, digiKam ou Immich — Facet écrit les notes, les libellés, les mots-clés, les légendes et les régions de visages dans des fichiers annexes `.xmp` (les originaux restent intacts sauf si vous demandez l'intégration : l'action « Écrire les métadonnées dans le fichier » de la galerie ou `--export-sidecars --embed-originals`) et relit les modifications avec `--import-sidecars`. Un module externe Lightroom `facet.lrplugin` ajoute un flux bidirectionnel. Voir [Interopérabilité](docs/fr/INTEROP.md).

**Probablement pas pour vous si vous voulez :**

- un remplaçant de Google Photos clé en main, mobile et adossé au cloud, avec sauvegarde automatique du téléphone ;
- de l'édition ou du développement RAW — Facet évalue et organise, il n'édite pas ;
- une application de bureau sans configuration — il faut Python, et les meilleurs modèles nécessitent un GPU.

**Comment il se situe par rapport aux autres outils**

- Les bibliothèques auto-hébergées (Immich, PhotoPrism) se concentrent sur l'organisation, la recherche et la sauvegarde. Facet ajoute l'évaluation de la qualité, le classement et un flux de tri qu'elles n'ont pas, mais il n'a ni application mobile ni sauvegarde/synchronisation intégrée.
- Les applications de tri par IA (Aftershoot, Narrative, FilterPixel) sont des trieurs commerciaux soignés, souvent avec l'édition intégrée. Facet est gratuit, local, plus large (galerie, recherche, visages), et son évaluation est réglable — mais c'est un projet d'un seul développeur, sans leur support ni leur édition RAW.
- Les éditeurs et catalogues (Lightroom, darktable, digiKam) développent et gèrent les photos. Facet les complète via l'interop de métadonnées XMP décrite ci-dessus plutôt que de les remplacer.

Le score esthétique repose sur un modèle et reste approximatif ; attendez-vous à régler les poids pour les faire correspondre à votre goût.

## Démarrage rapide

### Docker (recommandé)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env      # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose up -d      # puis ouvrez http://localhost:5000
```

Vous avez une carte NVIDIA ? Utilisez le bloc correspondant à sa taille dans
[Installation](docs/fr/INSTALLATION.md#installer-avec-docker) — une ligne pour chacune des cartes 8 Go, 16 Go
et 24 Go.

### Sans Docker (Linux, macOS)

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh                        # détecte votre matériel, installe tout
source venv/bin/activate
python facet.py /path/to/your/photos   # évaluer les photos
python viewer.py                       # galerie → http://localhost:5000
```

> **macOS :** le récepteur AirPlay du Centre de contrôle occupe le port 5000 par défaut. Si vous voyez « Address already in use », lancez `python viewer.py --port 5001`.

Guide complet : **[Installation](docs/fr/INSTALLATION.md)** — configuration par matériel, téléchargements
au premier lancement, et [dépannage des conflits de dépendances](docs/fr/INSTALLATION.md#résoudre-les-conflits-de-dépendances).
Lancez `python facet.py --doctor` pour diagnostiquer les problèmes de GPU.

Première fois ? Suivez le parcours **[Prise en main](docs/fr/GETTING_STARTED.md)** : analyser, passer en revue, apprendre, écarter, taguer et exporter.

## Documentation

| Document | Description |
|----------|-------------|
| [Installation](docs/fr/INSTALLATION.md) | Prérequis, configuration GPU, profils VRAM, dépendances |
| [Prise en main](docs/fr/GETTING_STARTED.md) | Parcours de premier lancement : de l'installation à l'analyse, au tri, à l'apprentissage, à l'écartement, au tagging et à l'export |
| [Commandes](docs/fr/COMMANDS.md) | Référence de toutes les commandes CLI |
| [Configuration](docs/fr/CONFIGURATION.md) | Référence complète de `scoring_config.json` |
| [Évaluation](docs/fr/SCORING.md) | Catégories, poids, guide de réglage |
| [Reconnaissance faciale](docs/fr/FACE_RECOGNITION.md) | Flux des visages, regroupement, gestion des personnes |
| [Visualiseur](docs/fr/VIEWER.md) | Fonctionnalités et utilisation de la galerie web |
| [API](docs/API.md) | Référence de l'API HTTP du visualiseur |
| [Interopérabilité](docs/fr/INTEROP.md) | Faire circuler notes/tags avec Lightroom, Capture One, digiKam, darktable |
| [Immich](docs/fr/IMMICH.md) | Synchroniser notes et favoris avec Immich, plus le webhook entrant |
| [Relier](docs/fr/RELINK.md) | Relier une photo déplacée |
| [Agents IA](docs/fr/AGENTS.md) | Laisser un assistant compatible MCP interroger la bibliothèque avec un jeton personnel |
| [Déploiement](docs/fr/DEPLOYMENT.md) | Déploiement en production (NAS Synology, Linux, Docker) |
| [Contribuer](CONTRIBUTING.md) | Configuration de développement, architecture, style de code |

## Licence

[MIT](LICENSE)

### Licences

Le code de Facet est sous licence MIT. Certains modèles par défaut sont **non commerciaux** : pyiqa (TOPIQ, LIQE, …) et les poids InsightFace. Définissez `licensing.mode: commercial` pour n'utiliser que des remplaçants à licence permissive ([Licences](docs/fr/CONFIGURATION.md#licences), [Modèles tiers](docs/fr/THIRD_PARTY_MODELS.md)).
