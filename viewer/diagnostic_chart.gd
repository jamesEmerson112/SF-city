extends Control
## Fixed-length presentation graph, redrawn only when a visible sample changes.
var values: Array[float] = []
var title: String = ""
var color: Color = Color("7ee2c5")
var limit: int = 120

func _ready() -> void:
	custom_minimum_size = Vector2(90,95)
	mouse_filter = Control.MOUSE_FILTER_IGNORE

func push(value: float) -> void:
	values.append(value if is_finite(value) and value >= 0.0 else -1.0)
	if values.size() > limit: values.pop_front()
	if is_visible_in_tree(): queue_redraw()

func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO,size),Color("101d25"))
	var font := ThemeDB.fallback_font
	var maximum: float = 1.0
	for value: float in values: maximum = maxf(maximum,value)
	var label: String = title+"  "+("%.1f" % values.back() if not values.is_empty() and values.back() >= 0 else "unavailable")
	draw_string(font,Vector2(8,18),label,HORIZONTAL_ALIGNMENT_LEFT,size.x-16,13,Color("dceae5"))
	var previous := Vector2.ZERO
	var valid: bool = false
	for index: int in range(values.size()):
		if values[index] < 0:
			valid = false
			continue
		var point := Vector2(8.0+float(index)/float(maxi(1,limit-1))*(size.x-16),size.y-8-values[index]/maximum*(size.y-36))
		if valid: draw_line(previous,point,color,1.5,true)
		previous = point
		valid = true
