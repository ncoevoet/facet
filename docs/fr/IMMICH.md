# Intégration Immich

> 🌐 [English](../IMMICH.md) · **Français** · [Deutsch](../de/IMMICH.md) · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md) · [简体中文](../zh/IMMICH.md)

[Immich](https://immich.app/) stocke, sauvegarde et sert vos photos. Facet les note, les classe et les trie. Cette page relie les deux :

- Les notes et favoris de Facet apparaissent dans Immich.
- Un envoi vers Immich signale à Facet qu'un nouveau travail l'attend.

Les deux sens n'utilisent que l'API REST d'Immich. Aucun des deux outils ne touche à la base de données de l'autre.

**Facet exige Immich ≥ 3.0.** Facet efface une note avec `null` et marque un rejet avec `-1`. Un serveur 2.x refuse l'effacement, si bien que des notes obsolètes restent sur vos ressources.

---

## Table des matières

- [Comment les deux voient le même fichier](#comment-les-deux-voient-le-même-fichier)
- [Étape 1 — partager la bibliothèque avec Immich](#étape-1--partager-la-bibliothèque-avec-immich)
- [Étape 2 — créer une clé API](#étape-2--créer-une-clé-api)
- [Étape 3 — mettre en correspondance les chemins](#étape-3--mettre-en-correspondance-les-chemins)
- [Étape 4 — tester, puis pousser](#étape-4--tester-puis-pousser)
- [Pousser les rejets](#pousser-les-rejets)
- [Piles manuelles : import et envoi](#piles-manuelles-import-et-envoi)
- [Le webhook entrant](#le-webhook-entrant)
- [Diagnostic dans le visualiseur](#diagnostic-dans-le-visualiseur)
- [Référence de configuration](#référence-de-configuration)
- [Dépannage](#dépannage)

---

## Comment les deux voient le même fichier

Facet et Immich voient le même fichier sur le disque sous des chemins différents :

- **Facet** utilise le chemin absolu sur la machine qui exécute l'analyse, p. ex. `/mnt/photos/2026/07/IMG_1234.jpg`.
- **Immich** utilise son `originalPath` : le chemin tel qu'il est vu *depuis l'intérieur du conteneur Immich*. C'est souvent `/usr/src/app/upload/…` pour les envois, ou le point de montage d'une bibliothèque externe.

Vous indiquez une fois à Facet la réécriture de préfixe, dans `immich.path_map`. Toute résolution y passe. Si elle est incorrecte, tout rapporte « unmatched » — voir [Dépannage](#dépannage).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

La correspondance fonctionne dans les deux sens. `--immich-sync` l'utilise pour trouver la ressource Immich d'un chemin Facet. Le webhook l'utilise pour trouver la photo Facet d'un `originalPath` Immich.

## Étape 1 — partager la bibliothèque avec Immich

La configuration la plus simple est une **bibliothèque externe** Immich : Immich lit les photos là où elles se trouvent déjà, et Facet analyse le même répertoire.

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

Aucun fichier n'est dupliqué sur le disque.

Vous pouvez aussi envoyer vers Immich comme d'habitude (sauvegarde mobile, uploader web) et pointer Facet vers le répertoire d'upload d'Immich. Seuls les préfixes changent. Relancez l'analyse Facet après les envois, ou utilisez `--watch`.

## Étape 2 — créer une clé API

Dans Immich : **cliquez sur votre avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 permet de restreindre une clé à certaines portées. La synchronisation notes/favoris nécessite celles-ci (les piles manuelles en demandent davantage, voir plus bas) :

| Portée | Ce que Facet en fait |
|-------|-------------------------|
| `server.about` | Contrôle de connectivité/authentification pour `--immich-test` |
| `asset.read` | Résoudre les ressources par `originalPath` |
| `asset.update` | Écrire `rating` et `isFavorite` |
| `album.read` | Trouver l'album de coups de cœur par son nom et lire ses membres |
| `album.create` | Créer l'album de coups de cœur la première fois |
| `albumAsset.create` | Ajouter des photos à l'album de coups de cœur |
| `albumAsset.delete` | Retirer les photos repassées sous le seuil des coups de cœur |

Vous pouvez omettre les quatre portées d'album si `push.top_picks_album` est vide. Facet ne touche aux albums que lorsque ce nom est défini. Sans `albumAsset.delete`, la synchronisation continue : les retraits refusés sont ignorés et comptabilisés dans le résumé, et la simulation les prévisualise.

Facet envoie la clé dans un en-tête `x-api-key`. Placez-la dans `scoring_config.json` :

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Remarque :** Facet écrit les notes avec `PUT /api/assets`. Immich le marque comme obsolète, mais son remplaçant n'est pas encore publié ; Facet continue donc de l'utiliser.

## Étape 3 — mettre en correspondance les chemins

Ajoutez une paire par racine partagée. Règles :

- La première correspondance de préfixe l'emporte. C'est une comparaison de chaîne simple, pas de répertoire.
- Terminez les préfixes de répertoire par `/`.
- Placez les correspondances étroites avant les correspondances larges.

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

L'exemple fourni par défaut (`{"facet_prefix": "", "immich_prefix": ""}`) laisse les chemins inchangés. Cela ne fonctionne que si Facet et Immich voient des chemins absolus identiques, ce qui est rare sauf si Facet s'exécute dans le conteneur Immich.

Pour trouver la vraie valeur, ouvrez une photo dans Immich et appuyez sur `i` pour afficher le panneau d'informations. Comparez son chemin de fichier avec le chemin que Facet affiche pour la même photo.

## Étape 4 — tester, puis pousser

```bash
# Connectivité + authentification uniquement. Aucune écriture.
python facet.py --immich-test

# Résout chaque ressource et indique ce qui CHANGERAIT. Toujours aucune écriture.
python facet.py --immich-sync --dry-run

# Pour de vrai.
python facet.py --immich-sync
```

La synchronisation rapporte `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / albums créés. Lors d'une simulation, `updated` compte les ressources qui changeraient, et rien n'est écrit. Un nombre élevé de `unmatched` au premier lancement signifie presque toujours que la correspondance des chemins est incorrecte — voir [Dépannage](#dépannage).

Ce qui est poussé :

- **Notes en étoiles 1–5** → le `rating` d'Immich. Une photo non notée ne pousse rien.
- **Favoris** → l'`isFavorite` d'Immich.
- **Effacements.** Si vous avez noté une photo, synchronisé, puis réinitialisé sa note, la synchronisation suivante envoie `rating: null` pour qu'Immich l'efface aussi. Facet se souvient de ce qu'il a poussé en dernier (dans `stats_cache`) pour cela. Il envoie `null`, jamais `0` : Immich v3 rejette `0`, et un seul lot rejeté interrompt toute la synchronisation.
- **Un album de coups de cœur** (facultatif), lorsque `push.top_picks_album` est défini : les photos notées au moins `push.top_picks_min_rating` en sont membres, et un membre repassé sous le seuil en est retiré lors d'une synchronisation globale tant que Facet sait l'y attribuer (une photo supprimée ou l'asset d'une autre application reste en place) ; un membre existant n'est jamais réajouté.

En mode multi-utilisateurs, `--immich-sync --user alice` pousse les notes propres à Alice (`user_preferences`) au lieu des notes globales, et suit son état de synchronisation séparément.

## Pousser les rejets

Désactivé par défaut. Quand il est activé, une photo que vous rejetez dans la vue de tri de Facet reçoit le marqueur de rejet d'Immich :

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

- Une photo rejetée pousse `rating: -1`, la valeur « rejeté » d'Immich v3.
- **Le rejet l'emporte sur les étoiles.** Une photo à 5 étoiles mais rejetée pousse `-1`, pas `5`.
- **Annuler le rejet l'efface.** La photo pousse alors sa note en étoiles actuelle, ou `rating: null` si elle n'en a aucune.
- Une photo rejetée ne rejoint jamais l'album de coups de cœur.
- `push.ratings: false` le désactive aussi, puisque `-1` est une note.

Laissez-le désactivé si d'autres personnes (ou votre téléphone) consultent la bibliothèque Immich : elles verront le `-1`.

## Piles manuelles : import et envoi

Les piles manuelles ont leur propre flux de **plan/application en CLI locale**, avec les options habituelles `--config`, `--db` et `--user`. La synchronisation notes/favoris n'est pas affectée.

Prérequis :

- Immich **≥ 3.0** (Facet vérifie aussi la prise en charge des piles à l'exécution).
- Permissions de la clé : `user.read` et `stack.read` en plus de `asset.read` ; l'envoi nécessite aussi `stack.create` et `asset.update`. `stack.update` et `stack.delete` ne sont pas nécessaires.
- Les installations multi-utilisateurs doivent nommer un utilisateur existant.
- La clé Immich n'est jamais utilisée par les opérations de piles depuis la visionneuse web, les assistants (MCP) ou le webhook d'envoi.

Flux de travail :

1. Aperçu. Il est en lecture seule des deux côtés et ne migre pas la base.
2. Examinez le plan et son empreinte SHA-256.
3. Appliquez explicitement.

Options et limites :

- `--stack-id UUID` (répétable) limite l'exécution à ces piles source.
- `--stack-plan-out` écrit un nouveau fichier JSON privé (mode POSIX `0600`) et refuse d'écraser.
- Un plan contient au plus **1000 groupes, 1000 membres par groupe, 20000 membres au total et 16 MiB**. Utilisez `--stack-id` pour le réduire.
- Sous Windows, choisissez un dossier de sortie dont l'ACL limite l'accès à votre compte ; les bits de mode POSIX n'y protègent pas le fichier.

Règles de correspondance :

- Chaque membre doit correspondre à exactement une photo indexée, visible et en ligne appartenant au compte distant. Un membre absent ou ambigu fait ignorer tout le groupe.
- L'envoi ne crée une pile qu'à partir de ressources distantes qui ne sont pas encore empilées.
- Une correspondance exacte des membres et de la couverture relie les deux piles à l'application.
- Les chevauchements partiels, les couvertures différentes, les membres modifiés et les cas empilés d'un seul côté sont ignorés comme conflits. Les piles existantes ne sont jamais mises à jour.
- Seule la couverture fait l'aller-retour ; l'ordre des autres membres, non.
- Il n'y a pas de synchronisation bidirectionnelle automatique, de sondage ni de propagation du désempilage.

Les plans, liens et reçus sont liés au serveur, au compte distant, au propriétaire local et à la correspondance des chemins. Changez l'un d'eux et l'ancien plan ne s'applique plus. Les reçus conservent les résultats et les identifiants de ressources distantes, jamais d'identifiants de connexion.

L'application revérifie chaque groupe avant d'écrire et le relit ensuite. Si une réponse de création est perdue, Facet la réconcilie avant tout réessai au lieu de la renvoyer. L'annulation s'arrête entre les groupes ; une application ultérieure reprend à partir des reçus.

> **Avertissement :** Immich ne peut pas créer une pile de façon conditionnelle. Un autre client peut modifier les ressources entre la dernière vérification de Facet et l'écriture, et Facet ne peut pas l'annuler.

## Le webhook entrant

Le webhook fonctionne dans l'autre sens : Immich indique à Facet qu'une ressource a changé, et Facet répond avec ce qu'il en sait.

**Il est désactivé par défaut et ne déclenche jamais d'analyse.** À la place :

- **Photo connue et notée** → Facet repousse immédiatement sa note et son favori vers Immich. Notez une photo, envoyez-la, et la note atterrit dans Immich sans attendre `--immich-sync`.
- **Photo inconnue ou pas encore notée** → Facet ajoute le chemin à une liste d'attente bornée, et le prochain `--immich-sync` la journalise.

### Activer

Le jeton est un secret : il vit donc dans une variable d'environnement, pas dans `scoring_config.json` (ce fichier est lisible par tout le monde sur la plupart des installations). La configuration nomme la variable ; la variable détient la valeur.

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

Si `token_env` est vide, ou si la variable est non définie ou vide, le point d'accès est désactivé et renvoie **404** (comme `frame.tokens` et `upload.username`).

### Diriger Immich vers le webhook

Dans Immich ≥ 3.0 : **Administration → Workflows → Create Workflow**.

1. **Trigger** — `Asset uploaded`. Ajoutez `Asset updated` si les modifications doivent aussi le déclencher.
2. **Action** — choisissez **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, avec une adresse que le conteneur Immich peut réellement atteindre. Si les deux tournent dans Docker sur un même hôte, c'est le nom du service (`http://facet:5000/…`), pas `localhost`.
4. **Header** — nom `x-facet-token`, valeur votre jeton. Le nom doit correspondre à `webhook.header`. `Authorization: Bearer <token>` est aussi accepté, pour les proxys qui n'offrent que cela.
5. Enregistrez, puis envoyez une photo pour confirmer.

### Ce que renvoie le point d'accès

| Statut | Signification |
|--------|---------|
| `202` | Accepté. Le JSON compte les ressources de cette livraison : `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | JSON valide, mais aucune ressource reconnue par Facet. Journalisé, pas une erreur. |
| `400` | Le corps n'était pas du JSON. |
| `401` | Aucun jeton dans la requête. |
| `403` | Mauvais jeton. |
| `404` | La fonctionnalité est désactivée (aucun jeton configuré). |

Facet lit `originalPath` où qu'il se trouve dans le payload : une ressource seule, `{"asset": {…}}`, une liste, ou n'importe lequel de ces cas sous `data` / `items` / `assets`. Si le payload contient l'`id` de la ressource, Facet la récupère dans Immich et vérifie son chemin et son propriétaire/sa bibliothèque avant la mise à jour. Une incohérence compte comme `failed`.

Les chemins en attente sont rapportés par la synchronisation suivante :

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Analysez ces photos (`python facet.py /mnt/photos`) et elles quittent la liste à la synchronisation suivante. La liste garde au plus `max_pending` entrées et supprime les plus anciennes en premier.

### Notes de sécurité

- Le jeton est comparé à temps constant ; un jeton erroné reçoit un simple `403`, sans indice temporel.
- Servez la visionneuse en HTTPS sauf si Immich l'atteint par un réseau privé : le jeton voyage dans un en-tête à chaque envoi.
- Pour effectuer la rotation du jeton, changez ensemble la variable d'environnement et l'en-tête du workflow Immich, puis redémarrez la visionneuse.
- Le webhook pousse la note globale, pas celle d'un utilisateur en particulier. Pour des notes par utilisateur dans Immich, laissez le webhook désactivé et lancez `--immich-sync --user <nom>` selon un calendrier.

## Diagnostic dans le visualiseur

Dans le sous-menu **Tâches et diagnostics** du menu utilisateur, ouvrez **Diagnostic Immich**. En multi-utilisateur, il faut un accès superadministrateur ; en mono-utilisateur, un accès édition (ou une édition locale approuvée).

- Rien n'est lu depuis Immich avant que vous ne cliquiez sur **Tester la connexion**. Le test lit la version du serveur et l'accès au compte, et n'écrit rien.
- La couverture des chemins vérifie au plus 200 photos indexées. Elle ne confirme pas que chacune correspond à une ressource Immich.
- L'heure de dernière synchronisation peut précéder un changement du serveur configuré.
- La vérification de version ne contrôle pas les permissions des piles.
- Les identifiants et les chemins du serveur ne sont jamais affichés.

## Référence de configuration

Le bloc `immich` complet, avec les valeurs par défaut fournies :

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
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
| `owner_id` | `""` | Ne retient que les ressources ayant exactement cet `ownerId` Immich. |
| `library_id` | `""` | Ne retient que les ressources de cette `libraryId` Immich exacte. Vide signifie n'importe quelle bibliothèque. |
| `path_map` | une paire vide | Réécritures de préfixe entre les chemins Facet et l'`originalPath` d'Immich. La première correspondance l'emporte ; utilisé dans les deux sens. |
| `push.ratings` | `true` | Pousse les notes en étoiles 1–5 (et leurs effacements). |
| `push.favorites` | `true` | Pousse `isFavorite` (et son effacement). |
| `push.rejected` | `false` | Pousse `rating: -1` pour les photos rejetées dans Facet. Nécessite `push.ratings`. |
| `push.top_picks_album` | `""` | Nom de l'album à remplir en continu : les membres sous `push.top_picks_min_rating` en sont retirés lors d'une synchronisation globale tant que Facet sait les y attribuer. Vide signifie que Facet ne touche jamais aux albums. |
| `push.top_picks_min_rating` | `4` | Note en étoiles minimale pour cet album. |
| `webhook.token_env` | `""` | Variable d'environnement contenant le secret du webhook. Vide désactive le point d'accès. |
| `webhook.header` | `"x-facet-token"` | En-tête dans lequel Immich envoie le jeton. |
| `webhook.max_pending` | `500` | Longueur maximale de la liste des chemins en attente (non notés). |
| `timeout_seconds` | `30` | Délai d'expiration HTTP par requête. |

## Dépannage

### Tout revient en `unmatched`

La correspondance des chemins est incorrecte. C'est de loin la panne la plus fréquente.

1. Ouvrez une photo dans Immich et appuyez sur `i`. Notez le chemin dans le panneau d'informations.
2. Retrouvez le chemin de cette même photo dans Facet (le panneau de détail de la galerie, ou `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Les deux chemins se terminent de la même façon. Les parties qui diffèrent sont votre `facet_prefix` et votre `immich_prefix`.

Pièges courants :

- **Une barre oblique finale manquante.** `"/mnt/photos"` → `"/usr/src/app/external"` réécrit aussi `/mnt/photosXYZ/a.jpg`. Terminez les deux préfixes par `/`.
- **Chemin hôte contre chemin conteneur.** Le chemin Immich est ce que voit le *conteneur*. Vérifiez avec `docker compose exec immich-server ls /usr/src/app/external`.
- **Liens symboliques et montages liés (bind mounts).** Immich stocke le chemin qu'il a parcouru. Un lien symbolique d'un seul côté fait différer les chaînes.
- **Casse et Unicode.** La comparaison est exacte. Sur un partage insensible à la casse, `/Photos/` et `/photos/` ne correspondent pas l'un à l'autre.
- **Immich n'a pas encore indexé le fichier.** Lancez **Scan All Libraries** et vérifiez que la ressource existe dans Immich.

`--immich-sync --dry-run` journalise les 20 premiers chemins non appariés, ce qui révèle généralement le mauvais préfixe.

### `--immich-test` échoue

- `Unsupported Immich URL scheme` — `url` a besoin de `http://` ou `https://`.
- `HTTP 401` — la clé API est incorrecte ou a été révoquée.
- `HTTP 403` — il manque `server.about` à la clé. Recréez-la avec les sept portées ci-dessus.
- Connexion refusée / délai dépassé — le port est incorrect, ou Facet ne peut pas atteindre le conteneur. Testez avec `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` depuis la machine qui exécute Facet.

### Le webhook renvoie 404

La fonctionnalité est désactivée : `webhook.token_env` est vide, ou la variable qu'il nomme est non définie ou vide *dans l'environnement de la visionneuse*. L'exporter dans votre shell ne l'atteint pas si la visionneuse est lancée par systemd ou Docker. Définissez-la dans le fichier d'unité ou le fichier compose, puis redémarrez.

### Le webhook renvoie 401 ou 403

`401` : aucun jeton n'est arrivé, donc le nom d'en-tête envoyé par Immich ne correspond pas à `webhook.header`. `403` : le jeton est erroné. Comparez la valeur d'en-tête du workflow avec la variable d'environnement.

### `ModuleNotFoundError: No module named 'sync'`

Le serveur semble sain, mais le webhook échoue quand Immich l'appelle et `--immich-sync` échoue d'emblée. Vérifiez avec :

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Si vous obtenez `ModuleNotFoundError: No module named 'sync'`, votre image Docker est trop ancienne. Récupérez l'image actuelle ou reconstruisez-la depuis un dépôt à jour.

### Les notes se poussent, mais pas les effacements

Facet n'efface qu'une note qu'il a déjà poussée, et il s'en souvient dans `stats_cache`, dans la base de données de Facet. Restaurer une base plus ancienne, ou en utiliser une neuve, perd cette mémoire : une note effacée pendant cet intervalle reste dans Immich. Re-notez puis re-effacez la photo, ou corrigez-la dans Immich.

### Les notes apparaissent sur les mauvaises photos

Facet ignore les correspondances ambiguës et les signale comme `identity_conflicts` :

- un chemin Facet qui correspond à plusieurs ressources Immich
- plusieurs chemins Facet qui désignent le même chemin Immich

Rien n'est écrit pour ces chemins ; les autres photos se synchronisent normalement.

Un lot de webhook est plus strict : si plusieurs chemins Facet revendiquent la même cible ou le même identifiant de ressource, chaque entrée éligible du lot est refusée et comptée comme `failed`. Corrigez les racines qui se chevauchent dans `path_map`, ou renseignez `owner_id` et `library_id`, puis réessayez. Ne devinez pas le propriétaire à partir du nom d'une personne ou du chemin.

Les réponses d'Immich doivent contenir `id` et `originalPath`, et correspondre au propriétaire et à la bibliothèque configurés. Une mise à jour réussie signifie qu'Immich l'a acceptée ; son propre traitement de métadonnées en arrière-plan peut encore être en cours.

### `rating: 0 is not valid`

Le serveur Immich est antérieur à la version 3.0. Mettez-le à niveau — la sémantique d'effacement de Facet a besoin de `null`, et `push.rejected` a besoin de `-1` ; il n'existe aucun repli qui fonctionne sur la 2.x.

---

**Voir aussi :** [Commandes — Synchronisation Immich](COMMANDS.md#synchronisation-immich) · [Configuration](CONFIGURATION.md) · [Recettes d'interopérabilité avec les éditeurs](INTEROP.md) pour l'aller-retour XMP avec Lightroom, darktable et digiKam.
