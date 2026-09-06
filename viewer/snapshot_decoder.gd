extends RefCounted
## Private JSON/metadata worker. Only immutable packets/results cross the mutex.
## No Node, SceneTree, socket, signal or rendering API is used on this thread.

const Adapter = preload("res://scene_adapter.gd")
const MAX_FRAME_BYTES: int = 16 * 1024 * 1024
const MAX_INPUT_BYTES: int = 32 * 1024 * 1024
const MAX_OUTPUT_BYTES: int = 32 * 1024 * 1024
const MAX_INPUT_MESSAGES: int = 256
const MAX_OUTPUT_MESSAGES: int = 64
const MAX_OUTPUT_SNAPSHOTS: int = 4

var _thread := Thread.new()
var _mutex := Mutex.new()
var _work := Semaphore.new()
var _space := Semaphore.new()
var _input: Array[Dictionary] = []
var _output: Array[Dictionary] = []
var _input_bytes: int = 0
var _output_bytes: int = 0
var _output_snapshots: int = 0
var _generation: int = 0
var _stopping: bool = false
var _in_flight: bool = false
var _coalesced: int = 0
var _resident_count: int = 0
var _building_count: int = 0
var _trip_count: int = 0
var _point_count: int = 0
var _route_encoding: String = ""

func start() -> Error:
	if _thread.is_started():
		return OK
	return _thread.start(_run)

func reset() -> int:
	# Old work may finish parsing, but generation checks prevent its publication.
	# Release old large results outside the queue mutex.
	_mutex.lock()
	_generation += 1
	var retired_input: Array[Dictionary] = _input
	var retired_output: Array[Dictionary] = _output
	_input = [{"generation":_generation, "reset":true, "bytes":PackedByteArray()}]
	_output = []
	_input_bytes = 0
	_output_bytes = 0
	_output_snapshots = 0
	_resident_count = 0
	_building_count = 0
	_trip_count = 0
	_point_count = 0
	_route_encoding = ""
	var result: int = _generation
	_mutex.unlock()
	_work.post()
	_space.post()
	retired_input.clear()
	retired_output.clear()
	return result

func can_accept(byte_count: int) -> bool:
	_mutex.lock()
	var result: bool = not _stopping and byte_count <= MAX_FRAME_BYTES and _input_bytes + byte_count <= MAX_INPUT_BYTES and _input.size() < MAX_INPUT_MESSAGES
	_mutex.unlock()
	return result

func enqueue(bytes: PackedByteArray, generation: int) -> bool:
	_mutex.lock()
	if _stopping or generation != _generation or bytes.size() > MAX_FRAME_BYTES or _input_bytes + bytes.size() > MAX_INPUT_BYTES or _input.size() >= MAX_INPUT_MESSAGES:
		_mutex.unlock()
		return false
	_input.append({"generation":generation, "bytes":bytes})
	_input_bytes += bytes.size()
	_mutex.unlock()
	_work.post()
	return true

func take() -> Dictionary:
	_mutex.lock()
	if _output.is_empty():
		_mutex.unlock()
		return {}
	var result: Dictionary = _output.pop_front()
	_output_bytes -= int(result.charge)
	if result.kind == "snapshot":
		_output_snapshots -= 1
	_mutex.unlock()
	_space.post()
	return result

func stats() -> Dictionary:
	_mutex.lock()
	var result: Dictionary = {"generation":_generation, "input_messages":_input.size(), "input_bytes":_input_bytes, "output_messages":_output.size(), "output_bytes":_output_bytes, "output_snapshots":_output_snapshots, "in_flight":_in_flight, "coalesced_snapshots":_coalesced, "resident_count":_resident_count, "building_count":_building_count, "trip_count":_trip_count, "point_count":_point_count, "route_geometry_encoding":_route_encoding}
	_mutex.unlock()
	return result

func stop() -> void:
	_mutex.lock()
	_stopping = true
	_generation += 1
	_mutex.unlock()
	_work.post()
	_space.post()
	if _thread.is_started():
		_thread.wait_to_finish()
	_input.clear()
	_output.clear()

func _run() -> void:
	# Adapter and session variables belong exclusively to this thread.
	var adapter = Adapter.new()
	var generation: int = -1
	var session: String = ""
	var sequence: int = -1
	var failed: bool = false
	while true:
		_work.wait()
		_mutex.lock()
		if _stopping:
			_mutex.unlock()
			break
		if _input.is_empty():
			_mutex.unlock()
			continue
		var packet: Dictionary = _input.pop_front()
		_input_bytes -= packet.bytes.size()
		_in_flight = true
		_mutex.unlock()
		if generation != int(packet.generation):
			adapter.clear()
			generation = int(packet.generation)
			session = ""
			sequence = -1
			failed = false
		if not packet.get("reset", false) and not failed:
			var result: Dictionary = _decode(packet.bytes, adapter, session, sequence)
			result["generation"] = generation
			if result.kind == "scene":
				session = str(result.message.session_id)
				sequence = -1
			elif result.kind == "snapshot":
				sequence = int(result.message.sequence)
			elif result.kind == "failure":
				failed = true
			_publish(result)
		_mutex.lock()
		_in_flight = false
		if generation == _generation:
			_resident_count = adapter.resident_metadata.size()
			_building_count = adapter.building_metadata.size()
			_trip_count = adapter.trip_geometries.size()
			_point_count = adapter.shared_geometry.points.size() if adapter.shared_geometry != null else 0
			_route_encoding = adapter.route_encoding
		_mutex.unlock()
	adapter.clear()

func _decode(bytes: PackedByteArray, adapter: RefCounted, session: String, sequence: int) -> Dictionary:
	var started: int = Time.get_ticks_usec()
	var parser := JSON.new()
	var parsed: Error = parser.parse(bytes.get_string_from_utf8())
	var result: Dictionary = {"kind":"barrier", "message":{}, "charge":bytes.size(), "json_ms":(Time.get_ticks_usec() - started) / 1000.0, "expand_ms":0.0}
	if parsed != OK or not parser.data is Dictionary:
		return _invalid(result, "Simulation sent invalid JSON.")
	var message: Dictionary = parser.data
	var kind: String = str(message.get("type", ""))
	match kind:
		"scene":
			if int(message.get("protocol_version", -1)) != 1 or str(message.get("session_id", "")).is_empty():
				return _invalid(result, "Unsupported simulation protocol or missing session identity.")
			started = Time.get_ticks_usec()
			var accepted: bool = adapter.apply_scene(message)
			result.expand_ms = (Time.get_ticks_usec() - started) / 1000.0
			if not accepted:
				return _invalid(result, adapter.error_message)
			result.kind = kind
			result.message = message
		"trip_geometries", "forget_trip_geometries":
			if int(message.get("protocol_version", -1)) != 1:
				return _invalid(result, "Trip geometry protocol does not match the viewer.")
			if str(message.get("session_id", "")) == session:
				started = Time.get_ticks_usec()
				var accepted: bool = adapter.apply_trip_geometries(message, bytes.size() + 1) if kind == "trip_geometries" else adapter.forget_trip_geometries(message)
				result.expand_ms = (Time.get_ticks_usec() - started) / 1000.0
				if not accepted:
					return _invalid(result, adapter.error_message)
			# A lightweight output barrier keeps snapshot coalescing from crossing
			# reliable cache mutations. Parsed definitions stay in the adapter.
			result.charge = 0
		"route_coordinate_pool", "trip_geometry_indices":
			if str(message.get("session_id", "")) == session:
				started = Time.get_ticks_usec()
				var accepted: bool = adapter.apply_shared_geometry(message, bytes.size() + 1)
				result.expand_ms = (Time.get_ticks_usec() - started) / 1000.0
				if not accepted: return _invalid(result, adapter.error_message)
			result.charge = 0
		"geometry_status":
			if message.get("protocol_version") != 1 or str(message.get("status", "")) not in ["preparing", "streaming", "ready"]:
				return _invalid(result, "Invalid route preparation status.")
			if str(message.get("session_id", "")) == session:
				result.kind = kind
				result.message = message
		"snapshot":
			if int(message.get("protocol_version", -1)) != 1:
				return _invalid(result, "Snapshot protocol does not match the viewer.")
			if str(message.get("session_id", "")) != session or int(message.get("sequence", -1)) <= sequence:
				result.charge = 0
				return result
			if not message.get("residents") is Array or not message.get("buildings") is Array:
				return _invalid(result, "Incomplete simulation snapshot.")
			started = Time.get_ticks_usec()
			var expanded: Dictionary = adapter.expand_snapshot(message)
			result.expand_ms = (Time.get_ticks_usec() - started) / 1000.0
			if expanded.is_empty():
				return _invalid(result, adapter.error_message)
			result.kind = kind
			result.message = expanded
		"ack", "error":
			result.kind = kind
			result.message = message
		"command_status":
			if int(message.get("protocol_version", -1)) != 1 or str(message.get("status", "")) not in ["pending", "running"]:
				return _invalid(result, "Invalid background command status.")
			result.kind = kind
			result.message = message
		_:
			return _invalid(result, "Simulation sent an unknown message type.")
	return result

func _invalid(result: Dictionary, explanation: String) -> Dictionary:
	result.kind = "failure"
	result.message = {"message":explanation}
	result.charge = 0
	return result

func _publish(result: Dictionary) -> void:
	while true:
		_mutex.lock()
		if _stopping or int(result.generation) != _generation:
			_mutex.unlock()
			return
		var retired: Dictionary = {}
		# Adjacent completed snapshots are replaceable; every other result is
		# a reliable ordering boundary, including definitions and evictions.
		var replacing: bool = result.kind == "snapshot" and not _output.is_empty() and _output.back().kind == "snapshot" and _output.back().message.session_id == result.message.session_id
		var replaced_bytes: int = int(_output.back().charge) if replacing else 0
		var snapshots: int = _output_snapshots + (1 if result.kind == "snapshot" and not replacing else 0)
		if _output_bytes - replaced_bytes + int(result.charge) <= MAX_OUTPUT_BYTES and (_output.size() < MAX_OUTPUT_MESSAGES or replacing) and snapshots <= MAX_OUTPUT_SNAPSHOTS:
			if replacing:
				retired = _output.pop_back()
				_output_bytes -= int(retired.charge)
				result.json_ms += float(retired.json_ms)
				result.expand_ms += float(retired.expand_ms)
				_coalesced += 1
			_output.append(result)
			_output_bytes += int(result.charge)
			_output_snapshots = snapshots
			_mutex.unlock()
			retired.clear()
			return
		_mutex.unlock()
		# Stop/reset and main-thread result consumption all wake this wait.
		_space.wait()
