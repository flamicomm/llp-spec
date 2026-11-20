# Vendored reference implementation

The files in this directory are **byte-identical copies** of the reference
implementation of wire format 4.0.0 and of the R1 reliable channel profile.
They are vendored, not forked: the canonical copies live in the library
repository and these files must never be edited here.

| File | Source | sha256 |
|---|---|---|
| `llp_v4.py` | `llp-protocol/scripts/llp_v4.py` | `d0fd05c99752274708515635c1dcffbe0900984ecb05f0d069142b747293e739` |
| `llp_v4_rel.py` | `llp-protocol/scripts/llp_v4_rel.py` | `a6161a5188d668c48a009bc0b82aabdcc1cd2ff38fb79f69f4b2aeec605fd4c2` |

| | |
|---|---|
| Source commit | `6200cac` (CNC-030 Ola 2, PR #16) |
| Vendored on | 2026-11-20 |

## Why a copy instead of a git submodule

A submodule would couple every clone of the specification repository to the
library repository's branch, and the specification must stay usable offline.
The copies are cheap, and the checks below make drift detectable.

## Checking

Self-contained (runs in CI, no network):

```bash
python3 tools/check_vendor.py
```

Against a local checkout of the library:

```bash
python3 tools/check_vendor.py \
    --against ../llp-protocol/scripts/llp_v4.py \
    --against ../llp-protocol/scripts/llp_v4_rel.py
```

The weekly `drift-watch` workflow (`.github/workflows/drift-watch.yml`) fetches
the published `main` branch and diffs `llp_v4.py` against it. It warns, it does
not block pull requests: a change to the reference is a specification change and
has to go through review here first. It does not cover `llp_v4_rel.py` yet;
`tools/check_vendor.py` does pin that file, and the workflow should compare both
copies when it is next touched.

## Updating

1. Change the reference in the library repository and commit it there.
2. Copy the files over these ones
   (`cp .../scripts/llp_v4*.py reference/`).
3. Recompute the hashes and update the table above:

   ```bash
   sha256sum reference/llp_v4.py reference/llp_v4_rel.py
   ```

4. Run `python3 tools/build_vectors.py` and commit the regenerated vectors in
   the same change. A reference change that alters the wire format requires a
   new ADR in `llp-protocol` **and** a new `spec` version here.
