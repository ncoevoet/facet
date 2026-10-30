# Visionneuse web

> 🌐 [English](../VIEWER.md) · **Français** · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md) · [简体中文](../zh/VIEWER.md)

La visionneuse est une application web FastAPI + Angular pour parcourir, filtrer, trier et gérer vos photos.

## Sommaire

- [Démarrer la visionneuse](#démarrer-la-visionneuse) · [Authentification](#authentification) · [Options de filtrage](#options-de-filtrage) · [Tri](#tri) · [Décisions de tri](#décisions-de-tri) · [Fonctionnalités de la galerie](#fonctionnalités-de-la-galerie)
- [Panoramas et bracketings d'exposition](#panoramas-et-bracketings-dexposition)
- [Gestion des personnes](#gestion-des-personnes) · [Déclenchement d'un scan](#déclenchement-dun-scan) · [Recherche sémantique](#recherche-sémantique) · [Albums](#albums)
- [Critique IA](#critique-ia) · [Légendage IA](#légendage-ia-gpu-16gb24gb-edition) · [Souvenirs (« Ce jour-là »)](#souvenirs-ce-jour-là) · [Vue Chronologie](#vue-chronologie) · [Vue Carte](#vue-carte) · [Capsules](#capsules)
- [Vue Dossiers](#vue-dossiers) · [Boîte de dialogue Filtre GPS](#boîte-de-dialogue-filtre-gps) · [Suggestions de fusion](#suggestions-de-fusion) · [Export vers éditeur](#export-vers-éditeur) · [Téléchargement](#téléchargement) · [Tri sélectif](#tri-sélectif) · [Nettoyage des indésirables](#nettoyage-des-indésirables) · [Mode de comparaison par paires](#mode-de-comparaison-par-paires)
- [Statistiques EXIF](#statistiques-exif) · [Raccourcis clavier](#raccourcis-clavier-galerie) · [Annuler](#annuler) · [Application web progressive](#application-web-progressive) · [Mobile](#mobile) · [Cadre photo / Kiosque](#cadre-photo--kiosque) · [Envoi automatique depuis le téléphone](#envoi-automatique-depuis-le-téléphone)
- [Configuration](#configuration-3) · [Performances](#performances) · [Points d'accès API](#points-daccès-api) · [Photos JPEG XL](#photos-jpeg-xl) · [Dépannage](#dépannage)

> **Les prérequis des fonctionnalités** sont indiqués en ligne : `[GPU]` · `[16gb/24gb]` (profil VRAM) · `[Edition]` (mot de passe d'édition) · `[Superadmin]`. Voir la [matrice des fonctionnalités](INSTALLATION.md#exigences-par-fonctionnalité).

> **Assistants IA** : Facet peut fournir ses outils aux assistants compatibles MCP. Avec le bon niveau de jeton, ils peuvent chercher dans la bibliothèque, la modifier et la trier. Voir [Agents IA (MCP)](AGENTS.md).

## Démarrer la visionneuse

### Production

```bash
python viewer.py
# Ouvrez http://localhost:5000
```

Cela sert l'API et l'application Angular pré-compilée sur un seul port.

Pour un débit plus élevé, lancez le mode production (Uvicorn, sans rechargement automatique). Ajoutez `--workers N` pour monter en charge (1 par défaut) :

```bash
python viewer.py --production --workers 4
```

### Développement

Lancez séparément le serveur d'API et le serveur de développement Angular :

```bash
# Terminal 1 : serveur d'API
python viewer.py
# API disponible sur http://localhost:5000

# Terminal 2 : serveur de développement Angular avec rechargement à chaud
cd client && npx ng serve
# Ouvrez http://localhost:4200 (redirige les appels d'API vers :5000)
```

## Authentification

### Mode mono-utilisateur (par défaut)

Protégez la visionneuse avec un mot de passe facultatif :

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Deux mots de passe contrôlent l'accès :

- **`viewer.password`** décide qui peut *parcourir*. Vide, tout le monde peut parcourir toute la bibliothèque. Défini, les utilisateurs doivent d'abord se connecter.
- **`viewer.edition_password`** est requis pour toute modification : notes, favoris et rejets, tri, albums, gestion des personnes et des visages, mode comparaison, changements de poids et de priorités, et exports. Vide (la valeur livrée par défaut), l'installation est en **lecture seule** : les modifications sont refusées avec `403` (« Set viewer.edition_password to enable editing »).

La génération IA à la demande (légendes, critiques VLM) exige aussi le mot de passe d'édition. Sans lui, vous n'obtenez que ce qui est déjà en cache (`source: "none"` ou `vlm_available: false`). Sans mot de passe d'édition, la galerie masque aussi les badges d'étoiles, de favori et de rejet existants, comme pour les visiteurs sans édition d'une installation protégée par mot de passe.

Redémarrez la visionneuse après avoir défini `viewer.edition_password` : la configuration n'est pas rechargée à chaud.

> **Avertissement :** avec un `viewer.password` vide (la valeur livrée par défaut), toute personne pouvant atteindre le port de la visionneuse peut parcourir la bibliothèque et télécharger les originaux. `viewer.py` écoute sur toutes les interfaces par défaut (`--host 0.0.0.0`, dont dépend l'image Docker). Définissez `viewer.password` avant de l'exposer au-delà de votre propre machine, ou liez-la au loopback avec `--host 127.0.0.1`. Dans Docker, publiez le port avec `127.0.0.1:5000:5000`. La visionneuse journalise un avertissement au démarrage tant que `viewer.password` est vide (sauf si on lui demande de se lier au loopback).

La connexion place aussi le jeton de session dans un cookie `HttpOnly` `SameSite=Lax`, afin que les miniatures et le flux de progression du scan se chargent sur les installations protégées par mot de passe. Le cookie n'est accepté que pour les requêtes en lecture seule (GET/HEAD) ; les modifications exigent toujours le jeton Bearer. La déconnexion (`POST /api/auth/logout`) l'efface.

### Mode multi-utilisateurs

Pour un NAS familial où chaque membre a ses dossiers de photos privés. Ajoutez une section `users` à `scoring_config.json` :

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

Écrivez chaque entrée de `directories` et `shared_directories` exactement comme le scanner a enregistré le chemin. La correspondance ignore la casse ASCII sous Windows, macOS, et pour les entrées UNC ou à lettre de lecteur. Elle distingue la casse partout ailleurs (Linux, par exemple). Les différences de casse non ASCII, et un lecteur mappé que l'hôte ne peut pas résoudre, ne correspondent pas.

Créez les utilisateurs depuis la CLI (il n'y a pas de page d'inscription) :

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Voir [Configuration](CONFIGURATION.md#utilisateurs) pour la référence complète.

### Rôles

| Rôle | Voir ses photos + partagées | Noter/mettre en favori | Gérer personnes/visages | Lancer des scans |
|------|:-:|:-:|:-:|:-:|
| `user` | oui | oui | non | non |
| `admin` | oui | oui | oui | non |
| `superadmin` | oui | oui | oui | oui |

### Visibilité des photos

Chaque utilisateur voit les photos de ses propres répertoires plus celles des répertoires partagés. Cela s'applique partout : galerie, miniatures, téléchargements, statistiques, options de filtre et pages de personnes.

### Notes par utilisateur

En mode multi-utilisateurs, les notes en étoiles, favoris et rejets sont stockés par utilisateur dans la table `user_preferences`. Les favoris d'Alice n'affectent pas la vue de Bob.

Pour migrer des notes mono-utilisateur existantes :

```bash
python database.py --migrate-user-preferences --user alice
```

## Options de filtrage

La recherche textuelle de la galerie conserve les mots Unicode et traite la ponctuation des noms de fichiers comme des séparateurs de mots. `IMG_0042.JPG` recherche ensemble les préfixes `IMG`, `0042` et `JPG`. Les termes cyrilliques et CJK fonctionnent. Les opérateurs FTS comme `OR` sont traités comme des mots littéraux.

### Onglets de la barre latérale

La barre latérale de filtres regroupe ses sections en cinq onglets, affichés sous forme d'icônes (survolez pour voir le nom). Un petit badge sur une icône compte les filtres actifs de l'onglet, et l'onglet garde son nom pour les lecteurs d'écran (« Parcourir, 2 actif(s) »). Le dernier onglet utilisé est mémorisé dans ce navigateur (`facet_sidebar_tab`). Parcourir, Qualité et Sujet ont des panneaux repliables, chacun mémorisant s'il est ouvert ; Tri et Affichage n'en ont pas.

| Onglet | Sections |
|--------|----------|
| **Parcourir** | Recherche sémantique, Personnes, Plage de dates, Contenu, Albums, Localisation, Dossier, Équipement |
| **Tri** | Une ligne de menu chacune pour la décision, puis les rafales, les doublons, les clignements, les bracketings, les panoramas et les rejetées, une note par étoiles, les bascules Favoris et Monochrome et, pour les éditeurs, *Visages manuels à vérifier* et *Corrections de panorama* |
| **Qualité** | Qualité, Couleur et qualité, Qualité étendue, Technique, Exposition & Plage (la qualité de l'image) |
| **Sujet** | Métriques visage, Composition, Saillance du sujet, Moments (ce qui est dans le cadre) |
| **Affichage** | Vue (taille des cartes, disposition, défilement rapide, actions des cartes) |

L'en-tête, **Rechercher un filtre**, l'avis d'album intelligent et la recherche par nom de fichier restent au-dessus des onglets sur chacun d'eux, donc `/` fonctionne depuis n'importe lequel. Saisir dans **Rechercher un filtre** masque les onglets et liste les curseurs correspondants de tous les onglets.

Le nombre à côté de **Filtres** est le total de tous les filtres actifs. Une plage min/max compte une fois, tout comme le filtre de localisation. La recherche par nom de fichier et *Similaire à* n'ont pas de section : ils ne sont comptés que dans ce total, tout comme un filtre sur une métrique que cette installation masque, afin que **Réinitialiser** puisse quand même l'effacer. **Réinitialiser** (avec une infobulle) apparaît à côté du nombre tant qu'au moins un filtre est actif ; le simple **X** tout à droite ne fait que fermer la barre latérale sur les écrans étroits.

Dans l'onglet Tri, la décision et chaque série (par exemple Doublons) est une ligne affichant sa valeur actuelle (comme Masqués, Affichés ou Seulement ceux-ci) qui ouvre un menu de choix, chacun avec une explication d'une ligne. Une ligne laissée sur sa valeur par défaut ne compte pas dans le badge de l'onglet ni de l'en-tête. *Seulement* et *Masqués* s'excluent mutuellement. Tant qu'une décision est choisie, Rejetées est verrouillé, et son infobulle en donne la raison. Le bouton étoile définit une note minimale : chaque clic l'augmente d'un cran, et le clic après 5, ou après un maximum venu d'un lien, l'efface. Il partage une ligne avec les bascules Favoris et Monochrome, réduites à une icône et dotées d'infobulles. Dans les onglets Qualité et Sujet, survoler le nom d'un réglage explique ce qui est noté et par quel modèle, et les contrôles de Tri ont aussi des infobulles.

<details><summary>Barre latérale de filtres complète — toutes les sections développées (cliquer pour voir)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Les cinq onglets de la barre latérale de filtres côte à côte : Parcourir, Tri, Qualité, Sujet et Affichage" width="900"></p>
</details>

### Filtres principaux

| Filtre | Options |
|--------|---------|
| **Type de photo** | Coups de cœur, Portraits, Personnes en scène, Paysages, Architecture, Nature, Animaux, Art & statues, Noir & blanc, Faible luminosité, Silhouettes, Macro, Astrophotographie, Rue, Pose longue, Aérien & drone, Concerts |
| **Niveau de qualité** | Bon (6+), Très bon (7+), Excellent (8+), Meilleur (9+) |
| **Appareil & objectif** | Filtrage basé sur l'équipement |
| **Personne** | Filtrer par personne reconnue |
| **Catégorie** | Filtrer par catégorie de photo |

### Filtres avancés

| Catégorie | Filtres |
|----------|---------|
| **Date** | Date de début et de fin |
| **Scores** | Agrégat, esthétique, score TOPIQ, score de qualité |
| **Qualité étendue** | Esthétique IAA (mérite artistique), Qualité du visage IQA, score LIQE |
| **Métriques de visage** | Qualité du visage, netteté des yeux, netteté du visage, proportion du visage, confiance de détection, nombre de visages |
| **Composition** | Score de composition, points de force, lignes directrices, isolation, motif de composition |
| **Saillance du sujet** | Netteté du sujet, prééminence du sujet, placement du sujet, séparation de l'arrière-plan |
| **Technique** | Netteté, contraste, plage dynamique, niveau de bruit |
| **Couleur** | Score de couleur, saturation, luminance, étalement de l'histogramme ; température de couleur et tranche de teinte (nécessitent `--recompute-colors`) |
| **Exposition** | Score d'exposition |
| **Notes utilisateur** | Note en étoiles |
| **Réglages de l'appareil** | ISO, ouverture (curseur de plage de diaphragme), focale (curseur de plage) |
| **Contenu** | Tags, bascule monochrome |
| **Moments** | Confiance du moment narratif (curseur 0–1 : `min_moment_confidence` / `max_moment_confidence`) |

Certains filtres de plage ne retiennent que les photos qui ont une valeur : même un filtre qui commence à 0 exclut donc les photos non notées :

- **Esthétique IAA, Qualité du visage IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA** : une photo que le modèle n'a pas pu noter n'a pas de valeur. Un tri croissant sur ces colonnes la place en dernier, dans la galerie comme dans les albums. Voir [Dimensions IQA supplémentaires](SCORING.md#dimensions-iqa-supplémentaires).
- **Netteté du sujet, Placement du sujet, Séparation de l'arrière-plan, Points de force** : une photo sans sujet détectable n'a pas de valeur, et le panneau de détail omet la ligne. La prééminence du sujet vaut 0.0 pour une telle photo. Voir [SCORING.md](SCORING.md).

### Motifs de composition

Filtrer par les 8 motifs détectés par SAMP-Net (dans `models/samp_net.py`) :
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Tri

Le bouton de tri de l'en-tête (et de la barre d'outils mobile) affiche l'icône du tri actuel ; son infobulle indique `Trier par : <tri actuel>`. Il ouvre un menu groupé de tous les tris. Le bouton croissant/décroissant se trouve à côté. Les modèles de notation alternatifs utilisent des libellés courts (IAA, 2.5, Q-R, DeQA, LIQE et IQA).

**Tri mémorisé.** La galerie s'ouvre sur le dernier tri choisi, ce qui l'emporte sur `viewer.defaults.sort`. Le choix est enregistré par navigateur dans `localStorage`, et non par compte.

- Seul un choix fait dans le menu de tri est mémorisé. Un tri venant d'un lien partagé ou d'un assistant ne l'est pas, et le `sort` propre à un lien l'emporte.
- Choisir de nouveau le tri par défaut configuré, ou réinitialiser les filtres, oublie ce choix.
- **Pertinence** n'est jamais mémorisé, car il exige une requête de recherche.

Les vitesses d'obturation sont triées par durée, donc `1/250` et `0.004` sont égales. Les valeurs manquantes ou invalides apparaissent en dernier dans les deux sens.

Colonnes triables par groupe (d'après `viewer.sort_options`) :

| Groupe | Colonnes |
|-------|---------|
| **Général** | Score global, Esthétique, Score de qualité, Date de prise de vue, Note en étoiles, Esthétique (IAA), Score LIQE, Q-ReAlign (Esthétique), DeQA, Esthétique v2.5 (les trois derniers apparaissent dès qu'une photo a ce score) |
| **Métriques de visage** | Qualité du visage, Qualité du visage (IQA), Netteté des yeux, Netteté du visage, Proportion du visage, Nombre de visages |
| **Technique** | Netteté technique, Contraste, Niveau de bruit |
| **Couleur** | Score de couleur, Saturation |
| **Exposition** | Score d'exposition, Luminance moyenne, Étalement de l'histogramme, Plage dynamique |
| **Composition** | Score de composition, Score des points de force, Lignes directrices, Bonus d'isolation, Motif de composition |
| **Saillance du sujet** | Netteté du sujet, Prééminence du sujet, Placement du sujet, Séparation de l'arrière-plan |
| **Contenu** | Confiance du moment (les NULL en dernier) |

### My Taste

Trie selon le `learned_score` du classeur personnel : ce qu'il a appris de vos comparaisons A/B, de vos notes et de vos décisions de tri. Un badge à côté du tri indique la couverture (% de photos ayant un score appris) et la précision du classeur sur données écartées, pour que vous puissiez juger dans quelle mesure lui faire confiance. Entraînez ou rafraîchissez le classeur avec `python facet.py --train-ranker`.

Contrôlé par `viewer.features.show_my_taste` (par défaut : `true`). État du classeur : `GET /api/ranker/status`.

### Métriques masquées en mode commercial

Avec `licensing.mode` défini sur `commercial`, la visionneuse masque les métriques dont les modèles ne peuvent pas être utilisés commercialement : LIQE, Esthétique IAA, Qualité du visage IQA (sauf si OFIQ est installé), DeQA (sauf si `licensing.allow_unclear` est défini) et Aesthetic V2.5. Leurs filtres, puces et options de tri disparaissent ; `/api/config` les liste dans `unavailable_metrics`. Dans la page de réglage des poids, leurs curseurs restent visibles mais désactivés, et la notation écarte ces poids puis renormalise. Redémarrez la visionneuse après avoir changé le mode de licence.

## Décisions de tri

Utilisez **Décision de tri → À examiner** dans la galerie pour parcourir les photos sans décision. Cette vue est triée par **Date de prise de vue, la plus ancienne d'abord** ; vous pouvez l'inverser ou la restreindre par date, dossier ou album. Choisir une décision de tri quitte les recherches sémantiques et de photos similaires.

- **Gardez** une photo que vous voulez ; **Rejetez** celle dont vous ne voulez pas. Les deux la retirent de À examiner. Retrouvez les photos conservées avec le filtre de statut **Conservées**.
- Garder est indépendant des favoris et des notes en étoiles.
- Garder et **Réinitialiser la décision** sont dans le détail de la photo, le menu contextuel et les actions groupées. Appuyez sur **K** (réassignable, voir [Raccourcis clavier](#raccourcis-clavier-galerie)) pour garder la photo courante. Dans le détail de la photo, Garder bascule.
- **Réinitialiser la décision** efface Garder et Rejeter sans toucher aux étoiles ni au favori.
- Les décisions survivent aux rechargements, redémarrages et rescans. Sur les installations multi-utilisateurs, elles appartiennent à l'utilisateur courant.
- Confirmer un groupe de tri marque ses photos conservées comme Conservées. Les notes et favoris existants ne sont pas convertis en décisions Garder.

**Compteurs de progression.** La galerie affiche les compteurs **indécises**, **conservées** et **rejetées** pour tout le dossier, album ou périmètre filtré visible, et pas seulement la page chargée. Le pourcentage est `(conservées + rejetées) / total`. Les bascules Décision de tri et Masquer rejetés ne réduisent pas le total ; les autres filtres le font.

**Reprendre une file.** **Trier les indécises** lance une file. **Continuer le tri** rouvre votre file À examiner la plus récente sur ce navigateur, à sa première photo indécise restante.

- Le signet est propre au navigateur et à l'identité connectée (jusqu'à 20 identités). Il ne se synchronise pas entre appareils.
- Changer de filtres ne le remplace pas, sauf si vous ouvrez une autre file À examiner.
- Les files d'album utilisent les critères enregistrés actuels de l'album.
- Les groupes temporaires de rafales/séries ne sont pas mis en signet, car un rescan peut les renuméroter.
- La déconnexion efface tous les signets de files de tri sur ce navigateur.

**Notifications flottantes.** La progression du tri, **Continuer le tri**, la notification de photos masquées, celle des filtres actifs (avec **Réinitialiser tous les filtres**) et celle de migration des miniatures s'empilent en bas à droite.

- Le × de chaque carte la masque pour l'onglet courant du navigateur. Elle revient dans un nouvel onglet, ou quand la notification change (autre périmètre, nombre de photos masquées modifié, filtre ajouté ou retiré).
- Pour masquer définitivement la progression du tri, utilisez **Masquer la progression du tri** / **Afficher la progression du tri** du menu utilisateur. Ce choix est enregistré par navigateur et masque aussi le bouton **Trier les indécises**.
- Après quelques secondes d'inactivité, la pile se replie en une petite pastille avec un compteur. Survolez-la ou cliquez dessus pour la déplier.

## Fonctionnalités de la galerie

### Piles de photos manuelles

Sélectionnez **2 à 1000 photos explicites**, puis **Empiler les photos** dans la barre de sélection ou appuyez sur **S** pour ouvrir l’éditeur pleine page à `/stacks/edit`. Une sélection de toute la vue ne crée pas de pile. S ouvre un aperçu sans enregistrer. Le menu utilisateur → **Personnaliser les raccourcis** permet de modifier cette touche ; l’infobulle, l’Aide et la référence `?` affichent la touche actuelle. Si un ancien réglage utilise déjà S, il est conservé et l’action Empiler reste **Non attribuée** jusqu’au choix d’une touche libre. Les droits d’édition sont nécessaires. Une photo appartient à une seule pile par propriétaire. La page centre un aperçu avec zoom au-dessus d’une bande de vignettes permanente. Cliquez sur une vignette ou utilisez `←`/`→` pour cibler une photo, puis ses commandes de couverture, d’ordre ou de retrait. Le bouton de zoom, la molette ou un double-clic permettent d’examiner les détails.

Utilisez **Cmd+Maj+S** ou **Ctrl+Maj+S** pour empiler immédiatement les photos explicites non empilées dans l’ordre de sélection, la première servant de couverture. Les membres de piles existantes ouvrent l’éditeur. Une réussite efface la sélection validée et Annuler la rétablit ; une annulation ou un échec la conserve. Échap dans l’éditeur revient à la galerie d’origine sans enregistrer.

**Rejeter pendant l’empilage.** Activez une photo dans l’éditeur pleine page ou son dialogue et utilisez **Rejeter** ou **R**. La photo active dans la chambre noire des piles suggérées propose la même action ; ouvrez-la d’abord pour choisir la photo. Rejeter enregistre immédiatement la décision habituelle, efface Conserver, favori et étoiles, et exclut uniquement cette photo de la pile proposée. Les fichiers originaux ne sont ni supprimés ni modifiés. Le compteur et les miniatures assombries montrent les exclusions. Annuler restaure les valeurs antérieures et l’appartenance au brouillon encore pertinent sans remplacer les choix ultérieurs d’ordre ou de couverture ; une décision ultérieure peut empêcher l’annulation. Les photos déjà rejetées restent présentes jusqu’à leur exclusion explicite, sans nouvelle décision. Le regroupement attend Enregistrer ; quitter sans enregistrer n’annule pas Rejeter.

Si les photos sélectionnées appartiennent déjà à des piles, **Combiner les piles** est le choix par défaut : l’aperçu inclut leurs autres membres. **Photos sélectionnées uniquement** déplace seulement la sélection explicite. L’éditeur affiche les nombres sélectionné et final, les membres supplémentaires et un résumé des effets ; développez les détails pour examiner chaque pile source. Au moins deux membres restants conservent leur pile ; un seul redevient indépendant et une source vide disparaît. Exclure une photo de la nouvelle pile la laisse dans sa source selon ces mêmes règles. La pile finale et l’ensemble des photos concernées sont chacun limités à 1000 ; une source indisponible ou partiellement visible est refusée. Changer de mode conserve l’ordre, la couverture et les exclusions encore applicables.

Vérifiez l’aperçu actualisé par le serveur puis choisissez **Empiler les photos** pour enregistrer. La page reste ouverte pour examiner le résultat ; la notification propose **Annuler** tant qu’elle reste disponible et que les révisions correspondent. **Continuer la modification** récupère un nouvel aperçu avant tout autre enregistrement. **Retour à la galerie** revient à la galerie ou à l’album d’origine avec son URL exacte et invalide l’annulation précédente. Partir sans enregistrer abandonne le regroupement ; un rejet explicite persiste. Recharger le navigateur restaure la sélection uniquement pour le même compte, après une nouvelle autorisation ; ouvrir l’URL sans sélection valide permet de revenir en arrière.

Le badge ou une photo empilée ouvre la visionneuse : bande de vignettes, boutons précédent/suivant et compteur suivent l’ordre enregistré. Les flèches restent dans la pile. **Gérer la pile** ouvre une boîte de dialogue secondaire : cliquez sur une vignette ou utilisez Gauche/Droite pour son grand aperçu, choisissez **Couverture**, réordonnez avec les boutons fléchés ou retirez des membres. L’ouverture seule conserve l’édition ordinaire : un membre retiré devient indépendant, retirer la couverture choisit le premier membre restant, et moins de deux membres ou **Dissocier** dissout la pile. **Ajouter les photos sélectionnées** depuis une autre pile active explicitement l’aperçu de regroupement et ses deux modes. Les changements de regroupement préservent fichiers et valeurs de tri ; l’action Rejeter explicite change immédiatement les valeurs de tri.

- Les actions de notation, Garder/Rejeter, métadonnées, téléchargement, album et suppression n'étendent jamais implicitement une pile.

**Dans la galerie.** Une pile se replie en une seule vignette ; **Développer toutes les piles** est une préférence mémorisée. Les filtres et l'appartenance aux albums s'appliquent aux photos individuelles : la couverture s'affiche si elle correspond, sinon le premier membre correspondant. Le parcours d'une pile contourne le masquage automatique des rafales/doublons. La chronologie et la carte affichent les photos individuelles.

**Sélection.** Sélectionner une vignette repliée ne sélectionne que la photo affichée. Ouvrez la pile et utilisez **Sélectionner les N membres** pour tous les sélectionner. **Tout sélectionner dans la vue**, la sélection par percentile et `target:view` de l'assistant incluent toutes les photos correspondantes, membres repliés compris, et les actions sur toute la vue affichent d'abord le nombre réel de photos. Dans les résumés API/assistant, `total` compte les vignettes affichées et `photo_total` les photos.

**Confidentialité et persistance.**

- Les piles sont privées à leur propriétaire (l'installation, en mode mono-utilisateur). La modification exige l'accès édition.
- Elles sont absentes des partages publics et des exports de la visionneuse. Une pile partiellement visible est en lecture seule.
- Les rescans conservent couverture, ordre et appartenance. Les sauvegardes ordinaires de la base de données conservent les piles.
- Les exports complets de la base de données de la visionneuse omettent les piles et les albums intelligents dont les filtres nomment une pile privée, ainsi que les albums intelligents aux filtres illisibles (JSON invalide, imbrication excessive ou plus de 1 Mio). Les mises à jour incrémentales conservent les albums et piles propres à la destination.
- L'[import/envoi de piles Immich](IMMICH.md#piles-manuelles-import-et-envoi) est une opération CLI distincte.

**Piles suggérées** ouvre la revue pleine page à `/culling?mode=stacks`, avec les filtres courants et un retour à la galerie ou à l’album d’origine. Les droits d’édition sont nécessaires. Elle examine les groupes de doublons et de rafales existants sans masquer leurs membres.

- Dans la grille, `↑`/`↓` sélectionnent un groupe, **Entrée** ouvre sa chambre noire et **S** l’empile avec la couverture proposée. Dans la chambre noire, `←`/`→` ciblent une image et **S** ou **Entrée** l’empile avec cette couverture. **X** ignore le groupe ; empiler et ignorer proposent Annuler.
- **Rejeter** ou **R** dans la chambre noire exclut la photo active. Empiler enregistre les photos restantes et en exige au moins deux. Ignorer écarte la proposition originale. S’il en reste trop peu, vous pouvez examiner les photos exclues, changer de groupe, annuler, ignorer ou revenir. Le rejet reste enregistré après avoir terminé une proposition. Annuler Empiler ou Ignorer rétablit ses exclusions ; une suggestion ultérieure commence un nouveau brouillon.
- La chambre noire conserve le grand aperçu avec zoom, la loupe, la comparaison et la bande de vignettes. **Z** bascule le zoom, **P** l’accentuation de mise au point, **G** fait défiler les grilles de composition, **F** le plein écran et **Échap** revient à la grille des groupes. **Modifier les membres** ouvre une boîte de dialogue secondaire ; réduire une suggestion à une photo propose **Passer cette pile**.
- Les groupes ignorés sont mémorisés par compte jusqu’au changement de leurs membres. Les groupes contenant des photos déjà empilées ou des vues de bracketing/panorama sont exclus ; les groupes qui se chevauchent sont exclus en entier, en privilégiant les doublons.
- L’en-tête compte les suggestions chargées, pas le total de la bibliothèque. Un lot contient au plus 20 propositions et 2000 photos (1000 par groupe). Le suivant se charge automatiquement seulement après avoir empilé ou ignoré toutes les suggestions chargées. **Recharger les suggestions** recharge le même périmètre ; **Retour à la galerie** revient à l’origine.
- Indisponible dans les listes épinglées, Photos similaires ou la recherche sémantique. Empiler et Ignorer ne modifient ni décisions de tri ni originaux. Seul Rejeter explicitement change les valeurs de tri.

### Cartes de photo

- Miniature avec badge de score. Survolez-la pour voir où se situe le score dans votre bibliothèque (« Top 18 % de la bibliothèque »).
- Tags cliquables pour un filtrage rapide
- Avatars de personnes pour les visages reconnus
- Badge de catégorie
- Le clic droit (ou Maj+F10) ouvre le [menu contextuel](#sélection-multiple--actions-groupées)

Dans le détail de la photo, les métriques sont réparties en onglets à icônes : données EXIF (si présentes), Qualité, Composition (avec la saillance du sujet), Technique et Histogramme. Le dernier onglet ouvert est mémorisé. Chaque score s'affiche à côté de sa distribution dans la bibliothèque, la barre de la photo étant mise en évidence ; survolez une barre pour voir le rang de la photo et la plage de la bibliothèque. Le placement est calculé sur toute la bibliothèque, et non sur les filtres courants, à la barre la plus proche parmi 20.

### Sélection multiple & actions groupées

Cliquez sur des photos pour les sélectionner ; Maj+clic sélectionne une plage. Une barre d'actions apparaît en bas à gauche avec des boutons à icônes (survolez pour voir les libellés). Les actions groupées nécessitent le mode édition.

- **Favori** — marque toutes les photos comme favorites (efface le rejet)
- **Rejeter** — marque toutes les photos comme rejetées (efface le favori et la note)
- **Noter** — définit ou efface une note de 1 à 5 étoiles
- **Ajouter à un album** — ajoute à un album existant ou nouveau
- **Modifier les mots-clés** — ajoute ou retire un [tag manuel](#tags-manuels) sur chaque photo sélectionnée
- **Tout sélectionner** — avec une sélection vide, sélectionne toutes les photos que les filtres retiennent, pas seulement les pages chargées. Avec des photos déjà sélectionnées, ajoute les photos chargées et propose d'élargir à toute la vue. Les actions sur toute la vue confirment d'abord le nombre exact de photos.
- **Inverser** — remplace la sélection par son complément. À partir d'une sélection vide, c'est toute la vue. À partir d'une sélection non vide, cela reste dans les photos chargées : choisissez les gardées, inversez, rejetez.
- **Comparer** — ouvre 2 à 4 photos côte à côte avec panoramique et zoom synchronisés (molette pour zoomer, glisser pour déplacer, double-clic pour réinitialiser). Les volets passent en pleine résolution au zoom.
- **Copier les noms** — copie les noms de fichiers dans le presse-papiers. Une copie de toute la vue demande d'abord confirmation ; au-delà de 10 000 photos, elle est refusée.
- **Exporter** — écrit des sidecars XMP à côté des fichiers (voir [Export vers éditeur](#export-vers-éditeur))
- **Trier vers un dossier** — copie les gardées, ou déplace/met à la corbeille les rejetées, vers un dossier (voir [Trier vers un dossier](#trier-vers-un-dossier))
- **Supprimer** — envoie les photos à la corbeille du système (voir [Supprimer](#supprimer)). Affiché seulement quand `viewer.cull.allow_trash` est activé. Désactivé pour une sélection « tout sélectionner dans la vue » : sélectionnez les photos explicitement.
- **Télécharger** — télécharge les photos sélectionnées
- Effacez la sélection avec Échap ou le bouton Effacer.

Double-cliquez sur une photo pour l'ouvrir.

**Menu contextuel.** Clic droit sur une photo, ou donnez-lui le focus et appuyez sur Maj+F10 / la touche Menu.

- Sur une photo faisant partie d'une sélection de plusieurs photos, il agit sur toute la sélection avec les actions de la barre (sauf Inverser et Tout sélectionner), y compris **Modifier les mots-clés**.
- Sur toute autre photo, il agit sur cette photo seule et ajoute Ouvrir la photo, Similaires, Pourquoi ce score ?, Écrire les métadonnées dans le fichier et Assigner un visage à une personne (quand la photo a des visages non assignés), selon leurs conditions d'accès.
- Trier une photo depuis le menu ne retire que cette photo de la sélection.
- Non proposé sur les appareils tactiles (`hover: none` et `pointer: coarse`) ; utilisez-y la feuille Actions.

### Garder le top N%

Le contrôle **Garder le top %** de la barre d'outils (mode édition) trie toute la vue filtrée en une étape. Définissez un pourcentage. Facet classe la vue selon le **tri courant** (agrégat, My Taste, Coups de cœur, netteté…), garde la part supérieure et **sélectionne le reste**. Rejetez-les depuis la barre d'actions, après avoir désélectionné celles que vous voulez épargner.

- Rien n'est déplacé ni supprimé ; cela ne fait que remplir la sélection. Les rejets entraînent toujours My Taste.
- La sélection est plafonnée à 5000 photos. Sur une vue plus grande, restreignez le filtre (album, date, personne…).
- Avec les valeurs par défaut `hide_brackets` / `hide_panoramas`, un bracketing ou un panorama compte pour **une** photo.

### Liste épinglée par l'assistant

Quand un assistant connecté via [Agents IA (MCP)](AGENTS.md) vous montre une liste exacte de photos, la galerie l'affiche dans l'ordre de l'assistant. Une ligne d'état indique combien de photos ont été choisies ; **Revenir à la vue habituelle** rétablit vos filtres.

- Tant que la liste est affichée, la barre de filtres, les puces de tags, les avatars de personnes, **Similaires** et les actions liées au filtre (comme **Garder le top N%**) sont masqués. Changer d'album remplace quand même la liste.
- Afficher une liste efface votre sélection et le panneau latéral.
- Les écritures de l'assistant apparaissent sans rechargement : les cartes modifiées se rafraîchissent et les photos supprimées quittent la liste. Une photo que `cull_apply` a déplacée ou mise à la corbeille reste. Une seule notification « L'assistant a modifié N photos » apparaît par rafale de changements. Voir [Mises à jour en direct](AGENTS.md#mises-à-jour-en-direct).

**Pastille Assistant actif.** Pendant qu'un assistant travaille dans votre onglet, une pastille **Assistant actif** s'affiche dans l'en-tête pendant quelques secondes après chaque écriture ou commande. Cliquez dessus pour ouvrir **Activité de l'assistant** : les 50 dernières actions de cette session (perdues au rechargement), avec l'outil, le nombre de photos et l'heure. Les actions qui désignaient des photos ont **Afficher les photos**. Quand l'assistant le demande, l'onglet lui indique sur quelle photo se trouve votre curseur (`focused`) et ce que vous avez fait depuis son dernier coup d'œil (`user_activity`). Rien n'est envoyé sans sollicitation. Voir [Contrôler votre onglet ouvert](AGENTS.md#piloter-votre-onglet-ouvert).

### Trier vers un dossier

**Trier vers un dossier…** dans la barre d'actions groupées (mode édition) copie les gardées, ou déplace/met à la corbeille les rejetées, vers un dossier cible. La corbeille est celle du système, jamais une suppression définitive, et exige `viewer.cull.allow_trash`.

- **Chaque exécution commence en simulation.** Vous voyez un aperçu avant que quoi que ce soit soit écrit ; déplacer/mettre à la corbeille ne s'exécutent qu'avec un `dry_run=false` explicite.
- **Le serveur choisit les fichiers d'après l'état propre de chaque photo.** Copier n'agit que sur les gardées, déplacer/corbeille que sur les rejetées. Tout le reste est signalé comme `excluded_by_state`. Le client ne peut pas fournir une liste de fichiers à supprimer.
- **Les compagnons sont optionnels.** Rejeter un JPEG n'emporte pas son RAW, sauf si vous cochez **Inclure le RAW / XMP associé** (`include_companions`).
- Sous macOS et Windows, les fichiers RAW compagnons gardent leurs noms sur disque, y compris les extensions en majuscules ; sous Windows, les sidecars `.xmp` aussi.

**Disponibilité de la corbeille pour les rejetées.** L'option « Mettre les rejetées à la corbeille » n'apparaît que lorsque `viewer.cull.allow_trash` est activé *et* que le paquet `send2trash` est installé (`/api/config` indique `cull.trash_available: true`). Sinon la boîte de dialogue en donne la raison : « le paquet `send2trash` n'est pas installé » ou « un administrateur a désactivé la mise à la corbeille ».

**Séries multi-images.** Avec les valeurs par défaut `hide_brackets` / `hide_panoramas`, la sélection ne contient que l'exposition de référence d'un bracketing ou la vue centrale d'un panorama. Par défaut, trier une série agit donc sur **un seul** fichier. Deux cases optionnelles élargissent la portée :

- **Inclure le RAW / XMP associé** (`include_companions`) ajoute le RAW et le sidecar `.xmp` de la même vue.
- **Inclure les vues de la série** (`include_sequence_siblings`) ajoute les autres vues de la série, mais seulement celles dont l'état garder/rejeter correspond à l'action. Les vues gardées ne sont jamais mises à la corbeille parce qu'une voisine a été rejetée. Une vue que vous avez désélectionnée n'est jamais réintégrée.
- L'aperçu indique toujours combien de vues voisines existent (`sequence_siblings`). `matched` distingue « rien n'était éligible » d'un résultat vide.
- Déplacer ou mettre à la corbeille la tête d'une série promeut une voisine survivante, de sorte que la série reste visible.
- Pour choisir un sous-ensemble exact d'une série, ouvrez-la d'abord avec l'action « ouvrir cette série dans la galerie » du détail de la photo. Cette vue montre chaque image.

Un tri limité par un filtre suit les mêmes règles de filtre que la galerie, Type de photo compris. Une vue de plus de 10 000 photos est refusée plutôt que tronquée, même pour une simulation : restreignez-la (album, date, personne…) et réessayez. Détails : [API.md](../API.md).

**Où vous pouvez écrire.** Sans `viewer.export.allowed_target_dirs`, Facet n'écrit que dans vos répertoires de scan. Un sous-dossier de l'arborescence de photos (par ex. `_rejected`) fonctionne sans configuration. Pour un dossier ailleurs, ajoutez-le à `viewer.export.allowed_target_dirs`. Voir [Configuration — Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri). Dans Docker/Podman, les chemins se résolvent **à l'intérieur du conteneur** — voir [Déploiement — Sémantique des chemins dans les conteneurs](DEPLOYMENT.md#sémantique-des-chemins-en-conteneur).

**« Accès refusé » sur chaque action.** C'est un refus volontaire : le dossier cible n'est pas autorisé, ou votre session d'édition a expiré. Vérifiez le champ `detail` de la requête en échec dans l'onglet Réseau du navigateur. Un vrai problème de système de fichiers a un autre aspect : succès partiel avec un compteur `errors` non nul, et l'erreur de l'OS dans le journal du serveur.

### Supprimer

**Supprimer** dans le détail de la photo et sur la barre de sélection envoie les fichiers directement à la corbeille du système (récupérable, via `send2trash`). C'est distinct de Trier vers un dossier et de la chambre noire `/culling`. Cela utilise le même indicateur `viewer.cull.allow_trash`.

- **L'entrée de la bibliothèque disparaît aussitôt.** Contrairement à Trier vers un dossier, la ligne de la photo est supprimée dès que son fichier est mis à la corbeille ; pas besoin de `--cleanup-missing-photos`. Un RAW compagnon entraîné qui avait été analysé comme photo à part entière disparaît aussi.
- **Sélection explicite uniquement.** Jusqu'à 10000 chemins ; « tout sélectionner dans la vue » est désactivé.
- **Portée.** Par défaut, uniquement le fichier nommé. **Inclure le RAW / XMP associé** (`include_companions`) et **Inclure les vues de la série** (`include_sequence_siblings`) l'élargissent, comme dans Trier vers un dossier. Les deux sont désactivés par défaut.
- **Les expositions de référence des bracketings sont protégées.** La vue de référence d'un bracketing (`sequence_ev_offset = 0`) est refusée (`refused_bracket_lead`) sauf si vous incluez les voisines ; tout le bracketing part alors ensemble. La tête d'un panorama supprimé promeut une voisine survivante.
- **Résultats partiels.** Chaque chemin est rapporté séparément. Une tête de bracketing refusée n'arrête pas le reste. Un fichier dont la mise à la corbeille a échoué (`errors`) conserve sa ligne.
- **Fichiers déjà absents du disque.** **Supprimer aussi les entrées de la bibliothèque dont le fichier est déjà absent du disque** (activé par défaut) supprime aussi ces lignes, rapportées comme `removed_missing`. Décoché, elles reviennent dans `skipped` et leurs lignes sont conservées. Un chemin hors des répertoires de scan, ou dans un dossier absent ou vide (un volume hors ligne), reste toujours dans `skipped`. Utilisez `--cleanup-missing-photos` pour balayer toute une bibliothèque.

Champs de réponse et codes de statut : [API.md](../API.md).

### Options d'affichage

- **Mode de disposition** — **Grille** (cartes uniformes) ou **Mosaïque** (rangées justifiées conservant les proportions), à toutes les largeurs d'écran.
- **Taille des vignettes** — curseur de hauteur des cartes/rangées (120–400 px, enregistré dans localStorage)
- **Masquer détails** — masque les métadonnées sur les cartes (mode grille uniquement)
- **Infobulle** — comment les détails d'une photo s'affichent : **Panneau latéral** (par défaut), **Survol**, **Clic** ou **Désactivée**.
  - Le panneau latéral montre tous les détails dans le tiroir de droite, disposés comme le détail de la photo. Il suit le survol et le clic, donc il fonctionne sur écran tactile. Il garde la dernière photo quand le curseur quitte la grille.
  - Cliquer sur une photo maintient le panneau sur elle jusqu'à ce que vous appuyiez sur **Désélectionner** (ce qui désélectionne aussi la photo). **Échap** fait la même chose et efface la sélection.
  - Le panneau partage le tiroir avec les filtres ; ouvrir les filtres le masque. Il exige une fenêtre d'au moins 1280 px de large.
  - **Survol** et **Clic** affichent une courte bulle : catégorie, agrégat et rang, esthétique, composition, netteté, exposition et une ligne EXIF.
- **Personnaliser les boutons des cartes** — réordonnez et affichez/masquez les boutons de la ligne qui apparaît au survol d'une carte. Neuf actions sont disponibles : trouver des similaires, pourquoi ce score, écrire les métadonnées, assigner un visage, ouvrir le groupe de doublons, le groupe de rafale, la série bracketing/panorama ou la pile de photos, et ouvrir la page de la photo. Les boutons de groupe n'apparaissent que sur les photos d'un tel groupe. Les boutons de groupe de doublons et de pile de photos sont activés par défaut ; les autres sont optionnels. Enregistré par navigateur.
- **Masquer clignements** — masque les photos avec clignements détectés
- **Clignements uniquement / Doublons uniquement** — n'affiche que les photos avec clignement, ou tous les membres de chaque groupe de doublons. Les bascules de masquage sont suspendues pour cette vue.
- **Rejetés uniquement** — liste uniquement vos photos rejetées. Traitez-les avec tout sélectionner et **Trier vers un dossier**, ou avec **Tout mettre à la corbeille (corbeille du système)** dans Tri sélectif. Les deux plafonnent la portée du filtre à 10 000 photos ; restreignez par date ou album pour en traiter davantage, et désactivez les filtres qui masquent des groupes pour inclure chaque vue rejetée. Désactivé tant qu'une décision de tri est sélectionnée.
- **Meilleure de la rafale** — n'affiche que la photo la mieux notée de chaque rafale
- **Meilleure du bracketing** — n'affiche que l'exposition de référence de chaque bracketing. **Activé par défaut.** Indépendant de Meilleure de la rafale, car la tête de rafale d'un bracketing n'est pas toujours son exposition de référence.
- **Meilleure du panorama** — n'affiche que la vue centrale de chaque panorama ou panorama HDR. **Activé par défaut.**
- **Défilement infini** — les photos se chargent au fil du défilement
- **Défilement rapide (virtualisé)** — ne rend que les rangées proches de la fenêtre, ce qui garde un défilement profond rapide. Activé par défaut. Désactivez-le dans l'onglet Affichage de la barre latérale si vous rencontrez des problèmes de mise en page. Le mode grille avec détails affichés se rend toujours en entier. Enregistré dans localStorage (`facet_virtual_scroll`).

### Photos similaires

Cliquez sur **Similaires** sur une photo et choisissez un mode :

- **Visuel** (par défaut) — similarité pHash (70 %) + similarité CLIP/SigLIP (30 %). Quand deux photos ne partagent qu'un des deux signaux, il compte à plein poids ; les photos qui n'en partagent aucun ne sont jamais listées. Toutes les correspondances au-dessus du seuil sont renvoyées, page par page. Si la photo n'a aucun des deux signaux, réanalysez-la avec `--force` (un simple `python facet.py <dir>` ignore les fichiers déjà traités).
- **Couleur** — intersection d'histogrammes (70 %) + distance de saturation (10 %) + distance de luminance (10 %) + bonus monochrome (10 %). Préfiltre par indicateur monochrome et plage de saturation.
- **Personne** — photos avec la ou les mêmes personnes, par `person_id` quand disponible, sinon par similarité des embeddings de visage.

Le **curseur de seuil de similarité** (0–90 %) règle la rigueur de la correspondance (pas en mode personne). Les résultats défilent à l'infini.

### Puces de filtre

Les filtres actifs apparaissent comme des puces amovibles avec compteurs en haut de la galerie.

### Tags manuels

Les tags manuels sont des tags que vous saisissez vous-même, conservés à côté des tags IA. Ils sont stockés à part (`photo_manual_tags`, et non la colonne `tags` de la photo), si bien que les rescans et ré-étiquetages ne les effacent jamais.

- **Où ils s'affichent.** Dans le **détail** de la photo uniquement, sous forme de puces marquées différemment des tags IA. Les cartes et infobulles montrent les tags IA.
- **Qui peut les modifier.** Les utilisateurs en mode édition. Sur une installation sans `viewer.edition_password`, ils sont en lecture seule. Les tags IA ne peuvent pas être retirés.
- **Modification groupée.** Sélectionnez des photos et utilisez **Modifier les mots-clés** (barre de sélection, feuille Actions mobile ou menu contextuel) pour ajouter ou retirer un tag. Les sélections de toute la vue fonctionnent. Les photos qui ont déjà 50 tags manuels sont ignorées ; `count` rapporte les photos réellement modifiées.
- **Format.** Les tags sont rognés, mis en minuscules et leurs espaces réduits (NFC). 64 caractères max, 50 max par photo. Les tags vides, les virgules et les caractères de contrôle sont refusés. Un tag égal à l'un des tags IA de la photo n'est pas stocké.
- **La recherche et les filtres les voient.** Le filtre de tags, la recherche textuelle, la recherche sémantique (`/api/search`, sauf la portée texte limitée aux légendes), la liste déroulante des tags, les statistiques et les exports sidecar/intégré/Lightroom utilisent tous les tags IA + manuels. La recherche textuelle fait correspondre un tag manuel comme une expression entière.
- **Exceptions.** Les capsules ne comptent que les tags IA. Les tags manuels n'affectent jamais les scores, les catégories ni les moments narratifs.
- **Masqués des liens de partage.** Les visiteurs d'un lien de partage ne les voient jamais. Un album intelligent partagé applique quand même le filtre enregistré du propriétaire.
- **Partagés par tous les utilisateurs.** En mode multi-utilisateurs, tout utilisateur en mode édition peut retirer un tag ajouté par un autre.
- **Non annulables.** [Annuler](#annuler) ne les couvre pas. Un tag retiré peut revenir depuis un sidecar ; voir [Règles de conflit](INTEROP.md#règles-de-conflit).
- **Tags importés.** `--import-sidecars` stocke les mots-clés de sidecar inconnus (ni tags IA, ni noms de personnes) comme tags manuels avec la source `xmp`.
- **Liés au chemin du fichier.** Déplacer ou renommer un fichier lui fait perdre ses tags manuels.

## Panoramas et bracketings d'exposition

Les vues d'un panorama sont destinées à être assemblées et celles d'un bracketing à être fusionnées ; ce ne sont pas des prises concurrentes. La seule détection de rafales les regrouperait et n'en laisserait qu'une visible, donc Facet détecte ces séries séparément.

**Dans la galerie.** `Meilleure du bracketing` et `Meilleure du panorama` (tous deux activés par défaut) montrent une vue par série : l'exposition de référence d'un bracketing, la vue centrale d'un panorama. Cette vue porte une petite icône à côté de l'étoile et du cœur : balayage simple, balayage HDR ou bracketing d'exposition. L'icône n'apparaît que tant que la bascule masque le reste de la série.

**Dans le tri.** Le menu de granularité propose `Bracketings d'exposition`, `Panoramas` et `Panoramas HDR` comme flux distincts, jamais fusionnés dans `Tout`. Chaque vue commence gardée, et confirmer une série n'enregistre aucune paire de comparaison, de sorte que le classeur n'est pas entraîné sur la façon dont une série a été prise.

**Corriger une série.** La détection se trompe sur environ 4 % des séries. Les corrections sont persistantes : elles survivent à toute exécution de détection ultérieure. Les deux exigent le mode édition, au moins deux vues, et peuvent être annulées depuis la barre de notification.

- **Faux positif** (pas un panorama, ou simple vs HDR) : utilisez le menu de correction de la barre d'actions du groupe dans le tri.
- **Panorama manqué** : sélectionnez ses vues dans la galerie et choisissez *Marquer comme série* → *Marquer comme un panorama*.

**Marquer un bracketing manqué.** Pour une échelle d'expositions détectée comme une rafale ordinaire :

- Dans la chambre noire, un groupe de rafale simple (aucune vue déjà dans un bracketing ou un panorama) propose *Marquer comme bracket*.
- Dans la barre de sélection de la galerie, utilisez *Marquer comme série* → *Marquer comme un seul bracket*.
- Les vues doivent former une vraie échelle : au moins 2 vues, chacune avec des données d'exposition (ouverture, vitesse d'obturation, ISO) et une date de prise de vue, et deux vues ne peuvent pas avoir la même valeur d'exposition. Sinon le marquage est refusé avec un message et rien n'est enregistré.
- Marquer des vues qui chevauchent un bracketing déjà marqué l'étend. L'ensemble combiné doit rester une échelle valide.
- Le flux de la chambre noire masque les vues rejetées, donc un marquage dans la chambre noire n'inclut jamais un échelon rejeté.
- Un groupe `bracket` propose à la place *Abandonner la correction*.
- Si une vue marquée disparaît ou perd ses données d'exposition ou de date, toute la série attend que chaque membre soit de nouveau éligible.
- **Le marquage l'emporte sur la détection de panoramas** : un panorama détecté contenant des vues marquées est abandonné à l'exécution suivante.

**Les corrections s'appliquent à la prochaine exécution de détection.** Une correction est enregistrée aussitôt et affichée comme en attente : un badge d'horloge sur la vignette de la galerie, une puce *Correction en attente* dans le tri. La page de tri affiche une bannière avec un bouton **Relancer la détection**. Le filtre *Corrections de panorama* de la barre latérale (édition uniquement, dans l'onglet Tri) liste les corrections en attente sur toute la bibliothèque. *Abandonner la correction* en retire une plus tard.

**Le régler.** L'onglet Panoramas sous Comparer contient les seuils calibrés : nombre minimal de vues, balayage minimal, plus grand écart et écart d'exposition HDR. Les enregistrer ne change rien tant que vous ne relancez pas la détection (le bouton est à côté d'Enregistrer). Voir [CONFIGURATION.md](CONFIGURATION.md#détection-de-panoramas).

## Gestion des personnes

> Parcourir les personnes est ouvert à tous les visiteurs ; renommer, fusionner, changer d'avatar et assigner des visages exigent `[Edition]`.

### Filtre par personne

La liste déroulante présente les personnes avec leurs miniatures de visage. Cliquez sur l'une d'elles pour filtrer la galerie.

### Galerie d'une personne

Cliquez sur le nom d'une personne pour voir toutes ses photos sur `/person/<id>`. Sur la page Gérer les personnes, un double-clic sur une carte (nommée, non nommée dans « À nommer », ou ignorée) ouvre la galerie sur les photos de cette personne ; les doubles-clics sur le champ de nom, la case et les boutons leur restent réservés.

**Nommer depuis la galerie.** Quand la galerie est filtrée sur une personne (`?person_id=95`), sa pastille dans la rangée des filtres actifs affiche son visage et son nom, ou **Sans nom**, entouré pour inciter à le nommer ; son × (**Retirer du filtre**) retire la personne du filtre. Pour les utilisateurs en mode édition, deux boutons précèdent le ×. **Renommer** (le crayon) renomme la personne sur place : le champ de nom affiche « Qui est-ce ? Saisissez ou choisissez un nom » pour une personne sans nom et « Renommer ou fusionner dans… » pour une personne nommée, ses suggestions montrent le visage, le nom et le nombre de photos de chaque personne, et **Enregistrer** ou **Annuler** le ferme (Échap annule aussi). Le nom est toujours enregistré d'abord (`POST /api/persons/{id}/rename`) ; si d'autres groupes le portent déjà (casse et espaces ignorés, qu'ils figurent ou non parmi les suggestions), la pastille propose ensuite la même fusion que la page Gérer les personnes (voir **Renommer** plus bas), et après une fusion la galerie passe à la personne conservée. **Plus** (⋮) ouvre le menu de la personne : **Voir toutes les photos de {name}**, **Trouver d'autres visages de {name}** et **Ignorer** (**Rétablir** pour une personne ignorée). Quand les options de masquage de la galerie cachent certaines photos de la personne, les avis de la galerie en donnent le nombre, réparti entre photos de rafale, de clignement, en double, de bracketing et de panorama, pour que vous les affichiez avant de nommer.

### Page Gérer les personnes

En mode édition, la page a deux onglets, **Nommées (N)** et **À nommer (N)**, et s'ouvre toujours sur **Nommées**. **À nommer** liste les clusters sans nom, chacun avec un champ de nom ; **Nommées** regroupe les personnes nommées, avec les personnes ignorées dans une section repliable **Ignorés** en bas. Les utilisateurs en lecture seule ne voient que la grille des personnes nommées. Les suggestions de nom, ici comme sur la pastille de personne de la galerie et le menu des visages de la photo, montrent le visage, le nom et le nombre de photos de chaque personne. Sur **À nommer**, le menu de tri propose **Nombre de visages** et **Plus récents**. Quand il ne reste personne à nommer, l'onglet affiche « Tout le monde est nommé. Les nouveaux visages à nommer apparaîtront ici. »

Ouvrez-la depuis le bouton de l'en-tête ou `/persons` :

| Action | Comment |
|--------|--------|
| **Fusionner** | Sélectionnez la personne source, cliquez sur la cible, confirmez |
| **Supprimer** | Cliquez sur le bouton de suppression de la carte de la personne |
| **Renommer** | Cliquez sur le nom de la personne pour le modifier sur place. Si d'autres groupes portent déjà ce nom (casse et espaces autour ignorés), une confirmation affiche une vignette par personne (visage, nom, nombre de visages), toutes sélectionnées, et marque la personne conservée : la plus grande des sélectionnées, qui garde son orthographe. Désélectionnez un homonyme, ou annulez, pour le garder à part. Une fusion ne peut pas être annulée |
| **Scinder** | Ouvrez les visages d'une personne, sélectionnez-en un sous-ensemble, scindez-le en une nouvelle personne |
| **Trouver d'autres visages** | Le bouton de recherche de la carte d'une personne, ou **Trouver d'autres visages de {name}** dans un menu de personne, liste les visages qui lui ressemblent, les plus proches en premier, comparés au centroïde de la personne (`GET /api/person/{id}/possible_faces`). Sous **Visages à inclure**, trois puces affichent chacune leur nombre : **Hors groupe** et **Groupes sans nom**, activées par défaut, et **Personnes nommées**, désactivée. Un visage qui appartient à une personne nommée porte un badge **de {name}**, et en cocher un affiche un avertissement : l'ajouter le déplace vers cette personne. Au-dessus des visages, **Groupes qui se ressemblent** liste d'autres clusters dont le centroïde ressemble à celui de la personne (ceux sans nom, plus les nommés tant que **Personnes nommées** est activée) ; chacun affiche sa photo, son nom ou **Groupe sans nom**, son nombre de visages et **{percent} % de ressemblance**, avec **Tout fusionner** pour intégrer le groupe entier à cette personne. Fusionner un groupe nommé demande confirmation, et une fusion est irréversible. Chaque visage porte **Forte** (50 % de ressemblance ou plus) ou **Possible**, avec son pourcentage, et **Degré de ressemblance** fixe le seuil : un bouton à barres de signal qui affiche `≥NN%` et ouvre le menu des niveaux, avec cinq niveaux, **Très strict** 60 %, **Strict** 50 %, **Normal** 35 % (par défaut), **Large** 25 % et **Très large** 20 %. Quand aucun visage n'atteint le seuil, la boîte de dialogue affiche « Aucun visage ne ressemble à {name} (le plus proche : N %). » et propose **Essayer Large** ou **Inclure les personnes nommées**. Quand une recherche devrait comparer trop de visages, elle cherche parmi les seuls visages hors groupe ; s'il y en a encore trop, elle demande une **Année** où chercher. **Sélectionner les fortes**, Maj+clic pour une plage et Espace sur un visage ciblé accélèrent la sélection, et le bouton Ajouter affiche combien sont cochés. L'ajout recalcule le centroïde, donc le tour suivant est classé selon ce que vous venez de confirmer ; les visages laissés décochés ne sont plus proposés tant que la boîte de dialogue reste ouverte |
| **Ignorer** | Ignorer un cluster (personnel, inconnus) : le bouton ⊘ d'une carte, aussi sur les cartes « À nommer ». Les personnes ignorées quittent la liste, « À nommer », les filtres, les suggestions de fusion et la recherche de visages, et sont listées dans la section repliable **Ignorés** en bas de l'onglet **Nommées**, avec **Rétablir** (`GET /api/persons?hidden_only=true`). Il utilise le même indicateur `is_hidden` qu'avant. Ignorer s'applique aussitôt et affiche pendant 10 secondes une notification avec **Annuler**, ici et dans chaque menu de personne. |

### Visages sur la photo

Dans la vue photo, un cadre apparaît autour de chaque visage détecté quand le pointeur survole la photo, et survoler un visage affiche son nom (cadre rouge : pas encore nommé). Les cadres suivent le zoom et le déplacement, et faire glisser ou double-cliquer sur un visage continue de déplacer la vue ou de réinitialiser le zoom. Le cadre d'un visage sans nom est en plus en pointillés, pour ne pas reposer sur la seule couleur, et chaque cadre a un contour sombre pour rester visible sur tout fond. Sauf si les cadres sont sur **Désactivé**, au clavier, Tab passe d'un visage à l'autre, chacun annoncé par son nom (ou comme visage inconnu), et Entrée ou Espace ouvre son menu. Sur un écran tactile, un appui n'ouvre le menu d'un visage que lorsque les cadres sont affichés (cadres sur **Toujours**, ou, hors **Désactivé**, visage de la personne sur laquelle la galerie est filtrée) ; sinon, toucher la photo ne fait rien au visage. En mode édition, cliquer sur un visage ouvre un menu : **Changer de personne…** (ou **Nommer ce visage…**) pour choisir une personne existante ou saisir un nouveau nom, **Trouver d'autres visages de …** pour cette personne, et **Pas …** pour détacher ce seul visage de cette personne (`POST /api/face/{id}/unassign`) ; ses autres visages sur la photo lui restent attribués. Les visages dont les dimensions enregistrées ne sont pas fiables ne sont pas dessinés. Les cadres viennent de `GET /api/photo/faces`, qui renvoie le `box` de chaque visage normalisé au cadre. Tout visage rattaché à une personne, nommée ou non, propose aussi **Voir toutes les photos de …** (ou **Voir toutes les photos de ce groupe**), qui ouvre la galerie filtrée sur cette personne ; cette action fonctionne aussi en lecture seule. Un bouton de la barre d'outils fait passer les cadres par trois états, mémorisés par navigateur : **Désactivé** (aucun cadre, et les visages ne peuvent être ni cliqués ni atteints au clavier), **Au survol** (par défaut, comme décrit ci-dessus) et **Toujours** (tous les cadres et noms restent affichés). Quand la galerie est filtrée sur une personne, ses visages restent encadrés d'un trait plus épais, sauf si les cadres sont sur **Désactivé**. **Utiliser comme photo de …** fait du visage cliqué la photo de la carte ; une personne qui reçoit des visages sans avoir de photo prend automatiquement le plus fiable. Dans la galerie filtrée sur une personne, chaque vignette entoure son visage en rouge, pour voir de quel visage parle un cluster avant de le nommer. Dans la liste **Personnes** du panneau de droite, cliquer sur l'avatar d'une personne ouvre le même menu que cliquer sur le cadre de ce visage, même quand les cadres sont sur **Désactivé** ; **Voir toutes les photos de …** dans ce menu ouvre la galerie.

### Marquer un visage non détecté

En mode édition, ouvrez une photo et choisissez **Marquer un visage manquant**, même si aucun visage n'a été détecté. Tracez un rectangle (ou saisissez ses coordonnées), choisissez une personne existante ou saisissez un nouveau nom, puis **Enregistrer**. Annuler n'enregistre rien.

Enregistrer, modifier ou supprimer un visage manuel actualise les cadres et les personnes de la photo sans la rouvrir.

- Utilisez le même éditeur pour ajuster, réassigner ou supprimer une marque manuelle.
- Les marques manuelles restent liées à leur personne à travers les rescans et la synchronisation de la visionneuse. Elles n'entraînent pas la reconnaissance et ne changent pas les scores de qualité des visages.
- L'éditeur travaille à partir de l'image originale, de sorte que les photos RAW et pivotées s'alignent. Sans l'original, vous pouvez lister et supprimer des marques, mais pas en tracer.
- Une marque qui ne peut pas être vérifiée s'affiche comme **À vérifier**. Les marques issues des premières versions de prévisualisation exigent une vérification : ouvrez l'original, modifiez et enregistrez la marque.
- Une image remplacée signale ses marques. Une retouche subtile ou un petit recadrage de même taille peut passer inaperçu. Les écritures de métadonnées, remontages de volume et autres hôtes gardent les marques à jour.
- L'éditeur réutilise une image décodée de 128 Mio au plus ; des images plus grandes peuvent nécessiter un nouveau décodage. La limite est fixe.
- Les marques supprimées restent supprimées lors des synchronisations suivantes.
- Les changements vivent dans la base de données de la bibliothèque ; les originaux et les sidecars ne sont pas touchés.

> **Avertissement :** une reconstruction forcée de la base de données de la visionneuse remplace les modifications propres à la visionneuse, marques manuelles comprises, par la base source. Exportez-les ou sauvegardez-les d'abord. La synchronisation incrémentale normale les conserve.

L'ancien réglage `viewer.performance.face_cache_size` est ignoré et peut être retiré.

## Déclenchement d'un scan

Lancez un scan depuis le navigateur. Le bouton Scan apparaît quand **les deux** conditions sont réunies :

- `viewer.features.show_scan_button` vaut `true` (livré à **`false`**).
- Vous avez l'accès scan : le rôle `superadmin` en mode multi-utilisateurs, ou une session d'édition sur une installation mono-utilisateur avec un `viewer.edition_password` non vide.

Sur une installation mono-utilisateur ouverte (`viewer.edition_password` vide, valeur par défaut), personne ne peut lancer de scan depuis le navigateur. Exception : avec `viewer.trusted_local_editing`, une session de navigateur local de confiance, ou un assistant local avec un jeton Édition complète, peut lancer un scan sans `show_scan_button` ni mot de passe d'édition.

Le bouton se trouve sur la galerie vide (**Lancer un scan pour commencer**) et à la fin de l'en-tête (**Scanner de nouvelles photos** ; barre du bas sur petits écrans). Les deux ouvrent le lanceur de scan :

- Choisissez un répertoire dans la liste et lancez le scan.
- La progression en direct et les lignes de sortie défilent dans la boîte de dialogue. La galerie se rafraîchit à la fin du scan.
- Le scan exécute `facet.py` en arrière-plan ; un seul scan à la fois.
- La liste des répertoires combine les `directories` de chaque utilisateur, les répertoires partagés, les cibles de `path_mapping` et `viewer.scan_directories`. Renseignez `viewer.scan_directories` (par ex. `/data/photos`) pour que les installations mono-utilisateur et Docker aient une cible.

Aucun GPU n'est requis — voir [Quel profil convient à mon matériel ?](INSTALLATION.md#quel-profil-correspond-à-mon-matériel) et [Pas de carte graphique](INSTALLATION.md#pas-de-carte-graphique). Le scan s'exécute sur la machine de la visionneuse, il est donc plus rapide quand celle-ci a un GPU.

Pour recalculer les scores des photos existantes sans scanner de nouveaux fichiers, utilisez `POST /api/scan/recompute` (édition uniquement) — voir [Priorité des catégories et contextes de notation](#priorité-des-catégories-et-contextes-de-notation).

## Recherche sémantique

Saisissez une requête comme « coucher de soleil sur des montagnes » et obtenez les photos correspondantes. Le classement mêle la similarité des embeddings CLIP/SigLIP (70 %) à la correspondance textuelle FTS5 BM25 sur les légendes et tags (30 %).

- **Prérequis.** Les photos doivent avoir des données `clip_embedding` stockées (calculées pendant la notation). Lancez `database.py --rebuild-fts` pour activer la partie texte légendes/tags.
- **Modèle.** Utilise le modèle d'embedding du profil VRAM actif (SigLIP 2 pour 16gb/24gb, CLIP ViT-L-14 pour legacy/8gb), ou celui de `models.clip`/`clip_legacy` qui correspond aux embeddings stockés (voir [CONFIGURATION.md](CONFIGURATION.md)).
- **Vitesse.** Installer sqlite-vec accélère la recherche ; sinon Facet garde une matrice en mémoire. La première requête sur une grande bibliothèque peut prendre plusieurs secondes.
- **Seuil.** Le seuil de correspondance vaut par défaut `models.clip.search_threshold_percent` (`5%`) ou `models.clip_legacy.search_threshold_percent` (15 %), distinct de `tag_threshold_percent`. Le curseur de la galerie couvre 0–50 % ; `search_threshold_default` de `/api/config` définit sa position de départ. Même `0%` rejette une similarité négative. Le défaut SigLIP de 5 % favorise le rappel — voir `clip.search_threshold_percent` dans [CONFIGURATION.md](CONFIGURATION.md).
- **Texte seul.** `scope=text` limite la requête aux correspondances FTS5 littérales dans le texte OCR/des légendes.
- **Fonctionne avec tous les filtres de la galerie**, bascules de masquage comprises. Avec les valeurs par défaut, les membres masqués de rafales, doublons, bracketings et panoramas, les clignements et les rejets restent masqués.
- **Aucun plafond de résultats.** La galerie pagine les résultats et affiche le vrai total.
- **Tri par pertinence.** Quand une requête est active, le tri passe par défaut à **Pertinence** (meilleure correspondance d'abord). Effacer la requête rétablit le tri par défaut.
- **Sélection.** Tout sélectionner ne couvre que les photos chargées ; la portée toute la vue n'est pas disponible ici.
- Contrôlé par `viewer.features.show_semantic_search` (par défaut : `true`).

Les résultats rapportent `similarity` (le score mêlé) et `embedding_similarity` (le cosinus brut testé par rapport au seuil, absent pour les correspondances texte seul). Les paramètres de galerie `semantic_q`, `semantic_threshold` et `sort=relevance` sont documentés dans [API.md](../API.md).

## Albums

Organisez les photos en albums nommés sur `/albums`. Contrôlé par `viewer.features.show_albums` (par défaut : `true`).

### Albums manuels

Créez des albums et ajoutez-y des photos depuis la galerie par sélection multiple. Les albums prennent en charge :
- Nom et description
- Photo de couverture personnalisée
- Ordre personnalisé
- Parcourir le contenu de l'album sur `/album/:albumId`

### Albums intelligents

Enregistrez une combinaison de filtres (appareil, tag, personne, dates, seuils de score…) comme album intelligent. Il se met à jour quand de nouvelles photos correspondent. Les filtres sont stockés en JSON dans `smart_filter_json`.

### Contexte de notation

Un album peut porter un contexte de notation qui décide quelle catégorie l'emporte pour ses photos, indépendamment de la priorité globale — voir [Contextes de notation](CONFIGURATION.md#contextes-de-notation). Définissez-le depuis la boîte de dialogue de l'album (mode édition).

- Le définir applique le contexte aux membres **actuels** de l'album. Une photo ayant son propre remplacement manuel est laissée telle quelle.
- Les membres d'un album intelligent viennent de son filtre enregistré, en ignorant les bascules de masquage de la galerie, si bien que le compte peut dépasser ce que la vue de l'album affiche.
- Les photos ajoutées plus tard à un album manuel héritent du contexte. Les nouvelles correspondances d'un album intelligent non ; redéfinissez le contexte.
- **Effacer le contexte** (différent de choisir `default`) retire l'empreinte. Une photo encore dans un autre album ayant un contexte reçoit ce contexte à la place.
- Facet peut suggérer un contexte à partir du moment narratif dominant de l'album (via le `suggest_from_moments` de chaque contexte). Il n'écrit rien tant que vous ne confirmez pas.
- Lancez un recalcul (`POST /api/scan/recompute`) pour que le nouveau contexte change les catégories stockées.

Points d'accès et compteurs de réponse : [API.md](../API.md#albums).

### Export de portfolio

Transformez un album manuel en galerie HTML statique autonome. Avec `viewer.features.show_portfolio_export` activé (`true` par défaut) et l'édition déverrouillée, chaque carte d'album manuel a **Exporter le portfolio**. Choisissez un titre, un dossier cible et si les légendes sont incluses.

- La sortie contient `index.html` (une grille de miniatures avec visionneuse intégrée, sans référence externe ni CDN, fonctionne hors ligne), un dossier `assets/` de JPEG à noms séquentiels (aucun chemin de bibliothèque ne fuit) et un `manifest.json`.
- Chaque photo utilise l'original, réduit à `portfolio.max_edge`, ou la miniature stockée de 640 px si l'original est inaccessible.
- Le dossier cible doit figurer dans la liste d'autorisation d'export (`viewer.export.allowed_target_dirs` plus les répertoires de scan, voir [Configuration — Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri)).
- Les albums de plus de `portfolio.max_photos` (500 par défaut) sont refusés.
- Réexporter ne réécrit que les fichiers propres à l'export.

Voir [Configuration de l'export de portfolio](CONFIGURATION.md#export-de-portfolio). Point d'accès : `POST /api/albums/{album_id}/export-portfolio`.

### Partage de photos

Partagez des albums par liens à jeton. Voir un album partagé ne demande aucune connexion.

| Action | Comment |
|--------|--------|
| **Partager** | Ouvrez l'album, cliquez sur le bouton « Partager » pour générer un lien partageable |
| **Révoquer** | Cliquez sur « Ne plus partager » pour invalider le jeton de partage |
| **Voir** | Les destinataires ouvrent le lien pour parcourir l'album partagé sur `/shared/album/:id` |

### Épreuvage client

Laissez un client choisir ses favorites dans une livraison. Avec `viewer.features.show_proofing` activé (`false` par défaut), un lien de partage peut fonctionner en **mode épreuvage** : le client l'ouvre, saisit un code PIN s'il est défini (`viewer.proofing.pin`), puis met des **cœurs** aux photos et laisse des **commentaires**.

- Les choix du client sont stockés à part (`album_client_picks`) et ne touchent jamais vos favoris ni vos notes, ni n'entraînent le classeur.
- Lisez les choix depuis une boîte de dialogue `[Edition]` sur la carte de l'album.
- Les sessions durent `viewer.proofing.session_minutes` (24 h par défaut) et prennent fin quand l'album n'est plus partagé ou que l'épreuvage est désactivé.

Voir [Configuration — Épreuvage client](CONFIGURATION.md#épreuvage-client).

## Critique IA

Explique le score d'une photo sous forme de points forts, de points faibles et de suggestions. Contrôlé par `viewer.features.show_critique` (par défaut : `true`).

### Critique basée sur des règles

Disponible sur tous les profils VRAM. Facet recalcule le score à partir des métriques stockées de la photo et de la configuration actuelle, et montre le calcul.

- **La catégorie** est celle que la formule actuelle attribue (en tenant compte d'un remplacement de catégorie et du contexte de notation). Elle peut différer de la catégorie stockée jusqu'au prochain `--recompute-average`.
- **Les lignes de détail** montrent chaque entrée 0–10 que le scoreur pondère (plus haut est mieux, donc bruit et plage dynamique se lisent comme de la qualité), avec poids et contribution.
- **Ajustements nets et arrondi** (bonus, multiplicateur de clignement, écrêtage, pénalités de bruit et de sursaturation, bornage) réconcilie les lignes avec le total du **Calcul actuel**, affiché à côté du **Score stocké**.
- **Conditions détectées** liste le clignement et une dominante de teint.
- La netteté, la couleur et la netteté des yeux utilisent l'instantané de percentiles du dernier `--recompute-average`. Une bibliothèque seulement scannée utilise les valeurs du scan.
- **Lignes indicatives**, affichées seulement quand calculées : forme et harmonie colorimétrique (symétrie, équilibre, entropie d'orientation des contours, complexité fractale, harmonie colorimétrique de Matsuda ; `--recompute-form`), puces de distorsion (flou de bougé, dominante colorée, suraccentuation… ; `--recompute-distortions`) et une note de teint pour les portraits (`--recompute-skin-tone`). Elles expliquent la photo mais ne changent pas l'agrégat.

Si le calcul n'est pas disponible, seul le score stocké est affiché, avec le correctif :

| Raison | Correctif |
|--------|-----|
| Schéma obsolète | `python database.py` |
| Instantané de normalisation indisponible | Réessayez, puis `python facet.py --recompute-average` |
| Métriques stockées invalides | Réanalysez avec `--force` |

La boîte de dialogue distingue aussi une photo *pas encore notée* d'une photo dont le *score stocké est inutilisable*.

### Critique VLM `[GPU]` `[16gb/24gb]`

Utilise le VLM configuré (Qwen3.5-2B ou Qwen3.5-4B) pour une critique contextuelle. Nécessite le profil 16gb ou 24gb, `viewer.features.show_vlm_critique` à `true` (la valeur par défaut) et une session d'édition pour la générer. Sans édition, seule une critique en cache est affichée et `vlm_available` vaut `false`. La boîte de dialogue génère via `POST /api/critique/vlm` (édition uniquement ; les requêtes simultanées pour une même photo partagent une seule génération) ; `GET /api/critique` ne fait que lire le cache et ne génère, ne traduit ni n'écrit jamais.

- Le prompt (`critique.vlm`) inclut le détail du score, les scores stocké et recalculé, les conditions détectées et l'EXIF.
- La réponse se lit **Observation / Évaluation / Suggestions**. Elle est mise en cache par photo (`photos.vlm_critique`), traduite lorsqu'une session d'édition l'ouvre dans la langue cible (puis enregistrée et servie telle quelle), et **Régénérer** la recalcule. Sans session d'édition, vous voyez le texte non traduit, sauf si une traduction enregistrée existe déjà.
- Elle s'exécute sur la miniature stockée, donc les fichiers RAW fonctionnent.

**Superposition visuelle « pourquoi ce score ».** Avec `viewer.features.show_saliency_overlay` activé (`true` par défaut), la boîte de dialogue de critique a **Afficher la superposition**. Elle dessine la carte de saillance BiRefNet sous forme de carte thermique (`GET /api/saliency_overlay`), plus des cadres de visages et des marqueurs d'yeux issus des points de repère stockés (`GET /api/photo/face_markers`). Les cadres sont verts pour des yeux ouverts, ambre pour un clignement. La carte thermique a la résolution de la miniature, elle est donc approximative. La bascule est masquée sur les profils qui ne peuvent pas produire de masque de saillance.

## Légendage IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenez une légende en langage naturel pour n'importe quelle photo. Une session d'édition la génère à la première demande ; elle est ensuite mise en cache dans la colonne `caption`. Modifiez les légendes dans le détail de la photo (mode édition). Une installation ouverte en lecture seule n'en génère jamais. `POST /api/caption` la génère (et la traduit) ; `GET /api/caption` ne renvoie que la légende ou la traduction enregistrée et ne génère, ne traduit ni n'écrit jamais.

Génération et traduction en masse depuis la CLI :

```bash
python facet.py --generate-captions      # Génère les légendes de toutes les photos sans légende
python facet.py --translate-captions     # Traduit les légendes vers la langue cible configurée
```

La traduction utilise MarianMT sur CPU (pas de GPU nécessaire). Définissez la langue avec `translation.target_language` (par défaut : `"fr"`). Langues prises en charge : français, allemand, espagnol, italien.

Contrôlé par `viewer.features.show_captions` (par défaut : `true`). Sans le profil 16gb/24gb ni `vlm_backend` distant, le bouton Générer une légende est masqué et les critiques restent basées sur des règles.

## Souvenirs (« Ce jour-là »)

Voyez les photos prises à la date du jour les années précédentes. Souvenirs ouvre un diaporama plein écran aléatoire.

Contrôlé par `viewer.features.show_memories` (par défaut : `true`).

## Workflows courants

- **Trier des vacances** — ouvrez Capsules et trouvez la capsule `journey` du voyage. Chaque capsule peut être enregistrée comme album.
- **Passer en revue jour par jour** — ouvrez Chronologie et descendez années → mois → jours. Cliquez sur un jour pour ouvrir la galerie filtrée sur ce jour.
- **Montrer ce qui est masqué** — la galerie masque par défaut les clignements et les rafales et doublons hors tête. Quand quelque chose est masqué, une notification « N photos masquées par les filtres actuels · Tout afficher » apparaît en bas à droite.
- **Retrouver vos filtres** — l'icône de photos de l'en-tête ramène à la galerie avec les filtres, le tri et la position que vous aviez laissés. Double-touchez-la, ou réinitialisez les filtres, pour repartir des valeurs par défaut.

## Vue Chronologie

Parcourez chronologiquement : les années descendent vers les mois, puis vers un calendrier des jours. Chaque tuile montre un nombre de photos et une photo de couverture. Cliquez sur un jour pour ouvrir la galerie filtrée sur cette date ; triez-y.

Les cinq bascules de masquage de la galerie (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`) s'appliquent, avec `viewer.defaults` pour valeurs par défaut, de sorte que les compteurs des tuiles correspondent à ce que montre la galerie. Quand quelque chose est masqué, un bouton `visibility_off` apparaît dans la barre d'outils (« Certaines photos sont masquées par vos filtres ») ; cliquez dessus pour effacer les cinq.

Ouvrez `/timeline`. Contrôlé par `viewer.features.show_timeline` (par défaut : `true`).

## Vue Carte

Voyez les photos sur une carte Leaflet interactive, regroupées selon le niveau de zoom, à partir de leurs coordonnées GPS EXIF.

### Configuration

Extrayez les coordonnées GPS des photos existantes :

```bash
python facet.py --extract-gps    # Extrait lat/lng GPS de l'EXIF vers la base de données
```

Les nouvelles photos obtiennent leurs coordonnées pendant la notation.

Ouvrez `/map`. Contrôlé par `viewer.features.show_map` (par défaut : `true`). Les fonds de carte viennent d'OpenStreetMap et nécessitent une connexion internet, même dans l'application installée.

### Lieux enregistrés et GPS manuel

**Trouver les photos sans lieu.** Dans les filtres, ouvrez **Localisation** et activez **Sans géolocalisation**. Cela peut être enregistré dans un album intelligent. Cela se désactive quand vous lancez une recherche sémantique/de similaires ou choisissez un rayon sur la carte.

**Définir le lieu d'une photo.** En mode édition, ouvrez **Ajouter une position** ou **Modifier la position** sur une photo. Cherchez dans **Lieux enregistrés**, choisissez un **Lieu récent**, placez une épingle ou saisissez des coordonnées. **Enregistrer** l'applique.

**En définir plusieurs d'un coup.** Sélectionnez des photos et choisissez **Définir le lieu** (barre de sélection, actions mobiles ou menu contextuel).

- **Uniquement les photos sans lieu** est activé par défaut ; désactivez-le pour remplacer les lieux existants.
- **Aperçu des changements de lieu** montre combien seront modifiés ou ignorés. Si quoi que ce soit change entre-temps, prévisualisez de nouveau.
- Jusqu'à 1000 photos visibles par lot, sélections de toute la vue comprises.

**Lieux enregistrés.** Choisissez un point et utilisez **Enregistrer ce lieu** avec un nom (par ex. « Travail »), ou mettez en favori le point d'une photo géolocalisée. Renommez ou supprimez depuis la liste ; cela ne déplace pas les photos déjà assignées. Chaque éditeur a une liste privée : jusqu'à 100 lieux enregistrés et 20 points récents.

**Les lieux manuels persistent.** Un lieu défini dans la visionneuse survit aux rescans et à la réextraction EXIF, y compris un lieu effacé. **Utiliser le lieu du fichier** abandonne le remplacement et relit le GPS du fichier (ou l'efface si le fichier n'en a pas).

**Écriture dans les fichiers.** L'enregistrement n'écrit jamais le fichier image. Un export de métadonnées explicite écrit les lieux manuels (et les effacements explicites) dans le sidecar XMP : dans la visionneuse ou avec `--export-sidecars`. L'intégration (**Écrire les métadonnées dans le fichier**, ou `--embed-originals`) écrit aussi le GPS EXIF dans les originaux pris en charge. Voir [INTEROP](INTEROP.md).

### Recherche en ligne de lieux

Utilisez **Adresse ou établissement → Rechercher en ligne** pour chercher un lieu avec Photon (données OpenStreetMap, © contributeurs OpenStreetMap). La requête n'est envoyée que lorsque vous cliquez sur **Rechercher en ligne** ou appuyez sur Entrée. Choisissez un résultat pour le prévisualiser, puis **Enregistrer**. Les lieux enregistrés et les coordonnées fonctionnent hors ligne.

- `viewer.place_search_url` (par défaut `https://photon.komoot.io/api`) désigne le fournisseur. Utilisez un Photon auto-hébergé, ou `""` pour désactiver la recherche.
- La démo publique n'offre aucune garantie de disponibilité. Utilisez un seul worker de visionneuse avec elle, car chaque worker a sa propre limite de débit.
- Les requêtes font de 3 à 200 points de code Unicode et renvoient jusqu'à cinq résultats en moins de cinq secondes, dans une réponse d'au plus 64 Kio. Les libellés de résultat sont plafonnés à 600 caractères Unicode.
- Un cache par processus conserve 128 recherches pendant 15 minutes. En mode multi-utilisateurs, chaque compte ne voit que ses propres entrées, mais la capacité de 128 entrées et la limitation du fournisseur sont partagées par tout le processus.
- Facet attend au moins une seconde entre deux appels au fournisseur et n'en envoie jamais deux à la fois.
- Facet ne journalise pas les requêtes. Configurez votre reverse proxy pour qu'il ne journalise pas les chaînes de requête.

## Capsules

Diaporamas thématiques regroupés par thème, lieu, personnes et période. Ouvrez `/capsules` et cliquez sur une capsule pour la lire.

### Types de capsules

Facet génère des capsules à partir de votre bibliothèque :

- **Voyage** — voyages détectés par regroupement GPS, avec des noms de destination issus du géocodage inverse (« Voyage à Rome — mars 2025 »)
- **Moments avec [Personne]** — les meilleures photos de chaque personne reconnue
- **Palette saisonnière** — photos regroupées par saison + année
- **Collection d'or** — le top 1 % par score global
- **Histoire de couleurs** — groupes visuellement proches par regroupement d'embeddings CLIP
- **Cette semaine, il y a des années** — « Ce jour-là » étendu à ±3 jours
- **Lieu** — groupes de photos géolocalisées avec noms de lieux
- **Favoris** — photos favorites regroupées par année et saison
- **Par dimension** — par appareil, objectif, catégorie, motif de composition, plage de focale, moment de la journée, note en étoiles, et leurs combinaisons

### Diaporama

Cliquez sur une carte de capsule pour lancer un diaporama :
- **Transitions thématiques** — glissement (voyages), zoom (portraits), kenburns (or/saisonnier), fondu enchaîné (par défaut)
- **Enchaînement automatique** — quand une capsule se termine, une carte présente la suivante
- **Aléatoire et reprise** — les photos sont mélangées ; votre position est conservée par capsule
- **Regroupement adaptatif** — les photos en portrait sont affichées côte à côte pour remplir l'écran
- **Enregistrer comme album** — gardez n'importe quelle capsule comme album

### Fraîcheur

Les capsules tournent selon un calendrier (par défaut : 24 heures). **Régénérer** dans l'en-tête les rafraîchit tout de suite.

### Géocodage inverse

Les capsules de lieu et de voyage affichent des noms de lieux (par ex. « Paris, France ») grâce au paquet hors ligne `reverse_geocoder`. Aucun appel d'API ; les résultats sont mis en cache dans la base de données.

Installation : `pip install reverse_geocoder`

### Configuration

Voir [Configuration — Capsules](CONFIGURATION.md#capsules) pour tous les réglages.

## Vue Dossiers

Parcourez par répertoire sur `/folders`.

- Le fil d'Ariane permet de remonter dans l'arborescence.
- Chaque dossier montre sa photo la mieux notée comme couverture.
- Cliquez sur un dossier pour l'ouvrir, ou sur une photo pour l'ouvrir dans la galerie.
- Chaque carte de dossier a une action de filtre qui ouvre la galerie restreinte à ce dossier.
- En mode multi-utilisateurs, vous ne voyez que vos répertoires.

### Filtre par dossier

La section **Dossier** de la barre latérale de filtres a **Choisir un dossier…**, un sélecteur qui parcourt l'arborescence. L'appliquer restreint la galerie à ce dossier **et à ses sous-dossiers**. Il s'affiche comme une puce, se combine avec les autres filtres, survit à un rechargement (paramètre d'URL `path_prefix`) et s'enregistre dans les albums intelligents.

Il ne réduit que la grille de photos. Les listes déroulantes de la barre latérale, les compteurs de types, les statistiques, la chronologie, la carte et la recherche restent sur toute la bibliothèque.

## Boîte de dialogue Filtre GPS

Filtrez les photos par lieu avec un sélecteur sur carte :

- Cliquez sur le bouton de filtre de localisation pour ouvrir la carte.
- Cliquez ou glissez pour définir un point central.
- Ajustez le curseur de rayon.
- Les photos dans le rayon apparaissent dans la galerie.
- Nécessite des coordonnées GPS (lancez `--extract-gps` si les photos ont des données GPS EXIF).

## Suggestions de fusion

Trouvez les groupes de personnes qui pourraient être la même personne. Ouvrez `/merge-suggestions` ou passez par la page Gérer les personnes.

- **Curseur de seuil de similarité** — plus bas montre plus de suggestions, plus haut en montre moins
- **Fusionner** — accepter une suggestion
- **Fusion par lot** — fusionner plusieurs suggestions à la fois
- Les suggestions écartées ne sont plus proposées
- CLI : `python facet.py --suggest-person-merges`

## Export vers éditeur

Écrivez notes, favoris et rejets dans des sidecars XMP pour que darktable, Lightroom et d'autres éditeurs les prennent en compte. Nécessite le mode édition.

- **Depuis la galerie** — sélectionnez des photos, puis **Actions → Exporter** écrit un sidecar à côté de chaque fichier.
- **Depuis un album** — exportez tout l'album en sidecars, ou copiez/liez symboliquement ses fichiers vers un dossier (même liste d'autorisation que [Trier vers un dossier](#trier-vers-un-dossier)). Les albums utilisent leur appartenance enregistrée, albums intelligents compris.
- **Écrire les métadonnées dans le fichier** — dans le détail de la photo, intègre la note et les mots-clés dans l'original (JPEG/HEIC/TIFF/PNG/DNG via exiftool) en plus d'écrire le sidecar. Les fichiers RAW propriétaires ne sont jamais modifiés. Contrôlé par `viewer.features.show_embed_metadata` (par défaut : `true`).
- **Lightroom** (mode édition) — **Télécharger le manifeste Lightroom** enregistre `facet_manifest.json` pour la sélection de la boîte de dialogue, pour l'étape **Facet: Apply ratings and flags...** de `facet.lrplugin`. **Importer l'état Lightroom…** lit le `facet_lightroom_state.json` du menu **Facet: Export Lightroom State to Facet...** du module externe (Lightroom gagne pour la note et le pick/rejet) et rapporte les compteurs apparié/non apparié/modifié. Aucune exécution de `--import-lightroom` n'est nécessaire. Voir [Lightroom Classic](INTEROP.md#lightroom-classic).

**Limites et progression.**

- Les exports sont plafonnés à 10 000 photos, pour les sélections, les vues filtrées et les albums. Un ensemble plus grand est refusé avant toute écriture ; restreignez les filtres et réessayez.
- Les exports s'exécutent en arrière-plan, avec progression et compteurs écrits/ignorés/erreurs. **Arrêter après le fichier actuel** annule entre deux fichiers ; les sidecars terminés restent.
- Un seul travail de bibliothèque s'exécute à la fois. Pendant un export, les scans, recalculs et réentraînements automatiques attendent ou sont refusés, et un export est refusé pendant que l'un d'eux s'exécute.
- Fermer la boîte de dialogue arrête le suivi de la progression, pas l'export.
- Rouvrez Export vers l'éditeur pour voir vos 20 exports les plus récents. **Réessayer les fichiers restants** lance un nouveau travail pour les fichiers en échec, ignorés et non traités. Un fichier interrompu en cours d'écriture peut être réécrit.

## Téléchargement

Téléchargez des photos depuis le détail de la photo ou la barre de sélection. Le menu de téléchargement par photo liste les types disponibles pour cette photo, y compris les profils darktable configurés :

- **Original** (`original`) — le fichier tel quel (JPG/HEIF), ou un RAW converti en JPEG avec le même rendu que celui de la visionneuse. Une vue de bracketing se télécharge donc sans correction d'exposition — voir [CONFIGURATION.md](CONFIGURATION.md#les-vues-dun-bracketing-saffichent-sans-correction).
- **darktable** (`darktable`) — le RAW compagnon converti avec un profil darktable nommé. Se rabat sur l'original s'il n'y a pas de RAW compagnon.
- **RAW** (`raw`) — le fichier RAW compagnon tel quel. Non disponible dans les albums partagés.

**Recadrage social tenant compte de la saillance.** Avec `viewer.features.show_social_export` activé (`true` par défaut) et l'édition déverrouillée, la barre de téléchargement du détail de la photo a un menu **Recadrage social**. Il liste `social_export.presets` (carré 1:1, portrait 4:5, story 9:16 par défaut). En choisir un télécharge un JPEG pleine résolution recadré à ce format et centré sur le sujet. Le sujet vient du cadre de sujet BiRefNet (`photos.subject_bbox`, issu de `--recompute-saliency`), sinon des visages détectés, sinon du centre. L'infobulle du menu indique lequel a été utilisé (`saliency` / `faces` / `center`).

Points d'accès : [API.md — Téléchargement](../API.md#download).

## Tri sélectif

La page de tri (`/culling`, mode édition) regroupe les prises quasi identiques pour que vous gardiez la meilleure de chacune et rejetiez les autres. Choisissez la ou les photos à garder dans chaque groupe ; confirmer rejette les autres. Les confirmations sont différées et peuvent être annulées (voir [Annuler](#annuler)).

La **granularité** (premier contrôle de la barre d'outils) choisit comment les photos sont regroupées :

- **Tout** (par défaut) — rafales et groupes de similaires fusionnés.
- **Rafales** — photos prises rapprochées dans le temps.
- **Similaires** — photos qui se ressemblent quel que soit le moment, par similarité CLIP/SigLIP. Un curseur règle la rigueur.
- **Scènes** — séquences chronologiques d'heures de prise de vue, chacune coiffée de sa plage horaire et de son moment narratif principal. Nécessite `viewer.features.show_scenes`.
- **Bracketings d'exposition** — séries trouvées par [`--detect-sequences`](COMMANDS.md), exposition de référence d'abord, chaque vue étiquetée de sa compensation (`-2 EV` … `+2 EV`).
- **Panoramas** — balayages trouvés par [`--detect-panoramas`](COMMANDS.md), dans l'ordre de prise de vue, vue centrale marquée.
- **Panoramas HDR** — balayages de panorama avec un écart d'exposition supérieur à `hdr_min_span_stops`. Une série HDR sur trépied apparaît d'abord sous **Bracketings d'exposition** et passe ici (comme `hdr_panorama`) une fois que la passe panorama reconnaît le balayage. Si elle ne le reconnaît jamais, elle reste un bracketing.

**Séries à garder entières.** Les bracketings d'exposition, panoramas et panoramas HDR ne font pas partie de **Tout**. Chaque vue commence gardée et confirmer n'enregistre aucune paire de comparaison. Le double-clic (« garder seulement celle-ci ») n'y fait rien. Ces flux ignorent les bascules `hide_*` de la galerie et montrent chaque vue. Pour écarter les expositions latérales, utilisez l'élagage des bracketings du tri automatique (ci-dessous).

Un groupe qui compte moins de 2 vues une fois les photos déjà rejetées retirées est écarté du flux.

**Tri.** Le **mode de tri** (les plus faciles d'abord, les plus redondantes, les meilleures, les plus récentes, nécessite des comparaisons, **les plus anciennes d'abord**) se trouve à côté de la granularité, avec un bouton fléché qui l'inverse. Les plus anciennes d'abord ordonne aussi les photos *à l'intérieur* de chaque groupe par heure de prise de vue, ce qui convient aux bracketings et aux panoramas.

La granularité, le tri et la catégorie persistent dans `localStorage`. Les contrôles qui ne s'appliquent pas sont masqués (ni tri ni seuil en mode scène ; pas de bouton de portée sans albums manuels). Sur petits écrans, la barre d'outils devient une barre du bas défilante.

**Mettre toutes les rejetées à la corbeille (corbeille du système).** Ce bouton de la barre d'outils prévisualise chaque photo rejetée visible pour vous dans toute la bibliothèque, vues masquées comprises. Il ignore l'album, la date et les filtres de la galerie. **Appliquer** envoie les fichiers à la corbeille du système sur la machine Facet. Contrairement à **Supprimer**, les lignes de la bibliothèque et les décisions restent, pour My Taste.

- Nécessite l'accès édition, `viewer.cull.allow_trash` et la prise en charge de la corbeille.
- Plafonné à 10 000 photos. Pour davantage, utilisez Rejetés uniquement dans la galerie, restreignez par date ou album, et utilisez Trier vers un dossier → Mettre les rejetées à la corbeille par lots. Désactivez les filtres qui masquent des groupes pour inclure chaque vue rejetée.
- Les fichiers RAW/XMP compagnons sont optionnels.
- Si les fichiers résolus, les options ou la destination ont changé depuis l'aperçu, Appliquer est refusé ; prévisualisez de nouveau. La vérification compare les noms de fichiers et les réglages, pas le contenu des fichiers, et ne verrouille pas les fichiers.
- Un échec du système de fichiers en cours de route laisse à la corbeille les fichiers déjà traités ; la boîte de dialogue reste ouverte pour un nouvel aperçu.
- Dans les conteneurs, la corbeille et la récupération dépendent du système de fichiers du serveur.

> **Avertissement :** sur une bibliothèque partagée, Mettre toutes les rejetées à la corbeille n'utilise que *vos* rejets. Elle met à la corbeille les fichiers partagés même si un autre utilisateur les a gardés, mis en favori ou notés. Vérifiez l'aperçu.

**Tri limité à un périmètre.** Restreignez la chambre noire avec des paramètres d'URL : `?group_by=scene` pour les scènes, `?album=<id>` pour un album, `?from=&to=` pour une fenêtre d'heures de prise de vue (texte EXIF ou dates ISO comme `2026-06-01`). Une bannière montre le périmètre avec **Quitter la scène**. Les rafales qui franchissent le bord de la fenêtre montrent quand même toutes leurs vues.

**Plage de dates.** Le bouton **plage de dates** (icône `date_range`) propose **7 derniers jours**, **30 derniers jours**, **Cette année**, **Année dernière**, **Plage personnalisée...** et **Toutes les dates**. Les dates s'affichent en jj/MM/aaaa.

- Elle se combine avec la portée d'album. Les photos sans date de prise de vue sortent d'une plage datée.
- Les préréglages se résolvent au moment du choix, donc un « 7 derniers jours » mis en signet est une fenêtre fixe.
- La plage ne vit que dans l'URL (`?from=2026-07-01&to=2026-07-31`), pas dans `localStorage`.
- La changer recharge le flux : une confirmation en attente est validée, les sélections et sauts non confirmés sont abandonnés.

**Ligne My Taste.** Chaque confirmation enregistre des comparaisons `source='culling'` qui entraînent le classeur personnel. La boîte de dialogue Aide (menu utilisateur → Aide) affiche « My Taste · N comparaisons » (`GET /api/ranker/status`) et liste les raccourcis du tri.

**Profils par genre.** Le sélecteur **Profil** applique un préréglage de genre qui fixe d'un coup la rigueur, le budget de photos conservées, le seuil de similarité et les seuils de visage yeux fermés / mauvaise expression. Le sport ne garde que la plus nette d'une rafale, les mariages gardent davantage de variantes yeux ouverts, les concerts et la faune assouplissent les barrières de visage. Le choix et le curseur de rigueur persistent dans `localStorage`. Modifier un réglage à la main affiche « Personnalisé ». Les préréglages vivent dans [`cull_profiles`](CONFIGURATION.md#profils-de-tri-par-genre) (`GET /api/culling/profiles`).

### Tri automatique

**Tri automatique** dans la barre d'outils trie tout un périmètre en une passe.

1. Choisissez le périmètre : tous les groupes, ou seulement rafales / similaires / scènes, éventuellement un album ou une fenêtre de dates.
2. Réglez la **rigueur** (plus haut garde moins de photos par groupe).
3. Prévisualisez. Chaque groupe garde sa meilleure photo plus tout ce qui se trouve dans la marge de rigueur (au moins un minimum par groupe), et rejette le reste.
4. Confirmez. Les rejets sont enregistrés, les photos conservées sont marquées **Conservées**, et My Taste en apprend.

- L'aperçu est une **simulation** : rien n'est écrit.
- Un album **Coups de cœur** facultatif rassemble la meilleure photo de chaque groupe dont le score atteint au moins `auto_cull.highlights_min`.
- Un badge « meilleure photo dans ce groupe » signale les groupes où le tri automatique garderait une autre vue que la tête actuelle.
- Quand une tête de classement des photos à conserver est entraînée et passe son seuil de précision, elle choisit la photo à garder (`keeper_prob`). Sinon l'heuristique habituelle le fait.
- Le bouton est masqué dans les granularités à garder entières. Dans un périmètre mixte, les bracketings sont décidés en premier.
- Configurez avec le bloc [`auto_cull`](CONFIGURATION.md#tri-automatique) (`POST /api/culling/auto`). Lancez-le depuis le terminal avec `python facet.py --auto-cull` — voir [Tri en ligne de commande](COMMANDS.md#tri-en-ligne-de-commande).

**L'élagage des bracketings redondants** (`trim_brackets`, désactivé par défaut) est la seule façon dont le tri automatique réduit jamais une série. Quand l'exposition de référence d'un bracketing n'écrête ni les ombres ni les hautes lumières, les vues latérales n'apportent rien, donc seule la vue de référence est gardée. Les séries dont l'écrêtage de référence n'a jamais été mesuré sont laissées telles quelles.

### Mode plan de l'assistant

Quand un assistant connecté via [Agents IA (MCP)](AGENTS.md) prévisualise un tri automatique (`auto_cull`, ou `ui_show_culling_plan`), votre onglet ouvert charge ce plan sur `/culling`. C'est la chambre noire normale (loupe `Z`, comparaison 2 / 4 vues, focus peaking), avec les photos à garder du plan présélectionnées.

- Une bannière indique **Plan de l'assistant · x/y confirmés · Quitter**.
- Chaque groupe a une puce comme **#3 · raison · garder 2 / rejeter 1 suggérés**. Une puce d'en-tête bleue est la note de l'assistant sur le groupe.
- Un point sur une vue signifie que vous l'avez modifiée par rapport au plan.
- Un badge en pointillés **Assistant : garder** / **Assistant : rejeter** est la suggestion de l'assistant, avec sa raison dans l'infobulle. Cliquez dessus (ou Entrée/Espace) pour l'appliquer ; vous confirmez toujours le groupe.
- Confirmez groupe par groupe comme d'habitude, avec le compte à rebours et **Annuler**. Les confirmations en mode plan n'ajoutent jamais à un album de coups de cœur.
- Un groupe de rafale ou de similaires confirmé quitte le plan. Un groupe de scène confirmé n'est pas enregistré, donc l'aperçu suivant peut le proposer à nouveau.
- Confirmer une rafale ne rejette que les membres affichés ; les membres hors de l'album ou de la fenêtre de dates ne sont pas touchés.
- Le tri et le seuil sont verrouillés. Déplacer le curseur de rigueur ou changer la **plage de dates** replanifie ; vos inversions et groupes confirmés sont conservés. **Toutes les dates** peut atteindre le plafond du plan (`plan_truncated`).
- **Quitter**, ou changer le regroupement, le périmètre ou le tri, sort du mode plan. Quitter `/culling` et revenir le restaure ; recharger l'abandonne.
- Si la bibliothèque a changé depuis l'aperçu, une notification indique que le plan est périmé. Les groupes trop volumineux sont écartés et comptés dans une notification.

L'assistant lit votre progression avec `ui_get_context` (`culling` : groupes confirmés, en attente et modifiés) et n'applique rien depuis l'onglet lui-même. Voir [Mode plan sur `/culling`](AGENTS.md#les-résultats-saffichent-dans-votre-onglet).

### Plein écran

Appuyez sur **`F`** (ou la bascule de l'en-tête) pour trier en plein écran sans interface. Appuyez sur `F` ou `Échap` pour quitter.

Appuyez sur **`S`** (ou le bouton de pile de l'en-tête) pour empiler le groupe ouvert avec la vue ciblée comme couverture. Les décisions ne sont pas touchées et Annuler est proposé. Non proposé pour les groupes contenant des vues de bracketing ou de panorama, ou une photo déjà dans une pile.

### Loupe / zoom touche Z

Appuyez sur **`Z`** en vue simple pour basculer une loupe (ajusté ↔ 2× ; molette ou `+`/`-` jusqu'à 800 %). Au-delà de l'ajustement, le volet charge le `/image` pleine résolution, pour que vous jugiez la netteté sur les vrais pixels. Les miniatures font 640 px et la vue ajustée est un rendu jusqu'à 1920 px ; la loupe va au-delà.

- Sur la bande de contacts des Scènes, `Z` bascule une loupe au survol avec un curseur de zoom.
- Les volets montrent d'abord la miniature stockée, puis passent au rendu net. Les vues suivante et précédente sont préchargées (sauf avec l'économiseur de données).
- Un rendu qui ne peut pas démarrer en 5 s est remplacé par la miniature pendant 60 secondes.

**Loupe au survol de la chambre noire.** Une loupe ronde suit le curseur sur la vue principale, chaque volet de comparaison et les gros plans de visages, en montrant des pixels pleine résolution. Une bascule de la barre d'outils l'active ou la désactive (activée par défaut, enregistrée par navigateur). Elle se met en pause quand la vue est zoomée au-delà de l'ajustement, fonctionne en plein écran et suit `←`/`→`.

### Badges par visage

Dans la visionneuse du tri, chaque visage porte ses propres badges : yeux ouverts/fermés, mauvaise expression et confiance de détection. Vous voyez quel visage d'une photo de groupe a les yeux fermés. Récupérés par groupe avec `POST /api/culling-group/faces`.

**Panneau des visages.** Les vignettes de visages sont colorées en vert / orange / rouge d'après leurs scores d'yeux ouverts et de sourire.

- Les curseurs **Yeux** et **Sourire** règlent ce qui compte comme clignement ou expression faible. Ils partent de `face_detection.eyes_closed_max` et `face_detection.poor_expression_min` (tous deux `4.0` par défaut).
- **Taille** (64–256 px, par pas de 16, `112px` par défaut) redimensionne les vignettes. Les valeurs des curseurs sont enregistrées par navigateur.
- Après avoir utilisé un curseur à la souris, les touches fléchées reviennent à la chambre noire (`←`/`→` vue, `↑`/`↓` garder/rejeter). Passez à un curseur avec Tab pour l'ajuster au clavier.

**Bande de gros plans du sujet (groupes sans visage).** Pour les groupes sans visages significatifs (faune, macro, produits), la chambre noire montre côte à côte le sujet principal de chaque vue, recadré d'après le cadre de sujet BiRefNet. Chaque recadrage a un badge de netteté (10 = la plus nette du groupe) et un anneau vert / ambre / rouge. Cliquez sur un recadrage pour aller à cette photo. Aucun modèle ne s'exécute (`POST /api/culling-group/subjects`). Pour une bibliothèque existante, lancez d'abord `python facet.py --recompute-saliency` (GPU) ; d'ici là la bande n'apparaît pas.

**Sujet clé (cible du zoom + personne clé).** Zoomer (**`Z`**, double-clic ou premier cran de molette) se place sur le sujet clé de la vue plutôt que sur le centre : son meilleur visage, ou le cadre du sujet s'il n'en a pas. Dès que vous déplacez ou zoomez une vue vous-même, Facet cesse de la recadrer. Une personne nommée qui l'emporte reçoit une pastille de nom ambre dans la bande des visages. Les personnes nommées à mi-distance l'emportent sur de plus grands inconnus ; un minuscule visage d'arrière-plan ne gagne pas. Rien n'est stocké. Les cadres sont des fractions de l'image entière (`normalized_frame_xyxy`). Points d'accès : `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Comparaison synchronisée (2 / 4 vues).** Les boutons Simple / Comparer 2 / Comparer 4 de l'en-tête changent de vue. En mode comparaison, tous les volets partagent un même panoramique/zoom, vous comparez donc exactement le même recadrage. Un double-clic bascule ajusté ↔ zoom. À l'ajustement, chaque volet montre `/thumbnail?size=1920` ; zoomé, il charge le `/image` pleine résolution. Le pincement tactile n'est pas encore branché ; utilisez la molette de la souris.

**Glisser pour garder ou rejeter (tactile).** Sur un appareil tactile, glissez la vue vers la droite pour garder ou vers la gauche pour rejeter. Elle s'incline et se teinte de vert (GARDER) ou de rouge (REJETER).

- Au-delà de 35 % de la largeur (au moins 48 px), relâcher valide la même décision que `↑` / `↓` et passe à la vue suivante. En deçà, elle revient en place.
- Un glissement vertical est ignoré.
- Chaque glissement affiche **Annuler**, qui restaure la décision et revient à cette vue.
- Uniquement en vue simple, à l'échelle ajustée, avec un doigt ou un stylet. Une indication d'une ligne s'affiche jusqu'à ce qu'elle soit fermée.

**Aperçu du rendu édité.** En vue simple, le menu **palette** liste « Original » plus chaque style darktable configuré, pour que vous triiez sur le rendu développé.

- Facet rend l'original via darktable-cli (`--style`, borné à `preview_max_edge`). En cas d'échec, il revient à Original.
- Le style reste pour le groupe courant et se réinitialise quand vous rouvrez la chambre noire.
- Affiché seulement quand un style est configuré **et** que darktable-cli est trouvé. Les styles doivent exister dans la configuration darktable de l'utilisateur qui exécute la visionneuse.
- Les rendus sont mis en cache sur disque.
- Point d'accès : `GET /api/photo/cull_preview?path=&style=` (édition). Configurez via [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#décodage-raw).

## Vue Scènes

Une vue en **lecture seule** de la bibliothèque sous forme de scènes chronologiques, dans l'ordre de l'histoire avec des en-têtes de date/moment et une loupe au survol. Ouverte à **tous les utilisateurs authentifiés**.

- Une nouvelle scène commence quand plus de `scenes.gap_minutes` s'écoulent entre deux prises (élargi sur les prises clairsemées). Les séquences très longues sont scindées.
- Ouvrez-la depuis l'action **Afficher les scènes de cet album** d'un album dans la grille des Albums ; un sélecteur change d'album. Il n'y a pas d'entrée Scènes dans la navigation principale.
- Chaque scène a un bouton **Trier cette scène** réservé à l'édition, qui ouvre le [Tri sélectif](#tri-sélectif) sur cette scène (`/culling?group_by=scene&album=&from=&to=`).
- Quand les moments narratifs sont calculés, chaque scène est titrée d'après son moment principal, et `scenes.split_on_moment_change` peut scinder une séquence là où le moment change.
- Les scènes plus petites que `scenes.min_size` sont omises ; au plus `scenes.max_photos` photos se chargent.

Contrôlé par `viewer.features.show_scenes` (par défaut : `true`). Voir [Configuration — Scènes](CONFIGURATION.md#scènes) pour `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` et `adaptive_k`.

## Moments narratifs

Facet étiquette chaque photo avec l'activité qu'elle montre. Le vocabulaire **général** par défaut : fête, repas, plage, activité nautique, montagne, nature et faune, paysage urbain, site touristique, concert, sport, rassemblement, portrait, enfants, animaux de compagnie, vie nocturne, cérémonie, paysage, neige et hiver, intérieur, route et véhicule, ou `other`. Un vocabulaire `wedding` est disponible en option de genre.

- Il s'exécute localement, sans passe de modèle supplémentaire : la légende IA de chaque photo est comparée aux prompts textuels de chaque moment (l'embedding de l'image est utilisé quand il n'y a pas de légende). Un lissage temporel corrige les erreurs de lecture isolées.
- Un arbitre VLM facultatif (16gb/24gb) revérifie les images à faible confiance.
- Il **s'exécute automatiquement à la fin de chaque scan**. La première passe sur une bibliothèque existante encode chaque légende (GPU recommandé). Ré-étiquetez tout avec `python facet.py --recompute-moments`.
- Les moments apparaissent comme titres de scènes et comme filtre de galerie (`GET /api/photos?narrative_moment=beach`, options depuis `GET /api/filter_options/narrative_moments`).
- Le vocabulaire est configurable — voir [Configuration — Moments narratifs](CONFIGURATION.md#moments-narratifs).

**Confiance du moment.** Chaque étiquette a une confiance (`narrative_moment_confidence`). Les étiquettes en dessous de `viewer.moment_confidence_min` (par défaut `0` = jamais atténué) apparaissent atténuées avec « (incertain) » dans les en-têtes des Scènes et du Tri et dans l'infobulle. La confiance est aussi un tri (**Confiance du moment**, sous Contenu) et un filtre de plage 0–1 (`min_moment_confidence` / `max_moment_confidence`, section **Moments** de la barre latérale).

## Nettoyage des indésirables

Une file de revue rapide pour les captures d'écran, documents numérisés, reçus, mèmes et diapositives. Lancez `python facet.py --detect-junk` (il s'exécute aussi après chaque scan) pour remplir `junk_kind`. Voir [Configuration — Nettoyage des indésirables](CONFIGURATION.md#nettoyage-des-indésirables).

Ouvrez **Nettoyage** dans la navigation (`/junk`, édition uniquement) :

- **Puces de filtre par type** — « Tous les types » plus une puce par type avec son compte (`GET /api/filter_options/junk_kinds`).
- **Nombre de candidates** — décroît au fil de vos décisions.
- **Conserver** — retire la photo de la file **définitivement** (`not_junk`) ; les exécutions ultérieures de `--detect-junk` l'ignorent.
- **Rejeter** — marque la photo rejetée (rien n'est supprimé).
- **Tout rejeter** — rejette chaque candidate chargée, après confirmation.
- **Loupe** — appuyez sur **`Z`** (ou la bascule de la barre d'outils) pour agrandir un texte fin.

Les photos indésirables restent visibles dans la galerie normale. Filtrez-les avec `?junk_kind=<kind>` ou `?junk_kind=any` (exclut `not_junk`).

Contrôlé par `viewer.features.show_junk_sweep` (par défaut : `true`).

## Mode de comparaison par paires

Classez les photos en en jugeant deux à la fois ; les votes alimentent le réglage des poids. Ouvrez `/compare` (bouton Comparer dans l'en-tête). Nécessite un `edition_password` non vide (mono-utilisateur) ou le rôle `admin`/`superadmin` (multi-utilisateurs).

### Onglet Comparaison A/B

Choisissez un gagnant, marquez une égalité ou passez. Une barre de progression compte jusqu'à 50 votes, avec les totaux A gagne/B gagne/égalité. Un filtre de catégorie délimite la session ; une liste déroulante de stratégie choisit les paires :

| Stratégie | Description |
|----------|-------------|
| `learning` | Par défaut. D'abord des paires variées, puis les paires sur lesquelles le classeur personnel est le plus en désaccord (les plus informatives) |
| `uncertainty` | Photos aux scores proches (les plus informatives) |
| `boundary` | Plage de score 6–8 (zone ambiguë) |
| `active` | Photos ayant le moins de comparaisons (garantit la couverture) |
| `random` | Paires aléatoires (référence) |

**Raccourcis clavier :**

| Touche | Action |
|-----|--------|
| `A` | La photo de gauche gagne |
| `B` | La photo de droite gagne |
| `T` | Égalité |
| `S` | Passer la paire |
| `Escape` | Fermer la fenêtre de remplacement de catégorie |

### Onglet Suggestions de poids

Compare les poids appris de vos votes avec les poids actuels, avec la précision du modèle avant/après et les 10 meilleures photos maintenant vs. après recalcul.

- **Appliquer** écrit les poids suggérés ; **Recalculer** recalcule les scores de la catégorie (tous deux en mode édition).
- **Appliquer** n'apparaît que lorsque la suggestion bat les poids actuels sur des comparaisons écartées (`suggest_changes`, le même test que `--optimize-weights`, voir [COMMANDS.md](COMMANDS.md)).
- Contrairement à `--optimize-weights`, **Appliquer** ne recentre pas le bonus de la catégorie, donc son score moyen peut bouger.

### Onglet Poids

Un curseur par métrique pour la catégorie sélectionnée, avec aperçu du score en direct. **Enregistrer** écrit `scoring_config.json` (avec une sauvegarde) ; **Recalculer les scores** l'applique ; **Réinitialiser** recharge les poids stockés.

### Onglet Instantanés

Enregistrez les poids actuels comme instantané nommé et restaurez n'importe quel instantané antérieur. Un instantané restaure aussi le bonus de la catégorie (`modifiers.bonus`). Les instantanés antérieurs à la 1.21, issus de `calibrate.py`, ou pour `others` n'ont pas de bonus et le laissent inchangé.

### Priorité des catégories et contextes de notation

Les catégories sont examinées par ordre de `priority` croissante ; la première qui correspond l'emporte. Voir [Évaluation des filtres](SCORING.md#fonctionnement-du-scoring) et [Contextes de notation](CONFIGURATION.md#contextes-de-notation). Deux outils réservés à l'édition modifient cela sans éditer `scoring_config.json` :

- **Priorité globale** — réordonnez l'ordre d'évaluation de base.
- **Contextes de notation** — préréglages (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) qui promeuvent certaines catégories et en excluent d'autres, sans changer l'ordre global. Modifiez tout préréglage autre que `default` dans l'onglet **Contexte de notation** : glissez (ou montez/descendez) les catégories promues, basculez les exclusions, enregistrez. Une catégorie listée dans les deux l'emporte comme exclue. `label_key` et `suggest_from_moments` ne sont pas modifiables ici. Assignez un contexte par album (voir [Contexte de notation](#contexte-de-notation)) ou par photo (ci-dessous).

Aucun des deux ne recalcule les scores par lui-même. Ensuite, lancez un recalcul (`POST /api/scan/recompute`) et surveillez `GET /api/scan/recompute_status`. Un scan ou un recalcul déjà en cours depuis un terminal bloque un nouveau lancement depuis la visionneuse. Avec `normalization.per_category` activé, un recalcul peut ne pas converger complètement — voir [Normalisation](CONFIGURATION.md#normalisation) et [Réordonner la priorité globale](CONFIGURATION.md#réorganiser-la-priorité-globale).

**Collisions de catégories** (`GET /api/stats/categories/overlap`) montre quelle catégorie de priorité supérieure capte les photos d'une catégorie. Par catégorie, il liste **Assignées**, **Correspond aux filtres** (si évaluée seule) et **Captées par une priorité supérieure** (`matched - assigned`, plancher à 0). **Principales paires en collision** classe les catégories par photos partagées. Le fourre-tout `default` est exclu, puisqu'il correspond à tout.

### Remplacement de catégorie

Réassignez la catégorie d'une photo depuis la vue de comparaison : modifiez le badge de catégorie, choisissez une catégorie, lancez « Analyser les conflits de filtres » pour voir quels filtres l'excluent, puis appliquez. Le remplacement est persistant : il survit aux recalculs jusqu'à ce que vous l'effaciez (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

La visionneuse de la photo a les mêmes actions sous **Définir la catégorie de notation…** / **Effacer le remplacement** (édition uniquement). Le chevron de la puce de catégorie ouvre **pourquoi n'est-ce pas une autre catégorie ?** : choisissez une catégorie et il liste les filtres qui excluent la photo et ce que chacun exigerait, par ex. *« Augmentez shutter_speed_max de 0.02 à 0.033 »*. Cela montre quand une catégorie est inatteignable pour une photo, ce qu'un réordonnancement ne peut pas corriger (`POST /api/comparison/suggest_filters`).

## Statistiques EXIF

La page Stats (`/stats`) a 5 onglets. Les sélecteurs de **catégorie** et de **plage de dates** filtrent chaque graphique. En mode multi-utilisateurs, chaque utilisateur voit les statistiques de ses propres photos visibles.

### Onglets

| Onglet | Description |
|-----|-------------|
| **Équipement** | Boîtiers, objectifs et combinaisons (top 20 chacun) |
| **Paramètres de prise de vue** | Distributions d'ISO, d'ouverture, de focale, de vitesse d'obturation |
| **Chronologie** | Photos dans le temps |
| **Catégories** | Analyses par catégorie, gestion des poids et corrélations de scores |
| **Corrélations** | Graphiques de corrélation X/Y personnalisés avec regroupement |

### Onglet Catégories

Quatre sous-onglets :

| Sous-onglet | Description |
|---------|-------------|
| **Répartition** | Nombre de photos par catégorie, scores moyens, histogrammes de distribution des scores |
| **Poids** | Comparaison par graphique radar (jusqu'à 5 catégories), carte thermique des poids et éditeur de poids (mode édition) |
| **Corrélations** | Carte thermique de corrélation de Pearson montrant comment chaque dimension influence l'agrégat, vue détaillée au clic |
| **Chevauchement** | Analyse du chevauchement des filtres montrant quelles catégories partagent des photos correspondantes |

Chaque graphique a un bouton `?` qui explique comment le lire ; une bascule dans la barre des sous-onglets affiche toutes les explications.

### Éditeur de poids (mode édition)

Dans le sous-onglet Poids, avec le mode édition activé :

1. Sélectionnez une catégorie dans la liste déroulante
2. Ajustez les curseurs de poids (un par métrique, la somme devrait être de 100 %)
3. Utilisez « Normaliser à 100 » pour équilibrer automatiquement
4. Développez la section Modificateurs pour ajuster les bonus/pénalités
5. L'**Aperçu de la distribution des scores** montre un histogramme avant/après en direct
6. Cliquez sur **Enregistrer** pour mettre à jour `scoring_config.json` (crée une sauvegarde horodatée)
7. Cliquez sur **Recalculer les scores** (apparaît après l'enregistrement) pour appliquer les poids à cette catégorie

## Raccourcis clavier (galerie)

Les raccourcis à touche unique sont inactifs quand le focus est dans un champ de texte, un menu ou une liste.

| Touche | Action |
|-----|--------|
| `←` `→` `↑` `↓` | Déplace le repère de photo courante entre les cartes (colonnes de la grille et rangées de la mosaïque) |
| `Enter` | Ouvre la photo ciblée |
| `Space` | Sélectionne / désélectionne la photo ciblée |
| `Ctrl+A` / `Cmd+A` | Tout sélectionner — toute la vue filtrée à partir d'une sélection vide, sinon les photos chargées |
| `Escape` | Efface la sélection (en mode panneau latéral, libère aussi la photo retenue) / ferme le tiroir de filtres |
| `Shift+Click` | Sélectionne une plage de photos entre la dernière sélectionnée et celle cliquée |
| `Double-click` | Ouvre la photo |
| `Shift+F10` / `Menu` | Ouvre le menu contextuel de la carte de photo ciblée (le clic droit fait de même) |
| `1`–`5` | Note la photo ciblée de 1 à 5 étoiles (mode édition ; passe automatiquement à la photo suivante) |
| `K` | Garde la photo ciblée (mode édition) |
| `F` | Met en favori / retire des favoris la photo ciblée (mode édition) |
| `X` ou `0` | Rejette / annule le rejet de la photo ciblée (mode édition ; passe automatiquement à la suivante) |
| `/` | Met le focus sur la recherche de la barre d'outils (affichée à partir de 1360 px de large) ; plus étroit, ouvre la recherche de la barre latérale de filtres |
| `S` | Ouvre l'éditeur de piles pour la sélection explicite (mode édition ; réassignable, peut rester non assignée) |
| `Ctrl+Maj+S` / `Cmd+Maj+S` | Empile aussitôt la sélection explicite non empilée dans l’ordre de sélection, la première photo servant de couverture (mode édition ; les membres de piles existantes ouvrent l’éditeur) |
| `B` | Affiche / masque la barre latérale de filtres |
| `V` | Bascule entre la disposition grille et mosaïque |
| `?` | Affiche la référence des raccourcis clavier (sur chaque page ; aussi dans menu utilisateur → Aide) |

**Réassigner les touches.** `K`, `F`, `X`, `/`, `B`, `V` et `S` sont les valeurs par défaut. Menu utilisateur → **Personnaliser les raccourcis** vous permet de cliquer sur une action et d'appuyer sur une nouvelle touche (`Esc` ou `Tab` annule). Les chiffres, `Space` et `?` sont réservés, et une touche déjà utilisée est refusée. **Tout réinitialiser** restaure les valeurs par défaut. L'association est enregistrée par navigateur (`localStorage`). La page de photo utilise les mêmes touches, et la référence `?` montre toujours les touches en vigueur.

**Photo courante.** La photo sur laquelle agissent les touches de note, de favori et de rejet a un contour de 4 px ; les autres cartes sont atténuées à 50 %. Rien n'est marqué tant que vous ne vous placez pas sur une photo. Cliquer sur une photo y déplace le repère. Revenir d'une photo laisse le repère sur la dernière consultée. L'indication de carte ciblée n'apparaît qu'en mode édition avec `viewer.features.show_rating_controls` activé.

**Sur la page de photo**, `1`–`5`, la touche de favori et la touche de rejet (`F` et `X` par défaut ; `0` rejette aussi) agissent sur la photo ouverte, en mode édition avec `viewer.features.show_rating_controls` activé. Elles n'avancent pas ; utilisez `←` `→`. La référence `?` les liste sous *Vue photo*.

## Annuler

Les changements groupés de favori/rejet/note et les confirmations de tri affichent une barre de notification avec **Annuler** pendant environ 7 secondes.

- Les changements groupés d'indicateurs s'appliquent aussitôt et s'annulent en les inversant (jusqu'à 500 photos).
- Les confirmations de tri sont différées : le groupe disparaît aussitôt, mais rien n'est enregistré avant la fin de la fenêtre d'annulation.
- Les modifications de [tags manuels](#tags-manuels) ne sont pas annulables.

Pour des changements plus anciens, voir l'[Historique des modifications](#historique-des-modifications).

## Application web progressive

Les builds de production peuvent être installées sur l'écran d'accueil. La coque de l'application se charge hors ligne, et jusqu'à 1000 miniatures sont mises en cache pendant 7 jours (les tailles plus grandes, comme les rendus 1920 px de la chambre noire, reposent sur le cache du navigateur). Les réponses de l'API ne sont jamais mises en cache, sauf les paquets de traduction. Une barre de notification propose un rechargement quand une nouvelle version est déployée.

> **Avertissement :** la déconnexion vide le cache de miniatures de l'application mais pas le cache HTTP du navigateur, qui peut conserver les images consultées (miniatures, rendus, images pleine résolution) jusqu'à un an. Les comptes qui ne doivent pas voir les photos les uns des autres ne devraient pas partager un profil de navigateur.

## Mobile

Sur petits écrans, la carte de sélection flottante garde le compteur et les boutons effacer, tout sélectionner et inverser, plus un bouton **Actions**. Il ouvre une feuille du bas avec toutes les opérations groupées (favori, rejet, note, albums, copie, téléchargement). Un bouton de comparaison apparaît quand la sélection tient dans la vue de comparaison.

## Cadre photo / Kiosque

Les cadres photo connectés, les tableaux de bord Home Assistant et les affichages de type ImmichFrame / Immich-Kiosk peuvent récupérer vos meilleures prises sans connexion. Il n'y a **aucune interface client** : les appareils appellent les points d'accès avec un **jeton de cadre** de longue durée issu du bloc de configuration `frame`. Avec `frame.tokens` vide (la valeur par défaut), la fonctionnalité est désactivée et chaque point d'accès renvoie 404.

- **Ce qui est affiché.** Les photos viennent de toute la bibliothèque, pas des dossiers d'un seul utilisateur. Les photos rejetées, indésirables et avec clignement sont exclues. `frame.min_aggregate` (7.0 par défaut) fixe le plancher de score ; `frame.favorites_only` et `frame.categories` restreignent davantage.
- **Variété.** Les photos sont un échantillon aléatoire pondéré par le score, pour que vous voyiez de bonnes prises différentes plutôt que toujours les mêmes.
- **Aucun chemin de fichier.** Chaque photo est adressée par un identifiant signé opaque, si bien qu'un détenteur de jeton ne peut pas savoir où se trouvent vos fichiers ni parcourir d'autres lignes.

| Point d'accès | Renvoie | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` plafonné à `frame.max_count` (100 par défaut), vaut par défaut `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | le JPEG de la photo — original réduit à `max_edge` (plafonné par `frame.max_edge`, 1920 par défaut), ou la miniature stockée si l'original est inaccessible | immuable longue durée |
| `GET /api/frame/next?token=` | un JPEG sélectionné au hasard, différent à chaque appel — pour les cadres simples et Home Assistant | `no-store` |

### Générer un jeton

Un jeton est n'importe quelle chaîne de votre choix. Utilisez-en une longue et aléatoire et traitez-la comme un mot de passe :

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Ajoutez-le à `frame.tokens` dans `scoring_config.json`. Listez-en un par appareil ; retirez-en un pour le révoquer :

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Recette Home Assistant

`/api/frame/next` fonctionne comme [caméra générique](https://www.home-assistant.io/integrations/generic/) Home Assistant ; chaque rafraîchissement tire une nouvelle prise :

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # rafraîchit toutes les ~20 s
```

Ajoutez la caméra à une carte Picture Glance / Picture Entity pour obtenir un cadre photo qui se met à jour tout seul.

Pour un client de type **ImmichFrame** qui gère son propre diaporama, interrogez `GET /api/frame/photos?token=…&count=30` pour obtenir les identifiants, puis récupérez chacun avec `GET /api/frame/image/{id}?token=…&max_edge=1920`. Les identifiants sont stables et les images sont mises en cache longtemps, donc chaque photo n'est téléchargée qu'une fois.

## Envoi automatique depuis le téléphone

Poussez les photos de votre téléphone vers Facet. Un petit serveur **WebDAV** sur `/dav` permet à PhotoSync (ou à tout client WebDAV) d'envoyer vers un **répertoire de dépôt**. Placez ce dépôt dans un répertoire scanné et lancez `facet.py --watch` dessus : chaque photo est notée dès son arrivée.

- **Identifiants séparés.** L'accès utilise HTTP Basic avec un identifiant d'appareil partagé du bloc `upload` (`upload.username` / `upload.password`), pas un compte utilisateur.
- **Désactivé par défaut.** `/dav` renvoie **404** tant que `upload.username`, `upload.password` et `upload.inbox_dir` ne sont pas tous définis.
- **Confiné au dépôt.** Rien en dehors de `upload.inbox_dir` n'est accessible. Les fichiers sont plafonnés à `upload.max_file_mb` (500 par défaut).
- **Méthodes :** `OPTIONS`, `PROPFIND` (profondeur 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` ne sont pas implémentées ; les applications d'envoi fonctionnent sans.

### Configuration

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Gardez `inbox_dir` sous un répertoire scanné pour que `--watch` voie les envois :

```bash
python facet.py /photos --watch
```

### Recette PhotoSync

1. Dans PhotoSync, ajoutez une configuration **WebDAV** (Configurer → Ajouter une configuration → WebDAV).
2. **URL / Serveur** : `http://<host>:5000/dav/` (`https://` derrière un reverse proxy).
3. **Nom d'utilisateur / Mot de passe** : vos `upload.username` / `upload.password`.
4. **Dossier cible** : la racine (`/`) pour le dépôt, ou un sous-dossier.
5. Sur l'hôte Facet, surveillez le dépôt pour que les envois soient notés :

   ```bash
   python facet.py /photos --watch
   ```

### Test rapide avec curl

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (ou `204 No Content` en cas d'écrasement) signifie que le fichier a atteint le dépôt ; `--watch` le note peu après.

## Configuration

### Paramètres d'affichage

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Pagination

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Limites des menus déroulants

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Augmentez `min_photos_for_person` pour masquer de la liste du filtre les personnes ayant peu de photos.

### Seuils de qualité

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Filtres par défaut

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Poids des coups de cœur

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performances

### Grandes bases de données (50k+ photos)

Lancez ceci pour de meilleures performances :

```bash
python database.py --migrate-tags    # Requêtes de tags 10 à 50 fois plus rapides
python database.py --refresh-stats   # Précalcule les agrégations
python database.py --optimize        # Défragmente la base de données
```

`--migrate-tags` est une mise en place unique. Ensuite, les scans, `--recompute-tags`, `--recompute-tags-vlm` et `tag_existing.py` tiennent la table de tags à jour. Tant que vous ne l'avez pas lancé, les filtres de tags utilisent un repli plus lent.

Vérifiez le cache de statistiques (durée de vie de 5 minutes) avec :

```bash
python database.py --stats-info
```

### Index de la galerie et cache des comptages

Facet ajoute des index qui gardent rapides les pages et compteurs de la galerie sur de grandes bibliothèques. Sur une bibliothèque de 130k photos, ils ont fait passer la page par défaut d'environ 1,2 s à 26–38 ms avec le compte en cache, et environ 104 ms juste après un changement de la base de données.

- **Construits une fois, en arrière-plan.** Le premier démarrage de la visionneuse après une mise à jour construit les index manquants alors qu'elle sert déjà. Sur une bibliothèque de 130k photos, le plus gros index a pris 45 à 55 s à construire et environ 106 à 111 Mo de taille de base de données supplémentaire. Pendant l'écriture d'un index, les enregistrements sont brièvement refusés avec un message « réessayez dans un instant ». Un scan `python facet.py` ou une exécution de `python database.py` les construit d'abord à la place. Voir [DEPLOYMENT.md](DEPLOYMENT.md#démarrage-de-la-visionneuse-et-index-de-la-galerie) pour les écritures pendant la construction, l'arrêt, `--workers N` et Docker.
- **Les écritures deviennent légèrement plus lentes** : environ 0,5 à 0,7 ms de plus par ligne quand une colonne portée par ces index change.
- **Cache des comptages.** Les compteurs de la galerie sont mis en cache 5 minutes. Tout changement venant d'un processus du même hôte (y compris `--detect-junk` et `--recompute-*`) les rafraîchit. Un changement fait depuis une autre machine via un partage réseau apparaît à l'expiration du cache.

## Points d'accès API

La référence de l'API HTTP se trouve dans [API.md](../API.md). La documentation interactive est servie sur `/api/docs`.

## Photos JPEG XL

Facet analyse le JPEG XL (`.jxl`) grâce à la dépendance principale `imagecodecs`, incluse dans les installations standard et Docker. Aucun paquet supplémentaire n'est nécessaire ; les scans n'ignorent `.jxl` que si ce codec est indisponible.

- **Affichage.** Les navigateurs qui acceptent `image/jxl` reçoivent le fichier original ; les autres reçoivent un JPEG. Les miniatures de la galerie sont des JPEG.
- **Métadonnées.** Les originaux restent en `.jxl`. Les modifications de revue vont dans des sidecars, pas dans le fichier.
- **Animations.** Seule la première image est utilisée.
- **Couleur.** Un JXL qui reconstruit un JPEG conserve son profil ICC et les aperçus sont convertis en sRGB. Pour un JXL natif, le profil de couleur intégré n'est pas disponible, donc les scores et aperçus de fichiers à gamut étendu ou HDR peuvent ne pas être fidèles en couleurs. Les téléchargements d'originaux conservent leur profondeur et leur profil.
- **Limites.** Le décodage vérifie la limite de pixels de Pillow avant d'allouer les pixels, et l'inspection des en-têtes de conteneur s'arrête à 4 096 boîtes. L'EXIF encodé et décompressé est limité à 16 Mio chacun ; un EXIF trop volumineux est ignoré et l'image reste lisible. Au plus cinq conversions JPEG sont mises en cache. Les fichiers aux canaux supplémentaires non pris en charge sont refusés.

## Dépannage

| Problème | Solution |
|-------|----------|
| Chargement de page lent | Lancez `--migrate-tags` et `--optimize` |
| Filtres qui n'apparaissent pas | Vérifiez `--stats-info`, lancez `--refresh-stats` |
| Filtre de personnes vide | Lancez `--cluster-faces-incremental` |
| Bouton Comparer absent | Définissez un `edition_password` non vide (mono-utilisateur) ou utilisez le rôle `admin`/`superadmin` (multi-utilisateurs) |
| Le mot de passe ne fonctionne pas | Vérifiez `viewer.password` (mono-utilisateur) ou le hachage du mot de passe (multi-utilisateurs) |
| Un utilisateur ne voit pas de photos | Vérifiez `directories` dans sa configuration utilisateur et `shared_directories` |
| Bouton Scan absent | Nécessite `viewer.features.show_scan_button: true` plus l'accès scan — voir [Déclenchement d'un scan](#déclenchement-dun-scan) |
| La recherche ne renvoie aucun résultat | Assurez-vous que les photos ont des données `clip_embedding` (lancez d'abord la notation) |
| La recherche indique que l'accélération Apple Silicon est occupée | Réessayez une fois la tâche de modèle en cours terminée |
| Critique VLM indisponible | Nécessite le profil 16gb/24gb, `viewer.features.show_vlm_critique: true` et une session d'édition |
| La carte n'affiche aucune photo | Lancez `--extract-gps` ; vérifiez que les photos ont des données GPS EXIF |
| Les légendes ne se génèrent pas | Nécessite le profil VRAM 16gb/24gb pour le légendage VLM |
| Chronologie vide | Assurez-vous que les photos ont des valeurs `date_taken` |
| Port 5000 occupé | Lancez `python viewer.py --port 5001` (ou définissez `PORT=5001`). Sous macOS, AirPlay Receiver utilise 5000 : choisissez un autre port ou désactivez-le dans Réglages Système → Général → AirDrop et Handoff. |

### Vérifier les repères manuels de visages enregistrés

Trouvez les photos dont les rectangles de visages enregistrés doivent être vérifiés. Dans l'onglet Tri de la barre latérale de la galerie, activez **Visages manuels à vérifier** (éditeurs). Ouvrez l'éditeur de visages d'une photo et ajustez puis enregistrez, ou supprimez, chaque rectangle signalé. La photo quitte alors la liste. Le filtre fonctionne dans les albums intelligents et les sélections de toute la vue, et s'affiche comme une puce amovible.

- La liste reflète le dernier scan ou la dernière vérification de l'éditeur, pas une surveillance de fichiers en direct. Les scans vérifient les photos avec marques manuelles même quand la détection de visages est désactivée.
- Ouvrir l'éditeur revérifie l'original et fait foi.
- Les marques reprises par un relink (`relink_unverified`) restent signalées jusqu'à un nouvel enregistrement dans l'éditeur.
- La revue ne modifie jamais les fichiers originaux. Les exports et mises à jour de la base de données de la visionneuse conservent le statut de revue.

## Correction de la date de prise de vue

Corrigez une horloge d'appareil erronée. En mode édition, choisissez **Corriger la date de prise de vue** depuis l'icône de calendrier près de la date de la photo, ou depuis la barre de sélection de la galerie. Jusqu'à 1000 photos visibles, « Tout sélectionner dans la vue » compris.

- **Décaler de** (par défaut) : choisissez **Plus tôt** ou **Plus tard** et saisissez Jours, Heures, Minutes et Secondes. Par défaut : 1 heure plus tard. Les boutons rapides −1 h, +1 h, −1 j et +1 j s'ajoutent au décalage.
- **Définir l'heure exacte** : saisissez la date et l'heure correctes d'une photo de référence (la photo ouverte, ou la première photo datée de la sélection ; pas pour « Tout sélectionner dans la vue »). Le décalage en est déduit.
- Le décalage doit être non nul et d'au plus ±366 jours.
- Un résumé énonce le décalage (« 1 h 30 min plus tard »), et l'aperçu montre les compteurs de photos modifiées/ignorées et les 20 premiers horodatages ancien/nouveau.
- **Appliquer la correction (N)** l'applique. Si quelque chose a changé entre-temps, une erreur propose **Aperçu** pour rafraîchir.

**Ce qui change.**

- L'heure de l'appareil est décalée telle quelle : aucune logique de fuseau horaire ni d'heure d'été.
- Seules les dates complètes `YYYY:MM:DD HH:MM:SS` ou `YYYY-MM-DD[T ou espace]HH:MM:SS` sont prises en charge. Les dates inconnues, sans heure, avec fuseau/sous-seconde et invalides sont ignorées.
- Les dates corrigées survivent aux rescans et aux exports incrémentaux de la base de données de la visionneuse.
- **Utiliser la date du fichier** retire la correction et relit le fichier. Pas de date de fichier signifie une date de prise de vue inconnue.
- Appliquer une correction n'écrit jamais l'original et ne change pas son horodatage de fichier. L'export XMP écrit `exif:DateTimeOriginal` ; **Écrire les métadonnées dans le fichier** met aussi à jour l'EXIF `DateTimeOriginal` dans les formats pris en charge.
- Les groupes de rafales et de séries ne sont pas recalculés ; relancez la détection si vous avez besoin d'un nouveau regroupement.

Points d'accès : `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — voir [API.md](../API.md).

## Historique des modifications

Passez en revue et annulez vos modifications récentes dans toute la bibliothèque. En mode édition, ouvrez **Historique des modifications** depuis l'icône d'horloge de la navigation principale (après Ce jour-là). Développez une entrée pour voir les valeurs exactes avant/après, puis **Annuler cette entrée**.

- **Ce qui est enregistré :** GPS, dates de prise de vue, décisions de tri, étoiles, favoris et piles manuelles. Pas les fichiers ni la reconnaissance de visages.
- Le GPS et les dates de prise de vue sont des valeurs partagées de la bibliothèque. Les décisions de tri, étoiles et favoris sont les vôtres.
- Le court Annuler et la liste d'activité de l'assistant sont distincts.
- **Limites.** Les **50 dernières entrées par compte**, chacune jusqu'à **1000 photos et 1 Mio** de valeurs. Les actions de revue filtrées plus grandes sont scindées en parties ; l'annulation en restaure une. Un remplacement de pile peut couvrir jusqu'à 2000 photos en une entrée.
- L'historique survit aux redémarrages et aux mises à jour incrémentales de la base de données de la visionneuse. Un export de visionneuse neuf/complet repart vide. Il ne se synchronise pas vers une autre base de données.
- **L'annulation est tout ou rien.** Elle est refusée si la valeur d'une photo a changé depuis, même si elle est revenue en arrière. La modification de revue privée d'un autre compte ne bloque pas la vôtre. Les rescans, imports et Annuler peuvent aussi invalider des entrées plus anciennes.
- Une entrée est masquée quand l'une de ses photos est supprimée ou n'est plus visible pour vous.
- Une annulation ajoute sa propre entrée et marque l'originale comme annulée.

## Visages sans nom

Trouvez les visages non assignés et les groupes de personnes sans nom : `Filtres → Personnes → Visages sans nom` (`faces_need_names=true`). Utilisez + pour assigner un visage, ou nommez un groupe dans Personnes. Les photos sans visages détectés sont exclues.

Les utilisateurs en lecture seule peuvent parcourir ce filtre ; assigner ou nommer exige l'accès édition.

## Assigner des personnes

Le sélecteur **Assigner un visage à une personne** liste d'abord jusqu'à 12 personnes que vous avez récemment assignées dans ce navigateur (par identité connectée). Les autres personnes nommées suivent par nombre de visages dans les photos que vous pouvez voir. La recherche et la pagination couvrent tout le monde.

- Une personne ne devient récente qu'après une assignation réussie ou un enregistrement de visage manuel.
- Seuls les identifiants de personnes sont stockés localement. La déconnexion vide la liste.

## Actualiser les métadonnées et l'aperçu

Relisez les métadonnées d'une photo et reconstruisez son aperçu sans rescan complet. Les annotations manuelles, notes, visages et scores IA sont conservés. Les originaux ne sont jamais écrits. Réanalysez si des pixels modifiés nécessitent de nouveaux scores ou une nouvelle détection de visages.

- Jusqu'à 100 photos sélectionnées ; les sélections de toute la vue ne sont pas prises en charge.
- Les valeurs sources manquantes n'effacent pas les valeurs stockées. Sans `exiftool`, seul l'aperçu est rafraîchi.
- Le GPS et les dates manuels sont conservés.
- Refusé tant qu'un autre travail de bibliothèque s'exécute ; réessayez plus tard.
- Chaque photo est enregistrée séparément ; un nouvel essai traite les échecs.
- Jusqu'au prochain rescan, les histogrammes utilisent le nouvel aperçu et la recherche par similarité de couleur ignore la photo.
