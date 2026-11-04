# Vendored reference implementation

`llp_v4.py` in this directory is a **byte-identical copy** of the reference
implementation of wire format 4.0.0. It is vendored, not forked: the canonical
copy lives in the library repository and this file must never be edited here.

| | |
|---|---|
| Source | `llp-protocol/scripts/llp_v4.py` |
| Source commit | `cf8c35d` (tag `v4.0.0`) |
| sha256 | `0d9c2e81d077c05aa5f5b9160ba8fb5215b05a185d9dd70802967793bb745b35` |
| Vendored on | 2026-11-03 |

## Why a copy instead of a git submodule

A submodule would couple every clone of the specification repository to the
library repository's branch, and the specification must stay usable offline.
The copy is cheap (243 lines), and the checks below make drift detectable.

## Checking

Self-contained (runs in CI, no network):

```bash
python3 tools/check_vendor.py
```

Against a local checkout of the library:

```bash
python3 tools/check_vendor.py --against ../llp-protocol/scripts/llp_v4.py
```

The scheduled `drift-watch` workflow performs the same comparison against the
published `main` branch once a week. It reports a warning, it does not block
pull requests: a change to the reference is a specification change and has to
go through review here first.

## Updating

1. Change the reference in the library repository and commit it there.
2. Copy the file over this one (`cp .../scripts/llp_v4.py reference/llp_v4.py`).
3. Recompute the hash and update the table above:

   ```bash
   sha256sum reference/llp_v4.py
   ```

4. Run `python3 tools/build_vectors.py` and commit the regenerated vectors in
   the same change. A reference change that alters the wire format requires a
   new ADR in `llp-protocol` **and** a new `spec` version here.
