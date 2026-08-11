"""Tests for runner_modal.exceptions."""

from __future__ import annotations

import pytest

from runner_modal.exceptions import AuthError, ConcurrencyLimitError, RunnerError


def test_product_errors_are_runner_errors() -> None:
    for exc in (AuthError, ConcurrencyLimitError):
        assert issubclass(exc, RunnerError)
        with pytest.raises(RunnerError):
            raise exc("boom")
