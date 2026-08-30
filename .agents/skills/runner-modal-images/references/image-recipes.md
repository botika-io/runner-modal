# runner-modal image recipes

## Contents

- What each Image is
- `default_image` (Debian)
- `docker_image` (Ubuntu VM)
- Custom rebuild + publish
- Webhook Function `image=`

## What each Image is

| Image | Who uses it | How it is chosen |
|-------|-------------|------------------|
| `control_plane_image()` | webhook Function | `Runner.create(image=)` or the default |
| `{name}-job` Named Image | Job Sandboxes | Always `Image.from_name`. Stock publish at `Runner.create`, optional overwrite after |

Do not pass a custom Job recipe as `Runner.create(image=)`. That only
replaces the webhook Function image.

## `default_image` (Debian)

`modal.Image.debian_slim(python_version="3.12")` plus:

- apt: `curl`, `ca-certificates`, `git`, `libicu-dev`, `liblttng-ust1`,
  `libssl3`, `tar`, `unzip`, `zip`
- `uv_pip_install(*JOB_DEPS)` (`httpx`, `modal`, `pydantic`, `tenacity`)
- `add_local_python_source("runner_modal", copy=True)`
- `RUNNER_ALLOW_RUNASROOT=1`
- `Runner.install_actions_runner` (pinned Actions runner tarball + SHA-256)

`actions/setup-python` often lacks Debian builds. Prefer `setup-uv` or
`add_python` on a custom base.

## `docker_image` (Ubuntu VM)

Used when `experimental_options={"vm_runtime": True}`. Base
`ubuntu:24.04` plus `docker.io` / `docker-buildx`. No GPU.

## Custom rebuild + publish

1. Start from a registry image (`ubuntu:24.04` with `add_python="3.12"`,
   or another glibc Linux x64).
2. Install Actions runner deps (icu, ssl, git, curl, tar/zip). Ubuntu
   t64 packages are `liblttng-ust1t64` / `libssl3t64`.
3. `uv_pip_install(*JOB_DEPS)` then extra tools.
4. `add_local_python_source("runner_modal", copy=True)`.
5. `Runner.install_actions_runner(image)`.
6. `Runner.create(…)` (publishes stock `{name}-job`).
7. `custom.build(modal.App.lookup(app_name, create_if_missing=True)).publish(f"{name}-job")`.

`install_actions_runner` downloads
`actions-runner-linux-x64-{version}.tar.gz` and checks
`DEFAULT_RUNNER_SHA256` from `runner_modal.meta`.

## Webhook Function `image=`

Leave unset unless the control plane itself needs extra packages. Jobs
never see this image.
