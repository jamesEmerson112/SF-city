extends CanvasLayer
## Lightweight modal options. Simulation and exit decisions belong to MenuFlow.
signal action_requested(action: String)
var panel: PanelContainer
var scroll: ScrollContainer
var surface: Control
var status_label: Label
var pages: Dictionary = {}
var buttons: Dictionary = {}
var page: String = "root"
var scale_picker: OptionButton
var mode_picker: OptionButton
var previous_focus: WeakRef
var previous_mouse_mode: int = Input.MOUSE_MODE_VISIBLE

func _ready() -> void:
	layer = 120
	surface = Control.new()
	surface.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	surface.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(surface)
	var shade := ColorRect.new()
	shade.color = Color(0.015,0.025,0.04,0.72)
	shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	surface.add_child(shade)
	panel = PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color("14252ff8")
	style.border_color = Color("527474")
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	style.set_content_margin_all(20)
	panel.add_theme_stylebox_override("panel",style)
	surface.add_child(panel)
	scroll = ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	panel.add_child(scroll)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation",12)
	scroll.add_child(body)
	var title := Label.new()
	title.text = "SAN FRANCISCO"
	title.add_theme_font_size_override("font_size",22)
	body.add_child(title)
	status_label = _label("Options")
	body.add_child(status_label)
	for name_value: String in ["root","display","controls","exit","error","confirm_unsaved"]:
		var column := VBoxContainer.new()
		column.add_theme_constant_override("separation",10)
		body.add_child(column)
		pages[name_value] = column
	_add_button("root","return","Return to city")
	_add_button("root","save","Save day")
	pages.root.add_child(_label("Save day replaces the local quick save."))
	_add_button("root","display","Display")
	_add_button("root","controls","Controls")
	_add_button("root","performance","Performance")
	_add_button("root","exit","Save & Exit")
	pages.root.add_child(_label("Exit recovery is separate from your quick save."))
	_add_button("display","back_display","Back")
	mode_picker = OptionButton.new()
	mode_picker.custom_minimum_size.y = 42
	for value: String in ["Windowed","Maximized","Fullscreen"]: mode_picker.add_item(value)
	mode_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("mode_%d" % index))
	pages.display.add_child(mode_picker)
	scale_picker = OptionButton.new()
	scale_picker.custom_minimum_size.y = 42
	for value: String in ["UI 100%","UI 125%","UI 150%"]: scale_picker.add_item(value)
	scale_picker.item_selected.connect(func(index: int) -> void: action_requested.emit("scale_%d" % index))
	pages.display.add_child(scale_picker)
	_add_button("controls","back_controls","Back")
	pages.controls.add_child(_label("Escape  Options / return\n1  Overhead   2  Walk\n3  Follow   4  2D map\nWASD  Move    Q / E  Rotate\nShift  Move faster\nDrag  Look / pan\nWheel  Zoom\nSpace  Pause / resume\nN  Next activity\nF5  Quick save    F9  Load quick save\nF3  Performance    F11  Fullscreen\nG  City overview    H  City Hall\nTab  City panels\n\nMenu: Up / Down or Tab to navigate; Enter to choose."))
	for name_value: String in ["exit","error"]:
		_add_button(name_value,"cancel_"+name_value,"Return to menu")
		if name_value == "error": _add_button(name_value,"retry","Retry")
		_add_button(name_value,"unsaved_"+name_value,"Exit without saving...")
		pages[name_value].add_child(_label("A save already in progress may still finish if you cancel this exit."))
	_add_button("confirm_unsaved","cancel_unsaved","Keep application open")
	pages.confirm_unsaved.add_child(_label("Exit without a new recovery save? This does not undo a save that already finished."))
	_add_button("confirm_unsaved","confirm_unsaved","Exit without saving")
	visible = false
	show_page("root")
	layout(get_viewport().get_visible_rect().size)

func _label(value: String) -> Label:
	var label := Label.new()
	label.text = value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label

func _add_button(parent_page: String, key: String, label: String) -> void:
	var button := Button.new()
	button.text = label
	button.custom_minimum_size.y = 42
	button.focus_mode = Control.FOCUS_ALL
	button.pressed.connect(func() -> void: action_requested.emit(key))
	pages[parent_page].add_child(button)
	buttons[key] = button

func set_open(value: bool) -> void:
	if visible == value: return
	if value:
		var focus: Control = get_viewport().gui_get_focus_owner()
		previous_focus = weakref(focus) if focus != null else null
		previous_mouse_mode = Input.mouse_mode
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		visible = true
		show_page("root")
	else:
		visible = false
		var focus: Control = previous_focus.get_ref() as Control if previous_focus != null else null
		if is_instance_valid(focus) and focus.is_visible_in_tree(): focus.grab_focus()
		Input.mouse_mode = previous_mouse_mode

func show_page(value: String) -> void:
	if not pages.has(value): return
	page = value
	for key: String in pages: pages[key].visible = key == page
	scroll.scroll_vertical = 0
	_focus_first.call_deferred()

func _focusables() -> Array[Control]:
	var result: Array[Control] = []
	for child: Node in pages[page].get_children():
		if child is BaseButton and not child.disabled and child.is_visible_in_tree(): result.append(child)
	return result

func _focus_first() -> void:
	if not visible: return
	var controls: Array[Control] = _focusables()
	if not controls.is_empty(): controls[0].grab_focus()

func handle_key(event: InputEventKey) -> bool:
	if not visible or not event.pressed or event.echo: return false
	if popup_open(): return false
	if event.physical_keycode in [KEY_TAB,KEY_UP,KEY_DOWN]:
		var controls: Array[Control] = _focusables()
		if controls.is_empty(): return true
		var index: int = controls.find(get_viewport().gui_get_focus_owner())
		var backwards: bool = event.physical_keycode == KEY_UP or (event.physical_keycode == KEY_TAB and event.shift_pressed)
		index = posmod(index+(-1 if backwards else 1),controls.size())
		controls[index].grab_focus()
		scroll.ensure_control_visible(controls[index])
		return true
	return false

func popup_open() -> bool:
	return mode_picker.get_popup().visible or scale_picker.get_popup().visible

func close_popup() -> bool:
	for picker: OptionButton in [mode_picker,scale_picker]:
		if picker.get_popup().visible:
			picker.get_popup().hide()
			picker.grab_focus()
			return true
	return false

func layout(view_size: Vector2) -> void:
	if panel == null: return
	panel.position = Vector2(16,16)
	panel.custom_minimum_size = Vector2.ZERO
	panel.size = Vector2(maxf(180,minf(360,view_size.x-32)),maxf(160,view_size.y-32))

func update_status(text_value: String, busy: bool, can_save: bool, exit_label: String = "Save & Exit") -> void:
	status_label.text = text_value
	buttons.save.disabled = not can_save or busy
	buttons.exit.text = exit_label
	buttons.exit.disabled = busy
	if buttons.has("retry"): buttons.retry.disabled = busy
