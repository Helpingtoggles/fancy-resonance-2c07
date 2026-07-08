from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.patient import Episode, EpisodeStatus, Patient
from app.models.user import Role, User
from app.schemas.common import (
    EpisodeCreate,
    EpisodeOut,
    EpisodeUpdate,
    PatientCreate,
    PatientOut,
)
from app.services import audit

router = APIRouter(tags=["patients"])

clinical_write = require_roles(Role.RN_REVIEWER, Role.CLINICIAN, Role.INTAKE)


@router.get("/patients", response_model=list[PatientOut])
def list_patients(q: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Patient).order_by(Patient.last_name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Patient.last_name.ilike(like) | Patient.first_name.ilike(like) | Patient.mrn.ilike(like))
    return db.execute(stmt.limit(200)).scalars().all()


@router.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(body: PatientCreate, db: Session = Depends(get_db), actor: User = Depends(clinical_write)):
    if db.execute(select(Patient).where(Patient.mrn == body.mrn)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"MRN '{body.mrn}' already exists")
    patient = Patient(**body.model_dump())
    db.add(patient)
    db.flush()
    audit.record(db, action="patient.created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="patient", resource_id=patient.id,
                 detail={"mrn": patient.mrn})
    db.commit()
    return patient


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    return patient


@router.get("/patients/{patient_id}/episodes", response_model=list[EpisodeOut])
def list_patient_episodes(patient_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(
        select(Episode).where(Episode.patient_id == patient_id).order_by(Episode.created_at.desc())
    ).scalars().all()


@router.post("/episodes", response_model=EpisodeOut, status_code=status.HTTP_201_CREATED)
def create_episode(body: EpisodeCreate, db: Session = Depends(get_db), actor: User = Depends(clinical_write)):
    if db.get(Patient, body.patient_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    episode = Episode(**body.model_dump())
    db.add(episode)
    db.flush()
    audit.record(db, action="episode.created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="episode", resource_id=episode.id)
    db.commit()
    return episode


@router.get("/episodes/{episode_id}", response_model=EpisodeOut)
def get_episode(episode_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
    return episode


@router.patch("/episodes/{episode_id}", response_model=EpisodeOut)
def update_episode(episode_id: str, body: EpisodeUpdate, db: Session = Depends(get_db),
                   actor: User = Depends(clinical_write)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        try:
            changes["status"] = EpisodeStatus(changes["status"])
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown status '{changes['status']}'")
    for key, value in changes.items():
        setattr(episode, key, value)
    audit.record(db, action="episode.updated", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="episode", resource_id=episode.id,
                 detail={"fields": sorted(changes.keys())})
    db.commit()
    return episode
