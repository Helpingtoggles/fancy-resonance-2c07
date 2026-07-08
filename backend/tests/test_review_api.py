"""RN review workflow via the API + health/safety surface."""


def _make_soc_draft_task(client, rn_headers, episode_id):
    resp = client.post(
        "/api/v1/voice/sessions", headers=rn_headers,
        files={"file": ("visit.wav", b"Vitals: BP 120/70. Plan: SN visits.", "audio/wav")},
        data={"episode_id": episode_id},
    )
    session = resp.json()
    tasks = client.get("/api/v1/review/tasks", headers=rn_headers).json()
    return next(t for t in tasks if t["subject_id"] == session["id"])


class TestReviewApi:
    def test_lifecycle_claim_approve_sign(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        task = _make_soc_draft_task(client, rn_headers, episode["id"])

        for action, expected in (("claim", "in_review"), ("approve", "approved")):
            body = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                               json={"action": action}).json()
            assert body["status"] == expected

        signed = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                             json={"action": "sign",
                                   "attestation": "I reviewed this SOC draft and attest to its accuracy."})
        assert signed.status_code == 200
        assert signed.json()["status"] == "signed"

    def test_request_changes_loop(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        task = _make_soc_draft_task(client, rn_headers, episode["id"])
        client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers, json={"action": "claim"})
        body = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                           json={"action": "request_changes", "note": "Missing wound measurements"}).json()
        assert body["status"] == "changes_requested"
        body = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                           json={"action": "resume"}).json()
        assert body["status"] == "in_review"

    def test_invalid_transition_rejected(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        task = _make_soc_draft_task(client, rn_headers, episode["id"])
        resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                           json={"action": "approve"})  # not claimed yet
        assert resp.status_code == 409

    def test_clinician_sign_rejected_via_api(self, client, rn_headers, clinician_headers, patient_episode):
        _, episode = patient_episode
        task = _make_soc_draft_task(client, rn_headers, episode["id"])
        client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers, json={"action": "claim"})
        client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers, json={"action": "approve"})
        resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=clinician_headers,
                           json={"action": "sign",
                                 "attestation": "I reviewed this SOC draft and attest to its accuracy."})
        assert resp.status_code == 403

    def test_readonly_cannot_act(self, client, rn_headers, readonly_headers, patient_episode):
        _, episode = patient_episode
        task = _make_soc_draft_task(client, rn_headers, episode["id"])
        resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=readonly_headers,
                           json={"action": "claim"})
        assert resp.status_code == 403


class TestHealth:
    def test_health_reports_safety_posture(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "disabled" in body["safety"]["auto_sign"]
        assert "disabled" in body["safety"]["auto_submit"]
        assert "disabled" in body["safety"]["ai_final_oasis_codes"]
