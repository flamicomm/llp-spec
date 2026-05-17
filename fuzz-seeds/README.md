# Fuzz Seeds — `fuzz-seeds/`

AFL/libFuzzer corpus seeds generated from official test vectors. Each seed is a minimal binary input that exercises a specific code path in an LLP implementation.

## Corpus Structure

```
fuzz-seeds/
├── empty/          # Minimal valid frames (FinalNode, 1 byte, 2 bytes)
├── stuffing/       # Byte stuffing edge cases (0xAA, 0xAA 0x55, triple 0xAA)
├── layers/         # Layer chain variants (passthrough, transform, reserved, nested)
├── errors/         # Invalid frames triggering errors (CRC, truncation, sync, etc.)
├── edge_cases/     # Boundary conditions (255/256 bytes, long chains, all IDs)
└── streams/        # Multi-frame stream seeds (concatenated frames, noise, garbage)
```

## Generating Seeds

```bash
python3 generate_fuzz_seeds.py
```

This regenerates all seeds from the official test vectors. Run after modifying `build_vectors.py` or `runner.py`.

## Seed Count

- 48 total seeds across 6 categories

## Usage with AFL

```bash
# Compile target with AFL
AFL_USE_ASAN=1 afl-gcc-fast your_llp_impl.c -o your_fuzzer

# Run with corpus
afl-fuzz -i fuzz-seeds/empty -o findings ./your_fuzzer
```

## Usage with libFuzzer

```bash
# Compile with sanitizer
clang++ -fsanitize=address,fuzzer your_llp_fuzzer.cpp -o your_fuzzer

# Run with corpus
./your_fuzzer fuzz-seeds/
```