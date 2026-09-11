# SF-city Patch Notes

## 2026-09-06 - Escape menu and confirmed recovery exit

Press **Escape** to open the vertical game menu. It pauses the city, blocks
camera input, and puts Return, Save day, Display, Controls, Performance, and
**Save & Exit** in one place. Return restores the previous playback state.

Previously, Escape cancelled dragging and closing the window could abandon an
unfinished save. A ready launcher-owned game now waits for an acknowledged
**exit-recovery** checkpoint before closing, including when using the window's
close button. This preserves the quick-save slot. Failed or unconfirmed saves
keep the window open with Retry, Return, and an explicit unsaved-exit choice.
Slow saves continue with visible status.

Resume the recovery with:

```powershell
python -m civic_center --load .local/civic/saves/exit-recovery.json
```

Recovery opens paused at the saved tick, with its population and speed. The
launcher finishes owned-process cleanup, output capture, hardware monitoring,
telemetry, and the final JSON report after Godot exits. Wait for the launcher to
return before closing its terminal. The report now separates save intent/outcome
from actual cleanup results, including forced or incomplete cleanup.

### Validation and observed save cost

The application suite passed **839 tests, with 1 skipped**. Eight relevant Godot
checks passed, covering menu input/layout, pause/save coordination, socket closure,
existing workspace behavior, metrics and telemetry. Layout checks exercised
960 x 540 through 5120 x 1440 at 100%, 125% and 150% scale; these do not establish
physical ultrawide or mixed-DPI display coverage.

**Eight rendered trials passed:** Save & Exit and ordinary window close in both
3D and 2D, saving after a live population change, a deliberately failed save with
explicit unsaved exit, a 1,000-resident city recovery, and a portable pilot.
Successful saves reloaded at the acknowledged tick and retained their roster;
quick saves stayed unchanged. Final logs were readable, output was drained, and
owned processes stopped. The fresh pilot-only portable package verified
**275 files / 210,453,089 bytes** and ran with its bundled runtimes and individual
crowd fallback.

Selected single-run observations from the
[aggregate validation report](benchmarks/2026-09-06-game-menu.json):

| Scenario | Residents / outdoors at menu | Save request through acknowledgement | Whole automated application run |
| --- | --- | --- | --- |
| City Hall pilot, 3D overhead | 200 / 47 | 0.342 s | 4.828 s |
| City Hall pilot, 2D map | 200 / 47 | 0.472 s | 5.109 s |
| Installed city, 2D map | 1,000 / 782 | 24.839 s | 64.015 s |

Each row is **one observation**, on Windows 11, Ryzen 5 2600X, about 32 GiB RAM,
and GTX 1070 Ti 8 GiB (driver 582.66), with Python 3.12.10 and Godot 4.7.2
Compatibility. The 3D row used the Rust crowd helper; both map rows used the
2D canvas. These source trials used a 1280 x 720 window, 100% UI scale, VSync,
fixed lighting and existing local caches; no cold
reset was performed. Save timing includes validation, disk work and transport.
Whole-run timing includes startup, scripted interaction, a screenshot, closure,
and 250 ms process polling; it is not click-to-exit latency. Recovery reload
validation ran afterward. Pause had already completed before exit was requested.

The gain is recoverable progress and explicit shutdown outcomes. There is no
measured before/after speedup, absolute time saving, or percentage reduction for
this feature. Scenes and workloads differ, so the rows are not a 2D-versus-3D
performance comparison. Large saves can take tens of seconds. The report retains
separate menu, pause, close-dispatch and launcher-cleanup observations, source
fingerprints, and measurement limits; raw logs remain ignored locally.

Recovery does not record camera poses or individual trajectories. The
[overlapping-newcomer fix and coordinate recorder](CITIZEN_COORDINATE_PLAN.md)
remain planned. Direct viewer and replay exits do not claim a new live recovery
save; unexpected OS termination or filesystem failure can still interrupt
persistence. See the [application guide](../civic_center/README.md#escape-menu-and-safe-exit)
for controls and recovery behavior.

## 2026-09-06 - Live population experiments and a wider workspace

### What users gain

Changing the population no longer has to restart the day. Open **Performance**
with **F3**, enter a target, and choose **Apply live**. Existing citizens keep
their identities, current activities and trips; additions join the current
schedule. The old population presets remain explicit new-day restarts.

| Feature | Product impact |
| --- | --- |
| Live population target and adjustment buttons | Increase or reduce a synthetic workload while retaining the experiment's current day. |
| Frame charts, hardware readings, filtered logs and comparison points | Inspect performance beside the city and retain observations in the run's JSON report. |
| Resizable diagnostics, fullscreen and UI scale | Keep controls usable across wide and short windows; use F11 and 100%, 125% or 150% scale. |
| Versioned saves for changed rosters | Resume a changed population with its current state and identity allocator intact; older saves remain readable. |
| Bounded, staged city updates | Send larger valid population updates without overflowing the connection's outgoing queue. |

Population preparation runs in an isolated process. The viewer retains the
previous complete scene until the new roster arrives. A surviving selection and
camera remain in place; removing the followed citizen releases the camera at its
current pose. Large changes still have preparation and presentation costs.

The console provides Charts, Details and Logs tabs, pause/speed/activity controls,
2D/3D switching, save/load, **Record point**, and **Open run log**. Hardware keeps
its own timestamps, unsupported readings and stale status. Clearing the console
clears its visible history. Per-run records retain bounded experiment phases and
distinguish intervals that cross a workload change.

### How to use it

```powershell
python -m civic_center --performance --window-mode maximized
python -m civic_center --mode map --performance
```

Enter a target between **1 and 5,000**, then apply. This is an experimental input
range subject to scene, route-data and transport budgets, not a supported smooth
population ceiling. Additions reuse the loaded cohort's home/work assignments
and routes; they are synthetic workload changes, not calibrated population growth.
The number outdoors matters as well as the total.

**Known issue discovered after delivery:** live additions can copy an existing
citizen's entire walking trajectory and appear stacked together. A focused pilot
reproduction grew 200 -> 2,000 citizens and produced 458 walkers at only 47 exact
positions, with up to 18 coincident walkers. Indoor building aggregation was
excluded. [Individual coordinate recording and a deterministic newcomer fix](CITIZEN_COORDINATE_PLAN.md)
are planned; the passing checks below did not test outdoor spatial separation.

### Validation and observed limits

The application suite passed **802 tests, with 1 skipped**. Relevant Godot checks
passed for layout, input exclusion, telemetry, transport, frame measurements,
map and presentation behavior. Both final rendered trials passed with unchanged
source fingerprints and **zero application or hardware errors**. They checked
paused/running changes, survivor state and occupancy, camera behavior, and
save/load followed by another resize.

A fresh **pilot-only portable build** passed a rendered launch using its own
Python 3.13.15 and Godot runtimes, including the individual crowd fallback.
Its manifest verified **262 files / 210,367,131 bytes**. This validates packaging
and behavior; it is not a full-city distribution or a startup-speed comparison.

Window requests from **1280 x 720 through 5120 x 1440**, 100%/125%/150% UI scale,
and windowed/maximized/fullscreen transitions passed. Requested and actual sizes
are retained separately. Dedicated physical 3440/5120-pixel display and mixed-DPI
multi-monitor testing remain outstanding.

#### Observed cost of opening the console

These are exploratory observations on an **AMD Ryzen 5 2600X, 32 GB-class RAM,
NVIDIA GTX 1070 Ti with 8 GiB VRAM, driver 582.66, Windows 11**, using Python
3.12.10 and **Godot 4.7.2 Compatibility**. The pilot used the Rust crowd backend;
the city used the 2D canvas backend with 3D rendering disabled.

Each count has **three alternating hidden/shown pairs** at a fixed paused state,
1440 x 900, UI scale 100%, fixed lighting, VSync enabled, and hardware sampling
enabled at one-second intervals in both conditions. Each window requested three
seconds in the pilot and five in the city. The camera was held fixed; the city
map's center, scale and drawing rectangle were also held fixed. Existing local
caches were retained, with no cold-cache reset; OS and driver cache state were
uncontrolled. Loading, population transitions and settling were excluded.

The ranges below contain the three measured callback-interval p95 values per
condition. The last column is the median of the three paired shown-minus-hidden
changes (and their corresponding percentages). It is not a pooled percentile,
GPU execution time, or the difference between the range endpoints.

| Scene: total / outdoors | Console hidden p95 range (ms) | Console shown p95 range (ms) | Median paired change |
| --- | --- | --- | --- |
| Pilot 3D: 200 / 47 | 13.535-13.581 | 13.525-13.585 | +0.004 ms / +0.03% |
| Pilot 3D: 1,000 / 219 | 25.022-26.896 | 26.068-26.970 | +0.074 ms / +0.28% |
| Pilot 3D: 2,000 / 447 | 27.384-29.742 | 32.045-52.683 | +7.608 ms / +25.58% |
| Pilot 3D: 5,000 / 1,097 | 53.138-63.521 | 55.759-60.993 | -3.314 ms / -5.22% |
| City 2D: 1,000 / 885 | 52.237-53.516 | 51.171-73.731 | +9.754 ms / +18.67% |
| City 2D: 2,000 / 1,755 | 74.188-84.919 | 81.195-89.029 | +7.007 ms / +9.44% |

Opening the console had a visible measured cost in some conditions. Short
windows, background machine activity and VSync make small differences uncertain;
the negative 5,000-resident result does **not** establish a speedup. Hardware
monitoring remained enabled, so this does not measure the total cost of monitoring.
The benefit delivered here is keeping an experiment's state while changing its
workload and inspecting evidence. No debugging-time saving or runtime optimization
percentage has been established.

#### Population changes and current limits

Single paused pilot transitions took **0.892 seconds** for 200 -> 1,000,
**2.080 seconds** for 1,000 -> 2,000, and **6.766 seconds** for 2,000 -> 5,000,
measured from request to presentation of the new count.

The busy detailed-city save took **44.227 seconds** for 1,000 -> 2,000 at the
same paused tick. Its recorded preparation was **29.875 seconds**, validated
commit work **3.623 seconds**, and commit-to-viewer handoff **10.297 seconds**
(with 21.407 ms clock uncertainty). These component measurements have separate
boundaries; they should not be summed as an exact request-duration breakdown.

A subsequent 5,000-resident city request exceeded the existing **32 MiB route-data
cache budget** and was rejected after **44.996 seconds**. The roster, tick,
session, selection and camera stayed unchanged, and the connection accepted the
next command. It produced **one command-rejection warning**, not a fatal run error.
A separate outgoing queue remains bounded while valid larger updates are staged.

Successful pilot counts do not establish detailed-city capacity. Sustained
unpaused throughput, long-duration memory growth and monitoring-on/off comparisons
remain unmeasured. The [aggregate evidence](benchmarks/2026-09-06-live-workspace.json)
retains exact sample counts, individual pairs, source/runtime/checkpoint hashes,
transition timings, hardware summaries and validation boundaries. Only hardware
intervals wholly inside a comparison window after clock-uncertainty margins enter
its summaries; mixed intervals are excluded. Raw logs and screenshots remain local.

The original OpenGlassBox-Python repository and retained upstream version are
unchanged. The application guide documents [the workspace controls](../civic_center/README.md#desktop-workspace-and-live-experiments).

## 2026-09-06 - Local hardware reporting for each run

### What users gain

Each run now records the machine it ran on and how resource usage changed during
loading and play. This helps investigate whether a slow moment coincides with
simulation CPU load, memory pressure, disk activity, or GPU load.

Previously, logs retained application timings and the latest viewer summary.
They now add **one hardware sample per second**, the most recent **360 samples**
(about six minutes by default), and bounded numeric summaries that retain
earlier peaks. Sample timestamps align with the latest known viewer context;
its separate timestamp makes older frame or camera information identifiable.

| Added evidence | Debugging use |
| --- | --- |
| CPU model/cores, RAM, OS, GPU/driver/VRAM | Compare runs with their machine specifications visible. |
| System and per-core CPU, RAM/swap, disk activity | Recognize resource pressure during loading or play. |
| Launcher, viewer, worker and preparation process usage | Locate CPU or memory growth within the application. |
| Available GPU utilization, VRAM, temperature, power, clocks and fan readings | Investigate graphics pressure and changing GPU conditions. |
| Recent history, lifetime summaries and explicit unavailable readings | Preserve earlier spikes without treating missing sensors as idle hardware. |

### How to use it

Normal launches enable reporting automatically and save it under the existing
ignored `.local/civic/logs/` directory. The JSON's `hardware` section contains
inventory, samples, summaries, capability status and sensor errors.
This checkout's monitoring libraries are installed. For a new source environment:

```powershell
venv/Scripts/python.exe -m pip install -r civic_center/requirements-monitoring.txt
python -m civic_center
```

Use `--hardware-interval 2` to sample every two seconds, or
`--no-hardware-monitor` to keep application logging without sensor sampling.
New portable Windows builds include pinned, checksum-verified monitoring wheels.
The existing retained OpenGlassBox engine and upstream version are unchanged.

### Validation and measured observations

A rendered **20-resident stylized City Hall pilot** completed successfully on an
AMD Ryzen 5 2600X with 32 GB-class RAM and an NVIDIA GTX 1070 Ti (8 GiB VRAM,
driver 582.66), using Godot 4.7.2 Compatibility rendering. It saved **7 samples**
and **98 numeric summaries**, with **zero hardware errors**. The JSON was
**126,662 bytes**. Two samples carried viewer context; the earlier samples
covered startup before the first viewer metrics report.

In this single run, hardware inventory collection took **265.400 ms** on the
background thread. The first sensor sample took **928.190 ms**; the following
six samples had a **39.024 ms median** and **164.658 ms maximum**. These are
sensor-call and process-registration durations, excluding JSON serialization,
disk writes and lock waits. They do not measure total monitoring overhead,
FPS impact, or time saved debugging. No speedup is claimed.

Validation included 705 passing application tests (one skip), followed by
30 passing run-log checks after final summary corrections; counts overlap.
Headless and rendered application checks passed. A separate isolated portable
Python 3.13.15 probe loaded the pinned libraries from its own runtime, read live
CPU/RAM/disk/process/GPU metrics, and reused cached wheels without network access.

See the [machine-readable evidence](benchmarks/2026-09-06-hardware-reporting.json)
for the exact command, hardware, measurements and raw-log hash. The portable
check validates the runtime and collectors; a full-city distribution was not rebuilt.

### Limits

NVIDIA readings cover the whole adapter, including other applications.
AMD/Intel GPU sensors are not implemented in this backend. CPU temperature and
motherboard fan readings were explicitly unsupported by the Windows provider;
GPU temperature, power and fan readings were available. No battery was reported.

Sensor failures remain nonfatal. The monitor waits at most two seconds for sensor
calls at shutdown, while ordinary log writes still depend on the filesystem.
Hardware samples flush about every five seconds and on other log events or
normal shutdown; an abrupt termination may lose the last buffered samples.

Also fixed a startup failure discovered during verification: random connection
tokens beginning with a dash are now passed unambiguously to the worker's argument
parser. A regression check covers successful startup and token redaction.

## 2026-09-06 - Prepared scenery and startup improvements

### What users gain

The recorded 200-resident City Hall replay reached its usable view in **14.1
seconds instead of 46.6 seconds** after the preprocessing and startup changes.
That is **32.5 seconds saved, or 69.8% less waiting**, in the observed comparison.

| Measurement | Before: generated during startup | After: prepared scenery | Observed savings |
| --- | ---: | ---: | ---: |
| Time until the City Hall view is usable | 46.589 s | 14.088 s | 32.501 s (69.8%) |

The loading window now opens before resident preparation and shows the current
stage. Users can see progress, close the window to cancel startup, and read a
startup error in the window if loading fails.

### What changed

- Building, road, and terrain geometry can be prepared before launching the city.
- Normal launches also save newly generated geometry and reuse valid entries on
  later launches and visits.
- Changed inputs or geometry builders select new cache entries; damaged entries
  regenerate automatically.
- The recorded prepared launch reused **20 geography tiles and 263 terrain
  chunks**, with **zero cache misses, writes, or errors**.

Godot still loads assets, creates mesh instances, and uploads geometry at runtime.
Residents and their simulation remain live. This preparation stage does not
prebuild tree geometry, landmark imports, 2D drawing buffers, or route bundles.

### Preparation cost and use

The recorded full-city preparation took **267.7 seconds (about 4 minutes
28 seconds)**, processing 576 geography tiles and 512 terrain chunks. One terrain
chunk was already cached. This is preparation work done ahead of a launch; it is
not included in the 14.1-second startup result. Valid prepared entries can be
reused, while changed inputs require rebuilding the affected entries.

From the SF-city repository root:

```powershell
# Prepare the starting City Hall area, then launch.
venv\Scripts\python.exe scripts/prepare_sf_render.py
python -m civic_center
```

Add `--scope city` to the preparation command to cover the whole installed city.
Prepared geometry occupies disk space under `.local/civic/render-cache/`.
See [loading and prepared scenery](../civic_center/README.md#loading-and-prepared-scenery)
for cache controls, scope, and fallback behavior.

### Measurement context

These are **one historical run per condition**, recorded on September 6, 2026
before the repository move. Both used the same paused City Hall replay with 200
residents, an overhead view at 1440 x 900, Godot 4.7.2 Compatibility/OpenGL, and
an NVIDIA GTX 1070 Ti.

The timer starts in the Godot viewer's `_ready()` and ends when the loading
overlay finishes and the starting view becomes usable. It excludes engine/process
launch overhead and offline preparation. The comparison includes accompanying
startup changes, so it does **not isolate the cache-only improvement**. Source
revisions and complete launch commands were not captured.

These observations are not repeated-trial averages, a guaranteed launch time, or
evidence of higher FPS or resident capacity. Live launches and other machines
need their own measurements. Exact timings, scene conditions, cache counters,
preparation totals, and raw-file provenance hashes are preserved in the
[benchmark summary](benchmarks/2026-09-06-prepared-scenery.json).

For future comparisons, record matching configuration and source revisions, vary
`--no-render-cache` versus a populated cache, and collect multiple runs of each.
Use `metrics.startup.usable_ms` in [per-run JSON logs](../civic_center/README.md#json-run-logs)
with the same viewer timing boundary; record preparation time separately.
