# Référence de configuration

> 🌐 [English](../CONFIGURATION.md) · **Français** · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md)

Tous les réglages se trouvent dans `scoring_config.json`. Après modification, exécutez `python facet.py --recompute-average` pour mettre à jour les scores (aucun GPU requis).

## Table des matières

- [Utilisateurs](#users)
- [Analyse](#scanning)
- [Catégories](#categories)
- [Contextes de notation](#contextes-de-notation)
- [Notation](#scoring)
- [Seuils](#thresholds)
- [Composition](#composition)
- [Ajustements EXIF](#exif-adjustments)
- [Exposition](#exposure)
- [Pénalités](#penalties)
- [Normalisation](#normalization)
- [Modèles](#models)
- [Modèles d'évaluation de la qualité](#quality-assessment-models)
- [Traitement](#processing)
- [Détection de rafales](#burst-detection)
- [Notation des rafales](#burst-scoring)
- [Détection de doublons](#duplicate-detection)
- [Détection des visages](#face-detection)
- [Regroupement des visages](#face-clustering)
- [Traitement des visages](#face-processing)
- [Détection monochrome](#monochrome-detection)
- [Étiquetage](#tagging)
- [Étiquettes autonomes](#standalone-tags)
- [Analyse](#analysis)
- [Visionneuse](#viewer)
- [Performance](#performance)
- [Stockage](#storage)
- [Plugins](#plugins)
- [Capsules](#capsules)
- [Groupes de similarité](#similarity-groups)
- [Scènes](#scenes)
- [OCR](#ocr)
- [Frise chronologique](#timeline)
- [Carte](#map)
- [Traduction](#translation)

---

## Utilisateurs

Mode multi-utilisateur optionnel. Lorsque la clé `users` est présente (avec au moins un utilisateur), l'authentification par mot de passe unique est remplacée par une connexion par utilisateur.

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

### Champs utilisateur

| Champ | Type | Description |
|-------|------|-------------|
| `password_hash` | chaîne | Empreinte PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`). Générée par la commande `--add-user`. |
| `display_name` | chaîne | Affiché dans l'en-tête de l'interface |
| `role` | chaîne | `user`, `admin` ou `superadmin` |
| `directories` | tableau | Répertoires photo privés de cet utilisateur |

### Répertoires partagés

La clé `shared_directories` (au même niveau que les objets utilisateur) liste les répertoires visibles par tous les utilisateurs.

### Rôles

| Rôle | Voir ses photos + partagées | Noter/favori | Gérer personnes/visages | Déclencher des analyses |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Ajouter des utilisateurs

Les utilisateurs sont créés uniquement via la ligne de commande — il n'existe ni interface ni API d'inscription :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Demande un mot de passe, écrit l'empreinte dans scoring_config.json
```

Après l'ajout d'un utilisateur, modifiez `scoring_config.json` pour configurer ses `directories`.

### Rétrocompatibilité

- Absence de clé `users` = mode mono-utilisateur historique (comportement inchangé)
- `viewer.password` et `viewer.edition_password` sont ignorés en mode multi-utilisateur
- Les notes existantes dans la table `photos` restent valables en mode mono-utilisateur ; utilisez `--migrate-user-preferences` pour les copier

---

## Analyse

Contrôle le comportement d'analyse des répertoires.

```json
{
  "scanning": {
    "skip_hidden_directories": true
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `skip_hidden_directories` | `true` | Ignorer les répertoires commençant par `.` lors de l'analyse des photos |

---

## Catégories

Tableau de définitions de catégories. Voir [Notation](SCORING.md) pour la documentation détaillée des catégories.

Chaque catégorie possède :
- `name` - Identifiant de la catégorie
- `priority` - Plus la valeur est faible, plus la priorité est élevée (évaluée en premier)
- `filters` - Conditions de correspondance
- `weights` - Pondérations des métriques de notation (la somme doit faire 100)
- `modifiers` - Ajustements de comportement
- `tags` - Vocabulaire CLIP pour la correspondance par étiquettes

> **Poids de forme et d'harmonie colorimétrique.** Le bloc `weights` de chaque catégorie porte cinq clés de métriques explicables — `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` et `color_harmony_percent` — renseignées par `--recompute-form`. Elles sont livrées à `0` dans chaque catégorie, si bien que les agrégats restent identiques au bit près jusqu'à ce que vous en pondériez une (relancez alors `--recompute-average`). La somme des poids d'une catégorie doit toujours faire 100.

---

## Contextes de notation

Un contexte de notation est un **delta** nommé appliqué à l'ordre de priorité global des `categories` ci-dessus — il promeut une courte liste de catégories en tête et en exclut d'autres purement et simplement, en laissant tout le reste dans son ordre de priorité existant. Il existe parce que la priorité est globale et partagée, mais la catégorie qui *devrait* l'emporter varie selon la séance photo : une photo de danse à contre-jour taguée `sports` est captée par `silhouette` (priorité 42) bien avant que `sports` (priorité 71) ne soit atteinte, et les curseurs de poids ne peuvent rien y faire — ils régissent la façon dont la catégorie *sélectionnée* est notée, pas laquelle est sélectionnée.

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| Champ | Description |
|-------|-------------|
| `label_key` | Clé i18n pour le nom d'affichage du contexte |
| `promote` | Noms de catégorie déplacés en tête de l'ordre d'évaluation, dans l'ordre donné |
| `excluded` | Noms de catégorie entièrement retirés de l'évaluation (jamais retenus sous ce contexte) |
| `suggest_from_moments` | Valeurs `narrative_moment` qui suggèrent ce contexte pour un album — lues par `GET /api/albums/{id}/suggested_context` (voir [VIEWER.md](VIEWER.md)) |

**Ordre effectif** = `promote` (dans l'ordre) → l'ordre de priorité global moins les noms promus et exclus → `default` (la catégorie de repli, priorité 999) en dernier. Un nom présent à la fois dans `promote` et dans `excluded` est entièrement retiré de l'ordre — c'est `excluded` qui l'emporte, l'entrée `promote` n'est pas honorée. `default` elle-même ne peut jamais être promue ni exclue. Ne passer aucun contexte, ou un nom de contexte inconnu, retombe sur le simple ordre de priorité global (avec un avertissement journalisé pour un nom inconnu) ; la liste résolue `[(category_name, CategoryFilter)]` est mise en cache par nom de contexte pour la durée de vie de la configuration chargée (`ScoringConfig.resolve_context_order`). `python facet.py --validate-categories` signale (sans faire échouer le chargement) tout nom `promote`/`excluded` qui ne correspond à aucune catégorie réelle, tout nom présent dans les deux, ainsi que toute entrée `suggest_from_moments` qui n'est pas une clé de `narrative_moments.event_types.<default_event_type>` — une faute de frappe dans l'un de ces champs échoue sinon silencieusement.

Préréglages livrés par défaut — `default` est un delta vide, si bien que le comportement existant reste inchangé tant qu'un contexte n'est pas explicitement attribué :

| Contexte | Promeut | Exclut | Suggéré à partir des moments |
|---------|----------|----------|------------------------|
| `default` | — | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` | `sports`, `concert`, `nightlife` |
| `party_event` | `group_portrait`, `candid`, `food` | — | `celebration`, `group_gathering`, `dining` |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — | `portrait`, `children` |
| `wildlife` | `wildlife` | — | `nature_wildlife`, `pets` |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — | `scenic_landscape`, `mountains`, `snow_winter` |
| `motorsport` | `sports`, `vehicle` | `silhouette` | `sports`, `road_vehicle` |

### Ajouter votre propre contexte

Les préréglages fournis ne forment pas un ensemble fermé : ajoutez une clé sous `scoring_contexts` et vous obtenez un contexte comme les autres — il se résout, il s'attribue à un album, et son delta se modifie depuis l'onglet **Contexte de notation**. Rien n'est à déclarer dans le code.

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

Une nuance toutefois : `label_key` est recherchée dans les paquets i18n, et une clé absente retombe désormais sur le **`name`** propre au contexte (par exemple `dance_comp`) plutôt que sur un chemin brut à points — un contexte personnalisé reste lisible dans le sélecteur, dans toutes les langues, même avant d'avoir une traduction. Ajoutez la clé aux six paquets `i18n/translations/*.json` pour lui donner un libellé correctement localisé plutôt que le simple nom.

### Modifier un contexte

`PUT /api/config/scoring_contexts/{name}` (réservé au mode édition) réécrit le delta d'un seul contexte depuis l'onglet **Contexte de notation** de la visionneuse — faites glisser la tête promue dans l'ordre voulu (ou utilisez les boutons Monter/Descendre), cliquez sur une catégorie pour basculer son exclusion, enregistrez. Le corps est `{"promote": [nom, ...], "excluded": [nom, ...]}`. Seuls ces deux champs sont modifiables : `label_key` et `suggest_from_moments` restent exactement tels quels, et tous les autres contextes sont laissés intacts. **L'interface ne propose délibérément que l'édition du delta** — un contexte ne porte jamais d'ordre complet autonome, si bien que les catégories non promues conservent toujours l'ordre de priorité global et qu'une catégorie ajoutée plus tard ne peut jamais manquer silencieusement dans six listes distinctes.

L'écriture est rejetée par un 400 nommant le fautif lorsque le contexte n'existe pas, lorsqu'une entrée de `promote`/`excluded` ne correspond à aucune catégorie existante, lorsque `default` apparaît dans l'une des deux listes (c'est la catégorie de repli épinglée : elle ne peut être ni promue ni exclue), ou lorsque `promote` répète un nom (son ordre est signifiant, un doublon serait donc ambigu). Lister la même catégorie dans **les deux** listes reste accepté — `excluded` l'emporte et l'entrée `promote` est abandonnée, exactement comme documenté ci-dessus — et un doublon à l'intérieur d'`excluded` est fusionné plutôt que rejeté, puisqu'il s'agit d'un ensemble. Chaque écriture prend la même copie de sauvegarde horodatée et élaguée `.backup.<timestamp>` et prend le même verrou que les writers de priorité et de poids, si bien que des enregistrements de configuration concurrents ne peuvent pas s'annuler mutuellement. `resolve_context_order` met son résultat en cache par instance de `ScoringConfig`, et chaque lecteur en construit une nouvelle à chaque requête : il n'y a donc aucun cache d'ordre à invalider après une écriture.

Comme une réorganisation des priorités, modifier un contexte ne touche pas en soi la `category` stockée d'une photo — lancez un recalcul ensuite (voir [Modifier les priorités nécessite un recalcul](#réorganiser-la-priorité-globale)) ; l'onglet propose un bouton **Recalculer maintenant** précisément pour cela.

### Assigner un contexte

Un contexte de notation s'attribue **par album** via `PUT /api/albums/{id}/scoring_context` (réservé au mode édition), qui écrit la colonne `scoring_context` de l'album et matérialise la même valeur dans `photo_scoring_overrides.scoring_context` pour chaque photo qui est membre **à cet instant précis**, en laissant de côté tout membre dont le remplacement a été défini manuellement (`source = 'manual'`) — une attribution d'album ne convertit jamais silencieusement le choix manuel d'une photo en un contexte venant de l'album. Le compteur `conflicts` de la réponse indique combien de membres non manuels portaient déjà un contexte différent (le dernier enregistrement l'emporte), `manual_skipped` indique combien de membres manuels ont été laissés intacts, et `updated` indique combien ont réellement été écrites. Un album manuel résout son appartenance à partir de ses lignes `album_photos` ; un album intelligent (`is_smart`) n'en a aucune, son appartenance est donc résolue en évaluant son `smart_filter_json` enregistré sur la base de données en direct (`_resolve_album_member_paths`, qui reflète la branche intelligente de `_fetch_album_photos`). C'est la **définition de filtre** de l'album, pas la vue galerie : `smart_filter_json` ne porte que le filtre choisi par l'utilisateur (tri, personne, etc.) et exclut délibérément les préférences d'affichage `hide_blinks`/`hide_bursts`/`hide_duplicates`/`hide_rejected` de la galerie (globales, modifiables en cours d'exécution via `viewer.defaults`, et ne faisant pas partie de la définition propre de l'album), si bien que `updated` peut légitimement dépasser le nombre de photos que la propre vue galerie de l'album affiche lorsque ces bascules sont activées — une photo suiveuse de rafale par ailleurs correspondante reste un membre à part entière. Un album intelligent dont le filtre ne correspond actuellement à rien renvoie `updated: 0` avec un `warning`. Dans tous les cas, l'attribution est un instantané, pas un abonnement : pour un album manuel, une photo ajoutée *par la suite* via `append_album_photos` hérite bien automatiquement du contexte (en laissant également de côté les membres manuels), mais une photo qui correspond *plus tard* au filtre d'un album intelligent n'hérite **pas** rétroactivement du contexte — seul un nouvel appel à `PUT` réattribue le contexte aux membres du moment. `DELETE /api/albums/{id}/scoring_context` efface le `scoring_context` de l'album et annule l'attribution sur exactement les membres que cet album avait marqués (`source = 'album:<id>'`), sans toucher au remplacement manuel propre à une photo. Retirer des photos précises d'un album (`DELETE /api/albums/{id}/photos`) annule de la même façon l'attribution de cet album sur exactement ces photos, sauf lorsqu'une photo retirée est *encore* membre d'un autre album qui déclare lui-même un contexte — une seule colonne `source` ne peut pas représenter une appartenance à plusieurs albums, donc cette photo est réattribuée avec le contexte de cet autre album plutôt que d'être laissée sans catégorie (cette redérivation se limite aux photos de la requête de retrait ; une suppression d'album complète ou un effacement explicite du contexte ne le tente pas, car vérifier chaque photo effacée par rapport à chaque autre album déclarant un contexte n'est pas borné pour l'appartenance complète d'un album intelligent). Retirer des photos d'un album intelligent est sans effet (`album_photos` ne porte aucune ligne pour lui, et les photos retirées restent généralement membres). `GET /api/albums/{id}/suggested_context` propose un contexte à partir du `narrative_moment` dominant de l'album (résolu de la même façon, `_resolve_album_member_paths`), mappé via `suggest_from_moments`, accompagné du `share` du moment dominant dans l'album — cet appel n'écrit rien ; l'attribution ci-dessus doit toujours être appelée explicitement.

Pour une photo isolée récalcitrante, un **remplacement de catégorie** est l'échappatoire — non pas un contexte, mais une attribution directe de catégorie : `POST /api/comparison/override_category` (réservé au mode édition) valide le nom de catégorie par rapport à la configuration et l'enregistre dans `photo_scoring_overrides.category_override` ; `POST /api/comparison/clear_category_override` le supprime, laissant de nouveau l'évaluation des filtres décider au prochain recalcul.

Les deux leviers sont conservés dans une seule table annexe, `photo_scoring_overrides(photo_path PK, scoring_context, category_override, source, created_at, created_by)`, plutôt que comme des colonnes de `photos` — `save_photo`/`save_photos_batch` écrivent les lignes de photo avec `INSERT OR REPLACE` (`processing/scorer.py`), ce qui supprimerait silencieusement toute nouvelle colonne de cette ligne au prochain rescan. `Facet._determine_photo_category` de `processing/scorer.py` est le point de passage unique qui résout les deux, aussi bien sur le chemin de scan que sur `--recompute-average` : un `category_override` valide l'emporte purement et simplement ; sinon, `ScoringConfig.determine_category(photo_data, context=scoring_context)` évalue l'ordre effectif du contexte. Un filtre numérique échoue toujours lorsque la valeur EXIF sous-jacente est manquante ou ininterprétable, quel que soit le contexte — voir [Notation — le piège des données EXIF manquantes](SCORING.md#le-piège-des-données-exif-manquantes) pour le cas `sports`/`shutter_speed_max` que la seule promotion ne peut pas corriger.

### Réorganiser la priorité globale

`GET|POST /api/config/category_priorities` (réservé au mode édition) lit et réécrit l'ordre de base sur lequel chaque contexte applique son delta. `POST` prend `{"order": [name, ...]}` — une permutation à ensemble égal de tous les noms de catégorie hors `default` — et **permute le multi-ensemble de priorités existant selon le nouvel ordre** plutôt que de le renuméroter (p. ex. 10/20/30) : cela garde les nombres de priorité documentés pertinents et garantit l'unicité par construction. `default` (priorité 999) reste fixé en dernière position et n'est pas concerné par la réorganisation. Chaque écriture prend d'abord une copie horodatée `.backup.<timestamp>` de `scoring_config.json`, et cet écrivain partage un verrou avec l'éditeur de poids (`update_category_weights`) — la précédente lecture-modification-écriture non protégée permettait à un enregistrement concurrent de l'un d'écraser silencieusement les modifications de l'autre.

**Modifier les priorités nécessite un recalcul.** La réorganisation elle-même ne touche la `category` stockée d'aucune photo — lancez `python facet.py --recompute-average`, ou déclenchez `POST /api/scan/recompute` depuis la visionneuse (réservé au mode édition) puis interrogez `GET /api/scan/recompute_status`. `update_all_aggregates` émet des lignes `@FACET_PROGRESS` (auparavant réservées à `tqdm`), ce qui permet d'alimenter une barre de progression. Un recalcul maintient une seule et longue transaction d'écriture sur toute la table `photos`, si bien que `--recompute-average`/`--recompute-category` acquièrent, pour toute leur durée, un `facet.LibraryLock` inter-processus (un fichier horodaté par PID `<db_dir>/.facet_cache/library.lock`), et pas seulement le verrou en mémoire de la visionneuse : un recalcul en ligne de commande se refuse d'emblée si un scan est déjà en cours, un scan en ligne de commande se refuse d'emblée si un recalcul est déjà en cours, et les points d'accès de la visionneuse (`POST /api/scan/start`, `POST /api/scan/recompute`) consultent ce même fichier de verrou et renvoient 409 en nommant le détenteur (type, pid, origine) avant de démarrer — une tâche lancée depuis un terminal et une tâche déclenchée par la visionneuse ne peuvent donc plus entrer en collision et mourir avec `SQLITE_BUSY`. Un détenteur qui plante est détecté immédiatement via une vérification de vivacité du PID au niveau du système d'exploitation, si bien qu'un verrou périmé se répare de lui-même plutôt que de bloquer les tâches suivantes. Il reste une lacune : scan contre scan en ligne de commande, où deux scans concurrents lancés depuis un terminal ne reçoivent encore qu'un avertissement, pas un refus (choix délibéré ; `--resume` continue de refuser sans exception). Si `normalization.per_category` est activé, voir [Normalisation](#normalisation) pour comprendre pourquoi même un recalcul unique et sans conflit peut nécessiter deux passages.

---

## Notation

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `score_min` | `0.0` | Score minimum possible |
| `score_max` | `10.0` | Score maximum possible |
| `score_precision` | `2` | Nombre de décimales pour les scores |

---

## Seuils

Seuils de détection pour la catégorisation automatique.

```json
{
  "thresholds": {
    "portrait_face_ratio_percent": 5,
    "blink_penalty_percent": 50,
    "night_luminance_threshold": 0.15,
    "night_iso_threshold": 3200,
    "long_exposure_shutter_threshold": 1.0,
    "astro_shutter_threshold": 10.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `portrait_face_ratio_percent` | `5` | Visage > 5 % du cadre = portrait |
| `blink_penalty_percent` | `50` | Multiplicateur de score en cas de clignement détecté (0,5x) |
| `night_luminance_threshold` | `0.15` | Luminance moyenne inférieure à cette valeur = nuit |
| `night_iso_threshold` | `3200` | ISO supérieur à cette valeur = faible luminosité |
| `long_exposure_shutter_threshold` | `1.0` | Vitesse d'obturation > 1 s = pose longue |
| `astro_shutter_threshold` | `10.0` | Vitesse d'obturation > 10 s = astrophotographie |

---

## Composition

Notation de composition fondée sur des règles (utilisée lorsque SAMP-Net n'est pas actif).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `power_point_weight` | `2.0` | Pondération du placement selon la règle des tiers |
| `line_weight` | `1.0` | Pondération des lignes directrices |

---

## Ajustements EXIF

Ajustements de notation automatiques fondés sur les réglages de l'appareil.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `iso_sharpness_compensation` | `true` | Réduit la pénalité de netteté pour les ISO élevés |
| `aperture_isolation_boost` | `true` | Renforce l'isolation pour les grandes ouvertures (f/1.4-f/2.8) |

---

## Exposition

Contrôle l'analyse de l'exposition et la détection des écrêtages.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `shadow_clip_threshold_percent` | `15` | Signaler si > 15 % des pixels sont noir pur |
| `highlight_clip_threshold_percent` | `10` | Signaler si > 10 % des pixels sont blanc pur |
| `silhouette_detection` | `true` | Détecter les silhouettes intentionnelles |

---

## Pénalités

Pénalités de score pour les problèmes techniques.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "bimodality_threshold": 2.5,
    "bimodality_penalty_points": 0.5,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_pixel_percent": 5,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `noise_sigma_threshold` | `4.0` | Un bruit supérieur déclenche une pénalité |
| `noise_max_penalty_points` | `1.5` | Pénalité de bruit maximale |
| `noise_penalty_per_sigma` | `0.3` | Points par sigma au-dessus du seuil |
| `bimodality_threshold` | `2.5` | Coefficient de bimodalité de l'histogramme |
| `bimodality_penalty_points` | `0.5` | Pénalité pour les histogrammes bimodaux |
| `leading_lines_blend_percent` | `30` | Mélange dans comp_score |
| `oversaturation_threshold` | `0.9` | Seuil de saturation moyenne |
| `oversaturation_pixel_percent` | `5` | Réservé à la détection au niveau du pixel |
| `oversaturation_penalty_points` | `0.5` | Pénalité de sursaturation |

**Formule de pénalité de bruit :**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalisation

Contrôle la façon dont les métriques brutes sont mises à l'échelle entre 0 et 10.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `method` | `"percentile"` | Méthode de normalisation |
| `percentile_target` | `90` | Le 90e centile = score de 10,0 |
| `per_category` | `true` | Normalisation propre à chaque catégorie |
| `category_min_samples` | `50` | Nombre minimal de photos pour la normalisation par catégorie |

**Un seul recalcul ne suffit pas à converger quand `per_category` est activé.** `compute_percentiles_per_category` (`config/percentile_normalizer.py`) regroupe les photos par la colonne `photos.category` *actuellement stockée*, et s'exécute une seule fois, en amont, avant que `update_all_aggregates` ne redétermine et ne réécrive la catégorie de chaque photo pour la nouvelle configuration. Ainsi, après tout changement susceptible de déplacer des photos entre catégories — réorganisation des priorités, affectation ou suppression d'un contexte de notation, ajout ou suppression d'une dérogation de catégorie — le premier `--recompute-average` normalise chaque photo par rapport à des centiles regroupés selon son **ancienne** catégorie, et non celle qui va lui être attribuée. Relancez `--recompute-average` une seconde fois pour que les centiles par catégorie soient calculés à partir de la colonne `category` désormais correcte ; ce n'est qu'alors que les scores normalisés se stabilisent.

---

## Modèles

Sélectionne les modèles utilisés selon le profil VRAM.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": [],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (8GB+ RAM)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": false,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "qwen2-vl-2b",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "similarity_threshold_percent": 8
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "similarity_threshold_percent": 22
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth",
      "download_url": "https://github.com/bcmi/Image-Composition-Assessment-with-SAMP/releases/download/v1.0/samp_net.pth",
      "input_size": 384,
      "patterns": [
        "none", "center", "rule_of_thirds", "golden_ratio", "triangle",
        "horizontal", "vertical", "diagonal", "symmetric", "curved",
        "radial", "vanishing_point", "pattern", "fill_frame"
      ]
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `vram_profile` | `"auto"` | Profil actif (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) |
| `keep_in_ram` | `"auto"` | Conserver les modèles en RAM entre les blocs multi-pass (`"auto"`, `"always"`, `"never"`). `auto` vérifie la RAM disponible avant la mise en cache. |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modèles PyIQA à exécuter pour ce profil (vide pour `legacy`) |
| `profiles.*.saliency_enabled` | `true` (16gb/24gb) | Exécuter la saillance du sujet BiRefNet pour ce profil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modèle d'embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Dimensions de l'embedding (1152 pour SigLIP 2) |
| `clip.similarity_threshold_percent` | `8` | Similarité cosinus CLIP minimale pour une correspondance d'étiquette |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modèle CLIP historique (profils legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Poids pré-entraînés historiques |
| `clip_legacy.embedding_dim` | `768` | Dimensions de l'embedding historique |
| `clip_legacy.similarity_threshold_percent` | `22` | Seuil de correspondance d'étiquette pour le CLIP historique |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Chemin HuggingFace (VLM de composition 24gb) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modèle d'étiquetage pour le profil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Images par lot d'inférence VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modèle d'étiquetage pour le profil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Images par lot d'inférence VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modèle de saillance BiRefNet |
| `saliency.resolution` | `1024` | Résolution d'inférence |
| `saliency.mask_threshold` | `0.3` | Seuil sigmoïde pour le masque binaire du sujet |
| `saliency.min_subject_pixels` | `50` | Nombre minimal de pixels de sujet pour considérer qu'un sujet est détecté |
| `samp_net.input_size` | `384` | Taille d'entrée du modèle de composition |

### Détection automatique de la VRAM

Lorsque `vram_profile` vaut `"auto"` (par défaut), le système détecte la VRAM GPU disponible au démarrage et sélectionne le plus grand profil compatible :

| VRAM détectée | Profil sélectionné |
|---------------|--------------------|
| ≥ 20 Go | `24gb` |
| ≥ 14 Go | `16gb` |
| ≥ 6 Go | `8gb` |
| Pas de GPU | `legacy` (utilise la RAM système) |

---

## Modèles d'évaluation de la qualité

Sélectionne le modèle qui note la qualité/l'esthétique de l'image, via la bibliothèque [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `model` | `"auto"` | Modèle de qualité : `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` utilise `topiq`. |
| `prefer_llm` | `false` | Préférer un évaluateur fondé sur un LLM lorsqu'il est disponible |

### Modèles de qualité disponibles

SRCC = coefficient de corrélation de rang de Spearman sur le benchmark KonIQ-10k (1,0 = parfait).

| Modèle | SRCC | VRAM | Notes |
|--------|------|------|-------|
| `topiq` | 0,93 | ~2 Go | Par défaut (`auto`) ; squelette ResNet50 avec attention descendante |
| `hyperiqa` | 0,90 | ~2 Go | Hyper-réseau, adaptatif au contenu |
| `dbcnn` | 0,90 | ~2 Go | CNN à double branche (distorsions synthétiques + authentiques) |
| `musiq` | 0,87 | ~2 Go | Transformeur multi-échelle ; gère toute résolution |
| `clipiqa+` | 0,86 | ~4 Go | CLIP avec prompts de qualité appris |
| `clip-mlp` | 0,76 | ~4 Go | CLIP ViT-L-14 historique + tête MLP |

### Changer de modèle de qualité

1. Modifiez `scoring_config.json` :
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Re-notez les photos existantes (optionnel) :
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Traitement

Réglages de traitement unifiés pour le traitement par lots GPU et le mode multi-pass.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Concepts clés

**`gpu_batch_size`** - Nombre d'images traitées ensemble sur le GPU en une seule passe avant. Limité par la VRAM. Auto-réglé : réduit lorsque la mémoire GPU dépasse la limite.

**`ram_chunk_size`** - Nombre d'images mises en cache en RAM entre les passes de modèle (mode multi-pass uniquement). Réduit les E/S disque en chargeant les images une fois par bloc. Limité par la RAM système. Auto-réglé : réduit lorsque la mémoire système dépasse la limite.

### Référence des réglages

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mode` | `"auto"` | Mode de traitement : `auto`, `multi-pass`, `single-pass` |
| `gpu_batch_size` | `16` | Images par lot GPU (limité par la VRAM) |
| `ram_chunk_size` | `32` | Images par bloc RAM (multi-pass) |
| `num_workers` | `4` | Threads de chargement d'images |
| `load_workers` | `num_workers` | Threads de chargement de blocs en multi-pass (plafonnés à 8, `1` = séquentiel) |
| `raw_decode_concurrency` | `0` (auto) | Nombre maximal de décodages RAW simultanés ; dimensionné automatiquement selon CPU/RAM (1-4), `1` = entièrement sérialisé |
| `raw_decode_timeout_seconds` | `120` | Abandonner un décodage RAW bloqué après ce délai (`0` = désactivé) ; l'analyse échoue rapidement après des blocages répétés |
| `exif_prefetch` | `true` | Mode single-pass : précharger l'EXIF en arrière-plan au lieu de bloquer le thread GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Activer l'auto-réglage |
| `monitor_interval_seconds` | `5` | Intervalle de vérification des ressources |
| `tuning_interval_images` | `32` | Re-régler toutes les N images |
| `min_processing_workers` | `1` | Nombre minimal de threads de chargement |
| `max_processing_workers` | `32` | Nombre maximal de threads de chargement |
| `min_gpu_batch_size` | `2` | Taille minimale de lot GPU |
| `max_gpu_batch_size` | `32` | Taille maximale de lot GPU |
| `min_ram_chunk_size` | `10` | Taille minimale de bloc RAM |
| `max_ram_chunk_size` | `128` | Taille maximale de bloc RAM |
| `memory_limit_percent` | `85` | Limite d'utilisation de la mémoire système |
| `cpu_target_percent` | `85` | Cible d'utilisation du CPU |
| `metrics_print_interval_seconds` | `30` | Intervalle d'affichage des statistiques |
| **thumbnails** | | |
| `photo_size` | `640` | Taille de la vignette stockée (pixels) |
| `photo_quality` | `80` | Qualité JPEG des vignettes |
| `face_padding_ratio` | `0.3` | Marge autour des recadrages de visage |

### Modes de traitement

| Mode | Description |
|------|-------------|
| `auto` | Sélectionne automatiquement multi-pass ou single-pass selon la VRAM |
| `multi-pass` | Chargement séquentiel des modèles (fonctionne avec une VRAM limitée) |
| `single-pass` | Tous les modèles chargés en même temps (nécessite une VRAM élevée) |

### Fonctionnement du multi-pass

Au lieu de charger tous les modèles en même temps, le multi-pass :

1. Charge les images par blocs en RAM (`ram_chunk_size` par défaut : 32)
2. Pour chaque bloc, exécute les modèles séquentiellement : charger le modèle → traiter le bloc → décharger le modèle
3. Combine les résultats dans une passe d'agrégation finale

Chaque image est chargée une fois par bloc, et les passes sont regroupées pour tenir dans la VRAM disponible, de sorte que les VLM de tagger/composition plus volumineux s'exécutent même avec une VRAM limitée.

### Comportement de l'auto-réglage

Le système surveille l'utilisation des ressources et ajuste :

| Métrique | Action |
|----------|--------|
| Mémoire GPU > limite | Réduire `gpu_batch_size` de 25 % |
| RAM système > limite | Réduire `ram_chunk_size` de 25 % |
| RAM système < (limite - 20 %) | Augmenter `ram_chunk_size` de 25 % |
| CPU > cible | Suggérer moins de workers |
| Délais de file d'attente > 5 % | Suggérer plus de workers |

### Regroupement dynamique des passes

Quand la VRAM le permet, plusieurs petits modèles s'exécutent ensemble :

| VRAM | Passe 1 | Passe 2 |
|------|---------|---------|
| 8 Go | CLIP + SAMP-Net + InsightFace | TOPIQ |
| 12 Go | CLIP + SAMP-Net + InsightFace + TOPIQ | - |
| 16 Go | CLIP + SAMP-Net + InsightFace + TOPIQ | VLM tagger |
| 24 Go+ | Tous les modèles ensemble (single-pass) | - |

### Options en ligne de commande

```bash
# Par défaut : multi-pass automatique avec regroupement optimal
python facet.py /path/to/photos

# Forcer le single-pass (tous les modèles chargés en même temps)
python facet.py /path --single-pass

# Exécuter une passe spécifique uniquement
python facet.py /path --pass quality       # TOPIQ uniquement
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérite esthétique)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualité + distorsion)
python facet.py /path --pass tags          # Tagger configuré uniquement
python facet.py /path --pass composition   # SAMP-Net uniquement
python facet.py /path --pass faces         # InsightFace uniquement
python facet.py /path --pass embeddings    # Embeddings CLIP/SigLIP uniquement
python facet.py /path --pass saliency      # Saillance du sujet BiRefNet

# Lister les modèles disponibles
python facet.py --list-models
```

---

## Détection de rafales

Regroupe les photos similaires prises en succession rapide.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `similarity_threshold_percent` | `70` | Seuil de similarité des empreintes d'image |
| `time_window_minutes` | `0.8` | Temps maximal entre deux photos |
| `rapid_burst_seconds` | `0.4` | Photos prises dans cet intervalle automatiquement regroupées |

---

## Notifications de mise à jour

Prévient l'administrateur de l'installation qu'une nouvelle version de Facet est parue. À ne pas confondre avec le « Une nouvelle version est disponible — Recharger » du navigateur, qui bascule la page sur un paquet déjà téléchargé : ici il s'agit d'une version que personne n'a encore installée.

Volontairement discret. La vérification a lieu côté serveur et son résultat est mis en cache : une installation n'interroge GitHub qu'une fois tous les `interval_days`, quel que soit le nombre de personnes devant le viewer. La requête ne transporte rien d'autre qu'elle-même — aucun jeton, aucun identifiant, rien de la photothèque. Un échec est silencieux : un GitHub injoignable se traduit par « aucune mise à jour connue », jamais par une erreur. Seuls les utilisateurs en mode édition sont prévenus, car la mise à jour relève de l'exploitant, et chaque navigateur n'affiche l'avis qu'une fois par semaine au maximum.

Passez `enabled` à `false` pour supprimer complètement la requête sortante.

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| Paramètre | Défaut | Description |
|---|---|---|
| `enabled` | `true` | `false` désactive la vérification ; plus aucune requête n'est émise |
| `check_url` | API GitHub des dernières versions | Où chercher la dernière version publiée |
| `interval_days` | `7` | Durée de mise en cache du résultat avant une nouvelle interrogation |

---

## Détection de séquences

Nomme les séries prises volontairement en plusieurs vues — aujourd'hui les bracketings
d'exposition — pour qu'elles ne soient pas lues comme des prises concurrentes. L'échelle
d'exposition est déduite des `f_stop` / `shutter_speed` / `ISO` déjà stockés
(`EV = log2(N^2 / t) - log2(ISO / 100)`) : une bibliothèque existante est donc étiquetée par
simple calcul, sans nouveau scan, sans décodage d'image et sans modèle.

Une série est retenue si les vues partagent le même boîtier, se suivent dans
`max_gap_seconds`, gardent le même cadrage (`max_hamming` sur le pHash) et si leurs IL
forment une échelle régulière et unidirectionnelle d'au moins `min_frames` vues couvrant
`min_span_stops`. C'est la régularité des pas qui distingue un bracketing d'une série à main
levée dans une lumière changeante.

Chaque vue reçoit `sequence_ev_offset`, sa correction d'exposition par rapport à la vue de
référence, signée comme sur le boîtier : `-2` est la vue sombre, `+2` la vue claire. Quand
une rafale correspond exactement à un bracketing, son `is_burst_lead` est déplacé sur la vue
de référence, afin que la galerie affiche la photo correctement exposée plutôt que celle qui
obtient le meilleur score.

La vue de référence est le barreau central de l'échelle. Un nombre pair de vues en compte
deux à égale distance du centre : la référence est alors celle qui a brûlé le moins
d'extrémités de son histogramme (`shadow_clipped` / `highlight_clipped`), car la vue mesurée
tient la scène tandis que les barreaux qui l'encadrent sont poussés assez loin pour écrêter.
Si aucune des deux n'a été mesurée, ou si elles écrêtent autant l'une que l'autre, la plus
ancienne l'emporte. Une échelle impaire se centre toujours sur sa vue médiane, quel que soit
l'écrêtage : une série symétrique `(-2, 0, +2)` n'est donc pas affectée.

Lancé par `--detect-sequences` ; s'exécute aussi à la fin de chaque scan, après le
regroupement des rafales.

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| Paramètre | Défaut | Description |
|---|---|---|
| `enabled` | `true` | Désactive entièrement la détection de bracketing |
| `max_gap_seconds` | `3.0` | Écart maximal entre deux vues consécutives d'une série |
| `max_hamming` | `10` | Distance pHash tolérée entre les vues (même cadrage) |
| `min_frames` | `3` | Nombre minimal de vues pour parler de bracketing. `2` est optionnel — voir la mise en garde ci-dessous |
| `min_step_stops` | `0.5` | Plus petit écart d'IL considéré comme volontaire |
| `min_span_stops` | `1.0` | Amplitude minimale entre la vue la plus sombre et la plus claire |
| `step_tolerance_stops` | `0.34` | Irrégularité tolérée entre les pas (un tiers d'IL) |

**Pourquoi `min_frames` vaut `3` par défaut.** Sur une paire, deux des quatre tests de
l'échelle ne veulent plus rien dire : un pas unique est trivialement unidirectionnel et
trivialement régulier. Il ne reste que « deux vues prises à quelques instants d'intervalle,
au même cadrage, séparées d'au moins un IL » — ce qui décrit tout aussi bien un photographe
qui corrige son exposition et redéclenche qu'un vrai bracketing à deux vues. Mesuré sur une
bibliothèque de 124 886 photos, `2` ajoute 381 séries aux 226 trouvées par défaut, et les
indices disent que la plupart n'en sont pas : 56 % couvrent moins de deux IL là où 99,6 % des
séries confirmées en couvrent deux ou plus, et leur profil d'écrêtage le plus fréquent est
« les deux vues sombres » plutôt que l'encadrement ombres/hautes lumières des séries
confirmées.

Pire, une paire qui est *réellement* ce qui reste d'une série de trois vues se compose de
deux barreaux voisins qui encadrent la référence, et rien de stocké ne dit de quel côté
manquait le troisième : le `sequence_ev_offset` `0` se pose alors sur une vue que le boîtier
n'a jamais mesurée, et `hide_brackets` (actif par défaut) masque l'autre. Ne passez à `2` que
si vous pratiquez le bracketing à deux vues et préférez assumer ces faux positifs plutôt que
de manquer ces séries.

---

## Détection de panoramas

Les images d'un panorama ont été prises pour être assemblées, pas pour se concurrencer : la détection de rafales les lit comme des prises concurrentes et n'en garde qu'une. Cette passe les nomme sur des preuves géométriques — points SIFT et homographie RANSAC entre images consécutives, mesurés sur les vignettes 640px déjà stockées. Aucun décodage de l'original, aucun modèle, aucune dépendance supplémentaire.

Ce qui distingue un balayage d'une rafale est le déplacement **cumulé**, pas le décalage image par image : un panorama est pris avec environ 90 % de recouvrement, donc un pas ne déplace que 5 à 18 % du cadre, tandis que sur la durée une rafale oscille autour de zéro et un balayage avance. Les panoramas simples et HDR sont deux types distincts, séparés par l'écart d'exposition.

Les seuils ont été calibrés sur 26 panoramas et 8 non-panoramas confirmés à l'œil sur une bibliothèque de 126 000 photos. Précision mesurée : environ 96 %. Le rappel est volontairement incomplet — les balayages verticaux à faible déplacement et les panoramas à peu de positions passent sous le seuil et sont manqués. Manquer un panorama ne coûte rien ; étiqueter du reportage à tort coûte la confiance, et la correction manuelle persistante rattrape les deux sens.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5
  }
}
```

| Paramètre | Défaut | Description |
|---------|---------|-------------|
| `enabled` | `true` | Désactiver complètement la détection de panoramas |
| `max_gap_seconds` | `30.0` | Écart maximal entre deux images consécutives d'un balayage |
| `min_frames` | `8` | Série la plus courte considérée comme un panorama. Le discriminant le plus fort : tous les non-panoramas confirmés comptaient 6 images ou moins |
| `min_drift` | `0.43` | Balayage total, en largeurs de cadre, pour qu'une série compte. Les non-panoramas confirmés se groupent entre 0,36 et 0,40 ; le plus petit vrai panorama est à 0,46 |
| `min_inliers` | `25` | Points concordants RANSAC requis pour valider une paire |
| `max_step` | `0.9` | Plus grand pas isolé, en largeurs de cadre — au-delà c'est une coupure de scène |
| `back_tolerance` | `0.02` | Recul toléré sur un pas avant que la série ne s'arrête |
| `max_ortho` | `0.15` | Dérive latérale tolérée sur l'ensemble du balayage |
| `ortho_ratio` | `0.25` | Marge latérale supplémentaire proportionnelle au balayage, pour ne pas pénaliser les longues séries |
| `step_ortho_abs` | `0.02` | Déplacement latéral toléré sur un seul pas avant d'être lu comme un recadrage |
| `step_ortho_ratio` | `0.5` | La même limite, en fraction de la taille du pas |
| `hdr_min_span_stops` | `1.5` | Écart d'exposition au-delà duquel un balayage est un panorama HDR. Les balayages simples couvrent 0,0 à 0,7 IL, les HDR 2,0 à 4,4 |
| `sift_features` | `400` | Points caractéristiques par vignette. Le corpus est encore détecté à 250 ; 400 garde de la marge |
| `match_ratio` | `0.75` | Rapport de Lowe qu'une correspondance doit franchir pour être retenue |
| `workers` | `0` | Processus parallèles ; `0` choisit selon le nombre de cœurs. L'accélération reste en deçà du nombre de cœurs : le coût est dominé par les lectures aléatoires de vignettes |
| `probe_stride` | `8` | Nombre d'images entre les sondages rapides qui écartent les rafales ordinaires |
| `probe_min_drift` | `0.05` | Mouvement en deçà duquel un sondage déclare la série immobile |
| `max_run_frames` | `500` | Plus longue série mesurée. Un panoramique n'a jamais besoin d'autant d'images, et le plafond borne le cache de descripteurs par série (~220 Ko par image et par processus) |

Modifier ces valeurs ne change rien en soi — la détection est une passe par lots : relancez `--detect-panoramas` (ou l'action de relance dans la visionneuse) pour que le changement atteigne la galerie et le tri. Les modifier invalide aussi le repère incrémental : la passe suivante remesure toute la bibliothèque au lieu de réutiliser des étiquettes calculées avec les anciens seuils.

---

## Notation des rafales

Pondérations utilisées par le tri de rafales pour calculer un score composite afin de sélectionner la meilleure prise au sein de chaque groupe de rafale. La somme des pondérations doit faire 1,0.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `weight_aggregate` | `0.4` | Pondération du score agrégé global |
| `weight_aesthetic` | `0.25` | Pondération du score de qualité esthétique |
| `weight_sharpness` | `0.2` | Pondération du score de netteté technique |
| `weight_blink` | `0.15` | Pondération de pénalité pour les clignements détectés (plus élevée = pénalité plus forte) |

---

## Détection de doublons

Détecter les photos en double globalement à l'aide d'une comparaison par empreinte perceptuelle (pHash).

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `similarity_threshold_percent` | `90` | Filtre pHash strict (90 % = distance de Hamming <= 6 sur 64 bits) ; utilisé comme seul critère quand un embedding manque pour l'une des deux photos |
| `prefilter_hamming` | `12` | Surcharge optionnelle (absente du fichier livré). Filtre Hamming lâche de l'étape 1 pour l'ensemble candidat quand les deux photos ont des embeddings (forcé à être >= au filtre strict) |
| `embedding_cosine_threshold` | `0.90` | Surcharge optionnelle (absente du fichier livré). Filtre cosinus SigLIP/CLIP de l'étape 2 : un candidat à pHash lâche n'est fusionné que si le cosinus >= cette valeur |

La détection se fait en deux étapes : candidats pHash lâches (rappel) confirmés par un filtre cosinus d'embedding strict (précision). Les photos sans embedding retombent sur le critère strict pHash seul, donc le comportement est inchangé en l'absence d'embeddings.

Exécutez `python facet.py --detect-duplicates` pour détecter et regrouper les doublons. Exécutez `python facet.py --sweep-dedup-thresholds [labels.json]` pour évaluer le filtre cosinus — avec un fichier de labels JSON, il affiche un tableau précision/rappel, sinon la distribution des cosinus candidats et combien de collisions pHash strictes le filtre rejette.

---

## Niveau IQA étendu (optionnel)

Évaluateurs de qualité lourds/expérimentaux, **désactivés par défaut** et **jamais un remplacement de TOPIQ** — ils n'ajoutent des colonnes supplémentaires que lorsqu'ils sont explicitement activés. Lorsqu'ils sont activés, les évaluateurs étendus s'exécutent **pendant une analyse normale** et écrivent leurs propres colonnes ; une erreur de chargement/VRAM est journalisée et la colonne reste à `NULL` (l'analyse ne s'interrompt jamais).

```json
{
  "iqa_extended": {
    "qalign": "4bit",
    "aesthetic_v25": true,
    "deqa": false
  }
}
```

| Réglage | Défaut | Valeurs acceptées | Colonne | Description |
|---------|--------|-------------------|---------|-------------|
| `qalign` | `false` | `false` · `"4bit"` · `"8bit"` · `true`/`"full"` | `qalign_score` | IQA fondé sur un LLM Q-Align (basé sur pyiqa). `"4bit"` (~6-8 Go VRAM) est le choix pratique sur une carte 16 Go ; `"8bit"` ~12-14 Go ; pleine précision (`true`) requiert 16 Go+. Les modes 4/8 bits nécessitent `bitsandbytes`. |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (tête SigLIP, ~2 Go). Nécessite le paquet `aesthetic-predictor-v2-5`. |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16 Go+ ; ignoré et laissé à NULL sinon). |

**Installez les dépendances optionnelles** correspondant à ce que vous activez : `pip install -e .[iqa-extended]` (ajoute `aesthetic-predictor-v2-5` + `bitsandbytes`), ou décommentez les lignes correspondantes dans `requirements.txt`. Q-Align lui-même est livré avec `pyiqa` ; DeQA-Score se télécharge via `transformers`.

Lorsqu'elle est activée, chaque métrique est exposée à l'agrégat pondéré mais avec une pondération par défaut de 0, de sorte que `--recompute-average` reste identique au bit près jusqu'à ce que vous lui attribuiez une pondération. Exécutez `python facet.py --eval-iqa-srcc` pour mesurer la qualité du classement de votre photothèque par chaque métrique au regard de vos propres notes en étoiles.

**Affichage dans la visionneuse.** Lorsqu'une de ces colonnes est renseignée, la visionneuse affiche la valeur dans le panneau **Quality** du détail de la photo (`Q-Align`, `Aesthetic V2.5`, `DeQA`) et expose un curseur de plage correspondant dans la barre latérale de filtres de la galerie, sous **Extended Quality** (`min_qalign`/`max_qalign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`). Les photos analysées avant l'activation du niveau ont simplement `NULL` dans ces colonnes et ne sont pas affectées par les filtres.

**Robustesse.** DeQA-Score charge du code `trust_remote_code` distant dont la signature de forward varie selon les révisions de checkpoint ; son évaluateur est défensif — toute défaillance de prédiction (mauvaise signature, forme de sortie inattendue, OOM) est interceptée et le `deqa_score` de l'image reste à `NULL` au lieu de faire planter l'analyse.

---

## Détection des visages

Réglages de détection des visages InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `min_confidence_percent` | `65` | Confiance de détection minimale |
| `min_face_size` | `20` | Taille minimale du visage en pixels |
| `blink_ear_threshold` | `0.28` | Rapport d'aspect de l'œil (EAR) pour la détection de clignement |
| `min_faces_for_group` | `4` | Nombre minimal de visages pour classer en portrait de groupe (recalculé lors de `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Surcharge optionnelle (absente du fichier livré ; défaut du code `false`). Charge le module InsightFace `landmark_3d_68` pour l'extraction de la pose de tête (lacet/tangage/roulis). Coûte ~5 Mo de poids ONNX supplémentaires. Actuellement informatif ; de futurs affinements de profil/silhouette le liront. |
| `eyes_closed_max` | `4.0` | Score d'ouverture des yeux par visage (0–10) à ou en dessous duquel la chambre noire de tri signale un visage comme clignant. Pilote les anneaux de visage rouge/orange/vert et le curseur de seuil des yeux (déplacé depuis une constante codée en dur) |
| `poor_expression_min` | `4.0` | Score de sourire/expression par visage (0–10) en dessous duquel la chambre noire signale une expression faible. Pilote l'anneau de visage d'expression et le curseur (déplacé depuis une constante codée en dur) |
| `blendshapes.enabled` | `true` | Utilise les scores blendshapes de MediaPipe (basés sur l'apparence) pour `eyes_open_score` / `smile_score` par visage quand MediaPipe et le modèle `face_landmarker.task` sont disponibles ; quand `true`, ils remplacent les scores de géométrie des points de repère, sinon le repli géométrique s'exécute automatiquement. Dépendance optionnelle — installer avec `pip install mediapipe==0.10.35 --no-deps` (jamais un simple `pip install mediapipe`). Voir [FACE_RECOGNITION.md](FACE_RECOGNITION.md#signaux-dexpression-par-visage-yeux-ouverts--sourire). |
| `blendshapes.min_crop_size` | `192` | Les visages dont le recadrage rembourré est plus petit que cette valeur (px, côté le plus court) retombent sur le score géométrique plutôt que d'agrandir un visage minuscule |

---

## Regroupement des visages

Regroupement HDBSCAN pour la reconnaissance des visages.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Activer le regroupement des visages |
| `min_faces_per_person` | `2` | Nombre minimal de photos par personne |
| `min_samples` | `2` | Paramètre min_samples de HDBSCAN |
| `auto_merge_distance_percent` | `15` | Fusion automatique dans cette distance |
| `clustering_algorithm` | `"best"` | Algorithme HDBSCAN |
| `leaf_size` | `40` | Taille des feuilles de l'arbre (CPU uniquement) |
| `use_gpu` | `"auto"` | Mode GPU : `auto`, `always`, `never` |
| `merge_threshold` | `0.6` | Similarité de centroïde pour la correspondance |

**Algorithmes de regroupement :**

| Algorithme | Complexité | Idéal pour |
|------------|------------|------------|
| `boruvka_balltree` | O(n log n) | Données de haute dimension (recommandé) |
| `boruvka_kdtree` | O(n log n) | Données de faible dimension |
| `prims_balltree` | O(n²) | Mémoire limitée, haute dimension |
| `prims_kdtree` | O(n²) | Mémoire limitée, faible dimension |
| `best` | Auto | Laisser HDBSCAN décider |

---

## Traitement des visages

Contrôle l'extraction des visages et la génération de vignettes.

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `crop_padding` | `0.3` | Ratio de marge pour les recadrages de visage |
| `use_db_thumbnails` | `true` | Utiliser les vignettes stockées |
| `face_thumbnail_size` | `640` | Taille de la vignette en pixels |
| `face_thumbnail_quality` | `90` | Qualité JPEG |
| `extract_workers` | `2` | Workers d'extraction parallèles |
| `extract_batch_size` | `16` | Taille de lot d'extraction |
| `refill_workers` | `4` | Workers de regénération de vignettes |
| `refill_batch_size` | `100` | Taille de lot de regénération |
| **auto_tuning** | | |
| `enabled` | `true` | Activer le réglage fondé sur la mémoire |
| `memory_limit_percent` | `80` | Limite d'utilisation de la mémoire |
| `min_batch_size` | `8` | Taille minimale de lot |
| `monitor_interval_seconds` | `5` | Intervalle de vérification |

---

## Détection monochrome

Détection des photos en noir et blanc.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `saturation_threshold_percent` | `5` | Saturation moyenne < 5 % = monochrome |

---

## Étiquetage

Réglages généraux d'étiquetage. Le modèle d'étiquetage est configuré par profil dans `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Activer l'étiquetage |
| `max_tags` | `5` | Nombre maximal d'étiquettes par photo |

**Note :** les réglages spécifiques à CLIP comme `similarity_threshold_percent` se trouvent dans la section `models.clip`.

### Modèles d'étiquetage disponibles

Configurés via `models.profiles.*.tagging_model` :

| Modèle | VRAM | Style d'étiquette | Notes |
|--------|------|-------------------|-------|
| `clip` | 0 (réutilise les embeddings) | Ambiance/atmosphère (dramatic, golden_hour, vintage) | Aucun chargement de modèle supplémentaire ; détection d'objets moins littérale |
| `qwen3.5-2b` | ~4 Go | Scènes structurées (landscape, architecture, reflection) | Nécessite transformers + VRAM supplémentaire |
| `qwen3.5-4b` | ~8 Go | Scènes détaillées avec nuance | VRAM plus élevée ; inférence plus lente |

### Modèles d'étiquetage par défaut selon le profil

| Profil | Modèle d'étiquetage | Modèle d'embedding |
|--------|---------------------|--------------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768 dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768 dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152 dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152 dim) |

### Ré-étiquetage des photos

```bash
python facet.py --recompute-tags       # Ré-étiqueter avec le modèle configuré par profil
python facet.py --recompute-tags-vlm   # Ré-étiqueter avec le tagger VLM
```

---

## Étiquettes autonomes

Étiquettes avec listes de synonymes qui ne sont liées à aucune catégorie spécifique. Elles sont disponibles pour toutes les photos, quelle que soit l'attribution de catégorie. Chaque clé est le nom de l'étiquette ; la valeur est une liste de synonymes pour la correspondance CLIP/VLM.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Ajoutez de nouvelles étiquettes autonomes en fournissant une clé et une liste de synonymes. Les étiquettes définies ici sont fusionnées avec les étiquettes spécifiques aux catégories pour former le vocabulaire complet d'étiquettes.

---

## Analyse

Seuils pour `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `aesthetic_max_threshold` | `9.0` | Avertir si l'esthétique maximale est en dessous |
| `aesthetic_target` | `9.5` | Cible pour aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Seuil de qualité « haute valeur » |
| `quality_weight_threshold_percent` | `10` | Avertir si la pondération de qualité ≤ cette valeur |
| `correlation_dominant_threshold` | `0.5` | Avertissement « signal dominant » |
| `category_min_samples` | `50` | Nombre minimal de photos par catégorie |
| `category_imbalance_threshold` | `0.5` | Avertissement d'écart de score |
| `score_clustering_std_threshold` | `1.0` | Avertir si l'écart-type < cette valeur |
| `top_score_threshold` | `8.5` | Avertir si l'agrégat maximal < cette valeur |
| `exposure_avg_threshold` | `8.0` | Avertir si l'exposition moyenne > cette valeur |

---

## Visionneuse

Affichage et comportement de la galerie web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "hover",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Note :** `sort_options` (élidé en `{ ... }` ci-dessus) associe les colonnes de la base aux libellés du menu déroulant et est rarement modifié. Le groupe **Content** inclut un tri `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (les NULL sont relégués en dernier).

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `default_category` | `""` | Filtre de catégorie par défaut |
| `edition_password` | `""` | Mot de passe pour déverrouiller le mode édition (vide = désactivé) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Minimum pour l'optimisation |
| `pair_selection_strategy` | `"learning"` | Stratégie de paires : `learning` (démarrage à froid par diversité d'embeddings + désaccord de rang une fois entraîné), `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Bassin candidat aléatoire au sein duquel la stratégie `learning` échantillonne les paires |
| `show_current_scores` | `true` | Afficher les scores pendant la comparaison |
| **pagination** | | |
| `default_per_page` | `64` | Photos par page |
| **dropdowns** | | |
| `max_cameras` | `50` | Nombre maximal d'appareils dans le menu déroulant |
| `max_lenses` | `50` | Nombre maximal d'objectifs |
| `max_persons` | `50` | Nombre maximal de personnes |
| `max_tags` | `20` | Nombre maximal d'étiquettes |
| `min_photos_for_person` | `10` | Masquer du menu déroulant les personnes ayant moins de photos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | face_count minimal pour qu'un cluster auto-regroupé apparaisse dans la section « À nommer » de `/persons` |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nom du binaire darktable-cli ou chemin absolu |
| `darktable.profiles` | `[]` | Tableau de profils d'export darktable nommés (voir ci-dessous) |
| `darktable.profiles[].name` | *(requis)* | Nom d'affichage du profil (utilisé dans le menu de téléchargement et le paramètre API `profile`) |
| `darktable.profiles[].hq` | `true` | Passe `--hq true` pour un export haute qualité |
| `darktable.profiles[].width` | *(omettre)* | Largeur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].height` | *(omettre)* | Hauteur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].style` | *(omettre)* | Nom du style darktable appliqué lors de l'export (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | Lorsque `false`, passe `--apply-custom-presets false` afin que seul le `style` explicite soit rendu (et non les préréglages auto-appliqués) |
| `darktable.profiles[].extra_args` | `[]` | Arguments CLI supplémentaires (par ex. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Styles darktable nommés proposés comme aperçus développés dans le studio de tri (`GET /api/photo/cull_preview`). Vide = le sélecteur de style est masqué. Chaque style **doit déjà exister** dans la configuration darktable de l'utilisateur qui exécute la visionneuse. Le nom est transmis tel quel à `--style`. |
| `darktable.cull_styles[].name` | *(requis)* | Nom du style darktable (transmis à `--style` et validé par l'endpoint) |
| `darktable.cull_styles[].label_key` | *(name)* | Clé i18n facultative pour le libellé du menu (par défaut le nom du style) |
| `darktable.preview_max_edge` | `1440` | Bord maximal (px) du rendu de l'aperçu de tri |
| `darktable.preview_timeout_seconds` | `60` | Délai d'attente darktable-cli par rendu d'aperçu |
| **display** | | |
| `tags_per_photo` | `4` | Étiquettes affichées sur les cartes |
| `card_width_px` | `168` | Largeur de la carte |
| `image_width_px` | `160` | Largeur de l'image |
| `image_jpeg_quality` | `96` | Qualité JPEG pour la conversion RAW/HEIF dans `/api/download` et `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Taille minimale de vignette (px) |
| `thumbnail_slider.max_px` | `400` | Taille maximale de vignette (px) |
| `thumbnail_slider.default_px` | `168` | Taille de vignette par défaut (px) |
| `thumbnail_slider.step_px` | `8` | Pas d'incrément du curseur (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Taille de vignette |
| `jpeg_quality` | `80` | Qualité JPEG |
| `crop_padding_ratio` | `0.2` | Marge du visage |
| `min_crop_size_px` | `20` | Taille minimale de recadrage |
| **quality_thresholds** | | |
| `good` | `6` | Seuil « bon » |
| `great` | `7` | Seuil « très bon » |
| `excellent` | `8` | Seuil « excellent » |
| `best` | `9` | Seuil « meilleur » |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimum pour Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Ratio de visage pour les pondérations |
| `low_light_max_luminance` | `0.2` | Seuil de faible luminosité |
| **defaults** | | |
| `type` | `""` | Filtre de type de photo par défaut (par ex. `"portraits"`, `"landscapes"`, ou `""` pour Toutes) |
| `sort` | `"aggregate"` | Colonne de tri par défaut |
| `sort_direction` | `"DESC"` | Sens de tri par défaut (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Masquer les photos avec clignement par défaut |
| `hide_bursts` | `true` | Afficher uniquement la meilleure de chaque rafale par défaut |
| `hide_duplicates` | `true` | Masquer les doublons non principaux par défaut |
| `hide_brackets` | `true` | Afficher uniquement l'exposition de base de chaque bracketing par défaut |
| `hide_panoramas` | `true` | N'afficher qu'une image représentative par panorama par défaut |
| `hide_details` | `true` | Masquer les détails des photos sur les cartes par défaut |
| `tooltip_mode` | `"hover"` | Déclencheur d'infobulle : `"hover"`, `"click"` ou `"off"`. Remplace l'ancien booléen `hide_tooltip`. |
| `hide_rejected` | `true` | Masquer les photos rejetées par défaut |
| `gallery_mode` | `"mosaic"` | Disposition de galerie par défaut (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origines CORS autorisées pour le serveur FastAPI. Ajoutez votre domaine ou l'URL de votre reverse proxy en cas d'hébergement distant. |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(valeur par défaut compatible SPA)_ | Valeur de l'en-tête Content-Security-Policy. Par défaut, une politique autorisant les ressources propres de la SPA (script/style de thème inline, Google Fonts, tuiles OpenStreetMap, API de même origine). Mettre `""` pour désactiver, ou fournir une politique plus stricte. |
| `security_headers.hsts` | `false` | Envoyer `Strict-Transport-Security`. À activer uniquement lorsque la visionneuse est servie en HTTPS. |
| **Autres** | | |
| `cache_ttl_seconds` | `3600` | TTL des caches de statistiques/requêtes en mémoire. Le calcul des statistiques sur toute la bibliothèque peut prendre plusieurs minutes, donc un TTL plus court que ce calcul empêche tout succès de cache |
| `notification_duration_ms` | `2000` | Durée des notifications toast |
| `moment_confidence_min` | `0` | En dessous de ce postérieur `narrative_moment_confidence` stocké (0–1), les libellés de moment sont affichés atténués avec un suffixe « (uncertain) » dans l'en-tête Scènes, l'en-tête du groupe de scène du tri (Culling) et l'infobulle photo de la galerie. `0` = jamais atténué |

### Fonctionnalités

Activez ou désactivez des fonctionnalités optionnelles pour réduire l'utilisation mémoire ou simplifier l'interface :

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_rating_badge": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `show_similar_button` | `true` | Afficher le bouton « Trouver des similaires » sur les cartes photo (utilise numpy pour la similarité CLIP) |
| `show_merge_suggestions` | `true` | Activer la fonctionnalité de suggestions de fusion sur la page de gestion des personnes |
| `show_rating_controls` | `true` | Afficher les commandes de notation par étoiles et de favori |
| `show_rating_badge` | `true` | Afficher le badge de notation sur les cartes photo |
| `show_scan_button` | `false` | Afficher le bouton de déclenchement d'analyse pour les superadmins (nécessite un GPU sur l'hôte de la visionneuse) |
| `metrics_enabled` | `false` | Activer le point d'accès public Prometheus `GET /metrics`. Désactivé par défaut — il expose les nombres de photos/personnes/visages, la taille de la base et la mémoire du processus ; à n'activer que lorsque le point d'accès est joignable depuis le réseau du collecteur, et non depuis Internet public. |
| `show_semantic_search` | `true` | Afficher la barre de recherche sémantique (recherche texte-vers-image via les embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Afficher la fonctionnalité d'albums (créer, gérer et parcourir des albums photo) |
| `show_critique` | `true` | Afficher le bouton de critique IA sur les cartes photo (décomposition de score fondée sur des règles) |
| `show_vlm_critique` | `true` | Activer le mode de critique propulsé par VLM (nécessite un profil VRAM 16gb/24gb). Le code retombe sur `false` quand la clé est absente. |
| `show_embed_metadata` | `true` | Afficher l'action « Écrire les métadonnées dans le fichier » par vignette en mode édition (intègre notes/mots-clés dans l'image originale via exiftool) |
| `show_memories` | `true` | Afficher la boîte de dialogue souvenirs « Ce jour-là » (photos prises à la même date les années précédentes) |
| `show_captions` | `true` | Afficher les légendes générées par IA sur les cartes photo |
| `show_timeline` | `true` | Afficher la vue chronologique pour un parcours chronologique avec navigation par date |
| `show_map` | `true` | Afficher la vue carte avec les emplacements GPS des photos (nécessite Leaflet). Le code retombe sur `false` quand la clé est absente. |
| `show_capsules` | `true` | Afficher la vue Capsules (diaporamas de photos sélectionnées regroupées par thème) |
| `show_folders` | `true` | Afficher le parcours par dossiers de la structure de répertoires photo |
| `show_scenes` | `true` | Afficher la vue Scènes (`/scenes`) qui regroupe les photos de tête de rafale en scènes chronologiques pour un tri dans l'ordre du récit |
| `show_my_taste` | `true` | Afficher le tri « My Taste » fondé sur le score appris du classeur personnel, avec un badge de confiance couverture-apprise / précision |
| `show_social_export` | `true` | Affiche le menu **Recadrage social** (réservé à l'édition) : recadrages sensibles au sujet pour les formats des réseaux sociaux. Voir [Export social](#export-social) |
| `show_portfolio_export` | `true` | Affiche l'action d'album **Exporter le portfolio** (réservée à l'édition) : galerie HTML statique autonome. Voir [Export de portfolio](#export-de-portfolio) |
| `show_proofing` | `false` | Active l'épreuvage client sur les albums partagés : un lien de partage (plus un code PIN facultatif) permet à un client sans compte de mettre un cœur aux photos et de laisser des commentaires, que le propriétaire de l'album examine depuis une boîte de dialogue réservée à l'édition. Désactivé par défaut. Voir [Épreuvage client](#client-proofing) |

**Optimisation mémoire :** définir `show_similar_button: false` empêche le chargement de numpy, réduisant l'empreinte mémoire de la visionneuse. La fonctionnalité de photos similaires calcule la similarité cosinus des embeddings CLIP, ce qui nécessite numpy.

### Épreuvage client

`viewer.features.show_proofing` (par défaut `false`) transforme n'importe quel album partagé en surface d'épreuvage client. Un lien de partage — éventuellement protégé par `viewer.proofing.pin` — permet à un client sans compte d'échanger le jeton de partage contre une session éphémère, puis de mettre un cœur aux photos et de laisser des commentaires. Les sélections vivent dans une table dédiée `album_client_picks`, limitées aux photos de cet album et totalement isolées des notes du propriétaire (elles ne touchent jamais `photos.is_favorite` / `user_preferences` et n'entraînent jamais le classeur personnel). Le propriétaire lit les sélections depuis une boîte de dialogue réservée à l'édition sur la carte de l'album.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `features.show_proofing` | `false` | Interrupteur principal de l'épreuvage client sur les albums partagés |
| `proofing.pin` | `""` | Code PIN facultatif qu'un client doit saisir (avec le jeton de partage) pour ouvrir une session d'épreuvage. Vide = aucun PIN. Les vérifications sont limitées en débit et sûres au niveau des octets |
| `proofing.session_minutes` | `1440` | Durée de vie en minutes d'un jeton de session d'épreuvage client (par défaut 24 h). Les sessions s'arrêtent aussi dès que l'album n'est plus partagé ou que l'épreuvage est désactivé |

### Mappage de chemins

Associer les chemins de la base à des chemins du système de fichiers local. Utile lorsque les photos ont été notées sur une machine (par ex. Windows avec des chemins UNC) mais que la visionneuse s'exécute sur une autre (par ex. un NAS Linux avec des points de montage).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `path_mapping` | `{}` | Dictionnaire de préfixe source vers préfixe de destination. Lors du service d'images en pleine taille ou de la critique VLM, les chemins de la base commençant par un préfixe source sont réécrits pour utiliser le préfixe de destination. |

**Fonctionnement :**
- Ne s'applique que lors de la **lecture de fichiers depuis le disque** (service d'images en pleine taille, téléchargements de fichiers, critique VLM). Les chemins de la base ne sont jamais modifiés.
- La normalisation barre oblique inverse/barre oblique est gérée automatiquement : `\\NAS\Photos\img.jpg` et `//NAS/Photos/img.jpg` correspondent tous deux.
- Les mappages sont évalués dans l'ordre ; le premier préfixe correspondant l'emporte.
- Les cibles de mappage de chemins sont automatiquement incluses dans la liste blanche des répertoires d'analyse pour les contrôles de sécurité multi-utilisateurs.

**Exemple :** une base remplie sous Windows stocke des chemins comme `\\NAS\Photos\2024\IMG_001.jpg`. Sous Linux, le même partage est monté sur `/mnt/nas/Photos`. Configurez :

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protection par mot de passe

Protection par mot de passe optionnelle pour la visionneuse :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Lorsqu'il est défini, les utilisateurs doivent s'authentifier avant d'accéder à la visionneuse.

### Performance de la visionneuse

Surcharger les réglages globaux `performance` lors de l'exécution de la visionneuse. Utile pour un déploiement NAS à faible mémoire où la notation a besoin de ressources élevées mais pas la visionneuse.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mmap_size_mb` | *(global)* | Surcharge de la taille mmap SQLite pour les connexions de la visionneuse. `0` désactive mmap. |
| `cache_size_mb` | *(global)* | Surcharge de la taille du cache SQLite pour les connexions de la visionneuse |
| `pool_size` | `5` | Taille du pool de connexions (réduire pour les systèmes à faible mémoire) |
| `thumbnail_cache_size` | `2000` | Nombre maximal d'entrées dans le cache de redimensionnement de vignettes en mémoire |
| `face_cache_size` | `500` | Nombre maximal d'entrées dans le cache de vignettes de visages en mémoire |

Lorsqu'ils ne sont pas définis, la visionneuse utilise les valeurs `performance` globales. Voir [Déploiement](DEPLOYMENT.md) pour les réglages NAS recommandés.

---

## Performance

Réglages de performance de la base de données.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

> **Note :** `wal_checkpoint_minutes` est une surcharge optionnelle et **n'est pas** présente dans le bloc `performance` livré (qui ne contient que `mmap_size_mb`, `cache_size_mb` et `slow_request_ms`). Ajoutez-le explicitement pour changer la valeur par défaut de `30`.

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mmap_size_mb` | `2048` | Taille des E/S mappées en mémoire SQLite |
| `cache_size_mb` | `128` | Taille du cache SQLite |
| `wal_checkpoint_minutes` | `30` | Surcharge optionnelle (absente du fichier livré). Intervalle en minutes du `PRAGMA wal_checkpoint(TRUNCATE)` en arrière-plan de la visionneuse. Empêche le gonflement du WAL sur les déploiements de longue durée. Mettre `0` pour désactiver. |
| `slow_request_ms` | `1000` | Les requêtes de l'API de la visionneuse plus lentes que ce nombre de millisecondes sont journalisées en WARNING avec un marqueur `SLOW`. Mettre `0` pour désactiver. |

---

## Stockage

Contrôle l'emplacement de stockage des vignettes et des embeddings. Par défaut, des colonnes BLOB dans la base SQLite ; le mode système de fichiers les stocke à la place sous forme de fichiers sur disque, ce qui réduit la taille de la base.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mode` | `"database"` | Backend de stockage : `"database"` (BLOBs SQLite) ou `"filesystem"` (fichiers sur disque) |
| `filesystem_path` | `"./storage"` | Répertoire de base pour le mode système de fichiers. Les vignettes sont stockées dans `<path>/thumbnails/` et les embeddings dans `<path>/embeddings/`, organisés en sous-répertoires par empreinte de contenu. |

**Détails du mode système de fichiers :**
- Les fichiers sont organisés par empreinte SHA-256 du chemin de la photo, avec des sous-répertoires à deux caractères pour éviter d'avoir trop de fichiers dans un seul répertoire (par ex. `thumbnails/a3/a3f8..._640.jpg`).
- Supprimer une photo supprime toutes les tailles de vignettes et fichiers d'embeddings associés.
- Le répertoire est créé automatiquement à la première utilisation.

---

## Plugins

Système de plugins événementiel pour réagir aux événements de notation. Les plugins peuvent être des modules Python, des webhooks ou des actions intégrées.

### Configuration

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Clé | Défaut | Description |
|-----|--------|-------------|
| `enabled` | `false` | Interrupteur principal — lorsque false, aucun événement n'est émis |
| `high_score_threshold` | `8.0` | Score agrégé minimal pour déclencher les événements `on_high_score` |
| `webhooks` | `[]` | Liste des points d'accès webhook recevant des charges utiles JSON POST |
| `actions` | `{}` | Actions intégrées nommées déclenchées par des événements |

### Événements pris en charge

| Événement | Déclencheur | Charge utile |
|-----------|-------------|--------------|
| `on_score_complete` | Après la notation de chaque photo | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Quand une photo entre dans la base | Identique à `on_score_complete` |
| `on_high_score` | Quand l'agrégat ≥ `high_score_threshold` | Identique à `on_score_complete` |
| `on_burst_detected` | Quand un groupe de rafale est identifié | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Écrire un plugin

Placez un fichier `.py` dans le répertoire `plugins/`. Définissez des fonctions nommées d'après les événements que vous souhaitez gérer :

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Voir `plugins/example_plugin.py.example` pour l'interface complète.

### Webhooks

Chaque webhook reçoit un POST JSON avec protection SSRF (les adresses privées/loopback sont bloquées) :

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Options de webhook : `url` (requis), `events` (liste de noms d'événements), `min_score` (agrégat minimal pour déclencher).

### Actions intégrées

| Action | Description | Options |
|--------|-------------|---------|
| `copy_to_folder` | Copier la photo dans un dossier | `folder`, `min_score` |
| `send_notification` | Journaliser une notification | `min_score` |

### Points d'accès de l'API

| Méthode | Chemin | Description |
|---------|--------|-------------|
| `GET` | `/api/plugins` | Lister les plugins, webhooks et actions chargés |
| `POST` | `/api/plugins/test-webhook` | Envoyer une charge utile de test à une URL de webhook |

---

## Capsules

Diaporamas de photos sélectionnées regroupées par thème. Les capsules sont générées automatiquement à partir de votre photothèque et mises en cache avec un TTL configurable.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Réglages globaux

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `min_aggregate` | `6.0` | Score agrégé minimal pour qu'une photo soit incluse dans les capsules |
| `max_photos_per_capsule` | `40` | Nombre maximal de photos par capsule (diversité MMR appliquée au-delà de 5) |
| `max_photo_overlap` | `0.2` | Fraction maximale de photos partagées entre deux capsules avant que la déduplication n'en supprime une |
| `mmr_lambda` | `0.5` | Pondération de diversité MMR : 0 = maximiser la diversité, 1 = maximiser la qualité |
| `mmr_moment_weight` | `0.0` | Pondération optionnelle intégrant le `narrative_moment_confidence` de chaque photo dans la sélection MMR des capsules. `0.0` = comportement inchangé |
| `freshness_hours` | `24` | TTL du cache et période de rotation des photos de couverture et des capsules graines |
| `reverse_geocoding` | `true` | Activer le géocodage inverse hors ligne pour les titres des capsules de lieu/voyage (nécessite le paquet `reverse_geocoder`) |

### Types de capsules

| Type | Description |
|------|-------------|
| `journey` | Voyages détectés via le regroupement GPS + écarts temporels. Les titres incluent le nom de la destination lorsque le géocodage est activé. |
| `faces_of` | Meilleures photos de chaque personne reconnue |
| `seasonal` | Photos regroupées par saison + année |
| `golden` | Top 1 % par score agrégé |
| `color_story` | Groupes visuellement similaires via le regroupement des embeddings CLIP |
| `this_week` | « Cette semaine, il y a des années » — extension de Ce jour-là sur ±3 jours |
| `location` | Clusters de photos géolocalisées avec noms de lieux géocodés en inverse |
| `person_pair` | Paires de personnes nommées apparaissant ensemble |
| `seeded` | Découverte à base de graines via le temps, la similarité, la personne, l'étiquette, le lieu, l'ambiance |
| `progress` | « Votre photographie s'améliore » à partir des tendances de score trimestrielles |
| `color_palette` | « Couleur du mois » à partir des profils de saturation/monochrome |
| `rare_pair` | Paires de personnes peu fréquentes dans les photos bien notées |
| `favorites` | Photos favorites regroupées par année et saison |

### Capsules fondées sur des dimensions

Générées automatiquement à partir des colonnes de la base :

| Dimension | Regroupe par |
|-----------|--------------|
| `year` | Année extraite de date_taken |
| `month` | Année-mois extraits de date_taken |
| `week` | Année-semaine extraites de date_taken |
| `camera` | Modèle d'appareil |
| `lens` | Modèle d'objectif |
| `tag` | Étiquettes de photo (nécessite la table `photo_tags`) |
| `day_of_week` | Jour de la semaine (dimanche–samedi) |
| `composition` | Motif de composition SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Tranches de focale : ultra grand-angle (<24 mm), grand-angle (24–35 mm), standard (36–70 mm), portrait (71–135 mm), téléobjectif (136–300 mm), super téléobjectif (300 mm+) |
| `category` | Catégorie de contenu de la photo (portrait, paysage, rue, etc.) |
| `time_of_day` | Tranches horaires : matin doré, matin, midi, après-midi, soir doré, nuit |
| `star_rating` | Notes en étoiles de l'utilisateur (1–5 étoiles) |

Des combos transversaux sont également générés (par ex. appareil × année, focal_range × category, category × year).

### Transitions du diaporama

Chaque type de capsule correspond à une transition de diapositive thématique :

| Transition | Utilisée par | Effet |
|-----------|--------------|-------|
| `crossfade` | Par défaut | Échange d'opacité en 300 ms |
| `slide` | journey, location, this_week | Glissement depuis la droite (500 ms) |
| `zoom` | faces_of, color_story | Échelle 1,05→1,0 avec fondu (400 ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lent 1,0→1,08 sur la durée de la diapositive |

### Géocodage inverse

Les capsules de lieu et de voyage utilisent le géocodage inverse hors ligne via le paquet `reverse_geocoder` (jeu de données GeoNames local, ~30 Mo, aucun appel API). Les résultats sont mis en cache dans la table `location_names` de la base à une résolution de grille de 0,1° (~11 km).

Installer : `pip install reverse_geocoder`

Mettez `"reverse_geocoding": false` pour désactiver et revenir à l'affichage des coordonnées.

## Groupes de similarité

Réglages pour la fonctionnalité de tri IA des photos similaires, qui regroupe les photos visuellement similaires à l'aide des embeddings CLIP/SigLIP :

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `default_threshold` | `0.85` | Similarité cosinus minimale (0,0–1,0) pour considérer deux photos comme visuellement similaires. Des valeurs plus basses produisent des groupes plus grands mais avec moins de similarité visuelle. |
| `min_group_size` | `2` | Nombre minimal de photos requis pour former un groupe de similarité |
| `max_photos` | `10000` | Nombre maximal de photos chargées pour le calcul de similarité (coût en O(n²)). Augmentez pour les photothèques plus grandes au prix du temps de calcul. |
| `max_group_size` | `50` | Nombre maximal de photos par groupe de similarité. Les groupes plus grands sont scindés pour garder l'interface utilisable. |

## Tri automatique

Tri automatique en un bouton pour la chambre noire de tri (`POST /api/culling/auto`, réservé à l'édition). Il trie toute une portée — tous les groupes, ou seulement les rafales / similaires / scènes, éventuellement restreinte à un album ou une fenêtre de dates — en une seule passe. Chaque groupe conserve sa meilleure photo plus tout ce qui se trouve dans une marge dérivée de la rigueur (le même budget de conservation que le curseur manuel de la chambre noire), avec un plancher par groupe, et rejette le reste.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `default_strictness` | `50` | Budget de conservation (0–100) utilisé lorsque la requête omet `strictness`. Plus élevé = conserver moins de photos par groupe (marge plus serrée autour de la meilleure du groupe) |
| `highlights_min` | `8.0` | Score agrégé minimal pour que la meilleure photo d'un groupe soit rassemblée dans l'album **Highlights** facultatif lorsqu'un tri automatique est appliqué (idempotent) |

`dry_run` est activé par défaut et renvoie un aperçu conservation/rejet par groupe ; une application enregistre en plus des lignes de comparaison `source='culling'` et déclenche un ré-entraînement automatique. Voir [Visionneuse web — Tri automatique](VIEWER.md#auto-cull).

## Ré-entraînement automatique

Contrôle le moment où le classeur personnel (« Mes goûts ») se ré-entraîne. Chaque confirmation de tri et chaque changement de note incrémente un compteur par utilisateur de « nouvelles comparaisons depuis le dernier entraînement » ; le franchissement de `threshold` arme une minuterie d'inactivité, et le ré-entraînement ne démarre qu'après `idle_seconds` sans activité de votre part.

Cette fenêtre d'inactivité est essentielle : le ré-entraînement réécrit une ligne par photo, et SQLite n'autorise qu'un seul écrivain par fichier de base. Un déclenchement en pleine série le mettrait en concurrence avec vos propres écritures de notation — c'est précisément ainsi qu'un long ré-entraînement faisait échouer les actions de notation. Attendre une pause sépare les deux.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `threshold` | `25` | Nombre de nouvelles comparaisons qu'un utilisateur doit accumuler avant qu'un ré-entraînement soit armé. À augmenter si vous notez de très gros lots et souhaitez amortir le coût de l'entraînement (CPU, de quelques secondes à quelques minutes) sur davantage de signal |
| `idle_seconds` | `60` | Secondes sans activité de notation/tri requises avant que le ré-entraînement armé ne démarre réellement. Chaque nouvelle action repousse la minuterie. `0` déclenche immédiatement (comportement antérieur à la 1.7.3) |

Les deux sont surchargeables à l'exécution par des variables d'environnement, prioritaires sur les valeurs JSON — utile sous Docker, où la configuration est souvent intégrée à l'image :

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variable | Surcharge |
|----------|-----------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

Une valeur illisible retombe sur le réglage JSON, et un bloc absent ou mal formé retombe sur les valeurs par défaut intégrées : une faute de frappe dégrade donc vers le comportement livré au lieu de désactiver le ré-entraînement automatique. Les deux valeurs sont lues une seule fois au démarrage — les modifier nécessite un redémarrage.

Le ré-entraînement conserve son verrou de validation croisée sur données réservées : une exécution qui ne bat pas la référence actuelle n'écrit rien.

## Profils de tri par genre

Préréglages par genre qui regroupent tous les réglages de tri en un clic : le sport ne garde que la photo la plus nette d'une longue rafale, les mariages conservent plus de variantes avec les yeux ouverts prioritaires, les concerts assouplissent les seuils yeux/expression, l'animalier supprime totalement le filtre de visage humain. La chambre noire de tri affiche un sélecteur de préréglage.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Réglage | Description |
|---|---|
| `default` | Id de profil appliqué quand aucun n'est mémorisé côté client |
| `profiles.<id>.label_key` | Chemin i18n du nom affiché du préréglage (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Budget de conservation (0–100) injecté dans la marge d'auto-tri quand ce préréglage est actif |
| `profiles.<id>.eyes_closed_max` | Score yeux ouverts (0–10) en dessous duquel un visage est considéré fermé — remplace `face_detection.eyes_closed_max` dans les badges de visage |
| `profiles.<id>.poor_expression_min` | Score d'expression/sourire (0–10) en dessous duquel un visage est jugé médiocre — remplace `face_detection.poor_expression_min` |
| `profiles.<id>.keep_min_per_group` | Plancher par groupe sur l'ensemble conservé par l'auto-tri |
| `profiles.<id>.similarity_threshold` | Seuil de regroupement par similarité (pourcentage) appliqué quand le préréglage est sélectionné |

Point d'accès (en lecture seule) : `GET /api/culling/profiles` renvoie la liste ordonnée des préréglages et le défaut. La requête d'auto-tri (`POST /api/culling/auto`) et le lot par visage (`POST /api/culling-group/faces`) acceptent un `profile` optionnel ; un `strictness`/`min_keep_per_group` explicite dans la requête l'emporte toujours sur le préréglage.

## Scènes

Réglages pour la vue Scènes, qui regroupe les photos de tête de rafale en scènes chronologiques (séparées par les écarts de temps de capture) pour un tri dans l'ordre du récit :

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `gap_minutes` | `20.0` | Une nouvelle scène commence lorsque plus de ce nombre de minutes s'écoule entre deux photos de tête de rafale consécutives (le plancher quand `adaptive` est activé) |
| `min_size` | `2` | Nombre minimal de photos pour qu'une scène soit affichée |
| `max_photos` | `5000` | Nombre maximal de photos de tête de rafale chargées pour le regroupement en scènes |
| `max_scene_size` | `60` | Une scène plus grande est sous-scindée récursivement à ses plus grands écarts internes, afin qu'un événement photographié en continu ne s'effondre jamais en une seule scène géante |
| `adaptive` | `true` | Lorsqu'il est activé, l'écart effectif s'élargit à `adaptive_k × médiane` des écarts consécutifs de la séance (se resserre pour les prises rapides, s'élargit pour les vacances clairsemées) |
| `adaptive_k` | `6.0` | Multiplicateur appliqué à l'écart médian lorsque `adaptive` est activé |
| `split_on_moment_change` | `false` | Lorsqu'il est activé (et que les moments narratifs sont calculés), sous-scinder une série temporelle où le moment dominant change et se maintient pendant `moment_split_min_run` images |
| `moment_split_min_run` | `4` | Hystérésis pour `split_on_moment_change` — nombre d'images consécutives durant lesquelles un nouveau moment doit persister pour forcer une frontière |

## Moments narratifs

Étiquetage zero-shot du « moment » scène/activité de chaque photo. Le vocabulaire **general** par défaut couvre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle`, ou `other` — il fonctionne donc sur n'importe quelle bibliothèque, pas seulement les mariages (`wedding` est fourni comme genre activable à la demande). Renseigné par `--detect-moments` (s'exécute automatiquement à la fin de chaque analyse) et exposé comme noms de scènes et filtre de galerie. Quelque chose que ni Narrative Select ni AfterShoot ne font.

Le signal repose sur la **sémantique de la légende** : la légende IA de chaque photo est encodée une seule fois avec la tour textuelle et stockée (la colonne `caption_embedding`) ; le moment est le meilleur cosinus **max-pooled** de cet embedding de légende au regard des prompts textuels par moment. L'embedding d'image stocké sert de repli lorsqu'une photo n'a pas de légende. Le texte des légendes correspond aux prompts de moment ~2,4× plus nettement que l'embedding d'image brut, si bien que le signal `caption` porte des seuils plus élevés que le repli `image` ; chacun est ajusté par backend (les cosinus open_clip sont bien plus bas que ceux de SigLIP). Les valeurs `transformers` (SigLIP) sont fournies comme valeurs par défaut conservatrices — réajustez-les si vous utilisez un profil SigLIP.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": { "enabled": true, "weight": 0.04 },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Interrupteur principal ; lorsque désactivé, `--detect-moments` et le hook d'analyse ne font rien |
| `prompt_template` | `"a photo of {desc}"` | Enveloppe appliquée à chaque prompt avant l'encodage |
| `default_event_type` | `"general"` | Quel vocabulaire `event_types` est actif. `general` = 20 moments scène/activité agnostiques ; `wedding` est fourni comme genre activable à la demande |
| `pooling` | `"max"` | Score par moment = le meilleur cosinus de prompt unique (max-pool), plus discriminant que la moyenne |
| `caption_min_confidence` | `0` | Filtre de qualité de légende : lorsque > 0, `--generate-captions` et le point d'accès de légende à la demande ignorent les photos non étiquetées, `other`, ou en dessous de cette confiance de moment stockée. `0` = aucun filtre |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | En dessous de ce cosinus top-1, une photo est `other`. Indexé par **signal** (`caption` vs `image`) puis par backend — les cosinus de légende sont ~2,4× plus élevés |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Écart cosinus minimal top-1/top-2 ; en dessous, l'image est `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Coups de pouce L1 visage/étiquette qui ne départagent que les quasi-égalités ; `weight` plafonne chaque ajustement à l'échelle cosinus |
| `priors.caption_tag_scale` | `0.25` | Atténue les règles `tag` sur le signal caption (le L0 encode déjà la légende) ; les règles structurelles gardent tout leur poids |
| `priors.rules` / `priors.event_types.<et>.rules` | (jeu général) | Règles déclaratives `{kind, when, boost}` indépendantes du vocabulaire ; un `boost` ciblant un moment absent du vocabulaire actif est ignoré. Les règles par `event_type` remplacent la liste globale. Référence complète des prédicats : doc anglaise |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Lissage de chronologie L2 (Viterbi) : à forte tendance auto-boucle sans progression vers l'avant (le vocabulaire agnostique n'a pas d'ordre canonique), appliqué légèrement (`weight=0` = pas de lissage) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Départage L3 (désormais actif) : lorsqu'il est activé sur les profils 16gb/24gb, seules les images à faible postérieur (sous `min_confidence`) ou à faible marge (sous `min_margin`) sont reclassées par le VLM du profil pendant `--detect-moments` / `--recompute-moments` : reclasser les images à faible marge avec le VLM Qwen (16gb/24gb uniquement) |
| `event_types` | `general` + `wedding` | `{moment: [synonymes de prompt]}` par type d'événement ; définissez `default_event_type` pour changer de genre ou ajouter le vôtre |

> **Coût du remplissage rétroactif des légendes.** Les embeddings de légende sont calculés une seule fois et stockés, si bien que le cosinus par photo est ensuite gratuit. Une analyse n'encode que sa poignée de nouvelles légendes (peu coûteux, incrémental), mais la première passe complète sur une bibliothèque existante encode chaque légende — une passe avant de la tour textuelle par légende, rapide sur GPU et ~quelques heures sur CPU. Exécutez `python facet.py --detect-moments` une fois (GPU recommandé) pour ce remplissage ; ajoutez `--limit N` pour vérifier d'abord sur un échantillon.

**Découvrir un vocabulaire propre à la bibliothèque.** L'ensemble `general` est une valeur par défaut raisonnable, mais vous pouvez proposer un vocabulaire adapté à *votre* bibliothèque avec `python facet.py --discover-moments` : il regroupe les vecteurs `caption_embedding` stockés (HDBSCAN), nomme chaque grappe à partir de ses légendes (un mot-clé plus les légendes les plus proches du centroïde comme prompts prêts à l'emploi), et écrit le résultat sous forme d'un bloc `event_types.discovered` dans `scoring_config.discovered.json`. Examinez-le, copiez `discovered` dans `event_types` ci-dessus, réglez `default_event_type` sur `discovered`, et exécutez `--recompute-moments` pour l'adopter — la découverte propose, elle ne réécrit jamais la configuration active. `--discover-min-cluster-size N` contrôle la granularité (plus petit = plus de moments, plus fins).

## OCR

Recherche de texte dans les photos : lit les mots *à l'intérieur* de vos photos — panneaux de rue, façades de magasins, dossards de course, tranches de livres, diapositives, tableaux blancs, documents scannés — vers `photos.ocr_text`, une colonne de couverture de l'index plein texte `photos_fts`. Une fois renseigné, ce texte est cherchable depuis la barre de recherche de la galerie comme n'importe quelle légende ou étiquette, et `GET /api/search?scope=text` restreint une requête aux seules colonnes porteuses de texte.

**Désactivé par défaut**, et nécessite l'installation d'un moteur :

```bash
pip install easyocr           # ou : pip install -e .[ocr]
```

Puis activez-le et lancez la passe :

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # uniquement les photos jamais évaluées
python facet.py --recompute-text   # relit toute la bibliothèque
```

| Clé | Défaut | Description |
|-----|--------|-------------|
| `enabled` | `false` | Interrupteur principal. `--detect-text` refuse de s'exécuter tant que ceci est à `false`, afin que la passe ne soit jamais déclenchée par accident |
| `languages` | `["en", "fr"]` | Codes de langue transmis au moteur. Les langues à écriture latine se combinent librement ; mélanger les écritures (par ex. `en` + `ja`) est rejeté par easyocr, donc utilisez une seule famille d'écriture par exécution |
| `min_confidence` | `0.4` | Écarte les détections que le moteur note en dessous de cette valeur (0–1). Augmentez-la si le bruit OCR pollue les résultats de recherche, diminuez-la pour capter un texte faible ou éloigné |
| `full_resolution` | `false` | Applique l'OCR au fichier original au lieu de la miniature stockée en 640px. Bien plus lent et n'en vaut la peine que pour du texte petit ou éloigné — le 640px résout déjà panneaux, affiches et titres de document. Se rabat sur la miniature lorsque l'original est hors ligne |

**Sémantique des sentinelles.** `ocr_text` vaut `NULL` tant qu'une photo n'a jamais été évaluée, et `''` une fois qu'elle a été lue et jugée sans texte. C'est cette distinction qui permet à `--detect-text` de se limiter aux photos réellement nouvelles au lieu de relire chaque image sans texte à chaque exécution ; `--recompute-text` l'ignore et relit tout. FTS5 indexe `''` comme zéro token, si bien qu'une photo sans texte ne peut jamais correspondre à une requête.

**Pas besoin de `--rebuild-fts`.** `ocr_text` figure dans la liste `UPDATE OF` des déclencheurs de synchronisation FTS, si bien que les écritures de la passe elle-même réindexent chaque ligne au fur et à mesure. `python database.py --rebuild-fts` n'est requis que pour une base créée avant que `ocr_text` ne rejoigne l'index de couverture — `init_database` détecte cet index plus ancien et le recrée pour vous.

**Moteurs.** `easyocr` (Apache-2.0, PyTorch) est le moteur par défaut et réutilise la pile que Facet installe déjà — il n'ajoute pas de second OpenCV et ne fige aucune version de numpy/torch. Ses poids (~113 Mo) se téléchargent depuis les releases GitHub propres au projet au premier lancement. Le binaire `tesseract` plus `pytesseract` fonctionne comme outil externe optionnel alternatif (comme `exiftool`) et est utilisé lorsque easyocr est absent, mais il est réglé pour les pages scannées et lit nettement moins bien le texte de scène. Sans aucun des deux installés, la passe se termine en erreur au lieu d'écrire silencieusement du vide.

**Coût.** Une miniature 640px prend environ 0,4 s sur CPU, si bien qu'une bibliothèque de 50 000 photos représente une nuit de travail CPU — c'est un remplissage rétroactif ponctuel, et les analyses suivantes n'ajoutent que de nouvelles photos. Un GPU est utilisé automatiquement lorsque torch en signale un.

## Export social

Recadrages sensibles au sujet pour les formats des réseaux sociaux (`GET /api/photo/social_crop`, réservé à l'édition). Chaque préréglage recadre l'original en pleine résolution vers un format cible et le cadre sur le sujet détecté — le plus grand rectangle de ce format tenant dans l'image, centré sur le sujet et borné aux bords. La boîte du sujet suit une chaîne de repli : la boîte de sujet BiRefNet persistée (`photos.subject_bbox`) → l'union des boîtes de visages détectés → un recadrage centré simple. Voir [Visionneuse web — Téléchargement](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| Réglage | Défaut | Description |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Chemin i18n pour le nom affiché du préréglage (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Format cible sous la forme `"l:h"` (p. ex. `1:1`, `4:5`, `9:16`) |
| `jpeg_quality` | `92` | Qualité JPEG du recadrage exporté |

Contrôlé par `viewer.features.show_social_export` (par défaut `true`). La colonne `photos.subject_bbox` est écrite par la passe de saillance au scan et par `--recompute-saliency` ; les lignes scannées avant son existence se rabattent automatiquement sur le recadrage par visages ou centré.

## Export de portfolio

Exportez un album sous forme de galerie HTML statique autonome qu'un photographe peut déposer sur n'importe quel hébergeur web — sans outil externe (thumbsup/sigal) requis (`POST /api/albums/{album_id}/export-portfolio`, réservé à l'édition). Le répertoire généré contient `index.html` (une grille de vignettes responsive en CSS pur plus une visionneuse vanilla-JS intégrée, avec **zéro** référence externe/CDN — entièrement hors ligne), un dossier `assets/` de JPEG nommés séquentiellement (aucun chemin de bibliothèque divulgué) et un `manifest.json`. Chaque photo utilise l'**original** sur disque (réduit à `max_edge`) lorsqu'il est lisible et se rabat sur la vignette 640 px stockée lorsque l'original est inaccessible (partages réseau hors ligne) ; la source utilisée est enregistrée par photo dans le manifeste. La génération est déterministe et idempotente — une réexportation ne réécrit que ses propres fichiers.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `max_photos` | `500` | Les albums plus grands sont refusés avec une erreur 400 (l'export est synchrone) |
| `max_edge` | `2048` | Plafond du grand côté (px) pour les originaux exportés ; la requête peut le remplacer (borné 256–8000) |
| `jpeg_quality` | `88` | Qualité JPEG des images exportées |

Le `target_dir` passe par la même liste d'autorisation que les endpoints d'export copie/déplacement (`viewer.export.allowed_target_dirs` plus les répertoires de scan). Contrôlé par `viewer.features.show_portfolio_export` (par défaut `true`).

## Cadre photo / Kiosque

Diffuse les « meilleures photos » vers des appareils kiosque sans authentification — cadres photo connectés, tableaux de bord Home Assistant, affichages de type ImmichFrame / Immich-Kiosk — via trois endpoints anonymes à jeton statique (`GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`). L'accès repose sur un **jeton de cadre** opaque à longue durée de vie ; une liste `tokens` vide désactive toute la fonctionnalité (chaque endpoint renvoie 404). Les réponses ne contiennent jamais de chemins de fichiers — chaque photo est identifiée par un identifiant signé opaque dérivé du `rowid` de la ligne.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `tokens` | `[]` | Jetons de cadre opaques (liste). **Vide = fonctionnalité désactivée (404).** Utilisez des chaînes aléatoires longues, une par appareil ; supprimez-en une pour la révoquer. Générez-en une avec `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `count` | `20` | Nombre de photos renvoyées par défaut par `/api/frame/photos` |
| `max_count` | `100` | Plafond strict du paramètre de requête `count` |
| `min_aggregate` | `7.0` | Score agrégé minimal pour qu'une photo soit sélectionnée |
| `max_edge` | `1920` | Plafond du côté long (px) des JPEG servis ; le paramètre `max_edge` peut l'abaisser mais jamais le dépasser |
| `favorites_only` | `false` | Si `true`, seules les photos favorites sont sélectionnées |
| `categories` | `[]` | Liste blanche de noms de catégories (vide = toutes) |

Les jetons sont comparés à temps constant en octets UTF-8 : un jeton manquant renvoie 401 et un jeton erroné ou non-ASCII renvoie 403 (jamais 500). La sélection exclut les photos rejetées, indésirables (`junk_kind`) et avec clignement, puis applique le seuil de score / favoris / catégories ; l'ensemble renvoyé est un échantillon aléatoire pondéré par le score.

Un jeton de cadre n'est pas une connexion utilisateur : il ne porte aucun `user_id` et est vérifié par rapport à toute la bibliothèque, donc en [mode multi-utilisateur](#users), il ignore les `directories` privés de chaque utilisateur et accorde un accès en lecture aux photos de tous les utilisateurs, pas seulement aux `shared_directories`. N'émettez des jetons de cadre que sur les installations où chaque utilisateur configuré est à l'aise avec cela.

## Envoi automatique depuis le téléphone

Un endpoint **WebDAV** minimal sous `/dav` permet aux applications d'envoi automatique depuis le téléphone (PhotoSync et autres) de déposer des photos dans un **répertoire de réception** (inbox) que `facet.py --watch` évalue ensuite automatiquement — le modèle de synchronisation mobile de PhotoPrism. Plomberie d'envoi uniquement : n'affecte jamais les sessions utilisateur ni les JWT. L'accès se fait en HTTP Basic avec des **identifiants d'appareil partagé** (`username` / `password`), et non un compte utilisateur. Tout l'arbre `/dav` renvoie **404 tant qu'il est désactivé** — la fonctionnalité n'est active que lorsque `username`, `password` et `inbox_dir` sont tous renseignés. Chaque opération est confinée à `inbox_dir` (traversée / chemin absolu / évasion par lien symbolique refusés), et les envois sont écrits sur disque de façon atomique avec le plafond `max_file_mb`.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `username` | `""` | Nom d'utilisateur HTTP Basic (identifiant d'appareil partagé). **Vide = fonctionnalité désactivée (404).** |
| `password` | `""` | Mot de passe HTTP Basic (identifiant d'appareil partagé). **Vide = fonctionnalité désactivée (404).** Utilisez une chaîne aléatoire longue. |
| `inbox_dir` | `""` | Chemin absolu du répertoire de réception. **Vide = fonctionnalité désactivée (404).** Pointez-le vers l'un des répertoires scannés (ou un sous-répertoire) pour que `facet.py --watch` évalue les envois à leur arrivée. Créé à la demande. |
| `max_file_mb` | `500` | Plafond de taille par fichier (Mo) ; un envoi qui le dépasse est interrompu avec un `413` et ne laisse aucun fichier partiel. |

Les identifiants sont comparés à temps constant en octets UTF-8 ; un en-tête `Authorization` manquant ou erroné renvoie un `401` avec `WWW-Authenticate: Basic realm="Facet upload"`. Méthodes implémentées : `OPTIONS`, `PROPFIND` (profondeur 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (`LOCK`/`UNLOCK` ne sont pas implémentées). La recette PhotoSync et un test rapide avec `curl` sont décrits dans la documentation du Visualiseur Web.

## Nettoyage des indésirables

Détecteur zero-shot pour les fichiers non photographiques « indésirables » — captures d'écran, documents scannés, reçus, mèmes, diapositives de présentation — sur l'**embedding d'image stocké** (pas de décodage d'image, pas de passe de modèle par image ; la même architecture que les moments narratifs, sans le lissage temporel). Chaque type porte une liste de prompts textuels ; l'embedding de la photo est noté par cosinus contre chaque prompt puis **max-pooled** par type. Un jeu de prompts contrastifs `not_junk` conditionne la décision : une photo n'est signalée que lorsque le meilleur type d'indésirable franchit `min_confidence` ET dépasse le meilleur prompt `not_junk` de `min_margin` — sinon elle est enregistrée avec la sentinelle `not_junk` (évaluée et propre). `NULL` signifie « non évaluée » : `--detect-junk` n'étiquette que les lignes `NULL` (et s'exécute automatiquement en fin de scan), tandis que `--recompute-junk` réévalue toute la bibliothèque. Alimente `photos.junk_kind` ; la file de revue **Nettoyage des indésirables** de la visionneuse ([VIEWER.md](VIEWER.md#nettoyage-des-indésirables)) la consulte.

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Exécute la détection d'indésirables pendant `--detect-junk` / `--recompute-junk` et en fin de scan |
| `prompt_template` | `"{desc}"` | Gabarit de format appliqué à chaque prompt (`{desc}` = le prompt) ; identité par défaut puisque les prompts sont des phrases complètes |
| `pooling` | `"max"` | Regroupe les cosinus par prompt en un score par type, via `max` (meilleur prompt unique, plus discriminant) ou `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Cosinus max-pooled minimal pour que le meilleur type d'indésirable soit pris en compte (les cosinus CLIP/`open_clip` sont plus bas que ceux de SigLIP/`transformers`, d'où un seuil propre à chaque backend) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Écart minimal que le meilleur type d'indésirable doit creuser sur le meilleur prompt contrastif `not_junk` avant que la photo soit signalée |
| `kinds` | screenshot/document/receipt/meme/slide | `{type: [synonymes de prompt]}` ; ajoutez, retirez ou renommez les types librement — la colonne et la file de la visionneuse suivent la configuration |
| `not_junk_prompts` | 8 prompts de photographie | Jeu contrastif décrivant de vraies photographies ; le filtre qui garde les photos authentiques hors de la file |

## Backend VLM

Choisit où s'exécute le modèle vision-langage de légendage/étiquetage. `local` (par défaut) utilise le chemin transformers Qwen en process, embarqué avec les profils VRAM 16gb/24gb — aucun changement pour les installations existantes. Les deux backends distants pointent Facet vers un serveur externe afin que le légendage et l'étiquetage VLM fonctionnent sur les **profils legacy/8gb qui n'embarquent aucun VLM local** : quand un backend distant est sélectionné, les fonctionnalités VLM ne dépendent plus du profil VRAM.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `type` | `"local"` | Backend : `local` (transformers Qwen en process), `ollama` (API REST native d'Ollama), ou `openai_compatible` (tout endpoint de complétion de chat compatible OpenAI — LM Studio, vLLM, OpenRouter) |
| `ollama.base_url` | `"http://localhost:11434"` | URL de base du serveur Ollama ; l'image est envoyée en base64 à `POST /api/generate` |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag de modèle Ollama (doit être un modèle vision déjà récupéré sur le serveur) |
| `ollama.timeout_seconds` | `120` | Délai d'expiration par requête pour les appels Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL de base compatible OpenAI, **suffixe `/v1` inclus** ; les requêtes partent vers `{base_url}/chat/completions` avec l'image en URI de données `image_url` |
| `openai_compatible.api_key` | `""` | Jeton porteur envoyé en `Authorization: Bearer <clé>` ; laissez vide pour les serveurs locaux sans authentification |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nom de modèle transmis à l'endpoint |
| `openai_compatible.timeout_seconds` | `120` | Délai d'expiration par requête pour les appels compatibles OpenAI |

Le backend partagé pilote le légendage (`--generate-captions` et l'endpoint à la demande `/api/caption`), la critique VLM (`/api/critique?mode=vlm`), le ré-étiquetage VLM (`--recompute-tags-vlm`), et le départage VLM des moments narratifs. Un échec de requête distante est rapporté comme un échec par photo (journalisé, tags vides / pas de légende) et ne fait jamais planter l'exécution. L'étiquetage en cours de scan utilise toujours l'étiqueteur propre au profil ; exécutez `--recompute-tags-vlm` pour appliquer un backend distant à une bibliothèque existante.

## Critique IA

Configuration du prompt de la critique propulsée par VLM (profils 16gb/24gb). La critique injecte la décomposition complète des règles, les pénalités et l'EXIF dans un prompt à paliers configurable, restitue la réponse sous forme Observation / Évaluation / Suggestions, et la met en cache par photo dans `photos.vlm_critique` (traduite à la demande dans `vlm_critique_translated`). Elle s'exécute sur la vignette stockée, si bien que les fichiers RAW sont critiqués correctement au lieu d'échouer en silence ; `refresh` régénère. Le palier par défaut suit la structure à quatre aptitudes d'AesBench (percevoir → ressentir → juger → conseiller) : son Évaluation donne un verdict bref sur la composition, la couleur & la lumière, la mise au point/PdC & l'exécution technique, et le sujet & le moment, chacun confronté aux métriques injectées plutôt que de répéter les chiffres.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Budget de jetons pour la génération de la critique VLM structurée |

Voir [Visionneuse web — Critique IA](VIEWER.md#ai-critique).

## Attributs de distorsion

Étiquetage de distorsion zero-shot, indicatif uniquement. `--recompute-distortions` note chaque photo au regard de prompts contrastifs de style ExIQA sur son embedding CLIP/SigLIP stocké et enregistre les défauts probables (flou de bougé, dominante colorée, suraccentuation, …) dans une colonne JSON indicative. Il n'alimente jamais l'agrégat ; les étiquettes s'affichent sous forme de puces d'avertissement dans la boîte de dialogue de critique.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Calcule les attributs de distorsion lors de `--recompute-distortions` |
| `top_n` | `5` | Nombre maximal d'étiquettes de distorsion conservées par photo |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Température softmax sur les scores des prompts contrastifs, par backend d'embedding (comme pour `narrative_moments`, les cosinus open_clip et transformers évoluent à des échelles différentes) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilité minimale pour qu'une étiquette de distorsion soit conservée |
| `vocabulary` | `{}` | Remplacement facultatif de l'ensemble de prompts de distorsion intégré (`{attribut: [synonymes de prompt]}`) ; vide = valeurs par défaut du module |

## Teint

Naturel du teint des portraits (indicatif uniquement). `--recompute-skin-tone` échantillonne le chroma CIELAB des joues à partir des vignettes de visage + points de repère stockés et mesure sa distance CIEDE2000 à un lieu de peau à température de couleur corrélée, signalant les portraits dont la peau dérive vers le vert / magenta / bleu / jaune. Il n'alimente jamais l'agrégat ; le résultat s'affiche comme note de teint dans la boîte de dialogue de critique.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `cast_delta_threshold` | `12.0` | Écart CIEDE2000 minimal entre le chroma de peau mesuré et le lieu de peau avant qu'une dominante de couleur soit signalée |

## Synchronisation Immich

Synchronisation à sens unique des notes en étoiles et favoris Facet vers un serveur [Immich](https://immich.app/) via son API REST. Les ressources sont résolues par `originalPath` grâce aux correspondances de préfixes de chemin configurées, en une seule passe de recherche groupée. Lancez-la avec `--immich-sync` (vérifiez d'abord avec `--immich-test`) ; voir [Commandes — Synchronisation Immich](COMMANDS.md#immich-sync).

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "rejected": false,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "webhook": {
      "token_env": "",
      "header": "x-facet-token",
      "max_pending": 500
    },
    "timeout_seconds": 30
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `url` | `""` | URL de base du serveur Immich (par ex. `http://nas:2283`) |
| `api_key` | `""` | Clé API Immich, envoyée comme en-tête `x-api-key` |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Réécritures de préfixe des chemins Facet vers les valeurs `originalPath` d'Immich ; le premier `facet_prefix` correspondant est remplacé par son `immich_prefix` lors de la résolution d'une ressource |
| `push.ratings` | `true` | Pousse les notes en étoiles. La politique de compatibilité de version d'Immich est respectée — seul 1–5 est écrit, jamais 0/−1 |
| `push.favorites` | `true` | Pousse l'indicateur de favori |
| `push.rejected` | `false` | Pousse `rating: -1` pour les photos rejetées dans Facet. Nécessite `push.ratings` |
| `push.top_picks_album` | `""` | Nom d'album Immich facultatif qui rassemble les photos poussées au-dessus du seuil de note. Vide = aucun album |
| `push.top_picks_min_rating` | `4` | Note en étoiles minimale pour qu'une photo soit ajoutée à `top_picks_album` |
| `webhook.token_env` | `""` | Nom de la variable d'environnement contenant le secret du webhook entrant. Vide (ou variable non définie/vide) désactive le point d'accès — il renvoie 404 |
| `webhook.header` | `"x-facet-token"` | En-tête dans lequel le workflow Immich envoie le jeton |
| `webhook.max_pending` | `500` | Plafond de la liste des chemins mémorisés mais non notés, rapportée par la prochaine synchronisation |
| `timeout_seconds` | `30` | Délai d'expiration REST par requête |

`--immich-sync` honore `--dry-run` (résout chaque ressource mais n'écrit rien) et `--user` (pousse les notes `user_preferences` de cet utilisateur en mode multi-utilisateurs). REST uniquement — Facet ne touche jamais la base de données Immich.

## Frise chronologique

Réglages pour la vue chronologique :

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `photos_per_group` | `30` | Nombre de photos chargées par groupe de date dans la vue chronologique. Des valeurs plus élevées affichent plus de photos par date mais alourdissent la page. |

## Carte

Réglages pour la vue carte interactive :

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `cluster_zoom_threshold` | `10` | Niveau de zoom auquel les marqueurs individuels remplacent les clusters. Des valeurs plus basses affichent les marqueurs individuels plus tôt (plus de détail à un zoom plus large). Plage : 1 (monde) à 18 (rue). |

## Traduction

Réglages pour la traduction des légendes IA via MarianMT :

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `target_language` | `"fr"` | Code de langue cible pour `--translate-captions`. Pris en charge : `fr` (français), `de` (allemand), `es` (espagnol), `it` (italien), `pt` (portugais brésilien). Utilise les modèles MarianMT de Helsinki-NLP (CPU, aucun GPU requis). |

## CLIP esthétique (R2)

Score esthétique supplémentaire dérivé des embeddings CLIP/SigLIP mis en cache via projection textuelle. Les prompts sont réglables par l'utilisateur pour le benchmarking AVA — voir `scripts/benchmark_aesthetic.py` pour mesurer l'impact SRCC de tout changement.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Des tableaux vides retombent sur les valeurs par défaut du module intégrées dans `analyzers/aesthetic_clip.py`. Ne réglez pas ces prompts sans relancer le benchmark AVA — les valeurs par défaut obtiennent un SRCC de ~0,52 sur `ava_test/` et des changements peuvent facilement régresser à ~0,30.

## Ajout de modèles VLM tagger / critique alternatifs (R3)

La clé `tagging_model` de chaque profil VRAM (par ex. `qwen3.5-2b`) correspond à une entrée de modèle dans la même section `models`. Pour expérimenter avec un VLM différent (Pixtral-12B, InternVL-2.5, etc.) :

1. Ajoutez une entrée de modèle sous `models` :
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Pointez un profil dessus :
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Exécutez `python facet.py --recompute-tags-vlm` pour ré-étiqueter.

Aucun changement de code nécessaire. Validez la qualité par un contrôle ponctuel côte à côte sur ~30 photos avant de promouvoir en valeur par défaut.

## Secret de partage

Chaîne hexadécimale de 64 caractères auto-générée pour les jetons de session/partage :

```json
{
  "share_secret": "31a1c944ea5c82b871e61e50e5920daa2d1940b126c395f519088506595fd925"
}
```

Générée automatiquement au premier lancement si absente.
