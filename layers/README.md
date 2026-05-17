# Layers — `layers/*.json`

Layer-chain test vectors cover the payload format: an ordered sequence of layer headers followed by raw application data.

## Files

| File | Vectors | Description |
|------|---------|-------------|
| `passthrough.json` | 33 | Passthrough layer chains (0x01–0x7F) and FinalNode |
| `transform.json` | 13 | Transform layer chains (0x80–0xFE) |
| `malformed.json` | 4 | Malformed layer chains: truncated metadata, invalid IDs |
| `traversal.json` | 5 | Layer traversal to extract final application payload |

## Layer ID Ranges

| Range | Type | Behaviour |
|-------|------|-----------|
| `0x00` | **FinalNode** | End of layer headers; remainder is raw application data |
| `0x01`–`0x7F` | **Passthrough** | Metadata present; payload unchanged; parsers may skip to FinalNode |
| `0x80`–`0xFE` | **Transform** | Metadata present; payload transformed; parsers MUST NOT skip |
| `0xFF` | **Reserved** | Unknown; parsers may skip or report |

## Metadata Length Encoding

| Condition | Encoding |
|-----------|----------|
| `0 ≤ meta_len ≤ 254` | 1 byte: `meta_len` |
| `meta_len ≥ 255` | 3 bytes: `0xFF` + `len_high` + `len_low` (big-endian) |

## Extended Metadata

Vectors `extended_meta_zero`, `extended_meta_255`, and `extended_meta_256` test the 3-byte extended encoding. Flags are `["EdgeCase"]` because most implementations will not encounter ≥255 byte metadata frequently.

## Transform Layer Error

`transform_no_handler_decode` (in `transform.json`) validates that the transport layer successfully parses and deframes a frame containing a transform layer, but layer-chain traversal blocks with `TRANSFORM_NO_HANDLER` because no transform handler is registered. This is `result: valid` at the transport level.

## Traversal

`traversal` vectors test that a deframer can walk the layer chain and extract the raw application data following FinalNode. The transform-layer vector uses `result: invalid` with `flags: ["ImplementationDefined"]` because whether a parser blocks or skips transform layers with no handler is implementation-defined.