from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class WorkflowDefinition(Base):
    """A compiled workflow authored in the platform DSL (see services/workflow_dsl.py)."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    dsl_source: Mapped[str] = mapped_column(Text)
    compiled: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    current_state: Mapped[str] = mapped_column(String(128))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transitions: Mapped[list["WorkflowTransitionLog"]] = relationship(
        back_populates="instance", order_by="WorkflowTransitionLog.created_at"
    )


class WorkflowTransitionLog(Base):
    __tablename__ = "workflow_transition_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    instance_id: Mapped[str] = mapped_column(ForeignKey("workflow_instances.id"), index=True)
    event: Mapped[str] = mapped_column(String(128))
    from_state: Mapped[str] = mapped_column(String(128))
    to_state: Mapped[str] = mapped_column(String(128))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(32), default="human")
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instance: Mapped[WorkflowInstance] = relationship(back_populates="transitions")
