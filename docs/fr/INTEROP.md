# Recettes d'interopérabilité avec les éditeurs

> 🌐 [English](../INTEROP.md) · **Français** · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md)

Recettes pratiques, étape par étape, pour faire circuler dans les deux sens les notes, libellés et tags de Facet avec les éditeurs externes et les outils de gestion de photothèque que les photographes utilisent réellement. Cette page suppose que vous savez déjà *que* Facet écrit du XMP — voir [Commandes — Aperçu et export](COMMANDS.md#preview--export) pour la référence complète des options `--export-sidecars` / `--import-sidecars` et la correspondance des champs (`xmp:Rating`, `xmp:Label`, `dc:subject`).

## Le piège du nommage des sidecars RAW

Facet nomme un sidecar `<image><ext>.xmp` — par exemple `IMG_1234.CR2.xmp` à côté de `IMG_1234.CR2` — la même convention qu'utilisent darktable et digiKam. **Lightroom Classic et Capture One attendent l'inverse : `IMG_1234.xmp`, extension RAW retirée.** Aucun des deux ne détectera un sidecar écrit par Facet pour un fichier RAW propriétaire (CR2, CR3, NEF, ARW, RAF, RW2, ORF, SRW, PEF — tout sauf le DNG), et le `--import-sidecars` de Facet ne trouvera pas non plus un sidecar écrit par une application de l'écosystème Adobe pour ce même RAW. Il s'agit d'une incompatibilité de nommage entre écosystèmes, pas d'un bug de l'un ou l'autre côté.

Cela n'affecte **pas** :
- **JPEG, HEIC, TIFF, PNG, DNG** — passez `--embed-originals` et Facet écrit les métadonnées *directement dans le fichier* (via exiftool), donc il n'y a aucun nom de sidecar que Lightroom/Capture One pourrait manquer.
- **digiKam** — vérifie les deux conventions de nommage et trouve le sidecar de Facet dans tous les cas (voir [digiKam](#digikam) plus bas).
- **darktable** — utilise la même convention `<image><ext>.xmp` que Facet (voir [darktable](#darktable) plus bas).

Donc, pour un flux Lightroom ou Capture One : utilisez `--embed-originals` pour tout ce qui n'est pas du RAW propriétaire, et attendez-vous à ce que l'aller-retour par sidecar reste silencieux (pas d'erreur, simplement rien lu) pour les fichiers RAW purs. Si vous shootez en RAW+JPEG, le JPEG compagnon est le véhicule d'interopérabilité pratique — le RAW reste sur le disque, intact, tandis que la base de données de Facet conserve la note qui fait autorité.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (ajoutez un chemin pour restreindre la portée, par exemple `--export-sidecars /photos/mariage-2026`). Ajoutez `--embed-originals` pour aussi écrire directement dans les fichiers JPEG/HEIC/TIFF/PNG/DNG.
2. Dans le module Bibliothèque de Lightroom Classic, sélectionnez les photos (Ctrl/Cmd+A pour tout sélectionner) et choisissez **Métadonnées → Lire les métadonnées du fichier**. Lightroom écrase la note, le libellé de couleur et les mots-clés de son catalogue à partir du sidecar (ou des métadonnées intégrées, pour les formats ci-dessus).

Le marqueur de rejet de Facet (`xmp:Rating = -1`) est relu comme le drapeau Rejeter de Lightroom. Un favori Facet écrit `xmp:Label = Yellow`, que Lightroom affiche comme le **libellé de couleur Jaune** — pas le drapeau Sélectionner (Pick). Si votre flux Lightroom se base sur les drapeaux Pick plutôt que sur les libellés de couleur, ajoutez une étape de conversion libellé-couleur → pick, ou filtrez plutôt sur le libellé Jaune.

Un flux `python facet.py --export-manifest` (chemin, catégorie, tous les scores, tags, et les mêmes colonnes de note que `--export-sidecars` — y compris les notes par utilisateur via `--export-manifest --user alice` sur une installation multi-utilisateurs) existe désormais pour les outils qui veulent les données de Facet sans analyser le XMP — voir [Commandes — Aperçu et export](COMMANDS.md#preview--export). C'est ce flux que consomme le module externe Facet décrit ci-dessous.

### Le module externe Facet (notes et drapeaux Pick)

`facet.lrplugin/`, dans le dépôt Facet, est un module externe (plug-in) Lightroom Classic qui écrit la note en étoiles et l'état favori/rejeté de Facet **directement dans le catalogue**. Il existe parce que deux choses évoquées plus haut sont impossibles à corriger côté XMP : Lightroom ne trouve jamais un sidecar Facet pour un fichier RAW propriétaire, et le XMP n'a aucun canal pour le drapeau Sélectionner (Pick) de Lightroom. Le module lit un fichier manifeste : il ne parle jamais au serveur Facet, ne demande aucun mot de passe et fonctionne alors que Facet est arrêté — et comme il apparie les photos par chemin plutôt que par sidecar, **une bibliothèque 100 % RAW fonctionne exactement comme une bibliothèque JPEG**.

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

**Limites**, en toute honnêteté :

- **Les drapeaux Pick n'existent que dans le catalogue.** C'est un choix de Lightroom, pas du module : Lightroom n'écrit jamais le drapeau Pick dans le XMP, il n'atteint donc aucune autre application et il est perdu si vous reconstruisez le catalogue à partir des fichiers. Les notes en étoiles, elles, survivent via **Métadonnées → Enregistrer les métadonnées dans le fichier**.
- **Les scores de Facet ne sont pas ajoutés comme champs de métadonnées Lightroom** : il n'y a donc pas de collection dynamique « aggregate > 8 ». Le SDK d'Adobe n'admet les champs propres à un module externe dans le vocabulaire de recherche qu'en texte ou énumération (`sdktext:`) ; les opérateurs numériques (`>`, `<`, « compris entre ») restent réservés aux critères intégrés de Lightroom. Faire passer le score par la **note en étoiles** est délibéré : c'est le seul canal que Lightroom lui-même filtre et trie numériquement.
- **Sens unique.** Les notes que vous modifiez ensuite dans Lightroom reviennent vers Facet par l'aller-retour XMP décrit plus haut, pas par le module externe.
- **L'annulation** fonctionne par lot : le module écrit par blocs de 200 photos, donc Ctrl/Cmd+Z annule 200 photos à la fois.
- Cochez **Write facet-apply.log next to the manifest** avant un traitement si vous avez besoin de voir, ligne par ligne, quels chemins ont été appariés et ce qui a été écrit.

### Lightroom → Facet

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
python /chemin/vers/facet.py --import-sidecars "$(dirname "$INPUT")"
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
