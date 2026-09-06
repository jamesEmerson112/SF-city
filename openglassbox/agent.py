"""
Agent class for OpenGlassBox simulation engine.

This module defines the Agent class which represents mobile entities that move along paths
and carry resources between Units. Agents are responsible for resource transportation in the
simulation.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import os

from .vector import Vector3f
from .resources import Resources
from .config import TICKS_PER_SECOND


def debug_print(*args, **kwargs):
    """Print debug messages only if OPENGLASSBOX_DEBUG environment variable is set."""
    if os.environ.get('OPENGLASSBOX_DEBUG'):
        print(*args, **kwargs)


@dataclass
class AgentType:
    """Type definition for Agents in the simulation."""
    name: str
    speed: float
    radius: float
    color: int


class Agent:
    """
    Mobile entity that travels along paths carrying resources.

    Agents are created by Units and carry resources from one Unit to another.
    They follow paths and have movement logic to navigate through the simulation.
    """

    def __init__(self, id: int, agent_type: AgentType, owner, resources: Resources, search_target: str):
        """
        Create a new Agent.

        Args:
            id: Unique identifier for the agent
            agent_type: Type of agent (determines speed, capacity, etc)
            owner: The Unit that created this agent
            resources: Resources that the Agent is carrying
            search_target: The type of Unit target (destination)
        """
        self.m_id = id
        self.m_type = agent_type
        self.m_searchTarget = search_target
        self.m_resources = resources
        self.m_position = owner.node().position()
        self.m_offset = 0.0
        self.m_currentWay = None
        self.m_lastNode = owner.node()
        self.m_nextNode = None
        
        # Debug: log initial resources
        debug_print(f"Agent {self.m_id} created with {len(self.m_resources.container())} resources:")
        for resource in self.m_resources.container():
            debug_print(f"  - {resource.type()}: {resource.get_amount()}/{resource.get_capacity()}")
        

    def id(self) -> int:
        """Get the unique identifier of the agent."""
        return self.m_id

    def position(self) -> Vector3f:
        """Get the position of the agent in world coordinates."""
        return self.m_position

    def type(self) -> str:
        """Get the type name of the agent."""
        return self.m_type.name

    def color(self) -> int:
        """Get the color identifier for rendering."""
        return self.m_type.color

    def resources(self) -> List:
        """Get the resources carried by the agent (for debugging)."""
        return self.m_resources.container()

    def translate(self, direction: Vector3f) -> None:
        """
        Translate the agent's position by the given direction vector.

        Args:
            direction: Vector to translate the agent by
        """
        self.m_position += direction

    def update(self, dijkstra) -> bool:
        """
        Update the agent's position and state.

        This method moves the agent along its current way, handles resource transfer,
        and determines next movements.

        Args:
            dijkstra: Pathfinding algorithm instance for route calculation

        Returns:
            True if the agent has completed its task and should be removed, False otherwise
        """
        # Reached the destination node?
        if self.m_nextNode is None:
            debug_print(f"Agent {self.m_id} at node, pos: {self.m_position}, target: {self.m_searchTarget}")
            # Yes! Transfer resources to the Unit.
            # Has Agent no more resource?
            if self._unload_resources():
                # Yes! Return true to remove it!
                debug_print(f"Agent {self.m_id} REMOVED - no more resources after unload")
                return True
            else:
                # No! Keep finding another destination to unload resources.
                debug_print(f"Agent {self.m_id} still has resources, finding next node...")
                self._find_next_node(dijkstra)
                if self.m_nextNode is None:
                    debug_print(f"Agent {self.m_id} FAILED to find next node - will be removed next update")
                else:
                    debug_print(f"Agent {self.m_id} found next node: {self.m_nextNode.position()}")
        else:
            # Move the Agent towards the next Node.
            self._move_towards_next_node()

        return False

    def _search_unit(self):
        """
        Search for a Unit at the current node that accepts the agent's resources.

        Returns:
            Unit that accepts resources or None if none found
        """
        if self.m_lastNode is None:
            return None

        units = self.m_lastNode.units()
        for unit in reversed(units):
            if unit.accepts(self.m_searchTarget, self.m_resources):
                return unit

        return None

    def _unload_resources(self) -> bool:
        """
        Transfer resources to the target Unit.

        Returns:
            True if the agent has no more resources to carry
        """
        unit = self._search_unit()
        debug_print(f"Agent {self.m_id} searching for unit at node {self.m_lastNode.position() if self.m_lastNode else 'None'}, found: {unit is not None}")
        if unit is not None:
            debug_print(f"Agent {self.m_id} transferring resources to unit {unit.type()}")
            self.m_resources.transfer_resources_to(unit.resources())
        else:
            debug_print(f"Agent {self.m_id} no unit found to accept resources")
        is_empty = self.m_resources.is_empty()
        debug_print(f"Agent {self.m_id} resources empty after unload: {is_empty}")
        debug_print(f"Agent {self.m_id} current resources:")
        for resource in self.m_resources.container():
            debug_print(f"  - {resource.type()}: {resource.get_amount()}/{resource.get_capacity()}")
        return is_empty

    def _find_next_node(self, dijkstra) -> None:
        """
        Search for a new Way to reach the destination Node/Unit.

        Args:
            dijkstra: Pathfinding algorithm for finding routes
        """
        if self.m_lastNode is None:
            return

        self.m_nextNode = dijkstra.find_next_point(self.m_lastNode, self.m_searchTarget, self.m_resources)
        if self.m_nextNode is not None:
            self.m_currentWay = self.m_lastNode.get_way_to_node(self.m_nextNode)
            if self.m_currentWay is not None:
                if self.m_lastNode is self.m_currentWay.from_():
                    self.m_offset = 0.0
                else:
                    self.m_offset = 1.0
            else:
                print("failure: getWayToNode")

    def _move_towards_next_node(self) -> None:
        """Move the agent along the current way towards the next node."""
        # Verify the current way exists
        if self.m_currentWay is None:
            print("Ill-formed Node: should have Ways to make Agents move towards them")
            self.m_position = self.m_lastNode.position()
            return

        # Determine direction of movement
        if self.m_nextNode is self.m_currentWay.to():
            # Moving from origin node to destination node
            direction = 1.0
        else:
            # Moving from destination node to origin node
            direction = -1.0

        ticks_per_second = TICKS_PER_SECOND
        self.m_offset += (direction *
                         (self.m_type.speed / ticks_per_second) /
                         self.m_currentWay.magnitude())

        # Check if we've reached one of the end nodes
        if self.m_offset < 0.0:
            self.m_offset = 0.0
            self.m_lastNode = self.m_currentWay.from_()
            self.m_nextNode = None
        elif self.m_offset > 1.0:
            self.m_offset = 1.0
            self.m_lastNode = self.m_currentWay.to()
            self.m_nextNode = None

        # Update the world position of the Agent along the way
        position1 = self.m_currentWay.position1()
        position2 = self.m_currentWay.position2()
        self.m_position = position1 + (position2 - position1) * self.m_offset
