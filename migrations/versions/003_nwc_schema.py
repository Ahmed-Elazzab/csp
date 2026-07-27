"""Add NWC 4-dimension fields and NWCDimensionScore table.

Revision ID: 003
Revises: 002
Create Date: 2024-07-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New NWC dimension columns on assessments ───────────────────────────────
    with op.batch_alter_table("assessments") as batch:
        batch.add_column(sa.Column("nwc_operations_option",    sa.String(5),   nullable=True))
        batch.add_column(sa.Column("nwc_operations_score",     sa.Integer(),   nullable=True))
        batch.add_column(sa.Column("nwc_water_quality_option", sa.String(5),   nullable=True))
        batch.add_column(sa.Column("nwc_water_quality_score",  sa.Integer(),   nullable=True))
        batch.add_column(sa.Column("nwc_availability_option",  sa.String(5),   nullable=True))
        batch.add_column(sa.Column("nwc_availability_score",   sa.Integer(),   nullable=True))
        batch.add_column(sa.Column("nwc_safety_option",        sa.String(5),   nullable=True))
        batch.add_column(sa.Column("nwc_safety_score",         sa.Integer(),   nullable=True))
        batch.add_column(sa.Column("nwc_total_score",          sa.Integer(),   nullable=True))
        batch.add_column(sa.Column("nwc_label",                sa.String(50),  nullable=True))
        batch.add_column(sa.Column("nwc_strategic_rules",      sa.Text(),      nullable=True))
        batch.add_column(sa.Column("analysis_json",            sa.Text(),      nullable=True))
        batch.add_column(sa.Column("model_used",               sa.String(150), nullable=True))
        batch.add_column(sa.Column("prompt_version",           sa.String(50),  nullable=True))
        batch.add_column(sa.Column("inference_timestamp",      sa.DateTime(),  nullable=True))
        batch.add_column(sa.Column("analysis_confidence",      sa.Float(),     nullable=True))

    # ── New nwc_dimension_scores table ─────────────────────────────────────────
    op.create_table(
        "nwc_dimension_scores",
        sa.Column("id",            sa.Integer(),   nullable=False),
        sa.Column("assessment_id", sa.Integer(),   nullable=False),
        sa.Column("dimension",     sa.String(50),  nullable=False),
        sa.Column("selected_option", sa.String(5), nullable=False),
        sa.Column("option_label",  sa.Text(),      nullable=True),
        sa.Column("score",         sa.Integer(),   nullable=False),
        sa.Column("confidence",    sa.Float(),     nullable=False),
        sa.Column("reason",        sa.Text(),      nullable=True),
        sa.Column("sources",       sa.Text(),      nullable=True),
        sa.Column("created_at",    sa.DateTime(),  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "dimension"),
    )


def downgrade() -> None:
    op.drop_table("nwc_dimension_scores")
    with op.batch_alter_table("assessments") as batch:
        for col in [
            "nwc_operations_option", "nwc_operations_score",
            "nwc_water_quality_option", "nwc_water_quality_score",
            "nwc_availability_option", "nwc_availability_score",
            "nwc_safety_option", "nwc_safety_score",
            "nwc_total_score", "nwc_label", "nwc_strategic_rules",
            "analysis_json", "model_used", "prompt_version",
            "inference_timestamp", "analysis_confidence",
        ]:
            batch.drop_column(col)
