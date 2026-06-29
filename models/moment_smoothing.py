"""L2 temporal smoothing for narrative moments — Viterbi over the timeline.

Weddings follow a near-fixed script (getting ready -> ceremony -> portraits ->
reception -> party). The zero-shot classifier is context-blind, so an isolated
misread (a rings close-up at dinner labelled ``ring_exchange``) survives. This
layer smooths the per-frame probability vectors with a soft transition matrix
built from the canonical moment order, pulling stray frames back into the
surrounding run. It is a pure function — no model, no I/O.
"""

import numpy as np
from scipy.special import logsumexp

_EPS = 1e-9
_DEFAULT_SEGMENT_GAP_SECONDS = 6 * 3600


def _transition_matrix(n, stay_prob, forward_bias, floor=0.01):
    """Soft row-stochastic matrix: strong self-loop + forward step, tiny else."""
    matrix = np.full((n, n), floor, dtype=np.float64)
    for i in range(n):
        matrix[i, i] += stay_prob
        if i + 1 < n:
            matrix[i, i + 1] += forward_bias
    return matrix / matrix.sum(axis=1, keepdims=True)


def _segment_ranges(timestamps, gap_seconds):
    """Split the timeline into (start, end) ranges on large capture-time gaps."""
    ranges = []
    start = 0
    for i in range(1, len(timestamps)):
        a, b = timestamps[i - 1], timestamps[i]
        if a is not None and b is not None and (b - a).total_seconds() > gap_seconds:
            ranges.append((start, i))
            start = i
    ranges.append((start, len(timestamps)))
    return ranges


def _forward_backward(log_emit, log_trans):
    """Per-frame log-posterior log P(state=j | all observations in the segment).

    Soft-assignment counterpart of the Viterbi MAP path: γ_t(j) integrates the
    emission with the full past (α) and future (β) context, so a per-frame
    ambiguous state flanked by a confident run scores HIGH for the run's state.
    The transition kernel is the same ``T**weight`` Viterbi uses (so γ is a
    tempered posterior, not a coherent-HMM one), and it reduces to the
    normalized per-frame emission at ``weight=0``.
    """
    n, m = log_emit.shape
    if n == 0:
        return log_emit
    log_alpha = np.empty((n, m))
    log_alpha[0] = log_emit[0]
    for t in range(1, n):
        log_alpha[t] = log_emit[t] + logsumexp(log_alpha[t - 1][:, None] + log_trans, axis=0)
    log_beta = np.zeros((n, m))
    for t in range(n - 2, -1, -1):
        log_beta[t] = logsumexp(log_trans + (log_emit[t + 1] + log_beta[t + 1]), axis=1)
    log_gamma = log_alpha + log_beta
    log_gamma -= logsumexp(log_gamma, axis=1, keepdims=True)
    return log_gamma


def _viterbi(log_emit, log_trans):
    """Best state path maximizing summed emission + transition log-scores."""
    n, m = log_emit.shape
    if n == 0:
        return []
    dp = log_emit[0].copy()
    back = np.zeros((n, m), dtype=np.int64)
    for t in range(1, n):
        scored = dp[:, None] + log_trans          # (prev, cur)
        best_prev = np.argmax(scored, axis=0)
        dp = scored[best_prev, np.arange(m)] + log_emit[t]
        back[t] = best_prev
    path = [int(np.argmax(dp))]
    for t in range(n - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    path.reverse()
    return path


def smooth(prob_vectors, timestamps, transitions, segment_gap_seconds=_DEFAULT_SEGMENT_GAP_SECONDS):
    """Viterbi-smooth per-frame moment probabilities along the timeline.

    Args:
        prob_vectors: list of probability ndarrays (length M, aligned to the
            canonical order) or None for frames with no usable embedding.
        timestamps: list of datetimes (or None), parallel to prob_vectors.
        transitions: dict with ``order``, ``stay_prob``, ``forward_bias``,
            ``weight``. ``weight=0`` makes the output identical to per-frame
            argmax (transitions contribute nothing).
        segment_gap_seconds: shoots separated by a gap this large are smoothed
            independently so one event's order can't bleed into another's.

    Returns:
        list parallel to the input: ``(moment_index, confidence)`` for usable
        frames, ``(None, None)`` otherwise. ``moment_index`` is the Viterbi MAP
        state; ``confidence`` is its forward-backward posterior γ (temporally
        aware, on a single 0-1 scale), NOT the raw per-frame emission — so a
        frame the smoother rescued reports the run's confidence, not the
        context-blind model's doubt.
    """
    n = len(prob_vectors)
    out = [(None, None)] * n
    order = transitions.get('order', [])
    m = len(order)
    if n == 0 or m == 0:
        return out

    stay = float(transitions.get('stay_prob', 0.6))
    forward = float(transitions.get('forward_bias', 0.3))
    weight = float(transitions.get('weight', 0.5))
    log_trans = weight * np.log(_transition_matrix(m, stay, forward) + _EPS)

    for start, end in _segment_ranges(timestamps, segment_gap_seconds):
        idxs = [i for i in range(start, end) if prob_vectors[i] is not None]
        if not idxs:
            continue
        emit = np.stack([np.asarray(prob_vectors[i], dtype=np.float64) for i in idxs])
        log_emit = np.log(emit + _EPS)
        path = _viterbi(log_emit, log_trans)
        log_gamma = _forward_backward(log_emit, log_trans)
        for local, global_i in enumerate(idxs):
            j = path[local]
            out[global_i] = (j, float(np.exp(log_gamma[local, j])))
    return out
