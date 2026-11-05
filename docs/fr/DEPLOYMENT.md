# Guide de déploiement

> 🌐 [English](../DEPLOYMENT.md) · **Français** · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md) · [简体中文](../zh/DEPLOYMENT.md)

Exécutez la galerie web Facet sur un serveur distant ou un NAS.

> **Nouveau ici ?** Ce guide sert à mettre Facet à disposition d'autres machines. Pour le
> faire fonctionner sur votre propre ordinateur, commencez par [Installation](INSTALLATION.md).

## Vue d'ensemble

Facet comporte deux charges de travail :

| Composant | Matériel | Rôle |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24 Go VRAM) ou CPU (8 Go de RAM minimum, 12 Go recommandés ; davantage pour `12gb`/`16gb`/`24gb`, voir [Limites de mémoire du conteneur](#limites-de-mémoire-du-conteneur)) | Analyser et noter les photos |
| **Galerie web** (`viewer.py`) | Toute machine (peu de ressources) | Servir la galerie web |

Seule la galerie web doit tourner sur le serveur. Notez les photos sur un poste de travail, puis synchronisez la base de données.

> **Avertissement :** tant que `viewer.password` est vide (valeur par défaut), toute personne
> pouvant atteindre le port de la galerie web peut parcourir toute la bibliothèque et
> télécharger les originaux. Définissez `viewer.password` avant d'exposer le port au-delà de
> la machine ; voir [Mode mono-utilisateur](VIEWER.md#mode-mono-utilisateur-par-défaut).

Sur une installation ouverte (sans `viewer.password`), les jetons d'assistant (**Connecter un assistant**)
ne se gèrent que depuis l'ordinateur qui exécute Facet. Derrière Docker ou un proxy inverse,
définissez `viewer.password`, ou exécutez la requête sur l'hôte
(`docker compose exec facet python -c "import urllib.request ..."`). Un proxy inverse doit
envoyer `X-Forwarded-For` ou `Forwarded`, sinon il est traité comme la machine locale.

## Mappage des chemins

Lorsque la machine de scoring et la galerie web voient les photos sous des chemins différents, configurez
`viewer.path_mapping` dans `scoring_config.json` pour traduire les chemins de la base de données en chemins locaux.

**Exemple :** photos notées sous Windows via UNC/NFS, servies depuis un NAS Linux :

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Cela mappe `\\NAS\share\Photos\2024\IMG_001.jpg` vers `/volume1/Photos/2024/IMG_001.jpg`.
Utilisez des barres obliques dans les clés ; les barres obliques inverses sont normalisées.

Plusieurs mappages sont pris en charge (la première correspondance l'emporte) :

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos",
      "//NAS/share/Archive": "/volume1/Archive"
    }
  }
}
```

- La base de données conserve les chemins de scan d'origine (par ex. `\\NAS\share\Photos\2024\IMG_001.jpg`).
- Les miniatures sont stockées dans la base de données, donc la navigation ne nécessite aucun accès disque.
- Le mappage s'applique chaque fois que la galerie ouvre un fichier original : téléchargements,
  vue pleine résolution, génération de légendes et critique.
- Les chemins UNC (`\\server\share`) comme les lettres de lecteur (`Z:\`) sont pris en charge.

## Sémantique des chemins en conteneur

Sous Docker/Podman, chaque dossier que vous saisissez dans la galerie est un chemin **à l'intérieur du conteneur**.
Cela concerne une cible « Trier vers un dossier », une destination d'export d'album et
`viewer.export.allowed_target_dirs`. Utilisez le point de montage, jamais le chemin de l'hôte.

**Exemple.** Le `docker-compose.yml` fourni monte vos photos sur `/data/photos` :

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Pour trier les rejetées vers un sous-dossier `rejects`, saisissez `/data/photos/rejects`, pas
`/home/vous/Photos` ni `D:\Photos`, que le conteneur ne peut pas voir.

Pour écrire hors de l'arborescence photo, montez d'abord la cible, puis indiquez son chemin côté conteneur dans
`viewer.export.allowed_target_dirs` :

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # volume supplémentaire pour la sortie de tri/export
```

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    }
  }
}
```

Une destination hors de toute racine autorisée est refusée, après résolution des liens symboliques et des `..`.
Voir [Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri).

**Ce refus n'est pas un problème de droits.** Il survient avant que le moindre fichier ne soit touché. Un
écart d'uid entre l'utilisateur `facet` du conteneur et votre compte hôte est une défaillance distincte :
elle se produit pendant la copie/le déplacement et est journalisée avec l'erreur système.

### Où va la corbeille d'un conteneur

Quand `viewer.cull.allow_trash` est activé, `trash_rejects` utilise `send2trash`. Dans l'agencement fourni
(photos montées en bind sur `/data/photos`, uid 1000, `HOME=/home/facet`), les photos et
`$HOME` sont sur des systèmes de fichiers différents ; les fichiers mis à la corbeille vont donc dans la corbeille propre au volume photo :

- fichiers : `/data/photos/.Trash-1000/files/<nom>`
- métadonnées : `<nom>.trashinfo` (avec `Path=` et `DeletionDate=`) dans `/data/photos/.Trash-1000/info/`
- le répertoire est créé en mode `0700`

`.Trash-1000` est visible côté **hôte** : un simple `mv` hors de `files/` restaure une photo.
Les nouveaux scans l'ignorent tant que `scanning.skip_hidden_directories` vaut vrai (valeur par défaut).

Deux exceptions :

- **Aucun montage bind** pour les photos (par ex. `docker run` avec les photos dans le conteneur) :
  la corbeille va dans `~/.local/share/Trash` du conteneur et est **perdue quand le conteneur est
  supprimé**.
- **Podman rootless** : `.Trash-1000` appartient au sous-uid hôte mappé, pas à votre compte ;
  la restauration peut nécessiter `podman unshare`.

Pour choisir vous-même la destination, utilisez plutôt `move_rejects` vers un `target_dir`
([Trier vers un dossier](VIEWER.md#trier-vers-un-dossier)).

### Propriété du fichier de configuration

Facet ne prend possession que d'un `/config/scoring_config.json` qu'il a créé ; un fichier déjà présent
conserve son propriétaire et ses droits. La seule exception (une configuration que l'utilisateur `facet` du conteneur ne peut pas
lire) et la recette pour Podman rootless se trouvent dans
[Installation — Propriété du fichier en conteneur](INSTALLATION.md#propriété-du-fichier-en-conteneur).

Avec `group_add` de compose (voir [Partages photo lisibles uniquement via un groupe](#partages-photo-lisibles-uniquement-via-un-groupe-group_add)),
le test de lisibilité tient compte de ces groupes aussi : une configuration lisible via un tel groupe est
donc laissée telle quelle. Si le test `setpriv` échoue lui-même, le fichier est considéré comme illisible.

## Compilation du client Angular

Le serveur sert la SPA pré-compilée depuis `client/dist/client/browser/`. Compilez-la avant
le déploiement :

```bash
cd client && npm install && npx ng build && cd ..
```

Cela nécessite Node.js 20+ uniquement au moment de la compilation, pas sur le serveur.

## NAS Synology (DS420j / série J)

La série J possède un processeur ARM, 1 Go de RAM et pas de Docker. La galerie web tourne directement avec Python.

### Prérequis

1. **Activer SSH :** DSM > Panneau de configuration > Terminal & SNMP > Activer SSH
2. **Installer Python3 :** Centre de paquets DSM, ou via SSH :
   ```bash
   # Vérifier la disponibilité
   python3 --version
   pip3 --version
   ```

### Installation

```bash
ssh admin@your-synology-ip

# Créer le répertoire
mkdir -p /volume1/facet

# Installer les dépendances (galerie web uniquement)
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Exporter une base de données allégée

Sur votre poste de travail de scoring, exportez une base de données réduite pour le NAS :

```bash
python database.py --export-viewer-db
```

Cela crée `photo_scores_viewer.db`, qui :

- supprime les embeddings CLIP, de légende et de visage ;
- conserve l'histogramme par photo (~2 Ko chacun) pour le widget d'histogramme RVB ;
- réduit les miniatures de 640 px à 320 px ;
- fait généralement passer une base de 14 Go à environ 4-5 Go.

Les exports sont incrémentaux : seules les photos nouvelles et modifiées sont synchronisées. Pour une reconstruction complète :

```bash
python database.py --export-viewer-db --force-export
```

> **Avertissement :** `--force-export` supprime les notes, les positions et les tags manuels
> définis dans la galerie sur le NAS. Seul un export incrémental les conserve.

La fonctionnalité « Photos similaires » ne fonctionne pas sur la base exportée (pas d'embeddings). Utilisez la machine
de scoring pour cela.

**Tags manuels.** L'export embarque les [tags manuels](VIEWER.md#tags-manuels)
(`photo_manual_tags`). Un export incrémental ajoute seulement les tags de la base de scoring :

- Un tag retiré sur le NAS revient si la base de scoring le possède encore.
- Un tag ajouté sur le NAS n'est jamais recopié vers la base de scoring ; ajoutez-le aussi sur la machine de scoring.
- Un tag retiré sur la machine de scoring reste sur le NAS jusqu'à `--force-export`.
- La limite de 50 tags par photo n'est pas appliquée lors de la fusion : une photo peut donc la dépasser.

### Synchroniser les fichiers

Compilez d'abord le client Angular ([Compilation du client Angular](#compilation-du-client-angular)),
puis synchronisez vers le NAS :

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` porte les valeurs par défaut livrées, et le NAS tourne donc sur celles-ci. Pour utiliser votre propre
`scoring_config.json`, ajoutez-le à la liste `rsync`. Relisez-le d'abord : il contient le mot de passe
de la visionneuse et les clés API en clair.

La galerie web ouvre `photo_scores_pro.db` par défaut (modifiable via `DB_PATH`). Sur le NAS,
définissez `DB_PATH=/volume1/facet/photo_scores_viewer.db` ou créez un lien symbolique :

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Pour les téléchargements, les originaux doivent être accessibles sur le NAS au chemin de `path_mapping`.

### Configuration à faible mémoire

Ajoutez `viewer.performance` à `scoring_config.json` sur le NAS :

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

Cela remplace les paramètres globaux de `performance` (optimisés pour le scoring) par des valeurs pour 1 Go
de RAM. Voir [Configuration](CONFIGURATION.md#performance-de-la-visionneuse).

### Exécution

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Production (1 worker pour 1 Go de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Ouvrez `http://your-synology-ip:5000`.

### Démarrage automatique

DSM > Panneau de configuration > Planificateur de tâches > Créer > Tâche déclenchée > Script défini par l'utilisateur :

- **Événement :** Démarrage
- **Utilisateur :** root
- **Script :**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Utilisez le proxy inverse de Synology : DSM > Panneau de configuration > Portail de connexion > Avancé > Proxy inversé :

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Ajoutez un certificat Let's Encrypt depuis DSM > Panneau de configuration > Sécurité > Certificat.

Pour le pont d'onglet des agents ([Agents IA](AGENTS.md)), ouvrez l'onglet **En-tête personnalisé** de la règle
et choisissez **Créer > WebSocket**. Cela ajoute les en-têtes `Upgrade` et `Connection`
dont `/api/mcp/bridge` a besoin. Si la règle réécrit l'en-tête `Host`, indiquez votre origine publique dans
`viewer.mcp.allowed_origins`.

## NAS Synology (Plus / série x86)

Les NAS de la série Plus prennent en charge Docker (Container Manager).

### Lancer l'image publiée

Installez comme dans [Installation › Installer avec Docker](INSTALLATION.md#installer-avec-docker) :
`docker compose up -d` sur un NAS CPU, ou le bloc par profil avec une carte NVIDIA. Les
réglages `.env` et le montage de la configuration sont dans
[Installation › Réglages Docker modifiables](INSTALLATION.md#réglages-docker-modifiables).
Ce qui suit ne couvre que ce qui diffère sur un NAS.

**Les images sont uniquement en `linux/amd64` (x86_64).** Cela couvre le matériel NAS x86 (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer ou un Docker classique sur Intel/AMD). Il n'existe
pas d'image `arm64`. Sur un NAS ARM ou un Raspberry Pi, compilez localement avec
`docker compose build` ; le fichier compose conserve `build: .` sous la clé `image:` pour cela.

**Prévoyez l'espace disque :** l'image plus les modèles que chaque profil télécharge au premier lancement.

- Images, décompressées : CPU ~3,34 Go, `latest-cuda` (`sm_75`-`sm_120`) ~13,1 Go,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13,8 Go ([Taille de l'image](#taille-de-limage)).
  `docker pull` transfère moins, compressé.
- Modèles : `legacy` 4,69 Go, `8gb` 6,93 Go, `12gb`/`16gb` 14,55 Go, `24gb` 19,32 Go
  ([Tailles de téléchargement](INSTALLATION.md#tailles-de-téléchargement)).
- `docker compose down -v` supprime les volumes de modèles et force un nouveau téléchargement.

**Tags versionnés.** `:latest`, `:latest-cuda` et `:latest-cuda-legacy` évoluent à chaque
release. Épinglez une version (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) sur un NAS
que vous ne voulez pas voir changer sans prévenir. Les variantes se compilent depuis un seul `Dockerfile` via les
arguments de compilation `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` et `REQUIREMENTS_LOCK`, définis dans
`.github/workflows/docker-publish.yml`. Un déclenchement manuel `workflow_dispatch` de ce workflow
republie `latest` / `latest-cuda` / `latest-cuda-legacy` depuis `master` sans release.

**Build commercial.** Ajoutez `--build-arg FACET_LICENSING=commercial` (compose :
`build.args.FACET_LICENSING: commercial`). Cela ignore le lock restreint (`insightface`,
`pyiqa` et leurs dépendances) et définit `FACET_LICENSING_MODE=commercial`. La valeur par défaut
`FACET_LICENSING=default` conserve le comportement publié. Le lock restreint suit
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` pour le lock legacy). Voir
[Installation](INSTALLATION.md#installation-commerciale-et-paquets-restreints).

Pour une petite image réservée à la galerie web (sans CUDA), compilez une image allégée. Chaque source `COPY` doit être
suivie par git, ce qui explique pourquoi `scoring_config.json` n'est pas copié ; sans lui, le conteneur
tourne sur les valeurs par défaut de `config/`.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

> **Le pont d'onglet des agents exige un seul worker.** Avec plus d'un worker, un appel `ui_*` peut atteindre
> un processus qui ignore votre onglet et répondre `no_tab`. Utilisez `--workers 1` si vous employez les
> [Agents IA](AGENTS.md).

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Monter les photos pour les téléchargements
    restart: always
```

### Partages photo lisibles uniquement via un groupe (`group_add`)

Sur un NAS, le partage photo n'est souvent lisible que via un groupe (sur Synology, typiquement
`users`, gid 100). Donnez ce groupe au conteneur avec `group_add`, en utilisant le gid numérique
donné par `id <votre-utilisateur>` sur le NAS :

```yaml
services:
  facet:
    group_add:
      - "100"
```

L'entrypoint passe de root à `facet` avec `setpriv` et conserve ces gids. Vérifiez avec
`docker compose exec facet grep Groups /proc/1/status` : la sortie liste `1000` plus vos gids.

Alternative : exécuter avec `user: "1000:1000"` plus `group_add`. L'entrypoint ne fait alors ni chown ni
amorçage de `/config` : chaque montage doit déjà être accessible en écriture à l'uid 1000.

## Limites de mémoire du conteneur

Facet lit la limite mémoire du conteneur (`memory.max` en cgroup v2,
`memory.limit_in_bytes` en v1) plutôt que la RAM de l'hôte. Il dimensionne selon cette limite quels modèles se chargent
ensemble, la taille du bloc RAM, la mise en cache des modèles et le décodage RAW. Les versions antérieures
(v1.7.2 et avant) ignoraient `mem_limit` et pouvaient être tuées par OOM
([issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Mémoire minimale recommandée par profil

Les poids des modèles ne représentent qu'une partie du pic de mémoire : le runtime torch, les images décodées et
les activations s'y ajoutent. Considérez ces chiffres comme des planchers.

| Profil VRAM | Poids des modèles (total) | Mémoire du conteneur recommandée |
|---|---|---|
| `legacy` / `8gb` | 15,0 Go | 12 Go (GPU) / 8 Go minimum, 12 Go recommandés (CPU) |
| `12gb` / `16gb` | 22,0 Go | au moins 18 Go (provisoire) |
| `24gb` | 25,0 Go | au moins 18 Go (provisoire) |

- **GPU et CPU diffèrent.** Sur un GPU, les poids résident en VRAM et la RAM contient surtout les images décodées :
  un lancement `8gb` sur une RTX 3080 (405 photos, `ram_chunk_size: 12`, `num_workers: 2`) a atteint un pic de
  9,23 Go et a réussi avec `mem_limit: 12g`. Sur
  CPU, tous les modèles se chargent en RAM. Dimensionnez selon la ligne qui correspond à votre façon de lancer.
- **8 Go est un plancher sur CPU.** Des scans de 50 photos avec `--memory=8g` ont abouti sur `legacy` (pic 7,26 Go) et
  `8gb` (7,56 Go), à moins d'un demi-gigaoctet du plafond sur des JPEG 18-20 MP. Des images plus grandes, un décodage RAW
  ou un hôte chargé demandent davantage, d'où la recommandation de 12 Go.
- **`12gb`, `16gb` et `24gb` ne sont pas mesurés.** 18 Go est une valeur provisoire.
- **Pic de VRAM de `12gb` : TODO_VRAM12 GiB (simulé).** Mesuré sous un plafond simulé de 12 GiB sur une carte de 16 Go ; les modèles ONNX Runtime (InsightFace) ignorent ce plafond ; non mesuré sur une vraie carte de 12 Go.
- **Surveillez la mémoire anonyme.** Le MemUsage de `docker stats` et le `memory.current` du cgroup
  comptent tous deux le cache de pages récupérable, et sont donc trompeurs.
- **Mise en cache des modèles.** Avec `models.keep_in_ram` à `"auto"`, un modèle reste en RAM entre
  deux blocs seulement tant que sa taille plus `models.ram_cache_reserve_gb` (4 Go par défaut) est libre. Une
  réserve plus petite met davantage de modèles en cache ([Configuration](CONFIGURATION.md#modèles)).

Sur CPU, le profil `8gb` planifie toujours les mêmes 5 passes, quelle que soit la limite :
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Définissez la limite dans `docker-compose.yml` (ou un fichier de surcharge) :

```yaml
services:
  facet:
    mem_limit: 16g
```

### Le regroupement des passes a un plafond, et aucun plancher

- **Avec une limite de conteneur**, chaque passe CPU reçoit la limite moins une réserve de 2 Go, plafonnée à
  5 Go. Une limite serrée signifie un modèle par passe.
- **Sans limite**, le budget est (RAM système − 1 Go) ÷ 1,6. Un hôte de 4 Go obtient 1,9 Go par
  passe, un hôte de 2 Go 0,6 Go.
- **Un modèle plus gros que le budget** obtient quand même sa propre passe, avec un avertissement qui le nomme. Par
  exemple `qwen3_5_4b_tagger` (`24gb`) donne à lui seul une passe de 8,0 Go.

> **Avertissement :** ne dimensionnez jamais un conteneur en dessous du plus gros modèle unique de votre profil.

## Windows (WSL2) avec un GPU NVIDIA

Exécutez la pile GPU de scoring et de galerie web dans Docker sous Windows via WSL2, sans Docker
Desktop. Tout (la distribution, ses images, `/var/lib/docker`) reste sur un **disque de données**
(par ex. `D:`), utile quand `C:` manque d'espace.

**Prérequis :** un pilote NVIDIA récent sous Windows (`nvidia-smi` fonctionne dans l'invite Windows).
N'installez **pas** de pilote dans WSL.

### 1. Installer WSL2 (admin, une seule fois)

Dans un PowerShell **élevé**, puis redémarrez si demandé :

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Installer une distribution dont le disque se trouve sur le disque de données

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` place le `ext4.vhdx` de la distribution sous `D:\wsl\facet`. `--no-launch` ignore l'invite
de premier lancement ; les commandes ci-dessous s'exécutent en tant que `root`.

### 3. Activer systemd (nécessaire pour le service docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Installer Docker CE + le NVIDIA Container Toolkit (à l'intérieur de la distribution)

```bash
wsl -d facet -u root
# --- inside the distro ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Docker repo (fall back to the newest supported codename if yours is too new):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# NVIDIA toolkit repo (distribution-agnostic):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 has no nvidia cgroup
systemctl enable --now docker
# Verify GPU passthrough:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Lancer Facet

Le dépôt sur le disque Windows est visible sous `/mnt/d/...` dans WSL. Lancez le bloc correspondant à votre carte
depuis [Installation › Installer avec Docker](INSTALLATION.md#installer-avec-docker) :

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # ou le fichier de votre carte
curl -s localhost:5000/health          # -> ok
```

Ajoutez `--build` pour compiler depuis le clone plutôt que de récupérer l'image. Les profils GPU
(`8gb`/`12gb`/`16gb`/`24gb`) regroupent les visages sur le GPU via le RAPIDS cuML intégré ; `legacy`
regroupe sur CPU. Le premier lancement télécharge les modèles dans les volumes nommés ; réinitialisez-les avec
`docker compose down -v`.

### Image reproductible et autonome

- **Versions figées.** L'image est compilée à partir de `requirements.lock.txt`, un `pip freeze` d'un
  conteneur validé sans `torch`/`torchvision` ni `nvidia-*` (l'image de base CUDA les fournit).
  `kornia`, requis par BiRefNet, y est figé aussi. Régénérez-le après une mise à niveau
  intentionnelle : `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Regroupement de visages sur GPU inclus.** RAPIDS cuML (`cuml-cu12`, ~5,75 Go) permet aux profils GPU de
  regrouper sur le GPU (`face_clustering.use_gpu="auto"`). `legacy`, et les hôtes sans CUDA,
  regroupent sur CPU.
- **Aucun couplage avec l'hôte.** Les caches de modèles sont des volumes nommés ; le conteneur s'exécute avec
  l'utilisateur `facet`, sans privilèges.
- **Contexte de compilation allégé.** `.dockerignore` exclut le contenu volumineux local (`conda/`, jeux de données d'exemple,
  `*.db`, caches) ; ajoutez-y les nouveaux gros dossiers locaux.

### Taille de l'image

Aucune image ne contient les poids des modèles ; ils se téléchargent au premier lancement dans les volumes nommés
([totaux par profil](INSTALLATION.md#tailles-de-téléchargement)). Prévoyez de l'espace disque pour les deux.

| Image | Sur disque (mesuré) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 Go | `python:3.12-slim` + PyTorch en wheels CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 Go | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, de Turing à Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 Go | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, de Maxwell à Hopper) + RAPIDS cuML |

« Sur disque » est la taille décompressée (`docker images`). `docker pull` transfère moins ; les tailles
compressées ne sont pas encore mesurées.

## Serveur Linux générique

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Ou utilisez le wrapper (1 worker par défaut ; `--workers N` pour davantage) :

```bash
python viewer.py --production --workers 4
```

Le pont d'onglet des agents exige `--workers 1` (voir
[Lancer l'image publiée](#lancer-limage-publiée)).

### Uvicorn + Nginx

```nginx
server {
    listen 80;
    server_name photos.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 50M;
    }

    location /api/mcp/bridge {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_read_timeout 3600s;
    }
}
```

Le pont d'onglet des agents (`/api/mcp/bridge`, voir [Agents IA](AGENTS.md)) est un WebSocket. Il
lui faut les en-têtes `Upgrade` et `Connection` du second bloc `location` et un seul worker
(`--workers 1`, la valeur par défaut) ; sinon les outils d'agent `ui_*` répondent `no_tab`.

Ajoutez HTTPS :

```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Service systemd

```ini
# /etc/systemd/system/facet.service
[Unit]
Description=Facet Viewer
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/facet
ExecStart=/usr/local/bin/uvicorn api:create_app --factory --host 127.0.0.1 --port 5000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Utilisez `--workers 1` si vous employez le pont d'onglet des agents.

```bash
sudo systemctl enable --now facet
```

### Caddy (HTTPS automatique)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Flux de travail

```
 Scoring Machine (GPU)                      Server / NAS
 ─────────────────────                      ─────────────
 python facet.py /photos
         │
         ├─ database.py --export-viewer-db
         │       │
         │       └─ photo_scores_viewer.db ──rsync──▶ viewer.py serves gallery
         └─ scoring_config.json ────────────────────▶ (with path_mapping +
                                                       viewer.performance)
                                                        │
                                                 http://nas:5000
```

Relancez l'export et `rsync` après chaque session de scoring. Sur un serveur doté de beaucoup de
mémoire, vous pouvez synchroniser la base complète `photo_scores_pro.db` à la place.

### Un seul travail de bibliothèque à la fois

Un scan, `--recompute-average`, `--upgrade-db` et un entraînement du classeur personnel réécrivent chacun la
base de données : un seul s'exécute donc à la fois. Un second travail refuse de démarrer, nomme celui en cours,
et se termine avec le code 75 (code 1 si le fichier de verrou `<db_dir>/.facet_cache/library.lock` est
inutilisable).

> **Avertissement :** ce verrou ne fonctionne que sur **une seule machine**. Via SMB/CIFS (par ex. un poste
> Windows qui score vers un partage NAS), chaque machine a son propre verrou. Facet journalise un
> avertissement mais ne peut pas l'empêcher : lancez les travaux de bibliothèque depuis une seule machine à la fois. NFS entre
> clients Linux n'est pas concerné.

### Démarrage de la visionneuse et index de la galerie

Le premier démarrage après une mise à niveau depuis la 1.20 construit les index de galerie manquants
([détails](VIEWER.md#index-de-la-galerie-et-cache-des-comptages)). Sur une bibliothèque d'environ 130k photos, cela
prend quelques minutes et ajoute environ 130 Mo à la base de données.

**Recommandé :** après la mise à niveau, lancez une fois `python database.py` (Docker :
`docker compose exec facet python database.py`) **avant** de démarrer la visionneuse. Un
scan `python facet.py` les construit aussi à son démarrage.

Si la visionneuse les construit à la place :

- Elle sert pendant la construction, mais la galerie est lente et les **enregistrements (notes, rejets, modifications
  d'album…) peuvent être refusés** avec un message « bibliothèque occupée, réessayez ».
- Le journal affiche `Creating index ...` et `Created index ... in N s` par index, puis
  `Gallery indexes ready`. `/health` rend compte de la progression sous `gallery_indexes` (`state` :
  `building`, `ready`, `deferred`, `failed` ou `stopped` ; `done` sur `total`).
- Arrêter la visionneuse conserve les index terminés ; le démarrage suivant reprend.
- Si un scan ou un autre travail de bibliothèque est en cours, la visionneuse sert sans les index et
  journalise un avertissement. Redémarrez-la quand le travail est terminé, ou lancez `python database.py`.
- Si `.facet_cache/library.lock` à côté de la base est inutilisable (droits, montage en lecture
  seule), la visionneuse ne construit pas. Corrigez le chemin et redémarrez.
- Avec `--workers N`, un worker construit et les autres servent.
- Sous Docker, le `start_period` de 30 s du healthcheck n'a pas besoin d'être modifié : `/health` répond pendant la construction.

Sur un SQLite antérieur à 3.48.0 (l'image CPU embarque 3.46.1), la détection de panoramas ne peut pas lire
depuis le nouvel index seul ; sa vitesse n'y a pas été mesurée. Sur un SQLite autre que 3.51,
des photos portant des horodatages identiques peuvent être groupées autrement lors de la première passe de rafales après
la mise à niveau (voir le CHANGELOG).

> **Avertissement :** ne copiez ou ne remplacez la base qu'après avoir arrêté la visionneuse. Tant qu'elle tourne,
> les changements récents se trouvent dans les fichiers `-wal` et `-shm`, pas dans le seul `.db` ; un arrêt
> propre les fusionne (y compris avec `performance.wal_checkpoint_minutes: 0`). Sous Windows, le fichier
> ne peut pas du tout être remplacé tant que la visionneuse l'a ouvert.

## Stockage et rotation du secret

Un seul secret signe chaque session de connexion (JWT) et chaque lien de cadre photo. Il réside dans
`.facet_secret` à côté de la configuration (mode `0600`, ignoré par git), pas dans `scoring_config.json`.

Les anciennes versions le stockaient comme `share_secret` dans la configuration, et la valeur livrée était publique.
Au démarrage, Facet déplace tout `share_secret` résiduel dans le fichier de secret et supprime la clé.
Une valeur que Facet a lui-même publiée est remplacée, ce qui déconnecte tout le monde une fois.

| Emplacement | Méthode |
|-------------|---------|
| Par défaut | `.facet_secret` à côté de `scoring_config.json`, mode `0600` |
| Conteneur / orchestrateur | Variable d'environnement `FACET_JWT_SECRET` — lue en premier, jamais écrite sur disque |
| Rotation | `python database.py --rotate-secret`, puis redémarrer la visionneuse |

- **Docker :** `/app` est la couche inscriptible du conteneur : un secret créé là est perdu
  à la recréation et tout le monde est déconnecté à chaque mise à jour de l'image. Définissez `FACET_JWT_SECRET` dans
  `docker-compose.yml`, ou montez le fichier avec `- ./.facet_secret:/app/.facet_secret`.
- **Effectuez une rotation** dès que le secret a pu être divulgué (une configuration commitée, une sauvegarde divulguée, le
  départ d'un administrateur). Tout le monde se reconnecte et les appareils kiosque récupèrent leurs liens de cadre.
- **Plusieurs workers :** créez le secret avant le premier démarrage avec `--workers > 1` (lancez
  `python database.py --rotate-secret` une fois, démarrez une fois avec `--workers 1`, ou définissez
  `FACET_JWT_SECRET`). Sinon chaque worker génère le sien et les sessions échouent jusqu'au redémarrage.
- **Répertoire d'installation en lecture seule :** le serveur tourne sur un secret en mémoire, donc les sessions meurent
  à chaque redémarrage. Définissez `FACET_JWT_SECRET`.
- **Sauvegardez-le** avec la base de données ; restaurer une base sans lui déconnecte tout le monde.

## Configuration multi-utilisateur

Pour attribuer à chaque utilisateur un ensemble privé de répertoires de photos, ajoutez une section `users` à
`scoring_config.json`. Voir [Configuration](CONFIGURATION.md#utilisateurs).

### Démarrage rapide

```bash
# Sur la machine de notation, ajouter des utilisateurs
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Puis modifiez `scoring_config.json` :

```json
{
  "users": {
    "alice": {
      "password_hash": "...",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "...",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family"
    ]
  }
}
```

Les chemins des répertoires doivent correspondre aux chemins de photos de la base de données. Avec `viewer.path_mapping`,
utilisez les chemins **mappés** (tels que vus sur l'hôte de la galerie web).

### Migration des notes existantes

Pour déplacer les notes du mode mono-utilisateur vers un utilisateur :

```bash
python database.py --migrate-user-preferences --user alice
```

### Bouton de scan

Pour permettre à la galerie de déclencher des scans (le superadmin en mode multi-utilisateurs ; une session d'édition sur une
installation mono-utilisateur dotée d'un `viewer.edition_password` non vide), activez-le. Le scan s'exécute sur
la machine de la galerie et ne requiert aucun GPU ([Pas de carte graphique](INSTALLATION.md#pas-de-carte-graphique)) :

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Sauvegardes continues avec Litestream

La base de données peut atteindre plusieurs dizaines de gigaoctets (~14 Go après plus de 20k photos), et un re-scan
coûte du temps GPU. [Litestream](https://litestream.io/) diffuse les changements en continu vers S3,
B2, GCS, SFTP ou un autre disque, avec restauration à un instant précis à quelques secondes près.

Facet ne fournit pas Litestream. Installez-le sur l'hôte exécutant Facet ; il tourne en parallèle
sans modification de Facet. Le checkpoint périodique du WAL de Facet (toutes les 30 min par défaut,
`performance.wal_checkpoint_minutes` ; `0` le désactive, un arrêt propre de la visionneuse fait toujours
un checkpoint) maintient le WAL petit.

### Configuration Litestream minimale

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Stockage objet économique ; remplacez par le bucket de votre choix.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # conserver 3 jours d'historique à un instant donné
        snapshot-interval: 24h        # instantané complet une fois par jour
        validation-interval: 6h       # détecter la corruption tôt
```

### Unité systemd

```ini
# /etc/systemd/system/litestream.service
[Unit]
Description=Litestream continuous SQLite replication
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/litestream replicate -config /etc/litestream.yml
Restart=always
User=facet
EnvironmentFile=/etc/litestream.env

[Install]
WantedBy=multi-user.target
```

`litestream.env` contient les identifiants AWS / B2, hors du YAML.

### Exercice de restauration

Entraînez-vous avant d'en avoir besoin :

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# vérifier
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# remplacer par
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Ordre de grandeur des coûts

Pour une base de 14 Go avec environ 50 Mo/jour de variation du WAL pendant le scoring actif :

- environ 0,30 $/mois pour le stockage sur S3 Standard
- environ 0,05 $/mois pour les opérations PUT

Négligeable comparé à un re-scan : environ 50 heures-GPU sur une RTX 16 Go.
