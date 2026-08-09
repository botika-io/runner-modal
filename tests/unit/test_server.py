"""Tests for runner_modal.server."""

from __future__ import annotations

from runner_modal.server import SERVER_CLASS_NAME, RunnerServer


def test_server_class_name_is_stable() -> None:
    assert RunnerServer.__name__ == SERVER_CLASS_NAME
