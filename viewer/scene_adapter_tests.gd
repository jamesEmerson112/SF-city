extends SceneTree
## Godot --headless --path viewer --script res://scene_adapter_tests.gd
const Adapter = preload("res://scene_adapter.gd")
class RejectionDiagnostics extends PanelContainer:
	var pending: bool = false

	func set_population_status(_message: String, waiting: bool) -> void:
		pending = waiting

var failures: Array[String] = []

func _initialize() -> void:
	_test_complete_reconstruction()
	_test_invalid_membership()
	_test_session_and_legacy()
	_test_client_application()
	_test_reliable_trip_geometry()
	_test_rows()
	_test_invalid_rows()
	_test_client_buffer_and_pending_status()
	_test_command_rejection_severity()
	_test_thread_ordering_and_generation()
	_test_thread_route_ordering()
	_test_thread_backpressure_and_shutdown()
	_test_thread_reset_while_output_blocked()
	_test_thread_failure_and_utf8()
	for argument: String in OS.get_cmdline_user_args():
		if argument.begins_with("--fixture="):
			_test_actual_city_fixture(argument.trim_prefix("--fixture="))
		if argument.begins_with("--wire-fixture="):
			_test_raw_worker_stream(argument.trim_prefix("--wire-fixture="))
	if failures.is_empty():
		print("GODOT_SCENE_ADAPTER_TESTS_OK complete state parity, identities, legacy, threaded decode, reliable ordering, generation reset, bounded queues, shutdown, UTF-8 fragments")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _scene() -> Dictionary:
	return {"type":"scene", "protocol_version":1, "session_id":"one", "snapshot_encoding":Adapter.ENCODING, "scenario":{"residents":[{"id":"alice", "label":"Alice", "home_id":"home", "color":[1,0,0]}, {"id":"bob", "label":"Bob", "home_id":"home", "color":[0,0,1]}], "buildings":[{"id":"home", "label":"Home", "footprint":[[0,0,0],[1,0,0],[0,1,0]]}]}}

func _person(id: String) -> Dictionary:
	return {"id":id, "activity":"home", "building_id":"home", "position":[0,0,0], "heading":0, "visible":false, "moving":false, "trip":null, "blocked_reason":null}

func _snapshot() -> Dictionary:
	return {"type":"snapshot", "protocol_version":1, "session_id":"one", "sequence":1, "tick":0, "paused":true, "encoding":Adapter.ENCODING, "residents":[_person("bob"),_person("alice")], "buildings":[{"id":"home", "occupancy":2, "resident_ids":["alice","bob"]}]}

func _test_complete_reconstruction() -> void:
	var adapter = Adapter.new()
	adapter.apply_scene(_scene())
	var state: Dictionary = adapter.expand_snapshot(_snapshot())
	if state.is_empty():
		failures.append(adapter.error_message)
		return
	var expected: Dictionary = _snapshot()
	expected.erase("encoding")
	expected.residents[0].merge(_scene().scenario.residents[1])
	expected.residents[1].merge(_scene().scenario.residents[0])
	expected.buildings[0].merge(_scene().scenario.buildings[0])
	if state != expected: failures.append("Reconstructed state differs from complete authoritative records.")
	if state.residents.size() != 2 or state.residents[0].id != "bob" or state.residents[0].visible:
		failures.append("Reconstruction lost reorder or indoor identity.")
	state.residents[0]["label"] = "consumer local edit"
	if adapter.expand_snapshot(_snapshot()).residents[0].label != "Bob":
		failures.append("A reconstructed top-level edit mutated static metadata.")

func _test_invalid_membership() -> void:
	var adapter = Adapter.new()
	adapter.apply_scene(_scene())
	for mode: String in ["missing", "duplicate", "unknown", "field", "static_override"]:
		var state: Dictionary = _snapshot()
		match mode:
			"missing": state.residents.pop_back()
			"duplicate": state.residents[0] = state.residents[1].duplicate(true)
			"unknown": state.residents[0].id = "unregistered"
			"field": state.residents[0].erase("activity")
			"static_override": state.residents[0]["label"] = "unexpected static field"
		if not adapter.expand_snapshot(state).is_empty() or adapter.error_message.is_empty():
			failures.append("Invalid compact state was accepted: " + mode)
	var duplicate_scene: Dictionary = _scene()
	duplicate_scene.scenario.residents.append(duplicate_scene.scenario.residents[0])
	if adapter.apply_scene(duplicate_scene) or not adapter.resident_metadata.is_empty():
		failures.append("Duplicate metadata was accepted or retained after failure.")

func _test_session_and_legacy() -> void:
	var adapter = Adapter.new()
	adapter.apply_scene(_scene())
	var second: Dictionary = _scene()
	second.session_id = "two"
	second.scenario.residents[1].label = "New Bob"
	adapter.apply_scene(second)
	if not adapter.expand_snapshot(_snapshot()).is_empty(): failures.append("Old session reused replacement metadata.")
	var state: Dictionary = _snapshot()
	state.session_id = "two"
	if adapter.expand_snapshot(state).residents[0].label != "New Bob": failures.append("Replacement scene did not replace metadata.")
	adapter.clear()
	if not adapter.expand_snapshot(state).is_empty(): failures.append("Reconnect retained metadata before scene.")
	state.erase("encoding")
	if adapter.expand_snapshot(state) != state: failures.append("Legacy full state was altered.")
	if not adapter.apply_scene({"type":"scene", "session_id":"legacy", "scenario":{}}): failures.append("Legacy scene was rejected.")

func _test_client_application() -> void:
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var received: Array = []
	client.snapshot_received.connect(func(message: Dictionary) -> void: received.append(message))
	client._receive(JSON.stringify(_scene()))
	client._receive(JSON.stringify(_snapshot()))
	client._receive(JSON.stringify(_snapshot()))
	if received.size() != 1 or received[0].residents[0].label != "Bob" or received[0].has("encoding"):
		failures.append("Client failed to expand once before presenter delivery.")
	client._failure("fixture disconnect")
	if client.decoder.stats().resident_count != 0: failures.append("Disconnect retained metadata cache.")
	client.queue_free()

func _test_reliable_trip_geometry() -> void:
	var adapter = Adapter.new()
	var scene: Dictionary = _scene()
	scene.snapshot_encoding = Adapter.ROUTES_ENCODING
	adapter.apply_scene(scene)
	var state: Dictionary = _snapshot()
	state.encoding = Adapter.ROUTES_ENCODING
	state.residents[0].trip = {"id":"bob-outbound", "segment_index":0, "segment_progress":0.5, "departure_tick":0, "arrival_tick":200, "origin_id":"home", "destination_id":"office"}
	var geometry: Dictionary = {"id":"bob-outbound", "points":[[0,0,0],[1,0,0]], "node_ids":["a","b"], "length_m":1.0}
	var definitions: Dictionary = {"type":"trip_geometries", "protocol_version":1, "session_id":"one", "geometries":[geometry]}
	if not adapter.expand_snapshot(state).is_empty(): failures.append("Trip reference was accepted before geometry.")
	if not adapter.apply_trip_geometries(definitions): failures.append("Valid reliable geometry was rejected.")
	var expanded: Dictionary = adapter.expand_snapshot(state)
	if expanded.is_empty() or expanded.residents[0].trip.points != geometry.points or expanded.residents[0].trip.segment_progress != 0.5:
		failures.append("Reliable geometry did not reconstruct the authoritative trip.")
	if adapter.apply_trip_geometries(definitions): failures.append("Duplicate trip definition was accepted.")
	if not adapter.forget_trip_geometries({"session_id":"one", "ids":["bob-outbound"]}): failures.append("Inactive route eviction failed.")
	if not adapter.trip_geometries.is_empty() or adapter.trip_geometry_bytes != 0: failures.append("Eviction did not release cache capacity.")
	if expanded.residents[0].trip.points != geometry.points: failures.append("Eviction changed a previously reconstructed snapshot.")
	if not adapter.expand_snapshot(state).is_empty(): failures.append("Evicted route reference was accepted without a new definition.")
	scene.session_id = "two"
	adapter.apply_scene(scene)
	state.session_id = "two"
	if not adapter.expand_snapshot(state).is_empty() or not adapter.trip_geometries.is_empty(): failures.append("New scene retained old route geometry.")
	definitions.session_id = "two"
	if adapter.apply_trip_geometries(definitions, Adapter.MAX_TRIP_GEOMETRY_BYTES + 1) or not adapter.trip_geometries.is_empty():
		failures.append("Oversized route cache was accepted or partially updated.")

func _rows(state: Dictionary) -> Dictionary:
	var message: Dictionary = state.duplicate(true)
	message.encoding = Adapter.ROWS_ENCODING
	var people: Array = []
	for person: Dictionary in state.residents:
		var trip: Variant = person.trip
		if trip != null:
			trip = [trip.id, trip.segment_index, trip.segment_progress, trip.departure_tick, trip.arrival_tick, trip.origin_id, trip.destination_id]
		people.append([person.id, person.activity, person.building_id, person.position, person.heading, person.visible, person.moving, trip, person.blocked_reason])
	message.residents = people
	var buildings: Array = []
	for building: Dictionary in state.buildings:
		buildings.append([building.id, building.occupancy, building.resident_ids])
	message.buildings = buildings
	return message

func _test_rows() -> void:
	var adapter = Adapter.new()
	var scene: Dictionary = _scene()
	scene.snapshot_encoding = Adapter.ROUTES_ENCODING
	adapter.apply_scene(scene)
	var state: Dictionary = _snapshot()
	state.encoding = Adapter.ROUTES_ENCODING
	state.residents[0].trip = {"id":"bob-outbound", "segment_index":0, "segment_progress":0.1234567890123456, "departure_tick":0, "arrival_tick":200, "origin_id":"home", "destination_id":"office"}
	var definitions: Dictionary = {"type":"trip_geometries", "protocol_version":1, "session_id":"one", "geometries":[{"id":"bob-outbound", "points":[[0,0,0],[1,0,0]], "node_ids":["a","b"], "length_m":1.0}]}
	adapter.apply_trip_geometries(definitions)
	var expected: Dictionary = adapter.expand_snapshot(state)
	scene.snapshot_encoding = Adapter.ROWS_ENCODING
	adapter.apply_scene(scene)
	if not adapter.expand_snapshot(_rows(state)).is_empty(): failures.append("Row trip referenced unknown geometry.")
	adapter.apply_trip_geometries(definitions)
	var expanded: Dictionary = adapter.expand_snapshot(_rows(state))
	if expanded != expected: failures.append("Rows changed exact expanded state or resident order.")
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var delivered: Array = []
	client.snapshot_received.connect(func(message: Dictionary) -> void: delivered.append(message))
	for message: Dictionary in [scene, definitions, _rows(state), {"type":"ack", "request_id":"step", "tick":0}]:
		var packet: PackedByteArray = (JSON.stringify(message, "", true, true) + "\n").to_utf8_buffer()
		client.incoming.append_array(packet.slice(0, 3))
		client._drain_incoming()
		client.incoming.append_array(packet.slice(3))
		client._drain_incoming()
	if not client._flush_decoder_for_tests() or delivered.size() != 1 or delivered[0] != JSON.parse_string(JSON.stringify(expected, "", true, true)):
		failures.append("Fragmented threaded row delivery differs from full state: " + client.last_error)
	client.free()
	adapter.forget_trip_geometries({"session_id":"one", "ids":["bob-outbound"]})
	if not adapter.expand_snapshot(_rows(state)).is_empty() or expanded != expected: failures.append("Row eviction retained an active definition or mutated a delivered state.")
	scene.session_id = "two"
	adapter.apply_scene(scene)
	if not adapter.expand_snapshot(_rows(state)).is_empty(): failures.append("Rows crossed a scene session boundary.")

func _test_invalid_rows() -> void:
	var scene: Dictionary = _scene()
	scene.snapshot_encoding = Adapter.ROWS_ENCODING
	var adapter = Adapter.new()
	adapter.apply_scene(scene)
	var cases: Array = []
	for row: Variant in [null, {}, [], ["bob"], ["bob","home","home",[0,0,0],0,false,false,null,null,"extra"], ["unknown","home","home",[0,0,0],0,false,false,null,null]]:
		var state: Dictionary = _rows(_snapshot())
		state.residents[0] = row
		cases.append(state)
	for index: int in [1,2,3,4,5,6,7,8]:
		var state: Dictionary = _rows(_snapshot())
		state.residents[0][index] = {"bad":"type"}
		cases.append(state)
	for row: Variant in [["home",-1,[]], ["home",1.5,["bob"]], ["home",1,["missing"]], ["home",2,["bob","bob"]], ["home",2,["bob"]]]:
		var state: Dictionary = _rows(_snapshot())
		state.buildings[0] = row
		cases.append(state)
	var duplicate: Dictionary = _rows(_snapshot())
	duplicate.residents[0] = duplicate.residents[1]
	cases.append(duplicate)
	var short: Dictionary = _rows(_snapshot())
	short.residents.pop_back()
	cases.append(short)
	for bad: Dictionary in cases:
		if not adapter.expand_snapshot(bad).is_empty() or adapter.error_message.is_empty(): failures.append("Malformed row was accepted.")
	if adapter.expand_snapshot(_rows(_snapshot())).is_empty(): failures.append("Malformed row mutated the scene metadata.")
	adapter.apply_trip_geometries({"session_id":"one", "geometries":[{"id":"route", "points":[[0,0,0],[1,0,0]], "node_ids":["a","b"], "length_m":1.0}]})
	for trip: Variant in [["route",0,0.5,0,200,"home"], ["route",0,-0.1,0,200,"home","work"], ["route",0,NAN,0,200,"home","work"], ["route",0.5,0.5,0,200,"home","work"], ["route",0,0.5,200,0,"home","work"], ["route",0,0.5,0,200,{},"work"]]:
		var bad: Dictionary = _rows(_snapshot())
		bad.residents[0][7] = trip
		if not adapter.expand_snapshot(bad).is_empty(): failures.append("Malformed known trip row was accepted.")
	for position: Variant in [[0,0], [0,NAN,0], [0,INF,0], [0,true,0]]:
		var bad: Dictionary = _rows(_snapshot())
		bad.residents[0][3] = position
		if not adapter.expand_snapshot(bad).is_empty(): failures.append("Malformed row coordinate was accepted.")

func _test_raw_worker_stream(directory: String) -> void:
	# Source files contain untouched real TCP frames, so there is no intermediate
	# Godot JSON serialization or decimal rounding before the production decoder.
	for mode: String in ["routes", "rows"]:
		var client = preload("res://snapshot_client.gd").new()
		root.add_child(client)
		var delivered: Array = []
		client.snapshot_received.connect(func(message: Dictionary) -> void: delivered.append(message))
		var oracle: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(directory.path_join(mode + "-fulls.json")))
		var expected: Array = []
		for envelope: Dictionary in oracle.envelopes:
			var full: Dictionary = oracle.states[str(int(envelope.tick))].duplicate(false)
			full.merge(envelope, true)
			expected.append(full)
		var stream: PackedByteArray = FileAccess.get_file_as_bytes(directory.path_join(mode + ".ndjson"))
		var offset: int = 0
		while offset < stream.size():
			var stop: int = mini(offset + 16381, stream.size())
			client.incoming.append_array(stream.slice(offset, stop))
			if not client._drain_incoming(): break
			offset = stop
			if not client._flush_decoder_for_tests(): break
		if delivered != expected: failures.append("Real TCP " + mode + " decoder parity failed: " + client.last_error + " " + _first_difference(delivered, expected))
		client.free()

func _test_actual_city_fixture(path: String) -> void:
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		failures.append("Could not read actual city transport fixture: " + path)
		return
	var adapter = Adapter.new()
	adapter.apply_scene(parsed.scene)
	if adapter.expand_snapshot(parsed.compact) != parsed.full:
		failures.append("Actual city dynamic state differs from the Python full snapshot: " + path)
	adapter.apply_scene(parsed.route_scene)
	for message: Dictionary in parsed.trip_geometries:
		if not adapter.apply_trip_geometries(message): failures.append(adapter.error_message)
	if adapter.expand_snapshot(parsed.route_snapshot) != parsed.full:
		failures.append("Actual city route-reference state differs from the Python full snapshot: " + path)
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var received: Array = []
	client.snapshot_received.connect(func(message: Dictionary) -> void: received.append(message))
	client._receive(JSON.stringify(parsed.route_scene, "", true, true))
	for message: Dictionary in parsed.trip_geometries:
		client._receive(JSON.stringify(message, "", true, true))
	client._receive(JSON.stringify(parsed.route_snapshot, "", true, true))
	# Both sides pass through Godot's fixture serializer once. Its decimal float
	# parser can shift a final ULP on reserialization, even with full_precision.
	# The direct adapter checks above compare the original Python values exactly.
	var transmitted_full: Dictionary = JSON.parse_string(JSON.stringify(parsed.full, "", true, true))
	if received.size() != 1:
		failures.append("Threaded city fixture was not delivered: " + path + " " + client.last_error)
	elif received[0] != transmitted_full:
		failures.append("Actual threaded city reconstruction differs: " + path + " " + _first_difference(received[0], transmitted_full))
	client.free()

func _first_difference(left: Variant, right: Variant, path: String = "root") -> String:
	if typeof(left) != typeof(right): return path + " type mismatch"
	if left is Dictionary:
		if left.size() != right.size(): return path + " dictionary size mismatch"
		for key: Variant in left:
			if not right.has(key): return path + " missing key " + str(key)
			if left[key] != right[key]: return _first_difference(left[key], right[key], path + "." + str(key))
	elif left is Array:
		if left.size() != right.size(): return path + " array size mismatch"
		for index: int in range(left.size()):
			if left[index] != right[index]: return _first_difference(left[index], right[index], path + "[" + str(index) + "]")
	elif left != right:
		return path + " " + str(left) + " != " + str(right)
	return "same"

func _test_client_buffer_and_pending_status() -> void:
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var received: Array = []
	var acks: Array = []
	client.snapshot_received.connect(func(message: Dictionary) -> void: received.append(message))
	client.acknowledged.connect(func(message: Dictionary) -> void: acks.append(message))
	var scene: Dictionary = {"type":"scene", "protocol_version":1, "session_id":"one", "scenario":{}, "padding":"x".repeat(client.MAX_BUFFER - 130)}
	var snapshot: Dictionary = _snapshot()
	snapshot.erase("encoding")
	var complete: PackedByteArray = (JSON.stringify(scene) + "\n" + JSON.stringify(snapshot) + "\n").to_utf8_buffer()
	if complete.size() <= client.MAX_BUFFER: failures.append("Boundary fixture did not cross the aggregate buffer limit.")
	# A partial UTF-8/JSON frame stays buffered, and completing it with the next
	# full frame is legal even when the combined buffer is larger than one frame.
	client.incoming = complete.slice(0, 77)
	if not client._drain_incoming() or not received.is_empty(): failures.append("Partial frame was applied prematurely.")
	client.incoming.append_array(complete.slice(77))
	if not client._drain_incoming() or not client._flush_decoder_for_tests() or received.size() != 1: failures.append("Legal combined frames exceeded the wrong buffer bound.")
	client.pending["save"] = 1
	client._receive(JSON.stringify({"type":"command_status", "protocol_version":1, "request_id":"save", "action":"save", "status":"pending", "elapsed_seconds":0}))
	if not client.pending.has("save") or not acks.is_empty(): failures.append("Pending save status was treated as completion.")
	client.incoming = ("x".repeat(client.MAX_BUFFER + 1)).to_utf8_buffer()
	if client._drain_incoming(): failures.append("Oversized incomplete frame was accepted.")
	client.queue_free()

func _wait_decoder(decoder: RefCounted, expected_outputs: int = -1) -> bool:
	var deadline: int = Time.get_ticks_msec() + 10000
	while Time.get_ticks_msec() < deadline:
		var state: Dictionary = decoder.stats()
		if expected_outputs >= 0 and state.output_messages >= expected_outputs:
			return true
		if expected_outputs < 0 and state.input_messages == 0 and not state.in_flight:
			return true
		OS.delay_msec(1)
	failures.append("Background fixture decoder did not reach its expected boundary.")
	return false

func _enqueue_fixture(decoder: RefCounted, message: Dictionary, generation: int = 0) -> void:
	if not decoder.enqueue(JSON.stringify(message).to_utf8_buffer(), generation):
		failures.append("Background fixture queue unexpectedly rejected a message.")

func _test_thread_ordering_and_generation() -> void:
	var decoder = preload("res://snapshot_decoder.gd").new()
	_enqueue_fixture(decoder, _scene())
	for number: int in range(1, 4):
		var snapshot: Dictionary = _snapshot()
		snapshot.sequence = number
		_enqueue_fixture(decoder, snapshot)
	_enqueue_fixture(decoder, {"type":"ack", "request_id":"pause", "tick":3})
	var fourth: Dictionary = _snapshot()
	fourth.sequence = 4
	_enqueue_fixture(decoder, fourth)
	decoder.start()
	_wait_decoder(decoder)
	var results: Array = []
	while true:
		var result: Dictionary = decoder.take()
		if result.is_empty(): break
		results.append(result)
	if results.size() != 4 or results[0].kind != "scene" or results[1].message.sequence != 3 or results[2].kind != "ack" or results[3].message.sequence != 4:
		failures.append("Thread coalescing crossed a reliable acknowledgement boundary.")
	if decoder.stats().coalesced_snapshots != 2:
		failures.append("Adjacent completed snapshots were not coalesced.")
	# Reset while results/packets from a prior connection exist; old work cannot
	# publish into the replacement generation even if it was already in flight.
	_enqueue_fixture(decoder, _scene())
	_enqueue_fixture(decoder, _snapshot())
	var generation: int = decoder.reset()
	var second: Dictionary = _scene()
	second.session_id = "replacement"
	_enqueue_fixture(decoder, second, generation)
	var replacement: Dictionary = _snapshot()
	replacement.session_id = "replacement"
	_enqueue_fixture(decoder, replacement, generation)
	_wait_decoder(decoder)
	while true:
		var result: Dictionary = decoder.take()
		if result.is_empty(): break
		if result.generation != generation or str(result.message.get("session_id", "")) != "replacement":
			failures.append("Reconnect delivered an older connection generation.")
	decoder.stop()

func _test_thread_failure_and_utf8() -> void:
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	var received: Array = []
	client.snapshot_received.connect(func(message: Dictionary) -> void: received.append(message))
	var scene: Dictionary = _scene()
	scene.scenario.residents[1].label = "Bo\u00f6b \u6771"
	var bytes: PackedByteArray = (JSON.stringify(scene) + "\n").to_utf8_buffer()
	var split: int = bytes.find(195) + 1 # Inside the two-byte UTF-8 umlaut.
	if split <= 0: failures.append("UTF-8 fixture did not contain the expected multi-byte character.")
	client.incoming = bytes.slice(0, split)
	client._drain_incoming()
	if client.decoder.stats().input_messages != 0:
		failures.append("A partial multi-byte frame reached the decoder.")
	client.incoming.append_array(bytes.slice(split))
	client._drain_incoming()
	client._flush_decoder_for_tests()
	client._receive(JSON.stringify(_snapshot()))
	if received.size() != 1 or received[0].residents[0].label != scene.scenario.residents[1].label:
		failures.append("Thread framing corrupted a split multi-byte UTF-8 character.")
	var invalid: Dictionary = _snapshot()
	invalid.sequence = 2
	invalid.residents[0].id = "unknown"
	if client._receive(JSON.stringify(invalid)) or client.last_error.is_empty() or received.size() != 1:
		failures.append("Invalid dynamic membership was delivered by the background decoder.")
	client.free()
	client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	if client._receive("{invalid") or client.last_error.is_empty():
		failures.append("Malformed JSON was not rejected by the background decoder.")
	client.free()

func _test_thread_route_ordering() -> void:
	# Route definitions and evictions must remain ordered with snapshots; a
	# previously delivered state keeps its immutable geometry after eviction.
	var decoder = preload("res://snapshot_decoder.gd").new()
	var scene: Dictionary = _scene()
	scene.snapshot_encoding = Adapter.ROUTES_ENCODING
	_enqueue_fixture(decoder, scene)
	var geometry: Dictionary = {"id":"bob-trip", "points":[[0,0,0],[2,0,0]], "node_ids":["a","b"], "length_m":2.0}
	_enqueue_fixture(decoder, {"type":"trip_geometries", "protocol_version":1, "session_id":"one", "geometries":[geometry]})
	var walking: Dictionary = _snapshot()
	walking.encoding = Adapter.ROUTES_ENCODING
	walking.residents[0].trip = {"id":"bob-trip", "segment_progress":0.25}
	_enqueue_fixture(decoder, walking)
	_enqueue_fixture(decoder, {"type":"forget_trip_geometries", "protocol_version":1, "session_id":"one", "ids":["bob-trip"]})
	var indoor: Dictionary = _snapshot()
	indoor.encoding = Adapter.ROUTES_ENCODING
	indoor.sequence = 2
	_enqueue_fixture(decoder, indoor)
	decoder.start()
	_wait_decoder(decoder)
	var results: Array = []
	while true:
		var result: Dictionary = decoder.take()
		if result.is_empty(): break
		results.append(result)
	var expected_points: Array = JSON.parse_string(JSON.stringify(geometry)).points
	if results.size() != 5 or results[2].kind != "snapshot" or results[2].message.residents[0].trip.points != expected_points or results[4].message.residents[0].trip != null:
		failures.append("Background route definitions/evictions lost ordering or full state parity.")
	if decoder.stats().trip_count != 0:
		failures.append("Background route cache did not release inactive definitions.")
	decoder.stop()

func _test_thread_backpressure_and_shutdown() -> void:
	var decoder = preload("res://snapshot_decoder.gd").new()
	var maximum := PackedByteArray()
	maximum.resize(decoder.MAX_FRAME_BYTES)
	if not decoder.enqueue(maximum, 0) or not decoder.enqueue(maximum, 0) or decoder.enqueue("x".to_utf8_buffer(), 0):
		failures.append("Decoder input byte bound did not apply backpressure.")
	decoder.stop() # Never-started threads must also dispose safely.
	decoder = preload("res://snapshot_decoder.gd").new()
	for number: int in range(decoder.MAX_OUTPUT_MESSAGES + 2):
		_enqueue_fixture(decoder, {"type":"ack", "request_id":str(number)})
	decoder.start()
	_wait_decoder(decoder, decoder.MAX_OUTPUT_MESSAGES)
	if decoder.stats().output_messages > decoder.MAX_OUTPUT_MESSAGES:
		failures.append("Reliable decoder output exceeded its count bound.")
	# The thread is waiting for output space; stop must wake and join it.
	decoder.stop()
	decoder = preload("res://snapshot_decoder.gd").new()
	for number: int in range(decoder.MAX_INPUT_MESSAGES):
		_enqueue_fixture(decoder, {"type":"ack", "request_id":str(number)})
	if decoder.enqueue("{}".to_utf8_buffer(), 0):
		failures.append("Decoder input message bound did not apply backpressure.")
	decoder.stop()
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	for number: int in range(client.decoder.MAX_INPUT_MESSAGES):
		_enqueue_fixture(client.decoder, {"type":"ack", "request_id":str(number)})
	var framed: PackedByteArray = (JSON.stringify(_scene()) + "\n").to_utf8_buffer()
	client.incoming = framed
	if not client._drain_incoming() or client.incoming != framed:
		failures.append("Input backpressure discarded or partially consumed a complete frame.")
	client.free()

func _test_thread_reset_while_output_blocked() -> void:
	var decoder = preload("res://snapshot_decoder.gd").new()
	_enqueue_fixture(decoder, _scene())
	for number: int in range(1, decoder.MAX_OUTPUT_SNAPSHOTS + 2):
		var snapshot: Dictionary = _snapshot()
		snapshot.sequence = number
		_enqueue_fixture(decoder, snapshot)
		_enqueue_fixture(decoder, {"type":"ack", "request_id":str(number)})
	decoder.start()
	_wait_decoder(decoder, 1 + 2 * decoder.MAX_OUTPUT_SNAPSHOTS)
	if decoder.stats().output_snapshots != decoder.MAX_OUTPUT_SNAPSHOTS:
		failures.append("Reconstructed snapshot count exceeded its heap bound.")
	var generation: int = decoder.reset()
	var scene: Dictionary = _scene()
	scene.session_id = "after-backpressure"
	_enqueue_fixture(decoder, scene, generation)
	_wait_decoder(decoder)
	var replacement: Dictionary = decoder.take()
	if replacement.is_empty() or replacement.generation != generation or replacement.kind != "scene" or replacement.message.session_id != "after-backpressure" or not decoder.take().is_empty():
		failures.append("Reset did not release output backpressure and reject old in-flight work.")
	decoder.stop()

func _test_command_rejection_severity() -> void:
	var client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	client.connected = true
	client.session_id = "fixture"
	var app = preload("res://main.gd").new()
	app.startup_complete = true
	app.client = client
	app.hud = preload("res://hud.gd").new()
	root.add_child(app.hud)
	app.diagnostics = RejectionDiagnostics.new()
	root.add_child(app.diagnostics)
	var warnings: Array[Dictionary] = []
	var statuses: Array[bool] = []
	client.command_rejected.connect(func(message: Dictionary) -> void: warnings.append(message))
	client.command_rejected.connect(app._command_rejected)
	client.status_changed.connect(app._connection_status)
	client.status_changed.connect(func(_message: String,fatal: bool) -> void: statuses.append(fatal))
	client.acknowledged.connect(app._acknowledged)
	var request: String = client.command("set_population",5000,0)
	var rejection: Dictionary = {"type":"error","protocol_version":1,"request_id":request,"code":"invalid_command","message":"Requested population exceeds the current route-data limit.","session_id":"fixture"}
	if not client._receive(JSON.stringify(rejection)): failures.append("Recognized pending command rejection failed decoding.")
	if warnings.size() != 1 or warnings[0].action != "set_population" or statuses.back() or not client.connected: failures.append("Pending rejection lost action metadata or became a fatal/disconnecting error.")
	if not app.last_error.is_empty() or not str(app.run_metrics().error).is_empty() or not app.ack_results.has(request): failures.append("Rejected command poisoned recurring application metrics or lost its acknowledgement.")
	client._receive(JSON.stringify(rejection))
	if warnings.size() != 1: failures.append("Exact duplicate rejection emitted another warning.")
	var next: String = client.command("pause",true)
	client._receive(JSON.stringify({"type":"ack","protocol_version":1,"request_id":next,"action":"pause","session_id":"fixture","tick":1}))
	if next.is_empty() or client.pending.has(next) or app.ack_results.get(next,{}).get("type") != "ack": failures.append("A rejected command prevented a later acknowledged command.")
	var auth_request: String = client.command("pause",true)
	client._receive(JSON.stringify({"type":"error","protocol_version":1,"request_id":auth_request,"code":"authentication_failed","message":"Invalid authentication."}))
	if not statuses.back() or app.last_error.is_empty() or warnings.size() != 1: failures.append("Authentication error was downgraded because it carried a pending request ID.")
	client._receive(JSON.stringify({"type":"error","protocol_version":1,"request_id":"unknown","code":"invalid_command","message":"Unknown response."}))
	if not statuses.back() or warnings.size() != 1: failures.append("Unknown request error was downgraded to a command warning.")
	if client._receive("{invalid") or client.last_error.is_empty() or client.connected: failures.append("Malformed transport data no longer fails the connection.")
	app.hud.queue_free()
	app.diagnostics.queue_free()
	app.free()
	client.queue_free()
