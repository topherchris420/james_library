"""Diplomat — file-based mailbox for external inter-process messages."""

from __future__ import annotations

import glob
import os
import shutil
from typing import Optional

from .sanitize import sanitize_text


class Diplomat:
    """Simple file-based mailbox for external messages."""

    def __init__(
        self, base_path: str = ".", inbox: str = "inbox", outbox: str = "outbox", processed: str = "processed"
    ):
        self.inbox = os.path.join(base_path, inbox)
        self.outbox = os.path.join(base_path, outbox)
        self.processed = os.path.join(base_path, processed)

        os.makedirs(self.inbox, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)
        os.makedirs(self.processed, exist_ok=True)

    def check_inbox(self) -> Optional[str]:
        """Read first inbox message, archive it, and return formatted text."""

        message_files = sorted(glob.glob(os.path.join(self.inbox, "*.txt")), key=os.path.getmtime)

        if not message_files:
            return None

        message_file = message_files[0]

        try:
            with open(message_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            content = sanitize_text(content)

        except Exception as e:
            print(f"\u26a0\ufe0f  Failed to read diplomat message '{message_file}': {e}")
            return None

        archived_path = os.path.join(self.processed, os.path.basename(message_file))

        try:
            shutil.move(message_file, archived_path)
        except Exception as e:
            print(f"\u26a0\ufe0f  Failed to archive diplomat message '{message_file}': {e}")
            return None

        return f"\U0001f4e8 EXTERNAL MESSAGE: {content}"
