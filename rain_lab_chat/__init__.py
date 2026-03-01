"""rain_lab_chat — modular R.A.I.N. Lab meeting package."""

from rain_lab_chat._sanitize import sanitize_text
from rain_lab_chat.config import Config
from rain_lab_chat.agents import Agent, RainLabAgentFactory
from rain_lab_chat.context import ContextManager
from rain_lab_chat.web_search import WebSearchManager
from rain_lab_chat.citations import CitationAnalyzer
from rain_lab_chat.director import RainLabDirector
from rain_lab_chat.logging_events import LogManager, VisualEventLogger, Diplomat
from rain_lab_chat.voice import VoiceEngine
from rain_lab_chat.orchestrator import RainLabOrchestrator

__all__ = [
    "sanitize_text",
    "Config",
    "Agent", "RainLabAgentFactory",
    "ContextManager",
    "WebSearchManager",
    "CitationAnalyzer",
    "RainLabDirector",
    "LogManager", "VisualEventLogger", "Diplomat",
    "VoiceEngine",
    "RainLabOrchestrator",
]
