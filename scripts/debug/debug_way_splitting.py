#!/usr/bin/env python3
"""
Debug script to test if way splitting works correctly.
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

def debug_way_splitting():
    """Test if way splitting creates proper network connectivity."""
    print("=== Debugging Way Splitting ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse TestCity to get types
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create a test city
    print(f"\n2. Creating test city...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    
    # Create a simple path network
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))
    n3 = road.add_node(Vector3f(150.0, 200.0, 0.0))
    
    # Connect nodes in a triangle
    w1 = road.add_way(dirt_type, n1, n2)  # Bottom edge
    w2 = road.add_way(dirt_type, n2, n3)  # Right edge
    w3 = road.add_way(dirt_type, n3, n1)  # Left edge
    
    print(f"✓ Created triangle network:")
    print(f"   Initial state: {len(road.nodes())} nodes, {len(road.ways())} ways")
    print(f"   Nodes: n1={n1.position()}, n2={n2.position()}, n3={n3.position()}")
    print(f"   Ways: w1={w1.from_().position()}→{w1.to().position()}")
    print(f"         w2={w2.from_().position()}→{w2.to().position()}")
    print(f"         w3={w3.from_().position()}→{w3.to().position()}")
    
    # Test way splitting - place units on ways
    print(f"\n3. Testing way splitting by placing units...")
    
    # Place Home unit at 50% along w1
    print(f"   Placing Home unit at 50% along w1...")
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.5)
    home_node = home_unit.node()
    
    print(f"   After splitting w1:")
    print(f"     New node count: {len(road.nodes())} (should be 4)")
    print(f"     New way count: {len(road.ways())} (should be 4)")
    print(f"     Home unit at: {home_node.position()}")
    print(f"     Home node connections: {len(home_node.ways())} ways")
    
    # Place Work unit at 75% along w2  
    print(f"   Placing Work unit at 75% along w2...")
    work_unit = paris.add_unit_on_way(work_type, road, w2, 0.75)
    work_node = work_unit.node()
    
    print(f"   After splitting w2:")
    print(f"     New node count: {len(road.nodes())} (should be 5)")
    print(f"     New way count: {len(road.ways())} (should be 5)")
    print(f"     Work unit at: {work_node.position()}")
    print(f"     Work node connections: {len(work_node.ways())} ways")
    
    # Verify network connectivity
    print(f"\n4. Verifying network connectivity...")
    
    # Check all nodes and their connections
    for i, node in enumerate(road.nodes()):
        print(f"   Node {i}: pos={node.position()}, ways={len(node.ways())}, units={len(node.units())}")
        for j, way in enumerate(node.ways()):
            other_node = way.to() if way.from_() is node else way.from_()
            print(f"     → Way {j}: connects to {other_node.position()}")
    
    # Test pathfinding between the split nodes
    print(f"\n5. Testing pathfinding on split network...")
    from openglassbox.dijkstra import Dijkstra
    from openglassbox.resources import Resources
    
    dijkstra = Dijkstra()
    test_resources = Resources()
    test_resources.add_resource("People", 1)
    
    # Can Home node find Work target?
    next_node = dijkstra.find_next_point(home_node, "Work", test_resources)
    if next_node:
        print(f"   ✓ Pathfinding from Home: found target at {next_node.position()}")
        print(f"     Target node has {len(next_node.units())} units")
        for unit in next_node.units():
            print(f"       Unit: {unit.type()}")
    else:
        print(f"   ✗ Pathfinding from Home: NO target found!")
    
    # Can Work node find Home target?
    next_node = dijkstra.find_next_point(work_node, "Home", test_resources)
    if next_node:
        print(f"   ✓ Pathfinding from Work: found target at {next_node.position()}")
        print(f"     Target node has {len(next_node.units())} units")
        for unit in next_node.units():
            print(f"       Unit: {unit.type()}")
    else:
        print(f"   ✗ Pathfinding from Work: NO target found!")
    
    print(f"\n6. Summary:")
    print(f"   Network has {len(road.nodes())} nodes and {len(road.ways())} ways")
    print(f"   Way splitting appears to be working: {'✓' if len(road.nodes()) == 5 else '✗'}")

if __name__ == "__main__":
    debug_way_splitting()
