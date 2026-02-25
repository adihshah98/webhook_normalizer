"""extend event_id to 256 for provider-scoped keys

Revision ID: 003
Revises: 002
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "events",
        "event_id",
        type_=sa.String(256),
        existing_type=sa.String(64),
    )


def downgrade() -> None:
    op.alter_column(
        "events",
        "event_id",
        type_=sa.String(64),
        existing_type=sa.String(256),
    )
