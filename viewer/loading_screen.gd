extends CanvasLayer
## Lightweight startup UI: real stages, no estimated percentage or scene assets.
signal close_requested

class CityBackdrop extends Control:
	var motion: float = 0.0
	var failed: bool = false

	func _draw() -> void:
		draw_rect(Rect2(Vector2.ZERO,size),Color("101f27"))
		var scale_value: float = minf(size.x / 1440.0,size.y / 900.0)
		var origin := Vector2(size.x * 0.72,size.y * 0.70)
		var ink := Color("27434b")
		for index: int in range(11):
			var y: float = origin.y + float(index * 28) * scale_value
			draw_line(Vector2(0,y),Vector2(size.x,y),Color(0.17,0.28,0.31,0.27),1.0)
		# An original line illustration of City Hall's dome and civic skyline.
		var skyline: PackedVector2Array = PackedVector2Array([
			Vector2(-580,0),Vector2(-580,-75),Vector2(-520,-75),Vector2(-520,-35),
			Vector2(-430,-35),Vector2(-430,-135),Vector2(-390,-135),Vector2(-390,-85),
			Vector2(-310,-85),Vector2(-310,-28),Vector2(-165,-28),Vector2(-165,-92),
			Vector2(-73,-92),Vector2(-73,-116),Vector2(-42,-116),Vector2(-42,-155),
			Vector2(-30,-180),Vector2(-13,-192),Vector2(-13,-217),Vector2(0,-230),
			Vector2(13,-217),Vector2(13,-192),Vector2(30,-180),Vector2(42,-155),
			Vector2(42,-116),Vector2(73,-116),Vector2(73,-92),Vector2(165,-92),
			Vector2(165,-28),Vector2(250,-28),Vector2(250,-132),Vector2(305,-132),
			Vector2(305,-62),Vector2(385,-62),Vector2(385,0),Vector2(580,0)])
		for index: int in range(skyline.size()): skyline[index] = origin + skyline[index] * scale_value
		draw_polyline(skyline,ink,2.0,true)
		draw_line(origin+Vector2(-580,1)*scale_value,origin+Vector2(580,1)*scale_value,ink,1.0)
		for side: int in [-1,1]:
			for column: int in range(5):
				var x: float = float(side * (85+column*15))
				draw_line(origin+Vector2(x,-80)*scale_value,origin+Vector2(x,-30)*scale_value,ink,1.0)
		draw_arc(origin+Vector2(0,-145)*scale_value,40*scale_value,PI,TAU,24,Color("ad926a"),2.0,true)
		if not failed:
			var track := Rect2(Vector2(size.x*0.09,size.y*0.57),Vector2(minf(size.x*0.42,540.0),3.0))
			draw_rect(track,Color("29434b"))
			var width: float = track.size.x * 0.17
			var x: float = track.position.x + (sin(motion*1.2)*0.5+0.5)*(track.size.x-width)
			draw_rect(Rect2(Vector2(x,track.position.y),Vector2(width,3)),Color("bca377"))

	func _process(delta: float) -> void:
		motion += delta
		queue_redraw()

var surface: Control
var backdrop: CityBackdrop
var stage_label: Label
var detail_label: Label
var state_label: Label
var failed: bool = false
var stage: String = "Opening San Francisco"

func _ready() -> void:
	layer = 100
	surface = Control.new()
	surface.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	surface.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(surface)
	backdrop = CityBackdrop.new()
	backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
	surface.add_child(backdrop)
	var brand: Label = _label("O P E N G L A S S B O X",16,Color("a8c0c1"))
	brand.position = Vector2(52,38)
	surface.add_child(brand)
	var close: Button = Button.new()
	close.text = "Close"
	close.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	close.position = Vector2(-118,28)
	close.size = Vector2(82,38)
	close.focus_mode = Control.FOCUS_NONE
	close.pressed.connect(func() -> void: close_requested.emit())
	surface.add_child(close)
	var content := VBoxContainer.new()
	content.anchor_left = 0.09
	content.anchor_top = 0.28
	content.anchor_right = 0.78
	content.add_theme_constant_override("separation",16)
	surface.add_child(content)
	content.add_child(_label("A CITY IN MOTION",14,Color("bca377")))
	content.add_child(_label("San Francisco",56,Color("edf2e9")))
	stage_label = _label(stage,23,Color("d4e2de"))
	content.add_child(stage_label)
	detail_label = _label("Please wait while your city loads.",16,Color("a0b6b9"))
	detail_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	detail_label.custom_minimum_size = Vector2(520,52)
	content.add_child(detail_label)
	state_label = _label("CITY EXPLORATION  /  RESIDENT SIMULATION",12,Color("809d9f"))
	state_label.anchor_left = 0.09
	state_label.anchor_top = 0.90
	surface.add_child(state_label)

func _label(text_value: String, size_value: int, color_value: Color) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size",size_value)
	label.add_theme_color_override("font_color",color_value)
	return label

func set_stage(value: String, detail: String = "Please wait while your city loads.") -> void:
	if failed: return
	stage = value
	stage_label.text = value
	detail_label.text = detail

func show_error(message: String) -> void:
	failed = true
	backdrop.failed = true
	stage = "The city could not finish loading"
	stage_label.text = stage
	stage_label.add_theme_color_override("font_color",Color("e6b79c"))
	detail_label.text = message + "\nClose this window and try launching again."
	state_label.text = "LOADING STOPPED"

func finish() -> void:
	visible = false
	backdrop.set_process(false)
	surface.mouse_filter = Control.MOUSE_FILTER_IGNORE
