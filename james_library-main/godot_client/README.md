# Godot Retro RPG Client (MVP)

This is a presentation-only Godot 4 client for R.A.I.N. Lab conversations.
It does not change backend reasoning, prompts, turn-taking, memory, or tool behavior.

## Run

### Live Mode (default)

1. Launch the full stack: `python rain_lab.py --mode godot --topic "your topic"`
2. The launcher starts the bridge + Godot client automatically.
3. Avatars appear as agents speak.

### Demo Mode

1. Open `godot_client/project.godot` in Godot 4.x.
2. Select the `EventClient` node → set `use_demo_events = true` in Inspector.
3. Press Play.
4. Press `1` for `flower_field` and `2` for `lab`.

## Structure

```text
godot_client/
  scenes/conversation_root.tscn
  scenes/agent_avatar.tscn
  scripts/
    scene_orchestrator.gd
    theme_manager.gd
    event_client.gd
    audio_sync.gd
    dialogue_ui.gd
    background_painter.gd
    agent_avatar.gd
  shaders/background_gradient.gdshader
  scenes/agent_avatar.tscn
  themes/
    flower_field/theme.json
    lab/theme.json
  contracts/NEUTRAL_EVENT_CONTRACT.md
  data/demo_events.json
```

## Backend Wiring

- Integration entrypoint: `godot_client/scripts/event_client.gd`
- Default: live WebSocket mode, connects to `ws://127.0.0.1:8765`
- Demo mode: set `use_demo_events = true` in the EventClient Inspector
- Bridge helper (in repo root): `python godot_event_bridge.py --events-file meeting_archives/godot_events.jsonl`
- Backend emitter hook: `rain_lab_meeting_chat_version.py --emit-visual-events`
- Per-turn audio files in payload: enable `--tts-audio-dir` (default `meeting_archives/tts_audio`)
- The orchestrator listens for:
  - `conversation_started`
  - `agent_utterance`
  - `agent_utterance_chunk`
  - `theme_changed`
  - `conversation_ended`

## Runtime Tuning

- `EventClient` now supports reconnect and keepalive controls:
  - `reconnect_enabled`
  - `reconnect_initial_delay_s`
  - `reconnect_max_delay_s`
  - `reconnect_jitter_s`
  - `ping_interval_s`
  - `ping_timeout_s`
- `AudioSync` now uses `audio.ducking_db` in theme configs with smooth attack/release
  so ambient audio ducks under active speech.
- Agent avatars now instantiate from `scenes/agent_avatar.tscn` and use
  `AnimationPlayer`-driven idle/talk/pulse animation.
- `BackgroundPainter` now renders sky/ground gradients with a shader
  (`shaders/background_gradient.gdshader`) and keeps decor overlays in script.
- Demo mode includes replay controls (pause/play + scrubber) for faster iteration.

## Adding a Theme

1. Copy a theme folder under `godot_client/themes/`.
2. Edit `theme.json` with:
   - `background` palette/decor settings
   - `ui` panel/text/typewriter settings
   - `audio.ambient` synth settings
   - `agents` style variants keyed by `agent_id`
3. Emit `theme_changed` with the new `theme_id`.
