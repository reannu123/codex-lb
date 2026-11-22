# deploy/production

Desired state of the Switchboard production stack on pm-docker. Portainer deploys
`deploy/portainer/compose.yaml` from this branch with GitOps updates **off**, so a
change here deploys nothing by itself.

- Changes arrive only as pull requests that bump the image digest, opened by the
  `Fork image` workflow on `main` (`deploy/promote-production.py`). Nothing pushes
  to this branch directly, and nothing auto-merges.
- Runbook (backup, rehearsal, deploy, rollback, handover): `deploy/README.md` on `main`.
