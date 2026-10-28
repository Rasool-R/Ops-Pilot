"""Initial incident, alert, and audit_event schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply initial Phase 2 tables, constraints, and indexes."""
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("service_id", sa.String(length=64), nullable=False),
        sa.Column("alert_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("incident_status", sa.String(length=32), nullable=False),
        sa.Column("investigation_status", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("remediation_execution_status", sa.String(length=32), nullable=False),
        sa.Column("recovery_verification_status", sa.String(length=32), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incidents_service_fingerprint",
        "incidents",
        ["service_id", "alert_fingerprint"],
        unique=False,
    )
    op.create_index("ix_incidents_status", "incidents", ["incident_status"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("alert_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("service_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("annotations_json", sa.JSON(), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_alerts_fingerprint", "alerts", ["alert_fingerprint"], unique=False)
    op.create_index("ix_alerts_incident_id", "alerts", ["incident_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_incident_id", "audit_events", ["incident_id"], unique=False)


def downgrade() -> None:
    """Revert initial Phase 2 tables."""
    op.drop_index("ix_audit_events_incident_id", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_alerts_incident_id", table_name="alerts")
    op.drop_index("ix_alerts_fingerprint", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_service_fingerprint", table_name="incidents")
    op.drop_table("incidents")