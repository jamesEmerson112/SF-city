shader_type spatial;
render_mode cull_back;

uniform vec3 route_points[64];
uniform float route_lengths[64];
uniform ivec4 route_start;
uniform ivec4 route_count;
uniform vec4 route_duration;
uniform vec4 route_total;
uniform float simulation_time;
uniform vec3 part_size;
uniform vec3 part_center;
uniform vec3 part_pivot;
uniform float part_swing;

void vertex() {
    int route = int(INSTANCE_CUSTOM.x + 0.5);
    float phase = INSTANCE_CUSTOM.y;
    float distance = fract(simulation_time / route_duration[route] + phase) * route_total[route];
    vec3 position = route_points[route_start[route]];
    vec3 direction = vec3(1.0, 0.0, 0.0);
    for (int segment = 0; segment < 16; segment++) {
        int index = route_start[route] + segment;
        float length = route_lengths[index];
        if (distance <= length || segment == route_count[route] - 2) {
            direction = route_points[index + 1] - route_points[index];
            position = route_points[index] + direction * (distance / max(length, 0.0001));
            break;
        }
        distance -= length;
    }
    float heading = atan(direction.y, direction.x);
    float angle = part_swing * sin(6.28318530718 * (1.6 * simulation_time + phase)) * 0.55 * INSTANCE_CUSTOM.z;
    float c = cos(angle);
    float s = sin(angle);
    mat3 gait = mat3(vec3(c,0.0,-s), vec3(0.0,1.0,0.0), vec3(s,0.0,c));
    mat3 facing = mat3(vec3(cos(heading),sin(heading),0.0), vec3(-sin(heading),cos(heading),0.0), vec3(0.0,0.0,1.0));
    vec3 local = part_pivot + gait * (part_center - part_pivot + VERTEX * part_size);
    vec3 world = position + facing * local;
    vec3 normal = facing * gait * normalize(NORMAL / part_size);
    VERTEX = vec3(world.x, world.z, -world.y);
    NORMAL = vec3(normal.x, normal.z, -normal.y);
    COLOR.rgb = mix(COLOR.rgb, vec3(1.0, 0.76, 0.18), INSTANCE_CUSTOM.w * 0.45);
}

void fragment() {
    ALBEDO = COLOR.rgb;
    ROUGHNESS = 0.85;
    METALLIC = 0.0;
}
