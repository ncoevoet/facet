# Intégration Immich

> 🌐 [English](../IMMICH.md) · **Français** · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md)

Facet et [Immich](https://immich.app/) remplissent des rôles différents sur les mêmes photos. Immich est la bibliothèque : il ingère, sauvegarde et sert les photos à votre téléphone. Facet est le jugement : il note, classe et trie les photos. Cette page relie les deux pour que les verdicts de Facet apparaissent sous forme de notes et de favoris dans Immich, et pour qu'un envoi vers Immich signale à Facet qu'un nouveau travail l'attend.

Le lien est exclusivement REST dans les deux sens. Facet ne touche jamais à la base de données d'Immich, et Immich ne touche jamais à celle de Facet.

**Facet exige Immich ≥ 3.0.** Les serveurs plus anciens rejettent la sémantique de notation dont Facet dépend : `null` pour effacer une note et `-1` pour en marquer une comme rejetée. Sur un serveur 2.x, l'effacement est refusé et des notes obsolètes restent bloquées indéfiniment sur vos ressources.

---

## Table des matières

- [Comment les deux voient le même fichier](#comment-les-deux-voient-le-même-fichier)
- [Étape 1 — partager la bibliothèque avec Immich](#étape-1--partager-la-bibliothèque-avec-immich)
- [Étape 2 — créer une clé API](#étape-2--créer-une-clé-api)
- [Étape 3 — mettre en correspondance les chemins](#étape-3--mettre-en-correspondance-les-chemins)
- [Étape 4 — tester, puis pousser](#étape-4--tester-puis-pousser)
- [Pousser les rejets](#pousser-les-rejets)
- [Le webhook entrant](#le-webhook-entrant)
- [Référence de configuration](#référence-de-configuration)
- [Dépannage](#dépannage)

---

## Comment les deux voient le même fichier

Tout ce qui suit repose sur une seule idée : **la même photo sur le disque, vue depuis deux conteneurs**.

Facet connaît une photo par son chemin absolu sur la machine qui exécute l'analyse — `/mnt/photos/2026/07/IMG_1234.jpg`. Immich connaît ce même fichier par son propre `originalPath`, c'est-à-dire ce à quoi ce fichier ressemble *depuis l'intérieur du conteneur Immich* — souvent `/usr/src/app/upload/…` pour les ressources envoyées, ou le point de montage que vous avez donné à une bibliothèque externe.

Aucun des deux côtés ne peut deviner la vue de l'autre, vous indiquez donc une bonne fois à Facet la réécriture de préfixe (`immich.path_map`), et toute résolution dans les deux sens y passe. Une fois que c'est correct, le reste est mécanique ; si c'est incorrect, tout rapporte silencieusement « unmatched » — voir [Dépannage](#dépannage).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La correspondance est utilisée dans les deux sens : en sortie (`--immich-sync` traduit un chemin Facet pour trouver la ressource) et en entrée (le webhook traduit l'`originalPath` d'Immich pour retrouver la photo).

## Étape 1 — partager la bibliothèque avec Immich

La configuration la plus propre est une **bibliothèque externe** : Immich lit les photos là où elles se trouvent déjà, plutôt que d'en posséder une seconde copie. Facet analyse le même répertoire de son côté.

1. Dans Immich, allez dans **Administration → External Libraries → Create Library**, choisissez le propriétaire, et ajoutez un chemin d'import pointant vers le répertoire tel que le conteneur Immich le voit.
2. Assurez-vous que ce répertoire est monté (bind mount) en lecture seule dans le conteneur Immich. Dans `docker-compose.yml` :

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Analysez la bibliothèque depuis l'interface d'Immich (**Scan All Libraries**), et analysez le même répertoire avec Facet :

   ```bash
   python facet.py /mnt/photos
   ```

Les deux outils détiennent désormais une ligne par fichier. Rien n'est dupliqué sur le disque.

Si à la place vous envoyez normalement vers Immich (sauvegarde automatique mobile, l'uploader web) et que vous pointez Facet vers le propre répertoire d'upload d'Immich, l'intégration fonctionne exactement de la même façon — seuls les préfixes diffèrent. Dans ce cas, c'est Immich qui possède l'organisation des fichiers, donc relancez l'analyse Facet après chaque envoi (ou utilisez `--watch`).

## Étape 2 — créer une clé API

Dans Immich : **cliquez sur votre avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 permet de restreindre la portée d'une clé plutôt que de tout lui accorder. Facet a besoin d'exactement six portées :

| Portée | Ce que Facet en fait |
|-------|-------------------------|
| `server.about` | Contrôle de connectivité/authentification pour `--immich-test` |
| `asset.read` | Résoudre les ressources par `originalPath` |
| `asset.update` | Écrire `rating` et `isFavorite` |
| `album.read` | Trouver un album de coups de cœur existant par son nom |
| `album.create` | Créer l'album de coups de cœur la première fois |
| `albumAsset.create` | Ajouter des photos à l'album de coups de cœur |

Omettez les trois derniers si vous laissez `push.top_picks_album` vide — Facet ne touche aux albums que lorsque ce nom est défini.

La clé est envoyée en en-tête `x-api-key` à chaque requête. Placez-la dans `scoring_config.json` :

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Une remarque sur `PUT /api/assets`.** Facet écrit les notes avec `PUT /api/assets`, que le document OpenAPI d'Immich marque comme *deprecated*. Les alias `PATCH` de remplacement sont annoncés mais **absents de la spécification publiée** ; il n'y a donc rien vers quoi migrer pour l'instant — `PUT` reste le seul point d'accès qui existe réellement, et Facet continue de l'utiliser. Chaque route Immich que Facet touche vit dans `ImmichClient` (`sync/immich.py`), donc le jour où les routes `PATCH` sortiront, le changement tiendra dans une seule classe.

## Étape 3 — mettre en correspondance les chemins

Ajoutez une paire par racine que vous partagez. La première paire dont le `facet_prefix` correspond à une photo l'emporte :

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Deux racines, deux paires :

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

Laissez l'exemple fourni par défaut (`{"facet_prefix": "", "immich_prefix": ""}`) tel quel et les chemins passent inchangés — ce n'est correct que lorsque Facet et Immich voient réellement des chemins absolus identiques, ce qui est le cas si vous exécutez Facet dans l'espace de noms du conteneur Immich, et presque jamais autrement.

Pour lire la vraie valeur, ouvrez n'importe quelle photo dans Immich, appuyez sur `i` pour afficher le panneau d'informations, et comparez le chemin de fichier qui y est indiqué avec le chemin que Facet rapporte pour la même photo.

## Étape 4 — tester, puis pousser

```bash
# Connectivité + authentification uniquement. Aucune écriture.
python facet.py --immich-test

# Résout chaque ressource et indique ce qui CHANGERAIT. Toujours aucune écriture.
python facet.py --immich-sync --dry-run

# Pour de vrai.
python facet.py --immich-sync
```

La synchronisation rapporte `matched` / `unmatched` / `updated` / `skipped (unrated)` / albums créés. Un premier lancement avec un nombre élevé de `unmatched` signifie presque toujours que la correspondance des chemins est incorrecte — voir [Dépannage](#dépannage).

Ce qui est poussé :

- **Notes en étoiles 1–5** → le `rating` d'Immich. Une photo que vous n'avez jamais notée ne pousse rien.
- **Favoris** → l'`isFavorite` d'Immich.
- **Effacements.** Si vous avez noté une photo 5, synchronisé, puis réinitialisé sa note, la synchronisation suivante envoie `rating: null` pour qu'Immich l'oublie aussi. Facet se souvient de ce qu'il a poussé en dernier (dans la table annexe `stats_cache`) précisément pour que cette transition ne soit pas perdue. C'est `null`, jamais `0` — Immich v3 rejette purement et simplement `0`, et un seul lot rejeté interrompt toute la synchronisation.
- **Un album de coups de cœur facultatif**, rempli à partir de `push.top_picks_min_rating`, lorsque `push.top_picks_album` en nomme un.

En mode multi-utilisateurs, `--immich-sync --user alice` pousse les notes `user_preferences` d'Alice au lieu des colonnes globales, et suit son état dans sa propre portée.

## Pousser les rejets

Désactivé par défaut. Activez-le et une photo que vous avez rejetée dans la chambre noire de Facet reçoit le propre marqueur de rejet d'Immich :

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

Avec `push.rejected` activé :

- Une photo rejetée pousse `rating: -1`, la valeur qu'Immich v3 utilise pour « rejeté ».
- **Le rejet l'emporte sur les étoiles.** Une photo à 5 étoiles mais rejetée pousse `-1`, pas `5` — vous l'avez jetée, et c'est ce fait qui mérite d'être reflété.
- **Annuler le rejet l'efface.** Une photo qui a poussé `-1` et dont le rejet est ensuite annulé pousse à la place sa note en étoiles actuelle, ou `rating: null` si elle n'en a aucune. Même mécanisme d'état suivi que pour tout autre effacement.
- Une photo rejetée ne rejoint jamais l'album de coups de cœur.
- `push.ratings: false` le supprime. `-1` est une écriture de note, donc une configuration qui a désactivé l'envoi des notes n'en voit pas une se réintroduire en douce.

Laissez-le désactivé si d'autres personnes (ou votre téléphone) consultent la bibliothèque Immich : un `-1` y est visible, et « rejetée dans Facet » est un jugement de travail que vous ne voulez peut-être pas diffuser.

## Le webhook entrant

Tout ce qui précède va de Facet vers Immich. Le webhook, lui, est le sens inverse : Immich indique à Facet qu'une ressource vient de changer, et Facet répond immédiatement avec ce qu'il en sait.

**Il est désactivé par défaut et ne déclenche jamais d'analyse.** Un webhook est un appel non authentifié par session en provenance d'un autre démon ; laisser un tel appel déclencher du travail GPU donnerait à quiconque possède le jeton un moyen de mettre votre machine à genoux. Voici ce qu'il fait à la place :

- **Photo connue et notée** → sa note/son favori est repoussé immédiatement vers Immich, sur-le-champ, sous forme de mise à jour d'une seule ressource. C'est ce qui referme la boucle après une analyse : notez une photo, envoyez-la, et la note atterrit dans Immich sans attendre le prochain `--immich-sync`.
- **Photo inconnue ou pas encore notée** → le chemin est mémorisé dans une liste d'attente bornée et dédupliquée, et le prochain `--immich-sync` la journalise. Rien n'est analysé.

### Activer

Le jeton est un secret partagé, il vit donc dans l'environnement, jamais dans `scoring_config.json` (ce fichier est réécrit sur place par plusieurs points d'accès et lisible par tout le monde sur la plupart des installations). La configuration nomme la *variable* ; la variable détient la *valeur*.

1. Générez un jeton et exportez-le partout où la visionneuse démarre — votre unité systemd, `docker-compose.yml`, ou votre profil de shell :

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Nommez cette variable dans `scoring_config.json` :

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Redémarrez la visionneuse (`python viewer.py`).

Un `token_env` vide, ou une variable non définie ou vide, désactive entièrement le point d'accès — il renvoie **404**, exactement comme `frame.tokens` et `upload.username`. Il n'existe aucun état intermédiaire.

### Diriger Immich vers le webhook

Dans Immich ≥ 3.0 : **Administration → Workflows → Create Workflow**.

1. **Trigger** — choisissez l'événement de ressource que vous voulez répercuter. `Asset uploaded` est celui qui est utile ; ajoutez `Asset updated` si vous voulez aussi que les modifications redéclenchent l'événement.
2. **Action** — choisissez **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, avec une adresse que le conteneur Immich peut réellement atteindre. Si les deux tournent dans Docker sur un même hôte, c'est le nom du service (`http://facet:5000/…`), pas `localhost`.
4. **Header** — nom `x-facet-token`, valeur le jeton que vous avez généré. Le nom doit correspondre à `webhook.header` ; renommez les deux ensemble si votre installation a besoin d'un nom différent. `Authorization: Bearer <token>` est aussi accepté, pour les proxys qui n'offrent que cela.
5. Enregistrez, puis envoyez une photo pour confirmer.

### Ce que renvoie le point d'accès

| Statut | Signification |
|--------|---------|
| `202` | Corps compris. Le récapitulatif JSON compte les ressources de *cette* livraison : `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON valide, mais aucune ressource reconnue par Facet. Journalisé, pas une erreur — la forme du payload appartient à Immich, qui peut la faire évoluer. |
| `400` | Le corps n'était pas du JSON du tout. |
| `401` | Aucun jeton dans la requête. |
| `403` | Mauvais jeton. |
| `404` | La fonctionnalité est désactivée (aucun jeton configuré). |

Facet lit `originalPath` dans le payload et se montre délibérément permissif sur son emplacement — un objet ressource nu, `{"asset": {…}}`, une liste, ou n'importe lequel de ces cas imbriqué sous `data` / `items` / `assets` fonctionnent tous. Si le payload porte l'`id` de la ressource, Facet l'utilise et s'épargne un aller-retour de résolution.

Les chemins en attente sont rapportés par la synchronisation suivante :

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Analysez ces photos (`python facet.py /mnt/photos`) et elles disparaissent de la liste à la synchronisation suivante. La liste est plafonnée à `max_pending` entrées, les plus anciennes étant supprimées en premier, si bien qu'un Immich bavard ne peut jamais la faire grossir sans limite.

### Notes de sécurité

- Le jeton est comparé à temps constant. Un jeton erroné produit un simple `403`, sans aucun indice temporel.
- Servez la visionneuse en HTTPS si Immich l'atteint via un chemin moins sûr qu'un réseau bridge privé — le jeton voyage dans un en-tête à chaque envoi.
- Effectuez la rotation en changeant ensemble la variable d'environnement et l'en-tête du workflow Immich, puis en redémarrant la visionneuse.
- Le webhook lit les colonnes de note globales, donc en mode multi-utilisateurs il reflète la note partagée/globale, pas la surcouche d'un utilisateur en particulier. Si ce sont des notes par utilisateur que vous voulez dans Immich, laissez le webhook désactivé et utilisez `--immich-sync --user <nom>` sur une planification récurrente.

## Référence de configuration

Le bloc `immich` complet, avec les valeurs par défaut fournies :

```json
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
```

| Clé | Défaut | Signification |
|-----|---------|---------|
| `url` | `""` | URL de base d'Immich, `http` ou `https`. Une barre oblique finale est retirée. |
| `api_key` | `""` | Clé API, envoyée comme `x-api-key`. Vide interrompt toute synchronisation avec une erreur explicite. |
| `path_map` | une paire vide | Réécritures de préfixe entre les chemins Facet et les valeurs `originalPath` d'Immich. La première correspondance l'emporte ; utilisé dans les deux sens. |
| `push.ratings` | `true` | Pousse les notes en étoiles 1–5 (et leurs effacements). |
| `push.favorites` | `true` | Pousse `isFavorite` (et son effacement). |
| `push.rejected` | `false` | Pousse `rating: -1` pour les photos rejetées dans Facet. Nécessite `push.ratings`. |
| `push.top_picks_album` | `""` | Nom de l'album à remplir. Vide signifie que Facet ne touche jamais aux albums. |
| `push.top_picks_min_rating` | `4` | Note en étoiles minimale pour cet album. |
| `webhook.token_env` | `""` | Nom de la variable d'environnement contenant le secret du webhook. Vide ⇒ le point d'accès renvoie 404. |
| `webhook.header` | `"x-facet-token"` | En-tête dans lequel Immich envoie le jeton. |
| `webhook.max_pending` | `500` | Plafond de la liste des chemins mémorisés mais non notés. |
| `timeout_seconds` | `30` | Délai d'expiration HTTP par requête. |

## Dépannage

### Tout revient en `unmatched`

La correspondance des chemins est incorrecte — c'est de loin la panne la plus fréquente.

1. Ouvrez une photo dans Immich et appuyez sur `i`. Notez le chemin dans le panneau d'informations.
2. Retrouvez le chemin de cette même photo dans Facet (le panneau de détail de la galerie, ou `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Les deux partagent un *suffixe*. Ce qui diffère, c'est le préfixe, et ces deux préfixes sont exactement `facet_prefix` et `immich_prefix`.

Pièges courants :

- **Une barre oblique finale manquante.** `"/mnt/photos"` → `"/usr/src/app/external"` réécrit aussi `/mnt/photosXYZ/a.jpg`. Terminez toujours les deux préfixes par `/`.
- **Chemin hôte contre chemin conteneur.** Le chemin Immich est ce que voit le *conteneur*. `docker compose exec immich-server ls /usr/src/app/external` tranche la question.
- **Liens symboliques et montages liés (bind mounts).** Immich stocke le chemin qu'il a parcouru. Si votre bibliothèque est atteinte via un lien symbolique d'un seul côté, les chaînes diffèrent même si le fichier est unique.
- **Casse et Unicode.** La comparaison est exacte. Une bibliothèque sur un partage insensible à la casse peut contenir à la fois `/Photos/` et `/photos/` ; seule l'orthographe stockée correspond.
- **Immich n'a pas encore indexé le fichier.** Lancez **Scan All Libraries** et vérifiez que la ressource existe bien dans Immich avant d'incriminer la correspondance.

`--immich-sync --dry-run` nomme les 20 premiers chemins non appariés dans le journal ; cette liste identifie généralement le mauvais préfixe au premier coup d'œil.

### `--immich-test` échoue

- `Unsupported Immich URL scheme` — `url` a besoin de `http://` ou `https://`.
- `HTTP 401` — la clé API est incorrecte ou a été révoquée.
- `HTTP 403` — la clé est valide mais lui manque `server.about`. Recréez-la avec les six portées ci-dessus.
- Connexion refusée / délai dépassé — le port est incorrect, ou Facet ne peut pas atteindre le conteneur. Testez avec `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` depuis la machine qui exécute Facet.

### Le webhook renvoie 404

La fonctionnalité est désactivée. Soit `webhook.token_env` est vide, soit la variable qu'il nomme est non définie ou vide *dans l'environnement propre de la visionneuse*. L'exporter dans votre shell interactif ne change rien pour une visionneuse gérée par systemd ou Docker — définissez-la dans le fichier d'unité ou le fichier compose, puis redémarrez.

### Le webhook renvoie 401 ou 403

`401` signifie qu'aucun jeton n'est arrivé : le nom d'en-tête envoyé par Immich ne correspond pas à `webhook.header`. `403` signifie qu'un jeton est arrivé mais qu'il était erroné — comparez la valeur d'en-tête du workflow avec la variable d'environnement, caractère par caractère.

### Les notes se poussent, mais pas les effacements

Facet n'envoie un effacement que pour une photo qu'il a réellement poussée auparavant ; cette mémoire vit dans `stats_cache`, dans la base de données de Facet. Restaurer une base de données plus ancienne (ou repartir d'une base neuve) la fait perdre, et une note effacée pendant cet intervalle ne sera pas désactivée dans Immich. Re-notez puis re-effacez la photo, ou corrigez-la directement dans Immich.

### Les notes apparaissent sur les mauvaises photos

Deux fichiers avec le même `originalPath` ne peuvent pas se produire à l'intérieur d'Immich, mais deux racines *Facet* correspondant à un même préfixe Immich peuvent entrer en collision. Vérifiez que vos paires `path_map` ne se chevauchent pas : la première paire correspondante l'emporte, donc une paire large listée avant une paire étroite l'engloutit.

### `rating: 0 is not valid`

Le serveur Immich est antérieur à la version 3.0. Mettez-le à niveau — la sémantique d'effacement de Facet a besoin de `null`, et `push.rejected` a besoin de `-1` ; il n'existe aucun repli qui fonctionne sur la 2.x.

---

**Voir aussi :** [Commandes — Synchronisation Immich](COMMANDS.md#synchronisation-immich) · [Configuration](CONFIGURATION.md) · [Recettes d'interopérabilité avec les éditeurs](INTEROP.md) pour l'aller-retour XMP avec Lightroom, darktable et digiKam.
