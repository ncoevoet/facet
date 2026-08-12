# Defaults to the CUDA runtime (the local `docker build` / `docker compose build`
# path, unchanged). The published CPU image overrides BASE_IMAGE to a slim base
# and flips STRIP_TORCH/INSTALL_CUML — see .github/workflows/docker-publish.yml.
# Must be declared before the FIRST FROM to be usable as a later stage's default.
ARG BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime

# ---- Stage 1: Build Angular client ----
FROM node:22-alpine AS client-build

WORKDIR /app/client
COPY client/package.json ./
RUN npm install --no-audit --no-fund
COPY client/ ./
RUN npx ng build

# ---- Stage 2: Python runtime ----
FROM ${BASE_IMAGE}

# STRIP_TORCH=1 (default, CUDA base): torch/torchvision are NOT installed here —
# the CUDA base image already ships them, and requirements.lock.txt below is a
# pre-stripped freeze that omits torch/torchvision/nvidia-*/triton for exactly
# that reason (see the comment on the COPY below).
# STRIP_TORCH=0 (slim/CPU base): the base image has no torch at all, so install
# it explicitly from the CPU wheel index — pulling it from PyPI unpinned would
# resolve the full CUDA wheels and blow the CPU image's size target.
ARG STRIP_TORCH=1
# INSTALL_CUML=1 (default, CUDA base): install RAPIDS cuML for GPU-accelerated
# face clustering (~5.75 GB, the largest single layer).
# INSTALL_CUML=0 (CPU base): skip it entirely — face clustering already falls
# back to CPU HDBSCAN (face_clustering.use_gpu="auto") when no CUDA device is
# present, so the CPU image needs none of this.
ARG INSTALL_CUML=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libimage-exiftool-perl \
    libgl1 \
    libglib2.0-0 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — pinned lock for a reproducible, self-contained image.
# requirements.lock.txt is a full pip freeze from a validated container (every
# version tested working end-to-end) with torch/torchvision + nvidia-*/triton
# stripped, since the CUDA base image already provides them. This makes the image
# "sticky": it does not float to newer, untested releases (e.g. transformers 5.3
# once broke the Qwen3.5 batched tagger until the padding fix landed).
# Regenerate the lock from a good build with:
#   docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt
# The optional extended-IQA tier (scoring_config.json "iqa_extended") is OFF by
# default and intentionally NOT installed here (see docs/CONFIGURATION.md).
COPY requirements.lock.txt .
# CPU base only: the image ships no torch at all, so install it up front from
# the CPU wheel index before anything in requirements.lock.txt can pull in a
# CUDA build transitively.
RUN if [ "$STRIP_TORCH" = "0" ]; then \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu ; \
    fi
RUN pip install --no-cache-dir -r requirements.lock.txt

# GPU face clustering (RAPIDS cuML). Baked in so the GPU profiles (8gb/16gb/24gb)
# use cuML HDBSCAN via face_clustering.use_gpu="auto"; the legacy profile forces
# CPU clustering (faces/clusterer.py) and the clusterer also falls back to CPU
# when no CUDA device is present. RAPIDS wheels come from the NVIDIA index. This
# is by far the largest single add to the image (~5.75 GB); pinned for reproducibility.
# Installed unconstrained: cuML pins numba<0.65 (the lock has 0.65.1 via pyiqa) and
# pulls newer nvidia-cuda-* 12.9 wheels. Validated that torch + pyiqa still work after.
# Skipped on the CPU image (INSTALL_CUML=0) — see the ARG comment above.
RUN if [ "$INSTALL_CUML" = "1" ]; then \
        pip install --no-cache-dir --extra-index-url https://pypi.nvidia.com cuml-cu12==26.6.0 ; \
    fi

# Copy built Angular client
COPY --from=client-build /app/client/dist/client/browser client/dist/client/browser

# Copy Python source code
COPY api/ api/
COPY analyzers/ analyzers/
COPY comparison/ comparison/
COPY config/ config/
COPY db/ db/
COPY exiftool/ exiftool/
COPY faces/ faces/
COPY i18n/ i18n/
COPY models/ models/
COPY optimization/ optimization/
COPY processing/ processing/
COPY utils/ utils/
COPY plugins/ plugins/
COPY storage/ storage/
COPY validation/ validation/
COPY facet.py database.py viewer.py tag_existing.py validate_db.py calibrate.py diagnostics.py ./
# Ship a sanitized default config so the image runs preconfigured with zero host
# setup (empty secrets, darktable-cli on PATH, vram_profile=auto, all profiles at
# full feature set). Baked as the active scoring_config.json AND kept alongside so
# users can `cp scoring_config.default.json scoring_config.json` to customize and
# mount it back (docker-compose.yml has the optional mount commented in).
COPY scoring_config.default.json /app/scoring_config.default.json
COPY scoring_config.default.json /app/scoring_config.json
COPY pyproject.toml ./

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN useradd --create-home --shell /bin/bash facet \
    && mkdir -p /app/data \
    && chown -R facet:facet /app \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

# Pin HOME so the HuggingFace / InsightFace caches are deterministic. They pick
# their dir from os.path.expanduser("~"), which is $HOME when set and otherwise
# the passwd home. gosu does not reset $HOME on the privilege drop, so without
# this the cache landed in /root or /home/facet depending on the environment's
# inherited $HOME — and the bind mounts only catch one of them.
ENV HOME=/home/facet

EXPOSE 5000

# Entrypoint fixes ownership of the writable bind mounts (created root-owned by
# the Docker daemon) then drops to the unprivileged "facet" user.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "viewer.py", "--production"]
