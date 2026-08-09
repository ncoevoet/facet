"""Benchmark harness for Facet.

Two entry points:

* ``scripts/bench/bench.py`` — HTTP endpoint latency suites (p50/p95/p99).
* ``scripts/bench/scoring_throughput.py`` — ``facet.py`` throughput, RSS, GPU memory.

Results are written to ``bench/results/<UTC-date>-<branch>-<suite>.json`` so
before/after diffs across branches are mechanical.
"""
