"""OASIS-E2 engine: item instantiation, skip logic, RN finalization, signing flow."""

from app.services.oasis_catalog import items_for_time_point
from tests.conftest import upload_referral


def _create_assessment(client, headers, episode_id, a_type="start_of_care"):
    resp = client.post("/api/v1/oasis", headers=headers,
                       json={"episode_id": episode_id, "assessment_type": a_type})
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestTimePoints:
    def test_soc_has_more_items_than_transfer(self):
        assert len(items_for_time_point("start_of_care")) > len(items_for_time_point("transfer"))

    def test_transfer_includes_emergent_care(self):
        ids = {i.item_id for i in items_for_time_point("transfer")}
        assert "M2301" in ids and "M0906" in ids and "M1800" not in ids

    def test_assessment_instantiates_correct_items(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"], "transfer")
        items = client.get(f"/api/v1/oasis/{assessment['id']}/items", headers=rn_headers).json()
        assert {i["item_id"] for i in items} == {i.item_id for i in items_for_time_point("transfer")}


class TestSkipLogic:
    def test_gated_item_skipped_when_gate_negative(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"])
        aid = assessment["id"]
        # RN finalizes M1306 = 0 (no stage-2+ pressure ulcer)
        resp = client.post(f"/api/v1/oasis/{aid}/items/M1306/finalize", headers=rn_headers,
                           json={"value": "0"})
        assert resp.status_code == 200
        items = {i["item_id"]: i for i in client.get(f"/api/v1/oasis/{aid}/items", headers=rn_headers).json()}
        assert items["M1324"]["skipped"] is not None
        assert items["M1311"]["skipped"] is not None

    def test_gated_item_active_when_gate_positive(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"])
        aid = assessment["id"]
        client.post(f"/api/v1/oasis/{aid}/items/M1306/finalize", headers=rn_headers, json={"value": "1"})
        items = {i["item_id"]: i for i in client.get(f"/api/v1/oasis/{aid}/items", headers=rn_headers).json()}
        assert items["M1324"]["skipped"] is None


class TestFinalization:
    def test_only_rn_can_finalize(self, client, clinician_headers, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"])
        resp = client.post(f"/api/v1/oasis/{assessment['id']}/items/M1800/finalize",
                           headers=clinician_headers, json={"value": "1"})
        assert resp.status_code == 403

    def test_domain_enforced_on_finalize(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"])
        resp = client.post(f"/api/v1/oasis/{assessment['id']}/items/M1800/finalize",
                           headers=rn_headers, json={"value": "9"})
        assert resp.status_code == 422

    def test_finalize_records_reviewer(self, client, rn_headers, patient_episode):
        _, episode = patient_episode
        assessment = _create_assessment(client, rn_headers, episode["id"])
        client.post(f"/api/v1/oasis/{assessment['id']}/items/M1800/finalize",
                    headers=rn_headers, json={"value": "2"})
        items = {i["item_id"]: i for i in
                 client.get(f"/api/v1/oasis/{assessment['id']}/items", headers=rn_headers).json()}
        assert items["M1800"]["final_value"] == "2"
        assert items["M1800"]["finalized_by"] is not None

    def test_completeness_counts_only_finalized(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        upload_referral(client, rn_headers, patient["id"], episode["id"])
        assessment = _create_assessment(client, rn_headers, episode["id"])
        aid = assessment["id"]
        client.post(f"/api/v1/oasis/{aid}/suggest", headers=rn_headers)
        comp = client.get(f"/api/v1/oasis/{aid}/completeness", headers=rn_headers).json()
        assert comp["complete"] is False
        assert comp["finalized"] == 0
        assert comp["suggested_awaiting_review"] > 0


class TestFullSigningFlow:
    def _finalize_all(self, client, headers, aid):
        items = client.get(f"/api/v1/oasis/{aid}/items", headers=headers).json()
        safe_values = {"date": "2026-06-26", "text": "I50.23", "number": "63"}
        for item in items:
            if item["skipped"]:
                continue
            if item["value_type"] in ("code", "multiselect") and item["allowed_values"]:
                value = item["suggested_value"] if item["suggested_value"] in item["allowed_values"] \
                    else item["allowed_values"][0]
            else:
                value = safe_values.get(item["value_type"], "reviewed")
            resp = client.post(f"/api/v1/oasis/{aid}/items/{item['item_id']}/finalize",
                               headers=headers, json={"value": value})
            assert resp.status_code == 200, (item["item_id"], resp.text)
        # re-fetch: skip logic may have activated/deactivated gated items
        items = client.get(f"/api/v1/oasis/{aid}/items", headers=headers).json()
        for item in items:
            if not item["skipped"] and item["final_value"] is None and item["value_type"] == "code":
                client.post(f"/api/v1/oasis/{aid}/items/{item['item_id']}/finalize",
                            headers=headers, json={"value": item["allowed_values"][0]})

    def test_sign_blocked_until_complete_then_succeeds(self, client, rn_headers, patient_episode):
        patient, episode = patient_episode
        upload_referral(client, rn_headers, patient["id"], episode["id"])
        assessment = _create_assessment(client, rn_headers, episode["id"])
        aid = assessment["id"]
        client.post(f"/api/v1/oasis/{aid}/suggest", headers=rn_headers)

        tasks = client.get("/api/v1/review/tasks", headers=rn_headers).json()
        task = next(t for t in tasks if t["subject_type"] == "oasis_assessment" and t["subject_id"] == aid)

        # Walk to approved with items incomplete
        for action in ("claim", "approve"):
            resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                               json={"action": action})
            assert resp.status_code == 200, resp.text

        # Sign blocked: items not finalized
        resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                           json={"action": "sign",
                                 "attestation": "I have reviewed this assessment and attest to its accuracy."})
        assert resp.status_code == 409
        assert "finalized" in resp.json()["detail"]

        # RN finalizes everything, then signing succeeds
        self._finalize_all(client, rn_headers, aid)
        comp = client.get(f"/api/v1/oasis/{aid}/completeness", headers=rn_headers).json()
        assert comp["complete"] is True, comp

        resp = client.post(f"/api/v1/review/tasks/{task['id']}/act", headers=rn_headers,
                           json={"action": "sign",
                                 "attestation": "I have reviewed this assessment and attest to its accuracy."})
        assert resp.status_code == 200, resp.text

        signed = client.get(f"/api/v1/oasis/{aid}", headers=rn_headers).json()
        assert signed["status"] == "signed"
        assert signed["signed_by"] is not None

        # items frozen after signing
        resp = client.post(f"/api/v1/oasis/{aid}/items/M1800/finalize", headers=rn_headers,
                           json={"value": "0"})
        assert resp.status_code == 409

        # export now allowed, produces final values only
        export = client.post(f"/api/v1/oasis/{aid}/export", headers=rn_headers).json()
        assert export["items"]
        assert "transmission" in export["note"].lower() or "human" in export["note"].lower()
