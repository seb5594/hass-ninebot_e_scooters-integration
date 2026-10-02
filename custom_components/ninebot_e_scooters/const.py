"""Constants for the Ninebot E-Scooters integration."""

from __future__ import annotations
from .protocols.constants import (
    NUS_SERVICE_UUID as NUS_SERVICE_UUID,
    NUS_TX_UUID as NUS_TX_UUID,
    NUS_RX_UUID as NUS_RX_UUID,
    NUS_WRITE_UUID as NUS_WRITE_UUID,
    NUS_NOTIFY_UUID as NUS_NOTIFY_UUID,
    AUTH_SERVICE_UUID as AUTH_SERVICE_UUID,
    AUTH_UPNP_UUID as AUTH_UPNP_UUID,
    AUTH_AVDTP_UUID as AUTH_AVDTP_UUID,
    MASTER_TO_MOTOR as MASTER_TO_MOTOR,
    MASTER_TO_BATTERY as MASTER_TO_BATTERY,
    MOTOR_TO_MASTER as MOTOR_TO_MASTER,
    BATTERY_TO_MASTER as BATTERY_TO_MASTER,
    READ as READ,
    WRITE as WRITE,
    ATTR_GENERAL_INFO as ATTR_GENERAL_INFO,
    ATTR_BMS_VERSION as ATTR_BMS_VERSION,
    ATTR_DISTANCE_LEFT as ATTR_DISTANCE_LEFT,
    ATTR_BATTERY_INFO as ATTR_BATTERY_INFO,
    ATTR_BATTERY_PERCENT as ATTR_BATTERY_PERCENT,
    ATTR_BATTERY_CURRENT as ATTR_BATTERY_CURRENT,
    ATTR_BATTERY_VOLTAGE as ATTR_BATTERY_VOLTAGE,
    ATTR_BATTERY_CELL_VOLTAGES as ATTR_BATTERY_CELL_VOLTAGES,
    ATTR_TRIP_INFO as ATTR_TRIP_INFO,
    ATTR_SPEED as ATTR_SPEED,
    ATTR_TRIP_DISTANCE as ATTR_TRIP_DISTANCE,
    ATTR_CRUISE as ATTR_CRUISE,
    ATTR_TAIL_LIGHT as ATTR_TAIL_LIGHT,
    ATTR_MOTOR_INFO as ATTR_MOTOR_INFO,
    ATTR_GET_LOCK as ATTR_GET_LOCK,
    ATTR_SET_LOCK as ATTR_SET_LOCK,
    ATTR_UNSET_LOCK as ATTR_UNSET_LOCK,
    ATTR_SUPPLEMENTARY as ATTR_SUPPLEMENTARY,
    ATTR_KERS as ATTR_KERS,
    CMD_GET_INFO as CMD_GET_INFO,
    CMD_SET_KEY as CMD_SET_KEY,
    CMD_AUTH as CMD_AUTH,
    CMD_LOGIN as CMD_LOGIN,
    CMD_SEND_DATA as CMD_SEND_DATA,
    CMD_SEND_DID as CMD_SEND_DID,
    CMD_SEND_KEY as CMD_SEND_KEY,
    CMD_SEND_INFO as CMD_SEND_INFO,
    RCV_RDY as RCV_RDY,
    RCV_OK as RCV_OK,
    RCV_AUTH_OK as RCV_AUTH_OK,
    RCV_AUTH_ERR as RCV_AUTH_ERR,
    RCV_LOGIN_OK as RCV_LOGIN_OK,
    RCV_LOGIN_ERR as RCV_LOGIN_ERR,
)

from homeassistant.const import Platform
from .models.profiles import AUTO_MODEL, PROFILES, UNVERIFIED

DOMAIN = "ninebot_e_scooters"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.LOCK,
    Platform.SELECT,
]

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 10
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 120

MODEL = "Mi Electric Scooter 1S"
MANUFACTURER = "Xiaomi"
CONF_MODEL = "model"
# Model names are labels for the shared legacy Xiaomi protocol, not proof of
# support for every dashboard firmware or every writable setting.
LEGACY_XIAOMI_MODELS = (
    MODEL, "Mi Electric Scooter", "Mi Electric Scooter Pro",
    "Mi Electric Scooter Pro 2", "Mi Electric Scooter Essential",
    "Mi Electric Scooter 3",
    "Automatisch",
)
REFERENCE_RANGE_KM = {MODEL: 30.0}
CONFIGURABLE_MODELS = (AUTO_MODEL,) + tuple(
    profile.name for profile in PROFILES if profile.protocol != UNVERIFIED
)
# Keep the former import name while existing config entries migrate.
LEGACY_XIAOMI_MODELS = CONFIGURABLE_MODELS
