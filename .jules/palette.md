## 2024-05-22 - [CLI Ghosting with Emoji]
**Learning:** Overwriting lines in CLI with `\r` can leave "ghost" characters if the new string is shorter than the old one, especially when emoji width varies (1 vs 2 chars).
**Action:** Always use `\033[K` (Clear Line) after `\r` when overwriting status messages to ensure a clean slate.
