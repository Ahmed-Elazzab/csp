"""Widen spare_parts.part_number from VARCHAR(100) to TEXT.

Revision ID: 002
Revises: 001
Create Date: 2024-01-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "spare_parts",
        "part_number",
        existing_type=sa.String(100),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Note: this will fail if any part_number exceeds 100 chars
    op.alter_column(
        "spare_parts",
        "part_number",
        existing_type=sa.Text(),
        type_=sa.String(100),
        existing_nullable=False,
    )
