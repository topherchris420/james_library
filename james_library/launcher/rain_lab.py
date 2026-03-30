"""Unified launcher for R.A.I.N. Lab meeting modes.

Recommended front door:
  Install with INSTALL_RAIN.cmd on Windows, or with the uv + bootstrap_local.py flow on macOS/Linux.
  After setup, this launcher is the daily product entrypoint.

Quick Start:
  python rain_lab.py           # Interactive wizard - asks what you want to do
  python rain_lab.py --mode chat --topic "your research topic"
  python rain_lab.py --mode validate  # Check if system is ready

Usage examples:
  python rain_lab.py           # Interactive wizard (recommended!)
  python rain_lab.py --mode first-run
  python rain_lab.py --mode chat --topic "Guarino paper"
  python rain_lab.py --mode chat --topic "Guarino paper" --temp 0.85 --max-tokens 320
  python rain_lab.py --mode rlm --topic "Guarino paper"
  python rain_lab.py --mode validate
  python rain_lab.py --mode models
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path

ANSI_RESET = "\033[0m"
ANSI_CYAN = "\033[96m"
ANSI_BLUE = "\033[94m"
ANSI_MAGENTA = "\033[95m"
ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_DIM = "\033[90m"

BANNER_LINES = [
    "==============================================================",
    "  R.A.I.N. LAB - Recursive Architecture of Intelligent Nexus  ",
    "==============================================================",
    "                 V E R S 3 D Y N A M I C S                   ",
]
ASCII_ART_LINES = [
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557\u2588\u2588\u2588\u2557   \u2588\u2588\u2557    \u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 ",  # noqa: E501
    "\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",  # noqa: E501
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2554\u2588\u2588\u2557 \u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",  # noqa: E501
    "\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551\u255a\u2588\u2588\u2557\u2588\u2588\u2551    \u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",  # noqa: E501
    "\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551\u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2551    \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",  # noqa: E501
    "\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d    \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u255d ",  # noqa: E501
    "\u2593" * 55,
    ("\u2592" * 18) + " V E R S 3 D Y N A M I C S " + ("\u2592" * 12),
]

VALID_UI_MODES = {"auto", "on", "off"}
BEGINNER_DEBATE_HINTS = (
    "debate",
    "argue",
    "compare",
    "comparison",
    "versus",
    " vs ",
    " pros and cons ",
    "which is better",
    "roundtable",
    "panel",
)


@dataclass(frozen=True)
class BeginnerPreset:
    slug: str
    title: str
    summary: str
    default_topic: str
    topic_template: str
    recommended_mode: str
    demo_hook: str


BEGINNER_PRESETS: dict[str, BeginnerPreset] = {
    "startup-debate": BeginnerPreset(
        slug="startup-debate",
        title="Startup Debate",
        summary="Turn one idea into a sharp founder-vs-investor showdown.",
        default_topic="an AI tutor for overwhelmed college students",
        topic_template=(
            "Run this like a punchy startup debate. Pressure-test the idea, call out weak spots,"
            " defend what is strong, and end with the single strongest version of it: {topic}"
        ),
        recommended_mode="rlm",
        demo_hook="A founder pitches. A skeptic attacks. The room still lands on a clearer version.",
    ),
    "idea-roast": BeginnerPreset(
        slug="idea-roast",
        title="Idea Roast",
        summary="Roast the concept hard, then rescue it with concrete fixes.",
        default_topic="a social app for roommates who never answer texts",
        topic_template=(
            "Roast this idea with wit, but stay useful. Point out what is weak, boring, risky,"
            " or confusing, then give three concrete ways to make it actually work: {topic}"
        ),
        recommended_mode="chat",
        demo_hook="The first draft gets roasted. The second draft suddenly sounds worth building.",
    ),
    "explain-like-im-12": BeginnerPreset(
        slug="explain-like-im-12",
        title="Explain Like I'm 12",
        summary="Use concrete analogies, short sentences, and zero jargon.",
        default_topic="resonance in simple everyday language",
        topic_template=(
            "Explain this like I am 12 years old. Use vivid analogies, short sentences, and plain"
            " language, but do not talk down to me: {topic}"
        ),
        recommended_mode="chat",
        demo_hook="A hard idea gets translated into something a curious kid could actually repeat.",
    ),
}
BEGINNER_PRESET_CHOICES = tuple(sorted(BEGINNER_PRESETS))
BEGINNER_PROMPT_SHORTCUTS = {
    "1": "startup-debate",
    "2": "idea-roast",
    "3": "explain-like-im-12",
}


@dataclass(frozen=True)
class FollowUpMove:
    label: str
    description: str
    command: str


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_banner() -> None:
    if (getattr(sys.stdout, "encoding", "") or "").lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    supports_overlay = bool(getattr(sys.stdout, "isatty", lambda: False)())

    art_colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_BLUE, ANSI_CYAN, ANSI_GREEN, ANSI_BLUE, ANSI_YELLOW]
    for line, color in zip(ASCII_ART_LINES, art_colors):
        safe_line = _console_safe(line)
        if supports_overlay:
            print(f"{ANSI_DIM} {safe_line}{ANSI_RESET}\r{color}{safe_line} {ANSI_RESET}", flush=True)
        else:
            print(f"{color}{safe_line}{ANSI_RESET}", flush=True)
    print("", flush=True)

    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_YELLOW]
    for line, color in zip(BANNER_LINES, colors):
        safe_line = _console_safe(line)
        if supports_overlay:
            print(f"{ANSI_DIM} {safe_line}{ANSI_RESET}\r{color}{safe_line} {ANSI_RESET}", flush=True)
        else:
            print(f"{color}{safe_line}{ANSI_RESET}", flush=True)


def _spinner(message: str, duration_s: float = 1.25) -> None:
    safe_message = _console_safe(message)
    if not sys.stdout.isatty():
        print(f"{ANSI_CYAN}{safe_message}...{ANSI_RESET}", flush=True)
        return

    frames = ["[   ]", "[=  ]", "[== ]", "[===]", "[ ==]", "[  =]"]
    colors = [ANSI_CYAN, ANSI_BLUE, ANSI_MAGENTA, ANSI_GREEN, ANSI_YELLOW]
    end_time = time.time() + max(0.2, duration_s)
    i = 0
    while time.time() < end_time:
        frame = frames[i % len(frames)]
        color = colors[i % len(colors)]
        pulse = "." * ((i % 3) + 1)
        print(f"\r{color}{frame} {safe_message} {pulse}{ANSI_RESET}   ", end="", flush=True)
        i += 1
        time.sleep(0.09)
    print(f"\r{ANSI_GREEN}OK {safe_message}{ANSI_RESET}   ")


def _split_passthrough_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        idx = argv.index("--")
        return argv[:idx], argv[idx + 1 :]
    return argv, []


def _resolve_beginner_preset(preset_name: str | None) -> BeginnerPreset | None:
    if not preset_name:
        return None
    return BEGINNER_PRESETS.get(preset_name)


def _beginner_topic_prompt() -> str:
    return (
        "Pick a quick starter: 1) Startup Debate  2) Roast My Idea  3) Explain Like I'm 12"
        "  4) Instant Demo\nOr type your own topic: "
    )


def _apply_beginner_shortcut(raw_input: str) -> tuple[str | None, str | None, bool]:
    trimmed = raw_input.strip()
    if trimmed == "4":
        return None, None, True
    if trimmed in BEGINNER_PROMPT_SHORTCUTS:
        return BEGINNER_PROMPT_SHORTCUTS[trimmed], None, False
    if trimmed:
        return None, trimmed, False
    return "explain-like-im-12", None, False


def _render_beginner_topic(topic: str | None, preset_name: str | None) -> tuple[str, str]:
    preset = _resolve_beginner_preset(preset_name)
    display_topic = (topic or (preset.default_topic if preset else "Help me explore a new idea")).strip()
    if preset is None:
        return display_topic, display_topic
    return display_topic, preset.topic_template.format(topic=display_topic)


def _topic_for_command(topic: str | None) -> str:
    cleaned = (topic or "").strip().replace('"', "'")
    if cleaned:
        return cleaned
    return "your idea"


def _command_for_mode(mode: str, *, topic: str | None = None, preset: str | None = None) -> str:
    command = f"python rain_lab.py --mode {mode}"
    if preset:
        command += f" --preset {preset}"
    if topic:
        command += f' --topic "{_topic_for_command(topic)}"'
    return command


def _wrap_display_lines(text: str, *, max_chars: int, max_lines: int) -> list[str]:
    words = " ".join((text or "").split()).split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break

    remaining_words = words[len(" ".join(lines + [current]).split()) :]
    if remaining_words:
        tail = " ".join([current, *remaining_words]).strip()
    else:
        tail = current

    if len(lines) < max_lines:
        lines.append(tail)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == max_lines and len(lines[-1]) > max_chars:
        clipped = lines[-1][: max_chars - 3].rsplit(" ", 1)[0].strip() or lines[-1][: max_chars - 3]
        lines[-1] = f"{clipped}..."

    return lines[:max_lines]


def _poster_path_for_share_card(share_html_path: Path) -> Path:
    if "BEGINNER_SHARE_" in share_html_path.name:
        poster_name = share_html_path.name.replace("BEGINNER_SHARE_", "BEGINNER_POSTER_").replace(".html", ".svg")
        return share_html_path.with_name(poster_name)
    return share_html_path.with_suffix(".svg")


def _build_beginner_poster_svg(
    *,
    topic: str,
    preset_title: str,
    session_label: str,
    caption: str,
    pull_quote: str,
    demo_mode: bool,
) -> str:
    accent = "#f97316" if demo_mode else "#14b8a6"
    accent_deep = "#9a3412" if demo_mode else "#115e59"
    accent_soft = "#ffedd5" if demo_mode else "#ccfbf1"
    topic_lines = _wrap_display_lines(topic, max_chars=18, max_lines=3)
    quote_lines = _wrap_display_lines(pull_quote, max_chars=20, max_lines=5)
    caption_lines = _wrap_display_lines(caption, max_chars=44, max_lines=3)
    session_text = "INSTANT DEMO" if demo_mode else "BEGINNER SESSION"

    topic_svg = "".join(
        f'<tspan x="640" y="{178 + (idx * 78)}">{html_escape(line)}</tspan>'
        for idx, line in enumerate(topic_lines or ["R.A.I.N. Lab"])
    )
    quote_svg = "".join(
        f'<tspan x="86" y="{218 + (idx * 52)}">{html_escape(line)}</tspan>'
        for idx, line in enumerate(quote_lines or ["A shareable", "result page."])
    )
    caption_svg = "".join(
        f'<tspan x="640" y="{470 + (idx * 30)}">{html_escape(line)}</tspan>'
        for idx, line in enumerate(caption_lines or ["Local-first AI research sessions."])
    )
    safe_topic = html_escape(topic)
    safe_preset_title = html_escape(preset_title)
    safe_session_label = html_escape(session_label)
    session_banner = f"R.A.I.N. LAB / {session_text}"

    return f"""<svg
  xmlns="http://www.w3.org/2000/svg"
  width="1200"
  height="630"
  viewBox="0 0 1200 630"
  role="img"
  aria-label="{safe_topic} poster"
>
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{accent}"/>
      <stop offset="100%" stop-color="{accent_deep}"/>
    </linearGradient>
    <radialGradient id="glow" cx="25%" cy="22%" r="75%">
      <stop offset="0%" stop-color="rgba(255,255,255,0.34)"/>
      <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
    </radialGradient>
  </defs>
  <rect width="1200" height="630" rx="34" fill="#f8f2e9"/>
  <rect x="22" y="22" width="1156" height="586" rx="28" fill="url(#bg)"/>
  <rect x="44" y="44" width="1112" height="542" rx="24" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.18)"/>
  <circle cx="188" cy="114" r="148" fill="url(#glow)"/>
  <circle cx="1064" cy="542" r="186" fill="rgba(255,255,255,0.08)"/>
  <rect x="62" y="62" width="500" height="506" rx="26" fill="rgba(10,20,18,0.22)" stroke="rgba(255,255,255,0.14)"/>
  <text
    x="86"
    y="112"
    fill="{accent_soft}"
    font-family="Avenir Next, Trebuchet MS, sans-serif"
    font-size="22"
    font-weight="700"
    letter-spacing="4"
  >{session_banner}</text>
  <text fill="white" font-family="Georgia, Times New Roman, serif" font-size="42" font-weight="700">{quote_svg}</text>
  <text
    x="86"
    y="512"
    fill="rgba(255,255,255,0.82)"
    font-family="Avenir Next, Trebuchet MS, sans-serif"
    font-size="18"
    letter-spacing="2"
  >{safe_preset_title}</text>
  <text
    x="86"
    y="542"
    fill="rgba(255,255,255,0.92)"
    font-family="Avenir Next, Trebuchet MS, sans-serif"
    font-size="24"
    font-weight="700"
  >{safe_session_label}</text>
  <text fill="white" font-family="Georgia, Times New Roman, serif" font-size="68" font-weight="700">{topic_svg}</text>
  <text
    fill="rgba(255,255,255,0.92)"
    font-family="Avenir Next, Trebuchet MS, sans-serif"
    font-size="24"
  >{caption_svg}</text>
  <text
    x="640"
    y="558"
    fill="rgba(255,255,255,0.7)"
    font-family="Avenir Next, Trebuchet MS, sans-serif"
    font-size="18"
    letter-spacing="2"
  >Generated locally for quick sharing and remixing</text>
</svg>
"""




def _build_follow_up_moves(topic: str | None, current_preset: str | None) -> list[FollowUpMove]:
    subject = topic or "your idea"
    moves: list[FollowUpMove] = []
    preset_order = (
        (
            "startup-debate",
            "Run the debate",
            "Pressure-test the same topic with a sharper founder-vs-skeptic angle.",
        ),
        (
            "idea-roast",
            "Roast the idea",
            "Push the weak spots hard, then rescue the concept with concrete fixes.",
        ),
        (
            "explain-like-im-12",
            "Explain it simply",
            "Turn the topic into something easy to repeat to someone else.",
        ),
    )
    for slug, label, description in preset_order:
        if slug == current_preset:
            continue
        moves.append(
            FollowUpMove(
                label=label,
                description=description,
                command=_command_for_mode("beginner", topic=subject, preset=slug),
            )
        )

    moves.append(
        FollowUpMove(
            label="Instant wow demo",
            description="Run the zero-setup preview again if you want a fast shareable result.",
            command=_command_for_mode("demo", preset="startup-debate"),
        )
    )
    return moves[:3]


def _read_share_card_metadata(share_html_path: Path) -> tuple[str, str, str]:
    topic = "Fresh R.A.I.N. Lab session"
    preset = "Custom Prompt"
    session_style = "Beginner Session"
    markdown_path = share_html_path.with_suffix(".md")
    try:
        lines = markdown_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return topic, preset, session_style

    for line in lines:
        if line.startswith("Topic: "):
            topic = line.removeprefix("Topic: ").strip() or topic
        elif line.startswith("Preset: "):
            preset = line.removeprefix("Preset: ").strip() or preset
        elif line.startswith("Session style: "):
            session_style = line.removeprefix("Session style: ").strip() or session_style
    return topic, preset, session_style


def _poster_uri_for_share_card(share_html_path: Path) -> str | None:
    poster_path = _poster_path_for_share_card(share_html_path)
    if poster_path.exists():
        return poster_path.resolve().as_uri()
    return None


def _collect_recent_share_cards(share_dir: Path, limit: int = 6) -> list[Path]:
    return sorted(share_dir.glob("BEGINNER_SHARE_*.html"), reverse=True)[:limit]


def _build_showcase_html(
    *,
    title: str,
    hero_topic: str,
    latest_share_card: Path | None,
    follow_up_moves: list[FollowUpMove],
    recent_share_cards: list[Path],
) -> str:
    safe_title = html_escape(title)
    safe_hero_topic = html_escape(hero_topic)
    latest_href = latest_share_card.resolve().as_uri() if latest_share_card is not None else ""
    latest_poster_uri = _poster_uri_for_share_card(latest_share_card) if latest_share_card is not None else None
    latest_label = "Open latest share card" if latest_share_card is not None else "Run your first instant demo"
    latest_copy = (
        "The newest session is ready to revisit, screenshot, or send."
        if latest_share_card is not None
        else "No session yet. Run the instant demo and this page will turn into your local gallery."
    )
    hero_preview_markup = ""
    hero_poster_link_markup = ""
    if latest_poster_uri:
        hero_preview_markup = (
            f'<img class="hero-preview" src="{latest_poster_uri}" alt="Latest poster preview">'
        )
        hero_poster_link_markup = f'<a href="{latest_poster_uri}">Open poster</a>'
    move_cards = []
    for idx, move in enumerate(follow_up_moves, start=1):
        move_cards.append(
            f"""
        <article class="action-card">
          <div class="card-label">{html_escape(move.label)}</div>
          <p>{html_escape(move.description)}</p>
          <code id="move-{idx}">{html_escape(move.command)}</code>
          <button type="button" data-copy-target="move-{idx}">Copy Command</button>
        </article>
"""
        )
    move_cards_html = "".join(move_cards)

    preset_cards = []
    for preset in BEGINNER_PRESETS.values():
        preset_slug = html_escape(preset.slug)
        preset_command = html_escape(
            _command_for_mode("beginner", topic=preset.default_topic, preset=preset.slug)
        )
        preset_cards.append(
            f"""
        <article class="preset-card">
          <div class="card-label">{html_escape(preset.title)}</div>
          <p>{html_escape(preset.summary)}</p>
          <code id="preset-{preset_slug}">{preset_command}</code>
          <button type="button" data-copy-target="preset-{preset_slug}">Copy Command</button>
        </article>
"""
        )
    preset_cards_html = "".join(preset_cards)

    recent_items = []
    for share_path in recent_share_cards:
        topic, preset_title, session_style = _read_share_card_metadata(share_path)
        poster_uri = _poster_uri_for_share_card(share_path)
        poster_markup = ""
        if poster_uri is not None:
            poster_markup = (
                f'<img class="poster-thumb" src="{poster_uri}" '
                f'alt="{html_escape(topic)} poster preview">'
            )
        recent_items.append(
            f"""
        <a class="recent-card" href="{share_path.resolve().as_uri()}">
          {poster_markup}
          <div class="card-label">{html_escape(preset_title)}</div>
          <strong>{html_escape(topic)}</strong>
          <span>{html_escape(session_style)}</span>
        </a>
"""
        )
    if recent_items:
        recent_cards_html = "".join(recent_items)
    else:
        recent_cards_html = """
        <div class="empty-state">
          Run `python rain_lab.py` and press Enter for the instant demo. Your first shareable session will appear here.
        </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f7f1e6;
      --panel: rgba(255, 252, 247, 0.94);
      --panel-strong: rgba(255, 255, 255, 0.97);
      --ink: #1f2937;
      --muted: #5c6675;
      --line: rgba(31, 41, 55, 0.08);
      --accent: #0f766e;
      --accent-deep: #134e4a;
      --accent-warm: #ea580c;
      --shadow: rgba(15, 23, 42, 0.14);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif;
      background:
        radial-gradient(circle at 8% 10%, rgba(20,184,166,0.16), transparent 24%),
        radial-gradient(circle at 90% 14%, rgba(234,88,12,0.16), transparent 22%),
        linear-gradient(160deg, #fff8ef 0%, var(--bg) 56%, #e8ddcc 100%);
      min-height: 100vh;
      padding: 28px 20px 40px;
    }}
    .shell {{
      max-width: 1120px;
      margin: 0 auto;
      display: grid;
      gap: 22px;
    }}
    .hero, .panel {{
      background: linear-gradient(180deg, var(--panel-strong), var(--panel));
      border: 1px solid var(--line);
      border-radius: 30px;
      box-shadow: 0 28px 80px -44px var(--shadow);
      overflow: hidden;
    }}
    .hero {{
      padding: 32px;
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.85fr);
      gap: 20px;
      position: relative;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.48), transparent 36%),
        linear-gradient(135deg, rgba(255,255,255,0), rgba(255,255,255,0.38));
      pointer-events: none;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 8px 14px;
      background: rgba(15,118,110,0.14);
      color: var(--accent-deep);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 18px 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(40px, 7vw, 78px);
      line-height: 0.92;
      letter-spacing: -0.04em;
      max-width: 10ch;
    }}
    .lede {{
      margin: 0;
      max-width: 56ch;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.58;
    }}
    .hero-card {{
      border-radius: 28px;
      padding: 24px;
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.24), transparent 30%),
        linear-gradient(145deg, var(--accent), var(--accent-deep));
      color: white;
      display: grid;
      align-content: end;
      min-height: 300px;
      position: relative;
      gap: 14px;
    }}
    .hero-card::before {{
      content: "";
      position: absolute;
      inset: 14px;
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.24);
      pointer-events: none;
    }}
    .hero-card strong {{
      font-size: 28px;
      line-height: 1.12;
      max-width: 13ch;
    }}
    .hero-card p {{
      margin: 14px 0 18px;
      line-height: 1.55;
      max-width: 28ch;
    }}
    .hero-card a {{
      color: white;
      text-decoration: none;
      font-weight: 700;
    }}
    .hero-preview {{
      width: 100%;
      border-radius: 20px;
      border: 1px solid rgba(255,255,255,0.2);
      background: rgba(255,255,255,0.12);
      min-height: 188px;
      object-fit: cover;
    }}
    .hero-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .panel {{
      padding: 24px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 18px;
      margin-bottom: 16px;
    }}
    .section-head h2 {{
      margin: 0;
      font-size: 28px;
      font-family: Georgia, "Times New Roman", serif;
    }}
    .section-head p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      max-width: 56ch;
    }}
    .action-grid, .preset-grid, .recent-grid {{
      display: grid;
      gap: 16px;
    }}
    .action-grid {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .preset-grid {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .recent-grid {{
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .action-card, .preset-card, .recent-card, .empty-state {{
      border-radius: 24px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      padding: 20px;
    }}
    .recent-card {{
      text-decoration: none;
      color: inherit;
      display: grid;
      gap: 8px;
    }}
    .poster-thumb {{
      width: 100%;
      aspect-ratio: 1.78 / 1;
      object-fit: cover;
      border-radius: 18px;
      border: 1px solid rgba(31,41,55,0.08);
      background: linear-gradient(145deg, rgba(20,184,166,0.12), rgba(249,115,22,0.1));
    }}
    .recent-card strong {{
      font-size: 21px;
      line-height: 1.2;
    }}
    .recent-card span {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .card-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    .action-card p, .preset-card p {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.55;
    }}
    code {{
      display: block;
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(31,41,55,0.06);
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 14px;
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-size: 14px;
    }}
    button {{
      appearance: none;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), var(--accent-deep));
      color: white;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .empty-state {{
      color: var(--muted);
      line-height: 1.65;
    }}
    @media (max-width: 920px) {{
      .hero {{
        grid-template-columns: 1fr;
      }}
      .action-grid,
      .preset-grid,
      .recent-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div>
        <div class="eyebrow">R.A.I.N. Lab / Start Here</div>
        <h1>{safe_hero_topic}</h1>
        <p class="lede">
          This is the local-first front door for R.A.I.N. Lab. Start with the instant demo if you
          want a fast wow moment, then use the follow-up commands below to turn that spark into
          something you can keep, compare, or share.
        </p>
      </div>
      <aside class="hero-card">
        <div class="card-label">Latest surface</div>
        {hero_preview_markup}
        <strong>{html_escape(latest_label)}</strong>
        <p>{html_escape(latest_copy)}</p>
        <div class="hero-links">
          <a href="{latest_href or '#'}">{html_escape(latest_label)}</a>
          {hero_poster_link_markup}
        </div>
      </aside>
    </section>
    <section class="panel">
      <div class="section-head">
        <div>
          <h2>Try Next</h2>
          <p>Three fast paths to keep momentum without digging through docs or flags.</p>
        </div>
      </div>
      <div class="action-grid">{move_cards_html}</div>
    </section>
    <section class="panel">
      <div class="section-head">
        <div>
          <h2>Pick A Vibe</h2>
          <p>
            Each preset bends the same topic into a different experience, so it feels closer to a
            toy box than a terminal menu.
          </p>
        </div>
      </div>
      <div class="preset-grid">{preset_cards_html}</div>
    </section>
    <section class="panel">
      <div class="section-head">
        <div>
          <h2>Poster Wall</h2>
          <p>Your latest beginner and demo sessions stay here as a local poster wall.</p>
        </div>
      </div>
      <div class="recent-grid">{recent_cards_html}</div>
    </section>
  </main>
  <script>
    document.querySelectorAll("[data-copy-target]").forEach((button) => {{
      const targetId = button.getAttribute("data-copy-target");
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target || !navigator.clipboard) return;
      button.addEventListener("click", async () => {{
        const original = button.textContent;
        try {{
          await navigator.clipboard.writeText(target.innerText);
          button.textContent = "Command copied";
        }} catch (_error) {{
          button.textContent = "Copy failed";
        }}
        window.setTimeout(() => {{
          button.textContent = original;
        }}, 1400);
      }});
    }});
  </script>
</body>
</html>
"""


def _write_beginner_showcase_page(
    args: argparse.Namespace,
    repo_root: Path,
    *,
    latest_share_card: Path | None = None,
) -> Path:
    library_root = _resolve_library_root(args, repo_root)
    share_dir = library_root / "meeting_archives"
    share_dir.mkdir(parents=True, exist_ok=True)
    topic = getattr(args, "display_topic", args.topic or "Start with the instant demo")
    current_preset = getattr(args, "preset", None)
    follow_up_moves = _build_follow_up_moves(topic, current_preset)
    recent_share_cards = _collect_recent_share_cards(share_dir)
    showcase_path = share_dir / "RAIN_LAB_SHOWCASE.html"
    showcase_path.write_text(
        _build_showcase_html(
            title="R.A.I.N. Lab Showcase",
            hero_topic=topic,
            latest_share_card=latest_share_card,
            follow_up_moves=follow_up_moves,
            recent_share_cards=recent_share_cards,
        ),
        encoding="utf-8",
    )
    return showcase_path


def _print_follow_up_moves(topic: str | None, preset_name: str | None) -> None:
    moves = _build_follow_up_moves(topic, preset_name)[:2]
    if not moves:
        return
    print(f"{ANSI_CYAN}Try next:{ANSI_RESET}")
    for move in moves:
        print(f"{ANSI_DIM}- {move.label}: {move.command}{ANSI_RESET}")


def _choose_beginner_mode(topic: str | None) -> str:
    if not topic:
        return "chat"

    normalized = f" {' '.join(topic.strip().lower().split())} "
    for hint in BEGINNER_DEBATE_HINTS:
        if hint in normalized:
            return "rlm"
    return "chat"


def _prepare_beginner_args(
    args: argparse.Namespace,
    *,
    ui_was_explicit: bool = False,
) -> argparse.Namespace:
    preset = _resolve_beginner_preset(getattr(args, "preset", None))
    beginner_mode = preset.recommended_mode if preset else _choose_beginner_mode(args.topic)
    prepared = _copy_args_with_mode(args, beginner_mode)
    display_topic, effective_topic = _render_beginner_topic(args.topic, getattr(args, "preset", None))
    prepared.display_topic = display_topic
    prepared.topic = effective_topic

    if not ui_was_explicit and prepared.ui == "off":
        prepared.ui = "auto"

    if prepared.mode == "rlm" and prepared.turns is None:
        prepared.turns = 4

    return prepared


def _prepare_demo_args(args: argparse.Namespace) -> argparse.Namespace:
    prepared = _copy_args_with_mode(args, "demo")
    if not getattr(prepared, "preset", None):
        prepared.preset = "startup-debate"
    display_topic, effective_topic = _render_beginner_topic(prepared.topic, prepared.preset)
    prepared.display_topic = display_topic
    prepared.topic = effective_topic
    return prepared


def _resolve_library_root(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.library:
        candidate = Path(args.library).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate
    return repo_root


def _read_share_excerpt(path: Path, max_chars: int = 700) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""

    if not text:
        return ""

    excerpt = text[-max_chars:].strip()
    if len(text) > max_chars:
        excerpt = "..." + excerpt
    return excerpt


def _build_beginner_share_html(
    *,
    title: str,
    topic: str,
    session_label: str,
    caption: str,
    preset_title: str,
    demo_mode: bool,
    excerpt: str,
    session_log: Path,
    launcher_log: Path | str,
    rerun_command: str,
) -> str:
    accent = "#f97316" if demo_mode else "#14b8a6"
    accent_soft = "#fed7aa" if demo_mode else "#99f6e4"
    label = "Instant Demo" if demo_mode else "Beginner Session"
    hook = "No model setup required." if demo_mode else "Saved as a shareable local artifact."
    safe_excerpt = html_escape(excerpt).replace("\n", "<br>")
    safe_caption = html_escape(caption)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      --bg: #f5efe4;
      --panel: #fffaf2;
      --ink: #1f2937;
      --muted: #5b6472;
      --accent: {accent};
      --accent-soft: {accent_soft};
      --shadow: rgba(31, 41, 55, 0.16);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(20,184,166,0.18), transparent 34%),
        radial-gradient(circle at top right, rgba(249,115,22,0.18), transparent 28%),
        linear-gradient(160deg, #fff8ef 0%, var(--bg) 55%, #efe6d8 100%);
      min-height: 100vh;
      padding: 24px;
    }}
    .shell {{
      max-width: 980px;
      margin: 0 auto;
      display: grid;
      gap: 20px;
    }}
    .hero, .card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(255,250,242,0.94));
      border: 1px solid rgba(31,41,55,0.08);
      border-radius: 28px;
      box-shadow: 0 24px 48px -28px var(--shadow);
      overflow: hidden;
    }}
    .hero {{
      padding: 30px;
      position: relative;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.45) 100%);
      pointer-events: none;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 8px 14px;
      background: var(--accent-soft);
      color: var(--ink);
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    h1 {{
      margin: 18px 0 12px;
      font-size: clamp(34px, 7vw, 60px);
      line-height: 0.95;
      max-width: 12ch;
    }}
    .lede {{
      font-size: 18px;
      line-height: 1.5;
      max-width: 60ch;
      color: var(--muted);
      margin: 0;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      padding: 0 30px 30px;
    }}
    .card {{
      padding: 22px;
    }}
    .label {{
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .value {{
      font-size: 18px;
      line-height: 1.45;
    }}
    .caption {{
      font-size: 22px;
      line-height: 1.45;
      margin: 0 0 16px;
    }}
    .controls {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    button, .link {{
      appearance: none;
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .link.secondary {{
      background: transparent;
      color: var(--ink);
      border: 1px solid rgba(31,41,55,0.14);
    }}
    .excerpt {{
      background: rgba(255,255,255,0.7);
      border-radius: 20px;
      padding: 18px;
      border: 1px dashed rgba(31,41,55,0.14);
      line-height: 1.65;
      color: var(--ink);
    }}
    code {{
      display: block;
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(31,41,55,0.06);
      border-radius: 16px;
      padding: 14px;
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="eyebrow">{label} · {html_escape(preset_title)}</div>
      <h1>{html_escape(topic)}</h1>
      <p class="lede">{html_escape(session_label)}. {html_escape(hook)}</p>
    </section>
    <section class="grid">
      <article class="card">
        <div class="label">Caption</div>
        <p class="caption" id="caption">{safe_caption}</p>
        <div class="controls">
          <button
            type="button"
            onclick="navigator.clipboard.writeText(document.getElementById('caption').innerText)"
          >
            Copy Caption
          </button>
          <a class="link secondary" href="{session_log.as_uri()}">Open Session Log</a>
        </div>
      </article>
      <article class="card">
        <div class="label">Session Flavor</div>
        <div class="value">{html_escape(session_label)}</div>
        <div class="label" style="margin-top:18px;">Launcher Log</div>
        <div class="value">{html_escape(str(launcher_log))}</div>
      </article>
      <article class="card">
        <div class="label">Quick Re-run</div>
        <code>{html_escape(rerun_command)}</code>
      </article>
      <article class="card">
        <div class="label">Highlight</div>
        <div class="excerpt">{safe_excerpt or 'Run the session again to capture a fresh highlight.'}</div>
      </article>
    </section>
  </main>
</body>
</html>
"""


def _share_pull_quote(excerpt: str, max_chars: int = 220) -> str:
    if not excerpt:
        return ""

    compact = " ".join(excerpt.split())
    if len(compact) <= max_chars:
        return compact

    clipped = compact[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def _build_beginner_share_html_v2(
    *,
    title: str,
    topic: str,
    session_label: str,
    caption: str,
    preset_title: str,
    demo_mode: bool,
    excerpt: str,
    session_log: Path,
    launcher_log: Path | str,
    rerun_command: str,
    follow_up_moves: list[FollowUpMove],
    showcase_path: Path | None,
    poster_path: Path | None,
) -> str:
    accent = "#f97316" if demo_mode else "#14b8a6"
    accent_soft = "#fed7aa" if demo_mode else "#99f6e4"
    accent_deep = "#9a3412" if demo_mode else "#115e59"
    label = "Instant Demo" if demo_mode else "Beginner Session"
    hook = "No model setup required." if demo_mode else "Saved as a shareable local artifact."
    safe_excerpt = html_escape(excerpt).replace("\n", "<br>")
    safe_caption = html_escape(caption)
    pull_quote = html_escape(_share_pull_quote(excerpt) or hook)
    session_log_uri = session_log.as_uri()
    launcher_log_value = html_escape(str(launcher_log))
    safe_topic = html_escape(topic)
    safe_title = html_escape(title)
    safe_session_label = html_escape(session_label)
    safe_preset_title = html_escape(preset_title)
    safe_rerun_command = html_escape(rerun_command)
    showcase_uri = showcase_path.resolve().as_uri() if showcase_path is not None else ""
    poster_uri = poster_path.resolve().as_uri() if poster_path is not None else ""
    follow_up_cards: list[str] = []
    for idx, move in enumerate(follow_up_moves, start=1):
        follow_up_cards.append(
            f"""
          <article class="next-card">
            <strong>{html_escape(move.label)}</strong>
            <p>{html_escape(move.description)}</p>
            <code id="follow-up-{idx}">{html_escape(move.command)}</code>
            <button type="button" data-copy-target="follow-up-{idx}">Copy Command</button>
          </article>
"""
        )
    follow_up_cards_html = "".join(follow_up_cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f6efe6;
      --paper: rgba(255, 250, 243, 0.92);
      --paper-strong: rgba(255, 255, 255, 0.97);
      --ink: #1f2937;
      --muted: #586271;
      --accent: {accent};
      --accent-soft: {accent_soft};
      --accent-deep: {accent_deep};
      --shadow: rgba(31, 41, 55, 0.14);
      --line: rgba(31, 41, 55, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Trebuchet MS", "Gill Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 10%, rgba(20,184,166,0.22), transparent 28%),
        radial-gradient(circle at 92% 12%, rgba(249,115,22,0.24), transparent 26%),
        radial-gradient(circle at 50% 100%, rgba(15,23,42,0.08), transparent 38%),
        linear-gradient(160deg, #fff8ef 0%, var(--bg) 54%, #eadfce 100%);
      min-height: 100vh;
      padding: 28px 20px 36px;
      position: relative;
      overflow-x: hidden;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background:
        linear-gradient(transparent 0%, rgba(255,255,255,0.28) 100%),
        repeating-linear-gradient(
          115deg,
          rgba(255,255,255,0.12) 0,
          rgba(255,255,255,0.12) 1px,
          transparent 1px,
          transparent 16px
        );
      pointer-events: none;
      opacity: 0.45;
    }}
    .shell {{
      max-width: 1080px;
      margin: 0 auto;
      display: grid;
      gap: 22px;
      position: relative;
      z-index: 1;
    }}
    .hero, .card {{
      background: linear-gradient(180deg, var(--paper-strong), var(--paper));
      border: 1px solid var(--line);
      border-radius: 30px;
      box-shadow: 0 28px 80px -42px var(--shadow);
      overflow: hidden;
    }}
    .hero {{
      padding: 30px;
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.85fr);
      gap: 20px;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at top right, rgba(255,255,255,0.5), transparent 38%),
        linear-gradient(135deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.42) 100%);
      pointer-events: none;
    }}
    .hero-copy {{
      position: relative;
      z-index: 1;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 8px 14px;
      background: linear-gradient(135deg, var(--accent-soft), rgba(255,255,255,0.88));
      color: var(--ink);
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
    }}
    h1 {{
      margin: 18px 0 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(40px, 7.6vw, 78px);
      line-height: 0.92;
      letter-spacing: -0.04em;
      max-width: 10ch;
    }}
    .lede {{
      font-size: 18px;
      line-height: 1.55;
      max-width: 54ch;
      color: var(--muted);
      margin: 0;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }}
    .chip {{
      border-radius: 999px;
      border: 1px solid rgba(31,41,55,0.1);
      padding: 10px 14px;
      background: rgba(255,255,255,0.64);
      font-size: 13px;
      font-weight: 700;
      color: var(--accent-deep);
      backdrop-filter: blur(8px);
    }}
    .poster {{
      position: relative;
      z-index: 1;
      display: grid;
      align-content: end;
      min-height: 320px;
      padding: 24px;
      border-radius: 26px;
      color: white;
      background:
        linear-gradient(155deg, rgba(255,255,255,0.14), transparent 28%),
        radial-gradient(circle at top left, rgba(255,255,255,0.18), transparent 30%),
        linear-gradient(145deg, var(--accent) 0%, var(--accent-deep) 100%);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.24);
      transform: rotate(-1.2deg);
    }}
    .poster::before {{
      content: "";
      position: absolute;
      inset: 14px;
      border: 1px solid rgba(255,255,255,0.26);
      border-radius: 22px;
      pointer-events: none;
    }}
    .poster-kicker {{
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 700;
      opacity: 0.9;
    }}
    .poster-quote {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(24px, 3vw, 36px);
      line-height: 1.08;
      margin: 14px 0 16px;
      max-width: 15ch;
    }}
    .poster-foot {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: end;
      font-size: 13px;
      opacity: 0.9;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 18px;
    }}
    .card {{
      padding: 22px;
      position: relative;
    }}
    .card-primary {{
      grid-column: span 7;
    }}
    .card-side {{
      grid-column: span 5;
    }}
    .card-wide {{
      grid-column: span 12;
    }}
    .label {{
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .caption {{
      font-size: clamp(24px, 2.3vw, 32px);
      line-height: 1.25;
      margin: 0 0 18px;
      font-weight: 700;
      max-width: 20ch;
    }}
    .controls {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    button, .link {{
      appearance: none;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), var(--accent-deep));
      color: white;
      padding: 12px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .link.secondary {{
      background: transparent;
      color: var(--ink);
      border: 1px solid rgba(31,41,55,0.14);
    }}
    .microcopy {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0 0 18px;
      max-width: 56ch;
    }}
    .quote-block {{
      position: relative;
      padding: 24px 24px 22px 28px;
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(255,255,255,0.66));
      border: 1px solid rgba(31,41,55,0.08);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.65);
    }}
    .quote-block::before {{
      content: '"';
      position: absolute;
      left: 18px;
      top: 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 68px;
      line-height: 1;
      color: rgba(31,41,55,0.14);
    }}
    .quote-text {{
      position: relative;
      z-index: 1;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(22px, 2.3vw, 30px);
      line-height: 1.22;
      max-width: 24ch;
      margin: 0 0 10px;
    }}
    .quote-meta {{
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .stat {{
      padding: 16px;
      border-radius: 20px;
      background: rgba(255,255,255,0.62);
      border: 1px solid rgba(31,41,55,0.08);
    }}
    .stat strong {{
      display: block;
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 10px;
    }}
    .stat span {{
      display: block;
      font-size: 18px;
      line-height: 1.4;
      font-weight: 700;
    }}
    .excerpt {{
      background: rgba(255,255,255,0.78);
      border-radius: 24px;
      padding: 22px;
      border: 1px dashed rgba(31,41,55,0.16);
      line-height: 1.72;
      color: var(--ink);
      font-size: 16px;
    }}
    code {{
      display: block;
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(31,41,55,0.06);
      border-radius: 16px;
      padding: 14px;
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-size: 14px;
    }}
    .footer-note {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .poster-preview {{
      width: 100%;
      border-radius: 22px;
      border: 1px solid rgba(31,41,55,0.08);
      background: linear-gradient(145deg, rgba(20,184,166,0.12), rgba(249,115,22,0.1));
      aspect-ratio: 1.78 / 1;
      object-fit: cover;
      margin-top: 14px;
    }}
    .next-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .next-card {{
      border-radius: 22px;
      border: 1px solid rgba(31,41,55,0.08);
      background: rgba(255,255,255,0.72);
      padding: 18px;
    }}
    .next-card strong {{
      display: block;
      font-size: 18px;
      margin-bottom: 8px;
    }}
    .next-card p {{
      color: var(--muted);
      line-height: 1.55;
      margin: 0 0 14px;
    }}
    .next-card code {{
      margin-bottom: 14px;
    }}
    .fade-up {{
      opacity: 0;
      transform: translateY(18px);
      animation: fadeUp 560ms ease forwards;
    }}
    .fade-up.delay-1 {{ animation-delay: 70ms; }}
    .fade-up.delay-2 {{ animation-delay: 140ms; }}
    .fade-up.delay-3 {{ animation-delay: 210ms; }}
    @keyframes fadeUp {{
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    @media (max-width: 860px) {{
      .hero {{
        grid-template-columns: 1fr;
      }}
      .poster {{
        min-height: 220px;
        transform: none;
      }}
      .card-primary,
      .card-side,
      .card-wide {{
        grid-column: span 12;
      }}
      .next-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero fade-up">
      <div class="hero-copy">
        <div class="eyebrow">{label} / {safe_preset_title}</div>
        <h1>{safe_topic}</h1>
        <p class="lede">{safe_session_label}. {html_escape(hook)}</p>
        <div class="chips">
          <span class="chip">Shareable artifact</span>
          <span class="chip">Local-first flow</span>
          <span class="chip">{safe_preset_title}</span>
        </div>
      </div>
      <aside class="poster">
        <div class="poster-kicker">Best line from the session</div>
        <div class="poster-quote">"{pull_quote}"</div>
        <div class="poster-foot">
          <span>{safe_session_label}</span>
          <span>{safe_preset_title}</span>
        </div>
      </aside>
    </section>
    <section class="grid">
      <article class="card card-primary fade-up delay-1">
        <div class="label">Caption</div>
        <p class="caption" id="caption">{safe_caption}</p>
        <p class="microcopy">
          This page is designed to be screenshot-friendly. Copy the caption, grab the highlight,
          and send the result to someone immediately.
        </p>
        <div class="controls">
          <button id="copy-caption" type="button">Copy Caption</button>
          <a class="link secondary" href="{session_log_uri}">Open Session Log</a>
        </div>
        <div class="footer-note">
          Tip: the best social posts use the caption plus the pull-quote poster from the top of
          this page.
        </div>
      </article>
      <article class="card card-side fade-up delay-1">
        <div class="label">Spotlight Quote</div>
        <div class="quote-block">
          <p class="quote-text" id="spotlight-quote">{pull_quote}</p>
          <div class="quote-meta">{safe_preset_title} / {safe_session_label}</div>
        </div>
        <div class="controls" style="margin-top:14px;">
          <button id="copy-quote" type="button">Copy Quote</button>
        </div>
      </article>
      <article class="card card-side fade-up delay-2">
        <div class="label">Session Details</div>
        <div class="stat-grid">
          <div class="stat">
            <strong>Mode</strong>
            <span>{safe_session_label}</span>
          </div>
          <div class="stat">
            <strong>Preset</strong>
            <span>{safe_preset_title}</span>
          </div>
          <div class="stat">
            <strong>Topic</strong>
            <span>{safe_topic}</span>
          </div>
          <div class="stat">
            <strong>Log</strong>
            <span>{launcher_log_value}</span>
          </div>
        </div>
      </article>
      <article class="card card-primary fade-up delay-2">
        <div class="label">Quick Re-run</div>
        <code id="rerun-command">{safe_rerun_command}</code>
        <div class="controls" style="margin-top:14px;">
          <button id="copy-rerun" type="button">Copy Command</button>
          <a class="link secondary" href="{poster_uri}">Open Poster SVG</a>
        </div>
      </article>
      <article class="card card-wide fade-up delay-3">
        <div class="label">Try Next</div>
        <p class="microcopy">
          Keep the same spark, but run it through a different preset so the result feels new
          instead of repetitive.
        </p>
        <div class="next-grid">{follow_up_cards_html}</div>
        <div class="controls" style="margin-top:14px;">
          <a class="link secondary" href="{showcase_uri}">Open Local Showcase</a>
        </div>
      </article>
      <article class="card card-wide fade-up delay-3">
        <div class="label">Session Highlight</div>
        <div class="excerpt">{safe_excerpt or 'Run the session again to capture a fresh highlight.'}</div>
        {f'<img class="poster-preview" src="{poster_uri}" alt="Poster preview for {safe_topic}">' if poster_uri else ""}
      </article>
    </section>
  </main>
  <script>
    const wireCopy = (buttonId, targetId, readyText) => {{
      const button = document.getElementById(buttonId);
      const target = document.getElementById(targetId);
      if (!button || !target || !navigator.clipboard) return;
      button.addEventListener("click", async () => {{
        const original = button.textContent;
        try {{
          await navigator.clipboard.writeText(target.innerText);
          button.textContent = readyText;
        }} catch (_error) {{
          button.textContent = "Copy failed";
        }}
        window.setTimeout(() => {{
          button.textContent = original;
        }}, 1400);
      }});
    }};
    wireCopy("copy-caption", "caption", "Caption copied");
    wireCopy("copy-quote", "spotlight-quote", "Quote copied");
    wireCopy("copy-rerun", "rerun-command", "Command copied");
    document.querySelectorAll("[data-copy-target]").forEach((button) => {{
      const targetId = button.getAttribute("data-copy-target");
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target || !navigator.clipboard) return;
      button.addEventListener("click", async () => {{
        const original = button.textContent;
        try {{
          await navigator.clipboard.writeText(target.innerText);
          button.textContent = "Command copied";
        }} catch (_error) {{
          button.textContent = "Copy failed";
        }}
        window.setTimeout(() => {{
          button.textContent = original;
        }}, 1400);
      }});
    }});
  </script>
</body>
</html>
"""


def _write_beginner_share_card(
    args: argparse.Namespace,
    repo_root: Path,
    *,
    requested_mode: str,
    launched_mode: str,
    exit_code: int,
    session_log_path: Path | None = None,
) -> Path | None:
    if requested_mode not in {"beginner", "demo"}:
        return None

    library_root = _resolve_library_root(args, repo_root)
    share_dir = library_root / "meeting_archives"
    share_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    share_markdown_path = share_dir / f"BEGINNER_SHARE_{timestamp}.md"
    share_html_path = share_dir / f"BEGINNER_SHARE_{timestamp}.html"
    poster_path = _poster_path_for_share_card(share_html_path)
    session_log = session_log_path or (library_root / "RAIN_LAB_MEETING_LOG.md")
    excerpt = _read_share_excerpt(session_log)
    topic = getattr(args, "display_topic", args.topic or "Open exploration")
    preset = _resolve_beginner_preset(getattr(args, "preset", None))
    preset_title = preset.title if preset else "Custom Prompt"
    demo_mode = requested_mode == "demo"
    if demo_mode:
        session_label = "Instant demo, no setup required"
    else:
        session_label = "Research debate" if launched_mode == "rlm" else "Guided chat"
    launcher_log = _resolve_launcher_log_path(args, repo_root) or "[disabled]"
    rerun_command = f'python rain_lab.py --mode {requested_mode} --topic "{topic}"'
    if preset is not None:
        rerun_command += f" --preset {preset.slug}"
    follow_up_moves = _build_follow_up_moves(topic, preset.slug if preset is not None else None)
    showcase_path = share_dir / "RAIN_LAB_SHOWCASE.html"
    caption = (
        f'I just tried the instant R.A.I.N. Lab demo for "{topic}".'
        if demo_mode
        else f'I explored "{topic}" with R.A.I.N. Lab in beginner mode.'
    )
    if preset is not None:
        caption += f" It used the {preset.title.lower()} preset."
    pull_quote = _share_pull_quote(excerpt) or (
        "No model setup required." if demo_mode else "Saved as a shareable local artifact."
    )

    lines = [
        "# Beginner Session Share Card",
        "",
        f"Topic: {topic}",
        f"Preset: {preset_title}",
        f"Session style: {session_label}",
        f"UI preference used: {args.ui}",
        f"Exit code: {exit_code}",
        "",
        "## Suggested Share Caption",
        "",
        caption,
        "",
    ]

    if excerpt:
        lines.extend(
            [
                "## Session Highlight",
                "",
                excerpt,
                "",
            ]
        )

    lines.extend(
        [
            "## Files",
            "",
            f"- Session log: {session_log}",
            f"- Launcher events: {launcher_log}",
            f"- HTML card: {share_html_path}",
            f"- Poster SVG: {poster_path}",
            "",
            "## Quick Re-run",
            "",
            rerun_command,
            "",
            "## Try Next",
            "",
        ]
    )
    for move in follow_up_moves:
        lines.extend(
            [
                f"- {move.label}: {move.description}",
                f"  {move.command}",
            ]
        )
    lines.extend(
        [
            "",
            f"Open local showcase: {showcase_path}",
            "",
        ]
    )

    share_markdown_path.write_text("\n".join(lines), encoding="utf-8")
    poster_path.write_text(
        _build_beginner_poster_svg(
            topic=topic,
            preset_title=preset_title,
            session_label=session_label,
            caption=caption,
            pull_quote=pull_quote,
            demo_mode=demo_mode,
        ),
        encoding="utf-8",
    )
    share_html_path.write_text(
        _build_beginner_share_html_v2(
            title=f"R.A.I.N. Lab Share Card · {topic}",
            topic=topic,
            session_label=session_label,
            caption=caption,
            preset_title=preset_title,
            demo_mode=demo_mode,
            excerpt=excerpt,
            session_log=session_log,
            launcher_log=launcher_log,
            rerun_command=rerun_command,
            follow_up_moves=follow_up_moves,
            showcase_path=showcase_path,
            poster_path=poster_path,
        ),
        encoding="utf-8",
    )
    return share_html_path


def _build_demo_session_markdown(args: argparse.Namespace) -> str:
    preset = _resolve_beginner_preset(getattr(args, "preset", None)) or BEGINNER_PRESETS["startup-debate"]
    topic = getattr(args, "display_topic", args.topic or preset.default_topic)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if preset.slug == "startup-debate":
        body = f"""
## Opening Spark

James frames the idea as a real startup pitch: {topic}.

## Demo Exchange

Founder Voice:
This could win because the pain is obvious, the value is easy to repeat, and the best version is surprisingly memorable.

Skeptic Voice:
Right now it still sounds generic. The wedge is weak, the first user is blurry, and the
retention story is doing too much hand-waving.

Builder Voice:
Shrink the surface. Make one painful job dramatically easier. Then give it one line that a user
would actually say to a friend.

## Punchy Takeaway

The demo says the concept is not dead. It just needs a more precise buyer, a stronger promise,
and one feature people would immediately miss.
""".strip()
    elif preset.slug == "idea-roast":
        body = f"""
## Opening Spark

James takes a swing at the idea: {topic}.

## Demo Exchange

Roast:
This version feels like three products wearing the same hoodie. It wants to be clever, social,
premium, and frictionless all at once.

Rescue:
Keep the strongest emotional hook. Cut the rest. If the pitch cannot survive in one sentence,
the product is still hiding from itself.

## Punchy Takeaway

The roast lands, but the fix is clear: sharper audience, smaller promise, faster payoff.
""".strip()
    else:
        body = f"""
## Opening Spark

James explains the topic in plain language: {topic}.

## Demo Exchange

Simple Version:
Think of it like pushing someone on a swing. Tiny pushes do almost nothing unless you hit the
timing just right. When the timing matches, the motion suddenly gets bigger.

Why It Matters:
That is the difference between noise and resonance. Same effort, much bigger effect.

## Punchy Takeaway

The demo turns a dense concept into something concrete enough to retell.
""".strip()

    return f"""# R.A.I.N. Lab Instant Demo

Date: {timestamp}
Preset: {preset.title}
Topic: {topic}
Mode Feel: {preset.recommended_mode}

Note: This is a no-model demo generated locally so new users can try the product flow before setup.

{body}
"""


def _run_demo_session(
    args: argparse.Namespace,
    repo_root: Path,
    log_path: Path | None,
) -> int:
    preset = _resolve_beginner_preset(getattr(args, "preset", None)) or BEGINNER_PRESETS["startup-debate"]
    library_root = _resolve_library_root(args, repo_root)
    archive_dir = library_root / "meeting_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_log_path = archive_dir / f"DEMO_SESSION_{timestamp}.md"
    session_log_path.write_text(_build_demo_session_markdown(args), encoding="utf-8")

    print(f"{ANSI_CYAN}Instant demo mode: no local model required.{ANSI_RESET}")
    print(f"{ANSI_DIM}{preset.summary}{ANSI_RESET}")
    print(f"{ANSI_GREEN}Demo session saved to: {session_log_path}{ANSI_RESET}")
    _append_launcher_event(
        log_path,
        "demo_session_generated",
        preset=preset.slug,
        topic=getattr(args, "display_topic", args.topic),
        session_log=str(session_log_path),
    )

    share_card_path = _write_beginner_share_card(
        args,
        repo_root,
        requested_mode="demo",
        launched_mode=preset.recommended_mode,
        exit_code=0,
        session_log_path=session_log_path,
    )
    if share_card_path is not None:
        print(f"{ANSI_GREEN}Share card ready: {share_card_path}{ANSI_RESET}")
        showcase_path = _write_beginner_showcase_page(args, repo_root, latest_share_card=share_card_path)
        print(f"{ANSI_GREEN}Local showcase ready: {showcase_path}{ANSI_RESET}")
        _print_follow_up_moves(getattr(args, "display_topic", args.topic), getattr(args, "preset", None))
        _append_launcher_event(
            log_path,
            "beginner_share_card_created",
            path=str(share_card_path),
            launched_mode="demo",
        )
        _append_launcher_event(
            log_path,
            "beginner_showcase_created",
            path=str(showcase_path),
            launched_mode="demo",
        )

    return 0


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    known, passthrough = _split_passthrough_args(argv)
    default_ui_mode = os.environ.get("RAIN_UI_MODE", "off").strip().lower()
    if default_ui_mode not in VALID_UI_MODES:
        default_ui_mode = "off"
    default_restart_sidecars = _env_bool("RAIN_RESTART_SIDECARS", True)

    parser = argparse.ArgumentParser(description="Unified launcher for rain_lab_meeting modes")
    parser.add_argument(
        "--mode",
        choices=[
            "beginner",
            "demo",
            "rlm",
            "chat",
            "godot",
            "hello-os",
            "compile",
            "preflight",
            "backup",
            "first-run",
            "wizard",
            "start",
            "validate",
            "models",
            "onboard",
            "status",
        ],
        default="chat",
        help=(
            "Which engine to run: beginner (easy mode), wizard (guided help),"
            " demo (no-setup preview), start (same as wizard), chat (talk to AI),"
            " validate (check system), models (list AI models), status (show status),"
            " onboard (first-time"
            " setup), rlm (tool-exec), godot (chat + visual), hello-os"
            " (executable), compile (build knowledge), preflight (env checks),"
            " backup (snapshot), first-run (onboarding)"
        ),
    )
    parser.add_argument("--topic", type=str, default=None, help="Meeting topic")
    parser.add_argument(
        "--preset",
        choices=BEGINNER_PRESET_CHOICES,
        default=None,
        help="Beginner/demo preset. Adds a playful prompt frame and default topic.",
    )
    parser.add_argument(
        "--library",
        type=str,
        default=None,
        help="Library path (used directly by chat mode; exported as JAMES_LIBRARY_PATH for rlm mode)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Turn limit alias: maps to --turns (rlm) or --max-turns (chat)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("RAIN_LM_TIMEOUT", "180")),
        help="Chat mode only: LM request timeout in seconds (default: 180; maps to --timeout)",
    )
    parser.add_argument(
        "--temp",
        type=float,
        default=float(os.environ.get("RAIN_CHAT_TEMP", "0.7")),
        help="Chat/Godot mode only: generation temperature (default: 0.7; set higher for more exploratory outputs)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("RAIN_CHAT_MAX_TOKENS", "320")),
        help="Chat/Godot mode only: response token budget per turn (default: 320)",
    )
    parser.add_argument(
        "--recursive-depth",
        type=int,
        default=None,
        help="Chat mode only: internal self-reflection passes (maps to --recursive-depth)",
    )
    parser.add_argument(
        "--no-recursive-intellect",
        action="store_true",
        help="Chat mode only: disable recursive self-reflection",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Reserved for runtime integrations; ignored by meeting chat mode.",
    )
    parser.add_argument(
        "--ui",
        choices=sorted(VALID_UI_MODES),
        default=default_ui_mode,
        help=(
            "Chat/Godot UI behavior: auto launches avatars when available,"
            " on requires UI stack, off (default) forces CLI-only."
        ),
    )
    parser.add_argument(
        "--godot-client-bin",
        type=str,
        default=os.environ.get("RAIN_GODOT_BIN", ""),
        help="UI mode: Godot executable name/path (defaults to RAIN_GODOT_BIN, then godot4/godot).",
    )
    parser.add_argument(
        "--godot-project-dir",
        type=str,
        default=os.environ.get("RAIN_GODOT_PROJECT_DIR", "godot_client"),
        help="UI mode: Godot project directory (must contain project.godot).",
    )
    parser.add_argument(
        "--godot-events-log",
        type=str,
        default=os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl"),
        help="Godot mode: JSONL events file used by the bridge and emitter.",
    )
    parser.add_argument(
        "--godot-tts-audio-dir",
        type=str,
        default=os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio"),
        help="Godot mode: per-turn TTS export directory.",
    )
    parser.add_argument(
        "--godot-ws-host",
        type=str,
        default="127.0.0.1",
        help="Godot mode: bridge WebSocket host.",
    )
    parser.add_argument(
        "--godot-ws-port",
        type=int,
        default=8765,
        help="Godot mode: bridge WebSocket port.",
    )
    parser.add_argument(
        "--no-godot-bridge",
        action="store_true",
        help="Godot mode: deprecated (bridge is now embedded). Kept for CLI compatibility.",
    )
    parser.add_argument(
        "--no-godot-client",
        action="store_true",
        help="Godot/chat UI mode: do not auto-launch the Godot client.",
    )
    parser.add_argument(
        "--launcher-log",
        type=str,
        default=os.environ.get("RAIN_LAUNCHER_LOG", "meeting_archives/launcher_events.jsonl"),
        help="Write launcher lifecycle events to JSONL (relative to --library or repo root).",
    )
    parser.add_argument(
        "--no-launcher-log",
        action="store_true",
        help="Disable JSONL launcher event logging.",
    )
    parser.add_argument(
        "--restart-sidecars",
        action="store_true",
        dest="restart_sidecars",
        default=default_restart_sidecars,
        help="Auto-restart Godot sidecars (bridge/client) if they exit while session is running.",
    )
    parser.add_argument(
        "--no-restart-sidecars",
        action="store_false",
        dest="restart_sidecars",
        help="Disable sidecar auto-restart supervision.",
    )
    parser.add_argument(
        "--max-sidecar-restarts",
        type=int,
        default=_env_int("RAIN_MAX_SIDECAR_RESTARTS", 2, 0),
        help="Maximum restart attempts per sidecar process.",
    )
    parser.add_argument(
        "--sidecar-restart-backoff",
        type=float,
        default=_env_float("RAIN_SIDECAR_RESTART_BACKOFF", 0.5, 0.0),
        help="Delay in seconds before restarting a failed sidecar.",
    )
    parser.add_argument(
        "--sidecar-poll-interval",
        type=float,
        default=_env_float("RAIN_SIDECAR_POLL_INTERVAL", 0.25, 0.05),
        help="Supervisor poll interval in seconds while session is running.",
    )
    args = parser.parse_args(known)
    return args, passthrough


def build_command(args: argparse.Namespace, passthrough: list[str], repo_root: Path) -> list[str]:

    if args.mode == "first-run":
        target = repo_root / "rain_first_run.py"
        cmd = [sys.executable, str(target)]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "compile":
        target = repo_root / "library_compiler.py"
        cmd = [sys.executable, str(target)]
        lib_path = args.library or str(repo_root)
        cmd.extend(["--library", lib_path])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "preflight":
        target = repo_root / "rain_preflight_check.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough)
        return cmd

    if args.mode == "models":
        # Show models info - run preflight with models focus
        target = repo_root / "rain_preflight_check.py"
        cmd = [sys.executable, str(target), "--verbose"]
        cmd.extend(passthrough)
        return cmd

    if args.mode == "backup":
        target = repo_root / "rain_lab_backup.py"
        cmd = [sys.executable, str(target)]
        if args.library:
            cmd.extend(["--library", args.library])
        cmd.extend(passthrough)
        return cmd

    if args.mode == "hello-os":
        target = repo_root / "hello_os_executable.py"
        cmd = [sys.executable, str(target)]
        cmd.extend(passthrough if passthrough else ["inspect"])
        return cmd

    if args.mode == "rlm":
        target = repo_root / "rain_lab_meeting.py"
        cmd = [sys.executable, str(target)]
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.turns is not None:
            cmd.extend(["--turns", str(args.turns)])
        cmd.extend(passthrough)
        return cmd

    if args.mode in {"chat", "godot"}:
        target = repo_root / "rain_lab_meeting_chat_version.py"
        if not target.exists():
            raise FileNotFoundError("Chat/Godot mode requires rain_lab_meeting_chat_version.py")
        cmd = [sys.executable, str(target)]
        if args.mode == "godot":
            cmd.extend(
                [
                    "--emit-visual-events",
                    "--visual-events-host",
                    args.godot_ws_host,
                    "--visual-events-port",
                    str(args.godot_ws_port),
                    "--tts-audio-dir",
                    args.godot_tts_audio_dir,
                ]
            )
        if args.topic:
            cmd.extend(["--topic", args.topic])
        if args.library:
            cmd.extend(["--library", args.library])
        if args.turns is not None:
            cmd.extend(["--max-turns", str(args.turns)])
        if args.timeout is not None:
            cmd.extend(["--timeout", str(args.timeout)])
        if args.temp is not None:
            cmd.extend(["--temp", str(args.temp)])
        if args.max_tokens is not None:
            cmd.extend(["--max-tokens", str(args.max_tokens)])
        if args.no_recursive_intellect or args.recursive_depth is None:
            cmd.append("--no-recursive-intellect")
        elif args.recursive_depth is not None:
            cmd.extend(["--recursive-depth", str(args.recursive_depth)])
        cmd.extend(passthrough)
        return cmd


def build_godot_bridge_command(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    """Deprecated: bridge is now embedded in the main process. Returns None."""
    return None


def _resolve_executable(candidate: str) -> str | None:
    text = (candidate or "").strip()
    if not text:
        return None

    path_candidate = Path(text).expanduser()
    if path_candidate.is_absolute() or any(sep in text for sep in ("/", "\\")):
        if path_candidate.exists():
            return str(path_candidate)
        return None

    return shutil.which(text)


def build_godot_client_command(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    if args.no_godot_client:
        return None

    project_dir = Path(args.godot_project_dir).expanduser()
    if not project_dir.is_absolute():
        project_dir = (repo_root / project_dir).resolve()
    project_file = project_dir / "project.godot"
    if not project_file.exists():
        return None

    candidate_bins: list[str] = []
    if args.godot_client_bin:
        candidate_bins.append(args.godot_client_bin)
    candidate_bins.extend(["godot4", "godot"])

    for candidate in candidate_bins:
        resolved = _resolve_executable(candidate)
        if resolved:
            return [resolved, "--path", str(project_dir)]

    return None


@dataclass(frozen=True)
class LaunchPlan:
    effective_mode: str
    launch_bridge: bool = False  # Deprecated: bridge is now embedded; kept for API compat
    launch_godot_client: bool = False
    godot_client_cmd: list[str] | None = None


@dataclass
class SidecarSpec:
    name: str
    command: list[str]
    critical: bool = False


@dataclass
class SidecarState:
    spec: SidecarSpec
    process: subprocess.Popen[bytes]
    restart_count: int = 0
    active: bool = True


def _resolve_launcher_log_path(args: argparse.Namespace, repo_root: Path) -> Path | None:
    if args.no_launcher_log:
        return None

    raw = (args.launcher_log or "").strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate

    if args.library:
        base_dir = Path(args.library).expanduser()
        if not base_dir.is_absolute():
            base_dir = (Path.cwd() / base_dir).resolve()
    else:
        base_dir = repo_root

    return (base_dir / candidate).resolve()


def _append_launcher_event(log_path: Path | None, event: str, **payload: object) -> None:
    if log_path is None:
        return

    record = {"ts": _utc_now_iso(), "event": event, **payload}
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Logging must never block the launcher.
        return


def _launch_sidecar(
    spec: SidecarSpec,
    child_env: dict[str, str] | None,
    log_path: Path | None,
) -> SidecarState:
    _spinner(f"Starting {spec.name}")
    print(f"{ANSI_CYAN}Launching {spec.name}: {' '.join(spec.command)}{ANSI_RESET}", flush=True)
    process = subprocess.Popen(spec.command, env=child_env)
    _append_launcher_event(
        log_path,
        "sidecar_started",
        sidecar=spec.name,
        pid=process.pid,
        command=spec.command,
        critical=spec.critical,
        restart_count=0,
    )
    return SidecarState(spec=spec, process=process)


def _supervise_sidecars(
    sidecars: list[SidecarState],
    child_env: dict[str, str] | None,
    args: argparse.Namespace,
    log_path: Path | None,
) -> str | None:
    for sidecar in sidecars:
        if not sidecar.active:
            continue

        exit_code = sidecar.process.poll()
        if exit_code is None:
            continue

        _append_launcher_event(
            log_path,
            "sidecar_exited",
            sidecar=sidecar.spec.name,
            exit_code=exit_code,
            pid=sidecar.process.pid,
            restart_count=sidecar.restart_count,
            critical=sidecar.spec.critical,
        )
        print(
            f"{ANSI_YELLOW}Warning: {sidecar.spec.name} exited with code {exit_code}.{ANSI_RESET}",
            flush=True,
        )

        should_restart = args.restart_sidecars and sidecar.restart_count < max(0, int(args.max_sidecar_restarts))
        if should_restart:
            sidecar.restart_count += 1
            backoff = max(0.0, float(args.sidecar_restart_backoff))
            if backoff > 0.0:
                time.sleep(backoff)

            try:
                sidecar.process = subprocess.Popen(sidecar.spec.command, env=child_env)
            except Exception as exc:
                sidecar.active = False
                _append_launcher_event(
                    log_path,
                    "sidecar_restart_failed",
                    sidecar=sidecar.spec.name,
                    restart_count=sidecar.restart_count,
                    error=str(exc),
                    critical=sidecar.spec.critical,
                )
                if sidecar.spec.critical:
                    return f"{sidecar.spec.name} failed to restart ({exc})"
                continue

            _append_launcher_event(
                log_path,
                "sidecar_restarted",
                sidecar=sidecar.spec.name,
                pid=sidecar.process.pid,
                restart_count=sidecar.restart_count,
                max_restarts=args.max_sidecar_restarts,
            )
            print(
                f"{ANSI_GREEN}Recovered: restarted {sidecar.spec.name} "
                f"({sidecar.restart_count}/{args.max_sidecar_restarts}).{ANSI_RESET}",
                flush=True,
            )
            continue

        sidecar.active = False
        if sidecar.spec.critical:
            return f"{sidecar.spec.name} stopped (exit {exit_code}) and restart budget is exhausted."

    return None


def resolve_launch_plan(args: argparse.Namespace, repo_root: Path) -> LaunchPlan:
    visual_runtime_exists = (repo_root / "rain_lab_meeting_chat_version.py").exists()
    godot_client_cmd = build_godot_client_command(args, repo_root)

    wants_client = not args.no_godot_client

    if args.mode == "chat":
        if args.ui == "off":
            return LaunchPlan(effective_mode="chat")

        if args.ui == "on":
            missing: list[str] = []
            if not visual_runtime_exists:
                missing.append("rain_lab_meeting_chat_version.py")
            if wants_client and godot_client_cmd is None:
                missing.append("Godot executable + godot_client/project.godot")
            if missing:
                missing_str = ", ".join(missing)
                raise RuntimeError(f"UI mode 'on' requires: {missing_str}")
            return LaunchPlan(
                effective_mode="godot",
                launch_godot_client=wants_client and godot_client_cmd is not None,
                godot_client_cmd=godot_client_cmd,
            )

        # ui=auto: prefer avatars only when the full stack is available.
        if not visual_runtime_exists:
            return LaunchPlan(effective_mode="chat")
        if wants_client and godot_client_cmd is None:
            return LaunchPlan(effective_mode="chat")
        return LaunchPlan(
            effective_mode="godot",
            launch_godot_client=wants_client and godot_client_cmd is not None,
            godot_client_cmd=godot_client_cmd,
        )

    if args.mode == "godot":
        if not visual_runtime_exists:
            raise FileNotFoundError("Godot mode requires rain_lab_meeting_chat_version.py")

        launch_client = args.ui != "off" and wants_client and godot_client_cmd is not None
        return LaunchPlan(
            effective_mode="godot",
            launch_godot_client=launch_client,
            godot_client_cmd=godot_client_cmd if launch_client else None,
        )

    return LaunchPlan(effective_mode=args.mode)


def _build_sidecar_specs(
    args: argparse.Namespace,
    launch_plan: LaunchPlan,
    bridge_cmd: list[str] | None = None,
) -> list[SidecarSpec]:
    strict_ui = args.ui == "on"
    specs: list[SidecarSpec] = []

    if launch_plan.launch_godot_client and launch_plan.godot_client_cmd is not None:
        specs.append(
            SidecarSpec(
                name="Godot avatar client",
                command=launch_plan.godot_client_cmd,
                critical=strict_ui,
            )
        )

    return specs


def _copy_args_with_mode(args: argparse.Namespace, mode: str) -> argparse.Namespace:
    payload = vars(args).copy()
    payload["mode"] = mode
    return argparse.Namespace(**payload)


def _terminate_process(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()


async def run_rain_lab(
    query: str,
    mode: str = "chat",
    agent: str | None = None,
    recursive_depth: int = 1,
) -> str:
    """Async integration entrypoint used by non-CLI gateways (e.g., Telegram).

    This launcher keeps backward compatibility with the existing CLI while
    providing an importable symbol for adapters.

    By default it tries to import a richer runtime implementation from
    ``rain_lab_runtime.py``. If that module is absent, an explicit error is
    raised so integrators know where to wire their project-specific logic.
    """
    try:
        from rain_lab_runtime import run_rain_lab as runtime_run_rain_lab
    except ImportError as exc:
        raise RuntimeError(
            "run_rain_lab is not wired yet. Add rain_lab_runtime.py with an "
            "async run_rain_lab(...) implementation, or replace rain_lab.run_rain_lab "
            "with your project's existing async entrypoint."
        ) from exc

    return await runtime_run_rain_lab(
        query=query,
        mode=mode,
        agent=agent,
        recursive_depth=recursive_depth,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Handle simple/friendly mode aliases before full parsing
    if argv and argv[0] == "--mode" and len(argv) > 1:
        mode_arg = argv[1]
        # Map friendly names to actual modes
        mode_map = {
            "start": "wizard",
            "easy": "beginner",
            "try": "demo",
            "onboard": "first-run",
            "validate": "preflight",
            "models": "preflight",  # Will show models after preflight
            "status": "preflight",  # Status is same as preflight
        }
        if mode_arg in mode_map:
            argv[1] = mode_map[mode_arg]

    args, passthrough = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    requested_mode = args.mode
    ui_was_explicit = "--ui" in argv
    banner_printed = False

    if not argv:
        args.mode = "wizard"
        requested_mode = "wizard"

    # Handle wizard mode - interactive guidance
    if args.mode == "wizard":
        _print_banner()
        banner_printed = True
        showcase_path = _write_beginner_showcase_page(args, repo_root)
        print(f"\n{ANSI_CYAN}Welcome to R.A.I.N. Lab!{ANSI_RESET}")
        print(
            f"{ANSI_DIM}I'll help you get started. Press Enter for a fast no-setup demo, "
            f"or pick a path below.{ANSI_RESET}"
        )
        print(f"{ANSI_DIM}Local showcase: {showcase_path}{ANSI_RESET}\n")

        print("What would you like to do first?")
        print(f"  {ANSI_GREEN}1{ANSI_RESET} - Instant demo (recommended first step)")
        print(f"  {ANSI_GREEN}2{ANSI_RESET} - Beginner mode with my own idea")
        print(f"  {ANSI_GREEN}3{ANSI_RESET} - First-time setup")
        print(f"  {ANSI_GREEN}4{ANSI_RESET} - Check if my system is ready")
        print(f"  {ANSI_GREEN}5{ANSI_RESET} - Run a research debate")
        print(f"  {ANSI_GREEN}6{ANSI_RESET} - See what AI models are available")

        try:
            choice = input(f"\n{ANSI_YELLOW}Enter number (1-6, or press Enter for the demo): {ANSI_RESET}").strip()
        except KeyboardInterrupt:
            print(f"\n{ANSI_RED}Goodbye!{ANSI_RESET}")
            return 0

        if choice in {"", "1"}:
            print(f"\n{ANSI_GREEN}Starting instant demo...{ANSI_RESET}")
            args.mode = "demo"
            args.preset = "startup-debate"
        elif choice == "2":
            print(f"\n{ANSI_GREEN}Starting beginner mode...{ANSI_RESET}")
            args.mode = "beginner"
        elif choice == "3":
            print(f"\n{ANSI_GREEN}Starting first-time setup...{ANSI_RESET}")
            args.mode = "first-run"
        elif choice == "4":
            print(f"\n{ANSI_GREEN}Running system check...{ANSI_RESET}")
            args.mode = "preflight"
        elif choice == "5":
            print(f"\n{ANSI_GREEN}Starting research meeting...{ANSI_RESET}")
            args.mode = "rlm"
            print(f"{ANSI_DIM}What's your research topic?{ANSI_RESET}")
            try:
                topic = input(f"{ANSI_GREEN}Topic: {ANSI_RESET}").strip()
                if topic:
                    args.topic = topic
            except KeyboardInterrupt:
                print(f"\n{ANSI_RED}Goodbye!{ANSI_RESET}")
                return 0
        elif choice == "6":
            print(f"\n{ANSI_GREEN}Checking available models...{ANSI_RESET}")
            args.mode = "preflight"
        else:
            print(f"\n{ANSI_YELLOW}Starting instant demo...{ANSI_RESET}")
            args.mode = "demo"
            args.preset = "startup-debate"

        requested_mode = args.mode

    if requested_mode == "beginner":
        if (
            not args.topic
            and not getattr(args, "preset", None)
            and "-h" not in passthrough
            and "--help" not in passthrough
        ):
            if not banner_printed:
                _print_banner()
                banner_printed = True
            print(f"\n{ANSI_CYAN}Beginner mode keeps this simple.{ANSI_RESET}")
            print(f"{ANSI_DIM}Pick a fun starter, type your own idea, or jump into an instant demo.{ANSI_RESET}")
            try:
                starter_input = input(f"{ANSI_GREEN}{_beginner_topic_prompt()}{ANSI_RESET}")
                preset_name, typed_topic, wants_demo = _apply_beginner_shortcut(starter_input)
                if wants_demo:
                    args.mode = "demo"
                    requested_mode = "demo"
                    args.preset = "startup-debate"
                else:
                    if preset_name is not None:
                        args.preset = preset_name
                    if typed_topic is not None:
                        args.topic = typed_topic
            except KeyboardInterrupt:
                print(f"\n{ANSI_RED}Aborted.{ANSI_RESET}")
                return 1

        if requested_mode == "beginner":
            args = _prepare_beginner_args(args, ui_was_explicit=ui_was_explicit)
            preset = _resolve_beginner_preset(getattr(args, "preset", None))
            if not banner_printed:
                _print_banner()
                banner_printed = True
            chosen_label = "research debate" if args.mode == "rlm" else "guided chat"
            if preset is not None:
                print(f"{ANSI_GREEN}Beginner mode: choosing {preset.title} via {chosen_label}.{ANSI_RESET}")
            else:
                print(f"{ANSI_GREEN}Beginner mode: choosing {chosen_label}.{ANSI_RESET}")
            if args.ui == "auto":
                print(
                    f"{ANSI_DIM}If avatars are available, I will use them. Otherwise this stays "
                    f"in the CLI.{ANSI_RESET}"
                )

    if args.mode == "demo":
        args = _prepare_demo_args(args)
        preset = _resolve_beginner_preset(getattr(args, "preset", None))
        if not banner_printed:
            _print_banner()
            banner_printed = True
        if preset is not None:
            print(f"{ANSI_GREEN}Instant demo: loading {preset.title}.{ANSI_RESET}")

    if not banner_printed:
        _print_banner()
        banner_printed = True

    # Interactive prompt if topic is missing (and not asking for help)
    if (
        args.mode not in {"hello-os", "compile", "preflight", "backup", "first-run", "wizard"}
        and not args.topic
        and "-h" not in passthrough
        and "--help" not in passthrough
    ):
        print(f"\n{ANSI_YELLOW}Research Topic needed.{ANSI_RESET}")
        print(f"{ANSI_DIM}Example: 'Guarino paper', 'Quantum Resonance', 'The nature of time'{ANSI_RESET}")
        try:
            # Show cursor and prompt
            topic_input = input(f"{ANSI_GREEN}Enter topic: {ANSI_RESET}").strip()
            if topic_input:
                args.topic = topic_input
            else:
                args.topic = "Open research discussion"
        except KeyboardInterrupt:
            print(f"\n{ANSI_RED}Aborted.{ANSI_RESET}")
            return 1

    log_path = _resolve_launcher_log_path(args, repo_root)
    _append_launcher_event(
        log_path,
        "launcher_started",
        requested_mode=requested_mode,
        ui=args.ui,
        restart_sidecars=bool(args.restart_sidecars),
        max_sidecar_restarts=max(0, int(args.max_sidecar_restarts)),
        sidecar_restart_backoff=max(0.0, float(args.sidecar_restart_backoff)),
        sidecar_poll_interval=max(0.05, float(args.sidecar_poll_interval)),
        passthrough=passthrough,
    )

    if args.mode == "demo":
        exit_code = _run_demo_session(args, repo_root, log_path)
        _append_launcher_event(log_path, "launcher_finished", exit_code=exit_code, mode="demo")
        return exit_code

    launch_plan = resolve_launch_plan(args, repo_root)
    if args.mode == "chat" and args.ui == "auto":
        if launch_plan.effective_mode == "godot":
            print(f"{ANSI_GREEN}UI auto: Godot avatars available; launching visual mode.{ANSI_RESET}")
        else:
            print(f"{ANSI_DIM}UI auto: Godot UI unavailable; running CLI chat mode.{ANSI_RESET}")

    effective_args = _copy_args_with_mode(args, launch_plan.effective_mode)
    cmd = build_command(effective_args, passthrough, repo_root)

    sidecar_specs = _build_sidecar_specs(args, launch_plan)

    child_env = None
    if args.library:
        child_env = dict(os.environ)
        child_env["JAMES_LIBRARY_PATH"] = args.library

    sidecars: list[SidecarState] = []
    main_proc: subprocess.Popen[bytes] | None = None
    exit_code = 1

    auto_chat_visual = args.mode == "chat" and args.ui == "auto" and launch_plan.effective_mode == "godot"
    try:
        for spec in sidecar_specs:
            sidecars.append(_launch_sidecar(spec, child_env, log_path))
            time.sleep(0.25)
    except Exception as exc:
        for sidecar in sidecars:
            _terminate_process(sidecar.process)
        sidecars = []

        if auto_chat_visual:
            print(
                f"{ANSI_YELLOW}UI auto: visual startup failed ({exc}); falling back to CLI chat mode.{ANSI_RESET}",
                flush=True,
            )
            _append_launcher_event(
                log_path,
                "ui_auto_fallback",
                reason=str(exc),
                from_mode=launch_plan.effective_mode,
                to_mode="chat",
            )
            effective_args = _copy_args_with_mode(args, "chat")
            cmd = build_command(effective_args, passthrough, repo_root)
            sidecar_specs = []
        else:
            _append_launcher_event(log_path, "launcher_failed", phase="sidecar_launch", error=str(exc))
            raise

    _spinner("Booting VERS3DYNAMICS R.A.I.N. Lab launcher")
    print(f"{ANSI_CYAN}Launching mode={effective_args.mode}...{ANSI_RESET}", flush=True)
    _append_launcher_event(
        log_path,
        "session_launch",
        mode=effective_args.mode,
        command=cmd,
        sidecars=[sidecar.spec.name for sidecar in sidecars],
    )
    try:
        main_proc = subprocess.Popen(cmd, env=child_env)
        _append_launcher_event(
            log_path,
            "session_started",
            mode=effective_args.mode,
            pid=main_proc.pid,
        )

        poll_interval = max(0.05, float(args.sidecar_poll_interval))
        while True:
            result_code = main_proc.poll()
            if result_code is not None:
                exit_code = int(result_code)
                break

            fatal = _supervise_sidecars(sidecars, child_env, args, log_path)
            if fatal:
                print(f"{ANSI_RED}Critical sidecar failure: {fatal}{ANSI_RESET}", flush=True)
                _append_launcher_event(log_path, "sidecar_fatal", reason=fatal)
                _terminate_process(main_proc)
                exit_code = 1
                break

            time.sleep(poll_interval)

        return exit_code
    finally:
        share_card_path = _write_beginner_share_card(
            args,
            repo_root,
            requested_mode=requested_mode,
            launched_mode=effective_args.mode,
            exit_code=exit_code,
        )
        if share_card_path is not None:
            print(f"{ANSI_GREEN}Share card ready: {share_card_path}{ANSI_RESET}", flush=True)
            showcase_path = _write_beginner_showcase_page(args, repo_root, latest_share_card=share_card_path)
            print(f"{ANSI_GREEN}Local showcase ready: {showcase_path}{ANSI_RESET}", flush=True)
            _print_follow_up_moves(getattr(args, "display_topic", args.topic), getattr(args, "preset", None))
            _append_launcher_event(
                log_path,
                "beginner_share_card_created",
                path=str(share_card_path),
                launched_mode=effective_args.mode,
            )
            _append_launcher_event(
                log_path,
                "beginner_showcase_created",
                path=str(showcase_path),
                launched_mode=effective_args.mode,
            )
        _terminate_process(main_proc)
        for sidecar in sidecars:
            _terminate_process(sidecar.process)
        _append_launcher_event(
            log_path,
            "launcher_finished",
            exit_code=exit_code,
            mode=effective_args.mode,
        )


if __name__ == "__main__":
    raise SystemExit(main())
