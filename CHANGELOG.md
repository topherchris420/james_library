# Changelog

## [Unreleased] - 2026-03-29

### Added

- R.A.I.N. Rig (optional, opt-in): `rain rig status|doctor|models|capabilities|peers|setup|up|radio` turns the runtime into a self-contained local research node. Discovery probes only loopback/private-network endpoints and reuses the existing `llamacpp` (`llama.cpp`), `ollama` and `lmstudio` providers; `[rig]` adds built-in `local`/`node`/`field` profiles, a privacy-safe node identity, and `privacy = "local"`, which makes provider construction refuse hosted inference (including fallbacks and model routes) instead of falling back. Includes a strict action boundary with a disposition log, a restricted inbound message layer, discovery-only Reticulum/LXMF adapters, and the experimental software-only Skybridge modem (RF transmit disabled). Omitting `[rig]` keeps prior behavior; `python rain_lab.py` does not depend on it. See `docs/rig/`
- Godot client agent animation: avatars are now layered procedural pixel-art rigs with distinct characters (octopus James; Jasmine as a Black woman with deep brown skin, a natural afro, goggles and hoops; scarfed Luca; Elena as a woman with long hair, glasses and a skirt), breathing, blinks, gaze that follows the speaker, listener nods and reactions, tone-driven expressions (with text-based tone inference when the backend sends `neutral`), gestures, drop-in entrances, turn-taking hops with squash and stretch, and an end-of-conversation cheer. Mouths are lip-synced to the voice: metered from a dedicated `RainVoice` bus for TTS files, or from the syllable schedule of the new pulse-wave synthetic voice. Includes a headless smoke test (`godot_client/tests/animation_rig_test.gd`)
- Instant demo (`python rain_lab.py --mode demo`, or Enter in the wizard) is now an offline four-agent research meeting over the citation corpus instead of a canned script: each agent picks evidence through its own lens, every quote is a verbatim span re-verified with `citation_corpus.verify_quote`, and the transcript ends with a verdict, a next move, and a citation audit with a corpus fingerprint. Questions the library does not cover get an explicit "no evidence" meeting and suggested questions instead of unrelated quotes. Presets no longer change the demo's content; `--corpus` and `RAIN_CORPUS_DIR` now apply to the demo as well as chat

- `hmem` memory backend (alias `meterless`): local implementation of the Meterless H-MEM retrieval semantics over the sqlite store — 8-signal hybrid re-ranking with 0.35 score threshold, category→tier mapping, and an append-only trust ledger (`memory/hmem_trust_ledger.jsonl`) recording provenance and SHA-256 content digests for every mutation

### Fixed

- Godot client: TTS voice files (`audio.mode = file`) failed with a script error in Godot 4.2 (`AudioStreamWAV.load_wav_from_file` does not exist), so live lines never played and the speaker never stopped talking. WAV/MP3/OGG files are now decoded at runtime, and unreadable files fall back to the synthetic voice
- Godot client demo: each line was cut off after 0.4–1.0 s because the next event fired on its short `delay_s`; demo playback now waits for the line's `duration_ms`
- Godot client: theme `agents` colours were ignored by the avatars; they now apply and update live on theme change

- OTP codes are now single-use within their validity window (anti-replay protection)
- Brute-force rate limiting added to OTP validation (3 attempts before 5-minute lockout)
- Replay rejection no longer counts toward brute-force lockout, preventing DoS amplification

### Changed

- `cache_valid_secs` config field clarified as anti-replay window in source and docs
- `challenge_max_attempts` config field documented in English and Chinese config references
