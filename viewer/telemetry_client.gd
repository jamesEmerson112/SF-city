extends Node
## Bounded, read-only launcher diagnostics. Received messages never reach stdout.
signal received(message: Dictionary)
var peer := StreamPeerTCP.new()
var incoming := PackedByteArray()
var outgoing := PackedByteArray()
var active: bool = false
var greeted: bool = false
var secret: String = ""
var port: int = 0
var last_sequence: int = -1
var run_id: String = ""
var status: String = "No launcher feed; local viewer metrics remain available"
var last_message_msec: int = 0
var retry_msec: int = 0
var hello_sent_usec: int = 0
var clock_synced: bool = false
var monotonic_offset: float = 0.0
var clock_uncertainty: float = 0.0
const MAX_BYTES: int = 256*1024

func configure(number: int, credential: String) -> void:
	port = number
	secret = credential
	if port < 1 or port > 65535 or secret.is_empty(): return
	_connect()

func _connect() -> void:
	peer.disconnect_from_host()
	incoming.clear()
	greeted = false
	clock_synced = false
	last_sequence = -1
	hello_sent_usec = Time.get_ticks_usec()
	outgoing = (JSON.stringify({"type":"hello","schema_version":1,"token":secret})+"\n").to_utf8_buffer()
	active = peer.connect_to_host("127.0.0.1",port) == OK
	status = "Connecting to local diagnostics"
	retry_msec = Time.get_ticks_msec()+3000

func _process(_delta: float) -> void:
	if not active:
		if port > 0 and not secret.is_empty() and Time.get_ticks_msec() >= retry_msec: _connect()
		return
	peer.poll()
	if peer.get_status() == StreamPeerTCP.STATUS_CONNECTING:
		if Time.get_ticks_msec() > retry_msec: _disconnect("Diagnostics connection timed out")
		return
	if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		_disconnect("Diagnostics disconnected; showing last readings")
		return
	if not outgoing.is_empty():
		var sent: Array = peer.put_partial_data(outgoing)
		if int(sent[0]) != OK:
			_disconnect("Diagnostics handshake failed")
			return
		outgoing = outgoing.slice(int(sent[1]))
	var available: int = mini(peer.get_available_bytes(),65536)
	if available > 0:
		var result: Array = peer.get_partial_data(available)
		if int(result[0]) != OK:
			_disconnect("Diagnostics read failed")
			return
		incoming.append_array(result[1])
	if incoming.size() > MAX_BYTES:
		_disconnect("Diagnostics frame exceeded its limit")
		return
	for index: int in range(8):
		var boundary: int = incoming.find(10)
		if boundary < 0: break
		var parsed: Variant = JSON.parse_string(incoming.slice(0,boundary).get_string_from_utf8())
		incoming = incoming.slice(boundary+1)
		if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1: continue
		var next_run: String = str(parsed.get("run_id",""))
		if next_run != run_id:
			run_id = next_run
			last_sequence = -1
		if str(parsed.get("kind","")) == "heartbeat":
			last_message_msec = Time.get_ticks_msec()
			status = "Connected"
			continue
		var sequence: int = int(parsed.get("sequence",-1))
		if sequence <= last_sequence: continue
		last_sequence = sequence
		last_message_msec = Time.get_ticks_msec()
		if str(parsed.get("kind","")) == "snapshot":
			var clock: Dictionary = parsed.get("payload",{}).get("clock",{})
			if clock.get("launcher_monotonic_seconds") is float or clock.get("launcher_monotonic_seconds") is int:
				var received_usec: int = Time.get_ticks_usec()
				clock_uncertainty = float(received_usec-hello_sent_usec)/2000000.0
				monotonic_offset = float(clock.launcher_monotonic_seconds)-float(received_usec+hello_sent_usec)/2000000.0
				clock_synced = true
		status = "Connected"
		received.emit(parsed)

func _disconnect(message: String) -> void:
	active = false
	peer.disconnect_from_host()
	incoming.clear()
	status = message
	retry_msec = Time.get_ticks_msec()+3000

func _exit_tree() -> void:
	peer.disconnect_from_host()
