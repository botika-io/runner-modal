"""Tests for runner_modal.webhook — HMAC, admit, claim, outcomes."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from runner_modal.exceptions import AuthError, ConcurrencyLimitError
from runner_modal.meta import RunnerMeta
from runner_modal.runner import Runner
from runner_modal.webhook import (
    PENDING_TTL_SECONDS,
    DeliveryRecord,
    DeliveryStore,
    WebhookApp,
    WorkflowJobEvent,
)

POOL_LABELS = ["self-hosted", "modal", "acme"]
REPO = "acme/api"
HOOK = "hook"


def test_hmac_rejects_wrong_secret() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    with pytest.raises(AuthError, match="mismatch"):
        WorkflowJobEvent.from_request(
            body,
            {
                "x-github-event": "workflow_job",
                "x-github-delivery": "d1",
                "x-hub-signature-256": "sha256="
                + hmac.new(b"wrong", body, hashlib.sha256).hexdigest(),
            },
            secret=HOOK,
        )


def test_hmac_requires_delivery_and_signature_headers() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    with pytest.raises(AuthError, match="X-GitHub-Delivery"):
        WorkflowJobEvent.from_request(
            body,
            {
                "x-github-event": "workflow_job",
                "x-hub-signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
            },
            secret=HOOK,
        )
    with pytest.raises(AuthError, match="X-Hub-Signature-256"):
        WorkflowJobEvent.from_request(
            body,
            {"x-github-event": "workflow_job", "x-github-delivery": "d1"},
            secret=HOOK,
        )


def test_event_parses_queued_and_ignores_completed() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    event = WorkflowJobEvent.from_request(
        body,
        {
            "x-github-event": "workflow_job",
            "x-github-delivery": "d1",
            "x-hub-signature-256": "sha256="
            + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
        },
        secret=HOOK,
    )
    assert event is not None
    assert event.action == "queued"
    assert event.repo == REPO
    assert event.delivery_id == "d1"

    done = json.dumps(
        {
            "action": "completed",
            "workflow_job": {"id": 1, "run_id": 2, "labels": []},
            "repository": {"full_name": "a/b"},
        }
    ).encode()
    assert (
        WorkflowJobEvent.from_request(
            done,
            {
                "x-github-event": "workflow_job",
                "x-github-delivery": "d-done",
                "x-hub-signature-256": "sha256="
                + hmac.new(HOOK.encode(), done, hashlib.sha256).hexdigest(),
            },
            secret=HOOK,
        )
        is None
    )


def test_event_parses_form_urlencoded_github_payload() -> None:
    from urllib.parse import urlencode

    inner = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 7,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    )
    body = urlencode({"payload": inner}).encode()
    event = WorkflowJobEvent.from_request(
        body,
        {
            "content-type": "application/x-www-form-urlencoded",
            "x-github-event": "workflow_job",
            "x-github-delivery": "d-form",
            "x-hub-signature-256": "sha256="
            + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
        },
        secret=HOOK,
    )
    assert event is not None
    assert event.job_id == 7
    assert event.delivery_id == "d-form"


def test_try_claim_reclaims_stale_pending_without_object_id() -> None:
    store = MagicMock()
    stale = DeliveryRecord(
        status="pending", ts=time.time() - PENDING_TTL_SECONDS - 1
    ).model_dump(mode="json")
    store.get.side_effect = [stale, None]
    store.put.return_value = True
    deliveries = DeliveryStore.__new__(DeliveryStore)
    deliveries.store = store

    assert deliveries.try_claim("d-stale") is None
    store.__delitem__.assert_called()
    store.put.assert_called_once()


def test_try_claim_never_reclaims_pending_with_object_id() -> None:
    store = MagicMock()
    pending = DeliveryRecord(
        status="pending",
        ts=time.time() - PENDING_TTL_SECONDS - 1,
        object_id="sb-bound",
    ).model_dump(mode="json")
    store.get.return_value = pending
    deliveries = DeliveryStore.__new__(DeliveryStore)
    deliveries.store = store

    got = deliveries.try_claim("d-bound")
    assert got is not None
    assert got.object_id == "sb-bound"
    store.__delitem__.assert_not_called()
    store.put.assert_not_called()


def test_bind_object_durable_retries_until_verified() -> None:
    store = MagicMock()
    deliveries = DeliveryStore.__new__(DeliveryStore)
    deliveries.store = store
    bound = DeliveryRecord(
        status="pending", ts=time.time(), object_id="sb-1"
    ).model_dump(mode="json")
    store.get.side_effect = [None, bound]

    with patch("runner_modal.webhook.time.sleep"):
        deliveries.bind_object_durable("d1", "sb-1")

    assert store.__setitem__.call_count >= 1
    assert store.get.call_count == 2


def test_queued_job_accepted_with_object_id() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    fake_job = MagicMock()
    fake_job.object_id = "sb-ok"
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    gh = MagicMock()
    app = MagicMock()

    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=None),
        patch.object(DeliveryStore, "bind_object_durable") as bind,
        patch.object(DeliveryStore, "mark_done") as mark_done,
        patch.object(runner, "hydrate"),
        patch.object(runner, "github_secret", return_value=gh),
        patch.object(runner, "job_app", return_value=app),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch(
            "runner_modal.webhook.Runner.Job.create",
            return_value=fake_job,
        ) as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "deliv-1",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"object_id": "sb-ok", "name": "job-42"}
        assert resp.headers.get("X-Runner-Modal-Outcome") == "accepted"
        bind.assert_called_once_with("deliv-1", "sb-ok")
        mark_done.assert_called_once_with("deliv-1", "sb-ok")
        assert create.call_args.kwargs["github_secret"] is gh
        assert create.call_args.kwargs["app"] is app


def test_bad_hmac_returns_401() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    with patch.object(DeliveryStore, "__init__", lambda self, name: None):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(b"wrong", body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        assert resp.headers.get("X-Runner-Modal-Outcome") == "auth"
        assert resp.headers.get("X-Runner-Modal-Reason") == "hmac"


def test_ignored_event_returns_204_with_reason() -> None:
    body = json.dumps(
        {
            "action": "completed",
            "workflow_job": {"id": 1, "run_id": 1, "labels": []},
            "repository": {"full_name": "a/b"},
        }
    ).encode()
    with patch.object(DeliveryStore, "__init__", lambda self, name: None):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Outcome") == "ignored"
        assert resp.headers.get("X-Runner-Modal-Reason") == "event_filtered"


def test_label_mismatch_returns_204_and_does_not_create() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": ["self-hosted", "modal"],
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create") as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Outcome") == "ignored"
        assert resp.headers.get("X-Runner-Modal-Reason") == "label_mismatch"
        create.assert_not_called()


def test_repo_mismatch_returns_204_and_does_not_create() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=["other/repo"])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=["other/repo"],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create") as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Reason") == "repository_mismatch"
        create.assert_not_called()


def test_missing_self_hosted_returns_204() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": ["modal", "acme"],
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=["modal", "acme"], repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=["modal", "acme"],
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create") as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Reason") == "missing_self_hosted"
        create.assert_not_called()


def test_empty_pool_labels_returns_204() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=[], repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=[],
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create") as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Reason") == "empty_pool_labels"
        create.assert_not_called()


def test_cancelled_terminates_matching_job() -> None:
    body = json.dumps(
        {
            "action": "cancelled",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    job = MagicMock()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch.object(WebhookApp, "job_from_name", return_value=job),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Outcome") == "cancelled"
        job.terminate.assert_called_once()


def test_cancelled_skips_repo_mismatch() -> None:
    body = json.dumps(
        {
            "action": "cancelled",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=["other/repo"])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=["other/repo"],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch.object(WebhookApp, "terminate_job") as terminate,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 204
        assert resp.headers.get("X-Runner-Modal-Reason") == "repository_mismatch"
        terminate.assert_not_called()


def test_duplicate_delivery_returns_existing_object_id() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    done = DeliveryRecord(status="done", ts=time.time(), object_id="sb-dup")
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=done),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create") as create,
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["object_id"] == "sb-dup"
        assert resp.headers.get("X-Runner-Modal-Outcome") == "duplicate"
        create.assert_not_called()


def test_in_flight_delivery_returns_503() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    pending = DeliveryRecord(status="pending", ts=time.time())
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=pending),
        patch.object(runner, "hydrate"),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 503
        assert resp.headers.get("X-Runner-Modal-Outcome") == "busy"
        assert resp.headers.get("X-Runner-Modal-Reason") == "delivery_in_progress"


def test_capacity_full_releases_claim_and_returns_503() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=None),
        patch.object(DeliveryStore, "release") as release,
        patch.object(runner, "hydrate"),
        patch.object(runner, "github_secret", return_value=MagicMock()),
        patch.object(runner, "job_app", return_value=MagicMock()),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch(
            "runner_modal.webhook.Runner.Job.create",
            side_effect=ConcurrencyLimitError("full"),
        ),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 503
        assert resp.headers.get("X-Runner-Modal-Outcome") == "capacity"
        release.assert_called_once_with("d")


def test_create_failure_releases_claim() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=None),
        patch.object(DeliveryStore, "mark_done") as mark_done,
        patch.object(DeliveryStore, "release") as release,
        patch.object(runner, "hydrate"),
        patch.object(runner, "github_secret", return_value=MagicMock()),
        patch.object(runner, "job_app", return_value=MagicMock()),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch(
            "runner_modal.webhook.Runner.Job.create",
            side_effect=RuntimeError("boom"),
        ),
    ):
        resp = TestClient(
            WebhookApp("acme", webhook_secret=HOOK).fastapi,
            raise_server_exceptions=False,
        ).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d-fail",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 500
        mark_done.assert_not_called()
        release.assert_called_once_with("d-fail")


def test_mark_done_failure_after_bind_still_accepts() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    fake_job = MagicMock()
    fake_job.object_id = "sb-ok"
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=None),
        patch.object(DeliveryStore, "bind_object_durable"),
        patch.object(DeliveryStore, "mark_done", side_effect=RuntimeError("dict")),
        patch.object(DeliveryStore, "release") as release,
        patch.object(runner, "hydrate"),
        patch.object(runner, "github_secret", return_value=MagicMock()),
        patch.object(runner, "job_app", return_value=MagicMock()),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create", return_value=fake_job),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["object_id"] == "sb-ok"
        release.assert_not_called()


def test_bind_failure_terminates_job_releases_and_returns_503() -> None:
    body = json.dumps(
        {
            "action": "queued",
            "workflow_job": {
                "id": 42,
                "run_id": 1,
                "labels": list(POOL_LABELS),
            },
            "repository": {"full_name": REPO},
        }
    ).encode()
    fake_job = MagicMock()
    fake_job.object_id = "sb-ok"
    runner = Runner.from_name("acme", labels=POOL_LABELS, repositories=[REPO])
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        app_name="acme-ci",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(DeliveryStore, "try_claim", return_value=None),
        patch.object(
            DeliveryStore,
            "bind_object_durable",
            side_effect=RuntimeError("dict down"),
        ),
        patch.object(DeliveryStore, "release") as release,
        patch.object(runner, "hydrate"),
        patch.object(runner, "github_secret", return_value=MagicMock()),
        patch.object(runner, "job_app", return_value=MagicMock()),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
        patch("runner_modal.webhook.Runner.Job.create", return_value=fake_job),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).post(
            "/github",
            content=body,
            headers={
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "d",
                "X-Hub-Signature-256": "sha256="
                + hmac.new(HOOK.encode(), body, hashlib.sha256).hexdigest(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 503
        assert resp.headers.get("X-Runner-Modal-Outcome") == "bind_failed"
        fake_job.terminate.assert_called_once()
        release.assert_called_once()


def test_health_reports_labels_and_concurrency() -> None:
    runner = Runner.from_name(
        "acme", labels=POOL_LABELS, repositories=[REPO], max_concurrent=20
    )
    runner.meta = RunnerMeta(
        name="acme",
        labels=list(POOL_LABELS),
        repositories=[REPO],
        max_concurrent=20,
        app_name="acme-ci",
        webhook_function="webhook",
        github_secret_name="github-token",
        webhook_secret_name="github-webhook",
        job_image_name="acme-job",
    )
    with (
        patch.object(DeliveryStore, "__init__", lambda self, name: None),
        patch.object(runner, "hydrate"),
        patch.object(runner, "active_count", return_value=2),
        patch("runner_modal.webhook.Runner.from_name", return_value=runner),
    ):
        resp = TestClient(WebhookApp("acme", webhook_secret=HOOK).fastapi).get(
            "/health"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["runner"] == "acme"
        assert body["labels"] == POOL_LABELS
        assert body["repositories"] == 1
        assert body["active_runners"] == 2
        assert body["max_concurrent"] == 20
