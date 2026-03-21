extends Node
class_name ThemeManager

signal theme_applied(theme_id: String, theme_config: Dictionary)

@export var themes_root: String = "res://themes"

var current_theme_id: String = ""
var current_theme: Dictionary = {}

func apply_theme(theme_id: String) -> bool:
	var loaded := _load_theme(theme_id)
	if loaded.is_empty():
		return false

	current_theme_id = theme_id
	current_theme = loaded
	emit_signal("theme_applied", current_theme_id, current_theme)
	return true


func get_default_participants() -> Array[String]:
	var result: Array[String] = []
	if current_theme.has("participants") and current_theme["participants"] is Array:
		for item in current_theme["participants"]:
			var agent_id := str(item).strip_edges().to_lower()
			if agent_id != "" and not result.has(agent_id):
				result.append(agent_id)
	return result


func get_agent_style(agent_id: String) -> Dictionary:
	var fallback := {
		"body": "#5f8dd4",
		"accent": "#3d5d93",
		"skin": "#f2d4b3",
		"hair": "#2f3b52",
		"outline": "#1b2230",
		"eye": "#101318",
		"mouth": "#5d2d2d",
		"flap_speed": 10.0,
	}

	var style := fallback.duplicate(true)
	var agents: Dictionary = {}
	if current_theme.has("agents") and current_theme["agents"] is Dictionary:
		agents = current_theme["agents"]

	if agents.has("default") and agents["default"] is Dictionary:
		style.merge(agents["default"], true)

	var key := agent_id.strip_edges().to_lower()
	if agents.has(key) and agents[key] is Dictionary:
		style.merge(agents[key], true)

	return style


func _load_theme(theme_id: String) -> Dictionary:
	var path := "%s/%s/theme.json" % [themes_root, theme_id]
	if not FileAccess.file_exists(path):
		push_error("Theme file not found: %s" % path)
		return {}

	var raw := FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(raw)
	if parsed is Dictionary:
		var cfg: Dictionary = parsed
		if not cfg.has("id"):
			cfg["id"] = theme_id
		return cfg

	push_error("Failed to parse theme file: %s" % path)
	return {}
