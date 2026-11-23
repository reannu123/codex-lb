"""Regression tests for deploy/promote-production.py and its Fork image job."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
D1, D2, D3 = ("sha256:" + c * 64 for c in "123")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("promote_production", ROOT / "deploy" / "promote-production.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


promote = _load()


def compose(digest: str) -> str:
    return (
        "# production\nservices:\n  codex-lb:\n"
        f"    image: ghcr.io/reannu123/codex-lb@{digest}\n"
        "    container_name: codex-lb\n"
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """main: c1 - c2 - c3 (+ off-main side commit); deploy/production pins D1 (built from c1)."""
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "origin.git")], check=True)
    monkeypatch.chdir(work)
    for key, value in {"user.name": "t", "user.email": "t@example.test", "commit.gpgsign": "false"}.items():
        git("config", key, value)
    git("remote", "add", "origin", str(tmp_path / "origin.git"))
    shas = {}
    for name in ("c1", "c2", "c3"):
        git("commit", "-q", "--allow-empty", "-m", name)
        shas[name] = git("rev-parse", "HEAD")
    git("switch", "-q", "-c", "side", shas["c1"])
    git("commit", "-q", "--allow-empty", "-m", "side")
    shas["side"] = git("rev-parse", "HEAD")
    git("switch", "-q", "--orphan", "deploy/production")
    (work / "deploy" / "portainer").mkdir(parents=True)
    (work / promote.COMPOSE).write_text(compose(D1))
    (work / "README.md").write_text("bot-managed\n")
    git("add", ".")
    git("commit", "-q", "-m", "production baseline")
    shas["base"] = git("rev-parse", "HEAD")
    git("push", "-q", "origin", "main", "deploy/production")
    return shas


def labels(shas: dict[str, str], extra: dict[str, str] | None = None):
    mapping = {D1: shas["c1"], D2: shas["c3"], **(extra or {})}
    return lambda digest: mapping[digest]


def test_plan_bumps_only_the_digest(repo: dict[str, str]) -> None:
    p = promote.plan(repo["c3"], D2, repo["base"], repo["c3"], labels(repo))
    assert p.deployed_digest == D1 and p.deployed_source == repo["c1"]
    assert p.compose.decode() == compose(D2)

    commit = promote.commit(p, repo["c3"], D2)
    assert git("rev-parse", f"{commit}^") == repo["base"]
    assert git("diff", "--name-only", repo["base"], commit) == promote.COMPOSE
    changed = [
        line
        for line in git("diff", "-U0", repo["base"], commit).splitlines()
        if line[:1] in "+-" and line[:3] not in ("+++", "---")
    ]
    assert changed == [f"-    image: ghcr.io/reannu123/codex-lb@{D1}", f"+    image: ghcr.io/reannu123/codex-lb@{D2}"]
    message = git("log", "-1", "--format=%B", commit)
    assert f"Source: {repo['c3']}" in message and f"Digest: {D2}" in message


def test_already_pinned_digest_is_a_no_op(repo: dict[str, str]) -> None:
    assert promote.plan(repo["c1"], D1, repo["base"], repo["c3"], labels(repo)) is None


@pytest.mark.parametrize(
    ("source", "digest", "extra", "reason"),
    [
        ("c2", D2, None, "was not built from"),  # D2's label says c3
        ("side", D3, {D3: "side"}, "is not on main"),
        ("c1", D3, {D3: "c1"}, "already deployed under another digest"),
    ],
)
def test_refusals(repo: dict[str, str], source: str, digest: str, extra: dict[str, str] | None, reason: str) -> None:
    extra = {k: repo[v] for k, v in (extra or {}).items()}
    with pytest.raises(SystemExit, match=reason):
        promote.plan(repo[source], digest, repo["base"], repo["c3"], labels(repo, extra))


def test_refuses_a_commit_that_does_not_descend_from_the_deployed_one(repo: dict[str, str]) -> None:
    # Production runs c3 (D2); proposing the older c2 would be a rollback.
    p = promote.plan(repo["c3"], D2, repo["base"], repo["c3"], labels(repo))
    rolled = promote.commit(p, repo["c3"], D2)
    with pytest.raises(SystemExit, match="does not descend from the deployed commit"):
        promote.plan(repo["c2"], D3, rolled, repo["c3"], labels(repo, {D3: repo["c2"]}))


def test_refuses_an_ambiguous_compose_file(repo: dict[str, str]) -> None:
    second = f"  other:\n    image: ghcr.io/reannu123/codex-lb@{D1}\n"
    (Path.cwd() / promote.COMPOSE).write_text(compose(D1) + second)
    git("commit", "-qam", "two images")
    with pytest.raises(SystemExit, match="exactly one pinned image line"):
        promote.plan(repo["c3"], D2, "HEAD", repo["c3"], labels(repo))


@pytest.mark.parametrize(("source", "digest"), [("abc", D2), ("c3", "sha256:xyz"), ("c3", "latest")])
def test_rejects_malformed_inputs(repo: dict[str, str], source: str, digest: str) -> None:
    with pytest.raises(SystemExit):
        promote.plan(repo.get(source, source), digest, repo["base"], repo["c3"], labels(repo))


def test_push_only_creates_a_new_promotion_branch(repo: dict[str, str]) -> None:
    p = promote.plan(repo["c3"], D2, repo["base"], repo["c3"], labels(repo))
    commit = promote.commit(p, repo["c3"], D2)
    promote.push_new_branch(commit, "promote/production-abc")
    assert git("ls-remote", "origin", "refs/heads/promote/production-abc").split()[0] == commit
    # deploy/production itself is untouched.
    assert git("ls-remote", "origin", "refs/heads/deploy/production").split()[0] == repo["base"]
    # An existing branch is never updated.
    other = promote.commit(p, repo["c2"], D2)
    with pytest.raises(subprocess.CalledProcessError):
        promote.push_new_branch(other, "promote/production-abc")
    assert git("ls-remote", "origin", "refs/heads/promote/production-abc").split()[0] == commit


def test_workflow_job_only_proposes() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "fork-image.yml").read_text())
    job = workflow["jobs"]["promote-production"]
    assert job["needs"] == ["resolve", "publish"]
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert workflow["jobs"]["publish"]["outputs"]["digest"] == "${{ steps.push.outputs.digest }}"
    text = yaml.safe_dump(job) + (ROOT / "deploy" / "promote-production.py").read_text()
    assert '"merge"' not in text and "--auto" not in text
    assert "refs/heads/deploy/production" not in text.split("def push_new_branch")[1]
