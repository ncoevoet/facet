"""Shortcuts for loading a pretrained model whose every weight comes from a checkpoint.

Two costs of a model load buy nothing when the checkpoint is already on disk:

* the constructor draws random initial values for every parameter (CLIP ViT-L/14
  spends seconds in ``normal_`` / ``kaiming_uniform_``) and ``load_state_dict``
  overwrites all of them a moment later;
* the hub clients ask huggingface.co whether the cached revision is current before
  reading it, one TLS round-trip per file.

Measured on an M4 Pro scan of six photos, the two together were about 10 s of a 48 s
run.
"""

import contextlib
import json
import logging
import os
import threading
from typing import Callable

logger = logging.getLogger("facet.fast_load")

_RANDOM_INITS = (
    'uniform_', 'normal_', 'trunc_normal_',
    'xavier_uniform_', 'xavier_normal_',
    'kaiming_uniform_', 'kaiming_normal_',
    'orthogonal_', 'sparse_',
)

# Set by the scan CLI while it scores: read a model that has loaded on this install
# before from the hub cache without asking the hub. A module switch because the
# effect is process-wide too (see hub_offline); the viewer never sets it.
prefer_local_hub = False

_PATCH_LOCK = threading.RLock()
_local = threading.local()
_originals: dict[str, Callable] = {}
_active = 0


def _keep_tensor(tensor, *args, **kwargs):
    return tensor


def _dispatch(name, original):
    # Closes over ``original``: a caller that kept a reference to this dispatcher
    # (``from torch.nn.init import normal_`` during a load) must still work after
    # the patch is lifted.
    def init(tensor, *args, **kwargs):
        replacement = getattr(_local, 'replacement', None)
        if replacement is None:
            return original(tensor, *args, **kwargs)
        return replacement(tensor, *args, **kwargs)
    init.__name__ = name
    return init


@contextlib.contextmanager
def skip_weight_init(replacement=_keep_tensor):
    """Make ``torch.nn.init``'s random initialisers no-ops for a model built on this thread.

    Only for a model whose checkpoint supplies EVERY parameter: one the checkpoint
    leaves out would keep whatever ``torch.empty`` handed it. ``ones_`` / ``zeros_`` /
    ``constant_`` are left alone, so normalisation layers and biases that rely on
    their defaults still get them. ``replacement`` exists for the test that proves
    full coverage by poisoning instead of skipping.

    ``torch.nn.init`` is process-wide, so the functions are swapped for dispatchers
    that skip only on a thread inside this context. A module another thread builds
    meanwhile (the viewer trains its ranker beside model loads) is initialised as usual.
    """
    try:
        import torch.nn.init as init
    except ImportError:
        # Nothing to skip, and the loader must still run: a loader that refuses a
        # model (the licensing gate) does so without ever importing torch.
        yield
        return

    global _active
    with _PATCH_LOCK:
        if _active == 0:
            for name in _RANDOM_INITS:
                if hasattr(init, name):
                    _originals[name] = getattr(init, name)
                    setattr(init, name, _dispatch(name, _originals[name]))
        _active += 1
    outer = getattr(_local, 'replacement', None)
    _local.replacement = replacement
    try:
        yield
    finally:
        _local.replacement = outer
        with _PATCH_LOCK:
            _active -= 1
            if _active == 0:
                for name, fn in _originals.items():
                    setattr(init, name, fn)
                _originals.clear()


@contextlib.contextmanager
def hub_offline():
    """Answer hub lookups from the local cache, without the network round-trip.

    Process-wide (``huggingface_hub`` reads one module constant), so only for a
    process whose other threads use no hub: a download running elsewhere would be
    refused for the duration. The scan CLI qualifies; the viewer does not.
    """
    try:
        from huggingface_hub import constants
    except ImportError:
        yield
        return
    with _PATCH_LOCK:
        saved = constants.HF_HUB_OFFLINE
        constants.HF_HUB_OFFLINE = True
        try:
            yield
        finally:
            constants.HF_HUB_OFFLINE = saved


class WarmModelLedger:
    """Remembers which models have loaded once, so later loads can stay offline.

    A model is only tried offline after an online load of it succeeded on this
    install; a first-ever load therefore never logs a spurious cache-miss failure.
    """

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()
        self._names = None

    def _read(self):
        if self._names is None:
            try:
                with open(self._path, encoding='utf-8') as f:
                    self._names = set(json.load(f))
            except (OSError, ValueError, TypeError):
                self._names = set()
        return self._names

    def __contains__(self, name):
        with self._lock:
            return name in self._read()

    def _write(self, names):
        try:
            os.makedirs(os.path.dirname(self._path) or '.', exist_ok=True)
            tmp = f'{self._path}.{os.getpid()}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(sorted(names), f)
            os.replace(tmp, self._path)
        except OSError as e:
            logger.debug("Could not record warm models at %s: %s", self._path, e)

    def add(self, name):
        with self._lock:
            names = self._read()
            if name not in names:
                names.add(name)
                self._write(names)

    def discard(self, name):
        with self._lock:
            names = self._read()
            if name in names:
                names.discard(name)
                self._write(names)
