#!/usr/bin/env python3
"""
LLP Test Vector Validator.

Validates all test vectors in transport/, layers/, parser/ against
the Python reference runner.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "interoperability" / "python"))

from runner import (
    Deframer,
    make_frame,
    make_stuffed_frame,
    traverse_layer_chain,
    FrameEvent,
)

SPEC_DIR = Path(__file__).parent


def normalize(v: str) -> str:
    return v.upper() if v else ""


def check_transport(v: dict, check_payload: bool = True) -> tuple[bool, str]:
    """Check transport-level decoding. Returns (ok, (frame, raw_payload) | error_msg)."""
    frame_hex = v["input"].get("frame_hex", "")
    frame = bytes.fromhex(frame_hex) if frame_hex else b""
    exp = v["expected"]
    outcome = exp.get("outcome", "")

    d = Deframer()
    d.process_bytes(frame)
    frames = [e for e in d.events if e.type == "FRAME"]
    errors = [e for e in d.events if e.type == "ERROR"]

    if outcome == "FRAME":
        if not frames:
            return False, f"expected FRAME, got {len(errors)} error(s)"
        if check_payload:
            exp_payload = normalize(exp.get("payload_hex", ""))
            act_payload = normalize(frames[0].payload_hex or "")
            if act_payload != exp_payload:
                return False, f"payload mismatch: expected {exp_payload}, got {act_payload}"
        if errors:
            return False, f"expected no errors, got {errors[0].error_code}"
        raw = bytes.fromhex(frames[0].payload_hex) if frames[0].payload_hex else b""
        return True, raw.hex().upper()

    if outcome == "ERROR":
        exp_error = exp.get("error_code", "")
        if exp_error == "TIMEOUT":
            if frames or errors:
                return False, f"expected TIMEOUT (no events), got {len(frames)} frame(s), {len(errors)} error(s)"
            return True, ""
        if not errors:
            return False, f"expected {exp_error}, got no error"
        act_error = errors[0].error_code
        if act_error == exp_error:
            return True, ""
        return False, f"error mismatch: expected {exp_error}, got {act_error}"

    if outcome == "NONE":
        if frames or errors:
            return False, f"expected NONE, got events"
        return True, ""

    return False, f"unknown outcome: {outcome}"


def check_decode(v: dict) -> tuple[bool, str]:
    exp = v["expected"]
    outcome = exp.get("outcome", "")
    exp_error = exp.get("error_code", "")

    # Layer-level errors need transport decode + layer traversal
    if outcome == "ERROR" and exp_error in ("LAYER_MALFORMED", "TRANSFORM_NO_HANDLER"):
        frame_hex = v["input"].get("frame_hex", "")
        frame = bytes.fromhex(frame_hex) if frame_hex else b""

        d = Deframer()
        d.process_bytes(frame)
        frames = [e for e in d.events if e.type == "FRAME"]

        if not frames:
            return False, f"transport: expected valid frame (for layer check), got no frame"

        raw = bytes.fromhex(frames[0].payload_hex) if frames[0].payload_hex else b""
        ok, err, _ = traverse_layer_chain(raw)

        if ok:
            return False, f"transport OK, layer traversal OK, but expected {exp_error}"

        if err != exp_error:
            return False, f"layer error: expected {exp_error}, got {err}"

        return True, ""

    return check_transport(v, check_payload=True)


def check_traversal(v: dict) -> tuple[bool, str]:
    """Transport decode + layer chain traversal."""
    frame_hex = v["input"].get("frame_hex", "")
    frame = bytes.fromhex(frame_hex) if frame_hex else b""
    exp = v["expected"]
    outcome = exp.get("outcome", "")

    d = Deframer()
    d.process_bytes(frame)
    frames = [e for e in d.events if e.type == "FRAME"]
    errors = [e for e in d.events if e.type == "ERROR"]

    # Transport must succeed (frame must have valid CRC)
    if not frames:
        if outcome == "ERROR":
            exp_error = exp.get("error_code", "")
            if exp_error in ("TRANSFORM_NO_HANDLER", "LAYER_MALFORMED"):
                if errors:
                    return False, f"transport error ({errors[0].error_code}) but expected {exp_error} at layer level"
                return False, f"transport produced no frame but no transport error either"
        return check_transport(v, check_payload=False)

    raw_hex = frames[0].payload_hex or ""
    raw = bytes.fromhex(raw_hex) if raw_hex else b""

    # Traverse layer chain
    trav_ok, trav_error, final_payload = traverse_layer_chain(raw)

    if outcome == "FRAME":
        if not trav_ok:
            return False, f"transport OK but layer traversal failed: {trav_error}"
        exp_final = normalize(exp.get("final_payload_hex", ""))
        act_final = normalize(final_payload.hex().upper()) if final_payload else ""
        if act_final != exp_final:
            return False, f"final payload: expected {exp_final}, got {act_final}"
        return True, ""

    if outcome == "ERROR":
        exp_error = exp.get("error_code", "")
        if trav_ok:
            return False, f"expected error {exp_error} but traversal succeeded (final={final_payload.hex()})"
        if trav_error != exp_error:
            return False, f"layer error: expected {exp_error}, got {trav_error}"
        return True, ""

    return False, f"unknown traversal outcome: {outcome}"


def check_encode(v: dict) -> tuple[bool, str]:
    payload_hex = v["input"].get("llp_payload_hex", "")
    payload = bytes.fromhex(payload_hex) if payload_hex else b""
    exp_frame = normalize(v["expected"].get("frame_hex", ""))

    frame = make_frame(payload)
    if normalize(frame.hex()) == exp_frame:
        return True, ""

    if 0xAA in payload:
        frame = make_stuffed_frame(payload)
        if normalize(frame.hex()) == exp_frame:
            return True, ""

    return False, f"frame mismatch: expected {exp_frame}, got {frame.hex().upper()}"


def check_stream(v: dict) -> tuple[bool, str]:
    chunks = [bytes.fromhex(ch) for ch in v["input"].get("chunks_hex", [])]
    expected = v["expected"].get("events", [])

    d = Deframer()
    for chunk in chunks:
        d.process_bytes(chunk)
    actual = d.events

    if len(actual) != len(expected):
        return False, f"event count: expected {len(expected)}, got {len(actual)}"

    for i, (exp, act) in enumerate(zip(expected, actual)):
        if exp["type"] != act.type:
            return False, f"event {i} type: expected {exp['type']}, got {act.type}"
        if act.type == "FRAME":
            exp_p = normalize(exp.get("payload_hex", ""))
            act_p = normalize(act.payload_hex or "")
            if act_p != exp_p:
                return False, f"event {i} payload: expected {exp_p}, got {act_p}"
        elif act.type == "ERROR":
            exp_e = exp.get("error_code", "")
            act_e = act.error_code or ""
            if act_e != exp_e:
                return False, f"event {i} error: expected {exp_e}, got {act_e}"
    return True, ""


def check_timing(v: dict) -> tuple[bool, str]:
    timeout_ms = v["config"]["timeout_ms"]
    events_in = v["input"]["events"]
    expected = v["expected"].get("events", [])

    d = Deframer(timeout_ms=timeout_ms)
    start = time.time() * 1000
    last_rel = 0

    for ev_in in events_in:
        b = bytes.fromhex(ev_in["byte_hex"])[0]
        t = ev_in["time_ms"]
        sleep = (t - last_rel) / 1000.0
        if sleep > 0:
            time.sleep(sleep)
        last_rel = t
        elapsed = (time.time() * 1000) - start
        if t > elapsed:
            time.sleep((t - elapsed) / 1000.0)
        d.process_byte(b, time.time() * 1000)

    actual = d.events

    if len(actual) != len(expected):
        return False, f"event count: expected {len(expected)}, got {len(actual)}"

    for i, (exp, act) in enumerate(zip(expected, actual)):
        if exp["type"] != act.type:
            return False, f"event {i} type: expected {exp['type']}, got {act.type}"
        if act.type == "FRAME":
            exp_p = normalize(exp.get("payload_hex", ""))
            act_p = normalize(act.payload_hex or "")
            if act_p != exp_p:
                return False, f"event {i} payload: expected {exp_p}, got {act_p}"
        elif act.type == "ERROR":
            exp_e = exp.get("error_code", "")
            act_e = act.error_code or ""
            if act_e != exp_e:
                return False, f"event {i} error: expected {exp_e}, got {act_e}"
    return True, ""


CHECKERS = {
    "decode": check_decode,
    "encode": check_encode,
    "stream": check_stream,
    "timing": check_timing,
    "traversal": check_traversal,
}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LLP Test Vector Validator")
    parser.add_argument("--include-slow", action="store_true",
                        help="Include Slow-flagged timing vectors (default: skip)")
    args = parser.parse_args()

    root = SPEC_DIR
    passed = 0
    failed = 0
    skipped = 0
    slow_skipped = 0

    print("LLP Test Vector Validator")
    print(f"  --include-slow: {'yes' if args.include_slow else 'no'}")
    print()

    for dirname in ["transport", "layers", "parser"]:
        d = root / dirname
        if not d.is_dir():
            continue
        for fn in sorted(d.iterdir()):
            if fn.suffix != ".json":
                continue
            with open(fn) as f:
                data = json.load(f)
            for v in data["vectors"]:
                typ = v.get("type", "")
                checker = CHECKERS.get(typ)
                if checker is None:
                    print(f"SKIP  {fn.name}/{v['name']}: no checker for type '{typ}'")
                    skipped += 1
                    continue

                if "Slow" in v.get("flags", []) and not args.include_slow:
                    slow_skipped += 1
                    continue

                try:
                    ok, msg = checker(v)
                except Exception as e:
                    ok, msg = False, str(e)
                    import traceback
                    traceback.print_exc()

                if ok:
                    passed += 1
                else:
                    failed += 1
                    print(f"FAIL  {fn.name}/{v['name']}: {msg}")

    total = passed + failed + skipped + slow_skipped
    print(f"\n{'=' * 40}")
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}  Slow: {slow_skipped}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
