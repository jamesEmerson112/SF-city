extends SceneTree

func _initialize() -> void:
	var terrain = preload("res://terrain.gd").new()
	root.add_child(terrain)
	terrain.configure({"schema_version":1,"width":2,"height":2,"bounds":{"min":[-100000,-100000],"max":[100000,100000]},"origin_elevation_m":0,"elevations_m":[0,0,0,0]})
	var visuals = preload("res://geography_visuals.gd").new()
	root.add_child(visuals)
	visuals.terrain = terrain
	visuals.initialize(ProjectSettings.globalize_path("res://../.local/civic/geography/sf-geography.json"))
	var failure: String = ""
	if not visuals.available: failure = "The installed visual index failed source validation: " + visuals.last_error
	else:
		visuals.set_pilot_mode(false)
		visuals._load_tile("0_0")
		if not visuals.last_error.is_empty(): failure = visuals.last_error
		elif visuals.loaded.get("0_0",{}).get("mesh") == null: failure = "The city visual tile did not produce a merged silhouette batch."
		else:
			var record: Dictionary = visuals.loaded["0_0"]
			if record.mesh.multimesh.instance_count != int(visuals.descriptors["0_0"].building_count): failure = "The silhouette batch lost a source building."
			if record.roofs.is_empty(): failure = "The tile's courtyard roof triangulations did not load."
			else:
				var identity: String = record.roofs.keys()[0]
				var source: Dictionary = {"id":identity,"footprint":[],"rings":[]}
				var enriched: Dictionary = visuals.enrich_building(source,"0_0")
				if enriched.get("roof_triangles",[]).is_empty() or source.has("roof_triangles"): failure = "Roof enrichment did not preserve the source record."
			visuals.pending.clear()
			var fake_root := Node3D.new()
			root.add_child(fake_root)
			var fake_mesh := MeshInstance3D.new()
			fake_root.add_child(fake_mesh)
			visuals.update_view(Vector3.ZERO,{"0_0":{"root":fake_root,"high":fake_mesh}})
			if record.mesh.visible: failure = "Coarse silhouettes overlap their detailed tile replacement."
			visuals.update_view(Vector3.ZERO,{})
			if not record.mesh.visible: failure = "Distant silhouettes did not return after detailed tile eviction."
			fake_root.free()
	visuals.free()
	terrain.free()
	if failure.is_empty():
		print("GODOT_VISUALS_TESTS_OK source hash, tile checksum, merged silhouettes, courtyard roof enrichment, detail replacement")
		quit(0)
	else:
		push_error(failure)
		quit(1)
