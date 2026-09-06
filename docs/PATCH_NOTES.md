# SF-city Patch Notes

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
