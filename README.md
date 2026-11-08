# LLP Specification v4.0.0

**LLP** (Lightweight Link Protocol) — a transport-level framing layer for
byte-oriented links that can corrupt, drop or invent bytes: UART, RS-485, RF,
CAN, sockets.

> This repository is the **single source of truth** for the LLP wire format.
> It owns the normative specification ([`docs/SPEC-v4.md`](docs/SPEC-v4.md)),
> the language-independent conformance vectors ([`vectors/`](vectors/)),
> their schema and the Python reference implementation used to generate them.
> Every implementation (C, Java, Rust, Python, …) **must conform** to what is
> defined here.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Spec v4.0.0](https://img.shields.io/badge/Spec-v4.0.0-blue)](docs/SPEC-v4.md)
[![Wire format](https://img.shields.io/badge/Wire-AA%2055%20%7C%20LEN%20%7C%20CHANNEL-lightgrey)](docs/SPEC-v4.md)

---

## Table of Contents

1. [What LLP guarantees](#what-llp-guarantees)
2. [Wire format](#wire-format)
3. [Channels](#channels)
4. [Errors](#errors)
5. [Timeout](#timeout)
6. [Conformance vectors](#conformance-vectors)
7. [Reference implementation](#reference-implementation)
8. [Repository structure](#repository-structure)
9. [Running the checks](#running-the-checks)
10. [Relationship with v3.1.0](#relationship-with-v310)

---

## What LLP guarantees

1. **No corrupted frame reaches the application.** A frame is delivered only
   after its CRC validates. Nothing is observable before that.
2. **Fast resynchronisation.** After noise, the parser finds the next frame in a
   bounded number of bytes (~50–70, measured in the C implementation).
3. **Predictable cost.** O(1) work per byte, no dynamic memory, no recursion.
4. **Small on 8-bit MCUs.** Fits an ATmega328P; the C parser needs 17 bytes of
   RAM with a caller-owned payload buffer.
5. **Multiplexing.** Applications route messages by `CHANNEL`.

Deliberately **out of scope**: retransmission, acknowledgements, ordering, flow
control, encryption, compression, and fragmentation of messages larger than 255
bytes. The payload is opaque bytes; the application owns its format.

## Wire format

```
 offset  0      1      2      3        4 .. 3+LEN      4+LEN  5+LEN
        +------+------+------+------+----------------+------+------+
        | 0xAA | 0x55 | LEN  | CHAN |    PAYLOAD     | CRC_L| CRC_H|
        +------+------+------+------+----------------+------+------+
          magic (never stuffed)     LEN bytes           little-endian
```

| Field | Size | Description |
|---|---:|---|
| `MAGIC` | 2 | `0xAA 0x55`, never stuffed, never escaped |
| `LEN` | 1 | Payload length, `0..255` |
| `CHANNEL` | 1 | Application routing tag, `0..255` |
| `PAYLOAD` | `LEN` | Opaque application bytes |
| `CRC16` | 2 | CRC16-CCITT-FALSE over `MAGIC + LEN + CHANNEL + PAYLOAD`, little-endian |

Every byte from `LEN` onwards is subject to byte stuffing: `0xAA` is written as
`0xAA 0x00`. `0xAA 0x55` inside a frame is a **resync**, `0xAA` followed by
anything else is a **sync error**. `LEN == 0` is valid.

| | Bytes |
|---|---:|
| Minimum frame (empty payload, nothing stuffed) | 6 |
| Common frame with `n` bytes and no `0xAA` | `6 + n` |
| Worst case (every byte after the magic is `0xAA`) | `10 + 2n` |

```
empty payload, channel 0     : aa55000023b3
"ok\n", channel 0            : aa5503006f6b0a08db
"G1 X10\n", channel 1        : aa5507014731205831300ae427
payload AA 55, channel 0     : aa550200aa0055d24a
payload 0xAA × 8, channel 0  : aa550800aa00aa00aa00aa00aa00aa00aa00aa00b6bb
```

The full state machine, the error table and the normative invariants live in
[`docs/SPEC-v4.md`](docs/SPEC-v4.md). The C, Java and Python APIs are described
there as guidance, not as wire.

## Channels

`CHANNEL` is opaque to the protocol. A convention that works well:

| Channel | Suggested use |
|---:|---|
| `0` | default / text command stream |
| `1` | binary commands |
| `2` | telemetry |
| `3` | logs |
| `4..239` | application-defined |
| `240..255` | reserved for future LLP layers |

Reliability features (sequence numbers, ACK, retransmission) are **not** part of
the framing: they belong to the application or a channel convention.

## Errors

| Name | Value | Cause | Recovery |
|---|---:|---|---|
| `LLP_ERR_CRC` | 1 | CRC mismatch after a complete frame | frame discarded, back to `WAIT_MAGIC1` |
| `LLP_ERR_LEN` | 2 | `LEN` greater than the instance capacity | rejected as soon as `LEN` is read |
| `LLP_ERR_TIMEOUT` | 3 | inter-byte gap greater than `timeout_ms` | frame discarded; the byte is re-examined as a magic |
| `LLP_ERR_SYNC` | 4 | bad escape, or a new magic inside a frame | frame discarded (`AA 55` starts the new frame) |

Errors are **events**, not fatal states: after reporting one the parser is
always ready for the next frame.

## Timeout

- Measured between consecutive bytes, from the second byte of a frame onwards.
- No timeout is reported while in `WAIT_MAGIC1` (an idle link is normal).
- Default **2000 ms**; the comparison is **strictly greater than** `timeout_ms`.
- Timestamp arithmetic must be wrap-safe on 16 bits, which caps the timeout at
  **32767 ms**.

## Conformance vectors

Vectors are the contract between implementations: if a C parser, a Java parser
and a Python parser all pass them, they speak the same protocol regardless of
internal structure. They are **generated and self-checked** by
[`tools/build_vectors.py`](tools/build_vectors.py) on top of the reference
implementation, so a vector cannot disagree with the specification.

<!-- LLP-VECTORS-TABLE:BEGIN -->
| File | Cases | Category | Covers |
|---|---:|---|---|
| `vectors/encode.json` | 39 | `transport_encode` | Encoder conformance: (channel, payload) produces exact frame bytes. |
| `vectors/decode.json` | 45 | `transport_decode` | Decoder conformance: byte streams produce the exact frames and no errors. |
| `vectors/errors.json` | 15 | `transport_errors` | Error handling: CRC, length and sync errors, and recovery after them. |
| `vectors/timing.json` | 12 | `transport_timing` | Inter-byte timeout with injected time: gaps, boundary, recovery, 16-bit wrap. |
| `vectors/channels.json` | 14 | `transport_channels` | Channel field: routing range, reserved range, and stuffing of the field itself. |
| `vectors/reliability.json` | 9 | `profile_r1_reliability` | Profile R1 (optional): command/ACK frame layouts on channels 1 and 2. |
| `vectors/payload.json` | 24 | `transport_payload` | Opaque payload: bytes that look like v3 layer chains are delivered unchanged. |
| `vectors/streams.json` | 12 | `parser_streams` | Incremental parsing: chunk boundaries, multi-frame streams and recovery. |
| **Total** | **170** | | |
<!-- LLP-VECTORS-TABLE:END -->

All hex strings are lowercase without separators. A case carries either a
compact `frame` or an explicit `feed` of `{hex, dt_ms}` steps when it needs
timed gaps; `stream` cases carry `chunks` so chunk boundaries are exercised.
The schema is [`schema/vector.schema.json`](schema/vector.schema.json) and the
per-kind rules are in [`docs/CONFORMANCE.md`](docs/CONFORMANCE.md).

```bash
python3 tools/validate_vectors.py    # every case against the reference
python3 tools/build_vectors.py --check   # vectors, manifest and README table
```

## Reference implementation

`reference/llp_v4.py` is a byte-identical copy of the C library's Python
reference ([`reference/VENDOR.md`](reference/VENDOR.md) pins its sha256). It is
deliberately literal: ~200 lines that can be transliterated to a new language.
`interoperability/python/runner.py` is only the vector **driver** — it feeds
bytes and collects events, it does not implement the protocol.

## Repository structure

```
llp-spec/
├── README.md                      # this overview (vector table is generated)
├── docs/
│   ├── SPEC-v4.md                 # normative wire specification
│   └── CONFORMANCE.md             # vector schema, per-kind rules and checklist
├── schema/
│   ├── vector.schema.json         # JSON Schema 2.0.0 (draft-07)
│   └── CHANGELOG.md               # schema history
├── vectors/                       # the conformance corpus (v4)
│   ├── README.md                  # behaviour reference per file
│   ├── encode.json  decode.json  errors.json  timing.json
│   ├── channels.json  payload.json  streams.json
│   └── MANIFEST.sha256            # pin for consumers that vendor the corpus
├── reference/
│   ├── llp_v4.py                  # vendored reference implementation
│   └── VENDOR.md                  # source, commit and sha256 pin
├── interoperability/python/runner.py   # vector driver
├── tools/
│   ├── build_vectors.py           # generator + self-check + C fixture emitter
│   ├── validate_vectors.py        # runs the corpus through the driver
│   ├── generate_fuzz_seeds.py     # AFL/libFuzzer corpus
│   ├── check_schema.py            # schema validation
│   ├── check_vendor.py            # vendored reference pin
│   └── selftest_reference.py      # reference vs the examples in the spec
└── fuzz-seeds/                    # deterministic fuzzing corpus
```

## Running the checks

```bash
python3 tools/check_schema.py              # jsonschema over vectors/
python3 tools/build_vectors.py --check     # corpus + manifest + README table
python3 tools/validate_vectors.py          # conformance run
python3 tools/generate_fuzz_seeds.py --check
python3 tools/check_vendor.py              # vendored reference pin
python3 tools/selftest_reference.py        # reference vs the spec examples
python3 tools/selftest_reliability.py      # Profile R1 traces T1-T9 + unit behaviour
```

Regenerating after adding a case:

```bash
python3 tools/build_vectors.py             # writes vectors/ and MANIFEST.sha256
python3 tools/build_vectors.py --update-readme
```

### Consuming the vectors from another language

- **C**: `python3 tools/build_vectors.py --emit-c test/v4_vectors_generated.h`
  produces a header with `llp4_vec_encode[]` and `llp4_vec_decode[]`, so the C
  suite needs no JSON parser.
- **Java / others**: vendor `vectors/` and verify `MANIFEST.sha256` in CI.

## Relationship with v3.1.0

| | v3.1.0 | v4.0.0 |
|---|---|---|
| Header | `MAGIC + LEN(2) + layered payload` | `MAGIC + LEN(1) + CHANNEL(1)` |
| Minimum frame | 7 bytes | 6 bytes |
| Payload layout | layer chain with metadata | opaque bytes |
| Multiplexing | layer IDs with metadata | `CHANNEL` byte |
| Stuffing / CRC / magic | `0xAA` escape, CRC16-CCITT, `AA 55` | **unchanged** |

v4 is **not wire compatible** with v3.1.0 and there is no dual-format mode. The
v3 specification and its 199 vectors remain available in branch
`feature/v3.1.0` (commit `f444c6a`); the rationale for each change is recorded
as ADR-001…ADR-010 in
[`llp-protocol/docs/DECISIONS.md`](https://github.com/flamicomm/llp-protocol/blob/main/docs/DECISIONS.md).

## Contributing

1. Add the case to the relevant `build_*_vectors()` function in
   [`tools/build_vectors.py`](tools/build_vectors.py).
2. Run `python3 tools/build_vectors.py` — the generator refuses to write a case
   the reference implementation does not reproduce, so a failing self-check
   means the **expectation** is wrong (or the spec changed).
3. Commit the generator change and the regenerated JSON together.
4. A change to the wire format requires a new ADR in the C library repository
   and a new `spec` version here.

## License

MIT — see [LICENSE](LICENSE).

LLP Specification v4.0.0 — Copyright © 2026 Flamingo Communications
