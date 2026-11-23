# Fork policy: reannu123/switchboard

This fork tracks [Soju06/codex-lb](https://github.com/Soju06/codex-lb). Where this file and
[CONTRIBUTING.md](CONTRIBUTING.md) disagree, this file governs work that lands on the
fork's `main`. Upstream's CONTRIBUTING.md still governs anything proposed upstream.

## Merge gates for fork `main`

A PR may merge only when all of these hold on its **current head SHA**:

1. **`Fork CI required` is green.** This is the only CI check the fork requires
   ([`fork-ci.yml`](workflows/fork-ci.yml)). It passes only when every group that the
   change selects has passed:

   | Group | Runs when | Blocking |
   |---|---|---|
   | Policy: upstream-workflow retirement inventory, OpenSpec (`--specs` and changed folders, strict) | always | yes |
   | Ruff, architecture checks (`make lint`, including migration topology), `ty` | backend paths | yes |
   | Unit, simulation and request-log tests (`make test-unit`) | backend paths | yes |
   | Focused integration: routing/load balancer/stickiness, API keys and permission matrix, warm-up and usage-refresh scheduling, SQLite migrations ([list](fork/focused-integration-tests.txt)), and `make migration-check` | backend paths | yes |
   | Frontend `tsc`, eslint, vitest, vite build | `frontend/**` | yes |
   | Rust fmt, clippy, tests, release build, native wire probes, `cargo deny` bans/licenses/sources | Rust paths | yes |
   | `cargo deny` advisories | Rust paths | **reported only**: the RustSEC advisories in `Cargo.lock` are inherited from upstream |
   | Container image: Linux build, boot, `/health/ready`, **Trivy CRITICAL/HIGH** | Dockerfile, lockfiles, `pyproject.toml` | yes |

   Changing the fork CI itself selects every group except the container image. The image
   group is triggered only by image inputs, so a CI-only change is not blocked by
   lockfile or base-image advisories it did not introduce.
2. The merge state is **CLEAN**: no failing check of any kind. A failing check that is
   not required still blocks a merge.
3. No unresolved, non-outdated review threads. Native (Orchestrator) review findings are
   fixed or answered in-thread. Native review is not a GitHub review, and it never
   counts as an approval.
4. Behavior, API, schema, or dashboard changes carry an OpenSpec change folder
   (AGENTS.md "Workflow"). A PR does one thing.
5. For agent-prepared PRs, the orchestrator verifies the gates and coordinates each
   merge. Production deployment always needs the owner's direct approval
   ([runbook](../deploy/README.md)).

Once this policy is adopted, `main` branch protection requires `Fork CI required` and
blocks force pushes and deletion. Until then the gates above are enforced by review and
orchestrator coordination. Admin bypass is never used to land a change.

## Image publishing

[`fork-image.yml`](workflows/fork-image.yml) publishes `ghcr.io/reannu123/codex-lb` (the package name is fixed and is not derived
from the repository name; this repository was renamed from `reannu123/codex-lb`). It runs
only after `Fork CI` succeeds for a push to `main`, or by manual dispatch, which itself
requires a successful Fork CI push run for the commit at the tip of `main`. It builds
that exact commit, boots it, requires `/health/ready`, and applies the **blocking Trivy
CRITICAL/HIGH** gate before pushing anything. It pushes the immutable tag
`sha-<full sha>` and the moving tag `fork-main`. The immutable tag is never overwritten: a
retry reuses the digest first published under it. Only the current tip of `main` is
published: a rerun for a superseded commit publishes nothing, and `fork-main` is promoted
only if the commit is still the tip at promotion time. It never pushes `latest` or release
tags. Deploying an image is a separate step that needs the owner's direct approval.

After a publish, the same workflow's `promote-production` job runs
[`deploy/promote-production.py`](../deploy/promote-production.py). It prepares a pull request
into `deploy/production`, the branch Portainer deploys with GitOps updates off, that changes
only the image digest: it pushes the branch and puts a prefilled one-click "Create pull
request" link in the run summary. The owner opens the PR, as GitHub Actions is not allowed
to create pull requests in this repository. It reads the deployed commit from the
`org.opencontainers.image.revision` label of the currently pinned image and refuses unless
the new image's label is the published commit and that commit is on `main` and descends from
the deployed one. It pushes only a new `promote/production-<sha12>` branch, never
`deploy/production`, and never merges. Merging and deploying stay with the owner.

## Broad suites

[`fork-ci-broad.yml`](workflows/fork-ci-broad.yml) is run manually from the Actions tab. It
runs all integration-core shards, the bridge and e2e suites, and PostgreSQL (migration
check and suite). Run it before risky merges and after every upstream import.

## Retired upstream workflows

Upstream workflows stay in the tree unchanged, except that their root jobs carry
`if: github.repository == 'Soju06/codex-lb'`, the guard upstream already uses for
`update-upstream-metadata`. Upstream behavior is therefore identical, and imports merge
with at most one-line conflicts. Retired on the fork:

- `ci.yml` except its OpenSpec job, including contributor attribution, Helm, Nix, and the
  upstream Docker job
- release guards, Release Please, beta release prepare and publish, and `release.yml`
- the docs Pages deploy
- issue and PR labelers
- the stale bot
- the Windows startup check

Kept: `simplicity-budgets.yml`, the docs build (`mkdocs --strict`), and `ci.yml`'s
`OpenSpec validation` job, which upstream requires to run unconditionally on every PR.

The policy job in Fork CI fails when an upstream workflow job would run on the fork
without being guarded or listed as kept in
[`check_workflow_retirement.py`](fork/check_workflow_retirement.py).

## Importing upstream

1. Branch from fork `main`, then `git merge upstream/main`. Never rebase or force-push.
2. Resolve conflicts. If a retired workflow conflicts, keep upstream's change and re-apply
   the guard on its root jobs.
3. Open a PR. `Fork CI required` must pass, including the retirement inventory, which
   catches any new upstream workflow or job.
4. Run the broad suite before merging.
