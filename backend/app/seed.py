"""Development/demo seed data.

Usage:  python -m app.seed
Creates role-per-user demo accounts (password from HHRN_SEED_PASSWORD, default
'ChangeMe-Demo-1234'), a sample patient/episode, and the standard SOC intake
workflow definition. Idempotent: safe to re-run.
"""

import os
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.patient import Episode, Patient
from app.models.user import Role, User
from app.models.workflow import WorkflowDefinition
from app.services import workflow_dsl

SOC_INTAKE_DSL = """workflow soc_intake v1
state referral_received initial
  on documents_uploaded -> awaiting_extraction

state awaiting_extraction
  on extraction_complete when ctx.meds_extracted >= 1 -> pending_rn_review
  on extraction_complete -> pending_manual_entry

state pending_rn_review
  require role rn_reviewer
  do create_review_task "Reconcile extracted medications and orders"
  on review_approved -> ready_for_soc_visit

state pending_manual_entry
  on manual_entry_complete -> pending_rn_review

state ready_for_soc_visit terminal
"""

DEMO_USERS = [
    ("admin@example-agency.com", "Ada Admin", Role.ADMIN, None),
    ("rn@example-agency.com", "Riley Nguyen, RN", Role.RN_REVIEWER, "RN"),
    ("clinician@example-agency.com", "Casey Lopez, RN", Role.CLINICIAN, "RN"),
    ("intake@example-agency.com", "Ivy Torres", Role.INTAKE, None),
    ("auditor@example-agency.com", "Quinn Adebayo", Role.QA_AUDITOR, None),
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    password = os.environ.get("HHRN_SEED_PASSWORD", "ChangeMe-Demo-1234")
    db = SessionLocal()
    try:
        for email, name, role, creds in DEMO_USERS:
            if not db.execute(select(User).where(User.email == email)).scalar_one_or_none():
                db.add(User(email=email, hashed_password=hash_password(password),
                            full_name=name, role=role, credentials=creds))
                print(f"created user {email} ({role.value})")

        if not db.execute(select(Patient).where(Patient.mrn == "DEMO-0001")).scalar_one_or_none():
            patient = Patient(
                mrn="DEMO-0001", first_name="Edna", last_name="Rivera",
                date_of_birth=date(1948, 3, 12), sex="F", payer="Medicare",
                primary_physician="Dr. Amara Okafor",
            )
            db.add(patient)
            db.flush()
            soc = date.today() + timedelta(days=3)
            db.add(Episode(
                patient_id=patient.id, referral_date=date.today(), soc_date=soc,
                cert_period_start=soc, cert_period_end=soc + timedelta(days=59),
                primary_diagnosis="CHF exacerbation", primary_diagnosis_code="I50.23",
                referring_physician="Dr. Amara Okafor",
                face_to_face_date=date.today() - timedelta(days=7),
                homebound_narrative=(
                    "Patient requires considerable and taxing effort to leave home due to "
                    "dyspnea on exertion at less than 20 feet; uses rolling walker with standby assist."
                ),
            ))
            print("created demo patient DEMO-0001 with episode")

        existing = db.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.name == "soc_intake")
        ).scalar_one_or_none()
        if not existing:
            workflow_dsl.create_definition(db, source=SOC_INTAKE_DSL, created_by=None)
            print("created soc_intake workflow definition")

        db.commit()
        print(f"seed complete (demo password: {'from HHRN_SEED_PASSWORD' if 'HHRN_SEED_PASSWORD' in os.environ else password})")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
