"""Tests for runner_modal.server."""

from __future__ import annotations

from runner_modal.server import SERVER_CLASS_NAME, RunnerServer


def test_modal_identifies_server_by_stable_class_name() -> None:
    """Servers have no parameters; Modal keys identity off class __name__."""
    assert RunnerServer.__name__ == "RunnerServer"
    assert SERVER_CLASS_NAME == "RunnerServer"
