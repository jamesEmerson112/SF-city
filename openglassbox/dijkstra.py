"""
Dijkstra module for OpenGlassBox simulation engine.

This module implements the Dijkstra pathfinding algorithm used for finding routes
between nodes in the transportation network. It is used primarily by agents to
navigate between locations when carrying resources.
"""

from typing import Dict, List, Optional, Set, Any
import random
import sys
from .node import Node
from .resources import Resources
from .vector import Vector3D


class Dijkstra:
    """
    Dijkstra class for pathfinding in the transportation network.

    This algorithm is used to find paths between nodes in the transportation
    network. It uses a heuristic-enhanced implementation to find not just the
    shortest path, but paths to nodes that have units with specific resources.
    """

    def __init__(self):
        """Initialize the Dijkstra pathfinder with empty data structures."""
        self.m_closed_set: Set[Node] = set()
        self.m_open_set: List[Node] = []
        self.m_came_from: Dict[Node, Node] = {}
        self.m_score_from_start: Dict[Node, float] = {}
        self.m_score_plus_heuristic_from_start: Dict[Node, float] = {}

    def find_next_point(self, from_node: Node, search_target: str, resources: Resources) -> Optional[Node]:
        """
        Find the next node to move to when trying to reach a destination.

        This method calculates the best next node to move to when trying to reach
        a target. It considers both the distance and whether nodes have units
        that accept the specified resource type.

        Args:
            from_node: The starting node
            search_target: The target resource type to search for
            resources: The resources being carried or considered for the search

        Returns:
            The next node to move to, or None if no path is available
        """
        # Clear our collections
        self.m_closed_set.clear()
        self.m_open_set.clear()
        self.m_came_from.clear()
        self.m_score_from_start.clear()
        self.m_score_plus_heuristic_from_start.clear()

        # Start the search from the starting node
        self.m_open_set.append(from_node)
        self.m_score_from_start[from_node] = 0.0
        self.m_score_plus_heuristic_from_start[from_node] = 0.0

        while len(self.m_open_set) > 0:
            # Get the node with lowest score
            current = self._get_point_with_lowest_score_plus_heuristic_from_start()
            if current is None:
                break

            # Check if we've reached a target
            if self._get_unit_with_target_and_capacity(current, search_target, resources):
                # If we started at the target, we're already there
                if current is from_node:
                    return current

                # Otherwise, reconstruct the path back to the start and return the next step
                while self.m_came_from[current] is not from_node:
                    current = self.m_came_from[current]

                return current

            # Process the current node
            self.m_open_set.remove(current)
            self.m_closed_set.add(current)

            # Examine all connected ways/nodes
            for way in current.ways():
                # Get the neighbor node (the node at the other end of the way)
                neighbor = way.to() if way.from_() is current else way.from_()

                # Calculate tentative score to this neighbor
                neighbor_score_from_start = self.m_score_from_start[current] + way.magnitude()

                # If this node is in the closed set and we don't have a better path, skip it
                if neighbor in self.m_closed_set:
                    if neighbor_score_from_start >= self.m_score_from_start.get(neighbor, float('inf')):
                        continue

                # If we found a better path to this neighbor, update it
                if neighbor not in self.m_open_set or neighbor_score_from_start < self.m_score_from_start.get(neighbor, float('inf')):
                    # Update or set the path and scores
                    self.m_came_from[neighbor] = current
                    self.m_score_from_start[neighbor] = neighbor_score_from_start
                    self.m_score_plus_heuristic_from_start[neighbor] = (
                        neighbor_score_from_start + self._heuristic(neighbor, from_node)
                    )

                    # Add to open set if not already there
                    if neighbor not in self.m_open_set:
                        self.m_open_set.append(neighbor)

        # No path found - return a random connected node as fallback
        if from_node.ways():
            random_way = random.choice(from_node.ways())
            if random_way.from_() is from_node:
                return random_way.to()
            elif random_way.to() is from_node:
                return random_way.from_()

        return None

    # Alias for C++ compatibility
    findNextPoint = find_next_point

    def _get_point_with_lowest_score_plus_heuristic_from_start(self) -> Optional[Node]:
        """
        Find the node with the lowest combined score in the open set.

        Returns:
            The node with lowest score, or None if no nodes are available
        """
        lowest_value = float('inf')
        lowest_point = None

        # Find node with lowest score
        for point, score in self.m_score_plus_heuristic_from_start.items():
            if score < lowest_value:
                lowest_value = score
                lowest_point = point

        # Remove the found point from the heuristic scores dict to avoid re-processing
        if lowest_point is not None:
            del self.m_score_plus_heuristic_from_start[lowest_point]

        return lowest_point

    def _heuristic(self, p1: Node, p2: Node) -> float:
        """
        Calculate the heuristic distance between two nodes.

        Args:
            p1: First node
            p2: Second node

        Returns:
            The squared distance between the nodes as a heuristic value
        """
        # Calculate squared distance (faster than using magnitude which requires sqrt)
        vec = p2.position() - p1.position()
        return vec.x * vec.x + vec.y * vec.y + vec.z * vec.z

    @staticmethod
    def _get_unit_with_target_and_capacity(current: Node, search_target: str, resources: Resources) -> bool:
        """
        Check if a node has any units that accept the specified resource.

        Args:
            current: The node to check
            search_target: The resource type being searched for
            resources: The resources to check capacity against

        Returns:
            True if there's a unit that accepts the resource, False otherwise
        """
        for unit in current.units():
            if unit.accepts(search_target, resources):
                return True

        return False
