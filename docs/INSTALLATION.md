# Installation

> 🌐 **English** · [Français](fr/INSTALLATION.md) · [Deutsch](de/INSTALLATION.md) · [Italiano](it/INSTALLATION.md) · [Español](es/INSTALLATION.md) · [Português](pt/INSTALLATION.md) · [简体中文](zh/INSTALLATION.md)

Facet runs on your own machine. Pick the section that matches your setup and copy the
block. The [Advanced](#advanced) part is only for when you need it.

## Which install is for me?

Both routes run the same Facet; they trade simplicity of installation against
performance. Pick the one that fits you.

| | Docker | Without Docker |
|---|---|---|
| Installing | One command: everything comes in the image | `install.sh` (Linux, macOS) or the Windows installer builds a Python environment on the machine |
| Updating | Pull the new image | Update the code and run `install.sh` again, or install the new Windows installer |
| Performance | A container sits between Facet and your files and graphics card; on Windows it runs inside WSL2 | Facet uses the machine's graphics card and files directly |

| Your situation | Go to |
|----------------|-------|
| Windows, macOS or Linux, in a container | [Install with Docker](#install-with-docker) |
| Windows, macOS or Linux, without containers | [Install without Docker](#install-without-docker) |
| A NAS, or a server you want to reach from other machines | [Deployment](DEPLOYMENT.md) |

## Which profile fits my hardware?

A *profile* is a set of AI models sized for your machine. You pick one at install and can
change it later.

| Your hardware | Profile | What you get |
|---------------|---------|--------------|
| No graphics card | `legacy` | Everything works, just slower. |
| NVIDIA card, 6–14 GB | `8gb` | The `legacy` models, run on the graphics card. |
| NVIDIA card, 14–20 GB | `16gb` | The strongest scoring, plus AI tags and captions. |
| NVIDIA card, 20 GB or more | `24gb` | The largest models, plus written composition explanations. |
| Apple Silicon Mac (M1–M4) | picked for you | Uses the Mac's graphics cores; profile sized from memory. |

Not sure how much memory your card has? Use the *Auto-detect* block below.

## Install with Docker

You need [Docker](https://docs.docker.com/get-started/get-docker/). With an NVIDIA card you
also need the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
On Windows that means running Facet inside WSL2
([step-by-step guide](DEPLOYMENT.md#windows-wsl2-with-an-nvidia-gpu)).

Each block starts from scratch. Pick **one**.

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

### Older NVIDIA card (Maxwell, Pascal, Volta)

The GPU blocks above and `docker-compose.gpu.yml` pull `ghcr.io/ncoevoet/facet:latest-cuda`,
which covers `sm_75`-`sm_120` (Turing through Blackwell).

For a Maxwell, Pascal (GTX 900/10-series) or Volta (e.g. Titan V) card, edit the `image:`
line in the compose file you used (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` or
`.gpu.yml`) before `docker compose up -d`:

- from `ghcr.io/ncoevoet/facet:latest-cuda`
- to `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, Maxwell through Hopper)

This `-cuda-legacy` image tag is unrelated to `docker-compose.legacy.yml`, which selects
the CPU-only `legacy` profile. Cards older than Maxwell (Kepler, Fermi) have no CUDA
image: use the [No graphics card](#no-graphics-card) block.

### Everyday commands

The gallery is empty until you score your photos. Inside Docker your photo folder is
always `/data/photos`:

```bash
docker compose exec facet python facet.py /data/photos   # score your photos
docker compose logs -f                                   # watch what it is doing
docker compose down                                      # stop it
```

To start again, re-run the `docker compose … up -d` line you used above.

## Install without Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

`install.sh` detects your graphics card, installs the matching packages and builds the
web gallery. Then, each time:

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

On Apple Silicon this uses the graphics cores automatically. Then, each time:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # score your photos
python viewer.py                       # start the gallery
```

Open <http://localhost:5000>.

> **Port 5000 is already taken?** macOS uses it for AirPlay. Run
> `python viewer.py --port 5001` and open <http://localhost:5001>.

### Windows

A per-user installer (MSI) sets Facet up without administrator rights:

| Folder | What it holds |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | the program, replaced on upgrade |
| `%LOCALAPPDATA%\Facet\venv` | the Python environment, built when the installer finishes |
| `%LOCALAPPDATA%\Facet\data` | the database (`photo_scores_pro.db`) and logs |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Getting the installer.** No release ships one yet. Build it from a clone with
`installer\build-msi.ps1` (it needs WiX 3.14, `uv` and a built client, and says where to get
WiX), or download the `facet-msi` artifact of a *Windows install (MSI)* workflow run. Building
needs Node.js 22.22.3 or newer for the client (22.14 fails `npm run build`).

**First start.** The installer starts the Python environment setup as soon as it finishes. The environment is about 6 GB, and uv's download cache
(`%LOCALAPPDATA%\uv\cache`) takes about as much again. The *Facet* Start-menu entry runs setup
if it never completed, and again after an upgrade that changes Facet's dependencies. It picks
the PyTorch build for your NVIDIA card and driver the way `install.sh` does, or the CPU build
without an NVIDIA card. If the GPU build it installed cannot reach the card, setup stops and
says so: update the driver, or run `Setup-Facet.ps1 -Force -Cpu`.

If the viewer cannot start (port in use, setup failure, no answer after 90 s), the Start-menu
window shows the error and waits for Enter. After 90 s without an answer the viewer is left
running and may still come up.

**Every day:**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # score photos; extra arguments go to facet.py
.\Start-Facet.ps1                # the gallery, at http://localhost:5000
.\Stop-Facet.ps1                 # stop the gallery and any scan
```

The gallery answers on this computer only. `Start-Facet.ps1 -Lan` opens it to other
devices, and refuses to start until `viewer.password` is set in the config.

**One spelling per folder.** Facet stores each photo under the path it was scanned by, so
`\\NAS\Photos` and the same share mapped as `Z:\` are two different folders to it: scanning
both adds every photo twice. Pick one and keep it.

**Managed computers.** The shortcuts run Facet's unsigned PowerShell scripts with `-ExecutionPolicy Bypass`. An execution policy set by Group Policy overrides that, so on a managed PC the scripts may not run; ask its administrator to allow them.

**Uninstalling** (Settings, Apps) stops Facet and removes the program, its shortcuts, the Python
environment and ExifTool (under a custom `FACET_HOME` too), and keeps `data` and `config`.
Anything it cannot delete is listed in `data\logs\uninstall.log`. uv's download cache
(`%LOCALAPPDATA%\uv\cache`) and the downloaded models stay (`.cache`, `.insightface` in your
user folder). An upgrade keeps a custom install folder, and sets the environment up again only
when Facet's dependencies changed.

**Moving a library from Docker.** The database stores each photo's full path, and the
Windows install sees the same photos under another one (`\\NAS\Photos\...` rather than
`/data/photos/...`). Copy the database into `data`, stop Facet, then rewrite the paths,
with a dry run first:

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

It keeps a copy of the database (`photo_scores_pro.db.before-rewrite-<time>`), refuses to merge
a photo already scanned under the new path, and empties the vector index, which
`..\venv\Scripts\python.exe database.py --db ..\data\photo_scores_pro.db --populate-vec`
rebuilds. Undo history from before the move no longer applies. These commands assume the
default install folder. An old and a new prefix where one lies inside the other (for example
`D:\Photos` to `D:\Photos\new`) are refused; go through a temporary prefix.

Docker works on Windows too; for an NVIDIA card, follow the [WSL2 guide](DEPLOYMENT.md#windows-wsl2-with-an-nvidia-gpu).

## First run: what to expect

- **A download.** The first scan fetches the models for your profile: about 4.7 GB for
  `legacy`, 6.9 GB for `8gb`, 14.6 GB for `16gb`, 19.3 GB for `24gb`
  ([Download sizes](#download-sizes)). This happens once.
- **No setup to scan.** Facet creates its database on the first scan.
- **Read-only until you set a password.** To edit (rate, cull, albums, people), set
  `viewer.edition_password` in `scoring_config.json` and restart the viewer. With the
  bundled `docker-compose.yml`, the image generates one on first start.
- **Your photos are not modified.** Scanning only reads them. Writing ratings and keywords
  back to files is a separate opt-in ([Interop](INTEROP.md)).
- **Time.** A first scan of a large library takes a while, longer on a processor than on a
  graphics card. You can browse the gallery while it runs.

## Check it worked

```bash
python facet.py --doctor                             # without Docker
docker compose exec facet python facet.py --doctor   # with Docker
```

This prints your graphics card, the chosen profile and anything missing. While the gallery
runs, <http://localhost:5000/health> answers `ok`.

Something wrong? See [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts)
and [GPU detection issues](#gpu-detection-issues).

---

# Advanced

Optional: what the install does, how to change it, and the dependency reference.

- [Docker settings you can change](#docker-settings-you-can-change)
- [Choosing the profile yourself](#choosing-the-profile-yourself)
- [Install by hand, without install.sh](#install-by-hand-without-installsh)
- [install.sh options and Makefile shortcuts](#installsh-options-and-makefile-shortcuts)
- [exiftool](#exiftool)
- [ONNX Runtime for face detection](#onnx-runtime-for-face-detection)
- [OpenCV headless build](#opencv-headless-build)
- [GPU face clustering with RAPIDS cuML](#gpu-face-clustering-with-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Download sizes](#download-sizes)
- [Dependencies](#dependencies)
- [Feature requirements](#feature-requirements)
- [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts)
- [Angular client](#angular-client)

## Docker settings you can change

Deploy settings live in `.env` (copy `.env.example`):

| Key | Default | Purpose |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Host folder mounted read-write at `/data/photos` (so XMP sidecars can be written) |
| `PORT` | `5000` | Host port for the gallery |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb`; overrides `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Database path in the container, on the `./data` bind mount |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | config's `auto_retrain` | Personal-ranker retrain trigger, for heavy raters |

`scoring_config.json` is your **override**. The shipped values live in
`config/scoring_config.default.json` inside the image. Your file only holds what you
changed; everything else keeps the shipped value and follows upgrades. See
[Configuration](CONFIGURATION.md#defaults-and-your-override) and
[the full key reference](CONFIGURATION.md).

On first run, `docker-entrypoint.sh` creates `./facet-config/scoring_config.json`:

- `docker-compose.yml` bind-mounts it as `FACET_CONFIG=/config/scoring_config.json`, so
  config changes made in the viewer survive `docker compose down && up`.
- Under compose, it contains a generated `viewer.edition_password`, printed once in
  `docker compose logs facet`. A plain `docker run` without `FACET_CONFIG` creates an empty
  override and no password.
- An existing file is never overwritten, and its owner and mode are left alone.

### Container file ownership

Facet only `chown`s and `chmod`s a `scoring_config.json` it created itself.

One exception: if an existing config is not **readable** by the container's `facet` user
(uid 1000), the entrypoint takes ownership of it and says so on stderr. An unreadable
config would lock you out of the UI. To keep ownership, make it readable instead:
`chmod o+r facet-config/scoring_config.json`.

Under rootless Podman/Docker, your file is owned by a uid the container's `facet` user
cannot become. Make it **writable by the container user while you keep ownership**:

```bash
# 100999 = the host subuid the in-container facet user (uid 1000) maps to;
# read yours off a file the container already made: stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

The file stays yours and editable, and Facet's writes keep it that way. Alternatives:
`podman unshare chown` to edit a container-owned file, or `--userns=keep-id` (or a compose
`user:` override) so the container user *is* you.

> **Warning — upgrading from an older compose file.** Earlier versions mounted
> `- ./scoring_config.json:/app/scoring_config.json`. The shipped compose file no longer
> does. If you adopt the new one, **move your config across first**, or your weights,
> categories and viewer password stop being read:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> If you keep your own `docker-compose.yml` with the old mount, `./facet-config` is seeded
> from that file and nothing is lost.
>
> A carried-across config is a full copy of the old defaults. It still works, but your
> edits are hard to spot. Run `python database.py --compact-config` (Docker:
> `docker compose exec facet python database.py --compact-config`) to reduce it to what you
> changed. It makes a `0600` backup first and resolves to the same configuration.

Model caches live in named volumes (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) and survive restarts. `docker compose down -v`
deletes them and forces a re-download.

The image bundles `exiftool` but **not** darktable. The viewer's RAW/darktable-profile
download stays off unless you add a `darktable-cli` binary to the image.

## Choosing the profile yourself

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` each set `FACET_VRAM_PROFILE`; the GPU ones also reserve the
  NVIDIA device.
- `docker-compose.gpu.yml` reserves the GPU and leaves the profile to the config's
  `vram_profile` (default `auto`).

Three images are published:

| Image | Contents | Unpacked |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Slim CPU build | 3.34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, incl. RTX 50-series); default for `8gb`/`16gb`/`24gb` | 13.1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper); see [Older NVIDIA card](#older-nvidia-card-maxwell-pascal-volta) | 13.8 GB |

- Both CUDA images ship `onnxruntime-gpu` (1.26.0, CUDA 12) instead of `onnxruntime`, so
  face detection runs on the GPU. The CPU image keeps `onnxruntime`.
- All three are `linux/amd64` only. On ARM, build locally with `docker compose build`.
- `docker compose build` (or `up --build`) builds from this repository. Build args:
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (see the `Dockerfile`).

Without Docker, use the environment variable or the config key:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

The thresholds `auto` uses are in
[Configuration › VRAM auto-detection](CONFIGURATION.md#vram-auto-detection).

## Commercial install and the restricted packages

`insightface` and `pyiqa` (plus `openai-clip`, `facexlib` and `onnxruntime`, which only they
need) ship model weights under non-commercial terms. They are not in the base install. They
live in the `faces-insightface` and `iqa` extras and in `requirements.restricted.txt` (plus
`requirements.restricted.lock.txt` and `requirements.legacy.restricted.lock.txt` for Docker).

> **Breaking change.** `pip install -e .` and `pip install -r requirements.txt` alone no
> longer include insightface or pyiqa. Use `pip install -e .[all]` or
> `pip install -r requirements.txt -r requirements.restricted.txt`. `install.sh` and the
> default Docker image install both.

| Goal | Command |
|------|---------|
| Everything (default) | `bash install.sh`, or `pip install -e .[all]` |
| Commercial-safe | `bash install.sh --commercial` |
| Commercial-safe, by hand | `pip install -r requirements.txt`, then `pip install -e .[commercial]` and `pip install mediapipe==0.10.35 --no-deps` |
| Commercial-safe, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` and the `faces-insightface` extra install the CPU `onnxruntime`.
  On a CUDA machine, follow with the GPU command from
  [ONNX Runtime for face detection](#onnx-runtime-for-face-detection). `bash install.sh`
  and the CUDA images already do.
- Always install `mediapipe` with `--no-deps`, or its `opencv-contrib-python` double-installs
  the `cv2` namespace. The `commercial` extra declares its runtime dependencies (`absl-py`,
  `flatbuffers`).
- `python-ofiq` (OFIQ face-quality bindings) has wheels for Linux x86-64 and macOS arm64
  only. Install it by hand with `pip install python-ofiq` where available.

Installing commercially does not switch the mode. Set it in your override:
`{ "licensing": { "mode": "commercial" } }`. The Docker build argument also sets
`FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` shows the active licence
mode and, in commercial mode, the components a scan would load (YuNet, SFace, Q-ReAlign).

## Install by hand, without install.sh

Requires Python 3.12 (3.10+ works) and Node.js 20+ for the gallery build.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install PyTorch first, matching your CUDA version:
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    Your CARD matters too: Maxwell/Pascal/Volta (GTX 900/10-series, Titan V) need cu126,
#    even on a CUDA 12.8 driver. Check: `nvidia-smi --query-gpu=compute_cap --format=csv`
#    Unsure? Copy the command from https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Install the rest in one go so pip resolves the whole graph
pip install -r requirements.txt -r requirements.restricted.txt

# 4. CUDA only, AFTER step 3: swap in the GPU ONNX Runtime (match your PyTorch CUDA build)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # CUDA 12.x PyTorch (cu124, cu126, cu128)
# CPU only, or CUDA 11.8 (cu118): keep what step 3 installed, or reinstall it with
# pip install "onnxruntime>=1.15.0"

# 5. AFTER steps 3 and 4: keep only the headless OpenCV build (the GUI one needs libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Build the web gallery
cd client && npm install && npx ng build && cd ..

# 7. Run it
python facet.py /path/to/photos
python viewer.py
```

Step order matters: packages that share files (`onnxruntime`/`onnxruntime-gpu`,
`opencv-python`/`opencv-python-headless`) are won by whichever installs last.
`install.sh` applies the card floor and both swaps automatically.

Verify the environment:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Errors? See [Troubleshooting dependency conflicts](#troubleshooting-dependency-conflicts).

## install.sh options and Makefile shortcuts

`install.sh`:

1. finds a Python 3.10+ and creates the `venv`;
2. detects the OS and GPU (Apple Silicon → Metal, otherwise `nvidia-smi` → matching CUDA build);
3. installs PyTorch, `requirements.txt`, `transformers` and `accelerate`;
4. swaps in the right [ONNX Runtime](#onnx-runtime-for-face-detection) and the
   [headless OpenCV build](#opencv-headless-build);
5. checks for `exiftool`, builds the Angular client and verifies every import (exit status 1 if one fails).

| Flag | Effect |
|------|--------|
| `--cpu` | Force CPU-only PyTorch (no CUDA) |
| `--cuda VERSION` | Override the detected CUDA version (e.g. `--cuda 12.8`) |
| `--skip-client` | Skip the Angular frontend build |
| `--no-uv` | Use pip instead of uv |
| `--commercial` | Commercial-safe install: skips insightface, pyiqa and ONNX Runtime, installs mediapipe with `--no-deps`; set `licensing.mode` to `commercial` yourself |

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
`exifread` (handles all RAW formats), then to PIL (JPEG/TIFF/DNG only).

| OS | Command |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Download from [exiftool.org](https://exiftool.org/) |

## ONNX Runtime for face detection

Face detection (InsightFace) runs on ONNX Runtime: `onnxruntime` (CPU) or
`onnxruntime-gpu` (CUDA). The two share the `onnxruntime/` directory, so only one can be installed; the last one
pip installs wins. `insightface` depends on the CPU build, so installing it
(`requirements.restricted.txt`, `pip install -e .[all]`, the `faces-insightface` extra)
brings the CPU build back. On a CUDA machine, install the GPU package **after** those,
removing both names first.

`bash install.sh` does this on x86_64 with a CUDA 12 PyTorch, then tests a real CUDA
session (as `--doctor` does). Re-run it to repair a broken `venv` or switch CPU/GPU. The
CUDA Docker images do the same. CPU installs, CUDA 11.8 (cu118), macOS, the CPU image and
aarch64 (no CUDA 12 `onnxruntime-gpu` wheel) keep `onnxruntime`.

By hand, pick the row for your **PyTorch** CUDA build:

| PyTorch build | Command |
|---------------|---------|
| CPU only, or CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Match PyTorch, not the driver.** The CUDA version `nvidia-smi` prints is the newest the
  driver supports; a CUDA 13 driver still runs the cu128 PyTorch. `python facet.py --doctor`
  shows PyTorch's build on its `CUDA (compiled)` line.
- **Keep the version range.** `onnxruntime-gpu` 1.19–1.26 are CUDA 12 builds; 1.27+ need
  CUDA 13 libraries. An unpinned install looks fine but quietly runs on the CPU. For a CUDA
  13 PyTorch installed by hand, `"onnxruntime-gpu>=1.27.0"` matches (untested).
- **CUDA 11.8 has no usable GPU build.** The old CUDA 11 `onnxruntime-gpu` needs cuDNN 8,
  but cu118 PyTorch uses cuDNN 9. For GPU face detection, update the driver to one reporting
  CUDA 12.4 or newer and re-run `install.sh`.
- **Quote the requirement.** Unquoted, `pip install onnxruntime-gpu>=1.19.0,<1.27` creates an
  empty file named `=1.19.0,` and fails with `1.27: No such file or directory`. Delete that file.
- **Uninstall both names.** `pip uninstall onnxruntime` then `pip install onnxruntime-gpu`
  leaves `import onnxruntime` an empty package, and InsightFace fails with
  `module 'onnxruntime' has no attribute 'InferenceSession'`.

After the swap, `pip check` reports "insightface ... requires onnxruntime, which is not
installed" (`uv pip check`: "The package `insightface` requires `onnxruntime`, but it's not
installed"). This is harmless: `onnxruntime-gpu` provides the same module. Likewise after
the OpenCV swap, `insightface` and `facexlib` requiring `opencv-python` is harmless. A later
`pip install -r requirements.txt` brings the GUI OpenCV back; redo the
[OpenCV swap](#opencv-headless-build) or re-run `install.sh`.

**Check it:** the **ONNX Runtime** section of `python facet.py --doctor` lists the package,
version and execution providers, and warns (with the fix) when both packages are installed
or the import fails. On CUDA it runs a test session; the `CUDA session` line is OK only when
it really runs on `CUDAExecutionProvider`. The test needs the `onnx` package and is skipped
on CPU and in commercial mode. A scan on CUDA also warns once when InsightFace runs on the CPU.

In Docker, a repair inside the container is lost on the next `docker run`: pull a current
image or rebuild. The CUDA images set `onnxruntime-gpu` 1.26.0 via the `ORT_GPU_VERSION`
build argument; never set 1.27 or later (CUDA 13).

## OpenCV headless build

`opencv-python` (GUI) and `opencv-python-headless` share the `cv2/` directory; the last one
installed wins. Facet's dependencies pull in both. The GUI build needs `libGL.so.1`, which
Debian, WSL and slim hosts lack, so `import cv2` fails with
`ImportError: libGL.so.1: cannot open shared object file`. Facet opens no OpenCV windows,
so the headless build is enough.

`bash install.sh` keeps only the headless build in every mode, including `--commercial`.
The Docker images are not affected (they install `libgl1`). To repair a `venv` by hand,
replace `<version>` with the version `pip list` shows for either package:

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

The **OpenCV** section of `python facet.py --doctor` shows `[OK]` when `cv2` imports, or
the import error and the repair command with your version filled in. Both packages with a
working import is fine (the Docker images ship both, with `libgl1`). If a core import such
as `cv2` fails, `install.sh` prints "Installation finished with errors" and exits with
status 1.

## GPU face clustering with RAPIDS cuML

For large face databases (80k+ faces), cuML speeds up clustering a lot. It needs conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# or: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt installs opencv-python, the GUI build (needs libGL.so.1): keep only the headless one
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

With cuML installed, clustering uses the GPU automatically (`face_clustering.use_gpu` in
`scoring_config.json`). The CUDA Docker images bundle it, so `8gb`/`16gb`/`24gb` containers
cluster on the GPU. `legacy` always clusters on the processor.

## Apple Silicon (Metal/MPS)

No extra GPU package is needed. Install with `bash install.sh`, then check that
`python facet.py --doctor` reports `Facet runtime device: mps`. Facet enables PyTorch's
CPU fallback for unsupported operators. To compare:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` disables acceleration; `FACET_DEVICE=mps` requires it and fails if
  unavailable. `FACET_DEVICE=cuda` fails the same way when PyTorch sees no CUDA device
  (e.g. `CUDA_VISIBLE_DEVICES=''`).
- InsightFace stays on the processor (it is an ONNX Runtime model).
- TOPIQ scores can differ slightly from CPU/CUDA. On MPS, a photo whose sides are not
  multiples of 32 is centre-cropped first (1024×682 becomes 1024×672).

`vram_profile: "auto"` sizes the profile from total unified memory:

| Total unified memory | Profile selected by `auto` |
|----------------------|----------------------------|
| under 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB and above | `24gb` |

Each threshold is about twice the profile's model footprint, because macOS and other apps
share that memory. A Mac that swaps is slower than one on a smaller profile. An explicitly
set profile is always used as written.

### Memory on a Mac

If Activity Monitor shows Facet using more memory than the Mac has, or swap keeps growing
during a scan, try these in order.

**1. Cap PyTorch's memory pool:**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` means "the Mac's recommended working set, no more". A pass may then stop with "out of
memory" instead of swapping, which is better than the Mac grinding to a halt.

**Weights load one at a time.** On macOS Facet sets `HF_DEACTIVATE_ASYNC_LOAD=1` by
default, because concurrent loading can crash a scan on MPS. Nothing to configure; set
`HF_DEACTIVATE_ASYNC_LOAD=0` yourself to get concurrent loading back.

**2. Turn off the two heaviest optional models.** Add only these keys to
`scoring_config.json`:

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` turns off subject detection; `qrealign` turns off an extra quality
model. Aesthetics, composition, faces and technical quality are still scored. Use your
Mac's profile key: `"16gb"` on 32-47GB, `"24gb"` on 48GB and up.

**3. Process fewer photos at a time:**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Set all three, or auto-tuning moves the chunk size between `min_ram_chunk_size` and
`max_ram_chunk_size`.

## Download sizes

Models download on first use into:

- `~/.cache/huggingface/` (Hugging Face models)
- `~/.cache/torch/hub/` (PyIQA weights)
- `~/.insightface/` (face detection/recognition)
- `pretrained_models/` in the repository root: `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task`, and `aesthetic_predictor_weights.pth` (`legacy`/`8gb` only)

In Docker these are named volumes (`pretrained_models/` is `facet-pretrained`), so nothing
re-downloads when the container is recreated. No weights are baked into the image.

Sizes are decimal (GB = 10⁹ bytes, MB = 10⁶ bytes).

| Model | Size | Profiles |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + CLIP tagging + CLIP-MLP aesthetic) | 1.711 GB | `legacy`/`8gb` |
| Aesthetic-MLP head (`sac+logos+ava1-l14-linearMSE.pth`) | 3.7 MB | `legacy`/`8gb` only |
| SigLIP 2 NaFlex SO400M (embeddings) | 4.581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (VLM tagging) | 4.571 GB | `16gb` |
| Qwen3.5-4B (VLM tagging) | 9.343 GB | `24gb` |
| Qwen2-VL-2B (composition) | 4.430 GB | none by default; see note 1 |
| InsightFace buffalo_l (faces) | 289 MB download / 630 MB on disk (zip kept beside the `.onnx` files) | all |
| SAMP-Net weights (composition) | 183 MB | all |
| U2-Net-P (SAMP-Net's saliency sub-model) | 4.7 MB | same as SAMP-Net |
| BiRefNet_dynamic (subject saliency) | 445 MB | all |
| TOPIQ NR (aesthetic model) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (supplementary aesthetic) | 873 MB | all |
| TOPIQ NR-Face (supplementary face quality) | 376 MB | all |
| LIQE (supplementary quality/distortion) | 708 MB | all |
| timm resnet50.a1_in1k (shared PyIQA backbone) | 102 MB | all |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2.235 GB | `8gb`/`16gb`/`24gb`, **on by default** (`"auto"`) |

1. Qwen2-VL-2B loads only if you set `composition_model: "qwen2-vl-2b"` **and**
   `processing.mode: "single-pass"`, replacing SAMP-Net/U2-Net-P. Outside commercial mode
   this works only on `legacy`/`8gb`: on `16gb`/`24gb` single-pass falls back to multi-pass,
   which has no Qwen2-VL pass.

Totals per profile (download): `legacy` 4.69 GB · `8gb` 6.93 GB · `16gb` 14.55 GB ·
`24gb` 19.32 GB · `24gb` with Qwen2-VL composition 23.56 GB (commercial mode only, see note 1).

The Docker images themselves, before any model download: `latest` 3.34 GB unpacked,
`latest-cuda` 13.1 GB, `latest-cuda-legacy` 13.8 GB
([Deployment › Image size](DEPLOYMENT.md#image-size)). Compressed download sizes are not
measured yet.

Opt-in models, not in the totals:

| Model | Size | Trigger |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16.41 GB | off by default |
| SigLIP so400m-patch14-384 backbone (`iqa_extended.aesthetic_v25`) | 3.515 GB | off by default, **deprecated** (prefer `qrealign`) |
| Helsinki-NLP OPUS-MT, per target language (caption translation) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | only for the languages you enable |
| MediaPipe `face_landmarker.task` | 3.76 MB | only when `mediapipe` is installed |

`reverse_geocoder` needs no download; its data ships in the wheel.

SAMP-Net weights come from the
[model-weights-v1 release](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
If you see `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (offline or
restricted network), download the file and place it at `pretrained_models/samp_net.pth`.

## Dependencies

### Required packages

| Package | Purpose |
|---------|---------|
| `torch`, `torchvision` | Deep learning framework (installed separately, see above) |
| `open-clip-torch` | CLIP embeddings/tagging (legacy/8gb profiles) |
| `pyiqa` | TOPIQ and other quality/aesthetic models |
| `opencv-python` | Image processing |
| `pillow` | Image loading, incl. PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF needs pillow>=11.3) |
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
| `sqlite-vec` | On-disk semantic search (falls back to an in-memory NumPy cache); `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | JPEG XL photos and Lightroom Classic 13+ merged DNG previews (HDR/Panorama/Enhance) |

All of these are in `requirements.txt` except `pyiqa` and `insightface`, which are in `requirements.restricted.txt` (see [Commercial install and the restricted packages](#commercial-install-and-the-restricted-packages)). No profile needs extra base packages.

### Optional packages

Each unlocks a feature; without it the feature is skipped or a fallback is used.

| Package | Unlocks | Without it |
|---------|---------|-----------|
| `watchdog` | Watch mode (`--watch`); **not in `requirements.txt`**, install with `pip install .[watch]` | `--watch` unavailable |
| `pillow-heif` | HEIF/HEIC decode | HEIF/HEIC files skipped |
| `rawpy` | RAW decode (CR2/CR3/NEF/ARW/…), already in `requirements.txt` | RAW files skipped |
| `cuml`, `cupy` | GPU face clustering (conda + CUDA) | Clustering on CPU via `hdbscan` (default) |
| `onnxruntime-gpu` | GPU face detection, **instead of** `onnxruntime` ([details](#onnx-runtime-for-face-detection)) | CPU `onnxruntime` (slower) |
| `aesthetic-predictor-v2-5` | `aesthetic_v25` scorer (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, off by default). **Deprecated** (AGPL-3.0, unmaintained since 2024-12-18); prefer `qrealign`, which needs no extra package | `aesthetic_v25` unavailable |
| `darktable-cli` (system) | RAW/darktable profile export from the viewer | Only original/embedded download offered |
| `exiftool` (system) | Best EXIF/GPS extraction | Falls back to `exifread`, then PIL |

## Feature requirements

Most of Facet runs anywhere (CPU, any profile). Some features need a GPU, a higher **VRAM
profile**, an optional package, or the viewer's **edition password** / **superadmin**
role. Tags used in the docs:
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
| AI captions (generate / view) | yes | `16gb`/`24gb` | edition (generate) | — |
| AI captions (edit) | yes | `16gb`/`24gb` | edition | — |
| VLM critique | yes | `16gb`/`24gb` | edition (generate) | — |
| Face detection / extraction (InsightFace) | recommended (CPU works, slow) | any | — | — |
| Face clustering (HDBSCAN) | no (CPU) | any | — | `cuml`/`cupy` (optional GPU accel) |
| Semantic search | no | any | — | `sqlite-vec` (falls back to NumPy) |
| RAW / HEIF decode | no | any | — | `rawpy` / `pillow-heif` |
| Watch mode (`--watch`) | no | any | — | `watchdog` |
| GPS extract / darktable export | no | any | — | `exiftool` / `darktable-cli` |
| Ratings, favorites, face & person edits, culling | no | any | edition | — |
| Trigger scans from the web UI | no | any | edition (single-user) / superadmin (multi-user) | — |
| Multi-user (per-user ratings & roles) | no | any | role-based | — |

The edition password and user roles are set in `scoring_config.json`; see
[Configuration](CONFIGURATION.md).

> No local GPU? Point VLM tagging, captions and critique at a remote Ollama or
> OpenAI-compatible server with `vlm_backend` in `scoring_config.json`. Those features then
> work on the `legacy`/`8gb` profiles too.

## Troubleshooting dependency conflicts

Facet's ML packages (`torch`, `open-clip-torch`, `insightface`, …) pull in many
dependencies, and installing them one by one can break each other.

**Symptoms:** each install asks for yet another package; version conflicts between
`torch`, `numpy`, `huggingface-hub` or `open-clip-torch`; `pip install` succeeds but
`import` fails.

**1. Install everything at once:** `pip install -r requirements.txt`, so pip solves the
full graph. Don't install packages individually
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Use [uv](https://docs.astral.sh/uv/)**: `uv` resolves the whole graph before
installing:

```bash
pip install uv
uv pip install -r requirements.txt
# With the CUDA index for PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Start fresh:** `deactivate`, `rm -rf venv`, and redo
[Install by hand](#install-by-hand-without-installsh) (or re-run `install.sh`).

### GPU detection issues

If your GPU is not detected (common with newer cards), run:

```bash
python facet.py --doctor
```

It checks PyTorch CUDA support and the driver, and suggests the right pip command. It also
catches what `torch.cuda.is_available()` misses: a GPU the installed PyTorch has no kernels for (e.g. RTX 50-series on a pre-12.8
CUDA build). In that case Facet falls back to CPU instead of crashing, and `--doctor` names
the fix: in Docker, the right image tag (`ghcr.io/ncoevoet/facet:latest-cuda-legacy` for
Maxwell/Pascal/Volta); bare metal, the right `--index-url`.

To simulate hardware for testing:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Angular client

Only needed for development or custom builds; `install.sh` and the Docker image already
build it.

```bash
cd client
npm install
npm run build    # Production build → client/dist/
npm start        # Dev server on http://localhost:4200 (proxies API to :5000)
```

> **`npm audit` warnings:** most findings are in build-time dev dependencies that never
> reach the browser. Review them before running `npm audit fix`, which can downgrade or
> remove packages.
