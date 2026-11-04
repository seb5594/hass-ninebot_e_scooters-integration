"""The feedback invitation: when it appears, when it goes, and that the README count stays true."""

import importlib
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO = Path(__file__).parents[2]
INVITATION_DELAY = timedelta(days=3)
LONG_AGO = datetime.now(timezone.utc) - INVITATION_DELAY - timedelta(hours=1)


class RecordingIssueRegistry:
    def __init__(self):
        self.created, self.deleted = [], []

    def async_create_issue(self, hass, domain, issue_id, **details):
        self.created.append((issue_id, details))

    def async_delete_issue(self, hass, domain, issue_id):
        self.deleted.append(issue_id)


@pytest.fixture
def registry(monkeypatch):
    """Home Assistant doubles for the few modules the feedback module touches."""
    recording = RecordingIssueRegistry()

    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    issues = module("homeassistant.helpers.issue_registry",
                    async_create_issue=recording.async_create_issue,
                    async_delete_issue=recording.async_delete_issue,
                    IssueSeverity=SimpleNamespace(WARNING="warning"))
    store = type("Store", (), {
        "__class_getitem__": classmethod(lambda cls, item: cls),
        "__init__": lambda self, *args, **kwargs: None,
        "async_delay_save": lambda self, *args: None,
    })
    module("homeassistant", __path__=[])
    module("homeassistant.const", Platform=SimpleNamespace(SENSOR="sensor", BINARY_SENSOR="binary_sensor",
                                                           SWITCH="switch", LOCK="lock", SELECT="select"))
    module("homeassistant.core", HomeAssistant=object)
    module("homeassistant.helpers", issue_registry=issues)
    module("homeassistant.helpers.storage", Store=store)
    for name in ("const", "feedback"):
        monkeypatch.delitem(sys.modules, f"custom_components.ninebot_e_scooters.{name}", raising=False)
    feedback = importlib.import_module("custom_components.ninebot_e_scooters.feedback")
    recording.new_invitation = lambda: feedback.FeedbackInvitation(
        hass=None, entry_id="entry1", address="AA:BB:CC:DD:EE:FF")
    return recording


def test_nothing_is_raised_before_the_waiting_time_is_over(registry):
    invitation = registry.new_invitation()
    invitation.note_live_reading("Mi Electric Scooter Pro 2", model_is_verified=False)
    assert registry.created == []


def test_invitation_is_raised_once_after_the_waiting_time(registry):
    invitation = registry.new_invitation()
    invitation._first_live_reading_at = LONG_AGO
    invitation.note_live_reading("Mi Electric Scooter Pro 2", model_is_verified=False)
    invitation.note_live_reading("Mi Electric Scooter Pro 2", model_is_verified=False)
    assert [issue_id for issue_id, _ in registry.created] == ["scooter_feedback_entry1"]
    details = registry.created[0][1]
    assert details["is_fixable"] is False
    assert details["translation_placeholders"]["model"] == "Mi Electric Scooter Pro 2"


def test_verified_models_are_never_asked_and_lose_a_raised_invitation(registry):
    invitation = registry.new_invitation()
    invitation._first_live_reading_at = LONG_AGO
    invitation.note_live_reading("Mi Electric Scooter 1S", model_is_verified=True)
    assert registry.created == [] and registry.deleted == []
    invitation.note_live_reading("Mi Electric Scooter Pro 2", model_is_verified=False)
    invitation.note_live_reading("Mi Electric Scooter Pro 2", model_is_verified=True)
    assert registry.deleted == ["scooter_feedback_entry1"]


@pytest.mark.parametrize("readme, summary", [
    ("README.md", r"Only (\d+) of (\d+) model groups"),
    ("docs/README.de.md", r"nur (\d+) von (\d+) Modellgruppen"),
])
def test_readme_count_matches_the_model_table(readme, summary):
    text = (REPO / readme).read_text()
    table_rows = re.findall(r"^\| (?!Modell|Model|---)[^|]+\|[^|]+\|[^|]+\|([^|]+)\|$", text, re.MULTILINE)
    verified = sum(1 for status in table_rows if status.strip().startswith(("Reference device", "Referenzgerät")))
    announced = re.search(summary, text, re.IGNORECASE)
    assert announced and (int(announced[1]), int(announced[2])) == (verified, len(table_rows))
