"""Add approval_decisions, action_executions, and verification_results tables.

Revision ID: 0003_remediation_schema
Revises: 0002_investigation_persistence
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_remediation_schema"
down_revision: str | None = "0002_investigation_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create remediation approval, execution, and verification tables."""
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("approver_id", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["remediation_proposals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_decisions_incident_id",
        "approval_decisions",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_decisions_proposal_id",
        "approval_decisions",
        ["proposal_id"],
        unique=False,
    )

    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("target_service", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("output_message", sa.Text(), nullable=False),
        sa.Column("rollback_plan", sa.Text(), nullable=False),
        sa.Column("executed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["remediation_proposals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_action_executions_incident_id",
        "action_executions",
        ["incident_id"],
        unique=False,
    )

    op.create_table(
        "verification_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("recovered", sa.Boolean(), nullable=False),
        sa.Column("observed_5xx_rate", sa.Float(), nullable=True),
        sa.Column("observed_pool_wait_ms", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("verified_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["action_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verification_results_incident_id",
        "verification_results",
        ["incident_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop remediation tables."""
    op.drop_index("ix_verification_results_incident_id", table_name="verification_results")
    op.drop_table("verification_results")

    op.drop_index("ix_action_executions_incident_id", table_name="action_executions")
    op.drop_table("action_executions")

    op.drop_index("ix_approval_decisions_proposal_id", table_name="approval_decisions")
    op.drop_index("ix_approval_decisions_incident_id", table_name="approval_decisions")
    op.drop_table("approval_decisions")