# Changelog

## [Unreleased] - 2026-03-29

### Added

- `hmem` memory backend (alias `meterless`): local implementation of the Meterless H-MEM retrieval semantics over the sqlite store — 8-signal hybrid re-ranking with 0.35 score threshold, category→tier mapping, and an append-only trust ledger (`memory/hmem_trust_ledger.jsonl`) recording provenance and SHA-256 content digests for every mutation

### Fixed

- OTP codes are now single-use within their validity window (anti-replay protection)
- Brute-force rate limiting added to OTP validation (3 attempts before 5-minute lockout)
- Replay rejection no longer counts toward brute-force lockout, preventing DoS amplification

### Changed

- `cache_valid_secs` config field clarified as anti-replay window in source and docs
- `challenge_max_attempts` config field documented in English and Chinese config references
