import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class OasisAssessmentType(str, enum.Enum):
    SOC = "start_of_care"
    ROC = "resumption_of_care"
    RECERT = "recertification"
    OTHER_FOLLOWUP = "other_followup"
    TRANSFER = "transfer"
    DISCHARGE = "discharge"


class OasisStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"       # suggestions complete, RN review required
    CHANGES_REQUESTED = "changes_requested"
    REVIEWED = "reviewed"                   # every item finalized by RN
    SIGNED = "signed"                       # RN attested; export becomes possible
    EXPORTED = "exported"                   # human-requested export of a signed assessment


class OasisAssessment(Base):
    """An OASIS-E2 assessment.

    Item-level data lives in :class:`OasisItemResponse`. The assessment can
    only reach ``SIGNED`` through the RN review workflow — there is no code
    path that signs or finalizes automatically (see services/review.py and
    core/safety.py).
    """

    __tablename__ = "oasis_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    assessment_type: Mapped[OasisAssessmentType] = mapped_column(Enum(OasisAssessmentType))
    status: Mapped[OasisStatus] = mapped_column(Enum(OasisStatus), default=OasisStatus.IN_PROGRESS)
    oasis_version: Mapped[str] = mapped_column(String(16), default="E2")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    signed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attestation: Mapped[str | None] = mapped_column(Text, default=None)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    exported_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["OasisItemResponse"]] = relationship(back_populates="assessment")


class OasisItemResponse(Base):
    """One OASIS item within an assessment.

    ``suggested_value`` is written by the OASIS engine (with evidence and
    confidence). ``final_value`` is written ONLY by a human RN through the
    review API. AI never writes ``final_value`` — enforced by the engine
    (it has no code path to do so) and asserted by tests.
    """

    __tablename__ = "oasis_item_responses"
    __table_args__ = (UniqueConstraint("assessment_id", "item_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("oasis_assessments.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(16))               # e.g. "M1800", "GG0130A"
    suggested_value: Mapped[str | None] = mapped_column(String(255), default=None)
    suggested_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    suggested_rationale: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, default=None)
    suggested_by: Mapped[str | None] = mapped_column(String(128), default=None)  # engine name+version
    final_value: Mapped[str | None] = mapped_column(String(255), default=None)
    finalized_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    skipped: Mapped[str | None] = mapped_column(String(255), default=None)  # skip-logic reason when not applicable
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assessment: Mapped[OasisAssessment] = relationship(back_populates="items")
