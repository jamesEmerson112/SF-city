import {
  Axis, BoundingSphere, BoxGeometry, Cartesian2, Cartesian3, Color,
  ColorGeometryInstanceAttribute, ComponentDatatype, DirectionalLight, EllipsoidGeometry,
  Geometry, GeometryAttribute, GeometryInstance, GeometryInstanceAttribute, Intersect,
  JulianDate, Matrix4, Model, PerInstanceColorAppearance, Primitive, PrimitiveType,
  ScreenSpaceEventType, ShadowMode, Transforms, Viewer,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { canWalk, sampleResident, walkingEyeHeight } from '../common.js';

const radians = (degrees) => degrees * Math.PI / 180;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const glslNumber = (value) => Number(value).toFixed(10);
const glslVector = (values) => `vec3(${values.map(glslNumber).join(',')})`;

function characterGeometry(scene) {
  const positions = [], normals = [], partIndices = [], indices = [];
  scene.character.parts.forEach((part, partIndex) => {
    const options = { vertexFormat: PerInstanceColorAppearance.VERTEX_FORMAT };
    const geometry = part.kind === 'box'
      ? BoxGeometry.createGeometry(BoxGeometry.fromDimensions({ ...options, dimensions: new Cartesian3(...part.size) }))
      : part.kind === 'sphere' ? EllipsoidGeometry.createGeometry(new EllipsoidGeometry({
        ...options, radii: new Cartesian3(part.radius, part.radius, part.radius), stackPartitions: 6, slicePartitions: 8,
      })) : null;
    if (!geometry) throw new Error(`Cesium character part kind ${part.kind} is unsupported.`);
    const offset = positions.length / 3;
    const source = geometry.attributes.position.values;
    for (let i = 0; i < source.length; i += 3) {
      positions.push(source[i] + part.center[0], source[i + 1] + part.center[1], source[i + 2] + part.center[2]);
      partIndices.push(partIndex);
    }
    normals.push(...geometry.attributes.normal.values);
    for (const index of geometry.indices) indices.push(index + offset);
  });
  return new Geometry({
    attributes: {
      position: new GeometryAttribute({ componentDatatype: ComponentDatatype.DOUBLE, componentsPerAttribute: 3, values: new Float64Array(positions) }),
      normal: new GeometryAttribute({ componentDatatype: ComponentDatatype.FLOAT, componentsPerAttribute: 3, values: new Float32Array(normals) }),
      partIndex: new GeometryAttribute({ componentDatatype: ComponentDatatype.FLOAT, componentsPerAttribute: 1, values: new Float32Array(partIndices) }),
    },
    indices: new Uint16Array(indices), primitiveType: PrimitiveType.TRIANGLES,
    // The vertex shader moves the people over every route. Include their entire
    // travel area in the bounds rather than culling their origin-only geometry.
    boundingSphere: new BoundingSphere(Cartesian3.ZERO, Math.hypot(...scene.bounds.max) + 10),
  });
}

function crowdVertexShader(scene) {
  const routeCode = scene.routes.map((route, routeIndex) => {
    const lengths = route.points.slice(1).map((p, i) => Math.hypot(...p.map((v, j) => v - route.points[i][j])));
    const total = lengths.reduce((a, b) => a + b, 0);
    return `if (routeIndex < ${routeIndex + 0.5}) {
      float distance = fract(u_time / ${glslNumber(route.duration)} + phase) * ${glslNumber(total)};
      ${lengths.map((length, i) => {
        const a = route.points[i], b = route.points[i + 1];
        return `if (distance <= ${glslNumber(length)} ${i === lengths.length - 1 ? '|| true' : ''}) {
          position = mix(${glslVector(a)}, ${glslVector(b)}, distance / ${glslNumber(length)});
          heading = ${glslNumber(Math.atan2(b[1] - a[1], b[0] - a[0]))}; return;
        } distance -= ${glslNumber(length)};`;
      }).join('\n')}
    }`;
  }).join('\n');
  const partCode = scene.character.parts.map((part, i) => `if (partIndex > ${i - 0.5} && partIndex < ${i + 0.5}) {
    pivot = ${glslVector(part.pivot || part.center)}; swing = ${glslNumber(part.swing || 0)};
    role = ${part.color_role === 'skin' ? '1.0' : part.color_role === 'trousers' ? '2.0' : part.color_role === 'bag' ? '3.0' : '0.0'};
  }`).join('\n');
  return `
    in vec3 position3DHigh; in vec3 position3DLow; in vec3 normal;
    in float batchId; in float partIndex;
    uniform float u_time; uniform float u_selected; uniform float u_visible;
    out vec3 v_positionEC; out vec3 v_normalEC; out vec4 v_color;
    void routePosition(float routeIndex, float phase, out vec3 position, out float heading) {
      ${routeCode}
      position = vec3(0.0); heading = 0.0;
    }
    void main() {
      vec4 person = czm_batchTable_person(batchId);
      vec3 route; float heading;
      routePosition(person.x, person.y, route, heading);
      vec3 pivot = vec3(0.0); float swing = 0.0; float role = 0.0;
      ${partCode}
      float angle = swing * sin(6.28318530718 * (1.6 * u_time + person.y)) * 0.55 * czm_batchTable_gait(batchId);
      float ca = cos(angle), sa = sin(angle), ch = cos(heading), sh = sin(heading);
      mat3 ry = mat3(ca, 0.0, -sa, 0.0, 1.0, 0.0, sa, 0.0, ca);
      mat3 rz = mat3(ch, sh, 0.0, -sh, ch, 0.0, 0.0, 0.0, 1.0);
      vec3 original = position3DHigh + position3DLow;
      vec3 animated = rz * (pivot + ry * (original - pivot)) + route;
      vec4 p = czm_computePosition();
      p.xyz += animated - original;
      v_positionEC = (czm_modelViewRelativeToEye * p).xyz;
      v_normalEC = czm_normal * (rz * ry * normal);
      v_color = role < 0.5 ? czm_batchTable_color(batchId) : role < 1.5 ? czm_batchTable_skin(batchId)
        : role < 2.5 ? czm_batchTable_trousers(batchId) : czm_batchTable_bag(batchId);
      if (abs(person.z - u_selected) < 0.1) v_color = vec4(1.0, 0.82, 0.4, 1.0);
      gl_Position = czm_modelViewProjectionRelativeToEye * p;
      if (u_visible < 0.5) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    }
  `;
}

// Offline fixture: positions are meters in a single east/north/up frame at City Hall.
// No imagery, terrain provider, ion token, geocoder, or network tiles are requested.
export async function createViewer({ canvas, scene, onSelect = () => {} }) {
  if (!scene.asset?.url || scene.character?.parts?.length !== 7) throw new Error('Cesium requires the City Hall GLB and shared seven-part characters.');
  const container = document.createElement('div');
  container.className = 'cesium-comparison-view';
  Object.assign(container.style, { position: 'absolute', inset: '0', width: '100%', height: '100%' });
  const previousDisplay = canvas.style.display;
  canvas.style.display = 'none';
  canvas.after(container);
  let viewer;
  try {
    viewer = new Viewer(container, {
      animation: false, timeline: false, baseLayerPicker: false, baseLayer: false,
      geocoder: false, homeButton: false, sceneModePicker: false,
      navigationHelpButton: false, fullscreenButton: false,
      infoBox: false, selectionIndicator: false, globe: false,
      skyBox: false, skyAtmosphere: false, shouldAnimate: false,
      useDefaultRenderLoop: false, shadows: true, scene3DOnly: true,
      contextOptions: { webgl: { alpha: false, antialias: true, preserveDrawingBuffer: true } },
    });
  } catch (error) {
    container.remove();
    canvas.style.display = previousDisplay;
    throw error;
  }
  const origin = Cartesian3.fromDegrees(scene.origin.longitude, scene.origin.latitude);
  const frame = Transforms.eastNorthUpToFixedFrame(origin);
  const inverseFrame = Matrix4.inverseTransformation(frame, new Matrix4());
  const worldPoint = ([x, y, z]) => Matrix4.multiplyByPoint(frame, new Cartesian3(x, y, z), new Cartesian3());
  const worldDirection = ([x, y, z]) => Matrix4.multiplyByPointAsVector(frame, new Cartesian3(x, y, z), new Cartesian3());
  const localPoint = (point) => {
    const result = Matrix4.multiplyByPoint(inverseFrame, point, new Cartesian3());
    return [result.x, result.y, result.z];
  };
  viewer.scene.backgroundColor = Color.fromCssColorString('#b9d4df');
  viewer.scene.rethrowRenderErrors = true;
  viewer.scene.fog.enabled = false;
  if (viewer.scene.sun) viewer.scene.sun.show = false;
  if (viewer.scene.moon) viewer.scene.moon.show = false;
  viewer.scene.screenSpaceCameraController.enableInputs = false;
  viewer.scene.highDynamicRange = false;
  viewer.scene.light = new DirectionalLight({
    direction: Cartesian3.normalize(worldDirection([0.5, 0.3, -0.8]), new Cartesian3()),
    color: Color.fromCssColorString('#fff3d8'), intensity: 1.8,
  });
  viewer.shadowMap.maximumDistance = 1600;
  viewer.shadowMap.size = 2048;
  viewer.camera.frustum.near = 0.1;
  viewer.camera.frustum.far = 6000;
  viewer.camera.frustum.fov = radians(55);
  // Fix Cesium's lighting/time so the comparison clock only moves the residents.
  viewer.clock.currentTime = JulianDate.fromIso8601('2026-09-05T19:00:00Z');
  viewer.clock.shouldAnimate = false;
  // The comparison shell supplies selection and navigation instead of Viewer defaults.
  viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_CLICK);
  viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  const assetSelections = new Map();
  let assetMeshCount = 0;
  let model;
  try {
    model = await Model.fromGltfAsync({
      url: scene.asset.url, modelMatrix: frame, upAxis: Axis.Y, forwardAxis: Axis.X,
      shadows: ShadowMode.ENABLED, incrementallyLoadTextures: false,
      gltfCallback(gltf) {
        assetMeshCount = gltf.meshes?.length || 0;
        const parents = new Map();
        (gltf.nodes || []).forEach((node, index) => { for (const child of node.children || []) parents.set(child, index); });
        (gltf.nodes || []).forEach((node, index) => {
          let metadata = node;
          let cursor = index;
          while (!metadata.extras?.id && parents.has(cursor)) { cursor = parents.get(cursor); metadata = gltf.nodes[cursor]; }
          const extra = metadata.extras || {};
          assetSelections.set(node.name, { id: extra.id || node.name, label: extra.label || node.name, type: extra.type || 'feature' });
        });
      },
    });
    viewer.scene.primitives.add(model);
  } catch (error) {
    viewer.destroy(); container.remove(); canvas.style.display = previousDisplay;
    throw error;
  }
  const landmarkSelection = viewer.entities.add({
    show: false, position: origin, point: { pixelSize: 11, color: Color.fromCssColorString('#ffd166'), outlineWidth: 2, outlineColor: Color.BLACK },
  });
  const template = characterGeometry(scene);
  const shader = crowdVertexShader(scene);
  let residents = [];
  let crowd = null;
  let animated = new Set();
  let visibleResidentCount = 0;

  let mode = 'orbit';
  let selected = null;
  let simulationTime = 0;
  let orbitYaw = radians(scene.camera.yaw_degrees);
  let orbitPitch = radians(scene.camera.pitch_degrees);
  let orbitDistance = scene.camera.distance;
  const walkPosition = [...scene.camera.walk_position];
  let walkYaw = 0;
  let walkPitch = radians(scene.camera.walk_pitch_degrees ?? 18);
  let drag = null;
  const keys = new Set();
  const listeners = [];
  const activeCanvas = viewer.canvas;
  activeCanvas.style.touchAction = 'none';
  activeCanvas.tabIndex = 0;
  function listen(target, event, callback, options) {
    target.addEventListener(event, callback, options);
    listeners.push(() => target.removeEventListener(event, callback, options));
  }
  function aim(position, target) {
    const destination = worldPoint(position);
    const direction = Cartesian3.normalize(Cartesian3.subtract(worldPoint(target), destination, new Cartesian3()), new Cartesian3());
    viewer.camera.setView({ destination, orientation: { direction, up: worldDirection([0, 0, 1]) } });
  }
  function aimOrbit() {
    const [x, y, z] = scene.camera.target;
    aim([
      x + Math.cos(orbitYaw) * Math.cos(orbitPitch) * orbitDistance,
      y + Math.sin(orbitYaw) * Math.cos(orbitPitch) * orbitDistance,
      z + Math.sin(orbitPitch) * orbitDistance,
    ], scene.camera.target);
  }
  function aimWalk() {
    aim(walkPosition, [
      walkPosition[0] + Math.cos(walkYaw) * Math.cos(walkPitch),
      walkPosition[1] + Math.sin(walkYaw) * Math.cos(walkPitch),
      walkPosition[2] + Math.sin(walkPitch),
    ]);
  }
  function aimFollow() {
    const entry = residents.find(({ resident }) => resident.id === selected?.id) || residents[0];
    if (!entry) return;
    const { position, heading } = entry.sample;
    aim([
      position[0] - Math.cos(heading) * 13,
      position[1] - Math.sin(heading) * 13, position[2] + 8,
    ], [position[0], position[1], position[2] + 2]);
  }
  function setMode(nextMode) {
    if (!['orbit', 'walk', 'follow'].includes(nextMode)) throw new Error(`Unknown camera mode: ${nextMode}`);
    mode = nextMode;
    keys.clear();
    drag = null;
    if (mode === 'orbit') {
      orbitYaw = radians(scene.camera.yaw_degrees);
      orbitPitch = radians(scene.camera.pitch_degrees);
      orbitDistance = scene.camera.distance;
      aimOrbit();
    } else if (mode === 'walk') {
      walkPosition.splice(0, 3, ...scene.camera.walk_position);
      walkYaw = Math.atan2(scene.camera.target[1] - walkPosition[1], scene.camera.target[0] - walkPosition[0]);
      walkPitch = radians(scene.camera.walk_pitch_degrees ?? 18);
      aimWalk();
    } else aimFollow();
  }
  function select(next) {
    selected = next;
    if (crowd) crowd.appearance.uniforms.u_selected = residents.findIndex((entry) => entry.resident.id === selected?.id);
    if (selected?.type === 'resident' || !selected) landmarkSelection.show = false;
    onSelect(selected);
  }
  listen(activeCanvas, 'pointerdown', (event) => {
    if (event.button !== 0) return;
    activeCanvas.focus({ preventScroll: true });
    activeCanvas.setPointerCapture(event.pointerId);
    drag = { x: event.clientX, y: event.clientY, total: 0 };
  });
  listen(activeCanvas, 'pointermove', (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    drag.x = event.clientX;
    drag.y = event.clientY;
    drag.total += Math.hypot(dx, dy);
    if (mode === 'orbit') {
      orbitYaw -= dx * 0.005;
      orbitPitch = clamp(orbitPitch + dy * 0.005, radians(8), radians(85));
    } else if (mode === 'walk') {
      walkYaw -= dx * 0.003;
      walkPitch = clamp(walkPitch - dy * 0.003, -1.4, 1.4);
    }
  });
  listen(activeCanvas, 'pointerup', (event) => {
    if (drag && drag.total < 5) {
      const bounds = activeCanvas.getBoundingClientRect();
      const pixel = new Cartesian2(event.clientX - bounds.left, event.clientY - bounds.top);
      const pick = viewer.scene.pick(pixel);
      const resident = residents.find((entry) => entry.resident.id === pick?.id)?.resident;
      const nodeName = pick?.detail?.node?.node?.name;
      const selection = resident ? { id: resident.id, label: resident.label, type: 'resident', route: resident.route_id }
        : assetSelections.get(nodeName) || null;
      landmarkSelection.show = false;
      if (selection && !resident && viewer.scene.pickPositionSupported) {
        const position = viewer.scene.pickPosition(pixel);
        if (position) { landmarkSelection.position = position; landmarkSelection.show = true; }
      }
      select(selection);
    }
    drag = null;
    if (activeCanvas.hasPointerCapture(event.pointerId)) activeCanvas.releasePointerCapture(event.pointerId);
  });
  listen(activeCanvas, 'pointercancel', () => { drag = null; });
  listen(activeCanvas, 'wheel', (event) => {
    if (mode !== 'orbit') return;
    event.preventDefault();
    orbitDistance = clamp(orbitDistance * Math.exp(event.deltaY * 0.001), 12, 1400);
  }, { passive: false });
  listen(activeCanvas, 'contextmenu', (event) => event.preventDefault());
  listen(window, 'keydown', (event) => {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target?.tagName)) return;
    keys.add(event.code);
    if (mode === 'walk' && /^(Key[WASD]|Arrow)/.test(event.code)) event.preventDefault();
  });
  listen(window, 'keyup', (event) => keys.delete(event.code));
  listen(window, 'blur', () => { keys.clear(); drag = null; });
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
    viewer.resize();
    // Cesium defines fov on the longer viewport dimension; the fixture viewers
    // use a 55-degree vertical FOV. Convert it for wide desktop windows.
    const aspect = viewer.camera.frustum.aspectRatio;
    viewer.camera.frustum.fov = aspect > 1
      ? 2 * Math.atan(Math.tan(radians(55) / 2) * aspect) : radians(55);
  }
  function update(time, dt) {
    simulationTime = time;
    for (const entry of residents) entry.sample = sampleResident(scene, entry.resident, time);
    if (mode === 'orbit') aimOrbit();
    else if (mode === 'walk') moveWalk(dt);
    else aimFollow();
    if (crowd) {
      crowd.appearance.uniforms.u_time = time;
      updateDetail();
    }
    viewer.render();
  }
  function updateDetail() {
    const camera = localPoint(viewer.camera.positionWC);
    const frustum = viewer.camera.frustum.computeCullingVolume(viewer.camera.positionWC, viewer.camera.directionWC, viewer.camera.upWC);
    const nearby = [];
    visibleResidentCount = 0;
    const sphere = new BoundingSphere();
    for (let index = 0; index < residents.length; index++) {
      const position = residents[index].sample.position;
      const distance = Math.hypot(...position.map((value, axis) => value - camera[axis]));
      if (distance <= scene.character.animation_distance) nearby.push({ index, distance });
      sphere.center = worldPoint([position[0], position[1], position[2] + 0.9]);
      sphere.radius = 0;
      if (frustum.computeVisibility(sphere) !== Intersect.OUTSIDE) visibleResidentCount++;
    }
    nearby.sort((a, b) => a.distance - b.distance || a.index - b.index);
    const next = new Set(nearby.slice(0, scene.character.max_animated).map((entry) => entry.index));
    if (crowd.ready) {
      for (const index of animated) if (!next.has(index)) crowd.getGeometryInstanceAttributes(residents[index].resident.id).gait = new Float32Array([0]);
      for (const index of next) if (!animated.has(index)) crowd.getGeometryInstanceAttributes(residents[index].resident.id).gait = new Float32Array([1]);
      animated = next;
    }
  }
  async function setPopulation(population) {
    const entries = population.map((resident) => ({ resident, sample: sampleResident(scene, resident, simulationTime) }));
    const attribute = (values) => new GeometryInstanceAttribute({
      componentDatatype: ComponentDatatype.FLOAT, componentsPerAttribute: values.length, value: new Float32Array(values),
    });
    const colorAttribute = (color) => ColorGeometryInstanceAttribute.fromColor(new Color(...color, 1));
    const appearance = new PerInstanceColorAppearance({ translucent: false, closed: true, vertexShaderSource: shader });
    // Primitive consumes appearance.uniforms as a live uniform map (Cesium1.145).
    // Updating time moves the whole batch without rebuilding people or geometry.
    appearance.uniforms = { u_time: simulationTime, u_selected: -1, u_visible: 0 };
    const primitive = new Primitive({
      geometryInstances: entries.map(({ resident }, index) => new GeometryInstance({
        id: resident.id,
        geometry: new Geometry({
          attributes: { ...template.attributes }, indices: template.indices,
          primitiveType: template.primitiveType, boundingSphere: BoundingSphere.clone(template.boundingSphere),
        }),
        attributes: {
          color: colorAttribute(resident.color), skin: colorAttribute(resident.skin_color),
          trousers: colorAttribute(resident.trouser_color), bag: colorAttribute(resident.bag_color),
          person: attribute([scene.routes.findIndex((route) => route.id === resident.route_id), resident.phase, index, 0]),
          gait: attribute([0]),
        },
      })),
      appearance, modelMatrix: frame, asynchronous: false, compressVertices: false,
      shadows: ShadowMode.ENABLED,
    });
    viewer.scene.primitives.add(primitive);
    try {
      await new Promise((resolve, reject) => {
        const deadline = performance.now() + 45000;
        function prepare() {
          try {
            viewer.render();
            if (primitive.ready) { resolve(); return; }
            if (performance.now() > deadline) throw new Error('Cesium crowd preparation timed out.');
            requestAnimationFrame(prepare);
          } catch (error) { reject(error); }
        }
        requestAnimationFrame(prepare);
      });
    } catch (error) { viewer.scene.primitives.remove(primitive); throw error; }
    if (crowd) viewer.scene.primitives.remove(crowd);
    crowd = primitive;
    residents = entries;
    animated = new Set();
    crowd.appearance.uniforms.u_visible = 1;
    if (selected?.type === 'resident' && !residents.some((entry) => entry.resident.id === selected.id)) select(null);
    crowd.appearance.uniforms.u_selected = residents.findIndex((entry) => entry.resident.id === selected?.id);
    update(simulationTime, 0);
  }
  resize();
  setMode('orbit');
  update(0, 0);
  try {
    await setPopulation(scene.residents);
    await new Promise((resolve, reject) => {
      const deadline = performance.now() + 30000;
      function finishInitialFrame() {
        try {
          update(0, 0);
          if (model.ready && crowd.ready && viewer.dataSourceDisplay.ready) { resolve(); return; }
          if (performance.now() > deadline) throw new Error('Cesium geometry preparation timed out. Check local worker assets.');
          requestAnimationFrame(finishInitialFrame);
        } catch (error) { reject(error); }
      }
      requestAnimationFrame(finishInitialFrame);
    });
  } catch (error) {
    for (const remove of listeners) remove();
    viewer.destroy();
    container.remove();
    canvas.style.display = previousDisplay;
    throw error;
  }
  return {
    update, setMode, resize, setPopulation,
    resetCamera() { setMode(mode); },
    getState() {
      // Positions use the same route sampler and the live GPU time uniform.
      const position = residents[0] ? sampleResident(scene, residents[0].resident, crowd.appearance.uniforms.u_time).position : null;
      const animatedSample = residents.find((entry, index) => animated.has(index) && entry.resident.id === selected?.id)
        || residents.find((entry, index) => animated.has(index));
      const gaitEnabled = animatedSample ? crowd.getGeometryInstanceAttributes(animatedSample.resident.id).gait[0] : 0;
      return {
        mode, simulationTime, sampleResidentPosition: position,
        cameraPosition: localPoint(viewer.camera.positionWC),
        selectedId: selected?.id || null,
        primitiveCount: scene.primitives.length,
        residentCount: residents.length,
        visibleResidentCount, animatedResidentCount: animated.size,
        assetLoaded: model.ready, assetMeshCount, characterPartCount: scene.character.parts.length,
        sampleAnimatedResidentId: animatedSample?.resident.id || null,
        sampleGaitAngle: animatedSample ? Math.sin(2 * Math.PI * (1.6 * crowd.appearance.uniforms.u_time + animatedSample.resident.phase)) * 0.55 * gaitEnabled : 0,
        entityCount: viewer.entities.values.length,
        movingPrimitiveCount: crowd ? 1 : 0,
        renderedInstances: residents.length,
      };
    },
    dispose() {
      for (const remove of listeners) remove();
      viewer.destroy();
      container.remove();
      canvas.style.display = previousDisplay;
    },
  };
}
