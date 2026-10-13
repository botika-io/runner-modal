"""Tests for runner_modal.entrypoint — Sandbox entrypoint behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runner_modal.entrypoint import (
    ACTIONS_RUNNER,
    JIT_CONFIG_ENV,
    JOB_SPEC_ENV,
    JobSpec,
)
from runner_modal.exceptions import AuthError


def test_job_spec_roundtrips_json() -> None:
    spec = JobSpec(
        repository="a/b",
        labels=["modal"],
        runner_group_id=2,
        runner_name="r1",
        use_docker=True,
    )
    assert JobSpec.model_validate_json(spec.model_dump_json()).use_docker is True


def test_main_requires_job_spec_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JOB_SPEC_ENV, raising=False)
    monkeypatch.delenv(JIT_CONFIG_ENV, raising=False)
    with pytest.raises(RuntimeError, match=JOB_SPEC_ENV):
        JobSpec.main()


def test_main_requires_jit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = JobSpec(repository="a/b", labels=["m"], runner_name="r")
    monkeypatch.setenv(JOB_SPEC_ENV, spec.model_dump_json())
    monkeypatch.delenv(JIT_CONFIG_ENV, raising=False)
    with pytest.raises(AuthError, match=JIT_CONFIG_ENV):
        JobSpec.main()


def test_start_execs_actions_runner_with_jit() -> None:
    spec = JobSpec(repository="a/b", labels=["modal"], runner_name="r1")
    with (
        patch.object(JobSpec, "mint_jitconfig", return_value="JIT") as mint,
        patch("runner_modal.entrypoint.os.execv") as execv,
    ):
        spec.start(jit_config="JIT")
        mint.assert_not_called()
        execv.assert_called_once_with(
            ACTIONS_RUNNER, [ACTIONS_RUNNER, "--jitconfig", "JIT"]
        )


def test_start_boots_docker_when_vm_runtime_requested() -> None:
    spec = JobSpec(
        repository="a/b", labels=["modal"], runner_name="r1", use_docker=True
    )
    with (
        patch.object(JobSpec, "boot_docker") as boot,
        patch.object(JobSpec, "mint_jitconfig", return_value="JIT"),
        patch("runner_modal.entrypoint.os.execv"),
    ):
        spec.start(jit_config="JIT")
        boot.assert_called_once()


def test_mint_rejects_bad_inputs() -> None:
    with pytest.raises(AuthError, match="token is required"):
        JobSpec(repository="a/b", labels=["m"], runner_name="r").mint_jitconfig(
            token=""
        )
    with pytest.raises(ValueError, match="labels must be non-empty"):
        JobSpec(repository="a/b", labels=[], runner_name="r").mint_jitconfig(token="t")
    with pytest.raises(ValueError, match="owner/repo"):
        JobSpec(repository="bad", labels=["m"], runner_name="r").mint_jitconfig(
            token="t"
        )


def test_mint_returns_encoded_jit_from_github() -> None:
    spec = JobSpec(repository="acme/api", labels=["modal"], runner_name="r1")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"runner": {"id": 123}, "encoded_jit_config": "ENC"}
    with patch("runner_modal.entrypoint.httpx.post", return_value=resp) as post:
        registration = spec.mint_jitconfig(token="tok")
        assert registration.encoded_jit_config == "ENC"
        assert registration.runner.id == 123
        url = post.call_args.args[0]
        assert url.endswith("/repos/acme/api/actions/runners/generate-jitconfig")
        assert post.call_args.kwargs["json"]["labels"] == ["modal"]


def test_mint_maps_401_to_auth_error() -> None:
    spec = JobSpec(repository="a/b", labels=["m"], runner_name="r")
    resp = MagicMock()
    resp.status_code = 401
    with (
        patch("runner_modal.entrypoint.httpx.post", return_value=resp),
        pytest.raises(AuthError, match="401"),
    ):
        spec.mint_jitconfig(token="tok")


def test_main_removes_jit_before_docker_and_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    spec = JobSpec(
        repository="a/b", labels=["modal"], runner_name="r1", use_docker=True
    )
    monkeypatch.setenv(JOB_SPEC_ENV, spec.model_dump_json())
    monkeypatch.setenv(JIT_CONFIG_ENV, "one-job-jit")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def check_environment(*args: object) -> None:
        assert JIT_CONFIG_ENV not in os.environ
        assert "GITHUB_TOKEN" not in os.environ

    with (
        patch.object(JobSpec, "boot_docker", side_effect=check_environment) as boot,
        patch("runner_modal.entrypoint.os.execv", side_effect=check_environment) as run,
        patch.object(JobSpec, "mint_jitconfig") as mint,
    ):
        JobSpec.main()
        boot.assert_called_once()
        run.assert_called_once_with(
            ACTIONS_RUNNER, [ACTIONS_RUNNER, "--jitconfig", "one-job-jit"]
        )
        mint.assert_not_called()
