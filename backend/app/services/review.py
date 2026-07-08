"""RN review workflow.

All AI output (extracted fields, OASIS suggestions, SOC drafts) funnels into
review tasks that a human RN works through:

    pending → in_review → (changes_requested ↔ in_review) → approved → signed

Signing rules (the platform's hardest guarantees live here):
  * Only a human actor may approve or sign (``safety.assert_human_actor``).
  * Only users in ``SIGNING_ROLES`` (RN reviewers) may sign.
  * Signing requires a non-empty attestation.
  * An OASIS assessment may only be signed when it is fully RN-finalized and
    CMS validation reports zero errors.
  * There is deliberately NO bulk-sign, NO auto-advance, and NO scheduled job
    that touches these transitions.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.safety import SafetyViolation, assert_human_actor
from app.models.oasis import OasisAssessment, OasisStatus
from app.models.patient import Episode
from app.models.review import ReviewDecision, ReviewStatus, ReviewTask
from app.models.user import SIGNING_ROLES, User
from app.services import audit, cms_validation
from app.services.oasis_engine import completeness

_TRANSITIONS: dict[str, tuple[ReviewStatus, ReviewStatus]] = {
    # action: (required current status, next status)
    "claim": (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW),
    "request_changes": (ReviewStatus.IN_REVIEW, ReviewStatus.CHANGES_REQUESTED),
    "resume": (ReviewStatus.CHANGES_REQUESTED, ReviewStatus.IN_REVIEW),
    "approve": (ReviewStatus.IN_REVIEW, ReviewStatus.APPROVED),
    "sign": (ReviewStatus.APPROVED, ReviewStatus.SIGNED),
    "cancel": (ReviewStatus.PENDING, ReviewStatus.CANCELLED),
}


class ReviewError(ValueError):
    pass


def act_on_task(
    db: Session,
    *,
    task: ReviewTask,
    actor: User,
    action: str,
    note: str | None = None,
    attestation: str | None = None,
    actor_kind: str = "human",
) -> ReviewTask:
    if action not in _TRANSITIONS:
        raise ReviewError(f"Unknown review action '{action}'.")
    required, target = _TRANSITIONS[action]
    if task.status != required:
        raise ReviewError(f"Cannot '{action}' a task in status '{task.status.value}' (requires '{required.value}').")

    # Approval and signing are human-only, always.
    if action in ("approve", "sign"):
        assert_human_actor(actor_kind, f"review.{action}")

    if action == "sign":
        _enforce_sign_rules(db, task, actor, attestation)

    if action == "claim":
        task.assigned_to = actor.id
    task.status = target
    db.add(
        ReviewDecision(
            task_id=task.id, reviewer_id=actor.id, action=action, note=note, attestation=attestation
        )
    )
    audit.record(
        db, action=f"review.{action}", actor_id=actor.id, actor_email=actor.email,
        actor_role=actor.role.value, resource_type="review_task", resource_id=task.id,
        detail={"subject_type": task.subject_type, "subject_id": task.subject_id, "note": note},
    )

    if action == "sign" and task.subject_type == "oasis_assessment":
        _sign_oasis(db, task.subject_id, actor, attestation)

    db.flush()
    return task


def _enforce_sign_rules(db: Session, task: ReviewTask, actor: User, attestation: str | None) -> None:
    if actor.role not in SIGNING_ROLES:
        raise SafetyViolation(
            f"Role '{actor.role.value}' may not sign documentation. Signing requires an RN reviewer."
        )
    if not attestation or len(attestation.strip()) < 10:
        raise ReviewError(
            "Signing requires an explicit attestation statement (e.g., 'I have reviewed this "
            "assessment and attest to its accuracy.')."
        )
    if task.subject_type == "oasis_assessment":
        assessment = db.get(OasisAssessment, task.subject_id)
        if assessment is None:
            raise ReviewError("OASIS assessment not found for this task.")
        comp = completeness(assessment)
        if not comp["complete"]:
            raise ReviewError(
                f"OASIS assessment is not fully RN-finalized: {len(comp['missing'])} required "
                f"item(s) missing final values ({', '.join(comp['missing'][:8])}…). "
                "Every item must be reviewed by a human before signing."
            )
        episode = db.get(Episode, assessment.episode_id)
        result = cms_validation.validate_assessment(db, assessment, episode)
        errors = [f for f in result if f.severity == "error"]
        if errors:
            raise ReviewError(
                f"CMS validation reports {len(errors)} error(s); resolve before signing. "
                f"First: [{errors[0].rule_id}] {errors[0].message}"
            )


def _sign_oasis(db: Session, assessment_id: str, actor: User, attestation: str | None) -> None:
    assessment = db.get(OasisAssessment, assessment_id)
    assessment.status = OasisStatus.SIGNED
    assessment.signed_by = actor.id
    assessment.signed_at = datetime.now(timezone.utc)
    assessment.attestation = attestation


def open_tasks(db: Session, *, assigned_to: str | None = None) -> list[ReviewTask]:
    stmt = select(ReviewTask).where(
        ReviewTask.status.in_([ReviewStatus.PENDING, ReviewStatus.IN_REVIEW, ReviewStatus.CHANGES_REQUESTED, ReviewStatus.APPROVED])
    )
    if assigned_to:
        stmt = stmt.where(ReviewTask.assigned_to == assigned_to)
    return list(db.execute(stmt.order_by(ReviewTask.created_at.asc())).scalars().all())
