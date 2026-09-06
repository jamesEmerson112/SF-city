extends SceneTree

var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _check(condition: bool, message: String) -> void:
	if not condition: failures.append(message)

func _check_keyboard_navigation(map) -> void:
	map.center = Vector2.ZERO
	map.meters_per_pixel = 2.0
	map.bearing = 0.0
	map.keyboard_navigate(Vector2(0, 1), 0.0, 0.02)
	_check(map.center.distance_to(Vector2(0, 20)) < 0.0001, "W must move the map camera toward screen top at a zoom-scaled rate.")
	map.center = Vector2.ZERO
	map.keyboard_navigate(Vector2(1, 1), 0.0, 0.02)
	_check(absf(map.center.length() - 20.0) < 0.0001, "Diagonal keyboard movement must not be faster than cardinal movement.")
	map.center = Vector2.ZERO
	map.keyboard_navigate(Vector2(1, 0), 0.0, 0.02, true)
	_check(map.center.distance_to(Vector2(50, 0)) < 0.0001, "Shift must multiply map pan speed by 2.5.")
	map.center = Vector2.ZERO
	map.keyboard_navigate(Vector2(1, 0), 0.0, 10.0)
	_check(map.center.distance_to(Vector2(50, 0)) < 0.0001, "A delayed keyboard frame must be capped at 0.05 seconds.")
	map.keyboard_navigate(Vector2.ZERO, 1.0, 0.02)
	_check(map.bearing > 0.0 and is_equal_approx(map.bearing, PI / 100.0), "E must rotate the camera clockwise from north.")
	map.keyboard_navigate(Vector2.ZERO, -1.0, 0.02)
	_check(is_zero_approx(map.bearing), "Q must reverse E's rotation at the same rate.")
	map.center = Vector2.ZERO
	map.bearing = PI / 2.0
	map.keyboard_navigate(Vector2(0, 1), 0.0, 0.02)
	_check(map.center.distance_to(Vector2(20, 0)) < 0.0001, "At an eastward bearing W must move east, toward screen top.")
	map.center = Vector2.ZERO
	map.keyboard_navigate(Vector2(1, 0), 0.0, 0.02)
	_check(map.center.distance_to(Vector2(0, -20)) < 0.0001, "At an eastward bearing D must move south, toward screen right.")
	var camera_center: Vector2 = map.center
	var camera_bearing: float = map.bearing
	map._tile_queue.append({"id": "untouched"})
	map.keyboard_navigate(Vector2.ZERO, 0.0, 0.02)
	map.keyboard_navigate(Vector2.ONE, 1.0, 0.0)
	map.keyboard_navigate(Vector2.ONE, 1.0, -1.0)
	map.keyboard_navigate(Vector2(NAN, 0), 1.0, 0.02)
	map.keyboard_navigate(Vector2.ONE, INF, 0.02)
	_check(map.center == camera_center and map.bearing == camera_bearing and map._tile_queue.size() == 1, "Idle or invalid keyboard input must perform no camera or tile work.")
	map._tile_queue.clear()
	for angle: float in [PI / 4.0, PI / 2.0, -PI / 2.0, PI * 0.93]:
		map.bearing = angle
		map.frame_bounds({"min": [-200, -100], "max": [200, 100]})
		_check(is_equal_approx(map.bearing, angle), "Bounds framing must retain map bearing.")
		var viewport := Rect2(Vector2.ZERO, Vector2(1200, 690))
		for corner: Vector2 in [Vector2(-200, -100), Vector2(-200, 100), Vector2(200, -100), Vector2(200, 100)]:
			_check(viewport.has_point(map.world_to_screen(corner)), "Rotated bounds framing must fit all four source corners.")
		var point := Vector2(-113.123, 88.5)
		_check(map.screen_to_world(map.world_to_screen(point)).distance_to(point) < 0.0001, "Rotated coordinate projection must roundtrip.")
		_check((map._base_layer.transform * point).distance_to(map.world_to_screen(point)) < 0.0001, "Rotated retained streets must align with citizen projection.")
		_check((map._footprint_layer.transform * point).distance_to(map.world_to_screen(point)) < 0.0001, "Rotated retained footprints must align with citizen projection.")
		var view: Rect2 = map._visible_world_bounds()
		for screen: Vector2 in [Vector2.ZERO, Vector2(1200, 0), Vector2(1200, 800), Vector2(0, 800)]:
			_check(view.has_point(map.screen_to_world(screen)), "Tile bounds must cover every rotated viewport corner.")
		var anchor := Vector2(876, 234)
		var before: Vector2 = map.screen_to_world(anchor)
		map.zoom_at(1.2, anchor)
		_check(map.screen_to_world(anchor).distance_to(before) < 0.0001, "Rotated zoom must preserve its pointer anchor.")
		var projected: Vector2 = map.world_to_screen(point)
		map.pan_pixels(Vector2(15, -20))
		_check(map.world_to_screen(point).distance_to(projected + Vector2(15, -20)) < 0.0001, "Rotated drag must move source geometry in the drag direction.")
	map.bearing = PI / 2.0
	map.frame_bounds({"min": [-200, -100], "max": [200, 100]})
	var north: Vector2 = map.world_to_screen(Vector2(0, 10)) - map.world_to_screen(Vector2.ZERO)
	_check(north.x < 0.0 and absf(north.y) < 0.0001, "At a 90-degree clockwise camera bearing source north must point left.")

func _run() -> void:
	var map = preload("res://map_2d.gd").new()
	root.add_child(map)
	map._viewport_size = Vector2(1200, 800)
	var scenario: Dictionary = {
		"nodes": [{"id": "a", "position": [0, 0, 2]}, {"id": "b", "position": [100, 100, 5]}],
		"edges": [{"from": "a", "to": "b"}],
		"buildings": [
			{"id": "home", "centroid": [-40, 0, 0], "footprint": [[-50, -10], [-30, -10], [-30, 10], [-50, 10]]},
			{"id": "work", "centroid": [100, 100, 0], "rings": [[[80, 80], [120, 80], [120, 120], [80, 120]], [[95, 95], [105, 95], [105, 105], [95, 105]]]}
		]
	}
	map.configure(scenario)
	map.jump_to(Vector2(50, 50), 400.0)
	var test_point := Vector2(-113.123, 88.5)
	_check(map.screen_to_world(map.world_to_screen(test_point)).distance_to(test_point) < 0.0001, "Coordinate projection must roundtrip with north upward.")
	_check(map.world_to_screen(Vector2(0, 10)).y < map.world_to_screen(Vector2.ZERO).y, "North must project upward.")
	var anchor := Vector2(876, 234)
	var before: Vector2 = map.screen_to_world(anchor)
	map.zoom_at(2.0, anchor)
	_check(map.screen_to_world(anchor).distance_to(before) < 0.0001, "Zoom must preserve its pointer anchor.")
	var previous: Vector2 = map.center
	map.pan_pixels(Vector2(15, -20))
	_check(map.center.distance_to(previous + Vector2(-15, -20) * map.meters_per_pixel) < 0.0001, "Pan must move the map in the drag direction.")
	map.frame_bounds({"min": [-200, -100], "max": [200, 100]})
	_check(map.center == Vector2.ZERO, "Bounds framing must center its source coordinates.")
	_check_keyboard_navigation(map)
	var resident: Dictionary = {"id": "citizen-a", "label": "Citizen A", "home_id": "home", "work_id": "work", "building_id": "home", "position": [-49, 0, 2.5], "heading": 0.0, "activity": "home", "visible": false, "moving": false, "trip": null}
	var other: Dictionary = resident.duplicate(true)
	other.id = "citizen-b"
	map.apply_snapshot({"residents": [other, resident]}, resident.id)
	_check(map.ids == ["citizen-a", "citizen-b"], "IDs must be deterministic regardless of packet ordering.")
	_check(map.marker_positions[resident.id] == Vector2(-40, 0), "Indoor map markers must use the building centroid.")
	_check(map.display_transforms[resident.id].origin == Vector3(-49, 2.5, 0), "Indoor markers must never alter the authoritative display root.")
	_check(map.pick(map.world_to_screen(Vector2(-40, 0))) == "citizen-a", "Coincident residents need deterministic picking.")
	_check(map.outdoor_count == 0 and map.visible_count == 2, "Indoor residents remain visible and counted in the map.")
	_check(map.pick(map.world_to_screen(Vector2(85, 85))) == "work", "Modeled footprint must be selectable after resident picking.")
	_check(map.pick(map.world_to_screen(Vector2(100, 100))).is_empty(), "Building courtyard must not count as footprint.")
	var footprint_segments := PackedVector2Array()
	map._append_footprint_lines(footprint_segments, map._footprints[0], Rect2(-200, -200, 400, 400))
	_check(footprint_segments.size() == 8, "Retained footprint batching must receive all ring edges.")
	resident.visible = true
	resident.moving = true
	resident.activity = "walking_to_work"
	resident.building_id = null
	resident.position = [0, 10, 4]
	resident.trip = {"id": "citizen-a:outbound:0", "points": [[-49, 0, 2.5], [0, 0, 2.5], [0, 100, 4], [100, 100, 5]]}
	map.apply_snapshot({"residents": [resident, other]}, resident.id)
	_check(map.marker_positions[resident.id] == Vector2(0, 10), "Walking marker must use the displayed position exactly.")
	_check(map.selected_route == PackedVector2Array([Vector2(-49, 0), Vector2.ZERO, Vector2(0, 100), Vector2(100, 100)]), "Selected route must preserve every route corner.")
	_check(map.outdoor_count == 1 and map.pick(map.world_to_screen(Vector2(0, 10))) == resident.id, "Walking picking must share drawn positions.")
	await process_frame
	await process_frame
	var redraws: int = map.static_redraws
	resident.position = [0, 11, 4]
	map.apply_snapshot({"residents": [other, resident]}, resident.id)
	await process_frame
	_check(map.static_redraws == redraws, "Moving citizens must not rebuild the retained street map.")
	map.pan_pixels(Vector2(17, -11))
	map.zoom_at(1.1, Vector2(400, 300))
	var domain_before: Dictionary = resident.duplicate(true)
	map.keyboard_navigate(Vector2(1, 1), 1.0, 0.02)
	await process_frame
	await process_frame
	_check(map.static_redraws == redraws, "Pan, zoom and rotation must transform retained streets instead of rebuilding every city vertex.")
	_check(resident == domain_before, "Camera navigation must never mutate a resident's authoritative state or route.")
	_check((map._base_layer.transform * test_point).distance_to(map.world_to_screen(test_point)) < 0.0001, "Retained geometry and citizen projection must stay aligned during navigation.")
	map._ensure_dot_indices(2)
	_check(map._dot_indices.size() >= 72 and map._dot_indices[36] == 13, "Batched circles must keep an independent triangle fan for each visible resident.")
	resident.visible = false
	resident.moving = false
	resident.activity = "at_work"
	resident.building_id = "work"
	resident.position = [100, 80, 5]
	resident.trip = null
	map.apply_snapshot({"residents": [resident, other]}, resident.id)
	_check(map.selected_route.is_empty() and map.marker_positions[resident.id] == Vector2(100, 100), "Arrival must clear the route and change indoor location atomically.")
	_check(map.records.has(resident.id) and map.display_transforms[resident.id].origin == Vector3(100, 5, -80), "Arrival must preserve persistent selection and the exact root.")
	map.apply_snapshot({"residents": [resident]}, resident.id)
	_check(not map.records.has(other.id) and not map.display_transforms.has(other.id) and not map.marker_positions.has(other.id), "Removed residents must leave no stale render or picking state.")
	map.frame_selected()
	_check(map.center == Vector2(100, 100), "Center selected must frame an indoor building marker.")
	previous = map.center
	var previous_scale: float = map.meters_per_pixel
	var previous_bearing: float = map.bearing
	map.configure(scenario)
	_check(map.ids.is_empty() and map.records.is_empty() and map.marker_positions.is_empty() and map.selected_route.is_empty(), "New sessions must evict all prior agent data.")
	_check(map.center == previous and map.meters_per_pixel == previous_scale and map.bearing == previous_bearing, "Session changes must preserve map navigation and bearing.")
	map.configure({"nodes": [], "edges": [], "buildings": []}, {"overview_streets": [{"points": [[0, 0], [10, 0], [10, 20]]}]})
	_check(map.get_state().street_paths == 1, "Compact city scenes must draw streets from their geography manifest.")
	map.configure({}, {"_base_path": "user://", "files": {}, "tiles": [{"id": "invalid", "path": "../outside.json", "bounds": {"min": [90, 90], "max": [110, 110]}}]})
	map._load_one_tile()
	_check(map.get_state().loaded_tiles == 0 and not map.last_error.is_empty(), "Footprint paths must remain inside the configured manifest directory.")
	map.free()
	if failures.is_empty():
		print("MAP_2D_TESTS_OK")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
