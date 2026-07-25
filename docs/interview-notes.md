# Interview Notes

Running log of decisions I made and must be able to defend out loud. Rule from the plan: **code I cannot explain does not merge to `main`.** Each entry pairs the decision with the "why" and the answer I'd give an interviewer. Appended each working day.

---

## Day 1 — Scaffold & toolchain

### 1. Why does `/health/live` not touch the database?

Liveness and readiness are different questions. `live` proves the process is running; `ready` proves it can serve traffic (DB reachable). An orchestrator restarts a container that fails *liveness* — but restarting won't fix a down database, so a DB check belongs in *readiness*, where the platform instead stops routing traffic until it recovers. Mixing them causes restart storms during a DB blip.

### 2. Why a `create_app()` factory instead of a module-level `app`?

The factory returns a fresh, fully-configured instance on demand. Tests get an isolated app each run, and I can later inject different settings (test DB vs prod DB) without editing application code. A module-level singleton binds configuration at import time, which fights testability.

### 3. Why `mypy --strict` and Ruff from commit one?

Type and lint debt compounds. Turning on strict typing at the start costs almost nothing; retrofitting it onto a mature codebase surfaces hundreds of errors at once and usually gets abandoned. Same logic for lint/format — the CI gate keeps `main` consistently clean instead of relying on discipline.

### 4. Why commit `uv.lock`, and what does `uv sync --locked` buy me?

The lockfile pins exact versions of every transitive dependency, so my machine, a teammate's, and CI all build byte-identical environments — reproducible builds. `--locked` in CI *fails* if the lockfile and `pyproject.toml` have drifted, catching a forgotten `uv lock` before it reaches `main`.

### 5. (Real problem hit) pytest couldn't import `app` — why `pythonpath` instead of packaging?

Tests failed with `ModuleNotFoundError: No module named 'app'` because the project root wasn't on `sys.path`. I set `pythonpath = ["."]` in pytest config rather than turning the app into an installable package, because this app is a **deployment unit** (the uvicorn target `app.main:app`), not a library meant to be `pip install`-ed. Packaging it would add build config that serves no one.

### 6. (Real problem hit) why `httpx2` instead of `httpx` for the test client?

Starlette's `TestClient` emitted a deprecation warning that its httpx-based transport is going away in favour of `httpx2`. I switched the test dependency rather than suppress the warning — silencing deprecation warnings just defers the break to an inconvenient time.

---

## Day 2 — Database, async session & migrations

### 7. Why async SQLAlchemy + asyncpg instead of a sync ORM?

FastAPI runs on an async event loop. Under load, a request that waits on the database should yield the event loop so other requests are served instead of blocking a worker thread. Async SQLAlchemy over asyncpg keeps I/O non-blocking end to end, which is where a web API actually spends its time. The cost is that everything touching the DB is `async`/`await` and I must never call blocking code inside a handler.

### 8. Where do transaction boundaries live, and why in the dependency?

The `get_session` dependency wraps the whole request: it commits if the handler returns normally and rolls back on any exception. So a request is an all-or-nothing unit of work — a business change and its audit event either both commit or both roll back. Putting this in one place (not scattered `commit()` calls in handlers) is what later guarantees the audit invariant.

### 9. Why does Alembic own the schema instead of `Base.metadata.create_all`?

`create_all` only ever builds the *current* model shape — it has no concept of migrating an existing database, so it can't be used in production where data already exists. Alembic gives ordered, reversible migrations with a recorded history, and I run the exact same migrations in tests, CI, and prod. The plan bans `create_all`, including in tests, for this reason.

### 10. Why is the DB URL read from settings in `env.py`, not stored in `alembic.ini`?

`alembic.ini` is committed, so a real connection string there would leak a secret. I set `sqlalchemy.url` in `env.py` from the same `pydantic-settings` object the app uses, so there is one source of truth (an env var) and no credentials in the repo.

### 11. Why is `assets` the baseline table when the plan says "work_orders first"?

`work_orders` has foreign keys to `assets` (and later `users`), so those tables must exist first — I build the schema in dependency order. `assets` has no FK dependencies, and the very next slice (issue #5) builds directly on it, so nothing is wasted. This is a small, deliberate deviation from the plan's wording for a correctness reason.

### 12. Why generate IDs and timestamps with server defaults (`gen_random_uuid()`, `now()`)?

The database is the single writer of record, so defaults belong there: every row gets a UUID and UTC timestamps regardless of which code path (API, seed script, a manual `INSERT`) created it. `updated_at` uses `onupdate=now()` so it can't be forgotten. Generating these in Python would let a buggy or alternative caller skip them.

### 13. (Real problem hit) Postgres 18 container exited on first boot

The compose volume mounted `/var/lib/postgresql/data`, but Postgres 18 changed its recommended layout: mount the parent `/var/lib/postgresql` and data lives in a version subdirectory, so `pg_upgrade --link` works without crossing a mount boundary. The old mount made the container `exit(1)` immediately. Fixed the mount point and documented why in `docker-compose.yml`.

---

<!-- Day 3 entries go below this line -->
