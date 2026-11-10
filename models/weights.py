"""Filesystem home for auto-downloaded model weights.

``pretrained_models/`` is resolved against the repository root rather than the
process working directory: ``facet.py`` and ``viewer.py`` are launched from
different directories, and the Docker image's working directory is not a mounted
volume, so a CWD-relative destination re-downloads the same file over and over.
"""

import hashlib
import logging
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("facet.models")

# Seconds a socket operation (connect, or waiting for the next chunk) may block.
# Per operation, not a total: a 400 MB fetch on a slow link is legitimate, a
# stalled connection holding a fetch lock for every face worker is not.
DOWNLOAD_TIMEOUT_SECONDS = 60

# Attempts per download, and the first backoff (doubled after each failure). Only
# a server-side refusal (5xx, 429) or a dropped connection is retried: a stall
# already cost DOWNLOAD_TIMEOUT_SECONDS, and a 4xx or a bad body will not change.
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_RETRY_BACKOFF_SECONDS = 2

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


def _is_transient(ex: Exception) -> bool:
    if isinstance(ex, urllib.error.HTTPError):
        return ex.code >= 500 or ex.code == 429
    if isinstance(ex, urllib.error.URLError):
        return isinstance(ex.reason, ConnectionError)
    return isinstance(ex, ConnectionError)


def _fetch(url: str, temp_path: str, sha256: Optional[str]):
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, \
            open(temp_path, 'wb') as out:
        shutil.copyfileobj(response, out, 1 << 20)
        received = out.tell()
    # HTTPResponse.read() does not raise on a short body, so check it ourselves.
    headers = getattr(response, 'headers', None)
    declared = headers.get('Content-Length') if headers else None
    if declared is not None and declared.strip().isdigit() and received != int(declared):
        raise ValueError(
            f"Downloaded {url} is truncated: received {received} bytes, "
            f"server declared Content-Length {declared}."
        )
    if sha256 is not None:
        digest = _sha256_file(temp_path)
        if digest != sha256:
            raise ValueError(
                f"Downloaded {url} has SHA-256 {digest}, expected {sha256}. "
                f"Refusing to install a checkpoint that doesn't match."
            )


def download_weights(url: str, destination: Path, sha256: Optional[str] = None):
    """Download ``url`` to ``destination``, atomically.

    The fetch goes to a unique temporary file in the destination directory and is
    then moved into place, so a second scan racing on the same missing file can
    never load a half-written checkpoint. When ``sha256`` is given, a mismatched
    download is discarded rather than installed. A transient server or connection
    failure is retried up to ``DOWNLOAD_ATTEMPTS`` times with a doubling backoff.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading model weights to %s...", destination)
    fd, temp_path = tempfile.mkstemp(dir=str(destination.parent), suffix='.part')
    os.close(fd)
    try:
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                _fetch(url, temp_path, sha256)
                break
            except Exception as ex:
                if attempt == DOWNLOAD_ATTEMPTS or not _is_transient(ex):
                    raise
                delay = DOWNLOAD_RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
                logger.warning("Download of %s failed (%s); retrying in %ss (attempt %d of %d)",
                               url, ex, delay, attempt + 1, DOWNLOAD_ATTEMPTS)
                time.sleep(delay)
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# Permissive (commercial-mode) face pipeline weights, issue #185 W5. Pinned to the
# opencv_zoo commit that last touched each file (not `main`) and SHA-256 checked.
# Licences (verified against the repo LICENSE files): YuNet MIT, SFace Apache-2.0.
YUNET_WEIGHTS_FILENAME = "face_detection_yunet_2023mar.onnx"
YUNET_WEIGHTS_URL = (
    "https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_WEIGHTS_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
SFACE_WEIGHTS_FILENAME = "face_recognition_sface_2021dec.onnx"
SFACE_WEIGHTS_URL = (
    "https://github.com/opencv/opencv_zoo/raw/ba91a3b91d00d76e86540d4013f944bd6b514e39/"
    "models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
SFACE_WEIGHTS_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
