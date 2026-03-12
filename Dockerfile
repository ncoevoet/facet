# ---- Stage 1: Build Angular client ----
FROM node:22-alpine AS client-build

WORKDIR /app/client
COPY client/package.json client/package-lock.json ./
RUN npm ci
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
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (torch/torchvision already in base image)
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
COPY viewer/ viewer/
COPY facet.py database.py viewer.py tag_existing.py validate_db.py calibrate.py diagnostics.py ./
COPY scoring_config.json pyproject.toml ./

RUN useradd --create-home --shell /bin/bash facet \
    && chown -R facet:facet /app

USER facet
EXPOSE 5000

CMD ["python", "viewer.py", "--production"]
