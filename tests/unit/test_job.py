"""Tests for runner_modal.job — Sandbox entrypoint behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runner_modal.exceptions import AuthError
from runner_modal.job import ACTIONS_RUNNER, JOB_SPEC_ENV, JobSpec


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
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match=JOB_SPEC_ENV):
        JobSpec.main()


def test_main_requires_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = JobSpec(repository="a/b", labels=["m"], runner_name="r")
    monkeypatch.setenv(JOB_SPEC_ENV, spec.model_dump_json())
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(AuthError, match="GITHUB_TOKEN"):
        JobSpec.main()


def test_start_execs_actions_runner_with_jit() -> None:
    spec = JobSpec(repository="a/b", labels=["modal"], runner_name="r1")
    with (
        patch.object(JobSpec, "mint_jitconfig", return_value="JIT") as mint,
        patch("runner_modal.job.os.execv") as execv,
    ):
        spec.start(token="t")
        mint.assert_called_once_with(token="t")
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
        patch("runner_modal.job.os.execv"),
    ):
        spec.start(token="t")
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
    resp.json.return_value = {"encoded_jit_config": "ENC"}
    with patch("runner_modal.job.httpx.post", return_value=resp) as post:
        assert spec.mint_jitconfig(token="tok") == "ENC"
        url = post.call_args.args[0]
        assert url.endswith("/repos/acme/api/actions/runners/generate-jitconfig")
        assert post.call_args.kwargs["json"]["labels"] == ["modal"]


def test_mint_maps_401_to_auth_error() -> None:
    spec = JobSpec(repository="a/b", labels=["m"], runner_name="r")
    resp = MagicMock()
    resp.status_code = 401
    with (
        patch("runner_modal.job.httpx.post", return_value=resp),
        pytest.raises(AuthError, match="401"),
    ):
        spec.mint_jitconfig(token="tok")
