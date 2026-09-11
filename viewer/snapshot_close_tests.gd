extends SceneTree
## Real loopback: closing in an ACK callback must abort the current socket poll.
var failures: Array[String] = []
var client
var server := TCPServer.new()
var remote: StreamPeerTCP
var acknowledgements: int = 0

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	_check(server.listen(0,"127.0.0.1") == OK,"Could not listen for shutdown fixture")
	client = preload("res://snapshot_client.gd").new()
	root.add_child(client)
	client.acknowledged.connect(func(_message: Dictionary) -> void:
		acknowledgements += 1
		client.stop())
	client.connect_worker("127.0.0.1",server.get_local_port(),"fixture-secret")
	var deadline: int = Time.get_ticks_msec()+5000
	while not server.is_connection_available() and Time.get_ticks_msec() < deadline: await process_frame
	if not server.is_connection_available():
		_check(false,"Fixture socket did not connect")
		_finish()
		return
	remote = server.take_connection()
	for frame: int in range(3): await process_frame
	var scene: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://../contracts/one-resident-replay.json")).scene
	var session: String = str(scene.session_id)
	var first: Dictionary = {"type":"ack","protocol_version":1,"request_id":"save-exit","action":"save","session_id":session,"slot":"exit-recovery","captured_tick":40,"tick":40}
	var later: Dictionary = first.duplicate()
	later.request_id = "must-not-deliver"
	client.pending["save-exit"] = Time.get_ticks_msec()
	client.pending_actions["save-exit"] = "save"
	remote.put_data((JSON.stringify(scene)+"\n"+JSON.stringify(first)+"\n"+JSON.stringify(later)+"\n").to_utf8_buffer())
	deadline = Time.get_ticks_msec()+5000
	while not client.stopped and Time.get_ticks_msec() < deadline: await process_frame
	for frame: int in range(4): await process_frame
	_check(client.stopped and not client.active and not client.connected,"ACK close did not stop the client")
	_check(acknowledgements == 1,"Decoded callbacks continued after ACK close")
	_check(client.last_error.is_empty(),"Orderly ACK close became a transport error")
	_check(client.incoming.is_empty() and client.outgoing.is_empty() and client.pending.is_empty(),"Stopped client retained transport work")
	client.stop()
	client._poll_connection()
	_finish()

func _check(value: bool, message: String) -> void:
	if not value: failures.append(message)

func _finish() -> void:
	if remote != null: remote.disconnect_from_host()
	server.stop()
	if client != null: client.queue_free()
	await process_frame
	if failures.is_empty(): print("GODOT_SNAPSHOT_CLOSE_TESTS_OK callback stop, no later delivery, idempotent socket teardown")
	else:
		for message: String in failures: push_error(message)
	quit(0 if failures.is_empty() else 1)
