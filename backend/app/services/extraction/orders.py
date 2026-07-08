"""Physician order extraction from OCR'd documents.

Detects order type (skilled-nursing frequency, therapy, medication, wound
care, infusion), ordering physician, order date, verbal-order flags, and
certification period. Every extracted attribute records evidence + confidence.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.clinical import OrderStatus, PhysicianOrder
from app.models.document import Document
from app.services import evidence_ledger

EXTRACTOR_NAME = "rules:physician_order"
EXTRACTOR_VERSION = "1.1"

# e.g. "SN 2wk9" or "SN 1w9" (visits per week for N weeks), "PT eval and treat"
_SN_FREQ_RE = re.compile(r"\bSN\s*(?P<freq>\d+\s?[wW](?:k)?\s?\d+(?:\s*,\s*\d+\s?[wW](?:k)?\s?\d+)*)", re.IGNORECASE)
_THERAPY_RE = re.compile(r"\b(?P<disc>PT|OT|ST|SLP|MSW|HHA)\b\s*(?:eval(?:uate)?(?:\s*(?:and|&)\s*treat)?|\d+\s?[wW]k?\s?\d+)", re.IGNORECASE)
_WOUND_RE = re.compile(r"\bwound\s+care\b|\bdressing\s+change\b|\bwound\s+vac\b|\bNPWT\b", re.IGNORECASE)
_INFUSION_RE = re.compile(r"\binfus(?:e|ion)\b|\bIV\s+(?:antibiotic|therapy|infusion)\b|\bTPN\b|\bIVIG\b", re.IGNORECASE)
_MED_ORDER_RE = re.compile(r"\b(?:start|begin|increase|decrease|discontinue|d/c|hold)\b.{0,60}\b(?:mg|mcg|units?|tablet|capsule)\b", re.IGNORECASE)
_PHYSICIAN_RE = re.compile(r"(?:Dr\.?|Doctor)\s+(?P<name>[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?)|(?P<name2>[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)?),?\s+(?:MD|DO|NP|PA)\b")
_NPI_RE = re.compile(r"\bNPI[:#\s]*(?P<npi>\d{10})\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<y>\d{2,4})\b")
_VERBAL_RE = re.compile(r"\b(?:verbal order|V\.?O\.?|telephone order|T\.?O\.?)\b", re.IGNORECASE)
_CERT_RE = re.compile(
    r"cert(?:ification)?\s+period[:\s]*(?P<start>\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*(?:to|through|-|–)\s*(?P<end>\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)


@dataclass
class ParsedOrder:
    order_type: str
    text: str
    span: tuple[int, int]
    confidence: float
    physician: str | None = None
    npi: str | None = None
    order_date: date | None = None
    is_verbal: bool = False
    cert_period: tuple[date, date] | None = None
    attributes: dict = field(default_factory=dict)


def _parse_date(m: re.Match) -> date | None:
    try:
        year = int(m.group("y"))
        if year < 100:
            year += 2000
        return date(year, int(m.group("m")), int(m.group("d")))
    except ValueError:
        return None


def _parse_date_str(s: str) -> date | None:
    m = _DATE_RE.search(s)
    return _parse_date(m) if m else None


def extract_orders_from_text(text: str) -> list[ParsedOrder]:
    orders: list[ParsedOrder] = []

    detectors: list[tuple[str, re.Pattern, float]] = [
        ("sn_frequency", _SN_FREQ_RE, 0.92),
        ("therapy", _THERAPY_RE, 0.85),
        ("wound_care", _WOUND_RE, 0.8),
        ("infusion", _INFUSION_RE, 0.8),
        ("medication", _MED_ORDER_RE, 0.7),
    ]

    # Document-level attributes
    phys_m = _PHYSICIAN_RE.search(text)
    physician = None
    if phys_m:
        physician = phys_m.group("name") or phys_m.group("name2")
    npi_m = _NPI_RE.search(text)
    date_m = _DATE_RE.search(text)
    verbal = bool(_VERBAL_RE.search(text))
    cert_m = _CERT_RE.search(text)
    cert_period = None
    if cert_m:
        start = _parse_date_str(cert_m.group("start"))
        end = _parse_date_str(cert_m.group("end"))
        if start and end:
            cert_period = (start, end)

    seen_spans: list[tuple[int, int]] = []
    for order_type, pattern, confidence in detectors:
        for m in pattern.finditer(text):
            # Skip if this span is inside an already-captured higher-priority order.
            if any(s <= m.start() < e for s, e in seen_spans):
                continue
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line_end = line_end if line_end != -1 else len(text)
            line = text[line_start:line_end].strip()
            orders.append(
                ParsedOrder(
                    order_type=order_type,
                    text=line,
                    span=(line_start, line_end),
                    confidence=confidence,
                    physician=physician,
                    npi=npi_m.group("npi") if npi_m else None,
                    order_date=_parse_date(date_m) if date_m else None,
                    is_verbal=verbal,
                    cert_period=cert_period,
                    attributes={"match": m.group(0)},
                )
            )
            seen_spans.append((line_start, line_end))
    return orders


def extract_and_persist(db: Session, document: Document) -> list[PhysicianOrder]:
    persisted: list[PhysicianOrder] = []
    for page in document.pages:
        page_conf = page.ocr_confidence if page.ocr_confidence is not None else 0.5
        for parsed in extract_orders_from_text(page.text):
            order = PhysicianOrder(
                episode_id=document.episode_id,
                order_type=parsed.order_type,
                order_text=parsed.text,
                ordering_physician=parsed.physician,
                npi=parsed.npi,
                order_date=parsed.order_date,
                is_verbal=parsed.is_verbal,
                status=OrderStatus.PENDING_SIGNATURE if parsed.is_verbal else OrderStatus.EXTRACTED,
                source_document_id=document.id,
            )
            db.add(order)
            db.flush()

            combined = round(parsed.confidence * page_conf, 4)
            evidence = evidence_ledger.append_evidence(
                db,
                document_id=document.id,
                page_number=page.page_number,
                span_start=parsed.span[0],
                span_end=parsed.span[1],
                snippet=parsed.text,
                method=f"{EXTRACTOR_NAME}:{parsed.order_type}",
                method_version=EXTRACTOR_VERSION,
                confidence=combined,
                context={"ocr_confidence": page_conf, "physician": parsed.physician},
            )
            evidence_ledger.create_extracted_field(
                db,
                entity_type="physician_order",
                entity_id=order.id,
                field_name="order_text",
                suggested_value=parsed.text,
                evidence=evidence,
                extractor_name=EXTRACTOR_NAME,
                extractor_version=EXTRACTOR_VERSION,
                confidence=combined,
            )
            persisted.append(order)
    return persisted
