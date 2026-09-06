#!/usr/bin/env python3
"""
Debug script to test the complete agent lifecycle.
This will track agents from spawn to destination and back.
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

def debug_agent_lifecycle():
    """Debug the complete agent lifecycle over many ticks."""
    print("=== Debugging Complete Agent Lifecycle ===")
    
    # Create simulation
    simulation = Simulation(12, 12)
    
    # Parse the TestCity.txt file
    simfile = os.path.join(project_root, "demo", "data", "Simulations", "TestCity.txt")
    print(f"\n1. Parsing simulation file: {simfile}")
    if not simulation.parse(simfile):
        print(f"FAILED to parse {simfile}")
        return False
    
    # Create a test city with simplified setup
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
    
    # Add a simple straight path
    road = paris.add_path(road_type)
    n1 = road.add_node(Vector3f(100.0, 100.0, 0.0))  # Home end
    n2 = road.add_node(Vector3f(200.0, 100.0, 0.0))  # Work end
    w1 = road.add_way(dirt_type, n1, n2)
    
    # Add one Home and one Work unit
    home_unit = paris.add_unit_on_way(home_type, road, w1, 0.1)  # Near start
    work_unit = paris.add_unit_on_way(work_type, road, w1, 0.9)  # Near end
    
    print(f"✓ Created city with {len(paris.units())} units")
    print(f"  - Home unit at position: {home_unit.position()}")
    print(f"  - Work unit at position: {work_unit.position()}")
    
    # Initialize water in the map (for the SendPeopleToHome condition)
    print(f"\n3. Initializing water resources...")
    for u in range(paris_water.grid_size_u()):
        for v in range(paris_water.grid_size_v()):
            paris_water.add_resource(u, v, 80)  # Set water > 70
    print(f"✓ Set water levels to 80 (above the required 70)")
    
    # Track state over many ticks
    print(f"\n4. Simulating over 200 ticks...")
    
    for tick in range(200):
        # Record state before update
        home_people = sum(res.get_amount() for res in home_unit.resources().container() if res.type() == "People")
        work_people = sum(res.get_amount() for res in work_unit.resources().container() if res.type() == "People")
        num_agents = len(paris.agents())
        
        # Run one simulation step
        simulation.update(0.016)  # ~60 FPS delta time
        
        # Record state after update
        new_home_people = sum(res.get_amount() for res in home_unit.resources().container() if res.type() == "People")
        new_work_people = sum(res.get_amount() for res in work_unit.resources().container() if res.type() == "People")
        new_num_agents = len(paris.agents())
        
        # Report changes
        if (home_people != new_home_people or 
            work_people != new_work_people or 
            num_agents != new_num_agents or 
            tick % 20 == 0):  # Also report every 20 ticks
            
            print(f"Tick {simulation.get_total_ticks():3d}: Home People: {new_home_people}, Work People: {new_work_people}, Agents: {new_num_agents}")
            
            if num_agents != new_num_agents:
                if new_num_agents > num_agents:
                    print(f"    → Agent SPAWNED")
                else:
                    print(f"    → Agent ARRIVED at destination")
            
            if home_people != new_home_people:
                if new_home_people < home_people:
                    print(f"    → Home lost People ({home_people} -> {new_home_people})")
                else:
                    print(f"    → Home gained People ({home_people} -> {new_home_people})")
            
            if work_people != new_work_people:
                if new_work_people < work_people:
                    print(f"    → Work lost People ({work_people} -> {new_work_people})")
                else:
                    print(f"    → Work gained People ({work_people} -> {new_work_people})")
            
            # Check water levels
            total_water = sum(paris_water.get_resource(u, v) 
                            for u in range(paris_water.grid_size_u()) 
                            for v in range(paris_water.grid_size_v()))
            avg_water = total_water / (paris_water.grid_size_u() * paris_water.grid_size_v())
            if tick % 40 == 0:  # Report water every 40 ticks
                print(f"    → Average water level: {avg_water:.1f}")

if __name__ == "__main__":
    debug_agent_lifecycle()
