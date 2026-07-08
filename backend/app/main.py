"""Application entrypoint.

Startup refuses to boot if any clinical safety invariant is disabled
(see app.core.safety).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.safety import enforce_safety_invariants
from app.api import (
    audit as audit_api,
    auth,
    documents,
    evidence,
    infusion,
    medications,
    oasis,
    orders,
    patients,
    review,
    risk,
    users,
    voice,
    wounds,
    workflows,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    enforce_safety_invariants()
    # Tables are managed by Alembic in production; create_all is a no-op for
    # existing tables and keeps development/test bootstraps simple.
    Base.metadata.create_all(bind=engine)
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Home Health RN AI platform. AI output is always a suggestion with "
        "evidence and confidence; final documentation decisions are made and "
        "signed exclusively by human RNs."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
for router in (
    auth.router, users.router, patients.router, documents.router, evidence.router,
    medications.router, orders.router, infusion.router, wounds.router, oasis.router,
    workflows.router, voice.router, review.router, risk.router, audit_api.router,
):
    app.include_router(router, prefix=API_PREFIX)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "safety": {
            "auto_submit": "disabled (hard invariant)",
            "auto_sign": "disabled (hard invariant)",
            "ai_final_oasis_codes": "disabled (hard invariant)",
        },
    }
