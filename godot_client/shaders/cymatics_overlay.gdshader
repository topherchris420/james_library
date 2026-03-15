shader_type canvas_item;

// Resonance event data (set from GDScript).
uniform float target_frequency : hint_range(20.0, 2000.0) = 0.0;
uniform float amplitude : hint_range(0.0, 1.0) = 0.0;
uniform float consensus_stability : hint_range(0.0, 1.0) = 0.5;

// Internal animation clock (seconds, advanced from GDScript).
uniform float time_s : hint_range(0.0, 100000.0) = 0.0;

// Tint colour for the nodal lines.
uniform vec4 line_color : source_color = vec4(0.4, 0.85, 1.0, 1.0);

// --- Chladni plate equation ---
// Classic rectangular Chladni pattern:  f(x,y) = cos(n*pi*x) * cos(m*pi*y) - cos(m*pi*x) * cos(n*pi*y)
// We derive (n, m) from target_frequency so higher frequencies yield denser
// nodal grids, and we blend two mode-pairs for visual richness.

float chladni(vec2 uv, float n, float m) {
	float a = cos(n * 3.14159 * uv.x) * cos(m * 3.14159 * uv.y);
	float b = cos(m * 3.14159 * uv.x) * cos(n * 3.14159 * uv.y);
	return a - b;
}

void fragment() {
	// When amplitude is zero the overlay is fully transparent — no work needed.
	if (amplitude < 0.001) {
		COLOR = vec4(0.0);
		return;
	}

	// Map frequency to mode indices (n, m).  Low frequencies → simple patterns,
	// high frequencies → intricate grids.
	float freq_norm = clamp((target_frequency - 20.0) / 1980.0, 0.0, 1.0);
	float base_n = mix(1.0, 6.0, freq_norm);
	float base_m = mix(2.0, 9.0, freq_norm);

	// Jitter: low consensus_stability adds time-varying wobble to mode indices.
	float jitter = (1.0 - consensus_stability) * 0.6;
	float wobble = sin(time_s * 3.7) * jitter;
	float wobble2 = cos(time_s * 2.3) * jitter;

	float n1 = base_n + wobble;
	float m1 = base_m + wobble2;
	float n2 = base_n * 0.7 + wobble2 * 0.5;
	float m2 = base_m * 1.3 - wobble * 0.5;

	// Centre UVs around origin and scale to [-1, 1].
	vec2 uv = UV * 2.0 - 1.0;

	// Optional slow rotation when stability is low.
	float angle = time_s * 0.15 * (1.0 - consensus_stability);
	float ca = cos(angle);
	float sa = sin(angle);
	uv = vec2(uv.x * ca - uv.y * sa, uv.x * sa + uv.y * ca);

	// Evaluate two Chladni modes and blend.
	float c1 = chladni(uv, n1, m1);
	float c2 = chladni(uv, n2, m2);
	float pattern = mix(c1, c2, 0.35 + 0.15 * sin(time_s * 0.5));

	// Nodal lines are where pattern ≈ 0.  Use smoothstep for soft edges.
	float line_width = mix(0.18, 0.08, consensus_stability);
	float nodal = 1.0 - smoothstep(0.0, line_width, abs(pattern));

	// Ripple ring emanating from centre (frequency-scaled).
	float dist = length(uv);
	float ring = sin(dist * base_n * 4.0 - time_s * 2.5) * 0.5 + 0.5;
	ring = smoothstep(0.42, 0.48, ring);

	// Composite: nodal lines + subtle ripple ring.
	float composite = max(nodal, ring * 0.35);

	// Final alpha driven by amplitude.
	float alpha = composite * amplitude * 0.55;

	// Slight brightness pulse keyed to stability.
	float pulse = 1.0 + 0.12 * sin(time_s * 1.8) * (1.0 - consensus_stability);
	vec3 col = line_color.rgb * pulse;

	COLOR = vec4(col, alpha);
}
