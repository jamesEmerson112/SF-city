extends SceneTree
const Driver = preload("res://area_activity_driver.gd")
var failures: Array[String] = []

func _initialize() -> void:
	call_deferred("_run")

func _wait_result(driver: Node, tick: int, milliseconds: int = 3000) -> Dictionary:
	var deadline: int = Time.get_ticks_msec()+milliseconds
	while Time.get_ticks_msec() < deadline:
		var result: Dictionary = driver.poll()
		if not result.is_empty() and int(result.tick) == tick: return result
		await process_frame
	return {}

func _run() -> void:
	var driver = Driver.new()
	root.add_child(driver)
	var polygons: Array = [{"rings":[[[0,0,0],[20,0,0],[20,20,0],[0,20,0]]]}]
	var scenario: Dictionary = {"buildings":[{"id":"home","centroid":[5,5,0]},{"id":"work","centroid":[50,50,0]}],"residents":[{"id":"a","home_id":"home","work_id":"work"}]}
	var snapshot: Dictionary = {"session_id":"first","sequence":1,"tick":1,"clock_seconds":28800,"residents":[{"id":"a","building_id":"home","position":[5,5,0],"trip":null}]}
	if not driver.configure("area",polygons,scenario,"first"): failures.append("Valid background configuration was rejected.")
	driver.sample(snapshot)
	var result: Dictionary = await _wait_result(driver,1)
	if result.get("people_here",-1) != 1 or result.get("clock_seconds",0) != 28800: failures.append("Background result differs from the exact input state or lost its clock.")
	# Submit many immutable frames faster than the worker can consume them.
	for tick: int in range(2,1002):
		var next: Dictionary = snapshot.duplicate(false)
		next.tick = tick
		next.sequence = tick
		driver.sample(next)
		if int(driver.get_state().pending_jobs) > 1: failures.append("Background activity queued a frame history.")
	result = await _wait_result(driver,1001)
	if int(result.get("tick",-1)) != 1001: failures.append("Coalescing failed to eventually publish the newest complete frame.")
	# Immediate session replacement may race with the old calculation; results
	# must always belong to the newly configured selection and session.
	for index: int in range(20):
		var session: String = "session-"+str(index)
		driver.configure("area-"+str(index),polygons,scenario,session)
		var next: Dictionary = snapshot.duplicate(false)
		next.session_id = session
		next.tick = 2000+index
		next.sequence = 2000+index
		driver.sample(next)
		if not driver.poll().is_empty() and driver.poll().get("session_id") != session: failures.append("A previous session result leaked into the selected area.")
	result = await _wait_result(driver,2019)
	if result.get("session_id") != "session-19" or result.get("selected_id") != "area-19": failures.append("Final selected area used stale membership metadata.")
	driver.clear()
	if not driver.poll().is_empty() or driver.available: failures.append("Clearing a selection retained prior counts.")
	driver.configure("area",polygons,scenario,"last")
	driver.stop()
	if driver.get_state().in_flight or int(driver.get_state().pending_jobs) != 0: failures.append("Stopping did not join the background worker and clear its pending data.")
	driver.free()
	if failures.is_empty():
		print("GODOT_AREA_ACTIVITY_DRIVER_OK exact timed results, bounded latest-state coalescing, session/selection replacement, clear and joined shutdown")
		quit(0)
	else:
		for failure: String in failures: push_error(failure)
		quit(1)
