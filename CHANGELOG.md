# Changelog

## Unreleased

### Breaking

- Control plane is a Function `@modal.asgi_app` (not Modal Server). URL host is `*.modal.run`; re-point GitHub webhooks after redeploy.
- `Runner.create` uses `region=` (not `compute_region=`). Meta field `webhook_function` replaces `server_name`.
- `Runner.create` requires non-empty `labels`; default `min_containers=0`, `buffer_containers=1`.
- `cpu` / `memory` / `gpu` on `Runner.create` are Job Sandbox defaults (not control-plane resources).
- Images install runtime deps from PyPI and bake local `runner_modal` (`add_local_python_source`); Actions runner tarball is checksum-verified. `PACKAGE_SPEC` documents the operator install pin (`@main` until public tag).
- Removed `StageClock` / `runner_modal.profile` (tracing TBD).
- Job entrypoint: `JobSpec.start` / `JobSpec.mint_jitconfig` (no free `mint_jitconfig` helper).

### Added

- Durable delivery bind (`bind_object_durable`) before accept; bind failure → terminate + 503.
- Webhook outcome headers (`X-Runner-Modal-Outcome`, `X-Runner-Modal-Reason`) and richer `/health`.
- `Runner.admit_reason` for fail-loud admission.
- Consumer kits: `examples/basic/`, `examples/gpu/`.
- GitHub Release workflow on `v*` tags (source dist; not PyPI).

### Changed

- Quick start documents webhook UI, token scopes, and troubleshooting.
- Module `api` / `server` → `webhook` (ASGI entry + FastAPI collaborators).

## 0.1.0

### Breaking

- `Runner.create` requires `github_secret`, `webhook_secret`, and non-empty `repositories`.
- `Runner.Job.create` takes `github_secret=`.
- Webhook admission requires repository allowlist; `X-GitHub-Delivery` required.
- Default `cache=False`.
- Server mounts only `webhook_secret`; Jobs mount only `github_secret`.

### Added

- `SECURITY.md`, `CONTRIBUTING.md`
- Delivery `bind_object` so successful creates are not TTL-reclaimed into a second Sandbox
- Dogfood App `runner-modal-ci-app` with `min_containers=0`
