# FieldOps Work Order Bridge

A Field Service Work Order Integration API. External vendor systems send maintenance events; the system creates work orders idempotently, dispatchers assign them, technicians progress them through a fixed state machine, and every change is audited.

> Status: Day 1 — project scaffold in progress.

## What this demonstrates

- Webhook ingestion with signature verification and idempotency
- A fixed work order state machine with explicit command endpoints
- Role-based access control (dispatcher / technician / admin)
- Optimistic concurrency and transactional audit history
- Real PostgreSQL integration tests, CI, and Azure deployment

## Planned stack

Python 3.14 · FastAPI · Pydantic 2 · SQLAlchemy 2 (async) · PostgreSQL 18 · Alembic · pytest · uv · Ruff · mypy · Docker · GitHub Actions · Azure (App Service, PostgreSQL Flexible Server, Key Vault, Application Insights)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it manages the Python 3.14 toolchain for you).

```bash
uv sync                                  # install exact locked dependencies
uv run uvicorn app.main:app --reload     # start the API at http://127.0.0.1:8000
uv run pytest                            # run the test suite
```

Interactive API docs: http://127.0.0.1:8000/docs

## References and attribution

This project is built from scratch; selected patterns are referenced from:

- [rhoboro/async-fastapi-sqlalchemy](https://github.com/rhoboro/async-fastapi-sqlalchemy) — async session / transaction / test fixture patterns
- [rafsaf/minimal-fastapi-postgres-template](https://github.com/rafsaf/minimal-fastapi-postgres-template) — JWT, pytest and CI patterns
- [Azure-Samples/msdocs-fastapi-postgresql-sample-app](https://github.com/Azure-Samples/msdocs-fastapi-postgresql-sample-app) — Bicep / azd / OIDC wiring

What was adopted vs. rejected from each is documented as the project evolves.
