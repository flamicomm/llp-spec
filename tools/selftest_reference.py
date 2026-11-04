#!/usr/bin/env python3
"""Self-test of the vendored reference implementation.

``check_vendor.py`` proves the file was not edited; this script proves the file
still implements what the specification says. It is cheap and runs everywhere:

- the CRC known-answer vector (``123456789`` -> ``0x29B1``);
- the five example frames printed in ``docs/SPEC-v4.md`` §3;
- the size table of §3 (``frame_size``);
- a round trip and a CRC rejection.

Usage:
    python3 tools/selftest_reference.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reference"))

import llp_v4 as llp  # noqa: E402

# (channel, payload, expected frame) — copied verbatim from docs/SPEC-v4.md §3.
SPEC_EXAMPLES = [
    (0, b"", "aa55000023b3"),
    (0, b"ok\n", "aa5503006f6b0a08db"),
    (1, b"G1 X10\n", "aa5507014731205831300ae427"),
    (0, bytes([0xAA, 0x55]), "aa550200aa0055d24a"),
    (0, bytes([0xAA]) * 8, "aa550800aa00aa00aa00aa00aa00aa00aa00aa00b6bb"),
]


def main() -> int:
    problems: list[str] = []

    crc = llp.crc16(b"123456789")
    if crc != 0x29B1:
        problems.append(f"CRC known-answer: got 0x{crc:04X}, want 0x29B1")

    for channel, payload, expected in SPEC_EXAMPLES:
        got = llp.encode(channel, payload).hex()
        if got != expected:
            problems.append(
                f"spec example (channel {channel}, payload {payload.hex() or '-'}): "
                f"got {got}, want {expected}"
            )

    # frame_size() is the worst case (every byte after the magic stuffed), not
    # the minimum: 2 + 2*(LEN + CHANNEL + payload) + 2*CRC = 10 + 2n.
    if llp.frame_size(0) != 10:
        problems.append(f"frame_size(0) = {llp.frame_size(0)}, want 10 (worst case)")
    if llp.frame_size(255) != 10 + 2 * 255:
        problems.append(f"frame_size(255) = {llp.frame_size(255)}, want {10 + 2 * 255}")

    # Round trip.
    frame = llp.encode(7, b"hello")
    parser = llp.Parser()
    events = []
    for byte in frame:
        events.extend(parser.feed(byte, 0))
    if events != [("frame", 7, b"hello")]:
        problems.append(f"round trip: got {events}")

    # A flipped CRC byte must be rejected.
    bad = bytearray(frame)
    bad[-1] ^= 0xFF
    parser = llp.Parser()
    events = []
    for byte in bad:
        events.extend(parser.feed(byte, 0))
    if events != [("error", llp.ERR_CRC)]:
        problems.append(f"CRC rejection: got {events}")

    for problem in problems:
        print(f"FAIL  {problem}")
    if problems:
        return 1

    print("ok    reference implementation matches docs/SPEC-v4.md §3 and §4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
