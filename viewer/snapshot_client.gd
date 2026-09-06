extends Node
## Loopback newline JSON transport. No blocking read or unbounded message queue.

signal scene_received(message: Dictionary)
signal snapshot_received(message: Dictionary)
signal acknowledged(message: Dictionary)
signal status_changed(message: String, is_error: bool)

const MAX_BUFFER: int = 16 * 1024 * 1024
const MAX_FRAME_READ: int = 1024 * 1024
const CONNECT_TIMEOUT: float = 10.0
const SceneAdapter = preload("res://scene_adapter.gd")
const Decoder = preload("res://snapshot_decoder.gd")
var decoder = Decoder.new()
var generation: int = 0
var peer := StreamPeerTCP.new()
var incoming := PackedByteArray()
var outgoing := PackedByteArray()
var connected: bool = false
var active: bool = false
var hello_sent: bool = false
var host: String = "127.0.0.1"
var port: int = 0
var token: String = ""
var started_at: float = 0.0
var last_received_at: float = 0.0
var session_id: String = ""
var sequence: int = -1
var request_number: int = 0
var pending: Dictionary = {}
var last_process_ms: float = 0.0
var last_parse_ms: float = 0.0 # Main-thread framing and synchronous delivery only.
var last_json_decode_ms: float = 0.0 # Background CPU completed/delivered this frame.
var last_expand_ms: float = 0.0 # Background CPU completed/delivered this frame.
var last_delivery_ms: float = 0.0
var last_error: String = ""
var requested_encoding: String = SceneAdapter.ROUTES_ENCODING
var requested_route_encoding: String = ""

func _exit_tree() -> void:
	decoder.stop()

func _notification(what: int) -> void:
	# Headless fixtures may free a client before it ever enters the SceneTree.
	if what == NOTIFICATION_PREDELETE:
		decoder.stop()

func _ensure_decoder() -> bool:
	var error: Error = decoder.start()
	if error != OK:
		_failure("Could not start the simulation decoder: " + error_string(error))
		return false
	return true

func connect_worker(address: String, number: int, secret: String) -> void:
	peer.disconnect_from_host()
	incoming.clear()
	outgoing.clear()
	pending.clear()
	generation = decoder.reset()
	last_error = ""
	host = address
	port = number
	token = secret
	connected = false
	hello_sent = false
	session_id = ""
	sequence = -1
	requested_encoding = OS.get_environment("CIVIC_SNAPSHOT_ENCODING")
	if requested_encoding.is_empty(): requested_encoding = SceneAdapter.ROUTES_ENCODING
	if requested_encoding not in [SceneAdapter.ENCODING, SceneAdapter.ROUTES_ENCODING, SceneAdapter.ROWS_ENCODING]:
		_failure("Unsupported CIVIC_SNAPSHOT_ENCODING setting.")
		return
	requested_route_encoding = OS.get_environment("CIVIC_ROUTE_GEOMETRY_ENCODING")
	if requested_route_encoding not in ["", SceneAdapter.SharedGeometry.ENCODING] or (not requested_route_encoding.is_empty() and requested_encoding == SceneAdapter.ENCODING):
		_failure("Unsupported CIVIC_ROUTE_GEOMETRY_ENCODING setting.")
		return
	started_at = Time.get_ticks_msec() / 1000.0
	last_received_at = started_at
	if host not in ["127.0.0.1", "localhost", "::1"] or port < 1 or port > 65535:
		_failure("The simulation connection must use a local address and valid port.")
		return
	var error: Error = peer.connect_to_host(host, port)
	active = error == OK
	if error != OK:
		_failure("Could not connect to the simulation: " + error_string(error))
	else:
		if not _ensure_decoder():
			return
		status_changed.emit("Connecting to local simulation...", false)

func command(action: String, value: Variant = null) -> String:
	if not connected or session_id.is_empty():
		status_changed.emit("Simulation is disconnected. Reconnect before changing playback.", true)
		return ""
	request_number += 1
	var request_id: String = "viewer-%d" % request_number
	var message: Dictionary = {"type":"command", "request_id":request_id, "action":action}
	if value != null:
		message["value"] = value
	pending[request_id] = Time.get_ticks_msec()
	_queue(message)
	return request_id

func _queue(message: Dictionary) -> void:
	var bytes: PackedByteArray = (JSON.stringify(message) + "\n").to_utf8_buffer()
	if outgoing.size() + bytes.size() > MAX_BUFFER:
		_failure("Simulation send queue exceeded its limit.")
		return
	outgoing.append_array(bytes)

func _process(_delta: float) -> void:
	var started: int = Time.get_ticks_usec()
	_poll_connection()
	last_process_ms = (Time.get_ticks_usec() - started) / 1000.0

func _poll_connection() -> void:
	last_parse_ms = 0.0
	last_json_decode_ms = 0.0
	last_expand_ms = 0.0
	last_delivery_ms = 0.0
	if not active:
		return
	peer.poll()
	var status: int = peer.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTING:
		if Time.get_ticks_msec() / 1000.0 - started_at > CONNECT_TIMEOUT:
			_failure("Simulation connection timed out.")
		return
	if status != StreamPeerTCP.STATUS_CONNECTED:
		_failure("Simulation disconnected. Display is frozen; reconnect to recover.")
		return
	connected = true
	if not hello_sent:
		var hello: Dictionary = {"type":"hello", "protocol_version":1, "token":token, "snapshot_encoding":requested_encoding, "command_status":true}
		if not requested_route_encoding.is_empty(): hello["route_geometry_encoding"] = requested_route_encoding
		_queue(hello)
		hello_sent = true
	if not outgoing.is_empty():
		var sent: Array = peer.put_partial_data(outgoing)
		if int(sent[0]) != OK:
			_failure("Could not send a simulation command.")
			return
		outgoing = outgoing.slice(int(sent[1]))
	# Deliver at most one complete render state per frame. Commands above always
	# reach the socket even when decoding or presentation is behind.
	if not _drain_decoded():
		return
	if not _drain_incoming():
		return
	# Backpressure retains exact framed bytes and lets the TCP receive window
	# throttle the worker. Reliable messages are never discarded to make room.
	var available: int = 0
	if incoming.find(10) < 0 and decoder.can_accept(MAX_FRAME_READ):
		available = mini(peer.get_available_bytes(), MAX_FRAME_READ)
	if available > 0:
		var result: Array = peer.get_partial_data(available)
		if int(result[0]) != OK:
			_failure("Could not read simulation data.")
			return
		incoming.append_array(result[1])
		last_received_at = Time.get_ticks_msec() / 1000.0
		# One read may finish a maximum-size frame and also contain the start
		# of the following frame. Bound storage separately from frame length.
		if incoming.size() > MAX_BUFFER + MAX_FRAME_READ:
			_failure("Simulation message exceeded the 16 MB safety limit.")
			return
	if not _drain_incoming():
		return
	if Time.get_ticks_msec() / 1000.0 - last_received_at > 10.0:
		_failure("No simulation updates for 10 seconds. Display is frozen; reconnect to recover.")

func _drain_incoming() -> bool:
	var started: int = Time.get_ticks_usec()
	var result: bool = _drain_frames()
	last_parse_ms += (Time.get_ticks_usec() - started) / 1000.0
	return result

func _drain_frames() -> bool:
	# Frame bytes only. UTF-8 conversion, JSON and metadata stay off the UI thread.
	var cursor: int = 0
	var processed: int = 0
	while processed < 256:
		var newline: int = incoming.find(10, cursor)
		if newline < 0:
			break
		if newline - cursor > MAX_BUFFER:
			_failure("Simulation frame exceeded the 16 MiB limit.")
			return false
		if newline > cursor:
			if not decoder.can_accept(newline - cursor):
				break
			if not _ensure_decoder():
				return false
			if not decoder.enqueue(incoming.slice(cursor, newline), generation):
				break
		cursor = newline + 1
		processed += 1
	if cursor > 0:
		incoming = incoming.slice(cursor)
	if incoming.size() > MAX_BUFFER and incoming.find(10) < 0:
		_failure("Simulation frame exceeded the 16 MiB limit.")
		return false
	return true

func _receive(line: String) -> bool:
	# Synchronous fixture injection through the real thread. Production framing
	# calls enqueue directly and never waits for decoding.
	if not _ensure_decoder() or not decoder.enqueue(line.to_utf8_buffer(), generation):
		return false
	return _flush_decoder_for_tests()

func _flush_decoder_for_tests(timeout_ms: int = 10000) -> bool:
	var deadline: int = Time.get_ticks_msec() + timeout_ms
	while Time.get_ticks_msec() < deadline:
		if not _drain_decoded(256):
			return false
		var state: Dictionary = decoder.stats()
		if state.input_messages == 0 and state.output_messages == 0 and not state.in_flight:
			return last_error.is_empty()
		OS.delay_msec(1)
	_failure("Fixture decoder did not become idle before its deadline.")
	return false

func _drain_decoded(snapshot_budget: int = 1) -> bool:
	var started: int = Time.get_ticks_usec()
	var snapshots: int = 0
	for _index: int in range(256):
		var result: Dictionary = decoder.take()
		if result.is_empty():
			break
		if int(result.generation) != generation:
			continue
		last_json_decode_ms += float(result.json_ms)
		last_expand_ms += float(result.expand_ms)
		if not _deliver(result):
			return false
		if result.kind == "snapshot":
			snapshots += 1
			if snapshots >= snapshot_budget:
				break
	last_parse_ms += (Time.get_ticks_usec() - started) / 1000.0
	return true

func _deliver(result: Dictionary) -> bool:
	var message: Dictionary = result.message
	match str(result.kind):
		"scene":
			session_id = str(message.session_id)
			sequence = -1
			scene_received.emit(message)
			status_changed.emit("Live local simulation", false)
		"snapshot":
			if str(message.get("session_id", "")) != session_id:
				return true
			var next_sequence: int = int(message.get("sequence", -1))
			if next_sequence <= sequence:
				return true
			sequence = next_sequence
			var delivery_started: int = Time.get_ticks_usec()
			snapshot_received.emit(message)
			last_delivery_ms += (Time.get_ticks_usec() - delivery_started) / 1000.0
		"ack":
			pending.erase(str(message.get("request_id", "")))
			acknowledged.emit(message)
		"command_status":
			var label: String = {"save":"Saving day", "load":"Loading saved day", "population":"Preparing residents"}.get(str(message.get("action", "")), "Preparing simulation")
			status_changed.emit("%s… %.0fs" % [label, float(message.get("elapsed_seconds", 0.0))], false)
		"geometry_status":
			if str(message.get("session_id", "")) == session_id:
				var label: String = {"preparing":"Preparing route geometry", "streaming":"Loading route geometry", "ready":"Live local simulation"}.get(str(message.get("status", "")), "Loading route geometry")
				status_changed.emit(label, false)
		"error":
			pending.erase(str(message.get("request_id", "")))
			status_changed.emit(str(message.get("message", message.get("error", "Simulation rejected a request."))), true)
			acknowledged.emit(message)
		"failure":
			_failure(str(message.message))
			return false
	return true

func _failure(message: String) -> void:
	active = false
	connected = false
	peer.disconnect_from_host()
	incoming.clear()
	outgoing.clear()
	pending.clear()
	generation = decoder.reset()
	session_id = ""
	sequence = -1
	last_error = message
	status_changed.emit(message, true)
