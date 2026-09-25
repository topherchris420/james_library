extends Node2D
class_name AgentAvatar

## Procedural NES-style agent avatar with a layered animation rig.
##
## Every part is drawn in code on a 20x28 "sprite pixel" canvas and shown at 4x
## with nearest-neighbour filtering, so the client needs no image assets. The
## rig is a stack of layers (ground, body, secondary, head, eyes, brows, mouth,
## blush, front accessories). Textures are baked once per theme style; animation
## swaps baked frames and moves layers in whole sprite pixels, which keeps the
## retro look crisp and costs no allocations per frame.
##
## Behaviours:
## - idle: breathing bob, randomised blinks (sometimes double), wandering gaze,
##   per-character secondary motion (James's tentacles, Luca's scarf)
## - listening: eyes and a head lean follow the active speaker, occasional nods,
##   brief reactions to the speaker's tone
## - talking: mouth shapes driven by the live voice level from AudioSync (or a
##   procedural flap when no level is available), syllable head bobs, gestures
## - tone: expression presets (curious, excited, focused, skeptical, concerned,
##   pleased) that set brows, eyes, resting mouth, blush, head tilt and energy
## - events: staggered drop-in entrance, turn-taking hop with squash and
##   stretch, end-of-conversation celebration

const SPRITE_SCALE := 4
const CANVAS_W := 20
const CANVAS_H := 28
const BODY_PHASES := 8
const SECONDARY_FRAMES := 4

const LIDS: Array[String] = ["open", "wide", "half", "narrow", "closed", "happy"]
const BROWS: Array[String] = ["neutral", "raised", "furrowed", "worried", "skeptical"]
const MOUTHS: Array[String] = ["closed", "small", "open", "wide", "smile", "frown", "grin"]
const POSES: Array[String] = ["rest", "gesture", "cheer"]

## Expression presets keyed by canonical tone.
const EXPRESSIONS := {
	"neutral": {"brows": "neutral", "lid": "open", "mouth": "closed", "blush": false, "tilt": 0, "energy": 1.0},
	"curious": {"brows": "raised", "lid": "wide", "mouth": "closed", "blush": false, "tilt": 1, "energy": 1.1},
	"excited": {"brows": "raised", "lid": "open", "mouth": "smile", "blush": true, "tilt": 0, "energy": 1.6},
	"focused": {"brows": "furrowed", "lid": "narrow", "mouth": "closed", "blush": false, "tilt": 0, "energy": 0.8},
	"skeptical": {"brows": "skeptical", "lid": "narrow", "mouth": "frown", "blush": false, "tilt": -1, "energy": 0.9},
	"concerned": {"brows": "worried", "lid": "open", "mouth": "frown", "blush": false, "tilt": 0, "energy": 0.8},
	"pleased": {"brows": "neutral", "lid": "open", "mouth": "smile", "blush": true, "tilt": 0, "energy": 1.1},
}

## Tone words that map onto the presets above.
const TONE_ALIASES := {
	"happy": "pleased",
	"agree": "pleased",
	"agreeing": "pleased",
	"warm": "pleased",
	"enthusiastic": "excited",
	"surprised": "curious",
	"questioning": "curious",
	"doubtful": "skeptical",
	"critical": "skeptical",
	"worried": "concerned",
	"cautious": "concerned",
	"thoughtful": "focused",
	"serious": "focused",
	"analytical": "focused",
}

## Per-character silhouettes. Colours always come from the theme style.
const LOOKS := {
	"james": {"archetype": "octopus", "accessory": "spectacles"},
	"jasmine": {"archetype": "humanoid", "hair": "bob", "outfit": "overalls", "accessory": "goggles"},
	"luca": {"archetype": "humanoid", "hair": "swept", "outfit": "scarf", "accessory": ""},
	"elena": {"archetype": "humanoid", "hair": "bun", "outfit": "blazer", "accessory": "glasses"},
}
const FALLBACK_HAIR: Array[String] = ["short", "bob", "swept", "bun"]

const HUMANOID_FACE := {"eye_l": Vector2i(6, 7), "eye_r": Vector2i(11, 7), "eye_h": 2, "mouth": Vector2i(9, 10), "blush_y": 9}
const OCTOPUS_FACE := {"eye_l": Vector2i(5, 8), "eye_r": Vector2i(12, 8), "eye_h": 3, "mouth": Vector2i(9, 12), "blush_y": 11}

const DROP_HEIGHT_PX := 480.0
const DROP_TIME_S := 0.55

var agent_id: String = ""
var display_name: String = ""
var style: Dictionary = {}

var _look: Dictionary = {}
var _face: Dictionary = HUMANOID_FACE
var _pal: Dictionary = {}
var _rng := RandomNumberGenerator.new()
var _phase: float = 0.0
var _time: float = 0.0
var _baked: bool = false

# Baked textures.
var _body_tex: Dictionary = {}        # "pose:phase" -> Texture2D
var _secondary_tex: Array[Texture2D] = []
var _head_tex: Texture2D
var _eyes_tex: Dictionary = {}        # "lid:gaze" -> Texture2D
var _brows_tex: Dictionary = {}
var _mouth_tex: Dictionary = {}
var _blush_tex: Texture2D
var _front_tex: Texture2D
var _shadow_tex: Texture2D
var _spot_tex: Texture2D
var _marker_tex: Texture2D

# Rig nodes.
var _ground: Sprite2D
var _rig: Node2D
var _body: Sprite2D
var _secondary: Sprite2D
var _head: Node2D
var _head_base: Sprite2D
var _eyes: Sprite2D
var _brows: Sprite2D
var _mouth: Sprite2D
var _blush: Sprite2D
var _front: Sprite2D
var _marker: Sprite2D
var _label: Label

# Behaviour state.
var _is_talking: bool = false
var _is_active: bool = false
var _tone: String = "neutral"
var _relax_at: float = INF
var _focus_dir: int = 0
var _gaze: int = 0
var _next_glance: float = 0.0
var _blink_start: float = -INF
var _blink_second: float = -INF
var _next_blink: float = 0.0
var _pose: String = "rest"
var _pose_until: float = 0.0
var _next_gesture: float = 0.0
var _voice_level: float = -1.0
var _mouth_open: float = 0.0
var _mouth_shape: String = "closed"
var _mouth_hold: float = 0.0
var _flap_speed: float = 10.0
var _flap_threshold: float = 0.08
var _nod_start: float = -INF
var _hops: Array[Dictionary] = []
var _was_airborne: bool = false
var _squash_start: float = -INF
var _squash_amount: float = 0.0
var _drop_start: float = -INF
var _landed: bool = true
var _celebrate_until: float = -INF


func _init() -> void:
	# Build the rig up front so the avatar owns its parts even if it is freed
	# before entering the scene tree.
	_ground = _make_sprite("Ground")
	_ground.centered = true
	_ground.scale = Vector2(SPRITE_SCALE, SPRITE_SCALE)
	_ground.position = Vector2(0, 2)
	add_child(_ground)

	_rig = Node2D.new()
	_rig.name = "Rig"
	_rig.scale = Vector2(SPRITE_SCALE, SPRITE_SCALE)
	add_child(_rig)
	_body = _make_sprite("Body")
	_secondary = _make_sprite("Secondary")
	_head = Node2D.new()
	_head.name = "Head"
	_rig.add_child(_body)
	_rig.add_child(_secondary)
	_rig.add_child(_head)

	_head_base = _make_sprite("HeadBase")
	_blush = _make_sprite("Blush")
	_eyes = _make_sprite("Eyes")
	_front = _make_sprite("Front")
	_brows = _make_sprite("Brows")
	_mouth = _make_sprite("Mouth")
	for part in [_head_base, _blush, _eyes, _front, _brows, _mouth]:
		_head.add_child(part)
	for part in [_body, _secondary, _head_base, _blush, _eyes, _front, _brows, _mouth]:
		part.position = Vector2(-CANVAS_W * 0.5, -CANVAS_H)

	_marker = _make_sprite("Marker")
	_marker.centered = true
	_marker.scale = Vector2(SPRITE_SCALE, SPRITE_SCALE)
	add_child(_marker)

	_label = Label.new()
	_label.name = "NamePlate"
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.size = Vector2(180, 22)
	_label.position = Vector2(-90, -CANVAS_H * SPRITE_SCALE - 30)
	_label.add_theme_font_size_override("font_size", 15)
	_label.add_theme_constant_override("outline_size", 6)
	_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_label)


func _ready() -> void:
	if not _baked:
		configure(agent_id if agent_id != "" else "james", display_name, style)


func _process(delta: float) -> void:
	_time += delta
	_tick_expression()
	_tick_blink()
	_tick_gaze()
	_tick_gesture()
	_tick_mouth(delta)
	_tick_motion()
	_apply_layers()


## ------------------------------------------------------------------
## Public API (driven by scene_orchestrator.gd)
## ------------------------------------------------------------------

func configure(agent_key: String, shown_name: String, style_cfg: Dictionary) -> void:
	agent_id = agent_key
	display_name = shown_name if shown_name != "" else agent_key.capitalize()
	var seed_value := hash(agent_key.to_lower())
	_rng.seed = seed_value
	_phase = float(abs(seed_value) % 1000) / 1000.0 * TAU
	_look = _look_for(agent_key)
	_face = OCTOPUS_FACE if _look.archetype == "octopus" else HUMANOID_FACE
	_next_blink = _rng.randf_range(0.6, 3.0)
	_next_glance = _rng.randf_range(1.0, 3.0)
	apply_style(style_cfg)


func apply_style(style_cfg: Dictionary) -> void:
	style = style_cfg.duplicate(true) if style_cfg else {}
	_flap_speed = float(style.get("flap_speed", 10.0))
	_flap_threshold = float(style.get("mouth_flap_threshold", 0.08))
	_pal = _palette_from(style)
	_bake_all()
	_label.text = display_name
	_label.add_theme_color_override("font_color", _pal["name"])
	_label.add_theme_color_override("font_outline_color", _pal["outline"])
	_apply_active_visuals()
	_apply_layers()


func set_talking(value: bool) -> void:
	if _is_talking == value:
		return
	_is_talking = value
	if value:
		_next_gesture = _time + _rng.randf_range(0.3, 1.0)
		_next_glance = _time + _rng.randf_range(0.8, 1.6)
		_gaze = 0
	else:
		_pose = "rest"
		_voice_level = -1.0
		_relax_at = _time + 2.5


func set_active(value: bool) -> void:
	if _is_active == value:
		return
	_is_active = value
	if value and _landed:
		_queue_hop(0.0, 10.0, 0.24)
	_apply_active_visuals()


## Mood for this avatar's own line. Unknown tones fall back to neutral.
func set_tone(tone: String) -> void:
	_tone = canonical_tone(tone)
	_relax_at = INF


## A listener's short-lived reaction to someone else's tone.
func react(tone: String) -> void:
	if _is_talking:
		return
	_tone = canonical_tone(tone)
	_relax_at = _time + _rng.randf_range(2.2, 3.8)


## Live mouth driver: 0..1 loudness, or a negative value when unknown.
func set_voice_level(level: float) -> void:
	_voice_level = level


## -1/1 points toward the active speaker, 0 when nobody is speaking.
func set_focus_direction(direction: int) -> void:
	_focus_dir = signi(direction)
	if _focus_dir != 0 and not _is_talking:
		_gaze = _focus_dir
		_next_glance = _time + _rng.randf_range(1.8, 3.6)


func nod(delay_s: float = 0.0) -> void:
	_nod_start = _time + maxf(0.0, delay_s)


func play_entrance(delay_s: float = 0.0) -> void:
	_drop_start = _time + maxf(0.0, delay_s)
	_landed = false
	_hops.clear()
	_apply_active_visuals()
	_tick_motion()


func celebrate(delay_s: float = 0.0) -> void:
	var start := maxf(0.0, delay_s)
	_queue_hop(start, 16.0, 0.32)
	_queue_hop(start + 0.42, 10.0, 0.26)
	_celebrate_until = _time + start + 1.6
	_tone = "pleased"
	_relax_at = _celebrate_until + 1.0


static func canonical_tone(tone: String) -> String:
	var key := tone.strip_edges().to_lower()
	if EXPRESSIONS.has(key):
		return key
	return str(TONE_ALIASES.get(key, "neutral"))


## ------------------------------------------------------------------
## Behaviour
## ------------------------------------------------------------------

func _tick_expression() -> void:
	if _time >= _relax_at:
		_tone = "neutral"
		_relax_at = INF


func _tick_blink() -> void:
	if _time < _next_blink:
		return
	_blink_start = _time
	_blink_second = _time + 0.3 if _rng.randf() < 0.2 else -INF
	var gap := _rng.randf_range(1.6, 3.4) if _is_talking else _rng.randf_range(2.2, 5.5)
	_next_blink = _time + gap


func _blink_lid() -> String:
	for start in [_blink_start, _blink_second]:
		var t: float = _time - start
		if t >= 0.0 and t < 0.19:
			return "closed" if t >= 0.05 and t < 0.14 else "half"
	return ""


func _tick_gaze() -> void:
	if _time < _next_glance:
		return
	_next_glance = _time + _rng.randf_range(1.4, 4.2)
	if _is_talking:
		# Speakers scan the room, favouring the audience in front of them.
		_gaze = 0 if _rng.randf() < 0.45 else _rng.randi_range(-1, 1)
	elif _focus_dir != 0 and _rng.randf() < 0.8:
		_gaze = _focus_dir
	else:
		_gaze = _rng.randi_range(-1, 1) if _rng.randf() < 0.6 else 0


func _tick_gesture() -> void:
	if _time < _celebrate_until:
		_pose = "cheer"
		return
	if not _is_talking:
		_pose = "rest"
		return
	var energy := _energy()
	if _pose != "rest" and _time >= _pose_until:
		_pose = "rest"
		_next_gesture = _time + _rng.randf_range(0.9, 2.4) / energy
	elif _pose == "rest" and _time >= _next_gesture:
		_pose = "cheer" if _tone == "excited" and _rng.randf() < 0.45 else "gesture"
		_pose_until = _time + _rng.randf_range(0.5, 1.1)


func _tick_mouth(delta: float) -> void:
	var target := 0.0
	if _is_talking:
		target = _voice_level if _voice_level >= 0.0 else _procedural_voice()
	var rate := 30.0 if target > _mouth_open else 14.0
	_mouth_open = lerpf(_mouth_open, target, minf(1.0, delta * rate))

	var desired := str(_expression().mouth)
	if _is_talking and _mouth_open >= _flap_threshold:
		if _mouth_open < 0.32:
			desired = "small"
		elif _mouth_open < 0.62:
			desired = "open"
		else:
			desired = "grin" if _tone == "excited" or _tone == "pleased" else "wide"
	elif _time < _celebrate_until:
		desired = "grin"

	_mouth_hold -= delta
	if desired != _mouth_shape and _mouth_hold <= 0.0:
		_mouth_shape = desired
		_mouth_hold = 0.05  # hold each shape for a few frames, like hand-drawn flaps


func _procedural_voice() -> float:
	# Syllable-like bumps at the theme's flap speed, shaped by a slower phrase contour.
	var syllables := absf(sin(_time * _flap_speed * 0.5 * PI + _phase))
	var phrase := 0.55 + 0.45 * sin(_time * 1.7 + _phase)
	return syllables * phrase


func _tick_motion() -> void:
	# Entrance drop: fall with gravity, land with squash and a small bounce.
	var drop_offset := 0.0
	if not _landed:
		var t := _time - _drop_start
		if t < 0.0:
			drop_offset = -DROP_HEIGHT_PX
		elif t < DROP_TIME_S:
			var p := t / DROP_TIME_S
			drop_offset = -DROP_HEIGHT_PX * (1.0 - p * p)
		else:
			_landed = true
			_start_squash(0.22)
			_queue_hop(0.0, 6.0, 0.18)
			_apply_active_visuals()

	var hop_offset := _hop_offset()
	var airborne := hop_offset < -0.5 or drop_offset < -0.5
	if _was_airborne and not airborne:
		_start_squash(0.16)
	_was_airborne = airborne

	var lift := drop_offset + hop_offset
	_rig.position = Vector2(0.0, roundf(lift / SPRITE_SCALE) * SPRITE_SCALE)
	_rig.visible = _landed or _time >= _drop_start

	var squash := 0.0
	var st := _time - _squash_start
	if st >= 0.0 and st < 0.2:
		squash = _squash_amount * (1.0 - st / 0.2)
	_rig.scale = Vector2(SPRITE_SCALE * (1.0 + squash), SPRITE_SCALE * (1.0 - squash))

	var air := clampf(-lift / 90.0, 0.0, 0.7)
	_ground.scale = Vector2(SPRITE_SCALE * (1.0 - air), SPRITE_SCALE * (1.0 - air))
	var spot_pulse := 0.8 + 0.2 * sin(_time * 4.0)
	_ground.modulate.a = (spot_pulse if _is_active else 1.0) * (1.0 - air * 0.6)

	# Head: breathing on a slow cycle, syllable emphasis, nods, tilt and lean.
	var breath_period := 1.2 if _is_talking else 1.9
	var head_y := 1 if fmod(_time + _phase, breath_period) > breath_period * 0.5 else 0
	if _is_talking and _mouth_open > 0.62:
		head_y -= 1
	var nod_t := _time - _nod_start
	if nod_t >= 0.0 and nod_t < 0.48 and int(nod_t / 0.12) % 2 == 0:
		head_y += 1
	var head_x := int(_expression().tilt)
	if not _is_talking and _focus_dir != 0 and _time >= _celebrate_until:
		head_x = _focus_dir
	_head.position = Vector2(head_x, head_y)

	# Active-speaker marker bobs one sprite pixel above the name plate.
	var marker_bob := 1 if fmod(_time, 0.8) > 0.4 else 0
	_marker.position = Vector2(0, -CANVAS_H * SPRITE_SCALE - 42 + marker_bob * SPRITE_SCALE)


func _queue_hop(delay_s: float, height_px: float, duration_s: float) -> void:
	_hops.append({"start": _time + delay_s, "height": height_px, "duration": duration_s})


func _hop_offset() -> float:
	var offset := 0.0
	var remaining: Array[Dictionary] = []
	for hop in _hops:
		var t: float = _time - float(hop.start)
		var duration: float = hop.duration
		if t < duration:
			remaining.append(hop)
		if t >= 0.0 and t < duration:
			var p := t / duration
			offset = minf(offset, -float(hop.height) * 4.0 * p * (1.0 - p))
	_hops = remaining
	return offset


func _start_squash(amount: float) -> void:
	_squash_start = _time
	_squash_amount = amount


func _expression() -> Dictionary:
	return EXPRESSIONS.get(_tone, EXPRESSIONS["neutral"])


func _energy() -> float:
	return float(_expression().energy)


## ------------------------------------------------------------------
## Layer selection
## ------------------------------------------------------------------

func _apply_layers() -> void:
	if not _baked:
		return
	var phase_rate := (5.0 * _energy()) if _is_talking else 2.2
	var phase := int(_time * phase_rate + _phase * 2.0) % BODY_PHASES
	var pose := _pose if POSES.has(_pose) else "rest"
	_body.texture = _body_tex.get("%s:%d" % [pose, phase], _body_tex.get("rest:0"))

	_secondary.visible = not _secondary_tex.is_empty()
	if _secondary.visible:
		var sway_rate := 6.0 if _is_talking else 3.0
		_secondary.texture = _secondary_tex[int(_time * sway_rate + _phase) % _secondary_tex.size()]

	var expression := _expression()
	var lid := str(expression.lid)
	if _time < _celebrate_until:
		lid = "happy"
	var blink := _blink_lid()
	if blink != "":
		lid = blink
	var gaze := _gaze if lid in ["open", "wide", "half", "narrow"] else 0
	_eyes.texture = _eyes_tex.get("%s:%d" % [lid, gaze])
	_brows.texture = _brows_tex.get(str(expression.brows))
	_mouth.texture = _mouth_tex.get(_mouth_shape)
	_blush.visible = bool(expression.blush) or _time < _celebrate_until
	_front.visible = _front_tex != null


func _apply_active_visuals() -> void:
	if not _baked:
		return
	_ground.texture = _spot_tex if _is_active else _shadow_tex
	_marker.visible = _is_active and _landed
	_label.visible = _landed
	_label.modulate = Color(1, 1, 1, 1.0 if _is_active else 0.72)


## ------------------------------------------------------------------
## Palette and baking
## ------------------------------------------------------------------

func _look_for(key: String) -> Dictionary:
	var lower := key.to_lower()
	for look_key in LOOKS.keys():
		if lower.contains(look_key):
			return LOOKS[look_key]
	var hair := FALLBACK_HAIR[abs(hash(lower)) % FALLBACK_HAIR.size()]
	return {"archetype": "humanoid", "hair": hair, "outfit": "plain", "accessory": ""}


func _palette_from(cfg: Dictionary) -> Dictionary:
	var body := _color(cfg.get("body"), "#5f8dd4")
	var accent := _color(cfg.get("accent"), "#3d5d93")
	var skin := _color(cfg.get("skin"), "#f2d4b3")
	var hair := _color(cfg.get("hair"), "#2f3b52")
	var outline := _color(cfg.get("outline"), "#1b2230")
	var eye := _color(cfg.get("eye"), "#101318")
	var mouth := _color(cfg.get("mouth"), "#5d2d2d")
	var octopus: bool = _look.get("archetype", "") == "octopus"
	var face_skin := body if octopus else skin
	return {
		"body": body,
		"body_shade": body.darkened(0.22),
		"body_light": body.lightened(0.25),
		"accent": accent,
		"accent_shade": accent.darkened(0.25),
		"accent_light": accent.lightened(0.3),
		"skin": skin,
		"face": face_skin,
		"lid": face_skin.darkened(0.2),
		"blush": face_skin.lerp(Color("#ff6f86"), 0.5),
		"hair": hair,
		"hair_light": hair.lightened(0.22),
		"brow": body.darkened(0.5) if octopus else hair,
		"outline": outline,
		"shoe": outline.lightened(0.12),
		"eye": eye,
		"white": Color("#f5f3ea"),
		"lens": Color("#d8f1ff"),
		"mouth": mouth,
		"mouth_dark": mouth.darkened(0.45),
		"tongue": Color("#e0707a"),
		"gold": Color("#f2c14e"),
		"name": body.lightened(0.45),
	}


func _color(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges() if value != null else ""
	if not text.begins_with("#"):
		text = fallback_hex
	return Color(text)


func _bake_all() -> void:
	_body_tex.clear()
	_eyes_tex.clear()
	_brows_tex.clear()
	_mouth_tex.clear()
	_secondary_tex.clear()

	var octopus: bool = _look.archetype == "octopus"
	for pose in POSES:
		for phase in BODY_PHASES:
			var img := _bake_octopus_body(pose, phase) if octopus else _bake_humanoid_body(pose)
			_body_tex["%s:%d" % [pose, phase]] = ImageTexture.create_from_image(img)
	if _look.get("outfit", "") == "scarf":
		for frame in SECONDARY_FRAMES:
			_secondary_tex.append(ImageTexture.create_from_image(_bake_scarf_tail(frame)))

	_head_tex = ImageTexture.create_from_image(_bake_octopus_head() if octopus else _bake_humanoid_head())
	for lid in LIDS:
		for gaze in [-1, 0, 1]:
			_eyes_tex["%s:%d" % [lid, gaze]] = ImageTexture.create_from_image(_bake_eyes(lid, gaze))
	for shape in BROWS:
		_brows_tex[shape] = ImageTexture.create_from_image(_bake_brows(shape))
	for shape in MOUTHS:
		_mouth_tex[shape] = ImageTexture.create_from_image(_bake_mouth(shape))
	_blush_tex = ImageTexture.create_from_image(_bake_blush())
	var front := _bake_front()
	_front_tex = ImageTexture.create_from_image(front) if front != null else null
	_shadow_tex = ImageTexture.create_from_image(_bake_ellipse(18, 4, Color(0, 0, 0, 0.28), Color(0, 0, 0, 0.28)))
	_spot_tex = ImageTexture.create_from_image(
		_bake_ellipse(22, 6, Color(1, 1, 1, 0.22), _pal.body_light * Color(1, 1, 1, 0.55))
	)
	_marker_tex = ImageTexture.create_from_image(_bake_marker())

	_head_base.texture = _head_tex
	_blush.texture = _blush_tex
	_front.texture = _front_tex
	_marker.texture = _marker_tex
	_baked = true


## -- drawing primitives ------------------------------------------------

func _canvas(width: int = CANVAS_W, height: int = CANVAS_H) -> Image:
	var img := Image.create(width, height, false, Image.FORMAT_RGBA8)
	img.fill(Color(0, 0, 0, 0))
	return img


func _px(img: Image, x: int, y: int, c: Color) -> void:
	if x >= 0 and y >= 0 and x < img.get_width() and y < img.get_height():
		img.set_pixel(x, y, c)


func _rect(img: Image, x: int, y: int, w: int, h: int, c: Color) -> void:
	for yy in range(y, y + h):
		for xx in range(x, x + w):
			_px(img, xx, yy, c)


func _clear(img: Image, x: int, y: int) -> void:
	_px(img, x, y, Color(0, 0, 0, 0))


func _opaque(img: Image, x: int, y: int) -> bool:
	return x >= 0 and y >= 0 and x < img.get_width() and y < img.get_height() and img.get_pixel(x, y).a > 0.0


## Wrap every opaque region in a 1-pixel outline (4-neighbourhood), NES style.
func _outline(img: Image, c: Color) -> void:
	var marks: Array[Vector2i] = []
	for y in img.get_height():
		for x in img.get_width():
			if _opaque(img, x, y):
				continue
			if _opaque(img, x + 1, y) or _opaque(img, x - 1, y) or _opaque(img, x, y + 1) or _opaque(img, x, y - 1):
				marks.append(Vector2i(x, y))
	for p in marks:
		img.set_pixel(p.x, p.y, c)


## -- bodies -------------------------------------------------------------

func _bake_humanoid_body(pose: String) -> Image:
	var img := _canvas()
	var pal := _pal
	var outfit := str(_look.get("outfit", "plain"))
	var pants: Color = pal.accent_shade if outfit == "scarf" or outfit == "blazer" else pal.accent

	_rect(img, 9, 11, 2, 2, pal.skin.darkened(0.12))                  # neck
	_rect(img, 7, 21, 2, 4, pants)                                     # legs
	_rect(img, 11, 21, 2, 4, pants)
	_rect(img, 6, 25, 3, 2, pal.shoe)                                  # shoes
	_rect(img, 11, 25, 3, 2, pal.shoe)
	_rect(img, 5, 13, 10, 8, pal.body)                                 # torso
	_rect(img, 14, 13, 1, 8, pal.body_shade)
	_rect(img, 6, 13, 8, 1, pal.body_light)

	match outfit:
		"overalls":
			_rect(img, 7, 13, 1, 4, pal.accent)
			_rect(img, 12, 13, 1, 4, pal.accent)
			_rect(img, 7, 16, 6, 5, pal.accent)
			_rect(img, 9, 17, 2, 1, pal.accent_shade)
			_px(img, 7, 16, pal.gold)
			_px(img, 12, 16, pal.gold)
		"scarf":
			_rect(img, 6, 12, 8, 2, pal.accent)
			_rect(img, 6, 13, 8, 1, pal.accent_shade)
			_rect(img, 5, 17, 10, 1, pal.body_light)
		"blazer":
			_rect(img, 8, 13, 4, 1, pal.white)
			_rect(img, 9, 14, 2, 1, pal.white)
			_px(img, 8, 14, pal.accent)
			_px(img, 11, 14, pal.accent)
			_px(img, 8, 15, pal.accent)
			_px(img, 11, 15, pal.accent)
			_px(img, 9, 17, pal.gold)
			_px(img, 9, 19, pal.gold)
		_:
			_rect(img, 5, 20, 10, 1, pal.accent_shade)

	var sleeve: Color = pal.body_shade
	# Left arm.
	if pose == "cheer":
		_rect(img, 3, 12, 2, 2, sleeve)
		_rect(img, 1, 10, 2, 2, sleeve)
		_rect(img, 1, 8, 2, 2, pal.skin)
	else:
		_rect(img, 3, 13, 2, 6, sleeve)
		_rect(img, 3, 19, 2, 2, pal.skin)
	# Right arm.
	if pose == "gesture" or pose == "cheer":
		_rect(img, 15, 12, 2, 2, sleeve)
		_rect(img, 17, 10, 2, 2, sleeve)
		_rect(img, 17, 8, 2, 2, pal.skin)
	else:
		_rect(img, 15, 13, 2, 6, sleeve)
		_rect(img, 15, 19, 2, 2, pal.skin)

	_outline(img, pal.outline)
	return img


func _bake_octopus_body(pose: String, phase: int) -> Image:
	var img := _canvas()
	var pal := _pal
	# Four tentacles, two pixels thick near the mantle and tapering to curled tips.
	var bases := [4, 7, 11, 14]
	var lengths := [10, 11, 11, 10]
	var angle := float(phase) / float(BODY_PHASES) * TAU
	for i in bases.size():
		var raised := (pose != "rest" and i == bases.size() - 1) or (pose == "cheer" and i == 0)
		if raised:
			_draw_raised_tentacle(img, i != 0)
			continue
		var base: int = bases[i]
		var length: int = lengths[i]
		var outward := -1 if base < 10 else 1
		var x := base
		for k in length:
			var reach := float(k) / float(length)
			var sway := sin(angle + float(k) * 0.55 + float(i) * 1.7) * 1.4 * reach
			x = base + int(roundf(sway + float(outward) * reach * reach * 1.6))
			var thick := k < length - 4
			_px(img, x, 15 + k, pal.accent)
			if thick:
				_px(img, x - outward, 15 + k, pal.accent_light if k % 2 == 0 else pal.accent)
		# Curl the tip outward and up.
		_px(img, x + outward, 14 + length, pal.accent)
		_px(img, x + outward, 13 + length, pal.accent_light)
	_outline(img, pal.outline)
	return img


func _draw_raised_tentacle(img: Image, right_side: bool) -> void:
	var path := [Vector2i(15, 13), Vector2i(16, 12), Vector2i(17, 11), Vector2i(17, 10), Vector2i(18, 9), Vector2i(18, 8), Vector2i(17, 7)]
	for i in path.size():
		var p: Vector2i = path[i]
		var x := p.x if right_side else CANVAS_W - 1 - p.x
		_px(img, x, p.y, _pal.accent_light if i % 3 == 1 else _pal.accent)


func _bake_scarf_tail(frame: int) -> Image:
	var img := _canvas()
	var angle := float(frame) / float(SECONDARY_FRAMES) * TAU
	for row in range(14, 19):
		var reach := float(row - 13) / 5.0
		var dx := int(roundf(sin(angle + reach * 2.2) * reach * 1.2))
		_rect(img, 12 + dx, row, 2, 1, _pal.accent if row < 18 else _pal.accent_light)
	_outline(img, _pal.outline)
	return img


## -- heads --------------------------------------------------------------

func _bake_humanoid_head() -> Image:
	var img := _canvas()
	var pal := _pal
	_rect(img, 5, 3, 10, 9, pal.skin)
	for corner in [Vector2i(5, 3), Vector2i(14, 3), Vector2i(5, 11), Vector2i(14, 11)]:
		_clear(img, corner.x, corner.y)
	_rect(img, 4, 7, 1, 2, pal.skin.darkened(0.1))                   # ears
	_rect(img, 15, 7, 1, 2, pal.skin.darkened(0.1))

	match str(_look.get("hair", "short")):
		"bob":
			_rect(img, 5, 1, 10, 4, pal.hair)
			_clear(img, 5, 1)
			_clear(img, 14, 1)
			_rect(img, 4, 3, 1, 7, pal.hair)
			_rect(img, 15, 3, 1, 7, pal.hair)
			_rect(img, 7, 2, 2, 1, pal.hair_light)
		"swept":
			_rect(img, 5, 2, 10, 3, pal.hair)
			_rect(img, 12, 1, 2, 1, pal.hair)
			_rect(img, 13, 5, 2, 1, pal.hair)
			_px(img, 14, 6, pal.hair)
			_rect(img, 4, 3, 1, 4, pal.hair)
			_rect(img, 15, 3, 1, 5, pal.hair)
			_rect(img, 7, 2, 3, 1, pal.hair_light)
		"bun":
			_rect(img, 8, 1, 4, 2, pal.hair)
			_px(img, 9, 1, pal.hair_light)
			_rect(img, 5, 3, 10, 2, pal.hair)
			_clear(img, 5, 3)
			_clear(img, 14, 3)
			_rect(img, 4, 4, 1, 4, pal.hair)
			_rect(img, 15, 4, 1, 4, pal.hair)
			_rect(img, 8, 3, 4, 1, pal.accent)
		_:
			_rect(img, 5, 2, 10, 3, pal.hair)
			_rect(img, 4, 3, 1, 3, pal.hair)
			_rect(img, 15, 3, 1, 3, pal.hair)
			_rect(img, 7, 2, 2, 1, pal.hair_light)

	if _look.get("accessory", "") == "goggles":
		_rect(img, 4, 4, 12, 1, pal.accent)
		_rect(img, 6, 3, 2, 2, pal.lens)
		_rect(img, 12, 3, 2, 2, pal.lens)
		_px(img, 6, 3, pal.white)
		_px(img, 12, 3, pal.white)

	_outline(img, pal.outline)
	return img


func _bake_octopus_head() -> Image:
	var img := _canvas()
	var pal := _pal
	var spans := {2: [6, 13], 3: [5, 14], 4: [4, 15], 13: [4, 15], 14: [5, 14]}
	for y in range(2, 15):
		var span: Array = spans.get(y, [3, 16])
		_rect(img, span[0], y, span[1] - span[0] + 1, 1, pal.body)
	_rect(img, 6, 4, 2, 1, pal.body_light)
	_rect(img, 5, 5, 2, 1, pal.body_light)
	for spot in [Vector2i(10, 3), Vector2i(12, 5), Vector2i(14, 7), Vector2i(4, 11)]:
		_px(img, spot.x, spot.y, pal.body_shade)
	_outline(img, pal.outline)
	return img


## -- face layers ----------------------------------------------------------

func _bake_eyes(lid: String, gaze: int) -> Image:
	var img := _canvas()
	var pal := _pal
	var h: int = _face.eye_h
	var white: Color = pal.lens.lerp(pal.white, 0.5) if _look.get("accessory", "") == "glasses" else pal.white
	for eye in [_face.eye_l, _face.eye_r]:
		var x0: int = eye.x
		var y0: int = eye.y
		var pupil_x := x0 + 1 + gaze
		match lid:
			"open":
				_rect(img, x0, y0, 3, h, white)
				_rect(img, pupil_x, y0 + h - 2, 1, 2, pal.eye)
			"wide":
				_rect(img, x0, y0 - 1, 3, h + 1, white)
				_rect(img, pupil_x, y0 + h - 2, 1, 2, pal.eye)
			"half":
				_rect(img, x0, y0, 3, 1, pal.lid)
				_rect(img, x0, y0 + 1, 3, h - 1, white)
				_rect(img, pupil_x, y0 + h - 1, 1, 1, pal.eye)
			"narrow":
				_rect(img, x0, y0, 3, h - 1, pal.outline)
				_rect(img, x0, y0 + h - 1, 3, 1, white)
				_px(img, pupil_x, y0 + h - 1, pal.eye)
			"closed":
				_rect(img, x0, y0 + h - 1, 3, 1, pal.eye)
			"happy":
				_px(img, x0, y0 + 1, pal.eye)
				_px(img, x0 + 1, y0, pal.eye)
				_px(img, x0 + 2, y0 + 1, pal.eye)
	return img


func _bake_brows(shape: String) -> Image:
	var img := _canvas()
	var c: Color = _pal.brow
	var l: Vector2i = _face.eye_l
	var r: Vector2i = _face.eye_r
	match shape:
		"raised":
			_rect(img, l.x, l.y - 2, 3, 1, c)
			_rect(img, r.x, r.y - 2, 3, 1, c)
		"furrowed":
			_px(img, l.x, l.y - 2, c)
			_rect(img, l.x + 1, l.y - 1, 2, 1, c)
			_rect(img, r.x, r.y - 1, 2, 1, c)
			_px(img, r.x + 2, r.y - 2, c)
		"worried":
			_rect(img, l.x, l.y - 1, 2, 1, c)
			_px(img, l.x + 2, l.y - 2, c)
			_px(img, r.x, r.y - 2, c)
			_rect(img, r.x + 1, r.y - 1, 2, 1, c)
		"skeptical":
			_rect(img, l.x, l.y - 2, 3, 1, c)
			_rect(img, r.x, r.y - 1, 3, 1, c)
		_:
			_rect(img, l.x, l.y - 1, 3, 1, c)
			_rect(img, r.x, r.y - 1, 3, 1, c)
	return img


func _bake_mouth(shape: String) -> Image:
	var img := _canvas()
	var pal := _pal
	var m: Vector2i = _face.mouth
	match shape:
		"small":
			_rect(img, m.x, m.y, 2, 1, pal.mouth_dark)
			_rect(img, m.x, m.y + 1, 2, 1, pal.mouth)
		"open":
			_rect(img, m.x, m.y, 2, 1, pal.mouth_dark)
			_rect(img, m.x, m.y + 1, 2, 1, pal.tongue)
		"wide":
			_rect(img, m.x - 1, m.y, 4, 1, pal.mouth_dark)
			_px(img, m.x - 1, m.y + 1, pal.mouth_dark)
			_rect(img, m.x, m.y + 1, 2, 1, pal.tongue)
			_px(img, m.x + 2, m.y + 1, pal.mouth_dark)
		"smile":
			_px(img, m.x - 1, m.y, pal.mouth)
			_px(img, m.x + 2, m.y, pal.mouth)
			_rect(img, m.x, m.y + 1, 2, 1, pal.mouth)
		"frown":
			_rect(img, m.x, m.y, 2, 1, pal.mouth)
			_px(img, m.x - 1, m.y + 1, pal.mouth)
			_px(img, m.x + 2, m.y + 1, pal.mouth)
		"grin":
			_px(img, m.x - 1, m.y, pal.mouth)
			_rect(img, m.x, m.y, 2, 1, pal.white)
			_px(img, m.x + 2, m.y, pal.mouth)
			_rect(img, m.x, m.y + 1, 2, 1, pal.mouth_dark)
		_:
			_rect(img, m.x, m.y, 2, 1, pal.mouth)
	return img


func _bake_blush() -> Image:
	var img := _canvas()
	var y: int = _face.blush_y
	_px(img, _face.eye_l.x, y, _pal.blush)
	_px(img, _face.eye_r.x + 2, y, _pal.blush)
	return img


func _bake_front() -> Image:
	var accessory := str(_look.get("accessory", ""))
	if accessory != "glasses" and accessory != "spectacles":
		return null
	var img := _canvas()
	var frame: Color = _pal.outline.lightened(0.1)
	var h: int = _face.eye_h
	for eye in [_face.eye_l, _face.eye_r]:
		var x0: int = eye.x
		var y0: int = eye.y
		_rect(img, x0 - 1, y0, 1, h, frame)
		_rect(img, x0 + 3, y0, 1, h, frame)
		_rect(img, x0, y0 + h, 3, 1, frame)
		if accessory == "spectacles":
			_rect(img, x0, y0 - 1, 3, 1, frame)
	if accessory == "spectacles":
		_rect(img, 9, _face.eye_l.y, 2, 1, frame)
	return img


## -- ground and marker ----------------------------------------------------

func _bake_ellipse(width: int, height: int, edge: Color, core: Color) -> Image:
	var img := _canvas(width, height)
	var cx := (float(width) - 1.0) / 2.0
	var cy := (float(height) - 1.0) / 2.0
	for y in height:
		for x in width:
			var nx := (float(x) - cx) / (float(width) / 2.0)
			var ny := (float(y) - cy) / (float(height) / 2.0)
			var d := nx * nx + ny * ny
			if d <= 1.0:
				img.set_pixel(x, y, core if d < 0.35 else edge)
	return img


func _bake_marker() -> Image:
	var img := _canvas(7, 5)
	_rect(img, 1, 1, 5, 1, _pal.gold)
	_rect(img, 2, 2, 3, 1, _pal.gold)
	_px(img, 3, 3, _pal.gold)
	_outline(img, _pal.outline)
	return img


func _make_sprite(node_name: String) -> Sprite2D:
	var sprite := Sprite2D.new()
	sprite.name = node_name
	sprite.centered = false
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	return sprite
