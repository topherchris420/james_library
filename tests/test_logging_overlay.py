import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rain_lab_chat._logging import OverlayAwareStreamHandler, clear_terminal_overlay, set_terminal_overlay


def test_overlay_handler_clears_and_redraws():
    stream = io.StringIO()
    handler = OverlayAwareStreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    events: list[str] = []
    set_terminal_overlay(lambda: events.append("clear"), lambda: events.append("redraw"))
    try:
        record = logging.LogRecord("rain_lab_chat.test", logging.WARNING, __file__, 1, "overlay-safe", (), None)
        handler.emit(record)
    finally:
        clear_terminal_overlay()

    assert stream.getvalue() == "overlay-safe\n"
    assert events == ["clear", "redraw"]
