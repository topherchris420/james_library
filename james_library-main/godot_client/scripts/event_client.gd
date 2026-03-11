extends Node
class_name EventClient

signal event_received(event_payload: Dictionary)
signal connection_state_changed(state: String)
signal demo_progress_changed(progress: float, emitted_count: int, total_count: int)
signal demo_playback_state_changed(paused: bool)

@export var use_demo_events: bool = true
@export_file("*.json") var demo_events_path: String = "res://data/demo_events.json"
@export var backend_ws_url: String = "ws://127.0.0.1:8765"
@export var auto_subscribe_conversation_id: String = ""
@export var reconnect_enabled: bool = true
@export var reconnect_initial_delay_s: float = 0.5
@export var reconnect_max_delay_s: float = 8.0
@export var reconnect_jitter_s: float = 0.2
@export var ping_interval_s: float = 15.0
@export var ping_timeout_s: float = 8.0
@export var demo_loop: bool = false

var _socket: WebSocketPeer = WebSocketPeer.new()
var _demo_events: Array = []
var _demo_index: int = 0
var _demo_wait_s: float = 0.0
var _demo_running: bool = false
var _demo_paused: bool = false
var _announced_open: bool = false
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()
var _reconnect_wait_s: float = -1.0
var _reconnect_attempts: int = 0
var _awaiting_pong: bool = false
var _pong_wait_s: float = 0.0
var _ping_elapsed_s: float = 0.0


func _ready() -> void:
	_rng.randomize()
	if use_demo_events:
		_load_demo_events()
		_demo_running = _demo_events.size() > 0
		_demo_wait_s = 0.2
		_emit_demo_progress()
		emit_signal("connection_state_changed", "demo")
	else:
		connect_backend()


func _process(delta: float) -> void:
	if use_demo_events:
		_process_demo(delta)
	else:
		_poll_websocket()
		_tick_keepalive(delta)
		_tick_reconnect(delta)


func connect_backend() -> void:
	if use_demo_events:
		return
	var state := _socket.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN or state == WebSocketPeer.STATE_CONNECTING:
		return
	if state == WebSocketPeer.STATE_CLOSING:
		return
	_socket = WebSocketPeer.new()
	var err := _socket.connect_to_url(backend_ws_url)
	if err == OK:
		_reset_ping_state()
		emit_signal("connection_state_changed", "connecting")
	else:
		emit_signal("connection_state_changed", "error")
		push_warning("WebSocket connect failed for %s (code %d)" % [backend_ws_url, err])
		_schedule_reconnect("connect_failed")


func send_subscribe(conversation_id: String) -> void:
	if _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return
	var payload := {
		"type": "subscribe",
		"conversation_id": conversation_id,
	}
	_socket.send_text(JSON.stringify(payload))


func push_external_event(event_payload: Dictionary) -> void:
	emit_signal("event_received", event_payload)


func is_demo_mode() -> bool:
	return use_demo_events


func is_demo_paused() -> bool:
	return _demo_paused


func get_demo_total_count() -> int:
	return _demo_events.size()


func get_demo_emitted_count() -> int:
	return mini(_demo_index, _demo_events.size())


func get_demo_progress() -> float:
	var total := _demo_events.size()
	if total <= 0:
		return 0.0
	return float(mini(_demo_index, total)) / float(total)


func set_demo_paused(paused: bool) -> void:
	if not use_demo_events:
		return
	_demo_paused = paused
	emit_signal("demo_playback_state_changed", _demo_paused)


func seek_demo_progress(progress: float) -> void:
	if not use_demo_events or _demo_events.is_empty():
		return
	var clamped := clampf(progress, 0.0, 1.0)
	var max_index := maxi(0, _demo_events.size() - 1)
	var target_index := mini(max_index, maxi(0, int(round(clamped * float(max_index)))))
	_replay_demo_to_index(target_index)


func _process_demo(delta: float) -> void:
	if not _demo_running:
		return
	if _demo_paused:
		return

	_demo_wait_s -= delta
	if _demo_wait_s > 0.0:
		return

	if _demo_index >= _demo_events.size():
		if demo_loop and not _demo_events.is_empty():
			_replay_demo_to_index(0)
		else:
			_demo_running = false
			emit_signal("connection_state_changed", "demo_complete")
		return

	var item: Variant = _demo_events[_demo_index]
	_demo_index += 1

	if item is Dictionary:
		var event_wrapper: Dictionary = item
		_demo_wait_s = float(event_wrapper.get("delay_s", 0.0))
		var payload: Variant = event_wrapper.get("event", {})
		if payload is Dictionary:
			emit_signal("event_received", payload)
	_emit_demo_progress()


func _poll_websocket() -> void:
	var state := _socket.get_ready_state()
	if state != WebSocketPeer.STATE_CLOSED:
		var poll_err := _socket.poll()
		if poll_err != OK:
			push_warning("WebSocket poll failed (code %d)" % poll_err)
			_handle_disconnect("poll_failed")
			return
		state = _socket.get_ready_state()

	if state == WebSocketPeer.STATE_OPEN:
		if not _announced_open:
			_announced_open = true
			_reconnect_attempts = 0
			_reconnect_wait_s = -1.0
			_reset_ping_state()
			emit_signal("connection_state_changed", "open")
			if auto_subscribe_conversation_id != "":
				send_subscribe(auto_subscribe_conversation_id)

		while _socket.get_available_packet_count() > 0:
			var packet: PackedByteArray = _socket.get_packet()
			var json_text := packet.get_string_from_utf8()
			var payload: Variant = JSON.parse_string(json_text)
			if payload is Dictionary:
				var payload_dict: Dictionary = payload
				var payload_type := str(payload_dict.get("type", "")).to_lower()
				if payload_type == "pong":
					_awaiting_pong = false
					_pong_wait_s = 0.0
				else:
					emit_signal("event_received", payload_dict)
			else:
				push_warning("Ignored non-dictionary event payload: %s" % json_text)

	elif state == WebSocketPeer.STATE_CLOSED:
		if _announced_open:
			emit_signal("connection_state_changed", "closed")
		_handle_disconnect("closed")


func _tick_keepalive(delta: float) -> void:
	if _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return

	if _awaiting_pong:
		_pong_wait_s += delta
		if _pong_wait_s >= ping_timeout_s:
			push_warning("WebSocket ping timeout after %.2fs" % _pong_wait_s)
			_handle_disconnect("ping_timeout")
			return
	else:
		_ping_elapsed_s += delta
		if _ping_elapsed_s >= ping_interval_s:
			_send_ping()


func _send_ping() -> void:
	if _socket.get_ready_state() != WebSocketPeer.STATE_OPEN:
		return
	var ping_payload := {"type": "ping"}
	_socket.send_text(JSON.stringify(ping_payload))
	_awaiting_pong = true
	_pong_wait_s = 0.0
	_ping_elapsed_s = 0.0


func _tick_reconnect(delta: float) -> void:
	if use_demo_events or not reconnect_enabled:
		return
	if _reconnect_wait_s < 0.0:
		return

	_reconnect_wait_s -= delta
	if _reconnect_wait_s <= 0.0:
		_reconnect_wait_s = -1.0
		connect_backend()


func _schedule_reconnect(reason: String) -> void:
	if use_demo_events or not reconnect_enabled:
		return
	if _reconnect_wait_s >= 0.0:
		return

	_reconnect_attempts += 1
	var exp_factor := pow(2.0, float(maxi(0, _reconnect_attempts - 1)))
	var base_delay := minf(reconnect_max_delay_s, reconnect_initial_delay_s * exp_factor)
	var jitter := _rng.randf_range(-reconnect_jitter_s, reconnect_jitter_s)
	_reconnect_wait_s = maxf(0.05, base_delay + jitter)
	emit_signal("connection_state_changed", "reconnecting")
	push_warning("WebSocket reconnect scheduled in %.2fs (%s)" % [_reconnect_wait_s, reason])


func _handle_disconnect(reason: String) -> void:
	_reset_ping_state()
	if _announced_open:
		_announced_open = false
	if _socket.get_ready_state() != WebSocketPeer.STATE_CLOSED:
		_socket.close()
	_schedule_reconnect(reason)


func _reset_ping_state() -> void:
	_awaiting_pong = false
	_pong_wait_s = 0.0
	_ping_elapsed_s = 0.0


func _replay_demo_to_index(target_index: int) -> void:
	if _demo_events.is_empty():
		return
	var clamped_target := mini(maxi(0, target_index), _demo_events.size() - 1)
	emit_signal("event_received", {"type": "conversation_reset"})
	for i in range(clamped_target + 1):
		var item: Variant = _demo_events[i]
		if item is Dictionary:
			var event_wrapper: Dictionary = item
			var payload: Variant = event_wrapper.get("event", {})
			if payload is Dictionary:
				emit_signal("event_received", payload)
	_demo_index = clamped_target + 1
	_demo_wait_s = 0.0
	_demo_running = true
	_emit_demo_progress()


func _emit_demo_progress() -> void:
	if not use_demo_events:
		return
	var total := _demo_events.size()
	if total <= 0:
		emit_signal("demo_progress_changed", 0.0, 0, 0)
		return
	var emitted_count := mini(_demo_index, total)
	var progress := float(emitted_count) / float(total)
	emit_signal("demo_progress_changed", progress, emitted_count, total)


func _load_demo_events() -> void:
	_demo_events.clear()
	if not FileAccess.file_exists(demo_events_path):
		push_warning("Demo events file missing: %s" % demo_events_path)
		return

	var raw := FileAccess.get_file_as_string(demo_events_path)
	var parsed: Variant = JSON.parse_string(raw)
	if parsed is Dictionary:
		var root: Dictionary = parsed
		if root.has("events") and root["events"] is Array:
			_demo_events = root["events"]
			return

	if parsed is Array:
		_demo_events = parsed
		return

	push_warning("Unable to parse demo events: %s" % demo_events_path)
