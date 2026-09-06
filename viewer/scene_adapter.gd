extends RefCounted
## Expand complete dynamic city states using bounded, session-scoped metadata.
## Cached nested metadata is immutable by convention; consumers copy before edits.

const ENCODING: String = "city-dynamic-v1"
const ROUTES_ENCODING: String = "city-routes-v1"
const ROWS_ENCODING: String = "city-rows-v1"
const SharedGeometry = preload("res://shared_geometry.gd")
const MAX_ENTITIES: int = 100000
const MAX_TRIP_DEFINITIONS: int = 20000
const MAX_TRIP_GEOMETRY_BYTES: int = 32 * 1024 * 1024
const RESIDENT_FIELDS: Array[String] = ["id", "activity", "building_id", "position", "heading", "visible", "moving", "trip", "blocked_reason"]
const BUILDING_FIELDS: Array[String] = ["id", "occupancy", "resident_ids"]
var session_id: String = ""
var encoding: String = ""
var route_encoding: String = ""
var shared_geometry: RefCounted = null
var error_message: String = ""
var resident_metadata: Dictionary = {}
var building_metadata: Dictionary = {}
var trip_geometries: Dictionary = {}
var trip_geometry_bytes: int = 0
var trip_geometry_sizes: Dictionary = {}

func clear() -> void:
	session_id = ""
	encoding = ""
	route_encoding = ""
	shared_geometry = null
	error_message = ""
	resident_metadata.clear()
	building_metadata.clear()
	trip_geometries.clear()
	trip_geometry_bytes = 0
	trip_geometry_sizes.clear()

func apply_scene(message: Dictionary) -> bool:
	clear()
	var selected: String = str(message.get("snapshot_encoding", ""))
	var selected_routes: String = str(message.get("route_geometry_encoding", ""))
	if selected not in ["", ENCODING, ROUTES_ENCODING, ROWS_ENCODING]:
		error_message = "Unsupported simulation snapshot encoding."
		return false
	if selected_routes not in ["", SharedGeometry.ENCODING] or (not selected_routes.is_empty() and selected not in [ROUTES_ENCODING, ROWS_ENCODING]):
		error_message = "Unsupported shared route capability or snapshot encoding."
		return false
	if selected in [ENCODING, ROUTES_ENCODING, ROWS_ENCODING]:
		var scenario: Variant = message.get("scenario")
		if not scenario is Dictionary:
			error_message = "City scene is missing static metadata."
			return false
		if not _index(scenario.get("residents"), resident_metadata) or not _index(scenario.get("buildings"), building_metadata):
			resident_metadata.clear()
			building_metadata.clear()
			return false
	session_id = str(message.get("session_id", ""))
	encoding = selected
	route_encoding = selected_routes
	if route_encoding == SharedGeometry.ENCODING:
		shared_geometry = SharedGeometry.new()
		shared_geometry.reset(session_id, resident_metadata)
		trip_geometries = shared_geometry.trip_geometries
	return true

func apply_shared_geometry(message: Dictionary, wire_bytes: int = -1) -> bool:
	error_message = ""
	if shared_geometry == null or route_encoding != SharedGeometry.ENCODING:
		error_message = "Shared coordinate messages have no negotiated scene."
		return false
	var accepted: bool = shared_geometry.apply(message, wire_bytes)
	error_message = shared_geometry.error_message
	trip_geometry_bytes = int(shared_geometry.stats().accounted_wire_bytes)
	return accepted

func apply_trip_geometries(message: Dictionary, wire_bytes: int = -1) -> bool:
	error_message = ""
	if not route_encoding.is_empty():
		error_message = "Shared route scenes require indexed geometry definitions."
		return false
	if encoding not in [ROUTES_ENCODING, ROWS_ENCODING] or str(message.get("session_id", "")) != session_id:
		error_message = "Trip geometry has no matching metadata session."
		return false
	var records: Variant = message.get("geometries")
	if not records is Array or records.size() + trip_geometries.size() > MAX_TRIP_DEFINITIONS:
		error_message = "Trip geometry collection exceeds its cache limit."
		return false
	if wire_bytes < 0:
		wire_bytes = JSON.stringify(message).to_utf8_buffer().size() + 1
	if wire_bytes > MAX_TRIP_GEOMETRY_BYTES:
		error_message = "Trip geometry cache reached its 32 MiB limit; reconnect to recover."
		return false
	var added: Dictionary = {}
	var sizes: Dictionary = {}
	var added_bytes: int = 0
	for value: Variant in records:
		if not value is Dictionary or not value.get("id") is String or str(value.id).is_empty() or trip_geometries.has(value.id) or added.has(value.id):
			error_message = "Trip geometry contains an invalid or duplicate identity."
			return false
		if not value.get("points") is Array or value.points.size() < 2 or not value.get("node_ids") is Array or not value.has("length_m"):
			error_message = "Trip geometry is incomplete."
			return false
		added[value.id] = value
		sizes[value.id] = JSON.stringify(value).to_utf8_buffer().size()
		added_bytes += int(sizes[value.id])
	if trip_geometry_bytes + added_bytes > MAX_TRIP_GEOMETRY_BYTES:
		error_message = "Active trip geometry cache reached its 32 MiB limit."
		return false
	# Parsed reliable messages are private to this adapter; retain geometry once.
	trip_geometries.merge(added)
	trip_geometry_sizes.merge(sizes)
	trip_geometry_bytes += added_bytes
	return true

func forget_trip_geometries(message: Dictionary) -> bool:
	error_message = ""
	if route_encoding == SharedGeometry.ENCODING:
		return apply_shared_geometry(message)
	if encoding not in [ROUTES_ENCODING, ROWS_ENCODING] or str(message.get("session_id", "")) != session_id or not message.get("ids") is Array:
		error_message = "Trip eviction has no matching metadata session."
		return false
	var seen: Dictionary = {}
	for id: Variant in message.ids:
		if not id is String or not trip_geometries.has(id) or seen.has(id):
			error_message = "Trip eviction contains an unknown or duplicate identity."
			return false
		seen[id] = true
	for id: String in seen:
		trip_geometry_bytes -= int(trip_geometry_sizes[id])
		trip_geometry_sizes.erase(id)
		trip_geometries.erase(id)
	return true

func _index(records: Variant, target: Dictionary) -> bool:
	if not records is Array or records.size() > MAX_ENTITIES:
		error_message = "Invalid or oversized city metadata collection."
		return false
	for value: Variant in records:
		if not value is Dictionary or not value.get("id") is String or str(value.id).is_empty() or target.has(value.id):
			error_message = "City metadata contains a missing or duplicate identity."
			return false
		# One deep copy per scene, never per snapshot. Nested appearance/footprint
		# arrays are shared by reconstructed records and must remain read-only.
		target[value.id] = value.duplicate(true)
	return true

func expand_snapshot(message: Dictionary) -> Dictionary:
	error_message = ""
	var received_encoding: String = str(message.get("encoding", ""))
	if received_encoding.is_empty():
		return message # Legacy live messages and full replay files are unchanged.
	if received_encoding not in [ENCODING, ROUTES_ENCODING, ROWS_ENCODING] or encoding != received_encoding or str(message.get("session_id", "")) != session_id:
		error_message = "City snapshot has no matching metadata session."
		return {}
	var rows: bool = received_encoding == ROWS_ENCODING
	var residents: Array = _expand_rows(message.get("residents"), resident_metadata, true) if rows else _expand(message.get("residents"), resident_metadata, RESIDENT_FIELDS)
	if not error_message.is_empty():
		return {}
	if received_encoding == ROUTES_ENCODING:
		for person: Dictionary in residents:
			if person.get("trip") == null:
				continue
			var trip: Variant = person.get("trip")
			if not trip is Dictionary or not trip_geometries.has(trip.get("id")) or trip.has("points") or trip.has("node_ids") or trip.has("length_m"):
				error_message = "Snapshot references trip geometry before its reliable definition."
				return {}
			var expanded_trip: Dictionary = trip_geometries[trip.id].duplicate(false)
			expanded_trip.merge(trip, true)
			person["trip"] = expanded_trip
	var buildings: Array = _expand_rows(message.get("buildings"), building_metadata, false) if rows else _expand(message.get("buildings"), building_metadata, BUILDING_FIELDS)
	if not error_message.is_empty():
		return {}
	var result: Dictionary = message.duplicate(false)
	result.erase("encoding")
	result["residents"] = residents
	result["buildings"] = buildings
	return result

func _number(value: Variant) -> bool:
	return (value is float or value is int) and is_finite(float(value))

func _nonnegative_integer(value: Variant) -> bool:
	return _number(value) and value >= 0 and floor(value) == value

func _expand_trip_row(value: Variant) -> Dictionary:
	if not value is Array or value.size() != 7 or not value[0] is String or not trip_geometries.has(value[0]):
		error_message = "Trip row is incomplete or precedes its reliable definition."
		return {}
	if not _nonnegative_integer(value[1]) or not _number(value[2]) or value[2] < 0 or value[2] > 1 or not _nonnegative_integer(value[3]) or not _nonnegative_integer(value[4]) or value[4] < value[3] or not value[5] is String or not value[6] is String:
		error_message = "Trip row has invalid timing, progress, or building identities."
		return {}
	var trip: Dictionary = trip_geometries[value[0]].duplicate(false)
	trip["segment_index"] = value[1]
	trip["segment_progress"] = value[2]
	trip["departure_tick"] = value[3]
	trip["arrival_tick"] = value[4]
	trip["origin_id"] = value[5]
	trip["destination_id"] = value[6]
	return trip

func _expand_rows(records: Variant, metadata: Dictionary, resident: bool) -> Array:
	if not records is Array or records.size() != metadata.size():
		error_message = "City rows do not include every authoritative identity."
		return []
	var seen: Dictionary = {}
	var expanded: Array = []
	var width: int = 9 if resident else 3
	for value: Variant in records:
		if not value is Array or value.size() != width or not value[0] is String or not metadata.has(value[0]) or seen.has(value[0]):
			error_message = "City row has an invalid width or unknown/duplicate identity."
			return []
		seen[value[0]] = true
		var record: Dictionary = metadata[value[0]].duplicate(false)
		if resident:
			if not value[1] is String or (value[2] != null and not value[2] is String) or not value[3] is Array or value[3].size() != 3 or not _number(value[3][0]) or not _number(value[3][1]) or not _number(value[3][2]) or not _number(value[4]) or not value[5] is bool or not value[6] is bool or (value[8] != null and not value[8] is String):
				error_message = "Resident row has invalid activity, position, flags, or reason."
				return []
			var trip: Variant = null
			if value[7] != null:
				trip = _expand_trip_row(value[7])
				if not error_message.is_empty(): return []
			record["activity"] = value[1]
			record["building_id"] = value[2]
			record["position"] = value[3]
			record["heading"] = value[4]
			record["visible"] = value[5]
			record["moving"] = value[6]
			record["trip"] = trip
			record["blocked_reason"] = value[8]
		else:
			if not _nonnegative_integer(value[1]) or not value[2] is Array or value[1] != value[2].size():
				error_message = "Building row has invalid occupancy or membership."
				return []
			var occupants: Dictionary = {}
			for id: Variant in value[2]:
				if not id is String or not resident_metadata.has(id) or occupants.has(id):
					error_message = "Building row has an unknown or duplicate resident."
					return []
				occupants[id] = true
			record["occupancy"] = value[1]
			record["resident_ids"] = value[2]
		expanded.append(record)
	return expanded

func _expand(records: Variant, metadata: Dictionary, fields: Array[String]) -> Array:
	if not records is Array or records.size() != metadata.size():
		error_message = "City snapshot does not include every authoritative identity."
		return []
	var seen: Dictionary = {}
	var expanded: Array = []
	for value: Variant in records:
		if not value is Dictionary or not value.get("id") is String or not metadata.has(value.id) or seen.has(value.id):
			error_message = "City snapshot contains an unknown or duplicate identity."
			return []
		if value.size() != fields.size():
			error_message = "City snapshot has incomplete dynamic state."
			return []
		for field_name: String in fields:
			if not value.has(field_name):
				error_message = "City snapshot has incomplete dynamic state."
				return []
		seen[value.id] = true
		var record: Dictionary = metadata[value.id].duplicate(false)
		record.merge(value, true)
		expanded.append(record)
	return expanded
