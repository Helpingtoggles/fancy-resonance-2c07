"""Audit log hash chain + Evidence Ledger integrity."""

import pytest

from app.services import audit, evidence_ledger


class TestAuditChain:
    def test_chain_valid_after_writes(self, db):
        for i in range(5):
            audit.record(db, action=f"test.event{i}", detail={"i": i})
        db.commit()
        assert audit.verify_chain(db)["valid"] is True

    def test_tamper_detected(self, db):
        audit.record(db, action="test.a")
        entry = audit.record(db, action="test.b", detail={"x": 1})
        audit.record(db, action="test.c")
        db.commit()
        entry.detail = {"x": 999}  # simulate tampering
        db.commit()
        result = audit.verify_chain(db)
        assert result["valid"] is False
        assert result["first_invalid_id"] == entry.id

    def test_state_changes_are_audited_via_api(self, client, rn_headers, auditor_headers):
        client.post("/api/v1/patients", headers=rn_headers,
                    json={"mrn": "AUD-1", "first_name": "A", "last_name": "B"})
        entries = client.get("/api/v1/audit", headers=auditor_headers,
                             params={"action": "patient.created"}).json()
        assert len(entries) == 1
        assert entries[0]["actor_role"] == "rn_reviewer"
        verify = client.get("/api/v1/audit/verify", headers=auditor_headers).json()
        assert verify["valid"] is True


class TestEvidenceLedger:
    def test_append_and_verify(self, db):
        for i in range(4):
            evidence_ledger.append_evidence(
                db, snippet=f"line {i}", method="test", confidence=0.5 + i / 10
            )
        db.commit()
        assert evidence_ledger.verify_chain(db)["valid"] is True

    def test_empty_snippet_rejected(self, db):
        with pytest.raises(ValueError, match="non-empty"):
            evidence_ledger.append_evidence(db, snippet="   ", method="test", confidence=0.5)

    def test_confidence_bounds_enforced(self, db):
        with pytest.raises(ValueError, match="confidence"):
            evidence_ledger.append_evidence(db, snippet="x", method="test", confidence=1.5)

    def test_tamper_detected(self, db):
        evidence_ledger.append_evidence(db, snippet="a", method="test", confidence=0.9)
        target = evidence_ledger.append_evidence(db, snippet="b", method="test", confidence=0.9)
        evidence_ledger.append_evidence(db, snippet="c", method="test", confidence=0.9)
        db.commit()
        target.snippet = "b (altered)"
        db.commit()
        result = evidence_ledger.verify_chain(db)
        assert result["valid"] is False
        assert result["first_invalid_seq"] == target.seq

    def test_extracted_field_requires_persisted_evidence(self, db):
        from app.models.evidence import EvidenceRecord

        with pytest.raises(ValueError, match="persisted EvidenceRecord"):
            evidence_ledger.create_extracted_field(
                db, entity_type="medication", field_name="name",
                suggested_value="x", evidence=EvidenceRecord(), extractor_name="t",
            )

    def test_field_starts_suggested_with_confidence(self, db):
        ev = evidence_ledger.append_evidence(db, snippet="Lisinopril 10 mg", method="test", confidence=0.8)
        field = evidence_ledger.create_extracted_field(
            db, entity_type="medication", field_name="name",
            suggested_value="Lisinopril", evidence=ev, extractor_name="test",
        )
        assert field.status.value == "suggested"
        assert field.final_value is None
        assert field.confidence == 0.8
        assert field.evidence_id == ev.id
