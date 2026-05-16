# Parser — `parser/*.json`

Parser-state-machine test vectors cover incremental parsing, fragment boundaries, and error recovery.

## Files

| File | Vectors | Description |
|------|---------|-------------|
| `incremental.json` | 5 | Byte-by-byte and varied-chunk parsing |
| `fragmented.json` | 6 | Frame fragments split across chunk boundaries |
| `recovery.json` | 5 | Recovery after CRC, timeout, sync error, garbage |

## What Each Category Tests

### `incremental.json`
The deframer is fed one byte at a time (or in small chunks). Every intermediate state must be valid. The state machine must not assume any minimum chunk size.

### `fragmented.json`
Frames are intentionally split at every field boundary and every byte of a stuffed sequence. The parser must reassemble correctly without false resync.

### `recovery.json`
After each error type, the deframer must:
1. Reset to `WAIT_MAGIC1`
2. Scan for the next `0xAA` magic byte
3. Continue processing subsequent bytes

Garbage between frames must be silently discarded. Multiple consecutive errors must not break the parser permanently.

## Parser State Machine

```
WAIT_MAGIC1 --0xAA--> WAIT_MAGIC2 --0x55--> READ_LEN_L --> READ_LEN_H
                                                           |
READ_CRC_H <-- READ_CRC_L <-----------------------------+  |
    ^                                                      |
    |              READ_PAYLOAD ---------------------------+

Any error (CHECKSUM, TIMEOUT, SYNC_ERROR) or timeout --> WAIT_MAGIC1
```

## Timeout Rule

Timer starts on `MAGIC1`, resets on every byte, and fires when `LLP_FRAME_TIMEOUT_MS` (default 2000 ms) is exceeded. On timeout: reset to `WAIT_MAGIC1`. If the current byte is `0xAA`, the parser may transition directly to `WAIT_MAGIC2` (optimistic resync).