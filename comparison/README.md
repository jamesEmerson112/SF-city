# City Hall engine demos

**Decision, September 5, 2026: Godot is the selected engine for the city application.**
Development continues with the [Godot implementation plan](../docs/GODOT_NEXT_STEPS.md).
These six demos remain available as comparison references.
The live resident application now starts with `python -m civic_center`; see its
[launch instructions](../civic_center/README.md).

Six viewers now share a detailed Blender City Hall model and adjustable crowds:
**Godot, Panda3D, Three.js, Babylon.js, deck.gl and CesiumJS**. Round two adds
facade windows and columns, a ribbed dome, entrance steps, plaza furniture and
human-scale walking people. Choose **200, 1,000 or 5,000 residents** while running.

The model contains 1,977 source shapes joined into 146 imported meshes. It is an
original stylized approximation. Residents follow four synthetic looping routes;
home and destination labels are illustrative. Real geography, daily schedules,
arrival/occupancy behavior and the OpenGlassBox backend remain future work.

## Launch

From the repository root, choose an engine or use the menu:

```powershell
python comparison/launch.py
python comparison/launch.py three --population 1000 --mode walk
python comparison/launch.py godot --population 1000 --mode walk
python comparison/launch.py panda3d
python comparison/launch.py babylon
python comparison/launch.py deck
python comparison/launch.py cesium
```

All engines accept `--population 200|1000|5000` and
`--mode overhead|walk|follow`. Godot and Panda3D open native windows. Web engines
open a separate Edge/Chromium app window; its top links switch engines. Closing
that window stops its local server. Browser profiles and downloaded tools stay
in ignored `.tools/`. This is a local browser app window, not an Electron package.

For a browser tab, run `npm run dev` in `comparison/web`, then open
<http://127.0.0.1:5173>. Stop that server with Ctrl+C.

## Controls

| Input | Action |
|---|---|
| Population control | Switch 200 / 1,000 / 5,000 without resetting time or camera |
| `1` / `2` / `3` | Overhead / walk / follow selected or first resident |
| Drag | Orbit overhead; look around while walking |
| Mouse wheel | Zoom overhead |
| `W A S D` | Walk; hold `Shift` to move faster |
| Left/right arrows | Turn while walking |
| Click | Inspect a building or person |
| `Space` | Pause/resume movement |
| `T` | Toggle 1x / 4x playback |
| `R` | Reset time and the current camera |

Walking checks building rectangles and approximates the entrance stairs with a
ramp. Camera movement remains available while paused. Residents do not collide,
queue at crossings, enter buildings or climb those steps as a scheduled trip.

## What to compare

Start in walking mode with 200 residents. Inspect the facade and people, select
someone and follow them, then raise the population to 1,000 and 5,000. Return to
an overhead view to inspect the whole block. Run one viewer at a time.

People have seven instanced/batched parts with procedural arm and leg movement.
The nearest 300 within 80 meters animate; distant people keep their full static
silhouette and continue moving. These are articulated shapes, not imported
skeletal animations. Total population, centers within the camera frustum and
nearby animated population are separate counts; frustum counts include people
hidden behind buildings. At 5,000, substantial overlap on four fixed routes is
intentional synthetic stress, not a credible local pedestrian distribution.

| Demo | What this implementation exercises |
|---|---|
| Godot | Runtime GLB import, seven MultiMeshes, native UI and picking; Compatibility renderer |
| Panda3D | glTF loading, Python integration, hardware-instanced parts and custom crowd shader |
| Three.js | GLTFLoader, InstancedMesh parts, custom camera/UI integration and ray picking |
| Babylon.js | glTF loader, thin instances, engine materials/shadows and mesh picking |
| deck.gl | Imported geometry baked into selection groups, seven instanced mesh layers and picking |
| CesiumJS | Native GLB in City Hall's east/north/up frame; one GPU crowd batch with picking |

Deck.gl preserves the asset's base colors with shared lighting, rather than its
metallic/roughness/emission materials, and omits cast shadows. Its adapter rejects
image textures instead of silently dropping them. Other viewers load GLB
materials, with different lighting and shadow implementations. The current asset
has colored materials and no image textures. Missing GLB assets fail clearly.
Panda3D's static architecture casts shadows, but character shadows were not visible
in the captured frames; that crowd shadow path still needs work.

FPS and rolling frame intervals are local diagnostics affected by resolution,
refresh rate, drivers and other applications. Browser UI also displays p95 over
its recent frame window. These measurements are not GPU execution times or a
controlled engine ranking. Godot was selected for development after the hands-on comparison.

## Blender asset workflow

The checked-in [Blender source](shared/civic-center.blend) and
[GLB](shared/civic-center.glb) are ready to load; Blender need not run with a demo.
The [manifest](shared/asset-manifest.json) records the exported counts and version.
All architecture is original generated geometry; no hosted asset library, token,
basemap, terrain service or external runtime content is required.

To regenerate the blueprint and rebuild the asset from source:

```powershell
python comparison/shared/generate_scene.py
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python comparison/shared/build_blender_asset.py
```

Adjust the Blender executable path on another machine. The builder creates a
separate scene and saves `.blend` and `.glb` in `shared`. Manual edits in the
Blender file can be exported as GLB instead of regenerating the blueprint; retain
meter scale, Y-up glTF export and object extras for selection. Rebuilding from the
blueprint replaces the generated asset files, including any manual asset edits.

## Set up another checkout

- **Panda3D:** install `comparison/panda3d/requirements.txt` in a Python environment.
  The launcher looks in `venv`, then `.venv`, then uses the launching Python.
  Tested with Python 3.12.10, Panda3D 1.10.16, panda3d-gltf 1.3.0 and
  panda3d-simplepbr 0.13.1.
- **Godot:** set `GODOT_BIN`, put `godot` on PATH, or place a portable console
  executable in `.tools/godot/`. Tested with Godot 4.7.2 Compatibility. Running
  from source loads the shared files; standalone export needs to package them.
- **Web:** Node.js 22.12+ and `npm ci` in `comparison/web`. Use installed
  Edge/Chrome or `npx playwright install chromium`. `COMPARISON_BROWSER=chrome`
  or `msedge` selects a browser channel.

The lockfile pins Three.js 0.185.1, Babylon.js 9.25.0, deck.gl 9.4.0,
CesiumJS 1.145.0, Vite 8.2.2 and Playwright 1.63.0. Dependency installation
requires downloads; the running scene uses local assets.

## Verification

The September 5 checks and their limits are recorded in [VALIDATION.md](VALIDATION.md).

From the repository root:

```powershell
python comparison/launch.py panda3d --smoke-test
python comparison/launch.py godot --smoke-test
python comparison/launch.py three --population 1000 --mode walk --smoke-test
```

Native details and screenshot options are in [Panda3D](panda3d/README.md) and
[Godot](godot/README.md). For the full web suite, in `comparison/web`:

```powershell
npm test
npm run build
npm run smoke
```

The full browser suite starts production preview on loopback port 5175 and checks
all four engines: GLB import, population changes, rendered positions and gait,
pause, speed, picking, cameras, walking, following, reset, resize and absence of
browser errors or external content requests. Screenshots and results go into
ignored `comparison/artifacts/`. Set `COMPARISON_URL` for an existing server, or
`COMPARISON_ENGINES` for a comma-separated subset. Headless timings are not
performance results. The launcher smoke check verifies app-window startup only.

See the [scene contract](SCENE_CONTRACT.md), [round-two scope](ROUND_TWO.md),
[renderer investigation](../docs/RENDERER_COMPARISON.md) and
[San Francisco plan](../docs/SAN_FRANCISCO_PLAN.md).
