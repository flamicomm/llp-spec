#!/usr/bin/env python3
"""Self-check for the Profile R1 reference implementation.

Runs the conformance traces of ``docs/RELIABILITY.md`` §11 (T1–T9) plus the
unit behaviour the profile depends on (byte-identical retransmission, 16-bit
clock wrap, exhaustion never claiming delivery, chunking).

Usage:
    python3 tools/selftest_reliability.py          # summary
    python3 tools/selftest_reliability.py --verbose

Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "reference"))

import llp_v4_rel as rel  # noqa: E402

FAILURES = 0


def check(label: str, condition: bool) -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
        print(f"FAIL  {label}")
    elif "--verbose" in sys.argv:
        print(f"ok    {label}")


def new_pair(timeout_ms: int = 50, max_retries: int = 5, backoff_ms: int = 1000):
    return rel.Sender(timeout_ms, max_retries, backoff_ms), rel.Receiver()


# ---------------------------------------------------------------------------
# Unit behaviour
# ---------------------------------------------------------------------------

def unit_checks() -> None:
    sender, receiver = new_pair()
    check("sender starts idle", sender.service(0) == rel.TX_IDLE)

    # A frame is ready as soon as it is loaded, and the payload is [SEQ][DATA].
    check("start accepts a command", sender.start(3, b"G1 X0\n", 100))
    check("payload is [SEQ][DATA]", sender.payload == b"\x03G1 X0\n")

    # Retransmission after the timeout is byte-identical.
    first = sender.payload
    check("idle before the timeout", sender.service(149) == rel.TX_IDLE)
    check("retransmit at the timeout", sender.service(150) == rel.TX_SEND)
    check("retransmission is byte-identical", sender.payload == first)
    check("retries counted", sender.retries == 1)

    # Oversized data and a busy window are rejected.
    check("busy window rejected", not sender.start(4, b"x", 200))
    check("oversized data rejected", not rel.Sender().start(0, b"x" * (rel.MAX_DATA + 1), 0))

    # Stale ACKs are ignored.
    check("stale ACK ignored", not sender.on_ack(2))
    check("matching ACK releases", sender.on_ack(3))
    check("window idle after ACK", not sender.active)

    # 16-bit clock wrap.
    sender, _ = new_pair()
    sender.start(1, b"x", 0xFFF0)
    check("wrap: still inside the window", sender.service((0xFFF0 + 49) & 0xFFFF) == rel.TX_IDLE)
    check("wrap: timeout fires", sender.service((0xFFF0 + 50) & 0xFFFF) == rel.TX_SEND)

    # Backoff after the fast retries: reported at the timeout boundary, then
    # once per backoff period, never as delivery.
    sender, _ = new_pair(timeout_ms=50, max_retries=2, backoff_ms=1000)
    sender.start(1, b"x", 0)
    check("retry 1", sender.service(50) == rel.TX_SEND)
    check("retry 2", sender.service(100) == rel.TX_SEND)
    check("exhausted after the last retry times out", sender.service(150) == rel.TX_EXHAUSTED)
    check("backoff: silent", sender.service(1149) == rel.TX_IDLE)
    check("backoff: exhausted again", sender.service(1150) == rel.TX_EXHAUSTED)

    # Receiver basics and wrap.
    _, receiver = new_pair()
    check("first frame delivered", receiver.accept(255))
    check("wrap to 0 delivered", receiver.accept(0))
    check("repeat of 0 is a duplicate", not receiver.accept(0))
    check("delivered counter", receiver.delivered == 2)
    check("duplicates counter", receiver.duplicates == 1)

    # Payload helpers and chunking.
    check("ack payload", rel.ack_payload(7) == b"\x07")
    check("hello payload", rel.hello_payload() == b"\x52")
    pieces = list(rel.chunks(bytes(range(200)), 63))
    check("chunking sizes", [len(p) for p in pieces] == [63, 63, 63, 11])
    check("chunking preserves data", b"".join(pieces) == bytes(range(200)))
    try:
        rel.command_payload(0, b"x" * (rel.MAX_DATA + 1))
    except ValueError:
        check("oversized command_payload raises", True)
    else:
        check("oversized command_payload raises", False)


# ---------------------------------------------------------------------------
# Conformance traces (RELIABILITY.md §11)
# ---------------------------------------------------------------------------

def trace_t1() -> None:
    sender, receiver = new_pair()
    sender.start(7, b"G1 X0\n", 0)
    check("T1 delivered once", receiver.accept(7))
    check("T1 ACK releases", sender.on_ack(7))
    check("T1 no retransmission", sender.retries == 0 and not sender.active)


def trace_t2() -> None:
    sender, receiver = new_pair()
    sender.start(11, b"G1 X1\n", 0)          # first transmission is lost
    check("T2 retransmits", sender.service(50) == rel.TX_SEND)
    check("T2 retransmission delivered", receiver.accept(11))
    check("T2 ACK releases", sender.on_ack(11))
    check("T2 delivered once", receiver.delivered == 1)


def trace_t3() -> None:
    sender, receiver = new_pair()
    sender.start(21, b"G1 X2\n", 0)
    check("T3 delivered", receiver.accept(21))
    # The ACK is lost, so the sender retransmits.
    check("T3 retransmits", sender.service(50) == rel.TX_SEND)
    check("T3 duplicate suppressed", not receiver.accept(21))
    check("T3 delivered once", receiver.delivered == 1)
    check("T3 duplicate counted", receiver.duplicates == 1)
    check("T3 late ACK releases", sender.on_ack(21))


def trace_t4() -> None:
    _, receiver = new_pair()
    check("T4 first delivered", receiver.accept(33))
    check("T4 same SEQ, other DATA discarded", not receiver.accept(33))
    check("T4 delivered once", receiver.delivered == 1)


def trace_t5() -> None:
    sender, receiver = new_pair()
    sender.start(255, b"a", 0)
    check("T5 255 delivered", receiver.accept(255))
    sender.on_ack(255)
    sender.start(0, b"b", 0)
    check("T5 0 delivered", receiver.accept(0))
    check("T5 both delivered", receiver.delivered == 2)


def trace_t6() -> None:
    sender, _ = new_pair(timeout_ms=50, max_retries=3, backoff_ms=1000)
    sender.start(44, b"x", 0)
    check("T6 retry 1", sender.service(50) == rel.TX_SEND)
    check("T6 retry 2", sender.service(100) == rel.TX_SEND)
    check("T6 retry 3", sender.service(150) == rel.TX_SEND)
    check("T6 reports exhaustion", sender.service(200) == rel.TX_EXHAUSTED)
    check("T6 still not delivered", sender.active)


def trace_t7() -> None:
    sender, _ = new_pair()
    sender.start(5, b"x", 0)
    check("T7 stale ACK 4 ignored", not sender.on_ack(4))
    check("T7 stale ACK 6 ignored", not sender.on_ack(6))
    check("T7 window untouched", sender.active)


def trace_t8() -> None:
    sender, receiver = new_pair(max_retries=1)
    sender.start(60, b"x", 0)
    check("T8 delivered", receiver.accept(60))
    check("T8 retransmits", sender.service(50) == rel.TX_SEND)
    check("T8 duplicate suppressed", not receiver.accept(60))
    check("T8 exhaustion", sender.service(100) == rel.TX_EXHAUSTED)
    for _ in range(2):
        check("T8 late duplicate still suppressed", not receiver.accept(60))
    check("T8 delivered once", receiver.delivered == 1)


def trace_t9() -> None:
    _, receiver = new_pair()
    check("T9 first delivered", receiver.accept(5))
    check("T9 duplicate before hello", not receiver.accept(5))
    receiver.reset()                       # HELLO on channel 3
    check("T9 same SEQ after hello is delivered", receiver.accept(5))
    check("T9 counters start over", receiver.delivered == 1 and receiver.duplicates == 0)


def main() -> int:
    unit_checks()
    for trace in (trace_t1, trace_t2, trace_t3, trace_t4, trace_t5,
                  trace_t6, trace_t7, trace_t8, trace_t9):
        trace()

    print()
    if FAILURES:
        print(f"FAIL  {FAILURES} check(s) failed")
        return 1
    print("ok    Profile R1 reference: all checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
