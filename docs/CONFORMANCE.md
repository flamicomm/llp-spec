# Conformance vectors

The cases in [`../vectors/`](../vectors/) are the contract between
implementations. If a C parser, a Java parser and a Python parser all pass them,
they speak the same protocol — regardless of internal structure.

They are **generated and self-checked** by
[`../tools/build_vectors.py`](../tools/build_vectors.py), which drives the
vendored reference implementation in
[`../reference/llp_v4.py`](../reference/llp_v4.py). Every expectation is written
by hand and verified against the reference, so a vector can never disagree with
the specification it documents.

```bash
python3 tools/build_vectors.py            # regenerate + self-check
python3 tools/build_vectors.py --check    # verify the checked-in files
python3 tools/validate_vectors.py         # run the corpus through the driver
```

## File layout

| File | Contents |
|---|---|
| `vectors/encode.json` | `(channel, payload)` → exact frame bytes |
| `vectors/decode.json` | byte streams → accepted frames (garbage, resync, max payload…) |
| `vectors/errors.json` | CRC, length and sync error handling, plus recovery |
| `vectors/timing.json` | inter-byte timeouts, boundaries, recovery, 16-bit wrap |
| `vectors/channels.json` | routing range, reserved range, stuffing of the channel field |
| `vectors/reliability.json` | **Profile R1** (optional): command/ACK frames on channels 1 and 2 |
| `vectors/payload.json` | opaque payloads that look like v3 layer chains |
| `vectors/streams.json` | chunk boundaries, multi-frame streams, recovery |

`vectors/MANIFEST.sha256` pins every file so a consumer that vendors the corpus
(C fixture, Java test resources) can verify it did not drift.

## Schema

The authoritative schema is [`../schema/vector.schema.json`](../schema/vector.schema.json)
(version **2.0.0**, independent of the protocol version).

```json
{
  "spec": "llp/4.0.0",
  "schema_version": "2.0.0",
  "category": "transport_decode",
  "description": "…",
  "generated_by": "tools/build_vectors.py",
  "cases": [
    {
      "id": "enc-text-ok",
      "kind": "encode",
      "result": "valid",
      "flags": [],
      "channel": 0,
      "payload": "6f6b0a",
      "frame": "aa5503006f6b0a08db"
    },
    {
      "id": "dec-resync-inside-frame",
      "kind": "decode",
      "result": "invalid",
      "flags": [],
      "capacity": 255,
      "timeout_ms": 2000,
      "frame": "aa5503006f6baa5507014731205831300ae427",
      "expect": {
        "frames": [{ "channel": 1, "payload": "4731205831300a" }],
        "errors": ["LLP_ERR_SYNC"],
        "timeouts": 0
      },
      "note": "…"
    },
    {
      "id": "timeout-mid-frame",
      "kind": "decode",
      "result": "invalid",
      "flags": [],
      "capacity": 255,
      "timeout_ms": 2000,
      "feed": [
        { "hex": "aa", "dt_ms": 0 },
        { "hex": "55", "dt_ms": 0 },
        { "hex": "05", "dt_ms": 2100 }
      ],
      "expect": { "frames": [], "errors": ["LLP_ERR_TIMEOUT"], "timeouts": 1 }
    }
  ]
}
```

A decode case carries **either**:

- `frame` — a hex string fed byte by byte with `dt_ms = 0` (compact form), or
- `feed` — an explicit list of `{hex, dt_ms}` steps, required when the vector
  needs timed gaps (timeout cases) or per-byte control.

A `stream` case carries `chunks` (an array of hex strings) instead, so that
chunk boundaries are exercised. All bytes inside one chunk are fed with
`dt_ms = 0`.

All hex strings are **lowercase**, without separators. `note` is optional prose.

### Encode cases

1. Encoding `(channel, payload)` must produce exactly `frame`.
2. Decoding `frame` must produce exactly one frame with the same
   `(channel, payload)` and no errors.

### Decode and stream cases

`frame` (or every entry of `feed`, or every byte of every chunk) is applied byte
by byte, in order:

1. The driver keeps a monotonic `now_ms` (any origin) and adds `dt_ms` to it
   **before** feeding that byte. Time is **simulated**: nothing sleeps.
2. Feed the byte to the parser.
3. Collection rules:
   - `expect.frames` — frames delivered, in order, as `(channel, payload)`.
   - `expect.errors` — error codes, in detection order. The exact strings are
     `LLP_ERR_CRC`, `LLP_ERR_LEN`, `LLP_ERR_TIMEOUT` and `LLP_ERR_SYNC`.
   - `expect.timeouts` — value of the timeout counter after the run; it must
     equal the number of `LLP_ERR_TIMEOUT` events. Implementations that do not
     expose counters can ignore the field.

A conformant implementation must deliver **exactly** the listed frames, in
order: no extra frames, no missing frames. It may report errors at a finer
granularity only if it still reports the listed ones in the listed order.

### Result model (Wycheproof)

| Value | Meaning |
|---|---|
| `valid` | The implementation MUST accept the input and produce the expected output, with **no** error event. |
| `invalid` | The implementation MUST report at least one error for this input. Recovery frames listed in `expect.frames` are still required. |
| `acceptable` | Implementation-defined; any conformant behaviour is allowed. Requires at least one `flag`. |

Flags: `EdgeCase` (boundary condition), `OptionalBehavior`,
`ImplementationDefined`, `Deprecated`. There is no `Slow` flag: injected time
made real sleeps unnecessary.

### Error names

| Name | Value | Meaning |
|---|---:|---|
| `LLP_ERR_CRC` | 1 | CRC mismatch on a complete frame |
| `LLP_ERR_LEN` | 2 | `LEN` > instance capacity |
| `LLP_ERR_TIMEOUT` | 3 | inter-byte gap > `timeout_ms` |
| `LLP_ERR_SYNC` | 4 | bad escape, or a new magic inside a frame |

## Profile R1 (optional)

[`RELIABILITY.md`](RELIABILITY.md) defines an optional reliable command channel
on top of the base framing. It is **not** part of base conformance:

- Wire layout: covered by [`../vectors/reliability.json`](../vectors/reliability.json)
  (command frame `[SEQ][DATA]` on channel 1, ACK frame `[SEQ]` on channel 2).
- Behaviour (deduplication, retransmission, exhaustion): given by the trace
  table in §11 of that document. An implementation that claims R1 SHOULD ship
  those traces as unit tests; the C reference does so in
  `llp-protocol/test/test_v4_rel.c`.

An implementation that ignores the profile stays conformant with the wire
specification: profile frames are ordinary v4 frames, and the reserved channels
keep their generic meaning.

## Conformance checklist

### Encoder

- [ ] Header is `AA 55` then `LEN` then `CHANNEL`, single bytes each.
- [ ] Every `0xAA` in `LEN`, `CHANNEL`, `PAYLOAD` and `CRC` is emitted as
      `AA 00`; the magic itself is never escaped.
- [ ] CRC16-CCITT-FALSE over `AA 55 LEN CHANNEL PAYLOAD` (unescaped values).
- [ ] CRC transmitted low byte first.
- [ ] `LEN` may be 0; payload larger than 255 is rejected.

### Decoder

- [ ] Garbage while waiting for the magic is ignored, never reported as an error.
- [ ] `AA AA 55` is a valid frame start (the second `AA` is not treated as an
      escape).
- [ ] `AA 55` inside a frame reports `LLP_ERR_SYNC` and starts a new frame.
- [ ] `AA` + anything else reports `LLP_ERR_SYNC` and discards the frame.
- [ ] `AA 00` yields a literal `0xAA` in the current field.
- [ ] `LEN == 0` is valid and skips the payload.
- [ ] `LEN > capacity` reports `LLP_ERR_LEN` **before** storing any payload byte.
- [ ] CRC mismatch reports `LLP_ERR_CRC` and discards the frame.
- [ ] No payload byte is observable by the application before the CRC validates.
- [ ] `CHANNEL` is delivered with the payload and is not interpreted.

### Timing

- [ ] Timeout compares with **strictly greater than** `timeout_ms`.
- [ ] No timeout is reported in `WAIT_MAGIC1` (idle link).
- [ ] A timeout resets the frame but the offending byte is re-examined as a
      possible `0xAA` magic.
- [ ] Timestamp arithmetic is wrap-safe on 16 bits (vectors cross the 65536
      boundary mid-frame).

### Resource behaviour

- [ ] Work per byte is O(1) and does not depend on payload content.
- [ ] A parser instance never buffers more than `capacity` payload bytes.
- [ ] No dynamic allocation, no recursion, no VLAs.

## Porting to a new language

Implement three primitives and you have a conformant port:

1. `encode(channel, payload) -> bytes`
2. `Parser(capacity, timeout_ms)` with `feed(byte, now_ms) -> events`
3. The four error codes.

Then run the vectors. [`../reference/llp_v4.py`](../reference/llp_v4.py) is
~240 lines and can be transliterated directly; it was written to be readable
rather than clever.

## Consuming the vectors from another language

**C** — the corpus is emitted as a generated header, so the test suite needs no
JSON parser:

```bash
python3 tools/build_vectors.py --emit-c test/v4_vectors_generated.h
```

The header exposes `llp4_vec_encode[]` and `llp4_vec_decode[]`; the C suite
walks them and asserts exactly what the JSON says. Regenerate it in CI and fail
if it is stale, so the C fixture and the corpus can never drift apart.

**Java and others** — vendor `vectors/` and verify `MANIFEST.sha256` in CI:

```bash
cd vectors && sha256sum -c MANIFEST.sha256
```

## Adding vectors

1. Add the case to the relevant `build_*_vectors()` function in
   [`../tools/build_vectors.py`](../tools/build_vectors.py).
2. Run `python3 tools/build_vectors.py`.
3. The generator refuses to write a case that the reference implementation does
   not reproduce, so a failing self-check means the *expectation* is wrong (or
   the spec changed).
4. Commit the generator change, the regenerated JSON and the updated
   `MANIFEST.sha256` together.
