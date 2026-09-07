extends SceneTree
const Client = preload("res://telemetry_client.gd")
var failures: Array[String] = []
var rows: Array[Dictionary] = []
var server := TCPServer.new()
var client
var remote: StreamPeerTCP

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	_check(server.listen(0,"127.0.0.1") == OK,"Loopback fixture could not listen")
	client = Client.new()
	root.add_child(client)
	client.received.connect(func(row: Dictionary) -> void: rows.append(row))
	client.configure(server.get_local_port(),"fixture-secret")
	await _accept()
	if remote == null:
		_finish()
		return
	await _send_snapshot(10)
	_check(rows.size() == 1 and client.clock_synced,"Snapshot did not initialize the feed clock")
	var before: int = client.last_message_msec
	await create_timer(0.025).timeout
	_send({"kind":"heartbeat","sequence":10,"payload":{}})
	await _frames(4)
	_check(client.last_message_msec > before and rows.size() == 1,"Duplicate-sequence heartbeat did not refresh freshness")
	_send({"kind":"log","sequence":10,"payload":{"message":"duplicate"}})
	await _frames(4)
	_check(rows.size() == 1,"Duplicate event was delivered")
	# A single JSON line can arrive across frames.
	var frame: PackedByteArray = _frame({"kind":"log","sequence":11,"payload":{"message":"fragmented"}})
	remote.put_data(frame.slice(0,12))
	await _frames(3)
	_check(rows.size() == 1,"Incomplete JSON frame was delivered")
	remote.put_data(frame.slice(12))
	await _frames(4)
	_check(rows.size() == 2 and rows.back().payload.message == "fragmented","Fragmented frame was lost")
	remote.disconnect_from_host()
	await _frames(4)
	_check(not client.active,"Disconnected feed was treated as active")
	client._connect()
	await _accept()
	await _send_snapshot(11)
	_check(rows.size() == 3 and client.clock_synced,"Reconnect skipped a snapshot at the previous sequence")
	var oversized := PackedByteArray()
	oversized.resize(Client.MAX_BYTES+65536)
	oversized.fill(65)
	remote.put_data(oversized)
	await _frames(20)
	_check(not client.active and client.incoming.is_empty(),"Oversized feed buffer was not rejected and cleared")
	_finish()

func _accept() -> void:
	remote = null
	for index: int in range(120):
		if server.is_connection_available():
			remote = server.take_connection()
			await _frames(3)
			remote.poll()
			if remote.get_available_bytes() > 0:
				var hello: String = remote.get_utf8_string(remote.get_available_bytes())
				_check('"hello"' in hello and '"fixture-secret"' in hello,"Authenticated hello was not sent")
			return
		await process_frame
	_check(false,"Client connection timed out")

func _send_snapshot(sequence: int) -> void:
	_send({"kind":"snapshot","sequence":sequence,"payload":{"clock":{"launcher_monotonic_seconds":500.0},"status":{},"hardware":{},"logs":[]}})
	await _frames(5)

func _frame(fields: Dictionary) -> PackedByteArray:
	var message: Dictionary = {"type":"telemetry","schema_version":1,"run_id":"fixture-run"}
	message.merge(fields)
	return (JSON.stringify(message)+"\n").to_utf8_buffer()

func _send(fields: Dictionary) -> void:
	remote.put_data(_frame(fields))

func _frames(count: int) -> void:
	for index: int in range(count): await process_frame

func _check(condition: bool, message: String) -> void:
	if not condition: failures.append(message)

func _finish() -> void:
	if remote != null: remote.disconnect_from_host()
	server.stop()
	if client != null: client.queue_free()
	if failures.is_empty(): print("GODOT_TELEMETRY_CLIENT_TESTS_OK")
	else:
		for failure: String in failures: push_error(failure)
	quit(0 if failures.is_empty() else 1)
