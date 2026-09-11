extends SceneTree
## --headless --path viewer --script res://game_menu_tests.gd -- --replay ../contracts/one-resident-replay.json --geography ""
const Menu = preload("res://game_menu.gd")
class ProbeApp extends "res://main.gd":
	var close_seen: bool = false
	func _close_application() -> void:
		close_seen = true

var failures: Array[String] = []
var app: Node3D

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	await _layout_and_focus()
	app = ProbeApp.new()
	root.add_child(app)
	var deadline: int = Time.get_ticks_msec()+45000
	while not app.startup_complete and not app.startup_failed and Time.get_ticks_msec() < deadline:
		await process_frame
	_check(app.startup_complete,"Replay fixture did not become usable")
	if not app.startup_complete:
		_finish()
		return
	app._set_probe_input_guard(false)
	app.replay_paused = true
	app.diagnostics.set_open(false)
	for mode: String in ["overhead","walk","follow","map"]:
		app._set_mode(mode)
		await _frames()
		var selected: String = app.selected_id
		var hud_rect: Rect2 = app.hud.content_rect()
		_key(KEY_ESCAPE,true)
		_key(KEY_ESCAPE,false)
		await _frames()
		_check(app.game_menu.visible,"Escape failed to open menu in "+mode)
		var pose: Transform3D = app.cameras.camera.global_transform
		var map_center: Vector2 = app.map_2d.center
		var map_bearing: float = app.map_2d.bearing
		for code: int in [KEY_W,KEY_E,KEY_RIGHT]: _key(code,true)
		for code: int in [KEY_1,KEY_2,KEY_3,KEY_4,KEY_SPACE,KEY_R,KEY_N,KEY_F5,KEY_F9]:
			_key(code,true)
			_key(code,false)
		_mouse(Vector2(800,400),MOUSE_BUTTON_LEFT,true)
		_mouse(Vector2(800,400),MOUSE_BUTTON_LEFT,false)
		_mouse(Vector2(800,400),MOUSE_BUTTON_WHEEL_UP,true)
		_mouse(Vector2(800,400),MOUSE_BUTTON_WHEEL_UP,false)
		await _frames(4)
		_check(app._view_mode() == mode,"Menu leaked view shortcut in "+mode)
		_check(app.selected_id == selected,"Menu leaked world selection in "+mode)
		_check(app.cameras.camera.global_transform.is_equal_approx(pose),"Menu leaked camera input in "+mode)
		_check(app.map_2d.center == map_center and app.map_2d.bearing == map_bearing,"Menu leaked map navigation in "+mode)
		_check(app.hud.content_rect() == hud_rect,"Menu changed city interaction layout in "+mode)
		_check(app.replay_paused,"Gameplay shortcut resumed replay behind menu")
		for code: int in [KEY_W,KEY_E,KEY_RIGHT]: _key(code,false)
		app.game_menu.show_page("controls")
		await _frames()
		_key(KEY_ESCAPE,true)
		_key(KEY_ESCAPE,false)
		await _frames()
		_check(app.game_menu.visible and app.game_menu.page == "root","Nested Escape did not return to root menu")
		_key(KEY_ESCAPE,true)
		_key(KEY_ESCAPE,false)
		await _frames()
		_check(not app.game_menu.visible,"Root Escape did not return to city")
		_check(app.replay_paused,"Returning changed an already-paused replay")
	_check(not app.close_seen,"Escape or gameplay keys closed the application")

	app.replay_paused = false
	app.menu_flow.open_menu()
	await _frames()
	_check(app.replay_paused,"Opening menu did not pause running replay")
	app.menu_flow.return_to_city()
	await _frames()
	_check(not app.replay_paused,"Return did not restore running replay")
	app.replay_paused = true
	var input_layer := CanvasLayer.new()
	input_layer.layer = 115
	app.add_child(input_layer)
	var editor := LineEdit.new()
	editor.position = Vector2(500,120)
	editor.size = Vector2(220,44)
	input_layer.add_child(editor)
	editor.grab_focus()
	await _frames()
	_key(KEY_ESCAPE,true)
	_key(KEY_ESCAPE,false)
	await _frames()
	_check(app.game_menu.visible,"Focused text field swallowed menu Escape")
	app.menu_flow.return_to_city()
	await _frames()
	_check(root.gui_get_focus_owner() == editor,"Return did not restore prior editor focus")
	input_layer.queue_free()
	await _frames()
	app._set_mode("overhead")
	app.menu_flow.open_menu()
	await _frames()
	app.game_menu.show_page("display")
	await _frames()
	app.game_menu.mode_picker.grab_focus()
	app.game_menu.mode_picker.get_popup().popup()
	await _frames()
	_key(KEY_ESCAPE,true)
	_key(KEY_ESCAPE,false)
	await _frames()
	_check(app.game_menu.visible and app.game_menu.page == "display" and not app.game_menu.popup_open(),"Escape did not dismiss the foremost dropdown alone")
	_key(KEY_ESCAPE,true)
	_key(KEY_ESCAPE,false)
	await _frames()
	_check(app.game_menu.page == "root","Escape did not leave Display submenu")
	var held_pose: Transform3D = app.cameras.camera.global_transform
	_key(KEY_W,true)
	_key(KEY_E,true)
	app.menu_flow.return_to_city()
	await _frames(4)
	_check(app.navigation_rearm,"Return did not wait for held movement keys to be released")
	_check(app.cameras.camera.global_transform.is_equal_approx(held_pose),"Held movement continued after menu close")
	_key(KEY_W,false)
	_key(KEY_E,false)
	await _frames()
	_check(not app.navigation_rearm,"Released movement keys did not rearm navigation")
	app.menu_flow.open_menu()
	await _frames()
	_key(KEY_ENTER,true)
	_key(KEY_ENTER,false)
	await _frames()
	_check(not app.game_menu.visible,"Enter did not activate focused Return")
	_check(not app.close_seen,"Return closed application")
	_finish()

func _layout_and_focus() -> void:
	var menu := Menu.new()
	root.add_child(menu)
	menu.set_open(true)
	await _frames()
	for size: Vector2i in [Vector2i(960,540),Vector2i(1280,720),Vector2i(1920,1080),Vector2i(3440,1440),Vector2i(5120,1440)]:
		for scale_value: float in [1.0,1.25,1.5]:
			var logical: Vector2 = Vector2(size)/scale_value
			menu.layout(logical)
			for page: String in ["root","display","controls","exit","error","confirm_unsaved"]:
				menu.show_page(page)
				await _frames()
				_check(Rect2(Vector2.ZERO,logical).grow(1).encloses(menu.panel.get_rect()),"Menu overflow at %s scale=%s page=%s" % [size,scale_value,page])
				var controls: Array[Control] = menu._focusables()
				_check(not controls.is_empty(),"Menu page has no keyboard-accessible action: "+page)
				for control: Control in controls:
					_check(control.focus_mode == Control.FOCUS_ALL,"Menu action lacks keyboard focus")
				var visited: Dictionary = {}
				for index: int in controls.size()+1:
					var current: Control = root.gui_get_focus_owner()
					if current != null: visited[current.get_instance_id()] = true
					var down := InputEventKey.new()
					down.physical_keycode = KEY_DOWN
					down.pressed = true
					menu.handle_key(down)
				_check(visited.size() == controls.size(),"Keyboard navigation escaped/skipped actions on "+page)
	menu.show_page("root")
	await _frames()
	_check(root.gui_get_focus_owner() == menu.buttons["return"],"Initial focus is not Return")
	menu.set_open(false)
	menu.queue_free()
	await _frames()

func _frames(count: int = 2) -> void:
	for index: int in count: await process_frame

func _key(code: int, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)
	Input.flush_buffered_events()

func _mouse(position: Vector2, button: int, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.position = position
	event.global_position = position
	event.button_index = button
	event.pressed = pressed
	root.push_input(event,true)

func _check(value: bool, message: String) -> void:
	if not value: failures.append(message)

func _finish() -> void:
	for code: int in [KEY_W,KEY_E,KEY_RIGHT,KEY_ESCAPE]: _key(code,false)
	if failures.is_empty(): print("GODOT_GAME_MENU_TESTS_OK layout, focus, four-view modal input, replay and editor restoration")
	else:
		for failure: String in failures: push_error(failure)
	quit(0 if failures.is_empty() else 1)
