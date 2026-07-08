# OASIS-E2 workflow

## Lifecycle

```
IN_PROGRESS ──suggest──▶ PENDING_REVIEW ──RN finalizes items──▶ REVIEWED
                                                                   │
                            review task: pending → in_review → approved
                                                                   │
                                              RN signs (attestation, clean
                                              validation, 100% finalized)
                                                                   ▼
                                                                SIGNED ──human export──▶ EXPORTED
```

- `POST /api/v1/oasis` creates an assessment and instantiates the item set
  for its time point (SOC / ROC / recert / follow-up / transfer / discharge)
  from the E2 catalog (`services/oasis_catalog.py`).
- `POST /oasis/{id}/suggest` runs the engine: document heuristics (height/
  weight, UTI, inpatient discharge, pressure/surgical wound mentions),
  medication-derived items (M2010 high-risk education, M2030 injectable
  management), and wound-list-derived items (M1306/M1324/M1340). Each
  suggestion carries confidence + Evidence Ledger references and is dropped
  if outside the item's value domain.
- `POST /oasis/{id}/items/{item}/finalize` — RN-only single writer of final
  values. Re-runs skip logic after every answer.
- Signing happens through the review queue (see `docs/SAFETY.md`).

## Item catalog

`oasis_catalog.py` encodes a representative, extensible subset of OASIS-E2:
administrative (M0080–M0110), history (M1000/M1005/M1021/M1033), health
(M1060, M1400), sensory (B0200/B1000), integumentary (M1306–M1342),
elimination (M1600–M1620), cognitive/mood (C0500, M1700–M1720, D0150),
ADL (M1800–M1860), GG self-care/mobility items, medications (M2001–M2030),
and transfer/discharge outcomes (M2301, M2410, M0906). Each entry declares:

- `time_points` — which assessment types include the item
- `values` + `value_type` — allowed response domain
- `required` — counts toward completeness
- `gate` — skip logic, e.g. `M1324` is active only when `M1306 = 1`

Adding an item is a data change; the engine, validation, completeness, and
the UI pick it up automatically.

## Skip logic

Gates evaluate against the final value when present (else the suggestion,
advisorily). A skipped item records *why* (`skipped: "skipped: M1306=0 …"`),
is excluded from completeness, and is greyed out in the UI.

## Completeness

An item counts as complete **only when RN-finalized** (or skipped). AI
suggestions never count. Signing requires `complete == true`.

## CMS validation rules (`services/cms_validation.py`)

| Rule | Severity | Checks |
|---|---|---|
| E2-DOMAIN-001 | error | any answered value outside the item's domain |
| E2-COMPLETE-001 | error | required non-skipped items lacking final values |
| E2-REVIEW-001 | warning | AI suggestions awaiting RN review |
| E2-SKIP-1306 / E2-SKIP-1340 | error | answers present that violate skip logic |
| E2-DRR-001/002 | error/warning | M2001↔M2003 drug-regimen-review consistency |
| E2-PLAUS-HT / E2-PLAUS-WT | warning | implausible height/weight |
| E2-DATE-M0090 / E2-DATE-SOC5 / E2-DATE-FMT | error | completion-date sanity, SOC 5-day rule |
| EP-DX-001 / EP-CERT-001 | warning/error | missing primary dx code; cert period > 60 days |

Runs are persisted with a `run_id` (`validation_findings`) and re-run at
sign time — an assessment with validation errors cannot be signed.
