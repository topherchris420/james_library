"""Terminal and Markdown presentation for :mod:`offline_meeting`.

The terminal view streams the meeting like a live room when stdout is a TTY and
prints it instantly otherwise (pipes, CI, tests). Colors follow the chat mode's
agent palette and respect ``NO_COLOR``. Box-drawing glyphs fall back to ASCII
when the console encoding cannot represent them.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
import time
from pathlib import Path
from typing import TextIO

from james_library.launcher.offline_meeting import (
    GROUNDING_NONE,
    GROUNDING_PARTIAL,
    GROUNDING_STRONG,
    OfflineMeeting,
    Passage,
    Turn,
)

AGENT_COLORS = {
    "James": "\033[92m",
    "Jasmine": "\033[93m",
    "Luca": "\033[96m",
    "Elena": "\033[95m",
}
BOLD = "\033[1m"
DIM = "\033[90m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

_UNICODE_GLYPHS = {
    "bar": "│",
    "rule": "─",
    "heavy": "━",
    "dot": "●",
    "check": "✓",
    "cross": "✗",
    "dash": "—",
    "sep": "·",
    "meter_on": "■",
    "meter_off": "□",
}
_ASCII_GLYPHS = {
    "bar": "|",
    "rule": "-",
    "heavy": "=",
    "dot": "*",
    "check": "ok",
    "cross": "x",
    "dash": "--",
    "sep": "|",
    "meter_on": "#",
    "meter_off": ".",
}
_GROUNDING_METER = {GROUNDING_STRONG: 3, GROUNDING_PARTIAL: 2, GROUNDING_NONE: 0}


def _honesty_note(meeting: OfflineMeeting) -> str:
    if not meeting.quotes:
        return "No model ran. The dialogue is scripted, and with no evidence in the library it makes no claims."
    return (
        "No model ran. Every quote is copied verbatim from your library and re-verified; "
        "the dialogue around the quotes is scripted."
    )


def display_path(path: Path) -> str:
    """``papers/`` when the corpus sits under the working directory, else the absolute path."""

    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(Path.cwd().resolve())
    except ValueError:
        return f"{resolved}{os.sep}"
    return f"{relative.as_posix()}/" if str(relative) != "." else "./"


def share_highlight(meeting: OfflineMeeting) -> str:
    """One line worth putting on a share card: the counter-argument if there is one."""

    for turn in meeting.turns:
        if turn.speaker == "Elena" and turn.quotes:
            quote = turn.quotes[0]
            return f'Elena, citing {quote.title}: "{quote.text}"'
    return f"Verdict: {meeting.verdict.next_move}"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def render_markdown(meeting: OfflineMeeting, *, timestamp: str, preset_title: str | None = None) -> str:
    library = display_path(meeting.corpus_root)
    matched = len(meeting.matched_terms)
    total = matched + len(meeting.missing_terms)
    lines = [
        "# R.A.I.N. Lab Offline Meeting",
        "",
        f"**Question:** {meeting.question}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Date | {timestamp} |",
        f"| Library | `{library}` ({meeting.corpus_files} papers, {meeting.quotable_passages} quotable passages) |",
        f"| Grounding | {meeting.grounding} ({matched} of {total} question terms found) |",
        "| Model | none (instant demo) |",
    ]
    if preset_title:
        lines.append(f"| Preset | {preset_title} |")
    lines.extend(["", f"> {_honesty_note(meeting)}", "", "## Meeting", ""])

    for turn in meeting.turns:
        lines.append(f"**{turn.speaker}** ({turn.role}, {turn.move}): {turn.lead}")
        lines.append("")
        for quote in turn.quotes:
            lines.append(f"> “{quote.text}”")
            lines.append(f"> — `{quote.citation}` ✓ verbatim")
            lines.append("")
        if turn.coda:
            lines.append(turn.coda)
            lines.append("")

    verdict = meeting.verdict
    lines.extend(
        [
            "## Verdict",
            "",
            f"- **Agreed:** {verdict.agreed}",
            f"- **Contested:** {verdict.contested}",
            f"- **Next move:** {verdict.next_move}",
        ]
    )
    if verdict.read_next:
        lines.append("- **Read next:** " + ", ".join(f"`{citation}`" for citation in verdict.read_next))
    if meeting.suggestions:
        lines.extend(["", "Questions this library can answer:", ""])
        lines.extend(f"- `python rain_lab.py --mode demo --topic \"{question}\"`" for question in meeting.suggestions)

    audit = meeting.audit
    lines.extend(["", "## Citation Audit", ""])
    if audit.checked:
        lines.append(
            f"{audit.verified} of {audit.checked} quotes re-verified verbatim against `{library}` with the same "
            "verifier the live meeting uses."
        )
    else:
        lines.append("No quotes were used, so there was nothing to verify.")
    lines.extend(
        [
            "",
            f"Corpus fingerprint (SHA-256 over {audit.corpus_files} file hashes): `{audit.corpus_sha256}`",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


class _Console:
    def __init__(self, out: TextIO, *, color: bool, pace: bool, width: int) -> None:
        self.out = out
        self.color = color
        self.pace = pace
        self.width = width
        encoding = getattr(out, "encoding", None) or "utf-8"
        try:
            "".join(_UNICODE_GLYPHS.values()).encode(encoding)
            self.glyphs = _UNICODE_GLYPHS
        except (UnicodeEncodeError, LookupError):
            self.glyphs = _ASCII_GLYPHS
        self._encoding = encoding

    def paint(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        return "".join(styles) + text + RESET

    def write(self, text: str = "") -> None:
        safe = text.encode(self._encoding, errors="replace").decode(self._encoding, errors="replace")
        self.out.write(safe + "\n")
        self.out.flush()

    def pause(self, seconds: float) -> None:
        if self.pace:
            time.sleep(seconds)

    def type_lines(self, lines: list[str], *, prefix: str = "", style: str = "") -> None:
        """Stream lines word by word on a TTY; print them whole otherwise."""

        for line in lines:
            if not self.pace:
                self.write(prefix + self.paint(line, style) if style else prefix + line)
                continue
            self.out.write(prefix)
            words = line.split(" ")
            for index, word in enumerate(words):
                chunk = word if index == 0 else " " + word
                self.out.write(self.paint(chunk, style) if style else chunk)
                self.out.flush()
                time.sleep(0.009)
            self.out.write("\n")
            self.out.flush()

    def status(self, text: str, seconds: float) -> None:
        """A transient 'reading...' line, erased before the turn prints."""

        if not self.pace:
            return
        self.out.write(self.paint(text, DIM))
        self.out.flush()
        time.sleep(seconds)
        self.out.write("\r\033[K")
        self.out.flush()


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def _terminal_width(out: TextIO) -> int:
    columns = shutil.get_terminal_size((88, 24)).columns if out is sys.stdout else 88
    return max(60, min(columns, 96)) - 2


def stream_meeting(
    meeting: OfflineMeeting,
    *,
    out: TextIO | None = None,
    color: bool | None = None,
    pace: bool | None = None,
    width: int | None = None,
) -> None:
    """Print the meeting. Defaults: color and pacing only on an interactive terminal."""

    stream = out or sys.stdout
    interactive = bool(getattr(stream, "isatty", lambda: False)())
    use_color = interactive and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    console = _Console(
        stream,
        color=use_color if color is None else color,
        pace=interactive if pace is None else pace,
        width=width or _terminal_width(stream),
    )
    _print_header(console, meeting)
    for turn in meeting.turns:
        _print_turn(console, turn)
    _print_verdict(console, meeting)


def _rule(console: _Console, label: str = "", *, heavy: bool = False) -> str:
    glyph = console.glyphs["heavy" if heavy else "rule"]
    if not label:
        return console.paint(glyph * console.width, DIM)
    head = f"{glyph * 2} {label} "
    return console.paint(head, BOLD) + console.paint(glyph * max(0, console.width - len(head)), DIM)


_LABEL_WIDTH = 11


def _field(console: _Console, label: str, value: str | list[str], *, style: str = "") -> None:
    """A labelled block; a list value prints one item per line instead of reflowing."""

    indent = _LABEL_WIDTH + 2
    items = value if isinstance(value, list) else [value]
    lines = [line for item in items for line in _wrap(item, console.width - indent)]
    for index, line in enumerate(lines):
        head = console.paint(label.ljust(_LABEL_WIDTH), DIM) if index == 0 else " " * _LABEL_WIDTH
        console.write("  " + head + (console.paint(line, style) if style else line))


def _print_header(console: _Console, meeting: OfflineMeeting) -> None:
    g = console.glyphs
    console.write()
    console.write(_rule(console, "OFFLINE RESEARCH MEETING", heavy=True))
    console.write(
        "  " + console.paint(f"no model {g['sep']} 4 agents {g['sep']} every quote verified against your library", DIM)
    )
    console.write()
    _field(console, "Question", meeting.question, style=BOLD)
    _field(
        console,
        "Library",
        f"{display_path(meeting.corpus_root)} {g['sep']} {meeting.corpus_files} papers {g['sep']} "
        f"{meeting.quotable_passages} quotable passages",
    )
    level = _GROUNDING_METER.get(meeting.grounding, 0)
    meter = g["meter_on"] * level + g["meter_off"] * (3 - level)
    matched = len(meeting.matched_terms)
    total = matched + len(meeting.missing_terms)
    tone = {GROUNDING_STRONG: GREEN, GROUNDING_PARTIAL: YELLOW}.get(meeting.grounding, RED)
    console.write(
        "  "
        + console.paint("Grounding".ljust(_LABEL_WIDTH), DIM)
        + console.paint(f"{meter} {meeting.grounding}", tone)
        + console.paint(f"  {matched} of {total} question terms covered by the evidence", DIM)
    )
    console.write(_rule(console))
    console.pause(0.4)


def _print_turn(console: _Console, turn: Turn) -> None:
    g = console.glyphs
    agent_color = AGENT_COLORS.get(turn.speaker, "")
    console.write()
    sources = sorted({quote.title for quote in turn.quotes})
    if sources:
        console.status(f"  {turn.speaker} is reading {', '.join(sources)}...", 0.45)
    else:
        console.status(f"  {turn.speaker} is thinking...", 0.3)
    tag = f"[{turn.move}]"
    name = f"{g['dot']} {turn.speaker}"
    role = f"  {turn.role}"
    gap = max(1, console.width - len(name) - len(role) - len(tag) - 2)
    console.write(
        "  " + console.paint(name, BOLD, agent_color) + console.paint(role, DIM) + " " * gap + console.paint(tag, DIM)
    )
    body_width = console.width - 4
    console.type_lines(_wrap(turn.lead, body_width), prefix="    ")
    for quote in turn.quotes:
        console.pause(0.15)
        _print_quote(console, quote, agent_color)
    if turn.coda:
        if turn.quotes:
            console.write()
        console.type_lines(_wrap(turn.coda, body_width), prefix="    ")
    console.pause(0.25)


def _print_quote(console: _Console, quote: Passage, agent_color: str) -> None:
    g = console.glyphs
    console.write()
    bar = console.paint(g["bar"], agent_color)
    for line in _wrap(f"“{quote.text}”", console.width - 8):
        console.write(f"    {bar} {line}")
        console.pause(0.03)
    citation = console.paint(f"{g['dash']} {quote.citation}", DIM)
    console.write(f"    {bar} {citation}  {console.paint(g['check'] + ' verbatim', GREEN)}")


def _print_verdict(console: _Console, meeting: OfflineMeeting) -> None:
    g = console.glyphs
    verdict = meeting.verdict
    console.write()
    console.write(_rule(console, "VERDICT", heavy=True))
    _field(console, "Agreed", verdict.agreed)
    _field(console, "Contested", verdict.contested)
    _field(console, "Next move", verdict.next_move, style=BOLD)
    if verdict.read_next:
        _field(console, "Read next", list(verdict.read_next))
    if meeting.suggestions:
        console.write()
        console.write("  " + console.paint("Questions this library can answer:", BOLD))
        for question in meeting.suggestions:
            console.write("    " + console.paint(f'python rain_lab.py --mode demo --topic "{question}"', DIM))

    audit = meeting.audit
    console.write()
    console.write(_rule(console, "CITATION AUDIT"))
    if audit.checked:
        mark, tone = (g["check"], GREEN) if audit.passed else (g["cross"], RED)
        summary = f"{mark} {audit.verified}/{audit.checked} quotes re-verified verbatim"
        console.write(
            "  "
            + console.paint(summary, tone, BOLD)
            + console.paint(
                f" against {display_path(meeting.corpus_root)} {g['sep']} corpus sha256 {audit.corpus_sha256[:12]}",
                DIM,
            )
        )
    else:
        console.write("  " + console.paint("No quotes used, so nothing to verify.", DIM))
    for line in _wrap(_honesty_note(meeting), console.width - 2):
        console.write("  " + console.paint(line, DIM))
    console.write(_rule(console))
