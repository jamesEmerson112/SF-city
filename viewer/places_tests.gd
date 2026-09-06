extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var places = preload("res://places.gd").new()
	places.initialize(ProjectSettings.globalize_path("res://../.local/civic/geography/sf-geography.json"))
	var failures: Array[String] = []
	_check_camera_fit(failures)
	if not places.available: failures.append("Installed places failed geography/source validation: " + places.last_error)
	else:
		if places.entries.size() != 294: failures.append("Named destinations do not cover the normalized 41 analysis areas and 253 Rec/Park properties.")
		if str(places.resolve("Mission").get("id","")) != "sf-neighborhood:Mission": failures.append("An exact name was treated as an ambiguous substring.")
		if str(places.resolve("neighborhood:Mission").get("id","")) != "sf-neighborhood:Mission": failures.append("A kind filter lost exact-name precedence.")
		if str(places.resolve("Golden Gate Park").get("id","")) != "sf-neighborhood:Golden Gate Park": failures.append("An exact analysis-area name was confused with park sections.")
		if places.search("park:golden gate park").size() != 7: failures.append("Kind-filtered search lost the source park sections.")
		if not places.resolve("park:golden gate park").is_empty() or places.last_error.is_empty(): failures.append("An ambiguous destination silently selected a section.")
		if not places.resolve("No such destination xxyy").is_empty() or places.last_error.is_empty(): failures.append("Unknown destinations did not report an error.")
		var landmark_manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/landmarks.json"))
		var landmark_records: Dictionary = {}
		for record: Dictionary in landmark_manifest.landmarks: landmark_records[str(record.id)] = record
		places.add_landmarks(landmark_records)
		if places.entries.size() != 298 or str(places.resolve("landmark:Coit Tower").get("id","")) != "sf-building:201006.0006230": failures.append("Loaded landmark exteriors were not searchable by kind and name.")
		if not str(places.resolve("Transamerica Pyramid").get("walk_node_id","")).begins_with("sf-"): failures.append("Landmark navigation did not retain its supplied street node.")
		var terrain = preload("res://terrain.gd").new()
		root.add_child(terrain)
		terrain.initialize(ProjectSettings.globalize_path("res://../.local/civic/terrain/terrain.json"))
		terrain.set_pilot_mode(false)
		var cameras = preload("res://cameras.gd").new()
		root.add_child(cameras)
		cameras.initialize(JSON.parse_string(FileAccess.get_file_as_string("res://assets/visual.json")))
		cameras.pilot_enabled = false
		cameras.terrain = terrain
		cameras.configure_geography({"min":[-10000,-10000],"max":[10000,10000]})
		var destination: Dictionary = places.resolve("sf-neighborhood:Mission")
		if not cameras.jump_to_place(destination): failures.append("Valid destination did not create an overhead view.")
		var height_value: float = float(terrain.triangle_height_at(float(destination.target[0]),float(destination.target[1])))
		if absf(cameras.orbit_target.y-height_value-8.0) > 0.001 or cameras.mode != "overhead": failures.append("Place overview ignored the common terrain datum.")
		cameras.pan(Vector2(20.0,30.0))
		var pan_height: float = float(terrain.triangle_height_at(cameras.orbit_target.x,-cameras.orbit_target.z))
		if absf(cameras.orbit_target.y-pan_height-8.0) > 0.001: failures.append("Map panning dropped the camera target below the shared terrain.")
		cameras.jump_to_place(destination,"walk")
		var eye_height: float = float(terrain.triangle_height_at(float(destination.walk_position[0]),float(destination.walk_position[1])))+cameras.EYE_HEIGHT
		if absf(cameras.walk_position.y-eye_height) > 0.001 or cameras.mode != "walk": failures.append("Walk-nearby view did not use the recorded source street node and terrain.")
		var picker = preload("res://place_search.gd").new()
		root.add_child(picker)
		await process_frame
		picker.configure(places)
		picker._filter("Mission")
		if not picker.results.visible or picker.results.item_count < 2: failures.append("Search UI did not show the matching named destinations.")
		picker.show_place(destination)
		if picker.results.visible or not picker.links.visible or not "Analysis area" in picker.detail.text: failures.append("Selected place lost its category or source controls.")
		picker.free()
		cameras.terrain = null
		cameras.pilot_enabled = true
		cameras.fixture.collision_boxes = [{"min":[-50,-50],"max":[50,50]}]
		cameras.follow_available = true
		cameras.follow_indoor = true
		cameras.follow_building_height = 50.0
		cameras.follow_position = Vector3.ZERO
		cameras.set_mode("follow")
		if not cameras._can_walk_to(cameras.camera.position) or cameras.camera.position.y < 50.0: failures.append("An indoor resident's follow camera stayed trapped inside a large building.")
		if cameras.follow_position != Vector3.ZERO: failures.append("Indoor camera framing moved the resident's authoritative arrival point.")
		cameras.free()
		terrain.free()
	if failures.is_empty():
		print("GODOT_PLACES_TESTS_OK observed source index, exact and ambiguous names, kind search, geographic camera target, street-node walk spawn, source-aware UI")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _check_camera_fit(failures: Array[String]) -> void:
	var camera_script = preload("res://cameras.gd")
	var target := Vector3(500.0,12.0,-80.0)
	var points: Array[Vector3] = []
	for x: float in [-3000.0,3400.0]:
		for z: float in [-600.0,700.0]:
			for y: float in [0.0,100.0]: points.append(Vector3(x,y,z))
	var pitch: float = deg_to_rad(62.0)
	var yaw: float = deg_to_rad(-90.0)
	var back := Vector3(cos(yaw)*cos(pitch),sin(pitch),-sin(yaw)*cos(pitch))
	var right: Vector3 = Vector3.UP.cross(back).normalized()
	var up: Vector3 = back.cross(right)
	for aspect: float in [0.6,1.6,2.4]:
		for keep_aspect: int in [Camera3D.KEEP_HEIGHT,Camera3D.KEEP_WIDTH]:
			var distance: float = camera_script.fit_distance(points,target,pitch,yaw,55.0,aspect,keep_aspect)
			var tangent_y: float = tan(deg_to_rad(55.0)*0.5)
			var tangent_x: float = tangent_y*aspect
			if keep_aspect == Camera3D.KEEP_WIDTH:
				tangent_x = tangent_y
				tangent_y /= aspect
			var extent: float = 0.0
			for point: Vector3 in points:
				var offset: Vector3 = point-target
				var depth: float = distance-offset.dot(back)
				if depth <= 0.0: failures.append("Place fit left a bounding point behind the camera.")
				extent = maxf(extent,maxf(absf(offset.dot(right))/(depth*tangent_x),absf(offset.dot(up))/(depth*tangent_y)))
			if absf(extent-0.86) > 0.0001: failures.append("Place fit did not use the viewport aspect, perspective depth and requested margin.")
