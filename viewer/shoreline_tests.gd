extends SceneTree
const Shoreline = preload("res://terrain_shoreline.gd")
const Builder = preload("res://geography_mesh.gd")

func _initialize() -> void:
	var cell := Rect2(0,0,10,10)
	var bounds: Array[Rect2] = [cell]
	var pieces: Array = Shoreline.prepare([[PackedVector2Array([Vector2(0,0),Vector2(10,0),Vector2(0,10)])]],bounds,cell)
	var builder = Builder.new()
	var first: Array[Vector3] = [Vector3(0,20,-10),Vector3(10,10,0),Vector3(10,30,-10)]
	var second: Array[Vector3] = [Vector3(0,20,-10),Vector3(0,0,0),Vector3(10,10,0)]
	Shoreline.add_clipped_triangle(builder,first,pieces,Color.WHITE)
	Shoreline.add_clipped_triangle(builder,second,pieces,Color.WHITE)
	var failure: String = ""
	if Shoreline.cell_coverage(cell,pieces) != 1: failure = "A coastline cell was incorrectly treated as complete land."
	var area: float = 0.0
	for i: int in range(0,builder.vertices.size(),3):
		var a := Vector2(builder.vertices[i].x,-builder.vertices[i].z)
		var b := Vector2(builder.vertices[i+1].x,-builder.vertices[i+1].z)
		var c := Vector2(builder.vertices[i+2].x,-builder.vertices[i+2].z)
		area += absf((b-a).cross(c-a))*0.5
	for point: Vector3 in builder.vertices:
		if point.x-point.z > 10.0001: failure = "A terrain vertex extends across the observed shoreline."
		if absf(point.y-(point.x-2.0*point.z)) > 0.0001: failure = "Clipped shoreline vertices left their source triangle plane."
	if absf(area-50.0) > 0.0001: failure = "Shoreline clipping did not conserve observed land area."
	var island := PackedVector2Array([Vector2(3,3),Vector2(4,3),Vector2(4,4),Vector2(3,4)])
	var island_bounds: Array[Rect2] = [Rect2(3,3,1,1)]
	var island_pieces: Array = Shoreline.prepare([[island]],island_bounds,cell)
	if Shoreline.cell_coverage(cell,island_pieces) != 1: failure = "A small island disappeared between coarse raster sample centers."
	if failure.is_empty():
		print("GODOT_SHORELINE_TESTS_OK observed coast clipping, land area, terrain plane, small islands")
		quit(0)
	else:
		push_error(failure)
		quit(1)
