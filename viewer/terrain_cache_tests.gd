extends SceneTree
## Exact prepared terrain, including both detail levels and source invalidation.
const Terrain = preload("res://terrain.gd")
const Cache = preload("res://scenery_cache.gd")
const Builder = preload("res://geography_mesh.gd")
var failures: Array[String] = []
var cache_directory: String

func _initialize() -> void:
	cache_directory = ProjectSettings.globalize_path("res://../.cache/terrain-cache-tests/%d-%d" % [OS.get_process_id(),Time.get_ticks_usec()])
	var baseline = _terrain("")
	baseline._build_chunk(Vector2i.ZERO,4)
	baseline._build_chunk(Vector2i.ZERO,1)
	var expected_low: Array = _arrays(baseline,4)
	var expected_high: Array = _arrays(baseline,1)
	_check(not expected_high.is_empty(),"The reference terrain produced no mesh.")
	_check(int(baseline.cache_stats().writes) == 0 and int(baseline.cache_stats().misses) == 0,"Existing callers unexpectedly wrote a persistent cache.")
	_check(var_to_bytes(expected_low) != var_to_bytes(expected_high),"Coarse and detailed terrain were not distinct.")

	var cold = _terrain(cache_directory)
	cold._build_chunk(Vector2i.ZERO,4)
	cold._build_chunk(Vector2i.ZERO,1)
	_check(int(cold.cache_stats().writes) == 2 and int(cold.cache_stats().misses) == 2,"The first build did not prepare both detail levels.")
	_check(var_to_bytes(_arrays(cold,4)) == var_to_bytes(expected_low) and var_to_bytes(_arrays(cold,1)) == var_to_bytes(expected_high),"Preparing terrain changed its mesh arrays.")
	var cold_triangles: int = cold.terrain_triangle_count
	var base_identity: Dictionary = cold.cache_identity()
	_check(str(base_identity.terrain_sha256).length() == 64 and str(base_identity.shoreline_sha256).length() == 64 and str(base_identity.builder_sha256).length() == 64 and not str(base_identity.godot).is_empty(),"Terrain cache omitted source or builder identity.")

	var hot = _terrain(cache_directory)
	hot._build_chunk(Vector2i.ZERO,4)
	hot._build_chunk(Vector2i.ZERO,1)
	_check(int(hot.cache_stats().hits) == 2 and int(hot.cache_stats().writes) == 0,"The second renderer did not load both prepared detail levels.")
	_check(hot.shore_chunks.is_empty(),"A cache hit still prepared shoreline clipping.")
	_check(hot.terrain_triangle_count == cold_triangles and var_to_bytes(_arrays(hot,4)) == var_to_bytes(expected_low) and var_to_bytes(_arrays(hot,1)) == var_to_bytes(expected_high),"Prepared terrain differs from its uncached triangles, normals, colors, or UVs.")
	_check(hot.triangle_height_at(13,17) == baseline.triangle_height_at(13,17) and hot.height_at(-1,20) == null,"Loading prepared geometry changed live terrain height queries.")

	var grid_changed = _terrain(cache_directory)
	var changed_grid: Dictionary = _grid()
	changed_grid.elevations_m[0] += 7.0
	grid_changed.configure(changed_grid)
	grid_changed._build_chunk(Vector2i.ZERO,1)
	_check(grid_changed.cache_identity() != base_identity and int(grid_changed.cache_stats().misses) == 1 and int(grid_changed.cache_stats().hits) == 0,"Elevation changes reused stale terrain.")
	_check(var_to_bytes(_arrays(grid_changed,1)) != var_to_bytes(expected_high),"Changed elevations retained the old mesh.")

	var coast_changed = _terrain(cache_directory)
	coast_changed.set_land([{"points":[[-5,-5],[20,-5],[20,45],[-5,45]]}])
	coast_changed._build_chunk(Vector2i.ZERO,1)
	_check(coast_changed.cache_identity() != base_identity and int(coast_changed.cache_stats().misses) == 1 and int(coast_changed.cache_stats().hits) == 0,"Shoreline changes reused stale clipped terrain.")
	_check(var_to_bytes(_arrays(coast_changed,1)) != var_to_bytes(expected_high),"Changed shoreline retained the old clipped mesh.")

	var pilot = _terrain(cache_directory)
	pilot.set_pilot_mode(true)
	pilot._build_chunk(Vector2i.ZERO,1)
	_check(pilot.cache_identity() != base_identity and int(pilot.cache_stats().misses) == 1 and int(pilot.cache_stats().hits) == 0,"The synthetic pilot reused real-city terrain.")
	_check(var_to_bytes(_arrays(pilot,1)) != var_to_bytes(expected_high) and pilot.display_height_at(13,17) == 0.0,"The pilot flattening variant was not preserved.")
	pilot.detailed_chunks = 1
	pilot.set_pilot_mode(false)
	_check(pilot.chunks.is_empty() and pilot.terrain_triangle_count == 0 and pilot.detailed_chunks == 0 and not pilot.pending.is_empty(),"Changing terrain mode left stale chunks or counters.")
	pilot._build_chunk(Vector2i.ZERO,1)
	_check(int(pilot.cache_stats().hits) == 1 and var_to_bytes(_arrays(pilot,1)) == var_to_bytes(expected_high),"Returning to city terrain did not reuse its exact prepared variant.")

	var missing = _terrain(cache_directory)
	var missing_grid: Dictionary = _grid()
	missing_grid.elevations_m[12] = null
	missing.configure(missing_grid)
	missing._build_chunk(Vector2i.ZERO,1)
	_check(missing.triangle_height_at(20,20) == null and missing.terrain_triangle_count < cold_triangles and int(missing.cache_stats().hits) == 0,"Prepared geometry filled a missing source sample.")

	var changed_builder = _terrain(cache_directory)
	changed_builder.builder_digest = "different-builder"
	changed_builder._build_chunk(Vector2i.ZERO,1)
	_check(int(changed_builder.cache_stats().misses) == 1 and int(changed_builder.cache_stats().hits) == 0,"A different geometry builder reused an old entry.")

	var cache = Cache.new()
	cache.configure(cache_directory)
	cache.enabled = true
	var identity: Dictionary = base_identity.duplicate(true)
	identity["chunk"] = Vector2i.ZERO
	identity["stride"] = 1
	var corrupt_file := FileAccess.open(cache.entry_path(identity),FileAccess.WRITE)
	_check(corrupt_file != null,"Could not create the isolated corrupt-cache fixture.")
	if corrupt_file != null:
		corrupt_file.store_string("truncated")
		corrupt_file.close()
	var corrupt = _terrain(cache_directory)
	corrupt._build_chunk(Vector2i.ZERO,1)
	_check(int(corrupt.cache_stats().errors) > 0 and int(corrupt.cache_stats().writes) == 1 and var_to_bytes(_arrays(corrupt,1)) == var_to_bytes(expected_high),"A corrupt cache entry did not rebuild exact terrain.")

	cache.write_entry(identity,{"origin":Vector3.ZERO,"vertices":"bad array"})
	var malformed = _terrain(cache_directory)
	malformed._build_chunk(Vector2i.ZERO,1)
	_check(int(malformed.cache_stats().invalid_payloads) == 1 and int(malformed.cache_stats().errors) > 0 and var_to_bytes(_arrays(malformed,1)) == var_to_bytes(expected_high),"Malformed checksummed arrays did not rebuild safely.")

	# A regular file at the configured directory reliably denies cache writes on
	# every OS without changing permissions or depending on an elevated user.
	var blocker_path: String = cache_directory.path_join("unwritable-directory")
	var blocker := FileAccess.open(blocker_path,FileAccess.WRITE)
	_check(blocker != null,"Could not create the isolated unwritable-cache fixture.")
	if blocker != null:
		blocker.store_string("directory blocker")
		blocker.close()
	var unwritable = _terrain(blocker_path)
	unwritable._build_chunk(Vector2i.ZERO,1)
	_check(int(unwritable.cache_stats().errors) > 0 and int(unwritable.cache_stats().writes) == 0 and var_to_bytes(_arrays(unwritable,1)) == var_to_bytes(expected_high),"An unwritable cache prevented rendering generated terrain.")

	var disabled = _terrain(cache_directory)
	disabled.set_cache_enabled(false)
	disabled._build_chunk(Vector2i.ZERO,1)
	_check(int(disabled.cache_stats().hits) == 0 and int(disabled.cache_stats().writes) == 0 and var_to_bytes(_arrays(disabled,1)) == var_to_bytes(expected_high),"Disabling prepared scenery changed terrain output or still touched the cache.")
	for terrain: Node in [baseline,cold,hot,grid_changed,coast_changed,pilot,missing,changed_builder,corrupt,malformed,unwritable,disabled]: terrain.free()
	if failures.is_empty():
		print("GODOT_TERRAIN_CACHE_TESTS_OK exact cold/hot arrays, both detail levels, terrain/shoreline/pilot/builder invalidation, missing samples, corrupt/malformed/unwritable fallback")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _terrain(directory: String) -> Node3D:
	var terrain = Terrain.new()
	root.add_child(terrain)
	_check(terrain.configure(_grid()),"Terrain fixture did not configure.")
	terrain.mesh_material = Builder.surface_material()
	terrain.set_pilot_mode(false)
	terrain.set_land([{"points":[[-5,-5],[45,-5],[45,23],[29,45],[-5,45]]}])
	if not directory.is_empty(): terrain.configure_render_cache(directory)
	return terrain

func _grid() -> Dictionary:
	var elevations: Array = []
	for row: int in range(5):
		for column: int in range(5): elevations.append(10.0+column*3.0+row*5.0+column*row)
	return {"schema_version":1,"width":5,"height":5,"bounds":{"min":[0,0],"max":[40,40]},"origin_elevation_m":10.0,"elevations_m":elevations}

func _arrays(terrain: Node3D,stride: int) -> Array:
	if not terrain.chunks.has(Vector2i.ZERO): return []
	var mesh: MeshInstance3D = terrain.chunks[Vector2i.ZERO]["low" if stride == 4 else "high"]
	if mesh == null: return []
	return mesh.mesh.surface_get_arrays(0)

func _check(condition: bool,message: String) -> void:
	if not condition: failures.append(message)
