extends Node2D
## Flat inspection of the existing displayed state. This module never advances
## residents, computes routes, or changes the snapshot's indoor arrival point.

const Coordinates = preload("res://coordinates.gd")
const MAX_TILES: int = 16
const MAX_TILE_BYTES: int = 8 * 1024 * 1024
const MAX_STATIC_SEGMENTS: int = 120000
const MAX_RESIDENTS: int = 100000
const DOT_SIDES: int = 12
const HOME_COLOR := Color("6ebaff")
const WORK_COLOR := Color("cc9fff")
const WALK_COLOR := Color("ffd166")
const OTHER_COLOR := Color("ff8290")
const BACKGROUND := Color("101b26")
const LAND_COLOR := Color("1c2d36")
const KEYBOARD_PAN_PIXELS_PER_SECOND: float = 500.0
const KEYBOARD_TURN_RADIANS_PER_SECOND: float = PI / 2.0

class StaticLayer extends Node2D:
	var painter: Callable
	func _draw() -> void:
		if painter.is_valid(): painter.call(self)

var center := Vector2.ZERO
var meters_per_pixel: float = 1.0
# Clockwise camera bearing from north. Camera state survives framing and sessions.
var bearing: float = 0.0
var ids: Array[String] = []
var records: Dictionary = {}
var display_transforms: Dictionary = {}
var marker_positions: Dictionary = {}
var visible_count: int = 0
var outdoor_count: int = 0
var animated_count: int = 0
var last_error: String = ""
var draw_backend: String = "canvas-2d"
var selected_id: String = ""
var static_redraws: int = 0
var footprint_redraws: int = 0
var selected_route := PackedVector2Array()
var last_profile: Dictionary = {}
var _scenario: Dictionary = {}
var _manifest: Dictionary = {}
var _buildings: Dictionary = {}
var _building_centers: Dictionary = {}
var _footprints: Array[Dictionary] = []
var _streets: Array[Dictionary] = []
var _land: Array[Dictionary] = []
var _background_layer: StaticLayer
var _base_layer: StaticLayer
var _footprint_layer: StaticLayer
var _viewport_size := Vector2.ZERO
var _tiles: Dictionary = {}
var _tile_queue: Array[Dictionary] = []
var _wanted_tiles: Dictionary = {}
var _failed_tiles: Dictionary = {}
var _base_path: String = ""
var _selected_trip_id: String = ""
var _selected_route_owner: String = ""
var _last_marker_signature: Array = []
var _map_bounds: Dictionary = {}
var _unit_circle := PackedVector2Array()
var _dot_indices := PackedInt32Array()
var _dot_index_capacity: int = 0

func _ready() -> void:
	_unit_circle.append(Vector2.ZERO)
	for i: int in range(DOT_SIDES): _unit_circle.append(Vector2.from_angle(TAU * float(i) / DOT_SIDES))
	_background_layer = StaticLayer.new()
	_background_layer.name = "FlatBackground"
	_background_layer.painter = _draw_background
	_background_layer.show_behind_parent = true
	add_child(_background_layer)
	_base_layer = StaticLayer.new()
	_base_layer.name = "RetainedStreetMap"
	_base_layer.painter = _draw_base
	_base_layer.show_behind_parent = true
	add_child(_base_layer)
	_footprint_layer = StaticLayer.new()
	_footprint_layer.name = "RetainedFootprints"
	_footprint_layer.painter = _draw_footprints
	_footprint_layer.show_behind_parent = true
	add_child(_footprint_layer)
	_viewport_size = get_viewport_rect().size
	_redraw_static()

func configure(scenario: Dictionary, geography_manifest: Dictionary = {}) -> void:
	# Camera state intentionally survives a new population or saved session.
	clear()
	_scenario = scenario
	_manifest = geography_manifest
	_base_path = str(_manifest.get("_base_path", ""))
	_map_bounds = _manifest.get("bounds", {})
	var nodes: Dictionary = {}
	for node: Dictionary in scenario.get("nodes", []):
		if _valid_point(node.get("position")): nodes[str(node.id)] = _point(node.position)
	for building: Dictionary in scenario.get("buildings", []):
		var identifier: String = str(building.get("id", ""))
		if identifier.is_empty(): continue
		_buildings[identifier] = building
		if _valid_point(building.get("centroid")):
			_building_centers[identifier] = _point(building.centroid)
		elif _valid_point(building.get("position")):
			_building_centers[identifier] = _point(building.position)
		elif nodes.has(str(building.get("entrance_node_id", ""))):
			_building_centers[identifier] = nodes[str(building.entrance_node_id)]
		var shape: Dictionary = _prepare_footprint(building)
		if not shape.is_empty(): _footprints.append(shape)
	var streets: Array = _manifest.get("overview_streets", [])
	if not streets.is_empty():
		for street: Dictionary in streets:
			_add_street(street.get("points", []))
	else:
		for edge: Dictionary in scenario.get("edges", []):
			if edge.get("points", []).size() >= 2:
				_add_street(edge.points)
			elif nodes.has(str(edge.get("from", ""))) and nodes.has(str(edge.get("to", ""))):
				var start: Vector2 = nodes[str(edge.from)]
				var end: Vector2 = nodes[str(edge.to)]
				_add_street([[start.x, start.y], [end.x, end.y]])
	for polygon: Dictionary in _manifest.get("land", []):
		var rings: Array = polygon.get("rings", [polygon.get("points", [])])
		for i: int in range(rings.size()):
			var points: PackedVector2Array = _points(rings[i])
			if points.size() < 3: continue
			# Triangulate once; the retained canvas only projects vertices on pan/zoom.
			var triangles: PackedInt32Array = Geometry2D.triangulate_polygon(points)
			_land.append({"points": points, "triangles": triangles, "hole": i > 0, "bounds": _bounds(points)})
	_refresh_tile_requests()
	_redraw_static()

func clear() -> void:
	_scenario = {}
	_manifest = {}
	_base_path = ""
	_map_bounds = {}
	ids.clear()
	records.clear()
	display_transforms.clear()
	marker_positions.clear()
	_buildings.clear()
	_building_centers.clear()
	_footprints.clear()
	_streets.clear()
	_land.clear()
	_tiles.clear()
	_tile_queue.clear()
	_wanted_tiles.clear()
	_failed_tiles.clear()
	selected_id = ""
	_selected_trip_id = ""
	_selected_route_owner = ""
	selected_route.clear()
	_last_marker_signature.clear()
	visible_count = 0
	outdoor_count = 0
	last_error = ""
	_redraw_static()

func _process(_delta: float) -> void:
	if not visible: return
	var size: Vector2 = get_viewport_rect().size
	if size != _viewport_size:
		_viewport_size = size
		_view_changed()
	if not _tile_queue.is_empty(): _load_one_tile()

func apply_snapshot(displayed: Dictionary, selection: String) -> void:
	var started: int = Time.get_ticks_usec()
	var next: Dictionary = {}
	for person: Dictionary in displayed.get("residents", []):
		if next.size() >= MAX_RESIDENTS: break
		if person.get("id") is String: next[person.id] = person
	if next.size() != records.size() or not _same_ids(next):
		ids.assign(next.keys())
		ids.sort()
		display_transforms.clear()
		marker_positions.clear()
	records = next
	selected_id = selection
	outdoor_count = 0
	visible_count = 0
	var signature: Array = [selection, center, meters_per_pixel, bearing, _viewport_size]
	var viewport: Rect2 = Rect2(Vector2.ZERO, _viewport_size).grow(8.0)
	for identifier: String in ids:
		var person: Dictionary = records[identifier]
		if not _valid_point(person.get("position")): continue
		var position_value: Array = person.position
		display_transforms[identifier] = Transform3D(Basis(Vector3.UP, float(person.get("heading", 0.0))), Coordinates.to_world(position_value))
		var marker: Vector2 = _point(position_value)
		var outdoors: bool = bool(person.get("visible", false))
		if outdoors:
			outdoor_count += 1
		elif _building_centers.has(str(person.get("building_id", ""))):
			marker = _building_centers[str(person.building_id)]
		marker_positions[identifier] = marker
		if viewport.has_point(world_to_screen(marker)): visible_count += 1
		signature.append(marker)
		signature.append(str(person.get("activity", "")))
		signature.append(outdoors)
		signature.append(person.get("blocked_reason"))
	_update_selected_route()
	if signature != _last_marker_signature:
		_last_marker_signature = signature
		queue_redraw()
	last_profile = {"update_ms": float(Time.get_ticks_usec() - started) / 1000.0}

func _same_ids(next: Dictionary) -> bool:
	for identifier: String in ids:
		if not next.has(identifier): return false
	return true

func world_to_screen(point: Vector2) -> Vector2:
	var offset: Vector2 = (point - center) / meters_per_pixel
	return _canvas_center() + Vector2(offset.x, -offset.y).rotated(-bearing)

func screen_to_world(screen: Vector2) -> Vector2:
	var offset: Vector2 = (screen - _canvas_center()).rotated(bearing) * meters_per_pixel
	return center + Vector2(offset.x, -offset.y)

func pan_pixels(delta: Vector2) -> void:
	if not delta.is_finite() or delta == Vector2.ZERO: return
	var offset: Vector2 = delta.rotated(bearing) * meters_per_pixel
	center += Vector2(-offset.x, offset.y)
	_view_changed()

func keyboard_navigate(direction: Vector2, turn: float, delta: float, fast: bool = false) -> void:
	# Direction is screen-relative: x = D-A, y = W-S. Positive turn is E/right.
	# Cap a delayed frame so regaining focus cannot fling the camera across town.
	if not direction.is_finite() or not is_finite(turn) or not is_finite(delta) or delta <= 0.0: return
	if direction == Vector2.ZERO and is_zero_approx(turn): return
	var step: float = minf(delta, 0.05)
	bearing = wrapf(bearing + clampf(turn, -1.0, 1.0) * KEYBOARD_TURN_RADIANS_PER_SECOND * step, -PI, PI)
	var movement: Vector2 = direction.limit_length() * KEYBOARD_PAN_PIXELS_PER_SECOND * meters_per_pixel * step
	if fast: movement *= 2.5
	var offset := Vector2(movement.x, -movement.y).rotated(bearing)
	center += Vector2(offset.x, -offset.y)
	_view_changed()

func zoom_at(factor: float, screen: Vector2) -> void:
	if not is_finite(factor) or factor <= 0.0: return
	var before: Vector2 = screen_to_world(screen)
	meters_per_pixel = clampf(meters_per_pixel / factor, 0.06, 160.0)
	center += before - screen_to_world(screen)
	_view_changed()

func jump_to(point: Vector2, span_m: float) -> void:
	if not point.is_finite() or not is_finite(span_m): return
	center = point
	meters_per_pixel = clampf(span_m / maxf(1.0, minf(_viewport_size.x, _viewport_size.y - 140.0)), 0.06, 160.0)
	_view_changed()

func frame_bounds(bounds: Dictionary) -> void:
	if not _valid_point(bounds.get("min")) or not _valid_point(bounds.get("max")): return
	var low: Vector2 = _point(bounds.min)
	var high: Vector2 = _point(bounds.max)
	center = (low + high) * 0.5
	# Fit all four corners at the current bearing, retaining the user's heading.
	var span: Vector2 = (high - low).abs()
	var rotated_span := Vector2(absf(cos(bearing)) * span.x + absf(sin(bearing)) * span.y, absf(sin(bearing)) * span.x + absf(cos(bearing)) * span.y)
	meters_per_pixel = clampf(maxf(rotated_span.x / maxf(1.0, _viewport_size.x - 60.0), rotated_span.y / maxf(1.0, _viewport_size.y - 140.0)) * 1.15, 0.06, 160.0)
	_view_changed()

func frame_selected() -> void:
	if marker_positions.has(selected_id):
		jump_to(marker_positions[selected_id], 550.0)
	elif _building_centers.has(selected_id):
		jump_to(_building_centers[selected_id], 550.0)

func pick(screen: Vector2) -> String:
	var result: String = ""
	var distance: float = 11.0 * 11.0
	# Sorted IDs make coincident markers deterministic; all remain in the list.
	for identifier: String in ids:
		if not marker_positions.has(identifier): continue
		var candidate: float = screen.distance_squared_to(world_to_screen(marker_positions[identifier]))
		if candidate < distance:
			distance = candidate
			result = identifier
	if not result.is_empty(): return result
	var point: Vector2 = screen_to_world(screen)
	for footprint: Dictionary in _footprints:
		if _inside_footprint(point, footprint): return str(footprint.id)
	# Only modeled buildings are returned: the inspector already owns their
	# occupancy. Other source footprints remain geographic context.
	return ""

func get_state() -> Dictionary:
	return {"enabled": visible, "backend": draw_backend, "resident_count": ids.size(), "visible_count": visible_count, "outdoor_count": outdoor_count, "indoor_count": ids.size() - outdoor_count, "street_paths": _streets.size(), "modeled_footprints": _footprints.size(), "loaded_tiles": _tiles.size(), "pending_tiles": _tile_queue.size(), "loading": not _tile_queue.is_empty(), "static_redraws": static_redraws, "footprint_redraws": footprint_redraws, "selected_route_points": selected_route.size(), "meters_per_pixel": meters_per_pixel, "bearing": bearing, "center": [center.x, center.y], "error": last_error}

func _view_changed() -> void:
	var previous_tiles: Array = _tiles.keys()
	_refresh_tile_requests()
	_sync_static_transform()
	if previous_tiles != _tiles.keys() and _footprint_layer != null: _footprint_layer.queue_redraw()
	if _background_layer != null: _background_layer.queue_redraw()
	queue_redraw()

func _redraw_static() -> void:
	_sync_static_transform()
	if _background_layer != null: _background_layer.queue_redraw()
	if _base_layer != null: _base_layer.queue_redraw()
	if _footprint_layer != null: _footprint_layer.queue_redraw()
	queue_redraw()

func _sync_static_transform() -> void:
	# Native hairline width stays one pixel under CanvasItem scaling. Streets,
	# land and cached source footprints retain their ENU vertices while the
	# transform handles navigation entirely inside the canvas renderer.
	var right: Vector2 = Vector2.RIGHT.rotated(-bearing) / meters_per_pixel
	var north: Vector2 = Vector2.UP.rotated(-bearing) / meters_per_pixel
	var canvas_transform := Transform2D(right, north, _canvas_center() - right * center.x - north * center.y)
	for layer: StaticLayer in [_base_layer, _footprint_layer]:
		if layer == null: continue
		layer.transform = canvas_transform
	if _footprint_layer != null: _footprint_layer.visible = meters_per_pixel <= 5.0

func _update_selected_route() -> void:
	var trip: Variant = records.get(selected_id, {}).get("trip")
	var trip_id: String = str(trip.get("id", "")) if trip is Dictionary else ""
	if trip_id == _selected_trip_id and selected_id == _selected_route_owner: return
	_selected_trip_id = trip_id
	_selected_route_owner = selected_id
	selected_route = _points(trip.get("points", [])) if trip is Dictionary else PackedVector2Array()
	queue_redraw()

func _draw() -> void:
	var viewport: Rect2 = Rect2(Vector2.ZERO, _viewport_size).grow(12.0)
	if selected_route.size() >= 2:
		draw_polyline(_project(selected_route), Color("f6d882"), 2.5, true)
	var selected: Dictionary = records.get(selected_id, {})
	if not selected.is_empty():
		_draw_destination(str(selected.get("home_id", "")), "HOME", HOME_COLOR)
		_draw_destination(str(selected.get("work_id", "")), "WORK", WORK_COLOR)
	var groups: Dictionary = {}
	var dot_vertices := PackedVector2Array()
	var dot_colors := PackedColorArray()
	dot_vertices.resize(ids.size() * (DOT_SIDES + 1))
	dot_colors.resize(ids.size() * (DOT_SIDES + 1))
	var dot_count: int = 0
	for identifier: String in ids:
		if not marker_positions.has(identifier): continue
		var point: Vector2 = world_to_screen(marker_positions[identifier])
		if not viewport.has_point(point): continue
		var person: Dictionary = records[identifier]
		var color: Color = _person_color(person)
		var outdoors: bool = bool(person.get("visible", false))
		var radius: float = 3.6 if outdoors else 3.0
		var offset: int = dot_count * (DOT_SIDES + 1)
		for i: int in range(DOT_SIDES + 1):
			dot_vertices[offset + i] = point + _unit_circle[i] * radius
			dot_colors[offset + i] = color
		dot_count += 1
		if not outdoors:
			var key: Vector2 = marker_positions[identifier]
			groups[key] = int(groups.get(key, 0)) + 1
	if dot_count > 0:
		_ensure_dot_indices(dot_count)
		dot_vertices.resize(dot_count * (DOT_SIDES + 1))
		dot_colors.resize(dot_count * (DOT_SIDES + 1))
		RenderingServer.canvas_item_add_triangle_array(get_canvas_item(), _dot_indices.slice(0, dot_count * DOT_SIDES * 3), dot_vertices, dot_colors)
	for position_value: Vector2 in groups:
		if int(groups[position_value]) <= 1: continue
		var point: Vector2 = world_to_screen(position_value)
		draw_circle(point, 5.0, Color("d1deea"), false, 1.0, true)
		if meters_per_pixel < 2.0:
			draw_string(ThemeDB.fallback_font, point + Vector2(7.0, -5.0), str(groups[position_value]), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("dfebf4"))
	if marker_positions.has(selected_id):
		var point: Vector2 = world_to_screen(marker_positions[selected_id])
		draw_circle(point, 8.0, Color.WHITE, false, 2.0, true)
		if viewport.has_point(point):
			draw_string(ThemeDB.fallback_font, point + Vector2(12.0, 5.0), str(selected.get("label", selected_id)), HORIZONTAL_ALIGNMENT_LEFT, 240.0, 14, Color.WHITE)
	_draw_key()

func _ensure_dot_indices(count: int) -> void:
	if count <= _dot_index_capacity: return
	_dot_indices.resize(count * DOT_SIDES * 3)
	for dot: int in range(_dot_index_capacity, count):
		var vertex: int = dot * (DOT_SIDES + 1)
		var offset: int = dot * DOT_SIDES * 3
		for i: int in range(DOT_SIDES):
			_dot_indices[offset + i * 3] = vertex
			_dot_indices[offset + i * 3 + 1] = vertex + i + 1
			_dot_indices[offset + i * 3 + 2] = vertex + ((i + 1) % DOT_SIDES) + 1
	_dot_index_capacity = count

func _draw_destination(identifier: String, label: String, color: Color) -> void:
	if not _building_centers.has(identifier): return
	var point: Vector2 = world_to_screen(_building_centers[identifier])
	if not Rect2(Vector2.ZERO, _viewport_size).grow(30.0).has_point(point): return
	draw_rect(Rect2(point - Vector2.ONE * 6.0, Vector2.ONE * 12.0), color, false, 2.0)
	draw_string(ThemeDB.fallback_font, point + Vector2(10.0, -10.0), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, color)

func _draw_key() -> void:
	var origin := Vector2(24.0, maxf(28.0, _viewport_size.y - 86.0))
	draw_style_box(_key_background(), Rect2(origin - Vector2(12.0, 21.0), Vector2(625.0, 40.0)))
	var entries: Array = [[HOME_COLOR, "Home"], [WORK_COLOR, "At work"], [WALK_COLOR, "Walking"], [OTHER_COLOR, "Other / blocked"]]
	var x: float = origin.x
	for entry: Array in entries:
		draw_circle(Vector2(x, origin.y - 2.0), 4.0, entry[0], true, -1.0, true)
		draw_string(ThemeDB.fallback_font, Vector2(x + 10.0, origin.y + 3.0), str(entry[1]), HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color("dbe5ed"))
		x += 100.0 if str(entry[1]) != "Other / blocked" else 142.0
	var compass_center := Vector2(x + 10.0, origin.y - 2.0)
	var north: Vector2 = Vector2.UP.rotated(-bearing)
	var north_tip: Vector2 = compass_center + north * 10.0
	var compass_color := Color("a8bdcd")
	draw_line(compass_center - north * 6.0, north_tip, compass_color, 1.5, true)
	draw_line(north_tip, north_tip - north.rotated(0.6) * 5.0, compass_color, 1.5, true)
	draw_line(north_tip, north_tip - north.rotated(-0.6) * 5.0, compass_color, 1.5, true)
	draw_string(ThemeDB.fallback_font, Vector2(x + 27.0, origin.y + 3.0), "N  ·  synthetic citizens", HORIZONTAL_ALIGNMENT_LEFT, -1, 12, compass_color)
	var scale_m: float = pow(10.0, floor(log(maxf(1.0, 110.0 * meters_per_pixel)) / log(10.0)))
	if scale_m / meters_per_pixel < 45.0: scale_m *= 5.0
	var length: float = scale_m / meters_per_pixel
	var start := Vector2(maxf(20.0, _viewport_size.x - length - 28.0), _viewport_size.y - 95.0)
	draw_line(start, start + Vector2(length, 0.0), Color("b9cbd8"), 2.0)
	draw_string(ThemeDB.fallback_font, start + Vector2(0.0, -8.0), ("%.1f km" % (scale_m / 1000.0)) if scale_m >= 1000.0 else ("%d m" % int(scale_m)), HORIZONTAL_ALIGNMENT_LEFT, -1, 12, Color("b9cbd8"))

func _key_background() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.045, 0.075, 0.11, 0.95)
	style.set_corner_radius_all(7)
	return style

func _person_color(person: Dictionary) -> Color:
	if person.get("blocked_reason") != null: return OTHER_COLOR
	match str(person.get("activity", "")):
		"home": return HOME_COLOR
		"at_work": return WORK_COLOR
		"walking_to_work", "walking_home": return WALK_COLOR
	return WALK_COLOR if bool(person.get("moving", false)) else OTHER_COLOR

func _draw_background(canvas: Node2D) -> void:
	canvas.draw_rect(Rect2(Vector2.ZERO, _viewport_size), BACKGROUND)

func _draw_base(canvas: Node2D) -> void:
	static_redraws += 1
	for polygon: Dictionary in _land:
		if not polygon.triangles.is_empty():
			RenderingServer.canvas_item_add_triangle_array(canvas.get_canvas_item(), polygon.triangles, polygon.points, PackedColorArray([BACKGROUND if bool(polygon.hole) else LAND_COLOR]))
	var segments := PackedVector2Array()
	for street: Dictionary in _streets:
		var points: PackedVector2Array = street.points
		for i: int in range(1, points.size()):
			if segments.size() >= MAX_STATIC_SEGMENTS * 2: break
			segments.append(points[i - 1])
			segments.append(points[i])
		if segments.size() >= MAX_STATIC_SEGMENTS * 2: break
	# Negative width uses native hairline primitives. Antialiased positive-width
	# lines expand the entire city into hundreds of thousands of canvas objects.
	if not segments.is_empty(): canvas.draw_multiline(segments, Color("4d6773"), -1.0, false)

func _draw_footprints(canvas: Node2D) -> void:
	footprint_redraws += 1
	# GPU clipping culls these retained world vertices as the view moves. Cache
	# membership and triangle counts remain bounded independently of navigation.
	var visible_bounds := Rect2(-1000000.0, -1000000.0, 2000000.0, 2000000.0)
	var segments := PackedVector2Array()
	for tile: Dictionary in _tiles.values():
		for footprint: Dictionary in tile.footprints:
			_append_footprint_lines(segments, footprint, visible_bounds)
	for footprint: Dictionary in _footprints:
		_append_footprint_lines(segments, footprint, visible_bounds)
	if not segments.is_empty(): canvas.draw_multiline(segments, Color("657582"), -1.0, false)
	# Pilot metadata may only include entrances, so show an honest small square
	# marker rather than inventing a footprint for those buildings.
	if _manifest.get("overview_streets", []).is_empty():
		for identifier: String in _building_centers:
			if not _buildings[identifier].get("footprint", []).is_empty() or not _buildings[identifier].get("rings", []).is_empty(): continue
			var point: Vector2 = _building_centers[identifier]
			canvas.draw_rect(Rect2(point - Vector2.ONE * 3.0, Vector2.ONE * 6.0), Color("647987"), false, -1.0)

func _append_footprint_lines(segments: PackedVector2Array, footprint: Dictionary, visible_bounds: Rect2) -> void:
	if not visible_bounds.intersects(footprint.bounds, true): return
	for ring: PackedVector2Array in footprint.rings:
		for i: int in range(ring.size()):
			if segments.size() >= MAX_STATIC_SEGMENTS * 2: return
			segments.append(ring[i])
			segments.append(ring[(i + 1) % ring.size()])

func _refresh_tile_requests() -> void:
	_tile_queue.clear()
	_wanted_tiles.clear()
	# Source footprints matter at street scale. The city view retains streets
	# and cohort buildings, keeping map graphics and file work bounded.
	if _base_path.is_empty() or meters_per_pixel > 5.0: return
	var view: Rect2 = _visible_world_bounds()
	var candidates: Array[Dictionary] = []
	for tile: Dictionary in _manifest.get("tiles", []):
		var bounds: Dictionary = tile.get("bounds", {})
		if not _valid_point(bounds.get("min")) or not _valid_point(bounds.get("max")): continue
		var low: Vector2 = _point(bounds.min)
		var high: Vector2 = _point(bounds.max)
		if not view.intersects(Rect2(low, high - low), true): continue
		candidates.append({"distance": center.distance_squared_to((low + high) * 0.5), "tile": tile})
	candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return float(a.distance) < float(b.distance))
	for candidate: Dictionary in candidates.slice(0, MAX_TILES):
		var tile: Dictionary = candidate.tile
		var identifier: String = str(tile.get("id", ""))
		_wanted_tiles[identifier] = true
		if not _tiles.has(identifier) and not _failed_tiles.has(identifier): _tile_queue.append(tile)
	for identifier: String in _tiles.keys():
		if not _wanted_tiles.has(identifier): _tiles.erase(identifier)

func _load_one_tile() -> void:
	var tile: Dictionary = _tile_queue.pop_front()
	var identifier: String = str(tile.get("id", ""))
	var relative: String = str(tile.get("path", ""))
	if relative.is_empty() or relative.is_absolute_path() or "\\" in relative or ":" in relative or ".." in relative.split("/"):
		_tile_failure(identifier, "Map footprint tile has an invalid relative path.")
		return
	var path: String = _base_path.path_join(relative)
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null or file.get_length() > MAX_TILE_BYTES:
		_tile_failure(identifier, "Map footprint tile is missing or exceeds its size limit.")
		return
	var bytes: PackedByteArray = file.get_buffer(file.get_length())
	file.close()
	var expected: String = str(_manifest.get("files", {}).get(relative, ""))
	var hash_context := HashingContext.new()
	hash_context.start(HashingContext.HASH_SHA256)
	hash_context.update(bytes)
	if expected.is_empty() or hash_context.finish().hex_encode() != expected:
		_tile_failure(identifier, "Map footprint tile checksum does not match the geography manifest.")
		return
	var parsed: Variant = JSON.parse_string(bytes.get_string_from_utf8())
	if not parsed is Dictionary or str(parsed.get("id", "")) != identifier or not parsed.get("buildings") is Array:
		_tile_failure(identifier, "Map footprint tile has invalid contents.")
		return
	var shapes: Array[Dictionary] = []
	for building: Dictionary in parsed.buildings:
		if _buildings.has(str(building.get("id", ""))): continue
		var shape: Dictionary = _prepare_footprint(building)
		if not shape.is_empty(): shapes.append(shape)
	_tiles[identifier] = {"footprints": shapes}
	if _footprint_layer != null: _footprint_layer.queue_redraw()

func _tile_failure(identifier: String, message: String) -> void:
	_failed_tiles[identifier] = true
	last_error = message

func _prepare_footprint(building: Dictionary) -> Dictionary:
	var source: Array = building.get("rings", [building.get("footprint", [])])
	var rings: Array[PackedVector2Array] = []
	for ring: Variant in source:
		var points: PackedVector2Array = _points(ring)
		if points.size() >= 3: rings.append(points)
	if rings.is_empty(): return {}
	return {"id": str(building.get("id", "")), "rings": rings, "bounds": _bounds(rings[0])}

func _inside_footprint(point: Vector2, footprint: Dictionary) -> bool:
	if not footprint.bounds.has_point(point): return false
	if not Geometry2D.is_point_in_polygon(point, footprint.rings[0]): return false
	for i: int in range(1, footprint.rings.size()):
		if Geometry2D.is_point_in_polygon(point, footprint.rings[i]): return false
	return true

func _add_street(source: Variant) -> void:
	var points: PackedVector2Array = _points(source)
	if points.size() >= 2: _streets.append({"points": points, "bounds": _bounds(points).grow(0.01)})

func _visible_world_bounds() -> Rect2:
	# A rotated viewport needs all four corners; opposite corners can collapse
	# one axis at a diagonal bearing and incorrectly evict visible source tiles.
	var bounds := Rect2(screen_to_world(Vector2.ZERO), Vector2.ZERO)
	for corner: Vector2 in [Vector2(_viewport_size.x, 0.0), _viewport_size, Vector2(0.0, _viewport_size.y)]:
		bounds = bounds.expand(screen_to_world(corner))
	return bounds.grow(meters_per_pixel * 20.0)

func _canvas_center() -> Vector2:
	# Keep geography above the always-present footer and map legend.
	return Vector2(_viewport_size.x * 0.5, maxf(1.0, _viewport_size.y - 110.0) * 0.5)

func _project(points: PackedVector2Array) -> PackedVector2Array:
	var projected := PackedVector2Array()
	projected.resize(points.size())
	for i: int in range(points.size()): projected[i] = world_to_screen(points[i])
	return projected

func _bounds(points: PackedVector2Array) -> Rect2:
	var box := Rect2(points[0], Vector2.ZERO)
	for point: Vector2 in points: box = box.expand(point)
	return box

func _points(source: Variant) -> PackedVector2Array:
	var points := PackedVector2Array()
	if not source is Array or source.size() > 250000: return points
	for item: Variant in source:
		if not _valid_point(item): return PackedVector2Array()
		points.append(_point(item))
	return points

func _valid_point(value: Variant) -> bool:
	return value is Array and value.size() >= 2 and (value[0] is float or value[0] is int) and (value[1] is float or value[1] is int) and is_finite(float(value[0])) and is_finite(float(value[1]))

func _point(value: Array) -> Vector2:
	return Vector2(float(value[0]), float(value[1]))
