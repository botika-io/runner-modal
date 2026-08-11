# runner-modal

Self-hosted [GitHub Actions](https://docs.github.com/en/actions) runners on [Modal](https://modal.com) Sandboxes.

You deploy your own Modal App and Secrets. This is not a managed multi-tenant service.

## Requirements

- Python >= 3.12, [Modal](https://modal.com) account + CLI (`modal setup`)
- Repo admin on GitHub (webhook + token)
- Two named Modal Secrets: `GITHUB_TOKEN` (Jobs) and `WEBHOOK_SECRET` (webhook Function)

## Quick start (basic CI)

### 1. Install

Until a PyPI release, install from GitHub (prefer a tag once one exists):

```bash
uv add git+https://github.com/modal-projects/runner-modal.git@main
# after first release: …runner-modal.git@v0.1.0
```

Deploy from a checkout (or editable install) so Modal Image builds can
`add_local_python_source("runner_modal")`. Copy `examples/basic/app.py`, set
`repositories=[…]`, then `modal deploy …`. GitHub Releases publish sdists;
PyPI publish is not set up yet.

Redeploying `Runner.create` overwrites Runner meta (last deploy wins).

### 2. Secrets

```bash
modal secret create github-token GITHUB_TOKEN=ghp_xxx
modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
```

Prefer a fine-scoped GitHub App or PAT that can call `POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig` on allowlisted repos (classic: `repo` + admin on self-hosted runners; App: Administration read/write for runners).

### 3. Deploy

Copy [`examples/basic/app.py`](examples/basic/app.py), set `repositories=["YOUR_ORG/YOUR_REPO"]`, then:

```bash
modal deploy examples/basic/app.py
```

### 4. Webhook URL

```python
from runner_modal import Runner
print(Runner.from_name("ci").url)  # None until the App is deployed
# GET {url}/health
```

In GitHub → Settings → Webhooks → Add webhook:

| Field | Value |
|-------|--------|
| Payload URL | `{url}/github` |
| Content type | `application/json` |
| Secret | same value as `WEBHOOK_SECRET` |
| Events | **Workflow jobs** only |

### 5. Workflow

Copy [`examples/basic/workflow.yml`](examples/basic/workflow.yml) into `.github/workflows/`. Pool labels must match `Runner.create(labels=…)`. Keep the unique `job-${{ github.run_id }}-${{ github.job }}` pin.

## Examples

| Kit | When |
|-----|------|
| [`examples/basic/`](examples/basic/) | Standard checkout + test CI |
| [`examples/gpu/`](examples/gpu/) | CUDA / ML jobs (`gpu="T4"` Job defaults) |

One `Runner.create` per App = one resource profile. GPU pool = separate App (see `examples/gpu/`). Docker-in-CI: `experimental_options={"vm_runtime": True}` on `Runner.create` (no GPU).

`cpu` / `memory` / `gpu` on `Runner.create` are **Job** Sandbox defaults. The webhook Function stays small (`buffer_containers=1` by default so cold starts rarely race GitHub’s delivery timeout).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| HTTP 401 | Webhook secret ≠ Modal `WEBHOOK_SECRET` |
| HTTP 204 + `X-Runner-Modal-Reason` | Admit miss: repo allowlist, labels, missing `self-hosted`, empty pool |
| HTTP 503 capacity / busy | Soft `max_concurrent`, or delivery in flight |
| Job queued forever | Modal Sandbox logs (JIT 401/403, runner boot); `GET /health`; confirm webhook URL is the Function `*.modal.run` URL |

## How it works

```text
GitHub  --workflow_job-->  webhook (Function + asgi_app)
                              |
                       admit (repo + labels)
                              |
                       claim delivery ID
                              |
                       Job.create -> Sandbox
                              |
                       python -m runner_modal.entrypoint
                              |
                       mint JIT -> ./run.sh --jitconfig …
```

`max_concurrent` is soft (list-then-create). See [SECURITY.md](SECURITY.md).

## Imperative jobs

```python
job = Runner.Job.create(
    runner,
    repository="YOUR_ORG/YOUR_REPO",
    labels=["self-hosted", "modal", "ci", "job-1"],
    github_secret=github,
    gpu="T4",  # overrides Runner defaults when set
)
job.wait()
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check src/runner_modal tests examples
uv run ruff format --check src/runner_modal tests examples
uv run ty check
```

## License

[Apache License 2.0](LICENSE)
