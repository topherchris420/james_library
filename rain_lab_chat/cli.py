"""CLI interface and entry point for R.A.I.N. Lab meetings."""

import os
import sys
import argparse

from rain_lab_chat.config import Config, DEFAULT_LIBRARY_PATH, DEFAULT_MODEL_NAME, DEFAULT_RECURSIVE_LIBRARY_SCAN
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

        """

    )

    

    parser.add_argument(

        '--library',

        type=str,

        default=DEFAULT_LIBRARY_PATH,

        help='Path to research library folder'

    )

    

    parser.add_argument(

        '--topic',

        type=str,

        help='Research topic (if not provided, will prompt)'

    )

    parser.add_argument(

        '--model',

        type=str,

        default=DEFAULT_MODEL_NAME,

        help=f"LM Studio model name (default: {DEFAULT_MODEL_NAME})"

    )

    parser.add_argument(

        '--base-url',

        type=str,

        default=os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),

        help='LM Studio OpenAI-compatible base URL'

    )

    

    parser.add_argument(

        '--temp',

        type=float,

        default=0.4,

        help='LLM temperature (0.0-1.0, default: 0.4)'

    )

    parser.add_argument(

        '--recursive-depth',

        type=int,

        default=int(os.environ.get("RAIN_RECURSIVE_DEPTH", "1")),

        help='Internal self-reflection passes per response (default: 1)'

    )

    parser.add_argument(

        '--no-recursive-intellect',

        action='store_true',

        help='Disable recursive self-reflection refinement'

    )

    parser.add_argument(

        '--recursive-library-scan',

        action='store_true',

        help='Recursively scan nested folders in the research library'

    )

    parser.add_argument(

        '--no-recursive-library-scan',

        action='store_true',

        help='Scan only top-level files in the research library (default)'

    )

    

    parser.add_argument(

        '--max-turns',

        type=int,

        default=25,

        help='Maximum conversation turns (default: 25)'

    )

    

    parser.add_argument(

        '--max-tokens',

        type=int,

        default=200,

        help='Max tokens per response (default: 200)'

    )

    parser.add_argument(

        '--timeout',

        type=float,

        default=float(os.environ.get("RAIN_LM_TIMEOUT", "300")),

        help='LLM read timeout in seconds (default: 300)'

    )

    

    parser.add_argument(

        '--no-web',

        action='store_true',

        help='Disable DuckDuckGo web search'

    )

    

    parser.add_argument(

        '--verbose', '-v',

        action='store_true',

        help='Show detailed loading output (papers, souls, web search)'

    )

    parser.add_argument(

        '--emit-visual-events',

        action='store_true',

        help='Write neutral conversation events for Godot/WebSocket bridge clients'

    )

    parser.add_argument(

        '--no-emit-visual-events',

        action='store_true',

        help='Disable neutral visual event output even if env enables it'

    )

    parser.add_argument(

        '--visual-events-log',

        type=str,

        default=os.environ.get("RAIN_VISUAL_EVENTS_LOG", "meeting_archives/godot_events.jsonl"),

        help='Path (relative to --library or absolute) for JSONL event output'

    )

    parser.add_argument(

        '--tts-audio-dir',

        type=str,

        default=os.environ.get("RAIN_TTS_AUDIO_DIR", "meeting_archives/tts_audio"),

        help='Directory (relative to --library or absolute) for per-turn TTS audio files'

    )

    parser.add_argument(

        '--no-export-tts-audio',

        action='store_true',

        help='Disable per-turn TTS file export (keeps spoken audio behavior unchanged)'

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

    export_tts_audio = os.environ.get("RAIN_EXPORT_TTS_AUDIO", "1") != "0"
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

    )

    

    # Get topic

    if args.topic:

        topic = args.topic

    else:

        print("\n" + "="*70)

        print("R.A.I.N. LAB - RESEARCH FOCUS")

        print("="*70)

        topic = input("\n🔬 Research Topic: ").strip()

    

    if not topic:

        print("❌ No topic provided. Exiting.")

        sys.exit(1)

    

    # Run meeting

    orchestrator = RainLabOrchestrator(config)

    orchestrator.run_meeting(topic)

if __name__ == "__main__":

    main()
