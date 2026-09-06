"""Cache a USGS 3DEP bare-earth elevation grid for mainland SF and Bay islands.

The service export is floating-point elevation, not a rendered hillshade. Raw
responses, acquisition metadata and checksums accompany the normalized grid.
Farallon Islands are outside this initial terrain rectangle and remain unknown.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from civic_center.terrain import ORIGIN, TerrainGrid, local_xy
from civic_center.geography import LocalProjection

SERVICE = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
)
BBOX = (-122.54, 37.69, -122.32, 37.85)


def request_json(url: str, cache: Path, refresh: bool) -> dict:
    if refresh or not cache.is_file():
        request = urllib.request.Request(
            url, headers={"User-Agent": "OpenGlassBox-SanFrancisco/0.1"}
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
        data = json.loads(raw)
        if "error" in data:
            raise RuntimeError(f"USGS elevation service error: {data['error']}")
        cache.write_bytes(raw)
        cache.with_suffix(".request.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return json.loads(cache.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/civic/terrain")
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    if not 32 <= args.size <= 4096:
        parser.error("--size must be between 32 and 4096")
    from PIL import Image

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = request_json(SERVICE + "?f=pjson", output / "service.json", args.refresh)
    geometry = {
        "xmin": BBOX[0],
        "ymin": BBOX[1],
        "xmax": BBOX[2],
        "ymax": BBOX[3],
        "spatialReference": {"wkid": 4326},
    }
    query = {
        "f": "json",
        "where": "1=1",
        "geometry": json.dumps(geometry),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "false",
        "outFields": "Dataset_ID,Source,VerticalDatum,AcquisitionDate,URL,title,Resolution_X,Resolution_Y,Best,DEM_Type",
    }
    catalog = request_json(
        SERVICE + "/query?" + urllib.parse.urlencode(query),
        output / "catalog.json",
        args.refresh,
    )
    params = {
        "f": "json",
        "bbox": ",".join(map(str, BBOX)),
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{args.size},{args.size}",
        "format": "tiff",
        "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation",
        "renderingRule": json.dumps({"rasterFunction": "None"}),
        "adjustAspectRatio": "false",
        "noData": -999999,
    }
    export_url = SERVICE + "/exportImage?" + urllib.parse.urlencode(params)
    export_path = output / f"export-{args.size}.json"
    raster_path = output / f"elevation-{args.size}.tif"
    export = request_json(
        export_url, export_path, args.refresh or not raster_path.is_file()
    )
    if args.refresh or not raster_path.is_file():
        print("Downloading floating-point USGS elevation raster...", flush=True)
        with urllib.request.urlopen(export["href"], timeout=90) as response:
            raster_path.write_bytes(response.read())
    with Image.open(raster_path) as raster:
        if raster.mode != "F":
            raise ValueError(
                f"Expected floating-point elevations, got image mode {raster.mode}"
            )
        width, height = raster.size
        # USGS NoData values are far outside any SF elevation. Preserve holes.
        elevations = [
            round(value, 3) if -500 < value < 5000 else None
            for value in raster.get_flattened_data()
        ]
    if args.download_only:
        print(
            json.dumps(
                {
                    "raster": str(raster_path),
                    "size": [width, height],
                    "bytes": raster_path.stat().st_size,
                    "catalog_features": len(catalog.get("features", [])),
                }
            )
        )
        return 0
    extent = export["extent"]
    spatial_reference = extent.get("spatialReference", {})
    if spatial_reference.get("latestWkid", spatial_reference.get("wkid")) != 4326:
        raise ValueError("USGS returned an unexpected horizontal coordinate system")
    delta_lon = (extent["xmax"] - extent["xmin"]) / width
    delta_lat = (extent["ymax"] - extent["ymin"]) / height
    # Raster values are at pixel centers, not outside cell corners.
    geo_minimum = [extent["xmin"] + delta_lon / 2, extent["ymin"] + delta_lat / 2]
    geo_maximum = [extent["xmax"] - delta_lon / 2, extent["ymax"] - delta_lat / 2]
    corners = [
        local_xy(lon, lat)
        for lon in (geo_minimum[0], geo_maximum[0])
        for lat in (geo_minimum[1], geo_maximum[1])
    ]
    minimum = [min(point[axis] for point in corners) for axis in range(2)]
    maximum = [max(point[axis] for point in corners) for axis in range(2)]
    geographic_grid = TerrainGrid(
        {
            "schema_version": 1,
            "width": width,
            "height": height,
            "bounds": {"min": geo_minimum, "max": geo_maximum},
            "origin_elevation_m": 0,
            "elevations_m": elevations,
        }
    )
    projection = LocalProjection(ORIGIN["longitude"], ORIGIN["latitude"])
    print(
        "Resampling geographic raster into the shared WGS84 local meter grid...",
        flush=True,
    )
    normalized_elevations = []
    for row in range(height):
        north = maximum[1] - row * (maximum[1] - minimum[1]) / (height - 1)
        for column in range(width):
            east = minimum[0] + column * (maximum[0] - minimum[0]) / (width - 1)
            longitude, latitude = projection.to_lonlat(east, north)
            elevation = geographic_grid.elevation_at(longitude, latitude)
            normalized_elevations.append(
                None if elevation is None else round(elevation, 3)
            )
    elevations = normalized_elevations
    retrieval = json.loads(
        export_path.with_suffix(".request.json").read_text(encoding="utf-8")
    )
    data = {
        "schema_version": 1,
        "origin": ORIGIN,
        "origin_elevation_m": 0,
        "coordinate_system": "local east, north, up; meters",
        "horizontal_projection": "WGS84 ECEF surface projected into City Hall east/north tangent plane",
        "vertical_datum": "USGS 3DEP source catalog; see catalog.json for source datums",
        "row_order": "north_to_south",
        "width": width,
        "height": height,
        "bounds": {"min": minimum, "max": maximum},
        "elevations_m": elevations,
        "source": {
            "title": "USGS 3DEP Bare Earth DEM",
            "url": SERVICE,
            "export_url": export_url,
            "retrieved_at": retrieval["retrieved_at"],
            "copyright": metadata.get("copyrightText"),
            "raster_sha256": hashlib.sha256(raster_path.read_bytes()).hexdigest(),
            "catalog": "catalog.json",
            "service_metadata": "service.json",
            "catalog_feature_count": len(catalog.get("features", [])),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resampling": "USGS bilinear WGS84 geographic export, then bilinear resampling into regular local east/north meters; rows run north to south and bounds refer to sample centers.",
        "coverage_note": "Initial rectangle covers mainland SF and Bay islands, not the Farallon Islands. Grid is resampled bare-earth data; no building or sidewalk detail is implied.",
    }
    origin_elevation = TerrainGrid(data).elevation_at(0, 0)
    if origin_elevation is None:
        raise ValueError(
            "USGS raster does not contain a valid City Hall origin elevation"
        )
    data["origin_elevation_m"] = round(origin_elevation, 3)
    target = output / "terrain.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    temporary.replace(target)
    valid = [value for value in elevations if value is not None]
    print(
        json.dumps(
            {
                "output": str(target),
                "size": [width, height],
                "bytes": target.stat().st_size,
                "origin_elevation_m": data["origin_elevation_m"],
                "range_m": [min(valid), max(valid)],
                "unknown_samples": len(elevations) - len(valid),
                "catalog_features": len(catalog.get("features", [])),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
