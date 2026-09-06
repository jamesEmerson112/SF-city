extends RefCounted
## Exercise the map through the live application's presentation and control paths.
const Coordinates = preload("res://coordinates.gd")
const Commands = preload("res://smoke_checks.gd")

func run(app: Node3D) -> String:
	if not app.map_active or app._view_mode() != "map" or not app.get_viewport().disable_3d:
		return "Map mode did not disable viewport 3D rendering."
	if app._resident_view() != app.map_2d or not app.map_2d.visible:
		return "The active resident view is not the 2D canvas."
	if app.hud.use_toggle.visible or app.hud.daylight_toggle.get_parent().visible or app.hud.facade_toggle.visible or app.hud.trees_toggle.get_parent().visible:
		return "The map still exposes inactive 3D graphics controls."
	if app.map_2d.ids.is_empty(): return "The map has no persistent resident identities."
	var commands := Commands.new()
	if app.replay.is_empty():
		var pause: Dictionary = await commands._command(app,"pause",true)
		if str(pause.get("type","")) != "ack": return "Map pause was not acknowledged: " + JSON.stringify(pause)
		var speed_failure: String = await _check_map_speed_controls(app)
		if not speed_failure.is_empty(): return speed_failure
	else:
		app.replay_paused = true
	app.presenter.atomic = true
	app._render_snapshot()
	var first_id: String = app.map_2d.ids[0]
	app._select(first_id)
	var navigation_failure: String = preload("res://navigation_input_checks.gd").new().run(app)
	if not navigation_failure.is_empty(): return navigation_failure
	var failure: String = _check_records(app)
	if not failure.is_empty(): return failure
	failure = _check_pick(app,first_id)
	if not failure.is_empty(): return failure
	var paused_tick: int = int(app.presenter.current.get("tick",-1))
	var held_state: Dictionary = _domain_state(app)
	await app.get_tree().create_timer(0.15).timeout
	if int(app.presenter.current.get("tick",-1)) != paused_tick: return "The paused map advanced the simulation."
	if _domain_state(app) != held_state: return "The paused map changed authoritative resident state."
	failure = await _check_view_roundtrip(app,first_id)
	if not failure.is_empty(): return failure
	failure = _check_named_navigation(app)
	if not failure.is_empty(): return failure
	if app.replay.is_empty():
		failure = await _check_live(app,commands,first_id)
	else:
		failure = await _check_replay(app,first_id)
	if not failure.is_empty(): return failure
	app._set_mode("map")
	app._select(first_id)
	app.presenter.atomic = true
	app._render_snapshot()
	return _check_records(app)

func _check_map_speed_controls(app: Node3D) -> String:
	var paused_tick: int = int(app.presenter.current.tick)
	var session: String = app.session_id
	var was_collapsed: bool = app.hud.controls_collapsed
	app.hud.set_controls_collapsed(true)
	if not app.hud.map_speed.is_visible_in_tree(): return "The map speed control disappears when full controls are collapsed."
	for index: int in [2,0]:
		var expected_speed: int = 60 if index == 2 else 1
		var previous_acks: Dictionary = app.ack_results.duplicate(false)
		app.hud.map_speed.item_selected.emit(index)
		var deadline: int = Time.get_ticks_msec()+10000
		var acknowledged: bool = false
		while Time.get_ticks_msec() < deadline:
			for request_id: String in app.ack_results:
				if previous_acks.has(request_id): continue
				var response: Dictionary = app.ack_results[request_id]
				if str(response.get("action","")) == "speed" and str(response.get("type","")) == "ack": acknowledged = true
			var state: Dictionary = app.presenter.current
			if int(state.get("tick",-1)) != paused_tick or not bool(state.get("paused",false)) or str(state.get("session_id","")) != session:
				return "Changing map playback speed moved or resumed the paused simulation."
			if acknowledged and int(state.get("speed",0)) == expected_speed and app.hud.map_speed.selected == index and app.hud.speed_picker.selected == index: break
			await app.get_tree().process_frame
		if not acknowledged or int(app.presenter.current.get("speed",0)) != expected_speed:
			return "The map speed selector did not receive its acknowledged authoritative speed."
		if app.hud.map_speed.selected != index or app.hud.speed_picker.selected != index:
			return "The map and full speed selectors do not agree with the authoritative snapshot."
	app.hud.set_controls_collapsed(was_collapsed)
	return ""

func _check_records(app: Node3D) -> String:
	var people: Array = app.presenter.current.get("residents",[])
	if app.map_2d.ids.size() != people.size() or app.map_2d.records.size() != people.size():
		return "Map membership differs from the complete authoritative cohort."
	if app.map_2d.marker_positions.size() != people.size() or app.map_2d.display_transforms.size() != people.size():
		return "Indoor arrival removed a map marker or its recorded position."
	var outdoors: int = 0
	for person: Dictionary in people:
		var identifier: String = str(person.id)
		if not app.map_2d.records.has(identifier): return "A resident identity vanished from the map: " + identifier
		var record: Dictionary = app.map_2d.records[identifier]
		if record.position != person.position: return "The map changed original domain coordinates: " + identifier
		for field: String in ["activity","visible","moving","building_id","home_id","work_id","trip"]:
			if record.get(field) != person.get(field): return "The map changed authoritative resident " + field
		var transform_value: Transform3D = app.map_2d.display_transforms[identifier]
		if transform_value.origin != Coordinates.to_world(person.position): return "The map changed the root used for inspection and following."
		if bool(person.get("visible",false)): outdoors += 1
	if app.map_2d.outdoor_count != outdoors: return "Map outdoor count differs from the snapshot."
	if app.map_2d.animated_count != 0: return "Character animation remains active in the 2D map."
	var selected: Dictionary = app.map_2d.records.get(app.selected_id,{})
	var trip: Variant = selected.get("trip")
	if trip is Dictionary:
		if app.map_2d.selected_route.size() != trip.get("points",[]).size(): return "The selected map route differs from the authoritative trip."
	elif not app.map_2d.selected_route.is_empty():
		return "An indoor arrival retained the previous walking route."
	return ""

func _check_pick(app: Node3D, identifier: String) -> String:
	app._select(identifier)
	app.map_2d.frame_selected()
	var marker: Vector2 = app.map_2d.marker_positions[identifier]
	var pixel: Vector2 = app.map_2d.world_to_screen(marker)
	if app.map_2d.screen_to_world(pixel).distance_to(marker) > 0.005: return "Map projection does not round-trip its drawn marker."
	# Lowest sorted identity wins at coincident markers; all remain in the list.
	var picked: String = app.map_2d.pick(pixel)
	if picked.is_empty() or not app.map_2d.records.has(picked): return "A displayed map marker cannot be picked."
	app._select_at(pixel)
	if app.selected_id != picked: return "Map clicks do not use the map marker picking path."
	app._select(identifier)
	return ""

func _check_view_roundtrip(app: Node3D, identifier: String) -> String:
	var original_center: Vector2 = app.map_2d.center
	var scale: float = app.map_2d.meters_per_pixel
	var domain: Dictionary = _domain_state(app)
	app.map_2d.pan_pixels(Vector2(37,-21))
	if app.map_2d.center.distance_to(original_center+Vector2(-37,-21)*scale) > 0.01: return "Map drag did not pan in screen coordinates."
	var cursor: Vector2 = app.get_viewport().get_visible_rect().size*Vector2(0.61,0.44)
	var anchor: Vector2 = app.map_2d.screen_to_world(cursor)
	var wheel := InputEventMouseButton.new()
	wheel.button_index = MOUSE_BUTTON_WHEEL_UP
	wheel.pressed = true
	wheel.position = cursor
	app._unhandled_input(wheel)
	if app.map_2d.meters_per_pixel >= scale: return "Mouse-wheel up zooms out instead of in on the map."
	if app.map_2d.screen_to_world(cursor).distance_to(anchor) > 0.01: return "Map zoom moved the point beneath the cursor."
	var held_center: Vector2 = app.map_2d.center
	var held_scale: float = app.map_2d.meters_per_pixel
	for mode: String in ["overhead","follow"]:
		app._set_mode(mode)
		if app.map_active or app.get_viewport().disable_3d or app.map_2d.visible: return "Returning to " + mode + " did not restore 3D rendering."
		await app.get_tree().process_frame
		if app._view_mode() != mode or not app.cameras.camera.position.is_finite(): return "The restored 3D camera is invalid."
		if app.crowd.records.size() != app.map_2d.records.size(): return "Returning to 3D lost resident membership."
		for person: Dictionary in app.presenter.current.residents:
			if app.crowd.records.get(str(person.id),{}).get("position") != person.position: return "Returning to 3D used stale resident positions."
		if mode == "follow" and not app.cameras.follow_available: return "The selected map resident cannot be followed in 3D."
		app._set_mode("map")
		if not app.get_viewport().disable_3d or not app.map_2d.visible: return "Returning to the map left 3D rendering enabled."
		if app.map_2d.center != held_center or app.map_2d.meters_per_pixel != held_scale: return "A view switch discarded map pan or zoom."
		if app.selected_id != identifier or _domain_state(app) != domain: return "A view switch changed selection or simulation state."
	var frozen: Dictionary = _three_d_state(app)
	for frame: int in range(8): await app.get_tree().process_frame
	if _three_d_state(app) != frozen: return "3D camera, crowd, lighting or scenery continued updating in map mode."
	if _domain_state(app) != domain: return "Map pan or zoom changed the simulation."
	return ""

func _check_named_navigation(app: Node3D) -> String:
	if not app.places.available or app.places.entries.is_empty(): return ""
	var record: Dictionary = app.places.resolve("Mission")
	if record.is_empty(): record = app.places.entries[0]
	var domain: Dictionary = _domain_state(app)
	var center: Vector2 = app.map_2d.center
	var scale: float = app.map_2d.meters_per_pixel
	var camera: Transform3D = app.cameras.camera.global_transform
	if not app._jump_place(str(record.id)): return "A named destination could not frame the map."
	if not app.map_active or app.hud.place_search.active_id != str(record.id): return "Named map navigation changed mode or lost its destination label."
	if app.cameras.camera.global_transform != camera: return "Named map navigation moved the saved 3D camera."
	app._set_mode("overhead")
	if not app.hud.place_search.active_id.is_empty() or not app.place_outline.selected_id.is_empty(): return "Returning to the saved 3D camera retained another map's place label."
	app._set_mode("map")
	var can_walk: bool = true
	if app.terrain.available:
		can_walk = app.terrain.display_height_at(float(record.target[0]),float(record.target[1])) != null and app.terrain.display_height_at(float(record.walk_position[0]),float(record.walk_position[1])) != null
	if can_walk:
		if not app._jump_place(str(record.id),"walk"): return "Walk nearby street failed from a named map destination."
		if app.map_active or app._view_mode() != "walk" or app.get_viewport().disable_3d: return "Named walking navigation did not restore the 3D walk view."
		if app.hud.place_search.active_id != str(record.id): return "Named walking navigation lost its intended place label."
		app._set_mode("map")
		if not app.hud.place_search.active_id.is_empty(): return "Returning to the saved map retained another 3D view's place label."
	if _domain_state(app) != domain: return "Named navigation changed the resident simulation."
	# Restore this smoke's map framing; the later reset/reconnect checks retain it.
	app.map_2d.jump_to(center,scale*minf(app.get_viewport().get_visible_rect().size.x,app.get_viewport().get_visible_rect().size.y))
	return ""

func _check_replay(app: Node3D, identifier: String) -> String:
	var seen: Dictionary = {}
	app._seek_replay(0)
	app.replay_paused = true
	app._select(identifier)
	for snapshot: Dictionary in app.replay.snapshots:
		if str(snapshot.session_id) != app.session_id:
			var scene: Dictionary = app.replay.scene.duplicate(false)
			scene["session_id"] = snapshot.session_id
			app._receive_scene(scene)
			if not app.map_2d.records.is_empty() or not app.map_2d.marker_positions.is_empty(): return "A new scene retained map residents from the prior session."
		app._receive_snapshot(snapshot)
		app.presenter.atomic = true
		app._render_snapshot()
		var failure: String = _check_records(app)
		if not failure.is_empty(): return failure
		if not app.map_2d.records.has(identifier) or app.selected_id != identifier: return "A replay transition changed the selected persistent identity."
		seen[str(app.map_2d.records[identifier].activity)] = true
		failure = _check_pick(app,identifier)
		if not failure.is_empty(): return failure
		await app.get_tree().process_frame
	if str(app.replay.scene.scenario.get("id","")) == "civic-center-walking-day-v1" and app.replay.snapshots.size() >= 7:
		for activity: String in ["home","walking_to_work","at_work","walking_home"]:
			if not seen.has(activity): return "The complete replay did not show map activity: " + activity
	var latest: Dictionary = _domain_state(app)
	app._receive_snapshot(app.replay.snapshots[0])
	if _domain_state(app) != latest: return "A stale replay snapshot moved the map backwards."
	return ""

func _check_live(app: Node3D, commands: RefCounted, identifier: String) -> String:
	var tick: int = int(app.presenter.current.tick)
	var ack: Dictionary = await commands._command(app,"next_event",null)
	if str(ack.get("type","")) != "ack": return "Map Next activity was not acknowledged: " + JSON.stringify(ack)
	app.presenter.atomic = true
	app._render_snapshot()
	if int(app.presenter.current.tick) < tick or not bool(app.presenter.current.paused): return "Next activity did not retain an authoritative paused state."
	var failure: String = _check_records(app)
	if not failure.is_empty(): return failure
	if app.selected_id != identifier: return "Next activity changed the selected resident."
	var stale: Dictionary = app.presenter.current
	var prior_session: String = app.session_id
	var held_center: Vector2 = app.map_2d.center
	var held_scale: float = app.map_2d.meters_per_pixel
	ack = await commands._command(app,"reset",null)
	if str(ack.get("type","")) != "ack": return "Map Reset day was not acknowledged: " + JSON.stringify(ack)
	if app.session_id == prior_session: return "Reset did not establish a fresh session."
	ack = await commands._command(app,"pause",true)
	if str(ack.get("type","")) != "ack": return "The reset map could not be paused."
	app.presenter.atomic = true
	app._render_snapshot()
	var reset_state: Dictionary = _domain_state(app)
	app._receive_snapshot(stale)
	if _domain_state(app) != reset_state: return "An old-session snapshot overwrote the reset map."
	failure = _check_records(app)
	if not failure.is_empty(): return failure
	var prior_sequence: int = app.sequence
	app._action("reconnect")
	var deadline: int = Time.get_ticks_msec()+20000
	while Time.get_ticks_msec() < deadline:
		if app.client.connected and app.sequence > prior_sequence and not app.presenter.current.is_empty(): break
		await app.get_tree().process_frame
	if not app.client.connected or app.sequence <= prior_sequence: return "Map reconnect did not obtain a fresh complete snapshot."
	app.presenter.atomic = true
	app._render_snapshot()
	if _domain_state(app) != reset_state: return "Reconnect changed a paused resident day."
	if app.selected_id != identifier: return "Reset or reconnect lost the selected resident."
	if app.map_2d.center != held_center or app.map_2d.meters_per_pixel != held_scale: return "Reset or reconnect discarded the user's map framing."
	return _check_records(app)

func _domain_state(app: Node3D) -> Dictionary:
	var snapshot: Dictionary = app.presenter.current
	var people: Dictionary = {}
	for person: Dictionary in snapshot.get("residents",[]):
		people[str(person.id)] = [person.position.duplicate(),person.get("activity"),person.get("building_id"),person.get("visible"),person.get("moving")]
	var occupancy: Dictionary = {}
	for building: Dictionary in snapshot.get("buildings",[]): occupancy[str(building.id)] = building.get("occupancy")
	return {"session":snapshot.get("session_id"),"tick":snapshot.get("tick"),"paused":snapshot.get("paused"),"speed":snapshot.get("speed"),"people":people,"occupancy":occupancy}

func _three_d_state(app: Node3D) -> Dictionary:
	return {
		"camera":app.cameras.camera.global_transform,
		"geography":app.geography.get_state(),
		"geography_requests":app.geography.requests.duplicate(),
		"terrain":app.terrain.get_state(),
		"terrain_pending":app.terrain.pending.duplicate(),
		"terrain_detailed_pending":app.terrain.detailed_pending.duplicate(),
		"trees":app.street_trees.get_state(),
		"daylight":app.daylight.get_state(),
		"crowd_roots":app.crowd.submitted_roots.duplicate(true),
		"crowd_time":app.crowd.simulation_time,
		"crowd_profile":app.crowd.last_profile.duplicate(true),
		"crowd_visibility_update":app.crowd.last_visibility_msec,
	}
