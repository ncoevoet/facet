"""
Best-of-group lead selection (Topic 4 step 6).

Burst and duplicate groups historically picked the lead purely by max(aggregate).
That ignores which frame actually has open eyes / a composed expression / sharper
faces — the things that decide "which of these near-identical shots is the keeper".

``composite_lead_score`` keeps ``aggregate`` as the dominant term and adds a small,
bounded tie-break that nudges selection toward open eyes, a composed expression,
and sharper faces. The tie-break magnitude is small enough that a meaningful
aggregate gap is never overridden — it only decides near-ties (e.g. two burst
frames with equal aggregate where one is mid-blink).

For photos with no faces, the eyes/expression terms are absent (NULL), so the
score degrades to aggregate plus the sharpness nudge.
"""

# Tie-break weights, centered on a neutral 5.0 so a score equals aggregate when
# the secondary signals are neutral/absent. Bounded swings:
#   eyes:        +/-0.15   (5pts * 0.03)
#   expression:  +/-0.075  (5pts * 0.015)
#   sharpness:   +/-0.05   (5pts * 0.01)
# => a blink (eyes ~1) loses ~0.27 to an open-eyes frame (eyes ~10) of equal aggregate.
_EYES_W = 0.03
_EXPR_W = 0.015
_SHARP_W = 0.01
_LEARNED_W = 0.05   # personal-ranker nudge (Topic 4 step 7); inert when learned_score absent
_NEUTRAL = 5.0


def composite_lead_score(photo):
    """Composite best-of score: aggregate (dominant) + bounded tie-break terms.

    ``photo`` is a mapping with optional keys: aggregate, face_count,
    eyes_open_score, expression_score, tech_sharpness, learned_score.

    The optional ``learned_score`` (personal-ranker output, Topic 4 step 7) only
    contributes when present and non-None — when no learned_scores rows exist it
    is simply absent, so selection is identical to the eyes/expression behavior.
    """
    score = float(photo.get('aggregate') or 0.0)
    face_count = photo.get('face_count') or 0

    if face_count and face_count > 0:
        eyes = photo.get('eyes_open_score')
        expr = photo.get('expression_score')
        if eyes is not None:
            score += (float(eyes) - _NEUTRAL) * _EYES_W
        if expr is not None:
            score += (float(expr) - _NEUTRAL) * _EXPR_W

    sharp = photo.get('tech_sharpness')
    if sharp is not None:
        score += (float(sharp) - _NEUTRAL) * _SHARP_W

    learned = photo.get('learned_score')
    if learned is not None:
        score += (float(learned) - _NEUTRAL) * _LEARNED_W

    return score


def pick_lead(photos):
    """Return the lead photo (dict) of a group by composite_lead_score, or None."""
    if not photos:
        return None
    return max(photos, key=composite_lead_score)
