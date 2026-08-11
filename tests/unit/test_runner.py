"""Tests for runner_modal.runner — Runner / Job observable behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import runner_modal
from runner_modal import Runner
from runner_modal.entrypoint import JOB_SPEC_ENV, JobSpec
from runner_modal.exceptions import ConcurrencyLimitError
from runner_modal.meta import JOB_KIND, JOB_MODULE, KIND_TAG, POOL_TAG

POOL = ["self-hosted", "modal"]
REPO = "a/b"


def test_public_surface_is_runner_and_errors_only() -> None:
    assert set(runner_modal.__all__) >= {
        "Runner",
        "AuthError",
        "ConcurrencyLimitError",
        "JobTimeoutError",
        "RunnerError",
        "RunnerInfo",
        "__version__",
    }
    for name in (
        "spawn",
        "parse_labels",
        "WebhookApp",
        "DeliveryStore",
        "JobSpec",
        "DeliveryRecord",
    ):
        assert name not in runner_modal.__all__
        assert name not in vars(runner_modal)


def test_job_create_raises_when_at_soft_capacity() -> None:
    runner = Runner.from_name(
        "full",
        create_if_missing=True,
        max_concurrent=1,
        labels=POOL,
        repositories=[REPO],
    )
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=False),
        pytest.raises(ConcurrencyLimitError, match="max_concurrent"),
    ):
        Runner.Job.create(
            runner, repository=REPO, labels=POOL, github_secret=MagicMock()
        )


def test_job_create_rejects_when_not_admitted() -> None:
    runner = Runner.from_name(
        "p",
        create_if_missing=True,
        labels=POOL,
        repositories=[REPO],
    )
    with (
        patch.object(runner, "hydrate"),
        pytest.raises(ValueError, match="repository_mismatch"),
    ):
        Runner.Job.create(
            runner,
            repository="other/repo",
            labels=POOL,
            github_secret=MagicMock(),
        )


def test_has_capacity_is_soft_list_then_create() -> None:
    runner = Runner.from_name("cap", create_if_missing=True, max_concurrent=2)
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "active_count", return_value=2),
    ):
        assert runner.has_capacity() is False
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "active_count", return_value=1),
    ):
        assert runner.has_capacity() is True
    runner_unlimited = Runner.from_name("u", create_if_missing=True)
    with patch.object(runner_unlimited, "hydrate"):
        assert runner_unlimited.has_capacity() is True


def test_url_none_when_undeployed() -> None:
    runner = Runner.from_name("u")
    with patch.object(runner, "hydrate"):
        assert runner.url is None


def test_job_create_passes_github_secret_and_job_spec() -> None:
    fake_sb = MagicMock()
    fake_sb.object_id = "sb-test"
    runner = Runner.from_name(
        "p", create_if_missing=True, labels=POOL, repositories=[REPO]
    )
    runner.meta = runner.meta.model_copy(update={"job_image_name": "p-job"})
    gh = MagicMock()

    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=True),
        patch(
            "runner_modal.runner.modal.Sandbox.create", return_value=fake_sb
        ) as create,
        patch("runner_modal.runner.modal.Image.from_name", return_value=MagicMock()),
    ):
        job = Runner.Job.create(
            runner,
            repository=REPO,
            labels=["job-1"],
            github_secret=gh,
            cpu=2.0,
        )
        assert job.object_id == "sb-test"
        assert create.call_args.args[:3] == ("python", "-m", JOB_MODULE)
        kwargs = create.call_args.kwargs
        assert kwargs["secrets"][0] is gh
        assert "MODAL_RUNNER_JIT" not in (kwargs.get("env") or {})
        spec = JobSpec.model_validate_json(kwargs["env"][JOB_SPEC_ENV])
        assert spec.repository == REPO
        assert "modal" in spec.labels and "job-1" in spec.labels
        assert kwargs["tags"][KIND_TAG] == JOB_KIND
        assert kwargs["tags"][POOL_TAG] == "p"
        assert kwargs["cpu"] == 2.0


def test_job_create_uses_meta_resource_defaults_when_omitted() -> None:
    fake_sb = MagicMock()
    fake_sb.object_id = "sb-gpu"
    runner = Runner.from_name(
        "p", create_if_missing=True, labels=POOL, repositories=[REPO]
    )
    runner.meta = runner.meta.model_copy(
        update={"job_image_name": "p-job", "gpu": "T4", "cpu": 4.0, "memory": 8192}
    )
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=True),
        patch(
            "runner_modal.runner.modal.Sandbox.create", return_value=fake_sb
        ) as create,
        patch("runner_modal.runner.modal.Image.from_name", return_value=MagicMock()),
    ):
        Runner.Job.create(
            runner, repository=REPO, labels=["job-1"], github_secret=MagicMock()
        )
        assert create.call_args.kwargs["gpu"] == "T4"
        assert create.call_args.kwargs["cpu"] == 4.0
        assert create.call_args.kwargs["memory"] == 8192


def test_job_create_explicit_gpu_overrides_meta_default() -> None:
    fake_sb = MagicMock()
    fake_sb.object_id = "sb-a100"
    runner = Runner.from_name(
        "p", create_if_missing=True, labels=POOL, repositories=[REPO]
    )
    runner.meta = runner.meta.model_copy(
        update={"job_image_name": "p-job", "gpu": "T4"}
    )
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=True),
        patch(
            "runner_modal.runner.modal.Sandbox.create", return_value=fake_sb
        ) as create,
        patch("runner_modal.runner.modal.Image.from_name", return_value=MagicMock()),
    ):
        Runner.Job.create(
            runner,
            repository=REPO,
            labels=["job-1"],
            github_secret=MagicMock(),
            gpu="A100",
        )
        assert create.call_args.kwargs["gpu"] == "A100"


def test_job_create_without_named_image_builds_default() -> None:
    fake_sb = MagicMock()
    fake_sb.object_id = "sb-local"
    runner = Runner.from_name(
        "p", create_if_missing=True, labels=POOL, repositories=[REPO]
    )
    assert runner.meta.job_image_name is None
    recipe = MagicMock()
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=True),
        patch("runner_modal.runner.modal.Sandbox.create", return_value=fake_sb),
        patch.object(Runner, "default_image", return_value=recipe) as default_image,
    ):
        Runner.Job.create(
            runner, repository=REPO, labels=["job-1"], github_secret=MagicMock()
        )
        default_image.assert_called_once()


def test_runner_create_publishes_job_image_and_mounts_webhook_secret_only() -> None:
    app = MagicMock()
    app.name = "acme-ci"
    github = MagicMock()
    github.name = "github-token"
    webhook = MagicMock()
    webhook.name = "github-webhook"
    recipe = MagicMock()
    built = MagicMock()
    recipe.build.return_value = built
    runner_handle = Runner.from_name("acme", create_if_missing=True)

    with (
        patch.object(Runner, "from_name", return_value=runner_handle),
        patch.object(runner_handle, "hydrate"),
        patch.object(runner_handle, "persist_meta") as persist,
        patch.object(Runner, "default_image", return_value=recipe),
        patch.object(Runner, "control_plane_image", return_value=MagicMock()),
        patch("runner_modal.runner.modal.App.lookup", return_value=MagicMock()),
        patch(
            "runner_modal.runner.modal.concurrent",
            side_effect=lambda **kw: lambda f: f,
        ),
        patch(
            "runner_modal.runner.modal.asgi_app",
            side_effect=lambda **kw: lambda f: f,
        ),
        patch.object(app, "function", return_value=lambda f: f) as register,
    ):
        out = Runner.create(
            app=app,
            name="acme",
            github_secret=github,
            webhook_secret=webhook,
            repositories=["acme/api"],
            labels=["self-hosted", "modal", "acme"],
            cpu=2.0,
            gpu="T4",
        )
        assert out is runner_handle
        built.publish.assert_called_once_with(
            "acme-job", environment_name=None, client=None
        )
        assert runner_handle.meta.job_image_name == "acme-job"
        assert runner_handle.meta.github_secret_name == "github-token"
        assert runner_handle.meta.webhook_secret_name == "github-webhook"
        assert runner_handle.meta.webhook_function == "webhook"
        assert runner_handle.meta.repositories == ["acme/api"]
        assert runner_handle.meta.cpu == 2.0
        assert runner_handle.meta.gpu == "T4"
        persist.assert_called_once()
        assert register.call_args.kwargs["secrets"] == [webhook]
        assert register.call_args.kwargs["name"] == "webhook"
        assert "gpu" not in register.call_args.kwargs
        assert "cpu" not in register.call_args.kwargs
        assert register.call_args.kwargs["min_containers"] == 0
        assert register.call_args.kwargs["buffer_containers"] == 1


def test_runner_create_rejects_empty_labels_and_repositories() -> None:
    app = MagicMock()
    app.name = "acme-ci"
    github = MagicMock()
    github.name = "g"
    webhook = MagicMock()
    webhook.name = "w"
    with pytest.raises(ValueError, match="repositories"):
        Runner.create(
            app=app,
            name="acme",
            github_secret=github,
            webhook_secret=webhook,
            repositories=[],
            labels=["modal"],
        )
    with pytest.raises(ValueError, match="labels"):
        Runner.create(
            app=app,
            name="acme",
            github_secret=github,
            webhook_secret=webhook,
            repositories=["acme/api"],
            labels=[],
        )


def test_objects_create_rejects_empty_labels_and_repositories() -> None:
    with pytest.raises(ValueError, match="labels"):
        Runner.objects.create("x", labels=[], repositories=[REPO])
    with pytest.raises(ValueError, match="repositories"):
        Runner.objects.create("x", labels=POOL, repositories=[])
    with pytest.raises(ValueError, match="owner/repo"):
        Runner.objects.create("x", labels=POOL, repositories=["bad"])


def test_objects_delete_removes_deliveries_dict() -> None:
    dict_objects = MagicMock()
    volume_objects = MagicMock()
    with (
        patch("runner_modal.runner.modal.Dict") as dict_cls,
        patch("runner_modal.runner.modal.Volume") as volume_cls,
    ):
        dict_cls.objects = dict_objects
        volume_cls.objects = volume_objects
        Runner.objects.delete("acme")
        names = [c.args[0] for c in dict_objects.delete.call_args_list]
        assert "acme-runner-meta" in names
        assert "acme-runner-deliveries" in names
        volume_objects.delete.assert_called_once()


def test_job_create_docker_sets_vm_runtime() -> None:
    fake_sb = MagicMock()
    fake_sb.object_id = "sb-d"
    runner = Runner.from_name(
        "d", create_if_missing=True, labels=POOL, repositories=[REPO]
    )
    with (
        patch.object(runner, "hydrate"),
        patch.object(runner, "has_capacity", return_value=True),
        patch(
            "runner_modal.runner.modal.Sandbox.create", return_value=fake_sb
        ) as create,
        patch.object(Runner, "docker_image", return_value=MagicMock()),
    ):
        Runner.Job.create(
            runner,
            repository=REPO,
            labels=["job-1"],
            github_secret=MagicMock(),
            experimental_options={"vm_runtime": True},
        )
        assert create.call_args.kwargs["experimental_options"]["vm_runtime"] is True
        spec = JobSpec.model_validate_json(create.call_args.kwargs["env"][JOB_SPEC_ENV])
        assert spec.use_docker is True


def test_job_wait_blocks_until_sandbox_finishes() -> None:
    sb = MagicMock()
    sb.object_id = "sb-w"
    sb.returncode = 0
    job = Runner.Job(sb)
    assert job.wait() == 0
    sb.wait.assert_called_once_with(raise_on_termination=False)


def test_admit_reason_requires_repo_pool_subset_and_self_hosted() -> None:
    runner = Runner.from_name(
        "p",
        create_if_missing=True,
        labels=["self-hosted", "modal"],
        repositories=["acme/api"],
    )
    with patch.object(runner, "hydrate"):
        runner.meta = runner.meta.model_copy(
            update={
                "labels": ["self-hosted", "modal"],
                "repositories": ["acme/api"],
            }
        )
        assert (
            runner.admit_reason(["self-hosted", "modal", "job-1"], "acme/api") is None
        )
        assert (
            runner.admit_reason(["modal", "job-1"], "acme/api") == "missing_self_hosted"
        )
        assert (
            runner.admit_reason(["self-hosted", "modal"], "other/repo")
            == "repository_mismatch"
        )
        assert (
            runner.admit_reason(["self-hosted", "ci"], "acme/api") == "label_mismatch"
        )
    runner.meta = runner.meta.model_copy(update={"labels": [], "repositories": []})
    with patch.object(runner, "hydrate"):
        assert runner.admit_reason(["self-hosted", "modal"], "acme/api") == (
            "no_repositories"
        )


def test_images_install_runtime_deps_and_local_package() -> None:
    with patch("runner_modal.runner.modal.Image") as image_cls:
        slim = MagicMock()
        image_cls.debian_slim.return_value = slim
        slim.apt_install.return_value = slim
        slim.uv_pip_install.return_value = slim
        slim.add_local_python_source.return_value = slim
        slim.env.return_value = slim
        with patch.object(
            Runner,
            "install_actions_runner",
            side_effect=lambda img, **kwargs: img,
        ):
            Runner.default_image()
        slim.uv_pip_install.assert_called()
        slim.add_local_python_source.assert_called_with("runner_modal", copy=True)
