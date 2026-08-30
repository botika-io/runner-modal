---
name: runner-modal-deploy
description: >-
  Deploys runner-modal GitHub Actions self-hosted runner pools on Modal
  Sandboxes. Use when creating Modal Secrets, writing Runner.create apps,
  running modal deploy, registering GitHub workflow_job webhooks, or
  tearing down a pool. Not for hosted ubuntu-latest or generic Modal Apps.
---

# Deploying runner-modal

Operator-deployed webhook Function + one Job Sandbox per `workflow_job`.
Not a managed service. Human DX: `README.md`. Trust: `SECURITY.md`.

Copy `examples/basic/app.py` (CPU) or `examples/gpu/app.py` (GPU). Do not
invent a second resource profile on the same App.

## Rules

- Pin with `uv add git+https://github.com/modal-projects/runner-modal.git@v0.1.0`.
  Deploy from a checkout so Images can `add_local_python_source("runner_modal")`.
- Two named Secrets, never one: `github-token` (`GITHUB_TOKEN`, Jobs only)
  and `github-webhook` (`WEBHOOK_SECRET`, webhook Function only).
- One `Runner.create` per `modal.App` = one resource profile. GPU is a
  separate App. `repositories` required. Labels must include `self-hosted`.
- `cpu` / `memory` / `gpu` are Job defaults, not webhook Function size.
- Do not use a Modal Server for the webhook (503 on zero→one). Inputs queue.
- Redeploy overwrites Runner meta (last deploy wins).

```bash
modal secret create github-token GITHUB_TOKEN=ghp_xxx
modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
modal deploy examples/basic/app.py
```

Webhook: `{Runner.from_name("ci").url}/github`, `application/json`,
**Workflow jobs** only, same `WEBHOOK_SECRET`. One webhook per pool.

```bash
curl -sS "$URL/health"
```

Teardown: `Runner.objects.delete(name)`, then `modal app stop` and remove
the GitHub webhook. JIT runner rows exist only while a Job runs.

`max_concurrent` is soft (list-then-create), not a lock.
