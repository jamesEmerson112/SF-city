extends SceneTree
const Trees = preload("res://trees.gd")
var failures: Array[String] = []

class Ground extends Node3D:
	var available: bool = true
	func display_height_at(east: float,north: float) -> Variant:
		return null if north == 999.0 else 5.0+east*0.01

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	_check_geometry()
	_check_record_validation()
	_check_fixture()
	_check_actual_cache()
	if failures.is_empty():
		print("GODOT_TREES_TESTS_OK original bounded meshes, finite/source metadata, checked files, exact-coordinate deduplication, shared terrain, pilot exclusion, cache/display limits, toggle lifecycle")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _record(identity: int, east: float = 0.0, north: float = 0.0) -> Dictionary:
	return {"id":"sf-tree:%d" % identity,"position":[east,north,0.0],"species":"Fixture tree","planttype":"Tree","siteinfo":null,"planteddate":null,"data_as_of":"2026-09-05","data_loaded_at":"2026-09-06","dbh_source_value":10.0,"dbh_source_units":"not stated in source metadata","display":{"source":"illustrative-v1","shape":"broadleaf","height_m":8.0,"canopy_width_m":5.0,"rotation_degrees":30.0,"tint_variant":2}}

func _check_geometry() -> void:
	for shape: String in Trees.SHAPES:
		var mesh: ArrayMesh = preload("res://tree_geometry.gd").create_mesh(shape)
		var bounds: AABB = mesh.get_aabb()
		if bounds.position.y != 0.0 or absf(bounds.end.y-1.0) > 0.0001 or absf(bounds.size.x-1.0) > 0.0001 or absf(bounds.size.z-1.0) > 0.0001: failures.append("Original tree geometry did not retain its declared unit height/width: "+shape)
		var arrays: Array = mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		if vertices.size() > 360: failures.append("Original tree mesh exceeded 120 triangles: "+shape)
		for vertex: Vector3 in vertices:
			if not vertex.is_finite(): failures.append("Tree mesh contains a nonfinite vertex."); break

func _check_record_validation() -> void:
	var bounds: Dictionary = {"min":[-100,-100],"max":[100,100]}
	var original: Dictionary = _record(1)
	if not Trees.valid_record(original,bounds): failures.append("Valid source/display fixture was rejected.")
	for key: String in ["height_m","canopy_width_m","rotation_degrees","tint_variant"]:
		var invalid: Dictionary = original.duplicate(true)
		invalid.display[key] = NAN
		if Trees.valid_record(invalid,bounds): failures.append("Nonfinite display metadata was accepted.")
	for key: String in ["position","id","planttype","dbh_source_units","species"]:
		var invalid: Dictionary = original.duplicate(true)
		invalid[key] = {"position":[INF,0,0],"id":"sf-tree:invalid","planttype":"Planting Site","dbh_source_units":"inches","species":"x".repeat(3000)}[key]
		if Trees.valid_record(invalid,bounds): failures.append("Invalid source metadata was accepted: "+key)
	for values: Dictionary in [{"source":"measured"},{"height_m":40.0},{"canopy_width_m":-1.0},{"shape":"unknown"},{"tint_variant":1.5},{"height_m":true}]:
		var invalid: Dictionary = original.duplicate(true)
		invalid.display.merge(values,true)
		if Trees.valid_record(invalid,bounds): failures.append("Display metadata escaped its explicit illustrative bounds.")

func _check_fixture() -> void:
	var directory: String = ProjectSettings.globalize_path("res://../.cache/viewer-tree-tests")
	DirAccess.make_dir_recursive_absolute(directory)
	var geography_path: String = directory.path_join("sf-geography.json")
	_write(geography_path,{"sha256":"f".repeat(64)})
	var records: Array = [_record(12),_record(2),_record(3,10.0),_record(4,20.0,999.0)]
	_write(directory.path_join("tile.json"),{"schema_version":1,"tile_id":"0_0","trees":records})
	var descriptor: Dictionary = {"id":"0_0","path":"tile.json","sha256":FileAccess.get_sha256(directory.path_join("tile.json")),"tree_count":records.size(),"bounds":{"min":[0,0],"max":[20,999]}}
	var manifest: Dictionary = {"schema_version":1,"tile_size_m":500,"geography_sha256":"f".repeat(64),"geography_file_sha256":FileAccess.get_sha256(geography_path),"source":{"id":"uzd4-f6yf","url":"https://data.sfgov.org/d/uzd4-f6yf","title":"Test inventory","license":{"name":"PDDL"},"metadata_sha256":"a".repeat(64),"observation_note":"Source points, not complete park coverage."},"display_note":"All shape and dimensions are illustrative.","statistics":{},"tiles":[descriptor]}
	_write(directory.path_join("tree-index.json"),manifest)
	var terrain := Ground.new()
	root.add_child(terrain)
	var forest = Trees.new()
	forest.terrain = terrain
	root.add_child(forest)
	forest.set_pilot_mode(false)
	if not forest.initialize(geography_path): failures.append("Checked source fixture failed: "+forest.last_error)
	forest._load_tile("0_0")
	if forest.cached_count != 2 or forest.duplicate_count != 1 or forest.missing_terrain_count != 1: failures.append("Coincident sources or missing terrain produced invented/overlapping trees.")
	if forest.loaded.has("0_0"):
		for instance: MultiMeshInstance3D in forest.loaded["0_0"].instances:
			if not instance.multimesh.use_colors or not instance.multimesh.use_custom_data: failures.append("Tree buffers omitted colors or illustrative tint attributes.")
		var trees: Array = forest.loaded["0_0"].by_shape.broadleaf
		if trees[0].id != "sf-tree:2": failures.append("Coincident source coordinates did not select the lowest stable numeric ID.")
		for item: Dictionary in trees:
			if absf(item.transform.origin.y-(5.0+item.transform.origin.x*0.01)) > 0.0001: failures.append("Tree base did not use the shared terrain surface.")
		forest.wanted.assign(["0_0"])
		forest._update_visibility()
		forest.set_enabled(false)
		if forest.visible or forest.displayed_count != 0 or not forest.pending.is_empty(): failures.append("Tree toggle left visible instances or pending loading.")
	forest.set_pilot_mode(true)
	forest._load_tile("0_0")
	if forest.cached_count != 0: failures.append("Source trees duplicated the authored pilot footprint.")
	forest.set_pilot_mode(false)
	forest.descriptors["0_0"].sha256 = "0".repeat(64)
	forest._load_tile("0_0")
	if not forest.loaded.is_empty() or forest.last_error.is_empty(): failures.append("Corrupt tree tile checksum was accepted.")
	for path: String in ["../tile.json","C:/tile.json","folder\\tile.json"]:
		var invalid: Dictionary = manifest.duplicate(true)
		invalid.tiles[0].path = path
		_write(directory.path_join("tree-index.json"),invalid)
		if forest.initialize(geography_path) or forest.available: failures.append("Tree tile path escaped its checked data directory.")
	var invalid_source: Dictionary = manifest.duplicate(true)
	invalid_source.source.id = "historical-dataset"
	_write(directory.path_join("tree-index.json"),invalid_source)
	if forest.initialize(geography_path): failures.append("Historical/unknown source metadata was accepted.")
	forest.free()
	terrain.free()

func _check_actual_cache() -> void:
	var path: String = ProjectSettings.globalize_path("res://../.local/civic/geography/sf-geography.json")
	if not FileAccess.file_exists(path.get_base_dir().path_join("tree-index.json")): return
	var ground := Ground.new()
	root.add_child(ground)
	var forest = Trees.new()
	forest.terrain = ground
	root.add_child(forest)
	forest.set_pilot_mode(false)
	if not forest.initialize(path): failures.append("Installed tree data failed source integrity: "+forest.last_error)
	var sorted: Array = forest.descriptors.keys()
	sorted.sort_custom(func(a: String,b: String) -> bool: return int(forest.descriptors[a].tree_count) > int(forest.descriptors[b].tree_count))
	for identity: String in sorted.slice(0,32):
		forest._load_tile(identity)
		if forest.loaded.size() > forest.CACHE_LIMIT or forest.cached_count > forest.CACHE_TREE_LIMIT: failures.append("Actual source tile loading exceeded the bounded cache.")
	forest.wanted.assign(forest.loaded.keys())
	forest._update_visibility()
	if forest.displayed_count != forest.DISPLAY_LIMIT: failures.append("Actual dense inventory did not respect the 6,000-instance display cap.")
	if not forest.last_error.is_empty(): failures.append("Actual tree cache rejected valid normalized source data: "+forest.last_error)
	forest._clear_cache()
	for identity: String in sorted.slice(-32): forest._load_tile(identity)
	if forest.loaded.size() != forest.CACHE_LIMIT or forest.cached_count > forest.CACHE_TREE_LIMIT: failures.append("Sparse source tiles did not evict at the 24-tile cache limit.")
	forest.free()
	ground.free()

func _write(path: String, value: Dictionary) -> void:
	var file := FileAccess.open(path,FileAccess.WRITE)
	file.store_string(JSON.stringify(value))
	file.close()
