---
name: runner-modal-images
description: >-
  Customizes runner-modal Job images on Modal (Named Image {name}-job,
  GPU pools, Docker VM runtime, shared /cache Volume). Use when rebuilding
  the Actions runner recipe, publishing over ci-job, adding gcc/cmake/CUDA,
  enabling cache=True, or setting experimental_options vm_runtime. Not for
  generic Modal Image tutorials or webhook Function sizing.
---

# Customizing runner-modal Job images

Webhook `Job.create` loads the published Named Image `{name}-job`.
`Runner.create(image=)` is the **webhook Function** image
(`control_plane_image()`), not the Job image.

Recipes: [references/image-recipes.md](references/image-recipes.md).
Deploy first: `runner-modal-deploy`. Workflows: `runner-modal-workflows`.

Worked example: [Nordlys `runners/core_app.py`](https://github.com/Nordlys-Labs/nordlys/blob/main/runners/core_app.py)
(Ubuntu 24.04 + gcc 13, publish over `ci_core-job`, `cache=True`).

## Choose a path

| Need | Do |
|------|-----|
| Default CPU CI | `Runner.create` only. Publishes `{name}-job` from `default_image()` (Debian slim + Actions runner) |
| CUDA / ML | Separate pool. `gpu="T4"` (or other) on `Runner.create`. Default Job image is enough if CUDA comes from pip wheels |
| Docker-in-CI | `experimental_options={"vm_runtime": True}` — **no GPU**. Library publishes `docker_image()` |
| Different distro / gcc / cmake | Rebuild with `install_actions_runner`, then publish over `{name}-job` **after** `Runner.create` (last publish wins) |
| Shared compile cache | `cache=True` → Volume at `/cache`, same-pool only |

Do not invent `ResourceSpec` / `DockerResources`. Flat kwargs: `cpu`,
`memory`, `gpu`, `experimental_options`. Modal enforces GPU vs VM limits.

## Default publish

`Runner.create` builds `default_image()` (or `docker_image()` when
`vm_runtime`) and publishes it as `{name}-job`. Webhook Jobs use
`Image.from_name`. Every deploy republishes the default recipe first.

## Custom Job image

Mirror the library recipe, then overwrite the Named Image. `add_local_python_source("runner_modal", copy=True)` is required until PyPI.

```python
import modal
from runner_modal import Runner
from runner_modal.meta import JOB_DEPS

APP_NAME = "myorg-ci-core"
RUNNER_NAME = "ci_core"

app = modal.App(APP_NAME)
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

core_job_image = Runner.install_actions_runner(
    modal.Image.from_registry("ubuntu:24.04", add_python="3.12")
    .apt_install(
        "curl", "ca-certificates", "git", "libicu-dev",
        "liblttng-ust1t64", "libssl3t64", "tar", "unzip", "zip",
        "build-essential", "gcc-13", "g++-13", "ninja-build", "pkg-config",
    )
    .uv_pip_install(*JOB_DEPS)
    .uv_pip_install("cmake>=3.28", "conan>=2")
    .add_local_python_source("runner_modal", copy=True)
    .env({"RUNNER_ALLOW_RUNASROOT": "1", "CC": "gcc-13", "CXX": "g++-13"})
)

Runner.create(
    app=app,
    name=RUNNER_NAME,
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    labels=["self-hosted", "modal", "ci-core"],
    cpu=4.0,
    memory=8192,
    cache=True,
    min_containers=0,
    idle_timeout=900,
)

build_app = modal.App.lookup(APP_NAME, create_if_missing=True)
core_job_image.build(build_app).publish(f"{RUNNER_NAME}-job")
```

Order: `Runner.create` (publishes stock `{name}-job`) → custom
`.publish(f"{name}-job")`. Last publish wins. Redeploy both steps.

No `Path` / `add_local_dir`. Use uv Image methods.

## GPU pool

Separate App. Host driver comes from Modal; CUDA userspace from wheels is
fine on the default Job image.

```python
Runner.create(
    app=app,
    name="ci_gpu",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    labels=["self-hosted", "modal", "ci-gpu"],
    gpu="T4",
    cpu=4.0,
    memory=16384,
    max_concurrent=2,
    min_containers=0,
    idle_timeout=900,
)
```

See `examples/gpu/app.py`.

## Docker-in-CI

```python
Runner.create(
    …,
    experimental_options={"vm_runtime": True},
    # no gpu=
)
```

## `/cache`

`cache=True` creates `{name}-cache` and mounts it at `/cache` for every Job
in that pool. Same-pool Jobs can read/write each other’s files. Default is
`cache=False`. This is not GitHub `actions/cache`.

Workflows must point tools at `/cache` (`runner-modal-workflows`).
