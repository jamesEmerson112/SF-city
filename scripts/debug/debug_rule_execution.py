#!/usr/bin/env python3
"""
Debug script to test rule execution in detail.
This will help us identify what's happening with rule execution.
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

def debug_rule_execution():
    """Debug rule execution in detail."""
    print("=== Debugging Rule Execution ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    print("✓ Successfully parsed simulation file")
    
    # Get the parsed rules and examine them
    print(f"\n2. Examining parsed rules:")
    
    # Check unit rules in detail
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    
    print(f"   Home unit type:")
    print(f"     - Rules count: {len(home_type.rules)}")
    for i, rule in enumerate(home_type.rules):
        print(f"     - Rule {i}: '{rule.type()}' rate={rule.rate()}")
        print(f"       - Commands count: {len(rule.commands())}")
        for j, cmd in enumerate(rule.commands()):
            print(f"         - Command {j}: {cmd.type()}")
    
    print(f"   Work unit type:")
    print(f"     - Rules count: {len(work_type.rules)}")
    for i, rule in enumerate(work_type.rules):
        print(f"     - Rule {i}: '{rule.type()}' rate={rule.rate()}")
        print(f"       - Commands count: {len(rule.commands())}")
        for j, cmd in enumerate(rule.commands()):
            print(f"         - Command {j}: {cmd.type()}")
    
    # Check map rules
    grass_type = simulation.get_map_type("Grass")
    water_type = simulation.get_map_type("Water")
    
    print(f"   Map types:")
    print(f"     - Grass map rules: {len(grass_type.rules)}")
    for i, rule in enumerate(grass_type.rules):
        print(f"       - Rule {i}: '{rule.type()}' rate={rule.rate()}")
    print(f"     - Water map rules: {len(water_type.rules)}")
    
    # Create a test city
    print(f"\n3. Creating test city...")
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Add paths
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
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
    
    # Test rule execution manually on one unit
    print(f"\n4. Testing rule execution manually on Home unit:")
    home_unit = u1  # First home unit
    
    print(f"   Initial state:")
    initial_resources = {res.type(): res.get_amount() for res in home_unit.resources().container()}
    print(f"     - Resources: {initial_resources}")
    print(f"     - Unit tick count: {home_unit.m_ticks}")
    
    # Check if the unit has rules
    print(f"   Unit type rules: {len(home_unit.m_type.rules)}")
    for i, rule in enumerate(home_unit.m_type.rules):
        print(f"     - Rule {i}: {rule.type()} (rate={rule.rate()})")
    
    # Manually execute rule(s) multiple times to reach the rate threshold
    print(f"\n   Testing manual rule execution:")
    print(f"   Rule rate is {home_unit.m_type.rules[0].rate()}, so need {home_unit.m_type.rules[0].rate()} ticks...")
    
    for tick in range(25):  # More than rate=20
        print(f"   Tick {tick + 1}:")
        print(f"     - Before: ticks={home_unit.m_ticks}")
        
        # Call execute_rules manually
        home_unit.execute_rules()
        
        print(f"     - After: ticks={home_unit.m_ticks}")
        
        # Check if resources changed
        current_resources = {res.type(): res.get_amount() for res in home_unit.resources().container()}
        if current_resources != initial_resources:
            print(f"     - Resources CHANGED! {initial_resources} -> {current_resources}")
            initial_resources = current_resources
        
        # Check if agents were created
        if paris.agents():
            print(f"     - Agents created: {len(paris.agents())}")
        
        # If we're at a multiple of the rule rate, we should see execution
        if home_unit.m_ticks % home_unit.m_type.rules[0].rate() == 0:
            print(f"     - This tick should execute rule (tick {home_unit.m_ticks} % rate {home_unit.m_type.rules[0].rate()} == 0)")
    
    return True

if __name__ == "__main__":
    debug_rule_execution()
