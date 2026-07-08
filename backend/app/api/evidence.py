from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.evidence import EvidenceRecord, ExtractedField, FieldStatus
from app.models.user import Role, User
from app.schemas.common import EvidenceOut, ExtractedFieldOut, FieldReviewRequest
from app.services import audit, evidence_ledger

router = APIRouter(prefix="/evidence", tags=["evidence"])

reviewer_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.get("/ledger/verify")
def verify_ledger(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return evidence_ledger.verify_chain(db)


@router.get("/ledger/stats")
def ledger_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return evidence_ledger.ledger_stats(db)


@router.get("/{evidence_id}", response_model=EvidenceOut)
def get_evidence(evidence_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record = db.get(EvidenceRecord, evidence_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence record not found")
    return record


@router.get("/fields/by-entity/{entity_type}/{entity_id}", response_model=list[ExtractedFieldOut])
def fields_for_entity(entity_type: str, entity_id: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return db.execute(
        select(ExtractedField).where(
            ExtractedField.entity_type == entity_type, ExtractedField.entity_id == entity_id
        )
    ).scalars().all()


@router.post("/fields/{field_id}/review", response_model=ExtractedFieldOut)
def review_field(field_id: str, body: FieldReviewRequest, db: Session = Depends(get_db),
                 actor: User = Depends(reviewer_roles)):
    """Human review of one extracted field: accept, edit, or reject.

    This is the ONLY code path that writes ``final_value`` on an extracted
    field — it requires an authenticated RN/clinician.
    """
    field = db.get(ExtractedField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracted field not found")
    if field.status != FieldStatus.SUGGESTED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Field already reviewed ({field.status.value})")

    if body.action == "accept":
        field.status = FieldStatus.ACCEPTED
        field.final_value = field.suggested_value
    elif body.action == "edit":
        if body.final_value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Edit requires final_value")
        field.status = FieldStatus.EDITED
        field.final_value = body.final_value
    else:  # reject
        field.status = FieldStatus.REJECTED
        field.final_value = None

    field.reviewed_by = actor.id
    field.reviewed_at = datetime.now(timezone.utc)
    field.review_note = body.note
    audit.record(
        db, action=f"field.{body.action}", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="extracted_field", resource_id=field.id,
        detail={"entity_type": field.entity_type, "field": field.field_name,
                "suggested": field.suggested_value, "final": field.final_value},
    )
    db.commit()
    return field
