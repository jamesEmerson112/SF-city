# Round-two validation

Checked locally on September 5, 2026.

- Shared scene: version 2, 1,977 blueprint shapes, 146 GLB meshes, 47 materials.
- GLB: 2,439,744 bytes; SHA256
  `54ffd49ddae34ef8977ad829fdb19b71c1ef72e448239c2dbcf39f3e8ca03c79`.
- Web shared logic: all five tests pass.
- Web production build: passes. Vite reports large engine bundle warnings.
- Production browser suite: Three.js, Babylon.js, deck.gl and CesiumJS all pass
  actual asset loading, 200/1,000/5,000 population changes, rendered position and
  gait checks, time/camera preservation, navigation settings, building picking,
  pause/speed, walking/following, reset, resize, no browser errors and no external
  content requests.
- Additional adapter checks: moving resident picking and following, selection
  clearing when shrinking population, stair eye height, and missing-asset errors.
- Desktop launcher: Three.js opens exactly one app window with 1,000 residents
  in walking mode, imports the GLB and exits successfully in smoke mode.
- Native engine checks: Godot and Panda3D pass all three population presets,
  runtime population changes, imported metadata and resident picking, route
  playback, camera modes, nearby gait and stair ramp checks. Rendered PNGs are
  checked separately from Godot headless behavior tests.

Reproduce checks using [README.md](README.md) and the native engine READMEs.
The browser suite writes `artifacts/web-smoke-results.json` and PNGs; these
machine-specific outputs are ignored by Git. The Blender source and GLB are
included so a new checkout can inspect the same exported asset.

These are functional checks and visual inspection, not a performance ranking.
The test machine uses Windows and an NVIDIA GTX 1070 Ti. Browser/headless/native
viewport dimensions and graphics paths differ; no comparable FPS or memory
result is claimed. Panda3D offscreen capture lacks requested MSAA on this setup.
Panda3D architecture shadows are visible; instanced character shadows are not
visible in the current captures and remain an adapter limitation.
