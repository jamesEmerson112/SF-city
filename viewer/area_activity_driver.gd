extends Node
## Background aggregation for one selected area. Exactly one pending job and
## one in-flight job retain immutable scene/snapshot references, never a history.
const Activity = preload("res://area_activity.gd")
var available: bool = false
var last_error: String = ""
var selected_id: String = ""
var session_id: String = ""
var _thread := Thread.new()
var _mutex := Mutex.new()
var _work := Semaphore.new()
var _generation: int = 0
var _stopping: bool = false
var _pending: Dictionary = {}
var _output: Dictionary = {}
var _configuration: Dictionary = {}
var _last_result: Dictionary = {}
var _last_submitted: Array = []
var _in_flight: bool = false
var _completed: int = 0
var _coalesced: int = 0
var _discarded: int = 0
var _last_compute_ms: float = 0.0

func configure(place_id: String, checked_polygons: Array, scenario: Dictionary, active_session: String) -> bool:
	clear()
	if place_id.is_empty() or active_session.is_empty() or checked_polygons.is_empty() or not scenario.get("buildings") is Array or not scenario.get("residents") is Array or scenario.buildings.size() > Activity.MAX_ENTITIES or scenario.residents.size() > Activity.MAX_ENTITIES:
		last_error = "Area activity needs bounded source geometry and cohort metadata."
		return false
	if not _thread.is_started():
		_stopping = false
		var started: Error = _thread.start(_run)
		if started != OK:
			last_error = "Could not start the selected-area calculation thread."
			return false
	selected_id = place_id
	session_id = active_session
	available = true
	# These are existing private, immutable decoded records, like the metadata
	# shared by the snapshot decoder. Caller edits require a new configuration.
	_configuration = {"id":place_id,"polygons":checked_polygons,"scenario":scenario,"session_id":active_session}
	_submit({})
	return true

func sample(snapshot: Dictionary) -> Dictionary:
	_take_output()
	if not available: return {}
	if str(snapshot.get("session_id","")) != session_id:
		last_error = "Area activity is waiting for the current simulation session."
		return {}
	var residents: Variant = snapshot.get("residents")
	if not residents is Array or residents.size() != _configuration.scenario.residents.size():
		last_error = "Area activity requires the complete current cohort."
		return {}
	var stamp: Array = [snapshot.get("sequence",0),snapshot.get("tick",0),snapshot.get("simulation_time",0.0)]
	if stamp != _last_submitted:
		_last_submitted = stamp
		_submit(snapshot)
	return _last_result

func _submit(snapshot: Dictionary) -> void:
	_mutex.lock()
	var wake: bool = _pending.is_empty()
	if not wake: _coalesced += 1
	_pending = {"generation":_generation,"configuration":_configuration,"snapshot":snapshot}
	_mutex.unlock()
	if wake: _work.post()

func _take_output() -> void:
	_mutex.lock()
	var output: Dictionary = _output
	_output = {}
	_mutex.unlock()
	if output.is_empty() or int(output.generation) != _generation: return
	last_error = str(output.error)
	if not last_error.is_empty():
		_last_result = {}
		return
	if not output.result.is_empty(): _last_result = output.result

func clear() -> void:
	_mutex.lock()
	_generation += 1
	var retired_pending: Dictionary = _pending
	var retired_output: Dictionary = _output
	_pending = {}
	_output = {}
	_mutex.unlock()
	retired_pending.clear()
	retired_output.clear()
	available = false
	last_error = ""
	selected_id = ""
	session_id = ""
	_configuration = {}
	_last_result = {}
	_last_submitted = []

func poll() -> Dictionary:
	_take_output()
	return _last_result

func get_state() -> Dictionary:
	_mutex.lock()
	var state: Dictionary = {"available":available,"selected_id":selected_id,"generation":_generation,"pending_jobs":0 if _pending.is_empty() else 1,"in_flight":_in_flight,"completed":_completed,"coalesced":_coalesced,"discarded":_discarded,"last_compute_ms":_last_compute_ms,"error":last_error}
	_mutex.unlock()
	return state

func stop() -> void:
	_mutex.lock()
	_stopping = true
	_generation += 1
	_mutex.unlock()
	_work.post()
	if _thread.is_started(): _thread.wait_to_finish()
	clear()

func _exit_tree() -> void:
	stop()

func _run() -> void:
	var activity = Activity.new()
	var prepared_generation: int = -1
	while true:
		_work.wait()
		_mutex.lock()
		if _stopping:
			_mutex.unlock()
			break
		var job: Dictionary = _pending
		_pending = {}
		_in_flight = not job.is_empty()
		_mutex.unlock()
		if job.is_empty(): continue
		var started: int = Time.get_ticks_usec()
		if prepared_generation != int(job.generation):
			var configuration: Dictionary = job.configuration
			activity.configure(str(configuration.id),configuration.polygons,configuration.scenario,str(configuration.session_id))
			prepared_generation = int(job.generation)
		var result: Dictionary = {}
		if activity.available and not job.snapshot.is_empty(): result = activity.sample(job.snapshot)
		var error: String = activity.last_error
		_mutex.lock()
		_in_flight = false
		_last_compute_ms = float(Time.get_ticks_usec()-started)/1000.0
		if not _stopping and int(job.generation) == _generation:
			_output = {"generation":job.generation,"result":result,"error":error}
			_completed += 1
		else: _discarded += 1
		_mutex.unlock()
