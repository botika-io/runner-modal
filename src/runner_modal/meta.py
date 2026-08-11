"""Persisted Runner state and public info snapshot (not exported)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

META_KEY = "runner"
KIND_TAG = "runner_modal"
JOB_KIND = "runner"
POOL_TAG = "runner_pool"
DEFAULT_RUNNER_VERSION = "2.336.0"
JOB_MODULE = "runner_modal.job"
# Install path for Images until the package is on PyPI.
PACKAGE_GIT = "git+https://github.com/modal-projects/runner-modal.git"


class RunnerMeta(BaseModel):
    """Persisted Runner Dict payload."""

    model_config = ConfigDict(frozen=True)

    name: str
    labels: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    max_concurrent: int | None = None
    cache: bool = False
    app_name: str | None = None
    server_name: str | None = None
    github_secret_name: str | None = None
    webhook_secret_name: str | None = None
    job_image_name: str | None = None
    github_enterprise_domain: str | None = None
    region: str | list[str] | None = None
    idle_timeout: int | None = None
    experimental_options: dict[str, object] | None = None
    runner_group_id: int = 1


class RunnerInfo(BaseModel):
    """Snapshot from ``Runner.info()``."""

    model_config = ConfigDict(frozen=True)

    name: str
    labels: list[str]
    repositories: list[str]
    max_concurrent: int | None
    cache: bool
    active_runners: int
    app_name: str | None
    server_name: str | None
    github_secret_name: str | None
    webhook_secret_name: str | None
    job_image_name: str | None
