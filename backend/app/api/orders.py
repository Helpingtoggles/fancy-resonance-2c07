from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.clinical import OrderStatus, PhysicianOrder
from app.models.user import Role, User
from app.schemas.common import OrderStatusUpdate, PhysicianOrderOut
from app.services import audit

router = APIRouter(prefix="/orders", tags=["physician-orders"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN, Role.INTAKE)


@router.get("", response_model=list[PhysicianOrderOut])
def list_orders(episode_id: str | None = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    stmt = select(PhysicianOrder).order_by(PhysicianOrder.created_at.desc()).limit(500)
    if episode_id:
        stmt = stmt.where(PhysicianOrder.episode_id == episode_id)
    return db.execute(stmt).scalars().all()


@router.patch("/{order_id}/status", response_model=PhysicianOrderOut)
def update_order_status(order_id: str, body: OrderStatusUpdate, db: Session = Depends(get_db),
                        actor: User = Depends(clinical_roles)):
    """Track an order through its signature lifecycle.

    Marking an order SIGNED records that the *physician's* signature was
    received (with the date) — the platform itself never signs anything.
    """
    order = db.get(PhysicianOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    try:
        new_status = OrderStatus(body.status)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown status '{body.status}'")
    if new_status == OrderStatus.SIGNED and body.signed_date is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Recording a signed order requires the physician's signature date")
    order.status = new_status
    order.signed_date = body.signed_date
    audit.record(
        db, action="order.status_updated", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="physician_order", resource_id=order.id,
        detail={"status": new_status.value, "signed_date": str(body.signed_date) if body.signed_date else None},
    )
    db.commit()
    return order
