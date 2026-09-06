"""Reproducible DataSF geography import in City Hall-local meters.

Only public municipal sources are downloaded. Raw WGS84 GeoJSON pages remain in
the cache; normalized artifacts retain stable IDs and cite every source page.
Geometry is a two-dimensional baseline. NAVD88 building-ground measurements are
preserved separately for the terrain integration, never treated as building height.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from functools import cached_property
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / ".cache" / "sf-geography"
DEFAULT_OUTPUT = ROOT / ".local" / "civic" / "geography"
ORIGIN_LONGITUDE = -122.4193
ORIGIN_LATITUDE = 37.7793
SOURCE_DOMAIN = "https://data.sfgov.org"
PDDL_URL = "https://opendatacommons.org/licenses/pddl/1-0/"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
JUNCTION_TOLERANCE_M = 2.0


@dataclass(frozen=True)
class Source:
    key: str
    dataset_id: str
    title: str
    geometry_field: str
    select: str
    order: str
    where: str = ""
    observation_note: str = ""

    @property
    def url(self) -> str:
        return f"{SOURCE_DOMAIN}/d/{self.dataset_id}"


SOURCES = (
    Source(
        "shoreline",
        "txuc-3kzm",
        "SF Shoreline and Islands",
        "the_geom",
        "the_geom,objectid,innerwater",
        "objectid",
        observation_note="Historical shoreline and county-line layer; source data last updated 2016-07-12. Includes islands; this is land extent, not the maritime legal boundary.",
    ),
    Source(
        "streets",
        "3psu-pn9h",
        "Streets - Active and Retired",
        "line",
        "line,cnn,f_node_cnn,t_node_cnn,active,classcode,layer,oneway,streetname,accepted,data_as_of",
        "cnn",
        "active = true",
        "Public Works basemap; active source records only. Source-system data_as_of is retained separately from portal refresh dates.",
    ),
    Source(
        "buildings",
        "ynuv-fyni",
        "Building Footprints",
        "shape",
        "shape,sf16_bldgid,area_id,mblr,p2010_name,hgt_median_m,gnd_min_m,peak_1st_m,data_as_of",
        "sf16_bldgid",
        observation_note="Footprints originate from a Pictometry 2010 model, split/refined with methodology documented May 2017. Recent portal refreshes do not establish new measurements. The source includes selected nearby parcels from adjacent counties.",
    ),
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_write(path: str | Path, payload: bytes) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return destination


def _request_json(
    url: str, *, timeout: float = 45, attempts: int = 4
) -> tuple[Any, bytes]:
    """Bound public downloads and retry transient failures without credentials."""
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "OpenGlassBox-SF-Geography/1.0",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError("source response exceeds 64 MiB; reduce --page-size")
            return json.loads(payload), payload
        except HTTPError as exc:
            if (
                exc.code not in (408, 429, 500, 502, 503, 504)
                or attempt + 1 == attempts
            ):
                raise
            retry_after = exc.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = 2**attempt
            if not math.isfinite(delay):
                delay = 2**attempt
            delay = max(0.0, min(20.0, delay))
        except (URLError, TimeoutError, ConnectionError):
            if attempt + 1 == attempts:
                raise
            delay = min(20, 2**attempt)
        time.sleep(delay)
    raise RuntimeError("source request exhausted retries")


def fetch_source(
    source: Source,
    cache_dir: str | Path = DEFAULT_CACHE,
    *,
    page_size: int = 5000,
    offline: bool = False,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fetch or verify a complete source cache, with resumable atomic pages."""
    if type(page_size) is not int or not 1 <= page_size <= 50000:
        raise ValueError("page_size must be an integer from 1 to 50000")
    if offline and refresh:
        raise ValueError("offline and refresh cannot be combined")
    cache = Path(cache_dir)
    query = {
        "select": source.select,
        "order": source.order,
        "where": source.where,
        "page_size": page_size,
    }
    folder = cache / source.dataset_id / content_hash(query)[:16]
    metadata_path = folder / "metadata.json"
    index_path = folder / "source.json"
    if index_path.exists() and not refresh:
        index = json.loads(index_path.read_bytes())
        if index.get("complete"):
            if not metadata_path.is_file() or hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest() != index.get("metadata_sha256"):
                raise ValueError(
                    f"cached {source.key} metadata failed checksum; use --refresh"
                )
            for page in index["pages"]:
                path = folder / page["file"]
                if (
                    not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != page["sha256"]
                ):
                    raise ValueError(
                        f"cached {source.key} page failed checksum: {page['file']}; use --refresh"
                    )
            index["cache_folder"] = str(folder.resolve())
            return index
    if offline:
        raise FileNotFoundError(
            f"complete cached {source.key} source is unavailable: {folder}"
        )
    metadata, metadata_raw = _request_json(
        f"{SOURCE_DOMAIN}/api/views/{source.dataset_id}.json"
    )
    columns = {column.get("fieldName") for column in metadata.get("columns", [])}
    missing = set(source.select.split(",")) - columns
    if missing:
        raise ValueError(
            f"{source.key} source schema changed; missing fields: {sorted(missing)}"
        )
    if metadata.get("licenseId") != "PDDL":
        raise ValueError(
            f"{source.key} source no longer declares the reviewed PDDL license"
        )
    old_metadata = (
        json.loads(metadata_path.read_bytes()) if metadata_path.exists() else None
    )
    reuse_pages = (
        not refresh
        and old_metadata is not None
        and old_metadata.get("rowsUpdatedAt") == metadata.get("rowsUpdatedAt")
    )
    atomic_write(metadata_path, metadata_raw)
    count_query = {"$select": "count(*)"}
    if source.where:
        count_query["$where"] = source.where
    count_data, _ = _request_json(
        f"{SOURCE_DOMAIN}/resource/{source.dataset_id}.json?{urlencode(count_query)}"
    )
    expected = int(count_data[0]["count"])
    if not 0 <= expected <= 1_000_000:
        raise ValueError(f"unexpected {source.key} row count: {expected}")
    pages = []
    actual = 0
    for offset in range(0, expected, page_size):
        query_args = {
            "$select": source.select,
            "$order": source.order,
            "$limit": page_size,
            "$offset": offset,
        }
        if source.where:
            query_args["$where"] = source.where
        url = f"{SOURCE_DOMAIN}/resource/{source.dataset_id}.geojson?{urlencode(query_args)}"
        page_path = folder / f"page-{offset:09d}.geojson"
        if reuse_pages and page_path.exists():
            raw = page_path.read_bytes()
            data = json.loads(raw)
        else:
            data, raw = _request_json(url)
        if data.get("type") != "FeatureCollection" or not isinstance(
            data.get("features"), list
        ):
            raise ValueError(f"{source.key} did not return a GeoJSON FeatureCollection")
        features = len(data["features"])
        if features != min(page_size, expected - offset):
            raise ValueError(
                f"{source.key} pagination changed: expected {min(page_size, expected-offset)} records, received {features}; retry with --refresh"
            )
        crs = data.get("crs", {}).get("properties", {}).get("name", "")
        if crs and "CRS84" not in crs and "4326" not in crs:
            raise ValueError(f"unsupported source coordinate system: {crs}")
        atomic_write(page_path, raw)
        pages.append(
            {
                "file": page_path.name,
                "url": url,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "feature_count": features,
            }
        )
        actual += features
        if progress:
            progress(f"{source.key}: {actual:,}/{expected:,} records cached")
    latest_metadata, _ = _request_json(
        f"{SOURCE_DOMAIN}/api/views/{source.dataset_id}.json"
    )
    if latest_metadata.get("rowsUpdatedAt") != metadata.get("rowsUpdatedAt"):
        raise ValueError(f"{source.key} changed during download; retry with --refresh")
    index = {
        "schema_version": 1,
        "complete": True,
        "id": source.dataset_id,
        "key": source.key,
        "title": source.title,
        "url": source.url,
        "metadata_url": f"{SOURCE_DOMAIN}/api/views/{source.dataset_id}.json",
        "metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
        "license": metadata["license"],
        "attribution": metadata.get("attribution")
        or "City and County of San Francisco",
        "observation_note": source.observation_note,
        "source_rows_updated_at": metadata.get("rowsUpdatedAt"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_query": query,
        "feature_count": actual,
        "pages": pages,
    }
    atomic_write(index_path, canonical_bytes(index))
    index["cache_folder"] = str(folder.resolve())
    return index


def cached_features(index: dict[str, Any]) -> Iterable[dict[str, Any]]:
    folder = Path(index["cache_folder"])
    for page in index["pages"]:
        raw = (folder / page["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != page["sha256"]:
            raise ValueError("source cache checksum does not match")
        yield from json.loads(raw)["features"]


@dataclass(frozen=True)
class LocalProjection:
    """WGS84 ellipsoid surface projected into a local east/north tangent plane.

    Horizontal coordinates are the E/N components of ECEF minus origin ECEF,
    rotated by the origin's geodetic latitude/longitude. All source coordinates
    use ellipsoid height zero for this horizontal map. ``z`` is deliberately an
    independent local vertical datum supplied by the caller, not ECEF curvature.
    The inverse solves the same equations; it is intended for the SF region.
    """

    origin_longitude: float = ORIGIN_LONGITUDE
    origin_latitude: float = ORIGIN_LATITUDE

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.origin_longitude)
            or not -180 <= self.origin_longitude <= 180
        ):
            raise ValueError("origin longitude must be finite and within [-180,180]")
        if (
            not math.isfinite(self.origin_latitude)
            or not -89 <= self.origin_latitude <= 89
        ):
            raise ValueError("origin latitude must be finite and within [-89,89]")

    @staticmethod
    def _ecef(longitude: float, latitude: float) -> tuple[float, float, float]:
        longitude, latitude = math.radians(longitude), math.radians(latitude)
        eccentricity_squared = 6.6943799901413165e-3
        radius = 6378137.0 / math.sqrt(
            1 - eccentricity_squared * math.sin(latitude) ** 2
        )
        return (
            radius * math.cos(latitude) * math.cos(longitude),
            radius * math.cos(latitude) * math.sin(longitude),
            radius * (1 - eccentricity_squared) * math.sin(latitude),
        )

    @cached_property
    def _basis(self) -> tuple[Any, ...]:
        lon, lat = math.radians(self.origin_longitude), math.radians(
            self.origin_latitude
        )
        return (
            self._ecef(self.origin_longitude, self.origin_latitude),
            math.sin(lon),
            math.cos(lon),
            math.sin(lat),
            math.cos(lat),
        )

    def to_local(
        self, longitude: float, latitude: float, z: float = 0.0
    ) -> list[float]:
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in (longitude, latitude, z)
        ):
            raise ValueError("coordinates must be finite numbers")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("longitude/latitude is outside its valid range")
        origin, sin_lon, cos_lon, sin_lat, cos_lat = self._basis
        position = self._ecef(longitude, latitude)
        dx, dy, dz = (position[index] - origin[index] for index in range(3))
        east = -sin_lon * dx + cos_lon * dy
        north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        return [east, north, float(z)]

    def to_lonlat(self, east: float, north: float) -> list[float]:
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in (east, north)
        ):
            raise ValueError("local coordinates must be finite numbers")
        if math.hypot(east, north) > 200000:
            raise ValueError(
                "inverse local projection is limited to 200 km from its origin"
            )
        longitude = self.origin_longitude + math.degrees(
            east / (6378137 * math.cos(math.radians(self.origin_latitude)))
        )
        latitude = self.origin_latitude + math.degrees(north / 6378137)
        for _ in range(8):
            actual_east, actual_north, _ = self.to_local(longitude, latitude)
            error_east, error_north = east - actual_east, north - actual_north
            if math.hypot(error_east, error_north) < 1e-6:
                return [longitude, latitude]
            step = 1e-6
            plus_lon = self.to_local(longitude + step, latitude)
            plus_lat = self.to_local(longitude, latitude + step)
            a, b = (plus_lon[0] - actual_east) / step, (
                plus_lat[0] - actual_east
            ) / step
            c, d = (plus_lon[1] - actual_north) / step, (
                plus_lat[1] - actual_north
            ) / step
            determinant = a * d - b * c
            longitude += (d * error_east - b * error_north) / determinant
            latitude += (-c * error_east + a * error_north) / determinant
        raise ValueError("local coordinate inversion did not converge")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _network_id(value: Any) -> str | None:
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or number <= 0
            or number != number.to_integral_value()
        ):
            return None
        return str(int(number))
    except (InvalidOperation, ValueError, TypeError):
        return None


def bounds_of(points: Iterable[list[float]]) -> dict[str, list[float]]:
    points = list(points)
    if not points:
        return {"min": [0.0, 0.0], "max": [0.0, 0.0]}
    return {
        "min": [min(point[axis] for point in points) for axis in range(2)],
        "max": [max(point[axis] for point in points) for axis in range(2)],
    }


def _project_points(
    coordinates: Any, projection: LocalProjection, *, ring: bool = False
) -> list[list[float]]:
    if not isinstance(coordinates, list):
        raise ValueError("geometry coordinates must be an array")
    points = []
    for coordinate in coordinates:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise ValueError("geometry requires longitude/latitude pairs")
        point = [
            round(value, 3)
            for value in projection.to_local(coordinate[0], coordinate[1])
        ]
        if not points or points[-1] != point:
            points.append(point)
    if ring and len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < (3 if ring else 2):
        raise ValueError("geometry has too few distinct points")
    return points


def _area_centroid(ring: list[list[float]]) -> tuple[float, list[float]]:
    cross_sum = center_x = center_y = 0.0
    for first, second in zip(ring, ring[1:] + ring[:1]):
        cross = first[0] * second[1] - second[0] * first[1]
        cross_sum += cross
        center_x += (first[0] + second[0]) * cross
        center_y += (first[1] + second[1]) * cross
    if abs(cross_sum) < 1e-8:
        raise ValueError("polygon ring has zero area")
    return abs(cross_sum) / 2, [
        center_x / (3 * cross_sum),
        center_y / (3 * cross_sum),
        0.0,
    ]


def _polygon_centroid(rings: list[list[list[float]]]) -> tuple[float, list[float]]:
    area, center = _area_centroid(rings[0])
    weighted = [center[0] * area, center[1] * area]
    for ring in rings[1:]:
        hole_area, hole_center = _area_centroid(ring)
        area -= hole_area
        weighted[0] -= hole_area * hole_center[0]
        weighted[1] -= hole_area * hole_center[1]
    if area <= 0:
        raise ValueError("polygon holes consume its outer area")
    return round(area, 3), [
        round(weighted[0] / area, 3),
        round(weighted[1] / area, 3),
        0.0,
    ]


def simplify_line(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Iterative Douglas-Peucker simplification, preserving line endpoints."""
    if len(points) <= 2 or tolerance <= 0:
        return points
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start, end = pending.pop()
        first, last = points[start], points[end]
        dx, dy = last[0] - first[0], last[1] - first[1]
        length_squared = dx * dx + dy * dy
        largest, chosen = tolerance * tolerance, None
        for index in range(start + 1, end):
            point = points[index]
            amount = (
                max(
                    0.0,
                    min(
                        1.0,
                        ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy)
                        / length_squared,
                    ),
                )
                if length_squared
                else 0.0
            )
            distance = (point[0] - first[0] - amount * dx) ** 2 + (
                point[1] - first[1] - amount * dy
            ) ** 2
            if distance > largest:
                largest, chosen = distance, index
        if chosen is not None:
            keep.add(chosen)
            pending.extend(((start, chosen), (chosen, end)))
    return [points[index] for index in sorted(keep)]


def simplify_ring(
    points: list[list[float]], tolerance: float = 2.0
) -> list[list[float]]:
    if len(points) < 4 or tolerance <= 0:
        return points
    opposite = max(
        range(1, len(points)),
        key=lambda index: math.dist(points[0][:2], points[index][:2]),
    )
    first = simplify_line(points[: opposite + 1], tolerance)
    second = simplify_line(points[opposite:] + points[:1], tolerance)
    result = first[:-1] + second[:-1]
    return result if len(result) >= 3 else points


def normalize_streets(
    features: Iterable[dict[str, Any]], projection: LocalProjection | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    projection = projection or LocalProjection()
    streets, graph_edges = [], []
    candidates: dict[str, set[tuple[float, ...]]] = defaultdict(set)
    candidate_layers: dict[tuple[str, tuple[float, ...]], set[str]] = defaultdict(set)
    node_sources: dict[str, str] = {}
    source_ids = set()
    statistics: Counter[str] = Counter()
    width_by_class = {0: 6, 1: 24, 2: 22, 3: 18, 4: 14, 5: 9, 6: 10}
    for feature in features:
        statistics["input_features"] += 1
        properties = feature.get("properties") or {}
        if properties.get("active") not in (True, "true", "TRUE"):
            statistics["excluded_retired"] += 1
            continue
        layer = str(properties.get("layer") or "").upper()
        if layer.startswith("PAPER") or layer == "PSEUDO":
            statistics["excluded_paper_or_pseudo"] += 1
            continue
        cnn = _network_id(properties.get("cnn"))
        if cnn is None:
            statistics["rejected_missing_id"] += 1
            continue
        if cnn in source_ids:
            raise ValueError(f"duplicate source street CNN: {cnn}")
        source_ids.add(cnn)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "LineString":
            parts = [geometry.get("coordinates")]
        elif geometry.get("type") == "MultiLineString":
            parts = geometry.get("coordinates", [])
        else:
            statistics["rejected_geometry"] += 1
            continue
        road_class = int(_number(properties.get("classcode")) or 0)
        walkable = road_class not in (1, 6) and not layer.startswith(
            ("PRIVATE", "FREEWAY")
        )
        if not walkable:
            statistics["excluded_from_walking_graph"] += 1
        for part_index, coordinates in enumerate(parts):
            try:
                points = _project_points(coordinates, projection)
            except ValueError:
                statistics["rejected_geometry"] += 1
                continue
            identity = f"sf-street:{cnn}" + (
                f":part:{part_index}" if len(parts) > 1 else ""
            )
            streets.append(
                {
                    "id": identity,
                    "source_id": cnn,
                    "name": properties.get("streetname") or f"Street {cnn}",
                    "points": points,
                    "bounds": bounds_of(points),
                    "classcode": road_class,
                    "layer": layer,
                    "motor_oneway": properties.get("oneway"),
                    "accepted": properties.get("accepted"),
                    "width_m": width_by_class.get(road_class, 9),
                    "width_source": "inferred from street classification; not measured pavement or right-of-way width",
                    "walkable_proxy": walkable,
                    "data_as_of": properties.get("data_as_of"),
                }
            )
            if not walkable:
                continue
            identities = []
            for vertex_index, point in enumerate(points):
                source_node = None
                if vertex_index == 0 and part_index == 0:
                    source_node = _network_id(properties.get("f_node_cnn"))
                elif vertex_index == len(points) - 1 and part_index == len(parts) - 1:
                    source_node = _network_id(properties.get("t_node_cnn"))
                if source_node is not None:
                    node_id = f"sf-node:{source_node}"
                    node_sources[node_id] = source_node
                else:
                    node_id = f"sf-bend:{cnn}:{part_index}:{vertex_index}"
                candidates[node_id].add(tuple(point))
                candidate_layers[(node_id, tuple(point))].add(layer)
                identities.append((node_id, tuple(point)))
            for index, (first, second) in enumerate(zip(identities, identities[1:])):
                graph_edges.append(
                    {
                        "id": f"{identity}:segment:{index}",
                        "from": first,
                        "to": second,
                        "bidirectional": True,
                        "source_street_id": cnn,
                        "street_name": properties.get("streetname"),
                        "source_layer": layer,
                    }
                )
    nodes = []
    largest_snap = 0.0
    maximum_disagreement = 0.0
    ambiguous_nodes = []
    remap = {}
    for identity, positions in sorted(candidates.items()):
        maximum_disagreement = max(
            maximum_disagreement,
            max(
                math.dist(first, second) for first in positions for second in positions
            ),
        )
        clusters: list[list[tuple[float, ...]]] = []
        for position in sorted(positions):
            for cluster in clusters:
                if all(
                    math.dist(position, other) <= JUNCTION_TOLERANCE_M
                    for other in cluster
                ):
                    cluster.append(position)
                    break
            else:
                clusters.append([position])
        if len(clusters) > 1:
            ambiguous_nodes.append(identity)
        for cluster in clusters:
            position = min(cluster)
            cluster_id = (
                identity
                if len(clusters) == 1
                else f"{identity}:cluster:{content_hash(list(position))[:10]}"
            )
            largest_snap = max(
                largest_snap, max(math.dist(position, other) for other in cluster)
            )
            layers = set()
            for member in cluster:
                remap[(identity, member)] = cluster_id
                layers.update(candidate_layers[(identity, member)])
            node = {
                "id": cluster_id,
                "position": list(position),
                "source_layers": sorted(layers),
            }
            if identity in node_sources:
                node["source_node_id"] = node_sources[identity]
                node["source_node_conflict"] = len(clusters) > 1
            nodes.append(node)
    node_positions = {node["id"]: node["position"] for node in nodes}
    valid_edges = []
    for edge in graph_edges:
        edge["from"], edge["to"] = remap[edge["from"]], remap[edge["to"]]
        if (
            edge["from"] == edge["to"]
            or math.dist(node_positions[edge["from"]], node_positions[edge["to"]]) <= 0
        ):
            statistics["excluded_zero_length_graph_edges"] += 1
            continue
        valid_edges.append(edge)
    graph = {
        "schema_version": 1,
        "nodes": sorted(nodes, key=lambda node: node["id"]),
        "edges": sorted(valid_edges, key=lambda edge: edge["id"]),
        "routing_assumption": "Two-way pedestrian proxy on physical street centerlines, excluding freeways, ramps and private layers. Sidewalks, legal access and safe crossings are not validated. CNN endpoint IDs and bounded coordinate clusters establish connectivity; geometric crossings alone do not. Source layers are retained, but grade/level is unavailable.",
        "junction_tolerance_m": JUNCTION_TOLERANCE_M,
        "maximum_endpoint_snap_m": round(largest_snap, 3),
        "source_endpoint_maximum_disagreement_m": round(maximum_disagreement, 3),
        "ambiguous_source_node_count": len(ambiguous_nodes),
        "partitioned_source_node_ids": ambiguous_nodes,
    }
    statistics["display_parts"] = len(streets)
    statistics["graph_nodes"] = len(nodes)
    statistics["graph_edges"] = len(valid_edges)
    statistics["ambiguous_source_nodes"] = len(ambiguous_nodes)
    return (
        sorted(streets, key=lambda street: street["id"]),
        graph,
        dict(sorted(statistics.items())),
    )


def normalize_buildings(
    features: Iterable[dict[str, Any]], projection: LocalProjection | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    projection = projection or LocalProjection()
    buildings = []
    seen = set()
    statistics: Counter[str] = Counter()
    for feature in features:
        statistics["input_features"] += 1
        properties = feature.get("properties") or {}
        source_id = properties.get("sf16_bldgid")
        if not isinstance(source_id, str) or not source_id:
            statistics["rejected_missing_id"] += 1
            continue
        if source_id in seen:
            raise ValueError(f"duplicate source building ID: {source_id}")
        seen.add(source_id)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "MultiPolygon":
            polygons = geometry.get("coordinates", [])
        elif geometry.get("type") == "Polygon":
            polygons = [geometry.get("coordinates", [])]
        else:
            statistics["rejected_geometry"] += 1
            continue
        measured_height = _number(properties.get("hgt_median_m"))
        has_height = measured_height is not None and measured_height > 0
        ground = _number(properties.get("gnd_min_m"))
        peak = _number(properties.get("peak_1st_m"))
        for part_index, polygon in enumerate(polygons):
            try:
                if not polygon:
                    raise ValueError("empty polygon")
                rings = [
                    _project_points(ring, projection, ring=True) for ring in polygon
                ]
                area, centroid = _polygon_centroid(rings)
            except ValueError:
                statistics["rejected_geometry"] += 1
                continue
            identity = f"sf-building:{source_id}" + (
                f":part:{part_index}" if len(polygons) > 1 else ""
            )
            buildings.append(
                {
                    "id": identity,
                    "source_id": source_id,
                    "name": properties.get("p2010_name") or "",
                    "source_name_note": "Pictometry model name; may be an asset filename rather than a real building name",
                    "mblr": properties.get("mblr"),
                    "area_id": properties.get("area_id"),
                    "footprint": rings[0],
                    "rings": rings,
                    "centroid": centroid,
                    "bounds": bounds_of(rings[0]),
                    "area_m2": area,
                    "height_m": round(measured_height if has_height else 6.0, 3),
                    "height_source": (
                        "DataSF hgt_median_m: LiDAR-derived median height above ground"
                        if has_height
                        else "estimated 6 m; positive source height unavailable"
                    ),
                    "ground_elevation_navd88_m": (
                        round(ground, 3) if ground is not None else None
                    ),
                    "roof_peak_elevation_navd88_m": (
                        round(peak, 3) if peak is not None else None
                    ),
                    "data_as_of": properties.get("data_as_of"),
                    "use": None,
                }
            )
            statistics[
                "measured_height_parts" if has_height else "estimated_height_parts"
            ] += 1
            if len(rings) > 1:
                statistics["parts_with_holes"] += 1
    statistics["building_parts"] = len(buildings)
    return sorted(buildings, key=lambda building: building["id"]), dict(
        sorted(statistics.items())
    )


def normalize_land(
    features: Iterable[dict[str, Any]],
    projection: LocalProjection | None = None,
    *,
    tolerance: float = 2.0,
) -> list[dict[str, Any]]:
    projection = projection or LocalProjection()
    land = []
    for feature_index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "MultiPolygon":
            polygons = geometry.get("coordinates", [])
        elif geometry.get("type") == "Polygon":
            polygons = [geometry.get("coordinates", [])]
        else:
            raise ValueError("shoreline source must contain polygon geometry")
        identity = (feature.get("properties") or {}).get("objectid", feature_index)
        for part_index, polygon in enumerate(polygons):
            rings = [
                simplify_ring(_project_points(ring, projection, ring=True), tolerance)
                for ring in polygon
            ]
            if not rings:
                continue
            area, _ = _polygon_centroid(rings)
            land.append(
                {
                    "id": f"sf-land:{identity}:{part_index}",
                    "points": rings[0],
                    "rings": rings,
                    "bounds": bounds_of(rings[0]),
                    "area_m2": area,
                    "simplification_tolerance_m": tolerance,
                    "display_note": "Source holes retained in rings; viewer must triangulate holes or omit the roof/fill for those polygons.",
                }
            )
    return sorted(land, key=lambda item: item["id"])


class _RingMask:
    """Horizontal edge bands make many point-in-polygon checks inexpensive."""

    def __init__(self, points: list[list[float]]) -> None:
        self.bounds = bounds_of(points)
        self.bands: dict[int, list[tuple[list[float], list[float]]]] = defaultdict(list)
        for first, second in zip(points, points[1:] + points[:1]):
            for band in range(
                math.floor(min(first[1], second[1]) / 100),
                math.floor(max(first[1], second[1]) / 100) + 1,
            ):
                self.bands[band].append((first, second))

    def contains(self, point: list[float]) -> bool:
        x, y = point[:2]
        if not all(
            self.bounds["min"][axis] <= point[axis] <= self.bounds["max"][axis]
            for axis in range(2)
        ):
            return False
        inside = False
        for first, second in self.bands.get(math.floor(y / 100), ()):
            dx, dy = second[0] - first[0], second[1] - first[1]
            cross = (x - first[0]) * dy - (y - first[1]) * dx
            if (
                abs(cross) < 1e-7
                and min(first[0], second[0]) <= x <= max(first[0], second[0])
                and min(first[1], second[1]) <= y <= max(first[1], second[1])
            ):
                return True
            if (first[1] > y) != (second[1] > y) and x < first[0] + (
                y - first[1]
            ) * dx / dy:
                inside = not inside
        return inside


class LandMask:
    """Containment in source land polygons, not a legal jurisdiction test."""

    def __init__(self, land: list[dict[str, Any]]) -> None:
        self.polygons = [
            (polygon["id"], [_RingMask(ring) for ring in polygon["rings"]])
            for polygon in sorted(land, key=lambda item: (-item["area_m2"], item["id"]))
        ]

    def polygon_at(self, point: list[float]) -> str | None:
        for identity, rings in self.polygons:
            if rings[0].contains(point) and not any(
                ring.contains(point) for ring in rings[1:]
            ):
                return identity
        return None


def _tile_id(point: list[float], tile_size_m: float) -> str:
    return f"{math.floor(point[0] / tile_size_m)}_{math.floor(point[1] / tile_size_m)}"


def write_geography(
    street_features: Iterable[dict[str, Any]],
    building_features: Iterable[dict[str, Any]],
    shoreline_features: Iterable[dict[str, Any]],
    output_dir: str | Path,
    *,
    sources: list[dict[str, Any]] | None = None,
    tile_size_m: float = 500,
    complete: bool = True,
    projection: LocalProjection | None = None,
) -> dict[str, Any]:
    """Normalize geometry and atomically publish a manifest after all artifacts.

    Building parts live in their centroid tile, whose culling bounds include the
    complete footprint. Street parts are copied into every intersected bbox tile
    so a long street never disappears when its midpoint tile is distant.
    """
    if not math.isfinite(tile_size_m) or not 50 <= tile_size_m <= 5000:
        raise ValueError("tile_size_m must be finite and between 50 and 5000")
    projection = projection or LocalProjection()
    output = Path(output_dir)
    streets, graph, street_statistics = normalize_streets(street_features, projection)
    # Validate the exact exported representation against the runtime router.
    from civic_center.routing import WalkingGraph

    WalkingGraph(graph["nodes"], graph["edges"])
    buildings, building_statistics = normalize_buildings(building_features, projection)
    land = normalize_land(shoreline_features, projection)
    land_mask = LandMask(land)
    land_counts: Counter[str] = Counter()
    for building in buildings:
        land_id = land_mask.polygon_at(building["centroid"])
        building["centroid_on_source_land"] = land_id is not None
        building["source_land_polygon_id"] = land_id
        land_counts[land_id or "outside_source_land"] += 1
    building_statistics["centroids_outside_source_land"] = land_counts[
        "outside_source_land"
    ]
    building_statistics["centroids_on_source_land"] = (
        len(buildings) - land_counts["outside_source_land"]
    )
    tiles: dict[str, dict[str, Any]] = {}

    def tile(identity: str) -> dict[str, Any]:
        if identity not in tiles:
            east, north = (int(value) for value in identity.split("_"))
            tiles[identity] = {
                "schema_version": 1,
                "id": identity,
                "buildings": [],
                "streets": [],
                "bounds": {
                    "min": [east * tile_size_m, north * tile_size_m],
                    "max": [(east + 1) * tile_size_m, (north + 1) * tile_size_m],
                },
            }
        return tiles[identity]

    building_index = []
    index_fields = (
        "id",
        "source_id",
        "centroid",
        "bounds",
        "height_m",
        "height_source",
        "ground_elevation_navd88_m",
        "roof_peak_elevation_navd88_m",
        "mblr",
        "name",
        "area_m2",
        "use",
        "data_as_of",
        "centroid_on_source_land",
        "source_land_polygon_id",
    )
    for building in buildings:
        identity = _tile_id(building["centroid"], tile_size_m)
        building["tile_id"] = identity
        tile(identity)["buildings"].append(building)
        building_index.append(
            {**{key: building[key] for key in index_fields}, "tile_id": identity}
        )
    for street in streets:
        low, high = street["bounds"]["min"], street["bounds"]["max"]
        for east in range(
            math.floor(low[0] / tile_size_m), math.floor(high[0] / tile_size_m) + 1
        ):
            for north in range(
                math.floor(low[1] / tile_size_m), math.floor(high[1] / tile_size_m) + 1
            ):
                tile(f"{east}_{north}")["streets"].append(street)
    files = {}

    def artifact(relative: str, value: Any) -> None:
        raw = canonical_bytes(value)
        atomic_write(output / relative, raw)
        files[relative] = hashlib.sha256(raw).hexdigest()

    graph_path = "sf-geography/street-graph.json"
    building_path = "sf-geography/buildings-index.json"
    artifact(graph_path, graph)
    artifact(building_path, {"schema_version": 1, "buildings": building_index})
    tile_index = []
    for identity, contents in sorted(tiles.items()):
        extent_points = [contents["bounds"]["min"], contents["bounds"]["max"]]
        for item in contents["buildings"] + contents["streets"]:
            extent_points.extend((item["bounds"]["min"], item["bounds"]["max"]))
        contents["bounds"] = bounds_of(extent_points)
        relative = f"sf-geography/tiles/{identity}.json"
        artifact(relative, contents)
        tile_index.append(
            {
                "id": identity,
                "path": relative,
                "bounds": contents["bounds"],
                "building_count": len(contents["buildings"]),
                "street_count": len(contents["streets"]),
            }
        )
    urban_extent = [
        point
        for item in streets + buildings
        for point in (item["bounds"]["min"], item["bounds"]["max"])
    ]
    land_extent = [
        point
        for item in land
        for point in (item["bounds"]["min"], item["bounds"]["max"])
    ]
    overview = [
        {
            key: street[key]
            for key in (
                "id",
                "source_id",
                "width_m",
                "width_source",
                "classcode",
                "name",
            )
        }
        | {"points": simplify_line(street["points"], 1.0)}
        for street in streets
    ]
    statistics = {
        "building_count": len(buildings),
        "street_count": len(streets),
        "tile_count": len(tiles),
        "land_polygon_count": len(land),
        "graph_node_count": len(graph["nodes"]),
        "graph_edge_count": len(graph["edges"]),
        "streets": street_statistics,
        "buildings": building_statistics,
        "buildings_by_source_land_polygon": dict(sorted(land_counts.items())),
    }
    manifest = {
        "schema_version": 1,
        "id": "san-francisco-geography",
        "title": "San Francisco official street and building geography",
        "complete": complete,
        "origin": {
            "longitude": projection.origin_longitude,
            "latitude": projection.origin_latitude,
        },
        "coordinate_system": "local east, north, up; meters",
        "horizontal_projection": "WGS84 ellipsoid height-zero ECEF to City Hall-local east/north tangent components",
        "vertical_note": "Planar z=0 geometry baseline; source NAVD88 ground/roof elevations retained separately. Terrain integration supplies local up.",
        "coordinate_precision_m": 0.001,
        "tile_size_m": tile_size_m,
        "bounds": bounds_of(urban_extent or land_extent),
        "land_bounds": bounds_of(land_extent),
        "coverage_bounds": bounds_of(urban_extent + land_extent),
        "coverage_note": "All available source street/building features across SF and dataset-adjacent parcels; shoreline includes source islands. Initial bounds follow urban geometry; land_bounds also retain outlying islands. No spatial clipping to a small pilot.",
        "land_membership_note": "Building centroid membership uses the source shoreline simplified to 2 m, including polygon holes. Outside-source-land may mean adjacent-county parcels, piers, or shoreline-vintage mismatches; it does not establish legal jurisdiction. Farallon land is retained even if no street/building records are supplied there.",
        "sources": sources or [],
        "land": land,
        "overview_streets": overview,
        "graph_path": graph_path,
        "building_index_path": building_path,
        "tiles": tile_index,
        "statistics": statistics,
        "files": files,
        "limitations": [
            "2010-derived footprints are not a current-year reconstruction.",
            "Street widths are inferred; centerline access is a walking proxy, not verified sidewalks.",
            "Building uses, households and capacities are not supplied by this geometry dataset.",
            "Footprint holes are retained; viewers must preserve courtyards when generating roofs.",
            "Measured median building height does not reproduce roof shape, domes, facades or exact peak height.",
        ],
    }
    manifest["sha256"] = content_hash(manifest)
    manifest_path = atomic_write(
        output / "sf-geography.json", canonical_bytes(manifest)
    )
    return {
        "manifest": str(manifest_path.resolve()),
        "sha256": manifest["sha256"],
        "statistics": statistics,
    }


def build_geography(
    indexes: dict[str, dict[str, Any]],
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    tile_size_m: float = 500,
) -> dict[str, Any]:
    source_notes = [
        {key: value for key, value in index.items() if key != "cache_folder"}
        for index in indexes.values()
    ]
    return write_geography(
        cached_features(indexes["streets"]),
        cached_features(indexes["buildings"]),
        cached_features(indexes["shoreline"]),
        output_dir,
        sources=source_notes,
        tile_size_m=tile_size_m,
    )
