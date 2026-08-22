# Installation

> 🌐 [English](../INSTALLATION.md) · **Français** · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md)

Facet s'exécute sur votre propre machine. Choisissez la section qui correspond à votre
situation, copiez le bloc, et c'est terminé. La moitié [Avancé](#avancé) tout en bas n'est
utile que si vous en avez besoin.

## Quelle installation me convient ?

| Votre situation | Aller à |
|----------------|-------|
| Windows, macOS ou Linux, et vous voulez juste que ça tourne | [Installer avec Docker](#installer-avec-docker) |
| Linux ou macOS, et vous préférez éviter les conteneurs | [Installer sans Docker](#installer-sans-docker) |
| Un NAS, ou un serveur que vous voulez atteindre depuis d'autres machines | [Déploiement](DEPLOYMENT.md) |

## Quel profil correspond à mon matériel ?

Facet propose quatre *profils*. Un profil est simplement un jeu de modèles IA dimensionné
pour votre machine — vous en choisissez un pendant l'installation et pouvez en changer plus
tard.

| Votre matériel | Profil | Ce que vous obtenez |
|---------------|---------|--------------|
| Pas de carte graphique | `legacy` | Tout fonctionne — évaluation, visages, tags, tri, galerie — juste plus lentement. |
| Carte NVIDIA, 6–14 Go | `8gb` | Les mêmes modèles que `legacy`, exécutés sur la carte graphique plutôt que sur le processeur. |
| Carte NVIDIA, 14–20 Go | `16gb` | L'évaluation de photos la plus poussée, avec des tags et légendes IA rédigés par la machine. |
| Carte NVIDIA, 20 Go ou plus | `24gb` | Les modèles les plus volumineux, avec des explications rédigées sur la composition d'une photo. |
| Mac Apple Silicon (M1–M4) | choisi pour vous | Facet utilise les cœurs graphiques du Mac et dimensionne le profil selon votre mémoire. |

Vous ne savez pas combien de mémoire a votre carte ? Ignorez cette question — le bloc
*Détection automatique* ci-dessous s'en charge pour vous.

## Installer avec Docker

Il vous faut [Docker](https://docs.docker.com/get-started/get-docker/). Si votre machine
dispose d'une carte NVIDIA, il vous faut aussi le
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
pour que Docker puisse l'atteindre — sous Windows, cela signifie exécuter Facet dans WSL2
([guide pas à pas](DEPLOYMENT.md#windows-wsl2-avec-un-gpu-nvidia)).

Chaque bloc ci-dessous part de zéro. Choisissez-en **un seul**.

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

### Commandes du quotidien

La galerie est vide tant que vous n'avez pas évalué vos photos. À l'intérieur de Docker,
votre dossier de photos s'appelle toujours `/data/photos`, quel que soit son nom sur votre
machine :

```bash
docker compose exec facet python facet.py /data/photos   # évaluer vos photos
docker compose logs -f                                   # suivre ce qu'il se passe
docker compose down                                       # l'arrêter
```

Pour le redémarrer plus tard, relancez la même ligne `docker compose … up -d` que vous
avez utilisée ci-dessus.

## Installer sans Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` détecte votre carte graphique, installe tout ce qui lui correspond, et
compile la galerie web. Ensuite, à chaque utilisation de Facet :

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

Sur un Mac Apple Silicon, cela utilise automatiquement les cœurs graphiques du Mac.
Ensuite, à chaque utilisation de Facet :

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # évaluer vos photos
python viewer.py                       # démarrer la galerie
```

Ouvrez <http://localhost:5000>.

> **Le port 5000 est déjà utilisé ?** macOS s'en sert pour AirPlay. Démarrez la galerie
> avec `python viewer.py --port 5001` et ouvrez <http://localhost:5001> à la place.

### Windows

Utilisez [Docker](#installer-avec-docker). Pour utiliser une carte NVIDIA sous Windows,
suivez le [guide WSL2](DEPLOYMENT.md#windows-wsl2-avec-un-gpu-nvidia) — c'est le chemin
testé.

## Premier lancement : à quoi s'attendre

- **Un téléchargement.** Le premier scan récupère les modèles IA de votre profil —
  environ 4,7 Go pour `legacy`, 6,9 Go pour `8gb`, 14,6 Go pour `16gb`, 19,1 Go pour
  `24gb` (détail complet dans [Tailles de téléchargement](#tailles-de-téléchargement)).
  Cela n'arrive qu'une fois ; les lancements suivants démarrent immédiatement.
- **Aucune configuration.** Il n'y a rien à paramétrer. Facet crée sa base de données au
  premier scan et fonctionne avec des réglages par défaut opérationnels.
- **Vos photos ne sont pas modifiées.** Le scan se contente de les lire ; les résultats
  vont dans la base de données de Facet. Réécrire les notes et les mots-clés dans vos
  fichiers est une action distincte, que vous déclenchez vous-même ([Interopérabilité](INTEROP.md)).
- **Le temps.** Un premier scan d'une grande bibliothèque prend du temps, et il est
  nettement plus lent sur un processeur que sur une carte graphique. La progression
  s'affiche au fur et à mesure, et vous pouvez parcourir la galerie pendant ce temps.

## Vérifier que ça fonctionne

```bash
python facet.py --doctor                             # sans Docker
docker compose exec facet python facet.py --doctor   # avec Docker
```

Cela affiche ce que Facet a trouvé : votre carte graphique, le profil choisi, et tout ce
qui manque. Si la galerie tourne, <http://localhost:5000/health> répond `ok`.

Quelque chose ne fonctionne pas ? Consultez
[Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances) et
[Problèmes de détection du GPU](#problèmes-de-détection-du-gpu) ci-dessous.

---

# Avancé

Tout ce qui suit est optionnel : ce que l'installation fait réellement, comment la
modifier, et la référence complète des dépendances.

- [Réglages Docker modifiables](#réglages-docker-modifiables)
- [Choisir le profil soi-même](#choisir-le-profil-soi-même)
- [Installation manuelle, sans install.sh](#installation-manuelle-sans-installsh)
- [Options d'install.sh et raccourcis Makefile](#options-dinstallsh-et-raccourcis-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime pour la détection de visages](#onnx-runtime-pour-la-détection-de-visages)
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
| `PHOTOS_DIR` | `./photos` | Dossier hôte monté en lecture-écriture sur `/data/photos` (inscriptible pour que les fichiers annexes XMP puissent être écrits à côté des originaux) |
| `PORT` | `5000` | Port hôte pour la galerie |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — remplace `models.vram_profile` sans éditer le moindre JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Chemin de la base de données à l'intérieur du conteneur, conservé sur le montage `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` de la config | Déclencheur de réentraînement du classeur personnel, pour les utilisateurs qui notent beaucoup |

Une version assainie de `scoring_config.default.json` est intégrée à l'image comme
configuration de départ. `docker-entrypoint.sh` la copie, au premier démarrage
uniquement, dans le fichier persistant `./facet-config/scoring_config.json` que
`docker-compose.yml` monte déjà (sous la forme `FACET_CONFIG=/config/scoring_config.json`
dans le conteneur) — le conteneur tourne donc sans aucune configuration côté hôte, et
chaque écriture de configuration à l'exécution (mise à niveau du mot de passe d'édition,
poids, priorités, contextes de notation) survit désormais à un `docker compose down &&
up`. Éditez directement `./facet-config/scoring_config.json` pour personnaliser à la main
les poids, le mot de passe d'édition ou les catégories ; un fichier déjà présent n'est
jamais écrasé.

Les caches de modèles vivent dans des volumes nommés gérés par Docker
(`facet-hf-cache`, `facet-torch-cache`, `facet-insightface`, `facet-pretrained`), si
bien que l'image ne lit jamais les caches propres à votre machine et que les modèles
survivent aux redémarrages. `docker compose down -v` les supprime et force un nouveau
téléchargement.

L'image embarque `exiftool` mais **pas** darktable, si bien que le téléchargement
optionnel de profil RAW/darktable de la galerie reste inerte à moins d'étendre l'image
avec un binaire `darktable-cli`. Tout le reste fonctionne quoi qu'il en soit.

## Choisir le profil soi-même

Les fichiers par profil (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) définissent chacun
`FACET_VRAM_PROFILE` et, pour les profils GPU, réservent le périphérique NVIDIA.
`docker-compose.gpu.yml` est l'alternative générique : il réserve le GPU mais laisse le
profil au `vram_profile` propre à la configuration (par défaut `auto`).

Deux images sont publiées à partir d'un seul `Dockerfile` : `ghcr.io/ncoevoet/facet:latest`
est une version CPU allégée (~3,3 Go décompressés sur disque, valeur approximative —
la récupérer transfère moins, 4,18 Go compressés ; voir
[Tailles de téléchargement](#tailles-de-téléchargement)), `ghcr.io/ncoevoet/facet:latest-cuda`
embarque CUDA et RAPIDS cuML (~21 Go décompressés sur disque, approximatif ; 7,33 Go
compressés à récupérer) et c'est elle que récupèrent les profils GPU. Les deux sont
uniquement en `linux/amd64` — sur une machine ARM, compilez localement avec
`docker compose build` plutôt que de récupérer l'image. `docker compose build`
(ou `up --build`) compile toujours depuis ce dépôt ; voir les arguments de compilation
`BASE_IMAGE`, `STRIP_TORCH` et `INSTALL_CUML` dans le `Dockerfile`.

Sans Docker, le même choix se fait via une variable d'environnement ou une clé de
configuration :

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Les seuils exacts appliqués par `auto` se trouvent dans
[Configuration › Détection automatique de la VRAM](CONFIGURATION.md#détection-automatique-de-la-vram).

## Installation manuelle, sans install.sh

Nécessite Python 3.12 (3.10+ fonctionne) et Node.js 20+ pour la compilation de la
galerie.

```bash
# 1. Créer et activer un environnement virtuel
python3 -m venv venv
source venv/bin/activate

# 2. Installer d'abord PyTorch, avec l'URL d'index correspondant à votre version CUDA.
#    cu128 cible CUDA 12.8+/13.x ; utilisez cu118 pour CUDA 11.8, cu124 pour CUDA 12.4.
#    En cas de doute, copiez la commande depuis https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Installer le reste en une seule fois, pour que pip puisse résoudre tout le graphe d'un coup.
#    requirements.txt inclut déjà transformers et accelerate, nécessaires pour les
#    modèles SigLIP/BiRefNet/VLM utilisés par les profils 8gb et supérieurs.
pip install -r requirements.txt

# 4. Installer UN SEUL ONNX Runtime pour la détection de visages (voir le tableau ci-dessous)
pip install onnxruntime-gpu>=1.17.0   # ou : pip install onnxruntime>=1.15.0

# 5. Compiler la galerie web
cd client && npm install && npx ng build && cd ..

# 6. L'exécuter
python facet.py /path/to/photos
python viewer.py
```

Vérifiez l'environnement en une seule ligne :

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Des erreurs ? Consultez
[Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances).

## Options d'install.sh et raccourcis Makefile

`install.sh` repère un Python 3.10+, crée le `venv`, détecte l'OS et le GPU (Apple
Silicon → Metal, sinon `nvidia-smi` → build CUDA correspondant), installe PyTorch, la
bonne variante d'ONNX Runtime, `requirements.txt`, `transformers` et `accelerate`,
vérifie la présence d'`exiftool`, compile le client Angular et vérifie chaque import.

| Option | Effet |
|------|--------|
| `--cpu` | Force PyTorch en mode CPU uniquement (sans CUDA) |
| `--cuda VERSION` | Remplace la version de CUDA détectée (ex. `--cuda 12.8`) |
| `--skip-client` | Ignore la compilation du frontend Angular |
| `--no-uv` | Utilise pip au lieu de uv |

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

exiftool offre la meilleure extraction EXIF pour tous les formats. Sans lui, Facet se
rabat sur `exifread` (une bibliothèque Python qui gère tous les formats RAW), puis sur
PIL (JPEG/TIFF/DNG uniquement).

| OS | Commande |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Téléchargez-le depuis [exiftool.org](https://exiftool.org/) |

## ONNX Runtime pour la détection de visages

La détection de visages (InsightFace) s'exécute via ONNX Runtime, disponible en
variantes CPU et GPU. Installez-en exactement une :

| Configuration | Commande |
|--------|---------|
| CPU uniquement | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Vérifiez votre version de CUDA avec `nvidia-smi` — elle s'affiche dans le coin supérieur
droit. Pour faire basculer une installation existante du CPU vers le GPU :

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## Regroupement de visages sur GPU avec RAPIDS cuML

Pour les grandes bases de visages (80 000+ visages), cuML accélère considérablement le
regroupement. Il nécessite un environnement conda :

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# ou : pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

Lorsque cuML est disponible, le regroupement utilise automatiquement le GPU
(`face_clustering.use_gpu` dans `scoring_config.json`). L'image Docker CUDA l'embarque
déjà, si bien que les profils conteneurisés `8gb`/`16gb`/`24gb` regroupent sur le GPU
sans étape supplémentaire ; `legacy` regroupe toujours sur le processeur.

## Apple Silicon (Metal/MPS)

Aucun paquet GPU séparé n'est nécessaire. Installez avec `bash install.sh`, puis
vérifiez que `python facet.py --doctor` indique `Facet runtime device: mps`. Facet
active par défaut le repli sur CPU de PyTorch pour les opérateurs non pris en charge.
Pour comparer :

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Définissez `FACET_DEVICE=cpu` pour désactiver l'accélération, ou `FACET_DEVICE=mps`
pour l'exiger (et échouer clairement si elle n'est pas disponible). InsightFace reste
sur le processeur car c'est un modèle ONNX Runtime, pas un modèle PyTorch.

Metal n'a pas de mémoire vidéo dédiée : `vram_profile: "auto"` est donc dimensionné à
partir de la mémoire unifiée totale :

| Mémoire unifiée totale | Profil sélectionné par `auto` |
|----------------------|----------------------------|
| moins de 16 Go | `legacy` |
| 16-31 Go | `8gb` |
| 32-47 Go | `16gb` |
| 48 Go et plus | `24gb` |

Chaque seuil demande environ le double de l'empreinte mémoire des modèles du profil,
car la mémoire unifiée est partagée avec macOS, le serveur graphique et toutes les
autres applications en cours d'exécution — un Mac qui recourt au swap est plus lent
qu'un Mac sur un profil plus modeste. Un profil explicitement configuré est toujours
respecté tel quel : définissez-en un pour outrepasser ces seuils dans un sens comme
dans l'autre.

## Tailles de téléchargement

Les modèles se téléchargent à la première utilisation dans `~/.cache/huggingface/`
(modèles Hugging Face), `~/.cache/torch/hub/` (poids PyIQA) et `~/.insightface/`
(détection/reconnaissance de visages), ou les volumes nommés Docker. `samp_net.pth`,
`u2netp.pth`, `face_landmarker.task` et le `aesthetic_predictor_weights.pth` de la tête
esthétique CLIP-MLP (`legacy`/`8gb` uniquement) atterrissent tous dans
`pretrained_models/`, résolu par rapport à la racine du dépôt plutôt qu'au répertoire de
travail du processus — sous Docker, c'est le volume monté `facet-pretrained`, donc aucun
d'eux ne se retélécharge à la recréation du conteneur. Aucun poids de modèle n'est
intégré à l'image.

Les tailles ci-dessous sont décimales (Go = 10⁹ octets, Mo = 10⁶ octets), mesurées à
partir des caches de modèles locaux et de l'API Hugging Face.

| Modèle | Taille | Profils |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + tagging CLIP + esthétique CLIP-MLP) | 1,711 Go | `legacy`/`8gb` |
| Tête esthétique MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 Mo | `legacy`/`8gb` uniquement |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 Go | `16gb`/`24gb` |
| Qwen3.5-2B (tagging par VLM) | 4,571 Go | `16gb` |
| Qwen3.5-4B (tagging par VLM) | 9,343 Go | `24gb` |
| Qwen2-VL-2B (composition) | 4,430 Go | aucun par défaut — uniquement si vous définissez manuellement `composition_model: "qwen2-vl-2b"` **et** `processing.mode: "single-pass"` |
| InsightFace buffalo_l (visages) | 289 Mo téléchargés / 630 Mo sur disque (le zip est conservé à côté des fichiers `.onnx` extraits) | tous |
| Poids SAMP-Net (composition) | 183 Mo | tous |
| U2-Net-P (sous-modèle de saillance de SAMP-Net) | 4,7 Mo | même profils que SAMP-Net |
| BiRefNet_dynamic (saillance du sujet) | 445 Mo | tous |
| TOPIQ NR (modèle esthétique) | 181 Mo | `16gb`/`24gb` |
| TOPIQ IAA (esthétique complémentaire) | 873 Mo | tous |
| TOPIQ NR-Face (qualité des visages complémentaire) | 376 Mo | tous |
| LIQE (qualité/distorsion complémentaire) | 708 Mo | tous |
| timm resnet50.a1_in1k (backbone PyIQA partagé) | 102 Mo | tous |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 Go | `8gb`/`16gb`/`24gb`, **activé par défaut** (`"auto"` s'active sur tous les profils sauf `legacy`) |

Totaux par profil (téléchargement) : `legacy` 4,69 Go · `8gb` 6,93 Go ·
`16gb` 14,55 Go · `24gb` 19,32 Go · `24gb` avec `composition_model: "qwen2-vl-2b"` et
`processing.mode: "single-pass"` 23,56 Go (le remplacement manuel se substitue à
SAMP-Net/U2-Net-P plutôt que de s'y ajouter).

Pour référence, télécharger l'image Docker elle-même (avant tout téléchargement de
modèle) transfère `ghcr.io/ncoevoet/facet:latest` sur 4,18 Go compressés et
`:latest-cuda` sur 7,33 Go compressés, d'après les manifestes actuels du registre.

Modèles optionnels non comptés dans les totaux ci-dessus :

| Modèle | Taille | Déclencheur |
|-------|------|----------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 Go | désactivé par défaut |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 Go | désactivé par défaut, **déprécié** (AGPL-3.0, non maintenu en amont — préférer `qrealign`) |
| Helsinki-NLP OPUS-MT, par langue cible (traduction des légendes) | en→fr 303 Mo · en→de 298 Mo · en→es 312 Mo · en→it 343 Mo · en→pt 465 Mo | uniquement pour les langues activées |
| MediaPipe `face_landmarker.task` | 3,76 Mo | uniquement si `mediapipe` est installé |

`reverse_geocoder` ne nécessite aucun téléchargement : ses données sont
embarquées dans le wheel.

Les poids SAMP-Net proviennent de la
[version model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)
du projet. Si ce téléchargement échoue (hors ligne ou réseau restreint), vous verrez
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` — récupérez le fichier
manuellement et placez-le à `pretrained_models/samp_net.pth`.

## Dépendances

### Paquets requis

| Paquet | Rôle |
|---------|---------|
| `torch`, `torchvision` | Framework d'apprentissage profond (installé séparément, voir ci-dessus) |
| `open-clip-torch` | Embeddings/tagging CLIP (profils legacy/8gb) |
| `pyiqa` | TOPIQ et autres modèles de qualité/esthétique |
| `opencv-python` | Traitement d'image |
| `pillow` | Chargement d'image |
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
| `sqlite-vec` | KNN sur disque pour la recherche sémantique et la similarité (repli sur le cache d'embeddings NumPy en mémoire s'il est absent) |

Tous ces paquets figurent dans `requirements.txt` ; aucun profil ne nécessite de
paquets de base supplémentaires.

### Paquets optionnels

Chacun débloque une fonctionnalité ; sans lui, la fonctionnalité est ignorée ou une
solution de repli est utilisée.

| Paquet | Débloque / rôle | Sans lui |
|---------|-------------------|-----------|
| `watchdog` | Mode surveillance (le démon `--watch` re-scanne les nouveaux fichiers) — **absent de `requirements.txt`** ; uniquement installé via `pip install .[watch]`, donc les utilisateurs de `requirements.txt` direct n'ont pas `--watch` | `--watch` indisponible |
| `pillow-heif` | Décodage HEIF/HEIC | Les fichiers HEIF/HEIC sont ignorés |
| `rawpy` | Décodage RAW (CR2/CR3/NEF/ARW/…) | Les fichiers RAW sont ignorés (déjà dans le `requirements.txt` de base) |
| `cuml`, `cupy` | Clustering de visages accéléré sur GPU (conda + CUDA) | Le clustering s'exécute sur CPU via `hdbscan` (par défaut) |
| `onnxruntime-gpu` | Détection de visages accélérée sur GPU | `onnxruntime` sur CPU (plus lent) |
| `aesthetic-predictor-v2-5` | Palier IQA étendu — évaluateur `aesthetic_v25` (`pip install -e .[iqa-extended]` ; `iqa_extended.aesthetic_v25` dans `scoring_config.json`, désactivé par défaut). **Déprécié** — AGPL-3.0, sans maintenance depuis le 2024-12-18 ; préférez `qrealign`, qui ne nécessite aucun paquet supplémentaire (livré avec la dépendance de base `pyiqa`) | `aesthetic_v25` indisponible |
| `darktable-cli` (système) | Export RAW/profil darktable depuis la galerie | Seul le téléchargement original/intégré est proposé |
| `exiftool` (système) | Meilleure extraction EXIF/GPS | Repli sur `exifread`, puis PIL |

## Exigences par fonctionnalité

L'essentiel de Facet fonctionne partout (CPU, n'importe quel profil). Certaines
fonctionnalités nécessitent un GPU, un **profil VRAM** plus élevé, un paquet optionnel,
ou le **mot de passe d'édition** / le rôle **superadmin** du visualiseur. Étiquettes
utilisées tout au long de la documentation :
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
| Légendes IA (générer / consulter) | oui | `16gb`/`24gb` | — | — |
| Légendes IA (modifier) | oui | `16gb`/`24gb` | edition | — |
| Critique VLM | oui | `16gb`/`24gb` | — | — |
| Détection / extraction de visages (InsightFace) | recommandé (le CPU fonctionne, lentement) | tout | — | — |
| Regroupement de visages (HDBSCAN) | non (CPU) | tout | — | `cuml`/`cupy` (accélération GPU optionnelle) |
| Recherche sémantique | non | tout | — | `sqlite-vec` (repli sur NumPy) |
| Décodage RAW / HEIF | non | tout | — | `rawpy` / `pillow-heif` |
| Mode surveillance (`--watch`) | non | tout | — | `watchdog` |
| Extraction GPS / export darktable | non | tout | — | `exiftool` / `darktable-cli` |
| Notes, favoris, édition des visages et personnes, tri | non | tout | edition | — |
| Déclencher des analyses depuis l'interface web | non | tout | superadmin | — |
| Multi-utilisateur (notes et rôles par utilisateur) | non | tout | par rôle | — |

> Le *regroupement* de visages s'exécute par défaut sur CPU (paquet `hdbscan`
> autonome) ; `cuml`/`cupy` n'ajoutent qu'une accélération GPU optionnelle — ils ne sont
> **pas** requis. Le mot de passe d'édition et les rôles utilisateur se configurent dans
> `scoring_config.json` — voir [Configuration](CONFIGURATION.md) pour l'authentification.

> Pas de GPU local ? Pointez le tagging, les légendes et la critique VLM vers un
> serveur Ollama ou compatible OpenAI distant via `vlm_backend` dans
> `scoring_config.json` — ces fonctionnalités fonctionnent alors aussi sur les profils
> CPU `legacy`/`8gb`.

## Résoudre les conflits de dépendances

Facet a de nombreuses dépendances ML (`torch`, `open-clip-torch`, `insightface`, etc.)
qui entraînent leurs propres dépendances transitives. pip résout les dépendances de
façon séquentielle, ce qui peut provoquer des erreurs en cascade où l'installation d'un
paquet en casse un autre.

**Symptômes :** installer les paquets un par un déclenche des erreurs réclamant encore
un autre paquet ; des conflits de version entre `torch`, `numpy`, `huggingface-hub` ou
`open-clip-torch` ; `pip install` réussit mais l'`import` échoue à l'exécution.

**1. Tout installer en une fois** — `pip install -r requirements.txt` donne à pip le
graphe complet des dépendances à résoudre. N'installez pas les paquets individuellement
(`pip install open-clip-torch && pip install insightface && ...`) ; cela empêche pip de
résoudre le graphe complet.

**2. Utilisez [uv](https://docs.astral.sh/uv/) au lieu de pip** — `uv` résout le graphe
complet des dépendances en amont avant d'installer quoi que ce soit, évitant les
conflits en cascade :

```bash
pip install uv
uv pip install -r requirements.txt
# Avec l'index CUDA pour PyTorch :
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Repartir de zéro** — si votre environnement est déjà cassé, faites `deactivate`,
`rm -rf venv`, puis refaites
[Installation manuelle, sans install.sh](#installation-manuelle-sans-installsh) (ou
relancez simplement `install.sh`).

### Problèmes de détection du GPU

Si votre GPU n'est pas détecté (fréquent avec les cartes récentes), lancez le
diagnostic :

```bash
python facet.py --doctor
```

Il vérifie la prise en charge de CUDA par PyTorch et la compatibilité du pilote, et
suggère la bonne commande pip. Vous pouvez aussi simuler du matériel pour les tests :

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Client Angular

Nécessaire uniquement pour le développement ou des compilations personnalisées —
`install.sh` et l'image Docker le compilent déjà.

```bash
cd client
npm install
npm run build    # Build de production → client/dist/
npm start        # Serveur de dev sur http://localhost:4200 (redirige l'API vers :5000)
```

> **Avertissements `npm audit` :** Angular entraîne une arborescence de dépendances
> transitives profonde et `npm audit` signalera des problèmes, la plupart concernant
> des dépendances de développement utilisées à la compilation qui n'atteignent jamais le
> navigateur. Examinez la liste avant d'exécuter `npm audit fix` — il peut
> silencieusement rétrograder ou supprimer des paquets.
