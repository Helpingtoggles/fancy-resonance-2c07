"""Authentication and role-based access control."""

from app.models.user import Role
from tests.conftest import PASSWORD, auth_headers


class TestAuth:
    def test_login_success_returns_tokens(self, client, users):
        resp = client.post("/api/v1/auth/login",
                           json={"email": users[Role.RN_REVIEWER].email, "password": PASSWORD})
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] and body["refresh_token"]

    def test_login_wrong_password_rejected_and_audited(self, client, users, auditor_headers):
        resp = client.post("/api/v1/auth/login",
                           json={"email": users[Role.RN_REVIEWER].email, "password": "wrong-password"})
        assert resp.status_code == 401
        entries = client.get("/api/v1/audit", headers=auditor_headers,
                             params={"action": "auth.login_failed"}).json()
        assert len(entries) == 1

    def test_me_requires_token(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_returns_profile(self, client, rn_headers):
        body = client.get("/api/v1/auth/me", headers=rn_headers).json()
        assert body["role"] == "rn_reviewer"

    def test_refresh_flow(self, client, users):
        tokens = client.post("/api/v1/auth/login",
                             json={"email": users[Role.CLINICIAN].email, "password": PASSWORD}).json()
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    def test_access_token_cannot_be_used_as_refresh(self, client, users):
        tokens = client.post("/api/v1/auth/login",
                             json={"email": users[Role.CLINICIAN].email, "password": PASSWORD}).json()
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
        assert resp.status_code == 401

    def test_garbage_token_rejected(self, client):
        resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401


class TestRBAC:
    def test_readonly_cannot_create_patient(self, client, readonly_headers):
        resp = client.post("/api/v1/patients", headers=readonly_headers,
                           json={"mrn": "X1", "first_name": "A", "last_name": "B"})
        assert resp.status_code == 403

    def test_readonly_can_list_patients(self, client, readonly_headers):
        assert client.get("/api/v1/patients", headers=readonly_headers).status_code == 200

    def test_intake_can_create_patient_but_not_medications(self, client, intake_headers, users, db):
        resp = client.post("/api/v1/patients", headers=intake_headers,
                           json={"mrn": "X2", "first_name": "A", "last_name": "B"})
        assert resp.status_code == 201
        # intake cannot reconcile medications
        resp = client.patch("/api/v1/medications/nonexistent", headers=intake_headers,
                            json={"status": "active"})
        assert resp.status_code == 403

    def test_only_admin_manages_users(self, client, rn_headers, admin_headers):
        assert client.get("/api/v1/users", headers=rn_headers).status_code == 403
        assert client.get("/api/v1/users", headers=admin_headers).status_code == 200

    def test_admin_creates_user_with_role(self, client, admin_headers):
        resp = client.post("/api/v1/users", headers=admin_headers, json={
            "email": "newrn@agency-example.com", "password": "a-long-password-123",
            "full_name": "New RN", "role": "rn_reviewer", "credentials": "RN",
        })
        assert resp.status_code == 201
        assert resp.json()["role"] == "rn_reviewer"

    def test_unknown_role_rejected(self, client, admin_headers):
        resp = client.post("/api/v1/users", headers=admin_headers, json={
            "email": "x@agency-example.com", "password": "a-long-password-123",
            "full_name": "X", "role": "superuser",
        })
        assert resp.status_code == 422

    def test_deactivated_user_cannot_login(self, client, admin_headers, users):
        target = users[Role.READONLY]
        assert client.post(f"/api/v1/users/{target.id}/deactivate", headers=admin_headers).status_code == 200
        resp = client.post("/api/v1/auth/login", json={"email": target.email, "password": PASSWORD})
        assert resp.status_code == 403

    def test_audit_endpoint_restricted(self, client, clinician_headers, auditor_headers):
        assert client.get("/api/v1/audit", headers=clinician_headers).status_code == 403
        assert client.get("/api/v1/audit", headers=auditor_headers).status_code == 200
