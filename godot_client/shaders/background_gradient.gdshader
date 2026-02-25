shader_type canvas_item;

uniform vec4 sky_top : source_color = vec4(0.486, 0.776, 1.0, 1.0);
uniform vec4 sky_bottom : source_color = vec4(0.875, 0.957, 1.0, 1.0);
uniform vec4 ground_top : source_color = vec4(0.475, 0.71, 0.353, 1.0);
uniform vec4 ground_bottom : source_color = vec4(0.29, 0.478, 0.216, 1.0);
uniform float horizon_y : hint_range(0.02, 0.98) = 0.62;

void fragment() {
	float y = clamp(UV.y, 0.0, 1.0);
	float safe_horizon = clamp(horizon_y, 0.02, 0.98);

	float sky_t = clamp(y / safe_horizon, 0.0, 1.0);
	float ground_t = clamp((y - safe_horizon) / (1.0 - safe_horizon), 0.0, 1.0);

	vec4 sky_col = mix(sky_top, sky_bottom, sky_t);
	vec4 ground_col = mix(ground_top, ground_bottom, ground_t);
	float ground_mask = step(safe_horizon, y);
	COLOR = mix(sky_col, ground_col, ground_mask);
}
