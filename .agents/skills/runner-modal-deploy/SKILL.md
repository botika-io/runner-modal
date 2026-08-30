---
name: runner-modal-deploy
description: >-
  Deploys runner-modal GitHub Actions self-hosted runner pools on Modal
  Sandboxes. Use when creating Modal Secrets, writing Runner.create apps,
  running modal deploy, registering GitHub workflow_job webhooks, tearing
  down a pool, or setting up Modal CI for a repo. Not for hosted
  ubuntu-latest runners or generic Modal Apps.
---

# Deploying runner-modal

Self-hosted GitHub Actions on Modal: one webhook Function per pool, one
ephemeral Job Sandbox per `workflow_job`. Operator-deployed, not a managed
service.

Human DX: `README.md`. Trust model: `SECURITY.md`.
Workflows: `runner-modal-workflows`. Job images: `runner-modal-images`.
Failures: `runner-modal-troubleshoot`.

Reference integration: [Nordlys-Labs/nordlys `runners/`](https://github.com/Nordlys-Labs/nordlys/tree/main/runners).

## Workflow

Copy and check off:

```
- [ ] Pin runner-modal
- [ ] Split Secrets
- [ ] One App per pool
- [ ] modal deploy
- [ ] Webhook per pool
- [ ] Health check
```

### 1. Pin runner-modal

Separate uv project (Nordlys keeps this in `runners/`). PyPI is not set up;
Image builds need `add_local_python_source("runner_modal")` at deploy time.

```toml
[project]
name = "my-ci-runners"
requires-python = ">=3.12"
dependencies = ["modal>=1.5.2,<2", "runner-modal"]

[tool.uv.sources]
runner-modal = { git = "https://github.com/modal-projects/runner-modal.git", tag = "v0.1.0" }
```

```bash
uv sync
```

### 2. Split Secrets

Never merge these. Workflow code on a Job can read every mounted env key.

```bash
modal secret create github-token GITHUB_TOKEN=ghp_xxx
modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
```

| Secret | Keys | Mounted on |
|--------|------|------------|
| `github-token` | `GITHUB_TOKEN` | Job Sandboxes only |
| `github-webhook` | `WEBHOOK_SECRET` | webhook Function only |

PAT or GitHub App: `POST /repos/{owner}/{repo}/actions/runners/generate-jitconfig`
on allowlisted repos only (Administration: Read & write).

### 3. One App per pool

One `Runner.create` per `modal.App` = one resource profile. GPU is a
**separate App**, not a label on the CPU pool. Redeploy overwrites Runner
meta (last deploy wins).

`repositories` is required and non-empty. `labels` must include `self-hosted`.
Admission is fail-closed.

Start from `examples/basic/app.py` or `examples/gpu/app.py`:

```python
import modal
from runner_modal import Runner

app = modal.App("myorg-ci")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="ci",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    labels=["self-hosted", "modal", "ci"],
    region="us-east",
    cpu=2.0,
    memory=4096,
    max_concurrent=20,
    min_containers=0,
    idle_timeout=900,
)
```

`cpu` / `memory` / `gpu` are Job Sandbox defaults. The webhook Function stays
small (`buffer_containers=1` by default). Do not attach this as a Modal Server
(503 on zero→one). Inputs queue on the Function.

Nordlys shape: three pools, three Apps (`nordlys-ci`, `nordlys-ci-core`,
`nordlys-ci-gpu`), same two Secrets.

### 4. Deploy

```bash
uv run modal deploy cpu_app.py
```

`url` is `None` until the Function is deployed.

### 5. Webhook per pool

```python
from runner_modal import Runner
print(Runner.from_name("ci").url)  # …/webhook → payload is {url}/github
```

| Field | Value |
|-------|--------|
| Payload URL | `{url}/github` |
| Content type | `application/json` |
| Secret | same as `WEBHOOK_SECRET` |
| Events | **Workflow jobs** only |

One webhook per pool. Same secret is fine.

### 6. Health

```bash
curl -sS "$URL/health"
```

Returns `runner`, `labels`, `repositories` (count), `active_runners`,
`max_concurrent`. `GET /health` is public.

## Ops

| Task | Command |
|------|---------|
| Logs (webhook Function) | `modal app logs <app-name>` |
| Teardown pool state | `uv run python -c "from runner_modal import Runner; Runner.objects.delete('ci')"` |
| Stop App | `modal app stop <app-name>` then remove the repo webhook |

`Runner.objects.delete` removes `{name}-runner-meta`, `{name}-runner-deliveries`,
and `{name}-cache`. GitHub runner rows are ephemeral (JIT); they appear only
while a Job runs.

## Cost knobs

Per pool: `cpu` / `memory` / `gpu`, soft `max_concurrent` (list-then-create,
not a lock), `idle_timeout` (Job linger), `min_containers` / `buffer_containers`
(webhook warm pool; keep at `0` / `1`).

## Public-repo forks

Self-hosted Jobs run workflow code with `GITHUB_TOKEN` in the Sandbox. Prefer
approval for outside collaborators and read-only default workflow permissions.
See `SECURITY.md`.
