# LLP Specification v3.0.0

**Layered Link Protocol** — a transport-level, language-agnostic protocol for framing, byte-stuffing, CRC integrity, and layer-based payload encapsulation.

> This repository is the **single source of truth** for the LLP protocol. All implementations (C, Java, Rust, Python, etc.) **must conform** to the rules defined here.

---

## Table of Contents

1. [Objective](#objective)
2. [Wire Format](#wire-format)
3. [Byte Stuffing](#byte-stuffing)
4. [CRC16-CCITT](#crc16-ccitt)
5. [Layer Chain Format](#layer-chain-format)
6. [Timeout Behavior](#timeout-behavior)
7. [Parser State Machine](#parser-state-machine)
8. [Test Vectors](#test-vectors)
9. [Conformance](#conformance)
10. [Repository Structure](#repository-structure)
11. [Contributing](#contributing)

---

## Objective

The LLP protocol defines a **wire-compatible framing layer** that guarantees:

- **Frame delineation**: unambiguous start/end of messages over a byte stream
- **Error detection**: CRC16-CCITT integrity check on every frame
- **Transparency**: byte stuffing prevents magic sequences from appearing in payload
- **Layering**: extensible layer chain for metadata, routing, and transformation
- **Resilience**: automatic resynchronisation after corruption or noise

Any two implementations that pass the same set of official test vectors are **wire-compatible**: frames produced by one can be consumed by the other.

---

## Wire Format

Every LLP transport frame has this exact structure:

```
+--------+--------+--------+--------+------------------+--------+--------+
| MAGIC1 | MAGIC2 | LEN_L  | LEN_H  | PAYLOAD (stuffed)| CRC_L  | CRC_H  |
+--------+--------+--------+--------+------------------+--------+--------+
|  0xAA  |  0x55  | [0..N] | [0..N] |  layer chain     | [0..N] | [0..N] |
+--------+--------+--------+--------+------------------+--------+--------+
```

### Field Descriptions

| Field | Size | Description |
|-------|------|-------------|
| `MAGIC1` | 1 byte | Frame start marker: `0xAA`. **Never stuffed.** |
| `MAGIC2` | 1 byte | Frame start marker: `0x55`. **Never stuffed.** |
| `LEN_L` | 1 byte | Payload length (bytes), little-endian, **stuffed**. |
| `LEN_H` | 1 byte | Payload length (bytes), little-endian, **stuffed**. |
| `PAYLOAD` | N bytes | Layer chain data. **Stuffed.** Includes all layer headers. |
| `CRC_L` | 1 byte | CRC16-CCITT low byte. **Stuffed.** |
| `CRC_H` | 1 byte | CRC16-CCITT high byte. **Stuffed.** |

### Length Encoding

Payload length is a **16-bit unsigned integer in little-endian byte order**:

- Length = `LEN_L + (LEN_H << 8)`
- Minimum: `0` (payload-less frame — still contains FinalNode)
- Maximum: defined by implementation (`LLP_MAX_PAYLOAD` / `maxPayloadBytes`)

### CRC Coverage

The CRC is computed over these bytes **in order** (all **unstuffed**):

```
MAGIC1 + MAGIC2 + LEN_L + LEN_H + PAYLOAD
```

Where PAYLOAD is the raw (unstuffed) layer chain bytes. The CRC bytes themselves are **not** included in the CRC calculation.

### Frame Size

The worst-case frame size (all payload bytes = `0xAA`, each doubling) is:

```
max_frame_size = 2 (magic) + 2 (length) + N*2 (payload, stuffed) + 4 (CRC, stuffed)
               = 8 + N * 2
```

Where N is the unstuffed payload (layer chain) length.

---

## Byte Stuffing

Byte stuffing ensures that the magic sequence `0xAA 0x55` never appears unintentionally inside a frame.

### Encoding (Framer)

During frame construction, every byte written after the magic header is subject to stuffing:

```
if byte == 0xAA:
    write(0xAA)
    write(0x00)    // escape byte
else:
    write(byte)
```

This applies to **all** fields: length, payload, and CRC.

The magic bytes (`MAGIC1`, `MAGIC2`) are **never stuffed**.

### Decoding (Parser)

During frame parsing, the reverse operation:

```
if byte == 0xAA:
    next_byte = read()
    if next_byte == 0x00:
        emit(0xAA)          // restore original byte
    elif next_byte == 0x55:
        resync()            // overlapping frame detected
    else:
        sync_error()        // invalid escape sequence
else:
    emit(byte)
```

### Stuffing Rules Summary

| Encountered | Next Byte | Meaning |
|-------------|-----------|---------|
| `0xAA` (non-magic) | `0x00` | Stuffed byte: restore `0xAA` |
| `0xAA` (non-magic) | `0x55` | Overlapping magic: resync |
| `0xAA` (non-magic) | other | Invalid escape: sync error |
| `0xAA` at magic pos 1 | — | Frame start: do not unstuff |
| `0x55` at magic pos 2 | — | Frame start: do not unstuff |

---

## CRC16-CCITT

The protocol uses **CRC16-CCITT** with the following parameters:

| Parameter | Value |
|-----------|-------|
| Polynomial | `0x1021` (`x^16 + x^12 + x^5 + 1`) |
| Initial value | `0xFFFF` |
| Final XOR | `0x0000` (none — result is used directly) |
| Input reflected | No |
| Output reflected | No |

### Reference Algorithm (Bit-by-Bit)

```c
uint16_t crc16_ccitt(uint16_t crc, uint8_t data) {
    crc ^= (uint16_t)data << 8;
    for (int i = 0; i < 8; i++) {
        if (crc & 0x8000)
            crc = (crc << 1) ^ 0x1021;
        else
            crc <<= 1;
    }
    return crc & 0xFFFF;
}
```

Initialise with `crc = 0xFFFF`, then call for every byte in order: magic bytes, length bytes, and unstuffed payload bytes.

### Verification

A frame's CRC is valid when computing CRC over the entire frame (magic + length + unstuffed payload) and comparing the result against the received CRC bytes yields equality.

### Known Test Vector

| Input (hex) | Expected CRC |
|-------------|--------------|
| `"123456789"` (ASCII) | `0x29B1` |

---

## Layer Chain Format

The payload portion of an LLP frame contains a **layer chain**: an ordered sequence of layer headers followed by raw application data.

### Structure

```
+-----------+-------------+----------+---+----------+-----------------+
| LAYER_1   | LAYER_2     | ...      |   | FINAL    | RAW DATA        |
| [ID+META] | [ID+META]   |          |   | (0x00)   |                 |
+-----------+-------------+----------+---+----------+-----------------+
```

### Layer Header

Each layer header has this format:

```
+----------+-----------------+--------------+
| LAYER_ID | META_LEN        | METADATA     |
| (1 byte) | (1 or 3 bytes)  | (N bytes)    |
+----------+-----------------+--------------+
```

#### Layer ID

| ID Range | Type | Meaning |
|----------|------|---------|
| `0x00` | **FinalNode** | No more layers; raw data follows immediately. This layer has 0 metadata bytes. |
| `0x01` – `0x7F` | **Passthrough** | Metadata present; raw payload is unchanged underneath. Parsers may skip passthrough layers to reach FinalNode. |
| `0x80` – `0xFE` | **Transform** | Metadata present; payload was transformed (e.g., encrypted, compressed). Parsers MUST NOT skip transform layers — the raw data cannot be understood without the transform. |
| `0xFF` | **Reserved** | Reserved for future use. Parsers should treat as unknown and skip if possible. |

#### Meta Length Encoding

| Condition | Encoding | Example |
|-----------|----------|---------|
| `0 <= meta_len <= 254` | 1 byte: `meta_len` | `0x03` = 3 bytes of metadata |
| `meta_len >= 255` | 3 bytes: `0xFF` + `len_high` + `len_low` (big-endian) | `0xFF 0x01 0x00` = 256 bytes |

### FinalNode

`0x00` marks the end of layer headers. Everything after FinalNode is **raw application data**, passed through without interpretation by the LLP transport layer.

### Layer Traversal

To extract the final application payload from a received frame:

1. Start at the first byte of the payload (after length)
2. Read layer ID
3. If `ID == 0x00` (FinalNode): all remaining bytes are raw data. Done.
4. If passthrough (`0x01-0x7F`): read metadata, skip it, go to next layer
5. If transform (`0x80-0xFE`): read metadata, but payload may be modified — return entire layer chain for application-level processing
6. If reserved/unknown: skip or report based on implementation policy

---

## Timeout Behavior

The parser must implement a timeout mechanism to detect truncated frames:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LLP_FRAME_TIMEOUT_MS` | `2000` ms | Maximum idle time between bytes of a single frame |

### Timeout Rules

1. A timer starts when `MAGIC1` is received
2. The timer resets on every subsequent byte
3. If the timer exceeds `LLP_FRAME_TIMEOUT_MS` before the frame is complete:
   - The parser emits a `TIMEOUT` error
   - The parser resets its state machine
   - If the byte that triggered the timeout is `0xAA`, the parser should begin a new frame attempt (optimistic resync)

### Optimistic Resync After Timeout

When a timeout occurs, the parser resets to `WAIT_MAGIC1`. If the current byte being processed is `0xAA`, it is **not discarded** — instead, the parser transitions directly to `WAIT_MAGIC2` to minimise data loss.

---

## Parser State Machine

The parser implements a deterministic finite-state machine with these states:

```
       +--- 0xAA ---> WAIT_MAGIC2 --- 0x55 ---> READ_LEN_L
       |                                                  |
       v                                                  v
WAIT_MAGIC1 <--- timeout/resync <--- ... <--- READ_CRC_H <--- READ_PAYLOAD
       ^                                                  |
       +--- (recovery after error) -----------------------+
```

### States

| State | Description |
|-------|-------------|
| `WAIT_MAGIC1` | Idle; waiting for `0xAA`. Any other byte is discarded. |
| `WAIT_MAGIC2` | Received `0xAA`; waiting for `0x55`. Anything else resets to `WAIT_MAGIC1`. |
| `READ_LEN_L` | Reading the low byte of payload length. |
| `READ_LEN_H` | Reading the high byte of payload length. |
| `READ_PAYLOAD` | Reading the payload bytes, performing unstuffing. |
| `READ_CRC_L` | Reading the low byte of CRC, performing unstuffing. |
| `READ_CRC_H` | Reading the high byte of CRC, performing unstuffing. |

### State Transitions

| Current State | Input | Next State | Action |
|--------------|-------|------------|--------|
| `WAIT_MAGIC1` | `0xAA` | `WAIT_MAGIC2` | Start frame timer |
| `WAIT_MAGIC1` | other | `WAIT_MAGIC1` | Discard byte |
| `WAIT_MAGIC2` | `0x55` | `READ_LEN_L` | — |
| `WAIT_MAGIC2` | `0xAA` | `WAIT_MAGIC2` | Partial magic; keep waiting |
| `WAIT_MAGIC2` | other | `WAIT_MAGIC1` | Reset (invalid magic2) |
| `READ_LEN_L` | any | `READ_LEN_H` | Store byte (after unstuffing) |
| `READ_LEN_H` | any | `READ_PAYLOAD` | Store byte; validate length ≤ max |
| `READ_PAYLOAD` | any | `READ_PAYLOAD` or `READ_CRC_L` | Store unstuffed bytes; check index |
| `READ_CRC_L` | any | `READ_CRC_H` | Store byte (after unstuffing) |
| `READ_CRC_H` | any | `WAIT_MAGIC1` | Validate CRC; emit frame/error |

### Error Recovery

After any error (CRC mismatch, sync error, timeout, or invalid length), the parser resets to `WAIT_MAGIC1` and resumes scanning for the next `0xAA` magic byte. This enables **automatic resynchronisation** without external intervention.

---

## Test Vectors

This repository contains **199 official test vectors** across 13 categories, covering encoding, decoding, stream parsing, timing, and layer traversal scenarios.

Vectors are **grouped by category** into JSON files. Each file contains multiple related samples to validate a specific aspect of the protocol.

### Vector Types

| Type | Purpose | Input | Expected |
|------|---------|-------|----------|
| `encode` | Validate frame construction | `llp_payload_hex` (layer chain) | `frame_hex` (complete frame) |
| `decode` | Validate frame parsing | `frame_hex` | `outcome` + `payload_hex` or `error_code` |
| `stream` | Validate incremental / multi-frame parsing | `chunks_hex[]` | `events[]` (FRAME or ERROR) |
| `timing` | Validate timeout behaviour | `events[]` with `byte_hex` + `time_ms` | `events[]` (FRAME or ERROR) |
| `traversal` | Validate layer chain parsing to extract final payload | `frame_hex` | `outcome` + `final_payload_hex` |

### File Format

```json
{
  "spec_version": "3.0.0",
  "category": "transport_crc",
  "description": "Frames with invalid CRC values",
  "vectors": [
    {
      "name": "crc_all_zero",
      "type": "decode",
      "result": "invalid",
      "flags": [],
      "description": "CRC field set to 0x0000",
      "input": { "frame_hex": "AA5506000068656C6C6F0000" },
      "expected": { "outcome": "ERROR", "error_code": "CHECKSUM" }
    }
  ]
}
```

All binary values are **uppercase hex strings**. See [schema/vector.schema.json](schema/vector.schema.json) for full validation rules.

### Result Model (Wycheproof)

Every vector carries a `result` field following the Wycheproof conformance model:

| Value | Meaning |
|-------|---------|
| `"valid"` | Implementation MUST accept this input and produce the expected output |
| `"invalid"` | Implementation MUST reject this input and produce the expected error |
| `"acceptable"` | Implementation MAY accept or reject; any conformant behaviour is allowed |

The `flags` array documents additional constraints:

| Flag | Meaning |
|------|---------|
| `OptionalBehavior` | Behaviour is implementation-defined; both outcomes are conformant |
| `EdgeCase` | Tests boundary conditions that may expose bugs |
| `ImplementationDefined` | Behaviour depends on implementation configuration |
| `Deprecated` | Input uses a deprecated feature; future versions may reject |
| `Slow` | Timing vector requiring real-time sleeps; skipped by default, run with `--include-slow` |

### Vector Categories

| Directory | File | Vectors | Description |
|-----------|------|---------|-------------|
| `transport/` | `valid.json` | 69 | Valid frame encode, decode round-trips, multi-frame streams |
| `transport/` | `crc.json` | 28 | CRC error detection (bit flips, byte swaps, all-zero, wrong CRC) |
| `transport/` | `stuffing.json` | 8 | Byte stuffing encode/decode edge cases |
| `transport/` | `resync.json` | 8 | Resynchronisation after noise and corruption |
| `transport/` | `truncation.json` | 10 | Truncated frames at every field boundary |
| `transport/` | `timeout.json` | 5 | Timeout behaviour between bytes |
| `layers/` | `passthrough.json` | 24 | Passthrough layer chain encode/decode/traversal |
| `layers/` | `transform.json` | 12 | Transform layer chain encode/decode |
| `layers/` | `malformed.json` | 4 | Malformed layer chains (truncated metadata, empty payload, reserved IDs) |
| `layers/` | `traversal.json` | 5 | Layer traversal to extract final application payload |
| `parser/` | `incremental.json` | 5 | Byte-by-byte and chunked incremental parsing |
| `parser/` | `fragmented.json` | 6 | Frame fragments split across chunk boundaries |
| `parser/` | `recovery.json` | 5 | Recovery after errors in a byte stream |

### Vector Philosophy

- Each file groups **many related samples** for the same protocol aspect
- Every vector has a clear `description` explaining what behaviour it validates
- Vectors are **deterministic**: same input always produces the same output
- Prefer **semantic edge cases** over random testing: 10 well-designed vectors > 1000 random ones
- Each vector should answer: *"What exact behaviour am I validating?"*

---

## Conformance

An LLP implementation **conforms** to this specification when it passes all official test vectors.

### Conformance Badge

Once an implementation passes 100 % of the vector suite:

```
Compatible with LLP Spec v3.0.0
Passed: 199/199 official vectors
```

### Validation

This repository includes a Python reference runner for automated validation:

```bash
# Validate vectors (skips Slow timing vectors by default)
python3 validate_vectors.py

# Validate all vectors including timing (takes ~20 seconds)
python3 validate_vectors.py --include-slow

# Expected output (default, fast):
# Total: 199  Passed: 194  Failed: 0  Skipped: 0  Slow: 5

# Expected output (--include-slow, all vectors):
# Total: 199  Passed: 199  Failed: 0  Skipped: 0  Slow: 0
```

### Conformance Requirements

1. **Framer**: Must produce byte-identical frames for every `encode` vector
2. **Parser**: Must return the exact `payload_hex` or `error_code` for every `decode` vector
3. **Stream parser**: Must emit events in the exact order specified for every `stream` vector
4. **Timing**: Must respect `LLP_FRAME_TIMEOUT_MS` (2000 ms default) for every `timing` vector
5. **Stuffing**: Must correctly apply and remove byte stuffing according to the stuffing rules
6. **CRC**: Must compute and verify CRC16-CCITT per the reference algorithm
7. **Layer traversal**: Must correctly identify FinalNode and extract raw application data for `traversal` vectors
8. **Error codes**: Must recognise all error codes: `CHECKSUM`, `TIMEOUT`, `SYNC_ERROR`, `PAYLOAD_LEN_INVALID`, `BUFFER_FULL`, `LAYER_MALFORMED`, `TRANSFORM_NO_HANDLER`
9. **Result model**: Vectors with `result: "valid"` are mandatory; `result: "acceptable"` allows implementation choice documented via `flags`

### Non-Requirements

- The spec does **not** prescribe specific error reporting APIs, listener patterns, or logging
- The spec does **not** prescribe memory allocation strategies
- The spec does **not** prescribe threading models
- The spec does **not** prescribe configuration mechanisms (build flags, constructors, etc.)

---

## Repository Structure

```
llp-spec/
├── README.md                        # This file — the specification
├── spec_frame_generator.c           # C reference frame generator (uses llp_protocol.h)
├── build_vectors.py                # Python script to generate all JSON vectors
├── validate_vectors.py             # Python reference runner — validates all vectors
├── generate_fuzz_seeds.py          # Generates AFL/libFuzzer corpus seeds
├── schema/
│   ├── vector.schema.json         # JSON Schema v1.1.0 (draft-07) for test vector validation
│   └── CHANGELOG.md               # Schema version history
├── transport/
│   ├── README.md                  # Category overview and behaviour reference
│   ├── valid.json                 # Valid frame encoding/decoding tests
│   ├── crc.json                   # CRC error detection tests
│   ├── stuffing.json              # Byte stuffing edge cases
│   ├── truncation.json            # Truncated frame tests
│   ├── resync.json                 # Resynchronisation tests
│   └── timeout.json               # Timeout behaviour tests (4 of 5 are Slow-flagged)
├── layers/
│   ├── README.md                  # Category overview and behaviour reference
│   ├── passthrough.json           # Passthrough layer tests
│   ├── transform.json             # Transform layer tests
│   ├── malformed.json             # Malformed layer chain tests
│   └── traversal.json             # Layer traversal tests
├── parser/
│   ├── README.md                  # Category overview and behaviour reference
│   ├── incremental.json           # Byte-by-byte and chunked parsing
│   ├── fragmented.json            # Fragment boundary tests
│   └── recovery.json             # Error recovery tests
├── interoperability/
│   └── python/
│       └── runner.py             # Python reference LLP implementation (canonical for validation)
├── fuzz-seeds/                    # AFL/libFuzzer corpus seeds
│   ├── empty/                    # Minimal valid frames
│   ├── stuffing/                # Byte stuffing edge cases
│   ├── layers/                  # Layer chain variants
│   ├── errors/                  # Invalid frames (error触发)
│   ├── edge_cases/              # Boundary conditions
│   └── streams/                # Multi-frame stream seeds
```

### Reference Implementations

| Implementation | Role | Location |
|---------------|------|----------|
| **C (`llp_protocol.h`)** | Wire-format authority: defines exact frame bytes, stuffing, CRC, layer encoding | External library |
| **Python (`runner.py`)** | Canonical reference for automated validation; all 199 vectors validated against this | `interoperability/python/runner.py` |
| **C (`spec_frame_generator.c`)** | Generates reference hex values used by `build_vectors.py` | Root of repo |

The C implementation defines the authoritative wire format. The Python implementation is the canonical reference for automated conformance testing. Both must produce byte-identical output for every encode vector.

### Key Files

| File | Purpose |
|------|---------|
| `spec_frame_generator.c` | Generates reference frame hex values using the C `llp_protocol.h` implementation. All encode vectors are produced by this program. |
| `build_vectors.py` | Reads reference hex values and generates all JSON vector files. Run after modifying `spec_frame_generator.c`. |
| `validate_vectors.py` | Python reference runner — validates all vectors against the Python implementation. Use `--include-slow` to run timing vectors. |
| `interoperability/python/runner.py` | Python reference LLP implementation: CRC16-CCITT, frame building, deframing state machine, layer traversal. |
| `schema/vector.schema.json` | JSON Schema v1.1.0 (draft-07) for validating vector file structure. |
| `generate_fuzz_seeds.py` | Generates AFL/libFuzzer corpus seeds from official test vectors. |

### Regenerating Vectors

```bash
# 1. Compile the reference generator
gcc -std=c99 -I /path/to/llp-protocol/include -o /tmp/spec_gen spec_frame_generator.c

# 2. Generate reference hex values
/tmp/spec_gen

# 3. Build all JSON vectors
python3 build_vectors.py
```

---

## Wire Compatibility Matrix

| Feature | C (llp_protocol.h) | Java (llp-core) | Python (reference) | Requirement |
|---------|-------------------|-----------------|---------------------|-------------|
| Frame magic (`AA 55`) | ✅ | ✅ | ✅ | MUST |
| Little-endian length | ✅ | ✅ | ✅ | MUST |
| Byte stuffing | ✅ | ✅ | ✅ | MUST |
| Unstuffing | ✅ | ✅ | ✅ | MUST |
| CRC16-CCITT (0x1021, 0xFFFF) | ✅ | ✅ | ✅ | MUST |
| CRC coverage (magic+len+payload) | ✅ | ✅ | ✅ | MUST |
| Timeout (2000 ms default) | ✅ | ✅ | ✅ | MUST |
| Layer chain parsing | ✅ | ✅ | ✅ | MUST |
| FinalNode detection | ✅ | ✅ | ✅ | MUST |
| Passthrough layers | ✅ | ✅ | ✅ | MUST |
| Transform layers | ✅ | ✅ | ✅ | MUST |
| Extended metadata (≥255) | ✅ | ✅ | ✅ | SHOULD |
| Optimistic resync after timeout | ✅ | ✅ | ✅ | MAY |

---

## Contributing

### Adding Test Vectors

1. Add the test case to `spec_frame_generator.c` (if it requires frame generation)
2. Run the generator and `build_vectors.py`
3. Verify the new vector with at least two independent implementations
4. Submit a pull request

### Vector Design Principles

- **Deterministic**: Same input → same output, always
- **Minimal**: Each vector tests exactly one behaviour
- **Independent**: Vectors should not depend on each other
- **Documented**: Every vector has a clear `description` explaining what it tests
- **Coverage**: Prefer semantic coverage over raw quantity — 10 well-chosen edge cases > 1000 random frames

### Error Code Reference

| Error Code | Meaning |
|------------|---------|
| `CHECKSUM` | CRC16-CCITT validation failed |
| `TIMEOUT` | Inter-byte timeout exceeded |
| `SYNC_ERROR` | Invalid escape sequence or unexpected byte in frame |
| `PAYLOAD_LEN_INVALID` | Payload length exceeds implementation maximum |
| `BUFFER_FULL` | Internal parser buffer overflow |
| `LAYER_MALFORMED` | Layer chain metadata is truncated, inconsistent, or uses invalid IDs |
| `TRANSFORM_NO_HANDLER` | Transform layer (0x80-0xFE) encountered with no registered handler |

---

## License

LLP Specification v3.0.0 — Copyright © 2026 Flamingo Communications

This specification is maintained as the authoritative reference for the LLP protocol.
All implementations should reference this document as the canonical behaviour definition.
