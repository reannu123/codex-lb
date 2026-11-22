#!/usr/bin/env python3
"""Offline verification of a codex-lb SQLite backup (stdlib only; runs on the host).

``snapshot DIR`` copies DIR's store.db (and -wal, if present) to a scratch
directory next to DIR, so the verified files are never opened, runs a full
``PRAGMA integrity_check``, reads the Alembic revision and counts every table.
It prints a JSON manifest and exits non-zero unless the copy is sound and
DIR/encryption.key is non-empty. ``--in-place`` inspects DIR directly (for a
throwaway copy). ``check DIR`` re-snapshots DIR and requires the result to match
DIR/manifest.json. ``--meta KEY=VALUE`` adds provenance fields to the output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

DB = "store.db"
KEY = "encryption.key"
SIDECARS = ("store.db-wal",)


class Snapshot(TypedDict):
    integrity: list[str]
    schema: list[str] | None
    counts: dict[str, int]


def fail(message: str) -> None:
    print(f"VERIFY FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def inspect_db(path: Path) -> Snapshot:
    connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema = None
        if "alembic_version" in tables:
            schema = sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        connection.close()
    return Snapshot(integrity=integrity, schema=schema, counts=counts)


def snapshot(directory: Path, in_place: bool) -> Snapshot:
    if not (directory / DB).is_file():
        fail(f"{directory / DB} is missing")
    key = directory / KEY
    if not key.is_file() or key.stat().st_size == 0:
        fail(f"{key} is missing or empty")
    if in_place:
        result = inspect_db(directory / DB)
    else:
        with tempfile.TemporaryDirectory(prefix=".verify-", dir=directory.parent) as scratch:
            for name in (DB, *SIDECARS):
                if (directory / name).exists():
                    shutil.copyfile(directory / name, Path(scratch) / name)
            result = inspect_db(Path(scratch) / DB)
    if result["integrity"] != ["ok"]:
        fail(f"integrity_check: {result['integrity'][:5]}")
    if not result["schema"]:
        fail("no Alembic revision recorded (alembic_version is missing or empty)")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "check"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE", help="Extra manifest field.")
    args = parser.parse_args()
    result: dict[str, object] = dict(snapshot(args.directory, args.in_place))
    for item in args.meta:
        key, separator, value = item.partition("=")
        if not separator or key in result:
            fail(f"bad --meta {item!r}")
        result[key] = value
    if args.command == "check":
        manifest = json.loads((args.directory / "manifest.json").read_text())
        for field in ("integrity", "schema", "counts"):
            if manifest.get(field) != result[field]:
                fail(f"{field} differs from manifest.json: {manifest.get(field)!r} != {result[field]!r}")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
