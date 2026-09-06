shader_type spatial;
render_mode diffuse_burley, specular_disabled;

void vertex() {
	vec3 base = (MODEL_MATRIX * vec4(0.0,0.0,0.0,1.0)).xyz;
	float fade = 1.0 - smoothstep(650.0,950.0,distance(base,CAMERA_POSITION_WORLD));
	VERTEX *= fade;
	float tint = clamp(INSTANCE_CUSTOM.r,0.0,3.0)/3.0;
	COLOR.rgb *= mix(vec3(0.88,0.94,0.88),vec3(1.04,1.02,0.92),tint);
}

void fragment() {
	ALBEDO = COLOR.rgb;
	ROUGHNESS = 1.0;
}
