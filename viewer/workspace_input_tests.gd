extends SceneTree
## --headless --path viewer --script res://workspace_input_tests.gd -- --replay ../contracts/one-resident-replay.json --geography ""
class ProbeApp extends "res://main.gd":
	var close_seen: bool = false

	func _close_application() -> void:
		close_seen = true

var failures: Array[String] = []
var app: Node3D

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	app = ProbeApp.new()
	root.add_child(app)
	var deadline: int = Time.get_ticks_msec()+45000
	while not app.startup_complete and not app.startup_failed and Time.get_ticks_msec() < deadline: await process_frame
	_check(app.startup_complete,"Fixture did not reach a usable replay")
	if not app.startup_complete:
		_finish()
		return
	app.set_process(false)
	app._set_probe_input_guard(false)
	app._set_mode("overhead")
	app.diagnostics.set_open(false)
	var layer := CanvasLayer.new()
	layer.layer = 200
	app.add_child(layer)
	var button := Button.new()
	button.text = "Test view toggle"
	button.position = Vector2(600,250)
	button.size = Vector2(190,45)
	button.focus_mode = Control.FOCUS_NONE
	button.pressed.connect(func() -> void: app._action("toggle_map"))
	layer.add_child(button)
	await process_frame
	await process_frame
	_mouse(button.get_global_rect().get_center(),true)
	_mouse(button.get_global_rect().get_center(),false)
	await process_frame
	_check(app.map_active,"Baseline injected GUI click did not change view")
	app._set_mode("overhead")
	_key(KEY_F3,true)
	_key(KEY_F3,false)
	await process_frame
	_check(app.diagnostics.visible,"Baseline injected shortcut did not open diagnostics")
	app.diagnostics.set_open(false)
	var baseline: Vector3 = app.cameras.orbit_target
	_key(KEY_W,true)
	app.cameras.allow_walk_input = true
	app._update_keyboard_navigation(0.04)
	_key(KEY_W,false)
	_check(not app.cameras.orbit_target.is_equal_approx(baseline),"Baseline injected physical key did not move camera")
	app.cameras.update_camera(0.0)
	app._set_probe_input_guard(true)
	_check(root.gui_disable_input,"Probe did not disable viewport GUI input")
	var pose: Transform3D = app.cameras.camera.global_transform
	_mouse(button.get_global_rect().get_center(),true)
	_mouse(button.get_global_rect().get_center(),false)
	for code: int in [KEY_4,KEY_F3,KEY_F11]:
		_key(code,true)
		_key(code,false)
	await process_frame
	_check(not app.map_active and not app.diagnostics.visible,"Injected GUI/shortcut changed probe presentation")
	_key(KEY_W,true)
	_key(KEY_E,true)
	app.cameras.allow_walk_input = true
	app._update_keyboard_navigation(0.04)
	app._process(0.04)
	_key(KEY_W,false)
	_key(KEY_E,false)
	_check(not app.cameras.allow_walk_input,"Probe frame enabled physical camera polling")
	_check(app.cameras.camera.global_transform.is_equal_approx(pose),"Held input moved or rotated the probe camera")
	app._action("toggle_map")
	_check(app.map_active,"Probe guard blocked programmatic actions")
	app._set_mode("overhead")
	app.display_settings.set_scale(1.25,false)
	_check(not app.map_active and app.display_settings.scale_value == 1.25,"Probe guard blocked direct presentation APIs")
	app.notification(Node.NOTIFICATION_WM_CLOSE_REQUEST)
	_check(app.close_seen,"Probe guard blocked OS close cancellation")
	app._set_probe_input_guard(false)
	layer.queue_free()
	_finish()

func _mouse(position: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.position = position
	event.global_position = position
	event.button_index = MOUSE_BUTTON_LEFT
	event.pressed = pressed
	root.push_input(event,true)

func _key(code: int, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)
	Input.flush_buffered_events()

func _check(condition: bool, message: String) -> void:
	if not condition: failures.append(message)

func _finish() -> void:
	for code: int in [KEY_W,KEY_E,KEY_4,KEY_F3,KEY_F11]: _key(code,false)
	if failures.is_empty(): print("GODOT_WORKSPACE_INPUT_TESTS_OK")
	else:
		for failure: String in failures: push_error(failure)
	quit(0 if failures.is_empty() else 1)
