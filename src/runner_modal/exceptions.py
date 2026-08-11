"""Public exception types.

Soft absence → ``None`` (e.g. ``runner.url``, ignored webhook).
Failures → raise (auth, timeout, concurrency, or ``ValueError`` / ``LookupError``).
"""

from __future__ import annotations


class RunnerError(Exception):
    pass


class AuthError(RunnerError):
    pass


class ConcurrencyLimitError(RunnerError):
    pass


class JobTimeoutError(RunnerError):
    pass
