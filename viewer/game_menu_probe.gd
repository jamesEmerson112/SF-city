extends RefCounted
## Functional probe for the real launcher. Uses an isolated --save-dir.
var output_path: String = ""
var report: Dictionary = {"schema_version":1,"status":"running","checks":[],"failures":[]}
var started_usec: int = 0

func run(app: Node3D, path: String, case_name: String) -> String:
	output_path = path
	started_usec = Time.get_ticks_usec()
	report.merge({"case":case_name,"mode":app._view_mode(),"rendered":DisplayServer.get_name() != "headless","rendering_method":RenderingServer.get_current_rendering_method(),"graphics_adapter":RenderingServer.get_video_adapter_name(),"display":app.display_settings.state(),"initial_population":app.presenter.current.get("residents",[]).size()})
	app.client.acknowledged.connect(_record_ack)
	var ack: Dictionary = await _command(app,"pause",true)
	if ack.get("type") != "ack": return _failure("Could not pause before menu trial")
	ack = await _command(app,"step",60000)
	if ack.get("type") != "ack": return _failure("Could not prepare an occupied street")
	ack = await _command(app,"pause",false)
	if ack.get("type") != "ack": return _failure("Could not start running trial")
	if case_name == "population_exit":
		app._action("set_population",int(report.initial_population)+1)
		if app.population_request.is_empty(): return _failure("Live population request was not submitted")
	var opened_usec: int = Time.get_ticks_usec()
	_escape(app)
	await app.get_tree().process_frame
	await app.get_tree().process_frame
	report["menu_open_ms"] = float(Time.get_ticks_usec()-opened_usec)/1000.0
	if not app.game_menu.visible: return _failure("Injected Escape did not open vertical menu")
	if not await _settled(app): return _failure("Menu pause or prior operation did not settle")
	report["menu_open_to_paused_ms"] = float(Time.get_ticks_usec()-opened_usec)/1000.0
	report.checks.append("Escape opened menu and authoritative pause completed")
	var population: int = app.presenter.current.get("residents",[]).size()
	if population != int(report.initial_population)+(1 if case_name == "population_exit" else 0):
		return _failure("Population handoff did not preserve expected roster")
	report["population"] = population
	report["tick"] = int(app.presenter.current.tick)
	report["roster_revision"] = int(app.presenter.current.get("roster_revision",0))
	var rectangle: Rect2 = app.game_menu.panel.get_rect()
	report["menu_panel"] = [rectangle.position.x,rectangle.position.y,rectangle.size.x,rectangle.size.y]
	if not app.get_viewport().get_visible_rect().grow(1).encloses(rectangle):
		return _failure("Menu panel exceeded logical viewport")
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		var result: int = app.get_viewport().get_texture().get_image().save_png(output_path.get_basename()+".png")
		if result != OK: return _failure("Could not write rendered menu evidence")
	report["runtime"] = app.run_metrics()
	app.menu_flow.return_to_city()
	var deadline: int = Time.get_ticks_msec()+120000
	while Time.get_ticks_msec() < deadline:
		if not app.game_menu.visible and not bool(app.presenter.current.get("paused",true)):
			break
		await app.get_tree().process_frame
	if app.game_menu.visible or bool(app.presenter.current.get("paused",true)):
		return _failure("Returning from menu failed to resume the originally running day")
	report.checks.append("Return restored running state, including any live population handoff")
	_escape(app)
	if not await _settled(app): return _failure("Second menu pause did not settle")
	report["exit_started_usec"] = Time.get_ticks_usec()
	if case_name == "window_close":
		app.notification(Node.NOTIFICATION_WM_CLOSE_REQUEST)
	else:
		app.menu_flow.request_exit("menu")
	# Repeated OS close must not bypass saving or create another save.
	app.notification(Node.NOTIFICATION_WM_CLOSE_REQUEST)
	if case_name == "save_error":
		deadline = Time.get_ticks_msec()+120000
		while app.game_menu.page != "error" and Time.get_ticks_msec() < deadline:
			await app.get_tree().process_frame
		if app.game_menu.page != "error": return _failure("Forced save error did not keep the error menu open")
		if not app.game_menu.visible: return _failure("Application hid menu after save error")
		report.checks.append("Save failure kept application open for explicit choice")
		if DisplayServer.get_name() != "headless":
			await RenderingServer.frame_post_draw
			app.get_viewport().get_texture().get_image().save_png(output_path.get_basename()+"-error.png")
		report["status"] = "passed"
		_save()
		app.game_menu.show_page("confirm_unsaved")
		app.menu_flow.confirm_unsaved()
	else:
		report["status"] = "passed"
		report.checks.append("Save & Exit requested; final save ACK and process outcomes validated by outer harness")
		_save()
	# Keep this RefCounted probe alive until its ACK callback records the save.
	await app.tree_exiting
	return ""

func _escape(app: Node3D) -> void:
	app._set_probe_input_guard(false)
	for pressed: bool in [true,false]:
		var event := InputEventKey.new()
		event.keycode = KEY_ESCAPE
		event.physical_keycode = KEY_ESCAPE
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
	app._set_probe_input_guard(true)

func _settled(app: Node3D) -> bool:
	var deadline: int = Time.get_ticks_msec()+120000
	while Time.get_ticks_msec() < deadline:
		if app.game_menu.visible and bool(app.presenter.current.get("paused",false)) and app.client.pending.is_empty() and app.pending_population_scene.is_empty() and not app.diagnostics.pending:
			await app.get_tree().process_frame
			await app.get_tree().process_frame
			if bool(app.presenter.current.get("paused",false)) and app.client.pending.is_empty():
				return true
		if app.startup_failed: return false
		await app.get_tree().process_frame
	return false

func _command(app: Node3D, action: String, value: Variant) -> Dictionary:
	var identifier: String = app.client.command(action,value)
	var deadline: int = Time.get_ticks_msec()+120000
	while not app.ack_results.has(identifier) and Time.get_ticks_msec() < deadline:
		await app.get_tree().process_frame
	var ack: Dictionary = app.ack_results.get(identifier,{})
	if ack.get("type") != "ack": return ack
	while Time.get_ticks_msec() < deadline:
		var current: Dictionary = app.presenter.current
		if str(current.get("session_id","")) == str(ack.get("session_id","")) and int(current.get("tick",-1)) >= int(ack.get("tick",0)):
			if action != "pause" or bool(current.get("paused",not bool(value))) == bool(value):
				return ack
		await app.get_tree().process_frame
	return {"type":"error","message":"Acknowledged state was not delivered"}

func _record_ack(message: Dictionary) -> void:
	if str(message.get("action","")) != "save": return
	report["save_response"] = message
	if message.get("type") == "ack":
		report["exit_request_to_save_ack_ms"] = float(Time.get_ticks_usec()-int(report.get("exit_started_usec",Time.get_ticks_usec())))/1000.0
	_save()

func _failure(message: String) -> String:
	report.status = "failed"
	report.failures.append(message)
	_save()
	return message

func _save() -> void:
	report["probe_elapsed_ms"] = float(Time.get_ticks_usec()-started_usec)/1000.0
	var file := FileAccess.open(output_path,FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(report,"\t"))
		file.close()
