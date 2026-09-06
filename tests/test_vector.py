"""
Test suite for Vector classes (Vector2D and Vector3D).

This file covers:
- Vector construction and initialization
- Basic vector operations (addition, subtraction, multiplication, division)
- Vector utility methods (magnitude, normalization, dot product, cross product)
- Vector comparison and equality
- Vector conversion operations

The tests ensure that vector operations work correctly and match the mathematical
expectations for vector arithmetic, serving as the foundation for spatial calculations
in the simulation.
"""

import pytest
import math
from typing import List, Tuple
from openglassbox.vector import Vector2D, Vector3D


def test_vector3d_initialization():
    # Default initialization to origin
    v1 = Vector3D()
    assert v1.x == 0.0
    assert v1.y == 0.0
    assert v1.z == 0.0

    # Initialization with specific values
    v2 = Vector3D(1.0, 2.0, 3.0)
    assert v2.x == 1.0
    assert v2.y == 2.0
    assert v2.z == 3.0

    # Initialization with integer values (should convert to float)
    v3 = Vector3D(1, 2, 3)
    assert v3.x == 1.0
    assert v3.y == 2.0
    assert v3.z == 3.0
    assert isinstance(v3.x, float)
    assert isinstance(v3.y, float)
    assert isinstance(v3.z, float)

def test_vector3d_equality():
    v1 = Vector3D(1.0, 2.0, 3.0)
    v2 = Vector3D(1.0, 2.0, 3.0)
    v3 = Vector3D(3.0, 2.0, 1.0)

    assert v1 == v2
    assert v1 != v3
    assert v2 != v3

    # Test with small floating point differences (should still be equal)
    v4 = Vector3D(1.0000001, 2.0, 3.0)
    assert v1 == v4  # Using epsilon comparison

def test_vector3d_addition():
    v1 = Vector3D(1.0, 2.0, 3.0)
    v2 = Vector3D(4.0, 5.0, 6.0)

    # Test addition operator
    result = v1 + v2
    assert result == Vector3D(5.0, 7.0, 9.0)

    # Test that the original vectors are unchanged
    assert v1 == Vector3D(1.0, 2.0, 3.0)
    assert v2 == Vector3D(4.0, 5.0, 6.0)

    # Test in-place addition
    v1 += v2
    assert v1 == Vector3D(5.0, 7.0, 9.0)
    assert v2 == Vector3D(4.0, 5.0, 6.0)  # v2 should be unchanged

def test_vector3d_subtraction():
    v1 = Vector3D(5.0, 7.0, 9.0)
    v2 = Vector3D(1.0, 2.0, 3.0)

    # Test subtraction operator
    result = v1 - v2
    assert result == Vector3D(4.0, 5.0, 6.0)

    # Test that the original vectors are unchanged
    assert v1 == Vector3D(5.0, 7.0, 9.0)
    assert v2 == Vector3D(1.0, 2.0, 3.0)

def test_vector3d_scalar_multiplication():
    v = Vector3D(1.0, 2.0, 3.0)

    # Test scalar multiplication
    result = v * 2.0
    assert result == Vector3D(2.0, 4.0, 6.0)

    # Test right multiplication
    result = 3.0 * v
    assert result == Vector3D(3.0, 6.0, 9.0)

    # Test that the original vector is unchanged
    assert v == Vector3D(1.0, 2.0, 3.0)

def test_vector3d_magnitude():
    # Zero vector
    v0 = Vector3D(0.0, 0.0, 0.0)
    assert v0.magnitude_squared() == 0.0
    assert v0.magnitude() == 0.0

    # Unit vectors
    vx = Vector3D(1.0, 0.0, 0.0)
    vy = Vector3D(0.0, 1.0, 0.0)
    vz = Vector3D(0.0, 0.0, 1.0)
    assert vx.magnitude() == 1.0
    assert vy.magnitude() == 1.0
    assert vz.magnitude() == 1.0

    # Pythagorean triple
    v = Vector3D(3.0, 4.0, 0.0)
    assert v.magnitude_squared() == 25.0
    assert v.magnitude() == 5.0

    # General case
    v = Vector3D(2.0, 3.0, 6.0)
    assert v.magnitude_squared() == 49.0
    assert v.magnitude() == 7.0

def test_vector3d_normalization():
    # Test normalizing non-zero vector
    v = Vector3D(3.0, 4.0, 0.0)
    normalized = v.normalized()
    assert normalized.magnitude() == pytest.approx(1.0)
    assert normalized == Vector3D(0.6, 0.8, 0.0)

    # Original vector should be unchanged
    assert v == Vector3D(3.0, 4.0, 0.0)

    # Test in-place normalization
    v.normalize()
    assert v.magnitude() == pytest.approx(1.0)
    assert v == Vector3D(0.6, 0.8, 0.0)

    # Test normalizing zero vector
    v0 = Vector3D(0.0, 0.0, 0.0)
    normalized = v0.normalized()
    assert normalized == Vector3D(0.0, 0.0, 0.0)

    # Test in-place normalization of zero vector
    v0 = Vector3D(0.0, 0.0, 0.0)
    v0.normalize()
    assert v0 == Vector3D(0.0, 0.0, 0.0)

def test_vector3d_dot_product():
    v1 = Vector3D(1.0, 2.0, 3.0)
    v2 = Vector3D(4.0, 5.0, 6.0)

    # Test dot product
    assert v1.dot(v2) == 32.0  # 1*4 + 2*5 + 3*6 = 4 + 10 + 18 = 32

    # Test perpendicular vectors (dot product should be 0)
    v3 = Vector3D(1.0, 0.0, 0.0)
    v4 = Vector3D(0.0, 1.0, 0.0)
    assert v3.dot(v4) == 0.0

def test_vector3d_cross_product():
    v1 = Vector3D(1.0, 0.0, 0.0)  # x unit vector
    v2 = Vector3D(0.0, 1.0, 0.0)  # y unit vector

    # Cross product should be z unit vector
    assert v1.cross(v2) == Vector3D(0.0, 0.0, 1.0)
    # Cross product is anti-commutative
    assert v2.cross(v1) == Vector3D(0.0, 0.0, -1.0)

    v3 = Vector3D(2.0, 3.0, 4.0)
    v4 = Vector3D(5.0, 6.0, 7.0)

    # Manually verify cross product
    cross_result = v3.cross(v4)
    expected = Vector3D(
        3.0 * 7.0 - 4.0 * 6.0,  # y1*z2 - z1*y2
        4.0 * 5.0 - 2.0 * 7.0,  # z1*x2 - x1*z2
        2.0 * 6.0 - 3.0 * 5.0   # x1*y2 - y1*x2
    )
    assert cross_result == expected

def test_vector3d_string_representation():
    v = Vector3D(1.0, 2.0, 3.0)

    # Test string representation
    assert str(v) == "(1.0, 2.0, 3.0)" or str(v) == "(1, 2, 3)"

    # Test repr
    assert repr(v) == "Vector3D(1.0, 2.0, 3.0)" or repr(v) == "Vector3D(1, 2, 3)"

def test_vector2d_initialization():
    # Default initialization to origin
    v1 = Vector2D()
    assert v1.x == 0.0
    assert v1.y == 0.0

    # Initialization with specific values
    v2 = Vector2D(1.0, 2.0)
    assert v2.x == 1.0
    assert v2.y == 2.0

    # Initialization with integer values (should convert to float)
    v3 = Vector2D(1, 2)
    assert v3.x == 1.0
    assert v3.y == 2.0
    assert isinstance(v3.x, float)
    assert isinstance(v3.y, float)

def test_vector2d_equality():
    v1 = Vector2D(1.0, 2.0)
    v2 = Vector2D(1.0, 2.0)
    v3 = Vector2D(2.0, 1.0)

    assert v1 == v2
    assert v1 != v3
    assert v2 != v3

    # Test with small floating point differences
    v4 = Vector2D(1.0000001, 2.0)
    assert v1 == v4  # Using epsilon comparison

def test_vector2d_addition():
    v1 = Vector2D(1.0, 2.0)
    v2 = Vector2D(3.0, 4.0)

    # Test addition operator
    result = v1 + v2
    assert result == Vector2D(4.0, 6.0)

    # Test that the original vectors are unchanged
    assert v1 == Vector2D(1.0, 2.0)
    assert v2 == Vector2D(3.0, 4.0)

    # Test in-place addition
    v1 += v2
    assert v1 == Vector2D(4.0, 6.0)
    assert v2 == Vector2D(3.0, 4.0)  # v2 should be unchanged

def test_vector2d_subtraction():
    v1 = Vector2D(4.0, 6.0)
    v2 = Vector2D(1.0, 2.0)

    # Test subtraction operator
    result = v1 - v2
    assert result == Vector2D(3.0, 4.0)

    # Test that the original vectors are unchanged
    assert v1 == Vector2D(4.0, 6.0)
    assert v2 == Vector2D(1.0, 2.0)

def test_vector2d_scalar_multiplication():
    v = Vector2D(1.0, 2.0)

    # Test scalar multiplication
    result = v * 2.0
    assert result == Vector2D(2.0, 4.0)

    # Test right multiplication
    result = 3.0 * v
    assert result == Vector2D(3.0, 6.0)

    # Test that the original vector is unchanged
    assert v == Vector2D(1.0, 2.0)

def test_vector2d_magnitude():
    # Zero vector
    v0 = Vector2D(0.0, 0.0)
    assert v0.magnitude_squared() == 0.0
    assert v0.magnitude() == 0.0

    # Unit vectors
    vx = Vector2D(1.0, 0.0)
    vy = Vector2D(0.0, 1.0)
    assert vx.magnitude() == 1.0
    assert vy.magnitude() == 1.0

    # Pythagorean triple
    v = Vector2D(3.0, 4.0)
    assert v.magnitude_squared() == 25.0
    assert v.magnitude() == 5.0

    # General case
    v = Vector2D(2.0, 3.0)
    assert v.magnitude_squared() == 13.0
    assert v.magnitude() == pytest.approx(3.605551275)  # sqrt(13) ≈ 3.6056

def test_vector2d_normalization():
    # Test normalizing non-zero vector
    v = Vector2D(3.0, 4.0)
    normalized = v.normalized()
    assert normalized.magnitude() == pytest.approx(1.0)
    assert normalized == Vector2D(0.6, 0.8)

    # Original vector should be unchanged
    assert v == Vector2D(3.0, 4.0)

    # Test in-place normalization
    v.normalize()
    assert v.magnitude() == pytest.approx(1.0)
    assert v == Vector2D(0.6, 0.8)

    # Test normalizing zero vector
    v0 = Vector2D(0.0, 0.0)
    normalized = v0.normalized()
    assert normalized == Vector2D(0.0, 0.0)

    # Test in-place normalization of zero vector
    v0 = Vector2D(0.0, 0.0)
    v0.normalize()
    assert v0 == Vector2D(0.0, 0.0)

def test_vector2d_dot_product():
    v1 = Vector2D(1.0, 2.0)
    v2 = Vector2D(3.0, 4.0)

    # Test dot product
    assert v1.dot(v2) == 11.0  # 1*3 + 2*4 = 3 + 8 = 11

    # Test perpendicular vectors (dot product should be 0)
    v3 = Vector2D(1.0, 0.0)
    v4 = Vector2D(0.0, 1.0)
    assert v3.dot(v4) == 0.0

def test_vector2d_string_representation():
    v = Vector2D(1.0, 2.0)

    # Test string representation
    assert str(v) == "(1.0, 2.0)" or str(v) == "(1, 2)"

    # Test repr
    assert repr(v) == "Vector2D(1.0, 2.0)" or repr(v) == "Vector2D(1, 2)"
