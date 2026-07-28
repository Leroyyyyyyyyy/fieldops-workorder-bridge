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

## Day 3 — Reviewing the schema slice before building on it

### 14. When is a server-generated UUID actually available on the object?

Only after `flush()`. `session.add()` just registers the object in the unit of work and emits no SQL, so `id`, `created_at` and `updated_at` are all `None` until the INSERT runs. Because the columns use `server_default`, SQLAlchemy doesn't know the values until PostgreSQL returns them:

```sql
INSERT INTO assets (external_id, site, name, asset_type, status)
VALUES ($1, $2, $3, $4, $5)
RETURNING assets.id, assets.created_at, assets.updated_at
```

Two consequences for the `POST /assets` handler. First, it must `await session.flush()` before building the response — the transaction is committed by the `get_session` dependency *after* the handler returns, so without an explicit flush the response would serialise `"id": null`. Second, `RETURNING` already fetches the timestamps in the same round trip, so calling `session.refresh()` afterwards would be a wasted SELECT.

A related surprise: a Python-side `default=` (like `status="ACTIVE"`) is *also* unset until flush. It is a Core column default evaluated when the INSERT is compiled, not an attribute assigned in `__init__`.

### 15. Correction to entry 12: `server_default` and `onupdate` are not equally strong

Entry 12 claimed `updated_at` "can't be forgotten" because of `onupdate=now()`. Testing that assumption showed it is only true for writers that go through SQLAlchemy. Updating the same row three ways:

| How the UPDATE was issued | `updated_at` refreshed? |
|---|---|
| ORM attribute change + `flush()` | yes |
| Core `update(Asset).values(...)` | yes |
| `text("UPDATE assets SET ...")` | **no** |

`onupdate` is not a database feature — SQLAlchemy injects the value while *compiling* the UPDATE statement, so any SQL it did not compile skips it. The dividing line is not "ORM vs Core" but "was this statement generated from the Column definition".

So the two timestamps in the same mixin carry different guarantees: `created_at` uses `server_default`, which holds even for a manual `INSERT`, while `updated_at` is an application-layer convenience. That is acceptable while the API is the only writer, but a `psql` hotfix or a second service writing the table would silently leave it stale. Making it writer-independent needs a `BEFORE UPDATE` trigger.

### 16. Does a passing `alembic check` prove the migration matches the models?

No — it rules out one common class of error, not all of them. `alembic check` compares `Base.metadata` against the live database and does catch structural drift; changing `external_id` to `Mapped[str | None]` fails it immediately with `modify_nullable`.

But it reported "No new upgrade operations detected" after I moved the primary key from `server_default=gen_random_uuid()` (database-generated) to `default=uuid.uuid4` (Python-generated) — a change that visibly alters the emitted SQL, moving `id` out of `RETURNING` and into the INSERT column list. Alembic's `compare_server_default` defaults to `False`, and `env.py` used the template call unchanged. In other words, the guarantee this schema is built on — that the database is the single writer of record — is exactly the guarantee CI cannot currently enforce. The fix is one argument, `compare_server_default=True` in `context.configure()`, and it is cheap now: once several tables exist, turning the comparison on means reconciling whatever drift has already accumulated.

Autogenerate is structurally blind to more than that: renames appear as drop-plus-add (which silently discards data), CHECK constraints are not compared by default, and triggers, views and data migrations are outside its model entirely. A green `alembic check` means "no detected drift", not "correct migration".

### 17. How does SQLAlchemy 2.0 decide whether a column is nullable?

From the type annotation. `Mapped[str]` produces `NOT NULL`; `Mapped[str | None]` produces a nullable column; an explicit `mapped_column(nullable=...)` overrides both. This is why the baseline migration has `nullable=False` on columns where the model never mentions nullability. The annotation is not merely documentation for mypy — it is part of the schema definition, and changing it changes DDL.

### 18. Where should the valid set of statuses be enforced?

Splitting the question in two makes the answer clear. The *value domain* (a status is one of a known set) is a constraint the database can enforce. The *legal transitions* (`COMPLETED` cannot return to `IN_PROGRESS`) depend on the current row, the caller's role and the request, so they can only live in the application.

For the value domain I'd use a `CHECK` constraint rather than a PostgreSQL `ENUM` type: adding a value to an enum requires `ALTER TYPE` and removing one is effectively impossible, which makes migrations painful, whereas a CHECK is an ordinary migration. `Asset.status` is currently an unconstrained string; that is low-stakes for now, and the constraint is worth adding with the work order state machine, when there is an invariant genuinely worth protecting.

### 19. Why detect a duplicate `external_id` from the database error instead of checking first?

Because "does this external_id exist?" followed by an INSERT is a race: two concurrent requests can both read "no" and both proceed, and the loser gets a 500 instead of a clean 409. The unique index is the only thing that can actually decide, so the duplicate necessarily arrives as an `IntegrityError` after the INSERT.

That means the handler has to identify *which* constraint failed rather than treating every integrity error as a duplicate — otherwise a future foreign-key or CHECK violation would also be reported to the client as "duplicate external_id", which is both wrong and misleading during an incident. I match on SQLSTATE `23505` (unique_violation) plus the constraint name, which asyncpg exposes on the exception wrapped inside SQLAlchemy's error; anything else is re-raised untouched.

### 20. How do the tests exercise real transaction boundaries without leaving data behind?

Each test opens one connection, begins a transaction, and rolls it back at the end. Sessions are created with `join_transaction_mode="create_savepoint"`, so a `commit()` inside a request handler releases a SAVEPOINT instead of ending the outer transaction — the application commits for real, and the test still discards everything. The assets table is empty after the suite runs.

The part I'd point at in review: the client fixture replaces the app's `get_sessionmaker` rather than overriding the `get_session` dependency. Overriding the dependency would mean the tests supply their own commit/rollback logic, so the transaction boundary — the thing most worth testing, since the audit-trail guarantee will depend on it — would never actually run. Replacing the sessionmaker keeps the real dependency in the path and only changes where the connection comes from.

Verified by breaking it deliberately: removing the `flush()` from the create handler failed five tests with `ResponseValidationError`, because the id is generated by PostgreSQL and does not exist on the object until the INSERT is sent.

### 21. Why a custom error body instead of FastAPI's default `{"detail": ...}`?

Clients need something stable to branch on, and a human-readable sentence is not it — wording changes are not supposed to be breaking changes. So handled errors return `code` (machine-readable, part of the contract), `message` (for a human reading a log) and `correlation_id`.

`correlation_id` is always null right now because the middleware that would populate it does not exist yet. I included the field anyway: adding a key later is a change every consumer has to be told about, and the cost of carrying a null today is zero. Request-validation failures still return FastAPI's own 422 shape — unifying those is worth doing when the error contract is finished, not as a side effect of this slice.

### 22. What happens to that 409 if the database or the driver changes underneath it?

Deciding "this is a duplicate" by matching SQLSTATE `23505` *and* the constraint name couples an API contract to two things the API layer does not own: the name of a database object, and the shape of a driver's exception. Both couplings are real, so I measured what each one costs.

Renaming the index makes the lookup return a name that no longer matches, the `IntegrityError` is re-raised, and the client gets a 500 instead of a 409. Two tests fail immediately, so it cannot reach `main` quietly. Changing drivers degrades the same way and just as loudly:

| Driver | Constraint name available? | Result |
|---|---|---|
| asyncpg (current) | yes, on the wrapped `__cause__` | 409 |
| psycopg 3 | no — SQLAlchemy passes its error through as `orig`, nothing wrapped | 500 |
| psycopg 2 | no — and it spells the code `pgcode`, not `sqlstate` | 500 |

The portable alternative is to match SQLSTATE alone, but it is coarser: every unique constraint on the table would then report itself as a duplicate `external_id`, which becomes wrong the moment a second one exists. I kept the precise version, because a misleading error code during an incident costs more than a driver migration that CI catches on the first run.

### 23. Which test actually protects the 409, and how do I know?

Only one of them, and finding out which took an experiment rather than a reading. `test_rejected_duplicate_leaves_the_original_intact` checks that a rejected duplicate leaves the first row intact; it never asserts the status code of the rejected request. When I removed the 409 mapping and added a generic 500 handler, that test stayed green while the endpoint's behaviour was broken. It fails today only because the unhandled exception escapes the test transport — an accident of the client, not an assertion.

That is a reasonable design, since each test asserts one thing and the status code is covered by `test_duplicate_external_id_is_rejected_with_409`. The point is what it implies: delete that one test and the suite is still green while the contract is unguarded. "The suite passes" and "the behaviour is covered" are different claims, and the only way I know of to tell them apart is to break the code on purpose and watch which tests notice.
