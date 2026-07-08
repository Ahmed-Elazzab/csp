"""Initial schema – creates all tables.

Revision ID: 001
Revises: 
Create Date: 2024-01-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attribute_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("impact", sa.String(50), nullable=True),
        sa.Column("reasons", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(50), nullable=True),
        sa.Column("sample_values", sa.Text(), nullable=True),
        sa.Column("attribute_source", sa.String(255), nullable=True),
        sa.Column("currently_exists", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "questionnaire_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario", sa.String(100), nullable=False),
        sa.Column("question_id", sa.String(10), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario", "question_id"),
    )

    op.create_table(
        "spare_parts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.Text(), nullable=False),
        sa.Column("part_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model_number", sa.String(255), nullable=True),
        sa.Column("part_type", sa.String(100), nullable=True),
        sa.Column("technical_specs", sa.Text(), nullable=True),
        sa.Column("country_of_origin", sa.String(100), nullable=True),
        sa.Column("oem_only", sa.Boolean(), nullable=True),
        sa.Column("substitute_available", sa.Boolean(), nullable=True),
        sa.Column("obsolescence_risk", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("part_number"),
    )
    op.create_index("ix_spare_parts_part_number", "spare_parts", ["part_number"])

    op.create_table(
        "part_attributes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("attribute_name", sa.String(255), nullable=False),
        sa.Column("attribute_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source_tier", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["part_id"], ["spare_parts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("part_id", "attribute_name"),
    )

    op.create_table(
        "research_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(100), nullable=True),
        sa.Column("reliability_tier", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("extracted_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["part_id"], ["spare_parts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("operations_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("supply_chain_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("inventory_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("override_label", sa.String(50), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("key_reasons", sa.Text(), nullable=True),
        sa.Column("override_rules_triggered", sa.Text(), nullable=True),
        sa.Column("missing_attributes", sa.Text(), nullable=True),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("assessment_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["part_id"], ["spare_parts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "questionnaire_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("question_db_id", sa.Integer(), nullable=False),
        sa.Column("answer_value", sa.Text(), nullable=True),
        sa.Column("answer_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("answered_by", sa.String(50), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"]),
        sa.ForeignKeyConstraint(["question_db_id"], ["questionnaire_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("questionnaire_answers")
    op.drop_table("assessments")
    op.drop_table("research_sources")
    op.drop_table("part_attributes")
    op.drop_index("ix_spare_parts_part_number", table_name="spare_parts")
    op.drop_table("spare_parts")
    op.drop_table("questionnaire_questions")
    op.drop_table("attribute_definitions")
