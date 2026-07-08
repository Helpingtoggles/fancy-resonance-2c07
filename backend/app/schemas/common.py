"""Pydantic schemas shared across routers."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth / users ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12)
    full_name: str
    role: str
    credentials: str | None = None


class UserOut(ORMModel):
    id: str
    email: str
    full_name: str
    role: str
    credentials: str | None
    is_active: bool


# --- Patients / episodes ---

class PatientCreate(BaseModel):
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    sex: str | None = None
    payer: str | None = None
    medicare_id: str | None = None
    address: str | None = None
    phone: str | None = None
    primary_physician: str | None = None


class PatientOut(ORMModel):
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: date | None
    sex: str | None
    payer: str | None
    primary_physician: str | None


class EpisodeCreate(BaseModel):
    patient_id: str
    referral_date: date | None = None
    soc_date: date | None = None
    cert_period_start: date | None = None
    cert_period_end: date | None = None
    primary_diagnosis: str | None = None
    primary_diagnosis_code: str | None = None
    referring_physician: str | None = None
    face_to_face_date: date | None = None
    homebound_narrative: str | None = None


class EpisodeUpdate(BaseModel):
    status: str | None = None
    soc_date: date | None = None
    cert_period_start: date | None = None
    cert_period_end: date | None = None
    primary_diagnosis: str | None = None
    primary_diagnosis_code: str | None = None
    face_to_face_date: date | None = None
    homebound_narrative: str | None = None


class EpisodeOut(ORMModel):
    id: str
    patient_id: str
    status: str
    referral_date: date | None
    soc_date: date | None
    cert_period_start: date | None
    cert_period_end: date | None
    primary_diagnosis: str | None
    primary_diagnosis_code: str | None
    referring_physician: str | None
    face_to_face_date: date | None
    homebound_narrative: str | None


# --- Documents / evidence ---

class DocumentOut(ORMModel):
    id: str
    patient_id: str | None
    episode_id: str | None
    kind: str
    status: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    ocr_engine: str | None
    created_at: datetime


class DocumentPageOut(ORMModel):
    page_number: int
    text: str
    ocr_confidence: float | None


class EvidenceOut(ORMModel):
    id: str
    document_id: str | None
    page_number: int | None
    span_start: int | None
    span_end: int | None
    snippet: str
    method: str
    method_version: str
    confidence: float
    created_at: datetime


class ExtractedFieldOut(ORMModel):
    id: str
    entity_type: str
    entity_id: str | None
    field_name: str
    suggested_value: str | None
    confidence: float
    evidence_id: str
    extractor_name: str
    extractor_version: str
    status: str
    final_value: str | None
    reviewed_by: str | None
    review_note: str | None


class FieldReviewRequest(BaseModel):
    action: str = Field(pattern="^(accept|edit|reject)$")
    final_value: str | None = None
    note: str | None = None


# --- Medications / orders ---

class MedicationOut(ORMModel):
    id: str
    patient_id: str
    episode_id: str | None
    name: str
    strength: str | None
    dose: str | None
    route: str | None
    frequency: str | None
    prn: bool
    prn_reason: str | None
    status: str
    is_high_risk: bool
    source_document_id: str | None
    fdb_payload: dict | None
    fdb_prepared_at: datetime | None


class MedicationUpdate(BaseModel):
    status: str | None = None
    name: str | None = None
    strength: str | None = None
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    prn: bool | None = None
    indication: str | None = None


class PhysicianOrderOut(ORMModel):
    id: str
    episode_id: str
    order_type: str | None
    order_text: str
    ordering_physician: str | None
    npi: str | None
    order_date: date | None
    is_verbal: bool
    status: str
    source_document_id: str | None
    signed_date: date | None


class OrderStatusUpdate(BaseModel):
    status: str
    signed_date: date | None = None


# --- Infusion ---

class InfusionOrderCreate(BaseModel):
    episode_id: str
    drug_name: str
    dose_value: float | None = None
    dose_unit: str | None = None
    diluent: str | None = None
    volume_ml: float | None = None
    rate_ml_hr: float | None = None
    duration_minutes: int | None = None
    frequency: str | None = None
    access_type: str | None = None
    line_flush_protocol: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class InfusionOrderOut(ORMModel):
    id: str
    episode_id: str
    drug_name: str
    dose_value: float | None
    dose_unit: str | None
    volume_ml: float | None
    rate_ml_hr: float | None
    duration_minutes: int | None
    frequency: str | None
    access_type: str | None
    line_flush_protocol: str | None
    status: str


class InfusionAdministrationCreate(BaseModel):
    started_at: datetime | None = None
    ended_at: datetime | None = None
    actual_rate_ml_hr: float | None = None
    site_assessment: str | None = None
    line_patency_confirmed: bool = False
    flush_performed: bool = False
    complications: str | None = None
    notes: str | None = None


# --- Wounds ---

class WoundCreate(BaseModel):
    patient_id: str
    episode_id: str | None = None
    location: str
    wound_type: str
    pressure_stage: str | None = None
    onset_date: date | None = None


class WoundOut(ORMModel):
    id: str
    patient_id: str
    episode_id: str | None
    location: str
    wound_type: str
    pressure_stage: str | None
    status: str


class WoundAssessmentCreate(BaseModel):
    length_cm: float | None = None
    width_cm: float | None = None
    depth_cm: float | None = None
    undermining: str | None = None
    tunneling: str | None = None
    tissue_type: str | None = None
    exudate_amount: str | None = None
    exudate_type: str | None = None
    odor: bool = False
    periwound: str | None = None
    pain_score: int | None = None
    treatment_performed: str | None = None
    photo_document_id: str | None = None
    notes: str | None = None


class WoundAssessmentOut(ORMModel):
    id: str
    wound_id: str
    assessed_at: datetime
    length_cm: float | None
    width_cm: float | None
    depth_cm: float | None
    tissue_type: str | None
    exudate_amount: str | None
    push_score: int | None
    photo_document_id: str | None


# --- OASIS ---

class OasisCreate(BaseModel):
    episode_id: str
    assessment_type: str


class OasisItemOut(ORMModel):
    item_id: str
    suggested_value: str | None
    suggested_confidence: float | None
    suggested_rationale: str | None
    evidence_ids: list | None
    suggested_by: str | None
    final_value: str | None
    finalized_by: str | None
    skipped: str | None


class OasisOut(ORMModel):
    id: str
    episode_id: str
    assessment_type: str
    status: str
    oasis_version: str
    signed_by: str | None
    signed_at: datetime | None
    created_at: datetime


class OasisItemFinalize(BaseModel):
    value: str


# --- Review ---

class ReviewTaskOut(ORMModel):
    id: str
    subject_type: str
    subject_id: str
    episode_id: str | None
    title: str
    status: str
    priority: str
    assigned_to: str | None
    created_at: datetime


class ReviewActionRequest(BaseModel):
    action: str = Field(pattern="^(claim|request_changes|resume|approve|sign|cancel)$")
    note: str | None = None
    attestation: str | None = None


# --- Workflows ---

class WorkflowDefinitionCreate(BaseModel):
    dsl_source: str


class WorkflowDefinitionOut(ORMModel):
    id: str
    name: str
    version: int
    compiled: dict
    is_active: bool


class WorkflowStartRequest(BaseModel):
    definition_id: str
    subject_type: str
    subject_id: str
    context: dict = {}


class WorkflowEventRequest(BaseModel):
    event: str
    context_updates: dict = {}


class WorkflowInstanceOut(ORMModel):
    id: str
    definition_id: str
    subject_type: str
    subject_id: str
    current_state: str
    context: dict
    is_complete: bool


# --- Voice ---

class VoiceSessionOut(ORMModel):
    id: str
    episode_id: str
    status: str
    transcript: str | None
    transcription_engine: str | None
    transcription_confidence: float | None
    soc_draft: dict | None
    created_at: datetime
