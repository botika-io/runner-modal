"""GitHub Actions runners on Modal — Runner.create + deploy.

Setup (two Secrets — never co-mount WEBHOOK_SECRET into Jobs):

  modal secret create github-token GITHUB_TOKEN=ghp_xxx
  modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)

  # from the repo root (uv project — builds/publishes named job image):
  modal deploy examples/github_webhook.py

Webhook: ``{runner.url}/github``
runs-on: [self-hosted, modal, acme, \"job-${{ github.run_id }}-${{ github.job }}\"]
"""

from __future__ import annotations

import modal

from runner_modal import Runner

REPO = "modal-projects/runner-modal"

app = modal.App("acme-ci")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

runner = Runner.create(
    app=app,
    name="acme",
    github_secret=github,
    webhook_secret=webhook,
    repositories=[REPO],
    compute_region="us-east",
    labels=["self-hosted", "modal", "acme"],
    max_concurrent=20,
    idle_timeout=900,
)
