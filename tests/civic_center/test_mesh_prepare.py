import pytest

pytest.importorskip("mapbox_earcut")

from civic_center.mesh_prepare import signed_area, triangulate_rings


def test_roof_keeps_courtyard_open_and_preserves_area():
    result = triangulate_rings(
        [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
        ]
    )
    assert result["roof_area_m2"] == 84
    vertices, indices = result["roof_vertices"], result["roof_triangles"]
    for offset in range(0, len(indices), 3):
        points = [vertices[index] for index in indices[offset : offset + 3]]
        x, y = [sum(point[axis] for point in points) / 3 for axis in (0, 1)]
        assert not (3 < x < 7 and 3 < y < 7)
        assert abs(signed_area(points)) > 0


def test_concave_roof_preserves_notch():
    result = triangulate_rings([[[0, 0], [5, 0], [5, 1], [1, 1], [1, 5], [0, 5]]])
    assert result["roof_area_m2"] == 9


def test_degenerate_roof_is_rejected():
    with pytest.raises(ValueError, match="degenerate"):
        triangulate_rings([[[0, 0], [1, 0], [2, 0]]])
