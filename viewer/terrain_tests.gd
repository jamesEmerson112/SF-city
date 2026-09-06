extends SceneTree
var failures: Array[String] = []

func _initialize() -> void:
	var sampler = preload("res://terrain.gd").new()
	root.add_child(sampler)
	var fixture: Dictionary = {"schema_version":1,"width":2,"height":2,"bounds":{"min":[0,0],"max":[10,10]},"origin_elevation_m":10,"elevations_m":[10,20,30,40]}
	if not sampler.configure(fixture): failures.append("Small terrain fixture did not configure.")
	if absf(float(sampler.height_at(5,5))-15.0) > 0.000001: failures.append("Terrain bilinear interpolation differs from the north-to-south grid.")
	if float(sampler.height_at(0,10)) != 0.0 or float(sampler.height_at(10,0)) != 30.0: failures.append("Terrain sample endpoints were flipped.")
	if sampler.height_at(-1,5) != null: failures.append("Outside terrain bounds must remain unknown.")
	fixture.elevations_m = [10,null,30,40]
	sampler.configure(fixture)
	if sampler.height_at(5,5) != null: failures.append("Terrain interpolated through missing data.")
	if sampler.height_at(0,10) != 0.0: failures.append("A zero-weight missing neighbor invalidated an exact sample.")
	fixture.elevations_m = [10,10,10,30]
	sampler.configure(fixture)
	if absf(float(sampler.triangle_height_at(7.5,7.5))-5.0) > 0.000001 or absf(float(sampler.triangle_height_at(2.5,2.5))-5.0) > 0.000001: failures.append("The NW-SE terrain triangle planes differ from the displayed mesh.")
	if absf(float(sampler.triangle_height_at(5,5))-10.0) > 0.000001: failures.append("The terrain diagonal does not interpolate shared corner heights.")
	var fractions: Array[float] = sampler.segment_fractions(0,5,10,5)
	if not 0.5 in fractions: failures.append("The terrain line did not split at its raster diagonal.")
	for i: int in range(fractions.size()-1):
		var first: float = fractions[i]*10.0
		var last: float = fractions[i+1]*10.0
		var linear_height: float = lerpf(float(sampler.triangle_height_at(first,5)),float(sampler.triangle_height_at(last,5)),0.5)
		if absf(linear_height-float(sampler.triangle_height_at((first+last)*0.5,5))) > 0.000001: failures.append("A split path segment left the terrain triangle plane.")
	fixture.elevations_m = [10,null,10,30]
	sampler.configure(fixture)
	if sampler.triangle_height_at(2.5,2.5) == null or sampler.triangle_height_at(7.5,7.5) != null: failures.append("Missing samples did not respect the selected terrain triangle.")
	var path: String = ProjectSettings.globalize_path("res://../.local/civic/terrain/terrain.json")
	if FileAccess.file_exists(path):
		if not sampler.initialize(path): failures.append("The actual local terrain grid did not load.")
		else:
			for sample: Array in [[0,0,-0.0003194808],[500,500,0.02830066935],[-5000,2000,80.22838469817],[-3000,-3000,137.35056008649],[2000,4000,-18.53085220067]]:
				var measured: Variant = sampler.height_at(float(sample[0]),float(sample[1]))
				if measured == null or absf(float(measured)-float(sample[2])) > 0.0001: failures.append("Godot terrain sample differs from Python at %s: %s" % [sample,measured])
			if sampler.height_at(99999,99999) != null: failures.append("Actual grid accepted an outside sample.")
			sampler.set_pilot_mode(true)
			if sampler.display_height_at(100,100) != 0.0: failures.append("Legacy pilot terrain patch is not flat.")
			sampler.set_pilot_mode(false)
			if sampler.display_height_at(100,100) != sampler.triangle_height_at(100,100): failures.append("Authentic city terrain still uses a synthetic pilot patch.")
	sampler.free()
	if failures.is_empty():
		print("GODOT_TERRAIN_TESTS_OK bilinear grid, triangle surface, bounds, null samples, Python parity, scenario-specific pilot patch")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
