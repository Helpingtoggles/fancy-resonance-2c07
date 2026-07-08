import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    ADMIN = "admin"
    RN_REVIEWER = "rn_reviewer"      # RN with sign-off authority
    CLINICIAN = "clinician"          # field RN / therapist documenting visits
    INTAKE = "intake_coordinator"    # uploads referrals, manages documents
    QA_AUDITOR = "qa_auditor"        # read-only + audit access
    READONLY = "readonly"


#: Roles permitted to write *final* values / sign documentation.
SIGNING_ROLES = {Role.RN_REVIEWER}
#: Roles permitted to edit clinical data.
CLINICAL_WRITE_ROLES = {Role.ADMIN, Role.RN_REVIEWER, Role.CLINICIAN}
#: Roles permitted to ingest documents.
INGEST_ROLES = {Role.ADMIN, Role.RN_REVIEWER, Role.CLINICIAN, Role.INTAKE}


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.READONLY)
    credentials: Mapped[str | None] = mapped_column(String(64), default=None)  # e.g. "RN", "LVN"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
