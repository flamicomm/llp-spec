#!/usr/bin/env python3
"""Generate the AFL/libFuzzer seed corpus in ``fuzz-seeds/``.

The corpus is deterministic: every seed comes from the curated table below, the
frames are built with the reference encoder, and ``--check`` fails if the files
on disk differ from what this script produces (including leftover files from a
previous layout).

The seeds are deliberately small and mutually distinct. They are *not* a dump of
``vectors/``: a fuzzer wants boundary-hitting inputs, not coverage duplicates.
The three stuffing sites of the header (LEN, CHANNEL, CRC) each get their own
seed, because those are the three places where a single byte can change the frame
length.

Usage:
    python3 tools/generate_fuzz_seeds.py           # write fuzz-seeds/
    python3 tools/generate_fuzz_seeds.py --check   # fail if they are stale
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reference"))

import llp_v4 as llp  # noqa: E402

SEEDS_DIR = ROOT / "fuzz-seeds"


def _crc_stuffing_payload() -> bytes:
    """Smallest repeated-byte payload whose CRC contains a 0xAA byte."""
    for length in range(1, 200):
        for value in range(256):
            candidate = bytes([value]) * length
            body = bytes([length, 0]) + candidate
            crc = llp.crc16(body, llp._crc_seed())
            if (crc & 0xFF) == 0xAA or (crc >> 8) == 0xAA:
                return candidate
    raise SystemExit("error: no CRC-stuffing payload found")


def seeds() -> dict[str, bytes]:
    empty = llp.encode(0, b"")
    hello = llp.encode(0, b"hello")
    aa_frame = llp.encode(0, b"\xaa")

    crc_error = bytearray(empty)
    crc_error[-1] ^= 0xFF

    seeds: dict[str, bytes] = {}

    # ── empty: minimal valid frames ────────────────────────────────────────
    seeds["empty/empty_frame.bin"] = empty
    seeds["empty/single_byte.bin"] = llp.encode(0, b"\x42")
    seeds["empty/two_bytes.bin"] = llp.encode(0, b"Hi")
    seeds["empty/channel_255.bin"] = llp.encode(255, b"")

    # ── stuffing: every place a 0xAA can appear ────────────────────────────
    seeds["stuffing/payload_aa.bin"] = aa_frame
    seeds["stuffing/payload_aa55.bin"] = llp.encode(0, b"\xaa\x55")
    seeds["stuffing/payload_triple_aa.bin"] = llp.encode(0, b"\xaa\xaa\xaa")
    seeds["stuffing/payload_aa00_pairs.bin"] = llp.encode(0, b"\xaa\x00\xaa\x00")
    seeds["stuffing/len_field.bin"] = llp.encode(0, b"x" * 0xAA)
    seeds["stuffing/channel_field.bin"] = llp.encode(0xAA, b"hi")
    seeds["stuffing/crc_field.bin"] = llp.encode(0, _crc_stuffing_payload())

    # ── errors: invalid frames that must be rejected ───────────────────────
    seeds["errors/crc_error_last_byte.bin"] = bytes(crc_error)
    seeds["errors/crc_all_zeros.bin"] = empty[:-2] + b"\x00\x00"
    seeds["errors/truncated_after_magic.bin"] = b"\xaa\x55"
    seeds["errors/truncated_after_len.bin"] = hello[:3]
    seeds["errors/truncated_mid_payload.bin"] = hello[:5]
    seeds["errors/truncated_after_crc_low.bin"] = hello[:-1]
    seeds["errors/invalid_escape_01.bin"] = b"\xaa\x55\x02\x00\xaa\x01" + hello
    seeds["errors/invalid_escape_ff.bin"] = b"\xaa\x55\x02\x00\xaa\xff" + hello
    seeds["errors/raw_aa_no_escape.bin"] = (
        aa_frame[:5] + aa_frame[6:]  # drop the 0x00 that escapes the payload 0xAA
    )
    seeds["errors/wrong_magic1.bin"] = b"\xbb" + empty[1:]
    seeds["errors/wrong_magic2.bin"] = empty[:1] + b"\x44" + empty[2:]

    # ── edge_cases: boundary conditions ────────────────────────────────────
    seeds["edge_cases/payload_255.bin"] = llp.encode(0, b"\xff" * 255)
    seeds["edge_cases/payload_255_all_aa.bin"] = llp.encode(0, b"\xaa" * 255)
    seeds["edge_cases/payload_empty.bin"] = empty
    seeds["edge_cases/all_zeros.bin"] = llp.encode(0, b"\x00" * 32)
    seeds["edge_cases/all_ones.bin"] = llp.encode(0, b"\xff" * 32)
    seeds["edge_cases/alternating_55aa.bin"] = llp.encode(0, b"\x55\xaa" * 16)
    seeds["edge_cases/max_stuffing.bin"] = llp.encode(0, b"\xaa" * 64)

    # ── streams: multi-frame and noisy inputs ──────────────────────────────
    seeds["streams/two_empty.bin"] = empty + empty
    seeds["streams/empty_then_hello.bin"] = empty + hello
    seeds["streams/three_channels.bin"] = (
        llp.encode(0, b"a") + llp.encode(1, b"b") + llp.encode(255, b"c")
    )
    seeds["streams/noise_before.bin"] = b"\xff\xff\xff" + empty
    seeds["streams/noise_between.bin"] = empty + b"\xde\xad" + hello
    seeds["streams/garbage_three.bin"] = empty + b"\xff" + hello + b"\xaa\xbb" + empty
    seeds["streams/corrupt_magic1.bin"] = b"\xbb\x55" + empty
    seeds["streams/corrupt_magic2.bin"] = b"\xaa\x44" + empty
    seeds["streams/invalid_escape.bin"] = b"\xaa\x55\x02\x00\xaa\x99" + empty
    seeds["streams/crc_error_recovery.bin"] = bytes(crc_error) + hello

    return seeds


def main() -> int:
    generated = seeds()
    existing = {path.relative_to(SEEDS_DIR).as_posix() for path in SEEDS_DIR.rglob("*.bin")}

    if "--check" in sys.argv:
        problems = []
        for name, data in generated.items():
            path = SEEDS_DIR / name
            if not path.is_file():
                problems.append(f"missing: {name}")
            elif path.read_bytes() != data:
                problems.append(f"stale:   {name}")
        for name in sorted(existing - set(generated)):
            problems.append(f"extra:   {name}")
        if problems:
            for problem in problems:
                print(f"FAIL  {problem}")
            print("\nrun: python3 tools/generate_fuzz_seeds.py")
            return 1
        print(f"ok    {len(generated)} seeds up to date")
        return 0

    for name, data in generated.items():
        path = SEEDS_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)}")

    for name in sorted(existing - set(generated)):
        (SEEDS_DIR / name).unlink()
        print(f"removed fuzz-seeds/{name}")

    print(f"\n{len(generated)} seeds in {SEEDS_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
