import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    SIGNED = "signed"
    CANCELLED = "cancelled"


class ReviewTask(Base):
    """A human-review work item. All AI output funnels through these."""

    __tablename__ = "review_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(64), index=True)  # oasis_assessment | medication_list | soc_draft | document_extraction
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[ReviewStatus] = mapped_column(Enum(ReviewStatus), default=ReviewStatus.PENDING)
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # low|normal|high|urgent
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    decisions: Mapped[list["ReviewDecision"]] = relationship(
        back_populates="task", order_by="ReviewDecision.created_at"
    )


class ReviewDecision(Base):
    """An explicit human decision on a review task (append-only)."""

    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32))  # claim|approve|request_changes|sign|cancel
    note: Mapped[str | None] = mapped_column(Text, default=None)
    attestation: Mapped[str | None] = mapped_column(Text, default=None)  # required for "sign"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[ReviewTask] = relationship(back_populates="decisions")
