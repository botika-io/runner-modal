"""Runner — Modal-shaped CI control plane + Job Sandboxes."""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Collection, Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import ClassVar, Literal, Self

import modal

from runner_modal.entrypoint import JIT_CONFIG_ENV, JOB_SPEC_ENV, JobSpec
from runner_modal.exceptions import ConcurrencyLimitError
from runner_modal.meta import (
    CONTROL_PLANE_DEPS,
    DEFAULT_RUNNER_SHA256,
    DEFAULT_RUNNER_VERSION,
    JOB_DEPS,
    JOB_KIND,
    JOB_MODULE,
    KIND_TAG,
    META_KEY,
    POOL_TAG,
    WEBHOOK_FUNCTION,
    RunnerInfo,
    RunnerMeta,
)

RUNNER_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
WEBHOOK_TIMEOUT_SECONDS = 300
WEBHOOK_MAX_INPUTS = 64


class RunnerObjects:
    """Admin namespace (Modal ``Volume.objects`` shape)."""

    @staticmethod
    def create(
        name: str,
        *,
        allow_existing: bool = False,
        environment_name: str | None = None,
        labels: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        max_concurrent: int | None = None,
        cache: bool = False,
        client: modal.Client | None = None,
    ) -> None:
        if not RUNNER_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid Runner name {name!r}")
        if not labels:
            raise ValueError("labels must be a non-empty sequence")
        if not repositories:
            raise ValueError(
                "repositories must be a non-empty sequence of 'owner/repo'"
            )
        repos: list[str] = []
        for repo in repositories:
            if repo.count("/") != 1:
                raise ValueError(f"repository must be 'owner/repo', got {repo!r}")
            repos.append(repo)
        modal.Dict.objects.create(
            f"{name}-runner-meta",
            allow_existing=allow_existing,
            environment_name=environment_name,
            client=client,
        )
        if cache:
            modal.Volume.objects.create(
                f"{name}-cache",
                allow_existing=True,
                environment_name=environment_name,
                client=client,
            )
        Runner.from_name(
            name,
            create_if_missing=True,
            environment_name=environment_name,
            labels=list(labels),
            repositories=repos,
            max_concurrent=max_concurrent,
            cache=cache,
            client=client,
        ).hydrate()

    @staticmethod
    def delete(
        name: str,
        *,
        allow_missing: bool = True,
        environment_name: str | None = None,
        client: modal.Client | None = None,
    ) -> None:
        modal.Dict.objects.delete(
            f"{name}-runner-meta",
            allow_missing=allow_missing,
            environment_name=environment_name,
            client=client,
        )
        modal.Dict.objects.delete(
            f"{name}-runner-deliveries",
            allow_missing=True,
            environment_name=environment_name,
            client=client,
        )
        modal.Volume.objects.delete(
            f"{name}-cache",
            allow_missing=True,
            environment_name=environment_name,
            client=client,
        )

    @staticmethod
    def list(
        *,
        environment_name: str | None = None,
        client: modal.Client | None = None,
    ) -> Sequence[str]:
        suffix = "-runner-meta"
        names: list[str] = []
        for d in modal.Dict.objects.list(
            environment_name=environment_name or "",
            client=client,
        ):
            label = d.name or ""
            if label.endswith(suffix):
                names.append(label[: -len(suffix)])
        return sorted(names)


class Runner:
    """Named CI runner — Volume-shaped lookup + ASGI webhook registration.

    ``Runner.create(app, name, …)`` registers the control plane
    (definition-time). ``Runner.Job.create(runner, …)`` starts a job
    Sandbox (eager, like ``Sandbox.create``).
    """

    objects: ClassVar[RunnerObjects] = RunnerObjects()

    def __init__(
        self,
        name: str,
        *,
        environment_name: str | None = None,
        create_if_missing: bool = False,
        labels: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        max_concurrent: int | None = None,
        cache: bool = False,
        client: modal.Client | None = None,
    ) -> None:
        self.name = name
        self.environment_name = environment_name
        self.create_if_missing = create_if_missing
        self.client = client
        self.meta = RunnerMeta(
            name=name,
            labels=list(labels or []),
            repositories=list(repositories or []),
            max_concurrent=max_concurrent,
            cache=cache,
        )
        self.meta_dict: modal.Dict | None = None
        self.volume: modal.Volume | None = None
        self.hydrated = False

    class Job:
        def __init__(self, sandbox: modal.Sandbox) -> None:
            self.sandbox = sandbox

        @classmethod
        def from_id(
            cls, sandbox_id: str, *, client: modal.Client | None = None
        ) -> Runner.Job:
            return cls(modal.Sandbox.from_id(sandbox_id, client=client))

        @classmethod
        def from_name(
            cls,
            app_name: str,
            name: str,
            *,
            environment_name: str | None = None,
            client: modal.Client | None = None,
        ) -> Runner.Job:
            return cls(
                modal.Sandbox.from_name(
                    app_name,
                    name,
                    environment_name=environment_name,
                    client=client,
                )
            )

        @classmethod
        def list(
            cls,
            *,
            app_id: str | None = None,
            tags: dict[str, str] | None = None,
            client: modal.Client | None = None,
        ) -> Iterator[Runner.Job]:
            merged = {KIND_TAG: JOB_KIND, **(tags or {})}
            for sb in modal.Sandbox.list(app_id=app_id, tags=merged, client=client):
                yield cls(sb)

        @classmethod
        def create(
            cls,
            runner: Runner,
            *,
            repository: str,
            github_token: str,
            app: modal.App | None = None,
            labels: Sequence[str] | None = None,
            runner_group_id: int | None = None,
            runner_name: str | None = None,
            github_enterprise_domain: str | None = None,
            image: modal.Image | None = None,
            env: dict[str, str | None] | None = None,
            secrets: Collection[modal.Secret] | None = None,
            volumes: Mapping[
                str | os.PathLike[str], modal.Volume | modal.CloudBucketMount
            ]
            | None = None,
            timeout: int = 60 * 60,
            idle_timeout: int | None = None,
            workdir: str | None = None,
            cpu: float | tuple[float, float] | None = None,
            memory: int | tuple[int, int] | None = None,
            runtime: Literal["gvisor", "vm"] | None = None,
            gpu: str | None = None,
            cloud: str | None = None,
            region: str | Sequence[str] | None = None,
            block_network: bool = False,
            outbound_cidr_allowlist: Sequence[str] | None = None,
            inbound_cidr_allowlist: Sequence[str] | None = None,
            proxy: modal.Proxy | None = None,
            name: str | None = None,
            tags: dict[str, str] | None = None,
            experimental_options: dict[str, object] | None = None,
            environment_name: str | None = None,
            client: modal.Client | None = None,
        ) -> Runner.Job:
            """Create a job Sandbox (eager) — same role as ``modal.Sandbox.create``.

            Mint JIT in the trusted caller using ``github_token``. Only the
            single-use configuration is mounted into the job Sandbox.
            """
            if repository.count("/") != 1:
                raise ValueError(f"repository must be 'owner/repo', got {repository!r}")

            runner.hydrate()
            merged_labels = list(dict.fromkeys([*(labels or []), *runner.meta.labels]))
            reason = runner.admit_reason(merged_labels, repository)
            if reason is not None:
                raise ValueError(f"Job.create rejected: {reason}")
            if not runner.has_capacity():
                raise ConcurrencyLimitError(
                    f"Runner {runner.name!r} at max_concurrent="
                    f"{runner.meta.max_concurrent}"
                )

            group_id = (
                runner_group_id
                if runner_group_id is not None
                else runner.meta.runner_group_id
            )
            job_region = region if region is not None else runner.meta.region
            job_idle = (
                idle_timeout if idle_timeout is not None else runner.meta.idle_timeout
            )
            exp = dict(runner.meta.experimental_options or {})
            exp.update(experimental_options or {})
            domain = (
                github_enterprise_domain
                if github_enterprise_domain is not None
                else runner.meta.github_enterprise_domain
            )

            job_runtime = runtime if runtime is not None else runner.meta.runtime
            use_docker = job_runtime == "vm"
            if image is None:
                if runner.meta.job_image_name:
                    image = modal.Image.from_name(
                        runner.meta.job_image_name,
                        environment_name=environment_name or runner.environment_name,
                        client=client or runner.client,
                    )
                else:
                    image = (
                        Runner.docker_image() if use_docker else Runner.default_image()
                    )

            vol_map: dict[
                str | os.PathLike[str], modal.Volume | modal.CloudBucketMount
            ] = dict(volumes) if volumes else {}
            if runner.volume is not None and "/cache" not in {
                str(path) for path in vol_map
            }:
                vol_map["/cache"] = runner.volume

            merged_tags: dict[str, str] = {
                **(tags or {}),
                KIND_TAG: JOB_KIND,
                POOL_TAG: runner.name,
                "repository": repository.replace("/", "_"),
            }

            spec = JobSpec(
                repository=repository,
                labels=merged_labels,
                runner_group_id=group_id,
                runner_name=runner_name or f"{name or 'modal'}-{uuid.uuid4().hex}",
                github_enterprise_domain=domain,
                use_docker=use_docker,
            )
            registration = spec.mint_jitconfig(token=github_token)
            jit_secret = modal.Secret.from_dict(
                {JIT_CONFIG_ENV: registration.encoded_jit_config}
            )
            run_env = dict(env or {})
            run_env.setdefault("RUNNER_ALLOW_RUNASROOT", "1")
            run_env[JOB_SPEC_ENV] = spec.model_dump_json()

            job_cpu = cpu if cpu is not None else runner.meta.cpu
            job_memory = memory if memory is not None else runner.meta.memory
            job_gpu = gpu if gpu is not None else runner.meta.gpu

            try:
                sandbox = modal.Sandbox.create(
                    "python",
                    "-m",
                    JOB_MODULE,
                    app=app,
                    image=image,
                    env=run_env,
                    secrets=[jit_secret, *(secrets or [])],
                    volumes=vol_map,
                    timeout=timeout,
                    idle_timeout=job_idle,
                    workdir=workdir,
                    gpu=job_gpu,
                    cloud=cloud,
                    region=job_region,
                    cpu=job_cpu,
                    memory=job_memory,
                    runtime=job_runtime,
                    block_network=block_network,
                    outbound_cidr_allowlist=outbound_cidr_allowlist,
                    inbound_cidr_allowlist=inbound_cidr_allowlist,
                    proxy=proxy,
                    name=name,
                    tags=merged_tags,
                    experimental_options=exp or None,
                    client=client or runner.client,
                )
            except (
                modal.exception.AlreadyExistsError,
                modal.exception.InvalidError,
                modal.exception.AuthError,
                modal.exception.PermissionDeniedError,
                modal.exception.NotFoundError,
                modal.exception.ResourceExhaustedError,
            ):
                try:
                    spec.delete_registration(
                        token=github_token, runner_id=registration.runner.id
                    )
                except Exception:
                    logging.getLogger("runner_modal.runner").warning(
                        "registration cleanup failed repository=%s runner_id=%s",
                        repository,
                        registration.runner.id,
                    )
                raise
            return cls(sandbox)

        @property
        def object_id(self) -> str:
            return self.sandbox.object_id

        def terminate(self) -> None:
            self.sandbox.terminate()

        def wait(self) -> int | None:
            """Block until the Sandbox finishes (like ``Sandbox.wait``)."""
            self.sandbox.wait(raise_on_termination=False)
            return self.sandbox.returncode

        def poll(self) -> int | None:
            return self.sandbox.poll()

        def __repr__(self) -> str:
            return f"Runner.Job.from_id({self.object_id!r})"

    @classmethod
    def control_plane_image(cls) -> modal.Image:
        return (
            modal.Image.debian_slim(python_version="3.12")
            .uv_pip_install(*CONTROL_PLANE_DEPS)
            .add_local_python_source("runner_modal", copy=True)
        )

    @classmethod
    def install_actions_runner(
        cls,
        image: modal.Image,
        *,
        runner_version: str = DEFAULT_RUNNER_VERSION,
        runner_sha256: str = DEFAULT_RUNNER_SHA256,
    ) -> modal.Image:
        """Download Actions runner tarball and verify SHA-256 before extract."""
        return image.run_commands(
            f"curl -fsSL -o /tmp/actions-runner.tar.gz "
            f"https://github.com/actions/runner/releases/download/"
            f"v{runner_version}/actions-runner-linux-x64-{runner_version}.tar.gz",
            f"echo '{runner_sha256}  /tmp/actions-runner.tar.gz' | sha256sum -c -",
            "mkdir -p /actions-runner",
            "tar -xzf /tmp/actions-runner.tar.gz -C /actions-runner",
            "rm /tmp/actions-runner.tar.gz",
            "chmod +x /actions-runner/run.sh /actions-runner/config.sh",
        )

    @classmethod
    def default_image(
        cls, *, runner_version: str = DEFAULT_RUNNER_VERSION
    ) -> modal.Image:
        base = (
            modal.Image.debian_slim(python_version="3.12")
            .apt_install(
                "curl",
                "ca-certificates",
                "git",
                "libicu-dev",
                "liblttng-ust1",
                "libssl3",
                "tar",
                "unzip",
                "zip",
            )
            .uv_pip_install(*JOB_DEPS)
            .add_local_python_source("runner_modal", copy=True)
            .env({"RUNNER_ALLOW_RUNASROOT": "1"})
        )
        return cls.install_actions_runner(base, runner_version=runner_version)

    @classmethod
    def docker_image(
        cls, *, runner_version: str = DEFAULT_RUNNER_VERSION
    ) -> modal.Image:
        base = (
            modal.Image.from_registry("ubuntu:24.04", add_python="3.12")
            .env({"DEBIAN_FRONTEND": "noninteractive", "RUNNER_ALLOW_RUNASROOT": "1"})
            .apt_install(
                "curl",
                "ca-certificates",
                "git",
                "docker.io",
                "docker-buildx",
                "libicu-dev",
                "tar",
                "unzip",
                "zip",
            )
            .uv_pip_install(*JOB_DEPS)
            .add_local_python_source("runner_modal", copy=True)
        )
        return cls.install_actions_runner(base, runner_version=runner_version)

    @classmethod
    def create(
        cls,
        app: modal.App,
        name: str,
        *,
        github_secret: modal.Secret,
        webhook_secret: modal.Secret,
        repositories: Sequence[str],
        labels: Sequence[str] | None = None,
        max_concurrent: int | None = None,
        cache: bool = False,
        image: modal.Image | None = None,
        job_image: modal.Image | None = None,
        volumes: Mapping[str | PurePosixPath, modal.Volume | modal.CloudBucketMount]
        | None = None,
        env: dict[str, str | None] | None = None,
        region: str | Sequence[str] | None = None,
        cloud: str | None = None,
        min_containers: int = 0,
        max_containers: int | None = None,
        buffer_containers: int = 1,
        scaledown_window: int | None = None,
        timeout: int = WEBHOOK_TIMEOUT_SECONDS,
        startup_timeout: int | None = None,
        ephemeral_disk: int | None = None,
        proxy: modal.Proxy | None = None,
        environment_name: str | None = None,
        client: modal.Client | None = None,
        idle_timeout: int | None = None,
        experimental_options: dict[str, object] | None = None,
        runner_group_id: int | None = None,
        github_enterprise_domain: str | None = None,
        # Job Sandbox defaults (not control-plane sizing).
        gpu: str | None = None,
        cpu: float | tuple[float, float] | None = None,
        memory: int | tuple[int, int] | None = None,
        runtime: Literal["gvisor", "vm"] | None = None,
    ) -> Self:
        """Register ASGI webhook Function on ``app`` (definition-time).

        Call once per App. ``github_secret`` (``GITHUB_TOKEN``) mounts only
        on the controller.
        ``webhook_secret`` (``WEBHOOK_SECRET``) mounts on the webhook Function only.
        ``repositories`` and ``labels`` are required — webhook admission is fail-closed.
        ``job_image`` overrides the job recipe; ``image`` configures the webhook.
        ``cpu`` / ``memory`` / ``gpu`` / ``runtime`` are default Job Sandbox resources.
        ``min_containers`` defaults to ``0``; ``buffer_containers`` defaults to ``1``.
        """
        if not RUNNER_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid Runner name {name!r}")
        if not app.name:
            raise ValueError(
                "Runner.create requires a named App, "
                "e.g. modal.App('runner-modal-ci-app')"
            )
        if not repositories:
            raise ValueError(
                "repositories must be a non-empty sequence of 'owner/repo'"
            )
        if not labels:
            raise ValueError("labels must be a non-empty sequence")
        repos: list[str] = []
        for repo in repositories:
            if repo.count("/") != 1:
                raise ValueError(f"repository must be 'owner/repo', got {repo!r}")
            repos.append(repo)
        label_list = list(labels)
        github_name = github_secret.name
        if not github_name:
            raise ValueError(
                "github_secret requires a named Secret (modal.Secret.from_name)"
            )
        webhook_name = webhook_secret.name
        if not webhook_name:
            raise ValueError(
                "webhook_secret requires a named Secret (modal.Secret.from_name)"
            )

        runner = cls.from_name(
            name,
            create_if_missing=True,
            environment_name=environment_name,
            labels=label_list,
            repositories=repos,
            max_concurrent=max_concurrent,
            cache=cache,
            client=client,
        )
        runner.hydrate()
        prior = runner.meta
        if region is None:
            region_default: str | list[str] | None = prior.region
        elif isinstance(region, str):
            region_default = region
        else:
            region_default = list(region)

        exp = (
            dict(experimental_options)
            if experimental_options is not None
            else dict(prior.experimental_options or {})
        )
        job_runtime = runtime if runtime is not None else prior.runtime
        job_image_name = f"{name}-job"
        recipe = job_image
        if recipe is None:
            recipe = cls.docker_image() if job_runtime == "vm" else cls.default_image()
        build_app = modal.App.lookup(
            app.name,
            create_if_missing=True,
            environment_name=environment_name,
            client=client,
        )
        recipe.build(build_app).publish(
            job_image_name,
            environment_name=environment_name,
            client=client,
        )

        runner.meta = RunnerMeta(
            name=name,
            labels=label_list,
            repositories=repos,
            max_concurrent=(
                max_concurrent if max_concurrent is not None else prior.max_concurrent
            ),
            cache=cache,
            app_name=app.name,
            webhook_function=WEBHOOK_FUNCTION,
            github_secret_name=github_name,
            webhook_secret_name=webhook_name,
            job_image_name=job_image_name,
            github_enterprise_domain=(
                github_enterprise_domain
                if github_enterprise_domain is not None
                else prior.github_enterprise_domain
            ),
            region=region_default,
            idle_timeout=(
                idle_timeout if idle_timeout is not None else prior.idle_timeout
            ),
            experimental_options=exp or None,
            runner_group_id=(
                runner_group_id
                if runner_group_id is not None
                else prior.runner_group_id
            ),
            cpu=cpu if cpu is not None else prior.cpu,
            memory=memory if memory is not None else prior.memory,
            gpu=gpu if gpu is not None else prior.gpu,
            runtime=job_runtime,
        )
        runner.persist_meta()

        vol_map: dict[str | PurePosixPath, modal.Volume | modal.CloudBucketMount] = (
            dict(volumes) if volumes else {}
        )
        if (
            cache
            and runner.volume is not None
            and not any(str(path) == "/cache" for path in vol_map)
        ):
            vol_map["/cache"] = runner.volume

        run_env = dict(env or {})
        run_env["RUNNER_MODAL_NAME"] = name

        control_image = image if image is not None else cls.control_plane_image()
        from runner_modal.webhook import webhook as webhook_entry

        app.function(
            name=WEBHOOK_FUNCTION,
            image=control_image,
            secrets=[github_secret, webhook_secret],
            volumes=vol_map,
            env=run_env,
            region=region,
            cloud=cloud,
            min_containers=min_containers,
            max_containers=max_containers,
            buffer_containers=buffer_containers,
            scaledown_window=scaledown_window,
            timeout=timeout,
            startup_timeout=startup_timeout,
            ephemeral_disk=ephemeral_disk,
            proxy=proxy,
        )(
            modal.concurrent(max_inputs=WEBHOOK_MAX_INPUTS)(
                modal.asgi_app()(webhook_entry)
            )
        )
        return runner

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        environment_name: str | None = None,
        create_if_missing: bool = False,
        labels: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        max_concurrent: int | None = None,
        cache: bool = False,
        client: modal.Client | None = None,
    ) -> Self:
        if not RUNNER_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid Runner name {name!r}")
        return cls(
            name,
            environment_name=environment_name,
            create_if_missing=create_if_missing,
            labels=labels,
            repositories=repositories,
            max_concurrent=max_concurrent,
            cache=cache,
            client=client,
        )

    @classmethod
    @contextmanager
    def ephemeral(
        cls,
        *,
        labels: Sequence[str] | None = None,
        repositories: Sequence[str] | None = None,
        max_concurrent: int | None = None,
        cache: bool = False,
        client: modal.Client | None = None,
    ) -> Generator[Self, None, None]:
        name = f"ephemeral_{uuid.uuid4().hex}"
        runner = cls.from_name(
            name,
            create_if_missing=True,
            labels=labels,
            repositories=repositories,
            max_concurrent=max_concurrent,
            cache=cache,
            client=client,
        )
        try:
            runner.hydrate()
            yield runner
        finally:
            cls.objects.delete(name, client=client)

    def __repr__(self) -> str:
        return f"Runner.from_name({self.name!r})"

    def hydrate(self) -> None:
        if self.hydrated:
            return

        self.meta_dict = modal.Dict.from_name(
            f"{self.name}-runner-meta",
            environment_name=self.environment_name,
            create_if_missing=self.create_if_missing,
            client=self.client,
        )
        existing = self.meta_dict.get(META_KEY)
        if existing is None:
            if not self.create_if_missing:
                raise LookupError(
                    f"Runner {self.name!r} does not exist; "
                    "call Runner.create(...) first"
                )
            written = self.meta_dict.put(
                META_KEY, self.meta.model_dump(mode="json"), skip_if_exists=True
            )
            if not written:
                existing = self.meta_dict.get(META_KEY)
                if existing is None:
                    raise LookupError(f"Runner {self.name!r} meta init race")
                self.meta = RunnerMeta.model_validate(existing)
        else:
            self.meta = RunnerMeta.model_validate(existing)

        self.bind_volume()
        self.hydrated = True

    def bind_volume(self) -> None:
        if self.meta.cache:
            self.volume = modal.Volume.from_name(
                f"{self.name}-cache",
                environment_name=self.environment_name,
                create_if_missing=True,
                client=self.client,
            )
        else:
            self.volume = None

    def persist_meta(self) -> None:
        """Persist ``self.meta`` without reloading from the Dict."""
        if self.meta_dict is None:
            self.meta_dict = modal.Dict.from_name(
                f"{self.name}-runner-meta",
                environment_name=self.environment_name,
                create_if_missing=True,
                client=self.client,
            )
        self.meta_dict[META_KEY] = self.meta.model_dump(mode="json")
        self.bind_volume()
        self.hydrated = True

    def admit_reason(self, labels: Sequence[str], repository: str) -> str | None:
        """``None`` if admitted; otherwise a stable ignore reason string."""
        self.hydrate()
        allowed = set(self.meta.repositories)
        if not allowed:
            return "no_repositories"
        if repository not in allowed:
            return "repository_mismatch"
        pool = set(self.meta.labels)
        if not pool:
            return "empty_pool_labels"
        job_labels = set(labels)
        if "self-hosted" not in job_labels:
            return "missing_self_hosted"
        if not pool <= job_labels:
            return "label_mismatch"
        return None

    def job_app(self) -> modal.App:
        """App handle for webhook ``Job.create`` (explicit; no ambient context)."""
        self.hydrate()
        if not self.meta.app_name:
            raise LookupError(
                f"Runner {self.name!r} has no app_name; call Runner.create(...) first"
            )
        return modal.App.lookup(
            self.meta.app_name,
            environment_name=self.environment_name,
            client=self.client,
        )

    @property
    def url(self) -> str | None:
        self.hydrate()
        if not self.meta.app_name or not self.meta.webhook_function:
            return None
        try:
            fn = modal.Function.from_name(
                self.meta.app_name,
                self.meta.webhook_function,
                environment_name=self.environment_name,
                client=self.client,
            )
            return fn.get_web_url()
        except modal.exception.Error:
            return None

    def active_count(self, *, app_id: str | None = None) -> int:
        tags: dict[str, str] = {KIND_TAG: JOB_KIND, POOL_TAG: self.name}
        return sum(
            1 for _ in modal.Sandbox.list(app_id=app_id, tags=tags, client=self.client)
        )

    def has_capacity(self, *, app_id: str | None = None) -> bool:
        """Soft list-then-create check (not a reservation)."""
        self.hydrate()
        limit = self.meta.max_concurrent
        if limit is None:
            return True
        return self.active_count(app_id=app_id) < limit

    def info(self, *, app_id: str | None = None) -> RunnerInfo:
        self.hydrate()
        return RunnerInfo(
            name=self.meta.name,
            labels=list(self.meta.labels),
            repositories=list(self.meta.repositories),
            max_concurrent=self.meta.max_concurrent,
            cache=self.meta.cache,
            active_runners=self.active_count(app_id=app_id),
            app_name=self.meta.app_name,
            webhook_function=self.meta.webhook_function,
            github_secret_name=self.meta.github_secret_name,
            webhook_secret_name=self.meta.webhook_secret_name,
            job_image_name=self.meta.job_image_name,
        )
