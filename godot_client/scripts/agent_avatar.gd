extends Node2D
class_name AgentAvatar

## Pixel size — every shape snaps to this grid for authentic 8-bit crunch.
const PX: float = 4.0

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
@onready var _left_pupil: Polygon2D = $BobRoot/LeftPupil
@onready var _right_pupil: Polygon2D = $BobRoot/RightPupil
@onready var _mouth: Polygon2D = $BobRoot/Mouth
@onready var _active_stripe: Polygon2D = $BobRoot/ActiveStripe
@onready var _anim_body: AnimationPlayer = $AnimationPlayer
@onready var _anim_ring: AnimationPlayer = $ActiveRingPlayer
@onready var _name_label: Label = $NameLabel

# Base positions for eye features (in screen-pixels, grid-snapped)
const _LEFT_EYE_POS := Vector2(-10.0, -54.0)
const _RIGHT_EYE_POS := Vector2(6.0, -54.0)
const _LEFT_PUPIL_POS := Vector2(-8.0, -54.0)
const _RIGHT_PUPIL_POS := Vector2(8.0, -54.0)


func configure(agent_key: String, shown_name: String, style_cfg: Dictionary) -> void:
	agent_id = agent_key
	display_name = shown_name
	_phase_seed = float(abs(hash(agent_key)) % 1000) * 0.01
	_mouth_phase = _phase_seed
	apply_style(style_cfg)
	if is_inside_tree() and _name_label != null:
		_name_label.text = display_name


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
	if _name_label != null:
		_name_label.text = display_name
		_name_label.add_theme_color_override("font_color", Color("#c8c8c8"))
		_name_label.add_theme_font_size_override("font_size", 13)


# ── Pixel-art geometry ──────────────────────────────────────────────
# Every measurement is a multiple of PX for crisp grid-aligned edges.

func _setup_geometry() -> void:
	# Shadow — flat rectangle below the sprite
	_px_rect(_shadow, 16, 2)
	_shadow.position = _snap(0.0, 56.0)
	_shadow.color = Color(0.0, 0.0, 0.0, 0.28)

	# Active ring — simple square outline (8-bit style, not a circle)
	_active_ring.polygon = _px_ring(20, 23, 2)
	_active_ring.position = _snap(0.0, 16.0)
	_active_ring.visible = false

	# Body — wide rectangle (RPG torso)
	_px_rect(_body, 12, 12)
	_body.position = _snap(0.0, 12.0)

	# Shoulders — slightly wider bar on top of body
	_px_rect(_shoulders, 14, 3)
	_shoulders.position = _snap(0.0, -4.0)

	# Neck — small connector
	_px_rect(_neck, 4, 3)
	_neck.position = _snap(0.0, -12.0)

	# Head — large square block (chibi RPG style)
	_px_rect(_head, 12, 10)
	_head.position = _snap(0.0, -22.0)

	# Hair — wider block on top of head with overhang
	_px_rect(_hair, 14, 4)
	_hair.position = _snap(0.0, -32.0)

	# Left eye — white sclera square (2×2 px)
	_px_rect(_left_eye, 3, 2)
	_left_eye.position = _LEFT_EYE_POS

	# Right eye — white sclera square (2×2 px)
	_px_rect(_right_eye, 3, 2)
	_right_eye.position = _RIGHT_EYE_POS

	# Left pupil — dark pixel (1×1 px)
	_px_rect(_left_pupil, 1, 2)
	_left_pupil.position = _LEFT_PUPIL_POS

	# Right pupil — dark pixel (1×1 px)
	_px_rect(_right_pupil, 1, 2)
	_right_pupil.position = _RIGHT_PUPIL_POS

	# Mouth — thin line
	_px_rect(_mouth, 4, 1)
	_mouth.position = _snap(0.0, -16.0)

	# Active stripe — highlight bar across shoulders
	_px_rect(_active_stripe, 16, 1)
	_active_stripe.position = _snap(0.0, -4.0)
	_active_stripe.visible = false


func _ensure_animations() -> void:
	_anim_body.root_node = NodePath("..")
	_anim_ring.root_node = NodePath("..")

	var body_library := _anim_body.get_animation_library("")
	if body_library == null:
		body_library = AnimationLibrary.new()
		_anim_body.add_animation_library("", body_library)

	# 8-bit idle: slow 1-pixel bob
	if not body_library.has_animation("idle"):
		body_library.add_animation("idle", _build_bob_animation(1.2, PX))
	# 8-bit talk: faster 2-pixel bob
	if not body_library.has_animation("talk"):
		body_library.add_animation("talk", _build_bob_animation(0.5, PX * 2.0))

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

	# Snap bob to full-pixel offsets for that retro stutter
	var bob_track := anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(bob_track, NodePath("BobRoot:position"))
	anim.track_insert_key(bob_track, 0.0, _snap(0.0, -amplitude))
	anim.track_insert_key(bob_track, length_s * 0.5, _snap(0.0, amplitude))
	anim.track_insert_key(bob_track, length_s, _snap(0.0, -amplitude))
	anim.value_track_set_update_mode(bob_track, Animation.UPDATE_DISCRETE)
	return anim


func _build_ring_pulse_animation() -> Animation:
	var anim := Animation.new()
	anim.length = 0.6
	anim.loop_mode = Animation.LOOP_LINEAR

	var color_track := anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(color_track, NodePath("ActiveRing:modulate"))
	anim.track_insert_key(color_track, 0.0, Color(1.0, 1.0, 1.0, 0.18))
	anim.track_insert_key(color_track, 0.3, Color(1.0, 1.0, 1.0, 0.38))
	anim.track_insert_key(color_track, 0.6, Color(1.0, 1.0, 1.0, 0.18))
	anim.value_track_set_update_mode(color_track, Animation.UPDATE_DISCRETE)
	return anim


func _play_body_animation() -> void:
	var target := "talk" if _is_talking else "idle"
	if _anim_body.current_animation == target and _anim_body.is_playing():
		return
	_anim_body.play(target, 0.0)  # 0.0 blend for crisp pixel transitions
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
		_active_ring.modulate = Color(1.0, 1.0, 1.0, 0.0)


func _apply_tone_to_eyes() -> void:
	# Shift pupils by 1 logical pixel based on tone
	var l_pos := _LEFT_PUPIL_POS
	var r_pos := _RIGHT_PUPIL_POS
	if _tone == "skeptical":
		l_pos.y -= PX
	elif _tone == "curious":
		l_pos.x += PX
		r_pos.x += PX
	elif _tone == "excited":
		l_pos.y += PX
		r_pos.y += PX
	_left_pupil.position = l_pos
	_right_pupil.position = r_pos


func _apply_style_to_nodes() -> void:
	var outline := _color_from(style.get("outline", "#1b2230"), "#1b2230")
	var body_col := _color_from(style.get("body", "#6c91d5"), "#6c91d5")
	var accent := _color_from(style.get("accent", "#405f98"), "#405f98")
	var skin := _color_from(style.get("skin", "#f2d4b3"), "#f2d4b3")
	var hair_col := _color_from(style.get("hair", "#2e3f5b"), "#2e3f5b")
	var eye := _color_from(style.get("eye", "#101318"), "#101318")
	var mouth_col := _color_from(style.get("mouth", "#5d2d2d"), "#5d2d2d")

	_body.color = body_col
	_shoulders.color = accent
	_neck.color = skin
	_head.color = skin
	_hair.color = hair_col
	_left_eye.color = Color(0.92, 0.92, 0.92)  # off-white sclera
	_right_eye.color = Color(0.92, 0.92, 0.92)
	_left_pupil.color = eye
	_right_pupil.color = eye
	_mouth.color = mouth_col

	var stripe := accent.lightened(0.3)
	_active_stripe.color = stripe

	var ring_color := accent
	ring_color.a = 0.2
	_active_ring.color = ring_color
	_shadow.color = Color(0.0, 0.0, 0.0, 0.28)

	# 8-bit palette: slight darkening at edges for "outline" depth
	_hair.color = outline.lerp(hair_col, 0.85)
	_shoulders.color = outline.lerp(accent, 0.82)

	# Name label color
	if _name_label != null:
		_name_label.add_theme_color_override("font_color", accent.lightened(0.45))


func _set_mouth_geometry(is_open: bool) -> void:
	if is_open and _is_talking:
		# Open mouth: taller rectangle
		_px_rect(_mouth, 4, 2)
		_mouth.position = _snap(0.0, -16.0)
	elif _tone == "excited":
		# Excited: wider mouth
		_px_rect(_mouth, 6, 1)
		_mouth.position = _snap(0.0, -16.0)
	else:
		# Closed: thin line
		_px_rect(_mouth, 4, 1)
		_mouth.position = _snap(0.0, -16.0)


# ── Pixel-art helper functions ──────────────────────────────────────

func _snap(x: float, y: float) -> Vector2:
	## Snap a position to the pixel grid.
	return Vector2(roundf(x / PX) * PX, roundf(y / PX) * PX)


func _px_rect(poly: Polygon2D, w_px: int, h_px: int) -> void:
	## Build a rectangle from logical pixel dimensions.
	var hw := float(w_px) * PX * 0.5
	var hh := float(h_px) * PX * 0.5
	poly.polygon = PackedVector2Array([
		Vector2(-hw, -hh),
		Vector2(hw, -hh),
		Vector2(hw, hh),
		Vector2(-hw, hh),
	])


func _px_ring(w_px: int, h_px: int, thickness_px: int) -> PackedVector2Array:
	## Build a rectangular ring (outline only) from logical pixel dimensions.
	var hw := float(w_px) * PX * 0.5
	var hh := float(h_px) * PX * 0.5
	var t := float(thickness_px) * PX
	# Outer box CW, then inner box CCW to form a hollow ring
	var outer := [
		Vector2(-hw, -hh), Vector2(hw, -hh),
		Vector2(hw, hh), Vector2(-hw, hh),
	]
	var inner := [
		Vector2(-hw + t, -hh + t), Vector2(-hw + t, hh - t),
		Vector2(hw - t, hh - t), Vector2(hw - t, -hh + t),
	]
	var pts := PackedVector2Array()
	for p in outer:
		pts.append(p)
	for p in inner:
		pts.append(p)
	return pts


func _color_from(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges()
	if text == "" or not text.begins_with("#"):
		text = fallback_hex
	return Color(text)
