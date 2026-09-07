# Citizen coordinate recording and overlapping newcomers

Status: planned, September 6, 2026. Runtime behavior is unchanged by this plan.

The user reported that increasing population places new agents on top of existing
agents and produces a visual glitch. The next delivery will make individual
citizen positions inspectable over time and prevent live additions from creating
the persistent stacks reproduced below.

Planning defaults, pending user preference: automatic bounded recent history,
longer captures on demand, and validation in both 3D and 2D. Residents are
synthetic. Recorded positions describe the simulation, not observed real people.

## Confirmed cause and baseline

A citizen already has an individual Python object: [Resident](../civic_center/model.py).
The missing class is not the cause. [Population preparation](../civic_center/population.py)
copies an existing home/work assignment, departure time, return time and walking
speed, then changes identity and appearance. Position is derived from route,
elapsed trip time and speed, so those citizens follow identical trajectories.

A deterministic in-memory pilot reproduction used seed 7, 200 starting citizens,
daily schedules, the Python routing backend, and tick 60,000 (300 simulated
seconds). It grew directly to 2,000 without advancing the existing citizens.

| State | Outdoor citizens | Unique exact outdoor positions | Largest coincident group |
| --- | ---: | ---: | ---: |
| Before growth | 47 | 47 | 1 |
| Immediately after growth | 458 | 47 | 18 |
| 60 simulated seconds later | 477 | 50 | 15 |

All 1,800 additions copied an existing assignment/schedule/speed tuple. Original
citizen records were unchanged. Indoor residents sharing an entrance were counted
separately; that is the current expected representation.

Viewer inspection found distinct ID-based slots and transforms in the Rust and
GDScript crowd paths. They receive the coincident coordinates from the model.
Different animation phases and colors do not separate the bodies. The 2D map also
uses those outdoor positions; indoor dots intentionally aggregate at building
centers. The latest performance log has no individual coordinate history, so this
reproduction establishes the model defect without reconstructing the user's
exact visual sequence.

This is a single functional reproduction, not a performance benchmark. The
recorder and fix have not been implemented or measured.

## 1. Give each citizen a clear domain interface

Extract the existing Resident and Trip types into a focused
civic_center/resident.py module, retaining compatible imports from model.py.
Keep one Resident instance per citizen and preserve the event-driven simulation.

Resident will expose stable identity, home/work assignment, resolved schedule,
current activity/building/trip, and a typed pose-sampling method. An immutable
ResidentPose value will carry position, heading, visibility and route progress
at an explicit completed tick. Simulation snapshots and recording will use this
same method so they cannot calculate conflicting coordinates.

Position remains derived from canonical route and time. Avoid a second mutable
position field or a separate simulation loop per citizen. CivicSimulation retains
the shared clock, event queue, routing graph and occupancy bookkeeping. Godot
keeps batched rendering; this change does not create a scene node for every agent.

Newcomer provenance will include join tick, source assignment ID, population
request ID, and schedule-policy version/parameters. Immutable assignment metadata
is written once per recording segment, with references from individual samples.

## 2. Stop cloning entire journeys during population growth

Use a versioned deterministic newcomer policy derived from the world seed and
never-reused resident ID. Reuse eligible home/work pairs and cached routes, while
giving newcomers distinct valid departure/return schedules. Keep walking speeds
unchanged initially to isolate the schedule fix. Existing citizens retain all
their current and future schedule state.

Preparation will search a bounded set of schedule shifts on the detached model.
Start with at most 64 candidates per newcomer, shifting departure and return
together within a configurable 15-minute window. Validate nonnegative times,
journey durations, return ordering and the next daily departure. Prefer the
donor's current activity category where feasible; report the resulting indoor
and outdoor counts rather than promising a fixed number of additional walkers.

Check each directed route/speed cohort against all live profiles, including
citizens currently indoors. Enforce distinct timing and nominal departure
headway separately for outbound and return legs. Derive headway from the
separation threshold and speed, rather than separating copies by one tick.
Return departure is max(outbound arrival, return_tick); recurring headway checks
include the midnight wrap modulo the repeat period. One-off schedules use actual
ticks. A unique combined schedule tuple, ID or appearance alone is insufficient
because one of the two legs can still be identical.

Check candidate outdoor positions against visible survivors and accepted
newcomers using a spatial grid, with an initial configurable 0.75-meter
center-to-center separation. This is an admission threshold, not a calibrated
personal-space model or a guarantee that animated meshes cannot touch. Exempt
hidden indoor residents; never scatter coordinates off routes or into buildings
to make a check pass.

Prepare final schedules off the simulation loop. At the actual commit tick,
resample all affected positions and revalidate spacing, ordinary schedule
invariants, and existing transport/checkpoint budgets before mutation. The day
may have advanced during preparation. Do not reuse coordinates captured at the
request tick as current coordinates.

If no valid candidate or commit-time clearance is available, reject the entire
request with a specific explanation: try a smaller population or advance the
simulation. Preserve the roster, allocator, session and camera, with no extra clock or
event changes caused by rejection. Normal day advancement during preparation
continues unless paused. There is no partial addition and no new exceptional waiting queue in
this first delivery. Existing command idempotency remains in force.

Persist the resolved schedules in the existing v3 scenario/checkpoint data.
Old saves retain their original schedules, including any historical coincidences;
loading a save must not silently reposition citizens. Do not reuse prepared
scene/checkpoint bytes if final schedule metadata changes. Any future admission
queues or continuous avoidance would need explicit new reconstruction semantics.

The first fix prevents overlapping joins and removes the reproduced cloned
trajectories. It does not promise collision-free walking at every intersection
or solve later crowd interactions. Continuous avoidance is a separate simulation
feature with consequences for arrival times and daily fast-forward behavior.

## 3. Record individual coordinates without overwhelming diagnostics

Add a CitizenCoordinateRecorder owned by the authoritative worker, with one
writer per output stream. Store captures under the already ignored
.local/civic/recordings/<run-id>/ directory. Reference their relative paths,
status, sample counts, gaps, bytes and summaries from the existing run JSON.
Keep full trajectories out of its repeatedly rewritten aggregate document and
out of the live telemetry/console message stream.

Proposed first-delivery limits:

| Setting | Default |
| --- | --- |
| Automatic history | All citizens, at most 1 sample per second of wall time |
| In-memory retention | Most recent 30 seconds, capped at 32 MiB including buffers/indexes |
| Population incident capture | Recent history, exact before/after commit states, then 10 seconds |
| Selected-citizen detail | On demand, up to 10 Hz for at most 32 selected/flagged citizens |
| Writer queue | 8 MiB, immutable bounded batches |
| Disk capture budget | 128 MiB per run, including metadata and all sidecars |
| File segments | Up to 16 MiB each; each segment independently interpretable |

These are proposed ceilings, not measured overhead claims. Repeated population
requests inside an active post-event interval extend/coalesce that capture within
the same budgets. Persist the recent tail on normal shutdown. Longer manual
captures retain the per-run disk bound unless the user explicitly raises it.

Use packed numeric buffers and shared metadata references for the ring. Do not
copy full resident dictionaries or route geometry into every sample. Tap the
existing canonical pose/snapshot calculation once per sample interval, independent
of viewer count or negotiated transport encoding. A headless worker can sample
through the same pose interface without inventing a second state representation.

Sampling cadence uses a monotonic wall clock, while each sample records the
actual completed simulation tick. Paused repeats can be represented by explicit
unchanged-state spans. Faster simulation speeds do not multiply recorder rate;
time jumps and missing intervals remain explicit. Sampling does not provide an
exact trajectory between every two recorded points.

Capture before/after membership and coordinates at one authoritative commit tick,
plus addition/removal provenance, request/commit/rejection and reset/load events.
A failed request has a rejection record and unchanged state, not a successful
birth event. Before/after snapshots are immutable captures on the owning loop;
JSON serialization and file I/O run in the background. Recording must not turn a
successful population operation into a failure if the disk or queue is unavailable.

When budgets are reached, drop/coalesce periodic detail first and count gaps.
Reserve bounded space for membership/boundary summaries; report explicitly if
full boundary coordinates cannot be retained. At the disk cap, stop appending
and surface Recording full. Never silently overwrite older runs. A disk error
disables persistence with one visible warning while simulation continues.
Complete JSONL lines remain readable after a crash; an incomplete trailing line
and unfinished manifest are identifiable.

## 4. Make the data unambiguous

The versioned capture header records run ID, recording epoch, world/scenario
fingerprints, origin and coordinate units, tick rate, policy version, requested
sampling settings and numeric precision. Domain coordinates remain unrounded
east/north/up meters. Latitude/longitude conversion is available for inspection
and export, rather than repeated in every sample.

| Record layer | Fields needed to investigate the glitch |
| --- | --- |
| Authoritative sample | Citizen ID, tick, activity, building/trip ID, position, heading, visible/moving state, route segment and progress |
| Lifecycle/provenance | Joined/removed at tick, donor assignment, resolved schedule, roster revision and population request |
| Presentation sample | Source session/sequence, previous/current snapshot ticks, interpolation alpha, atomic flag, displayed tick and position |
| 3D submission | Backend, transient slot index, actual submitted root and its numeric precision; convert back to domain axes for comparison |
| 2D marker | Marker world/screen position, map projection settings and whether it represents outdoor position or indoor building aggregation |

Authoritative worker and viewer traces use separate streams and files, joined
through run/epoch/session/revision/ID and source snapshot identifiers. Record
monotonic timestamps and clock uncertainty; do not compare poses from different
ticks as though they were simultaneous. Never treat a slot index as citizen
identity. Save/load, reset and reconnect boundaries are explicit because ticks
and sequences can move backward or restart.

Full-population authoritative history is separate from the bounded set of
presentation traces. Capture submitted CPU-side transforms; no GPU readback is
needed for this defect. Missing/out-of-view samples have an explicit reason.
World-coordinate coincidence and overlapping screen pixels are different findings.

Raw captures contain synthetic citizen IDs and are local debugging data. Public
patch-note evidence contains aggregate counts and timings, not individual paths,
tokens or private filesystem locations.

## 5. Add inspection and overlap diagnostics

Add a Coordinates section to Performance with automatic/manual/off mode, capture
status, effective rate, bytes/gaps, Save recent history and Open capture folder.
The resident inspector shows ID, ENU position, trip progress and newcomer
provenance, with optional selected-citizen trail capture.

Use a spatial-grid detector to report exact outdoor coincidences, near neighbors,
largest group and duration. Cap group details and pair work; a pathological stack
must not cause quadratic logging. Treat persistent matching trajectories as
stronger evidence than one crossing or nearby pedestrians. Quantized grid cells
only find candidates; confirm distances with the original coordinates.

Allow inspecting/cycling the IDs in a coincident outdoor group and show an overlap
count on the 2D map. Keep indoor building aggregation labeled. A screen-space
badge improves inspection without claiming that underlying positions changed.

## 6. Delivery sequence and acceptance

1. Preserve the reproduction as a failing regression. Extract the citizen pose
   interface with existing snapshots, saves and behavior unchanged.
2. Add bounded recording, lifecycle boundaries and a small offline analyzer that
   filters by citizen/time and reports coincident positions and trajectory groups.
3. Implement deterministic newcomer schedules and atomic join-time spacing.
4. Add Performance/inspector controls and selected-ID presentation traces.
5. Run rendered regression and recorder-overhead comparisons; update guides and
   patch notes with measured results.

Required checks include:

- The 200 -> 2,000 pilot reproduction and the user's city conditions, both paused
  and running, with checks immediately and 1/10/60 simulated seconds afterward. Admitted newcomers meet the join threshold; rejected changes
  preserve exact prior state. Count outdoor workload explicitly.
- Every original citizen remains identical to an unchanged control simulation.
  Unique IDs, occupancy, event ordering and removal cleanup remain correct.
- Growth/shrink cycles, delayed preparation, deterministic retry, midnight,
  departures/arrivals, repeated days, and exact save/load continuation.
- Rust, GDScript-buffer and individual rendering plus 2D: correct ID/slot/root
  association, no stale instances, correct picking and follow across resizing.
- Intentional indoor grouping and brief crossings are distinguished from
  persistent coincident outdoor agents.
- Recorder on/off produces identical simulation state and consumes no simulation
  RNG. Test slow/full disk, queue floods, caps, shutdown and truncated-line recovery.
- Logs link to captures and remain bounded; recordings stay ignored by Git.
  Existing portable packaging includes the new module without requiring Godot
  objects or optional native helpers in the authoritative model.

Measure recorder off, automatic and selected-detail modes with at least three
matched runs per condition at the same saved state, camera, display, renderer,
cache and hardware-monitor settings. Record frame p95, worker sampling/encode
time, population request/commit/handoff latency, CPU/memory, bytes per second,
effective rate and dropped samples. Document regressions as well as improvements.

Fix validation and performance validation are separate: eliminating the reproduced
stack does not by itself establish an FPS gain or a supported population ceiling.
