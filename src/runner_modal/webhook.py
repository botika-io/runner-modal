"""Webhook FastAPI face, delivery store, Modal ASGI entry (not exported)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import os
import time
from collections.abc import Mapping
from typing import Literal, Self

import modal
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from runner_modal.exceptions import AuthError, ConcurrencyLimitError
from runner_modal.runner import Runner

PENDING_TTL_SECONDS = 15 * 60
BIND_ATTEMPTS = 5
BIND_RETRY_SECONDS = 0.05
OUTCOME_HEADER = "X-Runner-Modal-Outcome"
REASON_HEADER = "X-Runner-Modal-Reason"

log = logging.getLogger("runner_modal.webhook")


def webhook() -> FastAPI:
    """Modal ASGI entry — mounted env only (KeyError if missing)."""
    return WebhookApp(
        os.environ["RUNNER_MODAL_NAME"],
        webhook_secret=os.environ["WEBHOOK_SECRET"],
    ).fastapi


class DeliveryRecord(BaseModel):
    status: Literal["pending", "done"]
    ts: float
    object_id: str | None = None


class Repository(BaseModel):
    full_name: str


class WorkflowJob(BaseModel):
    id: int
    run_id: int = 0
    labels: list[str] = Field(default_factory=list)


class WorkflowJobEvent(BaseModel):
    """GitHub ``workflow_job`` event; construct via ``from_request`` (HMAC first)."""

    action: str
    workflow_job: WorkflowJob
    repository: Repository
    delivery_id: str = ""

    @property
    def job_id(self) -> int:
        return self.workflow_job.id

    @property
    def labels(self) -> list[str]:
        return list(self.workflow_job.labels)

    @property
    def repo(self) -> str:
        return self.repository.full_name

    @classmethod
    def from_request(
        cls,
        body: bytes,
        headers: Mapping[str, str],
        *,
        secret: str,
    ) -> Self | None:
        if not secret:
            raise AuthError("webhook secret is required")

        hdrs = {k.lower(): v for k, v in headers.items()}
        signature = hdrs.get("x-hub-signature-256")
        if not signature or not signature.startswith("sha256="):
            raise AuthError("missing or invalid X-Hub-Signature-256")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        received = signature.removeprefix("sha256=")
        try:
            matched = hmac.compare_digest(expected, received)
        except ValueError as e:
            raise AuthError("webhook signature mismatch") from e
        if not matched:
            raise AuthError("webhook signature mismatch")

        delivery = hdrs.get("x-github-delivery")
        if not delivery:
            raise AuthError("missing X-GitHub-Delivery")

        event_name = hdrs.get("x-github-event", "")
        if event_name and event_name != "workflow_job":
            return None

        payload = body
        content_type = hdrs.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or payload.startswith(
            b"payload="
        ):
            from urllib.parse import parse_qs

            form = parse_qs(payload.decode(), keep_blank_values=True)
            values = form.get("payload") or []
            if not values:
                raise AuthError("missing form payload field")
            payload = values[0].encode()

        event = cls.model_validate_json(payload)
        if event.action not in ("queued", "cancelled"):
            return None

        return event.model_copy(update={"delivery_id": delivery})


class HealthResponse(BaseModel):
    # HTTP 200 is success; no ``ok: bool`` field.
    runner: str
    labels: list[str]
    repositories: int
    active_runners: int
    max_concurrent: int | None


class JobAccepted(BaseModel):
    object_id: str
    name: str | None = None


class DeliveryStore:
    """Delivery-ID idempotency (Modal Dict).

    Claim before create; pending rows with ``object_id`` are never TTL-reclaimed.
    """

    def __init__(self, runner_name: str) -> None:
        self.store = modal.Dict.from_name(
            f"{runner_name}-runner-deliveries",
            create_if_missing=True,
        )

    def get(self, delivery_id: str) -> DeliveryRecord | None:
        val = self.store.get(delivery_id)
        if val is None:
            return None
        try:
            return DeliveryRecord.model_validate(val)
        except ValidationError:
            return None

    def try_claim(self, delivery_id: str) -> DeliveryRecord | None:
        """Claim ``delivery_id``. Returns ``None`` if this caller won.

        If the key already exists, returns the existing record.
        Stale pending without ``object_id`` older than ``PENDING_TTL_SECONDS``
        may be deleted and reclaimed. Pending with ``object_id`` is never reclaimed.
        """
        existing = self.get(delivery_id)
        if existing is not None:
            if existing.object_id is not None:
                return existing
            if (
                existing.status == "pending"
                and time.time() - existing.ts > PENDING_TTL_SECONDS
            ):
                del self.store[delivery_id]
            else:
                return existing

        pending = DeliveryRecord(status="pending", ts=time.time())
        written = self.store.put(
            delivery_id,
            pending.model_dump(mode="json"),
            skip_if_exists=True,
        )
        if written:
            return None
        return self.get(delivery_id)

    def bind_object(self, delivery_id: str, object_id: str) -> None:
        self.store[delivery_id] = DeliveryRecord(
            status="pending",
            ts=time.time(),
            object_id=object_id,
        ).model_dump(mode="json")

    def bind_object_durable(self, delivery_id: str, object_id: str) -> None:
        """Write and verify ``object_id`` so TTL reclaim cannot double-spawn."""
        last_error: Exception | None = None
        for attempt in range(BIND_ATTEMPTS):
            try:
                self.bind_object(delivery_id, object_id)
                record = self.get(delivery_id)
                if record is not None and record.object_id == object_id:
                    return
                last_error = RuntimeError(
                    f"delivery {delivery_id!r} bind not durable after write"
                )
            except Exception as e:
                last_error = e
            if attempt + 1 < BIND_ATTEMPTS:
                time.sleep(BIND_RETRY_SECONDS)
        assert last_error is not None
        raise last_error

    def mark_done(self, delivery_id: str, object_id: str) -> None:
        record = DeliveryRecord(status="done", ts=time.time(), object_id=object_id)
        self.store[delivery_id] = record.model_dump(mode="json")

    def release(self, delivery_id: str) -> None:
        """Delete claim only while pending and still unbound."""
        record = self.get(delivery_id)
        if (
            record is not None
            and record.status == "pending"
            and record.object_id is None
        ):
            del self.store[delivery_id]


class WebhookApp:
    """ASGI control plane for one named Runner."""

    def __init__(self, runner_name: str, *, webhook_secret: str) -> None:
        if not webhook_secret:
            raise AuthError("webhook_secret is required")
        self.runner_name = runner_name
        self.webhook_secret = webhook_secret
        self.deliveries = DeliveryStore(runner_name)
        self.fastapi = FastAPI()
        self.fastapi.get("/health", response_model=HealthResponse)(self.health)
        self.fastapi.post(
            "/github",
            response_model=JobAccepted,
            responses={
                204: {"description": "Event ignored"},
                503: {"description": "Capacity full or delivery in progress"},
            },
        )(self.github_webhook)

    def outcome(self, outcome: str, reason: str | None = None) -> dict[str, str]:
        headers = {OUTCOME_HEADER: outcome}
        if reason:
            headers[REASON_HEADER] = reason
        return headers

    def ignore(self, reason: str) -> Response:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers=self.outcome("ignored", reason),
        )

    def accept(self, body: JobAccepted, *, outcome: str = "accepted") -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=body.model_dump(mode="json"),
            headers=self.outcome(outcome),
        )

    def health(self) -> HealthResponse:
        info = Runner.from_name(self.runner_name).info()
        return HealthResponse(
            runner=info.name,
            labels=list(info.labels),
            repositories=len(info.repositories),
            active_runners=info.active_runners,
            max_concurrent=info.max_concurrent,
        )

    async def github_webhook(self, request: Request) -> JobAccepted | Response:
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()}
        return await asyncio.to_thread(self.process_webhook, body, headers)

    def process_webhook(
        self, body: bytes, headers: dict[str, str]
    ) -> JobAccepted | Response:
        try:
            event = WorkflowJobEvent.from_request(
                body, headers, secret=self.webhook_secret
            )
        except AuthError as e:
            log.info(
                "webhook auth_failed runner=%s detail=%s",
                self.runner_name,
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers=self.outcome("auth", "hmac"),
            ) from e
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            ) from e

        if event is None:
            log.info(
                "webhook ignored runner=%s reason=event_filtered",
                self.runner_name,
            )
            return self.ignore("event_filtered")

        runner = Runner.from_name(self.runner_name)
        reason = runner.admit_reason(event.labels, event.repo)
        if reason is not None:
            log.info(
                "webhook ignored runner=%s delivery=%s repo=%s action=%s reason=%s",
                self.runner_name,
                event.delivery_id,
                event.repo,
                event.action,
                reason,
            )
            return self.ignore(reason)

        if event.action == "cancelled":
            self.terminate_job(runner, event.job_id)
            log.info(
                "webhook cancelled runner=%s delivery=%s job_id=%s",
                self.runner_name,
                event.delivery_id,
                event.job_id,
            )
            return Response(
                status_code=status.HTTP_204_NO_CONTENT,
                headers=self.outcome("cancelled"),
            )

        existing = self.deliveries.try_claim(event.delivery_id)
        if existing is not None:
            if existing.object_id:
                log.info(
                    "webhook duplicate runner=%s delivery=%s object_id=%s",
                    self.runner_name,
                    event.delivery_id,
                    existing.object_id,
                )
                return self.accept(
                    JobAccepted(object_id=existing.object_id), outcome="duplicate"
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="delivery in progress",
                headers=self.outcome("busy", "delivery_in_progress"),
            )

        job_name = f"job-{event.job_id}"
        try:
            job = Runner.Job.create(
                runner,
                app=runner.job_app(),
                repository=event.repo,
                labels=event.labels,
                name=job_name,
                github_secret=runner.github_secret(),
            )
        except LookupError as e:
            self.deliveries.release(event.delivery_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            ) from e
        except ConcurrencyLimitError as e:
            self.deliveries.release(event.delivery_id)
            log.info(
                "webhook capacity runner=%s delivery=%s",
                self.runner_name,
                event.delivery_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e),
                headers=self.outcome("capacity"),
            ) from e
        except modal.exception.AlreadyExistsError:
            job = self.job_from_name(runner, job_name)
            if job is None:
                self.deliveries.release(event.delivery_id)
                raise
        except Exception:
            self.deliveries.release(event.delivery_id)
            raise

        try:
            self.deliveries.bind_object_durable(event.delivery_id, job.object_id)
        except Exception:
            with contextlib.suppress(Exception):
                job.terminate()
            self.deliveries.release(event.delivery_id)
            log.info(
                "webhook bind_failed runner=%s delivery=%s",
                self.runner_name,
                event.delivery_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="delivery bind failed",
                headers=self.outcome("bind_failed"),
            ) from None
        with contextlib.suppress(Exception):
            self.deliveries.mark_done(event.delivery_id, job.object_id)
        log.info(
            "webhook accepted runner=%s delivery=%s repo=%s object_id=%s",
            self.runner_name,
            event.delivery_id,
            event.repo,
            job.object_id,
        )
        return self.accept(
            JobAccepted(
                object_id=job.object_id,
                name=job_name,
            )
        )

    def job_from_name(self, runner: Runner, job_name: str) -> Runner.Job | None:
        runner.hydrate()
        app_name = runner.meta.app_name
        if not app_name:
            return None
        try:
            return Runner.Job.from_name(
                app_name,
                job_name,
                environment_name=runner.environment_name,
                client=runner.client,
            )
        except (LookupError, modal.exception.NotFoundError):
            return None

    def terminate_job(self, runner: Runner, job_id: int) -> None:
        job = self.job_from_name(runner, f"job-{job_id}")
        if job is not None:
            job.terminate()
