# Production deployment (fork)

Runbook for deploying Switchboard (`ghcr.io/reannu123/codex-lb`) to **pm-docker** with a
Portainer Git stack. There is no staging environment. Every deploy is an owner-approved
change to production.

| Piece | Where |
|---|---|
| Stack definition | `deploy/portainer/compose.yaml` on the **`deploy/production`** branch |
| Promotion PRs | prepared by the `promote-production` job of [Fork image](../.github/workflows/fork-image.yml) ([policy](../.github/FORK_POLICY.md#image-publishing)): it pushes `promote/production-<sha12>` and the run summary links a prefilled PR you open |
| Backup / restore / rehearsal | [`backup.sh`](backup.sh), [`restore.sh`](restore.sh), [`rehearse-migration.sh`](rehearse-migration.sh) |
| Data | `/docker/appdata/codex-lb` (`store.db`, `encryption.key`) |
| Backups | `/docker/backups/codex-lb/<label>-<UTC timestamp>/` (`SHA256SUMS`, `manifest.json`) |

Invariants:

- **Only one stack ever mounts `/docker/appdata/codex-lb`.** The compose file fixes
  `container_name: codex-lb`, so a second copy fails to start instead of opening the same
  SQLite store. The backup and restore scripts refuse to run while any other running
  container mounts the data dir.
- **Migrations are one-way.** An image starts by migrating `store.db` to its head. An older
  image refuses a newer schema (`schema revision(s) … are not known to this build`), so a
  rollback always pairs the old digest with the backup taken before the deploy.
- GitOps updates stay **off**. Merging a promotion PR deploys nothing until someone runs
  *Pull and redeploy*.

## Portainer stack settings

Stacks → Add stack → **Repository**:

| Field | Value |
|---|---|
| Name | `switchboard` (not `codex-lb`, so the old host project can never adopt it) |
| Repository URL | `https://github.com/reannu123/switchboard.git` |
| Repository reference | `refs/heads/deploy/production` |
| Compose path | `deploy/portainer/compose.yaml` |
| Authentication | off (public repository) |
| GitOps updates | **off** |
| Environment variables | none. The file has no secrets. If a sensitive setting is ever needed, add it here as a stack variable and reference it as `${NAME}`; never commit it. |
| Registry | none. The GHCR package is public (anonymous pulls work). If it is ever made private, add a `ghcr.io` registry with a PAT that has only `read:packages`. |

## Host tools checkout (one time)

The scripts run on pm-docker from a checkout of `main`. They use bash, coreutils, `flock`,
Docker and the host's `python3`:

```sh
git clone https://github.com/reannu123/switchboard.git /docker/compose/switchboard
```

Before every use: `git -C /docker/compose/switchboard pull --ff-only`. The commands below run
from `/docker/compose/switchboard`.

## Deploy

1. **Open and review the promotion PR.** In the Fork image run summary, click *Create the
   promotion pull request* (`chore(deploy): promote <sha12> to production`). Its only
   change is the digest. Read the compare link in the body.
2. **Rehearse the migration** against the newest backup (take one first if it is stale;
   the backup stops the app for about a minute):

   ```sh
   deploy/backup.sh --label rehearsal          # only if the newest backup is stale
   deploy/rehearse-migration.sh ghcr.io/reannu123/codex-lb@sha256:<new digest>
   ```

   It must end with `REHEARSAL OK: … <old revision> -> <new revision>`. Note the new
   revision for step 6. Any `REHEARSAL FAILED` stops the deploy.
3. **Merge the PR** on GitHub. Close any PRs it lists as superseded.
4. **Back up**, leaving the app stopped:

   ```sh
   deploy/backup.sh --label pre-<sha12> --leave-stopped
   ```

   It must print `BACKUP OK: /docker/backups/codex-lb/pre-<sha12>-<ts>`. Note the name.
   On `BACKUP FAILED` the app is restarted on the old image. Investigate and do not deploy.
5. **Portainer** → Stacks → `switchboard` → **Pull and redeploy** (re-pull the image). Check
   that it shows the merged `deploy/production` commit.
6. **Verify**:

   ```sh
   docker inspect -f '{{.Config.Image}} {{.State.Health.Status}}' codex-lb   # new digest, healthy
   curl -fsS http://100.105.49.87:2455/health/ready                          # "status":"ok"
   curl -fsS http://codex-lb.home/health/ready     # via Nginx Proxy Manager -> pm-docker LAN :2455
   docker exec codex-lb python -m app.db.migrate current                     # revision from step 2
   docker logs --since 15m codex-lb 2>&1 | grep -iE 'error|traceback'        # expect nothing new
   ```

   Then sign in to the dashboard at `http://100.105.49.87:2455/` and check that accounts
   and recent requests look right.

If step 5 or 6 fails, roll back.

## Rollback

Data written after the pre-deploy backup is lost. Rolling back is the old digest **and**
the matching backup:

1. On GitHub, open the merged promotion PR → **Revert**, then merge the revert PR into
   `deploy/production`. It pins the previous digest again.
2. Restore the pre-deploy backup. This stops the container and leaves it stopped:

   ```sh
   deploy/restore.sh pre-<sha12>-<ts> --yes
   ```

   It prints the image recorded in the backup's manifest, which must be the digest from
   step 1. The replaced files are kept in `/docker/backups/codex-lb/pre-restore-<ts>/`.
3. Portainer → **Pull and redeploy**, then verify as in Deploy step 6, with the old digest
   and the backup's revision (`schema` in its `manifest.json`).

The next promotion still works: new `main` commits descend from the restored commit.

## One-time handover from the host compose file

Done once, in a maintenance window the owner picks. The Portainer stack takes over with the
**same image and the same data**. `deploy/production` starts at the digest the host runs
(`sha256:9f7464be…0285`, revision `1eee39f9`). Before the window, check that
`docker inspect -f '{{.Config.Image}}' codex-lb` on pm-docker still shows that digest. If
it does not, first change `deploy/production` to match through a reviewed PR.

1. `git -C /docker/compose/switchboard pull --ff-only`.
2. Back up and leave the app stopped:
   `deploy/backup.sh --label pre-portainer --leave-stopped`. It must print `BACKUP OK`.
3. Retire the host project, so it can never start a second copy:

   ```sh
   cd /docker/compose/codex-lb
   docker compose down                       # removes the container and network, not data
   mv compose.yaml compose.yaml.retired-portainer-$(date -u +%Y%m%d)
   docker ps -a --format '{{.Names}}' | grep -x codex-lb   # must print nothing
   ```

4. Create the Portainer stack with the settings above → **Deploy the stack**.
5. Verify as in Deploy step 6 (same digest, same revision, sign-in works).

To back out of the handover (data unchanged, so no restore is needed): delete the
`switchboard` stack in Portainer, then
`mv compose.yaml.retired-portainer-* compose.yaml && docker compose up -d` in
`/docker/compose/codex-lb`. Use `restore.sh pre-portainer-<ts>` only if the data was damaged.

## Housekeeping

Backups are not pruned automatically. Each one is about the size of `store.db` (about 0.8 GB).
Delete old directories under `/docker/backups/codex-lb/` by hand, and keep at least the
backup from before the current deploy. `*.failed` directories are failed attempts and are
never valid backups.
