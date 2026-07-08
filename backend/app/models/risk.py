from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import _uuid, utcnow


class ValidationFinding(Base):
    """A CMS/OASIS validation finding for an assessment run."""

    __tablename__ = "validation_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("oasis_assessments.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))  # error | warning | info
    message: Mapped[str] = mapped_column(Text)
    item_ids: Mapped[list | None] = mapped_column(JSON, default=None)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DenialRiskFinding(Base):
    """A payer-denial risk flag for an episode."""

    __tablename__ = "denial_risk_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    risk_level: Mapped[str] = mapped_column(String(16))  # high | medium | low
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text, default=None)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
