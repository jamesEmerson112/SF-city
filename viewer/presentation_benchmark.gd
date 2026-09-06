extends SceneTree
## Local dense-route interpolation benchmark; consumes two recorded snapshots.

func _initialize() -> void:
	var path: String = ProjectSettings.globalize_path("res://../.cache/sf-busy-1000-replay.json")
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or parsed.get("snapshots",[]).size() < 2:
		push_error("Dense-route benchmark needs .cache/sf-busy-1000-replay.json with two snapshots.")
		quit(1)
		return
	var first: Dictionary = parsed.snapshots[0]
	var second: Dictionary = parsed.snapshots[1]
	var before: Dictionary = {}
	for person: Dictionary in first.residents: before[str(person.id)] = person
	var stable_first: Array = []
	var stable_second: Array = []
	var route_points: int = 0
	var shared_geometry: bool = not "--full-geometry" in OS.get_cmdline_user_args()
	for person: Dictionary in second.residents:
		var prior: Dictionary = before.get(str(person.id),{})
		if bool(person.get("moving",false)) and bool(prior.get("moving",false)) and person.get("trip") is Dictionary and prior.get("trip") is Dictionary and person.trip.id == prior.trip.id:
			# city-routes-v1 expands snapshots with shared session geometry arrays.
			if shared_geometry: person.trip.points = prior.trip.points
			stable_first.append(prior)
			stable_second.append(person)
			route_points += person.trip.points.size()
	first.residents = stable_first
	second.residents = stable_second
	first.buildings = []
	second.buildings = []
	first.paused = false
	second.paused = false
	var presenter = preload("res://presenter.gd").new()
	var start: int = Time.get_ticks_usec()
	presenter.receive(first)
	presenter.receive(second)
	var prepare_ms: float = float(Time.get_ticks_usec()-start)/1000.0
	var samples: Array[float] = []
	var shown: Dictionary
	for i: int in range(20):
		presenter.blend_duration = 1.0
		presenter.received_at = Time.get_ticks_msec()/1000.0-0.5
		start = Time.get_ticks_usec()
		shown = presenter.sample()
		samples.append(float(Time.get_ticks_usec()-start)/1000.0)
	samples.sort()
	print("GODOT_DENSE_INTERPOLATION_PROFILE " + JSON.stringify({"residents":stable_second.size(),"route_points":route_points,"shared_geometry":shared_geometry,"prepare_ms":prepare_ms,"last_prepare_phases_ms":presenter.last_prepare_profile,"sample_p50_ms":samples[9],"sample_p95_ms":samples[18],"atomic":presenter.atomic,"sample_count":shown.residents.size()}))
	quit(0)
