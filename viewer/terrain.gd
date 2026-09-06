extends Node3D
## North-to-south elevation grid. No interpolation through missing samples.
const Builder = preload("res://geography_mesh.gd")
const Shoreline = preload("res://terrain_shoreline.gd")
const RenderCache = preload("res://scenery_cache.gd")
const CHUNK_SAMPLES: int = 64
const CACHE_VERSION: int = 1
var data: Dictionary = {}
var available: bool = false
var last_error: String = ""
var width: int = 0
var height: int = 0
var values: Array = []
var minimum := Vector2.ZERO
var maximum := Vector2.ZERO
var step := Vector2.ONE
var origin_elevation_m: float = 0.0
var pilot_enabled: bool = true
var land_polygons: Array = []
var land_bounds: Array[Rect2] = []
var chunks: Dictionary = {}
var pending: Array[Vector2i] = []
var detailed_pending: Array[Vector2i] = []
var mesh_material: StandardMaterial3D
var last_focus := Vector3(INF,INF,INF)
var detailed_chunks: int = 0
var terrain_triangle_count: int = 0
var min_east: float = 0.0
var max_east: float = 0.0
var min_north: float = 0.0
var max_north: float = 0.0
var step_east: float = 1.0
var step_north: float = 1.0
var shore_chunks: Dictionary = {}
var render_cache = RenderCache.new()
var terrain_digest: String = ""
var land_digest: String = ""
var builder_digest: String = ""
var invalid_cache_payloads: int = 0

func configure_render_cache(directory: String, enabled: bool = true) -> void:
	render_cache.configure(directory)
	render_cache.enabled = enabled and not directory.is_empty()

func set_cache_directory(directory: String) -> void:
	configure_render_cache(directory)

func set_cache_enabled(enabled: bool) -> void:
	render_cache.enabled = enabled

func cache_stats() -> Dictionary:
	var result: Dictionary = render_cache.statistics()
	result["invalid_payloads"] = invalid_cache_payloads
	return result

func get_cache_state() -> Dictionary:
	return cache_stats()

func cache_identity() -> Dictionary:
	# Hash the grid and normalized shoreline only when their source changes.
	# Keep the live source grid intact for camera, route, and ground queries.
	return {"namespace":"terrain", "version":CACHE_VERSION, "godot":Engine.get_version_info().get("string",""), "builder_sha256":builder_digest, "terrain_sha256":terrain_digest, "shoreline_sha256":land_digest, "pilot":pilot_enabled}

static func _digest(value: Variant) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes(value))
	return context.finish().hex_encode()

func initialize(path: String) -> bool:
	if path.is_empty() or not FileAccess.file_exists(path): return false
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or not configure(parsed):
		if last_error.is_empty(): last_error = "Terrain file is not a valid version 1 grid."
		return false
	mesh_material = Builder.surface_material()
	return true

func configure(config: Dictionary) -> bool:
	if int(config.get("schema_version",0)) != 1: return false
	width = int(config.get("width",0))
	height = int(config.get("height",0))
	if width < 2 or height < 2 or width > 8192 or height > 8192: return false
	if not config.get("elevations_m") is Array or config.elevations_m.size() != width*height: return false
	if not config.get("bounds") is Dictionary or not config.bounds.get("min") is Array or not config.bounds.get("max") is Array: return false
	if config.bounds.min.size() != 2 or config.bounds.max.size() != 2: return false
	minimum = Vector2(float(config.bounds.min[0]),float(config.bounds.min[1]))
	maximum = Vector2(float(config.bounds.max[0]),float(config.bounds.max[1]))
	min_east = float(config.bounds.min[0])
	min_north = float(config.bounds.min[1])
	max_east = float(config.bounds.max[0])
	max_north = float(config.bounds.max[1])
	if not minimum.is_finite() or not maximum.is_finite() or minimum.x >= maximum.x or minimum.y >= maximum.y: return false
	origin_elevation_m = float(config.get("origin_elevation_m",0.0))
	if not is_finite(origin_elevation_m): return false
	values = config.elevations_m
	for value: Variant in values:
		if value != null and (not (value is float or value is int) or not is_finite(float(value))): return false
	step = Vector2((maximum.x-minimum.x)/float(width-1),(maximum.y-minimum.y)/float(height-1))
	step_east = (max_east-min_east)/float(width-1)
	step_north = (max_north-min_north)/float(height-1)
	data = config
	available = true
	terrain_digest = _digest([width,height,min_east,min_north,max_east,max_north,origin_elevation_m,values])
	if builder_digest.is_empty():
		builder_digest = _digest([RenderCache.file_digest("res://terrain.gd"),RenderCache.file_digest("res://terrain_shoreline.gd"),RenderCache.file_digest("res://geography_mesh.gd")])
	shore_chunks.clear()
	_restart_meshes()
	return true

func height_at(east: float, north: float) -> Variant:
	if not available or not is_finite(east) or not is_finite(north) or east < min_east or east > max_east or north < min_north or north > max_north: return null
	var column: float = minf((east-min_east)/step_east,float(width-1))
	var row: float = minf((max_north-north)/step_north,float(height-1))
	var left: int = mini(int(column),width-2)
	var top: int = mini(int(row),height-2)
	var fraction_x: float = column-left
	var fraction_y: float = row-top
	var neighbors: Array = [[top*width+left,(1.0-fraction_x)*(1.0-fraction_y)],[top*width+left+1,fraction_x*(1.0-fraction_y)],[(top+1)*width+left,(1.0-fraction_x)*fraction_y],[(top+1)*width+left+1,fraction_x*fraction_y]]
	var result: float = 0.0
	for neighbor: Array in neighbors:
		var weight: float = float(neighbor[1])
		if weight <= 0.000000000001: continue
		var value: Variant = values[int(neighbor[0])]
		if value == null: return null
		result += float(value)*weight
	return result-origin_elevation_m

func display_height_at(east: float,north: float) -> Variant:
	var value: Variant = triangle_height_at(east,north)
	if value == null or not pilot_enabled: return value
	var outside := Vector2(maxf(absf(east)-205.0,0.0),maxf(absf(north)-185.0,0.0))
	var factor: float = smoothstep(0.0,150.0,outside.length())
	return float(value)*factor

func triangle_height_at(east: float,north: float) -> Variant:
	# The source-resolution mesh splits every cell along its NW-to-SE diagonal.
	# This is also the authoritative city route surface, independent of visual LOD.
	if not available or not is_finite(east) or not is_finite(north) or east < min_east or east > max_east or north < min_north or north > max_north: return null
	var column: float = minf((east-min_east)/step_east,float(width-1))
	var row: float = minf((max_north-north)/step_north,float(height-1))
	var left: int = mini(int(column),width-2)
	var top: int = mini(int(row),height-2)
	var u: float = column-left
	var v: float = row-top
	var neighbors: Array
	if u >= v:
		neighbors = [[top*width+left,1.0-u],[top*width+left+1,u-v],[(top+1)*width+left+1,v]]
	else:
		neighbors = [[top*width+left,1.0-v],[(top+1)*width+left,v-u],[(top+1)*width+left+1,u]]
	var result: float = 0.0
	for neighbor: Array in neighbors:
		var weight: float = float(neighbor[1])
		if weight <= 0.000000000001: continue
		var value: Variant = values[int(neighbor[0])]
		if value == null: return null
		result += float(value)*weight
	return result-origin_elevation_m

func segment_fractions(east_a: float,north_a: float,east_b: float,north_b: float) -> Array[float]:
	# Break a line at every raster-cell edge and NW-SE diagonal. Linear travel
	# between these points then stays on a single source terrain triangle.
	var result: Array[float] = [0.0,1.0]
	if not available: return result
	var column_a: float = (east_a-min_east)/step_east
	var row_a: float = (max_north-north_a)/step_north
	var column_delta: float = (east_b-east_a)/step_east
	var row_delta: float = (north_a-north_b)/step_north
	for axis: Array in [[column_a,column_delta],[row_a,row_delta]]:
		var start: float = float(axis[0])
		var change: float = float(axis[1])
		if absf(change) < 0.000000000001: continue
		for grid_line: int in range(int(ceil(minf(start,start+change))),int(floor(maxf(start,start+change)))+1):
			var fraction: float = (float(grid_line)-start)/change
			if fraction > 0.000000001 and fraction < 0.999999999: result.append(fraction)
	result.sort()
	var diagonal_delta: float = column_delta-row_delta
	if absf(diagonal_delta) > 0.000000000001:
		var grid_breaks: Array[float] = result.duplicate()
		for i: int in range(grid_breaks.size()-1):
			var middle: float = (grid_breaks[i]+grid_breaks[i+1])*0.5
			var column: int = int(floor(column_a+column_delta*middle))
			var row: int = int(floor(row_a+row_delta*middle))
			var fraction: float = (float(column-row)-column_a+row_a)/diagonal_delta
			if fraction > grid_breaks[i]+0.000000001 and fraction < grid_breaks[i+1]-0.000000001: result.append(fraction)
	# Also retain modest spacing for the synthetic pilot's blended ground patch.
	var divisions: int = maxi(1,int(ceil(sqrt(pow(east_b-east_a,2)+pow(north_b-north_a,2))/15.0)))
	for i: int in range(1,divisions): result.append(float(i)/float(divisions))
	result.sort()
	var unique: Array[float] = []
	for fraction: float in result:
		if unique.is_empty() or fraction-unique[-1] > 0.000000001: unique.append(fraction)
	return unique

func set_pilot_mode(enabled: bool) -> void:
	if pilot_enabled == enabled: return
	pilot_enabled = enabled
	_restart_meshes()

func set_land(polygons: Array) -> void:
	shore_chunks.clear()
	land_polygons.clear()
	land_bounds.clear()
	for polygon: Dictionary in polygons:
		var rings: Array = polygon.get("rings",[])
		if rings.is_empty() and polygon.get("points") is Array: rings = [polygon.points]
		if rings.is_empty(): continue
		var prepared: Array = []
		var bounds := Rect2()
		for i: int in range(rings.size()):
			var ring := PackedVector2Array()
			for point: Array in rings[i]: ring.append(Vector2(float(point[0]),float(point[1])))
			if ring.size() < 3: continue
			if i == 0:
				bounds = Rect2(ring[0],Vector2.ZERO)
				for point: Vector2 in ring: bounds = bounds.expand(point)
			prepared.append(ring)
		if not prepared.is_empty():
			land_polygons.append(prepared)
			land_bounds.append(bounds)
	land_digest = _digest(land_polygons)
	_restart_meshes()

func _restart_meshes() -> void:
	for chunk: Dictionary in chunks.values(): chunk.root.queue_free()
	chunks = {}
	pending.clear()
	detailed_pending.clear()
	terrain_triangle_count = 0
	detailed_chunks = 0
	last_focus = Vector3(INF,INF,INF)
	if not available or land_polygons.is_empty(): return
	for row: int in range(0,height-1,CHUNK_SAMPLES):
		for column: int in range(0,width-1,CHUNK_SAMPLES): pending.append(Vector2i(column,row))

func _on_land(east: float,north: float) -> bool:
	var point := Vector2(east,north)
	for i: int in range(land_polygons.size()):
		if not land_bounds[i].has_point(point): continue
		var rings: Array = land_polygons[i]
		if not Geometry2D.is_point_in_polygon(point,rings[0]): continue
		var hole: bool = false
		for j: int in range(1,rings.size()):
			if Geometry2D.is_point_in_polygon(point,rings[j]): hole = true
		if not hole: return true
	return false

func update_view(focus: Vector3, zoom: float) -> void:
	if not available: return
	if last_focus.distance_squared_to(focus) > 40000.0:
		last_focus = focus
		pending.sort_custom(func(a: Vector2i,b: Vector2i) -> bool: return _chunk_distance(a,focus) < _chunk_distance(b,focus))
	if not pending.is_empty():
		_build_chunk(pending.pop_front(),4)
	elif not detailed_pending.is_empty():
		var key: Vector2i = detailed_pending.pop_front()
		if _chunk_distance(key,focus) < 1700.0 and zoom < 2500.0: _build_chunk(key,1)
	detailed_chunks = 0
	for key: Vector2i in chunks:
		var chunk: Dictionary = chunks[key]
		var detailed: bool = zoom < 2500.0 and _chunk_distance(key,focus) < 1700.0
		if detailed and not bool(chunk.high_built) and not key in detailed_pending: detailed_pending.append(key)
		if chunk.high != null: chunk.high.visible = detailed
		if chunk.low != null: chunk.low.visible = not detailed or chunk.high == null
		if detailed and chunk.high != null: detailed_chunks += 1

func _chunk_distance(key: Vector2i,focus: Vector3) -> float:
	var center := Vector2(minimum.x+(key.x+CHUNK_SAMPLES*0.5)*step.x,maximum.y-(key.y+CHUNK_SAMPLES*0.5)*step.y)
	return center.distance_to(Vector2(focus.x,-focus.z))

func _build_chunk(key: Vector2i,stride: int) -> void:
	if not available or not stride in [1,4] or key.x < 0 or key.y < 0 or key.x >= width-1 or key.y >= height-1: return
	var origin := Vector3(min_east+key.x*step_east,0.0,-(max_north-key.y*step_north))
	var builder = Builder.new(origin)
	var identity: Dictionary = cache_identity()
	identity["chunk"] = key
	identity["stride"] = stride
	var cached: Dictionary = render_cache.read_entry(identity)
	var loaded: bool = not cached.is_empty() and builder.apply_array_payload(cached)
	if loaded and builder.origin != origin: loaded = false
	if not loaded:
		if not cached.is_empty():
			invalid_cache_payloads += 1
			render_cache.reject_entry("Prepared terrain arrays are invalid; rebuilding this chunk.")
		builder = Builder.new(origin)
		_fill_chunk_builder(key,stride,builder)
		render_cache.write_entry(identity,builder.array_payload())
	if not chunks.has(key):
		var chunk_root := Node3D.new()
		chunk_root.name = "Terrain-%d-%d" % [key.x,key.y]
		add_child(chunk_root)
		chunks[key] = {"root":chunk_root,"low":null,"high":null,"high_built":false}
	var mesh: MeshInstance3D = builder.create_instance("TerrainStride%d"%stride,mesh_material)
	if mesh != null: chunks[key].root.add_child(mesh)
	chunks[key]["low" if stride == 4 else "high"] = mesh
	if stride != 4: chunks[key].high_built = true
	terrain_triangle_count += builder.triangle_count

func _fill_chunk_builder(key: Vector2i,stride: int,builder: RefCounted) -> void:
	var last_row: int = mini(key.y+CHUNK_SAMPLES,height-1)
	var last_column: int = mini(key.x+CHUNK_SAMPLES,width-1)
	if not shore_chunks.has(key):
		var south_west := Vector2(min_east+key.x*step_east,max_north-last_row*step_north)
		var chunk_size := Vector2((last_column-key.x)*step_east,(last_row-key.y)*step_north)
		shore_chunks[key] = Shoreline.prepare(land_polygons,land_bounds,Rect2(south_west,chunk_size))
	var shore: Array = shore_chunks[key]
	for row: int in range(key.y,last_row,stride):
		for column: int in range(key.x,last_column,stride):
			var bottom: int = mini(row+stride,last_row)
			var right: int = mini(column+stride,last_column)
			var coordinates: Array = [[column,row],[right,row],[right,bottom],[column,bottom]]
			var cell_bounds := Rect2(Vector2(min_east+column*step_east,max_north-bottom*step_north),Vector2((right-column)*step_east,(bottom-row)*step_north))
			var coverage: int = Shoreline.cell_coverage(cell_bounds,shore)
			if coverage == 0: continue
			var points: Array[Vector3] = []
			for coordinate: Array in coordinates:
				var east: float = min_east+float(coordinate[0])*step_east
				var north: float = max_north-float(coordinate[1])*step_north
				var elevation: Variant = display_height_at(east,north)
				if elevation == null: break
				points.append(Vector3(east,float(elevation)-0.08,-north))
			if points.size() != 4: continue
			var color: Color = Color("8a9a81").lerp(Color("809178"),clampf((points[0].y+origin_elevation_m)/250.0,0.0,1.0))
			if coverage == 2:
				builder.triangle(points[0],points[2],points[1],color)
				builder.triangle(points[0],points[3],points[2],color)
			else:
				var first: Array[Vector3] = [points[0],points[2],points[1]]
				var second: Array[Vector3] = [points[0],points[3],points[2]]
				Shoreline.add_clipped_triangle(builder,first,shore,color)
				Shoreline.add_clipped_triangle(builder,second,shore,color)

func get_state() -> Dictionary:
	return {"available":available,"width":width,"height":height,"loaded_chunks":chunks.size(),"pending_chunks":pending.size(),"detailed_chunks":detailed_chunks,"triangles":terrain_triangle_count,"origin_elevation_m":origin_elevation_m,"pilot_patch":pilot_enabled,"land_mask":not land_polygons.is_empty(),"error":last_error}
