# Project Contract

One page. If a proposed change conflicts with this page, the change waits.

## Business problem

A field service company maintains equipment for multiple client sites. External contractor/vendor systems send maintenance events. Today those events would be handled by email and spreadsheets: duplicates create duplicate jobs, nobody knows who is working on what, and there is no reliable history of what happened. This system turns vendor events into work orders with a controlled lifecycle.

## Users

| Role | What they do |
|---|---|
| Vendor system | Sends signed maintenance events (machine-to-machine) |
| Dispatcher | Reviews new work orders, assigns technicians, cancels invalid ones |
| Technician | Starts and completes work orders assigned to them |
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
