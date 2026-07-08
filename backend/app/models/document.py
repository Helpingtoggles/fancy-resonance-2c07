import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import _uuid, utcnow


class DocumentKind(str, enum.Enum):
    REFERRAL = "referral"
    PHYSICIAN_ORDER = "physician_order"
    MEDICATION_LIST = "medication_list"
    DISCHARGE_SUMMARY = "discharge_summary"
    FACE_TO_FACE = "face_to_face"
    WOUND_PHOTO = "wound_photo"
    INSURANCE_CARD = "insurance_card"
    VOICE_RECORDING = "voice_recording"
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    OCR_COMPLETE = "ocr_complete"
    EXTRACTED = "extracted"
    FAILED = "failed"


class Document(Base):
    """An ingested artifact: scanned page(s), photo, PDF, text, or audio."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id"), index=True)
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind), default=DocumentKind.OTHER)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.UPLOADED)
    filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1024))
    ocr_engine: Mapped[str | None] = mapped_column(String(64), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", order_by="DocumentPage.page_number"
    )


class DocumentPage(Base):
    """OCR/transcription output for one page (or the whole audio transcript)."""

    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    layout: Mapped[dict | None] = mapped_column(JSON, default=None)  # word boxes when available

    document: Mapped[Document] = relationship(back_populates="pages")


class VoiceSessionStatus(str, enum.Enum):
    RECORDED = "recorded"
    TRANSCRIBED = "transcribed"
    DRAFTED = "drafted"        # SOC draft generated, awaiting RN review
    FAILED = "failed"


class VoiceSession(Base):
    """A voice-to-SOC documentation session.

    The generated SOC narrative/fields are *drafts*; they flow into the RN
    review workflow like any other extraction and are never auto-finalized.
    """

    __tablename__ = "voice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    audio_document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[VoiceSessionStatus] = mapped_column(
        Enum(VoiceSessionStatus), default=VoiceSessionStatus.RECORDED
    )
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    transcription_engine: Mapped[str | None] = mapped_column(String(64), default=None)
    transcription_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    soc_draft: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
