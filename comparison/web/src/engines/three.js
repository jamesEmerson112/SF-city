import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { canWalk, sampleResident, sampleGait, walkingEyeHeight } from '../common.js';

// Scene data uses X east, Y north, Z up; Three.js uses Y up.
const vector = ([x, y, z]) => new THREE.Vector3(x, z, -y);
const radians = (degrees) => degrees * Math.PI / 180;

export async function createViewer({ canvas, scene, onSelect = () => {} }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  const world = new THREE.Scene();
  world.background = new THREE.Color('#b9d4df');
  const extent = Math.max(
    scene.bounds.max[0] - scene.bounds.min[0],
    scene.bounds.max[1] - scene.bounds.min[1],
  );
  world.fog = new THREE.Fog('#b9d4df', extent * 1.7, extent * 5);
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, extent * 12);
  const orbit = new OrbitControls(camera, canvas);
  orbit.enableDamping = true;
  orbit.dampingFactor = 0.12;
  orbit.minDistance = 12;
  orbit.maxDistance = extent * 3;
  orbit.maxPolarAngle = Math.PI / 2 - 0.03;
  orbit.screenSpacePanning = false;
  world.add(new THREE.HemisphereLight('#edf7ff', '#6c7864', 1.8));
  const sunlight = new THREE.DirectionalLight('#fff3d8', 2.5);
  sunlight.position.set(-extent * 0.5, extent, extent * 0.45);
  sunlight.castShadow = true;
  sunlight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunlight.shadow.camera, {
    left: -extent * 0.75, right: extent * 0.75,
    top: extent * 0.75, bottom: -extent * 0.75,
    near: 1, far: extent * 4,
  });
  sunlight.shadow.normalBias = 0.15;
  world.add(sunlight);

  const geometries = new Set();
  const materials = new Set();
  const pickables = [];
  const objectMaterials = new Map();
  function material(color) {
    const result = new THREE.MeshStandardMaterial({
      color: new THREE.Color(...color), roughness: 0.88, metalness: 0,
    });
    materials.add(result);
    return result;
  }
  if (!scene.asset?.url) throw new Error('Three.js requires the shared Blender GLB asset URL');
  const district = await new GLTFLoader().loadAsync(scene.asset.url);
  if (!district.scene) throw new Error('Blender GLB contains no scene');
  world.add(district.scene);
  const primitiveMetadata = new Map(scene.primitives.map(primitive => [primitive.id, primitive]));
  function buildingSelection(object) {
    for (let node = object; node; node = node.parent) {
      const metadata = node.userData || {};
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
  district.scene.traverse(object => {
    if (!object.isMesh) return;
    importedMeshCount++;
    geometries.add(object.geometry);
    object.updateWorldMatrix(true, false);
    const bounds = new THREE.Box3().setFromObject(object);
    object.castShadow = bounds.max.y - bounds.min.y >= 1 && bounds.max.y > 0.5;
    object.receiveShadow = true;
    const selection = buildingSelection(object);
    // Imported surfaces may be shared across buildings; clone for local highlighting.
    const surfaces = (Array.isArray(object.material) ? object.material : [object.material]).map(surface => {
      const copy = surface.clone();
      copy.shadowSide = THREE.BackSide;
      materials.add(copy);
      return copy;
    });
    object.material = Array.isArray(object.material) ? surfaces : surfaces[0];
    if (selection) {
      object.userData.selection = selection;
      pickables.push(object);
      objectMaterials.set(selection.id, [...(objectMaterials.get(selection.id) || []), ...surfaces]);
    }
  });
  if (!importedMeshCount) throw new Error('Blender GLB contains no renderable meshes');

  if (scene.character?.parts?.length !== 7) throw new Error('Shared fixture requires seven human character parts');
  let residents = [];
  let crowdMeshes = [];
  let visibleResidentCount = 0;
  let animatedResidentCount = 0;
  const animated = new Set();
  const partGeometry = scene.character.parts.map(part => {
    const geometry = part.kind === 'sphere'
      ? new THREE.SphereGeometry(part.radius, 10, 8)
      : new THREE.BoxGeometry(part.size[0], part.size[2], part.size[1]);
    geometries.add(geometry);
    return geometry;
  });
  const crowdMaterial = material([1, 1, 1]);
  const transform = new THREE.Object3D();
  const headingQuaternion = new THREE.Quaternion();
  const swingQuaternion = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const forward = new THREE.Vector3(0, 0, 1);
  const instanceColor = new THREE.Color();
  const frustum = new THREE.Frustum();
  const projection = new THREE.Matrix4();
  const residentCenter = new THREE.Vector3();
  function residentColor(resident, role) {
    const field = { clothes: 'color', clothing: 'color', skin: 'skin_color', trousers: 'trouser_color', backpack: 'bag_color', bag: 'bag_color' }[role] || role;
    return resident[field] || resident.color;
  }
  function updateCrowdColors() {
    for (let partIndex = 0; partIndex < crowdMeshes.length; partIndex++) {
      const object = crowdMeshes[partIndex];
      residents.forEach((entry, i) => {
        instanceColor.setRGB(...residentColor(entry.resident, scene.character.parts[partIndex].color_role));
        if (entry.resident.id === selected?.id) instanceColor.lerp(new THREE.Color('#ffff87'), 0.65);
        object.setColorAt(i, instanceColor);
      });
      if (object.instanceColor) object.instanceColor.needsUpdate = true;
    }
  }
  async function setPopulation(population) {
    if (!Array.isArray(population) || !population.length) throw new Error('Population must contain residents');
    for (const object of crowdMeshes) {
      world.remove(object);
      pickables.splice(pickables.indexOf(object), 1);
      object.dispose();
    }
    residents = population.map(resident => ({ resident, sample: sampleResident(scene, resident, simulationTime) }));
    crowdMeshes = partGeometry.map((geometry, i) => {
      const object = new THREE.InstancedMesh(geometry, crowdMaterial, residents.length);
      object.name = `residents-${scene.character.parts[i].id || i}`;
      object.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      object.castShadow = true;
      object.receiveShadow = true;
      object.frustumCulled = false;
      // Routes stay inside district bounds, so this remains valid as instances move.
      object.boundingSphere = new THREE.Sphere(new THREE.Vector3(), extent * 3);
      object.userData.residentPart = true;
      world.add(object);
      pickables.push(object);
      return object;
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
    camera.updateMatrixWorld();
    projection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    frustum.setFromProjectionMatrix(projection);
    visibleResidentCount = 0;
    residents.forEach((entry, i) => {
      residentCenter.copy(vector(entry.sample.position));
      residentCenter.y += scene.character.height / 2;
      if (frustum.containsPoint(residentCenter)) visibleResidentCount++;
      const distance = residentCenter.distanceToSquared(camera.position);
      if (distance <= 80 * 80) nearby.push({ i, distance });
    });
    nearby.sort((a, b) => a.distance - b.distance || a.i - b.i);
    animated.clear();
    for (const entry of nearby.slice(0, 300)) animated.add(entry.i);
    animatedResidentCount = animated.size;
    residents.forEach((entry, i) => {
      const { position, heading } = entry.sample;
      const cosHeading = Math.cos(heading), sinHeading = Math.sin(heading);
      headingQuaternion.setFromAxisAngle(up, heading);
      const gait = animated.has(i) ? sampleGait(entry.resident, simulationTime) : 0;
      scene.character.parts.forEach((part, partIndex) => {
        const angle = (part.swing || 0) * gait;
        const pivot = part.pivot || part.center;
        const dx = part.center[0] - pivot[0], dz = part.center[2] - pivot[2];
        const x = pivot[0] + Math.cos(angle) * dx + Math.sin(angle) * dz;
        const y = part.center[1];
        const z = pivot[2] - Math.sin(angle) * dx + Math.cos(angle) * dz;
        transform.position.set(position[0] + cosHeading * x - sinHeading * y,
          position[2] + z, -(position[1] + sinHeading * x + cosHeading * y));
        swingQuaternion.setFromAxisAngle(forward, -angle);
        transform.quaternion.copy(headingQuaternion).multiply(swingQuaternion);
        transform.updateMatrix();
        crowdMeshes[partIndex].setMatrixAt(i, transform.matrix);
      });
    });
    for (const object of crowdMeshes) object.instanceMatrix.needsUpdate = true;
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
    drag = { x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY, distance: 0 };
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
      walkPitch = THREE.MathUtils.clamp(walkPitch - dy * 0.004, -1.35, 1.35);
      aimWalk();
    }
  });
  const raycaster = new THREE.Raycaster();
  listen(canvas, 'pointerup', (event) => {
    if (!drag) return;
    const shouldPick = drag.distance < 5;
    drag = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!shouldPick) return;
    const bounds = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(
      (event.clientX - bounds.left) / bounds.width * 2 - 1,
      -(event.clientY - bounds.top) / bounds.height * 2 + 1,
    ), camera);
    const hit = raycaster.intersectObjects(pickables, false)[0];
    if (!hit) return;
    if (selected) for (const surface of objectMaterials.get(selected.id) || []) surface.emissive.setHex(0);
    const resident = hit.object.userData.residentPart ? residents[hit.instanceId]?.resident : null;
    selected = resident ? { id: resident.id, label: resident.label, type: 'resident' } : hit.object.userData.selection;
    if (!selected) return;
    for (const surface of objectMaterials.get(selected.id) || []) surface.emissive.setRGB(0.12, 0.2, 0.2);
    updateCrowdColors();
    onSelect(selected);
  });
  listen(canvas, 'pointercancel', () => { drag = null; });

  function aimWalk() {
    walkPosition[2] = walkingEyeHeight(scene, walkPosition[0], walkPosition[1]);
    camera.position.copy(vector(walkPosition));
    camera.lookAt(camera.position.clone().add(new THREE.Vector3(
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
    camera.position.copy(target).add(new THREE.Vector3(
      Math.cos(yaw) * Math.cos(pitch) * distance,
      Math.sin(pitch) * distance,
      -Math.sin(yaw) * Math.cos(pitch) * distance,
    ));
    orbit.target.copy(target);
    orbit.update();
  }
  function follow() {
    const resident = residents.find((entry) => entry.resident.id === selected?.id) || residents[0];
    if (!resident) return;
    const { position, heading } = resident.sample;
    camera.position.copy(vector([
      position[0] - Math.cos(heading) * 13,
      position[1] - Math.sin(heading) * 13,
      position[2] + 8,
    ]));
    camera.lookAt(vector([position[0], position[1], position[2] + 2]));
  }
  function setMode(nextMode) {
    if (!['orbit', 'walk', 'follow'].includes(nextMode)) throw new Error(`Unknown camera mode: ${nextMode}`);
    mode = nextMode;
    camera.near = mode === 'orbit' ? 1 : 0.1;
    camera.updateProjectionMatrix();
    keys.clear();
    drag = null;
    orbit.enabled = mode === 'orbit';
    if (mode === 'orbit') resetOrbit();
    if (mode === 'walk') resetWalk();
    if (mode === 'follow') follow();
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
  function resize() {
    const { width, height } = canvas.getBoundingClientRect();
    renderer.setSize(Math.max(1, width), Math.max(1, height), false);
    camera.aspect = Math.max(1, width) / Math.max(1, height);
    camera.updateProjectionMatrix();
  }
  function update(time, dt) {
    simulationTime = time;
    for (const entry of residents) {
      entry.sample = sampleResident(scene, entry.resident, time);
    }
    if (mode === 'orbit') orbit.update();
    if (mode === 'walk') moveWalk(dt);
    if (mode === 'follow') follow();
    updateCrowd();
    renderer.render(world, camera);
  }
  resize();
  setMode('orbit');
  await setPopulation(scene.residents);
  return {
    update, setMode, resize, setPopulation,
    resetCamera() { setMode(mode); },
    getState() {
      const firstMatrix = new THREE.Matrix4();
      crowdMeshes[0]?.getMatrixAt(0, firstMatrix);
      const sampleAnimatedIndex = animated.values().next().value;
      const limbMatrix = new THREE.Matrix4();
      if (sampleAnimatedIndex !== undefined) crowdMeshes[2].getMatrixAt(sampleAnimatedIndex, limbMatrix);
      return {
        mode, simulationTime,
        residentCount: residents.length, visibleResidentCount, animatedResidentCount,
        assetLoaded: true, importedMeshCount,
        residentPartCount: residents.length * 7,
        sampleAnimatedResidentId: residents[sampleAnimatedIndex]?.resident.id || null,
        sampleGaitAngle: sampleAnimatedIndex === undefined ? 0 : Math.atan2(-limbMatrix.elements[1], limbMatrix.elements[5]),
        sampleResidentPosition: residents.length ? [firstMatrix.elements[12], -firstMatrix.elements[14], firstMatrix.elements[13] - scene.character.parts[0].center[2]] : null,
        cameraPosition: [camera.position.x, -camera.position.z, camera.position.y],
        selectedId: selected?.id || null,
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
      };
    },
    dispose() {
      for (const remove of listeners) remove();
      orbit.dispose();
      for (const object of crowdMeshes) object.dispose();
      for (const geometry of geometries) geometry.dispose();
      for (const surface of materials) surface.dispose();
      renderer.dispose();
    },
  };
}
