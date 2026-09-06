extends RefCounted
## Visual daylight for a representative September day, driven by displayed time.
## Sun direction is approximate NOAA geometry; colors/fill are artistic choices.
const Solar = preload("res://solar.gd")
var enabled: bool = true
var environment: Environment
var sunlight: DirectionalLight3D
var sky_material: ProceduralSkyMaterial
var last_clock: float = 28790.0
var current: Dictionary = {}
var fixed: Dictionary = {}
var last_update_msec: int = -1000
var applied_clock: float = -INF

func initialize(value: Environment, light: DirectionalLight3D) -> void:
	environment = value
	sunlight = light
	if environment == null or sunlight == null: return
	if environment.sky != null and environment.sky.sky_material is ProceduralSkyMaterial:
		sky_material = environment.sky.sky_material
	fixed = {"rotation":sunlight.rotation,"light_color":sunlight.light_color,"light_energy":sunlight.light_energy,"ambient_color":environment.ambient_light_color,"ambient_energy":environment.ambient_light_energy}
	if sky_material != null:
		fixed["sky_top"] = sky_material.sky_top_color
		fixed["sky_horizon"] = sky_material.sky_horizon_color
		fixed["ground_bottom"] = sky_material.ground_bottom_color
		fixed["ground_horizon"] = sky_material.ground_horizon_color
	update_clock(last_clock,true)

func set_enabled(value: bool) -> void:
	if enabled == value: return
	enabled = value
	if environment == null or sunlight == null: return
	if enabled:
		update_clock(last_clock,true)
	else:
		sunlight.rotation = fixed.rotation
		sunlight.light_color = fixed.light_color
		sunlight.light_energy = fixed.light_energy
		environment.ambient_light_color = fixed.ambient_color
		environment.ambient_light_energy = fixed.ambient_energy
		if sky_material != null:
			sky_material.sky_top_color = fixed.sky_top
			sky_material.sky_horizon_color = fixed.sky_horizon
			sky_material.ground_bottom_color = fixed.ground_bottom
			sky_material.ground_horizon_color = fixed.ground_horizon

func update_clock(seconds: float, force: bool = false) -> bool:
	if not is_finite(seconds): return false
	last_clock = seconds
	if not enabled or environment == null or sunlight == null: return false
	var now: int = Time.get_ticks_msec()
	if not force and (seconds == applied_clock or now-last_update_msec < 200): return false
	var state: Dictionary = Solar.sample(seconds)
	if state.is_empty(): return false
	current = state
	applied_clock = seconds
	last_update_msec = now
	var altitude: float = float(state.altitude_degrees)
	var direction: Vector3 = state.direction
	# Directional lights emit along local -Z; point that axis away from the sun.
	sunlight.basis = Basis.looking_at(-direction,Vector3.UP)
	var daylight: float = smoothstep(-8.0,12.0,altitude)
	var warmth: float = smoothstep(0.0,28.0,altitude)
	sunlight.light_color = Color("ffd0a0").lerp(Color("fff8ed"),warmth)
	sunlight.light_energy = 0.52*smoothstep(-0.6,8.0,altitude)
	# Night fill preserves inspectability; it does not model moonlight or lamps.
	environment.ambient_light_color = Color("a5b8d7").lerp(Color("d7e1e7"),daylight)
	environment.ambient_light_energy = lerpf(0.12,0.24,daylight)
	if sky_material != null:
		var twilight: float = 1.0-absf(daylight*2.0-1.0)
		var horizon: Color = Color("17243a").lerp(Color("dce8e9"),daylight).lerp(Color("c49a87"),twilight*0.55)
		sky_material.sky_top_color = Color("07111f").lerp(Color("759cb8"),daylight)
		sky_material.sky_horizon_color = horizon
		sky_material.ground_horizon_color = horizon
		sky_material.ground_bottom_color = Color("142030").lerp(Color("52606a"),daylight)
	return true

func get_state() -> Dictionary:
	return {"enabled":enabled,"mode":"cycle" if enabled else "fixed","label":"September daylight" if enabled else "Fixed daylight","phase":current.get("phase","daylight") if enabled else "fixed","altitude_degrees":current.get("altitude_degrees",0.0),"azimuth_degrees":current.get("azimuth_degrees",0.0),"reference":"Representative September 6, PDT, San Francisco; approximate sun direction and illustrative colors; no live weather or seasonal calendar."}
