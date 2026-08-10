"""Imperative Runner.Job.create — one job Sandbox without the webhook.

JIT mint runs inside the Sandbox using ``GITHUB_TOKEN`` from an explicit Secret.

  modal secret create github-token GITHUB_TOKEN=ghp_...

Run (from repo root):
  modal run examples/imperative_create.py
"""

from __future__ import annotations

import time

import modal

from runner_modal import Runner

REPO = "modal-projects/runner-modal"

app = modal.App("runner-modal-example")
github = modal.Secret.from_name("github-token", required_keys=["GITHUB_TOKEN"])

Runner.objects.create(
    "demo",
    allow_existing=True,
    labels=["modal", "demo"],
    repositories=[REPO],
    max_concurrent=5,
)


@app.local_entrypoint()
def main(repository: str = REPO) -> None:
    parent = modal.App.lookup("runner-modal-example", create_if_missing=True)
    runner = Runner.from_name("demo")

    unique = f"manual-{int(time.time())}"
    job = Runner.Job.create(
        runner,
        app=parent,
        repository=repository,
        labels=["modal", "demo", unique],
        github_secret=github,
        cpu=2.0,
        region="us-east",
        timeout=30 * 60,
        name=unique,
    )
    print(f"spawned job object_id={job.object_id}")
    code = job.wait(timeout=30 * 60)
    print(f"exit code={code}")
