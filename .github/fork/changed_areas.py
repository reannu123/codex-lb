#!/usr/bin/env python3
"""Decide which fork CI groups run for an event (fork-owned; no upstream counterpart).

Pull requests compare the base and head SHAs, pushes compare ``before`` and
``after`` (with rename detection off, so a moved file selects the groups of
both its old and new paths), and ``workflow_dispatch`` runs every group. A change to the fork CI
itself runs every group except ``image``: the image group builds and scans
the container and is triggered only by image inputs, so a CI-only change is
not blocked by base-image or lockfile advisories it did not introduce.
"""

from __future__ import annotations

import json
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path

FORK_CI = [".github/workflows/fork-ci.yml", ".github/fork/**", "Makefile"]

AREAS: dict[str, list[str]] = {
    "backend": [
        "app/**",
        "tests/**",
        "config/**",
        "scripts/**",
        "pyproject.toml",
        "uv.lock",
        "docs/reference/settings.md",
        ".env.example",
        "openspec/**",
        *FORK_CI,
    ],
    "frontend": ["frontend/**", *FORK_CI],
    # Mirrors upstream's Rust area: Rust sources plus the Python seams the
    # native egress wire probes exercise, and the files that build the binary.
    "rust": [
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "deny.toml",
        "crates/**",
        "app/core/clients/codex.py",
        "app/core/clients/http.py",
        "app/core/clients/native_egress.py",
        "app/core/clients/usage.py",
        "app/core/clients/stream_errors.py",
        "app/core/clients/proxy.py",
        "app/core/clients/proxy_websocket.py",
        "app/core/config/settings.py",
        "app/core/openai/**",
        "app/core/upstream_proxy/**",
        "app/core/utils/proxy_env.py",
        # The wire probes install the Python environment from these.
        "pyproject.toml",
        "uv.lock",
        "tests/unit/test_native_egress.py",
        "tests/unit/test_usage_client.py",
        "tests/unit/test_native_egress_packaging.py",
        "tests/unit/test_native_sse_fixtures.py",
        "tests/integration/test_native_routed_egress.py",
        "tests/integration/test_native_sse_egress.py",
        "tests/integration/test_native_usage_egress.py",
        "Dockerfile",
        "Dockerfile.*",
        *FORK_CI,
    ],
    "image": [
        "Dockerfile",
        "Dockerfile.*",
        ".dockerignore",
        "pyproject.toml",
        "uv.lock",
        "frontend/package.json",
        "frontend/bun.lock",
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
    ],
}


def _changed_files(base: str, head: str) -> list[str]:
    subprocess.run(["git", "fetch", "--no-tags", "--depth=200", "origin", base], check=False, capture_output=True)
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"], check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> None:
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if event_name == "workflow_dispatch":
        selected = dict.fromkeys(AREAS, True)
        files: list[str] = []
    else:
        if event_name == "pull_request":
            base, head = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
        else:
            base, head = event["before"], event["after"]
        files = _changed_files(base, head) if set(base) != {"0"} else []
        if not files and set(base) == {"0"}:
            selected = {area: area != "image" for area in AREAS}
        else:
            selected = {area: any(fnmatch(f, p) for f in files for p in patterns) for area, patterns in AREAS.items()}
    print(f"changed files: {len(files)}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        for area, value in selected.items():
            print(f"{area}={'true' if value else 'false'}")
            output.write(f"{area}={'true' if value else 'false'}\n")


if __name__ == "__main__":
    main()
