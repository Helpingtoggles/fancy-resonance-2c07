from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import Role, User
from app.schemas.common import UserCreate, UserOut
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])

admin_only = require_roles()  # admin is implicitly allowed by require_roles


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), actor: User = Depends(admin_only)):
    return db.execute(select(User).order_by(User.created_at)).scalars().all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: User = Depends(admin_only)):
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown role '{body.role}'")
    if db.execute(select(User).where(User.email == body.email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=role,
        credentials=body.credentials,
    )
    db.add(user)
    db.flush()
    audit.record(
        db, action="user.created", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="user", resource_id=user.id,
        detail={"email": user.email, "role": role.value},
    )
    db.commit()
    return user


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(admin_only)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate yourself")
    user.is_active = False
    audit.record(
        db, action="user.deactivated", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="user", resource_id=user.id,
    )
    db.commit()
    return user
