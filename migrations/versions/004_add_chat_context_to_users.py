"""Add chat context columns to users.

Revision ID: 004
Revises: 003
Create Date: 2026-03-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_chat_response_id", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_chat_activity", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_chat_activity")
    op.drop_column("users", "last_chat_response_id")
