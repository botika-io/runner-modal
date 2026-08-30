---
name: runner-modal-troubleshoot
description: >-
  Diagnoses runner-modal Modal runner failures (GitHub webhook 401/204/503,
  X-Runner-Modal-Reason admit misses, jobs queued forever, JIT boot,
  matrix pin collisions). Use when a self-hosted Modal Actions job never
  starts, the webhook ignores a delivery, or health/active_runners look
  wrong. Not for generic Actions or Modal Function debugging.
---

# Troubleshooting runner-modal

Fail-closed admit, HMAC on the raw body, delivery claim before
`Job.create`. Soft `max_concurrent` is list-then-create, not a lock.

Deploy: `runner-modal-deploy`. Workflows: `runner-modal-workflows`.
Images: `runner-modal-images`. Trust model: `SECURITY.md`.

## Symptom table

| Symptom | Check |
|---------|--------|
| HTTP 401 | GitHub webhook secret ≠ Modal `WEBHOOK_SECRET` |
| HTTP 204 + `X-Runner-Modal-Reason` | Admit miss (table below) |
| HTTP 503 | Soft `max_concurrent` overshoot, or delivery in flight / bind failure |
| Job queued forever | Sandbox logs (JIT / boot); `GET /health`; confirm Function `*.modal.run` URL, not a Server |
| Matrix collision | Two legs share the same pin (missing literal suffix) |
| Hosted action fails on Modal | `setup-python` on Debian; `actions/cache` vs `/cache` |
| Webhook never hits Modal | Events ≠ **Workflow jobs**; payload URL missing `/github`; wrong pool URL |

## Admit reasons (`X-Runner-Modal-Reason`)

`admit_reason(labels, repository)` returns `None` if admitted.

| Reason | Cause |
|--------|--------|
| `repository_mismatch` | `repository` not in `Runner.create(repositories=…)` |
| `missing_self_hosted` | `runs-on` omitted `self-hosted` |
| `label_mismatch` | pool labels ⊈ job labels |
| `no_repositories` / `empty_pool_labels` | broken meta; redeploy `Runner.create` |

Fix labels/allowlist and re-run. Ignored deliveries are 204 by design.

## Health

```bash
curl -sS "$URL/health"
```

`runner`, `labels`, `repositories` (count), `active_runners`,
`max_concurrent`. `url` is `None` until the webhook Function is deployed.

```python
from runner_modal import Runner
print(Runner.from_name("ci").url)
print(Runner.from_name("ci").info())
```

## Logs

| Layer | Where |
|-------|--------|
| HMAC / admit / claim | `modal app logs <app-name>` (webhook Function) |
| JIT mint / `./run.sh` | Job Sandbox logs |
| GitHub side | Actions job “Queued” / runner registration (JIT rows are ephemeral) |

## 503

- Soft capacity: `active_runners >= max_concurrent` at list time. Concurrent
  creates can still overshoot. Raise `max_concurrent` or wait.
- Delivery already claimed (`skip_if_exists`) and still in flight.
- Bind of `object_id` failed: Job is terminated when possible; claim stays
  if terminate is unconfirmed. GitHub retries.

Do not treat 503 as “use a Modal Server”. Servers reject zero→one with
503; this webhook is a Function so inputs queue on cold start.

## Queued forever

1. `GET /health` — Function up? `active_runners` at cap?
2. GitHub webhook recent deliveries — 401 / 204 / 503 / 200?
3. Pin unique per matrix leg (`runner-modal-workflows`)?
4. Sandbox logs — `generate-jitconfig` 403 (token scope / allowlist),
   image pull, `python -m runner_modal.entrypoint`.
5. Payload URL is `{Function.get_web_url()}/github`, not a Server URL.

## Compose

- Secrets / App / webhook missing → `runner-modal-deploy`
- `runs-on` / pin / hosted split → `runner-modal-workflows`
- Job image / GPU / `/cache` / `vm_runtime` → `runner-modal-images`
