# runner-modal

Self-hosted [GitHub Actions](https://docs.github.com/en/actions) runners on [Modal](https://modal.com) Sandboxes.

You deploy your own Modal App and Secrets. This is not a managed multi-tenant service.

`Runner` registers a webhook control plane. Jobs run as Sandboxes via `python -m runner_modal.job`.

## Requirements

- Python >= 3.12, [Modal](https://modal.com) CLI
- Two named Modal Secrets: `GITHUB_TOKEN` (Jobs) and `WEBHOOK_SECRET` (Server)

## Quick start

```bash
uv add git+https://github.com/modal-projects/runner-modal

modal secret create github-token GITHUB_TOKEN=ghp_xxx
modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
```

Not on PyPI yet — install from the GitHub repo. Then put this in e.g. `app.py` and `modal deploy app.py`:

```python
import modal
from runner_modal import Runner

app = modal.App("runner-modal-ci-app")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="ci",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    compute_region="us-east",
    labels=["self-hosted", "modal", "ci"],
    max_concurrent=20,
    min_containers=0,
    idle_timeout=900,
)
```

```python
print(Runner.from_name("ci").url)  # None until ready
# Webhook URL: {url}/github
```

```yaml
runs-on:
  - self-hosted
  - modal
  - ci
  - job-${{ github.run_id }}-${{ github.job }}
```

One `Runner.create` per App. It publishes named Image `{name}-job`. Include every pool label plus a unique pin so one runner maps to one job. Use `min_containers=0` to keep the App deployed while scaling the control plane to zero when idle.

| Key | Secret | Mounted on | Purpose |
|-----|--------|------------|---------|
| `GITHUB_TOKEN` | `github_secret` | Job Sandbox only | Mint JIT inside the job |
| `WEBHOOK_SECRET` | `webhook_secret` | Server only | HMAC on `POST /github` |

Never put both keys in one Secret. Never put tokens or JIT in Sandbox `env=`.

## How it works

```text
GitHub  --workflow_job-->  RunnerServer
                              |
                       admit (repo + labels)
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
| Meta | Dict `{name}-runner-meta` | Labels, repos, capacity, secret/image names |
| Deliveries | Dict `{name}-runner-deliveries` | Claim before create |
| Job image | Named Image `{name}-job` | Published at `Runner.create` |
| Cache | Volume `{name}-cache` → `/cache` | Optional (`cache=True`); same-pool Volume, not `actions/cache` |
| Control plane | Server `RunnerServer` | HMAC, admission, create/cancel |
| Job | Sandbox | `python -m runner_modal.job` |

Admission: repository is in `repositories`, job has `self-hosted`, pool is non-empty, and `pool ⊆ job.labels`.

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
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])

job = Runner.Job.create(
    runner,
    repository="modal-projects/runner-modal",
    labels=["modal", "ci", "job-1"],
    github_secret=github,
    gpu="t4",
)
job.wait()
```

Docker / VM (no GPU): `experimental_options={"vm_runtime": True}`. Job kwargs are Modal Sandbox-shaped: `cpu`, `memory`, `gpu`, `experimental_options`.

## API

| Call | Notes |
|------|-------|
| `Runner.create(app, name, github_secret=…, webhook_secret=…, repositories=…)` | Registers Server + publishes job Image |
| `Runner.from_name` / `objects` / `ephemeral` | Named handle / admin |
| `runner.url` | Server URL, or `None` until ready |
| `Runner.Job.create(…, repository=…, github_secret=…)` | Eager job Sandbox |
| `Runner.Job.from_id` / `from_name` / `wait` | Lookup / block |
| `POST {url}/github` | Admit → claim → create → 200 / 204 / 5xx |

| Situation | Result |
|-----------|--------|
| Undeployed | `runner.url is None` |
| Ignored webhook | HTTP 204 |
| Bad args | `ValueError` |
| Missing meta | `LookupError` |
| Bad HMAC / missing delivery | `AuthError` / HTTP 401 |
| At `max_concurrent` | `ConcurrencyLimitError` / HTTP 503 |
| Delivery in progress | HTTP 503 |
| `job.wait` timeout | `JobTimeoutError` |

## Security

See [SECURITY.md](SECURITY.md). Short version: HMAC proves the webhook secret, not repo ACL; `repositories` is required; Jobs never see `WEBHOOK_SECRET`; treat fork PRs as hostile; `max_concurrent` is soft.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src/runner_modal tests examples
uv run ruff format --check src/runner_modal tests examples
uv run ty check
```

See [`AGENTS.md`](AGENTS.md) for conventions and [`CONTRIBUTING.md`](CONTRIBUTING.md) for PRs.

## License

[Apache License 2.0](LICENSE)
