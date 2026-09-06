"""Offline polygon triangulation for buildings with preserved courtyard holes."""

from __future__ import annotations

import math


def signed_area(ring: list) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2


def triangulate_rings(rings: list) -> dict:
    """Return explicit roof vertices/indices after checking conserved roof area."""
    import mapbox_earcut
    import numpy as np

    if not rings:
        raise ValueError("A roof needs an outer ring")
    cleaned = []
    for original in rings:
        ring = []
        for point in original:
            if len(point) < 2 or any(
                not math.isfinite(float(value)) for value in point[:2]
            ):
                raise ValueError("Roof coordinates must be finite")
            position = [
                float(point[0]),
                float(point[1]),
                float(point[2]) if len(point) > 2 else 0.0,
            ]
            if not ring or position[:2] != ring[-1][:2]:
                ring.append(position)
        if len(ring) > 1 and ring[0][:2] == ring[-1][:2]:
            ring.pop()
        if len(ring) < 3 or abs(signed_area(ring)) < 1e-8:
            raise ValueError("Roof ring is degenerate")
        cleaned.append(ring)
    points = [point for ring in cleaned for point in ring]
    ends = np.cumsum([len(ring) for ring in cleaned], dtype=np.uint32)
    indices = mapbox_earcut.triangulate_float64(
        np.asarray([point[:2] for point in points], dtype=np.float64), ends
    ).tolist()
    expected_area = abs(signed_area(cleaned[0])) - sum(
        abs(signed_area(ring)) for ring in cleaned[1:]
    )
    if expected_area <= 0 or not indices or len(indices) % 3:
        raise ValueError("Roof polygon has no valid surface")
    actual_area = 0.0
    for start in range(0, len(indices), 3):
        triangle = [points[index] for index in indices[start : start + 3]]
        actual_area += abs(signed_area(triangle))
    if not math.isclose(actual_area, expected_area, rel_tol=1e-7, abs_tol=1e-5):
        raise ValueError("Roof triangulation did not preserve polygon/courtyard area")
    return {
        "roof_vertices": points,
        "roof_triangles": indices,
        "roof_area_m2": round(actual_area, 6),
        "ring_count": len(cleaned),
    }
