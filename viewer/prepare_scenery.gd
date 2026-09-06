extends SceneTree
## Offline static scenery preparation using the same builders as the viewer.

func _initialize() -> void:
	call_deferred("_run")

func _argument(args: PackedStringArray, key: String, fallback: String = "") -> String:
	var index: int = args.find(key)
	return args[index+1] if index >= 0 and index+1 < args.size() else fallback

func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var geography_path := _argument(args,"--geography")
	var terrain_path := _argument(args,"--terrain")
	var cache_path := _argument(args,"--render-cache")
	var scope := _argument(args,"--scope","city-hall")
	var radius := float(_argument(args,"--radius","750"))
	if geography_path.is_empty() or cache_path.is_empty() or scope not in ["city","city-hall"] or not is_finite(radius) or radius <= 0.0:
		printerr("SCENERY_PREPARE_ERROR Invalid preparation arguments")
		quit(1)
		return
	var started := Time.get_ticks_usec()
	var terrain = preload("res://terrain.gd").new()
	root.add_child(terrain)
	terrain.configure_render_cache(cache_path)
	if not terrain_path.is_empty() and not terrain.initialize(terrain_path):
		printerr("SCENERY_PREPARE_ERROR " + str(terrain.last_error))
		quit(1)
		return
	var landmarks = preload("res://landmarks.gd").new()
	root.add_child(landmarks)
	landmarks.initialize(terrain)
	var geography = preload("res://geography.gd").new()
	root.add_child(geography)
	geography.terrain = terrain
	geography.landmark_records = landmarks.replacements
	geography.configure_render_cache(cache_path)
	if not geography.initialize(geography_path):
		printerr("SCENERY_PREPARE_ERROR " + str(geography.last_error))
		quit(1)
		return
	if terrain.available: terrain.set_land(geography.manifest.get("land",[]))
	terrain.set_pilot_mode(false)
	geography.set_pilot_mode(false)
	var tile_ids: Array[String] = []
	for identifier: String in geography.tiles:
		var bounds: Dictionary = geography.tiles[identifier].bounds
		if scope == "city" or (float(bounds.max[0]) > -radius and float(bounds.min[0]) < radius and float(bounds.max[1]) > -radius and float(bounds.min[1]) < radius):
			tile_ids.append(identifier)
	tile_ids.sort()
	var completed: int = 0
	var tile_samples: Array[float] = []
	for identifier: String in tile_ids:
		var before := Time.get_ticks_usec()
		geography._load_tile(identifier)
		tile_samples.append(float(Time.get_ticks_usec()-before)/1000.0)
		if not geography.loaded.has(identifier):
			printerr("SCENERY_PREPARE_ERROR " + str(geography.last_error))
			quit(1)
			return
		geography.loaded[identifier].root.queue_free()
		geography.loaded.clear()
		geography.loaded_buildings = 0
		completed += 1
		print("SCENERY_PREPARE_PROGRESS " + JSON.stringify({"stage":"buildings_roads","done":completed,"total":tile_ids.size()}))
		await process_frame
	var terrain_samples: Array[float] = []
	var chunk_count: int = 0
	if terrain.available:
		var keys: Array[Vector2i] = terrain.pending.duplicate()
		terrain.pending.clear()
		for key: Vector2i in keys:
			var west: float = terrain.min_east+key.x*terrain.step_east
			var north: float = terrain.max_north-key.y*terrain.step_north
			var east: float = west+terrain.CHUNK_SAMPLES*terrain.step_east
			var south: float = north-terrain.CHUNK_SAMPLES*terrain.step_north
			var near: bool = scope == "city" or (east > -radius and west < radius and north > -radius and south < radius)
			var strides: Array = [4,1] if near else [4]
			for stride: int in strides:
				var before := Time.get_ticks_usec()
				terrain._build_chunk(key,stride)
				terrain_samples.append(float(Time.get_ticks_usec()-before)/1000.0)
				chunk_count += 1
			if terrain.chunks.has(key): terrain.chunks[key].root.queue_free()
			terrain.chunks.clear()
			if chunk_count % 16 == 0: print("SCENERY_PREPARE_PROGRESS " + JSON.stringify({"stage":"terrain","chunks":chunk_count}))
			await process_frame
	var report := {"scope":scope,"radius_m":radius,"geography_tiles":completed,"terrain_chunks":chunk_count,"elapsed_seconds":float(Time.get_ticks_usec()-started)/1000000.0,"geography_cache":geography.cache_stats(),"terrain_cache":terrain.cache_stats(),"tile_work_ms":_summary(tile_samples),"terrain_work_ms":_summary(terrain_samples),"sources":{"geography_sha256":FileAccess.get_sha256(geography_path),"terrain_sha256":FileAccess.get_sha256(terrain_path) if not terrain_path.is_empty() else "none","attribution":"Derived display geometry; geographic source notices remain in the installed manifests and docs/SF_GEOGRAPHY.md."}}
	var report_path := _argument(args,"--report")
	if not report_path.is_empty():
		var file := FileAccess.open(report_path,FileAccess.WRITE)
		if file == null:
			printerr("SCENERY_PREPARE_ERROR Could not write report")
			quit(1)
			return
		file.store_string(JSON.stringify(report,"\t"))
	var successful: bool = int(report.geography_cache.get("errors",0))+int(report.terrain_cache.get("errors",0)) == 0
	print(("SCENERY_PREPARE_OK " if successful else "SCENERY_PREPARE_ERROR ") + JSON.stringify(report))
	quit(0 if successful else 1)

func _summary(samples: Array[float]) -> Dictionary:
	if samples.is_empty(): return {"count":0}
	samples.sort()
	return {"count":samples.size(),"p50":samples[int((samples.size()-1)*0.5)],"p95":samples[int((samples.size()-1)*0.95)],"max":samples[-1]}
