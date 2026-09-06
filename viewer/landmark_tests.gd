extends SceneTree

func _initialize() -> void:
	var terrain = preload("res://terrain.gd").new()
	root.add_child(terrain)
	terrain.configure({"schema_version":1,"width":2,"height":2,"bounds":{"min":[-10000,-10000],"max":[10000,10000]},"origin_elevation_m":10,"elevations_m":[12,12,12,12]})
	var landmarks = preload("res://landmarks.gd").new()
	root.add_child(landmarks)
	landmarks.initialize(terrain)
	var failure: String = ""
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/landmarks.json"))
	var expected_meshes: int = 0
	for source: Dictionary in manifest.landmarks: expected_meshes += int(source.mesh_count)
	if landmarks.records.size() != manifest.landmarks.size() or landmarks.mesh_count != expected_meshes: failure = "The aligned landmark assets did not load their declared material meshes."
	elif not landmarks.records.has("sf-building:201006.0000041"): failure = "The landmark lost the observed source identity."
	else:
		var record: Dictionary = landmarks.records["sf-building:201006.0000041"]
		if absf(record.root.position.y-2.0) > 0.00001: failure = "Landmark base was not sampled from the terrain datum."
		if landmarks.visible: failure = "A loaded city landmark became visible in pilot mode."
		landmarks.set_enabled(true)
		for body: StaticBody3D in landmarks.find_children("*","StaticBody3D",true,false):
			if body.collision_layer != 1 or not landmarks.records.has(body.get_meta("selection_id")): failure = "Active landmark picking does not preserve the building ID."
		landmarks.set_enabled(false)
		for body: StaticBody3D in landmarks.find_children("*","StaticBody3D",true,false):
			if body.collision_layer != 0: failure = "Hidden landmark colliders still block the pilot."
		if landmarks.aliases.get("sf-building:201006.0062170","") != "sf-building:201006.0009087" or landmarks.aliases.get("sf-building:201006.0168289","") != "sf-building:201006.0009087": failure = "Overlapping Sutro source parts did not alias the primary tower."
		if landmarks.replacements.size() != 6: failure = "Landmark replacement IDs differ from the four exteriors and two overlapping tower parts."
	landmarks.free()
	terrain.free()
	var without_terrain = preload("res://landmarks.gd").new()
	root.add_child(without_terrain)
	without_terrain.initialize(null)
	if not without_terrain.last_error.is_empty() or not without_terrain.records.is_empty(): failure = "An intentionally terrain-free pilot reported missing city landmark errors."
	without_terrain.set_enabled(true)
	if without_terrain.last_error.is_empty(): failure = "Explicit city mode hid missing landmark terrain."
	without_terrain.set_enabled(false)
	if not without_terrain.last_error.is_empty(): failure = "Returning to a terrain-free pilot retained irrelevant city errors."
	without_terrain.free()
	if failure.is_empty():
		print("GODOT_LANDMARK_TESTS_OK actual GLB, terrain datum, source ID, mode visibility and picking layers")
		quit(0)
	else:
		push_error(failure)
		quit(1)
