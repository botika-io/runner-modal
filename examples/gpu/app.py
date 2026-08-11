"""GPU CI pool — one Runner = one resource profile.

  modal deploy examples/gpu/app.py

Webhook: {Runner.from_name("gpu").url}/github
Copy examples/gpu/workflow.yml into your repo.
``gpu=`` on Runner.create sets Job Sandbox defaults (not the webhook Function).
"""

from __future__ import annotations

import modal

from runner_modal import Runner

app = modal.App("runner-modal-gpu")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="gpu",
    github_secret=github,
    webhook_secret=webhook,
    repositories=["YOUR_ORG/YOUR_REPO"],
    region="us-east",
    labels=["self-hosted", "modal", "gpu"],
    gpu="T4",
    cpu=4.0,
    memory=16384,
    max_concurrent=8,
    min_containers=0,
    idle_timeout=900,
)
