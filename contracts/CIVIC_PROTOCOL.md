# Civic Center protocol version 1

The Python worker owns simulation state. The Godot application owns presentation.
TCP binds only to `127.0.0.1`; each connection sends a launch token in a `hello`
message before receiving scenario data. UTF-8 JSON messages are terminated by LF.
Readers must handle fragmented and combined messages; no frame exceeds 16 MiB.

```json
{"type":"hello","protocol_version":1,"token":"launch-provided-token"}
```

The worker responds with a `scene` message, followed by a complete current
`snapshot`. The default wire representation is full records:

```json
{"type":"scene","protocol_version":1,"session_id":"uuid","scenario":{},"visual_asset":"res://assets/civic-center.glb"}
```

`scenario` has schema_version=1, id, label, tick_hz=200, start_time_seconds,
nodes, edges, buildings and residents. Nodes contain id and position [east,north,up]
in local meters. Edges contain id, from, to and bidirectional. Buildings contain
id, label, entrance_node_id, kind and capacity. Residents contain id, label,
home_id, work_id, departure_tick, return_tick, speed_mps and appearance fields
color, skin_color, trouser_color, bag_color and phase. The fixture is synthetic.

For city scenarios, the scene's `scenario` is a presentation projection:
`presentation_only=true`, `nodes` contains building entrance positions, and
`edges` is empty. `routing_graph_counts` reports the full core graph size and
`authoritative_scenario_sha256` identifies the original scenario. The projection
omits its own `sha256` because it is not the full scenario and cannot be loaded
as one. Python and checkpoints retain the complete graph. Godot receives current
trip polylines in resident snapshots and street geometry from the local map;
neither requires retransmitting the full routing graph on every connection.

Live city clients may request `"snapshot_encoding":"city-dynamic-v1"` or
`"snapshot_encoding":"city-routes-v1"` or `"snapshot_encoding":"city-rows-v1"`
in `hello`. The worker acknowledges the
selected encoding in the scene's `snapshot_encoding`; unknown requests and pilot
scenarios use full records. The Godot client prefers `city-routes-v1`. Protocol
version remains 1, and existing full clients and full replay files remain valid.

All compact city encodings send all immutable resident/building metadata once
in `scene.scenario`. Their snapshots add the selected `encoding` and carry every
resident ID with `activity`, `building_id`, `position`, `heading`, `visible`,
`moving`, `trip`, and `blocked_reason`; every building ID carries `occupancy`
and `resident_ids`. These are complete dynamic collections, never camera-filtered
subsets or deltas against the previous snapshot. Array order may change. The
viewer joins by ID with the matching scene and delivers complete records to the
existing presenter. Missing, duplicate, unknown IDs or missing dynamic fields
are errors. Changes to static metadata require a new scene/session.

`city-rows-v1` retains the route-definition protocol below, but replaces each
dynamic resident, building, and non-null trip dictionary with a fixed-width JSON
array. These are protocol columns, not positions in the scene's entity arrays:
each row still carries its complete ID and may be reordered. No coordinate,
heading, progress, time, or identity is rounded, quantized, inferred, or omitted.

| Row | Columns in exact order |
|---|---|
| Resident (9) | `id`, `activity`, `building_id`, `position`, `heading`, `visible`, `moving`, `trip`, `blocked_reason` |
| Building (3) | `id`, `occupancy`, `resident_ids` |
| Non-null trip (7) | `id`, `segment_index`, `segment_progress`, `departure_tick`, `arrival_tick`, `origin_id`, `destination_id` |

The decoder rejects incorrect widths and collection sizes, unknown or duplicate
entity IDs, invalid column types, non-finite coordinates/headings/progress, and
trip references without reliable definitions. Position is exactly three finite
numbers. Visibility and movement are booleans; building ID and blocked reason
may be null. Trip segment/tick fields are nonnegative integers, progress is in
`[0,1]`, and arrival cannot precede departure. Building occupancy is a nonnegative
integer equal to its resident-ID list length; occupants must be unique known IDs.
Expansion removes the wire `encoding` and delivers the same complete public
dictionaries as the older encodings, including all static metadata and full trips.

Rows are opt-in with `CIVIC_SNAPSHOT_ENCODING=city-rows-v1` in the Godot process's
environment. The default remains `city-routes-v1`: rows reduce bytes and JSON
parsing, but their strict validation/reconstruction offsets much of the total
CPU saving on the measured workload. The setting also accepts `city-dynamic-v1`
and `city-routes-v1`; an unsupported local setting reports an error. Unknown
capability requests received by Python continue to select legacy full records.

The current source-use city checkpoint at tick 240,000 had 1,000 residents, 893
walking. Across 21 interleaved samples on local Python 3.12.10, routes versus rows
used 595,444 versus 364,113 bytes per snapshot (38.9% less). JSON encoding medians
were 10.174 versus 8.999 ms; complete snapshot-plus-encode medians were 25.169
versus 25.280 ms. Godot 4.7.2's final raw-TCP-fixture sample measured JSON parsing
at 42.350 versus 22.703 ms and reconstruction at 72.746 versus 80.293 ms; combined
medians were 125.684 versus 102.186 ms. Earlier paired samples showed only about
3% combined improvement, so this is not a stable frame-rate claim. Reliable
geometry and scene bytes are unchanged, so the initial connection saves much
less than recurring snapshots. Limits and live population presets are unchanged.

Reproduce the CPU comparison and exact production decoder parity from an
existing local checkpoint (large oracle files are ignored local artifacts):

```powershell
venv/Scripts/python.exe scripts/profile_civic_transport.py --checkpoint .cache/sf-1000-v2.save.json --output .cache/city-rows-network-1000
$env:APPDATA = Join-Path (Get-Location) '.local/civic/runtime/roaming'
& comparison/.tools/godot/Godot_v4.7.2-stable_win64_console.exe --headless --path viewer --script res://transport_benchmark.gd -- --directory=../.cache/city-rows-network-1000
& comparison/.tools/godot/Godot_v4.7.2-stable_win64_console.exe --headless --path viewer --script res://scene_adapter_tests.gd -- --wire-fixture=../.cache/city-rows-network-1000
```

The profiler retains untouched authenticated TCP response bytes, including
fragmented hello, reliable route definitions, acknowledgments and stepped states.
Python records complete authoritative oracles at acknowledged ticks. The Godot
test feeds those raw bytes in fragments through its production client/decoding
thread and compares all expanded values; it does not reserialize floats through
Godot before testing. Credentials are never recorded. Tests also cover mixed
encoding clients, process-prepared load, reset/reconnect, malformed rows, and
reliable geometry ordering/eviction under partial writes and snapshot coalescing.

`city-dynamic-v1` includes complete trips. `city-routes-v1` removes only trip
`points`, `node_ids`, and `length_m`; `city-rows-v1` carries the same remaining
values in its trip rows. All timing and segment progress remain in
each snapshot. Before the first reference to a trip ID on each connection, the
worker sends one or more reliable messages:

```json
{"type":"trip_geometries","protocol_version":1,"session_id":"uuid","geometries":[{"id":"trip-id","points":[[0,0,0],[1,0,0]],"node_ids":["a","b"],"length_m":1.0}]}
```

Definitions are immutable within a session. They enter the reliable queue before
the snapshot that references them; they are never coalesced or discarded as
visual snapshots. Definitions are split across frames when necessary; no frame
exceeds 16 MiB. A partially transmitted definition completes before subsequent
frames. The viewer rejects references without definitions. Every scene,
reconnect and disconnect clears metadata and route caches; reconnect sends the
current scene and all currently needed route definitions before the snapshot.

The worker retires inactive trip IDs with a reliable `forget_trip_geometries`
message containing `protocol_version`, `session_id`, and `ids`. This message
follows any partially sent old snapshot and precedes newly needed definitions
and the next snapshot. Removing a cache entry does not change geometry already
held by reconstructed presenter snapshots. Trip IDs never alias a different
journey, including on repeating days. Thus the cache tracks active trips rather
than accumulating every trip throughout the session.

Each connection bounds retained route definitions to 20,000 IDs and a 32 MiB
serialized-size estimate for the cached geometry records. Python and Godot
account their local JSON representations; native heap usage is larger than JSON.
Reaching either limit closes that client with a clear error. Reconnect reloads
currently active routes, but cannot make an oversized active set fit the limit.
The existing 32 MiB outgoing queue limit also applies. Scene metadata is bounded
by the 16 MiB frame cap and 100,000 records per collection in the viewer. Shared
nested geometry/appearance arrays in reconstructed viewer records are read-only
by convention; presentation consumers copy before editing them.

The live Godot client frames incoming bytes on the main thread and sends complete
immutable UTF-8 packets to one owned decoding thread. That thread exclusively
owns the JSON parser, metadata adapter and route cache. It validates and expands
messages in wire order, then publishes complete reconstructed records through a
mutex-protected queue. Only the main thread touches the socket, emits Node
signals, or applies scene/UI state. This follows Godot's
[thread-safety rules](https://docs.godotengine.org/en/stable/tutorials/performance/thread_safe_apis.html)
and [explicit thread shutdown pattern](https://docs.godotengine.org/en/stable/tutorials/performance/using_multiple_threads.html).

The input queue holds at most 256 frames and 32 MiB of packet bytes, plus one
in-flight frame of at most 16 MiB. The output queue holds at most 64 results,
four reconstructed snapshots, and a 32 MiB source-packet byte charge. Shared
static arrays and route definitions are retained by reference; JSON byte charges
are accounting bounds, not claims about native heap consumption. The existing
metadata and route-cache bounds still apply. The socket reader keeps at most
one 16 MiB frame plus its next 1 MiB read. When decoder input is full, it retains
the exact unread frame and stops socket reads until capacity returns. Outgoing
commands continue to flush before main-thread state delivery.

Adjacent completed snapshots from one session may replace each other in the
decoder's output queue. Scene, route-definition, eviction, acknowledgment,
status and error results are reliable boundaries that coalescing cannot cross.
At most one complete snapshot is delivered per rendered frame. This preserves
all authoritative identities and atomic state application while avoiding several
superseded presentations in the same frame. Full replay still bypasses the live
decoder and uses its existing complete-state path.

Reconnect/disconnect increments a connection generation, clears pending queues,
and schedules private cache reset. An already-running parse can finish, but both
publication and main-thread delivery reject results from the old generation.
Session IDs and sequence checks additionally reject stale state within a live
connection. Reset and stop wake a decoder waiting for output capacity; Node
destruction signals stop and joins the thread, including clients freed before
entering the SceneTree. Headless fixture injection also uses this real thread;
its explicit test-only drain helper is never called by production socket polling.

Client profiling distinguishes main-thread `last_process_ms` and `last_parse_ms`
(framing plus delivery) from background `last_json_decode_ms` and `last_expand_ms`
(CPU work attached to results consumed that frame). `last_delivery_ms` measures
synchronous presenter signals. Background timings must not be added to main
frame time; they can overlap. `decoder.stats()` provides bounded queue sizes,
cache counts and the cumulative number of coalesced output snapshots.

On the same saved busy 1,000-resident terrain day, running at 1x in follow mode,
the matched 121-frame sample changed frame-wall p95 from 141.015 ms before
threading to 65.116 ms afterward. Main-thread transport p95 was 49.496 ms;
synchronous state delivery still accounted for 48.552 ms. A separate 10.011 s,
287-frame run measured p50/p95/p99 of 33.328/74.385/105.437 ms with about 880
residents outdoors. These local samples demonstrate removal of decode/expansion
from the main-thread stall; they do not establish a fixed frame-rate guarantee.
Logs are `.cache/sf-busy-1000-throttled.log`,
`.cache/sf-busy-1000-threaded.log`, and
`.cache/sf-busy-1000-threaded-10s.log`.

The core's default `snapshot()` remains fully detached and unchanged for saves
and replays. Live transport calls `snapshot(include_static=False,
include_trip_geometry=False)` and requests detached `trip_geometries(ids)` only
for new references, avoiding repeated geometry allocation and serialization.

Measured on the September 6, 2026 city scenarios, nine interleaved samples per
mode after two warmups gave these median Python snapshot-plus-JSON costs. These
are CPU/transport payload measurements, not rendering FPS. Resident state was
equal after reconstruction in both Python and headless Godot.

| Residents / elapsed seconds / walking | Full snapshot | Route-reference snapshot | Full CPU | Route-reference CPU |
|---|---:|---:|---:|---:|
| 200 / 600 / 105 | 1,373,081 B | 123,007 B | 104.6 ms | 3.7 ms |
| 200 / 1200 / 166 | 1,613,113 B | 160,199 B | 101.9 ms | 6.1 ms |
| 1000 / 600 / 499 | 6,055,813 B | 522,883 B | 498.3 ms | 20.0 ms |
| 1000 / 1200 / 877 | 7,361,768 B | 602,839 B | 720.7 ms | 31.8 ms |

The 1,000-resident case at 1,200 seconds additionally needs 2,706,648 B of reliable
route definitions when a new viewer joins; subsequent snapshots reuse them.
Scene metadata is 1.02 MB for 200 residents and 4.36 MB for 1,000. These source
scenarios predate the denser terrain triangle-edge polylines; future route sizes
and initial definition bursts must be measured separately. Snapshot payload size
after route caching is independent of polyline vertex count. Exact scenario hashes
and timings are in the local `.cache/city-transport-benchmark.json` report.

Every `snapshot` has protocol_version, session_id, sequence, tick,
simulation_time (elapsed seconds), clock_seconds (scenario start + elapsed),
paused, speed, residents and buildings. tick records completed simulation ticks.
Snapshot sequence increases within a session. Reset/population replacement starts
a new session and sends a new scene. A reconnect receives complete current data.

Resident snapshots retain stable IDs and appearance and contain activity, position,
heading, home_id, work_id, building_id, visible, moving, blocked_reason and trip.
Heading is radians: zero faces east; pi/2 faces north. Indoor residents remain in
the snapshot but are invisible. Activities: home, walking_to_work, at_work,
walking_home, blocked. Buildings report occupancy and resident_ids.

`trip` is null indoors or contains id, points, segment_index, segment_progress,
departure_tick, arrival_tick and destination_id. Segment progress is a fraction
in [0,1]. The route consists of absolute local-meter points. The viewer must use
the same displayed root transform for drawing, picking and following; there is no
independent shader route loop. Activity, visibility, occupancy and inspection
changes are displayed together at arrival. Walking gait requires moving=true.

The latest 256 simulation events may be included as `events`, with monotonic event
sequence and lifetime `event_count`. Event history is diagnostic; complete resident
and building state remains authoritative when visual snapshots are skipped.

```json
{"type":"command","request_id":"ui-1","action":"pause","value":true}
```

| Action | Value | Result |
|---|---|---|
| pause | boolean | Pause/resume authoritative clock. |
| speed | 1, 4, 60 or 600 | Change wall-clock playback multiplier. |
| reset | omitted | Repeat the seeded scenario from tick zero in a new session. |
| population | 1, 20, 200, 1000 or 5000 | Initialize a new seeded scenario/session; no deletion from a running household. |
| step | integer ticks, 0..17,280,000 | Advance exactly while paused; used for inspection and deterministic checks. |
| next_event | omitted | Advance exactly to the next scheduled activity event and pause. |
| save | slot name, default `quick` | Atomically save the scenario, completed tick and playback state. |
| load | slot name, default `quick` | Validate and restore a saved day, send a new session/scene and restore saved pause/speed. |
| shutdown | omitted | Acknowledge and shut down the worker. |

An `ack` includes protocol_version, request_id, action, session_id and tick. Errors
include type=error, code, message and request_id when applicable. Malformed or
unauthorized clients must not mutate the simulation. Commands and acknowledgments
are reliable; an unsent complete visual snapshot may be superseded by a newer one.
Never discard bytes from a partially sent frame. Total outgoing buffering is bounded.
An acknowledgment precedes its resulting snapshot and may arrive in an earlier
render frame. Command tests anchor to the acknowledgment's session/tick and wait
for the corresponding complete snapshot before checking displayed state.

Save, load and population preparation run in one owned spawned child process.
A single collector thread handles its local IPC; an explicit thread backend is
retained for deterministic test factories. The production worker uses process
isolation so checkpoint reconstruction and JSON serialization cannot hold the
network loop's Python GIL for several seconds.
Clients may request `"command_status":true` in `hello` to receive reliable
`command_status` messages with `request_id`, `action`, `session_id`, `tick`,
`status` (`pending` or `running`), and `elapsed_seconds`. The first status is
immediate; running status is sent approximately once per second. These report
work in progress, not completion. Clients that do not opt in receive only the
existing final acknowledgment or error.

While a job runs, the current day keeps advancing and publishing snapshots, and
pause, speed, step, next-event, reconnect and shutdown remain available. A second
save, load, population or reset request receives `operation_pending`; the worker
does not accumulate an unbounded preparation queue. A loaded or newly generated
candidate replaces the active model only after background validation and a
successful main-loop transport check. It then sends a new scene, acknowledgment,
required trip definitions and complete snapshot. Errors retain the active day.

A save captures immutable scenario bytes prepared before readiness plus detached
dynamic bytes at one completed tick. The writer reconstructs an isolated model
and validates that capture; it never reads the concurrently advancing live model.
Its acknowledgment includes `captured_tick`, and `tick` identifies that same saved
tick even if the live day has since advanced. Only a final acknowledgment confirms
successful persistence or replacement. Shutdown may finish before a pending
operation acknowledges; an unfinished load/population candidate never commits
after the network loop stops. Checkpoint replacement remains atomic.

Child processes are private descendants, started with `multiprocessing`'s spawn
method and joined after completion. Shutdown/cancellation terminates and joins
an unfinished child before the worker acknowledges shutdown; it cannot continue
writing a save afterward. No client request supplies executable objects. The
public TCP protocol accepts JSON only. An anonymous pipe created by the parent
transfers compressed pickle exclusively from its owned child, with compressed
and decompressed payloads bounded to 192 MiB. This private IPC representation is
not a checkpoint format and must never be accepted from TCP or arbitrary files.

Load/population children return the validated model and precomputed scene,
initial snapshots and route frames. The collector unpickles the model; the main
loop installs it and queues those frames without reconstructing the world or
reserializing its full routes. The immutable checkpoint preparation is rebound
to the received model for future captures. Population preparation preserves the
current geography, terrain and optional land-use manifest paths.

On the repeating 1,000-resident terrain scenario, process isolation changed
these measured loopback costs compared with the prior thread backend:

| Operation | Thread elapsed | Process elapsed | Thread control median / worst | Process control median / worst |
|---|---:|---:|---:|---:|
| Save | 53.1 s | 36.6 s | 312 / 4,140 ms | 31 / 63 ms |
| Load | 39.1 s | 51.1 s | 258 / 1,781 ms | 46 / 125 ms |

The load is slower overall because the child also prepares transport frames and
transfers a compiled model. Its 125.47 MB pickle compressed to 50.90 MB; parent
unpickling took 1.515 s and main-loop installation 0.140 s. Maximum snapshot gap
was 1.80 s, down from 5.63 s. Both processes and their current/prepared models can
coexist temporarily, increasing memory use. These are local measurements, not
fixed deadlines or rendering FPS. The report is
`.cache/city-process-worker-profile.json`; current source also passed a real
spawn/save/load check using the isolated portable Python 3.13.15 runtime.

Save/load slot names contain 1–48 ASCII letters, digits, underscores or hyphens.
They resolve inside the worker's configured save directory; clients cannot send
arbitrary filesystem paths. Their acknowledgments include `slot`. Invalid or
missing saves leave the current simulation unchanged. Checkpoint version 1
reconstructs the deterministic scenario at its saved tick and verifies the full
authoritative state; future mutable schedules or random events will need a new
checkpoint representation before those behaviors can be persisted safely.

Worker readiness prints one flushed JSON line with type=ready, protocol_version,
port and pid. Optional ready-file output contains the same information and is
written atomically. A launcher owns worker and viewer startup/shutdown; credentials
are not written to ordinary logs. CLI diagnostics go to stderr after readiness.

Replay files use `{ "scene": <scene message>, "snapshots": [<snapshot>, ...] }`.
They use the same state application path as live messages. A new session resets
interpolation; stale sequences from the current session are ignored.
