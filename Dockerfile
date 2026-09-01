# Defaults to the CUDA runtime (the local `docker build` / `docker compose build`
# path). The published CPU image overrides BASE_IMAGE to a slim base and flips
# STRIP_TORCH/INSTALL_CUML; the published legacy CUDA image overrides BASE_IMAGE
# and REQUIREMENTS_LOCK — see .github/workflows/docker-publish.yml.
# The default is the CUDA 12.8 build because its torch ships sm_75...sm_120
# cubins, and sm_120 is what makes Blackwell (RTX 50-series) run a kernel at all
# — the 12.6 build stops at sm_90 and died with "no kernel image is available for
# execution on the device" (issue #119). The same wheel DROPS sm_50/sm_60/sm_70,
# so Maxwell / Pascal / Volta cards need the legacy variant
# (pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime, sm_50...sm_90). Verified by
# reading torch._C._cuda_getArchFlags() inside each base image.
# Must be declared before the FIRST FROM to be usable as a later stage's default.
ARG BASE_IMAGE=pytorch/pytorch:2.11.0-cuda12.8-cudnn9-runtime

# ---- Stage 1: Build Angular client ----
# Pinned to an exact patch, not the floating node:22-alpine: that tag is
# republished with whatever npm it ships, and the npm 10.9.8 it carried on
# 2026-08-22 could not resolve this dependency graph at all.
FROM node:22.23.2-alpine AS client-build

WORKDIR /app/client
# `npm ci` installs the locked transitive graph instead of re-resolving it from
# the registry, so a build here yields the tree that was tested rather than
# whatever was published since.
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
RUN npx ng build

# ---- Stage 2: Python runtime ----
FROM ${BASE_IMAGE}

# STRIP_TORCH=1 (default, CUDA base): torch/torchvision are NOT installed here —
# the CUDA base image already ships them, and the lock files below are
# pre-stripped freezes that omit torch/torchvision/nvidia-*/triton for exactly
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
# REQUIREMENTS_LOCK selects WHICH lock to install, because the two CUDA bases
# cannot share one. A pinned sympy that does not satisfy the BASE IMAGE's torch
# makes pip resolve the conflict by replacing that torch with a PyPI build: torch
# 2.6.0 requires sympy==1.13.1 exactly, torch 2.11.0 requires sympy>=1.13.3, and
# a `pip install --dry-run` of the legacy lock against the 2.11.0 base plans
# torch 2.6.0 + the CUDA 12.4 nvidia-* wheels — i.e. it silently throws away the
# base image's CUDA stack, which is the failure requirements.lock.txt exists to
# prevent, running backwards.
#   requirements.lock.txt        -> torch 2.11.0 CUDA base AND the slim CPU base
#   requirements.legacy.lock.txt -> pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime
ARG REQUIREMENTS_LOCK=requirements.lock.txt

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libimage-exiftool-perl \
    libgl1 \
    libglib2.0-0 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies — pinned lock for a reproducible, self-contained image.
# Each lock is a pip freeze from a validated container (every version tested
# working end-to-end) with torch/torchvision + nvidia-*/triton stripped, since
# the CUDA base image already provides them. This makes the image "sticky": it
# does not float to newer, untested releases (e.g. transformers 5.3 once broke
# the Qwen3.5 batched tagger until the padding fix landed).
# Regenerate a lock from a good build of THAT VARIANT, never by copying the
# other one — each is valid only against its own base image's torch:
#   docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt
# and, from a container built with BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime,
# the same command redirected to requirements.legacy.lock.txt instead.
# The optional extended-IQA tier (scoring_config.json "iqa_extended") is OFF by
# default and intentionally NOT installed here (see docs/CONFIGURATION.md).
# BOTH locks are COPYed, with literal paths rather than ${REQUIREMENTS_LOCK}:
# ci.yml's "Forbid Dockerfile COPY of untracked paths" gate greps this file
# textually and runs `git ls-files` on every COPY source, so a build-arg source
# would not resolve there. The unused one costs ~4 KB.
COPY requirements.lock.txt requirements.legacy.lock.txt ./
# CPU base only: the image ships no torch at all, so install it up front from
# the CPU wheel index before anything in the lock can pull in a CUDA build
# transitively.
# The trailing python call records the torch this image is SUPPOSED to end up
# with — the base image's on a CUDA base, the one just installed on the CPU base
# — so the guard after the lock install can prove pip did not replace it.
RUN if [ "$STRIP_TORCH" = "0" ]; then \
        pip install --no-cache-dir --break-system-packages torch torchvision --index-url https://download.pytorch.org/whl/cpu ; \
    fi \
    && python -c 'import pathlib, torch; pathlib.Path("/tmp/intended-torch").write_text(torch.__version__)'
# --break-system-packages: the CUDA 12.8 base is Ubuntu 24.04 and ships
# /usr/lib/python3.12/EXTERNALLY-MANAGED, so PEP 668 makes a plain `pip install`
# abort with "externally-managed-environment". A single-purpose image has no
# distro package manager competing for these packages, and a venv would only
# hide the base image's own torch. Accepted as a no-op by the pip in both other
# bases (24.3.1 conda / 25.0.1 slim), neither of which carries that marker.
RUN pip install --no-cache-dir --break-system-packages -r "${REQUIREMENTS_LOCK}"
# Nothing else makes BASE_IMAGE and REQUIREMENTS_LOCK move together, and a
# mismatched pair does not fail the install above — it silently swaps the torch
# the image is built around: requirements.lock.txt over the 12.6 base resolves
# torch 2.13.0 + CUDA 13 wheels, and requirements.legacy.lock.txt over the CPU
# base resolves torch 2.6.0 + 13 CUDA 12.4 wheels (the 8.81 GB "CPU" image that
# shipped as :latest). Both build clean and then cannot run on the hardware the
# tag promises, so assert it here rather than discover it on a user's card.
RUN REQUIREMENTS_LOCK="$REQUIREMENTS_LOCK" STRIP_TORCH="$STRIP_TORCH" python -c 'import os, pathlib, torch; \
marker = pathlib.Path("/tmp/intended-torch"); \
intended = marker.read_text(); \
lock = os.environ["REQUIREMENTS_LOCK"]; \
strip = os.environ["STRIP_TORCH"]; \
assert torch.__version__ == intended, f"{lock} replaced this image torch {intended} with {torch.__version__}: BASE_IMAGE and REQUIREMENTS_LOCK must move together"; \
assert (torch.version.cuda is None) == (strip == "0"), f"STRIP_TORCH={strip} but torch {torch.__version__} reports CUDA {torch.version.cuda}"; \
marker.unlink()'

# GPU face clustering (RAPIDS cuML). Baked in so the GPU profiles (8gb/16gb/24gb)
# use cuML HDBSCAN via face_clustering.use_gpu="auto"; the legacy profile forces
# CPU clustering (faces/clusterer.py) and the clusterer also falls back to CPU
# when no CUDA device is present. RAPIDS wheels come from the NVIDIA index. This
# is by far the largest single add to the image (~5.75 GB); pinned for reproducibility.
# Installed unconstrained: cuML pins numba<0.65 (the lock has 0.65.1 via pyiqa) and
# pulls newer nvidia-cuda-* 12.9 wheels. Validated that torch + pyiqa still work after.
# Stays cuml-cu12 on the 12.8 base: 12.8 is still CUDA 12, and the cu12 wheels
# already override the base's nvidia-cuda-* with 12.9 ones either way.
# Skipped on the CPU image (INSTALL_CUML=0) — see the ARG comment above.
RUN if [ "$INSTALL_CUML" = "1" ]; then \
        pip install --no-cache-dir --break-system-packages --extra-index-url https://pypi.nvidia.com cuml-cu12==26.6.0 ; \
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
COPY sync/ sync/
COPY validation/ validation/
COPY facet.py cli_args.py database.py viewer.py tag_existing.py validate_db.py calibrate.py diagnostics.py ./
# Ship a sanitized default config so the image runs preconfigured with zero host
# setup (empty secrets, darktable-cli on PATH, vram_profile=auto, all profiles at
# full feature set). Kept at /app/scoring_config.default.json as the pristine
# copy, and baked again as the active /app/scoring_config.json: FACET_CONFIG
# falls back to that path when unset, so `docker run` without compose (or any
# other use of this image that skips the mount) still gets a working,
# preconfigured install. docker-entrypoint.sh seeds the /config bind mount
# docker-compose.yml points FACET_CONFIG at from the ACTIVE one, not the
# pristine one — they are the same file unless the operator mounted their own
# over it, which is exactly the upgrade path that must not be reset. That mount
# lands at /config, not /app/config: the latter is where COPY config/ config/
# above bakes the `config` PYTHON PACKAGE, and a mount there would shadow it.
COPY scoring_config.default.json /app/scoring_config.default.json
COPY scoring_config.default.json /app/scoring_config.json
COPY pyproject.toml ./

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# The runtime UID/GID is pinned to 1000 explicitly, not left to useradd. Ubuntu
# 24.04 — what the CUDA 12.8 base is built on — already ships `ubuntu` at
# 1000:1000, so a bare useradd lands on 1001, while the conda 12.6 base and
# python:3.12-slim have nothing at 1000 and give 1000. That divergence is silent
# and destructive across a `docker compose pull` of an existing GPU install: the
# entrypoint's chown is deliberately NON-recursive, so files already inside the
# bind mounts keep UID 1000 and mode 0644, a 1001 process lands in the `other`
# class, and the SQLite DB opens read-only. The same chown then retargets the
# operator's own host ./data, ./storage and ./config to 1001, and /data/photos —
# never chowned at all — loses write access for XMP sidecar export and
# /api/cull/apply. Freeing 1000 first is a no-op on the two bases that have
# nobody there; on Ubuntu the distro user owns only its own 4-file home.
RUN if getent passwd 1000 >/dev/null; then userdel --remove "$(getent passwd 1000 | cut -d: -f1)"; fi \
    && if getent group 1000 >/dev/null; then groupdel "$(getent group 1000 | cut -d: -f1)"; fi \
    && groupadd --gid 1000 facet \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash facet \
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
