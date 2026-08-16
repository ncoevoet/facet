"""Filesystem home for auto-downloaded model weights.

``pretrained_models/`` is resolved against the repository root rather than the
process working directory: ``facet.py`` and ``viewer.py`` are launched from
different directories, and the Docker image's working directory is not a mounted
volume, so a CWD-relative destination re-downloads the same file over and over.
"""

import hashlib
import logging
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("facet.models")

PRETRAINED_MODELS_DIR = Path(__file__).resolve().parent.parent / 'pretrained_models'

# Pinned to the commit that added the file (the only one that has ever touched
# it) rather than `main`, so the download can't silently change out from under
# a checksum-verified deploy.
AESTHETIC_MLP_WEIGHTS_URL = (
    "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/"
    "61f2f07a2b16be5ffb40a10ba5adae4a74c9d0d9/sac%2Blogos%2Bava1-l14-linearMSE.pth"
)
AESTHETIC_MLP_WEIGHTS_SHA256 = "21dd590f3ccdc646f0d53120778b296013b096a035a2718c9cb0d511bff0f1e0"


def pretrained_model_path(filename: str) -> Path:
    """Absolute path of a weights file inside ``pretrained_models/``."""
    return PRETRAINED_MODELS_DIR / filename


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download_weights(url: str, destination: Path, sha256: Optional[str] = None):
    """Download ``url`` to ``destination``, atomically.

    The fetch goes to a unique temporary file in the destination directory and is
    then moved into place, so a second scan racing on the same missing file can
    never load a half-written checkpoint. When ``sha256`` is given, a mismatched
    download is discarded rather than installed.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading model weights to %s...", destination)
    fd, temp_path = tempfile.mkstemp(dir=str(destination.parent), suffix='.part')
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, temp_path)
        if sha256 is not None:
            digest = _sha256_file(temp_path)
            if digest != sha256:
                raise ValueError(
                    f"Downloaded {url} has SHA-256 {digest}, expected {sha256}. "
                    f"Refusing to install a checkpoint that doesn't match."
                )
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
