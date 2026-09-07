extends Node3D
## Dedicated desktop viewer. Python owns the clock, schedules, routes and occupancy.
const Coordinates = preload("res://coordinates.gd")
const PROFILE_SAMPLE_LIMIT: int = 2400
const RUN_METRICS_INTERVAL_USEC: int = 10000000
var world: Node3D
var cameras: Node3D
var crowd: Node3D
var map_2d: Node2D
var map_active: bool = false
var map_configured: bool = false
var map_has_view: bool = false
var last_map_error: String = ""
var hud: CanvasLayer
var client: Node
var presenter := preload("res://presenter.gd").new()
var visual: Dictionary = {}
var scene_message: Dictionary = {}
var displayed: Dictionary = {}
var session_id: String = ""
var sequence: int = -1
var selected_id: String = ""
var selected_label: String = "Choose a person or click a building."
var follow_id: String = ""
var follow_camera_id: String = ""
var drag_distance: float = 0.0
var dragging: bool = false
var frame_ms: float = 16.67
var host: String = "127.0.0.1"
var port: int = 0
var token: String = ""
var replay: Dictionary = {}
var replay_index: int = 0
var replay_elapsed: float = 0.0
var replay_paused: bool = false
var replay_speed: float = 1.0
var smoke: bool = false
var screenshot_path: String = ""
var initial_mode: String = "overhead"
var automation_running: bool = false
var last_error: String = ""
var ready_reported: bool = false
var ack_results: Dictionary = {}
var initial_replay_index: int = 0
var geography: Node3D
var pan_drag: bool = false
var initial_location: String = "city-hall"
var terrain: Node3D
var is_pilot: bool = true
var frame_samples: Array[float] = []
var previous_frame_usec: int = 0
var last_presentation_ms: float = 0.0
var last_crowd_ms: float = 0.0
var last_validation_ms: float = 0.0
var last_prepare_ms: float = 0.0
var phase_samples: Dictionary = {"presentation":[],"crowd":[],"view":[],"area":[],"trees":[],"hud":[],"transport":[],"parse_and_delivery":[],"json_decode":[],"snapshot_expand":[],"snapshot_delivery":[],"resident_validation":[],"presentation_prepare":[]}
var hud_elapsed: float = 0.0
var view_elapsed: float = 0.0
var last_hud_sequence: int = -1
var last_hud_session: String = ""
var last_hud_selected: String = ""
var last_hud_mode: String = ""
var places := preload("res://places.gd").new()
var initial_place: String = ""
var initial_place_applied: bool = false
var follow_metadata_key: String = ""
var daylight := preload("res://daylight.gd").new()
var initial_lighting: String = "cycle"
var place_outline: Node3D
var street_trees: Node3D
var area_activity := preload("res://area_activity.gd").new()
var area_activity_state: Dictionary = {}
var area_activity_elapsed: float = 1.0
var loading_screen: CanvasLayer
var startup_initialized: bool = false
var startup_complete: bool = false
var startup_failed: bool = false
var startup_started_usec: int = 0
var startup_first_paint_ms: float = -1.0
var startup_first_snapshot_ms: float = -1.0
var startup_usable_ms: float = -1.0
var startup_stage_started_usec: int = 0
var startup_stage_name: String = ""
var startup_stages: Array[Dictionary] = []
var startup_frames: Array[float] = []
var startup_total_frames: int = 0
var startup_worst_ms: float = 0.0
var streaming_frames: Array[float] = []
var streaming_total_frames: int = 0
var streaming_worst_ms: float = 0.0
var streaming_total_ms: float = 0.0
var scenery_ready_frames: int = 0
var scenery_was_pending: bool = false
var run_metrics_last_usec: int = 0
var run_metrics_final_reported: bool = false
var diagnostics: PanelContainer
var display_settings: Node
var telemetry: Node
var diagnostics_elapsed: float = 0.0
var pending_population_scene: Dictionary = {}
var population_handoff_started_usec: int = 0
var population_request: String = ""
var workspace_probe_active: bool = false
var viewer_clock_id: String = Crypto.new().generate_random_bytes(16).hex_encode()
var phase_counter: int = 0
var phase_clock_synced: bool = false
var phase_id: String = "viewer-0"
var phase_started_usec: int = 0
var phase_signature: String = ""
var layout_last_size := Vector2.ZERO

func _ready() -> void:
	get_tree().auto_accept_quit = false
	startup_started_usec = Time.get_ticks_usec()
	previous_frame_usec = startup_started_usec
	run_metrics_last_usec = startup_started_usec
	loading_screen = preload("res://loading_screen.gd").new()
	add_child(loading_screen)
	loading_screen.close_requested.connect(_close_application)
	var arguments: PackedStringArray = OS.get_cmdline_user_args()
	if "--workspace-probe" in arguments: _set_probe_input_guard(true)
	display_settings = preload("res://display_settings.gd").new()
	add_child(display_settings)
	display_settings.initialize(arguments)
	display_settings.changed.connect(_display_changed)
	phase_started_usec = startup_started_usec
	var diagnostics_layer := CanvasLayer.new()
	diagnostics_layer.layer = 110
	add_child(diagnostics_layer)
	diagnostics = preload("res://diagnostics.gd").new()
	diagnostics_layer.add_child(diagnostics)
	diagnostics.action_requested.connect(_action)
	diagnostics.layout_changed.connect(_workspace_layout)
	diagnostics.set_open("--performance" in arguments)
	telemetry = preload("res://telemetry_client.gd").new()
	add_child(telemetry)
	telemetry.received.connect(diagnostics.receive_telemetry)
	telemetry.configure(int(_argument(arguments,"--telemetry-port","0")),_argument(arguments,"--telemetry-token",""))
	smoke = "--smoke-test" in arguments
	await _loading_stage("Opening San Francisco")
	startup_first_paint_ms = float(Time.get_ticks_usec()-startup_started_usec)/1000.0
	print("GODOT_APPLICATION_LOADING_VISIBLE " + JSON.stringify({"elapsed_ms":startup_first_paint_ms,"rendered":DisplayServer.get_name() != "headless"}))
	if "--startup-file" in arguments:
		arguments = await _await_launcher(_argument(arguments,"--startup-file",""))
		if startup_failed: return
	hud = preload("res://hud.gd").new()
	add_child(hud)
	hud.visible = false
	hud.action_requested.connect(_action)
	hud.mode_requested.connect(_set_mode)
	hud.resident_selected.connect(func(identifier: String) -> void: _select(identifier))
	hud.layout_changed.connect(_workspace_layout)
	_workspace_layout()
	if telemetry.port == 0: telemetry.configure(int(_argument(arguments,"--telemetry-port","0")),_argument(arguments,"--telemetry-token",""))
	smoke = "--smoke-test" in arguments
	host = _argument(arguments,"--host","127.0.0.1")
	port = int(_argument(arguments,"--port","0"))
	token = _argument(arguments,"--token","")
	initial_mode = _argument(arguments,"--mode","overhead")
	initial_location = _argument(arguments,"--location","city-hall")
	initial_place = _argument(arguments,"--place","")
	initial_lighting = _argument(arguments,"--lighting","cycle")
	screenshot_path = _argument(arguments,"--screenshot","")
	initial_replay_index = maxi(0,int(_argument(arguments,"--replay-index","0")))
	var cache_directory: String = _argument(arguments,"--render-cache","")
	var cache_enabled: bool = "--no-render-cache" not in arguments
	await _loading_stage("Loading City Hall", "Preparing buildings, landmarks, and the city view. Please wait.")
	var visual_path: String = "res://assets/visual.json"
	if not FileAccess.file_exists(visual_path):
		_fail("Missing viewer/assets/visual.json. Run the application launcher to stage assets.")
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(visual_path))
	if not parsed is Dictionary:
		_fail("The visual asset manifest is invalid.")
		return
	visual = parsed
	world = preload("res://world.gd").new()
	add_child(world)
	if not world.initialize(visual):
		_fail(str(world.last_error))
		return
	daylight.initialize(world.environment_resource,world.daylight_sun)
	daylight.set_enabled(initial_lighting != "fixed")
	hud.update_lighting(daylight.get_state())
	cameras = preload("res://cameras.gd").new()
	add_child(cameras)
	cameras.initialize(visual)
	cameras.set_mode(initial_mode)
	await _loading_stage("Loading the landscape", "Reading San Francisco's elevation and shoreline data.")
	terrain = preload("res://terrain.gd").new()
	add_child(terrain)
	terrain.configure_render_cache(cache_directory,cache_enabled)
	var terrain_path: String = _argument(arguments,"--terrain","")
	if not terrain_path.is_empty():
		if not terrain.initialize(terrain_path) and str(terrain.last_error).is_empty(): terrain.last_error = "Requested terrain grid was not found."
	cameras.terrain = terrain
	world.initialize_landmarks(terrain)
	hud.landmark_records = world.landmarks.records
	await _loading_stage("Loading city geography", "Opening sourced streets and buildings for your starting location.")
	geography = preload("res://geography.gd").new()
	geography.terrain = terrain
	geography.landmark_records = world.landmarks.replacements
	add_child(geography)
	geography.configure_render_cache(cache_directory,cache_enabled)
	cameras.geography = geography
	var geography_path: String = _argument(arguments,"--geography","res://assets/sf-geography.json")
	if geography.initialize(geography_path):
		cameras.configure_geography(geography.manifest.bounds)
		if terrain.available: terrain.set_land(geography.manifest.get("land",[]))
		if initial_location == "city": cameras.jump_to_city()
	elif "--geography" in arguments and str(geography.last_error).is_empty():
		geography.last_error = "Requested manifest was not found. The City Hall pilot still works."
	await _loading_stage("Preparing places and trees", "Loading neighborhood boundaries, destinations, and street trees.")
	hud.use_context = geography.use_context
	places.initialize(geography_path)
	places.add_landmarks(world.landmarks.records)
	place_outline = preload("res://place_outline.gd").new()
	place_outline.terrain = terrain
	add_child(place_outline)
	if not places.manifest.is_empty(): place_outline.initialize(geography_path,places.manifest)
	street_trees = preload("res://trees.gd").new()
	street_trees.terrain = terrain
	add_child(street_trees)
	street_trees.initialize(geography_path)
	street_trees.set_enabled(_argument(arguments,"--trees","on") != "off")
	hud.update_trees(street_trees.get_state())
	hud.place_search.configure(places)
	if "--use-overlay" in arguments: geography.set_use_overlay(true)
	geography.set_facades(_argument(arguments,"--facades","on") != "off")
	hud.update_geography(geography.get_state())
	await _loading_stage("Preparing residents", "Getting the map and resident displays ready.")
	crowd = preload("res://crowd.gd").new()
	add_child(crowd)
	crowd.initialize(visual)
	map_2d = preload("res://map_2d.gd").new()
	add_child(map_2d)
	map_2d.visible = false
	_set_mode(initial_mode)
	client = preload("res://snapshot_client.gd").new()
	add_child(client)
	client.scene_received.connect(_receive_scene)
	client.snapshot_received.connect(_receive_snapshot)
	client.status_changed.connect(_connection_status)
	client.acknowledged.connect(_acknowledged)
	client.command_rejected.connect(_command_rejected)
	startup_initialized = true
	await _loading_stage("Waiting for the simulation", "Preparing residents, homes, jobs, and daily commutes. Please wait.")
	var replay_path: String = _argument(arguments,"--replay","")
	if not replay_path.is_empty():
		_load_replay(replay_path)
	elif port > 0 and not token.is_empty():
		client.connect_worker(host,port,token)
	else:
		_fail("Start with the Python launcher, or provide --replay PATH. A live connection needs --port and --token.")
		return
	call_deferred("_automation")


func _loading_stage(label: String, detail: String = "Please wait while your city loads.") -> void:
	_set_loading_stage(label,detail)
	# Two process boundaries let text reach a rendered frame before imports.
	await get_tree().process_frame
	await get_tree().process_frame

func _set_loading_stage(label: String, detail: String = "Please wait while your city loads.") -> void:
	if startup_failed or startup_complete: return
	if label != startup_stage_name:
		var now: int = Time.get_ticks_usec()
		if not startup_stage_name.is_empty(): startup_stages.append({"stage":startup_stage_name,"duration_ms":float(now-startup_stage_started_usec)/1000.0})
		startup_stage_name = label
		startup_stage_started_usec = now
	loading_screen.set_stage(label,detail)

func _await_launcher(path: String) -> PackedStringArray:
	_set_loading_stage("Preparing your city", "Preparing local city data. The first launch can take longer. Please wait.")
	var deadline: int = Time.get_ticks_msec()+1800000
	while Time.get_ticks_msec() < deadline:
		if FileAccess.file_exists(path):
			var file: FileAccess = FileAccess.open(path,FileAccess.READ)
			if file == null or file.get_length() > 1048576:
				_fail("The launcher startup status could not be read.")
				return PackedStringArray()
			var parsed: Variant = JSON.parse_string(file.get_as_text())
			file.close()
			if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1:
				_fail("The launcher startup status is invalid.")
				return PackedStringArray()
			match str(parsed.get("status","")):
				"preparing": _set_loading_stage("Preparing your city",str(parsed.get("message","Preparing local city data. Please wait.")))
				"error":
					_fail(str(parsed.get("message","The launcher could not prepare this city.")))
					return PackedStringArray()
				"ready":
					var forwarded: Variant = parsed.get("arguments")
					if forwarded is Array:
						var result := PackedStringArray()
						for value: Variant in forwarded:
							if not value is String:
								_fail("The launcher startup arguments are invalid.")
								return PackedStringArray()
							result.append(value)
						return result
					_fail("The launcher did not provide startup arguments.")
					return PackedStringArray()
				_:
					_fail("The launcher startup status is not recognized.")
					return PackedStringArray()
		await get_tree().create_timer(0.1).timeout
	_fail("City preparation did not finish within 30 minutes. Check the launcher's terminal for details.")
	return PackedStringArray()

func _update_loading() -> void:
	if startup_complete or startup_failed or not ready_reported: return
	var pending_now: bool = _scenery_pending()
	var elapsed_since_snapshot: float = float(Time.get_ticks_usec()-startup_started_usec)/1000.0-startup_first_snapshot_ms
	if pending_now or elapsed_since_snapshot < 400.0:
		scenery_ready_frames = 0
		_set_loading_stage("Loading your starting view", "Residents are ready. Nearby streets, buildings, and scenery are loading.")
		return
	scenery_ready_frames += 1
	if scenery_ready_frames < 3: return
	startup_usable_ms = float(Time.get_ticks_usec()-startup_started_usec)/1000.0
	startup_stages.append({"stage":startup_stage_name,"duration_ms":float(Time.get_ticks_usec()-startup_stage_started_usec)/1000.0})
	startup_complete = true
	loading_screen.finish()
	hud.visible = true
	print("GODOT_APPLICATION_STARTUP_COMPLETE " + JSON.stringify(startup_profile()))
	_emit_run_metrics()

func _interval_summary(source: Array[float]) -> Dictionary:
	if source.is_empty(): return {"samples":0}
	var sorted: Array[float] = source.duplicate()
	sorted.sort()
	return {"samples":sorted.size(),"p50_ms":sorted[int((sorted.size()-1)*0.50)],"p95_ms":sorted[int((sorted.size()-1)*0.95)],"p99_ms":sorted[int((sorted.size()-1)*0.99)],"max_ms":sorted.back()}

func startup_profile() -> Dictionary:
	return {"complete":startup_complete,"failed":startup_failed,"stage":startup_stage_name,"first_paint_ms":startup_first_paint_ms,"first_snapshot_ms":startup_first_snapshot_ms,"usable_ms":startup_usable_ms,"stages":startup_stages.duplicate(true),"frames":_interval_summary(startup_frames),"total_frames":startup_total_frames,"worst_frame_ms":startup_worst_ms,"measurement":"viewer elapsed wall time; includes launcher preparation when started with a startup file"}

func streaming_profile() -> Dictionary:
	var result: Dictionary = _interval_summary(streaming_frames)
	result["total_frames"] = streaming_total_frames
	result["total_ms"] = streaming_total_ms
	result["worst_ms"] = streaming_worst_ms
	result["measurement"] = "wall intervals while scenery is pending, including the interval after each loading frame; recent samples are bounded, totals retain all spikes"
	return result

func run_metrics(final: bool = false) -> Dictionary:
	# Logs contain aggregate diagnostics only. In particular, do not serialize
	# displayed, scene_message, OS arguments, or the authentication token.
	# This also runs when loading is canceled before any world nodes exist.
	var window_end_usec: int = Time.get_ticks_usec()
	var performance: Dictionary = _interval_summary(frame_samples)
	var sampled_ms: float = 0.0
	for interval: float in frame_samples: sampled_ms += interval
	var phases: Dictionary = {}
	for label: String in phase_samples:
		var values: Array = phase_samples[label].duplicate()
		values.sort()
		if not values.is_empty(): phases[label] = {"p50":values[int((values.size()-1)*0.5)],"p95":values[int((values.size()-1)*0.95)]}
	performance["sampled_seconds"] = sampled_ms/1000.0
	performance["phase_id"] = phase_id
	performance["window_start_monotonic_seconds"] = _python_monotonic(phase_started_usec)
	performance["window_end_monotonic_seconds"] = _python_monotonic(window_end_usec)
	performance["measurement"] = "monotonic wall time between process callbacks; recent samples are bounded"
	performance["cpu_phases_ms"] = phases
	performance["decoder"] = client.decoder.stats() if is_instance_valid(client) and client.decoder != null else {}
	performance["streaming"] = streaming_profile()
	performance["scenery_cache"] = {"geography":geography.cache_stats() if is_instance_valid(geography) else {},"terrain":terrain.cache_stats() if is_instance_valid(terrain) else {}}
	var resident_view: Node = map_2d if map_active else crowd
	var resident_count: int = resident_view.ids.size() if is_instance_valid(resident_view) else displayed.get("residents",[]).size()
	var viewport: Viewport = get_viewport() if is_inside_tree() else null
	var simulation: Dictionary = {"ready":not displayed.is_empty(),"sequence":sequence,"tick":displayed.get("tick"),"simulation_time":displayed.get("simulation_time"),"clock_seconds":displayed.get("clock_seconds"),"resident_count":resident_count,"outdoor_count":resident_view.outdoor_count if is_instance_valid(resident_view) else null,"paused":displayed.get("paused"),"speed":displayed.get("speed")}
	var presentation: Dictionary = {"mode":"map" if map_active else (str(cameras.mode) if is_instance_valid(cameras) else initial_mode),"display_server":DisplayServer.get_name(),"rendering_method":RenderingServer.get_current_rendering_method(),"graphics_adapter":RenderingServer.get_video_adapter_name(),"rendering_3d":not viewport.disable_3d if viewport != null else null,"render_draw_calls":int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),"render_primitives":int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),"crowd_backend":str(resident_view.draw_backend) if is_instance_valid(resident_view) else "","lighting_mode":"cycle" if daylight.enabled else "fixed"}
	if display_settings != null: presentation.merge(display_settings.state())
	simulation["population"] = displayed.get("population",resident_count)
	simulation["roster_revision"] = displayed.get("roster_revision",scene_message.get("roster_revision",0))
	simulation["worker_metrics"] = displayed.get("worker_metrics",{})
	simulation["population_change"] = displayed.get("population_change",{})
	return {"viewer_clock_id":viewer_clock_id,"phase_id":phase_id,"window_start_local_usec":phase_started_usec,"window_end_local_usec":window_end_usec,"clock_uncertainty_seconds":telemetry.clock_uncertainty if telemetry != null and telemetry.clock_synced else null,"window_start_monotonic_seconds":_python_monotonic(phase_started_usec),"window_end_monotonic_seconds":_python_monotonic(window_end_usec),"schema_version":1,"final":final,"elapsed_ms":float(Time.get_ticks_usec()-startup_started_usec)/1000.0 if startup_started_usec > 0 else 0.0,"startup":startup_profile(),"performance":performance,"simulation":simulation,"presentation":presentation,"error":last_error}

func _maybe_emit_run_metrics(now_usec: int) -> void:
	if now_usec-run_metrics_last_usec >= RUN_METRICS_INTERVAL_USEC:
		_emit_run_metrics()

func _emit_run_metrics(final: bool = false) -> void:
	if run_metrics_final_reported: return
	run_metrics_last_usec = Time.get_ticks_usec()
	run_metrics_final_reported = final
	print("GODOT_APPLICATION_RUN_METRICS " + JSON.stringify(run_metrics(final)))

func _exit_tree() -> void:
	# Covers ordinary close, automation quit, and scene teardown. Close emits
	# before disconnecting; the flag prevents a second final record here.
	_emit_run_metrics(true)

func _argument(arguments: PackedStringArray, name_value: String, fallback: String) -> String:
	var index: int = arguments.find(name_value)
	return arguments[index + 1] if index >= 0 and index + 1 < arguments.size() else fallback

func _receive_scene(message: Dictionary) -> void:
	var same_world: bool = not str(message.get("world_identity","")).is_empty() and message.get("world_identity") == scene_message.get("world_identity")
	if str(message.get("reason","")) == "population_adjustment" and same_world and not displayed.is_empty():
		pending_population_scene = message
		population_handoff_started_usec = Time.get_ticks_usec()
		session_id = str(message.get("session_id",""))
		sequence = -1
		if diagnostics != null: diagnostics.set_population_status("Committed in simulation; receiving the updated population...",true)
		_emit_phase("population_commit","transition",message.get("population_change",{}))
		return
	var previous_scenario_id: String = str(scene_message.get("scenario",{}).get("id",""))
	scene_message = message
	var scenario: Dictionary = message.get("scenario",{})
	is_pilot = str(scenario.get("id","")) == "civic-center-walking-day-v1"
	world.set_pilot_visible(is_pilot)
	cameras.pilot_enabled = is_pilot
	if previous_scenario_id != str(scenario.get("id","")):
		cameras.configure_scenario_view(scenario.get("view",{}))
	if terrain != null: terrain.set_pilot_mode(is_pilot)
	if street_trees != null: street_trees.set_pilot_mode(is_pilot)
	if geography != null: geography.set_pilot_mode(is_pilot)
	if geography != null: geography.landmark_error = world.landmarks.last_error
	if crowd != null:
		crowd.configure_bounds(visual.bounds if is_pilot or geography == null or not geography.available else geography.manifest.bounds)
	hud.configure_scenario(scenario)
	session_id = str(message.get("session_id",""))
	sequence = -1
	area_activity.clear()
	area_activity_state = {}
	hud.place_search.update_activity({})
	presenter.clear()
	displayed = {}
	map_configured = false
	last_map_error = ""
	map_2d.clear()
	if map_active: _configure_map()
	# A session changes the domain state, never the user's camera or selected ID.
	if crowd != null: crowd.apply_snapshot({"residents":[]},cameras.camera,selected_id)
	cameras.follow_available = false
	if not initial_place_applied and not initial_place.is_empty():
		initial_place_applied = true
		_jump_place(initial_place,initial_mode)
	_configure_area_activity()

func _receive_snapshot(message: Dictionary) -> void:
	var validation_started: int = Time.get_ticks_usec()
	if str(message.get("session_id","")) != session_id or int(message.get("sequence",-1)) <= sequence:
		return
	var identities: Dictionary = {}
	for person: Variant in message.get("residents",[]):
		if not person is Dictionary or not person.get("position") is Array or person.position.size() != 3 or str(person.get("id","")).is_empty():
			_fail("Simulation sent an invalid resident record.")
			return
		var identity: String = str(person.id)
		if identities.has(identity) or not Coordinates.to_world(person.position).is_finite():
			_fail("Simulation sent duplicate identities or invalid coordinates.")
			return
		identities[identity] = true
	var population_handoff: bool = not pending_population_scene.is_empty()
	var removed_selection: bool = population_handoff and _resident_view().records.has(selected_id) and not identities.has(selected_id)
	var removed_follow: bool = population_handoff and not follow_id.is_empty() and not identities.has(follow_id)
	var population_change: Dictionary = {}
	if population_handoff:
		scene_message = pending_population_scene
		pending_population_scene = {}
		population_change = scene_message.get("population_change",{})
		hud.configure_scenario(scene_message.get("scenario",{}))
		area_activity.clear()
		area_activity_state = {}
		hud.place_search.update_activity({})
		_configure_area_activity()
		if map_2d != null: map_2d._scenario = scene_message.get("scenario",{})
		if removed_selection:
			selected_id = ""
			selected_label = "Selected citizen was removed by the population experiment."
		if removed_follow:
			follow_id = ""
			follow_camera_id = ""
			if cameras.mode == "follow": cameras.detach_follow()
	last_validation_ms = float(Time.get_ticks_usec()-validation_started)/1000.0
	sequence = int(message.sequence)
	var prepare_started: int = Time.get_ticks_usec()
	presenter.receive(message)
	last_prepare_ms = float(Time.get_ticks_usec()-prepare_started)/1000.0
	# Establish membership immediately after a new session. Subsequent snapshots
	# render once in the regular frame pass, avoiding a second full crowd upload.
	var resident_view: Node = _resident_view()
	if resident_view.ids.is_empty() or population_handoff:
		_render_snapshot()
		if not map_active: daylight.update_clock(float(displayed.get("clock_seconds",28790.0)),true)
	if not population_handoff and (cameras == null or not cameras.follow_detached) and not resident_view.records.has(follow_id) and not resident_view.ids.is_empty():
		follow_id = resident_view.ids[0]
		# A new follow view starts with an outdoor resident when one exists.
		# Once selected, their identity persists through every indoor arrival.
		if selected_id.is_empty() and initial_mode == "follow":
			for identity: String in resident_view.ids:
				if bool(resident_view.records[identity].get("visible",false)):
					follow_id = identity
					break
		if selected_id.is_empty() or selected_id.begins_with("resident-") or selected_id.begins_with("sf-resident-"): _select(follow_id)
	if population_handoff:
		if diagnostics != null:
			diagnostics.set_population_status("Applied %d citizens at tick %d; current day preserved." % [identities.size(),int(message.get("tick",0))],false)
			diagnostics.target_population.value = identities.size()
		_emit_phase("population_handoff","settled",population_change)
		print("GODOT_APPLICATION_POPULATION_HANDOFF "+JSON.stringify({"population_change":population_change,"roster_revision":message.get("roster_revision",0),"count":identities.size(),"tick":message.get("tick",0),"handoff_ms":float(Time.get_ticks_usec()-population_handoff_started_usec)/1000.0,"received_at_unix":Time.get_unix_time_from_system()}))
	if not ready_reported:
		startup_first_snapshot_ms = float(Time.get_ticks_usec()-startup_started_usec)/1000.0
		ready_reported = true
		print("GODOT_APPLICATION_READY " + JSON.stringify(_report_state()))

func _acknowledged(message: Dictionary) -> void:
	if str(message.get("action","")) == "set_population" or str(message.get("request_id","")) == population_request:
		if str(message.get("type","")) == "error":
			diagnostics.set_population_status(str(message.get("message","Population change rejected.")),false)
		elif bool(message.get("noop",false)):
			diagnostics.set_population_status("Population already matches the target.",false)
	ack_results[str(message.get("request_id",""))] = message
	while ack_results.size() > 512: ack_results.erase(ack_results.keys()[0])
	if str(message.get("type","")) == "ack":
		match str(message.get("action","")):
			"save": hud.set_status("Day saved to the local quick slot.")
			"load": hud.set_status("Saved day restored. The camera and selected resident stay yours.")

func _command_rejected(message: Dictionary) -> void:
	# An acknowledged limit/validation rejection leaves the existing day usable.
	# Record the event once; recurring runtime metrics retain only actual failures.
	var marker: Dictionary = {"schema_version":1,"request_id":str(message.get("request_id","")).left(128),"action":str(message.get("action","")).left(128),"code":str(message.get("code","")).left(128),"message":str(message.get("message","Request rejected.")).left(2048),"session_id":str(message.get("session_id",session_id)).left(128),"at_unix":Time.get_unix_time_from_system()}
	print("GODOT_APPLICATION_COMMAND_REJECTED "+JSON.stringify(marker))

func _connection_status(message: String, is_error: bool) -> void:
	hud.set_status(message,is_error)
	if is_error and diagnostics != null and diagnostics.pending: diagnostics.set_population_status(message,false)
	if is_error:
		if not startup_complete:
			_fail(message)
			return
		last_error = message
		# Complete the final authoritative state once; never extrapolate after loss.
		presenter.atomic = true

func _load_replay(path: String) -> void:
	if not FileAccess.file_exists(path):
		_fail("Replay file not found: " + path)
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or not parsed.get("scene") is Dictionary or not parsed.get("snapshots") is Array or parsed.snapshots.is_empty():
		_fail("Replay requires a scene message and nonempty snapshots array.")
		return
	replay = parsed
	_seek_replay(initial_replay_index)
	hud.set_status("Recorded simulation replay Â· each frame is an authoritative state")

func _seek_replay(index: int) -> void:
	replay_index = clampi(index,0,replay.snapshots.size()-1)
	replay_elapsed = 0.0
	replay_paused = bool(replay.snapshots[replay_index].get("paused",false))
	var target_scene: Dictionary = replay.scene.duplicate(false)
	target_scene["session_id"] = replay.snapshots[replay_index].session_id
	_receive_scene(target_scene)
	_receive_snapshot(replay.snapshots[replay_index])

func _process(delta: float) -> void:
	# Keep the interval's original start: a phase can change during diagnostics
	# or later while presenting a population handoff in this same callback.
	var interval_start_usec: int = previous_frame_usec
	_update_diagnostics(delta)
	var now_usec: int = Time.get_ticks_usec()
	var wall_frame_ms: float = float(now_usec-previous_frame_usec)/1000.0 if previous_frame_usec > 0 else delta*1000.0
	previous_frame_usec = now_usec
	_maybe_emit_run_metrics(now_usec)
	if not startup_complete and not startup_failed:
		startup_frames.append(wall_frame_ms)
		startup_total_frames += 1
		startup_worst_ms = maxf(startup_worst_ms,wall_frame_ms)
		if startup_frames.size() > PROFILE_SAMPLE_LIMIT: startup_frames.pop_front()
	# The first snapshot establishes which city or pilot owns these scenery tiles.
	# The client processes independently while this main frame loop is waiting.
	if not startup_initialized or startup_failed or not ready_reported: return
	frame_ms = lerpf(frame_ms,wall_frame_ms,0.08)
	if startup_complete and not replay.is_empty() and not replay_paused and not automation_running:
		replay_elapsed += delta * replay_speed
		if replay_elapsed >= 1.5:
			replay_elapsed = 0.0
			_advance_replay()
	_render_snapshot()
	var area_started: int = Time.get_ticks_usec()
	area_activity_elapsed += delta
	if area_activity.available and area_activity_elapsed >= 1.0 and not displayed.is_empty():
		area_activity_elapsed = 0.0
		if int(area_activity_state.get("tick",-1)) != int(displayed.get("tick",0)):
			area_activity_state = area_activity.sample(displayed)
			hud.place_search.update_activity(area_activity_state,area_activity.last_error)
	var area_ms: float = float(Time.get_ticks_usec()-area_started)/1000.0
	var view_started: int = Time.get_ticks_usec()
	if not map_active and not displayed.is_empty(): daylight.update_clock(float(displayed.get("clock_seconds",28790.0)))
	view_elapsed += delta
	cameras.allow_walk_input = startup_complete and not workspace_probe_active and camera_input_allowed(get_viewport().gui_get_focus_owner(),get_window().has_focus())
	if not map_active:
		_update_follow()
	_update_keyboard_navigation(delta)
	if not map_active:
		cameras.update_camera(delta)
	var trees_ms: float = 0.0
	if not map_active:
		var focus: Vector3 = cameras.orbit_target if cameras.mode == "overhead" else cameras.camera.position
		var zoom: float = cameras.orbit_distance if cameras.mode == "overhead" else 100.0
		if geography != null and geography.available: geography.update_view(cameras.camera,focus,zoom,delta)
		var trees_started: int = Time.get_ticks_usec()
		if street_trees != null: street_trees.update_view(focus,zoom,delta)
		trees_ms = float(Time.get_ticks_usec()-trees_started)/1000.0
		if terrain != null and terrain.available and (view_elapsed >= 0.2 or not terrain.pending.is_empty() or not terrain.detailed_pending.is_empty()):
			terrain.update_view(focus,zoom)
			view_elapsed = 0.0
	if not map_active and place_outline != null and hud_elapsed+delta >= 0.2: place_outline.update_view(cameras.camera)
	var view_ms: float = float(Time.get_ticks_usec()-view_started)/1000.0
	var hud_started: int = Time.get_ticks_usec()
	hud_elapsed += delta
	# Activity/occupancy changes still refresh immediately with their snapshot.
	# Clock metrics and unchanged labels do not need repeated layout every frame.
	if hud_elapsed >= 0.2 or sequence != last_hud_sequence or session_id != last_hud_session or selected_id != last_hud_selected or _view_mode() != last_hud_mode:
		if geography != null: hud.update_geography(geography.get_state())
		hud.update_lighting(daylight.get_state())
		if street_trees != null: hud.update_trees(street_trees.get_state())
		hud.set_map_mode(map_active)
		if map_active and not map_2d.last_error.is_empty() and map_2d.last_error != last_map_error:
			last_map_error = map_2d.last_error
			hud.set_status("2D map: " + last_map_error,true)
		if not displayed.is_empty(): hud.update_display(displayed,_resident_view(),_view_mode(),selected_id,selected_label,frame_ms)
		hud_elapsed = 0.0
		last_hud_sequence = sequence
		last_hud_session = session_id
		last_hud_selected = selected_id
		last_hud_mode = _view_mode()
	var hud_ms: float = float(Time.get_ticks_usec()-hud_started)/1000.0
	var scenery_pending: bool = _scenery_pending()
	if scenery_pending or scenery_was_pending:
		streaming_frames.append(wall_frame_ms)
		if streaming_frames.size() > PROFILE_SAMPLE_LIMIT: streaming_frames.pop_front()
		streaming_total_frames += 1
		streaming_total_ms += wall_frame_ms
		streaming_worst_ms = maxf(streaming_worst_ms,wall_frame_ms)
	scenery_was_pending = scenery_pending
	_update_loading()
	if scenery_pending:
		frame_samples.clear()
		for samples: Array in phase_samples.values(): samples.clear()
	elif interval_start_usec > 0 and interval_start_usec >= phase_started_usec:
		frame_samples.append(wall_frame_ms)
		if frame_samples.size() > PROFILE_SAMPLE_LIMIT: frame_samples.pop_front()
		_record_phase("presentation",last_presentation_ms)
		_record_phase("crowd",last_crowd_ms)
		_record_phase("view",view_ms)
		_record_phase("trees",trees_ms)
		_record_phase("area",area_ms)
		_record_phase("hud",hud_ms)
		_record_phase("transport",float(client.last_process_ms) if client != null else 0.0)
		_record_phase("parse_and_delivery",float(client.last_parse_ms) if client != null else 0.0)
		_record_phase("json_decode",float(client.last_json_decode_ms) if client != null else 0.0)
		_record_phase("snapshot_expand",float(client.last_expand_ms) if client != null else 0.0)
		_record_phase("snapshot_delivery",float(client.last_delivery_ms) if client != null else 0.0)
		_record_phase("resident_validation",last_validation_ms if client != null and client.last_delivery_ms > 0.0 else 0.0)
		_record_phase("presentation_prepare",last_prepare_ms if client != null and client.last_delivery_ms > 0.0 else 0.0)

func _record_phase(label: String, value: float) -> void:
	phase_samples[label].append(value)
	if phase_samples[label].size() > PROFILE_SAMPLE_LIMIT: phase_samples[label].pop_front()

func _scenery_pending() -> bool:
	if map_active: return map_2d != null and int(map_2d.get_state().get("pending_tiles",0)) > 0
	return (street_trees != null and street_trees.available and street_trees.enabled and not street_trees.pending.is_empty()) or (terrain != null and terrain.available and (not terrain.pending.is_empty() or not terrain.detailed_pending.is_empty())) or (geography != null and geography.available and (not geography.requests.is_empty() or (geography.visual_context != null and geography.visual_context.available and not geography.visual_context.pending.is_empty())))

func scenery_cache_profile() -> Dictionary:
	return {"geography":geography.cache_stats() if geography != null else {},"terrain":terrain.cache_stats() if terrain != null else {}}

func frame_profile() -> Dictionary:
	if frame_samples.is_empty(): return {"samples":0,"loading":_scenery_pending(),"startup":startup_profile(),"streaming":streaming_profile(),"scenery_cache":scenery_cache_profile()}
	var sorted: Array[float] = frame_samples.duplicate()
	sorted.sort()
	var phases: Dictionary = {}
	var sampled_ms: float = 0.0
	for interval: float in frame_samples: sampled_ms += interval
	var decoder_state: Dictionary = client.decoder.stats() if client != null and client.decoder != null else {}
	for label: String in phase_samples:
		var values: Array = phase_samples[label].duplicate()
		values.sort()
		if not values.is_empty(): phases[label] = {"p50":values[int((values.size()-1)*0.5)],"p95":values[int((values.size()-1)*0.95)]}
	return {"startup":startup_profile(),"streaming":streaming_profile(),"scenery_cache":scenery_cache_profile(),"samples":sorted.size(),"sampled_seconds":sampled_ms/1000.0,"loading":_scenery_pending(),"measurement":"monotonic wall time between process callbacks","decode_measurement":"JSON and expansion measure completed background work; other phases measure main-thread work","decoder":decoder_state,"p50_ms":sorted[int((sorted.size()-1)*0.50)],"p95_ms":sorted[int((sorted.size()-1)*0.95)],"p99_ms":sorted[int((sorted.size()-1)*0.99)],"cpu_phases_ms":phases,"mode":_view_mode(),"rendering_3d":not get_viewport().disable_3d,"render_draw_calls":int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),"render_primitives":int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),"map":map_2d.get_state() if map_active else {},"lighting_mode":daylight.get_state().mode,"facades_enabled":geography.facades_enabled,"trees":street_trees.get_state() if street_trees != null else {},"crowd_backend":_resident_view().draw_backend,"resident_count":_resident_view().ids.size(),"outdoor_count":_resident_view().outdoor_count,"paused":bool(displayed.get("paused",false)),"speed":float(displayed.get("speed",1.0))}

func _render_snapshot() -> void:
	if not pending_population_scene.is_empty(): return
	var started: int = Time.get_ticks_usec()
	displayed = presenter.sample()
	if not displayed.is_empty() and not replay.is_empty():
		displayed = displayed.duplicate(false)
		displayed["paused"] = replay_paused
		displayed["speed"] = replay_speed
	last_presentation_ms = float(Time.get_ticks_usec()-started)/1000.0
	started = Time.get_ticks_usec()
	if not displayed.is_empty():
		if map_active: map_2d.apply_snapshot(displayed,selected_id)
		else: crowd.apply_snapshot(displayed,cameras.camera,selected_id)
	last_crowd_ms = float(Time.get_ticks_usec()-started)/1000.0

func _advance_replay() -> void:
	if replay_index + 1 >= replay.snapshots.size():
		replay_paused = true
		hud.set_status("Replay finished Â· Reset day to inspect it again")
		return
	replay_index += 1
	var next: Dictionary = replay.snapshots[replay_index]
	if str(next.get("session_id","")) != session_id:
		var next_scene: Dictionary = replay.scene.duplicate(true)
		next_scene["session_id"] = next.session_id
		_receive_scene(next_scene)
	_receive_snapshot(next)

func _action(action: String, value: Variant = null) -> void:
	match action:
		"performance":
			if diagnostics != null: diagnostics.set_open(not diagnostics.visible)
			return
		"fullscreen":
			if display_settings != null: display_settings.toggle_fullscreen()
			return
		"window_mode":
			if display_settings != null: display_settings.set_mode(str(value))
			return
		"ui_scale":
			if display_settings != null: display_settings.set_scale(float(value))
			return
		"open_run_log":
			var path: String = str(diagnostics.feed_status.get("report_path","")) if diagnostics != null else ""
			if path.is_absolute_path() and path.get_extension().to_lower() == "json" and FileAccess.file_exists(path): OS.shell_open(path)
			return
		"comparison":
			var point: Dictionary = run_metrics()
			point["context"] = _phase_context()
			point["phase_id"] = phase_id
			point["boundary_at_unix"] = Time.get_unix_time_from_system()
			print("GODOT_APPLICATION_COMPARISON_POINT "+JSON.stringify(point))
			return
		"toggle_pause":
			_action("pause",not bool(displayed.get("paused",false)))
			return
		"toggle_map":
			if not startup_initialized or startup_failed: return
			_set_mode("overhead" if map_active else "map")
			return
		"set_population":
			if not startup_complete or client == null or not replay.is_empty() or not bool(scene_message.get("capabilities",{}).get("set_population",false)):
				if diagnostics != null: diagnostics.set_population_status("Live population changes are unavailable in this connection.",false)
				return
			if diagnostics.pending: return
			var target: int = int(value)
			var limit: int = int(scene_message.get("capabilities",{}).get("population_max",5000))
			if target < 1 or target > limit or float(value) != float(target):
				diagnostics.set_population_status("Enter a whole population between 1 and %d." % limit,false)
				return
			var revision: int = int(displayed.get("roster_revision",scene_message.get("roster_revision",0)))
			population_request = client.command("set_population",target,revision)
			diagnostics.set_population_status("Requested %d citizens; preparing while this day continues..." % target,not population_request.is_empty())
			print("GODOT_APPLICATION_POPULATION_REQUEST "+JSON.stringify({"request_id":population_request,"requested_count":target,"roster_revision":revision,"at_unix":Time.get_unix_time_from_system()}))
			return
	if not startup_initialized or startup_failed: return
	if map_active and action in ["trees","facades","lighting","use_overlay"]: return
	if action == "map_center_selected":
		if map_active: map_2d.frame_selected()
		return
	if action == "trees":
		street_trees.set_enabled(bool(value))
		hud.update_trees(street_trees.get_state())
		return
	if action == "facades":
		geography.set_facades(bool(value))
		hud.update_geography(geography.get_state())
		return
	if action == "lighting":
		daylight.set_enabled(bool(value))
		hud.update_lighting(daylight.get_state())
		return
	if action == "place":
		_jump_place(str(value.get("id","")),str(value.get("mode","overhead")))
		return
	if action == "use_overlay":
		geography.set_use_overlay(bool(value))
		hud.update_geography(geography.get_state())
		return
	if action == "city_hall":
		_clear_place()
		if map_active: map_2d.jump_to(Vector2.ZERO,900.0)
		else: cameras.jump_to_city_hall()
		return
	if action == "city_overview":
		_clear_place()
		if map_active: map_2d.frame_bounds(geography.manifest.bounds if geography.available and not is_pilot else visual.bounds)
		else: cameras.jump_to_city()
		return
	if action == "reconnect":
		if replay.is_empty(): client.connect_worker(host,port,token)
		return
	if not replay.is_empty():
		match action:
			"pause": replay_paused = bool(value)
			"speed": replay_speed = float(value)
			"reset":
				_seek_replay(0)
				replay_paused = false
			"next_event":
				replay_paused = true
				_advance_replay()
			_:
				hud.set_status("Population changes and saving require the live simulation.",true)
		return
	client.command(action,value)

func _jump_place(query: String, requested_mode: String = "overhead") -> bool:
	var record: Dictionary = places.resolve(query)
	if record.is_empty():
		_clear_place()
		hud.set_status(places.last_error,true)
		return false
	if map_active and requested_mode != "walk":
		_clear_place()
		if record.has("bounds"): map_2d.frame_bounds(record.bounds)
		else: map_2d.jump_to(Vector2(float(record.target[0]),float(record.target[1])),maxf(500.0,float(record.get("view_distance_m",500.0))))
	elif not cameras.jump_to_place(record,requested_mode):
		hud.set_status("This place does not have terrain coverage for its view and nearby street.",true)
		return false
	elif map_active:
		_set_mode("walk")
	hud.place_search.show_place(record)
	if place_outline != null and not map_active:
		place_outline.show_place(record)
		place_outline.update_view(cameras.camera)
		if not place_outline.last_error.is_empty(): hud.set_status(place_outline.last_error,true)
	_configure_area_activity()
	return true

func _configure_area_activity() -> void:
	var identity: String = place_outline.selected_id if place_outline != null else ""
	if identity.is_empty() or session_id.is_empty() or not place_outline.areas.has(identity):
		area_activity.clear()
		area_activity_state = {}
		hud.place_search.update_activity({})
		return
	if area_activity.available and area_activity.selected_id == identity and area_activity.session_id == session_id: return
	area_activity_state = {}
	area_activity_elapsed = 1.0
	area_activity.configure(identity,place_outline.areas[identity],scene_message.scenario,session_id)
	hud.place_search.update_activity({},area_activity.last_error)

func _clear_place() -> void:
	if place_outline != null: place_outline.clear_selection()
	hud.place_search.clear_place()
	area_activity.clear()
	area_activity_state = {}

func _set_mode(next_mode: String) -> void:
	if cameras == null or map_2d == null or next_mode not in ["map","overhead","walk","follow"]: return
	dragging = false
	var was_map: bool = map_active
	map_active = next_mode == "map"
	if was_map != map_active: _clear_place()
	get_viewport().disable_3d = map_active
	map_2d.visible = map_active
	hud.set_map_mode(map_active)
	frame_samples.clear()
	for samples: Array in phase_samples.values(): samples.clear()
	if map_active:
		if not scene_message.is_empty(): _configure_map()
		if not displayed.is_empty(): map_2d.apply_snapshot(displayed,selected_id)
		return
	# Upload the current state before restoring 3D follow or picking.
	if was_map and not displayed.is_empty(): crowd.apply_snapshot(displayed,cameras.camera,selected_id)
	if next_mode == "follow":
		if crowd.records.has(selected_id): follow_id = selected_id
		elif not crowd.ids.is_empty(): follow_id = crowd.ids[0]
		if not follow_id.is_empty(): _select(follow_id)
	_update_follow()
	cameras.set_mode(next_mode)
	if was_map and not displayed.is_empty(): daylight.update_clock(float(displayed.get("clock_seconds",28790.0)),true)

func _view_mode() -> String:
	return "map" if map_active else cameras.mode

func _set_probe_input_guard(enabled: bool) -> void:
	# Visible automated trials must not consume typing or clicks meant for the
	# desktop. Programmatic actions and OS window-close notifications still work.
	workspace_probe_active = enabled
	get_viewport().gui_disable_input = enabled
	if enabled and cameras != null: cameras.allow_walk_input = false

static func camera_input_allowed(focus: Control, window_focused: bool) -> bool:
	return window_focused and not (focus is LineEdit or focus is TextEdit or focus is SpinBox or focus is OptionButton)

func _update_keyboard_navigation(delta: float) -> void:
	if workspace_probe_active or not cameras.allow_walk_input: return
	var direction := Vector2(
		float(Input.is_physical_key_pressed(KEY_D))-float(Input.is_physical_key_pressed(KEY_A)),
		float(Input.is_physical_key_pressed(KEY_W))-float(Input.is_physical_key_pressed(KEY_S)))
	var turn: float = float(Input.is_physical_key_pressed(KEY_E))-float(Input.is_physical_key_pressed(KEY_Q))
	if direction.is_zero_approx() and turn == 0.0: return
	var fast: bool = Input.is_physical_key_pressed(KEY_SHIFT)
	if map_active: map_2d.keyboard_navigate(direction,turn,delta,fast)
	else: cameras.keyboard_navigate(direction,turn,delta,fast)

func _resident_view() -> Node:
	return map_2d if map_active else crowd

func _configure_map() -> void:
	if map_configured or scene_message.is_empty(): return
	var manifest: Dictionary = geography.manifest.duplicate(false) if geography.available and not is_pilot else {}
	manifest["_base_path"] = geography.manifest_directory
	var map_scenario: Dictionary = scene_message.scenario
	if is_pilot:
		# The authored pilot has display bounds, not observed geographic footprints.
		# Enrich only this view's shallow copies; never alter domain metadata.
		map_scenario = map_scenario.duplicate(false)
		var buildings: Array = []
		for building: Dictionary in map_scenario.get("buildings",[]):
			var copy: Dictionary = building.duplicate(false)
			for box: Dictionary in visual.get("collision_boxes",[]):
				if str(box.id) != str(building.id): continue
				copy["footprint"] = [[box.min[0],box.min[1]],[box.max[0],box.min[1]],[box.max[0],box.max[1]],[box.min[0],box.max[1]]]
				copy["centroid"] = [(float(box.min[0])+float(box.max[0]))*0.5,(float(box.min[1])+float(box.max[1]))*0.5]
				break
			buildings.append(copy)
		map_scenario["buildings"] = buildings
	map_2d.configure(map_scenario,manifest)
	map_configured = true
	if not map_has_view:
		map_has_view = true
		if initial_location == "city" and geography.available and not is_pilot: map_2d.frame_bounds(geography.manifest.bounds)
		elif cameras.mode == "follow" and crowd.records.has(follow_id):
			var point: Array = crowd.records[follow_id].position
			map_2d.jump_to(Vector2(float(point[0]),float(point[1])),900.0)
		else:
			var focus: Vector3 = cameras.walk_position if cameras.mode == "walk" else cameras.orbit_target
			map_2d.jump_to(Vector2(focus.x,-focus.z),clampf(cameras.orbit_distance*2.0,700.0,20000.0))

func _update_follow() -> void:
	if follow_camera_id != follow_id:
		follow_camera_id = follow_id
		cameras.follow_pan_offset = Vector3.ZERO
	cameras.follow_available = crowd.display_transforms.has(follow_id)
	if cameras.follow_available:
		var transform_value: Transform3D = crowd.display_transforms[follow_id]
		cameras.follow_position = transform_value.origin
		cameras.follow_heading = float(crowd.records[follow_id].get("heading",0.0))
		cameras.follow_indoor = not bool(crowd.records[follow_id].get("visible",false))
		if cameras.follow_indoor:
			var resident: Dictionary = crowd.records[follow_id]
			var building_value: Variant = resident.get("building_id")
			var building_id: String = str(building_value) if building_value != null else str(resident.get("work_id" if str(resident.get("activity","")) == "at_work" else "home_id",""))
			var key: String = session_id+":"+follow_id+":"+building_id
			if key != follow_metadata_key:
				follow_metadata_key = key
				cameras.follow_building_height = 0.0
				for building: Dictionary in displayed.get("buildings",[]):
					if str(building.id) == building_id:
						cameras.follow_building_height = float(building.get("height_m",0.0))
						break
		else:
			follow_metadata_key = ""
			cameras.follow_building_height = 0.0

func _select(identifier: String, label_value: String = "") -> void:
	var source_id: String = identifier.trim_prefix("geography:")
	if world.landmarks != null and world.landmarks.aliases.has(source_id): identifier = str(world.landmarks.aliases[source_id])
	world.highlight(selected_id,identifier)
	selected_id = identifier
	selected_label = label_value if not label_value.is_empty() else identifier
	if world.landmarks != null and world.landmarks.records.has(identifier):
		var landmark: Dictionary = world.landmarks.records[identifier]
		selected_label = "%s\nSource ID: %s\nExterior height: %.1f m\n\n%s\n\nNo modeled residents are assigned here. Real-world occupancy is not modeled." % [landmark.get("label",identifier),identifier,float(landmark.get("height_m",0.0)),landmark.get("source_note","")]
	var resident_view: Node = _resident_view()
	if resident_view.records.has(identifier):
		selected_label = str(resident_view.records[identifier].get("label",identifier))
		follow_id = identifier
	if map_active and not displayed.is_empty(): map_2d.apply_snapshot(displayed,selected_id)

func _select_at(screen_position: Vector2) -> void:
	if map_active:
		var identifier: String = map_2d.pick(screen_position)
		_select(identifier)
		if not identifier.is_empty(): hud.set_inspector_collapsed(false)
		return
	var camera: Camera3D = cameras.camera
	var start: Vector3 = camera.project_ray_origin(screen_position)
	var direction: Vector3 = camera.project_ray_normal(screen_position)
	var query := PhysicsRayQueryParameters3D.create(start,start + direction * camera.far,1)
	var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(query)
	var identifier: String = ""
	var label_value: String = "Choose a person or click a building."
	var maximum: float = camera.far
	if not hit.is_empty():
		identifier = str(hit.collider.get_meta("selection_id",""))
		label_value = str(hit.collider.get_meta("selection_label","Building"))
		var note: String = str(hit.collider.get_meta("selection_note",""))
		if not note.is_empty(): label_value += "\n\n" + note
		maximum = start.distance_to(hit.position)
	if geography != null and geography.available:
		var mapped: Dictionary = geography.pick(start,direction,maximum)
		if not mapped.is_empty():
			maximum = float(mapped.distance)
			identifier = str(mapped.id)
			if world.landmarks != null and world.landmarks.records.has(identifier.trim_prefix("geography:")): identifier = identifier.trim_prefix("geography:")
			label_value = "%s\nSource ID: %s\nHeight: %.1f m\nHeight source: %s\n\nGeographic context. This building's occupancy is not available in the inspector." % [mapped.label,mapped.source_id,float(mapped.height_m),mapped.height_source]
			for building: Dictionary in displayed.get("buildings",[]):
				if str(building.id) == identifier.trim_prefix("geography:"):
					identifier = str(building.id)
					break
	var resident: String = crowd.pick(start,direction,maximum)
	if not resident.is_empty(): identifier = resident
	_select(identifier,label_value)
	if not identifier.is_empty(): hud.set_inspector_collapsed(false)

func _unhandled_input(event: InputEvent) -> void:
	if workspace_probe_active: return
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_F11:
			_action("fullscreen")
			get_viewport().set_input_as_handled()
			return
		if event.physical_keycode == KEY_F3:
			_action("performance")
			get_viewport().set_input_as_handled()
			return
	if not startup_complete or startup_failed or cameras == null: return
	if event is InputEventKey and event.pressed and not event.echo:
		if not camera_input_allowed(get_viewport().gui_get_focus_owner(),get_window().has_focus()): return
		match event.physical_keycode:
			KEY_1: _set_mode("overhead")
			KEY_2: _set_mode("walk")
			KEY_3: _set_mode("follow")
			KEY_4: _set_mode("map")
			KEY_SPACE: _action("pause",not bool(displayed.get("paused",false)))
			KEY_N: _action("next_event")
			KEY_R: _action("reset")
			KEY_F5: _action("save","quick")
			KEY_F9: _action("load","quick")
			KEY_G: _action("city_overview")
			KEY_H: _action("city_hall")
			KEY_U: _action("use_overlay",not geography.use_context.enabled)
			KEY_TAB: hud.toggle_panels()
			KEY_T:
				var speeds: Array = [1,4,60,600]
				_action("speed",speeds[(speeds.find(int(displayed.get("speed",1))) + 1) % speeds.size()])
			KEY_ESCAPE: dragging = false
	if event is InputEventMouseButton:
		if event.pressed and hud != null and hud.content_rect().has_area() and not hud.content_rect().has_point(event.position): return
		if event.button_index in [MOUSE_BUTTON_LEFT,MOUSE_BUTTON_RIGHT,MOUSE_BUTTON_MIDDLE]:
			if event.pressed:
				var focused_control: Control = get_viewport().gui_get_focus_owner()
				if focused_control != null: focused_control.release_focus()
				dragging = true
				drag_distance = 0.0
				pan_drag = map_active or (cameras.mode == "overhead" and (event.button_index == MOUSE_BUTTON_MIDDLE or event.shift_pressed))
			else:
				dragging = false
				if event.button_index == MOUSE_BUTTON_LEFT and drag_distance < 5.0: _select_at(event.position)
		if event.pressed:
			if event.button_index in [MOUSE_BUTTON_WHEEL_UP,MOUSE_BUTTON_WHEEL_DOWN]:
				var factor: float = 0.9 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1.1
				if map_active: map_2d.zoom_at(1.0/factor,event.position)
				else: cameras.zoom(factor)
	if event is InputEventMouseMotion and dragging:
		drag_distance += event.relative.length()
		if map_active: map_2d.pan_pixels(event.relative)
		elif pan_drag: cameras.pan(event.relative)
		else: cameras.drag(event.relative)

func get_application_state() -> Dictionary:
	var positions: Dictionary = {}
	var resident_view: Node = _resident_view()
	for identifier: String in resident_view.ids:
		positions[identifier] = Coordinates.to_domain(resident_view.display_transforms[identifier].origin)
	return {"ready":not displayed.is_empty(),"session_id":session_id,"sequence":sequence,"tick":int(displayed.get("tick",0)),"simulation_time":float(displayed.get("simulation_time",0.0)),"paused":bool(displayed.get("paused",false)),"speed":displayed.get("speed",1),"resident_count":resident_view.ids.size(),"outdoor_count":resident_view.outdoor_count,"visible_count":resident_view.visible_count,"animated_count":resident_view.animated_count,"asset_loaded":world.asset_loaded,"asset_mesh_count":world.asset_mesh_count,"crowd_batches":0 if map_active else crowd.batches.size(),"rendering_3d":not get_viewport().disable_3d,"map":map_2d.get_state() if map_active else {},"mode":_view_mode(),"selected_id":selected_id,"follow_id":follow_id,"positions":positions,"residents":displayed.get("residents",[]),"buildings":displayed.get("buildings",[]),"error":last_error}

func _report_state() -> Dictionary:
	var result: Dictionary = get_application_state()
	var resident_view: Node = _resident_view()
	result["crowd_backend"] = resident_view.draw_backend
	result["crowd_backend_error"] = resident_view.last_error
	result["lighting"] = daylight.get_state()
	if place_outline != null: result["place_outline"] = place_outline.get_state()
	if street_trees != null: result["trees"] = street_trees.get_state()
	result["area_activity"] = area_activity_state
	result["places"] = {"available":places.available,"count":places.entries.size(),"selected_id":hud.place_search.active_id,"error":places.last_error}
	result.erase("positions")
	result.erase("residents")
	if geography != null: result["geography"] = geography.get_state()
	if world.landmarks != null: result["landmarks"] = {"loaded":world.landmarks.records.size(),"meshes":world.landmarks.mesh_count,"visible":world.landmarks.visible,"error":world.landmarks.last_error}
	result["frame_profile"] = frame_profile()
	result["buildings"] = []
	result["building_count"] = displayed.get("buildings",[]).size()
	for building: Dictionary in displayed.get("buildings",[]).slice(0,8):
		result.buildings.append({"id":building.id,"occupancy":building.get("occupancy",0)})
	if not resident_view.ids.is_empty():
		var identifier: String = resident_view.ids[0]
		result["sample_resident"] = resident_view.records[identifier].duplicate(true)
		if result.sample_resident.get("trip") is Dictionary:
			result.sample_resident.trip["point_count"] = result.sample_resident.trip.get("points",[]).size()
			result.sample_resident.trip.erase("points")
	return result

func _fail(message: String) -> void:
	last_error = message
	if not startup_complete:
		startup_failed = true
		if loading_screen != null: loading_screen.show_error(message)
	push_error(message)
	print("GODOT_APPLICATION_FAIL " + message)
	_emit_run_metrics()
	if hud != null: hud.set_status(message,true)
	if smoke: get_tree().quit(1)

func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_close_application()

func _close_application() -> void:
	_emit_run_metrics(true)
	# The launcher owns the worker lifecycle. A viewer only closes its peer.
	if client != null: client.peer.disconnect_from_host()
	get_tree().quit()

func _automation() -> void:
	var probe: bool = "--workspace-probe" in OS.get_cmdline_user_args()
	if not smoke and screenshot_path.is_empty() and not probe: return
	automation_running = true
	var deadline: int = Time.get_ticks_msec() + 45000
	while (displayed.is_empty() or not startup_complete) and Time.get_ticks_msec() < deadline and last_error.is_empty():
		await get_tree().process_frame
	if displayed.is_empty() or not startup_complete:
		_fail("The initial simulation and scenery did not finish loading for automation.")
		get_tree().quit(1)
		return
	if probe:
		var failure: String = await preload("res://live_workspace_probe.gd").new().run(self,OS.get_cmdline_user_args())
		if not failure.is_empty(): _fail(failure)
		else: print("GODOT_APPLICATION_WORKSPACE_OK")
		_emit_run_metrics(true)
		get_tree().quit(0 if failure.is_empty() else 1)
		return
	if smoke:
		var warmup_deadline: int = Time.get_ticks_msec()+45000
		while _scenery_pending() and Time.get_ticks_msec() < warmup_deadline: await get_tree().process_frame
		var checks: RefCounted = preload("res://map_mode_checks.gd").new() if initial_mode == "map" else preload("res://smoke_checks.gd").new()
		var failure: String = await checks.run(self)
		if not failure.is_empty():
			_fail(failure)
			get_tree().quit(1)
			return
		print("GODOT_APPLICATION_SMOKE_OK " + JSON.stringify(_report_state()))
		if not replay.is_empty(): _seek_replay(initial_replay_index)
	_set_mode(initial_mode)
	if initial_location == "city" and geography != null and geography.available: _action("city_overview")
	if not initial_place.is_empty() and not _jump_place(initial_place,initial_mode):
		_fail("Could not open the requested named place: " + initial_place)
		get_tree().quit(1)
		return
	if not screenshot_path.is_empty():
		if DisplayServer.get_name() == "headless":
			_fail("Screenshots require a rendered launch.")
			get_tree().quit(1)
			return
		for frame: int in range(6): await get_tree().process_frame
		var scenery_deadline: int = Time.get_ticks_msec()+45000
		while Time.get_ticks_msec() < scenery_deadline:
			if not _scenery_pending(): break
			await get_tree().process_frame
		frame_samples.clear()
		for samples: Array in phase_samples.values(): samples.clear()
		var sample_started: int = Time.get_ticks_msec()
		while frame_samples.size() < 120 or Time.get_ticks_msec()-sample_started < 10000:
			await get_tree().process_frame
		print("GODOT_APPLICATION_FRAME_PROFILE " + JSON.stringify(frame_profile()))
		await RenderingServer.frame_post_draw
		var screenshot: Image = get_viewport().get_texture().get_image()
		if not screenshot_path.get_base_dir().is_empty(): DirAccess.make_dir_recursive_absolute(screenshot_path.get_base_dir())
		var error: Error = screenshot.save_png(screenshot_path)
		if error != OK:
			_fail("Could not save screenshot: " + error_string(error))
			get_tree().quit(1)
			return
		print("GODOT_APPLICATION_SCREENSHOT " + screenshot_path)
	get_tree().quit(0)

func _workspace_layout() -> void:
	var viewport_size: Vector2 = get_viewport().get_visible_rect().size
	layout_last_size = viewport_size
	var dock := Rect2()
	if diagnostics != null: dock = diagnostics.layout(viewport_size)
	if hud != null:
		hud.layout(viewport_size,dock)
		if map_2d != null: map_2d.set_content_rect(hud.content_rect())

func _display_changed() -> void:
	_workspace_layout()
	if startup_complete: _emit_phase("display","settled")

func _phase_context() -> Dictionary:
	var result: Dictionary = {"population":displayed.get("population",displayed.get("residents",[]).size()),"roster_revision":displayed.get("roster_revision",0),"mode":_view_mode() if cameras != null else initial_mode,"paused":displayed.get("paused",false),"speed":displayed.get("speed",1),"world_identity":scene_message.get("world_identity",""),"diagnostics_visible":diagnostics.visible if diagnostics != null else false}
	if display_settings != null: result.merge(display_settings.state())
	if cameras != null and cameras.camera != null:
		var pose: Vector3 = cameras.camera.position
		result["camera_position"] = [pose.x,pose.y,pose.z]
		result["camera_rotation"] = [cameras.camera.rotation.x,cameras.camera.rotation.y,cameras.camera.rotation.z]
		result["orbit_distance"] = cameras.orbit_distance
	return result

func _python_monotonic(local_usec: int) -> Variant:
	return float(local_usec)/1000000.0+telemetry.monotonic_offset if telemetry != null and telemetry.clock_synced else null

func _emit_phase(reason: String, stage: String, change: Dictionary = {}) -> void:
	phase_counter += 1
	phase_id = "viewer-%d" % phase_counter
	phase_started_usec = Time.get_ticks_usec()
	frame_samples.clear()
	for samples: Array in phase_samples.values(): samples.clear()
	var marker: Dictionary = {"viewer_clock_id":viewer_clock_id,"boundary_local_usec":phase_started_usec,"phase_id":phase_id,"reason":reason,"stage":stage,"boundary_at_unix":Time.get_unix_time_from_system(),"received_at_unix":Time.get_unix_time_from_system(),"boundary_monotonic_seconds":_python_monotonic(phase_started_usec),"clock_uncertainty_seconds":telemetry.clock_uncertainty if telemetry != null and telemetry.clock_synced else null,"clock_method":"hello_round_trip" if telemetry != null and telemetry.clock_synced else "unsynchronized","context":_phase_context()}
	if not change.is_empty(): marker["population_change"] = change
	print("GODOT_APPLICATION_PHASE "+JSON.stringify(marker))
	phase_signature = _configuration_signature()

func _configuration_signature() -> String:
	var context: Dictionary = _phase_context()
	for key: String in ["camera_position","camera_rotation","orbit_distance"]: context.erase(key)
	return JSON.stringify(context)

func _update_diagnostics(delta: float) -> void:
	if diagnostics == null: return
	if get_viewport().get_visible_rect().size != layout_last_size: _workspace_layout()
	if startup_complete and not displayed.is_empty():
		var signature: String = _configuration_signature()
		if telemetry != null and telemetry.clock_synced and not phase_clock_synced:
			phase_clock_synced = true
			_emit_phase("telemetry_clock_ready","settled")
		elif signature != phase_signature: _emit_phase("configuration","settled")
		if telemetry != null and not telemetry.clock_synced: phase_clock_synced = false
	diagnostics_elapsed += delta
	if diagnostics_elapsed < 1.0: return
	diagnostics_elapsed = 0.0
	var local_report: Dictionary = run_metrics() if diagnostics.visible else {}
	diagnostics.update_local(local_report,displayed,scene_message)
	if telemetry != null:
		var age: float = float(Time.get_ticks_msec()-telemetry.last_message_msec)/1000.0 if telemetry.last_message_msec > 0 else -1.0
		diagnostics.refresh_feed_label(telemetry.status,age)
