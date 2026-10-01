# Prise en main

> 🌐 [English](../GETTING_STARTED.md) · **Français** · [Deutsch](../de/GETTING_STARTED.md) · [Italiano](../it/GETTING_STARTED.md) · [Español](../es/GETTING_STARTED.md) · [Português](../pt/GETTING_STARTED.md) · [简体中文](../zh/GETTING_STARTED.md)

Un parcours de première session pour le cas le plus courant : vous venez de prendre ou
d'importer un lot de photos et vous voulez obtenir un ensemble trié. Il suit six étapes —
importer, regrouper les photos quasi identiques, apprendre vos goûts à Facet, écarter,
taguer, exporter — et renvoie vers la page qui explique chacune plutôt que de la répéter.

![Facet gallery walkthrough](../screenshots/walkthrough.gif)

## Avant de commencer

### 1. Définir un mot de passe d'édition

Une installation neuve est en **lecture seule**. Vous pouvez parcourir la galerie (sous
réserve de `viewer.password`, si vous en définissez un), mais toute modification — notes,
tri, visages, albums, tags et bouton Scanner — est refusée tant que vous n'avez pas défini
`viewer.edition_password` dans `scoring_config.json` et redémarré la visionneuse (la
configuration n'est pas rechargée à chaud).

Avec le `docker-compose.yml` fourni, inutile d'en inventer un : l'image génère un mot de
passe au premier démarrage et l'affiche une seule fois. Lisez-le avec :

```bash
docker compose logs facet
```

Connectez-vous ensuite comme éditeur depuis la galerie. Détails : [Mode mono-utilisateur](VIEWER.md#mode-mono-utilisateur-par-défaut) et [Réglages Docker modifiables](INSTALLATION.md#réglages-docker-modifiables).

![Edition login](../screenshots/getting-started-edition-login.jpg)

### 2. Choisir un mode d'installation

Docker est la voie la plus courte sous Windows, macOS et Linux ; l'installation native
s'adresse à ceux qui préfèrent se passer de conteneurs. [Quelle installation me convient ?](INSTALLATION.md#quelle-installation-me-convient)
contient le tableau.

Deux points piègent souvent avec les conteneurs :

- **Configuration et propriété des fichiers.** Le conteneur s'exécute avec l'uid 1000, que
  Podman sans root associe à un subuid de l'hôte ; les fichiers qu'il crée dans `./facet-config`
  peuvent donc ne pas appartenir à votre utilisateur. Voir
  [Propriété du fichier en conteneur](INSTALLATION.md#propriété-du-fichier-en-conteneur).
- **Les chemins sont ceux du conteneur, pas ceux de l'hôte.** Vous scannez `/data/photos`, pas
  `~/Pictures`. Voir [Sémantique des chemins en conteneur](DEPLOYMENT.md#sémantique-des-chemins-en-conteneur).

### 3. Pas de GPU ? Aucun souci

Tout — notation, visages, tags, tri, bouton Scanner — fonctionne sur un processeur avec le
profil CPU `legacy` ; c'est simplement plus lent. Lisez
[Pas de carte graphique](INSTALLATION.md#pas-de-carte-graphique) et
[Quel profil correspond à mon matériel ?](INSTALLATION.md#quel-profil-correspond-à-mon-matériel). Une carte
graphique n'est jamais une condition pour que le bouton Scanner apparaisse.

### 4. Surveiller la mémoire

Un conteneur limité en mémoire peut être tué en plein scan avec les profils les plus
lourds. Consultez
[Limites de mémoire du conteneur](DEPLOYMENT.md#limites-de-mémoire-du-conteneur) avant d'en plafonner un ; sur un
Mac, voir [Mémoire sur un Mac](INSTALLATION.md#mémoire-sur-un-mac).

## Le flux de travail

### Étape 1 : importer les images

Placez vos photos dans le dossier vers lequel Facet pointe (JPEG, HEIF/HEIC, PNG et les
formats RAW courants — voir [types de fichiers pris en charge](README.md#types-de-fichiers-pris-en-charge)) et
scannez-le. Vous pouvez le faire depuis le terminal ([Analyse](COMMANDS.md#analyse)) ou
depuis le navigateur :

- Définissez `viewer.features.show_scan_button` à `true` (désactivé par défaut).
- Mono-utilisateur : il faut un mot de passe d'édition **et** être connecté comme éditeur.
  Multi-utilisateurs : il faut le rôle superadmin.
- Ajoutez le dossier à `viewer.scan_directories` pour que le lanceur ait quelque chose à proposer.

Un bouton **Scanner de nouvelles photos** apparaît alors au-dessus de la grille de la
galerie, quelle que soit la largeur d'écran, et pas seulement sur la galerie vide. Règles
complètes : [Déclenchement d'un scan](VIEWER.md#déclenchement-dun-scan). Le premier
scan télécharge une seule fois les modèles d'IA ([Premier lancement](INSTALLATION.md#premier-lancement-à-quoi-sattendre)).

![Scan button above the gallery](../screenshots/getting-started-scan-button.jpg)

### Étape 2 : repérer doublons, rafales et photos quasi identiques

Facet regroupe seul les images de rafale, les quasi-doublons, les bracketings d'exposition
et les panoramas, et la galerie **masque par défaut l'essentiel d'un ensemble** pour que
vous n'en voyiez qu'un représentant. Si votre nombre de photos paraît plus bas que prévu,
ce sont les bascules de masquage, pas des fichiers manquants — voir
[Options d'affichage](VIEWER.md#options-daffichage) et [Filtres par défaut](VIEWER.md#filtres-par-défaut).
Pour voir un ensemble entier côte à côte, ouvrez [Photos similaires](VIEWER.md#photos-similaires) ou la
chambre noire [Tri sélectif](VIEWER.md#tri-sélectif) ; les ensembles qui doivent rester entiers sont décrits dans
[Panoramas et bracketings d'exposition](VIEWER.md#panoramas-et-bracketings-dexposition).

![Burst culling](../screenshots/burst-culling.jpg)

### Étape 3 : apprendre à Facet laquelle vous préférez

Chaque choix que vous faites pendant le tri, et chaque choix A/B en mode comparaison, est un
signal. Facet en tire un classement personnel et l'expose sous le nom **Mes goûts**
([My Taste](VIEWER.md#my-taste)). Choisissez « celle-ci l'emporte sur celle-là » dans le
[Mode de comparaison par paires](VIEWER.md#mode-de-comparaison-par-paires), ou triez simplement — l'écran
[Tri sélectif](VIEWER.md#tri-sélectif) enregistre vos conservations et rejets. Le classement se ré-entraîne
tout seul après suffisamment de nouveaux choix, et seulement une fois que vous faites une
pause ([Ré-entraînement automatique](CONFIGURATION.md#ré-entraînement-automatique)).

![Comparing two photos](../screenshots/getting-started-teach.jpg)

### Étape 4 : écarter ce dont vous ne voulez pas

Rejetez des photos pendant le tri, ou sélectionnez un ensemble et agissez dessus
([Sélection multiple & actions groupées](VIEWER.md#sélection-multiple--actions-groupées)) :
[Garder le top %](VIEWER.md#garder-le-top-n), [Trier vers un dossier](VIEWER.md#trier-vers-un-dossier) ou
[Supprimer](VIEWER.md#supprimer). Trier vers un dossier s'affiche d'abord en simulation jusqu'à ce que vous l'appliquiez. Supprimer envoie les fichiers
à la corbeille du système immédiatement, et seulement si `viewer.cull.allow_trash` est activé (il est à `false` par défaut).
[Annuler](VIEWER.md#annuler) couvre les changements de drapeaux par lot et les confirmations de tri, pas ces opérations
sur les fichiers. Les dossiers où un tri peut écrire forment une liste d'autorisation : vos
dossiers de scan plus `viewer.export.allowed_target_dirs`, de sorte qu'un sous-dossier de
l'arborescence de photos fonctionne sans configuration, alors qu'un dossier extérieur est refusé tant que vous ne l'ajoutez pas. Voir
[Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri). Pour trier
sans interface : [Trier une séance depuis le terminal](COMMANDS.md#trier-une-séance-depuis-le-terminal).

Les photos que vous supprimez hors de Facet laissent leur ligne en base jusqu'à ce que vous lanciez le nettoyage décrit dans
[Maintenance de la base de données](COMMANDS.md#maintenance-de-la-base-de-données).

![Bulk actions on a selection](../screenshots/getting-started-discard.jpg)

### Étape 5 : ajouter tags et métadonnées aux photos retenues

Facet tague automatiquement les photos, et vous pouvez ajouter **vos propres tags** : dans
la vue détail pour une photo, ou depuis les actions groupées pour une sélection. Les tags
manuels survivent aux nouveaux scans, le filtre de tags et la recherche les trouvent, et ils
sont masqués dans les liens de partage. Les mots-clés des sidecars XMP externes sont
importés comme tags manuels ; retirer un tag dans Facet ne le retire pas des sidecars que
Facet a déjà écrits. Voir [Tags manuels](VIEWER.md#tags-manuels) et
[Tags manuels et mots-clés XMP](INTEROP.md#tags-manuels-et-mots-clés-xmp). Pour transférer notes
et mots-clés vers Lightroom, Capture One, digiKam ou darktable, voir [Interopérabilité](INTEROP.md)
(cela nécessite [exiftool](INSTALLATION.md#exiftool) pour l'intégration).

![Manual tags dialog](../screenshots/getting-started-manual-tags.jpg)

### Étape 6 : exporter l'ensemble trié

Placez vos photos retenues dans un album et exportez depuis celui-ci, ou utilisez
[Export vers éditeur](VIEWER.md#export-vers-éditeur) pour un transfert vers un éditeur, ou
[Trier vers un dossier](VIEWER.md#trier-vers-un-dossier) pour copier les photos retenues dans un dossier. La
même liste d'autorisation de destinations qu'à l'étape 4 s'applique
([Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri)).

![Exporting an album](../screenshots/getting-started-export.jpg)

## Et ensuite

[Visionneuse](VIEWER.md) pour chaque fonctionnalité de la galerie, [Commandes](COMMANDS.md) pour le terminal,
[Notation](SCORING.md) pour régler ce qui fait une bonne photo, et
[Déploiement](DEPLOYMENT.md) pour un NAS ou un serveur partagé.
