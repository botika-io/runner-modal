"""Persisted Runner state and public info snapshot (not exported)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

META_KEY = "runner"
KIND_TAG = "runner_modal"
JOB_KIND = "runner"
POOL_TAG = "runner_pool"
DEFAULT_RUNNER_VERSION = "2.336.0"
# Upstream actions-runner-linux-x64 tarball digest for DEFAULT_RUNNER_VERSION.
DEFAULT_RUNNER_SHA256 = (
    "04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d"
)
JOB_MODULE = "runner_modal.entrypoint"
WEBHOOK_FUNCTION = "webhook"
PACKAGE_VERSION = "0.1.0"
# Documented install pin for operators (`uv add …`). Image builds install
# runtime deps from PyPI and bake local ``runner_modal`` via
# ``add_local_python_source`` until a PyPI release.
PACKAGE_SPEC = "git+https://github.com/modal-projects/runner-modal.git@v0.1.0"
CONTROL_PLANE_DEPS = (
    "fastapi>=0.115.0",
    "httpx>=0.28.0",
    "modal>=1.5.2,<2",
    "pydantic>=2.0",
    "tenacity>=9.0.0",
)
JOB_DEPS = (
    "httpx>=0.28.0",
    "modal>=1.5.2,<2",
    "pydantic>=2.0",
    "tenacity>=9.0.0",
)


class RunnerMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    labels: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    max_concurrent: int | None = None
    cache: bool = False
    app_name: str | None = None
    webhook_function: str | None = None
    github_secret_name: str | None = None
    webhook_secret_name: str | None = None
    job_image_name: str | None = None
    github_enterprise_domain: str | None = None
    region: str | list[str] | None = None
    idle_timeout: int | None = None
    experimental_options: dict[str, object] | None = None
    runner_group_id: int = 1
    # Job Sandbox defaults for webhook create when Job.create omits resources.
    cpu: float | None = None
    memory: int | None = None
    gpu: str | None = None


class RunnerInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    labels: list[str]
    repositories: list[str]
    max_concurrent: int | None
    cache: bool
    active_runners: int
    app_name: str | None
    webhook_function: str | None
    github_secret_name: str | None
    webhook_secret_name: str | None
    job_image_name: str | None
