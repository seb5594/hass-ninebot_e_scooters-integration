"""Fragmented UART reception, encrypted requests and response correlation."""

from __future__ import annotations
import asyncio
from dataclasses import replace
from bleak.exc import BleakError
from ..protocols.ninebot.packet import (
    CMD_INIT,
    CMD_PAIR,
    CMD_PING,
    CMD_READ,
    CMD_WRITE,
    CMD_WRITE_NO_REPLY,
    NinebotPacket,
)
from ..protocols.ninebot.packet import (
    DeviceId,
    ENCRYPTED_FRAME_OVERHEAD,
    FrameOffset,
    HEADER as NINEBOT_HEADER,
    LegacyM365Reply,
    PairingStatus,
)
from ..utilities import TIMEOUT_ERRORS, timeout as async_timeout
from .errors import ScooterConnectionError
from .constants import MAX_BLE129_BUFFER, MAX_BLE129_PAYLOAD
import logging

_LOGGER = logging.getLogger(__name__)


class RequestsMixin:
    """Requests operations on the coordinator session."""

    def _handle_notification(self, payload: bytes) -> None:
        """Accumulate BLE fragments and decode complete Ninebot frames."""
        if not payload:
            return
        self._last_notification = payload.hex()
        self._raw_notification_count += 1
        _LOGGER.debug("Scooter BLE <- encrypted fragment: length=%d", len(payload))
        self._rx_buffer.extend(payload)
        if len(self._rx_buffer) > MAX_BLE129_BUFFER:
            self._last_frame_issue = "receive_buffer_overflow"
            # Keep only a possible partial start marker; do not retain an
            # unbounded corrupt stream across 10-second polling cycles.
            self._rx_buffer[:] = NINEBOT_HEADER[:1] if self._rx_buffer[-1:] == NINEBOT_HEADER[:1] else b""
            return

        while True:
            if len(self._rx_buffer) < len(NINEBOT_HEADER):
                return
            if self._rx_buffer[:len(NINEBOT_HEADER)] != NINEBOT_HEADER:
                header = self._rx_buffer.find(NINEBOT_HEADER)
                if header < 0:
                    # A notification is an arbitrary ATT fragment. A header
                    # can be split exactly between 0x5A and 0xA5; never drop
                    # the terminal 0x5A as earlier versions did.
                    self._rx_buffer[:] = (
                        NINEBOT_HEADER[:1] if self._rx_buffer[-1:] == NINEBOT_HEADER[:1] else b""
                    )
                    self._last_frame_issue = "header_resync"
                    return
                del self._rx_buffer[:header]
                self._last_frame_issue = "header_resync"
            if len(self._rx_buffer) <= FrameOffset.LENGTH:
                return

            data_length = self._rx_buffer[FrameOffset.LENGTH]
            if data_length > MAX_BLE129_PAYLOAD:
                # The old 'length + 13 > 512' test was unreachable for a
                # one-byte length and could stall forever on a false header.
                self._last_frame_issue = "invalid_payload_length"
                del self._rx_buffer[:len(NINEBOT_HEADER)]
                continue
            encrypted_length = data_length + ENCRYPTED_FRAME_OVERHEAD
            if len(self._rx_buffer) < encrypted_length:
                return

            encrypted = bytes(self._rx_buffer[:encrypted_length])
            del self._rx_buffer[:encrypted_length]
            try:
                assert self._crypto is not None
                decrypted = self._crypto.decrypt(encrypted)
            except Exception:
                self._last_frame_issue = "decrypt_exception"
                _LOGGER.exception("Failed to decrypt Xiaomi BLE129 packet")
                continue
            if not decrypted:
                self._last_frame_issue = getattr(
                    self._crypto, "last_rejection_reason", None
                ) or "integrity_or_counter"
                self._last_rejected_frame_counter16 = int.from_bytes(encrypted[-2:], "big")
                self._rejected_crypto_frames += 1
                if self._rejected_crypto_frames <= 2 or self._rejected_crypto_frames % 10 == 0:
                    _LOGGER.warning(
                        "Scooter BLE rejected encrypted frame: reason=%s count=%d "
                        "local_counter=%s received_counter16=%s; key retained",
                        self._last_frame_issue, self._rejected_crypto_frames,
                        self._crypto.message_counter if self._crypto is not None else None,
                        self._last_rejected_frame_counter16,
                    )
                # If a spurious 5AA5 inside preceding noise was mistaken for
                # a frame header, its claimed length may have consumed the
                # beginning of the *real* next frame. Salvage that suffix;
                # otherwise the actual 0x5B acknowledgement is lost.
                nested_header = encrypted.find(NINEBOT_HEADER, len(NINEBOT_HEADER))
                if nested_header > 0:
                    self._rx_buffer[:0] = encrypted[nested_header:]
                    self._last_frame_issue = "integrity_realign"
                continue
            packet = NinebotPacket.unpack(decrypted)
            if packet is None:
                self._last_frame_issue = "invalid_decrypted_packet"
                _LOGGER.debug("Invalid decrypted Ninebot packet: length=%d", len(decrypted))
                continue
            self._last_frame_issue = None
            # Only log message metadata; payload may include serial/key material.
            self._last_reply_command = f"0x{packet.command:02X}/0x{packet.index:02X}"
            _LOGGER.info(
                "Scooter BLE received: src=0x%02X dst=0x%02X "
                "command=0x%02X argument=0x%02X payload_len=%d",
                packet.source, packet.target,
                packet.command, packet.index, len(packet.data),
            )
            if packet.source == DeviceId.DASHBOARD and packet.target == getattr(self, "_host_id", DeviceId.PHONE) and packet.index == PairingStatus.CONFIRMED:
                if packet.command == CMD_PING:
                    self._pending_pair_confirmation = packet
                elif packet.command == CMD_PAIR:
                    self._pending_pair_ack = packet
            if self._packet_queue.full():
                self._packet_queue.get_nowait()
            self._packet_queue.put_nowait(packet)

    async def _async_crypto_request(
        self,
        request: NinebotPacket,
        *,
        expected_commands: set[int],
        timeout: float,
        accept_timeout: bool = False,
        quiet_timeout: bool = False,
        encrypted_override: bytes | None = None,
    ) -> NinebotPacket | None:
        """Send one encrypted request and match its response without losing late ACKs.

        0x5C/0x5D pairing confirmations can arrive between the timeout of
        one request and the next transmission. Do not blindly drain the BLE
        response queue: a valid button confirmation would be discarded.
        """
        host_id = getattr(self, "_host_id", DeviceId.PHONE)
        if request.source != host_id:
            request = replace(request, source=host_id)
        if getattr(self, "_shutting_down", False):
            raise ScooterConnectionError("Scooter config entry is shutting down")
        if self._crypto is None or self._client is None or self._tx_char is None:
            raise ScooterConnectionError("BLE129 session is not initialized")
        crypto = self._crypto
        client = self._client
        packet_queue = self._packet_queue
        if not client.is_connected:
            raise ScooterConnectionError("Scooter GATT link was lost before BLE129 request")

        # An unsolicited button acknowledgement can arrive during a different
        # register request. Retain it until the matching handshake step.
        if request.command == CMD_PING and getattr(self, "_pending_pair_confirmation", None) is not None:
            packet = self._pending_pair_confirmation
            self._pending_pair_confirmation = None
            return packet
        if request.command == CMD_PAIR and getattr(self, "_pending_pair_ack", None) is not None:
            packet = self._pending_pair_ack
            self._pending_pair_ack = None
            return packet

        self._last_reply_command = None
        notifications_before_request = self._raw_notification_count

        def matches(packet: NinebotPacket) -> bool:
            if packet.command not in expected_commands:
                return False
            if request.command == CMD_READ:
                # Xiaomi scooters use 0x01 for register replies. Ninebot uses
                # 0x04. 5A A5 packets generally use source 0x20 for ESC and
                # 0x22 for BMS; 0x23/0x25 are legacy 55 AA response aliases.
                # Never accept a delayed reply to another register or one
                # addressed to another application.
                if packet.index != request.index or packet.target != request.source:
                    return False
                expected_sources = {
                    DeviceId.ESC: (DeviceId.ESC, LegacyM365Reply.ESC),
                    DeviceId.BMS: (DeviceId.BMS, LegacyM365Reply.BMS),
                }.get(request.target, (request.target,))
                return packet.source in expected_sources
            # The dashboard answers 0x5B/5C/5D from device 0x21 to phone
            # 0x3E. Do not misidentify a controller response as pairing ACK.
            return (packet.source == request.target and packet.target == request.source
                    # 0x02 and 0x03 are the two family write opcodes.
                    and (request.command not in (CMD_WRITE, CMD_WRITE_NO_REPLY)
                         or packet.index == request.index))

        # A late 0x5C01 may have already switched the crypto session key.
        # In that case DO NOT send another 0x5C; proceed directly to 0x5D.
        # The queue is fresh for every new BLE connection.
        if request.command in (CMD_INIT, CMD_PING, CMD_PAIR):
            while not packet_queue.empty():
                try:
                    packet = packet_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if packet is None:
                    raise ScooterConnectionError("Scooter GATT link was lost during pairing")
                if matches(packet) and (request.command == CMD_INIT or packet.index == PairingStatus.CONFIRMED):
                    _LOGGER.info(
                        "Scooter BLE accepted late reply: command=0x%02X",
                        packet.command,
                    )
                    if request.command == CMD_PING:
                        self._pending_pair_confirmation = None
                    elif request.command == CMD_PAIR:
                        self._pending_pair_ack = None
                    return packet
                if matches(packet) and packet.index == PairingStatus.PENDING:
                    _LOGGER.debug(
                        "Scooter BLE old pairing acknowledgement: command=0x%02X argument=0",
                        packet.command,
                    )

        # For other requests the queue remains intact. Non-matching packets
        # are ignored by the waiter, never preemptively destroyed by a flush.
        logical = request.pack()
        encrypted = encrypted_override if encrypted_override is not None else crypto.encrypt(logical)
        # 0x5C contains raw application key. Do not log the logical bytes.
        _LOGGER.info(
            "Scooter BLE sending: phase=%s command=0x%02X argument=0x%02X frame_len=%d",
            self._stage, request.command, request.index, len(encrypted),
        )
        await self._async_write_packet(encrypted)
        _LOGGER.info("Scooter BLE write completed: phase=%s", self._stage)
        if (self._client is not client or not client.is_connected
                or self._crypto is not crypto or self._packet_queue is not packet_queue):
            raise ScooterConnectionError("Scooter GATT link was lost during BLE129 write")

        try:
            async with async_timeout(timeout):
                while True:
                    packet = await packet_queue.get()
                    if (packet is None or self._client is not client
                            or not client.is_connected or self._crypto is not crypto
                            or self._packet_queue is not packet_queue):
                        raise ScooterConnectionError("Scooter GATT link was lost during BLE129 response")
                    if matches(packet):
                        if request.command == CMD_PING and packet.index == PairingStatus.CONFIRMED:
                            self._pending_pair_confirmation = None
                        elif request.command == CMD_PAIR and packet.index == PairingStatus.CONFIRMED:
                            self._pending_pair_ack = None
                        return packet
                    _LOGGER.debug(
                        "Scooter BLE ignoring unmatched response: src=0x%02X "
                        "dst=0x%02X command=0x%02X register=0x%02X "
                        "in phase %s",
                        packet.source, packet.target, packet.command,
                        packet.index, self._stage,
                    )
        except TIMEOUT_ERRORS as err:
            if (self._client is not client or not client.is_connected
                    or self._crypto is not crypto or self._packet_queue is not packet_queue):
                raise ScooterConnectionError(
                    "Scooter GATT link was lost during BLE129 response"
                ) from err
            # Unlike the previous diagnostic, these fields now describe this
            # particular request, not the entire Bluetooth connection.
            notification_received = self._raw_notification_count > notifications_before_request
            log_timeout = _LOGGER.debug if quiet_timeout else _LOGGER.warning
            log_timeout(
                "Scooter BLE response timeout: phase=%s command=0x%02X "
                "expected=%s last_decoded_reply=%s notification_during_request=%s "
                "crypto_counter=%s raw_notification_count=%d rejected_frames=%d "
                "last_frame_issue=%s rx_buffer_bytes=%d",
                self._stage, request.command, sorted(expected_commands),
                self._last_reply_command, notification_received,
                crypto.message_counter, self._raw_notification_count,
                self._rejected_crypto_frames, self._last_frame_issue,
                len(self._rx_buffer),
            )
            if accept_timeout:
                return None
            raise ScooterConnectionError(
                f"BLE response timeout in phase '{self._stage}' after "
                f"{timeout:.1f}s (command=0x{request.command:02X}, "
                f"expected={sorted(expected_commands)}, "
                f"notification_during_request={notification_received}, "
                f"crypto_counter={crypto.message_counter})"
            ) from err

    async def _async_write_packet(self, data: bytes) -> None:
        """Write a Ninebot encrypted frame in default-MTU-safe NUS chunks."""
        if self._client is None or self._tx_char is None or not self._client.is_connected:
            raise ScooterConnectionError("BLE write channel is disconnected")

        client = self._client
        tx_char = self._tx_char
        properties = set(tx_char.properties or ())
        supports_command = "write-without-response" in properties
        supports_request = "write" in properties
        if not supports_command and not supports_request:
            raise ScooterConnectionError(
                f"NUS write characteristic has no write capability: {sorted(properties)}"
            )

        # A 0x5C login frame is longer than the 20-byte ATT payload at MTU 23.
        # Earlier builds sent that frame in a single write, which can fail
        # with 'Failed to initiate write' on BlueZ and on Bluetooth proxies.
        # Use 20-byte chunks even if the negotiated MTU allows more.
        # Nordic UART uses write commands when advertised. Request writes on
        # this 1S return ATT error 0x0E while the socket is still connected.
        response_mode = not supports_command
        self._last_write_mode = "request" if response_mode else "command"
        for offset in range(0, len(data), 20):
            if self._client is not client or not client.is_connected:
                raise ScooterConnectionError(
                    f"Scooter GATT link was lost before NUS byte {offset}/{len(data)}"
                )
            chunk = data[offset: offset + 20]
            try:
                await client.write_gatt_char(
                    tx_char, chunk, response=response_mode
                )
            except BleakError as err:
                # Do not clear_cache() on a live connection: this invalidates
                # the exact service context the following write depends on.
                # Reconnect with cache disabled at the next poll instead.
                _LOGGER.warning(
                    "Scooter NUS write failed at offset=%s/%s mode=%s: %s",
                    offset, len(data), response_mode, err,
                )
                raise ScooterConnectionError(
                    f"NUS write failed at byte {offset}/{len(data)}: {err}"
                ) from err
            if offset + 20 < len(data):
                await asyncio.sleep(0.08)
