# Installation

> 🌐 **English** · [Français](fr/INSTALLATION.md) · [Deutsch](de/INSTALLATION.md) · [Italiano](it/INSTALLATION.md) · [Español](es/INSTALLATION.md) · [Português](pt/INSTALLATION.md)

Facet runs on your own machine. Pick the section that matches your setup, copy the
block, and you are done. The [Advanced](#advanced) half at the bottom is only there
when you need it.

## Which install is for me?

| Your situation | Go to |
|----------------|-------|
| Windows, macOS or Linux, and you just want it running | [Install with Docker](#install-with-docker) |
| Linux or macOS, and you prefer no containers | [Install without Docker](#install-without-docker) |
| A NAS, or a server you want to reach from other machines | [Deployment](DEPLOYMENT.md) |

## Which profile fits my hardware?

Facet ships four *profiles*. A profile is just a set of AI models sized for your
machine — you pick one during install and can change it later.

| Your hardware | Profile | What you get |
|---------------|---------|--------------|
| No graphics card | `legacy` | Everything works — scoring, faces, tags, culling, the gallery — just slower. |
| NVIDIA card, 6–14 GB | `8gb` | The same models as `legacy`, run on the graphics card instead of the processor. |
| NVIDIA card, 14–20 GB | `16gb` | The strongest photo scoring, plus AI tags and captions written by the machine. |
| NVIDIA card, 20 GB or more | `24gb` | The largest models, plus written explanations of a photo's composition. |
| Apple Silicon Mac (M1–M4) | picked for you | Facet uses the Mac's graphics cores and sizes the profile from your memory. |

Not sure how much memory your card has? Skip it — the *Auto-detect* block below
figures it out for you.

## Install with Docker

You need [Docker](https://docs.docker.com/get-started/get-docker/). If your machine
has an NVIDIA card, you also need the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
so Docker can reach it — on Windows, that means running Facet inside WSL2
([step-by-step guide](DEPLOYMENT.md#windows-wsl2-with-an-nvidia-gpu)).

Every block below starts from scratch. Pick **one**.

### Auto-detect my hardware

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # open .env and set PHOTOS_DIR to your photo folder
docker compose up -d
```

Open <http://localhost:5000>.

### No graphics card

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # open .env and set PHOTOS_DIR to your photo folder
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Open <http://localhost:5000>.

### 8 GB graphics card

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # open .env and set PHOTOS_DIR to your photo folder
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Open <http://localhost:5000>.

### 16 GB graphics card

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # open .env and set PHOTOS_DIR to your photo folder
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Open <http://localhost:5000>.

### 24 GB graphics card

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # open .env and set PHOTOS_DIR to your photo folder
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Open <http://localhost:5000>.

### Everyday commands

The gallery is empty until you score your photos. Inside Docker your photo folder is
always called `/data/photos`, whatever it is called on your machine:

```bash
docker compose exec facet python facet.py /data/photos   # score your photos
docker compose logs -f                                   # watch what it is doing
docker compose down                                      # stop it
```

To start it again later, re-run the same `docker compose … up -d` line you used above.

## Install without Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` finds your graphics card, installs everything that matches it, and builds
the web gallery. Then, every time you use Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # score your photos
python viewer.py                       # start the gallery
```

Open <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

On an Apple Silicon Mac this uses the Mac's graphics cores automatically. Then, every
time you use Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # score your photos
python viewer.py                       # start the gallery
```

Open <http://localhost:5000>.

> **Port 5000 is already taken?** macOS uses it for AirPlay. Start the gallery with
> `python viewer.py --port 5001` and open <http://localhost:5001> instead.

### Windows

Use [Docker](#install-with-docker). To use an NVIDIA card on Windows, follow the
[WSL2 guide](DEPLOYMENT.md#windows-wsl2-with-an-nvidia-gpu) — it is the tested path.

## First run: what to expect

- **A download.** The first scan fetches the AI models for your profile — roughly
  4.7 GB for `legacy`, 6.9 GB for `8gb`, 14.6 GB for `16gb`, 19.1 GB for `24gb`
  (full breakdown in [Download sizes](#download-sizes)). This happens once; later
  runs start immediately.
- **No setup.** There is nothing to configure. Facet creates its database on the first
  scan and ships with working settings.
- **Your photos are not modified.** Scanning only reads them; results go to Facet's own
  database. Writing ratings and keywords back to your files is a separate, opt-in action
  ([Interop](INTEROP.md)).
- **Time.** A first scan of a large library takes a while, and it is markedly slower on a
  processor than on a graphics card. Progress is printed as it goes, and you can browse
  the gallery while it works.

## Check it worked

```bash
python facet.py --doctor                             # without Docker
docker compose exec facet python facet.py --doctor   # with Docker
```

This prints what Facet found: your graphics card, the profile it picked, and anything
missing. If the gallery is running, <http://localhost:5000/health> answers `ok`.

Something not working? See [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts)
and [GPU detection issues](#gpu-detection-issues) below.

---

# Advanced

Everything past this point is optional: what the install actually does, how to change
it, and the full dependency reference.

- [Docker settings you can change](#docker-settings-you-can-change)
- [Choosing the profile yourself](#choosing-the-profile-yourself)
- [Install by hand, without install.sh](#install-by-hand-without-installsh)
- [install.sh options and Makefile shortcuts](#installsh-options-and-makefile-shortcuts)
- [exiftool](#exiftool)
- [ONNX Runtime for face detection](#onnx-runtime-for-face-detection)
- [GPU face clustering with RAPIDS cuML](#gpu-face-clustering-with-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Download sizes](#download-sizes)
- [Dependencies](#dependencies)
- [Feature requirements](#feature-requirements)
- [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts)
- [Angular client](#angular-client)

## Docker settings you can change

Deploy knobs live in `.env` (copy `.env.example`):

| Key | Default | Purpose |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Host folder mounted read-write at `/data/photos` (writable so XMP sidecars can be written next to the originals) |
| `PORT` | `5000` | Host port for the gallery |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — overrides `models.vram_profile` without editing any JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Database path inside the container, kept on the `./data` bind mount |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | config's `auto_retrain` | Personal-ranker retrain trigger, for heavy raters |

A sanitized `scoring_config.default.json` is baked into the image as the seed config.
`docker-entrypoint.sh` copies it, on first run only, into the persistent
`./facet-config/scoring_config.json` that `docker-compose.yml` already bind-mounts (as
`FACET_CONFIG=/config/scoring_config.json` inside the container) — so the container runs
with zero host setup, and every runtime config write (the viewer password upgrade,
weights, priorities, scoring contexts) survives `docker compose down && up`. Edit
`./facet-config/scoring_config.json` directly to customize weights, the viewer password
or categories by hand; an existing file is never overwritten.

Model caches live in Docker-managed named volumes (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`), so the image never reads your machine's own
caches and the models survive restarts. `docker compose down -v` deletes them and forces
a re-download.

The image bundles `exiftool` but **not** darktable, so the viewer's optional
RAW/darktable-profile download stays inert unless you extend the image with a
`darktable-cli` binary. Everything else works regardless.

## Choosing the profile yourself

The per-profile files (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) each set `FACET_VRAM_PROFILE` and,
for the GPU profiles, reserve the NVIDIA device. `docker-compose.gpu.yml` is the generic
alternative: it reserves the GPU but leaves the profile to the config's own
`vram_profile` (default `auto`).

Two images are published from one `Dockerfile`: `ghcr.io/ncoevoet/facet:latest` is a
slim CPU build (~3.3 GB unpacked on disk, approximate — pulling it transfers less,
4.18 GB compressed; see [Download sizes](#download-sizes)), `ghcr.io/ncoevoet/facet:latest-cuda`
carries CUDA and RAPIDS cuML (~21 GB unpacked on disk, approximate; 7.33 GB compressed
to pull) and is what the GPU profiles pull. Both are `linux/amd64` only — on an ARM
machine, build locally with `docker compose build` instead of pulling. `docker compose build`
(or `up --build`) always builds from this repository; see the `BASE_IMAGE`, `STRIP_TORCH`
and `INSTALL_CUML` build args in the `Dockerfile`.

Without Docker, the same choice is an environment variable or a config key:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

The exact thresholds `auto` applies are in
[Configuration › VRAM auto-detection](CONFIGURATION.md#vram-auto-detection).

## Install by hand, without install.sh

Requires Python 3.12 (3.10+ works) and Node.js 20+ for the gallery build.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install PyTorch first, with the index URL matching your CUDA version.
#    cu128 targets CUDA 12.8+/13.x; use cu118 for CUDA 11.8, cu124 for CUDA 12.4.
#    When unsure, copy the command from https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Install the rest in one go, so pip can resolve the whole graph at once.
#    requirements.txt already includes transformers and accelerate, needed by the
#    SigLIP/BiRefNet/VLM models the 8gb+ profiles use.
pip install -r requirements.txt

# 4. Install ONE ONNX Runtime for face detection (see the table below)
pip install onnxruntime-gpu>=1.17.0   # or: pip install onnxruntime>=1.15.0

# 5. Build the web gallery
cd client && npm install && npx ng build && cd ..

# 6. Run it
python facet.py /path/to/photos
python viewer.py
```

Verify the environment in one line:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Hitting errors? See [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts).

## install.sh options and Makefile shortcuts

`install.sh` locates a Python 3.10+, creates the `venv`, detects the OS and GPU (Apple
Silicon → Metal, otherwise `nvidia-smi` → matching CUDA build), installs PyTorch, the
right ONNX Runtime, `requirements.txt`, `transformers` and `accelerate`, checks for
`exiftool`, builds the Angular client and verifies every import.

| Flag | Effect |
|------|--------|
| `--cpu` | Force CPU-only PyTorch (no CUDA) |
| `--cuda VERSION` | Override the detected CUDA version (e.g. `--cuda 12.8`) |
| `--skip-client` | Skip the Angular frontend build |
| `--no-uv` | Use pip instead of uv |

| Make target | Runs |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, auto-detected or CPU-only |
| `make client` | Rebuild the Angular frontend |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU or NVIDIA |
| `make test` / `make test-cov` | pytest, with or without coverage |
| `make clean` | Remove `venv`, `client/dist`, `client/node_modules` |

## exiftool

exiftool gives the best EXIF extraction for every format. Without it Facet falls back to
`exifread` (a Python library that handles all RAW formats), then to PIL (JPEG/TIFF/DNG
only).

| OS | Command |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download from [exiftool.org](https://exiftool.org/) |

## ONNX Runtime for face detection

Face detection (InsightFace) runs on ONNX Runtime, which ships in CPU and GPU variants.
Install exactly one:

| Setup | Command |
|--------|---------|
| CPU only | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Check your CUDA version with `nvidia-smi` — it is printed in the top-right corner. To
switch an existing install from CPU to GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## GPU face clustering with RAPIDS cuML

For large face databases (80k+ faces), cuML speeds clustering up considerably. It needs
a conda environment:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# or: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

When cuML is available, clustering uses the GPU automatically (`face_clustering.use_gpu`
in `scoring_config.json`). The Docker CUDA image already bundles it, so containerized
`8gb`/`16gb`/`24gb` profiles cluster on the GPU with no extra step; `legacy` always
clusters on the processor.

## Apple Silicon (Metal/MPS)

No separate GPU package is needed. Install with `bash install.sh`, then confirm that
`python facet.py --doctor` reports `Facet runtime device: mps`. Facet enables PyTorch's
CPU fallback for unsupported operators by default. To compare:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Set `FACET_DEVICE=cpu` to disable acceleration, or `FACET_DEVICE=mps` to require it (and
fail clearly if it is unavailable). InsightFace stays on the processor because it is an
ONNX Runtime model, not a PyTorch one.

Metal has no dedicated video memory, so `vram_profile: "auto"` is sized from total
unified memory:

| Total unified memory | Profile selected by `auto` |
|----------------------|----------------------------|
| under 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB and above | `24gb` |

Each threshold asks for roughly twice the profile's model footprint, because unified
memory is shared with macOS, the window server and every other running application — a
Mac that swaps is slower than one on a smaller profile. An explicitly configured profile
is always honoured as written, so set one to override these thresholds in either
direction.

## Download sizes

Models download on first use into `~/.cache/huggingface/` (Hugging Face models),
`~/.cache/torch/hub/` (PyIQA weights) and `~/.insightface/` (face detection/recognition),
or the Docker named volumes. `samp_net.pth`, `u2netp.pth`, `face_landmarker.task` and the
CLIP-MLP aesthetic head's `aesthetic_predictor_weights.pth` (`legacy`/`8gb` only) all land
in `pretrained_models/`, resolved against the repository root rather than the process's
working directory — in Docker that's the mapped `facet-pretrained` volume, so none of them
re-download on container recreation. No model weights are baked into the image.

Sizes below are decimal (GB = 10⁹ bytes, MB = 10⁶ bytes), measured from the local model
caches and the Hugging Face API.

| Model | Size | Profiles |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + CLIP tagging + CLIP-MLP aesthetic) | 1.711 GB | `legacy`/`8gb` |
| Aesthetic-MLP head (`sac+logos+ava1-l14-linearMSE.pth`) | 3.7 MB | `legacy`/`8gb` only |
| SigLIP 2 NaFlex SO400M (embeddings) | 4.581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (VLM tagging) | 4.571 GB | `16gb` |
| Qwen3.5-4B (VLM tagging) | 9.343 GB | `24gb` |
| Qwen2-VL-2B (composition) | 4.430 GB | none by default — only if you manually set `composition_model: "qwen2-vl-2b"` **and** `processing.mode: "single-pass"` |
| InsightFace buffalo_l (faces) | 289 MB download / 630 MB on disk (the zip is kept alongside the extracted `.onnx` files) | all |
| SAMP-Net weights (composition) | 183 MB | all |
| U2-Net-P (SAMP-Net's saliency sub-model) | 4.7 MB | same as SAMP-Net |
| BiRefNet_dynamic (subject saliency) | 445 MB | all |
| TOPIQ NR (aesthetic model) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (supplementary aesthetic) | 873 MB | all |
| TOPIQ NR-Face (supplementary face quality) | 376 MB | all |
| LIQE (supplementary quality/distortion) | 708 MB | all |
| timm resnet50.a1_in1k (shared PyIQA backbone) | 102 MB | all |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2.235 GB | `8gb`/`16gb`/`24gb`, **on by default** (`"auto"` resolves to enabled on every profile but `legacy`) |

Totals per profile (download): `legacy` 4.69 GB · `8gb` 6.93 GB · `16gb` 14.55 GB ·
`24gb` 19.32 GB · `24gb` with `composition_model: "qwen2-vl-2b"` and
`processing.mode: "single-pass"` 23.56 GB (the manual override replaces SAMP-Net/U2-Net-P
rather than adding to them).

For reference, pulling the Docker image itself (before any model downloads) transfers
`ghcr.io/ncoevoet/facet:latest` at 4.18 GB compressed and `:latest-cuda` at 7.33 GB
compressed, per the current registry manifests.

Opt-in models not counted in the totals above:

| Model | Size | Trigger |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16.41 GB | off by default |
| SigLIP so400m-patch14-384 backbone (`iqa_extended.aesthetic_v25`) | 3.515 GB | off by default, **deprecated** (AGPL-3.0, unmaintained upstream — prefer `qrealign`) |
| Helsinki-NLP OPUS-MT, per target language (caption translation) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | only for the languages you enable |
| MediaPipe `face_landmarker.task` | 3.76 MB | only when `mediapipe` is installed |

`reverse_geocoder` needs no download — its data ships inside the wheel.

SAMP-Net weights come from the project's
[model-weights-v1 release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
If that download fails (offline or restricted network) you will see
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` — fetch the file
manually and place it at `pretrained_models/samp_net.pth`.

## Dependencies

### Required packages

| Package | Purpose |
|---------|---------|
| `torch`, `torchvision` | Deep learning framework (installed separately, see above) |
| `open-clip-torch` | CLIP embeddings/tagging (legacy/8gb profiles) |
| `pyiqa` | TOPIQ and other quality/aesthetic models |
| `opencv-python` | Image processing |
| `pillow` | Image loading |
| `imagehash` | Perceptual hashing for burst detection |
| `rawpy` | RAW file support |
| `fastapi`, `uvicorn` | API server |
| `pyjwt` | JWT authentication |
| `numpy` | Numerical operations |
| `tqdm` | Progress bars |
| `exifread` | EXIF metadata extraction |
| `insightface` | Face detection and recognition |
| `transformers`, `accelerate` | SigLIP/BiRefNet/VLM models (8gb+ profiles) |
| `scipy` | Scientific computing |
| `hdbscan` | Face clustering (pulls in scikit-learn) |
| `reverse_geocoder` | Reverse geocoding for GPS |
| `psutil` | Batch-processing auto-tuning (system monitoring) |
| `aiosqlite` | Async SQLite for FastAPI read endpoints |
| `sqlite-vec` | On-disk KNN for semantic search & similarity (falls back to in-memory NumPy cache if missing) |

All of these are in `requirements.txt`; no profile needs extra base packages.

### Optional packages

Each unlocks a feature; without it the feature is skipped or a fallback is used.

| Package | Unlocks / purpose | Without it |
|---------|-------------------|-----------|
| `watchdog` | Watch mode (`--watch` daemon re-scans new files) — **not in `requirements.txt`**; only pulled via `pip install .[watch]`, so direct `requirements.txt` users don't get `--watch` | `--watch` unavailable |
| `pillow-heif` | HEIF/HEIC decode | HEIF/HEIC files skipped |
| `rawpy` | RAW decode (CR2/CR3/NEF/ARW/…) | RAW files skipped (already in base `requirements.txt`) |
| `cuml`, `cupy` | GPU-accelerated face clustering (conda + CUDA) | Clustering runs on CPU via `hdbscan` (default) |
| `onnxruntime-gpu` | GPU-accelerated face detection | CPU `onnxruntime` (slower) |
| `aesthetic-predictor-v2-5` | Extended IQA tier — `aesthetic_v25` scorer (`pip install -e .[iqa-extended]`; `iqa_extended.aesthetic_v25` in `scoring_config.json`, off by default). **Deprecated** — AGPL-3.0, unmaintained upstream since 2024-12-18; prefer `qrealign`, which needs no extra package (ships with the base `pyiqa` dependency) | `aesthetic_v25` unavailable |
| `darktable-cli` (system) | RAW/darktable profile export from the viewer | Only original/embedded download offered |
| `exiftool` (system) | Best EXIF/GPS extraction | Falls back to `exifread`, then PIL |

## Feature requirements

Most of Facet runs anywhere (CPU, any profile). Some features need a GPU, a higher **VRAM profile**, an optional package, or the viewer's **edition password** / **superadmin** role. Tags used throughout the docs:
`[GPU]` · `[16gb/24gb]` (VRAM profile) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Feature | GPU | Profile | Auth | Optional package |
|---------|:---:|---------|:----:|------------------|
| Scoring / scan (baseline) | optional | any (`legacy` = CPU) | — | — |
| TOPIQ aesthetic | yes | `16gb`/`24gb` | — | — |
| Supplementary IQA (TOPIQ IAA, NR-Face, LIQE) | optional | any (`legacy` = CPU) | — | — |
| SigLIP 2 embeddings | yes | `16gb`/`24gb` | — | — |
| VLM tagging (Qwen3.5) | yes | `16gb`/`24gb` | — | — |
| Composition pattern (SAMP-Net) | optional | any (`legacy` = CPU) | — | — |
| Subject saliency (BiRefNet) | optional | any (`legacy` = CPU) | — | — |
| AI captions (generate / view) | yes | `16gb`/`24gb` | — | — |
| AI captions (edit) | yes | `16gb`/`24gb` | edition | — |
| VLM critique | yes | `16gb`/`24gb` | — | — |
| Face detection / extraction (InsightFace) | recommended (CPU works, slow) | any | — | — |
| Face clustering (HDBSCAN) | no (CPU) | any | — | `cuml`/`cupy` (optional GPU accel) |
| Semantic search | no | any | — | `sqlite-vec` (falls back to NumPy) |
| RAW / HEIF decode | no | any | — | `rawpy` / `pillow-heif` |
| Watch mode (`--watch`) | no | any | — | `watchdog` |
| GPS extract / darktable export | no | any | — | `exiftool` / `darktable-cli` |
| Ratings, favorites, face & person edits, culling | no | any | edition | — |
| Trigger scans from the web UI | no | any | superadmin | — |
| Multi-user (per-user ratings & roles) | no | any | role-based | — |

> Face *clustering* runs on CPU by default (standalone `hdbscan`); `cuml`/`cupy` only add optional GPU acceleration — they are **not** required. The edition password and user roles are configured in `scoring_config.json` — see [Configuration](CONFIGURATION.md) for auth.

> No local GPU? Point VLM tagging, captions and critique at a remote Ollama or
> OpenAI-compatible server with `vlm_backend` in `scoring_config.json` — those features
> then work on the CPU `legacy`/`8gb` profiles too.

## Troubleshooting dependency conflicts

Facet has many ML dependencies (`torch`, `open-clip-torch`, `insightface`, etc.) that pull in their own transitive dependencies. pip resolves dependencies sequentially, which can lead to cascading errors where installing one package breaks another.

**Symptoms:** installing packages one by one triggers errors asking for yet another
package; version conflicts between `torch`, `numpy`, `huggingface-hub` or
`open-clip-torch`; `pip install` succeeds but `import` fails at runtime.

**1. Install everything at once** — `pip install -r requirements.txt` gives pip the full dependency graph to solve. Don't install packages individually (`pip install open-clip-torch && pip install insightface && ...`); that prevents pip from resolving the full graph.

**2. Use [uv](https://docs.astral.sh/uv/) instead of pip** — `uv` resolves the complete dependency graph upfront before installing anything, avoiding cascading conflicts:

```bash
pip install uv
uv pip install -r requirements.txt
# With the CUDA index for PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Start fresh** — if your environment is already broken, `deactivate`, `rm -rf venv`,
and redo [Install by hand](#install-by-hand-without-installsh) (or just re-run `install.sh`).

### GPU detection issues

If your GPU is not detected (common with newer cards), run the diagnostic:

```bash
python facet.py --doctor
```

It checks PyTorch CUDA support and driver compatibility, and suggests the correct pip
command. You can also simulate hardware for testing:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular client

Only needed for development or custom builds — `install.sh` and the Docker image already
build it.

```bash
cd client
npm install
npm run build    # Production build → client/dist/
npm start        # Dev server on http://localhost:4200 (proxies API to :5000)
```

> **`npm audit` warnings:** Angular pulls in a deep transitive dependency tree and
> `npm audit` will report findings, most of them in build-time dev dependencies that
> never reach the browser. Review the list before running `npm audit fix` — it can
> silently downgrade or remove packages.
