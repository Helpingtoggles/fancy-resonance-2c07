import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class EpisodeStatus(str, enum.Enum):
    REFERRAL = "referral"
    PENDING_SOC = "pending_soc"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    DISCHARGED = "discharged"


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mrn: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str] = mapped_column(String(128))
    date_of_birth: Mapped[date | None] = mapped_column(Date, default=None)
    sex: Mapped[str | None] = mapped_column(String(16), default=None)
    payer: Mapped[str | None] = mapped_column(String(128), default=None)
    medicare_id: Mapped[str | None] = mapped_column(String(32), default=None)
    address: Mapped[str | None] = mapped_column(String(512), default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)
    primary_physician: Mapped[str | None] = mapped_column(String(255), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    episodes: Mapped[list["Episode"]] = relationship(back_populates="patient")


class Episode(Base):
    """A home-health episode / certification period for a patient."""

    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    status: Mapped[EpisodeStatus] = mapped_column(Enum(EpisodeStatus), default=EpisodeStatus.REFERRAL)
    referral_date: Mapped[date | None] = mapped_column(Date, default=None)
    soc_date: Mapped[date | None] = mapped_column(Date, default=None)
    cert_period_start: Mapped[date | None] = mapped_column(Date, default=None)
    cert_period_end: Mapped[date | None] = mapped_column(Date, default=None)
    primary_diagnosis: Mapped[str | None] = mapped_column(String(255), default=None)
    primary_diagnosis_code: Mapped[str | None] = mapped_column(String(16), default=None)
    referring_physician: Mapped[str | None] = mapped_column(String(255), default=None)
    face_to_face_date: Mapped[date | None] = mapped_column(Date, default=None)
    homebound_narrative: Mapped[str | None] = mapped_column(String(2048), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="episodes")
