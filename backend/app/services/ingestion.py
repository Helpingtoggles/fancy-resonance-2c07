"""Document/image/audio ingestion.

Flow: upload → content-addressed storage (sha256) → OCR/transcription →
DocumentPage rows → downstream extraction. Duplicate uploads (same hash,
same patient) are detected and returned instead of re-processed.
"""

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentKind, DocumentPage, DocumentStatus
from app.services import audit
from app.services.ocr import get_ocr_engine

IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff", "image/webp", "image/bmp"}
AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/webm", "audio/ogg"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def store_bytes(content: bytes, filename: str) -> tuple[str, str]:
    """Write content-addressed file; returns (sha256, storage_path)."""
    digest = hashlib.sha256(content).hexdigest()
    root = Path(get_settings().storage_dir)
    suffix = Path(filename).suffix.lower()[:16]
    target = root / digest[:2] / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)
    return digest, str(target)


def ingest_document(
    db: Session,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    kind: DocumentKind,
    patient_id: str | None,
    episode_id: str | None,
    uploaded_by: str | None,
) -> Document:
    if not content:
        raise ValueError("Empty upload.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")

    sha256, storage_path = store_bytes(content, filename)

    existing = db.execute(
        select(Document).where(Document.sha256 == sha256, Document.patient_id == patient_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    doc = Document(
        patient_id=patient_id,
        episode_id=episode_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256=sha256,
        storage_path=storage_path,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    db.flush()

    if content_type in AUDIO_TYPES or kind == DocumentKind.VOICE_RECORDING:
        # Audio is transcribed by the voice-to-SOC pipeline, not OCR.
        doc.status = DocumentStatus.UPLOADED
    else:
        run_ocr(db, doc)

    audit.record(
        db,
        action="document.ingested",
        actor_id=uploaded_by,
        resource_type="document",
        resource_id=doc.id,
        detail={"filename": filename, "kind": kind.value, "sha256": sha256, "bytes": len(content)},
    )
    return doc


def run_ocr(db: Session, doc: Document) -> Document:
    doc.status = DocumentStatus.PROCESSING
    engine = get_ocr_engine()
    try:
        pages = engine.process(Path(doc.storage_path), doc.content_type)
    except Exception as exc:  # engine failure must not lose the document
        doc.status = DocumentStatus.FAILED
        doc.error = f"{type(exc).__name__}: {exc}"
        db.flush()
        return doc

    for page in pages:
        db.add(
            DocumentPage(
                document_id=doc.id,
                page_number=page.page_number,
                text=page.text,
                ocr_confidence=page.confidence,
                layout=page.layout,
            )
        )
    doc.ocr_engine = engine.name
    doc.status = DocumentStatus.OCR_COMPLETE
    db.flush()
    return doc
