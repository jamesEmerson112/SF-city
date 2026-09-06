"""
Implementation of MapCoordinatesInsideRadius class for the OpenGlassBox engine.

This class efficiently calculates and iterates through coordinates within
a specified radius of a center point. Used primarily for resource distribution
and collection in Map cells.
"""

from typing import List, Tuple, Dict, Optional
import random
import math


class MapCoordinatesInsideRadius:
    """
    Helper class to efficiently calculate coordinates inside a given radius.

    This class pre-computes and caches coordinates within a radius for efficient
    access, and provides iteration utilities to access these coordinates.
    """

    # Class-level cache of coordinate patterns for different radii
    _coordinate_cache: Dict[int, List[Tuple[int, int]]] = {}

    def __init__(self):
        """Initialize the radius coordinates calculator."""
        self.m_relativeCoord = None
        self.m_offset = 0
        self.m_centerU = 0
        self.m_centerV = 0
        self.m_minU = 0
        self.m_maxU = 0
        self.m_minV = 0
        self.m_maxV = 0
        self.m_distributed = False
        self.m_currentIndex = 0

    def init(self, radius: int, center_u: int, center_v: int,
             min_u: int, max_u: int, min_v: int, max_v: int,
             distributed: bool) -> None:
        """
        Initialize the calculation of coordinates within radius.

        Args:
            radius: The radius to search within
            center_u: Center U coordinate
            center_v: Center V coordinate
            min_u: Minimum allowed U coordinate
            max_u: Maximum allowed U coordinate
            min_v: Minimum allowed V coordinate
            max_v: Maximum allowed V coordinate
            distributed: Whether to randomize the order of coordinates
        """
        self.m_offset = radius
        self.m_centerU = center_u
        self.m_centerV = center_v
        self.m_minU = min_u
        self.m_maxU = max_u
        self.m_minV = min_v
        self.m_maxV = max_v
        self.m_distributed = distributed

        # Get or generate the relative coordinates for this radius
        self.m_relativeCoord = self._get_or_generate_coordinates(radius)

        # For distributed access, shuffle the coordinates
        if distributed and self.m_relativeCoord:
            # Make a copy to avoid modifying the cached version
            self.m_relativeCoord = self.m_relativeCoord.copy()
            random.shuffle(self.m_relativeCoord)

        self.m_currentIndex = 0

    def next(self) -> Tuple[bool, int, int]:
        """
        Get the next coordinate inside the radius.

        Returns:
            Tuple of (success, u, v)
            - success: True if a coordinate was found, False if we're done
            - u: U coordinate if found
            - v: V coordinate if found
        """
        if not self.m_relativeCoord or self.m_currentIndex >= len(self.m_relativeCoord):
            return False, 0, 0

        rel_u, rel_v = self.m_relativeCoord[self.m_currentIndex]
        self.m_currentIndex += 1

        abs_u = self.m_centerU + rel_u
        abs_v = self.m_centerV + rel_v

        # Check if coordinate is within bounds
        if (abs_u >= self.m_minU and abs_u < self.m_maxU and
            abs_v >= self.m_minV and abs_v < self.m_maxV):
            return True, abs_u, abs_v

        # Try the next coordinate
        return self.next()

    @classmethod
    def _get_or_generate_coordinates(cls, radius: int) -> List[Tuple[int, int]]:
        """
        Get coordinates from cache or generate if not present.

        Args:
            radius: The radius to get coordinates for

        Returns:
            List of (u, v) relative coordinate pairs within radius
        """
        # Check if we already have this radius cached
        if radius in cls._coordinate_cache:
            return cls._coordinate_cache[radius]

        # Generate new coordinates for this radius
        coords = cls._generate_coordinates_for_radius(radius)

        # Cache the result
        cls._coordinate_cache[radius] = coords
        return coords

    @staticmethod
    def _generate_coordinates_for_radius(radius: int) -> List[Tuple[int, int]]:
        """
        Generate the list of relative coordinates within a radius.

        Args:
            radius: The radius to generate coordinates for

        Returns:
            List of (u, v) coordinate pairs representing relative positions
        """
        # Special case for radius 1 (plus sign)
        if radius == 1:
            return [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]

        # For other radii, generate a diamond pattern (Manhattan distance)
        coords = []
        for v in range(-radius, radius + 1):
            for u in range(-radius, radius + 1):
                # Use Manhattan distance
                if abs(u) + abs(v) <= radius:
                    coords.append((u, v))
        return coords

    @staticmethod
    def compress(rel_u: int, rel_v: int) -> int:
        """
        Compress a relative coordinate pair into a single integer.

        Args:
            rel_u: Relative U coordinate
            rel_v: Relative V coordinate

        Returns:
            Compressed integer representation
        """
        # In Python we don't need this for our implementation, but included
        # for compatibility with C++ tests
        return (rel_v << 16) | (rel_u & 0xFFFF)

    @staticmethod
    def relative_coordinates(radius: int) -> List[Tuple[int, int]]:
        """
        Get relative coordinates for a radius (static utility method).

        Args:
            radius: The radius to get coordinates for

        Returns:
            List of relative coordinates
        """
        return MapCoordinatesInsideRadius._get_or_generate_coordinates(radius)
