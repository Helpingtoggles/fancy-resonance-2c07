# Architecture

## System overview

```
┌────────────┐     /api/v1 (rewrite proxy)      ┌─────────────────┐
│  Next.js   │ ───────────────────────────────▶ │   FastAPI        │
│  frontend  │                                   │   backend        │
└────────────┘                                   │                  │
                                                 │  ┌────────────┐  │      ┌──────────────┐
   uploads (docs / images / audio) ────────────▶ │  │ Ingestion  │──┼────▶ │ Content-     │
                                                 │  │ + OCR/ASR  │  │      │ addressed    │
                                                 │  └─────┬──────┘  │      │ file storage │
                                                 │        ▼         │      └──────────────┘
                                                 │  ┌────────────┐  │
                                                 │  │ Extractors │  │      ┌──────────────┐
                                                 │  │ meds/orders│──┼────▶ │ PostgreSQL   │
                                                 │  │ OASIS engn │  │      │  + Evidence  │
                                                 │  │ voice-SOC  │  │      │    Ledger    │
                                                 │  └─────┬──────┘  │      │  + Audit log │
                                                 │        ▼         │      └──────────────┘
                                                 │  ┌────────────┐  │
                                                 │  │ RN review  │  │   ◀── the ONLY path to
                                                 │  │ workflow   │  │       final values / signatures
                                                 │  └────────────┘  │
                                                 └─────────────────┘
```

## Data flow: referral to signed OASIS

1. **Ingestion** (`services/ingestion.py`): upload → SHA-256 content-addressed
   storage → dedupe → OCR (`services/ocr.py`, pluggable engine) →
   `DocumentPage` rows with per-page confidence.
2. **Extraction** (`services/extraction/`): deterministic rule-based parsers
   walk the OCR text. Every field they emit is created through
   `evidence_ledger.create_extracted_field`, which **requires** a persisted
   `EvidenceRecord` (snippet + span + method + confidence). Extracted
   medications enter `EXTRACTED` status — never active.
3. **OASIS suggestions** (`services/oasis_engine.py`): the engine reads
   documents, reconciled medications, and the wound list, and writes
   `suggested_value`/`suggested_confidence`/`evidence_ids` on item responses.
   It has no code path that writes `final_value`.
4. **RN review** (`services/review.py` + `api/oasis.py`): an RN finalizes
   each item (domain-checked), CMS validation must be clean, then the task
   walks `pending → in_review → approved → signed` with an attestation.
5. **Export** (`api/oasis.py#export_assessment`): flat export of a *signed*
   assessment. No transmission — submission tooling is deliberately human.

## The evidence model

Two append-only, hash-chained tables provide provenance and tamper evidence:

- **`audit_log`** — every state change: actor, role, action, resource,
  detail, IP. `entry_hash = sha256(prev_hash + canonical_json(entry))`;
  `GET /api/v1/audit/verify` re-walks the chain.
- **`evidence_ledger`** — every AI/extraction output: document, page, char
  span, verbatim snippet, method+version, confidence.
  `GET /api/v1/evidence/ledger/verify` re-walks the chain.

`extracted_fields` links a suggestion to its evidence and carries the human
disposition (`suggested → accepted | edited | rejected`) with reviewer and
timestamp. Corrections happen on the field; the evidence of what the source
said is immutable.

## Pluggable engines

| Protocol | Default | Production option |
|---|---|---|
| `OcrEngine` | `stub` (UTF-8 text passthrough; binary → 0-confidence page flagged for manual transcription) | `tesseract` (in Docker image); implement the protocol for cloud OCR |
| `TranscriptionEngine` | `stub` | implement for a real ASR provider |
| `FdbClient` | `NullFdbClient` (reports not-configured, returns no fabricated results) | licensed FDB MedKnowledge client |

FDB preparation (`services/fdb.py`) normalizes each medication — parsed
strength value/unit, FDB-style route code, structured schedule from the
frequency — into a stored `fdb_payload` (schema `fdb-prep/1`) so screening
can be switched on without re-processing history.

## Persistence

SQLAlchemy 2.0 models in `app/models/`. Alembic owns production migrations
(`alembic upgrade head`); startup `create_all` keeps dev/test bootstraps
simple. Tests run the full API against in-memory SQLite (no services needed).

## Frontend

Next.js App Router, all pages client-rendered against the JSON API with JWT
bearer auth. `next.config.mjs` rewrites `/api/v1/*` to the backend so the
browser sees a single origin. Role awareness mirrors the backend (e.g. the
finalize/sign controls render only for RN reviewers) — but authorization is
enforced server-side; the UI hints are convenience only.
