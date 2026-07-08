import enum
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class MedicationStatus(str, enum.Enum):
    EXTRACTED = "extracted"          # from a document; pending RN reconciliation
    ACTIVE = "active"
    HELD = "held"
    DISCONTINUED = "discontinued"


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    strength: Mapped[str | None] = mapped_column(String(64), default=None)      # "10 mg"
    dose: Mapped[str | None] = mapped_column(String(64), default=None)          # "1 tablet"
    route: Mapped[str | None] = mapped_column(String(32), default=None)         # PO/IV/SUBQ...
    frequency: Mapped[str | None] = mapped_column(String(64), default=None)     # BID/Q8H...
    prn: Mapped[bool] = mapped_column(Boolean, default=False)
    prn_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    indication: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[MedicationStatus] = mapped_column(Enum(MedicationStatus), default=MedicationStatus.EXTRACTED)
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)
    is_high_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    fdb_payload: Mapped[dict | None] = mapped_column(JSON, default=None)   # normalized FDB request, see services/fdb.py
    fdb_prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderStatus(str, enum.Enum):
    EXTRACTED = "extracted"
    PENDING_SIGNATURE = "pending_signature"
    SIGNED = "signed"
    VOIDED = "voided"


class PhysicianOrder(Base):
    __tablename__ = "physician_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    order_type: Mapped[str | None] = mapped_column(String(64), default=None)   # sn_frequency|therapy|medication|wound_care|infusion|other
    order_text: Mapped[str] = mapped_column(Text)
    ordering_physician: Mapped[str | None] = mapped_column(String(255), default=None)
    npi: Mapped[str | None] = mapped_column(String(16), default=None)
    order_date: Mapped[date | None] = mapped_column(Date, default=None)
    is_verbal: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.EXTRACTED)
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    signed_date: Mapped[date | None] = mapped_column(Date, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InfusionOrder(Base):
    __tablename__ = "infusion_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    physician_order_id: Mapped[str | None] = mapped_column(ForeignKey("physician_orders.id"))
    drug_name: Mapped[str] = mapped_column(String(255))
    dose_value: Mapped[float | None] = mapped_column(Float, default=None)
    dose_unit: Mapped[str | None] = mapped_column(String(32), default=None)      # mg, g, units, mcg/kg/min
    diluent: Mapped[str | None] = mapped_column(String(128), default=None)
    volume_ml: Mapped[float | None] = mapped_column(Float, default=None)
    rate_ml_hr: Mapped[float | None] = mapped_column(Float, default=None)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    frequency: Mapped[str | None] = mapped_column(String(64), default=None)
    access_type: Mapped[str | None] = mapped_column(String(64), default=None)    # PICC, port, midline, PIV
    line_flush_protocol: Mapped[str | None] = mapped_column(String(255), default=None)
    start_date: Mapped[date | None] = mapped_column(Date, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    administrations: Mapped[list["InfusionAdministration"]] = relationship(back_populates="order")


class InfusionAdministration(Base):
    __tablename__ = "infusion_administrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    infusion_order_id: Mapped[str] = mapped_column(ForeignKey("infusion_orders.id"), index=True)
    administered_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    actual_rate_ml_hr: Mapped[float | None] = mapped_column(Float, default=None)
    site_assessment: Mapped[str | None] = mapped_column(Text, default=None)
    line_patency_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    flush_performed: Mapped[bool] = mapped_column(Boolean, default=False)
    complications: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[InfusionOrder] = relationship(back_populates="administrations")


class Wound(Base):
    __tablename__ = "wounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"), index=True)
    location: Mapped[str] = mapped_column(String(255))
    wound_type: Mapped[str] = mapped_column(String(64))       # pressure|surgical|venous|arterial|diabetic|trauma|other
    pressure_stage: Mapped[str | None] = mapped_column(String(32), default=None)  # 1-4, unstageable, DTI
    onset_date: Mapped[date | None] = mapped_column(Date, default=None)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|healing|healed|deteriorating
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assessments: Mapped[list["WoundAssessment"]] = relationship(
        back_populates="wound", order_by="WoundAssessment.assessed_at"
    )


class WoundAssessment(Base):
    __tablename__ = "wound_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    wound_id: Mapped[str] = mapped_column(ForeignKey("wounds.id"), index=True)
    assessed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    length_cm: Mapped[float | None] = mapped_column(Float, default=None)
    width_cm: Mapped[float | None] = mapped_column(Float, default=None)
    depth_cm: Mapped[float | None] = mapped_column(Float, default=None)
    undermining: Mapped[str | None] = mapped_column(String(255), default=None)
    tunneling: Mapped[str | None] = mapped_column(String(255), default=None)
    tissue_type: Mapped[str | None] = mapped_column(String(64), default=None)   # granulation|slough|eschar|epithelial
    exudate_amount: Mapped[str | None] = mapped_column(String(32), default=None)  # none|light|moderate|heavy
    exudate_type: Mapped[str | None] = mapped_column(String(32), default=None)
    odor: Mapped[bool] = mapped_column(Boolean, default=False)
    periwound: Mapped[str | None] = mapped_column(String(255), default=None)
    pain_score: Mapped[int | None] = mapped_column(Integer, default=None)
    treatment_performed: Mapped[str | None] = mapped_column(Text, default=None)
    photo_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    push_score: Mapped[int | None] = mapped_column(Integer, default=None)  # computed, see services/wounds.py
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    wound: Mapped[Wound] = relationship(back_populates="assessments")
