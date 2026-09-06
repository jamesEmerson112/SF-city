extends Node3D
## Shared-fixture renderer, deliberately independent of OpenGlassBox's simulation.
## Coordinates in JSON are (east, north, up); Godot uses (east, up, -north).

const EYE_HEIGHT: float = 1.8
const WALK_RADIUS: float = 0.7
const WALK_SPEED: float = 9.0

var fixture: Dictionary = {}
var route_cache: Dictionary = {}
var resident_nodes: Array[RefCounted] = []
var crowd: Node3D
var population: int = 200
var population_picker: OptionButton
var asset_loaded: bool = false
var asset_mesh_count: int = 0
var selectable_nodes: Dictionary = {}
var camera: Camera3D
var simulation_time: float = 0.0
var paused: bool = false
var time_speed: float = 1.0
var mode: String = "overhead"
var orbit_target: Vector3 = Vector3.ZERO
var orbit_yaw: float = 0.0
var orbit_pitch: float = 0.7
var orbit_distance: float = 450.0
var walk_position: Vector3 = Vector3.ZERO
var walk_yaw: float = 0.0
var walk_pitch: float = 0.0
var drag_distance: float = 0.0
var mouse_dragging: bool = false
var selected_id: String = ""
var selected_label: String = "Nothing selected"
var follow_index: int = 0
var stat_label: Label
var selection_label: Label
var mode_buttons: Dictionary = {}
var pause_button: Button
var speed_button: Button
var frame_ms: float = 16.67
var measured_frames: int = 0
var automation_running: bool = false


func _ready() -> void:
	var scene_path: String = ProjectSettings.globalize_path("res://").path_join("../shared/scene.json").simplify_path()
	if not FileAccess.file_exists(scene_path):
		_fail("Shared fixture not found: " + scene_path)
		return
	var parser := JSON.new()
	if parser.parse(FileAccess.get_file_as_string(scene_path)) != OK or not parser.data is Dictionary:
		_fail("Could not parse shared scene: " + parser.get_error_message())
		return
	fixture = parser.data
	for required: String in ["primitives", "routes", "residents", "camera", "bounds", "collision_boxes", "asset", "character"]:
		if not fixture.has(required):
			_fail("Shared scene is missing " + required)
			return
	_build_environment()
	if not _load_asset(scene_path.get_base_dir()):
		return
	_build_routes()
	_build_residents()
	camera = Camera3D.new()
	camera.name = "ExplorerCamera"
	camera.near = 0.15
	camera.far = 4000.0
	camera.fov = 55.0
	add_child(camera)
	camera.current = true
	_build_hud()
	_reset()
	_update_residents()
	_update_camera(0.0)
	_update_hud()
	call_deferred("_automation")


func _load_asset(directory: String) -> bool:
	var path: String = directory.path_join(str(fixture.asset.file))
	if not FileAccess.file_exists(path):
		_fail("The Blender GLB asset is required: " + path)
		return false
	var document := GLTFDocument.new()
	var state := GLTFState.new()
	var error: Error = document.append_from_file(path, state)
	if error != OK:
		_fail("GLB import failed: " + error_string(error))
		return false
	var imported: Node = document.generate_scene(state)
	if imported == null:
		_fail("GLB import produced an empty scene")
		return false
	add_child(imported)
	var metadata: Dictionary = {}
	for item: Dictionary in state.json.get("nodes", []):
		if item.get("extras", {}).has("id"):
			metadata[str(item.get("name", "")).validate_node_name()] = item.extras
	for mesh: MeshInstance3D in imported.find_children("*", "MeshInstance3D", true, false):
		asset_mesh_count += 1
		var parent: Node = mesh
		var info: Dictionary = {}
		while parent != null and parent != self:
			if metadata.has(str(parent.name)):
				info = metadata[str(parent.name)]
				break
			parent = parent.get_parent()
		if info.is_empty():
			info = {"id": str(mesh.name), "label": str(mesh.name), "type": "feature"}
		var identity: String = str(info.id)
		var body := StaticBody3D.new()
		body.set_meta("selection_id", identity)
		body.set_meta("selection_label", str(info.get("label", identity)))
		body.collision_layer = 1
		body.collision_mask = 0
		var collision := CollisionShape3D.new()
		collision.shape = mesh.mesh.create_trimesh_shape()
		body.add_child(collision)
		mesh.add_child(body)
		if not selectable_nodes.has(identity): selectable_nodes[identity] = []
		selectable_nodes[identity].append(mesh)
	asset_loaded = asset_mesh_count > 0
	if not asset_loaded: _fail("GLB contained no mesh instances")
	return asset_loaded


func _fail(message: String) -> void:
	push_error(message)
	print("GODOT_COMPARISON_FAIL: " + message)
	get_tree().quit(1)


func _to_godot(point: Array) -> Vector3:
	return Vector3(float(point[0]), float(point[2]), -float(point[1]))


func _to_shared(point: Vector3) -> Array:
	return [point.x, -point.z, point.y]


func _color(rgb: Array) -> Color:
	return Color(float(rgb[0]), float(rgb[1]), float(rgb[2]))


func _material(rgb: Array) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = _color(rgb)
	material.roughness = 0.86
	return material


func _build_environment() -> void:
	var world := WorldEnvironment.new()
	var environment := Environment.new()
	var sky := Sky.new()
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color("759cb8")
	sky_material.sky_horizon_color = Color("dce8e9")
	sky_material.ground_bottom_color = Color("52606a")
	sky_material.ground_horizon_color = Color("dce8e9")
	sky.sky_material = sky_material
	environment.background_mode = Environment.BG_SKY
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("d7e1e7")
	environment.ambient_light_energy = 0.20
	environment.ambient_light_sky_contribution = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	world.environment = environment
	add_child(world)
	var sunlight := DirectionalLight3D.new()
	sunlight.name = "AfternoonSun"
	sunlight.rotation_degrees = Vector3(-48.0, -35.0, 0.0)
	sunlight.light_color = Color("fff3dc")
	sunlight.light_energy = 0.65
	sunlight.shadow_enabled = true
	sunlight.directional_shadow_max_distance = 900.0
	add_child(sunlight)


func _build_primitive(primitive: Dictionary) -> void:
	var container := StaticBody3D.new()
	container.name = str(primitive.id).validate_node_name()
	container.position = _to_godot(primitive.position)
	container.set_meta("selection_id", str(primitive.id))
	container.set_meta("selection_label", str(primitive.label))
	container.collision_layer = 1 if bool(primitive.collidable) else 0
	container.collision_mask = 0
	var mesh_instance := MeshInstance3D.new()
	var shape: Shape3D
	match str(primitive.kind):
		"box":
			var box := BoxMesh.new()
			var size: Array = primitive.size
			box.size = Vector3(float(size[0]), float(size[2]), float(size[1]))
			mesh_instance.mesh = box
			var box_shape := BoxShape3D.new()
			box_shape.size = box.size
			shape = box_shape
		"sphere":
			var sphere := SphereMesh.new()
			sphere.radius = float(primitive.radius)
			sphere.height = 2.0 * sphere.radius
			sphere.radial_segments = 32
			sphere.rings = 16
			mesh_instance.mesh = sphere
			var sphere_shape := SphereShape3D.new()
			sphere_shape.radius = sphere.radius
			shape = sphere_shape
			var mesh_scale: Array = primitive.get("scale", [1.0, 1.0, 1.0])
			container.scale = Vector3(float(mesh_scale[0]), float(mesh_scale[2]), float(mesh_scale[1]))
		"cylinder":
			var cylinder := CylinderMesh.new()
			cylinder.top_radius = float(primitive.radius)
			cylinder.bottom_radius = float(primitive.radius)
			cylinder.height = float(primitive.height)
			cylinder.radial_segments = 32
			mesh_instance.mesh = cylinder
			var cylinder_shape := CylinderShape3D.new()
			cylinder_shape.radius = cylinder.top_radius
			cylinder_shape.height = cylinder.height
			shape = cylinder_shape
		_:
			_fail("Unsupported primitive kind: " + str(primitive.kind))
			return
	mesh_instance.material_override = _material(primitive.color)
	container.add_child(mesh_instance)
	if bool(primitive.collidable):
		var collider := CollisionShape3D.new()
		collider.shape = shape
		container.add_child(collider)
	add_child(container)
	selectable_nodes[str(primitive.id)] = container


func _build_routes() -> void:
	for route: Dictionary in fixture.routes:
		var points: Array[Vector3] = []
		var lengths: Array[float] = []
		var total: float = 0.0
		for point: Array in route.points:
			points.append(_to_godot(point))
		for i: int in range(points.size() - 1):
			var segment_length: float = points[i].distance_to(points[i + 1])
			lengths.append(segment_length)
			total += segment_length
		route_cache[str(route.id)] = {"points": points, "lengths": lengths, "total": total, "duration": float(route.duration)}


func _build_residents() -> void:
	crowd = preload("res://crowd.gd").new()
	add_child(crowd)
	crowd.initialize(fixture, route_cache)
	population = fixture.residents.size()
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	var index: int = arguments.find("--population")
	if index >= 0:
		if index + 1 >= arguments.size() or int(arguments[index + 1]) not in [200, 1000, 5000]:
			_fail("--population requires 200, 1000, or 5000")
			return
		population = int(arguments[index + 1])
	resident_nodes = crowd.set_population(population)
	fixture.residents = crowd.residents


func _set_population(count: int) -> void:
	population = count
	resident_nodes = crowd.set_population(count)
	fixture.residents = crowd.residents
	if selected_id.begins_with("resident-") and int(selected_id.trim_prefix("resident-")) >= count:
		_apply_selection("", "Nothing selected")
	follow_index = mini(follow_index, count - 1)
	_update_residents()
	_update_camera(0.0)
	_update_hud()


func _choose_population(index: int) -> void:
	_set_population([200, 1000, 5000][index])


func _change_population(direction: int) -> void:
	var index: int = [200, 1000, 5000].find(population)
	index = posmod(index + direction, 3)
	population_picker.select(index)
	_choose_population(index)


func _sample_route(resident: Dictionary, time: float) -> Vector3:
	var route: Dictionary = route_cache[str(resident.route_id)]
	var distance: float = fposmod(time / float(route.duration) + float(resident.phase), 1.0) * float(route.total)
	var points: Array = route.points
	var lengths: Array = route.lengths
	for i: int in range(lengths.size()):
		var length: float = float(lengths[i])
		if distance <= length or i == lengths.size() - 1:
			return (points[i] as Vector3).lerp(points[i + 1], distance / maxf(length, 0.0001))
		distance -= length
	return points[0]


func _update_residents() -> void:
	crowd.update_all(simulation_time, camera, selected_id)


func _panel() -> PanelContainer:
	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.035, 0.075, 0.11, 0.94)
	style.border_color = Color(0.22, 0.42, 0.44, 0.85)
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	style.content_margin_left = 22.0
	style.content_margin_right = 22.0
	style.content_margin_top = 16.0
	style.content_margin_bottom = 16.0
	panel.add_theme_stylebox_override("panel", style)
	panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return panel


func _label(text_value: String, size: int = 16, color_value: Color = Color("e7efed")) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color_value)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label


func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var root := Control.new()
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(root)
	var top := _panel()
	top.position = Vector2(24.0, 24.0)
	root.add_child(top)
	var info := VBoxContainer.new()
	info.add_theme_constant_override("separation", 7)
	info.mouse_filter = Control.MOUSE_FILTER_IGNORE
	top.add_child(info)
	info.add_child(_label("CITY HALL  /  RENDERER LAB", 14, Color("7ee2c5")))
	info.add_child(_label("Godot 4", 34))
	info.add_child(_label("San Francisco · Civic Center", 17))
	info.add_child(_label("Blender architecture · synthetic population workloads", 13, Color("a8b8c2")))
	stat_label = _label("", 15)
	info.add_child(stat_label)
	var toolbar := HBoxContainer.new()
	toolbar.add_theme_constant_override("separation", 8)
	info.add_child(toolbar)
	for item: Array in [["overhead", "1  Overhead"], ["walk", "2  Walk"], ["follow", "3  Follow"]]:
		var button := Button.new()
		button.text = str(item[1])
		button.focus_mode = Control.FOCUS_NONE
		button.custom_minimum_size.y = 35.0
		button.pressed.connect(_set_mode.bind(str(item[0])))
		toolbar.add_child(button)
		mode_buttons[str(item[0])] = button
	pause_button = Button.new()
	pause_button.text = "Pause"
	pause_button.focus_mode = Control.FOCUS_NONE
	pause_button.pressed.connect(_toggle_pause)
	toolbar.add_child(pause_button)
	speed_button = Button.new()
	speed_button.text = "1×"
	speed_button.focus_mode = Control.FOCUS_NONE
	speed_button.pressed.connect(_toggle_speed)
	toolbar.add_child(speed_button)
	population_picker = OptionButton.new()
	population_picker.focus_mode = Control.FOCUS_NONE
	for value: int in [200, 1000, 5000]: population_picker.add_item("%d people" % value)
	population_picker.select([200, 1000, 5000].find(population))
	population_picker.item_selected.connect(_choose_population)
	info.add_child(population_picker)
	var footer := _panel()
	root.add_child(footer)
	footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	footer.offset_left = 24.0
	footer.offset_right = -24.0
	footer.offset_top = -112.0
	footer.offset_bottom = -24.0
	var footer_content := VBoxContainer.new()
	footer_content.add_theme_constant_override("separation", 5)
	footer_content.mouse_filter = Control.MOUSE_FILTER_IGNORE
	footer.add_child(footer_content)
	selection_label = _label("", 17, Color("7ee2c5"))
	footer_content.add_child(selection_label)
	footer_content.add_child(_label("Drag: orbit / look   ·   Wheel: zoom   ·   WASD: walk   ·   Click: inspect   ·   Space: pause   ·   T: 1× / 4×   ·   R: reset", 15))


func _process(delta: float) -> void:
	if fixture.is_empty() or camera == null:
		return
	frame_ms = lerpf(frame_ms, delta * 1000.0, 0.08)
	measured_frames += 1
	if not automation_running:
		_advance_simulation(delta)
	_update_residents()
	_update_camera(delta)
	_update_hud()


func _advance_simulation(delta: float) -> void:
	if not paused:
		simulation_time += delta * time_speed


func _reset() -> void:
	var config: Dictionary = fixture.camera
	simulation_time = 0.0
	paused = false
	time_speed = 1.0
	orbit_target = _to_godot(config.target)
	orbit_distance = float(config.distance)
	orbit_yaw = deg_to_rad(float(config.yaw_degrees))
	orbit_pitch = deg_to_rad(float(config.pitch_degrees))
	walk_position = _to_godot(config.walk_position)
	var look_direction: Vector3 = orbit_target - walk_position
	walk_yaw = atan2(look_direction.x, -look_direction.z)
	walk_pitch = deg_to_rad(float(config.get("walk_pitch_degrees", 0.0)))
	_apply_selection("", "Nothing selected")
	follow_index = 0
	_set_mode("overhead")


func _set_mode(next_mode: String) -> void:
	if next_mode not in ["overhead", "walk", "follow"]:
		return
	mode = next_mode
	if mode == "follow":
		for i: int in range(fixture.residents.size()):
			if str(fixture.residents[i].id) == selected_id:
				follow_index = i
	_update_camera(0.0)
	_update_hud()


func _toggle_pause() -> void:
	paused = not paused


func _toggle_speed() -> void:
	time_speed = 4.0 if time_speed == 1.0 else 1.0


func _can_walk_to(position_value: Vector3) -> bool:
	var x: float = position_value.x
	var y: float = -position_value.z
	var bounds: Dictionary = fixture.bounds
	if x < float(bounds.min[0]) + WALK_RADIUS or x > float(bounds.max[0]) - WALK_RADIUS:
		return false
	if y < float(bounds.min[1]) + WALK_RADIUS or y > float(bounds.max[1]) - WALK_RADIUS:
		return false
	for box: Dictionary in fixture.collision_boxes:
		if x > float(box.min[0]) - WALK_RADIUS and x < float(box.max[0]) + WALK_RADIUS and y > float(box.min[1]) - WALK_RADIUS and y < float(box.max[1]) + WALK_RADIUS:
			return false
	return true


func _walking_eye_height(position_value: Vector3) -> float:
	var x: float = position_value.x
	var y: float = -position_value.z
	for surface: Dictionary in fixture.get("walk_surfaces", []):
		if x >= float(surface.min[0]) and x <= float(surface.max[0]) and y >= float(surface.min[1]) and y <= float(surface.max[1]):
			var fraction: float = clampf((y - float(surface.from_y)) / (float(surface.to_y) - float(surface.from_y)), 0.0, 1.0)
			return EYE_HEIGHT + lerpf(float(surface.from_z), float(surface.to_z), fraction)
	return 2.28


func _update_camera(delta: float) -> void:
	if camera == null:
		return
	if mode == "walk":
		var turn: float = float(Input.is_physical_key_pressed(KEY_RIGHT)) - float(Input.is_physical_key_pressed(KEY_LEFT))
		walk_yaw += turn * delta * 1.6
		var direction := Vector2(
			float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)),
			float(Input.is_physical_key_pressed(KEY_W)) - float(Input.is_physical_key_pressed(KEY_S)))
		if direction.length_squared() > 0.0:
			direction = direction.normalized()
			var forward := Vector3(sin(walk_yaw), 0.0, -cos(walk_yaw))
			var right := Vector3(cos(walk_yaw), 0.0, sin(walk_yaw))
			var speed: float = 22.0 if Input.is_physical_key_pressed(KEY_SHIFT) else WALK_SPEED
			var displacement: Vector3 = (forward * direction.y + right * direction.x) * speed * minf(delta, 0.05)
			var candidate: Vector3 = walk_position + Vector3(displacement.x, 0.0, 0.0)
			if _can_walk_to(candidate):
				walk_position = candidate
			candidate = walk_position + Vector3(0.0, 0.0, displacement.z)
			if _can_walk_to(candidate):
				walk_position = candidate
		walk_position.y = _walking_eye_height(walk_position)
		camera.position = walk_position
		camera.look_at(walk_position + Vector3(sin(walk_yaw) * cos(walk_pitch), sin(walk_pitch), -cos(walk_yaw) * cos(walk_pitch)), Vector3.UP)
	elif mode == "follow" and not resident_nodes.is_empty():
		var actor: RefCounted = resident_nodes[follow_index]
		var target: Vector3 = actor.position + Vector3.UP * 2.0
		camera.position = actor.position + actor.basis.z * 13.0 + Vector3.UP * 8.0
		camera.look_at(target, Vector3.UP)
	else:
		var offset := Vector3(cos(orbit_yaw) * cos(orbit_pitch), sin(orbit_pitch), -sin(orbit_yaw) * cos(orbit_pitch)) * orbit_distance
		camera.position = orbit_target + offset
		camera.look_at(orbit_target, Vector3.UP)


func _unhandled_input(event: InputEvent) -> void:
	if fixture.is_empty():
		return
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_1: _set_mode("overhead")
			KEY_2: _set_mode("walk")
			KEY_3: _set_mode("follow")
			KEY_SPACE: _toggle_pause()
			KEY_T: _toggle_speed()
			KEY_R: _reset()
			KEY_EQUAL, KEY_PLUS: _change_population(1)
			KEY_MINUS: _change_population(-1)
			KEY_ESCAPE: mouse_dragging = false
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_LEFT or event.button_index == MOUSE_BUTTON_RIGHT:
			if event.pressed:
				mouse_dragging = true
				drag_distance = 0.0
			else:
				mouse_dragging = false
				if event.button_index == MOUSE_BUTTON_LEFT and drag_distance < 5.0:
					_select_at(event.position)
		if event.pressed and mode == "overhead":
			if event.button_index == MOUSE_BUTTON_WHEEL_UP:
				orbit_distance = maxf(25.0, orbit_distance * 0.9)
			elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
				orbit_distance = minf(1500.0, orbit_distance * 1.1)
	if event is InputEventMouseMotion and mouse_dragging:
		drag_distance += event.relative.length()
		if mode == "walk":
			walk_yaw += event.relative.x * 0.005
			walk_pitch = clampf(walk_pitch - event.relative.y * 0.005, -1.35, 1.35)
		else:
			orbit_yaw -= event.relative.x * 0.006
			orbit_pitch = clampf(orbit_pitch + event.relative.y * 0.006, 0.13, 1.48)


func _select_at(screen_position: Vector2) -> void:
	var start: Vector3 = camera.project_ray_origin(screen_position)
	var finish: Vector3 = start + camera.project_ray_normal(screen_position) * camera.far
	var query := PhysicsRayQueryParameters3D.create(start, finish, 1)
	var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
	var identity: String = ""
	var label_value: String = "Nothing selected"
	var nearest: float = camera.far
	if not hit.is_empty():
		var collider: Node = hit.collider
		identity = str(collider.get_meta("selection_id", ""))
		label_value = str(collider.get_meta("selection_label", "Unknown"))
		nearest = start.distance_to(hit.position)
	var direction: Vector3 = (finish - start).normalized()
	for i: int in range(resident_nodes.size()):
		var box := AABB(resident_nodes[i].position + Vector3(-0.32, 0.0, -0.32), Vector3(0.64, 1.85, 0.64))
		var point: Variant = box.intersects_ray(start, direction)
		if point is Vector3:
			var distance: float = start.distance_to(point)
			if distance < nearest:
				nearest = distance
				identity = str(fixture.residents[i].id)
				label_value = "%s · %s → %s" % [fixture.residents[i].label, fixture.residents[i].home, fixture.residents[i].destination]
	_apply_selection(identity, label_value)


func _apply_selection(identifier: String, label_value: String) -> void:
	for id_value: String in [selected_id, identifier]:
		if not selectable_nodes.has(id_value):
			continue
		for mesh: MeshInstance3D in selectable_nodes[id_value]:
			if id_value == identifier:
				var source: Material = mesh.mesh.surface_get_material(0)
				if source is StandardMaterial3D:
					var material: StandardMaterial3D = source.duplicate()
					material.emission_enabled = true
					material.emission = Color(0.2, 0.13, 0.02)
					mesh.material_override = material
			else:
				mesh.material_override = null
	selected_id = identifier
	selected_label = label_value
	follow_index = 0
	for i: int in range(fixture.residents.size()):
		if str(fixture.residents[i].id) == selected_id:
			follow_index = i
	_update_hud()


func _update_hud() -> void:
	if stat_label == null:
		return
	var minutes: int = int(simulation_time) / 60
	var seconds: int = int(simulation_time) % 60
	stat_label.text = "%d simulated · %d in frustum · %d with gait\n%d GLB meshes · %02d:%02d simulated" % [resident_nodes.size(), crowd.visible_count, crowd.animated_count, asset_mesh_count, minutes, seconds]
	stat_label.text += "\n%.0f FPS / %.1f ms (local frame timing)" % [1000.0 / maxf(frame_ms, 0.001), frame_ms] if measured_frames >= 30 else "\nTiming starts during interactive playback"
	selection_label.text = "INSPECT  /  " + selected_label
	if selected_id != "":
		selection_label.text += "  ·  " + selected_id
	if mode == "follow" and not fixture.residents.is_empty():
		selection_label.text += "     FOLLOWING  /  " + str(fixture.residents[follow_index].label)
	for key: String in mode_buttons:
		mode_buttons[key].modulate = Color("7ee2c5") if key == mode else Color.WHITE
	pause_button.text = "Resume" if paused else "Pause"
	speed_button.text = "%d×" % int(time_speed)


func get_comparison_state() -> Dictionary:
	var animated_id: Variant = null
	var angle: Variant = null
	if not crowd.animated_indices.is_empty():
		var indices: Array = crowd.animated_indices.keys()
		indices.sort()
		var index: int = int(indices[0])
		animated_id = fixture.residents[index].id
		angle = sin(TAU * (1.6 * simulation_time + float(fixture.residents[index].phase))) * 0.55
	return {
		"engine": "Godot", "ready": not fixture.is_empty(),
		"simulationTime": simulation_time, "residentCount": resident_nodes.size(),
		"primitiveCount": fixture.primitives.size(), "mode": mode, "paused": paused,
		"assetLoaded": asset_loaded, "assetMeshCount": asset_mesh_count,
		"visibleResidentCount": crowd.visible_count, "animatedResidentCount": crowd.animated_count,
		"crowdPartBatches": crowd.batches.size(),
		"sampleAnimatedResidentId": animated_id, "sampleGaitAngle": angle,
		"selectedId": selected_id,
		"sampleResidentPosition": _to_shared(resident_nodes[0].position) if not resident_nodes.is_empty() else [],
	}


func _automation() -> void:
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	var smoke: bool = "--smoke-test" in arguments
	var initial_mode: String = "overhead"
	var mode_index: int = arguments.find("--mode")
	if mode_index >= 0:
		if mode_index + 1 >= arguments.size() or arguments[mode_index + 1] not in ["overhead", "walk", "follow"]:
			_fail("--mode requires overhead, walk, or follow")
			return
		initial_mode = arguments[mode_index + 1]
	var screenshot_path: String = ""
	var screenshot_index: int = arguments.find("--screenshot")
	if screenshot_index >= 0:
		if screenshot_index + 1 >= arguments.size():
			_fail("--screenshot requires an output PNG path")
			return
		screenshot_path = arguments[screenshot_index + 1]
	if not smoke and screenshot_path.is_empty():
		_set_mode(initial_mode)
		return
	automation_running = true
	for frame: int in range(4):
		await get_tree().process_frame
	if smoke:
		if resident_nodes.is_empty() or fixture.primitives.is_empty():
			_fail("Empty fixture")
			return
		var resident: Dictionary = fixture.residents[0]
		var route: Dictionary = route_cache[str(resident.route_id)]
		var origin_position: Vector3 = _sample_route(resident, 0.0)
		if origin_position.distance_to(_sample_route(resident, float(route.duration))) > 0.01:
			_fail("Route does not repeat deterministically")
			return
		if origin_position.distance_to(_sample_route(resident, 8.0)) < 0.01:
			_fail("Resident does not move")
			return
		simulation_time = 15.0
		_update_residents()
		if resident_nodes[0].position.distance_to(_sample_route(resident, 15.0)) > 0.001:
			_fail("Resident playback differs from sampler")
			return
		if not _can_walk_to(walk_position):
			_fail("Fixture walk spawn intersects a building or bounds")
			return
		if _can_walk_to(Vector3(float(fixture.bounds.max[0]) + 5.0, EYE_HEIGHT, 0.0)):
			_fail("Walk bounds did not reject an outside point")
			return
		for box: Dictionary in fixture.collision_boxes:
			var center := Vector3((float(box.min[0]) + float(box.max[0])) * 0.5, EYE_HEIGHT, -(float(box.min[1]) + float(box.max[1])) * 0.5)
			if _can_walk_to(center):
				_fail("Building collision did not reject its center")
				return
		for check_mode: String in ["walk", "follow", "overhead"]:
			_set_mode(check_mode)
			if not camera.position.is_finite():
				_fail("Invalid camera transform in " + check_mode)
				return
		# Use real camera rays against the physics world, as interactive picking does.
		await get_tree().physics_frame
		var actor: RefCounted = resident_nodes[0]
		var pick_target: Vector3 = actor.position + Vector3.UP * 0.9
		camera.position = pick_target + Vector3(0.01, 20.0, 0.0)
		camera.look_at(pick_target, Vector3.UP)
		_select_at(camera.unproject_position(pick_target))
		if selected_id != str(fixture.residents[0].id):
			_fail("Resident camera ray did not select its marker: " + selected_id)
			return
		var finial := Vector3(0.0, 77.4, -30.0)
		camera.position = finial + Vector3(0.01, 25.0, 0.0)
		camera.look_at(finial, Vector3.UP)
		_select_at(camera.unproject_position(finial))
		if selected_id != "city-hall":
			_fail("City Hall camera ray did not select its finial: " + selected_id)
			return
		_toggle_pause()
		_advance_simulation(1.0)
		if not paused or simulation_time != 15.0:
			_fail("Pause control failed")
			return
		_toggle_speed()
		_toggle_pause()
		_advance_simulation(1.0)
		if time_speed != 4.0 or simulation_time != 19.0:
			_fail("Speed control failed")
			return
		_reset()
		if simulation_time != 0.0 or mode != "overhead" or paused or time_speed != 1.0:
			_fail("Reset control failed")
			return
		_update_residents()
		if not asset_loaded or asset_mesh_count == 0 or crowd.batches.size() != 7:
			_fail("Actual GLB and seven resident part batches must be loaded")
			return
		_set_mode("walk")
		_update_residents()
		if crowd.animated_count <= 0 or crowd.animated_count > 300:
			_fail("Near-camera gait selection must respect the 300-person limit")
			return
		var gait_before: float = float(get_comparison_state().sampleGaitAngle)
		simulation_time += 0.1
		_update_residents()
		if float(get_comparison_state().sampleGaitAngle) == gait_before:
			_fail("Submitted near-person gait must advance")
			return
		simulation_time = 0.0
		if absf(_walking_eye_height(Vector3(0, 0, 10)) - 2.28) > 0.001 or absf(_walking_eye_height(Vector3(0, 0, -4)) - 4.2) > 0.001:
			_fail("Shared staircase ramp eye height differs")
			return
		_set_mode("overhead")
		_update_residents()
		var original_population: int = population
		var original_camera: Vector3 = camera.position
		_set_population(1000 if original_population == 200 else 200)
		if simulation_time != 0.0 or camera.position.distance_to(original_camera) > 0.001 or resident_nodes.size() != population:
			_fail("Population control must preserve time/camera and update all identities")
			return
		_set_population(original_population)
		print("GODOT_COMPARISON_SMOKE_OK " + JSON.stringify(get_comparison_state()))
	if not screenshot_path.is_empty():
		if DisplayServer.get_name() == "headless":
			_fail("Screenshots require a rendered run; omit --headless")
			return
		_reset()
		_update_residents()
		_set_mode(initial_mode)
		_update_hud()
		for frame: int in range(6):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var screenshot: Image = get_viewport().get_texture().get_image()
		if not screenshot_path.get_base_dir().is_empty():
			DirAccess.make_dir_recursive_absolute(screenshot_path.get_base_dir())
		var error: Error = screenshot.save_png(screenshot_path)
		if error != OK:
			_fail("Could not save screenshot: " + error_string(error))
			return
		print("GODOT_COMPARISON_SCREENSHOT " + screenshot_path)
	get_tree().quit(0)
