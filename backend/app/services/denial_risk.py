"""Denial-risk detection.

Screens an episode against common Medicare home-health denial drivers
(face-to-face, orders, homebound support, OASIS/orders consistency) and
produces weighted findings plus an aggregate risk score. Findings are
advisory — they feed the RN review queue, never block or alter documentation
by themselves.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.clinical import Medication, MedicationStatus, OrderStatus, PhysicianOrder
from app.models.document import Document, DocumentKind
from app.models.oasis import OasisAssessment
from app.models.patient import Episode
from app.models.risk import DenialRiskFinding

DETECTOR_VERSION = "denial-rules/1.0"


@dataclass
class RiskFinding:
    rule_id: str
    risk_level: str  # high | medium | low
    weight: float
    rationale: str
    remediation: str


def assess_episode(db: Session, episode: Episode) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    add = lambda *a: findings.append(RiskFinding(*a))  # noqa: E731

    docs = db.execute(select(Document).where(Document.episode_id == episode.id)).scalars().all()
    orders = db.execute(select(PhysicianOrder).where(PhysicianOrder.episode_id == episode.id)).scalars().all()
    meds = db.execute(select(Medication).where(Medication.episode_id == episode.id)).scalars().all()
    assessments = db.execute(select(OasisAssessment).where(OasisAssessment.episode_id == episode.id)).scalars().all()

    # --- Face-to-face encounter ---
    f2f_docs = [d for d in docs if d.kind == DocumentKind.FACE_TO_FACE]
    if episode.face_to_face_date is None and not f2f_docs:
        add("DR-F2F-001", "high", 0.30,
            "No face-to-face encounter date or documentation on file. Medicare requires an F2F "
            "encounter within 90 days before or 30 days after SOC.",
            "Obtain and attach the F2F encounter note; record the encounter date on the episode.")
    elif episode.face_to_face_date and episode.soc_date:
        delta = (episode.soc_date - episode.face_to_face_date).days
        if not (-30 <= delta <= 90):
            add("DR-F2F-002", "high", 0.30,
                f"F2F encounter is {delta} days before SOC — outside the 90-before/30-after window.",
                "Verify the encounter date; a compliant F2F encounter may be needed.")

    # --- Orders ---
    unsigned = [o for o in orders if o.status in (OrderStatus.EXTRACTED, OrderStatus.PENDING_SIGNATURE)]
    if unsigned:
        add("DR-ORD-001", "high", 0.25,
            f"{len(unsigned)} physician order(s) are not signed (extracted or pending signature).",
            "Track and obtain physician signatures before billing; unsigned orders are a top denial driver.")
    verbal_unsigned = [o for o in unsigned if o.is_verbal]
    if verbal_unsigned:
        add("DR-ORD-002", "medium", 0.10,
            f"{len(verbal_unsigned)} verbal order(s) await countersignature.",
            "Send verbal orders for physician countersignature promptly.")
    if not any(o.order_type == "sn_frequency" for o in orders):
        add("DR-ORD-003", "medium", 0.15,
            "No skilled-nursing frequency order found for the episode.",
            "Confirm the plan of care includes an SN visit frequency (e.g., 'SN 2wk9').")

    # --- Homebound support ---
    if not episode.homebound_narrative or len(episode.homebound_narrative.strip()) < 40:
        add("DR-HB-001", "high", 0.20,
            "Homebound status narrative is missing or too thin to support medical review.",
            "Document taxing effort and the supporting clinical conditions per Medicare homebound criteria.")

    # --- Certification period ---
    if episode.cert_period_start is None or episode.cert_period_end is None:
        add("DR-CERT-001", "medium", 0.10,
            "Certification period dates are missing on the episode.",
            "Enter the certification period from the signed plan of care.")
    if episode.soc_date and episode.cert_period_start and episode.soc_date != episode.cert_period_start:
        add("DR-CERT-002", "low", 0.05,
            "SOC date differs from certification period start.",
            "Confirm episode dates match the plan of care.")

    # --- OASIS state ---
    if not assessments:
        add("DR-OASIS-001", "high", 0.20,
            "No OASIS assessment exists for the episode.",
            "Complete the SOC comprehensive assessment within 5 days of SOC.")
    else:
        unsigned_oasis = [a for a in assessments if a.signed_at is None]
        if unsigned_oasis:
            add("DR-OASIS-002", "medium", 0.15,
                f"{len(unsigned_oasis)} OASIS assessment(s) not yet RN-signed.",
                "Complete RN review and signature via the review workflow.")

    # --- Medication reconciliation ---
    unreconciled = [m for m in meds if m.status == MedicationStatus.EXTRACTED]
    if unreconciled:
        add("DR-MED-001", "low", 0.05,
            f"{len(unreconciled)} extracted medication(s) have not been RN-reconciled.",
            "Reconcile the medication profile in the review queue.")

    return findings


def risk_score(findings: list[RiskFinding]) -> dict:
    total = min(1.0, sum(f.weight for f in findings))
    level = "high" if total >= 0.5 else "medium" if total >= 0.25 else "low" if total > 0 else "none"
    return {"score": round(total, 3), "level": level}


def run_and_persist(db: Session, episode: Episode) -> dict:
    run_id = str(uuid.uuid4())
    findings = assess_episode(db, episode)
    for f in findings:
        db.add(
            DenialRiskFinding(
                episode_id=episode.id, rule_id=f.rule_id, risk_level=f.risk_level,
                weight=f.weight, rationale=f.rationale, remediation=f.remediation, run_id=run_id,
            )
        )
    db.flush()
    score = risk_score(findings)
    return {
        "run_id": run_id,
        "detector": DETECTOR_VERSION,
        "episode_id": episode.id,
        **score,
        "findings": [f.__dict__ for f in findings],
    }
