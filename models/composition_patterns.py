"""Composition pattern labels used by SAMP-Net's spatial pooling strategies.

Kept out of ``models/samp_net.py`` (which imports torch at module scope) so
read-only CLI paths such as ``--list-models`` can report the pattern count
without pulling in the ML stack.
"""

# 8 composition patterns based on spatial pooling strategies
COMPOSITION_PATTERNS = [
    'global',           # 0: Global average pooling
    'horizontal',       # 1: Upper/lower halves
    'vertical',         # 2: Left/right halves
    'triangular',       # 3: Triangular regions
    'surround',         # 4: Center vs surroundings
    'quarter',          # 5: 2x2 grid
    'cross',            # 6: Cross divisions
    'rule_of_thirds',   # 7: 3x3 composition grid
]
