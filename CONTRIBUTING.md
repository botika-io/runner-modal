# Contributing

## Setup

```bash
uv sync
uv run pytest
uv run ruff check src/runner_modal tests examples
uv run ruff format --check src/runner_modal tests examples
uv run ty check
```

## CI

GitHub Actions runs on ``ubuntu-latest``. Run the setup commands above locally before opening a PR. The maintainer control plane (``scripts/ci_app.py``) is for dogfooding this product on real Jobs, not for repository CI.

## Conventions

See [AGENTS.md](AGENTS.md): entity-based public DX (`Runner` / `Runner.Job`), no free public helpers, explicit kwargs / named Secrets (no ambient credential `getenv` in primitives), claim-before-create, soft capacity.

## PRs

- Prefer small PRs with tests for security and race paths (HMAC, delivery claim, admission), not only export/signature checks.
- Do not add process-local registries, `ok: bool` response fields, or co-mounted webhook + GitHub secrets.
- Temporary profiling harnesses (`scripts/`) stay out of library PRs.
