"""Invite owners of scooter models without hardware verification to report their result.

The invitation is a single dismissible entry in Home Assistant's Repairs. It appears
once a scooter has delivered live readings for a few days, so only people whose setup
demonstrably works are asked, and it disappears as soon as the model counts as verified.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import DOMAIN, REPORT_URL
from .utilities import UTC

INVITATION_DELAY = timedelta(days=3)
STORE_VERSION = 1


def invitation_issue_id(entry_id: str) -> str:
    """One invitation per config entry."""
    return f"scooter_feedback_{entry_id}"


def withdraw_invitation(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the invitation; Home Assistant remembers it if the user dismissed it before."""
    ir.async_delete_issue(hass, DOMAIN, invitation_issue_id(entry_id))


class FeedbackInvitation:
    """Track since when a scooter delivers live readings and raise the invitation once due."""

    def __init__(self, hass: HomeAssistant, entry_id: str, address: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"ninebot_e_scooters_feedback_{address.replace(':', '').lower()}"
        )
        self._first_live_reading_at: datetime | None = None
        self._invitation_raised = False

    async def async_load(self) -> None:
        """Restore the first live reading, so a restart does not restart the waiting time."""
        payload = await self._store.async_load()
        try:
            self._first_live_reading_at = datetime.fromisoformat(payload["first_live_reading_at"])
        except (KeyError, TypeError, ValueError):
            self._first_live_reading_at = None

    def note_live_reading(self, model: str, model_is_verified: bool) -> None:
        """Called after every successful live telemetry read."""
        if model_is_verified:
            self._withdraw()
            return
        now = datetime.now(UTC)
        if self._first_live_reading_at is None:
            self._first_live_reading_at = now
            self._store.async_delay_save(
                lambda: {"first_live_reading_at": now.isoformat()}, 1
            )
        if not self._invitation_raised and now - self._first_live_reading_at >= INVITATION_DELAY:
            self._raise(model)

    def _raise(self, model: str) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            invitation_issue_id(self._entry_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            learn_more_url=REPORT_URL,
            translation_key="scooter_feedback",
            translation_placeholders={"model": model, "report_url": REPORT_URL},
        )
        self._invitation_raised = True

    def _withdraw(self) -> None:
        if self._invitation_raised:
            withdraw_invitation(self._hass, self._entry_id)
            self._invitation_raised = False
