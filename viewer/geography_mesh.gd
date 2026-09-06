extends RefCounted
## Merge an entire geographic tile into a handful of mesh surfaces.
const Coordinates = preload("res://coordinates.gd")
var vertices := PackedVector3Array()
var normals := PackedVector3Array()
var colors := PackedColorArray()
var use_coordinates := PackedVector2Array()
var facade_coordinates := PackedVector2Array()
var use_category: float = 8.0
var origin := Vector3.ZERO
var triangle_count: int = 0

func _init(local_origin: Vector3 = Vector3.ZERO) -> void:
	origin = local_origin

func triangle(a: Vector3, b: Vector3, c: Vector3, color: Color, normal: Vector3 = Vector3.ZERO, facade_uvs: Array[Vector2] = [], wall_span: float = 0.0) -> void:
	var has_facade_coordinates: bool = facade_uvs.size() == 3 or not facade_coordinates.is_empty()
	if has_facade_coordinates and facade_coordinates.is_empty(): facade_coordinates.resize(vertices.size())
	var cross: Vector3 = (b-a).cross(c-a)
	var face_normal: Vector3 = normal if normal.length_squared() > 0.0 else cross.normalized()
	# Godot's front faces are clockwise, opposite the conventional cross normal.
	var points: Array[Vector3] = [a,b,c]
	var ordered: Array = [0,2,1] if cross.dot(face_normal) > 0.0 else [0,1,2]
	for index: int in ordered:
		var point: Vector3 = points[index]
		vertices.append(point-origin)
		normals.append(face_normal)
		colors.append(color)
		use_coordinates.append(Vector2(use_category,wall_span))
		if has_facade_coordinates: facade_coordinates.append(facade_uvs[index] if facade_uvs.size() == 3 else Vector2.ZERO)
	triangle_count += 1

func polygon(points: Array, color: Color, height: float = 0.0, indices: Array = []) -> bool:
	var boundary := PackedVector2Array()
	var world_points: Array[Vector3] = []
	for point: Array in points:
		if point.size() < 2: return false
		boundary.append(Vector2(float(point[0]),float(point[1])))
		world_points.append(Vector3(float(point[0]),float(point[2]) + height if point.size() > 2 else height,-float(point[1])))
	if boundary.size() > 3 and boundary[0].is_equal_approx(boundary[-1]) and indices.is_empty():
		boundary.resize(boundary.size()-1)
		world_points.resize(world_points.size()-1)
	if boundary.size() < 3: return false
	var triangles := PackedInt32Array(indices)
	if triangles.is_empty(): triangles = Geometry2D.triangulate_polygon(boundary)
	if triangles.is_empty() or triangles.size() % 3 != 0: return false
	for i: int in range(0,triangles.size(),3):
		var ia: int = triangles[i]
		var ib: int = triangles[i+1]
		var ic: int = triangles[i+2]
		if mini(ia,mini(ib,ic)) < 0 or maxi(ia,maxi(ib,ic)) >= world_points.size(): return false
		triangle(world_points[ia],world_points[ib],world_points[ic],color,Vector3.UP)
	return true

func building(record: Dictionary, detailed: bool = true) -> bool:
	use_category = float(record.get("use_category",8))
	var points: Array = record.get("footprint",[])
	if points.size() < 3: return false
	var height: float = clampf(float(record.get("height_m",8.0)),0.25,600.0) if detailed else 0.12
	var roof: Color = Color("8e9d9d")
	if record.get("height_source","") in ["estimated","default"]: roof = Color("a3aaa1")
	var rings: Array = record.get("rings",[points])
	var indices: Array = record.get("roof_triangles",[])
	# A courtyard must not be silently filled. Without a hole-aware triangulation,
	# leave its roof open and retain outer/courtyard walls until better data arrives.
	if rings.size() <= 1 or not indices.is_empty():
		if not polygon(record.get("roof_vertices",points),roof,height,indices): return false
	if not detailed: return true
	for i: int in range(rings.size()):
		_building_walls(rings[i],height,i > 0)
	return true

func _building_walls(points: Array, height: float, courtyard: bool) -> void:
	var ring: Array = points.duplicate(false)
	if ring.size() > 3 and ring[0] == ring[-1]: ring.pop_back()
	var area: float = 0.0
	for i: int in range(ring.size()):
		var a: Array = ring[i]
		var b: Array = ring[(i+1)%ring.size()]
		area += float(a[0])*float(b[1])-float(b[0])*float(a[1])
	for i: int in range(ring.size()):
		var a: Vector3 = Coordinates.to_world(ring[i])
		var b: Vector3 = Coordinates.to_world(ring[(i+1)%ring.size()])
		var normal: Vector3 = (b-a).cross(Vector3.UP).normalized() * (1.0 if area >= 0.0 else -1.0) * (-1.0 if courtyard else 1.0)
		var upper_a: Vector3 = a + Vector3.UP*height
		var upper_b: Vector3 = b + Vector3.UP*height
		var span: float = Vector2(b.x-a.x,b.z-a.z).length()
		triangle(a,b,upper_b,Color("b2b6ac"),normal,[Vector2.ZERO,Vector2(span,0.0),Vector2(span,height)],span)
		triangle(a,upper_b,upper_a,Color("b2b6ac"),normal,[Vector2.ZERO,Vector2(span,height),Vector2(0.0,height)],span)

func street(record: Dictionary, color: Color = Color("616e73"), elevation: float = 0.05) -> bool:
	var points: Array = record.get("points",[])
	var width: float = clampf(float(record.get("width_m",8.0)),0.5,80.0)
	if points.size() < 2: return false
	for i: int in range(points.size()-1):
		var a: Vector3 = Coordinates.to_world(points[i]) + Vector3.UP*elevation
		var b: Vector3 = Coordinates.to_world(points[i+1]) + Vector3.UP*elevation
		var direction: Vector3 = b-a
		direction.y = 0.0
		if direction.length_squared() < 0.00001: continue
		var offset: Vector3 = direction.normalized().cross(Vector3.UP) * width * 0.5
		triangle(a-offset,a+offset,b+offset,color,Vector3.UP)
		triangle(a-offset,b+offset,b-offset,color,Vector3.UP)
	return true

func array_payload() -> Dictionary:
	return {"origin":origin,"vertices":vertices,"normals":normals,"colors":colors,"use_coordinates":use_coordinates,"facade_coordinates":facade_coordinates,"triangle_count":triangle_count}

func apply_array_payload(payload: Dictionary) -> bool:
	if not payload.get("origin") is Vector3 or not payload.origin.is_finite(): return false
	if not payload.get("vertices") is PackedVector3Array or not payload.get("normals") is PackedVector3Array or not payload.get("colors") is PackedColorArray: return false
	if not payload.get("use_coordinates") is PackedVector2Array or not payload.get("facade_coordinates") is PackedVector2Array: return false
	if not payload.get("triangle_count") is int: return false
	var size_value: int = payload.vertices.size()
	if size_value % 3 != 0 or size_value > 3000000 or payload.triangle_count != size_value / 3: return false
	if payload.normals.size() != size_value or payload.colors.size() != size_value or payload.use_coordinates.size() != size_value: return false
	if payload.facade_coordinates.size() != 0 and payload.facade_coordinates.size() != size_value: return false
	for point: Vector3 in payload.vertices:
		if not point.is_finite(): return false
	for normal: Vector3 in payload.normals:
		if not normal.is_finite(): return false
	for uv: Vector2 in payload.use_coordinates:
		if not uv.is_finite(): return false
	for uv: Vector2 in payload.facade_coordinates:
		if not uv.is_finite(): return false
	for color: Color in payload.colors:
		if not is_finite(color.r) or not is_finite(color.g) or not is_finite(color.b) or not is_finite(color.a): return false
	origin = payload.origin
	vertices = payload.vertices
	normals = payload.normals
	colors = payload.colors
	use_coordinates = payload.use_coordinates
	facade_coordinates = payload.facade_coordinates
	triangle_count = int(payload.triangle_count)
	return true

func create_instance(name_value: String, material: Material) -> MeshInstance3D:
	if vertices.is_empty(): return null
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_COLOR] = colors
	arrays[Mesh.ARRAY_TEX_UV] = use_coordinates
	if not facade_coordinates.is_empty(): arrays[Mesh.ARRAY_TEX_UV2] = facade_coordinates
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,arrays)
	var instance := MeshInstance3D.new()
	instance.name = name_value
	instance.mesh = mesh
	instance.position = origin
	instance.material_override = material
	return instance

static func surface_material(unshaded: bool = false) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.vertex_color_use_as_albedo = true
	material.roughness = 0.94
	material.cull_mode = BaseMaterial3D.CULL_BACK
	if unshaded: material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	return material
