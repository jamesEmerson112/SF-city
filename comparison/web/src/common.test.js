import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { sampleResident, canWalk, createPopulation, sampleGait, walkingEyeHeight } from './common.js';

const scene = JSON.parse(readFileSync(new URL('../../shared/scene.json', import.meta.url)));
const near = (a, b) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < 1e-6, `${a} != ${b}`));

test('route progress follows distance, including unequal segments and wraparound', () => {
  const fixture = { routes: [{ id: 'r', duration: 12, points: [[0, 0, 0], [4, 0, 0], [4, 2, 0], [0, 2, 0], [0, 0, 0]] }] };
  const resident = { id: 'person', route_id: 'r', phase: 0 };
  near(sampleResident(fixture, resident, 5).position, [4, 1, 0]);
  near(sampleResident(fixture, resident, 13).position, [1, 0, 0]);
  near(sampleResident(fixture, resident, -1).position, [0, 1, 0]);
  assert.equal(sampleResident(fixture, resident, 5).heading, Math.PI / 2);
});

test('all residents repeat their closed routes deterministically', () => {
  assert.equal(new Set(scene.residents.map(r => r.id)).size, 200);
  for (const resident of scene.residents) {
    const route = scene.routes.find(r => r.id === resident.route_id);
    near(route.points[0], route.points.at(-1));
    near(sampleResident(scene, resident, 17).position, sampleResident(scene, resident, 17 + route.duration).position);
  }
});

test('population changes preserve identities, routes, colors and deterministic samples', () => {
  const small = createPopulation(scene, 200), large = createPopulation(scene, 5000);
  assert.deepEqual(small, scene.residents);
  assert.deepEqual(large.slice(0, 200), small);
  assert.equal(new Set(large.map(r => r.id)).size, 5000);
  for (const resident of large) assert.ok(sampleResident(scene, resident, 31).position.every(Number.isFinite));
  assert.throws(() => createPopulation(scene, 999), /preset/);
});

test('gait repeats and stair eye height increases across the modeled run', () => {
  const resident = scene.residents[0];
  assert.ok(Math.abs(sampleGait(resident, 0.12) - sampleGait(resident, 0.12 + 1 / 1.6)) < 1e-10);
  assert.ok(walkingEyeHeight(scene, 0, 3) > walkingEyeHeight(scene, 0, -9));
});

test('walking permits plaza spawn and blocks building interiors, edges and invalid coordinates', () => {
  assert.ok(canWalk(scene, ...scene.camera.walk_position.slice(0, 2)));
  for (const box of scene.collision_boxes) {
    assert.equal(canWalk(scene, (box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2), false);
  }
  assert.equal(canWalk(scene, scene.bounds.max[0], 0), false);
  assert.equal(canWalk(scene, NaN, 0), false);
  assert.equal(canWalk(scene, 0, -30), true);
});
