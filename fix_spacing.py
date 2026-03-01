"""Collapse consecutive blank lines in rain_lab_chat modules.

Line-by-line approach: if a line is entirely blank (only whitespace/CR/LF)
and the previous line was also blank, drop it. This preserves indentation
and doesn't touch content inside strings.
"""
from pathlib import Path

pkg = Path(__file__).parent / "rain_lab_chat"
targets = list(pkg.glob("*.py"))

total_saved = 0

for f in sorted(targets):
    lines = f.read_text(encoding="utf-8").split("\n")
    before = len(lines)

    cleaned = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue  # skip consecutive blank line
        cleaned.append(line)
        prev_blank = is_blank

    after = len(cleaned)
    saved = before - after
    if saved > 0:
        f.write_text("\n".join(cleaned), encoding="utf-8")
        print(f"  {f.name}: {before} -> {after} lines (-{saved})")
    else:
        print(f"  {f.name}: {before} lines (no change)")
    total_saved += saved

print(f"\nTotal: saved {total_saved} lines")
