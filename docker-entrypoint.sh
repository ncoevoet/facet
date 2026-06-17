#!/bin/sh
set -e

# The Docker daemon creates any absent bind-mount source on the host as root,
# which the unprivileged "facet" user cannot write — breaking the SQLite DB at
# DB_PATH ("unable to open database file"). When the container starts as root,
# take ownership of the writable mounts, then drop privileges to "facet". When
# already running unprivileged (a `user:` override in compose), just exec.
if [ "$(id -u)" = '0' ]; then
    mkdir -p /app/data /app/storage /app/pretrained_models \
        /home/facet/.cache/huggingface /home/facet/.insightface
    # Best-effort: on read-only / NFS root_squash / already-correct mounts the
    # chown may fail harmlessly — don't abort startup over it (set -e). A real
    # permission problem still surfaces with a clear error when SQLite opens.
    chown facet:facet /app/data /app/storage /app/pretrained_models \
        /home/facet/.cache/huggingface /home/facet/.insightface 2>/dev/null || true
    exec gosu facet "$@"
fi

exec "$@"
