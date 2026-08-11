# Changelog

## Unreleased

### Changed

- Quick start installs with `uv add git+https://github.com/modal-projects/runner-modal` (not PyPI yet).
- Control-plane and job Images install the package from GitHub via `uv_pip_install` (works outside this repo clone).

## 0.1.0

### Breaking

- `Runner.create` requires `github_secret`, `webhook_secret`, and non-empty `repositories` (replaces single `secret=`).
- `Runner.Job.create` takes `github_secret=` (replaces `secret=`).
- Webhook admission requires repository allowlist match; cancel uses the same gate.
- `X-GitHub-Delivery` is required (no fallback to workflow job id).
- Default `cache=False`.
- `RunnerMeta` / `RunnerInfo` use `github_secret_name` / `webhook_secret_name` (no `secret_name`).
- Server mounts only `webhook_secret`; Jobs mount only `github_secret`.

### Added

- `SECURITY.md`, `CONTRIBUTING.md`
- Delivery `bind_object` so successful creates are not TTL-reclaimed into a second Sandbox
- Dogfood App `runner-modal-ci-app` with `min_containers=0`
