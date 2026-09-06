extends SceneTree
## Python-generated raw packet fixtures; no rendering or socket timing claims.
const Adapter = preload("res://scene_adapter.gd")

func _initialize() -> void:
	var directory: String = "../.cache/city-rows-profile"
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--directory="): directory = argument.trim_prefix("--directory=")
	var expected: Dictionary = {}
	var adapters: Dictionary = {}
	var packets: Dictionary = {}
	var samples: Dictionary = {}
	for mode: String in ["routes", "rows"]:
		var adapter = Adapter.new()
		var metadata: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join(mode + "-scene.json")))
		expected = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join(mode + "-full.json")))
		if not adapter.apply_scene(metadata): push_error(adapter.error_message); quit(1); return
		for line: String in FileAccess.get_file_as_string(directory.path_join(mode + "-definitions.ndjson")).split("\n", false):
			var definition: Dictionary = JSON.parse_string(line)
			if not adapter.apply_trip_geometries(definition): push_error(adapter.error_message); quit(1); return
		adapters[mode] = adapter
		packets[mode] = FileAccess.get_file_as_string(directory.path_join(mode + ".json"))
		samples[mode] = {"json_ms":[], "expand_ms":[], "total_ms":[]}
		var actual: Dictionary = adapter.expand_snapshot(JSON.parse_string(packets[mode]))
		if actual != expected: push_error("Raw Python " + mode + " packet differs from authoritative full state: " + adapter.error_message); quit(1); return
	for iteration: int in range(24):
		for mode: String in (["routes", "rows"] if iteration % 2 else ["rows", "routes"]):
			var started: int = Time.get_ticks_usec()
			var parsed: Dictionary = JSON.parse_string(packets[mode])
			var decoded: int = Time.get_ticks_usec()
			var expanded: Dictionary = adapters[mode].expand_snapshot(parsed)
			var ended: int = Time.get_ticks_usec()
			if expanded.is_empty(): push_error(adapters[mode].error_message); quit(1); return
			if iteration >= 3:
				samples[mode].json_ms.append((decoded-started)/1000.0)
				samples[mode].expand_ms.append((ended-decoded)/1000.0)
				samples[mode].total_ms.append((ended-started)/1000.0)
	var report: Dictionary = {"engine":Engine.get_version_info().string, "samples":21, "parity":true, "population":expected.residents.size()}
	for mode: String in samples:
		report[mode] = {}
		for phase: String in samples[mode]:
			var values: Array = samples[mode][phase]
			values.sort()
			report[mode][phase] = values[values.size()/2]
	print("CIVIC_TRANSPORT_BENCHMARK " + JSON.stringify(report))
	var report_file := FileAccess.open(directory.path_join("godot.json"), FileAccess.WRITE)
	if report_file != null: report_file.store_string(JSON.stringify(report, "  "))
	quit(0)
