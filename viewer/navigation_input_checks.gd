extends RefCounted
## Exercise physical-key polling through the application's production dispatcher.
const KEYS: Array[int] = [KEY_W,KEY_A,KEY_S,KEY_D,KEY_Q,KEY_E,KEY_SHIFT]
const CAMERA_FIELDS: Array[String] = ["mode","orbit_target","orbit_yaw","orbit_pitch","orbit_distance","walk_position","walk_yaw","walk_pitch","follow_position","follow_pan_offset","follow_heading","follow_available","follow_indoor","follow_building_height","follow_distance","follow_yaw_offset","follow_pitch","allow_walk_input"]
const STEP: float = 0.04

func run(app: Node3D) -> String:
	var saved_mode: String = app._view_mode()
	var saved_camera: Dictionary = _camera_state(app)
	var saved_map: Dictionary = _map_state(app)
	var saved_selection: Array = [app.selected_id,app.selected_label,app.follow_id,app.follow_camera_id,app.follow_metadata_key]
	var saved_focus: Control = app.get_viewport().gui_get_focus_owner()
	var saved_dragging: bool = app.dragging
	var domain: Dictionary = app.displayed.duplicate(true)
	_release_keys()
	if saved_focus != null: saved_focus.release_focus()
	var failure: String = ""
	var modes: Array = ["map"] if app.map_active else ["overhead","follow","walk"]
	for mode: String in modes:
		app._set_mode(mode)
		app.cameras.allow_walk_input = true
		failure = _check_mode(app,mode)
		if not failure.is_empty(): break
	if failure.is_empty(): failure = _check_focus_guards(app)
	if failure.is_empty() and app.displayed != domain:
		failure = "Camera keyboard navigation changed authoritative state, pause or speed."
	# Always release injected keys and restore presentation, including on failure.
	_release_keys()
	app._set_mode(saved_mode)
	app._select(str(saved_selection[0]),str(saved_selection[1]))
	app.follow_id = saved_selection[2]
	app.follow_camera_id = saved_selection[3]
	app.follow_metadata_key = saved_selection[4]
	_restore_camera(app,saved_camera)
	_restore_map(app,saved_map)
	app.dragging = saved_dragging
	if is_instance_valid(saved_focus): saved_focus.grab_focus()
	if failure.is_empty(): print("GODOT_NAVIGATION_INPUT_CHECKS_PASS " + saved_mode)
	return failure

func _check_mode(app: Node3D, mode: String) -> String:
	var cameras: Node3D = app.cameras
	if mode == "follow" and not cameras.follow_available:
		return "Keyboard Follow check has no selected resident to follow."
	var camera_origin: Dictionary = _camera_state(app)
	var map_origin: Dictionary = _map_state(app)
	var selected: String = app.selected_id
	var start: Vector2 = _position(app,mode)
	if mode != "walk":
		var forward: Vector2 = _forward(app,mode)
		var right := Vector2(forward.y,-forward.x)
		var normal_distance: float = 0.0
		for entry: Array in [[KEY_W,forward],[KEY_S,-forward],[KEY_A,-right],[KEY_D,right]]:
			_restore_pose(app,camera_origin,map_origin)
			_pulse(app,[int(entry[0])])
			var displacement: Vector2 = _position(app,mode)-start
			var expected: Vector2 = entry[1]
			if displacement.length() <= 0.001 or displacement.normalized().dot(expected) < 0.999:
				return "Physical WASD did not move relative to the " + mode + " view."
			if int(entry[0]) == KEY_W: normal_distance = displacement.length()
		_restore_pose(app,camera_origin,map_origin)
		_pulse(app,[KEY_W,KEY_D])
		if absf((_position(app,mode)-start).length()/normal_distance-1.0) > 0.002:
			return "Diagonal keyboard movement is faster in " + mode + "."
		_restore_pose(app,camera_origin,map_origin)
		_pulse(app,[KEY_W,KEY_SHIFT])
		if absf((_position(app,mode)-start).length()/normal_distance-2.5) > 0.002:
			return "Shift did not accelerate keyboard movement in " + mode + "."
		_restore_pose(app,camera_origin,map_origin)
		_pulse(app,[KEY_W,KEY_A,KEY_S,KEY_D,KEY_Q,KEY_E])
		if _position(app,mode).distance_to(start) > 0.0001:
			return "Opposite held keys did not cancel in " + mode + "."
	_restore_pose(app,camera_origin,map_origin)
	var initial_angle: float = _angle(app,mode)
	var right_sign: float = 1.0 if mode in ["map","walk"] else -1.0
	_pulse(app,[KEY_E])
	if angle_difference(initial_angle,_angle(app,mode))*right_sign <= 0.001:
		return "E did not rotate right in " + mode + "."
	_pulse(app,[KEY_Q])
	if absf(angle_difference(initial_angle,_angle(app,mode))) > 0.00001:
		return "Q did not reverse the E rotation in " + mode + "."
	_pulse(app,[KEY_Q,KEY_E])
	if absf(angle_difference(initial_angle,_angle(app,mode))) > 0.00001:
		return "Q and E did not cancel in " + mode + "."
	if mode == "follow":
		_pulse(app,[KEY_D])
		if cameras.follow_pan_offset.is_zero_approx(): return "Follow keyboard pan lost its offset."
		app._set_mode("follow")
		if not cameras.follow_pan_offset.is_zero_approx(): return "Pressing Follow again did not recenter the camera."
	if app.selected_id != selected: return "Camera movement changed selected resident identity."
	_restore_pose(app,camera_origin,map_origin)
	return ""

func _check_focus_guards(app: Node3D) -> String:
	if not app.camera_input_allowed(null,true) or app.camera_input_allowed(null,false):
		return "Camera input does not honor application window focus."
	var failure: String = ""
	for field: Control in [LineEdit.new(),TextEdit.new()]:
		app.add_child(field)
		field.grab_focus()
		var actual_focus: Control = app.get_viewport().gui_get_focus_owner()
		app.cameras.allow_walk_input = app.camera_input_allowed(actual_focus,true)
		if actual_focus != field or app.cameras.allow_walk_input:
			failure = "A focused text field did not suppress camera keyboard input."
		var camera_before: Dictionary = _camera_state(app)
		var map_before: Dictionary = _map_state(app)
		_pulse(app,[KEY_W,KEY_D,KEY_E])
		if _camera_state(app) != camera_before or _map_state(app) != map_before:
			failure = "Consumed text-field keys still moved or rotated the camera."
		field.release_focus()
		field.free()
	app.cameras.allow_walk_input = app.camera_input_allowed(null,false)
	var camera_before: Dictionary = _camera_state(app)
	var map_before: Dictionary = _map_state(app)
	_pulse(app,[KEY_W,KEY_E])
	if _camera_state(app) != camera_before or _map_state(app) != map_before:
		failure = "An unfocused window still accepted camera keyboard input."
	app.cameras.allow_walk_input = true
	return failure

func _pulse(app: Node3D, keys: Array) -> void:
	_release_keys()
	for key: int in keys: _key(key,true)
	Input.flush_buffered_events()
	app._update_keyboard_navigation(STEP)
	# Placement is a separate production phase; keep walk displacement out of
	# this control check because collision regressions have their own fixtures.
	if not app.map_active: app.cameras.update_camera(0.0)
	_release_keys()

func _key(code: int, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)

func _release_keys() -> void:
	for key: int in KEYS: _key(key,false)
	Input.flush_buffered_events()

func _camera_state(app: Node3D) -> Dictionary:
	var result: Dictionary = {}
	for property: String in CAMERA_FIELDS: result[property] = app.cameras.get(property)
	return result

func _restore_camera(app: Node3D, state: Dictionary) -> void:
	for property: String in CAMERA_FIELDS: app.cameras.set(property,state[property])
	app.cameras.update_camera(0.0)

func _map_state(app: Node3D) -> Dictionary:
	return {"center":app.map_2d.center,"bearing":app.map_2d.bearing,"meters_per_pixel":app.map_2d.meters_per_pixel}

func _restore_map(app: Node3D, state: Dictionary) -> void:
	app.map_2d.center = state.center
	app.map_2d.bearing = state.bearing
	app.map_2d.meters_per_pixel = state.meters_per_pixel
	app.map_2d._view_changed()

func _restore_pose(app: Node3D, camera_state: Dictionary, map_state: Dictionary) -> void:
	_restore_camera(app,camera_state)
	_restore_map(app,map_state)

func _position(app: Node3D, mode: String) -> Vector2:
	if mode == "map": return app.map_2d.center
	var value: Vector3 = app.cameras.follow_pan_offset if mode == "follow" else app.cameras.orbit_target
	return Vector2(value.x,-value.z)

func _forward(app: Node3D, mode: String) -> Vector2:
	if mode == "map":
		var center_screen: Vector2 = app.map_2d.world_to_screen(app.map_2d.center)
		return (app.map_2d.screen_to_world(center_screen+Vector2.UP*10.0)-app.map_2d.center).normalized()
	var forward: Vector3 = -app.cameras.camera.global_basis.z
	return Vector2(forward.x,-forward.z).normalized()

func _angle(app: Node3D, mode: String) -> float:
	match mode:
		"map": return app.map_2d.bearing
		"walk": return app.cameras.walk_yaw
		"follow": return app.cameras.follow_yaw_offset
		_: return app.cameras.orbit_yaw
