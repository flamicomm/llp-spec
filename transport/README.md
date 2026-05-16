# Transport — `transport/*.json`

Transport-layer test vectors cover the wire-format framing: magic bytes, length encoding, CRC16-CCITT integrity check, and byte stuffing/unstuffing.

## Files

| File | Vectors | Description |
|------|---------|-------------|
| `valid.json` | 69 | Valid frame encode/decode round-trips and multi-frame streams |
| `crc.json` | 28 | CRC error detection: bit flips, byte swaps, all-zeros/ones, wrong CRC, payload corruption |
| `stuffing.json` | 8 | Byte stuffing edge cases: magic overlap, invalid escape sequences |
| `truncation.json` | 10 | Truncated frames at every field boundary |
| `resync.json` | 8 | Resynchronisation after noise and corruption |
| `timeout.json` | 5 | Timeout behaviour between bytes (4 of 5 are `Slow`-flagged) |

## What Each Category Tests

### `valid.json`
Encode: given a layer chain (`llp_payload_hex`), the framer produces the exact `frame_hex`.
Decode: given a valid frame, the deframer returns the exact layer chain and no error.
Stream: multiple valid frames concatenated in one byte stream produce frames in the correct order.

### `crc.json`
Every vector has an invalid CRC. The deframer MUST reject with `CHECKSUM`. Tests bit-level CRC sensitivity.

### `stuffing.json`
Valid stuffing: payload bytes `0xAA` are escaped with `0x00` — parser restores them correctly.
Invalid stuffing: `0xAA` followed by a byte other than `0x00` or `0x55` → `SYNC_ERROR`.
`0xAA 0x55` in the payload (stuffed) must NOT trigger resync.

### `truncation.json`
At every byte boundary within a frame (after magic1, after magic2, after each length byte, mid-payload, after first CRC byte), a partial frame must eventually produce a `TIMEOUT` error (after the inter-byte timeout elapses).

### `resync.json`
Garbage bytes before, between, or inside frames must be silently discarded. Parser recovers and finds the next valid frame.

### `timeout.json`
After any byte, if `LLP_FRAME_TIMEOUT_MS` (default 2000 ms) elapses before the frame completes, the parser emits `TIMEOUT` and resets. The `timeout_then_aa_triggers_resync` vector is `acceptable` — both behaviours (discard the 0xAA or use it as the start of a new frame) are conformant.

## Slow Vectors

Four of the five timing vectors require real-time sleep to simulate inter-byte gaps > 5 seconds. These are flagged `Slow` and skipped by default:

```bash
python3 validate_vectors.py                 # fast only (195 vectors)
python3 validate_vectors.py --include-slow  # all 199 vectors
```

## Reference Algorithm (CRC16-CCITT)

```
poly=0x1021, init=0xFFFF, no XOR out, no reflection
Input: MAGIC1 + MAGIC2 + LEN_L + LEN_H + (unstuffed payload bytes)
Known vector: "123456789" (ASCII) → 0x29B1
```