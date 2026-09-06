# Round two: detailed City Hall and adjustable crowds

Round two implements both requested improvements: a detailed shared Blender scene
and adjustable population. Godot, Panda3D, Three.js, Babylon.js, deck.gl and CesiumJS
load the same City Hall GLB and display human-scale people at 200, 1,000 or 5,000
residents. The user selected Godot on September 5, 2026. The next phase is defined
in the [Godot implementation plan](../docs/GODOT_NEXT_STEPS.md).

This is an original visual approximation of Civic Center with synthetic trips.
The architecture is not surveyed San Francisco geometry, and the crowd presets
are rendering workloads rather than observed neighborhood population.

## Delivered experience

Start above Civic Center, switch to street level, inspect City Hall's facade and
dome, and walk toward the entrance. Select a building or person, follow a resident,
pause playback, or change population while preserving the camera and simulation
time. The initial walking view tilts upward by 18 degrees to frame the landmark;
drag to look around.

- **Shared architecture:** the Blender source and GLB include the dome and ribs,
  columns, pediment, inscription, window details, staircase, paving, fountain,
  street furniture, crossings and surrounding buildings. The export contains
  146 meshes and 47 materials, recorded in [the asset manifest](shared/asset-manifest.json).
- **Human-scale characters:** each person has a torso, head, two arms, two legs
  and backpack. Clothing, skin, trousers and backpack colors vary. Joint rotations
  produce procedural walking poses; these are not imported skeletal animations.
- **Population controls:** 200, 1,000 and 5,000 people use stable IDs and the same
  deterministic four-route playback. Home and destination labels support inspection;
  they do not represent a working household or employment simulation.
- **Nearby animation:** limbs animate for the nearest people within 80 meters,
  capped at 300. Other people retain their complete human silhouette and continue
  along their routes. Population, centers inside the camera frustum, and animated
  people are reported separately. Frustum counts do not measure occlusion.
- **Ground-level movement:** shared building rectangles constrain walking and
  entrance ramp approximations adjust camera eye height over the steps. These are
  simple movement aids, not full stair, terrain or pedestrian physics.

The 5,000-person preset can produce substantial overlap along the four fixed
routes. There is no crowd avoidance, crossing arbitration or queue simulation.

## Shared assets and implementation differences

[civic-center.blend](shared/civic-center.blend) is the editable source;
[civic-center.glb](shared/civic-center.glb) is the exported asset loaded by every
viewer. [scene.json](shared/scene.json) supplies route, character, population,
camera and collision data. Its primitive records remain the authoring blueprint
and metadata; they are not a fallback for a failed GLB import. The asset is
original and uses material colors without external image textures.

| Viewer | Asset and crowd path |
|---|---|
| Godot | GLB import, Compatibility renderer and seven MultiMesh character batches |
| Panda3D | panda3d-gltf import, simplepbr materials and seven hardware-instanced character parts |
| Three.js | GLTFLoader and seven InstancedMesh character parts |
| Babylon.js | glTF importer and seven character meshes with thin instances |
| deck.gl | Imported GLB geometry grouped by building, material base colors baked into vertex colors, and seven instanced character layers |
| CesiumJS | Native GLB Model in a local east/north/up frame, with one batched crowd primitive using GPU route and gait calculations |

Deck.gl uses shared mesh lighting without cast shadows and does not preserve the
GLB's individual roughness, metallic or emission properties. The other viewers
include shadows, but lighting, material treatment, antialiasing and shadow quality
still differ. The comparison therefore exercises actual import and interaction
workflows without claiming identical pixels or rendering work.
Panda3D's architecture shadows work, but its instanced character shadows were not
visible in current captures despite a separate shadow pass. That is a remaining
adapter limitation, not evidence that the engine cannot support them.

The running scenes require no hosted basemap, terrain, asset service or API token.
See [the demo README](README.md) for launch commands and controls, and
[the round-two contract](shared/ROUND_TWO_CONTRACT.md) for the shared conventions.

## Validation and interpretation

Validation covers GLB loading, deterministic resident movement, population changes,
nearby gait, building and person selection, orbit/walk/follow cameras, playback,
reset and camera movement. Browser smoke checks also inspect errors and requests
for external content. Screenshots allow inspection of the imported landmark and
human silhouettes; an automated count alone cannot establish visual fidelity.

Live FPS, frame interval and available percentile readouts are local diagnostics.
Asset loading, shader preparation, population rebuilds, viewport size, browser or
native runtime, GPU drivers and other running applications all affect them. These
readouts are not controlled engine benchmarks and do not establish a winner.

## Future work

The following parts of the earlier challenge remain future work:

- Real San Francisco building and street data, calibrated populations, persistent
  homes and jobs, and integration with the OpenGlassBox simulation backend.
- Imported rigged characters, skeletal walk/idle clips and animation transitions;
  texture-rich stone, pavement and other materials.
- Departure and arrival events, crossing waits, queues, building entry and
  occupancy, pedestrian avoidance and fuller collision or terrain physics.
- Day/night controls, dusk lighting, changing sun and streetlight behavior.
- Enhanced visual presets using each engine's additional rendering capabilities,
  recorded separately from attempts to match scene quality.
- A repeatable camera replay, controlled steady-state benchmarks, comparable
  memory and loading measurements, and a documented Blender edit/reimport exercise.

A later benchmark should run one viewer at a time at fixed resolution, warm up
shaders, separate loading and rebuilds from steady playback, and record hardware,
runtime, quality settings and visible/animated counts. Choose an engine from the
experience and implementation effort together with that evidence.
