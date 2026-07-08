from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.clinical import Medication, MedicationStatus
from app.models.user import Role, User
from app.schemas.common import MedicationOut, MedicationUpdate
from app.services import audit, fdb

router = APIRouter(prefix="/medications", tags=["medications"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.get("", response_model=list[MedicationOut])
def list_medications(
    episode_id: str | None = None,
    patient_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Medication).order_by(Medication.created_at.desc()).limit(500)
    if episode_id:
        stmt = stmt.where(Medication.episode_id == episode_id)
    if patient_id:
        stmt = stmt.where(Medication.patient_id == patient_id)
    return db.execute(stmt).scalars().all()


@router.patch("/{medication_id}", response_model=MedicationOut)
def update_medication(medication_id: str, body: MedicationUpdate, db: Session = Depends(get_db),
                      actor: User = Depends(clinical_roles)):
    """RN reconciliation: correct fields and/or move status (e.g. extracted → active)."""
    med = db.get(Medication, medication_id)
    if med is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Medication not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        try:
            changes["status"] = MedicationStatus(changes["status"])
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown status '{changes['status']}'")
    for key, value in changes.items():
        setattr(med, key, value)
    audit.record(
        db, action="medication.updated", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="medication", resource_id=med.id,
        detail={"fields": sorted(changes.keys())},
    )
    db.commit()
    return med


@router.post("/{medication_id}/prepare-fdb", response_model=MedicationOut)
def prepare_fdb(medication_id: str, db: Session = Depends(get_db), actor: User = Depends(clinical_roles)):
    """Normalize this medication into an FDB screening payload."""
    med = db.get(Medication, medication_id)
    if med is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Medication not found")
    fdb.prepare_medication(med)
    audit.record(db, action="medication.fdb_prepared", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="medication", resource_id=med.id)
    db.commit()
    return med


@router.post("/screen")
def screen_medications(episode_id: str, db: Session = Depends(get_db), actor: User = Depends(clinical_roles)):
    """Run FDB screening over an episode's prepared medications.

    With the default NullFdbClient this reports that screening is not
    configured instead of fabricating results.
    """
    meds = db.execute(select(Medication).where(Medication.episode_id == episode_id)).scalars().all()
    payloads = []
    for med in meds:
        if med.fdb_payload is None:
            fdb.prepare_medication(med)
        payloads.append(med.fdb_payload)
    db.commit()
    client = fdb.get_fdb_client()
    return client.screen(payloads)
