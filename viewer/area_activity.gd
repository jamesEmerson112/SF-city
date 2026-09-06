extends RefCounted
## Counts for one selected source polygon and the current synthetic cohort.
## Static building membership uses source centroids; walkers use displayed poses.
const MAX_ENTITIES: int = 100000
const MAX_POLYGON_POINTS: int = 250000
const MAX_EDGE_REFERENCES: int = 500000
var available: bool = false
var last_error: String = ""
var selected_id: String = ""
var session_id: String = ""
var polygons: Array[Dictionary] = []
var building_membership: Dictionary = {}
var resident_ids: Dictionary = {}
var static_counts: Dictionary = {}
var edge_references: int = 0

func clear() -> void:
	available = false
	last_error = ""
	selected_id = ""
	session_id = ""
	polygons.clear()
	building_membership.clear()
	resident_ids.clear()
	static_counts.clear()
	edge_references = 0

func configure(place_id: String, checked_polygons: Array, scenario: Dictionary, active_session: String) -> bool:
	clear()
	if place_id.is_empty() or active_session.is_empty() or checked_polygons.is_empty(): return _invalid("Area activity needs a selected polygon and simulation session.")
	if not scenario.get("buildings") is Array or not scenario.get("residents") is Array or scenario.buildings.size() > MAX_ENTITIES or scenario.residents.size() > MAX_ENTITIES:
		return _invalid("Area activity metadata exceeds its entity bounds.")
	var points: int = 0
	for polygon: Variant in checked_polygons:
		if not polygon is Dictionary or not polygon.get("rings") is Array or polygon.rings.is_empty(): return _invalid("Area activity requires checked polygon rings.")
		var rings: Array[Dictionary] = []
		for source_ring: Variant in polygon.rings:
			if not source_ring is Array or source_ring.size() < 3: return _invalid("Area activity received an invalid ring.")
			points += source_ring.size()
			if points > MAX_POLYGON_POINTS: return _invalid("Area activity geometry exceeds its point bound.")
			for point: Variant in source_ring:
				if not _position_valid(point): return _invalid("Area activity received a nonfinite polygon point.")
			var prepared: Dictionary = _prepare_ring(source_ring)
			if prepared.is_empty(): return _invalid("Area activity geometry exceeds its edge-reference bound.")
			rings.append(prepared)
		polygons.append({"rings":rings})
	var inside_buildings: int = 0
	var missing_centroids: int = 0
	for building: Variant in scenario.buildings:
		if not building is Dictionary or not building.get("id") is String or building.id.is_empty() or building_membership.has(building.id): return _invalid("Area activity building identities are invalid or duplicated.")
		var membership: Variant = null
		if _position_valid(building.get("centroid")):
			membership = contains_position(building.centroid)
			if membership: inside_buildings += 1
		else: missing_centroids += 1
		building_membership[building.id] = membership
	var home_assignments: int = 0
	var work_assignments: int = 0
	for resident: Variant in scenario.residents:
		if not resident is Dictionary or not resident.get("id") is String or resident.id.is_empty() or resident_ids.has(resident.id) or not resident.get("home_id") is String or not resident.get("work_id") is String or not building_membership.has(resident.home_id) or not building_membership.has(resident.work_id): return _invalid("Area activity resident assignments are missing or duplicated.")
		resident_ids[resident.id] = true
		if building_membership[resident.home_id] == true: home_assignments += 1
		if building_membership[resident.work_id] == true: work_assignments += 1
	static_counts = {"cohort_size":resident_ids.size(),"assigned_buildings":inside_buildings,"home_assignments":home_assignments,"work_assignments":work_assignments,"buildings_without_centroids":missing_centroids}
	selected_id = place_id
	session_id = active_session
	available = true
	return true

func _invalid(message: String) -> bool:
	clear()
	last_error = message
	return false

static func _position_valid(value: Variant) -> bool:
	if not value is Array or value.size() != 3: return false
	for coordinate: Variant in value:
		if (not coordinate is int and not coordinate is float) or not is_finite(float(coordinate)) or absf(float(coordinate)) > 100000.0: return false
	return true

func _prepare_ring(points: Array) -> Dictionary:
	# Keep numeric Array coordinates: Vector2 is float32 in this Godot build and
	# can move source street-centerline points across nearby analysis boundaries.
	var minimum: Array[float] = [INF,INF]
	var maximum: Array[float] = [-INF,-INF]
	var bands: Dictionary = {}
	for index: int in range(points.size()):
		var first: Array = points[index]
		var second: Array = points[(index+1)%points.size()]
		var ax: float = float(first[0])
		var ay: float = float(first[1])
		var bx: float = float(second[0])
		var by: float = float(second[1])
		minimum[0] = minf(minimum[0],ax)
		minimum[1] = minf(minimum[1],ay)
		maximum[0] = maxf(maximum[0],ax)
		maximum[1] = maxf(maximum[1],ay)
		var low: int = int(floor(minf(ay,by)/100.0))
		var high: int = int(floor(maxf(ay,by)/100.0))
		edge_references += high-low+1
		if edge_references > MAX_EDGE_REFERENCES: return {}
		var edge: Array[float] = [ax,ay,bx,by,bx-ax,by-ay]
		for band: int in range(low,high+1):
			if not bands.has(band): bands[band] = []
			bands[band].append(edge)
	return {"min":minimum,"max":maximum,"bands":bands}

static func _contains_ring(value: Array, ring: Dictionary) -> bool:
	var x: float = float(value[0])
	var y: float = float(value[1])
	if x < float(ring.min[0]) or y < float(ring.min[1]) or x > float(ring.max[0]) or y > float(ring.max[1]): return false
	var inside: bool = false
	for edge: Array in ring.bands.get(int(floor(y/100.0)),[]):
		var ax: float = edge[0]
		var ay: float = edge[1]
		var bx: float = edge[2]
		var by: float = edge[3]
		var dx: float = edge[4]
		var dy: float = edge[5]
		var cross_value: float = (x-ax)*dy-(y-ay)*dx
		if absf(cross_value) < 0.0000001 and x >= minf(ax,bx) and x <= maxf(ax,bx) and y >= minf(ay,by) and y <= maxf(ay,by): return true
		if (ay > y) != (by > y) and x < ax+(y-ay)*dx/dy: inside = not inside
	return inside

func contains_position(value: Array) -> bool:
	for polygon: Dictionary in polygons:
		var rings: Array = polygon.rings
		if not _contains_ring(value,rings[0]): continue
		var in_hole: bool = false
		for index: int in range(1,rings.size()):
			if _contains_ring(value,rings[index]):
				in_hole = true
				break
		if not in_hole: return true
	return false

func sample(snapshot: Dictionary) -> Dictionary:
	last_error = ""
	if not available: return {}
	if str(snapshot.get("session_id","")) != session_id:
		last_error = "Area activity is waiting for the current simulation session."
		return {}
	var residents: Variant = snapshot.get("residents")
	if not residents is Array or residents.size() != resident_ids.size():
		last_error = "Area activity requires the complete current cohort."
		return {}
	var result: Dictionary = static_counts.duplicate(false)
	result["clock_seconds"] = snapshot.get("clock_seconds",0.0)
	result["sequence"] = snapshot.get("sequence",0)
	result.merge({"selected_id":selected_id,"session_id":session_id,"tick":snapshot.get("tick",0),"people_here":0,"indoors_here":0,"walking_here":0,"incoming_trips":0,"outgoing_trips":0,"internal_trips":0,"people_without_location":0})
	var seen: Dictionary = {}
	for resident: Variant in residents:
		if not resident is Dictionary or not resident.get("id") is String or not resident_ids.has(resident.id) or seen.has(resident.id):
			last_error = "Area activity snapshot has duplicate or foreign residents."
			return {}
		seen[resident.id] = true
		var building_id: Variant = resident.get("building_id")
		if building_id != null:
			if not building_id is String or not building_membership.has(building_id):
				last_error = "Area activity snapshot refers to an unknown building."
				return {}
			var inside: Variant = building_membership[str(building_id)]
			if inside == true: result.indoors_here += 1
			elif inside == null: result.people_without_location += 1
		elif _position_valid(resident.get("position")):
			if contains_position(resident.position): result.walking_here += 1
		else: result.people_without_location += 1
		var trip: Variant = resident.get("trip")
		if trip is Dictionary:
			if not trip.get("origin_id") is String or not trip.get("destination_id") is String:
				last_error = "Area activity trip endpoints must be stable string IDs."
				return {}
			var origin: String = str(trip.get("origin_id",""))
			var destination: String = str(trip.get("destination_id",""))
			if not building_membership.has(origin) or not building_membership.has(destination):
				last_error = "Area activity trip has an unknown endpoint."
				return {}
			var origin_inside: Variant = building_membership[origin]
			var destination_inside: Variant = building_membership[destination]
			if origin_inside == true and destination_inside == true: result.internal_trips += 1
			elif origin_inside == false and destination_inside == true: result.incoming_trips += 1
			elif origin_inside == true and destination_inside == false: result.outgoing_trips += 1
	result.people_here = result.indoors_here + result.walking_here
	return result
