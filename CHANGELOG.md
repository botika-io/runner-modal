# Changelog

## 0.1.0

### Breaking

- Control plane is a Function `@modal.asgi_app` (not Modal Server). URL host is `*.modal.run`.
- `Runner.create` uses `region=` (not `compute_region=`). Meta field `webhook_function` replaces `server_name`.
- `Runner.create` requires `github_secret`, `webhook_secret`, non-empty `repositories` and `labels`.
- `cpu` / `memory` / `gpu` on `Runner.create` are Job Sandbox defaults (not control-plane resources).
- Default `min_containers=0`, `buffer_containers=1`, `cache=False`.
- Images install runtime deps from PyPI and bake local `runner_modal` (`add_local_python_source`).
- `Runner.Job.create` takes `github_secret=`. Webhook mounts only `webhook_secret`; Jobs mount only `github_secret`.
- Module `api` / `server` → `webhook`. Removed `StageClock` / `runner_modal.profile`.
- Job Sandbox entrypoint module is `runner_modal.entrypoint` (`python -m runner_modal.entrypoint`).
- `Runner.Job.wait()` matches unbounded `Sandbox.wait` (no `timeout=`).
- `DeliveryStore.claim` / `bind` replace earlier claim/bind helpers.
- `admit_reason` is the admission API (`None` when admitted).
- `Runner.objects.create` requires non-empty `repositories` (`owner/repo`).
- `Runner.Job.create` rejects jobs that fail admission.
- Removed unused public `JobTimeoutError`.

### Added

- Delivery claim/bind before accept; webhook outcome headers and `/health`.
- `Runner.admit_reason` for fail-loud admission.
- `Runner.objects.delete` also removes `{name}-runner-deliveries`.
- Consumer kits: `examples/basic/`, `examples/gpu/`.
- GitHub Release workflow on `v*` tags (source dist; not PyPI).
- `SECURITY.md`, `CONTRIBUTING.md`
- Stateful delivery claim/bind/release tests.

### Changed

- Bind failure: release claim only after confirmed `terminate`; otherwise leave claim and return 503.
- Stale delivery reclaim overwrites in place (no delete-then-put).
- Maintainer CI App lives at `scripts/ci_app.py` (not under `examples/`).
- Install pin is `git+…@v0.1.0` (`PACKAGE_SPEC`).
