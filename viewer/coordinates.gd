extends RefCounted
## Domain coordinates are meters (east, north, up), Godot is (east, up, -north).

static func to_world(point: Array) -> Vector3:
	return Vector3(float(point[0]), float(point[2]), -float(point[1]))

static func to_domain(point: Vector3) -> Array:
	return [point.x, -point.z, point.y]
