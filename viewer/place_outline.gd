extends Node3D
## One selected source area, rendered as a terrain-draped map annotation.
const MAX_FILE_BYTES: int = 16 * 1024 * 1024
const MAX_SOURCE_POINTS: int = 250000
const MAX_SEGMENTS: int = 150000
const OUTLINE_SHADER = preload("res://place_outline.gdshader")
var terrain: Node3D
var available: bool = false
var last_error: String = ""
var selected_id: String = ""
var areas: Dictionary = {}
var instance: MeshInstance3D
var material: ShaderMaterial
var source_points: int = 0
var segment_count: int = 0
var skipped_segments: int = 0
var selection_center := Vector3.ZERO
var prepared_path: String = ""
var prepared_sha256: String = ""

func initialize(geography_path: String, places_manifest: Dictionary) -> bool:
	clear_selection()
	areas.clear()
	available = false
	last_error = ""
	prepared_path = ""
	var relative: String = str(places_manifest.get("areas_path",""))
	var checksum: String = str(places_manifest.get("areas_sha256",""))
	# The normalizer places this sidecar next to its checked geography/index.
	# Resolve the path before opening so an edited index cannot escape that folder.
	if relative.is_empty() or relative.is_absolute_path() or ":" in relative or "\\" in relative or ".." in relative.split("/"):
		last_error = "Selected-area geometry has an invalid relative path."
		return false
	var base: String = ProjectSettings.globalize_path(geography_path).get_base_dir().simplify_path()
	var path: String = base.path_join(relative).simplify_path()
	if not path.begins_with(base+"/") or not FileAccess.file_exists(path) or checksum.length() != 64:
		last_error = "Selected-area geometry is unavailable."
		return false
	var file := FileAccess.open(path,FileAccess.READ)
	if file == null or file.get_length() > MAX_FILE_BYTES:
		last_error = "Selected-area geometry exceeds its file limit."
		return false
	file.close()
	if FileAccess.get_sha256(path) != checksum:
		last_error = "Selected-area geometry checksum mismatch."
		return false
	prepared_path = path
	prepared_sha256 = checksum
	available = true
	return true

func configure(data: Dictionary) -> bool:
	clear_selection()
	areas.clear()
	source_points = 0
	available = false
	last_error = ""
	if int(data.get("schema_version",0)) != 1 or not data.get("areas") is Array or data.areas.size() > 4096:
		return _invalid("Selected-area geometry requires a bounded schema 1 area list.")
	var checked: Dictionary = {}
	var point_count: int = 0
	for item: Variant in data.areas:
		if not item is Dictionary or not item.get("id") is String or item.id.is_empty() or checked.has(item.id) or not item.get("polygons") is Array or item.polygons.is_empty():
			return _invalid("Selected-area IDs and polygon lists must be valid and unique.")
		for polygon: Variant in item.polygons:
			if not polygon is Dictionary or not polygon.get("rings") is Array or polygon.rings.is_empty():
				return _invalid("A selected-area polygon has no valid rings.")
			for ring: Variant in polygon.rings:
				if not ring is Array or ring.size() < 3:
					return _invalid("A selected-area ring has fewer than three points.")
				point_count += ring.size()
				if point_count > MAX_SOURCE_POINTS: return _invalid("Selected-area geometry exceeds its point limit.")
				for point: Variant in ring:
					if not point is Array or point.size() != 3: return _invalid("A selected-area point has invalid coordinates.")
					for coordinate: Variant in point:
						if (not coordinate is int and not coordinate is float) or not is_finite(float(coordinate)) or absf(float(coordinate)) > 100000.0:
							return _invalid("A selected-area coordinate is outside the supported finite bounds.")
		checked[item.id] = item.polygons.duplicate(true)
	areas = checked
	source_points = point_count
	available = true
	return true

func _invalid(message: String) -> bool:
	last_error = message
	return false

func _load_prepared() -> bool:
	if not areas.is_empty(): return true
	if prepared_path.is_empty(): return false
	if FileAccess.get_sha256(prepared_path) != prepared_sha256:
		available = false
		return _invalid("Selected-area geometry changed after initialization.")
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(prepared_path))
	if not parsed is Dictionary:
		available = false
		return _invalid("Selected-area geometry is not a JSON object.")
	return configure(parsed)

func show_place(record: Dictionary) -> bool:
	clear_selection()
	last_error = ""
	if str(record.get("kind","")) == "landmark": return false
	if not available or not _load_prepared(): return false
	var identity: String = str(record.get("id",""))
	if not areas.has(identity): return _invalid("The selected place has no checked area geometry.")
	var vertices := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var attempted_segments: int = 0
	for polygon: Dictionary in areas[identity]:
		for ring: Array in polygon.rings:
			for index: int in range(ring.size()):
				var a: Array = ring[index]
				var b: Array = ring[(index+1)%ring.size()]
				var horizontal := Vector2(float(b[0])-float(a[0]),float(b[1])-float(a[1]))
				if horizontal.length_squared() < 0.00000001: continue
				var fractions: Array[float] = [0.0,1.0]
				if terrain != null and terrain.available:
					fractions = terrain.segment_fractions(float(a[0]),float(a[1]),float(b[0]),float(b[1]))
				attempted_segments += fractions.size()-1
				if attempted_segments > MAX_SEGMENTS:
					clear_selection()
					return _invalid("The selected boundary exceeds its segment limit.")
				for part: int in range(fractions.size()-1):
					var start: Variant = _surface_point(a,b,fractions[part])
					var end: Variant = _surface_point(a,b,fractions[part+1])
					if start == null or end == null:
						skipped_segments += 1
						continue
					var direction: Vector3 = end-start
					direction.y = 0.0
					var side: Vector3 = direction.normalized().cross(Vector3.UP)
					for corner: int in [0,1,2,0,2,3]:
						vertices.append(start if corner < 2 else end)
						normals.append(side)
						uvs.append(Vector2(-1.0 if corner in [0,3] else 1.0,0.0))
					segment_count += 1
	if vertices.is_empty(): return _invalid("The selected boundary has no available terrain segments.")
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,arrays)
	material = ShaderMaterial.new()
	material.shader = OUTLINE_SHADER
	material.render_priority = 100
	material.set_shader_parameter("outline_color",Color("ffd06fe0") if str(record.kind) == "neighborhood" else Color("69e8c9e0"))
	instance = MeshInstance3D.new()
	instance.name = "SelectedSourceArea"
	instance.mesh = mesh
	instance.material_override = material
	instance.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	instance.extra_cull_margin = 20.0
	add_child(instance)
	selected_id = identity
	selection_center = mesh.get_aabb().get_center()
	return true

func _surface_point(a: Array, b: Array, fraction: float) -> Variant:
	var east: float = lerpf(float(a[0]),float(b[0]),fraction)
	var north: float = lerpf(float(a[1]),float(b[1]),fraction)
	var height: Variant = 0.0
	if terrain != null and terrain.available: height = terrain.display_height_at(east,north)
	if height == null: return null
	return Vector3(east,float(height)+0.3,-north)

func update_view(camera: Camera3D) -> void:
	if material == null or camera == null: return
	var distance: float = camera.global_position.distance_to(selection_center)
	material.set_shader_parameter("half_width_m",clampf(distance*0.0011,0.15,12.0))

func clear_selection() -> void:
	if is_instance_valid(instance): instance.free()
	instance = null
	material = null
	selected_id = ""
	segment_count = 0
	skipped_segments = 0

func get_state() -> Dictionary:
	return {"available":available,"selected_id":selected_id,"segments":segment_count,"missing_terrain_segments":skipped_segments,"error":last_error}
