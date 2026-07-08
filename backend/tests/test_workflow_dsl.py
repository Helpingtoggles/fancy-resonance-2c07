"""Workflow DSL: compilation, expressions, execution, guards."""

import pytest

from app.services import workflow_dsl
from app.services.workflow_dsl import DslError, compile_dsl, evaluate_expression

VALID_SOURCE = """workflow soc_intake v2
# Intake flow
state referral_received initial
  on documents_uploaded -> awaiting_extraction

state awaiting_extraction
  on extraction_complete when ctx.meds_extracted >= 1 -> pending_rn_review
  on extraction_complete -> pending_manual_entry

state pending_rn_review
  require role rn_reviewer
  do create_review_task "Reconcile extracted medications"
  on review_approved -> ready_for_soc_visit

state pending_manual_entry
  on manual_entry_complete -> pending_rn_review

state ready_for_soc_visit terminal
"""


class TestCompile:
    def test_valid_source_compiles(self):
        compiled = compile_dsl(VALID_SOURCE)
        assert compiled["name"] == "soc_intake"
        assert compiled["version"] == 2
        assert compiled["initial"] == "referral_received"
        assert compiled["states"]["ready_for_soc_visit"]["terminal"] is True
        assert compiled["states"]["pending_rn_review"]["require_roles"] == ["rn_reviewer"]

    def test_missing_header(self):
        with pytest.raises(DslError, match="header"):
            compile_dsl("state a initial\nstate b terminal")

    def test_undefined_target(self):
        with pytest.raises(DslError, match="not a defined state"):
            compile_dsl("workflow w v1\nstate a initial\n  on go -> nowhere\nstate b terminal")

    def test_two_initials_rejected(self):
        with pytest.raises(DslError, match="initial"):
            compile_dsl("workflow w v1\nstate a initial terminal\nstate b initial terminal")

    def test_terminal_with_transitions_rejected(self):
        with pytest.raises(DslError, match="terminal"):
            compile_dsl("workflow w v1\nstate a initial\n  on go -> b\nstate b terminal\n  on go -> a")

    def test_unparseable_line(self):
        with pytest.raises(DslError, match="cannot parse"):
            compile_dsl("workflow w v1\nstate a initial\n  banana\nstate b terminal")


class TestExpressions:
    @pytest.mark.parametrize("expr,ctx,expected", [
        ("ctx.n >= 1", {"n": 2}, True),
        ("ctx.n >= 1", {"n": 0}, False),
        ("ctx.n >= 1", {}, False),  # missing key → None comparison → False
        ('ctx.status == "ready"', {"status": "ready"}, True),
        ("ctx.a > 1 and ctx.b < 5", {"a": 2, "b": 3}, True),
        ("not ctx.flag", {"flag": False}, True),
        ("(ctx.a == 1 or ctx.b == 1) and true", {"a": 0, "b": 1}, True),
        ("false or false", {}, False),
    ])
    def test_evaluation(self, expr, ctx, expected):
        assert evaluate_expression(expr, ctx) is expected

    def test_injection_is_a_syntax_error(self):
        with pytest.raises(DslError):
            evaluate_expression("__import__('os').system('rm -rf /')", {})

    def test_trailing_garbage_rejected(self):
        with pytest.raises(DslError):
            evaluate_expression("ctx.a == 1 ctx.b", {"a": 1})


class TestExecution:
    def _setup(self, db):
        definition = workflow_dsl.create_definition(db, source=VALID_SOURCE, created_by=None)
        instance = workflow_dsl.start_instance(
            db, definition=definition, subject_type="episode", subject_id="ep-1"
        )
        return definition, instance

    def test_conditional_routing(self, db):
        definition, instance = self._setup(db)
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="documents_uploaded", actor_id=None, actor_role="intake_coordinator")
        # meds_extracted = 0 → falls through to manual entry
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="extraction_complete", actor_id=None,
                                actor_role="intake_coordinator", context_updates={"meds_extracted": 0})
        assert instance.current_state == "pending_manual_entry"

    def test_conditional_routing_positive(self, db):
        definition, instance = self._setup(db)
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="documents_uploaded", actor_id=None, actor_role="intake_coordinator")
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="extraction_complete", actor_id=None,
                                actor_role="intake_coordinator", context_updates={"meds_extracted": 4})
        assert instance.current_state == "pending_rn_review"

    def test_entry_action_creates_review_task(self, db):
        from sqlalchemy import select

        from app.models.review import ReviewTask

        definition, instance = self._setup(db)
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="documents_uploaded", actor_id=None, actor_role="intake_coordinator")
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="extraction_complete", actor_id=None,
                                actor_role="intake_coordinator", context_updates={"meds_extracted": 4})
        tasks = db.execute(select(ReviewTask)).scalars().all()
        assert any(t.title == "Reconcile extracted medications" for t in tasks)

    def test_role_guard_enforced(self, db):
        definition, instance = self._setup(db)
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="documents_uploaded", actor_id=None, actor_role="intake_coordinator")
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="extraction_complete", actor_id=None,
                                actor_role="intake_coordinator", context_updates={"meds_extracted": 4})
        with pytest.raises(PermissionError, match="requires role"):
            workflow_dsl.send_event(db, instance=instance, definition=definition,
                                    event="review_approved", actor_id=None, actor_role="intake_coordinator")

    def test_terminal_state_completes_instance(self, db):
        definition, instance = self._setup(db)
        for event, role, ctx in [
            ("documents_uploaded", "intake_coordinator", None),
            ("extraction_complete", "intake_coordinator", {"meds_extracted": 2}),
            ("review_approved", "rn_reviewer", None),
        ]:
            workflow_dsl.send_event(db, instance=instance, definition=definition, event=event,
                                    actor_id=None, actor_role=role, context_updates=ctx)
        assert instance.current_state == "ready_for_soc_visit"
        assert instance.is_complete is True
        with pytest.raises(DslError, match="complete"):
            workflow_dsl.send_event(db, instance=instance, definition=definition,
                                    event="anything", actor_id=None, actor_role="rn_reviewer")

    def test_unknown_event_rejected(self, db):
        definition, instance = self._setup(db)
        with pytest.raises(DslError, match="no transition"):
            workflow_dsl.send_event(db, instance=instance, definition=definition,
                                    event="bogus", actor_id=None, actor_role="rn_reviewer")

    def test_transition_log_records_history(self, db):
        definition, instance = self._setup(db)
        workflow_dsl.send_event(db, instance=instance, definition=definition,
                                event="documents_uploaded", actor_id=None, actor_role="intake_coordinator")
        assert len(instance.transitions) >= 1
        t = instance.transitions[0]
        assert (t.from_state, t.to_state) == ("referral_received", "awaiting_extraction")


class TestWorkflowApi:
    def test_definition_create_and_run(self, client, rn_headers, intake_headers):
        definition = client.post("/api/v1/workflows/definitions", headers=rn_headers,
                                 json={"dsl_source": VALID_SOURCE}).json()
        assert definition["name"] == "soc_intake"

        instance = client.post("/api/v1/workflows/instances", headers=intake_headers, json={
            "definition_id": definition["id"], "subject_type": "episode", "subject_id": "ep-9",
        }).json()
        assert instance["current_state"] == "referral_received"

        resp = client.post(f"/api/v1/workflows/instances/{instance['id']}/events",
                           headers=intake_headers, json={"event": "documents_uploaded"})
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "awaiting_extraction"

    def test_forbidden_dsl_rejected_via_api(self, client, rn_headers):
        bad = 'workflow bad v1\nstate a initial\n  do sign "x"\n  on go -> b\nstate b terminal'
        resp = client.post("/api/v1/workflows/definitions", headers=rn_headers,
                           json={"dsl_source": bad})
        assert resp.status_code == 403
        assert "forbidden" in resp.json()["detail"]

    def test_only_rn_or_admin_author_workflows(self, client, intake_headers):
        resp = client.post("/api/v1/workflows/definitions", headers=intake_headers,
                           json={"dsl_source": VALID_SOURCE})
        assert resp.status_code == 403
