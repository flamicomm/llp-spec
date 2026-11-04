"""Conformance vector driver for LLP wire format 4.0.0.

This module does **not** implement the protocol: it imports the vendored
reference implementation (``reference/llp_v4.py``) and turns a JSON vector into
an observable outcome. Keeping the two roles apart is what makes the vectors a
real contract — if the driver reimplemented CRC or deframing, a bug could cancel
itself out.

Public API:

    run(case)    -> Outcome        apply one vector case
    check(case)  -> list[str]      compare against ``expect``; [] means pass

A case is a dict as described by ``schema/vector.schema.json`` (schema 2.0.0)
and by ``docs/CONFORMANCE.md``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "reference"
if str(REFERENCE) not in sys.path:
    sys.path.insert(0, str(REFERENCE))

import llp_v4 as llp  # noqa: E402

# Canonical error names, in the order the specification lists them.
ERROR_NAMES = (llp.ERR_CRC, llp.ERR_LEN, llp.ERR_TIMEOUT, llp.ERR_SYNC)
KINDS = ("encode", "decode", "stream")


@dataclass
class Outcome:
    """Everything a case can observe: delivered frames, errors, timeout count."""

    frames: list = field(default_factory=list)   # [(channel, payload_bytes)]
    errors: list = field(default_factory=list)   # [error name]
    timeouts: int = 0

    def describe(self) -> str:
        frames = ", ".join(f"ch{ch}:{pl.hex() or '-'}" for ch, pl in self.frames) or "-"
        errors = ", ".join(self.errors) or "-"
        return f"frames=[{frames}] errors=[{errors}] timeouts={self.timeouts}"


@dataclass
class CaseResult:
    """A case plus the outcome of running it, for reporting."""

    case_id: str
    kind: str
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


# --------------------------------------------------------------------------
# Feeding
# --------------------------------------------------------------------------
def steps(case: dict) -> list[tuple[int, int]]:
    """Expand a case into ``(byte, dt_ms)`` steps.

    A decode case carries either ``frame`` (compact: every byte with dt 0) or
    ``feed`` (explicit: needed for timed gaps). The schema forbids both.
    """
    if "feed" in case:
        return [(int(step["hex"], 16), int(step["dt_ms"])) for step in case["feed"]]
    return [(byte, 0) for byte in bytes.fromhex(case["frame"])]


def _parser_for(case: dict) -> "llp.Parser":
    return llp.Parser(
        capacity=case.get("capacity", llp.MAX_PAYLOAD),
        timeout_ms=case.get("timeout_ms", llp.DEFAULT_TIMEOUT_MS),
    )


def run(case: dict) -> Outcome:
    """Apply one decode or stream case and return what the parser observed."""
    parser = _parser_for(case)
    outcome = Outcome()

    if case["kind"] == "stream":
        chunks = [bytes.fromhex(chunk) for chunk in case["chunks"]]
        pairs = [(byte, 0) for chunk in chunks for byte in chunk]
    else:
        pairs = steps(case)

    now = 0
    for byte, dt_ms in pairs:
        now += dt_ms
        for event in parser.feed(byte, now):
            if event[0] == "frame":
                outcome.frames.append((event[1], event[2]))
            elif event[0] == "error":
                outcome.errors.append(event[1])

    outcome.timeouts = parser.timeouts
    return outcome


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------
def _expected(case: dict) -> Outcome:
    expect = case["expect"]
    return Outcome(
        frames=[(f["channel"], bytes.fromhex(f["payload"])) for f in expect["frames"]],
        errors=list(expect["errors"]),
        timeouts=int(expect["timeouts"]),
    )


def _compare(got: Outcome, want: Outcome) -> list[str]:
    problems = []
    if got.frames != want.frames:
        got_f = [(ch, pl.hex()) for ch, pl in got.frames]
        want_f = [(ch, pl.hex()) for ch, pl in want.frames]
        problems.append(f"frames: got {got_f} want {want_f}")
    if got.errors != want.errors:
        problems.append(f"errors: got {got.errors} want {want.errors}")
    if got.timeouts != want.timeouts:
        problems.append(f"timeouts: got {got.timeouts} want {want.timeouts}")
    return problems


def _unknown_errors(errors) -> list[str]:
    return [name for name in errors if name not in ERROR_NAMES]


def check(case: dict) -> list[str]:
    """Verify one case against the reference implementation.

    Returns a list of human-readable problems; an empty list means the case
    passes. ``result: "invalid"`` cases must additionally deliver no frame,
    so that an implementation which silently accepts them cannot pass.
    """
    kind = case.get("kind")
    if kind not in KINDS:
        return [f"unknown kind: {kind!r}"]

    if kind == "encode":
        channel = case["channel"]
        payload = bytes.fromhex(case["payload"])
        expected_frame = case["frame"].lower()

        problems = []
        generated = llp.encode(channel, payload)
        if generated.hex() != expected_frame:
            problems.append(
                f"frame: got {generated.hex()} want {expected_frame}"
            )
            return problems

        # Every encoded frame must decode back to the same (channel, payload).
        round_trip = run(
            {
                "kind": "decode",
                "capacity": llp.MAX_PAYLOAD,
                "timeout_ms": llp.DEFAULT_TIMEOUT_MS,
                "frame": expected_frame,
            }
        )
        want = Outcome(frames=[(channel, payload)], errors=[], timeouts=0)
        problems.extend(_compare(round_trip, want))
        return problems

    got = run(case)
    want = _expected(case)
    problems = _compare(got, want)

    bad_names = _unknown_errors(want.errors)
    if bad_names:
        problems.append(f"unknown error names in expectation: {bad_names}")

    # Wycheproof semantics: an `invalid` case must be rejected (at least one
    # error event), and a `valid` case must not produce any error at all. This
    # catches implementations that silently accept corrupt input without
    # pinning *which* frame a recovery case is allowed to deliver.
    if case.get("result") == "invalid" and not got.errors:
        problems.append("result is 'invalid' but no error was reported")
    if case.get("result") == "valid" and got.errors:
        problems.append(f"result is 'valid' but errors were reported: {got.errors}")

    return problems
