# Living San Francisco

This is the Godot application with a live Python resident simulation. Residents
keep their identities as they leave home, walk to an assigned workplace, arrive,
remain at work and return home. Building occupancy changes with those trips.

The detailed City Hall pilot uses original stylized Blender architecture. City
mode uses imported San Francisco streets and building footprints, with USGS
terrain when installed. Optional parcel-use data guides home/work eligibility
and provides a source-use overlay. Residents, employers and schedules are
synthetic; population calibration remains planned work.

## Run from the repository root

```powershell
python -m civic_center
python -m civic_center --mode map --location city
python -m civic_center --population 20 --mode follow
python -m civic_center --population 1 --mode walk
python -m civic_center --world city --location city
python -m civic_center --place "Mission" --use-overlay
python -m civic_center --place "Transamerica Pyramid" --lighting fixed
python -m civic_center --world pilot --no-geography
```

The module prefers this checkout's `venv` interpreter when present. Godot is found
through `GODOT_BIN`, the packaged runtime, PATH or the existing portable engine in
`comparison/.tools/godot/`. The launcher opens a loading window, prepares the
worker, then connects the viewer. It closes the worker when the viewer exits.
Each launch also prints the path to its [JSON run log](#json-run-logs).
The default `--world auto` selects city mode when its geographic manifest is
installed, otherwise the stylized pilot. City scenarios are cached by data,
builder version, seed and cohort size. Explicit `--scenario` and `--load` take
precedence over automatic scenario selection.

The clock begins at 07:59:50. The first resident leaves at 08:00; the others depart
over twenty minutes. Return trips start at 17:00. Use **Next activity** to jump to
the next departure or arrival and pause, or choose faster playback to inspect the
day. Search/select a resident in the right panel; indoor residents remain there.
Current city scenarios repeat those schedules on subsequent days. Legacy
one-day fixtures retain their original behavior. The displayed day count and
time describe simulation time, independent of the computer's current clock.

| Control | Action |
|---|---|
| 1 / 2 / 3 | Overhead / walking / follow the selected resident |
| 4 | Switch to the lightweight 2D agent map |
| Drag / mouse wheel | Look or orbit / zoom in 3D; pan / zoom in the 2D map |
| W / S / A / D | Move forward / backward / left / right relative to the view; walk in ground mode |
| Shift | Move faster while holding WASD |
| Q / E | Rotate the view left / right |
| Space | Pause/resume the authoritative simulation |
| N / Next activity | Jump to the next scheduled activity and pause |
| R / Reset day | Repeat the seeded scenario from its beginning |
| F5 / Save day | Save to the local `quick` slot |
| F9 / Load day | Restore the `quick` slot, including tick, pause and speed |
| H / G | City Hall / city overview when geography is installed |
| U | Toggle observed parcel-use colors and the source legend |
| Follow daylight | Follow the simulation clock or restore fixed inspection light |
| Illustrative facades | Show or hide approximate window patterns on nearby buildings |
| Street trees | Show or hide the optional recorded-location tree layer |
| Shift + drag | Pan the overhead camera across the map |
| Destination search | Jump to a named analysis area or Recreation and Parks property; walk from a nearby source street |
| Restart with population | Create a seeded cohort in the same world; city presets currently stop at 1,000 |

WASD pans the overhead and 2D views. In **Follow**, it offsets the camera while
continuing to follow the selected resident; press **3** or **Follow** again to
recenter. Ground mode retains walking collisions, and the left/right arrow keys
also turn there. Camera keyboard controls pause while typing in a search field
or when the application window loses focus.

Use `--mode map --location city` or press **4** to inspect residents on a flat 2D
map. It draws streets and building footprints with activity-colored markers, including
people at home or work. Drag to pan, scroll to zoom and click a marker or building
to inspect it. **Center selected** frames the selected person; **H** returns to
City Hall. Indoor markers use their building centers where available, while the
simulation retains each person's original position. People sharing a location
can overlap; the resident list lets you select each identity individually.
The resident search, clock, pause and activity controls use the
same simulation as the 3D views; switching views preserves the running day.
The map's **Simulation speed** selector stays available with full controls hidden.
Press **1**, **2** or **3** to return to a 3D view.

The 2D mode disables 3D drawing, terrain rendering and character animation while
active. It is intended for watching agent behavior with much less graphics work.
Simulation, routing and snapshot processing still run, so population capacity
also depends on those costs. City map geometry comes from the installed source
data; the pilot retains its illustrative geometry.

Changing population restarts the scenario. It does not remove residents from a
running household. The live city presets stop at 1,000; the older stylized pilot
also has a 5,000-person stress preset. Those counts are not established
interactive capacity. Nearby limb articulation is limited to 300 people within
80 meters; other outdoor people remain represented, and indoor people remain in
the simulation and inspector.

Saved days live in `.local/civic/saves/`. Resume a specific saved day at launch:

```powershell
python -m civic_center --load .local/civic/saves/quick.json
```

Saves capture the authoritative scenario, tick, schedules, occupancy, pause and
speed. Version 2 compresses immutable scenario data and verifies reconstructed
metadata and route geometry. Older version 1 saves remain readable. Save/load
jobs run in a bounded child process; the UI reports pending and completed work.
The current 1,000-person save is approximately 13.7 MB and restores exactly.

The selected scope is the whole of San Francisco. The launcher automatically detects a generated
`.local/civic/geography/sf-geography.json`; use `--geography PATH` for a different
manifest or `--world pilot --no-geography` to open the isolated City Hall pilot.
The terrain grid at `.local/civic/terrain/terrain.json` is also detected, or can
be supplied with `--terrain PATH`. Citywide population calibration remains
separate from synthetic stress presets.

Named navigation is optional and loads `places-index.json` beside the geography
manifest. Exact IDs and names take precedence over partial searches. Analysis
areas are Census-tract reporting groupings, not legal neighborhood boundaries.
Recreation and Parks holdings include plazas and facilities and do not represent
complete park or vegetation coverage. See [source preparation and provenance](../docs/SF_GEOGRAPHY.md).

Named analysis areas and Rec/Park properties have a source-boundary outline.
It is a map annotation that stays visible through buildings; holes remain open,
and missing terrain samples create gaps. Landmark search includes City Hall,
Transamerica Pyramid, Coit Tower and Sutro Tower. Their original Blender exteriors
use source locations and published heights with approximate architectural detail.

Daylight follows a representative September day at San Francisco's latitude;
it repeats with the simulated daily schedules. Sky colors and night fill are
artistic, not live weather. `--lighting fixed` restores consistent inspection
light. `--facades off` hides the illustrative window treatment. These patterns
do not add observed floor, window or occupancy information to the simulation.

The optional tree layer uses the replacement Public Works inventory. Tree
positions and species text are sourced; tree dimensions and canopy forms are
illustrative. It does not represent every tree in the city's parks. `--trees off`
hides it for visual or performance comparisons.

Optional Rust routing is built with `venv/Scripts/python.exe scripts/build_civic_native.py`.
`CIVIC_ROUTING_BACKEND=auto|python|rust` selects the backend; automatic mode uses
Python when the library is absent. Native load, ABI or route errors remain
explicit. Tested route results, checkpoints and scenario hashes are identical.
The separate [Godot crowd helper](../native/civic-godot/README.md) is also optional.
It packs existing render transforms; it does not own resident simulation state.

## JSON run logs

Every launch through `python -m civic_center` automatically creates a separate
UTF-8 JSON file under `.local/civic/logs/`. The filename contains a UTC timestamp
and unique run ID, and the terminal prints its path before Godot starts.

The log includes requested settings and input paths, startup stages and timings,
geometry-cache hits/misses, recent frame-time summaries, graphics information,
aggregate resident counts, hardware inventory and usage history, bounded
diagnostics, and the exit result. Observed
runtime counts reflect saved days, replays, and population changes during play;
the `settings` object preserves the original launch request.

Viewer metrics update about every ten seconds and on startup completion and
normal viewer exit. Hardware samples are collected every second by default. The launcher atomically replaces the same JSON document, so it
remains readable during a run. Final status is `completed`, `cancelled`, `failed`,
or `interrupted`, with UTC timestamps and exit codes. A forcibly killed launcher
or power loss can leave the last `starting`, `loading`, or `running` record with
`ended_at: null`; that record does not imply the process is still alive.
Viewer timing starts inside Godot; total run duration also includes engine startup
and process cleanup.

Use a different directory when needed:

```powershell
python -m civic_center --log-dir .local/civic/my-run-logs
```

The schema is versioned (`schema_version: 1`). `metrics.runtime` holds the latest
aggregate simulation, presentation, startup, and performance summaries.
Repeated viewer samples replace prior summaries. Hardware samples retain a
bounded history plus summaries covering the whole monitored run.
Logs omit authentication tokens, environment variables, and individual resident
routes. Logs are retained between launches and can be deleted when no longer
needed. If the directory cannot be written, the launcher reports that logging is
unavailable and continues running. Help and invalid command-line arguments do
not start a run or create a log.

## Hardware diagnostics

Hardware reporting starts automatically with each normal launch and runs during
loading and play. For a source checkout, install the monitoring libraries once
into the Python environment used by the launcher:

```powershell
venv/Scripts/python.exe -m pip install -r civic_center/requirements-monitoring.txt
python -m civic_center
```

The optional libraries are psutil and NVIDIA's official NVML Python bindings.
They are included in newly generated portable Windows builds. The application
still starts if dependencies, drivers, or individual sensors are unavailable;
the report records that limitation instead of inventing a zero reading.

Each run's existing JSON document contains a `hardware` section:

| Field | Meaning |
| --- | --- |
| `inventory` | OS, CPU model and core counts, installed RAM, application volume capacity, NVIDIA GPU model/driver/VRAM, and provider capabilities. |
| `samples` | UTC and elapsed timestamps, system/per-core CPU usage, RAM/swap, disk I/O, owned process usage, available temperatures/fans/battery, and NVIDIA GPU usage. |
| `summary` | Count, minimum, maximum, arithmetic mean, and latest value for bounded numeric measurement keys across the monitored run. |
| `status` and `errors` | Whether monitoring ran, stopped, was disabled, or encountered a provider failure. |

Process records separate the launcher, Godot viewer, simulation worker, and
preparation process, including their descendants. Process CPU percentages use
100% for one busy logical core, so a multithreaded process can exceed 100%.
System CPU percentages and the machine-normalized process total use 0-100%.
Summed resident memory can count shared pages more than once; private memory
is also recorded where supported. Disk I/O counters describe the whole machine;
process I/O is reported separately.

NVIDIA samples include adapter-wide GPU and memory-controller utilization,
VRAM used/free, GPU temperature, power in watts, clocks, and fan percentage where
supported. They include other applications' GPU activity. Memory-controller
utilization is activity, not the percentage of VRAM occupied. AMD/Intel sensor
telemetry is not currently provided by this backend; the viewer still records
its active graphics adapter. CPU temperatures and fan readings commonly remain
unavailable on Windows without an additional sensor provider. CPU frequency
may be nominal on that platform. Every provider reports availability.

The most recent **360 samples** are retained, about six minutes at the default
interval. Older samples are dropped, while numeric summaries keep earlier peaks.
Incomplete process totals are excluded from numeric summaries; available
individual process readings remain. Each sample includes the latest known viewer
context (camera mode, resident count, startup stage and frame p95) and the timestamp of that viewer update.
Viewer context updates less often than hardware; it is not a synchronous GPU
profiler. Frame times measure application callback intervals.

Hardware-only writes occur about every five seconds; viewer events and normal
shutdown also flush samples. An abrupt termination can lose the most recent
buffered samples. Monitoring uses a background thread and waits at most two
seconds for sensor calls during shutdown; ordinary log-file writes still depend
on the filesystem. It records `collection_ms` for sensor calls and process
registration. This excludes log serialization, disk writes and lock waits, and is not a measure of
total monitoring overhead.
It does not send data anywhere or enumerate unrelated process command lines.

```powershell
python -m civic_center --hardware-interval 2
python -m civic_center --no-hardware-monitor
```

The interval accepts 0.25-60 seconds. Disabling hardware monitoring preserves
the existing application logs and makes comparisons of monitoring overhead
possible. Changes to sampling cadence affect the history duration and the
short spikes it can observe. See [patch notes](../docs/PATCH_NOTES.md) for
validation and measured observations.

## Loading and prepared scenery

See the [preprocessing patch note](../docs/PATCH_NOTES.md#2026-09-06---prepared-scenery-and-startup-improvements) for the recorded
startup savings, preparation cost, and benchmark conditions.

The desktop window now opens before resident preparation. It shows the current
loading stage while homes, jobs, routes, and the starting view are prepared.
You can close the window to cancel startup; the launcher stops its own preparation
and simulation processes. Startup failures appear on the loading screen.

Building/road tiles and terrain chunks are saved automatically under
`.local/civic/render-cache/` after their first construction. Later launches and
visits reuse matching geometry. Changed source data, terrain, pilot settings,
or geometry builders select a new cache entry; damaged entries rebuild.
The source elevation grid, resident simulation, and current material controls
remain live. The 2D map keeps its existing lightweight drawing path.

To prepare the City Hall area before playing:

```powershell
venv\Scripts\python.exe scripts/prepare_sf_render.py
python -m civic_center
```

The default preparation covers the square within 750 meters east/west and
north/south of City Hall, nearby detailed terrain, and the city's coarse terrain.
Use `--scope city` to prepare all installed building/road tiles and both terrain
detail levels. This takes more time and disk space. Ctrl+C cancels the preparation
and closes its Godot process.

```powershell
venv\Scripts\python.exe scripts/prepare_sf_render.py --scope city
python -m civic_center --no-render-cache
```

`--no-render-cache` provides a comparison using freshly generated geometry;
it neither reads nor writes prepared meshes. `--render-cache PATH` selects another
cache directory in either command. Generated caches are disposable; the installed
source manifests retain geographic attribution. A preparation report is written
to `.cache/scenery-prepare.json`.

This first preprocessing stage covers terrain and building/road meshes. Trees,
landmark imports, 2D buffers, and persistent route bundles remain future work.

## Verify

```powershell
venv\Scripts\python.exe -m pytest tests/civic_center -q -o cache_dir=.cache/pytest
python -m civic_center --population 1 --headless --smoke-test
python -m civic_center --population 1 --mode map --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --no-geography --mode map --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --replay-index 2 --mode follow --screenshot .cache/civic-follow.png
```

Headless checks validate state, identity and controls. Rendered checks additionally
compare submitted crowd transforms and capture actual graphics. The local Windows
sandbox may print a certificate-store warning independent of rendering; the
launcher directs development shader caches into the writable `.local/civic/` area.
Map checks cover indoor and outdoor identities, unmodified simulation positions,
selection, wheel direction, map/3D switching and live pause/reset/reconnect.
The [viewer checks](../viewer/README.md#checks-and-replay) also include standalone
2D projection, footprint and marker tests.

Regenerate the deterministic seven-checkpoint replay with
`venv\Scripts\python.exe scripts/record_civic_replay.py`. Stage the shared Blender
export into the viewer with `venv\Scripts\python.exe scripts/stage_civic_assets.py`.
The viewer loads `res://assets/` and does not read the comparison directory at
runtime. Repository launch uses a Godot executable and Python. The
[portable Windows builder](../docs/WINDOWS_BUILD.md) bundles both runtimes and
prepared data into a folder with a double-click launch script.

See [the protocol](../contracts/CIVIC_PROTOCOL.md),
[implementation plan](../docs/GODOT_NEXT_STEPS.md), and
[ongoing evidence](../docs/OVERNIGHT_PROGRESS.md).
