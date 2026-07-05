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

digiKam lit nativement les sidecars XMP — pas besoin d'exiftool côté digiKam — et il recherche les deux conventions de nommage (`<image><ext>.xmp` d'abord, puis `<image>.xmp` en repli), donc il trouve les sidecars de Facet pour les fichiers RAW sans le piège ci-dessus. Après `python facet.py --export-sidecars`, ouvrez (ou actualisez) le dossier dans digiKam : il récupère automatiquement la note, le libellé de couleur, les mots-clés et les zones de visage nommées, tant que **Settings → Configure digiKam → Metadata → Read from sidecar files** est activé (c'est le réglage par défaut).

### Point d'ancrage Batch Queue Manager

Vous pouvez intégrer une réimportation Facet dans un flux Batch Queue Manager (BQM) de digiKam avec l'outil **Custom Script**, afin que les photos que vous notez ou libellez dans digiKam reviennent dans la base de données de Facet sans quitter digiKam. Activez **Settings → Configure digiKam → Metadata → Write to sidecar files** pour que digiKam persiste immédiatement vos modifications dans `<image>.xmp`, puis ajoutez une file dont le seul outil est Custom Script :

```bash
#!/bin/bash
python /chemin/vers/facet.py --import-sidecars "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` sont les substitutions par fichier de digiKam (BQM exécute le script via `/bin/bash` sous Linux/macOS et attend un fichier de sortie, d'où le passage `cp`). Comme `--import-sidecars` parcourt tout le dossier, l'exécuter une fois par photo dans un lot volumineux est redondant, bien qu'inoffensif (c'est idempotent — les photos inchangées sont ignorées). Pour les gros lots, évitez le point d'ancrage BQM et exécutez simplement `python facet.py --import-sidecars /chemin/vers/le/dossier` une fois à la main après que la file a terminé.

## darktable

darktable bénéficie déjà d'un traitement de premier ordre dans [Configuration — Visionneuse](CONFIGURATION.md#visionneuse) (profils/styles d'export `viewer.raw_processor.darktable`) et [Visionneuse — Téléchargement](VIEWER.md#points-daccès-api) (conversions `type=darktable`). Côté XMP : darktable écrit lui-même son `<image>.xmp` pour stocker son historique de retouches, et l'écriveur de sidecar de Facet, adossé à exiftool, fusionne dans ce même fichier en place — les nœuds `darktable:history`/masques sont préservés, jamais écrasés. Pas de recette séparée nécessaire ici : le comportement de sidecar bidirectionnel décrit plus haut pour Lightroom (export/import, le plus récent gagne, union des tags) s'applique de la même façon, sans le piège de nommage RAW puisque darktable et Facet s'accordent sur `<image><ext>.xmp`.

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
