extends Node
class_name EventClient

signal event_received(event_payload: Dictionary)
signal connection_state_changed(state: String)

@export var use_demo_events: bool = true
@export_file("*.json") var demo_events_path: String = "res://data/demo_events.json"
@export var backend_ws_url: String = "ws://127.0.0.1:8765"
@export var auto_subscribe_conversation_id: String = ""

var _socket: WebSocketPeer = WebSocketPeer.new()
var _demo_events: Array = []
var _demo_index: int = 0
var _demo_wait_s: float = 0.0
var _demo_running: bool = false
var _announced_open: bool = false


func _ready() -> void:
	if use_demo_events:
		_load_demo_events()
		_demo_running = _demo_events.size() > 0
		_demo_wait_s = 0.2
		emit_signal("connection_state_changed", "demo")
	else:
		connect_backend()


func _process(delta: float) -> void:
	if use_demo_events:
		_process_demo(delta)
	else:
		_poll_websocket()


func connect_backend() -> void:
	var err := _socket.connect_to_url(backend_ws_url)
	if err == OK:
		emit_signal("connection_state_changed", "connecting")
	else:
		emit_signal("connection_state_changed", "error")
		push_warning("WebSocket connect failed for %s (code %d)" % [backend_ws_url, err])


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


func _process_demo(delta: float) -> void:
	if not _demo_running:
		return

	_demo_wait_s -= delta
	if _demo_wait_s > 0.0:
		return

	if _demo_index >= _demo_events.size():
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


func _poll_websocket() -> void:
	_socket.poll()
	var state := _socket.get_ready_state()

	if state == WebSocketPeer.STATE_OPEN:
		if not _announced_open:
			_announced_open = true
			emit_signal("connection_state_changed", "open")
			if auto_subscribe_conversation_id != "":
				send_subscribe(auto_subscribe_conversation_id)

		while _socket.get_available_packet_count() > 0:
			var packet: PackedByteArray = _socket.get_packet()
			var json_text := packet.get_string_from_utf8()
			var payload: Variant = JSON.parse_string(json_text)
			if payload is Dictionary:
				emit_signal("event_received", payload)
			else:
				push_warning("Ignored non-dictionary event payload: %s" % json_text)

	elif state == WebSocketPeer.STATE_CLOSED and _announced_open:
		_announced_open = false
		emit_signal("connection_state_changed", "closed")


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
