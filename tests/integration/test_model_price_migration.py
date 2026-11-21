from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from app.db.migrate import _build_alembic_config, check_schema_drift, run_upgrade

pytestmark = pytest.mark.integration


def test_sqlite_model_price_migration_preserves_preexisting_costs_on_upgrade_and_rollback(tmp_path):
    db = tmp_path / "model-prices.db"
    url = f"sqlite+aiosqlite:///{db}"
    previous = "20260918_000000_merge_scim_and_overflow_heads"
    new = "20260918_020000_model_price_overrides"
    config = _build_alembic_config(url)
    assert ScriptDirectory.from_config(config).get_heads() == [new]
    run_upgrade(url, previous, bootstrap_legacy=False)
    previous_costs = [("missing", None), ("zero", 0.0), ("recorded", 0.125)]
    with sqlite3.connect(db) as connection:
        connection.executemany(
            "INSERT INTO request_logs (request_id, model, status, cost_usd) VALUES (?, 'gpt-6.2-sol', 'success', ?)",
            previous_costs,
        )
    run_upgrade(url, "head", bootstrap_legacy=False)
    assert check_schema_drift(url) == ()
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT request_id, cost_usd FROM request_logs ORDER BY id").fetchall() == previous_costs
        )
        assert connection.execute("SELECT DISTINCT cost_status FROM request_logs").fetchall() == [(None,)]
        connection.execute("INSERT INTO model_price_overrides VALUES ('gpt-6.2-sol', 2, 0, 8)")
    command.downgrade(config, previous)
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT request_id, cost_usd FROM request_logs ORDER BY id").fetchall() == previous_costs
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (previous,)
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name = 'model_price_overrides'").fetchone() is None
        )
        assert "cost_status" not in {column[1] for column in connection.execute("PRAGMA table_info(request_logs)")}
