extends RefCounted
## Disposable prepared scenery, never executable Resources or simulation state.
## Each immutable entry binds its exact inputs and binary payload to SHA-256.
const MAGIC: PackedByteArray = [83,70,83,67,78,48,48,49] # SFSCN001
const HEADER_BYTES: int = 84
const MAX_ENTRY_BYTES: int = 128 * 1024 * 1024
var directory: String = ""
var enabled: bool = false
var last_error: String = ""
var hits: int = 0
var misses: int = 0
var writes: int = 0
var errors: int = 0

func configure(path: String) -> void:
	directory = ProjectSettings.globalize_path(path).simplify_path() if not path.is_empty() else ""

static func file_digest(path: String) -> String:
	return FileAccess.get_sha256(path) if FileAccess.file_exists(path) else "missing"

static func value_digest(value: Variant) -> String:
	return _digest(var_to_bytes(_canonical(value))).hex_encode()

static func _canonical(value: Variant) -> Variant:
	if value is Dictionary:
		var result: Dictionary = {}
		var keys: Array = value.keys()
		keys.sort_custom(func(a: Variant,b: Variant) -> bool: return str(a) < str(b))
		for key: Variant in keys: result[key] = _canonical(value[key])
		return result
	if value is Array:
		var result: Array = []
		for item: Variant in value: result.append(_canonical(item))
		return result
	return value

static func _digest(bytes: PackedByteArray) -> PackedByteArray:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(bytes)
	return context.finish()

func entry_path(identity: Dictionary) -> String:
	var key: String = value_digest(identity)
	return directory.path_join(key.substr(0,2)).path_join(key + ".sfmesh")

func read_entry(identity: Dictionary) -> Dictionary:
	if not enabled or directory.is_empty(): return {}
	var path: String = entry_path(identity)
	if not FileAccess.file_exists(path):
		misses += 1
		return {}
	var file := FileAccess.open(path,FileAccess.READ)
	if file == null: return _read_error("Could not read prepared scenery.")
	var length: int = file.get_length()
	if length < HEADER_BYTES or length > HEADER_BYTES + MAX_ENTRY_BYTES:
		file.close()
		return _read_error("Prepared scenery has an invalid size; rebuilding it.")
	var magic: PackedByteArray = file.get_buffer(8)
	var version: int = file.get_32()
	var payload_size: int = file.get_64()
	var key: PackedByteArray = file.get_buffer(32)
	var expected: PackedByteArray = file.get_buffer(32)
	if magic != MAGIC or version != 1 or payload_size != length - HEADER_BYTES or key.hex_encode() != value_digest(identity):
		file.close()
		return _read_error("Prepared scenery header is invalid; rebuilding it.")
	var bytes: PackedByteArray = file.get_buffer(payload_size)
	file.close()
	if bytes.size() != payload_size or _digest(bytes) != expected:
		return _read_error("Prepared scenery checksum differs; rebuilding it.")
	# bytes_to_var deliberately excludes full object deserialization.
	var decoded: Variant = bytes_to_var(bytes)
	if not decoded is Dictionary or decoded.is_empty() or not _plain_data(decoded):
		return _read_error("Prepared scenery payload is invalid; rebuilding it.")
	hits += 1
	return decoded

func write_entry(identity: Dictionary,payload: Dictionary) -> bool:
	if not enabled or directory.is_empty(): return false
	if payload.is_empty() or not _plain_data(payload): return _write_error("Prepared scenery must contain plain array data.")
	var bytes: PackedByteArray = var_to_bytes(payload)
	if bytes.size() > MAX_ENTRY_BYTES: return _write_error("Prepared scenery exceeds the per-entry size limit.")
	var path: String = entry_path(identity)
	if FileAccess.file_exists(directory) or FileAccess.file_exists(path.get_base_dir()):
		return _write_error("Prepared scenery directory is not writable; using generated geometry.")
	if DirAccess.make_dir_recursive_absolute(path.get_base_dir()) != OK:
		return _write_error("Prepared scenery directory is not writable; using generated geometry.")
	var temporary: String = path + ".tmp-" + str(OS.get_process_id()) + "-" + str(Time.get_ticks_usec())
	var file := FileAccess.open(temporary,FileAccess.WRITE)
	if file == null: return _write_error("Prepared scenery could not be saved; using generated geometry.")
	file.store_buffer(MAGIC)
	file.store_32(1)
	file.store_64(bytes.size())
	file.store_buffer(value_digest(identity).hex_decode())
	file.store_buffer(_digest(bytes))
	file.store_buffer(bytes)
	file.flush()
	var write_error: Error = file.get_error()
	file.close()
	if write_error != OK:
		DirAccess.remove_absolute(temporary)
		return _write_error("Prepared scenery write was incomplete; using generated geometry.")
	# Rename within one directory so readers see a complete old or new file.
	if DirAccess.rename_absolute(temporary,path) != OK:
		DirAccess.remove_absolute(temporary)
		return _write_error("Prepared scenery could not be committed; using generated geometry.")
	writes += 1
	return true

static func _plain_data(value: Variant,depth: int = 0) -> bool:
	if depth > 32: return false
	if value is Dictionary:
		for key: Variant in value:
			if not key is String or not _plain_data(value[key],depth+1): return false
	elif value is Array:
		for item: Variant in value:
			if not _plain_data(item,depth+1): return false
	elif typeof(value) in [TYPE_OBJECT,TYPE_CALLABLE,TYPE_SIGNAL,TYPE_RID]: return false
	return true

func reject_entry(message: String) -> void:
	# Renderers may reject a checksummed payload whose array shape is invalid.
	errors += 1
	last_error = message

func _read_error(message: String) -> Dictionary:
	misses += 1
	errors += 1
	last_error = message
	return {}

func _write_error(message: String) -> bool:
	errors += 1
	last_error = message
	return false

func statistics() -> Dictionary:
	return {"enabled":enabled,"directory":directory,"hits":hits,"misses":misses,"writes":writes,"errors":errors,"error":last_error}
