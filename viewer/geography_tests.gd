extends SceneTree
var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var geography = preload("res://geography.gd").new()
	root.add_child(geography)
	if not geography.initialize("res://testdata/geography/manifest.json"):
		failures.append("Synthetic geography contract fixture failed to load.")
	else:
		var camera := Camera3D.new()
		root.add_child(camera)
		geography.update_view(camera,Vector3(750,0,-750),1000.0,0.3)
		geography.update_view(camera,Vector3(750,0,-750),1000.0,0.3)
		if geography.loaded.size() != 2 or geography.loaded_buildings != 2: failures.append("Nearby geographic tiles did not decode into merged buildings.")
		if geography.detailed_tiles != 2: failures.append("Near geographic buildings did not choose detailed meshes.")
		if geography.roofs_omitted_for_holes != 1: failures.append("A courtyard roof was silently filled instead of omitted.")
		var picked: Dictionary = geography.pick(Vector3(610,40,-610),Vector3.DOWN,100)
		if str(picked.get("source_id","")) != "building-test-a": failures.append("A mapped building cannot be inspected through its displayed polygon.")
		if not geography.pick(Vector3(1120,40,-620),Vector3.DOWN,100).is_empty(): failures.append("Picking filled the deliberately open courtyard.")
		geography.update_view(camera,Vector3(750,0,-750),3000.0,0.3)
		if geography.detailed_tiles != 0 or geography.visible_tiles != 2: failures.append("Medium-distance geography did not choose flat footprints.")
		geography.update_view(camera,Vector3(750,0,-750),10000.0,0.3)
		if geography.visible_tiles != 0: failures.append("City overview did not cull detailed tiles.")
		if not geography._segment_hits_pilot([-300,0,0],[300,0,0]): failures.append("A street crossed the pilot exclusion without detection.")
		if geography._segment_hits_pilot([-300,300,0],[300,300,0]): failures.append("A street outside the pilot was incorrectly removed.")
		var before: int = geography.missing_tiles
		geography.tiles["escape"] = {"id":"escape","path":"../outside.json","bounds":{"min":[0,0],"max":[1,1]}}
		geography._load_tile("escape")
		if geography.missing_tiles != before+1 or geography.loaded.has("escape"): failures.append("Geographic tile path traversal was not rejected.")
		camera.free()
	geography.free()
	if failures.is_empty():
		print("GODOT_GEOGRAPHY_TESTS_OK merged tiles, detail levels, courtyard roof omission, map picking, pilot exclusion, bounded file paths")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
