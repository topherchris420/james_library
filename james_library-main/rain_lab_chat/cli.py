"""CLI interface and entry point for R.A.I.N. Lab meetings."""

import argparse
import os
import sys

from rain_lab_chat.config import DEFAULT_LIBRARY_PATH, DEFAULT_MODEL_NAME, DEFAULT_RECURSIVE_LIBRARY_SCAN, Config
from rain_lab_chat.logging_events import parse_log_for_resume
from rain_lab_chat.orchestrator import RainLabOrchestrator


def parse_args():
    """Parse command line arguments"""

    parser = argparse.ArgumentParser(
        description="R.A.I.N. LAB - Research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""

Examples:

  python rain_lab_v31_production.py --topic "quantum resonance"

  python rain_lab_v31_production.py --library ./my_papers --topic "field theory"

  python rain_lab_v31_production.py --temp 0.3 --topic "entanglement"

        """,
    )

    parser.add_argument("--library", type=str, default=DEFAULT_LIBRARY_PATH, help="Path to research library folder")

    parser.add_argument("--topic", type=str, help="Research topic (if not provided, will prompt)")

    parser.add_argument(
        "--model", type=str, default=DEFAULT_MODEL_NAME, help=f"LM Studio model name (default: {DEFAULT_MODEL_NAME})"
    )

    parser.add_argument(
        "--base-url",
        type=str,
        default=os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
        help="LM Studio OpenAI-compatible base URL",
    )

    parser.add_argument("--temp", type=float, default=0.4, help="LLM temperature (0.0-1.0, default: 0.4)")

    parser.add_argument(
        "--recursive-depth",
        type=int,
        default=int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1")),
        help="Internal self-reflection passes per response (default: 1)",
    )

    parser.add_argument(
        "--no-recursive-intellect", action="store_true", help="Disable recursive self-reflection refinement"
    )

    parser.add_argument(
        "--recursive-library-scan", action="store_true", help="Recursively scan nested folders in the research library"
    )

    parser.add_argument(
        "--no-recursive-library-scan",
        action="store_true",
        help="Scan only top-level files in the research library (default)",
    )

    parser.add_argument("--max-turns", type=int, default=25, help="Maximum conversation turns (default: 25)")

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("RAIN_MAX_TOKENS", "500")),
        help="Max tokens per response (default: 500)",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("RAIN_LM_TIMEOUT", "180")),
        help="LLM read timeout in seconds (default: 180)",
    )

    parser.add_argument("--no-web", action="store_true", help="Disable DuckDuckGo web search")

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed loading output (papers, souls, web search)"
    )

    parser.add_argument(
        "--emit-visual-events",
        action="store_true",
        help="Write neutral conversation events for Godot/WebSocket bridge clients",
    )

    parser.add_argument(
        "--no-emit-visual-events",
        action="store_true",
        help="Disable neutral visual event output even if env enables it",
    )

    parser.add_argument(
        "--visual-events-log",
        type=str,
        default=os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl"),
        help="Path (relative to --library or absolute) for JSONL event output",
    )

    parser.add_argument(
        "--tts-audio-dir",
        type=str,
        default=os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio"),
        help="Directory (relative to --library or absolute) for per-turn TTS audio files",
    )

    parser.add_argument(
        "--no-export-tts-audio",
        action="store_true",
        help="Disable per-turn TTS file export (keeps spoken audio behavior unchanged)",
    )

    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default=os.environ.get("RAIN_SESSION_CHECKPOINT", "meeting_archives/latest_session_checkpoint.json"),
        help="Path (relative to --library or absolute) for structured JSON session checkpoints",
    )

    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        metavar="LOG_PATH",
        help="Resume a previous meeting from a JSON checkpoint or markdown meeting log",
    )

    args, unknown = parser.parse_known_args()

    if unknown:
        print(f"⚠️ Ignoring unrecognized args: {' '.join(unknown)}")

    return args


# --- ENTRY POINT ---


def main():
    """Main entry point"""

    args = parse_args()

    recursive_library_scan = DEFAULT_RECURSIVE_LIBRARY_SCAN

    if args.recursive_library_scan:
        recursive_library_scan = True

    if args.no_recursive_library_scan:
        recursive_library_scan = False

    emit_visual_events = os.environ.get("RAIN_VISUAL_EVENTS", "0") == "1"
    if args.emit_visual_events:
        emit_visual_events = True
    if args.no_emit_visual_events:
        emit_visual_events = False

    raw_export_tts = os.environ.get("RAIN_EXPORT_TTS_AUDIO")
    if raw_export_tts is None:
        # Default to exporting audio only when visual events are enabled.
        export_tts_audio = emit_visual_events
    else:
        export_tts_audio = raw_export_tts != "0"
    if args.no_export_tts_audio:
        export_tts_audio = False

    # Create config from args

    config = Config(
        library_path=args.library,
        temperature=args.temp,
        max_turns=args.max_turns,
        max_tokens=args.max_tokens,
        enable_web_search=not args.no_web,
        verbose=args.verbose,
        model_name=args.model,
        base_url=args.base_url,
        timeout=max(30.0, args.timeout),
        recursive_depth=max(1, args.recursive_depth),
        recursive_intellect=not args.no_recursive_intellect,
        recursive_library_scan=recursive_library_scan,
        emit_visual_events=emit_visual_events,
        visual_events_log=args.visual_events_log,
        export_tts_audio=export_tts_audio,
        tts_audio_dir=args.tts_audio_dir,
        checkpoint_path=args.checkpoint_path,
    )

    # Handle resume mode

    prior_history = None
    resume_state = None
    if args.resume:
        resume_path = args.resume
        if not os.path.isabs(resume_path):
            library_relative = os.path.join(args.library, resume_path)
            if os.path.exists(library_relative):
                resume_path = library_relative
        resume_data = parse_log_for_resume(resume_path)
        if not resume_data or not resume_data.get("topic"):
            print(f"❌ Could not parse log for resume: {args.resume}")
            sys.exit(1)
        topic = resume_data["topic"]
        prior_history = resume_data["history"]
        resume_state = resume_data
        print(f"🔄 Resuming topic: {topic}  ({len(prior_history)} prior turns loaded)")
    else:
        # Get topic

        if args.topic:
            topic = args.topic

        else:
            print("\n" + "=" * 70)

            print("R.A.I.N. LAB - RESEARCH FOCUS")

            print("=" * 70)

            topic = input("\n🔬 Research Topic: ").strip()

        if not topic:
            topic = "Open research discussion"
            print(f"💡 No topic specified — defaulting to: {topic}")

    # Run meeting

    orchestrator = RainLabOrchestrator(config)

    orchestrator.run_meeting(topic, prior_history=prior_history, resume_state=resume_state)


if __name__ == "__main__":
    main()
