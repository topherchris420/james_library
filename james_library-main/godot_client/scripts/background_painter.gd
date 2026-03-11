extends Node2D
class_name BackgroundPainter

const GRADIENT_SHADER_PATH := "res://shaders/background_gradient.gdshader"

var _theme_id: String = "flower_field"
var _background_cfg: Dictionary = {}
var _seed: int = 1
var _gradient_rect: ColorRect


func _ready() -> void:
	_ensure_gradient_layer()
	var viewport := get_viewport()
	if viewport != null:
		viewport.size_changed.connect(_on_viewport_size_changed)
	_sync_gradient_rect()
	_apply_gradient_to_shader()


func apply_theme(theme_id: String, background_cfg: Dictionary) -> void:
	_theme_id = theme_id
	_background_cfg = background_cfg.duplicate(true)
	_seed = abs(hash(theme_id)) + 17
	_apply_gradient_to_shader()
	queue_redraw()


func _on_viewport_size_changed() -> void:
	_sync_gradient_rect()
	queue_redraw()


func _draw() -> void:
	var size := get_viewport_rect().size
	var horizon_ratio := float(_background_cfg.get("horizon_y", 0.62))
	var horizon_y := int(size.y * horizon_ratio)

	var decor_style := str(_background_cfg.get("decor_style", "flowers")).to_lower()
	if decor_style == "lab":
		_draw_lab(size, horizon_y)
	else:
		_draw_flower_field(size, horizon_y)


func _ensure_gradient_layer() -> void:
	if _gradient_rect != null:
		return
	_gradient_rect = ColorRect.new()
	_gradient_rect.name = "GradientRect"
	_gradient_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_gradient_rect.z_index = -100
	add_child(_gradient_rect)

	var shader := load(GRADIENT_SHADER_PATH)
	if shader is Shader:
		var material := ShaderMaterial.new()
		material.shader = shader
		_gradient_rect.material = material


func _sync_gradient_rect() -> void:
	if _gradient_rect == null:
		return
	var rect := get_viewport_rect()
	_gradient_rect.position = rect.position
	_gradient_rect.size = rect.size


func _apply_gradient_to_shader() -> void:
	if _gradient_rect == null:
		return
	var material := _gradient_rect.material
	if material == null or not (material is ShaderMaterial):
		return
	var shader_mat := material as ShaderMaterial
	shader_mat.set_shader_parameter("sky_top", _color_from(_background_cfg.get("sky_top", "#7cc6ff"), "#7cc6ff"))
	shader_mat.set_shader_parameter("sky_bottom", _color_from(_background_cfg.get("sky_bottom", "#dff4ff"), "#dff4ff"))
	shader_mat.set_shader_parameter("ground_top", _color_from(_background_cfg.get("ground_top", "#79b55a"), "#79b55a"))
	shader_mat.set_shader_parameter("ground_bottom", _color_from(_background_cfg.get("ground_bottom", "#4a7a37"), "#4a7a37"))
	shader_mat.set_shader_parameter("horizon_y", clampf(float(_background_cfg.get("horizon_y", 0.62)), 0.02, 0.98))


func _draw_flower_field(size: Vector2, horizon_y: int) -> void:
	var rng := RandomNumberGenerator.new()
	rng.seed = _seed

	for i in range(7):
		var cloud_x := rng.randi_range(40, int(size.x) - 120)
		var cloud_y := rng.randi_range(30, maxi(60, horizon_y - 120))
		var cloud_col := Color(1, 1, 1, 0.7)
		draw_rect(Rect2(cloud_x, cloud_y, 56, 14), cloud_col, true)
		draw_rect(Rect2(cloud_x + 8, cloud_y - 8, 40, 10), cloud_col, true)

	var flower_colors: Array = _background_cfg.get(
		"decor_colors",
		["#ffd2f5", "#fff0a6", "#c6f3ff", "#ffd3b6", "#ffffff"]
	)
	var flower_count := int(_background_cfg.get("decor_count", 170))

	for i in range(flower_count):
		var x := rng.randi_range(4, int(size.x) - 4)
		var y := rng.randi_range(horizon_y + 8, int(size.y) - 18)
		draw_rect(Rect2(x, y - 2, 1, 3), _color_from("#476b2f", "#476b2f"), true)

		var petal_color := _color_from(
			flower_colors[rng.randi_range(0, flower_colors.size() - 1)],
			"#ffd2f5"
		)
		draw_rect(Rect2(x - 1, y - 4, 3, 1), petal_color, true)
		draw_rect(Rect2(x, y - 5, 1, 3), petal_color, true)


func _draw_lab(size: Vector2, horizon_y: int) -> void:
	var grid_color := _color_from(_background_cfg.get("grid_color", "#6ea9d5"), "#6ea9d5")
	var panel_color := _color_from(_background_cfg.get("panel_color", "#2c3a50"), "#2c3a50")
	var strip_color := _color_from(_background_cfg.get("strip_color", "#92d7ff"), "#92d7ff")

	for x in range(0, int(size.x) + 1, 32):
		draw_line(Vector2(x, horizon_y), Vector2(x, size.y), grid_color, 1.0)
	for y in range(horizon_y, int(size.y) + 1, 20):
		draw_line(Vector2(0, y), Vector2(size.x, y), grid_color, 1.0)

	var rng := RandomNumberGenerator.new()
	rng.seed = _seed * 3

	var terminal_count := 12
	var terminal_w := int(size.x / terminal_count)
	for i in range(terminal_count):
		var x := i * terminal_w + 4
		var h := rng.randi_range(36, 62)
		var y := horizon_y - h + rng.randi_range(0, 8)
		draw_rect(Rect2(x, y, terminal_w - 8, h), panel_color, true)
		draw_rect(Rect2(x + 6, y + 8, terminal_w - 20, 8), strip_color, true)
		draw_rect(Rect2(x + 6, y + 22, terminal_w - 28, 6), strip_color.darkened(0.2), true)


func _color_from(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges()
	if text == "":
		text = fallback_hex
	if not text.begins_with("#"):
		text = fallback_hex
	return Color(text)
