# City Hall renderer comparison fixture

All six viewers load `shared/scene.json` and the actual `shared/civic-center.glb`.
The original Blender model is a stylized approximation, not surveyed geography.
The current fixture is version 2; its asset, character, population and reporting
rules are in [the round-two contract](shared/ROUND_TWO_CONTRACT.md).

World coordinates are meters: X east, Y north, Z up. Colors are RGB arrays in
[0, 1]. Standard glTF uses Y-up; importers must preserve shared world coordinates
when reporting camera and resident positions. Building selection uses stable
`id`, `label` and `type` extras exported with the meshes.

`primitives` is the asset-generation blueprint and metadata. Renderers load the
GLB and fail clearly if it is missing; they do not silently substitute primitives.
The asset has 1,977 source shapes joined into 146 meshes by building/material.

Each route has `id`, `label`, `points: [[x,y,z], ...]` and `duration` in seconds.
Routes explicitly end at their first point. At time t, a resident's progress is
`((t / route.duration) + resident.phase) % 1`. Position is that fraction of the
total polyline length, interpolated along the selected segment. Heading follows
the segment. Routes run at approximately 1.45 m/s. Home and destination labels
are illustrative; no arrival, occupancy or daily schedule is implemented.

Walking uses a 0.7 m horizontal radius against shared building rectangles and
world bounds. `walk_surfaces` supplies a ramp approximation of the entrance
stairs, with a 1.8 m eye offset. This is simple camera movement rather than a
character controller with terrain physics. Residents do not collide or queue.
The shared camera specifies `walk_pitch_degrees` for the initial street view.

Controls: Space pauses; 1/2/3 select overhead/walk/follow; R resets time/camera;
T toggles 1x/4x speed; clicking selects buildings or people. The population
control selects 200/1,000/5,000. All identities persist when changing camera or
animation detail. Shrinking population clears a selection that no longer exists.

Browser automation uses `window.comparison`: `ready`, `getState()`, `setMode()`,
`setPaused()`, `setTime()`, `setPopulation()` and `reset()`. Population changes
preserve time and camera. State reports actual imported/rendered data, including
total, camera-frustum and nearby animated population, sample position and gait.
Frustum counts do not account for occlusion. Native viewers expose equivalent
controls and `--population`, `--mode`, `--smoke-test` and screenshot options.

This is a local rendering workload; it is not connected to the OpenGlassBox
simulation backend. Engine-specific batching, lighting and shadows differ and
must be disclosed. Frame intervals do not establish a controlled engine ranking.
