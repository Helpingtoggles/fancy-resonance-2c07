"""Hash-chained audit logging.

Every state-changing operation calls :func:`record`. Entries are chained with
SHA-256 (``entry_hash = sha256(prev_hash || canonical_json)``), making the log
tamper-evident: :func:`verify_chain` recomputes hashes over the full log.
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog

_GENESIS = "0" * 64


def _canonical(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(prev_hash: str, payload: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode()).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    actor_id: str | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.entry_hash if last else _GENESIS
    entry = AuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail=detail,
        ip_address=ip_address,
        prev_hash=prev_hash,
        entry_hash="",
    )
    payload = {
        "actor_id": entry.actor_id,
        "actor_email": entry.actor_email,
        "actor_role": entry.actor_role,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "detail": entry.detail,
        "ip_address": entry.ip_address,
    }
    entry.entry_hash = _compute_hash(prev_hash, payload)
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> dict:
    """Recompute the whole chain; returns {'valid': bool, 'entries': n, 'first_invalid_id': id|None}."""
    entries = db.execute(select(AuditLog).order_by(AuditLog.id.asc())).scalars().all()
    prev_hash = _GENESIS
    for e in entries:
        payload = {
            "actor_id": e.actor_id,
            "actor_email": e.actor_email,
            "actor_role": e.actor_role,
            "action": e.action,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "detail": e.detail,
            "ip_address": e.ip_address,
        }
        if e.prev_hash != prev_hash or e.entry_hash != _compute_hash(prev_hash, payload):
            return {"valid": False, "entries": len(entries), "first_invalid_id": e.id}
        prev_hash = e.entry_hash
    return {"valid": True, "entries": len(entries), "first_invalid_id": None}
