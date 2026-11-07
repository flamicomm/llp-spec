#!/usr/bin/env python3
"""Generate (and self-check) the LLP wire-format 4.0.0 conformance vectors.

The vectors in ``vectors/`` are the contract between implementations. They are
produced with the vendored reference implementation (``reference/llp_v4.py``)
and then verified by the driver in ``interoperability/python/runner.py``: every
expectation in this file is written by hand and checked against the reference,
so a vector can never disagree with the implementation it documents.

Usage:
    python3 tools/build_vectors.py                 # write vectors/ + MANIFEST
    python3 tools/build_vectors.py --check         # verify what is on disk
    python3 tools/build_vectors.py --update-readme # rewrite the README table
    python3 tools/build_vectors.py --check-readme  # fail if the table drifted
    python3 tools/build_vectors.py --emit-c OUT.h  # C fixture for the C suite
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reference"))
sys.path.insert(0, str(ROOT / "interoperability" / "python"))

import llp_v4 as llp  # noqa: E402
import runner  # noqa: E402

SPEC = "llp/4.0.0"
SCHEMA_VERSION = "2.0.0"
TIMEOUT_MS = llp.DEFAULT_TIMEOUT_MS
CAPACITY = llp.MAX_PAYLOAD
OUT_DIR = ROOT / "vectors"
MANIFEST = OUT_DIR / "MANIFEST.sha256"
README = ROOT / "README.md"

# Profile R1 channels (docs/RELIABILITY.md).
REL_CH_COMMAND = 1
REL_CH_ACK = 2
REL_CH_HELLO = 3

TABLE_BEGIN = "<!-- LLP-VECTORS-TABLE:BEGIN -->"
TABLE_END = "<!-- LLP-VECTORS-TABLE:END -->"

# Wire error codes, as required by the C fixture (must match include/llp_v4.h).
ERROR_CODES = {
    llp.ERR_CRC: 1,
    llp.ERR_LEN: 2,
    llp.ERR_TIMEOUT: 3,
    llp.ERR_SYNC: 4,
}


# --------------------------------------------------------------------------
# Case builders
# --------------------------------------------------------------------------
def encode_case(
    case_id: str,
    channel: int,
    payload: bytes,
    *,
    result: str = "valid",
    flags: tuple[str, ...] = (),
    note: str = "",
) -> dict:
    case = {
        "id": case_id,
        "kind": "encode",
        "result": result,
        "flags": list(flags),
        "channel": channel,
        "payload": payload.hex(),
        "frame": llp.encode(channel, payload).hex(),
    }
    if note:
        case["note"] = note
    return case


def decode_case(
    case_id: str,
    frame: bytes | None,
    *,
    frames: list[tuple[int, bytes]] | None = None,
    errors: list[str] | None = None,
    timeouts: int = 0,
    capacity: int = CAPACITY,
    timeout_ms: int = TIMEOUT_MS,
    feed: list[tuple[int, int]] | None = None,
    result: str = "valid",
    flags: tuple[str, ...] = (),
    note: str = "",
) -> dict:
    case = {
        "id": case_id,
        "kind": "decode",
        "result": result,
        "flags": list(flags),
        "capacity": capacity,
        "timeout_ms": timeout_ms,
        "expect": {
            "frames": [{"channel": ch, "payload": pl.hex()} for ch, pl in (frames or [])],
            "errors": list(errors or []),
            "timeouts": timeouts,
        },
    }
    if feed is not None:
        case["feed"] = [{"hex": f"{byte:02x}", "dt_ms": dt} for byte, dt in feed]
    else:
        case["frame"] = (frame or b"").hex()
    if note:
        case["note"] = note
    return case


def stream_case(
    case_id: str,
    chunks: list[bytes],
    *,
    frames: list[tuple[int, bytes]] | None = None,
    errors: list[str] | None = None,
    capacity: int = CAPACITY,
    timeout_ms: int = TIMEOUT_MS,
    result: str = "valid",
    flags: tuple[str, ...] = (),
    note: str = "",
) -> dict:
    case = {
        "id": case_id,
        "kind": "stream",
        "result": result,
        "flags": list(flags),
        "capacity": capacity,
        "timeout_ms": timeout_ms,
        "chunks": [chunk.hex() for chunk in chunks],
        "expect": {
            "frames": [{"channel": ch, "payload": pl.hex()} for ch, pl in (frames or [])],
            "errors": list(errors or []),
            "timeouts": 0,
        },
    }
    if note:
        case["note"] = note
    return case


def gaps(frame: bytes, at: dict[int, int]) -> list[tuple[int, int]]:
    """Expand a frame into (byte, dt_ms) steps, adding a gap before given offsets."""
    return [(byte, at.get(index, 0)) for index, byte in enumerate(frame)]


# --------------------------------------------------------------------------
# Payload table (carried over from the v3 corpus, re-expressed as opaque bytes)
# --------------------------------------------------------------------------
PAYLOADS: list[tuple[str, bytes, str]] = [
    ("empty", b"", "empty payload"),
    ("single-42", b"\x42", "one byte 0x42"),
    ("hello", b"Hello", "5-byte ASCII 'Hello'"),
    ("null-byte", b"\x00", "payload is a single 0x00"),
    ("ff-byte", b"\xff", "payload is a single 0xFF"),
    ("aa-byte", b"\xaa", "single 0xAA — the payload byte must be stuffed"),
    ("aa55", b"\xaa\x55", "0xAA 0x55 inside the payload must not look like a magic"),
    ("triple-aa", b"\xaa\xaa\xaa", "three consecutive 0xAA"),
    ("mixed-aa", b"\x01\xaa\x02\xaa\x03", "scattered 0xAA between normal bytes"),
    ("zeros-16", b"\x00" * 16, "16 zero bytes"),
    ("ones-16", b"\x01" * 16, "16 bytes of 0x01"),
    ("incremental-16", bytes(range(0x00, 0x10)), "16 sequential bytes 00..0f"),
    ("all-ff-16", b"\xff" * 16, "16 bytes of 0xFF"),
    ("aa-prefix", b"\xaa\x42", "0xAA as the first payload byte"),
    ("aa-suffix", b"\x42\xaa", "0xAA as the last payload byte, right before the CRC"),
    ("aa-boundary", b"\xaa\xaa\x00\xaa", "0xAA runs around an 0x00 byte"),
    ("aa00-alternating", b"\xaa\x00\xaa\x00\xaa", "alternating 0xAA / 0x00"),
    (
        "seq-32",
        bytes(range(0x20)),
        "32 sequential bytes 00..1f",
    ),
    ("byte-55", b"\x55", "single 0x55 — the second magic byte as data"),
    ("byte-7f", b"\x7f", "single 0x7F"),
    ("byte-80", b"\x80", "single 0x80"),
    ("byte-fe", b"\xfe", "single 0xFE"),
    ("ascii-test", b"Test", "4-byte ASCII 'Test'"),
    ("ascii-fox", b"The quick brown fox", "20-byte ASCII sentence"),
    ("eight-bytes", bytes(range(8)), "8 sequential bytes"),
    ("fifteen-null", b"\x00" * 15, "15 zero bytes"),
    ("thirty-null", b"\x00" * 30, "30 zero bytes"),
    ("seq-64", bytes(range(0x40)), "64 sequential bytes 00..3f"),
    ("repeated-55", b"\x55" * 8, "8 bytes of 0x55"),
    ("aa-55-pairs", b"\xaa\x55" * 3, "alternating 0xAA 0x55 pairs"),
    ("mixed-55-aa", b"\x55\xaa" * 4, "alternating 0x55 0xAA pattern"),
    ("double-zero", b"\x00\x00", "two consecutive 0x00"),
    ("ten-a", b"A" * 10, "10 bytes of ASCII 'A'"),
]


# --------------------------------------------------------------------------
# Vector sets
# --------------------------------------------------------------------------
def build_encode_vectors() -> list[dict]:
    cases = [
        encode_case(
            f"enc-{slug}", 0, payload, note=description
        )
        for slug, payload, description in PAYLOADS
    ]

    # A payload whose CRC contains a 0xAA byte, so a CRC byte gets stuffed.
    crc_stuff_payload = b""
    for length in range(1, 200):
        for value in range(256):
            candidate = bytes([value]) * length
            body = bytes([length, 0]) + candidate
            crc = llp.crc16(body, llp._crc_seed())
            if (crc & 0xFF) == 0xAA or (crc >> 8) == 0xAA:
                crc_stuff_payload = candidate
                break
        if crc_stuff_payload:
            break

    cases += [
        encode_case("enc-text-ok", 0, b"ok\n"),
        encode_case("enc-command-channel-1", 1, b"G1 X10\n"),
        encode_case(
            "enc-len-field-stuffed",
            0,
            b"x" * 170,
            note="LEN = 170 = 0xAA, so the LEN field itself must be stuffed",
        ),
        encode_case(
            "enc-crc-field-stuffed",
            0,
            crc_stuff_payload,
            note="a CRC byte is 0xAA, so the CRC field must be stuffed",
        ),
        encode_case(
            "enc-max-payload-255",
            7,
            b"\x00\xff" * 127 + b"\x00",
            note="maximum payload: LEN = 255, channel 7",
        ),
        encode_case(
            "enc-max-payload-all-aa",
            0,
            b"\xaa" * 255,
            note="worst case: 255 bytes of 0xAA, every payload byte doubles on the wire",
        ),
    ]
    return cases


def build_decode_vectors() -> list[dict]:
    cases = [
        decode_case(
            f"dec-{slug}",
            llp.encode(0, payload),
            frames=[(0, payload)],
            note=description,
        )
        for slug, payload, description in PAYLOADS
    ]

    a = llp.encode(0, b"ok\n")
    b = llp.encode(1, b"G1 X10\n")

    cases += [
        decode_case(
            "dec-two-frames-back-to-back",
            a + b,
            frames=[(0, b"ok\n"), (1, b"G1 X10\n")],
        ),
        decode_case(
            "dec-garbage-before-magic",
            b"\x00\xff\xaa\x13\xaa\xaa" + a,
            frames=[(0, b"ok\n")],
            note="garbage while waiting for the magic is ignored, never reported",
        ),
        decode_case(
            "dec-aa-aa-55-is-a-frame-start",
            b"\xaa\xaa" + a[1:],
            frames=[(0, b"ok\n")],
            note="the second 0xAA is not treated as an escape",
        ),
        decode_case(
            "dec-aa-00-in-wait-magic2",
            b"\xaa\x00" + a,
            frames=[(0, b"ok\n")],
            note="0xAA 0x00 before the magic reports nothing",
        ),
        decode_case(
            "dec-resync-discards-partial-frame",
            a[:6] + b,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
            note="a new magic inside a frame aborts it and starts over",
        ),
        decode_case(
            "dec-bad-escape-recovers",
            b"\xaa\x55\x03\x00\xaa\x42" + a,
            frames=[(0, b"ok\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
            note="0xAA followed by anything but 0x00/0x55 is a sync error",
        ),
        decode_case(
            "dec-truncated-tail-delivers-nothing",
            b"\xaa\x55\x03\x00\x6f\x6b",
            frames=[],
            note="incomplete tail with no following byte: nothing is delivered",
        ),
        decode_case(
            "dec-two-frames-max-payload",
            llp.encode(3, b"\xaa" * 255) + llp.encode(4, b"\x00" * 255),
            frames=[(3, b"\xaa" * 255), (4, b"\x00" * 255)],
            note="maximum payload in both stuffing directions",
        ),
        decode_case(
            "dec-len-exactly-at-capacity",
            llp.encode(0, b"z" * 64),
            frames=[(0, b"z" * 64)],
            capacity=64,
            note="LEN == capacity is accepted; only LEN > capacity is an error",
        ),
        decode_case(
            "dec-channel-255",
            llp.encode(255, b"x"),
            frames=[(255, b"x")],
        ),
        decode_case(
            "dec-channel-0xaa",
            llp.encode(0xAA, b"hi"),
            frames=[(0xAA, b"hi")],
            note="the CHANNEL field itself is stuffed",
        ),
        decode_case(
            "dec-payload-magic-escaped",
            llp.encode(0, b"\xaa\x55"),
            frames=[(0, b"\xaa\x55")],
            note="escaped magic inside the payload must not trigger a resync",
        ),
    ]
    return cases


def build_error_vectors() -> list[dict]:
    good = llp.encode(1, b"G1 X10\n")
    a = llp.encode(0, b"ok\n")

    def corrupt(frame: bytes, index: int, delta: int = 0xFF) -> bytes:
        out = bytearray(frame)
        out[index] ^= delta
        return bytes(out)

    # LEN tampered but the frame length kept consistent: insert a byte and bump LEN.
    len_tampered = a[:2] + bytes([a[2] + 1]) + a[3:7] + b"\x00" + a[7:]

    return [
        decode_case(
            "err-crc-payload-corrupted",
            corrupt(a, 5) + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_CRC],
            result="invalid",
            note="one payload bit flipped; the frame is discarded and the next one works",
        ),
        decode_case(
            "err-crc-low-byte",
            a[:-2] + bytes([a[-2] ^ 0xFF, a[-1]]),
            frames=[],
            errors=[llp.ERR_CRC],
            result="invalid",
        ),
        decode_case(
            "err-crc-high-byte",
            a[:-1] + bytes([a[-1] ^ 0xFF]),
            frames=[],
            errors=[llp.ERR_CRC],
            result="invalid",
        ),
        decode_case(
            "err-crc-all-zeros",
            a[:-2] + b"\x00\x00",
            frames=[],
            errors=[llp.ERR_CRC],
            result="invalid",
        ),
        decode_case(
            "err-crc-len-tampered",
            len_tampered,
            frames=[],
            errors=[llp.ERR_CRC],
            result="invalid",
            note="LEN changed and padded so the frame stays complete: the CRC catches it",
        ),
        decode_case(
            "err-crc-channel-tampered",
            a[:3] + bytes([a[3] ^ 0x01]) + a[4:],
            frames=[],
            errors=[llp.ERR_CRC],
            result="invalid",
            note="the CRC covers CHANNEL, so a rerouted frame is rejected",
        ),
        decode_case(
            "err-len-over-capacity-64",
            llp.encode(0, b"x" * 100) + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_LEN],
            capacity=64,
            result="invalid",
            note="LEN > capacity is rejected as soon as LEN is read",
        ),
        decode_case(
            "err-len-over-capacity-4",
            llp.encode(0, b"abcde"),
            frames=[],
            errors=[llp.ERR_LEN],
            capacity=4,
            result="invalid",
        ),
        decode_case(
            "err-len-over-capacity-0",
            llp.encode(0, b"x"),
            frames=[],
            errors=[llp.ERR_LEN],
            capacity=0,
            result="invalid",
            note="a zero-capacity parser rejects every non-empty frame",
        ),
        decode_case(
            "err-len-rejected-before-payload-stored",
            llp.encode(0, b"A" * 200) + llp.encode(1, b"ab"),
            frames=[(1, b"ab")],
            errors=[llp.ERR_LEN],
            capacity=4,
            result="invalid",
            note="no payload byte is stored before the length is validated",
        ),
        decode_case(
            "err-bad-escape-01",
            b"\xaa\x55\x03\x00\xaa\x01" + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
        ),
        decode_case(
            "err-bad-escape-ff",
            b"\xaa\x55\x03\x00\xaa\xff" + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
        ),
        decode_case(
            "err-resync-magic-in-len-state",
            b"\xaa\x55" + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
            note="a magic where LEN was expected aborts the frame and starts a new one",
        ),
        decode_case(
            "err-resync-magic-in-crc-state",
            a[:-1] + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
            note="a magic where CRC_H was expected resynchronises instead of corrupting",
        ),
        decode_case(
            "err-truncated-then-new-frame",
            b"\xaa\x55\x40\x00\x6f" + good,
            frames=[(1, b"G1 X10\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
            note="an incomplete frame with LEN=64 meets a new magic: resync",
        ),
    ]


def build_timing_vectors() -> list[dict]:
    hello = llp.encode(0, b"hello")
    after = llp.encode(1, b"after-timeout")

    # 16-bit wrap: reach t=65530 in WAIT_MAGIC1 (no timeout is possible there),
    # then feed a frame byte by byte so the clock crosses 65536 mid-frame.
    wrap_base = 65530
    wrap_steps = [(0x00, wrap_base)] + [(byte, 1) for byte in hello]
    wrap_late = [(0x00, wrap_base)] + [
        (byte, TIMEOUT_MS + 1 if index == 5 else 1) for index, byte in enumerate(hello)
    ]

    return [
        decode_case(
            "timeout-mid-frame",
            None,
            feed=gaps(hello, {4: TIMEOUT_MS + 100}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
            note="a gap greater than timeout_ms in the middle of a frame resets the parser",
        ),
        decode_case(
            "timeout-exactly-at-limit-is-ok",
            None,
            feed=gaps(hello, {3: TIMEOUT_MS}),
            frames=[(0, b"hello")],
            note="the rule is strictly greater than timeout_ms",
        ),
        decode_case(
            "timeout-limit-plus-one-fails",
            None,
            feed=gaps(hello, {3: TIMEOUT_MS + 1}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
        ),
        decode_case(
            "timeout-idle-before-magic-is-silent",
            None,
            feed=gaps(hello, {0: 5 * TIMEOUT_MS}),
            frames=[(0, b"hello")],
            note="no timeout is reported while waiting for the magic",
        ),
        decode_case(
            "timeout-between-frames-is-silent",
            None,
            feed=gaps(hello + after, {len(hello): 3 * TIMEOUT_MS}),
            frames=[(0, b"hello"), (1, b"after-timeout")],
            note="between frames the parser is in WAIT_MAGIC1, so no error",
        ),
        decode_case(
            "timeout-then-byte-re-examined-as-magic",
            None,
            feed=gaps(b"\xaa\x55\x05\x00\x68" + after, {5: TIMEOUT_MS + 1}),
            frames=[(1, b"after-timeout")],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
            note="the byte after the gap is re-examined as a possible magic",
        ),
        decode_case(
            "timeout-at-len-state",
            None,
            feed=gaps(hello, {2: TIMEOUT_MS + 1}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
        ),
        decode_case(
            "timeout-at-channel-state",
            None,
            feed=gaps(hello, {3: TIMEOUT_MS + 1}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
        ),
        decode_case(
            "timeout-at-crc-low-state",
            None,
            feed=gaps(hello, {len(hello) - 2: TIMEOUT_MS + 1}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
        ),
        decode_case(
            "timeout-at-crc-high-state",
            None,
            feed=gaps(hello, {len(hello) - 1: TIMEOUT_MS + 1}),
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
        ),
        decode_case(
            "timeout-16bit-wrap-is-not-a-timeout",
            None,
            feed=wrap_steps,
            frames=[(0, b"hello")],
            note="the timestamp wraps at 65536 mid-frame and the gap still compares correctly",
        ),
        decode_case(
            "timeout-16bit-wrap-detected",
            None,
            feed=wrap_late,
            frames=[],
            errors=[llp.ERR_TIMEOUT],
            timeouts=1,
            result="invalid",
            note="a gap across the wrap is measured correctly, not as a huge unsigned value",
        ),
    ]


def build_channel_vectors() -> list[dict]:
    payload = b"ping"
    cases = [
        encode_case(f"chan-enc-{channel}", channel, payload)
        for channel in (0, 1, 2, 3, 4, 239, 240, 255)
    ]
    cases += [
        encode_case(
            "chan-enc-0xaa-stuffed",
            0xAA,
            b"hi",
            note="CHANNEL = 0xAA, so the channel field itself is stuffed",
        ),
        decode_case(
            "chan-dec-1",
            llp.encode(1, payload),
            frames=[(1, payload)],
        ),
        decode_case(
            "chan-dec-240-reserved",
            llp.encode(240, payload),
            frames=[(240, payload)],
            note="240..255 is reserved for future LLP layers and must still be delivered",
        ),
        decode_case(
            "chan-dec-0xaa-stuffed",
            llp.encode(0xAA, payload),
            frames=[(0xAA, payload)],
        ),
        decode_case(
            "chan-same-payload-different-channels",
            llp.encode(2, payload) + llp.encode(3, payload),
            frames=[(2, payload), (3, payload)],
            note="routing is per frame; identical payloads stay distinguishable",
        ),
        stream_case(
            "chan-stream-split-between-frames",
            [
                llp.encode(1, b"cmd") + llp.encode(2, b"tel")[:3],
                llp.encode(2, b"tel")[3:],
            ],
            frames=[(1, b"cmd"), (2, b"tel")],
            note="chunk boundaries do not affect routing or frame order",
        ),
    ]
    return cases


def build_reliability_vectors() -> list[dict]:
    """Profile R1 (docs/RELIABILITY.md): command and ACK frame layouts."""
    command = b"\x00G1 X0\n"  # SEQ 0 + application bytes
    ack = b"\x07"
    cases = [
        encode_case(
            "rel-enc-command-seq0",
            REL_CH_COMMAND,
            command,
            note="R1 command frame: [SEQ][DATA] on channel 1",
        ),
        encode_case(
            "rel-enc-command-seq255",
            REL_CH_COMMAND,
            b"\xffG1 X0\n",
            note="SEQ wraps at 256; 255 is a valid value",
        ),
        encode_case(
            "rel-enc-command-seq-stuffed",
            REL_CH_COMMAND,
            b"\xaaG1 X0\n",
            note="SEQ = 0xAA is payload, so the seq byte itself is stuffed",
        ),
        encode_case(
            "rel-enc-ack-seq7",
            REL_CH_ACK,
            ack,
            note="R1 ACK frame: exactly one payload byte [SEQ] on channel 2",
        ),
        encode_case("rel-enc-ack-max", REL_CH_ACK, b"\xff"),
        encode_case(
            "rel-enc-hello-session",
            REL_CH_HELLO,
            b"\x2a",
            note="R1 session marker on channel 3: the receiver resets its dedup state",
        ),
        decode_case(
            "rel-dec-command",
            llp.encode(REL_CH_COMMAND, command),
            frames=[(REL_CH_COMMAND, command)],
        ),
        decode_case(
            "rel-dec-ack",
            llp.encode(REL_CH_ACK, ack),
            frames=[(REL_CH_ACK, ack)],
        ),
        decode_case(
            "rel-dec-command-then-ack",
            llp.encode(REL_CH_COMMAND, command) + llp.encode(REL_CH_ACK, ack),
            frames=[(REL_CH_COMMAND, command), (REL_CH_ACK, ack)],
            note="both profile channels interleaved in one stream; routing is per frame",
        ),
    ]
    return cases


def build_payload_vectors() -> list[dict]:
    """Payloads that would have been layer chains in v3 are opaque in v4."""
    table: list[tuple[str, bytes, str]] = [
        ("final-node", b"\x00", "0x00 used to mean FinalNode; now it is just data"),
        ("final-then-a", b"\x00A", "0x00 followed by application bytes"),
        ("passthrough-looking", b"\x01\x03\x10\x20\x30\x00Hello",
         "bytes shaped like a passthrough layer must be delivered verbatim"),
        ("transform-looking", b"\x80\x04\xde\xad\xbe\xef\x00OK",
         "bytes shaped like a transform layer must be delivered verbatim"),
        ("reserved-looking", b"\xff\x01\x00\x00data",
         "the 0xFF layer id has no meaning in v4"),
        ("max-passthrough-looking", b"\x7f\x02\xf0\x0f\x00xyz",
         "0x7F was the maximum passthrough id in v3"),
        ("max-transform-looking", b"\xfe\x01\xa5\x00\x01\x02\x03",
         "0xFE was the maximum transform id in v3"),
        ("truncated-metadata-looking", b"\x01\x0a\x10\x20\x30\x00Hello",
         "v3 reported LAYER_MALFORMED here; v4 delivers the bytes unchanged"),
        ("extended-metadata-looking", b"\x01\xff\x00Hello",
         "v3 reported LAYER_MALFORMED for a truncated extended metadata length"),
        ("lone-ff", b"\xff", "a single 0xFF byte"),
        ("lone-01", b"\x01", "a single 0x01 byte"),
        ("zero-then-magic", b"\x00\xaa\x55\x00\x55",
         "magic bytes after a leading 0x00 are still just payload"),
    ]

    cases: list[dict] = []
    for slug, payload, description in table:
        cases.append(encode_case(f"payload-enc-{slug}", 0, payload, note=description))
        cases.append(
            decode_case(
                f"payload-dec-{slug}",
                llp.encode(0, payload),
                frames=[(0, payload)],
                note=description,
            )
        )
    return cases


def build_stream_vectors() -> list[dict]:
    hello = llp.encode(0, b"ok\n")
    cmd = llp.encode(1, b"G1 X10\n")
    empty = llp.encode(0, b"")

    return [
        stream_case(
            "stream-byte-by-byte",
            [bytes([byte]) for byte in hello],
            frames=[(0, b"ok\n")],
            note="one byte per chunk",
        ),
        stream_case(
            "stream-two-byte-chunks",
            [hello[index:index + 2] for index in range(0, len(hello), 2)],
            frames=[(0, b"ok\n")],
        ),
        stream_case(
            "stream-split-after-magic1",
            [hello[:1], hello[1:]],
            frames=[(0, b"ok\n")],
        ),
        stream_case(
            "stream-split-after-len",
            [hello[:3], hello[3:]],
            frames=[(0, b"ok\n")],
        ),
        stream_case(
            "stream-split-mid-payload",
            [hello[:5], hello[5:]],
            frames=[(0, b"ok\n")],
        ),
        stream_case(
            "stream-split-after-crc-low",
            [hello[:-1], hello[-1:]],
            frames=[(0, b"ok\n")],
        ),
        stream_case(
            "stream-three-frames-mixed-channels",
            [empty, cmd, hello],
            frames=[(0, b""), (1, b"G1 X10\n"), (0, b"ok\n")],
        ),
        stream_case(
            "stream-noise-between-frames",
            [b"\xff\xff", hello, b"\xde\xad\x00", cmd],
            frames=[(0, b"ok\n"), (1, b"G1 X10\n")],
            note="noise in WAIT_MAGIC1 is ignored, never reported",
        ),
        stream_case(
            "stream-recovery-after-crc-error",
            [bytes([hello[0], hello[1], hello[2], hello[3], hello[4] ^ 0xFF]) + hello[5:], hello],
            frames=[(0, b"ok\n")],
            errors=[llp.ERR_CRC],
            result="invalid",
            note="after a CRC error the parser finds the next frame",
        ),
        stream_case(
            "stream-recovery-after-sync-error",
            [b"\xaa\x55\x03\x00\xaa\x99", hello],
            frames=[(0, b"ok\n")],
            errors=[llp.ERR_SYNC],
            result="invalid",
        ),
        stream_case(
            "stream-max-payload-split",
            [llp.encode(9, b"\xaa" * 255)[:40], llp.encode(9, b"\xaa" * 255)[40:]],
            frames=[(9, b"\xaa" * 255)],
        ),
        stream_case(
            "stream-garbage-before-first-frame",
            [b"\x00\x13\xaa\xaa", hello],
            frames=[(0, b"ok\n")],
        ),
    ]


VECTOR_SETS: dict[str, tuple[str, str, Callable[[], list[dict]]]] = {
    "encode.json": (
        "transport_encode",
        "Encoder conformance: (channel, payload) produces exact frame bytes.",
        build_encode_vectors,
    ),
    "decode.json": (
        "transport_decode",
        "Decoder conformance: byte streams produce the exact frames and no errors.",
        build_decode_vectors,
    ),
    "errors.json": (
        "transport_errors",
        "Error handling: CRC, length and sync errors, and recovery after them.",
        build_error_vectors,
    ),
    "timing.json": (
        "transport_timing",
        "Inter-byte timeout with injected time: gaps, boundary, recovery, 16-bit wrap.",
        build_timing_vectors,
    ),
    "channels.json": (
        "transport_channels",
        "Channel field: routing range, reserved range, and stuffing of the field itself.",
        build_channel_vectors,
    ),
    "reliability.json": (
        "profile_r1_reliability",
        "Profile R1 (optional): command/ACK frame layouts on channels 1 and 2.",
        build_reliability_vectors,
    ),
    "payload.json": (
        "transport_payload",
        "Opaque payload: bytes that look like v3 layer chains are delivered unchanged.",
        build_payload_vectors,
    ),
    "streams.json": (
        "parser_streams",
        "Incremental parsing: chunk boundaries, multi-frame streams and recovery.",
        build_stream_vectors,
    ),
}


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------
def document(name: str, cases: list[dict]) -> dict:
    category, description, _ = VECTOR_SETS[name]
    return {
        "spec": SPEC,
        "schema_version": SCHEMA_VERSION,
        "category": category,
        "description": description,
        "generated_by": "tools/build_vectors.py",
        "cases": cases,
    }


def serialise(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def manifest_text(files: dict[str, str]) -> str:
    lines = [
        "# sha256 of every file in vectors/, for consumers that vendor the corpus.",
        "# Regenerate with: python3 tools/build_vectors.py",
    ]
    for name in sorted(files):
        digest = sha256(files[name].encode("utf-8")).hexdigest()
        lines.append(f"{digest}  {name}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# README table
# --------------------------------------------------------------------------
def readme_table() -> str:
    rows = [
        "| File | Cases | Category | Covers |",
        "|---|---:|---|---|",
    ]
    total = 0
    for name, (category, description, builder) in VECTOR_SETS.items():
        count = len(builder())
        total += count
        rows.append(f"| `vectors/{name}` | {count} | `{category}` | {description} |")
    rows.append(f"| **Total** | **{total}** | | |")
    return "\n".join(rows)


def replace_table(text: str, table: str) -> str:
    start = text.find(TABLE_BEGIN)
    end = text.find(TABLE_END)
    if start == -1 or end == -1:
        raise SystemExit(f"error: README is missing the {TABLE_BEGIN} / {TABLE_END} markers")
    return text[: start + len(TABLE_BEGIN)] + "\n" + table + "\n" + text[end:]


# --------------------------------------------------------------------------
# C fixture (same shape as llp-protocol/test/v4_vectors_generated.h)
# --------------------------------------------------------------------------
def _c_bytes(name: str, data: bytes) -> list[str]:
    lines = [f"static const uint8_t {name}[] = {{"]
    for start in range(0, len(data), 16):
        chunk = ", ".join(f"0x{byte:02X}" for byte in data[start:start + 16])
        lines.append(f"    {chunk},")
    lines.append("};")
    return lines


def emit_c_header(path: Path) -> None:
    lines: list[str] = [
        "/* AUTO-GENERATED by tools/build_vectors.py --emit-c. Do not edit. */",
        f"/* Source: the corpus in vectors/ — wire format {SPEC} */",
        "#ifndef LLP4_VECTORS_GENERATED_H",
        "#define LLP4_VECTORS_GENERATED_H",
        "",
        "#include <stdint.h>",
        "",
        "typedef struct {",
        "    uint8_t byte;",
        "    uint16_t dt_ms;",
        "} llp4_vec_step_t;",
        "",
        "typedef struct {",
        "    uint8_t channel;",
        "    const uint8_t *payload;",
        "    uint8_t payload_len;",
        "} llp4_vec_frame_t;",
        "",
        "typedef struct {",
        "    const char *id;",
        "    uint8_t channel;",
        "    const uint8_t *payload;",
        "    uint8_t payload_len;",
        "    const uint8_t *frame;",
        "    uint16_t frame_len;",
        "} llp4_vec_encode_t;",
        "",
        "typedef struct {",
        "    const char *id;",
        "    uint8_t capacity;",
        "    uint16_t timeout_ms;",
        "    const llp4_vec_step_t *steps;",
        "    uint16_t step_count;",
        "    const llp4_vec_frame_t *frames;",
        "    uint8_t frame_count;",
        "    const uint8_t *errors;",
        "    uint8_t error_count;",
        "    uint8_t timeouts;",
        "} llp4_vec_decode_t;",
        "",
        "/* ---- data ---------------------------------------------------------- */",
        "",
    ]

    encode_cases = [
        case
        for case in (
            build_encode_vectors()
            + build_channel_vectors()
            + build_payload_vectors()
        )
        if case["kind"] == "encode"
    ]

    encode_rows: list[str] = []
    for index, case in enumerate(encode_cases):
        payload = bytes.fromhex(case["payload"])
        frame = bytes.fromhex(case["frame"])
        payload_ref = "NULL"
        if payload:
            lines.extend(_c_bytes(f"enc{index}_payload", payload))
            payload_ref = f"enc{index}_payload"
        lines.extend(_c_bytes(f"enc{index}_frame", frame))
        encode_rows.append(
            f'    {{"{case["id"]}", {case["channel"]}, {payload_ref}, '
            f'{len(payload)}, enc{index}_frame, {len(frame)}}},'
        )

    decode_rows: list[str] = []
    decode_cases = [
        case
        for case in (
            build_decode_vectors()
            + build_error_vectors()
            + build_timing_vectors()
            + build_channel_vectors()
            + build_payload_vectors()
            + build_stream_vectors()
        )
        if case["kind"] != "encode"
    ]

    for index, case in enumerate(decode_cases):
        if "feed" in case:
            pairs = [(int(step["hex"], 16), step["dt_ms"]) for step in case["feed"]]
        elif "chunks" in case:
            pairs = [
                (byte, 0) for chunk in case["chunks"] for byte in bytes.fromhex(chunk)
            ]
        else:
            pairs = [(byte, 0) for byte in bytes.fromhex(case["frame"])]

        lines.append(f"static const llp4_vec_step_t dec{index}_steps[] = {{")
        for byte, dt in pairs:
            lines.append(f"    {{0x{byte:02X}, {dt}}},")
        lines.append("};")

        frame_entries: list[str] = []
        for frame_index, entry in enumerate(case["expect"]["frames"]):
            payload = bytes.fromhex(entry["payload"])
            payload_ref = "NULL"
            if payload:
                lines.extend(_c_bytes(f"dec{index}_f{frame_index}", payload))
                payload_ref = f"dec{index}_f{frame_index}"
            frame_entries.append(
                f'    {{{entry["channel"]}, {payload_ref}, {len(payload)}}},'
            )

        frames_ref, frame_count = "NULL", 0
        if frame_entries:
            lines.append(f"static const llp4_vec_frame_t dec{index}_frames[] = {{")
            lines.extend(frame_entries)
            lines.append("};")
            frames_ref, frame_count = f"dec{index}_frames", len(frame_entries)

        errors = case["expect"]["errors"]
        errors_ref, error_count = "NULL", 0
        if errors:
            codes = "{" + ", ".join(str(ERROR_CODES[name]) for name in errors) + "}"
            lines.append(f"static const uint8_t dec{index}_errors[] = {codes};")
            errors_ref, error_count = f"dec{index}_errors", len(errors)

        decode_rows.append(
            f'    {{"{case["id"]}", {case["capacity"]}, {case["timeout_ms"]}, '
            f"dec{index}_steps, {len(pairs)}, "
            f'{frames_ref}, {frame_count}, {errors_ref}, {error_count}, '
            f'{case["expect"]["timeouts"]}}},'
        )

    lines.append("static const llp4_vec_encode_t llp4_vec_encode[] = {")
    lines.extend(encode_rows)
    lines.append("};")
    lines.append(
        "#define LLP4_VEC_ENCODE_COUNT "
        "(sizeof(llp4_vec_encode) / sizeof(llp4_vec_encode[0]))"
    )
    lines.append("")
    lines.append("static const llp4_vec_decode_t llp4_vec_decode[] = {")
    lines.extend(decode_rows)
    lines.append("};")
    lines.append(
        "#define LLP4_VEC_DECODE_COUNT "
        "(sizeof(llp4_vec_decode) / sizeof(llp4_vec_decode[0]))"
    )
    lines.append("")
    lines.append("#endif /* LLP4_VECTORS_GENERATED_H */")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote {path}: {len(encode_rows)} encode + {len(decode_rows)} decode cases"
    )


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------
def self_check(name: str, cases: list[dict]) -> int:
    failures = 0
    for case in cases:
        problems = runner.check(case)
        if problems:
            failures += 1
            print(f"FAIL {name}:{case['id']}")
            for problem in problems:
                print(f"     {problem}")
    return failures


def main() -> int:
    argv = sys.argv[1:]

    if "--emit-c" in argv:
        index = argv.index("--emit-c") + 1
        if index >= len(argv):
            print("usage: --emit-c <output header>")
            return 2
        emit_c_header(Path(argv[index]))
        return 0

    failures = 0
    for name, (_, _, builder) in VECTOR_SETS.items():
        cases = builder()
        failures += self_check(name, cases)
        if failures:
            print(f"\n{failures} case(s) failed self-check; nothing written")
            return 1

    total = sum(len(builder()) for _, (_, _, builder) in VECTOR_SETS.items())
    print(f"self-check OK: {total} cases match the reference implementation")

    if "--check-readme" in argv:
        current = README.read_text(encoding="utf-8")
        updated = replace_table(current, readme_table())
        if updated != current:
            print("FAIL  README vector table is stale")
            print("      run: python3 tools/build_vectors.py --update-readme")
            return 1
        print("ok    README vector table is up to date")
        if "--check" not in argv and "--update-readme" not in argv:
            return 0

    if "--check" in argv:
        stale = []
        files: dict[str, str] = {}
        for name, (_, _, builder) in VECTOR_SETS.items():
            expected = serialise(document(name, builder()))
            files[name] = expected
            path = OUT_DIR / name
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(name)
        expected_manifest = manifest_text(files)
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != expected_manifest:
            stale.append("MANIFEST.sha256")
        if stale:
            print(f"FAIL  out of date: {', '.join(stale)}")
            print("      run: python3 tools/build_vectors.py")
            return 1
        print("ok    vectors/ and MANIFEST.sha256 are up to date")
        return 0

    files = {}
    for name, (_, _, builder) in VECTOR_SETS.items():
        text = serialise(document(name, builder()))
        (OUT_DIR / name).write_text(text, encoding="utf-8")
        files[name] = text
        print(f"wrote vectors/{name} ({len(builder())} cases)")
    MANIFEST.write_text(manifest_text(files), encoding="utf-8")
    print("wrote vectors/MANIFEST.sha256")

    table = readme_table()
    text = README.read_text(encoding="utf-8")
    updated = replace_table(text, table)
    if "--update-readme" in argv:
        README.write_text(updated, encoding="utf-8")
        print("wrote README.md (vector table)")
    elif updated != text:
        print("note: README table is stale; run with --update-readme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
