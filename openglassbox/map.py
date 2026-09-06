"""
Map class for OpenGlassBox simulation engine.

This module defines the Map class which represents a grid-based resource distribution
system in the simulation. Maps store resources in cells and provide methods for
adding, removing, and querying resources within regions.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

from .vector import Vector3f
from .map_coordinates_inside_radius import MapCoordinatesInsideRadius
from .map_random_coordinates import MapRandomCoordinates
from .resource import Resource
from .rule import RuleContext
from . import config


@dataclass
class MapType:
    """Type definition for Maps in the simulation."""
    name: str
    color: int = 0xFFFFFF
    capacity: int = 2147483647  # Resource.MAX_CAPACITY (2^31 - 1)
    rules: List[Any] = field(default_factory=list)


class Map:
    """
    Grid-based resource management system.

    Maps represent resources distributed across a 2D grid. Each cell in the grid
    can contain a certain amount of a resource, up to the map's capacity.
    Maps handle resource spreading, querying, and applying rules.
    """

    def __init__(self, map_type: MapType, city: Any):
        """
        Create a new Map instance.

        Args:
            map_type: The type of map (defines capacity, color, rules)
            city: The city containing this map
        """
        self.m_type = map_type
        self.m_position = city.position()
        self.m_gridSizeU = city.grid_size_u()
        self.m_gridSizeV = city.grid_size_v()

        # Initialize resources with zero in each cell
        self.m_resources = [0] * (self.m_gridSizeU * self.m_gridSizeV)

        # Initialize context for rule execution
        self.m_context = RuleContext()
        self.m_context.city = city

        # Initialize tick counter for rule execution
        self.m_ticks = 0

        # Initialize coordinate caches
        self.m_coordinates = MapCoordinatesInsideRadius()
        self.m_randomCoordinates = MapRandomCoordinates()

    def set_resource(self, u: int, v: int, amount: int) -> None:
        """
        Set the resource amount at the specified grid cell.

        Args:
            u: Grid U coordinate
            v: Grid V coordinate
            amount: Resource amount to set
        """
        # Clamp amount to capacity
        if amount > self.m_type.capacity:
            amount = self.m_type.capacity

        # Update resource amount with optimization check (like C++)
        index = v * self.m_gridSizeU + u
        if index < len(self.m_resources):
            if self.m_resources[index] != amount:
                self.m_resources[index] = amount

    def get_resource(self, u: int, v: int, radius: Optional[int] = None) -> int:
        """
        Get the resource amount at the specified grid cell.

        Args:
            u: Grid U coordinate
            v: Grid V coordinate
            radius: Optional radius to sum resources within

        Returns:
            Resource amount at the cell or sum of resources within radius
        """
        if radius is None:
            # Get single cell resource
            index = v * self.m_gridSizeU + u
            if 0 <= index < len(self.m_resources):
                return self.m_resources[index]
            return 0
        else:
            # Sum resources within radius
            total = 0
            x, y = u, v
            self.m_coordinates.init(radius, x, y, 0, self.m_gridSizeU, 0, self.m_gridSizeV, False)

            success, x, y = self.m_coordinates.next()
            while success:
                total += self.get_resource(x, y)
                success, x, y = self.m_coordinates.next()

            return total

    def add_resource(self, u: int, v: int, to_add: int, radius: Optional[int] = None, distributed: bool = True) -> None:
        """
        Add resources to the specified grid cell or within radius.

        Args:
            u: Grid U coordinate
            v: Grid V coordinate
            to_add: Amount of resource to add
            radius: Optional radius to add resources within
            distributed: If True, distribute resources among cells; if False, add to all cells
        """
        if radius is None:
            # Add to single cell
            amount = self.get_resource(u, v)

            # Avoid integer overflow
            if amount >= Resource.MAX_CAPACITY - to_add:
                amount = Resource.MAX_CAPACITY
            else:
                amount += to_add

            self.set_resource(u, v, amount)
        else:
            # Add to cells within radius
            remaining = to_add
            x, y = u, v

            self.m_coordinates.init(radius, x, y, 0, self.m_gridSizeU, 0, self.m_gridSizeV, distributed)
            success, x, y = self.m_coordinates.next()
            while (remaining > 0) and success:
                amount = self.get_resource(x, y)
                add_amount = min(self.m_type.capacity - amount, remaining)

                if add_amount > 0:
                    amount += add_amount
                    if distributed:
                        remaining -= add_amount
                    self.set_resource(x, y, amount)
                success, x, y = self.m_coordinates.next()

    def remove_resource(self, u: int, v: int, to_remove: int, radius: Optional[int] = None, distributed: bool = True) -> None:
        """
        Remove resources from the specified grid cell or within radius.

        Args:
            u: Grid U coordinate
            v: Grid V coordinate
            to_remove: Amount of resource to remove
            radius: Optional radius to remove resources within
            distributed: If True, distribute removal among cells; if False, remove from all cells
        """
        if radius is None:
            # Remove from single cell
            amount = self.get_resource(u, v)

            if amount > to_remove:
                amount -= to_remove
            else:
                amount = 0

            self.set_resource(u, v, amount)
        else:
            # Remove from cells within radius
            remaining = to_remove
            x, y = u, v

            self.m_coordinates.init(radius, x, y, 0, self.m_gridSizeU, 0, self.m_gridSizeV, distributed)
            success, x, y = self.m_coordinates.next()
            while (remaining > 0) and success:
                amount = self.get_resource(x, y)
                remove_amount = min(amount, remaining)

                if remove_amount > 0:
                    amount -= remove_amount
                    if distributed:
                        remaining -= remove_amount
                    self.set_resource(x, y, amount)
                success, x, y = self.m_coordinates.next()

    def get_world_position(self, u: int, v: int) -> Vector3f:
        """
        Get the world position corresponding to grid coordinates.

        Args:
            u: Grid U coordinate
            v: Grid V coordinate

        Returns:
            World position as Vector3f
        """
        # Clamp coordinates to grid bounds
        u_clamped = max(0, min(u, self.m_gridSizeU))
        v_clamped = max(0, min(v, self.m_gridSizeV))

        return Vector3f(
            float(u_clamped) * config.GRID_SIZE,
            float(v_clamped) * config.GRID_SIZE,
            0.0
        )

    def translate(self, direction: Vector3f) -> None:
        """
        Translate the map position.

        Args:
            direction: Direction vector to translate by
        """
        self.m_position += direction

    def execute_rules(self) -> None:
        """Execute map rules for the current simulation step."""
        self.m_ticks += 1  # Increment the tick counter for this map

        for rule in self.m_type.rules:
            # Only execute rules at their specified rate (every N ticks)
            if self.m_ticks % rule.rate() == 0:
                if rule.is_random():
                    # If the rule is random, execute it on a random subset of tiles
                    self.m_randomCoordinates.init(self.m_gridSizeU, self.m_gridSizeV)
                    tiles_amount = rule.percent(self.m_gridSizeU * self.m_gridSizeV)

                    while tiles_amount > 0:
                        # For each randomly selected tile, set context and execute the rule
                        success, u, v = self.m_randomCoordinates.next()
                        if success:
                            self.m_context.u = u
                            self.m_context.v = v
                            rule.execute(self.m_context)
                        tiles_amount -= 1
                else:
                    # Use C++-style decrementing loops for consistency
                    u = self.m_gridSizeU
                    while u > 0:
                        u -= 1  # Decrement at beginning like C++ --u
                        self.m_context.u = u
                        v = self.m_gridSizeV
                        while v > 0:
                            v -= 1  # Decrement at beginning like C++ --v
                            self.m_context.v = v
                            rule.execute(self.m_context)

    # Getter methods
    def type(self) -> str:
        """Get the type name of the map."""
        return self.m_type.name

    def get_map_type(self) -> MapType:
        """Get the map type information."""
        return self.m_type

    def position(self) -> Vector3f:
        """Get the position of the map in world coordinates."""
        return self.m_position

    def grid_size_u(self) -> int:
        """Get the grid size along the U-axis."""
        return self.m_gridSizeU

    def grid_size_v(self) -> int:
        """Get the grid size along the V-axis."""
        return self.m_gridSizeV

    def color(self) -> int:
        """Get the color identifier for rendering."""
        return self.m_type.color

    def get_capacity(self) -> int:
        """Get the maximum capacity per cell for this map."""
        return self.m_type.capacity
