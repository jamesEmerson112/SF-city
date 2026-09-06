extends Node3D
## All rendering, picking and follow share these ID-keyed, snapshot-derived roots.
const Coordinates = preload("res://coordinates.gd")
var visual: Dictionary = {}
var ids: Array[String] = []
var slots: Dictionary = {}
var records: Dictionary = {}
var display_transforms: Dictionary = {}
var batches: Array[MultiMesh] = []
var materials: Array[ShaderMaterial] = []
var animated_ids: Dictionary = {}
var visible_count: int = 0
var outdoor_count: int = 0
var animated_count: int = 0
var simulation_time: float = 0.0
var submitted_roots: Dictionary = {}
var submitted_custom: Dictionary = {}
var last_visibility_msec: int = -1000
var buffer_helper: RefCounted
var buffer_roots: Array[Transform3D] = []
var buffer_custom := PackedColorArray()
var draw_backend: String = "individual"
var last_error: String = ""
var last_profile: Dictionary = {}

func configure_bounds(bounds: Dictionary) -> void:
	var minimum: Array = bounds.min
	var maximum: Array = bounds.max
	var box := AABB(Vector3(float(minimum[0])-3.0,-250.0,-float(maximum[1])-3.0),Vector3(float(maximum[0])-float(minimum[0])+6.0,1500.0,float(maximum[1])-float(minimum[1])+6.0))
	for batch: MultiMesh in batches: batch.custom_aabb = box

func initialize(config: Dictionary) -> void:
	visual = config
	buffer_helper = preload("res://native/crowd_buffer_factory.gd").create()
	if buffer_helper != null:
		draw_backend = "rust" if buffer_helper.get_class() == "CivicCrowdBuffers" else "gdscript-buffer"
	for part: Dictionary in visual.character.parts:
		var mesh: Mesh
		if str(part.kind) == "sphere":
			var sphere := SphereMesh.new()
			sphere.radius = 1.0
			sphere.height = 2.0
			sphere.radial_segments = 12
			sphere.rings = 6
			mesh = sphere
		else:
			var box := BoxMesh.new()
			box.size = Vector3.ONE
			mesh = box
		var material := ShaderMaterial.new()
		material.shader = preload("res://crowd.gdshader")
		for key: String in ["center", "pivot"]:
			var value: Array = part.get(key, part.center)
			material.set_shader_parameter("part_" + key, Vector3(float(value[0]), float(value[1]), float(value[2])))
		var size: Array = part.get("size", [part.get("radius",1.0), part.get("radius",1.0), part.get("radius",1.0)])
		material.set_shader_parameter("part_size", Vector3(float(size[0]), float(size[1]), float(size[2])))
		material.set_shader_parameter("part_swing", float(part.get("swing", 0.0)))
		var batch := MultiMesh.new()
		batch.transform_format = MultiMesh.TRANSFORM_3D
		batch.use_colors = true
		batch.use_custom_data = true
		batch.mesh = mesh
		var minimum: Array = visual.bounds.min
		var maximum: Array = visual.bounds.max
		batch.custom_aabb = AABB(Vector3(float(minimum[0])-3.0,-3.0,-float(maximum[1])-3.0), Vector3(float(maximum[0])-float(minimum[0])+6.0,100.0,float(maximum[1])-float(minimum[1])+6.0))
		var instance := MultiMeshInstance3D.new()
		instance.name = "Residents-" + str(part.id)
		instance.multimesh = batch
		instance.material_override = material
		add_child(instance)
		batches.append(batch)
		materials.append(material)

func apply_snapshot(snapshot: Dictionary, camera: Camera3D, selected_id: String) -> void:
	var phase_started: int = Time.get_ticks_usec()
	var next_records: Dictionary = {}
	var membership_changed: bool = snapshot.get("residents",[]).size() != records.size()
	for person: Dictionary in snapshot.get("residents", []):
		var identifier: String = str(person.id)
		next_records[identifier] = person
		if not slots.has(identifier): membership_changed = true
	records = next_records
	if membership_changed:
		var retained: Array[String] = []
		for identifier: String in ids:
			if records.has(identifier): retained.append(identifier)
		for identifier: String in records:
			if not slots.has(identifier): retained.append(identifier)
		ids = retained
		slots = {}
		display_transforms = {}
		submitted_roots.clear()
		submitted_custom.clear()
		for i: int in range(ids.size()): slots[ids[i]] = i
		for batch: MultiMesh in batches: batch.instance_count = ids.size()
		buffer_roots.resize(ids.size())
		buffer_custom.resize(ids.size())
		_apply_colors()
	var membership_ms: float = float(Time.get_ticks_usec()-phase_started)/1000.0
	phase_started = Time.get_ticks_usec()
	simulation_time = float(snapshot.get("simulation_time", 0.0))
	var candidates: Array = []
	var frustum: Array[Plane] = []
	# Frustum counts are HUD metrics. They do not cull resident draw transforms,
	# determine picking, or decide gait; refreshing them at 5 Hz avoids thousands
	# of redundant plane tests on every rendered frame.
	var refresh_visibility: bool = membership_changed or Time.get_ticks_msec()-last_visibility_msec >= 200
	if refresh_visibility:
		last_visibility_msec = Time.get_ticks_msec()
		visible_count = 0
		if camera != null: frustum = camera.get_frustum()
	outdoor_count = 0
	for identifier: String in ids:
		var person: Dictionary = records[identifier]
		var root := Transform3D(Basis(Vector3.UP, float(person.get("heading",0.0))), Coordinates.to_world(person.position))
		display_transforms[identifier] = root
		if not bool(person.get("visible",false)):
			continue
		outdoor_count += 1
		var center: Vector3 = root.origin + Vector3.UP * 0.9
		var distance2: float = camera.global_position.distance_squared_to(center) if camera != null else INF
		if distance2 <= 6400.0 and bool(person.get("moving",false)):
			candidates.append([distance2, identifier])
		if refresh_visibility:
			var in_frustum: bool = camera != null
			for plane: Plane in frustum:
				if plane.is_point_over(center):
					in_frustum = false
					break
			if in_frustum: visible_count += 1
	visible_count = mini(visible_count,outdoor_count)
	var roots_ms: float = float(Time.get_ticks_usec()-phase_started)/1000.0
	phase_started = Time.get_ticks_usec()
	candidates.sort_custom(func(a: Array, b: Array) -> bool: return a[0] < b[0] if a[0] != b[0] else a[1] < b[1])
	animated_ids = {}
	for candidate: Array in candidates.slice(0, mini(300,candidates.size())): animated_ids[str(candidate[1])] = true
	animated_count = animated_ids.size()
	var gait_ms: float = float(Time.get_ticks_usec()-phase_started)/1000.0
	phase_started = Time.get_ticks_usec()
	var buffers_dirty: bool = false
	for identifier: String in ids:
		var person: Dictionary = records[identifier]
		var root: Transform3D = display_transforms[identifier]
		if not bool(person.get("visible",false)):
			root.basis = Basis.from_scale(Vector3.ZERO)
		var custom := Color(float(person.get("phase",0.0)), 1.0 if animated_ids.has(identifier) else 0.0, 1.0 if bool(person.get("moving",false)) else 0.0, 1.0 if identifier == selected_id else 0.0)
		if not submitted_roots.has(identifier) or submitted_roots[identifier] != root:
			if buffer_helper == null:
				for batch: MultiMesh in batches: batch.set_instance_transform(int(slots[identifier]),root)
			else: buffer_roots[int(slots[identifier])] = root
			buffers_dirty = true
			submitted_roots[identifier] = root
		if not submitted_custom.has(identifier) or submitted_custom[identifier] != custom:
			if buffer_helper == null:
				for batch: MultiMesh in batches: batch.set_instance_custom_data(int(slots[identifier]),custom)
			else: buffer_custom[int(slots[identifier])] = custom
			buffers_dirty = true
			submitted_custom[identifier] = custom
	var prepare_upload_ms: float = float(Time.get_ticks_usec()-phase_started)/1000.0
	phase_started = Time.get_ticks_usec()
	if buffers_dirty and buffer_helper != null: _upload_buffers()
	var buffer_ms: float = float(Time.get_ticks_usec()-phase_started)/1000.0
	for material: ShaderMaterial in materials: material.set_shader_parameter("simulation_time",simulation_time)
	last_profile = {"membership":membership_ms,"roots_candidates":roots_ms,"gait_order":gait_ms,"prepare_upload":prepare_upload_ms,"bulk_buffer":buffer_ms,"visibility_refreshed":refresh_visibility,"buffers_dirty":buffers_dirty}

func _apply_colors() -> void:
	var part_colors: Array[PackedColorArray] = []
	for part_index: int in range(batches.size()):
		var role: String = str(visual.character.parts[part_index].color_role)
		var key: String = {"clothes":"color","skin":"skin_color","trousers":"trouser_color","bag":"bag_color"}[role]
		var colors := PackedColorArray()
		for identifier: String in ids:
			var rgb: Array = records[identifier].get(key,[0.5,0.5,0.5])
			var color := Color(float(rgb[0]),float(rgb[1]),float(rgb[2]),1.0)
			if buffer_helper == null: batches[part_index].set_instance_color(int(slots[identifier]),color)
			else: colors.append(color)
		part_colors.append(colors)
	if buffer_helper != null and not buffer_helper.configure_colors(part_colors):
		last_error = "Draw helper rejected colors; using built-in uploads. " + str(buffer_helper.get_error_message())
		buffer_helper = null
		draw_backend = "individual"
		_apply_colors()

func _upload_buffers() -> void:
	# The helper only packs already-chosen draw roots, colors and gait flags.
	# It has no route sampler, resident clock, picking or follow state.
	var buffers: Array = buffer_helper.build_buffers(buffer_roots,buffer_custom)
	var valid: bool = buffers.size() == batches.size()
	for buffer: Variant in buffers:
		if not buffer is PackedFloat32Array or buffer.size() != ids.size()*20: valid = false
	if valid:
		for part: int in range(batches.size()): batches[part].buffer = buffers[part]
		return
	last_error = "Draw helper rejected a frame; using built-in uploads. " + str(buffer_helper.get_error_message())
	buffer_helper = null
	draw_backend = "individual"
	_apply_colors()
	for identifier: String in ids:
		for batch: MultiMesh in batches:
			batch.set_instance_transform(int(slots[identifier]),submitted_roots[identifier])
			batch.set_instance_custom_data(int(slots[identifier]),submitted_custom[identifier])

func pick(origin: Vector3, direction: Vector3, maximum: float) -> String:
	var selected: String = ""
	var nearest: float = maximum
	for identifier: String in ids:
		if not bool(records[identifier].get("visible",false)): continue
		var root: Transform3D = display_transforms[identifier]
		var box := AABB(root.origin + Vector3(-0.35,0.0,-0.35), Vector3(0.7,1.85,0.7))
		var point: Variant = box.intersects_ray(origin,direction)
		if point is Vector3:
			var distance: float = origin.distance_to(point)
			if distance < nearest:
				nearest = distance
				selected = identifier
	return selected

func gait_angle(identifier: String) -> float:
	if not animated_ids.has(identifier) or not records.has(identifier): return 0.0
	return sin(TAU * (1.6 * simulation_time + float(records[identifier].get("phase",0.0)))) * 0.55
