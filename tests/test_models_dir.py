"""``FACET_MODELS_DIR`` and the ``pretrained_models/`` defaults that must follow it."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from models import weights
from models.piaa_prior import prior_path

REPO = Path(__file__).resolve().parent.parent


def test_env_moves_the_models_dir(tmp_path):
    env = {**os.environ, weights.MODELS_DIR_ENV: str(tmp_path / 'models')}
    out = subprocess.run(
        [sys.executable, '-c', 'from models.weights import PRETRAINED_MODELS_DIR; print(PRETRAINED_MODELS_DIR)'],
        cwd=REPO, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == str((tmp_path / 'models').resolve())


@pytest.fixture()
def models_dir(tmp_path, monkeypatch):
    directory = tmp_path / 'models'
    monkeypatch.setattr(weights, 'PRETRAINED_MODELS_DIR', directory)
    # A CWD-relative default would now land in here instead.
    monkeypatch.chdir(tmp_path)
    return directory


def test_piaa_default_follows_the_models_dir(models_dir):
    assert prior_path(768) == str(models_dir / 'piaa_prior_768.npz')


def test_samp_net_and_u2net_defaults_follow_the_models_dir(models_dir, monkeypatch):
    pytest.importorskip('torch')
    from models import samp_net

    monkeypatch.setattr(samp_net.SAMPNetScorer, '_load_model', lambda self: None)
    scorer = samp_net.SAMPNetScorer(device='cpu')
    assert scorer.model_path == str(models_dir / 'samp_net.pth')
    assert scorer.saliency_detector.weights_path == str(models_dir / 'u2netp.pth')


def test_shipped_samp_net_config_value_follows_the_models_dir(models_dir):
    shipped = json.loads((REPO / 'config' / 'scoring_config.default.json').read_text())
    assert weights.resolve_models_path(shipped['models']['samp_net']['model_path']) == str(models_dir / 'samp_net.pth')
    assert weights.resolve_models_path(shipped['piaa_prior']['models_dir']) == str(models_dir)


@pytest.mark.parametrize('path', ['/opt/weights/samp_net.pth', 'custom/samp_net.pth', 'samp_net.pth'])
def test_other_paths_are_left_alone(models_dir, path):
    assert weights.resolve_models_path(path) == path
