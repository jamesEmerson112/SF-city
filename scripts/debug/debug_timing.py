#!/usr/bin/env python3
"""
Debug script to test timing and tick calculation.
"""

import sys
import os

# Add project root to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from openglassbox.simulation import Simulation, TICKS_PER_SECOND
from openglassbox.vector import Vector3f

def debug_timing():
    """Debug timing and tick calculation."""
    print("=== Debugging Simulation Timing ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create test city
    paris = simulation.add_city("Paris", Vector3f(400.0, 200.0, 0.0))
    
    # Get types
    home_type = simulation.get_unit_type("Home")
    work_type = simulation.get_unit_type("Work")
    grass_type = simulation.get_map_type("Grass")
    water_type = simulation.get_map_type("Water")
    road_type = simulation.get_path_type("Road")
    dirt_type = simulation.get_way_type("Dirt")
    
    # Add maps
    paris_grass = paris.add_map(grass_type)
    paris_water = paris.add_map(water_type)
    
    # Add paths and ways
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(60.0, 60.0, 0.0) + paris.position())
    n2 = road.add_node(Vector3f(300.0, 300.0, 0.0) + paris.position())
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Add units
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.5)
    work_unit = paris.add_unit_on_way(work_type, road, w1, 0.66)
    
    print(f"1. Initial setup:")
    print(f"   - Home unit rule rate: {home_unit.m_type.rules[0].rate()}")
    print(f"   - Work unit rule rates: {[rule.rate() for rule in work_unit.m_type.rules]}")
    print(f"   - Simulation TICKS_PER_SECOND: {TICKS_PER_SECOND}")
    print(f"   - Time per tick: {1.0 / TICKS_PER_SECOND}")
    
    initial_home_resources = {res.type(): res.get_amount() for res in home_unit.resources().container()}
    initial_work_resources = {res.type(): res.get_amount() for res in work_unit.resources().container()}
    print(f"   - Initial home resources: {initial_home_resources}")
    print(f"   - Initial work resources: {initial_work_resources}")
    
    print(f"\n2. Running simulation for 25 steps (should be enough for rate=20):")
    for step in range(25):
        print(f"   Step {step + 1}:")
        print(f"     - Before update: home unit ticks = {home_unit.m_ticks}")
        
        # Update simulation
        simulation.update(1.0 / 200.0)  # One tick
        
        print(f"     - After update: home unit ticks = {home_unit.m_ticks}")
        
        # Check resources
        current_home_resources = {res.type(): res.get_amount() for res in home_unit.resources().container()}
        current_work_resources = {res.type(): res.get_amount() for res in work_unit.resources().container()}
        
        if current_home_resources != initial_home_resources:
            print(f"     - Home resources CHANGED! {initial_home_resources} -> {current_home_resources}")
            initial_home_resources = current_home_resources
            
        if current_work_resources != initial_work_resources:
            print(f"     - Work resources CHANGED! {initial_work_resources} -> {current_work_resources}")
            initial_work_resources = current_work_resources
        
        # Check agents
        if paris.agents():
            print(f"     - Agents in city: {len(paris.agents())}")
        
        # Check if this step should trigger the SendPeopleToWork rule
        if home_unit.m_ticks % home_unit.m_type.rules[0].rate() == 0 and home_unit.m_ticks > 0:
            print(f"     - This step should have executed SendPeopleToWork rule!")
    
    return True

if __name__ == "__main__":
    debug_timing()
