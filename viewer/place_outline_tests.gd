extends SceneTree
const Outline = preload("res://place_outline.gd")
const Terrain = preload("res://terrain.gd")
var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	_check_geometry()
	_check_source_integrity()
	if failures.is_empty():
		print("GODOT_PLACE_OUTLINE_TESTS_OK source checksum/path, source detachment, ring holes and closure, terrain triangles, missing samples, selection lifecycle and bounded input")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _fixture() -> Dictionary:
	return {"schema_version":1,"areas":[{"id":"test-area","polygons":[{"rings":[[[0,0,0],[20,0,0],[20,20,0],[0,20,0]],[[5,5,0],[5,10,0],[10,10,0],[10,5,0]]]}]}]}

func _record() -> Dictionary:
	return {"id":"test-area","kind":"park","name":"Test source area"}

func _check_geometry() -> void:
	var outline = Outline.new()
	root.add_child(outline)
	var fixture: Dictionary = _fixture()
	if not outline.configure(fixture): failures.append("Valid source rings were rejected.")
	fixture.areas[0].polygons[0].rings[0][0][0] = 500
	if not outline.show_place(_record()): failures.append("Valid selected area did not render.")
	if outline.segment_count != 8: failures.append("Outer and inner rings must each close without joining across a hole.")
	var mesh: ArrayMesh = outline.instance.mesh
	var vertices: PackedVector3Array = mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	for vertex: Vector3 in vertices:
		if vertex.x > 20.0 or vertex.z > 0.0 or vertex.y != float(Vector3(0,0.3,0).y): failures.append("Outline mutated source coordinates or converted ENU incorrectly.")
	var terrain = Terrain.new()
	root.add_child(terrain)
	terrain.configure({"schema_version":1,"width":3,"height":3,"bounds":{"min":[0,0],"max":[20,20]},"elevations_m":[20,30,40,10,20,30,0,10,20],"origin_elevation_m":0})
	terrain.set_pilot_mode(false)
	outline.terrain = terrain
	if not outline.show_place(_record()) or outline.segment_count <= 8: failures.append("Boundary was not split at common terrain triangles.")
	vertices = outline.instance.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX]
	for vertex: Vector3 in vertices:
		var height: float = float(terrain.display_height_at(vertex.x,-vertex.z))+0.3
		if absf(vertex.y-height) > 0.00001: failures.append("Boundary height differs from the common displayed terrain.")
	terrain.values[0] = null
	if not outline.show_place(_record()) or outline.skipped_segments <= 0: failures.append("Missing terrain must create a gap, not invented height.")
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.position = Vector3(1000,1000,1000)
	outline.update_view(camera)
	if float(outline.material.get_shader_parameter("half_width_m")) <= 0.0: failures.append("Selected boundary has no visible width.")
	if outline.show_place({"id":"landmark","kind":"landmark"}) or not outline.selected_id.is_empty() or outline.instance != null: failures.append("Choosing a landmark retained a previous source area.")
	outline.show_place(_record())
	if outline.show_place({"id":"unknown","kind":"park"}) or outline.instance != null or outline.last_error.is_empty(): failures.append("Unknown place retained a misleading prior boundary.")
	for bad: Dictionary in [{"schema_version":0,"areas":[]},{"schema_version":1,"areas":[{"id":"test","polygons":[]}]},{"schema_version":1,"areas":[{"id":"test","polygons":[{"rings":[[[0,0,0],[1,0,0],[NAN,1,0]]]}]}]}]:
		if outline.configure(bad) or outline.available or not outline.areas.is_empty(): failures.append("Invalid source geometry left a usable partial area index.")
	var duplicate: Dictionary = _fixture()
	duplicate.areas.append(duplicate.areas[0].duplicate(true))
	if outline.configure(duplicate): failures.append("Duplicate source identities were accepted.")
	camera.free()
	outline.free()
	terrain.free()

func _check_source_integrity() -> void:
	var geography_path: String = ProjectSettings.globalize_path("res://../.local/civic/geography/sf-geography.json")
	var index_path: String = geography_path.get_base_dir().path_join("places-index.json")
	if not FileAccess.file_exists(index_path):
		failures.append("Installed places index is required for the source integration check.")
		return
	var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(index_path))
	var outline = Outline.new()
	root.add_child(outline)
	if not outline.initialize(geography_path,manifest) or not outline.areas.is_empty(): failures.append("Source sidecar should validate before lazy geometry loading.")
	var selected: Dictionary = {}
	for record: Dictionary in manifest.places:
		if record.id == "sf-neighborhood:Golden Gate Park": selected = record
	if not outline.show_place(selected) or outline.segment_count <= 0 or outline.source_points != 89381: failures.append("Actual Golden Gate Park source geometry failed to load and render.")
	var altered: Dictionary = manifest.duplicate(true)
	altered.areas_sha256 = "0".repeat(64)
	if outline.initialize(geography_path,altered) or outline.available or outline.instance != null: failures.append("Changed source checksum retained a usable outline.")
	for path: String in ["../places-areas.json","C:/places-areas.json","/places-areas.json","folder/../../places-areas.json","folder\\places-areas.json"]:
		altered.areas_path = path
		if outline.initialize(geography_path,altered): failures.append("Unsafe geometry path was accepted: "+path)
	outline.free()
