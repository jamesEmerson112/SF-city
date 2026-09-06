extends SceneTree
## Isolates crowd work from parsing/interpolation using frozen real 1,000 states.
const Coordinates = preload("res://coordinates.gd")

func _initialize() -> void: call_deferred("_run")

func _run() -> void:
	var fixture: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://../.cache/sf-busy-1000-replay.json"))
	if not fixture is Dictionary or fixture.get("snapshots",[]).size() < 2:
		push_error("Crowd benchmark needs .cache/sf-busy-1000-replay.json.")
		quit(1)
		return
	var first: Dictionary = fixture.snapshots[0]
	var second: Dictionary = fixture.snapshots[1]
	var earlier: Dictionary = {}
	for resident: Dictionary in first.residents: earlier[str(resident.id)] = resident
	for resident: Dictionary in second.residents:
		var prior: Dictionary = earlier[str(resident.id)]
		if resident.get("trip") is Dictionary and prior.get("trip") is Dictionary and str(resident.trip.id) == str(prior.trip.id): resident.trip.points = prior.trip.points
	var presenter = preload("res://presenter.gd").new()
	presenter.receive(first)
	presenter.receive(second)
	var states: Array[Dictionary] = []
	for fraction: float in [0.1,0.3,0.5,0.7,0.9]:
		presenter.blend_duration = 1.0
		presenter.received_at = Time.get_ticks_msec()/1000.0-fraction
		var sampled: Dictionary = presenter.sample()
		var frozen: Dictionary = sampled.duplicate(false)
		var residents: Array = []
		for resident: Dictionary in sampled.residents:
			var record: Dictionary = resident.duplicate(false)
			record.position = resident.position.duplicate()
			residents.append(record)
		frozen.residents = residents
		states.append(frozen)
	var camera := Camera3D.new()
	root.add_child(camera)
	var followed: String = ""
	for resident: Dictionary in states[0].residents:
		if bool(resident.visible):
			followed = str(resident.id)
			var position: Vector3 = Coordinates.to_world(resident.position)
			camera.position = position+Vector3(0,8,14)
			camera.look_at(position+Vector3.UP)
			break
	var config: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/visual.json"))
	var old_backend: String = OS.get_environment("CIVIC_CROWD_BACKEND")
	for backend: String in ["rust","individual"]:
		OS.set_environment("CIVIC_CROWD_BACKEND",backend)
		var crowd = preload("res://crowd.gd").new()
		root.add_child(crowd)
		crowd.initialize(config)
		crowd.configure_bounds({"min":[-10000,-10000],"max":[10000,10000]})
		if crowd.draw_backend != backend:
			push_error("Requested crowd benchmark backend is unavailable: "+backend)
			quit(1)
			return
		for mode: String in ["interpolating","unchanged"]:
			var samples: Array[float] = []
			var phases: Dictionary = {}
			var refreshes: int = 0
			var changed: int = 0
			for frame: int in range(200):
				var snapshot: Dictionary = states[frame%states.size()] if mode == "interpolating" else states[2]
				var started: int = Time.get_ticks_usec()
				crowd.apply_snapshot(snapshot,camera,followed)
				var elapsed: float = float(Time.get_ticks_usec()-started)/1000.0
				if frame >= 20:
					samples.append(elapsed)
					for key: String in ["membership","roots_candidates","gait_order","prepare_upload","bulk_buffer"]:
						if not phases.has(key): phases[key] = []
						phases[key].append(float(crowd.last_profile[key]))
					if crowd.last_profile.visibility_refreshed: refreshes += 1
					if crowd.last_profile.buffers_dirty: changed += 1
				await process_frame
			var result: Dictionary = {"backend":backend,"mode":mode,"resident_count":crowd.ids.size(),"outdoor_count":crowd.outdoor_count,"animated_count":crowd.animated_count,"samples":samples.size(),"total_ms":_percentiles(samples),"phases_ms":{},"frustum_refresh_frames":refreshes,"changed_buffer_frames":changed,"renderer":DisplayServer.get_name(),"fixture":"sf-busy-1000-replay v2, 1200.0-1200.1 seconds; frozen presented fractions 0.1/0.3/0.5/0.7/0.9"}
			for key: String in phases: result.phases_ms[key] = _percentiles(phases[key])
			print("GODOT_CROWD_ISOLATED_PROFILE "+JSON.stringify(result))
		for resident: Dictionary in states[2].residents:
			if crowd.display_transforms[str(resident.id)].origin.distance_to(Coordinates.to_world(resident.position)) > 0.00001:
				push_error("Crowd benchmark changed the presented root.")
				quit(1)
				return
		crowd.free()
	OS.set_environment("CIVIC_CROWD_BACKEND",old_backend)
	camera.free()
	quit(0)

func _percentiles(values: Array) -> Dictionary:
	var sorted: Array = values.duplicate()
	sorted.sort()
	return {"p50":sorted[int((sorted.size()-1)*0.5)],"p95":sorted[int((sorted.size()-1)*0.95)],"p99":sorted[int((sorted.size()-1)*0.99)]}
