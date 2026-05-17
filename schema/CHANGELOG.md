# Schema Changelog

All schema versions are independent of the protocol version (`spec_version` in vector files).
The schema describes the structure of vector files; the protocol version lives in each vector file.

## v1.1.0 — 2026-05-14

- Added `Slow` to the `flag` enum. Timing vectors that require real-time sleeps (> 5 simulated seconds)
  are now flagged `Slow` and skipped by default in `validate_vectors.py`.
- Added `$comment` field documenting the schema version.

**Migration**: Update `$id` to point to v1.1.0. No changes to vector file structure.

## v1.0.0 — 2026-05-14

- Initial release. Supports vector types: `encode`, `decode`, `stream`, `timing`, `traversal`.
- Result model: `valid`, `invalid`, `acceptable`.
- Flags: `OptionalBehavior`, `EdgeCase`, `ImplementationDefined`, `Deprecated`.

## Design Notes

- The schema uses JSON Schema draft-07 `if`/`then`/`else` for conditional per-type validation.
- `spec_version` in each vector file is the *protocol* version (e.g. `"3.1.0"`), independent of the schema version.
- `result: "acceptable"` vectors MUST have at least one flag; the flag documents the ambiguity.
- Every vector file must pass schema validation before it can be used with `validate_vectors.py`.