from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.safety import SafetyViolation
from app.models.user import Role, User
from app.models.workflow import WorkflowDefinition, WorkflowInstance
from app.schemas.common import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionOut,
    WorkflowEventRequest,
    WorkflowInstanceOut,
    WorkflowStartRequest,
)
from app.services import audit, workflow_dsl

router = APIRouter(prefix="/workflows", tags=["workflows"])

author_roles = require_roles(Role.RN_REVIEWER)  # + admin implicitly
operate_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN, Role.INTAKE)


@router.post("/definitions", response_model=WorkflowDefinitionOut, status_code=status.HTTP_201_CREATED)
def create_definition(body: WorkflowDefinitionCreate, db: Session = Depends(get_db),
                      actor: User = Depends(author_roles)):
    try:
        definition = workflow_dsl.create_definition(db, source=body.dsl_source, created_by=actor.id)
    except SafetyViolation as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except workflow_dsl.DslError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"DSL error: {exc}")
    audit.record(db, action="workflow.definition_created", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="workflow_definition", resource_id=definition.id,
                 detail={"name": definition.name, "version": definition.version})
    db.commit()
    return definition


@router.get("/definitions", response_model=list[WorkflowDefinitionOut])
def list_definitions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.is_active.is_(True))
        .order_by(WorkflowDefinition.name, WorkflowDefinition.version.desc())
    ).scalars().all()


@router.post("/instances", response_model=WorkflowInstanceOut, status_code=status.HTTP_201_CREATED)
def start_instance(body: WorkflowStartRequest, db: Session = Depends(get_db),
                   actor: User = Depends(operate_roles)):
    definition = db.get(WorkflowDefinition, body.definition_id)
    if definition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow definition not found")
    instance = workflow_dsl.start_instance(
        db, definition=definition, subject_type=body.subject_type,
        subject_id=body.subject_id, context=body.context,
    )
    audit.record(db, action="workflow.instance_started", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="workflow_instance", resource_id=instance.id,
                 detail={"definition": definition.name})
    db.commit()
    return instance


@router.get("/instances", response_model=list[WorkflowInstanceOut])
def list_instances(subject_id: str | None = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    stmt = select(WorkflowInstance).order_by(WorkflowInstance.created_at.desc()).limit(200)
    if subject_id:
        stmt = stmt.where(WorkflowInstance.subject_id == subject_id)
    return db.execute(stmt).scalars().all()


@router.post("/instances/{instance_id}/events", response_model=WorkflowInstanceOut)
def send_event(instance_id: str, body: WorkflowEventRequest, db: Session = Depends(get_db),
               actor: User = Depends(operate_roles)):
    instance = db.get(WorkflowInstance, instance_id)
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow instance not found")
    definition = db.get(WorkflowDefinition, instance.definition_id)
    try:
        instance = workflow_dsl.send_event(
            db, instance=instance, definition=definition, event=body.event,
            actor_id=actor.id, actor_role=actor.role.value, actor_kind="human",
            context_updates=body.context_updates,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except SafetyViolation as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except workflow_dsl.DslError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.commit()
    return instance
