"""Tests for runner_modal.meta — persisted Runner state and install pins."""

from __future__ import annotations

from runner_modal.meta import (
    DEFAULT_RUNNER_SHA256,
    DEFAULT_RUNNER_VERSION,
    PACKAGE_SPEC,
    PACKAGE_VERSION,
    RunnerInfo,
    RunnerMeta,
)


def test_package_spec_pins_git_main_until_release() -> None:
    assert PACKAGE_VERSION == "0.1.0"
    assert PACKAGE_SPEC.endswith("@main")
    assert "runner-modal.git" in PACKAGE_SPEC


def test_actions_runner_pin_has_checksum() -> None:
    assert DEFAULT_RUNNER_VERSION
    assert len(DEFAULT_RUNNER_SHA256) == 64


def test_runner_meta_stores_job_resource_defaults() -> None:
    meta = RunnerMeta(
        name="ci",
        labels=["self-hosted", "modal"],
        repositories=["acme/api"],
        cpu=2.0,
        memory=4096,
        gpu="T4",
    )
    assert meta.cpu == 2.0
    assert meta.memory == 4096
    assert meta.gpu == "T4"
    assert meta.cache is False


def test_runner_meta_is_frozen() -> None:
    meta = RunnerMeta(name="ci")
    try:
        meta.name = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("RunnerMeta should be frozen")


def test_runner_info_snapshot_fields() -> None:
    info = RunnerInfo(
        name="ci",
        labels=["modal"],
        repositories=["acme/api"],
        max_concurrent=10,
        cache=False,
        active_runners=1,
        app_name="app",
        webhook_function="webhook",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
        job_image_name="ci-job",
    )
    assert info.github_secret_name == "github-token"
    assert info.webhook_secret_name == "github-webhook"
    assert "secret_name" not in RunnerInfo.model_fields
