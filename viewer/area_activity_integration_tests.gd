extends SceneTree
const Activity = preload("res://area_activity.gd")

func _initialize() -> void:
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	var oracle_path: String = arguments[0] if not arguments.is_empty() else ProjectSettings.globalize_path("res://../.cache/area-activity-oracle.json")
	var oracle: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(oracle_path))
	var replay: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(oracle.replay))
	var area_data: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(oracle.areas))
	var areas: Dictionary = {}
	for area: Dictionary in area_data.areas: areas[area.id] = area.polygons
	var failures: Array[String] = []
	var configure_ms: Array[float] = []
	var sample_ms: Array[float] = []
	for case: Dictionary in oracle.cases:
		var activity = Activity.new()
		var started: int = Time.get_ticks_usec()
		if not activity.configure(str(case.id),areas[case.id],replay.scene.scenario,str(replay.snapshots[0].session_id)):
			failures.append(str(case.id)+": "+activity.last_error)
			continue
		configure_ms.append(float(Time.get_ticks_usec()-started)/1000.0)
		for index: int in range(replay.snapshots.size()):
			started = Time.get_ticks_usec()
			var result: Dictionary = activity.sample(replay.snapshots[index])
			sample_ms.append(float(Time.get_ticks_usec()-started)/1000.0)
			for key: String in case.expected[index]:
				if result.get(key) != case.expected[index][key]: failures.append(str(case.id)+" frame "+str(index)+" "+key+" expected="+str(case.expected[index][key])+" actual="+str(result.get(key)))
	configure_ms.sort()
	sample_ms.sort()
	if failures.is_empty():
		print("GODOT_AREA_ACTIVITY_INTEGRATION_OK ",JSON.stringify({"areas":oracle.cases.size(),"snapshots":oracle.snapshot_count,"cohort_size":oracle.cohort_size,"configure_p50_ms":configure_ms[configure_ms.size()/2],"configure_max_ms":configure_ms[-1],"sample_p50_ms":sample_ms[sample_ms.size()/2],"sample_max_ms":sample_ms[-1],"people_here_sums":oracle.people_here_sums}))
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
