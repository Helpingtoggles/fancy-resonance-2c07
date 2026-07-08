"""FDB (First Databank) preparation.

The platform does not bundle FDB content (it is licensed). This module:

1. Normalizes extracted medications into the shape an FDB MedKnowledge /
   OrderKnowledge integration expects (parsed strength value+unit, mapped
   route code, structured schedule), so the payloads are ready the moment an
   FDB subscription is configured.
2. Defines the :class:`FdbClient` protocol that a real integration
   implements (drug normalization, interaction screening, dose range checks).
   ``NullFdbClient`` is the default and reports itself as not configured
   rather than fabricating clinical screening results.
"""

import re
from datetime import datetime, timezone
from typing import Protocol

from app.models.clinical import Medication

FDB_ROUTE_CODES = {
    # Simplified mapping to FDB-style route-of-administration identifiers.
    "PO": {"code": "1", "description": "Oral"},
    "IV": {"code": "11", "description": "Intravenous"},
    "IVPB": {"code": "11", "description": "Intravenous"},
    "SUBQ": {"code": "5", "description": "Subcutaneous"},
    "IM": {"code": "6", "description": "Intramuscular"},
    "SL": {"code": "2", "description": "Sublingual"},
    "TOP": {"code": "20", "description": "Topical"},
    "TD": {"code": "21", "description": "Transdermal"},
    "INH": {"code": "13", "description": "Inhalation"},
    "NEB": {"code": "13", "description": "Inhalation"},
    "PR": {"code": "3", "description": "Rectal"},
    "OPH": {"code": "16", "description": "Ophthalmic"},
    "OTIC": {"code": "17", "description": "Otic"},
    "NAS": {"code": "14", "description": "Nasal"},
    "GT": {"code": "9", "description": "Gastrostomy tube"},
}

FREQUENCY_SCHEDULE = {
    "QD": {"times_per_day": 1, "interval_hours": 24},
    "BID": {"times_per_day": 2, "interval_hours": 12},
    "TID": {"times_per_day": 3, "interval_hours": 8},
    "QID": {"times_per_day": 4, "interval_hours": 6},
    "QHS": {"times_per_day": 1, "interval_hours": 24, "time_of_day": "bedtime"},
    "QAM": {"times_per_day": 1, "interval_hours": 24, "time_of_day": "morning"},
    "QPM": {"times_per_day": 1, "interval_hours": 24, "time_of_day": "evening"},
    "QOD": {"times_per_day": 0.5, "interval_hours": 48},
    "QWEEK": {"times_per_day": 1 / 7, "interval_hours": 168},
    "QMONTH": {"times_per_day": 1 / 30, "interval_hours": 720},
    "Q4H": {"times_per_day": 6, "interval_hours": 4},
    "Q6H": {"times_per_day": 4, "interval_hours": 6},
    "Q8H": {"times_per_day": 3, "interval_hours": 8},
    "Q12H": {"times_per_day": 2, "interval_hours": 12},
    "Q72H": {"times_per_day": 1 / 3, "interval_hours": 72},
}

_STRENGTH_PARSE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s?(?P<unit>mg|mcg|g|gm|units?|iu|meq|ml|mL|%)"
    r"(?:\s?/\s?(?P<per>ml|mL|day|dose|hr|kg))?",
    re.IGNORECASE,
)


def parse_strength(strength: str | None) -> dict | None:
    if not strength:
        return None
    m = _STRENGTH_PARSE.search(strength)
    if not m:
        return {"raw": strength, "parsed": False}
    return {
        "raw": strength,
        "parsed": True,
        "value": float(m.group("value").replace(",", ".")),
        "unit": m.group("unit").lower().replace("gm", "g"),
        "per": m.group("per").lower() if m.group("per") else None,
    }


def prepare_fdb_payload(med: Medication) -> dict:
    """Build the normalized FDB screening request for one medication."""
    route = FDB_ROUTE_CODES.get(med.route or "")
    schedule = FREQUENCY_SCHEDULE.get(med.frequency or "")
    return {
        "drug": {
            "name": med.name,
            "name_normalized": med.name.strip().lower(),
            "strength": parse_strength(med.strength),
            "dose": med.dose,
        },
        "route": {"raw": med.route, "fdb": route},
        "schedule": {"raw": med.frequency, "fdb": schedule, "prn": med.prn, "prn_reason": med.prn_reason},
        "flags": {"high_risk": med.is_high_risk},
        "screening_requested": ["drug_drug_interaction", "duplicate_therapy", "dose_range", "allergy"],
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "schema": "fdb-prep/1",
    }


def prepare_medication(med: Medication) -> Medication:
    med.fdb_payload = prepare_fdb_payload(med)
    med.fdb_prepared_at = datetime.now(timezone.utc)
    return med


class FdbClient(Protocol):
    """Interface a licensed FDB integration must implement."""

    def is_configured(self) -> bool: ...

    def screen(self, payloads: list[dict]) -> dict:
        """Run interaction/dose/duplicate/allergy screening on prepared payloads."""
        ...


class NullFdbClient:
    """Default client when no FDB license is configured.

    It intentionally does NOT fabricate screening results: it reports that
    screening is unavailable so the RN knows to screen through another system.
    """

    def is_configured(self) -> bool:
        return False

    def screen(self, payloads: list[dict]) -> dict:
        return {
            "configured": False,
            "results": [],
            "message": (
                "FDB is not configured. Payloads are prepared and stored; connect a licensed "
                "FDB MedKnowledge endpoint to enable interaction and dose-range screening."
            ),
            "payloads_prepared": len(payloads),
        }


def get_fdb_client() -> FdbClient:
    return NullFdbClient()
