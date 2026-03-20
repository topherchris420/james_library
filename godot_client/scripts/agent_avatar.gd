extends Node2D
class_name AgentAvatar

## NES-style pixel-art avatar renderer.
## All sprites are generated procedurally at authentic NES resolution (8 px wide).
## Godot's nearest-neighbor upscale + pixel-snap in project.godot gives the chunky
## retro look with zero external assets.

## Base palette — neutral greys used by all character palettes
const PAL := {
	0: null,                          # transparent
	1: Color("#1b2230"),              # outline / deep shadow
	2: Color("#bca078"),              # skin mid
	3: Color("#f0d8a8"),              # skin light
	4: Color("#d89878"),             # skin cheek / blush
	5: Color("#3a6abc"),              # blue body (Jasmine)
	6: Color("#1e3a8a"),              # blue dark
	7: Color("#7ec8e3"),              # eye / water blue
	8: Color("#f0f0e8"),              # white
	9: Color("#e82020"),              # red / mouth
	10: Color("#50a050"),             # green body (James octopus)
	11: Color("#2860a0"),             # blue
	12: Color("#a07050"),             # hair brown
	13: Color("#e8c040"),             # gold / star
	14: Color("#303030"),             # near-black (Luca)
	15: Color("#c0c0c0"),             # light grey (Luca)
	16: Color("#b03030"),             # dark red body (Elena)
	17: Color("#e04040"),             # bright red (Elena accent)
	18: Color("#e8a030"),             # amber / gold (James body)
	19: Color("#c87040"),             # coral pink (James tentacles)
}

## AVATARS — each entry has its own palette and 8×20 sprite grid.
## Palette indices are local to each entry and map to the shared PAL above.
## Sprite rows: head(4) + brow(1) + eyes(2) + mouth(1) + body(5) + legs(7) = 20 px tall.
const AVATARS := {
	"james": {
		## Amber/gold octopus with coral pink tentacles
		"palette": [1, 2, 3, 7, 18, 19],
		"sprite": [
			# head outline
			[0,0,1,1,1,1,0,0],
			[0,1,18,18,18,18,1,0],
			# head face
			[1,2,3,3,3,3,2,1],
			# brow
			[1,3,3,3,3,3,3,1],
			# eyes row 1 — wide, big octopus eyes
			[1,2,8,8,8,8,2,1],
			# eyes row 2
			[1,2,8,7,7,8,2,1],
			# mouth row
			[1,2,2,2,2,2,2,1],
			# body — dark, tentacles spread from row 7 downward
			[0,1,19,19,19,19,1,0],
			[1,1,19,19,19,19,1,1],
			# tentacles: spread outward from center
			[1,19,19,1,1,19,19,1],
			[1,19,1,0,0,1,19,1],
			[19,1,0,0,0,0,1,19],
			[0,1,0,0,0,0,1,0],
			[0,1,0,0,0,0,1,0],
			[1,19,1,0,0,1,19,1],
			[1,19,19,1,1,19,19,1],
			[0,1,19,19,19,19,1,0],
			[0,0,1,1,1,1,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
		],
	},
	"jasmine": {
		## Blue body, humanoid
		"palette": [1, 2, 3, 7, 5, 6, 8, 9],
		"sprite": [
			[0,0,1,1,1,1,0,0],
			[0,1,2,2,2,2,1,0],
			[1,3,3,3,3,3,3,1],
			[1,3,3,3,3,3,3,1],
			[1,2,8,8,8,8,2,1],
			[1,2,8,7,7,8,2,1],
			[1,2,2,9,9,2,2,1],
			[0,1,5,5,5,5,1,0],
			[1,1,5,5,5,5,1,1],
			[1,6,5,1,1,5,6,1],
			[1,5,5,5,5,5,5,1],
			[0,1,1,8,8,1,1,0],
			[0,1,6,6,6,6,1,0],
			[0,1,1,0,0,1,1,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,1,1,1,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
		],
	},
	"elena": {
		## Red body, humanoid
		"palette": [1, 2, 3, 7, 16, 17, 8, 9],
		"sprite": [
			[0,0,1,1,1,1,0,0],
			[0,1,2,2,2,2,1,0],
			[1,3,3,3,3,3,3,1],
			[1,3,3,3,3,3,3,1],
			[1,2,8,8,8,8,2,1],
			[1,2,8,7,7,8,2,1],
			[1,2,2,9,9,2,2,1],
			[0,1,16,16,16,16,1,0],
			[1,1,16,16,16,16,1,1],
			[1,17,16,1,1,16,17,1],
			[1,16,16,16,16,16,16,1],
			[0,1,1,8,8,1,1,0],
			[0,1,17,17,17,17,1,0],
			[0,1,1,0,0,1,1,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,1,1,1,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
		],
	},
	"luca": {
		## Grey / dark — humanoid with grey body
		"palette": [1, 2, 3, 7, 14, 15, 8, 9],
		"sprite": [
			[0,0,1,1,1,1,0,0],
			[0,1,2,2,2,2,1,0],
			[1,3,3,3,3,3,3,1],
			[1,3,3,3,3,3,3,1],
			[1,2,8,8,8,8,2,1],
			[1,2,8,7,7,8,2,1],
			[1,2,2,2,2,2,2,1],
			[0,1,14,14,14,14,1,0],
			[1,1,14,14,14,14,1,1],
			[1,15,14,1,1,14,15,1],
			[1,14,14,14,14,14,14,1],
			[0,1,1,8,8,1,1,0],
			[0,1,15,15,15,15,1,0],
			[0,1,1,0,0,1,1,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,0,0,1,0,0],
			[0,0,1,1,1,1,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
			[0,0,0,0,0,0,0,0],
		],
	},
}

const SPRITE_SCALE := 4.0   # 8 px × 4 = 32 px wide × 80 px tall
const FRAME_HZ    := 6.0   # animation frame rate

var agent_id: String = ""
var display_name: String = ""
var style: Dictionary = {}

var _avatar_key := "james"
var _is_talking := false
var _is_active  := false
var _frame: float = 0.0

var _anim_sprite: Sprite2D
var _talk_sprite: Sprite2D
var _active_sprite: Sprite2D

var _idle_frames: Array[Image] = []
var _talk_frames: Array[Image] = []


func _init() -> void:
	_anim_sprite = Sprite2D.new()
	_talk_sprite = Sprite2D.new()
	_active_sprite = Sprite2D.new()
	_anim_sprite.name = "AnimSprite"
	_talk_sprite.name = "TalkSprite"
	_active_sprite.name = "ActiveSprite"


func _ready() -> void:
	add_child(_anim_sprite)
	add_child(_talk_sprite)
	add_child(_active_sprite)

	_anim_sprite.centered = false
	_talk_sprite.centered = false
	_active_sprite.centered = false

	_anim_sprite.position = Vector2i.ZERO
	_talk_sprite.position = Vector2i.ZERO
	_talk_sprite.visible = false
	_active_sprite.position = Vector2i.ZERO
	_active_sprite.visible = false

	_generate_frames()
	_apply_active_state()


func _process(delta: float) -> void:
	if _is_talking:
		_frame += delta * FRAME_HZ
	else:
		_frame += delta * 2.0   # slower idle bob

	var frames := _talk_frames if _is_talking else _idle_frames
	var idx := int(_frame) % frames.size()
	_set_sprite_frame(_anim_sprite if not _is_talking else _talk_sprite, frames[idx])


## ------------------------------------------------------------------
## public API — matches scene_orchestrator.gd expectations
## ------------------------------------------------------------------

func configure(agent_key: String, shown_name: String, style_cfg: Dictionary) -> void:
	agent_id = agent_key
	display_name = shown_name
	_avatar_key = _pick_avatar_key(agent_key)
	style = style_cfg.duplicate(true) if style_cfg else {}
	_frame = 0.0
	_generate_frames()


func apply_style(style_cfg: Dictionary) -> void:
	style = style_cfg.duplicate(true) if style_cfg else {}
	_generate_frames()


func set_talking(value: bool) -> void:
	if _is_talking == value:
		return
	_is_talking = value
	_anim_sprite.visible = not value
	_talk_sprite.visible = value


func set_active(value: bool) -> void:
	if _is_active == value:
		return
	_is_active = value
	_apply_active_state()


func set_tone(_tone: String) -> void:
	# mouth expression baked into talk frame; no extra work needed
	pass


## ------------------------------------------------------------------
## private
## ------------------------------------------------------------------

func _pick_avatar_key(key: String) -> String:
	var lower := key.to_lower()
	for k in AVATARS.keys():
		if lower.contains(k):
			return k
	var av_keys: Array = AVATARS.keys()
	var h: int = abs(hash(key)) % av_keys.size()
	return str(av_keys[h])


func _generate_frames() -> void:
	var av: Dictionary = AVATARS.get(_avatar_key, AVATARS["james"])
	var pal: Array = av.palette
	var data: Array = av.sprite
	var w: int = data[0].size()
	var h: int = data.size()

	var lookup := _build_palette_lookup(pal)

	_idle_frames = [_build_frame(data, w, h, lookup, false)]
	_talk_frames = [_build_frame(data, w, h, lookup, true), _build_frame(data, w, h, lookup, true)]

	_set_sprite_frame(_anim_sprite, _idle_frames[0])
	_set_sprite_frame(_talk_sprite, _talk_frames[0])


func _build_palette_lookup(type_pal: Array) -> Dictionary:
	var lookup := {}
	for i in type_pal:
		var c: Color = PAL.get(i, Color.TRANSPARENT)
		lookup[i] = c
	return lookup


func _build_frame(data: Array, w: int, h: int, lookup: Dictionary, talk: bool) -> Image:
	var img := Image.create(w, h, false, Image.FORMAT_RGBA8)
	img.fill(Color.TRANSPARENT)

	for row in range(h):
		var row_data: Array = data[row]
		for col in range(w):
			var pal_idx: int = row_data[col]
			if pal_idx == 0:
				continue

			var c: Color = lookup.get(pal_idx, Color.TRANSPARENT)

			# Mouth animation: row 6 (mouth row) cols 3-4 open when talking
			if talk and row == 6 and (col == 3 or col == 4):
				c = lookup.get(3, c)   # light skin = open mouth interior

			img.set_pixel(col, row, c)

	return img


func _set_sprite_frame(sprite: Sprite2D, img: Image) -> void:
	var tex := ImageTexture.create_from_image(img)
	sprite.texture = tex
	sprite.scale = Vector2(SPRITE_SCALE, SPRITE_SCALE)


func _apply_active_state() -> void:
	if _is_active:
		_active_sprite.visible = true
		_start_ring()
	else:
		_active_sprite.visible = false


func _start_ring() -> void:
	var ring := Image.create(8, 8, false, Image.FORMAT_RGBA8)
	ring.fill(Color.TRANSPARENT)
	var cx := 4
	var cy := 4
	var r := 3
	for y in range(8):
		for x in range(8):
			var dx := x - cx
			var dy := y - cy
			if abs(sqrt(dx*dx + dy*dy) - r) < 0.8:
				ring.set_pixel(x, y, Color(1, 1, 1, 0.8))
	_set_sprite_frame(_active_sprite, ring)
