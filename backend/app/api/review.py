from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.safety import SafetyViolation
from app.models.review import ReviewTask
from app.models.user import Role, User
from app.schemas.common import ReviewActionRequest, ReviewTaskOut
from app.services import review as review_service

router = APIRouter(prefix="/review", tags=["review"])

reviewer_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.get("/tasks", response_model=list[ReviewTaskOut])
def list_tasks(mine: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return review_service.open_tasks(db, assigned_to=user.id if mine else None)


@router.get("/tasks/{task_id}", response_model=ReviewTaskOut)
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review task not found")
    return task


@router.post("/tasks/{task_id}/act", response_model=ReviewTaskOut)
def act(task_id: str, body: ReviewActionRequest, db: Session = Depends(get_db),
        actor: User = Depends(reviewer_roles)):
    """Advance a review task: claim, request_changes, resume, approve, sign, cancel.

    Signing is restricted to RN reviewers, requires an attestation, and — for
    OASIS subjects — requires full RN finalization and clean CMS validation.
    """
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review task not found")
    try:
        task = review_service.act_on_task(
            db, task=task, actor=actor, action=body.action,
            note=body.note, attestation=body.attestation,
        )
    except SafetyViolation as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except review_service.ReviewError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.commit()
    return task
