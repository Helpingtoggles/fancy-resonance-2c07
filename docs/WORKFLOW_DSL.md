# Workflow DSL reference

A small, line-oriented language for encoding agency operational flows
(intake, SOC, recert, wound follow-up) as auditable state machines.
Definitions are compiled and stored (`workflow_definitions`); instances track
a subject (episode, document, assessment) through the states, logging every
transition and audit event.

## Example

```
workflow soc_intake v2
# comments start with '#'

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
```

## Grammar

```
workflow <name> v<version>            # required header, once
state <name> [initial] [terminal]     # exactly one initial; terminals have no transitions
  require role <role>[, <role>...]    # guard: all events in this state need one of these roles
  do <action> ["arg"]                 # entry actions, run when the state is entered
  on <event> [when <expr>] -> <target>  # transitions; first matching wins
```

- Names: lowercase `[a-z][a-z0-9_]*`.
- `admin` passes any `require role` guard.
- Compile errors carry line numbers.

## Expressions (`when …`)

Operands: `ctx.<key>` (instance context), numbers, `"strings"`,
`true`/`false`. Operators: `== != < <= > >=`, `and`, `or`, `not`,
parentheses. Evaluated by a purpose-built recursive-descent parser —
**no `eval`**, so context values can never execute code. A missing context
key evaluates as `null` (comparisons with it are false).

## Actions (allowlist)

| Action | Effect |
|---|---|
| `create_review_task "title"` | opens an RN review task for the instance's subject |
| `set_priority "high"` | sets `ctx.priority` (used by created tasks) |
| `flag "note"` | appends to `ctx.flags` |
| `notify "message"` | records a notify entry in the transition log |

**Forbidden by the compiler and again at execution time:** `sign`,
`auto_sign`, `submit`, `auto_submit`, `transmit`, `finalize_oasis` — a
workflow can *route work to humans*, it can never perform the human act
itself. Unknown actions are compile errors.

## API

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /api/v1/workflows/definitions` | rn_reviewer, admin | compile + store DSL |
| `GET /api/v1/workflows/definitions` | any authed | list active definitions |
| `POST /api/v1/workflows/instances` | clinical roles | start an instance for a subject |
| `POST /api/v1/workflows/instances/{id}/events` | clinical roles | send an event (with optional `context_updates`) |

Every transition is written to `workflow_transition_log` (event, from/to,
actor, actor kind) and to the audit log.
