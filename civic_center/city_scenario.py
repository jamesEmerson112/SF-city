"""Seed a small persistent walking cohort on normalized San Francisco geography.

Street/building geometry retains its source IDs. Entrances, straight connectors,
household/job assignments and schedules are generated assumptions. Optional
parcel land-use evidence constrains residential/commercial eligibility; without
that source, building uses also remain generated assumptions.
Street centerlines are a walking proxy, not a surveyed sidewalk/access network.
Only assigned buildings enter the simulation; the complete visual building layer
remains available through the referenced geography manifest.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any

from .routing import WalkingGraph
from .scenario import POPULATIONS as RESIDENT_SEED_POPULATIONS, make_scenario, scenario_hash

CITY_POPULATIONS = (1, 20, 200, 1000)
OFFLINE_CITY_POPULATIONS = (2000, 5000)
DEFAULT_CANDIDATE_LIMIT = 4000
CITY_GENERATOR_VERSION = 4
DISTINCT_ALLOCATION_GENERATOR_VERSION = 5
MAX_WORK_CHOICES_PER_HOME = 16


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError(f"Expected geography schema_version 1: {path}")
    return value


def _artifact_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Geography artifact paths must be nonempty strings")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError("Geography artifact paths must be relative to the manifest")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Geography artifact path escapes the manifest directory")
    return resolved


def _read_artifact(manifest: dict[str, Any], root: Path, relative: str) -> dict[str, Any]:
    path = _artifact_path(root, relative)
    encoded = path.read_bytes()
    checksums = manifest.get("files", {})
    if relative in checksums:
        actual = hashlib.sha256(encoded).hexdigest()
        if actual != checksums[relative]:
            raise ValueError(f"Geography artifact checksum mismatch: {relative}")
    value = json.loads(encoded.decode("utf-8-sig"))
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError(f"Expected geography schema_version 1: {path}")
    return value


def _point(value: Any) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise ValueError("Geography coordinates require two or three finite numbers")
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in value):
        raise ValueError("Geography coordinates must be finite numbers")
    return float(value[0]), float(value[1]), float(value[2]) if len(value) == 3 else 0.0


def _projection(point, first, second):
    delta = [second[axis] - first[axis] for axis in range(2)]
    length_squared = sum(value * value for value in delta)
    if not length_squared:
        return 0.0, first, math.dist(point[:2], first[:2])
    fraction = max(0.0, min(1.0, sum((point[i] - first[i]) * delta[i] for i in range(2)) / length_squared))
    projected = tuple(first[i] + fraction * (second[i] - first[i]) for i in range(3))
    return fraction, projected, math.dist(point[:2], projected[:2])


class _SegmentIndex:
    """Grid lookup avoids comparing every building with every street segment."""

    def __init__(self, nodes, edges, cell_size=200.0):
        self.cell_size = cell_size
        self.positions = {node["id"]: _point(node["position"]) for node in nodes}
        self.edges = {edge["id"]: edge for edge in edges}
        self.cells = defaultdict(list)
        for identity, edge in self.edges.items():
            a, b = self.positions[edge["from"]], self.positions[edge["to"]]
            for x in range(math.floor(min(a[0], b[0]) / cell_size), math.floor(max(a[0], b[0]) / cell_size) + 1):
                for y in range(math.floor(min(a[1], b[1]) / cell_size), math.floor(max(a[1], b[1]) / cell_size) + 1):
                    self.cells[x, y].append(identity)

    def nearest(self, point, maximum_distance):
        candidates = set()
        size = self.cell_size
        for x in range(math.floor((point[0] - maximum_distance) / size), math.floor((point[0] + maximum_distance) / size) + 1):
            for y in range(math.floor((point[1] - maximum_distance) / size), math.floor((point[1] + maximum_distance) / size) + 1):
                candidates.update(self.cells.get((x, y), ()))
        best = None
        for identity in sorted(candidates):
            edge = self.edges[identity]
            fraction, position, distance = _projection(
                point, self.positions[edge["from"]], self.positions[edge["to"]],
            )
            candidate = distance, identity, fraction, position
            if distance <= maximum_distance and (best is None or candidate < best):
                best = candidate
        return best


def _components(nodes, edges):
    parents = {node["id"]: node["id"] for node in nodes}

    def find(identity):
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    for edge in edges:
        first, second = find(edge["from"]), find(edge["to"])
        if first != second:
            parents[max(first, second)] = min(first, second)
    return {identity: find(identity) for identity in parents}


def _weighted_order(records, rng, weight):
    """Seeded weighted sampling without replacement using exponential clocks."""
    ranked = [(-math.log(max(rng.random(), 2 ** -53)) / weight(record), index, record)
              for index, record in enumerate(records)]
    return [record for _priority, _index, record in sorted(ranked)]


def _distributed_candidates(records, seed, limit, weights=None):
    """Round-robin spatial cells before taking another building from one cell."""
    buckets = defaultdict(list)
    for record in records:
        centroid = _point(record["centroid"])
        key = math.floor(centroid[0] / 750), math.floor(centroid[1] / 750)
        buckets[key].append(record)
    keys = sorted(buckets)
    random.Random(seed).shuffle(keys)
    for key in keys:
        buckets[key].sort(key=lambda record: record["id"])
        rng = random.Random(f"{seed}:{key[0]}:{key[1]}")
        if weights is None:
            rng.shuffle(buckets[key])
        else:
            buckets[key] = _weighted_order(buckets[key], rng, lambda record: weights[record["id"]])
    result = []
    rank = 0
    while len(result) < limit:
        added = False
        for key in keys:
            if rank < len(buckets[key]):
                result.append(buckets[key][rank])
                added = True
                if len(result) == limit:
                    break
        if not added:
            break
        rank += 1
    return result


def _eligible_use(use, role):
    if not use or not use.get(f"{role}_eligible"):
        return False
    weight = use.get(f"{role}_weight")
    return type(weight) in (int, float) and math.isfinite(weight) and weight > 0


def _landuse_candidates(records, uses, seed, limit):
    """Balance home/work evidence while preserving coverage and group weights."""
    pools = []
    for role in ("home", "work"):
        eligible = [record for record in records if _eligible_use(uses.get(record["id"]), role)]
        if not eligible:
            raise ValueError(f"Land-use data provides no positive eligible {role} candidates on source land")
        weights = {record["id"]: uses[record["id"]][f"{role}_weight"] for record in eligible}
        pools.append(_distributed_candidates(eligible, f"{seed}:{role}", limit, weights))
    result, seen = [], set()
    for rank in range(max(map(len, pools))):
        for pool in pools:
            if rank < len(pool) and pool[rank]["id"] not in seen:
                result.append(pool[rank])
                seen.add(pool[rank]["id"])
                if len(result) == limit:
                    return result
    return result


def _candidate_footprints(manifest, root, records):
    requested = {record["id"] for record in records}
    result = {}
    tile_ids = {record["tile_id"] for record in records}
    tiles = {tile["id"]: tile for tile in manifest["tiles"]}
    for tile_id in sorted(tile_ids):
        if tile_id not in tiles:
            raise ValueError(f"Building references an unknown geography tile: {tile_id}")
        tile = _read_artifact(manifest, root, tiles[tile_id]["path"])
        for building in tile.get("buildings", []):
            if building["id"] in requested:
                footprint = [_point(point) for point in building["footprint"]]
                if len(footprint) < 3:
                    continue
                if footprint[0] == footprint[-1]:
                    footprint.pop()
                if len(footprint) < 3:
                    continue
                result[building["id"]] = {
                    "footprint": footprint,
                    "rings": deepcopy(building.get("rings", [building["footprint"]])),
                }
    return result


def _boundary_entrance(footprint, street_position):
    best = None
    for index, first in enumerate(footprint):
        second = footprint[(index + 1) % len(footprint)]
        _fraction, position, distance = _projection(street_position, first, second)
        candidate = distance, index, position
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    # Streets are currently normalized on a flat zero-elevation baseline.
    return best[0], (best[2][0], best[2][1], street_position[2])


def _inside_footprint(point, footprint):
    """Strict outer-ring interior; a street point on its boundary is allowed."""
    inside = False
    x, y = point[:2]
    for index, a in enumerate(footprint):
        b = footprint[(index + 1) % len(footprint)]
        if _projection(point, a, b)[2] < 1e-7:
            return False
        if (a[1] > y) != (b[1] > y):
            crossing_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < crossing_x:
                inside = not inside
    return inside


def _attach_buildings(graph, candidates, footprints, maximum_connector_m, terrain=None):
    WalkingGraph(graph["nodes"], graph["edges"])
    if any(edge.get("bidirectional", True) is not True for edge in graph["edges"]):
        raise ValueError("City walking scenario requires bidirectional proxy street edges")
    index = _SegmentIndex(graph["nodes"], graph["edges"])
    components = _components(graph["nodes"], graph["edges"])
    accepted = []
    cuts = defaultdict(list)
    skipped = Counter()
    for source in candidates:
        identity = source["id"]
        if identity not in footprints:
            skipped["missing_footprint"] += 1
            continue
        centroid = _point(source["centroid"])
        footprint = footprints[identity]["footprint"]
        radius = max(math.dist(centroid[:2], point[:2]) for point in footprint)
        nearest = index.nearest(centroid, maximum_connector_m + radius)
        if nearest is None:
            skipped["no_nearby_street"] += 1
            continue
        _distance, edge_id, fraction, street_position = nearest
        if _inside_footprint(street_position, footprint):
            skipped["street_projection_inside_footprint"] += 1
            continue
        missing_projection = False
        missing_entrance = False
        if terrain is not None:
            height = terrain.triangle_height_at(*street_position[:2])
            missing_projection = height is None
            street_position = (street_position[0], street_position[1], .08 if height is None else height + .08)
        connector_distance, entrance = _boundary_entrance(footprint, street_position)
        if terrain is not None:
            height = terrain.triangle_height_at(*entrance[:2])
            missing_entrance = height is None
            entrance = (entrance[0], entrance[1], .08 if height is None else height + .08)
        connector_distance = math.dist(entrance, street_position)
        if connector_distance > maximum_connector_m:
            skipped["connector_too_long"] += 1
            continue
        edge = index.edges[edge_id]
        candidate = {
            "source": source, "geometry": footprints[identity], "entrance": entrance,
            "street_position": street_position, "edge_id": edge_id,
            "fraction": fraction, "component": components[edge["from"]],
            "connector_distance_m": connector_distance,
            "street_name": edge.get("street_name"),
            "missing_projection_elevation": missing_projection,
            "missing_entrance_elevation": missing_entrance,
        }
        accepted.append(candidate)
        cuts[edge_id].append(candidate)
    nodes = deepcopy(graph["nodes"])
    edges = []
    for original in graph["edges"]:
        attached = sorted(cuts.get(original["id"], ()), key=lambda candidate: (candidate["fraction"], candidate["source"]["id"]))
        if not attached:
            edges.append(deepcopy(original))
            continue
        chain = [(original["from"], index.positions[original["from"]])]
        for candidate in attached:
            position = candidate["street_position"]
            if math.dist(position, index.positions[original["to"]]) <= 1e-6:
                junction = original["to"]
            elif math.dist(position, chain[-1][1]) <= 1e-6:
                junction = chain[-1][0]
            else:
                junction = f"sf-attach:{candidate['source']['id']}"
                nodes.append({"id": junction, "position": list(position), "source": "generated street-centerline projection"})
                chain.append((junction, position))
            candidate["junction_id"] = junction
            entrance = candidate["entrance"]
            if math.dist(entrance, position) <= 1e-6:
                candidate["entrance_node_id"] = junction
            else:
                entrance_id = f"entrance:{candidate['source']['id']}"
                candidate["entrance_node_id"] = entrance_id
                nodes.append({"id": entrance_id, "position": list(entrance), "source": "inferred footprint boundary; not an observed door"})
                edges.append({
                    "id": f"connector:{candidate['source']['id']}", "from": entrance_id,
                    "to": junction, "bidirectional": True,
                    "source": "generated straight connector; access and intervening obstacles unvalidated",
                })
        if chain[-1][0] != original["to"]:
            chain.append((original["to"], index.positions[original["to"]]))
        for part, (first, second) in enumerate(zip(chain, chain[1:])):
            edge = deepcopy(original)
            edge.update(id=f"{original['id']}:split:{part:04d}", **{"from": first[0], "to": second[0]})
            edge["original_edge_id"] = original["id"]
            edges.append(edge)
    return nodes, edges, accepted, dict(skipped)


def _choose_pairs(candidates, graph, population, seed, minimum_walk_m, maximum_walk_m, uses=None, *, distinct_allocations=False):
    router = WalkingGraph(graph[0], graph[1])
    homes, workplaces = candidates, candidates
    if uses is not None:
        by_id = {candidate["source"]["id"]: candidate for candidate in candidates}
        home_sources = [candidate["source"] for candidate in candidates
                        if _eligible_use(uses.get(candidate["source"]["id"]), "home")]
        workplaces = [candidate for candidate in candidates
                      if _eligible_use(uses.get(candidate["source"]["id"]), "work")]
        home_weights = {source["id"]: uses[source["id"]]["home_weight"] for source in home_sources}
        homes = [by_id[source["id"]] for source in _distributed_candidates(
            home_sources, f"{seed}:resident-home", len(home_sources), home_weights,
        )]
    # Query nearby candidates by a bounded spatial grid before any path search.
    cell_size = maximum_walk_m
    grid = defaultdict(list)
    for candidate in workplaces:
        x, y, _z = candidate["entrance"]
        grid[math.floor(x / cell_size), math.floor(y / cell_size)].append(candidate)
    pairs = []
    route_searches = 0
    remaining_homes = []

    def choose_next_work(home, choices):
        nonlocal route_searches
        for index, work in enumerate(choices):
            route_searches += 1
            route = router.route(home["entrance_node_id"], work["entrance_node_id"])
            if route is not None and minimum_walk_m <= route.length <= maximum_walk_m:
                pairs.append((home, work, route.length))
                return choices[index + 1:]
        return []

    for home in homes:
        x, y, _z = home["entrance"]
        cx, cy = math.floor(x / cell_size), math.floor(y / cell_size)
        options = []
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                for work in grid.get((gx, gy), ()):
                    if work is home or work["component"] != home["component"]:
                        continue
                    distance = math.dist(home["entrance"], work["entrance"])
                    if minimum_walk_m <= distance <= maximum_walk_m:
                        options.append(work)
        options.sort(key=lambda candidate: candidate["source"]["id"])
        rng = random.Random(f"{seed}:work:{home['source']['id']}")
        if uses is None:
            rng.shuffle(options)
        else:
            options = _weighted_order(options, rng, lambda work: uses[work["source"]["id"]]["work_weight"])
        remaining = choose_next_work(home, options[:MAX_WORK_CHOICES_PER_HOME])
        if distinct_allocations and remaining:
            remaining_homes.append((home, remaining))
        if len(pairs) >= population:
            break
    if not pairs:
        if uses is not None:
            raise ValueError("No eligible residential/commercial walking pair satisfies the configured distance and access constraints; land-use allocation cannot fall back to arbitrary buildings")
        raise ValueError("No connected home/work pair satisfies the configured walking-distance range")
    if distinct_allocations:
        # Preserve the original first home/work choice and its seeded prefix.
        # Additional rounds distribute another distinct workplace per home before
        # taking a third. A home still has at most 16 path searches in total;
        # this does not become an all-pairs search as population increases.
        while len(pairs) < population and remaining_homes:
            next_round = []
            for home, choices in remaining_homes:
                remaining = choose_next_work(home, choices)
                if remaining:
                    next_round.append((home, remaining))
                if len(pairs) >= population:
                    break
            remaining_homes = next_round
        if len(pairs) < population:
            raise ValueError(
                f"Distinct city allocation requires {population} home/work pairs; "
                f"only {len(pairs)} satisfy eligibility, access and distance constraints "
                f"within {MAX_WORK_CHOICES_PER_HOME} work choices per home. "
                "No pair assignments were repeated."
            )
    return [pairs[index % len(pairs)] for index in range(population)], route_searches, len(pairs)


def _terrain_polylines(nodes, edges, terrain, maximum_spacing_m=20.0):
    """Attach dense terrain geometry without adding any routing graph junctions."""
    positions = {node["id"]: node["position"] for node in nodes}
    polyline_count = 0
    point_count = 0
    missing = 0
    for edge in edges:
        first, last = positions[edge["from"]], positions[edge["to"]]
        fractions = terrain.segment_fractions(first[:2], last[:2], max_spacing_m=maximum_spacing_m)
        points = [list(first)]
        for fraction in fractions[1:-1]:
            east = first[0] + (last[0] - first[0]) * fraction
            north = first[1] + (last[1] - first[1]) * fraction
            height = terrain.triangle_height_at(east, north)
            if height is None:
                missing += 1
            position = [east, north, .08 if height is None else height + .08]
            if position != points[-1]:
                points.append(position)
        if list(last) != points[-1]:
            points.append(list(last))
        if len(points) > 2:
            edge["points"] = points
            polyline_count += 1
            point_count += len(points)
    return {
        "polyline_edges": polyline_count, "polyline_points": point_count,
        "missing_polyline_interior_samples": missing,
        "maximum_polyline_spacing_m": maximum_spacing_m,
        "interpolation": "northwest/southeast DEM triangles; exact grid and diagonal crossings",
    }


def build_city_scenario(
    manifest_path: str | Path, population: int = 200, seed: int = 7,
    *, minimum_walk_m: float = 150, maximum_walk_m: float = 3000,
    maximum_connector_m: float = 120, candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    terrain_path: str | Path | None = None,
    repeat_days: bool = True,
    landuse_path: str | Path | None = None,
    distinct_allocations: bool = False,
) -> dict[str, Any]:
    """Build a distributed synthetic cohort on authentic geometry.

    Generated city schedules repeat daily by default. ``repeat_days=False``
    retains the finite one-day behavior; neither mode infers observed attendance.
    ``distinct_allocations=True`` requires a different home/work building pair
    for every synthetic resident and permits offline 2,000/5,000 cohorts. These
    are distinct assignments, not observed households or measured jobs. Viewer
    population presets remain the separately bounded ``CITY_POPULATIONS``.
    """
    if type(distinct_allocations) is not bool:
        raise ValueError("distinct_allocations must be a boolean")
    allowed_populations = CITY_POPULATIONS + OFFLINE_CITY_POPULATIONS if distinct_allocations else CITY_POPULATIONS
    if type(population) is not int or population not in allowed_populations:
        raise ValueError(f"City population must be one of {allowed_populations}; offline larger cohorts require distinct_allocations=True")
    if type(seed) is not int:
        raise ValueError("City scenario seed must be an integer")
    if type(repeat_days) is not bool:
        raise ValueError("repeat_days must be a boolean")
    for value in (minimum_walk_m, maximum_walk_m, maximum_connector_m):
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError("Walking and connector distances must be finite and positive")
    if minimum_walk_m >= maximum_walk_m:
        raise ValueError("minimum_walk_m must be less than maximum_walk_m")
    if type(candidate_limit) is not int or not 2 <= candidate_limit <= 20_000:
        raise ValueError("candidate_limit must be an integer from 2 to 20000")
    path = Path(manifest_path).resolve()
    manifest = _read_json(path)
    if manifest.get("sha256") and manifest["sha256"] != scenario_hash(manifest):
        raise ValueError("Geography manifest checksum mismatch")
    root = path.parent
    graph = _read_artifact(manifest, root, manifest["graph_path"])
    # Fail on corrupt source topology before loading the much larger building
    # index and tile geometries. Attachment construction validates it again after
    # elevation assignment because those positions become the movement graph.
    WalkingGraph(graph["nodes"], graph["edges"])
    terrain = None
    terrain_metadata = None
    if terrain_path is None:
        sibling = root.parent / "terrain" / "terrain.json"
        if sibling.exists():
            terrain_path = sibling
    if terrain_path is not None:
        from .terrain import TerrainGrid
        terrain_path = Path(terrain_path).resolve()
        terrain = TerrainGrid.load(terrain_path)
        if terrain.data.get("origin", manifest["origin"]) != manifest["origin"]:
            raise ValueError("Terrain and geography must use the same local origin")
        missing = 0
        for node in graph["nodes"]:
            east, north, _z = _point(node["position"])
            height = terrain.triangle_height_at(east, north)
            node["position"] = [east, north, .08 if height is None else height + .08]
            node["elevation_source"] = "terrain sample plus 0.08 m foot clearance" if height is not None else "terrain unavailable; flat local fallback plus 0.08 m"
            missing += height is None
        terrain_metadata = {
            "path": str(terrain_path), "sha256": hashlib.sha256(terrain_path.read_bytes()).hexdigest(),
            "origin_elevation_m": terrain.origin_elevation_m, "walking_clearance_m": .08,
            "missing_street_node_samples": missing,
            "assumption": "terrain sampled on northwest/southeast raster triangles; bridges/decks and doors unobserved",
        }
    index = _read_artifact(manifest, root, manifest["building_index_path"])
    records = index.get("buildings")
    if type(records) is not list or len(records) < 2:
        raise ValueError("City scenario needs at least two building footprints")
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("Geography building IDs must be unique")
    uses = None
    landuse_metadata = None
    if landuse_path is not None:
        from .landuse import LandUseIndex
        landuse_path = Path(landuse_path).resolve()
        landuse = LandUseIndex.load(landuse_path)
        # Apportion source-group counts over the complete footprint index,
        # before candidate limits or shoreline filters can change group totals.
        uses, join_statistics = landuse.match_buildings(records)
        landuse_metadata = {
            "path": str(landuse_path), "sha256": landuse.data["sha256"],
            "file_sha256": hashlib.sha256(landuse_path.read_bytes()).hexdigest(),
            "source": deepcopy(landuse.data.get("source", {})),
            "join_statistics": join_statistics,
            "selection": "balanced home/work candidate pools; weighted ordering within 750 m spatial coverage cells; residential-unit and commercial-area weights shared once across source-group footprints",
            "assignment_note": "Synthetic residents and jobs are sampled on eligible source uses; dwelling units are not residents, and commercial square feet are not jobs. Repeated eligible pairs do not establish measured occupancy.",
        }
        del landuse
    original_building_count = len(records)
    records = [record for record in records if record.get("centroid_on_source_land") is not False]
    if uses is None:
        selected = _distributed_candidates(records, seed, candidate_limit)
    else:
        selected = _landuse_candidates(records, uses, seed, candidate_limit)
        uses = {record["id"]: uses[record["id"]] for record in selected}
    footprints = _candidate_footprints(manifest, root, selected)
    nodes, edges, candidates, skipped = _attach_buildings(graph, selected, footprints, maximum_connector_m, terrain)
    if terrain_metadata is not None:
        terrain_metadata["missing_building_projection_samples"] = sum(candidate["missing_projection_elevation"] for candidate in candidates)
        terrain_metadata["missing_building_entrance_samples"] = sum(candidate["missing_entrance_elevation"] for candidate in candidates)
        terrain_metadata.update(_terrain_polylines(nodes, edges, terrain))
    pairs, searches, unique_pairs = _choose_pairs(
        candidates, (nodes, edges), population, seed, minimum_walk_m, maximum_walk_m,
        uses, distinct_allocations=distinct_allocations,
    )
    seed_population = next(size for size in RESIDENT_SEED_POPULATIONS if size >= population)
    resident_seeds = make_scenario(seed_population, seed)
    residents = []
    assignments = defaultdict(set)
    assigned_residents = defaultdict(set)
    home_counts, work_counts = Counter(), Counter()
    buildings_by_id = {}
    for index, (home, work, distance) in enumerate(pairs):
        source = resident_seeds["residents"][index]
        home_id, work_id = home["source"]["id"], work["source"]["id"]
        source.update(
            id=f"sf-resident-{index:06d}", label=f"SF Resident {index + 1:06d}",
            home_id=home_id, work_id=work_id, commute_distance_m=distance,
            allocation_source="generated short walking commute; not observed household or employment data",
        )
        if uses is not None:
            source["allocation_source"] = "generated resident and job assignment constrained by matched official residential/commercial parcel uses; not observed household or employment data"
            source["home_landuse_record_id"] = uses[home_id]["record_id"]
            source["work_landuse_record_id"] = uses[work_id]["record_id"]
        residents.append(source)
        home_counts[home_id] += 1
        work_counts[work_id] += 1
        for role, candidate in (("home", home), ("work", work)):
            identity = candidate["source"]["id"]
            assignments[identity].add(role)
            assigned_residents[identity].add(source["id"])
            buildings_by_id[identity] = candidate
    buildings = []
    for identity, candidate in sorted(buildings_by_id.items()):
        source = deepcopy(candidate["source"])
        roles = sorted(assignments[identity])
        position = list(_point(source["centroid"]))
        base_height = terrain.triangle_height_at(*position[:2]) if terrain is not None else None
        position[2] = 0.0 if base_height is None else base_height
        name = source.get("name")
        if name and str(name).lower().endswith((".flt", ".obj", ".3ds", ".dae")):
            name = None
        street_name = candidate.get("street_name")
        label = name or (f"Building near {street_name}" if street_name else f"SF building {source.get('source_id', identity)}")
        source.update(
            label=label, nearest_street_name=street_name,
            kind=roles[0] if len(roles) == 1 else "mixed",
            generated_roles=roles, capacity=population,
            capacity_source="synthetic cohort capacity; not a surveyed building capacity",
            use_source="generated home/work allocation; source footprint index has no building-use field",
            position=position, base_elevation_m=position[2],
            base_elevation_source="terrain sampled at building centroid; building base flattened" if base_height is not None else "flat local fallback; no terrain sample",
            footprint=[list(point) for point in candidate["geometry"]["footprint"]],
            rings=deepcopy(candidate["geometry"]["rings"]),
            entrance_node_id=candidate["entrance_node_id"],
            entrance_position=list(candidate["entrance"]),
            entrance_source="inferred closest footprint boundary to a nearby street-centerline projection",
            entrance_elevation_source="terrain plus 0.08 m foot clearance" if terrain is not None and not candidate["missing_entrance_elevation"] else "flat local fallback",
            connector_distance_m=candidate["connector_distance_m"],
        )
        if uses is not None:
            source.update(
                land_use=deepcopy(uses[identity]),
                use_source="official parcel/group residential and commercial measures joined by exact parcel ID; footprint shares and resident/job assignments are generated",
                generated_home_resident_count=home_counts[identity],
                generated_work_resident_count=work_counts[identity],
                capacity=len(assigned_residents[identity]),
                capacity_source="number of distinct synthetic cohort residents assigned here in either role; not source-group dwelling units, measured building capacity or jobs",
            )
        buildings.append(source)
    spawn_node = min(graph["nodes"], key=lambda node: (node["position"][0] ** 2 + node["position"][1] ** 2, node["id"]))
    spawn = list(spawn_node["position"])
    spawn[2] += 1.8
    city_hall_ground = terrain.triangle_height_at(0, 0) if terrain is not None else 0.0
    scenario = {
        "schema_version": 1, "id": "san-francisco-street-walking-day-v1",
        "label": "San Francisco: a generated walking day", "seed": seed,
        "tick_hz": resident_seeds["tick_hz"], "start_time_seconds": resident_seeds["start_time_seconds"],
        "population": population, "population_presets": list(CITY_POPULATIONS),
        "coordinate_system": manifest.get("coordinate_system", "local east, north, up; meters"),
        "origin": deepcopy(manifest["origin"]),
        "geography_manifest": str(path), "geography_manifest_sha256": manifest.get("sha256") or scenario_hash(manifest),
        "source_note": "Authentic normalized San Francisco building footprints and street geometry. Synthetic residents, uses, schedules, entrances and straight access connectors; no observed household/job assignments. Street-centerline walking proxy and unvalidated access/crossings. " + ("Terrain-sampled route vertices with explicit missing-sample fallbacks." if terrain is not None else "Flat walking elevation baseline; no terrain loaded."),
        "routing_assumption": graph.get("routing_assumption", "bidirectional street-centerline proxy; not surveyed sidewalks"),
        "view": {
            "walk_position": spawn, "walk_source_node_id": spawn_node["id"],
            "walk_position_source": "source street graph node nearest City Hall origin, with generated eye height",
            "target": [0, 0, (city_hall_ground or 0.0) + 15], "distance": 700,
        },
        "generation": {
            "generator_version": CITY_GENERATOR_VERSION,
            "candidate_limit": candidate_limit, "candidate_buildings": len(selected),
            "connected_candidate_buildings": len(candidates), "assigned_buildings": len(buildings),
            "distinct_home_work_pairs": unique_pairs, "route_searches": searches,
            "minimum_walk_m": minimum_walk_m, "maximum_walk_m": maximum_walk_m,
            "maximum_connector_m": maximum_connector_m, "skipped_candidates": skipped,
            "excluded_off_source_land": original_building_count - len(records),
            "land_filter_note": "exclude explicitly off-source-land centroids from cohort assignment; historical shoreline membership is not a legal-jurisdiction claim",
            "coverage": "spatially distributed small cohort; not a city population estimate",
        },
        "nodes": nodes, "edges": edges, "buildings": buildings, "residents": residents,
    }
    if terrain_metadata is not None:
        scenario["terrain"] = terrain_metadata
        scenario["terrain_manifest"] = terrain_metadata["path"]
        scenario["terrain_manifest_sha256"] = terrain_metadata["sha256"]
    if landuse_metadata is not None:
        scenario["landuse"] = landuse_metadata
        scenario["landuse_manifest"] = landuse_metadata["path"]
        scenario["landuse_manifest_sha256"] = landuse_metadata["sha256"]
        scenario["landuse_manifest_file_sha256"] = landuse_metadata["file_sha256"]
        scenario["source_note"] = scenario["source_note"].replace(
            "Synthetic residents, uses, schedules, entrances and straight access connectors; no observed household/job assignments.",
            "Official parcel/group land-use evidence constrains eligible homes and workplaces. Residents, jobs, schedules, entrances and straight access connectors are generated; no observed household/job assignments.",
        )
        scenario["generation"]["landuse_candidate_home_count"] = sum(_eligible_use(use, "home") for use in uses.values())
        scenario["generation"]["landuse_candidate_work_count"] = sum(_eligible_use(use, "work") for use in uses.values())
        scenario["generation"]["reused_pair_assignments"] = population - unique_pairs
    if repeat_days:
        scenario["schedule"] = {"mode": "daily-v1"}
        scenario["schedule_note"] = "Generated home/work schedules repeat every 24 hours; no weekday, holiday, seasonal or observed attendance model. Disconnected trips remain blocked."
    if distinct_allocations:
        scenario["generation"].update(
            generator_version=DISTINCT_ALLOCATION_GENERATOR_VERSION,
            distinct_allocations_required=True,
            maximum_work_choices_per_home=MAX_WORK_CHOICES_PER_HOME,
            offline_scale_validation=population not in CITY_POPULATIONS,
        )
    scenario["sha256"] = scenario_hash(scenario)
    return scenario


def write_city_scenario(manifest_path: str | Path, output: str | Path, **options) -> Path:
    scenario = build_city_scenario(manifest_path, **options)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(scenario, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return destination
