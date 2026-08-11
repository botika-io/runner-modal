"""Maintainer CI control plane for modal-projects/runner-modal.

Not a consumer template — copy examples/basic/ or examples/gpu/ instead.

  modal deploy scripts/ci_app.py
"""

from __future__ import annotations

import modal

from runner_modal import Runner

REPO = "modal-projects/runner-modal"

app = modal.App("runner-modal-ci-app")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])
webhook = modal.Secret.from_name("github-webhook", required_keys=["WEBHOOK_SECRET"])

Runner.create(
    app=app,
    name="ci",
    github_secret=github,
    webhook_secret=webhook,
    repositories=[REPO],
    region="us-east",
    labels=["self-hosted", "modal", "ci"],
    cpu=2.0,
    memory=4096,
    max_concurrent=20,
    min_containers=0,
    idle_timeout=900,
)
