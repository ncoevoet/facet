# Guide de déploiement

> 🌐 [English](../DEPLOYMENT.md) · **Français** · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · [Português](../pt/DEPLOYMENT.md)

Exécutez la galerie web Facet sur un serveur distant ou un NAS.

> **Nouveau ici ?** Ce guide sert à mettre Facet à disposition d'autres machines. Pour le
> faire fonctionner sur votre propre ordinateur, commencez par [Installation](INSTALLATION.md).

## Vue d'ensemble

Facet comporte deux charges de travail :

| Composant | Matériel | Rôle |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24 Go VRAM) ou CPU (8 Go+ RAM) | Analyser et noter les photos |
| **Galerie web** (`viewer.py`) | Toute machine (peu de ressources) | Servir la galerie web |

Seule la galerie web doit tourner sur le serveur. Notez les photos sur un poste de travail, puis synchronisez la base de données.

## Mappage des chemins

Lorsque la machine de scoring et le serveur de la galerie accèdent aux photos depuis des points de montage différents, configurez `viewer.path_mapping` dans `scoring_config.json` pour traduire les chemins de la base de données en chemins de disque local.

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

Utilisez des **barres obliques** (forward slashes) dans les clés de configuration pour la lisibilité — les barres obliques inverses sont normalisées automatiquement. Cela mappe des chemins de base de données comme `\\NAS\share\Photos\2024\IMG_001.jpg` vers `/volume1/Photos/2024/IMG_001.jpg`.

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

**Fonctionnement :**
- La base de données stocke les chemins de scan d'origine (par ex. `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Les miniatures sont stockées comme BLOB dans la base de données, donc la navigation ne nécessite aucun accès disque
- Le mappage des chemins s'applique chaque fois que la galerie ouvre un fichier original : téléchargements, vue pleine résolution, génération de légendes et critique
- Les chemins UNC (`\\server\share`) comme les lettres de lecteur (`Z:\`) sont pris en charge
- Le premier préfixe correspondant l'emporte

## Sémantique des chemins en conteneur

Tout ce que vous saisissez dans un champ de dossier de la visionneuse — une cible « Trier vers un dossier », la destination d'export copie/symlink d'un album, ou `viewer.export.allowed_target_dirs` dans `scoring_config.json` — est résolu par le processus Facet lui-même. **Sous Docker/Podman, ce processus s'exécute à l'intérieur du conteneur**, si bien que chaque chemin est celui que *le conteneur* voit : le point de montage, jamais le chemin côté hôte.

**Exemple.** Le `docker-compose.yml` fourni monte votre dossier photo sur `/data/photos` :

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Pour trier les rejetées vers un sous-dossier `rejects`, saisissez `/data/photos/rejects` dans la boîte de dialogue — jamais le chemin hôte (`/home/vous/Photos`, `D:\Photos`, …), que le conteneur ne peut pas voir du tout. Il en va de même pour `viewer.export.allowed_target_dirs` : indiquez le chemin côté conteneur.

Pour écrire ailleurs que dans l'arborescence photo scannée — un volume d'export séparé, par exemple —, montez-le d'abord dans le conteneur, puis ajoutez son chemin côté conteneur à `viewer.export.allowed_target_dirs` :

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

Une destination qui se résout hors de tout volume monté est refusée (`403`) — le contrôle de target-dir de Facet exécute `os.path.realpath()` à la fois sur la requête *et* sur chaque racine autorisée, résolvant les liens symboliques et les `..` avant comparaison, si bien qu'un chemin qui ne semble correct que depuis l'extérieur du conteneur (ou un lien symbolique pointant hors d'un montage) échoue quand même au test de confinement. Voir [Configuration — Destinations d'export et de tri](CONFIGURATION.md#destinations-dexport-et-de-tri) pour la référence complète de la liste d'autorisation.

**Ce n'est pas un problème de droits de l'utilisateur conteneur.** L'UID de l'utilisateur `facet` à l'intérieur du conteneur diffère couramment de celui de votre compte hôte, et cela peut causer un vrai problème de droits du système de fichiers, distinct, sur un montage bind — mais cela se produit *après* que ce contrôle de chemin a été franchi, quand la copie/le lien symbolique/le déplacement s'exécute réellement, et c'est journalisé côté serveur avec l'erreur système sous-jacente pour le fichier en échec. Un `403 target_dir is not an allowed export location` (ou un « accès refusé » générique dans l'interface) se produit *avant* que le moindre fichier ne soit touché et n'a rien à voir avec les UID.

## Compilation du client Angular

Le serveur FastAPI sert la SPA pré-compilée depuis `client/dist/client/browser/`. Compilez-la avant le déploiement :

```bash
cd client && npm install && npx ng build && cd ..
```

Cela nécessite Node.js 20+ uniquement au moment de la compilation. Les fichiers compilés sont des ressources statiques — Node.js n'est pas requis sur le serveur à l'exécution.

## NAS Synology (DS420j / série J)

La série J possède un processeur ARM, 1 Go de RAM et ne prend pas en charge Docker. La galerie web tourne directement avec Python.

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
pip3 install fastapi uvicorn pyjwt pillow
```

### Exporter une base de données allégée

Sur votre poste de travail de scoring, exportez une base de données réduite pour le déploiement sur NAS :

```bash
python database.py --export-viewer-db
```

Cela crée `photo_scores_viewer.db`, qui :
- Supprime les embeddings CLIP, les embeddings de légende et les embeddings de visage
- Conserve l'histogramme par photo (~2 Ko chacun), lu par le widget d'histogramme RVB de la galerie
- Réduit les miniatures de 640 px à 320 px
- Fait généralement passer une base de données de 14 Go à environ 4-5 Go

Les exports sont incrémentaux : si `photo_scores_viewer.db` existe déjà, seules les photos nouvelles et modifiées sont synchronisées. Utilisez `--force-export` pour une reconstruction complète :

```bash
python database.py --export-viewer-db --force-export
```

La fonctionnalité « Photos similaires » ne fonctionnera pas sur la base de données exportée (les embeddings CLIP sont supprimés). Utilisez la machine de scoring pour cela.

### Synchroniser les fichiers

Sur la machine de scoring, compilez d'abord le client Angular :

```bash
cd client && npm install && npx ng build && cd ..
```

Puis synchronisez la galerie web et la base de données exportée vers le NAS :

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

La galerie web ouvre `photo_scores_pro.db` par défaut (modifiable via la variable d'environnement `DB_PATH`). Sur le NAS, définissez soit `DB_PATH=/volume1/facet/photo_scores_viewer.db`, soit créez un lien symbolique :
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Les photos originales doivent être accessibles sur le NAS au chemin configuré dans `path_mapping` pour que les téléchargements fonctionnent.

### Configuration à faible mémoire

Ajoutez `viewer.performance` à `scoring_config.json` sur le NAS pour réduire l'utilisation de la mémoire :

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

Cela remplace les paramètres globaux de `performance` (optimisés pour le scoring) par des valeurs adaptées à 1 Go de RAM. Voir [Configuration](CONFIGURATION.md#performance-de-la-visionneuse) pour plus de détails.

### Exécution

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Production (1 worker pour 1 Go de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Accès à `http://your-synology-ip:5000`

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

Utilisez le proxy inverse intégré de Synology :

DSM > Panneau de configuration > Portail de connexion > Avancé > Proxy inversé :

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Associez-le à un certificat Let's Encrypt depuis DSM > Panneau de configuration > Sécurité > Certificat.

## NAS Synology (Plus / série x86)

Les NAS de la série Plus prennent en charge Docker (Container Manager).

### Lancer l'image publiée

Installez exactement comme dans [Installation › Installer avec Docker](INSTALLATION.md#installer-avec-docker) :
`docker compose up -d` pour un NAS CPU, ou le bloc par profil si la machine possède une
carte NVIDIA. Les réglages `.env` et le montage de la configuration sont documentés dans
[Installation › Réglages Docker modifiables](INSTALLATION.md#réglages-docker-modifiables).
Ce qui suit ne couvre que ce qui diffère sur un NAS.

**Les deux images publiées sont uniquement en `linux/amd64` (x86_64).** Cela couvre le matériel NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive, et tout ce qui fait tourner Coolify, Portainer ou un Docker classique sur un CPU Intel/AMD). Il n'existe pas d'image `arm64` : la compilation croisée d'une pile ML de plusieurs gigaoctets sous QEMU coûte des heures par tag, et la variante CUDA est de toute façon réservée à x86. Sur un NAS ARM ou un Raspberry Pi, compilez localement avec `docker compose build` plutôt que de récupérer l'image — `docker compose up` conserve `build: .` sous la clé `image:` précisément pour ce cas.

**Prévoyez l'espace disque.** Une fois décompressée, l'image CPU pèse environ 3,3 Go
sur disque et l'image CUDA environ 21 Go (valeurs approximatives, non revérifiées par
rapport à la build actuelle : le téléchargement lui-même transfère moins,
compressé — voir [Taille de l'image](#taille-de-limage) plus bas), plus les poids des
modèles que chaque profil télécharge au premier lancement (`legacy` 4,69 Go, `8gb`
6,93 Go, `16gb` 14,55 Go, `24gb` 19,13 Go — tableau complet dans
[Installation › Tailles de téléchargement](INSTALLATION.md#tailles-de-téléchargement)).
`docker compose down -v` supprime les volumes de modèles et force un nouveau
téléchargement.

**Tags versionnés.** `:latest` et `:latest-cuda` évoluent à chaque release ; épinglez une version (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, …) sur un NAS que vous ne voulez pas voir changer sans prévenir. Les deux variantes se compilent depuis le même `Dockerfile` via les arguments de compilation `BASE_IMAGE`, `STRIP_TORCH` et `INSTALL_CUML`, définis par variante dans `.github/workflows/docker-publish.yml`. Ce workflow accepte aussi un déclenchement manuel `workflow_dispatch`, qui republie `latest`/`latest-cuda` depuis `master` sans avoir à couper de release ni à créer de tag versionné.

Pour un NAS dédié à la galerie web où l'image doit rester légère (sans CUDA), compilez plutôt une image allégée. Notez que le garde-fou de la CI exige que chaque source `COPY` soit suivie par git, donc le contexte de compilation doit inclure les fichiers listés :

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow
COPY viewer.py config.py database.py tagger.py scoring_config.json ./
COPY api/ api/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

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

## Windows (WSL2) avec un GPU NVIDIA

Exécutez la pile complète de scoring + galerie web sur GPU dans Docker sous Windows via WSL2 — sans Docker Desktop. Cela conserve tout (la distribution Linux, ses images Docker, et `/var/lib/docker`) sur un **disque de données** (par ex. `D:`), ce qui compte lorsque le disque système `C:` manque d'espace.

**Prérequis :** un pilote NVIDIA récent sous Windows (`nvidia-smi` fonctionne dans l'invite de commandes Windows — le pilote fournit le passthrough CUDA pour WSL2 ; vous n'installez **pas** de pilote à l'intérieur de WSL).

### 1. Installer WSL2 (admin, une seule fois)

Dans un PowerShell **élevé** (exécuté en administrateur), puis redémarrez si demandé :

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Installer une distribution dont le disque se trouve sur le disque de données

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` place le fichier `ext4.vhdx` de la distribution sous `D:\wsl\facet`, de sorte que le stockage des images Docker reste hors de `C:`. `--no-launch` ignore l'invite interactive de premier lancement ; les commandes ci-dessous s'exécutent en tant que `root`, ce qui convient pour une machine dédiée à un seul usage.

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

### Lancer Facet

Le dépôt sur le disque Windows est visible depuis WSL sous `/mnt/d/...`. À partir de là, lancez le
bloc correspondant à votre carte depuis
[Installation › Installer avec Docker](INSTALLATION.md#installer-avec-docker) :

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # ou le fichier de votre carte
curl -s localhost:5000/health          # -> ok
```

Ajoutez `--build` pour compiler depuis le clone plutôt que de récupérer l'image publiée. Les profils
GPU (`8gb`/`16gb`/`24gb`) regroupent les visages sur le GPU via RAPIDS cuML intégré ; le
profil `legacy` regroupe toujours sur CPU. Le premier lancement télécharge les modèles du profil dans les
volumes nommés ; réinitialisez-les avec `docker compose down -v`.

### Image reproductible et autonome

- **Versions figées.** L'image est compilée à partir de `requirements.lock.txt` — un `pip freeze` complet d'un conteneur validé, avec `torch`/`torchvision` et `nvidia-*` retirés (l'image de base CUDA les fournit déjà). Cela évite toute dérive silencieuse vers des versions non testées. (Exemple que cela évite : transformers 5.3 a changé le traitement par lots de la vision de Qwen3.5 et cassé le tagger VLM jusqu'au correctif de padding ; `kornia`, requis par BiRefNet, n'est pas entraîné par transformers et doit être figé.) Régénérez-le après une mise à niveau intentionnelle : `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Regroupement de visages sur GPU intégré.** RAPIDS cuML (`cuml-cu12`) est fourni dans l'image, si bien que les profils GPU (8gb/16gb/24gb) regroupent les visages sur le GPU (HDBSCAN via `face_clustering.use_gpu="auto"`) ; le profil legacy — et tout hôte sans périphérique CUDA — regroupe toujours sur CPU. cuML est de loin la plus grosse dépendance (~5,75 Go ; voir la répartition des tailles ci-dessous).
- **Aucun couplage avec l'hôte.** Les caches de modèles sont des volumes nommés, pas des montages hôte ; le conteneur s'exécute sans privilèges (le point d'entrée par défaut bascule vers l'utilisateur `facet`).
- **Contexte de compilation allégé.** `.dockerignore` exclut le contenu volumineux local (`conda/`, jeux de données d'exemple, `*.db`, caches, artefacts de développement) — gardez les nouveaux répertoires locaux volumineux hors du contexte en les y ajoutant.

### Taille de l'image

Aucune des deux images publiées ne contient les poids des modèles — ils se téléchargent au premier
lancement dans les volumes nommés ([totaux par profil](INSTALLATION.md#tailles-de-téléchargement)). Prévoyez de l'espace disque pour
l'image **plus** ces volumes.

| Image | Téléchargement compressé | Sur disque (approx.) | Base |
|-------|------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 4,18 Go | ~3,3 Go | `python:3.12-slim` + PyTorch en wheels CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 7,33 Go | ~21 Go | PyTorch CUDA + RAPIDS cuML |

Le « téléchargement compressé » est ce que transfère `docker pull`, mesuré à partir des
manifestes actuels du registre `ghcr.io/ncoevoet/facet`. La valeur « sur disque » est
l'empreinte de l'image une fois décompressée ; ces chiffres n'ont pas été revérifiés par
rapport au digest `:latest` actuel pour cette passe — traitez-les comme un ordre de
grandeur pour la planification plutôt qu'une mesure précise et actuelle.

L'image CPU est dominée par la pile de dépendances ML (~1,9 Go) plutôt que par PyTorch
lui-même (~960 Mo), plus les bibliothèques système (~288 Mo) et l'OS de base (~150 Mo). Dans l'image CUDA,
c'est la pile GPU qui domine : RAPIDS cuML ~5,75 Go, bibliothèques runtime CUDA ~3,7 Go, PyTorch et
Triton ~1,9 Go, dépendances ML ~1,9 Go, OS de base et conda ~2-3 Go.

## Serveur Linux générique

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Ou utilisez le wrapper (par défaut 1 worker ; passez `--workers N` pour davantage) :

```bash
python viewer.py --production --workers 4
```

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
}
```

Ajouter HTTPS :
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

Relancez l'export et `rsync` après chaque session de scoring pour mettre à jour la base de données sur le serveur. Pour les serveurs dotés de beaucoup de mémoire, vous pouvez synchroniser directement la base complète `photo_scores_pro.db` au lieu de l'exporter.

### Un seul travail de bibliothèque à la fois

Un scan, `--recompute-average`, `--upgrade-db` et un entraînement du classeur personnel réécrivent chacun toute la base de données : Facet n'en autorise donc qu'un seul à la fois. Chacun prend un fichier de verrou dans `<db_dir>/.facet_cache/library.lock`, et un second travail refuse de démarrer en nommant celui déjà en cours.

Ce verrou est un verrou de fichier du noyau : il n'exclut donc les travaux que **sur une seule machine**. Lorsque la base de données est accédée via SMB/CIFS — un poste Windows qui score des photos sur un partage NAS, par exemple —, chaque machine prend sa propre copie du verrou et aucune ne voit l'autre. Facet détecte le montage et journalise un avertissement au moment de prendre le verrou, mais il ne peut rien imposer entre machines : lancez les travaux de bibliothèque depuis une seule machine à la fois. NFS entre clients Linux n'est pas concerné — `flock` y devient un verrou d'enregistrement POSIX arbitré par le serveur.

## Stockage et rotation du secret

Un seul secret signe chaque session de connexion (JWT) et chaque lien de cadre photo. Ce n'est **pas** une clé de `scoring_config.json` : il réside dans `.facet_secret`, à côté de la configuration, créé en mode `0600` au premier lancement et ignoré par git.

C'était auparavant la clé `share_secret` de `scoring_config.json`. Ce fichier est suivi par git : la valeur générée au premier démarrage a donc été commitée et publiée — le secret livré par ce projet est public et doit être considéré comme compromis. Au démarrage suivant, Facet déplace tout `share_secret` résiduel dans le fichier de secret, supprime la clé de la configuration et journalise un avertissement. Une valeur que Facet a lui-même publiée est remplacée au lieu d'être reprise, ce qui déconnecte tout le monde délibérément.

| Emplacement | Méthode |
|-------------|---------|
| Par défaut | `.facet_secret` à côté de `scoring_config.json`, mode `0600` |
| Conteneur / orchestrateur | Variable d'environnement `FACET_JWT_SECRET` — lue en premier, jamais écrite sur disque |
| Rotation | `python database.py --rotate-secret`, puis redémarrer le viewer |

Sous Docker, `/app` est la couche inscriptible du conteneur : un secret créé là est perdu à la recréation du conteneur — tout le monde est déconnecté à chaque mise à jour de l'image. Définissez `FACET_JWT_SECRET` dans `docker-compose.yml`, ou montez le fichier avec `- ./.facet_secret:/app/.facet_secret`.

Effectuez une rotation dès que le secret a pu être lu par un tiers : une configuration commitée un jour, une sauvegarde divulguée, le départ d'un administrateur. La rotation invalide chaque session et chaque URL de cadre signée : les utilisateurs se reconnectent et les appareils kiosque récupèrent de nouveaux liens.

Avec `--workers > 1`, tous les workers lisent le même fichier : un JWT signé par l'un est validé par tous — **une fois que ce fichier existe**. Un premier démarrage avec `--workers > 1` et sans `.facet_secret` fait exception : chaque worker génère son propre secret et un seul remporte l'écriture, si bien qu'une session ouverte sur un worker est rejetée par les autres jusqu'au redémarrage du serveur. Créez le secret avant le premier démarrage multi-worker — lancez `python database.py --rotate-secret` une fois, démarrez une fois avec `--workers 1`, ou définissez `FACET_JWT_SECRET`.

Cette divergence devient permanente si le répertoire d'installation n'est pas inscriptible : le serveur journalise une erreur et fonctionne sur un secret en mémoire, donc chaque session meurt à chaque redémarrage et chaque worker signe avec une clé différente. Définissez-y `FACET_JWT_SECRET`.

Sauvegardez ce fichier avec la base de données — restaurer une base sans lui déconnecte tout le monde.

## Configuration multi-utilisateur

Pour attribuer à chaque utilisateur un ensemble privé de répertoires de photos, ajoutez une section `users` à `scoring_config.json`. Voir [Configuration](CONFIGURATION.md#utilisateurs) pour la référence complète.

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

Les chemins des répertoires doivent correspondre aux chemins de photos stockés dans la base de données. Si vous utilisez `viewer.path_mapping`, les répertoires doivent employer les chemins **mappés** (tels qu'ils apparaissent sur l'hôte de la galerie web).

### Migration des notes existantes

Si vous aviez des notes en mode mono-utilisateur, migrez-les vers un utilisateur :

```bash
python database.py --migrate-user-preferences --user alice
```

### Bouton de scan

Pour permettre au superadmin de déclencher des scans de photos depuis l'interface de la galerie web (utile uniquement lorsque la galerie tourne sur la machine GPU) :

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

La base de données SQLite peut atteindre plusieurs dizaines de gigaoctets (`photo_scores_pro.db` atteint environ 14 Go après le scoring de plus de 20 000 photos), et un re-scan coûte du temps GPU. [Litestream](https://litestream.io/) diffuse en continu le WAL vers S3, B2, GCS, SFTP ou un autre disque local, avec restauration à un instant précis à quelques secondes près.

Facet ne fournit pas Litestream. Installez-le une fois sur l'hôte exécutant la galerie web/le scoring ; il tourne comme un processus annexe (sidecar), transparent pour l'application.

Facet utilise déjà le mode WAL (`db/connection.py:apply_pragmas`), et le thread de checkpoint périodique (toutes les 30 min par défaut, configurable via `performance.wal_checkpoint_minutes`) maintient le WAL borné. Les lectures restent non bloquées pendant la réplication.

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

`litestream.env` contient les identifiants AWS / B2 pour les garder hors du YAML.

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

Pour la base de 14 Go avec environ 50 Mo/jour de variation du WAL pendant le scoring actif, prévoyez :
- environ 0,30 $/mois pour le stockage sur S3 Standard
- environ 0,05 $/mois pour les opérations PUT
Négligeable comparé à un re-scan : environ 50 heures-GPU sur une RTX 16 Go.
