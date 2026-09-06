extends SceneTree
const Factory = preload("res://native/crowd_buffer_factory.gd")
var failures: Array[String] = []

func _initialize() -> void:
	var script: RefCounted = Factory.create("gdscript")
	_test_provider(script, "gdscript")
	var native: RefCounted = Factory.create("auto")
	if native != null:
		_test_provider(native, "rust")
	elif "--require-native" in OS.get_cmdline_user_args():
		failures.append("Required native crowd helper did not load.")
	if Factory.create("individual") != null:
		failures.append("Individual fallback unexpectedly required a buffer helper.")
	if failures.is_empty():
		print("CROWD_BUFFER_TESTS_OK native=", native != null, " exact poses/flags, frozen colors, detached outputs, bounds, empty/reordered slots, individual fallback")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _test_provider(helper: RefCounted, label: String) -> void:
	var empty_colors: Array[PackedColorArray] = []
	var empty_roots: Array[Transform3D] = []
	if not helper.configure_colors(empty_colors) or not helper.build_buffers(empty_roots, PackedColorArray()).is_empty():
		failures.append(label + ": empty crowd failed.")
	var colors: Array[PackedColorArray] = [PackedColorArray([Color(0.1,0.2,0.3,1), Color(0.7,0.8,0.9,1)]), PackedColorArray([Color(0.3,0.4,0.5,1), Color(0.9,0.2,0.4,1)])]
	var original_colors: Array[PackedColorArray] = []
	for values: PackedColorArray in colors: original_colors.append(values.duplicate())
	var roots: Array[Transform3D] = [Transform3D(Basis.from_euler(Vector3(0.23,1.17,-0.33)), Vector3(-321.5,47.25,118.75)), Transform3D(Basis.from_scale(Vector3.ZERO), Vector3(17,-6.0,-42))]
	var original_roots: Array[Transform3D] = roots.duplicate()
	var custom := PackedColorArray([Color(0.17,1,1,0),Color(0.79,0,0,1)])
	var original_custom: PackedColorArray = custom.duplicate()
	if not helper.configure_colors(colors): failures.append(label + ": valid appearance failed.")
	var buffers: Array[PackedFloat32Array] = helper.build_buffers(roots, custom)
	if buffers.size() != 2:
		failures.append(label + ": wrong part count.")
		return
	for part: int in range(2):
		if buffers[part].size() != 40: failures.append(label + ": wrong stride/count.")
		for index: int in range(2):
			var data: PackedFloat32Array = buffers[part]
			var offset: int = index*20
			var basis := Basis(Vector3(data[offset],data[offset+4],data[offset+8]), Vector3(data[offset+1],data[offset+5],data[offset+9]), Vector3(data[offset+2],data[offset+6],data[offset+10]))
			var decoded := Transform3D(basis, Vector3(data[offset+3],data[offset+7],data[offset+11]))
			if decoded != roots[index]: failures.append(label + ": heading/terrain/hidden root changed.")
			var tint := Color(data[offset+12],data[offset+13],data[offset+14],data[offset+15])
			var flags := Color(data[offset+16],data[offset+17],data[offset+18],data[offset+19])
			if tint != colors[part][index] or flags != custom[index]: failures.append(label + ": appearance, selection or gait flags changed.")
	if roots != original_roots or custom != original_custom or colors != original_colors:
		failures.append(label + ": packing mutated caller-owned draw inputs.")
	# Caller changes must not mutate frozen configuration or previous outputs.
	colors[0][0] = Color(1,0,0,1)
	if helper.build_buffers(roots,custom) != buffers:
		failures.append(label + ": configured colors were not detached from caller edits.")
	var invalid_colors: Array[PackedColorArray] = [PackedColorArray([Color.WHITE]), PackedColorArray()]
	if helper.configure_colors(invalid_colors): failures.append(label + ": inconsistent color membership accepted.")
	if helper.build_buffers(roots,custom) != buffers:
		failures.append(label + ": failed configuration changed the previous valid crowd.")
	if not helper.build_buffers(roots,PackedColorArray()).is_empty(): failures.append(label + ": mismatched custom-data count accepted.")
	var oversized := PackedColorArray()
	oversized.resize(100001)
	var oversized_colors: Array[PackedColorArray] = [oversized]
	if helper.configure_colors(oversized_colors): failures.append(label + ": instance bound was ignored.")
	var too_many_parts: Array[PackedColorArray] = []
	too_many_parts.resize(33)
	if helper.configure_colors(too_many_parts): failures.append(label + ": part bound was ignored.")
	# Membership/reordering is explicit in configuration, never inferred natively.
	roots.reverse()
	custom.reverse()
	var reordered: Array[PackedColorArray] = []
	for values: PackedColorArray in original_colors:
		var reversed: PackedColorArray = values.duplicate()
		reversed.reverse()
		reordered.append(reversed)
	helper.configure_colors(reordered)
	var next: Array[PackedFloat32Array] = helper.build_buffers(roots,custom)
	for part: int in range(2):
		if next[part].slice(0,20) != buffers[part].slice(20,40) or next[part].slice(20,40) != buffers[part].slice(0,20):
			failures.append(label + ": explicit slot reorder altered resident draw attributes.")
