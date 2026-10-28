"""Add evidence, hypotheses, diagnostics, proposals, and incident_reports tables.

Revision ID: 0002_investigation_persistence
Revises: 0001_initial_schema
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_investigation_persistence"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create Phase 5 investigation persistence tables with idempotency constraints."""
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("fact_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("service_id", sa.String(length=64), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("signal_name", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id", "fact_id", name="uq_evidence_incident_fact"),
    )
    op.create_index(
        "ix_evidence_records_incident_id", "evidence_records", ["incident_id"], unique=False
    )

    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=128), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("target_service", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("supporting_fact_ids_json", sa.JSON(), nullable=False),
        sa.Column("contradicting_fact_ids_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id", "hypothesis_id", name="uq_hypothesis_incident_hyp"),
    )
    op.create_index("ix_hypotheses_incident_id", "hypotheses", ["incident_id"], unique=False)

    op.create_table(
        "diagnostic_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("target_service", sa.String(length=64), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("executed", sa.Boolean(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id", "step_id", name="uq_diagnostic_incident_step"),
    )
    op.create_index(
        "ix_diagnostic_runs_incident_id", "diagnostic_runs", ["incident_id"], unique=False
    )

    op.create_table(
        "remediation_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("target_service", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("preconditions_json", sa.JSON(), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_remediation_proposals_incident_id",
        "remediation_proposals",
        ["incident_id"],
        unique=False,
    )

    op.create_table(
        "incident_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("root_cause_summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("bounded_next_diagnostic", sa.Text(), nullable=True),
        sa.Column("report_payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index(
        "ix_incident_reports_incident_id", "incident_reports", ["incident_id"], unique=False
    )


def downgrade() -> None:
    """Drop Phase 5 investigation persistence tables."""
    op.drop_index("ix_incident_reports_incident_id", table_name="incident_reports")
    op.drop_table("incident_reports")

    op.drop_index("ix_remediation_proposals_incident_id", table_name="remediation_proposals")
    op.drop_table("remediation_proposals")

    op.drop_index("ix_diagnostic_runs_incident_id", table_name="diagnostic_runs")
    op.drop_table("diagnostic_runs")

    op.drop_index("ix_hypotheses_incident_id", table_name="hypotheses")
    op.drop_table("hypotheses")

    op.drop_index("ix_evidence_records_incident_id", table_name="evidence_records")
    op.drop_table("evidence_records")