extends RefCounted
## Thread-private city-points-v1 pool. Expanded point arrays are immutable.
const ENCODING: String = "city-points-v1"
const MAX_FRAME_BYTES: int = 16 * 1024 * 1024
const MAX_CACHE_BYTES: int = 32 * 1024 * 1024
const MAX_POINTS: int = 400000
const MAX_POOL_MESSAGE_POINTS: int = 1024
const MAX_POINT_REFERENCES: int = 2000000
const MAX_NODE_REFERENCES: int = 500000
const MAX_IDENTITIES: int = 20000
const MAX_ROUTE_ITEMS: int = 50000
const MAX_SAFE_INTEGER: int = 9007199254740991
const WIRE_RESERVE: int = 4096

var session_id: String = ""
var error_message: String = ""
var points: Array = []
var trip_geometries: Dictionary = {}
var identities: Dictionary = {}
var known_residents: Dictionary = {}
var path_sizes: Dictionary = {}
var point_references: int = 0
var node_references: int = 0
var pool_wire_bytes: int = 0
var path_wire_bytes: int = 0
var _controls := RegEx.new()

func _init() -> void:
	_controls.compile("[\\x00-\\x1f\\x7f]")

func reset(session: String, residents: Dictionary) -> void:
	session_id = session
	error_message = ""
	# Replacement containers preserve geometry already held by presenter states.
	points = []
	trip_geometries = {}
	identities = {}
	known_residents = residents
	path_sizes = {}
	point_references = 0
	node_references = 0
	pool_wire_bytes = 0
	path_wire_bytes = 0

func stats() -> Dictionary:
	return {"points":points.size(), "active_trips":trip_geometries.size(), "identity_records":identities.size(), "point_references":point_references, "node_references":node_references, "accounted_wire_bytes":pool_wire_bytes + path_wire_bytes + WIRE_RESERVE}

func _fail(explanation: String) -> bool:
	error_message = explanation
	return false

func _number(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))

func _integer(value: Variant) -> bool:
	return _number(value) and value >= 0 and value <= MAX_SAFE_INTEGER and floor(value) == value

func _id(value: Variant) -> bool:
	return value is String and not value.is_empty() and value.to_utf8_buffer().size() <= 512 and _controls.search(value) == null

func _identity(value: String) -> Dictionary:
	var last: int = value.rfind(":")
	if last < 0: return {}
	var prefix: String = value.substr(0, last)
	var separator: int = prefix.rfind(":")
	if separator < 0: return {}
	var resident: String = prefix.substr(0, separator)
	var direction: String = prefix.substr(separator + 1)
	var cycle: String = value.substr(last + 1)
	if not _id(resident) or not known_residents.has(resident) or direction not in ["outbound", "return"] or cycle.is_empty() or cycle.length() > 16 or not cycle.is_valid_int(): return {}
	var number: int = int(cycle)
	if number < 0 or number > MAX_SAFE_INTEGER or str(number) != cycle: return {}
	return {"key":prefix, "cycle":number}

func apply(message: Dictionary, wire_bytes: int = -1) -> bool:
	error_message = ""
	if not _integer(message.get("protocol_version")) or message.protocol_version != 1 or message.get("session_id") != session_id:
		return _fail("Shared geometry has an invalid protocol or session.")
	if wire_bytes < 0: wire_bytes = JSON.stringify(message, "", true, true).to_utf8_buffer().size() + 1
	if wire_bytes > MAX_FRAME_BYTES + 1 or wire_bytes < 1:
		return _fail("Shared geometry frame exceeds its 16 MiB limit.")
	match message.get("type"):
		"route_coordinate_pool": return _append_points(message, wire_bytes)
		"trip_geometry_indices": return _define_path(message, wire_bytes)
		"forget_trip_geometries": return _forget(message)
	return _fail("Shared geometry message type is unsupported.")

func _append_points(message: Dictionary, wire_bytes: int) -> bool:
	if message.size() != 5 or not _integer(message.get("start_index")) or message.start_index != points.size() or not message.get("points") is Array:
		return _fail("Shared point pool must append at its exact next index.")
	var additions: Array = message.points
	if additions.is_empty() or additions.size() > MAX_POOL_MESSAGE_POINTS or points.size() + additions.size() > MAX_POINTS:
		return _fail("Shared point pool exceeds its decoded point limit.")
	if pool_wire_bytes + path_wire_bytes + wire_bytes + WIRE_RESERVE > MAX_CACHE_BYTES:
		return _fail("Shared point pool exceeds its 32 MiB cache limit.")
	for point: Variant in additions:
		if not point is Array or point.size() != 3 or not _number(point[0]) or not _number(point[1]) or not _number(point[2]):
			return _fail("Shared coordinates must contain three finite numbers.")
	# Godot normalizes JSON integer/float types. Equal parsed triples may have
	# distinct source types; append-only index identity remains unambiguous.
	points.append_array(additions)
	pool_wire_bytes += wire_bytes
	return true

func _define_path(message: Dictionary, wire_bytes: int) -> bool:
	# Production emits one independently bounded route per reliable frame.
	if message.size() != 4 or not message.get("geometries") is Array or message.geometries.size() != 1:
		return _fail("Shared paths require one indexed route per frame.")
	var record: Variant = message.geometries[0]
	if not record is Dictionary or record.size() != 4 or not _id(record.get("id")) or not record.get("point_indices") is Array or not record.get("node_ids") is Array or not _number(record.get("length_m")) or record.length_m < 0:
		return _fail("Shared path has invalid fields or route identity.")
	var references: Array = record.point_indices
	var nodes: Array = record.node_ids
	if references.is_empty() or references.size() > MAX_ROUTE_ITEMS or nodes.is_empty() or nodes.size() > MAX_ROUTE_ITEMS:
		return _fail("Shared path exceeds its route item limit.")
	var identity: Dictionary = _identity(record.id)
	if identity.is_empty(): return _fail("Shared path requires a known resident and canonical commuter cycle.")
	var digest: String = JSON.stringify({"point_indices":references, "node_ids":nodes, "length_m":record.length_m}, "", true, true).sha256_text()
	if identities.has(identity.key):
		var prior: Dictionary = identities[identity.key]
		if digest != prior.digest or int(identity.cycle) < int(prior.cycle):
			return _fail("Shared commuter route changed or reintroduced a stale cycle.")
	elif identities.size() >= MAX_IDENTITIES:
		return _fail("Shared commuter identity cache reached its limit.")
	for index: Variant in references:
		if not _integer(index) or index >= points.size():
			return _fail("Shared path references an undefined or invalid coordinate index.")
	for node: Variant in nodes:
		if not _id(node): return _fail("Shared path contains an invalid graph node identity.")
	if trip_geometries.has(record.id): return true # Exact active retransmission.
	if point_references + references.size() > MAX_POINT_REFERENCES or node_references + nodes.size() > MAX_NODE_REFERENCES:
		return _fail("Shared paths exceed their decoded reference limits.")
	if pool_wire_bytes + path_wire_bytes + wire_bytes + WIRE_RESERVE > MAX_CACHE_BYTES:
		return _fail("Shared paths exceed the 32 MiB cache limit.")
	var expanded: Array = []
	expanded.resize(references.size())
	for index: int in range(references.size()):
		expanded[index] = points[int(references[index])]
	trip_geometries[record.id] = {"id":record.id, "points":expanded, "node_ids":nodes, "length_m":record.length_m}
	identities[identity.key] = {"digest":digest, "cycle":identity.cycle}
	path_sizes[record.id] = wire_bytes
	point_references += references.size()
	node_references += nodes.size()
	path_wire_bytes += wire_bytes
	return true

func _forget(message: Dictionary) -> bool:
	if message.size() != 4 or not message.get("ids") is Array or message.ids.is_empty() or message.ids.size() > MAX_IDENTITIES:
		return _fail("Shared route eviction has invalid fields or size.")
	var seen: Dictionary = {}
	for id: Variant in message.ids:
		if not id is String or not trip_geometries.has(id) or seen.has(id):
			return _fail("Shared route eviction contains an unknown or duplicate identity.")
		seen[id] = true
	for id: String in seen:
		point_references -= trip_geometries[id].points.size()
		node_references -= trip_geometries[id].node_ids.size()
		path_wire_bytes -= int(path_sizes[id])
		path_sizes.erase(id)
		trip_geometries.erase(id)
	return true
