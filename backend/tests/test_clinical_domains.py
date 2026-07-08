"""Medications/FDB prep, infusion management, wound management, voice-to-SOC."""

import pytest

from app.services import fdb, infusion, wounds
from tests.conftest import upload_referral


class TestFdbPreparation:
    def test_strength_parsing(self):
        parsed = fdb.parse_strength("40 mg")
        assert parsed == {"raw": "40 mg", "parsed": True, "value": 40.0, "unit": "mg", "per": None}
        assert fdb.parse_strength("5 mcg/kg")["per"] == "kg"
        assert fdb.parse_strength("weird")["parsed"] is False
        assert fdb.parse_strength(None) is None

    def test_payload_shape(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        client.post(f"/api/v1/documents/{doc['id']}/extract", headers=rn_headers)
        meds = client.get("/api/v1/medications", headers=rn_headers,
                          params={"episode_id": episode["id"]}).json()
        med = next(m for m in meds if m["name"].lower().startswith("furosemide"))
        prepared = client.post(f"/api/v1/medications/{med['id']}/prepare-fdb", headers=rn_headers).json()
        payload = prepared["fdb_payload"]
        assert payload["schema"] == "fdb-prep/1"
        assert payload["drug"]["strength"]["value"] == 40.0
        assert payload["route"]["fdb"]["description"] == "Oral"
        assert payload["schedule"]["fdb"]["times_per_day"] == 2
        assert "drug_drug_interaction" in payload["screening_requested"]
        assert prepared["fdb_prepared_at"] is not None

    def test_null_client_reports_not_configured(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        client.post(f"/api/v1/documents/{doc['id']}/extract", headers=rn_headers)
        result = client.post("/api/v1/medications/screen", headers=rn_headers,
                             params={"episode_id": episode["id"]}).json()
        assert result["configured"] is False
        assert result["payloads_prepared"] >= 5
        assert result["results"] == []  # never fabricates screening output


class TestInfusion:
    def test_rate_math(self):
        assert infusion.compute_rate_ml_hr(100, 60) == 100.0
        assert infusion.compute_rate_ml_hr(250, 90) == 166.67
        assert infusion.compute_duration_minutes(100, 200) == 30
        with pytest.raises(ValueError):
            infusion.compute_rate_ml_hr(0, 60)

    def test_weight_based_conversion(self):
        # 5 mcg/kg/min, 80 kg, 1600 mcg/mL → 15 mL/hr
        assert infusion.mcg_kg_min_to_ml_hr(5, 80, 1600) == 15.0

    def test_order_check_flags_rate_mismatch(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        result = client.post("/api/v1/infusion/orders", headers=rn_headers, json={
            "episode_id": episode["id"], "drug_name": "Vancomycin",
            "volume_ml": 250, "duration_minutes": 120, "rate_ml_hr": 500,  # wrong: should be 125
            "access_type": "PICC",
        }).json()
        ids = {c["check_id"] for c in result["checks"]}
        assert "INF-RATE-001" in ids
        assert "INF-RATE-002" in ids  # 500 > PICC advisory max 400

    def test_rate_autocomputed_when_missing(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        result = client.post("/api/v1/infusion/orders", headers=rn_headers, json={
            "episode_id": episode["id"], "drug_name": "Ceftriaxone",
            "volume_ml": 100, "duration_minutes": 30, "access_type": "PICC",
        }).json()
        assert result["order"]["rate_ml_hr"] == 200.0

    def test_administration_deviation_flagged(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        order = client.post("/api/v1/infusion/orders", headers=rn_headers, json={
            "episode_id": episode["id"], "drug_name": "Ceftriaxone",
            "volume_ml": 100, "duration_minutes": 60, "access_type": "PICC",
        }).json()["order"]
        result = client.post(f"/api/v1/infusion/orders/{order['id']}/administrations",
                             headers=rn_headers, json={
                                 "actual_rate_ml_hr": 150.0,  # ordered 100
                                 "line_patency_confirmed": True, "flush_performed": True,
                             }).json()
        assert any(c["check_id"] == "INF-ADMIN-001" for c in result["checks"])

    def test_line_care_schedule(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        order = client.post("/api/v1/infusion/orders", headers=rn_headers, json={
            "episode_id": episode["id"], "drug_name": "Ceftriaxone",
            "volume_ml": 100, "duration_minutes": 60, "access_type": "PICC",
            "start_date": "2026-07-01",
        }).json()["order"]
        schedule = client.get(f"/api/v1/infusion/orders/{order['id']}/line-care-schedule",
                              headers=rn_headers).json()
        assert schedule[0]["due_date"] == "2026-07-01"
        assert "Dressing change" in schedule[0]["task"]
        assert len(schedule) >= 4  # weekly over 4 weeks


class TestWounds:
    def test_push_score_components(self):
        assert wounds.push_area_score(2.0, 1.5) == 5   # 3.0 cm²
        assert wounds.push_exudate_score("heavy") == 3
        assert wounds.push_tissue_score("eschar") == 4

    def test_pressure_wound_requires_stage(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        resp = client.post("/api/v1/wounds", headers=rn_headers, json={
            "patient_id": patient["id"], "episode_id": episode["id"],
            "location": "sacrum", "wound_type": "pressure",
        })
        assert resp.status_code == 422

    def test_assessment_computes_push_and_trajectory(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        wound = client.post("/api/v1/wounds", headers=rn_headers, json={
            "patient_id": patient["id"], "episode_id": episode["id"],
            "location": "left heel", "wound_type": "pressure", "pressure_stage": "3",
        }).json()["wound"]
        a1 = client.post(f"/api/v1/wounds/{wound['id']}/assessments", headers=rn_headers, json={
            "length_cm": 3.0, "width_cm": 2.0, "tissue_type": "slough", "exudate_amount": "moderate",
        }).json()
        assert a1["push_score"] == 7 + 2 + 3  # area 6cm²→7, moderate→2, slough→3
        client.post(f"/api/v1/wounds/{wound['id']}/assessments", headers=rn_headers, json={
            "length_cm": 2.0, "width_cm": 1.0, "tissue_type": "granulation", "exudate_amount": "light",
        })
        trajectory = client.get(f"/api/v1/wounds/{wound['id']}/trajectory", headers=rn_headers).json()
        assert trajectory["status"] == "improving"
        assert trajectory["delta"] < 0

    def test_reverse_staging_blocked(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        wound = client.post("/api/v1/wounds", headers=rn_headers, json={
            "patient_id": patient["id"], "location": "sacrum",
            "wound_type": "pressure", "pressure_stage": "4",
        }).json()["wound"]
        resp = client.post(f"/api/v1/wounds/{wound['id']}/restage", headers=rn_headers,
                           params={"new_stage": "2"})
        assert resp.status_code == 422
        assert "Reverse staging" in resp.json()["detail"]

    def test_wound_photo_attaches_to_assessment(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        photo = client.post(
            "/api/v1/documents", headers=rn_headers,
            files={"file": ("heel.png", b"\x89PNG fakebytes", "image/png")},
            data={"kind": "wound_photo", "patient_id": patient["id"], "episode_id": episode["id"]},
        ).json()
        wound = client.post("/api/v1/wounds", headers=rn_headers, json={
            "patient_id": patient["id"], "location": "left heel",
            "wound_type": "pressure", "pressure_stage": "2",
        }).json()["wound"]
        assessment = client.post(f"/api/v1/wounds/{wound['id']}/assessments", headers=rn_headers,
                                 json={"length_cm": 1.0, "width_cm": 1.0,
                                       "photo_document_id": photo["id"]}).json()
        assert assessment["assessment"]["photo_document_id"] == photo["id"]


VISIT_TRANSCRIPT = """Start of care visit for Edna Rivera.
Chief complaint: shortness of breath and lower extremity edema following CHF exacerbation.
Vital signs: BP 138/82, heart rate 78, respiratory rate 20, temp 98.2, O2 sat 94 percent on room air.
Pain: patient rates pain 3 out of 10 in lower back.
Medications: reviewed med list, patient confirms furosemide and warfarin, needs teaching on insulin.
Skin assessment: left heel pressure ulcer stage 3, dressing dry and intact.
Homebound status: patient requires taxing effort to ambulate beyond 20 feet with rolling walker.
Plan of care: skilled nursing twice weekly for nine weeks, CHF teaching, medication management.
"""


class TestVoiceToSoc:
    def test_pipeline_produces_evidence_backed_draft(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        resp = client.post(
            "/api/v1/voice/sessions", headers=rn_headers,
            files={"file": ("visit.wav", VISIT_TRANSCRIPT.encode(), "audio/wav")},
            data={"episode_id": episode["id"]},
        )
        assert resp.status_code == 201, resp.text
        session = resp.json()
        assert session["status"] == "drafted"
        assert session["transcription_confidence"] == 0.95

        fields = session["soc_draft"]["fields"]
        assert fields["vital.blood_pressure"]["value"] == "138/82"
        assert fields["vital.oxygen_saturation"]["value"] == "94"
        assert fields["vital.pain_score"]["value"] == "3"
        assert "section.medications" in fields
        assert "section.homebound" in fields
        for f in fields.values():
            assert f["evidence_id"]
            assert 0 < f["confidence"] <= 1

        # draft flagged as requiring review, never auto-final
        assert "never auto-finalized" in session["soc_draft"]["disclaimer"].lower() or \
               "requires rn review" in session["soc_draft"]["disclaimer"].lower()
        tasks = client.get("/api/v1/review/tasks", headers=rn_headers).json()
        assert any(t["subject_type"] == "soc_draft" and t["subject_id"] == session["id"] for t in tasks)

    def test_binary_audio_fails_gracefully_with_stub(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        resp = client.post(
            "/api/v1/voice/sessions", headers=rn_headers,
            files={"file": ("visit.wav", b"\x00\x01\x02RIFF\xff\xfe", "audio/wav")},
            data={"episode_id": episode["id"]},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "failed"

    def test_evidence_spans_point_into_transcript(self, client, rn_headers, patient_episode, db):
        _, episode = patient_episode
        session = client.post(
            "/api/v1/voice/sessions", headers=rn_headers,
            files={"file": ("visit.wav", VISIT_TRANSCRIPT.encode(), "audio/wav")},
            data={"episode_id": episode["id"]},
        ).json()
        ev_id = session["soc_draft"]["fields"]["vital.blood_pressure"]["evidence_id"]
        evidence = client.get(f"/api/v1/evidence/{ev_id}", headers=rn_headers).json()
        span_text = VISIT_TRANSCRIPT[evidence["span_start"]:evidence["span_end"]]
        assert "138/82" in span_text
