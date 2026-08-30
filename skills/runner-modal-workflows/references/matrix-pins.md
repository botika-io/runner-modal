# runner-modal matrix pins

`${{ strategy.job-index }}` cannot be used inside `matrix.include` values.
Every Modal leg needs a unique trailing pin.

## Single job

```yaml
runs-on:
  - self-hosted
  - modal
  - ci
  - job-${{ github.run_id }}-${{ github.job }}
```

## CPU matrix (literal suffixes)

Pool labels: `self-hosted`, `modal`, `ci`.

```yaml
strategy:
  fail-fast: true
  matrix:
    include:
      - { os: linux, python: "3.11", runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}-py311"] }
      - { os: linux, python: "3.12", runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}-py312"] }
      - { os: linux, python: "3.13", runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}-py313"] }
      - { os: macos, python: "3.12", runner: macos-latest }
      - { os: windows, python: "3.12", runner: windows-latest }

jobs:
  test:
    runs-on: ${{ matrix.runner }}
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync && uv run pytest
```

## GPU leg (separate pool)

Pool labels: `self-hosted`, `modal`, `gpu` (or `ci-gpu`). Requires a
dedicated `Runner.create(gpu=…)` App.

```yaml
- { os: linux-gpu, python: "3.12", runner: [self-hosted, modal, gpu, "job-${{ github.run_id }}-${{ github.job }}-gpu"] }
```

## Custom-image / cache pool

Pool labels: `self-hosted`, `modal`, `ci-core`. `cache=True` → `/cache`.

```yaml
- { os: linux, runner: [self-hosted, modal, ci-core, "job-${{ github.run_id }}-${{ github.job }}-linux"], conan_home: /cache/conan2 }
- { os: macos, runner: macos-15 }
```

Two jobs in one workflow that share a pool still need distinct pins
(`-${{ github.job }}` already differs per job id; add a literal if the
same `github.job` appears twice via matrix).

## Wrong

```yaml
# strategy.job-index is empty / invalid inside matrix values
- runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}-${{ strategy.job-index }}"]

# two matrix legs, same pin → one JIT runner, the other queues forever
- runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}"]
- runner: [self-hosted, modal, ci, "job-${{ github.run_id }}-${{ github.job }}"]
```
