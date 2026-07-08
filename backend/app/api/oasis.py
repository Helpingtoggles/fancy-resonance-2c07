from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.safety import assert_human_actor
from app.models.oasis import OasisAssessment, OasisAssessmentType, OasisItemResponse, OasisStatus
from app.models.patient import Episode
from app.models.review import ReviewTask
from app.models.user import Role, User
from app.schemas.common import OasisCreate, OasisItemFinalize, OasisItemOut, OasisOut
from app.services import audit, cms_validation, oasis_engine
from app.services.oasis_catalog import ITEMS_BY_ID

router = APIRouter(prefix="/oasis", tags=["oasis"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)
rn_only = require_roles(Role.RN_REVIEWER)


@router.post("", response_model=OasisOut, status_code=status.HTTP_201_CREATED)
def create_assessment(body: OasisCreate, db: Session = Depends(get_db), actor: User = Depends(clinical_roles)):
    if db.get(Episode, body.episode_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
    try:
        a_type = OasisAssessmentType(body.assessment_type)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Unknown assessment type '{body.assessment_type}'")
    assessment = oasis_engine.create_assessment(
        db, episode_id=body.episode_id, assessment_type=a_type.value, created_by=actor.id
    )
    audit.record(db, action="oasis.created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="oasis_assessment", resource_id=assessment.id,
                 detail={"type": a_type.value})
    db.commit()
    return assessment


@router.get("", response_model=list[OasisOut])
def list_assessments(episode_id: str | None = None, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    stmt = select(OasisAssessment).order_by(OasisAssessment.created_at.desc()).limit(200)
    if episode_id:
        stmt = stmt.where(OasisAssessment.episode_id == episode_id)
    return db.execute(stmt).scalars().all()


@router.get("/{assessment_id}", response_model=OasisOut)
def get_assessment(assessment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    return assessment


@router.get("/{assessment_id}/items")
def get_items(assessment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    out = []
    for r in assessment.items:
        item = ITEMS_BY_ID.get(r.item_id)
        payload = OasisItemOut.model_validate(r).model_dump()
        payload.update({
            "section": item.section if item else None,
            "label": item.label if item else None,
            "allowed_values": list(item.values) if item else [],
            "value_type": item.value_type if item else "text",
            "required": item.required if item else False,
        })
        out.append(payload)
    return out


@router.post("/{assessment_id}/suggest")
def generate_suggestions(assessment_id: str, db: Session = Depends(get_db),
                         actor: User = Depends(clinical_roles)):
    """Run the OASIS engine to produce suggested values with evidence.

    Suggestions never become final automatically — each item must be
    finalized by an RN via the finalize endpoint.
    """
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    if assessment.status in (OasisStatus.SIGNED, OasisStatus.EXPORTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Assessment is signed; suggestions are frozen")
    result = oasis_engine.generate_suggestions(db, assessment)

    existing_task = db.execute(
        select(ReviewTask).where(ReviewTask.subject_type == "oasis_assessment",
                                 ReviewTask.subject_id == assessment.id,
                                 ReviewTask.status.notin_(["cancelled", "signed"]))
    ).scalars().first()
    if existing_task is None:
        db.add(ReviewTask(
            subject_type="oasis_assessment", subject_id=assessment.id,
            episode_id=assessment.episode_id,
            title=f"Review OASIS {assessment.assessment_type.value} assessment", priority="high",
        ))
    audit.record(db, action="oasis.suggestions_generated", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="oasis_assessment",
                 resource_id=assessment.id, detail=result)
    db.commit()
    return result


@router.post("/{assessment_id}/items/{item_id}/finalize")
def finalize_item(assessment_id: str, item_id: str, body: OasisItemFinalize,
                  db: Session = Depends(get_db), actor: User = Depends(rn_only)):
    """RN writes the FINAL value for one OASIS item.

    This is the only code path in the platform that sets a final OASIS value.
    It requires an authenticated human RN reviewer.
    """
    assert_human_actor("human", "oasis.finalize_item")  # API users are always human
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    if assessment.status in (OasisStatus.SIGNED, OasisStatus.EXPORTED):
        raise HTTPException(status.HTTP_409_CONFLICT, "Assessment is signed; items are frozen")
    response = db.execute(
        select(OasisItemResponse).where(OasisItemResponse.assessment_id == assessment_id,
                                        OasisItemResponse.item_id == item_id)
    ).scalar_one_or_none()
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Item {item_id} not in this assessment")
    item = ITEMS_BY_ID.get(item_id)
    if item and item.values and item.value_type == "code" and body.value not in item.values:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Value '{body.value}' outside allowed domain {list(item.values)}")

    response.final_value = body.value
    response.finalized_by = actor.id
    response.finalized_at = datetime.now(timezone.utc)
    oasis_engine.apply_skip_logic(db, assessment)
    audit.record(db, action="oasis.item_finalized", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="oasis_assessment", resource_id=assessment.id,
                 detail={"item_id": item_id, "final_value": body.value,
                         "suggested_value": response.suggested_value})
    db.commit()
    return {"item_id": item_id, "final_value": body.value,
            "completeness": oasis_engine.completeness(assessment)}


@router.get("/{assessment_id}/completeness")
def get_completeness(assessment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    return oasis_engine.completeness(assessment)


@router.post("/{assessment_id}/validate")
def validate(assessment_id: str, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    episode = db.get(Episode, assessment.episode_id)
    result = cms_validation.run_and_persist(db, assessment, episode)
    audit.record(db, action="oasis.validated", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="oasis_assessment", resource_id=assessment.id,
                 detail={"run_id": result["run_id"], "errors": result["errors"], "warnings": result["warnings"]})
    db.commit()
    return result


@router.post("/{assessment_id}/export")
def export_assessment(assessment_id: str, db: Session = Depends(get_db), actor: User = Depends(rn_only)):
    """Produce a flat export of a SIGNED assessment for downstream submission
    tooling. This endpoint does NOT transmit anything anywhere — submission to
    iQIES/payers is intentionally out of scope for automation.
    """
    assessment = db.get(OasisAssessment, assessment_id)
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    if assessment.status not in (OasisStatus.SIGNED, OasisStatus.EXPORTED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a signed assessment can be exported. Complete the RN review workflow first.",
        )
    assessment.status = OasisStatus.EXPORTED
    assessment.exported_at = datetime.now(timezone.utc)
    assessment.exported_by = actor.id
    audit.record(db, action="oasis.exported", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="oasis_assessment", resource_id=assessment.id)
    db.commit()
    return {
        "assessment_id": assessment.id,
        "assessment_type": assessment.assessment_type.value,
        "oasis_version": assessment.oasis_version,
        "signed_by": assessment.signed_by,
        "signed_at": assessment.signed_at.isoformat() if assessment.signed_at else None,
        "items": {r.item_id: r.final_value for r in assessment.items if r.final_value is not None},
        "note": "Export only — transmission to CMS/payer systems must be performed by a human through your submission tool.",
    }
