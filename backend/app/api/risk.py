from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.patient import Episode
from app.models.risk import DenialRiskFinding, ValidationFinding
from app.models.user import User
from app.services import audit, denial_risk

router = APIRouter(tags=["risk"])


@router.post("/episodes/{episode_id}/denial-risk")
def run_denial_risk(episode_id: str, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
    result = denial_risk.run_and_persist(db, episode)
    audit.record(db, action="denial_risk.assessed", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="episode", resource_id=episode.id,
                 detail={"run_id": result["run_id"], "score": result["score"], "level": result["level"]})
    db.commit()
    return result


@router.get("/episodes/{episode_id}/denial-risk")
def get_denial_risk_findings(episode_id: str, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    findings = db.execute(
        select(DenialRiskFinding).where(DenialRiskFinding.episode_id == episode_id)
        .order_by(DenialRiskFinding.created_at.desc()).limit(100)
    ).scalars().all()
    return [
        {"id": f.id, "rule_id": f.rule_id, "risk_level": f.risk_level, "weight": f.weight,
         "rationale": f.rationale, "remediation": f.remediation, "run_id": f.run_id,
         "created_at": f.created_at.isoformat() if f.created_at else None}
        for f in findings
    ]


@router.get("/assessments/{assessment_id}/validation-findings")
def get_validation_findings(assessment_id: str, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    findings = db.execute(
        select(ValidationFinding).where(ValidationFinding.assessment_id == assessment_id)
        .order_by(ValidationFinding.created_at.desc()).limit(200)
    ).scalars().all()
    return [
        {"id": f.id, "rule_id": f.rule_id, "severity": f.severity, "message": f.message,
         "item_ids": f.item_ids, "run_id": f.run_id,
         "created_at": f.created_at.isoformat() if f.created_at else None}
        for f in findings
    ]
