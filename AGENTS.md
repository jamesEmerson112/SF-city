# SF-city Repository Guidelines

## Repository Scope

This is the active repository for the San Francisco desktop simulation. The sibling
`OpenGlassBox-Python` repository preserves the original Python port. Make city
application changes here; preserve the upstream license and attribution in the
retained engine, demo, and comparison code.

Read [the application guide](civic_center/README.md) for current behavior and
[the project plan](docs/SAN_FRANCISCO_PLAN.md) for product direction. The Godot
application uses its own Python `CivicSimulation`; it does not run on the
retained `openglassbox/` resource simulation engine.

## Product Communication and Patch Notes

The user is a product engineer. Lead with the problem, the observable improvement,
and how it was verified. Explain implementation details when they clarify a
tradeoff or limitation.

For user-visible features and performance improvements, update
[docs/PATCH_NOTES.md](docs/PATCH_NOTES.md), newest dated entry first. State what
users gain, how to use the feature, and any material limits. For performance claims:

- Record the baseline, result, units, absolute savings, and percentage reduction.
- Identify the scenario, resident count, hardware, renderer, cache state, and
  measurement boundary. Distinguish viewer startup from total launcher time.
- Include the sample count and evidence. Keep a small, shareable measurement
  summary in `docs/benchmarks/`; keep raw logs in their ignored locations.
- Separate one-time preprocessing cost from the savings on later launches.
  State which work still happens at runtime.
- Label single-run observations, estimates, and non-comparable runs explicitly.
  If an improvement has not been measured, say so; do not invent a number or
  infer FPS, simulation capacity, or accuracy from startup timings.

## Project Structure and Ownership

- `civic_center/`: authoritative resident simulation, worker, launcher, geography preparation, and per-run JSON logging.
- `viewer/`: Godot presentation, loading screen, cameras, 2D map, scenery streaming, and runtime assets.
- `native/`: optional Rust routing and crowd helpers; retain working fallbacks.
- `scripts/`: geographic imports, asset preparation, benchmarks, and Windows packaging.
- `assets/source/`: Blender sources; `contracts/`: transport protocol and replay fixtures.
- `tests/civic_center/` and `viewer/*_tests.gd`: application checks; `tests/` also retains engine/demo checks.
- `openglassbox/` and `demo/`: original engine and pygame demo; `comparison/`: renderer experiments.
- `docs/`: plans, provenance, patch notes, and development evidence.

Python owns simulation state; Godot owns presentation. Update
`contracts/CIVIC_PROTOCOL.md` and fixtures when transport behavior changes.
Preserve source attribution and distinguish observed geography from synthetic
residents, schedules, and travel assumptions.

## Development Commands

Run from this repository root with Python 3.10+. On this Windows checkout, use
`venv\Scripts\python.exe` for tooling; `python -m civic_center` selects that
environment automatically when it exists.

- `python -m civic_center`: launch the city. See `civic_center/README.md` for Godot discovery and options.
- `venv\Scripts\python.exe -m pytest tests/civic_center -q`: application tests.
- `python -m civic_center --world pilot --no-geography --population 1 --headless --smoke-test`: small integration check.
- `venv\Scripts\python.exe scripts/prepare_sf_render.py`: prepare City Hall scenery; add `--scope city` for the full installed city.
- `venv\Scripts\python.exe -m pip install -e ".[dev]"`: install legacy engine/demo and development dependencies, including pytest 9+; the city application currently runs from the checkout.
- `venv\Scripts\python.exe -m pytest`: complete Python suite.
- `python -m demo.src.main`: retained pygame demo.

Follow `viewer/README.md` for relevant Godot checks. For web comparison changes,
run `npm ci`, `npm test`, `npm run build`, and `npm run smoke` in `comparison/web/`.
Use `docs/WINDOWS_BUILD.md` for application packaging; `python -m build` builds
the legacy Python distributions.

## Coding Style and Validation

Use four-space Python indentation, type annotations, snake_case functions/modules,
and PascalCase classes. Preserve the original engine's camelCase APIs and `m_`
fields. Run Black and isort on changed Python files with 88 columns and the Black
profile. Match existing tab indentation in GDScript. Flake8 and mypy commands are
in `Makefile`.

Add meaningful regression tests for changed simulation, routing, save/resume, and
protocol behavior. For viewer behavior changes, run the applicable Godot checks
and capture rendered evidence. For documentation-only changes, check facts,
calculations, links, and whitespace; do not rebuild city data or rerun unrelated
application tests.

Use short, action-oriented commit subjects. Keep commits focused. PRs should
describe the user-visible change, relevant validation, and material limitations;
include screenshots for visual changes.

## Generated Data and Performance Evidence

Keep geography, terrain, scenarios, saves, logs, and render caches under ignored
`.local/civic/` paths, and transient reports under `.cache/`. Per-run diagnostics
live in `.local/civic/logs/`. Do not commit virtual environments, generated meshes,
downloaded datasets, or raw logs.

Prepared scenery depends on source data, builder code, and relevant settings.
Retain validation and regeneration on cache misses or corruption. Scope expensive
preparation to the change being tested and reuse valid caches. Export only the
aggregate measurements needed for a patch note; exclude tokens, private absolute
paths, and individual resident records.
