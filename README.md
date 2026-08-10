# runner-modal

Self-hosted [GitHub Actions](https://docs.github.com/en/actions) runners on [Modal](https://modal.com).

`Runner` registers a webhook control plane. Jobs run as Sandboxes (`python -m runner_modal.job`). The API mirrors Modal: `Runner` ≈ Volume + Server, `Runner.Job` ≈ Sandbox.

## Requirements

- Python >= 3.12, [Modal](https://modal.com) CLI
- Named Modal Secret with `GITHUB_TOKEN` and `WEBHOOK_SECRET`

## Quick start

```bash
uv sync

modal secret create github-runner \
  GITHUB_TOKEN=ghp_xxx \
  WEBHOOK_SECRET=$(openssl rand -hex 32)

modal deploy examples/github_webhook.py
```

```python
import modal
from runner_modal import Runner

app = modal.App("acme-ci")
gh = modal.Secret.from_name(
    "github-runner",
    required_keys=["GITHUB_TOKEN", "WEBHOOK_SECRET"],
)

Runner.create(
    app=app,
    name="acme",
    secret=gh,
    compute_region="us-east",
    labels=["self-hosted", "modal", "acme"],
    max_concurrent=20,
    idle_timeout=900,
)
```

```python
print(Runner.from_name("acme").url)  # None until ready
# Webhook URL: {url}/github
```

```yaml
runs-on:
  - self-hosted
  - modal
  - acme
  - job-${{ github.run_id }}-${{ github.job }}
```

One `Runner.create` per App. It publishes named Image `{name}-job` and stores `secret_name` / `job_image_name` for the webhook path. Include every pool label plus a unique pin so one runner maps to one job.

| Key | Used by | Purpose |
|-----|---------|---------|
| `GITHUB_TOKEN` | Job Sandbox | Mint JIT inside the job |
| `WEBHOOK_SECRET` | Server | HMAC on `POST /github` |

Named Secrets only. Never put tokens or JIT in Sandbox `env=`.

## How it works

```text
GitHub  --workflow_job-->  RunnerServer
                              |
                       claim delivery ID
                              |
                       Job.create -> Sandbox
                              |
                       python -m runner_modal.job
                              |
                       mint JIT -> ./run.sh --jitconfig …
```

| Piece | Modal object | Role |
|-------|--------------|------|
| Meta | Dict `{name}-runner-meta` | Labels, capacity, secret/image names |
| Deliveries | Dict `{name}-runner-deliveries` | Claim before create |
| Job image | Named Image `{name}-job` | Published at `Runner.create` |
| Cache | Volume `{name}-cache` → `/cache` | Optional; not `actions/cache` |
| Control plane | Server `RunnerServer` | HMAC, admission, create/cancel |
| Job | Sandbox | `python -m runner_modal.job` |

Admission: job has `self-hosted`, pool is non-empty, and `pool ⊆ job.labels`.

Examples: [`github_webhook.py`](examples/github_webhook.py), [`imperative_create.py`](examples/imperative_create.py).

## Performance

Time-to-start, cold vs warm, concurrency, and idle cost (not workflow pytest time):

![Time to runner ready](docs/time-to-ready.png)

![Warm queue budget](docs/queue-budget.png)

![Concurrency / burst](docs/concurrency.png)

![Idle vs active cost](docs/idle-cost.png)

Charts are illustrative. Regenerate with `uv run --group dev python scripts/charts.py`.

`max_concurrent` is soft (list-then-create TOCTOU). Idle cost is mostly `min_containers`; jobs are ephemeral Sandboxes.

## Imperative jobs

```python
gh = modal.Secret.from_name("github-runner", required_keys=["GITHUB_TOKEN"])

job = Runner.Job.create(
    runner,
    repository="acme/api",
    labels=["modal", "acme", "job-1"],
    secret=gh,
    gpu="t4",
)
job.wait()
```

Docker / VM (no GPU): `experimental_options={"vm_runtime": True}`. Resources are Modal-flat: `cpu`, `memory`, `gpu`, `experimental_options`.

## API

| Call | Modal analogue |
|------|----------------|
| `Runner.create(app, name, secret=…)` | `@app.server` + publish job Image |
| `Runner.from_name` / `objects` / `ephemeral` | `Volume.*` |
| `runner.url` | `Server.get_url()` (`None` until ready) |
| `Runner.Job.create(…, repository=…, secret=…)` | `Sandbox.create` |
| `Runner.Job.from_id` / `from_name` / `wait` | `Sandbox.*` |
| `POST {url}/github` | Claim → create → 200 / 204 / 5xx |

| Situation | Result |
|-----------|--------|
| Undeployed | `runner.url is None` |
| Ignored webhook | HTTP 204 |
| Bad args | `ValueError` |
| Missing meta | `LookupError` |
| Bad HMAC / missing secret | `AuthError` |
| At `max_concurrent` | `ConcurrencyLimitError` / HTTP 503 |
| Delivery in progress | HTTP 503 |
| `job.wait` timeout | `JobTimeoutError` |

## Security

Self-hosted runners execute workflow code with access to the runner environment. Treat fork PRs and untrusted workflows as hostile. Prefer private repos or trusted branches before exposing a shared org webhook.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src/runner_modal tests examples
uv run ruff format --check src/runner_modal tests examples
uv run ty check
```

See [`AGENTS.md`](AGENTS.md) for conventions.
