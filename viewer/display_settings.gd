extends Node
## Local presentation preferences; never modifies a saved simulation.
signal changed
const PATH: String = "user://display-settings.json"
var scale_value: float = 1.0
var persist_enabled: bool = true
var windowed_size := Vector2i(1440,900)
var windowed_position := Vector2i(80,80)
var elapsed: float = 0.0
var last_saved: String = ""
var last_state: Dictionary = {}

func initialize(arguments: PackedStringArray) -> void:
	persist_enabled = "--no-display-settings" not in arguments and "--smoke-test" not in arguments and "--workspace-probe" not in arguments and DisplayServer.get_name() != "headless"
	var settings: Dictionary = {}
	if persist_enabled and FileAccess.file_exists(PATH):
		var file := FileAccess.open(PATH,FileAccess.READ)
		if file != null and file.get_length() < 4096:
			var parsed: Variant = JSON.parse_string(file.get_as_text())
			if parsed is Dictionary: settings = parsed
	var size_text: String = option(arguments,"--window-size","")
	if not size_text.is_empty():
		var parts: PackedStringArray = size_text.to_lower().split("x")
		if parts.size() == 2 and parts[0].is_valid_int() and parts[1].is_valid_int(): windowed_size = Vector2i(int(parts[0]),int(parts[1]))
	elif valid_pair(settings.get("size")):
		windowed_size = Vector2i(int(settings["size"][0]),int(settings["size"][1]))
	if valid_pair(settings.get("position")): windowed_position = Vector2i(int(settings["position"][0]),int(settings["position"][1]))
	var scale_text: String = option(arguments,"--ui-scale",str(settings.get("scale",1.0)))
	var requested_scale: float = float(scale_text) if scale_text.is_valid_float() else 1.0
	set_scale(requested_scale,false)
	var window := get_window()
	window.min_size = Vector2i(960,540)
	window.unresizable = false
	if DisplayServer.get_name() != "headless":
		var area: Rect2i = DisplayServer.screen_get_usable_rect()
		windowed_size = Vector2i(clampi(windowed_size.x,960,maxi(960,area.size.x)),clampi(windowed_size.y,540,maxi(540,area.size.y)))
		windowed_position = Vector2i(clampi(windowed_position.x,area.position.x,maxi(area.position.x,area.end.x-windowed_size.x)),clampi(windowed_position.y,area.position.y,maxi(area.position.y,area.end.y-windowed_size.y)))
		window.size = windowed_size
		window.position = windowed_position
		set_mode(option(arguments,"--window-mode",str(settings.get("mode","windowed"))),false)

static func option(arguments: PackedStringArray, name_value: String, fallback: String) -> String:
	var index: int = arguments.find(name_value)
	return arguments[index+1] if index >= 0 and index+1 < arguments.size() else fallback

func set_scale(value: float, save: bool = true) -> void:
	if not is_finite(value): value = 1.0
	scale_value = [1.0,1.25,1.5][clampi(roundi((value-1.0)/0.25),0,2)]
	get_window().content_scale_factor = scale_value
	changed.emit()
	if save: persist()

func set_mode(value: String, save: bool = true) -> void:
	var window := get_window()
	if window.mode == Window.MODE_WINDOWED:
		windowed_size = window.size
		windowed_position = window.position
	match value:
		"fullscreen": window.mode = Window.MODE_FULLSCREEN
		"maximized": window.mode = Window.MODE_MAXIMIZED
		_:
			window.mode = Window.MODE_WINDOWED
			window.size = windowed_size
			window.position = windowed_position
	changed.emit()
	if save: persist()

func toggle_fullscreen() -> void:
	set_mode("windowed" if get_window().mode == Window.MODE_FULLSCREEN else "fullscreen")

func state() -> Dictionary:
	var window := get_window()
	if window == null or get_viewport() == null: return last_state.duplicate()
	last_state = {"window_pixels":[window.size.x,window.size.y],"viewport_size":[get_viewport().get_visible_rect().size.x,get_viewport().get_visible_rect().size.y],"ui_scale":scale_value,"window_mode":window.mode,"vsync_mode":DisplayServer.window_get_vsync_mode(),"frame_cap":Engine.max_fps}
	return last_state.duplicate()

func _process(delta: float) -> void:
	elapsed += delta
	if elapsed >= 2.0:
		elapsed = 0.0
		persist()

func persist() -> void:
	if not persist_enabled: return
	var window := get_window()
	if window == null: return
	if window.mode == Window.MODE_WINDOWED:
		windowed_size = window.size
		windowed_position = window.position
	var mode_name: String = "fullscreen" if window.mode == Window.MODE_FULLSCREEN else ("maximized" if window.mode == Window.MODE_MAXIMIZED else "windowed")
	var data: String = JSON.stringify({"schema_version":1,"size":[windowed_size.x,windowed_size.y],"position":[windowed_position.x,windowed_position.y],"mode":mode_name,"scale":scale_value})
	if data == last_saved: return
	var file := FileAccess.open(PATH,FileAccess.WRITE)
	if file != null:
		file.store_string(data)
		last_saved = data

func _exit_tree() -> void:
	persist()

static func valid_pair(value: Variant) -> bool:
	if not value is Array or value.size() != 2: return false
	for number: Variant in value:
		if not (number is int or number is float) or not is_finite(float(number)) or absf(float(number)) > 100000: return false
	return true
