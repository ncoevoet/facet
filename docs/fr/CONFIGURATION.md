# Référence de configuration

> 🌐 [English](../CONFIGURATION.md) · **Français** · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md) · [简体中文](../zh/CONFIGURATION.md)

Chaque réglage est livré dans `config/scoring_config.default.json`. Votre propre `scoring_config.json` le surcharge clé par clé — voir [Valeurs par défaut et votre surcharge](#valeurs-par-défaut-et-votre-surcharge). Après une modification, lancez `python facet.py --recompute-average` pour mettre à jour les scores (pas de GPU nécessaire).

## Table des matières

- [Valeurs par défaut et votre surcharge](#valeurs-par-défaut-et-votre-surcharge)
- [Utilisateurs](#utilisateurs)
- [Analyse](#analyse)
- [Catégories](#catégories)
- [Contextes de notation](#contextes-de-notation)
- [Notation](#notation)
- [Seuils](#seuils)
- [Composition](#composition)
- [Ajustements EXIF](#ajustements-exif)
- [Exposition](#exposition)
- [Pénalités](#pénalités)
- [Normalisation](#normalisation)
- [Modèles](#modèles)
- [Modèles d'évaluation de la qualité](#modèles-dévaluation-de-la-qualité)
- [Traitement](#traitement)
- [Décodage RAW](#décodage-raw)
- [Mappage de tons HDR PQ](#mappage-de-tons-hdr-pq)
- [Détection de rafales](#détection-de-rafales)
- [Notation des rafales](#notation-des-rafales)
- [Détection de doublons](#détection-de-doublons)
- [Détection des visages](#détection-des-visages)
- [Regroupement des visages](#regroupement-des-visages)
- [Traitement des visages](#traitement-des-visages)
- [Détection monochrome](#détection-monochrome)
- [Étiquetage](#étiquetage)
- [Étiquettes autonomes](#étiquettes-autonomes)
- [Analyse](#analyse)
- [Visionneuse](#visionneuse)
- [Performance](#performance)
- [Stockage](#stockage)
- [Plugins](#plugins)
- [Capsules](#capsules)
- [Groupes de similarité](#groupes-de-similarité)
- [Scènes](#scènes)
- [OCR](#ocr)
- [Frise chronologique](#frise-chronologique)
- [Carte](#carte)
- [Traduction](#traduction)

---

## Valeurs par défaut et votre surcharge

`scoring_config.json` ne contient **que ce que vous avez modifié**. Facet le résout par-dessus `config/scoring_config.default.json` : tout ce que vous omettez garde la valeur livrée. Une installation neuve n'a pas de `scoring_config.json` et fonctionne avec les valeurs par défaut.

Pour augmenter le poids esthétique des portraits et définir un mot de passe d'édition, le fichier complet est :

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

Comment les deux fichiers se combinent :

- **Les objets fusionnent clé par clé.** `{"performance": {"mmap_size_mb": 4096}}` change ce seul réglage ; `cache_size_mb` et toutes les autres clés `performance` gardent leurs valeurs livrées.
- **Les tableaux remplacent en bloc.** Un tableau `categories` dans votre fichier remplace entièrement celui livré. L'ordre compte (`categories` est en premier-qui-correspond-gagne, `scoring_contexts.*.promote` est lu dans l'ordre), et omettre une catégorie de votre tableau la supprime.

Pour changer un poids dans une catégorie, copiez le tableau `categories` entier depuis `config/scoring_config.default.json`, modifiez-le et gardez-le dans votre fichier.

### Mettre à niveau une installation existante

Rien à faire : un `scoring_config.json` complet issu d'une version antérieure fonctionne toujours. Toute écriture de Facet dans le fichier (enregistrement des poids ou des priorités dans la visionneuse, changement d'un seuil de panorama, première connexion qui met à niveau un mot de passe en clair, scan où `validate_weights` corrige des poids) le réécrit sous forme de surcharge et supprime toute clé égale à la valeur livrée.

Pour le compacter à la demande, avec une copie de sauvegarde `0600` faite au préalable :

```bash
python database.py --compact-config
```

Le résultat se résout exactement en la même configuration.

> **Remarque :** Une valeur égale à la valeur livrée ne reste pas dans votre fichier. Si une version ultérieure change cette valeur par défaut, votre comportement change aussi. Pour figer une valeur, elle doit différer de la valeur par défaut.

## Utilisateurs

Mode multi-utilisateur optionnel. Lorsque la clé `users` contient au moins un utilisateur, une connexion par utilisateur remplace l'authentification par mot de passe unique.

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
| `password_hash` | string | Hachage PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`), généré par `--add-user` |
| `display_name` | chaîne | Affiché dans l'en-tête de l'interface |
| `role` | chaîne | `user`, `admin` ou `superadmin` |
| `directories` | array | Dossiers de photos privés de cet utilisateur (correspondance : voir [Dossiers partagés](#répertoires-partagés)) |

### Répertoires partagés

`shared_directories` (au même niveau que les objets utilisateur) liste les dossiers que tous les utilisateurs peuvent voir. Les entrées de `directories` et de `shared_directories` sont comparées aux chemins enregistrés par le scanner :

- La casse ASCII est ignorée sous Windows et macOS, et pour les entrées UNC ou à lettre de lecteur sur n'importe quel hôte.
- Ailleurs (Linux, par exemple) la casse compte : écrivez chaque entrée exactement comme le scanner l'a enregistrée.
- Non gérés : les différences de casse non ASCII, et un lecteur réseau mappé que l'hôte ne sait pas résoudre.
- Une entrée vide n'accorde rien.

### Rôles

| Rôle | Voir ses photos + partagées | Noter/favori | Gérer personnes/visages | Déclencher des analyses |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Ajouter des utilisateurs

Les utilisateurs se créent uniquement depuis la CLI ; il n'y a ni interface ni API d'inscription :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Demande un mot de passe, écrit l'empreinte dans scoring_config.json
```

Modifiez ensuite `scoring_config.json` pour définir leurs `directories`.

### Rétrocompatibilité

- Pas de clé `users` = mode mono-utilisateur (comportement inchangé).
- `viewer.password` et `viewer.edition_password` sont ignorés en mode multi-utilisateur.
- Les notes existantes de la table `photos` restent pour le mode mono-utilisateur ; `--migrate-user-preferences` les copie.

---

## Analyse

Contrôle les dossiers que le scan parcourt.

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `skip_hidden_directories` | `true` | Ignorer les dossiers dont le nom commence par `.` |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | Motifs de noms de dossier ignorés à toute profondeur |

Remarques sur `skip_directories` :
- Les motifs utilisent `fnmatch`, sont sensibles à la casse et ne portent que sur le nom du dossier.
- Les valeurs par défaut couvrent `@eaDir` de Synology (ses miniatures `SYNOPHOTO_THUMB_*.jpg`), `#recycle`, `#snapshot` et `@Recycle` de QNAP.
- Votre liste remplace celle par défaut ; `[]` désactive l'exclusion par nom. La racine du scan n'est jamais ignorée.
- Les photos déjà indexées depuis ces dossiers restent dans la base de données.

---

## Catégories

Tableau de définitions de catégories. Voir [Évaluation](SCORING.md) pour le guide complet des catégories.

Chaque catégorie possède :
- `name` - Identifiant de la catégorie
- `priority` - Plus la valeur est faible, plus la priorité est élevée (évaluée en premier)
- `filters` - Conditions de correspondance
- `weights` - Pondérations des métriques de notation (la somme doit faire 100)
- `modifiers` - Ajustements de comportement
- `tags` - Vocabulaire CLIP pour la correspondance par étiquettes

> **Poids de forme et d'harmonie des couleurs.** Les `weights` de chaque catégorie ont cinq clés remplies par `--recompute-form` : `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` et `color_harmony_percent`. Elles sont livrées à `0`, donc les scores ne changent pas tant que vous n'en pondérez pas une (puis lancez `--recompute-average`). Les poids totalisent toujours 100.

> **`quality_percent` compte pour `aesthetic`.** La qualité n'a pas de score propre : `quality_percent` est donc ajouté à `aesthetic_percent` avant le calcul. Voir [SCORING.md](SCORING.md).

> **La catégorie `astro` livrée exige une image sombre.** Outre l'un de ses tags, elle requiert `luminance_max: 0.30` (luminance moyenne d'au plus 0.30), si bien qu'une scène lumineuse taguée `aurora` ou `stars` n'est pas `astro`. Si votre `scoring_config.json` a son propre tableau `categories`, son entrée `astro` ne reçoit pas ce filtre : ajoutez `"luminance_max": 0.30` sous `astro.filters`, ou supprimez le tableau. `python facet.py --doctor` affiche un « Config notice » lorsque `astro` n'a pas de `luminance_max`. Lancez ensuite `--recompute-average` (après une mise à niveau : d'abord `--recompute-silhouette`, puis `--recompute-average` deux fois ; voir [COMMANDS.md](COMMANDS.md)).

---

## Contextes de notation

Un contexte d'évaluation change la catégorie qui l'emporte pour un album ou une photo. Il fait passer quelques catégories en tête de l'ordre global de `categories` et en exclut d'autres ; les restantes gardent leur ordre de priorité. Utilisez-le quand l'ordre global choisit la mauvaise catégorie pour une séance : une image de danse à contre-jour taguée `sports` est captée par `silhouette` (priorité 42) avant `sports` (priorité 71). Les curseurs de poids n'y peuvent rien, car ils ne changent que la façon dont la catégorie sélectionnée est notée.

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
| `promote` | Catégories placées en tête de l'ordre d'évaluation, dans l'ordre indiqué |
| `excluded` | Catégories jamais retenues sous ce contexte |
| `suggest_from_moments` | Valeurs de `narrative_moment` qui suggèrent ce contexte pour un album (`GET /api/albums/{id}/suggested_context`, voir [VIEWER.md](VIEWER.md)) |

**Ordre effectif** = `promote` (dans l'ordre) → l'ordre de priorité global sans les noms promus et exclus → `default` (la catégorie fourre-tout, priorité 999) en dernier.

- Un nom présent à la fois dans `promote` et `excluded` est exclu.
- `default` ne peut jamais être promu ni exclu.
- Sans contexte, ou avec un nom inconnu, l'ordre global simple est utilisé (un nom inconnu journalise un avertissement).
- `python facet.py --validate-categories` signale les noms de catégorie inconnus, les noms présents dans les deux listes et les entrées `suggest_from_moments` qui ne sont pas des clés de `narrative_moments.event_types.<default_event_type>`. Sinon, les fautes de frappe passent inaperçues.

Préréglages livrés (`default` est vide, donc rien ne change tant que vous n'assignez pas de contexte) :

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

Ajoutez une clé sous `scoring_contexts` et elle fonctionne comme un préréglage livré : vous pouvez l'assigner à un album et la modifier dans l'onglet **Contexte de notation**.

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

Si `label_key` n'a pas de traduction, le sélecteur affiche le **`name`** du contexte (par ex. `dance_comp`). Ajoutez la clé aux six bundles `i18n/translations/*.json` pour obtenir un libellé localisé.

### Modifier un contexte

Dans l'onglet **Contexte de notation** de la visionneuse (réservé à l'édition, `PUT /api/config/scoring_contexts/{name}`), glissez ou déplacez des catégories dans la liste promue, cliquez sur une catégorie pour basculer son exclusion, puis enregistrez.

- Seuls `promote` et `excluded` sont modifiables ; `label_key`, `suggest_from_moments` et les autres contextes restent tels quels.
- Un enregistrement est refusé lorsque le contexte n'existe pas, lorsqu'une entrée n'est pas une catégorie existante, lorsque `default` figure dans l'une des listes, ou lorsque `promote` répète un nom. Un nom présent dans les deux listes est accepté (`excluded` l'emporte) ; une répétition dans `excluded` est fusionnée.
- Chaque enregistrement conserve une copie `.backup.<timestamp>` horodatée de la configuration.
- Modifier un contexte ne recatégorise pas les photos : lancez ensuite un recalcul (voir [Changer les priorités exige un recalcul](#réorganiser-la-priorité-globale)). L'onglet propose un bouton **Recalculer maintenant**.

### Assigner un contexte

Assignez un contexte **par album** avec `PUT /api/albums/{id}/scoring_context` (réservé à l'édition).

- Il s'applique à chaque photo de l'album à ce moment-là, sauf aux photos dont vous avez défini le contexte à la main.
- Une photo ajoutée plus tard à un album manuel hérite du contexte. Une nouvelle photo correspondant au filtre d'un album intelligent n'en hérite pas ; appelez de nouveau `PUT` pour le réappliquer.
- Un album intelligent utilise son filtre enregistré, pas les bascules de masquage de la galerie ; il peut donc couvrir plus de photos que sa vue de galerie n'en montre.
- `DELETE /api/albums/{id}/scoring_context` retire le contexte des photos que cet album a définies. Les choix manuels restent.
- Retirer des photos d'un album (`DELETE /api/albums/{id}/photos`) leur retire le contexte de cet album. Une photo encore dans un autre album ayant un contexte prend le contexte de cet album.
- `GET /api/albums/{id}/suggested_context` propose un contexte d'après le `narrative_moment` dominant de l'album, via `suggest_from_moments`. Il ne modifie rien.

Pour une seule photo récalcitrante, utilisez un **remplacement de catégorie** : `POST /api/comparison/override_category` (réservé à l'édition) définit directement la catégorie, et `POST /api/comparison/clear_category_override` la retire. Un remplacement l'emporte sur tout contexte.

Les remplacements et les contextes survivent aux nouveaux scans. Un filtre numérique échoue toujours lorsque sa valeur EXIF est absente, quel que soit le contexte — voir [Évaluation — le piège de l'EXIF manquant](SCORING.md#le-piège-des-données-exif-manquantes).

### Réorganiser la priorité globale

`GET|POST /api/config/category_priorities` (réservé à l'édition) lit et enregistre l'ordre global dont part chaque contexte. La visionneuse réordonne les numéros de priorité existants au lieu de les renuméroter.

- `default` (priorité 999) reste en dernier et ne peut pas être déplacé.
- Une catégorie dont la priorité est absente ou en double reçoit à l'enregistrement une valeur neuve au-delà du maximum actuel.
- Chaque enregistrement conserve une copie `.backup.<timestamp>` horodatée de `scoring_config.json` ; les 20 plus récentes sont conservées.

**Changer les priorités exige un recalcul.** Un réordonnancement ne change pas la `category` stockée des photos. Lancez `python facet.py --recompute-average`, ou démarrez `POST /api/scan/recompute` depuis la visionneuse (réservé à l'édition) et suivez `GET /api/scan/recompute_status`.

- Un recalcul et un scan ne peuvent pas s'exécuter en même temps : la CLI refuse, et la visionneuse indique quelle tâche détient la bibliothèque.
- Deux scans lancés depuis un terminal ne provoquent qu'un avertissement (`--resume` refuse).
- Avec `normalization.per_category` activé, un recalcul peut devoir être exécuté deux fois — voir [Normalisation](#normalisation).

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

Seuils de score. Seul `blink_penalty_percent` subsiste. Qu'une photo soit un portrait, une prise de nuit ou une longue pose est décidé par les `filters` de chaque catégorie (voir [Catégories](#catégories)), pas par ce bloc.

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `blink_penalty_percent` | `50` | Multiplicateur de score en cas de clignement détecté (0,5x) |

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
| `silhouette_detection` | `true` | Si `true`, une photo marquée `is_silhouette` ignore la pénalité d'écrêtage dans son score agrégé. Le drapeau lui-même n'est pas configurable : il provient d'une règle fixe fondée sur le visage (voir [SCORING.md](SCORING.md)) |

---

## Pénalités

Pénalités de score pour les problèmes techniques.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `noise_sigma_threshold` | `4.0` | Un bruit supérieur déclenche une pénalité |
| `noise_max_penalty_points` | `1.5` | Pénalité de bruit maximale |
| `noise_penalty_per_sigma` | `0.3` | Points par sigma au-dessus du seuil |
| `leading_lines_blend_percent` | `30` | Mélange dans comp_score |
| `oversaturation_threshold` | `0.9` | Seuil de saturation moyenne |
| `oversaturation_penalty_points` | `0.5` | Pénalité de sursaturation |

**Formule de pénalité de bruit :**

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

> **Remarque :** Avec `per_category` activé, un seul recalcul ne suffit pas à stabiliser. Les percentiles sont groupés par la catégorie *stockée* de chaque photo avant que le recalcul ne la réattribue. Après un changement qui déplace des photos entre catégories (priorités, contexte d'évaluation, remplacement de catégorie), lancez `--recompute-average` deux fois.

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
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
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
        "composition_model": "samp-net",
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
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
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
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `vram_profile` | `"auto"` | Profil actif (`auto`, `legacy`, `8gb`, `16gb`, `24gb`) ; `FACET_VRAM_PROFILE` le surcharge (voir ci-dessous) |
| `keep_in_ram` | `"auto"` | Garder les modèles en RAM entre les blocs multi-pass (`"auto"`, `"always"`, `"never"`) ; `auto` vérifie d'abord la RAM libre |
| `ram_cache_reserve_gb` | `4.0` (optionnel, absent du fichier livré) | RAM (Go) à laisser libre à côté d'un modèle en cache sous `"auto"` |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modèles PyIQA à exécuter pour ce profil (les quatre profils exécutent l’ensemble complet) |
| `profiles.*.saliency_enabled` | `true` (tous les profils) | Exécuter la saillance du sujet BiRefNet pour ce profil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modèle d'embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Dimensions de l'embedding (1152 pour SigLIP 2) |
| `clip.tag_threshold_percent` | `8` | Similarité minimale pour qu'un **tag** corresponde avec le tagueur SigLIP 2 des profils 16gb/24gb (remplace `similarity_threshold_percent`) |
| `clip.search_threshold_percent` | `5` | Similarité minimale pour la recherche sémantique (`GET /api/search`) ; nombre entier `0-50` |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modèle CLIP historique (profils legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Poids pré-entraînés historiques |
| `clip_legacy.embedding_dim` | `768` | Dimensions de l'embedding historique |
| `clip_legacy.tag_threshold_percent` | `8` | Même seuil de tag pour le tagueur CLIP des profils legacy/8gb ; `tagging.max_tags` plafonne leur nombre |
| `clip_legacy.search_threshold_percent` | `15` | Seuil de recherche sémantique du profil legacy/8gb ; nombre entier `0-50` |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Modèle pour l'activation manuelle `composition_model: "qwen2-vl-2b"` (aucun profil ne l'utilise) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modèle d'étiquetage pour le profil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Images par lot d'inférence VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modèle d'étiquetage pour le profil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Images par lot d'inférence VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modèle de saillance BiRefNet |
| `saliency.resolution` | `1024` | Résolution d'inférence |
| `saliency.mask_threshold` | `0.3` | Seuil sigmoïde pour le masque binaire du sujet |
| `saliency.min_subject_pixels` | `50` | Nombre minimal de pixels de sujet pour considérer qu'un sujet est détecté |

Remarques :
- **`ram_cache_reserve_gb` :** un modèle n'est conservé que tant que la RAM libre dépasse sa taille plus cette réserve. `"always"` saute la vérification ; `"never"` ne met rien en cache. Ce doit être un nombre >= 0, sinon le scan s'arrête au démarrage. Sous pression mémoire, le cache libère d'abord le modèle nécessaire le plus tard dans le futur (voir [Fonctionnement du multi-pass](#fonctionnement-du-multi-pass)).
- **Seuils de tag et de recherche :** `tag_threshold_percent` contrôle le tagging (scan, `--recompute-tags`, `tag_existing.py`). `search_threshold_percent` est la valeur par défaut du curseur de recherche 0-50 % de la galerie (`search_threshold_default` dans `/api/config`). La valeur SigLIP par défaut `5` privilégie le rappel : sur un échantillon de 34 photos, elle a gardé les 21 vraies correspondances et laissé passer 3 non-correspondances sur 13.

**Recherche sémantique et bibliothèque embarquée sous un profil différent :** `GET /api/search` choisit l'encodeur de texte et son `search_threshold_percent` parmi `clip` / `clip_legacy` selon la dimension d'embedding *stockée*, pas selon le `vram_profile` actif. Une bibliothèque embarquée avec CLIP en 768 dimensions et parcourue sur une machine 16gb cherche donc avec `clip_legacy`. Si la dimension stockée ne correspond à aucun des deux blocs, le bloc du profil actif est utilisé.

### Détection automatique de la VRAM

Lorsque `vram_profile` vaut `"auto"` (par défaut), Facet détecte la VRAM du GPU au démarrage et choisit le plus grand profil qui tient :

| VRAM détectée | Profil sélectionné |
|---------------|--------------------|
| ≥ 20 Go | `24gb` |
| ≥ 14 Go | `16gb` |
| ≥ 6 Go | `8gb` |
| Pas de GPU | `legacy` (utilise la RAM système) |

Un GPU CUDA ne compte que si PyTorch le voit. Sans périphérique visible (par exemple avec `CUDA_VISIBLE_DEVICES=''`), le scan utilise le processeur, signale 0 Go de VRAM et sélectionne `legacy`. `FACET_DEVICE=cuda` sans périphérique visible s'arrête sur « FACET_DEVICE=cuda was requested, but that device is not available ».

**Les cartes de 10 à 14 Go peuvent choisir l'ensemble complet des fonctionnalités.** La détection automatique choisit toujours `8gb` en dessous de 14 Go. Définissez `"vram_profile": "16gb"` ou `FACET_VRAM_PROFILE=16gb` pour exécuter SigLIP 2, TOPIQ, le tagging Qwen3.5-2B, Q-ReAlign et la saillance. Les modèles s'exécutent alors en quatre passes, ou trois sur une carte qui annonce 11,8 GiB ou plus (voir [Regroupement dynamique des passes](#regroupement-dynamique-des-passes)). Une photo que la saillance ne peut toujours pas noter enregistre NULL et journalise une ERROR.

> **Avertissement :** Passer une bibliothèque `8gb` existante à `16gb` change le modèle d'embeddings (CLIP ViT-L-14 en 768 dimensions → SigLIP 2 en 1152 dimensions). Relancez un scan ou exécutez `--recompute-embeddings`, sinon la bibliothèque mélange deux tailles d'embedding. D'ici là, la recherche se comporte comme décrit sous *Recherche sémantique et bibliothèque embarquée sous un profil différent* dans [Modèles](#modèles).

### Surcharge par la variable d'environnement `FACET_VRAM_PROFILE`

`FACET_VRAM_PROFILE` surcharge `models.vram_profile` au chargement, si bien qu'une seule configuration montée peut servir tous les profils Docker. Valeurs acceptées : `auto`, `legacy`, `8gb`, `16gb`, `24gb` ; toute autre valeur est ignorée avec un avertissement. Les surcouches Docker Compose (`docker-compose.{legacy,8gb,16gb,24gb}.yml`) la définissent pour vous.

La surcharge n'est jamais réécrite dans `scoring_config.json`. Un `vram_profile` que vous définissez dans le fichier s'applique toujours lorsque la variable n'est pas définie.

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

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
| `model` | `"auto"` | Modèle de qualité : `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` utilise `topiq`. |
| `prefer_llm` | `false` | Préférer un évaluateur fondé sur un LLM lorsqu'il est disponible |

### Modèles de qualité disponibles

SRCC = coefficient de corrélation de rang de Spearman sur le benchmark KonIQ-10k (1,0 = parfait).

| Modèle | SRCC | VRAM | Notes |
|--------|------|------|-------|
| `topiq` | 0,93 | ~2 Go | Par défaut (`auto`) ; squelette ResNet50 avec attention descendante |
| `hyperiqa` | 0,90 | ~2 Go | Hyper-réseau, adaptatif au contenu |
| `dbcnn` | 0,90 | ~2 Go | CNN à double branche (distorsions synthétiques + authentiques) |
| `musiq` | 0,87 | ~2 Go | Transformeur multi-échelle ; gère toute résolution |
| `clipiqa+` | 0,86 | ~4 Go | CLIP avec prompts de qualité appris |
| `clip-mlp` | 0,76 | ~4 Go | CLIP ViT-L-14 historique + tête MLP |

### Changer de modèle de qualité

1. Modifiez `scoring_config.json` :
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Re-notez les photos existantes (optionnel) :
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Traitement

Réglages du traitement par lots GPU et du multi-pass.

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

- **`gpu_batch_size`** : nombre d'images traitées ensemble dans une passe avant du GPU. Limité par la VRAM ; le réglage automatique le réduit lorsque la mémoire GPU dépasse la limite.
- **`ram_chunk_size`** : nombre d'images gardées en RAM entre les passes de modèles (multi-pass uniquement), pour que chaque image soit lue sur disque une fois par bloc. Limité par `memory_limit_percent`. Le réglage automatique le réduit aussitôt que la mémoire dépasse la limite, et ne l'augmente qu'après un bloc dont l'utilisation *de pointe* est restée sous la limite.

### Référence des réglages

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mode` | `"auto"` | Mode de traitement : `auto`, `multi-pass`, `single-pass`. Seul `single-pass` sélectionne le single-pass ; `auto` exécute toujours le multi-pass |
| `gpu_batch_size` | `16` | Images par lot GPU (limité par la VRAM) |
| `ram_chunk_size` | `32` | Images par bloc RAM (multi-pass) |
| `num_workers` | `4` | Threads de chargement d'images |
| `load_workers` | `num_workers` | Threads de chargement de blocs en multi-pass (plafonnés à 8, `1` = séquentiel) |
| `raw_decode_concurrency` | `0` (auto) | Nombre maximal de décodages RAW simultanés ; dimensionné automatiquement selon CPU/RAM (1-4), `1` = entièrement sérialisé |
| `raw_decode_timeout_seconds` | `120` | Abandonner un décodage RAW bloqué après ce délai (`0` = désactivé) ; l'analyse échoue rapidement après des blocages répétés |
| `exif_prefetch` | `true` | Mode single-pass : précharger l'EXIF en arrière-plan au lieu de bloquer le thread GPU |
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
| `memory_limit_percent` | `85` | Pourcentage de la limite de mémoire effective (limite cgroup sous un plafond conteneur, sinon RAM hôte) |
| `cpu_target_percent` | `85` | Cible d'utilisation du CPU |
| `metrics_print_interval_seconds` | `30` | Intervalle d'affichage des statistiques |
| **thumbnails** | | |
| `photo_size` | `640` | Taille de la vignette stockée (pixels) |
| `photo_quality` | `80` | Qualité JPEG des vignettes |
| `face_padding_ratio` | `0.3` | Marge autour des recadrages de visage |

### Modes de traitement

| Mode | Description |
|------|-------------|
| `auto` | Exécute toujours le multi-pass (valeur par défaut) ; seul `single-pass` sélectionne le single-pass |
| `multi-pass` | Chargement séquentiel des modèles (fonctionne avec une VRAM limitée) |
| `single-pass` | Tous les modèles chargés en même temps (VRAM élevée) ; profils `legacy`/`8gb` uniquement |

Sur `16gb`/`24gb` (esthétique TOPIQ), `single-pass` journalise un avertissement et s'exécute en multi-pass, sauf en mode commercial (voir [Licences](#licences)).

### Fonctionnement du multi-pass

Au lieu de charger tous les modèles en même temps, le multi-pass :

1. Charge les images par blocs en RAM (`ram_chunk_size` par défaut : 32)
2. Pour chaque bloc, exécute les modèles séquentiellement : charger le modèle → traiter le bloc → décharger le modèle
3. Combine les résultats dans une passe d'agrégation finale

Chaque image est décodée une fois par bloc et partagée par toutes les passes. Les passes sont regroupées pour tenir dans la VRAM disponible, de sorte que les VLM plus gros s'exécutent même sur de petites cartes.

- Les threads de chargement calculent aussi l'EXIF, les métriques techniques, la composition à base de règles, le hash perceptuel et une copie partagée de 1024 px pour les modèles pyiqa et Q-ReAlign.
- Une erreur de composition ne fait échouer que cette photo. Elle est enregistrée dans `scan_failures` à l'étape `composition` ; réessayez avec `--retry-failed`.
- Sur un GPU CUDA, un bloc est décodé pendant le chargement des modèles suivants, lorsque la mémoire libre de l'hôte le permet et que `keep_in_ram` n'est pas `"never"`. Sinon (et toujours sur CPU et Apple MPS), il est décodé d'abord. Les résultats sont identiques dans les deux cas.
- Lorsque la mémoire manque avant un bloc, le cache RAM libère d'abord le modèle nécessaire le plus tard dans le futur, et garde `ram_cache_reserve_gb` libre.
- Le résumé du scan indique `Plane rebuilds`, `I/O wait (scan thread blocked on decode)` et `Decode wall`.

### Comportement de l'auto-réglage

Facet surveille l'utilisation des ressources et s'ajuste comme suit. `memory_limit_percent` se mesure par rapport à la limite de mémoire *effective* : la limite cgroup sous un plafond de conteneur (Docker `mem_limit`, Podman `--memory`, Kubernetes `resources.limits.memory`), sinon la RAM de l'hôte. Ainsi `85` face à un plafond de 8 Go donne environ 6,8 Go.

| Métrique | Action |
|----------|--------|
| Mémoire GPU > limite | Réduire `gpu_batch_size` de 25 % |
| Utilisation mémoire > limite | Réduire `ram_chunk_size` de 25 % (immédiatement) |
| Bloc terminé dont l'utilisation maximale est restée < (limite - 20 %) | Augmenter `ram_chunk_size` de 25 % |
| CPU > cible | Suggérer moins de workers |
| Délais de file d'attente > 5 % | Suggérer plus de workers |

### Regroupement dynamique des passes

Lorsque la VRAM le permet, plusieurs modèles s'exécutent dans la même passe :

| VRAM | Passe 1 | Passe 2 | Passe 3 | Passe 4 |
|---|---|---|---|---|
| 8 Go (profil `8gb`) | CLIP | Q-ReAlign + saillance | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12 Go\* (profil `16gb`, optionnel) | Tagger Qwen3.5 + Q-ReAlign | SigLIP + saillance + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16 Go (profil `16gb`) | Tagger Qwen3.5 + SigLIP + TOPIQ | Q-ReAlign + saillance + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24 Go (profil `24gb`) | Tagger Qwen3.5 4B + SigLIP + Q-ReAlign + saillance | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35 Go+ (profil `24gb`) | Tous les modèles ensemble (single-pass) | - | - | - |

Les lignes sont les plans pour des cartes annonçant 8,0, 11,7, 15,99 et 23,99 GiB de VRAM totale ; 34,8 GiB ou plus donne une seule passe. Le planificateur garde 1,3 GiB libre pour CUDA, ONNX Runtime et le bureau. Une carte de 12 Go n'est pas sélectionnée automatiquement (voir [Détection automatique de la VRAM](#détection-automatique-de-la-vram)) : définissez `"vram_profile": "16gb"` ou `FACET_VRAM_PROFILE=16gb`.

\* La ligne 12 Go correspond à une carte annonçant 11,7 GiB. Une carte annonçant 11,8 GiB ou plus (par exemple 11,99 GiB) planifie à la place trois passes : tagueur Qwen3.5 + Q-ReAlign ; SigLIP + saillance + TOPIQ ; TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace.

### Options en ligne de commande

```bash
# Par défaut : multi-pass automatique avec regroupement optimal
python facet.py /path/to/photos

# Forcer le single-pass (tous les modèles chargés en même temps ; profils legacy/8gb seulement, avertissement et multi-pass sur 16gb/24gb)
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

## Décodage RAW

Comment les fichiers RAW sont convertis en pixels. Facet utilise deux profils :

- **Profil de métriques** : le dématriçage à partir duquel chaque score est calculé (et l'espace de pixels des cadres de visages et de `image_width`/`image_height`). Un seul gain d'exposition fixe pour toute la bibliothèque, aucune adaptation par vue.
- **Profil d'affichage** : ce que montrent la miniature stockée, la galerie et `/image`. Il préfère l'aperçu intégré au boîtier (la courbe de tons et l'exposition propres au boîtier), et se rabat sur le dématriçage des métriques.

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `bright` | `1.62` | Gain d'exposition fixe pour chaque dématriçage (`1.0` = niveau propre de LibRaw ; `1.62` ≈ +0,7 IL de darktable) |
| `prefer_embedded_preview` | `true` | Afficher l'aperçu du boîtier lorsqu'il y en a un ; `false` dématrice tout (plus lent, sans la courbe de tons du boîtier) |
| `preview_min_sensor_ratio` | `0.5` | Part du capteur qu'un aperçu doit couvrir pour que `/image` l'utilise au lieu de dématricer |
| `viewer_concurrency` | `3` | Nombre maximal de dématriçages RAW simultanés pour `/image` et `/thumbnail` de la visionneuse, distinct de `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | Afficher les vues d'un bracketing sans aucune correction (ni aperçu, ni gain `bright`) ; voir [plus bas](#les-vues-dun-bracketing-saffichent-sans-correction) |

Remarques :
- `bright` est la seule constante arbitraire ici. Vérifiez-la sur votre bibliothèque avec `--check-raw-rendering` avant un gros scan.
- Nikon, Pentax, Samsung et Canon CR3 intègrent un aperçu quasi pleine taille (0,98-0,99). Panasonic se situe à 0,52. Olympus, Fuji, Sony et DNG en intègrent un petit (0,29-0,49) et sont donc dématricés.

### Compromis mémoire

`viewer_concurrency` et `processing.raw_decode_concurrency` sont des budgets distincts. Dans le pire des cas les deux s'exécutent en même temps, et chaque dématriçage atteint un pic d'environ 200-400 Mo. Baissez `viewer_concurrency` sur un hôte à mémoire limitée. En pratique, seuls les fichiers Sony, Fuji, Olympus et DNG utilisent le budget de la visionneuse, car les autres ont un aperçu assez grand.

### Pourquoi il n'y a pas de luminosité automatique

L'éclaircissement automatique de LibRaw s'adapte à chaque vue, si bien qu'un bracketing ressort avec toutes ses vues à peu près à la même luminosité. Le gain fixe conserve l'échelle d'exposition réelle entre les vues.

Augmenter `bright` éclaircit tous les rendus. Les métriques d'exposition suivent : relancez `--recompute-average` après l'avoir changé, et rescannez pour réécrire les métriques elles-mêmes.

### Les vues d'un bracketing s'affichent sans correction

Une photo dont le `sequence_kind` est `bracket` ou `hdr_panorama` s'affiche sans aperçu du boîtier et sans gain `bright`. Les deux écrêteraient les hautes lumières que vous jugez dans un bracketing. Un simple `panorama` n'est pas concerné.

Où cela s'applique :
- `/image` (vue détail, loupe de comparaison, loupe de tri), rendu à la volée.
- Les vignettes de la galerie et la grille de comparaison, après `--refresh-thumbnails`.
- `GET /api/download` avec `type=original`.

Non concernés : `type=raw` (le RAW intact), `type=darktable` (l'export avec rendu retouché), `GET /api/photo/cull_preview` (rendu par darktable-cli) et le calcul des scores.

La détection des séquences s'exécute après un scan : lancez d'abord `--detect-sequences`, puis `--refresh-thumbnails`, pour que les vignettes suivent.

Définissez `faithful_bracket_render` à `false` pour afficher les bracketings comme n'importe quelle autre photo.

### Migration d'une bibliothèque scannée avant ce profil

Les miniatures et les histogrammes sont stockés au moment du scan ; changer de profil ne modifie donc pas les photos déjà scannées. `photos.render_version` indique quel rendu a produit chaque miniature stockée :

- `NULL` : antérieur au marquage
- `1` : aperçu du boîtier d'abord, gain `bright` sur le repli par dématriçage (ce que stocke chaque scan)
- `2` : ni aperçu ni gain, pour une vue de bracketing (seul `--refresh-thumbnails` le stocke)

Deux actions seulement mettent à jour les miniatures stockées :
- **Un nouveau scan** réécrit la miniature et l'histogramme, et marque toujours `1`.
- **`--refresh-thumbnails`** réécrit les miniatures RAW et marque `1` ou `2` d'après le `sequence_kind` actuel. Il reconstruit chaque ligne : relancez-le après un changement de `bright` ou une passe `--detect-sequences`.

La vue détail (`/image`) est toujours à jour ; la grille de la galerie ne change qu'après l'une de ces deux actions.

La galerie affiche une bannière que l'on peut fermer et qui compte les photos encore sur l'ancien rendu. Elle peut avoir jusqu'à une heure de retard ; `python database.py --refresh-stats` la met à jour aussitôt.

Un rendu entièrement noir (par exemple un RW2 Panasonic tronqué) est refusé, journalisé avec le nom du fichier, et retenté lors d'une exécution ultérieure.

---

## Mappage de tons HDR PQ

Les images Canon HDR PQ (`.HIF`) portent la fonction de transfert PQ (SMPTE ST 2084) sur des primaires BT.2020, jusqu'à 10 000 nits. Les modèles de qualité et les miniatures exigent du sRGB SDR 8 bits ; Facet décode donc une image PQ à la profondeur native du boîtier, la convertit en sRGB et applique un mappage de tons. Ce bloc contrôle ce mappage.

Il ne s'applique **qu'**aux images dont le profil colorimétrique NCLX déclare le transfert PQ (caractéristique 16). Le HEIF SDR, le HLG et le JPEG passent sans modification, quelle que soit la valeur de `enabled`. Les images pivotées (Orientation EXIF autre que 1) ressortent droites, y compris sur le chemin en profondeur native : avec pillow-heif 1.6 et plus, le plan est tourné avant le mappage de tons.

```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Applique le mappage de tons des images PQ vers le SDR ; `false` les laisse sombres et délavées (débogage uniquement) |
| `method` | `hable` | Courbe de tons : `hable` (filmique, comme le filtre `tonemap` de ffmpeg) ou `clip` (linéaire avec écrêtage net, référence uniquement) |
| `white_point.mode` | `percentile` | Comment le point blanc de chaque image est choisi : `percentile`, `max` (pixel le plus lumineux) ou `fixed` (`fixed_nits`) |
| `white_point.percentile` | `99.99` | Percentile utilisé par le mode `percentile` |
| `white_point.min_nits` | `100.0` | Plancher du point blanc ; une image sombre n’est jamais normalisée sous le blanc de référence SDR |
| `white_point.max_nits` | `1200.0` | Plafond en mode `percentile` ; limite dans quelle mesure une image inhabituellement claire peut tirer la courbe vers le bas |
| `white_point.fixed_nits` | `1000.0` | Point blanc utilisé en mode `fixed` |
| `chroma_preserve` | `per_channel` | `per_channel` (plus lumineux, léger décalage de teinte dans les hautes lumières) ou `max_channel` (préserve la teinte, légèrement plus sombre) |

Le mode `max` laisse un seul pixel chaud d'une scène nocturne assombrir toute l'image ; `percentile` l'évite.

### Pourquoi le point blanc est déterminé par image

Un point blanc fixe de 100 nits écrête en blanc pur tout ce qui est plus lumineux, alors que de vraies images HDR culminent à des centaines, voire des milliers de nits. Facet normalise donc à un point blanc propre à chaque image, comme ffmpeg (`vf_tonemap.c`). Le p99.99 par défaut, borné à 100-1200 nits, conserve la texture des hautes lumières et ignore les pixels chauds isolés.

### Pourquoi le décodage se fait à la profondeur native du boîtier

Décoder le PQ en 8 bits avant le mappage de tons postérise les dégradés doux. Facet demande au décodeur HEIF la profondeur propre au fichier (10 bits sur les boîtiers actuels) et ne réduit à 8 bits qu'après la courbe de tons. Le gain se voit sur les contenus doux (ciels dégagés, fonds de studio, bokeh prononcé) ; les indicateurs d'écrêtage et `exposure_score` sont inchangés sur de vraies photos. Un décodeur qui ne peut pas fournir la profondeur native se rabat sur 8 bits.

**Références.** EOTF PQ : SMPTE ST 2084:2014. Courbe Hable et pic par image :
ffmpeg `vf_tonemap.c` (John Hable, « Filmic Tonemapping Operators », 2010).
Matrice BT.2020 vers sRGB : BT.2020-2 / IEC 61966-2-1 avec D65. OETF sRGB :
IEC 61966-2-1. Caractéristique de transfert NCLX 16 : ISO/IEC 23001-8 /
UIT-T H.273.

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

Avertit les utilisateurs en mode édition qu'une version plus récente de Facet existe. C'est distinct de l'invite du navigateur « une nouvelle version est disponible — Recharger ».

- La version en cours s'affiche en bas du menu utilisateur pour tous ceux qui peuvent ouvrir la visionneuse.
- Une image construite avec `--build-arg FACET_BUILD=<branch>@<commit>` affiche aussi cette ligne de build. `/api/config` renvoie les deux sous `version` et `build`, uniquement aux appelants qui peuvent lire la bibliothèque.
- Le serveur interroge GitHub au plus une fois par `interval_days`, sans jeton ni donnée de la bibliothèque. Un échec de vérification s'affiche comme « aucune mise à jour connue ».
- Seuls les utilisateurs en mode édition voient l'avis, au plus une fois par semaine et par navigateur.

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
| `enabled` | `true` | `false` désactive la vérification ; plus aucune requête n'est émise |
| `check_url` | API GitHub des dernières versions | Où chercher la dernière version publiée |
| `interval_days` | `7` | Durée de mise en cache du résultat avant une nouvelle interrogation |

---

## Détection de séquences

Étiquette les bracketings d'exposition pour qu'ils ne soient pas traités comme des prises concurrentes. L'exposition de chaque vue vient de `f_stop` / `shutter_speed` / `ISO` stockés (`EV = log2(N^2 / t) - log2(ISO / 100)`), si bien qu'une bibliothèque existante est étiquetée sans nouveau scan.

Une suite est un bracketing lorsque ses vues :
- viennent du même appareil, chacune à moins de `max_gap_seconds` de la précédente ;
- gardent le même cadrage (`max_hamming` sur le pHash) ;
- forment une échelle régulière d'expositions distinctes, dans n'importe quel ordre de prise (base d'abord `0, -, +` fonctionne comme du sombre au clair), couvrant `min_span_stops`, sur au moins `min_frames` vues.

Chaque vue reçoit `sequence_ev_offset`, son exposition relative à la vue de base, signée comme les étiquettes AEB d'un boîtier (`-2` sombre, `+2` clair). La base est le barreau du milieu. Avec un nombre pair de vues, la base est la vue centrale qui écrête le moins d'extrémités de son histogramme (la plus ancienne en cas d'égalité) ; un jeu impair comme `(-2, 0, +2)` utilise toujours sa vue centrale. Lorsqu'un groupe de rafale est exactement un bracketing, la galerie montre sa vue de base.

Lancé par `--detect-sequences` ; s'exécute aussi à la fin de chaque scan, après le
regroupement des rafales.

**Les corrections manuelles couvrent aussi les bracketings.** Marquez un bracketing manqué à la main depuis la galerie ou la salle de tri (*Marquer comme bracket*). Il faut ≥ 2 vues, chacune avec des données d'exposition exploitables, sans deux vues à la même exposition. Voir [docs/VIEWER.md — Panoramas et bracketings d'exposition](VIEWER.md#panoramas-et-bracketings-dexposition).

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

**Pourquoi `min_frames` est livré à `3`.** Deux vues espacées d'un diaphragme se ressemblent, qu'il s'agisse d'un AEB à deux prises ou d'une correction d'exposition rapide. Avec `2`, la plupart des jeux supplémentaires trouvés sur une bibliothèque de test n'étaient pas des bracketings. Une paire peut aussi être ce qui reste d'un jeu de trois prises ; la base (`sequence_ev_offset` `0`) peut alors tomber sur la mauvaise vue tandis que `hide_brackets` (activé par défaut) masque l'autre. Ne choisissez `2` que si vous faites de l'AEB à deux vues et acceptez quelques faux positifs.

---

## Détection de panoramas

Étiquette les vues sources de panoramas, que la détection de rafales masquerait sinon comme prises concurrentes. La détection met en correspondance des caractéristiques SIFT entre miniatures stockées de 640 px consécutives ; elle n'exige ni décodage de l'original, ni modèle, ni dépendance supplémentaire.

- Un balayage avance régulièrement dans une direction ; une rafale oscille autour d'un point. Les balayages simples et HDR sont des genres distincts, séparés selon l'étendue d'exposition.
- Précision mesurée d'environ 96 % sur une bibliothèque de test. Certains panoramas verticaux ou à peu de positions sont manqués.
- Vous pouvez corriger dans les deux sens avec le remplacement par ensemble.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Désactiver complètement la détection de panoramas |
| `max_gap_seconds` | `30.0` | Écart maximal entre deux images consécutives d'un balayage |
| `min_frames` | `8` | Plus courte suite traitée comme panorama (filtre le plus fort ; les non-panoramas comptaient 6 vues ou moins) |
| `min_drift` | `0.43` | Balayage total, en largeurs de vue, avant qu'une suite compte |
| `min_inliers` | `25` | Points concordants RANSAC requis pour valider une paire |
| `max_step` | `0.9` | Plus grand pas isolé, en largeurs de cadre — au-delà c'est une coupure de scène |
| `back_tolerance` | `0.02` | Recul toléré sur un pas avant que la série ne s'arrête |
| `max_ortho` | `0.15` | Dérive latérale tolérée sur l'ensemble du balayage |
| `ortho_ratio` | `0.25` | Marge latérale supplémentaire proportionnelle au balayage, pour ne pas pénaliser les longues séries |
| `step_ortho_abs` | `0.02` | Déplacement latéral toléré sur un seul pas avant d'être lu comme un recadrage |
| `step_ortho_ratio` | `0.5` | La même limite, en fraction de la taille du pas |
| `hdr_min_span_stops` | `1.5` | Étendue d'exposition au-delà de laquelle un balayage est un panorama HDR |
| `sift_features` | `400` | Caractéristiques par miniature ; le coût croît avec le carré de cette valeur |
| `match_ratio` | `0.75` | Rapport de Lowe qu'une correspondance doit franchir pour être retenue |
| `workers` | `0` | Processus de travail parallèles ; `0` se règle d'après le nombre de cœurs |
| `probe_stride` | `8` | Nombre d'images entre les sondages rapides qui écartent les rafales ordinaires |
| `probe_min_drift` | `0.05` | Mouvement en deçà duquel un sondage déclare la série immobile |
| `max_run_frames` | `500` | Plus longue suite candidate mesurée (borne la mémoire, ~220 Ko par vue et par worker) |

Remarques :
- `sift_features` prend environ 2,3 ms par paire de vues à 400, et environ 0,12 s à 3000.
- Changer un réglage ne fait rien tant que la détection n'est pas relancée : utilisez `--detect-panoramas` (ou l'action de relance de la visionneuse), qui re-mesure toute la bibliothèque.
- L'étape panorama après un scan, `--recompute-average` ou `--recompute-burst` ne re-mesure que les suites modifiées. Modifier tout réglage autre que `enabled` et `workers` la fait tout re-mesurer.
- Vos corrections s'appliquent à la passe suivante. Deux passes sur une bibliothèque inchangée trouvent les mêmes ensembles avec les mêmes numéros de groupe.

---

## Notation des rafales

Poids utilisés par le tri des rafales pour choisir la meilleure prise de chaque groupe de rafale. Les poids doivent totaliser 1,0.

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

Trouve les photos en double dans toute la bibliothèque : candidats pHash larges, confirmés par un contrôle de similarité d'embedding.

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
| `similarity_threshold_percent` | `90` | Seuil strict du pHash (90 % = distance de Hamming <= 6 sur 64 bits) ; le seul test lorsqu'une des photos n'a pas d'embedding |
| `prefilter_hamming` | `12` | Optionnel (absent du fichier livré). Seuil de Hamming large pour les candidats lorsque les deux photos ont des embeddings (au moins le seuil strict) |
| `embedding_cosine_threshold` | `0.90` | Optionnel (absent du fichier livré). Un candidat n'est fusionné que si le cosinus SigLIP/CLIP est >= à cette valeur |

- `python facet.py --detect-duplicates` détecte et regroupe les doublons.
- `python facet.py --sweep-dedup-thresholds [labels.json]` évalue le seuil de cosinus : avec un JSON d'étiquettes il affiche précision et rappel, sinon la distribution des cosinus des candidats et le nombre de correspondances pHash strictes que le seuil rejette.

---

## Niveau IQA étendu (optionnel)

Évaluateurs de qualité supplémentaires qui écrivent leurs propres colonnes ; ils ne remplacent jamais TOPIQ. Ils s'exécutent pendant un scan normal. Un échec de chargement ou de VRAM est journalisé et laisse la colonne à `NULL` ; le scan continue.

- `qrealign` vaut par défaut `"auto"` : **activé** pour les profils `8gb`/`16gb`/`24gb`, **désactivé** pour `legacy`/CPU.
- `aesthetic_v25` et `deqa` sont **DÉSACTIVÉS par défaut**.

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| Réglage | Défaut | Valeurs acceptées | Colonne | Description |
|---------|--------|-------------------|---------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | IQA esthétique Q-ReAlign-Mini 0,8B (Apache-2.0, ~2-3 Go de VRAM/RAM, sans pyiqa) |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini` (0,8B) ou `lite` (4B) ; aussi le modèle principal avec `licensing.mode: "commercial"` |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (tête SigLIP, ~2 Go) ; **déprécié**, préférez `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16 Go+ ; ignoré et laissé à NULL sinon) |

Remarques :
- **Tri :** chaque métrique apparaît dans le menu de tri de la visionneuse dès qu'au moins une photo a un score (**Q-ReAlign (esthétique)**, **Esthétique v2.5**, **DeQA**). Les photos sans score sont triées en dernier.
- `qrealign_score` contient la tâche esthétique ; la qualité utilise `quality_score`.
- `aesthetic_v25` nécessite le paquet `aesthetic-predictor-v2-5`. Il est sous licence AGPL-3.0 et sans maintenance en amont depuis le 2024-12-18.

**Installez les dépendances optionnelles** correspondant à ce que vous activez : `pip install -e .[iqa-extended]` (ajoute `aesthetic-predictor-v2-5`), ou décommentez la ligne correspondante dans `requirements.txt`. DeQA-Score se télécharge via `transformers`.

Chaque métrique est disponible pour l'agrégat pondéré avec un poids de 0, donc `--recompute-average` ne change rien tant que vous ne la pondérez pas. `python facet.py --eval-iqa-srcc` mesure à quel point chaque métrique correspond à vos propres notes en étoiles.

**Affichage dans la visionneuse.** Les valeurs renseignées apparaissent dans le panneau **Qualité** du détail de la photo (`Q-ReAlign`, `Esthétique V2.5`, `DeQA`), avec des curseurs de plage sous **Qualité étendue** dans les filtres de la galerie (`min_qrealign`/`max_qrealign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`).

> **Avertissement :** Les photos scannées avant l'activation d'une métrique ont `NULL` à cet endroit, et tout minimum ou maximum sur son curseur les masque. Relancez un scan avant de filtrer sur une métrique fraîchement activée.

**Robustesse.** DeQA-Score exécute du code de modèle distant (`trust_remote_code`). S'il échoue sur une image (changement de signature, sortie étrange, OOM), le `deqa_score` de cette image reste `NULL` et le scan continue.

---

## Licences

Détermine quels composants de modèles Facet peut charger. Voir [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md) pour le tableau des licences par composant.

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| Réglage | Défaut | Valeurs acceptées | Description |
|---------|--------|-------------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` charge tous les modèles ; `"commercial"` ne charge que les composants sûrs pour un usage commercial |
| `allow_unclear` | `false` | `true` / `false` | En mode commercial, autorise aussi les composants à licence *incertaine* (SAMP-Net, U2-Net-P, la tête esthétique LAION CLIP-MLP) ; doit être un booléen JSON |

En mode `"commercial"` :
- `pyiqa` (TOPIQ, HyperIQA, LIQE, ...) et InsightFace ne sont jamais importés ni téléchargés.
- L'esthétique et la qualité viennent de Q-ReAlign, la composition de l'analyseur à base de règles.
- Les visages utilisent la détection YuNet, des embeddings SFace de 128 dimensions, et en option MediaPipe pour les yeux/le sourire et la qualité de visage OFIQ.
- `liqe` et `aesthetic_iaa` restent à `NULL`. `deqa` (licence *incertaine*) exige `allow_unclear`. `aesthetic_v25` (AGPL) n'est jamais disponible.
- Un composant refusé arrête le scan au démarrage avec une `LicenceError` qui le nomme ainsi que son remplaçant.
- `--score-topiq`, `--recompute-iqa` (modèles pyiqa) et `--recompute-composition-gpu` se terminent avec ce message.
- Les composants à licence non commerciale restent refusés même avec `allow_unclear`.

Rien ici ne constitue un conseil juridique.

Surcharges par variables d'environnement (elles ne peuvent que resserrer ; une valeur invalide arrête le démarrage) :

| Variable | Effet |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` force le mode commercial ; `default` ou vide = aucune surcharge |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`, `false`, `no`, `off` forcent `allow_unclear` à off ; `1`, `true`, `yes`, `on` ou vide = aucune surcharge |

La visionneuse transmet `FACET_LICENSING_MODE=commercial` et, lorsque sa politique interdit les composants incertains, `FACET_LICENSING_ALLOW_UNCLEAR=0` à chaque processus `facet.py` qu'elle démarre. Une chaîne telle que `"false"` pour `licensing.allow_unclear` est rejetée au démarrage.

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
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `min_confidence_percent` | `65` | Confiance minimale de détection (InsightFace uniquement) |
| `min_face_size` | `20` | Taille minimale d'un visage en pixels (InsightFace uniquement) |
| `blink_ear_threshold` | `0.28` | Rapport d'aspect de l'œil (EAR) pour la détection de clignement |
| `min_faces_for_group` | `4` | Nombre minimal de visages pour classer en portrait de groupe (recalculé lors de `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Optionnel (absent du fichier livré). Charge `landmark_3d_68` d'InsightFace pour la pose de la tête (lacet/tangage/roulis) ; ~5 Mo, informatif uniquement |
| `eyes_closed_max` | `4.0` | Score yeux ouverts (0–10) en dessous duquel ou égal auquel la salle de tri signale un clignement (anneaux de visages, curseur des yeux) |
| `poor_expression_min` | `4.0` | Score sourire/expression (0–10) en dessous duquel la salle de tri signale une expression faible |
| `blendshapes.enabled` | `true` | Utilise les blendshapes MediaPipe pour `eyes_open_score` / `smile_score` lorsqu'il est installé, sinon la géométrie des repères |
| `blendshapes.min_crop_size` | `192` | Les visages dont le recadrage avec marge est plus petit que cette valeur (px, petit côté) utilisent le score géométrique |
| `blendshapes.blink_pose_gate_deg` | `null` | Mode commercial (MediaPipe) uniquement : seuil de pose de la tête en degrés ; `null` = désactivé |

Remarques :
- Le détecteur YuNet du mode commercial utilise des valeurs fixes (confiance 0,7, 30 px) et ignore `min_confidence_percent` et `min_face_size`.
- MediaPipe a besoin du bundle `face_landmarker.task`. Installez-le avec `pip install mediapipe==0.10.35 --no-deps`, jamais un simple `pip install mediapipe`. Voir [FACE_RECOGNITION.md](FACE_RECOGNITION.md#signaux-dexpression-par-visage-yeux-ouverts--sourire).
- `blink_pose_gate_deg` : un visage dont le |lacet| ou le |tangage| le dépasse n'obtient ni verdict de clignement ni score yeux ouverts / sourire (NULL), car une tête tournée se lit comme des yeux fermés. Aucun seuil entre 20° et 45° n'a amélioré la détection des clignements sur une bibliothèque de test ; il est donc livré désactivé. Ce doit être un nombre positif ; il s'applique aux photos nouvellement scannées (`is_blink` change au nouveau scan).

---

## Regroupement des visages

Regroupement HDBSCAN pour la reconnaissance des visages.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Activer le regroupement des visages |
| `min_faces_per_person` | `2` | Nombre minimal de photos par personne |
| `min_samples` | `2` | Paramètre min_samples de HDBSCAN |
| `clustering_algorithm` | `"best"` | Algorithme HDBSCAN |
| `leaf_size` | `40` | Taille des feuilles de l'arbre (CPU uniquement) |
| `use_gpu` | `"auto"` | Mode GPU : `auto`, `always`, `never` |
| `thresholds_by_model` | voir le JSON | Par modèle de reconnaissance : `auto_merge_distance_percent` et `merge_threshold`. Valeurs par défaut : ArcFace `15` / `0.6`, SFace `27.5` / `0.65` |

`merge_threshold` (similarité des centroïdes pour la mise en correspondance) et `auto_merge_distance_percent` (distance de fusion automatique) sont lus dans `thresholds_by_model` pour le modèle de reconnaissance **actif** (ArcFace par défaut, SFace en mode commercial). Un modèle sans entrée est une erreur. Les mêmes clés définies directement sous `face_clustering` ne sont plus lues.

**Notes sur le regroupement GPU (`use_gpu`) :**

- Nécessite les paquets optionnels `cuml` + `cupy`. L'image Docker GPU inclut cuML.
- Le profil `legacy` regroupe toujours sur CPU, quelle que soit la valeur de `use_gpu`.
- Sans périphérique CUDA utilisable, le regroupement se rabat sur HDBSCAN CPU.
- `always` avertit et utilise le CPU si cuML est absent ; une erreur GPU pendant le regroupement se rabat aussi sur le CPU.

**Algorithmes de regroupement :**

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
| `memory_limit_percent` | `80` | Pourcentage de la limite de mémoire effective (limite cgroup sous un plafond conteneur, sinon RAM hôte) |
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

**Remarque :** Le seuil de tag CLIP/SigLIP est `tag_threshold_percent` dans le bloc du profil actif : `models.clip` pour `16gb`/`24gb`, `models.clip_legacy` pour `legacy`/`8gb`. L'ancienne clé `similarity_threshold_percent` n'est plus lue. Si vous l'aviez personnalisée, copiez la valeur dans `tag_threshold_percent` ; le chargement de la configuration et `python facet.py --doctor` signalent l'ancienne clé.

À la fin d'un scan, l'étape de tagging est ignorée (avec une ligne de journal) lorsque `enabled` vaut `false` ou qu'aucune photo n'a à la fois un embedding et une liste de tags vide. Les photos qu'aucun tag ne correspond jamais restent en attente, donc le modèle se charge encore à chaque scan. `python tag_existing.py` (avec ou sans `--force`) et `python facet.py --tag-untagged` s'exécutent toujours.

### Modèles d'étiquetage disponibles

Configurés via `models.profiles.*.tagging_model` :

| Modèle | VRAM | Style d'étiquette | Notes |
|--------|------|-------------------|-------|
| `clip` | 0 (réutilise les embeddings) | Ambiance/atmosphère (dramatic, golden_hour, vintage) | Aucun chargement de modèle supplémentaire ; détection d'objets moins littérale |
| `qwen3.5-2b` | ~4 Go | Scènes structurées (landscape, architecture, reflection) | Nécessite transformers + VRAM supplémentaire |
| `qwen3.5-4b` | ~8 Go | Scènes détaillées avec nuance | VRAM plus élevée ; inférence plus lente |

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

Étiquettes avec listes de synonymes qui ne sont liées à aucune catégorie spécifique. Elles sont disponibles pour toutes les photos, quelle que soit l'attribution de catégorie. Chaque clé est le nom de l'étiquette ; la valeur est une liste de synonymes pour la correspondance CLIP/VLM.

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
| `quality_avg_threshold` | `7.5` | Seuil de qualité « haute valeur » |
| `quality_weight_threshold_percent` | `10` | Avertir si la pondération de qualité ≤ cette valeur |
| `correlation_dominant_threshold` | `0.5` | Avertissement « signal dominant » |
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
      "tooltip_mode": "panel",
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

> **Note :** `sort_options` (élidé en `{ ... }` ci-dessus) associe les colonnes de la base aux libellés du menu déroulant et est rarement modifié. Le groupe **Content** inclut un tri `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (les NULL sont relégués en dernier).

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `default_category` | `""` | Filtre de catégorie par défaut |
| `edition_password` | `""` | Mot de passe pour déverrouiller le mode édition ; vide = lecture seule (sauf sous `trusted_local_editing`) |
| `trusted_local_editing` | `false` | Accorde les droits d'édition à un navigateur du même ordinateur, sans mot de passe. Voir [Édition locale de confiance](#édition-locale-de-confiance) |
| `place_search_url` | `"https://photon.komoot.io/api"` | Point d'accès Photon pour la recherche **Rechercher en ligne** de la galerie ; `""` la désactive. Voir [Recherche de lieux en ligne](#recherche-en-ligne-de-lieux) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Comparaisons décisives (égalités exclues) nécessaires dans une catégorie avant de suggérer des poids |
| `pair_selection_strategy` | `"learning"` | Stratégie de paires : `learning`, `uncertainty`, `boundary`, `active`, `random` |
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
| `needs_naming_min_faces` | `5` | Nombre minimal de visages pour qu'un groupe apparaisse sous « À nommer » dans `/persons` ; `1` liste toutes les personnes non nommées |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nom du binaire darktable-cli ou chemin absolu |
| `darktable.profiles` | `[]` | Tableau de profils d'export darktable nommés (voir ci-dessous) |
| `darktable.profiles[].name` | *(requis)* | Nom d'affichage du profil (utilisé dans le menu de téléchargement et le paramètre API `profile`) |
| `darktable.profiles[].hq` | `true` | Passe `--hq true` pour un export haute qualité |
| `darktable.profiles[].width` | *(omettre)* | Largeur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].height` | *(omettre)* | Hauteur de sortie maximale (omettre pour la pleine résolution) |
| `darktable.profiles[].style` | *(omettre)* | Nom du style darktable appliqué lors de l'export (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | `false` passe `--apply-custom-presets false`, si bien que seul le `style` explicite s'applique |
| `darktable.profiles[].extra_args` | `[]` | Arguments CLI supplémentaires (par ex. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Styles darktable proposés comme aperçus au rendu retouché dans la salle de tri ; vide masque le sélecteur |
| `darktable.cull_styles[].name` | *(obligatoire)* | Nom du style darktable (passé à `--style`) |
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
| `good` | `6` | Seuil « bon » |
| `great` | `7` | Seuil « très bon » |
| `excellent` | `8` | Seuil « excellent » |
| `best` | `9` | Seuil « meilleur » |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimum pour Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Ratio de visage pour les pondérations |
| `low_light_max_luminance` | `0.2` | Seuil de faible luminosité |
| **defaults** | | |
| `type` | `""` | Filtre de type de photo par défaut (par ex. `"portraits"`, `"landscapes"`, ou `""` pour Toutes) |
| `sort` | `"aggregate"` | Colonne de tri par défaut (un tri mémorisé par le navigateur l'emporte ; voir [Tri](VIEWER.md#tri)) |
| `sort_direction` | `"DESC"` | Sens de tri par défaut (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Masquer les photos avec clignement par défaut |
| `hide_bursts` | `true` | Afficher uniquement la meilleure de chaque rafale par défaut |
| `hide_duplicates` | `true` | Masquer les doublons non principaux par défaut |
| `hide_brackets` | `true` | Afficher uniquement l'exposition de base de chaque bracketing par défaut |
| `hide_panoramas` | `true` | N'afficher qu'une image représentative par panorama par défaut |
| `hide_details` | `true` | Masquer les détails des photos sur les cartes par défaut |
| `tooltip_mode` | `"panel"` | Déclencheur de l'infobulle : `"hover"`, `"click"`, `"off"` ou `"panel"` (rail ancré) ; remplace `hide_tooltip` |
| `panel_activation` | `"both"` | Geste qui change la photo du rail ancré en mode `"panel"` : `"hover"`, `"click"` ou `"both"` |
| `hide_rejected` | `true` | Masquer les photos rejetées par défaut |
| `gallery_mode` | `"mosaic"` | Disposition de galerie par défaut (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origines CORS autorisées ; ajoutez votre domaine ou l'URL de votre reverse proxy en cas d'hébergement distant |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(défaut compatible SPA)_ | En-tête Content-Security-Policy ; `""` le désactive, ou fournissez une politique plus stricte |
| `security_headers.hsts` | `false` | Envoyer `Strict-Transport-Security`. À activer uniquement lorsque la visionneuse est servie en HTTPS. |
| **Autres** | | |
| `cache_ttl_seconds` | `3600` | TTL des caches de statistiques/requêtes en mémoire ; gardez-le plus long qu'un calcul complet des statistiques (qui peut prendre des minutes) |
| `notification_duration_ms` | `2000` | Durée des notifications toast |
| `moment_confidence_min` | `0` | Les libellés de moments sous cette confiance (0–1) s'affichent atténués avec « (incertain) » ; `0` = jamais atténué |

Remarques :
- **`trusted_local_editing`** ne s'applique que tant que `password` et `edition_password` sont tous deux vides sur une installation mono-utilisateur. Il couvre toutes les routes réservées à l'édition, scans compris, et permet à la boîte de dialogue Connect de créer un jeton d'assistant **Édition complète** pour les requêtes `/mcp` de la même machine.

> **Avertissement :** N'activez jamais `trusted_local_editing` derrière un reverse proxy sur le même hôte.

- **`pair_selection_strategy` :** `learning` choisit d'abord des paires variées, puis les paires que le modèle classe de façon incohérente.
- **`darktable.cull_styles`** alimentent `GET /api/photo/cull_preview`. Chaque style **doit déjà exister** dans la configuration darktable de l'utilisateur qui exécute la visionneuse.
- La Content-Security-Policy par défaut autorise les ressources propres à la SPA : script/style de thème en ligne, Google Fonts, tuiles OpenStreetMap et API de même origine.
- `moment_confidence_min` atténue les libellés dans l'en-tête Scènes, l'en-tête de groupe de scène du tri et l'infobulle de la galerie.

### Badges de carte et écrêtage

`viewer.badges` active ou désactive chaque badge des cartes de la galerie. Les anciens badges valent `true` par défaut, donc omettre le bloc ne change rien.

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| Clé | Défaut | Description |
|-----|--------|-------------|
| `badges.favorite` | `true` | Badge cœur sur une photo favorite (mode édition) |
| `badges.star_rating` | `true` | Badge étoile + compteur sur une photo notée (mode édition) |
| `badges.rejected` | `true` | Badge pouce baissé sur une photo rejetée (mode édition) |
| `badges.sequence_kind` | `true` | Badge d'ensemble (rafale/bracketing/panorama/doublon), affiché tant que la bascule de masquage correspondante replie l'ensemble |
| `badges.sequence_override_pending` | `true` | Badge horloge pour une correction de panorama en attente de la prochaine détection |
| `badges.stack` | `true` | Badge de couches + nombre de membres sur les cartes d'une pile de photos manuelle ; un clic ouvre la pile |
| `badges.keeper_hint` | `true` | Flèche « une meilleure photo existe dans ce groupe » issue du modèle de sélection appris |
| `badges.best_of_burst` | `true` | Badge « TOP » sur le chef d'une rafale, affiché uniquement quand `hide_bursts` est désactivé |
| `badges.clipping_highlight` | `true` | Badge sur une photo dont les hautes lumières dépassent `clipping.badge_percent` |
| `badges.clipping_shadow` | `false` | Même chose pour les ombres bouchées (désactivé : souvent voulu dans les silhouettes, la nuit, le low-key) |

Désactiver `badges.stack` ne masque que le badge ; le bouton de carte « Ouvrir la pile de photos » fonctionne toujours.

`viewer.clipping` définit une seule fois ce qu'est « écrêté » pour le badge de carte, les repères de l'histogramme et le filtre de la galerie.

| Clé | Défaut | Description |
|-----|--------|-------------|
| `badge_percent` | `5` | Pourcentage de pixels, dans le pire de R/V/B, au-dessus duquel la carte reçoit un badge (environ 1 photo sur 25 sur un échantillon) |
| `indicator_percent` | `1` | Seuil des repères d'extrémité R/V/B propres à l'histogramme |
| `histogram_mode` | `"rgb"` | Valeur par défaut de l'histogramme du **panneau de détail** : `"luma"`, `"rgb"`, `"r"`, `"g"` ou `"b"` |
| `tooltip_histogram_mode` | `"luma"` | Valeur par défaut de l'onglet Histogramme du **panneau latéral** (`tooltip_mode: "panel"`), mêmes cinq valeurs |

Remarques :
- Le choix d'histogramme d'un utilisateur est stocké dans `localStorage` (`facet_histogram_mode`, `facet_histogram_mode_tooltip`) et l'emporte sur ces valeurs par défaut. Les deux réglages sont indépendants.
- Les bulles **Survol** et **Clic** n'affichent aucun histogramme.

**L'écrêtage se mesure par canal, exactement aux cases 0 et 255.** Il est stocké dans `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` comme la part de pixels du pire canal. Cela diffère des indicateurs `shadow_clipped` / `highlight_clipped`, qui couvrent les bandes de luminance 0–30 et 225–255 et alimentent `exposure_score`.

**`NULL` signifie inconnu, jamais propre.** Une photo avec un histogramme stocké plus ancien n'a pas de données par canal ; elle n'a donc aucun badge et ne correspond à aucun côté du filtre de la galerie. `python facet.py --backfill-clipping` remplit les colonnes à partir des histogrammes stockés ; il ne décode aucune image et peut être repris.

### Fonctionnalités

Activez ou désactivez des fonctionnalités optionnelles pour réduire l'utilisation mémoire ou simplifier l'interface :

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
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
| `show_similar_button` | `true` | Afficher le bouton « Trouver des similaires » sur les cartes photo (utilise numpy pour la similarité CLIP) |
| `show_merge_suggestions` | `true` | Activer la fonctionnalité de suggestions de fusion sur la page de gestion des personnes |
| `show_rating_controls` | `true` | Afficher les commandes de notation par étoiles et de favori |
| `show_scan_button` | `false` | Affiche le bouton de déclenchement du scan (pas de GPU nécessaire ; voir les remarques) |
| `metrics_enabled` | `false` | Active le point d'accès Prometheus public `GET /metrics` (voir l'avertissement ci-dessous) |
| `show_semantic_search` | `true` | Afficher la barre de recherche sémantique (recherche texte-vers-image via les embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Afficher la fonctionnalité d'albums (créer, gérer et parcourir des albums photo) |
| `show_critique` | `true` | Afficher le bouton de critique IA sur les cartes photo (décomposition de score fondée sur des règles) |
| `show_vlm_critique` | `true` | Active la critique VLM (profil 16gb/24gb) ; `false` si la clé est absente |
| `show_embed_metadata` | `true` | Affiche « Écrire les métadonnées dans le fichier » en mode édition (intègre notes/mots-clés via exiftool) |
| `show_memories` | `true` | Afficher la boîte de dialogue souvenirs « Ce jour-là » (photos prises à la même date les années précédentes) |
| `show_captions` | `true` | Afficher les légendes générées par IA sur les cartes photo |
| `show_timeline` | `true` | Afficher la vue chronologique pour un parcours chronologique avec navigation par date |
| `show_map` | `true` | Affiche la vue carte GPS (nécessite Leaflet) ; `false` si la clé est absente |
| `show_capsules` | `true` | Afficher la vue Capsules (diaporamas de photos sélectionnées regroupées par thème) |
| `show_folders` | `true` | Afficher le parcours par dossiers de la structure de répertoires photo |
| `show_scenes` | `true` | Affiche la vue Scènes (`/scenes`), des chefs de rafale regroupés en scènes chronologiques |
| `show_my_taste` | `true` | Affiche le tri « Mes goûts » du classeur personnel, avec un badge de confiance |
| `show_social_export` | `true` | Affiche le menu de téléchargement **Recadrage social**, réservé à l'édition. Voir [Export pour les réseaux sociaux](#export-social) |
| `show_portfolio_export` | `true` | Affiche l'action d'album **Exporter le portfolio**, réservée à l'édition. Voir [Export de portfolio](#export-de-portfolio) |
| `show_proofing` | `false` | Active la épreuvage client sur les albums partagés. Voir [Épreuvage client](#épreuvage-client) |

Remarques :
- **`show_scan_button` :** visible pour le superadmin en mode multi-utilisateur, ou pour une session d'édition déverrouillée en mode mono-utilisateur. Les scans s'exécutent sur CPU seul avec le profil `legacy`. Une session locale de confiance (`trusted_local_editing`) peut scanner sans lui.
- **Optimisation mémoire :** `show_similar_button: false` empêche numpy de se charger, ce qui réduit la mémoire de la visionneuse.

> **Avertissement :** `metrics_enabled` expose les nombres de photos/personnes/visages, la taille de la base et la mémoire du processus. Ne l'activez que là où le réseau du collecteur peut l'atteindre, jamais sur l'internet public.

### Épreuvage client

`viewer.features.show_proofing` (par défaut `false`) transforme tout album partagé en page de épreuvage client. Un client disposant du lien de partage (et du `viewer.proofing.pin` facultatif) peut mettre des cœurs et laisser des commentaires sans compte. Le propriétaire les consulte depuis une boîte de dialogue réservée à l'édition, sur la carte de l'album. Les choix des clients ne touchent jamais aux notes du propriétaire et n'entraînent pas le classeur personnel.

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
| `proofing.pin` | `""` | PIN facultatif que le client doit saisir avec le lien de partage ; vide = pas de PIN (les tentatives sont limitées) |
| `proofing.session_minutes` | `1440` | Durée de vie de la session client en minutes (24 h) ; elle prend fin aussitôt si l'album n'est plus partagé ou si la validation est désactivée |

### Mappage de chemins

Fait correspondre les chemins de la base à des chemins locaux, lorsque les photos ont été analysées sur une machine (par ex. Windows avec chemins UNC) et que la visionneuse tourne sur une autre (par ex. un NAS Linux).

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
| `path_mapping` | `{}` | Préfixe source → préfixe de destination, appliqué à la lecture des fichiers sur le disque |

**Fonctionnement :**
- S'applique uniquement à la **lecture de fichiers sur le disque** (images pleine taille, téléchargements, critique VLM). Les chemins de la base ne sont jamais modifiés.
- Les barres obliques inverses et normales sont normalisées : `\\NAS\Photos\img.jpg` et `//NAS/Photos/img.jpg` correspondent toutes deux.
- Les mappages sont évalués dans l'ordre ; le premier préfixe correspondant l'emporte.
- Les cibles de correspondance sont ajoutées automatiquement à la liste d'autorisation des dossiers du mode multi-utilisateur.

**Exemple :** une base remplie sous Windows stocke des chemins comme `\\NAS\Photos\2024\IMG_001.jpg`. Sous Linux, le même partage est monté sur `/mnt/nas/Photos`. Configurez :

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Protection par mot de passe

Protection par mot de passe optionnelle pour la visionneuse :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Une fois défini, les utilisateurs doivent se connecter avant d'utiliser la visionneuse.

### Édition locale de confiance

Permet à une visionneuse mono-utilisateur, utilisée uniquement depuis un navigateur du même ordinateur, de modifier sans mot de passe d'édition :

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

Il ne s'applique que tant que `viewer.password` **et** `viewer.edition_password` sont vides, que le mode multi-utilisateur est désactivé et que la configuration s'est chargée sans erreur. Définir un mot de passe d'édition le désactive. Il ne définit ni ne révèle aucun mot de passe, ne change aucun jeton et n'active pas l'administration multi-utilisateur.

Facet vérifie chaque requête. Une requête n'est de confiance que si toutes ces conditions sont réunies :

- le pair TCP est une adresse loopback (un pair IPv4 mappé comme `::ffff:127.0.0.1` est jugé sur son adresse IPv4) ;
- il y a exactement un en-tête `Host`, et il vaut `localhost`, `127.0.0.1` ou `[::1]`, avec un port facultatif ;
- la requête ne porte aucun en-tête `Forwarded`, `Via`, `X-Real-IP`, `X-Client-IP`, `True-Client-IP`, `CF-Connecting-IP`, `X-Original-Forwarded-For` ni `X-Forwarded-*` ;
- un `Origin` ou `Referer`, s'il est présent, nomme exactement le schéma, l'hôte et le port, sans identifiants (un `Origin` avec chemin, requête ou fragment est refusé) ; un `Sec-Fetch-Site`, s'il est présent, vaut `same-origin` ou `none`.

Toute autre requête est traitée comme si l'option était désactivée, requêtes GET comprises.

Une requête de confiance a tous les droits d'édition sur chaque route réservée à l'édition : notes, comparaisons, tri (y compris **Trier vers un dossier**, qui déplace ou met à la corbeille des fichiers, et la suppression par photo), albums, personnes et visages, poids, priorités et contextes d'évaluation, intégration et export des métadonnées, tâches de recalcul et de panorama, génération de légendes et de critiques. Elle peut aussi scanner sans `viewer.features.show_scan_button`. Le flux de progression du scan n'accepte un jeton de flux local de confiance que depuis la même machine locale.

**Assistants.** La boîte de dialogue Connect peut alors créer un jeton **Édition complète** (il faut toujours `viewer.mcp.enabled`).

- Le jeton n'agit comme `edition` que pour les requêtes `/mcp` qui passent les vérifications ci-dessus : `http://localhost:<port>` ou `127.0.0.1`, sur `:5000` ou le proxy de développement `ng serve` `:4200`.
- Depuis un client du réseau local, une URL à nom d'hôte ou `0.0.0.0`, ou un déploiement Docker, il agit comme `readonly`. Définir un mot de passe le rend aussi `readonly` ; l'effacer le rétablit.
- Les outils de suppression exigent toujours `viewer.mcp.allow_destructive`. Voir [Agents IA (MCP)](AGENTS.md).
- Sur une installation ouverte, la création, la liste et la révocation des jetons d'assistant ne fonctionnent que depuis une requête qui passe ces vérifications (ou une session d'édition lorsque `viewer.edition_password` est défini), quelle que soit la valeur de `trusted_local_editing`.
- `ng serve --host 0.0.0.0`, ou un proxy sur le même hôte qui n'ajoute aucun en-tête de transfert, laisse un client du réseau local passer avec `Host: localhost`. Un reverse proxy doit envoyer `X-Forwarded-For` ou `Forwarded`.

> **Avertissement :** Seule la vérification de la boucle locale est une vraie frontière ; les autres en-têtes viennent du client. Un reverse proxy, un tunnel ou une redirection de port sur le même hôte qui n'ajoute aucun des en-têtes ci-dessus ressemble exactement à votre navigateur. N'activez jamais cette option derrière un reverse proxy sur le même hôte. Tant qu'elle est activée, tout processus et tout compte local de l'ordinateur peut modifier.

### Recherche en ligne de lieux

`viewer.place_search_url` vaut par défaut `https://photon.komoot.io/api`.

- Définissez `""` pour désactiver la recherche d'adresses/commerces, ou pointez vers un point d'accès HTTP(S) Photon auto-hébergé (sans identifiants, paramètres de requête ni fragments).
- Le navigateur n'apprend que `place_search_enabled`, jamais l'URL.
- Les recherches exigent l'accès en édition et un clic explicite sur **Rechercher en ligne**. Il n'y a ni nouvelles tentatives ni redirections.
- Une requête expire au bout de cinq secondes ; la résolution DNS suit le résolveur du système et peut prendre plus de temps.

Voir [Recherche de lieux en ligne](VIEWER.md#recherche-en-ligne-de-lieux) pour la confidentialité, le cache et les limites. La [politique de la démo Photon](https://github.com/komoot/photon#demo-server) autorise un usage raisonnable par le projet sans garantie de disponibilité ; la [documentation de l'API Photon](https://github.com/komoot/photon/blob/master/docs/api-v1.md) définit son format GeoJSON.

### Performance de la visionneuse

Surcharge les réglages globaux `performance` pour la visionneuse seule, par ex. sur un NAS à faible mémoire.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
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

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `mmap_size_mb` | `2048` | Taille des E/S mappées en mémoire SQLite |
| `cache_size_mb` | `128` | Taille du cache SQLite |
| `wal_checkpoint_minutes` | `30` | Optionnel (absent du fichier livré). Minutes entre les checkpoints WAL d'arrière-plan de la visionneuse ; `0` les désactive |
| `slow_request_ms` | `1000` | Journalise les requêtes de l'API de la visionneuse plus lentes que cette valeur (WARNING, marqueur `SLOW`) ; `0` désactive |

Le checkpoint périodique (`PRAGMA wal_checkpoint(TRUNCATE)`) garde le fichier WAL petit sur les installations de longue durée ; un checkpoint s'exécute aussi à l'arrêt propre.

---

## Stockage

Où sont stockés les miniatures et les embeddings : colonnes BLOB de la base SQLite (par défaut), ou fichiers sur disque pour alléger la base.

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
| `mode` | `"database"` | Backend de stockage : `"database"` (BLOBs SQLite) ou `"filesystem"` (fichiers sur disque) |
| `filesystem_path` | `"./storage"` | Dossier de base du mode système de fichiers (`<path>/thumbnails/` et `<path>/embeddings/`) |

**Détails du mode système de fichiers :**
- Les fichiers sont nommés d'après le hachage SHA-256 du chemin de la photo, dans des sous-dossiers de deux caractères (par ex. `thumbnails/a3/a3f8..._640.jpg`).
- Supprimer une photo supprime toutes ses tailles de miniature et ses fichiers d'embedding.
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

Placez un fichier `.py` dans le répertoire `plugins/`. Définissez des fonctions nommées d'après les événements que vous souhaitez gérer :

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Voir `plugins/example_plugin.py.example` pour l'interface complète.

### Webhooks

Chaque webhook reçoit un POST JSON. Les adresses privées et de bouclage sont bloquées :

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

Options de webhook : `url` (requis), `events` (liste de noms d'événements), `min_score` (agrégat minimal pour déclencher).

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

Diaporamas organisés par thème, générés à partir de votre bibliothèque et mis en cache pendant `freshness_hours`.

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
| `mmr_lambda` | `0.5` | Pondération de diversité MMR : 0 = maximiser la diversité, 1 = maximiser la qualité |
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
| `this_week` | « Cette semaine, il y a des années » — extension de Ce jour-là sur ±3 jours |
| `location` | Clusters de photos géolocalisées avec noms de lieux géocodés en inverse |
| `person_pair` | Paires de personnes nommées apparaissant ensemble |
| `seeded` | Découverte à base de graines via le temps, la similarité, la personne, l'étiquette, le lieu, l'ambiance |
| `progress` | « Votre photographie s'améliore » à partir des tendances de score trimestrielles |
| `color_palette` | « Couleur du mois » à partir des profils de saturation/monochrome |
| `rare_pair` | Paires de personnes peu fréquentes dans les photos bien notées |
| `favorites` | Photos favorites regroupées par année et saison |

### Capsules fondées sur des dimensions

Générées automatiquement à partir des colonnes de la base :

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
| `focal_range` | Tranches de focale : ultra grand-angle (<24 mm), grand-angle (24–35 mm), standard (36–70 mm), portrait (71–135 mm), téléobjectif (136–300 mm), super téléobjectif (300 mm+) |
| `category` | Catégorie de contenu de la photo (portrait, paysage, rue, etc.) |
| `time_of_day` | Tranches horaires : matin doré, matin, midi, après-midi, soir doré, nuit |
| `star_rating` | Notes en étoiles de l'utilisateur (1–5 étoiles) |

Des combos transversaux sont également générés (par ex. appareil × année, focal_range × category, category × year).

### Transitions du diaporama

Chaque type de capsule correspond à une transition de diapositive thématique :

| Transition | Utilisée par | Effet |
|-----------|--------------|-------|
| `crossfade` | Par défaut | Échange d'opacité en 300 ms |
| `slide` | journey, location, this_week | Glissement depuis la droite (500 ms) |
| `zoom` | faces_of, color_story | Échelle 1,05→1,0 avec fondu (400 ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lent 1,0→1,08 sur la durée de la diapositive |

### Géocodage inverse

Les capsules de lieu et de voyage utilisent le géocodage inverse hors ligne via le paquet `reverse_geocoder` (jeu de données GeoNames local, ~30 Mo, aucun appel d'API). Les résultats sont mis en cache à une résolution de grille de 0,1° (~11 km).

Installer : `pip install reverse_geocoder`

Mettez `"reverse_geocoding": false` pour désactiver et revenir à l'affichage des coordonnées.

## Groupes de similarité

Réglages du tri par similarité, qui regroupe les photos visuellement proches d'après leur embedding CLIP/SigLIP :

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
| `default_threshold` | `0.85` | Similarité cosinus minimale (0,0–1,0) pour que deux photos comptent comme similaires ; plus bas = groupes plus grands et plus lâches |
| `min_group_size` | `2` | Nombre minimal de photos requis pour former un groupe de similarité |
| `max_photos` | `10000` | Nombre maximal de photos chargées pour la comparaison (le coût croît en O(n²)) |
| `max_group_size` | `50` | Nombre maximal de photos par groupe ; les groupes plus grands sont scindés |

## Tri automatique

Tri automatique en un bouton pour la salle de tri (`POST /api/culling/auto`, réservé à l'édition). Il trie tout un périmètre en une passe : tous les groupes, ou seulement les rafales / similaires / scènes, éventuellement limités à un album ou à une fenêtre de dates. Chaque groupe garde sa meilleure photo plus tout ce qui se trouve dans une marge fixée par la rigueur (comme avec le curseur de la salle), au moins un minimum par groupe, et rejette le reste.

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
| `default_strictness` | `50` | Budget de photos à garder (0–100) quand la requête omet `strictness` ; plus élevé garde moins de photos par groupe |
| `highlights_min` | `8.0` | Agrégat minimal pour que la meilleure photo d'un groupe rejoigne l'album **Coups de cœur** facultatif à l'application |

- `dry_run` est activé par défaut et renvoie un aperçu garder/rejeter par groupe.
- L'application enregistre des comparaisons `source='culling'` et compte pour un ré-entraînement automatique. Voir [Visionneuse web — Sélection automatique](VIEWER.md#tri-automatique).
- Les mêmes réglages alimentent `python facet.py --auto-cull` (voir [Tri](COMMANDS.md#tri-en-ligne-de-commande)) ; ses règles viennent de la configuration du serveur, pas de `--config`.

## Ré-entraînement automatique

Contrôle le moment où le classeur personnel (« Mes goûts ») se ré-entraîne. Chaque confirmation de tri et chaque changement de note incrémente un compteur par utilisateur. Franchir `threshold` arme le ré-entraînement, qui démarre une fois que vous êtes inactif pendant `idle_seconds`, afin de ne pas ralentir votre notation.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `threshold` | `25` | Nouvelles comparaisons nécessaires avant d'armer un ré-entraînement ; augmentez-le si vous notez de très gros lots |
| `idle_seconds` | `60` | Secondes sans activité de notation/tri avant que le ré-entraînement armé démarre ; `0` le démarre aussitôt |
| `backend` | `"native"` | `"native"` entraîne en local ; `"external"` ne garde que les préférences et les compteurs. Voir [Backend d'apprentissage externe](#backend-dapprentissage-externe) |

Les variables d'environnement surchargent `threshold` et `idle_seconds` (pratique pour Docker) :

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variable | Surcharge |
|----------|-----------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- Un `threshold` ou `idle_seconds` invalide retombe sur la valeur du JSON, puis sur la valeur intégrée par défaut. Les deux sont lus au démarrage ; les changements exigent un redémarrage.
- Un `auto_retrain.backend` invalide retombe sur `"external"` (voir ci-dessous).
- Un ré-entraînement qui ne bat pas le modèle actuel sur des données de validation ne sauvegarde rien.

### Backend d'apprentissage externe

`"backend": "external"` conserve les notes, les comparaisons et les compteurs en attente, mais n'entraîne ni n'évalue jamais en local le classeur personnel, la tête de sélection ni les poids appris. Utilisez-le quand un flux séparé, géré par l'opérateur, entraîne et publie les scores. Facet ne démarre aucun worker externe.

En mode externe :
- Les commandes manuelles du classeur personnel, de la tête de sélection et de l'apprentissage des poids signalent que l'entraînement est différé.
- Les probabilités de sélection sont indisponibles ; les réponses de Compare sur les poids appris et la confiance indiquent `available: false`.
- La notation normale des photos et les votes ne sont pas affectés.

Un bloc `auto_retrain` mal formé, un `backend` autre que `"native"` ou `"external"`, ou une configuration illisible sélectionne le mode externe et journalise un avertissement. Une configuration valide sans clé `backend` utilise le mode natif.

## Profils de tri par genre

Préréglages par genre qui règlent tous les paramètres de tri en un clic, depuis un sélecteur de la salle de tri. Le sport ne garde que l'image la plus nette d'une longue rafale ; les mariages gardent plus de variantes et exigent les yeux ouverts ; les concerts assouplissent les seuils yeux/expression ; la faune sauvage supprime le seuil de visage.

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
| `profiles.<id>.strictness` | Budget de photos à garder (0–100) pour le tri automatique avec ce préréglage |
| `profiles.<id>.eyes_closed_max` | Score yeux ouverts (0–10) en dessous duquel ou égal auquel un visage compte comme fermé (remplace `face_detection.eyes_closed_max`) |
| `profiles.<id>.poor_expression_min` | Score expression/sourire (0–10) en dessous duquel un visage compte comme médiocre (remplace `face_detection.poor_expression_min`) |
| `profiles.<id>.keep_min_per_group` | Plancher par groupe sur l'ensemble conservé par l'auto-tri |
| `profiles.<id>.similarity_threshold` | Seuil de regroupement par similarité (pourcentage) appliqué quand le préréglage est sélectionné |

`GET /api/culling/profiles` renvoie la liste ordonnée des préréglages et celui par défaut. `POST /api/culling/auto` et `POST /api/culling-group/faces` acceptent un identifiant `profile` facultatif ; un `strictness`/`min_keep_per_group` explicite dans la requête l'emporte sur le préréglage.

## Scènes

Réglages de la vue Scènes, qui regroupe les photos chefs de rafale en scènes chronologiques (coupées sur les écarts de temps de prise) pour un tri dans l'ordre de l'histoire :

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
| `gap_minutes` | `20.0` | Écart entre chefs de rafale consécutifs qui démarre une nouvelle scène (le plancher quand `adaptive` est activé) |
| `min_size` | `2` | Nombre minimal de photos pour qu'une scène soit affichée |
| `max_photos` | `5000` | Nombre maximal de photos de tête de rafale chargées pour le regroupement en scènes |
| `max_scene_size` | `60` | Les scènes plus grandes sont de nouveau scindées à leurs plus grands écarts internes |
| `adaptive` | `true` | Élargit l'écart à `adaptive_k × médiane` des écarts de la séance (plus serré pour une prise rapide, plus lâche pour les voyages clairsemés) |
| `adaptive_k` | `6.0` | Multiplicateur appliqué à l'écart médian lorsque `adaptive` est activé |
| `split_on_moment_change` | `false` | Avec les moments narratifs calculés, coupe aussi là où le moment dominant change pendant `moment_split_min_run` vues |
| `moment_split_min_run` | `4` | Nombre de vues consécutives qu'un nouveau moment doit durer pour imposer une limite de scène |

## Moments narratifs

Étiquette le « moment » de scène ou d'activité de chaque photo sans entraînement. Le vocabulaire **général** par défaut couvre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle`, ou `other`. `wedding` est livré comme genre facultatif. `--detect-moments` les remplit (il s'exécute aussi à la fin de chaque scan) ; ils apparaissent comme noms de scènes et comme filtre de la galerie.

Facet compare la légende IA de chaque photo, encodée une fois et stockée (`caption_embedding`), avec des invites textuelles pour chaque moment, et garde la meilleure correspondance. Sans légende, il utilise l'embedding de l'image. Les légendes correspondent plus nettement : le signal `caption` a donc des seuils plus élevés que le repli `image`, réglés par backend. Les valeurs `transformers` (SigLIP) sont des valeurs par défaut prudentes ; réajustez-les si vous utilisez un profil SigLIP.

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
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `enabled` | `true` | Interrupteur général ; désactivé, `--detect-moments` et le déclencheur du scan ne font rien |
| `prompt_template` | `"a photo of {desc}"` | Enveloppe appliquée à chaque prompt avant l'encodage |
| `default_event_type` | `"general"` | Vocabulaire `event_types` actif (`general` = 20 moments ; `wedding` facultatif) |
| `pooling` | `"max"` | Score par moment = la meilleure correspondance d'une seule invite |
| `caption_min_confidence` | `0` | Si > 0, la génération de légendes ignore les photos sans étiquette, `other`, ou sous cette confiance ; `0` = pas de seuil |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Sous ce cosinus top-1, une photo est `other` (indexé par signal, puis backend) |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Écart cosinus minimal top-1/top-2 ; en dessous, l'image est `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Petits coups de pouce visage/tag qui ne départagent que les quasi-égalités ; `weight` plafonne chaque bonus |
| `priors.caption_tag_scale` | `0.25` | Réduit les règles de **tag** sur le signal légende ; les règles structurelles gardent leur plein poids |
| `priors.rules` | (jeu général) | Liste de règles `{kind, when, boost}` (voir ci-dessous) |
| `priors.event_types.<et>.rules` | surcharge `wedding` | Règles qui **remplacent** les `rules` globales lorsque ce vocabulaire est actif |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Lissage temporel entre vues voisines (`weight=0` = aucun) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Sur 16gb/24gb, reclasse avec le VLM du profil uniquement les vues à faible confiance ou faible marge |
| `event_types` | `general` + `wedding` | `{moment: [synonymes de prompt]}` par type d'événement ; définissez `default_event_type` pour changer de genre ou ajouter le vôtre |

Format de `priors.rules` :
- `kind` : `structural` (géométrie des visages) ou `tag`.
- `when` (tout doit correspondre) : `is_group_portrait`, `face_count_min`/`face_count_max`, `face_ratio_min`/`face_ratio_max`, `tags_any`, `tags_all`.
- `boost` : `{moment: amount}`. Un moment absent du vocabulaire actif est ignoré.

Le départage par VLM s'exécute pendant `--detect-moments` / `--recompute-moments`.

> **Coût du remplissage des légendes.** Les embeddings de légendes sont calculés une fois et stockés. Un scan n'encode que ses nouvelles légendes, mais la première passe sur une bibliothèque existante encode chaque légende : rapide sur GPU, des heures sur CPU. Lancez `python facet.py --detect-moments` une fois (GPU recommandé) ; ajoutez `--limit N` pour essayer d'abord un échantillon.

**Découvrir un vocabulaire propre à la bibliothèque.** `python facet.py --discover-moments` regroupe les vecteurs `caption_embedding` stockés, nomme chaque groupe d'après ses légendes, et écrit un bloc `event_types.discovered` dans `scoring_config.discovered.json`. Il ne change jamais la configuration active. Pour l'adopter, copiez `discovered` dans `event_types`, définissez `default_event_type` à `discovered`, et lancez `--recompute-moments`. `--discover-min-cluster-size N` contrôle la granularité (plus petit = plus de moments, plus fins).

## OCR

Recherche de texte dans les photos : lit les mots *à l'intérieur* de vos photos (panneaux de rue, devantures, dossards, tranches de livres, diapositives, tableaux blancs, documents numérisés) dans `photos.ocr_text`. Ce texte est ensuite cherchable depuis la zone de recherche de la galerie comme une légende ou un tag ; `GET /api/search?scope=text` ne cherche que dans les champs de texte.

**Désactivé par défaut**, et nécessite l'installation d'un moteur :

```bash
pip install easyocr           # ou : pip install -e .[ocr]
```

Puis activez-le et lancez la passe :

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
| `enabled` | `false` | Interrupteur général ; `--detect-text` refuse de s'exécuter tant qu'il vaut `false` |
| `languages` | `["en", "fr"]` | Codes de langue transmis au moteur ; une famille d'écriture par exécution (easyocr rejette par ex. `en` + `ja`) |
| `min_confidence` | `0.4` | Ignore les détections notées en dessous (0–1) ; augmentez-le contre le bruit, baissez-le pour un texte faible |
| `full_resolution` | `false` | OCR sur l'original au lieu de la miniature de 640 px (bien plus lent ; se rabat sur la miniature hors ligne) |

Remarques :
- `ocr_text` vaut `NULL` tant qu'une photo n'est pas évaluée, et `''` quand elle n'a pas de texte. `--detect-text` ne lit que les photos `NULL` ; `--recompute-text` relit tout.
- **Pas besoin de `--rebuild-fts` :** la passe met à jour l'index de recherche à mesure qu'elle écrit. `python database.py --rebuild-fts` ne sert que pour une base créée avant l'OCR, et `init_database` s'en charge pour vous.
- La miniature de 640 px résout déjà les panneaux, les affiches et les titres de documents.

**Moteurs.** `easyocr` (Apache-2.0, PyTorch) est le moteur par défaut et réutilise la pile existante de Facet. Ses poids (~113 Mo) se téléchargent depuis les versions GitHub du projet au premier lancement. Le binaire `tesseract` plus `pytesseract` est utilisé quand easyocr est absent, mais lit moins bien le texte de scène. Si aucun des deux n'est installé, la passe se termine avec une erreur.

**Coût.** Environ 0,4 s par miniature sur CPU : une bibliothèque de 50 000 photos est donc une tâche unique d'une nuit ; les scans suivants n'ajoutent que les nouvelles photos. Un GPU est utilisé automatiquement quand torch en signale un.

## Destinations d'export et de tri

L'export d'album (`POST /api/albums/{id}/export`, modes `copy`/`symlink`) et le tri vers un dossier (`POST /api/cull/apply`, actions `copy_keeps` / `move_rejects`) écrivent dans un `target_dir`. Il doit se résoudre sous une racine autorisée, sinon la requête est refusée avant que le moindre fichier ne soit touché.

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `allowed_target_dirs` | *(clé absente)* | Racines supplémentaires où l'export et le tri vers un dossier peuvent écrire, en plus des dossiers de scan (toujours autorisés) |
| `cull.allow_trash` | `false` | Autorise l'action `trash_rejects` du tri vers un dossier (corbeille du système via `send2trash`, récupérable) ; désactivé, l'option est masquée |

**Ensembles multi-vues et actions groupées.** Avec `hide_brackets` / `hide_panoramas` activés (par défaut, voir [Visionneuse web — Filtres par défaut](VIEWER.md#filtres-par-défaut)), une sélection ne contient que la vue représentative de chaque ensemble, si bien que les actions groupées n'agissent que sur cette vue. L'option `include_sequence_siblings` du tri vers un dossier étend une photo retenue à tout son ensemble ; voir [Visionneuse web — Trier vers un dossier § Ensembles multi-vues](VIEWER.md#trier-vers-un-dossier).

**Ordre de résolution.** Les racines autorisées sont `allowed_target_dirs`, puis chaque dossier de scan (par utilisateur, partagé, et cibles de `path_mapping`). Exporter dans votre arborescence de photos n'exige aucune configuration ; une destination extérieure demande une entrée ici. Les liens symboliques et `..` sont résolus avant la vérification (`os.path.realpath()`), donc un lien pointant hors d'une racine autorisée est refusé.

**Refus par défaut, par conception.** Sans `allowed_target_dirs` ni dossier de scan, l'export copie/lien symbolique/déplacement est refusé.

**Dépannage de « accès refusé ».** L'interface web affiche une notification générique « Accès refusé ». Pour en voir la raison, ouvrez l'onglet Réseau du navigateur, trouvez la requête `/api/cull/apply` ou `/api/albums/{id}/export` qui a échoué et lisez le champ `detail` : soit cette liste d'autorisation, soit une session d'édition expirée. Une vraie erreur de permission du système de fichiers est différente : la requête réussit, le nombre `errors` de la réponse est non nul, et le journal du serveur contient une trace par fichier. Voir [Déploiement — Sémantique des chemins en conteneur](DEPLOYMENT.md#sémantique-des-chemins-en-conteneur) pour le cas des conteneurs.

Voir [Visionneuse web — Trier vers un dossier](VIEWER.md#trier-vers-un-dossier) et [Visionneuse web — Export vers éditeur](VIEWER.md#export-vers-éditeur).

## Export social

Préréglages de recadrage pour les formats d'image des réseaux sociaux, cadrés sur le sujet (`GET /api/photo/social_crop`, réservé à l'édition). Chaque préréglage recadre l'original pleine résolution au plus grand rectangle de ce format, centré sur le sujet. Le sujet est le cadre du sujet BiRefNet (`photos.subject_bbox`), sinon l'union des cadres de visages, sinon le centre de l'image. Voir [Visionneuse web — Téléchargement](VIEWER.md#téléchargement).

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

Conditionné par `viewer.features.show_social_export` (par défaut `true`). Le cadre du sujet est écrit par la passe de saillance au moment du scan et par `--recompute-saliency` ; les photos plus anciennes utilisent le recadrage sur le visage ou le centre.

## Export de portfolio

Exporte un album sous forme de galerie HTML statique autonome que vous pouvez téléverser sur n'importe quel hébergeur web (`POST /api/albums/{album_id}/export-portfolio`, réservé à l'édition).

- Le dossier de sortie contient `index.html` (grille de miniatures et visionneuse, sans référence externe ni CDN), un dossier `assets/` de JPEG nommés séquentiellement (sans chemins de la bibliothèque) et un `manifest.json`.
- Chaque photo utilise l'**original**, réduit à `max_edge`, ou la miniature stockée de 640 px quand l'original est inaccessible. Le manifeste enregistre lequel.
- Un nouvel export ne réécrit que ses propres fichiers.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `max_photos` | `500` | Les albums plus grands sont refusés (l'export s'exécute de façon synchrone) |
| `max_edge` | `2048` | Plafond du grand côté (px) pour les originaux exportés ; la requête peut le remplacer (borné 256–8000) |
| `jpeg_quality` | `88` | Qualité JPEG des images exportées |

Le `target_dir` utilise la même liste d'autorisation que les autres exports (`viewer.export.allowed_target_dirs` plus les dossiers de scan — voir [Destinations d'export et de tri](#destinations-dexport-et-de-tri)). Conditionné par `viewer.features.show_portfolio_export` (par défaut `true`). Voir [Visionneuse web — Export de portfolio](VIEWER.md#export-de-portfolio).

## Point d'accès agent (MCP)

Expose les outils décrits dans [Agents IA (MCP)](AGENTS.md) sur `POST /mcp` : lecture, pilotage de votre onglet ouvert et, selon le niveau du jeton, modification des notes, tags et albums, tri et suppression. Activé par défaut.

Sur une installation ouverte (sans `viewer.password`) :
- `/mcp` ne sert qu'une clé anonyme en lecture seule, qui ne montre rien que l'`/api` ouverte ne montre déjà.
- Un nouveau jeton est `readonly`, sauf si `viewer.trusted_local_editing` est activé ou si la session est connectée avec `viewer.edition_password` : l'un comme l'autre peut créer un jeton Édition complète, qui ne modifie que pour les requêtes de la même machine.
- Les jetons ne peuvent être créés, listés et révoqués que depuis l'ordinateur qui exécute Facet (ou dans une session d'édition lorsque `viewer.edition_password` est défini).

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| Clé | Défaut | Description |
|-----|--------|-------------|
| `enabled` | `true` | Interrupteur général de `/mcp` et `/api/mcp/*` |
| `bridge` | `true` | Autorise le pont avec l'onglet du navigateur (`/api/mcp/bridge`) pour que les outils `ui_*` atteignent un onglet ; nécessite un seul worker |
| `max_rows` | `100` | Nombre maximal de lignes dans un résultat d'outil (1 à 500) ; des lignes en trop positionnent `truncated: true` |
| `max_bytes` | `60000` | Taille sérialisée maximale d'un résultat d'outil en octets (4000 à 500000). |
| `max_image_bytes` | `262144` | Taille maximale d'image de `get_thumbnail` ou `contact_sheet` (32768 à 2097152) ; non comptée dans `max_bytes` |
| `call_timeout_s` | `30` | Délai d'un appel d'outil en secondes (1 à 300), aussi l'attente de `ui_*` pour l'onglet (`tab_timeout`) |
| `semantic_timeout_s` | `120` | Délai de `semantic_search` en secondes (1 à 300) ; l'outil charge le modèle d'embeddings et demande donc plus de temps. |
| `rate_per_min` | `120` | Appels d'outils par minute et par jeton (minimum 1). |
| `write_rate_per_min` | `30` | Appels d'écriture par minute et par jeton (minimum 1), séparé pour que les lectures ne puissent pas affamer les écritures |
| `tool_profile` | `"full"` | `"full"` liste tous les outils autorisés ; `"core"` liste un jeu de 11 outils pour les petits modèles |
| `allow_destructive` | `false` | Autorise `delete_photos`, `move_rejects`/`trash_rejects` de `cull_apply`, et `assign_faces` avec `allow_reassign` |
| `inpage_tools` | `true` | Laisse un onglet connecté appeler les outils du serveur depuis la page (`GET /api/mcp/inpage_tools`, `POST /api/mcp/call`) |
| `allowed_origins` | `[]` | Origines de navigateur supplémentaires (par ex. `["https://photos.example.com"]`) autorisées à ouvrir le pont d'onglet derrière un proxy qui réécrit `Host` ; pas la clé CORS `viewer.allowed_origins` |

Remarques :
- **`enabled: false`** désactive `/mcp` et `/api/mcp/*` (le pont se ferme avec le code 4404). **`bridge: false`** refuse le pont et fait renvoyer une erreur aux outils `ui_*`.
- **`write_rate_per_min`** couvre les outils d'écriture, y compris la simulation de `cull_apply` et `delete_photos` ; voir [Agents IA](AGENTS.md#modifier-la-bibliothèque).
- **`"core"`** liste `status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`. Seul le listage change ; les autres outils restent appelables si le niveau de la clé le permet. Toute autre valeur équivaut à `"full"`. Voir [Agents IA](AGENTS.md#niveaux-dautorisation).
- **`allow_destructive: false`** masque `delete_photos` ; les deux autres répondent `feature_disabled` en nommant cette clé. Voir [Agents IA](AGENTS.md#actions-destructives-aperçu-puis-confirmation).
- **`inpage_tools`** exécute les outils comme la session, à son niveau actuel. Désactivé, `features.mcp_inpage` vaut false dans `/api/auth/status`. Voir [Agents IA](AGENTS.md#webmcp-dans-la-page-agents-du-navigateur).
- Les nombres hors plage sont ramenés dans la plage ; une valeur du mauvais type utilise la valeur par défaut. Les changements s'appliquent au rechargement de la configuration, sans redémarrage.

## Cadre photo / Kiosque

Sert les meilleures photos sélectionnées à des appareils kiosque sans connexion : cadres photo connectés, tableaux de bord Home Assistant, écrans de type ImmichFrame / Immich-Kiosk. Trois points d'accès utilisent un jeton statique : `GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`. Une liste `tokens` vide désactive la fonctionnalité (les points d'accès répondent 404). Les réponses ne contiennent jamais de chemins de fichiers ; les photos sont adressées par un identifiant signé.

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

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `tokens` | `[]` | Jetons de cadre, une longue chaîne aléatoire par appareil ; en retirer un le révoque. **Vide = fonctionnalité désactivée.** |
| `count` | `20` | Nombre de photos renvoyées par défaut par `/api/frame/photos` |
| `max_count` | `100` | Plafond strict du paramètre de requête `count` |
| `min_aggregate` | `7.0` | Score agrégé minimal pour qu'une photo soit sélectionnée |
| `max_edge` | `1920` | Plafond du grand côté (px) des JPEG servis ; le paramètre de requête `max_edge` ne peut que l'abaisser |
| `favorites_only` | `false` | Si `true`, seules les photos favorites sont sélectionnées |
| `categories` | `[]` | Liste blanche de noms de catégories (vide = toutes) |

Générez un jeton avec `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

La sélection ignore les photos rejetées, indésirables (`junk_kind`) et avec clignement, applique les filtres de score, de favoris et de catégorie, puis tire un échantillon aléatoire pondéré par le score. Voir [Visionneuse web — Cadre photo / Kiosque](VIEWER.md#cadre-photo--kiosque) pour la recette Home Assistant.

> **Avertissement :** Un jeton de cadre n'est pas une connexion utilisateur. En [mode multi-utilisateur](#utilisateurs) il ignore les `directories` privés de chaque utilisateur et peut lire les photos de tous, pas seulement `shared_directories`. N'émettez des jetons de cadre que là où tous les utilisateurs l'acceptent.

## Envoi automatique depuis le téléphone

Un point d'accès **WebDAV** minimal sur `/dav` permet aux applications de téléversement automatique du téléphone (PhotoSync et similaires) de pousser des photos dans un **dossier d'arrivée**, que `facet.py --watch` analyse ensuite. L'accès utilise HTTP Basic avec des **identifiants d'appareil partagés** (`username` / `password`), pas un compte utilisateur.

- `/dav` renvoie **404** tant que `username`, `password` et `inbox_dir` ne sont pas tous définis.
- Chaque opération reste dans `inbox_dir` ; la traversée de chemin, les chemins absolus et les évasions par lien symbolique sont refusés.
- Les téléversements sont écrits de façon atomique et plafonnés à `max_file_mb`.

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

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `username` | `""` | Nom d'utilisateur HTTP Basic (identifiant d'appareil partagé). **Vide = fonctionnalité désactivée.** |
| `password` | `""` | Mot de passe HTTP Basic ; utilisez une longue chaîne aléatoire. **Vide = fonctionnalité désactivée.** |
| `inbox_dir` | `""` | Chemin absolu du dossier d'arrivée, créé à la demande. **Vide = fonctionnalité désactivée.** |
| `max_file_mb` | `500` | Taille maximale par fichier (Mo) ; un téléversement plus grand est interrompu et ne laisse aucun fichier partiel |

Pointez `inbox_dir` vers un dossier scanné (ou un sous-dossier) pour que `facet.py --watch` analyse les téléversements à leur arrivée.

Méthodes prises en charge : `OPTIONS`, `PROPFIND` (profondeur 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (pas de `LOCK`/`UNLOCK`). Un en-tête `Authorization` absent ou erroné reçoit `WWW-Authenticate: Basic realm="Facet upload"`. Voir [Visionneuse web — Envoi automatique depuis le téléphone](VIEWER.md#envoi-automatique-depuis-le-téléphone) pour la recette PhotoSync et un test rapide avec `curl`.

## Nettoyage des indésirables

Signale les « indésirables » qui ne sont pas des photos (captures d'écran, documents numérisés, reçus, mèmes, diapositives de présentation) à partir de l'**embedding d'image stocké**, sans décoder l'image. Chaque type a une liste d'invites textuelles, et l'invite la plus proche compte pour ce type.

- Une photo n'est signalée que lorsque son meilleur type d'indésirable atteint `min_confidence` **et** dépasse de `min_margin` la meilleure invite `not_junk`.
- Sinon elle est stockée comme `not_junk` (évaluée, propre). `NULL` signifie pas encore évaluée.
- `--detect-junk` n'étiquette que les photos `NULL` (il s'exécute aussi à la fin d'un scan) ; `--recompute-junk` revérifie toute la bibliothèque.
- Les résultats vont dans `photos.junk_kind`, examinés dans la file **Nettoyage** de la visionneuse ([VIEWER.md](VIEWER.md#nettoyage-des-indésirables)).

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
| `prompt_template` | `"{desc}"` | Chaîne de format appliquée à chaque invite (`{desc}` = l'invite) ; inchangée par défaut |
| `pooling` | `"max"` | Combine les scores d'invites par type via `max` (meilleure invite seule) ou `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Score minimal pour le meilleur type d'indésirable (par backend ; les scores CLIP/`open_clip` sont plus bas que SigLIP/`transformers`) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Écart minimal que le meilleur type d'indésirable doit creuser sur le meilleur prompt contrastif `not_junk` avant que la photo soit signalée |
| `kinds` | screenshot/document/receipt/meme/slide | `{kind: [synonymes d'invite]}` ; ajoutez, retirez ou renommez librement des types |
| `not_junk_prompts` | 8 invites de photographie | Invites décrivant de vraies photographies, qui gardent les vraies photos hors de la file |

## Critique IA

Réglages d'invite pour la critique VLM (profils 16gb/24gb). La critique fournit au VLM la décomposition du score, les pénalités et l'EXIF, et affiche sa réponse sous Observation / Évaluation / Suggestions.

- L'évaluation couvre la composition, la couleur et la lumière, la mise au point/profondeur de champ et l'exécution technique, et le sujet et le moment, vérifiés par rapport aux métriques.
- Elle est mise en cache par photo (`photos.vlm_critique`, traductions dans `vlm_critique_translated`) ; `refresh` la régénère.
- Elle s'exécute sur la miniature stockée, donc les fichiers RAW fonctionnent.

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

Voir [Visionneuse web — Critique IA](VIEWER.md#critique-ia).

## Backend VLM

Choisit où s'exécute le modèle vision-langage de légendes/tags. `local` (par défaut) utilise le modèle Qwen intégré des profils 16gb/24gb. Les deux backends distants utilisent un serveur externe : les légendes et le tagging VLM fonctionnent donc aussi sur les **profils legacy/8gb qui n'ont pas de VLM local**.

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
| `type` | `"local"` | `local` (Qwen intégré), `ollama` (API REST Ollama) ou `openai_compatible` (LM Studio, vLLM, OpenRouter, …) |
| `ollama.base_url` | `"http://localhost:11434"` | URL de base du serveur Ollama (les images vont à `POST /api/generate`) |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag de modèle Ollama (doit être un modèle vision déjà récupéré sur le serveur) |
| `ollama.timeout_seconds` | `120` | Délai d'expiration par requête pour les appels Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL de base **y compris le suffixe `/v1`** (les requêtes vont à `{base_url}/chat/completions`, l'image sous forme d'URI de données `image_url`) |
| `openai_compatible.api_key` | `""` | Envoyé comme `Authorization: Bearer <key>` ; laissez vide pour les serveurs locaux sans clé |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nom de modèle transmis à l'endpoint |
| `openai_compatible.timeout_seconds` | `120` | Délai d'expiration par requête pour les appels compatibles OpenAI |

Le backend pilote les légendes (`--generate-captions` et `/api/caption`), la critique VLM (`/api/critique?mode=vlm`), le re-tagging VLM (`--recompute-tags-vlm`) et le départage des moments narratifs. Une requête distante en échec ne fait échouer que cette photo (journalisé, ni tags ni légende). Le tagging pendant le scan utilise toujours le tagueur du profil ; lancez `--recompute-tags-vlm` pour appliquer un backend distant à une bibliothèque existante.

## Attributs de distorsion

Étiquettes de distorsion indicatives. `--recompute-distortions` compare l'embedding CLIP/SigLIP stocké de chaque photo avec des invites de défauts courants (flou de bougé, dominante de couleur, accentuation excessive, …) et stocke les plus probables. Elles n'affectent jamais le score ; elles apparaissent comme pastilles d'avertissement dans la boîte de dialogue de critique.

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
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Température du softmax sur les scores d'invites, par backend d'embedding (les échelles diffèrent, comme dans `narrative_moments`) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilité minimale pour qu'une étiquette de distorsion soit conservée |
| `vocabulary` | `{}` | Surcharge facultative des invites intégrées (`{attribute: [synonymes d'invite]}`) ; vide = valeurs par défaut |

## Teint

Vérification indicative de la teinte de peau des portraits. `--recompute-skin-tone` mesure la couleur des joues sur les miniatures de visages stockées et signale les portraits dont la peau dérive vers le vert, le magenta, le bleu ou le jaune. Elle n'affecte jamais le score ; le résultat apparaît comme une note dans la boîte de dialogue de critique.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `cast_delta_threshold` | `12.0` | Distance CIEDE2000 minimale aux teintes de peau naturelles avant qu'une dominante de couleur soit signalée |

## Synchronisation Immich

Synchronisation à sens unique des notes en étoiles et des favoris de Facet vers un serveur [Immich](https://immich.app/) via son API REST. Les ressources sont appariées par `originalPath` au moyen de `path_map`. Lancez `--immich-sync` (testez d'abord avec `--immich-test`) ; voir [Commandes — Synchronisation Immich](COMMANDS.md#synchronisation-immich).

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
| `owner_id` | `""` | ID de propriétaire exact facultatif ; les ressources sans lui ou appartenant à quelqu'un d'autre sont ignorées |
| `library_id` | `""` | ID de bibliothèque exact facultatif ; vide = pas de filtre de bibliothèque |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Réécritures de préfixe des chemins Facet vers l'`originalPath` d'Immich ; le premier `facet_prefix` qui correspond l'emporte |
| `push.ratings` | `true` | Envoie les notes en étoiles (seules 1–5 sont écrites, jamais 0/−1) |
| `push.favorites` | `true` | Pousse l'indicateur de favori |
| `push.rejected` | `false` | Pousse `rating: -1` pour les photos rejetées dans Facet. Nécessite `push.ratings` |
| `push.top_picks_album` | `""` | Nom d'album Immich facultatif qui rassemble les photos poussées au-dessus du seuil de note. Vide = aucun album |
| `push.top_picks_min_rating` | `4` | Note en étoiles minimale pour qu'une photo soit ajoutée à `top_picks_album` |
| `webhook.token_env` | `""` | Variable d'environnement contenant le secret partagé du webhook entrant ; vide ou non définie désactive le webhook |
| `webhook.header` | `"x-facet-token"` | En-tête dans lequel le workflow Immich envoie le jeton |
| `webhook.max_pending` | `500` | Plafond de la liste des chemins mémorisés mais non notés, rapportée par la prochaine synchronisation |
| `timeout_seconds` | `30` | Délai d'expiration REST par requête |

`--immich-sync` prend en charge `--dry-run` (apparie toutes les ressources, n'écrit rien) et `--user` (envoie les notes `user_preferences` de cet utilisateur en mode multi-utilisateur). Facet n'utilise que l'API REST et ne touche jamais à la base de données d'Immich.

## Frise chronologique

Réglages pour la vue chronologique :

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `photos_per_group` | `30` | Photos chargées par groupe de date ; plus élevé montre plus de photos par date mais alourdit les pages |

## Carte

Réglages pour la vue carte interactive :

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `cluster_zoom_threshold` | `10` | Niveau de zoom où les marqueurs individuels remplacent les regroupements ; 1 (monde) à 18 (rue) |

## Traduction

Réglages pour la traduction des légendes IA via MarianMT :

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Réglage | Défaut | Description |
|---------|--------|-------------|
| `target_language` | `"fr"` | Langue cible de `--translate-captions` : `fr`, `de`, `es`, `it`, `pt` (portugais brésilien) |

La traduction utilise les modèles Helsinki-NLP MarianMT sur le CPU ; aucun GPU n'est nécessaire.

## CLIP esthétique (R2)

Un score esthétique supplémentaire calculé à partir des embeddings CLIP/SigLIP en cache et d'invites textuelles. Utilisez `scripts/benchmark_aesthetic.py` pour mesurer l'effet d'un changement d'invite sur AVA.

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

Les tableaux vides utilisent les valeurs par défaut de `analyzers/aesthetic_clip.py`. Relancez le benchmark AVA avant de les modifier : les valeurs par défaut obtiennent un SRCC d'environ 0,52 sur `ava_test/`, et des modifications le font facilement tomber à ~0,30.

## Ajout de modèles VLM tagger / critique alternatifs (R3)

Le `tagging_model` de chaque profil (par ex. `qwen3.5-2b`) désigne une entrée de modèle dans la même section `models`. Pour essayer un autre VLM (Pixtral-12B, InternVL-2.5, etc.) :

1. Ajoutez une entrée de modèle sous `models` :
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Pointez un profil dessus :
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Exécutez `python facet.py --recompute-tags-vlm` pour ré-étiqueter.

Aucun changement de code nécessaire. Vérifiez ~30 photos côte à côte avant d'en faire la valeur par défaut.

## Secret du serveur

Le secret qui signe les jetons de session et les liens de cadre photo n'est **pas** une clé de ce fichier. Il réside dans `.facet_secret`, à côté de `scoring_config.json` (mode `0600`, ignoré par git), et est généré au premier lancement.

- Surcharge : la variable d'environnement `FACET_JWT_SECRET`.
- Rotation : `python database.py --rotate-secret`.

Un `share_secret` d'une ancienne installation est déplacé dans ce fichier au prochain démarrage et retiré de `scoring_config.json`. Voir [Stockage et rotation du secret](DEPLOYMENT.md#stockage-et-rotation-du-secret).
