#!/usr/bin/env python3
"""
LLP Fuzz Seed Generator.

Generates minimal binary seeds for AFL/libFuzzer corpus from official test vectors.
Each seed is a minimal byte sequence that exercises a specific code path.

Seeds are organised by category:
  fuzz-seeds/empty/         — minimal valid frames
  fuzz-seeds/stuffing/      — byte stuffing edge cases
  fuzz-seeds/layers/        — layer chain variants
  fuzz-seeds/errors/        — invalid frames triggering errors
  fuzz-seeds/edge_cases/     — boundary conditions

Usage:
    python3 generate_fuzz_seeds.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "interoperability", "python"))
from runner import make_frame, crc16

SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
SEEDS_DIR = os.path.join(SPEC_DIR, "fuzz-seeds")


def h2b(s):
    return bytes.fromhex(s) if s else b""


def generate_seeds():
    os.makedirs(os.path.join(SEEDS_DIR, "empty"), exist_ok=True)
    os.makedirs(os.path.join(SEEDS_DIR, "stuffing"), exist_ok=True)
    os.makedirs(os.path.join(SEEDS_DIR, "layers"), exist_ok=True)
    os.makedirs(os.path.join(SEEDS_DIR, "errors"), exist_ok=True)
    os.makedirs(os.path.join(SEEDS_DIR, "edge_cases"), exist_ok=True)

    def write(name, data, subdir):
        path = os.path.join(SEEDS_DIR, subdir, name)
        with open(path, "wb") as f:
            f.write(data)
        print(f"  {path}")

    # ── empty: minimal valid frames ────────────────────────────────────
    # Empty payload — only FinalNode (0x00)
    write("empty_frame.bin", make_frame(b"\x00"), "empty")
    # Single byte payload
    write("single_byte.bin", make_frame(b"\x00\x42"), "empty")
    # Two bytes
    write("two_bytes.bin", make_frame(b"\x00\x48\x65"), "empty")

    # ── stuffing: byte stuffing edge cases ──────────────────────────────
    # Payload with 0xAA — triggers stuffing
    write("stuffing_aa.bin", make_frame(b"\x00\xAA"), "stuffing")
    # Payload with 0xAA 0x55 (magic overlap in data)
    write("stuffing_aa55.bin", make_frame(b"\x00\xAA\x55"), "stuffing")
    # Triple 0xAA
    write("stuffing_triple_aa.bin", make_frame(b"\x00\xAA\xAA\xAA"), "stuffing")
    # Alternating 0xAA 0x00
    write("stuffing_aa00_aa00.bin", make_frame(b"\x00\xAA\x00\xAA\x00\xAA"), "stuffing")
    # Many 0xAA in metadata (layer with meta containing 0xAA)
    write("stuffing_meta_aa.bin", make_frame(b"\x01\x02\xAA\x00\xAA\x02\xBB\x00"), "stuffing")

    # ── layers: layer chain variants ────────────────────────────────────
    # Only FinalNode
    write("final_node_only.bin", make_frame(b"\x00"), "layers")
    # Passthrough + FinalNode + data
    write("passthrough.bin", make_frame(b"\x01\x03\x10\x20\x30\x00hello"), "layers")
    # Transform layer (0x80)
    write("transform_80.bin", make_frame(b"\x80\x04\xDE\xAD\xBE\xEF\x00OK"), "layers")
    # Mixed passthrough + transform
    write("mixed_layers.bin", make_frame(b"\x01\x02\x11\x22\x81\x01\xFF\x00\x55\xAA\x01"), "layers")
    # Unknown/reserved layer 0xFF
    write("reserved_ff.bin", make_frame(b"\xFF\x01\x00\x00data"), "layers")
    # Max passthrough ID 0x7F
    write("passthrough_7f.bin", make_frame(b"\x7F\x02\xF0\x0F\x00xyz"), "layers")
    # Max transform ID 0xFE
    write("transform_fe.bin", make_frame(b"\xFE\x01\xA5\x00\x01\x02\x03"), "layers")
    # Deeply nested layers
    write("deep_nested.bin", make_frame(b"\x01\x01\x01\x02\x01\x02\x03\x01\x03\x00deep"), "layers")

    # ── errors: invalid frames ───────────────────────────────────────────
    # CRC error — flip last CRC byte
    frame = make_frame(b"\x00")
    corrupted = bytearray(frame)
    corrupted[-1] ^= 0xFF
    write("crc_error_last_byte.bin", bytes(corrupted), "errors")

    # CRC all zeros
    write("crc_all_zeros.bin", frame[:-2] + b"\x00\x00", "errors")

    # Truncated mid-frame
    write("truncated_after_magic.bin", h2b("AA55"), "errors")
    write("truncated_after_len.bin", h2b("AA5502"), "errors")
    write("truncated_mid_payload.bin", h2b("AA55060048656C"), "errors")
    write("truncated_after_crc_low.bin", h2b("AA55060048656C6C6F37"), "errors")

    # Invalid escape sequence (0xAA followed by 0x01)
    write("invalid_escape_01.bin", h2b("AA55020000AA0197A6"), "errors")
    # Invalid escape sequence (0xAA followed by 0xFF)
    write("invalid_escape_ff.bin", h2b("AA55020000AAFF97A6"), "errors")
    # 0xAA without escape (raw 0xAA in frame without 0x00)
    write("raw_aa_no_escape.bin", h2b("AA55020000AA97A6"), "errors")

    # Wrong magic bytes
    write("wrong_magic1.bin", h2b("BB550100008883"), "errors")
    write("wrong_magic2.bin", h2b("AA440100008883"), "errors")

    # Layer malformed: metadata length exceeds available
    write("layer_meta_truncated.bin", h2b("AA550800010A1020300048656C6C6F3798"), "errors")
    # Layer malformed: extended meta truncated
    write("layer_extended_meta_truncated.bin", h2b("AA55040001FF0048656C6C6F3798"), "errors")

    # Payload length too big (exceeds max)
    write("payload_too_big.bin", h2b("AA55FFFF000000000000"), "errors")

    # ── edge_cases: boundary conditions ─────────────────────────────────
    # Max payload 255 bytes (just under extended meta threshold)
    write("payload_255.bin", make_frame(b"\x00" + b"\xFF" * 255), "edge_cases")
    # Payload 256 bytes (first extended meta case)
    write("payload_256.bin", make_frame(b"\x00" + b"\xAA" * 256), "edge_cases")
    # Very long layer chain (many layers)
    long_chain = b"\x00" + b"\x01\x00" * 100 + b"\x00end"
    write("long_layer_chain.bin", make_frame(long_chain), "edge_cases")
    # All possible layer IDs (0x00 to 0xFF, each followed by minimal metadata)
    all_layers = bytes([i for i in range(256)]) + b"\x00\x00\x00TEST"
    write("all_layer_ids.bin", make_frame(all_layers), "edge_cases")
    # Payload with only 0x00 bytes
    write("all_zeros.bin", make_frame(b"\x00" + b"\x00" * 32), "edge_cases")
    # Payload with only 0xFF bytes
    write("all_ones.bin", make_frame(b"\x00" + b"\xFF" * 32), "edge_cases")
    # Alternating pattern
    write("alternating_55aa.bin", make_frame(b"\x00" + b"\x55\xAA" * 16), "edge_cases")
    # Many 0xAA (maximum stuffing scenario)
    write("max_stuffing.bin", make_frame(b"\x00" + b"\xAA" * 64), "edge_cases")

    # ── multi-frame streams (interesting for stream fuzzing) ──────────────
    os.makedirs(os.path.join(SEEDS_DIR, "streams"), exist_ok=True)
    ef = make_frame(b"\x00")
    hf = make_frame(b"\x00hello")
    af = make_frame(b"\x00\xAA")

    write("stream_two_empty.bin", ef + ef, "streams")
    write("stream_empty_hello.bin", ef + hf, "streams")
    write("stream_three_mixed.bin", af + ef + hf, "streams")
    write("stream_noise_before.bin", b"\xFF\xFF\xFF" + ef, "streams")
    write("stream_noise_between.bin", ef + b"\xDE\xAD" + hf, "streams")
    write("stream_garbage_three.bin", ef + b"\xFF" + hf + b"\xAA\xBB" + ef, "streams")
    write("stream_corrupt_magic1.bin", b"\xBB\x55" + ef, "streams")
    write("stream_corrupt_magic2.bin", b"\xAA\x44" + ef, "streams")
    write("stream_invalid_escape.bin", h2b("AA55020000AA9997A6") + ef, "streams")
    write("stream_crc_error_recovery.bin", bytes([b ^ 0xFF for b in list(ef)[:4]] + list(ef)[4:]) + hf, "streams")

    print(f"\nGenerated fuzz seeds in {SEEDS_DIR}/")


if __name__ == "__main__":
    generate_seeds()