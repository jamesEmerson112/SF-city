"""
City class for OpenGlassBox simulation engine.

This module defines the City class which acts as the central container and coordinator
for the simulation. A City contains Maps, Paths, Units, and Agents, and manages their
interactions.
"""

from typing import Dict, List, Optional, Tuple, Any

from .vector import Vector3f
from .resources import Resources
from .map import MapType
from .path import PathType
from .script_parser import UnitType


class City:
    """
    Container class for all simulation elements.

    The City manages Maps, Paths, Units, and Agents, and coordinates their interactions.
    It also handles spatial conversions between world and grid coordinates.
    """

    class Listener:
        """
        Listener interface for City events.

        This class can be subclassed to implement callbacks for entity addition/removal.
        """

        def on_map_added(self, map_obj):
            """Called when a Map is added to the City."""
            pass

        def on_map_removed(self, map_obj):
            """Called when a Map is removed from the City."""
            pass

        def on_path_added(self, path):
            """Called when a Path is added to the City."""
            pass

        def on_path_removed(self, path):
            """Called when a Path is removed from the City."""
            pass

        def on_unit_added(self, unit):
            """Called when a Unit is added to the City."""
            pass

        def on_unit_removed(self, unit):
            """Called when a Unit is removed from the City."""
            pass

        def on_agent_added(self, agent):
            """Called when an Agent is added to the City."""
            pass

        def on_agent_removed(self, agent):
            """Called when an Agent is removed from the City."""
            pass

        def on_map_update(self, map_obj):
            """Called when a Map is updated during a simulation step."""
            pass

        def on_unit_update(self, unit):
            """Called when a Unit is updated during a simulation step."""
            pass

    def __init__(self, name: str, *args):
        """
        Create a new City.

        Args:
            name: Name of the city
            *args: Variable arguments depending on the constructor:
                - No args: Creates a 32x32 city at position (0,0,0)
                - (grid_size_u, grid_size_v): Creates a city with the given dimensions at (0,0,0)
                - (position, grid_size_u, grid_size_v): Creates a city at the given position
        """
        self.m_name = name

        if len(args) == 0:
            # Default constructor
            self.m_position = Vector3f(0.0, 0.0, 0.0)
            self.m_gridSizeU = 32
            self.m_gridSizeV = 32
        elif len(args) == 2 and isinstance(args[0], int) and isinstance(args[1], int):
            # Constructor with grid dimensions
            self.m_position = Vector3f(0.0, 0.0, 0.0)
            self.m_gridSizeU = args[0]
            self.m_gridSizeV = args[1]
        elif len(args) == 3 and isinstance(args[0], Vector3f):
            # Constructor with position and grid dimensions
            self.m_position = args[0]
            self.m_gridSizeU = args[1]
            self.m_gridSizeV = args[2]
        else:
            raise ValueError("Invalid arguments for City constructor")

        # Initialize collections
        self.m_nextAgentId = 0
        self.m_globals = Resources()
        self.m_maps = {}  # Dict[str, Map]
        self.m_paths = {}  # Dict[str, Path]
        self.m_units = []  # List[Unit]
        self.m_agents = []  # List[Agent]

        # Initialize Dijkstra pathfinding
        from .dijkstra import Dijkstra
        self.m_dijkstra = Dijkstra()

        # Create default listener
        self.m_listener = City.Listener()

    def set_listener(self, listener: 'City.Listener') -> None:
        """
        Set a listener for city events.

        Args:
            listener: A City.Listener instance to receive events
        """
        self.m_listener = listener

    def update(self) -> None:
        """
        Update all entities in the city for one simulation step.

        This method:
        1. Updates all agents and removes completed ones
        2. Executes rules for all units
        3. Executes rules for all maps
        """
        # Process agents from the end of the list for easier removal
        i = len(self.m_agents) - 1
        while i >= 0:
            if self.m_agents[i].update(self.m_dijkstra):
                # Agent completed its task, swap with last and remove
                self.m_agents[i], self.m_agents[-1] = self.m_agents[-1], self.m_agents[i]
                removed_agent = self.m_agents.pop()
                self.m_listener.on_agent_removed(removed_agent)
            i -= 1

        # Update all units
        for unit in reversed(self.m_units):
            unit.execute_rules()
            self.m_listener.on_unit_update(unit)

        # Update all maps
        for map_name, map_obj in self.m_maps.items():
            map_obj.execute_rules()
            self.m_listener.on_map_update(map_obj)

    def translate(self, direction: Vector3f) -> None:
        """
        Translate the position of the city and all its contents.

        Args:
            direction: Vector to translate the city by
        """
        # Since the city position is used as a reference for map positions,
        # we need to update the city position first, then translate
        # paths, nodes, and agents relative to the city
        self.m_position += direction

        # Translate paths (which will translate nodes and ways)
        for path_name, path in self.m_paths.items():
            path.translate(direction)

        # Translate agents
        for agent in self.m_agents:
            agent.translate(direction)

        # Note: Units are attached to Path Nodes, so they are translated indirectly
        # Note: Maps inherit their position from the city, so we don't need to translate them

    def world2mapPosition(self, world_pos: Vector3f, u_out: List[int], v_out: List[int]) -> None:
        """
        Convert a world position to map grid coordinates.

        Args:
            world_pos: Position in world coordinates
            u_out: Output list to store the U grid coordinate
            v_out: Output list to store the V grid coordinate
        """
        # Clear output lists and add new values (simulating C++ reference parameters)
        u_out.clear()
        v_out.clear()

        # For simplicity, we'll assume GRID_SIZE = 1.0 here
        GRID_SIZE = 1.0  # This should come from a config module

        x = (world_pos.x - self.m_position.x) / GRID_SIZE
        y = (world_pos.y - self.m_position.y) / GRID_SIZE

        # Clamp values to grid boundaries
        if x < 0.0:
            u = 0
        elif int(x) >= self.m_gridSizeU:
            u = self.m_gridSizeU - 1
        else:
            u = int(x)

        if y < 0.0:
            v = 0
        elif int(y) >= self.m_gridSizeV:
            v = self.m_gridSizeV - 1
        else:
            v = int(y)

        u_out.append(u)
        v_out.append(v)

    def add_map(self, map_type: MapType):
        """
        Add a new Map to the city.

        Args:
            map_type: Type definition for the map

        Returns:
            The newly created Map
        """
        # Import here to avoid circular imports
        from .map import Map

        new_map = Map(map_type, self)
        self.m_maps[map_type.name] = new_map
        self.m_listener.on_map_added(new_map)
        print(f"Map {map_type.name} added")
        return new_map

    def get_map(self, map_id: str):
        """
        Get a map by its identifier.

        Args:
            map_id: Name of the map to retrieve

        Returns:
            The requested Map

        Raises:
            KeyError: If the map does not exist
        """
        return self.m_maps[map_id]

    def add_path(self, path_type: PathType):
        """
        Add a new Path to the city.

        Args:
            path_type: Type definition for the path

        Returns:
            The newly created Path
        """
        # Import here to avoid circular imports
        from .path import Path

        new_path = Path(path_type)
        self.m_paths[path_type.name] = new_path
        self.m_listener.on_path_added(new_path)
        print(f"Path {path_type.name} added")
        return new_path

    def get_path(self, path_id: str):
        """
        Get a path by its identifier.

        Args:
            path_id: Name of the path to retrieve

        Returns:
            The requested Path

        Raises:
            KeyError: If the path does not exist
        """
        return self.m_paths[path_id]

    def add_unit(self, unit_type: UnitType, node):
        """
        Add a new Unit to the city at the given node.

        Args:
            unit_type: Type definition for the unit
            node: The node to attach the unit to

        Returns:
            The newly created Unit
        """
        # Import here to avoid circular imports
        from .unit import Unit

        new_unit = Unit(unit_type, node, self)
        self.m_units.append(new_unit)
        self.m_listener.on_unit_added(new_unit)
        return new_unit

    def add_unit_on_way(self, unit_type: UnitType, path, way, offset: float):
        """
        Add a new Unit to the city by splitting a way and creating a new node.

        Args:
            unit_type: Type definition for the unit
            path: The path containing the way
            way: The way to split
            offset: Position along the way (0.0 to 1.0)

        Returns:
            The newly created Unit
        """
        new_node = path.split_way(way, offset)
        return self.add_unit(unit_type, new_node)

    def add_agent(self, agent_type, owner, resources: Resources, search_target: str):
        """
        Add a new Agent to the city.

        Args:
            agent_type: Type definition for the agent
            owner: The unit that created/owns the agent
            resources: Resources that the agent carries (will be copied for each agent)
            search_target: Type of unit the agent is looking for

        Returns:
            The newly created Agent
        """
        # Import here to avoid circular imports
        from .agent import Agent

        # Create a deep copy of resources for each agent to avoid sharing
        agent_resources = Resources()
        agent_resources.add_resources(resources)
        
        new_agent = Agent(self.m_nextAgentId, agent_type, owner, agent_resources, search_target)
        self.m_nextAgentId += 1
        self.m_agents.append(new_agent)
        self.m_listener.on_agent_added(new_agent)
        return new_agent

    # Getters
    def name(self) -> str:
        """Get the name of the city."""
        return self.m_name

    def position(self) -> Vector3f:
        """Get the position of the city in world coordinates."""
        return self.m_position

    def grid_size_u(self) -> int:
        """Get the grid size along the U-axis."""
        return self.m_gridSizeU

    def grid_size_v(self) -> int:
        """Get the grid size along the V-axis."""
        return self.m_gridSizeV

    def globals(self) -> Resources:
        """Get the global resources for the city."""
        return self.m_globals

    def maps(self) -> Dict:
        """Get the maps collection."""
        return self.m_maps

    def paths(self) -> Dict:
        """Get the paths collection."""
        return self.m_paths

    def units(self) -> List:
        """Get the units collection."""
        return self.m_units

    def agents(self) -> List:
        """Get the agents collection."""
        return self.m_agents
