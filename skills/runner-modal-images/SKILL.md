---
name: runner-modal-images
description: >-
  Customizes runner-modal Job images (Named Image {name}-job, GPU, Docker
  VM, /cache). Use when changing the Job recipe, enabling cache=True, or
  setting runtime. Not for generic Modal Image tutorials.
---

# Customizing runner-modal Job images

Jobs load the published Named Image `{name}-job`.
`Runner.create(image=)` is the **webhook Function** image only.

## Rules

- Default CPU: `Runner.create` publishes `default_image()` as `{name}-job`.
- GPU: separate App, `gpu=` on `Runner.create`. See `examples/gpu/app.py`.
- Docker-in-CI: `runtime="vm"` (no GPU, Modal SDK 1.6+).
- Custom toolchain: build with `Runner.install_actions_runner`, then
  `.publish(f"{name}-job")` **after** `Runner.create`. Last publish wins.
  Keep `JOB_DEPS`, `add_local_python_source("runner_modal", copy=True)`,
  and `RUNNER_ALLOW_RUNASROOT=1`. No `Path` / `add_local_dir`.
- `cache=True` mounts `{name}-cache` at `/cache` for every Job in that
  pool. Same-pool only. Default is `cache=False`.

Point tools at `/cache` in the workflow when you enable it.
