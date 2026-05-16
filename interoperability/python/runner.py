"""
LLP Reference Runner — Python implementation of LLP transport deframer.

Provides CRC16-CCITT (incremental), frame building (plain & stuffed),
and frame deframing (state machine with timeout).
Matches the C/Java reference implementations.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

POLY = 0x1021
INIT = 0xFFFF

_CRC_TABLE: List[int] = []
for i in range(256):
    crc = i << 8
    for _ in range(8):
        if crc & 0x8000:
            crc = ((crc << 1) ^ POLY) & 0xFFFF
        else:
            crc = (crc << 1) & 0xFFFF
    _CRC_TABLE.append(crc)


def crc16_update(crc: int, byte: int) -> int:
    idx = ((crc >> 8) ^ byte) & 0xFF
    return ((crc << 8) ^ _CRC_TABLE[idx]) & 0xFFFF


def crc16(data: bytes) -> int:
    c = INIT
    for b in data:
        c = crc16_update(c, b)
    return c


def make_frame(payload: bytes) -> bytes:
    header = bytes([0xAA, 0x55, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF])
    crc_val = crc16(header + payload)
    return header + payload + bytes([crc_val & 0xFF, (crc_val >> 8) & 0xFF])


def make_stuffed_frame(payload: bytes) -> bytes:
    header = bytes([0xAA, 0x55, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF])
    stuffed = bytearray()
    for b in payload:
        if b == 0xAA:
            stuffed.extend([0xAA, 0x00])
        else:
            stuffed.append(b)
    crc_val = crc16(header + payload)
    return header + bytes(stuffed) + bytes([crc_val & 0xFF, (crc_val >> 8) & 0xFF])


class ErrorCode(Enum):
    CHECKSUM = "CHECKSUM"
    TIMEOUT = "TIMEOUT"
    SYNC_ERROR = "SYNC_ERROR"
    PAYLOAD_LEN_INVALID = "PAYLOAD_LEN_INVALID"
    BUFFER_FULL = "BUFFER_FULL"
    LAYER_MALFORMED = "LAYER_MALFORMED"
    TRANSFORM_NO_HANDLER = "TRANSFORM_NO_HANDLER"


@dataclass
class FrameEvent:
    type: str
    payload_hex: Optional[str] = None
    error_code: Optional[str] = None


class Deframer:
    MAX_PAYLOAD = 1024 * 1024

    def __init__(self, timeout_ms: int = 2000, max_payload: int = MAX_PAYLOAD):
        self.timeout_ms = timeout_ms
        self.max_payload = max_payload
        self.state = "WAIT_MAGIC1"
        self.escape_pending = False
        self.payload_len = 0
        self.payload_idx = 0
        self._len_l = 0
        self.crc_calc = INIT
        self.crc_received = 0
        self.last_byte_time = 0.0
        self._payload = bytearray()
        self._events: List[FrameEvent] = []

    @property
    def events(self) -> List[FrameEvent]:
        return list(self._events)

    def _notify_frame(self, payload: bytes):
        ev = FrameEvent(type="FRAME", payload_hex=payload.hex().upper())
        self._events.append(ev)

    def _notify_error(self, code: str):
        ev = FrameEvent(type="ERROR", error_code=code)
        self._events.append(ev)

    def _reset(self):
        self.state = "WAIT_MAGIC1"
        self.payload_idx = 0
        self.crc_calc = INIT
        self.escape_pending = False

    def process_byte(self, b: int, current_time_ms: Optional[float] = None) -> None:
        if current_time_ms is None:
            current_time_ms = time.time() * 1000

        # Timeout check
        if self.state != "WAIT_MAGIC1":
            elapsed = current_time_ms - self.last_byte_time
            if elapsed > self.timeout_ms:
                self._reset()
                self._notify_error(ErrorCode.TIMEOUT.value)
                if b == 0xAA:
                    self.state = "WAIT_MAGIC2"
                self.last_byte_time = current_time_ms
                return

        self.last_byte_time = current_time_ms

        # Escape / byte unstuffing (only in payload-reading states)
        if self.state not in ("WAIT_MAGIC1", "WAIT_MAGIC2"):
            if self.escape_pending:
                self.escape_pending = False
                if b == 0x55:
                    self._notify_error(ErrorCode.SYNC_ERROR.value)
                    self.crc_calc = INIT
                    self.crc_calc = crc16_update(self.crc_calc, 0xAA)
                    self.crc_calc = crc16_update(self.crc_calc, 0x55)
                    self.state = "READ_LEN_L"
                    return
                elif b == 0x00:
                    b = 0xAA
                else:
                    self._reset()
                    self._notify_error(ErrorCode.SYNC_ERROR.value)
                    return
            elif b == 0xAA:
                self.escape_pending = True
                return

        # State machine
        if self.state == "WAIT_MAGIC1":
            if b == 0xAA:
                self.state = "WAIT_MAGIC2"

        elif self.state == "WAIT_MAGIC2":
            if b == 0x55:
                self.crc_calc = INIT
                self.crc_calc = crc16_update(self.crc_calc, 0xAA)
                self.crc_calc = crc16_update(self.crc_calc, 0x55)
                self.state = "READ_LEN_L"
            elif b == 0xAA:
                pass
            else:
                self.state = "WAIT_MAGIC1"

        elif self.state == "READ_LEN_L":
            self.crc_calc = crc16_update(self.crc_calc, b)
            self._len_l = b
            self.state = "READ_LEN_H"

        elif self.state == "READ_LEN_H":
            self.crc_calc = crc16_update(self.crc_calc, b)
            self.payload_len = self._len_l | (b << 8)
            if self.payload_len > self.max_payload:
                self._reset()
                self._notify_error(ErrorCode.PAYLOAD_LEN_INVALID.value)
                return
            self.payload_idx = 0
            self._payload = bytearray()
            self.state = "READ_CRC_L" if self.payload_len == 0 else "READ_PAYLOAD"

        elif self.state == "READ_PAYLOAD":
            self._payload.append(b)
            self.crc_calc = crc16_update(self.crc_calc, b)
            self.payload_idx += 1
            if self.payload_idx == self.payload_len:
                self.state = "READ_CRC_L"

        elif self.state == "READ_CRC_L":
            self.crc_received = b
            self.state = "READ_CRC_H"

        elif self.state == "READ_CRC_H":
            self.crc_received |= (b << 8)
            if self.crc_received != self.crc_calc:
                self._reset()
                self._notify_error(ErrorCode.CHECKSUM.value)
                return
            self._reset()
            self._notify_frame(bytes(self._payload))

    def process_bytes(self, data: bytes, current_time_ms: Optional[float] = None) -> None:
        for b in data:
            self.process_byte(b, current_time_ms)


# ── Layer chain traversal ─────────────────────────────────────────────


def traverse_layer_chain(raw_payload: bytes) -> tuple[bool, Optional[str], bytes]:
    """
    Walk a layer chain, returning (success, error_code, final_payload).

    Passthrough layers (0x01-0x7F):  skip metadata, continue.
    Transform layers (0x80-0xFE):    no handler → error TRANSFORM_NO_HANDLER.
    FinalNode (0x00):                stop, remainder is application payload.
    Unknown/reserved (0xFF):         skip (treat as passthrough).
    """
    pos = 0
    while pos < len(raw_payload):
        layer_id = raw_payload[pos]
        pos += 1

        if layer_id == 0x00:
            return True, None, raw_payload[pos:]

        if 0x80 <= layer_id <= 0xFE:
            return False, ErrorCode.TRANSFORM_NO_HANDLER.value, b""

        if layer_id == 0xFF or (0x01 <= layer_id <= 0x7F):
            if pos >= len(raw_payload):
                return False, ErrorCode.LAYER_MALFORMED.value, b""
            meta_len = raw_payload[pos]
            pos += 1
            if meta_len == 0xFF:
                if pos + 2 > len(raw_payload):
                    return False, ErrorCode.LAYER_MALFORMED.value, b""
                actual_len = (raw_payload[pos] << 8) | raw_payload[pos + 1]
                pos += 2
            else:
                actual_len = meta_len
            if pos + actual_len > len(raw_payload):
                return False, ErrorCode.LAYER_MALFORMED.value, b""
            pos += actual_len
        else:
            return False, ErrorCode.LAYER_MALFORMED.value, b""

    return False, ErrorCode.LAYER_MALFORMED.value, b""
