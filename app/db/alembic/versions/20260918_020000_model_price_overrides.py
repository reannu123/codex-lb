"""Persist exact model-price overrides and recorded request cost details.

Both steps are idempotent: the legacy-history bootstrap can create the current
schema from metadata before replaying revisions, so the table or columns may
already exist.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260918_020000_model_price_overrides"
down_revision = "20260918_000000_merge_scim_and_overflow_heads"
branch_labels = None
depends_on = None

_OVERRIDES = "model_price_overrides"
_REQUEST_LOGS = "request_logs"
_COST_COLUMNS = ("cost_status", "cost_input_usd", "cost_cached_input_usd", "cost_output_usd")


def _existing_columns(inspector: sa.Inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_OVERRIDES):
        op.create_table(
            _OVERRIDES,
            sa.Column("model_id", sa.String(256), primary_key=True),
            sa.Column("input_per_1m", sa.Float(), nullable=False),
            sa.Column("cached_input_per_1m", sa.Float(), nullable=False),
            sa.Column("output_per_1m", sa.Float(), nullable=False),
        )
    existing = _existing_columns(inspector, _REQUEST_LOGS)
    for column in _COST_COLUMNS:
        if column in existing:
            continue
        column_type = sa.String(20) if column == "cost_status" else sa.Float()
        op.add_column(_REQUEST_LOGS, sa.Column(column, column_type, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = _existing_columns(inspector, _REQUEST_LOGS)
    for column in reversed(_COST_COLUMNS):
        if column in existing:
            op.drop_column(_REQUEST_LOGS, column)
    if inspector.has_table(_OVERRIDES):
        op.drop_table(_OVERRIDES)
