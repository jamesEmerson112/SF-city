extends Node3D
## Optional original architectural exteriors aligned to observed building IDs.
const Coordinates = preload("res://coordinates.gd")
var records: Dictionary = {}
var selectable: Dictionary = {}
var mesh_count: int = 0
var last_error: String = ""
var aliases: Dictionary = {}
var replacements: Dictionary = {}
var missing_terrain: Array[String] = []
var terrain_error: String = ""

func initialize(terrain: Node3D, path: String = "res://assets/landmarks.json") -> void:
	if not FileAccess.file_exists(path): return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or not parsed.get("landmarks") is Array:
		last_error = "Optional landmark manifest is invalid."
		return
	for source: Dictionary in parsed.landmarks:
		var identifier: String = str(source.get("id",""))
		var asset: String = str(source.get("asset","")).simplify_path()
		if identifier.is_empty() or not source.get("position") is Array or source.position.size() != 3 or not asset.begins_with("res://assets/"):
			last_error = "Optional landmark entry is invalid."
			continue
		var position_value: Vector3 = Coordinates.to_world(source.position)
		if not position_value.is_finite(): continue
		if bool(source.get("place_on_terrain",false)):
			var elevation: Variant = terrain.triangle_height_at(float(source.position[0]),float(source.position[1])) if terrain != null and terrain.available else null
			if elevation == null:
				missing_terrain.append(str(source.get("label","Landmark")))
				continue
			position_value.y += float(elevation)
		var document := GLTFDocument.new()
		var state := GLTFState.new()
		var error: Error = document.append_from_file(ProjectSettings.globalize_path(asset),state)
		if error != OK:
			last_error = "Optional landmark import failed: " + error_string(error)
			continue
		var imported: Node3D = document.generate_scene(state) as Node3D
		if imported == null: continue
		add_child(imported)
		imported.position = position_value
		var meshes: Array = []
		for mesh: MeshInstance3D in imported.find_children("*","MeshInstance3D",true,false):
			var body := StaticBody3D.new()
			body.collision_layer = 0
			body.collision_mask = 0
			body.set_meta("selection_id",identifier)
			body.set_meta("selection_label",str(source.get("label",identifier)))
			body.set_meta("selection_note",str(source.get("source_note","")))
			var shape := CollisionShape3D.new()
			shape.shape = mesh.mesh.create_trimesh_shape()
			body.add_child(shape)
			mesh.add_child(body)
			meshes.append(mesh)
		if meshes.is_empty():
			imported.queue_free()
			continue
		var record: Dictionary = source.duplicate(false)
		record["base_height"] = position_value.y
		record["root"] = imported
		records[identifier] = record
		var replaced_ids: Array = source.get("replaces_building_ids",[identifier]).duplicate()
		if identifier not in replaced_ids: replaced_ids.append(identifier)
		for replaced_id: String in replaced_ids:
			aliases[replaced_id] = identifier
			replacements[replaced_id] = record
		selectable[identifier] = meshes
		mesh_count += meshes.size()
	if not missing_terrain.is_empty(): terrain_error = "Landmark terrain is unavailable: " + ", ".join(missing_terrain)
	set_enabled(false)

func set_enabled(enabled: bool) -> void:
	visible = enabled
	if enabled and not terrain_error.is_empty(): last_error = terrain_error
	elif not enabled and last_error == terrain_error: last_error = ""
	for body: StaticBody3D in find_children("*","StaticBody3D",true,false): body.collision_layer = 1 if enabled else 0
