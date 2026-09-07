extends RefCounted
## Rendered integration probe. Run through scripts/benchmark_live_workspace.py.
var report: Dictionary = {"schema_version":1,"checks":[],"measurements":[],"layouts":[],"failures":[]}
var output_path: String = ""

func run(app: Node3D, arguments: PackedStringArray) -> String:
	app.get_window().title = "SF-city - Automated validation (close window to cancel)"
	output_path = app._argument(arguments,"--workspace-probe","")
	var count_text: String = app._argument(arguments,"--probe-counts","200,500,1000,2000,5000")
	var seconds: float = float(app._argument(arguments,"--probe-seconds","3"))
	var counts: Array[int] = []
	for part: String in count_text.split(","):
		if not part.is_valid_int() or int(part) < 1 or int(part) > 5000: return _failure("Probe counts must be integers from 1 to 5000.")
		counts.append(int(part))
	if output_path.is_empty() or seconds <= 0.0 or not is_finite(seconds): return _failure("Probe output and positive measurement duration are required.")
	report["rendered"] = DisplayServer.get_name() != "headless"
	report["renderer"] = RenderingServer.get_current_rendering_method()
	report["graphics_adapter"] = RenderingServer.get_video_adapter_name()
	report["measurement_seconds_requested"] = seconds
	report["counts_requested"] = counts
	var ack: Dictionary = await _command(app,"pause",true)
	if str(ack.get("type","")) != "ack": return _failure("Initial pause failed: "+JSON.stringify(ack))
	if int(app.presenter.current.get("tick",0)) < 60000:
		ack = await _command(app,"step",60000-int(app.presenter.current.get("tick",0)))
		if str(ack.get("type","")) != "ack": return _failure("Could not enter an active commute interval.")
	app.presenter.atomic = true
	app._render_snapshot()
	var fixed_tick: int = int(app.presenter.current.tick)
	var original_mode: String = app._view_mode()
	var baseline_ids: Dictionary = _residents(app.presenter.current)
	var baseline_count: int = baseline_ids.size()
	if not baseline_ids.is_empty():
		app._select(str(baseline_ids.keys()[0]))
	report["starting_tick"] = fixed_tick
	report["starting_population"] = baseline_count
	report["scenario_seed"] = app.scene_message.get("scenario",{}).get("seed",null)
	report["initial_metrics"] = app.run_metrics()
	if "--probe-layouts" in arguments:
		var layout_failure: String = await _layouts(app)
		if not layout_failure.is_empty(): return _failure(layout_failure)
	app.diagnostics.set_open(false)
	await app.get_tree().process_frame
	var fixed_map_rect: Rect2 = app.map_2d.content_rect
	var fixed_map_center: Vector2 = app.map_2d.center
	var fixed_map_scale: float = app.map_2d.meters_per_pixel
	var fixed_map_bearing: float = app.map_2d.bearing
	report["map_view_held_fixed"] = app.map_active
	report["comparison_context"] = app._phase_context()
	for count: int in counts:
		var before: Dictionary = _residents(app.presenter.current)
		var selected_before: String = app.selected_id
		var follow_before: String = app.follow_id
		var camera_before: Transform3D = app.cameras.camera.global_transform
		var world_before: int = app.world.get_instance_id()
		var geography_before: int = app.geography.get_instance_id()
		var terrain_before: int = app.terrain.get_instance_id()
		var began: int = Time.get_ticks_usec()
		var failure: String = await _population(app,count)
		if not failure.is_empty(): return _failure(failure)
		var transition_ms: float = float(Time.get_ticks_usec()-began)/1000.0
		var after: Dictionary = _residents(app.presenter.current)
		await app.get_tree().process_frame
		if after.has(selected_before) and app.selected_id != selected_before: return _failure("A surviving selection changed during resize.")
		if after.has(follow_before) and app.follow_id != follow_before: return _failure("A surviving follow target changed during resize.")
		if not app.cameras.camera.global_transform.is_equal_approx(camera_before): return _failure("The paused resize changed camera pose.")
		if app.world.get_instance_id() != world_before or app.geography.get_instance_id() != geography_before or app.terrain.get_instance_id() != terrain_before: return _failure("Static world nodes were replaced during resize.")
		if int(app.presenter.current.tick) != fixed_tick: return _failure("Live population change reset or advanced the paused day.")
		if not bool(app.presenter.current.paused): return _failure("Live population change lost pause state.")
		for identity: String in before:
			if after.has(identity) and before[identity] != after[identity]:
				return _failure("A surviving resident changed during paused resize: "+identity)
		var occupancy_error: String = _occupancy(app.presenter.current)
		if not occupancy_error.is_empty(): return _failure(occupancy_error)
		report.checks.append({"check":"paused_resize_survivors_and_occupancy","population":count,"tick":fixed_tick,"elapsed_ms":transition_ms})
		print("WORKSPACE_PROBE_PROGRESS "+JSON.stringify({"population":count,"stage":"paired_console_measurements"}))
		for pair: int in range(3):
			var order: Array = [false,true] if pair % 2 == 0 else [true,false]
			for open: bool in order:
				app.diagnostics.set_open(open)
				# Console docking normally changes map composition. Hold it fixed for
				# this controlled UI-cost comparison, then restore normal layout below.
				if app.map_active:
					app.map_2d.set_content_rect(fixed_map_rect)
					if app.map_2d.center != fixed_map_center or app.map_2d.meters_per_pixel != fixed_map_scale or app.map_2d.bearing != fixed_map_bearing:
						return _failure("Map pose changed during the controlled console comparison.")
				var settle_deadline: int = Time.get_ticks_msec()+120000
				while app._scenery_pending() and Time.get_ticks_msec() < settle_deadline:
					await app.get_tree().process_frame
				if app._scenery_pending(): return _failure("Scenery did not settle before measurement.")
				await app.get_tree().create_timer(0.25).timeout
				_reset_samples(app)
				var sample_start: int = Time.get_ticks_usec()
				await app.get_tree().create_timer(seconds).timeout
				var metrics: Dictionary = app.run_metrics()
				if app._view_mode() != original_mode: return _failure("Probe interrupted: view changed inside a controlled sample.")
				if app.map_active and app.map_2d.content_rect != fixed_map_rect: return _failure("Map framing changed inside a console sample.")
				report.measurements.append({"population":count,"pair":pair,"console_open":open,"elapsed_ms":float(Time.get_ticks_usec()-sample_start)/1000.0,"metrics":metrics,"map_pose":{"center":[app.map_2d.center.x,app.map_2d.center.y],"meters_per_pixel":app.map_2d.meters_per_pixel,"bearing":app.map_2d.bearing,"content_rect":[app.map_2d.content_rect.position.x,app.map_2d.content_rect.position.y,app.map_2d.content_rect.size.x,app.map_2d.content_rect.size.y]} if app.map_active else {}})

		_save()
	app._workspace_layout()
	var reject_text: String = OS.get_environment("CIVIC_WORKSPACE_REJECT_COUNT")
	if not reject_text.is_empty():
		if not reject_text.is_valid_int(): return _failure("Expected rejection count must be an integer.")
		var rejection_failure: String = await _expected_rejection(app,int(reject_text))
		if not rejection_failure.is_empty(): return _failure(rejection_failure)
	# Test real running changes separately from controlled paused measurements.
	ack = await _command(app,"speed",1)
	if str(ack.get("type","")) != "ack": return _failure("Running test could not set speed.")
	ack = await _command(app,"pause",false)
	if str(ack.get("type","")) != "ack": return _failure("Running test could not resume.")
	var tick_before: int = int(app.presenter.current.tick)
	await app.get_tree().create_timer(0.3).timeout
	var progress_deadline: int = Time.get_ticks_msec()+10000
	while int(app.presenter.current.tick) <= tick_before and Time.get_ticks_msec() < progress_deadline:
		await app.get_tree().process_frame
	if int(app.presenter.current.tick) <= tick_before: return _failure("The unpaused simulation did not advance.")
	var running_target: int = mini(5000,maxi(2,counts.back()+1))
	if running_target == counts.back(): running_target = maxi(1,running_target-1)
	var live_failure: String = await _population(app,running_target)
	if not live_failure.is_empty(): return _failure(live_failure)
	if bool(app.presenter.current.paused) or not is_equal_approx(float(app.presenter.current.speed),1.0): return _failure("Running resize lost playback state.")
	ack = await _command(app,"pause",true)
	if str(ack.get("type","")) != "ack" or int(app.presenter.current.tick) <= tick_before or not bool(app.presenter.current.paused):
		return _failure("Running resize lost the advancing day or pause control.")
	report.checks.append({"check":"running_resize","population":running_target,"tick_before":tick_before,"tick_after":int(app.presenter.current.tick)})
	# Select a removable newcomer and ensure shrinking detaches without a camera jump.
	var current_ids: Array = _residents(app.presenter.current).keys()
	var victim: String = ""
	for identity: String in current_ids:
		if not baseline_ids.has(identity): victim = identity
	if not victim.is_empty() and baseline_count < current_ids.size():
		app._select(victim)
		app._set_mode("follow")
		await app.get_tree().create_timer(0.5).timeout
		# Switching from map to a distant follow view can load terrain/collisions.
		# Establish a stable paused view before asserting removal preserves it.
		var quiet_since: int = Time.get_ticks_msec()
		var settle_deadline: int = quiet_since+60000
		var observed_pose: Transform3D = app.cameras.camera.global_transform
		while Time.get_ticks_msec()-quiet_since < 1000 and Time.get_ticks_msec() < settle_deadline:
			await app.get_tree().process_frame
			var next_pose: Transform3D = app.cameras.camera.global_transform
			if app._scenery_pending() or next_pose != observed_pose: quiet_since = Time.get_ticks_msec()
			observed_pose = next_pose
		if Time.get_ticks_msec()-quiet_since < 1000: return _failure("Follow view did not settle before the removal check.")
		var follow_pose: Transform3D = app.cameras.camera.global_transform
		live_failure = await _population(app,baseline_count)
		if not live_failure.is_empty(): return _failure(live_failure)
		if not _residents(app.presenter.current).has(victim):
			if app._view_mode() != "follow" or not app.cameras.follow_detached: return _failure("Removal did not detach the active follow camera.")
			await app.get_tree().process_frame
			if not app.cameras.camera.global_transform.is_equal_approx(follow_pose):
				return _failure("Removing the followed resident jumped the camera.")
			if not app.selected_id.is_empty() or not app.follow_id.is_empty():
				return _failure("Removed follow target remained selected or another person was selected automatically.")
			report.checks.append({"check":"removed_follow_target_detaches","population":baseline_count})
		else:
			report.checks.append({"check":"removed_follow_target_detaches","status":"skipped","reason":"Chosen newcomer survived the shrink."})
	else:
		report.checks.append({"check":"removed_follow_target_detaches","status":"skipped","reason":"No removable newcomer available."})
	# Saved state must include the changed roster and allow later changes.
	var slot: String = "workspace-probe-%d" % OS.get_process_id()
	var saved: Dictionary = _residents(app.presenter.current).duplicate(true)
	var saved_tick: int = int(app.presenter.current.tick)
	ack = await _command(app,"save",slot)
	if str(ack.get("type","")) != "ack": return _failure("Saving resized population failed: "+JSON.stringify(ack))
	ack = await _command(app,"step",400)
	if str(ack.get("type","")) != "ack" or int(app.presenter.current.tick) != saved_tick+400: return _failure("Checkpoint test could not advance away from the saved state.")
	ack = await _command(app,"load",slot)
	if str(ack.get("type","")) != "ack": return _failure("Restoring resized population failed: "+JSON.stringify(ack))
	if int(app.presenter.current.tick) != saved_tick or _residents(app.presenter.current) != saved:
		return _failure("Checkpoint did not restore the changed roster and exact resident state.")
	live_failure = await _population(app,mini(5000,saved.size()+1))
	if not live_failure.is_empty(): return _failure("Resize after restore: "+live_failure)
	report.checks.append({"check":"save_load_then_resize","saved_population":saved.size(),"saved_tick":saved_tick})
	app._set_mode(original_mode)
	app.diagnostics.set_open(true)
	await app.get_tree().create_timer(1.0).timeout
	report["final_metrics"] = app.run_metrics()
	report["status"] = "passed"
	if DisplayServer.get_name() != "headless":
		await RenderingServer.frame_post_draw
		var screenshot: Image = app.get_viewport().get_texture().get_image()
		var capture_path: String = output_path.get_basename()+".png"
		var capture_error: int = screenshot.save_png(capture_path)
		report["screenshot"] = capture_path.get_file() if capture_error == OK else ""
		report["screenshot_error"] = capture_error
	_save()
	return ""

func _layouts(app: Node3D) -> String:
	var window: Window = app.get_window()
	var previous: Vector2i = window.size
	for dimensions: Vector2i in [Vector2i(1280,720),Vector2i(1440,900),Vector2i(1920,1080),Vector2i(2560,1440),Vector2i(3440,1440),Vector2i(5120,1440)]:
		window.size = dimensions
		app.diagnostics.set_open(true)
		await app.get_tree().process_frame
		await app.get_tree().process_frame
		var available: Rect2 = app.hud.content_rect()
		if available.size.x <= 0.0 or available.size.y <= 0.0: return "Diagnostics left no usable city rectangle."
		report.layouts.append({"requested":[dimensions.x,dimensions.y],"actual":[window.size.x,window.size.y],"city_rect":[available.position.x,available.position.y,available.size.x,available.size.y]})
	window.size = previous
	await app.get_tree().process_frame
	for scale: float in [1.0,1.25,1.5]:
		app.display_settings.set_scale(scale,false)
		await app.get_tree().process_frame
		await app.get_tree().process_frame
		var bounds := Rect2(Vector2.ZERO,app.get_viewport().get_visible_rect().size)
		for panel: Control in [app.hud.left_panel,app.hud.right_panel,app.hud.footer_panel,app.diagnostics]:
			if panel.visible and not bounds.grow(1.0).encloses(panel.get_rect()): return "A panel overflowed at UI scale "+str(scale)
		var city: Rect2 = app.hud.content_rect()
		if city.size.x < 100 or city.size.y < 100: return "UI scaling left no usable city rectangle."
		report.layouts.append({"ui_scale":scale,"actual":[window.size.x,window.size.y],"viewport":[bounds.size.x,bounds.size.y],"city_rect":[city.position.x,city.position.y,city.size.x,city.size.y]})
	app.display_settings.set_scale(1.0,false)
	if DisplayServer.get_name() != "headless":
		for mode: String in ["maximized","fullscreen","windowed"]:
			app.display_settings.set_mode(mode,false)
			await app.get_tree().create_timer(0.3).timeout
			var expected: int = Window.MODE_MAXIMIZED if mode == "maximized" else (Window.MODE_FULLSCREEN if mode == "fullscreen" else Window.MODE_WINDOWED)
			if window.mode != expected: return "Display mode did not apply: "+mode
			report.layouts.append({"requested_mode":mode,"state":app.display_settings.state()})
	window.size = previous
	await app.get_tree().process_frame
	await app.get_tree().process_frame
	return ""

func _population(app: Node3D, count: int) -> String:
	var previous: int = app.presenter.current.get("residents",[]).size()
	var expected_mode: String = app._view_mode()
	app._action("set_population",count)
	var request_id: String = app.population_request
	if request_id.is_empty(): return "Population command was not submitted."
	var deadline: int = Time.get_ticks_msec()+120000
	while Time.get_ticks_msec() < deadline:
		if app._view_mode() != expected_mode: return "Probe interrupted: view changed during a population request."
		var response: Dictionary = app.ack_results.get(request_id,{})
		if str(response.get("type","")) == "error": return "Population request rejected: "+JSON.stringify(response)
		if app.presenter.current.get("residents",[]).size() == count and (count != previous or str(response.get("type","")) == "ack"):
			if count != previous:
				app.presenter.atomic = true
				app._render_snapshot()
			return ""
		if app.startup_failed: return "Application failed during population change: "+app.last_error
		await app.get_tree().process_frame
	return "Population change timed out requesting %d from %d. Last error: %s" % [count,previous,app.last_error]

func _expected_rejection(app: Node3D, target: int) -> String:
	var before: Dictionary = _residents(app.presenter.current)
	var tick: int = int(app.presenter.current.tick)
	var session: String = str(app.presenter.current.session_id)
	var revision: int = int(app.presenter.current.get("roster_revision",0))
	var pose: Transform3D = app.cameras.camera.global_transform
	var selection: String = app.selected_id
	var began: int = Time.get_ticks_usec()
	var failure: String = await _population(app,target)
	var response: Dictionary = app.ack_results.get(app.population_request,{})
	var message: String = str(response.get("message",""))
	if not failure.begins_with("Population request rejected:") or str(response.get("type","")) != "error" or not ("limit" in message.to_lower() or "budget" in message.to_lower()):
		return "Expected a bounded population rejection, received: "+failure
	var ack: Dictionary = await _command(app,"pause",true)
	if str(ack.get("type","")) != "ack" or not app.client.connected: return "Connection did not remain usable after rejecting population."
	if _residents(app.presenter.current) != before or int(app.presenter.current.tick) != tick or str(app.presenter.current.session_id) != session or int(app.presenter.current.get("roster_revision",0)) != revision:
		return "Rejected population change altered the existing day."
	if app.selected_id != selection or not app.cameras.camera.global_transform.is_equal_approx(pose): return "Rejected population change altered selection or camera."
	report.checks.append({"check":"oversized_population_rejected_without_state_change","requested_population":target,"population":before.size(),"tick":tick,"roster_revision":revision,"code":response.get("code",""),"message":message,"elapsed_ms":float(Time.get_ticks_usec()-began)/1000.0,"subsequent_command":"pause acknowledged"})
	return ""

func _command(app: Node3D, action: String, value: Variant) -> Dictionary:
	var identifier: String = app.client.command(action,value)
	var deadline: int = Time.get_ticks_msec()+120000
	while not app.ack_results.has(identifier) and Time.get_ticks_msec() < deadline:
		await app.get_tree().process_frame
	var ack: Dictionary = app.ack_results.get(identifier,{})
	if str(ack.get("type","")) != "ack": return ack
	while Time.get_ticks_msec() < deadline:
		var current: Dictionary = app.presenter.current
		if str(current.get("session_id","")) == str(ack.get("session_id","")) and int(current.get("tick",-1)) >= int(ack.get("tick",0)):
			if action == "pause" and bool(current.get("paused",not bool(value))) != bool(value):
				await app.get_tree().process_frame
				continue
			return ack
		await app.get_tree().process_frame
	return {"type":"error","message":"Acknowledged state was not delivered."}

func _residents(snapshot: Dictionary) -> Dictionary:
	var result: Dictionary = {}
	for resident: Dictionary in snapshot.get("residents",[]): result[str(resident.id)] = resident.duplicate(true)
	return result

func _occupancy(snapshot: Dictionary) -> String:
	var residents: Dictionary = _residents(snapshot)
	var seen: Dictionary = {}
	for building: Dictionary in snapshot.get("buildings",[]):
		if int(building.get("occupancy",-1)) != building.get("resident_ids",[]).size(): return "Building occupancy differs from its residents."
		for identity: String in building.get("resident_ids",[]):
			if seen.has(identity) or not residents.has(identity): return "Occupancy contains a duplicate or removed resident."
			if str(residents[identity].get("building_id","")) != str(building.id): return "Resident and building occupancy disagree."
			seen[identity] = true
	for identity: String in residents:
		if residents[identity].get("building_id") != null and not seen.has(identity): return "Indoor resident is absent from its building."
	return ""

func _reset_samples(app: Node3D) -> void:
	app._emit_phase("console_comparison_sample","settled")

func _failure(message: String) -> String:
	report.failures.append(message)
	report["status"] = "failed"
	_save()
	return message

func _save() -> void:
	if output_path.is_empty(): return
	var file: FileAccess = FileAccess.open(output_path,FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify(report,"\t"))
		file.close()
