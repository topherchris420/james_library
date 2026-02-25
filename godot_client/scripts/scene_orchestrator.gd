extends Node2D

const DEFAULT_PARTICIPANTS: Array[String] = ["james", "jasmine", "elena", "luca"]

@export var initial_theme_id: String = "flower_field"
@export var theme_hotkeys_enabled: bool = true
@export var fallback_participants: Array[String] = DEFAULT_PARTICIPANTS

@onready var _background_layer: BackgroundPainter = $BackgroundLayer
@onready var _character_layer: Node2D = $CharacterLayer
@onready var _dialogue_ui: DialogueUI = $UILayer/DialoguePanel
@onready var _theme_badge: Label = $UILayer/ThemeBadge
@onready var _theme_manager: ThemeManager = $Managers/ThemeManager
@onready var _event_client: EventClient = $Managers/EventClient
@onready var _audio_sync: AudioSync = $Managers/AudioSync

var _participants: Array[String] = []
var _avatars: Dictionary = {}
var _active_speaker_id: String = ""


func _ready() -> void:
	_theme_manager.theme_applied.connect(_on_theme_applied)
	_event_client.event_received.connect(_on_event_received)
	_audio_sync.utterance_started.connect(_on_utterance_started)
	_audio_sync.utterance_finished.connect(_on_utterance_finished)

	if not _theme_manager.apply_theme(initial_theme_id):
		push_warning("Initial theme could not be loaded: %s" % initial_theme_id)

	_spawn_participants(fallback_participants)
	_dialogue_ui.show_status("Waiting for conversation events...")


func _unhandled_input(event: InputEvent) -> void:
	if not theme_hotkeys_enabled:
		return
	if event is InputEventKey:
		var key_event := event as InputEventKey
		if not key_event.pressed or key_event.echo:
			return
		if key_event.keycode == KEY_1:
			_theme_manager.apply_theme("flower_field")
		elif key_event.keycode == KEY_2:
			_theme_manager.apply_theme("lab")


func _on_theme_applied(theme_id: String, theme_cfg: Dictionary) -> void:
	var background_cfg := _to_dict(theme_cfg.get("background", {}))
	var ui_cfg := _to_dict(theme_cfg.get("ui", {}))
	var audio_cfg := _to_dict(theme_cfg.get("audio", {}))

	_background_layer.apply_theme(theme_id, background_cfg)
	_dialogue_ui.apply_theme(ui_cfg, theme_id)
	_audio_sync.apply_theme_audio(audio_cfg)
	_theme_badge.text = "Theme: %s (1=flower_field, 2=lab)" % theme_id

	_apply_theme_to_avatars()

	if _participants.is_empty():
		var theme_default := _theme_manager.get_default_participants()
		if not theme_default.is_empty():
			_spawn_participants(theme_default)


func _on_event_received(event_payload: Dictionary) -> void:
	var event_type := str(event_payload.get("type", ""))
	match event_type:
		"conversation_started":
			_handle_conversation_started(event_payload)
		"agent_utterance":
			_handle_agent_utterance(event_payload)
		"agent_utterance_chunk":
			_handle_agent_chunk(event_payload)
		"theme_changed":
			_handle_theme_changed(event_payload)
		"conversation_ended":
			_handle_conversation_ended()
		_:
			push_warning("Unhandled event type: %s" % event_type)


func _handle_conversation_started(event_payload: Dictionary) -> void:
	var participants := _parse_participants(event_payload.get("participants", []))
	if participants.is_empty():
		participants = fallback_participants.duplicate()
	_spawn_participants(participants)
	_dialogue_ui.show_status("Conversation started.")


func _handle_agent_utterance(event_payload: Dictionary) -> void:
	var speaker_id := _normalize_agent_id(str(event_payload.get("agent_id", "")))
	if speaker_id == "":
		return

	if not _avatars.has(speaker_id):
		var expanded := _participants.duplicate()
		expanded.append(speaker_id)
		_spawn_participants(expanded)

	var speaker_name := _display_name_from_event(event_payload, speaker_id)
	var text := str(event_payload.get("text", "")).strip_edges()
	if text == "":
		return

	var tone := str(event_payload.get("tone", "neutral")).to_lower()
	var avatar_variant: Variant = _avatars.get(speaker_id, null)
	if avatar_variant is AgentAvatar:
		var avatar := avatar_variant as AgentAvatar
		avatar.set_tone(tone)

	_set_active_speaker(speaker_id)
	_dialogue_ui.show_line(speaker_name, text)
	_audio_sync.play_utterance(speaker_id, _to_dict(event_payload.get("audio", {})), text)


func _handle_agent_chunk(event_payload: Dictionary) -> void:
	var chunk := str(event_payload.get("text", ""))
	_dialogue_ui.append_chunk(chunk)


func _handle_theme_changed(event_payload: Dictionary) -> void:
	var requested_theme := str(event_payload.get("theme_id", "")).strip_edges()
	if requested_theme != "":
		_theme_manager.apply_theme(requested_theme)


func _handle_conversation_ended() -> void:
	_audio_sync.stop_current_utterance(true)
	_set_active_speaker("")
	_dialogue_ui.show_status("Conversation ended.")


func _on_utterance_started(agent_id: String) -> void:
	for key in _avatars.keys():
		var avatar_variant: Variant = _avatars[key]
		if avatar_variant is AgentAvatar:
			var avatar := avatar_variant as AgentAvatar
			avatar.set_talking(str(key) == agent_id)


func _on_utterance_finished(agent_id: String) -> void:
	if _avatars.has(agent_id):
		var avatar_variant: Variant = _avatars[agent_id]
		if avatar_variant is AgentAvatar:
			var avatar := avatar_variant as AgentAvatar
			avatar.set_talking(false)


func _spawn_participants(agent_ids: Array[String]) -> void:
	var deduped: Array[String] = []
	for raw_id in agent_ids:
		var clean_id := _normalize_agent_id(raw_id)
		if clean_id != "" and not deduped.has(clean_id):
			deduped.append(clean_id)

	for child in _character_layer.get_children():
		child.queue_free()

	_avatars.clear()
	_participants = deduped

	if _participants.is_empty():
		return

	var count := _participants.size()
	var left_x := 130.0
	var right_x := 1150.0
	var base_y := 378.0

	for i in count:
		var agent_id := _participants[i]
		var t := 0.5 if count == 1 else float(i) / float(count - 1)
		var x := lerpf(left_x, right_x, t)
		var y := base_y + absf(t - 0.5) * 92.0

		var avatar := AgentAvatar.new()
		_character_layer.add_child(avatar)
		avatar.configure(agent_id, _title_case(agent_id), _theme_manager.get_agent_style(agent_id))
		avatar.position = Vector2(x, y)
		_avatars[agent_id] = avatar

	_set_active_speaker("")


func _apply_theme_to_avatars() -> void:
	for key in _avatars.keys():
		var avatar_variant: Variant = _avatars[key]
		if avatar_variant is AgentAvatar:
			var avatar := avatar_variant as AgentAvatar
			avatar.apply_style(_theme_manager.get_agent_style(str(key)))


func _set_active_speaker(agent_id: String) -> void:
	_active_speaker_id = agent_id
	for key in _avatars.keys():
		var avatar_variant: Variant = _avatars[key]
		if avatar_variant is AgentAvatar:
			var avatar := avatar_variant as AgentAvatar
			avatar.set_active(str(key) == agent_id)


func _parse_participants(raw: Variant) -> Array[String]:
	var result: Array[String] = []
	if raw is Array:
		for item in raw:
			if item is String:
				var as_id := _normalize_agent_id(item)
				if as_id != "" and not result.has(as_id):
					result.append(as_id)
			elif item is Dictionary:
				var d: Dictionary = item
				var from_dict := _normalize_agent_id(str(d.get("agent_id", d.get("id", ""))))
				if from_dict != "" and not result.has(from_dict):
					result.append(from_dict)
	return result


func _display_name_from_event(event_payload: Dictionary, fallback_id: String) -> String:
	var preferred := str(event_payload.get("agent_name", event_payload.get("display_name", ""))).strip_edges()
	if preferred != "":
		return preferred
	return _title_case(fallback_id)


func _normalize_agent_id(value: String) -> String:
	return value.strip_edges().to_lower()


func _title_case(value: String) -> String:
	var cleaned := value.replace("_", " ").strip_edges()
	if cleaned == "":
		return "Agent"
	var pieces := cleaned.split(" ", false)
	var out: Array[String] = []
	for part in pieces:
		if part.length() == 0:
			continue
		out.append(part.left(1).to_upper() + part.substr(1).to_lower())
	return " ".join(out)


func _to_dict(value: Variant) -> Dictionary:
	if value is Dictionary:
		return value
	return {}
