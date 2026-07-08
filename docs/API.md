# API reference

Base path: `/api/v1`. All endpoints (except login/refresh and `/health`)
require `Authorization: Bearer <access_token>`. Interactive docs with full
schemas: `http://localhost:8000/docs`.

Roles column: **A**dmin, **R**N reviewer, **C**linician, **I**ntake,
**Q**A auditor, r**O** = readonly (read endpoints marked "any" include O).

## Auth
| Method | Path | Roles | Notes |
|---|---|---|---|
| POST | `/auth/login` | — | returns access + refresh tokens; failures audited |
| POST | `/auth/refresh` | — | refresh-token only |
| GET | `/auth/me` | any | current profile |

## Users
| POST | `/users` | A | create user with role |
| GET | `/users` | A | list |
| POST | `/users/{id}/deactivate` | A | cannot deactivate self |

## Patients & episodes
| GET | `/patients?q=` | any | search by name/MRN |
| POST | `/patients` | A R C I | MRN unique |
| GET | `/patients/{id}` · `/patients/{id}/episodes` | any | |
| POST | `/episodes` | A R C I | |
| GET/PATCH | `/episodes/{id}` | any / A R C I | status, cert period, F2F, homebound narrative |

## Documents, OCR & extraction
| POST | `/documents` (multipart) | A R C I | ingest + OCR; 50 MB cap; dedupe by sha256 |
| GET | `/documents?episode_id=` · `/documents/{id}` · `/{id}/pages` | any | pages carry OCR confidence |
| POST | `/documents/{id}/extract` | A R C I | run med + order extraction (suggestions only) |
| GET | `/documents/{id}/fields` | any | extracted fields with evidence + confidence |

## Evidence Ledger
| GET | `/evidence/{id}` | any | one evidence record (snippet, span, method) |
| GET | `/evidence/fields/by-entity/{type}/{id}` | any | fields for an entity |
| POST | `/evidence/fields/{id}/review` | A R C | accept / edit / reject — sole writer of field `final_value` |
| GET | `/evidence/ledger/verify` · `/ledger/stats` | any | hash-chain verification |

## Medications & FDB
| GET | `/medications?episode_id=` | any | |
| PATCH | `/medications/{id}` | A R C | RN reconciliation (extracted → active, corrections) |
| POST | `/medications/{id}/prepare-fdb` | A R C | normalize into `fdb-prep/1` payload |
| POST | `/medications/screen?episode_id=` | A R C | FDB screening (NullFdbClient reports not-configured) |

## Physician orders
| GET | `/orders?episode_id=` | any | |
| PATCH | `/orders/{id}/status` | A R C I | track physician signature; SIGNED requires signed_date |

## Infusion
| POST | `/infusion/orders` | A R C | auto-computes rate; returns safety checks |
| GET | `/infusion/orders` · `/{id}/checks` · `/{id}/line-care-schedule` | any | |
| POST | `/infusion/orders/{id}/administrations` | A R C | records visit administration + deviation checks |

## Wounds
| POST | `/wounds` | A R C | staging validation |
| GET | `/wounds` · `/{id}/assessments` · `/{id}/trajectory` | any | PUSH-score trend |
| POST | `/wounds/{id}/assessments` | A R C | computes PUSH score; photo attachable |
| POST | `/wounds/{id}/restage` | A R C | blocks reverse staging |

## OASIS-E2
| POST | `/oasis` | A R C | create assessment for a time point |
| GET | `/oasis?episode_id=` · `/oasis/{id}` · `/{id}/items` · `/{id}/completeness` | any | |
| POST | `/oasis/{id}/suggest` | A R C | engine suggestions (evidence + confidence; never final) |
| POST | `/oasis/{id}/items/{item}/finalize` | **R only** | sole writer of final OASIS values |
| POST | `/oasis/{id}/validate` | any | CMS validation run (persisted) |
| POST | `/oasis/{id}/export` | **R only** | flat export of a SIGNED assessment; no transmission |

## Voice-to-SOC
| POST | `/voice/sessions` (multipart) | A R C | transcribe + draft SOC fields with transcript evidence |
| GET | `/voice/sessions` · `/{id}` | any | |

## Workflows (DSL)
| POST | `/workflows/definitions` | A R | compile DSL (403 on forbidden actions) |
| GET | `/workflows/definitions` · `/instances` | any | |
| POST | `/workflows/instances` | A R C I | start instance |
| POST | `/workflows/instances/{id}/events` | A R C I | send event; role guards enforced |

## Review
| GET | `/review/tasks?mine=` | any | open queue |
| POST | `/review/tasks/{id}/act` | A R C | claim / request_changes / resume / approve / **sign (R only + attestation)** / cancel |

## Risk
| POST/GET | `/episodes/{id}/denial-risk` | any | run/read denial-risk findings + score |
| GET | `/assessments/{id}/validation-findings` | any | persisted validation history |

## Audit
| GET | `/audit?action=&resource_type=&resource_id=` | A R Q | filterable trail |
| GET | `/audit/verify` | A R Q | hash-chain verification |
