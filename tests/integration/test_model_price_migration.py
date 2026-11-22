from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from app.db.migrate import _build_alembic_config, check_schema_drift, run_upgrade
from app.db.migration_url import to_sync_database_url
from app.db.models import Base

pytestmark = pytest.mark.integration

_PREVIOUS = "20260918_000000_merge_scim_and_overflow_heads"
_NEW = "20260918_020000_model_price_overrides"
_COST_COLUMNS = {"cost_status", "cost_input_usd", "cost_cached_input_usd", "cost_output_usd"}
# Synthetic legacy rows: unknown, explicit zero, and a recorded positive estimate.
_LEGACY_COSTS = [("legacy-missing", None), ("legacy-zero", 0.0), ("legacy-recorded", 0.125)]


@pytest.fixture(params=["sqlite", "postgresql"])
def migration_url(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[str]:
    if request.param == "sqlite":
        yield f"sqlite+aiosqlite:///{tmp_path / 'model-prices.db'}"
        return

    configured = os.environ.get("CODEX_LB_TEST_DATABASE_URL", "")
    if not configured.startswith("postgresql"):
        pytest.skip("requires a disposable PostgreSQL CODEX_LB_TEST_DATABASE_URL")
    engine = sa.create_engine(to_sync_database_url(configured))
    try:
        _reset(engine)
        yield configured
    finally:
        try:
            _reset(engine)
        finally:
            engine.dispose()


def _reset(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))


def _costs(engine: sa.Engine) -> list[tuple[str, float | None]]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT request_id, cost_usd FROM request_logs WHERE request_id LIKE 'legacy-%' ORDER BY id")
        )
        return [(row[0], row[1]) for row in rows]


def _schema(engine: sa.Engine) -> tuple[bool, set[str]]:
    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("request_logs")}
    return inspector.has_table("model_price_overrides"), columns & _COST_COLUMNS


def test_model_price_migration_preserves_existing_costs_across_round_trip(migration_url: str) -> None:
    url = migration_url
    config = _build_alembic_config(url)
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_NEW).down_revision == _PREVIOUS
    compare_head_schema = script.get_current_head() == _NEW
    engine = sa.create_engine(to_sync_database_url(url))
    try:
        assert run_upgrade(url, _PREVIOUS, bootstrap_legacy=False).current_revision == _PREVIOUS
        with engine.begin() as connection:
            for request_id, cost in _LEGACY_COSTS:
                connection.execute(
                    sa.text(
                        "INSERT INTO request_logs "
                        "(request_id, requested_at, model, status, input_tokens, output_tokens, cost_usd) "
                        "VALUES (:id, CURRENT_TIMESTAMP, 'gpt-6.2-sol', 'success', 1000, 100, :cost)"
                    ),
                    {"id": request_id, "cost": cost},
                )

        assert run_upgrade(url, _NEW, bootstrap_legacy=False).current_revision == _NEW
        if compare_head_schema:
            assert check_schema_drift(url) == ()
        assert _costs(engine) == _LEGACY_COSTS
        assert _schema(engine) == (True, _COST_COLUMNS)
        with engine.begin() as connection:
            # Legacy rows stay unclassified so only upstream repair may fill them.
            statuses = connection.execute(sa.text("SELECT DISTINCT cost_status FROM request_logs")).all()
            assert [tuple(row) for row in statuses] == [(None,)]
            connection.execute(sa.text("INSERT INTO model_price_overrides VALUES ('gpt-6.2-sol', 2, 0, 8)"))

        command.downgrade(config, _PREVIOUS)
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == _PREVIOUS
        assert _costs(engine) == _LEGACY_COSTS
        assert _schema(engine) == (False, set())

        # The legacy bootstrap can create the table from metadata first.
        with engine.begin() as connection:
            overrides = Base.metadata.tables["model_price_overrides"]
            overrides.create(connection)
            connection.execute(
                overrides.insert().values(
                    model_id="gpt-6.2-sol", input_per_1m=3, cached_input_per_1m=0, output_per_1m=9
                )
            )
        assert run_upgrade(url, _NEW, bootstrap_legacy=False).current_revision == _NEW
        if compare_head_schema:
            assert check_schema_drift(url) == ()
        assert _costs(engine) == _LEGACY_COSTS
        assert _schema(engine) == (True, _COST_COLUMNS)
        with engine.connect() as connection:
            assert connection.execute(sa.select(overrides)).one() == ("gpt-6.2-sol", 3, 0, 9)
    finally:
        engine.dispose()
