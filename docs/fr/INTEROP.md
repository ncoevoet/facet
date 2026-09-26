# Recettes d'interopérabilité avec les éditeurs

> 🌐 [English](../INTEROP.md) · **Français** · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · [简体中文](../zh/INTEROP.md)

Recettes pratiques, étape par étape, pour faire circuler dans les deux sens les notes, libellés et tags de Facet avec les éditeurs externes et les outils de gestion de photothèque que les photographes utilisent réellement. Cette page suppose que vous savez déjà *que* Facet écrit du XMP — voir [Commandes — Aperçu et export](COMMANDS.md#preview--export) pour la référence complète des options `--export-sidecars` / `--import-sidecars` et la correspondance des champs (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## Le piège du nommage des sidecars RAW

Facet nomme un sidecar `<image><ext>.xmp` — par exemple `IMG_1234.CR2.xmp` à côté de `IMG_1234.CR2` — la même convention qu'utilisent darktable et digiKam. **Lightroom Classic et Capture One attendent l'inverse : `IMG_1234.xmp`, extension RAW retirée.** Aucun des deux ne détectera un sidecar écrit par Facet pour un fichier RAW propriétaire (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — tout sauf le DNG), et le `--import-sidecars` de Facet ne trouvera pas non plus un sidecar écrit par une application de l'écosystème Adobe pour ce même RAW. Il s'agit d'une incompatibilité de nommage entre écosystèmes, pas d'un bug de l'un ou l'autre côté.

Cela n'affecte **pas** :
- **JPEG, HEIC, TIFF, PNG, DNG** — passez `--embed-originals` et Facet écrit les métadonnées *directement dans le fichier* (via exiftool), donc il n'y a aucun nom de sidecar que Lightroom/Capture One pourrait manquer.
- **digiKam** — vérifie les deux conventions de nommage et trouve le sidecar de Facet dans tous les cas (voir [digiKam](#digikam) plus bas).
- **darktable** — utilise la même convention `<image><ext>.xmp` que Facet (voir [darktable](#darktable) plus bas).

**Le GIF, le WebP, le BMP et l'AVIF sont l'exception — ce sont eux que la discordance touche le plus.** Ils sont hors de l'ensemble embarquable de Facet : `--embed-originals` ne fait rien pour eux et leur seul véhicule d'aller-retour est un sidecar XMP portant le nommage de Facet (`photo.webp.xmp`). La discordance ci-dessus s'applique donc à ces quatre formats exactement comme au RAW propriétaire : digiKam et darktable trouvent le sidecar, Lightroom Classic et Capture One non.

Donc, pour un flux Lightroom ou Capture One : utilisez `--embed-originals` pour tout ce qui fait partie de l'ensemble embarquable (JPEG, HEIC, TIFF, PNG, DNG), et attendez-vous à ce que l'aller-retour par sidecar reste silencieux (pas d'erreur, simplement rien lu) pour les RAW propriétaires — ainsi que pour le GIF, le WebP, le BMP et l'AVIF. Si vous shootez en RAW+JPEG, le JPEG compagnon est le véhicule d'interopérabilité pratique — le RAW reste sur le disque, intact, tandis que la base de données de Facet conserve la note qui fait autorité.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (ajoutez un chemin pour restreindre la portée, par exemple `--export-sidecars /photos/mariage-2026`). Ajoutez `--embed-originals` pour aussi écrire directement dans les fichiers JPEG/HEIC/TIFF/PNG/DNG.
2. Dans le module Bibliothèque de Lightroom Classic, sélectionnez les photos (Ctrl/Cmd+A pour tout sélectionner) et choisissez **Métadonnées → Lire les métadonnées du fichier**. Lightroom écrase la note, le libellé de couleur et les mots-clés de son catalogue à partir du sidecar (ou des métadonnées intégrées, pour les formats ci-dessus).

Le marqueur de rejet de Facet (`xmp:Rating = -1`) est relu comme le drapeau Rejeter de Lightroom. Un favori Facet écrit `xmp:Label = Yellow`, que Lightroom affiche comme le **libellé de couleur Jaune** — pas le drapeau Sélectionner (Pick). Si votre flux Lightroom se base sur les drapeaux Pick plutôt que sur les libellés de couleur, ajoutez une étape de conversion libellé-couleur → pick, ou filtrez plutôt sur le libellé Jaune.

Un flux `python facet.py --export-manifest` (chemin, catégorie, tous les scores, tags, et les mêmes colonnes de note que `--export-sidecars` — y compris les notes par utilisateur via `--export-manifest --user alice` sur une installation multi-utilisateurs) existe désormais pour les outils qui veulent les données de Facet sans analyser le XMP — voir [Commandes — Aperçu et export](COMMANDS.md#preview--export). C'est ce flux que consomme le module externe Facet décrit ci-dessous.

**Manifeste version 2.** Le manifeste porte désormais aussi `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` et un compteur `pending_corrections` de haut niveau (corrections manuelles bracket/panorama pas encore appliquées par une exécution de détection — relancez `--detect-panoramas`). Le module externe utilise les champs par photo pour les options de sélection/rejet de rafale et de secours des étoiles ci-dessous, et affiche `pending_corrections` comme avertissement dans son Preview pour que vous sachiez qu'une nouvelle détection peut encore changer quelles images sont leaders. Il n'y a pas de chemin de lecture rétrocompatible : un module compilé pour la version 2 refuse purement et simplement un manifeste en version 1, avec une boîte de dialogue vous demandant de le réexporter, et un module plus ancien ne peut pas lire un manifeste en version 2. Si vous voyez cette boîte de dialogue, relancez simplement `--export-manifest`.

Dans le viewer, la boîte de dialogue **Export to editor** de la galerie propose le même manifeste via un bouton **Download Lightroom manifest**, portant sur la même sélection/le même filtre que l'export de sidecars situé juste à côté — voir [Editor Export](VIEWER.md#export-vers-éditeur). Il écrit exactement le même `facet_manifest.json` que `--export-manifest`, si bien que la boîte de dialogue du module ci-dessous fonctionne de la même façon quel que soit le côté qui a généré le fichier.

### Le module externe Facet (notes, drapeaux Pick, champs de métadonnées et mots-clés)

`facet.lrplugin/`, dans le dépôt Facet, est un module externe (plug-in) Lightroom Classic qui écrit la note en étoiles et l'état favori/rejeté de Facet **directement dans le catalogue**. Il existe parce que deux choses évoquées plus haut sont impossibles à corriger côté XMP : Lightroom ne trouve jamais un sidecar Facet pour un fichier RAW propriétaire, et le XMP n'a aucun canal pour le drapeau Sélectionner (Pick) de Lightroom. Le module lit un fichier manifeste : il ne parle jamais au serveur Facet, ne demande aucun mot de passe et fonctionne alors que Facet est arrêté — et comme il apparie les photos par chemin plutôt que par sidecar, **une bibliothèque 100 % RAW fonctionne exactement comme une bibliothèque JPEG**.

Le module enregistre deux éléments de menu dans **Bibliothèque → Extras du module externe** (**Library → Plug-in Extras**) : **Facet: Apply ratings and flags...** (le sens manifeste → catalogue, décrit dans cette section) et **Facet: Export Lightroom State to Facet...** (le sens inverse — voir [Lightroom → Facet](#lightroom--facet) ci-dessous).

**Installation** (une seule fois) :

1. Copiez le dossier `facet.lrplugin` sur la machine qui exécute Lightroom. Sur macOS, compressez-le d'abord en zip — le Finder traite un dossier `.lrplugin` comme un paquet.
2. Dans Lightroom Classic : **Fichier → Gestionnaire de modules externes → Ajouter**, sélectionnez le dossier `facet.lrplugin`, puis **Terminé**.

**Utilisation** (à chaque fois que vous voulez le verdict de Facet dans le catalogue) :

1. `python facet.py --export-manifest /photos/mariage-2026` (le chemin restreint la portée ; le fichier est toujours écrit sous le nom `facet_manifest.json` dans le répertoire courant). Copiez-le sur la machine Lightroom si Facet tourne ailleurs.
2. Dans le module Bibliothèque, sélectionnez les photos, puis **Bibliothèque → Modules externes supplémentaires → Facet: Apply ratings and flags...** (l'interface du module externe est en anglais).
3. Indiquez le fichier `facet_manifest.json`. Le chemin est mémorisé pour la fois suivante.
4. **Si Facet a analysé les photos depuis une autre machine, renseignez les deux préfixes de chemin.** Le manifeste contient les chemins de la machine qui a fait l'analyse (`/volume1/photos/...` sur un NAS), alors que Lightroom connaît ceux du poste de travail (`Z:\photos\...`). Saisissez le préfixe Lightroom et le préfixe Facet qui désignent le même dossier ; laissez les deux vides quand ils coïncident. C'est la seule erreur de premier lancement qui compte vraiment — elle ne fait tout simplement correspondre aucune photo.
5. Choisissez la portée : les photos sélectionnées (par défaut) ou toutes les photos du dossier courant.
6. Cliquez sur **Preview...** (Aperçu). **Rien n'est encore écrit.** Le module indique combien de photos il a trouvées dans le manifeste, combien il n'a pas trouvées, et combien de notes et de drapeaux il écrirait. Si le nombre d'appariements est 0, il affiche un exemple de chemin Lightroom à côté d'un exemple de chemin du manifeste, pour que vous voyiez ce que doivent être les préfixes.
7. Cliquez sur **Apply** (Appliquer). La progression est affichée et annulable ; un dialogue de synthèse indique ce qui a été écrit, ignoré et non trouvé.

**Ce qu'il écrit** — rien d'autre, et jamais dans vos fichiers image :

| État Facet | Champ Lightroom |
|---|---|
| `star_rating` 1-5 | note en étoiles |
| favori | drapeau Sélectionner (Pick) |
| rejeté | drapeau Rejeter (Reject) |

Une note Facet à 0 signifie « pas d'avis » (voir `xmp_export.score_to_rating`) et n'est jamais écrite.

**Sémantique d'écrasement** — par défaut, le module ne vous contredit jamais : il pose une note uniquement si la photo est *non notée* dans Lightroom, et un drapeau uniquement si la photo est *sans drapeau*. Tout ce que vous avez noté ou marqué à la main est laissé tel quel et compté comme « kept as they are » (conservé tel quel) dans l'aperçu. Cochez **Overwrite ratings and flags that are already set in Lightroom** pour les remplacer malgré tout. Cela reflète `only_when_unrated` dans `xmp_export.score_to_rating` : le module externe et le chemin sidecar traitent donc vos retouches manuelles de la même façon.

**Nouvelles options de la boîte de dialogue** (toutes optionnelles, chacune mémorisée pour la prochaine fois) :

- **Fill in star ratings from Facet scores for photos you have not rated** — quand une photo n'a pas de `star_rating` dans le manifeste (ou qu'il est à 0) mais que le score `aggregate` de Facet correspond à un nombre d'étoiles, cette note dérivée comble le manque. Comme c'est un secours pour une photo *non notée*, et non une vraie note du manifeste, elle **n'écrase jamais une note déjà présente dans Lightroom — même avec Overwrite cochée.** Une véritable `star_rating` du manifeste suit toujours la règle d'écrasement normale ci-dessus, sans changement.
- **Pick the recommended frame of each burst** — pour chaque groupe de rafale comptant au moins 2 membres dans le manifeste, chaque membre que le manifeste marque `is_burst_lead` (une rafale peut garder plus d'une image) est mis en Sélectionné (Pick). Une image isolée que le manifeste n'a jamais regroupée avec des voisines n'est jamais touchée par cette option, et un groupe de rafale sans aucun membre `is_burst_lead` dans le manifeste est ignoré entièrement (rien à en tirer). Un drapeau Sélectionner/Rejeter posé à la main — ou un favori/rejet Facet dans le manifeste — l'emporte toujours sur cette sélection dérivée.
- **Reject the other frames** (imbriquée sous l'option précédente, activée seulement avec elle) — met chaque membre de rafale qui n'est *pas* le leader en Rejeté, avec deux exceptions : un membre d'un bracket, d'un panorama ou d'un panorama HDR n'est jamais rejeté par cette règle, même si son `burst_group_id` le regroupe aussi avec des voisines — ces ensembles sont conservés intégralement ; et un groupe sans aucun leader dans le manifeste (voir ci-dessus) n'obtient aucun rejet non plus.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — pour chaque groupe comptant au moins 2 photos appariées dans la portée actuelle, crée ou réutilise une collection nommée `<yyyy-mm-dd HH:MM:SS> – <filename>` (l'heure de prise de vue et le nom de fichier du membre le plus ancien ; `~ (no date) – <filename>` quand ce membre n'a pas d'heure de prise de vue), imbriquée sous `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` ou `Facet › HDR panoramas` selon le cas. Un groupe de rafale ordinaire dont tous les membres appartiennent déjà entièrement à un même ensemble bracket/panorama/panorama HDR n'obtient pas de collection Bursts séparée, puisque cela ferait doublon avec celle sous Brackets/Panoramas/HDR panoramas. **Relancer n'ajoute que** des photos à une collection qu'il retrouve — il n'en retire jamais, donc une collection peut devenir obsolète par rapport à un ensemble regroupé ou redétecté plus tard (une photo sortie d'un bracket à un scan ultérieur n'est pas retirée de la collection). Les noms de collection entrent aussi en collision quand les membres les plus anciens de deux groupes différents partagent la même heure de prise de vue à la seconde et le même nom de fichier — deux appareils ayant tous deux écrit `IMG_0001` au même instant finissent par partager une seule collection au lieu d'en obtenir une chacun. C'est une limite connue, pas un bug à signaler.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (imbriquée sous l'option précédente) — au lieu de seulement ajouter, vide et remplit une collection à neuf, mais seulement quand la collection ET tout son groupe sont entièrement dans la portée du lancement en cours ; une collection partiellement couverte (certains membres hors de la sélection) ou pointant vers une collection intelligente/non résolue est laissée intacte et comptée comme ignorée, et le résumé indique combien ont été reconstruites, supprimées, ignorées et échouées. Elle atteint aussi une collection Facet dont le groupe s'est DISSOUS pendant ce lancement (plus au moins 2 membres dans la portée, donc aucune entrée de plan) — cette collection est alors vidée puis supprimée, mais seulement quand chaque photo qu'elle contient a été retrouvée par ce lancement ; une collection contenant une seule photo hors de ce lancement est laissée intacte. Rebuild n'est proposée — et ne s'exécute — que si **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** est activée ; décocher cette option désactive aussi Rebuild. Le balayage des collections dissoutes ne touche que les collections dont le nom correspond exactement à la forme générée par Facet lui-même (une date-heure ISO, ou le préfixe non daté `~ (no date)`, suivi de ` – <filename>`), si bien qu'une collection que vous avez vous-même nommée sous un ensemble Facet n'est jamais vidée ni supprimée. Quand le balayage a quelque chose à supprimer, le Preview ajoute une ligne `Facet collections to delete: N`, et le balayage s'exécute même quand c'est le seul changement en attente, plutôt que d'être signalé comme rien à changer.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — écrit le score `aggregate` (p. ex. `8.4`), une bande entière (`0`-`10`), la catégorie et le type d'ensemble dans les propres champs de métadonnées du module Facet, visibles dans le panneau Métadonnées et utilisables comme critères texte (`sdktext:`) du filtre de bibliothèque ou d'une collection intelligente — par exemple une collection intelligente qui fait correspondre la bande sur « n'importe lequel parmi 8, 9, 10 ». Un champ qui ne s'applique plus à une photo (par exemple elle a quitté un bracket, donc le type d'ensemble a disparu) est effacé plutôt que laissé obsolète — sinon une collection intelligente ou un critère du filtre de bibliothèque basé sur ce champ continuerait de faire correspondre une photo qui n'y correspond plus. Le SDK d'Adobe n'admet les champs propres à un module dans le vocabulaire de recherche que comme texte ou énumération, jamais comme plage numérique ; il n'y a donc toujours pas de collection intelligente « aggregate > 8 » — la bande est le meilleur substitut texte disponible. Deux propriétés de suivi supplémentaires (la note/le pick que ce lancement a dérivés) sont écrites en même temps mais restent hors du filtre de bibliothèque et des critères de collection intelligente — voir la remarque sur l'export inverse sous [Lightroom → Facet](#lightroom--facet). **NON VÉRIFIÉ sur un catalogue réel :** qu'un champ de métadonnées sans titre soit vraiment invisible dans le panneau Métadonnées et le filtre de bibliothèque n'est pas confirmé par la seule documentation du SDK Lightroom ; les deux propriétés de suivi sont donc marquées `searchable = false, browsable = false`, le repli le plus sûr et confirmé plutôt qu'un comportement d'omission de titre non confirmé — elles pourraient rester visibles dans certaines versions de Lightroom Classic.
- **Create "Facet" keywords from Facet tags (never included on export)** — crée un mot-clé racine `Facet` avec un enfant par tag Facet porté par vos photos, et fait correspondre exactement les mots-clés enfants `Facet ›` de chaque photo à ses tags du manifeste (ajoute et retire au fil des changements de tags entre les lancements). Chaque mot-clé créé ou touché par cette option a `Include on Export` désactivé, si bien que les tags automatiques de Facet ne s'infiltrent jamais dans un export JPEG/TIFF ni dans une galerie client. Vos propres mots-clés hors de la racine `Facet` ne sont jamais lus, ajoutés ou retirés par cette option.

**Pourquoi des collections, et non des piles.** Le SDK de Lightroom n'a aucun appel pour créer ou gérer une pile (Stack) — `stackInFolder`/`stackPositionInFolder` sont en lecture seule sur `LrPhoto`. Une collection est le substitut inscriptible le plus proche, et `canReturnPrior` fait que relancer le module retrouve la même collection au lieu de la dupliquer. Si vous voulez une vraie pile Lightroom, sélectionnez les photos d'une collection et utilisez vous-même **Photo → Empilement → Grouper en pile** (Ctrl/Cmd+G) — le module ne peut pas faire cette étape pour vous.

**Limites**, en toute honnêteté :

- **Les drapeaux Pick n'existent que dans le catalogue.** C'est un choix de Lightroom, pas du module : Lightroom n'écrit jamais le drapeau Pick dans le XMP, il n'atteint donc aucune autre application et il est perdu si vous reconstruisez le catalogue à partir des fichiers. Les notes en étoiles, elles, survivent via **Métadonnées → Enregistrer les métadonnées dans le fichier**.
- **La collection dynamique par champ de métadonnées reste texte uniquement.** Le SDK d'Adobe n'admet les champs propres à un module externe dans le vocabulaire de recherche qu'en texte ou énumération (`sdktext:`) ; les opérateurs numériques (`>`, `<`, « compris entre ») restent réservés aux critères intégrés de Lightroom. Le champ « bande » ci-dessus est le meilleur substitut texte à « aggregate > 8 » ; faire passer le score brut par la **note en étoiles** (l'option de secours ci-dessus) reste le seul canal que Lightroom lui-même filtre et trie numériquement.
- **L'annulation** fonctionne par lot : le module écrit par blocs de 200 photos, donc Ctrl/Cmd+Z annule 200 photos à la fois.
- Cochez **Write facet-apply.log next to the manifest** avant un traitement si vous avez besoin de voir, ligne par ligne, quels chemins ont été appariés et ce qui a été écrit.

### Lightroom → Facet

**Notes, picks et rejets — Lightroom gagne (via le module externe).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** écrit `facet_lightroom_state.json` (un enregistrement par photo : `path`, et `rating`/`pick` seulement quand ils doivent encore voyager — voir ci-dessous) à côté du manifeste. Réinjectez-le avec `python facet.py --import-lightroom facet_lightroom_state.json` (ajoutez `--user alice` sur une installation multi-utilisateur ; obligatoire dans ce cas) ou, dans le viewer, le bouton **Import Lightroom state…** de la boîte de dialogue **Export to editor** de la galerie, qui envoie directement le contenu du fichier au serveur. La valeur de Lightroom gagne sans condition pour chaque clé présente dans un enregistrement — le CLI et le viewer partagent le même importeur `processing/lightroom_sync.py`, qui rapporte les compteurs `matched`/`unmatched`/`changed` :

| État Lightroom | Résultat Facet |
|---|---|
| Drapeau Pick = Sélectionné (`pick = 1`) | favori activé, rejet désactivé |
| Drapeau Pick = Rejeté (`pick = -1`) | favori désactivé, rejet activé |
| Drapeau Pick = aucun (`pick = 0`) | favori désactivé, rejet désactivé |
| note en étoiles (`rating`, 0-5) | `star_rating` (`0` l'efface) |

Un enregistrement qui omet `rating` ou `pick` laisse intacte la valeur correspondante de Facet — l'export n'inclut une clé que quand la valeur actuelle de Lightroom diffère de celle que le sens Apply avait lui-même dérivée pour cette photo (deux propriétés cachées et non recherchables du module en gardent la trace), donc réexporter une photo non touchée écrit un enregistrement vide et ne change rien. Un import qui change quoi que ce soit reconstruit aussi les paires d'entraînement dérivées des notes et relance le même réentraînement automatique à déclenchement différé que toute autre écriture de note. Les copies virtuelles sont dédupliquées vers leur original par chemin avant l'export, en préférant l'original quand les deux existent pour le même fichier.

**Notes, libellés et mots-clés via XMP.** Séparément, et toujours à sens unique dans cette direction :

1. Dans Lightroom, sélectionnez les photos et choisissez **Métadonnées → Enregistrer les métadonnées dans le fichier** (Ctrl/Cmd+S). Cela déverse la note, le libellé et les mots-clés du catalogue dans le sidecar XMP (RAW) ou les intègre directement dans le fichier (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars` (éventuellement restreint à un chemin) les relit dans la base de données de Facet.

### Règles de conflit

- **Les notes et libellés suivent la règle « le plus récent gagne »**, en comparant le `xmp:MetadataDate` du sidecar au `scanned_at` de la photo (la dernière fois que Facet l'a évaluée) — pas un horodatage par note. Un sidecar plus récent que le dernier scan peut écraser une note que vous avez modifiée dans Facet *après* ce scan. Gardez l'aller-retour simple : export → Lightroom lit → modification dans Lightroom → Lightroom enregistre → import, sans re-noter dans Facet entre les deux.
- **Les tags et mots-clés sont toujours fusionnés** (union, dédupliqués) dans les deux sens — les mots-clés Lightroom n'effacent jamais les tags automatiques de Facet, et inversement.
- **Multi-utilisateur** (`--export-sidecars --user alice` / `--import-sidecars --user alice`) : les notes sont routées vers la ligne `user_preferences` d'Alice au lieu des colonnes globales. Les mots-clés restent globaux quel que soit `--user` — ils sont partagés entre utilisateurs.
- Exécutez `python database.py --migrate-tags` après `--import-sidecars` si vous utilisez la table de correspondance `photo_tags`, afin que les filtres de tags voient immédiatement les mots-clés fusionnés.

## Capture One

Capture One n'écrit jamais dans le fichier original ni dans un sidecar XMP synchronisé en continu comme le fait l'enregistrement automatique de Lightroom — il conserve ses propres réglages dans des fichiers `.cos` (Sessions) ou dans sa base de catalogue, et sa préférence **Sync Metadata** possède un mode bidirectionnel « Full Sync » qui peut écraser silencieusement le côté ayant écrit en dernier. Faire tourner une boucle bidirectionnelle via ce réglage risque de perdre les modifications de Facet ou celles de Capture One. Le schéma sûr est **à sens unique, Facet → Capture One** :

1. `python facet.py --export-sidecars /chemin/vers/la/séance --embed-originals`.
2. Dans Capture One, laissez **Preferences → General → Sync Metadata** à sa valeur par défaut (pas « Full Sync »).
3. Sélectionnez les images importées, faites un clic droit, puis choisissez **Load Metadata** pour faire entrer une seule fois la note, le libellé et les mots-clés du sidecar (ou des métadonnées intégrées) dans les champs de catalogue de Capture One.

Considérez Facet comme la source de vérité amont pour les notes et tags dérivés de l'IA sur cette séance : faites l'import ponctuel via `Load Metadata`, puis effectuez vos choix dans Capture One sans reconnecter sa synchronisation de métadonnées vers le sidecar de Facet. Si vous voulez récupérer les choix de Capture One dans Facet, exportez-les explicitement de Capture One vers XMP et exécutez `--import-sidecars` sur ce dossier comme une étape séparée et délibérée plutôt qu'une synchronisation automatique — et souvenez-vous du [piège du nommage des sidecars RAW](#le-piège-du-nommage-des-sidecars-raw) ci-dessus : cela ne fonctionne que pour JPEG/HEIC/TIFF/PNG/DNG, puisque Capture One nomme lui aussi les sidecars RAW `<image>.xmp` plutôt que le `<image><ext>.xmp` de Facet.

## digiKam

Depuis digiKam 9.1.0 (sortie le 2026-06-07), digiKam lit nativement les sidecars XMP — pas besoin d'exiftool côté digiKam — et il recherche les deux conventions de nommage (`<image><ext>.xmp` d'abord, puis `<image>.xmp` en repli), donc il trouve les sidecars de Facet pour les fichiers RAW sans le piège ci-dessus. Après `python facet.py --export-sidecars`, ouvrez (ou actualisez) le dossier dans digiKam : il récupère automatiquement la note, le libellé de couleur, les mots-clés et les zones de visage nommées, tant que **Settings → Configure digiKam → Metadata → Read from sidecar files** est activé (c'est le réglage par défaut).

### Point d'ancrage Batch Queue Manager

Vous pouvez intégrer une réimportation Facet dans un flux Batch Queue Manager (BQM) de digiKam avec l'outil **Custom Script**, afin que les photos que vous notez ou libellez dans digiKam reviennent dans la base de données de Facet sans quitter digiKam. Activez **Settings → Configure digiKam → Metadata → Write to sidecar files** pour que digiKam persiste immédiatement vos modifications dans `<image>.xmp`, puis ajoutez une file dont le seul outil est Custom Script :

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sont les substitutions par fichier de digiKam (BQM exécute le script via `/bin/bash` sous Linux/macOS et attend un fichier de sortie, d'où le passage `cp`). Comme `--import-sidecars` parcourt tout le dossier, l'exécuter une fois par photo dans un lot volumineux est redondant, bien qu'inoffensif (c'est idempotent — les photos inchangées sont ignorées). Pour les gros lots, évitez le point d'ancrage BQM et exécutez simplement `python facet.py --import-sidecars /chemin/vers/le/dossier` une fois à la main après que la file a terminé.

## darktable

darktable bénéficie déjà d'un traitement de premier ordre dans [Configuration — Visionneuse](CONFIGURATION.md#visionneuse) (profils/styles d'export `viewer.raw_processor.darktable`) et [Visionneuse — Téléchargement](VIEWER.md#points-daccès-api) (conversions `type=darktable`). Côté XMP : darktable écrit lui-même son `<image><ext>.xmp` pour stocker son historique de retouches, et l'écriveur de sidecar de Facet, adossé à exiftool, fusionne dans ce même fichier en place — les nœuds `darktable:history`/masques sont préservés, jamais écrasés. Pas de recette séparée nécessaire ici : le comportement de sidecar bidirectionnel décrit plus haut pour Lightroom (export/import, le plus récent gagne, union des tags) s'applique de la même façon, sans le piège de nommage RAW puisque darktable et Facet s'accordent sur `<image><ext>.xmp`.

**Mise en garde : le rechargement du XMP par darktable lui-même n'est pas fiable.** Indépendamment du chemin d'écriture de Facet, réimporter une image que darktable a déjà retouchée peut amener darktable à écraser l'historique de retouches du sidecar par un fichier vierge au lieu de le recharger — un bug amont ouvert ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), signalé le 2026-03-15) contre lequel la préférence « check for new/updated xmp files on start » ne protège pas. Facet n'en est pas la cause (la fusion via exiftool ci-dessus préserve déjà `darktable:history`), mais le risque se situe dans l'étape de relecture dont dépend l'aller-retour de cette page. Solution pratique, dans le même esprit que la discipline « en une fois » de la recette Capture One ci-dessus : après `--export-sidecars`, ne réimportez pas en bloc un dossier déjà retouché — rechargez les sidecars seulement pour les images que Facet vient de toucher, et vérifiez que l'historique de retouches est bien encore là avant de faire confiance au reste du lot.

## Comment Facet fusionne

| Champ | Facet écrit | Facet relit | Règle de conflit |
|---|---|---|---|
| Note (étoiles / rejet) | `xmp:Rating` (`-1` = rejeté) | `xmp:Rating` | Le plus récent gagne, vs `scanned_at` |
| Libellé de couleur | `xmp:Label` (`Red` = rejeté, `Yellow` = favori) | `xmp:Label` | Le plus récent gagne, vs `scanned_at` |
| Tags / mots-clés | `dc:subject` (à plat, inclut les noms des personnes des visages nommés) | `dc:subject` | Toujours fusionné (union, dédupliqué) |
| Tags hiérarchiques | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<nom>`) | Non réimporté | Export uniquement |
| Légende | `dc:description` (+ `IPTC:Caption-Abstract` via exiftool) | Non réimporté | Export uniquement |
| Zones de visage nommées | `mwg-rs:RegionList` MWG (centrée-normalisée, `Type=Face`) | Non réimporté | Export uniquement ; lu nativement par digiKam, **pas** lu par Lightroom (une limitation Adobe connue — Lightroom ne consomme que les zones MWG qu'il a lui-même écrites) |

Voir [Commandes — Aperçu et export](COMMANDS.md#preview--export) pour la référence CLI complète (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).
