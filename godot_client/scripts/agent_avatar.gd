extends Node2D
class_name AgentAvatar

var agent_id: String = ""
var display_name: String = ""
var style: Dictionary = {}

var _is_talking: bool = false
var _is_active: bool = false
var _tone: String = "neutral"
var _time: float = 0.0
var _mouth_open: bool = false
var _phase_seed: float = 0.0


func configure(agent_key: String, shown_name: String, style_cfg: Dictionary) -> void:
	agent_id = agent_key
	display_name = shown_name
	_phase_seed = float(abs(hash(agent_key)) % 1000) * 0.01
	apply_style(style_cfg)


func apply_style(style_cfg: Dictionary) -> void:
	style = style_cfg.duplicate(true)
	queue_redraw()


func set_talking(value: bool) -> void:
	_is_talking = value
	if not _is_talking:
		_mouth_open = false
	queue_redraw()


func set_active(value: bool) -> void:
	_is_active = value
	queue_redraw()


func set_tone(tone: String) -> void:
	_tone = tone.strip_edges().to_lower()
	queue_redraw()


func _process(delta: float) -> void:
	_time += delta
	if _is_talking:
		var flap_speed := float(style.get("flap_speed", 10.0))
		_mouth_open = int((_time + _phase_seed) * flap_speed) % 2 == 0
	queue_redraw()


func _draw() -> void:
	var outline := _color_from(style.get("outline", "#1b2230"), "#1b2230")
	var body := _color_from(style.get("body", "#6c91d5"), "#6c91d5")
	var accent := _color_from(style.get("accent", "#405f98"), "#405f98")
	var skin := _color_from(style.get("skin", "#f2d4b3"), "#f2d4b3")
	var hair := _color_from(style.get("hair", "#2e3f5b"), "#2e3f5b")
	var eye := _color_from(style.get("eye", "#101318"), "#101318")
	var mouth := _color_from(style.get("mouth", "#5d2d2d"), "#5d2d2d")

	var bob_amp := 1.2 if _is_talking else 2.2
	var bob := sin((_time * 2.2) + _phase_seed) * bob_amp

	if _is_active:
		var pulse := 0.5 + 0.5 * sin((_time * 6.2) + _phase_seed)
		var ring_color := accent
		ring_color.a = 0.18 + 0.12 * pulse
		draw_circle(Vector2(0, 18 + bob), 51 + pulse * 3.0, ring_color)

	draw_rect(Rect2(-32, 47, 64, 10), Color(0, 0, 0, 0.24), true)

	var body_rect := Rect2(-26, -14 + bob, 52, 44)
	_draw_rect_with_outline(body_rect, body, outline)

	var shoulder_rect := Rect2(-20, -22 + bob, 40, 14)
	_draw_rect_with_outline(shoulder_rect, accent, outline)

	var neck_rect := Rect2(-7, -32 + bob, 14, 10)
	_draw_rect_with_outline(neck_rect, skin, outline)

	var head_rect := Rect2(-22, -64 + bob, 44, 34)
	_draw_rect_with_outline(head_rect, skin, outline)

	var hair_rect := Rect2(-24, -68 + bob, 48, 14)
	_draw_rect_with_outline(hair_rect, hair, outline)

	var left_eye_y := -50 + bob
	var right_eye_y := -50 + bob
	if _tone == "skeptical":
		left_eye_y -= 1
		right_eye_y += 1
	elif _tone == "curious":
		left_eye_y -= 1
	elif _tone == "excited":
		left_eye_y += 1
		right_eye_y += 1

	draw_rect(Rect2(-12, left_eye_y, 6, 4), eye, true)
	draw_rect(Rect2(6, right_eye_y, 6, 4), eye, true)

	var mouth_h := 2
	if _is_talking and _mouth_open:
		mouth_h = 6
	elif _tone == "excited":
		mouth_h = 4
	draw_rect(Rect2(-6, -38 + bob, 12, mouth_h), mouth, true)

	if _is_active:
		draw_rect(Rect2(-28, -16 + bob, 56, 2), accent.lightened(0.2), true)


func _draw_rect_with_outline(rect: Rect2, fill: Color, line: Color) -> void:
	draw_rect(rect, fill, true)
	draw_rect(rect, line, false, 2.0)


func _color_from(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges()
	if text == "" or not text.begins_with("#"):
		text = fallback_hex
	return Color(text)
