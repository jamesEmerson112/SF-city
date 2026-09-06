extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var use_data = preload("res://geography_use.gd").new()
	var path: String = ProjectSettings.globalize_path("res://../.local/civic/geography/sf-geography.json")
	use_data.initialize(path)
	var failures: Array[String] = []
	if not use_data.available: failures.append("Installed use index failed source verification: " + use_data.last_error)
	else:
		use_data.load_colors("0_0")
		if use_data.building_tiles.is_empty(): failures.append("Compact colors did not retain building identities.")
		if not use_data.loaded.is_empty(): failures.append("Distant color loading retained full group metadata.")
		var identity: String = ""
		for id_value: String in use_data.building_tiles:
			if use_data.category_index(id_value) != 8:
				identity = id_value
				break
		var record: Dictionary = use_data.record_for(identity)
		if record.get("land_use",{}).is_empty(): failures.append("Nearby inspection did not load source group metadata.")
		else:
			var description: String = use_data.describe(record)
			if not "Source group totals" in description or not "not building capacities" in description: failures.append("Inspector omitted the group-level scope.")
			if not str(record.land_use.get("source_url","")).begins_with("https://data.sfgov.org/"): failures.append("Inspector source link did not preserve DataSF attribution.")
		for tile_id: String in use_data.descriptors.keys().slice(0,55): use_data.load_tile(tile_id)
		if use_data.loaded.size() > use_data.GROUP_CACHE_LIMIT: failures.append("Detailed use metadata exceeded its bounded cache.")
		var corrupt = preload("res://geography_use.gd").new()
		corrupt.initialize(path)
		corrupt.descriptors["0_0"] = corrupt.descriptors["0_0"].duplicate(true)
		corrupt.descriptors["0_0"]["color_sha256"] = "bad"
		corrupt.descriptors["0_0"]["sha256"] = "bad"
		corrupt.load_colors("0_0")
		if corrupt.last_error.is_empty() or not corrupt.building_tiles.is_empty(): failures.append("Corrupt color data was accepted.")
	var builder = preload("res://geography_mesh.gd").new()
	var source: Dictionary = {"id":"test","footprint":[[0,0,0],[10,0,0],[10,10,0],[0,10,0]],"height_m":12,"use_category":3}
	builder.building(source)
	for coordinate: Vector2 in builder.use_coordinates:
		if int(coordinate.x) != 3: failures.append("Merged roof/wall vertices lost their category."); break
	var material: ShaderMaterial = use_data.make_material()
	material.set_shader_parameter("use_overlay",true)
	if not bool(material.get_shader_parameter("use_overlay")): failures.append("Use overlay is not a uniform-only toggle.")
	var hud = preload("res://hud.gd").new()
	root.add_child(hud)
	await process_frame
	if hud.use_legend.get_child(0).get_child_count() != use_data.CATEGORIES.size(): failures.append("Legend did not include every source category.")
	hud.free()
	if failures.is_empty():
		print("GODOT_USE_TESTS_OK source checksums, compact colors, bounded group cache, scoped inspection, provenance link, merged categories, complete legend")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
