# Home Health RN AI Platform

An AI-assisted documentation platform for home health agencies. It ingests
referral packets, extracts medications and physician orders, drives the
OASIS-E2 assessment workflow, flags CMS-validation and payer-denial risks, and
funnels **everything** through an RN review queue.

## The safety contract

Three invariants are hard-coded (the app refuses to start if they are ever
disabled) and enforced end-to-end by `backend/app/core/safety.py`, the review
service, and the test suite:

1. **Never auto-submit.** There is no code path that transmits documentation
   to CMS or a payer. Export requires a signed assessment and an explicit
   human request, and produces a file — not a transmission.
2. **Never auto-sign.** Signing requires an authenticated human RN reviewer,
   an explicit attestation, complete RN finalization of every item, and clean
   CMS validation. Non-human actors (services, workflows, schedulers) are
   rejected at the service layer; the workflow DSL compiler rejects `sign`/
   `submit` actions outright.
3. **Never generate final OASIS codes.** The OASIS engine writes only
   `suggested_value` + confidence + evidence. `final_value` is written by
   exactly one endpoint, restricted to RN reviewers.

And one provenance rule: **every extracted field references an Evidence
Ledger record** — verbatim source snippet, document/page/char-span, method,
version, and confidence — in an append-only, hash-chained ledger.

## Stack

| Layer      | Tech |
|------------|------|
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PyJWT |
| Frontend   | Next.js 14 (App Router), TypeScript, React 18 |
| Database   | PostgreSQL 16 (SQLite in tests) |
| Deployment | Docker Compose (db + backend + frontend) |

## Quick start

```bash
cp .env.example .env          # set HHRN_SECRET_KEY (required)
docker compose up --build
docker compose exec backend python -m app.seed   # demo users + sample patient
```

- Frontend: http://localhost:3000 (sign in as `rn@example-agency.com` / seed password)
- API docs: http://localhost:8000/docs
- Health + safety posture: http://localhost:8000/health

### Local development

```bash
# backend
cd backend
pip install -r requirements-dev.txt
HHRN_DATABASE_URL=sqlite:///dev.db uvicorn app.main:app --reload

# frontend (proxies /api/v1 to BACKEND_URL, default http://localhost:8000)
cd frontend
npm install && npm run dev
```

### Tests

```bash
cd backend && python -m pytest            # 141 tests, no external services needed
cd frontend && npx vitest run
```

## Feature map

| Capability | Code | Docs |
|---|---|---|
| Auth + RBAC (6 roles) | `app/core/security.py`, `app/api/deps.py` | [docs/SECURITY.md](docs/SECURITY.md) |
| Hash-chained audit log | `app/services/audit.py` | [docs/SECURITY.md](docs/SECURITY.md) |
| Evidence Ledger | `app/services/evidence_ledger.py` | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| OASIS-E2 workflow engine | `app/services/oasis_engine.py`, `oasis_catalog.py` | [docs/OASIS_WORKFLOW.md](docs/OASIS_WORKFLOW.md) |
| Workflow DSL engine | `app/services/workflow_dsl.py` | [docs/WORKFLOW_DSL.md](docs/WORKFLOW_DSL.md) |
| Medication extraction | `app/services/extraction/medications.py` | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Physician-order extraction | `app/services/extraction/orders.py` | — |
| FDB preparation | `app/services/fdb.py` | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Infusion management | `app/services/infusion.py` | — |
| Wound management (PUSH, staging) | `app/services/wounds.py` | — |
| Voice-to-SOC drafts | `app/services/voice_soc.py` | — |
| OCR pipeline + image ingestion | `app/services/ocr.py`, `ingestion.py` | — |
| CMS/OASIS validation | `app/services/cms_validation.py` | [docs/OASIS_WORKFLOW.md](docs/OASIS_WORKFLOW.md) |
| Denial-risk detection | `app/services/denial_risk.py` | — |
| RN review workflow | `app/services/review.py` | [docs/SAFETY.md](docs/SAFETY.md) |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, data flow, evidence model
- [docs/SAFETY.md](docs/SAFETY.md) — the safety invariants and how each is enforced
- [docs/SECURITY.md](docs/SECURITY.md) — authn/authz, audit, deployment hardening
- [docs/OASIS_WORKFLOW.md](docs/OASIS_WORKFLOW.md) — OASIS-E2 lifecycle, skip logic, validation rules
- [docs/WORKFLOW_DSL.md](docs/WORKFLOW_DSL.md) — DSL reference with grammar and examples
- [docs/API.md](docs/API.md) — endpoint reference

## Production notes

- OCR: the Docker image ships tesseract (`HHRN_OCR_ENGINE=tesseract`); the
  `stub` engine is for tests/dev. Plug a cloud OCR/ASR provider by
  implementing the `OcrEngine` / `TranscriptionEngine` protocols.
- FDB: medication payloads are normalized and stored ready for a licensed
  First Databank integration (`FdbClient` protocol). The default client
  reports "not configured" and never fabricates screening results.
- Migrations: `alembic upgrade head` (the API also `create_all`s on startup
  for dev convenience).
- This platform processes PHI when used with real data: deploy behind TLS,
  set a strong `HHRN_SECRET_KEY`, restrict CORS, and review
  [docs/SECURITY.md](docs/SECURITY.md) before go-live.
