"""Config flow for the Ninebot E-Scooters integration."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Iterable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.storage import Store

from .helpers.compat import (
    ConfigFlowResult,
    async_request_active_scan,
    async_update_reload_and_abort,
    supports_progress_task,
)
from .const import (
    CONF_MODEL,
    CONF_PAIRING_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MODEL,
    REPORT_URL,
)
from .models.profiles import AUTO_MODEL, CONFIGURABLE_MODELS, identify_model
from .helpers.discovery import is_scooter_advertisement, needs_explicit_model
from .helpers.sensor_groups import (
    CONF_SENSOR_GROUPS,
    OPTIONAL_SENSOR_GROUPS,
    sensor_groups_option,
)
from .helpers.storage import restore, storage_key
from .helpers.utilities import parse_app_key
from .runtime.flow_pairing import PairingOutcome, async_attempt_pairing

_LOGGER = logging.getLogger(__name__)


def _device_name(service_info: Any) -> str:
    """Return the best available Bluetooth name."""
    return (
        getattr(service_info, "name", None)
        or getattr(service_info, "address", None)
        or "Xiaomi Scooter"
    )


def _is_supported(service_info: Any) -> bool:
    """Identify scooter names without matching every Nordic UART peripheral."""
    return is_scooter_advertisement(service_info)


def _sensor_groups_field(selected: Iterable[str]) -> dict[Any, Any]:
    """Checkbox list of the optional sensor groups, labelled by the translations."""
    return {
        vol.Optional(CONF_SENSOR_GROUPS, default=list(selected)): SelectSelector(
            SelectSelectorConfig(
                options=list(OPTIONAL_SENSOR_GROUPS),
                multiple=True,
                mode=SelectSelectorMode.LIST,
                translation_key=CONF_SENSOR_GROUPS,
            )
        )
    }


def _setup_fields(previous: Mapping[str, Any] | None = None) -> dict[Any, Any]:
    """Fields every setup form shares, prefilled with an earlier answer."""
    previous = previous or {}
    return {
        vol.Optional(CONF_MODEL, default=previous.get(CONF_MODEL, AUTO_MODEL)): vol.In(
            CONFIGURABLE_MODELS
        ),
        **_sensor_groups_field(sensor_groups_option(previous)),
    }


def _setup_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Entry options chosen in a setup form; unanswered fields keep their defaults."""
    return {
        CONF_MODEL: user_input.get(CONF_MODEL, AUTO_MODEL),
        CONF_SENSOR_GROUPS: sensor_groups_option(user_input),
    }


class NinebotScooterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Xiaomi Mi Scooter."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, Any] = {}
        self._discovery_address: str | None = None
        self._scan_error: str | None = None
        self._cached_model_labels: dict[str, str] = {}
        # Carries the device over from selection to the pairing step.
        self._pairing_context: dict[str, Any] | None = None
        self._pairing_task: asyncio.Task[PairingOutcome] | None = None
        self._pairing_outcome: PairingOutcome | None = None

    async def _async_model_label(self, address: str, name: str) -> str:
        """Show an identified model from saved telemetry without extra pairing."""
        address = address.upper()
        if address not in self._cached_model_labels:
            try:
                payload = await Store(
                    self.hass, 1, storage_key(address), private=True
                ).async_load()
                data, _last_read_at = restore(payload, address)
                identified = identify_model(data.serial, name) if data else None
                self._cached_model_labels[address] = (
                    identified.model if identified and identified.model else ""
                )
            except (OSError, TypeError, ValueError):
                self._cached_model_labels[address] = ""
        model = self._cached_model_labels[address]
        return f"{name} ({model})" if model else name

    async def _async_scan(self) -> dict[str, Any]:
        """Refresh HA's scanner cache without creating a second BLE scanner."""
        self._scan_error = None
        found = self._async_collect_discovered()
        if found:
            return found

        # Devices in an existing BLE connection may temporarily stop advertising,
        # so provoke an advertisement where Home Assistant offers an active scan.
        try:
            await async_request_active_scan(self.hass)
        except Exception as err:
            self._scan_error = str(err)
            _LOGGER.warning("Xiaomi scooter active scan failed: %s", err)

        for attempt in range(4):
            found = self._async_collect_discovered()
            if found:
                return found
            if attempt < 3:
                await asyncio.sleep(0.5)
        return {}

    def _async_collect_discovered(self) -> dict[str, Any]:
        """Collect devices from both the connectable and all-scanner caches."""
        configured_addresses = {
            address.upper() for address in self._async_current_ids(include_ignore=False)
        }
        found = dict(self._discovered_devices)

        # All scanner types may see an advertisement while only a subset
        # can establish a connection. Prefer the connectable advertisement.
        for connectable in (False, True):
            for service_info in bluetooth.async_discovered_service_info(
                self.hass, connectable=connectable
            ):
                address = service_info.address.upper()
                if address in configured_addresses or not _is_supported(service_info):
                    continue
                found[address] = service_info

        self._discovered_devices = found
        return found

    async def _async_create_entry_from_values(
        self, address: str, name: str, options: dict[str, Any], ble_device: Any,
    ) -> ConfigFlowResult:
        """Require a real pairing success, then save the scooter as a config entry."""
        if options[CONF_MODEL] == AUTO_MODEL and needs_explicit_model(name):
            return self._async_show_retry_scan_form(
                address, name, options, errors={CONF_MODEL: "model_required"}
            )
        self._pairing_context = {
            "address": address, "name": name, "options": options, "ble_device": ble_device,
        }
        return await self.async_step_pairing()

    def _async_show_retry_scan_form(
        self,
        address: str = "",
        name: str = "",
        previous: Mapping[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Offer a rescan, or the manual address and name as a last resort."""
        return self.async_show_form(
            step_id="retry_scan",
            data_schema=vol.Schema({
                vol.Optional("manual_address", default=address): str,
                vol.Optional("manual_name", default=name): str,
                **_setup_fields(previous),
            }),
            errors=errors or {},
            description_placeholders={"scan_error": self._scan_error or "-"},
        )

    async def _async_test_and_create_entry(
        self, address: str, options: dict[str, Any]
    ) -> ConfigFlowResult:
        """Pair with a device already found by HA Bluetooth before saving it.

        A connectable BLEDevice can disappear between the scan and the
        config-flow confirmation; a missing one aborts here rather than
        letting the pairing attempt fail with a confusing GATT error.
        """
        service_info = self._discovered_devices.get(address.upper())
        if service_info is None:
            return self.async_abort(reason="no_devices_found")
        name = _device_name(service_info)
        address = address.upper()
        # raise_on_progress=False: a concurrent discovery flow for the same
        # device must not abort this flow just for being in progress too.
        # _abort_if_unique_id_configured below still aborts gracefully if
        # that other flow finishes first and actually creates the entry.
        await self.async_set_unique_id(address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return await self._async_create_entry_from_values(address, name, options, service_info.device)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a discovered Xiaomi scooter by its broadcast Bluetooth name."""
        if user_input is not None:
            return await self._async_test_and_create_entry(
                user_input[CONF_ADDRESS], _setup_options(user_input)
            )

        devices = await self._async_scan()
        if not devices:
            # Unlike earlier releases, never abort setup just because the
            # advertisement cache is empty at one particular moment.
            return await self.async_step_retry_scan()

        choices = {
            address: f"{await self._async_model_label(address, _device_name(info))} ({address})"
            for address, info in devices.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In(choices),
                **_setup_fields(),
            }),
        )

    async def async_step_retry_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow a rescan or explicit Bluetooth address as a last resort."""
        errors: dict[str, str] = {}
        if user_input is not None:
            manual_address = str(user_input.get("manual_address") or "").strip().upper()
            manual_name = str(user_input.get("manual_name") or "").strip()
            if manual_address:
                if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", manual_address):
                    errors["manual_address"] = "invalid_address"
                elif not manual_name:
                    # BLE129 derives a crypto key from the advertised device name.
                    errors["manual_name"] = "name_required"
                else:
                    await self.async_set_unique_id(manual_address, raise_on_progress=False)
                    self._abort_if_unique_id_configured()
                    ble_device = bluetooth.async_ble_device_from_address(
                        self.hass, manual_address, connectable=True,
                    )
                    if ble_device is None:
                        errors["manual_address"] = "cannot_connect"
                    else:
                        return await self._async_create_entry_from_values(
                            manual_address, manual_name, _setup_options(user_input), ble_device,
                        )
            else:
                return await self.async_step_user()

        return self._async_show_retry_scan_form(previous=user_input, errors=errors)

    async def async_step_bluetooth(
        self,
        discovery_info: Any,
    ) -> ConfigFlowResult:
        """Handle automatic Bluetooth discovery."""
        if not _is_supported(discovery_info):
            return self.async_abort(reason="not_supported")

        # raise_on_progress=False: a manually started flow for the same
        # device may already be in progress (still scanning or showing its
        # form); claiming the unique ID must not abort it just for that.
        await self.async_set_unique_id(discovery_info.address, raise_on_progress=False)
        self._abort_if_unique_id_configured()

        self._discovered_devices[discovery_info.address] = discovery_info
        self._discovery_address = discovery_info.address

        self.context["title_placeholders"] = {
            "name": await self._async_model_label(discovery_info.address, _device_name(discovery_info)),
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm automatic Bluetooth discovery."""
        if user_input is None:
            return self.async_show_form(
                step_id="bluetooth_confirm",
                description_placeholders={**self.context["title_placeholders"], "report_url": REPORT_URL},
                data_schema=vol.Schema(_setup_fields()),
            )

        if self._discovery_address is None:
            return self.async_abort(reason="cannot_connect")

        return await self._async_test_and_create_entry(
            self._discovery_address, _setup_options(user_input)
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle reconfiguration by selecting a different scooter."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            address = user_input[CONF_ADDRESS]

            if address != entry.unique_id:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()

            service_info = self._discovered_devices.get(address)
            if service_info is None:
                return self.async_abort(reason="cannot_connect")

            # Older setup attempted ScooterCoordinator(...).async_test_gatt_connection()
            # before creating the entry, producing spurious cannot_connect errors.

            return async_update_reload_and_abort(
                self,
                entry,
                {
                    CONF_ADDRESS: address,
                    "bluetooth_name": _device_name(service_info),
                    # Pairing credentials belong to the previous physical scooter.
                    "app_key": secrets.token_hex(16),
                    "paired": False,
                },
                reason="reconfigured",
            )

        devices = await self._async_scan()
        choices = {
            address: await self._async_model_label(address, _device_name(info))
            for address, info in devices.items()
            if address != entry.data.get(CONF_ADDRESS)
        }

        if not choices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(choices),
                }
            ),
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Progress step: try every handshake in the background, in order.

        Tries the classic BLE129 handshake, then the newer MIoT elliptic one
        (see runtime/flow_pairing.py), on a connection of its own. The
        power-button dialog this integration already shows during pairing
        opens here too, since both reuse the same persistent-notification ID
        pattern pairing_dialog.js watches for. The entry is created either
        way once both have been tried; async_step_pairing_done decides
        whether it is created already paired or, as a last resort, the way
        setup always used to work: unpaired, to be paired on the next live
        advertisement.
        """
        context = self._pairing_context
        if context is None:
            return self.async_abort(reason="cannot_connect")

        if self._pairing_task is None:
            self._pairing_task = self.hass.async_create_task(
                async_attempt_pairing(self.hass, context["ble_device"], context["name"], self.flow_id),
                f"ninebot_e_scooters_config_flow_pairing_{self.flow_id}",
            )

        use_progress = supports_progress_task(self)
        if not self._pairing_task.done():
            if use_progress:
                return self.async_show_progress(
                    step_id="pairing", progress_action="pairing", progress_task=self._pairing_task,
                )
            # Before Home Assistant 2024.8, async_show_progress cannot poll a
            # task by itself; block this step on it directly instead. The
            # power-button dialog still opens the same way in the meantime.
            await self._pairing_task

        self._pairing_outcome = self._pairing_task.result()
        self._pairing_task = None
        if use_progress:
            return self.async_show_progress_done(next_step_id="pairing_done")
        return await self.async_step_pairing_done()

    async def async_step_pairing_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save the scooter once every handshake attempt has finished."""
        context = self._pairing_context
        outcome = self._pairing_outcome
        self._pairing_context = None
        self._pairing_outcome = None
        if outcome.protocol is not None:
            data: dict[str, Any] = {
                CONF_ADDRESS: context["address"],
                "bluetooth_name": context["name"],
                "app_key": outcome.app_key.hex(),
                "paired": True,
            }
            if outcome.protocol != "ble129":
                # No register map or entity exists yet for this protocol; the
                # coordinator checks this flag and raises a repair issue
                # instead of attempting a session it cannot decode (see
                # runtime/session.py).
                data["protocol"] = outcome.protocol
        else:
            # Neither handshake was confirmed. Add the scooter as a last
            # resort, unpaired, the way setup always used to work: the
            # existing runtime pairing (power-button prompt) retries on the
            # next live advertisement.
            _LOGGER.info(
                "Scooter config flow: no handshake was confirmed (%s); "
                "adding it unpaired, to pair on the next live advertisement",
                outcome.error,
            )
            data = {
                CONF_ADDRESS: context["address"],
                "bluetooth_name": context["name"],
                "app_key": secrets.token_hex(16),
                "paired": False,
            }
        self.context["title_placeholders"] = {"name": context["name"]}
        return self.async_create_entry(title=context["name"], data=data, options=context["options"])

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Return the options flow."""
        return NinebotScooterOptionsFlow(config_entry)


class NinebotScooterOptionsFlow(OptionsFlow):
    """Handle Xiaomi Mi Scooter options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Keep the entry privately: Home Assistant 2024.11+ owns `config_entry`."""
        self._entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage polling, model, optional sensor groups and a known pairing password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            chosen = {key: value for key, value in user_input.items() if key != CONF_PAIRING_PASSWORD}
            try:
                self._adopt_pairing_password(user_input.get(CONF_PAIRING_PASSWORD, ""))
            except ValueError:
                errors[CONF_PAIRING_PASSWORD] = "invalid_pairing_password"
            else:
                return self.async_create_entry(
                    data={**chosen, CONF_SENSOR_GROUPS: sensor_groups_option(chosen)}
                )

        options = {**self._entry.options, **(user_input or {})}
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=options.get(
                            CONF_POLL_INTERVAL,
                            DEFAULT_POLL_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_POLL_INTERVAL,
                            max=MAX_POLL_INTERVAL,
                        ),
                    ),
                    vol.Required(
                        CONF_MODEL,
                        default=options.get(CONF_MODEL, MODEL),
                    ): vol.In(CONFIGURABLE_MODELS),
                    **_sensor_groups_field(sensor_groups_option(options)),
                    vol.Optional(CONF_PAIRING_PASSWORD): str,
                }
            ),
        )

    def _adopt_pairing_password(self, entered: str) -> None:
        """Store a password the scooter already knows, so no new pairing replaces it.

        Raises ValueError unless the field is empty or holds 16 bytes as hex.
        """
        password = "".join(entered.split())
        if not password:
            return
        key = parse_app_key(password)
        self.hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, "app_key": key.hex(), "paired": True},
        )
