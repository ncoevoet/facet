# Collaborating on Facet

You have Write access to `ncoevoet/facet`. This page says what that access covers here, what stays
with the maintainer (@ncoevoet), and how a change gets from a fork to master. Everything in
[CONTRIBUTING.md](../CONTRIBUTING.md) still applies; this page only adds to it.

## What you can do

- **Review and approve pull requests.** Master needs one approving review, and yours counts, with two
  exceptions:
  - a PR whose latest commit you pushed needs someone else to approve that push;
  - a PR that touches `.github/` (workflows, Dependabot, `CODEOWNERS`, this page) needs @ncoevoet's
    approval.

  A new commit dismisses earlier approvals, so an approval always covers the commit that was reviewed.
- **Merge pull requests** once they have that approval and every required check is green on the latest
  commit. Use a merge commit, pinned to the commit you reviewed:

  ```bash
  gh pr merge <number> --merge --match-head-commit <full sha>
  ```

  `--match-head-commit` refuses the merge if anyone pushed after you looked.
- **Approve CI runs for first-time contributors.** A newcomer's PR waits for approval before its
  workflows run. Read the diff first, `.github/` above all.
- **Re-run failed jobs.** If you re-run a failure you believe is flaky, say in the PR which test failed
  and why it is unrelated to the change.
- **Push fixes to a contributor's PR** when *Allow edits by maintainers* is on. Push normally, never
  force-push, and leave a comment saying what you changed and why.
- **Triage**: label, assign, close and reopen issues and pull requests, and answer in Discussions.

## What stays with the maintainer

- **Branches in this repository.** Only @ncoevoet and Dependabot can create, update or delete branches
  other than master here, because a workflow pushed on a branch of this repository runs with write
  access. Work from your fork, as before.
- **Direct pushes to master.** Every change goes through a pull request. Master cannot be force-pushed or
  deleted.
- **Releases.** Only @ncoevoet can create `v*` tags, and a tag is what publishes the Docker images. If a
  change should ship in the next release, or deserves a patch release, say so in the PR or an issue.
- **Repository settings**: branch protection, rulesets, collaborators and Actions settings.
- **Security reports.** Vulnerabilities are reported privately, under *Security › Report a
  vulnerability*. If you find one, report it there too, not in a public issue, PR or discussion.

## Your own change

1. Branch from the latest master in your fork. Keep each PR to a single concern.
2. Run the checks in [Before You Open a PR](../CONTRIBUTING.md#before-you-open-a-pr), and add a
   `CHANGELOG.md` entry under `## [Unreleased]`.
3. Open the PR against master, and ask another collaborator or @ncoevoet to review it. You cannot merge
   your own PR without someone else's approval.
4. When master moves ahead, **merge master into your branch** and push normally. Don't rebase and
   force-push a branch that someone has reviewed or pushed to. `CHANGELOG.md` is the usual conflict:
   keep both sides' entries under `[Unreleased]`.

Commit messages read `type(scope): imperative subject` (`fix(geo): …`, `feat(ui): …`). The body says
why the change is needed and how things behaved before.

## Reviewing a pull request

Before you approve, check that:

- the change does one thing, and the description says why;
- a new test fails without the fix ([Tests](../CONTRIBUTING.md#tests)). If the PR does not show this,
  check it locally;
- a behaviour change updates the English docs in `docs/` and adds a CHANGELOG entry. The translated
  docs (`docs/<lang>/`, `README.<lang>.md`) are left to the maintainer, but UI strings must exist in all
  seven `i18n/translations/` files, which CI checks;
- a new or changed endpoint comes with a regenerated `client/src/app/core/api/schema.d.ts`
  (`npm run gen:api`). CI fails if it is stale.

Leave findings as review comments. Use *Request changes* for anything that must be fixed before the
merge: it blocks merging until the same reviewer approves or the review is dismissed.

## Merging

- Merge only when every required check is green on the latest commit and that commit carries the
  approval.
- A merge often makes other open PRs conflict in `CHANGELOG.md`. Their authors merge master into their
  branch, or you do it for them when *Allow edits by maintainers* is on.
