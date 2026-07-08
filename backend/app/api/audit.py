from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.services import audit as audit_service

router = APIRouter(prefix="/audit", tags=["audit"])

audit_roles = require_roles(Role.QA_AUDITOR, Role.RN_REVIEWER)


@router.get("")
def list_audit_entries(
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(audit_roles),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    entries = db.execute(stmt).scalars().all()
    return [
        {
            "id": e.id, "actor_id": e.actor_id, "actor_email": e.actor_email,
            "actor_role": e.actor_role, "action": e.action, "resource_type": e.resource_type,
            "resource_id": e.resource_id, "detail": e.detail, "ip_address": e.ip_address,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "entry_hash": e.entry_hash,
        }
        for e in entries
    ]


@router.get("/verify")
def verify_audit_chain(db: Session = Depends(get_db), user: User = Depends(audit_roles)):
    return audit_service.verify_chain(db)
