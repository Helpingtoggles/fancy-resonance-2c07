"""Wound management: PUSH-style scoring, healing trajectory, staging checks."""

from dataclasses import dataclass

from app.models.clinical import Wound, WoundAssessment

VALID_PRESSURE_STAGES = {"1", "2", "3", "4", "unstageable", "DTI"}


def push_area_score(length_cm: float | None, width_cm: float | None) -> int:
    """PUSH tool sub-score 1: surface area (cm²) mapped to 0-10."""
    if not length_cm or not width_cm:
        return 0
    area = length_cm * width_cm
    brackets = [
        (0.0, 0), (0.3, 1), (0.6, 2), (1.0, 3), (2.0, 4),
        (3.0, 5), (4.0, 6), (8.0, 7), (12.0, 8), (24.0, 9),
    ]
    for upper, score in brackets:
        if area <= upper:
            return score
    return 10


def push_exudate_score(exudate_amount: str | None) -> int:
    return {"none": 0, "light": 1, "moderate": 2, "heavy": 3}.get((exudate_amount or "").lower(), 0)


def push_tissue_score(tissue_type: str | None) -> int:
    return {
        "closed": 0, "epithelial": 1, "granulation": 2, "slough": 3, "eschar": 4, "necrotic": 4,
    }.get((tissue_type or "").lower(), 0)


def compute_push_score(assessment: WoundAssessment) -> int:
    """PUSH total 0 (healed) – 17 (worst)."""
    return (
        push_area_score(assessment.length_cm, assessment.width_cm)
        + push_exudate_score(assessment.exudate_amount)
        + push_tissue_score(assessment.tissue_type)
    )


@dataclass
class WoundCheck:
    check_id: str
    severity: str
    message: str


def validate_wound(wound: Wound) -> list[WoundCheck]:
    checks: list[WoundCheck] = []
    if wound.wound_type == "pressure":
        if not wound.pressure_stage:
            checks.append(WoundCheck("WND-STAGE-001", "error", "Pressure wound requires a stage (1-4, unstageable, DTI)."))
        elif wound.pressure_stage not in VALID_PRESSURE_STAGES:
            checks.append(WoundCheck("WND-STAGE-002", "error",
                                     f"Invalid pressure stage '{wound.pressure_stage}'. Valid: {sorted(VALID_PRESSURE_STAGES)}."))
    elif wound.pressure_stage:
        checks.append(WoundCheck("WND-STAGE-003", "warning",
                                 f"Non-pressure wound ({wound.wound_type}) should not carry a pressure stage."))
    return checks


def healing_trajectory(assessments: list[WoundAssessment]) -> dict:
    """Trend PUSH scores across assessments (chronological)."""
    scored = [
        {"assessed_at": a.assessed_at.isoformat() if a.assessed_at else None,
         "push_score": a.push_score if a.push_score is not None else compute_push_score(a),
         "length_cm": a.length_cm, "width_cm": a.width_cm, "depth_cm": a.depth_cm}
        for a in assessments
    ]
    if len(scored) < 2:
        return {"status": "insufficient_data", "points": scored}
    first, last = scored[0]["push_score"], scored[-1]["push_score"]
    delta = last - first
    if last == 0:
        status = "healed"
    elif delta < 0:
        status = "improving"
    elif delta == 0:
        status = "static"
    else:
        status = "deteriorating"
    return {"status": status, "delta": delta, "points": scored}


def staging_regression_check(wound: Wound, new_stage: str | None) -> list[WoundCheck]:
    """Pressure injuries never 'reverse stage' (NPIAP): a stage-4 ulcer that
    improves is a 'healing stage 4', not a stage 2."""
    checks: list[WoundCheck] = []
    if wound.wound_type != "pressure" or not new_stage:
        return checks
    old, new = wound.pressure_stage, new_stage
    if old and old.isdigit() and new.isdigit() and int(new) < int(old):
        checks.append(WoundCheck(
            "WND-STAGE-004", "error",
            f"Reverse staging is not permitted: wound was stage {old}; document as 'healing stage {old}' "
            "rather than restaging to a lower stage.",
        ))
    return checks
