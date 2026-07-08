from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.document import DocumentKind, VoiceSession
from app.models.patient import Episode
from app.models.user import Role, User
from app.schemas.common import VoiceSessionOut
from app.services import audit, ingestion, voice_soc

router = APIRouter(prefix="/voice", tags=["voice-to-soc"])

clinical_roles = require_roles(Role.RN_REVIEWER, Role.CLINICIAN)


@router.post("/sessions", response_model=VoiceSessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    episode_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(clinical_roles),
):
    """Upload a visit recording and run the voice-to-SOC pipeline.

    The result is a DRAFT: extracted sections/vitals carry transcript
    evidence + confidence and a review task is created for the RN.
    """
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")

    content = await file.read()
    try:
        audio_doc = ingestion.ingest_document(
            db, content=content, filename=file.filename or "recording",
            content_type=file.content_type or "audio/wav", kind=DocumentKind.VOICE_RECORDING,
            patient_id=episode.patient_id, episode_id=episode.id, uploaded_by=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    session_obj = VoiceSession(episode_id=episode.id, audio_document_id=audio_doc.id, created_by=actor.id)
    db.add(session_obj)
    db.flush()
    voice_soc.process_voice_session(db, session_obj, audio_doc)
    audit.record(db, action="voice.session_processed", actor_id=actor.id, actor_email=actor.email,
                 actor_role=actor.role.value, resource_type="voice_session", resource_id=session_obj.id,
                 detail={"status": session_obj.status.value})
    db.commit()
    return session_obj


@router.get("/sessions", response_model=list[VoiceSessionOut])
def list_sessions(episode_id: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    stmt = select(VoiceSession).order_by(VoiceSession.created_at.desc()).limit(100)
    if episode_id:
        stmt = stmt.where(VoiceSession.episode_id == episode_id)
    return db.execute(stmt).scalars().all()


@router.get("/sessions/{session_id}", response_model=VoiceSessionOut)
def get_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session_obj = db.get(VoiceSession, session_id)
    if session_obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice session not found")
    return session_obj
