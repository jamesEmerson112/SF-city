"""
Vector module for OpenGlassBox simulation engine.

This module implements 2D and 3D vector classes with comprehensive functionality
for spatial calculations used throughout the simulation engine.
"""

import math
from typing import Union, Tuple, Optional, Any


class Vector2D:
    """
    A two-dimensional vector class with standard vector operations.

    Provides complete functionality for 2D vector arithmetic, comparison,
    normalization, dot products, and other common vector operations.
    """

    def __init__(self, x: Union[int, float] = 0.0, y: Union[int, float] = 0.0):
        """
        Initialize a 2D vector with the given coordinates.

        Args:
            x: The x coordinate (defaults to 0)
            y: The y coordinate (defaults to 0)
        """
        self.x = float(x)
        self.y = float(y)

    def __eq__(self, other: Any) -> bool:
        """
        Check if this vector is equal to another vector.

        Uses a small epsilon value for floating point comparison to handle
        potential floating point inaccuracies.

        Args:
            other: The vector to compare with

        Returns:
            True if vectors are equal, False otherwise
        """
        if not isinstance(other, Vector2D):
            return False
        return (abs(self.x - other.x) < 1e-6 and
                abs(self.y - other.y) < 1e-6)

    def __add__(self, other: 'Vector2D') -> 'Vector2D':
        """
        Add another vector to this vector.

        Args:
            other: The vector to add

        Returns:
            A new vector that is the sum of the two vectors
        """
        if isinstance(other, Vector2D):
            return Vector2D(self.x + other.x, self.y + other.y)
        return NotImplemented

    def __iadd__(self, other: 'Vector2D') -> 'Vector2D':
        """
        Add another vector to this vector in-place.

        Args:
            other: The vector to add

        Returns:
            This vector after addition
        """
        if isinstance(other, Vector2D):
            self.x += other.x
            self.y += other.y
            return self
        return NotImplemented

    def __sub__(self, other: 'Vector2D') -> 'Vector2D':
        """
        Subtract another vector from this vector.

        Args:
            other: The vector to subtract

        Returns:
            A new vector that is the difference of the two vectors
        """
        if isinstance(other, Vector2D):
            return Vector2D(self.x - other.x, self.y - other.y)
        return NotImplemented

    def __mul__(self, scalar: Union[int, float]) -> 'Vector2D':
        """
        Multiply this vector by a scalar.

        Args:
            scalar: The scalar to multiply by

        Returns:
            A new vector that is the product of this vector and the scalar
        """
        if isinstance(scalar, (int, float)):
            return Vector2D(self.x * scalar, self.y * scalar)
        return NotImplemented

    def __rmul__(self, scalar: Union[int, float]) -> 'Vector2D':
        """
        Multiply this vector by a scalar (right multiplication).

        Args:
            scalar: The scalar to multiply by

        Returns:
            A new vector that is the product of this vector and the scalar
        """
        return self.__mul__(scalar)

    def __truediv__(self, scalar: Union[int, float]) -> 'Vector2D':
        """
        Divide this vector by a scalar.

        Args:
            scalar: The scalar to divide by

        Returns:
            A new vector that is the quotient of this vector and the scalar

        Raises:
            ZeroDivisionError: If scalar is zero
        """
        if scalar == 0:
            raise ZeroDivisionError("Division by zero")
        return Vector2D(self.x / scalar, self.y / scalar)

    def __str__(self) -> str:
        """
        Get a string representation of this vector.

        Returns:
            A string representation of this vector (e.g., "(1.0, 2.0)")
        """
        return f"({self.x}, {self.y})"

    def __repr__(self) -> str:
        """
        Get a string representation of this vector for debugging.

        Returns:
            A string representation of this vector (e.g., "Vector2D(1.0, 2.0)")
        """
        return f"Vector2D({self.x}, {self.y})"

    def dot(self, other: 'Vector2D') -> float:
        """
        Calculate the dot product of this vector and another vector.

        Args:
            other: The other vector

        Returns:
            The dot product
        """
        if isinstance(other, Vector2D):
            return self.x * other.x + self.y * other.y
        return NotImplemented

    def magnitude_squared(self) -> float:
        """
        Calculate the squared magnitude (length) of this vector.

        This is more efficient than calculating the magnitude when only
        comparing magnitudes, as it avoids the square root operation.

        Returns:
            The squared magnitude of this vector
        """
        return self.x * self.x + self.y * self.y

    def magnitude(self) -> float:
        """
        Calculate the magnitude (length) of this vector.

        Returns:
            The magnitude of this vector
        """
        return math.sqrt(self.magnitude_squared())

    def normalized(self) -> 'Vector2D':
        """
        Get a normalized (unit) vector in the same direction as this vector.

        Returns:
            A new vector that is the normalized version of this vector, or
            a zero vector if this vector's magnitude is close to zero
        """
        mag = self.magnitude()
        if mag < 1e-6:  # Avoid division by near-zero
            return Vector2D(0, 0)
        return Vector2D(self.x / mag, self.y / mag)

    def normalize(self) -> 'Vector2D':
        """
        Normalize this vector in-place (make it a unit vector).

        Returns:
            This vector after normalization, or unchanged if magnitude is close to zero
        """
        mag = self.magnitude()
        if mag < 1e-6:  # Avoid division by near-zero
            self.x = self.y = 0
            return self
        self.x /= mag
        self.y /= mag
        return self

    def distance_to(self, other: 'Vector2D') -> float:
        """
        Calculate the distance between this vector and another vector.

        Args:
            other: The other vector

        Returns:
            The distance between the vectors
        """
        return (self - other).magnitude()

    def distance_squared_to(self, other: 'Vector2D') -> float:
        """
        Calculate the squared distance between this vector and another vector.

        This is more efficient than calculating the distance when only
        comparing distances, as it avoids the square root operation.

        Args:
            other: The other vector

        Returns:
            The squared distance between the vectors
        """
        return (self - other).magnitude_squared()

    def lerp(self, other: 'Vector2D', t: float) -> 'Vector2D':
        """
        Linearly interpolate between this vector and another vector.

        Args:
            other: The other vector
            t: The interpolation parameter (0.0 = this vector, 1.0 = other vector)

        Returns:
            A new vector that is the interpolation between the two vectors
        """
        return Vector2D(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t
        )

    def to_tuple(self) -> Tuple[float, float]:
        """
        Convert this vector to a tuple.

        Returns:
            A tuple containing the vector components (x, y)
        """
        return (self.x, self.y)

    @classmethod
    def from_tuple(cls, tup: Tuple[Union[int, float], Union[int, float]]) -> 'Vector2D':
        """
        Create a vector from a tuple.

        Args:
            tup: A tuple containing the vector components (x, y)

        Returns:
            A new vector with the specified components
        """
        return cls(tup[0], tup[1])


class Vector3D:
    """
    A three-dimensional vector class with standard vector operations.

    Provides complete functionality for 3D vector arithmetic, comparison,
    normalization, dot/cross products, and other common vector operations.
    """

    def __init__(self, x: Union[int, float] = 0.0, y: Union[int, float] = 0.0, z: Union[int, float] = 0.0):
        """
        Initialize a 3D vector with the given coordinates.

        Args:
            x: The x coordinate (defaults to 0)
            y: The y coordinate (defaults to 0)
            z: The z coordinate (defaults to 0)
        """
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __eq__(self, other: Any) -> bool:
        """
        Check if this vector is equal to another vector.

        Uses a small epsilon value for floating point comparison to handle
        potential floating point inaccuracies.

        Args:
            other: The vector to compare with

        Returns:
            True if vectors are equal, False otherwise
        """
        if not isinstance(other, Vector3D):
            return False
        return (abs(self.x - other.x) < 1e-6 and
                abs(self.y - other.y) < 1e-6 and
                abs(self.z - other.z) < 1e-6)

    def __add__(self, other: 'Vector3D') -> 'Vector3D':
        """
        Add another vector to this vector.

        Args:
            other: The vector to add

        Returns:
            A new vector that is the sum of the two vectors
        """
        if isinstance(other, Vector3D):
            return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)
        return NotImplemented

    def __iadd__(self, other: 'Vector3D') -> 'Vector3D':
        """
        Add another vector to this vector in-place.

        Args:
            other: The vector to add

        Returns:
            This vector after addition
        """
        if isinstance(other, Vector3D):
            self.x += other.x
            self.y += other.y
            self.z += other.z
            return self
        return NotImplemented

    def __sub__(self, other: 'Vector3D') -> 'Vector3D':
        """
        Subtract another vector from this vector.

        Args:
            other: The vector to subtract

        Returns:
            A new vector that is the difference of the two vectors
        """
        if isinstance(other, Vector3D):
            return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)
        return NotImplemented

    def __mul__(self, scalar: Union[int, float]) -> 'Vector3D':
        """
        Multiply this vector by a scalar.

        Args:
            scalar: The scalar to multiply by

        Returns:
            A new vector that is the product of this vector and the scalar
        """
        if isinstance(scalar, (int, float)):
            return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)
        return NotImplemented

    def __rmul__(self, scalar: Union[int, float]) -> 'Vector3D':
        """
        Multiply this vector by a scalar (right multiplication).

        Args:
            scalar: The scalar to multiply by

        Returns:
            A new vector that is the product of this vector and the scalar
        """
        return self.__mul__(scalar)

    def __truediv__(self, scalar: Union[int, float]) -> 'Vector3D':
        """
        Divide this vector by a scalar.

        Args:
            scalar: The scalar to divide by

        Returns:
            A new vector that is the quotient of this vector and the scalar

        Raises:
            ZeroDivisionError: If scalar is zero
        """
        if scalar == 0:
            raise ZeroDivisionError("Division by zero")
        return Vector3D(self.x / scalar, self.y / scalar, self.z / scalar)

    def __str__(self) -> str:
        """
        Get a string representation of this vector.

        Returns:
            A string representation of this vector (e.g., "(1.0, 2.0, 3.0)")
        """
        return f"({self.x}, {self.y}, {self.z})"

    def __repr__(self) -> str:
        """
        Get a string representation of this vector for debugging.

        Returns:
            A string representation of this vector (e.g., "Vector3D(1.0, 2.0, 3.0)")
        """
        return f"Vector3D({self.x}, {self.y}, {self.z})"

    def dot(self, other: 'Vector3D') -> float:
        """
        Calculate the dot product of this vector and another vector.

        Args:
            other: The other vector

        Returns:
            The dot product
        """
        if isinstance(other, Vector3D):
            return self.x * other.x + self.y * other.y + self.z * other.z
        return NotImplemented

    def cross(self, other: 'Vector3D') -> 'Vector3D':
        """
        Calculate the cross product of this vector and another vector.

        Args:
            other: The other vector

        Returns:
            A new vector that is the cross product of the two vectors
        """
        if isinstance(other, Vector3D):
            return Vector3D(
                self.y * other.z - self.z * other.y,
                self.z * other.x - self.x * other.z,
                self.x * other.y - self.y * other.x
            )
        return NotImplemented

    def magnitude_squared(self) -> float:
        """
        Calculate the squared magnitude (length) of this vector.

        This is more efficient than calculating the magnitude when only
        comparing magnitudes, as it avoids the square root operation.

        Returns:
            The squared magnitude of this vector
        """
        return self.x * self.x + self.y * self.y + self.z * self.z

    def magnitude(self) -> float:
        """
        Calculate the magnitude (length) of this vector.

        Returns:
            The magnitude of this vector
        """
        return math.sqrt(self.magnitude_squared())

    def normalized(self) -> 'Vector3D':
        """
        Get a normalized (unit) vector in the same direction as this vector.

        Returns:
            A new vector that is the normalized version of this vector, or
            a zero vector if this vector's magnitude is close to zero
        """
        mag = self.magnitude()
        if mag < 1e-6:  # Avoid division by near-zero
            return Vector3D(0, 0, 0)
        return Vector3D(self.x / mag, self.y / mag, self.z / mag)

    def normalize(self) -> 'Vector3D':
        """
        Normalize this vector in-place (make it a unit vector).

        Returns:
            This vector after normalization, or unchanged if magnitude is close to zero
        """
        mag = self.magnitude()
        if mag < 1e-6:  # Avoid division by near-zero
            self.x = self.y = self.z = 0
            return self
        self.x /= mag
        self.y /= mag
        self.z /= mag
        return self

    def distance_to(self, other: 'Vector3D') -> float:
        """
        Calculate the distance between this vector and another vector.

        Args:
            other: The other vector

        Returns:
            The distance between the vectors
        """
        return (self - other).magnitude()

    def distance_squared_to(self, other: 'Vector3D') -> float:
        """
        Calculate the squared distance between this vector and another vector.

        This is more efficient than calculating the distance when only
        comparing distances, as it avoids the square root operation.

        Args:
            other: The other vector

        Returns:
            The squared distance between the vectors
        """
        return (self - other).magnitude_squared()

    def lerp(self, other: 'Vector3D', t: float) -> 'Vector3D':
        """
        Linearly interpolate between this vector and another vector.

        Args:
            other: The other vector
            t: The interpolation parameter (0.0 = this vector, 1.0 = other vector)

        Returns:
            A new vector that is the interpolation between the two vectors
        """
        return Vector3D(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
            self.z + (other.z - self.z) * t
        )

    def to_tuple(self) -> Tuple[float, float, float]:
        """
        Convert this vector to a tuple.

        Returns:
            A tuple containing the vector components (x, y, z)
        """
        return (self.x, self.y, self.z)

    def to_vector2d(self) -> Vector2D:
        """
        Project this vector to a 2D vector by dropping the z component.

        Returns:
            A new 2D vector with the x and y components of this vector
        """
        return Vector2D(self.x, self.y)

    @classmethod
    def from_tuple(cls, tup: Tuple[Union[int, float], Union[int, float], Union[int, float]]) -> 'Vector3D':
        """
        Create a vector from a tuple.

        Args:
            tup: A tuple containing the vector components (x, y, z)

        Returns:
            A new vector with the specified components
        """
        return cls(tup[0], tup[1], tup[2])

    @classmethod
    def from_vector2d(cls, v: Vector2D, z: Union[int, float] = 0.0) -> 'Vector3D':
        """
        Create a 3D vector from a 2D vector and a z coordinate.

        Args:
            v: The 2D vector
            z: The z coordinate (defaults to 0)

        Returns:
            A new 3D vector with the specified components
        """
        return cls(v.x, v.y, z)


# Aliases for compatibility with original C++ class names
Vector3f = Vector3D
