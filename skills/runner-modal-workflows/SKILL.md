---
name: runner-modal-workflows
description: >-
  Writes GitHub Actions workflows that target runner-modal Modal runner
  pools. Use when setting runs-on labels, unique job pins, matrix legs on
  self-hosted Modal runners, or splitting Linux Modal jobs from
  macOS/Windows/cibuildwheel hosted runners. Not for ubuntu-latest-only
  workflows or generic Actions YAML.
---

# Writing runner-modal workflows

`runs-on` must admit against a deployed pool (`runner-modal-deploy`).
Admission: repo allowlist + pool labels ⊆ job labels + `self-hosted` present.

Copy-ready matrix snippets: [references/matrix-pins.md](references/matrix-pins.md).
Kits: `examples/basic/workflow.yml`, `examples/gpu/workflow.yml`.
Worked example: [nordlys-test.yml](https://github.com/Nordlys-Labs/nordlys/blob/main/.github/workflows/nordlys-test.yml).

## Rules

1. **Superset labels.** `runs-on` must include every label from
   `Runner.create(labels=…)`. Always include `self-hosted`.
2. **Unique pin.** Every Modal job needs
   `job-${{ github.run_id }}-${{ github.job }}` so one JIT runner is claimed
   by exactly one job.
3. **Literal matrix suffixes.** `${{ strategy.job-index }}` is **not**
   available inside matrix values. Disambiguate legs with literals
   (`-py311`, `-gpu`, `-linux`).
4. **Linux x86_64 only.** Modal Jobs are Linux. Keep macOS, Windows,
   cibuildwheel, and OIDC/PyPI publish on hosted runners.
5. **`/cache` ≠ `actions/cache`.** `cache=True` mounts a pool Volume at
   `/cache`. Skip `actions/cache` when `runner.environment != 'github-hosted'`.
6. **Python on Debian.** `actions/setup-python` often has no builds for the
   default Debian job image. Prefer `astral-sh/setup-uv` or bake Python into
   the Named Image (`runner-modal-images`).

## Minimal job

Labels must match the pool. Keep the pin.

```yaml
jobs:
  test:
    runs-on:
      - self-hosted
      - modal
      - ci
      - job-${{ github.run_id }}-${{ github.job }}
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v7
      - run: uv sync && uv run pytest
```

## Hosted vs Modal

| Work | Runner |
|------|--------|
| Linux unit/lint/build | Modal pool |
| CUDA / GPU tests | Separate `gpu` / `ci-gpu` pool |
| C++ / custom toolchain | Separate pool + custom `{name}-job` image |
| macOS / Windows | Hosted |
| cibuildwheel (nested Docker) | Hosted, unless `vm_runtime` pool |
| Publish with OIDC / PyPI | Hosted |

## Cache on Modal

When the pool has `cache=True`, point the tool at `/cache` and skip
`actions/cache` on self-hosted:

```yaml
- { os: linux, runner: [self-hosted, modal, ci-core, "job-${{ github.run_id }}-${{ github.job }}-linux"], conan_home: /cache/conan2 }
- { os: macos, runner: macos-15 }

# steps:
- name: Point Conan at the pool Volume
  if: matrix.conan_home
  run: echo "CONAN_HOME=${{ matrix.conan_home }}" >> "$GITHUB_ENV"
- name: Cache Conan packages
  if: runner.environment == 'github-hosted'
  uses: actions/cache@v4
  with:
    path: ~/.conan2
    key: conan-${{ runner.os }}-${{ hashFiles('conanfile.py') }}
```

## Fork PRs

Self-hosted Jobs execute workflow steps with `GITHUB_TOKEN` in the Sandbox.
On a public repo: require approval for outside collaborators; read-only
default workflow permissions. See `SECURITY.md`.

## Compose

- Pool not deployed / webhook missing → `runner-modal-deploy`
- Custom image, GPU, Docker-in-CI, `/cache` → `runner-modal-images`
- 401 / 204 / 503 / queued forever → `runner-modal-troubleshoot`
