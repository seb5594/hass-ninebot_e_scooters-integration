"""Config flow for the Ninebot E-Scooters integration."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.storage import Store

from .compat import (
    ConfigFlowResult,
    async_request_active_scan,
    async_update_reload_and_abort,
)
from .const import (
    CONF_MODEL,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    LEGACY_XIAOMI_MODELS,
    MODEL,
)
from .models.profiles import AUTO_MODEL
from .models.profiles import identify_model
from .discovery import is_scooter_advertisement, needs_explicit_model
from .storage import restore, storage_key

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


class NinebotScooterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Xiaomi Mi Scooter."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, Any] = {}
        self._discovery_address: str | None = None
        self._scan_error: str | None = None
        self._cached_model_labels: dict[str, str] = {}

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

    def _async_create_entry_from_values(
        self, address: str, name: str, model: str = AUTO_MODEL
    ) -> ConfigFlowResult:
        """Save a discovered scooter without requiring a second BLE connection."""
        if model == AUTO_MODEL and needs_explicit_model(name):
            return self.async_show_form(
                step_id="retry_scan",
                data_schema=vol.Schema({
                    vol.Optional("manual_address", default=address): str,
                    vol.Optional("manual_name", default=name): str,
                    vol.Optional(CONF_MODEL, default=AUTO_MODEL): vol.In(LEGACY_XIAOMI_MODELS),
                }),
                errors={CONF_MODEL: "model_required"},
                description_placeholders={"scan_error": "-"},
            )
        self.context["title_placeholders"] = {"name": name}
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: address,
                "bluetooth_name": name,
                "app_key": secrets.token_hex(16),
            },
            options={CONF_MODEL: model},
        )

    async def _async_test_and_create_entry(
        self, address: str, model: str = AUTO_MODEL
    ) -> ConfigFlowResult:
        """Create a config entry for a device already found by HA Bluetooth."""
        service_info = self._discovered_devices.get(address.upper())
        if service_info is None:
            # The device has already been discovered by Home Assistant's
            # Bluetooth stack. Do not perform a second connection attempt here.
            # A connectable BLEDevice can disappear between the scan and the
            # config-flow confirmation; making setup depend on that lookup causes
            # false "cannot_connect" failures without even reaching the scooter.
            return self.async_abort(reason="no_devices_found")
        name = _device_name(service_info)
        address = address.upper()
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        return self._async_create_entry_from_values(address, name, model)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a discovered Xiaomi scooter by its broadcast Bluetooth name."""
        if user_input is not None:
            return await self._async_test_and_create_entry(
                user_input[CONF_ADDRESS], user_input.get(CONF_MODEL, AUTO_MODEL)
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
                vol.Optional(CONF_MODEL, default=AUTO_MODEL): vol.In(LEGACY_XIAOMI_MODELS),
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
                    await self.async_set_unique_id(manual_address)
                    self._abort_if_unique_id_configured()
                    return self._async_create_entry_from_values(
                        manual_address, manual_name, user_input.get(CONF_MODEL, AUTO_MODEL)
                    )
            else:
                return await self.async_step_user()

        return self.async_show_form(
            step_id="retry_scan",
            data_schema=vol.Schema(
                {
                    vol.Optional("manual_address", default=""): str,
                    vol.Optional("manual_name", default=""): str,
                    vol.Optional(CONF_MODEL, default=AUTO_MODEL): vol.In(LEGACY_XIAOMI_MODELS),
                }
            ),
            errors=errors,
            description_placeholders={"scan_error": self._scan_error or "-"},
        )

    async def async_step_bluetooth(
        self,
        discovery_info: Any,
    ) -> ConfigFlowResult:
        """Handle automatic Bluetooth discovery."""
        if not _is_supported(discovery_info):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
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
                description_placeholders=self.context["title_placeholders"],
                data_schema=vol.Schema({
                    vol.Optional(CONF_MODEL, default=AUTO_MODEL): vol.In(LEGACY_XIAOMI_MODELS),
                }),
            )

        if self._discovery_address is None:
            return self.async_abort(reason="cannot_connect")

        return await self._async_test_and_create_entry(
            self._discovery_address, user_input.get(CONF_MODEL, AUTO_MODEL)
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
                await self.async_set_unique_id(address)
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
        """Manage polling options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self._entry.options.get(
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
                        default=self._entry.options.get(CONF_MODEL, MODEL),
                    ): vol.In(LEGACY_XIAOMI_MODELS),
                }
            ),
        )
