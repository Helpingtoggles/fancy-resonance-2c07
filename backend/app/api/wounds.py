from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.clinical import Wound, WoundAssessment
from app.models.user import Role, User
from app.schemas.common import WoundAssessmentCreate, WoundAssessmentOut, WoundCreate, WoundOut
from app.services import audit
from app.services import wounds as wound_service

router = APIRouter(prefix="/wounds", tags=["wounds"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_wound(body: WoundCreate, db: Session = Depends(get_db), actor: User = Depends(clinical_roles)):
    wound = Wound(**body.model_dump())
    checks = wound_service.validate_wound(wound)
    errors = [c for c in checks if c.severity == "error"]
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, errors[0].message)
    db.add(wound)
    db.flush()
    audit.record(db, action="wound.created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="wound", resource_id=wound.id)
    db.commit()
    return {"wound": WoundOut.model_validate(wound).model_dump(),
            "checks": [c.__dict__ for c in checks]}


@router.get("", response_model=list[WoundOut])
def list_wounds(patient_id: str | None = None, episode_id: str | None = None,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Wound).order_by(Wound.created_at.desc()).limit(200)
    if patient_id:
        stmt = stmt.where(Wound.patient_id == patient_id)
    if episode_id:
        stmt = stmt.where(Wound.episode_id == episode_id)
    return db.execute(stmt).scalars().all()


@router.post("/{wound_id}/assessments", status_code=status.HTTP_201_CREATED)
def create_assessment(wound_id: str, body: WoundAssessmentCreate, db: Session = Depends(get_db),
                      actor: User = Depends(clinical_roles)):
    wound = db.get(Wound, wound_id)
    if wound is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wound not found")
    assessment = WoundAssessment(wound_id=wound.id, assessed_by=actor.id, **body.model_dump())
    assessment.push_score = wound_service.compute_push_score(assessment)
    db.add(assessment)
    db.flush()
    audit.record(db, action="wound.assessed", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="wound_assessment", resource_id=assessment.id,
                 detail={"wound_id": wound.id, "push_score": assessment.push_score})
    db.commit()
    return {"assessment": WoundAssessmentOut.model_validate(assessment).model_dump(mode="json"),
            "push_score": assessment.push_score}


@router.get("/{wound_id}/assessments", response_model=list[WoundAssessmentOut])
def list_assessments(wound_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(
        select(WoundAssessment).where(WoundAssessment.wound_id == wound_id)
        .order_by(WoundAssessment.assessed_at.asc())
    ).scalars().all()


@router.get("/{wound_id}/trajectory")
def get_trajectory(wound_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wound = db.get(Wound, wound_id)
    if wound is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wound not found")
    return wound_service.healing_trajectory(wound.assessments)


@router.post("/{wound_id}/restage")
def restage_wound(wound_id: str, new_stage: str, db: Session = Depends(get_db),
                  actor: User = Depends(clinical_roles)):
    wound = db.get(Wound, wound_id)
    if wound is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Wound not found")
    checks = wound_service.staging_regression_check(wound, new_stage)
    errors = [c for c in checks if c.severity == "error"]
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, errors[0].message)
    old = wound.pressure_stage
    wound.pressure_stage = new_stage
    audit.record(db, action="wound.restaged", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="wound", resource_id=wound.id,
                 detail={"from": old, "to": new_stage})
    db.commit()
    return {"wound_id": wound.id, "pressure_stage": wound.pressure_stage}
