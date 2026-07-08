# Safety invariants

These are product requirements, not defaults. Each is enforced in multiple
layers and locked in by tests (`backend/tests/test_safety_invariants.py`).

## 1. Never auto-submit documentation

- No code path transmits documentation to CMS/iQIES or a payer. The only
  outbound-shaped endpoint is `POST /oasis/{id}/export`, which returns a flat
  JSON export of a **signed** assessment to the caller and explicitly states
  that transmission is a human task.
- `HHRN_ALLOW_AUTO_SUBMIT=true` causes startup failure
  (`core/safety.enforce_safety_invariants`).
- The workflow DSL rejects `submit`/`auto_submit`/`transmit` actions at
  compile time *and* at execution time (defense in depth for stored
  definitions).

## 2. Never auto-sign documentation

- Signing happens in exactly one place: `review.act_on_task(action="sign")`.
  It requires:
  - an authenticated **human** actor (`assert_human_actor`; actor kinds
    `system`, `service`, `ai`, `workflow`, `scheduler` are rejected),
  - role `rn_reviewer` (admins cannot sign — signing is a clinical act),
  - a non-trivial attestation string,
  - task status `approved` (the workflow cannot be skipped),
  - for OASIS subjects: every required, non-skipped item RN-finalized and
    zero CMS-validation errors.
- There is no bulk-sign, no scheduled job, and no service account with
  signing ability.
- `HHRN_ALLOW_AUTO_SIGN=true` causes startup failure.

## 3. Never generate final OASIS codes

- The OASIS engine (`services/oasis_engine.py`) writes only
  `suggested_value`, `suggested_confidence`, `suggested_rationale`, and
  `evidence_ids`. Grep the file: `final_value` is only ever *read*.
- `final_value` is written by exactly one endpoint —
  `POST /oasis/{id}/items/{item}/finalize` — gated to RN reviewers, domain-
  validated, audited, and frozen once the assessment is signed.
- Out-of-domain suggestions are dropped by the engine, so even a bad
  heuristic cannot steer an RN toward an invalid code.
- `HHRN_ALLOW_AI_FINAL_CODES=true` causes startup failure.

## 4. Every extracted field carries evidence + confidence

- `ExtractedField.evidence_id` is `NOT NULL`; the only constructor
  (`evidence_ledger.create_extracted_field`) requires a **persisted**
  `EvidenceRecord` and a confidence in [0, 1].
- Evidence records require a non-empty verbatim snippet and carry method,
  method version, page, and character span.
- The ledger is append-only and hash-chained; `GET /evidence/ledger/verify`
  detects tampering.

## Residual-risk notes for operators

- The UI labels suggestions and confidence prominently, but automation bias
  is real: train reviewers to open the evidence snippet, not just accept.
- The stub OCR/ASR engines are for development; with real scans, monitor
  page-level OCR confidence (low-confidence pages surface as 0.0 and should
  be manually transcribed).
- Denial-risk and validation findings are advisory screens, not a guarantee
  of payment or compliance.
