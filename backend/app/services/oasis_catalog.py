"""OASIS-E2 item catalog (representative subset).

This catalog drives the OASIS workflow engine: section ordering, which items
apply to which assessment types (per the OASIS-E2 "time points" matrix),
allowed value domains, and skip-logic gates.

It is a curated subset of the full instrument covering the sections the
platform's extraction and validation pipelines operate on. Adding items is
data-only — append entries here and the engine, validation, and UI pick them
up. Item text is paraphrased; consult the CMS OASIS-E2 instrument for the
authoritative wording.
"""

from dataclasses import dataclass, field

SOC = "start_of_care"
ROC = "resumption_of_care"
RECERT = "recertification"
FU = "other_followup"
TRANSFER = "transfer"
DC = "discharge"

ALL_POINTS = (SOC, ROC, RECERT, FU, TRANSFER, DC)
SOC_ROC = (SOC, ROC)
SOC_ROC_DC = (SOC, ROC, DC)
SOC_ROC_FU = (SOC, ROC, RECERT, FU)


@dataclass(frozen=True)
class OasisItem:
    item_id: str
    section: str
    label: str
    time_points: tuple[str, ...]
    #: allowed responses; empty means free-form (text/date/number)
    values: tuple[str, ...] = ()
    value_type: str = "code"  # code | date | text | number | multiselect
    required: bool = True
    #: skip logic: {"item": other_item_id, "in": [values]} — item is active only
    #: when the gate item's value is in the list.
    gate: dict | None = field(default=None)


OASIS_E2_ITEMS: tuple[OasisItem, ...] = (
    # --- Administrative ---
    OasisItem("M0080", "administrative", "Discipline of person completing assessment", ALL_POINTS, ("1", "2", "3", "4"), required=True),
    OasisItem("M0090", "administrative", "Date assessment completed", ALL_POINTS, (), "date"),
    OasisItem("M0100", "administrative", "Reason for assessment", ALL_POINTS, ("1", "3", "4", "5", "6", "7", "8", "9")),
    OasisItem("M0102", "administrative", "Date of physician-ordered SOC/ROC", SOC_ROC, (), "date", required=False),
    OasisItem("M0104", "administrative", "Date of referral", SOC_ROC, (), "date"),
    OasisItem("M0110", "administrative", "Episode timing", (SOC, ROC, RECERT), ("1", "2", "UK", "NA"), required=False),
    # --- Patient history / diagnoses ---
    OasisItem("M1000", "history", "Inpatient facilities discharged from (past 14 days)", SOC_ROC, ("1", "2", "3", "4", "5", "6", "7", "NA"), "multiselect"),
    OasisItem("M1005", "history", "Most recent inpatient discharge date", SOC_ROC, (), "date", gate={"item": "M1000", "not_in": ["NA"]}),
    OasisItem("M1021", "history", "Primary diagnosis (ICD-10)", SOC_ROC_FU, (), "text"),
    OasisItem("M1033", "history", "Risk of hospitalization", SOC_ROC, ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10"), "multiselect"),
    # --- Health status / vitals ---
    OasisItem("M1060A", "health", "Height (inches)", SOC_ROC, (), "number"),
    OasisItem("M1060B", "health", "Weight (pounds)", SOC_ROC, (), "number"),
    OasisItem("M1400", "health", "Dyspnea (when short of breath)", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4")),
    # --- Sensory ---
    OasisItem("B0200", "sensory", "Hearing", SOC_ROC, ("0", "1", "2", "3")),
    OasisItem("B1000", "sensory", "Vision", SOC_ROC, ("0", "1", "2", "3", "4")),
    # --- Integumentary ---
    OasisItem("M1306", "integumentary", "Unhealed pressure ulcer/injury stage 2+", SOC_ROC + (RECERT, FU, DC), ("0", "1")),
    OasisItem("M1311", "integumentary", "Current number of unhealed pressure ulcers by stage", SOC_ROC + (RECERT, FU, DC), (), "text", gate={"item": "M1306", "in": ["1"]}),
    OasisItem("M1322", "integumentary", "Number of stage 1 pressure injuries", SOC_ROC + (RECERT, FU, DC), ("0", "1", "2", "3", "4")),
    OasisItem("M1324", "integumentary", "Stage of most problematic unhealed pressure ulcer", SOC_ROC + (RECERT, FU, DC), ("1", "2", "3", "4", "NA"), gate={"item": "M1306", "in": ["1"]}),
    OasisItem("M1330", "integumentary", "Stasis ulcer present", SOC_ROC + (RECERT, FU, DC), ("0", "1", "2", "3")),
    OasisItem("M1340", "integumentary", "Surgical wound present", SOC_ROC + (RECERT, FU, DC), ("0", "1", "2")),
    OasisItem("M1342", "integumentary", "Status of most problematic surgical wound", SOC_ROC + (RECERT, FU, DC), ("0", "1", "2", "3"), gate={"item": "M1340", "in": ["1"]}),
    # --- Respiratory / cardiac ---
    # --- Elimination ---
    OasisItem("M1600", "elimination", "Treated for UTI in past 14 days", SOC_ROC, ("0", "1", "NA", "UK")),
    OasisItem("M1610", "elimination", "Urinary incontinence or catheter", SOC_ROC_FU + (DC,), ("0", "1", "2")),
    OasisItem("M1620", "elimination", "Bowel incontinence frequency", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4", "5", "NA", "UK")),
    # --- Neuro / cognitive ---
    OasisItem("C0500", "cognitive", "BIMS summary score", SOC_ROC_DC, (), "number", required=False),
    OasisItem("M1700", "cognitive", "Cognitive functioning", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4")),
    OasisItem("M1710", "cognitive", "When confused", SOC_ROC_DC, ("0", "1", "2", "3", "4", "NA")),
    OasisItem("M1720", "cognitive", "When anxious", SOC_ROC_DC, ("0", "1", "2", "3", "NA")),
    OasisItem("D0150", "mood", "PHQ-2 to 9 mood interview", SOC_ROC_DC, (), "text", required=False),
    # --- ADL/IADL ---
    OasisItem("M1800", "adl", "Grooming", SOC_ROC_FU + (DC,), ("0", "1", "2", "3")),
    OasisItem("M1810", "adl", "Dress upper body", SOC_ROC_FU + (DC,), ("0", "1", "2", "3")),
    OasisItem("M1820", "adl", "Dress lower body", SOC_ROC_FU + (DC,), ("0", "1", "2", "3")),
    OasisItem("M1830", "adl", "Bathing", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4", "5", "6")),
    OasisItem("M1840", "adl", "Toilet transferring", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4")),
    OasisItem("M1850", "adl", "Transferring", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4", "5")),
    OasisItem("M1860", "adl", "Ambulation/locomotion", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "4", "5", "6")),
    # --- Functional abilities (GG) ---
    OasisItem("GG0130A", "gg", "Self-care: eating", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    OasisItem("GG0130B", "gg", "Self-care: oral hygiene", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    OasisItem("GG0130C", "gg", "Self-care: toileting hygiene", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    OasisItem("GG0170C", "gg", "Mobility: lying to sitting on side of bed", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    OasisItem("GG0170D", "gg", "Mobility: sit to stand", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    OasisItem("GG0170I", "gg", "Mobility: walk 10 feet", SOC_ROC_DC, ("01", "02", "03", "04", "05", "06", "07", "09", "10", "88")),
    # --- Medications ---
    OasisItem("M2001", "medications", "Drug regimen review: potential issues found", SOC_ROC, ("0", "1", "9")),
    OasisItem("M2003", "medications", "Medication follow-up within 1 calendar day", SOC_ROC, ("0", "1"), gate={"item": "M2001", "in": ["1"]}),
    OasisItem("M2010", "medications", "High-risk drug education provided", SOC_ROC, ("0", "1", "NA")),
    OasisItem("M2020", "medications", "Management of oral medications", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "NA")),
    OasisItem("M2030", "medications", "Management of injectable medications", SOC_ROC_FU + (DC,), ("0", "1", "2", "3", "NA")),
    # --- Care management ---
    OasisItem("M2102", "care_mgmt", "Types and sources of assistance: ADL", SOC_ROC_DC, ("0", "1", "2", "3", "4"), required=False),
    # --- Emergent care / discharge ---
    OasisItem("M2301", "outcomes", "Emergent care since last OASIS", (TRANSFER, DC), ("0", "1", "2", "UK")),
    OasisItem("M2410", "outcomes", "Inpatient facility admitted to", (TRANSFER,), ("1", "2", "3", "4")),
    OasisItem("M0906", "outcomes", "Discharge/transfer/death date", (TRANSFER, DC), (), "date"),
)

SECTION_ORDER = (
    "administrative", "history", "health", "sensory", "integumentary", "elimination",
    "cognitive", "mood", "adl", "gg", "medications", "care_mgmt", "outcomes",
)

ITEMS_BY_ID = {i.item_id: i for i in OASIS_E2_ITEMS}


def items_for_time_point(assessment_type: str) -> list[OasisItem]:
    return [i for i in OASIS_E2_ITEMS if assessment_type in i.time_points]
