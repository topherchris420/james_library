"""
R.A.I.N. Lab Rich UI Module

Terminal UI enhancements using ANSI codes (no external dependencies).
"""

# Color codes
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "underline": "\033[4m",

    # Foreground colors
    "black": "\033[30m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",

    # Bright foreground
    "bright_black": "\033[90m",
    "bright_red": "\033[91m",
    "bright_green": "\033[92m",
    "bright_yellow": "\033[93m",
    "bright_blue": "\033[94m",
    "bright_magenta": "\033[95m",
    "bright_cyan": "\033[96m",
    "bright_white": "\033[97m",

    # Background colors
    "bg_black": "\033[40m",
    "bg_red": "\033[41m",
    "bg_green": "\033[42m",
    "bg_yellow": "\033[43m",
    "bg_blue": "\033[44m",
    "bg_magenta": "\033[45m",
    "bg_cyan": "\033[46m",
    "bg_white": "\033[47m",
}

# Agent colors
AGENT_COLORS = {
    "James": "green",
    "Jasmine": "yellow",
    "Elena": "magenta",
    "Luca": "cyan",
    "Marcus": "red",
    "Dr_Sarah": "blue",
    "Nova": "white",
    "Devil": "bright_black",
    "Synth": "bright_yellow",
}


def color(text: str, color_name: str) -> str:
    """Apply color to text."""
    code = COLORS.get(color_name, "")
    return f"{code}{text}{COLORS['reset']}"


def bold(text: str) -> str:
    """Make text bold."""
    return f"{COLORS['bold']}{text}{COLORS['reset']}"


def panel(title: str, content: str, width: int = 60) -> str:
    """Create a bordered panel with title.

    Args:
        title: Panel title
        content: Panel content
        width: Panel width

    Returns:
        Formatted panel string
    """
    lines = content.split('\n')
    max_len = max(len(line_text) for line_text in lines) if lines else 0
    w = min(max(width, max_len + 4), 120)

    border = "═" * (w - 2)
    result = []
    result.append(f"╔{border}╗")
    result.append(f"║ {title.center(w - 4)} ║")
    result.append(f"╟{border}╢")

    for line in lines:
        padding = w - len(line) - 4
        result.append(f"║ {line}{' ' * max(0, padding)} ║")

    result.append(f"╚{'═' * (w - 2)}╝")
    return "\n".join(result)


def progress_bar(current: int, total: int, width: int = 40, prefix: str = "Progress") -> str:
    """Create a progress bar.

    Args:
        current: Current value
        total: Total value
        width: Bar width
        prefix: Prefix text

    Returns:
        Progress bar string
    """
    if total == 0:
        percent = 0
    else:
        percent = min(100, int(100 * current / total))

    filled = int(width * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)

    return f"{prefix}: [{bar}] {percent}%"


def table(headers: list, rows: list, align: list = None) -> str:
    """Create a simple ASCII table.

    Args:
        headers: List of column headers
        rows: List of row data (each row is a list)
        align: Optional list of alignments ('l', 'r', 'c')

    Returns:
        Formatted table string
    """
    if not rows:
        return "No data"

    # Calculate column widths
    col_count = len(headers)
    col_widths = [len(h) for h in headers]

    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    # Default alignment
    if align is None:
        align = ['l'] * col_count

    # Build table
    lines = []

    # Header
    header_cells = []
    for i, h in enumerate(headers):
        w = col_widths[i]
        if align[i] == 'r':
            header_cells.append(h.rjust(w))
        elif align[i] == 'c':
            header_cells.append(h.center(w))
        else:
            header_cells.append(h.ljust(w))

    sep = "│".join("─" * (w + 2) for w in col_widths)
    lines.append(f"┌{sep}┐")
    lines.append("│ " + " │ ".join(header_cells) + " │")
    lines.append(f"├{sep}┤")

    # Rows
    for row in rows:
        row_cells = []
        for i, cell in enumerate(row):
            if i >= col_count:
                break
            w = col_widths[i]
            cell_str = str(cell)
            if align[i] == 'r':
                row_cells.append(cell_str.rjust(w))
            elif align[i] == 'c':
                row_cells.append(cell_str.center(w))
            else:
                row_cells.append(cell_str.ljust(w))

        lines.append("│ " + " │ ".join(row_cells) + " │")

    lines.append(f"└{sep}┘")
    return "\n".join(lines)


def spinner(frame: int = 0) -> str:
    """Get next spinner frame.

    Args:
        frame: Frame number

    Returns:
        Spinner character
    """
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    return frames[frame % len(frames)]


def status_indicator(status: str) -> str:
    """Get status indicator with color.

    Args:
        status: Status string ('ok', 'warning', 'error', 'loading', 'info')

    Returns:
        Colored status string
    """
    indicators = {
        "ok": (f"{COLORS['green']}✓ OK{COLORS['reset']}", "All systems operational"),
        "warning": (f"{COLORS['yellow']}⚠ WARNING{COLORS['reset']}", "Potential issue detected"),
        "error": (f"{COLORS['red']}✗ ERROR{COLORS['reset']}", "Action required"),
        "loading": (f"{COLORS['cyan']}◐ LOADING{COLORS['reset']}", "Processing..."),
        "info": (f"{COLORS['blue']}ℹ INFO{COLORS['reset']}", "Information"),
    }

    ind = indicators.get(status.lower(), indicators["info"])
    return ind[0]


def agent_banner(name: str, role: str = None) -> str:
    """Create agent banner with color.

    Args:
        name: Agent name
        role: Optional role

    Returns:
        Formatted banner
    """
    agent_color = AGENT_COLORS.get(name, "white")
    c = COLORS.get(agent_color, "")

    banner = f"{c}{'─' * 40}{COLORS['reset']}\n"
    banner += f"{c}▶ {name}{COLORS['reset']}"
    if role:
        banner += f" {COLORS['dim']}({role}){COLORS['reset']}"
    banner += f"\n{c}{'─' * 40}{COLORS['reset']}"

    return banner


def highlight_keywords(text: str, keywords: list, color: str = "yellow") -> str:
    """Highlight keywords in text.

    Args:
        text: Input text
        keywords: Keywords to highlight
        color: Highlight color

    Returns:
        Text with highlighted keywords
    """
    result = text
    highlight_color = COLORS.get(color, "")

    for kw in keywords:
        result = result.replace(kw, f"{highlight_color}{kw}{COLORS['reset']}")

    return result


def meeting_header(topic: str, turn: int = None, max_turns: int = None) -> str:
    """Create meeting header.

    Args:
        topic: Meeting topic
        turn: Current turn number
        max_turns: Maximum turns

    Returns:
        Formatted header
    """
    lines = []
    lines.append(f"{COLORS['bold']}{COLORS['blue']}{'═' * 60}{COLORS['reset']}")
    lines.append(f"{COLORS['bold']}{COLORS['blue']}║{'R.A.I.N. LAB'.center(56)}{COLORS['reset']}{COLORS['blue']}║{COLORS['reset']}")
    lines.append(f"{COLORS['bold']}{COLORS['blue']}{'═' * 60}{COLORS['reset']}")

    if turn is not None and max_turns is not None:
        lines.append(f"{COLORS['dim']}Turn {turn}/{max_turns}{COLORS['reset']}")

    lines.append(f"{COLORS['bold']}Topic: {topic}{COLORS['reset']}")
    lines.append("")

    return "\n".join(lines)


def agreement_meter(agreement: float) -> str:
    """Create agreement meter.

    Args:
        agreement: Agreement level (0.0 to 1.0)

    Returns:
        Meter visualization
    """
    width = 20
    filled = int(width * agreement)

    if agreement < 0.3:
        color_name = "red"
    elif agreement < 0.7:
        color_name = "yellow"
    else:
        color_name = "green"

    bar = COLORS.get(color_name, "") + "█" * filled + COLORS["reset"] + "░" * (width - filled)
    return f"Agreement: [{bar}] {int(agreement * 100)}%"


# Pretty print functions
def print_agent(name: str, role: str, message: str):
    """Print agent message with formatting."""
    agent_color = AGENT_COLORS.get(name, "white")
    c = COLORS.get(agent_color, "")

    print(f"\n{c}▶ {name}{COLORS['reset']}")
    if role:
        print(f"  {COLORS['dim']}({role}){COLORS['reset']}")
    print(f"  {message}\n")


def print_panel(title: str, content: str):
    """Print content in a panel."""
    print(panel(title, content))


def print_table(headers: list, rows: list, align: list = None):
    """Print a table."""
    print(table(headers, rows, align))


def print_progress(current: int, total: int, prefix: str = "Progress"):
    """Print progress bar."""
    print(f"\r{progress_bar(current, total, prefix=prefix)}", end="", flush=True)
    if current >= total:
        print()  # New line when complete
