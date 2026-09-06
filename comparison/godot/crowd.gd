extends Node3D
## Seven MultiMeshes; resident identities are lightweight records, never nodes.

class ResidentHandle extends RefCounted:
	var position: Vector3 = Vector3.ZERO
	var rotation: Vector3 = Vector3.ZERO
	var basis: Basis:
		get: return Basis(Vector3.UP, rotation.y)

var fixture: Dictionary
var routes: Dictionary
var residents: Array = []
var handles: Array[RefCounted] = []
var batches: Array[MultiMesh] = []
var materials: Array[ShaderMaterial] = []
var animated_indices: Dictionary = {}
var selected_index: int = -1
var visible_count: int = 0
var animated_count: int = 0


func initialize(scene: Dictionary, route_data: Dictionary) -> void:
	fixture = scene
	routes = route_data
	var points := PackedVector3Array()
	var lengths := PackedFloat32Array()
	var starts := Vector4i.ZERO
	var counts := Vector4i.ZERO
	var durations := Vector4.ZERO
	var totals := Vector4.ZERO
	for i: int in range(fixture.routes.size()):
		var route: Dictionary = fixture.routes[i]
		starts[i] = points.size()
		counts[i] = route.points.size()
		durations[i] = float(route.duration)
		totals[i] = float(routes[str(route.id)].total)
		for j: int in range(route.points.size()):
			var point: Array = route.points[j]
			points.append(Vector3(float(point[0]), float(point[1]), float(point[2])))
			lengths.append(float(routes[str(route.id)].lengths[j]) if j < route.points.size() - 1 else 0.0)
	points.resize(64)
	lengths.resize(64)
	for part: Dictionary in fixture.character.parts:
		var mesh: Mesh
		if str(part.kind) == "sphere":
			var sphere := SphereMesh.new()
			sphere.radius = 1.0
			sphere.height = 2.0
			sphere.radial_segments = 12
			sphere.rings = 6
			mesh = sphere
		else:
			var box := BoxMesh.new()
			box.size = Vector3.ONE
			mesh = box
		var material := ShaderMaterial.new()
		material.shader = preload("res://crowd.gdshader")
		for key: String in ["center", "pivot"]:
			var value: Array = part.get(key, part.center)
			material.set_shader_parameter("part_" + key, Vector3(float(value[0]), float(value[1]), float(value[2])))
		var size: Array = part.get("size", [part.get("radius", 1.0), part.get("radius", 1.0), part.get("radius", 1.0)])
		material.set_shader_parameter("part_size", Vector3(float(size[0]), float(size[1]), float(size[2])))
		material.set_shader_parameter("part_swing", float(part.get("swing", 0.0)))
		material.set_shader_parameter("route_points", points)
		material.set_shader_parameter("route_lengths", lengths)
		material.set_shader_parameter("route_start", starts)
		material.set_shader_parameter("route_count", counts)
		material.set_shader_parameter("route_duration", durations)
		material.set_shader_parameter("route_total", totals)
		var batch := MultiMesh.new()
		batch.transform_format = MultiMesh.TRANSFORM_3D
		batch.use_colors = true
		batch.use_custom_data = true
		batch.mesh = mesh
		var minimum: Array = fixture.bounds.min
		var maximum: Array = fixture.bounds.max
		batch.custom_aabb = AABB(Vector3(float(minimum[0])-3.0, -3.0, -float(maximum[1])-3.0), Vector3(float(maximum[0])-float(minimum[0])+6.0, 12.0, float(maximum[1])-float(minimum[1])+6.0))
		var instance := MultiMeshInstance3D.new()
		instance.name = "people-" + str(part.id)
		instance.multimesh = batch
		instance.material_override = material
		add_child(instance)
		batches.append(batch)
		materials.append(material)


func set_population(count: int) -> Array[RefCounted]:
	residents.clear()
	handles.clear()
	animated_indices.clear()
	selected_index = -1
	for i: int in range(count):
		var person: Dictionary = {
			"id": "resident-%03d" % i, "label": "Resident %03d" % (i + 1),
			"route_id": "route-%d" % (i % 4), "phase": fposmod(float(i) * 0.61803398875, 1.0),
			"color": fixture.resident_palette[i % 4], "skin_color": fixture.skin_palette[(i / 3) % 4],
			"trouser_color": [[0.08,0.12,0.18],[0.21,0.22,0.20]][i % 2],
			"bag_color": [[0.30,0.21,0.12],[0.15,0.18,0.20]][i % 2],
			"home": "Home block %02d" % (i % 10 + 1),
			"destination": "City Hall" if i % 4 == 3 else "Work block %02d" % ((i * 3) % 10 + 1),
		}
		residents.append(person)
		handles.append(ResidentHandle.new())
	for part_index: int in range(batches.size()):
		var batch: MultiMesh = batches[part_index]
		batch.instance_count = count
		var role: String = str(fixture.character.parts[part_index].color_role)
		var color_key: String = {"clothes":"color", "skin":"skin_color", "trousers":"trouser_color", "bag":"bag_color"}[role]
		for i: int in range(count):
			var rgb: Array = residents[i][color_key]
			batch.set_instance_transform(i, Transform3D.IDENTITY)
			batch.set_instance_color(i, Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0))
			batch.set_instance_custom_data(i, Color(float(i % 4), float(residents[i].phase), 0.0, 0.0))
	return handles


func update_all(time: float, camera: Camera3D, selected_id: String) -> void:
	var candidates: Array = []
	var frustum: Array[Plane] = camera.get_frustum() if camera != null else []
	visible_count = 0
	for i: int in range(residents.size()):
		var person: Dictionary = residents[i]
		var route: Dictionary = routes[str(person.route_id)]
		var distance: float = fposmod(time / float(route.duration) + float(person.phase), 1.0) * float(route.total)
		for j: int in range(route.lengths.size()):
			var length: float = float(route.lengths[j])
			if distance <= length or j == route.lengths.size() - 1:
				var a: Vector3 = route.points[j]
				var direction: Vector3 = route.points[j + 1] - a
				handles[i].position = a + direction * (distance / maxf(length, 0.0001))
				handles[i].rotation.y = atan2(-direction.x, -direction.z)
				break
			distance -= length
		if camera == null:
			continue
		var center: Vector3 = handles[i].position + Vector3.UP * 0.9
		var distance2: float = camera.position.distance_squared_to(center)
		if distance2 <= 6400.0:
			candidates.append([distance2, i])
		var visible: bool = true
		for plane: Plane in frustum:
			if plane.is_point_over(center):
				visible = false
				break
		if visible:
			visible_count += 1
	candidates.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0] if a[0] != b[0] else a[1] < b[1])
	var next_animated: Dictionary = {}
	for item: Array in candidates.slice(0, mini(300, candidates.size())):
		next_animated[int(item[1])] = true
	var next_selected: int = -1
	if selected_id.begins_with("resident-"):
		next_selected = int(selected_id.trim_prefix("resident-"))
	var changed: Dictionary = {}
	for i: int in animated_indices:
		if not next_animated.has(i): changed[i] = true
	for i: int in next_animated:
		if not animated_indices.has(i): changed[i] = true
	if next_selected != selected_index:
		if selected_index >= 0: changed[selected_index] = true
		if next_selected >= 0: changed[next_selected] = true
	for i: int in changed:
		if i >= residents.size(): continue
		for batch: MultiMesh in batches:
			batch.set_instance_custom_data(i, Color(float(i % 4), float(residents[i].phase), 1.0 if next_animated.has(i) else 0.0, 1.0 if i == next_selected else 0.0))
	animated_indices = next_animated
	selected_index = next_selected
	animated_count = animated_indices.size()
	for material: ShaderMaterial in materials:
		material.set_shader_parameter("simulation_time", time)
