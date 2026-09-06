extends Node3D
## Optional derived visual data. Source hashes bind every roof and silhouette.
const Builder = preload("res://geography_mesh.gd")
var available: bool = false
var last_error: String = ""
var directory: String = ""
var descriptors: Dictionary = {}
var loaded: Dictionary = {}
var pending: Array[String] = []
var terrain: Node3D
var landmark_ids: Dictionary = {}
var pilot_enabled: bool = true
var last_focus := Vector3(INF,INF,INF)
var material: ShaderMaterial
var box_mesh: BoxMesh
var silhouette_count: int = 0
var roof_count: int = 0
var use_context: RefCounted

func initialize(geography_path: String) -> void:
	directory = ProjectSettings.globalize_path(geography_path).get_base_dir().simplify_path()
	var path: String = directory.path_join("visual-index.json")
	if not FileAccess.file_exists(path): return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or not parsed.get("tiles") is Array:
		last_error = "Optional city visual index is invalid."
		return
	var geography: Variant = JSON.parse_string(FileAccess.get_file_as_string(geography_path))
	if not geography is Dictionary or str(parsed.get("geography_sha256","")) != str(geography.get("sha256","")) or str(parsed.get("geography_file_sha256","")) != FileAccess.get_sha256(geography_path):
		last_error = "City visual index does not match the installed geography."
		return
	for descriptor: Dictionary in parsed.tiles:
		var identity: String = str(descriptor.get("id",""))
		if identity.is_empty(): continue
		descriptors[identity] = descriptor
		pending.append(identity)
	if use_context == null: use_context = preload("res://geography_use.gd").new()
	material = use_context.make_material(true)
	box_mesh = BoxMesh.new()
	box_mesh.size = Vector3.ONE
	available = true

func set_pilot_mode(enabled: bool) -> void:
	if pilot_enabled == enabled: return
	pilot_enabled = enabled
	for record: Dictionary in loaded.values():
		if record.get("mesh") != null: record.mesh.queue_free()
	loaded.clear()
	pending.assign(descriptors.keys())
	silhouette_count = 0
	roof_count = 0
	last_focus = Vector3(INF,INF,INF)

func update_view(focus: Vector3, detailed_tiles: Dictionary, refresh_visibility: bool = true) -> void:
	if not available: return
	if last_focus.distance_squared_to(focus) > 250000.0:
		last_focus = focus
		pending.sort_custom(func(a: String,b: String) -> bool: return _distance(a,focus) < _distance(b,focus))
	if not pending.is_empty():
		_load_tile(pending.pop_front())
		refresh_visibility = true
	if not refresh_visibility: return
	for identity: String in loaded:
		var mesh: MultiMeshInstance3D = loaded[identity].get("mesh")
		if mesh == null: continue
		var replaced: bool = false
		if detailed_tiles.has(identity):
			var detail: Dictionary = detailed_tiles[identity]
			replaced = detail.root.visible and detail.high != null and detail.high.visible
		mesh.visible = not replaced

func _distance(identity: String, focus: Vector3) -> float:
	var bounds: Dictionary = descriptors[identity].get("bounds",{})
	if bounds.is_empty(): return INF
	var east: float = clampf(focus.x,float(bounds.min[0]),float(bounds.max[0]))
	var north: float = clampf(-focus.z,float(bounds.min[1]),float(bounds.max[1]))
	return Vector2(east-focus.x,north+focus.z).length_squared()

func _load_tile(identity: String) -> void:
	if loaded.has(identity) or not descriptors.has(identity): return
	var descriptor: Dictionary = descriptors[identity]
	var relative: String = str(descriptor.get("path",""))
	var path: String = directory.path_join(relative).simplify_path()
	if relative.is_absolute_path() or not path.replace("\\","/").begins_with(directory.replace("\\","/").trim_suffix("/")+"/"):
		last_error = "City visual tile path escaped its manifest directory."
		loaded[identity] = {}
		return
	if not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(descriptor.get("sha256","")):
		last_error = "City visual tile is missing or does not match its checksum: " + identity
		loaded[identity] = {}
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1:
		last_error = "City visual tile is invalid: " + identity
		loaded[identity] = {}
		return
	var roofs: Dictionary = {}
	for roof: Dictionary in parsed.get("roofs",[]): roofs[str(roof.get("id",""))] = roof
	roof_count += roofs.size()
	var transforms: Array[Transform3D] = []
	var categories := PackedInt32Array()
	use_context.load_colors(identity)
	for row: Array in parsed.get("silhouettes",[]):
		if row.size() != 7 or landmark_ids.has(str(row[0])): continue
		var east: float = float(row[1])
		var north: float = float(row[2])
		if pilot_enabled and absf(east) <= 205.0 and absf(north) <= 185.0: continue
		var height_value: float = clampf(float(row[5]),0.25,600.0)
		var elevation: Variant = terrain.display_height_at(east,north) if terrain != null and terrain.available else 0.0
		if elevation == null: continue
		var size_value := Vector3(clampf(float(row[3]),0.25,1000.0),height_value,clampf(float(row[4]),0.25,1000.0))
		var basis_value: Basis = Basis(Vector3.UP,float(row[6])) * Basis.from_scale(size_value)
		transforms.append(Transform3D(basis_value,Vector3(east,float(elevation)+height_value*0.5,-north)))
		categories.append(use_context.category_index(str(row[0])))
	var instance: MultiMeshInstance3D
	if not transforms.is_empty():
		var batch := MultiMesh.new()
		batch.transform_format = MultiMesh.TRANSFORM_3D
		batch.use_custom_data = true
		batch.mesh = box_mesh
		batch.instance_count = transforms.size()
		for i: int in range(transforms.size()):
			batch.set_instance_transform(i,transforms[i])
			batch.set_instance_custom_data(i,Color(float(categories[i]),0.0,0.0,0.0))
		instance = MultiMeshInstance3D.new()
		instance.name = "CitySilhouette-" + identity.validate_node_name()
		instance.multimesh = batch
		instance.material_override = material
		instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(instance)
	loaded[identity] = {"roofs":roofs,"mesh":instance}
	silhouette_count += transforms.size()

func enrich_building(source: Dictionary, tile_id: String) -> Dictionary:
	if not available: return source
	if not loaded.has(tile_id):
		pending.erase(tile_id)
		_load_tile(tile_id)
	var roof: Dictionary = loaded.get(tile_id,{}).get("roofs",{}).get(str(source.get("id","")),{})
	if roof.is_empty(): return source
	var enhanced: Dictionary = source.duplicate(false)
	enhanced["roof_vertices"] = roof.get("roof_vertices",[])
	enhanced["roof_triangles"] = roof.get("roof_triangles",[])
	return enhanced

func get_state() -> Dictionary:
	return {"available":available,"loaded_tiles":loaded.size(),"pending_tiles":pending.size(),"silhouette_count":silhouette_count,"roof_count":roof_count,"error":last_error}
