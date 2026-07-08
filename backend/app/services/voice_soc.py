"""Voice-to-SOC documentation pipeline.

Flow: RN records a narrative during the SOC visit → audio ingested as a
document → transcription (pluggable engine) → deterministic section
segmentation + field extraction → a **draft** SOC note whose every field
carries transcript evidence and confidence → a review task for the RN.

The draft is never auto-finalized: it lands in the review queue like any
other extraction.
"""

import re
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, VoiceSession, VoiceSessionStatus
from app.models.review import ReviewTask
from app.services import evidence_ledger

PIPELINE_NAME = "voice-soc"
PIPELINE_VERSION = "1.0"


class TranscriptionEngine(Protocol):
    name: str

    def transcribe(self, audio_path: str) -> tuple[str, float]:
        """Return (transcript, confidence)."""
        ...


class StubTranscriptionEngine:
    """Development/test engine: reads a sidecar ``.txt`` transcript when the
    'audio' file is UTF-8 text (test fixtures), otherwise reports failure."""

    name = "stub"

    def transcribe(self, audio_path: str) -> tuple[str, float]:
        from pathlib import Path

        data = Path(audio_path).read_bytes()
        try:
            return data.decode("utf-8"), 0.95
        except UnicodeDecodeError:
            raise RuntimeError(
                "Stub transcription engine cannot process binary audio. "
                "Configure HHRN_TRANSCRIPTION_ENGINE for a real ASR provider."
            )


_ENGINES = {"stub": StubTranscriptionEngine}


def get_transcription_engine() -> TranscriptionEngine:
    name = get_settings().transcription_engine
    try:
        return _ENGINES[name]()
    except KeyError:
        raise ValueError(f"Unknown transcription engine '{name}'. Available: {sorted(_ENGINES)}")


# --- SOC narrative segmentation -------------------------------------------

SECTION_PATTERNS: dict[str, re.Pattern] = {
    "chief_complaint": re.compile(r"(?:chief complaint|reason for (?:visit|referral|admission))[:\s]", re.I),
    "history": re.compile(r"(?:history of present illness|medical history|past medical history|pmh)[:\s]", re.I),
    "vital_signs": re.compile(r"(?:vital signs?|vitals)[:\s]", re.I),
    "medications": re.compile(r"(?:medications?|med list|current meds)[:\s]", re.I),
    "wounds": re.compile(r"(?:wounds?|skin(?:\s+assessment)?|integumentary)[:\s]", re.I),
    "pain": re.compile(r"(?:pain(?:\s+assessment)?)[:\s]", re.I),
    "homebound": re.compile(r"(?:homebound(?:\s+status)?)[:\s]", re.I),
    "safety": re.compile(r"(?:home safety|safety(?:\s+assessment)?)[:\s]", re.I),
    "plan": re.compile(r"(?:plan(?:\s+of\s+care)?|goals)[:\s]", re.I),
}

_VITALS_RES = {
    "blood_pressure": re.compile(r"(?:bp|blood pressure)[:\s]*(?P<v>\d{2,3}\s*/\s*\d{2,3})", re.I),
    "heart_rate": re.compile(r"(?:hr|heart rate|pulse)[:\s]*(?P<v>\d{2,3})\b", re.I),
    "respiratory_rate": re.compile(r"(?:rr|respiratory rate|respirations)[:\s]*(?P<v>\d{1,2})\b", re.I),
    "temperature": re.compile(r"(?:temp(?:erature)?)[:\s]*(?P<v>\d{2,3}(?:\.\d)?)", re.I),
    "oxygen_saturation": re.compile(r"(?:o2 sat|spo2|oxygen saturation|pulse ox)[:\s]*(?P<v>\d{2,3})\s*%?", re.I),
    "pain_score": re.compile(r"pain(?:\s+(?:score|level|rated?))?(?:\s+(?:is|at|of))?[:\s]*(?P<v>\d{1,2})\s*(?:/|out of)\s*10", re.I),
}


def segment_transcript(transcript: str) -> dict[str, dict]:
    """Split a transcript into sections; returns {section: {text, span}}."""
    hits: list[tuple[int, str]] = []
    for section, pattern in SECTION_PATTERNS.items():
        m = pattern.search(transcript)
        if m:
            hits.append((m.start(), section))
    hits.sort()
    sections: dict[str, dict] = {}
    for idx, (start, section) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(transcript)
        sections[section] = {"text": transcript[start:end].strip(), "span": (start, end)}
    if not sections and transcript.strip():
        sections["narrative"] = {"text": transcript.strip(), "span": (0, len(transcript))}
    return sections


def extract_vitals(transcript: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, pattern in _VITALS_RES.items():
        m = pattern.search(transcript)
        if m:
            out[name] = {"value": m.group("v").replace(" ", ""), "span": (m.start(), m.end())}
    return out


def process_voice_session(db: Session, session_obj: VoiceSession, audio_doc: Document) -> VoiceSession:
    """Transcribe + draft. Creates evidence records and a review task."""
    engine = get_transcription_engine()
    try:
        transcript, confidence = engine.transcribe(audio_doc.storage_path)
    except RuntimeError as exc:
        session_obj.status = VoiceSessionStatus.FAILED
        session_obj.soc_draft = {"error": str(exc)}
        db.flush()
        return session_obj

    session_obj.transcript = transcript
    session_obj.transcription_engine = engine.name
    session_obj.transcription_confidence = confidence
    session_obj.status = VoiceSessionStatus.TRANSCRIBED

    sections = segment_transcript(transcript)
    vitals = extract_vitals(transcript)

    draft_fields: dict[str, dict] = {}
    for section, payload in sections.items():
        evidence = evidence_ledger.append_evidence(
            db,
            document_id=audio_doc.id,
            page_number=1,
            span_start=payload["span"][0],
            span_end=payload["span"][1],
            snippet=payload["text"][:500],
            method=f"{PIPELINE_NAME}:section:{section}",
            method_version=PIPELINE_VERSION,
            confidence=round(0.8 * confidence, 4),
            context={"section": section},
        )
        field = evidence_ledger.create_extracted_field(
            db,
            entity_type="soc_field",
            entity_id=session_obj.id,
            field_name=f"section.{section}",
            suggested_value=payload["text"],
            evidence=evidence,
            extractor_name=PIPELINE_NAME,
            extractor_version=PIPELINE_VERSION,
        )
        draft_fields[f"section.{section}"] = {
            "value": payload["text"],
            "confidence": field.confidence,
            "evidence_id": evidence.id,
        }

    for vital, payload in vitals.items():
        snippet = transcript[max(0, payload["span"][0] - 10): payload["span"][1] + 10].strip()
        evidence = evidence_ledger.append_evidence(
            db,
            document_id=audio_doc.id,
            page_number=1,
            span_start=payload["span"][0],
            span_end=payload["span"][1],
            snippet=snippet,
            method=f"{PIPELINE_NAME}:vital:{vital}",
            method_version=PIPELINE_VERSION,
            confidence=round(0.9 * confidence, 4),
            context={"vital": vital},
        )
        field = evidence_ledger.create_extracted_field(
            db,
            entity_type="soc_field",
            entity_id=session_obj.id,
            field_name=f"vital.{vital}",
            suggested_value=payload["value"],
            evidence=evidence,
            extractor_name=PIPELINE_NAME,
            extractor_version=PIPELINE_VERSION,
        )
        draft_fields[f"vital.{vital}"] = {
            "value": payload["value"],
            "confidence": field.confidence,
            "evidence_id": evidence.id,
        }

    session_obj.soc_draft = {
        "fields": draft_fields,
        "disclaimer": "DRAFT generated from voice transcript. Requires RN review; never auto-finalized.",
    }
    session_obj.status = VoiceSessionStatus.DRAFTED

    db.add(
        ReviewTask(
            subject_type="soc_draft",
            subject_id=session_obj.id,
            episode_id=session_obj.episode_id,
            title="Review voice-generated SOC draft",
            priority="high",
        )
    )
    db.flush()
    return session_obj
