"""Small, transport-independent helpers shared by session components."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timezone
import math

try:
    timeout = asyncio.timeout
except AttributeError:  # Python 3.10, used by Home Assistant before 2023.8
    from async_timeout import timeout

# datetime.UTC only exists from Python 3.11 on.
UTC = timezone.utc

# Python 3.10 raises asyncio.TimeoutError, which is not the builtin TimeoutError
# there. Both names are the same class from Python 3.11 on.
TIMEOUT_ERRORS = (asyncio.TimeoutError, TimeoutError)


def parse_app_key(value: object) -> bytes:
    """Validate a persisted key before any BLE operation can consume it."""
    if not isinstance(value, str):
        raise ValueError("The saved application key must be a hexadecimal string")
    try:
        key = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("The saved application key is not valid hexadecimal") from error
    if len(key) != 16:
        raise ValueError("The saved application key must contain exactly 16 bytes")
    return key


def finite_number(value: object) -> bool:
    """Reject booleans and non-finite values when restoring numeric telemetry."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(slots=True)
class ConnectionBackoff:
    """Limit repeated failed sessions without delaying a first recovery attempt."""

    failures: int = 0
    maximum_seconds: float = 120.0

    def failed(self, minimum_seconds: float, *, needs_confirmation: bool = False) -> float:
        """Keep backend cleanup deadlines and slow repeated button prompts."""
        self.failures = min(self.failures + 1, 8)
        minimum = max(minimum_seconds, 60.0 if needs_confirmation else 0.0)
        ceiling = max(self.maximum_seconds, 300.0 if needs_confirmation else minimum)
        return min(ceiling, minimum * 2 ** (self.failures - 1))

    def reset(self) -> None:
        """Only decoded telemetry proves that the complete session recovered."""
        self.failures = 0
