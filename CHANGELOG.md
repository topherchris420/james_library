# Changelog

## [Unreleased] - 2026-03-29

### Fixed

- OTP codes are now single-use within their validity window (anti-replay protection)
- Brute-force rate limiting added to OTP validation (3 attempts before 5-minute lockout)
- Replay rejection no longer counts toward brute-force lockout, preventing DoS amplification

### Changed

- `cache_valid_secs` config field clarified as anti-replay window in source and docs
- `challenge_max_attempts` config field documented in English and Chinese config references
