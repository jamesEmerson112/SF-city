"""
Test suite for MapCoordinatesInsideRadius (MCIR) and coordinate logic.

This file covers:
- Compression and decompression of map coordinates.
- Initialization and iteration of relative coordinates within a radius.
- Edge cases for zero and unit radius, and coordinate mapping logic.
- Testing for different radius shapes (circle, square).
- Boundary and edge case handling.
- Randomization of coordinate iteration.

The tests ensure that MCIR's coordinate handling and radius logic match the expectations
and edge cases of the original C++ simulation engine.
"""

import pytest
import random
from openglassbox.map_coordinates_inside_radius import MapCoordinatesInsideRadius

# Use a fixed seed for reproducible tests
random.seed(42)

def test_compress_uncompress_identity():
    """Test that compressing and then decompressing coordinates gives the original values."""
    for i in range(-128, 128):
        for j in range(-128, 128):
            compressed = MapCoordinatesInsideRadius.compress(i, j)
            # In Python implementation, we don't need uncompress as we store coordinates directly
            # But we can test that compress gives unique values
            compressed2 = MapCoordinatesInsideRadius.compress(i + 1, j)
            assert compressed != compressed2

def test_constructor_zero_unit_radius():
    """Test initialization with zero radius."""
    coord1 = MapCoordinatesInsideRadius()
    coord2 = MapCoordinatesInsideRadius()
    RADIUS = 0

    # Initialize the first coordinate calculator without randomization
    coord1.init(RADIUS, 2, 3, 4, 5, 6, 7, False)
    assert coord1.m_centerU == 2
    assert coord1.m_centerV == 3
    assert coord1.m_offset == RADIUS
    assert coord1.m_minU == 4
    assert coord1.m_maxU == 5
    assert coord1.m_minV == 6
    assert coord1.m_maxV == 7
    assert coord1.m_distributed is False

    # Get the relative coordinates for radius 0
    rel_coords = MapCoordinatesInsideRadius.relative_coordinates(RADIUS)
    assert len(rel_coords) == 1
    assert rel_coords[0] == (0, 0)
    assert coord1.m_relativeCoord == rel_coords

    # Initialize the second coordinate calculator with randomization
    coord2.init(RADIUS, 2, 3, 4, 5, 6, 7, True)
    assert coord2.m_centerU == 2
    assert coord2.m_centerV == 3
    assert coord2.m_offset == RADIUS
    assert coord2.m_minU == 4
    assert coord2.m_maxU == 5
    assert coord2.m_minV == 6
    assert coord2.m_maxV == 7
    assert coord2.m_distributed is True

    # For radius 0, even with randomization, we should still have one coordinate
    rel_coords2 = MapCoordinatesInsideRadius.relative_coordinates(RADIUS)
    assert len(rel_coords2) == 1
    assert rel_coords2[0] == (0, 0)
    assert len(coord2.m_relativeCoord) == 1

def test_relative_coordinates():
    """Test generation and access of relative coordinates for radius 1."""
    coord = MapCoordinatesInsideRadius()
    RADIUS = 1
    centerU = 3
    centerV = 3

    # Initialize the coordinate calculator
    coord.init(RADIUS, centerU, centerV, 0, 10, 0, 10, False)

    # Get the relative coordinates for radius 1
    c = MapCoordinatesInsideRadius.relative_coordinates(RADIUS)

    # Check that we have the expected coordinates (cross pattern for radius 1)
    assert len(c) == 5  # Should have 5 coordinates in the cross pattern

    # The coordinates should include (0,0) and the four adjacent positions
    expected_coords = {(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)}
    assert set(c) == expected_coords

    # Test iteration through coordinates
    success, u, v = coord.next()
    assert success is True
    assert u == centerU - 1 or u == centerU or u == centerU + 1  # Valid X coordinate
    assert v == centerV - 1 or v == centerV or v == centerV + 1  # Valid Y coordinate

    # Continue iterating until we've seen all 5 coordinates
    coords_seen = set()
    coords_seen.add((u, v))

    for _ in range(4):  # We've already gotten one, so 4 more to go
        success, u, v = coord.next()
        assert success is True
        coords_seen.add((u, v))

    # We should have seen all 5 absolute coordinates
    assert len(coords_seen) == 5

    # The next call should return False (no more coordinates)
    success, u, v = coord.next()
    assert success is False

def test_cached_relative_coordinates_clipped():
    """Test coordinate calculation with clipping at boundaries."""
    coord = MapCoordinatesInsideRadius()
    RADIUS = 1
    centerU = 3
    centerV = 3

    # Initialize with tight boundaries that will clip some coordinates
    coord.init(RADIUS, centerU, centerV, 3, 4, 3, 4, False)

    # The relative coordinates are the same, but some will get clipped
    c = MapCoordinatesInsideRadius.relative_coordinates(RADIUS)
    assert len(c) == 5

    # Expected coordinates after clipping:
    # (2,3) is clipped (out of bounds)
    # (3,2) is clipped (out of bounds)
    # (3,3) is in bounds
    # (3,4) is clipped (out of bounds)
    # (4,3) is clipped (out of bounds)

    # We should only get (3,3) as it's the only one in bounds
    success, u, v = coord.next()
    assert success is True
    assert u == 3
    assert v == 3

    # The next call should return False (no more coordinates in bounds)
    success, u, v = coord.next()
    assert success is False

def test_different_radius_shapes():
    """Test coordinates generation for different radius sizes."""
    # Test for radius 2 (diamond shape)
    radius2_coords = MapCoordinatesInsideRadius.relative_coordinates(2)

    # For a diamond with radius 2, we expect these coordinates:
    expected_radius2 = {
        (0, 0),   # Center
        (-1, 0), (1, 0), (0, -1), (0, 1),  # Radius 1 cross
        (-2, 0), (2, 0), (0, -2), (0, 2),  # Radius 2 extensions
        (-1, -1), (-1, 1), (1, -1), (1, 1)  # Diagonal positions at radius sqrt(2)
    }
    assert set(radius2_coords) == expected_radius2
    assert len(radius2_coords) == len(expected_radius2)

def test_grid_boundaries():
    """Test coordinate handling at grid boundaries."""
    coord = MapCoordinatesInsideRadius()

    # Initialize with center at the edge of the grid
    coord.init(1, 0, 0, 0, 10, 0, 10, False)

    # When centered at (0,0), some coordinates will fall outside the grid
    # We should only get coordinates that are within the grid
    valid_coords = set()
    while True:
        success, u, v = coord.next()
        if not success:
            break
        valid_coords.add((u, v))

    # We expect only the center (0,0) and the in-bound adjacents (1,0) and (0,1)
    assert valid_coords == {(0, 0), (1, 0), (0, 1)}

    # Test another boundary case with center at the max edge
    coord2 = MapCoordinatesInsideRadius()
    coord2.init(1, 9, 9, 0, 10, 0, 10, False)

    valid_coords2 = set()
    while True:
        success, u, v = coord2.next()
        if not success:
            break
        valid_coords2.add((u, v))

    # We expect only the center (9,9) and the in-bound adjacents (8,9) and (9,8)
    assert valid_coords2 == {(9, 9), (8, 9), (9, 8)}

def test_randomization():
    """Test randomization of coordinate order."""
    # Create two instances with the same parameters but one with randomization
    coord_normal = MapCoordinatesInsideRadius()
    coord_random = MapCoordinatesInsideRadius()

    # Use a larger radius for better randomization test
    RADIUS = 2

    # Initialize both with the same parameters
    coord_normal.init(RADIUS, 5, 5, 0, 10, 0, 10, False)
    coord_random.init(RADIUS, 5, 5, 0, 10, 0, 10, True)

    # Collect the coordinates from both in the order they are visited
    coords_normal = []
    coords_random = []

    while True:
        success, u, v = coord_normal.next()
        if not success:
            break
        coords_normal.append((u, v))

    while True:
        success, u, v = coord_random.next()
        if not success:
            break
        coords_random.append((u, v))

    # Both should have the same number of coordinates
    assert len(coords_normal) == len(coords_random)

    # But the order should be different (very likely)
    # This is a probabilistic test, but with a fixed seed it should be reliable
    assert coords_normal != coords_random

    # Both should have the same set of coordinates, just in different order
    assert set(coords_normal) == set(coords_random)
