# Skybridge (Experimental)

> **Experimental extension, not part of the stable core.** This build is
> software-only. It renders and decodes baseband audio. It cannot key a
> transmitter, select a frequency, set RF power, or drive an SDR.

Skybridge is a low-bandwidth, plaintext frame transport intended for future
HF/radio use. It is an independent design and is not wire-compatible with any
existing amateur-radio protocol.

## Layers

| Layer | Module | Status |
| --- | --- | --- |
| Frame codec | `src/rig/skybridge/frame.rs` | Implemented |
| Integrity | CRC-16/X.25 (`frame.rs`) | Implemented; detects corruption, **not** authentication |
| Modem / baseband | `src/rig/skybridge/modem.rs` | Implemented (software BFSK) |
| Transport adapter | `SkybridgeTransport` (`skybridge/mod.rs`) | Implemented (WAV/memory sinks and sources) |
| Receive pipeline | samples → demodulate → frame + CRC → restricted inbox | Implemented |
| Radio backend | `src/rig/skybridge/radio.rs` | Interface only; the single backend is permanently disabled |

## Frame format (version 1)

```text
offset  size  field
0       2     magic "SB"
2       1     version (1)
3       1     flags: bit 0 = final fragment; bits 1-7 reserved (must be 0)
4       1     station id length N (1..=9)
5       N     station id, ASCII A-Z 0-9 '/' '-'
5+N     2     sequence number (big-endian)
7+N     1     payload length L (0..=200)
8+N     L     UTF-8 plaintext payload (no control chars except \n \t)
8+N+L   2     CRC-16/X.25 over all preceding bytes (big-endian)
```

Payloads are plaintext by design. There is no encryption or compression
field, and binary payloads are rejected. Decoding is strict: truncation, bad
magic or version, reserved flags, oversized or non-plaintext payloads, CRC
mismatch and trailing bytes are all errors.

## Modem

Continuous-phase binary FSK at 100 baud. Mark is 1700 Hz and space is 1500 Hz,
at an 8000 Hz sample rate, with Goertzel tone detection over one symbol.
Line format: a 32-bit `1010…` preamble, sync word `0x2DD4`, the frame bytes
MSB-first, then an 8-bit tail. The demodulator searches symbol-timing offsets
and sync positions and accepts a frame only when it decodes and its CRC
matches. A maximum frame (219 bytes) takes about 18 s of airtime.

## CLI

```bash
rain rig radio status
rain rig radio encode --station N0CALL --text "measurement 12.5 Hz" --out frame.wav
rain rig radio decode --input frame.wav          # or --json
```

`encode` builds an operator proposal and runs it through the action boundary
(size and plaintext validation). The disposition is recorded in
`<workspace>/rig/dispositions.jsonl` before a PCM16 mono WAV file is written.
It refuses to overwrite an existing file unless you pass `--force`. `decode`
passes the frame through the restricted inbox, so a payload such as
`!shell reboot` becomes an inert `Note`.

## Why RF transmit cannot happen

Two independent guards:

1. The action boundary rejects every `RadioTransmit` proposal, even from an
   operator with an approval. No `AuthorizedAction` for radio can exist.
2. The only compiled-in backend, `DisabledRfBackend`, refuses every
   `transmit` call regardless of the token, and reports `can_transmit() = false`.

No code in this build has a frequency, PTT, power, or SDR API.

## Regulatory notes

Amateur-radio rules generally require a licensed operator, station
identification, and plaintext (unencrypted) content. They also restrict which
frequencies and emissions may be used. Skybridge keeps payloads plaintext and
carries a station field, but **this build does not transmit**, and nothing
here authorizes anyone to do so. A station id passed to `encode` is only a
label.

## Next steps for radio hardware

1. Implement `RfTransmitBackend` for a specific device behind a Cargo feature
   that is off by default.
2. Add an explicit, recorded operator authorization flow for `RadioTransmit`:
   licensed callsign, band plan, frequency, and power set by a human, never by
   a model. Keep the boundary's deterministic checks authoritative.
3. Add receive-only SDR input as a `BasebandSource` before adding any transmit
   path.
4. Consider forward error correction and fragmentation (the `final` flag is
   reserved for this) once real channel measurements exist.
