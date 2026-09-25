# Godot Retro RPG Client (MVP)

This is a presentation-only Godot 4 client for R.A.I.N. Lab conversations.
It does not change backend reasoning, prompts, turn-taking, memory, or tool behavior.

## Run

1. Open `godot_client/project.godot` in Godot 4.x.
2. Press Play.
3. The scene loads demo neutral events from `godot_client/data/demo_events.json`.
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
    tone_reader.gd
  shaders/background_gradient.gdshader
  scenes/agent_avatar.tscn
  themes/
    flower_field/theme.json
    lab/theme.json
  contracts/NEUTRAL_EVENT_CONTRACT.md
  data/demo_events.json
  tests/animation_rig_test.gd
```

## Backend Wiring

- Integration entrypoint: `godot_client/scripts/event_client.gd`
- Consume backend events by setting:
  - `use_demo_events = false`
  - `backend_ws_url = ws://...`
- Backend emitter hook: `rain_lab_meeting_chat_version.py --emit-visual-events` (starts embedded WS server on `ws://127.0.0.1:8765`)
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
- Agent avatars instantiate from `scenes/agent_avatar.tscn`; see
  [Agent Animation](#agent-animation) below.
- `BackgroundPainter` now renders sky/ground gradients with a shader
  (`shaders/background_gradient.gdshader`) and keeps decor overlays in script.
- Demo mode includes replay controls (pause/play + scrubber) for faster iteration.

## Agent Animation

Each avatar (`scripts/agent_avatar.gd`) is a procedural NES-style rig drawn in
code on a 20x28 pixel canvas and shown at 4x. Parts are separate layers (body,
head, eyes, brows, mouth, blush, accessories, secondary motion). Their textures
are baked once per theme style and then swapped or offset in whole sprite
pixels, so nothing is allocated per frame.

- **Characters:**
  - James is a spectacled octopus with swaying tentacles.
  - Jasmine is a Black woman with deep brown skin and a full natural afro. She
    wears her safety goggles as a headband, with gold hoops and fitted overalls.
  - Luca has swept hair and a scarf that sways.
  - Elena is a woman with long hair and glasses, in a fitted blazer,
    knee-length skirt and heels.
  - Other agent ids get a generic humanoid.
- **Colours:** clothing colours come from the theme's `agents` styles. Identity
  traits in `LOOKS` (Jasmine's skin tone and hair colour, lip colours) always
  apply, so a theme restyles outfits without changing who a character is.
- **Idle:** breathing bob, randomised blinks (sometimes a double blink),
  wandering gaze.
- **Listening:** eyes and a one-pixel head lean follow the active speaker.
  Listeners sometimes nod, and briefly mirror the speaker's tone (a pleased
  smile for an excited line, a worried look for a skeptical one).
- **Talking:** the mouth follows the live voice level from `AudioSync` through
  closed/small/open/wide shapes, gated by `audio.mouth_flap_threshold`. Loud
  syllables add a head bob, and gestures come every second or two (both arms
  up when excited). If no level can be measured, the mouth flaps at the
  style's `flap_speed`.
- **Tone:** `curious`, `excited`, `focused`, `skeptical`, `concerned` and
  `pleased` set brows, eyes, resting mouth, blush and head tilt. When an event
  carries no tone or `neutral`, `scripts/tone_reader.gd` guesses one from the
  text. This is presentation only.
- **Events:** staggered drop-in entrance, a turn-taking hop with squash and
  stretch, a ▼ marker and spotlight on the active speaker, and a group cheer
  on `conversation_ended`.

Lip-sync sources:

- Voice files (`audio.mode = file`) play on a dedicated `RainVoice` bus, whose
  peak meter drives the mouth. WAV (8/16-bit PCM), MP3 and OGG files are
  decoded at runtime, so paths outside the project work in Godot 4.2+.
- The synthetic voice is a retro pulse-wave babble built from a per-line
  syllable schedule. The same schedule drives the mouth, so sound and animation
  stay in step.

In demo mode each `agent_utterance` holds the next event until its
`duration_ms` has elapsed (plus `demo_turn_gap_s`), so lines are not cut off.

## Testing

A headless smoke test covers the rig bake, lip-sync, blinks, celebration hops,
tone reader, WAV loader, syllable voice and demo pacing:

```bash
godot --headless --path godot_client --import          # once, builds the class cache
godot --headless --path godot_client --script tests/animation_rig_test.gd
```

It exits non-zero on any failed check.

## Adding a Theme

1. Copy a theme folder under `godot_client/themes/`.
2. Edit `theme.json` with:
   - `background` palette/decor settings
   - `ui` panel/text/typewriter settings
   - `audio.ambient` synth settings
   - `agents` style variants keyed by `agent_id` (`body`, `accent`, `skin`, `hair`,
     `outline`, `eye`, `mouth`, `flap_speed`); avatars recolour live on theme change
3. Emit `theme_changed` with the new `theme_id`.
