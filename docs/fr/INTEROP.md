# Recettes d'interopérabilité avec les éditeurs

> 🌐 [English](../INTEROP.md) · **Français** · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Recettes pas à pas pour faire circuler les notes, libellés et tags de Facet vers et depuis Lightroom, Capture One, digiKam et darktable. Pour la référence complète des options `--export-sidecars` / `--import-sidecars` et la correspondance des champs (`xmp:Rating`, `xmp:Label`, `dc:subject`), voir [Commandes — Aperçu et export](COMMANDS.md#aperçu-et-export).

Les originaux ne sont jamais modifiés, sauf si vous demandez l'intégration : `--embed-originals` en ligne de commande, ou **Écrire les métadonnées dans le fichier** dans le visualiseur.

## Ce qui voyage

Les positions manuelles et les décisions de revue ne voyagent que lorsque vous exportez les métadonnées dans le visualiseur ou lancez `--export-sidecars`.

- **GPS** : utilise `exif:GPSLatitude` / `exif:GPSLongitude`. Seules les positions définies manuellement sont exportées, si bien que le GPS issu du scan ne remplace jamais celui du fichier. `--embed-originals` écrit aussi le GPS EXIF dans les originaux compatibles. Effacer une position exporte un effacement explicite ; un champ absent n'efface jamais une position à l'import.
- **Date de prise de vue.** Une date corrigée est exportée en `exif:DateTimeOriginal` (et en EXIF `DateTimeOriginal` avec `--embed-originals`). Après **Utiliser la date du fichier**, l'export suivant la retire du sidecar, mais laisse intacte une date écrite par un autre éditeur.
- **Garder et rejeter.** Garder est indépendant des étoiles et des favoris. Rejeter efface Garder, les étoiles et le favori.

L'espace de noms XMP propre à Facet, `https://github.com/ncoevoet/facet/ns/1.0/`, ajoute :

| Tag | Valeurs | Rôle |
|---|---|---|
| `facet:ReviewDecision` | `kept`, `rejected`, `undecided` | Décision de revue de Facet |
| `facet:GPSState` | `set`, `cleared` | Indique si Facet a défini ou effacé la position |
| `facet:DateState` | `set` | La date de prise de vue du sidecar provient de Facet |
| `facet:KeywordState` | JSON (`version` 1 ; listes `owned`, `deleted`, `ai`, `manual`) | Quels mots-clés Facet a écrits |
| `facet:RegionOwner` | `Facet` | Les régions de visages MWG écrites par Facet |

`facet:KeywordState` permet à `--reconcile-keywords` de ne retirer que les noms appartenant à Facet, et empêche une ancienne étiquette IA de devenir un tag manuel à l'import. `facet:RegionOwner` permet à ExifTool de ne remplacer que les régions de visages de Facet.

Comment `--import-sidecars` applique une décision Facet :

- Il applique une décision lorsque les champs de revue standard concordent avec elle ou sont absents.
- Si l'état de rejet standard diffère, un autre éditeur a modifié les champs standard. Facet ignore sa décision privée et applique aux champs standard la vérification « le plus récent gagne » fondée sur la date du scan.
- Une décision exportée avec les champs de revue standard suit aussi la règle du plus récent, si bien qu'un export plus ancien ne peut pas annuler une décision plus récente. L'exception est une photo sans état de revue (ni étoiles, ni favori, ni Garder, ni rejet) : une bibliothèque réanalysée retrouve ainsi ses décisions.
- Les imports contenant uniquement une décision restent explicites (vous les demandez) et sont appliqués sans la vérification de date du scan.

Autres règles :

- Le GPS manuel déjà présent dans Facet est conservé, sauf si vous ajoutez `--overwrite-manual-gps`. Les coordonnées invalides ou incomplètes sont ignorées.
- `--user alice` limite les imports et exports aux dossiers visibles de cet utilisateur et à ses décisions privées. Le GPS reste partagé. Sans `--user`, le CLI travaille sur l'état global.
- Les imports globaux (sans `--user`), y compris les aperçus `--dry-run`, n'ont pas besoin du secret de connexion du visualiseur.
- Avec ExifTool, l'export fusionne dans les sidecars existants. Sans lui, l'export laisse intact le sidecar d'un éditeur existant et écrit un fichier de repli.
- Les exports ExifTool nécessitent les définitions de balises fournies avec Facet. Si elles sont absentes, l'export s'arrête avant de rien modifier ; réinstallez Facet.

## Le piège du nommage des sidecars RAW

Facet exporte `IMG_1234.CR2.xmp` à côté de `IMG_1234.CR2` (convention de nom complet de darktable). Lightroom Classic et Capture One utilisent généralement `IMG_1234.xmp` pour les RAW propriétaires. Les noms d'export ne changent jamais.

Pour JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` écrit plutôt dans le fichier. GIF/WebP/BMP/AVIF/JPEG XL et les RAW propriétaires nécessitent toujours un sidecar au nommage compatible.

À l'import, choisissez le nommage avec `--import-sidecars --sidecar-naming full|basename|auto` :

- `full` (par défaut) : lit `<image.ext>.xmp` ou `<image.ext>.facet.xmp`, selon la date de modification la plus récente. Le fichier principal gagne à égalité.
- `basename` : lit `<image>.xmp` (seule la dernière extension est retirée). Les sidecars à nom complet sont ignorés.
- `auto` : accepte celui qui existe. Si les deux existent, la photo est ignorée comme ambiguë ; choisissez plutôt `full` ou `basename`.

Avec `basename` et `auto`, un nom de base partagé par plusieurs images (p. ex. `same.CR3` et `same.jpg`) est refusé, même si une seule est dans la portée. Utilisez des sidecars à nom complet pour celles-ci. `same_v1.jpg` a un nom de base différent et ne pose pas de problème.

- Un fichier à double extension comme `IMG.CR2.jpg` ne lit jamais `IMG.CR2.xmp`, qui appartient à `IMG.CR2`. Il en va de même pour le repli `.facet.xmp` d'une autre image.
- Les incompatibilités, ambiguïtés et sidecars illisibles sont signalés. Facet n'essaie pas un autre nommage après un échec d'analyse.
- Le bilan compte chaque photo concernée, y compris les sidecars ignorés à cause du nommage choisi. Les avis montrent un exemple par type.
- Aucun fichier n'est renommé.

L'import n'a pas besoin d'ExifTool. La fusion à l'export, l'intégration et les rectangles de visages MWG en ont besoin. Sans lui, Facet laisse intact le sidecar d'un éditeur existant et écrit `<image.ext>.facet.xmp` sans rectangles de visages. Les autres éditeurs ne cherchent pas ce nom : transmettez-le volontairement.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (ajoutez un chemin pour restreindre la portée, par exemple `--export-sidecars /photos/2026-wedding`). Ajoutez `--embed-originals` pour aussi écrire directement dans les fichiers JPEG/HEIC/TIFF/PNG/DNG.
2. Dans le module Bibliothèque de Lightroom Classic, sélectionnez les photos (Ctrl/Cmd+A pour tout sélectionner) et choisissez **Métadonnées → Lire les métadonnées du fichier**. Lightroom remplace sa note, son libellé de couleur et ses mots-clés par ceux du sidecar (ou des métadonnées intégrées).

Le rejet de Facet (`xmp:Rating = -1`) est relu comme le drapeau Rejeter de Lightroom. Un favori Facet écrit `xmp:Label = Yellow`, que Lightroom affiche comme le **libellé de couleur Jaune**, pas comme un Pick. Pour obtenir des Picks, utilisez le module externe ci-dessous ou filtrez sur le libellé Jaune.

`python facet.py --export-manifest` écrit les données de Facet sans XMP : chemin, catégorie, tous les scores, tags et les mêmes colonnes de note que `--export-sidecars`. Utilisez `--export-manifest --user alice` pour les notes par utilisateur. Voir [Commandes — Aperçu et export](COMMANDS.md#aperçu-et-export). Le module externe Facet ci-dessous le lit.

**Manifeste version 2** : ajoute `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` et un compteur `pending_corrections` de haut niveau. Ce compteur est le nombre de corrections manuelles de bracket/panorama pas encore appliquées ; relancez `--detect-panoramas` pour les appliquer. Le module l'affiche comme avertissement dans son Preview. Un module en version 2 refuse un manifeste en version 1 (et inversement) ; relancez `--export-manifest` si vous voyez cette boîte de dialogue.

Dans le visualiseur, la boîte de dialogue **Export to editor** de la galerie propose un bouton **Download Lightroom manifest** pour la même sélection ou le même filtre — voir [Editor Export](VIEWER.md#export-vers-éditeur). Il produit le même `facet_manifest.json` que `--export-manifest`.

### Le module externe Facet (notes, drapeaux Pick, champs de métadonnées et mots-clés)

`facet.lrplugin/`, dans le dépôt Facet, est un module externe (plug-in) Lightroom Classic. Il écrit la note en étoiles et l'état favori/rejeté de Facet **directement dans le catalogue**. Cela règle deux problèmes que le XMP ne peut pas résoudre : Lightroom ne trouve jamais un sidecar Facet pour un RAW propriétaire, et le XMP ne peut pas porter le drapeau Pick de Lightroom.

Le module lit un fichier manifeste. Il ne contacte jamais le serveur Facet, ne demande aucun mot de passe et fonctionne alors que Facet est arrêté. Il apparie les photos par chemin, donc **une bibliothèque 100 % RAW fonctionne comme une bibliothèque JPEG**.

Il ajoute deux éléments de menu à **Bibliothèque → Extras du module externe** (**Library → Plug-in Extras**) :

- **Facet: Apply ratings and flags...** — manifeste → catalogue (cette section).
- **Facet: Export Lightroom State to Facet...** — catalogue → Facet, voir [Lightroom → Facet](#lightroom--facet).

**Installation** (une seule fois) :

1. Copiez le dossier `facet.lrplugin` sur la machine qui exécute Lightroom. Sur macOS, compressez-le d'abord en zip : le Finder traite un dossier `.lrplugin` comme un paquet.
2. Dans Lightroom Classic : **Fichier → Gestionnaire de modules externes → Ajouter**, sélectionnez le dossier `facet.lrplugin`, puis **Terminé**.

**Utilisation** :

1. `python facet.py --export-manifest /photos/2026-wedding` (le chemin restreint la portée ; le fichier est toujours `facet_manifest.json` dans le répertoire courant). Copiez-le sur la machine Lightroom si nécessaire.
2. Dans le module Bibliothèque, sélectionnez les photos, puis **Bibliothèque → Extras du module externe → Facet: Apply ratings and flags...**
3. Indiquez le fichier `facet_manifest.json`. Le chemin est mémorisé.
4. **Si Facet a analysé les photos sur une autre machine, renseignez les deux préfixes de chemin.** Le manifeste contient les chemins de la machine d'analyse (p. ex. `/volume1/photos/...` sur un NAS) ; Lightroom contient ceux du poste de travail (p. ex. `Z:\photos\...`). Saisissez le préfixe Lightroom et le préfixe Facet qui désignent le même dossier. Laissez les deux vides si les chemins coïncident. S'ils sont faux, aucune photo ne correspond.
5. Choisissez la portée : les photos sélectionnées (par défaut) ou tout le dossier courant.
6. Cliquez sur **Preview...**. **Rien n'est encore écrit.** Le module indique combien de photos correspondent, combien ne correspondent pas, et ce qu'il définirait. Si rien ne correspond, il affiche un exemple de chemin Lightroom à côté d'un exemple de chemin du manifeste pour que vous puissiez corriger les préfixes.
7. Cliquez sur **Apply**. Vous pouvez annuler pendant la progression. Un résumé indique ce qui a été défini, ignoré et non trouvé.

**Ce qu'il écrit** (jamais dans vos fichiers image) :

| État Facet | Champ Lightroom |
|---|---|
| `star_rating` 1-5 | note en étoiles |
| favori | drapeau Pick |
| rejeté | drapeau Reject |

Une note Facet de 0 signifie « pas d'avis » et n'est jamais écrite.

**Règle d'écrasement.** Par défaut, le module ne pose une note que sur une photo *non notée* dans Lightroom, et un drapeau que sur une photo *sans drapeau*. Vos propres notes et drapeaux sont conservés et comptés comme « kept as they are ». Cochez **Overwrite ratings and flags that are already set in Lightroom** pour les remplacer. L'export de sidecars suit la même règle (`xmp_export.score_to_rating.only_when_unrated`, `true` par défaut).

**Options de la boîte de dialogue** (toutes désactivées par défaut, mémorisées d'une exécution à l'autre) :

- **Fill in star ratings from Facet scores for photos you have not rated** — si le manifeste n'a pas de `star_rating` (ou s'il vaut 0), le score `aggregate` est converti en étoiles. Ce secours **n'écrase jamais une note Lightroom existante, même avec Overwrite cochée.**
- **Pick the recommended frame of each burst** — dans chaque groupe de rafale d'au moins 2 membres, chaque membre marqué `is_burst_lead` est mis en Pick (une rafale peut en garder plusieurs). Les images isolées et les groupes sans leader sont ignorés. Vos propres drapeaux Pick/Reject et les favoris/rejets Facet l'emportent toujours.
- **Reject the other frames** (uniquement avec l'option Pick) — rejette chaque membre de rafale qui n'est pas leader. Les membres d'un bracket, d'un panorama ou d'un panorama HDR ne sont jamais rejetés, et les groupes sans leader n'obtiennent aucun rejet.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — pour chaque groupe d'au moins 2 photos appariées dans la portée, crée ou réutilise une collection sous `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` ou `Facet › HDR panoramas`.
  - Nom : `<yyyy-mm-dd HH:MM:SS> – <filename>` du membre le plus ancien, ou `~ (no date) – <filename>` s'il n'a pas d'heure de prise de vue.
  - Une rafale dont tous les membres appartiennent à un même ensemble bracket ou panorama n'obtient pas de collection Bursts séparée.
  - **Relancer n'ajoute que des photos.** Une photo qui quitte plus tard un ensemble reste dans sa collection.
  - Limite connue : deux groupes dont les membres les plus anciens partagent la même seconde de prise de vue et le même nom de fichier (p. ex. deux appareils écrivant `IMG_0001`) partagent une seule collection.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (uniquement avec l'option ci-dessus) — vide et remplit une collection, mais seulement quand la collection et tout son groupe sont dans la portée courante. Les collections partiellement couvertes et les collections intelligentes sont ignorées.
    - Elle vide aussi et supprime la collection d'un groupe dissous pendant ce lancement, mais seulement si chaque photo qu'elle contient a été appariée par ce lancement.
    - Elle ne touche que les collections dont le nom a le format propre à Facet (une date-heure ou `~ (no date)`, puis ` – <filename>`). Les collections que vous avez nommées vous-même ne sont jamais touchées.
    - Le Preview affiche une ligne `Facet collections to delete: N` quand il y a quelque chose à supprimer. Le résumé indique les collections reconstruites, supprimées, ignorées et en échec.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — écrit le score agrégé (p. ex. `8.4`), une bande entière (`0`-`10`), la catégorie et le type d'ensemble dans les champs de métadonnées propres à Facet. Ils apparaissent dans le panneau Métadonnées et servent de critères texte (`sdktext:`) dans le filtre de bibliothèque et les collections intelligentes, p. ex. la bande « n'importe lequel parmi 8, 9, 10 ». Un champ qui ne s'applique plus est effacé. Deux champs de suivi cachés (la note et le pick dérivés par ce lancement) sont aussi écrits ; ils sont exclus de la recherche mais peuvent rester visibles dans certaines versions de Lightroom Classic (non vérifié).
- **Create "Facet" keywords from Facet tags (never included on export)** — crée un mot-clé racine `Facet` avec un enfant par tag (tags IA et [tags manuels](#tags-manuels-et-mots-clés-xmp)). Les enfants `Facet ›` de chaque photo sont alignés sur ses tags : un tag retiré dans Facet disparaît donc à l'Apply suivant. `Include on Export` est désactivé pour tous, si bien qu'ils ne fuient jamais dans des exports ou des galeries client. Vos mots-clés hors de la racine `Facet` ne sont jamais modifiés. Un mot-clé `Facet` de premier niveau existant est adopté comme racine, et tout enfant que vous y avez ajouté vous-même est supprimé.

**Pourquoi des collections, et non des piles.** Le SDK de Lightroom ne sait pas créer de piles. Pour empiler les photos d'une collection, sélectionnez-les et utilisez **Photo → Empilement → Grouper en pile** (Ctrl/Cmd+G).

**Limites :**

- **Les drapeaux Pick restent dans le catalogue.** Lightroom ne les écrit jamais dans le XMP : aucune autre application ne les voit, et reconstruire le catalogue à partir des fichiers les perd. Les notes en étoiles survivent via **Métadonnées → Enregistrer les métadonnées dans le fichier**.
- **Pas de collections intelligentes numériques sur les champs Facet.** Les champs du module sont en texte seul (`sdktext:`) ; les opérateurs numériques (`>`, `<`, « compris entre ») ne fonctionnent que sur les champs intégrés de Lightroom. Utilisez le champ de bande, ou l'option de remplissage des étoiles, que Lightroom trie et filtre numériquement.
- **L'annulation** ne revient que sur un lot de 200 photos par Ctrl/Cmd+Z.
- Cochez **Write facet-apply.log next to the manifest** pour journaliser quels chemins ont correspondu et ce qui a été écrit.

### Lightroom → Facet

**Notes, picks et rejets — Lightroom gagne (via le module externe).**

1. **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** ouvre un panneau d'enregistrement. Le fichier contient un enregistrement par photo : `path`, plus `rating`/`pick` quand ils doivent voyager.
2. Importez-le avec `python facet.py --import-lightroom facet_lightroom_state.json` (`--user alice` est obligatoire sur une installation multi-utilisateur), ou avec **Import Lightroom state…** dans la boîte de dialogue **Export to editor** de la galerie.

La valeur de Lightroom l'emporte pour chaque champ d'un enregistrement. L'import rapporte les compteurs `matched`/`unmatched`/`changed`.

| État Lightroom | Résultat Facet |
|---|---|
| Drapeau Pick = Picked (`pick = 1`) | favori activé, rejet désactivé |
| Drapeau Pick = Rejected (`pick = -1`) | favori désactivé, rejet activé |
| Drapeau Pick = aucun (`pick = 0`) | favori désactivé, rejet désactivé |
| note en étoiles (`rating`, 0-5) | `star_rating` (`0` l'efface) |

- Un enregistrement sans `rating` ni `pick` laisse intacte la valeur Facet correspondante. L'export n'inclut un champ que si la valeur de Lightroom diffère de celle définie par le dernier Apply : une photo non touchée ne change donc rien.
- Les copies virtuelles sont fusionnées dans leur original avant l'export.
- Un import réussi qui modifie quelque chose rafraîchit les paires d'entraînement et arme le réentraînement automatique, comme tout changement de note.

> **Avertissement :** Comme Lightroom gagne, une photo que l'étape Apply n'a jamais touchée et qui est non notée et sans drapeau dans Lightroom (`pick = 0`, pas de `rating`) efface à l'import sa note en étoiles, son favori et son rejet dans Facet.

**Notes, libellés et mots-clés via XMP** (à sens unique) :

1. Dans Lightroom, sélectionnez les photos et choisissez **Métadonnées → Enregistrer les métadonnées dans le fichier** (Ctrl/Cmd+S). Cela écrit la note, le libellé et les mots-clés dans le sidecar XMP (RAW) ou dans le fichier (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` lit les sidecars RAW. Les noms de base RAW/JPEG partagés sont refusés. Cette commande ne lit pas les métadonnées intégrées. Les mots-clés importés deviennent des tags manuels.

### Règles de conflit

- **Les tags et mots-clés fusionnent par défaut.** Les exports ajoutent les mots-clés Facet ; `--reconcile-keywords` retire aussi les noms obsolètes appartenant à Facet. Les imports ajoutent des tags manuels sans jamais remplacer les tags IA. Voir [Tags manuels et mots-clés XMP](#tags-manuels-et-mots-clés-xmp).
- **Multi-utilisateurs** (`--export-sidecars --user alice` / `--import-sidecars --user alice`) : les notes vont dans les notes propres à Alice (`user_preferences`) plutôt que dans les notes globales. Les mots-clés sont toujours globaux : les tags manuels sont partagés.
- Les mots-clés importés sont stockés dans `photo_manual_tags`, que les filtres de tags lisent directement. `python database.py --migrate-tags` n'est pas nécessaire après `--import-sidecars`.

## Capture One

Capture One conserve ses réglages dans des fichiers `.cos` (Sessions) ou dans son catalogue. Son mode « Full Sync » de **Sync Metadata** peut écraser le côté ayant écrit en dernier : une boucle bidirectionnelle peut donc perdre des modifications. Utilisez le **sens unique, Facet → Capture One** :

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. Dans Capture One, laissez **Preferences → General → Sync Metadata** à sa valeur par défaut (pas « Full Sync »).
3. Sélectionnez les images, faites un clic droit et choisissez **Load Metadata** pour faire entrer une fois la note, le libellé et les mots-clés.

Poursuivez ensuite dans Capture One sans synchronisation automatique. Pour ramener dans Facet le XMP enregistré, lancez `--import-sidecars /path/to/shoot --sidecar-naming basename` pour les sidecars RAW à extension retirée, ou `full` pour les noms complets. Les noms de base RAW/JPEG partagés sont refusés. Cette commande lit les sidecars, pas les métadonnées intégrées.

## digiKam

Les [réglages de sidecars de digiKam](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) utilisent un seul nommage : `filename.ext.xmp` par défaut, ou `filename.xmp` avec **Sidecar file names are compatible with commercial programs** activé. digiKam n'essaie pas les deux.

- **Facet → digiKam :** utilisez le réglage de nom complet, activez **Read from sidecar files**, relisez les métadonnées des fichiers et vérifiez les champs.
- **digiKam → Facet :** passez `--sidecar-naming full` ou `basename` selon votre réglage digiKam.

Étoiles, libellés de couleur et drapeaux de sélection ont des sens légèrement différents d'une application à l'autre : vérifiez le résultat.

### Point d'ancrage Batch Queue Manager

Vous pouvez lancer un import Facet depuis l'outil **Custom Script** du Batch Queue Manager (BQM) de digiKam. Activez d'abord l'écriture des sidecars, enregistrez le réglage de nommage et appliquez les modifications de métadonnées en attente (digiKam peut différer les écritures). Cet exemple suppose des sidecars à nom complet ; n'utilisez `basename` que pour une collection sans nom de base partagé :

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sont les substitutions par fichier de digiKam. BQM attend un fichier de sortie, d'où le `cp`. `--import-sidecars` parcourt tout le dossier : l'exécuter une fois par photo est redondant mais inoffensif. Pour les gros lots, exécutez `python facet.py --import-sidecars /path/to/folder` une seule fois après la fin de la file.

## darktable

Voir [Configuration — Visionneuse](CONFIGURATION.md#visionneuse) (profils et styles d'export `viewer.raw_processor.darktable`) et [Visionneuse — Téléchargement](VIEWER.md#points-daccès-api) (conversions `type=darktable`).

darktable stocke son historique de retouches dans son propre `<image><ext>.xmp`. L'écriveur ExifTool de Facet fusionne dans ce fichier et conserve les nœuds `darktable:history` et de masques. Le comportement de sidecar décrit plus haut pour Lightroom (export/import, le plus récent gagne, union des tags) s'applique tel quel, et il n'y a aucune incohérence de nommage RAW : les deux utilisent `<image><ext>.xmp`.

**Version d'ExifTool :**

- **13.28 ou plus récente** est recommandée.
- Les modifications de visages nécessitent **12.65 ou plus récente**. Les versions plus anciennes ou inconnues ignorent les changements de visages avec un avertissement et exportent le reste.
- **13.23 à 13.27** corrompent les sidecars qui contiennent l'historique de darktable : Facet refuse donc d'écrire avec elles et demande une mise à jour. L'image Docker fige une version sûre. Les paquets de distribution peuvent ne pas l'être (le `libimage-exiftool-perl` de Debian trixie est en 13.25).

> **Avertissement :** darktable lui-même peut effacer l'historique de retouches en réimportant une image déjà retouchée : il peut écraser l'historique du sidecar par un historique vierge. C'est un bug amont ouvert ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), signalé le 2026-03-15), et la préférence « check for new/updated xmp files on start » ne l'empêche pas. Après `--export-sidecars`, ne réimportez pas en bloc un dossier déjà retouché. Rechargez seulement les images que Facet a touchées et vérifiez d'abord leur historique.

## Tags manuels et mots-clés XMP

Facet conserve les tags que vous saisissez (voir [Visionneuse — Tags manuels](VIEWER.md#tags-manuels)) dans `photo_manual_tags`, séparément des tags IA de `photos.tags`. Une nouvelle analyse ou un re-tagging ne les touche jamais.

- **Export.** Chaque écrivain de mots-clés émet les tags IA, puis les tags manuels, puis les noms de personnes, dédoublonnés sans tenir compte de la casse. Cela couvre `--export-sidecars`, les actions d'export XMP et « Écrire les métadonnées dans le fichier » de la galerie, et le manifeste Lightroom (`--export-manifest`, `/api/lightroom/manifest`).
- **Import.** `--import-sidecars` lit les mots-clés à plat dans `dc:subject` et les chemins hiérarchiques séparément dans `lr:hierarchicalSubject`. Les mots-clés à plat sont normalisés comme des tags saisis : espaces retirés, minuscules, 64 caractères au plus, 50 tags manuels par photo. Chacun devient un tag manuel avec la source `xmp`, sauf s'il :
  - fait déjà partie des tags IA ou des noms de personnes de la photo,
  - reproduit un chemin explicitement présent dans `lr:hierarchicalSubject`,
  - contient une virgule ou un caractère de contrôle, ou
  - dépasserait le plafond.
- **La suppression de mots-clés est explicite.** Les exports ne font qu'ajouter par défaut. `--export-sidecars /path --reconcile-keywords` (nécessite ExifTool) retire aussi les noms que Facet a écrits plus tôt et qui ne sont plus dans Facet. Les mots-clés que Facet n'a jamais écrits ne sont jamais retirés, même si le nom correspond, et les anciens sidecars sans marqueur n'accordent aucune propriété à Facet. Si vous réajoutez un mot-clé retiré dans un autre éditeur, Facet peut le réimporter et le traite ensuite comme étranger. Les mots-clés restent partagés, même avec `--user`.
- **Les mots-clés de Facet l'emportent à l'export.** Un mot-clé toujours présent dans Facet est réécrit même si un autre éditeur l'a retiré du fichier. Pour le supprimer définitivement, retirez le tag dans Facet. La réconciliation ne supprime jamais de tags de Facet.
- Les noms comme `2024`, `1.50`, `1e3`, `true`, `false` et `null` gardent leur orthographe.
- Si Facet ne peut pas lire les métadonnées d'un fichier existant, l'export s'arrête avant d'écrire.
- **Le manifeste Lightroom, lui, répercute les suppressions.** L'option de mots-clés du module réécrit les enfants `Facet ›` de chaque photo à chaque Apply.
- **Les tags IA restent des tags IA.** Les sidecars enregistrent quels mots-clés étaient IA et lesquels manuels : un re-tagging ne transforme donc pas un ancien mot-clé IA en tag manuel. Les sidecars d'anciennes versions de Facet gardent l'ancien comportement additif.
- **Hiérarchies.** Les chemins importés sont ajoutés à la hiérarchie partagée ; un nom à plat contenant `|` ou `/` ne crée pas à lui seul de hiérarchie. Les chemins marqués comme générés par Facet ne sont pas importés comme affectations manuelles, sauf s’ils sont aussi marqués manuels. Les exports incluent les affectations explicites et les chemins de catégorie/personne générés. L’export est additif par défaut ; `--reconcile-keywords` retire uniquement les chemins obsolètes appartenant à Facet et préserve les chemins étrangers.
- **Limites de propriété :** 10 000 noms par liste et 1 024 caractères par nom. Un export qui les dépasserait s'arrête avant d'écrire. Archivez et nettoyez un tel sidecar à la main avant de repartir de zéro.
- **Les mots-clés importés par une ancienne version de Facet restent où ils sont.** Les anciennes versions fusionnaient les mots-clés dans `photos.tags`, où ils ressemblent à des tags IA, et rien ne les migre. Pour en convertir un en tag manuel, videz ou re-taguez `photos.tags`, puis relancez `--import-sidecars` — ou ajoutez le tag à la main.
- **Fichiers déplacés ou renommés.** Les tags manuels sont liés au chemin du catalogue. Après avoir déplacé les fichiers vous-même, utilisez la [procédure de réassociation](RELINK.md) avec examen préalable pour mettre à jour ce chemin et conserver les tags ; scanner le nouvel emplacement seul ne les transfère pas.
- **`--export-csv` et `--export-json` restent limités à l'IA.** Leur valeur `tags` ne contient aucun tag manuel.

## Comment Facet fusionne

| Champ | Facet écrit | Facet relit | Règle de conflit |
|---|---|---|---|
| Note (étoiles / rejet) | `xmp:Rating` (`-1` = rejeté) | `xmp:Rating` | Horloges de revue suivies ; repli historique du scan |
| Libellé de couleur | `xmp:Label` (`Red` = rejeté, `Yellow` = favori) | `xmp:Label` | Horloges de revue suivies ; repli historique du scan |
| Tags / mots-clés | `dc:subject` (à plat, tags IA + tags manuels, inclut les noms des personnes identifiées) | `dc:subject` (stockés comme tags manuels) | Additif par défaut ; `--reconcile-keywords` retire seulement les noms obsolètes de Facet ; les imports restent additifs ([Tags manuels et mots-clés XMP](#tags-manuels-et-mots-clés-xmp)) |
| Tags hiérarchiques | `lr:hierarchicalSubject` (affectations explicites et chemins de catégorie/personne générés) | `lr:hierarchicalSubject` (affectations à la hiérarchie partagée) | Import additif ; la réconciliation à l’export retire uniquement les chemins obsolètes de Facet |
| Légende | `dc:description` langue par défaut (+ `IPTC:Caption-Abstract` via exiftool) | Non réimporté | Export uniquement |
| Zones de visage nommées | `mwg-rs:RegionList` MWG + `facet:RegionOwner=Facet` (centrée-normalisée, `Type=Face`) | Non réimporté | Export uniquement ; lu nativement par digiKam, **pas** lu par Lightroom (une limitation Adobe connue — Lightroom ne consomme que les zones MWG qu'il a lui-même écrites) |

Voir [Commandes — Aperçu et export](COMMANDS.md#aperçu-et-export) pour la référence CLI complète (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

**Effacements GPS.** Si un sidecar contient à la fois les champs GPS standard et un ancien `facet:GPSState=cleared`, une paire latitude/longitude complète et valide l'emporte. Une paire partielle ou invalide est ignorée et n'efface jamais une position. Seule une paire absente ou vide accompagnée du marqueur d'effacement efface le GPS. Le GPS manuel reste protégé sauf si vous demandez de l'écraser.

**Légendes.** Avec ExifTool, l'export ne met à jour que la langue par défaut (`x-default`) de `dc:description` et conserve les autres langues. Une légende Facet vide laisse intactes les légendes existantes. Sans ExifTool, Facet écrit une légende en langue par défaut et, lorsqu'un sidecar d'éditeur existe, écrit plutôt dans `<image>.facet.xmp`.

**Régions de visages.** Avec ExifTool, l'export ne remplace que les rectangles MWG marqués `facet:RegionOwner=Facet`.

- Les régions non marquées, y compris celles des anciennes versions de Facet, sont conservées. Après une mise à jour, un ancien visage non marqué et sa nouvelle copie marquée peuvent apparaître ensemble, et effacer les visages laisse l'ancien.
- Les exports répétés remplacent les copies marquées ; elles ne s'accumulent pas.
- Si les dimensions de l'image diffèrent de celles sur lesquelles les régions existantes ont été dessinées (ou sont inconnues), les changements de visages sont ignorés avec un avertissement. Note, libellé, mots-clés et GPS sont néanmoins exportés.
- Des métadonnées de visages illisibles ou invalides arrêtent l'export ou l'intégration d'une photo avant d'écrire.
- L'écriveur de repli (sans ExifTool) n'exporte aucun rectangle de visage.
- Une région marquée que vous modifiez ailleurs reste gérée par Facet. Retirez son marqueur de propriété pour la conserver comme la vôtre.

> **Avertissement :** Les écritures dans des fichiers séparés ne sont pas atomiques. Une erreur d'E/S ou une modification externe pendant l'export peut laisser certains fichiers à jour et d'autres non.

Si la vérification de version d'ExifTool échoue, Facet la retente la fois suivante. Tant que la version est inconnue, les régions de visages sont ignorées et le reste est exporté. Les versions défectueuses connues sont toujours refusées.

## Prévisualiser les imports et les conflits

Lancez `--import-sidecars /path --dry-run` pour voir le plan JSON avant d'écrire : le sidecar choisi, les champs avant/après, les mots-clés à ajouter, la date de la source et les motifs d'ignorance ou de conflit. L'aperçu ouvre la base en lecture seule et ne la modifie jamais. L'application relit tout, donc l'aperçu n'est pas un jeton à rejouer.

Si la base est absente, illisible ou invalide, l'aperçu se termine avec le code 1 et ne la crée ni ne la répare. `--dry-run-count` limite uniquement les échantillons de scan, pas les aperçus d'import.

`--sidecar-fields review,gps,keywords` sélectionne les groupes à importer ; omettez un groupe pour l'ignorer.

- **review** importe ensemble étoiles, favori, rejet et Garder, pour qu'un conflit n'applique jamais une demi-décision.
- **gps** conserve les positions manuelles sauf si `--overwrite-manual-gps` est donné.
- **keywords** sont additifs et partagés, même avec `--user`.

**Horloges de modification.** Facet enregistre quand chaque champ de revue a été modifié pour la dernière fois, par photo et par compte, remises à zéro comprises. Un sidecar plus ancien que cette modification est un conflit `newer_local_edit`, et ce groupe de revue reste inchangé. `--overwrite-sidecar-review` force le remplacement, ainsi que la vérification de date du scan. Une source `local` désigne un écrivain inconnu, pas forcément une personne. Les légendes, visages et le GPS externe non marqué ne sont jamais importés.

- Les champs modifiés avant que Facet ne commence à enregistrer les modifications n'ont pas de date de modification connue. La règle de la date du scan s'applique, signalée comme `untracked_legacy_edit`.
- L'aperçu ouvre aussi les anciennes bases sans les mettre à niveau ; un champ Garder absent se lit comme indécis.
- La date du sidecar est `xmp:MetadataDate`, ou la date de modification du fichier si elle est absente ou invalide.
- Le détail liste les 1 000 premières photos de la portée et 100 notes par photo, avec le compte de ce qui a été omis.

Les horloges de modification restent dans leur propre base. Un nouvel export du visualiseur ne copie ni horloges de modification du scanner ni chemins de sidecars. Un export incrémental conserve les horloges propres au visualiseur : les remises à zéro faites dans le visualiseur (y compris les notes par utilisateur supprimées) survivent donc. Les valeurs du scanner que le visualiseur n'a jamais modifiées continuent de se mettre à jour.

> **Avertissement :** Une base de visualiseur construite par une version non publiée antérieure à 1.24.0 peut contenir des horloges du scanner copiées. Elles comptent désormais comme des modifications du visualiseur : ces champs cessent donc de suivre les mises à jour du scanner. Sauvegardez et examinez cette base avant de la reconstruire : une reconstruction complète ne conserve pas les modifications locales du visualiseur.
