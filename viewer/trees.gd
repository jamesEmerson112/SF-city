extends Node3D
## Checked street-tree points; original silhouettes, without simulation collisions.
const CACHE_LIMIT: int = 24
const CACHE_TREE_LIMIT: int = 12000
const DISPLAY_LIMIT: int = 6000
const RADIUS: float = 850.0
const MAX_TILE_BYTES: int = 2*1024*1024
const SHAPES: Array[String] = ["broadleaf","conifer","palm"]
var terrain: Node3D
var available: bool = false
var enabled: bool = true
var pilot_enabled: bool = true
var last_error: String = ""
var manifest: Dictionary = {}
var directory: String = ""
var descriptors: Dictionary = {}
var loaded: Dictionary = {}
var failed: Dictionary = {}
var pending: Array[String] = []
var wanted: Array[String] = []
var meshes: Dictionary = {}
var material: ShaderMaterial
var cached_count: int = 0
var displayed_count: int = 0
var missing_terrain_count: int = 0
var duplicate_count: int = 0
var last_focus := Vector3(INF,INF,INF)
var last_zoom: float = -1.0
var refresh_elapsed: float = 1.0
var stamp: int = 0

func initialize(geography_path: String) -> bool:
	_clear_cache()
	available = false
	last_error = ""
	descriptors.clear()
	manifest.clear()
	directory = ProjectSettings.globalize_path(geography_path).get_base_dir().simplify_path()
	var path: String = directory.path_join("tree-index.json")
	if not FileAccess.file_exists(path): return false
	var parsed: Variant = _read_json(path,2*1024*1024)
	if not parsed is Dictionary or not _valid_index(parsed): return _error("The optional street-tree index has invalid or incomplete source metadata.")
	var geography: Variant = JSON.parse_string(FileAccess.get_file_as_string(geography_path))
	if not geography is Dictionary or str(parsed.get("geography_sha256","")) != str(geography.get("sha256","")) or str(parsed.get("geography_file_sha256","")) != FileAccess.get_sha256(geography_path): return _error("Street-tree data does not match the installed geography.")
	var checked: Dictionary = {}
	for item: Variant in parsed.tiles:
		if not item is Dictionary or not item.get("id") is String or checked.has(item.id) or str(item.id).is_empty() or not _valid_bounds(item.get("bounds")) or not _valid_count(item.get("tree_count"),2000) or not _valid_relative(item.get("path")) or not _valid_hash(item.get("sha256")): return _error("Street-tree tile descriptors exceed their bounds or omit integrity metadata.")
		checked[item.id] = item
	manifest = parsed
	descriptors = checked
	material = ShaderMaterial.new()
	material.shader = preload("res://trees.gdshader")
	for shape: String in SHAPES: meshes[shape] = preload("res://tree_geometry.gd").create_mesh(shape)
	available = true
	return true

func _valid_index(data: Dictionary) -> bool:
	if int(data.get("schema_version",0)) != 1 or int(data.get("tile_size_m",0)) != 500 or not data.get("tiles") is Array or data.tiles.size() > 1024: return false
	var source: Variant = data.get("source")
	if not source is Dictionary or str(source.get("id","")) != "uzd4-f6yf" or not str(source.get("url","")).begins_with("https://data.sfgov.org/") or not _valid_hash(source.get("metadata_sha256")): return false
	if not source.get("license") is Dictionary or not _text(source.get("title"),false) or not _text(source.get("observation_note"),false) or not _text(data.get("display_note"),false): return false
	return data.get("statistics") is Dictionary and _valid_hash(data.get("geography_sha256")) and _valid_hash(data.get("geography_file_sha256"))

func set_enabled(value: bool) -> void:
	enabled = value
	visible = value
	last_focus = Vector3(INF,INF,INF)
	if not value:
		pending.clear()
		displayed_count = 0

func set_pilot_mode(value: bool) -> void:
	if pilot_enabled == value: return
	pilot_enabled = value
	_clear_cache()

func update_view(focus: Vector3, zoom: float, delta: float) -> void:
	if not available or not enabled: return
	refresh_elapsed += delta
	var refresh: bool = refresh_elapsed >= 0.25 and (last_focus.distance_squared_to(focus) > 625.0 or absf(last_zoom-zoom) > 25.0)
	if refresh:
		refresh_elapsed = 0.0
		last_focus = focus
		last_zoom = zoom
		wanted.clear()
		pending.clear()
		if zoom < 1600.0:
			for identity: String in descriptors:
				if _distance_squared(descriptors[identity].bounds,focus) <= RADIUS*RADIUS: wanted.append(identity)
			wanted.sort_custom(func(a: String,b: String) -> bool: return _distance_squared(descriptors[a].bounds,focus) < _distance_squared(descriptors[b].bounds,focus))
			if wanted.size() > CACHE_LIMIT: wanted.resize(CACHE_LIMIT)
			var bounded: Array[String] = []
			var tree_budget: int = 0
			for identity: String in wanted:
				var count: int = int(descriptors[identity].tree_count)
				if tree_budget+count > CACHE_TREE_LIMIT: continue
				tree_budget += count
				bounded.append(identity)
			wanted = bounded
			for identity: String in wanted:
				if not loaded.has(identity) and not failed.has(identity): pending.append(identity)
	if not pending.is_empty():
		_load_tile(pending.pop_front())
		refresh = true
	if refresh: _update_visibility()

func _update_visibility() -> void:
	displayed_count = 0
	for tile: Dictionary in loaded.values():
		for instance: MultiMeshInstance3D in tile.instances: instance.visible = false
	for identity: String in wanted:
		if not loaded.has(identity): continue
		stamp += 1
		loaded[identity].stamp = stamp
		for instance: MultiMeshInstance3D in loaded[identity].instances:
			var count: int = mini(instance.multimesh.instance_count,DISPLAY_LIMIT-displayed_count)
			instance.multimesh.visible_instance_count = count
			instance.visible = count > 0
			displayed_count += count

func _load_tile(identity: String) -> void:
	if loaded.has(identity) or failed.has(identity): return
	var descriptor: Dictionary = descriptors[identity]
	var path: String = directory.path_join(str(descriptor.path)).simplify_path()
	if not path.replace("\\","/").begins_with(directory.replace("\\","/").trim_suffix("/")+"/") or not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(descriptor.sha256):
		_reject(identity,"Street-tree tile is missing or has an invalid checksum: "+identity)
		return
	var parsed: Variant = _read_json(path,MAX_TILE_BYTES)
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or str(parsed.get("tile_id","")) != identity or not parsed.get("trees") is Array or parsed.trees.size() != int(descriptor.tree_count):
		_reject(identity,"Street-tree tile has an invalid record count or identity: "+identity)
		return
	var identities: Dictionary = {}
	for record: Variant in parsed.trees:
		if not record is Dictionary or not valid_record(record,descriptor.bounds) or identities.has(str(record.id)):
			_reject(identity,"Street-tree tile contains invalid coordinates, IDs or display metadata: "+identity)
			return
		identities[str(record.id)] = true
	var records: Array = parsed.trees.duplicate(false)
	records.sort_custom(func(a: Dictionary,b: Dictionary) -> bool: return str(a.id).naturalnocasecmp_to(str(b.id)) < 0)
	var positions: Dictionary = {}
	var by_shape: Dictionary = {"broadleaf":[],"conifer":[],"palm":[]}
	var missing: int = 0
	var duplicates: int = 0
	var count: int = 0
	for record: Dictionary in records:
		var position_key: String = JSON.stringify(record.position.slice(0,2))
		if positions.has(position_key):
			duplicates += 1
			continue
		positions[position_key] = true
		var east: float = float(record.position[0])
		var north: float = float(record.position[1])
		if pilot_enabled and absf(east) <= 205.0 and absf(north) <= 185.0: continue
		var elevation: Variant = terrain.display_height_at(east,north) if terrain != null and terrain.available else null
		if elevation == null:
			missing += 1
			continue
		var display: Dictionary = record.display
		var dimensions := Vector3(float(display.canopy_width_m),float(display.height_m),float(display.canopy_width_m))
		var transform_value := Transform3D(Basis(Vector3.UP,deg_to_rad(float(display.rotation_degrees)))*Basis.from_scale(dimensions),Vector3(east,float(elevation),-north))
		by_shape[str(display.shape)].append({"id":str(record.id),"transform":transform_value,"tint":int(display.tint_variant)})
		count += 1
	while loaded.size() >= CACHE_LIMIT or cached_count+count > CACHE_TREE_LIMIT:
		if not _evict_one(): break
	if cached_count+count > CACHE_TREE_LIMIT:
		_reject(identity,"Nearby street-tree cache reached its bounded instance budget.")
		return
	var instances: Array[MultiMeshInstance3D] = []
	for shape: String in SHAPES:
		var trees: Array = by_shape[shape]
		if trees.is_empty(): continue
		var batch := MultiMesh.new()
		batch.transform_format = MultiMesh.TRANSFORM_3D
		batch.use_colors = true
		batch.use_custom_data = true
		batch.mesh = meshes[shape]
		batch.instance_count = trees.size()
		for i: int in range(trees.size()):
			batch.set_instance_transform(i,trees[i].transform)
			batch.set_instance_color(i,Color.WHITE)
			batch.set_instance_custom_data(i,Color(float(trees[i].tint),0,0,0))
		var instance := MultiMeshInstance3D.new()
		instance.name = "StreetTrees-"+identity.validate_node_name()+"-"+shape
		instance.multimesh = batch
		instance.material_override = material
		instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(instance)
		instances.append(instance)
	stamp += 1
	loaded[identity] = {"instances":instances,"count":count,"missing":missing,"duplicates":duplicates,"stamp":stamp,"by_shape":by_shape}
	cached_count += count
	missing_terrain_count += missing
	duplicate_count += duplicates

func _evict_one() -> bool:
	var candidate: String = ""
	var oldest: int = 9223372036854775807
	for identity: String in loaded:
		if identity in wanted: continue
		if int(loaded[identity].stamp) < oldest:
			oldest = int(loaded[identity].stamp)
			candidate = identity
	if candidate.is_empty(): return false
	var tile: Dictionary = loaded[candidate]
	for instance: MultiMeshInstance3D in tile.instances: instance.free()
	cached_count -= int(tile.count)
	missing_terrain_count -= int(tile.missing)
	duplicate_count -= int(tile.duplicates)
	loaded.erase(candidate)
	return true

func _clear_cache() -> void:
	for tile: Dictionary in loaded.values():
		for instance: MultiMeshInstance3D in tile.instances: instance.free()
	loaded.clear()
	failed.clear()
	pending.clear()
	wanted.clear()
	cached_count = 0
	displayed_count = 0
	missing_terrain_count = 0
	duplicate_count = 0
	last_focus = Vector3(INF,INF,INF)
	last_zoom = -1.0

func _reject(identity: String, message: String) -> void:
	failed[identity] = true
	last_error = message

func _error(message: String) -> bool:
	last_error = message
	return false

static func valid_record(record: Dictionary, bounds: Dictionary) -> bool:
	if not record.get("id") is String or not str(record.id).begins_with("sf-tree:") or str(record.id).length() > 64: return false
	var source_id: String = str(record.id).trim_prefix("sf-tree:")
	if not source_id.is_valid_int() or source_id.to_int() <= 0: return false
	var position: Variant = record.get("position")
	if not position is Array or position.size() != 3: return false
	for coordinate: Variant in position:
		if not _number(coordinate) or absf(float(coordinate)) > 100000.0: return false
	if float(position[2]) != 0.0: return false
	for axis: int in range(2):
		if float(position[axis]) < float(bounds.min[axis])-0.00001 or float(position[axis]) > float(bounds.max[axis])+0.00001: return false
	if str(record.get("planttype","")).to_lower() != "tree" or str(record.get("dbh_source_units","")) != "not stated in source metadata": return false
	for field: String in ["species","siteinfo","planteddate","data_as_of","data_loaded_at"]:
		if not _text(record.get(field),true): return false
	var dbh: Variant = record.get("dbh_source_value")
	if dbh != null and (not _number(dbh) or float(dbh) < 0.0): return false
	var display: Variant = record.get("display")
	if not display is Dictionary or str(display.get("source","")) != "illustrative-v1" or str(display.get("shape","")) not in SHAPES: return false
	for field: String in ["height_m","canopy_width_m","rotation_degrees","tint_variant"]:
		if not _number(display.get(field)): return false
	return float(display.height_m) >= 6.0 and float(display.height_m) <= 13.0 and float(display.canopy_width_m) >= 4.0 and float(display.canopy_width_m) <= 6.0 and float(display.rotation_degrees) >= 0.0 and float(display.rotation_degrees) <= 360.0 and _valid_count(display.tint_variant,3)

static func _number(value: Variant) -> bool:
	return (value is int or value is float) and is_finite(float(value))

static func _text(value: Variant, nullable: bool) -> bool:
	return (value == null and nullable) or (value is String and str(value).length() <= 2048 and (nullable or not str(value).is_empty()))

static func _valid_count(value: Variant, maximum: int) -> bool:
	return _number(value) and float(value) == floorf(float(value)) and float(value) >= 0.0 and float(value) <= maximum

static func _valid_hash(value: Variant) -> bool:
	return value is String and str(value).length() == 64 and str(value).is_valid_hex_number(false)

static func _valid_bounds(value: Variant) -> bool:
	if not value is Dictionary or not value.get("min") is Array or not value.get("max") is Array or value.min.size() != 2 or value.max.size() != 2: return false
	for axis: int in range(2):
		if not _number(value.min[axis]) or not _number(value.max[axis]) or float(value.min[axis]) > float(value.max[axis]) or absf(float(value.min[axis])) > 100000.0 or absf(float(value.max[axis])) > 100000.0: return false
	return true

static func _valid_relative(value: Variant) -> bool:
	return value is String and not str(value).is_empty() and not str(value).is_absolute_path() and not ":" in value and not "\\" in value and not ".." in str(value).split("/")

static func _read_json(path: String, maximum: int) -> Variant:
	var file := FileAccess.open(path,FileAccess.READ)
	if file == null or file.get_length() > maximum: return null
	return JSON.parse_string(file.get_as_text())

static func _distance_squared(bounds: Dictionary, focus: Vector3) -> float:
	var east: float = clampf(focus.x,float(bounds.min[0]),float(bounds.max[0]))
	var north: float = clampf(-focus.z,float(bounds.min[1]),float(bounds.max[1]))
	return Vector2(east-focus.x,north+focus.z).length_squared()

func get_state() -> Dictionary:
	return {"available":available,"enabled":enabled,"loaded_tiles":loaded.size(),"pending_tiles":pending.size(),"cached_instances":cached_count,"displayed_instances":displayed_count,"display_limit":DISPLAY_LIMIT,"missing_terrain":missing_terrain_count,"coincident_records_suppressed_in_cache":duplicate_count,"statistics":manifest.get("statistics",{}),"source":manifest.get("source",{}).get("url",""),"display_note":manifest.get("display_note",""),"error":last_error}
