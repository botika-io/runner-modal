# Changelog

## Unreleased

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
- CI on `ubuntu-latest`
- Delivery `bind_object` so successful creates are not TTL-reclaimed into a second Sandbox
