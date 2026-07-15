"""Add immutable workbook and canonical Model Extraction persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0002"
down_revision: Union[str, None] = "20260715_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workbook_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_type", sa.String(length=32), nullable=False),
        sa.Column("storage_ref", sa.String(length=512), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "storage_type <> 'database' OR content_bytes IS NOT NULL",
            name="ck_workbook_versions_database_has_bytes",
        ),
        sa.CheckConstraint(
            "file_size > 0",
            name="ck_workbook_versions_positive_size",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_workbook_versions_sha_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sha256",
            name="uq_workbook_versions_sha256",
        ),
        sa.UniqueConstraint(
            "storage_type",
            "storage_ref",
            name="uq_workbook_versions_storage_location",
        ),
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("workbook_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("upload_filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("submitted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("stop_reason", sa.String(length=100), nullable=True),
        sa.Column("extraction_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("driver_meta_json", sa.JSON(), nullable=True),
        sa.Column("coverage_json", sa.JSON(), nullable=True),
        sa.Column("validation_summary_json", sa.JSON(), nullable=True),
        sa.Column("time_series_summary_json", sa.JSON(), nullable=True),
        sa.Column("validation_results_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('extracting', 'extracted', 'materialized', "
            "'extraction_failed', 'persistence_failed')",
            name="ck_model_versions_status",
        ),
        sa.CheckConstraint(
            "validation_status IN ('not_run', 'validated', "
            "'validated_with_warning', 'review_required', 'rejected')",
            name="ck_model_versions_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["workbook_version_id"],
            ["workbook_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_versions_status_created",
        "model_versions",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_model_versions_workbook_created",
        "model_versions",
        ["workbook_version_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "model_parameters",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("llm_candidate_alias", sa.String(length=255), nullable=True),
        sa.Column("source_bucket", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=True),
        sa.Column("submitted_role", sa.String(length=64), nullable=False),
        sa.Column("validated_role", sa.String(length=64), nullable=False),
        sa.Column("raw_value_json", sa.JSON(), nullable=True),
        sa.Column("validated_value_json", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("scenario", sa.String(length=100), nullable=True),
        sa.Column("period_json", sa.JSON(), nullable=True),
        sa.Column("source_sheet", sa.String(length=255), nullable=False),
        sa.Column("source_cell", sa.String(length=32), nullable=False),
        sa.Column("exact_formula", sa.Text(), nullable=True),
        sa.Column("formula_status", sa.String(length=64), nullable=False),
        sa.Column("source_validation_status", sa.String(length=32), nullable=False),
        sa.Column("role_validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("data_type", sa.String(length=16), nullable=True),
        sa.Column("number_format", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("validation_confidence", sa.Float(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column("validation_warnings_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind = 'parameter'",
            name="ck_model_parameters_entity_kind",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_version_id",
            "source_sheet",
            "source_cell",
            name="uq_model_parameters_source_cell",
        ),
    )
    op.create_index(
        "ix_model_parameters_model_role",
        "model_parameters",
        ["model_version_id", "validated_role"],
        unique=False,
    )

    op.create_table(
        "financial_series",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("model_version_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("llm_series_alias", sa.String(length=255), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("semantic_role", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=64), nullable=True),
        sa.Column("orientation", sa.String(length=16), nullable=False),
        sa.Column("scenario", sa.String(length=100), nullable=True),
        sa.Column("entity", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=32), nullable=True),
        sa.Column("calculation_type", sa.String(length=32), nullable=False),
        sa.Column("period_source_range", sa.Text(), nullable=False),
        sa.Column("value_source_range", sa.Text(), nullable=False),
        sa.Column("label_source_sheet", sa.String(length=255), nullable=True),
        sa.Column("label_source_cell", sa.String(length=32), nullable=True),
        sa.Column("materialization_status", sa.String(length=32), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=True),
        sa.Column("formula_pattern_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_kind = 'financial_series'",
            name="ck_financial_series_entity_kind",
        ),
        sa.CheckConstraint(
            "semantic_role = 'financial_series'",
            name="ck_financial_series_semantic_role",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_series_model_category",
        "financial_series",
        ["model_version_id", "category"],
        unique=False,
    )
    op.create_index(
        "ix_financial_series_model_id",
        "financial_series",
        ["model_version_id", "id"],
        unique=False,
    )

    op.create_table(
        "financial_series_values",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("financial_series_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("period_index", sa.Integer(), nullable=False),
        sa.Column("raw_period_label_json", sa.JSON(), nullable=True),
        sa.Column("display_period_label", sa.Text(), nullable=True),
        sa.Column("period_type", sa.String(length=32), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("quarter", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("is_forecast", sa.Boolean(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("period_source_sheet", sa.String(length=255), nullable=False),
        sa.Column("period_source_cell", sa.String(length=32), nullable=False),
        sa.Column("value_source_sheet", sa.String(length=255), nullable=False),
        sa.Column("value_source_cell", sa.String(length=32), nullable=False),
        sa.Column("exact_formula", sa.Text(), nullable=True),
        sa.Column("formula_status", sa.String(length=64), nullable=False),
        sa.Column("cached_value_available", sa.Boolean(), nullable=False),
        sa.Column("cached_value_freshness", sa.String(length=32), nullable=True),
        sa.Column("number_format", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "month IS NULL OR month BETWEEN 1 AND 12",
            name="ck_financial_series_value_month",
        ),
        sa.CheckConstraint(
            "period_index >= 0",
            name="ck_financial_series_value_period_index",
        ),
        sa.CheckConstraint(
            "quarter IS NULL OR quarter BETWEEN 1 AND 4",
            name="ck_financial_series_value_quarter",
        ),
        sa.ForeignKeyConstraint(
            ["financial_series_id"],
            ["financial_series.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "financial_series_id",
            "period_index",
            name="uq_financial_series_value_period_index",
        ),
        sa.UniqueConstraint(
            "financial_series_id",
            "value_source_sheet",
            "value_source_cell",
            name="uq_financial_series_value_source_cell",
        ),
    )
    op.create_index(
        "ix_financial_series_values_period_source",
        "financial_series_values",
        ["period_source_sheet", "period_source_cell", "financial_series_id"],
        unique=False,
    )
    op.create_index(
        "ix_financial_series_values_value_source",
        "financial_series_values",
        ["value_source_sheet", "value_source_cell", "financial_series_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_financial_series_values_value_source",
        table_name="financial_series_values",
    )
    op.drop_index(
        "ix_financial_series_values_period_source",
        table_name="financial_series_values",
    )
    op.drop_table("financial_series_values")
    op.drop_index("ix_financial_series_model_id", table_name="financial_series")
    op.drop_index("ix_financial_series_model_category", table_name="financial_series")
    op.drop_table("financial_series")
    op.drop_index("ix_model_parameters_model_role", table_name="model_parameters")
    op.drop_table("model_parameters")
    op.drop_index("ix_model_versions_workbook_created", table_name="model_versions")
    op.drop_index("ix_model_versions_status_created", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_table("workbook_versions")
