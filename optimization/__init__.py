"""
Facet optimization package.

Weight optimization using pairwise comparison feedback.
"""

from optimization.weight_optimizer import (
    WeightOptimizer,
    print_comparison_stats,
    run_weight_optimization,
)
from optimization.personal_ranker import train_ranker
