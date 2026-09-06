import {
  Deck, OrbitView, FirstPersonView, COORDINATE_SYSTEM,
  AmbientLight, DirectionalLight, LightingEffect,
} from '@deck.gl/core';
import { SimpleMeshLayer } from '@deck.gl/mesh-layers';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { Matrix4 } from 'three';
import { canWalk, sampleResident, walkingEyeHeight } from '../common.js';

// All views deliberately omit longitude/latitude: fixture XYZ stays in local meters.
// https://deck.gl/docs/api-reference/core/orbit-view
// https://deck.gl/docs/api-reference/core/first-person-view
// https://deck.gl/docs/api-reference/mesh-layers/simple-mesh-layer
const radians = (degrees) => degrees * Math.PI / 180;
const degrees = (angle) => angle * 180 / Math.PI;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

function meshBuilder() {
  const positions = [], normals = [];
  return {
    triangle(a, b, c, na, nb = na, nc = na) {
      positions.push(...a, ...b, ...c);
      normals.push(...na, ...nb, ...nc);
    },
    finish() {
      return { attributes: {
        POSITION: { size: 3, value: new Float32Array(positions) },
        NORMAL: { size: 3, value: new Float32Array(normals) },
      } };
    },
  };
}

function boxMesh() {
  const mesh = meshBuilder();
  for (let axis = 0; axis < 3; axis++) {
    for (const sign of [-1, 1]) {
      const normal = [0, 0, 0];
      normal[axis] = sign;
      const points = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) => {
        const point = [0, 0, 0];
        point[axis] = sign * 0.5;
        point[(axis + 1) % 3] = u * 0.5;
        point[(axis + 2) % 3] = v * 0.5;
        return point;
      });
      if (sign < 0) points.reverse();
      mesh.triangle(points[0], points[1], points[2], normal);
      mesh.triangle(points[0], points[2], points[3], normal);
    }
  }
  return mesh.finish();
}

function sphereMesh(slices = 24, stacks = 16) {
  const mesh = meshBuilder();
  const point = (latitude, longitude) => [
    Math.sin(latitude) * Math.cos(longitude),
    Math.sin(latitude) * Math.sin(longitude), Math.cos(latitude),
  ];
  for (let stack = 0; stack < stacks; stack++) {
    for (let slice = 0; slice < slices; slice++) {
      const a = point(stack * Math.PI / stacks, slice * Math.PI * 2 / slices);
      const b = point((stack + 1) * Math.PI / stacks, slice * Math.PI * 2 / slices);
      const c = point((stack + 1) * Math.PI / stacks, (slice + 1) * Math.PI * 2 / slices);
      const d = point(stack * Math.PI / stacks, (slice + 1) * Math.PI * 2 / slices);
      mesh.triangle(a, b, c, a, b, c);
      mesh.triangle(a, c, d, a, c, d);
    }
  }
  return mesh.finish();
}

function cylinderMesh(slices = 24) {
  const mesh = meshBuilder();
  for (let slice = 0; slice < slices; slice++) {
    const angleA = slice * Math.PI * 2 / slices;
    const angleB = (slice + 1) * Math.PI * 2 / slices;
    const normalA = [Math.cos(angleA), Math.sin(angleA), 0];
    const normalB = [Math.cos(angleB), Math.sin(angleB), 0];
    const a = [normalA[0], normalA[1], -0.5];
    const b = [normalB[0], normalB[1], -0.5];
    const c = [normalB[0], normalB[1], 0.5];
    const d = [normalA[0], normalA[1], 0.5];
    mesh.triangle(a, b, c, normalA, normalB, normalB);
    mesh.triangle(a, c, d, normalA, normalB, normalA);
    mesh.triangle([0, 0, 0.5], d, c, [0, 0, 1]);
    mesh.triangle([0, 0, -0.5], b, a, [0, 0, -1]);
  }
  return mesh.finish();
}

async function loadCityAsset(scene) {
  if (!scene.asset?.url) throw new Error('deck.gl requires the round-two City Hall GLB asset.');
  const asset = await new GLTFLoader().loadAsync(scene.asset.url);
  asset.scene.updateMatrixWorld(true);
  const groups = new Map();
  const conversion = new Matrix4().makeRotationX(Math.PI / 2);
  let importedMeshCount = 0;
  asset.scene.traverse((object) => {
    if (!object.isMesh) return;
    importedMeshCount++;
    let metadata = object;
    while (metadata && !metadata.userData?.id) metadata = metadata.parent;
    const selection = metadata?.userData || { id: object.name, label: object.name, type: 'feature' };
    const group = groups.get(selection.id) || {
      id: selection.id, label: selection.label || selection.id, type: selection.type || 'building',
      positions: [], normals: [], colors: [],
    };
    const geometry = object.geometry.clone().applyMatrix4(conversion.clone().multiply(object.matrixWorld));
    if (!geometry.attributes.normal) geometry.computeVertexNormals();
    const flattened = geometry.index ? geometry.toNonIndexed() : geometry;
    const position = flattened.attributes.position;
    const normal = flattened.attributes.normal;
    const vertexColor = flattened.attributes.color;
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if (material.map) throw new Error('deck.gl color-baked City Hall import requires material colors without image textures.');
    }
    for (let i = 0; i < position.count; i++) {
      const materialGroup = flattened.groups.find((entry) => i >= entry.start && i < entry.start + entry.count);
      const material = materials[materialGroup?.materialIndex || 0];
      group.positions.push(position.getX(i), position.getY(i), position.getZ(i));
      group.normals.push(normal.getX(i), normal.getY(i), normal.getZ(i));
      group.colors.push(
        (material.color?.r ?? 1) * (vertexColor?.getX(i) ?? 1),
        (material.color?.g ?? 1) * (vertexColor?.getY(i) ?? 1),
        (material.color?.b ?? 1) * (vertexColor?.getZ(i) ?? 1),
      );
    }
    if (flattened !== geometry) flattened.dispose();
    geometry.dispose();
    groups.set(selection.id, group);
  });
  asset.scene.traverse((object) => {
    object.geometry?.dispose();
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) material?.dispose();
  });
  if (!importedMeshCount) throw new Error('City Hall GLB contains no renderable meshes.');
  return { importedMeshCount, groups: [...groups.values()].map((group) => ({
    selection: { id: group.id, label: group.label, type: group.type },
    mesh: { attributes: {
      POSITION: { size: 3, value: new Float32Array(group.positions) },
      NORMAL: { size: 3, value: new Float32Array(group.normals) },
      COLOR_0: { size: 3, value: new Float32Array(group.colors) },
    } },
  })) };
}

function characterMatrix(part, resident, time, animate) {
  const heading = resident.sample.heading;
  const angle = animate && part.swing ? part.swing * Math.sin(2 * Math.PI * (1.6 * time + resident.phase)) * 0.55 : 0;
  const ca = Math.cos(angle), sa = Math.sin(angle), ch = Math.cos(heading), sh = Math.sin(heading);
  const pivot = part.pivot || part.center;
  const offset = part.center.map((v, i) => v - pivot[i]);
  const local = [pivot[0] + ca * offset[0] + sa * offset[2], pivot[1] + offset[1], pivot[2] - sa * offset[0] + ca * offset[2]];
  const scale = part.size || [part.radius, part.radius, part.radius];
  if (part.id === 'left-arm') resident.renderedGaitAngle = angle;
  return [
    ch * ca * scale[0], sh * ca * scale[0], -sa * scale[0], 0,
    -sh * scale[1], ch * scale[1], 0, 0,
    ch * sa * scale[2], sh * sa * scale[2], ca * scale[2], 0,
    ch * local[0] - sh * local[1], sh * local[0] + ch * local[1], local[2], 1,
  ];
}

export async function createViewer({ canvas, scene, onSelect = () => {} }) {
  const meshes = { box: boxMesh(), sphere: sphereMesh(8, 6), cylinder: cylinderMesh() };
  const asset = await loadCityAsset(scene);
  if (scene.character?.parts?.length !== 7) throw new Error('deck.gl requires the shared seven-part character contract.');
  let residents = scene.residents.map((resident, index) => ({
    ...resident, index, sample: sampleResident(scene, resident, 0),
  }));
  let animated = new Set();
  let visibleResidentCount = 0;
  let detailRevision = 0;
  let staticLayers = null;
  let staticSelectionId = null;
  const previousBackground = canvas.style.backgroundColor;
  canvas.style.backgroundColor = '#b9d4df';
  const effects = [new LightingEffect({
    ambient: new AmbientLight({ color: [237, 247, 255], intensity: 0.85 }),
    sunlight: new DirectionalLight({ color: [255, 243, 216], intensity: 1.1, direction: [0.5, -0.45, -1] }),
  })];
  const material = { ambient: 0.65, diffuse: 0.8, shininess: 16, specularColor: [20, 20, 20] };
  let mode = 'orbit';
  let selected = null;
  let simulationTime = 0;
  let disposed = false;
  let renderError = null;
  let framesRendered = 0;
  let deck;
  let orbitState;
  let cameraState;
  let drag = null;
  let lastHeight = Math.max(1, canvas.getBoundingClientRect().height);
  const walkPosition = [...scene.camera.walk_position];
  let walkYaw = 0;
  let walkPitch = radians(scene.camera.walk_pitch_degrees ?? 18);
  const keys = new Set();
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
    if (mode !== 'walk' || event.button !== 0) return;
    drag = { x: event.clientX, y: event.clientY };
    canvas.setPointerCapture(event.pointerId);
  });
  listen(canvas, 'pointermove', (event) => {
    if (mode !== 'walk' || !drag) return;
    walkYaw -= (event.clientX - drag.x) * 0.004;
    walkPitch = clamp(walkPitch - (event.clientY - drag.y) * 0.004, -1.35, 1.35);
    drag = { x: event.clientX, y: event.clientY };
  });
  listen(canvas, 'pointerup', (event) => {
    drag = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  });
  listen(canvas, 'pointercancel', () => { drag = null; });

  function color(object, role = 'clothing') {
    if (selected?.id === object.id) return [90, 222, 230, 255];
    const source = role === 'skin' ? object.skin_color : role === 'trousers' || role === 'trouser' ? object.trouser_color
      : role === 'backpack' || role === 'bag' ? object.bag_color : object.color;
    return [...(source || object.color).map((channel) => Math.round(channel * 255)), 255];
  }
  function layers() {
    const shared = {
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      pickable: true, autoHighlight: true, highlightColor: [110, 225, 255, 90],
      getColor: color, material,
      getPolygonOffset: () => [0, 0],
      parameters: { cullMode: 'none' },
    };
    if (!staticLayers || staticSelectionId !== selected?.id) {
      staticSelectionId = selected?.id;
      staticLayers = asset.groups.map(({ selection, mesh }) => new SimpleMeshLayer({
        ...shared, id: `asset-${selection.id}`, data: [selection], mesh,
        getPosition: [0, 0, 0], getColor: selected?.id === selection.id ? [150, 235, 255, 255] : [255, 255, 255, 255],
        updateTriggers: { getColor: selected?.id },
      }));
    }
    return [
      ...staticLayers,
      ...scene.character.parts.map((part, partIndex) => new SimpleMeshLayer({
        ...shared, id: `resident-part-${partIndex}`, data: residents, mesh: meshes[part.kind],
        getPosition: (resident) => resident.sample.position,
        getTransformMatrix: (resident) => characterMatrix(part, resident, simulationTime, animated.has(resident.index)),
        getColor: (resident) => color(resident, part.color_role),
        updateTriggers: { getPosition: simulationTime, getTransformMatrix: [simulationTime, detailRevision], getColor: selected?.id },
      })),
    ];
  }

  function resetOrbit() {
    const height = Math.max(1, canvas.getBoundingClientRect().height);
    const focalDistance = 1 / (2 * Math.tan(radians(55) / 2));
    orbitState = {
      target: [...scene.camera.target],
      zoom: Math.log2(height * focalDistance / scene.camera.distance),
      rotationX: scene.camera.pitch_degrees,
      rotationOrbit: -90 - scene.camera.yaw_degrees,
      minRotationX: 2, maxRotationX: 89, minZoom: -3, maxZoom: 7,
    };
    cameraState = orbitState;
  }
  function aimWalk() {
    cameraState = { position: [...walkPosition], bearing: 90 - degrees(walkYaw), pitch: -degrees(walkPitch) };
  }
  function resetWalk() {
    walkPosition.splice(0, 3, ...scene.camera.walk_position);
    walkYaw = Math.atan2(scene.camera.target[1] - walkPosition[1], scene.camera.target[0] - walkPosition[0]);
    walkPitch = radians(scene.camera.walk_pitch_degrees ?? 18);
    aimWalk();
  }
  function follow() {
    const resident = residents.find((entry) => entry.id === selected?.id) || residents[0];
    if (!resident) return;
    const { position, heading } = resident.sample;
    cameraState = {
      position: [position[0] - Math.cos(heading) * 13, position[1] - Math.sin(heading) * 13, position[2] + 8],
      bearing: 90 - degrees(heading), pitch: degrees(Math.atan2(6, 13)),
    };
  }
  function applyView() {
    const view = mode === 'orbit'
      ? new OrbitView({ id: 'city', orbitAxis: 'Z', fovy: 55, near: 0.001, far: 1000,
        controller: { dragMode: 'rotate', keyboard: false, doubleClickZoom: false } })
      : new FirstPersonView({ id: 'city', fovy: 55, near: 0.1, far: 5000, controller: false });
    deck?.setProps({ views: view, viewState: cameraState });
  }
  function setMode(nextMode) {
    if (!['orbit', 'walk', 'follow'].includes(nextMode)) throw new Error(`Unknown camera mode: ${nextMode}`);
    mode = nextMode;
    keys.clear();
    drag = null;
    if (mode === 'orbit') resetOrbit();
    if (mode === 'walk') resetWalk();
    if (mode === 'follow') follow();
    applyView();
  }
  function moveWalk(dt) {
    const step = clamp(dt, 0, 0.05);
    walkYaw += (Number(keys.has('ArrowLeft')) - Number(keys.has('ArrowRight'))) * step * 1.7;
    const forward = Number(keys.has('KeyW') || keys.has('ArrowUp')) - Number(keys.has('KeyS') || keys.has('ArrowDown'));
    const side = Number(keys.has('KeyD')) - Number(keys.has('KeyA'));
    const norm = Math.hypot(forward, side) || 1;
    const speed = keys.has('ShiftLeft') || keys.has('ShiftRight') ? 22 : 9;
    const dx = (Math.cos(walkYaw) * forward + Math.sin(walkYaw) * side) / norm * speed * step;
    const dy = (Math.sin(walkYaw) * forward - Math.cos(walkYaw) * side) / norm * speed * step;
    if (canWalk(scene, walkPosition[0] + dx, walkPosition[1])) walkPosition[0] += dx;
    if (canWalk(scene, walkPosition[0], walkPosition[1] + dy)) walkPosition[1] += dy;
    walkPosition[2] = walkingEyeHeight(scene, walkPosition[0], walkPosition[1]);
    aimWalk();
  }
  function resize() {
    const { width, height } = canvas.getBoundingClientRect();
    const nextHeight = Math.max(1, height);
    if (orbitState) orbitState.zoom += Math.log2(nextHeight / lastHeight);
    lastHeight = nextHeight;
    deck?.setProps({ width: Math.max(1, width), height: nextHeight, viewState: cameraState });
  }
  function update(time, dt) {
    if (disposed) return;
    if (renderError) throw renderError;
    simulationTime = time;
    for (const resident of residents) resident.sample = sampleResident(scene, resident, time);
    if (mode === 'walk') moveWalk(dt);
    if (mode === 'follow') follow();
    deck.setProps({ viewState: cameraState });
    updateDetail();
    deck.setProps({ layers: layers(), viewState: cameraState });
    // The shared shell owns the clock; deck.gl still schedules its own GPU redraw.
    deck.redraw('comparison frame');
  }
  function updateDetail() {
    const viewport = deck.getViewports()[0];
    if (!viewport) return;
    const camera = mode === 'orbit' ? viewport.cameraPosition : cameraState.position;
    const nearby = [];
    visibleResidentCount = 0;
    const m = viewport.viewProjectionMatrix;
    for (const resident of residents) {
      const position = resident.sample.position;
      const distance = Math.hypot(...position.map((v, i) => v - camera[i]));
      if (distance <= 80) nearby.push({ index: resident.index, distance });
      const [x, y, z] = viewport.projectPosition([position[0], position[1], position[2] + 0.9]);
      const clip = [0, 1, 2, 3].map((row) => m[row] * x + m[row + 4] * y + m[row + 8] * z + m[row + 12]);
      if (clip[3] > 0 && clip.slice(0, 3).every((value) => Math.abs(value) <= clip[3])) visibleResidentCount++;
    }
    nearby.sort((a, b) => a.distance - b.distance || a.index - b.index);
    const next = new Set(nearby.slice(0, 300).map((entry) => entry.index));
    if (next.size !== animated.size || [...next].some((index) => !animated.has(index))) detailRevision++;
    animated = next;
  }
  async function setPopulation(population) {
    const next = population.map((resident, index) => ({ ...resident, index, sample: sampleResident(scene, resident, simulationTime) }));
    residents = next;
    if (selected?.type === 'resident' && !residents.some((resident) => resident.id === selected.id)) {
      selected = null;
      onSelect(null);
    }
    detailRevision++;
    update(simulationTime, 0);
    await new Promise(requestAnimationFrame);
    deck.redraw('population updated');
    if (renderError) throw renderError;
  }

  resetOrbit();
  await new Promise((resolve, reject) => {
    deck = new Deck({
      canvas, width: Math.max(1, canvas.clientWidth), height: lastHeight,
      useDevicePixels: Math.min(window.devicePixelRatio || 1, 2),
      views: new OrbitView({ id: 'city', orbitAxis: 'Z', fovy: 55, near: 0.001, far: 1000,
        controller: { dragMode: 'rotate', keyboard: false, doubleClickZoom: false } }),
      viewState: orbitState, layers: layers(), effects,
      onViewStateChange: ({ viewState }) => {
        if (mode !== 'orbit') return;
        orbitState = viewState;
        cameraState = orbitState;
        deck.setProps({ viewState: cameraState });
      },
      onClick: ({ object }) => {
        if (!object) return;
        selected = { id: object.id, label: object.label,
          type: object.route_id ? 'resident' : object.type || 'feature' };
        onSelect(selected);
      },
      getCursor: ({ isDragging, isHovering }) => isDragging ? 'grabbing' : isHovering ? 'pointer' : mode === 'walk' ? 'crosshair' : 'grab',
      onLoad: resolve,
      onAfterRender: () => { framesRendered++; },
      onError: (error) => { renderError = error; reject(error); },
    });
  });
  resize();
  update(0, 0);
  return {
    update, setMode, resize, setPopulation,
    resetCamera() { setMode(mode); },
    getState() {
      const viewport = deck.getViewports()[0];
      const animatedSample = residents.find((entry) => animated.has(entry.index) && entry.id === selected?.id)
        || residents.find((entry) => animated.has(entry.index));
      return {
        mode, simulationTime, primitiveCount: scene.primitives.length,
        residentCount: residents.length, sampleResidentPosition: residents[0] ? [...residents[0].sample.position] : null,
        visibleResidentCount, animatedResidentCount: animated.size,
        assetLoaded: true, assetMeshCount: asset.importedMeshCount, characterPartCount: scene.character.parts.length,
        sampleAnimatedResidentId: animatedSample?.id || null,
        sampleGaitAngle: animatedSample?.renderedGaitAngle ?? 0,
        cameraPosition: mode === 'orbit' ? Array.from(viewport?.cameraPosition || []) : [...cameraState.position],
        selectedId: selected?.id || null, framesRendered,
        renderedLayers: deck.props.layers.length,
        renderedInstances: asset.groups.length + residents.length * scene.character.parts.length,
        renderError: renderError?.message || null,
      };
    },
    dispose() {
      disposed = true;
      for (const remove of listeners) remove();
      deck.finalize();
      canvas.style.backgroundColor = previousBackground;
    },
  };
}
