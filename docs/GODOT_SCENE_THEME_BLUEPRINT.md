# Godot Scene Theme Blueprint for Multi-Agent Conversations

This blueprint adds a Godot 4 visual layer to R.A.I.N. Lab while keeping backend
conversation behavior intact.

## Goal

- Keep prompts, turn-taking, memory, tools, and model reasoning unchanged.
- Render participating agents together in one 2D scene.
- Map neutral conversation events to theme-specific visuals and audio.
- Swap themes without changing conversation content.

## Architecture

```text
Backend conversation engine (existing)
  -> neutral events (JSON over WebSocket)
  -> Godot SceneOrchestrator
      -> ThemeManager (background/ui/audio/agent variants)
      -> DialogueUI (speaker + captions + typewriter)
      -> AgentAvatar nodes (idle/talking states)
      -> AudioSync (utterance audio + talk loop sync)
```

## Node Tree (MVP)

```text
ConversationRoot (Node2D)
├── BackgroundLayer (Node2D, script: background_painter.gd)
├── CharacterLayer (Node2D, dynamic AgentAvatar nodes)
├── UILayer (CanvasLayer)
│   ├── DialoguePanel (PanelContainer, script: dialogue_ui.gd)
│   └── ThemeBadge (Label)
└── Managers (Node)
    ├── ThemeManager (theme_manager.gd)
    ├── EventClient (event_client.gd)
    └── AudioSync (audio_sync.gd)
```

## Neutral Event Contract

Required event types:

- `conversation_started`
- `agent_utterance`
- `conversation_ended`

Optional event types:

- `agent_utterance_chunk`
- `agent_emote`
- `theme_changed`

Example utterance event:

```json
{
  "type": "agent_utterance",
  "turn_id": "t_1042",
  "agent_id": "james",
  "text": "We should test that hypothesis.",
  "tone": "curious",
  "audio": {
    "mode": "file",
    "path": "C:/tmp/rain_lab_tts_t_1042.mp3",
    "duration_ms": 2430
  }
}
```

Rule:

- Backend never references visual assets (`flower_field_bg.png`, etc.).
- Theme-specific assets/settings live in Godot theme files only.

## Theme Pack Schema

Each theme lives in `godot_client/themes/<theme_id>/theme.json`.

Shared keys:

- `id`, `display_name`
- `participants` (default visible cast)
- `background`
- `ui`
- `audio` (ambient + sync settings)
- `agents` (style variants keyed by `agent_id`)

Included themes:

- `flower_field`
- `lab`

## Runtime Flow

1. `conversation_started`: spawn visible cast in `CharacterLayer`.
2. `agent_utterance`: update subtitle panel, set active speaker, start audio/talking.
3. `agent_utterance_chunk` (optional): append to subtitle in place.
4. `theme_changed` (optional): apply theme config live.
5. `conversation_ended`: stop talking/audio, keep scene visible.

Bridge option in this repo:

- Backend writes JSONL events to `meeting_archives/godot_events.jsonl`.
- `godot_event_bridge.py` tails that file and relays events over WebSocket.

## Audio/Animation Sync (MVP)

- If `audio.mode=file/res`: play provided stream.
- If unavailable: synthetic fallback voice timing.
- While active audio is playing:
  - active speaker uses talking loop (mouth flap),
  - non-speakers stay visible in idle state.
- On completion: speaker returns to idle.

## Separation of Concerns

Backend responsibilities:

- Orchestrate turns and reasoning.
- Emit neutral conversation events.
- Provide text and optional TTS file path/URL.

Godot responsibilities:

- Theme application.
- Character placement and animation state.
- Subtitle/typewriter rendering.
- Per-theme ambient and UI styling.

## Validation Checklist

- Switching `flower_field` and `lab` does not change transcript text.
- All speakers remain visible during dialogue.
- Captions overlay at bottom while scene remains visible.
- Speaker animation transitions idle -> talking -> idle in sync.
- Backend event shape stays theme-agnostic.
