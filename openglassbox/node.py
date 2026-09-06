"""
Node module for OpenGlassBox simulation engine.

This module defines the Node class which represents connection points
in the transportation network. Nodes can be connected by Ways and
may have Units placed on them.
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
import math

from .vector import Vector3f


@dataclass
class NodeType:
    """Type definition for Nodes in the simulation."""
    name: str
    color: int = 0xFFFFFF


class Node:
    """
    Node class representing vertices in the path graph.

    Nodes define connection points in the transportation network.
    They store their position in the world, track connected Ways,
    and may have Units attached to them.
    """

    def __init__(self, node_id: int, position: Vector3f):
        """
        Initialize a node with ID and position.

        Args:
            node_id: Unique identifier for this node
            position: The node's position in world space
        """
        self.m_id = node_id
        self.m_position = position
        self.m_ways: List[Any] = []  # List of connected Ways
        self.m_units: List[Any] = []  # List of attached Units

    def add_unit(self, unit: Any) -> None:
        """
        Attach a Unit to this node.

        Args:
            unit: The Unit to attach to this node
        """
        self.m_units.append(unit)

    def translate(self, direction: Vector3f) -> None:
        """
        Move the node by the specified direction vector.

        Args:
            direction: Vector representing the direction and magnitude of movement
        """
        self.m_position += direction
        # Update magnitude of all connected ways
        for way in self.m_ways:
            way.update_magnitude()

    def get_way_to_node(self, other_node: 'Node') -> Optional[Any]:
        """
        Find a way connecting this node to another specified node.

        Args:
            other_node: The node to find a connection to

        Returns:
            The Way object connecting the nodes, or None if no connection exists
        """
        for way in self.m_ways:
            if (way.m_from is other_node and way.m_to is self) or \
               (way.m_to is other_node and way.m_from is self):
                return way
        return None

    def has_ways(self) -> bool:
        """
        Check if this node has any ways connected to it.

        Returns:
            True if the node has at least one connected Way, False otherwise
        """
        return len(self.m_ways) > 0

    def get_map_position(self, grid_size_u: int, grid_size_v: int) -> Tuple[int, int]:
        """
        Convert world position to map coordinates.

        Args:
            grid_size_u: The grid size in the U direction
            grid_size_v: The grid size in the V direction

        Returns:
            Tuple of (u, v) map coordinates
        """
        # For simplicity, use a default grid size of 1.0
        GRID_SIZE = 1.0

        u = int(self.m_position.x / GRID_SIZE)
        v = int(self.m_position.y / GRID_SIZE)

        # Clamp to grid bounds
        u = max(0, min(u, grid_size_u - 1))
        v = max(0, min(v, grid_size_v - 1))

        return u, v

    def id(self) -> int:
        """Get the node's unique identifier."""
        return self.m_id

    def position(self) -> Vector3f:
        """Get the node's position in world space."""
        return self.m_position

    def ways(self) -> List[Any]:
        """Get the list of ways connected to this node."""
        return self.m_ways

    def units(self) -> List[Any]:
        """Get the list of units attached to this node."""
        return self.m_units

    def unit(self, index: int) -> Any:
        """Get a specific unit by index."""
        if 0 <= index < len(self.m_units):
            return self.m_units[index]
        return None

    @staticmethod
    def color() -> int:
        """Get the global color for nodes."""
        return 0xAAAAAA
