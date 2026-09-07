extends SceneTree
## --headless --path viewer --script res://run_metrics_tests.gd -- --replay <fixture> --geography ""
class BoundaryApp extends "res://main.gd":
	var phase_during_render: bool = false

	func _render_snapshot() -> void:
		super._render_snapshot()
		if phase_during_render:
			phase_during_render = false
			_emit_phase("fixture_mid_callback","settled")

var failures: Array[String] = []
var app: Node3D

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var early: Node3D = preload("res://main.gd").new()
	var early_clock_id: String = early.viewer_clock_id
	var waiting: Dictionary = early.run_metrics()
	_check(not waiting.simulation.ready and waiting.simulation.tick == null, "Early startup must not invent an authoritative simulation tick.")
	_check(waiting.performance.samples == 0 and waiting.performance.scenery_cache.geography.is_empty(), "Early startup metrics must work before scenery exists.")
	early.token = "private-authentication-sentinel"
	early.scene_message = {"private_scene":"private-scene-sentinel"}
	early.displayed = {"tick":42,"simulation_time":60.0,"clock_seconds":28850.0,"paused":true,"speed":4.0,"residents":[],"buildings":[{"private_building":"private-building-sentinel"}]}
	for index: int in range(10000): early.displayed.residents.append({"id":"private-resident-sentinel","position":[0,0,0],"trip":{"points":[[1,2,3]]}})
	early.frame_samples.assign([10.0,20.0,30.0])
	early.phase_samples.presentation.assign([2.0,4.0,6.0])
	var aggregate: Dictionary = early.run_metrics()
	var encoded: String = JSON.stringify(aggregate)
	_check(aggregate.simulation.resident_count == 10000 and aggregate.simulation.tick == 42, "Runtime metrics lost the authoritative tick or aggregate population.")
	_check(aggregate.performance.samples == 3 and aggregate.performance.p50_ms == 20.0, "Frame summaries must retain measured intervals.")
	_check(aggregate.performance.cpu_phases_ms.presentation.p50 == 4.0, "CPU phase summaries must retain measured intervals.")
	_check(not encoded.contains("private-") and encoded.length() < 16384, "Runtime metrics leaked private state or scaled with resident records.")
	_check(JSON.parse_string(encoded) is Dictionary, "Runtime metrics must serialize as a JSON object.")
	_check(aggregate.viewer_clock_id == early_clock_id and not early_clock_id.is_empty(), "Viewer clock identity must remain stable between reports.")
	_check(aggregate.window_start_local_usec == early.phase_started_usec and aggregate.window_end_local_usec >= aggregate.window_start_local_usec, "Metrics need ordered raw local window boundaries.")
	_check(aggregate.clock_uncertainty_seconds == null, "Unconnected metrics must not invent clock certainty.")
	early._emit_run_metrics(true)
	var final_usec: int = early.run_metrics_last_usec
	early._emit_run_metrics(true)
	early._maybe_emit_run_metrics(final_usec+early.RUN_METRICS_INTERVAL_USEC)
	_check(early.run_metrics_final_reported and early.run_metrics_last_usec == final_usec, "A finalized viewer must not emit duplicate or later metrics.")
	early.free()
	app = BoundaryApp.new()
	root.add_child(app)
	var deadline: int = Time.get_ticks_msec()+45000
	while not app.startup_complete and not app.startup_failed and Time.get_ticks_msec() < deadline:
		await process_frame
	_check(app.startup_complete and not app.startup_failed, "Replay did not reach a usable view for runtime diagnostics.")
	if app.startup_complete:
		var current: Dictionary = app.run_metrics()
		_check(current.simulation.ready and current.simulation.resident_count == 1, "Live replay metrics did not report the actual crowd.")
		_check(current.startup.complete and current.startup.usable_ms >= 0.0, "Usable startup timing is missing from runtime diagnostics.")
		_check(current.presentation.mode == app.initial_mode, "Runtime diagnostics reported the wrong camera mode.")
		_check(current.viewer_clock_id != early_clock_id, "Separate viewers reused a clock identity.")
		app.set_process(false)
		app._emit_phase("fixture_boundary","settled")
		app.previous_frame_usec = app.phase_started_usec-1000
		app._process(0.001)
		_check(app.frame_samples.is_empty(), "An interval starting before the phase boundary entered its samples.")
		app.phase_started_usec = Time.get_ticks_usec()-100000
		app.phase_signature = app._configuration_signature()
		app.previous_frame_usec = app.phase_started_usec+1000
		app._process(0.001)
		_check(app.frame_samples.size() == 1, "A complete interval inside the phase was discarded.")
		app.phase_during_render = true
		app.previous_frame_usec = Time.get_ticks_usec()-1000
		app._process(0.001)
		_check(app.frame_samples.is_empty(), "A phase emitted during presentation retained a straddling interval.")
		for samples: Array in app.phase_samples.values():
			_check(samples.is_empty(), "A phase emitted during presentation retained straddling CPU timings.")
		app.set_process(true)
		app.run_metrics_last_usec = Time.get_ticks_usec()-app.RUN_METRICS_INTERVAL_USEC
		var previous_usec: int = app.run_metrics_last_usec
		app._maybe_emit_run_metrics(Time.get_ticks_usec())
		_check(app.run_metrics_last_usec > previous_usec and not app.run_metrics_final_reported, "Periodic diagnostics did not update after the interval.")
	if failures.is_empty():
		print("GODOT_RUN_METRICS_TESTS_OK")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _check(condition: bool, message: String) -> void:
	if not condition: failures.append(message)
