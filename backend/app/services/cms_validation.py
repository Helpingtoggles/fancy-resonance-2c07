"""CMS/OASIS-E2 validation.

Rule engine over an assessment's items (final values where present, else
suggested values flagged as unreviewed) plus episode context. Severities:

  * ``error``   — would be rejected by iQIES / blocks signing
  * ``warning`` — likely to draw review or cause downstream denial
  * ``info``    — advisory

Each run gets a run_id; findings are persisted for the UI and history.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.oasis import OasisAssessment
from app.models.patient import Episode
from app.models.risk import ValidationFinding
from app.services.oasis_catalog import ITEMS_BY_ID

VALIDATOR_VERSION = "e2-rules/1.0"


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    item_ids: list[str]


def _value(responses: dict, item_id: str) -> str | None:
    r = responses.get(item_id)
    if r is None:
        return None
    return r.final_value if r.final_value is not None else r.suggested_value


def validate_assessment(db: Session, assessment: OasisAssessment, episode: Episode | None) -> list[Finding]:
    responses = {r.item_id: r for r in assessment.items}
    findings: list[Finding] = []
    add = lambda rid, sev, msg, items: findings.append(Finding(rid, sev, msg, items))  # noqa: E731

    # --- Domain checks: every answered item must be within its value domain ---
    for item_id, r in responses.items():
        item = ITEMS_BY_ID.get(item_id)
        if item is None or not item.values:
            continue
        for label, val in (("final", r.final_value), ("suggested", r.suggested_value)):
            if val is not None and item.value_type == "code" and val not in item.values:
                add("E2-DOMAIN-001", "error",
                    f"{item_id}: {label} value '{val}' outside allowed domain {list(item.values)}", [item_id])

    # --- Completeness: required, non-skipped items need a final value ---
    missing = [
        r.item_id for r in assessment.items
        if not r.skipped and (i := ITEMS_BY_ID.get(r.item_id)) and i.required and r.final_value is None
    ]
    if missing:
        add("E2-COMPLETE-001", "error",
            f"{len(missing)} required item(s) lack an RN-finalized value: {', '.join(sorted(missing)[:10])}"
            + ("…" if len(missing) > 10 else ""), sorted(missing))

    # --- Unreviewed AI suggestions ---
    unreviewed = [r.item_id for r in assessment.items if r.suggested_value is not None and r.final_value is None and not r.skipped]
    if unreviewed:
        add("E2-REVIEW-001", "warning",
            f"{len(unreviewed)} item(s) have AI suggestions awaiting RN review: {', '.join(sorted(unreviewed))}",
            sorted(unreviewed))

    # --- Cross-item consistency ---
    m1306 = _value(responses, "M1306")
    if m1306 == "0":
        for gated in ("M1311", "M1324"):
            gv = _value(responses, gated)
            if gv not in (None, "NA") and not (responses.get(gated) and responses[gated].skipped):
                add("E2-SKIP-1306", "error",
                    f"{gated} answered '{gv}' but M1306=0 (no stage-2+ pressure ulcer) — skip logic violated",
                    ["M1306", gated])
    m1340 = _value(responses, "M1340")
    m1342 = _value(responses, "M1342")
    if m1340 == "0" and m1342 is not None and not (responses.get("M1342") and responses["M1342"].skipped):
        add("E2-SKIP-1340", "error", "M1342 answered but M1340=0 (no surgical wound)", ["M1340", "M1342"])

    m2001 = _value(responses, "M2001")
    m2003 = _value(responses, "M2003")
    if m2001 == "1" and m2003 is None:
        add("E2-DRR-001", "error",
            "M2001 indicates potential clinically significant medication issues but M2003 (physician "
            "contact within 1 calendar day) is unanswered", ["M2001", "M2003"])
    if m2001 == "0" and m2003 is not None and not (responses.get("M2003") and responses["M2003"].skipped):
        add("E2-DRR-002", "warning", "M2003 answered but M2001 reports no issues found", ["M2001", "M2003"])

    # --- Plausibility ---
    def _num(item_id: str) -> float | None:
        v = _value(responses, item_id)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    height = _num("M1060A")
    if height is not None and not (30 <= height <= 90):
        add("E2-PLAUS-HT", "warning", f"M1060A height {height} in is outside plausible range 30–90", ["M1060A"])
    weight = _num("M1060B")
    if weight is not None and not (50 <= weight <= 700):
        add("E2-PLAUS-WT", "warning", f"M1060B weight {weight} lb is outside plausible range 50–700", ["M1060B"])

    # --- M0090 date sanity ---
    m0090 = _value(responses, "M0090")
    if m0090:
        try:
            completed = date.fromisoformat(m0090)
            if completed > date.today():
                add("E2-DATE-M0090", "error", "M0090 assessment completion date is in the future", ["M0090"])
            if episode and episode.soc_date and assessment.assessment_type.value == "start_of_care":
                delta = (completed - episode.soc_date).days
                if not (0 <= delta <= 5):
                    add("E2-DATE-SOC5", "error",
                        f"SOC comprehensive assessment must be completed within 5 days of SOC "
                        f"(M0090 is {delta} days from SOC date)", ["M0090"])
        except ValueError:
            add("E2-DATE-FMT", "error", f"M0090 '{m0090}' is not an ISO date (YYYY-MM-DD)", ["M0090"])

    # --- Episode-level context ---
    if episode:
        if not episode.primary_diagnosis_code:
            add("EP-DX-001", "warning", "Episode lacks a primary diagnosis ICD-10 code (M1021 support)", ["M1021"])
        if episode.cert_period_start and episode.cert_period_end:
            span = (episode.cert_period_end - episode.cert_period_start).days
            if span > 60:
                add("EP-CERT-001", "error", f"Certification period spans {span} days (maximum 60)", [])

    return findings


def run_and_persist(db: Session, assessment: OasisAssessment, episode: Episode | None) -> dict:
    run_id = str(uuid.uuid4())
    findings = validate_assessment(db, assessment, episode)
    for f in findings:
        db.add(
            ValidationFinding(
                assessment_id=assessment.id, rule_id=f.rule_id, severity=f.severity,
                message=f.message, item_ids=f.item_ids, run_id=run_id,
            )
        )
    db.flush()
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    return {
        "run_id": run_id,
        "validator": VALIDATOR_VERSION,
        "errors": errors,
        "warnings": warnings,
        "clean": errors == 0,
        "findings": [f.__dict__ for f in findings],
    }
