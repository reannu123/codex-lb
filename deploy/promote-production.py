#!/usr/bin/env python3
"""Prepare a pull request that bumps the production image digest on deploy/production.

Runs in the "Fork image" workflow after a verified publish (stdlib only). It
never merges and never pushes to deploy/production: it pushes a NEW branch
``promote/production-<sha12>`` whose only change is the digest on the image
line of deploy/portainer/compose.yaml, and prints a prefilled one-click link
for a person to open the PR into deploy/production. GitHub Actions is not
allowed to create pull requests in this repository, and does not need to be.
A rerun reuses the branch only while it still holds exactly the planned change.

The deployed commit is read from the ``org.opencontainers.image.revision``
label of the image currently pinned on deploy/production. The new image's
label must equal the published commit, and that commit must descend from the
deployed one and be on main. Anything unexpected exits non-zero.

Environment: SOURCE_SHA, IMAGE_DIGEST, GITHUB_REPOSITORY, GH_TOKEN.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PRODUCTION = "deploy/production"
COMPOSE = "deploy/portainer/compose.yaml"
IMAGE_REPO = "reannu123/codex-lb"
BRANCH_PREFIX = "promote/production-"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SHA = re.compile(r"[0-9a-f]{40}")
IMAGE_LINE = re.compile(rb"(?m)^(    image: ghcr\.io/" + re.escape(IMAGE_REPO.encode()) + rb"@)(sha256:[0-9a-f]{64})$")
ZERO = "0" * 40
REVISION_LABEL = "org.opencontainers.image.revision"
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class PromotionError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"PROMOTION REFUSED: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionError(message)


def git(*args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(["git", *args], input=data, env=env, check=True, capture_output=True).stdout


def ancestor(older: str, newer: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], capture_output=True)
    if result.returncode not in (0, 1):
        raise PromotionError(f"cannot compare {older} and {newer}: {result.stderr.decode().strip()}")
    return result.returncode == 0


def fetch(ref: str, destination: str) -> str:
    # '+' only updates a private runner-local ref.
    git("fetch", "--no-tags", "origin", f"+{ref}:{destination}")
    return git("rev-parse", f"{destination}^{{commit}}").decode().strip()


def _registry_json(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{IMAGE_REPO}/{path}", headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def image_revision(digest: str) -> str:
    """Return the source commit recorded in a published image's labels."""
    token_url = f"https://ghcr.io/token?scope=repository:{IMAGE_REPO}:pull"
    with urllib.request.urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    manifest = _registry_json(f"manifests/{digest}", token)
    if "manifests" in manifest:
        platforms = [
            m["digest"]
            for m in manifest["manifests"]
            if m.get("platform", {}).get("os") == "linux" and m.get("platform", {}).get("architecture") == "amd64"
        ]
        require(len(platforms) == 1, f"{digest} has no single linux/amd64 image")
        manifest = _registry_json(f"manifests/{platforms[0]}", token)
    config = _registry_json(f"blobs/{manifest['config']['digest']}", token)
    revision = (config.get("config", {}).get("Labels") or {}).get(REVISION_LABEL, "")
    require(bool(SHA.fullmatch(revision)), f"{digest} has no {REVISION_LABEL} label")
    return revision


@dataclass(frozen=True)
class Plan:
    base: str
    deployed_digest: str
    deployed_source: str
    compose: bytes


def plan(
    source: str, digest: str, base: str, main: str, revision_of: Callable[[str], str] = image_revision
) -> Plan | None:
    """Validate a promotion of ``source``/``digest`` onto deploy/production ``base``.

    Returns None when production already pins ``digest``.
    """
    require(bool(SHA.fullmatch(source)), "SOURCE_SHA must be a full commit SHA")
    require(bool(DIGEST.fullmatch(digest)), "IMAGE_DIGEST must be sha256:<64 hex>")
    current = git("show", f"{base}:{COMPOSE}")
    matches = IMAGE_LINE.findall(current)
    require(len(matches) == 1, f"{PRODUCTION}:{COMPOSE} must have exactly one pinned image line")
    deployed_digest = matches[0][1].decode()
    if deployed_digest == digest:
        return None
    require(ancestor(source, main), f"{source} is not on main")
    require(revision_of(digest) == source, f"{digest} was not built from {source}")
    deployed_source = revision_of(deployed_digest)
    require(deployed_source != source, f"{source} is already deployed under another digest")
    require(
        ancestor(deployed_source, source),
        f"{source} does not descend from the deployed commit {deployed_source}; promote by hand after review",
    )
    compose = IMAGE_LINE.sub(rb"\g<1>" + digest.encode(), current)
    return Plan(base, deployed_digest, deployed_source, compose)


def commit(p: Plan, source: str, digest: str) -> str:
    with tempfile.TemporaryDirectory(prefix="promote-production-") as temp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(temp) / "index")}
        git("read-tree", p.base, env=env)
        blob = git("hash-object", "-w", "--stdin", data=p.compose).decode().strip()
        git("update-index", "--cacheinfo", f"100644,{blob},{COMPOSE}", env=env)
        tree = git("write-tree", env=env).decode().strip()
    message = f"chore(deploy): promote {source[:12]} to production\n\nSource: {source}\nDigest: {digest}\n"
    return git("commit-tree", tree, "-p", p.base, data=message.encode()).decode().strip()


def push_new_branch(local: str, branch: str) -> None:
    """Create ``branch`` on origin; the hook rejects any other ref or an update."""
    with tempfile.TemporaryDirectory(prefix="promote-hook-") as hooks:
        hook = Path(hooks) / "pre-push"
        hook.write_text(
            "#!/bin/sh\nset -eu\n"
            "read -r local_ref local_oid remote_ref remote_oid\n"
            f'test "$remote_ref" = "refs/heads/{branch}"\n'
            f'test "$remote_oid" = "{ZERO}"\n'
            f'test "$local_oid" = "{local}"\n'
            "if read -r extra; then exit 1; fi\n"
        )
        hook.chmod(0o700)
        git("-c", f"core.hooksPath={hooks}", "push", "origin", f"{local}:refs/heads/{branch}")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout.strip()


def body(p: Plan, source: str, digest: str, repo: str, superseded: list[str]) -> str:
    lines = [
        "Bumps the production image digest. The only change is the `image:` line of",
        f"`{COMPOSE}`. Prepared by the Fork image workflow; never auto-merged.",
        "",
        "| | Commit | Digest |",
        "|---|---|---|",
        f"| deployed | `{p.deployed_source}` | `{p.deployed_digest}` |",
        f"| proposed | `{source}` | `{digest}` |",
        "",
        f"Changes: https://github.com/{repo}/compare/{p.deployed_source}...{source}",
        "",
        "Checked: the proposed image's revision label is the published commit, that commit",
        "is on `main` and descends from the deployed commit, and Fork CI, the boot probe and",
        "the Trivy gate passed before publishing.",
        "",
        "Deploy (deploy/README.md on main): rehearse the migration with this digest, merge,",
        "run `deploy/backup.sh`, then Pull and redeploy in Portainer and verify.",
    ]
    if superseded:
        lines += ["", "Supersedes open promotion PRs: " + ", ".join(superseded) + " (close them after merging)."]
    return "\n".join(lines) + "\n"


def remote_branch(branch: str) -> str | None:
    out = git("ls-remote", "--heads", "origin", f"refs/heads/{branch}").decode().split()
    return out[0] if out else None


def same_change(branch: str, planned: str) -> bool:
    """True when ``branch`` holds the planned parent and tree (commit SHAs differ by timestamp)."""
    existing = fetch(f"refs/heads/{branch}", "refs/promotion/existing")
    parents = git("rev-list", "--parents", "-n", "1", existing).decode().split()[1:]
    planned_parents = git("rev-list", "--parents", "-n", "1", planned).decode().split()[1:]
    tree = git("rev-parse", f"{existing}^{{tree}}").decode().strip()
    return parents == planned_parents and tree == git("rev-parse", f"{planned}^{{tree}}").decode().strip()


def pull_request_link(repo: str, branch: str, title: str, text: str) -> str:
    query = urllib.parse.urlencode({"quick_pull": "1", "title": title, "body": text})
    return f"https://github.com/{repo}/compare/{PRODUCTION}...{urllib.parse.quote(branch)}?{query}"


def main() -> None:
    source = os.environ["SOURCE_SHA"]
    digest = os.environ["IMAGE_DIGEST"]
    repo = os.environ["GITHUB_REPOSITORY"]
    base = fetch(f"refs/heads/{PRODUCTION}", "refs/promotion/production")
    main_tip = fetch("refs/heads/main", "refs/promotion/main")
    p = plan(source, digest, base, main_tip, image_revision)
    if p is None:
        print(f"{PRODUCTION} already pins {digest}; nothing to promote.")
        return

    branch = f"{BRANCH_PREFIX}{source[:12]}"
    open_prs = json.loads(
        gh("pr", "list", "--repo", repo, "--base", PRODUCTION, "--state", "open", "--json", "number,headRefName")
    )
    if any(pr["headRefName"] == branch for pr in open_prs):
        print(f"A promotion PR from {branch} is already open.")
        return
    superseded = [f"#{pr['number']}" for pr in open_prs if pr["headRefName"].startswith(BRANCH_PREFIX)]

    planned = commit(p, source, digest)
    if remote_branch(branch) is None:
        push_new_branch(planned, branch)
    else:
        require(
            same_change(branch, planned),
            f"{branch} exists but no longer matches {PRODUCTION}; delete the branch and rerun this job",
        )

    title = f"chore(deploy): promote {source[:12]} to production"
    link = pull_request_link(repo, branch, title, body(p, source, digest, repo, superseded))
    # The PR is opened by a person (GitHub Actions may not create pull requests here).
    print("### Production promotion ready")
    print()
    print(f"`{p.deployed_source[:12]}` -> `{source[:12]}` (`{digest}`) on branch `{branch}`.")
    print()
    print(f"**[Create the promotion pull request]({link})** (prefilled; review, then create).")


if __name__ == "__main__":
    main()
