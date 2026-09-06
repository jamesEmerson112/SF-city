import './style.css';
import scene from '../../shared/scene.json';
import { createPopulation } from './common.js';

const engines = {
  three: { name: 'Three.js', description: 'A flexible 3D renderer with a custom camera and interaction layer.', load: () => import('./engines/three.js') },
  babylon: { name: 'Babylon.js', description: 'A game-oriented engine with integrated scene, camera, and lighting tools.', load: () => import('./engines/babylon.js') },
  deck: { name: 'deck.gl', description: 'A data visualization renderer, here showing a local 3D scene without a basemap.', load: () => import('./engines/deck.js') },
  cesium: { name: 'CesiumJS', description: 'A geographic engine displaying the same scene in a local frame at City Hall.', load: () => import('./engines/cesium.js') },
};
const requested = new URLSearchParams(location.search).get('engine') || 'three';
const key = Object.hasOwn(engines, requested) ? requested : 'three';
const initialPopulation = Number(new URLSearchParams(location.search).get('population'));
const requestedMode = new URLSearchParams(location.search).get('mode');
const initialMode = ['orbit', 'walk', 'follow'].includes(requestedMode) ? requestedMode : 'orbit';
if (scene.population_presets.includes(initialPopulation)) scene.residents = createPopulation(scene, initialPopulation);
const spec = engines[key];
const byId = id => document.getElementById(id);
byId('engine-title').textContent = spec.name;
byId('engine-description').textContent = spec.description;
byId('resident-count').textContent = scene.residents.length;
byId('primitive-count').textContent = scene.primitives.length;
document.title = `${spec.name} · Civic Center`;
for (const [id, engine] of Object.entries(engines)) {
  const link = document.createElement('a');
  link.href = `?engine=${id}&population=${scene.residents.length}&mode=${initialMode}`;
  link.textContent = engine.name;
  if (id === key) { link.className = 'active'; link.setAttribute('aria-current', 'page'); }
  byId('engines').append(link);
}

let viewer, paused = false, speed = 1, simulationTime = 0, selected = null, populationBusy = false;
let mode = 'orbit', frameId, running = true, frameSamples = [];
const api = window.comparison = { ready: false, engine: key };
for (const count of scene.population_presets) {
  const option = document.createElement('option'); option.value = count; option.textContent = count.toLocaleString();
  byId('population').append(option);
}
byId('population').value = scene.residents.length;

async function setPopulation(count) {
  if (populationBusy) throw new Error('A population change is already in progress');
  const residents = createPopulation(scene, Number(count));
  populationBusy = true;
  byId('population').disabled = true;
  byId('population-status').textContent = 'Preparing people…';
  try {
    await viewer.setPopulation(residents);
    scene.residents = residents;
    if (selected?.type === 'resident' && !residents.some(r => r.id === selected.id)) inspect(null);
    byId('resident-count').textContent = residents.length.toLocaleString();
    byId('population').value = residents.length;
    const url = new URL(location.href); url.searchParams.set('population', residents.length); history.replaceState(null, '', url);
    document.querySelectorAll('#engines a').forEach(link => { const target = new URL(link.href); target.searchParams.set('population', residents.length); link.href = target.href; });
    frameSamples = [];
    viewer.update(simulationTime, 0);
    byId('population-status').textContent = 'Synthetic workload · all people retained';
  } finally { populationBusy = false; byId('population').disabled = false; }
}

function fail(error) {
  console.error(error);
  api.error = error.message || String(error);
  byId('loading').classList.remove('hidden');
  byId('loading').textContent = `Unable to start ${spec.name}. ${api.error}`;
  byId('load-status').textContent = 'Could not load';
  document.querySelector('.status').classList.add('failed');
  running = false;
}
function inspect(selection) {
  selected = selection;
  if (!selection) {
    byId('selection-title').textContent = 'Explore the neighborhood';
    byId('selection-detail').textContent = 'Click a building or resident to inspect it. Follow a selected resident along their route.';
    return;
  }
  byId('selection-title').textContent = selection.label;
  const resident = scene.residents.find(r => r.id === selection.id);
  if (resident) {
    const route = scene.routes.find(r => r.id === resident.route_id);
    byId('selection-detail').textContent = `${resident.home} → ${resident.destination}. ${route.label} · ${Math.round(route.duration)} second loop. Press 3 to follow. Assignments and trips are synthetic.`;
  } else {
    byId('selection-detail').textContent = `${selection.type === 'building' ? 'Building' : 'Scene feature'} · ${selection.id}. Part of the shared schematic City Hall scene.`;
  }
}
function setMode(next) {
  viewer.setMode(next);
  mode = next;
  const url = new URL(location.href); url.searchParams.set('mode', mode); history.replaceState(null, '', url);
  document.querySelectorAll('#engines a').forEach(link => { const target = new URL(link.href); target.searchParams.set('mode', mode); link.href = target.href; });
  document.querySelectorAll('[data-mode]').forEach(button => {
    button.classList.toggle('active', button.dataset.mode === mode);
    button.setAttribute('aria-pressed', button.dataset.mode === mode);
  });
  viewer.update(simulationTime, 0);
}
function setPaused(value) { paused = Boolean(value); byId('pause').textContent = paused ? 'Resume' : 'Pause'; }
function setTime(value) {
  if (!Number.isFinite(value) || value < 0) throw new Error('Time must be a nonnegative finite number');
  simulationTime = value;
  viewer.update(simulationTime, 0);
  displayClock();
}
function displayClock() {
  byId('sim-clock').textContent = `${String(Math.floor(simulationTime / 60)).padStart(2, '0')}:${String(Math.floor(simulationTime % 60)).padStart(2, '0')}`;
}
function toggleSpeed() { speed = speed === 1 ? 4 : 1; byId('speed').textContent = `${speed}× speed`; }
function reset() { setTime(0); viewer.resetCamera(); }

try {
  const adapter = await spec.load();
  viewer = await adapter.createViewer({ canvas: byId('scene-canvas'), scene, onSelect: inspect });
  setMode(initialMode);
  Object.assign(api, {
    setMode, setPaused, setTime, setPopulation, reset,
    getState: () => ({ ...viewer.getState(), engine: key, mode, paused, speed, simulationTime,
      populationBusy, requestedPopulation: scene.residents.length, primitiveCount: scene.primitives.length,
      selection: selected, frameIntervalMs: frameSamples.length ? frameSamples.reduce((a, b) => a + b, 0) / frameSamples.length : null }),
  });
  byId('pause').onclick = () => setPaused(!paused);
  byId('speed').onclick = toggleSpeed;
  byId('reset').onclick = reset;
  byId('population').onchange = event => setPopulation(Number(event.target.value)).catch(fail);
  document.querySelectorAll('[data-mode]').forEach(button => { button.onclick = () => setMode(button.dataset.mode); });
  window.addEventListener('keydown', event => {
    if (event.target instanceof HTMLElement && (event.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName))) return;
    const actions = { Space: () => setPaused(!paused), Digit1: () => setMode('orbit'), Digit2: () => setMode('walk'), Digit3: () => setMode('follow'), KeyR: reset, KeyT: toggleSpeed };
    if (actions[event.code]) { event.preventDefault(); if (!event.repeat) actions[event.code](); }
  });
  const observer = new ResizeObserver(() => viewer.resize());
  observer.observe(byId('stage'));
  let last = performance.now(), lastStats = last;
  document.addEventListener('visibilitychange', () => { last = performance.now(); });
  function frame(now) {
    if (!running) return;
    const elapsed = Math.max(0, (now - last) / 1000);
    const dt = document.hidden ? 0 : Math.min(elapsed, 0.1);
    last = now;
    if (!paused && !populationBusy) simulationTime += dt * speed;
    try { if (!populationBusy) viewer.update(simulationTime, dt); } catch (error) { fail(error); return; }
    if (elapsed > 0 && !document.hidden) {
      frameSamples.push(elapsed * 1000);
      if (frameSamples.length > 90) frameSamples.shift();
    }
    if (now - lastStats > 400) {
      const ms = frameSamples.reduce((a, b) => a + b, 0) / frameSamples.length;
      byId('fps').textContent = ms ? Math.round(1000 / ms) : '—';
      byId('frame-time').textContent = ms ? ms.toFixed(1) : '—';
      const state = viewer.getState();
      byId('visible-count').textContent = (state.visibleResidentCount ?? 0).toLocaleString();
      byId('animated-count').textContent = (state.animatedResidentCount ?? 0).toLocaleString();
      const sorted = [...frameSamples].sort((a, b) => a - b);
      byId('p95').textContent = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))].toFixed(1) : '—';
      displayClock();
      lastStats = now;
    }
    frameId = requestAnimationFrame(frame);
  }
  window.addEventListener('pagehide', () => {
    running = false;
    cancelAnimationFrame(frameId);
    observer.disconnect();
    viewer.dispose();
  }, { once: true });
  byId('loading').classList.add('hidden');
  byId('load-status').textContent = 'Blender scene ready';
  api.ready = true;
  frameId = requestAnimationFrame(frame);
} catch (error) { fail(error); }
