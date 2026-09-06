extends SceneTree
const Cache = preload("res://scenery_cache.gd")
const Builder = preload("res://geography_mesh.gd")
const Geography = preload("res://geography.gd")
const Terrain = preload("res://terrain.gd")
var failures: Array[String] = []
var directory: String = ""

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool,message: String) -> void:
	if not condition: failures.append(message)

func _run() -> void:
	directory = "res://../.cache/scenery-cache-tests-" + str(OS.get_process_id()) + "-" + str(Time.get_ticks_usec())
	_test_binary_cache()
	_test_geography()
	if failures.is_empty():
		print("GODOT_SCENERY_CACHE_TESTS_OK cold/hot arrays, canonical identity, source dependencies, terrain/pilot/landmarks, courtyard picking, corrupt/truncated/unwritable fallback, finite geometry")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _test_binary_cache() -> void:
	var cache = Cache.new()
	_check(not cache.enabled and cache.directory.is_empty(),"Scenery cache must remain opt-in for standalone renderers.")
	cache.configure(directory.path_join("helper"))
	cache.enabled = true
	var identity: Dictionary = {"kind":"test","source":{"z":3,"a":1}}
	_check(cache.read_entry(identity).is_empty(),"A new cache should miss.")
	var builder = Builder.new(Vector3(3,4,5))
	builder.triangle(Vector3.ZERO,Vector3.RIGHT,Vector3.FORWARD,Color.CORNFLOWER_BLUE)
	var payload: Dictionary = builder.array_payload()
	_check(cache.write_entry(identity,payload),"Could not save prepared triangle arrays.")
	var restored: Dictionary = cache.read_entry({"source":{"a":1,"z":3},"kind":"test"})
	_check(Cache.value_digest(restored) == Cache.value_digest(payload),"Packed triangle arrays did not round-trip exactly.")
	var copy = Builder.new()
	_check(copy.apply_array_payload(restored),"Round-tripped packed arrays were rejected.")
	_check(copy.origin == builder.origin and copy.vertices == builder.vertices,"Cached mesh placement or vertices changed.")
	var empty_builder = Builder.new()
	_check(copy.apply_array_payload(empty_builder.array_payload()) and copy.vertices.is_empty(),"Valid empty geometry was not restored.")

	_check(cache.read_entry({"kind":"test","source":{"z":4,"a":1}}).is_empty(),"Changed dependencies reused a stale entry.")
	var malformed: Dictionary = payload.duplicate(true)
	malformed["normals"] = PackedVector3Array()
	_check(not copy.apply_array_payload(malformed),"Mismatched packed array lengths were accepted.")
	malformed = payload.duplicate(true)
	malformed.vertices[0] = Vector3(NAN,0,0)
	_check(not copy.apply_array_payload(malformed),"Non-finite prepared mesh vertices were accepted.")
	for bad: Variant in [{"unexpected":1},[1],"1",1.0,true,null]:
		malformed = payload.duplicate(true)
		malformed["triangle_count"] = bad
		_check(not copy.apply_array_payload(malformed),"A malformed triangle count was cast before validation.")

	var node := Node.new()
	_check(not cache.write_entry({"kind":"object"},{"node":node}),"Executable object payload was accepted.")
	node.free()
	var file := FileAccess.open(cache.entry_path(identity),FileAccess.READ_WRITE)
	file.seek(file.get_length()-1)
	var value: int = file.get_8()
	file.seek(file.get_length()-1)
	file.store_8(value ^ 255)
	file.close()
	_check(cache.read_entry(identity).is_empty() and cache.errors >= 2,"A corrupted payload did not fail safely.")
	_check(cache.write_entry(identity,payload) and not cache.read_entry(identity).is_empty(),"A corrupt cache could not be atomically replaced.")
	file = FileAccess.open(cache.entry_path(identity),FileAccess.WRITE)
	file.store_buffer(PackedByteArray([83,70]))
	file.close()
	_check(cache.read_entry(identity).is_empty(),"Truncated cache header was accepted.")
	var blocker: String = ProjectSettings.globalize_path(directory).path_join("not-a-directory")
	file = FileAccess.open(blocker,FileAccess.WRITE)
	file.store_string("file")
	file.close()
	cache.configure(blocker)
	_check(not cache.write_entry(identity,payload),"Writing below a regular file should fail without losing generated geometry.")

func _new_geography(cache_path: String,terrain: Node3D = null) -> Node3D:
	var geography = Geography.new()
	geography.terrain = terrain
	geography.configure_render_cache(cache_path)
	root.add_child(geography)
	_check(geography.initialize("res://testdata/geography/manifest.json"),"Geography fixture did not initialize.")
	return geography

func _test_geography() -> void:
	var cache_path: String = directory.path_join("geography")
	var cold = _new_geography(cache_path)
	for identifier: String in cold.tiles.keys(): cold._load_tile(identifier)
	_check(cold.loaded_buildings == 2 and cold.cache_stats().writes == 2,"Cold geography did not prepare both fixture tiles.")
	var signatures: Dictionary = {}
	for identifier: String in cold.tiles:
		var source: String = cold.manifest_directory.path_join(str(cold.tiles[identifier].path))
		var identity: Dictionary = cold._tile_cache_identity(identifier,Cache.file_digest(source))
		signatures[identifier] = Cache.value_digest(cold.render_cache.read_entry(identity))
	var warm = _new_geography(cache_path)
	for identifier: String in warm.tiles.keys(): warm._load_tile(identifier)
	_check(warm.cache_stats().hits == 2 and warm.cache_stats().generated_tiles == 0,"Warm geography rebuilt geometry instead of restoring it.")
	_check(warm.loaded_buildings == cold.loaded_buildings and warm.roofs_omitted_for_holes == cold.roofs_omitted_for_holes,"Cached geography diagnostics differ from fresh geometry.")
	for identifier: String in warm.tiles:
		var source: String = warm.manifest_directory.path_join(str(warm.tiles[identifier].path))
		var identity: Dictionary = warm._tile_cache_identity(identifier,Cache.file_digest(source))
		var payload: Dictionary = warm.render_cache.read_entry(identity)
		_check(Cache.value_digest(payload) == signatures[identifier],"Cached geography arrays or metadata changed.")
		_check(warm.loaded[identifier].picking == cold.loaded[identifier].picking,"Cached picking polygons differ.")
		if warm.loaded[identifier].high != null:
			_check(warm.loaded[identifier].high.material_override == warm.building_material,"Cached meshes did not use current toggleable materials.")
	_check(str(warm.pick(Vector3(610,40,-610),Vector3.DOWN,100).get("source_id","")) == "building-test-a","Prepared building cannot be picked.")
	_check(warm.pick(Vector3(1120,40,-620),Vector3.DOWN,100).is_empty(),"Prepared courtyard was incorrectly filled during picking.")
	_check(warm.blocks_walk(610,610) and not warm.blocks_walk(1120,620),"Prepared walking collision lost the courtyard.")
	var identifier: String = str(warm.tiles.keys()[0])
	var source_path: String = warm.manifest_directory.path_join(str(warm.tiles[identifier].path))
	var source_hash: String = Cache.file_digest(source_path)
	var original_key: String = Cache.value_digest(warm._tile_cache_identity(identifier,source_hash))
	_check(Cache.value_digest(warm._tile_cache_identity(identifier,"changed-source")) != original_key,"Actual source tile bytes do not invalidate cached geometry.")
	warm.set_pilot_mode(false)
	_check(Cache.value_digest(warm._tile_cache_identity(identifier,source_hash)) != original_key,"Pilot exclusions do not invalidate cached geometry.")
	warm.set_pilot_mode(true)
	warm.landmark_records = {"building-test-a":{"id":"landmark-test","base_height":15.0}}
	_check(Cache.value_digest(warm._tile_cache_identity(identifier,source_hash)) != original_key,"Landmark replacement metadata does not invalidate cached picking.")
	var root_a := Node3D.new()
	var root_b := Node3D.new()
	warm.landmark_records["building-test-a"]["root"] = root_a
	var landmark_key: String = Cache.value_digest(warm._tile_cache_identity(identifier,source_hash))
	warm.landmark_records["building-test-a"]["root"] = root_b
	_check(Cache.value_digest(warm._tile_cache_identity(identifier,source_hash)) == landmark_key,"Process-local landmark roots changed persistent keys.")
	root_a.free()
	root_b.free()
	warm.landmark_records = {}
	var terrain = Terrain.new()
	_check(terrain.configure({"schema_version":1,"width":2,"height":2,"bounds":{"min":[0,0],"max":[2000,2000]},"elevations_m":[1,2,3,4]}),"Synthetic terrain did not configure.")
	warm.terrain = terrain
	var terrain_key: String = Cache.value_digest(warm._tile_cache_identity(identifier,source_hash))
	_check(terrain_key != original_key,"Terrain presence does not invalidate geometry.")
	terrain.configure({"schema_version":1,"width":2,"height":2,"bounds":{"min":[0,0],"max":[2000,2000]},"elevations_m":[1,2,3,8]})
	_check(Cache.value_digest(warm._tile_cache_identity(identifier,source_hash)) != terrain_key,"Changed elevations do not invalidate geometry.")
	var dependency_path: String = ProjectSettings.globalize_path(directory).path_join("dependency.json")
	var file := FileAccess.open(dependency_path,FileAccess.WRITE)
	file.store_string("first")
	file.close()
	var signature: Dictionary = warm._dependency_signature(dependency_path.get_base_dir(),{"path":"dependency.json","sha256":"fixed-descriptor"})
	file = FileAccess.open(dependency_path,FileAccess.WRITE)
	file.store_string("second")
	file.close()
	_check(signature != warm._dependency_signature(dependency_path.get_base_dir(),{"path":"dependency.json","sha256":"fixed-descriptor"}),"Actual optional dependency bytes did not invalidate a fixed descriptor.")
	warm.terrain = null
	var original_identity: Dictionary = cold._tile_cache_identity(identifier,source_hash)
	file = FileAccess.open(cold.render_cache.entry_path(original_identity),FileAccess.WRITE)
	file.store_buffer(PackedByteArray([0,1,2]))
	file.close()
	var recovered = _new_geography(cache_path)
	recovered._load_tile(identifier)
	_check(recovered.cache_stats().errors == 1 and recovered.cache_stats().generated_tiles == 1 and recovered.loaded.has(identifier),"Corrupt geography did not automatically rebuild from source.")
	_check(recovered.loaded[identifier].picking == cold.loaded[identifier].picking,"Corrupt-cache fallback changed geographic picking.")
	recovered.free()
	_test_malformed_geography(cold,identifier,original_identity,cache_path)
	terrain.free()
	cold.free()
	warm.free()


func _test_malformed_geography(cold: Node3D,identifier: String,identity: Dictionary,cache_path: String) -> void:
	var valid: Dictionary = cold.render_cache.read_entry(identity)
	_check(not valid.is_empty(),"Recovery did not replace the corrupt entry before malformed-payload checks.")
	for field: String in ["schema","triangle_count","buildings","triangles","skipped","omitted"]:
		for bad: Variant in [{"unexpected":1},[1],"1",1.0,true,null]:
			var damaged: Dictionary = valid.duplicate(true)
			if field == "triangle_count": damaged.high["triangle_count"] = bad
			else: damaged[field] = bad
			_assert_malformed_rebuild(cold,identifier,identity,cache_path,damaged,field)
	for field: String in ["height_m","bounds","polygon","holes","label"]:
		var damaged: Dictionary = valid.duplicate(true)
		damaged.picking[0][field] = {"unexpected":1}
		_assert_malformed_rebuild(cold,identifier,identity,cache_path,damaged,"picking."+field)
	var damaged: Dictionary = valid.duplicate(true)
	damaged.picking[0]["height_m"] = NAN
	_assert_malformed_rebuild(cold,identifier,identity,cache_path,damaged,"picking.height_m NaN")
	damaged = valid.duplicate(true)
	damaged.picking[0]["bounds"] = AABB(Vector3(INF,0,0),Vector3.ONE)
	_assert_malformed_rebuild(cold,identifier,identity,cache_path,damaged,"picking.bounds infinity")

func _assert_malformed_rebuild(cold: Node3D,identifier: String,identity: Dictionary,cache_path: String,damaged: Dictionary,field: String) -> void:
	_check(cold.render_cache.write_entry(identity,damaged),"Could not write the checksummed malformed fixture for "+field)
	var checked = _new_geography(cache_path)
	checked._load_tile(identifier)
	_check(checked.cache_stats().errors == 1 and checked.cache_stats().generated_tiles == 1 and checked.cache_stats().restored_tiles == 0 and checked.loaded.has(identifier),"Malformed "+field+" did not fall back to source geometry.")
	if checked.loaded.has(identifier):
		_check(checked.loaded[identifier].picking == cold.loaded[identifier].picking,"Malformed "+field+" recovery changed building picking.")
	checked.free()
