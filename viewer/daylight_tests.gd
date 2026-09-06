extends SceneTree
const Solar = preload("res://solar.gd")
const Daylight = preload("res://daylight.gd")
var failures: Array[String] = []

func _initialize() -> void:
	_check_solar_reference()
	_check_direction_and_calendar()
	_check_visual_modes()
	if failures.is_empty():
		print("GODOT_DAYLIGHT_TESTS_OK independent solar reference, compass orientation, repeated day, pause, invalid input, night and fixed restoration")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)

func _check_solar_reference() -> void:
	# Independent higher-precision NREL SPA worked example, Table A5.1:
	# 2003-10-17 12:30:30, UTC-7, 39.742476N/105.1786W.
	# https://docs.nlr.gov/docs/fy08osti/34302.pdf
	# NOAA's compact approximation omits SPA corrections; this is a 1 degree
	# direction sanity check, not a claim of SPA's much greater precision.
	var sample: Dictionary = Solar.sample(12*3600+30*60+30,39.742476,-105.1786,290,-7)
	if absf(float(sample.altitude_degrees)-(90.0-50.11162)) > 1.0 or absf(float(sample.azimuth_degrees)-194.34024) > 1.0:
		failures.append("Approximate solar direction disagrees with the independent SPA reference.")
	print("NOAA_APPROX_REFERENCE altitude=",sample.altitude_degrees," azimuth=",sample.azimuth_degrees)

func _check_direction_and_calendar() -> void:
	var morning: Dictionary = Solar.sample(8*3600)
	var noon: Dictionary = Solar.sample(13*3600)
	var evening: Dictionary = Solar.sample(17*3600)
	var midnight: Dictionary = Solar.sample(0)
	if morning.direction.x <= 0.0 or evening.direction.x >= 0.0: failures.append("Morning/evening sun must be east/west in Godot coordinates.")
	if noon.direction.z <= 0.0 or float(noon.altitude_degrees) < 50.0: failures.append("September midday SF sun should be high toward the south.")
	if float(midnight.altitude_degrees) >= 0.0 or midnight.phase != "night": failures.append("Midnight cannot have direct sunlight.")
	if morning.direction != Solar.sample(8*3600+86400*100).direction: failures.append("The representative day should repeat without seasonal drift.")
	if Solar.sample(-3600).direction != Solar.sample(23*3600).direction: failures.append("Negative time wrap differs from the previous day's hour.")
	for hour: int in range(24):
		var direction: Vector3 = Solar.sample(hour*3600).direction
		if not direction.is_finite() or absf(direction.length()-1.0) > 0.00001: failures.append("Sun direction must remain a finite unit vector.")
	for invalid: Dictionary in [Solar.sample(NAN),Solar.sample(INF),Solar.sample(0,91),Solar.sample(0,0,181),Solar.sample(0,0,0,367),Solar.sample(0,0,0,366,-7,365),Solar.sample(0,0,0,1,15)]:
		if not invalid.is_empty(): failures.append("Invalid solar inputs must be rejected.")
	if Solar.sample(0,0,0,366,0,366).is_empty(): failures.append("Leap-year final day was rejected.")

func _check_visual_modes() -> void:
	var environment := Environment.new()
	var sky := Sky.new()
	var material := ProceduralSkyMaterial.new()
	sky.sky_material = material
	environment.sky = sky
	environment.ambient_light_energy = 0.24
	var original_sky: Color = material.sky_top_color
	var sunlight := DirectionalLight3D.new()
	sunlight.rotation_degrees = Vector3(-48,-35,0)
	sunlight.light_energy = 0.48
	var original_rotation: Vector3 = sunlight.rotation
	var controller = Daylight.new()
	controller.initialize(environment,sunlight)
	controller.update_clock(0,true)
	if sunlight.light_energy != 0.0 or environment.ambient_light_energy < 0.1: failures.append("Night requires no direct sun and a readable fill.")
	if controller.update_clock(0): failures.append("Paused time should not rebuild lighting state.")
	var state: Dictionary = controller.get_state()
	if controller.update_clock(NAN,true) or controller.get_state() != state: failures.append("Invalid time altered visual state.")
	controller.set_enabled(false)
	if not sunlight.rotation.is_equal_approx(original_rotation) or not is_equal_approx(sunlight.light_energy,0.48) or material.sky_top_color != original_sky: failures.append("Fixed mode did not restore the original environment.")
	controller.update_clock(13*3600,true)
	controller.set_enabled(true)
	if sunlight.light_energy <= 0.45 or controller.get_state().phase != "daylight": failures.append("Re-enabling the cycle did not use the latest displayed clock.")
	var toward_sun: Vector3 = controller.current.direction
	if sunlight.basis.z.dot(toward_sun) < 0.999: failures.append("Directional light emits toward the sun instead of away from it.")
	sunlight.free()
