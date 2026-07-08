from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.clinical import InfusionAdministration, InfusionOrder
from app.models.user import Role, User
from app.schemas.common import InfusionAdministrationCreate, InfusionOrderCreate, InfusionOrderOut
from app.services import audit
from app.services import infusion as infusion_service

router = APIRouter(prefix="/infusion", tags=["infusion"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def create_infusion_order(body: InfusionOrderCreate, db: Session = Depends(get_db),
                          actor: User = Depends(clinical_roles)):
    order = InfusionOrder(**body.model_dump())
    if order.rate_ml_hr is None and order.volume_ml and order.duration_minutes:
        order.rate_ml_hr = infusion_service.compute_rate_ml_hr(order.volume_ml, order.duration_minutes)
    db.add(order)
    db.flush()
    checks = infusion_service.check_order(order)
    audit.record(db, action="infusion.order_created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="infusion_order", resource_id=order.id,
                 detail={"checks": len(checks)})
    db.commit()
    return {
        "order": InfusionOrderOut.model_validate(order).model_dump(),
        "checks": [c.__dict__ for c in checks],
    }


@router.get("/orders", response_model=list[InfusionOrderOut])
def list_infusion_orders(episode_id: str | None = None, db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    stmt = select(InfusionOrder).order_by(InfusionOrder.created_at.desc()).limit(200)
    if episode_id:
        stmt = stmt.where(InfusionOrder.episode_id == episode_id)
    return db.execute(stmt).scalars().all()


@router.get("/orders/{order_id}/checks")
def get_order_checks(order_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    order = db.get(InfusionOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Infusion order not found")
    return [c.__dict__ for c in infusion_service.check_order(order)]


@router.get("/orders/{order_id}/line-care-schedule")
def get_line_care_schedule(order_id: str, weeks: int = 4, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    order = db.get(InfusionOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Infusion order not found")
    if not order.access_type:
        raise HTTPException(status.HTTP_409_CONFLICT, "Order has no documented access type")
    anchor = order.start_date or date.today()
    return infusion_service.line_care_schedule(order.access_type, anchor, weeks=min(weeks, 12))


@router.post("/orders/{order_id}/administrations", status_code=status.HTTP_201_CREATED)
def record_administration(order_id: str, body: InfusionAdministrationCreate,
                          db: Session = Depends(get_db), actor: User = Depends(clinical_roles)):
    order = db.get(InfusionOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Infusion order not found")
    admin = InfusionAdministration(infusion_order_id=order.id, administered_by=actor.id, **body.model_dump())
    db.add(admin)
    db.flush()
    checks = infusion_service.check_administration(order, admin)
    audit.record(db, action="infusion.administration_recorded", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="infusion_administration", resource_id=admin.id,
                 detail={"order_id": order.id, "checks": len(checks)})
    db.commit()
    return {"administration_id": admin.id, "checks": [c.__dict__ for c in checks]}
