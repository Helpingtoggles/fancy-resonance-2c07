"""The platform's non-negotiable clinical safety guarantees.

These tests are the executable specification for:
  1. Never auto-submit documentation.
  2. Never auto-sign documentation.
  3. Never generate final OASIS codes (AI writes suggestions only).
  4. Every extracted field carries evidence + confidence.
"""

import pytest

from app.core import safety
from app.core.config import get_settings
from app.core.safety import SafetyViolation
from app.services import workflow_dsl


class TestStartupInvariants:
    def test_defaults_are_safe(self):
        s = get_settings()
        assert s.allow_auto_submit is False
        assert s.allow_auto_sign is False
        assert s.allow_ai_final_codes is False

    def test_startup_refuses_auto_sign(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "allow_auto_sign", True)
        with pytest.raises(SafetyViolation, match="auto-signed"):
            safety.enforce_safety_invariants()

    def test_startup_refuses_auto_submit(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "allow_auto_submit", True)
        with pytest.raises(SafetyViolation, match="auto-submitted"):
            safety.enforce_safety_invariants()

    def test_startup_refuses_ai_final_codes(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "allow_ai_final_codes", True)
        with pytest.raises(SafetyViolation, match="final OASIS"):
            safety.enforce_safety_invariants()


class TestActorGuards:
    @pytest.mark.parametrize("kind", ["system", "service", "ai", "extractor", "workflow", "scheduler"])
    def test_non_human_actors_cannot_sign(self, kind):
        with pytest.raises(SafetyViolation):
            safety.assert_human_actor(kind, "review.sign")

    def test_human_actor_allowed(self):
        safety.assert_human_actor("human", "review.sign")  # no raise

    @pytest.mark.parametrize("action", sorted(safety.FORBIDDEN_AUTOMATED_ACTIONS))
    def test_forbidden_actions_blocked_for_automation(self, action):
        with pytest.raises(SafetyViolation):
            safety.assert_action_allowed_for_automation(action)


class TestDslCannotSign:
    @pytest.mark.parametrize("action", ["sign", "auto_sign", "submit", "auto_submit", "finalize_oasis"])
    def test_compiler_rejects_forbidden_actions(self, action):
        source = f"""workflow bad v1
state start initial
  do {action} "sneaky"
  on go -> done
state done terminal
"""
        with pytest.raises(SafetyViolation, match="forbidden"):
            workflow_dsl.compile_dsl(source)

    def test_unknown_actions_rejected(self):
        source = """workflow bad v1
state start initial
  do transmit_to_cms "x"
  on go -> done
state done terminal
"""
        with pytest.raises((SafetyViolation, workflow_dsl.DslError)):
            workflow_dsl.compile_dsl(source)


class TestNoAutoFinalOasis:
    def test_engine_only_writes_suggestions(self, client, rn_headers, patient_episode):
        from tests.conftest import upload_referral

        patient, episode = patient_episode
        upload_referral(client, rn_headers, patient["id"], episode["id"])
        assessment = client.post("/api/v1/oasis", headers=rn_headers,
                                 json={"episode_id": episode["id"],
                                       "assessment_type": "start_of_care"}).json()
        result = client.post(f"/api/v1/oasis/{assessment['id']}/suggest", headers=rn_headers).json()
        assert result["suggestions_applied"] > 0

        items = client.get(f"/api/v1/oasis/{assessment['id']}/items", headers=rn_headers).json()
        suggested = [i for i in items if i["suggested_value"] is not None]
        assert suggested, "engine should have produced suggestions"
        for item in items:
            # THE invariant: AI never writes final values.
            assert item["final_value"] is None
            assert item["finalized_by"] is None
        for item in suggested:
            assert item["suggested_confidence"] is not None
            assert item["evidence_ids"], f"suggestion without evidence: {item['item_id']}"
            assert item["suggested_by"].startswith("oasis-e2-engine")

    def test_export_requires_signed_assessment(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        assessment = client.post("/api/v1/oasis", headers=rn_headers,
                                 json={"episode_id": episode["id"],
                                       "assessment_type": "start_of_care"}).json()
        resp = client.post(f"/api/v1/oasis/{assessment['id']}/export", headers=rn_headers)
        assert resp.status_code == 409
        assert "signed" in resp.json()["detail"].lower()


class TestSignGuardrails:
    def _make_task(self, db, subject_type="soc_draft", subject_id="subj-1"):
        from app.models.review import ReviewTask

        task = ReviewTask(subject_type=subject_type, subject_id=subject_id, title="t")
        db.add(task)
        db.commit()
        return task

    def test_service_actor_cannot_approve(self, db, users):
        from app.models.user import Role
        from app.services import review

        task = self._make_task(db)
        rn = users[Role.RN_REVIEWER]
        review.act_on_task(db, task=task, actor=rn, action="claim")
        with pytest.raises(SafetyViolation):
            review.act_on_task(db, task=task, actor=rn, action="approve", actor_kind="service")

    def test_clinician_cannot_sign(self, db, users):
        from app.models.user import Role
        from app.services import review

        task = self._make_task(db)
        clin = users[Role.CLINICIAN]
        review.act_on_task(db, task=task, actor=clin, action="claim")
        review.act_on_task(db, task=task, actor=users[Role.RN_REVIEWER], action="approve")
        with pytest.raises(SafetyViolation, match="may not sign"):
            review.act_on_task(db, task=task, actor=clin, action="sign",
                               attestation="I attest to reviewing this document fully.")

    def test_admin_cannot_sign(self, db, users):
        """Even admins can't sign — signing is a clinical act reserved to RNs."""
        from app.models.user import Role
        from app.services import review

        task = self._make_task(db)
        admin = users[Role.ADMIN]
        review.act_on_task(db, task=task, actor=admin, action="claim")
        review.act_on_task(db, task=task, actor=admin, action="approve")
        with pytest.raises(SafetyViolation, match="may not sign"):
            review.act_on_task(db, task=task, actor=admin, action="sign",
                               attestation="I attest to reviewing this document fully.")

    def test_sign_requires_attestation(self, db, users):
        from app.models.user import Role
        from app.services import review

        task = self._make_task(db)
        rn = users[Role.RN_REVIEWER]
        review.act_on_task(db, task=task, actor=rn, action="claim")
        review.act_on_task(db, task=task, actor=rn, action="approve")
        with pytest.raises(review.ReviewError, match="attestation"):
            review.act_on_task(db, task=task, actor=rn, action="sign", attestation="")

    def test_sign_requires_approved_status(self, db, users):
        """No skipping straight to signed — the workflow must be walked."""
        from app.models.user import Role
        from app.services import review

        task = self._make_task(db)
        with pytest.raises(review.ReviewError):
            review.act_on_task(db, task=task, actor=users[Role.RN_REVIEWER], action="sign",
                               attestation="I attest to reviewing this document fully.")
