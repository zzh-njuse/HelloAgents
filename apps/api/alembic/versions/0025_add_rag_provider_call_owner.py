"""add RAG owner to provider_calls (Stage 5 Slice 1B-2)

Revision ID: 0025
Revises: 0024

Per Spec 003 §4 / ADR 002 §7:

- ``provider_calls.rag_answer_trace_id``: nullable FK to rag_answer_traces.
- ``rag_answer_traces``: add redundant ``UNIQUE(id, workspace_id)`` so the
  composite FK target exists (same pattern as agent_runs in 0024).
- Composite FK ``(rag_answer_trace_id, workspace_id) ->
  rag_answer_traces(id, workspace_id)`` with ON DELETE CASCADE enforces
  Workspace consistency and cascades deletion.
- Check constraint: ``agent_run_id`` and ``rag_answer_trace_id`` are mutually
  exclusive (at most one non-null); both NULL is allowed (workspace-only call).
- Partial unique index: ``(rag_answer_trace_id, ordinal)`` unique when
  rag_answer_trace_id IS NOT NULL (RAG owner ordinal uniqueness).
- Downgrade removes the new column, constraints, indexes, and the
  rag_answer_traces redundant unique constraint, in dependency order.
- Does NOT weaken any 0024 constraint (Workspace isolation, price binding).
"""

from alembic import op
import sqlalchemy as sa


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- RagAnswerTrace redundant UNIQUE(id, workspace_id) ----------------------
    # Same pattern as agent_runs in 0024: id is already the PK, so
    # UNIQUE(id, workspace_id) is trivially unique and can never be violated.
    # It exists only so Postgres accepts the composite FK below.
    op.create_unique_constraint(
        "uq_rag_answer_traces_id_workspace",
        "rag_answer_traces",
        ["id", "workspace_id"],
    )

    # --- provider_calls.rag_answer_trace_id ------------------------------------
    op.add_column(
        "provider_calls",
        sa.Column("rag_answer_trace_id", sa.String(36), sa.ForeignKey("rag_answer_traces.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index(
        "ix_provider_calls_rag_answer_trace_id",
        "provider_calls",
        ["rag_answer_trace_id"],
    )

    # --- Owner mutual exclusion: at most one of agent_run_id / rag_answer_trace_id non-null ---
    op.execute(
        "ALTER TABLE provider_calls ADD CONSTRAINT ck_provider_calls_one_owner "
        "CHECK ("
        "  (CASE WHEN agent_run_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "  (CASE WHEN rag_answer_trace_id IS NOT NULL THEN 1 ELSE 0 END) <= 1"
        ")"
    )

    # --- Composite FK: (rag_answer_trace_id, workspace_id) -> rag_answer_traces ---
    # MATCH SIMPLE: when rag_answer_trace_id IS NULL, the FK is skipped
    # (workspace-only call). When set, workspace_id must match the trace's.
    # ON DELETE CASCADE: deleting a RagAnswerTrace cascades to its Provider Calls.
    op.create_foreign_key(
        "fk_provider_calls_rag_trace_workspace",
        "provider_calls",
        "rag_answer_traces",
        ["rag_answer_trace_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )

    # --- Partial unique index: RAG owner ordinal uniqueness --------------------
    # Within a single RagAnswerTrace, ordinal must be unique.
    # Calls without a RAG trace are excluded so they don't clash.
    op.execute(
        "CREATE UNIQUE INDEX uq_provider_calls_rag_trace_ordinal "
        "ON provider_calls (rag_answer_trace_id, ordinal) "
        "WHERE rag_answer_trace_id IS NOT NULL"
    )


def downgrade() -> None:
    # Reverse dependency order: indexes and FKs first, then the column,
    # then the rag_answer_traces unique constraint.
    op.execute("DROP INDEX IF EXISTS uq_provider_calls_rag_trace_ordinal")
    op.drop_constraint("fk_provider_calls_rag_trace_workspace", "provider_calls", type_="foreignkey")
    op.drop_constraint("ck_provider_calls_one_owner", "provider_calls", type_="check")
    op.drop_index("ix_provider_calls_rag_answer_trace_id", table_name="provider_calls")
    op.drop_column("provider_calls", "rag_answer_trace_id")
    op.drop_constraint("uq_rag_answer_traces_id_workspace", "rag_answer_traces", type_="unique")
