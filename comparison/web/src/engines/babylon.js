import {
  ArcRotateCamera, BoundingInfo, Color3, Color4, DirectionalLight, Engine, FreeCamera, Frustum,
  HemisphericLight, MeshBuilder, Scene, ShadowGenerator, StandardMaterial,
  ImportMeshAsync, Matrix, Vector3,
} from '@babylonjs/core';
import '@babylonjs/loaders/glTF';
import { canWalk, sampleResident, sampleGait, walkingEyeHeight } from '../common.js';

// Use a right-handed Y-up world, preserving the fixture's east/north orientation.
const vector = ([x, y, z]) => new Vector3(x, z, -y);
const radians = (degrees) => degrees * Math.PI / 180;

export async function createViewer({ canvas, scene, onSelect = () => {} }) {
  const engine = new Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
  engine.setHardwareScalingLevel(1 / Math.min(window.devicePixelRatio || 1, 2));
  const world = new Scene(engine);
  world.useRightHandedSystem = true;
  world.clearColor = new Color4(0.725, 0.831, 0.875, 1);
  const extent = Math.max(
    scene.bounds.max[0] - scene.bounds.min[0],
    scene.bounds.max[1] - scene.bounds.min[1],
  );
  world.fogMode = Scene.FOGMODE_LINEAR;
  world.fogStart = extent * 1.7;
  world.fogEnd = extent * 5;
  world.fogColor = new Color3(0.725, 0.831, 0.875);
  const orbit = new ArcRotateCamera('overhead', 0, 0.7, scene.camera.distance, vector(scene.camera.target), world);
  // Thin pavement layers need more depth precision from the distant overhead view.
  orbit.minZ = 1;
  orbit.maxZ = extent * 6;
  orbit.fov = radians(55);
  orbit.lowerRadiusLimit = 12;
  orbit.upperRadiusLimit = extent * 3;
  orbit.lowerBetaLimit = 0.04;
  orbit.upperBetaLimit = Math.PI / 2 - 0.03;
  orbit.wheelDeltaPercentage = 0.01;
  orbit.panningSensibility = 40;
  orbit.inputs.removeByType('ArcRotateCameraKeyboardMoveInput');
  const walkCamera = new FreeCamera('ground-level', vector(scene.camera.walk_position), world);
  walkCamera.minZ = 0.1;
  walkCamera.maxZ = extent * 6;
  walkCamera.fov = radians(55);
  walkCamera.inputs.clear();
  const ambient = new HemisphericLight('sky', new Vector3(0, 1, 0), world);
  ambient.diffuse = new Color3(0.93, 0.97, 1);
  ambient.groundColor = new Color3(0.42, 0.47, 0.39);
  ambient.intensity = 0.8;
  const sunlight = new DirectionalLight('sun', new Vector3(0.5, -1, -0.45).normalize(), world);
  sunlight.position = new Vector3(-extent * 0.5, extent, extent * 0.45);
  sunlight.diffuse = new Color3(1, 0.95, 0.85);
  sunlight.intensity = 1;
  // Fit the directional shadow volume to this small district, not the far camera.
  sunlight.shadowMinZ = extent * 0.25;
  sunlight.shadowMaxZ = extent * 2.5;
  sunlight.shadowFrustumSize = extent * 1.25;
  const shadows = new ShadowGenerator(2048, sunlight);
  shadows.usePercentageCloserFiltering = true;
  // Imported glTF and Babylon-built characters use different winding. Invert
  // each mesh's effective shadow winding instead of forcing one global winding.
  // Closed back faces prevent roof acne without detaching pedestrian shadows.
  shadows.forceBackFacesOnly = false;
  shadows.onBeforeShadowMapRenderMeshObservable.add(object => {
    const orientation = object.material?.sideOrientation ?? object.sideOrientation;
    let reverse = orientation === 0;
    const mirrored = object.getWorldMatrix().determinant() < 0;
    if (world.useRightHandedSystem !== mirrored) reverse = !reverse;
    engine.setState(true, 0, false, !reverse, object.material?.cullBackFaces ?? true);
  });
  shadows.bias = 0.0002;
  shadows.normalBias = 0.05;
  const objectMaterials = new Map();

  function material(id, color) {
    const surface = new StandardMaterial(`material-${id}`, world);
    surface.diffuseColor = new Color3(...color);
    surface.specularColor = new Color3(0.04, 0.04, 0.04);
    return surface;
  }
  if (!scene.asset?.url) throw new Error('Babylon.js requires the shared Blender GLB asset URL');
  const district = await ImportMeshAsync(scene.asset.url, world);
  const primitiveMetadata = new Map(scene.primitives.map(primitive => [primitive.id, primitive]));
  function buildingSelection(object) {
    for (let node = object; node; node = node.parent) {
      const metadata = node.metadata?.gltf?.extras || node.metadata || {};
      const primitive = primitiveMetadata.get(metadata.id || node.name);
      if (metadata.id || primitive) return {
        id: metadata.id || primitive.id,
        label: metadata.label || primitive?.label || node.name,
        type: metadata.type || (primitive?.collidable ? 'building' : 'feature'),
      };
    }
    return null;
  }
  let importedMeshCount = 0;
  for (const object of district.meshes) {
    if (!object.getTotalVertices()) continue;
    importedMeshCount++;
    object.computeWorldMatrix(true);
    object.receiveShadows = true;
    const bounds = object.getBoundingInfo().boundingBox;
    if (bounds.maximumWorld.y - bounds.minimumWorld.y >= 1 && bounds.maximumWorld.y > 0.5) shadows.addShadowCaster(object);
    const selection = buildingSelection(object);
    object.metadata = { ...object.metadata, selection };
    object.isPickable = Boolean(selection);
    if (object.material) {
      object.material = object.material.clone(`${object.name}-selection-material`);
      // These closed district meshes render only their outward-facing surfaces.
      object.material.backFaceCulling = true;
      if (selection) objectMaterials.set(selection.id, [...(objectMaterials.get(selection.id) || []), object.material]);
    }
  }
  if (!importedMeshCount) throw new Error('Blender GLB contains no renderable meshes');
  if (scene.character?.parts?.length !== 7) throw new Error('Shared fixture requires seven human character parts');
  let residents = [];
  let crowdMeshes = [];
  let visibleResidentCount = 0;
  let animatedResidentCount = 0;
  const animated = new Set();
  const crowdMaterial = material('residents', [1, 1, 1]);
  const residentCenter = new Vector3();
  function residentColor(resident, role) {
    const field = { clothes: 'color', clothing: 'color', skin: 'skin_color', trousers: 'trouser_color', backpack: 'bag_color', bag: 'bag_color' }[role] || role;
    return resident[field] || resident.color;
  }
  function updateCrowdColors() {
    crowdMeshes.forEach((batch, partIndex) => {
      residents.forEach((entry, i) => {
        const color = residentColor(entry.resident, scene.character.parts[partIndex].color_role);
        const highlight = entry.resident.id === selected?.id;
        batch.colors[i * 4] = highlight ? color[0] * 0.35 + 0.65 : color[0];
        batch.colors[i * 4 + 1] = highlight ? color[1] * 0.35 + 0.65 : color[1];
        batch.colors[i * 4 + 2] = highlight ? color[2] * 0.35 + 0.35 : color[2];
        batch.colors[i * 4 + 3] = 1;
      });
      batch.object.thinInstanceBufferUpdated('color');
    });
  }
  async function setPopulation(population) {
    if (!Array.isArray(population) || !population.length) throw new Error('Population must contain residents');
    for (const batch of crowdMeshes) {
      shadows.removeShadowCaster(batch.object);
      batch.object.dispose();
    }
    residents = population.map(resident => ({ resident, sample: sampleResident(scene, resident, simulationTime) }));
    crowdMeshes = scene.character.parts.map((part, i) => {
      const object = part.kind === 'sphere'
        ? MeshBuilder.CreateSphere(`residents-${i}`, { diameter: part.radius * 2, segments: 8 }, world)
        : MeshBuilder.CreateBox(`residents-${i}`, { width: part.size[0], height: part.size[2], depth: part.size[1] }, world);
      object.material = crowdMaterial;
      object.receiveShadows = true;
      object.metadata = { residentPart: true };
      object.thinInstanceEnablePicking = true;
      object.doNotSyncBoundingInfo = true;
      // Conservative district bounds remain valid while residents follow routes.
      object.setBoundingInfo(new BoundingInfo(
        new Vector3(scene.bounds.min[0] - 2, -2, -scene.bounds.max[1] - 2),
        new Vector3(scene.bounds.max[0] + 2, 5, -scene.bounds.min[1] + 2),
      ));
      const matrices = new Float32Array(residents.length * 16);
      const colors = new Float32Array(residents.length * 4);
      object.thinInstanceSetBuffer('matrix', matrices, 16, false);
      object.thinInstanceSetBuffer('color', colors, 4, false);
      shadows.addShadowCaster(object);
      return { object, matrices, colors };
    });
    if (selected?.type === 'resident' && !residents.some(entry => entry.resident.id === selected.id)) {
      selected = null;
      onSelect(null);
    }
    updateCrowdColors();
    update(simulationTime, 0);
  }
  function updateCrowd() {
    const nearby = [];
    const active = world.activeCamera;
    active.getViewMatrix();
    active.getProjectionMatrix();
    const planes = Frustum.GetPlanes(active.getTransformationMatrix());
    visibleResidentCount = 0;
    residents.forEach((entry, i) => {
      const position = entry.sample.position;
      residentCenter.set(position[0], position[2] + scene.character.height / 2, -position[1]);
      if (planes.every(plane => plane.dotCoordinate(residentCenter) >= 0)) visibleResidentCount++;
      const distance = Vector3.DistanceSquared(residentCenter, active.position);
      if (distance <= 80 * 80) nearby.push({ i, distance });
    });
    nearby.sort((a, b) => a.distance - b.distance || a.i - b.i);
    animated.clear();
    for (const entry of nearby.slice(0, 300)) animated.add(entry.i);
    animatedResidentCount = animated.size;
    residents.forEach((entry, i) => {
      const { position, heading } = entry.sample;
      const cosHeading = Math.cos(heading), sinHeading = Math.sin(heading);
      const gait = animated.has(i) ? sampleGait(entry.resident, simulationTime) : 0;
      scene.character.parts.forEach((part, partIndex) => {
        const angle = (part.swing || 0) * gait;
        const cosAngle = Math.cos(angle), sinAngle = Math.sin(angle);
        const pivot = part.pivot || part.center;
        const dx = part.center[0] - pivot[0], dz = part.center[2] - pivot[2];
        const x = pivot[0] + cosAngle * dx + sinAngle * dz;
        const y = part.center[1];
        const z = pivot[2] - sinAngle * dx + cosAngle * dz;
        const matrix = crowdMeshes[partIndex].matrices;
        const offset = i * 16;
        matrix[offset] = cosHeading * cosAngle;
        matrix[offset + 1] = -sinAngle;
        matrix[offset + 2] = -sinHeading * cosAngle;
        matrix[offset + 3] = 0;
        matrix[offset + 4] = cosHeading * sinAngle;
        matrix[offset + 5] = cosAngle;
        matrix[offset + 6] = -sinHeading * sinAngle;
        matrix[offset + 7] = 0;
        matrix[offset + 8] = sinHeading;
        matrix[offset + 9] = 0;
        matrix[offset + 10] = cosHeading;
        matrix[offset + 11] = 0;
        matrix[offset + 12] = position[0] + cosHeading * x - sinHeading * y;
        matrix[offset + 13] = position[2] + z;
        matrix[offset + 14] = -(position[1] + sinHeading * x + cosHeading * y);
        matrix[offset + 15] = 1;
      });
    });
    for (const batch of crowdMeshes) batch.object.thinInstanceBufferUpdated('matrix');
  }

  let mode = 'orbit';
  let selected = null;
  let simulationTime = 0;
  const keys = new Set();
  const walkPosition = [...scene.camera.walk_position];
  let walkYaw = 0;
  let walkPitch = 0;
  let drag = null;
  const listeners = [];
  function listen(target, event, callback, options) {
    target.addEventListener(event, callback, options);
    listeners.push(() => target.removeEventListener(event, callback, options));
  }
  const isInput = (target) => target instanceof HTMLElement && (
    target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)
  );
  listen(window, 'keydown', (event) => {
    if (isInput(event.target)) return;
    if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'].includes(event.code)) {
      keys.add(event.code);
      if (mode === 'walk') event.preventDefault();
    }
  });
  listen(window, 'keyup', (event) => keys.delete(event.code));
  listen(window, 'blur', () => { keys.clear(); drag = null; });
  listen(canvas, 'contextmenu', (event) => event.preventDefault());
  listen(canvas, 'pointerdown', (event) => {
    if (event.button !== 0) return;
    drag = { lastX: event.clientX, lastY: event.clientY, distance: 0 };
    if (mode !== 'orbit') canvas.setPointerCapture(event.pointerId);
  });
  listen(canvas, 'pointermove', (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.lastX;
    const dy = event.clientY - drag.lastY;
    drag.distance += Math.abs(dx) + Math.abs(dy);
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
    if (mode === 'walk') {
      walkYaw -= dx * 0.004;
      walkPitch = Math.max(-1.35, Math.min(1.35, walkPitch - dy * 0.004));
      aimWalk();
    }
  });
  listen(canvas, 'pointerup', (event) => {
    if (!drag) return;
    const shouldPick = drag.distance < 5;
    drag = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!shouldPick) return;
    const bounds = canvas.getBoundingClientRect();
    // Babylon caches per-instance picking matrices. Refresh that public cache from
    // the current GPU buffers so picking follows animation after the first click.
    for (const batch of crowdMeshes) {
      const matrices = batch.object.thinInstanceGetWorldMatrices();
      for (let i = 0; i < matrices.length; i++) Matrix.FromArrayToRef(batch.matrices, i * 16, matrices[i]);
    }
    const hit = world.pick(event.clientX - bounds.left, event.clientY - bounds.top,
      object => Boolean(object.metadata?.selection || object.metadata?.residentPart));
    if (!hit?.hit || !hit.pickedMesh?.metadata) return;
    if (selected) for (const surface of objectMaterials.get(selected.id) || []) surface.emissiveColor.set(0, 0, 0);
    const resident = hit.pickedMesh.metadata.residentPart ? residents[hit.thinInstanceIndex]?.resident : null;
    selected = resident ? { id: resident.id, label: resident.label, type: 'resident' } : hit.pickedMesh.metadata.selection;
    if (!selected) return;
    for (const surface of objectMaterials.get(selected.id) || []) surface.emissiveColor.set(0.12, 0.2, 0.2);
    updateCrowdColors();
    onSelect(selected);
  });
  listen(canvas, 'pointercancel', () => { drag = null; });

  function aimWalk() {
    walkPosition[2] = walkingEyeHeight(scene, walkPosition[0], walkPosition[1]);
    walkCamera.position.copyFrom(vector(walkPosition));
    walkCamera.setTarget(walkCamera.position.add(new Vector3(
      Math.cos(walkYaw) * Math.cos(walkPitch),
      Math.sin(walkPitch),
      -Math.sin(walkYaw) * Math.cos(walkPitch),
    )));
  }
  function resetWalk() {
    walkPosition.splice(0, 3, ...scene.camera.walk_position);
    walkYaw = Math.atan2(scene.camera.target[1] - walkPosition[1], scene.camera.target[0] - walkPosition[0]);
    walkPitch = radians(scene.camera.walk_pitch_degrees ?? 18);
    aimWalk();
  }
  function resetOrbit() {
    const yaw = radians(scene.camera.yaw_degrees);
    const pitch = radians(scene.camera.pitch_degrees);
    const distance = scene.camera.distance;
    const target = vector(scene.camera.target);
    orbit.setTarget(target);
    orbit.setPosition(target.add(new Vector3(
      Math.cos(yaw) * Math.cos(pitch) * distance,
      Math.sin(pitch) * distance,
      -Math.sin(yaw) * Math.cos(pitch) * distance,
    )));
    orbit.inertialAlphaOffset = 0;
    orbit.inertialBetaOffset = 0;
    orbit.inertialRadiusOffset = 0;
    orbit.inertialPanningX = 0;
    orbit.inertialPanningY = 0;
  }
  function follow() {
    const resident = residents.find((entry) => entry.resident.id === selected?.id) || residents[0];
    if (!resident) return;
    const { position, heading } = resident.sample;
    walkCamera.position.copyFrom(vector([
      position[0] - Math.cos(heading) * 13,
      position[1] - Math.sin(heading) * 13,
      position[2] + 8,
    ]));
    walkCamera.setTarget(vector([position[0], position[1], position[2] + 2]));
  }
  function setMode(nextMode) {
    if (!['orbit', 'walk', 'follow'].includes(nextMode)) throw new Error(`Unknown camera mode: ${nextMode}`);
    mode = nextMode;
    keys.clear();
    drag = null;
    orbit.detachControl();
    if (mode === 'orbit') {
      world.activeCamera = orbit;
      resetOrbit();
      orbit.attachControl(canvas, true);
    } else {
      world.activeCamera = walkCamera;
      if (mode === 'walk') resetWalk();
      else follow();
    }
  }
  function moveWalk(dt) {
    const step = Math.min(Math.max(dt, 0), 0.05);
    walkYaw += ((keys.has('ArrowLeft') ? 1 : 0) - (keys.has('ArrowRight') ? 1 : 0)) * step * 1.7;
    const forward = Number(keys.has('KeyW') || keys.has('ArrowUp')) - Number(keys.has('KeyS') || keys.has('ArrowDown'));
    const side = Number(keys.has('KeyD')) - Number(keys.has('KeyA'));
    const norm = Math.hypot(forward, side) || 1;
    const speed = keys.has('ShiftLeft') || keys.has('ShiftRight') ? 22 : 9;
    const dx = (Math.cos(walkYaw) * forward + Math.sin(walkYaw) * side) / norm * speed * step;
    const dy = (Math.sin(walkYaw) * forward - Math.cos(walkYaw) * side) / norm * speed * step;
    if (canWalk(scene, walkPosition[0] + dx, walkPosition[1])) walkPosition[0] += dx;
    if (canWalk(scene, walkPosition[0], walkPosition[1] + dy)) walkPosition[1] += dy;
    aimWalk();
  }
  function resize() { engine.resize(); }
  function update(time, dt) {
    simulationTime = time;
    for (const entry of residents) {
      entry.sample = sampleResident(scene, entry.resident, time);
    }
    if (mode === 'walk') moveWalk(dt);
    if (mode === 'follow') follow();
    updateCrowd();
    world.render();
  }
  resize();
  setMode('orbit');
  await setPopulation(scene.residents);
  return {
    update, setMode, resize, setPopulation,
    resetCamera() { setMode(mode); },
    getState() {
      const activePosition = world.activeCamera.position;
      const firstMatrix = crowdMeshes[0]?.matrices;
      const sampleAnimatedIndex = animated.values().next().value;
      const limbMatrix = crowdMeshes[2]?.matrices;
      return {
        mode, simulationTime,
        residentCount: residents.length, visibleResidentCount, animatedResidentCount,
        assetLoaded: true, importedMeshCount,
        residentPartCount: residents.length * 7,
        sampleAnimatedResidentId: residents[sampleAnimatedIndex]?.resident.id || null,
        sampleGaitAngle: sampleAnimatedIndex === undefined ? 0 : Math.atan2(-limbMatrix[sampleAnimatedIndex * 16 + 1], limbMatrix[sampleAnimatedIndex * 16 + 5]),
        sampleResidentPosition: firstMatrix ? [firstMatrix[12], -firstMatrix[14], firstMatrix[13] - scene.character.parts[0].center[2]] : null,
        cameraPosition: [activePosition.x, -activePosition.z, activePosition.y],
        selectedId: selected?.id || null,
        activeMeshes: world.getActiveMeshes().length,
        totalVertices: world.getTotalVertices(),
      };
    },
    dispose() {
      for (const remove of listeners) remove();
      world.dispose();
      engine.dispose();
    },
  };
}
