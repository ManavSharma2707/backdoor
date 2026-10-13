"""Chat, agent runs and traces, pending actions and the RAG knowledge base."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    EMPTY_OBJECT,
    TZ,
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    composite_fk,
    enum_check,
    tenant_unique,
)

EMBEDDING_DIM = 768


class ChatThread(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "chat_threads"
    __table_args__ = (
        composite_fk("user_id", "users"),
        tenant_unique(),
        Index(
            "ix_chat_threads_tenant_user_last_message",
            "tenant_id",
            "user_id",
            desc("last_message_at"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(Text)
    page_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(server_default=text("false"))
    last_message_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())


class ChatMessage(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        composite_fk("thread_id", "chat_threads"),
        enum_check("role", ("user", "assistant")),
        CheckConstraint("feedback IN (-1, 0, 1)", name="feedback_valid"),
        Index("ix_chat_messages_tenant_thread_created", "tenant_id", "thread_id", "created_at"),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    blocks: Mapped[list[Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[Any] | None] = mapped_column(JSONB)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    feedback: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    feedback_note: Mapped[str | None] = mapped_column(Text)


class AgentRun(IdMixin, TenantMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        composite_fk("user_id", "users"),
        composite_fk("thread_id", "chat_threads"),
        tenant_unique(),
        enum_check(
            "kind",
            ("chat", "monday_review", "investigation", "scenario_plan", "dq_scan", "supplier_prep"),
        ),
        enum_check("status", ("running", "succeeded", "failed", "capped", "fallback")),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_name: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    steps_count: Mapped[int] = mapped_column(Integer, server_default="0")
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJECT)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TZ)


class AgentStep(TenantMixin, CreatedAtMixin, Base):
    """Stored for audit and evals. Never returned by any user API."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        composite_fk("run_id", "agent_runs"),
        enum_check("step_type", ("llm", "tool", "retrieval", "verify", "safety")),
        Index("ix_agent_steps_tenant_run_idx", "tenant_id", "run_id", "idx"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    idx: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(Text)
    step_type: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class AgentAction(IdMixin, TenantMixin, Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        composite_fk("run_id", "agent_runs"),
        composite_fk("thread_id", "chat_threads"),
        enum_check(
            "action_type",
            ("approve_lines", "fix_data_issue", "create_report_note", "create_draft_pos"),
        ),
        enum_check("status", ("pending", "confirmed", "rejected", "expired", "failed")),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    proposed_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TZ)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class KnowledgeDocument(IdMixin, CreatedAtMixin, Base):
    """`tenant_id` NULL means a global document. Foreign keys stay plain because of that."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "doc_type",
            "source_ref",
            "content_hash",
            postgresql_nulls_not_distinct=True,
        ),
        enum_check(
            "doc_type",
            (
                "supplier_policy",
                "decision_memory",
                "report_narrative",
                "app_knowledge",
                "product_note",
            ),
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    doc_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    content_hash: Mapped[str] = mapped_column(CHAR(64))


class KnowledgeChunk(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_knowledge_chunks_tenant_document", "tenant_id", "document_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
