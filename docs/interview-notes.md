# Interview Notes

Running log of decisions I made and must be able to defend out loud. Rule from the plan: **code I cannot explain does not merge to `main`.** Each entry pairs the decision with the "why" and the answer I'd give an interviewer. Bilingual: English term first (for the interview), Chinese for my own recall.

---

## Day 1 — Scaffold & toolchain

### 1. Why does `/health/live` not touch the database?

**EN:** Liveness and readiness are different questions. `live` proves the process is running; `ready` proves it can serve traffic (DB reachable). An orchestrator restarts a container that fails *liveness* — but restarting won't fix a down database, so a DB check belongs in *readiness*, where the platform instead stops routing traffic until it recovers. Mixing them causes restart storms during a DB blip.

**中文：** live 只证明进程活着，ready 证明能对外服务。探针失败时 live→重启进程，ready→停止导流。数据库挂了重启进程没用，所以 DB 检查放 ready。混在一起会在数据库抖动时引发重启风暴。

### 2. Why an `create_app()` factory instead of a module-level `app`?

**EN:** The factory returns a fresh, fully-configured instance on demand. Tests get an isolated app each run, and I can later inject different settings (test DB vs prod DB) without editing application code. A module-level singleton binds configuration at import time, which fights testability.

**中文：** 工厂按需返回干净实例，测试隔离，后期能注入不同配置（测试库/生产库）而不改代码。模块级单例在 import 时就绑定配置，不利于测试。

### 3. Why `mypy --strict` and Ruff from commit one?

**EN:** Type and lint debt compounds. Turning on strict typing at the start costs almost nothing; retrofitting it onto a mature codebase surfaces hundreds of errors at once and usually gets abandoned. Same logic for lint/format — the CI gate keeps `main` consistently clean instead of relying on discipline.

**中文：** 类型/lint 债会复利。一开始开 strict 几乎零成本；成熟后再开会被几百个报错淹没而放弃。CI 门槛保证 main 一直干净，不靠自觉。

### 4. Why commit `uv.lock`, and what does `uv sync --locked` buy me?

**EN:** The lockfile pins exact versions of every transitive dependency, so my machine, a teammate's, and CI all build byte-identical environments — reproducible builds. `--locked` in CI *fails* if the lockfile and `pyproject.toml` have drifted, catching a forgotten `uv lock` before it reaches `main`.

**中文：** 锁文件钉死所有传递依赖的确切版本，本地/同事/CI 构建完全一致（可复现构建）。CI 里 `--locked` 在锁文件与 pyproject 不一致时直接失败，防止漏提交锁文件。

### 5. (Real problem hit) pytest couldn't import `app` — why `pythonpath` instead of packaging?

**EN:** Tests failed with `ModuleNotFoundError: No module named 'app'` because the project root wasn't on `sys.path`. I set `pythonpath = ["."]` in pytest config rather than turning the app into an installable package, because this app is a **deployment unit** (the uvicorn target `app.main:app`), not a library meant to be `pip install`-ed. Packaging it would add build config that serves no one.

**中文：** 报错找不到 app 模块，因为项目根不在 sys.path。我在 pytest 配置加 `pythonpath=["."]` 而不是打包，因为这个 app 是部署单元（uvicorn 目标），不是要被安装的库，打包纯属多余。

### 6. (Real problem hit) why `httpx2` instead of `httpx` for the test client?

**EN:** Starlette's `TestClient` emitted a deprecation warning that its httpx-based transport is going away in favour of `httpx2`. I switched the test dependency rather than suppress the warning — silencing deprecation warnings just defers the break to an inconvenient time.

**中文：** Starlette 的 TestClient 提示其 httpx 传输将废弃、改用 httpx2。我换依赖而不是压制警告——压制只是把破坏推迟到更糟的时刻。

---

<!-- Day 2 entries go below this line -->
