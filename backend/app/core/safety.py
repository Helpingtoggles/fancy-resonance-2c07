"""Platform-wide clinical safety invariants.

These invariants are non-negotiable product requirements:

1. **Never auto-submit documentation.** Submission to a payer/CMS is out of
   scope for automation; only export of RN-approved documents is supported,
   and export requires a signed document plus an explicit human request.
2. **Never auto-sign documentation.** Signing requires an authenticated human
   RN (or physician) actor performing an explicit attestation. There is no
   service-account or system code path that can sign.
3. **Never generate final OASIS codes.** AI/extraction output is only ever a
   *suggestion* with evidence and confidence. Final values are written
   exclusively through the RN review workflow by a human reviewer.
4. **Every extracted field carries source evidence and confidence.** The
   Evidence Ledger is append-only and every ``ExtractedField`` must reference
   an ``EvidenceRecord``.

This module centralizes enforcement so the rules cannot be silently disabled
by configuration drift, and gives tests a single surface to assert against.
"""

from app.core.config import get_settings


class SafetyViolation(RuntimeError):
    """Raised when code attempts to violate a clinical safety invariant."""


#: Workflow-DSL action names that are forbidden for automated execution.
FORBIDDEN_AUTOMATED_ACTIONS = frozenset(
    {"sign", "auto_sign", "submit", "auto_submit", "transmit", "finalize_oasis"}
)

#: Actor kinds considered non-human. These may never sign, submit, or
#: finalize documentation.
NON_HUMAN_ACTORS = frozenset({"system", "service", "ai", "extractor", "workflow", "scheduler"})


def enforce_safety_invariants() -> None:
    """Refuse to start the application if any invariant is disabled."""
    settings = get_settings()
    if settings.allow_auto_submit:
        raise SafetyViolation("HHRN_ALLOW_AUTO_SUBMIT=true is not permitted: documentation may never be auto-submitted.")
    if settings.allow_auto_sign:
        raise SafetyViolation("HHRN_ALLOW_AUTO_SIGN=true is not permitted: documentation may never be auto-signed.")
    if settings.allow_ai_final_codes:
        raise SafetyViolation("HHRN_ALLOW_AI_FINAL_CODES=true is not permitted: AI may never produce final OASIS codes.")


def assert_human_actor(actor_kind: str, operation: str) -> None:
    """Guard for sign/submit/finalize operations.

    ``actor_kind`` is derived from the authenticated principal; API users are
    always ``"human"``. Internal services must pass their own kind and will
    be rejected here.
    """
    if actor_kind != "human" or actor_kind in NON_HUMAN_ACTORS:
        raise SafetyViolation(
            f"Operation '{operation}' requires an authenticated human actor; got '{actor_kind}'."
        )


def assert_action_allowed_for_automation(action: str) -> None:
    """Guard used by the workflow DSL engine before executing an action."""
    if action.lower() in FORBIDDEN_AUTOMATED_ACTIONS:
        raise SafetyViolation(
            f"Workflow action '{action}' may not be executed by automation. "
            "Signing, submitting, and OASIS finalization require the RN review workflow."
        )
