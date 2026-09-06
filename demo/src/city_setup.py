"""
City Setup module for OpenGlassBox demo.

This module handles initialization of demo cities and simulation setup.
"""

from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f

class CitySetup:
    """Handles setting up demo cities for the simulation."""
    
    def __init__(self, simulation: Simulation):
        self.simulation = simulation
        self.unit_types = []
        self.map_types = []
        self.agent_types = []
        self.path_types = []
        self.way_types = []

    def init_demo_cities(self, simfile=None):
        """
        Initialize demo cities.
        
        If simfile is provided, parse it and use the defined types.
        If no simfile, require that types are already defined or fail gracefully.
        """
        # Try to parse scenario file if provided
        if simfile is not None:
            print(f"Parsing simulation file: {simfile}")
            if not self.simulation.parse(simfile):
                print(f"Failed to parse simulation file: {simfile}")
                return False
        else:
            print("No simulation file provided - types must already be defined")

        print("Creating demo cities...")

        # Try to get types from simulation - if they don't exist, we can't proceed
        try:
            grass_type = self.simulation.get_map_type("Grass")
            water_type = self.simulation.get_map_type("Water")
            road_type = self.simulation.get_path_type("Road")
            dirt_type = self.simulation.get_way_type("Dirt")
            home_type = self.simulation.get_unit_type("Home")
            work_type = self.simulation.get_unit_type("Work")
            people_agent_type = self.simulation.get_agent_type("People")
            worker_agent_type = self.simulation.get_agent_type("Worker")
        except KeyError as e:
            print(f"Missing required type: {e}")
            print("Cannot create demo cities without proper types defined")
            return False

        # Store all types for debug panel
        self.unit_types = [home_type, work_type]
        self.map_types = [grass_type, water_type]
        self.agent_types = [people_agent_type, worker_agent_type]
        self.path_types = [road_type]
        self.way_types = [dirt_type]

        # Create Paris city
        paris = self._create_paris_city(grass_type, water_type, road_type, dirt_type, home_type, work_type)
        
        # Create Versailles city
        versailles = self._create_versailles_city(grass_type, water_type, road_type, dirt_type, home_type, work_type, paris)
        
        print("Demo cities created successfully!")
        return True

    def _create_paris_city(self, grass_type, water_type, road_type, dirt_type, home_type, work_type):
        """Create Paris city with its infrastructure."""
        print("Creating Paris...")
        paris = self.simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))

        # Add path and nodes
        road = paris.add_path(road_type)
        n1 = road.add_node(Vector3f(60.0, 60.0, 0.0) + paris.position())
        n2 = road.add_node(Vector3f(300.0, 300.0, 0.0) + paris.position())
        n3 = road.add_node(Vector3f(60.0, 300.0, 0.0) + paris.position())

        # Add ways connecting nodes
        w1 = road.add_way(dirt_type, n1, n2)
        w2 = road.add_way(dirt_type, n2, n3)
        w3 = road.add_way(dirt_type, n3, n1)

        # Add units along the ways
        u1 = paris.add_unit_on_way(home_type, road, w1, 0.66)
        u2 = paris.add_unit_on_way(home_type, road, w1, 0.5)
        u3 = paris.add_unit_on_way(work_type, road, w2, 0.5)
        u4 = paris.add_unit_on_way(work_type, road, w3, 0.5)

        # Add maps
        paris_grass = paris.add_map(grass_type)
        paris_water = paris.add_map(water_type)
        
        return paris

    def _create_versailles_city(self, grass_type, water_type, road_type, dirt_type, home_type, work_type, paris):
        """Create Versailles city with connection to Paris."""
        print("Creating Versailles...")
        versailles = self.simulation.add_city("Versailles", Vector3f(0.0, 30.0, 0.0))

        # Add maps
        vers_grass = versailles.add_map(grass_type)
        vers_water = versailles.add_map(water_type)

        # Add path and nodes
        road2 = versailles.add_path(road_type)
        n4 = road2.add_node(Vector3f(40.0, 20.0, 0.0) + versailles.position())
        n5 = road2.add_node(Vector3f(300.0, 300.0, 0.0) + versailles.position())

        # Get first node from Paris for connection
        paris_road = list(paris.paths().values())[0]
        paris_first_node = paris_road.nodes()[0]

        # Add ways
        w4 = road2.add_way(dirt_type, n4, n5)
        w5 = road2.add_way(dirt_type, n5, paris_first_node)  # Connect to Paris

        # Add units
        u5 = versailles.add_unit_on_way(home_type, paris_road, w5, 0.1)
        u6 = versailles.add_unit_on_way(work_type, road2, w4, 0.8)
        
        return versailles

    def get_type_info(self):
        """Return type information for debug display."""
        return {
            'unit_types': self.unit_types,
            'map_types': self.map_types,
            'agent_types': self.agent_types,
            'path_types': self.path_types,
            'way_types': self.way_types
        }
