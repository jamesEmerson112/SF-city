extends RefCounted
## Named geographic navigation, independent of synthetic resident assignments.
var available: bool = false
var last_error: String = ""
var manifest: Dictionary = {}
var entries: Array[Dictionary] = []
var by_id: Dictionary = {}
var additional_sources: Dictionary = {}

func initialize(geography_path: String) -> void:
	var path: String = ProjectSettings.globalize_path(geography_path).get_base_dir().path_join("places-index.json")
	if not FileAccess.file_exists(path): return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	var geography: Variant = JSON.parse_string(FileAccess.get_file_as_string(geography_path))
	if not parsed is Dictionary or not geography is Dictionary:
		last_error = "Named places index is invalid."
		return
	if str(parsed.get("geography_sha256","")) != str(geography.get("sha256","")) or str(parsed.get("geography_file_sha256","")) != FileAccess.get_sha256(geography_path):
		last_error = "Named places do not match the installed geography."
		return
	configure(parsed)

func configure(data: Dictionary) -> bool:
	available = false
	entries.clear()
	by_id.clear()
	last_error = ""
	if int(data.get("schema_version",0)) != 1 or not data.get("places") is Array or not data.get("sources") is Dictionary:
		last_error = "Named places require schema 1, places and source metadata."
		return false
	for value: Variant in data.places:
		if not value is Dictionary or str(value.get("id","")).is_empty() or str(value.get("name","")).is_empty() or value.get("kind") not in ["neighborhood","park"] or not _valid_position(value.get("target")) or not _valid_position(value.get("walk_position")) or not is_finite(float(value.get("view_distance_m",0.0))) or float(value.get("view_distance_m",0.0)) <= 0.0 or not data.sources.has(str(value.get("source_key",""))):
			last_error = "A named place has invalid coordinates or source metadata."
			entries.clear()
			by_id.clear()
			return false
		var identity: String = str(value.id)
		if by_id.has(identity):
			last_error = "Named place IDs must be unique."
			entries.clear()
			by_id.clear()
			return false
		entries.append(value)
		by_id[identity] = value
	entries.sort_custom(func(a: Dictionary,b: Dictionary) -> bool: return str(a.name).naturalnocasecmp_to(str(b.name)) < 0)
	manifest = data
	available = true
	return true

func _valid_position(value: Variant) -> bool:
	if not value is Array or value.size() != 3: return false
	for coordinate: Variant in value:
		if not coordinate is float and not coordinate is int: return false
		if not is_finite(float(coordinate)): return false
	return true

func search(query: String, maximum: int = 12) -> Array[Dictionary]:
	var needle: String = query.strip_edges().to_lower()
	var kind: String = ""
	for candidate: String in ["park","neighborhood","landmark"]:
		if needle.begins_with(candidate+":"):
			kind = candidate
			needle = needle.trim_prefix(candidate+":").strip_edges()
	var found: Array[Dictionary] = []
	for record: Dictionary in entries:
		if not kind.is_empty() and str(record.kind) != kind: continue
		var haystack: String = (str(record.name)+" "+str(record.id)).to_lower()
		if needle in haystack:
			found.append(record)
			if found.size() >= maximum: break
	return found

func resolve(query: String) -> Dictionary:
	last_error = ""
	if not available:
		last_error = "Named places are unavailable. Load the city geography and places index."
		return {}
	if by_id.has(query): return by_id[query]
	var exact_name: String = query.strip_edges().to_lower()
	var requested_kind: String = ""
	for kind: String in ["park","neighborhood","landmark"]:
		if exact_name.begins_with(kind+":"):
			requested_kind = kind
			exact_name = exact_name.trim_prefix(kind+":").strip_edges()
	var exact: Array[Dictionary] = []
	for record: Dictionary in entries:
		if str(record.name).to_lower() == exact_name and (requested_kind.is_empty() or str(record.kind) == requested_kind): exact.append(record)
	var found: Array[Dictionary] = exact if not exact.is_empty() else search(query,entries.size())
	if found.size() == 1: return found[0]
	if found.is_empty(): last_error = "No named place matches: " + query
	else:
		var suggestions: PackedStringArray = []
		for record: Dictionary in found.slice(0,4): suggestions.append(str(record.id))
		last_error = "More than one place matches. Choose an exact ID: " + "; ".join(suggestions)
	return {}

func source_for(record: Dictionary) -> Dictionary:
	var key: String = str(record.get("source_key",""))
	return additional_sources[key] if additional_sources.has(key) else manifest.get("sources",{}).get(key,{})

func add_landmarks(records: Dictionary) -> void:
	for record: Dictionary in records.values():
		if not _valid_position(record.get("walk_position")) or by_id.has(str(record.id)): continue
		var key: String = "landmark:"+str(record.id)
		var source: Dictionary = record.get("height_reference",{}).duplicate(false)
		source["observation_note"] = str(record.get("source_note",""))
		additional_sources[key] = source
		var place: Dictionary = {"id":str(record.id),"name":str(record.label),"kind":"landmark","source_key":key,"target":record.position,"walk_position":record.walk_position,"walk_node_id":record.get("walk_node_id",""),"walk_target_distance_m":record.get("walk_target_distance_m",0.0),"view_distance_m":clampf(float(record.height_m)*2.3,220.0,950.0)}
		place["height_m"] = float(record.height_m)
		var minimum := Vector2(INF,INF)
		var maximum := Vector2(-INF,-INF)
		for point: Array in record.get("footprint",[]):
			minimum = minimum.min(Vector2(float(point[0]),float(point[1])))
			maximum = maximum.max(Vector2(float(point[0]),float(point[1])))
		if minimum.is_finite() and maximum.is_finite(): place["bounds"] = {"min":[minimum.x,minimum.y],"max":[maximum.x,maximum.y]}
		entries.append(place)
		by_id[str(record.id)] = place
	if not records.is_empty(): available = true
	entries.sort_custom(func(a: Dictionary,b: Dictionary) -> bool: return str(a.name).naturalnocasecmp_to(str(b.name)) < 0)

static func kind_label(record: Dictionary) -> String:
	if str(record.get("kind","")) == "landmark": return "Landmark exterior"
	return "Analysis area" if str(record.get("kind","")) == "neighborhood" else "Rec/Park property"
