# Installation

> 🌐 [English](../INSTALLATION.md) · **Français** · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · [Português](../pt/INSTALLATION.md)

## Démarrage rapide

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # détecte automatiquement le GPU, crée le venv, installe tout

# Activer le venv créé par install.sh — le script d'installation ne peut pas le faire
# à votre place car il s'exécute dans un sous-shell.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # vérifier votre installation
```

`install.sh` crée le venv, détecte le GPU/CUDA, installe PyTorch avec l'URL d'index correspondante, la bonne variante d'ONNX Runtime, le reste des dépendances, et compile le frontend Angular.

**Options :**
| Option | Effet |
|------|--------|
| `--cpu` | Force PyTorch en mode CPU uniquement (sans CUDA) |
| `--cuda VERSION` | Remplace la version de CUDA détectée (ex. `--cuda 12.8`) |
| `--skip-client` | Ignore la compilation du frontend Angular |
| `--no-uv` | Utilise pip au lieu de uv |

Un `Makefile` est également disponible : `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Installation manuelle

### Configuration système requise

- Python 3.12 (3.10+ pris en charge)
- `exiftool` (paquet système, optionnel mais recommandé)

#### Installer exiftool

exiftool offre la meilleure extraction EXIF pour tous les formats. Sans lui, l'application se rabat sur `exifread` (bibliothèque Python, gère tous les formats RAW) puis sur PIL (JPEG/TIFF/DNG uniquement).

| Système d'exploitation | Commande |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | À télécharger depuis [exiftool.org](https://exiftool.org/) |

### Environnement Python

```bash
# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer d'abord PyTorch avec la bonne URL d'index CUDA.
# cu128 cible CUDA 12.8+/13.x ; pour CUDA 11.8 utilisez cu118, pour CUDA 12.4 utilisez cu124.
# En cas de doute, choisissez la commande correspondante sur https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Installer les dépendances (toutes en une fois pour une résolution correcte des dépendances).
# requirements.txt inclut déjà transformers et accelerate, nécessaires pour
# les modèles SigLIP/BiRefNet/VLM utilisés par les profils 8gb et supérieurs.
pip install -r requirements.txt
```

> **Vous rencontrez des erreurs de dépendances ?** Consultez [Résoudre les conflits de dépendances](#résoudre-les-conflits-de-dépendances) ci-dessous.

### Configuration du GPU

#### PyTorch avec CUDA

Installez depuis [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) selon votre version de CUDA. Le script d'installation le fait automatiquement.

#### ONNX Runtime pour la détection de visages

Choisissez UNE option selon votre configuration :

| Option | Commande |
|--------|---------|
| CPU uniquement | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Vérifiez votre version de CUDA :** exécutez `nvidia-smi` et regardez le coin supérieur droit pour « CUDA Version: X.X ».

Si vous passez de la version CPU à la version GPU :
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML pour le clustering de visages sur GPU (optionnel)

Pour les grandes bases de visages (80K+ visages), le clustering accéléré sur GPU via cuML accélère considérablement le clustering de visages. Nécessite un environnement conda :

```bash
# Créer l'environnement conda avec prise en charge de CUDA
conda create -n facet python=3.12
conda activate facet

# Installer cuML (choisissez votre version de CUDA)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternative : pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Installer les autres dépendances
pip install -r requirements.txt
```

Lorsque cuML est disponible, le clustering de visages utilise automatiquement le GPU (configurable via `face_clustering.use_gpu` dans `scoring_config.json`).

## Vérifier l'installation

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Récapitulatif des dépendances

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

Tous ces paquets figurent dans `requirements.txt` ; aucun profil ne nécessite de paquets de base supplémentaires.

### Paquets optionnels

Chacun débloque une fonctionnalité ; sans lui, la fonctionnalité est ignorée ou une solution de repli est utilisée.

| Paquet | Débloque / rôle | Sans lui |
|---------|-------------------|-----------|
| `watchdog` | Mode surveillance (le démon `--watch` re-scanne les nouveaux fichiers) — **absent de `requirements.txt`** ; uniquement installé via `pip install .[watch]`, donc les utilisateurs de `requirements.txt` direct n'ont pas `--watch` | `--watch` indisponible |
| `pillow-heif` | Décodage HEIF/HEIC | Les fichiers HEIF/HEIC sont ignorés |
| `rawpy` | Décodage RAW (CR2/CR3/NEF/ARW/…) | Les fichiers RAW sont ignorés (déjà dans le `requirements.txt` de base) |
| `cuml`, `cupy` | Clustering de visages accéléré sur GPU (conda + CUDA) | Le clustering s'exécute sur CPU via `hdbscan` (par défaut) |
| `onnxruntime-gpu` | Détection de visages accélérée sur GPU | `onnxruntime` sur CPU (plus lent) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Palier IQA étendu (`pip install -e .[iqa-extended]` ; `iqa_extended` dans `scoring_config.json`, désactivé par défaut) | Métriques IQA étendues indisponibles |
| `darktable-cli` (système) | Export RAW/profil darktable depuis la galerie | Seul le téléchargement original/intégré est proposé |
| `exiftool` (système) | Meilleure extraction EXIF/GPS | Repli sur `exifread`, puis PIL |

## Exigences par fonctionnalité

L'essentiel de Facet fonctionne partout (CPU, n'importe quel profil). Certaines fonctionnalités nécessitent un GPU, un **profil VRAM** plus élevé, un paquet optionnel, ou le **mot de passe d'édition** / le rôle **superadmin** du visualiseur. Étiquettes utilisées tout au long de la documentation :
`[GPU]` · `[16gb/24gb]` (profil VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Fonctionnalité | GPU | Profil | Auth | Paquet optionnel |
|---------|:---:|---------|:----:|------------------|
| Évaluation / analyse (de base) | optionnel | tout (`legacy` = CPU) | — | — |
| Esthétique TOPIQ | oui | `16gb`/`24gb` | — | — |
| IQA supplémentaire (TOPIQ IAA, NR-Face, LIQE) | oui | `8gb`/`16gb`/`24gb` | — | — |
| Embeddings SigLIP 2 | oui | `16gb`/`24gb` | — | — |
| Tagging par VLM (Qwen3.5) | oui | `16gb`/`24gb` | — | — |
| Motif de composition (SAMP-Net) | optionnel | tout (`legacy` = CPU) | — | — |
| Composition (Qwen2-VL) | oui | `24gb` | — | — |
| Saillance du sujet (BiRefNet) | oui | `16gb`/`24gb` | — | — |
| Légendes IA (générer / consulter) | oui | `16gb`/`24gb` | — | — |
| Légendes IA (modifier) | oui | `16gb`/`24gb` | edition | — |
| Critique VLM | oui | `16gb`/`24gb` | — | — |
| Détection / extraction de visages (InsightFace) | recommandé (le CPU fonctionne, mais lentement) | tout | — | — |
| Regroupement de visages (HDBSCAN) | non (CPU) | tout | — | `cuml`/`cupy` (accélération GPU optionnelle) |
| Recherche sémantique | non | tout | — | `sqlite-vec` (repli sur NumPy) |
| Décodage RAW / HEIF | non | tout | — | `rawpy` / `pillow-heif` |
| Mode surveillance (`--watch`) | non | tout | — | `watchdog` |
| Extraction GPS / export darktable | non | tout | — | `exiftool` / `darktable-cli` |
| Notes, favoris, édition des visages et personnes, tri | non | tout | edition | — |
| Déclencher des analyses depuis l'interface web | non | tout | superadmin | — |
| Multi-utilisateur (notes et rôles par utilisateur) | non | tout | par rôle | — |

> Le *regroupement* de visages s'exécute par défaut sur CPU (paquet `hdbscan` autonome) ; `cuml`/`cupy` n'ajoutent qu'une accélération GPU optionnelle — ils ne sont **pas** requis. Le mot de passe d'édition et les rôles utilisateur se configurent dans `scoring_config.json` — voir [Configuration](CONFIGURATION.md) pour l'authentification.

## Résoudre les conflits de dépendances

Facet a de nombreuses dépendances ML (`torch`, `open-clip-torch`, `insightface`, etc.) qui entraînent leurs propres dépendances transitives. pip résout les dépendances de façon séquentielle, ce qui peut provoquer des erreurs en cascade où l'installation d'un paquet en casse un autre.

### Symptômes

- L'installation des paquets un par un déclenche des erreurs vous demandant d'installer encore un autre paquet
- Conflits de version entre `torch`, `numpy`, `huggingface-hub` ou `open-clip-torch`
- `pip install` réussit mais l'`import` échoue à l'exécution

### Solutions

**1. Tout installer en une fois** — donne à pip le graphe complet de dépendances à résoudre :

```bash
pip install -r requirements.txt
```

N'installez **pas** les paquets individuellement (`pip install open-clip-torch && pip install insightface && ...`) — cela empêche pip de résoudre le graphe complet.

**2. Utilisez [uv](https://docs.astral.sh/uv/) au lieu de pip** — `uv` résout le graphe complet de dépendances en amont avant d'installer quoi que ce soit, évitant les conflits en cascade :

```bash
# Installer uv
pip install uv

# Installer toutes les dépendances avec résolution complète
uv pip install -r requirements.txt

# Avec l'index CUDA pour PyTorch :
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Repartir de zéro** — si votre environnement est déjà dans un état défaillant, exécutez `deactivate`, `rm -rf venv`, puis reconstruisez-le en réexécutant les étapes [Environnement Python](#environnement-python) ci-dessus.

### Problèmes de détection du GPU

Si votre GPU n'est pas détecté (fréquent avec les GPU récents comme la RTX 5070 Ti), exécutez l'outil de diagnostic :

```bash
python facet.py --doctor
```

Il vérifie la prise en charge de CUDA par PyTorch, la compatibilité du pilote, et suggère la commande pip install correcte. Vous pouvez aussi simuler des scénarios GPU pour les tests :

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Premier lancement

Au premier lancement, Facet télécharge automatiquement le modèle d'embedding correspondant à votre profil :
- CLIP ViT-L-14 (profils legacy/8gb) : ~1,7 Go — ou SigLIP 2 NaFlex SO400M (profils 16gb/24gb), plus volumineux
- le modèle InsightFace buffalo_l : ~400 Mo
- les poids SAMP-Net (tous les profils) : ~50 Mo

Les modèles sont mis en cache à des emplacements standard (`~/.cache/` ou `~/.insightface/`).

## Client Angular (optionnel)

Nécessaire uniquement pour le développement ou les compilations personnalisées ; `install.sh` le compile déjà.

```bash
cd client
npm install
npm run build    # Build de production → client/dist/
npm start        # Serveur de développement sur http://localhost:4200 (proxy de l'API vers :5000)
```

> **Avertissements `npm audit` :** Angular entraîne une arborescence de dépendances transitives profonde
> et `npm audit` signalera des problèmes dont la plupart concernent des dépendances de
> développement utilisées à la compilation qui n'atteignent jamais le navigateur. Examinez la liste avant d'exécuter
> `npm audit fix` — il peut silencieusement rétrograder ou supprimer des paquets.

> **Port 5000 sous macOS :** le récepteur AirPlay de ControlCenter écoute sur 5000 par
> défaut. Démarrez la galerie avec `python viewer.py --port 5001` (ou définissez la
> variable d'environnement `PORT`) pour éviter le conflit.

### Téléchargement manuel de SAMP-Net

Les poids SAMP-Net se téléchargent automatiquement à la première utilisation depuis la version model-weights du projet (`github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth`). Aucune étape manuelle n'est normalement requise.

Si le téléchargement automatique échoue (par exemple hors ligne ou réseau restreint), vous verrez :
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Téléchargez alors manuellement :
1. Téléchargez `samp_net.pth` depuis la [version model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth) (ou, en repli secondaire, [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view))
2. Placez le fichier dans `pretrained_models/samp_net.pth`
