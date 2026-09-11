extends SceneTree
const Flow = preload("res://menu_flow.gd")
class Peer extends Node:
	var connected: bool = true
	var session_id: String = "s1"
	var pending_actions: Dictionary = {}
	var commands: Array[Dictionary] = []
	func command(action: String, value: Variant = null) -> String:
		var identifier: String = "test-%d" % (commands.size()+1)
		pending_actions[identifier] = action
		commands.append({"request_id":identifier,"action":action,"value":value})
		return identifier

class Menu extends Control:
	var page: String = "root"
	var text_value: String = ""
	func set_open(value: bool) -> void: visible = value
	func show_page(value: String) -> void: page = value
	func update_status(message: String,_busy: bool,_can_save: bool,_label: String) -> void: text_value = message

class App extends Node:
	var client := Peer.new()
	var game_menu := Menu.new()
	var replay: Dictionary = {}
	var replay_paused: bool = false
	var startup_complete: bool = true
	var startup_failed: bool = false
	var session_id: String = "s1"
	var pending_population_scene: Dictionary = {}
	var launcher_owned: bool = true
	var dragging: bool = true
	var pan_drag: bool = true
	var navigation_rearm: bool = false
	var display_settings: Node
	var exits: Array[Dictionary] = []
	func _init() -> void:
		add_child(client)
		add_child(game_menu)
		game_menu.visible = false
	func _render_snapshot() -> void: pass
	func _finalize_menu_exit(marker: Dictionary) -> void: exits.append(marker)

var failures: Array[String] = []

func _initialize() -> void:
	_late_pause()
	_saved_exit()
	_cancel_save()
	_save_intent_races()
	_save_error_retry()
	_population_continuity()
	_late_pause_population()
	_loaded_baseline()
	_stale_save()
	_unknown_save()
	_standalone()
	_loading_replay()
	_reconnect_pause()
	_reconnect_operation()
	_exit_waits_load()
	_timing_scope()
	if failures.is_empty(): print("GODOT_MENU_FLOW_TESTS_OK late ACKs, save correlation/cancellation, live handoffs, loaded baseline, unknown outcomes, ownership")
	else:
		for message: String in failures: push_error(message)
	quit(0 if failures.is_empty() else 1)

func _setup(paused: bool = false) -> Array:
	var app := App.new()
	var flow = Flow.new()
	flow.initialize(app)
	flow.observe_scene({"session_id":"s1","world_identity":"world","roster_revision":0})
	_snapshot(flow,paused)
	return [app,flow]

func _snapshot(flow: RefCounted, paused: bool, tick: int = 40, revision: int = 0, population: int = 20) -> void:
	flow.observe_snapshot({"session_id":flow.app.session_id,"sequence":tick,"tick":tick,"paused":paused,"speed":4,"roster_revision":revision,"population":population})

func _ack(flow: RefCounted, identifier: String, action: String, tick: int = 40, extra: Dictionary = {}) -> void:
	flow.app.client.pending_actions.erase(identifier)
	var message: Dictionary = {"type":"ack","request_id":identifier,"action":action,"session_id":flow.app.session_id,"tick":tick}
	message.merge(extra,true)
	flow.acknowledge(message)

func _pause(flow: RefCounted, paused: bool = true, tick: int = 41, revision: int = 0, population: int = 20) -> void:
	var identifier: String = flow.pause_request
	_check(not identifier.is_empty(),"Expected a pause/resume request")
	_ack(flow,identifier,"pause",tick)
	_snapshot(flow,paused,tick,revision,population)

func _check(value: bool, message: String) -> void:
	if not value: failures.append(message)

func _late_pause() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.open_menu()
	var identifier: String = flow.pause_request
	flow.return_to_city()
	_check(app.client.commands.size() == 1 and not app.game_menu.visible,"Returning before pause ACK queued an early resume or kept modal open")
	_ack(flow,identifier,"pause",42)
	_check(app.client.commands.size() == 1,"ACK alone was treated as complete paused state")
	_snapshot(flow,true,42)
	_check(app.client.commands.size() == 2 and app.client.commands.back().value == false,"Late pause was not reconciled by one resume")
	_pause(flow,false,43)
	_check(not flow.owns_pause and not flow.baseline_valid and flow.state == "idle","Late pause reconciliation retained stale pause ownership")
	_snapshot(flow,true,44)
	flow.open_menu()
	flow.return_to_city()
	_check(app.client.commands.size() == 2,"A later already-paused menu incorrectly restored an old running baseline")
	app.free()

func _saved_exit() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.request_exit("window_close")
	var identifier: String = flow.save_request
	flow.request_exit("window_close")
	_check(app.client.commands.size() == 1 and app.client.commands[0].value == "exit-recovery","Repeated exit queued duplicate saves or overwrote quick slot")
	flow.command_progress({"request_id":identifier,"action":"save","session_id":"s1","elapsed_seconds":30})
	flow.pump()
	_check(app.exits.is_empty() and "30" in app.game_menu.text_value,"Progress confirmed a save or lost correlated progress")
	_ack(flow,"unrelated","save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.is_empty(),"Unrelated save ACK closed application")
	_ack(flow,identifier,"save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.size() == 1 and app.exits[0].save_outcome == "saved" and app.exits[0].captured_tick == 40,"Matching save ACK did not produce one confirmed recovery exit")
	flow.acknowledge({"type":"ack","request_id":identifier,"action":"save","session_id":"s1","slot":"exit-recovery","captured_tick":40,"tick":40})
	flow.confirm_unsaved()
	_check(app.exits.size() == 1,"Late duplicate save/exit produced repeated finalization")
	app.free()

func _cancel_save() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.open_menu()
	_pause(flow)
	flow.request_exit()
	var identifier: String = flow.save_request
	flow.cancel_exit()
	flow.return_to_city()
	_check(app.client.commands.size() == 2,"Returning while save pending sent playback change before it settled")
	_ack(flow,identifier,"save",41,{"slot":"exit-recovery","captured_tick":41})
	_check(app.exits.is_empty() and app.client.commands.back().value == false,"Cancelled exit ACK closed app or stranded menu pause")
	_pause(flow,false,42)
	_check(flow.state == "idle","Cancelled save did not settle")
	app.free()

func _population_scene(flow: RefCounted, identifier: String) -> void:
	flow.app.session_id = "s2"
	flow.app.client.session_id = "s2"
	flow.observe_scene({"session_id":"s2","reason":"population_adjustment","world_identity":"world","roster_revision":1,"population_change":{"request_id":identifier,"roster_revision":1,"old_count":20,"new_count":35}})

func _population_continuity() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	var operation: String = app.client.command("set_population",35)
	flow.open_menu()
	_check(flow.pause_request.is_empty() and flow.state == "settling_operation","Menu ignored pending population preparation")
	_population_scene(flow,operation)
	_snapshot(flow,false,45,1,35)
	_check(flow.pause_request.is_empty(),"Population snapshot alone bypassed terminal operation ACK")
	_ack(flow,operation,"set_population",45)
	_pause(flow,true,46,1,35)
	flow.return_to_city()
	_check(not flow.pause_target and flow.pause_session == "s2","Live population handoff lost original running baseline")
	_pause(flow,false,47,1,35)
	_check(app.exits.is_empty() and not flow.owns_pause,"Live population return did not settle")
	app.free()

func _late_pause_population() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.open_menu()
	var pause_id: String = flow.pause_request
	var operation: String = app.client.command("set_population",35)
	flow.pump()
	_population_scene(flow,operation)
	flow.return_to_city()
	_ack(flow,pause_id,"pause",41,{"session_id":"s1"})
	_snapshot(flow,true,45,1,35)
	_ack(flow,operation,"set_population",45)
	_check(flow.state != "save_error" and not flow.pause_target and not flow.pause_request.is_empty(),"Validated handoff rejected late original-session pause ACK")
	_pause(flow,false,46,1,35)
	app.free()

func _loaded_baseline() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	var operation: String = app.client.command("load","quick")
	flow.open_menu()
	app.session_id = "loaded"
	app.client.session_id = "loaded"
	flow.observe_scene({"session_id":"loaded","world_identity":"world","roster_revision":0})
	_snapshot(flow,false,100)
	_check(flow.pause_request.is_empty(),"Load complete state bypassed terminal ACK")
	_ack(flow,operation,"load",100)
	_pause(flow,true,101)
	flow.return_to_city()
	_check(not flow.pause_target,"Loaded running day incorrectly inherited previous paused baseline")
	_pause(flow,false,102)
	app.free()

func _stale_save() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.request_exit()
	var identifier: String = flow.save_request
	app.session_id = "loaded"
	app.client.session_id = "loaded"
	flow.observe_scene({"session_id":"loaded","world_identity":"world","roster_revision":0})
	_snapshot(flow,true,100)
	_ack(flow,identifier,"save",40,{"session_id":"s1","slot":"exit-recovery","captured_tick":40})
	_check(app.exits.is_empty() and flow.state == "save_error","Stale save ACK closed a replacement session")
	app.free()

func _unknown_save() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.request_exit()
	app.client.connected = false
	flow.connection_failed("Disconnected before final acknowledgement.")
	_check(flow.state == "save_error" and flow.last_save.outcome == "unknown" and app.exits.is_empty(),"Lost save ACK was treated as success or automatic exit")
	flow.retry()
	_check(app.client.commands.size() == 1,"Disconnected retry silently submitted a save")
	flow.confirm_unsaved()
	_check(app.exits.size() == 1 and app.exits[0].save_outcome == "unknown","Explicit exit concealed unknown save outcome")
	app.free()

func _standalone() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	app.launcher_owned = false
	flow.open_menu()
	_pause(flow)
	flow.request_exit()
	_check(app.exits.is_empty() and not flow.pause_target,"Standalone exit did not await restoring its owned pause")
	_pause(flow,false,42)
	_check(app.exits.size() == 1 and app.exits[0].save_outcome == "viewer_only","Standalone viewer claimed recovery or worker ownership")
	for command: Dictionary in app.client.commands: _check(command.action == "pause","Standalone exit sent save/shutdown command")
	app.free()

func _loading_replay() -> void:
	for replay_mode: bool in [false,true]:
		var pair: Array = _setup()
		var app: App = pair[0]
		var flow: RefCounted = pair[1]
		if replay_mode: app.replay = {"fixture":true}
		else: app.startup_complete = false
		flow.request_exit("menu")
		_check(app.exits.size() == 1 and app.client.commands.is_empty(),"Loading/replay exit tried to save a live day")
		_check(app.exits[0].save_outcome == ("replay" if replay_mode else "not_available"),"Loading/replay exit reported wrong outcome")
		app.free()

func _save_intent_races() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.open_menu()
	flow.save_day()
	var quick: String = flow.save_request
	flow.request_exit()
	_ack(flow,quick,"save",40,{"slot":"quick","captured_tick":40})
	_check(app.exits.is_empty() and not flow.save_request.is_empty() and app.client.commands.back().value == "exit-recovery","Quick save completion discarded a queued recovery exit")
	_ack(flow,flow.save_request,"save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.size() == 1,"Recovery queued behind quick save did not close")
	app.free()
	pair = _setup(true)
	app = pair[0]
	flow = pair[1]
	flow.request_exit()
	var old: String = flow.save_request
	flow.cancel_exit()
	flow.request_exit()
	_ack(flow,old,"save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.is_empty() and not flow.save_request.is_empty() and flow.save_request != old,"Cancelled exit's late ACK closed a new exit intent")
	_ack(flow,flow.save_request,"save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.size() == 1,"New exit did not capture after cancelled save settled")
	app.free()

func _save_error_retry() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.request_exit()
	var identifier: String = flow.save_request
	app.client.pending_actions.erase(identifier)
	flow.acknowledge({"type":"error","request_id":identifier,"action":"save","session_id":"s1","code":"checkpoint_error","message":"save failed: [WinError 5] Access denied: C:/private/save.tmp -> C:/private/exit-recovery.json"})
	_check(flow.state == "save_error" and app.exits.is_empty(),"Failed save closed application")
	_check("Could not save the day." in flow.status_text and "Performance logs" in flow.status_text and not "WinError" in flow.status_text and not "C:/private" in flow.status_text,"Menu exposed raw save paths instead of concise recovery guidance")
	flow.retry()
	_check(app.client.commands.size() == 2 and not flow.save_request.is_empty(),"Explicit retry did not submit one new recovery save")
	_ack(flow,flow.save_request,"save",40,{"slot":"exit-recovery","captured_tick":40})
	_check(app.exits.size() == 1 and app.exits[0].save_outcome == "saved","Successful retry did not confirm saved exit")
	_check(not Flow.valid_capture({"captured_tick":-1,"tick":-1}) and not Flow.valid_capture({"captured_tick":40.5,"tick":40.5}) and not Flow.valid_capture({"captured_tick":40,"tick":41}),"Malformed capture tick was accepted")
	app.free()

func _reconnect_pause() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.open_menu()
	var lost: String = flow.pause_request
	app.client.connected = false
	app.client.pending_actions.clear()
	flow.connection_failed("Pause reply lost")
	flow.return_to_city()
	app.client.connected = true
	flow.observe_scene({"session_id":"s1","world_identity":"world","roster_revision":0})
	_snapshot(flow,true,41)
	_check(not flow.pause_request.is_empty() and flow.pause_request != lost and flow.pause_target,"Reconnect forgot an unresolved applied pause")
	_pause(flow,true,41)
	_check(not flow.pause_target,"Reconciled pause was not followed by restoration after Return")
	_pause(flow,false,42)
	_check(not flow.owns_pause and app.exits.is_empty(),"Reconnect left the formerly running city paused")
	app.free()

func _reconnect_operation() -> void:
	var pair: Array = _setup()
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	app.client.command("load","quick")
	flow.open_menu()
	app.client.connected = false
	app.client.pending_actions.clear()
	flow.connection_failed("Load result lost")
	app.client.connected = true
	app.client.session_id = "loaded"
	app.session_id = "loaded"
	flow.observe_scene({"session_id":"loaded","world_identity":"world","roster_revision":0})
	_snapshot(flow,false,80)
	_check(flow.known_operations.is_empty() and not flow.pause_request.is_empty(),"Fresh reconnect remained blocked on an unreachable old operation ACK")
	_pause(flow,true,81)
	flow.return_to_city()
	_pause(flow,false,82)
	app.free()

func _exit_waits_load() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	var operation: String = app.client.command("load","quick")
	flow.request_exit()
	app.client.session_id = "loaded"
	app.session_id = "loaded"
	flow.observe_scene({"session_id":"loaded","world_identity":"world","roster_revision":0})
	_snapshot(flow,false,80)
	_check(flow.state != "save_error" and flow.save_request.is_empty(),"Expected pending load became an unexpected-session error")
	_ack(flow,operation,"load",80)
	_pause(flow,true,81)
	_check(flow.save_session == "loaded" and not flow.save_request.is_empty(),"Exit did not save the settled newly loaded day")
	_ack(flow,flow.save_request,"save",81,{"slot":"exit-recovery","captured_tick":81})
	_check(app.exits.size() == 1 and app.exits[0].captured_tick == 81,"Loaded-session exit saved the wrong tick")
	app.free()

func _timing_scope() -> void:
	var pair: Array = _setup(true)
	var app: App = pair[0]
	var flow: RefCounted = pair[1]
	flow.durations = {"pause":2000.0,"settling":1000.0,"save":8000.0}
	flow.request_exit()
	_check(flow.durations.pause == 0 and flow.durations.settling == 0 and flow.durations.save == 0,"Exit timing included earlier menu visits")
	_ack(flow,flow.save_request,"save",40,{"slot":"exit-recovery","captured_tick":40.0})
	var serialized: String = JSON.stringify(app.exits[0])
	_check('"captured_tick":40,' in serialized or '"captured_tick":40}' in serialized,"Confirmed captured tick did not serialize as an integer")
	app.free()
