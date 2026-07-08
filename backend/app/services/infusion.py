"""Infusion management: rate math, safety checks, and line-care schedules.

Checks are advisory clinical decision support for the RN — they flag
discrepancies for human review and never modify orders.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.clinical import InfusionAdministration, InfusionOrder

#: Conservative default max rates (mL/hr) by access type for gravity/pump
#: home infusion. Agencies can tune per policy.
MAX_RATE_BY_ACCESS = {
    "PIV": 250.0,
    "midline": 250.0,
    "PICC": 400.0,
    "port": 400.0,
    "central": 400.0,
}

#: Standard flush protocols by access type (saline/heparin, home care norms).
FLUSH_PROTOCOLS = {
    "PIV": "SASH per agency policy: 3 mL 0.9% NaCl before/after each use; site change q72-96h.",
    "midline": "5-10 mL 0.9% NaCl before/after each use; assess site every visit.",
    "PICC": "10 mL 0.9% NaCl before/after use; weekly dressing change and measurement of external length.",
    "port": "10 mL 0.9% NaCl before/after use; heparin 100 units/mL 5 mL to lock; de-access weekly.",
    "central": "10 mL 0.9% NaCl before/after use per agency central-line policy.",
}


def compute_rate_ml_hr(volume_ml: float, duration_minutes: int) -> float:
    if volume_ml <= 0 or duration_minutes <= 0:
        raise ValueError("Volume and duration must be positive.")
    return round(volume_ml / (duration_minutes / 60.0), 2)


def compute_duration_minutes(volume_ml: float, rate_ml_hr: float) -> int:
    if volume_ml <= 0 or rate_ml_hr <= 0:
        raise ValueError("Volume and rate must be positive.")
    return round(volume_ml / rate_ml_hr * 60)


def mcg_kg_min_to_ml_hr(dose_mcg_kg_min: float, weight_kg: float, concentration_mcg_ml: float) -> float:
    """Weight-based continuous infusion conversion."""
    if min(dose_mcg_kg_min, weight_kg, concentration_mcg_ml) <= 0:
        raise ValueError("All inputs must be positive.")
    return round(dose_mcg_kg_min * weight_kg * 60.0 / concentration_mcg_ml, 2)


@dataclass
class InfusionCheck:
    check_id: str
    severity: str  # error | warning | info
    message: str


def check_order(order: InfusionOrder) -> list[InfusionCheck]:
    checks: list[InfusionCheck] = []

    if order.volume_ml and order.duration_minutes and order.rate_ml_hr:
        expected = compute_rate_ml_hr(order.volume_ml, order.duration_minutes)
        if abs(expected - order.rate_ml_hr) > max(1.0, 0.05 * expected):
            checks.append(InfusionCheck(
                "INF-RATE-001", "error",
                f"Ordered rate {order.rate_ml_hr} mL/hr disagrees with volume/duration "
                f"({order.volume_ml} mL over {order.duration_minutes} min = {expected} mL/hr).",
            ))

    max_rate = MAX_RATE_BY_ACCESS.get(order.access_type or "")
    if max_rate and order.rate_ml_hr and order.rate_ml_hr > max_rate:
        checks.append(InfusionCheck(
            "INF-RATE-002", "warning",
            f"Rate {order.rate_ml_hr} mL/hr exceeds the {order.access_type} advisory maximum of {max_rate} mL/hr.",
        ))

    if not order.access_type:
        checks.append(InfusionCheck("INF-ACCESS-001", "warning", "Vascular access type is not documented."))
    if not order.line_flush_protocol:
        suggestion = FLUSH_PROTOCOLS.get(order.access_type or "")
        checks.append(InfusionCheck(
            "INF-FLUSH-001", "info",
            "No flush protocol documented." + (f" Suggested: {suggestion}" if suggestion else ""),
        ))
    if order.end_date and order.start_date and order.end_date < order.start_date:
        checks.append(InfusionCheck("INF-DATE-001", "error", "Infusion end date precedes start date."))
    return checks


def check_administration(order: InfusionOrder, admin: InfusionAdministration) -> list[InfusionCheck]:
    checks: list[InfusionCheck] = []
    if order.rate_ml_hr and admin.actual_rate_ml_hr:
        deviation = abs(admin.actual_rate_ml_hr - order.rate_ml_hr) / order.rate_ml_hr
        if deviation > 0.10:
            checks.append(InfusionCheck(
                "INF-ADMIN-001", "warning",
                f"Administered rate {admin.actual_rate_ml_hr} mL/hr deviates "
                f"{deviation:.0%} from ordered {order.rate_ml_hr} mL/hr.",
            ))
    if not admin.line_patency_confirmed:
        checks.append(InfusionCheck("INF-ADMIN-002", "warning", "Line patency not confirmed before infusion."))
    if not admin.flush_performed:
        checks.append(InfusionCheck("INF-ADMIN-003", "info", "Post-infusion flush not documented."))
    if admin.complications:
        checks.append(InfusionCheck("INF-ADMIN-004", "warning", f"Complications documented: {admin.complications}"))
    return checks


def line_care_schedule(access_type: str, anchor: date, weeks: int = 4) -> list[dict]:
    """Dressing/site-care due dates from an anchor date."""
    interval_days = {"PIV": 3, "midline": 7, "PICC": 7, "port": 7, "central": 7}.get(access_type, 7)
    task = {"PIV": "Site rotation/assessment", "port": "De-access & re-access with sterile technique"}.get(
        access_type, "Dressing change & site assessment"
    )
    schedule = []
    due = anchor
    horizon = anchor + timedelta(weeks=weeks)
    while due <= horizon:
        schedule.append({"due_date": due.isoformat(), "task": task, "access_type": access_type})
        due += timedelta(days=interval_days)
    return schedule
