"""Model licence registry and the commercial-use policy (issue #185).

Stdlib only, and deliberately outside the ``config`` package so that any module
(including the lowest-level loaders) can import it without a cycle.

The registry is the single source for ``docs/THIRD_PARTY_MODELS.md`` (generated
by ``scripts/gen_third_party_models.py``) and for the ``--doctor`` licence
section. The *policy* decides what Facet may load:

* ``default`` -- everything is allowed (the shipped behaviour).
* ``commercial`` -- only components whose ``commercial`` status is ``yes`` are
  allowed, plus ``unclear`` ones when ``allow_unclear`` is set.

Nothing here is legal advice: a weights licence is not the licence of the data
the weights were trained on, and the dataset licences are unverified.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

LICENSING_MODE_ENV = 'FACET_LICENSING_MODE'
LICENSING_ALLOW_UNCLEAR_ENV = 'FACET_LICENSING_ALLOW_UNCLEAR'

MODE_DEFAULT = 'default'
MODE_COMMERCIAL = 'commercial'
MODES = (MODE_DEFAULT, MODE_COMMERCIAL)


class LicenceError(RuntimeError):
    """A component was requested that the active licensing policy forbids."""


def reraise_if_refused() -> None:
    """Call as the FIRST statement of a broad ``except Exception`` handler.

    Re-raises the exception being handled when it is, or was caused by or raised
    while handling, a :class:`LicenceError`, so a licence refusal is never
    downgraded to a logged warning. Python cannot make ``except Exception`` skip
    a subclass, so this one call is the single definition of "a refusal passes
    through". Outside an ``except`` block there is no active exception and it
    does nothing.
    """
    exc = sys.exc_info()[1]
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, LicenceError):
            raise exc
        seen.add(id(exc))
        # ``raise X from None`` sets __suppress_context__: the implicit context was
        # deliberately cut, so it is not followed (an explicit __cause__ still is).
        if exc.__cause__ is not None:
            exc = exc.__cause__
        elif exc.__suppress_context__:
            exc = None
        else:
            exc = exc.__context__


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    kind: str                 # 'code' | 'weights' | 'package'
    code_licence: str
    weights_licence: str
    commercial: str           # 'yes' | 'no' | 'unclear'
    source_url: str
    slot: str
    replacement: Optional[str]  # id of the component to use instead
    note: str = ''


def _c(id, name, kind, code, weights, commercial, url, slot, replacement=None, note=''):
    return Component(id, name, kind, code, weights, commercial, url, slot, replacement, note)


_PYIQA_NOTE = ('pyiqa 0.1.16 is PolyForm Noncommercial 1.0.0 (earlier releases CC BY-NC-SA); '
               'the PyPI "Apache" classifier is an upstream error (pyiqa issue #294).')
_PYIQA_CODE = 'PolyForm-NC 1.0.0 (pyiqa 0.1.16)'
_PYIQA_WEIGHTS = 'CC BY-NC-SA 4.0 (IQA-PyTorch-Weights)'
_PYIQA_URL = 'https://github.com/chaofengc/IQA-PyTorch'


def _pyiqa(id, name, slot, replacement, note=''):
    return _c(id, name, 'package', _PYIQA_CODE, _PYIQA_WEIGHTS, 'no', _PYIQA_URL, slot,
              replacement, (_PYIQA_NOTE + ' ' + note).strip())


COMPONENTS: dict[str, Component] = {c.id: c for c in (
    # --- pyiqa-backed scorers (every key of models.pyiqa_scorer.PYIQA_MODELS) ---
    _pyiqa('pyiqa', 'pyiqa (package)', 'every pyiqa-backed scorer below', 'qrealign_native',
           'The package itself: importing it is refused in commercial mode.'),
    _pyiqa('topiq', 'TOPIQ NR', 'aesthetic / quality_score (12gb, 16gb, 24gb)', 'qrealign_native'),
    _pyiqa('hyperiqa', 'HyperIQA', 'quality (optional)', 'qrealign_native'),
    _pyiqa('dbcnn', 'DBCNN', 'quality (optional)', 'qrealign_native'),
    _pyiqa('musiq', 'MUSIQ', 'quality (optional)', 'qrealign_native'),
    _pyiqa('musiq-koniq', 'MUSIQ (KonIQ)', 'quality (optional)', 'qrealign_native'),
    _pyiqa('clipiqa+', 'CLIP-IQA+', 'quality (optional)', 'qrealign_native'),
    _pyiqa('topiq_iaa', 'TOPIQ IAA', 'aesthetic_iaa (supplementary)', None,
           'No permissive replacement: the metric is unavailable in commercial mode.'),
    _pyiqa('topiq_nr_face', 'TOPIQ NR-Face', 'face_quality_iqa (supplementary)', 'ofiq'),
    _pyiqa('liqe', 'LIQE', 'quality + distortion diagnosis (supplementary)', None,
           'No permissive replacement: the metric is unavailable in commercial mode.'),
    _c('qrealign_native', 'Q-ReAlign Mini/Lite (transformers)', 'weights', 'MIT',
       'Apache-2.0', 'yes', 'https://huggingface.co/q-future', 'qrealign_score (extended IQA); '
       'aesthetic / quality_score (commercial mode)', None,
       'Loaded through transformers (models/qrealign_native.py); no pyiqa involved.'),
    # --- faces ---
    _c('insightface', 'InsightFace buffalo_l', 'weights', 'MIT (package)',
       'Non-commercial research only', 'no', 'https://github.com/deepinsight/insightface',
       'face detection, recognition, 106-point landmarks', 'yunet',
       'Commercial licences are available from recognition-oss-pack@insightface.ai. '
       "Immich's personal-use InsightFace permission does not extend to its users."),
    _c('yunet', 'YuNet (opencv_zoo)', 'weights', 'MIT', 'MIT', 'yes',
       'https://github.com/opencv/opencv_zoo', 'face detection (commercial mode)'),
    _c('sface', 'SFace (opencv_zoo)', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://github.com/opencv/opencv_zoo', 'face recognition (commercial mode)'),
    _c('mediapipe_face_landmarker', 'MediaPipe face_landmarker', 'weights', 'Apache-2.0',
       'Model cards Apache-2.0; bundle licence not stated', 'yes',
       'https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker',
       'eyes / smile blendshapes', None,
       'Marked permissive on the strength of the model cards.'),
    _c('ofiq', 'OFIQ (BSI, python-ofiq)', 'package', 'MIT', 'MIT / Apache-2.0 per LICENSE.md',
       'yes', 'https://github.com/BSI-OFIQ/OFIQ-Project', 'face_quality_iqa (optional)'),
    # --- embeddings / tagging / saliency ---
    _c('siglip2', 'SigLIP 2 NaFlex SO400M', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/google/siglip2-so400m-patch16-naflex',
       'embeddings (12gb, 16gb, 24gb)'),
    _c('clip', 'OpenCLIP ViT-L-14 (laion2b)', 'weights', 'MIT', 'MIT', 'yes',
       'https://github.com/mlfoundations/open_clip', 'embeddings + tagging (legacy, 8gb)'),
    _c('qwen2_vl', 'Qwen2-VL-2B', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct', 'composition (deprecated)'),
    _c('qwen2_5_vl_7b', 'Qwen2.5-VL-7B', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct', 'tagging (deprecated)'),
    _c('qwen3_vl_2b', 'Qwen3-VL-2B', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct', 'tagging (deprecated)'),
    _c('qwen3_5_2b', 'Qwen3.5-2B', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/Qwen/Qwen3.5-2B', 'tagging (12gb, 16gb)'),
    _c('qwen3_5_4b', 'Qwen3.5-4B', 'weights', 'Apache-2.0', 'Apache-2.0', 'yes',
       'https://huggingface.co/Qwen/Qwen3.5-4B', 'tagging (24gb)'),
    _c('birefnet', 'BiRefNet_dynamic', 'weights', 'MIT', 'MIT', 'yes',
       'https://huggingface.co/ZhengPeng7/BiRefNet_dynamic', 'subject saliency'),
    # --- aesthetic / composition ---
    _c('clip_mlp_head', 'CLIP-MLP aesthetic head (LAION)', 'weights', 'Apache-2.0',
       'No licence stated; trained on AVA', 'unclear',
       'https://github.com/christophschuhmann/improved-aesthetic-predictor',
       'aesthetic (legacy, 8gb)', 'qrealign_native'),
    _c('samp_net', 'SAMP-Net (CADB)', 'weights', 'MIT', 'No licence stated; Facet re-hosts',
       'unclear', 'https://github.com/bcmi/Image-Composition-Assessment-Dataset-CADB',
       'composition (14 patterns)', None, 'Commercial mode falls back to rule-based composition.'),
    _c('u2netp', 'U2-Net-P', 'weights', 'Apache-2.0', 'No licence stated; Facet re-hosts',
       'unclear', 'https://github.com/xuebinqin/U-2-Net', 'SAMP-Net saliency input'),
    _c('deqa', 'DeQA-Score', 'weights', 'MIT', 'MIT (Llama-2 base; treat as unclear)',
       'unclear', 'https://github.com/zhiyuanyou/DeQA-Score', 'extended IQA (off by default)'),
    _c('aesthetic_v25', 'aesthetic-predictor-v2-5', 'package', 'AGPL-3.0', '-', 'no',
       'https://github.com/discus0434/aesthetic-predictor-v2-5',
       'extended IQA (deprecated, off by default)', 'qrealign_native',
       'Copyleft; treated as not commercial-safe.'),
)}

# ModelManager.load_model_only() routing names that are not themselves a
# registry id. Every other loader name (the pyiqa ones included) IS an id.
LOADER_COMPONENTS: dict[str, str] = {
    'clip_aesthetic': 'clip_mlp_head',
    'vlm_tagger': 'qwen2_5_vl_7b',
    'qwen3_vl_tagger': 'qwen3_vl_2b',
    'qwen3_5_tagger': 'qwen3_5_2b',
    'qwen3_5_4b_tagger': 'qwen3_5_4b',
    'saliency': 'birefnet',
    'qrealign': 'qrealign_native',
    'qrealign_quality': 'qrealign_native',
    'faces_permissive': 'yunet',
}


def component_for_loader(loader_name: str) -> str:
    """Registry id for a ModelManager loader name."""
    return LOADER_COMPONENTS.get(loader_name, loader_name)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Policy:
    mode: str = MODE_DEFAULT
    allow_unclear: bool = False


_policy: Optional[Policy] = None


def _require_bool(allow_unclear) -> bool:
    if not isinstance(allow_unclear, bool):
        raise ValueError(
            f"licensing.allow_unclear must be a JSON boolean (true or false), got {allow_unclear!r}")
    return allow_unclear


def _validated(mode: str, allow_unclear: bool) -> Policy:
    if mode not in MODES:
        raise ValueError(f"licensing.mode must be one of {MODES}, got {mode!r}")
    return Policy(mode, _require_bool(allow_unclear))


def env_forces_commercial() -> bool:
    """Whether ``$FACET_LICENSING_MODE`` forces commercial mode.

    The value is stripped and lower-cased. ``commercial`` overrides any file
    value; ``default`` or empty is no override (it can never relax a file that
    says commercial); anything else raises ``ValueError`` so a typo cannot
    silently leave a commercial install running in default mode.
    """
    value = os.environ.get(LICENSING_MODE_ENV, '').strip().lower()
    if not value or value == MODE_DEFAULT:
        return False
    if value == MODE_COMMERCIAL:
        return True
    raise ValueError(
        f"{LICENSING_MODE_ENV}={value!r} is invalid; allowed values: "
        f"{MODE_COMMERCIAL!r}, {MODE_DEFAULT!r} or empty")


_ENV_FALSE = ('0', 'false', 'no', 'off')
_ENV_TRUE = ('1', 'true', 'yes', 'on')


def env_forbids_unclear() -> bool:
    """Whether ``$FACET_LICENSING_ALLOW_UNCLEAR`` forces ``allow_unclear`` off.

    Tighten-only, like :func:`env_forces_commercial`: a false value (``0``,
    ``false``, ``no``, ``off``) overrides a file that says true; a true value or
    an empty one is no override and can never grant what the file withholds.
    Anything else raises ``ValueError``.
    """
    value = os.environ.get(LICENSING_ALLOW_UNCLEAR_ENV, '').strip().lower()
    if not value or value in _ENV_TRUE:
        return False
    if value in _ENV_FALSE:
        return True
    raise ValueError(
        f"{LICENSING_ALLOW_UNCLEAR_ENV}={value!r} is invalid; allowed values: "
        f"{', '.join(_ENV_FALSE + _ENV_TRUE)} or empty")


def licensing_block(cfg: Optional[Mapping]) -> dict:
    """The effective ``{'mode', 'allow_unclear'}`` of a config dict, env overrides applied.

    ``allow_unclear`` must be a real boolean: a hand-edited ``"false"`` string
    is truthy, so coercing it would silently grant the unclear-licence
    components in commercial mode.
    """
    block = (cfg or {}).get('licensing') or {}
    mode = MODE_COMMERCIAL if env_forces_commercial() else block.get('mode', MODE_DEFAULT)
    allow_unclear = _require_bool(block.get('allow_unclear', False))
    if env_forbids_unclear():
        allow_unclear = False
    return {'mode': mode, 'allow_unclear': allow_unclear}


def resolve_policy(cfg: Optional[Mapping]) -> Policy:
    """Policy for a resolved config dict; an absent ``licensing`` block is default mode."""
    block = licensing_block(cfg)
    return _validated(block['mode'], block['allow_unclear'])


def set_policy(mode: str, allow_unclear: bool = False) -> Policy:
    global _policy
    _policy = _validated(mode, allow_unclear)
    return _policy


def reset_policy() -> None:
    global _policy
    _policy = None


def policy() -> Policy:
    """The active policy; resolved once from the resolved config when never set.

    Lazy resolution is what stops a script, or a child process spawned without
    ``--config``, from bypassing commercial mode.
    """
    global _policy
    if _policy is None:
        from config_resolve import load_resolved
        _policy = resolve_policy(load_resolved())
    return _policy


def _component(component_id: str) -> Component:
    try:
        return COMPONENTS[component_id]
    except KeyError:
        raise KeyError(f"Unknown licensing component {component_id!r}") from None


def allowed(component_id: str, policy_: Optional[Policy] = None) -> bool:
    comp = _component(component_id)
    pol = policy_ or policy()
    if pol.mode == MODE_DEFAULT:
        return True
    return comp.commercial == 'yes' or (comp.commercial == 'unclear' and pol.allow_unclear)


def require(component_id: str, policy_: Optional[Policy] = None) -> None:
    """Raise :class:`LicenceError` unless the policy allows the component."""
    if allowed(component_id, policy_):
        return
    comp = COMPONENTS[component_id]
    hint = (f" Use '{comp.replacement}' instead." if comp.replacement
            else ' It has no permissive replacement.')
    unclear = (" Set licensing.allow_unclear to true to accept its unclear licence."
               if comp.commercial == 'unclear' else '')
    raise LicenceError(
        f"{comp.name} ({comp.id}) is not permitted in licensing.mode 'commercial': "
        f"licence status is '{comp.commercial}' (code: {comp.code_licence}; "
        f"weights: {comp.weights_licence}).{hint}{unclear}"
    )


def loader_allowed(loader_name: str, policy_: Optional[Policy] = None) -> bool:
    """Whether the policy lets a ModelManager loader name run.

    A name the registry does not know is not allowed in commercial mode: the
    queue layer must never schedule a model nobody has classified.
    """
    component_id = component_for_loader(loader_name)
    if component_id not in COMPONENTS:
        return not is_commercial(policy_)
    return allowed(component_id, policy_)


def is_commercial(policy_: Optional[Policy] = None) -> bool:
    """Whether the active policy is ``commercial`` mode."""
    return (policy_ or policy()).mode == MODE_COMMERCIAL


def unavailable_metrics(policy_: Optional[Policy] = None) -> set[str]:
    """Metrics that cannot be computed under the active policy."""
    pol = policy_ or policy()
    if pol.mode == MODE_DEFAULT:
        return set()
    out = {'liqe', 'aesthetic_iaa'}
    if importlib.util.find_spec('ofiq') is None:
        out.add('face_quality_iqa')
    if not allowed('deqa', pol):
        out.add('deqa')
    if not allowed('aesthetic_v25', pol):
        out.add('aesthetic_v25')
    return out


# ---------------------------------------------------------------------------
# Documentation table
# ---------------------------------------------------------------------------

_HEADERS = {
    'en': ('Component', 'Code licence', 'Weights licence', 'Commercial use', 'Used for', 'Replacement'),
    'de': ('Komponente', 'Code-Lizenz', 'Gewichte-Lizenz', 'Kommerzielle Nutzung', 'Verwendet für', 'Ersatz'),
    'es': ('Componente', 'Licencia del código', 'Licencia de los pesos', 'Uso comercial', 'Se usa para', 'Reemplazo'),
    'fr': ('Composant', 'Licence du code', 'Licence des poids', 'Usage commercial', 'Utilisé pour', 'Remplacement'),
    'it': ('Componente', 'Licenza del codice', 'Licenza dei pesi', 'Uso commerciale', 'Usato per', 'Sostituto'),
    'pt': ('Componente', 'Licença do código', 'Licença dos pesos', 'Uso comercial', 'Usado para', 'Substituto'),
    'zh': ('组件', '代码许可证', '权重许可证', '商业使用', '用途', '替代'),
}
_STATUS = {
    'en': {'yes': 'yes', 'no': 'no', 'unclear': 'unclear'},
    'de': {'yes': 'ja', 'no': 'nein', 'unclear': 'unklar'},
    'es': {'yes': 'sí', 'no': 'no', 'unclear': 'poco claro'},
    'fr': {'yes': 'oui', 'no': 'non', 'unclear': 'incertain'},
    'it': {'yes': 'sì', 'no': 'no', 'unclear': 'incerto'},
    'pt': {'yes': 'sim', 'no': 'não', 'unclear': 'incerto'},
    'zh': {'yes': '是', 'no': '否', 'unclear': '不明确'},
}
LANGUAGES = tuple(_HEADERS)


def _cell(text: str) -> str:
    return text.replace('|', '\\|').replace('\n', ' ')


def render_markdown(lang: str = 'en') -> str:
    """The generated licence table (no trailing newline)."""
    if lang not in _HEADERS:
        raise KeyError(f"Unsupported language {lang!r}")
    headers = _HEADERS[lang]
    status = _STATUS[lang]
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    for comp in COMPONENTS.values():
        repl = f'`{comp.replacement}`' if comp.replacement else '-'
        row = (f'[{comp.name}]({comp.source_url}) (`{comp.id}`)', comp.code_licence,
               comp.weights_licence, status[comp.commercial], comp.slot, repl)
        lines.append('| ' + ' | '.join(_cell(c) for c in row) + ' |')
    return '\n'.join(lines)
