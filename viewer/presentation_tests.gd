extends SceneTree
## Run: Godot --headless --path viewer --script res://presentation_tests.gd
const Presenter = preload("res://presenter.gd")
var failures: Array[String] = []

func _initialize() -> void:
	_test_corner_interpolation()
	_test_atomic_arrival()
	_test_session_boundary()
	_test_snapshot_validation()
	_test_reordered_crowd()
	_test_route_cache_lifecycle()
	_test_bounded_route_span()
	if failures.is_empty():
		print("GODOT_PRESENTATION_TESTS_OK corner interpolation, arrival atomicity, session reset, protocol sequencing, stable crowd slots")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _resident() -> Dictionary:
	return {"id":"person-a","activity":"walking_to_work","position":[8,0,0],"heading":0,"visible":true,"moving":true,"trip":{"id":"trip-a","points":[[0,0,0],[10,0,0],[10,10,0]],"segment_index":0,"segment_progress":0.8}}

func _snapshot(tick: int, person: Dictionary) -> Dictionary:
	return {"type":"snapshot","protocol_version":1,"session_id":"one","sequence":tick,"tick":tick,"simulation_time":float(tick)/200.0,"clock_seconds":28790.0+float(tick)/200.0,"paused":false,"speed":1,"residents":[person],"buildings":[{"id":"office","occupancy":0}]}

func _test_corner_interpolation() -> void:
	var presenter = Presenter.new()
	var first: Dictionary = _resident()
	var second: Dictionary = first.duplicate(true)
	second.position = [10,2,0]
	second.heading = PI/2.0
	second.trip.segment_index = 1
	second.trip.segment_progress = 0.2
	presenter.receive(_snapshot(100,first))
	presenter.receive(_snapshot(120,second))
	presenter.received_at = Time.get_ticks_msec()/1000.0 - presenter.blend_duration * 0.5
	var sample: Dictionary = presenter.sample()
	var position: Array = sample.residents[0].position
	if absf(float(position[0])-10.0) > 0.05 or absf(float(position[1])) > 0.05:
		failures.append("Corner interpolation cut diagonally across the route.")
	if not presenter.sample().residents[0].moving: failures.append("Walking state was lost between snapshots.")
	presenter.received_at = -100000.0
	if presenter.sample().residents[0].position != second.position: failures.append("A stale frame extrapolated beyond the latest authoritative position.")

func _test_atomic_arrival() -> void:
	var presenter = Presenter.new()
	var first: Dictionary = _resident()
	var arrival: Dictionary = first.duplicate(true)
	arrival.activity = "at_work"
	arrival.visible = false
	arrival.moving = false
	arrival.position = [10,10,0]
	arrival.trip = null
	var complete: Dictionary = _snapshot(200,arrival)
	complete.buildings[0].occupancy = 1
	presenter.receive(_snapshot(100,first))
	presenter.receive(complete)
	var shown: Dictionary = presenter.sample()
	if not presenter.atomic or shown.residents[0].visible or shown.residents[0].position != arrival.position or shown.buildings[0].occupancy != 1:
		failures.append("Arrival position, visibility and occupancy did not change together.")

func _test_route_cache_lifecycle() -> void:
	var presenter = Presenter.new()
	var first: Dictionary = _resident()
	var same: Dictionary = first.duplicate(true)
	same.position = [9,0,0]
	same.trip.segment_progress = 0.9
	presenter.receive(_snapshot(100,first))
	presenter.receive(_snapshot(120,same))
	presenter.received_at = Time.get_ticks_msec()/1000.0-presenter.blend_duration*0.5
	if absf(float(presenter.sample().residents[0].position[0])-8.5) > 0.05: failures.append("Same-segment interpolation lost the authoritative position interval.")
	var corner: Dictionary = same.duplicate(true)
	corner.position = [10,2,0]
	corner.trip.segment_index = 1
	corner.trip.segment_progress = 0.2
	presenter.receive(_snapshot(140,corner))
	if presenter.route_cache.size() != 1: failures.append("A corner crossing did not cache cumulative route distances.")
	var arrival: Dictionary = corner.duplicate(true)
	arrival.trip = null
	arrival.activity = "at_work"
	arrival.visible = false
	arrival.moving = false
	presenter.receive(_snapshot(160,arrival))
	if not presenter.route_cache.is_empty(): failures.append("Completed trips accumulated in the presentation route cache.")
	presenter.receive(_snapshot(180,first))
	presenter.receive(_snapshot(200,corner))
	var reset: Dictionary = _snapshot(0,first)
	reset.session_id = "another-day"
	presenter.receive(reset)
	if not presenter.route_cache.is_empty(): failures.append("A new session retained another session's route geometry.")

func _test_session_boundary() -> void:
	var presenter = Presenter.new()
	presenter.receive(_snapshot(100,_resident()))
	var reset: Dictionary = _snapshot(0,_resident())
	reset.session_id = "two"
	reset.residents[0].position = [-50,0,0]
	presenter.receive(reset)
	if not presenter.atomic or presenter.sample().residents[0].position != [-50,0,0]: failures.append("Reset interpolated from the old session.")

func _test_bounded_route_span() -> void:
	var presenter = Presenter.new()
	var before: Dictionary = _resident()
	before.trip.points = []
	for i: int in range(5001): before.trip.points.append([float(i)*10.0,0.0,0.0])
	before.trip.segment_index = 2200
	before.trip.segment_progress = 0.8
	before.position = [22008.0,0.0,0.0]
	var after: Dictionary = before.duplicate(false)
	after.trip = before.trip.duplicate(false)
	after.trip.segment_index = 2203
	after.trip.segment_progress = 0.2
	after.position = [22032.0,0.0,0.0]
	presenter.receive(_snapshot(100,before))
	presenter.receive(_snapshot(120,after))
	presenter.received_at = Time.get_ticks_msec()/1000.0-presenter.blend_duration*0.5
	var shown: Dictionary = presenter.sample()
	if absf(float(shown.residents[0].position[0])-22020.0) > 0.05: failures.append("A span starting mid-route lost its absolute segment offset.")
	if presenter.route_cache["trip-a"].cumulative.size() != 5: failures.append("A short snapshot interval scanned the entire route.")

func _test_snapshot_validation() -> void:
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var scene: Dictionary = {"type":"scene","protocol_version":1,"session_id":"one","scenario":{}}
	client._receive(JSON.stringify(scene))
	client._receive(JSON.stringify(_snapshot(100,_resident())))
	client._receive(JSON.stringify(_snapshot(90,_resident())))
	if client.sequence != 100: failures.append("A stale snapshot sequence was accepted.")
	var wrong: Dictionary = _snapshot(200,_resident())
	wrong.session_id = "old"
	client._receive(JSON.stringify(wrong))
	if client.sequence != 100: failures.append("An old session snapshot was accepted.")
	client.free()

func _test_reordered_crowd() -> void:
	var crowd = preload("res://crowd.gd").new()
	root.add_child(crowd)
	var visual: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://assets/visual.json"))
	crowd.initialize(visual)
	var first: Dictionary = _resident()
	var second: Dictionary = first.duplicate(true)
	second.id = "person-b"
	second.position = [20,10,0]
	crowd.apply_snapshot({"residents":[first,second]},null,"person-b")
	var slot: int = int(crowd.slots["person-b"])
	first.position = [9,0,0]
	second.position = [21,10,0]
	crowd.apply_snapshot({"residents":[second,first]},null,"person-b")
	if int(crowd.slots["person-b"]) != slot: failures.append("Snapshot array reordering changed the resident's render slot.")
	if crowd.display_transforms["person-b"].origin.distance_to(Vector3(21,0,-10)) > 0.0001: failures.append("Reordered snapshot moved the wrong resident.")
	second.activity = "at_work"
	second.visible = false
	second.moving = false
	crowd.apply_snapshot({"residents":[first,second]},null,"person-b")
	if not crowd.records.has("person-b") or int(crowd.slots["person-b"]) != slot: failures.append("Indoor arrival destroyed a resident's persistent render identity.")
	crowd.free()
