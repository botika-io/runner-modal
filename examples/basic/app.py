"""Minimal CPU CI pool — copy and deploy.

  modal secret create github-token GITHUB_TOKEN=ghp_xxx
  modal secret create github-webhook WEBHOOK_SECRET=$(openssl rand -hex 32)
  modal deploy examples/basic/app.py

Webhook: {Runner.from_name("ci").url}/github
Copy examples/basic/workflow.yml into your repo.
"""

from __future__ import annotations

import modal

from runner_modal import Runner

app = modal.App("runner-modal-basic")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="ci",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    compute_region="us-east",
    labels=["self-hosted", "modal", "ci"],
    cpu=2.0,
    memory=4096,
    max_concurrent=20,
    min_containers=0,
    idle_timeout=900,
)
