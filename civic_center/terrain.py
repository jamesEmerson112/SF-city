"""Sample a documented elevation grid in the application's local meter frame."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .geography import LocalProjection

ORIGIN = {"longitude": -122.4193, "latitude": 37.7793}


def local_xy(
    longitude: float, latitude: float, origin: dict = ORIGIN
) -> tuple[float, float]:
    """Use exactly the same WGS84 tangent projection as street/footprint data."""
    point = LocalProjection(origin["longitude"], origin["latitude"]).to_local(
        longitude, latitude
    )
    return point[0], point[1]


class TerrainGrid:
    """North-to-south raster samples; unknown/outside elevations stay unknown."""

    def __init__(self, data: dict) -> None:
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported terrain schema")
        self.data = data
        self.width = data["width"]
        self.height = data["height"]
        if any(
            type(value) is not int or not 2 <= value <= 8192
            for value in (self.width, self.height)
        ):
            raise ValueError(
                "Terrain grid dimensions must be integers between 2 and 8192"
            )
        self.values = data["elevations_m"]
        if len(self.values) != self.width * self.height:
            raise ValueError("Terrain sample count does not match dimensions")
        if any(
            value is not None
            and (type(value) not in (int, float) or not math.isfinite(value))
            for value in self.values
        ):
            raise ValueError("Terrain elevations must be finite numbers or null")
        self.minimum = tuple(data["bounds"]["min"])
        self.maximum = tuple(data["bounds"]["max"])
        if (
            len(self.minimum) != 2
            or len(self.maximum) != 2
            or any(not math.isfinite(value) for value in (*self.minimum, *self.maximum))
            or any(self.minimum[i] >= self.maximum[i] for i in range(2))
        ):
            raise ValueError("Terrain bounds are invalid")
        self.origin_elevation_m = data["origin_elevation_m"]
        if type(self.origin_elevation_m) not in (int, float) or not math.isfinite(
            self.origin_elevation_m
        ):
            raise ValueError("Terrain origin elevation is invalid")
        self.step_x = (self.maximum[0] - self.minimum[0]) / (self.width - 1)
        self.step_y = (self.maximum[1] - self.minimum[1]) / (self.height - 1)

    @classmethod
    def load(cls, path: str | Path) -> "TerrainGrid":
        with Path(path).open(encoding="utf-8") as stream:
            return cls(json.load(stream))

    def elevation_at(self, east: float, north: float) -> float | None:
        """Bilinear absolute elevation; do not interpolate through missing data."""
        if not math.isfinite(east) or not math.isfinite(north):
            return None
        if not (
            self.minimum[0] <= east <= self.maximum[0]
            and self.minimum[1] <= north <= self.maximum[1]
        ):
            return None
        column = min((east - self.minimum[0]) / self.step_x, self.width - 1)
        row = min((self.maximum[1] - north) / self.step_y, self.height - 1)
        left = min(int(column), self.width - 2)
        top = min(int(row), self.height - 2)
        fraction_x, fraction_y = column - left, row - top
        neighbors = (
            (top * self.width + left, (1 - fraction_x) * (1 - fraction_y)),
            (top * self.width + left + 1, fraction_x * (1 - fraction_y)),
            ((top + 1) * self.width + left, (1 - fraction_x) * fraction_y),
            ((top + 1) * self.width + left + 1, fraction_x * fraction_y),
        )
        result = 0.0
        for index, weight in neighbors:
            if weight <= 1e-12:
                continue
            value = self.values[index]
            if value is None:
                return None
            result += value * weight
        return result

    def height_at(self, east: float, north: float) -> float | None:
        elevation = self.elevation_at(east, north)
        return None if elevation is None else elevation - self.origin_elevation_m

    def triangle_height_at(self, east: float, north: float) -> float | None:
        """Height on the detailed viewer mesh's northwest/southeast diagonal.

        ``height_at`` remains the bilinear raster reference. This method uses
        exactly the three vertices of the rendered triangle; unknown contributing
        samples remain unknown. Coordinates outside the raster are not clamped.
        """
        if not math.isfinite(east) or not math.isfinite(north):
            return None
        if not (self.minimum[0] <= east <= self.maximum[0] and self.minimum[1] <= north <= self.maximum[1]):
            return None
        column = min((east - self.minimum[0]) / self.step_x, self.width - 1)
        row = min((self.maximum[1] - north) / self.step_y, self.height - 1)
        left, top = min(int(column), self.width - 2), min(int(row), self.height - 2)
        u, v = column - left, row - top
        northwest = top * self.width + left
        southeast = (top + 1) * self.width + left + 1
        if u >= v:
            neighbors = ((northwest, 1 - u), (northwest + 1, u - v), (southeast, v))
        else:
            neighbors = ((northwest, 1 - v), (southeast - 1, v - u), (southeast, u))
        result = 0.0
        for index, weight in neighbors:
            if weight <= 1e-12:
                continue
            value = self.values[index]
            if value is None:
                return None
            result += value * weight
        return result - self.origin_elevation_m

    def segment_fractions(
        self, first: tuple[float, float], second: tuple[float, float],
        *, max_spacing_m: float = 20.0,
    ) -> tuple[float, ...]:
        """Split a line at raster grid/diagonal crossings and bounded spacing.

        Between consecutive fractions the line lies on one planar DEM triangle,
        so linear interpolation of its endpoint heights matches that triangle.
        Extra subdivisions bound 3D spacing when terrain is known, or horizontal
        spacing where it is unknown. This never fills missing elevations.
        """
        if type(max_spacing_m) not in (int, float) or not math.isfinite(max_spacing_m) or max_spacing_m <= 0:
            raise ValueError("max_spacing_m must be finite and positive")
        if not all(math.isfinite(value) for value in (*first[:2], *second[:2])):
            raise ValueError("segment coordinates must be finite")
        east, north = first[:2]
        dx, dy = second[0] - east, second[1] - north
        u0 = (east - self.minimum[0]) / self.step_x
        v0 = (self.maximum[1] - north) / self.step_y
        du, dv = dx / self.step_x, -dy / self.step_y
        fractions = {0.0, 1.0}
        for start, delta, dimension in ((u0, du, self.width), (v0, dv, self.height)):
            if abs(delta) <= 1e-15:
                continue
            low, high = sorted((start, start + delta))
            for coordinate in range(max(0, math.ceil(low)), min(dimension - 1, math.floor(high)) + 1):
                fraction = (coordinate - start) / delta
                if 1e-12 < fraction < 1 - 1e-12:
                    fractions.add(fraction)
        boundaries = sorted(fractions)
        if abs(du - dv) > 1e-15:
            for low, high in zip(boundaries, boundaries[1:]):
                middle = (low + high) / 2
                u, v = u0 + du * middle, v0 + dv * middle
                if not (0 <= u <= self.width - 1 and 0 <= v <= self.height - 1):
                    continue
                column = min(math.floor(u), self.width - 2)
                row = min(math.floor(v), self.height - 2)
                fraction = (column - row - (u0 - v0)) / (du - dv)
                if low + 1e-12 < fraction < high - 1e-12:
                    fractions.add(fraction)
        boundaries = sorted(fractions)
        for low, high in zip(boundaries, boundaries[1:]):
            a = east + dx * low, north + dy * low
            b = east + dx * high, north + dy * high
            az, bz = self.triangle_height_at(*a), self.triangle_height_at(*b)
            distance = math.dist(a, b) if az is None or bz is None else math.dist((*a, az), (*b, bz))
            pieces = max(1, math.ceil(distance / max_spacing_m))
            for index in range(1, pieces):
                fractions.add(low + (high - low) * index / pieces)
        # A horizontal/vertical grid crossing and diagonal can coincide within
        # floating precision. Keep one point rather than emitting a zero segment.
        result = []
        for fraction in sorted(fractions):
            if not result or fraction - result[-1] > 1e-12:
                result.append(fraction)
        if result[-1] != 1.0:
            result[-1] = 1.0
        return tuple(result)
