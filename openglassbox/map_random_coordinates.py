"""
Implementation of MapRandomCoordinates class for the OpenGlassBox engine.

This class generates random coordinates within a map grid, used primarily
for applying rules to random cells during simulation updates.
"""

from typing import List, Tuple, Optional
import random


class MapRandomCoordinates:
    """
    Helper class for generating random coordinates within a map.
    Used for rules that need to be applied to random map cells.
    """

    def __init__(self):
        """Initialize the random coordinate generator."""
        self.m_gridSizeU = 0
        self.m_gridSizeV = 0
        self.m_available_coordinates = []

    def init(self, grid_size_u: int, grid_size_v: int) -> None:
        """
        Initialize the random coordinate generator with grid dimensions.

        Args:
            grid_size_u: Size of the grid in U direction
            grid_size_v: Size of the grid in V direction
        """
        self.m_gridSizeU = grid_size_u
        self.m_gridSizeV = grid_size_v

        # Generate all available coordinates
        self.m_available_coordinates = []
        for v in range(grid_size_v):
            for u in range(grid_size_u):
                self.m_available_coordinates.append((u, v))

        # Shuffle for randomness
        random.shuffle(self.m_available_coordinates)

    def next(self) -> Tuple[bool, int, int]:
        """
        Get the next random coordinate.

        Returns:
            Tuple of (success, u, v)
            - success: True if a coordinate was returned, False if no more coordinates
            - u: U coordinate if found
            - v: V coordinate if found
        """
        if not self.m_available_coordinates:
            return False, 0, 0

        # Pop the next random coordinate
        next_u, next_v = self.m_available_coordinates.pop()
        return True, next_u, next_v

    def reset(self) -> None:
        """
        Reset the coordinate generator, re-initializing with the same grid dimensions.
        All coordinates become available again.
        """
        self.init(self.m_gridSizeU, self.m_gridSizeV)

    def remaining_count(self) -> int:
        """
        Get the number of remaining available coordinates.

        Returns:
            Number of coordinates that can still be returned by next()
        """
        return len(self.m_available_coordinates)

    def total_count(self) -> int:
        """
        Get the total number of coordinates in the grid.

        Returns:
            Total number of coordinates in the grid (width * height)
        """
        return self.m_gridSizeU * self.m_gridSizeV

    def pick_specific(self, u: int, v: int) -> bool:
        """
        Pick a specific coordinate, removing it from available coordinates.

        Args:
            u: The U coordinate to pick
            v: The V coordinate to pick

        Returns:
            True if the coordinate was available and has been removed,
            False if the coordinate was already used
        """
        if (u, v) in self.m_available_coordinates:
            self.m_available_coordinates.remove((u, v))
            return True
        return False
