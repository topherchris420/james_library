---
name: desktop-screenshot
description: >
  Capture desktop app screenshots and post them to GitHub PRs with immutable
  URLs. Requires a Playwright capture harness and a desktop frontend, neither of
  which ships with R.A.I.N.
version: 1
---

# Desktop Screenshot Skill

> **Ported from [block/buzz](https://github.com/block/buzz).** The workflow below
> is upstream's verbatim, and it targets buzz's monorepo layout.

## Prerequisites (NOT satisfied by this repository)

This skill is documented as-ported for reference. None of the infrastructure it
drives exists in R.A.I.N. today:

| Referenced by the skill | Status in R.A.I.N. |
| --- | --- |
| `just desktop-screenshot` recipe | absent — no such recipe in `Justfile` |
| `desktop/` Tauri + pnpm frontend | absent — `web/` is a Vite app with no capture harness |
| Playwright + mock bridge, mock channels | absent — no Playwright dependency |
| `scripts/post-screenshots.sh` | absent |
| `scripts/check-pr-image-urls.sh` | absent |
| `gh` CLI (required by the post script) | not installed |

Routing goes through `run_skill_tool("desktop-screenshot", [...])` in
`james_library/utilities/tools.py`, which resolves `$RAIN_SCREENSHOT_BIN`
(default `rain-desktop-screenshot`) and returns a structured error when it is
absent. Point that variable at a capture harness to make this skill live.

## CRITICAL: How to Host Screenshots for PRs

**NEVER use `buzz upload`, the relay media endpoint, or any third-party image
host (imgur, imgbb, etc.) for PR screenshots.** Relay media URLs fail through
GitHub's camo proxy (`Non-Image content-type returned`). External hosts are
unreliable and may expose content.

**ALWAYS use `scripts/post-screenshots.sh`** — it hosts PNGs on a per-developer
git branch with immutable commit-SHA URLs that render correctly on GitHub.
If you manually compose or edit PR markdown, run
`scripts/check-pr-image-urls.sh <markdown-file>` before posting. The checker
fails on Buzz/relay media URLs so broken images are caught locally.

This hosting rule applies to any PNG you want in a PR, including mobile
simulator screenshots captured outside the desktop Playwright helper.

## Step 1 — Capture Screenshots

`just desktop-screenshot` builds the frontend, starts a preview server, and
runs Playwright with the mock bridge (no relay needed).

```bash
just desktop-screenshot --name home
just desktop-screenshot --name channel --route /channels/general
just desktop-screenshot --name ctx-menu --right-click channel-random --clip 0,200,320,300
just desktop-screenshot --name sidebar --active-channel general --messages /tmp/msgs.json --clip 0,0,256,720
```

**Flags:** `--name` (filename, required), `--route` (client route), `--active-channel`
(channel to view), `--click`/`--right-click`/`--hover` (interact before capture),
`--clip` (crop as `x,y,w,h`), `--messages` (JSON file), `--wait` (ms, default 2000),
`--viewport` (WxH, default 1280x720), `--outdir` (default `test-results/screenshots`).

Output: PNG path on stdout.

### Injecting Messages

Write a JSON array to a temp file. `channelName` and `content` are required:

```json
[
  {"channelName": "random", "content": "Hey check this out", "kind": 40002},
  {"channelName": "random", "content": "Another message"}
]
```

Without `--active-channel`, the helper navigates to the message channel (for
showing content). With `--active-channel`, messages can target other channels
while the camera stays put (for unread indicators, badges).

### Available Mock Channels

`general`, `random`, `design`, `sales`, `engineering`, `agents`, `watercooler`,
`announcements`, `rain-operator`, `rain-maintainer`.

(Upstream's mock bridge names the two DM channels after personal names; they are
relabelled here to satisfy the privacy gate in CLAUDE.md 9.1. If you ever wire up
the real harness, check the fixture for its actual channel identifiers.)

`general` has pre-seeded messages (always shows `hasUnread`). Use `engineering`
for "no unread" visual states.

## Step 2 — Post to a PR

```bash
./scripts/post-screenshots.sh <PR-number> test-results/screenshots
./scripts/post-screenshots.sh <PR-number> test-results/screenshots body.md
```

The script pushes images to `agent-screenshots/<github-username>` and posts a
PR comment with `## Screenshots` and all images. Re-runs overwrite that PR's
images only.

### Body Templates

The optional third argument is a markdown file with `{{filename}}` placeholders
(without `.png`). Images not referenced by a placeholder are appended at the end.

```markdown
### Context menu
Right-click shows "Star channel".

{{01-ctx-menu}}

### Starred section
`engineering` appears under Starred.

{{02-starred}}
```

## Gotchas

1. **Stale server** — `reuseExistingServer: true` means a prior build serves old
   code. Kill port 4173 and rebuild (`cd desktop && pnpm run build`) after code changes.
2. **Clip for readability** — full 1280x720 screenshots are hard to read for sidebar
   features. Sidebar = 256px wide; context menus ~450px.
3. **`post-screenshots.sh` requires `gh` auth** — the script uses `gh api` and
   `gh pr comment`. Ensure `gh auth status` succeeds.
