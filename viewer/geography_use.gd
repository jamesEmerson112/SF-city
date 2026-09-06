extends RefCounted
## Optional observed parcel-group use. Cohort assignments remain separate.
const CATEGORIES: Array[String] = ["residential","mixed","office","institutional","medical","retail","industrial","visitor","unknown","commercial","parking","open_space","other"]
const PALETTE: Array[Color] = [Color("dfba72"),Color("c59ccc"),Color("789fce"),Color("78b8a5"),Color("df8f99"),Color("d69870"),Color("8e99ac"),Color("83bbc9"),Color("aaaead"),Color("ae91b3"),Color("b5a18f"),Color("99bd7c"),Color("b6bba9")]
const GROUP_CACHE_LIMIT: int = 48
var available: bool = false
var enabled: bool = false
var last_error: String = ""
var directory: String = ""
var manifest: Dictionary = {}
var descriptors: Dictionary = {}
var loaded: Dictionary = {}
var color_tiles: Dictionary = {}
var group_lru: Array[String] = []
var building_tiles: Dictionary = {}

func initialize(geography_path: String) -> void:
	directory = ProjectSettings.globalize_path(geography_path).get_base_dir().simplify_path()
	var path: String = directory.path_join("use-index.json")
	if not FileAccess.file_exists(path): return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or not parsed.get("tiles") is Array:
		last_error = "Optional building-use index is invalid."
		return
	var geography: Variant = JSON.parse_string(FileAccess.get_file_as_string(geography_path))
	if not geography is Dictionary or str(parsed.get("geography_sha256","")) != str(geography.get("sha256","")) or str(parsed.get("geography_file_sha256","")) != FileAccess.get_sha256(geography_path):
		last_error = "Building-use index does not match the installed geography."
		return
	manifest = parsed
	for descriptor: Dictionary in parsed.tiles:
		var identity: String = str(descriptor.get("id",""))
		if not identity.is_empty(): descriptors[identity] = descriptor
	available = true

func load_tile(identity: String) -> void:
	if not available or not descriptors.has(identity): return
	group_lru.erase(identity)
	group_lru.append(identity)
	if loaded.has(identity): return
	var parsed: Dictionary = _read_tile(identity,false)
	if not parsed.is_empty() and not parsed.get("groups") is Dictionary:
		last_error = "Building-use group metadata is invalid: " + identity
		parsed = {}
	if not color_tiles.has(identity): _store_colors(identity,parsed)
	loaded[identity] = parsed.get("groups",{})
	while group_lru.size() > GROUP_CACHE_LIMIT:
		loaded.erase(group_lru.pop_front())

func load_colors(identity: String) -> void:
	if not available or color_tiles.has(identity) or not descriptors.has(identity): return
	_store_colors(identity,_read_tile(identity,true))

func _read_tile(identity: String, color_only: bool) -> Dictionary:
	var descriptor: Dictionary = descriptors[identity]
	var compact: bool = color_only and descriptor.has("color_path")
	var relative: String = str(descriptor.get("color_path" if compact else "path",""))
	var path: String = directory.path_join(relative).simplify_path()
	if relative.is_absolute_path() or not path.replace("\\","/").begins_with(directory.replace("\\","/").trim_suffix("/")+"/"):
		last_error = "Building-use tile path escaped its manifest directory."
		return {}
	if not FileAccess.file_exists(path) or FileAccess.get_sha256(path) != str(descriptor.get("color_sha256" if compact else "sha256","")):
		last_error = "Building-use tile is missing or has a different checksum: " + identity
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary or int(parsed.get("schema_version",0)) != 1 or str(parsed.get("id","")) != identity or not parsed.get("buildings") is Array:
		last_error = "Building-use tile is invalid: " + identity
		return {}
	return parsed

func _store_colors(identity: String, parsed: Dictionary) -> void:
	var buildings: Dictionary = {}
	for row: Array in parsed.get("buildings",[]):
		if row.size() != 3: continue
		var category: String = str(row[1])
		if category not in CATEGORIES: category = "unknown"
		var building_id: String = str(row[0])
		buildings[building_id] = [category,str(row[2])]
		building_tiles[building_id] = identity
	color_tiles[identity] = buildings

func record_for(identifier: String, tile_id: String = "") -> Dictionary:
	if not tile_id.is_empty(): load_tile(tile_id)
	var owner: String = str(building_tiles.get(identifier,""))
	var row: Array = color_tiles.get(owner,{}).get(identifier,[])
	if row.is_empty(): return {}
	load_tile(owner)
	var source_group: Dictionary = loaded.get(owner,{}).get(str(row[1]),{}).duplicate(false)
	if not source_group.is_empty(): source_group["source_url"] = manifest.get("source",{}).get("url","")
	return {"category":str(row[0]),"group_id":str(row[1]),"land_use":source_group}

func category_index(identifier: String, tile_id: String = "") -> int:
	if not tile_id.is_empty(): load_colors(tile_id)
	var row: Array = color_tiles.get(building_tiles.get(identifier,""),{}).get(identifier,[])
	return CATEGORIES.find(str(row[0])) if not row.is_empty() else 8

func make_material(instanced: bool = false) -> ShaderMaterial:
	var material := ShaderMaterial.new()
	material.shader = preload("res://building_use.gdshader")
	material.set_shader_parameter("use_overlay",enabled)
	material.set_shader_parameter("instanced",instanced)
	material.set_shader_parameter("base_tint",Color("9ca69e") if instanced else Color.WHITE)
	material.set_shader_parameter("use_palette",PackedColorArray(PALETTE))
	return material

func get_state() -> Dictionary:
	return {"available":available,"enabled":enabled,"loaded_tiles":color_tiles.size(),"group_tiles":loaded.size(),"building_count":building_tiles.size(),"error":last_error}

static func describe(record: Dictionary) -> String:
	var group: Dictionary = record.get("land_use",{})
	var text: String = "Source group use: " + str(record.get("category","unclassified")).replace("_"," ").capitalize()
	if group.is_empty(): return text + "\nNo matched parcel-group use record."
	text += "\nParcel/group: " + str(group.get("parcel_key",group.get("record_id",record.get("group_id","unspecified"))))
	if group.has("data_as_of"): text += "\nSource date: " + str(group.data_as_of).substr(0,10)
	var units: int = int(group.get("residential_units_in_source_group",0))
	var beds: int = int(group.get("special_units_or_beds_in_source_group",0))
	var area: float = float(group.get("commercial_area_sqft_in_source_group",0.0))
	text += "\nSource group totals: %d residential units" % units
	if beds > 0: text += ", %d special units/beds" % beds
	text += "\n%.0f sq ft commercial area" % area
	text += "\nShared by %d footprint(s); these are not building capacities." % int(group.get("group_footprint_count",1))
	return text
