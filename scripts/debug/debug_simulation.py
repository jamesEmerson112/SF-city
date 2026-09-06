#!/usr/bin/env python3
"""
Debug script to test simulation rule execution without the GUI.
This will help us identify what's happening with the rules.
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

def debug_simulation():
    """Debug the simulation to see what's happening with rules."""
    print("=== Debugging OpenGlassBox Simulation ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    print("✓ Successfully parsed simulation file")
    
    # Check what types were parsed
    print(f"\n2. Checking parsed types:")
    print(f"   - Resources: {list(simulation.m_resources.keys())}")
    print(f"   - Agent types: {list(simulation.m_agentTypes.keys())}")
    print(f"   - Unit types: {list(simulation.m_unitTypes.keys())}")
    print(f"   - Map types: {list(simulation.m_mapTypes.keys())}")
    print(f"   - Rule maps: {list(simulation.m_ruleMaps.keys())}")
    print(f"   - Rule units: {list(simulation.m_ruleUnits.keys())}")
    
    # Create cities similar to demo
    print(f"\n3. Creating demo cities...")
    
    # Get types from simulation
    try:
        grass_type = simulation.get_map_type("Grass")
        water_type = simulation.get_map_type("Water")
        road_type = simulation.get_path_type("Road")
        dirt_type = simulation.get_way_type("Dirt") 
        home_type = simulation.get_unit_type("Home")
        work_type = simulation.get_unit_type("Work")
        people_agent_type = simulation.get_agent_type("People")
        worker_agent_type = simulation.get_agent_type("Worker")
        
        print("✓ All types found successfully")
        
        # Check unit type rules
        print(f"\n4. Checking unit type rules:")
        print(f"   - Home unit rules: {[rule.type() for rule in home_type.rules]}")
        print(f"   - Work unit rules: {[rule.type() for rule in work_type.rules]}")
        home_resources = {res.type(): res.get_amount() for res in home_type.resources.container()}
        work_resources = {res.type(): res.get_amount() for res in work_type.resources.container()}
        print(f"   - Home unit resources: {home_resources}")
        print(f"   - Work unit resources: {work_resources}")
        
    except Exception as e:
        print(f"✗ Failed to get types: {e}")
        return False
    
    # Create a test city
    print(f"\n5. Creating test city...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Add paths
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(60.0, 60.0, 0.0) + paris.position())
    n2 = road.add_node(Vector3f(300.0, 300.0, 0.0) + paris.position())
    n3 = road.add_node(Vector3f(60.0, 300.0, 0.0) + paris.position())
    
    w1 = road.add_way(dirt_type, n1, n2)
    w2 = road.add_way(dirt_type, n2, n3)
    w3 = road.add_way(dirt_type, n3, n1)
    
    # Add units
    u1 = paris.add_unit_on_way(home_type, road, w1, 0.66)
    u2 = paris.add_unit_on_way(home_type, road, w1, 0.5)
    u3 = paris.add_unit_on_way(work_type, road, w2, 0.5)
    u4 = paris.add_unit_on_way(work_type, road, w3, 0.5)
    
    print(f"✓ Created city with {len(paris.units())} units")
    
    # Check initial state
    print(f"\n6. Initial state:")
    for i, unit in enumerate(paris.units()):
        unit_resources = {res.type(): res.get_amount() for res in unit.resources().container()}
        print(f"   - Unit {i} ({unit.type()}): resources = {unit_resources}")
    
    print(f"   - Water map initial state: checking some cells...")
    for u in range(0, 5):
        for v in range(0, 5):
            water_amount = paris_water.get_resource(u, v)
            if water_amount > 0:
                print(f"     Water at ({u},{v}): {water_amount}")
    
    # Run simulation for a few steps
    print(f"\n7. Running simulation for 10 steps...")
    for step in range(10):
        print(f"   Step {step + 1}:")
        
        # Update simulation
        simulation.update(1.0 / 200.0)  # One tick
        
        # Check unit resources
        for i, unit in enumerate(paris.units()):
            unit_resources = {res.type(): res.get_amount() for res in unit.resources().container()}
            if unit_resources:  # Only print if unit has resources
                print(f"     Unit {i} ({unit.type()}): {unit_resources}")
        
        # Check agents
        if paris.agents():
            print(f"     Agents: {len(paris.agents())}")
        
        # Check water map changes
        total_water = 0
        for u in range(paris_water.grid_size_u()):
            for v in range(paris_water.grid_size_v()):
                total_water += paris_water.get_resource(u, v)
        if total_water > 0:
            print(f"     Total water on map: {total_water}")
    
    return True

if __name__ == "__main__":
    debug_simulation()
