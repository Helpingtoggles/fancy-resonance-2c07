# Security

## Authentication

- JWT bearer tokens (HS256) with distinct `access` (8 h) and `refresh` (7 d)
  types; refresh tokens cannot be replayed as access tokens and vice versa.
- Passwords hashed with PBKDF2-HMAC-SHA256, 600k iterations, per-password
  random salt (stdlib only — no native-dependency footguns).
- Failed logins are audited (`auth.login_failed`) with the source IP.
- Deactivated accounts fail login and token validation immediately.

## Roles

| Role | Intended user | Can |
|---|---|---|
| `admin` | system administrator | manage users, author workflows, everything **except sign** |
| `rn_reviewer` | RN with sign-off authority | everything clinical + finalize OASIS items + sign |
| `clinician` | field RN/therapist | document visits, upload, reconcile meds, review fields |
| `intake_coordinator` | intake staff | patients/episodes/documents/orders tracking |
| `qa_auditor` | compliance | read + audit log access |
| `readonly` | dashboards, integrations | read-only clinical views |

Enforcement is server-side via `require_roles(...)` dependencies; signing has
an additional independent check (`SIGNING_ROLES`) so an authorization-layer
mistake cannot grant signature ability.

## Audit logging

Every state-changing endpoint writes a hash-chained `audit_log` entry (actor,
role, action, resource, JSON detail, IP, timestamp). The chain is verified
via `GET /api/v1/audit/verify`; any UPDATE/DELETE of history breaks it
detectably. Access to the log is restricted to `qa_auditor` / `rn_reviewer` /
`admin`.

## Data protection

- Uploads are stored content-addressed (SHA-256) under `HHRN_STORAGE_DIR`
  with a 50 MB cap; duplicates are detected per patient.
- The API never serves raw storage paths for download without auth.
- PHI note: when running with real patient data you are subject to HIPAA.
  Deploy behind TLS, encrypt the Postgres volume/at-rest storage, set short
  token lifetimes as policy requires, and restrict `HHRN_CORS_ORIGINS`.

## Deployment hardening checklist

- [ ] `HHRN_SECRET_KEY` set to a 32+ byte random value (compose refuses to
      start without it)
- [ ] Strong `POSTGRES_PASSWORD`; database not exposed publicly
- [ ] TLS termination in front of both services
- [ ] `HHRN_CORS_ORIGINS` limited to the real frontend origin
- [ ] Database backups + tested restore
- [ ] Log shipping for `audit_log` (WORM storage recommended)
- [ ] Periodic `GET /audit/verify` and `GET /evidence/ledger/verify` checks
      wired to alerting
