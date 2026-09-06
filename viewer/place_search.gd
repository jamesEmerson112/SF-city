extends VBoxContainer
signal place_requested(identifier: String, camera_mode: String)
var places: RefCounted
var search_box: LineEdit
var results: ItemList
var detail: Label
var links: HBoxContainer
var active_id: String = ""
var source_url: String = ""
var source_button: LinkButton
var activity_label: Label

func _ready() -> void:
	search_box = LineEdit.new()
	search_box.placeholder_text = "Find a place or landmark"
	search_box.text_changed.connect(_filter)
	search_box.focus_entered.connect(func() -> void: _filter(search_box.text))
	search_box.text_submitted.connect(func(query: String) -> void:
		if places == null: return
		var record: Dictionary = places.resolve(query)
		if not record.is_empty(): _choose(str(record.id))
		else:
			detail.text = places.last_error
			detail.visible = true
	)
	add_child(search_box)
	results = ItemList.new()
	results.custom_minimum_size = Vector2(285,180)
	results.add_theme_font_size_override("font_size",13)
	results.visible = false
	results.item_selected.connect(func(index: int) -> void: _choose(str(results.get_item_metadata(index))))
	add_child(results)
	detail = Label.new()
	detail.add_theme_font_size_override("font_size",12)
	detail.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	detail.custom_minimum_size.x = 285
	detail.visible = false
	add_child(detail)
	links = HBoxContainer.new()
	links.visible = false
	add_child(links)
	var walk := Button.new()
	walk.text = "Walk nearby street"
	walk.focus_mode = Control.FOCUS_NONE
	walk.tooltip_text = "Start on a nearby source street node. This is not a surveyed park entrance."
	walk.pressed.connect(func() -> void: place_requested.emit(active_id,"walk"))
	links.add_child(walk)
	var source := LinkButton.new()
	source_button = source
	source.text = "DataSF source"
	source.pressed.connect(func() -> void:
		if source_url.begins_with("https://"): OS.shell_open(source_url)
	)
	links.add_child(source)
	activity_label = Label.new()
	activity_label.add_theme_font_size_override("font_size",11)
	activity_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	activity_label.custom_minimum_size.x = 285
	activity_label.visible = false
	add_child(activity_label)
	visible = false

func configure(value: RefCounted) -> void:
	places = value
	visible = places.available or not places.last_error.is_empty()
	search_box.editable = places.available
	if not places.last_error.is_empty():
		detail.text = places.last_error
		detail.visible = true

func _filter(query: String) -> void:
	if places == null or not places.available: return
	results.clear()
	for record: Dictionary in places.search(query):
		var index: int = results.add_item(str(record.name)+" · "+places.kind_label(record))
		results.set_item_metadata(index,str(record.id))
		results.set_item_tooltip(index,str(record.get("property_type",places.kind_label(record)))+"\n"+str(places.source_for(record).get("observation_note","")))
	results.visible = results.item_count > 0
	if results.item_count == 0:
		detail.text = "No matching area, property or landmark."
		detail.visible = true

func _choose(identifier: String) -> void:
	show_place(places.by_id[identifier])
	place_requested.emit(identifier,"overhead")

func show_place(record: Dictionary) -> void:
	active_id = str(record.id)
	search_box.text = str(record.name)
	search_box.release_focus()
	results.visible = false
	detail.text = str(record.name)+" · "+places.kind_label(record)
	detail.tooltip_text = str(places.source_for(record).get("observation_note",""))
	detail.visible = true
	source_url = str(places.source_for(record).get("url",""))
	source_button.text = "Height reference" if str(record.kind) == "landmark" else "DataSF source"
	links.visible = true

func clear_place() -> void:
	active_id = ""
	source_url = ""
	search_box.text = ""
	results.visible = false
	detail.visible = false
	links.visible = false
	update_activity({})

func update_activity(state: Dictionary, error: String = "") -> void:
	activity_label.visible = not state.is_empty() or not error.is_empty()
	if state.is_empty():
		activity_label.text = "Simulated cohort counts unavailable." if not error.is_empty() else ""
		activity_label.tooltip_text = error
		return
	var as_of: String = ""
	if state.has("clock_seconds"):
		var seconds: int = int(state.clock_seconds)
		as_of = " · as of %02d:%02d:%02d" % [posmod(seconds/3600,24),posmod(seconds/60,60),posmod(seconds,60)]
	activity_label.text = "Simulated cohort · %d total%s\nHere %d: %d indoors, %d walking\nHome/work assignments %d / %d · Buildings %d\nActive trips: %d in, %d out, %d within" % [int(state.cohort_size),as_of,int(state.people_here),int(state.indoors_here),int(state.walking_here),int(state.home_assignments),int(state.work_assignments),int(state.assigned_buildings),int(state.incoming_trips),int(state.outgoing_trips),int(state.internal_trips)]
	activity_label.tooltip_text = "Generated residents in this simulation, not measured population or jobs. Buildings counts only buildings assigned to this cohort. Home/work assignments and indoor membership use source building centroids; walkers use displayed positions. In/out/within classify active trip endpoints against the selected area. Counts refresh at most once a second. Missing building centroids: %d; residents without a location: %d." % [int(state.buildings_without_centroids),int(state.people_without_location)]
