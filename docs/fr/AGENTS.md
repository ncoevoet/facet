# Agents IA (MCP)

> 🌐 [English](../AGENTS.md) · **Français** · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · [简体中文](../zh/AGENTS.md)

Facet peut jouer le rôle de serveur [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) : un assistant IA compatible MCP peut ainsi rechercher et inspecter votre bibliothèque avec les filtres de la galerie. Il expose quatorze outils de lecture qui ne modifient rien et quinze outils `ui_*` qui pilotent l'onglet du navigateur que vous avez ouvert (page, filtres, sélection) sans écrire de données de la bibliothèque. Les jetons d'un niveau suffisant peuvent aussi [modifier des éléments](#modifier-la-bibliothèque) (notes, indicateurs, étiquettes, albums, tri et suppression) et piloter la [chambre noire](#chambre-noire-groupes-de-tri).

## L'activer

Le point d'accès est **activé par défaut**. Pour le désactiver, mettez `viewer.mcp.enabled` à `false` dans `scoring_config.json` (voir [Point d'accès agent (MCP)](CONFIGURATION.md#point-daccès-agent-mcp)), puis redémarrez la visionneuse ou rechargez la configuration. `/mcp` et toutes les routes `/api/mcp/*` répondent alors 404.

**Installations ouvertes.** Sans `viewer.password`, l'installation est considérée comme ouverte, même si `viewer.edition_password` est défini. Sur une installation ouverte :

- les jetons sont `readonly`, sauf si `viewer.trusted_local_editing` est actif, ou si le jeton est un jeton d'édition complète créé dans une session connectée avec le mot de passe d'édition et utilisé depuis le même ordinateur (voir plus bas) ;
- le point d'accès ne sert qu'une clé anonyme en lecture seule, qui n'accorde rien que l'`/api` ouverte n'accorde déjà ;
- les jetons ne se gèrent que depuis l'ordinateur qui exécute Facet, ou dans une session d'édition quand `viewer.edition_password` est défini (voir [Créer un jeton](#créer-un-jeton)).

Le point d'accès est `POST /mcp` sur le port de la visionneuse : HTTP diffusable (Streamable HTTP), sans état, réponses JSON simples (`GET` répond 405). Seul le pont d'onglet, `/api/mcp/bridge`, est un WebSocket ; voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert).

## Créer un jeton

Le plus simple passe par le navigateur :

1. Avec `viewer.mcp.enabled` activé, ouvrez le menu du compte et choisissez **Connecter un assistant**.
2. Saisissez un **Nom** et choisissez **Ce que l'assistant peut faire** : **Lecture et pilotage uniquement**, **Agir à ma place** ou **Édition complète**. Un jeton ne peut pas dépasser la session qui le crée.
3. Cliquez sur **Créer le jeton**. La boîte affiche **Collez ceci dans votre assistant**, une invite toute prête qui contient le jeton. Elle n'est affichée qu'une fois : cliquez sur **Copier l'invite**, collez-la dans votre assistant, puis cliquez sur **Terminé**.

**Gérer les jetons (N)** liste vos jetons avec leur dernière utilisation et permet d'en révoquer un. Une ligne d'état indique si cet onglet est connecté, donc pilotable par les assistants.

La boîte ne propose que les niveaux que le serveur accordera :

- une installation ouverte propose **Lecture et pilotage uniquement**, et **Édition complète** dans les cas indiqués ci-dessous ;
- **Agir à ma place** n'apparaît que sur les installations multi-utilisateurs ;
- **Édition complète** n'apparaît que dans une session d'édition ; sur une installation ouverte, cela signifie un navigateur du même ordinateur avec `viewer.trusted_local_editing` actif, ou une session connectée avec `viewer.edition_password` (le jeton ne modifie alors que depuis le même ordinateur).

L'invite indique le niveau réellement accordé. Sur une installation ouverte, depuis une autre machine et sans session d'édition, la boîte affiche « Sur une installation ouverte, les jetons d'assistant ne se gèrent que depuis l'ordinateur qui exécute Facet. Définissez viewer.password pour les gérer depuis une autre machine. » à la place du formulaire.

Alternative par script (curl) :

Un assistant s'authentifie avec un jeton personnel commençant par `fct_`. Créez-en un avec une requête authentifiée. Le jeton n'est renvoyé qu'**une seule fois** ; Facet ne conserve que son empreinte SHA-256 :

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

La réponse contient le jeton en clair dans `token`.

- `GET /api/mcp/tokens` liste vos jetons (jamais le secret) ; `DELETE /api/mcp/tokens/{id}` en révoque un.
- Un superadmin peut lister les jetons de tous les propriétaires avec `?all=1` et en révoquer n'importe lequel.
- Chaque propriétaire peut détenir au plus 20 jetons actifs.
- Ces routes refusent les identifiants d'un agent : un assistant ne peut donc jamais créer, lister ni révoquer de jetons.

Sur une installation ouverte (sans `viewer.password`), ces routes refusent aussi toute requête qui ne vient pas de l'ordinateur qui exécute Facet :

- une requête passant par un proxy inverse (un en-tête `Forwarded`, `X-Forwarded-*` ou `X-Real-IP`) ;
- une requête adressée à une IP du réseau local ou à un nom d'hôte au lieu de `localhost`, `127.0.0.1` ou `[::1]` ;
- une requête arrivant par le réseau pont de Docker.

Exécutez la recette ci-dessus sur l'hôte Facet (en SSH sur un NAS ; sous Docker, `docker compose exec facet python -c "import urllib.request ..."`, car l'image n'a pas curl) ou définissez `viewer.password`. Une session ouverte avec `viewer.edition_password` est acceptée depuis n'importe quelle machine. Un proxy inverse doit envoyer `X-Forwarded-For` ou `Forwarded`, sinon il est traité comme la machine locale.

## Connecter votre assistant

L'invite de la boîte contient tout ce dont un assistant a besoin : le nom du serveur `facet`, l'URL (`http://<hôte>/mcp`), le transport (Streamable HTTP), l'en-tête `Authorization: Bearer fct_...`, le niveau accordé et un appel à l'outil `status` pour confirmer la connexion. Collez-la dans votre assistant, ou ajoutez vous-même ce serveur à votre client MCP. Utilisez HTTPS dès que la visionneuse est accessible au-delà de votre machine : le jeton transite dans un en-tête à chaque appel.

## Niveaux d'autorisation

Un jeton est créé avec un niveau accordé : `readonly`, `user` ou `edition`. À chaque appel, le niveau **effectif** est recalculé : c'est le plus bas entre le niveau accordé et le niveau actuel du propriétaire. Chaque outil a son propre niveau minimal, vérifié avant toute lecture ou écriture ; un jeton plus bas reçoit `forbidden_level`.

- **Installations à mot de passe unique** : pas de niveau `user`. Un niveau `user` est ramené à `readonly` à la création, et le niveau effectif est `edition` ou `readonly`. Les outils marqués `user` dans [Modifier la bibliothèque](#modifier-la-bibliothèque) exigent donc un jeton `edition` ; un jeton plus bas reçoit `forbidden_level`, qui précise qu'il faut `edition`. Un jeton `edition` exige une session d'édition et ne fonctionne que tant que le mot de passe d'édition ne change pas.
- **Installations multi-utilisateurs.** Si le propriétaire est rétrogradé, un jeton `edition` passe à `user`. Une promotion n'élève jamais un jeton au-dessus de son niveau accordé.
- **Installations ouvertes** (aucun `viewer.password`, même si `viewer.edition_password` est défini). Les jetons appartiennent à un propriétaire partagé `_anonymous` et sont `readonly`, sauf si `viewer.trusted_local_editing` est actif ou que le jeton provient d'une session d'édition (deux points suivants).
- **Édition locale sur une installation ouverte.** Avec `viewer.trusted_local_editing` actif, la boîte Connecter un assistant peut créer un jeton **Édition complète** depuis un navigateur du même ordinateur. `viewer.mcp.enabled` et un jeton restent nécessaires (un appel sans jeton reste 401).
  - Le jeton n'est `edition` que pour les requêtes `/mcp` venant de la même machine : pair en loopback, URL `http://localhost:<port>` ou `127.0.0.1` et aucun en-tête de proxy. `:4200` (le proxy de développement `ng serve`) comme `:5000` conviennent.
  - Toute autre requête passe en `readonly`, même si l'invite annonce l'édition complète : client du réseau local, URL à nom d'hôte ou `0.0.0.0`, déploiement Docker.
  - Définir un mot de passe quelconque abaisse le jeton à `readonly` ; retirer le mot de passe le rétablit.
  - Les outils de suppression exigent toujours `viewer.mcp.allow_destructive`.
  - Le scan (`start_scan`, `scan_status`) fonctionne sans `viewer.features.show_scan_button`, comme pour le navigateur local.
- **Mot de passe d'édition sur une installation ouverte.** Avec `viewer.edition_password` défini et sans `viewer.password`, une session connectée avec le mot de passe d'édition peut créer un jeton **Édition complète**, depuis n'importe quelle machine ; toute autre session obtient `readonly`.
  - Le jeton n'est `edition` que pour les requêtes `/mcp` qui passent le même contrôle de machine locale que ci-dessus. Un client du réseau local ou une requête passée par un proxy obtient `readonly` : le jeton est un secret au porteur sur une installation que tout le monde peut lire.
  - Changer ou effacer le mot de passe d'édition le ramène à `readonly` ; créez-en un nouveau après le changement.
  - Le scan exige toujours `viewer.features.show_scan_button`, comme une session d'édition dans le navigateur. Les outils de suppression exigent toujours `viewer.mcp.allow_destructive`.

> **Avertissement :** `ng serve --host 0.0.0.0`, ou tout proxy sur la même machine qui n'ajoute aucun en-tête de proxy, laisse un client du réseau local envoyant `Host: localhost` passer pour local. Seul le jeton protège alors `/mcp`.

Un jeton cesse de fonctionner dès que les identifiants de son propriétaire changent : mot de passe de la visionneuse ou d'édition (mode mot de passe unique), mot de passe du propriétaire (mode multi-utilisateur), ou suppression de son compte. Il reçoit alors une réponse 401.

## Outils

Les quatorze outils de données sont en lecture seule :

| Outil | Rôle |
|------|--------------|
| `search_photos` | Filtre et trie la bibliothèque comme la galerie, en appliquant les masquages par défaut de la visionneuse (clignements, rafales, doublons, bracketings, panoramas, rejetées) sauf si le filtre les précise (renvoie `hidden_summary`). Affiché par défaut dans votre onglet ouvert (voir plus bas) ; `fields` ajoute n'importe quelle colonne de photo |
| `semantic_search` | Trouve des photos par le sens, ou par les mots des légendes avec `scope: "text"` Les lignes renvoyées sont épinglées dans l'onglet. `filters` restreignent la recherche comme ceux de la galerie, et chaque ligne porte sa `similarity`. |
| `get_photo` | Détail complet d'une photo à partir de son chemin (sans l'histogramme); ou `target: "selection"` (avec `tab_id`) pour l'unique photo sélectionnée |
| `get_photo_stack` | Lire la pile locale par chemin exact, ou null |
| `get_thumbnail` | Voir une photo : sa miniature comme partie image (`size` de 160 à 640, 512 par défaut). Une taille plus petite est utilisée si le JPEG dépasserait `viewer.mcp.max_image_bytes` ; `too_large` si aucune ne tient; ou `target: "selection"` (avec `tab_id`) pour l'unique photo sélectionnée |
| `contact_sheet` | Voir 1 à 16 photos en une grille numérotée (`columns` de 2 à 4, plus grand côté 1024). La partie texte liste `legend` (numéro de case vers chemin, dans l'ordre demandé) et `unavailable` (cases laissées vides car la photo est absente ou non visible); ou `target: "selection"` pour les photos sélectionnées (16 au plus) |
| `possible_faces` | Visages qui ressemblent à une personne reconnue : similarité cosinus au centroïde de la personne, meilleurs d'abord, même modèle d'embedding uniquement. `scope` vaut `unassigned` (défaut), `unnamed` (visages sans groupe ou dans un groupe que personne n'a nommé), `other_persons` ou `all` ; `min_similarity` vaut 0,30 par défaut ; `limit` jusqu'à 100. Une analyse de plus de 192000 visages est refusée (`too_large`) : restreignez avec `scope`, `path_prefix`, `date_from` ou `date_to`. Les photos s'affichent dans votre onglet. Chaque ligne porte le champ `owner` (`ungrouped`, `unnamed_group` ou `named`). `candidates` est le nombre de visages du périmètre que vous pouvez voir, avant la vérification de la dimension d'embedding ; `faces_scanned` est le nombre de lignes réellement évaluées. |
| `similar_photos` | Photos similaires à une photo, par plongement visuel ou par couleur ; `min_similarity` (0 à 1) fixe le seuil |
| `filter_options` | Le vocabulaire accepté par un filtre : appareils, objectifs, étiquettes, personnes, motifs, catégories, moments narratifs, types d'indésirables, plages de métriques |
| `list_persons` | Personnes reconnues, filtrables par nom; `show: true` ouvre `/persons` avec cette recherche |
| `list_albums` | Albums visibles par le propriétaire du jeton; `show: true` ouvre `/albums` avec cette recherche |
| `library_stats` | Statistiques de la bibliothèque : `kind` choisit l'aperçu de la taille et des scores (par défaut) ou n'importe quelle donnée de la page Statistiques (voir plus bas) |
| `status` | Identité du jeton, son niveau effectif et les réglages du serveur et les onglets ouverts qu'il peut piloter |
| `available_actions` | Les tâches qui s'appliquent maintenant à votre onglet ouvert et à ce jeton, chacune avec ses outils ; les outils au-dessus du niveau du jeton ne sont pas listés |

Remarques sur les filtres :

- `show_rejected` est un booléen : `true` ne liste que les photos rejetées ; `false` ou son absence donne la liste normale. Les agents peuvent l'appliquer avec `ui_set_gallery_filters` pour afficher dans l'onglet des recherches limitées aux rejetées. Les albums intelligents peuvent aussi l'enregistrer (false est omis).
- Un `review_status` explicite détermine la décision de tri à la place de `show_rejected` ou `hide_rejected`, et désactive `show_rejected` dans l'onglet.
- `show_rejected: true` avec `favorites_only: true` est refusé pour les modifications de l'onglet et la création d'albums intelligents (`invalid_input`). Une recherche renvoie toujours l'intersection, mais indique `shown_in_tab.reason: invalid_combination` et laisse l'onglet inchangé.
- `blinks_only` et `duplicates_only` sont eux aussi des booléens. `true` ne garde que les photos marquées comme clignements, ou les membres d'un groupe de doublons (têtes comprises). Comme `show_rejected`, ils montrent chacune de ces photos quelles que soient les bascules de masquage.

## Les résultats s'affichent dans votre onglet

- **Les recherches s'affichent dans votre onglet.** `search_photos`, `semantic_search` et `similar_photos` acceptent `show` (`true` par défaut). Après une recherche réussie sur la première page, le serveur l'affiche dans l'onglet Facet ouvert : vous voyez ce que l'assistant a trouvé sans avoir à le demander.
  - `search_photos` et `similar_photos` appliquent la même requête à l'onglet, en remplaçant ses filtres.
  - `semantic_search` épingle exactement les lignes renvoyées (ordre de similarité, au plus `limit`, avec ou sans `filters` ou `scope`) comme liste choisie par l'assistant (`shown_in_tab.mode` vaut `paths`), car la vue sémantique propre à l'onglet filtre et trie autrement.
  - `show: false` sert aux sondages intermédiaires et aux décomptes ; on indique aux assistants de ne jamais demander s'il faut afficher les résultats.
- Le résultat porte `shown_in_tab` : `{"applied": true, "tab_id", "keys", "total"}`, ou `{"applied": false, "reason"}`. Raisons : `error` (l'affichage lui-même a échoué), `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (l'onglet peut encore l'appliquer), `forbidden`, `invalid_input`, `upstream_error`, `page_not_first`, `empty_result`, `unsupported_filters` (avec `keys`), `invalid_combination`, `unsaved_decisions`, `navigation_refused` (l'onglet a refusé la navigation), `comparison_open` (l'utilisateur est sur `/compare`) et `modal_open` (une boîte de dialogue, une feuille inférieure ou un diaporama est ouvert dans l'onglet). Un affichage raté ne fait jamais échouer la recherche. Passez `tab_id` pour choisir un onglet. Quand des lignes sont raccourcies, `next_page` (avec `suggested_per_page`) désigne la page qui continue exactement après la dernière ligne renvoyée ; si les pages ne peuvent pas l'exprimer, `next_offset` la donne comme décalage en lignes.
- Seule la première page est affichée (l'onglet pagine lui-même au défilement). Un résultat vide n'est pas affiché : vous gardez votre vue précédente. Une recherche utilisant des filtres que la barre latérale de la galerie ne propose pas (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`) n'est jamais appliquée partiellement.
- Un affichage quitte `/photo` pour la galerie. Il quitte `/culling` seulement si l'utilisateur n'y a aucune décision non confirmée (sinon `unsaved_decisions`), et sur `/compare` il est refusé avec `comparison_open`. Il efface une sélection de toute la vue. Sur une page d'album, il revient d'abord à la galerie : les filtres enregistrés de l'album ne sont donc jamais écrasés. Une recherche dont le décompte alimente l'`expected_count` d'un outil d'écriture doit utiliser `show: false`.
- `list_albums`, `list_persons` et `junk_list` prennent `show` (`false` par défaut : ce sont surtout des recherches de nom). Avec `show: true`, ils ouvrent `/albums`, `/persons` ou `/junk` avec exactement la requête ; une requête vide efface la recherche de la page et réinitialise ses autres filtres. `junk_list` n'affiche que sa première page (sinon `page_not_first`) et jamais une liste vide (`empty_result`). `shown_in_tab` porte les mêmes raisons qu'une recherche, avec un `mode` valant `route`. `list_culling_groups` n'a pas de `show` : utilisez `ui_show_culling_group`.
- `ui_show_photos` épingle une liste exacte de photos, affichées dans votre ordre jusqu'à ce qu'un changement de filtre la remplace. `ui_get_context` indique si une liste épinglée est affichée. La liste est simple : ni groupes, ni marquages, ni libellés. Pour relire un plan de tri, l'assistant utilise `auto_cull`, qui ouvre le plan dans la [chambre noire](#chambre-noire-groupes-de-tri) (`/culling`).
- **Mode plan sur `/culling`.** `ui_show_culling_plan` (appelé par `auto_cull` lors d'un essai à blanc) charge un plan `auto_cull` dans la chambre noire. Vous retrouvez les mêmes groupes, les mêmes bordures garder/rejeter, la même loupe et la même comparaison que pour le tri manuel, avec les photos à garder du plan présélectionnées. Voir [Mode plan de l'assistant](VIEWER.md#mode-plan-de-lassistant).
  - L'utilisateur voit une bannière « Plan de l'assistant · x/y confirmés · Quitter », une pastille « #n · raison · suggestion : garder N / rejeter M » par groupe, et confirme groupe par groupe comme d'habitude. Le tri et le seuil sont désactivés ; le curseur de rigueur reste utilisable.
  - Déplacer le curseur, ou changer la plage de dates de la barre d'outils, recalcule le plan (nouveau `plan_digest`). Les groupes que vous avez inversés conservent votre choix. Un groupe se reforme comme confirmé quand il tombe à l'intérieur d'un groupe que vous avez confirmé, groupes de scènes compris ; avec `group_by=all`, un burst confirmé dont les photos gardées réapparaissent dans un plus grand groupe similar est proposé de nouveau (vos rejets restent appliqués). Les groupes ignorés reviennent. Une confirmation dont le compte à rebours court encore est validée aussitôt. Confirmer, passer et « tout confirmer » sont suspendus jusqu'à l'arrivée du nouveau plan.
  - Une plage de dates plus étroite reporte les inversions et les groupes confirmés selon leur ensemble de photos. Les groupes hors de la fenêtre disparaissent, et une notification signale les inversions perdues. **Toutes les dates** recalcule le plan sur toute la bibliothèque et peut atteindre la limite du plan (`plan_truncated`).
  - **Quitter**, ou un changement de regroupement, de portée album/scène ou de tri, quitte le mode plan. Quitter `/culling` puis y revenir rétablit le plan. Un rechargement complet de la page l'abandonne mais garde son album et ses dates dans l'URL (`?from=`, `?to=`), sur un flux manuel. Les confirmations faites en mode plan n'ajoutent jamais de sélection « highlights ».
  - **Badges de suggestion.** `ui_suggest_culling` marque les photos à garder ou à rejeter, avec une courte raison (un badge en pointillés), et ajoute des notes aux groupes (une pastille dans l'en-tête). Un clic sur un badge inverse cette photo ; sans clic rien ne change. Les marques survivent au déplacement du curseur ou de la plage de dates et à un nouvel affichage du même plan ; un autre plan, **Quitter** ou la sortie du mode plan les efface. Les badges apparaissent sur les vignettes du groupe seulement, pas dans la vue plein écran ni dans un groupe confirmé ou ignoré.
  - La réponse de l'assistant liste les chemins qu'il n'a pas conservés : `redundant` (déjà le choix du plan), `closed` (groupe confirmé ou ignoré) et `missing` (absents du plan). Les notes d'un groupe que vous avez confirmé, ignoré ou en cours de confirmation sont listées dans `groups_closed`. `suggestions_total` et `notes_total` indiquent ce que l'onglet conserve (au plus 300 suggestions et 100 notes).
- **Lire votre progression.** `ui_get_context.culling` vaut `null` hors du mode plan. En mode plan, il renvoie `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}` :
  - `confirmed` : les numéros de groupes du plan dont la confirmation est passée.
  - `pending` : les groupes que vous avez inversés par rapport au plan sans les confirmer.
  - `untouched` : le nombre des autres groupes.
  - `changed` : chaque groupe dont les photos gardées diffèrent du plan, sous la forme `{type, group_id, number, keep_paths, reject_paths}`.
  - `plan_truncated` vaut `true` quand le plan lui-même a atteint sa limite de groupes ou de photos et n'en liste qu'une partie.
  - Un bloc trop grand pour une réponse (le plafond de 100 Kio de l'onglet, ou celui du serveur) voit ses listes raccourcies et `truncated` passer à `true`. Les vrais effectifs restent dans `groups_total`, `confirmed_count`, `pending_count` et `changed_count`.
  - `culling.scope` (`{album_id, date_from, date_to}`) est la fenêtre pour laquelle le plan a été calculé.
  - `suggestions_open` (`[{path, action}]`) liste les marques en attente de votre clic, `suggestions_accepted` les marques dont vous avez mis la photo dans l'état suggéré, et `suggestions_total` les marques de photos conservées dans l'onglet (pas les notes de groupe). `suggestions_open_count` donne la vraie longueur quand cette liste est tronquée.

  Ne redécidez jamais un groupe confirmé. Un groupe burst ou similar confirmé disparaît de l'aperçu suivant. Un groupe scene confirmé n'est enregistré nulle part et peut être proposé de nouveau : passez donc `changed` comme `keep_paths` / `remove_paths` au prochain essai à blanc et à son application. `auto_cull` ne prend ses dates que de ses propres arguments : passez les dates de `culling.scope` avec `culling.changed` au prochain essai à blanc (le nouveau plan remplace celui affiché). Déplacer le curseur ou la plage de dates recalcule le plan : relisez `ui_get_context` avant le prochain essai à blanc.
- **Réglages de tri par défaut.** `ui_get_context` renvoie aussi `culling_defaults`, `{profile, strictness}` : les réglages qu'`auto_cull` utilise quand on ne lui en donne aucun (voir **Réglages repris de l'onglet** sous [Chambre noire](#chambre-noire-groupes-de-tri)). Ils sont mémorisés par navigateur, donc deux onglets les partagent. `culling_defaults.strictness` est la valeur vive et mémorisée du curseur : `null` quand seul un profil est mémorisé, 100 quand rien ne l'est. Un plan donné avec à la fois un profil et une `strictness` mémorise les deux. Déplacer le curseur hors du mode plan efface le profil mémorisé (mélange personnalisé) ; en mode plan, il le conserve.
- **Dates.** Les outils de tri (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) acceptent une date ISO (`2026-06-01`), une date-heure ISO (`2026-06-01T08:30:00`, ou avec une espace) ou la forme EXIF (`2026:06:01 08:30:00`). Un `date_to` sans heure couvre toute la journée. Les outils au jour près (`library_stats`, `possible_faces`, `cull_report` pour les décomptes comme pour les groupes de la chambre noire) n'acceptent qu'une date et refusent une heure avec `invalid_input`.
- Les lignes portent l'appareil, l'objectif, l'ouverture, la vitesse, les ISO, la focale et `is_monochrome`. `fields` (sur les trois outils de recherche) ajoute toute autre colonne de photo, hors données d'image et de plongements, par exemple `leading_lines_score`. `learned_score` n'est rempli que pour un tri sur ce score. Quand le plafond d'octets raccourcit les lignes, le résultat ajoute `returned` (et `next_offset` ou `suggested_per_page`).
- `library_stats` accepte `kind` (`overview` par défaut : taille, décomptes par type et aperçu des scores). Le `basis` de l'aperçu indique ce que compte chaque total. `total_photos` compte les photos que vous pouvez voir dans `date_from`/`date_to` et la catégorie (toutes si aucune n'est donnée) ; il ignore les bascules de masquage et inclut les photos rejetées. `type_counts` applique les bascules de masquage et ignore la date et la catégorie. Les autres valeurs sont en lecture seule et renvoient les données de la page Statistiques ; les longues listes sont coupées à 50 entrées avec `truncated: true` :

| Valeur de kind | Données |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | Les panneaux de la page Statistiques ; ils acceptent `date_from`, `date_to` et `category`. `correlations` accepte aussi `x`, `y` (liste séparée par des virgules), `group_by` et `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Statistiques par catégorie (sans paramètre) |
| `timeline_dates`, `timeline_months` | Nombre de photos par jour ou par mois ; elles exigent `year` (`timeline_dates` accepte aussi `month`) |
| `timeline_years` | Nombre de photos par année |

## Piloter votre onglet ouvert

En plus des outils de données, le serveur liste toujours quinze outils `ui_*` qui agissent sur l'onglet Facet que vous avez ouvert : ils changent de page, modifient les filtres ou la sélection et relisent ce que vous voyez. Ils n'écrivent jamais de données de la bibliothèque, un jeton `readonly` suffit donc.

| Outil | Ce qu'il fait |
|-------|---------------|
| `ui_navigate` | Aller à une page (galerie, personnes, albums, statistiques, ...) |
| `ui_set_gallery_filters` | Fusionner un correctif dans les filtres et le tri de la galerie (`null` retire un filtre, `replace: true` repart de zéro) |
| `ui_get_gallery_view` | Route, filtres actifs, total des résultats, premiers chemins de photos visibles et nombre de photos sélectionnées ; renvoie aussi `album_filter_json` (les filtres tels qu'un album intelligent les stockerait) et `filters_scopable` (si ces filtres décrivent toute la vue) |
| `ui_get_context` | La page ouverte (route), l'état de la galerie (total, nombre chargé, présence d'une liste épinglée), le nombre de photos sélectionnées et les `actions` qui s'appliquent à votre jeton ici ; aussi `focused` (la photo sur laquelle se trouve l'utilisateur), `culling` (le plan de l'assistant sur `/culling` : groupes confirmés, en attente et modifiés, et le `scope` pour lequel il a été calculé), `culling_defaults` (`{profile, strictness}` : le profil mémorisé et la rigueur vive et mémorisée du curseur, par navigateur ; `auto_cull` utilise les deux quand on ne lui en donne aucun) et `user_activity` (ce que l'utilisateur a fait), et accepte `activity_since` (voir plus bas); aussi `page` et `overlays` (voir plus bas) |
| `ui_open_photo` | Ouvrir une photo |
| `ui_open_album` | Ouvrir un album (fixe ou intelligent) par `album_id` ; un identifiant inconnu ou inaccessible répond `not_found` |
| `ui_show_photos` | Affiche exactement ces `paths` (jusqu'à 200) dans cet ordre comme liste de la galerie ; les introuvables reviennent dans `missing`. Tout changement de filtre remplace la liste |
| `ui_select_photos` | Sélectionner des `paths` explicites, ou toute la vue filtrée avec `select_view: true`, en mode `replace`, `add` ou `remove` |
| `ui_clear_selection` | Vider la sélection |
| `ui_get_selection` | Le `scope` (`paths` ou `view`) et le `count`, avec les `paths` ou, pour une vue, les `filters` et `excluded_paths` |
| `ui_next_page` | Charger la page suivante de la galerie |
| `ui_show_culling_group` | Ouvrir la chambre noire sur un groupe, identifié par `(type, group_id)` (comptes édition) |
| `ui_show_culling_plan` | Ouvrir la chambre noire sur un plan `auto_cull` (`plan_digest` et `request` de l'aperçu, `focus` facultatif : numéro de groupe), avec les photos à garder du plan présélectionnées pour que vous les inversiez et les confirmiez (comptes édition). `auto_cull` l'appelle pour vous lors d'un essai à blanc. Le même condensé que le plan déjà affiché ne fait que déplacer le focus ; un autre remplace le plan et est refusé avec `unsaved_decisions` tant que vous détenez des décisions non confirmées, et avec `plan_changed` quand la bibliothèque a bougé depuis l'aperçu, et avec `plan_load_failed` quand l'onglet n'a pas pu charger le plan pour une autre raison |
| `ui_suggest_culling` | Tant qu'un plan est affiché sur `/culling`, marque les photos que vous garderiez ou rejetteriez (`photos` : `path`, `action`, `reason`, jusqu'à 100) et les groupes à commenter (`groups` : le `path` d'une photo du groupe et une `note`, jusqu'à 50) ; une raison ou une note fait au plus 200 caractères. Vous voyez un badge par photo et une pastille par groupe, et rien ne change tant que vous ne cliquez pas sur un badge. Les appels fusionnent par chemin, `replace: true` supprime d'abord tout ce qui est conservé, et `replace` avec des listes vides efface tout. Répond `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}` ; refus : `no_plan` (l'onglet ne détient aucun plan), `too_large` (l'onglet conserve au plus 300 suggestions et 100 notes : utilisez `replace`) et `forbidden_level` (comptes édition uniquement). Avec plusieurs onglets ouverts, passez le `tab_id` de `shown_in_tab` ou de `status` |
| `ui_show_comparison` | Ouvrir la page de comparaison par paires, éventuellement sur une catégorie, une stratégie et un `tab` (`ab`, `snapshots`, `suggestions`, `weights`) ; elle ne fait qu'ouvrir la page, c'est vous qui choisissez les gagnants |

Fonctionnement :

- **Connexion.** Tant que vous êtes connecté et que `viewer.mcp.enabled` et `viewer.mcp.bridge` valent `true`, chaque onglet Facet ouvre un WebSocket de même origine vers `/api/mcp/bridge`, authentifié avec votre session dans son premier message. Le pont est actif par défaut. Mettez `viewer.mcp.bridge` à `false` pour le désactiver : les onglets ne se connectent alors pas du tout, et les outils `ui_*` répondent par une erreur explicite.
- **À qui sont les onglets.** Un outil n'atteint que les onglets du propriétaire du jeton. Avec un mot de passe unique, toutes les sessions forment le même utilisateur ; sur une installation ouverte, chaque onglet appartient à l'utilisateur partagé `_anonymous`, y compris les connexions en mode édition.
- **Niveaux des onglets.** Chaque onglet porte le niveau de la session qui l'a ouvert. Un jeton ne pilote que les onglets de niveau égal ou supérieur au sien : un jeton `edition` n'utilise jamais un onglet de simple consultation, alors qu'un jeton `readonly` peut piloter un onglet `edition`.
  - Installation à mot de passe unique : un jeton est aussi borné par la session qui l'a créé. Un jeton créé depuis une session de consultation ne pilote que les onglets de consultation, jamais l'onglet d'édition (un jeton antérieur à cette règle est borné à son propre niveau).
  - Installation ouverte : un jeton ne pilote que les onglets de consultation, jamais un onglet `edition`, sauf l'onglet d'édition local ci-dessous. Un jeton d'édition complète créé dans une session connectée avec le mot de passe d'édition atteint un onglet `edition` lorsqu'il est utilisé depuis le même ordinateur.
  - Avec `viewer.trusted_local_editing` sur une installation ouverte, un onglet qui passe la vérification « même machine » s'enregistre au niveau `edition` et repasse en `readonly` en un ping quand l'option est désactivée. Les onglets du réseau local ou transférés restent `readonly`. Un jeton utilisé depuis la machine locale atteint cet onglet quel que soit son niveau de création. Un jeton utilisé depuis le réseau local ne l'atteint jamais et reçoit `no_tab`, avec un message expliquant qu'une requête non locale ne peut pas piloter un onglet d'édition local.
  - Un onglet ne peut être remplacé que par un onglet de niveau égal ou supérieur : une session de consultation qui réutilise le `tab_id` d'un onglet d'édition est refusée avec 4409. Au-delà du plafond d'onglets par utilisateur, l'onglet de plus bas niveau part en premier.
  - `status` ne liste que les onglets que le jeton peut piloter, et indique `out_of_reach_tabs`, le nombre d'onglets ouverts qu'il ne peut pas piloter.
- **Plusieurs onglets.** Le dernier à avoir eu le focus est utilisé et le champ `tab` du résultat l'indique. Passez `tab_id` (listé par `status`) pour en choisir un autre.
- Un onglet refuse ce que son compte n'a pas le droit de faire (par exemple `/culling` pour un compte sans édition) et l'outil renvoie ce refus.
- Ce qu'un onglet renvoie n'est pas fiable : la profondeur, la longueur des chaînes et des listes sont bornées, et le tout est plafonné par `max_bytes`.
- Erreurs : `no_tab` (aucun onglet connecté ou ouvert, ou pont désactivé : ouvrez Facet dans un navigateur et connectez-vous), `tab_timeout` (pas de réponse sous `call_timeout_s`) et `tab_outdated` (l'onglet ouvert ne connaît pas l'outil ; rechargez la page après une mise à jour de Facet).
- Le pont accepte d'abord le WebSocket puis le refuse par un code de fermeture et non par un statut HTTP : 4404 quand le point d'accès ou le pont est désactivé (l'onglet reste alors déconnecté jusqu'au rechargement de la page), 4403 quand l'en-tête `Origin` est absent ou non autorisé, 4401 pour une session absente ou rejetée.
- **Proxy inverse.** Il doit transmettre la mise à niveau WebSocket pour `/api/mcp/bridge` ; voir [Déploiement](DEPLOYMENT.md). S'il réécrit l'en-tête `Host`, indiquez l'origine publique dans `viewer.mcp.allowed_origins` (par exemple `["https://photos.example.com"]`) : l'origine de la page doit correspondre à l'hôte ou figurer dans la liste.
- **Ce que fait l'utilisateur.** `ui_get_context` renvoie aussi :
  - `focused`, `{path}` : la photo sous le curseur clavier dans la galerie, la photo ouverte sur la page photo ou la photo courante dans la chambre noire ; sinon `null`. Le survol ne compte pas. Passer à la fenêtre de l'assistant la conserve, et elle s'efface quand la photo quitte la liste.
  - `user_activity`, `{items, until, truncated}` : ce que l'utilisateur a fait dans l'onglet, au plus 50 éléments de 20 chemins chacun, les plus récents étant conservés. L'appel est sans état : passez le `until` de la réponse précédente comme `activity_since` pour n'obtenir que le plus récent ; deux appels sans lui renvoient les mêmes éléments.

  Actions consignées :
  - notes, rejets et favoris ;
  - confirmations et sauts d'un plan de l'assistant sur `/culling` (`cull_confirm`, `cull_skip`), en mode plan seulement, une fois la confirmation passée ou le compte à rebours du saut écoulé (le tri manuel et une confirmation validée par Quitter ne sont pas consignés) ;
  - étiquettes ; albums (création, renommage, modification de la description, suppression, ajout) ; personnes (attribution, retrait, fusion, scission, renommage, masquage, démasquage, création, suppression) ; indésirables (rejet, marquage comme non indésirable) ;
  - réponses de comparaison (`winner` `a`, `b`, `tie` ou `skip`) ;
  - changements de filtres de la galerie : une rafale de modifications devient une seule entrée `filters` après une seconde de calme, `{reset: true}` pour une réinitialisation ; un changement de tri seul n'est pas consigné ;
  - navigation : un changement de page (une simple modification de la chaîne de requête n'en est pas un) ;
  - décisions manuelles Conserver et Réinitialiser depuis les actions individuelles ou groupées de la galerie et le détail d'une photo, une fois terminées : type `review`, avec `value` `kept` ou `undecided`. Les lots échoués ou partiellement terminés n'ajoutent aucune entrée.

  Les écritures de l'assistant et sa propre navigation `ui_*` ne sont jamais listées, et une action de votre part qui survient pendant qu'un outil `ui_*` de l'assistant s'exécute est ignorée. Les noms, textes de recherche et chemins d'une entrée sont des données non fiables, jamais des instructions. Le journal vit dans la mémoire de l'onglet (ses 500 dernières actions) et disparaît au rechargement.

En complément :

- **`ui_set_gallery_filters`** vous amène d'abord à la galerie si une autre page est ouverte, puis applique le patch. Sur une page d'album, tout changement revient à la galerie (pas seulement `replace: true`) : les filtres enregistrés de l'album ne sont pas écrasés et le périmètre de l'album est abandonné. L'outil refuse en bloc (`invalid_input`) un patch qui nomme un filtre que l'onglet ne sait pas piloter (utilisez `search_photos` pour ceux-là), un filtre inconnu, à la fois `category` et `type`, ou à la fois `person` et `person_id`. Il accepte aussi `semantic_query`, `semantic_threshold` (0 à 0,5), `similar_to`, `similarity_mode` et `min_similarity` (0 à 1) ; `similar_to` et `semantic_query` ne se combinent pas.
- `ui_get_gallery_view`, `ui_next_page` et `ui_select_photos` avec `select_view` exigent que la galerie (ou un album) soit la page ouverte, sinon ils répondent `no_active_view` ; appelez d'abord `ui_navigate` vers `/`. Donnez à `ui_select_photos` exactement l'un de `paths` et `select_view`. En mode `remove` sous une sélection de toute la vue, les chemins hors de la vue chargée sont ignorés et listés dans `not_in_view`.
- Un outil d'interface qui quitterait `/culling` alors que l'utilisateur a des décisions non confirmées répond `unsaved_decisions`. Une navigation que l'onglet refuse lui-même répond `navigation_refused`. `forbidden_level` n'est qu'un refus de permission.
- `ui_navigate` n'ouvre que les pages statiques de l'application. La page de connexion, les pages partagées, les URL externes et les chemins inconnus sont refusés (`invalid_input`), de même que les pages réservées à l'édition pour une session sans édition. `/timeline` accepte aussi `year` et `month` (1-12) ; `ui_get_context` renvoie alors `timeline`.
- **Recouvrements.** `ui_get_context.overlays` liste ce qui recouvre la page (`dialog`, `bottom_sheet`, `slideshow` ; vide quand rien ne la recouvre). Tant qu'elle n'est pas vide, tout outil d'interface qui modifie la vue répond `modal_open` et ne fait rien. `ui_get_context`, `ui_get_selection` et `ui_get_gallery_view` répondent toujours, et une recherche affichée avec `show` indique `shown_in_tab.reason` `modal_open` (la recherche elle-même réussit). Toute boîte de dialogue compte, y compris celles des raccourcis et de l'édition, sauf celle de connexion de l'assistant ; les menus, listes déroulantes, info-bulles et notifications ne comptent pas.
- **État de la page.** `ui_get_context.page` vaut `{id, ...état}` sur ces pages, et `null` sur toute autre :
  - `/persons` (`persons` : `search`, `sort`, `sort_direction`, `show_hidden`)
  - `/albums` (`albums` : `search`, `sort`, `type`)
  - `/stats` (`stats` : `tab`, `category`, `date_from`, `date_to`)
  - `/map` (`map` : `date_from`, `date_to`)
  - `/timeline` (`timeline` : `date_from`, `date_to`, `sort`)
  - `/scenes` (`scenes` : `album_id`, `total`)
  - `/culling` (`culling` : `mode` (`cull` ou `stacks`))
  - `/compare` (`compare` : `tab` (`snapshots`, `ab`, `suggestions`, `weights`, `context` ou `panorama`), `category`, `strategy`, `pair_a`, `pair_b`, `pair_loading`). `tab` vaut `null` tant qu'aucune catégorie n'est choisie ; la paire vaut `null` tant que l'onglet A/B n'est pas affiché.

  Les valeurs sont lues en direct et le texte libre est coupé à 200 caractères. Un onglet plus ancien omet `page` et `overlays`.
- La ligne d'état de la boîte **Connecter un assistant** indique si cet onglet est connecté ; `status` liste les onglets ouverts et leurs identifiants.
- Un onglet cesse de se reconnecter dès que sa session est rejetée (reconnectez-vous). Il attend votre retour sur lui lorsqu'un autre de vos onglets a pris la place.

## Mises à jour en direct

Quand un assistant modifie des photos avec un outil d'écriture, les onglets Facet que vous avez ouverts suivent sans rechargement.

- **Galerie.** Les cartes modifiées sont mises à jour sur place, la liste épinglée de l'assistant est conservée, et une photo supprimée de la bibliothèque (`delete_photos`) disparaît. Une photo que `cull_apply` a déplacée ou mise à la corbeille garde sa ligne dans la bibliothèque : elle reste donc dans une liste épinglée, tandis que les vues qui masquent les photos rejetées (le réglage par défaut) la masquent déjà. Une écriture qui ne peut pas nommer ses photos (voir plus bas) recharge la vue, en gardant les lignes actuelles à l'écran et votre sélection jusqu'à l'arrivée des nouvelles. Les vues de recherche sémantique et de photos similaires rafraîchissent les photos déjà affichées et n'en retirent jamais.
- **Page photo.** Elle recharge sa photo ; une photo supprimée de la bibliothèque vous ramène en arrière.
- **Chambre noire** (`/culling`). Elle met à jour rejet, favori et note sur place, affiche un repère Rejetée et conserve vos propres décisions. Face à un changement qu'elle ne peut pas délimiter, elle ne recharge que si rien n'est en jeu ; sinon elle affiche une bannière Recharger qui reste jusqu'à ce que vous rechargiez.
- **Un seul avis par rafale.** Les changements sont regroupés (anti-rebond de 400 ms, 2 s au plus) en un seul avis « L'assistant a modifié N photos ».
- **Une entrée par appel de l'assistant** dans le panneau d'activité, libellée avec le nom de l'outil dans votre langue (ou son nom brut s'il n'a pas de libellé), les photos de tout l'appel étant comptées ensemble. Au-delà de 200 photos, l'entrée n'en nomme aucune : la vue se recharge et il n'y a pas de bouton **Afficher les photos**. Après une application d'`auto_cull`, **Afficher les photos** épingle les photos qu'elle a rejetées (jusqu'à 200).
- **Quelles écritures.** Notes, favoris, rejets, étiquettes, légendes, appartenance aux albums, tris, suppressions, corrections de séquence et de catégorie, attributions de visages, effacement du rebut et confirmations de la chambre noire. Les lectures, essais à blanc, écritures refusées, créations d'album, exports de métadonnées et analyses ne rafraîchissent rien. Une écriture qui expire (`outcome_unknown`) rafraîchit quand même, car elle a pu aboutir ; une écriture encore en cours à ce moment apparaît au rafraîchissement ou au rechargement suivant.
- **Écritures sans portée.** Une écriture visant une vue `filters`, une qui inclut les images voisines d'un ensemble, une de plus de 200 photos, ou une qui ne nomme aucun chemin recharge la vue au lieu de rafraîchir des cartes nommées.
- **Le pont doit être activé.** Une écriture faite via `/mcp` atteint vos onglets par le pont d'onglet, donc `viewer.mcp.bridge` doit valoir `true`. Une écriture faite par la page elle-même (`POST /api/mcp/call`) utilise sa réponse (`changed_paths`) et met à jour même pont désactivé.
- **Même processus seulement.** Avec `viewer.py --workers N`, l'avis peut manquer un onglet (voir [Limites connues](#limites-connues)).
- **Après une mise à jour, rechargez vos onglets ouverts.** La liste des outils a changé : un onglet ouvert répond `tab_outdated` tant qu'il n'est pas rechargé.

## WebMCP dans la page (agents du navigateur)

Indépendamment du point d'accès `/mcp`, un onglet connecté propose aussi les mêmes outils `ui_*` aux agents qui vivent dans le navigateur lui-même, via l'API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Un assistant natif du navigateur voit donc exactement les outils listés plus haut, les exécute dans l'onglet que vous regardez et n'a besoin d'aucun jeton.

- **Contexte sécurisé uniquement.** Facet n'enregistre les outils qu'en HTTPS ou sur `localhost`. En HTTP simple, ils ne sont pas proposés ; la connexion par jeton continue de fonctionner.
- Ils sont enregistrés quand `viewer.mcp.enabled` vaut true et que vous êtes connecté, et retirés à la déconnexion.
- L'objet est `document.modelContext` (l'ancien alias `navigator.modelContext` n'est pas fourni). C'est un polyfill, installé seulement si le navigateur n'en a pas de natif, et il ne peut pas être désinstallé : il peut exister avant votre connexion sans aucun outil Facet, et reste après la déconnexion avec une liste d'outils vide.
- Les outils font les mêmes choses, bornées par le même niveau de compte, que dans le tableau ci-dessus. Un agent de navigateur lit la même liste `actions` via `ui_get_context`.
- **Outils de bibliothèque dans la page.** L'onglet propose aussi les outils propres au serveur (recherche, notes, étiquettes, albums, chambre noire, rapports) :
  - `GET /api/mcp/inpage_tools` les liste, avec le schéma de chaque outil, son `required_level` et le `level` actuel de la session.
  - `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`) en exécute un avec votre session connectée, par le même enveloppeur que `/mcp` : niveaux, aperçus, valeurs `confirm` et limites de débit se comportent donc à l'identique. Un outil en échec renvoie une enveloppe `ok: false` normale (HTTP 200). Un appel renvoie aussi `changed` (photos écrites).
- **Niveau.** Le plus bas entre celui de votre connexion et votre rôle actuel, relu à chaque appel : un compte rétrogradé perd aussitôt les écritures et un compte supprimé est refusé (401). Sous le seuil d'un outil, la réponse est `forbidden_level` (« This session's level is readonly; set_rating needs edition: unlock edition in Facet »). Sur une installation à mot de passe unique, une session qui écrit doit avoir déverrouillé l'édition.
- **Qui peut appeler.** Uniquement une personne connectée. Le jeton `/mcp` d'un agent est refusé sur ces routes (403), tout comme une `Origin` étrangère ; un cookie seul n'authentifie jamais. Chaque appel porte un en-tête `X-Facet-Agent-Session` (1 à 64 lettres, chiffres, `_` ou `-` ; absent ou mal formé, il répond 400). Il distingue les onglets : une valeur `confirm` émise pour un onglet est refusée à un autre. C'est la page qui le choisit : il sépare mais n'authentifie pas.
- **Ce qui est exclu.** Les outils d'image (`get_thumbnail`, `contact_sheet`) et `available_actions` (utilisez `ui_get_context`). L'argument `show` d'un outil est toujours désactivé, car l'onglet est l'appelant, et `tab_id` est refusé. `status` ne renvoie que les versions du serveur et du contrat d'interface. `target: "selection"` utilise le `selection_snapshot` envoyé par la page (ce que `ui_get_selection` a renvoyé). `create_album` avec `target: "view"` exige l'`album_filter_json` et le `filters_scopable` renvoyés par `ui_get_gallery_view` (`invalid_input` sans eux). Les actions destructrices suivent toujours `viewer.mcp.allow_destructive`.
- **Goût.** Comme toute écriture d'assistant, un appel d'outil fait depuis la page n'enregistre jamais de comparaisons et n'arme jamais le réentraînement.
- **Interrupteur.** `viewer.mcp.inpage_tools` (`true` par défaut) désactive les deux routes (404) et met `features.mcp_inpage` à faux dans `/api/auth/status`. `viewer.mcp.enabled: false` les désactive aussi.

## Modifier la bibliothèque

Les outils d'écriture figurent dans la même liste `/mcp` que les outils de lecture. Chacun passe par les routes `/api` de la visionneuse, de sorte que les protections de la route s'appliquent toujours, et chacun est décompté du budget `write_rate_per_min`. Le niveau est le plus bas niveau effectif autorisé à appeler l'outil (voir [Niveaux d'autorisation](#niveaux-dautorisation)).

| Outil | Niveau | Ce qu'il fait | Plafonds |
|-------|--------|---------------|----------|
| `set_rating` | `user` | Définit la note en étoiles (0-5) de photos | 50 chemins |
| `set_favorite` | `user` | Marque ou démarque des photos comme favorites (marquer retire le rejet) | 50 chemins |
| `set_rejected` | `user` | Rejette ou annule le rejet de photos (rejeter retire la note et le favori) | 50 chemins |
| `batch_set_rating` | `edition` | Définit la note de nombreuses photos | 1000 chemins, ou `filters` |
| `batch_set_favorite` | `edition` | Marque de nombreuses photos comme favorites | 1000 chemins, ou `filters` |
| `batch_set_rejected` | `edition` | Rejette de nombreuses photos | 1000 chemins, ou `filters` |
| `add_tags` | `edition` | Ajoute des étiquettes manuelles (séparées des étiquettes IA) | 10 étiquettes ; 1000 chemins, ou `filters` |
| `remove_tags` | `edition` | Retire des étiquettes manuelles | 10 étiquettes ; 1000 chemins, ou `filters` |
| `create_photo_stack` | `edition` | Créer une pile explicite ; renvoie une entrée Annuler | 2–1000 chemins |
| `update_photo_stack` | `edition` | Remplacer membres/ordre et couverture facultative ; refuse une révision périmée | 1000 chemins |
| `unstack_photos` | `edition` | Dissoudre une pile sans changer les originaux |  |
| `undo_photo_stack` | `edition` | Annuler seulement une entrée de pile disponible ; refuse les changements ultérieurs |  |
| `create_album` | `edition` | Crée un album (non idempotent : deux appels, deux albums) : vide, ou depuis `filters` / `target: "view"` comme album intelligent qui suit ces filtres, ou depuis `paths` / `target: "selection"` comme album fixe rempli dans le même appel (`added`, `skipped`). Un album intelligent applique les bascules de masquage du visualiseur et affiche 0 photo dans `list_albums`. Des `filters` sans aucun filtre effectif (`{}`, ou seulement des bascules d'affichage désactivées) sont refusés en `invalid_input` : omettez `filters` pour un album vide | |
| `album_add_photos` | `edition` | Ajoute des photos à un album (celles déjà présentes sont ignorées) | 1000 chemins |
| `album_remove_photos` | `edition` | Retire des photos d'un album ; les photos ne sont pas touchées | 1000 chemins |
| `assign_faces` | `edition` | Déplace des visages vers une personne ; ceux qu'une autre personne possède sont laissés tels quels sauf `allow_reassign`, et le résultat liste ce qui a été ignoré | 50 ids de visage |
| `set_caption` | `edition` | Définit la légende d'une photo (sémantique d'ensemble ; une légende inchangée revient en `already`) | 1 photo, 2000 caractères |
| `export_metadata` | `edition` | Écrit des sidecars XMP à côté des fichiers | 100 chemins, ou `filters`, ou `target` |
| `junk_list` | `readonly` | Liste les candidates du tri des ratés, éventuellement d'un seul `kind`; `show: true` ouvre `/junk` sur ce `kind` | 100 par page |
| `junk_reject` | `edition` | Rejette les candidates du tri des ratés (comme `batch_set_rejected`) | 1000 chemins, ou `target: "selection"` (page galerie uniquement) |
| `junk_clear` | `edition` | Conserve des candidates : les marque comme évaluées et saines pour qu'elles quittent la file | 50 chemins |
| `cull_apply` | `edition` | Copie les photos à conserver, ou déplace ou met à la corbeille les rejetées ([aperçu puis confirmation](#actions-destructives-aperçu-puis-confirmation)) | 10000 chemins, ou `filters` |
| `delete_photos` | `edition` | Met les fichiers à la corbeille et supprime leurs lignes de la bibliothèque ([aperçu puis confirmation](#actions-destructives-aperçu-puis-confirmation)) | 1000 chemins |

### Piles manuelles locales

- `get_photo_stack(path)` lit la pile locale de l'appelant, ou null. Avec une visibilité partielle, il ne renvoie que les membres autorisés, et la pile est en lecture seule.
- `create_photo_stack(paths, cover_path)` exige 2–1000 photos explicites non empilées.
- `update_photo_stack(stack_id, paths, expected_revision, cover_path?)` remplace membres et ordre ; 0 ou 1 membre dissout le groupe.
- `unstack_photos(stack_id, expected_revision)` la dissout.
- Ces trois outils exigent `edition`, plus l'UUID et la révision courante pour une pile existante. Ne répétez jamais aveuglément une création.
- Les changements réussis renvoient `undo.entry_id`. `undo_photo_stack(entry_id)` (`edition` uniquement) vérifie que l'entrée est une entrée de pile, et refuse après des modifications ultérieures ou une perte de visibilité.
- Les chemins sont limités à 4096 caractères. Aucun fichier, décision de tri ou état Immich distant n'est changé ; les identifiants globaux restent réservés à la CLI.
- `stack_truncated: true` après une modification réussie volumineuse signifie que la pile est renvoyée seulement comme résumé UUID/revision/member_count, et non comme liste complète de membres modifiable. `undo.entry_id` reste disponible.

`search_photos` et le contexte de la galerie distinguent `total` (éléments affichés) de `photo_total` (originaux correspondants). Utilisez `photo_total` pour l'`expected_count` d'une écriture filtrée. La sélection de toute la vue et `target:view` incluent les membres repliés : annoncez donc le nombre réel de photos et la portée de toute la vue avant d'appliquer. Une vignette réduite sélectionne seulement sa photo affichée. `user_activity` inclut `stack` create/update/unstack/undo. `stack_id`/`collapse_stacks`, réservés au serveur, ne sont pas des filtres d'onglet.

- **Les outils `user` exigent un jeton d'édition sur une installation à mot de passe unique**, qui n'a pas de niveau intermédiaire (voir [Niveaux d'autorisation](#niveaux-dautorisation)).
- **Sémantique d'affectation.** Les outils par photo n'écrivent qu'une différence avec l'état actuel, donc répéter un appel est sans danger ; chaque chemin indique `changed` ou `already`. Ils traitent un chemin à la fois et s'arrêtent au premier `library_busy`, `outcome_unknown` ou `forbidden_level`, en rapportant `affected`, les `results` par chemin et `not_attempted`. Les outils par lot appliquent le même état.
- **Choisir les photos.** Les outils par lot, d'étiquettes et `cull_apply` prennent SOIT `paths` SOIT `filters` (l'objet de filtres de `search_photos`), plus une liste `exclude` facultative.
  - Une cible `filters` exige `expected_count` : le nombre de correspondances des filtres avant `exclude` (le `photo_total` de `search_photos`). Facet recompte d'abord et n'écrit rien si les nombres diffèrent (`invalid_input`, avec `actual_count`).
  - Les masquages par défaut de la visionneuse (y compris les photos rejetées) s'appliquent à `filters` exactement comme dans `search_photos`. Pour `move_rejects` et `trash_rejects`, passez donc `show_rejected` (ou `hide_rejected: false`) à `search_photos` ET à `cull_apply`. `copy_keeps` n'a besoin de rien de plus.
- **À qui appartient l'état.** Les notes, favoris et rejets sont ceux du propriétaire du jeton.
- **Fichiers ignorés.** Quand `cull_apply` ou `delete_photos` renvoie une liste `skipped` non vide, le résultat contient aussi un `skipped_reason` : ces chemins n'ont aucun fichier lisible sur le disque (manquant, déplacé ou hors des répertoires analysés) et rien n'a été fait pour eux.
- **Les photos sélectionnées par l'utilisateur.** Là où un outil prend `paths`, `target: "selection"` utilise la sélection de l'onglet ouvert (`tab_id` choisit l'onglet).
  - Une sélection modifiée entre l'aperçu et la confirmation répond `invalid_input` avec `selection_changed` ; une sélection trop grande pour la réponse de l'onglet répond `too_large`. `delete_photos` relit la sélection à la confirmation.
  - `get_photo`, `get_thumbnail` (exactement une photo sélectionnée) et `contact_sheet` (16 au plus) prennent aussi `target: "selection"`, depuis n'importe quelle page.
  - `junk_reject` ne le prend que sur la page galerie (sinon `invalid_input`).
- **Légendes et exports.** `set_caption` ne stocke que le texte. La légende n'est pas ré-encodée : la recherche sémantique de légendes trouve l'ancien texte jusqu'à un nouveau ré-encodage. L'export incrémental vers la base de la visionneuse conserve une légende existante quand celle de la source est vide, si bien qu'une légende effacée peut revenir avec un export ou un scan ultérieur. `export_metadata` attend jusqu'à 180 secondes, rapporte `written`, `skipped` et `errors` (le premier message d'erreur dans `first_error`), et refuse d'écrire avec exiftool 13.23 à 13.27.
- **Visages.** `assign_faces` ignore, et liste, les visages manquants, déjà sur cette personne, possédés par une autre personne (sauf `allow_reassign`), d'un autre modèle d'embedding ou d'une personne masquée. `assigned_count` est ce qui a réellement bougé.

### Actions destructives : aperçu puis confirmation

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) et `delete_photos` portent l'indicateur `destructiveHint` et s'exécutent en simulation sauf appel avec `dry_run: false`.

1. La simulation ne modifie rien et liste les fichiers qu'elle copierait, déplacerait ou mettrait à la corbeille (les longues listes sont tronquées à `max_rows`, avec un `<key>_count`). Pour `move_rejects`, `trash_rejects` et `delete_photos`, elle renvoie aussi une valeur `confirm`, à usage unique et valable `confirm_expires_in_s` (5 minutes).
2. L'appel réel (`dry_run: false`) doit transmettre ce `confirm`. Facet recalcule les fichiers et les options ; si quelque chose a changé, l'appel répond `confirmation_required` : refaites une simulation.
3. `copy_keeps` n'a pas besoin de `confirm`, puisqu'il n'écrit que des copies. Il commence quand même par une simulation par défaut.

La valeur `confirm` est liée au jeton, à l'action et à l'ensemble exact de fichiers plus les options. Elle vit en mémoire dans un seul processus : un redémarrage supprime toutes les valeurs en attente.

**Pratique recommandée :** montrez toujours à l'utilisateur le résumé de la simulation (nombres et liste de fichiers) et obtenez son accord explicite avant l'appel `dry_run: false`. Ne confirmez jamais de votre propre initiative.

- `move_rejects` et `trash_rejects` n'agissent que sur les photos que le propriétaire a rejetées ; les autres sont signalées comme `excluded_by_state`. Les fichiers RAW et `.xmp` compagnons (`include_companions`) et les autres images d'un bracketing ou d'un panorama (`include_sequence_siblings`) ne sont pas touchés sauf si vous l'activez.
- **Prérequis.** `trash_rejects` et `delete_photos` exigent `viewer.cull.allow_trash` à `true` (par défaut `false`). Le `target_dir` de `copy_keeps` et `move_rejects` doit se trouver dans un emplacement d'export autorisé : `viewer.export.allowed_target_dirs` plus vos répertoires d'analyse (voir [Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri)).

> **Avertissement :** `delete_photos` envoie les fichiers à la corbeille du système et **supprime leurs lignes de la bibliothèque**. Les scores, étiquettes et notes ne sont pas récupérables, même si les fichiers le sont.

## Corrections et données de référence

- **Corrections** (`edition`). `override_sequence` (`kind` : `panorama`, `bracket`, `hdr_panorama` ou `suppress` ; au moins 2 chemins sauf pour `suppress`) et `clear_sequence_override` enregistrent une correction appliquée à la prochaine passe de détection (le résultat indique `pending`). `override_category` et `clear_category_override` définissent ou suppriment une catégorie persistante qui survit aux nouveaux scans et conserve le contexte de notation.
- **Comparer des images** (`readonly`). `group_compare` compare les images d'un groupe de tri (jusqu'à 12 chemins) `by: "faces"` (par image : nombre de visages, clignements, yeux ouverts le plus faible, meilleur sourire, `best_path_by_eyes`) ou `by: "subjects"` (netteté et importance du sujet, `sharpest_path`). C'est un conseil, pas une décision.
- **Rapport de tri.** `cull_report` résume un périmètre en un appel : total, conservées, rejetées, favorites, notées, non examinées, ce que les bascules de masquage cacheraient, indésirables, faibles scores, meilleures images et, avec un jeton edition, les premiers groupes de la chambre noire. Les raisons se recoupent. Son `basis` indique les filtres que respecte chaque décompte (les décomptes ignorent les bascules de masquage).
- **Goût.** `comparison_status` (`edition`) indique combien de comparaisons par paires vous avez faites et dans quelle mesure elles couvrent la bibliothèque. Aucun outil ne soumet, ne modifie ni ne supprime de comparaison : la réponse à une paire est votre propre clic. Les écritures d'un assistant (notes, rejets, confirmations de la chambre noire, `auto_cull`) n'enregistrent jamais de comparaison et n'arment jamais le réentraînement automatique ; la même action faite par vous dans la galerie le fait toujours. Les notes, favoris et rejets qu'un assistant a écrits sont aussi exclus des paires d'entraînement du classeur personnel, jusqu'à ce que vous notiez vous-même cette photo.
- **Scans.** `start_scan` et `scan_status` (`edition`) lancent et suivent un scan des répertoires configurés. Ils ne sont listés que si `viewer.features.show_scan_button` est actif et que l'installation est verrouillée (une clé superadmin en mode multi-utilisateur), ou pour un jeton local d'édition complète sous `viewer.trusted_local_editing`, qui n'a pas besoin de `show_scan_button`. Un scan est additif et refusé tant qu'une autre tâche tourne (`conflict`). La synchronisation avec Immich reste en ligne de commande. Sur une installation ouverte avec `viewer.edition_password`, un jeton local d'édition complète créé dans une session d'édition les obtient aussi, mais seulement avec `show_scan_button` actif.
- **Ressources.** Le serveur liste aussi cinq ressources `facet://` en lecture seule : `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (chaque filtre de recherche avec son domaine de valeurs, plus les plages de métriques) et `facet://scoring-contexts`. Chacune est lue comme le propriétaire de la clé voit la bibliothèque, limitée à 200 lignes et 32 Kio (`truncated` l'indique). Une sixième, `facet://scoring-weights` (les poids non nuls de chaque catégorie), n'est proposée qu'aux clés `edition`.
- **Choisir ce qui est listé.** `viewer.mcp.tool_profile` vaut `full` (par défaut) ou `core`. `core` ne liste qu'un ensemble de 11 outils pour les petits modèles (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`) ; cela ne change que la liste, jamais ce qu'une clé peut appeler. `viewer.mcp.allow_destructive` (`false` par défaut) conditionne `delete_photos` (non listé si désactivé), les actions `move_rejects` et `trash_rejects` de `cull_apply`, et `assign_faces` avec `allow_reassign` ; un appel refusé répond `feature_disabled`. Les outils au-dessus du niveau d'un jeton ne sont pas listés non plus.
- **Deux codes d'erreur de plus.** `feature_disabled` : une clé de configuration désactive la route, et le message la nomme. `conflict` : la bibliothèque est occupée par une tâche incompatible avec celle-ci (par exemple un scan déjà en cours).

## Scores et pondérations

Les assistants peuvent lire les pondérations de score et simuler un changement. Quatre outils écrivent : `apply_weights` et `restore_weight_snapshot` modifient la configuration, `recompute_scores` réécrit les scores et `override_categories` fixe des photos. Chacun exige le niveau `edition` et un `confirm` en deux temps issu d'un essai à blanc ou d'un aperçu. Les lectures ne changent rien.

- **Expliquer un score** (`readonly`). `explain_score` (`path`, ou `target: "selection"` pour exactement une photo sélectionnée ; `top_n` de 1 à 12, 5 par défaut) explique le score d'une photo : sa catégorie et pourquoi aucune catégorie plus prioritaire ne l'a retenue, l'agrégat enregistré, les principales métriques sous la forme `{metric_key, value, weight_percent, contribution}`, le reste en nombre et en somme, les points forts, les points faibles et les pénalités.
  - L'analyse est à base de règles et en lecture seule ; elle n'exécute jamais le VLM.
  - `weight_percent` est le poids effectif utilisé par le calcul. Il peut différer du `*_percent` configuré : `quality` est replié dans `aesthetic`, et les métriques que cette installation n'exécute pas sont renormalisées.
  - Elle exige `viewer.features.show_critique` (activé par défaut). Quand il est désactivé, l'outil n'est pas listé et `status` le nomme sous `hidden_tools.disabled`.
- **Lire les pondérations** (`edition`). `category_weights` renvoie les poids non nuls, les modificateurs, les filtres et la priorité d'une catégorie, ou les poids non nuls et le bonus de chaque catégorie. La ressource `facet://scoring-weights` porte la même liste. Pour une catégorie, il renvoie aussi `configured_keys` : les clés `*_percent` réellement présentes dans la configuration de la catégorie (zéros explicites inclus).
- **Simuler un changement** (`edition`). `preview_weights(category, weights | deltas, sample)` recalcule jusqu'à `sample` photos de la catégorie (30 par défaut, 100 au plus) avec les poids actuels puis proposés, normalisés comme le fait le calcul. Donnez `weights` (une table partielle fusionnée sur les valeurs actuelles) ou `deltas` (points de pourcentage signés).
  - Il indique d'abord les changements de rang, puis le décalage moyen, des `warnings` et un `preview_digest` à usage unique (valable 5 minutes, conservé en mémoire par un seul processus).
  - C'est une approximation (`basis: "approximate"`) : pas d'instantané de percentiles, pas de pénalités, scores plafonnés à 10. Il n'utilise que les métriques stockées et n'enregistre rien.
  - Seule la règle du serveur est appliquée (chaque poids de 0 à 100), plus un refus quand toutes les pondérations valent 0 (`all_weights_zero`). Une somme hors de 95 à 105 (que le chargeur de configuration rééchelonne) et une clé inconnue (enregistrée telle quelle, écartée par un chargement validant) reviennent en `warnings`, pas en refus.
  - `bonus` et les modificateurs ne sont pas modifiables par l'assistant.
  - Une catégorie de plus de 100 photos n'est échantillonnée que parmi ses 100 meilleures et ses 100 moins bonnes par agrégat (`sample_scope`).
  - Le digest n'est pas un consentement : montrez d'abord à l'utilisateur la proposition, le décalage et `basis_note`.
- **Appliquer un changement** (`edition`). `apply_weights(category, weights | deltas, preview_digest)` écrit un changement simulé. Répétez les MÊMES `weights` ou `deltas` donnés à `preview_weights` et passez son `preview_digest`. Sans le digest de cette proposition exacte sur les poids actuels, l'appel répond `confirmation_required` et n'écrit rien. Le digest est à usage unique, lié au jeton qui a simulé, et périmé dès que les poids changent.
  - L'écriture passe par la même route que l'interface web : les anciens poids sont d'abord sauvegardés (`auto:edit`) et le résultat nomme ce `snapshot`. Le résultat est relu (`verified`).
  - Aucune photo n'est recalculée : la réponse indique `scores_stale: true` et `next: "recompute_scores"`. Les scores, rangs et la galerie ne changent qu'après ce travail.
  - Limite connue : une page /compare déjà ouverte garde les anciens poids et les renverrait à sa prochaine modification ; la réponse porte donc `reload_compare: true` et l'assistant demande à l'utilisateur de la recharger.
- **Instantanés** (`edition`). `list_weight_snapshots(category, limit, offset)` liste les instantanés enregistrés, du plus récent au plus ancien, avec leurs poids non nuls et un indicateur `restorable`. `restore_weight_snapshot(snapshot_id)` est un essai à blanc par défaut : il liste le changement et renvoie un `confirm` à usage unique. L'exécution réelle (`dry_run: false` plus ce `confirm`) répond `confirmation_required` si les poids ont bougé entre-temps. Avant d'écraser quoi que ce soit, elle sauvegarde les poids actuels sous `auto:pre_restore` (`undo_snapshot_id`) : une restauration peut elle-même être annulée. Un instantané enregistré par l'interface web dans un autre format (noms de métriques nus au lieu de clés `*_percent`) répond `unsupported_snapshot` aux deux exécutions : restaurez-le depuis /compare.
- **Recalculer** (`edition`). Un changement de poids ne recalcule rien tant que `recompute_scores(category | all: true)` n'a pas été lancé. Il démarre aussitôt le travail en arrière-plan (demandez d'abord à l'utilisateur) et renvoie `started_at`. `recompute_status(started_at)` indique ensuite `running`, `succeeded`, `failed`, `busy` (un autre processus détient le verrou de la bibliothèque) ou `idle` ; `matches_started_job` dit si l'état décrit bien le travail lancé.
  - Un seul travail à la fois (`conflict`).
  - Le recalcul d'une catégorie ne réécrit que cette catégorie et ne rafraîchit pas les groupes de rafales ni de séquences (`all` le fait). Chaque exécution enregistre l'instantané des percentiles lu par la prochaine normalisation de chaque catégorie.
  - L'état est tenu dans un seul processus : avec plusieurs workers, une interrogation peut tomber sur un processus qui ignore le travail.
- **Ce que favorisent les comparaisons de l'utilisateur** (`edition`). `learned_weights(category, with_confidence)` lance l'optimiseur sur les comparaisons A/B de l'utilisateur et ne renvoie que les `changes` non nuls et une `proposal` à confier à `preview_weights` ; rien n'est enregistré. Plutôt que d'inventer une suggestion, il répond `available: false` avec une `reason` (`not_enough_comparisons`, `unavailable_if_external` quand le moteur d'apprentissage est externe, `optimizer_unavailable`). Quand l'optimiseur ne trouve aucune amélioration, il indique à l'assistant de ne rien proposer.
- **Corriger les catégories** (`edition`). `misassigned_categories(category, limit, scan)` liste des photos d'une catégorie qui appartiennent peut-être ailleurs, parmi les `scan` mieux notées. C'est une heuristique (`confidence_basis: "heuristic"`), pas une preuve ; elle n'écrit rien, ignore les photos à catégorie manuelle et disparaît avec `show_critique`.
  - `stale` : la configuration actuelle range la photo dans une autre catégorie. Remède : `recompute_scores`, pas une surcharge.
  - `near_miss` : elle a raté de moins de 10 % la première borne numérique en échec d'une catégorie plus prioritaire.
- **Fixer des catégories** (`edition`). `override_categories(category, paths, dry_run, confirm, expected_count)` fixe jusqu'à 50 photos.
  - L'essai à blanc liste ce qui changerait (`would_change`, `already`, `missing`) et renvoie un `confirm` à usage unique.
  - L'exécution réelle l'exige avec un `expected_count` égal à `would_pin`. Les photos déjà dans la catégorie sont fixées aussi, pour que le choix survive à un recalcul ultérieur. Elle s'arrête au premier échec et indique `affected`, `remaining` et `failed_path`.
  - Chaque fixation est durable et recalcule l'agrégat de la photo ; `clear_category_override` en annule une.
- `ui_show_comparison` accepte un `tab` (`ab`, `snapshots`, `suggestions`, `weights`) pour que l'assistant ouvre la page où l'utilisateur relit un changement.

## Prompts

Le serveur propose aussi cinq prompts prêts à l'emploi, listés par `prompts/list` et filtrés selon le niveau du jeton. Un prompt ne nomme que des outils que le jeton peut appeler, et un outil destructif seulement derrière son essai à blanc et sa confirmation. Chaque appel compte dans la limite de lecture et est journalisé par nom, jamais avec ses arguments.

| Prompt | Arguments | Ce qu'il demande à l'assistant |
|--------|-----------|--------------------------------|
| `find_photo` | `description` | Trouver une photo à partir d'une description et l'afficher |
| `cull_shoot` | `scope_hint` | Passer en revue une séance, proposer quoi rejeter et, une fois que vous avez décidé, enregistrer vos décisions avec `confirm_culling_groups` ; déplacer ou mettre à la corbeille n'arrive qu'après un essai à blanc et votre confirmation |
| `build_album` | `theme`, `album_name` | Réunir les photos correspondantes dans un nouvel album |
| `tag_people` | `person` | Trouver les visages qui ressemblent à une personne et assigner ceux que vous confirmez |
| `teach_taste` | `category` | Ouvrir la page de comparaison par paires dans votre onglet et suivre le nombre de comparaisons faites ; la réponse à chaque paire reste toujours votre propre clic |

## Chambre noire (groupes de tri)

Les outils de la chambre noire reprennent la page `/culling`. Tous exigent le niveau `edition`, y compris ceux qui ne font que lister.

| Outil | Ce qu'il fait |
|-------|---------------|
| `list_culling_groups` | Liste les groupes (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) avec leurs photos et scores, triables et limités par album ou plage de dates |
| `culling_profiles` | Les préréglages de tri adaptés au genre et celui par défaut |
| `suggest_culling_profile` | Nomme le préréglage adapté à un album ou à une plage de prise de vue |
| `keeper_hints` | Indications par photo « un meilleur cliché existe dans cette rafale » pour jusqu'à 100 chemins (vides si aucune tête de classement n'est entraînée) |
| `auto_cull` | Tri automatique d'un périmètre sous un budget de photos à conserver : aperçu du plan page par page, puis application avec la valeur `confirm` |
| `confirm_culling_groups` | Confirme jusqu'à 20 groupes : conserve leurs `keep_paths`, rejette le reste de leurs `paths` |

- **Un groupe est identifié par le couple `(type, group_id)`**, jamais par `group_id` seul : les identifiants des groupes similaires sont décalés lors de la fusion avec les rafales.
- **Le `group_by: "all"` par défaut ne renvoie que les rafales et les groupes similaires.** Demandez explicitement `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Une page est réduite pour tenir dans `max_bytes` en raccourcissant la liste `photos` de chaque groupe, jamais en retirant des groupes.** `photo_count` reste la vraie taille, `photos_truncated` signale un groupe dont la liste a été coupée et `has_more` indique si une autre page suit.
- **Les bracketings, panoramas et panoramas HDR sont conservés entiers.** Dans `confirm_culling_groups`, `keep_paths` doit égaler `paths` pour ces types (sinon `invalid_input`), et `auto_cull` ne les scinde jamais.
- **Un `keep_paths` vide rejette toutes les images du groupe.** Le premier appel répond alors `confirmation_required` avec une valeur `confirm` : montrez-le à l'utilisateur, puis répétez l'appel avec cette valeur. Si un lot s'arrête sur `forbidden_level`, `library_busy` ou `rate_limited`, les groupes déjà traités sont rapportés.
- **`auto_cull` fait un aperçu par défaut.** Il renvoie la répartition conservation/rejet par groupe, plus une valeur `confirm` s'il reste quelque chose à rejeter.
  - Chaque appel planifie tout le périmètre et le renvoie par pages de groupes entiers. La route pagine à 200 photos, un seul groupe plus grand obtient sa propre page, et l'outil peut renvoyer moins de groupes pour tenir dans la taille du résultat.
  - Répétez l'appel avec `cursor` égal au `next_cursor` précédent et `plan_digest` égal au `plan_digest` de la page du curseur 0 (obligatoire si `cursor` > 0), jusqu'à ce que `next_cursor` vaille `null`. Si le plan a changé depuis la première page, l'appel répond `confirmation_required` : recommencez au curseur 0.
  - Chaque ligne porte son `number` dans tout le plan ; `kept` et `rejected` couvrent le plan complet.
  - Triez une plage de dates entière en UN appel, jamais mois par mois.
- **Un seul `confirm` couvre tout le plan** (valable 300 s, à usage unique, émis sur la page du curseur 0 uniquement). L'application recalcule le plan et répond `confirmation_required` s'il a changé depuis l'aperçu. Elle ne renvoie que des compteurs (`groups_processed`, `kept`, `rejected`, `highlights_added`). Les rejets faits par un assistant n'alimentent jamais le classeur personnel, contrairement au même tri fait par vous dans la galerie.
- **Remplacements.** `keep_paths` et `remove_paths` (jusqu'à 1000 chacun) remplacent des images isolées du plan. Passez les mêmes remplacements à l'essai à blanc qui émet le `confirm` et à l'application.
  - Les chemins absents du plan sont ignorés et signalés dans `ignored_overrides` (les 20 premiers, avec `ignored_overrides_count`).
  - Refusés avec `invalid_input`, qui nomme les chemins ou les groupes : retirer une image que le plan GARDE dans un bracketing, un panorama ou un panorama HDR ; laisser un groupe sans photo gardée ; citer un chemin dans les deux listes.
  - Retirer une image que le plan rejette déjà ne fait rien.
  - La règle des séries ne s'applique qu'aux groupes entièrement composés d'un seul type de série. Un groupe mêlant images ordinaires et images de série n'est pas gardé en entier : ses images peuvent donc être remplacées comme celles de n'importe quelle rafale.
- **L'application ne relit jamais les inversions de l'utilisateur dans l'onglet.** Pour les respecter, lisez `ui_get_context.culling.changed` et passez les `keep_paths` / `reject_paths` de ces groupes comme `keep_paths` / `remove_paths` au prochain essai à blanc et à son application (les mêmes listes aux deux). Un groupe confirmé dans l'onglet quitte le plan : le condensé du plan change, donc un `confirm` en attente répond `confirmation_required`, et le nouvel aperçu ne contient plus ce groupe. Ne le redécidez jamais.
- **Si l'utilisateur change quelque chose entre l'aperçu et l'application.** L'application est comparée à l'aperçu.
  - Une photo dont l'utilisateur a modifié la note, le favori ou l'état de rejet depuis l'aperçu est écartée et signalée dans `skipped_user_changed` (les 50 premiers chemins, avec `skipped_user_changed_count`). Un groupe resté sans photo gardée est ignoré en entier et compté dans `skipped_user_changed_groups`.
  - Cette exclusion photo par photo ne s'applique que si ni `keep_paths` ni `remove_paths` n'est donné. Avec des listes explicites, l'application rejoue l'essai à blanc et refuse tout changement du plan, y compris un rejet manuel.
  - Une note, un favori ou un rejet écrit par quiconque entre l'aperçu et l'application, écritures de l'assistant comprises, compte comme un changement. Un changement du plan qu'aucune de ces photos n'explique reste refusé avec `confirmation_required`.
  - Quand le serveur ne détient plus l'aperçu (plus de 15 minutes, évincé, ou détenu par un autre processus), ou que le plan compte plus de 12000 photos sur l'ensemble des pages, la réponse indique `state_guard: "unavailable"` et le refus tout ou rien s'applique.
  - La garde ne couvre que les demandes de l'assistant ; la ligne de commande `--auto-cull` est inchangée.
- **`scope_dependent_kinds`** nomme les types de groupes dont la composition dépend de la plage de dates ou du lot de candidats (`similar`, `scene`, plus `bracket` si `trim_brackets` est actif), avec une note invitant à trier toute la plage en un appel. Les rafales et panoramas ne changent pas avec la plage, ni les bracketings tant que `trim_brackets` est inactif.
- **`show`** (par défaut `true`, avec `tab_id`). Lors d'un essai à blanc, le plan s'ouvre sur la page `/culling` de l'utilisateur via `ui_show_culling_plan` (voir Mode plan sur `/culling` plus haut).
  - Le résultat porte `shown_in_tab` : `{"applied": true, ...}`, ou `applied: false` avec les raisons d'un affichage de recherche raté, plus `unsaved_decisions` (l'utilisateur détient sur la page des décisions non confirmées), `stack_mode_active` (la page est en mode piles suggérées), `plan_changed` (la bibliothèque a bougé depuis l'aperçu), `too_large` (les remplacements sont trop volumineux pour être envoyés à l'onglet) et `plan_load_failed` (toute autre raison d'échec du chargement).
  - Seule la première page (`cursor` 0) charge le plan ; une page avec `cursor` > 0 ne fait que déplacer le focus de l'onglet sur le premier groupe de cette page.
  - Un affichage raté ne fait jamais échouer l'appel. Une application n'affiche jamais.
  - La mise à jour en direct d'une application (et, dans la page, le `show_paths` de la réponse `/api/mcp/call`) porte les photos qu'elle a rejetées, jusqu'à 200, pour le bouton **Afficher les photos** de l'entrée d'activité ; le résultat de l'outil reste limité aux compteurs. Une application qui n'a rien rejeté ne propose pas **Afficher les photos**, et un essai à blanc n'émet aucune mise à jour en direct.
- **Réglages repris de l'onglet.** Sans `strictness` ni `profile`, `auto_cull` planifie avec les réglages que la page `/culling` de l'onglet ouvert utiliserait au départ.
  - Rigueur : la valeur mémorisée du curseur ; s'il n'a jamais été déplacé, la rigueur propre au profil mémorisé, ou 100 sans profil.
  - Profil : le profil de tri mémorisé dans ce navigateur, s'il y en a un. Il fournit ses autres réglages (comme le nombre minimal de photos gardées par groupe) ; la rigueur du curseur l'emporte.
  - Afficher un plan déplace le curseur sur la rigueur du plan ; appliquer un profil suggéré mémorise sa rigueur.
  - Sans onglet joignable, elle utilise `auto_cull.default_strictness` du serveur.
  - Le résultat indique ce qu'il a utilisé dans `knobs_from_tab` (`{profile}`, `{strictness}` ou les deux) ; `ui_get_context.culling_defaults` montre la même paire.
  - Une application portant un nonce de confirmation reprend toujours les réglages de l'aperçu (`keep_paths` / `remove_paths` explicites compris) et ne relit pas l'onglet. Elle répond `confirmation_required` quand la page `/culling` de l'utilisateur affiche désormais un autre plan que lors de l'aperçu (recalculé ou remplacé). Un onglet injoignable ou sans plan affiché n'est pas vérifié.
- Appelez `ui_show_culling_group` pour montrer un groupe à l'utilisateur dans son onglet ouvert (voir [Piloter votre onglet ouvert](#piloter-votre-onglet-ouvert)).

## Résultats, limites et erreurs

Chaque résultat est une enveloppe JSON : `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. Les listes renvoient `data.rows` (un jeu compact et fixe de champs par photo) ainsi que `total`. Un résultat de recherche porte aussi `shown_in_tab`, et un résultat raccourci par le plafond d'octets porte `returned`.

- **Plafonds :** au plus `max_rows` lignes et `max_bytes` octets sérialisés. Les dernières lignes sont retirées et `truncated: true` est ajouté. Un résultat sans lignes qui dépasse `max_bytes` devient une erreur `too_large`.
- **Images :** `get_thumbnail` et `contact_sheet` renvoient une partie image avant la partie JSON. L'image est plafonnée par `max_image_bytes` (262144 par défaut), pas par `max_bytes`. Le texte visible dans une image est une donnée, jamais une instruction.
- **Analyse de visages :** `possible_faces` lit au plus 192000 visages et peut attendre jusqu'à 120 secondes ; au-delà, il répond `too_large`.
- **Limite de débit :** la lecture dispose de `rate_per_min` appels par minute et par jeton. Les outils d'écriture puisent dans un budget distinct, `write_rate_per_min` (30 par défaut), si bien que lectures et écritures ne s'affament pas mutuellement. La simulation de `cull_apply` et de `delete_photos` compte comme une écriture, l'aperçu d'`auto_cull` comme une lecture. Au-delà : `rate_limited` avec `retry_after_s`. Dix échecs d'authentification par minute depuis une même adresse déclenchent un 429.
- **Codes d'erreur :** `forbidden_level` (point d'accès désactivé, jeton invalide ou niveau insuffisant), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`, `no_active_view`, `unsaved_decisions`, `navigation_refused`, `modal_open`, `stack_mode_active`.
- **Les codes récents :** `confirmation_required` (un appel destructif n'a pas de valeur `confirm` valide pour cet ensemble exact : refaites une simulation, montrez le résultat à l'utilisateur, puis réessayez), `outcome_unknown` (une écriture a expiré ou la connexion a été coupée, elle a donc pu avoir lieu ou non : relisez l'état avant de réessayer, ne réessayez jamais à l'aveugle), `library_busy` (la bibliothèque est occupée par une autre tâche : réessayez dans un instant).
- **Codes HTTP à l'entrée :** 401 pour un jeton absent ou inconnu, 403 pour une requête de navigateur d'une autre origine ou pour les identifiants d'un agent sur `/api/mcp/tokens`, 404 quand le point d'accès est désactivé. Le pont d'onglet répond par des codes de fermeture. Sur une installation ouverte, `/api/mcp/tokens` répond aussi 403 à une requête qui ne vient pas de l'ordinateur qui exécute Facet.

## Notes de sécurité

- Les légendes, étiquettes, noms de fichiers, chemins et noms d'albums ou de personnes viennent de votre bibliothèque et peuvent contenir du texte écrit pour manipuler un assistant (injection de prompt). Chaque outil est marqué `facet/untrusted_content` et demande au modèle de les traiter comme des données. Ne donnez pas à un assistant qui lit aussi du contenu non fiable le moyen d'agir sur ce qu'il trouve ici.
- Les jetons n'expirent jamais. Révoquez ceux que vous n'utilisez plus.
- Les journaux consignent l'identifiant du jeton, l'outil, le résultat et le nombre de lignes, jamais les arguments ni le jeton.

## Limites connues

- **Installations ouvertes** (sans mot de passe). Seule la gestion des jetons est limitée à l'ordinateur local : un pair du réseau ne peut donc pas remplir la limite de 20 jetons. `/mcp`, les outils intégrés à la page et le pont d'onglet restent joignables par toute personne qui atteint la visionneuse, sous le même utilisateur anonyme partagé. Définissez un mot de passe avant d'activer le point d'accès sur un réseau.
- **Faux onglets sur une installation ouverte.** Un client hors navigateur peut envoyer une `Origin` inventée et un jeton nul, enregistrer un onglet `_anonymous` ayant le focus, répondre aux appels `ui_*` avec les données de son choix et évincer de vrais onglets via la limite de 8 onglets. Avec `viewer.trusted_local_editing`, un processus local peut aussi enregistrer un faux onglet `edition` (il peut falsifier `Host` et `Origin` sur le WebSocket), mais il pouvait déjà agir comme le navigateur. Un client du réseau local ne le peut pas, un pair en loopback étant exigé.
- Les limites de débit et les compteurs d'échecs d'authentification vivent en mémoire dans chaque processus ; avec `viewer.py --workers N`, chaque worker compte séparément.
- Le registre des onglets vit en mémoire dans un seul processus. Utilisez un seul worker (`viewer.py --workers 1`, la valeur par défaut) si vous vous appuyez sur les outils `ui_*` ; avec plusieurs workers, un appel peut atteindre un processus qui ignore votre onglet et répondre `no_tab`.
- Un utilisateur peut avoir au plus 8 onglets connectés ; en ouvrir un neuvième ferme le plus ancien.
- Rien n'est poussé de l'onglet vers un assistant externe : il ne connaît la progression du plan et l'activité de l'utilisateur qu'en appelant `ui_get_context`. L'application d'`auto_cull` ne lit pas l'onglet.
- La garde d'état d'`auto_cull` conserve 8 plans par utilisateur pendant 15 minutes. La mémoire d'aperçu est distincte : 300 secondes, 64 entrées pour tous les utilisateurs. Toutes deux vivent dans la mémoire d'un seul processus ; avec plusieurs workers, une application peut atteindre un processus qui n'en détient aucun, et la réponse indique alors `state_guard: "unavailable"`.
