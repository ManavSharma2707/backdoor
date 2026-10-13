"""agents rag

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"doc_type\" IN ('supplier_policy', 'decision_memory', 'report_narrative', 'app_knowledge', 'product_note')",
            name=op.f("ck_knowledge_documents_doc_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_knowledge_documents_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
        sa.UniqueConstraint(
            "tenant_id",
            "doc_type",
            "source_ref",
            "content_hash",
            name=op.f("uq_knowledge_documents_tenant_id_doc_type_source_ref_content_hash"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("page_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_chat_threads_tenant_id_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_chat_threads_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_threads")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_chat_threads_tenant_id_id")),
    )
    op.create_index(
        "ix_chat_threads_tenant_user_last_message",
        "chat_threads",
        ["tenant_id", "user_id", sa.literal_column("last_message_at DESC")],
        unique=False,
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_chunks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_knowledge_chunks_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_chunks_tenant_document",
        "knowledge_chunks",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_tsv", "knowledge_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "input",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("steps_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "\"kind\" IN ('chat', 'monday_review', 'investigation', 'scenario_plan', 'dq_scan', 'supplier_prep')",
            name=op.f("ck_agent_runs_kind_valid"),
        ),
        sa.CheckConstraint(
            "\"status\" IN ('running', 'succeeded', 'failed', 'capped', 'fallback')",
            name=op.f("ck_agent_runs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["chat_threads.tenant_id", "chat_threads.id"],
            name=op.f("fk_agent_runs_tenant_id_thread_id_chat_threads"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name=op.f("fk_agent_runs_tenant_id_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_agent_runs_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_agent_runs_tenant_id_id")),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("feedback", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"role\" IN ('user', 'assistant')", name=op.f("ck_chat_messages_role_valid")
        ),
        sa.CheckConstraint("feedback IN (-1, 0, 1)", name=op.f("ck_chat_messages_feedback_valid")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["chat_threads.tenant_id", "chat_threads.id"],
            name=op.f("fk_chat_messages_tenant_id_thread_id_chat_threads"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_chat_messages_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index(
        "ix_chat_messages_tenant_thread_created",
        "chat_messages",
        ["tenant_id", "thread_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "\"action_type\" IN ('approve_lines', 'fix_data_issue', 'create_report_note', 'create_draft_pos')",
            name=op.f("ck_agent_actions_action_type_valid"),
        ),
        sa.CheckConstraint(
            "\"status\" IN ('pending', 'confirmed', 'rejected', 'expired', 'failed')",
            name=op.f("ck_agent_actions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_agent_actions_resolved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_agent_actions_tenant_id_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["chat_threads.tenant_id", "chat_threads.id"],
            name=op.f("fk_agent_actions_tenant_id_thread_id_chat_threads"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_agent_actions_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_actions")),
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("step_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "\"step_type\" IN ('llm', 'tool', 'retrieval', 'verify', 'safety')",
            name=op.f("ck_agent_steps_step_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name=op.f("fk_agent_steps_tenant_id_run_id_agent_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_agent_steps_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
    )
    op.create_index(
        "ix_agent_steps_tenant_run_idx", "agent_steps", ["tenant_id", "run_id", "idx"], unique=False
    )


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_actions")
    op.drop_table("chat_messages")
    op.drop_table("agent_runs")
    op.drop_table("knowledge_chunks")
    op.drop_table("chat_threads")
    op.drop_table("knowledge_documents")
