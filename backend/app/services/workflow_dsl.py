"""Workflow DSL: a small, safe, auditable state-machine language.

Agencies encode operational flows (intake, SOC, recert, wound follow-up) as
text workflows. Example::

    workflow soc_intake v2

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

Grammar (line-oriented):
    workflow <name> v<version>
    state <name> [initial] [terminal]
      require role <role>[,<role>...]        # guard for ALL events in state
      do <action> ["arg"]                    # entry actions (side effects)
      on <event> [when <expr>] -> <target>   # transitions, first match wins

Expressions support: ctx.<key>, numbers, quoted strings, true/false,
comparison (== != < <= > >=), and/or/not, parentheses. Evaluated by a tiny
recursive-descent evaluator — no ``eval``.

SAFETY: the compiler rejects any ``do`` action in
``core.safety.FORBIDDEN_AUTOMATED_ACTIONS`` (sign/submit/finalize...), so a
workflow author cannot create automation that signs or submits
documentation. Allowed actions are an explicit allowlist.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.safety import FORBIDDEN_AUTOMATED_ACTIONS, SafetyViolation
from app.models.review import ReviewTask
from app.models.workflow import WorkflowDefinition, WorkflowInstance, WorkflowTransitionLog
from app.services import audit

ALLOWED_ACTIONS = {
    "create_review_task",  # arg: title
    "set_priority",        # arg: low|normal|high|urgent (stored in context)
    "flag",                # arg: free-text flag added to context.flags
    "notify",              # arg: message recorded in transition log (no external send here)
}


class DslError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Parsing / compilation
# ---------------------------------------------------------------------------

@dataclass
class Transition:
    event: str
    target: str
    condition: str | None = None


@dataclass
class StateDef:
    name: str
    initial: bool = False
    terminal: bool = False
    require_roles: list[str] = field(default_factory=list)
    actions: list[tuple[str, str | None]] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)


_WORKFLOW_RE = re.compile(r"^workflow\s+(?P<name>[a-z][a-z0-9_]*)\s+v(?P<version>\d+)$")
_STATE_RE = re.compile(r"^state\s+(?P<name>[a-z][a-z0-9_]*)(?P<flags>(?:\s+(?:initial|terminal))*)$")
_ON_RE = re.compile(r"^on\s+(?P<event>[a-z][a-z0-9_]*)(?:\s+when\s+(?P<cond>.+?))?\s*->\s*(?P<target>[a-z][a-z0-9_]*)$")
_REQUIRE_RE = re.compile(r"^require\s+role\s+(?P<roles>[a-z_,\s]+)$")
_DO_RE = re.compile(r'^do\s+(?P<action>[a-z_]+)(?:\s+"(?P<arg>[^"]*)")?$')


def compile_dsl(source: str) -> dict:
    """Compile DSL source → JSON-serializable definition. Raises DslError."""
    name: str | None = None
    version: int | None = None
    states: dict[str, StateDef] = {}
    current: StateDef | None = None

    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        if m := _WORKFLOW_RE.match(line):
            if name is not None:
                raise DslError(f"line {lineno}: duplicate 'workflow' header")
            name, version = m.group("name"), int(m.group("version"))
        elif m := _STATE_RE.match(line):
            state_name = m.group("name")
            if state_name in states:
                raise DslError(f"line {lineno}: duplicate state '{state_name}'")
            flags = m.group("flags") or ""
            current = StateDef(state_name, initial="initial" in flags, terminal="terminal" in flags)
            states[state_name] = current
        elif m := _ON_RE.match(line):
            if current is None:
                raise DslError(f"line {lineno}: 'on' outside a state")
            cond = m.group("cond")
            if cond:
                _validate_expression(cond, lineno)
            current.transitions.append(Transition(m.group("event"), m.group("target"), cond))
        elif m := _REQUIRE_RE.match(line):
            if current is None:
                raise DslError(f"line {lineno}: 'require' outside a state")
            current.require_roles = [r.strip() for r in m.group("roles").split(",") if r.strip()]
        elif m := _DO_RE.match(line):
            if current is None:
                raise DslError(f"line {lineno}: 'do' outside a state")
            action = m.group("action")
            if action in FORBIDDEN_AUTOMATED_ACTIONS:
                raise SafetyViolation(
                    f"line {lineno}: action '{action}' is forbidden — workflows may never "
                    "sign, submit, or finalize documentation automatically."
                )
            if action not in ALLOWED_ACTIONS:
                raise DslError(f"line {lineno}: unknown action '{action}'. Allowed: {sorted(ALLOWED_ACTIONS)}")
            current.actions.append((action, m.group("arg")))
        else:
            raise DslError(f"line {lineno}: cannot parse: {line!r}")

    if name is None or version is None:
        raise DslError("missing 'workflow <name> v<version>' header")
    initials = [s for s in states.values() if s.initial]
    if len(initials) != 1:
        raise DslError(f"exactly one 'initial' state required, found {len(initials)}")
    for s in states.values():
        for t in s.transitions:
            if t.target not in states:
                raise DslError(f"state '{s.name}': transition target '{t.target}' is not a defined state")
        if s.terminal and s.transitions:
            raise DslError(f"terminal state '{s.name}' must not define transitions")

    return {
        "name": name,
        "version": version,
        "initial": initials[0].name,
        "states": {
            s.name: {
                "terminal": s.terminal,
                "require_roles": s.require_roles,
                "actions": [{"action": a, "arg": arg} for a, arg in s.actions],
                "transitions": [
                    {"event": t.event, "target": t.target, "condition": t.condition}
                    for t in s.transitions
                ],
            }
            for s in states.values()
        },
    }


# ---------------------------------------------------------------------------
# Expression evaluator (no eval())
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>\"[^\"]*\")|(?P<ctx>ctx\.[a-zA-Z_][a-zA-Z0-9_]*)"
    r"|(?P<op><=|>=|==|!=|<|>)|(?P<kw>and|or|not|true|false)\b|(?P<paren>[()]))"
)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            if expr[pos:].strip():
                raise DslError(f"bad expression near: {expr[pos:pos + 20]!r}")
            break
        pos = m.end()
        for kind in ("num", "str", "ctx", "op", "kw", "paren"):
            if m.group(kind) is not None:
                tokens.append((kind, m.group(kind)))
                break
    return tokens


def _validate_expression(expr: str, lineno: int) -> None:
    try:
        evaluate_expression(expr, {})
    except DslError as e:
        raise DslError(f"line {lineno}: {e}")
    except Exception:
        pass  # runtime type errors with empty ctx are fine at compile time


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], ctx: dict):
        self.tokens = tokens
        self.pos = 0
        self.ctx = ctx

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def next(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == ("kw", "or"):
            self.next()
            right = self.parse_and()
            left = bool(left) or bool(right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek() == ("kw", "and"):
            self.next()
            right = self.parse_not()
            left = bool(left) and bool(right)
        return left

    def parse_not(self):
        if self.peek() == ("kw", "not"):
            self.next()
            return not bool(self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_atom()
        kind, value = self.peek()
        if kind == "op":
            self.next()
            right = self.parse_atom()
            try:
                match value:
                    case "==": return left == right
                    case "!=": return left != right
                    case "<": return left < right
                    case "<=": return left <= right
                    case ">": return left > right
                    case ">=": return left >= right
            except TypeError:
                return False
        return left

    def parse_atom(self):
        kind, value = self.next()
        if kind == "num":
            return float(value) if "." in value else int(value)
        if kind == "str":
            return value[1:-1]
        if kind == "kw" and value in ("true", "false"):
            return value == "true"
        if kind == "ctx":
            return self.ctx.get(value[4:])
        if kind == "paren" and value == "(":
            result = self.parse_or()
            if self.next() != ("paren", ")"):
                raise DslError("missing closing parenthesis")
            return result
        raise DslError(f"unexpected token {value!r}")


def evaluate_expression(expr: str, ctx: dict) -> bool:
    tokens = _tokenize(expr)
    if not tokens:
        raise DslError("empty expression")
    parser = _Parser(tokens, ctx)
    result = parser.parse_or()
    if parser.pos != len(tokens):
        raise DslError(f"trailing tokens in expression: {expr!r}")
    return bool(result)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def create_definition(db: Session, *, source: str, created_by: str | None) -> WorkflowDefinition:
    compiled = compile_dsl(source)
    definition = WorkflowDefinition(
        name=compiled["name"],
        version=compiled["version"],
        dsl_source=source,
        compiled=compiled,
        created_by=created_by,
    )
    db.add(definition)
    db.flush()
    return definition


def start_instance(
    db: Session, *, definition: WorkflowDefinition, subject_type: str, subject_id: str,
    context: dict | None = None,
) -> WorkflowInstance:
    instance = WorkflowInstance(
        definition_id=definition.id,
        subject_type=subject_type,
        subject_id=subject_id,
        current_state=definition.compiled["initial"],
        context=context or {},
    )
    db.add(instance)
    db.flush()
    _run_entry_actions(db, definition, instance, actor_id=None)
    return instance


def send_event(
    db: Session,
    *,
    instance: WorkflowInstance,
    definition: WorkflowDefinition,
    event: str,
    actor_id: str | None,
    actor_role: str | None,
    actor_kind: str = "human",
    context_updates: dict | None = None,
) -> WorkflowInstance:
    if instance.is_complete:
        raise DslError(f"workflow instance is complete (state '{instance.current_state}')")

    compiled = definition.compiled
    state = compiled["states"][instance.current_state]

    if state["require_roles"] and actor_role not in state["require_roles"] and actor_role != "admin":
        raise PermissionError(
            f"state '{instance.current_state}' requires role in {state['require_roles']}; actor has '{actor_role}'"
        )

    ctx = dict(instance.context or {})
    if context_updates:
        ctx.update(context_updates)

    target = None
    for t in state["transitions"]:
        if t["event"] != event:
            continue
        if t["condition"] and not evaluate_expression(t["condition"], ctx):
            continue
        target = t["target"]
        break
    if target is None:
        raise DslError(f"no transition for event '{event}' from state '{instance.current_state}'")

    from_state = instance.current_state
    instance.current_state = target
    instance.context = ctx
    db.add(
        WorkflowTransitionLog(
            instance_id=instance.id, event=event, from_state=from_state, to_state=target,
            actor_id=actor_id, actor_kind=actor_kind, detail={"context_updates": context_updates},
        )
    )
    audit.record(
        db, action="workflow.transition", actor_id=actor_id, actor_role=actor_role,
        resource_type="workflow_instance", resource_id=instance.id,
        detail={"event": event, "from": from_state, "to": target},
    )

    target_def = compiled["states"][target]
    _run_entry_actions(db, definition, instance, actor_id=actor_id)
    if target_def["terminal"]:
        instance.is_complete = True
    db.flush()
    return instance


def _run_entry_actions(
    db: Session, definition: WorkflowDefinition, instance: WorkflowInstance, actor_id: str | None
) -> None:
    state = definition.compiled["states"][instance.current_state]
    ctx = dict(instance.context or {})
    for entry in state["actions"]:
        action, arg = entry["action"], entry["arg"]
        # Defense in depth: the compiler already rejects these, but never trust
        # stored definitions that might predate the check.
        if action in FORBIDDEN_AUTOMATED_ACTIONS:
            raise SafetyViolation(f"stored workflow contains forbidden action '{action}'")
        if action == "create_review_task":
            db.add(
                ReviewTask(
                    subject_type=instance.subject_type,
                    subject_id=instance.subject_id,
                    title=arg or f"Review required: {definition.name}/{instance.current_state}",
                    priority=ctx.get("priority", "normal"),
                )
            )
        elif action == "set_priority":
            ctx["priority"] = arg or "normal"
        elif action == "flag":
            ctx.setdefault("flags", []).append(arg or "flag")
        elif action == "notify":
            db.add(
                WorkflowTransitionLog(
                    instance_id=instance.id, event="__notify__",
                    from_state=instance.current_state, to_state=instance.current_state,
                    actor_id=actor_id, actor_kind="workflow", detail={"message": arg},
                )
            )
    instance.context = ctx
    db.flush()
