#!/bin/sh
set -e

SEEDED_CONFIG=/config/scoring_config.json
IMAGE_CONFIG=/app/scoring_config.json

# Unset FACET_CONFIG when it names a seed that could not be created. A path the
# operator NAMED and that is not there aborts the container rather than being
# read as an install with no overrides -- deliberately, because that distinction
# is what stops a typo'd mount from presenting as a passwordless install. An
# UNSET variable is the supported zero-override state: it resolves to a
# repo-root path that is equally absent, and an absent path nobody named
# resolves to the defaults packaged in the image. One aimed anywhere else is the
# operator's choice and none of this seed's business.
fall_back_to_packaged_defaults() {
    if [ "${FACET_CONFIG:-}" = "$SEEDED_CONFIG" ]; then
        unset FACET_CONFIG
    fi
}

# Put a real, editable scoring_config.json where FACET_CONFIG points, so that
# every runtime write (the viewer password upgrade, the share-secret eviction,
# weights, priorities, scoring contexts) lands on the /config bind mount and
# survives `docker compose down && up` instead of dying with the container.
#
# Best-effort, like the chown below: a `:ro` mount or an NFS root_squash export
# makes the copy fail, and aborting on it (set -e) would refuse to start a
# container whose own image already carries a working config. `|| true` would
# not be enough, so fall_back_to_packaged_defaults names the alternative.
#
# The seed is EMPTY, because the config file is now the operator's override and a
# fresh install overrides nothing: every value comes from the defaults packaged in
# the image. That is the whole point -- what lands in /config is the handful of
# lines someone actually changed, not a 3700-line copy of the shipped config in
# which their own three edits are invisible.
#
# $IMAGE_CONFIG is not baked into the image any more, so it exists only when an
# operator mounted their own file there -- the upgrade path from a compose that
# mounted `./scoring_config.json:/app/scoring_config.json`. That file is copied
# across verbatim, because seeding an empty override over it would silently reset
# their weights, categories and viewer password -- the last of which disables
# edition gating entirely when empty. A full config still resolves to itself, so
# nothing about carrying it across is lossy.
write_seed() {
    if [ -e "$IMAGE_CONFIG" ]; then
        cp "$IMAGE_CONFIG" "$SEEDED_CONFIG" 2>/dev/null
    else
        printf '{}\n' > "$SEEDED_CONFIG" 2>/dev/null
    fi
}
#
# `-e` not `-f`, plus an explicit symlink refusal: under the root branch this
# runs over a directory chowned to the unprivileged `facet` user, so anyone with
# code execution as `facet` could plant $SEEDED_CONFIG as a symlink to a
# root-owned path and have the `cp` write through it. `[ ! -f ]` does not even
# see a dangling one. api/config.py guards the identical threat with lstat.
#
# 0600, not the 0644 `cp` leaves under the default umask: this file legitimately
# holds viewer.password, users.*.password_hash, upload.password, frame.tokens
# and immich.api_key in plaintext, and api.config.atomic_write_json PRESERVES
# the destination mode on every later write, so whatever bits the seed lands
# with are permanent. The module's own backup writer already forces 0600.
seed_config() {
    if [ -L "$SEEDED_CONFIG" ]; then
        echo "facet: $SEEDED_CONFIG is a symlink — refusing to write through it;" \
            "falling back to the defaults packaged in the image" >&2
        fall_back_to_packaged_defaults
        return
    fi
    if [ ! -e "$SEEDED_CONFIG" ] && ! write_seed; then
        echo "facet: cannot seed $SEEDED_CONFIG (read-only or root_squash mount) —" \
            "falling back to the defaults packaged in the image, whose edits are" \
            "lost when the container is removed" >&2
        fall_back_to_packaged_defaults
        return
    fi
    chmod 600 "$SEEDED_CONFIG" 2>/dev/null || true
}

# The Docker daemon creates any absent bind-mount source on the host as root,
# which the unprivileged "facet" user cannot write — breaking the SQLite DB at
# DB_PATH ("unable to open database file"). When the container starts as root,
# take ownership of the writable mounts, then drop privileges to "facet". When
# already running unprivileged (a `user:` override in compose), just exec.
if [ "$(id -u)" = '0' ]; then
    mkdir -p /app/data /app/storage /app/pretrained_models /config \
        /home/facet/.cache/huggingface /home/facet/.insightface
    seed_config
    # The `cp` above runs as root, so a freshly seeded file is root:root even
    # though /config itself is chowned below — and seed_config just chmod'd it
    # 0600, which leaves it unreadable by `facet`. Every config WRITER now goes
    # through atomic_write_json (mkstemp + os.replace) and needs only the
    # DIRECTORY, chowned below anyway: ScoringConfig.save_config was the last
    # in-place `open(path, 'w')` and became atomic too. So this chown is about
    # the READ, not the write — without it the first `load_resolved` of the
    # seed fails with EACCES. Skipped for a symlink, which seed_config already
    # refused to touch: chown without -h would follow it to whatever it names.
    if [ ! -L "$SEEDED_CONFIG" ]; then
        chown facet:facet "$SEEDED_CONFIG" 2>/dev/null || true
    fi
    # Best-effort: on read-only / NFS root_squash / already-correct mounts the
    # chown may fail harmlessly — don't abort startup over it (set -e). A real
    # permission problem still surfaces with a clear error when SQLite opens.
    # -h so a planted symlink among these names is retargeted rather than
    # followed to whatever it points at.
    chown -h facet:facet /app/data /app/storage /app/pretrained_models /config \
        /home/facet/.cache/huggingface /home/facet/.insightface 2>/dev/null || true
    exec gosu facet "$@"
fi

# A `user:` override in compose skips everything above, including the seed — but
# docker-compose.yml still sets FACET_CONFIG unconditionally, so without this
# the one configuration that avoids a root startup is the one that cannot start:
# ScoringConfig raises FileNotFoundError on the /config/scoring_config.json
# nothing created. Seed it where this user can write, name the baked fallback
# where it cannot.
mkdir -p /config 2>/dev/null || true
seed_config

exec "$@"
