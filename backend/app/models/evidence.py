import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import _uuid, utcnow


class EvidenceRecord(Base):
    """Append-only Evidence Ledger entry.

    Every AI/extraction output must point at one of these: the exact source
    location (document, page, character span) plus the verbatim snippet, the
    method that produced it, and a hash chain like the audit log so tampering
    is detectable. Rows are never updated or deleted.
    """

    __tablename__ = "evidence_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seq: Mapped[int] = mapped_column(Integer, autoincrement=True, unique=True, index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, default=None)
    span_start: Mapped[int | None] = mapped_column(Integer, default=None)
    span_end: Mapped[int | None] = mapped_column(Integer, default=None)
    snippet: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(128))          # e.g. "regex:medication_line"
    method_version: Mapped[str] = mapped_column(String(32), default="1")
    confidence: Mapped[float] = mapped_column(Float)
    context: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), index=True)

    __table_args__ = {"sqlite_autoincrement": True}


class FieldStatus(str, enum.Enum):
    SUGGESTED = "suggested"        # produced by AI/extraction — not usable clinically yet
    ACCEPTED = "accepted"          # RN accepted the suggestion as-is
    EDITED = "edited"              # RN corrected the value
    REJECTED = "rejected"          # RN rejected the suggestion


class ExtractedField(Base):
    """A single structured field produced by extraction.

    Invariants (enforced in ExtractionService / reviewed in tests):
      * ``evidence_id`` is required — no field without source evidence.
      * ``confidence`` is required.
      * ``final_value`` may only be written by the RN review endpoints and is
        NULL until a human reviews the field.
    """

    __tablename__ = "extracted_fields"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)   # medication | physician_order | oasis_item | soc_field ...
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    field_name: Mapped[str] = mapped_column(String(128))
    suggested_value: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_ledger.id"), nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(128))
    extractor_version: Mapped[str] = mapped_column(String(32), default="1")
    status: Mapped[FieldStatus] = mapped_column(Enum(FieldStatus), default=FieldStatus.SUGGESTED)
    final_value: Mapped[str | None] = mapped_column(Text, default=None)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
