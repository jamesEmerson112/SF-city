extends RefCounted
## Displays complete authoritative states and interpolates same-trip motion only.
## A transition snaps the entire snapshot, keeping occupancy/activity/visibility atomic.
const Coordinates = preload("res://coordinates.gd")
var current: Dictionary = {}
var previous: Dictionary = {}
var source_by_id: Dictionary = {}
var received_at: float = 0.0
var blend_duration: float = 0.1
var atomic: bool = true
var route_cache: Dictionary = {}
var interpolation_ranges: Dictionary = {}
var last_prepare_profile: Dictionary = {}

func clear() -> void:
	current = {}
	previous = {}
	source_by_id = {}
	atomic = true
	route_cache.clear()
	interpolation_ranges.clear()

func receive(snapshot: Dictionary) -> void:
	var phase_started: int = Time.get_ticks_usec()
	if str(snapshot.get("session_id","")) != str(current.get("session_id","")): route_cache.clear()
	previous = current
	current = snapshot
	received_at = Time.get_ticks_msec() / 1000.0
	source_by_id = {}
	for person: Dictionary in previous.get("residents", []):
		source_by_id[str(person.id)] = person
	last_prepare_profile = {"indices":float(Time.get_ticks_usec()-phase_started)/1000.0}
	phase_started = Time.get_ticks_usec()
	atomic = previous.is_empty() or str(previous.get("session_id", "")) != str(current.get("session_id", ""))
	atomic = atomic or bool(current.get("paused", false)) or bool(previous.get("paused", false))
	atomic = atomic or int(current.get("tick", 0)) <= int(previous.get("tick", 0))
	var previous_occupancy: Dictionary = {}
	for building: Dictionary in previous.get("buildings",[]): previous_occupancy[str(building.id)] = int(building.get("occupancy",0))
	atomic = atomic or previous_occupancy.size() != current.get("buildings",[]).size()
	for building: Dictionary in current.get("buildings",[]):
		if previous_occupancy.get(str(building.id),-1) != int(building.get("occupancy",0)):
			atomic = true
			break
	atomic = atomic or previous.get("residents", []).size() != current.get("residents", []).size()
	for person: Dictionary in current.get("residents", []):
		var before: Dictionary = source_by_id.get(str(person.id), {})
		if before.is_empty() or before.get("activity") != person.get("activity") or before.get("visible") != person.get("visible") or before.get("moving") != person.get("moving"):
			atomic = true
			break
		var old_trip: Variant = before.get("trip")
		var new_trip: Variant = person.get("trip")
		if old_trip is Dictionary and new_trip is Dictionary:
			if old_trip.get("id") != new_trip.get("id") or (not is_same(old_trip.get("points"),new_trip.get("points")) and old_trip.get("points") != new_trip.get("points")):
				atomic = true
		elif old_trip != new_trip:
			atomic = true
	last_prepare_profile["transitions"] = float(Time.get_ticks_usec()-phase_started)/1000.0
	phase_started = Time.get_ticks_usec()
	var elapsed: float = float(current.get("simulation_time", 0.0)) - float(previous.get("simulation_time", 0.0))
	blend_duration = clampf(elapsed / maxf(float(current.get("speed", 1.0)), 0.001), 0.016, 0.25)
	interpolation_ranges.clear()
	var active_routes: Dictionary = {}
	for person: Dictionary in current.get("residents",[]):
		var trip: Variant = person.get("trip")
		if not trip is Dictionary or trip.get("points",[]).size() < 2: continue
		var identity: String = str(trip.get("id",""))
		active_routes[identity] = true
		if atomic: continue
		var prior: Variant = source_by_id.get(str(person.id),{}).get("trip")
		if not prior is Dictionary or str(prior.get("id","")) != identity: continue
		if int(prior.get("segment_index",-1)) == int(trip.get("segment_index",-2)):
			interpolation_ranges[str(person.id)] = {"direct":true,"from_position":source_by_id[str(person.id)].position,"to_position":person.position}
			continue
		var first_segment: int = mini(int(prior.get("segment_index",0)),int(trip.get("segment_index",0)))
		var last_segment: int = maxi(int(prior.get("segment_index",0)),int(trip.get("segment_index",0)))
		var route: Dictionary = _cached_route(trip,first_segment,last_segment)
		interpolation_ranges[str(person.id)] = {"direct":false,"route":route,"from":_route_distance(prior,route),"to":_route_distance(trip,route)}
	for identity: String in route_cache.keys():
		if not active_routes.has(identity): route_cache.erase(identity)
	last_prepare_profile["intervals"] = float(Time.get_ticks_usec()-phase_started)/1000.0

func sample() -> Dictionary:
	if current.is_empty():
		return {}
	var alpha: float = 1.0 if atomic else clampf((Time.get_ticks_msec() / 1000.0 - received_at) / blend_duration, 0.0, 1.0)
	if alpha >= 1.0:
		return current
	var result: Dictionary = current.duplicate(false)
	result["simulation_time"] = lerpf(float(previous.simulation_time), float(current.simulation_time), alpha)
	result["clock_seconds"] = lerpf(float(previous.clock_seconds), float(current.clock_seconds), alpha)
	result["tick"] = int(lerpf(float(previous.tick),float(current.tick),alpha))
	result["residents"] = []
	for person: Dictionary in current.residents:
		var copy: Dictionary = person.duplicate(false)
		if bool(person.get("moving", false)) and interpolation_ranges.has(str(person.id)):
			var interval: Dictionary = interpolation_ranges[str(person.id)]
			if bool(interval.direct):
				var a: Array = interval.from_position
				var b: Array = interval.to_position
				copy["position"] = [lerpf(float(a[0]),float(b[0]),alpha),lerpf(float(a[1]),float(b[1]),alpha),lerpf(float(a[2]),float(b[2]),alpha)]
			else:
				var distance: float = lerpf(float(interval.from),float(interval.to),alpha)
				var sampled: Dictionary = _along_route(interval.route,distance)
				copy["position"] = sampled.position
				copy["heading"] = sampled.heading
		result.residents.append(copy)
	return result

func _cached_route(trip: Dictionary, first_segment: int, last_segment: int) -> Dictionary:
	var identity: String = str(trip.get("id",""))
	var points: Array = trip.get("points", [])
	first_segment = clampi(first_segment,0,points.size()-2)
	last_segment = clampi(last_segment,first_segment,points.size()-2)
	var cached: Dictionary = route_cache.get(identity,{})
	if not cached.is_empty() and int(cached.first_segment) == first_segment and int(cached.last_segment) == last_segment and (is_same(cached.source_points,points) or cached.source_points == points): return cached
	# Only this interval can be displayed between the two authoritative states.
	# A one-corner crossing must not scan the remaining kilometers of a route.
	# Retain at most one span per active trip, so the cache stays bounded by the
	# cohort and never grows to one dictionary entry per source route segment.
	var cumulative := PackedFloat64Array([0.0])
	for i: int in range(first_segment,last_segment+1):
		var a: Array = points[i]
		var b: Array = points[i+1]
		var east: float = float(b[0])-float(a[0])
		var north: float = float(b[1])-float(a[1])
		var up: float = float(b[2])-float(a[2])
		cumulative.append(cumulative[-1]+sqrt(east*east+north*north+up*up))
	cached = {"source_points":points,"points":points.slice(first_segment,last_segment+2),"cumulative":cumulative,"first_segment":first_segment,"last_segment":last_segment}
	route_cache[identity] = cached
	return cached

func _route_distance(trip: Dictionary, route: Dictionary) -> float:
	var cumulative: PackedFloat64Array = route.cumulative
	var segment: int = int(trip.get("segment_index", 0))-int(route.first_segment)
	if segment >= cumulative.size()-1: return cumulative[-1]
	segment = maxi(segment,0)
	return lerpf(cumulative[segment],cumulative[segment+1],clampf(float(trip.get("segment_progress",0.0)),0.0,1.0))

func _along_route(route: Dictionary, distance: float) -> Dictionary:
	var cumulative: PackedFloat64Array = route.cumulative
	var points: Array = route.points
	var low: int = 0
	var high: int = points.size()-2
	while low < high:
		var middle: int = (low+high)/2
		if cumulative[middle+1] < distance: low = middle+1
		else: high = middle
	var fraction: float = clampf((distance-cumulative[low])/maxf(cumulative[low+1]-cumulative[low],0.000000001),0.0,1.0)
	var a: Array = points[low]
	var b: Array = points[low+1]
	return {"position":[lerpf(float(a[0]),float(b[0]),fraction),lerpf(float(a[1]),float(b[1]),fraction),lerpf(float(a[2]),float(b[2]),fraction)],"heading":atan2(float(b[1])-float(a[1]),float(b[0])-float(a[0]))}
