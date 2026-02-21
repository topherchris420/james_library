
from rain_lab import BANNER_LINES, _print_banner

print("Printing banner for visual verification:")
_print_banner()

print("\nValidating line lengths:")
lengths = [len(line) for line in BANNER_LINES]
for i, length in enumerate(lengths):
    print(f"Line {i}: Length {length}")

expected_length = 59  # 57 original + 1 space + 1 extension = 59? Wait.
# Original was 57.
# I added 1 space to the text lines.
# I added 1 char to the underline lines.
# So all should be 58?
# Let's check the code change again.
# Text lines: " ... ██╗███╗ ... " -> " ... ██╗ ███╗ ... " (Added 1 space)
# Underline 1: " ... ▓" -> " ... ▓▓" (Added 1 char)
# Underline 2: " ... ▒" -> " ... ▒▒" (Added 1 char)

if all(line_length == lengths[0] for line_length in lengths):
    print(f"\nSUCCESS: All lines are equal length ({lengths[0]}).")
else:
    print(f"\nFAILURE: Line lengths are inconsistent: {lengths}")
