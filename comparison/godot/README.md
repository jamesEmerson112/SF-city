# Godot City Hall demo - round two

This desktop Godot 4 viewer imports the actual `../shared/civic-center.glb` at
runtime with `GLTFDocument`. JSON primitives remain blueprint metadata, not a
silent fallback. Missing or invalid assets fail clearly. No editor import step,
plugin, online map, Python process, or running Blender instance is required.

From the repository root, using the portable executable downloaded for this
comparison or your own Godot 4 executable:

```powershell
& comparison\.tools\godot\Godot_v4.7.2-stable_win64_console.exe --path comparison/godot -- --population 200 --mode walk
& comparison\.tools\godot\Godot_v4.7.2-stable_win64_console.exe --headless --path comparison/godot -- --smoke-test --population 5000
& comparison\.tools\godot\Godot_v4.7.2-stable_win64_console.exe --path comparison/godot -- --smoke-test --population 200 --screenshot "$PWD/comparison/artifacts/godot-round-two.png"
```

Import `project.godot` into the editor to inspect the implementation. Running from
source loads the fixture and GLB beside the Godot project directory. Standalone
exports must package these external files explicitly.

The population dropdown and **+ / -** choose 200, 1,000 or 5,000 people while
preserving time and camera. **1** selects overhead orbit, **2** walking, and **3**
follows the selected or first resident. Drag either mouse button to look/orbit;
use the wheel to zoom overhead. Walking uses **WASD**, **Shift** for faster movement,
and left/right arrows to turn. **Space** pauses, **T** changes 1x/4x playback, and
**R** resets. Click buildings or human-scale residents to inspect them.

Seven MultiMeshes render all residents. The shader samples the shared routes and
articulates arms and legs; identities and picking positions are lightweight CPU
records. Only the nearest 300 people within 80 m receive gait. Everyone remains
represented with the complete seven-part silhouette at longer distances. This is
procedural articulation, not imported skeletal animation or realistic crowd AI.

The HUD separates synthetic population, centers inside the camera frustum,
residents receiving gait, and actual imported mesh count. Frustum visibility does
not account for occlusion. The current GLB has 146 mesh objects, compiled from
1,977 blueprint primitives. Local frame timing is not a controlled benchmark.

Walking uses shared building rectangles and the staircase ramp approximation,
with a 1.8 m eye offset. Full interiors, dynamic crowd collision and character
physics are outside this demo. glTF extras resolve building identity across joined
meshes; imported geometry is ray-picked, and residents use human-sized bounds.

`--mode overhead|walk|follow` controls both startup and screenshot views. PNG
capture briefly opens a rendered window and exits; do not combine it with
`--headless`. Smoke tests cover imported/resident picking, deterministic movement,
cameras, pause/speed/reset, ramp height, gait limits and runtime population changes.
Success prints `GODOT_COMPARISON_SMOKE_OK` and live state, then exits zero. Headless
checks validate behavior; rendered screenshots separately validate GPU output.

This viewer uses the Compatibility renderer. The Windows sandbox may print
certificate-store or shader-cache write diagnostics; the tested logic and rendered
runs completed successfully despite those diagnostics.

References: [runtime glTF loading](https://docs.godotengine.org/en/stable/classes/class_gltfdocument.html),
[MultiMesh](https://docs.godotengine.org/en/stable/classes/class_multimesh.html), and
[command-line usage](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html).
