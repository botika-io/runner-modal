---
name: runner-modal-workflows
description: >-
  Writes GitHub Actions workflows for runner-modal pools. Use when setting
  runs-on labels, unique job pins, or matrix legs on self-hosted Modal
  runners. Not for ubuntu-latest-only workflows.
---

# Writing runner-modal workflows

`runs-on` must admit: repo in allowlist, pool labels ⊆ job labels,
`self-hosted` present. Kit: `examples/basic/workflow.yml`.

## Rules

- Match `Runner.create(labels=…)`. Always include `self-hosted`.
- Unique pin: `job-${{ github.run_id }}-${{ github.job }}`.
- Matrix legs that share a pool need a **literal** suffix
  (`-py311`). `${{ strategy.job-index }}` is unavailable inside matrix values.
- Modal Jobs are Linux x86_64. Keep other OSes on hosted runners.
- `cache=True` is a pool Volume at `/cache`, not `actions/cache`.
- Fork PR code on a self-hosted Job can read `GITHUB_TOKEN`. See `SECURITY.md`.

```yaml
jobs:
  test:
    runs-on:
      - self-hosted
      - modal
      - ci
      - job-${{ github.run_id }}-${{ github.job }}
```
