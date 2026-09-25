# Changelog

## [Unreleased] - 2026-03-29

### Added

- Instant demo (`python rain_lab.py --mode demo`, or Enter in the wizard) is now an offline four-agent research meeting over the citation corpus instead of a canned script: each agent picks evidence through its own lens, every quote is a verbatim span re-verified with `citation_corpus.verify_quote`, and the transcript ends with a verdict, a next move, and a citation audit with a corpus fingerprint. Questions the library does not cover get an explicit "no evidence" meeting and suggested questions instead of unrelated quotes. Presets no longer change the demo's content; `--corpus` and `RAIN_CORPUS_DIR` now apply to the demo as well as chat

- `hmem` memory backend (alias `meterless`): local implementation of the Meterless H-MEM retrieval semantics over the sqlite store — 8-signal hybrid re-ranking with 0.35 score threshold, category→tier mapping, and an append-only trust ledger (`memory/hmem_trust_ledger.jsonl`) recording provenance and SHA-256 content digests for every mutation

### Fixed

- OTP codes are now single-use within their validity window (anti-replay protection)
- Brute-force rate limiting added to OTP validation (3 attempts before 5-minute lockout)
- Replay rejection no longer counts toward brute-force lockout, preventing DoS amplification

### Changed

- `cache_valid_secs` config field clarified as anti-replay window in source and docs
- `challenge_max_attempts` config field documented in English and Chinese config references
