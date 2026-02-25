# Neutral Event Contract (Theme-Agnostic)

The backend must emit neutral conversation events with no visual asset names.
The Godot client maps these events to theme-specific visuals/audio.

## Required Event Types

- `conversation_started`
- `agent_utterance`
- `conversation_ended`

## Optional Event Types

- `agent_utterance_chunk`
- `agent_emote`
- `theme_changed`

## Example Payloads

### `conversation_started`

```json
{
  "type": "conversation_started",
  "conversation_id": "c_42",
  "participants": ["james", "jasmine", "elena", "luca"]
}
```

### `agent_utterance`

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

`audio.mode` values supported by MVP:

- `file` with local path (`.wav`, `.mp3`, `.ogg`)
- `res` with `res://` resource path
- `url` (accepted, but MVP falls back to synthetic voice unless a downloader is added)
- missing/unknown mode falls back to synthetic timing-based voice

### `agent_utterance_chunk`

```json
{
  "type": "agent_utterance_chunk",
  "turn_id": "t_1042",
  "agent_id": "james",
  "text": " ...additional streaming subtitle text"
}
```

### `theme_changed`

```json
{
  "type": "theme_changed",
  "theme_id": "lab"
}
```

### `conversation_ended`

```json
{
  "type": "conversation_ended",
  "conversation_id": "c_42"
}
```
