extends PanelContainer
class_name DialogueUI

@export var default_chars_per_second: float = 66.0

@onready var _speaker_name: Label = $Margin/VBox/SpeakerName
@onready var _subtitle_text: RichTextLabel = $Margin/VBox/SubtitleText

var _chars_per_second: float = default_chars_per_second
var _target_text: String = ""
var _visible_characters: int = 0
var _progress_characters: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_subtitle_text.visible_characters = -1
	_set_panel_style(Color("#f7f7f7"), Color("#2d2d2d"))


func _process(delta: float) -> void:
	if _visible_characters >= _target_text.length():
		return

	_progress_characters += _chars_per_second * delta
	var next_count := mini(_target_text.length(), int(_progress_characters))
	if next_count > _visible_characters:
		_visible_characters = next_count
		_subtitle_text.visible_characters = _visible_characters


func apply_theme(ui_cfg: Dictionary, theme_id: String) -> void:
	var panel_bg := _color_from(ui_cfg.get("panel_bg", "#e9e9e9"), "#e9e9e9")
	var panel_border := _color_from(ui_cfg.get("panel_border", "#222222"), "#222222")
	var speaker_color := _color_from(ui_cfg.get("speaker_color", "#1f1f1f"), "#1f1f1f")
	var text_color := _color_from(ui_cfg.get("text_color", "#171717"), "#171717")
	_chars_per_second = float(ui_cfg.get("typewriter_chars_per_second", default_chars_per_second))

	_set_panel_style(panel_bg, panel_border)
	_speaker_name.add_theme_color_override("font_color", speaker_color)
	_subtitle_text.add_theme_color_override("default_color", text_color)


func show_line(speaker_name: String, text: String) -> void:
	_speaker_name.text = speaker_name
	_start_typewriter(text.strip_edges())


func append_chunk(chunk: String) -> void:
	if chunk.strip_edges() == "":
		return
	_target_text += chunk
	_subtitle_text.text = _target_text


func show_status(text: String) -> void:
	_speaker_name.text = "SYSTEM"
	_start_typewriter(text.strip_edges())


func _start_typewriter(text: String) -> void:
	_target_text = text
	_visible_characters = 0
	_progress_characters = 0.0
	_subtitle_text.text = _target_text
	_subtitle_text.visible_characters = 0


func _set_panel_style(fill_color: Color, border_color: Color) -> void:
	var box := StyleBoxFlat.new()
	box.bg_color = fill_color
	box.border_color = border_color
	box.border_width_left = 4
	box.border_width_top = 4
	box.border_width_right = 4
	box.border_width_bottom = 4
	box.corner_radius_top_left = 0
	box.corner_radius_top_right = 0
	box.corner_radius_bottom_left = 0
	box.corner_radius_bottom_right = 0
	add_theme_stylebox_override("panel", box)


func _color_from(value: Variant, fallback_hex: String) -> Color:
	var text := str(value).strip_edges()
	if text == "" or not text.begins_with("#"):
		text = fallback_hex
	return Color(text)
