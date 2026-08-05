# ADR-001: Explicit command endpoints instead of a generic status PATCH

Status: accepted · 2026-08-04

## Context

A work order moves through a fixed lifecycle: `NEW → ASSIGNED → IN_PROGRESS → COMPLETED`, with cancellation possible from any non-terminal status, and no way back out of a terminal one. Each move has preconditions, required data, and a different person allowed to make it.

The conventional REST shape for this is a single `PATCH /work-orders/{id}` accepting a partial body, including `status`. That is one endpoint instead of four, and it is what most CRUD scaffolding produces.

## Decision

Explicit command endpoints — `POST /work-orders/{id}/assign`, `/reassign`, `/start`, `/complete`, `/cancel` — and no way to write `status` directly. `status` is absent from the create schema and from any update schema; the only thing that can change it is a command.

Reassignment is the case that tested the principle. Handing work to a different technician could have been a second `ASSIGN`, allowed from `ASSIGNED` — one line in the transition table instead of a new endpoint. It is a separate command because the audit trail would otherwise show two identical `ASSIGN` events, and a reader would have to compare payloads to discover that the second one changed hands. The commands are supposed to name what happened; "assigned" and "reassigned" are different things that happened.

The rules themselves live in a domain module as a pure function of `(command, current status)`, so the full transition matrix is unit-tested without a database or an HTTP request.

## Consequences

**What this buys**

- *The required data comes with the command.* Completing requires a resolution; cancelling requires a reason. With a generic PATCH these would be optional fields validated by conditional logic — "resolution is required, but only when status is becoming COMPLETED" — which is a rule about a transition wearing the clothes of a field validator.
- *Illegal moves are a single check.* `PATCH {"status": "COMPLETED"}` on a `NEW` work order is refused by the same code that refuses every other illegal move, and returns `409 INVALID_STATE_TRANSITION` naming both the command and the current status.
- *Authorisation has something to attach to.* Different roles may perform different transitions — a technician starts and completes their own work, a dispatcher assigns and cancels. That is a sentence about commands. Expressed against a generic PATCH it becomes a rule about which values of one field each role may write, which is harder to state and easier to get wrong.
- *The audit trail writes itself.* Every state change corresponds to exactly one command, so the audit event has a name, a payload, and a place to be written — inside the same transaction as the change.
- *The API documents the process.* The endpoint list is the lifecycle. A reader of the OpenAPI schema learns what can happen to a work order without reading the code.

**What it costs**

- Five endpoints instead of one, and a client that wants to change priority and status together needs two calls. Accepted: those are different kinds of change — one is editing a field, the other is an event in the work order's life.
- `start` takes an empty request body it does not read. Without a body FastAPI never inspects the request at all, so it would be the one command that silently ignores an unknown or misspelled field while the others reject it; and a field the commands all eventually need would then have to introduce a body where there was none.
- The transition table is stated twice, in the domain module and in the unit test matrix, deliberately: a change to the rules has to be made in both places, so it cannot be made accidentally.
- It is not what a reviewer expects from "REST CRUD", so the reasoning has to be legible — hence this record.

## Alternatives considered

**Generic `PATCH` with a status field.** Rejected: it makes an illegal transition indistinguishable from a typo at the schema level, pushes conditional-required rules into field validation, and leaves authorisation and auditing without a natural unit to attach to.

**A `POST /work-orders/{id}/transitions` endpoint taking a target status.** Closer, but it still names the destination rather than the intent, and each transition's required payload would again be conditional on the target. "Complete this work order, here is what was done" is the thing that actually happened; "set status to COMPLETED" is a description of the row afterwards.

## Related

- The value domain of `status` is also enforced by a database CHECK constraint, so a seed script or a manual UPDATE cannot introduce an unknown value. Which transitions are legal cannot be expressed there, because it depends on the current row and the caller — that stays in the application.
- Optimistic concurrency (`expected_version` on each command, `409 VERSION_CONFLICT` on a stale write) is a separate decision, deliberately deferred; the commands are the place it will attach when it lands.
