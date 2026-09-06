extends SceneTree
## Rendered benchmark: --path viewer --script res://native/crowd_buffer_benchmark.gd
const ScriptBuffers = preload("res://native/crowd_buffers.gd")
var failures: Array[String] = []
var batches: Array[MultiMesh] = []
var roots: Array[Transform3D] = []
var custom := PackedColorArray()
var colors: Array[PackedColorArray] = []

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var count: int = 1000
	for index: int in range(count):
		var basis := Basis.from_euler(Vector3(0.13 * (index % 3), index * 0.017, 0.07 * (index % 5)))
		if index >= 880: basis = Basis.from_scale(Vector3.ZERO)
		roots.append(Transform3D(basis, Vector3(index-500.0, index*0.03, index*1.7)))
		custom.append(Color(fmod(index*0.317, 1.0), 1.0 if index % 3 == 0 else 0.0, 1.0 if index < 880 else 0.0, 1.0 if index == 42 else 0.0))
	for part: int in range(7):
		var values := PackedColorArray()
		for index: int in range(count): values.append(Color(fmod(index*0.13,1.0), part/7.0, 0.43, 1.0))
		colors.append(values)
		var batch := MultiMesh.new()
		batch.transform_format = MultiMesh.TRANSFORM_3D
		batch.use_colors = true
		batch.use_custom_data = true
		batch.mesh = BoxMesh.new()
		batch.instance_count = count
		batches.append(batch)
		for index: int in range(count): batch.set_instance_color(index, values[index])
	var script = ScriptBuffers.new()
	script.configure_colors(colors)
	var packed: Array[PackedFloat32Array] = script.build_buffers(roots, custom)
	_verify_engine_parity(packed)
	var timings: Dictionary = {"individual_all":[], "individual_transforms":[], "gdscript_bulk":[]}
	var native: Variant = null
	var extension_path: String = "res://native/civic_godot.gdextension"
	if FileAccess.file_exists(extension_path):
		var status: int = GDExtensionManager.load_extension(extension_path)
		if status not in [GDExtensionManager.LOAD_STATUS_OK, GDExtensionManager.LOAD_STATUS_ALREADY_LOADED]:
			failures.append("Native extension failed to load: " + str(status))
		elif ClassDB.class_exists("CivicCrowdBuffers"):
			native = ClassDB.instantiate("CivicCrowdBuffers")
			if native.protocol_version() != 1: failures.append("Native helper protocol mismatch.")
			native.configure_colors(colors)
			var native_buffers: Array = native.build_buffers(roots, custom)
			if native_buffers != packed: failures.append("Native buffers differ from the GDScript baseline.")
			timings["rust_bulk"] = []
	for iteration: int in range(110):
		# Interleave methods and force changing roots, like active commuters.
		for index: int in range(count): roots[index].origin.x += 0.001
		var started: int = Time.get_ticks_usec()
		for index: int in range(count):
			for batch: MultiMesh in batches:
				batch.set_instance_transform(index, roots[index])
				batch.set_instance_custom_data(index, custom[index])
		var individual: float = (Time.get_ticks_usec()-started)/1000.0
		started = Time.get_ticks_usec()
		# Current crowd skips hidden/static roots and unchanged gait flags.
		for index: int in range(880):
			for batch: MultiMesh in batches: batch.set_instance_transform(index, roots[index])
		var individual_transforms: float = (Time.get_ticks_usec()-started)/1000.0
		started = Time.get_ticks_usec()
		var buffers: Array[PackedFloat32Array] = script.build_buffers(roots, custom)
		for part: int in range(batches.size()): batches[part].buffer = buffers[part]
		var gdscript_bulk: float = (Time.get_ticks_usec()-started)/1000.0
		var rust_bulk: float = 0.0
		if native != null:
			started = Time.get_ticks_usec()
			var native_buffers: Array = native.build_buffers(roots, custom)
			for part: int in range(batches.size()): batches[part].buffer = native_buffers[part]
			rust_bulk = (Time.get_ticks_usec()-started)/1000.0
		if iteration >= 10:
			timings.individual_all.append(individual)
			timings.individual_transforms.append(individual_transforms)
			timings.gdscript_bulk.append(gdscript_bulk)
			if native != null: timings.rust_bulk.append(rust_bulk)
		await process_frame
	var summary: Dictionary = {"engine":Engine.get_version_info().string, "display":DisplayServer.get_name(), "instances":count, "parts":7, "samples":100, "native":native != null, "failures":failures}
	for mode: String in timings:
		var values: Array = timings[mode]
		values.sort()
		summary[mode] = {"p50_ms":values[49], "p95_ms":values[94], "p99_ms":values[98]}
	print("CROWD_BUFFER_BENCHMARK ", JSON.stringify(summary))
	for failure: String in failures: push_error(failure)
	quit(0 if failures.is_empty() else 1)

func _verify_engine_parity(buffers: Array[PackedFloat32Array]) -> void:
	# Headless uses a dummy RenderingServer; render mode verifies the real upload.
	if DisplayServer.get_name() == "headless": return
	for part: int in range(batches.size()):
		for index: int in range(roots.size()):
			batches[part].set_instance_transform(index, roots[index])
			batches[part].set_instance_custom_data(index, custom[index])
		var expected: PackedFloat32Array = batches[part].buffer
		batches[part].buffer = buffers[part]
		if batches[part].buffer != expected:
			failures.append("Bulk upload differs from individual transform/color/custom uploads for part " + str(part))
		for index: int in [0,1,11,42,999]:
			if not batches[part].get_instance_transform(index).is_equal_approx(roots[index]):
				failures.append("Bulk upload changed visible or hidden root pose.")
