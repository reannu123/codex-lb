"""Regression tests for deploy/backup.sh, restore.sh and rehearse-migration.sh.

The scripts run against a synthetic SQLite store in a temp dir, with a fake
``docker`` that records calls and models one container's running state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

FAKE_DOCKER = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    state_path = os.environ["FAKE_DOCKER_STATE"]
    state = json.load(open(state_path))
    args = sys.argv[1:]
    state["calls"].append(args)
    containers = state["containers"]

    def save(code=0):
        json.dump(state, open(state_path, "w"))
        sys.exit(code)

    if args[0] == "inspect":
        fmt, name = args[2], args[3]
        container = containers.get(name)
        if container is None:
            save(1)
        if fmt == "{{.State.Running}}":
            print("true" if container["running"] else "false")
        elif fmt == "{{.Config.Image}}":
            print(container["image"])
        else:
            print("/" + name + " " + "".join(source + " " for source in container["mounts"]))
    elif args[0] == "ps":
        print("\\n".join(name for name, c in containers.items() if c["running"]))
    elif args[0] in ("stop", "start"):
        containers[args[-1]]["running"] = args[0] == "start"
    elif args[0] == "run":
        save(int(os.environ.get("FAKE_DOCKER_RUN_EXIT", "0")))
    save()
    """
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    data.mkdir()
    backups.mkdir()
    connection = sqlite3.connect(data / "store.db")
    connection.executescript(
        """
        CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('20260918_020000_model_price_overrides');
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT);
        CREATE INDEX idx_accounts_email ON accounts (email);
        """
    )
    connection.executemany("INSERT INTO accounts (email) VALUES (?)", [(f"u{i}@example.test",) for i in range(300)])
    connection.commit()
    connection.close()
    (data / "encryption.key").write_text("k" * 44)
    (data / "encryption.key").chmod(0o600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    state = tmp_path / "docker.json"
    image = "ghcr.io/reannu123/codex-lb@sha256:" + "a" * 64
    containers = {"codex-lb": {"running": True, "image": image, "mounts": [str(data)]}}
    state.write_text(json.dumps({"calls": [], "containers": containers}))
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_STATE": str(state),
        "CODEX_LB_DATA_DIR": str(data),
        "CODEX_LB_BACKUP_ROOT": str(backups),
    }


def run(script: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DEPLOY / script), *args], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )


def docker_state(env: dict[str, str]) -> dict:
    return json.loads(Path(env["FAKE_DOCKER_STATE"]).read_text())


def backups(env: dict[str, str]) -> list[str]:
    return sorted(p.name for p in Path(env["CODEX_LB_BACKUP_ROOT"]).iterdir() if not p.name.startswith("."))


def test_backup_stops_verifies_and_restarts(env: dict[str, str]) -> None:
    result = run("backup.sh", env, "--label", "pre-deploy")
    assert result.returncode == 0, result.stderr
    name = result.stdout.strip()
    assert name.startswith("pre-deploy-") and backups(env) == [name]
    backup = Path(env["CODEX_LB_BACKUP_ROOT"]) / name

    calls = [call[0] for call in docker_state(env)["calls"]]
    assert calls.index("stop") < calls.index("start")
    assert docker_state(env)["containers"]["codex-lb"]["running"] is True

    manifest = json.loads((backup / "manifest.json").read_text())
    assert manifest["integrity"] == ["ok"]
    assert manifest["schema"] == ["20260918_020000_model_price_overrides"]
    assert manifest["counts"] == {"accounts": 300, "alembic_version": 1}
    assert manifest["image"].endswith("a" * 64)
    # SHA256SUMS holds bare names, so it verifies from inside the directory.
    sums = (backup / "SHA256SUMS").read_text()
    assert "store.db" in sums and "encryption.key" in sums and "/" not in sums
    subprocess.run(["sha256sum", "--strict", "-c", "SHA256SUMS"], cwd=backup, check=True, capture_output=True)
    assert (backup / "encryption.key").stat().st_mode & 0o777 == 0o600


def test_backup_can_leave_the_app_stopped(env: dict[str, str]) -> None:
    result = run("backup.sh", env, "--leave-stopped")
    assert result.returncode == 0, result.stderr
    assert docker_state(env)["containers"]["codex-lb"]["running"] is False


def test_corrupt_store_fails_loudly_and_restarts(env: dict[str, str]) -> None:
    store = Path(env["CODEX_LB_DATA_DIR"]) / "store.db"
    raw = bytearray(store.read_bytes())
    raw[4096 : 4096 + 12] = b"\xff" * 12  # page 2 b-tree header
    store.write_bytes(bytes(raw))

    result = run("backup.sh", env)
    assert result.returncode != 0
    assert "BACKUP FAILED" in result.stderr
    assert all(name.endswith(".failed") for name in backups(env))
    assert docker_state(env)["containers"]["codex-lb"]["running"] is True


def test_missing_key_fails(env: dict[str, str]) -> None:
    (Path(env["CODEX_LB_DATA_DIR"]) / "encryption.key").unlink()
    result = run("backup.sh", env)
    assert result.returncode != 0 and "encryption.key not found" in result.stderr


def test_backup_refuses_while_another_container_mounts_the_data(env: dict[str, str]) -> None:
    state = docker_state(env)
    state["containers"]["portainer-copy"] = {"running": True, "image": "x", "mounts": [env["CODEX_LB_DATA_DIR"]]}
    Path(env["FAKE_DOCKER_STATE"]).write_text(json.dumps(state))
    result = run("backup.sh", env)
    assert result.returncode != 0
    assert "portainer-copy still mounts" in result.stderr
    assert not any(not name.endswith(".failed") for name in backups(env))


def test_restore_replaces_store_and_leaves_app_stopped(env: dict[str, str]) -> None:
    name = run("backup.sh", env).stdout.strip()
    data = Path(env["CODEX_LB_DATA_DIR"])
    with sqlite3.connect(data / "store.db") as connection:
        connection.execute("DELETE FROM accounts")
    (data / "store.db-shm").write_bytes(b"stale")
    (data / "store.db-wal").write_bytes(b"stale")

    assert run("restore.sh", env, name).returncode != 0  # no --yes on a non-tty
    result = run("restore.sh", env, name, "--yes")
    assert result.returncode == 0, result.stderr

    assert not (data / "store.db-shm").exists() and not (data / "store.db-wal").exists()
    with sqlite3.connect(f"file:{data / 'store.db'}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone() == (300,)
    assert docker_state(env)["containers"]["codex-lb"]["running"] is False
    aside = [n for n in backups(env) if n.startswith("pre-restore-")]
    assert len(aside) == 1
    assert (Path(env["CODEX_LB_BACKUP_ROOT"]) / aside[0] / "store.db-wal").read_bytes() == b"stale"


def test_restore_rejects_a_tampered_backup_before_touching_data(env: dict[str, str]) -> None:
    name = run("backup.sh", env).stdout.strip()
    (Path(env["CODEX_LB_BACKUP_ROOT"]) / name / "encryption.key").write_text("x" * 44)
    before = (Path(env["CODEX_LB_DATA_DIR"]) / "store.db").read_bytes()
    result = run("restore.sh", env, name, "--yes")
    assert result.returncode != 0 and "checksum mismatch" in result.stderr
    assert (Path(env["CODEX_LB_DATA_DIR"]) / "store.db").read_bytes() == before
    assert docker_state(env)["containers"]["codex-lb"]["running"] is True


@pytest.mark.parametrize("name", ["../etc", ".lock", "x.failed", "missing"])
def test_restore_rejects_bad_names(env: dict[str, str], name: str) -> None:
    result = run("restore.sh", env, name, "--yes")
    assert result.returncode != 0 and "RESTORE FAILED" in result.stderr


def test_rehearsal_is_isolated_and_cleans_up(env: dict[str, str]) -> None:
    run("backup.sh", env, "--label", "older")
    newest = run("backup.sh", env, "--label", "newer").stdout.strip()
    image = "ghcr.io/reannu123/codex-lb@sha256:" + "b" * 64
    result = run("rehearse-migration.sh", env, image)
    assert result.returncode == 0, result.stderr
    assert f"{newest}:" in result.stderr and "REHEARSAL OK" in result.stderr

    runs = [call for call in docker_state(env)["calls"] if call[0] == "run"]
    assert [call[-1] for call in runs] == ["current", "upgrade", "current", "check"]
    for call in runs:
        assert {"--network", "none"} <= set(call) and call[call.index("--network") + 1] == "none"
        assert "--read-only" in call and "--rm" in call and image in call
        mount = call[call.index("-v") + 1]
        assert mount.startswith(env["CODEX_LB_BACKUP_ROOT"] + "/.rehearsal.")
        assert env["CODEX_LB_DATA_DIR"] not in mount
    assert not list(Path(env["CODEX_LB_BACKUP_ROOT"]).glob(".rehearsal.*"))
    # The production container is never stopped or started by a rehearsal.
    assert docker_state(env)["containers"]["codex-lb"]["running"] is True


def test_failed_rehearsal_fails_loudly_and_cleans_up(env: dict[str, str]) -> None:
    run("backup.sh", env)
    result = run("rehearse-migration.sh", {**env, "FAKE_DOCKER_RUN_EXIT": "1"}, "img@sha256:" + "c" * 64)
    assert result.returncode != 0 and "REHEARSAL FAILED" in result.stderr
    assert not list(Path(env["CODEX_LB_BACKUP_ROOT"]).glob(".rehearsal.*"))
