extends SceneTree
## Render comparisons exercise the actual shader, including the overlay bypass.
const Builder = preload("res://geography_mesh.gd")
var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var builder = Builder.new(Vector3(100,0,-200))
	var footprint: Array = [[100,200,18],[116,200,18],[116,212,18],[100,212,18]]
	if not builder.building({"footprint":footprint,"height_m":16.0,"use_category":3}): failures.append("Facade fixture did not build.")
	var walls: int = 0
	var roofs: int = 0
	for i: int in range(builder.vertices.size()):
		var use_uv: Vector2 = builder.use_coordinates[i]
		var facade_uv: Vector2 = builder.facade_coordinates[i]
		if not facade_uv.is_finite() or int(use_uv.x) != 3: failures.append("Facade attributes lost finite coordinates or source category."); break
		if absf(builder.normals[i].y) > 0.9:
			roofs += 1
			if use_uv.y != 0.0 or facade_uv != Vector2.ZERO: failures.append("Roof vertices received window coordinates."); break
		else:
			walls += 1
			if use_uv.y <= 0.0 or facade_uv.x < 0.0 or facade_uv.x > use_uv.y+0.001 or absf(facade_uv.y-(builder.vertices[i].y-18.0)) > 0.001:
				failures.append("Wall coordinates did not retain local meters and sampled base height."); break
	if walls != 24 or roofs != 6: failures.append("Facade attributes changed the extrusion's geometry count.")
	var roads = Builder.new()
	roads.street({"points":[[0,0,0],[20,0,0]],"width_m":8.0})
	if not roads.facade_coordinates.is_empty(): failures.append("Road meshes allocated unnecessary facade attributes.")
	if DisplayServer.get_name() != "headless": await _render_checks()
	if failures.is_empty():
		print("GODOT_FACADE_TESTS_OK wall meter coordinates, roof isolation, source categories" + (", rendered visible pattern, exact overlay bypass, distant fade" if DisplayServer.get_name() != "headless" else " (render checks require a display)"))
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _render_checks() -> void:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(256,256)
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(viewport)
	var scene := Node3D.new()
	viewport.add_child(scene)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_mode = Environment.BG_COLOR
	environment.environment.background_color = Color("18242b")
	environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.environment.ambient_light_color = Color.WHITE
	environment.environment.ambient_light_energy = 1.0
	scene.add_child(environment)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.size = 20.0
	camera.far = 2000.0
	camera.position = Vector3(8,8,30)
	scene.add_child(camera)
	camera.look_at(Vector3(8,8,0))
	var builder = Builder.new()
	builder.building({"footprint":[[0,0,0],[16,0,0],[16,12,0],[0,12,0]],"height_m":16,"use_category":3})
	var material: ShaderMaterial = preload("res://geography_use.gd").new().make_material()
	scene.add_child(builder.create_instance("Fixture",material))
	material.set_shader_parameter("facades_enabled",false)
	var plain: PackedByteArray = await _pixels(viewport)
	material.set_shader_parameter("facades_enabled",true)
	var decorated: PackedByteArray = await _pixels(viewport)
	if plain == decorated: failures.append("Nearby rendered facade toggle produced no visual pattern.")
	material.set_shader_parameter("use_overlay",true)
	var overlay: PackedByteArray = await _pixels(viewport)
	material.set_shader_parameter("facades_enabled",false)
	if overlay != await _pixels(viewport): failures.append("Procedural facades changed exact parcel-use overlay pixels.")
	material.set_shader_parameter("use_overlay",false)
	camera.position = Vector3(8,8,600)
	var distant_plain: PackedByteArray = await _pixels(viewport)
	material.set_shader_parameter("facades_enabled",true)
	if distant_plain != await _pixels(viewport): failures.append("Facade pattern did not disappear at city-scale distance.")
	viewport.queue_free()
	await process_frame

func _pixels(viewport: SubViewport) -> PackedByteArray:
	for frame: int in range(3): await process_frame
	await RenderingServer.frame_post_draw
	return viewport.get_texture().get_image().get_data()
