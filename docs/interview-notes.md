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

---

## Day 4 — Work order slice and its foreign key

### 24. Why is an unknown asset a 404 rather than a 500 or a 400?

The request is syntactically valid — a well-formed UUID in the right field — so it passes schema validation and reaches the database, where the foreign key rejects it. Without handling, that surfaces as an unhandled `IntegrityError` and a 500, which tells the client "we broke" when the truth is "you referenced something that does not exist".

I chose 404 over 400 because the failure is about a resource that isn't there, which is what 404 means, and because it matches what `GET /assets/{id}` already returns for the same missing asset. A client that sees the same code for the same cause on both endpoints needs one branch, not two. The pattern is the same as the duplicate `external_id` 409: the database is the only race-free arbiter, so the violation necessarily arrives after the INSERT, and the handler's job is to translate it into the right contract.

### 25. Why name the foreign key explicitly, and why pin the name in a test?

Because the API decides 404-vs-500 by comparing the violated constraint's name, and I would rather match a name we chose than one PostgreSQL generated. Left to itself the constraint would be `work_orders_asset_id_fkey`; naming it `fk_work_orders_asset_id_assets` also means it already matches the convention the models will adopt, so adopting that convention later produces no drift to reconcile.

The coupling is still real, so there is a test asserting that a foreign key with exactly that name exists on the table. Renaming the constraint now fails a test whose name says what is wrong, instead of failing two endpoint tests with an `IntegrityError` that has to be traced back. Verified by pointing the constant at the old default name: three tests fail, and the pinning test is the one that explains why.

### 26. Why can't a client set `status` or `version` on create?

They are absent from the create schema, so a caller that sends them is ignored and the work order still starts at NEW with version 1 — there is a test for exactly that. If `status` were settable, the state machine would have a way around itself: a client could POST a work order that is already COMPLETED and skip every transition rule and audit event the design exists to guarantee. Ownership is the point — the client owns what work is needed, the server owns where that work has got to.

`version` is a column now but nothing increments it yet; the optimistic concurrency checks that will read it belong with the command endpoints.

### 27. Why is `asset_id` indexed but `status` deliberately not?

PostgreSQL does not create an index for a foreign key automatically, and every lookup of a work order goes through its asset, so `asset_id` is indexed.

`status` is left unindexed on purpose. It is the obvious column to filter on, which makes it the right subject for the query and index evidence work later: with a realistically sized table, the same filter can be shown as a sequential scan before an index and an index scan after. Adding the index now would remove the demonstration and leave nothing measurable to talk about.

---

## Day 5 — Two review findings, fixed

### 28. Why reject unknown request fields instead of ignoring them?

Pydantic drops fields it does not recognise by default, so a caller sending `descriptoin` gets a 201 and a work order with no description. For an API whose callers are other systems rather than people, that is silent data loss: nobody proof-reads a machine's JSON, and the mistake surfaces months later as missing data with no error anywhere to explain it. `extra="forbid"` turns it into a 422 on the integration's first call, which is the cheapest moment it can possibly fail.

I put the setting on a shared `RequestModel` base rather than on each schema, because it is a policy about how this API treats its callers, not a decision to re-make every time a schema is added. It also applies to the already-merged asset endpoint: two slices behaving differently on the same question is worse than either behaviour on its own.

The cost is that adding a field to a request schema can now break a caller who was already sending it under a name we did not know about — which is the right direction, since knowing what our own API accepts is our job.

### 29. What a test that assumed an empty database taught me

`test_rejected_work_order_leaves_no_partial_row` asserted `count(*) == 0` over the whole table. Every test runs inside a transaction that is rolled back, so I read that as "the table is empty" — but the rollback only discards *this test's* writes. Rows committed by anything else, including a manual `curl` against the same development database, are perfectly visible to it. Inserting a single row made the test fail with `assert 1 == 0`, which points at rollback rather than at the real cause.

The fix is to scope the assertion to the row the request would have written, using the asset id the test generated. The general rule: an assertion over "everything in the table" is really an assertion about the environment, and the environment is not something the test controls. The neighbouring asset tests already avoided this by asserting membership rather than totals — the inconsistency between two slices was the tell, which is the argument for reviewing the second implementation of a pattern side by side with the first rather than on its own.

---

## Day 6 — The state machine

### 30. Why explicit command endpoints rather than a status field someone can PATCH?

Full reasoning is in ADR-001; the short version is that each transition has its own required data, its own preconditions and its own eventual authorisation rule, and a generic `PATCH {"status": ...}` has nowhere natural to put any of them. "Completing requires a resolution" becomes "resolution is required, but only when status is becoming COMPLETED" — a rule about a transition disguised as a field validator. Commands also give the audit trail a unit to attach to: one command, one state change, one event, one transaction.

The rules live in a domain module as a pure function of `(command, current status)`, with no imports from FastAPI or SQLAlchemy, so the whole 4×5 matrix is unit-tested with no database and no HTTP. The matrix is written out by hand in the test rather than derived from the table it checks — a generated test would agree with the implementation by construction and prove nothing.

### 31. (Real problem hit) `MissingGreenlet` when returning an updated row

Every command endpoint failed with `MissingGreenlet: greenlet_spawn has not been called` while serialising the response — 16 tests at once. The cause was `updated_at`, which uses `onupdate=func.now()`: because that is a SQL expression, SQLAlchemy does not know the value the database computed, so after the flush it marks the attribute expired. Reading it during serialisation then attempts a blocking refresh, and under asyncio that raises instead of quietly issuing a second query.

The fix is `__mapper_args__ = {"eager_defaults": True}` on the timestamp mixin, which makes SQLAlchemy fetch the value back with `RETURNING` on the UPDATE, in the same round trip — the same mechanism that already supplies `id` and `created_at` on INSERT. The alternative, `await session.refresh()` after every command, costs an extra SELECT per request to get the same answer.

Worth noticing that async did not cause this bug, it *revealed* it. Synchronously the expired attribute would have triggered a silent extra query on every command and nothing would have looked wrong.

### 32. Why the test cannot assert that `updated_at` moved forward

The obvious assertion — after a command, `updated_at > created_at` — cannot pass here, and the reason is a property of PostgreSQL rather than of the code. `now()` returns the *transaction* start time, not the wall clock, so it is frozen for the life of a transaction; `clock_timestamp()` is the one that advances. Every request in a test shares the single outer transaction the fixture rolls back, so every timestamp inside one test is identical. In production each request is its own transaction and the value does advance.

So the test asserts the property that is actually at stake and is provable here: the timestamp in the response equals the one now stored in the row, i.e. the response is not serving the value the row was loaded with. Writing the stronger-looking assertion would have produced a test that fails for a reason unrelated to the behaviour it names.

### 33. Why a CHECK constraint on `status` and `priority` now, and what it cannot do

Entry 18 argued the value domain belongs in the database and the transition rules belong in the application; this is where that gets paid. The CHECK constraints mean no seed script, migration or manual `UPDATE` can put a status in the table that the application has never heard of — verified by trying: `INSERT ... status = 'REOPENED'` is refused by `ck_work_orders_status`.

What they cannot express is legality of a *move*, since that depends on the current row and eventually on who is asking. That stays in the domain module. The division is worth being able to state plainly: the database guarantees which values exist, the application guarantees how they change.

Note also that Alembic's autogenerate detected the three new columns and neither constraint — it does not compare CHECK constraints — so both were written into the migration by hand. That is the same class of blind spot as entry 16.

### 34. Why is reassignment a new command rather than one more line in the table?

Reviewing the state machine against the real workflow found a gap: `ASSIGN` was legal only from `NEW`, so once a work order was assigned there was no way to change who held it. A technician going off shift meant cancelling the work order and raising a new one, which loses the history and puts a false "cancelled" in the audit trail.

The cheap fix would have been to let `ASSIGN` run from `ASSIGNED` too — one line. It was rejected because of what the audit trail would then read like: two identical `ASSIGN` events, where the only way to discover that the second one changed hands is to compare payloads. Events should say what happened, so reassignment is its own command with its own name.

`REASSIGN` lands on `ASSIGNED` from either `ASSIGNED` or `IN_PROGRESS`. Handing work to someone else means the new assignee has not started it, whatever the previous one had done, so they start it themselves — which also keeps "someone is working on this" from drifting away from the status that claims it.

### 35. Why does `start` take a request body it never reads?

Because without one, FastAPI does not look at the request body at all, and `extra="forbid"` (entry 28) never runs. Measured before fixing it: `POST /start` with `{"total_nonsense": 123}` returned 200 and ignored it, while the same junk sent to `/complete` returned 422. One API, two answers to the same question, and the inconsistent one was the endpoint with nothing to validate.

The second reason is forward-looking. Optimistic concurrency will put an `expected_version` field on every command. With a body already there that is a new field on an existing shape; without one, `start` grows a body where a caller previously sent nothing, and any caller that had been sending `expected_version` all along would have had it silently ignored until the day it started being enforced.

The cost is a schema class with no fields, which looks silly in isolation. Worth it: a rule that holds on three endpoints out of four is not a rule, it is a habit.
