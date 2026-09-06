extends Node3D
## Loads the authored local asset; simulation data never comes from the visual fixture.
var fixture: Dictionary = {}
var asset_loaded: bool = false
var asset_mesh_count: int = 0
var selectable_nodes: Dictionary = {}
var last_error: String = ""
var original_materials: Dictionary = {}
var detailed_block: Node3D
var pilot_visible: bool = true
var landmarks: Node3D
var environment_resource: Environment
var daylight_sun: DirectionalLight3D

func initialize_landmarks(terrain: Node3D) -> void:
	landmarks = preload("res://landmarks.gd").new()
	add_child(landmarks)
	landmarks.initialize(terrain)
	for identifier: String in landmarks.selectable:
		selectable_nodes[identifier] = landmarks.selectable[identifier]
	landmarks.set_enabled(not pilot_visible)

func set_pilot_visible(enabled: bool) -> void:
	if landmarks != null: landmarks.set_enabled(not enabled)
	if pilot_visible == enabled: return
	pilot_visible = enabled
	if detailed_block != null:
		detailed_block.visible = enabled
		for body: StaticBody3D in detailed_block.find_children("*","StaticBody3D",true,false): body.collision_layer = 1 if enabled else 0

func initialize(visual: Dictionary) -> bool:
	fixture = visual
	_build_environment()
	return _load_asset(ProjectSettings.globalize_path("res://assets"))

func _fail(message: String) -> void:
	last_error = message
	push_error(message)

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
	detailed_block = imported as Node3D
	var metadata: Dictionary = {}
	for item: Dictionary in state.json.get("nodes", []):
		if item.get("extras", {}).has("id"):
			metadata[str(item.get("name", "")).validate_node_name()] = item.extras
	for mesh: MeshInstance3D in imported.find_children("*", "MeshInstance3D", true, false):
		asset_mesh_count += 1
		# The architectural study used near-white display colors. Moderate those
		# reflectances for daylight while retaining every authored material role.
		var source_material: Material = mesh.mesh.surface_get_material(0)
		if source_material is StandardMaterial3D:
			var daylight_material: StandardMaterial3D = source_material.duplicate()
			var brightness: float = maxf(daylight_material.albedo_color.r,maxf(daylight_material.albedo_color.g,daylight_material.albedo_color.b))
			if brightness > 0.72 and daylight_material.metallic < 0.5:
				daylight_material.albedo_color = daylight_material.albedo_color.darkened(0.17)
			mesh.material_override = daylight_material
			original_materials[mesh] = daylight_material
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

func _build_environment() -> void:
	var world := WorldEnvironment.new()
	var environment := Environment.new()
	environment_resource = environment
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
	environment.ambient_light_energy = 0.24
	environment.ambient_light_sky_contribution = 0.0
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	world.environment = environment
	add_child(world)
	var sunlight := DirectionalLight3D.new()
	daylight_sun = sunlight
	sunlight.name = "DaylightSun"
	sunlight.rotation_degrees = Vector3(-48.0, -35.0, 0.0)
	sunlight.light_color = Color("fff8ed")
	sunlight.light_energy = 0.48
	sunlight.shadow_enabled = true
	sunlight.directional_shadow_max_distance = 900.0
	add_child(sunlight)

func highlight(previous: String, selected: String) -> void:
	for identifier: String in [previous, selected]:
		for mesh: MeshInstance3D in selectable_nodes.get(identifier, []):
			if identifier == selected:
				var source: Material = original_materials.get(mesh,mesh.mesh.surface_get_material(0))
				if source is StandardMaterial3D:
					var material: StandardMaterial3D = source.duplicate()
					material.emission_enabled = true
					material.emission = Color(0.2, 0.13, 0.02)
					mesh.material_override = material
			else:
				mesh.material_override = original_materials.get(mesh)
