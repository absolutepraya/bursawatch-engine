"""One bound on Delivery Owner work for a single Board process.

A scheduled Hermes job runs on a serial lane shared with unrelated jobs, so a degraded
Delivery Owner must not be able to stretch a Board run. Every attempt (an outbox
operation, a heartbeat, or a publication projection) is charged here once it is claimed,
and the receipt wait is clamped to the time that remains. Work that is refused stays in
its durable queue and is retried by the next natural run.
"""

from __future__ import annotations

import math
import os
import time
from typing import Callable, Mapping

DEFAULT_MAX_ATTEMPTS = 40
DEFAULT_MAX_SECONDS = 180.0
# The scheduled run's own heartbeat must get a chance even after the main budget is spent.
RESERVE_ATTEMPTS = 2
RESERVE_SECONDS = 45.0

ATTEMPTS_VARIABLE = "IDX_SWING_PLAN_BOARD_DRAIN_MAX_ATTEMPTS"
SECONDS_VARIABLE = "IDX_SWING_PLAN_BOARD_DRAIN_MAX_SECONDS"


class DrainBudget:
    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("drain attempt budget must be a positive integer")
        if not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("drain time budget must be positive")
        self.max_attempts = max_attempts
        self.max_seconds = float(max_seconds)
        self._clock = clock
        self._started = clock()
        self.attempts = 0
        self.reason: str | None = None

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None, *, clock: Callable[[], float] = time.monotonic
    ) -> "DrainBudget":
        """Read operator overrides; anything unusable falls back to the reviewed default."""
        environ = os.environ if environ is None else environ
        try:
            attempts = int(environ.get(ATTEMPTS_VARIABLE, ""))
        except ValueError:
            attempts = DEFAULT_MAX_ATTEMPTS
        try:
            seconds = float(environ.get(SECONDS_VARIABLE, ""))
        except ValueError:
            seconds = DEFAULT_MAX_SECONDS
        if attempts < 1:
            attempts = DEFAULT_MAX_ATTEMPTS
        if not math.isfinite(seconds) or seconds <= 0:
            seconds = DEFAULT_MAX_SECONDS
        return cls(max_attempts=attempts, max_seconds=seconds, clock=clock)

    def reserve(self) -> "DrainBudget":
        """Separate headroom for the final heartbeat, on the same clock."""
        return DrainBudget(max_attempts=RESERVE_ATTEMPTS, max_seconds=RESERVE_SECONDS, clock=self._clock)

    @property
    def exhausted(self) -> bool:
        return self.reason is not None

    def elapsed_seconds(self) -> float:
        return self._clock() - self._started

    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed_seconds())

    def reached(self) -> str | None:
        """The limit that has been hit, without charging or recording anything."""
        if self.reason is not None:
            return self.reason
        if self.elapsed_seconds() >= self.max_seconds:
            return "elapsed"
        if self.attempts >= self.max_attempts:
            return "attempts"
        return None

    def refuse(self) -> None:
        """Record that work was turned away. Every later request is refused."""
        self.reason = self.reached()

    def charge(self) -> None:
        """Charge an attempt for work that has already been claimed."""
        self.attempts += 1

    def allow(self) -> bool:
        """Charge one attempt. Once refused, every later request is refused."""
        self.refuse()
        if self.reason is not None:
            return False
        self.charge()
        return True
