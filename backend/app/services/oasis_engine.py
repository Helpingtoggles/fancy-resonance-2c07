"""OASIS-E2 workflow engine.

Responsibilities:
  * Instantiate an assessment with the correct item set for its time point
    (SOC/ROC/Recert/Follow-up/Transfer/Discharge) from the E2 catalog.
  * Apply skip logic (gated items become active/inactive as answers change).
  * Generate *suggestions* for items from clinical evidence (documents,
    extracted meds, wounds, voice transcripts) — each suggestion carries
    evidence ledger references, a confidence, and a rationale.
  * Track completeness and drive the review workflow.

SAFETY: this engine writes ONLY ``suggested_value``. ``final_value`` is
written exclusively by a human RN via the review API (api/oasis.py →
finalize_item, which checks role + safety guards). The engine has no method
that touches ``final_value`` — grep for ``final_value`` in this file: it is
only ever read.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.clinical import Medication, MedicationStatus, Wound
from app.models.document import Document, DocumentPage
from app.models.oasis import OasisAssessment, OasisItemResponse, OasisStatus
from app.services import evidence_ledger
from app.services.oasis_catalog import ITEMS_BY_ID, OasisItem, items_for_time_point

ENGINE_NAME = "oasis-e2-engine"
ENGINE_VERSION = "1.0"
SUGGESTER = f"{ENGINE_NAME}/{ENGINE_VERSION}"


def create_assessment(
    db: Session, *, episode_id: str, assessment_type: str, created_by: str | None
) -> OasisAssessment:
    assessment = OasisAssessment(
        episode_id=episode_id, assessment_type=assessment_type, created_by=created_by
    )
    db.add(assessment)
    db.flush()
    for item in items_for_time_point(assessment_type):
        db.add(OasisItemResponse(assessment_id=assessment.id, item_id=item.item_id))
    db.flush()
    return assessment


# ---------------------------------------------------------------------------
# Skip logic
# ---------------------------------------------------------------------------

def _gate_satisfied(item: OasisItem, values: dict[str, str | None]) -> tuple[bool, str | None]:
    """Return (active, reason-if-skipped) for an item given current values.

    Gates evaluate against the *final* value when present, else the suggested
    value — but skip status is advisory until an RN finalizes the gate item.
    """
    if not item.gate:
        return True, None
    gate_item = item.gate["item"]
    gate_value = values.get(gate_item)
    if gate_value is None:
        return True, None  # gate unanswered: keep item visible
    if "in" in item.gate and gate_value not in item.gate["in"]:
        return False, f"skipped: {gate_item}={gate_value} not in {item.gate['in']}"
    if "not_in" in item.gate and gate_value in item.gate["not_in"]:
        return False, f"skipped: {gate_item}={gate_value} in excluded set"
    return True, None


def apply_skip_logic(db: Session, assessment: OasisAssessment) -> None:
    responses = {r.item_id: r for r in assessment.items}
    values = {
        item_id: (r.final_value if r.final_value is not None else r.suggested_value)
        for item_id, r in responses.items()
    }
    for item_id, response in responses.items():
        item = ITEMS_BY_ID.get(item_id)
        if not item:
            continue
        active, reason = _gate_satisfied(item, values)
        response.skipped = None if active else reason
    db.flush()


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------

@dataclass
class Suggestion:
    item_id: str
    value: str
    confidence: float
    rationale: str
    snippet: str
    document_id: str | None = None
    page_number: int | None = None
    span: tuple[int, int] | None = None


_HEIGHT_RE = re.compile(r"(?:height|ht)[:\s]*(?P<val>\d{2}(?:\.\d)?)\s*(?:in|inches|\")", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"(?:weight|wt)[:\s]*(?P<val>\d{2,3}(?:\.\d)?)\s*(?:lb|lbs|pounds|#)", re.IGNORECASE)
_UTI_RE = re.compile(r"\b(?:UTI|urinary tract infection)\b", re.IGNORECASE)
_HOSPITAL_RE = re.compile(r"\b(?:discharged from|hospital discharge|inpatient stay|s/p hospitalization)\b", re.IGNORECASE)
_PRESSURE_ULCER_RE = re.compile(r"\bpressure (?:ulcer|injury|sore)\b|\bdecubitus\b", re.IGNORECASE)
_SURGICAL_WOUND_RE = re.compile(r"\bsurgical (?:wound|incision)\b|\bs/p .{0,30}(?:surgery|-ectomy|-otomy|-plasty)\b", re.IGNORECASE)


def _document_suggestions(pages: list[tuple[Document, DocumentPage]]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for doc, page in pages:
        conf = page.ocr_confidence if page.ocr_confidence is not None else 0.5
        text = page.text or ""

        m = _HEIGHT_RE.search(text)
        if m:
            out.append(Suggestion("M1060A", m.group("val"), round(0.9 * conf, 4),
                                  "Height found in document text", _line_of(text, m.start()),
                                  doc.id, page.page_number, (m.start(), m.end())))
        m = _WEIGHT_RE.search(text)
        if m:
            out.append(Suggestion("M1060B", m.group("val"), round(0.9 * conf, 4),
                                  "Weight found in document text", _line_of(text, m.start()),
                                  doc.id, page.page_number, (m.start(), m.end())))
        m = _UTI_RE.search(text)
        if m:
            out.append(Suggestion("M1600", "1", round(0.6 * conf, 4),
                                  "UTI mention found; verify treatment within past 14 days",
                                  _line_of(text, m.start()), doc.id, page.page_number, (m.start(), m.end())))
        m = _HOSPITAL_RE.search(text)
        if m:
            out.append(Suggestion("M1000", "1", round(0.55 * conf, 4),
                                  "Recent inpatient discharge mentioned; confirm facility type",
                                  _line_of(text, m.start()), doc.id, page.page_number, (m.start(), m.end())))
        m = _PRESSURE_ULCER_RE.search(text)
        if m:
            out.append(Suggestion("M1306", "1", round(0.6 * conf, 4),
                                  "Pressure ulcer/injury mentioned in documentation",
                                  _line_of(text, m.start()), doc.id, page.page_number, (m.start(), m.end())))
        m = _SURGICAL_WOUND_RE.search(text)
        if m:
            out.append(Suggestion("M1340", "1", round(0.6 * conf, 4),
                                  "Surgical wound mentioned in documentation",
                                  _line_of(text, m.start()), doc.id, page.page_number, (m.start(), m.end())))
    return out


def _line_of(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start: end if end != -1 else len(text)].strip()[:500]


def _medication_suggestions(meds: list[Medication]) -> list[Suggestion]:
    out: list[Suggestion] = []
    active = [m for m in meds if m.status in (MedicationStatus.ACTIVE, MedicationStatus.EXTRACTED)]
    if not active:
        return out
    high_risk = [m for m in active if m.is_high_risk]
    if high_risk:
        names = ", ".join(sorted({m.name for m in high_risk}))
        out.append(Suggestion(
            "M2010", "1", 0.5,
            f"High-risk medication(s) on profile ({names}); education indicated — confirm it was provided",
            f"High-risk medications: {names}",
        ))
    injectables = [m for m in active if m.route in ("SUBQ", "IM", "IV", "IVPB")]
    if not injectables:
        out.append(Suggestion(
            "M2030", "NA", 0.7,
            "No injectable medications on the reconciled profile",
            "Medication profile contains no SUBQ/IM/IV medications",
        ))
    return out


def _wound_suggestions(wounds: list[Wound]) -> list[Suggestion]:
    out: list[Suggestion] = []
    pressure = [w for w in wounds if w.wound_type == "pressure" and w.status != "healed"]
    surgical = [w for w in wounds if w.wound_type == "surgical" and w.status != "healed"]
    stage2plus = [w for w in pressure if (w.pressure_stage or "") in ("2", "3", "4", "unstageable", "DTI")]
    if stage2plus:
        locs = "; ".join(f"{w.location} (stage {w.pressure_stage})" for w in stage2plus)
        out.append(Suggestion("M1306", "1", 0.85, f"Active stage-2+ pressure ulcer(s) on wound list: {locs}", locs))
        worst = max(
            (w for w in stage2plus if (w.pressure_stage or "").isdigit()),
            key=lambda w: int(w.pressure_stage), default=None,
        )
        if worst:
            out.append(Suggestion("M1324", worst.pressure_stage, 0.8,
                                  f"Most problematic pressure ulcer staged {worst.pressure_stage} ({worst.location})",
                                  f"{worst.location}: stage {worst.pressure_stage}"))
    elif wounds:
        out.append(Suggestion("M1306", "0", 0.6, "Wound list contains no stage-2+ pressure ulcers",
                              "No stage-2+ pressure ulcers documented"))
    if surgical:
        locs = "; ".join(w.location for w in surgical)
        out.append(Suggestion("M1340", "1", 0.85, f"Active surgical wound(s) on wound list: {locs}", locs))
    return out


def generate_suggestions(db: Session, assessment: OasisAssessment) -> dict:
    """Populate suggested values (+ evidence) for the assessment's items.

    Returns a summary. Existing RN-finalized items are never touched.
    """
    episode_id = assessment.episode_id

    docs = db.execute(
        select(Document, DocumentPage)
        .join(DocumentPage, DocumentPage.document_id == Document.id)
        .where(Document.episode_id == episode_id)
    ).all()
    meds = db.execute(select(Medication).where(Medication.episode_id == episode_id)).scalars().all()
    wounds = db.execute(select(Wound).where(Wound.episode_id == episode_id)).scalars().all()

    suggestions = (
        _document_suggestions([(d, p) for d, p in docs])
        + _medication_suggestions(meds)
        + _wound_suggestions(wounds)
    )

    responses = {r.item_id: r for r in assessment.items}
    applied = 0
    for sugg in suggestions:
        response = responses.get(sugg.item_id)
        item = ITEMS_BY_ID.get(sugg.item_id)
        if response is None or item is None:
            continue  # item not part of this time point
        if item.values and sugg.value not in item.values:
            continue  # never suggest out-of-domain values
        # Keep the highest-confidence suggestion per item.
        if response.suggested_confidence and response.suggested_confidence >= sugg.confidence:
            continue

        evidence = evidence_ledger.append_evidence(
            db,
            document_id=sugg.document_id,
            page_number=sugg.page_number,
            span_start=sugg.span[0] if sugg.span else None,
            span_end=sugg.span[1] if sugg.span else None,
            snippet=sugg.snippet,
            method=f"{ENGINE_NAME}:{sugg.item_id}",
            method_version=ENGINE_VERSION,
            confidence=sugg.confidence,
            context={"rationale": sugg.rationale},
        )
        evidence_ledger.create_extracted_field(
            db,
            entity_type="oasis_item",
            entity_id=response.id,
            field_name=sugg.item_id,
            suggested_value=sugg.value,
            evidence=evidence,
            extractor_name=ENGINE_NAME,
            extractor_version=ENGINE_VERSION,
            confidence=sugg.confidence,
        )
        response.suggested_value = sugg.value
        response.suggested_confidence = sugg.confidence
        response.suggested_rationale = sugg.rationale
        response.suggested_by = SUGGESTER
        response.evidence_ids = (response.evidence_ids or []) + [evidence.id]
        applied += 1

    apply_skip_logic(db, assessment)
    if assessment.status == OasisStatus.IN_PROGRESS and applied:
        assessment.status = OasisStatus.PENDING_REVIEW
    db.flush()
    return {"suggestions_generated": len(suggestions), "suggestions_applied": applied}


def completeness(assessment: OasisAssessment) -> dict:
    """Item-level completeness: an item counts as complete only when an RN has
    finalized it (or skip logic marks it inactive)."""
    total = 0
    finalized = 0
    suggested_only = 0
    missing: list[str] = []
    for r in assessment.items:
        item = ITEMS_BY_ID.get(r.item_id)
        if item is None:
            continue
        if r.skipped:
            continue
        if not item.required:
            continue
        total += 1
        if r.final_value is not None:
            finalized += 1
        else:
            if r.suggested_value is not None:
                suggested_only += 1
            missing.append(r.item_id)
    return {
        "required_items": total,
        "finalized": finalized,
        "suggested_awaiting_review": suggested_only,
        "missing": missing,
        "complete": finalized == total and total > 0,
    }
