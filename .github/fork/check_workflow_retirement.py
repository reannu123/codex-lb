#!/usr/bin/env python3
"""Fail if an upstream workflow job would run on the fork without being kept on purpose.

Upstream workflows are retired on the fork by guarding their root jobs with
``github.repository == 'Soju06/codex-lb'`` (the pattern upstream already uses),
so imports from upstream stay conflict-light. A job counts as retired when its
``if`` carries that guard, or when it only runs after retired jobs and does
not opt back in with ``always()``. New upstream workflows or jobs therefore
fail this check until they are guarded or added to ``KEPT`` below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

GUARD = "github.repository == 'Soju06/codex-lb'"
# Upstream jobs the fork deliberately keeps running.
KEPT: dict[str, set[str]] = {
    "simplicity-budgets.yml": {"budgets"},
    "docs.yml": {"build"},
}


def _retired(name: str, jobs: dict, memo: dict[str, bool]) -> bool:
    if name in memo:
        return memo[name]
    job = jobs[name]
    condition = str(job.get("if", ""))
    needs = job.get("needs") or []
    needs = [needs] if isinstance(needs, str) else list(needs)
    if GUARD in condition:
        result = True
    elif needs and "always()" not in condition and "failure()" not in condition:
        result = all(_retired(need, jobs, memo) for need in needs)
    else:
        result = False
    memo[name] = result
    return result


def main() -> int:
    problems: list[str] = []
    for path in sorted(Path(".github/workflows").glob("*.y*ml")):
        if path.name.startswith("fork-"):
            continue
        jobs = (yaml.safe_load(path.read_text()) or {}).get("jobs", {})
        kept = KEPT.get(path.name, set())
        memo: dict[str, bool] = {}
        for name in jobs:
            if name in kept:
                continue
            if not _retired(name, jobs, memo):
                problems.append(f"{path.name}: job '{name}' would run on the fork (add the guard or list it in KEPT)")
    for problem in problems:
        print(f"::error::{problem}")
    if not problems:
        print("all upstream workflow jobs are retired on the fork or explicitly kept")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
