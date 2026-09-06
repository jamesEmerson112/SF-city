extends SceneTree
## Exercises actual launcher handoff, partial initialization, failure, and reveal.
## --headless --path viewer --script res://startup_checks.gd -- --startup-file user://startup-checks.json
var app: Node3D
var startup_path: String = ""

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	startup_path = _argument("--startup-file","")
	if startup_path.is_empty():
		_finish("Startup checks require --startup-file pointing to a disposable status file.")
		return
	_write_status({"schema_version":1,"status":"preparing","message":"Preparing the City Hall block. Please wait."})
	app = preload("res://main.gd").new()
	root.add_child(app)
	for frame: int in range(5): await process_frame
	if app.loading_screen == null or not app.loading_screen.visible or app.startup_initialized or app.world != null:
		_finish("Loading screen did not appear before world initialization.")
		return
	var early_input := InputEventKey.new()
	early_input.physical_keycode = KEY_G
	early_input.pressed = true
	app._unhandled_input(early_input)
	if app.world != null:
		_finish("Input unexpectedly initialized scenery during launcher preparation.")
		return
	await _capture(_argument("--loading-screenshot",""))
	_write_status({"schema_version":1,"status":"error","message":"Fixture: city preparation could not finish."})
	var deadline: int = Time.get_ticks_msec()+5000
	while not app.startup_failed and Time.get_ticks_msec() < deadline: await process_frame
	if not app.startup_failed or not app.loading_screen.failed or not app.loading_screen.visible or app.world != null:
		_finish("Launcher failure did not replace loading with a visible error before world import.")
		return
	await _capture(_argument("--error-screenshot",""))
	app.queue_free()
	await process_frame
	_write_status({"schema_version":1,"status":"preparing","message":"Preparing the City Hall block. Please wait."})
	app = preload("res://main.gd").new()
	root.add_child(app)
	for frame: int in range(5): await process_frame
	var replay_path: String = ProjectSettings.globalize_path("res://../contracts/one-resident-replay.json").simplify_path()
	_write_status({"schema_version":1,"status":"ready","arguments":["--replay",replay_path,"--geography","","--mode",_argument("--mode","overhead"),"--no-render-cache"]})
	deadline = Time.get_ticks_msec()+45000
	var checked_before_snapshot: bool = false
	var checked_replay_wait: bool = false
	while not app.startup_complete and not app.startup_failed and Time.get_ticks_msec() < deadline:
		if app.startup_initialized and not app.ready_reported and not checked_before_snapshot:
			var previous_presentation_ms: float = app.last_presentation_ms
			app.last_presentation_ms = -123.0
			app._process(0.016)
			if app.last_presentation_ms != -123.0:
				_finish("Presentation or scenery started before the first authoritative snapshot.")
				return
			app.last_presentation_ms = previous_presentation_ms
			checked_before_snapshot = true
		if app.ready_reported and not app.startup_complete and not checked_replay_wait:
			if app.replay_paused:
				_finish("The replay fixture must start unpaused to check loading behavior.")
				return
			var waiting_index: int = app.replay_index
			var waiting_elapsed: float = app.replay_elapsed
			app._process(2.0)
			if app.replay_index != waiting_index or app.replay_elapsed != waiting_elapsed or app.replay_paused:
				_finish("Unpaused replay playback advanced or changed its pause state behind the loading screen.")
				return
			checked_replay_wait = true
		await process_frame
	if not checked_replay_wait:
		_finish("Startup check did not observe an unpaused replay behind the loading screen.")
		return
	if not checked_before_snapshot:
		_finish("Startup check did not observe the initial simulation wait.")
		return
	if not app.startup_complete or app.loading_screen.visible or not app.hud.visible or app.displayed.is_empty():
		_finish("The prepared city did not reveal a usable first snapshot and HUD.")
		return
	if app.startup_first_paint_ms < 0.0 or app.startup_first_snapshot_ms < app.startup_first_paint_ms or app.startup_usable_ms < app.startup_first_snapshot_ms:
		_finish("Startup timing milestones are not ordered.")
		return
	if app.startup_frames.is_empty() or app.startup_stages.size() < 6:
		_finish("Startup timing omitted loading frames or import stages.")
		return
	var ready_replay_index: int = app.replay_index
	app._process(2.0)
	if app.replay_index != ready_replay_index+1 or app.replay_paused:
		_finish("Unpaused replay playback did not resume after the loading screen cleared.")
		return
	app._seek_replay(ready_replay_index)
	# Direct frame profiling must retain intervals discarded from steady state.
	app.scenery_was_pending = true
	var previous_total: int = app.streaming_total_frames
	app._process(0.016)
	if app.streaming_total_frames != previous_total+1 or app.streaming_profile().samples < 1:
		_finish("Streaming frame timing lost the interval after loading work.")
		return
	await _capture(_argument("--ready-screenshot",""))
	print("GODOT_STARTUP_CHECKS_OK " + JSON.stringify(app.startup_profile()))
	quit(0)

func _write_status(value: Dictionary) -> void:
	var file: FileAccess = FileAccess.open(startup_path,FileAccess.WRITE)
	if file == null:
		_finish("Could not write startup check fixture.")
		return
	file.store_string(JSON.stringify(value))
	file.close()

func _argument(name_value: String, fallback: String) -> String:
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	var index: int = arguments.find(name_value)
	return arguments[index+1] if index >= 0 and index+1 < arguments.size() else fallback

func _capture(path: String) -> void:
	if path.is_empty(): return
	if DisplayServer.get_name() == "headless":
		_finish("Startup screenshots need a rendered check.")
		return
	await RenderingServer.frame_post_draw
	var screenshot: Image = root.get_texture().get_image()
	var error: Error = screenshot.save_png(path)
	if error != OK: _finish("Could not save startup screenshot: " + error_string(error))

func _finish(message: String) -> void:
	push_error(message)
	print("GODOT_STARTUP_CHECKS_FAIL " + message)
	quit(1)
