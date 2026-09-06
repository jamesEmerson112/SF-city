extends RefCounted
## Null means the existing individual MultiMesh calls remain active.
const ScriptBuffers = preload("res://native/crowd_buffers.gd")

static func create(backend: String = "") -> RefCounted:
	var selected: String = backend if not backend.is_empty() else OS.get_environment("CIVIC_CROWD_BACKEND")
	if selected.is_empty(): selected = "auto"
	if selected == "individual": return null
	if selected == "gdscript": return ScriptBuffers.new()
	if selected not in ["auto", "rust"]:
		push_error("Unknown CIVIC_CROWD_BACKEND: " + selected)
		return null
	if not ClassDB.class_exists("CivicCrowdBuffers"):
		var library: String = ""
		match OS.get_name():
			"Windows": library = "civic_godot.dll"
			"Linux": library = "libcivic_godot.so"
			"macOS": library = "libcivic_godot.dylib"
		var extension: String = "res://native/civic_godot.gdextension"
		if library.is_empty() or not FileAccess.file_exists(extension) or not FileAccess.file_exists("res://native/bin/" + library):
			if selected == "rust": push_error("Requested native crowd helper is not installed.")
			return null
		var status: int = GDExtensionManager.load_extension(extension)
		if status not in [GDExtensionManager.LOAD_STATUS_OK, GDExtensionManager.LOAD_STATUS_ALREADY_LOADED]:
			push_error("Could not load the installed native crowd helper: " + str(status))
			return null
	if not ClassDB.class_exists("CivicCrowdBuffers"):
		push_error("Native crowd extension did not register its helper class.")
		return null
	var helper: RefCounted = ClassDB.instantiate("CivicCrowdBuffers")
	if helper.protocol_version() != 1:
		push_error("Native crowd helper protocol is incompatible.")
		return null
	return helper
