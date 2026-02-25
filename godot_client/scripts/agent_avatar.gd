extends Node2D
class_name AgentAvatar

var agent_id: String = ""
var display_name: String = ""
var style: Dictionary = {}

var _is_talking: bool = false
var _is_active: bool = false
var _tone: String = "neutral"
var _mouth_open: bool = false
var _phase_seed: float = 0.0
var _mouth_phase: float = 0.0

@onready var _active_ring: Polygon2D = $ActiveRing
@onready var _shadow: Polygon2D = $Shadow
@onready var _bob_root: Node2D = $BobRoot
@onready var _body: Polygon2D = $BobRoot/Body
@onready var _shoulders: Polygon2D = $BobRoot/Shoulders
@onready var _neck: Polygon2D = $BobRoot/Neck
@onready var _head: Polygon2D = $BobRoot/Head
@onready var _hair: Polygon2D = $BobRoot/Hair
@onready var _left_eye: Polygon2D = $BobRoot/LeftEye
@onready var _right_eye: Polygon2D = $BobRoot/RightEye
@onready var _mouth: Polygon2D = $BobRoot/Mouth
@onready var _active_stripe: Polygon2D = $BobRoot/ActiveStripe
@onready var _anim_body: AnimationPlayer = $AnimationPlayer
@onready var _anim_ring: AnimationPlayer = $ActiveRingPlayer

const _LEFT_EYE_BASE := Vector2(-9.0, -50.0)
const _RIGHT_EYE_BASE := Vector2(9.0, -50.0)


func configure(agent_key: String, shown_name: String, style_cfg: Dictionary) -> void:
	agent_id = agent_key
	display_name = shown_name
	_phase_seed = float(abs(hash(agent_key)) % 1000) * 0.01
	_mouth_phase = _phase_seed
	apply_style(style_cfg)


func apply_style(style_cfg: Dictionary) -> void:
	style = style_cfg.duplicate(true)
	if not is_inside_tree():
		return
	_apply_style_to_nodes()


func set_talking(value: bool) -> void:
	if _is_talking == value:
		return
	_is_talking = value
	if not _is_talking:
		_mouth_open = false
		_set_mouth_geometry(false)
	_play_body_animation()


func set_active(value: bool) -> void:
	if _is_active == value:
		return
	_is_active = value
	_apply_active_state()


func set_tone(tone: String) -> void:
	_tone = tone.strip_edges().to_lower()
	if not is_inside_tree():
		return
	_apply_tone_to_eyes()
	_set_mouth_geometry(_mouth_open)


func _process(delta: float) -> void:
	if not _is_talking:
		return

	var flap_speed := maxf(1.0, float(style.get("flap_speed", 10.0)))
	_mouth_phase += delta * flap_speed
	var next_mouth_open := int(_mouth_phase * 2.0) % 2 == 0
	if next_mouth_open != _mouth_open:
		_mouth_open = next_mouth_open
		_set_mouth_geometry(_mouth_open)


func _ready() -> void:
	_setup_geometry()
	_ensure_animations()
	_apply_style_to_nodes()
	_apply_tone_to_eyes()
	_set_mouth_geometry(false)
	_apply_active_state()
	_play_body_animation()


func _setup_geometry() -> void:
	_set_rect(_shadow, 64.0, 10.0)
	_shadow.position = Vector2(0.0, 47.0)
	_shadow.color = Color(0.0, 0.0, 0.0, 0.24)

	_active_ring.polygon = _circle_polygon(52.0, 28)
	_active_ring.position = Vector2(0.0, 18.0)
	_active_ring.visible = false

	_set_rect(_body, 52.0, 44.0)
	_body.position = Vector2(0.0, 8.0)

	_set_rect(_shoulders, 40.0, 14.0)
	_shoulders.position = Vector2(0.0, -15.0)

	_set_rect(_neck, 14.0, 10.0)
	_neck.position = Vector2(0.0, -27.0)

	_set_rect(_head, 44.0, 34.0)
	_head.position = Vector2(0.0, -47.0)

	_set_rect(_hair, 48.0, 14.0)
	_hair.position = Vector2(0.0, -61.0)

	_set_rect(_left_eye, 6.0, 4.0)
	_left_eye.position = _LEFT_EYE_BASE
	_set_rect(_right_eye, 6.0, 4.0)
	_right_eye.position = _RIGHT_EYE_BASE

	_set_rect(_mouth, 12.0, 2.0)
	_mouth.position = Vector2(0.0, -37.0)

	_set_rect(_active_stripe, 56.0, 2.0)
	_active_stripe.position = Vector2(0.0, -15.0)
	_active_stripe.visible = false


func _ensure_animations() -> void:
	_anim_body.root_node = NodePath("..")
	_anim_ring.root_node = NodePath("..")

	var body_library := _anim_body.get_animation_library("")
	if body_library == null:
		body_library = AnimationLibrary.new()
		_anim_body.add_animation_library("", body_library)

	if not body_library.has_animation("idle"):
		body_library.add_animation("idle", _build_bob_animation(1.2, 2.2))
	if not body_library.has_animation("talk"):
		body_library.add_animation("talk", _build_bob_animation(0.7, 1.2))

	var ring_library := _anim_ring.get_animation_library("")
	if ring_library == null:
		ring_library = AnimationLibrary.new()
		_anim_ring.add_animation_library("", ring_library)
	if not ring_library.has_animation("pulse"):
		ring_library.add_animation("pulse", _build_ring_pulse_animation())


func _build_bob_animation(length_s: float, amplitude: float) -> Animation:
	var anim := Animation.new()
	anim.length = length_s
	anim.loop_mode = Animation.LOOP_LINEAR

	var bob_track := anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(bob_track, NodePath("BobRoot:position"))
	anim.track_insert_key(bob_track, 0.0, Vector2(0.0, -amplitude))
	anim.track_insert_key(bob_track, length_s * 0.5, Vector2(0.0, amplitude))
	anim.track_insert_key(bob_track, length_s, Vector2(0.0, -amplitude))
	return anim


func _build_ring_pulse_animation() -> Animation:
	var anim := Animation.new()
	anim.length = 0.8
	anim.loop_mode = Animation.LOOP_LINEAR

	var scale_track := anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(scale_track, NodePath("ActiveRing:scale"))
	anim.track_insert_key(scale_track, 0.0, Vector2(0.95, 0.95))
	anim.track_insert_key(scale_track, 0.4, Vector2(1.05, 1.05))
	anim.track_insert_key(scale_track, 0.8, Vector2(0.95, 0.95))

	var color_track := anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(color_track, NodePath("ActiveRing:modulate"))
	anim.track_insert_key(color_track, 0.0, Color(1.0, 1.0, 1.0, 0.2))
	anim.track_insert_key(color_track, 0.4, Color(1.0, 1.0, 1.0, 0.32))
	anim.track_insert_key(color_track, 0.8, Color(1.0, 1.0, 1.0, 0.2))
	return anim


func _play_body_animation() -> void:
	var target := "talk" if _is_talking else "idle"
	if _anim_body.current_animation == target and _anim_body.is_playing():
		return
	_anim_body.play(target, 0.15)
	var len := _anim_body.current_animation_length
	if len > 0.0:
		var offset := fmod(_phase_seed, len)
		_anim_body.seek(offset, true)


func _apply_active_state() -> void:
	_active_ring.visible = _is_active
	_active_stripe.visible = _is_active
	if _is_active:
		_anim_ring.play("pulse")
		var len := _anim_ring.current_animation_length
		if len > 0.0:
			var offset := fmod(_phase_seed, len)
			_anim_ring.seek(offset, true)
	else:
		_anim_ring.stop()
		_active_ring.scale = Vector2.ONE
		_active_ring.modulate = Color(1.0, 1.0, 1.0, 0.0)


func _apply_tone_to_eyes() -> void:
	var left_eye := _LEFT_EYE_BASE
	var right_eye := _RIGHT_EYE_BASE
	if _tone == "skeptical":
		left_eye.y -= 1.0
		right_eye.y += 1.0
	elif _tone == "curious":
		left_eye.y -= 1.0
	elif _tone == "excited":
		left_eye.y += 1.0
		right_eye.y += 1.0
	_left_eye.position = left_eye
	_right_eye.position = right_eye


func _apply_style_to_nodes() -> void:
	var outline := _color_from(style.get("outline", "#1b2230"), "#1b2230")
	var body := _color_from(style.get("body", "#6c91d5"), "#6c91d5")
	var accent := _color_from(style.get("accent", "#405f98"), "#405f98")
	var skin := _color_from(style.get("skin", "#f2d4b3"), "#f2d4b3")
	var hair := _color_from(style.get("hair", "#2e3f5b"), "#2e3f5b")
	var eye := _color_from(style.get("eye", "#101318"), "#101318")
	var mouth := _color_from(style.get("mouth", "#5d2d2d"), "#5d2d2d")

	_body.color = body
	_shoulders.color = accent
	_neck.color = skin
	_head.color = skin
	_hair.color = hair
	_left_eye.color = eye
	_right_eye.color = eye
	_mouth.color = mouth

	var stripe := accent.lightened(0.2)
	_active_stripe.color = stripe

	var ring_color := accent
	ring_color.a = 0.2
	_active_ring.color = ring_color
	_shadow.color = Color(0.0, 0.0, 0.0, 0.24)

	# Slight outline simulation using darkened fills on perimeter-adjacent parts.
	var border_tint := outline.darkened(0.05)
	_hair.color = border_tint.lerp(hair, 0.9)
	_shoulders.color = border_tint.lerp(accent, 0.88)
	_body.color = border_tint.lerp(body, 0.9)


func _set_mouth_geometry(is_open: bool) -> void:
	var mouth_h := 2.0
	if is_open and _is_talking:
		mouth_h = 6.0
	elif _tone == "excited":
		mouth_h = 4.0
	_set_rect(_mouth, 12.0, mouth_h)
	_mouth.position = Vector2(0.0, -38.0 + mouth_h * 0.5)


func _set_rect(poly: Polygon2D, width: float, height: float) -> void:
	var hw := width * 0.5
	var hh := height * 0.5
	poly.polygon = PackedVector2Array([
		Vector2(-hw, -hh),
		Vector2(hw, -hh),
		Vector2(hw, hh),
		Vector2(-hw, hh),
	])


func _circle_polygon(radius: float, points: int) -> PackedVector2Array:
	var out := PackedVector2Array()
	var count := maxi(8, points)
	for i in range(count):
		var t := float(i) / float(count)
		var ang := TAU * t
		out.append(Vector2(cos(ang) * radius, sin(ang) * radius))
	return out


func _color_from(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges()
	if text == "" or not text.begins_with("#"):
		text = fallback_hex
	return Color(text)
