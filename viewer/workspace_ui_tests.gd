extends SceneTree
const Main = preload("res://main.gd")
const Settings = preload("res://display_settings.gd")
var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var hud := preload("res://hud.gd").new()
	root.add_child(hud)
	var layer := CanvasLayer.new()
	root.add_child(layer)
	var diagnostics := preload("res://diagnostics.gd").new()
	layer.add_child(diagnostics)
	await process_frame
	await process_frame
	for dimensions: Vector2i in [Vector2i(1280,720),Vector2i(1440,900),Vector2i(1920,1080),Vector2i(2560,1440),Vector2i(3440,1440),Vector2i(5120,1440),Vector2i(960,540)]:
		for open: bool in [false,true]:
			diagnostics.set_open(open)
			var dock: Rect2 = diagnostics.layout(Vector2(dimensions))
			hud.layout(Vector2(dimensions),dock)
			await process_frame
			await process_frame
			var bounds := Rect2(Vector2.ZERO,Vector2(dimensions))
			for panel: Control in [hud.left_panel,hud.right_panel,hud.footer_panel,diagnostics]:
				if panel.visible:
					var rect: Rect2 = panel.get_rect()
					_check(bounds.grow(1).encloses(rect),"Panel overflow at %s / open=%s: %s" % [dimensions,open,rect])
			var content: Rect2 = hud.content_rect()
			_check(content.size.x >= 100 and content.size.y >= 100,"No usable city area at "+str(dimensions))
			if open: _check(not content.intersects(dock),"City interaction rectangle overlaps diagnostics")
	for field: Control in [LineEdit.new(),TextEdit.new(),SpinBox.new(),OptionButton.new()]:
		_check(not Main.camera_input_allowed(field,true),"Focused editor allowed camera input")
		field.free()
	_check(not Settings.valid_pair([{},null]),"Corrupt preference accepted")
	_check(not Settings.valid_pair([1,INF]),"Nonfinite preference accepted")
	_check(Settings.valid_pair([1440,900]),"Valid preference rejected")
	diagnostics.set_open(true)
	var emitted: Array = []
	diagnostics.action_requested.connect(func(action: String,value: Variant) -> void: emitted.append([action,value]))
	diagnostics.update_local({},{"population":200},{"capabilities":{"set_population":true,"population_max":5000}})
	_check(diagnostics.target_population.value == 200,"Initial target did not match loaded count")
	diagnostics.target_population.get_line_edit().text = "350"
	_check(emitted.is_empty(),"Editing target immediately changed population")
	diagnostics.apply_button.pressed.emit()
	_check(emitted == [["set_population",350]],"Apply did not emit custom population")
	for invalid: String in ["0","6000","3.5","ten"]:
		diagnostics.target_population.get_line_edit().text = invalid
		diagnostics.apply_button.pressed.emit()
	_check(emitted.size() == 1,"Invalid population was silently changed and submitted")
	diagnostics.receive_telemetry({"kind":"hardware","run_id":"test","payload":{"collected_at_unix":Time.get_unix_time_from_system()-20,"cpu":{"percent":50},"gpu":{"adapters":[{"gpu_utilization_percent":60}]}}})
	diagnostics.update_local({},{"population":200},{})
	_check(not diagnostics._hardware_live() and diagnostics.charts[1].values.back() == -1 and "STALE" in diagnostics.hardware_headline.text,"Stale hardware appeared as a fresh chart reading")
	for index: int in range(350):
		diagnostics.append_log({"id":str(index),"elapsed_seconds":index,"severity":"error" if index == 349 else "info","source":"worker","message":"row "+str(index)})
	_check(diagnostics.logs.size() == diagnostics.LOG_LIMIT,"Log history was not bounded")
	diagnostics.severity.select(3)
	diagnostics._refresh_logs()
	_check("row 349" in diagnostics.log_text.text and not "row 348" in diagnostics.log_text.text,"Severity filter failed")
	diagnostics.clear_visible_logs()
	_check(diagnostics.logs.is_empty(),"Clear view retained rows")
	diagnostics.append_log({"id":"349","elapsed_seconds":349,"message":"old snapshot row"})
	_check(diagnostics.logs.is_empty(),"Reconnect restored a cleared row")
	for index: int in range(130): diagnostics.update_local({},{"population":200},{})
	_check(diagnostics.local_series.size() == 120 and diagnostics.charts[0].values.size() == 120,"Chart history was not bounded")
	diagnostics.set_open(false)
	diagnostics.update_local({},{"population":200},{})
	_check(diagnostics.local_series.size() == 120,"Hidden console accumulated chart work")
	hud.queue_free()
	layer.queue_free()
	await process_frame
	if failures.is_empty(): print("GODOT_WORKSPACE_UI_TESTS_OK")
	else:
		for failure: String in failures: push_error(failure)
	quit(0 if failures.is_empty() else 1)

func _check(value: bool, message: String) -> void:
	if not value: failures.append(message)
