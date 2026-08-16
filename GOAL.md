# Goal

Land the RAW-exposure / viewer branch `fix/raw-exposure-equalization-105` on `master`,
review-clean and green.

## Done means

1. All oracle stages green: lint, test, typecheck, build.
2. `/review-all:review-all` reports **no Critical, Important or Debt findings** on the branch
   diff vs `master`. `reviewall` is deliberately OUT of `oracle.mandatory` during iteration —
   running a multi-agent review per micro-commit wastes quota — and MUST be re-added for the
   close task so the gate is honest.
3. Every finding at those three severities is fixed by a sub-agent, not inline, then re-reviewed.

## Constraints

- Review target is the BRANCH DIFF vs master, never the whole repo.
- Fixing findings is delegated to sub-agents grouped by area (2-3 max), never one per finding.
- Weekly usage cap **40%**. Baseline at arming: 7d = 27%. Check
  `watch-quota.sh --once` at every checkpoint and STOP at 40%, reporting state.
- STOP and report on any finding that needs a DESIGN decision — anything changing scoring
  semantics or user-visible defaults. Do not choose for the maintainer.
- Do not touch `photo_scores_pro.db` except read-only.

## Out of scope for the loop (orchestrator does these after DONE)

push, PR, CI watch, merge-commit to master, comment on issue #105, release 1.13.0 "Sténopé".

## Context

Full state, measured values with provenance, prior decisions and the release procedure:
`.claude/specs/issue-105-todo.md`. Read it rather than re-deriving.
