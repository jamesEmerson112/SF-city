extends RefCounted
## Clip terrain triangles to observed coast geometry, preserving their planes.

static func rectangle(bounds: Rect2) -> PackedVector2Array:
	return PackedVector2Array([bounds.position,Vector2(bounds.end.x,bounds.position.y),bounds.end,Vector2(bounds.position.x,bounds.end.y)])

static func polygon_bounds(polygon: PackedVector2Array) -> Rect2:
	var result := Rect2(polygon[0],Vector2.ZERO)
	for point: Vector2 in polygon: result = result.expand(point)
	return result

static func prepare(polygons: Array, bounds_list: Array[Rect2], chunk: Rect2) -> Array:
	var result: Array = []
	var region: PackedVector2Array = rectangle(chunk)
	for i: int in range(polygons.size()):
		if not bounds_list[i].intersects(chunk,true): continue
		var rings: Array = polygons[i]
		var holes: Array = []
		for j: int in range(1,rings.size()):
			var hole_bounds: Rect2 = polygon_bounds(rings[j])
			if hole_bounds.intersects(chunk,true): holes.append({"polygon":rings[j],"bounds":hole_bounds})
		for polygon: PackedVector2Array in Geometry2D.intersect_polygons(rings[0],region):
			if polygon.size() < 3: continue
			result.append({"polygon":polygon,"bounds":polygon_bounds(polygon),"holes":holes})
	return result

static func cell_coverage(cell: Rect2, pieces: Array) -> int:
	# 0 is water, 1 is a coastline cell, 2 lies fully inside one land polygon.
	var intersects: bool = false
	var corners: PackedVector2Array = rectangle(cell)
	for piece: Dictionary in pieces:
		if not piece.bounds.intersects(cell,true): continue
		intersects = true
		var fully_inside: bool = true
		for point: Vector2 in corners:
			if not Geometry2D.is_point_in_polygon(point,piece.polygon):
				fully_inside = false
				break
		for hole: Dictionary in piece.holes:
			if hole.bounds.intersects(cell,true): fully_inside = false
		# A concave inlet can lie between four land corners of a coarse cell.
		for point: Vector2 in piece.polygon:
			if point.x > cell.position.x+0.0001 and point.x < cell.end.x-0.0001 and point.y > cell.position.y+0.0001 and point.y < cell.end.y-0.0001:
				fully_inside = false
				break
		if fully_inside: return 2
	return 1 if intersects else 0

static func add_clipped_triangle(builder: RefCounted, vertices: Array[Vector3], pieces: Array, color: Color) -> void:
	var a := Vector2(vertices[0].x,-vertices[0].z)
	var b := Vector2(vertices[1].x,-vertices[1].z)
	var c := Vector2(vertices[2].x,-vertices[2].z)
	var triangle := PackedVector2Array([a,b,c])
	var bounds: Rect2 = polygon_bounds(triangle)
	var denominator: float = (b-a).cross(c-a)
	if absf(denominator) < 0.000001: return
	for piece: Dictionary in pieces:
		if not piece.bounds.intersects(bounds,true): continue
		for polygon: PackedVector2Array in Geometry2D.intersect_polygons(triangle,piece.polygon):
			if polygon.size() < 3: continue
			# Never fill an inner water ring. The current observed SF land source
			# has no such rings; conservative omission handles optional future data.
			var crosses_hole: bool = false
			for hole: Dictionary in piece.holes:
				if hole.bounds.intersects(polygon_bounds(polygon),true): crosses_hole = true
			if crosses_hole: continue
			var points: Array = []
			for point: Vector2 in polygon:
				var weight_b: float = (point-a).cross(c-a)/denominator
				var weight_c: float = (b-a).cross(point-a)/denominator
				var elevation: float = vertices[0].y*(1.0-weight_b-weight_c)+vertices[1].y*weight_b+vertices[2].y*weight_c
				points.append([point.x,point.y,elevation])
			builder.polygon(points,color)
