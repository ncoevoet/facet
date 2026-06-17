# ---- Stage 1: Build Angular client ----
FROM node:22-alpine AS client-build

WORKDIR /app/client
COPY client/package.json ./
RUN npm install --no-audit --no-fund
COPY client/ ./
RUN npx ng build

# ---- Stage 2: Python runtime with CUDA ----
FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libimage-exiftool-perl \
    libgl1 \
    libglib2.0-0 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (torch/torchvision already in base image)
# The optional extended-IQA tier (scoring_config.json "iqa_extended") is OFF by
# default and intentionally NOT installed here to keep the image lean. To use it,
# add `pip install --no-cache-dir aesthetic-predictor-v2-5 bitsandbytes` below
# (see docs/CONFIGURATION.md "Extended IQA tier").
COPY requirements.txt .
RUN sed -i '/^torch>=/d; /^torchvision>=/d' requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

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
# scoring_config.json is NOT baked in — mount it via docker-compose volume
COPY pyproject.toml ./

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN useradd --create-home --shell /bin/bash facet \
    && mkdir -p /app/data \
    && chown -R facet:facet /app \
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
