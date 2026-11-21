"""Regression tests for the fork-owned CI helpers under .github/fork/."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github" / "fork" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retirement = _load("check_workflow_retirement")
areas = _load("changed_areas")
G = retirement.GUARD


@pytest.mark.parametrize(
    "condition",
    [
        G,
        f"{G} && (always())",
        f"${{{{ {G} && (a && (b || c)) }}}}",
        f"{G} && (contains(github.event.pull_request.title, '('))",
        f"{G} && (contains(github.event.pull_request.title, ')'))",
        f"{G} && (github.head_ref == 'it''s (fine)')",
        f"{G} &&\n  (github.event_name != 'workflow_run' ||\n  github.event.workflow_run.conclusion == 'success')",
    ],
)
def test_upstream_only_guard_forms_are_accepted(condition: str) -> None:
    assert retirement._is_upstream_only(condition) is True


@pytest.mark.parametrize(
    "condition",
    [
        "",
        f"{G} || github.event_name == 'push'",
        f"{G} && a || b",
        f"{G} && (a) || (b)",
        f"x && {G}",
        f"{G} && a",
        # A quoted '(' must not keep the group open across the real ')'.
        f"{G} && (contains(x, '(')) || github.event_name == 'push'",
        f"{G} && (a == ')' ) || b",
        f"{G} && (a == 'unterminated)",
        f"{G} && ((a)",
    ],
)
def test_conditions_that_may_run_on_the_fork_are_rejected(condition: str) -> None:
    assert retirement._is_upstream_only(condition) is False


def test_dependent_jobs_inherit_retirement_unless_they_opt_back_in() -> None:
    jobs = {
        "root": {"if": G},
        "child": {"needs": "root"},
        "always_child": {"needs": ["root"], "if": "always()"},
        "guarded_always": {"needs": ["root"], "if": f"{G} && (always())"},
    }
    memo: dict[str, bool] = {}
    assert retirement._retired("child", jobs, memo) is True
    assert retirement._retired("always_child", jobs, memo) is False
    assert retirement._retired("guarded_always", jobs, memo) is True


def test_repository_workflows_pass_the_retirement_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    assert retirement.main() == 0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_changed_paths_are_raw_and_renames_select_both_sides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "ci")
    (repo / "app").mkdir()
    (repo / "app" / "café.py").write_text("x = 1\n")
    (repo / "app" / "moved.py").write_text("y = 2\n" * 20)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "app" / "café.py").write_text("x = 2\n")
    (repo / "notes").mkdir()
    _git(repo, "mv", "app/moved.py", "notes/moved.py")
    _git(repo, "commit", "-qam", "change")
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    files = areas._changed_files(base, head)
    assert "app/café.py" in files
    assert "app/moved.py" in files and "notes/moved.py" in files

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}))
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    areas.main()
    selected = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert selected == {"backend": "true", "frontend": "false", "rust": "false", "image": "false"}


def test_every_focused_integration_target_exists() -> None:
    listing = ROOT / ".github" / "fork" / "focused-integration-tests.txt"
    targets = [line.strip() for line in listing.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert targets
    missing = [target for target in targets if not (ROOT / target).is_file()]
    assert missing == []


def _fork_image_workflow() -> dict:
    import yaml

    return yaml.safe_load((ROOT / ".github" / "workflows" / "fork-image.yml").read_text())


def test_fork_image_publishes_only_for_this_repository_by_immutable_id() -> None:
    workflow = _fork_image_workflow()
    condition = " ".join(str(workflow["jobs"]["resolve"]["if"]).split())
    # The fork's immutable repository ID survives renames (codex-lb -> switchboard).
    assert condition.startswith("github.repository_id == '1464401554' && (")
    assert "github.repository ==" not in condition
    assert workflow["jobs"]["publish"]["if"] == "needs.resolve.outputs.qualified == 'true'"


def test_fork_image_package_name_is_fixed_not_derived_from_repository() -> None:
    workflow = _fork_image_workflow()
    steps = {step.get("name"): step for step in workflow["jobs"]["publish"]["steps"]}
    resolve = steps["Resolve image name"]
    assert resolve["run"].strip() == 'echo "name=ghcr.io/reannu123/codex-lb" >> "$GITHUB_OUTPUT"'
    assert "env" not in resolve
    text = (ROOT / ".github" / "workflows" / "fork-image.yml").read_text()
    assert "${REPO,,}" not in text
    assert ":latest" not in text


def test_fork_image_permissions_are_not_broadened() -> None:
    workflow = _fork_image_workflow()
    assert workflow["permissions"] == {}
    assert workflow["jobs"]["resolve"]["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["jobs"]["publish"]["permissions"] == {"contents": "read", "packages": "write"}
