extends CanvasLayer
signal action_requested(action: String, value: Variant)
signal mode_requested(mode: String)
signal resident_selected(identifier: String)
signal layout_changed

var status: Label
var clock_label: Label
var metrics: Label
var inspector: Label
var pause_button: Button
var speed_picker: OptionButton
var population_picker: OptionButton
var residents_list: ItemList
var mode_buttons: Dictionary = {}
var resident_ids: Array[String] = []
var last_selected: String = ""
var speeds: Array[int] = [1,4,60,600]
var populations: Array[int] = [1,20,200,1000,5000]
var last_snapshot: Dictionary = {}
var geography_label: Label
var city_overview_button: Button
var geography_caption: Label
var left_panel: PanelContainer
var controls_body: VBoxContainer
var inspector_body: VBoxContainer
var compact_clock: Label
var compact_pause: Button
var compact_playback: HBoxContainer
var controls_toggle: Button
var inspector_toggle: Button
var controls_collapsed: bool = false
var inspector_collapsed: bool = false
var configured_id: String = ""
var landmark_records: Dictionary = {}
var compact_status: Label
var compact_notice_until: int = 0
var use_toggle: CheckButton
var use_legend: VBoxContainer
var use_context: RefCounted
var source_link: LinkButton
var source_url: String = ""
var height_link: LinkButton
var height_url: String = ""
var use_legend_labels: Dictionary = {}
var inspector_scroll: ScrollContainer
var place_search: VBoxContainer
var daylight_toggle: CheckButton
var daylight_phase: Label
var facade_toggle: CheckButton
var trees_toggle: CheckButton
var trees_label: Label
var tree_source: LinkButton
var tree_source_url: String = ""
var map_toggle: Button
var map_controls: VBoxContainer
var map_summary: Label
var map_speed: OptionButton
var footer_label: Label
var map_enabled: bool = false
var root_control: Control
var right_panel: PanelContainer
var footer_panel: PanelContainer
var left_scroll: ScrollContainer
var right_scroll: ScrollContainer
var usable_rect := Rect2()
var compact_show_inspector: bool = false

func _ready() -> void:
	var root := Control.new()
	root_control = root
	root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)
	var top := _panel()
	left_panel = top
	top.position = Vector2(22,22)
	top.custom_minimum_size.x = 450
	root.add_child(top)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation",8)
	left_scroll = ScrollContainer.new()
	left_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	left_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	top.add_child(left_scroll)
	content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left_scroll.add_child(content)
	var heading := HBoxContainer.new()
	content.add_child(heading)
	var brand: Label = _label("SAN FRANCISCO",14,Color("7ee2c5"))
	brand.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	heading.add_child(brand)
	map_toggle = _button("4  2D Map")
	map_toggle.pressed.connect(func() -> void: mode_requested.emit("overhead" if map_enabled else "map"))
	heading.add_child(map_toggle)
	controls_toggle = _button("Hide controls")
	controls_toggle.pressed.connect(func() -> void: set_controls_collapsed(not controls_collapsed))
	heading.add_child(controls_toggle)
	place_search = preload("res://place_search.gd").new()
	place_search.place_requested.connect(func(identifier: String,camera_mode: String) -> void: action_requested.emit("place",{"id":identifier,"mode":camera_mode}))
	content.add_child(place_search)
	compact_clock = _label("07:59:50",28)
	content.add_child(compact_clock)
	compact_playback = HBoxContainer.new()
	content.add_child(compact_playback)
	compact_pause = _button("Pause")
	compact_pause.pressed.connect(func() -> void: action_requested.emit("pause",not bool(last_snapshot.get("paused",false))))
	compact_playback.add_child(compact_pause)
	var compact_next: Button = _button("Next activity")
	compact_next.pressed.connect(func() -> void: action_requested.emit("next_event",null))
	compact_playback.add_child(compact_next)
	compact_status = _label("",12,Color("a8dace"))
	compact_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	compact_status.custom_minimum_size.x = 285
	compact_status.visible = false
	content.add_child(compact_status)
	map_controls = VBoxContainer.new()
	map_controls.visible = false
	content.add_child(map_controls)
	map_controls.add_child(_label("2D AGENT MAP",13,Color("7ee2c5")))
	map_summary = _label("Waiting for citizens...",13)
	map_controls.add_child(map_summary)
	map_controls.add_child(_label("WASD / drag: pan · Q/E: rotate · Scroll: zoom",12))
	var map_playback := HBoxContainer.new()
	map_controls.add_child(map_playback)
	map_playback.add_child(_label("Simulation speed",12))
	map_speed = OptionButton.new()
	map_speed.focus_mode = Control.FOCUS_NONE
	for speed: int in speeds: map_speed.add_item("%d×" % speed)
	map_speed.item_selected.connect(func(index: int) -> void: action_requested.emit("speed",speeds[index]))
	map_playback.add_child(map_speed)
	var center_selected: Button = _button("Center selected citizen / building")
	center_selected.pressed.connect(func() -> void: action_requested.emit("map_center_selected",null))
	map_controls.add_child(center_selected)
	use_toggle = CheckButton.new()
	use_toggle.text = "U  Parcel-group use"
	use_toggle.focus_mode = Control.FOCUS_NONE
	use_toggle.disabled = true
	use_toggle.toggled.connect(func(enabled: bool) -> void: action_requested.emit("use_overlay",enabled))
	content.add_child(use_toggle)
	var lighting_row := HBoxContainer.new()
	content.add_child(lighting_row)
	daylight_toggle = CheckButton.new()
	daylight_toggle.text = "Follow daylight"
	daylight_toggle.focus_mode = Control.FOCUS_NONE
	daylight_toggle.set_pressed_no_signal(true)
	daylight_toggle.toggled.connect(func(enabled: bool) -> void: action_requested.emit("lighting",enabled))
	lighting_row.add_child(daylight_toggle)
	daylight_phase = _label("September daylight",12,Color("a8b8c2"))
	lighting_row.add_child(daylight_phase)
	use_legend = VBoxContainer.new()
	use_legend.visible = false
	content.add_child(use_legend)
	var legend_grid := GridContainer.new()
	legend_grid.columns = 2
	legend_grid.add_theme_constant_override("h_separation",16)
	use_legend.add_child(legend_grid)
	var use_data = preload("res://geography_use.gd")
	for i: int in range(use_data.CATEGORIES.size()):
		var category_label: Label = _label("● " + use_data.CATEGORIES[i].replace("_"," ").capitalize(),13,use_data.PALETTE[i])
		category_label.mouse_filter = Control.MOUSE_FILTER_STOP
		legend_grid.add_child(category_label)
		use_legend_labels[use_data.CATEGORIES[i]] = category_label
	use_legend.add_child(_label("DataSF group use; colors do not show occupancy.\nLandmarks keep their architectural materials.",11,Color("a8b8c2")))
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation",8)
	content.add_child(body)
	controls_body = body
	content = body
	content.add_child(_label("San Francisco",28))
	geography_caption = _label("Original architecture · synthetic homes and jobs",13,Color("a8b8c2"))
	content.add_child(geography_caption)
	var locations := HBoxContainer.new()
	content.add_child(locations)
	var city_hall: Button = _button("H  City Hall")
	city_hall.pressed.connect(func() -> void: action_requested.emit("city_hall",null))
	locations.add_child(city_hall)
	city_overview_button = _button("G  City overview")
	city_overview_button.disabled = true
	city_overview_button.pressed.connect(func() -> void: action_requested.emit("city_overview",null))
	locations.add_child(city_overview_button)
	geography_label = _label("City Hall resident pilot",12,Color("a8b8c2"))
	geography_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	geography_label.custom_minimum_size.x = 405
	content.add_child(geography_label)
	facade_toggle = CheckButton.new()
	facade_toggle.text = "Illustrative facades"
	facade_toggle.tooltip_text = "Procedural windows and floor rhythm on nearby building masses. These are original visual details, not observed window, material or floor records. Parcel-use colors and landmark exteriors keep their existing presentation."
	facade_toggle.focus_mode = Control.FOCUS_NONE
	facade_toggle.set_pressed_no_signal(true)
	facade_toggle.toggled.connect(func(enabled: bool) -> void: action_requested.emit("facades",enabled))
	content.add_child(facade_toggle)
	var tree_row := HBoxContainer.new()
	content.add_child(tree_row)
	trees_toggle = CheckButton.new()
	trees_toggle.text = "Street-tree inventory"
	trees_toggle.focus_mode = Control.FOCUS_NONE
	trees_toggle.set_pressed_no_signal(true)
	trees_toggle.toggled.connect(func(enabled: bool) -> void: action_requested.emit("trees",enabled))
	tree_row.add_child(trees_toggle)
	tree_source = LinkButton.new()
	tree_source.text = "DataSF source"
	tree_source.pressed.connect(func() -> void:
		if tree_source_url.begins_with("https://data.sfgov.org/"): OS.shell_open(tree_source_url)
	)
	tree_row.add_child(tree_source)
	trees_label = _label("Optional street-tree inventory",11,Color("a8b8c2"))
	trees_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	trees_label.custom_minimum_size.x = 405
	content.add_child(trees_label)
	clock_label = _label("07:59:50",34)
	content.add_child(clock_label)
	status = _label("Waiting for simulation...",13)
	status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status.custom_minimum_size.x = 405
	content.add_child(status)
	metrics = _label("",14)
	content.add_child(metrics)
	var modes := HBoxContainer.new()
	content.add_child(modes)
	for item: Array in [["overhead","1  Overhead"],["walk","2  Walk"],["follow","3  Follow"],["map","4  Map"]]:
		var button: Button = _button(str(item[1]))
		button.pressed.connect(func() -> void: mode_requested.emit(str(item[0])))
		modes.add_child(button)
		mode_buttons[str(item[0])] = button
	var playback := HBoxContainer.new()
	content.add_child(playback)
	pause_button = _button("Pause")
	pause_button.pressed.connect(func() -> void: action_requested.emit("pause",not bool(last_snapshot.get("paused",false))))
	playback.add_child(pause_button)
	speed_picker = OptionButton.new()
	speed_picker.focus_mode = Control.FOCUS_NONE
	for speed: int in speeds: speed_picker.add_item("%d×" % speed)
	speed_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("speed",speeds[index]))
	playback.add_child(speed_picker)
	var next: Button = _button("Next activity")
	next.pressed.connect(func() -> void: action_requested.emit("next_event",null))
	playback.add_child(next)
	var reset: Button = _button("Reset day")
	reset.pressed.connect(func() -> void: action_requested.emit("reset",null))
	playback.add_child(reset)
	var population_row := HBoxContainer.new()
	content.add_child(population_row)
	population_row.add_child(_label("Restart with",14))
	population_picker = OptionButton.new()
	population_picker.focus_mode = Control.FOCUS_NONE
	for population: int in populations: population_picker.add_item("%d resident%s" % [population,"" if population == 1 else "s"])
	population_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("population",populations[index]))
	population_row.add_child(population_picker)
	var reconnect: Button = _button("Reconnect")
	reconnect.pressed.connect(func() -> void: action_requested.emit("reconnect",null))
	population_row.add_child(reconnect)
	var persistence := HBoxContainer.new()
	content.add_child(persistence)
	var save: Button = _button("F5  Save day")
	save.tooltip_text = "Save the complete resident simulation in the local quick slot."
	save.pressed.connect(func() -> void: action_requested.emit("save","quick"))
	persistence.add_child(save)
	var load: Button = _button("F9  Load day")
	load.tooltip_text = "Restore the quick slot, including the clock, trips and playback state."
	load.pressed.connect(func() -> void: action_requested.emit("load","quick"))
	persistence.add_child(load)
	var side := _panel()
	right_panel = side
	root.add_child(side)
	side.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	side.offset_left = -352
	side.offset_right = -22
	side.offset_top = 22
	side.custom_minimum_size.x = 330
	var side_content := VBoxContainer.new()
	side_content.add_theme_constant_override("separation",8)
	right_scroll = ScrollContainer.new()
	right_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	side.add_child(right_scroll)
	side_content.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_scroll.add_child(side_content)
	var side_heading := HBoxContainer.new()
	side_content.add_child(side_heading)
	var side_label: Label = _label("RESIDENTS & BUILDINGS",14,Color("7ee2c5"))
	side_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	side_heading.add_child(side_label)
	inspector_toggle = _button("Hide")
	inspector_toggle.pressed.connect(func() -> void: set_inspector_collapsed(not inspector_collapsed))
	side_heading.add_child(inspector_toggle)
	inspector_body = VBoxContainer.new()
	inspector_body.add_theme_constant_override("separation",8)
	side_content.add_child(inspector_body)
	side_content = inspector_body
	var search := LineEdit.new()
	search.placeholder_text = "Find a resident by name or ID"
	search.text_changed.connect(_filter_residents)
	side_content.add_child(search)
	residents_list = ItemList.new()
	residents_list.custom_minimum_size = Vector2(284,180)
	residents_list.item_selected.connect(func(index: int) -> void: resident_selected.emit(str(residents_list.get_item_metadata(index))))
	side_content.add_child(residents_list)
	inspector = _label("Choose a person or click a building.",15)
	inspector.custom_minimum_size = Vector2(284,180)
	inspector.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	inspector_scroll = ScrollContainer.new()
	inspector_scroll.custom_minimum_size = Vector2(284,250)
	inspector_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	inspector.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	inspector_scroll.add_child(inspector)
	side_content.add_child(inspector_scroll)
	source_link = LinkButton.new()
	source_link.text = "Open DataSF source"
	source_link.visible = false
	source_link.pressed.connect(func() -> void:
		if source_url.begins_with("https://"): OS.shell_open(source_url)
	)
	side_content.add_child(source_link)
	height_link = LinkButton.new()
	height_link.text = "Architectural height reference"
	height_link.visible = false
	height_link.pressed.connect(func() -> void:
		if height_url.begins_with("https://"): OS.shell_open(height_url)
	)
	side_content.add_child(height_link)
	var footer := _panel()
	footer_panel = footer
	root.add_child(footer)
	footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	footer.offset_left = 22
	footer.offset_right = -22
	footer.offset_top = -67
	footer.offset_bottom = -20
	footer_label = _label("",14)
	var footer_row := HBoxContainer.new()
	footer.add_child(footer_row)
	footer_label.clip_text = true
	footer_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer_row.add_child(footer_label)
	var performance_button: Button = _button("F3 Performance")
	performance_button.pressed.connect(func() -> void: action_requested.emit("performance",null))
	footer_row.add_child(performance_button)
	var inspect_button: Button = _button("Inspector / controls")
	inspect_button.pressed.connect(func() -> void:
		compact_show_inspector = not compact_show_inspector
		layout_changed.emit()
	)
	footer_row.add_child(inspect_button)
	var full_button: Button = _button("F11 Fullscreen")
	full_button.pressed.connect(func() -> void: action_requested.emit("fullscreen",null))
	footer_row.add_child(full_button)
	set_map_mode(false)
	set_controls_collapsed(false)
	set_inspector_collapsed(false)

func set_controls_collapsed(collapsed: bool) -> void:
	controls_collapsed = collapsed
	controls_body.visible = not collapsed
	compact_clock.visible = collapsed
	compact_playback.visible = collapsed
	compact_status.visible = collapsed and Time.get_ticks_msec() < compact_notice_until
	controls_toggle.text = "Controls" if collapsed else "Hide controls"
	left_panel.custom_minimum_size.x = 330 if collapsed else 450
	left_panel.size = Vector2.ZERO
	layout_changed.emit()
	use_legend.visible = collapsed and use_toggle.button_pressed and not map_enabled

func set_inspector_collapsed(collapsed: bool) -> void:
	inspector_collapsed = collapsed
	inspector_body.visible = not collapsed
	inspector_toggle.text = "Show" if collapsed else "Hide"
	right_panel.size.y = 0
	layout_changed.emit()

func toggle_panels() -> void:
	var collapsed: bool = not controls_collapsed or not inspector_collapsed
	set_controls_collapsed(collapsed)
	set_inspector_collapsed(collapsed)

func set_map_mode(enabled: bool) -> void:
	map_enabled = enabled
	map_toggle.text = "1  3D view" if enabled else "4  2D Map"
	map_controls.visible = enabled
	use_toggle.visible = not enabled
	daylight_toggle.get_parent().visible = not enabled
	facade_toggle.visible = not enabled
	trees_toggle.get_parent().visible = not enabled
	trees_label.visible = not enabled
	geography_label.visible = not enabled
	if enabled: use_legend.visible = false
	footer_label.text = "WASD / drag: pan  ·  Q/E: rotate  ·  Shift: faster  ·  Wheel: zoom  ·  Click: inspect  ·  G/H: city / City Hall  ·  1/2/3: 3D views" if enabled else "WASD: move  ·  Q/E: rotate  ·  Shift: faster  ·  Drag: look/orbit  ·  Wheel: zoom  ·  Click: inspect  ·  3: follow/recenter  ·  4: 2D Map"

func update_geography(state: Dictionary) -> void:
	facade_toggle.disabled = not bool(state.get("available",false))
	facade_toggle.set_pressed_no_signal(bool(state.get("facades_enabled",true)))
	var use_state: Dictionary = state.get("land_use",{})
	use_toggle.disabled = not bool(use_state.get("available",false))
	use_toggle.set_pressed_no_signal(bool(use_state.get("enabled",false)))
	use_legend.visible = bool(use_state.get("enabled",false)) and controls_collapsed and not map_enabled
	if use_context != null and use_legend.visible:
		for category: String in use_legend_labels:
			use_legend_labels[category].tooltip_text = str(use_context.manifest.get("categories",{}).get(category,""))
	city_overview_button.disabled = not bool(state.get("available",false))
	if not bool(state.get("available",false)):
		geography_label.text = "City Hall resident pilot" if str(state.get("error","")).is_empty() else "City map unavailable: " + str(state.error)
		if not str(state.get("error","")).is_empty(): set_controls_collapsed(false)
		return
	geography_label.text = "Citywide map · %d / %d tiles cached · %d detailed" % [int(state.get("loaded_tiles",0)),int(state.get("tile_count",0)),int(state.get("detailed_tiles",0))]
	geography_label.text += "\nCity Hall remains an illustrative resident pilot." if bool(state.get("pilot_patch",true)) else "\nObserved geography · generated resident assignments."
	var terrain: Dictionary = state.get("terrain",{})
	if bool(terrain.get("available",false)):
		geography_label.text += "\nElevation grid · %d terrain chunks" % int(terrain.get("loaded_chunks",0))
		if int(terrain.get("pending_chunks",0)) > 0: geography_label.text += " (loading)"
	else: geography_label.text += "\nFlat ground; terrain not loaded."
	if not str(terrain.get("error","")).is_empty():
		geography_label.text += "\n" + str(terrain.error)
		set_controls_collapsed(false)
	if int(state.get("pending_tiles",0)) > 0: geography_label.text += "\nLoading nearby buildings..."
	var visuals: Dictionary = state.get("visuals",{})
	if bool(visuals.get("available",false)):
		geography_label.text += "\n%d distant building silhouettes" % int(visuals.get("silhouette_count",0))
		if int(visuals.get("pending_tiles",0)) > 0: geography_label.text += " (loading)"
	if not str(visuals.get("error","")).is_empty():
		geography_label.text += "\n" + str(visuals.error)
		set_controls_collapsed(false)
	if not str(use_state.get("error","")).is_empty():
		geography_label.text += "\n" + str(use_state.error)
		set_controls_collapsed(false)
	if not str(state.get("landmark_error","")).is_empty():
		geography_label.text += "\n" + str(state.landmark_error)
		set_controls_collapsed(false)
	if not str(state.get("error","")).is_empty(): geography_label.text += "\n" + str(state.error)

func update_lighting(state: Dictionary) -> void:
	daylight_toggle.set_pressed_no_signal(bool(state.get("enabled",false)))
	daylight_toggle.tooltip_text = str(state.get("reference",""))
	daylight_phase.text = str(state.get("phase","fixed")).capitalize()
	daylight_phase.tooltip_text = str(state.get("reference",""))

func update_trees(state: Dictionary) -> void:
	trees_toggle.disabled = not bool(state.get("available",false))
	trees_toggle.set_pressed_no_signal(bool(state.get("enabled",true)))
	tree_source_url = str(state.get("source",""))
	tree_source.visible = not tree_source_url.is_empty()
	var note: String = str(state.get("display_note",""))
	trees_toggle.tooltip_text = note
	trees_label.tooltip_text = note+"\nCoincident source IDs share a silhouette without moving their recorded coordinates. The source is not complete park-tree coverage."
	if bool(state.get("available",false)):
		trees_label.text = "%d nearby instances · %d mapped source records\nCanopy shape, size and color are illustrative." % [int(state.get("displayed_instances",0)),int(state.get("statistics",{}).get("renderable_records",0))]
		if int(state.get("missing_terrain",0)) > 0: trees_label.text += "\n%d locations skipped: missing terrain." % int(state.missing_terrain)
	else: trees_label.text = "Optional street-tree inventory is not installed."
	if not str(state.get("error","")).is_empty():
		trees_label.text = str(state.error)
		set_controls_collapsed(false)

func configure_scenario(scenario: Dictionary) -> void:
	var identity: String = str(scenario.get("id",""))
	if configured_id != identity:
		configured_id = identity
		set_controls_collapsed(identity != "civic-center-walking-day-v1")
		set_inspector_collapsed(identity != "civic-center-walking-day-v1")
	var options: Array = scenario.get("population_presets",[1,20,200,1000,5000])
	populations.clear()
	population_picker.clear()
	for value: Variant in options:
		populations.append(int(value))
		population_picker.add_item("%d resident%s" % [int(value),"" if int(value) == 1 else "s"])
	geography_caption.text = "Original architecture · synthetic homes and jobs" if str(scenario.get("id","")) == "civic-center-walking-day-v1" else "Observed city geometry · synthetic homes and jobs"

func set_status(message: String, is_error: bool = false) -> void:
	if status == null: return
	status.text = message
	var notice: bool = is_error or message.begins_with("Saving") or message.begins_with("Loading") or message.begins_with("Preparing") or message.begins_with("Day saved") or message.begins_with("Saved day restored")
	compact_notice_until = Time.get_ticks_msec()+5000 if notice else 0
	compact_status.text = message
	compact_status.visible = controls_collapsed and notice
	if is_error: set_controls_collapsed(false)
	status.add_theme_color_override("font_color",Color("ffb99e") if is_error else Color("a8dace"))

func update_display(snapshot: Dictionary, crowd: Node, mode: String, selected: String, selected_label: String, frame_ms: float) -> void:
	last_snapshot = snapshot
	var seconds: int = int(snapshot.get("clock_seconds",28790))
	clock_label.text = "%02d:%02d:%02d" % [posmod(seconds / 3600,24),posmod(seconds / 60,60),posmod(seconds,60)]
	if int(snapshot.get("day_index",0)) > 0: clock_label.text = "Day %d  %s" % [int(snapshot.day_index)+1,clock_label.text]
	compact_clock.text = clock_label.text
	compact_status.visible = controls_collapsed and Time.get_ticks_msec() < compact_notice_until
	var home_count: int = 0
	var work_count: int = 0
	var blocked_count: int = 0
	for person: Dictionary in snapshot.get("residents",[]):
		match str(person.get("activity","")):
			"home": home_count += 1
			"at_work": work_count += 1
			"blocked": blocked_count += 1
	metrics.text = "%d residents  ·  %d home  ·  %d at work\n%d outside  ·  %d in view  ·  %d with gait\nTick %d  ·  %.1f ms local frame interval" % [crowd.ids.size(),home_count,work_count,crowd.outdoor_count,crowd.visible_count,crowd.animated_count,int(snapshot.get("tick",0)),frame_ms]
	if mode == "map": metrics.text = "%d residents  ·  %d home  ·  %d at work\n%d outside  ·  %d markers in view\nTick %d  ·  %.1f ms local frame interval" % [crowd.ids.size(),home_count,work_count,crowd.outdoor_count,crowd.visible_count,int(snapshot.get("tick",0)),frame_ms]
	map_summary.text = "%d citizens · %d outside\n%d home · %d at work · %d in view" % [crowd.ids.size(),crowd.outdoor_count,home_count,work_count,crowd.visible_count]
	if blocked_count > 0: metrics.text += "\n%d resident(s) need a reachable route" % blocked_count
	if not crowd.last_error.is_empty(): metrics.text += "\n" + crowd.last_error
	pause_button.text = "Resume" if bool(snapshot.get("paused",false)) else "Pause"
	compact_pause.text = pause_button.text
	var speed_index: int = speeds.find(int(snapshot.get("speed",1)))
	if speed_index >= 0:
		speed_picker.select(speed_index)
		map_speed.select(speed_index)
	var population_index: int = populations.find(crowd.ids.size())
	if population_index >= 0: population_picker.select(population_index)
	for key: String in mode_buttons: mode_buttons[key].modulate = Color("7ee2c5") if key == mode else Color.WHITE
	if resident_ids != crowd.ids:
		resident_ids.assign(crowd.ids)
		_filter_residents("")
	inspector.text = "INSPECT\n" + selected_label
	source_url = ""
	var observed_use: Dictionary = use_context.record_for(selected.trim_prefix("geography:")) if use_context != null else {}
	if crowd.records.has(selected):
		var person: Dictionary = crowd.records[selected]
		var activity: String = str(person.get("activity", "unknown")).replace("_"," ")
		inspector.text = "%s\n%s\n\n%s\nHome: %s\nWork: %s" % [person.get("label",selected),selected,activity.capitalize(),_building_label(str(person.get("home_id",""))),_building_label(str(person.get("work_id","")))]
		inspector.text += "\nInside building" if not bool(person.get("visible",false)) else "\nOutside · visible in the world"
		if person.get("trip") is Dictionary:
			inspector.text += "\nDestination: " + _building_label(str(person.trip.get("destination_id","")))
		if person.get("blocked_reason") != null and not str(person.blocked_reason).is_empty(): inspector.text += "\n" + str(person.blocked_reason)
		if mode == "follow": inspector.text += "\n\nFollowing this resident"
	else:
		for building: Dictionary in snapshot.get("buildings",[]):
			if str(building.id) == selected:
				var homes: int = 0
				var jobs: int = 0
				for person: Dictionary in snapshot.get("residents",[]):
					if str(person.get("home_id","")) == selected: homes += 1
					if str(person.get("work_id","")) == selected: jobs += 1
				inspector.text = "%s\nSource ID: %s\n\n%d modeled residents inside\nAssigned homes: %d · jobs: %d\nCounts cover the simulation cohort." % [building.get("label",selected),selected,int(building.get("occupancy",0)),homes,jobs]
				if observed_use.is_empty() and building.get("land_use") is Dictionary:
					observed_use = {"land_use":building.land_use}
				if landmark_records.has(selected):
					var landmark: Dictionary = landmark_records[selected]
					inspector.text += "\n\nExterior height: %.1f m\n%s" % [float(landmark.get("height_m",0.0)),landmark.get("source_note","")]
	if observed_use.is_empty() and use_context != null and use_context.available and (selected.begins_with("geography:") or selected.begins_with("sf-building:")):
		observed_use = {"category":"unknown"}
	if not observed_use.is_empty() and not crowd.records.has(selected):
		inspector.text += "\n\n" + preload("res://geography_use.gd").describe(observed_use)
		source_url = str(observed_use.get("land_use",{}).get("source_url",""))
	source_link.visible = source_url.begins_with("https://")
	source_link.tooltip_text = source_url
	height_url = str(landmark_records.get(selected,{}).get("height_reference",{}).get("url",""))
	height_link.visible = height_url.begins_with("https://")
	height_link.tooltip_text = str(landmark_records.get(selected,{}).get("height_reference",{}).get("title",""))
	if selected != last_selected:
		last_selected = selected
		inspector_scroll.scroll_vertical = 0
		for i: int in range(residents_list.item_count):
			if str(residents_list.get_item_metadata(i)) == selected:
				residents_list.select(i)
				residents_list.ensure_current_is_visible()

func _building_label(identifier: String) -> String:
	for building: Dictionary in last_snapshot.get("buildings",[]):
		if str(building.id) == identifier: return str(building.get("label",identifier))
	return identifier

func _filter_residents(query: String) -> void:
	if residents_list == null: return
	residents_list.clear()
	var needle: String = query.to_lower().strip_edges()
	for person: Dictionary in last_snapshot.get("residents",[]):
		var identifier: String = str(person.id)
		var label: String = str(person.get("label",identifier))
		if needle.is_empty() or needle in identifier.to_lower() or needle in label.to_lower():
			var index: int = residents_list.add_item(label)
			residents_list.set_item_metadata(index,identifier)
			if identifier == last_selected: residents_list.select(index)

func _button(text_value: String) -> Button:
	var button := Button.new()
	button.text = text_value
	button.focus_mode = Control.FOCUS_NONE
	button.custom_minimum_size.y = 34
	return button

func _label(text_value: String, size: int, color_value: Color = Color("e7efed")) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size",size)
	label.add_theme_color_override("font_color",color_value)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return label

func _panel() -> PanelContainer:
	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.035,0.075,0.11,0.94)
	style.border_color = Color(0.22,0.42,0.44,0.85)
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	style.content_margin_left = 18
	style.content_margin_right = 18
	style.content_margin_top = 14
	style.content_margin_bottom = 14
	panel.add_theme_stylebox_override("panel",style)
	return panel

func layout(view_size: Vector2, dock: Rect2 = Rect2()) -> void:
	if left_panel == null or right_panel == null: return
	var area := Rect2(Vector2(12,12),Vector2(maxf(1,view_size.x-24),maxf(120,view_size.y-98)))
	if dock.has_area():
		if dock.position.y <= 12.0 and dock.position.x > view_size.x*0.5:
			area.size.x = maxf(200,dock.position.x-24)
		else:
			area.size.y = maxf(120,dock.position.y-24)
	var compact: bool = area.size.x < 1150
	left_panel.visible = not compact or not compact_show_inspector
	right_panel.visible = not compact or compact_show_inspector
	var left_width: float = 450.0 if not controls_collapsed else 350.0
	left_panel.position = area.position
	left_panel.custom_minimum_size.x = left_width
	left_panel.size = Vector2(left_width,area.size.y)
	right_panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	right_panel.position = Vector2(area.end.x-330,area.position.y)
	right_panel.size = Vector2(330,area.size.y)
	footer_panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	footer_panel.position = Vector2(12,view_size.y-74)
	footer_panel.size = Vector2(view_size.x-24,62)
	var left_edge: float = left_panel.position.x+left_panel.size.x+12 if left_panel.visible else area.position.x
	var right_edge: float = right_panel.position.x-12 if right_panel.visible else area.end.x
	usable_rect = Rect2(Vector2(left_edge,area.position.y),Vector2(maxf(1,right_edge-left_edge),area.size.y))

func content_rect() -> Rect2:
	return usable_rect
