# City Hall overnight implementation

Started September 5, 2026 at 23:42 Pacific daylight time (06:42 UTC September 6).
User authorized continuous improvements through the morning. Working deadline:
September 6 at 08:00 San Francisco local time (15:00 UTC). The user was asked
whether literal fixed PST, which would mean 09:00 local, was intended instead.
Use any subsequent user clarification as the authoritative deadline.

Godot is selected. Python first with gradual Rust adoption remains the accepted
planning default. The plan is in [GODOT_NEXT_STEPS.md](GODOT_NEXT_STEPS.md).

## Current batch

- Implement persistent resident/trip/routing domain with exact tick semantics.
- Build a loopback worker with versioned snapshots and acknowledged controls.
- Promote a dedicated Godot viewer using the same displayed state for rendering,
  picking, follow and inspector; retain the Blender asset and camera controls.
- Add a deterministic scenario, replay, launcher, behavioral/integration tests.

## Next useful improvements after integration

1. Capture and inspect a full resident day, occupancy and selection behavior.
2. Improve the inspection interface and physical placement of streets/entrances.
3. Import a reproducible small real City Hall geographic subset with provenance.
4. Add save/resume, scale profiling, and a bounded Rust integration experiment.
5. Package and validate a Windows launch, then refine visuals against screenshots.

This file records implemented evidence as work completes. It is not a claim that
the listed tasks already work, nor a performance benchmark.

## First integration evidence, September 6

- Persistent Python resident and route implementation: 40 model/router/scenario
  tests passed. One-person and 200/1,000/5,000-person days conserve identities and
  occupancy, and results agree across different tick-advance batches.
- Local worker: 35 protocol/network tests passed, including real fragmented and
  partial writes, authentication, controls, reset/reconnect and bounded queues.
- Godot viewer: live one-person and 200-person headless smoke checks passed;
  seven-state replay also passed in rendered mode. Drawing, picking and following
  use the same resident transforms; activity/occupancy transitions are atomic.
- Root launcher `python -m civic_center --population 1 --headless --smoke-test`
  passed, starting and closing both processes.
- Full Python suite at this checkpoint: 210 passed, 15 skipped. One pre-existing
  warning remains in `tests/test_rules_execution.py` about returning a boolean.
- Walking geometry now accounts for the raised central block, plaza/entrance
  ramps and paths around lawns/fountain. All of this remains stylized geometry.
- A local 5,000-person complete snapshot plus JSON encoding took approximately
  182 ms in an initial diagnostic. This is an identified scaling cost, not an
  engine ranking; 200 remains the initial live pilot.

Save/resume, broader rendered interaction checks and the next visual/data work
are underway. Launch instructions are in [civic_center/README.md](../civic_center/README.md).

## Scope expansion and second integration, approximately 00:20 local

The user explicitly requested expansion to the actual size of San Francisco.
Work now includes official citywide street/building/shoreline ingestion, nearby
geometry tiles in Godot and a synthetic commuting cohort on authentic geography.
City Hall stays the detailed starting area. Geographic extent, realistic behavior
and population calibration are separate milestones.

- Checkpoint implementation: 38 tests passed, including mid-trip continuation,
  paused state, corruption handling and atomic failure preserving an older save.
- Worker save/load integration: 73 worker tests passed. F5/F9 operate local quick
  slots; rendered smoke checks use isolated slots and preserve the user's save.
- Rendered 200-resident save/advance/load checks passed with camera and stable
  identity preserved. Screenshot: `.cache/civic-200-follow.png`.
- Windows forced process cleanup now uses scoped native process handles after
  `taskkill` proved unavailable in the sandbox. All three launcher tests passed,
  including verifying that a nested interpreter's listening socket closes.
- Snapshot construction optimization preserved identical state and JSON bytes.
  Same-process median snapshot time improved from 184.3 to 40.9 ms at 5,000
  residents; snapshot plus JSON improved from 263.1 to 147.7 ms. This still
  exceeds the proposed 100 ms publication interval and motivates spatially
  bounded visual updates. Report: `.cache/civic-core-benchmark.json`.

## Geographic preparation, approximately 00:40 local

- Official source downloads completed: 177,023 footprint records, 16,373 active
  street records and shoreline/island polygons. Initial normalization produced
  177,140 footprint polygon parts, 15,911 physical street parts and 576 spatial
  tiles. Source observation dates and inferred widths remain explicit.
- The first topology check found reused intersection IDs joining distant
  endpoints and a resulting zero-length edge. City scenario validation stopped
  before accepting that graph; the import is being corrected and rebuilt.
- USGS bare-earth F32 raster downloaded and resampled into the same WGS84 local
  east/north coordinate frame as streets/buildings. The 1,024-by-1,024 grid is
  about 6 MB, with approximately 18–19 m sample spacing. City Hall origin is
  18.458 m in the source vertical frame. Main terrain coverage includes mainland
  and Bay islands; the Farallon Islands remain outside this first terrain grid.
- Latest full Python checkpoint: 299 passed, 15 skipped, one existing boolean
  return warning. Subsequent worker/city-population/lifecycle/terrain checks:
  84 passed. Geographic/viewer integration checks are still in progress.

## Citywide integration, approximately 01:25 local

- Corrected and validated the street topology: 27,452 source nodes and 33,649
  edges, with reused source intersection IDs clustered by coordinates. No
  zero-length walking edges remain. Official geographic extent includes the
  mainland and islands; the initial urban camera intentionally excludes the
  distant Farallon Islands.
- Final terrain-aware 200/1,000 resident scenarios keep 34,949 connected graph
  nodes and 41,146 edges. Their route polylines contain 295,787 terrain samples.
  More than 305,000 active segment midpoint checks agree with the rendered
  terrain triangles plus foot clearance within numerical precision. All
  800/4,000 daily events complete with conserved identities and occupancy.
- Compact live updates retain exact state while separating immutable scene and
  reliable trip geometry. At 20 simulated minutes, measured 1,000-person
  publication size falls from 7.36 MB to 604 KB. Pre-densification timing improved
  from 721 ms to 32 ms for snapshot construction plus JSON encoding; current
  route geometry is denser, so final transport profiling remains a separate check.
- A production-limit 1,000-person checkpoint is 56.2 MB and restores exactly.
  After one-time immutable preparation, main-thread capture takes 23.8 ms median;
  background writing takes 31.5 seconds and loading 21.9 seconds. These timings
  motivated pending/completion command responses and bounded background jobs.
- City Hall now has an original ten-mesh Blender exterior aligned to its observed
  footprint, with architectural-height provenance. The compact HUD leaves more
  of the city visible. Selecting an unassigned building does not imply zero
  real-world occupancy.
- Distant building boxes cover 177,140 parts; nearby detailed roofs preserve all
  3,282 source courtyards. Shoreline clipping preserves islands and avoids the
  earlier raster-shaped coast. Rendered city overview passed; its 121-frame
  profile measured 13.2 ms median, 44.4 ms p95 and 46.6 ms p99. Periodic stalls
  remain, so this is not a sustained 60 FPS claim.
- The first portable Windows pilot bundles official Python 3.13.15 and the
  tested Godot executable. It starts its own simulation and passes the one-person
  headless smoke check without using the checkout's Python environment. A full
  city package and repeating commuter days are the next validation steps.

Reports and screenshots remain in `.cache/`; shipped-data provenance is described
in [SF_GEOGRAPHY.md](SF_GEOGRAPHY.md). No commit or public release has been made.

## Repeating days and independent runtime, approximately 01:45 local

- City generator v3 enables repeating daily schedules. Legacy one-day fixtures
  retain their exact output. Midnight crossings, later-day checkpoint resume and
  batched advancement pass; 164 focused tests cover this core milestone.
  Actual 1,000-person million-day advancement took 86 ms with bounded queues,
  2,000 cached routes and the 256-event journal. This is deterministic repeated
  scheduling, not evolving household demographics.
- Full city portable folder: 1,275 shipped files, 626 MB before compression.
  A live 200-resident smoke run using only its Python 3.13.15 runtime and bundled
  Godot returned zero in 92.42 seconds, including save/load and city assets.
  Report: `.cache/portable-city-01-verified.log`. The final build will be refreshed
  after ongoing changes. Cached source paths now rebase when a portable folder
  moves; source files and saved checkpoints are not silently rewritten.
- Busy 1,000-person rendering exposed repeated route-distance scans. Caching and
  direct segment interpolation reduced the 877-walker presentation microbenchmark
  from 394 ms to 15.3 ms median. The full running scene still measured 36.5 ms
  median and 173 ms p95, with client decode/expansion causing major stalls. These
  results do not establish smooth 1,000-person rendering.
- Large saves keep the socket connected, but the first threaded implementation
  still showed 4-5 second gaps due to shared-process work. A bounded child-process
  implementation is being measured to reduce those stalls.
- Current official parcel land-use attributes are imported and join uniquely to
  167,930 building parts. Group totals are counted once and unknown joins remain
  explicit. Ten importer/join tests pass; eligible home/work cohort generation
  is being integrated. This improves placement without claiming observed people,
  jobs or calibrated population.

## Source-based uses, navigation and native routing, approximately 02:35 local

- Generator v4 uses observed parcel-group eligibility and area-distributed
  allocation weights. The 1,000-person scenario contains 1,000 distinct commute
  pairs, 35,162 graph nodes and 41,359 edges. Ordinary housing units and special
  units/beds remain separate. Actual resident identities and jobs are synthetic.
- Optional Rust routing matches all 2,000 outbound/return routes exactly,
  including 560,124 dense geometry points. Cold routing totals were 14.56 seconds
  in Python and 1.38 in Rust; actual model construction fell from 20.83 to 6.45
  seconds. Checkpoints, scenario hashes and process transfer retain equivalence.
  The native dependency is optional and the Python implementation remains usable.
- Save/load/population work now uses bounded child processes. In the measured
  1,000-person save, control latency fell from 312 ms median to 31 ms, with a
  maximum 0.61-second snapshot gap. Loading remains more expensive, but control
  latency fell to 46 ms median and no worker subtree is left on cancellation.
- Godot parses JSON and expands compact scenes in a dedicated decoder thread.
  The matched short busy-1,000 sample improved frame p95 from 141 to 65 ms; longer
  ten-second samples remain around 70-74 ms p95 and 31 ms median. This is useful
  progress, not smooth 1,000-person rendering. Presenter preparation remains the
  largest measured main-thread snapshot stall.
- The observed-use overlay is rendered and source-group inspection is verified.
  The latest 200-person live smoke passes threaded transport, pause/step/speed,
  asynchronous save/load, all three cameras, picking and source-use toggling.
- Named navigation data now covers all 41 analysis areas and 253 in-city
  Recreation and Parks properties. Interior camera targets and nearby source
  street nodes are checked; source coverage limitations remain explicit.
- A bounded Rust Godot helper builds and loads on the installed engine. Its
  isolated MultiMesh upload benchmark saves about 0.8 ms median. Pose/LOD loops
  account for much more of the current crowd cost; broader integration is being
  evaluated on that evidence. Compact versioned checkpoints and searchable
  destination UI are also in progress before the next portable build.


## City scale and visual inspection, approximately 03:20 local

- Current generated city cohorts use distinct home/work pairs and preserve the
  original 1,000-person prefix. The actual 5,000-person cohort uses 3,347 assigned
  buildings, completes four repeating days with 80,000 events, and conserves
  all identities and occupancy. These are generated commuters, not a calibrated
  representation of San Francisco's resident population.
- Version 2 checkpoints store the immutable scenario once in bounded compressed
  chunks. The 1,000-person save decreased from 61.30 MB to 13.69 MB and resumes
  exactly; the actual distinct 5,000-person save is 17.24 MB. Version 1 saves
  remain readable. Corruption, decompression and future-route identity checks pass.
- Live city presets remain capped at 1,000 pending a transport/renderer scale
  check. At the busiest 5,000-person time, 4,488 walkers need 79.92 MB in the
  existing route format, exceeding its 32 MiB geometry cache. An independent
  exact shared-coordinate prototype reduces peak geometry to 22.84 MB; retaining
  its complete daily coordinate pool is 22.94 MB. Production protocol integration,
  staged bootstrap, reconnect and bounded long-running identity checks are underway.
- Optional row snapshots reduce the 1,000-person wire payload by 38.9%. Python
  total preparation CPU is essentially unchanged; measured Godot decode gains
  varied from 3 to 19%. Rows therefore remain opt-in rather than becoming the
  default on a bandwidth result alone. Actual TCP-to-Godot full-state parity and
  106 worker checks passed at this checkpoint.
- City Hall, Transamerica Pyramid, Coit Tower and Sutro Tower now have original
  Blender exteriors. The viewer replaces their corresponding coarse footprint
  parts, preserves source inspection and offers all four in destination search.
  Search also covers 41 analysis areas and 253 Rec/Park properties. Camera fitting
  accounts for viewport aspect, field of view, terrain and landmark height.
- A representative September daylight cycle follows the authoritative clock.
  Seven recorded Day 2 states cover dawn, both commutes, midday, dusk and night.
  Actual rendered smoke passed, including pause labels, replay seeking and fixed
  light restoration. This is illustrative sky/lighting, not live weather.
- Close-building facade patterns passed rendered overlay parity and distance
  fade checks. On the same paused 200-person scene with no outdoor residents,
  750 frames in about ten seconds yielded p95 13.506 ms off and 13.462 ms on.
  The capture is limited by 75 Hz vsync, so it demonstrates no measured frame
  penalty in that scene rather than zero GPU cost or a busy-crowd FPS result.
- Source area outlines are checksum-verified, preserve holes and separate parts,
  follow terrain and skip missing samples. Headless source/lifecycle tests pass;
  the integrated Golden Gate Park render is being checked.

Evidence is in `.cache/city-distinct-scale.json`,
`.cache/city-distinct-transport-peaks.json`, `.cache/shared-geometry-profile.json`,
`.cache/checkpoint-v2-profile.json`, `.cache/city-rows-network-1000/`,
`.cache/sf-daylight-*.png` and `.cache/sf-facades-{on,off}-paused.*`.
The next portable build will take a fresh snapshot after current integration.
