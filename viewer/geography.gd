extends Node3D
## Optional observed geographic context. Resident domains remain owned by Python.
## Tile files load on demand; there is never one Node3D per source building.
const Builder = preload("res://geography_mesh.gd")
const Coordinates = preload("res://coordinates.gd")
const SceneryCache = preload("res://scenery_cache.gd")
const CACHE_LIMIT: int = 48
const DETAIL_DISTANCE: float = 1700.0
const FLAT_DISTANCE: float = 2800.0
var render_cache = SceneryCache.new()
var cache_sources: Dictionary = {}
var generated_tiles: int = 0
var restored_tiles: int = 0
var manifest: Dictionary = {}
var manifest_directory: String = ""
var available: bool = false
var facades_enabled: bool = true
var last_error: String = ""
var landmark_error: String = ""
var tiles: Dictionary = {}
var loaded: Dictionary = {}
var requests: Array[String] = []
var wanted: Dictionary = {}
var last_focus := Vector3(INF,INF,INF)
var last_zoom: float = -1.0
var update_elapsed: float = 1.0
var visible_tiles: int = 0
var detailed_tiles: int = 0
var loaded_buildings: int = 0
var missing_tiles: int = 0
var skipped_polygons: int = 0
var roofs_omitted_for_holes: int = 0
var overview: Node3D
var pilot_exclusion: Dictionary = {"min":[-205,-185],"max":[205,185]}
var terrain_material: StandardMaterial3D
var building_material: ShaderMaterial
var overview_material: StandardMaterial3D
var terrain: Node3D
var pilot_enabled: bool = true
var overview_roads: MeshInstance3D
var landmark_records: Dictionary = {}
var visual_context: Node3D
var use_context := preload("res://geography_use.gd").new()

func configure_render_cache(directory: String,enabled: bool = true) -> void:
	render_cache.configure(directory)
	render_cache.enabled = enabled and not directory.is_empty()

func cache_stats() -> Dictionary:
	var result: Dictionary = render_cache.statistics()
	result["generated_tiles"] = generated_tiles
	result["restored_tiles"] = restored_tiles
	return result

func initialize(path: String) -> bool:
	if path.is_empty() or not FileAccess.file_exists(path): return false
	var parser := JSON.new()
	if parser.parse(FileAccess.get_file_as_string(path)) != OK or not parser.data is Dictionary:
		last_error = "Geography manifest is not valid JSON."
		return false
	manifest = parser.data
	if int(manifest.get("schema_version",0)) != 1 or not _valid_bounds(manifest.get("bounds")) or not manifest.get("tiles") is Array:
		last_error = "Geography manifest needs schema_version 1, bounds and tiles."
		return false
	manifest_directory = ProjectSettings.globalize_path(path).get_base_dir().simplify_path()
	pilot_exclusion = manifest.get("pilot_exclusion_bounds",pilot_exclusion)
	terrain_material = Builder.surface_material()
	use_context.initialize(path)
	building_material = use_context.make_material()
	building_material.set_shader_parameter("facades_enabled",facades_enabled)
	overview_material = Builder.surface_material(true)
	for descriptor: Dictionary in manifest.tiles:
		if str(descriptor.get("id","")).is_empty() or not _valid_bounds(descriptor.get("bounds")): continue
		tiles[str(descriptor.id)] = descriptor
	visual_context = preload("res://geography_visuals.gd").new()
	visual_context.terrain = terrain
	visual_context.landmark_ids = landmark_records
	visual_context.use_context = use_context
	add_child(visual_context)
	visual_context.initialize(path)
	cache_sources = {"schema":1,"godot":Engine.get_version_info().get("string",""),"manifest":SceneryCache.file_digest(path)}
	for source: String in ["res://geography.gd","res://geography_mesh.gd","res://coordinates.gd","res://geography_visuals.gd","res://geography_use.gd","res://scenery_cache.gd"]:
		cache_sources[source] = SceneryCache.file_digest(source)
	for source: String in ["visual-index.json","use-index.json"]:
		cache_sources[source] = SceneryCache.file_digest(manifest_directory.path_join(source))
	_build_overview()
	available = true
	return true

func set_use_overlay(enabled: bool) -> void:
	use_context.enabled = enabled and use_context.available
	if building_material != null: building_material.set_shader_parameter("use_overlay",use_context.enabled)
	if visual_context != null and visual_context.material != null:
		visual_context.material.set_shader_parameter("use_overlay",use_context.enabled)

func building_use(identifier: String) -> Dictionary:
	return use_context.record_for(identifier.trim_prefix("geography:"))

func set_facades(enabled: bool) -> void:
	facades_enabled = enabled
	if building_material != null: building_material.set_shader_parameter("facades_enabled",enabled)

func set_pilot_mode(enabled: bool) -> void:
	if pilot_enabled == enabled: return
	pilot_enabled = enabled
	if visual_context != null: visual_context.set_pilot_mode(enabled)
	pilot_exclusion = manifest.get("pilot_exclusion_bounds",{"min":[-205,-185],"max":[205,185]}) if enabled else {}
	for chunk: Dictionary in loaded.values(): chunk.root.queue_free()
	loaded.clear()
	requests.clear()
	wanted.clear()
	loaded_buildings = 0
	visible_tiles = 0
	detailed_tiles = 0
	last_zoom = -1.0
	last_focus = Vector3(INF,INF,INF)
	if overview != null:
		overview.queue_free()
		_build_overview()

func _valid_bounds(value: Variant) -> bool:
	if not value is Dictionary or not value.get("min") is Array or not value.get("max") is Array: return false
	if value.min.size() < 2 or value.max.size() < 2: return false
	for axis: int in range(2):
		if not is_finite(float(value.min[axis])) or not is_finite(float(value.max[axis])) or float(value.min[axis]) >= float(value.max[axis]): return false
	return true

func _build_overview() -> void:
	overview = Node3D.new()
	overview.name = "GeographicOverview"
	add_child(overview)
	var land = Builder.new()
	if terrain == null or not terrain.available:
		for polygon: Dictionary in manifest.get("land",[]):
			var points: Array = polygon.get("points",[])
			if points.is_empty() and polygon.get("rings",[]).size() > 0: points = polygon.rings[0]
			if not land.polygon(points,Color("7a9188"),-0.15,polygon.get("triangles",[])): skipped_polygons += 1
	var ground: MeshInstance3D = land.create_instance("ObservedLand",overview_material)
	if ground != null:
		overview.add_child(ground)
		ground.visible = terrain == null or not terrain.available
	overview_roads = null
	# Flat water only supplies a neutral backdrop; it is not an elevation model.
	var bounds: Dictionary = manifest.bounds
	var water = Builder.new()
	var margin: float = maxf(float(bounds.max[0])-float(bounds.min[0]),float(bounds.max[1])-float(bounds.min[1]))*3.0
	var water_height: float = -float(terrain.origin_elevation_m) if terrain != null and terrain.available else -0.8
	water.polygon([[float(bounds.min[0])-margin,float(bounds.min[1])-margin,water_height],[float(bounds.max[0])+margin,float(bounds.min[1])-margin,water_height],[float(bounds.max[0])+margin,float(bounds.max[1])+margin,water_height],[float(bounds.min[0])-margin,float(bounds.max[1])+margin,water_height]],Color("506f7d"))
	var sea: MeshInstance3D = water.create_instance("MapWaterBackdrop",overview_material)
	if sea != null: overview.add_child(sea)

func _build_overview_roads() -> void:
	var streets = Builder.new()
	for street: Dictionary in manifest.get("overview_streets",[]):
		# The distant street map is an overlay. Source vertices suffice here;
		# exact raster-plane crossings remain necessary for near road surfaces.
		_add_street_segments(streets,street,Color("44565c"),0.015,{},false)
	var road_overlay: StandardMaterial3D = Builder.surface_material(true)
	road_overlay.no_depth_test = true
	road_overlay.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	road_overlay.render_priority = 1
	overview_roads = streets.create_instance("ObservedStreetOverview",road_overlay)
	if overview_roads != null: overview.add_child(overview_roads)

func update_view(camera: Camera3D, focus: Vector3, zoom: float, delta: float) -> void:
	if not available: return
	if zoom > 4500.0 and overview_roads == null: _build_overview_roads()
	if overview_roads != null: overview_roads.visible = zoom > 4500.0
	update_elapsed += delta
	var refresh_visibility: bool = update_elapsed >= 0.2 or last_focus.distance_squared_to(focus) > 2500.0 or absf(zoom-last_zoom) > 200.0
	if refresh_visibility:
		update_elapsed = 0.0
		last_focus = focus
		last_zoom = zoom
		_select_tiles(focus,zoom)
	# At most one tile is decoded and merged per frame. Distant cache entries
	# are released before another tile is loaded, bounding scene/GPU residency.
	if not requests.is_empty():
		var identifier: String = requests.pop_front()
		if wanted.has(identifier) and not loaded.has(identifier):
			_evict_cache()
			_load_tile(identifier)
			refresh_visibility = true
	if refresh_visibility:
		visible_tiles = 0
		detailed_tiles = 0
		for identifier: String in loaded:
			var record: Dictionary = loaded[identifier]
			var visible: bool = wanted.has(identifier)
			var detail: bool = visible and float(wanted.get(identifier,INF)) <= DETAIL_DISTANCE and zoom < 2000.0
			record.root.visible = visible
			if record.high != null: record.high.visible = detail
			if record.low != null: record.low.visible = visible and not detail
			if visible: visible_tiles += 1
			if detail: detailed_tiles += 1
			if visible: record.last_used = Time.get_ticks_msec()
	if visual_context != null: visual_context.update_view(focus,loaded,refresh_visibility)

func _select_tiles(focus: Vector3, zoom: float) -> void:
	wanted = {}
	requests.clear()
	if zoom > 5200.0: return
	var candidates: Array = []
	var radius: float = minf(FLAT_DISTANCE,maxf(850.0,zoom*1.1))
	for identifier: String in tiles:
		var bounds: Dictionary = tiles[identifier].bounds
		var east: float = clampf(focus.x,float(bounds.min[0]),float(bounds.max[0]))
		var north: float = clampf(-focus.z,float(bounds.min[1]),float(bounds.max[1]))
		var distance: float = Vector2(focus.x-east,-focus.z-north).length()
		if distance <= radius: candidates.append([distance,identifier])
	candidates.sort_custom(func(a: Array,b: Array) -> bool: return a[0] < b[0])
	for candidate: Array in candidates.slice(0,CACHE_LIMIT):
		var identifier: String = str(candidate[1])
		wanted[identifier] = float(candidate[0])
		if not loaded.has(identifier): requests.append(identifier)

func _load_tile(identifier: String) -> void:
	var descriptor: Dictionary = tiles[identifier]
	var relative: String = str(descriptor.get("path",""))
	var path: String = manifest_directory.path_join(relative).simplify_path()
	if relative.is_absolute_path() or not path.replace("\\","/").begins_with(manifest_directory.replace("\\","/").trim_suffix("/")+"/"):
		last_error = "Geography tile path escaped its manifest directory."
		missing_tiles += 1
		tiles.erase(identifier)
		return
	if not FileAccess.file_exists(path):
		last_error = "A geography tile is missing: " + identifier
		missing_tiles += 1
		tiles.erase(identifier)
		return
	var source_file := FileAccess.open(path,FileAccess.READ)
	if source_file == null or source_file.get_length() > 8 * 1024 * 1024:
		if source_file != null: source_file.close()
		last_error = "A geography tile could not be read within its size limit: " + identifier
		missing_tiles += 1
		tiles.erase(identifier)
		return
	var source_bytes: PackedByteArray = source_file.get_buffer(source_file.get_length())
	source_file.close()
	var source_hash: String = SceneryCache._digest(source_bytes).hex_encode()
	var expected_hash: String = str(descriptor.get("sha256",""))
	if not expected_hash.is_empty() and source_hash != expected_hash:
		last_error = "A geography tile does not match its checksum: " + identifier
		missing_tiles += 1
		tiles.erase(identifier)
		return
	use_context.load_tile(identifier)
	var identity: Dictionary = _tile_cache_identity(identifier,source_hash)
	var payload: Dictionary = render_cache.read_entry(identity)
	if not payload.is_empty():
		if _install_tile_payload(identifier,payload):
			restored_tiles += 1
			return
		render_cache.reject_entry("Prepared building geometry is invalid; rebuilding it.")
	var parsed: Variant = JSON.parse_string(source_bytes.get_string_from_utf8())
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or str(parsed.get("id","")) != identifier:
		last_error = "A geography tile has invalid data: " + identifier
		missing_tiles += 1
		tiles.erase(identifier)
		return
	payload = _build_tile_payload(identifier,parsed,descriptor.bounds)
	if _install_tile_payload(identifier,payload):
		generated_tiles += 1
		render_cache.write_entry(identity,payload)

func _tile_cache_identity(identifier: String,source_hash: String) -> Dictionary:
	var dependencies: Dictionary = {}
	if use_context.available:
		dependencies["use"] = _dependency_signature(use_context.directory,use_context.descriptors.get(identifier,{}))
	if visual_context != null and visual_context.available:
		dependencies["visual"] = _dependency_signature(visual_context.directory,visual_context.descriptors.get(identifier,{}))
	return {"kind":"geography-tile","sources":cache_sources,"tile":identifier,"source":source_hash,"bounds":tiles[identifier].bounds,"tile_size_m":manifest.get("tile_size_m",500.0),"pilot":pilot_enabled,"exclusion":pilot_exclusion,"landmarks":_landmark_cache_identity(),"terrain":terrain.cache_identity() if terrain != null and terrain.available and terrain.has_method("cache_identity") else {"available":false},"dependencies":dependencies}

func _landmark_cache_identity() -> Dictionary:
	var result: Dictionary = {}
	for source_id: String in landmark_records:
		var record: Dictionary = landmark_records[source_id]
		var metadata: Dictionary = {}
		# Imported roots are presentation objects with process-local IDs. Only the
		# fields affecting replaced footprints, heights and labels belong in a key.
		for field: String in ["id","base_height","height_m","label","source_note"]:
			if record.has(field): metadata[field] = record[field]
		result[source_id] = metadata
	return result

func _dependency_signature(directory: String,descriptor: Dictionary) -> Dictionary:
	directory = ProjectSettings.globalize_path(directory).simplify_path()
	var result: Dictionary = {"descriptor":descriptor}
	for field: String in ["path","color_path"]:
		if not descriptor.has(field): continue
		var relative: String = str(descriptor[field])
		var path: String = directory.path_join(relative).simplify_path()
		var normalized: String = path.replace("\\","/")
		var base: String = directory.replace("\\","/").trim_suffix("/") + "/"
		result[field] = "unsafe" if relative.is_absolute_path() or not normalized.begins_with(base) else SceneryCache.file_digest(path)
	return result

func _build_tile_payload(identifier: String,data: Dictionary,bounds: Dictionary) -> Dictionary:
	var origin := Vector3(float(bounds.min[0]),0.0,-float(bounds.min[1]))
	var skipped: int = 0
	var omitted: int = 0
	var high_builder = Builder.new(origin)
	var low_builder = Builder.new(origin)
	var count: int = 0
	var picking: Array = []
	use_context.load_tile(identifier)
	for source_building: Dictionary in data.get("buildings",[]):
		if _inside_pilot(source_building.get("footprint",[])): continue
		if not pilot_enabled and landmark_records.has(str(source_building.get("id",""))):
			var landmark: Dictionary = landmark_records[str(source_building.id)]
			var picking_building: Dictionary = source_building.duplicate(false)
			picking_building["id"] = str(landmark.id)
			picking_building["source_id"] = str(landmark.id)
			picking_building["footprint"] = _raised_points(source_building.footprint,float(landmark.base_height))
			picking_building["height_m"] = landmark.get("height_m",source_building.get("height_m",10.0))
			picking_building["label"] = landmark.get("label","City landmark")
			picking_building["height_source"] = landmark.get("source_note","Aligned architectural exterior")
			picking.append(_picking_record(picking_building))
			continue
		var enriched: Dictionary = visual_context.enrich_building(source_building,identifier) if visual_context != null else source_building
		var building: Dictionary = _ground_building(enriched)
		# Store one category per merged vertex. Toggling the overlay changes only
		# a material uniform; it never rebuilds the city's geometry.
		building = building.duplicate(false)
		building["use_category"] = use_context.category_index(str(source_building.get("id","")))
		if high_builder.building(building):
			low_builder.building(building,false)
			count += 1
			picking.append(_picking_record(building))
			if building.get("rings",[]).size() > 1 and building.get("roof_triangles",[]).is_empty(): omitted += 1
		else: skipped += 1
	var road_builder = Builder.new(origin)
	var tile_core: Dictionary = bounds
	var key_parts: PackedStringArray = identifier.split("_")
	if key_parts.size() == 2 and key_parts[0].is_valid_int() and key_parts[1].is_valid_int():
		var tile_size: float = float(manifest.get("tile_size_m",500.0))
		tile_core = {"min":[float(key_parts[0])*tile_size,float(key_parts[1])*tile_size],"max":[(float(key_parts[0])+1.0)*tile_size,(float(key_parts[1])+1.0)*tile_size]}
	for street: Dictionary in data.get("streets",[]): _add_street_segments(road_builder,street,Color("59666b"),0.04,tile_core)
	return {"schema":1,"high":high_builder.array_payload(),"low":low_builder.array_payload(),"roads":road_builder.array_payload(),"buildings":count,"triangles":high_builder.triangle_count+low_builder.triangle_count+road_builder.triangle_count,"picking":picking,"bounds":bounds,"skipped":skipped,"omitted":omitted}

func _install_tile_payload(identifier: String,payload: Dictionary) -> bool:
	if not payload.get("schema") is int or payload.schema != 1: return false
	if not payload.get("bounds") is Dictionary or payload.bounds != tiles[identifier].bounds or not payload.get("picking") is Array: return false
	for field: String in ["high","low","roads"]:
		if not payload.get(field) is Dictionary: return false
	for field: String in ["buildings","triangles","skipped","omitted"]:
		if not payload.get(field) is int or int(payload[field]) < 0: return false
	for record: Variant in payload.picking:
		if not record is Dictionary or not record.get("bounds") is AABB or not record.get("polygon") is PackedVector2Array or not record.get("holes") is Array: return false
		for field: String in ["id","source_id","label","height_source"]:
			if not record.get(field) is String: return false
		if not record.get("height_m") is float and not record.get("height_m") is int: return false
		if not is_finite(float(record.height_m)): return false
		var pick_bounds: AABB = record.bounds
		if not pick_bounds.position.is_finite() or not pick_bounds.size.is_finite() or pick_bounds.size.x < 0.0 or pick_bounds.size.y < 0.0 or pick_bounds.size.z < 0.0: return false
		if record.polygon.size() < 3: return false
		for point: Vector2 in record.polygon:
			if not point.is_finite(): return false
		for hole: Variant in record.holes:
			if not hole is PackedVector2Array or hole.size() < 3: return false
			for point: Vector2 in hole:
				if not point.is_finite(): return false
	var high_builder = Builder.new()
	var low_builder = Builder.new()
	var road_builder = Builder.new()
	if not high_builder.apply_array_payload(payload.high) or not low_builder.apply_array_payload(payload.low) or not road_builder.apply_array_payload(payload.roads): return false
	if int(payload.triangles) != high_builder.triangle_count+low_builder.triangle_count+road_builder.triangle_count: return false
	var bounds: Dictionary = tiles[identifier].bounds
	var expected_origin := Vector3(float(bounds.min[0]),0.0,-float(bounds.min[1]))
	if high_builder.origin != expected_origin or low_builder.origin != expected_origin or road_builder.origin != expected_origin: return false
	var root := Node3D.new()
	root.name = "GeographyTile-" + identifier.validate_node_name()
	add_child(root)
	var high: MeshInstance3D = high_builder.create_instance("ExtrudedBuildings",building_material)
	var low: MeshInstance3D = low_builder.create_instance("FootprintOverview",building_material)
	var roads: MeshInstance3D = road_builder.create_instance("StreetSurfaces",terrain_material)
	if high != null: root.add_child(high)
	if low != null: root.add_child(low)
	if roads != null: root.add_child(roads)
	loaded[identifier] = {"root":root,"high":high,"low":low,"last_used":Time.get_ticks_msec(),"buildings":payload.buildings,"triangles":payload.triangles,"picking":payload.picking,"bounds":payload.bounds}
	loaded_buildings += int(payload.buildings)
	skipped_polygons += int(payload.skipped)
	roofs_omitted_for_holes += int(payload.omitted)
	return true

func _ground_building(source: Dictionary) -> Dictionary:
	if terrain == null or not terrain.available: return source
	var points: Array = source.get("footprint",[])
	if points.is_empty(): return source
	var centroid := Vector2.ZERO
	for point: Array in points: centroid += Vector2(float(point[0]),float(point[1]))
	centroid /= float(points.size())
	var height_value: Variant = terrain.display_height_at(centroid.x,centroid.y)
	if height_value == null: return source
	var result: Dictionary = source.duplicate(false)
	result["footprint"] = _raised_points(points,float(height_value))
	if source.has("rings"):
		result["rings"] = []
		for ring: Array in source.rings: result.rings.append(_raised_points(ring,float(height_value)))
	if source.has("roof_vertices"): result["roof_vertices"] = _raised_points(source.roof_vertices,float(height_value))
	return result

func _raised_points(points: Array, height_value: float) -> Array:
	var result: Array = []
	for point: Array in points: result.append([float(point[0]),float(point[1]),float(point[2])+height_value])
	return result

func _picking_record(building: Dictionary) -> Dictionary:
	var minimum := Vector3(INF,INF,INF)
	var maximum := Vector3(-INF,-INF,-INF)
	var polygon := PackedVector2Array()
	for point: Array in building.footprint:
		var world_point: Vector3 = Coordinates.to_world(point)
		minimum = minimum.min(world_point)
		maximum = maximum.max(world_point)
		polygon.append(Vector2(float(point[0]),float(point[1])))
	var holes: Array = []
	var rings: Array = building.get("rings",[])
	for i: int in range(1,rings.size()):
		var hole := PackedVector2Array()
		for point: Array in rings[i]: hole.append(Vector2(float(point[0]),float(point[1])))
		holes.append(hole)
	maximum.y += clampf(float(building.get("height_m",8.0)),0.25,600.0)
	return {"id":str(building.get("id","")),"source_id":str(building.get("source_id",building.get("id",""))),"label":str(building.get("label","Mapped building")),"height_m":float(building.get("height_m",8.0)),"height_source":str(building.get("height_source","unspecified")),"bounds":AABB(minimum,maximum-minimum),"polygon":polygon,"holes":holes}

func pick(origin: Vector3, direction: Vector3, maximum_distance: float) -> Dictionary:
	var result: Dictionary = {}
	var nearest: float = maximum_distance
	for identifier: String in loaded:
		var tile: Dictionary = loaded[identifier]
		if not tile.root.visible: continue
		var detailed: bool = tile.high != null and tile.high.visible
		for building: Dictionary in tile.picking:
			var bounds: AABB = building.bounds
			if not detailed: bounds.size.y = 0.12
			var intersection: Variant = bounds.intersects_ray(origin,direction)
			if not intersection is Vector3: continue
			var distance: float = origin.distance_to(intersection)
			if distance >= nearest: continue
			var point := Vector2(intersection.x,-intersection.z)
			if not Geometry2D.is_point_in_polygon(point,building.polygon): continue
			var courtyard: bool = false
			for hole: PackedVector2Array in building.holes:
				if Geometry2D.is_point_in_polygon(point,hole): courtyard = true
			if courtyard: continue
			nearest = distance
			result = {"id":"geography:"+str(building.id),"label":building.label,"source_id":building.source_id,"height_m":building.height_m,"height_source":building.height_source,"distance":distance}
	return result

func _inside_pilot(points: Array) -> bool:
	if pilot_exclusion.is_empty(): return false
	for point: Array in points:
		if float(point[0]) >= float(pilot_exclusion.min[0]) and float(point[0]) <= float(pilot_exclusion.max[0]) and float(point[1]) >= float(pilot_exclusion.min[1]) and float(point[1]) <= float(pilot_exclusion.max[1]): return true
	return false

func _add_street_segments(builder: RefCounted, street: Dictionary, color: Color, elevation: float, clip_bounds: Dictionary = {}, full_surface: bool = true) -> void:
	var points: Array = street.get("points",[])
	for i: int in range(points.size()-1):
		var segment: Array = [points[i],points[i+1]]
		if not clip_bounds.is_empty():
			segment = _clip_segment(segment[0],segment[1],clip_bounds)
			if segment.is_empty(): continue
		if _segment_hits_pilot(points[i],points[i+1]): continue
		var sampled: Array = segment
		if terrain != null and terrain.available:
			sampled = []
			var a: Array = segment[0]
			var b: Array = segment[1]
			var fractions: Array = terrain.segment_fractions(float(a[0]),float(a[1]),float(b[0]),float(b[1])) if full_surface else [0.0,1.0]
			for fraction: float in fractions:
				var east: float = lerpf(float(a[0]),float(b[0]),fraction)
				var north: float = lerpf(float(a[1]),float(b[1]),fraction)
				var base: float = lerpf(float(a[2]),float(b[2]),fraction)
				var terrain_height: Variant = terrain.display_height_at(east,north)
				if terrain_height != null: base += float(terrain_height)
				sampled.append([east,north,base])
		if full_surface and terrain != null and terrain.available:
			_add_draped_street(builder,sampled,float(street.get("width_m",8.0)),color,elevation)
		else: builder.street({"points":sampled,"width_m":street.get("width_m",8.0)},color,elevation)

func _add_draped_street(builder: RefCounted, points: Array, width: float, color: Color, elevation: float) -> void:
	for i: int in range(points.size()-1):
		var a: Vector3 = Coordinates.to_world(points[i])+Vector3.UP*elevation
		var b: Vector3 = Coordinates.to_world(points[i+1])+Vector3.UP*elevation
		var direction: Vector3 = b-a
		direction.y = 0.0
		if direction.length_squared() < 0.00001: continue
		var offset: Vector3 = direction.normalized().cross(Vector3.UP)*clampf(width,0.5,80.0)*0.5
		var a_left: Vector3 = _road_edge(a,-offset)
		var a_right: Vector3 = _road_edge(a,offset)
		var b_left: Vector3 = _road_edge(b,-offset)
		var b_right: Vector3 = _road_edge(b,offset)
		# An explicit center edge preserves the exact walking plane even when
		# either pavement edge crosses a slope in a neighboring raster cell.
		builder.triangle(a_left,a,b,color,Vector3.UP)
		builder.triangle(a_left,b,b_left,color,Vector3.UP)
		builder.triangle(a,a_right,b_right,color,Vector3.UP)
		builder.triangle(a,b_right,b,color,Vector3.UP)

func _road_edge(center: Vector3,offset: Vector3) -> Vector3:
	var edge: Vector3 = center+offset
	var center_height: Variant = terrain.display_height_at(center.x,-center.z)
	var edge_height: Variant = terrain.display_height_at(edge.x,-edge.z)
	if center_height != null and edge_height != null: edge.y = float(edge_height)+center.y-float(center_height)
	return edge

func blocks_walk(east: float,north: float) -> bool:
	var point := Vector2(east,north)
	for tile: Dictionary in loaded.values():
		if east < float(tile.bounds.min[0]) or east > float(tile.bounds.max[0]) or north < float(tile.bounds.min[1]) or north > float(tile.bounds.max[1]): continue
		for building: Dictionary in tile.picking:
			var bounds: AABB = building.bounds
			if east < bounds.position.x or east > bounds.end.x or -north < bounds.position.z or -north > bounds.end.z: continue
			if not Geometry2D.is_point_in_polygon(point,building.polygon): continue
			var courtyard: bool = false
			for hole: PackedVector2Array in building.holes:
				if Geometry2D.is_point_in_polygon(point,hole): courtyard = true
			if not courtyard: return true
	return false

func _clip_segment(a: Array,b: Array,bounds: Dictionary) -> Array:
	var near: float = 0.0
	var far: float = 1.0
	for axis: int in range(2):
		var direction: float = float(b[axis])-float(a[axis])
		var minimum: float = float(bounds.min[axis])
		var maximum: float = float(bounds.max[axis])
		if absf(direction) < 0.000001:
			if float(a[axis]) < minimum or float(a[axis]) > maximum: return []
			continue
		var first: float = (minimum-float(a[axis]))/direction
		var last: float = (maximum-float(a[axis]))/direction
		near = maxf(near,minf(first,last))
		far = minf(far,maxf(first,last))
		if near >= far: return []
	var first_point: Vector3 = Coordinates.to_world(a).lerp(Coordinates.to_world(b),near)
	var last_point: Vector3 = Coordinates.to_world(a).lerp(Coordinates.to_world(b),far)
	return [Coordinates.to_domain(first_point),Coordinates.to_domain(last_point)]

func _segment_hits_pilot(a: Array, b: Array) -> bool:
	if pilot_exclusion.is_empty(): return false
	var near: float = 0.0
	var far: float = 1.0
	for axis: int in range(2):
		var direction: float = float(b[axis])-float(a[axis])
		var minimum: float = float(pilot_exclusion.min[axis])
		var maximum: float = float(pilot_exclusion.max[axis])
		if absf(direction) < 0.000001:
			if float(a[axis]) < minimum or float(a[axis]) > maximum: return false
			continue
		var first: float = (minimum-float(a[axis]))/direction
		var last: float = (maximum-float(a[axis]))/direction
		near = maxf(near,minf(first,last))
		far = minf(far,maxf(first,last))
		if near > far: return false
	return true

func _evict_cache() -> void:
	while loaded.size() >= CACHE_LIMIT:
		var oldest: String = ""
		var stamp: int = 9223372036854775807
		for identifier: String in loaded:
			if wanted.has(identifier): continue
			if int(loaded[identifier].last_used) < stamp:
				oldest = identifier
				stamp = int(loaded[identifier].last_used)
		if oldest.is_empty(): return
		loaded_buildings -= int(loaded[oldest].buildings)
		loaded[oldest].root.queue_free()
		loaded.erase(oldest)

func get_state() -> Dictionary:
	return {"available":available,"facades_enabled":facades_enabled,"tile_count":tiles.size(),"loaded_tiles":loaded.size(),"visible_tiles":visible_tiles,"detailed_tiles":detailed_tiles,"loaded_buildings":loaded_buildings,"pending_tiles":requests.size(),"missing_tiles":missing_tiles,"skipped_polygons":skipped_polygons,"roofs_omitted_for_holes":roofs_omitted_for_holes,"statistics":manifest.get("statistics",{}),"terrain":terrain.get_state() if terrain != null else {},"visuals":visual_context.get_state() if visual_context != null else {},"land_use":use_context.get_state(),"landmark_error":landmark_error,"pilot_patch":pilot_enabled,"render_cache":cache_stats(),"error":last_error}
