#!/usr/bin/env python3
"""LLP Spec v3.1.0 — Official Test Vector Generator

Generates grouped JSON test vector files using the Wycheproof-inspired model:
  result = "valid" | "invalid" | "acceptable"
  expected = { outcome, payload_hex, error_code, ... }

Usage:
    python3 build_vectors.py
"""

import json
import os
import sys

SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC_VERSION = "3.1.0"


# =============================================================================
# Python Reference Implementation (verified against C llp_protocol.h)
# =============================================================================

def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        crc &= 0xFFFF
    return crc


def stuff_bytes(raw: bytes) -> bytes:
    out = bytearray()
    for b in raw:
        out.append(b)
        if b == 0xAA:
            out.append(0x00)
    return bytes(out)


def build_frame(layer_chain_hex: str) -> str:
    payload = bytes.fromhex(layer_chain_hex)
    plen = len(payload)
    frame = bytearray()
    frame.append(0xAA)
    frame.append(0x55)
    len_b = bytes([plen & 0xFF, (plen >> 8) & 0xFF])
    frame.extend(stuff_bytes(len_b))
    crc_in = bytes([0xAA, 0x55]) + len_b + payload
    crc = crc16_ccitt(crc_in)
    frame.extend(stuff_bytes(payload))
    crc_b = bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    frame.extend(stuff_bytes(crc_b))
    return frame.hex().upper()


def make_layer_chain(raw_hex: str) -> str:
    if not raw_hex:
        return "00"
    return "00" + raw_hex


# =============================================================================
# C Reference Assertions — verify Python matches llp_protocol.h output
# =============================================================================

_C_ASSERTIONS = [
    ("00",                    "AA550100008883"),
    ("0042",                  "AA5502000042B1DA"),
    ("0048656C6C6F",          "AA5506000048656C6C6F3798"),
    ("0000",                  "AA550200000037B2"),
    ("00FF",                  "AA55020000FFC7AC"),
    ("00AA",                  "AA55020000AA0097A6"),
    ("00AA55",                "AA55030000AA00552DE2"),
    ("00AAAAAA",              "AA55040000AA00AA00AA00722F"),
    ("0001AA02AA03",          "AA5506000001AA0002AA0003DBD7"),
    ("01031020300048656C6C6F","AA550B0001031020300048656C6C6F6191"),
    ("0101AA0202BBCC0042",    "AA5509000101AA000202BBCC0042822E"),
    ("8004DEADBEEF004F4B",    "AA5509008004DEADBEEF004F4BB396"),
    ("010211228101FF0055AA01","AA550B00010211228101FF0055AA0001C753"),
    ("FF01000064617461",      "AA550800FF010000646174615B24"),
    ("7F02F00F0078797A",      "AA5508007F02F00F0078797ACA6E"),
    ("FE01A500010203",        "AA550700FE01A5000102030750"),
    ("0101010201020301030064656570","AA550E000101010201020301030064656570F451"),
    ("0104AA00AA55004F4B",    "AA5509000104AA0000AA0055004F4BC83C"),
    ("01000064617461",        "AA55070001000064617461B65F"),
    ("010002000300040000656E64","AA550C00010002000300040000656E643755"),
]

for _c_chain, _c_frame in _C_ASSERTIONS:
    _py_frame = build_frame(_c_chain)
    assert _py_frame == _c_frame, (
        f"Python/C mismatch for chain={_c_chain}: "
        f"Python got {_py_frame}, C says {_c_frame}")

print(f"  Verified: Python framing matches C for {len(_C_ASSERTIONS)} vectors")


# =============================================================================
# Test Vector Definitions
# =============================================================================

# (name, raw_hex, description)
RAW_DATAS = [
    ("empty_payload",       "",      "Empty application payload — only FinalNode marker (0x00)"),
    ("single_byte_42",      "42",    "Single byte payload (0x42) — minimum non-empty frame"),
    ("hello_world",         "48656C6C6F", "5-byte ASCII payload 'Hello'"),
    ("payload_null_byte",   "00",    "Payload containing a single 0x00 byte"),
    ("payload_ff_byte",     "FF",    "Payload containing a single 0xFF byte"),
    ("payload_aa_byte",     "AA",    "Payload with single 0xAA — triggers byte stuffing"),
    ("payload_aa55",        "AA55",  "Payload with 0xAA 0x55 — magic sequence in payload"),
    ("payload_triple_aa",   "AAAAAA","Three consecutive 0xAA bytes"),
    ("payload_mixed_aa",    "01AA02AA03", "Scattered 0xAA bytes with normal data"),
    ("payload_zeros_16",    "00000000000000000000000000000000", "16 zero bytes"),
    ("payload_ones_16",     "01010101010101010101010101010101", "16 bytes of 0x01"),
    ("payload_incremental", "000102030405060708090A0B0C0D0E0F", "16 sequential bytes 0x00..0x0F"),
    ("payload_all_ff_16",   "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF", "16 bytes of 0xFF"),
    ("payload_aa_prefix",   "AA42",  "0xAA at start of payload"),
    ("payload_aa_suffix",   "42AA",  "0xAA at end of payload (right before CRC)"),
    ("payload_aa_boundary", "AAAA00AA", "0xAA sequences with 0x00 interleaved"),
    ("payload_alternating", "AA00AA00AA", "Alternating 0xAA / 0x00 pattern"),
    ("payload_seq_32",      "000102030405060708090A0B0C0D0E0F"
                            "101112131415161718191A1B1C1D1E1F",
                            "32 sequential bytes"),
    ("payload_55_byte",     "55",    "Single 0x55 byte (second magic byte in data)"),
    ("payload_byte_0x7F",   "7F",    "Single 0x7F byte (max passthrough layer ID)"),
    ("payload_byte_0x80",   "80",    "Single 0x80 byte (min transform layer ID)"),
    ("payload_byte_0xFE",   "FE",    "Single 0xFE byte (max transform layer ID)"),
    ("payload_ascii_test",  "54657374", "4-byte ASCII 'Test'"),
    ("payload_ascii_fox",   "54686520717569636B2062726F776E20666F78",
                              "The quick brown fox (20 bytes)"),
    ("payload_eight_bytes", "0001020304050607", "8 sequential bytes"),
    ("payload_fifteen_null","000000000000000000000000000000", "15 null bytes"),
    ("payload_thirty_null", "00" * 30, "30 null bytes"),
    ("payload_sixtyfour_seq",
        "000102030405060708090A0B0C0D0E0F"
        "101112131415161718191A1B1C1D1E1F"
        "202122232425262728292A2B2C2D2E2F"
        "303132333435363738393A3B3C3D3E3F",
        "64 sequential bytes"),
    ("payload_repeated_55", "5555555555555555", "8 bytes of 0x55"),
    ("payload_aa_55_pairs", "AA55AA55AA55", "Alternating 0xAA 0x55 pairs"),
    ("payload_mixed_55_aa", "55AA55AA55AA55AA", "Alternating 0x55 0xAA pattern"),
    ("payload_double_zero", "0000", "Two consecutive 0x00 bytes"),
    ("payload_ten_AS",      "41414141414141414141", "10 bytes of ASCII 'A'"),
]

# (name, layer_chain_hex, description)
LAYER_CHAINS = [
    ("empty_chain",         "00",       "Only FinalNode, no raw data"),
    ("final_then_ff",       "00FF",     "FinalNode then a single 0xFF byte"),
    ("final_then_aa55",     "00AA55",   "FinalNode then 0xAA 0x55 (magic overlap)"),
    ("final_hello",         "0048656C6C6F", "FinalNode then 'Hello'"),
    ("single_passthrough",  "01031020300048656C6C6F",
     "Passthrough (0x01) with 3 bytes metadata + FinalNode + 'Hello'"),
    ("two_passthrough",     "0101AA0202BBCC0042",
     "Two passthrough layers (0x01, 0x02) with metadata containing 0xAA"),
    ("transform_layer",     "8004DEADBEEF004F4B",
     "Transform layer (0x80) with 4-byte metadata + FinalNode + 'OK'"),
    ("mixed_layers",        "010211228101FF0055AA01",
     "Passthrough (0x01) then transform (0x81) then FinalNode"),
    ("unknown_layer_id",    "FF01000064617461",
     "Unknown layer ID (0xFF) with metadata + FinalNode + 'data'"),
    ("max_passthrough",     "7F02F00F0078797A",
     "Max passthrough layer ID (0x7F) with metadata + FinalNode + 'xyz'"),
    ("max_transform",       "FE01A500010203",
     "Max transform layer ID (0xFE) with metadata + FinalNode + raw bytes"),
    ("three_nested",        "0101010201020301030064656570",
     "Three nested passthrough layers before FinalNode + 'deep'"),
    ("stuffing_metadata",   "0104AA00AA55004F4B",
     "Layer metadata containing 0xAA and 0x55"),
    ("zero_meta_len",       "01000064617461",
     "Passthrough layer with meta_len=0 + FinalNode + 'data'"),
    ("four_nested",         "010002000300040000656E64",
     "Four nested passthrough layers + FinalNode + 'end'"),
    ("passthrough_7F_zero", "7F00004142",
     "Passthrough 0x7F with meta_len=0 + FinalNode + 'AB'"),
    ("transform_FE_meta5",  "FE05010203040500FF",
     "Transform 0xFE with 5 bytes metadata + FinalNode + 0xFF"),
    ("layers_aa_meta",      "0102AA00AA0203AABBCC006465616462656566",
     "Two layers with 0xAA in metadata"),
    ("deep_nested_5",       "0100010001000100010000656E64",
     "Five passthrough layers with zero metadata + FinalNode + 'end'"),
    ("zero_meta_then_final","010000006162",
     "Passthrough (meta=0) + FinalNode + 'ab'"),
    ("missing_final_node",  "014243",
     "Layer 0x01 + raw bytes (42 43), no FinalNode — parser emits entire chain as payload"),
]

# Precompute all frames
def _make(name, raw_hex, desc):
    chain = make_layer_chain(raw_hex)
    frame = build_frame(chain)
    return name, raw_hex, chain, frame, desc

RAW_VECTORS = [_make(*r) for r in RAW_DATAS]
LAYER_VECTORS = [(n, c, build_frame(c), d) for n, c, d in LAYER_CHAINS]


# =============================================================================
# Helpers
# =============================================================================

def h2b(s: str) -> bytes:
    return bytes.fromhex(s)


def b2h(b: bytes) -> str:
    return b.hex().upper()


def flip_last_byte(hex_str: str) -> str:
    b = bytearray(h2b(hex_str))
    if b:
        b[-1] ^= 0xFF
    return b2h(bytes(b))


def flip_byte(hex_str: str, pos: int) -> str:
    b = bytearray(h2b(hex_str))
    if 0 <= pos < len(b):
        b[pos] ^= 0xFF
    return b2h(bytes(b))


def truncate(hex_str: str, keep: int) -> str:
    return hex_str[:keep * 2]


def write_grouped_file(subdir: str, data: dict) -> str:
    """Write a single grouped JSON file per category."""
    path = os.path.join(SPEC_DIR, subdir + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def write_individual_vector(subdir: str, name: str, data: dict) -> str:
    """Legacy: write one file per vector. Used during migration only."""
    path = os.path.join(SPEC_DIR, subdir, name + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# =============================================================================
# Category Generators
# =============================================================================

def gen_transport_valid():
    v = []
    for name, _, chain, frame, desc in RAW_VECTORS:
        v.append(dict(name=f"encode_{name}", type="encode",
                      result="valid", flags=[],
                      description=desc,
                      input={"llp_payload_hex": chain},
                      expected={"frame_hex": frame}))
    for name, _, chain, frame, desc in RAW_VECTORS:
        v.append(dict(name=f"decode_{name}", type="decode",
                      result="valid", flags=[],
                      description=f"Parse valid frame — {desc}",
                      input={"frame_hex": frame},
                       expected={"outcome": "FRAME", "payload_hex": chain}))
    ef = next(f for n, _, _, f, _ in RAW_VECTORS if n == "empty_payload")
    ec = next(c for n, _, c, _, _ in RAW_VECTORS if n == "empty_payload")
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    hc = next(c for n, _, c, _, _ in RAW_VECTORS if n == "hello_world")
    af = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa_byte")
    ac = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa_byte")
    v.append(dict(name="stream_two_empty", type="stream",
                  result="valid", flags=[],
                  description="Two empty frames back-to-back",
                  input={"chunks_hex": [ef + ef]},
                  expected={"events": [
                      {"type": "FRAME", "payload_hex": ec},
                      {"type": "FRAME", "payload_hex": ec}]}))
    v.append(dict(name="stream_empty_then_hello", type="stream",
                  result="valid", flags=[],
                  description="Empty then hello frame concatenated",
                  input={"chunks_hex": [ef + hf]},
                  expected={"events": [
                      {"type": "FRAME", "payload_hex": ec},
                      {"type": "FRAME", "payload_hex": hc}]}))
    v.append(dict(name="stream_three_mixed", type="stream",
                  result="valid", flags=[],
                  description="Three frames: aa_byte, empty, hello",
                  input={"chunks_hex": [af + ef + hf]},
                  expected={"events": [
                      {"type": "FRAME", "payload_hex": ac},
                      {"type": "FRAME", "payload_hex": ec},
                      {"type": "FRAME", "payload_hex": hc}]}))
    return dict(spec_version=SPEC_VERSION, category="transport_valid",
        description="Valid LLP frames: encoding, decoding round-trips, and multi-frame streams",
        vectors=v)


def gen_transport_crc():
    v = []
    frames_for_crc = RAW_VECTORS[:14]
    for name, _, _, f, desc in frames_for_crc:
        v.append(dict(name=f"corrupted_last_byte_{name}", type="decode",
                      result="invalid", flags=[],
                      description=f"CRC last byte flipped — {desc}",
                      input={"frame_hex": flip_last_byte(f)},
                      expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    b = bytearray(h2b(hf))
    b[-1] ^= 0xFF; b[-2] ^= 0xFF
    v.append(dict(name="corrupted_both_crc_bytes", type="decode",
                  result="invalid", flags=[],
                  description="Both CRC bytes flipped",
                  input={"frame_hex": b2h(bytes(b))},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    v.append(dict(name="crc_all_zero", type="decode",
                  result="invalid", flags=[],
                  description="CRC field set to 0x0000",
                  input={"frame_hex": hf[:-4] + "0000"},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    v.append(dict(name="crc_all_ones", type="decode",
                  result="invalid", flags=[],
                  description="CRC field set to 0xFFFF",
                  input={"frame_hex": hf[:-4] + "FFFF"},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    hb = h2b(hf)
    for bit in range(8):
        mod = bytearray(hb)
        mod[-2] ^= (1 << bit)
        v.append(dict(name=f"crc_bit_flip_pos_{bit}", type="decode",
                      result="invalid", flags=[],
                      description=f"Single bit flip at position {bit} in CRC low byte",
                      input={"frame_hex": b2h(bytes(mod))},
                      expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    sf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "single_byte_42")
    v.append(dict(name="crc_from_different_frame", type="decode",
                  result="invalid", flags=[],
                  description="CRC bytes copied from a different frame",
                  input={"frame_hex": hf[:-4] + sf[-4:]},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    bb = bytearray(h2b(hf))
    bb[-1], bb[-2] = bb[-2], bb[-1]
    v.append(dict(name="crc_swapped_bytes", type="decode",
                  result="invalid", flags=[],
                  description="CRC bytes in wrong byte order",
                  input={"frame_hex": b2h(bytes(bb))},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    v.append(dict(name="corrupted_payload_byte", type="decode",
                  result="invalid", flags=[],
                  description="One payload byte flipped — CRC mismatch",
                  input={"frame_hex": flip_byte(hf, 6)},
                  expected={"outcome": "ERROR", "error_code": "CHECKSUM"}))
    return dict(spec_version=SPEC_VERSION, category="transport_crc",
        description="Invalid CRC: bit flips, byte swaps, all-zeros/ones, wrong frame CRC, payload corruption",
        vectors=v)


def gen_transport_stuffing():
    v = []
    aa_f = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa_byte")
    aa_c = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa_byte")
    aa55_f = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa55")
    aa55_c = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa55")
    taa_f = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_triple_aa")
    taa_c = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_triple_aa")
    maa_f = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_mixed_aa")
    maa_c = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_mixed_aa")
    for name, frame, chain, desc in [
        ("single_aa", aa_f, aa_c, "Single 0xAA stuffed byte"),
        ("magic_overlap", aa55_f, aa55_c, "0xAA 0x55 in payload — stuffed, no false resync"),
        ("triple_aa", taa_f, taa_c, "Three consecutive 0xAA bytes"),
        ("mixed_aa", maa_f, maa_c, "Scattered 0xAA bytes"),
    ]:
        v.append(dict(name=f"valid_{name}", type="decode",
                      result="valid", flags=[],
                      description=f"Valid stuffed frame — {desc}",
                      input={"frame_hex": frame},
                      expected={"outcome": "FRAME", "payload_hex": chain}))
    for name, frame, desc in [
        ("escape_0x01", "AA55020000AA0197A6", "0xAA followed by 0x01"),
        ("escape_0xFF", "AA55020000AAFF97A6", "0xAA followed by 0xFF"),
        ("escape_0xAA", "AA55020000AAAA97A6", "0xAA followed by another 0xAA"),
    ]:
        v.append(dict(name=f"invalid_{name}", type="decode",
                      result="invalid", flags=[],
                      description=f"Invalid escape sequence — {desc}",
                      input={"frame_hex": frame},
                      expected={"outcome": "ERROR", "error_code": "SYNC_ERROR"}))
    v.append(dict(name="raw_aa_unescaped", type="decode",
                  result="invalid", flags=[],
                  description="Raw 0xAA without 0x00 escape byte",
                  input={"frame_hex": "AA55020000AA97A6"},
                  expected={"outcome": "ERROR", "error_code": "SYNC_ERROR"}))
    return dict(spec_version=SPEC_VERSION, category="transport_stuffing",
        description="Byte stuffing: valid stuffed frames, magic overlap, invalid escape sequences",
        vectors=v)


def gen_transport_truncation():
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    boundaries = [
        (1, "after_magic1",   "First magic byte only"),
        (2, "after_magic2",   "Both magic bytes"),
        (3, "after_len_l",    "After first length byte"),
        (4, "after_len_h",    "After complete length field"),
        (6, "mid_payload_1",  "After one payload byte"),
        (7, "mid_payload_2",  "After two payload bytes"),
        (9, "mid_payload_4",  "After four payload bytes"),
        (11, "mid_crc_low",   "After first CRC byte"),
    ]
    v = [dict(name=f"truncated_{s}", type="decode",
              result="invalid", flags=[],
              description=f"{d} — frame incomplete, timeout expected",
              input={"frame_hex": truncate(hf, k)},
              expected={"outcome": "ERROR", "error_code": "TIMEOUT"})
         for k, s, d in boundaries]
    v.append(dict(name="empty_stream", type="decode",
                  result="valid", flags=[],
                  description="Empty byte stream — no frame",
                  input={"frame_hex": ""},
                  expected={"outcome": "NONE"}))
    v.append(dict(name="magic_only", type="decode",
                  result="invalid", flags=[],
                  description="Only AA55, no length or payload",
                  input={"frame_hex": "AA55"},
                  expected={"outcome": "ERROR", "error_code": "TIMEOUT"}))
    return dict(spec_version=SPEC_VERSION, category="transport_truncation",
        description="Truncated frames: each field boundary — tests timeout detection",
        vectors=v)


def gen_transport_resync():
    ef = next(f for n, _, _, f, _ in RAW_VECTORS if n == "empty_payload")
    ec = next(c for n, _, c, _, _ in RAW_VECTORS if n == "empty_payload")
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    hc = next(c for n, _, c, _, _ in RAW_VECTORS if n == "hello_world")
    af = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa_byte")
    ac = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa_byte")
    a55f = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa55")
    a55c = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa55")
    v = [
        dict(name="noise_before_frame", type="stream",
             result="valid", flags=[],
             description="Noise (0xFF) before valid frame — parser discards noise",
             input={"chunks_hex": ["FFFFFF" + ef]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec}]}),
        dict(name="noise_between_frames", type="stream",
             result="valid", flags=[],
             description="Two valid frames with noise between them",
             input={"chunks_hex": [ef + "DEAD" + hf]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": hc}]}),
        dict(name="corrupt_magic1", type="stream",
             result="valid", flags=[],
             description="First magic byte corrupted — parser resyncs",
             input={"chunks_hex": ["BB550100008883" + ef]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec}]}),
        dict(name="corrupt_magic2", type="stream",
             result="valid", flags=[],
             description="Second magic byte corrupted — parser resyncs",
             input={"chunks_hex": ["AA440100008883" + ef]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec}]}),
        dict(name="aa_in_payload_no_false_resync", type="stream",
             result="valid", flags=[],
             description="Stuffing hides 0xAA bytes — parser does not false-resync",
             input={"chunks_hex": [af]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="aa55_in_payload_no_false_resync", type="stream",
             result="valid", flags=[],
             description="0xAA 0x55 in payload is stuffed — parser does not split frame",
             input={"chunks_hex": [a55f]},
             expected={"events": [{"type": "FRAME", "payload_hex": a55c}]}),
        dict(name="invalid_escape_then_valid", type="stream",
             result="valid", flags=[],
             description="Invalid escape then valid frame — parser recovers with SYNC_ERROR",
             input={"chunks_hex": ["AA55020000AA9997A6" + ef]},
             expected={"events": [{"type": "ERROR", "error_code": "SYNC_ERROR"},
                                  {"type": "FRAME", "payload_hex": ec}]}),
        dict(name="garbage_three_frames", type="stream",
             result="valid", flags=[],
             description="Garbage between three valid frames — stress resync",
             input={"chunks_hex": [ef + "FF" + hf + "AABB" + ef]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": hc},
                                  {"type": "FRAME", "payload_hex": ec}]}),
    ]
    return dict(spec_version=SPEC_VERSION, category="transport_resync",
        description="Resynchronisation: noise, corruption, invalid escapes, and recovery",
        vectors=v)


def gen_transport_timeout():
    v = [
        dict(name="timeout_mid_frame", type="timing",
             result="invalid", flags=[],
             description="Timeout in middle of receiving a frame",
             config={"timeout_ms": 2000},
             input={"events": [
                 {"byte_hex": "AA", "time_ms": 0},
                 {"byte_hex": "55", "time_ms": 1},
                 {"byte_hex": "06", "time_ms": 2},
                 {"byte_hex": "00", "time_ms": 5000}]},
             expected={"events": [{"type": "ERROR", "error_code": "TIMEOUT"}]}),
dict(name="timeout_then_valid_frame", type="timing",
              result="valid", flags=["Slow"],
              description="Timeout then complete valid frame arrives after reset",
              config={"timeout_ms": 2000},
              input={"events": [
                  {"byte_hex": "AA", "time_ms": 0},
                  {"byte_hex": "55", "time_ms": 1},
                  {"byte_hex": "AA", "time_ms": 5000},
                  {"byte_hex": "55", "time_ms": 5001},
                  {"byte_hex": "01", "time_ms": 5002},
                  {"byte_hex": "00", "time_ms": 5003},
                  {"byte_hex": "00", "time_ms": 5004},
                  {"byte_hex": "88", "time_ms": 5005},
                  {"byte_hex": "83", "time_ms": 5006}]},
              expected={"events": [
                  {"type": "ERROR", "error_code": "TIMEOUT"},
                  {"type": "FRAME", "payload_hex": "00"}]}),
dict(name="timeout_between_frames", type="timing",
              result="valid", flags=["Slow"],
              description="Timeout gap between two valid frames — both received",
             config={"timeout_ms": 2000},
             input={"events": [
                 {"byte_hex": "AA", "time_ms": 0}, {"byte_hex": "55", "time_ms": 1},
                 {"byte_hex": "01", "time_ms": 2}, {"byte_hex": "00", "time_ms": 3},
                 {"byte_hex": "00", "time_ms": 4}, {"byte_hex": "88", "time_ms": 5},
                 {"byte_hex": "83", "time_ms": 6},
                 {"byte_hex": "AA", "time_ms": 5000}, {"byte_hex": "55", "time_ms": 5001},
                 {"byte_hex": "01", "time_ms": 5002}, {"byte_hex": "00", "time_ms": 5003},
                 {"byte_hex": "00", "time_ms": 5004}, {"byte_hex": "88", "time_ms": 5005},
                 {"byte_hex": "83", "time_ms": 5006}]},
             expected={"events": [
                 {"type": "FRAME", "payload_hex": "00"},
                 {"type": "FRAME", "payload_hex": "00"}]}),
dict(name="timeout_during_second_of_two", type="timing",
              result="invalid", flags=["Slow"],
              description="First frame OK, then timeout during second frame",
             config={"timeout_ms": 2000},
             input={"events": [
                 {"byte_hex": "AA", "time_ms": 0}, {"byte_hex": "55", "time_ms": 1},
                 {"byte_hex": "01", "time_ms": 2}, {"byte_hex": "00", "time_ms": 3},
                 {"byte_hex": "00", "time_ms": 4}, {"byte_hex": "88", "time_ms": 5},
                 {"byte_hex": "83", "time_ms": 6},
                 {"byte_hex": "AA", "time_ms": 7}, {"byte_hex": "55", "time_ms": 8000}]},
             expected={"events": [
                 {"type": "FRAME", "payload_hex": "00"},
                 {"type": "ERROR", "error_code": "TIMEOUT"}]}),
dict(name="timeout_then_aa_triggers_resync", type="timing",
              result="acceptable", flags=["OptionalBehavior", "Slow"],
             description="Timeout on 0xAA triggers optimistic resync instead of discarding byte",
             config={"timeout_ms": 2000},
             input={"events": [
                 {"byte_hex": "AA", "time_ms": 0},
                 {"byte_hex": "55", "time_ms": 1},
                 {"byte_hex": "AA", "time_ms": 5000},
                 {"byte_hex": "55", "time_ms": 5001},
                 {"byte_hex": "01", "time_ms": 5002},
                 {"byte_hex": "00", "time_ms": 5003},
                 {"byte_hex": "00", "time_ms": 5004},
                 {"byte_hex": "88", "time_ms": 5005},
                 {"byte_hex": "83", "time_ms": 5006}]},
             expected={"events": [
                 {"type": "ERROR", "error_code": "TIMEOUT"},
                 {"type": "FRAME", "payload_hex": "00"}]}),
    ]
    return dict(spec_version=SPEC_VERSION, category="transport_timeout",
        description="Timeout behaviour: mid-frame, between frames, and recovery after timeout",
        vectors=v)


def _layer_vectors(indices, cat, cat_desc):
    v = []
    for i in indices:
        n, c, f, d = LAYER_VECTORS[i]
        v.append(dict(name=f"encode_{n}", type="encode",
                      result="valid", flags=[],
                      description=f"Encode — {d}",
                      input={"llp_payload_hex": c},
                      expected={"frame_hex": f}))
        v.append(dict(name=f"decode_{n}", type="decode",
                      result="valid", flags=[],
                      description=f"Parse — {d}",
                      input={"frame_hex": f},
                      expected={"outcome": "FRAME", "payload_hex": c}))
    return dict(spec_version=SPEC_VERSION, category=cat,
        description=cat_desc, vectors=v)


_PT = {0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 20}
_TF = {6, 7, 16, 17, 18, 19}


def gen_layers_passthrough():
    v = _layer_vectors(_PT, "layers_passthrough",
        "Passthrough layer chains: FinalNode, single/multiple passthrough, metadata variants, unknown IDs")

    # Add extended metadata edge-case vectors
    # extended_meta_zero: 0xFF 0x00 0x00 = 0 bytes metadata
    ext_zero_chain = "01FF00000064617461"
    ext_zero_frame = build_frame(ext_zero_chain)
    v["vectors"].append(dict(name="extended_meta_zero", type="decode",
        result="valid", flags=["EdgeCase"],
        description="Extended meta length 0xFF 0x00 0x00 = 0 bytes metadata",
        input={"frame_hex": ext_zero_frame},
        expected={"outcome": "FRAME", "payload_hex": ext_zero_chain}))

    # extended_meta_255: 0xFF 0x00 0xFF = 255 bytes metadata
    ext_255_meta = "AA" * 255
    ext_255_chain = f"01FF00FF{ext_255_meta}006162"
    ext_255_frame = build_frame(ext_255_chain)
    v["vectors"].append(dict(name="extended_meta_255", type="decode",
        result="valid", flags=["EdgeCase"],
        description="Extended meta length 0xFF 0x00 0xFF = 255 bytes of 0xAA",
        input={"frame_hex": ext_255_frame},
        expected={"outcome": "FRAME", "payload_hex": ext_255_chain}))

    # extended_meta_256: 0xFF 0x01 0x00 = 256 bytes metadata
    ext_256_meta = "BB" * 256
    ext_256_chain = f"01FF0100{ext_256_meta}006162"
    ext_256_frame = build_frame(ext_256_chain)
    v["vectors"].append(dict(name="extended_meta_256", type="decode",
        result="valid", flags=["EdgeCase"],
        description="Extended meta length 0xFF 0x01 0x00 = 256 bytes of 0xBB",
        input={"frame_hex": ext_256_frame},
        expected={"outcome": "FRAME", "payload_hex": ext_256_chain}))

    return v


def gen_layers_transform():
    v = _layer_vectors(_TF, "layers_transform",
        "Transform layer chains: transform (0x80-0xFE), mixed passthrough+transform, max IDs")

    # Transform layer decode vector with no handler registered → TRANSFORM_NO_HANDLER error.
    # A transform layer (0x80-0xFE) without a registered handler means the parser cannot
    # traverse past it — the application must handle it externally.
    # We model this as result="valid" with the entire layer chain as payload (parse succeeds
    # at transport layer but traversal is blocked).
    v["vectors"].append(dict(name="transform_no_handler_decode", type="decode",
        result="valid", flags=[],
        description="Decode transform layer (0x80) with no handler — transport parse succeeds, traversal blocked",
        input={"frame_hex": LAYER_VECTORS[6][2]},
        expected={"outcome": "FRAME", "payload_hex": LAYER_VECTORS[6][1]}))

    return v


def gen_layers_malformed():
    return dict(spec_version=SPEC_VERSION, category="layers_malformed",
        description="Malformed layer chains: truncated metadata, empty payload, invalid structures",
        vectors=[
            dict(name="truncated_metadata", type="decode",
                 result="invalid", flags=[],
                 description="Metadata length 10 but only 6 bytes available — layer is malformed",
                 input={"frame_hex": "AA550800010A10203000486535BD"},
                 expected={"outcome": "ERROR", "error_code": "LAYER_MALFORMED"}),
            dict(name="empty_payload", type="decode",
                 result="valid", flags=[],
                 description="Zero-length payload — only FinalNode (0x00)",
                 input={"frame_hex": "AA550100008883"},
                 expected={"outcome": "FRAME", "payload_hex": "00"}),
            dict(name="extended_meta_truncated", type="decode",
                 result="invalid", flags=[],
                 description="Extended meta length 0xFF but only 1 byte follows — truncated",
                 input={"frame_hex": "AA55040001FF0000ED0A"},
                 expected={"outcome": "ERROR", "error_code": "LAYER_MALFORMED"}),
            dict(name="reserved_id_FF", type="decode",
                 result="valid", flags=["OptionalBehavior"],
                 description="Layer ID 0xFF (reserved) with metadata — parsers may skip or report",
                 input={"frame_hex": "AA550800FF010000646174615B24"},
                 expected={"outcome": "FRAME", "payload_hex": "FF01000064617461"}),
        ])


def gen_layers_traversal():
    return dict(spec_version=SPEC_VERSION, category="layers_traversal",
        description="Traverse layer chains to extract raw final payload",
        vectors=[
            dict(name="three_passthrough_get_deep", type="traversal",
                 result="valid", flags=[],
                 description="Extract from three nested passthrough → 'deep'",
                 input={"frame_hex": "AA550E000101010201020301030064656570F451"},
                 expected={"outcome": "FRAME", "final_payload_hex": "64656570"}),
            dict(name="single_passthrough_get_hello", type="traversal",
                 result="valid", flags=[],
                 description="Extract from single passthrough + FinalNode + 'Hello'",
                 input={"frame_hex": "AA550B0001031020300048656C6C6F6191"},
                 expected={"outcome": "FRAME", "final_payload_hex": "48656C6C6F"}),
            dict(name="direct_finalnode", type="traversal",
                 result="valid", flags=[],
                 description="Bare FinalNode — no layers, just raw 0x42",
                 input={"frame_hex": "AA5502000042B1DA"},
                 expected={"outcome": "FRAME", "final_payload_hex": "42"}),
            dict(name="empty_final_payload", type="traversal",
                 result="valid", flags=["EdgeCase"],
                 description="FinalNode with 0 bytes of raw application data",
                 input={"frame_hex": "AA550100008883"},
                 expected={"outcome": "FRAME", "final_payload_hex": ""}),
            dict(name="single_transform_blocked", type="traversal",
                 result="invalid", flags=["ImplementationDefined"],
                 description="Transform layer (0x80) blocks traversal — no handler registered",
                 input={"frame_hex": "AA5509008004DEADBEEF004F4BB396"},
                 expected={"outcome": "ERROR", "error_code": "TRANSFORM_NO_HANDLER"}),
        ])


def gen_parser_incremental():
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    hc = next(c for n, _, c, _, _ in RAW_VECTORS if n == "hello_world")
    ef = next(f for n, _, _, f, _ in RAW_VECTORS if n == "empty_payload")
    ec = next(c for n, _, c, _, _ in RAW_VECTORS if n == "empty_payload")
    af = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa_byte")
    ac = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa_byte")
    sf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_seq_32")
    sc = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_seq_32")

    v = [
        dict(name="byte_by_byte_hello", type="stream",
             result="valid", flags=[],
             description="Hello frame one byte at a time",
             input={"chunks_hex": [hf[i:i+2] for i in range(0, len(hf), 2)]},
             expected={"events": [{"type": "FRAME", "payload_hex": hc}]}),
        dict(name="two_bytes_empty_plus_aa", type="stream",
             result="valid", flags=[],
             description="Empty + aa_byte frames two bytes at a time",
             input={"chunks_hex": [(ef+af)[i:i+4] for i in range(0, len(ef+af), 4)]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": ac}]}),
        dict(name="mixed_chunks", type="stream",
             result="valid", flags=[],
             description="Two frames with varied chunk sizes",
             input={"chunks_hex": [ef[:6], ef[6:], hf[:10], hf[10:]]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": hc}]}),
        dict(name="large_frame_byte_by_byte", type="stream",
             result="valid", flags=[],
             description="32-byte payload frame one byte at a time",
             input={"chunks_hex": [sf[i:i+2] for i in range(0, len(sf), 2)]},
             expected={"events": [{"type": "FRAME", "payload_hex": sc}]}),
        dict(name="stuffed_frame_byte_by_byte", type="stream",
             result="valid", flags=[],
             description="Stuffed payload (0xAA) fed one byte at a time",
             input={"chunks_hex": [af[i:i+2] for i in range(0, len(af), 2)]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
    ]
    return dict(spec_version=SPEC_VERSION, category="parser_incremental",
        description="Incremental parsing: one byte, two bytes, varied chunks",
        vectors=v)


def _chunks_from_hex(hex_str: str) -> list:
    return [hex_str[i:i+2] for i in range(0, len(hex_str), 2)]


def gen_parser_fragmented():
    ef = next(f for n, _, _, f, _ in RAW_VECTORS if n == "empty_payload")
    ec = next(c for n, _, c, _, _ in RAW_VECTORS if n == "empty_payload")
    af = next(f for n, _, _, f, _ in RAW_VECTORS if n == "payload_aa_byte")
    ac = next(c for n, _, c, _, _ in RAW_VECTORS if n == "payload_aa_byte")

    v = [
        dict(name="after_magic1", type="stream",
             result="valid", flags=[],
             description="Split between the two magic bytes",
             input={"chunks_hex": ["AA", "55020000AA0097A6"]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="after_magic_both", type="stream",
             result="valid", flags=[],
             description="Split after both magic bytes",
             input={"chunks_hex": ["AA55", "020000AA0097A6"]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="at_length_boundary", type="stream",
             result="valid", flags=[],
             description="Split between length bytes",
             input={"chunks_hex": ["AA5502", "0000AA0097A6"]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="mid_stuffing", type="stream",
             result="valid", flags=[],
             description="Split in middle of stuffed sequence",
             input={"chunks_hex": ["AA55020000AA", "0097A6"]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="at_crc_boundary", type="stream",
             result="valid", flags=[],
             description="Split between CRC bytes",
             input={"chunks_hex": ["AA55020000AA0097", "A6"]},
             expected={"events": [{"type": "FRAME", "payload_hex": ac}]}),
        dict(name="many_small_chunks", type="stream",
             result="valid", flags=["EdgeCase"],
             description="Two frames in many 1-byte chunks",
             input={"chunks_hex": _chunks_from_hex(ef + af)},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": ac}]}),
    ]
    return dict(spec_version=SPEC_VERSION, category="parser_fragmented",
        description="Fragmented frames: split at every field and stuffing boundary",
        vectors=v)


def gen_parser_recovery():
    ef = next(f for n, _, _, f, _ in RAW_VECTORS if n == "empty_payload")
    ec = next(c for n, _, c, _, _ in RAW_VECTORS if n == "empty_payload")
    hf = next(f for n, _, _, f, _ in RAW_VECTORS if n == "hello_world")
    hc = next(c for n, _, c, _, _ in RAW_VECTORS if n == "hello_world")

    v = [
        dict(name="after_crc_error", type="stream",
             result="valid", flags=[],
             description="CRC error then valid frame — recovers",
             input={"chunks_hex": [flip_last_byte(ef), hf]},
             expected={"events": [{"type": "ERROR", "error_code": "CHECKSUM"},
                                  {"type": "FRAME", "payload_hex": hc}]}),
        dict(name="after_truncation", type="stream",
             result="valid", flags=["Slow"],
             description="Truncated mid-length then valid frame — parser recovers with SYNC_ERROR",
             input={"chunks_hex": ["AA5501", "AA550100008883"]},
             expected={"events": [{"type": "ERROR", "error_code": "SYNC_ERROR"},
                                  {"type": "FRAME", "payload_hex": ec}]}),
        dict(name="after_sync_error", type="stream",
             result="valid", flags=[],
             description="Invalid escape then valid — recovers",
             input={"chunks_hex": ["AA55020000AA9997A6", ef]},
             expected={"events": [{"type": "ERROR", "error_code": "SYNC_ERROR"},
                                  {"type": "FRAME", "payload_hex": ec}]}),
        dict(name="garbage_then_two_frames", type="stream",
             result="valid", flags=[],
             description="Garbage then two valid frames",
             input={"chunks_hex": ["DEADBEEF", ef, hf]},
             expected={"events": [{"type": "FRAME", "payload_hex": ec},
                                  {"type": "FRAME", "payload_hex": hc}]}),
        dict(name="multiple_errors_then_valid", type="stream",
             result="valid", flags=[],
             description="Two CRC errors then a valid frame — stress recovery",
             input={"chunks_hex": [flip_last_byte(ef), flip_last_byte(hf), ef]},
             expected={"events": [{"type": "ERROR", "error_code": "CHECKSUM"},
                                  {"type": "ERROR", "error_code": "CHECKSUM"},
                                  {"type": "FRAME", "payload_hex": ec}]}),
    ]
    return dict(spec_version=SPEC_VERSION, category="parser_recovery",
        description="Error recovery: CRC, timeout, sync error, garbage, and multiple errors",
        vectors=v)


# =============================================================================
# Main — clean legacy, generate grouped, validate
# =============================================================================

def remove_individual_files(subdir: str):
    """Remove old individual vector files in subdirectory."""
    path = os.path.join(SPEC_DIR, subdir)
    if os.path.isdir(path):
        for f in os.listdir(path):
            if f.endswith(".json"):
                os.remove(os.path.join(path, f))
        os.rmdir(path)


def main():
    generators = [
        ("transport/valid",       gen_transport_valid),
        ("transport/crc",         gen_transport_crc),
        ("transport/stuffing",    gen_transport_stuffing),
        ("transport/truncation",  gen_transport_truncation),
        ("transport/resync",      gen_transport_resync),
        ("transport/timeout",     gen_transport_timeout),
        ("layers/passthrough",    gen_layers_passthrough),
        ("layers/transform",      gen_layers_transform),
        ("layers/malformed",      gen_layers_malformed),
        ("layers/traversal",      gen_layers_traversal),
        ("parser/incremental",    gen_parser_incremental),
        ("parser/fragmented",     gen_parser_fragmented),
        ("parser/recovery",       gen_parser_recovery),
    ]

    total = 0
    for subdir, gen in generators:
        data = gen()
        # Write grouped file
        write_grouped_file(subdir, data)
        total += len(data["vectors"])
        print(f"  {subdir}.json ({len(data['vectors'])} vectors)")

    print(f"\nTotal: {total} test vectors across {len(generators)} categories.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
