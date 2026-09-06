shader_type spatial;
render_mode diffuse_burley, specular_disabled;

uniform bool use_overlay = false;
uniform bool instanced = false;
uniform bool facades_enabled = true;
uniform vec4 base_tint : source_color = vec4(1.0);
uniform vec4 use_palette[13] : source_color;
varying float category;

void vertex() {
	category = instanced ? INSTANCE_CUSTOM.r : UV.x;
}

void fragment() {
	ALBEDO = instanced ? base_tint.rgb : COLOR.rgb * base_tint.rgb;
	if (use_overlay) {
		int index = clamp(int(round(category)), 0, 12);
		ALBEDO = use_palette[index].rgb;
	} else if (facades_enabled && !instanced && UV.y > 0.01) {
		// Original visual rhythm only: no surveyed windows, floors or materials.
		// Coordinates are meters along this wall and above its sampled base.
		vec2 grid = UV2 / vec2(2.8, 3.25);
		vec2 footprint = max(fwidth(grid), vec2(0.0001));
		vec2 cell = fract(grid);
		vec2 window_edge = vec2(0.23, 0.27);
		vec2 window_mask = 1.0 - smoothstep(window_edge - footprint, window_edge + footprint, abs(cell - vec2(0.5, 0.52)));
		float edge_fade = smoothstep(0.15, 0.5, min(UV2.x, UV.y - UV2.x));
		float resolution_fade = 1.0 - smoothstep(0.08, 0.25, max(footprint.x, footprint.y));
		float distance_fade = 1.0 - smoothstep(120.0, 450.0, length(VERTEX));
		float strength = resolution_fade * distance_fade * edge_fade;
		float glazing = window_mask.x * window_mask.y * strength;
		float floor_band = 1.0 - smoothstep(0.018 - footprint.y, 0.018 + footprint.y, min(cell.y, 1.0 - cell.y));
		ALBEDO *= 1.0 - floor_band * strength * 0.09;
		ALBEDO = mix(ALBEDO, vec3(0.16, 0.22, 0.24), glazing * 0.62);
	}
	ROUGHNESS = 0.94;
}
