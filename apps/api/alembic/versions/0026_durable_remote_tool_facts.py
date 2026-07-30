"""durable remote tool facts and authorization budgets

Revision ID: 0026
Revises: 0025

Stage 5 Spec 008 / ADR 006:

- Agent Tool Calls bind to an AgentRun in the same Workspace.
- Ordinals are unique within a run.
- AgentRun deletion cascades to its Tool Calls.
- Job/Tutor authorization counters remain within their declared budgets.

The migration rejects inconsistent historical rows instead of rewriting them.
"""

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM agent_tool_calls tc
            JOIN agent_runs ar ON ar.id = tc.agent_run_id
            WHERE tc.workspace_id <> ar.workspace_id
          ) THEN
            RAISE EXCEPTION 'agent_tool_calls contain cross-workspace rows';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM agent_tool_calls
            GROUP BY agent_run_id, ordinal
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'agent_tool_calls contain duplicate run ordinals';
          END IF;
          IF EXISTS (
            SELECT 1 FROM agent_tool_calls
            WHERE ordinal < 0
               OR status NOT IN ('started','succeeded','failed','timed_out','canceled')
          ) THEN
            RAISE EXCEPTION 'agent_tool_calls contain invalid status or ordinal';
          END IF;
          IF EXISTS (
            SELECT 1 FROM job_tool_authorizations
            WHERE max_calls < 0 OR used_calls < 0 OR used_calls > max_calls
          ) THEN
            RAISE EXCEPTION 'job_tool_authorizations contain invalid budgets';
          END IF;
          IF EXISTS (
            SELECT 1 FROM tutor_turn_tool_authorizations
            WHERE max_calls < 0 OR used_calls < 0 OR used_calls > max_calls
          ) THEN
            RAISE EXCEPTION 'tutor_turn_tool_authorizations contain invalid budgets';
          END IF;
        END $$;
        """
    )

    # Replace the old single-column FK. Keeping it as NO ACTION beside the
    # composite CASCADE FK can block AgentRun deletion depending on FK order.
    op.drop_constraint(
        "agent_tool_calls_agent_run_id_fkey",
        "agent_tool_calls",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_agent_tool_calls_run_workspace",
        "agent_tool_calls",
        "agent_runs",
        ["agent_run_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_agent_tool_calls_status_valid",
        "agent_tool_calls",
        "status IN ('started','succeeded','failed','timed_out','canceled')",
    )
    op.create_check_constraint(
        "ck_agent_tool_calls_ordinal_nonneg",
        "agent_tool_calls",
        "ordinal >= 0",
    )
    op.create_check_constraint(
        "ck_job_tool_auth_budget_valid",
        "job_tool_authorizations",
        "max_calls >= 0 AND used_calls >= 0 AND used_calls <= max_calls",
    )
    op.create_check_constraint(
        "ck_tutor_turn_tool_auth_budget_valid",
        "tutor_turn_tool_authorizations",
        "max_calls >= 0 AND used_calls >= 0 AND used_calls <= max_calls",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tutor_turn_tool_auth_budget_valid",
        "tutor_turn_tool_authorizations",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_tool_auth_budget_valid",
        "job_tool_authorizations",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_tool_calls_ordinal_nonneg",
        "agent_tool_calls",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_tool_calls_status_valid",
        "agent_tool_calls",
        type_="check",
    )
    op.drop_constraint(
        "fk_agent_tool_calls_run_workspace",
        "agent_tool_calls",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "agent_tool_calls_agent_run_id_fkey",
        "agent_tool_calls",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
    )
