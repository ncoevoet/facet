#!/bin/sh
set -e

SEEDED_CONFIG=/config/scoring_config.json
IMAGE_CONFIG=/app/scoring_config.json

# The Docker daemon creates any absent bind-mount source on the host as root,
# which the unprivileged "facet" user cannot write — breaking the SQLite DB at
# DB_PATH ("unable to open database file"). When the container starts as root,
# take ownership of the writable mounts, then drop privileges to "facet". When
# already running unprivileged (a `user:` override in compose), just exec.
if [ "$(id -u)" = '0' ]; then
    mkdir -p /app/data /app/storage /app/pretrained_models /config \
        /home/facet/.cache/huggingface /home/facet/.insightface
    # Same daemon-creates-it-as-root behavior applies to /config, mounted
    # as a directory precisely so the daemon CAN create it: seed it from the
    # image's baked default on a first run, so FACET_CONFIG (which points here
    # in docker-compose.yml) finds a real, editable scoring_config.json rather
    # than nothing.
    #
    # Best-effort, like the chown below: a `:ro` mount or an NFS root_squash
    # export makes the copy fail, and aborting on it (set -e) refuses to start
    # a container whose own image already carries a working config. `|| true`
    # would not be enough — FACET_CONFIG would still name a file that is not
    # there, and ScoringConfig raises FileNotFoundError on a missing path
    # rather than falling back — so the fallback is named here instead. The
    # baked $IMAGE_CONFIG is owned by facet and stays writable; it just lives
    # in the container's own layer, so edits die with `docker rm`. Only a
    # FACET_CONFIG naming the file this seed failed to write is redirected: an
    # unset one already resolves to $IMAGE_CONFIG on its own, and one aimed
    # anywhere else is the operator's choice and none of this seed's business.
    if [ ! -f "$SEEDED_CONFIG" ] \
        && ! cp /app/scoring_config.default.json "$SEEDED_CONFIG" 2>/dev/null; then
        echo "facet: cannot seed $SEEDED_CONFIG (read-only or root_squash mount) —" \
            "falling back to the image's $IMAGE_CONFIG, whose edits are lost when" \
            "the container is removed" >&2
        if [ "${FACET_CONFIG:-}" = "$SEEDED_CONFIG" ]; then
            FACET_CONFIG="$IMAGE_CONFIG"
            export FACET_CONFIG
        fi
    fi
    # Best-effort: on read-only / NFS root_squash / already-correct mounts the
    # chown may fail harmlessly — don't abort startup over it (set -e). A real
    # permission problem still surfaces with a clear error when SQLite opens.
    # scoring_config.json is listed on its own, not just its directory: the
    # `cp` above runs as root, so a freshly seeded file is root:root even
    # though /config itself is chowned below. The viewer's own config writes
    # (weights, priorities, the password/share-secret migrations) would not
    # need it — they go through api.config.atomic_write_json, which is
    # mkstemp + os.replace and needs the DIRECTORY, chowned here anyway — but
    # ScoringConfig.save_config, which rewrites the file in place when weight
    # validation auto-corrects a category, is a plain open(path, 'w') on the
    # FILE. Belt and braces either way: chowning it costs nothing.
    chown facet:facet /app/data /app/storage /app/pretrained_models /config \
        "$SEEDED_CONFIG" \
        /home/facet/.cache/huggingface /home/facet/.insightface 2>/dev/null || true
    exec gosu facet "$@"
fi

exec "$@"
