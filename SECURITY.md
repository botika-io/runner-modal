# Security

`runner-modal` is an **operator-deployed** library. You run it in your Modal workspace with your GitHub credentials. It is not a managed multi-tenant service and does not isolate customers from each other.

## Trust model

| Signal | What it proves | What it does not prove |
|--------|----------------|------------------------|
| HMAC (`WEBHOOK_SECRET`) | Request holder knows the webhook secret (normally GitHub) | That a repository is allowed to spend your Modal account |
| `repositories` allowlist | Repo is explicitly permitted | Workflow code is trusted |
| Label match (`pool ⊆ runs-on`) | Job targeted this pool | Soft capacity will not overshoot |

Admission is fail-closed: repository must be in `repositories`, pool labels must match, and `self-hosted` must be present. Ignored deliveries return HTTP 204 with `X-Runner-Modal-Reason`.

## Job resources

`cpu` / `memory` / `gpu` on `Runner.create` are default **Job** Sandbox resources. The webhook Function does not take those knobs. One Runner = one resource profile.

## Secrets

Use **two** named Modal Secrets:

1. **`github_secret`** — `GITHUB_TOKEN` only — mounted on Job Sandboxes
2. **`webhook_secret`** — `WEBHOOK_SECRET` only — mounted on the webhook Function

Never put both keys in one Secret. Workflow code on a Job can read every env key Modal mounts. If `WEBHOOK_SECRET` is present in a Job, a hostile workflow can forge control-plane requests.

Prefer a fine-scoped GitHub App or PAT limited to runner JIT / admin on the allowlisted repos.

## Public webhook URL

`Runner.create` registers a public `@modal.asgi_app` Function so GitHub can POST. Auth for `/github` is HMAC only. `GET /health` is public and reports name and concurrency counts. Cold-start requests **queue** (Function inputs); they are not rejected with 503 the way Modal Servers reject zero→one traffic.

## Shared `/cache`

`cache=True` mounts one Volume at `/cache` for all jobs in the pool. Same-pool jobs can read/write each other’s cache. Default is `cache=False`. This is not the GitHub Actions `actions/cache` service.

## Soft capacity

`max_concurrent` is a soft list-then-create check. Concurrent creators can overshoot. Treat it as cost guidance, not a hard reservation.

## Delivery bind

After a Job Sandbox is created, the control plane durable-binds `object_id` onto the delivery claim before HTTP 200. Pending claims **with** `object_id` are never TTL-reclaimed. If bind cannot be made durable, the Job is terminated, the unbound claim is released, and GitHub receives HTTP 503 so it can retry.

## Fork PRs and untrusted workflows

Self-hosted runners execute workflow steps with access to the Job environment (including `GITHUB_TOKEN`). Treat fork PRs and untrusted workflows as hostile. Prefer private repos, trusted branches, and unique `runs-on` pins (`job-${{ github.run_id }}-${{ github.job }}`).

## Reporting issues

Open a private security report via GitHub Security Advisories on this repository when available, or contact the maintainers listed in the repo.
