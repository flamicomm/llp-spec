# Profile R1 — Reliable command channel

**Status:** optional profile, version 1.0.0
**Applies to:** LLP wire format 4.0.0
**Normative:** this document. Vectors: [`../vectors/reliability.json`](../vectors/reliability.json).

LLP guarantees that **no corrupted frame reaches the application**, but it does
not guarantee that a frame **arrives**. Profile R1 adds *at-most-once delivery*
for a command channel on top of the existing v4 channels, without changing the
wire format.

The problem it solves: a single lost command frame stalls a sender that is
waiting for an application-level answer (for example grbl's `ok`). Blind
retransmission is not safe, because the frame may have been delivered even when
the answer was lost. A sequence number makes the retransmission safe.

---

## 1. Scope

R1 specifies:

- which channels carry commands and acknowledgements,
- the payload layout of both frame types,
- sequence-number assignment, window and retransmission rules,
- the receiver's deduplication rules,
- the invariants an implementation must hold.

R1 does **not** specify the application protocol carried inside the commands,
and does not replace application-level acknowledgements (see §9).

## 2. Channel allocation

| Channel | Constant | Direction | Meaning |
|---:|---|---|---|
| `1` | `LLP4_REL_CH_COMMAND` | sender → receiver | reliable command frames |
| `2` | `LLP4_REL_CH_ACK` | receiver → sender | acknowledgements |
| `3` | `LLP4_REL_CH_HELLO` | sender → receiver | session start: reset dedup state |

Other channels keep their generic v4 meaning (channel `0` is recommended for
unreliable / urgent traffic). Profile frames are **ordinary v4 frames**: same
magic, length, stuffing and CRC.

## 3. Payload layout

```
COMMAND (channel 1):  [ SEQ (1) | DATA (0..N) ]
ACK     (channel 2):  [ SEQ (1) ]
HELLO   (channel 3):  [ SESSION (0..1) ]        ; opaque, ignored
```

- `SEQ` is an unsigned byte, `0..255`, wrapping modulo 256.
- `DATA` is opaque to R1 and is forwarded to the application byte-for-byte.
- `N` is bounded by the receiver's payload capacity. An implementation that
  must carry more than a frame can hold splits the message into several command
  frames, each with its own `SEQ` (§5.3).
- An ACK frame carries exactly one byte. A receiver MUST ignore an ACK frame
  whose length is not 1.

## 4. Sequence numbers

- The **sender** assigns `SEQ`. It MUST increment the value by one (modulo 256)
  for every *new* command frame it sends.
- A **retransmission** MUST reuse the `SEQ` and the `DATA` of the frame it
  repeats: the retransmitted frame is byte-identical to the original.
- The same `SEQ` MUST NOT be used for different `DATA` while the frame is
  unacknowledged.
- The receiver stores the `SEQ` of the last frame it accepted (§6).

## 5. Sender rules

### 5.1 Window

The sender MUST use a window of **exactly one** outstanding command frame: it
MUST NOT send a new command frame until the previous one is acknowledged.
This makes R1 a stop-and-wait protocol: ordering is guaranteed by construction
and no sliding window or bitmap is required on the receiver.

### 5.2 Retransmission

1. Send the command frame and start a timer.
2. On an ACK with the matching `SEQ`: the command is delivered. Stop the timer
   and make the window available again.
3. On an ACK with a different `SEQ`: ignore it (a stale acknowledgement).
4. On timeout: retransmit the identical frame and restart the timer, up to
   `MAX_RETRIES` times.
5. After `MAX_RETRIES` the sender MUST report the failure to its application
   and MUST NOT silently discard the command. It MAY keep retrying at a slower
   rate while it reports the state to its application.

### 5.3 Chunking

A message larger than one frame is sent as consecutive command frames with
consecutive `SEQ` values, one window at a time. The receiver forwards `DATA` in
order, so the application observes a continuous byte stream.

### 5.4 Timers (recommended)

| Parameter | Recommended | Range |
|---|---|---|
| `ACK_TIMEOUT` | 50 ms | 20–500 ms |
| `MAX_RETRIES` | 5 | 1–10 |
| `BACKOFF` (after exhaustion) | 1000 ms | 100–10000 ms |

The timeout is a round-trip budget for one frame plus the receiver's
acknowledgement latency. It is not a delivery deadline.

### 5.5 Session start

`SEQ` is one byte, so a sender that restarts (reboot, reconnect, process
restart) would restart its sequence and could collide with the receiver's
`last_seq`; the first command after the restart would then be taken for a
duplicate and dropped.

To prevent that, before the first command of a **session** (process start or new
link) the sender MUST send a **hello** frame on channel 3 and then reset its own
`SEQ` to any value. Sending it twice is recommended, since it is not
acknowledged: losing one copy only re-opens the 1/256 collision window.

## 6. Receiver rules

1. On a command frame, the receiver MUST first verify that it can accept the
   whole `DATA` (atomic acceptance; e.g. buffer space). If it cannot, it MUST
   NOT consume the `SEQ` and MUST NOT acknowledge the frame — the sender's
   retransmission will retry later. Partial storage followed by an ACK is a
   protocol violation.
2. If `SEQ` differs from the last accepted `SEQ`, accept it: store `SEQ` as the
   new last value, deliver `DATA` to the application, then send `ACK(SEQ)`.
3. If `SEQ` equals the last accepted `SEQ`, the frame is a **retransmission**:
   send `ACK(SEQ)` again and discard `DATA`. It MUST NOT be delivered twice.
4. The receiver MUST NOT acknowledge a frame that failed the transport checks
   (CRC, length, sync). Those are discarded by the parser and no frame reaches
   this layer.
5. The receiver's state is per link and starts empty (`have_seq = false`).
6. On a **hello** frame (channel 3), the receiver MUST reset its
   duplicate-suppression state (forget `last_seq`) and MUST NOT acknowledge it.
   This is what makes a restarted sender safe (§5.5). A hello does not disturb
   an outstanding command: the sender only sends it before the first command of
   a session.

## 7. Failure handling

- Exhausted retries mean *the command frame is not being delivered*, not that it
  was executed. The sender's application decides what to do (stop, report,
  retry later).
- Because of rule §6.3, a command is executed at most once even if the link
  loses every acknowledgement.
- Implementations SHOULD expose counters for diagnostics: commands delivered,
  retransmissions retried, duplicates observed, exhausted windows.

## 8. Ordering and interleaving

- Window 1 guarantees that command frames are delivered in order.
- Frames on other channels (for example channel 0 realtime bytes or status
  reports) MAY interleave between command frames and are unaffected by R1.
  A receiver MUST route by channel and only apply R1 to channels 1 and 2.

## 9. Relationship with application-level acknowledgements

An R1 ACK means **"the DATA was accepted for delivery to the application"**. It
says nothing about whether the application parsed, accepted, rejected or
executed it.

Application-level answers (for example grbl's `ok` / `error:N`) stay on their own
channel and keep their own semantics. R1 reduces — but does not eliminate — the
case where an application answer is lost: that direction is not covered here (see
§10).

## 10. Normative invariants

| # | Invariant |
|---|---|
| I1 | A command frame is delivered to the application **at most once**. |
| I2 | A command frame is retransmitted **byte-identically** (same `SEQ`, same `DATA`). |
| I3 | Command frames are delivered in `SEQ` order (window 1). |
| I4 | An ACK is sent only after `DATA` has been fully accepted. |
| I5 | Losing an ACK never causes re-delivery. |
| I6 | A duplicate is acknowledged again, so a lost ACK cannot deadlock the sender. |

## 11. Conformance traces

These traces are the behavioural contract. An implementation SHOULD ship them as
unit tests (the C reference in `llp-protocol/test/test_v4_rel.c` implements all of
them).

| # | Events | Expected |
|---|---|---|
| T1 | sender sends `SEQ=7`; receiver accepts; ACK 7 arrives | delivered 1×, retransmissions 0, window idle |
| T2 | command frame lost (never reaches receiver); timeout; retransmit; ACK 7 | delivered 1×, one retransmission |
| T3 | command delivered; ACK lost; timeout; retransmit; receiver sees `SEQ=7` again | **delivered 1×**, duplicate ACKed, window idle |
| T4 | duplicate `SEQ=7` with different `DATA` | second frame discarded and ACKed; delivered 1× |
| T5 | `SEQ=255` then `SEQ=0` | both delivered (wrap) |
| T6 | command never acknowledged; `MAX_RETRIES` reached | sender reports exhaustion, does not claim delivery |
| T7 | ACK with an unknown `SEQ` arrives | ignored; window state unchanged |
| T8 | ACK lost and the duplicate arrives **after** the sender already gave up | receiver still ACKs; data never delivered twice |
| T9 | sender restarts, sends HELLO, then `SEQ` equal to the last one seen | hello resets the state; the command is delivered (not taken for a duplicate) |

## 12. Vectors and reference implementation

[`../vectors/reliability.json`](../vectors/reliability.json) pins the frame
layout: command frames on channel 1 with `SEQ` 0, 255 and `0xAA` (the `SEQ` byte
is payload, so it is subject to stuffing), ACK frames on channel 2, the session
hello on channel 3, and the interleaving of both channels in one byte stream.

The traces in §11 are behavioural and are not expressible as wire vectors; they
are covered by the reference implementation's self-check:

```bash
python3 tools/selftest_reliability.py          # T1-T9 + unit behaviour
```

Reference implementation: [`../reference/llp_v4_rel.py`](../reference/llp_v4_rel.py)
(`Sender` + `Receiver`; framing stays in `llp_v4.py`). The C implementation is
`llp-protocol/include/llp_v4_rel.h` with the same traces in its Unity suite.

## 13. Non-goals

- Reliability for the receiver → sender direction (status, logs, application
  answers). It would need a bounded copy of the last transmitted frame on
  memory-constrained receivers; it is a separate profile.
- Flow control. Buffering pressure is converted into "no ACK yet" (§6.1), which
  the sender's retransmission handles; there is no credit window.
- Multiplexing several reliable streams. One `SEQ` space per link and direction.
- Congestion control, checksums beyond the transport CRC, or fragmentation
  metadata (chunks are plain consecutive frames).
