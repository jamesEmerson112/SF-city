shader_type spatial;
render_mode cull_back;

uniform float simulation_time;
uniform vec3 part_size;
uniform vec3 part_center;
uniform vec3 part_pivot;
uniform float part_swing;

void vertex() {
    // Root translation/facing comes ONLY from the authoritative display transform.
    // x = phase, y = close enough to animate, z = moving, w = selected.
    float angle = part_swing * sin(6.28318530718 * (1.6 * simulation_time + INSTANCE_CUSTOM.x)) * 0.55 * INSTANCE_CUSTOM.y * INSTANCE_CUSTOM.z;
    float c = cos(angle);
    float s = sin(angle);
    mat3 gait = mat3(vec3(c,0.0,-s), vec3(0.0,1.0,0.0), vec3(s,0.0,c));
    vec3 local = part_pivot + gait * (part_center - part_pivot + VERTEX * part_size);
    vec3 normal = gait * normalize(NORMAL / part_size);
    VERTEX = vec3(local.x, local.z, -local.y);
    NORMAL = vec3(normal.x, normal.z, -normal.y);
    COLOR.rgb = mix(COLOR.rgb, vec3(1.0, 0.76, 0.18), INSTANCE_CUSTOM.w * 0.45);
}

void fragment() {
    ALBEDO = COLOR.rgb;
    ROUGHNESS = 0.85;
    METALLIC = 0.0;
}
