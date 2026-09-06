extends RefCounted
## Functional checks use actual MultiMesh roots and the same selection path as the UI.
const Coordinates = preload("res://coordinates.gd")

func run(app: Node3D) -> String:
	if not app.world.asset_loaded or app.world.asset_mesh_count == 0 or app.crowd.batches.size() != 7:
		return "The actual GLB and seven crowd batches must load."
	if app.crowd.ids.is_empty(): return "Simulation has no persistent resident identities."
	var follow_daylight: bool = app.daylight.enabled
	app._action("lighting",false)
	if app.daylight.enabled or app.world.daylight_sun.rotation.distance_to(app.daylight.fixed.rotation) > 0.00001: return "Fixed lighting did not restore the captured environment."
	app._action("lighting",true)
	if not app.daylight.enabled or not app.hud.daylight_toggle.button_pressed: return "Daylight controls did not follow the visual clock."
	app._action("lighting",follow_daylight)
	if app.geography.available:
		var original_facades: bool = app.geography.facades_enabled
		app._action("facades",not original_facades)
		if app.hud.facade_toggle.button_pressed == original_facades or bool(app.geography.building_material.get_shader_parameter("facades_enabled")) == original_facades: return "Facade controls did not update the shared material."
		app._action("facades",original_facades)
	if app.street_trees != null and app.street_trees.available:
		var original_trees: bool = app.street_trees.enabled
		app._action("trees",false)
		if app.street_trees.visible or app.hud.trees_toggle.button_pressed or app.street_trees.displayed_count != 0: return "Street-tree controls left the layer visible."
		app._action("trees",true)
		if not app.street_trees.visible or not app.hud.trees_toggle.button_pressed: return "Street-tree controls could not restore the layer."
		app._action("trees",original_trees)
		if app.street_trees.cached_count > app.street_trees.CACHE_TREE_LIMIT or app.street_trees.loaded.size() > app.street_trees.CACHE_LIMIT: return "Street-tree loading exceeded its bounded cache."
		for tile: Dictionary in app.street_trees.loaded.values():
			for shape: String in app.street_trees.SHAPES:
				for tree: Dictionary in tile.by_shape[shape].slice(0,3):
					var base: Vector3 = tree.transform.origin
					var height: Variant = app.terrain.display_height_at(base.x,-base.z)
					if height == null or absf(base.y-float(height)) > 0.002: return "A street tree does not share the displayed terrain datum."
	if app.place_outline != null and app.place_outline.available:
		if not app._jump_place("Golden Gate Park") or app.place_outline.selected_id != "sf-neighborhood:Golden Gate Park" or app.place_outline.segment_count <= 0: return "Named destination did not display its checked source boundary."
		app._action("city_overview")
		if not app.place_outline.selected_id.is_empty() or not app.hud.place_search.active_id.is_empty(): return "City overview retained a misleading named boundary."
		if not app._jump_place("Mission") or app.place_outline.selected_id != "sf-neighborhood:Mission": return "Switching named areas did not replace the boundary."
		if app._jump_place("No such destination xxyy") or not app.place_outline.selected_id.is_empty(): return "Unknown destination retained a misleading boundary."
		if not app._jump_place("Transamerica Pyramid") or not app.place_outline.selected_id.is_empty(): return "Landmark selection retained a prior area boundary."
		app._action("city_hall")
	var first_id: String = app.crowd.ids[0]
	app._select(first_id)
	var navigation_failure: String = preload("res://navigation_input_checks.gd").new().run(app)
	if not navigation_failure.is_empty(): return navigation_failure
	app.hud.set_controls_collapsed(true)
	app.hud.set_inspector_collapsed(true)
	if app.hud.controls_body.visible or app.hud.inspector_body.visible or not app.hud.compact_clock.visible: return "Collapsed controls still obscure the city."
	app.hud.toggle_panels()
	if not app.hud.controls_body.visible or not app.hud.inspector_body.visible: return "Hidden panels cannot be reopened."
	app.hud.set_controls_collapsed(not app.is_pilot)
	app.hud.set_inspector_collapsed(not app.is_pilot)
	for mode: String in ["overhead","walk","follow"]:
		app._set_mode(mode)
		if not app.cameras.camera.position.is_finite(): return "Invalid camera in " + mode
	if not app.cameras._can_walk_to(app.cameras.walk_position): return "Walking spawn intersects a building."
	if app.cameras._can_walk_to(Vector3(99999,2,99999)): return "Walk bounds do not reject outside points."
	if not app.replay.is_empty():
		var seen_activities: Dictionary = {}
		# Starting at a later CLI frame must not make the monotonic live guard
		# silently skip the beginning of this independent replay verification.
		app._seek_replay(0)
		for snapshot: Dictionary in app.replay.snapshots:
			if str(snapshot.session_id) != app.session_id:
				var scene: Dictionary = app.replay.scene.duplicate(true)
				scene.session_id = snapshot.session_id
				app._receive_scene(scene)
			app._receive_snapshot(snapshot)
			app.presenter.atomic = true
			app._render_snapshot()
			if not app.crowd.records.has(first_id): return "A persistent resident vanished on arrival."
			seen_activities[str(app.crowd.records[first_id].activity)] = true
			var failure: String = _check_roots(app)
			if not failure.is_empty(): return failure
			if app.selected_id != first_id: return "Arrival or record reorder changed selected identity."
			app._set_mode("follow")
			if not app.cameras.follow_available: return "An indoor resident cannot be followed."
			await app.get_tree().process_frame
		if seen_activities.size() < 2: return "Replay does not demonstrate an activity transition."
		# An older sequence must not overwrite the displayed arrival state.
		var sequence: int = app.sequence
		app._receive_snapshot(app.replay.snapshots[0])
		if app.sequence != sequence: return "Stale snapshot moved the presentation backward."
	else:
		var ack: Dictionary = await _command(app,"pause",true)
		if str(ack.get("type","")) != "ack": return "Pause was not acknowledged."
		await app.get_tree().process_frame
		var tick: int = int(app.presenter.current.get("tick",-1))
		await app.get_tree().create_timer(0.15).timeout
		if int(app.presenter.current.get("tick",-1)) != tick: return "Paused simulation advanced."
		ack = await _command(app,"step",2000)
		if str(ack.get("type","")) != "ack": return "Deterministic step was not acknowledged."
		await app.get_tree().process_frame
		if int(app.presenter.current.get("tick",-1)) != tick + 2000: return "Step did not advance exactly 2000 ticks."
		ack = await _command(app,"speed",60)
		if str(ack.get("type","")) != "ack": return "Speed was not acknowledged."
		await app.get_tree().process_frame
		if int(app.presenter.current.get("speed",0)) != 60: return "Acknowledged speed was not displayed."
		app.presenter.atomic = true
		app._render_snapshot()
		var failure: String = _check_roots(app)
		if not failure.is_empty(): return failure
		var saved_tick: int = int(app.presenter.current.tick)
		var saved_session: String = app.session_id
		var saved_position: Array = app.crowd.records[first_id].position.duplicate()
		var saved_camera: Vector3 = app.cameras.camera.position
		var slot: String = "viewer-smoke-%d" % OS.get_process_id()
		ack = await _command(app,"save",slot)
		if str(ack.get("type","")) != "ack": return "Saving a local checkpoint was not acknowledged."
		ack = await _command(app,"step",400)
		if str(ack.get("type","")) != "ack": return "Could not advance after saving."
		ack = await _command(app,"load",slot)
		if str(ack.get("type","")) != "ack": return "Loading a local checkpoint was not acknowledged: %s; connection: %s" % [JSON.stringify(ack),app.last_error]
		await app.get_tree().process_frame
		app.presenter.atomic = true
		app._render_snapshot()
		if app.session_id == saved_session or int(app.presenter.current.tick) != saved_tick: return "Checkpoint load did not restore its tick in a new session."
		if not bool(app.presenter.current.paused) or int(app.presenter.current.speed) != 60: return "Checkpoint load lost playback controls."
		if app.selected_id != first_id or app.crowd.records[first_id].position != saved_position: return "Checkpoint load lost resident identity or position."
		app._update_follow()
		app.cameras.update_camera(0.0)
		if app.cameras.camera.position.distance_to(saved_camera) > 0.001: return "Checkpoint load changed the user's camera."
	if app.is_pilot:
		# Pick the authored pilot architecture through the physics ray path.
		await app.get_tree().physics_frame
		var finial := Vector3(0,77.4,-30)
		app.cameras.camera.position = finial + Vector3(0.01,25,0)
		app.cameras.camera.look_at(finial,Vector3.UP)
		app._select_at(app.cameras.camera.unproject_position(finial))
		if app.selected_id != "city-hall": return "Camera ray did not select City Hall."
	else:
		if app.world.pilot_visible or app.world.detailed_block.visible: return "Authentic city mode still displays the synthetic pilot block."
		if app.geography.pilot_enabled or not app.geography.pilot_exclusion.is_empty(): return "Authentic city mode still excludes actual City Hall geography."
		if app.terrain.available and app.terrain.pilot_enabled: return "Authentic city mode still flattens real terrain."
		if not app.world.landmarks.records.is_empty():
			if not app.world.landmarks.visible or app.world.landmarks.mesh_count <= 0: return "The aligned city landmark did not become visible."
			for record: Dictionary in app.world.landmarks.records.values():
				var expected: Variant = app.terrain.triangle_height_at(float(record.position[0]),float(record.position[1]))
				if expected == null or absf(record.root.position.y-float(expected)) > 0.001: return "The city landmark does not share the route terrain datum."
				await app.get_tree().physics_frame
				var probe: Dictionary = _landmark_probe(record.root)
				if probe.is_empty(): return "The landmark has no rendered triangle for picking."
				app.cameras.camera.position = probe.point+probe.normal*30.0
				app.cameras.camera.look_at(probe.point,Vector3.FORWARD if absf(probe.normal.dot(Vector3.UP)) > 0.9 else Vector3.UP)
				app._select_at(app.cameras.camera.unproject_position(probe.point))
				if app.selected_id != str(record.id): return "The aligned landmark is not selectable by its actual source building ID."
				if not "Exterior height:" in app.selected_label or not "Real-world occupancy is not modeled" in app.selected_label: return "Unassigned landmark inspection lost its source, height or occupancy scope."
		if app.geography.use_context.available:
			var prior_overlay: bool = app.geography.use_context.enabled
			var selected_source: String = ""
			for identity: String in app.geography.use_context.building_tiles:
				if not app.geography.use_context.record_for(identity).get("land_use",{}).is_empty():
					selected_source = identity
					break
			if selected_source.is_empty(): return "Installed use metadata has no inspectable source group."
			app._action("use_overlay",true)
			if not bool(app.geography.building_material.get_shader_parameter("use_overlay")) or not app.hud.use_legend.visible: return "Building-use toggle did not update existing materials and legend."
			app._select("geography:"+selected_source,"Mapped source building")
			app.hud.update_display(app.displayed,app.crowd,app.cameras.mode,app.selected_id,app.selected_label,app.frame_ms)
			if not "Source group totals" in app.hud.inspector.text or not "not building capacities" in app.hud.inspector.text or not app.hud.source_link.visible: return "Building-use inspection lost source attribution or group-level scope."
			app._action("use_overlay",prior_overlay)
	app._select(first_id)
	app._set_mode("follow")
	return ""

func _landmark_probe(root: Node3D) -> Dictionary:
	# Open trusses and separated antenna tips have no solid centroid. Probe a
	# real outward-facing triangle rather than assuming every exterior is a box.
	for mesh: MeshInstance3D in root.find_children("*","MeshInstance3D",true,false):
		if mesh.mesh.get_surface_count() == 0: continue
		var arrays: Array = mesh.mesh.surface_get_arrays(0)
		var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
		var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
		var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
		if vertices.size() < 3 or normals.size() < 3: continue
		var a: int = indices[0] if indices.size() >= 3 else 0
		var b: int = indices[1] if indices.size() >= 3 else 1
		var c: int = indices[2] if indices.size() >= 3 else 2
		var point: Vector3 = mesh.to_global((vertices[a]+vertices[b]+vertices[c])/3.0)
		var normal: Vector3 = (mesh.global_basis*(normals[a]+normals[b]+normals[c])).normalized()
		if normal.length_squared() > 0.9: return {"point":point,"normal":normal}
	return {}

func _check_roots(app: Node3D) -> String:
	for identifier: String in app.crowd.ids:
		var person: Dictionary = app.crowd.records[identifier]
		var root: Transform3D = app.crowd.display_transforms[identifier]
		if root.origin.distance_to(Coordinates.to_world(person.position)) > 0.0001: return "Displayed root differs from the sampled snapshot."
		for batch: MultiMesh in app.crowd.batches:
			if not batch.custom_aabb.has_point(root.origin): return "A resident's GPU culling bounds exclude their actual position."
			var submitted: Transform3D = batch.get_instance_transform(int(app.crowd.slots[identifier]))
			if DisplayServer.get_name() != "headless" and submitted.origin.distance_to(root.origin) > 0.0001: return "GPU root differs from follow/picking root: %s vs %s" % [submitted.origin,root.origin]
			if DisplayServer.get_name() != "headless" and not bool(person.visible) and submitted.basis.x.length_squared() > 0.0001: return "An indoor person remains visible."
		if bool(person.visible):
			var origin: Vector3 = root.origin + Vector3(0,0.9,3)
			if app.crowd.pick(origin,Vector3.FORWARD,4.0).is_empty(): return "Displayed resident is not pickable."
		if not bool(person.moving) and app.crowd.gait_angle(identifier) != 0.0: return "An idle person is walking in place."
	if app.crowd.animated_count > 300: return "Near-camera gait exceeded its population cap."
	return ""

func _command(app: Node3D, action: String, value: Variant) -> Dictionary:
	var identifier: String = app.client.command(action,value)
	var deadline: int = Time.get_ticks_msec() + (60000 if action in ["save","load","population"] else 10000)
	while not app.ack_results.has(identifier) and Time.get_ticks_msec() < deadline:
		await app.get_tree().process_frame
	var ack: Dictionary = app.ack_results.get(identifier,{})
	if str(ack.get("type","")) != "ack": return ack
	# An acknowledgment can precede its snapshot by several framed TCP reads.
	# Anchor assertions to the acknowledged state, never an arbitrary frame wait.
	while Time.get_ticks_msec() < deadline:
		var state: Dictionary = app.presenter.current
		var matched: bool = str(state.get("session_id","")) == str(ack.get("session_id","")) and int(state.get("tick",-1)) >= int(ack.get("tick",0))
		if action == "pause": matched = matched and bool(state.get("paused",not bool(value))) == bool(value)
		if action == "speed": matched = matched and int(state.get("speed",0)) == int(value)
		if matched: return ack
		await app.get_tree().process_frame
	return {"type":"error","message":"Acknowledged state did not arrive before the smoke deadline.","ack":ack}
