# Project Contract

One page. If a proposed change conflicts with this page, the change waits.

## Business problem

A maintenance contractor services fixed and mobile plant — haul trucks, conveyors, crushers, pumps — across several Pilbara mine sites in Western Australia. Condition monitoring and vendor systems raise maintenance events around the clock. Handled by email and spreadsheets, the same alarm becomes three jobs, nobody on site knows who is attending what, and when a regulator or a client asks what happened to a piece of plant there is no reliable answer. This system turns vendor events into work orders with a controlled lifecycle and a history that can be produced on request.

## Users

| Role | What they do |
|---|---|
| Vendor system | Condition monitoring or an OEM platform sending signed maintenance events (machine-to-machine) |
| Dispatcher | Maintenance planner or supervisor: reviews new work orders, assigns tradespeople, cancels invalid ones |
| Technician | Fitter, electrician or boilermaker on site: starts and completes work orders assigned to them |
| Admin | Everything a dispatcher can do, plus user/asset management |
| Developer/operator | Traces a failed request end-to-end from logs |

## Scope (v1)

```text
Vendor event
    -> validate signature and idempotency
    -> create WorkOrder
    -> dispatcher assigns technician
    -> technician starts work
    -> technician completes work
    -> every change creates an audit event
```

State machine (fixed):

```text
NEW -> ASSIGNED -> IN_PROGRESS -> COMPLETED
  \                    \
   ---------------------> CANCELLED
```

- `NEW -> ASSIGNED`: dispatcher/admin
- `ASSIGNED -> IN_PROGRESS`: the assigned technician
- `IN_PROGRESS -> COMPLETED`: the assigned technician, resolution required
- `NEW/ASSIGNED/IN_PROGRESS -> CANCELLED`: dispatcher/admin, reason required
- `COMPLETED` and `CANCELLED` are terminal; no reopen — create a new work order

Priority is a statement about risk to people first and production second, in the
language a WA maintenance planner works in:

| Priority | What it means on site |
|---|---|
| `CRITICAL` | An uncontrolled hazard or immediate risk to a person. Plant is isolated and stays down until the risk is eliminated or minimised so far as is reasonably practicable (SFAIRP). |
| `HIGH` | A control is degraded but the hazard is still controlled — a guard, brake or interlock needing attention before the next shift. |
| `MEDIUM` | Condition-based work with a real deadline: wear trending toward a limit, a leak that is contained. |
| `LOW` | No safety consequence; scheduled at the next convenient shutdown. |

Priority never changes what the state machine allows. It orders the queue, and it
is recorded so that a decision to defer work can be explained afterwards.

Core guarantees:

- **Idempotency** — the same vendor event delivered 10 times creates exactly one work order
- **RBAC** — technicians can only progress their own work orders
- **Optimistic concurrency** — stale writes are rejected with `409`
- **Audit** — every state change writes an event in the same DB transaction
- **Traceability** — one correlation ID links a request across logs

## Non-goals (v1)

Inventory, parts, purchasing, billing, scheduling, maps/GPS; multi-tenancy and enterprise SSO; real-time telemetry/IoT; message queues (RabbitMQ/Service Bus/Kafka), Redis, Celery; microservices, DDD, CQRS, Kubernetes; React admin UI; Fabric/Power BI/PySpark; LLM/RAG/agents; C#/.NET rewrite.

Rule: a feature that requires a new infrastructure service and is not needed for this week's acceptance goes to the backlog.

## Delivery constraints

- Phase 1 budget: 150–170 hours over at most 8 weeks; 180 hours is a hard cap
- At 180 hours without a deployment, cut features — do not extend the timeline
- Code that cannot be explained in an interview does not merge to `main`
