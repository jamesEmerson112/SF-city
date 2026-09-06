#!/usr/bin/env python3
"""
Debug script to check unit target and resource acceptance logic.
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
from openglassbox.resources import Resources

def debug_unit_targets():
    """Debug unit target acceptance logic."""
    print("=== Debugging Unit Target Acceptance ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Get unit types
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    
    print(f"\n2. Examining unit type definitions:")
    print(f"   Home type:")
    print(f"     - name: {home_type.name}")
    print(f"     - targets: {home_type.targets}")
    print(f"     - capacity: {getattr(home_type, 'capacity', 'N/A')}")
    print(f"     - initial resources: {getattr(home_type, 'resources', 'N/A')}")
    
    print(f"   Work type:")
    print(f"     - name: {work_type.name}")
    print(f"     - targets: {work_type.targets}")
    print(f"     - capacity: {getattr(work_type, 'capacity', 'N/A')}")
    print(f"     - initial resources: {getattr(work_type, 'resources', 'N/A')}")
    
    # Create a simple test setup
    print(f"\n3. Creating test city for unit testing...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    
    # Create a simple path
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Create units
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.25)
    work_unit = paris.add_unit_on_way(work_type, road, w1, 0.75)
    
    print(f"✓ Created units:")
    print(f"   Home unit: {home_unit.type()} at {home_unit.position()}")
    print(f"   Work unit: {work_unit.type()} at {work_unit.position()}")
    
    # Test resource acceptance with different scenarios
    print(f"\n4. Testing unit resource acceptance:")
    
    # Create test resources (what agents would carry)
    people_resources = Resources()
    people_resources.add_resource("People", 1)
    
    empty_resources = Resources()
    
    # Test scenarios
    test_cases = [
        ("Home", "Home", people_resources, "Home unit accepting 'Home' target with People"),
        ("Home", "Work", people_resources, "Home unit accepting 'Work' target with People"),
        ("Work", "Work", people_resources, "Work unit accepting 'Work' target with People"),
        ("Work", "Home", people_resources, "Work unit accepting 'Home' target with People"),
        ("Work", "Work", empty_resources, "Work unit accepting 'Work' target with no resources"),
    ]
    
    for unit_type_name, target, resources, description in test_cases:
        unit = home_unit if unit_type_name == "Home" else work_unit
        result = unit.accepts(target, resources)
        print(f"   {description}: {result}")
        
        # Debug why it failed
        if not result:
            can_add = unit.resources().can_add_some_resources(resources)
            target_match = target in unit.m_type.targets
            print(f"     → can_add_resources: {can_add}")
            print(f"     → target_in_list: {target_match}")
            print(f"     → unit targets: {unit.m_type.targets}")
            print(f"     → unit current resources: {[(res.type(), res.get_amount()) for res in unit.resources().container()]}")
            print(f"     → unit capacity: {getattr(unit.m_type, 'caps', 'N/A')}")
    
    # Test pathfinding integration
    print(f"\n5. Testing pathfinding with correct units:")
    from openglassbox.dijkstra import Dijkstra
    dijkstra = Dijkstra()
    
    # Test if units can be found by pathfinding
    print(f"   Testing if Work units can be found...")
    test_resources = Resources()
    test_resources.add_resource("People", 1)
    
    # Check if units are properly connected to nodes
    print(f"   Unit node connectivity:")
    print(f"     Home unit node: {home_unit.node().position()}")
    print(f"     Home unit node has {len(home_unit.node().units())} units")
    print(f"     Work unit node: {work_unit.node().position()}")
    print(f"     Work unit node has {len(work_unit.node().units())} units")
    
    # Test pathfinding from different positions
    start_node = home_unit.node()
    next_node = dijkstra.find_next_point(start_node, "Work", test_resources)
    if next_node:
        print(f"   → Pathfinding from Home unit found: {next_node.position()}")
        print(f"   → Target node has {len(next_node.units())} units")
    else:
        print(f"   → Pathfinding from Home unit found: NOTHING")

if __name__ == "__main__":
    debug_unit_targets()
