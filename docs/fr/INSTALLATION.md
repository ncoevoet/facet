# Installation

> 🌐 [English](../INSTALLATION.md) · **Français** · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md) · [简体中文](../zh/INSTALLATION.md)

Facet s'exécute sur votre propre machine. Choisissez la section qui correspond à votre
situation et copiez le bloc. La partie [Avancé](#avancé) ne sert que si vous en avez besoin.

## Quelle installation me convient ?

Les deux voies font tourner le même Facet ; elles échangent la simplicité d'installation
contre les performances. Choisissez celle qui vous convient.

| | Docker | Sans Docker |
|---|---|---|
| Installation | Une commande : tout est dans l'image | `install.sh` (Linux, macOS) ou l'installeur Windows crée un environnement Python sur la machine |
| Mise à jour | Récupérer la nouvelle image | Mettre à jour le code et relancer `install.sh`, ou installer le nouvel installeur Windows |
| Performances | Un conteneur se place entre Facet et vos fichiers et votre carte graphique ; sous Windows il tourne dans WSL2 | Facet utilise directement la carte graphique et les fichiers de la machine |

| Votre situation | Aller à |
|----------------|-------|
| Windows, macOS ou Linux, dans un conteneur | [Installer avec Docker](#installer-avec-docker) |
| Windows, macOS ou Linux, sans conteneur | [Installer sans Docker](#installer-sans-docker) |
| Un NAS, ou un serveur que vous voulez atteindre depuis d'autres machines | [Déploiement](DEPLOYMENT.md) |

## Quel profil correspond à mon matériel ?

Un *profil* est un jeu de modèles IA dimensionné pour votre machine. Vous en choisissez un
à l'installation et pouvez en changer plus tard.

| Votre matériel | Profil | Ce que vous obtenez |
|---------------|---------|--------------|
| Pas de carte graphique | `legacy` | Tout fonctionne, juste plus lentement. |
| Carte NVIDIA, 6–14 Go | `8gb` | Les modèles `legacy`, exécutés sur la carte graphique. |
| Carte NVIDIA, 14–20 Go | `16gb` | L'évaluation la plus poussée, avec des tags et légendes IA. |
| Carte NVIDIA, 20 Go ou plus | `24gb` | Les modèles les plus volumineux, avec des explications rédigées sur la composition. |
| Mac Apple Silicon (M1–M4) | choisi pour vous | Utilise les cœurs graphiques du Mac ; profil dimensionné selon la mémoire. |

Vous ne savez pas combien de mémoire a votre carte ? Utilisez le bloc *Détection automatique* ci-dessous.

## Installer avec Docker

Il vous faut [Docker](https://docs.docker.com/get-started/get-docker/). Avec une carte NVIDIA, il vous faut
aussi le
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
Sous Windows, cela signifie exécuter Facet dans WSL2
([guide pas à pas](DEPLOYMENT.md#windows-wsl2-avec-un-gpu-nvidia)).

Chaque bloc part de zéro. Choisissez-en **un seul**.

### Détection automatique de mon matériel

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose up -d
```

Ouvrez <http://localhost:5000>.

### Pas de carte graphique

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Ouvrez <http://localhost:5000>.

### Carte graphique 8 Go

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Ouvrez <http://localhost:5000>.

### Carte graphique 16 Go

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Ouvrez <http://localhost:5000>.

### Carte graphique 24 Go

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # ouvrez .env et définissez PHOTOS_DIR vers votre dossier de photos
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Ouvrez <http://localhost:5000>.

### Ancienne carte NVIDIA (Maxwell, Pascal, Volta)

Les blocs GPU ci-dessus et `docker-compose.gpu.yml` récupèrent `ghcr.io/ncoevoet/facet:latest-cuda`,
qui couvre `sm_75`-`sm_120` (de Turing à Blackwell).

Pour une carte Maxwell, Pascal (série GTX 900/10) ou Volta (par ex. une Titan V), modifiez la ligne
`image:` du fichier compose utilisé (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` ou
`.gpu.yml`) avant `docker compose up -d` :

- remplacez `ghcr.io/ncoevoet/facet:latest-cuda`
- par `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, de Maxwell à Hopper)

Ce tag d'image `-cuda-legacy` n'a rien à voir avec `docker-compose.legacy.yml`, qui sélectionne
le profil `legacy` sur CPU uniquement. Les cartes antérieures à Maxwell (Kepler, Fermi) n'ont pas d'image
CUDA : utilisez le bloc [Pas de carte graphique](#pas-de-carte-graphique).

### Commandes du quotidien

La galerie est vide tant que vous n'avez pas évalué vos photos. À l'intérieur de Docker, votre dossier de photos est
toujours `/data/photos` :

```bash
docker compose exec facet python facet.py /data/photos   # évaluer vos photos
docker compose logs -f                                   # suivre ce qu'il se passe
docker compose down                                      # l'arrêter
```

Pour redémarrer, relancez la ligne `docker compose … up -d` utilisée ci-dessus.

## Installer sans Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` détecte votre carte graphique, installe les paquets correspondants et compile la
galerie web. Ensuite, à chaque utilisation :

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # évaluer vos photos
python viewer.py                       # démarrer la galerie
```

Ouvrez <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

Sur Apple Silicon, cela utilise automatiquement les cœurs graphiques. Ensuite, à chaque utilisation :

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # évaluer vos photos
python viewer.py                       # démarrer la galerie
```

Ouvrez <http://localhost:5000>.

> **Le port 5000 est déjà utilisé ?** macOS s'en sert pour AirPlay. Lancez
> `python viewer.py --port 5001` et ouvrez <http://localhost:5001>.

### Windows

Un installeur par utilisateur (MSI) installe Facet sans droits d'administrateur :

| Dossier | Contenu |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | le programme, remplacé à chaque mise à jour |
| `%LOCALAPPDATA%\Facet\venv` | l'environnement Python, créé à la fin de l'installation |
| `%LOCALAPPDATA%\Facet\data` | la base de données (`photo_scores_pro.db`) et les journaux |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Obtenir l'installeur.** Aucune version publiée n'en fournit encore. Construisez-le depuis un
clone avec `installer\build-msi.ps1` (il faut WiX 3.14, `uv` et le client construit ; le script
indique où trouver WiX), ou téléchargez l'artefact `facet-msi` d'une exécution du workflow
*Windows install (MSI)*. La construction demande Node.js 22.22.3 ou plus récent pour le client
(22.14 échoue sur `npm run build`).

**Premier démarrage.** L'installeur lance la création de l'environnement Python dès qu'il a
terminé. L'environnement pèse environ 6 Go, et le cache de
téléchargement d'uv (`%LOCALAPPDATA%\uv\cache`) en prend à peu près autant. L'entrée *Facet* du
menu Démarrer lance la configuration si elle n'a jamais abouti, et de nouveau après une mise à
jour qui change les dépendances de Facet. Elle choisit la version de PyTorch adaptée à votre
carte NVIDIA et à son pilote comme le fait `install.sh`, ou la version CPU sans carte NVIDIA.
Si la version GPU installée n'atteint pas la carte, l'installation s'arrête et l'explique :
mettez le pilote à jour, ou lancez `Setup-Facet.ps1 -Force -Cpu`.

Si la galerie ne peut pas démarrer (port occupé, échec de la configuration, aucune réponse
après 90 s), la fenêtre de l'entrée du menu Démarrer affiche l'erreur et attend Entrée. Après
90 s sans réponse, la galerie reste lancée et peut encore démarrer.

**Au quotidien :**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # noter les photos ; les arguments en plus vont à facet.py
.\Start-Facet.ps1                # la galerie, sur http://localhost:5000
.\Stop-Facet.ps1                 # arrêter la galerie et tout scan
```

La galerie ne répond que sur cet ordinateur. `Start-Facet.ps1 -Lan` l'ouvre aux autres
appareils et refuse de démarrer tant que `viewer.password` n'est pas défini dans la
configuration.

**Une seule écriture par dossier.** Facet enregistre chaque photo sous le chemin par lequel elle a
été scannée : `\\NAS\Photos` et le même partage monté en `Z:\` sont pour lui deux dossiers
différents, et scanner les deux ajoute chaque photo deux fois. Choisissez-en un et gardez-le.

**Ordinateurs gérés.** Les raccourcis lancent les scripts PowerShell non signés de Facet avec `-ExecutionPolicy Bypass`. Une stratégie d'exécution définie par stratégie de groupe l'emporte, si bien que sur un PC géré les scripts peuvent ne pas s'exécuter ; demandez à son administrateur de les autoriser.

**La désinstallation** (Paramètres, Applications) arrête Facet et supprime le programme, les
raccourcis, l'environnement Python et ExifTool (y compris sous un `FACET_HOME` personnalisé),
et conserve `data` et `config`. Ce qu'elle ne peut pas supprimer est listé dans
`data\logs\uninstall.log`. Le cache de téléchargement d'uv (`%LOCALAPPDATA%\uv\cache`) et les
modèles téléchargés restent (`.cache`, `.insightface` dans votre dossier utilisateur). Une mise à
jour garde un dossier d'installation personnalisé et ne recrée l'environnement que si les
dépendances de Facet ont changé.

**Déplacer une bibliothèque depuis Docker.** La base enregistre le chemin complet de chaque
photo, et l'installation Windows voit les mêmes photos sous un autre chemin
(`\\NAS\Photos\...` au lieu de `/data/photos/...`). Copiez la base dans `data`, arrêtez
Facet, puis réécrivez les chemins, d'abord à blanc :

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

L'outil garde une copie de la base (`photo_scores_pro.db.before-rewrite-<heure>`), refuse de
fusionner une photo déjà scannée sous le nouveau chemin et vide l'index vectoriel, que
`..\venv\Scripts\python.exe database.py --db ..\data\photo_scores_pro.db --populate-vec`
reconstruit. L'historique d'annulation d'avant le déplacement ne s'applique plus. Ces commandes
supposent le dossier d'installation par défaut. Un ancien et un nouveau préfixe dont l'un est
dans l'autre (par exemple `D:\Photos` vers `D:\Photos\new`) sont refusés ; passez par un
préfixe temporaire.

Docker fonctionne aussi sous Windows ; pour une carte NVIDIA, suivez le [guide WSL2](DEPLOYMENT.md#windows-wsl2-avec-un-gpu-nvidia).

## Premier lancement : à quoi s'attendre

- **Un téléchargement.** Le premier scan récupère les modèles de votre profil : environ 4,7 Go pour
  `legacy`, 6,9 Go pour `8gb`, 14,6 Go pour `16gb`, 19,3 Go pour `24gb`
  ([Tailles de téléchargement](#tailles-de-téléchargement)). Cela n'arrive qu'une fois.
- **Aucune configuration pour scanner.** Facet crée sa base de données au premier scan.
- **Lecture seule tant que vous n'avez pas défini de mot de passe.** Pour modifier (noter, trier, albums, personnes), définissez
  `viewer.edition_password` dans `scoring_config.json` et redémarrez la galerie. Avec le
  `docker-compose.yml` fourni, l'image en génère un au premier démarrage.
- **Vos photos ne sont pas modifiées.** Le scan se contente de les lire. Réécrire les notes et les mots-clés
  dans les fichiers est une action distincte, à activer vous-même ([Interopérabilité](INTEROP.md)).
- **Le temps.** Un premier scan d'une grande bibliothèque prend du temps, davantage sur un processeur que sur une
  carte graphique. Vous pouvez parcourir la galerie pendant ce temps.

## Vérifier que ça fonctionne

```bash
python facet.py --doctor                             # sans Docker
docker compose exec facet python facet.py --doctor   # avec Docker
```

Cela affiche votre carte graphique, le profil choisi et tout ce qui manque. Tant que la galerie
tourne, <http://localhost:5000/health> répond `ok`.

Quelque chose ne va pas ? Consultez [Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances)
et [Problèmes de détection du GPU](#problèmes-de-détection-du-gpu).

---

# Avancé

Optionnel : ce que fait l'installation, comment la modifier, et la référence des dépendances.

- [Réglages Docker modifiables](#réglages-docker-modifiables)
- [Choisir le profil soi-même](#choisir-le-profil-soi-même)
- [Installation manuelle, sans install.sh](#installation-manuelle-sans-installsh)
- [Options d'install.sh et raccourcis Makefile](#options-dinstallsh-et-raccourcis-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime pour la détection de visages](#onnx-runtime-pour-la-détection-de-visages)
- [OpenCV en build headless](#opencv-en-build-headless)
- [Regroupement de visages sur GPU avec RAPIDS cuML](#regroupement-de-visages-sur-gpu-avec-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Tailles de téléchargement](#tailles-de-téléchargement)
- [Dépendances](#dépendances)
- [Exigences par fonctionnalité](#exigences-par-fonctionnalité)
- [Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances)
- [Client Angular](#client-angular)

## Réglages Docker modifiables

Les réglages de déploiement se trouvent dans `.env` (copiez `.env.example`) :

| Clé | Défaut | Rôle |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Dossier hôte monté en lecture-écriture sur `/data/photos` (pour que les fichiers annexes XMP puissent être écrits) |
| `PORT` | `5000` | Port hôte pour la galerie |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` ; remplace `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Chemin de la base de données dans le conteneur, sur le montage `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` de la config | Déclencheur de réentraînement du classeur personnel, pour les utilisateurs qui notent beaucoup |

`scoring_config.json` est votre **surcharge**. Les valeurs livrées vivent dans
`config/scoring_config.default.json` à l'intérieur de l'image. Votre fichier ne contient que ce que vous avez
modifié ; tout le reste conserve la valeur livrée et suit les mises à niveau. Voir
[Configuration](CONFIGURATION.md#valeurs-par-défaut-et-votre-surcharge) et
[la référence complète des clés](CONFIGURATION.md).

Au premier lancement, `docker-entrypoint.sh` crée `./facet-config/scoring_config.json` :

- `docker-compose.yml` le monte en bind sous la forme `FACET_CONFIG=/config/scoring_config.json`, si bien que
  les modifications de configuration faites dans la galerie survivent à `docker compose down && up`.
- Sous compose, il contient un `viewer.edition_password` généré, affiché une seule fois dans
  `docker compose logs facet`. Un simple `docker run` sans `FACET_CONFIG` crée une surcharge
  vide et aucun mot de passe.
- Un fichier déjà présent n'est jamais écrasé, et son propriétaire et ses droits restent intacts.

### Propriété du fichier en conteneur

Facet ne fait `chown` et `chmod` que sur un `scoring_config.json` qu'il a lui-même créé.

Une exception : si une configuration préexistante n'est pas **lisible** par l'utilisateur `facet` du conteneur
(uid 1000), l'entrypoint en prend possession et le signale sur stderr. Une configuration illisible
vous verrouillerait hors de l'interface. Pour garder la propriété, rendez-la plutôt lisible :
`chmod o+r facet-config/scoring_config.json`.

Sous Podman/Docker rootless, votre fichier appartient à un uid que l'utilisateur `facet` du conteneur
ne peut pas devenir. Rendez-le **inscriptible par l'utilisateur du conteneur sans perdre la propriété** :

```bash
# 100999 = le subuid hôte auquel l'utilisateur facet du conteneur (uid 1000) est mappé ;
# lisez le vôtre sur un fichier déjà créé par le conteneur : stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

Le fichier reste à vous et éditable, et les écritures de Facet le maintiennent ainsi. Alternatives :
`podman unshare chown` pour éditer un fichier appartenant au conteneur, ou `--userns=keep-id` (ou une
directive `user:` dans le compose) pour que l'utilisateur du conteneur soit vous.

> **Avertissement — migration depuis un ancien fichier compose.** Les versions précédentes montaient
> `- ./scoring_config.json:/app/scoring_config.json`. Le fichier compose livré ne le fait plus.
> Si vous adoptez le nouveau, **déplacez d'abord votre configuration**, sinon vos poids,
> catégories et mot de passe de la galerie ne sont plus lus :
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Si vous conservez votre propre `docker-compose.yml` avec l'ancien montage, `./facet-config` est initialisé
> à partir de ce fichier et rien n'est perdu.
>
> Une configuration reportée telle quelle est une copie complète des anciennes valeurs par défaut. Elle fonctionne toujours, mais vos
> modifications y sont difficiles à repérer. Exécutez `python database.py --compact-config` (Docker :
> `docker compose exec facet python database.py --compact-config`) pour la réduire à ce que vous avez
> changé. Il prend d'abord une sauvegarde en `0600` et se résout sur la même configuration.

Les caches de modèles vivent dans des volumes nommés (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) et survivent aux redémarrages. `docker compose down -v`
les supprime et force un nouveau téléchargement.

L'image embarque `exiftool` mais **pas** darktable. Le téléchargement de profil RAW/darktable de la galerie
reste désactivé à moins d'ajouter un binaire `darktable-cli` à l'image.

## Choisir le profil soi-même

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` définissent chacun `FACET_VRAM_PROFILE` ; ceux pour GPU réservent aussi le
  périphérique NVIDIA.
- `docker-compose.gpu.yml` réserve le GPU et laisse le profil au `vram_profile` de la
  configuration (par défaut `auto`).

Trois images sont publiées :

| Image | Contenu | Décompressée |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Build CPU allégée | 3,34 Go |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, RTX série 50 incluse) ; par défaut pour `8gb`/`16gb`/`24gb` | 13,1 Go |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper) ; voir [Ancienne carte NVIDIA](#ancienne-carte-nvidia-maxwell-pascal-volta) | 13,8 Go |

- Les deux images CUDA embarquent `onnxruntime-gpu` (1.26.0, CUDA 12) à la place de `onnxruntime`, si bien que
  la détection de visages s'exécute sur le GPU. L'image CPU garde `onnxruntime`.
- Les trois sont uniquement en `linux/amd64`. Sur ARM, compilez localement avec `docker compose build`.
- `docker compose build` (ou `up --build`) compile depuis ce dépôt. Arguments de compilation :
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (voir le `Dockerfile`).

Sans Docker, utilisez la variable d'environnement ou la clé de configuration :

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Les seuils utilisés par `auto` se trouvent dans
[Configuration › Détection automatique de la VRAM](CONFIGURATION.md#détection-automatique-de-la-vram).

## Installation commerciale et paquets restreints

`insightface` et `pyiqa` (avec `openai-clip`, `facexlib` et `onnxruntime`, qui ne servent qu'à eux) fournissent des poids de modèles sous conditions non commerciales. Ils ne font pas partie de l'installation de base. Ils
se trouvent dans les extras `faces-insightface` et `iqa` et dans `requirements.restricted.txt` (plus
`requirements.restricted.lock.txt` et `requirements.legacy.restricted.lock.txt` pour Docker).

> **Changement incompatible.** `pip install -e .` et `pip install -r requirements.txt` seuls
> n'incluent plus insightface ni pyiqa. Utilisez `pip install -e .[all]` ou
> `pip install -r requirements.txt -r requirements.restricted.txt`. `install.sh` et l'image Docker
> par défaut installent les deux.

| Objectif | Commande |
|----------|----------|
| Tout (par défaut) | `bash install.sh` ou `pip install -e .[all]` |
| Compatible usage commercial | `bash install.sh --commercial` |
| Commercial, à la main | `pip install -r requirements.txt`, puis `pip install -e .[commercial]` et `pip install mediapipe==0.10.35 --no-deps` |
| Commercial, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` et l'extra `faces-insightface` installent le `onnxruntime` CPU.
  Sur une machine CUDA, faites suivre la commande GPU de
  [ONNX Runtime pour la détection de visages](#onnx-runtime-pour-la-détection-de-visages). `bash install.sh`
  et les images CUDA le font déjà.
- Installez toujours `mediapipe` avec `--no-deps`, sinon son `opencv-contrib-python` installe l'espace de noms
  `cv2` en double. L'extra `commercial` déclare ses dépendances d'exécution (`absl-py`,
  `flatbuffers`).
- `python-ofiq` (les liaisons OFIQ de qualité de visage) n'a de wheels que pour Linux x86-64 et macOS arm64.
  Installez-le à la main avec `pip install python-ofiq` là où il est disponible.

Une installation commerciale ne bascule pas le mode. Réglez-le dans votre surcharge :
`{ "licensing": { "mode": "commercial" } }`. L'argument de build Docker définit aussi
`FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` affiche le mode de licence actif et,
en mode commercial, les composants qu'un scan chargerait (YuNet, SFace, Q-ReAlign).

## Installation manuelle, sans install.sh

Nécessite Python 3.12 (3.10+ fonctionne) et Node.js 20+ pour la compilation de la galerie.

```bash
# 1. Créer et activer un environnement virtuel
python3 -m venv venv
source venv/bin/activate

# 2. Installer d'abord PyTorch, selon votre version de CUDA :
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    Votre CARTE compte aussi : Maxwell/Pascal/Volta (GTX 900/série 10, Titan V) exigent cu126,
#    même avec un pilote CUDA 12.8. Vérifiez : `nvidia-smi --query-gpu=compute_cap --format=csv`
#    En cas de doute, copiez la commande depuis https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Installer le reste en une seule fois, pour que pip résolve tout le graphe
pip install -r requirements.txt -r requirements.restricted.txt

# 4. CUDA uniquement, APRÈS l'étape 3 : installer l'ONNX Runtime GPU (selon votre build CUDA de PyTorch)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # PyTorch CUDA 12.x (cu124, cu126, cu128)
# CPU uniquement, ou CUDA 11.8 (cu118) : conservez ce que l'étape 3 a installé, ou réinstallez-le avec
# pip install "onnxruntime>=1.15.0"

# 5. APRÈS les étapes 3 et 4 : ne garder que le build headless d'OpenCV (celui avec interface exige libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Compiler la galerie web
cd client && npm install && npx ng build && cd ..

# 7. L'exécuter
python facet.py /path/to/photos
python viewer.py
```

L'ordre des étapes compte : pour les paquets qui partagent des fichiers (`onnxruntime`/`onnxruntime-gpu`,
`opencv-python`/`opencv-python-headless`), le dernier installé l'emporte.
`install.sh` applique automatiquement le plancher de la carte et les deux échanges.

Vérifiez l'environnement :

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Des erreurs ? Consultez [Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances).

## Options d'install.sh et raccourcis Makefile

`install.sh` :

1. repère un Python 3.10+ et crée le `venv` ;
2. détecte l'OS et le GPU (Apple Silicon → Metal, sinon `nvidia-smi` → build CUDA correspondant) ;
3. installe PyTorch, `requirements.txt`, `transformers` et `accelerate` ;
4. met en place le bon [ONNX Runtime](#onnx-runtime-pour-la-détection-de-visages) et le
   [build headless d'OpenCV](#opencv-en-build-headless) ;
5. vérifie la présence d'`exiftool`, compile le client Angular et vérifie chaque import (code de sortie 1 si l'un échoue).

| Option | Effet |
|------|--------|
| `--cpu` | Force PyTorch en mode CPU uniquement (sans CUDA) |
| `--cuda VERSION` | Remplace la version de CUDA détectée (ex. `--cuda 12.8`) |
| `--skip-client` | Ignore la compilation du frontend Angular |
| `--no-uv` | Utilise pip au lieu de uv |
| `--commercial` | Installation compatible usage commercial : sans insightface, pyiqa ni ONNX Runtime, mediapipe installé avec `--no-deps` ; vous réglez vous-même `licensing.mode` sur `commercial` |

| Cible Make | Exécute |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, détection automatique ou CPU uniquement |
| `make client` | Recompile le frontend Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU ou NVIDIA |
| `make test` / `make test-cov` | pytest, avec ou sans couverture |
| `make clean` | Supprime `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool offre la meilleure extraction EXIF pour tous les formats. Sans lui, Facet se rabat sur
`exifread` (gère tous les formats RAW), puis sur PIL (JPEG/TIFF/DNG uniquement).

| OS | Commande |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Téléchargez-le depuis [exiftool.org](https://exiftool.org/) |

## ONNX Runtime pour la détection de visages

La détection de visages (InsightFace) s'exécute via ONNX Runtime : `onnxruntime` (CPU) ou
`onnxruntime-gpu` (CUDA). Les deux partagent le répertoire `onnxruntime/`, donc un seul peut être installé ; le dernier
installé par pip l'emporte. `insightface` dépend de la build CPU, si bien que l'installer
(`requirements.restricted.txt`, `pip install -e .[all]`, l'extra `faces-insightface`)
ramène la build CPU. Sur une machine CUDA, installez le paquet GPU **après** ces dépendances,
en retirant d'abord les deux noms.

`bash install.sh` s'en charge sur x86_64 avec un PyTorch CUDA 12, puis teste une vraie session CUDA
(comme `--doctor`). Relancez-le pour réparer un `venv` cassé ou passer du CPU au GPU. Les
images Docker CUDA font de même. Les installations CPU, CUDA 11.8 (cu118), macOS, l'image CPU et
aarch64 (pas de wheel `onnxruntime-gpu` CUDA 12) gardent `onnxruntime`.

À la main, choisissez la ligne qui correspond à la build CUDA de **PyTorch** :

| Build PyTorch | Commande |
|---------------|---------|
| CPU uniquement, ou CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Suivez PyTorch, pas le pilote.** La version de CUDA qu'affiche `nvidia-smi` est la plus récente que le
  pilote prend en charge ; un pilote CUDA 13 exécute toujours le PyTorch cu128. `python facet.py --doctor`
  affiche la build de PyTorch sur sa ligne `CUDA (compiled)`.
- **Gardez la plage de versions.** Les `onnxruntime-gpu` 1.19–1.26 sont des builds CUDA 12 ; la 1.27+ exige des
  bibliothèques CUDA 13. Une installation sans borne semble correcte mais tourne discrètement sur le CPU. Pour un PyTorch CUDA
  13 installé à la main, `"onnxruntime-gpu>=1.27.0"` convient (non testé).
- **CUDA 11.8 n'a pas de build GPU utilisable.** L'ancien `onnxruntime-gpu` CUDA 11 exige cuDNN 8,
  alors que PyTorch cu118 utilise cuDNN 9. Pour la détection de visages sur GPU, mettez le pilote à jour vers un pilote qui annonce
  CUDA 12.4 ou plus récent et relancez `install.sh`.
- **Mettez la dépendance entre guillemets.** Sans guillemets, `pip install onnxruntime-gpu>=1.19.0,<1.27` crée un
  fichier vide nommé `=1.19.0,` et échoue avec `1.27: No such file or directory`. Supprimez ce fichier.
- **Désinstallez les deux noms.** `pip uninstall onnxruntime` puis `pip install onnxruntime-gpu`
  laisse `import onnxruntime` avec un paquet vide, et InsightFace échoue avec
  `module 'onnxruntime' has no attribute 'InferenceSession'`.

Après l'échange, `pip check` signale « insightface ... requires onnxruntime, which is not
installed » (`uv pip check` : « The package `insightface` requires `onnxruntime`, but it's not
installed »). C'est sans conséquence : `onnxruntime-gpu` fournit le même module. De même, après
l'échange d'OpenCV, `insightface` et `facexlib` qui requièrent `opencv-python` est sans conséquence. Un
`pip install -r requirements.txt` ultérieur ramène l'OpenCV avec interface ; refaites
l'[échange d'OpenCV](#opencv-en-build-headless) ou relancez `install.sh`.

**Vérification :** la section **ONNX Runtime** de `python facet.py --doctor` liste le paquet, la
version et les fournisseurs d'exécution, et avertit (avec la correction) quand les deux paquets sont installés
ou que l'import échoue. Sur CUDA, elle exécute une session de test ; la ligne `CUDA session` n'est OK que si
elle tourne réellement sur `CUDAExecutionProvider`. Le test exige le paquet `onnx` et est ignoré
sur CPU et en mode commercial. Un scan sur CUDA avertit aussi une fois quand InsightFace tourne sur le CPU.

Dans Docker, une réparation faite dans le conteneur est perdue au prochain `docker run` : récupérez une image à jour
ou reconstruisez. Les images CUDA installent `onnxruntime-gpu` 1.26.0 via l'argument de build
`ORT_GPU_VERSION` ; ne le réglez jamais sur la 1.27 ou plus récente (CUDA 13).

## OpenCV en build headless

`opencv-python` (avec interface) et `opencv-python-headless` partagent le répertoire `cv2/` ; le dernier
installé l'emporte. Les dépendances de Facet demandent les deux. Le build avec interface exige `libGL.so.1`, que
Debian, WSL et les hôtes allégés n'ont pas : `import cv2` échoue alors avec
`ImportError: libGL.so.1: cannot open shared object file`. Facet n'ouvre aucune fenêtre OpenCV,
donc le build headless suffit.

`bash install.sh` ne garde que le build headless dans tous les modes, y compris `--commercial`.
Les images Docker ne sont pas concernées (elles installent `libgl1`). Pour réparer un `venv` à la main,
remplacez `<version>` par la version que `pip list` affiche pour l'un ou l'autre paquet :

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

La section **OpenCV** de `python facet.py --doctor` affiche `[OK]` quand `cv2` s'importe, ou
l'erreur d'import et la commande de réparation avec votre version. Avoir les deux paquets avec un import
qui fonctionne est normal (les images Docker embarquent les deux, avec `libgl1`). Si un import essentiel comme
`cv2` échoue, `install.sh` affiche « Installation finished with errors » et se termine avec le
code 1.

## Regroupement de visages sur GPU avec RAPIDS cuML

Pour les grandes bases de visages (80 000+ visages), cuML accélère considérablement le regroupement. Il nécessite conda :

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# ou : pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt installe opencv-python, le build avec interface (exige libGL.so.1) : ne gardez que le build headless
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

Avec cuML installé, le regroupement utilise automatiquement le GPU (`face_clustering.use_gpu` dans
`scoring_config.json`). Les images Docker CUDA l'embarquent, si bien que les conteneurs `8gb`/`16gb`/`24gb`
regroupent sur le GPU. `legacy` regroupe toujours sur le processeur.

## Apple Silicon (Metal/MPS)

Aucun paquet GPU supplémentaire n'est nécessaire. Installez avec `bash install.sh`, puis vérifiez que
`python facet.py --doctor` indique `Facet runtime device: mps`. Facet active le repli sur CPU
de PyTorch pour les opérateurs non pris en charge. Pour comparer :

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` désactive l'accélération ; `FACET_DEVICE=mps` l'exige et échoue si elle n'est pas
  disponible. `FACET_DEVICE=cuda` échoue de la même façon quand PyTorch ne voit aucun périphérique CUDA
  (par ex. `CUDA_VISIBLE_DEVICES=''`).
- InsightFace reste sur le processeur (c'est un modèle ONNX Runtime).
- Les scores TOPIQ peuvent différer légèrement de ceux du CPU/CUDA. Sur MPS, une photo dont les côtés ne sont pas
  des multiples de 32 est d'abord recadrée au centre (1024×682 devient 1024×672).

`vram_profile: "auto"` dimensionne le profil à partir de la mémoire unifiée totale :

| Mémoire unifiée totale | Profil sélectionné par `auto` |
|----------------------|----------------------------|
| moins de 16 Go | `legacy` |
| 16-31 Go | `8gb` |
| 32-47 Go | `16gb` |
| 48 Go et plus | `24gb` |

Chaque seuil vaut environ le double de l'empreinte des modèles du profil, car macOS et les autres applications
partagent cette mémoire. Un Mac qui recourt au swap est plus lent qu'un Mac sur un profil plus modeste. Un profil
explicitement défini est toujours respecté tel quel.

### Mémoire sur un Mac

Si le Moniteur d'activité montre Facet utilisant plus de mémoire que n'en possède le Mac, ou si le swap ne cesse de croître
pendant un scan, essayez ceci, dans l'ordre.

**1. Plafonnez le pool mémoire de PyTorch :**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` signifie « la taille de travail recommandée du Mac, pas plus ». Une passe peut alors s'arrêter avec une erreur de
mémoire insuffisante plutôt que de recourir au swap, ce qui vaut mieux que de voir le Mac s'enliser.

**Les poids se chargent un par un.** Sur macOS, Facet définit par défaut `HF_DEACTIVATE_ASYNC_LOAD=1`,
car le chargement concurrent peut faire planter un scan sur MPS. Rien à configurer ; définissez
vous-même `HF_DEACTIVATE_ASYNC_LOAD=0` pour retrouver le chargement concurrent.

**2. Désactivez les deux modèles optionnels les plus lourds.** N'ajoutez que ces clés à
`scoring_config.json` :

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` désactive la détection du sujet ; `qrealign` désactive un modèle de qualité supplémentaire.
L'esthétique, la composition, les visages et la qualité technique restent notés. Utilisez la clé de profil de
votre Mac : `"16gb"` sur 32-47 Go, `"24gb"` à partir de 48 Go.

**3. Traitez moins de photos à la fois :**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Réglez les trois clés, sinon l'auto-réglage fait varier la taille du lot entre `min_ram_chunk_size` et
`max_ram_chunk_size`.

## Tailles de téléchargement

Les modèles se téléchargent à la première utilisation dans :

- `~/.cache/huggingface/` (modèles Hugging Face)
- `~/.cache/torch/hub/` (poids PyIQA)
- `~/.insightface/` (détection/reconnaissance de visages)
- `pretrained_models/` à la racine du dépôt : `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task` et `aesthetic_predictor_weights.pth` (`legacy`/`8gb` uniquement)

Sous Docker, ce sont des volumes nommés (`pretrained_models/` est `facet-pretrained`), si bien que rien
ne se retélécharge à la recréation du conteneur. Aucun poids n'est intégré à l'image.

Les tailles sont décimales (Go = 10⁹ octets, Mo = 10⁶ octets).

| Modèle | Taille | Profils |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + tagging CLIP + esthétique CLIP-MLP) | 1,711 Go | `legacy`/`8gb` |
| Tête esthétique MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 Mo | `legacy`/`8gb` uniquement |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 Go | `16gb`/`24gb` |
| Qwen3.5-2B (tagging par VLM) | 4,571 Go | `16gb` |
| Qwen3.5-4B (tagging par VLM) | 9,343 Go | `24gb` |
| Qwen2-VL-2B (composition) | 4,430 Go | aucun par défaut ; voir la note 1 |
| InsightFace buffalo_l (visages) | 289 Mo téléchargés / 630 Mo sur disque (le zip est conservé à côté des fichiers `.onnx`) | tous |
| Poids SAMP-Net (composition) | 183 Mo | tous |
| U2-Net-P (sous-modèle de saillance de SAMP-Net) | 4,7 Mo | comme SAMP-Net |
| BiRefNet_dynamic (saillance du sujet) | 445 Mo | tous |
| TOPIQ NR (modèle esthétique) | 181 Mo | `16gb`/`24gb` |
| TOPIQ IAA (esthétique complémentaire) | 873 Mo | tous |
| TOPIQ NR-Face (qualité des visages complémentaire) | 376 Mo | tous |
| LIQE (qualité/distorsion complémentaire) | 708 Mo | tous |
| timm resnet50.a1_in1k (backbone PyIQA partagé) | 102 Mo | tous |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 Go | `8gb`/`16gb`/`24gb`, **activé par défaut** (`"auto"`) |

1. Qwen2-VL-2B ne se charge que si vous définissez `composition_model: "qwen2-vl-2b"` **et**
   `processing.mode: "single-pass"`, en remplacement de SAMP-Net/U2-Net-P. Hors mode commercial,
   cela ne fonctionne que sur `legacy`/`8gb` : sur `16gb`/`24gb`, le single-pass bascule en multi-pass,
   qui n'a pas de passe Qwen2-VL.

Totaux par profil (téléchargement) : `legacy` 4,69 Go · `8gb` 6,93 Go · `16gb` 14,55 Go ·
`24gb` 19,32 Go · `24gb` avec la composition Qwen2-VL 23,56 Go (mode commercial uniquement, voir la note 1).

Les images Docker elles-mêmes, avant tout téléchargement de modèle : `latest` 3,34 Go décompressés,
`latest-cuda` 13,1 Go, `latest-cuda-legacy` 13,8 Go
([Déploiement › Taille de l'image](DEPLOYMENT.md#taille-de-limage)). Les tailles de téléchargement compressées ne sont pas
encore mesurées.

Modèles optionnels, non comptés dans les totaux :

| Modèle | Taille | Déclencheur |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 Go | désactivé par défaut |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 Go | désactivé par défaut, **déprécié** (préférez `qrealign`) |
| Helsinki-NLP OPUS-MT, par langue cible (traduction des légendes) | en→fr 303 Mo · en→de 298 Mo · en→es 312 Mo · en→it 343 Mo · en→pt 465 Mo | uniquement pour les langues activées |
| MediaPipe `face_landmarker.task` | 3,76 Mo | uniquement si `mediapipe` est installé |

`reverse_geocoder` ne nécessite aucun téléchargement ; ses données sont embarquées dans le wheel.

Les poids SAMP-Net proviennent de la
[version model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
Si vous voyez `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (hors ligne ou
réseau restreint), téléchargez le fichier et placez-le à `pretrained_models/samp_net.pth`.

## Dépendances

### Paquets requis

| Paquet | Rôle |
|---------|---------|
| `torch`, `torchvision` | Framework d'apprentissage profond (installé séparément, voir ci-dessus) |
| `open-clip-torch` | Embeddings/tagging CLIP (profils legacy/8gb) |
| `pyiqa` | TOPIQ et autres modèles de qualité/esthétique |
| `opencv-python` | Traitement d'image |
| `pillow` | Chargement d'image, y compris PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF nécessite pillow>=11.3) |
| `imagehash` | Hachage perceptuel pour la détection de rafales |
| `rawpy` | Prise en charge des fichiers RAW |
| `fastapi`, `uvicorn` | Serveur d'API |
| `pyjwt` | Authentification JWT |
| `numpy` | Opérations numériques |
| `tqdm` | Barres de progression |
| `exifread` | Extraction des métadonnées EXIF |
| `insightface` | Détection et reconnaissance de visages |
| `transformers`, `accelerate` | Modèles SigLIP/BiRefNet/VLM (profils 8gb+) |
| `scipy` | Calcul scientifique |
| `hdbscan` | Clustering de visages (entraîne scikit-learn) |
| `reverse_geocoder` | Géocodage inverse pour le GPS |
| `psutil` | Auto-réglage du traitement par lots (surveillance système) |
| `aiosqlite` | SQLite asynchrone pour les points d'accès en lecture de FastAPI |
| `sqlite-vec` | Recherche sémantique sur disque (repli sur un cache NumPy en mémoire) ; `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | Photos JPEG XL et aperçus des DNG fusionnés de Lightroom Classic 13+ (HDR/Panorama/Amélioration) |

Tous ces paquets figurent dans `requirements.txt`, sauf `pyiqa` et `insightface`, qui sont dans `requirements.restricted.txt` (voir [Installation commerciale et paquets restreints](#installation-commerciale-et-paquets-restreints)). Aucun profil ne nécessite de paquets de base supplémentaires.

### Paquets optionnels

Chacun débloque une fonctionnalité ; sans lui, la fonctionnalité est ignorée ou une solution de repli est utilisée.

| Paquet | Débloque | Sans lui |
|---------|---------|-----------|
| `watchdog` | Mode surveillance (`--watch`) ; **absent de `requirements.txt`**, à installer avec `pip install .[watch]` | `--watch` indisponible |
| `pillow-heif` | Décodage HEIF/HEIC | Les fichiers HEIF/HEIC sont ignorés |
| `rawpy` | Décodage RAW (CR2/CR3/NEF/ARW/…), déjà dans `requirements.txt` | Les fichiers RAW sont ignorés |
| `cuml`, `cupy` | Regroupement de visages sur GPU (conda + CUDA) | Regroupement sur CPU via `hdbscan` (par défaut) |
| `onnxruntime-gpu` | Détection de visages sur GPU, **à la place de** `onnxruntime` ([détails](#onnx-runtime-pour-la-détection-de-visages)) | `onnxruntime` sur CPU (plus lent) |
| `aesthetic-predictor-v2-5` | Évaluateur `aesthetic_v25` (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, désactivé par défaut). **Déprécié** (AGPL-3.0, sans maintenance depuis le 2024-12-18) ; préférez `qrealign`, qui ne nécessite aucun paquet supplémentaire | `aesthetic_v25` indisponible |
| `darktable-cli` (système) | Export RAW/profil darktable depuis la galerie | Seul le téléchargement original/intégré est proposé |
| `exiftool` (système) | Meilleure extraction EXIF/GPS | Repli sur `exifread`, puis PIL |

## Exigences par fonctionnalité

L'essentiel de Facet fonctionne partout (CPU, n'importe quel profil). Certaines fonctionnalités nécessitent un GPU, un **profil
VRAM** plus élevé, un paquet optionnel, ou le **mot de passe d'édition** / le rôle **superadmin** de la galerie. Étiquettes
utilisées dans la documentation :
`[GPU]` · `[16gb/24gb]` (profil VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Fonctionnalité | GPU | Profil | Auth | Paquet optionnel |
|---------|:---:|---------|:----:|------------------|
| Évaluation / analyse (de base) | optionnel | tout (`legacy` = CPU) | — | — |
| Esthétique TOPIQ | oui | `16gb`/`24gb` | — | — |
| IQA supplémentaire (TOPIQ IAA, NR-Face, LIQE) | optionnel | tout (`legacy` = CPU) | — | — |
| Embeddings SigLIP 2 | oui | `16gb`/`24gb` | — | — |
| Tagging par VLM (Qwen3.5) | oui | `16gb`/`24gb` | — | — |
| Motif de composition (SAMP-Net) | optionnel | tout (`legacy` = CPU) | — | — |
| Saillance du sujet (BiRefNet) | optionnel | tout (`legacy` = CPU) | — | — |
| Légendes IA (générer / consulter) | oui | `16gb`/`24gb` | edition (génération) | — |
| Légendes IA (modifier) | oui | `16gb`/`24gb` | edition | — |
| Critique VLM | oui | `16gb`/`24gb` | edition (génération) | — |
| Détection / extraction de visages (InsightFace) | recommandé (le CPU fonctionne, lentement) | tout | — | — |
| Regroupement de visages (HDBSCAN) | non (CPU) | tout | — | `cuml`/`cupy` (accélération GPU optionnelle) |
| Recherche sémantique | non | tout | — | `sqlite-vec` (repli sur NumPy) |
| Décodage RAW / HEIF | non | tout | — | `rawpy` / `pillow-heif` |
| Mode surveillance (`--watch`) | non | tout | — | `watchdog` |
| Extraction GPS / export darktable | non | tout | — | `exiftool` / `darktable-cli` |
| Notes, favoris, édition des visages et personnes, tri | non | tout | edition | — |
| Déclencher des analyses depuis l'interface web | non | tout | edition (mono-utilisateur) / superadmin (multi-utilisateurs) | — |
| Multi-utilisateur (notes et rôles par utilisateur) | non | tout | par rôle | — |

Le mot de passe d'édition et les rôles utilisateur se configurent dans `scoring_config.json` ; voir
[Configuration](CONFIGURATION.md).

> Pas de GPU local ? Pointez le tagging, les légendes et la critique VLM vers un serveur Ollama ou
> compatible OpenAI distant via `vlm_backend` dans `scoring_config.json`. Ces fonctionnalités
> fonctionnent alors aussi sur les profils `legacy`/`8gb`.

## Résoudre les conflits de dépendances

Les paquets ML de Facet (`torch`, `open-clip-torch`, `insightface`, …) entraînent de nombreuses
dépendances, et les installer un par un peut les faire entrer en conflit.

**Symptômes :** chaque installation réclame encore un autre paquet ; des conflits de version entre
`torch`, `numpy`, `huggingface-hub` ou `open-clip-torch` ; `pip install` réussit mais
l'`import` échoue.

**1. Tout installer en une fois :** `pip install -r requirements.txt`, pour que pip résolve le
graphe complet. N'installez pas les paquets individuellement
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Utilisez [uv](https://docs.astral.sh/uv/) :** `uv` résout le graphe complet avant d'installer :

```bash
pip install uv
uv pip install -r requirements.txt
# Avec l'index CUDA pour PyTorch :
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Repartir de zéro :** `deactivate`, `rm -rf venv`, puis refaites
l'[Installation manuelle](#installation-manuelle-sans-installsh) (ou relancez `install.sh`).

### Problèmes de détection du GPU

Si votre GPU n'est pas détecté (fréquent avec les cartes récentes), lancez :

```bash
python facet.py --doctor
```

Il vérifie la prise en charge de CUDA par PyTorch et le pilote, et suggère la bonne commande pip. Il détecte aussi
ce que `torch.cuda.is_available()` ne voit pas : un GPU pour lequel le PyTorch installé n'a aucun noyau (par ex. RTX série 50 sur une build
CUDA antérieure à 12.8). Dans ce cas, Facet bascule sur le CPU au lieu de planter, et `--doctor` nomme
la correction : sous Docker, le bon tag d'image (`ghcr.io/ncoevoet/facet:latest-cuda-legacy` pour
Maxwell/Pascal/Volta) ; en natif, le bon `--index-url`.

Pour simuler du matériel pour les tests :

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Client Angular

Nécessaire uniquement pour le développement ou des compilations personnalisées ; `install.sh` et l'image Docker
le compilent déjà.

```bash
cd client
npm install
npm run build    # Build de production → client/dist/
npm start        # Serveur de dev sur http://localhost:4200 (redirige l'API vers :5000)
```

> **Avertissements `npm audit` :** la plupart des constats concernent des dépendances de développement utilisées à la compilation qui
> n'atteignent jamais le navigateur. Examinez-les avant d'exécuter `npm audit fix`, qui peut rétrograder ou
> supprimer des paquets.
