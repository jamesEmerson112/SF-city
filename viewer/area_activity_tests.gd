extends SceneTree
const Activity = preload("res://area_activity.gd")
var failures: Array[String] = []

func _initialize() -> void:
	var activity = Activity.new()
	var polygons: Array = [{"rings":[[[0,0,0],[20,0,0],[20,20,0],[0,20,0]],[[8,8,0],[12,8,0],[12,12,0],[8,12,0]]]},{"rings":[[[30,0,0],[40,0,0],[40,10,0],[30,10,0]]]}]
	var buildings: Array = [{"id":"in","centroid":[5,5,0]},{"id":"out","centroid":[25,0,0]},{"id":"hole","centroid":[10,10,0]},{"id":"part","centroid":[35,5,0]}]
	var residents: Array = [{"id":"a","home_id":"in","work_id":"out"},{"id":"b","home_id":"out","work_id":"in"},{"id":"c","home_id":"in","work_id":"part"},{"id":"d","home_id":"hole","work_id":"out"}]
	var scenario: Dictionary = {"buildings":buildings,"residents":residents}
	if not activity.configure("area",polygons,scenario,"session"): failures.append("Valid area cohort was rejected.")
	if activity.static_counts.home_assignments != 2 or activity.static_counts.work_assignments != 2 or activity.static_counts.assigned_buildings != 2: failures.append("Static assignment counts ignored a hole or separate polygon part.")
	if not activity.contains_position([20,0,0]) or activity.contains_position([10,10,0]) or not activity.contains_position([35,5,0]): failures.append("Polygon boundary, hole or separate part membership differs.")
	var snapshot: Dictionary = {"session_id":"session","tick":1,"residents":[{"id":"a","building_id":null,"position":[5,6,0],"trip":{"origin_id":"in","destination_id":"out"}},{"id":"b","building_id":null,"position":[25,6,0],"trip":{"origin_id":"out","destination_id":"in"}},{"id":"c","building_id":null,"position":[35,5,0],"trip":{"origin_id":"in","destination_id":"part"}},{"id":"d","building_id":"hole","position":[10,10,0],"trip":null}]}
	var result: Dictionary = activity.sample(snapshot)
	if result.people_here != 2 or result.walking_here != 2 or result.incoming_trips != 1 or result.outgoing_trips != 1 or result.internal_trips != 1: failures.append("Trips or current people were double counted or misclassified.")
	# Arrival switches the same identity from walking to occupancy atomically.
	snapshot.residents[1].building_id = "in"
	snapshot.residents[1].trip = null
	result = activity.sample(snapshot)
	if result.people_here != 3 or result.indoors_here != 1 or result.incoming_trips != 0: failures.append("Arrival did not update activity without duplicating a person.")
	# Input geometry/metadata must not mutate a configured membership cache.
	polygons[0].rings[0][0][0] = 99
	buildings[0].centroid = [25,0,0]
	if activity.sample(snapshot).indoors_here != 1: failures.append("Caller mutation changed configured area membership.")
	var foreign: Dictionary = snapshot.duplicate(true)
	foreign.session_id = "other"
	if not activity.sample(foreign).is_empty(): failures.append("Previous session counts leaked into a new session.")
	foreign = snapshot.duplicate(true)
	foreign.residents[1] = foreign.residents[0].duplicate(true)
	if not activity.sample(foreign).is_empty(): failures.append("Duplicate residents produced apparently valid counts.")
	foreign = snapshot.duplicate(true)
	foreign.residents.pop_back()
	if not activity.sample(foreign).is_empty(): failures.append("Partial snapshots produced apparently complete counts.")
	foreign = snapshot.duplicate(true)
	foreign.residents[0].id = 1
	if not activity.sample(foreign).is_empty(): failures.append("Numeric resident ID was coerced into a stable string identity.")
	var unknown: Dictionary = {"buildings":[{"id":"unknown"}],"residents":[{"id":"x","home_id":"unknown","work_id":"unknown"}]}
	activity.configure("area",[{"rings":[[[0,0,0],[20,0,0],[20,20,0],[0,20,0]]]}],unknown,"new")
	result = activity.sample({"session_id":"new","residents":[{"id":"x","building_id":"unknown","position":[5,5,0],"trip":null}]})
	if result.people_here != 0 or result.people_without_location != 1 or result.buildings_without_centroids != 1: failures.append("Missing source centroids silently became observed area membership.")
	if activity.configure("area",[],scenario,"new") or activity.available or not activity.static_counts.is_empty(): failures.append("Invalid selection retained previous cohort counts.")
	# Float32 vectors round these exterior points onto an inclusive outer edge.
	# Membership must preserve the same double coordinates as the live snapshot.
	activity.configure("precision",[{"rings":[[[5000,5000,0],[5020,5000,0],[5020,5020,0],[5000,5020,0]]]}],{"buildings":[],"residents":[]},"precision")
	if activity.contains_position([5020.0001,5010,0]) or activity.contains_position([4999.9999,5010,0]) or not activity.contains_position([5019.9999,5010,0]): failures.append("Float32 boundary rounding changed area membership.")
	var numeric_scenario: Dictionary = {"buildings":[{"id":"1","centroid":[5,5,0]}],"residents":[{"id":"1","home_id":"1","work_id":"1"},{"id":"2","home_id":"1","work_id":"1"}]}
	activity.configure("numeric",[{"rings":[[[0,0,0],[20,0,0],[20,20,0]]]}],numeric_scenario,"numeric")
	if not activity.sample({"session_id":"numeric","residents":[{"id":1,"building_id":"1","position":[5,5,0]},{"id":"1","building_id":"1","position":[5,5,0]}]}).is_empty(): failures.append("Mixed numeric/string IDs bypassed duplicate detection.")
	numeric_scenario.residents[0].home_id = 1
	if activity.configure("numeric",[{"rings":[[[0,0,0],[20,0,0],[20,20,0]]]}],numeric_scenario,"numeric"): failures.append("Numeric assignment reference was coerced into a valid building ID.")
	if failures.is_empty():
		print("GODOT_AREA_ACTIVITY_TESTS_OK centroid assignments, boundary/hole/parts, inbound/outbound/internal trips, arrival conservation, source detachment, unknown locations and session reset")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
