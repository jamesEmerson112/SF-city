shader_type spatial;
render_mode unshaded, cull_disabled, depth_test_disabled, depth_draw_never, shadows_disabled;

// An explicitly selected area is a map annotation, so its boundary remains
// visible through buildings. Width varies in the view; source coordinates do not.
uniform float half_width_m = 1.0;
uniform vec4 outline_color : source_color = vec4(1.0, 0.72, 0.25, 0.88);
varying float edge;

void vertex() {
	edge = UV.x;
	VERTEX += NORMAL * half_width_m * edge;
}

void fragment() {
	ALBEDO = outline_color.rgb;
	ALPHA = outline_color.a * (1.0 - smoothstep(0.70, 1.0, abs(edge)));
}
