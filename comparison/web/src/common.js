// Cache distances once per immutable fixture, rather than per marker per frame.
const routeCaches = new WeakMap();

export function createPopulation(scene, count) {
  if (!Number.isInteger(count) || !(scene.population_presets || [200, 1000, 5000]).includes(count)) throw new Error('Choose a supported population preset');
  return Array.from({ length: count }, (_, i) => ({
    id: `resident-${String(i).padStart(3, '0')}`, label: `Resident ${String(i + 1).padStart(3, '0')}`,
    route_id: `route-${i % 4}`, phase: (i * 0.61803398875) % 1,
    color: scene.resident_palette[i % 4], skin_color: scene.skin_palette[Math.floor(i / 3) % 4],
    trouser_color: [[0.08, 0.12, 0.18], [0.21, 0.22, 0.20]][i % 2],
    bag_color: [[0.30, 0.21, 0.12], [0.15, 0.18, 0.20]][i % 2],
    home: `Home block ${String(i % 10 + 1).padStart(2, '0')}`,
    destination: i % 4 === 3 ? 'City Hall' : `Work block ${String((i * 3) % 10 + 1).padStart(2, '0')}`,
  }));
}

export function sampleGait(resident, time) {
  return Math.sin(2 * Math.PI * (1.6 * time + resident.phase)) * 0.55;
}

export function walkingEyeHeight(scene, x, y) {
  const ramp = (scene.walk_surfaces || []).find(s => x >= s.min[0] && x <= s.max[0] && y >= s.min[1] && y <= s.max[1]);
  if (ramp) {
    const fraction = Math.max(0, Math.min(1, (y - ramp.from_y) / (ramp.to_y - ramp.from_y)));
    return 1.8 + ramp.from_z + fraction * (ramp.to_z - ramp.from_z);
  }
  return 2.28;
}

export function sampleResident(scene, resident, time) {
  let routes = routeCaches.get(scene);
  if (!routes) {
    routes = new Map(scene.routes.map(route => {
      const lengths = route.points.slice(1).map((point, i) => Math.hypot(...point.map((v, j) => v - route.points[i][j])));
      return [route.id, { ...route, lengths, length: lengths.reduce((a, b) => a + b, 0) }];
    }));
    routeCaches.set(scene, routes);
  }
  const route = routes.get(resident.route_id);
  if (!route || route.duration <= 0 || route.length <= 0) throw new Error(`Invalid route for ${resident.id}`);
  if (!Number.isFinite(time)) throw new Error('Simulation time must be finite');
  let distance = (((time / route.duration + resident.phase) % 1) + 1) % 1 * route.length;
  for (let i = 0; i < route.lengths.length; i++) {
    const length = route.lengths[i];
    if (length > 0 && (distance <= length || i === route.lengths.length - 1)) {
      const a = route.points[i], b = route.points[i + 1];
      return {
        position: a.map((value, axis) => value + (b[axis] - value) * distance / length),
        heading: Math.atan2(b[1] - a[1], b[0] - a[0]),
      };
    }
    distance -= length;
  }
  throw new Error(`Cannot sample route ${route.id}`);
}

export function canWalk(scene, x, y, radius = 0.7) {
  if (![x, y, radius].every(Number.isFinite) || radius < 0) return false;
  if (x - radius < scene.bounds.min[0] || y - radius < scene.bounds.min[1]
    || x + radius > scene.bounds.max[0] || y + radius > scene.bounds.max[1]) return false;
  return !scene.collision_boxes.some(box => x > box.min[0] - radius && x < box.max[0] + radius
    && y > box.min[1] - radius && y < box.max[1] + radius);
}
