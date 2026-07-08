"""Test fixtures: in-memory SQLite DB, app client, and role-based users.

The full stack runs against SQLite so the suite needs no external services;
PostgreSQL-specific behavior is limited to connection pooling.
"""

import os
import tempfile

os.environ.setdefault("HHRN_DATABASE_URL", "sqlite://")
os.environ.setdefault("HHRN_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("HHRN_STORAGE_DIR", tempfile.mkdtemp(prefix="hhrn-storage-"))
os.environ.setdefault("HHRN_OCR_ENGINE", "stub")
os.environ.setdefault("HHRN_TRANSCRIPTION_ENGINE", "stub")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.database as database
from app.core.database import Base

# Single shared in-memory database across all sessions in a test.
_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
database.engine = _engine
database.SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

import app.core.security as security  # noqa: E402

# Keep the production PBKDF2 work factor out of the test loop (verify_password
# reads the iteration count from the stored hash, so this only affects test users).
security._PBKDF2_ITERATIONS = 1_000

from app import models as _all_models  # noqa: F401,E402  (register all tables)
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import Role, User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield


@pytest.fixture
def db():
    session = database.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


PASSWORD = "correct-horse-battery"


def make_user(db, role: Role, email: str | None = None) -> User:
    user = User(
        email=email or f"{role.value}@agency-example.com",
        hashed_password=hash_password(PASSWORD),
        full_name=f"Test {role.value}",
        role=role,
        credentials="RN" if role in (Role.RN_REVIEWER, Role.CLINICIAN) else None,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def users(db):
    return {role: make_user(db, role) for role in Role}


def auth_headers(client, email: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def rn_headers(client, users):
    return auth_headers(client, users[Role.RN_REVIEWER].email)


@pytest.fixture
def clinician_headers(client, users):
    return auth_headers(client, users[Role.CLINICIAN].email)


@pytest.fixture
def intake_headers(client, users):
    return auth_headers(client, users[Role.INTAKE].email)


@pytest.fixture
def admin_headers(client, users):
    return auth_headers(client, users[Role.ADMIN].email)


@pytest.fixture
def readonly_headers(client, users):
    return auth_headers(client, users[Role.READONLY].email)


@pytest.fixture
def auditor_headers(client, users):
    return auth_headers(client, users[Role.QA_AUDITOR].email)


@pytest.fixture
def patient_episode(client, rn_headers):
    """A patient with an active episode, created through the API."""
    patient = client.post("/api/v1/patients", headers=rn_headers, json={
        "mrn": "MRN-0001", "first_name": "Edna", "last_name": "Rivera",
        "date_of_birth": "1948-03-12", "payer": "Medicare",
    }).json()
    episode = client.post("/api/v1/episodes", headers=rn_headers, json={
        "patient_id": patient["id"],
        "referral_date": "2026-06-20",
        "soc_date": "2026-06-25",
        "cert_period_start": "2026-06-25",
        "cert_period_end": "2026-08-23",
        "primary_diagnosis": "CHF exacerbation",
        "primary_diagnosis_code": "I50.23",
        "referring_physician": "Dr. Amara Okafor",
        "face_to_face_date": "2026-06-18",
        "homebound_narrative": (
            "Patient requires considerable and taxing effort to leave home due to dyspnea "
            "on exertion at less than 20 feet, requires a rolling walker and standby assist."
        ),
    }).json()
    return patient, episode


REFERRAL_TEXT = """Referral Summary — Mercy General Hospital
Patient: Edna Rivera   DOB: 03/12/1948   MRN: MRN-0001
Discharged from hospital inpatient stay on 06/22/2026 s/p CHF exacerbation.
Height: 63 inches   Weight: 172 lbs
Treated for urinary tract infection during admission.

Current Medications:
1. Furosemide 40 mg PO BID
2. Metoprolol succinate 25 mg PO daily
3. Warfarin 5 mg PO daily
4. Insulin glargine 20 units SubQ at bedtime
5. Acetaminophen 500 mg 1 tablet PO q6h PRN for pain

Orders:
SN 2wk9 for CHF management and medication teaching
PT eval and treat
Wound care: dressing change to left heel daily
Verbal order received from Dr. Amara Okafor, MD  NPI: 1234567890  06/24/2026
Cert period: 06/25/2026 to 08/23/2026
"""


def upload_referral(client, headers, patient_id: str, episode_id: str, text: str = REFERRAL_TEXT):
    resp = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("referral.txt", text.encode(), "text/plain")},
        data={"kind": "referral", "patient_id": patient_id, "episode_id": episode_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
