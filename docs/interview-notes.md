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

<!-- Day 2 entries go below this line -->
