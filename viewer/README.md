# San Francisco desktop viewer

This is the selected Godot application's viewer. Its resident positions,
activities, home/work assignments, trips and building occupancy come from the
Python simulation. The six renderer experiments remain in `comparison/`.

From the repository root:

```powershell
python -m civic_center --population 200
python -m civic_center --mode map --location city
```

When city geography is installed the launcher selects the observed city world.
Use `--world pilot` to explicitly open the original detailed City Hall study.
For a single resident's complete day in that study:

```powershell
python -m civic_center --world pilot --population 1 --mode follow
```

The day starts at 07:59:50. **Next activity** advances to a departure or arrival
and pauses; use it to skip the hours spent inside the workplace. Residents remain
in the list while indoors. Select one there, then use **Follow**. Clicking a
building shows its current occupancy. City mode uses observed geographic sources;
home/work assignments and use of street centerlines as walking routes are generated
assumptions. The original pilot retains its explicitly illustrative architecture.

| Control | Action |
|---|---|
| 1 / 2 / 3 | Overhead / walk / follow |
| 4 | Lightweight 2D agent map |
| Drag | Orbit or look in 3D; pan in the 2D map |
| Mouse wheel | Zoom overhead, follow or 2D map |
| Shift-drag or middle drag | Pan the overhead map |
| G / H | City overview / City Hall |
| U | Toggle observed parcel-group use colors |
| Tab | Collapse or expand the controls and resident inspector |
| W / S / A / D | Move forward / backward / left / right relative to the view; walk in ground mode |
| Shift | Move faster while holding WASD |
| Q / E | Rotate the view left / right |
| Space | Request pause/resume |
| T | Cycle 1×, 4×, 60×, 600× |
| N | Advance to the next activity and pause |
| R | Reset the seeded day |
| Escape | Open the vertical options menu; return from submenus or back to the city |
| F5 / F9 | Save / load the local quick slot |
| F3 / Performance | Open or close live charts, hardware readings, logs and experiment controls |
| F11 | Toggle fullscreen |
| Performance: Target / Apply live | Add or remove synthetic residents while keeping the current day |
| Performance: UI / window mode | Choose 100%, 125% or 150% UI scale; windowed, maximized or fullscreen |
| Resident list/search | Select a persistent resident, including indoors |
| Restart with | Initialize a new day with the current scenario's supported population presets |

WASD pans the overhead and 2D views. In **Follow**, it offsets the camera while
the camera continues following the selected resident. Press **3** or **Follow**
again to recenter. Ground mode retains walking collisions; left/right arrow keys
also turn there. Camera keyboard controls pause while typing in a search field
or while the application window is unfocused.

Resize or maximize the window to use a wider screen. Controls and inspection
panels scroll when space is limited; **Inspector / controls** switches between
them in compact layouts. The Performance panel becomes a right dock on wider
layouts and a bottom drawer on narrower ones. Drag its **Resize** grip to adjust
the space reserved for observations.

Window size, position, mode and UI scale are remembered in Godot's local user
data as `display-settings.json`. Saved geometry is clamped to the current screen.
Launch options override those preferences; `--no-display-settings` skips both
reading and writing them:

```powershell
python -m civic_center --performance --window-size 1920x1080 --window-mode windowed --ui-scale 1.25
```

The **2D Map** view (`--mode map`, or **4**) displays flat streets and building
footprints with activity-colored resident markers. Indoor residents appear at
their building centers when available; their original simulation coordinates
remain unchanged. Drag to pan, scroll to zoom, and click a resident or building
to inspect it. **Center selected** frames the selected resident, and **H** frames
City Hall. Markers sharing a location can overlap; the resident list keeps each
identity selectable. Resident search and simulation controls remain available.
The map's **Simulation speed** selector remains visible when full controls collapse.
**1 / 2 / 3** returns to a 3D view without restarting
the day. Both views use the same authoritative snapshots and resident identities.

While the 2D map is active, 3D drawing, terrain rendering and character animation
are disabled. This reduces graphics work; it does not remove simulation, routing
or snapshot-processing costs. The map's source streets and footprints remain
observed geography, while the people and their schedules remain synthetic.
The original pilot uses its illustrative map geometry.

The Python launcher saves [one JSON run log](../civic_center/README.md#json-run-logs)
under `.local/civic/logs/`, including startup/cache timings and compact runtime
summaries. The viewer emits `GODOT_APPLICATION_RUN_METRICS` every ten seconds and
at shutdown; the launcher records those summaries without printing them to the
terminal. Starting Godot directly emits diagnostics but does not create the
launcher's JSON file.

Press **F3** or **Performance** to observe a run. **Charts** keeps frame intervals
and system CPU/GPU trends beside the population controls; the headline shows
CPU, RAM, GPU and VRAM readings. **Details** adds per-process CPU/RSS, supported
GPU temperature/power, system disk activity, worker timing and decoder costs.
**Logs** supports severity/source filters, text search, paused auto-scroll and
clearing the visible history. **Open run log** opens the current JSON report;
**Record point** stores an aggregate comparison point in that report.

Enter a whole-number **Target** from 1 to 5,000 and click **Apply live**. The step
buttons adjust the proposed target; typing or stepping does not change the
simulation until Apply. Preparation runs while the existing day continues, or
remains paused. The committed change retains surviving residents, the current
clock, speed, selection and camera. Removing a selected/followed resident clears
that target and leaves the camera in place. **Restart with** remains a separate
new-day action. Added residents are synthetic load experiments; the target range
does not establish an interactive capacity or measured San Francisco population.
Recorded replay and older workers without this capability disable live changes.

The console also provides pause/resume, next activity, speed, 2D/3D and save/load
buttons. Frame statistics describe CPU callback intervals, not GPU execution
time. GPU readings describe the adapter as a whole, and process CPU can exceed
100% because 100% represents one busy logical core. Missing readings are
unavailable; older samples show their age and become stale rather than appearing
as new chart values. The UI retains at most 120 chart samples and 300 log rows;
closing it stops chart updates while the launcher continues recording.

Launcher diagnostics arrive over a separate authenticated local connection.
A disconnected feed leaves local viewer metrics available. Direct Godot launches
also retain local metrics, but need the launcher for collected hardware and the
JSON run report.

Press **Escape** for the vertical game menu: Return to city, Save day, Display,
Controls, Performance, and Save & Exit. The menu pauses the authoritative day and
blocks camera input; Return restores the previous playback state. Tab/Up/Down
navigate, Enter activates, and Escape returns from a submenu before closing the
menu. Display uses the existing window and UI-scale preferences.

In a launcher-owned live game, **Save & Exit** and normal window close wait for a
confirmed **exit-recovery** save, separate from the quick slot. Errors retain the
menu with Retry and explicit Exit without saving; an unacknowledged save is not
reported as successful. See the [recovery workflow](../civic_center/README.md#escape-menu-and-safe-exit).
The launcher remains the worker's lifecycle owner and finishes run diagnostics
after Godot exits. A directly connected viewer closes only its own connection.
**Reconnect** obtains a complete current snapshot after a recoverable interruption.

**Follow daylight** follows the displayed clock using an approximate September 6
sun direction for San Francisco/PDT. The same representative day repeats; this
does not model seasons, weather or a real calendar. Morning/evening colors and
night ambient fill are visual choices that keep the city inspectable. Toggle it
off, or launch with `--lighting fixed`, to restore the original fixed sun/sky for
controlled comparisons. Paused clocks freeze the cycle.

**Controls → Illustrative facades** adds restrained procedural windows and floor
rhythm to nearby extruded buildings. These original visual details do not imply
observed windows, materials or floor counts. A shared shader uses wall coordinates
in meters, fading the pattern with distance and pixel size; roofs, distant boxes
and landmark assets retain their existing treatment. Parcel-use colors bypass the
pattern exactly. Use `--facades off` for a controlled comparison.

**Controls → Street-tree inventory** uses the replacement Public Works inventory
for recorded locations and species text. The broadleaf, conifer and palm meshes,
heights, canopy widths, trunk thickness and colors are original illustrative
choices; DBH does not set their dimensions, and its source metadata does not state
units. This inventory does not cover every park tree. A DataSF link and source
counts are available beside the toggle; `--trees off` disables the layer.

Tree tiles and their index must match the installed geography and checked file
hashes. The viewer retains at most 24 tiles and 12,000 tree instances, displays at
most 6,000 nearby instances, and builds one tile per frame. Three shared meshes
use MultiMeshes, with shadows disabled; silhouettes shrink away from 650 to 950
meters and city-scale views omit the layer. Coincident source IDs keep their
recorded coordinates and share the lowest-ID silhouette, with suppressed counts
reported separately. Missing terrain is skipped. The pilot footprint excludes
source trees where its authored trees already exist. Trees do not change resident
routing or walking collision rules.

## Geographic context and terrain

The optional `--geography` manifest and `--terrain` grid load independently of the
resident snapshot protocol. The launcher detects generated files under
`.local/civic/geography/` and `.local/civic/terrain/`. Missing or invalid optional
data leaves the pilot available and displays a diagnostic.

City mode starts with compact clock/playback controls. **Controls** opens the
full simulation panel and **Show** opens resident search and inspection. Clicking
a person or building opens its inspector; hiding a panel preserves selection.

The optional `assets/landmarks.json` loads original architectural exteriors for
City Hall, Transamerica Pyramid, Coit Tower and Sutro Tower. They use observed
source locations and cited architectural heights, with bases on the shared
terrain triangle surface. Facades, dome, taper and trusses remain approximate
architectural studies. Picking retains the primary source building ID and
available modeled occupancy; height-reference links identify the primary source.
Sutro's three overlapping source parts map to its single primary tower.
Landmarks are hidden in the original pilot; detailed extrusions and distant
silhouettes are omitted only after the replacement asset loads successfully.

`geography.gd` streams 500-meter tiles into merged building/street meshes. It keeps
at most 48 detailed tiles in memory and builds at most one detailed tile per frame.
Nearby buildings are extruded from source footprints and heights; farther cached
tiles use flat footprints, and city overview uses an explicit street-map overlay. Street segments
are clipped to tile cores to prevent duplicate strips across neighboring tiles.
There is no scene node for each geographic building. Mapped buildings can be
inspected through an analytical footprint pick; modeled buildings show occupancy.

The optional `visual-index.json` beside the geography manifest streams derived
building silhouettes and courtyard roof triangulations. It must match both the
canonical manifest identity and its exact file checksum; every visual tile also
passes its byte checksum. Coarse oriented boxes use one MultiMesh per tile with
shadows disabled and disappear where detailed meshes substitute. There are no
individual building nodes. Roof enrichment preserves the original source records
and their courtyard rings. Without valid hole-aware roof data, the viewer omits
that roof and retains its outer/courtyard walls. Road widths are inferred display widths recorded by ingestion,
not measured pavement geometry.

The optional `use-index.json` adds the **U / Parcel-group use** overlay. Its source
hashes must match the installed geography and each tile's exact bytes. Compact
color tiles classify source residential units and dominant commercial area; only
48 nearby group-metadata tiles stay cached. Colors switch through material
uniforms on existing meshes and silhouettes, without rebuilding geometry. The
legend includes unknown and tied commercial uses. Landmark exteriors keep their
architectural materials. The overlay describes parcel/group source attributes,
not the location of uses inside a footprint or actual building occupancy.

Building inspection shows those source-group totals separately from assigned
simulation residents. It can open the recorded DataSF source in the user's
browser. The inspector scrolls so source details remain accessible in a desktop
window. Start with `python -m civic_center --use-overlay` to show the overlay.

`places-index.json` adds searchable destinations above the clock. Its 41 analysis
neighborhoods are reporting areas, not legal neighborhood boundaries; its 253
Rec/Park properties include facilities and plazas and do not cover every city
park operator. Results identify the source category and link to the DataSF
dataset. Choosing a destination fits its observed bounds to the current viewport,
field of view and camera pitch, with a margin around the area; landmark framing
also includes its architectural height. **Walk nearby street**
starts at the recorded source street node, not an asserted park entrance.
The checked `places-areas.json` adds an outline for the selected analysis area
(amber) or Rec/Park property (teal). This is a map annotation visible above city
geometry, with no land-cover fill. It follows terrain where samples exist and
leaves gaps where they do not. City overview, City Hall and landmark navigation
clear the previous area boundary.

`python -m civic_center --place Mission` selects an exact name before substring
matches. `--place 'Golden Gate Park'` frames the exact analysis area. Exact IDs
and kind filters such as `park:Golden Gate Park - Section 1` are also accepted;
ambiguous names require a more specific selection. Place views and walking
spawns sample the same terrain triangle surface as the city.
The four loaded landmark exteriors also appear in search, bringing the installed
city's destination count to 298. For example, `--place 'Transamerica Pyramid'`
frames the original exterior and `--place 'landmark:Coit Tower'` identifies the
landmark category explicitly. Their nearby street nodes come from the same
observed graph as other destinations.

`terrain.gd` retains a bilinear raw-data sampler and uses the NW-to-SE raster
triangle surface for rendered streets, building bases and walk cameras. Its
triangle interpolation and missing-value semantics match Python. Street paths
split at grid boundaries and diagonals so their centerlines stay on the same
ground planes as resident routes. Road strips sit 0.04 meters above that surface;
resident roots use the simulation's 0.08-meter clearance. Terrain meshes render
0.08 meters below it to reduce surface fighting.

Terrain triangles clip to the observed shoreline, including islands smaller than
a coarse raster cell. The clipped vertices retain their terrain triangle planes.
Chunks use coarse city-scale meshes and original grid spacing near the camera.
Road edges sample the neighboring ground while an explicit center edge preserves
the resident route surface; a building uses one base height at its footprint centroid. These are display approximations,
not a collision mesh or surveyed foundations. Water uses zero absolute elevation
minus the grid's recorded City Hall origin elevation.

The legacy `civic-center-walking-day-v1` scenario retains the authored block, hides
overlapping source geometry and uses a flat pilot terrain patch with a 150-meter
blend at its edges. Every other scenario hides the authored block/colliders,
clears that exclusion and uses raw observed terrain everywhere. The two coordinate
interpretations are never silently superimposed.

The initial overview frames the urban source bounds; source coverage also retains
outlying islands. The current elevation grid covers the main urban area and nearby
islands rather than the entire offshore jurisdiction. Resident routes remain
explicit generated walking proxies, separate from map completeness.

## Presentation boundary

- `snapshot_client.gd` polls local TCP, frames newline JSON across partial reads,
  limits buffers, handles acknowledgments, and rejects stale sessions/sequences.
  Its bounded decoder thread parses and expands snapshots before delivering
  completed states to the main thread in protocol order.
- `presenter.gd` interpolates distance along the same trip's route. It does not
  cut across corners or predict past the latest state. Activity, visibility and
  occupancy transitions apply as a complete snapshot. Same-segment updates
  interpolate their endpoint positions directly; segment crossings use cached
  cumulative lengths for the traversed span and binary search. A single corner
  never scans the rest of a kilometer-long trip. Completed trips and prior sessions are
  evicted, so repeating days do not retain old route arrays.
- `crowd.gd` maps persistent IDs to seven MultiMesh parts. The exact root used for
  drawing also drives picking and following. `crowd.gdshader` animates limbs only;
  it contains no route movement or independent simulation clock.
  If installed, the optional Rust draw helper packs these same roots, colors and
  gait flags into seven buffers. A missing helper uses the existing Godot upload
  path. `CIVIC_CROWD_BACKEND=individual` forces that fallback; `rust` and
  `gdscript` select the native or script buffer packer for comparisons. The helper
  does not own routes, scheduling, selection or the simulation clock.
- `world.gd` loads the local Blender GLB and creates selectable architecture.
- `cameras.gd` owns exploration controls and keeps follow cameras outside the
  fixture's building bounds where an alternative view is available.
  Indoor follow views retain the resident's arrival point and frame the building
  exterior from farther away; mouse-wheel zoom still adjusts that distance.
- `hud.gd` displays authoritative controls, resident details and occupancy.
- `diagnostics.gd` and `diagnostic_chart.gd` provide the bounded observation panel;
  `telemetry_client.gd` receives local launcher readings without polling log files.
- `display_settings.gd` manages local window and UI-scale preferences.
- `game_menu.gd` owns the vertical overlay and keyboard focus; `menu_flow.gd`
  coordinates authoritative pause, pending operations and acknowledged recovery exit.
- `main.gd` connects these modules and implements live/replay startup.

Local coordinates `(east, north, up)` convert once to Godot `(east, up, -north)`
through `coordinates.gd`. The GLB is already in standard glTF coordinates and is
not converted a second time. The current figures use procedural seven-part gait,
not skeletal character animation. At most 300 moving residents within 80 meters
receive articulated gait; all simulation residents retain their state.
Nonessential HUD layout and geographic visibility refresh at five updates per
second; snapshot transitions, camera movement and resident draw roots still
update immediately. Frustum counts are periodic HUD metrics, not draw culling.

## Startup and prepared geometry

`main.gd` shows a native loading screen before importing world assets. Live
launches use a short-lived local startup file from the Python launcher, so the
window is visible during scenario and worker preparation. The handoff contains
connection arguments and is removed when the owned application exits; it is not
part of the simulation protocol. Initial scene controls become available after
the first authoritative snapshot and requested scenery queues settle.

The launcher enables the shared `.local/civic/render-cache/` directory.
`scenery_cache.gd` stores checksummed, bounded binary Variant data with objects
disabled, including exact packed mesh arrays and analytical picking metadata.
Geography and terrain retain their current builders as the miss/failure path.
Godot still creates mesh instances and uploads arrays at runtime. Materials remain
shared and dynamic; raw terrain samples continue to drive cameras and routes.

`prepare_scenery.gd`, invoked by `scripts/prepare_sf_render.py`, uses the same
builders offline. The default prepares City Hall building/road tiles, nearby
detailed terrain, and all coarse terrain chunks. `--scope city` covers the entire
installed geography. Artifacts depend on source geometry, terrain, shoreline,
pilot settings, stable landmark replacement metadata, relevant builder source
and Godot versions. Existing tile residency limits remain in effect. A valid
prepared tile must preserve mesh arrays, picking, courtyard gaps, and shader
attributes exactly.

Direct Godot launches can pass `--render-cache ABSOLUTE_PATH`; caching is disabled
when no directory is supplied. `--no-render-cache` disables both cache reads and
writes for controlled comparisons.

`startup_profile()` records first paint, first snapshot, usable view, stage
durations, and frame intervals, including launcher preparation elapsed time.
`streaming_profile()` retains loading frame spikes separately from the existing
steady-state profile. These measurements describe startup/rendering work; they
do not establish live resident capacity.

Additional checks:

```powershell
godot --headless --path viewer --script res://scenery_cache_tests.gd
godot --headless --path viewer --script res://terrain_cache_tests.gd
godot --headless --path viewer --script res://startup_checks.gd -- --startup-file user://startup-checks.json
godot --headless --path viewer --script res://run_metrics_tests.gd -- --replay ../contracts/one-resident-replay.json --geography ""
```

The startup check deliberately injects a visible failure before testing successful
handoff. It prints one expected fixture failure followed by
`GODOT_STARTUP_CHECKS_OK`. For rendered evidence, omit `--headless` and pass
`--loading-screenshot ABSOLUTE_PATH --error-screenshot ABSOLUTE_PATH --ready-screenshot ABSOLUTE_PATH`.
Cache checks cover cold/hot parity, source/settings invalidation, and corrupt or
unwritable cache recovery.

## Checks and replay

```powershell
python -m civic_center --population 1 --headless --smoke-test
python -m civic_center --population 1 --mode map --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --no-geography --mode map --headless --smoke-test
python -m civic_center --replay contracts/one-resident-replay.json --smoke-test --screenshot .cache/civic-replay.png
```

With a Godot executable available as `godot`:

```powershell
godot --headless --path viewer --script res://presentation_tests.gd
godot --headless --path viewer --script res://workspace_ui_tests.gd
godot --headless --path viewer --script res://workspace_input_tests.gd -- --replay ../contracts/one-resident-replay.json --geography ""
godot --headless --path viewer --script res://telemetry_client_tests.gd
godot --headless --path viewer --script res://map_2d_tests.gd
godot --headless --path viewer --script res://geography_tests.gd
godot --headless --path viewer --script res://terrain_tests.gd
godot --headless --path viewer --script res://shoreline_tests.gd
godot --headless --path viewer --script res://landmark_tests.gd
godot --headless --path viewer --script res://geography_visuals_tests.gd
godot --headless --path viewer --script res://geography_use_tests.gd
godot --headless --path viewer --script res://places_tests.gd
```

Workspace UI checks cover narrow through ultrawide layouts, focus guards,
invalid population inputs, stale hardware and bounded histories. The telemetry
fixture checks authenticated hello, partial frames, reconnects, duplicate
suppression, heartbeat freshness and oversized-buffer rejection.
The input fixture injects real mouse and keyboard events: ordinary controls
respond, while an active workspace probe ignores interactive view changes and
held camera keys. Programmatic actions, display controls and OS close remain
available to the probe. This isolation applies only to automated workspace trials.

The standalone presentation checks cover a route corner, atomic arrival,
session reset, stale sequence rejection and stable slots after reordered records.
The 2D module checks cover projection, markers, footprint picking and membership
replacement. Launching smoke checks with `--mode map` exercises the application's
map controls, exact domain positions, indoor/outdoor transitions, retained
selection and framing, and restored 3D views. It also verifies that 3D scenery,
camera and crowd updates stop while the map is active. Live map checks pause,
advance to the next activity, reset and reconnect; recorded checks visit the
supplied replay states. Installed named destinations additionally exercise map
navigation and **Walk nearby street**.
The 3D smoke checks additionally exercise loaded architecture, the 3D camera modes,
resident/building picking, persistent indoor selection, paused exact stepping and
acknowledged speed changes. Live checks also save, advance and reload an isolated
`viewer-smoke-<process-id>` slot, verifying tick, pause, speed, selection, position
and camera restoration. Actual GPU MultiMesh transform checks run in rendered
mode because Godot's headless dummy renderer does not retain those GPU buffers.
Geography checks cover merged tiles, distance levels, courtyard omission, picking,
pilot exclusions and path bounds. Terrain checks cover bilinear interpolation,
triangle planes, line splits, unknown data, grid orientation, legacy-only
flattening and sampled Python parity.
Screenshot automation waits for scenery queues to settle and reports frame
interval p50/p95/p99 from monotonic wall times between subsequent steady frames;
the sample spans at least ten seconds and 120 frames, excluding loading spikes.
JSON/expansion timings describe completed background work; transport, delivery,
presentation, crowd, view and HUD timings describe main-thread work. A post-smoke profile measures the paused
state; it is not evidence of live population throughput.

Replay format and transport are specified in
[`contracts/CIVIC_PROTOCOL.md`](../contracts/CIVIC_PROTOCOL.md). A direct Godot
launch additionally accepts `--replay-index N` for a specific recorded snapshot;
give absolute paths for direct `--replay` and `--screenshot` arguments. Replay
playback steps through recorded snapshots, rather than recreating unsaved
simulation ticks. Population changes and saved sessions require a live worker.

## Game menu validation

Focused checks use the existing Godot executable:

```powershell
godot --headless --path viewer --script res://game_menu_tests.gd -- --replay ../contracts/one-resident-replay.json --geography ""
godot --headless --path viewer --script res://menu_flow_tests.gd
godot --headless --path viewer --script res://snapshot_close_tests.gd
```

Exercise the real launcher and rendered viewer with isolated temporary saves:

```powershell
venv/Scripts/python.exe scripts/benchmark_game_menu.py --mode overhead --case save_exit
venv/Scripts/python.exe scripts/benchmark_game_menu.py --mode map --case window_close
```

Other cases are `save_error` and `population_exit`. Use `--load PATH` for an
existing busy city, `--package-root PATH` for a portable build, or `--headless`
for behavior-only validation. The probe owns and closes its temporary application;
its saves and reports stay under an ignored `.cache/game-menu/` directory.
It verifies checkpoint reload, unchanged quick save, acknowledged worker shutdown,
final report and stopped owned processes. Single-run timings describe these
scripted operations, not a before/after optimization benchmark. See the
[recorded aggregate evidence](../docs/benchmarks/2026-09-06-game-menu.json).
