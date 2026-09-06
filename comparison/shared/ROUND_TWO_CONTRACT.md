# Round-two asset and crowd contract

World axes remain X east, Y north, Z up, in meters. `scene.asset.file` names
`civic-center.glb` beside `scene.json`; web URL is `/scene-assets/civic-center.glb`.
Blender exports standard glTF Y-up, so game engines use `(x,z,-y)`; geospatial
adapters convert imported geometry back to local ENU. Load the actual asset.
JSON primitives remain metadata and the asset-generation blueprint, not a
silent fallback for a broken GLB import.

Static asset meshes have stable names and custom extras `id`, `label`, `type`.
Repeated architectural details may be joined per building/material. Walk collision
continues to use the shared rectangles. `walk_surfaces` optionally describes ramp
approximations for stair eye height; do not invent full physics from those fields.

Population presets are 200, 1000 and 5000. Resident i uses ID `resident-` plus a
zero-padded minimum-three-digit index, route `route-(i % 4)`, and phase
`(i * 0.61803398875) % 1`. Original four clothing colors repeat. The scene carries
the default population; browser `createPopulation(scene,count)` creates others.
Routes remain four closed polylines with duration-based arc-length playback.
Population size is a synthetic workload, not observed neighborhood population.

Browser adapters add `setPopulation(residentsArray)` (may return a Promise).
Preserve simulation time and camera; clear selection if its ID no longer exists.
Report `residentCount`, `visibleResidentCount` (centers inside camera frustum,
not an occlusion measurement), `animatedResidentCount`, `assetLoaded` and
`sampleResidentPosition` from live rendering state. Root UI handles population
selection and timing. Native adapters expose equivalent controls and CLI options.

Characters are human-scale low-poly articulated models, NOT imported skeletal
animations. Local X is forward, Y left, Z up. All parts are centered meshes.
`scene.character.parts` defines seven parts: torso, head, left/right arm,
left/right leg, backpack. A part has `kind`, `size` or `radius`, `center`,
`color_role` and optionally `pivot`, `swing` (+1/-1).

For moving joints, angle = swing * sin(2*pi*(1.6*time + resident.phase)) * 0.55.
Rotate the part's `(center - pivot)` by local Y, add pivot, then rotate all local
positions by world Z heading from route sampling. Mesh orientation follows
Rz(heading)*Ry(angle). Arms oppose legs. Skin/trouser/backpack colors are carried
on residents as `skin_color`, `trouser_color`, `bag_color`; clothing uses `color`.

All residents stay represented. Animate limbs only within 80 m of the camera,
up to the nearest 300 people (distance, then stable resident index). Distant
people retain the full static human silhouette with gait angle zero. Report
the actual animated count; changing detail must not delete resident identities.
Use engine-appropriate instancing/batching. Shadows and material differences
remain disclosed; raw frame rate does not by itself establish an engine winner.
