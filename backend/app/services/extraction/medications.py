"""Medication extraction from OCR'd document text.

Deterministic, rule-based sig parsing: for each candidate medication line we
extract name, strength, dose, route, frequency, and PRN flag, each with a
character span into the source page (recorded in the Evidence Ledger) and a
per-field confidence heuristic.

The extractor NEVER creates active medications: extracted meds enter in
``EXTRACTED`` status and require RN reconciliation before becoming active.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.clinical import Medication, MedicationStatus
from app.models.document import Document
from app.services import evidence_ledger

EXTRACTOR_NAME = "rules:medication_sig"
EXTRACTOR_VERSION = "1.2"

ROUTES = {
    "po": "PO", "p.o.": "PO", "by mouth": "PO", "oral": "PO", "orally": "PO",
    "iv": "IV", "i.v.": "IV", "intravenous": "IV", "ivpb": "IVPB",
    "subq": "SUBQ", "sq": "SUBQ", "sc": "SUBQ", "subcutaneous": "SUBQ", "subcutaneously": "SUBQ",
    "im": "IM", "intramuscular": "IM",
    "sl": "SL", "sublingual": "SL",
    "topical": "TOP", "topically": "TOP",
    "inhaled": "INH", "inhalation": "INH", "nebulizer": "NEB", "neb": "NEB",
    "pr": "PR", "rectal": "PR", "transdermal": "TD", "patch": "TD",
    "ophthalmic": "OPH", "otic": "OTIC", "nasal": "NAS", "g-tube": "GT", "gt": "GT",
}

FREQUENCIES = {
    "qd": "QD", "daily": "QD", "once daily": "QD", "every day": "QD", "q day": "QD", "qday": "QD",
    "bid": "BID", "twice daily": "BID", "twice a day": "BID", "2 times daily": "BID",
    "tid": "TID", "three times daily": "TID", "3 times daily": "TID",
    "qid": "QID", "four times daily": "QID", "4 times daily": "QID",
    "qhs": "QHS", "at bedtime": "QHS", "nightly": "QHS",
    "qam": "QAM", "every morning": "QAM", "qpm": "QPM",
    "qod": "QOD", "every other day": "QOD",
    "weekly": "QWEEK", "once weekly": "QWEEK", "every week": "QWEEK",
    "monthly": "QMONTH", "q4h": "Q4H", "q6h": "Q6H", "q8h": "Q8H", "q12h": "Q12H",
    "every 4 hours": "Q4H", "every 6 hours": "Q6H", "every 8 hours": "Q8H", "every 12 hours": "Q12H",
    "every 72 hours": "Q72H", "q72h": "Q72H",
}

HIGH_RISK_MEDS = {
    "warfarin", "coumadin", "insulin", "heparin", "enoxaparin", "lovenox", "apixaban",
    "eliquis", "rivaroxaban", "xarelto", "digoxin", "methotrexate", "morphine",
    "oxycodone", "hydromorphone", "fentanyl", "hydrocodone", "amiodarone", "lithium",
    "vancomycin", "chemotherapy",
}

_STRENGTH_RE = re.compile(
    r"(?P<strength>\d+(?:[.,]\d+)?\s?(?:mg|mcg|g|gm|units?|iu|meq|ml|mL|%)(?:\s?/\s?(?:ml|mL|day|dose|hr|kg))?)",
    re.IGNORECASE,
)
_DOSE_RE = re.compile(
    r"(?P<dose>(?:\d+(?:[.,]\d+)?|one|two|three|half|\d+/\d+)\s?(?:tab(?:let)?s?|cap(?:sule)?s?|puffs?|sprays?|drops?|patch(?:es)?|units?|ml|mL)\b)",
    re.IGNORECASE,
)
_PRN_RE = re.compile(r"\b(?:prn|as needed)\b(?:\s+(?:for\s+)?(?P<reason>[\w\s]{3,40}?))?(?=[,.;]|$)", re.IGNORECASE)

# A candidate med line: starts with a capitalized token, contains a strength or a route/frequency keyword.
_NAME_RE = re.compile(r"^\s*(?:\d+[.)]\s*)?(?P<name>[A-Za-z][A-Za-z\-/']+(?:\s+[A-Za-z\-/']+)?)")

_SECTION_HINTS = re.compile(r"(medication|med list|current meds|home meds|discharge medications)", re.IGNORECASE)
_NEGATIVE_LINE = re.compile(
    r"^(allergies|diagnos|assessment|plan|history|vital|instructions|follow.?up|signature|physician|patient|dob|mrn)",
    re.IGNORECASE,
)


@dataclass
class ParsedMedLine:
    line: str
    line_start: int  # char offset of line within the page text
    name: str | None = None
    strength: str | None = None
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    prn: bool = False
    prn_reason: str | None = None
    field_spans: dict = field(default_factory=dict)  # field -> (start, end) within page
    field_confidence: dict = field(default_factory=dict)


def _find_keyword(line: str, table: dict[str, str]) -> tuple[str, int, int] | None:
    """Longest-match keyword search; returns (normalized, start, end)."""
    lowered = line.lower()
    best: tuple[str, int, int] | None = None
    for key, norm in table.items():
        idx = lowered.find(key)
        while idx != -1:
            before_ok = idx == 0 or not lowered[idx - 1].isalnum()
            after = idx + len(key)
            after_ok = after >= len(lowered) or not lowered[after].isalnum()
            if before_ok and after_ok and (best is None or len(key) > (best[2] - best[1])):
                best = (norm, idx, after)
            idx = lowered.find(key, idx + 1)
    return best


def parse_medication_line(line: str, line_start: int = 0) -> ParsedMedLine | None:
    stripped = line.strip()
    if len(stripped) < 4 or _NEGATIVE_LINE.match(stripped):
        return None

    parsed = ParsedMedLine(line=line, line_start=line_start)
    offset = line_start

    strength_m = _STRENGTH_RE.search(line)
    route_hit = _find_keyword(line, ROUTES)
    freq_hit = _find_keyword(line, FREQUENCIES)

    # Require at least a strength or (route and frequency) to consider it a med line.
    if not strength_m and not (route_hit and freq_hit):
        return None

    name_m = _NAME_RE.match(line)
    if not name_m:
        return None
    name = name_m.group("name").strip()
    # Trim the name if strength starts inside it ("Metoprolol 25 mg" matches fine,
    # but "Aspirin EC 81 mg" keeps "Aspirin EC").
    if strength_m and name_m.end("name") > strength_m.start():
        name = line[name_m.start("name"): strength_m.start()].strip(" -–")
    if not name or len(name) < 3:
        return None

    parsed.name = name
    parsed.field_spans["name"] = (offset + name_m.start("name"), offset + name_m.start("name") + len(name))
    parsed.field_confidence["name"] = 0.9 if strength_m else 0.75

    if strength_m:
        parsed.strength = re.sub(r"\s+", " ", strength_m.group("strength")).strip()
        parsed.field_spans["strength"] = (offset + strength_m.start(), offset + strength_m.end())
        parsed.field_confidence["strength"] = 0.95

    dose_m = _DOSE_RE.search(line, strength_m.end() if strength_m else 0)
    if dose_m:
        parsed.dose = dose_m.group("dose").strip()
        parsed.field_spans["dose"] = (offset + dose_m.start(), offset + dose_m.end())
        parsed.field_confidence["dose"] = 0.85

    if route_hit:
        parsed.route = route_hit[0]
        parsed.field_spans["route"] = (offset + route_hit[1], offset + route_hit[2])
        parsed.field_confidence["route"] = 0.9
    if freq_hit:
        parsed.frequency = freq_hit[0]
        parsed.field_spans["frequency"] = (offset + freq_hit[1], offset + freq_hit[2])
        parsed.field_confidence["frequency"] = 0.9

    prn_m = _PRN_RE.search(line)
    if prn_m:
        parsed.prn = True
        reason = (prn_m.group("reason") or "").strip() or None
        parsed.prn_reason = reason
        parsed.field_spans["prn"] = (offset + prn_m.start(), offset + prn_m.end())
        parsed.field_confidence["prn"] = 0.95

    return parsed


def extract_medications_from_text(text: str) -> list[ParsedMedLine]:
    results = []
    pos = 0
    for line in text.split("\n"):
        parsed = parse_medication_line(line, line_start=pos)
        if parsed:
            results.append(parsed)
        pos += len(line) + 1
    return results


def extract_and_persist(db: Session, document: Document) -> list[Medication]:
    """Run extraction over a document's OCR pages and persist EXTRACTED meds
    with per-field evidence."""
    meds: list[Medication] = []
    for page in document.pages:
        page_conf = page.ocr_confidence if page.ocr_confidence is not None else 0.5
        for parsed in extract_medications_from_text(page.text):
            name_lower = (parsed.name or "").lower()
            med = Medication(
                patient_id=document.patient_id,
                episode_id=document.episode_id,
                name=parsed.name or "",
                strength=parsed.strength,
                dose=parsed.dose,
                route=parsed.route,
                frequency=parsed.frequency,
                prn=parsed.prn,
                prn_reason=parsed.prn_reason,
                status=MedicationStatus.EXTRACTED,
                is_high_risk=any(h in name_lower for h in HIGH_RISK_MEDS),
                source_document_id=document.id,
            )
            db.add(med)
            db.flush()

            for field_name in ("name", "strength", "dose", "route", "frequency", "prn"):
                value = getattr(parsed, field_name, None)
                if value in (None, False, ""):
                    continue
                span = parsed.field_spans.get(field_name)
                extraction_conf = parsed.field_confidence.get(field_name, 0.5)
                combined = round(extraction_conf * page_conf, 4)
                evidence = evidence_ledger.append_evidence(
                    db,
                    document_id=document.id,
                    page_number=page.page_number,
                    span_start=span[0] if span else None,
                    span_end=span[1] if span else None,
                    snippet=parsed.line.strip(),
                    method=f"{EXTRACTOR_NAME}:{field_name}",
                    method_version=EXTRACTOR_VERSION,
                    confidence=combined,
                    context={"ocr_confidence": page_conf, "extraction_confidence": extraction_conf},
                )
                evidence_ledger.create_extracted_field(
                    db,
                    entity_type="medication",
                    entity_id=med.id,
                    field_name=field_name,
                    suggested_value=str(value),
                    evidence=evidence,
                    extractor_name=EXTRACTOR_NAME,
                    extractor_version=EXTRACTOR_VERSION,
                    confidence=combined,
                )
            meds.append(med)
    return meds
