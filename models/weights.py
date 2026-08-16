"""Filesystem home for auto-downloaded model weights.

``pretrained_models/`` is resolved against the repository root rather than the
process working directory: ``facet.py`` and ``viewer.py`` are launched from
different directories, and the Docker image's working directory is not a mounted
volume, so a CWD-relative destination re-downloads the same file over and over.
"""

import logging
import os
import tempfile
import urllib.request
from pathlib import Path

logger = logging.getLogger("facet.models")

PRETRAINED_MODELS_DIR = Path(__file__).resolve().parent.parent / 'pretrained_models'

AESTHETIC_MLP_WEIGHTS_URL = (
    "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/"
    "sac%2Blogos%2Bava1-l14-linearMSE.pth"
)


def pretrained_model_path(filename: str) -> Path:
    """Absolute path of a weights file inside ``pretrained_models/``."""
    return PRETRAINED_MODELS_DIR / filename


def download_weights(url: str, destination: Path):
    """Download ``url`` to ``destination``, atomically.

    The fetch goes to a unique temporary file in the destination directory and is
    then moved into place, so a second scan racing on the same missing file can
    never load a half-written checkpoint.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading model weights to %s...", destination)
    fd, temp_path = tempfile.mkstemp(dir=str(destination.parent), suffix='.part')
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, temp_path)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
