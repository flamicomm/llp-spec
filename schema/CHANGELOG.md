# Schema Changelog

All schema versions are independent of the protocol version (`spec` in vector
files). The schema describes the structure of vector files; the protocol version
lives in each vector file.

## v2.0.0 — 2026-11-03

Breaking: follows the wire-format 4.0.0 rewrite.

- `spec_version` → `spec`, now `const "llp/4.0.0"` (same field name as the
  reference implementation's generated vectors).
- `vectors` → `cases`; new required fields `schema_version` and `generated_by`.
- Case identity: `name` → `id` (`kebab-case`, `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`).
- `type` → `kind`; the value set is `encode`, `decode`, `stream`. **`traversal`
  is removed** (v4 has no layer chain to traverse).
- `input` / `expected` are gone. Fields are now flat, matching the C repository's
  vector shape: `channel` + `payload` + `frame` for encode; `capacity` +
  `timeout_ms` + `frame` XOR `feed` + `expect` for decode; `chunks` for stream.
- `channel` is required in encode cases and in every expected frame.
- `capacity` (0..255) and `timeout_ms` (1..32767) are required on decode and
  stream cases, because `LLP_ERR_LEN` and timed gaps are per-instance behaviour.
- Decode cases carry **either** `frame` (compact, every byte with `dt_ms = 0`)
  **or** `feed` (`[{hex, dt_ms}]`, required for timed gaps). The schema enforces
  the XOR. Time is **injected and simulated**, so there are no real sleeps.
- Error codes are the wire names: `LLP_ERR_CRC`, `LLP_ERR_LEN`,
  `LLP_ERR_TIMEOUT`, `LLP_ERR_SYNC`. The v3 names (`CHECKSUM`,
  `PAYLOAD_LEN_INVALID`, `SYNC_ERROR`, `LAYER_MALFORMED`,
  `TRANSFORM_NO_HANDLER`, `BUFFER_FULL`) are gone.
- `Slow` removed from the flag enum: no vector needs real time any more.
- Hex strings are **lowercase**, without separators.
- `result: "acceptable"` still requires at least one flag.

**Migration**: v3 vector files are not convertible in place (LEN became 1 byte,
a `CHANNEL` byte was added to the header and to the CRC coverage), so every
`frame`/`frame_hex` must be regenerated. The v3 corpus remains in branch
`feature/v3.1.0`; this repository's `main` only carries v4 vectors.

## v1.1.0 — 2026-05-14

- Added `Slow` to the `flag` enum. Timing vectors that require real-time sleeps
  (> 5 simulated seconds) were flagged `Slow` and skipped by default.
- Added `$comment` documenting the schema version.

## v1.0.0 — 2026-05-14

- Initial release. Vector types: `encode`, `decode`, `stream`, `timing`,
  `traversal`.
- Result model: `valid`, `invalid`, `acceptable`.
- Flags: `OptionalBehavior`, `EdgeCase`, `ImplementationDefined`, `Deprecated`.

## Design Notes

- Per-kind validation uses draft-07 `oneOf` over three case schemas, each with
  `additionalProperties: false`, so a field that belongs to another kind is
  rejected instead of silently ignored.
- `spec` in each vector file is the *protocol* version, independent of the
  schema version.
- `result: "invalid"` requires at least one error event, and `result: "valid"`
  forbids any error. Both are enforced by the driver, not by the schema.
- Every vector file must pass schema validation before it can be used with
  `tools/validate_vectors.py`.
