# FieldOps Work Order Bridge

A work order integration API for a mining maintenance contractor. Condition monitoring and vendor systems raise maintenance events across Pilbara sites; the system turns them into work orders idempotently, planners assign them, tradespeople progress them through a fixed state machine, and every change is written to an audit trail in the same transaction.

> Status: work order lifecycle and audit trail complete; see the issue tracker for what is next.

## What this demonstrates

- A fixed work order state machine with explicit command endpoints, and no generic status PATCH
- An audit event for every change, written in the same transaction as the change
- Webhook ingestion with signature verification and idempotency
- Role-based access control (dispatcher / technician / admin)
- Optimistic concurrency
- Real PostgreSQL integration tests, CI, and Azure deployment

## Planned stack

Python 3.14 · FastAPI · Pydantic 2 · SQLAlchemy 2 (async) · PostgreSQL 18 · Alembic · pytest · uv · Ruff · mypy · Docker · GitHub Actions · Azure (App Service, PostgreSQL Flexible Server, Application Insights)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it manages the Python 3.14 toolchain for you).

```bash
uv sync                                  # install exact locked dependencies
docker compose up -d db                  # start PostgreSQL 18
uv run alembic upgrade head              # apply migrations to an empty DB
uv run uvicorn app.main:app --reload     # start the API at http://127.0.0.1:8000
uv run pytest                            # run the test suite (needs the DB up)
```

Interactive API docs: http://127.0.0.1:8000/docs

Integration tests use real PostgreSQL (never SQLite). Start the database and apply
migrations before running them.

## References and attribution

This project is built from scratch; selected patterns are referenced from:

- [rhoboro/async-fastapi-sqlalchemy](https://github.com/rhoboro/async-fastapi-sqlalchemy) — async session / transaction / test fixture patterns
- [rafsaf/minimal-fastapi-postgres-template](https://github.com/rafsaf/minimal-fastapi-postgres-template) — JWT, pytest and CI patterns
- [Azure-Samples/msdocs-fastapi-postgresql-sample-app](https://github.com/Azure-Samples/msdocs-fastapi-postgresql-sample-app) — App Service / OIDC deployment wiring

What was adopted vs. rejected from each is documented as the project evolves.
