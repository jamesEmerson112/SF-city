import math

import pytest

from civic_center.terrain import TerrainGrid, local_xy


def grid(values=(30, 40, 10, 20)):
    return TerrainGrid(
        {
            "schema_version": 1,
            "width": 2,
            "height": 2,
            "bounds": {"min": [0, 0], "max": [10, 20]},
            "origin_elevation_m": 10,
            "elevations_m": list(values),
        }
    )


def test_bilinear_sampling_preserves_slope_and_north_row_order():
    terrain = grid()
    assert terrain.elevation_at(0, 20) == 30
    assert terrain.elevation_at(10, 0) == 20
    assert terrain.elevation_at(5, 10) == 25
    assert terrain.height_at(5, 10) == 15
    assert terrain.height_at(0, 0) == 0


def test_unknown_elevations_are_not_filled_or_clamped():
    terrain = grid((None, 40, 10, 20))
    assert terrain.elevation_at(0, 20) is None
    assert terrain.elevation_at(5, 10) is None
    assert terrain.elevation_at(10, 0) == 20
    assert terrain.elevation_at(-1, 0) is None
    assert terrain.elevation_at(0, 21) is None
    assert terrain.elevation_at(math.nan, 0) is None


def test_projection_origin_and_axis_directions():
    assert local_xy(-122.4193, 37.7793) == (0, 0)
    east, north = local_xy(-122.4183, 37.7803)
    assert 87 < east < 89
    assert 110 < north < 112


@pytest.mark.parametrize("values", [(1, 2, 3), (1, 2, math.inf, 4), (1, 2, True, 4)])
def test_malformed_elevation_grid_rejected(values):
    with pytest.raises(ValueError):
        grid(values)


def test_triangle_sampling_matches_northwest_southeast_mesh_diagonal():
    terrain = grid((0, 0, 0, 100))
    assert terrain.height_at(5, 10) == 15
    assert terrain.triangle_height_at(5, 10) == 40
    assert terrain.triangle_height_at(7.5, 15) == 15
    assert terrain.triangle_height_at(2.5, 5) == 15
    assert terrain.triangle_height_at(10, 0) == 90


def test_triangle_unknown_samples_are_not_filled_and_outside_is_not_clamped():
    terrain = grid((30, None, 10, 20))
    assert terrain.triangle_height_at(2.5, 5) == 7.5
    assert terrain.triangle_height_at(7.5, 15) is None
    assert terrain.triangle_height_at(5, 10) == 15
    assert terrain.triangle_height_at(-1, 0) is None
    assert terrain.triangle_height_at(0, math.nan) is None


def test_grid_and_diagonal_breakpoints_keep_whole_polyline_on_rendered_triangles():
    terrain = TerrainGrid({
        "schema_version": 1, "width": 3, "height": 3,
        "bounds": {"min": [0, 0], "max": [20, 20]},
        "origin_elevation_m": 0, "elevations_m": [10, 20, 60, 5, 50, 10, 0, 0, 20],
    })
    start, end = (1, 2), (19, 18)
    fractions = terrain.segment_fractions(start, end, max_spacing_m=7)
    assert fractions[0] == 0 and fractions[-1] == 1
    assert list(fractions) == sorted(set(fractions))
    points = []
    for fraction in fractions:
        x, y = [start[i] + fraction * (end[i] - start[i]) for i in range(2)]
        points.append((x, y, terrain.triangle_height_at(x, y)))
    for a, b in zip(points, points[1:]):
        assert 0 < math.dist(a, b) <= 7 + 1e-10
        for fraction in (.2, .5, .8):
            x, y, z = [a[i] + fraction * (b[i] - a[i]) for i in range(3)]
            assert terrain.triangle_height_at(x, y) == pytest.approx(z, abs=1e-9)


def test_segment_breakpoints_preserve_outside_unknown_and_grid_boundary_endpoints():
    terrain = grid()
    fractions = terrain.segment_fractions((-5, 10), (15, 10), max_spacing_m=100)
    assert .25 in fractions and .75 in fractions
    assert terrain.triangle_height_at(-5, 10) is None
    assert terrain.triangle_height_at(15, 10) is None
    diagonal = terrain.segment_fractions((0, 20), (10, 0), max_spacing_m=100)
    assert diagonal == (0, 1)
