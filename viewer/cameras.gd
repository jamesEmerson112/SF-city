extends Node3D
const EYE_HEIGHT: float = 1.8
const WALK_RADIUS: float = 0.7
const WALK_SPEED: float = 6.0
const KEYBOARD_TURN_SPEED: float = PI / 2.0
const Coordinates = preload("res://coordinates.gd")
var fixture: Dictionary = {}
var camera: Camera3D
var mode: String = "overhead"
var orbit_target: Vector3 = Vector3.ZERO
var orbit_yaw: float = 0.0
var orbit_pitch: float = 0.7
var orbit_distance: float = 330.0
var walk_position: Vector3 = Vector3.ZERO
var walk_yaw: float = 0.0
var walk_pitch: float = 0.0
var follow_position: Vector3 = Vector3.ZERO
var follow_pan_offset: Vector3 = Vector3.ZERO
var follow_heading: float = 0.0
var follow_available: bool = false
var follow_indoor: bool = false
var follow_building_height: float = 0.0
var allow_walk_input: bool = true
var follow_distance: float = 12.0
var follow_yaw_offset: float = 0.0
var follow_pitch: float = 0.38
var geography_bounds: Dictionary = {}
var orbit_max_distance: float = 1500.0
var city_view: bool = false
var pilot_enabled: bool = true
var terrain: Node3D
var geography: Node3D
var scenario_view: Dictionary = {}

func initialize(visual: Dictionary) -> void:
	fixture = visual
	camera = Camera3D.new()
	camera.near = 0.15
	camera.far = 4000.0
	camera.fov = 55.0
	add_child(camera)
	camera.current = true
	reset_camera()

func reset_camera() -> void:
	var config: Dictionary = fixture.camera.duplicate(false)
	if not pilot_enabled: config.merge(scenario_view,true)
	orbit_target = Coordinates.to_world(config.target)
	orbit_distance = float(config.distance)
	orbit_yaw = deg_to_rad(float(config.yaw_degrees))
	orbit_pitch = deg_to_rad(float(config.pitch_degrees))
	walk_position = Coordinates.to_world(config.walk_position)
	var look_direction: Vector3 = orbit_target - walk_position
	walk_yaw = atan2(look_direction.x, -look_direction.z)
	walk_pitch = deg_to_rad(float(config.get("walk_pitch_degrees", 18.0)))
	update_camera(0.0)

func set_mode(value: String) -> void:
	if value in ["overhead", "walk", "follow"]:
		mode = value
		if value == "follow": follow_pan_offset = Vector3.ZERO
		update_camera(0.0)

func configure_geography(bounds: Dictionary) -> void:
	geography_bounds = bounds
	var span := Vector2(float(bounds.max[0])-float(bounds.min[0]),float(bounds.max[1])-float(bounds.min[1]))
	orbit_max_distance = maxf(1500.0,span.length()*2.2)
	camera.far = maxf(4000.0,orbit_max_distance*2.0)

func jump_to_city() -> void:
	if geography_bounds.is_empty(): return
	mode = "overhead"
	city_view = true
	var bounds: Dictionary = geography_bounds
	orbit_target = Vector3((float(bounds.min[0])+float(bounds.max[0]))*0.5,0.0,-(float(bounds.min[1])+float(bounds.max[1]))*0.5)
	var span := Vector2(float(bounds.max[0])-float(bounds.min[0]),float(bounds.max[1])-float(bounds.min[1]))
	orbit_distance = maxf(span.x,span.y)*1.45
	orbit_pitch = deg_to_rad(72.0)
	orbit_yaw = deg_to_rad(-90.0)
	update_camera(0.0)

func configure_scenario_view(view: Dictionary) -> void:
	scenario_view = view
	if view.has("walk_position"): walk_position = Coordinates.to_world(view.walk_position)
	if not city_view: reset_camera()

func jump_to_city_hall() -> void:
	city_view = false
	mode = "overhead"
	reset_camera()

func jump_to_place(record: Dictionary, requested_mode: String = "overhead") -> bool:
	var target: Vector3 = Coordinates.to_world(record.target)
	var walking: Vector3 = Coordinates.to_world(record.walk_position)
	if terrain != null and terrain.available:
		var elevation: Variant = terrain.display_height_at(target.x,-target.z)
		var walking_elevation: Variant = terrain.display_height_at(walking.x,-walking.z)
		if elevation == null or walking_elevation == null: return false
		target.y = float(elevation)
		walking.y = float(walking_elevation)+EYE_HEIGHT
	else: walking.y += EYE_HEIGHT
	city_view = true
	orbit_target = target+Vector3.UP*maxf(8.0,float(record.get("height_m",0.0))*0.45)
	orbit_pitch = deg_to_rad(62.0)
	orbit_yaw = deg_to_rad(-90.0)
	var fitted_distance: float = float(record.view_distance_m)
	if record.has("bounds"):
		var points: Array[Vector3] = place_framing_points(record,target.y)
		var viewport_size: Vector2 = get_viewport().get_visible_rect().size
		var aspect: float = viewport_size.x/viewport_size.y if viewport_size.y > 0.0 else 1.6
		fitted_distance = fit_distance(points,orbit_target,orbit_pitch,orbit_yaw,camera.fov,aspect,camera.keep_aspect)
	orbit_distance = clampf(fitted_distance,100.0,orbit_max_distance)
	walk_position = walking
	var direction: Vector3 = target-walking
	walk_yaw = atan2(direction.x,-direction.z)
	walk_pitch = 0.0
	mode = "walk" if requested_mode == "walk" else "overhead"
	update_camera(0.0)
	return true

func place_framing_points(record: Dictionary, fallback_height: float) -> Array[Vector3]:
	var points: Array[Vector3] = []
	var bounds: Dictionary = record.bounds
	for east: float in [float(bounds.min[0]),float(bounds.max[0])]:
		for north: float in [float(bounds.min[1]),float(bounds.max[1])]:
			var height_value: float = fallback_height
			if terrain != null and terrain.available and str(record.get("kind","")) != "landmark":
				var sampled: Variant = terrain.display_height_at(east,north)
				if sampled != null: height_value = float(sampled)
			points.append(Vector3(east,height_value,-north))
			points.append(Vector3(east,height_value+float(record.get("height_m",0.0)),-north))
	return points

static func fit_distance(points: Array[Vector3], target: Vector3, pitch: float, yaw: float, fov_degrees: float, aspect: float, keep_aspect: int = Camera3D.KEEP_HEIGHT) -> float:
	# Bound each point's perspective projection, including the depth change from
	# the tilted camera. A fixed span multiplier wastes space on wide places.
	var back := Vector3(cos(yaw)*cos(pitch),sin(pitch),-sin(yaw)*cos(pitch))
	var right: Vector3 = Vector3.UP.cross(back).normalized()
	var up: Vector3 = back.cross(right)
	var tangent_y: float = tan(deg_to_rad(fov_degrees)*0.5)
	var tangent_x: float = tangent_y*maxf(aspect,0.1)
	if keep_aspect == Camera3D.KEEP_WIDTH:
		tangent_x = tangent_y
		tangent_y /= maxf(aspect,0.1)
	var result: float = 0.0
	for point: Vector3 in points:
		var offset: Vector3 = point-target
		var depth: float = offset.dot(back)
		result = maxf(result,depth+maxf(absf(offset.dot(right))/(tangent_x*0.86),absf(offset.dot(up))/(tangent_y*0.86)))
	return result

func pan(relative: Vector2) -> void:
	if mode != "overhead": return
	var scale_value: float = orbit_distance * 0.0012
	var right: Vector3 = camera.global_basis.x
	var forward: Vector3 = -camera.global_basis.z
	forward.y = 0.0
	forward = forward.normalized()
	_move_orbit_target((-right*relative.x + forward*relative.y)*scale_value)

func _clamp_horizontal(target: Vector3) -> Vector3:
	if not geography_bounds.is_empty():
		target.x = clampf(target.x,float(geography_bounds.min[0]),float(geography_bounds.max[0]))
		target.z = clampf(target.z,-float(geography_bounds.max[1]),-float(geography_bounds.min[1]))
	return target

func _move_orbit_target(displacement: Vector3) -> void:
	orbit_target = _clamp_horizontal(orbit_target+displacement)
	if terrain != null and terrain.available:
		var elevation: Variant = terrain.display_height_at(orbit_target.x,-orbit_target.z)
		if elevation != null: orbit_target.y = float(elevation)+8.0

func keyboard_navigate(direction: Vector2, turn: float, delta: float, fast: bool = false) -> void:
	if not allow_walk_input or camera == null or not direction.is_finite() or not is_finite(turn) or not is_finite(delta): return
	var elapsed: float = clampf(delta,0.0,0.05)
	if elapsed == 0.0: return
	var angle: float = clampf(turn,-1.0,1.0)*KEYBOARD_TURN_SPEED*elapsed
	if angle != 0.0:
		match mode:
			"walk": walk_yaw = wrapf(walk_yaw+angle,-PI,PI)
			"follow":
				if follow_available: follow_yaw_offset = wrapf(follow_yaw_offset-angle,-PI,PI)
				else: orbit_yaw = wrapf(orbit_yaw-angle,-PI,PI)
			_: orbit_yaw = wrapf(orbit_yaw-angle,-PI,PI)
		update_camera(0.0)
	# Walk movement retains its existing collision-aware path in update_camera.
	if mode == "walk" or direction.is_zero_approx(): return
	var right: Vector3 = camera.global_basis.x
	right.y = 0.0
	right = right.normalized()
	var forward: Vector3 = -camera.global_basis.z
	forward.y = 0.0
	forward = forward.normalized()
	var input_direction: Vector2 = direction.limit_length(1.0)
	var distance: float = follow_distance*(7.5 if follow_indoor else 1.0) if mode == "follow" and follow_available else orbit_distance
	var speed: float = maxf(10.0,distance*0.65)*(2.5 if fast else 1.0)
	var displacement: Vector3 = (right*input_direction.x+forward*input_direction.y)*speed*elapsed
	if mode == "follow" and follow_available:
		follow_pan_offset = _clamp_horizontal(follow_position+follow_pan_offset+displacement)-follow_position
	else:
		_move_orbit_target(displacement)

func drag(relative: Vector2) -> void:
	if mode == "walk":
		walk_yaw += relative.x * 0.005
		walk_pitch = clampf(walk_pitch - relative.y * 0.005, -1.35, 1.35)
	elif mode == "overhead":
		orbit_yaw -= relative.x * 0.006
		orbit_pitch = clampf(orbit_pitch + relative.y * 0.006, 0.13, 1.48)
	elif mode == "follow":
		follow_yaw_offset -= relative.x * 0.006
		follow_pitch = clampf(follow_pitch + relative.y * 0.006,0.08,1.3)

func zoom(direction: float) -> void:
	if mode == "overhead":
		orbit_distance = clampf(orbit_distance * direction, 25.0, orbit_max_distance)
	elif mode == "follow":
		follow_distance = clampf(follow_distance * direction,4.0,60.0)

func _can_walk_to(position_value: Vector3) -> bool:
	var x: float = position_value.x
	var y: float = -position_value.z
	var bounds: Dictionary = geography_bounds if not geography_bounds.is_empty() else fixture.bounds
	if x < float(bounds.min[0]) + WALK_RADIUS or x > float(bounds.max[0]) - WALK_RADIUS:
		return false
	if y < float(bounds.min[1]) + WALK_RADIUS or y > float(bounds.max[1]) - WALK_RADIUS:
		return false
	if pilot_enabled:
		for box: Dictionary in fixture.collision_boxes:
			if x > float(box.min[0]) - WALK_RADIUS and x < float(box.max[0]) + WALK_RADIUS and y > float(box.min[1]) - WALK_RADIUS and y < float(box.max[1]) + WALK_RADIUS: return false
	if geography != null and geography.available and geography.blocks_walk(x,y): return false
	return true

func _walking_eye_height(position_value: Vector3) -> float:
	var x: float = position_value.x
	var y: float = -position_value.z
	if pilot_enabled and absf(x) <= 205.0 and absf(y) <= 185.0:
		for surface: Dictionary in fixture.get("walk_surfaces", []):
			if x >= float(surface.min[0]) and x <= float(surface.max[0]) and y >= float(surface.min[1]) and y <= float(surface.max[1]):
				var fraction: float = clampf((y - float(surface.from_y)) / (float(surface.to_y) - float(surface.from_y)), 0.0, 1.0)
				return EYE_HEIGHT + lerpf(float(surface.from_z), float(surface.to_z), fraction)
		return 2.28
	if terrain != null and terrain.available:
		var elevation: Variant = terrain.display_height_at(x,y)
		if elevation != null: return EYE_HEIGHT + float(elevation)
	return EYE_HEIGHT

func update_camera(delta: float) -> void:
	if camera == null:
		return
	# A wider near plane preserves map depth precision at kilometer-scale zoom.
	camera.near = clampf(orbit_distance / 5000.0,0.15,10.0) if mode == "overhead" else 0.15
	if mode == "walk":
		var turn: float = float(Input.is_physical_key_pressed(KEY_RIGHT)) - float(Input.is_physical_key_pressed(KEY_LEFT))
		if allow_walk_input: walk_yaw += turn * delta * 1.6
		var direction := Vector2(
			float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)),
			float(Input.is_physical_key_pressed(KEY_W)) - float(Input.is_physical_key_pressed(KEY_S)))
		if allow_walk_input and direction.length_squared() > 0.0:
			direction = direction.normalized()
			var forward := Vector3(sin(walk_yaw), 0.0, -cos(walk_yaw))
			var right := Vector3(cos(walk_yaw), 0.0, sin(walk_yaw))
			var speed: float = 22.0 if Input.is_physical_key_pressed(KEY_SHIFT) else WALK_SPEED
			var displacement: Vector3 = (forward * direction.y + right * direction.x) * speed * minf(delta, 0.05)
			var candidate: Vector3 = walk_position + Vector3(displacement.x, 0.0, 0.0)
			if _can_walk_to(candidate):
				walk_position = candidate
			candidate = walk_position + Vector3(0.0, 0.0, displacement.z)
			if _can_walk_to(candidate):
				walk_position = candidate
		walk_position.y = _walking_eye_height(walk_position)
		camera.position = walk_position
		camera.look_at(walk_position + Vector3(sin(walk_yaw) * cos(walk_pitch), sin(walk_pitch), -cos(walk_yaw) * cos(walk_pitch)), Vector3.UP)
	elif mode == "follow" and follow_available:
		var target: Vector3 = follow_position + follow_pan_offset + Vector3.UP * _follow_target_height()
		var heading: float = follow_heading + follow_yaw_offset
		var candidate: Vector3 = _follow_offset(heading)
		# Entrances remain selectable indoors. Keep the camera outside their walls.
		if not _can_walk_to(candidate):
			var clear: bool = false
			for scale_value: float in [1.0,1.75,3.0,5.0]:
				for turn: float in [0.0,PI/3.0,-PI/3.0,2.0*PI/3.0,-2.0*PI/3.0,PI]:
					var alternative: Vector3 = _follow_offset(heading + turn,scale_value)
					if _can_walk_to(alternative):
						candidate = alternative
						clear = true
						break
				if clear: break
		candidate.y = maxf(candidate.y,_walking_eye_height(candidate)+1.0)
		camera.position = candidate
		camera.look_at(target, Vector3.UP)
	else:
		var offset := Vector3(cos(orbit_yaw) * cos(orbit_pitch), sin(orbit_pitch), -sin(orbit_yaw) * cos(orbit_pitch)) * orbit_distance
		camera.position = orbit_target + offset
		camera.look_at(orbit_target, Vector3.UP)

func _follow_target_height() -> float:
	return clampf(follow_building_height*0.45,8.0,35.0) if follow_indoor else 1.3

func _follow_offset(heading: float, distance_scale: float = 1.0) -> Vector3:
	var forward := Vector3(cos(heading),0.0,-sin(heading))
	# Indoors, retain the resident's arrival point but frame the exterior around
	# it. A close eye-level view from inside the footprint only reveals a wall.
	var distance: float = follow_distance * (7.5 if follow_indoor else 1.0)
	distance *= distance_scale
	var pitch: float = maxf(follow_pitch,0.65) if follow_indoor else follow_pitch
	return follow_position + follow_pan_offset - forward * distance * cos(pitch) + Vector3.UP * (_follow_target_height() + distance * sin(pitch))

