# Panda3D City Hall demo - round two

This desktop viewer imports the actual `../shared/civic-center.glb` authored in
Blender, using the pinned `panda3d-gltf` and `panda3d-simplepbr` packages. It fails
clearly if the GLB is missing; JSON primitives are blueprint metadata rather than
a fallback model. No online map or asset service is contacted by the viewer.

From the repository root:

```powershell
venv\Scripts\python.exe -m pip install -r comparison\panda3d\requirements.txt
venv\Scripts\python.exe comparison\panda3d\main.py --population 200 --mode walk
venv\Scripts\python.exe comparison\panda3d\main.py --smoke-test --population 5000
venv\Scripts\python.exe comparison\panda3d\main.py --population 200 --mode walk --screenshot comparison\artifacts\panda3d-round-two-walk.png
```

The population menu and **+ / -** cycle through 200, 1,000 and 5,000 people while
preserving time and camera. These are synthetic workloads, not observed residents.
**1** selects overhead orbit, **2** walking, **3** follows the selected or first
resident. Drag to look/orbit, wheel to zoom overhead, **WASD** to walk, **Shift** to
move faster, and arrow keys to turn/look. **Space** pauses, **T** switches 1x/4x,
and **R** resets. Click an imported building or person to inspect it.

People have seven human-scale body parts, with procedural arm and leg motion.
Seven hardware-instanced part meshes share a dynamic position/heading buffer;
there are no scene nodes per resident. Static GLB shadows render correctly;
person shadows are not visible in the current captures despite the separate
instanced shadow pass, so crowd shadow parity remains a rendering limitation.
All people remain represented. Gait is enabled only for the closest
300 people within 80 m; distant people retain their complete static silhouette.
This is procedural articulation, not an imported skeletal animation or behavioral
crowd simulation. Population colors and routes use the shared Python generator.

The HUD separately reports simulated people, centers inside the camera frustum,
people receiving gait, and imported GLB mesh count. Visibility is not an occlusion
measurement. The 1,977 blueprint primitives become 146 imported mesh objects in
the current asset. Frame timing is local feedback, not a controlled benchmark.

Walking uses the shared building rectangles and staircase ramp approximation,
with a 1.8 m eye offset. It does not implement interior navigation, dynamic crowd
collision, or full character physics. Imported metadata identifies whole buildings;
resident picking uses human-sized bounds around their live route positions.

Smoke tests exercise imported-asset picking, resident picking, route movement and
wrap, pause, speed, camera modes, ramp height, nearby gait, runtime population
changes, and reset. Success prints `PANDA3D_SMOKE_OK` with live state and exits zero.
The offscreen tests and PNG capture still need a working graphics driver. This
machine's offscreen driver did not provide requested MSAA, so saved edges may be
more jagged than an interactive window.

The instanced shader reuses the pinned simplepbr 0.13.1 material shader source with
added instance transforms; upgrading that dependency requires checking its shader
interface. The GLB and shared Python population module must accompany a packaged
build. Editable Blender source is not required at runtime.

References: [Panda3D glTF importer](https://github.com/Moguri/panda3d-gltf),
[simplepbr](https://github.com/Moguri/panda3d-simplepbr), and
[instanced vertex arrays](https://docs.panda3d.org/1.10/python/reference/panda3d.core.GeomVertexArrayFormat).
