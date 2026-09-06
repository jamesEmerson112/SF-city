#!/usr/bin/env python3
"""
Debug script to examine pathfinding logic in detail.
"""

import sys
import os

# Add project root to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from openglassbox.simulation import Simulation
from openglassbox.vector import Vector3f
from openglassbox.dijkstra import Dijkstra

def debug_pathfinding_details():
    """Debug pathfinding logic step by step."""
    print("=== Debugging Pathfinding Logic ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the original TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create a test city
    print(f"\n2. Creating test city...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    grass_type = simulation.get_map_type("Grass")
    water_type = simulation.get_map_type("Water")
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Create the triangle path network
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(60.0, 60.0, 0.0))    # Bottom left
    n2 = road.add_node(Vector3f(300.0, 300.0, 0.0))  # Top right  
    n3 = road.add_node(Vector3f(60.0, 300.0, 0.0))   # Top left
    
    # Connect all nodes in a triangle
    w1 = road.add_way(dirt_type, n1, n2)  # Bottom-left to top-right
    w2 = road.add_way(dirt_type, n2, n3)  # Top-right to top-left
    w3 = road.add_way(dirt_type, n3, n1)  # Top-left to bottom-left
    
    # Add units
    u1 = paris.add_unit_on_way(home_type, road, w1, 0.66)  # Home on way 1
    u2 = paris.add_unit_on_way(home_type, road, w1, 0.5)   # Home on way 1
    u3 = paris.add_unit_on_way(work_type, road, w2, 0.5)   # Work on way 2
    u4 = paris.add_unit_on_way(work_type, road, w3, 0.5)   # Work on way 3
    
    print(f"✓ Created city with {len(paris.units())} units")
    print(f"  Network topology:")
    print(f"    n1 {n1.position()} ← w1 → n2 {n2.position()}")
    print(f"    n2 {n2.position()} ← w2 → n3 {n3.position()}")  
    print(f"    n3 {n3.position()} ← w3 → n1 {n1.position()}")
    print(f"  Unit placement:")
    print(f"    Home u1: way w1 at {u1.position()}")
    print(f"    Home u2: way w1 at {u2.position()}")
    print(f"    Work u3: way w2 at {u3.position()}")
    print(f"    Work u4: way w3 at {u4.position()}")
    
    # Test dijkstra pathfinding manually
    print(f"\n3. Testing Dijkstra pathfinding...")
    dijkstra = Dijkstra()
    
    # Check nodes and their connections
    print(f"\n   Node connectivity:")
    print(f"   n1 has {len(n1.ways())} ways: {[way for way in n1.ways()]}")
    print(f"   n2 has {len(n2.ways())} ways: {[way for way in n2.ways()]}")
    print(f"   n3 has {len(n3.ways())} ways: {[way for way in n3.ways()]}")
    
    # Check units on nodes
    print(f"\n   Units on nodes:")
    print(f"   n1 has {len(n1.units())} units: {[unit for unit in n1.units()]}")
    print(f"   n2 has {len(n2.units())} units: {[unit for unit in n2.units()]}")
    print(f"   n3 has {len(n3.units())} units: {[unit for unit in n3.units()]}")
    
    # Test pathfinding from n1 to find Work units
    print(f"\n   Testing pathfinding from n1 to find 'Work' units...")
    from openglassbox.resources import Resources
    test_resources = Resources()
    
    next_node = dijkstra.find_next_point(n1, "Work", test_resources)
    if next_node:
        print(f"   → Dijkstra found next node: {next_node.position()}")
    else:
        print(f"   → Dijkstra found NO next node!")
    
    # Test from n2
    print(f"\n   Testing pathfinding from n2 to find 'Work' units...")
    next_node = dijkstra.find_next_point(n2, "Work", test_resources)
    if next_node:
        print(f"   → Dijkstra found next node: {next_node.position()}")
    else:
        print(f"   → Dijkstra found NO next node!")
    
    # Check what units accept the "Work" target
    print(f"\n   Checking unit acceptance of 'Work' target:")
    for i, unit in enumerate([u1, u2, u3, u4]):
        print(f"   Unit {i} ({unit.m_type.name}): accepts 'Work'? {unit.accepts('Work', test_resources)}")
    
    # Check if units are properly attached to nodes
    print(f"\n   Checking unit-node attachments:")
    for i, unit in enumerate([u1, u2, u3, u4]):
        node = unit.node()
        if node:
            print(f"   Unit {i} is attached to node at {node.position()}")
            print(f"     Node has {len(node.units())} units attached")
        else:
            print(f"   Unit {i} has NO node attached!")

if __name__ == "__main__":
    debug_pathfinding_details()
