from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.document import Document, DocumentKind
from app.models.evidence import ExtractedField
from app.models.user import Role, User
from app.schemas.common import DocumentOut, DocumentPageOut, ExtractedFieldOut
from app.services import audit, ingestion
from app.services.extraction import medications as med_extraction
from app.services.extraction import orders as order_extraction

router = APIRouter(prefix="/documents", tags=["documents"])

ingest_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN, Role.INTAKE)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form("other"),
    patient_id: str | None = Form(None),
    episode_id: str | None = Form(None),
    db: Session = Depends(get_db),
    actor: User = Depends(ingest_roles),
):
    try:
        doc_kind = DocumentKind(kind)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown document kind '{kind}'")
    content = await file.read()
    try:
        doc = ingestion.ingest_document(
            db,
            content=content,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            kind=doc_kind,
            patient_id=patient_id,
            episode_id=episode_id,
            uploaded_by=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.commit()
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(
    episode_id: str | None = None,
    patient_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Document).order_by(Document.created_at.desc()).limit(200)
    if episode_id:
        stmt = stmt.where(Document.episode_id == episode_id)
    if patient_id:
        stmt = stmt.where(Document.patient_id == patient_id)
    return db.execute(stmt).scalars().all()


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


@router.get("/{document_id}/pages", response_model=list[DocumentPageOut])
def get_document_pages(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc.pages


@router.post("/{document_id}/extract", response_model=dict)
def run_extraction(document_id: str, db: Session = Depends(get_db), actor: User = Depends(ingest_roles)):
    """Run medication + physician-order extraction over the document's OCR text.

    Output is suggestions-only: extracted meds enter EXTRACTED status and all
    fields carry evidence + confidence, awaiting RN review.
    """
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if not doc.pages:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document has no OCR text to extract from")

    meds = med_extraction.extract_and_persist(db, doc)
    orders = order_extraction.extract_and_persist(db, doc)
    from app.models.document import DocumentStatus

    doc.status = DocumentStatus.EXTRACTED
    audit.record(
        db, action="document.extracted", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="document", resource_id=doc.id,
        detail={"medications": len(meds), "orders": len(orders)},
    )
    db.commit()
    return {
        "document_id": doc.id,
        "medications_extracted": len(meds),
        "orders_extracted": len(orders),
        "note": "All extractions are suggestions pending RN review.",
    }


@router.get("/{document_id}/fields", response_model=list[ExtractedFieldOut])
def get_document_fields(document_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """All extracted fields whose evidence points at this document."""
    from app.models.evidence import EvidenceRecord

    stmt = (
        select(ExtractedField)
        .join(EvidenceRecord, ExtractedField.evidence_id == EvidenceRecord.id)
        .where(EvidenceRecord.document_id == document_id)
    )
    return db.execute(stmt).scalars().all()
