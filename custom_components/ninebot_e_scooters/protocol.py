"""Compatibility imports; implementation lives in protocols.xiaomi."""

from .protocols.xiaomi import (
    HEADER as HEADER,
    LEGACY_FRAME_OVERHEAD as LEGACY_FRAME_OVERHEAD,
    LEGACY_MINIMUM_CONTENT_LENGTH as LEGACY_MINIMUM_CONTENT_LENGTH,
    LEGACY_MINIMUM_FRAME_LENGTH as LEGACY_MINIMUM_FRAME_LENGTH,
    LEGACY_MAXIMUM_FRAME_LENGTH as LEGACY_MAXIMUM_FRAME_LENGTH,
    LegacyFrameOffset as LegacyFrameOffset,
    ScooterCommand as ScooterCommand,
    ScooterMessage as ScooterMessage,
    ScooterData as ScooterData,
    _format_packed_version as _format_packed_version,
    make_read as make_read,
    make_write as make_write,
    standard_read_commands as standard_read_commands,
    tail_light_command as tail_light_command,
    parse_message as parse_message,
    PacketParser as PacketParser,
    _safe_temperature as _safe_temperature,
    decode_battery_manufacture_date as decode_battery_manufacture_date,
    apply_message as apply_message,
    merge_messages as merge_messages,
)
