"""Every Home Assistant release difference handled by compat.py, without Home Assistant."""

import asyncio
from dataclasses import FrozenInstanceError, dataclass, fields
from types import SimpleNamespace

import pytest

from compat_scope import load_compat
from protocol_scope import utilities


class FullBluetooth:
    """A recent Home Assistant: every optional feature exists."""

    class BluetoothScanningMode:
        ACTIVE = "active"

    class BluetoothCallbackReplay:
        NEWEST_FIRST = "newest-first"

    def __init__(self):
        self.registered = None
        self.scans = []
        self.cleared = []

    def async_register_callback(self, hass, callback, match_dict, mode, *,
                                scan_interval=None, scan_duration=None, replay=None):
        self.registered = dict(match=match_dict, mode=mode, scan_interval=scan_interval,
                               scan_duration=scan_duration, replay=replay)
        return lambda: None

    async def async_request_active_scan(self, hass, **options):
        self.scans.append(options)

    def async_clear_advertisement_history(self, hass, address):
        self.cleared.append(address)

    def async_address_reachability_diagnostics(self, hass, address, intent):
        return f"diagnostics for {address} ({intent})"

    class BluetoothReachabilityIntent:
        CONNECTION = "connection"

    def async_scanner_count(self, hass, connectable=True):
        return 2


class OldBluetooth:
    """A release from 2023: only the callback, no optional features."""

    class BluetoothScanningMode:
        ACTIVE = "active"

    def __init__(self):
        self.registered = None

    def async_register_callback(self, hass, callback, match_dict, mode):
        self.registered = dict(match=match_dict, mode=mode)
        return lambda: None

    def async_scanner_count(self, hass, connectable=True):
        return 1


def test_callback_registration_passes_every_feature_a_recent_release_offers():
    bluetooth = FullBluetooth()
    load_compat(bluetooth).async_register_scooter_callback(
        object(), print, "AA:BB", scan_interval=60.0, scan_duration=10.0)
    assert bluetooth.registered == dict(
        match={"address": "AA:BB", "connectable": True}, mode="active",
        scan_interval=60.0, scan_duration=10.0, replay="newest-first")


def test_callback_registration_drops_features_an_old_release_does_not_know():
    bluetooth = OldBluetooth()
    unsubscribe = load_compat(bluetooth).async_register_scooter_callback(
        object(), print, "AA:BB", scan_interval=60.0, scan_duration=10.0)
    assert bluetooth.registered == dict(match={"address": "AA:BB", "connectable": True}, mode="active")
    assert callable(unsubscribe)


def test_active_scan_and_history_reset_are_noops_without_the_api():
    compat = load_compat(OldBluetooth())
    asyncio.run(compat.async_request_active_scan(object(), duration=4.0))
    compat.clear_advertisement_history(object(), "AA:BB")


def test_active_scan_and_history_reset_delegate_where_available():
    bluetooth = FullBluetooth()
    compat = load_compat(bluetooth)
    asyncio.run(compat.async_request_active_scan(object(), duration=4.0))
    compat.clear_advertisement_history(object(), "AA:BB")
    assert bluetooth.scans == [{"duration": 4.0}] and bluetooth.cleared == ["AA:BB"]


def test_unreachable_scooter_is_explained_with_or_without_reachability_diagnostics():
    assert "diagnostics for AA:BB (connection)" in load_compat(FullBluetooth()).describe_unreachable_scooter(
        object(), "AA:BB")
    assert load_compat(OldBluetooth()).describe_unreachable_scooter(object(), "AA:BB") == (
        "1 connectable Bluetooth scanner(s) available, none has seen AA:BB")


@dataclass
class StaticPath:
    url_path: str
    path: str
    cache_headers: bool


def test_static_files_use_the_async_registration_of_recent_releases():
    registered = []

    async def register(paths):
        registered.extend(paths)

    hass = SimpleNamespace(http=SimpleNamespace(async_register_static_paths=register))
    compat = load_compat(static_path_config=StaticPath)
    asyncio.run(compat.async_register_static_files(hass, [("/a.js", "/files/a.js")]))
    assert registered == [StaticPath("/a.js", "/files/a.js", True)]


def test_static_files_fall_back_to_the_blocking_registration_of_old_releases():
    registered = []
    hass = SimpleNamespace(http=SimpleNamespace(
        register_static_path=lambda url, path, cache: registered.append((url, path, cache))))
    asyncio.run(load_compat().async_register_static_files(hass, [("/a.js", "/files/a.js")]))
    assert registered == [("/a.js", "/files/a.js", True)]


class Flow:
    """Flow of a recent release: the entry data is merged by Home Assistant."""

    def async_update_reload_and_abort(self, entry, *, data_updates=None, data=None, reason):
        return dict(data_updates=data_updates, data=data, reason=reason)


class OldFlow:
    def async_update_reload_and_abort(self, entry, *, data=None, reason):
        return dict(data=data, reason=reason)


def test_reconfiguration_merges_entry_data_itself_only_on_old_releases():
    entry = SimpleNamespace(data={"address": "old", "paired": True})
    compat = load_compat()
    assert compat.async_update_reload_and_abort(Flow(), entry, {"address": "new"}, "done") == dict(
        data_updates={"address": "new"}, data=None, reason="done")
    assert compat.async_update_reload_and_abort(OldFlow(), entry, {"address": "new"}, "done") == dict(
        data={"address": "new", "paired": True}, reason="done")


class EntryWithEagerStart:
    def __init__(self):
        self.calls = []

    def async_create_background_task(self, hass, target, name, eager_start=True):
        target.close()
        self.calls.append((name, eager_start))


class EntryWithoutEagerStart:
    def __init__(self):
        self.calls = []

    def async_create_background_task(self, hass, target, name):
        target.close()
        self.calls.append(name)


async def idle():
    await asyncio.sleep(0)


def test_background_tasks_never_start_eagerly():
    compat = load_compat()
    recent, older = EntryWithEagerStart(), EntryWithoutEagerStart()
    compat.create_background_task(recent, None, idle(), "recent")
    compat.create_background_task(older, None, idle(), "older")
    assert recent.calls == [("recent", False)] and older.calls == ["older"]


def test_entries_without_background_tasks_get_them_cancelled_on_unload():
    compat = load_compat()

    class LegacyEntry:
        entry_id = "legacy"

        def __init__(self):
            self.unload = []

        def async_on_unload(self, callback):
            self.unload.append(callback)

    async def scenario():
        entry, hass = LegacyEntry(), SimpleNamespace(loop=asyncio.get_running_loop())
        finished = compat.create_background_task(entry, hass, idle(), "finished")
        waiting = [compat.create_background_task(entry, hass, asyncio.sleep(60), f"waiting-{n}")
                   for n in range(2)]
        await finished
        await asyncio.sleep(0)
        assert len(entry.unload) == 1, "one unload callback per entry, not per task"
        assert compat.LEGACY_BACKGROUND_TASKS["legacy"] == set(waiting)
        entry.unload[0]()
        await asyncio.gather(*waiting, return_exceptions=True)
        assert all(task.cancelled() for task in waiting)
        assert "legacy" not in compat.LEGACY_BACKGROUND_TASKS

    asyncio.run(scenario())


@pytest.mark.parametrize("version, frozen", [((2023, 12), False), ((2024, 1), True), ((2026, 9), True)])
def test_description_dataclasses_are_frozen_exactly_when_home_assistant_freezes_them(version, frozen):
    description = load_compat(version=version).description_dataclass(type("Item", (), {"__annotations__": {"key": str}}))
    assert description.__dataclass_params__.frozen is frozen
    assert [field.name for field in fields(description)] == ["key"]
    item = description(key="a")
    if frozen:
        with pytest.raises(FrozenInstanceError):
            item.key = "b"


def entity_class(compat, module):
    return type("Entity", (compat.EntityNameFallback,), {"__module__": module, "_attr_translation_key": "battery_percent"})


def test_entity_names_come_from_the_english_translation_before_name_translations_existed():
    entity = entity_class(load_compat(name_translations=False), "custom_components.ninebot_e_scooters.sensor")()
    assert entity.name == "Battery"
    assert entity_class(load_compat(name_translations=False), "custom_components.ninebot_e_scooters.lock")().name is None


def test_entity_names_are_left_to_home_assistant_once_it_translates_them():
    assert "name" not in vars(load_compat(name_translations=True).EntityNameFallback)


def test_timeouts_end_the_same_way_on_every_python_version():
    async def scenario():
        with pytest.raises(utilities.TIMEOUT_ERRORS):
            async with utilities.timeout(0.01):
                await asyncio.sleep(1)

    asyncio.run(scenario())
    assert utilities.UTC.utcoffset(None).total_seconds() == 0
