# runner-modal

Self-hosted [GitHub Actions](https://docs.github.com/en/actions) runners on [Modal](https://modal.com) Sandboxes.

You deploy your own Modal App and Secrets. This is not a managed multi-tenant service.

## Install

Python >= 3.12, a Modal account (`modal setup`), and repo admin on GitHub.

```bash
uv add git+https://github.com/modal-projects/runner-modal.git@v0.1.0
```

Deploy from a checkout (or editable install) so Image builds can
`add_local_python_source("runner_modal")`. PyPI is not set up yet.

## Agent skills

Install all integrator skills for Cursor, Claude Code, and
[other agents](https://skills.sh):

```bash
npx skills add modal-projects/runner-modal --all
npx skills add modal-projects/runner-modal --all -g
```

Project (`--all`) writes into the current repo. `-g` installs the same set
into your user skill directories.

| Skill | When |
|-------|------|
| `runner-modal-deploy` | Secrets, `Runner.create`, webhook, teardown |
| `runner-modal-workflows` | `runs-on`, unique pins, hosted vs Modal |
| `runner-modal-images` | `{name}-job`, GPU, `vm_runtime`, `/cache` |
| `runner-modal-troubleshoot` | 401 / 204 / 503, admit, queued forever |

## Quick start

### 1. Secrets

```bash
modal secret create github-token GITHUB_TOKEN=ghp_xxx
modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
```

Use a fine-scoped GitHub App or PAT that can call
`POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig`
on allowlisted repos.

### 2. Deploy

Copy [`examples/basic/app.py`](examples/basic/app.py), set
`repositories=["YOUR_ORG/YOUR_REPO"]`, then:

```bash
modal deploy examples/basic/app.py
```

One `Runner.create` per App = one resource profile. Redeploy overwrites Runner
meta (last deploy wins).

### 3. Webhook

```python
from runner_modal import Runner
print(Runner.from_name("ci").url)  # None until deployed
```

| Field | Value |
|-------|--------|
| Payload URL | `{url}/github` |
| Content type | `application/json` |
| Secret | same as `WEBHOOK_SECRET` |
| Events | **Workflow jobs** only |

### 4. Workflow

Copy [`examples/basic/workflow.yml`](examples/basic/workflow.yml) into
`.github/workflows/`. Labels must match `Runner.create(labels=…)`. Keep the
unique `job-${{ github.run_id }}-${{ github.job }}` pin.

## Examples

| Kit | When |
|-----|------|
| [`examples/basic/`](examples/basic/) | Standard CI |
| [`examples/gpu/`](examples/gpu/) | CUDA / ML (`gpu="T4"` Job defaults) |

GPU pool = separate App. Docker-in-CI:
`experimental_options={"vm_runtime": True}` on `Runner.create` (no GPU).
`cpu` / `memory` / `gpu` are **Job** Sandbox defaults; the webhook Function
stays small (`buffer_containers=1` by default).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| HTTP 401 | Webhook secret ≠ Modal `WEBHOOK_SECRET` |
| HTTP 204 + `X-Runner-Modal-Reason` | Admit miss: allowlist, labels, missing `self-hosted` |
| HTTP 503 | Soft `max_concurrent`, or delivery in flight |
| Job queued forever | Sandbox logs (JIT / boot); `GET /health`; Function `*.modal.run` URL |

## How it works

```text
GitHub workflow_job
  → webhook (Function + asgi_app)
  → admit (repo + labels)
  → claim delivery ID
  → Job.create → Sandbox
  → python -m runner_modal.entrypoint
  → mint JIT → ./run.sh --jitconfig …
```

`max_concurrent` is soft (list-then-create). See [SECURITY.md](SECURITY.md).

## Imperative jobs

```python
job = Runner.Job.create(
    runner,
    repository="YOUR_ORG/YOUR_REPO",
    labels=["self-hosted", "modal", "ci", "job-1"],
    github_secret=github,
    gpu="T4",
)
job.wait()
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE)
