"""OCR pipeline, document ingestion, medication + order extraction."""

from app.services.extraction.medications import extract_medications_from_text, parse_medication_line
from app.services.extraction.orders import extract_orders_from_text
from tests.conftest import REFERRAL_TEXT, upload_referral


class TestIngestion:
    def test_upload_runs_ocr(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        assert doc["status"] == "ocr_complete"
        pages = client.get(f"/api/v1/documents/{doc['id']}/pages", headers=rn_headers).json()
        assert len(pages) == 1
        assert "Furosemide" in pages[0]["text"]
        assert pages[0]["ocr_confidence"] > 0.9

    def test_duplicate_upload_dedupes(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        d1 = upload_referral(client, rn_headers, patient["id"], episode["id"])
        d2 = upload_referral(client, rn_headers, patient["id"], episode["id"])
        assert d1["id"] == d2["id"]

    def test_empty_upload_rejected(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        resp = client.post(
            "/api/v1/documents", headers=rn_headers,
            files={"file": ("empty.txt", b"", "text/plain")},
            data={"kind": "referral", "patient_id": patient["id"], "episode_id": episode["id"]},
        )
        assert resp.status_code == 400

    def test_binary_image_gets_zero_confidence_page_with_stub_engine(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        png_bytes = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        resp = client.post(
            "/api/v1/documents", headers=rn_headers,
            files={"file": ("wound.png", png_bytes, "image/png")},
            data={"kind": "wound_photo", "patient_id": patient["id"], "episode_id": episode["id"]},
        )
        assert resp.status_code == 201
        pages = client.get(f"/api/v1/documents/{resp.json()['id']}/pages", headers=rn_headers).json()
        assert pages[0]["ocr_confidence"] == 0.0  # flagged for manual transcription

    def test_readonly_cannot_upload(self, client, readonly_headers):
        resp = client.post(
            "/api/v1/documents", headers=readonly_headers,
            files={"file": ("x.txt", b"hello", "text/plain")}, data={"kind": "other"},
        )
        assert resp.status_code == 403


class TestMedicationParsing:
    def test_full_sig(self):
        parsed = parse_medication_line("Furosemide 40 mg PO BID")
        assert parsed.name == "Furosemide"
        assert parsed.strength == "40 mg"
        assert parsed.route == "PO"
        assert parsed.frequency == "BID"
        assert parsed.prn is False

    def test_prn_with_reason(self):
        parsed = parse_medication_line("Acetaminophen 500 mg 1 tablet PO q6h PRN for pain")
        assert parsed.prn is True
        assert "pain" in (parsed.prn_reason or "")
        assert parsed.dose == "1 tablet"
        assert parsed.frequency == "Q6H"

    def test_subq_insulin(self):
        parsed = parse_medication_line("Insulin glargine 20 units SubQ at bedtime")
        assert parsed.name.lower().startswith("insulin")
        assert parsed.route == "SUBQ"
        assert parsed.frequency == "QHS"

    def test_non_med_lines_skipped(self):
        assert parse_medication_line("Patient: Edna Rivera DOB 03/12/1948") is None
        assert parse_medication_line("Diagnosis: CHF exacerbation") is None
        assert parse_medication_line("") is None

    def test_extract_from_referral_text(self):
        meds = extract_medications_from_text(REFERRAL_TEXT)
        names = {m.name.split()[0].lower() for m in meds}
        assert {"furosemide", "metoprolol", "warfarin", "insulin", "acetaminophen"} <= names

    def test_field_spans_point_into_source(self):
        text = "Meds:\nWarfarin 5 mg PO daily\n"
        meds = extract_medications_from_text(text)
        assert len(meds) == 1
        start, end = meds[0].field_spans["strength"]
        assert text[start:end] == "5 mg"


class TestOrderParsing:
    def test_referral_orders(self):
        orders = extract_orders_from_text(REFERRAL_TEXT)
        types = {o.order_type for o in orders}
        assert "sn_frequency" in types
        assert "therapy" in types
        assert "wound_care" in types

    def test_physician_and_verbal_flags(self):
        orders = extract_orders_from_text(REFERRAL_TEXT)
        sn = next(o for o in orders if o.order_type == "sn_frequency")
        assert sn.physician == "Amara Okafor"
        assert sn.npi == "1234567890"
        assert sn.is_verbal is True
        assert sn.cert_period is not None


class TestEndToEndExtraction:
    def test_extract_endpoint_persists_meds_orders_with_evidence(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        result = client.post(f"/api/v1/documents/{doc['id']}/extract", headers=rn_headers).json()
        assert result["medications_extracted"] >= 5
        assert result["orders_extracted"] >= 3

        meds = client.get("/api/v1/medications", headers=rn_headers,
                          params={"episode_id": episode["id"]}).json()
        assert all(m["status"] == "extracted" for m in meds)  # never auto-active
        warfarin = next(m for m in meds if m["name"].lower().startswith("warfarin"))
        assert warfarin["is_high_risk"] is True

        # every extracted field must have evidence + confidence
        fields = client.get(f"/api/v1/documents/{doc['id']}/fields", headers=rn_headers).json()
        assert len(fields) > 10
        for f in fields:
            assert f["evidence_id"], f
            assert 0.0 <= f["confidence"] <= 1.0
            ev = client.get(f"/api/v1/evidence/{f['evidence_id']}", headers=rn_headers).json()
            assert ev["snippet"].strip()

        # ledger remains verifiable
        assert client.get("/api/v1/evidence/ledger/verify", headers=rn_headers).json()["valid"] is True

    def test_field_review_accept_edit_reject(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        client.post(f"/api/v1/documents/{doc['id']}/extract", headers=rn_headers)
        fields = client.get(f"/api/v1/documents/{doc['id']}/fields", headers=rn_headers).json()

        f0 = fields[0]
        accepted = client.post(f"/api/v1/evidence/fields/{f0['id']}/review", headers=rn_headers,
                               json={"action": "accept"}).json()
        assert accepted["status"] == "accepted"
        assert accepted["final_value"] == f0["suggested_value"]

        f1 = fields[1]
        edited = client.post(f"/api/v1/evidence/fields/{f1['id']}/review", headers=rn_headers,
                             json={"action": "edit", "final_value": "corrected", "note": "OCR misread"}).json()
        assert edited["status"] == "edited"
        assert edited["final_value"] == "corrected"

        # double review is blocked
        resp = client.post(f"/api/v1/evidence/fields/{f0['id']}/review", headers=rn_headers,
                           json={"action": "reject"})
        assert resp.status_code == 409

    def test_readonly_cannot_review_fields(self, client, rn_headers, readonly_headers, patient_episode):
        patient, episode = patient_episode
        doc = upload_referral(client, rn_headers, patient["id"], episode["id"])
        client.post(f"/api/v1/documents/{doc['id']}/extract", headers=rn_headers)
        fields = client.get(f"/api/v1/documents/{doc['id']}/fields", headers=rn_headers).json()
        resp = client.post(f"/api/v1/evidence/fields/{fields[0]['id']}/review",
                           headers=readonly_headers, json={"action": "accept"})
        assert resp.status_code == 403
