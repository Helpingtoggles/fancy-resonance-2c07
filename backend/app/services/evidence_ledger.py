"""Evidence Ledger: append-only provenance for every AI/extraction output.

The ledger guarantees that every structured field the platform suggests can
be traced to a verbatim snippet of a source artifact (document page, OCR
text, or voice transcript) with the method and confidence that produced it.

Like the audit log, entries are hash-chained for tamper evidence. Entries
are never updated or deleted; corrections happen at the ExtractedField layer
(the RN edits the *field*, the evidence of what the source said stands).
"""

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.evidence import EvidenceRecord, ExtractedField, FieldStatus

_GENESIS = "0" * 64


def _entry_payload(e: EvidenceRecord) -> dict:
    return {
        "document_id": e.document_id,
        "page_number": e.page_number,
        "span_start": e.span_start,
        "span_end": e.span_end,
        "snippet": e.snippet,
        "method": e.method,
        "method_version": e.method_version,
        "confidence": e.confidence,
        "context": e.context,
    }


def _compute_hash(prev_hash: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def append_evidence(
    db: Session,
    *,
    snippet: str,
    method: str,
    confidence: float,
    document_id: str | None = None,
    page_number: int | None = None,
    span_start: int | None = None,
    span_end: int | None = None,
    method_version: str = "1",
    context: dict | None = None,
) -> EvidenceRecord:
    if not snippet or not snippet.strip():
        raise ValueError("Evidence snippet must be non-empty: every suggestion needs verbatim source text.")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError("Evidence confidence must be within [0, 1].")

    last = db.execute(
        select(EvidenceRecord).order_by(EvidenceRecord.seq.desc()).limit(1)
    ).scalar_one_or_none()
    prev_hash = last.entry_hash if last else _GENESIS
    next_seq = (last.seq if last and last.seq else 0) + 1

    record = EvidenceRecord(
        seq=next_seq,
        document_id=document_id,
        page_number=page_number,
        span_start=span_start,
        span_end=span_end,
        snippet=snippet,
        method=method,
        method_version=method_version,
        confidence=confidence,
        context=context,
        prev_hash=prev_hash,
        entry_hash="",
    )
    record.entry_hash = _compute_hash(prev_hash, _entry_payload(record))
    db.add(record)
    db.flush()
    return record


def create_extracted_field(
    db: Session,
    *,
    entity_type: str,
    field_name: str,
    suggested_value: str | None,
    evidence: EvidenceRecord,
    extractor_name: str,
    extractor_version: str = "1",
    entity_id: str | None = None,
    confidence: float | None = None,
) -> ExtractedField:
    """The only sanctioned way to create an ExtractedField.

    Enforces the invariant that fields carry evidence + confidence, and start
    in SUGGESTED status (never pre-accepted).
    """
    if evidence is None or evidence.id is None:
        raise ValueError("ExtractedField requires a persisted EvidenceRecord.")
    conf = confidence if confidence is not None else evidence.confidence
    if conf is None or not (0.0 <= conf <= 1.0):
        raise ValueError("ExtractedField requires a confidence within [0, 1].")

    field = ExtractedField(
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        suggested_value=suggested_value,
        confidence=conf,
        evidence_id=evidence.id,
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        status=FieldStatus.SUGGESTED,
    )
    db.add(field)
    db.flush()
    return field


def verify_chain(db: Session) -> dict:
    entries = db.execute(select(EvidenceRecord).order_by(EvidenceRecord.seq.asc())).scalars().all()
    prev_hash = _GENESIS
    for e in entries:
        if e.prev_hash != prev_hash or e.entry_hash != _compute_hash(prev_hash, _entry_payload(e)):
            return {"valid": False, "entries": len(entries), "first_invalid_seq": e.seq}
        prev_hash = e.entry_hash
    return {"valid": True, "entries": len(entries), "first_invalid_seq": None}


def ledger_stats(db: Session) -> dict:
    total = db.execute(select(func.count(EvidenceRecord.id))).scalar_one()
    fields = db.execute(select(func.count(ExtractedField.id))).scalar_one()
    return {"evidence_records": total, "extracted_fields": fields}
