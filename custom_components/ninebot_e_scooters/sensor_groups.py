"""Optional sensor groups for values that rarely matter while the scooter is parked.

A parked scooter keeps reporting zero speed, the same temperatures and the same
firmware versions. Only the battery, odometer and range sensors are created by
default; everything else belongs to a group the user can tick during setup or
later in the integration options.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONF_SENSOR_GROUPS = "sensor_groups"

RIDING = "riding"
TEMPERATURES = "temperatures"
BATTERY_HEALTH = "battery_health"
DEVICE_INFO = "device_info"
STATUS_CODES = "status_codes"

# Also the order of the checkboxes in the setup and options forms.
OPTIONAL_SENSOR_GROUPS = (RIDING, TEMPERATURES, BATTERY_HEALTH, DEVICE_INFO, STATUS_CODES)


def selected_sensor_groups(options: Mapping[str, Any]) -> frozenset[str]:
    """Return the groups switched on in a form or in the entry options.

    Names of groups a later release might drop are ignored rather than trusted.
    """
    return frozenset(options.get(CONF_SENSOR_GROUPS) or ()).intersection(OPTIONAL_SENSOR_GROUPS)


def sensor_groups_option(options: Mapping[str, Any]) -> list[str]:
    """Store the selection in form order, so the options dialog shows it unchanged."""
    selected = selected_sensor_groups(options)
    return [group for group in OPTIONAL_SENSOR_GROUPS if group in selected]
