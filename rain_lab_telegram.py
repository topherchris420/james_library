"""Telegram gateway for R.A.I.N. Lab.

This module adds a phone-friendly interface on top of the existing async
``run_rain_lab`` entry point. It intentionally does not change existing CLI
behavior in ``rain_lab.py``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from rain_lab import run_rain_lab


# Telegram hard limit is 4096 characters. Keep a little safety margin.
TELEGRAM_MESSAGE_LIMIT = 3900
MAX_TEXT_MESSAGES_BEFORE_FILE = 3
AGENT_PREFIX_RE = re.compile(r"^\s*@(?P<agent>james|elena|jasmine|luca)\b\s*[:\-]?\s*", re.IGNORECASE)


@dataclass(slots=True)
class RouteDecision:
    """Normalized routing information for an incoming user message."""

    mode: str
    query: str
    agent: Optional[str] = None


def _normalize_agent_name(agent: str) -> str:
    """Convert user-facing tags into canonical agent names."""
    canonical = agent.strip().lower()
    mapping = {
        "james": "James",
        "elena": "Elena",
        "jasmine": "Jasmine",
        "luca": "Luca",
    }
    return mapping.get(canonical, "James")


def _route_message(text: str) -> RouteDecision:
    """Route user text to chat/meeting mode and optional agent override."""
    cleaned = text.strip()

    # Meeting routing is keyword based per requirement.
    if "/meeting" in cleaned.lower() or "meeting" in cleaned.lower():
        query = cleaned.replace("/meeting", "").strip() or "Open research discussion"
        return RouteDecision(mode="rlm", query=query)

    # Agent mention routing (chat mode).
    match = AGENT_PREFIX_RE.match(cleaned)
    if match:
        agent = _normalize_agent_name(match.group("agent"))
        query = cleaned[match.end() :].strip() or "Continue"
        return RouteDecision(mode="chat", query=query, agent=agent)

    # Default behavior: normal chat to James.
    return RouteDecision(mode="chat", query=cleaned, agent="James")


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split long text at natural boundaries while respecting Telegram limits."""
    normalized = text.strip()
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    remaining = normalized

    while len(remaining) > limit:
        # Prefer newline boundaries first, then sentence boundary, then hard cut.
        cut = remaining.rfind("\n", 0, limit)
        if cut < int(limit * 0.5):
            cut = remaining.rfind(". ", 0, limit)
        if cut < int(limit * 0.5):
            cut = limit

        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def _send_long_response(update: Update, response_text: str) -> None:
    """Send response as one or many messages, with optional .txt fallback."""
    chunks = _split_message(response_text)

    if len(chunks) > MAX_TEXT_MESSAGES_BEFORE_FILE:
        # Bonus behavior: send as a .txt if text would be too spammy.
        payload = io.BytesIO(response_text.encode("utf-8"))
        payload.name = "rain_lab_response.txt"
        await update.message.reply_document(
            document=payload,
            caption="Response is long, so I attached it as a text file.",
        )
        return

    for index, chunk in enumerate(chunks):
        if index < len(chunks) - 1:
            await update.message.reply_text(f"{chunk}\n\n_Continued in next message…_", parse_mode="Markdown")
        else:
            await update.message.reply_text(chunk)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start with a concise onboarding message."""
    del context
    message = (
        "🧠 *Welcome to R.A.I.N. Lab Telegram Gateway*\n\n"
        "I can route your prompt to the team:\n"
        "• *James* (default): systems + synthesis\n"
        "• *Elena*: engineering + implementation rigor\n"
        "• *Jasmine*: theory + conceptual depth\n"
        "• *Luca*: critical analysis + edge cases\n\n"
        "Usage:\n"
        "• Send normal text → James in chat mode\n"
        "• `@Elena design a robust test harness` → direct agent chat\n"
        "• `/meeting Quantum resonance` or any message containing `meeting` → full multi-agent mode\n"
        "• `/help` for more examples"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help with command examples."""
    del context
    message = (
        "📘 *Commands & Examples*\n\n"
        "• Normal chat:\n"
        "  `Summarize today's strongest hypothesis`\n\n"
        "• Agent routing:\n"
        "  `@James pressure-test this idea`\n"
        "  `@Elena propose an implementation plan`\n"
        "  `@Jasmine derive a conceptual model`\n"
        "  `@Luca find flaws in this argument`\n\n"
        "• Meeting mode:\n"
        "  `/meeting Evaluate recursive self-critique`\n"
        "  `Run a meeting on robust local RAG pipelines`"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main message handler: route text and call the async R.A.I.N. entrypoint."""
    del context
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    route = _route_message(user_text)

    logging.info(
        "Incoming message chat_id=%s mode=%s agent=%s query_preview=%s",
        update.effective_chat.id if update.effective_chat else "unknown",
        route.mode,
        route.agent,
        route.query[:120],
    )

    await update.message.chat.send_action(action=ChatAction.TYPING)

    try:
        response = await run_rain_lab(
            query=route.query,
            mode=route.mode,
            agent=route.agent,
            recursive_depth=1,
        )
        response = response.strip() or "(No response returned.)"
        await _send_long_response(update, response)
    except Exception:
        logging.exception("run_rain_lab failed")
        await update.message.reply_text(
            "Sorry — R.A.I.N. Lab hit an internal error while processing that request. "
            "Please try again in a moment."
        )


async def main() -> None:
    """Entrypoint for starting Telegram long polling in local/dev workflows."""
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN. Add it to your environment or .env file.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Starting R.A.I.N. Lab Telegram gateway (polling mode)")

    # run_polling() is blocking. Wrap it in a worker thread so main() remains async,
    # which keeps this module compatible with asyncio.run(main()).
    await asyncio.to_thread(application.run_polling, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())
