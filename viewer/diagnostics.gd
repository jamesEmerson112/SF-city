extends PanelContainer
## Observation and explicit actions; bounded UI history and no executable prompt.
signal action_requested(action: String, value: Variant)
signal layout_changed
const Chart = preload("res://diagnostic_chart.gd")
const LOG_LIMIT: int = 300
var target_population: SpinBox
var apply_button: Button
var population_label: Label
var summary: Label
var hardware_headline: Label
var workspace: BoxContainer
var controls_scroll: ScrollContainer
var metric_tabs: TabContainer
var chart_grid: GridContainer
var hardware_label: Label
var transport_label: Label
var feed_label: Label
var log_text: RichTextLabel
var search: LineEdit
var severity: OptionButton
var source_filter: OptionButton
var freeze_scroll: CheckButton
var charts: Array[Control] = []
var local_series: Array[Dictionary] = []
var logs: Array[Dictionary] = []
var log_ids: Dictionary = {}
var dropped: int = 0
var cleared_before: float = -1.0
var inventory: Dictionary = {}
var hardware: Dictionary = {}
var feed_status: Dictionary = {}
var hardware_received_msec: int = 0
var latest_run_id: String = ""
var current_count: int = 0
var roster_revision: int = 0
var pending: bool = false
var supported: bool = false
var wide: bool = false
var preferred_width: float = 420.0
var preferred_height: float = 330.0
var resize_drag: bool = false
var display_configuration: Dictionary = {}
var scale_picker: OptionButton
var mode_picker: OptionButton
var hardware_age_at_receipt: float = 0.0
var _dirty_logs: bool = true
var _local_count: int = 0
var target_initialized: bool = false
var target_edited: bool = false

func _ready() -> void:
	size = Vector2(1000,330)
	mouse_filter = Control.MOUSE_FILTER_STOP
	var style := StyleBoxFlat.new()
	style.bg_color = Color("14252ff5")
	style.border_color = Color("426b70")
	style.set_border_width_all(1)
	style.set_content_margin_all(10)
	add_theme_stylebox_override("panel",style)
	var body := VBoxContainer.new()
	add_child(body)
	var heading := HBoxContainer.new()
	body.add_child(heading)
	var title := _label("PERFORMANCE  /  F3")
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(title)
	var grip := _button("Resize",func() -> void: pass)
	grip.tooltip_text = "Drag to resize this dock"
	grip.gui_input.connect(_resize_input)
	heading.add_child(grip)
	heading.add_child(_button("Close",func() -> void: set_open(false)))
	feed_label = _label("Local viewer metrics available")
	feed_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(feed_label)
	hardware_headline = _label("CPU unavailable / RAM unavailable / GPU unavailable")
	hardware_headline.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(hardware_headline)
	workspace = BoxContainer.new()
	workspace.size_flags_vertical = Control.SIZE_EXPAND_FILL
	workspace.add_theme_constant_override("separation",12)
	body.add_child(workspace)
	controls_scroll = ScrollContainer.new()
	controls_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	controls_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	workspace.add_child(controls_scroll)
	var controls := VBoxContainer.new()
	controls.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	controls_scroll.add_child(controls)
	var population_row := HBoxContainer.new()
	controls.add_child(population_row)
	population_row.add_child(_label("Target"))
	target_population = SpinBox.new()
	target_population.min_value = 1
	target_population.max_value = 5000
	target_population.step = 1
	target_population.value = 200
	target_population.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	target_population.get_line_edit().placeholder_text = "Citizens"
	target_population.get_line_edit().text_changed.connect(func(_text: String) -> void: target_edited = true)
	population_row.add_child(target_population)
	apply_button = _button("Apply live",_apply_population)
	population_row.add_child(apply_button)
	var steps := HFlowContainer.new()
	controls.add_child(steps)
	for step_value: int in [-1000,-100,100,1000]:
		var step: int = step_value
		steps.add_child(_button("%+d" % step,func() -> void:
			target_edited = true
			target_population.value = clampf(target_population.value+step,target_population.min_value,target_population.max_value)))
	population_label = _label("Connect to a live simulation to change its population")
	population_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	controls.add_child(population_label)
	var actions := HFlowContainer.new()
	controls.add_child(actions)
	for pair: Array in [["Pause / resume","toggle_pause"],["Next activity","next_event"],["2D / 3D","toggle_map"],["Save","save"],["Load","load"],["Record point","comparison"],["Open run log","open_run_log"]]:
		var action: String = str(pair[1])
		actions.add_child(_button(str(pair[0]),func() -> void: action_requested.emit(action,"quick" if action in ["save","load"] else null)))
	var speed := OptionButton.new()
	speed.focus_mode = Control.FOCUS_NONE
	for value: int in [1,4,60,600]: speed.add_item("%dx speed" % value)
	speed.item_selected.connect(func(index: int) -> void: action_requested.emit("speed",[1,4,60,600][index]))
	actions.add_child(speed)
	var display_row := HFlowContainer.new()
	controls.add_child(display_row)
	scale_picker = OptionButton.new()
	for value: int in [100,125,150]: scale_picker.add_item("UI %d%%" % value)
	scale_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("ui_scale",[1.0,1.25,1.5][index]))
	display_row.add_child(scale_picker)
	mode_picker = OptionButton.new()
	for mode_name: String in ["Windowed","Maximized","Fullscreen"]: mode_picker.add_item(mode_name)
	mode_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("window_mode",["windowed","maximized","fullscreen"][index]))
	display_row.add_child(mode_picker)
	metric_tabs = TabContainer.new()
	metric_tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	metric_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	workspace.add_child(metric_tabs)
	var number_scroll := ScrollContainer.new()
	number_scroll.name = "Charts"
	number_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	metric_tabs.add_child(number_scroll)
	var numbers := VBoxContainer.new()
	numbers.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	number_scroll.add_child(numbers)
	summary = _label("")
	summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	numbers.add_child(summary)
	chart_grid = GridContainer.new()
	chart_grid.columns = 3
	numbers.add_child(chart_grid)
	for label_value: String in ["Frame p95 ms","System CPU %","GPU adapter %"]:
		var chart := Chart.new()
		chart.title = label_value
		chart.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		chart_grid.add_child(chart)
		charts.append(chart)
	var detail_scroll := ScrollContainer.new()
	detail_scroll.name = "Details"
	detail_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	metric_tabs.add_child(detail_scroll)
	var details := VBoxContainer.new()
	details.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	detail_scroll.add_child(details)
	hardware_label = _label("")
	hardware_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	details.add_child(hardware_label)
	transport_label = _label("")
	transport_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	details.add_child(transport_label)
	var log_scroll := ScrollContainer.new()
	log_scroll.name = "Logs"
	log_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	metric_tabs.add_child(log_scroll)
	var log_panel := VBoxContainer.new()
	log_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	log_scroll.add_child(log_panel)
	search = LineEdit.new()
	search.placeholder_text = "Filter log text"
	search.text_changed.connect(func(_value: String) -> void: _dirty_logs = true)
	log_panel.add_child(search)
	var filters := HFlowContainer.new()
	log_panel.add_child(filters)
	severity = OptionButton.new()
	for label_value: String in ["All levels","info","warning","error"]: severity.add_item(label_value)
	severity.item_selected.connect(func(_index: int) -> void: _dirty_logs = true)
	filters.add_child(severity)
	source_filter = OptionButton.new()
	for label_value: String in ["All sources","viewer","launcher","worker","preparation","hardware"]: source_filter.add_item(label_value)
	source_filter.item_selected.connect(func(_index: int) -> void: _dirty_logs = true)
	filters.add_child(source_filter)
	freeze_scroll = CheckButton.new()
	freeze_scroll.text = "Pause scroll"
	filters.add_child(freeze_scroll)
	filters.add_child(_button("Clear view",clear_visible_logs))
	log_text = RichTextLabel.new()
	log_text.bbcode_enabled = false
	log_text.selection_enabled = true
	log_text.custom_minimum_size = Vector2(0,160)
	log_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	log_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	log_panel.add_child(log_text)
	visible = false

func _label(value: String) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size",13)
	return label

func _button(value: String, callback: Callable) -> Button:
	var button := Button.new()
	button.text = value
	button.focus_mode = Control.FOCUS_NONE
	button.custom_minimum_size.y = 30
	button.pressed.connect(callback)
	return button

func set_open(value: bool) -> void:
	visible = value
	_dirty_logs = true
	layout_changed.emit()

func layout(view_size: Vector2) -> Rect2:
	wide = view_size.x >= 1700.0
	workspace.vertical = wide
	controls_scroll.custom_minimum_size = Vector2(0,195) if wide else Vector2(clampf(view_size.x*0.27,250,340),0)
	controls_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL if wide else Control.SIZE_FILL
	controls_scroll.size_flags_vertical = Control.SIZE_FILL if wide else Control.SIZE_EXPAND_FILL
	metric_tabs.custom_minimum_size = Vector2(0,100)
	chart_grid.columns = 1 if wide else 3
	if wide:
		var target := Vector2(clampf(preferred_width,340.0,view_size.x*0.36),maxf(160,view_size.y-98))
		size = target
		set_deferred("size",target)
		position = Vector2(view_size.x-target.x-12,12)
	else:
		var target := Vector2(maxf(300,view_size.x-24),clampf(preferred_height,170.0,maxf(170,view_size.y*0.55)))
		size = target
		set_deferred("size",target)
		position = Vector2(12,view_size.y-target.y-86)
	return Rect2(position,Vector2(view_size.x-position.x-12,view_size.y-position.y-86) if not wide else Vector2(view_size.x-position.x-12,view_size.y-98)) if visible else Rect2()

func _resize_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT: resize_drag = event.pressed
	if event is InputEventMouseMotion and resize_drag:
		if wide: preferred_width -= event.relative.x
		else: preferred_height -= event.relative.y
		layout_changed.emit()

func set_population_status(message: String, waiting: bool) -> void:
	pending = waiting
	population_label.text = message
	apply_button.disabled = pending or not supported
	target_population.editable = not pending and supported

func update_local(report: Dictionary, snapshot: Dictionary, scene: Dictionary) -> void:
	current_count = int(snapshot.get("population",snapshot.get("residents",[]).size()))
	roster_revision = int(snapshot.get("roster_revision",scene.get("roster_revision",0)))
	if not target_initialized and current_count > 0:
		if not target_edited: target_population.value = current_count
		target_initialized = true
	var capabilities: Dictionary = scene.get("capabilities",{})
	supported = bool(capabilities.get("set_population",false))
	target_population.max_value = int(capabilities.get("population_max",5000))
	apply_button.disabled = pending or not supported
	target_population.editable = not pending and supported
	if not pending: population_label.text = "%d current / revision %d. Synthetic load experiment; day continues." % [current_count,roster_revision] if supported else "%d citizens. Live changes unavailable in this connection." % current_count
	if not visible: return
	var performance: Dictionary = report.get("performance",{})
	var presentation: Dictionary = report.get("presentation",{})
	scale_picker.select(clampi(roundi((float(presentation.get("ui_scale",1.0))-1.0)/0.25),0,2))
	mode_picker.select(2 if int(presentation.get("window_mode",0)) == Window.MODE_FULLSCREEN else (1 if int(presentation.get("window_mode",0)) == Window.MODE_MAXIMIZED else 0))
	var worker: Dictionary = snapshot.get("worker_metrics",{})
	var p95: float = float(performance.get("p95_ms",-1.0))
	var p50: float = float(performance.get("p50_ms",-1.0))
	summary.text = "%d citizens / %d outside / %s at %.1fx requested\nCallback p50 %s / p95 %s / p99 %s ms; %.1f derived FPS\n%d frames / %d draws / %d primitives; GPU time unavailable" % [current_count,int(report.get("simulation",{}).get("outdoor_count",0)),"paused" if bool(snapshot.get("paused",false)) else "running",float(snapshot.get("speed",1)),_number(p50),_number(p95),_number(performance.get("p99_ms")),1000.0/p50 if p50 > 0 else 0.0,int(performance.get("samples",0)),int(presentation.get("render_draw_calls",0)),int(presentation.get("render_primitives",0))]
	transport_label.text = _transport_text(performance,worker)
	local_series.append({"at_msec":Time.get_ticks_msec(),"p95_ms":p95,"population":current_count,"revision":roster_revision})
	if local_series.size() > 120: local_series.pop_front()
	charts[0].push(p95)
	charts[1].push(float(hardware.get("cpu",{}).get("percent",-1.0)) if _hardware_live() and hardware.get("cpu",{}).get("percent") != null else -1.0)
	var adapters: Array = hardware.get("gpu",{}).get("adapters",[])
	var gpu: Dictionary = adapters[0] if not adapters.is_empty() else {}
	charts[2].push(float(gpu.get("gpu_utilization_percent",-1.0)) if _hardware_live() and gpu.get("gpu_utilization_percent") != null else -1.0)
	_refresh_hardware()
	_refresh_logs()

func receive_telemetry(message: Dictionary) -> void:
	var next_run: String = str(message.get("run_id",""))
	if next_run != latest_run_id:
		cleared_before = -1.0
	latest_run_id = next_run
	dropped = maxi(dropped,int(message.get("dropped_events",0)))
	var payload: Dictionary = message.get("payload",{})
	match str(message.get("kind","")):
		"snapshot":
			inventory = payload.get("inventory",{})
			hardware = payload.get("hardware",{})
			feed_status = payload.get("status",{})
			for row: Dictionary in payload.get("logs",[]): append_log(row)
			if not hardware.is_empty(): hardware_received_msec = Time.get_ticks_msec()
		"hardware":
			hardware = payload
			hardware_received_msec = Time.get_ticks_msec()
		"inventory": inventory = payload
		"status": feed_status = payload
		"log": append_log(payload)
		"phase": append_log({"id":"phase-"+str(message.get("sequence")),"at":message.get("at",""),"elapsed_seconds":message.get("elapsed_seconds",0),"source":"launcher","severity":"info","message":"Experiment phase: "+JSON.stringify(payload).left(500)})

	if str(message.get("kind","")) in ["snapshot","hardware"]:
		hardware_age_at_receipt = maxf(0.0,float(message.get("elapsed_seconds",0))-float(hardware.get("elapsed_seconds",0)))
		if hardware.get("collected_at_unix") is float or hardware.get("collected_at_unix") is int:
			hardware_age_at_receipt = maxf(0.0,Time.get_unix_time_from_system()-float(hardware.collected_at_unix))

func append_log(row: Dictionary) -> void:
	var identifier: String = latest_run_id+":"+str(row.get("id",""))
	if log_ids.has(identifier) or float(row.get("elapsed_seconds",0)) <= cleared_before: return
	var safe: Dictionary = {"id":identifier,"at":str(row.get("at","")).left(40),"elapsed_seconds":row.get("elapsed_seconds",0),"source":str(row.get("source","launcher")).left(30),"severity":str(row.get("severity","info")).left(20),"message":str(row.get("message","")).left(1800)}
	log_ids[identifier] = true
	logs.append(safe)
	if logs.size() > LOG_LIMIT:
		log_ids.erase(str(logs[0].id))
		logs.pop_front()
		dropped += 1
	_dirty_logs = true

func clear_visible_logs() -> void:
	for row: Dictionary in logs: cleared_before = maxf(cleared_before,float(row.elapsed_seconds))
	logs.clear()
	log_ids.clear()
	_dirty_logs = true
	_refresh_logs()

func _refresh_logs() -> void:
	if not visible or not _dirty_logs: return
	_dirty_logs = false
	var lines := PackedStringArray()
	var query: String = search.text.to_lower()
	for row: Dictionary in logs:
		if severity.selected > 0 and str(row.severity) != severity.get_item_text(severity.selected): continue
		if source_filter.selected > 0 and str(row.source) != source_filter.get_item_text(source_filter.selected): continue
		var line: String = "%s [%s/%s] %s" % [row.at,row.source,row.severity,row.message]
		if not query.is_empty() and not query in line.to_lower(): continue
		lines.append(line)
	var previous: float = log_text.get_v_scroll_bar().value
	log_text.text = "\n".join(lines)
	if freeze_scroll.button_pressed: log_text.get_v_scroll_bar().value = previous
	else: log_text.scroll_to_line(maxi(0,log_text.get_line_count()-1))

func _refresh_hardware() -> void:
	var age: float = _hardware_age()
	var interval: float = float(feed_status.get("hardware_interval_seconds",1.0))
	var state: String = "unavailable" if hardware.is_empty() else ("STALE" if age > maxf(3.0,interval*3.0) else "live")
	var cpu: Dictionary = hardware.get("cpu",{})
	var memory: Dictionary = hardware.get("memory",{})
	var adapters: Array = hardware.get("gpu",{}).get("adapters",[])
	var gpu: Dictionary = adapters[0] if not adapters.is_empty() else {}
	hardware_headline.text = "CPU %s%% / RAM %s%% / GPU %s%% / VRAM %s MiB  |  %s, age %s s" % [_number(cpu.get("percent")),_number(memory.get("percent")),_number(gpu.get("gpu_utilization_percent")),_number(float(gpu.vram_used_bytes)/1048576.0 if gpu.get("vram_used_bytes") != null else null),state,_number(age)]
	hardware_label.text = "HARDWARE / %s / age %s s\nSystem CPU %s%% / RAM %s%%\nGPU adapter %s%% / VRAM %s MiB\nGPU %s C / %s W\nCPU sensors: %s / GPU: %s\nProcess readings (CPU 100%% = one core):\n%s\nDisk: %s" % [state,_number(age),_number(cpu.get("percent")),_number(memory.get("percent")),_number(gpu.get("gpu_utilization_percent")),_number(float(gpu.vram_used_bytes)/1048576.0 if gpu.get("vram_used_bytes") != null else null),_number(gpu.get("temperature_c")),_number(gpu.get("power_watts")),hardware.get("sensors",{}).get("temperatures",{}).get("status","unavailable"),hardware.get("gpu",{}).get("status","unavailable"),_process_text(),_disk_text()]

func _process_text() -> String:
	var rows := PackedStringArray()
	for item: Dictionary in hardware.get("processes",{}).get("items",[]):
		rows.append("%s: %s%% CPU / %s MiB RSS" % [item.get("role","process"),_number(item.get("cpu",{}).get("percent")),_number(float(item.memory.rss_bytes)/1048576.0 if item.get("memory",{}).get("rss_bytes") != null else null)])
	return "\n".join(rows) if not rows.is_empty() else "unavailable"

func _number(value: Variant) -> String:
	return "%.1f" % float(value) if (value is int or value is float) and is_finite(float(value)) and float(value) >= 0 else "unavailable"

func refresh_feed_label(connection: String, age: float) -> void:
	if visible: feed_label.text = "%s / message age %s s / %d dropped or evicted log entries" % [connection,_number(age),dropped]

func _hardware_age() -> float:
	return hardware_age_at_receipt+float(Time.get_ticks_msec()-hardware_received_msec)/1000.0 if hardware_received_msec > 0 else -1.0

func _hardware_live() -> bool:
	return not hardware.is_empty() and _hardware_age() >= 0 and _hardware_age() <= maxf(3.0,float(feed_status.get("hardware_interval_seconds",1.0))*3.0)

func _apply_population() -> void:
	var raw: String = target_population.get_line_edit().text.strip_edges()
	if not raw.is_valid_int() or int(raw) < int(target_population.min_value) or int(raw) > int(target_population.max_value):
		set_population_status("Enter a whole population between %d and %d." % [int(target_population.min_value),int(target_population.max_value)],false)
		return
	target_population.value = int(raw)
	action_requested.emit("set_population",int(raw))

func _transport_text(performance: Dictionary, worker: Dictionary) -> String:
	var decoder: Dictionary = performance.get("decoder",{})
	var lines := PackedStringArray([
		"WORKER",
		"Advance %s ms / snapshot %s ms / encode %s ms" % [_number(worker.get("advance_ms")),_number(worker.get("snapshot_ms")),_number(worker.get("encode_ms"))],
		"Achieved %s simulated seconds / wall second since current settings" % _number(worker.get("simulated_seconds_per_wall_second")),
		"Snapshot %s KiB / queued %s KiB" % [_scaled(worker.get("snapshot_bytes"),1024),_scaled(worker.get("transport_queue_bytes"),1024)],
		"Route cache %s entries / geometry %s MiB" % [_number(worker.get("route_cache_entries")),_scaled(worker.get("geometry_cache_bytes"),1048576)],
		"DECODER",
		"Input %s KiB / output %s KiB / coalesced %s snapshots" % [_scaled(decoder.get("input_bytes"),1024),_scaled(decoder.get("output_bytes"),1024),_number(decoder.get("coalesced_snapshots"))],
		"VIEWER CPU p95 (ms)"
	])
	var phases: Dictionary = performance.get("cpu_phases_ms",{})
	for name_value: String in phases:
		lines.append("%s: %s" % [name_value.replace("_"," "),_number(phases[name_value].get("p95"))])
	return "\n".join(lines)

func _scaled(value: Variant, divisor: float) -> String:
	return _number(float(value)/divisor) if value is float or value is int else "unavailable"

func _disk_text() -> String:
	var rates: Dictionary = hardware.get("disk",{}).get("rates",{})
	return "%s / read %s MiB/s / write %s MiB/s (system)" % [rates.get("status","unavailable"),_scaled(rates.get("read_bytes_per_second"),1048576),_scaled(rates.get("write_bytes_per_second"),1048576)]
