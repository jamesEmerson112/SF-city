extends RefCounted
## Request-correlated menu pause and exit. No process ownership or filesystem I/O.
const OPERATIONS: Array[String] = ["save","load","population","set_population","reset"]
const REPLACING: Array[String] = ["load","population","reset"]
var app: Node
var state: String = "idle"
var menu_open: bool = false
var exit_intent: bool = false
var exit_reason: String = "menu"
var status_text: String = "Options"
var pause_request: String = ""
var save_request: String = ""
var last_save: Dictionary = {}
var authoritative: Dictionary = {}
var current_scene: Dictionary = {}
var known_operations: Dictionary = {}
var abandoned_requests: Dictionary = {}
var baseline_valid: bool = false
var baseline_paused: bool = true
var baseline_session: String = ""
var owns_pause: bool = false
var pause_target: bool = true
var pause_session: String = ""
var pause_origin_session: String = ""
var pause_ack: Dictionary = {}
var save_session: String = ""
var save_capture_tick: int = -1
var reconnect_pending: bool = false
var reconnect_scene_seen: bool = false
var reconnect_pause: Dictionary = {}
var reconnect_save_unknown: bool = false
var save_slot: String = ""
var save_goal: String = ""
var retry_slot: String = ""
var save_for_exit: bool = false
var viewer_only_exit: bool = false
var stage_started_usec: int = 0
var exit_started_usec: int = 0
var durations: Dictionary = {"settling":0.0,"pause":0.0,"save":0.0}
var finished: bool = false
var progress_text: String = ""
var _pumping: bool = false

func initialize(application: Node) -> void:
	app = application

func active() -> bool:
	return menu_open or exit_intent or owns_pause or not pause_request.is_empty() or not save_request.is_empty()

func blocks_actions() -> bool:
	return menu_open or state != "idle" or not pause_request.is_empty() or not save_request.is_empty()

func _live() -> bool:
	return app.replay.is_empty() and app.startup_complete and not app.startup_failed and app.client != null

func _connected() -> bool:
	return _live() and app.client.connected and not app.client.session_id.is_empty()

func _current_complete() -> bool:
	return not authoritative.is_empty() and str(authoritative.get("session_id","")) == str(current_scene.get("session_id","")) and str(authoritative.get("session_id","")) == app.session_id and app.pending_population_scene.is_empty()

func _track_operations() -> void:
	if app.client == null: return
	for identifier: String in app.client.pending_actions:
		var action: String = str(app.client.pending_actions[identifier])
		if action not in OPERATIONS or identifier == save_request or known_operations.has(identifier) or abandoned_requests.has(identifier): continue
		known_operations[identifier] = {"action":action,"session_id":authoritative.get("session_id",""),"revision":authoritative.get("roster_revision",0),"population":authoritative.get("population",0),"world_identity":current_scene.get("world_identity",""),"terminal":false}
	while known_operations.size() > 64: known_operations.erase(known_operations.keys()[0])

func _settled() -> bool:
	_track_operations()
	if not _current_complete(): return false
	var pending: bool = false
	for identifier: String in known_operations.keys():
		var operation: Dictionary = known_operations[identifier]
		if not bool(operation.get("terminal",false)):
			pending = true
		elif bool(operation.get("failed",false)):
			known_operations.erase(identifier)
		elif str(operation.get("ack_session","")) == str(authoritative.session_id) and int(authoritative.get("tick",-1)) >= int(operation.get("ack_tick",0)):
			known_operations.erase(identifier)
		else:
			pending = true
	return not pending

func _new_baseline() -> void:
	if not _current_complete(): return
	baseline_valid = true
	baseline_paused = bool(authoritative.get("paused",true))
	baseline_session = str(authoritative.session_id)
	owns_pause = false

func open_menu() -> void:
	if finished or menu_open: return
	menu_open = true
	app.dragging = false
	app.pan_drag = false
	app.game_menu.set_open(true)
	_track_operations()
	if app.replay.is_empty():
		var replacing: bool = false
		for operation: Dictionary in known_operations.values():
			if str(operation.action) in REPLACING: replacing = true
		if not baseline_valid and not replacing: _new_baseline()
	else:
		baseline_valid = true
		baseline_paused = app.replay_paused
		owns_pause = not baseline_paused
		app.replay_paused = true
		app._render_snapshot()
	pump()

func return_to_city() -> void:
	if finished: return
	exit_intent = false
	viewer_only_exit = false
	save_goal = ""
	save_for_exit = false
	menu_open = false
	app.game_menu.set_open(false)
	app.navigation_rearm = true
	if state == "save_error": _stage("idle","Options")
	if not app.replay.is_empty():
		if owns_pause: app.replay_paused = baseline_paused
		owns_pause = false
		baseline_valid = false
		app._render_snapshot()
	pump()

func save_day() -> void:
	if finished or not save_request.is_empty() or state == "save_error": return
	if not _connected():
		status_text = "Saving requires a ready live simulation."
		_refresh()
		return
	save_goal = "quick"
	last_save = {}
	pump()

func request_exit(reason: String = "menu") -> void:
	if finished or exit_intent: return
	open_menu()
	exit_reason = reason
	exit_started_usec = Time.get_ticks_usec()
	durations = {"settling":0.0,"pause":0.0,"save":0.0}
	stage_started_usec = exit_started_usec
	exit_intent = true
	app.game_menu.show_page("exit")
	if not app.replay.is_empty():
		_finish("replay")
	elif not app.startup_complete or app.startup_failed:
		_finish("not_available")
	elif not app.launcher_owned:
		viewer_only_exit = true
		save_goal = ""
		pump()
	else:
		save_goal = "exit-recovery"
		last_save = {}
		pump()

func cancel_exit() -> void:
	if finished: return
	exit_intent = false
	viewer_only_exit = false
	save_goal = ""
	save_for_exit = false
	if state == "save_error": _stage("idle","Options")
	app.game_menu.show_page("root")
	pump()

func retry() -> void:
	if finished or state != "save_error": return
	if not _connected():
		status_text = "The worker is unavailable. Return to the city and reconnect, or explicitly exit without saving."
		_refresh()
		return
	reconnect_save_unknown = false
	save_goal = retry_slot if not retry_slot.is_empty() else ("exit-recovery" if exit_intent else "")
	pause_request = ""
	pause_ack = {}
	_stage("idle","Retrying...")
	pump()

func confirm_unsaved() -> void:
	if finished: return
	if _live() and not app.launcher_owned and _connected():
		exit_intent = true
		viewer_only_exit = true
		save_goal = ""
		save_for_exit = false
		pump()
		return
	if exit_started_usec == 0: exit_started_usec = Time.get_ticks_usec()
	_finish("unknown" if not save_request.is_empty() or str(last_save.get("outcome","")) == "unknown" else "skipped")

func observe_scene(message: Dictionary) -> void:
	_track_operations()
	var old: String = str(current_scene.get("session_id",""))
	var next: String = str(message.get("session_id",""))
	var continuous: bool = false
	var change: Dictionary = message.get("population_change",{})
	var identifier: String = str(change.get("request_id",""))
	if str(message.get("reason","")) == "population_adjustment" and known_operations.has(identifier):
		var operation: Dictionary = known_operations[identifier]
		continuous = str(operation.action) == "set_population" and str(operation.session_id) == old and old != next and not old.is_empty() and not str(message.get("world_identity","")).is_empty() and message.get("world_identity") == operation.world_identity and int(message.get("roster_revision",-1)) == int(operation.revision)+1 and int(change.get("roster_revision",-1)) == int(operation.revision)+1 and int(change.get("old_count",-1)) == int(operation.population)
	var expected_replacement: bool = false
	for operation: Dictionary in known_operations.values():
		if str(operation.action) in REPLACING and str(operation.session_id) == old and (not bool(operation.get("terminal",false)) or str(operation.get("ack_session","")) == next):
			expected_replacement = true
	if reconnect_pending: reconnect_scene_seen = true
	current_scene = {"session_id":next,"world_identity":message.get("world_identity",""),"roster_revision":message.get("roster_revision",0)}
	if old == next or old.is_empty() or not active(): return
	if continuous:
		baseline_session = next
		if pause_session == old: pause_session = next
	else:
		baseline_valid = false
		baseline_session = next
		owns_pause = false
		reconnect_pause = {}
		pause_request = ""
		pause_ack = {}
		if not save_request.is_empty() or (exit_intent and not expected_replacement):
			_abandon_save()
			last_save = {"outcome":"unknown"}
			save_goal = ""
			_error("The simulation session changed. Review the new day before retrying; the earlier save outcome is unknown.")
		elif state != "save_error":
			_stage("settling_operation","Waiting for the new day...")
	# A newly complete snapshot and any originating operation ACK must arrive first.

func observe_snapshot(message: Dictionary) -> void:
	authoritative = {}
	for key: String in ["session_id","sequence","tick","paused","speed","population","roster_revision"]:
		authoritative[key] = message.get(key)
	if reconnect_pending and reconnect_scene_seen and _current_complete():
		# Prior socket ACKs can never arrive through a fresh decoder generation.
		known_operations.clear()
		reconnect_pending = false
		reconnect_scene_seen = false
		if not reconnect_save_unknown and not reconnect_pause.is_empty() and str(reconnect_pause.get("session_id","")) == str(authoritative.session_id):
			baseline_valid = true
			baseline_paused = bool(reconnect_pause.get("baseline_paused",true))
			baseline_session = str(authoritative.session_id)
			pause_target = bool(reconnect_pause.target)
			pause_session = baseline_session
			pause_origin_session = baseline_session
			pause_ack = {}
			_stage("pausing","Reconciling the earlier pause request...")
			pause_request = app.client.command("pause",pause_target)
		elif not reconnect_save_unknown and state == "save_error":
			_stage("idle","Connected to the current day.")
		reconnect_pause = {}
	pump()

func acknowledge(message: Dictionary) -> void:
	var identifier: String = str(message.get("request_id",""))
	var success: bool = str(message.get("type","")) == "ack"
	if known_operations.has(identifier):
		var operation: Dictionary = known_operations[identifier]
		operation["terminal"] = true
		operation["failed"] = not success
		operation["ack_session"] = str(message.get("session_id",""))
		operation["ack_tick"] = int(message.get("tick",0))
	if identifier == pause_request and str(message.get("action","")) == "pause":
		if not success:
			pause_request = ""
			_error("Pause request failed: "+str(message.get("message","worker rejected the request.")))
		else:
			# A population handoff can carry this already accepted pause into a
			# new transport session; the scene validator updates pause_session.
			var reply_session: String = str(message.get("session_id",""))
			if reply_session != pause_origin_session:
				pause_request = ""
				_error("Pause reply belongs to an earlier simulation session.")
			else:
				pause_ack = message.duplicate(false)
	if identifier == save_request and str(message.get("action","")) == "save":
		if not success:
			save_request = ""
			last_save = {"outcome":"failed"}
			_error("Could not save the day. Check the save folder and try again. Details are in Performance logs.")
		elif str(message.get("session_id","")) != save_session or save_session != str(current_scene.get("session_id","")) or str(message.get("slot","")) != save_slot or not valid_capture(message) or int(message.get("captured_tick",-1)) != save_capture_tick:
			save_request = ""
			last_save = {"outcome":"unknown"}
			_error("The save reply does not confirm this session and slot. Save outcome unknown.")
		else:
			last_save = {"outcome":"saved","slot":save_slot,"captured_tick":int(message.captured_tick),"session_id":save_session}
			save_request = ""
			_stage("idle","Saved %s at tick %d." % [save_slot,int(message.captured_tick)])
			if exit_intent and save_for_exit:
				_finish("saved")
				return
	pump()

func command_progress(message: Dictionary) -> void:
	var identifier: String = str(message.get("request_id",""))
	if identifier == save_request and str(message.get("action","")) == "save" and str(message.get("session_id","")) == save_session:
		progress_text = "Saving %s: %.0f s" % [save_slot,float(message.get("elapsed_seconds",0.0))]
	elif known_operations.has(identifier):
		progress_text = "Waiting for %s: %.0f s" % [str(message.get("action","operation")),float(message.get("elapsed_seconds",0.0))]

func connection_failed(message: String) -> void:
	if not active(): return
	reconnect_pending = true
	reconnect_scene_seen = false
	if not pause_request.is_empty():
		reconnect_pause = {"session_id":pause_session,"target":pause_target,"baseline_paused":baseline_paused}
	elif owns_pause:
		reconnect_pause = {"session_id":baseline_session,"target":menu_open,"baseline_paused":baseline_paused}
	if not save_request.is_empty():
		_abandon_save()
		reconnect_save_unknown = true
		last_save = {"outcome":"unknown"}
		_error("Save outcome unknown: "+message)
	elif exit_intent or not pause_request.is_empty():
		pause_request = ""
		pause_ack = {}
		_error("The worker is unavailable: "+message)
	else:
		_stage("idle","Disconnected. The prior operation's outcome is unknown until reconnect.")

static func valid_capture(message: Dictionary) -> bool:
	var value: Variant = message.get("captured_tick")
	return (value is int or value is float) and is_finite(float(value)) and float(value) >= 0 and float(value) == floorf(float(value)) and value == message.get("tick")

func _abandon_save() -> void:
	if not save_request.is_empty(): abandoned_requests[save_request] = true
	while abandoned_requests.size() > 64: abandoned_requests.erase(abandoned_requests.keys()[0])
	save_request = ""

func _pause_ready() -> bool:
	if pause_request.is_empty(): return true
	if pause_ack.is_empty() or not _current_complete(): return false
	if str(authoritative.session_id) != pause_session or int(authoritative.tick) < int(pause_ack.get("tick",0)) or bool(authoritative.paused) != pause_target: return false
	owns_pause = pause_target and not baseline_paused
	pause_request = ""
	pause_ack = {}
	_stage("idle","City paused." if pause_target else "Playback restored.")
	return true

func pump() -> void:
	if app == null or finished or _pumping: return
	_pumping = true
	_pump()
	_refresh()
	_pumping = false

func _pump() -> void:
	if state == "save_error": return
	if reconnect_pending:
		status_text = "Waiting for a fresh connection and complete city state."
		return
	if not active() and save_goal.is_empty():
		baseline_valid = false
		return
	if not app.replay.is_empty():
		status_text = "Replay paused. Saving requires the live simulation."
		return
	if not _live():
		status_text = "There is no ready day to save. Exit cancels loading." if not app.startup_failed else "Loading stopped. You can close this application."
		return
	if not _connected():
		if exit_intent: _error("The worker is unavailable. No recovery save has been confirmed.")
		else: status_text = "Simulation disconnected. Saving and pausing are unavailable."
		return
	if not _pause_ready():
		_stage("pausing","Pausing..." if pause_target else "Restoring playback...")
		return
	if not save_request.is_empty(): return
	if not _settled():
		_stage("settling_operation","Waiting for the current operation and complete city state...")
		return
	if not baseline_valid: _new_baseline()
	var should_pause: bool = menu_open and not viewer_only_exit
	if should_pause and not bool(authoritative.get("paused",true)):
		pause_target = true
		pause_session = str(authoritative.session_id)
		pause_origin_session = pause_session
		pause_ack = {}
		_stage("pausing","Pausing...")
		pause_request = app.client.command("pause",true)
		if pause_request.is_empty(): _error("The pause request could not be sent.")
		return
	if not should_pause and owns_pause:
		pause_target = false
		pause_session = str(authoritative.session_id)
		pause_origin_session = pause_session
		pause_ack = {}
		_stage("pausing","Restoring playback...")
		pause_request = app.client.command("pause",false)
		if pause_request.is_empty(): _error("Playback could not be restored.")
		return
	if viewer_only_exit:
		_finish("viewer_only")
		return
	if not save_goal.is_empty():
		save_slot = save_goal
		save_goal = ""
		retry_slot = save_slot
		save_session = str(authoritative.session_id)
		save_capture_tick = int(authoritative.tick)
		save_for_exit = exit_intent and save_slot == "exit-recovery"
		_stage("saving","Saving %s..." % save_slot)
		save_request = app.client.command("save",save_slot)
		if save_request.is_empty(): _error("The save request could not be sent.")
		return
	if state != "idle": _stage("idle","City paused." if menu_open else "Options")
	if not menu_open:
		baseline_valid = false
		owns_pause = false

func _stage(next: String, label: String) -> void:
	if state != next:
		if stage_started_usec > 0:
			var key: String = {"settling_operation":"settling","pausing":"pause","saving":"save"}.get(state,"")
			if not key.is_empty(): durations[key] += float(Time.get_ticks_usec()-stage_started_usec)/1000.0
		state = next
		stage_started_usec = Time.get_ticks_usec()
		progress_text = ""
	status_text = label

func _error(message: String) -> void:
	retry_slot = save_goal if not save_goal.is_empty() else save_slot
	_stage("save_error",message)
	if app.game_menu.visible: app.game_menu.show_page("error")

func _refresh() -> void:
	if app == null or app.game_menu == null: return
	var message: String = progress_text if not progress_text.is_empty() else status_text
	if state in ["settling_operation","pausing","saving"] and stage_started_usec > 0:
		var seconds: float = float(Time.get_ticks_usec()-stage_started_usec)/1000000.0
		message += "\n%.0f s elapsed" % seconds
		if seconds >= 15.0: message += "\nStill working. You can keep waiting; no save deadline has been imposed."
	var label: String = "Save & Exit"
	if not app.replay.is_empty(): label = "Exit replay"
	elif not app.startup_complete or app.startup_failed: label = "Exit application"
	elif not app.launcher_owned: label = "Close viewer"
	app.game_menu.update_status(message,state in ["settling_operation","pausing","saving","closing"],_connected(),label)

func _finish(outcome: String) -> void:
	if finished: return
	finished = true
	_stage("closing","Closing... The launcher may still be finishing cleanup.")
	_refresh()
	var preferences_started: int = Time.get_ticks_usec()
	if app.display_settings != null: app.display_settings.persist()
	durations["preferences"] = float(Time.get_ticks_usec()-preferences_started)/1000.0
	durations["total"] = float(Time.get_ticks_usec()-exit_started_usec)/1000.0 if exit_started_usec > 0 else 0.0
	var marker: Dictionary = {"schema_version":1,"reason":exit_reason,"save_intent":"save" if outcome == "saved" else ("skip" if outcome in ["skipped","unknown"] else "unavailable"),"save_outcome":outcome,"slot":"exit-recovery" if outcome in ["saved","unknown"] else null,"captured_tick":int(last_save.get("captured_tick",0)) if outcome == "saved" else null,"session_id":str(current_scene.get("session_id","")),"durations_ms":durations.duplicate(),"at_unix":Time.get_unix_time_from_system()}
	app._finalize_menu_exit(marker)
