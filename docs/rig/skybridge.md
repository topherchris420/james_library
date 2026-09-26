# Skybridge (Experimental)

> **Experimental extension, not part of the stable core.** Default builds are
> receive and software only: they render and decode baseband audio and can
> read a receive-only receiver command. They cannot key a transmitter. RF
> transmit exists only in binaries built with the off-by-default Cargo
> feature `rig-rf-transmit`, and even there every transmission needs a human
> operator's typed confirmation.

Skybridge is a low-bandwidth, plaintext frame transport for HF/radio use. It
is an independent design and is not wire-compatible with any existing
amateur-radio protocol.

## Layers

| Layer | Module | Status |
| --- | --- | --- |
| Frame codec | `src/rig/skybridge/frame.rs` | Implemented |
| Integrity | CRC-16/X.25 (`frame.rs`) | Implemented; detects corruption, **not** authentication |
| Forward error correction | `src/rig/skybridge/fec.rs` | Hamming(7,4), interleaved; on by default |
| Fragmentation | `src/rig/skybridge/fragment.rs` | Messages up to 1000 B over up to 5 frames |
| Modem / baseband | `src/rig/skybridge/modem.rs` | Software BFSK; finds every frame in a recording |
| Transport adapter | `SkybridgeTransport` (`skybridge/mod.rs`) | WAV/memory sinks; WAV, memory and receiver-command sources |
| Receiver input | `src/rig/skybridge/receiver.rs` | Receive-only external command (for example `rtl_fm`) |
| Receive pipeline | samples → demodulate (FEC) → frame + CRC → reassembly → restricted inbox | Implemented |
| RF transmit | `src/rig/skybridge/radio.rs` | Disabled by default; external-command backend in `rig-rf-transmit` builds |

## Frame format (version 1)

```text
offset  size  field
0       2     magic "SB"
2       1     version (1)
3       1     flags: bit 0 = final fragment, bit 1 = continuation;
              bits 2-7 reserved (must be 0)
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

## Fragmentation

Messages longer than 200 B (up to 1000 B) are split at UTF-8 character
boundaries into frames with consecutive sequence numbers. Every frame after
the first sets `continuation`, and only the last sets `final`, so a
single-frame message is `final` without `continuation`. Each fragment is valid
plaintext on its own.

Reassembly delivers a message only when all of these hold:

- the run starts with a non-continuation frame;
- every frame in the run comes from the same station with the next sequence
  number;
- the run ends in a `final` frame.

Gaps, station changes, orphaned continuations, runs without an end, and runs
over five frames or 1000 B are dropped and counted. A partial message is
never delivered.

## Modem and FEC

Continuous-phase binary FSK at 100 baud. Mark is 1700 Hz and space is 1500 Hz,
at an 8000 Hz sample rate, with Goertzel tone detection over one symbol.
Each frame on the line is a 32-bit `1010…` preamble, a 16-bit sync word, the
coded frame, and an 8-bit tail. The sync word selects the coding:

| Sync | Coding | Airtime (max frame, 219 B) |
| --- | --- | --- |
| `0xD22B` | Hamming(7,4), 8-codeword block interleaving (default) | about 31 s |
| `0x2DD4` | Plain bytes, MSB-first (`encode --no-fec`) | about 18 s |

Hamming(7,4) corrects one bit per codeword. Interleaving spreads each
8-codeword block so that a burst of up to 8 consecutive bit errors is fully
corrected. The CRC still decides whether a frame is accepted. The demodulator
accepts both codings, searches symbol-timing offsets, and returns every frame
in the recording once (the same frame seen at several offsets is
de-duplicated).

## CLI

```bash
rain rig radio status
rain rig radio encode --station N0CALL --text "measurement 12.5 Hz" --out frame.wav
rain rig radio encode --station N0CALL --text "…" --out frame.wav --no-fec
rain rig radio decode --input frame.wav          # or --json
rain rig radio listen --seconds 60               # receive-only command from [rig.radio] receive
rain rig radio transmit --frequency-hz 14100000 --power-w 10 --text "CQ de N0CALL"   # rig-rf-transmit builds only
```

`encode` builds an operator proposal and runs it through the action boundary
(size and plaintext validation). The disposition is recorded in
`<workspace>/rig/dispositions.jsonl` before a PCM16 mono WAV file is written.
It refuses to overwrite an existing file unless you pass `--force`. `decode`
and `listen` pass every complete message through the restricted inbox, so a
payload such as `!shell reboot` becomes an inert `Note`.

## Receiving from a radio or SDR

`[rig.radio] receive` is the argv of a command that writes raw PCM16
little-endian mono at 8000 Hz to stdout. It runs without a shell. For example:

```toml
[rig.radio]
receive = ["rtl_fm", "-f", "14.1M", "-M", "usb", "-s", "8000", "-"]
```

`listen` runs it for at most `--seconds` (1–300), stops it, and decodes what
it produced. A frame cut by the capture window, or one that fails the CRC, is
reported as "no further complete frame" rather than an error. Receiving never
transmits.

## RF transmit (`rig-rf-transmit` builds only)

Default builds reject every `RadioTransmit` proposal and use a backend that
refuses every call. In a build with `cargo build --features rig-rf-transmit`,
transmission additionally requires all of the following:

1. **Configuration.** Set `callsign`, `max_power_w` (1–1500) and
   `[rig.radio.transmit]`:

   ```toml
   [rig.radio]
   callsign = "N0CALL"
   max_power_w = 20

   [rig.radio.transmit]
   ptt_on  = ["rigctl", "-m", "2", "F", "{frequency_hz}", "T", "1"]
   play    = ["aplay", "-q", "{wav}"]
   ptt_off = ["rigctl", "-m", "2", "T", "0"]
   ```

   The commands are argv (no shell). They may use the placeholders `{wav}`,
   `{frequency_hz}` and `{power_w}`. `ptt_on` is optional for VOX setups;
   when it is set, `ptt_off` is required.
2. **An operator origin.** RF parameters come from a human at the CLI.
   Proposals from a model or from host code are rejected even with an
   approval.
3. **Deterministic checks.** The callsign must match the configured one. The
   frequency is the USB dial frequency, and its whole 3 kHz channel must fit
   inside the built-in band plan. Power must be 1..=`max_power_w`. The
   payload must be plaintext of at most 1000 B.
4. **Interactive confirmation.** The command shows callsign, frequency, band,
   power, frame count, airtime and backend. You must then type your callsign
   at a terminal. There is no flag to skip this, and piped stdin is refused.
5. **Backend guards.** The external-command backend caps airtime at 180 s and
   runs each command with a timeout. If keying fails it skips `play`. It
   always runs `ptt_off`.

Every step is recorded in the disposition log: rejected, awaiting
confirmation, and authorized.

Built-in band plan (USB dial plus 3 kHz must fit): 160 m 1.810–1.850,
80 m 3.500–3.800, 40 m 7.000–7.200, 30 m 10.100–10.150, 20 m 14.000–14.350,
17 m 18.068–18.168, 15 m 21.000–21.450, 12 m 24.890–24.990 and
10 m 28.000–29.700 MHz. These are the parts of each allocation common to ITU
Regions 1–3. The 60 m band is excluded. The plan is an outer bound, not a
grant: your licence class and national rules may be narrower.

## Regulatory notes

Amateur-radio rules generally require:

- a licensed operator;
- station identification;
- plaintext (unencrypted) content.

They also restrict which frequencies, emissions and power levels you may use.
Skybridge keeps payloads plaintext, puts the licensed callsign in every
transmitted frame's station field, and requires your typed confirmation for
each transmission. Staying within the rules is still your responsibility.
Nothing in R.A.I.N. authorizes anyone to transmit.
