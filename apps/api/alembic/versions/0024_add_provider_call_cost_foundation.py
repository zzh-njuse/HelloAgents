"""add provider call and CNY rate snapshot foundation (Stage 5 Slice 1B-1)

Revision ID: 0024
Revises: 0023

Two new independent fact tables (Spec 002 / ADR 001):

- ``provider_rate_snapshots``: append-only CNY price snapshots keyed by
  (provider, model, effective_at), currency locked to CNY, non-negative rates.
- ``provider_calls``: one real provider request attempt with optional binding
  to a rate snapshot and an optional AgentRun owner (CASCADE on both).

Plus two human-approved DB-layer integrity hardenings (independent review,
2026-07-27; recorded in Spec 002 / ADR 001):

- Issue 2 (no wrong-price binding): ``provider_calls`` carries a composite FK
  (provider_rate_snapshot_id, provider, model) -> provider_rate_snapshots, so a
  bound snapshot's provider/model must equal the call's.
- Issue 1 (Workspace isolation): ``provider_calls`` carries a composite FK
  (agent_run_id, workspace_id) -> agent_runs, so a bound run's workspace must
  equal the call's. This needs a redundant UNIQUE(id, workspace_id) on the
  existing ``agent_runs`` table — ``id`` is already the PK, so it can never be
  violated; it exists only as the composite-FK target.

The migration is purely additive: it creates the two new tables and adds one
redundant unique constraint on an existing table. No existing column, table or
row is altered or backfilled, and no existing constraint/index is dropped.
Downgrade reverses in dependency order: provider_calls first (dropping its FKs),
then the agent_runs unique constraint, then the two new tables (and indexes).
"""

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- provider_rate_snapshots (created first: provider_calls references it) -
    op.create_table(
        "provider_rate_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("input_rate_per_1m", sa.Numeric(16, 8), nullable=False),
        sa.Column("output_rate_per_1m", sa.Numeric(16, 8), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "model", "effective_at", name="uq_provider_rate_snapshots_pme"),
        # Composite-FK target for provider_calls (Issue 2: no wrong-price
        # binding). ``id`` is the PK, so (id, provider, model) is trivially
        # unique and never violated; it exists only so Postgres accepts the
        # matching composite foreign key on provider_calls below.
        sa.UniqueConstraint("id", "provider", "model", name="uq_provider_rate_snapshots_id_provider_model"),
        sa.CheckConstraint("currency = 'CNY'", name="ck_provider_rate_snapshots_currency_cny"),
        sa.CheckConstraint("input_rate_per_1m >= 0", name="ck_provider_rate_snapshots_input_rate_nonneg"),
        sa.CheckConstraint("output_rate_per_1m >= 0", name="ck_provider_rate_snapshots_output_rate_nonneg"),
    )
    op.create_index("ix_provider_rate_snapshots_provider", "provider_rate_snapshots", ["provider"])
    op.create_index("ix_provider_rate_snapshots_model", "provider_rate_snapshots", ["model"])

    # --- Issue 1: Workspace isolation ----------------------------------------
    # Composite-FK target on the EXISTING agent_runs table. ``id`` is already the
    # PK, so UNIQUE(id, workspace_id) is redundant and can never be violated; it
    # is created here (before provider_calls) only so Postgres accepts the
    # matching composite FK below. Human-approved minimal hardening.
    op.create_unique_constraint(
        "uq_agent_runs_id_workspace",
        "agent_runs",
        ["id", "workspace_id"],
    )

    # --- provider_calls ------------------------------------------------------
    op.create_table(
        "provider_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="started"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_rate_snapshot_id", sa.String(36), sa.ForeignKey("provider_rate_snapshots.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("ordinal >= 0", name="ck_provider_calls_ordinal_nonneg"),
        sa.CheckConstraint(
            "status IN ('started','succeeded','failed','timed_out','canceled')",
            name="ck_provider_calls_status_valid",
        ),
        sa.CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_provider_calls_input_tokens_nonneg"),
        sa.CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_provider_calls_output_tokens_nonneg"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_provider_calls_latency_nonneg"),
        # Issue 2: bound snapshot's provider/model must equal the call's
        # provider/model. MATCH SIMPLE skips the FK when snapshot_id IS NULL.
        sa.ForeignKeyConstraint(
            ["provider_rate_snapshot_id", "provider", "model"],
            ["provider_rate_snapshots.id", "provider_rate_snapshots.provider", "provider_rate_snapshots.model"],
            name="fk_provider_calls_snapshot_provider_model",
        ),
        # Issue 1: a bound run's workspace must equal the call's workspace.
        # MATCH SIMPLE skips the FK when agent_run_id IS NULL (workspace-only
        # call). ON DELETE CASCADE is required because Postgres checks FKs in
        # DDL order; this composite FK appears before the simple FK in
        # SQLAlchemy's emitted DDL, so NO ACTION would block the AgentRun
        # delete before the simple FK's CASCADE fires.
        sa.ForeignKeyConstraint(
            ["agent_run_id", "workspace_id"],
            ["agent_runs.id", "agent_runs.workspace_id"],
            name="fk_provider_calls_run_workspace",
            ondelete="CASCADE",
        ),
    )
    for column in ("workspace_id", "agent_run_id", "status", "provider_rate_snapshot_id"):
        op.create_index(f"ix_provider_calls_{column}", "provider_calls", [column])
    # Partial unique index: ordinal distinguishes calls within a run. Valid on
    # both Postgres and SQLite (both support partial indexes with WHERE). Raw
    # SQL is used so the same statement is portable across dialects.
    op.execute(
        "CREATE UNIQUE INDEX uq_provider_calls_run_ordinal "
        "ON provider_calls (agent_run_id, ordinal) "
        "WHERE agent_run_id IS NOT NULL"
    )


def downgrade() -> None:
    # Reverse dependency order: provider_calls (whose FKs reference both
    # snapshots and agent_runs) is dropped first; only then can the agent_runs
    # unique constraint added by this migration be removed.
    op.execute("DROP INDEX IF EXISTS uq_provider_calls_run_ordinal")
    for column in ("workspace_id", "agent_run_id", "status", "provider_rate_snapshot_id"):
        op.drop_index(f"ix_provider_calls_{column}", table_name="provider_calls")
    op.drop_table("provider_calls")
    op.drop_constraint("uq_agent_runs_id_workspace", "agent_runs", type_="unique")
    op.drop_index("ix_provider_rate_snapshots_model", table_name="provider_rate_snapshots")
    op.drop_index("ix_provider_rate_snapshots_provider", table_name="provider_rate_snapshots")
    op.drop_table("provider_rate_snapshots")
